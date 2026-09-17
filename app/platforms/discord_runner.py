import os
import asyncio
import shutil
import re
import random
import sys
import time

# Allow running this file directly (python app/platforms/discord_runner.py), on
# its own, sys.path[0] is app/platforms/ and the app package isn't importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
import app.utils.ai as ai_module

# ── Engine import ─────────────────────────────────────────────────────────────
# Discord keeps its own generate_response_and_reply() for Discord-specific
# behaviour (typing, files, voice, TTS); the Snapchat bridge uses
# core.engine.generate_ai_response() directly. Both share the utils/ layer.
from app.core.engine import is_refusal, style_block, reaction_rules  # reuse refusal list instead of duplicating
from app.utils.humanize import strip_meta, add_typo
from app.utils.pictures import is_picture_request

from app.utils.helpers import (
    clear_console,
    resource_path,
    get_env_path,
    load_instructions,
    load_config,
    load_tokens,
    france_time_str,
)

from app.utils.db import init_db, get_channels, get_ignored_users, add_unresponded, mark_responded, mark_nudge_sent, get_pending_nudges, get_all_picture_descriptions, record_user_message, get_cached_profile, set_cached_profile
from app.utils.error_notifications import notify_telegram_error
from colorama import init, Fore, Style

from app.utils.logger import (
    log_incoming,
    log_response,
    log_rate_limit,
    log_error,
    log_system,
    log_received,
    separator,
    set_theme,
)

from curl_cffi.requests import AsyncSession

from app.utils.session import (
    build_session,
    set_default_proxy,
    set_gateway_headers,
    build_desktop_headers,
)
from app.utils.behavior import (
    typing_speed,
    typing_time,
    typing_bursts,
    parse_reaction_tag,
    reaction_emojis,
    night_window_state,
    style_chunk_split,
    tiny_typo_fix,
)
from app.utils.ratelimit import SlidingWindow
from app.utils.mood import get_mood_prompt, mood_loop, shift_mood
from app.utils.memory import init_memory, get_memory, set_memory, delete_memory, format_memory_for_prompt, get_persona
from app.utils.tts import generate_voice_message
from app.utils.tts_trigger import is_tts_request
from app.utils.voice_send import send_voice_message

# Smooths bulk sweeps only, normal chat never comes close to these caps.
_profile_fetch_budget = SlidingWindow(limit=20, window_seconds=3600)
_history_scan_budget = SlidingWindow(limit=60, window_seconds=3600)


def history_scan_allowed() -> bool:
    """True when a REST message-history fetch fits in the hourly budget."""
    return _history_scan_budget.allow()


def profile_fetch_allowed() -> bool:
    """True when a fresh user.profile() fetch fits in the hourly budget."""
    return _profile_fetch_budget.allow()


init()
set_theme("discord")


def get_batch_wait_time():
    wait_times = config["bot"]["batch_wait_times"]
    times = [item["time"] for item in wait_times]
    weights = [item["weight"] for item in wait_times]
    return random.choices(times, weights=weights, k=1)[0]


config = load_config()

from app.utils.ai import init_ai, generate_response, generate_response_image, extract_memory, detect_memory_deletion, transcribe_voice, summarize_history, detect_language, generate_nudge, reset_client_index, fallback_model
from dotenv import load_dotenv
from discord.ext import commands
from app.utils.split_response import split_response
from datetime import datetime
from collections import deque
from asyncio import Lock

env_path = get_env_path()

load_dotenv(dotenv_path=env_path, override=True)

init_db()
init_ai()
init_memory()

TOKENS = load_tokens()

# Which account this process drives (1-based). Multi-account runs spawn one
# child per token with DISCORD_ACCOUNT_INDEX set; a single account is always #1.
_PINNED_ACCOUNT = os.getenv("DISCORD_ACCOUNT_INDEX")  # set only in a per-account child
try:
    ACCOUNT_INDEX = min(max(1, int(_PINNED_ACCOUNT or 1)), len(TOKENS))
except ValueError:
    ACCOUNT_INDEX = 1
os.environ["DISCORD_ACCOUNT_INDEX"] = str(ACCOUNT_INDEX)  # picked up by the error relay
ACCOUNT_TOKEN = TOKENS[ACCOUNT_INDEX - 1]

# One IP for gateway and REST alike: every build_session() call falls back to
# this account proxy unless the caller overrides it.
set_default_proxy(ACCOUNT_TOKEN.get("proxy"))

PREFIX = config["bot"]["prefix"]
OWNER_ID = config["bot"]["owner_id"]
TRIGGER = config["bot"]["trigger"].lower().split(",")


def _compile_triggers(words):
    """One compiled alternation for all trigger words.

    Matching ran re.escape() and built a pattern per keyword, against a freshly
    lowercased copy of the message, for every message the account saw - not
    just the ones it answered.

    The words are used exactly as config gives them, NOT stripped or filtered:
    "John, Jon" splits to ["john", " jon"], and that leading space is part of
    what the old per-keyword search matched on. An alternation of the same
    escaped words is equivalent to any() over the same individual searches, so
    this is a speed change only. (Two consequences of that are worth knowing
    about, but they are pre-existing and not for this change to alter: a word
    with a leading space will not match at the very start of a message, and an
    empty word - from a trailing comma - matches every message.)
    """
    if not words:
        return None
    parts = [re.escape(w) for w in words]
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


TRIGGER_RE = _compile_triggers(TRIGGER)
DISABLE_MENTIONS = config["bot"]["disable_mentions"]
PRIORITY_PREFIX = config["bot"]["priority_prefix"]

SPAM_MESSAGE_THRESHOLD = 5
SPAM_TIME_WINDOW = 10.0
COOLDOWN_DURATION = 60.0
MAX_HISTORY = 15
IGNORE_CHANCE = config["bot"]["ignore_chance"]
CONVERSATION_TIMEOUT = 150.0

# Whether keyword triggers / real @mentions skip the random ignore_chance roll
TRIGGER_BYPASSES_IGNORE = config["bot"].get("trigger_bypasses_ignore", True)
MENTION_BYPASSES_IGNORE = config["bot"].get("mention_bypasses_ignore", True)

# Whether to enforce a random gap between any two replies (global, not per-user).
# Disable for a personal/single-user bot.
GLOBAL_COOLDOWN_ENABLED = config["bot"].get("global_cooldown_enabled", True)
GLOBAL_COOLDOWN_MIN = config["bot"].get("global_cooldown_min", 45)
GLOBAL_COOLDOWN_MAX = config["bot"].get("global_cooldown_max", 120)

# Wait window for follow-up messages before the batch is treated as complete.
BATCH_TAIL_WAIT_MIN = config["bot"].get("batch_tail_wait_min", 1.5)
BATCH_TAIL_WAIT_MAX = config["bot"].get("batch_tail_wait_max", 7.0)

# Simulated "reading" delay before typing, per channel type.
READ_DELAY_DM_MIN = config["bot"].get("read_delay_dm_min", 2.5)
READ_DELAY_DM_MAX = config["bot"].get("read_delay_dm_max", 8.0)
READ_DELAY_GROUP_MIN = config["bot"].get("read_delay_group_min", 1.5)
READ_DELAY_GROUP_MAX = config["bot"].get("read_delay_group_max", 5.0)
READ_DELAY_SERVER_MIN = config["bot"].get("read_delay_server_min", 1.0)
READ_DELAY_SERVER_MAX = config["bot"].get("read_delay_server_max", 4.0)

_MOOD_CFG = config["bot"]["mood"]
_LATE_CFG = config["bot"]["late_reply"]
_STALE_CFG = config["bot"].get("stale_reply") or {}


def refresh_config(bot=None) -> None:
    """Re-read config.yaml into everything cached above.

    These were read once at import, so changing a timing or a chance in the
    panel did nothing until the account was restarted. load_config() is
    mtime-cached, so re-reading is cheap and picks the new file up at once.
    """
    global config, PREFIX, OWNER_ID, TRIGGER, DISABLE_MENTIONS, PRIORITY_PREFIX
    global IGNORE_CHANCE, TRIGGER_BYPASSES_IGNORE, MENTION_BYPASSES_IGNORE
    global GLOBAL_COOLDOWN_ENABLED, GLOBAL_COOLDOWN_MIN, GLOBAL_COOLDOWN_MAX
    global BATCH_TAIL_WAIT_MIN, BATCH_TAIL_WAIT_MAX
    global READ_DELAY_DM_MIN, READ_DELAY_DM_MAX
    global READ_DELAY_GROUP_MIN, READ_DELAY_GROUP_MAX
    global READ_DELAY_SERVER_MIN, READ_DELAY_SERVER_MAX
    global _MOOD_CFG, _LATE_CFG, _STALE_CFG

    from app.utils.helpers import invalidate_config_cache
    invalidate_config_cache()
    config = load_config()
    b = config["bot"]

    PREFIX = b["prefix"]
    OWNER_ID = b["owner_id"]
    TRIGGER = b["trigger"].lower().split(",")
    global TRIGGER_RE
    TRIGGER_RE = _compile_triggers(TRIGGER)
    DISABLE_MENTIONS = b["disable_mentions"]
    PRIORITY_PREFIX = b["priority_prefix"]
    IGNORE_CHANCE = b["ignore_chance"]
    TRIGGER_BYPASSES_IGNORE = b.get("trigger_bypasses_ignore", True)
    MENTION_BYPASSES_IGNORE = b.get("mention_bypasses_ignore", True)
    GLOBAL_COOLDOWN_ENABLED = b.get("global_cooldown_enabled", True)
    GLOBAL_COOLDOWN_MIN = b.get("global_cooldown_min", 45)
    GLOBAL_COOLDOWN_MAX = b.get("global_cooldown_max", 120)
    BATCH_TAIL_WAIT_MIN = b.get("batch_tail_wait_min", 1.5)
    BATCH_TAIL_WAIT_MAX = b.get("batch_tail_wait_max", 7.0)
    READ_DELAY_DM_MIN = b.get("read_delay_dm_min", 2.5)
    READ_DELAY_DM_MAX = b.get("read_delay_dm_max", 8.0)
    READ_DELAY_GROUP_MIN = b.get("read_delay_group_min", 1.5)
    READ_DELAY_GROUP_MAX = b.get("read_delay_group_max", 5.0)
    READ_DELAY_SERVER_MIN = b.get("read_delay_server_min", 1.0)
    READ_DELAY_SERVER_MAX = b.get("read_delay_server_max", 4.0)
    _MOOD_CFG = b["mood"]
    _LATE_CFG = b["late_reply"]
    _STALE_CFG = b.get("stale_reply") or {}

    if bot is not None:
        bot.command_prefix = PREFIX
        bot.owner_id = OWNER_ID
        bot.allow_dm = b["allow_dm"]
        bot.allow_gc = b["allow_gc"]
        bot.allow_server = b.get("allow_server", True)
        bot.realistic_typing = b["realistic_typing"]
        bot.anti_age_ban = b["anti_age_ban"]
        bot.disable_mentions = DISABLE_MENTIONS
        bot.batch_messages = b["batch_messages"]
        for attr, key in (("hold_conversation", "hold_conversation"),
                          ("reply_ping", "reply_ping"),
                          ("read_bios", "read_bios")):
            if key in b:
                setattr(bot, attr, b[key])

# REFUSAL_PHRASES and is_refusal() are imported from app.core.engine above


async def _apply_client_profile():
    """Align the whole process (gateway identify + every REST call) on one
    client profile: the desktop app when client_profile=desktop, otherwise
    the gateway's own live web headers.

    Runs from setup_hook, i.e. after login/startup (headers fetched) and
    before the gateway connects - the websocket picks bot.http.headers up
    right after this, so the IDENTIFY super-properties match automatically.
    """
    from app.utils import session as session_mod
    profile = getattr(bot, "client_profile", "web")
    try:
        live = bot.http.headers
    except Exception:
        live = None
    try:
        if profile == "desktop":
            hdr = await session_mod.build_desktop_headers(config, live)
            bot.http.headers = hdr
            session_mod.set_gateway_headers(hdr)
        elif live is not None:
            session_mod.set_gateway_headers(live)
    except Exception as e:
        log_error("Client Profile", str(e))
    # One visible line per login: the fingerprint every REST call and the
    # next IDENTIFY will carry. Check the log if the profile indicator looks
    # wrong, this tells you exactly what was sent.
    try:
        props = bot.http.headers.super_properties
        log_system(
            f"Client profile: {profile} | browser={props.get('browser')} "
            f"build={props.get('client_build_number')} "
            f"channel={props.get('release_channel')} "
            f"ua={str(bot.http.headers.user_agent)[:80]}"
        )
    except Exception:
        pass
    tz = config["bot"].get("timezone")
    if tz:
        try:
            bot.http.timezone = tz
        except Exception:
            pass
    session_mod.set_default_proxy(ACCOUNT_TOKEN.get("proxy"))


def create_bot() -> commands.Bot:
    """Instantiate a fully configured bot for this process's account."""
    kwargs = {"command_prefix": PREFIX, "help_command": None}
    if ACCOUNT_TOKEN.get("proxy"):
        kwargs["proxy"] = ACCOUNT_TOKEN["proxy"]
    b = commands.Bot(**kwargs)
    b.client_profile = config["bot"].get("client_profile", "web")
    b._react_only_count = 0
    b._reply_total = 0
    b.retry_queue = deque()
    b.owner_id = OWNER_ID
    b.active_channels = set(get_channels())
    b.ignore_users = get_ignored_users()
    b.message_history = {}
    b.paused = False
    b.allow_dm = config["bot"]["allow_dm"]
    b.allow_gc = config["bot"]["allow_gc"]
    b.allow_server = config["bot"].get("allow_server", True)
    b.realistic_typing = config["bot"]["realistic_typing"]
    b.anti_age_ban = config["bot"]["anti_age_ban"]
    b.disable_mentions = DISABLE_MENTIONS
    b.batch_messages = config["bot"]["batch_messages"]
    b.hold_conversation = config["bot"]["hold_conversation"]
    b.user_message_counts = {}
    b.user_cooldowns = {}
    b.instructions = load_instructions()
    b.message_queues = {}
    b.processing_locks = {}
    b.user_message_batches = {}
    b.active_conversations = {}
    b.last_sent_picture = {}
    b._memory_cache = {}
    b.paused_users = set()
    b.removed_friends = set()  # previously-friend user IDs (for instant re-add)
    # Global send lock: one message sent at a time across ALL users.
    b.global_send_lock = Lock()
    b.last_global_send = 0.0  # timestamp of last sent message across all users
    b._lang_cache = {}  # uid -> {"tag": str, "count": int}
    return b


bot = create_bot()

def get_channel_context(message):
    """Returns (channel_name, guild_name) with proper DM/GC labels."""
    if isinstance(message.channel, discord.GroupChannel):
        channel_name = getattr(message.channel, 'name', None) or "GC"
        guild_name = "GC"
    elif isinstance(message.channel, discord.DMChannel):
        channel_name = "DM"
        guild_name = "DM"
    else:
        channel_name = getattr(message.channel, 'name', 'unknown')
        guild_name = getattr(message.guild, 'name', 'unknown')
    return channel_name, guild_name


def get_late_opener(prompt: str) -> str:
    late_cfg = config["bot"]["late_reply"]
    french_indicators = late_cfg.get("french_indicators", [])
    prompt_lower = prompt.lower()
    is_french = any(word in prompt_lower.split() for word in french_indicators)
    openers = late_cfg["openers_fr"] if is_french else late_cfg["openers_en"]
    return random.choice(openers)


async def _simulate_typing(channel, text: str, fast: bool = False):
    """Type `text` at human speed (2.5-6 cps normal, 4-8 fast) in short
    bursts with occasional think-pauses. The typing indicator stays up the
    whole time; Discord only clears it ~10s after the last refresh."""
    total = typing_time(text, fast)
    for burst, pause in typing_bursts(total, fast):
        async with channel.typing():
            await asyncio.sleep(burst)
        if pause:
            await asyncio.sleep(pause)


async def _maybe_edit_after_send(sent_msg, original: str):
    """Rare human behaviour: fix a small slip right after sending."""
    try:
        await asyncio.sleep(random.uniform(3, 15))
        fixed = tiny_typo_fix(original)
        if fixed and fixed != original:
            await sent_msg.edit(content=fixed)
            log_system("Edited sent message (typo fix)")
    except Exception:
        pass


async def _cleanup_loop():
    """Periodically prune unbounded in-memory dicts to prevent slow memory leaks."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)  # run every hour
        now = time.time()
        # Prune spam counters for users quiet for > 5 minutes
        stale_counts = [uid for uid, times in bot.user_message_counts.items()
                        if not times or now - max(times) > 300]
        for uid in stale_counts:
            bot.user_message_counts.pop(uid, None)
        # Prune expired cooldowns
        expired_cd = [uid for uid, end in bot.user_cooldowns.items() if now > end]
        for uid in expired_cd:
            bot.user_cooldowns.pop(uid, None)
        # Prune stale active_conversations (expired long ago)
        stale_conv = [k for k, t in bot.active_conversations.items()
                      if now - t > CONVERSATION_TIMEOUT * 2]
        for k in stale_conv:
            bot.active_conversations.pop(k, None)
        # Prune lang cache when it grows large
        if len(bot._lang_cache) > 500:
            bot._lang_cache.clear()
        # Prune per-user last-sent-picture tracking after 100 unique users
        if len(bot.last_sent_picture) > 100:
            bot.last_sent_picture.clear()
        # Drop conversation history for chats with no recent activity
        stale_hist = []
        if len(bot.message_history) > 500:
            for k in list(bot.message_history):
                last = bot.active_conversations.get(k)
                if last is None or now - last > CONVERSATION_TIMEOUT * 8:
                    stale_hist.append(k)
            for k in stale_hist:
                bot.message_history.pop(k, None)
        if len(_profile_cache) > 500:
            _profile_cache.clear()
        if len(bot._memory_cache) > 1000:
            bot._memory_cache.clear()
        # These two grow by one entry per unique user ever seen and were the
        # only dicts here with no bound at all. _profile_seen holds the last
        # time a profile was written, on a one-hour throttle, so anything older
        # than that would be rewritten on sight anyway; _friend_due holds
        # scheduled accept times, so anything in the past has already fired.
        stale_seen = [uid for uid, at in _profile_seen.items() if now - at > 3600]
        for uid in stale_seen:
            _profile_seen.pop(uid, None)
        stale_friend = [uid for uid, at in _friend_due.items() if at < now]
        for uid in stale_friend:
            _friend_due.pop(uid, None)
        log_system(
            f"Cleanup: pruned {len(stale_counts)} count(s), {len(expired_cd)} cooldown(s), "
            f"{len(stale_conv)} conversation(s), {len(stale_hist)} history entr(ies), "
            f"{len(stale_seen)} profile stamp(s), {len(stale_friend)} friend timer(s)"
        )


def _pick_status(status_cfg: dict, status_map: dict, defaults: dict):
    """Choose the next presence from the configured statuses and weights.

    Everything here is defensive because this runs in a background task: an
    exception escaping it kills the presence loop for the rest of the session,
    silently. A config written by hand can easily give fewer weights than
    statuses, a weight that is not a number, or weights that are all zero, and
    none of those should stop the account changing status ever again.
    """
    names = status_cfg.get("statuses") or ["online", "idle", "dnd"]
    if isinstance(names, str):
        names = [names]
    raw_weights = status_cfg.get("weights") or []
    if not isinstance(raw_weights, (list, tuple)):
        raw_weights = []

    pool = []
    for i, name in enumerate(names):
        if name not in status_map:
            continue
        # A short weights list leaves the rest at their defaults rather than
        # dropping those statuses entirely, which would silently pin the
        # account to whichever ones happened to be listed first.
        weight = None
        if i < len(raw_weights):
            try:
                weight = float(raw_weights[i])
            except (TypeError, ValueError):
                weight = None
        if weight is None:
            weight = defaults.get(name, 0.05)
        if weight > 0:
            pool.append((status_map[name], weight))

    if not pool:
        # Every weight was zero or unusable. Online is the safe answer, and it
        # is what a real account looks like most of the time anyway.
        return status_map["online"]
    return random.choices([p[0] for p in pool], weights=[p[1] for p in pool], k=1)[0]


async def random_status_loop():
    """Realistic presence, not random flipping.

    Humans stay online for long stretches, occasionally idle out, rarely set
    dnd on purpose, and are invisible while asleep. Randomly switching
    status every 30-180 minutes is an automation signature, so this keeps
    one status until a change feels natural and never flips when the
    persona's local time falls inside the night window (still replies:
    invisible ≠ offline).
    """
    await bot.wait_until_ready()
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    _DEFAULT_WEIGHTS = {"online": 0.85, "idle": 0.12, "dnd": 0.03, "invisible": 0.0}
    # Wait 10-30 min before the FIRST change, flipping presence right after
    # login is a classic automation tell.
    await asyncio.sleep(random.uniform(600, 1800))
    _last_status = None
    while not bot.is_closed():
        status_cfg = config["bot"].get("status") or {}
        night_cfg = config["bot"].get("night_invisible") or {}
        night, secs_until_day = night_window_state(night_cfg)

        if night:
            target = discord.Status.invisible
        else:
            target = _pick_status(status_cfg, status_map, _DEFAULT_WEIGHTS)

        if target != _last_status:
            try:
                await bot.change_presence(status=target)
                _last_status = target
                log_system(f"Presence: {target}")
            except Exception as e:
                log_error("Presence", str(e))

        if night:
            # Sleep through the night; wake 0-20 min after sunrise so the
            # account doesn't flip online at exactly 8:00:00.
            await asyncio.sleep(max(60, (secs_until_day or 3600) + random.uniform(0, 1200)))
        else:
            base = random.randint(
                status_cfg.get("change_interval_min", 1800),
                status_cfg.get("change_interval_max", 10800),
            )
            await asyncio.sleep(base * random.uniform(0.7, 1.3))


def get_terminal_size():
    columns, _ = shutil.get_terminal_size()
    return columns


def create_border(char="═"):
    width = get_terminal_size()
    return char * (width - 2)


def print_header():
    width = get_terminal_size()
    border = create_border()
    title = "LLMSelfbot Discord"
    padding = " " * ((width - len(title) - 2) // 2)

    print(f"{Fore.CYAN}╔{border}╗")
    print(f"║{padding}{Style.BRIGHT}{title}{Style.NORMAL}{padding}║")
    print(f"╚{border}╝{Style.RESET_ALL}")


def print_separator():
    print(f"{Fore.CYAN}{create_border('─')}{Style.RESET_ALL}")


async def _reply_pending_messages():
    """After restart, reply to any users who messaged right before the update."""
    import json
    from app.utils.helpers import resource_path

    path = resource_path("config/pending_messages.json")
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception:
        return

    if not pending:
        return

    os.remove(path)
    log_system(f"Replying to {len(pending)} pending message(s) from before restart...")
    # Wait a human-like 3-8 min before firing pending replies, replying seconds
    # after startup looks like a bot.
    await asyncio.sleep(random.uniform(180, 480))

    for key, data in pending.items():
        try:
            user_id = int(data["user_id"])
            channel_id = int(data["channel_id"])
            history = data.get("history", [])
            content = data["content"]

            if history and history[-1].get("role") == "assistant":
                continue

            # Try to get user from cache first, fall back to fetch
            user = bot.get_user(user_id)
            if user is None:
                try:
                    user = await bot.fetch_user(user_id)
                except Exception as e:
                    log_error("Pending Reply", f"Could not fetch user {user_id}: {e}")
                    continue

            bot.message_history[key] = history
            last_msg = None
            channel = None

            # Use stored last_message_id to fetch directly, no history scan needed
            last_message_id = data.get("last_message_id")
            if last_message_id:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel is None:
                        channel = await user.create_dm()
                    last_msg = await channel.fetch_message(int(last_message_id))
                except Exception:
                    last_msg = None

            # Fallback: scan DM history (only if we had no stored message id)
            if last_msg is None:
                try:
                    dm = await user.create_dm()
                    async for msg in dm.history(limit=15):
                        if msg.author.id == user_id:
                            last_msg = msg
                            channel = dm
                            break
                except Exception:
                    pass

            if last_msg is None:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel is None:
                        for pc in bot.private_channels:
                            if pc.id == channel_id:
                                channel = pc
                                break
                    if channel:
                        async for msg in channel.history(limit=15):
                            if msg.author.id == user_id:
                                last_msg = msg
                                break
                except Exception as e:
                    log_error("Pending Reply", f"Could not check original channel {channel_id}: {e}")

            if last_msg is None or channel is None:
                log_error("Pending Reply", f"No message found for user {user.name}, skipping")
                continue

            if isinstance(channel, discord.TextChannel):
                was_mentioned = bot.user.mentioned_in(last_msg) and "@everyone" not in last_msg.content and "@here" not in last_msg.content
                was_replied_to = (
                    last_msg.reference
                    and last_msg.reference.resolved
                    and last_msg.reference.resolved.author.id == bot.selfbot_id
                )
                if not was_mentioned and not was_replied_to:
                    log_system(f"Skipping pending reply to {user.name}, server channel, not a mention/reply")
                    continue

            log_system(f"Replying to pending message from {user.name}")
            await asyncio.sleep(random.uniform(8, 25))
            response = await generate_response_and_reply(last_msg, content, history)
            if response:
                bot.message_history[key].append({"role": "assistant", "content": response})
        except Exception as e:
            log_error("Pending Reply Error", str(e))


async def _friend_request_loop():
    """On startup, accept any pending friend requests using the raw HTTP API."""
    await bot.wait_until_ready()
    await asyncio.sleep(5)

    fr_cfg = config["bot"].get("friend_requests") or {}
    if not fr_cfg.get("enabled", False):
        return
    delay = random.randint(
        fr_cfg.get("accept_delay_min", 120),
        fr_cfg.get("accept_delay_max", 600),
    )

    try:
        token = bot._connection.http.token
        async with build_session(token) as session:
            resp = await session.get(
                "https://discord.com/api/v9/users/@me/relationships",
            )
            if resp.status_code != 200:
                log_error("Friend Request Loop", f"Failed to fetch relationships: {resp.status_code}: {resp.text}")
                return

            relationships = resp.json()
            # type 3 = incoming friend request in Discord's raw API
            pending = [r for r in relationships if r.get("type") == 3]
            log_system(f"Friend requests: found {len(pending)} pending on startup")

            # Distribute accepts in random bursts across a 6-hour window,
            # mimicking a human who opens Discord a few times and clears requests.
            num_bursts = random.randint(2, 3)
            burst_offsets = sorted(random.uniform(0, 21600) for _ in range(num_bursts))  # 6h window
            for i, rel in enumerate(pending):
                user_id = int(rel["id"])
                username = rel.get("user", {}).get("username", str(user_id))
                # Assign this request to a burst, with intra-burst jitter
                # (10-90s apart), plus ±25% wobble on the total so two accepts
                # never land on a metronome.
                burst_base = burst_offsets[i % num_bursts]
                intra_jitter = random.uniform(10, 90) * (i // num_bursts)
                actual_delay = (delay + burst_base + intra_jitter) * random.uniform(0.75, 1.25)
                log_system(f"Pending friend request from {username}, accepting in {int(actual_delay)}s")
                _friend_due[user_id] = time.time() + actual_delay

                async def _accept(uid=user_id, uname=username, d=actual_delay):
                    await asyncio.sleep(d)
                    try:
                        async with build_session(bot._connection.http.token) as s:
                            r = await s.put(
                                f"https://discord.com/api/v9/users/@me/relationships/{uid}",
                                json={"type": 1},
                            )
                            if r.status_code in (200, 204):
                                log_system(f"Accepted friend request from {uname}")
                            else:
                                try:
                                    data = r.json()
                                    log_error("Friend Request Accept", f"{r.status_code}: {data}")
                                except Exception:
                                    log_error("Friend Request Accept", f"{r.status_code}: {r.text}")
                    except Exception as e:
                        log_error("Friend Request Loop", str(e))

                asyncio.create_task(_accept())

    except Exception as e:
        log_error("Friend Request Loop", str(e))




async def _nudge_loop():
    """Background task: periodically check for long-unanswered DMs and send a nudge."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        nudge_cfg = config["bot"].get("nudge") or {}
        if not nudge_cfg.get("enabled", False):
            await asyncio.sleep(3600)
            continue

        check_interval_hours = nudge_cfg.get("check_interval_hours", 6)
        threshold_days = nudge_cfg.get("threshold_days", 2)
        send_hour_start = nudge_cfg.get("send_during_hours", [10, 22])[0]
        send_hour_end = nudge_cfg.get("send_during_hours", [10, 22])[1]

        current_hour = datetime.now().astimezone().hour
        if send_hour_start <= current_hour < send_hour_end:
            threshold_seconds = threshold_days * 86400
            pending = get_pending_nudges(threshold_seconds)

            for entry in pending:
                try:
                    user_id = entry["user_id"]
                    channel_id = entry["channel_id"]
                    original_content = entry["content"]
                    days_elapsed = (time.time() - entry["received_at"]) / 86400

                    user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                    if not user:
                        continue

                    # Build minimal instructions for nudge tone
                    uid = user_id
                    if uid not in bot._memory_cache:
                        bot._memory_cache[uid] = get_memory(uid)
                    memory_block = format_memory_for_prompt(bot._memory_cache[uid])
                    mood_block = f"\n\n[Right now: {get_mood_prompt()}]" if _MOOD_CFG.get("enabled", True) else ""
                    nudge_instructions = bot.instructions + mood_block + memory_block

                    nudge_text = await generate_nudge(original_content, days_elapsed, nudge_instructions)
                    if not nudge_text or is_refusal(nudge_text):
                        continue

                    # Human-like pre-send delay
                    await asyncio.sleep(random.uniform(30, 120))

                    try:
                        dm = user.dm_channel or await user.create_dm()
                        if bot.realistic_typing:
                            async with dm.typing():
                                cps = random.uniform(7, 18)
                                await asyncio.sleep(len(nudge_text) / cps)
                        await dm.send(nudge_text)
                        mark_nudge_sent(user_id, channel_id)
                        log_system(f"Nudge sent to {user.name} ({days_elapsed:.1f}d elapsed)")

                        # Add to history so the conversation continues naturally
                        key = f"{user_id}-{channel_id}"
                        bot.message_history.setdefault(key, [])
                        bot.message_history[key].append({"role": "assistant", "content": nudge_text})

                    except Exception as send_err:
                        log_error("Nudge Send", str(send_err))

                except Exception as e:
                    log_error("Nudge Loop", str(e))

        await asyncio.sleep(check_interval_hours * 3600)


async def _shutdown_on_401():
    """Cancel all pending tasks and close the bot cleanly on 401."""
    print(
        f"\n{'='*60}\n"
        f"  ✗  TOKEN INVALIDATED (401 Unauthorized)\n"
        f"  →  Discord rejected the token mid-session, it may have been\n"
        f"     reset, logged out, or flagged.\n"
        f"  →  Update DISCORD_TOKEN in your .env file and restart.\n"
        f"{'='*60}\n"
    )
    current = asyncio.current_task()
    for task in asyncio.all_tasks():
        if task is not current and not task.done():
            task.cancel()
    await bot.close()


def _flush_commands(cmd_file, remaining, handled):
    """Rewrite the IPC command file, preserving entries added while we worked.

    Errors queued by _notify_telegram_error (or a second bot instance) land in
    this file mid-pass; a blind overwrite would silently drop them.
    """
    import json as _json
    handled_ids = {e.get("id") for e in handled}
    keep = list(remaining)
    keep_ids = {e.get("id") for e in keep}
    try:
        current = _json.loads(cmd_file.read_text())
    except Exception:
        current = []
    if isinstance(current, list):
        for entry in current:
            eid = entry.get("id")
            if eid not in handled_ids and eid not in keep_ids:
                keep.append(entry)
                keep_ids.add(eid)
    tmp = cmd_file.with_suffix(".tmp")
    tmp.write_text(_json.dumps(keep, ensure_ascii=False))
    tmp.replace(cmd_file)


async def _tg_ipc_loop():
    """Poll for commands from the Telegram controller and execute them in-process.

    Each bot instance uses its own per-account IPC files:
      config/tg_commands_1.json / tg_results_1.json  (account 1)
      config/tg_commands_2.json / tg_results_2.json  (account 2)
    The account index matches the position of DISCORD_TOKEN_N in .env.
    """
    import json as _json
    from pathlib import Path as _Path

    await bot.wait_until_ready()

    _CMD_FILE    = _Path(resource_path(f"config/tg_commands_{ACCOUNT_INDEX}.json"))
    _RESULT_FILE = _Path(resource_path(f"config/tg_results_{ACCOUNT_INDEX}.json"))
    _POLL_INTERVAL = 2.0

    # A result is only removed when someone reads it. Anything whose caller
    # timed out or went away stayed forever, and reply_check answers are tens
    # of KB each, so this file reached 91 MB in normal use. Every IPC call then
    # re-read and rewrote all of it synchronously, which stalled the whole
    # panel. Keeping only the newest few bounds it for good.
    _MAX_RESULTS = 40

    def _write_result(cmd_id: str, data: dict):
        results = {}
        if _RESULT_FILE.exists():
            try:
                results = _json.loads(_RESULT_FILE.read_text())
            except Exception:
                pass
        if not isinstance(results, dict):
            results = {}
        results[cmd_id] = data
        if len(results) > _MAX_RESULTS:
            # dicts keep insertion order, so the tail is the newest.
            results = dict(list(results.items())[-_MAX_RESULTS:])
        _RESULT_FILE.write_text(_json.dumps(results))

    log_system("Telegram IPC bridge started")

    _FLAG_FILE = _Path(resource_path("config/update.flag"))

    while not bot.is_closed():
        await asyncio.sleep(_POLL_INTERVAL)

        # ── Check for update sentinel flag (written by Telegram controller) ──
        if _FLAG_FILE.exists():
            try:
                _flag_source = _FLAG_FILE.read_text().strip() or "release"
                if _flag_source not in ("release", "main"):
                    _flag_source = "release"
                _FLAG_FILE.unlink(missing_ok=True)
                log_system(f"Update ({_flag_source}) triggered via flag file")
                _upd_repo_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                import subprocess as _upd_sp
                if sys.platform == "win32":
                    _upd_path = os.path.join(_upd_repo_dir, "scripts", "updater.bat")
                    _upd_sp.Popen(
                        f'cmd /c start "Updating LLMSelfbot..." /d "{_upd_repo_dir}" "{_upd_path}" {_flag_source}',
                        shell=True,
                        cwd=_upd_repo_dir,
                        creationflags=0x00000010,  # CREATE_NEW_CONSOLE
                    )
                else:
                    _upd_path = os.path.join(_upd_repo_dir, "scripts", "updater.sh")
                    try:
                        os.chmod(_upd_path, 0o755)
                    except Exception:
                        pass
                    _upd_sp.Popen(["bash", _upd_path, _flag_source], start_new_session=True, cwd=_upd_repo_dir)
                await asyncio.sleep(2)
                await bot.close()
                sys.exit(0)
            except Exception as _flag_err:
                log_error("Update Flag", str(_flag_err))

        if not _CMD_FILE.exists():
            continue
        try:
            raw = _CMD_FILE.read_text()
            commands = _json.loads(raw)
        except Exception:
            continue
        if not commands:
            continue

        # Error notifications are for the Telegram controller to consume, the
        # runner only queues them, so they must survive this pass.
        remaining = [e for e in commands if e.get("cmd") == "send_error_notification"]
        commands = [e for e in commands if e.get("cmd") != "send_error_notification"]
        for entry in commands:
            cmd_id  = entry.get("id", "")
            cmd     = entry.get("cmd", "")
            payload = entry.get("payload", {})
            try:
                if cmd == "pause":
                    bot.paused = not bot.paused
                    _write_result(cmd_id, {"paused": bot.paused})

                elif cmd == "wipe":
                    bot.message_history.clear()
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "toggle_dm":
                    bot.allow_dm = not bot.allow_dm
                    cfg = load_config(); cfg["bot"]["allow_dm"] = bot.allow_dm
                    import yaml as _yaml
                    with open(resource_path("config/config.yaml"), "w", encoding="utf-8") as _f:
                        _yaml.dump(cfg, _f, default_flow_style=False, allow_unicode=True)
                    _write_result(cmd_id, {"allow_dm": bot.allow_dm})

                elif cmd == "toggle_gc":
                    bot.allow_gc = not bot.allow_gc
                    cfg = load_config(); cfg["bot"]["allow_gc"] = bot.allow_gc
                    import yaml as _yaml
                    with open(resource_path("config/config.yaml"), "w", encoding="utf-8") as _f:
                        _yaml.dump(cfg, _f, default_flow_style=False, allow_unicode=True)
                    _write_result(cmd_id, {"allow_gc": bot.allow_gc})

                elif cmd == "toggle_server":
                    bot.allow_server = not getattr(bot, "allow_server", True)
                    cfg = load_config(); cfg["bot"]["allow_server"] = bot.allow_server
                    import yaml as _yaml
                    with open(resource_path("config/config.yaml"), "w", encoding="utf-8") as _f:
                        _yaml.dump(cfg, _f, default_flow_style=False, allow_unicode=True)
                    _write_result(cmd_id, {"allow_server": bot.allow_server})

                elif cmd == "ignore_add":
                    uid = int(payload["user_id"])
                    if uid not in bot.ignore_users:
                        bot.ignore_users.append(uid)
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "ignore_remove":
                    uid = int(payload["user_id"])
                    if uid in bot.ignore_users:
                        bot.ignore_users.remove(uid)
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "pauseuser":
                    bot.paused_users.add(int(payload["user_id"]))
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "unpauseuser":
                    bot.paused_users.discard(int(payload["user_id"]))
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "persona_set":
                    from app.utils.memory import set_persona as _sp
                    uid = int(payload["user_id"])
                    _sp(uid, payload["persona"])
                    bot._memory_cache.setdefault(uid, {})["__persona__"] = payload["persona"]
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "persona_clear":
                    from app.utils.memory import clear_persona as _cp
                    uid = int(payload["user_id"])
                    _cp(uid)
                    bot._memory_cache.get(uid, {}).pop("__persona__", None)
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "mood_set":
                    import app.utils.mood as _mood_mod
                    _mood_mod.current_mood = payload["mood"]
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "instructions_update":
                    bot.instructions = payload["text"]
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "config_update":
                    _live = {
                        "allow_dm":          lambda v: setattr(bot, "allow_dm", v),
                        "allow_gc":          lambda v: setattr(bot, "allow_gc", v),
                        "allow_server":      lambda v: setattr(bot, "allow_server", v),
                        "realistic_typing":  lambda v: setattr(bot, "realistic_typing", v),
                        "batch_messages":    lambda v: setattr(bot, "batch_messages", v),
                        "hold_conversation": lambda v: setattr(bot, "hold_conversation", v),
                        "reply_ping":        lambda v: setattr(bot, "reply_ping", v),
                        "disable_mentions":  lambda v: setattr(bot, "disable_mentions", v),
                        "anti_age_ban":      lambda v: setattr(bot, "anti_age_ban", v),
                    }
                    leaf = payload.get("key", "").split(".")[-1]
                    if leaf in _live:
                        _live[leaf](payload.get("value"))
                    # Everything else cached at import (timings, chances, mood,
                    # late/stale reply) is picked up here, so almost nothing
                    # needs the account restarted any more.
                    try:
                        refresh_config(bot)
                    except Exception as _re:
                        log_error("Config reload", str(_re))
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "reply_check":
                    users_out = []
                    seen_ids = set()

                    # Pass 1: in-memory history (fast, works mid-session)
                    for hk, history in bot.message_history.items():
                        if not history or history[-1].get("role") != "user":
                            continue
                        try:
                            uid = int(hk.split("-")[0])
                            if uid in seen_ids or uid in _blocked_users:
                                continue
                            seen_ids.add(uid)
                            u = bot.get_user(uid)
                            pending = [e["content"] for e in reversed(history) if e["role"] == "user"]
                            last = pending[0] if pending else ""
                            snippet = (last[:60] + "…") if len(last) > 60 else last
                            # When the bot will answer this one on its own,
                            # from the batch it is sitting in.
                            _due = 0.0
                            try:
                                for _bk, _b in bot.user_message_batches.items():
                                    if _bk.startswith(f"{uid}-") and _b.get("reply_at"):
                                        _due = max(_due, float(_b["reply_at"]))
                            except Exception:
                                pass
                            users_out.append({
                                "reply_at": _due or None,
                                "id": uid,
                                "name": u.name if u else str(uid),
                                "snippet": snippet,
                                "count": len(pending),
                                "ts": 0,          # this session, so effectively now
                            })
                        except Exception:
                            pass

                    # Pass 2: live DM channel scan (catches post-restart gaps)
                    # The budget is spent once for the whole sweep, not once per
                    # channel: this is a person opening the Chats page, and with
                    # 20 DMs the per-channel cost drained an hour of budget in
                    # three refreshes, after which conversations just vanished.
                    _scanned = 0
                    _SCAN_CAP = 30
                    try:
                        _selfbot_id = getattr(bot, "selfbot_id", None) or bot.user.id
                        _sweep_ok = history_scan_allowed()
                        for _ch in bot.private_channels:
                            if not isinstance(_ch, discord.DMChannel):
                                continue
                            _other = _ch.recipient
                            if _other is None or _other.id in seen_ids:
                                continue
                            # Blocked: the DM still exists and still ends with
                            # their message, so this pass found it every time.
                            if _other.id in _blocked_users:
                                continue
                            # Quick cache check, skip if bot sent the last message
                            _cached_last = None
                            if _ch.last_message_id:
                                _cached_last = _ch._state._get_message(_ch.last_message_id)
                            if _cached_last is not None and _cached_last.author.id == _selfbot_id:
                                continue
                            try:
                                # One budget unit covers the sweep; the cap keeps
                                # a huge DM list from turning into a REST storm.
                                if not _sweep_ok or _scanned >= _SCAN_CAP:
                                    continue
                                _scanned += 1
                                _last_msgs = [m async for m in _ch.history(limit=10)]
                                if not _last_msgs:
                                    continue
                                _last_other = next((m for m in _last_msgs if m.author.id != _selfbot_id), None)
                                _last_bot   = next((m for m in _last_msgs if m.author.id == _selfbot_id), None)
                                if _last_other is None:
                                    continue
                                if _last_bot and _last_bot.created_at > _last_other.created_at:
                                    continue
                                _pending_ct = sum(
                                    1 for m in _last_msgs
                                    if m.author.id != _selfbot_id
                                    and (_last_bot is None or m.created_at > _last_bot.created_at)
                                )
                                _snip_text = _last_other.content or "[attachment]"
                                _snip = (_snip_text[:60] + "…") if len(_snip_text) > 60 else _snip_text
                                seen_ids.add(_other.id)
                                users_out.append({
                                    "id": _other.id,
                                    "name": _other.name,
                                    "snippet": _snip,
                                    "count": max(_pending_ct, 1),
                                    "ts": _last_other.created_at.timestamp(),
                                })
                            except Exception:
                                continue
                    except Exception:
                        pass

                    # Why nothing has moved yet, so the page can say "in 40s"
                    # rather than leaving a list of unanswered people with no
                    # explanation. All of it is state the runner already holds.
                    _cool_until = 0.0
                    if GLOBAL_COOLDOWN_ENABLED:
                        _cool_until = getattr(bot, "last_global_send", 0.0) + GLOBAL_COOLDOWN_MIN
                    _write_result(cmd_id, {
                        "users": users_out,
                        "paused": getattr(bot, "paused", False),
                        # Unix time when the next reply may be sent, or 0.
                        "cooldown_until": _cool_until if _cool_until > time.time() else 0,
                        "cooldown_range": [GLOBAL_COOLDOWN_MIN, GLOBAL_COOLDOWN_MAX]
                        if GLOBAL_COOLDOWN_ENABLED else None,
                    })

                elif cmd == "reply_user":
                    uid = int(payload["user_id"])
                    # A failure that can never succeed has to take the message
                    # off the waiting list too. Leaving it there meant the same
                    # conversation came back on every sweep and Reply to all
                    # retried it for ever, always with the same error.
                    from app.utils.db import drop_unresponded as _drop
                    if uid == bot.user.id:
                        _drop(uid)
                        _write_result(cmd_id, {"success": False, "dropped": True,
                                               "reason": "that is this account, Discord has no DM with yourself"})
                        continue
                    try:
                        u = bot.get_user(uid) or await bot.fetch_user(uid)
                    except discord.NotFound:
                        # Raised straight out before, so the panel showed the raw
                        # "404 ... (error code: 10013): Unknown User" instead of
                        # anything actionable.
                        _drop(uid)
                        _write_result(cmd_id, {"success": False, "dropped": True,
                                               "reason": f"Discord does not know user {uid}"})
                        continue
                    except Exception as _fe:
                        _write_result(cmd_id, {"success": False, "reason": str(_fe)}); continue
                    if not u:
                        _drop(uid)
                        _write_result(cmd_id, {"success": False, "dropped": True,
                                               "reason": "user not found"}); continue
                    target_msg = None; target_ch = None
                    for hk in bot.message_history:
                        if hk.startswith(f"{uid}-"):
                            try:
                                if not history_scan_allowed():
                                    break
                                ch = bot.get_channel(int(hk.split("-")[1])) or await u.create_dm()
                                async for msg in ch.history(limit=10):
                                    if msg.author.id == uid:
                                        target_msg = msg; target_ch = ch; break
                            except Exception:
                                pass
                            break
                    if not target_msg:
                        try:
                            if history_scan_allowed():
                                dm = u.dm_channel or await u.create_dm()
                                async for msg in dm.history(limit=10):
                                    if msg.author.id == uid:
                                        target_msg = msg; target_ch = dm; break
                        except Exception:
                            pass
                    if not target_msg:
                        _write_result(cmd_id, {"success": False, "reason": "no recent message found"}); continue
                    hk = f"{uid}-{target_ch.id}"
                    history = bot.message_history.get(hk, [])
                    combined = target_msg.content or "[attachment]"
                    if not history or history[-1].get("content") != combined:
                        history.append({"role": "user", "content": combined})
                        bot.message_history[hk] = history
                    resp = await generate_response_and_reply(target_msg, combined, history, bypass_cooldown=True, bypass_typing=True)
                    if resp:
                        bot.message_history[hk].append({"role": "assistant", "content": resp})
                        _write_result(cmd_id, {"success": True})
                    elif uid in _blocked_users:
                        _write_result(cmd_id, {
                            "success": False, "dropped": True,
                            "reason": "they have blocked the account or closed their DMs"})
                    else:
                        # Left on the waiting list on purpose: unlike a block,
                        # this can succeed later, so it is worth retrying.
                        _write_result(cmd_id, {
                            "success": False, "retryable": True,
                            "reason": "could not send a reply, see the log"})

                elif cmd == "reply_all":
                    results_out = []; seen = set()
                    _ra_selfbot_id = getattr(bot, "selfbot_id", None) or bot.user.id

                    # ── Pass 1: in-memory history (fast, works mid-session) ────
                    _ra_candidates = []  # list of (uid, channel_id, history_key)
                    for hk, history in list(bot.message_history.items()):
                        if not history or history[-1].get("role") != "user":
                            continue
                        try:
                            uid = int(hk.split("-")[0])
                            cid = int(hk.split("-")[1])
                            if uid in seen: continue
                            seen.add(uid)
                            _ra_candidates.append((uid, cid, hk))
                        except Exception:
                            pass

                    # ── Pass 2: live DM scan (catches post-restart gaps) ─────
                    try:
                        for _ra_ch in bot.private_channels:
                            if not isinstance(_ra_ch, discord.DMChannel):
                                continue
                            _ra_other = _ra_ch.recipient
                            if _ra_other is None or _ra_other.id in seen:
                                continue
                            # Quick cache pre-filter, skip if bot sent last message
                            _ra_cached = None
                            if _ra_ch.last_message_id:
                                _ra_cached = _ra_ch._state._get_message(_ra_ch.last_message_id)
                            if _ra_cached is not None and _ra_cached.author.id == _ra_selfbot_id:
                                continue
                            try:
                                if not history_scan_allowed():
                                    continue
                                _ra_msgs = [m async for m in _ra_ch.history(limit=10)]
                                if not _ra_msgs: continue
                                _ra_last_other = next((m for m in _ra_msgs if m.author.id != _ra_selfbot_id), None)
                                _ra_last_bot   = next((m for m in _ra_msgs if m.author.id == _ra_selfbot_id), None)
                                if _ra_last_other is None: continue
                                if _ra_last_bot and _ra_last_bot.created_at > _ra_last_other.created_at:
                                    continue
                                seen.add(_ra_other.id)
                                _ra_candidates.append((_ra_other.id, _ra_ch.id, None))
                            except Exception:
                                continue
                    except Exception:
                        pass

                    # ── Reply to every discovered candidate ───────────────────
                    _ra_ignored = set(getattr(bot, "ignore_users", []))
                    _ra_filtered = [(u, c, h) for u, c, h in _ra_candidates if u not in _ra_ignored]

                    if not _ra_filtered:
                        _write_result(cmd_id, {"total": 0, "results": []})
                    else:
                        for _ra_uid, _ra_cid, _ra_hk in _ra_filtered:
                            try:
                                _ra_u = bot.get_user(_ra_uid) or await bot.fetch_user(_ra_uid)
                                _ra_ch2 = bot.get_channel(_ra_cid)
                                if _ra_ch2 is None:
                                    try:
                                        _ra_ch2 = await _ra_u.create_dm()
                                    except Exception:
                                        results_out.append({"id": _ra_uid, "name": _ra_u.name if _ra_u else str(_ra_uid), "success": False, "reason": "could not open DM"})
                                        continue
                                _ra_target = None
                                if history_scan_allowed():
                                    async for _ra_m in _ra_ch2.history(limit=15):
                                        if _ra_m.author.id == _ra_uid:
                                            _ra_target = _ra_m; break
                                if not _ra_target:
                                    results_out.append({"id": _ra_uid, "name": _ra_u.name, "success": False, "reason": "no recent message found"})
                                    continue
                                _ra_hk2 = _ra_hk or f"{_ra_uid}-{_ra_cid}"
                                _ra_hist = bot.message_history.get(_ra_hk2, [])
                                _ra_combined = "\n".join(e["content"] for e in _ra_hist[-3:] if e["role"] == "user") or (_ra_target.content or "[attachment]")
                                if not _ra_hist or _ra_hist[-1].get("content") != _ra_combined:
                                    _ra_hist.append({"role": "user", "content": _ra_combined})
                                    bot.message_history[_ra_hk2] = _ra_hist
                                resp = await generate_response_and_reply(_ra_target, _ra_combined, _ra_hist, bypass_cooldown=True, bypass_typing=True)
                                if resp:
                                    bot.message_history[_ra_hk2].append({"role": "assistant", "content": resp})
                                    results_out.append({"id": _ra_uid, "name": _ra_u.name, "success": True})
                                else:
                                    results_out.append({"id": _ra_uid, "name": _ra_u.name, "success": False, "reason": "no response generated"})
                            except Exception as _ra_e:
                                _ra_name = str(_ra_uid)
                                try:
                                    _ra_name = (bot.get_user(_ra_uid) or await bot.fetch_user(_ra_uid)).name
                                except Exception:
                                    pass
                                results_out.append({"id": _ra_uid, "name": _ra_name, "success": False, "reason": str(_ra_e)})
                        _write_result(cmd_id, {"total": len(results_out), "results": results_out})

                elif cmd == "restart":
                    import atexit as _atexit
                    log_system("Restart requested via Telegram")
                    # Route through the role launcher so it also works frozen.
                    def _relaunch():
                        from app.core.launcher import spawn_role
                        spawn_role("discord", ACCOUNT_INDEX, capture=False)
                    _atexit.register(_relaunch)
                    # Flush command file before exit so the restart entry is
                    # not re-processed on the next startup.
                    _flush_commands(_CMD_FILE, remaining, commands)
                    await bot.close(); sys.exit(0)

                elif cmd == "get_status":
                    import app.utils.mood as _mood_mod
                    _write_result(cmd_id, {
                        "paused": bot.paused,
                        "mood": _mood_mod.current_mood,
                        "active_channels": len(bot.active_channels),
                        "ignored_users": len(bot.ignore_users),
                    })

                elif cmd == "mood_get":
                    import app.utils.mood as _mood_mod
                    _write_result(cmd_id, {"mood": _mood_mod.current_mood})

                elif cmd == "ignore_toggle":
                    uid = int(payload["user_id"])
                    if uid in bot.ignore_users:
                        bot.ignore_users.remove(uid)
                        from app.utils.db import remove_ignored_user as _riu
                        _riu(uid)
                        _write_result(cmd_id, {"ok": True, "ignored": False})
                    else:
                        bot.ignore_users.append(uid)
                        from app.utils.db import add_ignored_user as _aiu
                        _aiu(uid)
                        _write_result(cmd_id, {"ok": True, "ignored": True})

                elif cmd == "persona_get":
                    from app.utils.memory import get_persona as _gp
                    uid = int(payload["user_id"])
                    _write_result(cmd_id, {"persona": _gp(uid)})

                elif cmd == "get_leaderboard":
                    from app.utils.db import get_leaderboard as _glb
                    from datetime import datetime as _dt
                    import re as _re
                    import time as _time_mod
                    filter_str = payload.get("filter")
                    since_ts = None
                    filter_label = "all time"
                    if filter_str:
                        m = _re.fullmatch(r"(\d+(?:\.\d+)?)\s*([hdwm])", filter_str.strip().lower())
                        if m:
                            amount, unit = float(m.group(1)), m.group(2)
                            seconds_map = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000}
                            since_ts = _time_mod.time() - amount * seconds_map[unit]
                            unit_names = {"h": "hour", "d": "day", "w": "week", "m": "month"}
                            n = int(amount) if amount == int(amount) else amount
                            filter_label = f"last {n} {unit_names[unit]}{'s' if n != 1 else ''}"
                    rows = _glb(limit=20, since=since_ts)
                    serialized = []
                    for row in rows:
                        serialized.append({
                            "username": row["username"],
                            "message_count": row["message_count"],
                            "first_seen_fmt": _dt.fromtimestamp(row["first_seen"]).strftime("%d %b %Y"),
                        })
                    _write_result(cmd_id, {"rows": serialized, "filter_label": filter_label})

                elif cmd == "shutdown":
                    log_system("Shutdown requested via Telegram")
                    _flush_commands(_CMD_FILE, remaining, commands)
                    await bot.close(); sys.exit(0)

                # ── toggle_active ─────────────────────────────────────────────
                elif cmd == "toggle_active":
                    _ch_id = int(payload["channel_id"])
                    if _ch_id in bot.active_channels:
                        bot.active_channels.discard(_ch_id)
                        from app.utils.db import remove_channel as _rc
                        _rc(_ch_id)
                        _write_result(cmd_id, {"active": False})
                    else:
                        bot.active_channels.add(_ch_id)
                        from app.utils.db import add_channel as _ac
                        _ac(_ch_id)
                        _write_result(cmd_id, {"active": True})

                # ── get_profile ───────────────────────────────────────────────
                # Fills the panel's profile card for someone the bot has not
                # spoken to since the cache existed. Without this an avatar only
                # ever appears after they happen to message again.
                elif cmd == "get_profile":
                    _uid = int(payload["user_id"])
                    try:
                        _user = bot.get_user(_uid) or await bot.fetch_user(_uid)
                    except Exception as _e:
                        _write_result(cmd_id, {"ok": False, "reason": f"User {_uid} not found."})
                        continue
                    _profile_seen.pop(_uid, None)      # force the write through
                    _cache_author(_user)
                    _avatar = ""
                    try:
                        _avatar = _user.display_avatar.replace(size=128).url
                    except Exception:
                        _avatar = str(getattr(getattr(_user, "display_avatar", None), "url", "") or "")
                    _write_result(cmd_id, {
                        "ok": True,
                        "username": getattr(_user, "name", ""),
                        "display_name": getattr(_user, "global_name", None)
                        or getattr(_user, "display_name", ""),
                        "avatar": _avatar,
                    })

                # ── analyse_user ──────────────────────────────────────────────
                elif cmd == "analyse_user":
                    _uid = int(payload["user_id"])
                    try:
                        _user = bot.get_user(_uid) or await bot.fetch_user(_uid)
                    except Exception:
                        _write_result(cmd_id, {"ok": False, "reason": f"User {_uid} not found."})
                        continue
                    _msg_list = []
                    try:
                        if not history_scan_allowed():
                            _write_result(cmd_id, {"ok": False, "reason": "history scan budget exhausted - try again in a bit"})
                            continue
                        _dm = _user.dm_channel or await _user.create_dm()
                        async for _m in _dm.history(limit=200):
                            if _m.author.id == _uid and _m.content:
                                _msg_list.append(_m.content)
                    except Exception:
                        pass
                    if len(_msg_list) < 20:
                        for _cid in list(bot.active_channels)[:3]:
                            try:
                                if not history_scan_allowed():
                                    break
                                _ch = bot.get_channel(_cid) or await bot.fetch_channel(_cid)
                                async for _m in _ch.history(limit=200):
                                    if _m.author.id == _uid and _m.content:
                                        _msg_list.append(_m.content)
                            except Exception:
                                pass
                    if not _msg_list:
                        _write_result(cmd_id, {"ok": False, "reason": f"No messages found for user {_uid}."})
                        continue
                    _analyse_instructions = (
                        bot.instructions +
                        f"\n\nSomeone asked you to give your honest read on {_user.name} based on their messages. "
                        "Stay in character. Give your real unfiltered opinion like you would to a friend. "
                        "Be casual, funny, and direct. Roast them a bit but also be real about what you actually see. "
                        "Reference specific things they said to back up your points. "
                        "Keep it conversational, no bullet points, no formal structure, just talk like yourself. "
                        "Don't be overly mean but don't sugarcoat either. Max 3-4 short paragraphs."
                    )
                    _analyse_prompt = "Here are their messages: " + " | ".join(_msg_list[-200:])
                    _profile = await generate_response(_analyse_prompt, _analyse_instructions, history=None)
                    if _profile:
                        _write_result(cmd_id, {"ok": True, "profile": _profile})
                    else:
                        _write_result(cmd_id, {"ok": False, "reason": "AI returned an empty response."})

                # ── voice_join ────────────────────────────────────────────────
                elif cmd == "voice_join":
                    import re as _re3
                    _args_str = payload.get("args", "").strip()
                    _gid_v, _cid_v = None, None
                    _lm = _re3.match(r"https?://discord\.com/channels/(\d+)/(\d+)", _args_str)
                    if _lm:
                        _gid_v, _cid_v = int(_lm.group(1)), int(_lm.group(2))
                    elif _args_str.isdigit():
                        _cid_v = int(_args_str)
                    else:
                        _parts = _args_str.split()
                        if len(_parts) == 2 and _parts[0].isdigit() and _parts[1].isdigit():
                            _gid_v, _cid_v = int(_parts[0]), int(_parts[1])
                    if not _cid_v:
                        _write_result(cmd_id, {"ok": False, "reason": "Invalid channel ID or link."})
                        continue
                    _vtarget = (bot.get_guild(_gid_v).get_channel(_cid_v) if _gid_v and bot.get_guild(_gid_v) else bot.get_channel(_cid_v))
                    if not isinstance(_vtarget, discord.VoiceChannel):
                        _write_result(cmd_id, {"ok": False, "reason": "Channel not found or is not a voice channel."})
                        continue
                    try:
                        _existing = _vtarget.guild.voice_client
                        if _existing:
                            _existing._keep_alive_guard = False
                            await _existing.disconnect(force=True)
                        await _vtarget.connect(self_mute=True, self_deaf=True)
                        _write_result(cmd_id, {"ok": True, "channel": _vtarget.name, "guild": _vtarget.guild.name})
                    except Exception as _e:
                        _write_result(cmd_id, {"ok": False, "reason": str(_e)})

                # ── voice_leave ───────────────────────────────────────────────
                elif cmd == "voice_leave":
                    _gid_l = payload.get("guild_id")
                    if _gid_l:
                        _gl = bot.get_guild(int(_gid_l))
                        _vc = _gl.voice_client if _gl else None
                    else:
                        _vc = next((g.voice_client for g in bot.guilds if g.voice_client), None)
                    if _vc:
                        _vc._keep_alive_guard = False
                        await _vc.disconnect(force=True)
                        _write_result(cmd_id, {"ok": True, "channel": _vc.channel.name, "guild": _vc.guild.name})
                    else:
                        _write_result(cmd_id, {"ok": False, "reason": "Not in a voice channel."})

                # ── voice_autojoin ────────────────────────────────────────────
                elif cmd == "voice_autojoin":
                    import re as _re4
                    import yaml as _yaml_aj
                    _aj_args = payload.get("args", "").strip()
                    if not _aj_args or _aj_args.lower() == "off":
                        _aj_cfg = load_config()
                        _aj_cfg["bot"]["autojoin_channel"] = None
                        with open(resource_path("config/config.yaml"), "w", encoding="utf-8") as _f:
                            _yaml_aj.dump(_aj_cfg, _f, default_flow_style=False, allow_unicode=True)
                        _write_result(cmd_id, {"ok": True, "disabled": True})
                        continue
                    _gid_aj, _cid_aj = None, None
                    _lm_aj = _re4.match(r"https?://discord\.com/channels/(\d+)/(\d+)", _aj_args)
                    if _lm_aj:
                        _gid_aj, _cid_aj = int(_lm_aj.group(1)), int(_lm_aj.group(2))
                    elif _aj_args.isdigit():
                        _cid_aj = int(_aj_args)
                    else:
                        _p = _aj_args.split()
                        if len(_p) == 2 and _p[0].isdigit() and _p[1].isdigit():
                            _gid_aj, _cid_aj = int(_p[0]), int(_p[1])
                    if not _cid_aj:
                        _write_result(cmd_id, {"ok": False, "reason": "Invalid channel ID or link."})
                        continue
                    _aj_target = (bot.get_guild(_gid_aj).get_channel(_cid_aj) if _gid_aj and bot.get_guild(_gid_aj) else bot.get_channel(_cid_aj))
                    if not isinstance(_aj_target, discord.VoiceChannel):
                        _write_result(cmd_id, {"ok": False, "reason": "Channel not found or is not a voice channel."})
                        continue
                    _aj_cfg2 = load_config()
                    _aj_cfg2["bot"]["autojoin_channel"] = {"guild_id": _aj_target.guild.id, "channel_id": _aj_target.id}
                    with open(resource_path("config/config.yaml"), "w", encoding="utf-8") as _f:
                        _yaml_aj.dump(_aj_cfg2, _f, default_flow_style=False, allow_unicode=True)
                    _write_result(cmd_id, {"ok": True, "disabled": False, "channel": _aj_target.name, "guild": _aj_target.guild.name})

                # ── set_status ────────────────────────────────────────────────
                elif cmd == "set_status":
                    _st_emoji = payload.get("emoji")
                    _st_text  = payload.get("text")
                    try:
                        await bot.change_presence(
                            activity=discord.CustomActivity(name=_st_text or "", emoji=_st_emoji or None)
                        )
                        _write_result(cmd_id, {"ok": True})
                    except Exception as _e:
                        _write_result(cmd_id, {"ok": False, "reason": str(_e)})

                # ── set_bio ───────────────────────────────────────────────────
                elif cmd == "set_bio":
                    try:
                        await bot.user.edit(bio=payload.get("text", ""))
                        _write_result(cmd_id, {"ok": True})
                    except Exception as _e:
                        _write_result(cmd_id, {"ok": False, "reason": str(_e)})

                # ── set_pfp ───────────────────────────────────────────────────
                elif cmd == "set_pfp":
                    _pfp_url = payload.get("url", "")
                    _pfp_b64 = payload.get("b64", "")
                    try:
                        if _pfp_b64:
                            import base64 as _b64mod
                            _pfp_data = _b64mod.b64decode(_pfp_b64)
                        elif _pfp_url:
                            async with AsyncSession(impersonate="chrome") as _pfp_s:
                                _pfp_r = await _pfp_s.get(_pfp_url)
                                if _pfp_r.status_code != 200:
                                    _write_result(cmd_id, {"ok": False, "reason": f"Failed to fetch image (status {_pfp_r.status_code})."})
                                    continue
                                _pfp_data = _pfp_r.content
                        else:
                            _write_result(cmd_id, {"ok": False, "reason": "No image URL or data provided."})
                            continue
                        await bot.user.edit(avatar=_pfp_data)
                        _write_result(cmd_id, {"ok": True})
                    except Exception as _e:
                        _write_result(cmd_id, {"ok": False, "reason": str(_e)})

                # ── set_banner ────────────────────────────────────────────────
                elif cmd == "set_banner":
                    _banner_url = payload.get("url", "")
                    _banner_b64 = payload.get("b64", "")
                    try:
                        if _banner_b64:
                            import base64 as _b64mod
                            _banner_data = _b64mod.b64decode(_banner_b64)
                        elif _banner_url:
                            async with AsyncSession(impersonate="chrome") as _banner_s:
                                _banner_r = await _banner_s.get(_banner_url)
                                if _banner_r.status_code != 200:
                                    _write_result(cmd_id, {"ok": False, "reason": f"Failed to fetch image (status {_banner_r.status_code})."})
                                    continue
                                _banner_data = _banner_r.content
                        else:
                            _write_result(cmd_id, {"ok": False, "reason": "No image URL or data provided."})
                            continue
                        await bot.user.edit(banner=_banner_data)
                        _write_result(cmd_id, {"ok": True})
                    except Exception as _e:
                        _write_result(cmd_id, {"ok": False, "reason": str(_e)})

                # ── add_friend ────────────────────────────────────────────────
                # ── Friend requests, answered now rather than on a timer ──────
                # The background loop spreads accepts over hours on purpose, so
                # the account does not look automated. That is the right default
                # and the wrong thing when you are sitting there watching one
                # arrive, so the panel can take them straight away.
                elif cmd == "friends_pending":
                    _fr_out = []
                    try:
                        async with build_session(bot._connection.http.token) as _fr_s:
                            _fr_r = await _fr_s.get(
                                "https://discord.com/api/v9/users/@me/relationships")
                            if _fr_r.status_code != 200:
                                _write_result(cmd_id, {
                                    "ok": False,
                                    "reason": f"Discord answered {_fr_r.status_code}"})
                                continue
                            for _rel in _fr_r.json():
                                # 3 is an incoming request; 4 is one we sent.
                                if _rel.get("type") not in (3, 4):
                                    continue
                                _u = _rel.get("user", {}) or {}
                                _av = _u.get("avatar")
                                _uid = str(_rel.get("id"))
                                _fr_out.append({
                                    "id": _uid,
                                    "username": _u.get("username", ""),
                                    "display_name": _u.get("global_name")
                                    or _u.get("display_name") or "",
                                    "avatar": (f"https://cdn.discordapp.com/avatars/{_uid}/{_av}.webp?size=128"
                                               if _av else ""),
                                    "incoming": _rel.get("type") == 3,
                                    "since": _rel.get("since", ""),
                                    # None means no accept is scheduled: either
                                    # automatic accepting is off, or this one
                                    # arrived after the startup sweep.
                                    "accept_at": _friend_due.get(int(_rel.get("id") or 0)),
                                })
                    except Exception as _fe:
                        _write_result(cmd_id, {"ok": False, "reason": str(_fe)})
                        continue
                    _write_result(cmd_id, {"ok": True, "requests": _fr_out})

                elif cmd in ("friend_accept", "friend_decline"):
                    _fa_uid = int(payload["user_id"])
                    _accepting = cmd == "friend_accept"
                    try:
                        async with build_session(bot._connection.http.token) as _fa_s:
                            if _accepting:
                                _fa_r = await _fa_s.put(
                                    f"https://discord.com/api/v9/users/@me/relationships/{_fa_uid}",
                                    json={"type": 1})
                            else:
                                _fa_r = await _fa_s.delete(
                                    f"https://discord.com/api/v9/users/@me/relationships/{_fa_uid}")
                        if _fa_r.status_code in (200, 204):
                            _friend_due.pop(_fa_uid, None)
                            log_system(("Accepted" if _accepting else "Declined")
                                       + f" friend request from {_fa_uid}")
                            _write_result(cmd_id, {"ok": True})
                        else:
                            _write_result(cmd_id, {
                                "ok": False,
                                "reason": f"Discord answered {_fa_r.status_code}"})
                    except Exception as _fe:
                        _write_result(cmd_id, {"ok": False, "reason": str(_fe)})

                elif cmd == "add_friend":
                    _af_uid = int(payload["user_id"])
                    try:
                        async with build_session(bot.http.token) as _af_s:
                            _af_r = await _af_s.put(
                                f"https://discord.com/api/v9/users/@me/relationships/{_af_uid}",
                                json={"type": 1},
                            )
                            if _af_r.status_code in (200, 204):
                                _write_result(cmd_id, {"ok": True})
                            else:
                                try:
                                    _af_msg = _af_r.json().get("message", str(_af_r.status_code))
                                except Exception:
                                    _af_msg = f"HTTP {_af_r.status_code}"
                                _write_result(cmd_id, {"ok": False, "reason": _af_msg})
                    except Exception as _e:
                        _write_result(cmd_id, {"ok": False, "reason": str(_e)})

                # ── update (now handled via sentinel flag file) ───────────────
                elif cmd == "update":
                    # Telegram writes config/update.flag directly; this keeps
                    # the Discord /update command working too.
                    _upd_source = payload.get("source", "release")
                    if _upd_source not in ("release", "main"):
                        _upd_source = "release"
                    _upd_flag = _Path(resource_path("config/update.flag"))
                    _upd_flag.write_text(_upd_source)
                    # Do NOT re-append to remaining, the flag poller above
                    # would re-write the flag and fire the update twice.
                    _write_result(cmd_id, {"ok": True, "queued": True})

                # ── reload ────────────────────────────────────────────────────
                elif cmd == "reload":
                    _reload_errors = []
                    if getattr(sys, "frozen", False):
                        _cog_mods = ["app.cogs.general", "app.cogs.management", "app.cogs.error_handler"]
                    else:
                        import sys as _sys_r
                        _cogs_dir = os.path.join(getattr(_sys_r, "_MEIPASS", os.path.abspath(".")), "app", "cogs")
                        _cog_mods = [f"app.cogs.{f[:-3]}" for f in os.listdir(_cogs_dir)
                                     if f.endswith(".py")] if os.path.exists(_cogs_dir) else []
                    for _module in _cog_mods:
                        try:
                            await bot.unload_extension(_module)
                            await bot.load_extension(_module)
                        except Exception as _re:
                            _reload_errors.append(str(_re))
                    bot.instructions = load_instructions()
                    _write_result(cmd_id, {"ok": True, "errors": _reload_errors})

                # ── image_analyse ─────────────────────────────────────────────
                elif cmd == "image_analyse":
                    import base64 as _b64_ia
                    from app.utils.helpers import resource_path as _rp_ia
                    from app.utils.db import add_picture_description as _apd_ia
                    from app.utils.ai import _create_image_completion as _cic_ia
                    _ia_name = payload.get("name", "")
                    _ia_b64  = payload.get("b64", "")
                    _ia_ext  = payload.get("ext", ".jpg")
                    _ia_folder = _rp_ia("config/pictures")
                    _ia_path   = os.path.join(_ia_folder, _ia_name)
                    # If no b64 was sent (same-machine case), read the file
                    # from disk; otherwise decode and write it.
                    if not _ia_b64:
                        if os.path.exists(_ia_path):
                            with open(_ia_path, "rb") as _f:
                                _ia_b64 = _b64_ia.b64encode(_f.read()).decode()
                        else:
                            _write_result(cmd_id, {"ok": False, "reason": f"Image file not found: {_ia_name}"})
                            continue
                    elif not os.path.exists(_ia_path):
                        os.makedirs(_ia_folder, exist_ok=True)
                        with open(_ia_path, "wb") as _f:
                            _f.write(_b64_ia.b64decode(_ia_b64))
                    try:
                        _ia_cfg = load_config()
                        _ia_model = _ia_cfg["bot"].get("groq_image_model", "meta-llama/llama-4-scout-17b-16e-instruct")
                        _mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                                     ".gif": "image/gif", ".webp": "image/webp"}
                        _ia_mime = _mime_map.get(_ia_ext.lower(), "image/jpeg")
                        _ia_data_url = f"data:{_ia_mime};base64,{_ia_b64}"
                        log_system(f"Analysing image: {_ia_name}")
                        _ia_resp = await _cic_ia(
                            _ia_model,
                            messages=[{
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Describe this image in full detail exactly as you see it. Include all visible text, objects, people, colors, layout, and context."},
                                    {"type": "image_url", "image_url": {"url": _ia_data_url}},
                                ],
                            }],
                        )
                        _ia_desc = _ia_resp.choices[0].message.content.strip()
                        _apd_ia(_ia_name, _ia_desc)
                        log_system(f"Image analysed: {_ia_name}, {_ia_desc[:80]}")
                        _write_result(cmd_id, {"ok": True, "description": _ia_desc})
                    except Exception as _ia_e:
                        log_error("image_analyse", str(_ia_e))
                        _write_result(cmd_id, {"ok": False, "reason": str(_ia_e)})

                # ── image_setdesc ────────────────────────────────────────────
                elif cmd == "image_setdesc":
                    from app.utils.helpers import resource_path as _rp_isd
                    from app.utils.db import add_picture_description as _apd_isd
                    _isd_folder = _rp_isd("config/pictures")
                    _isd_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
                    _isd_name = payload.get("name", "")
                    _isd_desc = (payload.get("description") or "").strip()
                    _isd_files = sorted([f for f in os.listdir(_isd_folder) if os.path.splitext(f)[1].lower() in _isd_exts]) if os.path.exists(_isd_folder) else []
                    if _isd_name.isdigit():
                        _isd_matches = [f for f in _isd_files if os.path.splitext(f)[0] == f"IMG_{_isd_name}"]
                        _isd_name = _isd_matches[0] if _isd_matches else _isd_name
                    _isd_path = os.path.join(_isd_folder, _isd_name)
                    if not _isd_desc:
                        _write_result(cmd_id, {"ok": False, "reason": "Description can't be empty."})
                    elif not os.path.exists(_isd_path):
                        _write_result(cmd_id, {"ok": False, "reason": f"Image `{_isd_name}` not found."})
                    else:
                        _apd_isd(_isd_name, _isd_desc)
                        log_system(f"Description manually set for {_isd_name}: {_isd_desc[:80]}")
                        _write_result(cmd_id, {"ok": True, "name": _isd_name, "description": _isd_desc})

                # ── image_delete ──────────────────────────────────────────────
                elif cmd == "image_delete":
                    from app.utils.helpers import resource_path as _rp_img
                    from app.utils.db import delete_picture_db as _dpdb, rename_picture_db as _rpdb
                    _img_folder = _rp_img("config/pictures")
                    _img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
                    _del_name = payload.get("name", "")
                    _img_files = sorted([f for f in os.listdir(_img_folder) if os.path.splitext(f)[1].lower() in _img_exts]) if os.path.exists(_img_folder) else []
                    if _del_name.isdigit():
                        _matches = [f for f in _img_files if os.path.splitext(f)[0] == f"IMG_{_del_name}"]
                        _del_name = _matches[0] if _matches else _del_name
                    _del_path = os.path.join(_img_folder, _del_name)
                    if os.path.exists(_del_path):
                        os.remove(_del_path)
                        _dpdb(_del_name)
                        _remaining = sorted([f for f in os.listdir(_img_folder) if os.path.splitext(f)[1].lower() in _img_exts],
                                            key=lambda f: int(os.path.splitext(f)[0][4:]) if os.path.splitext(f)[0].startswith("IMG_") and os.path.splitext(f)[0][4:].isdigit() else 99999)
                        for _ri, _rfname in enumerate(_remaining, start=1):
                            _rstem, _rext = os.path.splitext(_rfname)
                            if _rstem.startswith("IMG_") and _rstem[4:].isdigit() and int(_rstem[4:]) != _ri:
                                _rnew = f"IMG_{_ri}{_rext}"
                                os.rename(os.path.join(_img_folder, _rfname), os.path.join(_img_folder, _rnew))
                                _rpdb(_rfname, _rnew)
                        _write_result(cmd_id, {"ok": True})
                    else:
                        _write_result(cmd_id, {"ok": False, "reason": f"Image `{_del_name}` not found."})

                # ── image_delete_multi ───────────────────────────────────────
                elif cmd == "image_delete_multi":
                    from app.utils.helpers import resource_path as _rp_idm
                    from app.utils.db import delete_picture_db as _dpdb_m, rename_picture_db as _rpdb_m
                    _idm_folder = _rp_idm("config/pictures")
                    _idm_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
                    _idm_names = payload.get("names", [])  # list of digit strings e.g. ["1","4","7"]
                    _idm_files = sorted(
                        [f for f in os.listdir(_idm_folder) if os.path.splitext(f)[1].lower() in _idm_exts],
                        key=lambda f: int(os.path.splitext(f)[0][4:])
                            if os.path.splitext(f)[0].startswith("IMG_") and os.path.splitext(f)[0][4:].isdigit()
                            else 99999
                    ) if os.path.exists(_idm_folder) else []
                    _idm_deleted = []
                    _idm_failed = []
                    for _idm_n in _idm_names:
                        _idm_matches = [f for f in _idm_files if os.path.splitext(f)[0] == f"IMG_{_idm_n}"]
                        if _idm_matches:
                            _idm_path = os.path.join(_idm_folder, _idm_matches[0])
                            try:
                                os.remove(_idm_path)
                                _dpdb_m(_idm_matches[0])
                                _idm_deleted.append(_idm_n)
                            except Exception:
                                _idm_failed.append(_idm_n)
                        else:
                            _idm_failed.append(_idm_n)
                    # Renumber remaining files once after all deletes
                    _idm_remaining = sorted(
                        [f for f in os.listdir(_idm_folder) if os.path.splitext(f)[1].lower() in _idm_exts],
                        key=lambda f: int(os.path.splitext(f)[0][4:])
                            if os.path.splitext(f)[0].startswith("IMG_") and os.path.splitext(f)[0][4:].isdigit()
                            else 99999
                    ) if os.path.exists(_idm_folder) else []
                    for _ri, _rfname in enumerate(_idm_remaining, start=1):
                        _rstem, _rext = os.path.splitext(_rfname)
                        if _rstem.startswith("IMG_") and _rstem[4:].isdigit() and int(_rstem[4:]) != _ri:
                            _rnew = f"IMG_{_ri}{_rext}"
                            os.rename(os.path.join(_idm_folder, _rfname), os.path.join(_idm_folder, _rnew))
                            _rpdb_m(_rfname, _rnew)
                    _write_result(cmd_id, {"ok": True, "deleted": _idm_deleted, "failed": _idm_failed})

                # ── image_delete_all ──────────────────────────────────────────
                elif cmd == "image_delete_all":
                    from app.utils.helpers import resource_path as _rp_imgd
                    from app.utils.db import clear_all_pictures_db as _capdb
                    _imgd_folder = _rp_imgd("config/pictures")
                    _imgd_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
                    if os.path.exists(_imgd_folder):
                        _imgd_files = [f for f in os.listdir(_imgd_folder) if os.path.splitext(f)[1].lower() in _imgd_exts]
                        for _f in _imgd_files:
                            os.remove(os.path.join(_imgd_folder, _f))
                        _capdb()
                        _write_result(cmd_id, {"ok": True, "count": len(_imgd_files)})
                    else:
                        _write_result(cmd_id, {"ok": True, "count": 0})

                else:
                    remaining.append(entry)

            except Exception as _err:
                log_error("TG IPC", f"cmd={cmd} error={_err}")
                _write_result(cmd_id, {"ok": False, "error": str(_err)})

        _flush_commands(_CMD_FILE, remaining, commands)


@bot.event
async def on_ready():
    if config["bot"]["owner_id"] == 123456789012345678:
        print(f"{Fore.RED}Error: Please set a valid owner_id in config.yaml{Style.RESET_ALL}")
        await bot.close()
        sys.exit(1)

    if config["bot"]["owner_id"] == bot.user.id:
        print(f"{Fore.RED}Error: owner_id in config.yaml cannot be the same as the bot account's user ID{Style.RESET_ALL}")
        await bot.close()
        sys.exit(1)

    bot.selfbot_id = bot.user.id

    # Record who this account actually is, so the panel can show the real
    # username and avatar instead of just "Discord #1". Written to a file
    # rather than fetched over IPC, so it is still there for a stopped account.
    try:
        import json as _idjson
        _identity = {
            "id": str(bot.user.id),
            "username": bot.user.name,
            "display_name": getattr(bot.user, "global_name", None) or bot.user.name,
            "avatar": str(bot.user.display_avatar.url) if getattr(bot.user, "display_avatar", None) else "",
            "seen": time.time(),
        }
        from pathlib import Path as _IdPath
        _idpath = _IdPath(resource_path(f"config/identity_{ACCOUNT_INDEX}.json"))
        _idpath.write_text(_idjson.dumps(_identity), encoding="utf-8")
    except Exception as _ie:
        log_system(f"[Identity] could not record account identity: {_ie}")

    clear_console()

    print_header()
    print(f"LLMSelfbot successfully logged in as {Fore.CYAN}{bot.user.name} ({bot.selfbot_id}){Style.RESET_ALL}.\n")
    log_system(f"Using model: {ai_module.model}")

    if config["bot"]["mood"].get("enabled", True):
        shift_mood()
        asyncio.create_task(mood_loop())

    print_separator()

    if config["bot"]["status"].get("enabled", True):
        asyncio.create_task(random_status_loop())

    # People who cannot be messaged, remembered across restarts. Without this
    # a blocked conversation reappeared on the waiting list on every launch,
    # and every reply to it failed with the same 403.
    try:
        from app.utils.db import blocked_users as _stored_blocked
        _blocked_users.update(_stored_blocked().keys())
        if _blocked_users:
            log_system(f"{len(_blocked_users)} conversation(s) cannot be messaged, skipping them")
    except Exception:
        pass

    asyncio.create_task(_reply_pending_messages())
    asyncio.create_task(_cleanup_loop())

    # Ground truth for the client-profile question: ask Discord what clients
    # it sees on this account. If an old web session from a previous run is
    # still lingering (killed process, no close frame), it shows up here too,
    # and Discord drops it within a minute or two.
    asyncio.create_task(_log_active_sessions())

    nudge_cfg = config["bot"].get("nudge") or {}
    if nudge_cfg.get("enabled", False):
        asyncio.create_task(_nudge_loop())

    fr_cfg = config["bot"].get("friend_requests") or {}
    if fr_cfg.get("enabled", False):
        asyncio.create_task(_friend_request_loop())

    asyncio.create_task(_tg_ipc_loop())


async def _log_active_sessions():
    """Ask Discord's sessions endpoint which clients it sees on this account.

    One call per login, logged once. This is the authoritative answer to
    "does the profile say web or desktop": each session's client_info comes
    straight from what the IDENTIFY payload claimed.
    """
    try:
        await asyncio.sleep(3)
        async with build_session(bot._connection.http.token) as s:
            resp = await s.get("https://discord.com/api/v9/users/@me/sessions")
            if resp.status_code != 200:
                log_system(f"[SESSIONS] endpoint returned {resp.status_code}")
                return
            for sess in resp.json():
                ci = sess.get("client_info") or {}
                log_system(
                    f"[SESSIONS] client={ci.get('client')} os={ci.get('os')} "
                    f"platform={ci.get('platform')} status={sess.get('status')}"
                )
    except Exception as e:
        log_error("Sessions Check", str(e))


async def setup_hook():
    bot.generate_response_and_reply = generate_response_and_reply
    await _apply_client_profile()

    # Proof of what the gateway will identify as: logs the exact properties
    # the IDENTIFY payload carries on the first connect of each session.
    async def _log_identify(initial: bool = False):
        if not initial:
            return
        try:
            props = bot.http.headers.super_properties
            log_system(
                f"[IDENTIFY] browser={props.get('browser')} "
                f"build={props.get('client_build_number')} "
                f"channel={props.get('release_channel')}"
            )
        except Exception:
            pass

    bot.before_identify_hook = _log_identify

    await load_extensions()

bot.setup_hook = setup_hook

# Raw message_reference cache: message_id -> referenced_message_id.
# discord.py-self sometimes drops message.reference for server channels; we
# catch it here from the raw gateway payload before it's stripped.
_raw_reply_cache: dict[int, int] = {}
_RAW_REPLY_CACHE_MAX = 500

@bot.event
async def on_socket_raw_receive(data):
    import json
    try:
        if isinstance(data, bytes):
            return  # compressed, skip
        payload = json.loads(data)
        if payload.get("t") != "MESSAGE_CREATE":
            return
        d = payload.get("d", {})
        msg_id = int(d["id"]) if d.get("id") else None
        if not msg_id:
            return

        # Cache bot's own message IDs so replies to manual messages are detected
        author_id = int(d.get("author", {}).get("id", 0))
        if author_id and hasattr(bot, "selfbot_id") and author_id == bot.selfbot_id:
            _raw_reply_cache[msg_id] = 0  # 0 = "this is a bot message"

        # Cache reply references
        ref = d.get("message_reference")
        if ref:
            ref_id = int(ref.get("message_id", 0))
            if ref_id:
                _raw_reply_cache[msg_id] = ref_id

        while len(_raw_reply_cache) > _RAW_REPLY_CACHE_MAX:
            _raw_reply_cache.pop(next(iter(_raw_reply_cache)))
    except Exception:
        pass


def should_ignore_message(message):
    return (
        message.author.id in bot.ignore_users
        or message.author.id == bot.selfbot_id
        or message.author.bot
        or message.type not in (discord.MessageType.default, discord.MessageType.reply)
    )


async def is_trigger_message(message):
    mentioned = (
        bot.user.mentioned_in(message)
        and "@everyone" not in message.content
        and "@here" not in message.content
    )
    replied_to = False
    if message.reference:
        ref_id = message.reference.message_id
        ref_msg = message.reference.resolved
        if ref_msg is None or isinstance(ref_msg, discord.DeletedReferencedMessage):
            ref_msg = bot._connection._get_message(ref_id)
        if ref_msg and ref_msg.author.id == bot.user.id:
            replied_to = True
        elif ref_id in _raw_reply_cache and _raw_reply_cache[ref_id] == 0:
            # ref_id is cached as a bot-sent message (value 0 = bot's own message)
            replied_to = True
    elif message.id in _raw_reply_cache:
        ref_id = _raw_reply_cache[message.id]
        if ref_id == 0:
            replied_to = True  # replying to a bot message tracked via raw cache
        else:
            ref_msg = bot._connection._get_message(ref_id)
            if ref_msg and ref_msg.author.id == bot.user.id:
                replied_to = True
    is_dm = isinstance(message.channel, discord.DMChannel) and bot.allow_dm
    is_group_dm = isinstance(message.channel, discord.GroupChannel) and bot.allow_gc

    conv_key = f"{message.author.id}-{message.channel.id}"
    in_conversation = (
        conv_key in bot.active_conversations
        and time.time() - bot.active_conversations[conv_key] < CONVERSATION_TIMEOUT
        and bot.hold_conversation
        and not isinstance(message.channel, (discord.TextChannel, discord.Thread, discord.ForumChannel, discord.StageChannel, discord.VoiceChannel))
    )

    is_server = isinstance(message.channel, (discord.TextChannel, discord.Thread, discord.ForumChannel, discord.StageChannel, discord.VoiceChannel))

    if is_server and not getattr(bot, "allow_server", True):
        mentioned = False
        replied_to = False

    content_has_trigger = (
        not is_server
        and TRIGGER_RE is not None
        and TRIGGER_RE.search(message.content.lower()) is not None
    )

    if (
        content_has_trigger
        or mentioned
        or replied_to
        or is_dm
        or is_group_dm
        or in_conversation
    ):
        bot.active_conversations[conv_key] = time.time()

    return (
        content_has_trigger
        or mentioned
        or replied_to
        or is_dm
        or is_group_dm
        or in_conversation
    ), content_has_trigger, mentioned


_profile_cache: dict = {}  # user_id -> bio string, in-memory layer on top of DB

async def _get_user_profile_block(user) -> str:
    """Fetch profile info (status, bio, display name) as a context block.

    Bio is cached in-memory, then the DB, then fetched from Discord.
    """
    parts = []
    try:
        display = getattr(user, 'global_name', None) or user.display_name
        if display and display != user.name:
            parts.append(f"display name: {display}")

        if hasattr(user, 'activities') and user.activities:
            for activity in user.activities:
                if hasattr(activity, 'state') and activity.state:
                    parts.append(f"status: {activity.state}")
                    break
                elif hasattr(activity, 'name') and activity.name and str(type(activity).__name__) == 'CustomActivity':
                    parts.append(f"status: {activity.name}")
                    break

        # Bio lookup is opt-out via config: bot.read_bios
        if config["bot"].get("read_bios", True):
            # 1. Check in-memory cache
            if user.id in _profile_cache:
                bio = _profile_cache[user.id]
            else:
                # 2. Check persistent DB cache
                bio = get_cached_profile(user.id)
                # 3. Fetch from Discord and persist, budgeted so bulk sweeps
                #    (/analyse, /reply all) can't burst the profile endpoint.
                #    When the budget denies the fetch, leave the cache empty so
                #    a later message retries within the next window.
                if bio is None and profile_fetch_allowed():
                    try:
                        profile = await user.profile()
                        bio = getattr(profile, 'bio', None) or ""
                    except Exception:
                        bio = ""
                    # "" marks "known to have no bio" so we don't refetch it.
                    set_cached_profile(user.id, bio)
                    _profile_cache[user.id] = bio
                elif bio is not None:
                    _profile_cache[user.id] = bio

            if bio:
                parts.append(f"bio: {bio}")

    except Exception:
        pass

    if not parts:
        return ""
    return "\n[About this person: " + ", ".join(parts) + "]"


def _extract_image_url_from_message(message) -> str | None:
    """Extract an image URL from message embeds or raw image URLs in content."""
    # 1. Check Discord embeds (already parsed by discord.py)
    for embed in message.embeds:
        if embed.image and embed.image.url:
            return embed.image.url
        if embed.thumbnail and embed.thumbnail.url:
            if embed.thumbnail.width and embed.thumbnail.width < 100:
                continue
            return embed.thumbnail.url
        if embed.video and embed.thumbnail and embed.thumbnail.url:
            return embed.thumbnail.url

    # 2. Scan raw URLs in message content
    urls = re.findall(r'https?://\S+', message.content)
    image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
    known_image_hosts = (
        'imgur.com/', 'i.imgur.com/',
        'tenor.com/view/', 'media.tenor.com/',
        'giphy.com/gifs/', 'media.giphy.com/',
        'cdn.discordapp.com/', 'media.discordapp.net/',
        'pbs.twimg.com/', 'i.redd.it/',
    )
    for url in urls:
        clean = url.rstrip(')')
        if any(clean.lower().endswith(ext) for ext in image_exts):
            return clean
        if any(host in clean for host in known_image_hosts):
            return clean

    return None


def _get_random_picture() -> list | None:
    """Returns list of (type, path, description) tuples from config/pictures - only files with a stored description."""
    folder_path = resource_path("config/pictures")
    if not os.path.exists(folder_path):
        return None
    exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    descriptions = get_all_picture_descriptions()
    files = [
        ("file", os.path.join(folder_path, f), descriptions[f])
        for f in os.listdir(folder_path)
        if os.path.splitext(f)[1].lower() in exts and descriptions.get(f)
    ]
    return files if files else None


# asyncio only holds a weak reference to a running task, so a fire-and-forget
# create_task() can be collected before it finishes. Keeping them here until
# they are done is the documented way to stop that.
_memory_tasks: set = set()


def _spawn_memory_update(author, prompt, response):
    """Run the post-reply memory work without blocking the reply."""
    task = asyncio.create_task(_update_memory_after_reply(author, prompt, response))
    _memory_tasks.add(task)
    task.add_done_callback(_memory_tasks.discard)


async def _update_memory_after_reply(author, prompt, response):
    """Deletion detection and fact extraction, off the reply's critical path.

    Extraction runs on EVERY reply, same as the Snapchat engine path. The old
    "every 4th message" cadence silently dropped one-off facts ("my name is
    X") from short conversations. The extractor dedupes against stored facts
    and returns {} when there is nothing new, so the cost is one small-model
    call per reply - it just no longer happens where the user can feel it.
    """
    uid = author.id
    try:
        current_mem = bot._memory_cache.get(uid, {})
        if current_mem:
            keys_to_delete = await detect_memory_deletion(prompt, current_mem)
            for key in keys_to_delete:
                if key in current_mem:
                    delete_memory(uid, key)
                    bot._memory_cache.get(uid, {}).pop(key, None)
                    log_system(f"Memory deleted for {author.name}: {key}")

        current_mem_snapshot = dict(bot._memory_cache.get(uid, {}))
        facts = await extract_memory(prompt, response, existing_memory=current_mem_snapshot)
        for key, value in facts.items():
            value = str(value).strip()
            if not value:
                continue
            set_memory(uid, key, value)
            bot._memory_cache.setdefault(uid, {})[key] = value
            log_system(f"Memory saved for {author.name}: {key} = {value}")
    except Exception as mem_err:
        log_error("Memory Error", str(mem_err))


async def generate_response_and_reply(message, prompt, history, image_url=None, wait_time=0, bypass_cooldown=False, bypass_typing=False):
    uid = message.author.id
    if uid not in bot._memory_cache:
        bot._memory_cache[uid] = get_memory(uid)
    memory = bot._memory_cache[uid]
    memory_block = format_memory_for_prompt(memory)
    mood_block = f"\n\n[Right now: {get_mood_prompt()}]" if _MOOD_CFG.get("enabled", True) else ""

    profile_block = await _get_user_profile_block(message.author)

    if profile_block:
        if "display name:" in profile_block and "name" not in memory:
            try:
                display = getattr(message.author, 'global_name', None) or message.author.display_name
                if display and display != message.author.name:
                    set_memory(uid, "name", display)
                    memory["name"] = display
                    memory_block = format_memory_for_prompt(memory)
            except Exception:
                pass

    enriched_instructions = bot.instructions + mood_block + memory_block + profile_block

    # Per-user persona override: inject a custom tone/personality for this user.
    # It lives in user_memory under __persona__, so the get_memory() above has
    # already fetched it; get_persona() opened a second sqlite connection for a
    # value sitting in `memory`. format_memory_for_prompt() filters __-prefixed
    # keys, so it never leaks into the memory block.
    _persona = memory.get("__persona__")
    if _persona:
        enriched_instructions += (
            f"\n\n[PERSONA OVERRIDE FOR THIS USER: {_persona} "
            f"Maintain this persona for the entirety of this conversation.]"
        )

    # Tone: straight/casual in servers, emotional/personal in DMs and GCs
    if isinstance(message.channel, discord.TextChannel):
        enriched_instructions += (
            "\n\n[CONTEXT: You are in a public server channel. Keep your tone straight, "
            "casual and concise, no excessive emotions, no deep personal feelings, no vulnerability. "
            "Talk like a normal person chatting in a group chat. Short replies are fine.]"
        )
    else:
        enriched_instructions += (
            "\n\n[CONTEXT: You are in a private DM. You can be more open, emotional and personal here. "
            "Show genuine feelings, be warmer and more expressive than you would in a public server.]"
        )

    # Detect the user's language, cached per user, re-checked every 5 messages
    # so drift is caught without a Groq call per message.
    _default_lang = config["bot"].get("default_language", "en")
    _lang_entry = bot._lang_cache.get(uid, {"tag": _default_lang, "count": 0})
    _lang_entry["count"] += 1
    # Only (re)detect with enough text, short messages ("ok", "tg", "lol") are
    # ambiguous and caused wrong-language replies.
    _alpha = sum(ch.isalpha() for ch in (prompt or ""))
    if _alpha >= 8 and (_lang_entry["count"] == 1 or _lang_entry["count"] % 5 == 0):
        try:
            _detected = await detect_language(history, prompt)
            if _detected:
                _lang_entry["tag"] = _detected
        except Exception:
            pass
    bot._lang_cache[uid] = _lang_entry
    _lang_tag = _lang_entry["tag"]

    _LANG_NAMES = {
        "fr": "French", "en": "English", "es": "Spanish", "de": "German",
        "ar": "Arabic", "pt": "Portuguese", "it": "Italian", "nl": "Dutch",
        "ru": "Russian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
        "tr": "Turkish", "pl": "Polish", "sv": "Swedish",
    }
    _lang_display = _LANG_NAMES.get(_lang_tag, _lang_tag.upper())
    enriched_instructions += (
        f"\n\n[LANGUAGE: The user is writing in {_lang_display}. "
        f"Reply in {_lang_display} only, matching their casual tone and register.]"
    )

    # Output discipline, never leak meta into the actual message.
    enriched_instructions += (
        "\n\n[OUTPUT RULES: Reply with ONLY the exact message you are sending, nothing else. "
        "Never add translations, your reasoning, explanations, notes, labels, or alternate "
        "versions (no '(translation: ...)', no 'changed to', no 'in English:'). Output the raw message only.]"
    )

    # Verbosity profile + Discord reaction vocabulary
    enriched_instructions += style_block()
    enriched_instructions += reaction_rules()

    # Inject real France time so the AI always knows the current local time.
    _fr_time_str = france_time_str()
    if _fr_time_str:
        enriched_instructions += (
            f"\n\n[CURRENT TIME: It is currently {_fr_time_str} in France (Paris time). "
            f"Use this if someone asks what time or date it is, or if it's relevant to the conversation.]"
        )

    pics_cfg = config["bot"].get("pictures") or {}
    _available_pics = _get_random_picture() if pics_cfg.get("enabled", True) and is_picture_request(prompt) else None
    _chosen_pic_idx = None
    _chosen_pic_idx2 = None
    if _available_pics:
        _pic_list_str = "\n".join(f"{i}: {desc}" for i, (_t, _p, desc) in enumerate(_available_pics))
        enriched_instructions += (
            "\n\n[IMPORTANT: You ARE sending the user a photo of yourself RIGHT NOW in this very reply. "
            "The image is already attached and being sent. "
            "NEVER say 'maybe later', 'not right now', 'later', 'next time', 'maybe another time', or anything that implies you are NOT sending a photo - you already are. "
            "Do NOT describe or caption the photo. "
            "Just react casually like a real person who just hit send on a selfie, short, natural, confident.\n"
            "Here are the photos you could be sending, pick whichever best fits what was asked for "
            "(e.g. if they asked for a specific pose, outfit, or setting, match that):\n"
            f"{_pic_list_str}\n"
            "End your reply on its own new line with exactly: [[PIC:N|N2]] where N is your first-choice "
            "photo number and N2 is your second-best choice (a different number), used as a fallback only "
            "if your first choice turns out to be the same photo that was just sent last time. If there's "
            "only one photo available, use the same number for both. If none fit better than any other, "
            "just pick 0|1 (or 0|0 if only one exists). This tag will be removed before the user sees your "
            "message - never mention it or the numbering in your visible reply.]"
        )

    late_opener = ""
    if _LATE_CFG.get("enabled", True) and wait_time >= _LATE_CFG.get("threshold", 300):
        late_opener = get_late_opener(prompt)
        # Inject the opener as a system instruction so the AI weaves it in
        # naturally rather than prepending it raw (which caused punctuation
        # clashes and double apologies).
        enriched_instructions += (
            f"\n\n[LATE REPLY: You took a while to respond. Open your reply naturally "
            f"with something like: \"{late_opener.strip()}\", weave it in as the very "
            f"first words of your message, then continue normally. Do NOT add 'sorry' again "
            f"later in the message and do NOT start with a comma or dash.]"
        )

    if len(history) > 20:
        try:
            summarized = await summarize_history(history, enriched_instructions)
            if summarized:
                history = summarized
                key = f"{message.author.id}-{message.channel.id}"
                bot.message_history[key] = history
        except Exception:
            pass

    if message.attachments and (message.flags.value & (1 << 13)):
        try:
            import aiohttp as _aiohttp
            att = message.attachments[0]
            async with _aiohttp.ClientSession() as _session:
                async with _session.get(att.url) as _resp:
                    audio_bytes = await _resp.read()
            transcribed = await transcribe_voice(audio_bytes, filename=att.filename or "voice.ogg")
            if transcribed:
                log_system(f"Transcribed voice message from {message.author.name}: {transcribed}")
                prompt = f"[voice message: {transcribed}]" if not prompt else f"{prompt} [voice message: {transcribed}]"
        except Exception as _e:
            log_error("Voice Transcription", str(_e))

    max_retries = 3
    response = None
    _was_rate_limited = False

    # Simulate the bot "reading" the message before it starts typing.
    # DMs get a longer read delay (read receipts are visible there).
    # bypass_typing (fast-path replies) scales the same range down to ~40%.
    if bot.realistic_typing:
        if isinstance(message.channel, discord.DMChannel):
            _read_delay = (
                random.uniform(READ_DELAY_DM_MIN * 0.4, READ_DELAY_DM_MAX * 0.375)
                if bypass_typing
                else random.uniform(READ_DELAY_DM_MIN, READ_DELAY_DM_MAX)
            )
        elif isinstance(message.channel, discord.GroupChannel):
            _read_delay = (
                random.uniform(READ_DELAY_GROUP_MIN * 0.4, READ_DELAY_GROUP_MAX * 0.375)
                if bypass_typing
                else random.uniform(READ_DELAY_GROUP_MIN, READ_DELAY_GROUP_MAX)
            )
        else:
            _read_delay = (
                random.uniform(READ_DELAY_SERVER_MIN * 0.4, READ_DELAY_SERVER_MAX * 0.375)
                if bypass_typing
                else random.uniform(READ_DELAY_SERVER_MIN, READ_DELAY_SERVER_MAX)
            )
        await asyncio.sleep(_read_delay)

    # Humans open the chat before typing - DMs show a read receipt, so ack
    # the message now (before the typing indicator) like a real person would.
    if isinstance(message.channel, discord.DMChannel):
        try:
            await message.ack()
        except Exception:
            pass

    for attempt in range(max_retries):
        try:
            if not bot.realistic_typing:
                async with message.channel.typing():
                    if image_url:
                        response = await generate_response_image(prompt, enriched_instructions, image_url, history)
                    else:
                        response = await generate_response(prompt, enriched_instructions, history)
            else:
                if image_url:
                    response = await generate_response_image(prompt, enriched_instructions, image_url, history)
                else:
                    response = await generate_response(prompt, enriched_instructions, history)

            if response and is_refusal(response):
                log_error("AI Refusal", "Model refused to respond, trying next model...")
                # Rotate to the next model before retrying, different models refuse differently
                fallback_model()
                # Random delay before retry so the refusal loop doesn't fire instantly
                await asyncio.sleep(random.uniform(1.5, 4.0))
                response = None

            if response:
                # Memory upkeep is two more sequential Groq round trips, and
                # neither of them changes the reply that has just been
                # generated. Awaiting them here put 1-6 seconds between the
                # reply existing and the user seeing it, so they run alongside
                # the send instead. The trade is that a fact learned this turn
                # may not be in the cache yet if the same person fires another
                # message within a second or two.
                _spawn_memory_update(message.author, prompt, response)

                if late_opener:
                    # Opener is injected via system instruction above, no prepend.
                    log_system(f"Late reply opener injected for {message.author.name}")

                break

        except Exception as e:
            error_msg = str(e)
            if "Rate limit reached" in error_msg or "rate_limit_exceeded" in error_msg:
                _was_rate_limited = True
                time_match = re.search(r"try again in (?:(\d+)m\s*)?(?:(\d+(?:\.\d+)?)s)?", error_msg)
                if time_match:
                    minutes = int(time_match.group(1)) if time_match.group(1) else 0
                    seconds = float(time_match.group(2)) if time_match.group(2) else 0
                    total_wait = int((minutes * 60) + seconds + 5)
                    log_rate_limit(total_wait)
                    bot.paused = True
                    await asyncio.sleep(total_wait)
                    bot.paused = False
                    reset_client_index()
                    continue
            log_error("AI Error", error_msg)
            if attempt == max_retries - 1:
                notify_telegram_error("AI Error", error_msg)
                return None
            await asyncio.sleep(2)

    if not response:
        # The long 120s wait only makes sense after an actual rate limit.
        if not _was_rate_limited:
            return None
        log_error("AI Error", "Retrying one last time after rate limit wait...")
        await asyncio.sleep(120)
        try:
            if image_url:
                response = await generate_response_image(prompt, enriched_instructions, image_url, history)
            else:
                response = await generate_response(prompt, enriched_instructions, history)
        except Exception:
            pass
        # If the last-ditch retry is still a refusal, don't send it
        if response and is_refusal(response):
            log_error("AI Refusal", "Final retry still a refusal, dropping response.")
            return None

    if not response:
        return None

    response = strip_meta(response).replace("\u2014", "").replace("\u2013", "")

    # ── Reaction handling ─────────────────────────────────────────────────────
    # The model may end a reply with [[REACT:emoji]] (react + reply) or reply
    # with only [[REACT_ONLY:emoji]] (react, no text - a natural end-of-topic
    # or laugh-off). Emoji are allowlisted in behavior.py. React-only stays a
    # rare human thing: capped, and never used when it would leave a question
    # unanswered (the model is told that in the prompt).
    _react_emoji, _react_only = None, False
    _react_cfg = config["bot"].get("reactions") or {}
    if _react_cfg.get("enabled", True):
        response, _react_emoji, _react_only = parse_reaction_tag(
            response, reaction_emojis(_react_cfg))
        # The tag is stripped whatever happens; whether it is acted on is a
        # separate question. Telling a model to react "only when a human would"
        # gets a reaction on nearly every reply, because from inside one reply
        # there is always some reason to. This is the actual rate control.
        #
        # Gated only when there is text to send. A reaction is the entire reply
        # in the react-only case, and dropping it there would answer with
        # silence, which is worse than reacting too often.
        if _react_emoji and response.strip():
            if random.random() >= float(_react_cfg.get("chance", 0.3) or 0):
                _react_emoji = None
        # Never react-only when a voice or photo was asked for - those need
        # an actual reply.
        if _react_emoji and _react_only and not response and not is_tts_request(prompt) and not _available_pics:
            bot._reply_total = getattr(bot, "_reply_total", 0) + 1
            ratio_cap = _react_cfg.get("react_only_max_ratio", 0.1)
            within_cap = getattr(bot, "_react_only_count", 0) / max(1, bot._reply_total) <= ratio_cap
            if within_cap:
                bot._react_only_count = getattr(bot, "_react_only_count", 0) + 1
            # React-only reply: acknowledge, send nothing. If the cap was
            # hit we still react - silence would be worse than over-reacting.
            try:
                await asyncio.sleep(random.uniform(1.5, 4.0))
                await message.add_reaction(_react_emoji)
                channel_name, guild_name = get_channel_context(message)
                log_incoming(message.author.name, channel_name, guild_name, prompt)
                log_response(message.author.name, f"[reaction only] {_react_emoji}")
                separator()
            except Exception:
                pass
            return response  # "" signals "handled without text"

    if _available_pics:
        _pic_tag_match = re.search(r"\[\[PIC:(\d+)(?:\|(\d+))?\]\]\s*$", response)
        if _pic_tag_match:
            try:
                _idx = int(_pic_tag_match.group(1))
                _idx2 = int(_pic_tag_match.group(2)) if _pic_tag_match.group(2) is not None else None
                if 0 <= _idx < len(_available_pics):
                    _chosen_pic_idx = _idx
                    _log_msg = f"[PIC] AI chose #{_idx}: {_available_pics[_idx][2][:60]}"
                    if _idx2 is not None and 0 <= _idx2 < len(_available_pics):
                        _chosen_pic_idx2 = _idx2
                        _log_msg += f" (2nd choice #{_idx2}: {_available_pics[_idx2][2][:40]})"
                    log_system(_log_msg)
                else:
                    log_system(f"[PIC] AI returned out-of-range first choice {_idx} (have {len(_available_pics)} pics)")
                    if _idx2 is not None and 0 <= _idx2 < len(_available_pics):
                        _chosen_pic_idx2 = _idx2
            except ValueError:
                pass
            response = response[:_pic_tag_match.start()].rstrip()
        else:
            log_system(f"[PIC] No [[PIC:N|N2]] tag found in response, falling back to random. Raw tail: {response[-80:]!r}")
            # Tag missing or not at the end, strip any stray occurrence and
            # fall back to random selection.
            response = re.sub(r"\[\[PIC:\d+(?:\|\d+)?\]\]", "", response).strip()

    tts_cfg = config["bot"].get("tts") or {}
    if tts_cfg.get("enabled", True) and is_tts_request(prompt):
        try:
            spoken_instructions = (
                enriched_instructions
                + "\n\n[IMPORTANT: You are sending a voice message. Short, natural, zero cringe. 1-2 sentences max.]"
            )
            spoken_response = await generate_response(prompt, spoken_instructions, history)
            if not spoken_response or is_refusal(spoken_response):
                spoken_response = response
            spoken_response = spoken_response.replace("\u2014", "").replace("\u2013", "")

            channel_name, guild_name = get_channel_context(message)
            log_incoming(message.author.name, channel_name, guild_name, prompt)
            log_response(message.author.name, f"[Voice Message] {spoken_response}")
            separator()

            audio_chunks = await generate_voice_message(spoken_response)
            if audio_chunks:
                for i, audio_bytes in enumerate(audio_chunks):
                    reply_msg = message if i == 0 else None
                    await send_voice_message(
                        message.channel,
                        audio_bytes,
                        reply_to=reply_msg,
                        mention_author=config["bot"]["reply_ping"],
                    )
                bot.last_global_send = time.time()
            else:
                log_error("TTS", "generate_voice_message returned None - check Groq TTS API key and model")
            return spoken_response
        except Exception as e:
            log_error("TTS Failed", str(e))

    chunks = split_response(response)

    # ── Style-aware chunking ──────────────────────────────────────────────────
    # Humans send short messages, not paragraphs: split long replies at
    # sentence boundaries and cap both the chunk size and the number of
    # follow-up messages per verbosity mode. Overflow is merged into the last
    # message so no content is ever dropped.
    _style_cfg = config["bot"].get("message_style") or {}
    _style_mode = _style_cfg.get("mode", "balanced")
    _style_defaults = {"short": (180, 2), "balanced": (400, 3), "chatty": (800, 4)}
    _style_max_chars, _style_max_chunks = _style_defaults.get(_style_mode, _style_defaults["balanced"])
    _style_max_chars = int(_style_cfg.get("max_chunk_chars", _style_max_chars))
    _style_pieces = []
    for _c in chunks:
        _style_pieces.extend(style_chunk_split(_c, _style_max_chars))
    if len(_style_pieces) > _style_max_chunks:
        _overflow = _style_pieces[_style_max_chunks - 1:]
        _style_pieces = _style_pieces[:_style_max_chunks - 1]
        _style_pieces.append(" ".join(_overflow)[:1900])
    chunks = _style_pieces

    # Global cooldown: human gap between replies so different conversations
    # never land seconds apart. Skipped with bypass_cooldown or when disabled.
    if not bypass_cooldown and GLOBAL_COOLDOWN_ENABLED:
        _time_since_last = time.time() - bot.last_global_send
        _global_cooldown_gap = random.uniform(GLOBAL_COOLDOWN_MIN, GLOBAL_COOLDOWN_MAX)
        if _time_since_last < _global_cooldown_gap:
            await asyncio.sleep(_global_cooldown_gap - _time_since_last)

    # Small pre-lock jitter: prevents perfectly serialized sends from looking
    # mechanical when multiple users are active at the same time.
    await asyncio.sleep(random.uniform(0.1, 1.2))
    async with bot.global_send_lock:
        pics_cfg = config["bot"].get("pictures") or {}
        if _available_pics and pics_cfg.get("enabled", True):
            all_pics = _available_pics
            uid = message.author.id
            last_sent = bot.last_sent_picture.get(uid)
            # Only exclude the single most-recently-sent picture (no consecutive
            # repeats). Falls back to the full list if there's only one picture.
            available = [p for p in all_pics if p[1] != last_sent] or all_pics
            # Try the AI's first choice, then its second choice, before falling
            # back to a true random pick (only if both choices are unusable).
            _chosen_entry = None
            if _chosen_pic_idx is not None and 0 <= _chosen_pic_idx < len(all_pics):
                _candidate = all_pics[_chosen_pic_idx]
                if _candidate in available:
                    _chosen_entry = _candidate
            if _chosen_entry is None and _chosen_pic_idx2 is not None and 0 <= _chosen_pic_idx2 < len(all_pics):
                _candidate2 = all_pics[_chosen_pic_idx2]
                if _candidate2 in available:
                    _chosen_entry = _candidate2
                    log_system(
                        f"[PIC] 1st choice #{_chosen_pic_idx} was the last picture sent, "
                        f"using 2nd choice #{_chosen_pic_idx2} instead"
                    )
            if _chosen_entry is None and _chosen_pic_idx is not None:
                log_system("[PIC] Both AI choices unusable, falling back to true random")
            pic_type, pic_value, _pic_desc = _chosen_entry or random.choice(available)
            if not _chosen_entry and _chosen_pic_idx is not None:
                log_system(f"[PIC] Sent random fallback instead: {_pic_desc[:60]}")
            bot.last_sent_picture[uid] = pic_value
            try:
                if bot.realistic_typing:
                    await asyncio.sleep(random.uniform(1, 3))
                # Same reply fallback as the text path: a channel that rejects
                # a reply payload can still receive the picture perfectly well.
                _pic_kwargs = {"file": discord.File(pic_value)} if pic_type == "file"                     else {"content": pic_value}
                await _send_here(message, _pic_kwargs)
            except Exception as _pe:
                _pd = _detail(_pe)
                log_error("Picture Send", str(_pe) + (f" | {_pd}" if _pd else ""))

        channel_name, guild_name = get_channel_context(message)
        # Whether anything actually reached Discord, as opposed to being generated.
        _delivered = False
        for i, chunk in enumerate(chunks):
            if getattr(bot, "disable_mentions", DISABLE_MENTIONS):
                chunk = chunk.replace("@", "@\u200b")

            if bot.anti_age_ban:
                # Only obfuscate numbers that appear in an age context, e.g.
                # "I'm 12", not innocent content like "Chapter 5" or "3 cats".
                chunk = re.sub(
                    r"(?i)\b(i(?:'m| am| was)|she(?:'s| is| was)|he(?:'s| is| was)|they(?:'re| are| were)|age[:\s]+|aged?)\s+([0-9]|1[0-2])\b",
                    lambda m: m.group(1) + " \u200b",
                    chunk,
                )
                chunk = re.sub(
                    r"(?i)\b([0-9]|1[0-2])\s+(year(?:s)?(?:\s+old)?|yo\b)",
                    "\u200b \u200b",
                    chunk,
                )

            chunk = add_typo(chunk, config["bot"]["typo_chance"])
            if i == 0:
                log_incoming(message.author.name, channel_name, guild_name, prompt)
            log_response(message.author.name, chunk)
            separator()

            try:
                # React before replying when the model called for one - humans
                # often drop the emoji first, then start typing.
                if i == 0 and _react_emoji:
                    try:
                        await asyncio.sleep(random.uniform(0.8, 2.5))
                        await message.add_reaction(_react_emoji)
                        log_response(message.author.name, f"[reaction] {_react_emoji}")
                    except Exception:
                        pass

                if bot.realistic_typing:
                    if bypass_typing:
                        if i > 0:
                            await asyncio.sleep(random.uniform(1.0, 2.5))
                        await _simulate_typing(message.channel, chunk, fast=True)
                    else:
                        # Short think before typing; follow-up chunks come
                        # 2-8s later (humans split a thought and hit send,
                        # they don't wander off for 15 seconds mid-message).
                        pre_delay = random.uniform(2, 8)
                        await asyncio.sleep(pre_delay)
                        await _simulate_typing(message.channel, chunk, fast=False)
                else:
                    if i > 0:
                        await asyncio.sleep(random.uniform(2, 8) if not bypass_typing else random.uniform(1.0, 2.5))

                if isinstance(message.channel, discord.DMChannel):
                    sent_msg = await message.channel.send(chunk)
                elif message.channel.id in _no_reply_channels:
                    # This channel has already rejected a reply once, so do not
                    # spend another failed request finding that out again.
                    sent_msg = await message.channel.send(chunk)
                else:
                    try:
                        sent_msg = await message.reply(
                            chunk, mention_author=config["bot"]["reply_ping"])
                    except discord.HTTPException as _re:
                        # 50035 is Discord rejecting the shape of the request,
                        # not the text. It happens on replies in some channels,
                        # group DMs among them, and the message itself is
                        # perfectly sendable: so send it, plainly, rather than
                        # dropping the reply entirely.
                        if _re.code != 50035:
                            raise
                        _no_reply_channels.add(message.channel.id)
                        log_system(
                            "Replies are not accepted in this chat, "
                            f"sending without one from now on ({_detail(_re)})")
                        sent_msg = await message.channel.send(chunk)
                bot.last_global_send = time.time()
                _delivered = True

                # Rare human behaviour: fix a small slip right after sending.
                if random.random() < config["bot"].get("edit_after_send_chance", 0.015):
                    asyncio.create_task(_maybe_edit_after_send(sent_msg, chunk))

            except discord.Forbidden:
                # 403 on a send means the door is shut: blocked, DMs closed, or
                # no longer friends. That never clears by itself, so the
                # conversation comes off the waiting list instead of being
                # retried on every sweep for ever.
                log_error("Reply Error",
                          f"403 Forbidden - cannot send to {message.author.name}, "
                          "they have blocked the account or closed their DMs")
                try:
                    from app.utils.db import drop_unresponded, add_blocked
                    drop_unresponded(message.author.id)
                    _blocked_users.add(message.author.id)
                    add_blocked(message.author.id,
                                "blocked the account or closed their DMs")
                    log_system(f"Removed {message.author.name} from the waiting list")
                except Exception:
                    pass
                return None
            except Exception as e:
                _extra = _detail(e)
                log_error("Reply Error", str(e) + (f" | {_extra}" if _extra else ""))

    # The caller treats a returned string as "this was sent", and the panel
    # reports it as a successful reply. Returning the text after every send
    # failed said the message had gone out when nothing had left the process,
    # so the conversation stayed unanswered while the panel said otherwise.
    if not _delivered:
        return None
    return response


@bot.event
async def on_relationship_remove(relationship):
    """Track users who unfriend/remove the bot so we can re-add them instantly if they send a new request."""
    try:
        if relationship.type == discord.RelationshipType.friend:
            bot.removed_friends.add(relationship.user.id)
            log_system(f"{relationship.user.name} removed the bot as a friend, will re-add instantly if they send a request")
    except Exception as e:
        log_error("Relationship Remove", str(e))


@bot.event
async def on_relationship_add(relationship):
    try:
        if relationship.type != discord.RelationshipType.incoming_request:
            return
        fr_cfg = config["bot"].get("friend_requests") or {}
        if not fr_cfg.get("enabled", False):
            return
        user = relationship.user

        # Previously-removed friends get a shorter delay, but never instant
        # (0s accept = bot pattern).
        if user.id in bot.removed_friends:
            bot.removed_friends.discard(user.id)
            delay = random.randint(60, 180)
            log_system(f"Friend request from {user.name} (was previously a friend), accepting in {delay}s")
        else:
            delay = random.randint(
                fr_cfg.get("accept_delay_min", 120),
                fr_cfg.get("accept_delay_max", 600),
            )
            log_system(f"Friend request from {user.name}, will accept in {delay}s")

        # Per-user jitter so rapid incoming requests don't all fire at the
        # exact same second (a bot-detection red flag).
        jitter = random.randint(0, 120)
        final_delay = delay + jitter

        async def _accept(u, d):
            try:
                if d > 0:
                    await asyncio.sleep(d)
                async with build_session(bot._connection.http.token) as session:
                    resp = await session.put(
                        f"https://discord.com/api/v9/users/@me/relationships/{u.id}",
                        json={"type": 1},
                    )
                    if resp.status_code in (200, 204):
                        log_system(f"Accepted friend request from {u.name}")
                    elif resp.status_code == 401:
                        asyncio.create_task(_shutdown_on_401())
                    else:
                        try:
                            data = resp.json()
                            log_error("Friend Request Accept", f"{resp.status_code}: {data}")
                        except Exception:
                            log_error("Friend Request Accept", f"HTTP {resp.status_code}")
            except Exception as e:
                log_error("Friend Request Accept", str(e))

        asyncio.create_task(_accept(user, final_delay))
    except Exception as e:
        log_error("Friend Request Error", str(e))


# Who we have already recorded recently, so a busy channel is not a database
# write per message.
_profile_seen: dict = {}
_PROFILE_REFRESH = 3600.0

async def _send_here(message, kwargs: dict):
    """Send into this message's channel, replying to it where that is allowed.

    Discord rejects a reply payload in some channels with 50035, group DMs
    among them. The message itself is fine, so the reply is dropped rather than
    the message, and the channel is remembered so the next one goes straight
    out.
    """
    channel = message.channel
    if isinstance(channel, discord.DMChannel) or channel.id in _no_reply_channels:
        return await channel.send(**kwargs)
    try:
        return await message.reply(mention_author=config["bot"]["reply_ping"], **kwargs)
    except discord.HTTPException as exc:
        if exc.code != 50035:
            raise
        _no_reply_channels.add(channel.id)
        log_system("Replies are not accepted in this chat, sending without one "
                   f"from now on ({_detail(exc)})")
        return await channel.send(**kwargs)


# Channels where Discord refuses a reply payload. Learned the first time it
# happens, so the bot sends plainly there instead of failing every message.
_no_reply_channels: set = set()


def _detail(exc) -> str:
    """The part of a Discord error that says what was actually wrong.

    str(HTTPException) is "400 Bad Request (error code: 50035): Invalid Form
    Body", which names the category and nothing else. The body carries the
    field that failed, and without it a 50035 is unfixable guesswork.
    """
    try:
        text = getattr(exc, "text", "") or ""
        errors = getattr(exc, "errors", None)
        if errors:
            import json as _json
            return _json.dumps(errors)[:400]
        return " ".join(text.split())[:400]
    except Exception:
        return ""


# People who have blocked the account or closed their DMs, noticed on a 403.
# Recorded so the panel can say why a reply was abandoned rather than just
# reporting a failure that looks retryable.
_blocked_users: set = set()

# When each pending friend request is due to be accepted, as a unix timestamp.
# The accepts are deliberately spread over hours so the account does not look
# scripted, which is right but opaque: the panel reads this to say exactly when
# each one is coming, and to offer taking it now instead.
_friend_due: dict = {}


def _cache_author(user) -> None:
    """Record a name, handle and avatar for the panel's profile card.

    Everything here is already on the message object, so there is no API call
    and no cost beyond an occasional row update. Avatars are asked for at 128px
    because that is roughly twice the size the card draws them, which keeps them
    crisp on a high density screen.
    """
    try:
        uid = getattr(user, "id", None)
        if not uid:
            return
        now = time.time()
        if now - _profile_seen.get(uid, 0.0) < _PROFILE_REFRESH:
            return
        _profile_seen[uid] = now

        avatar = ""
        asset = getattr(user, "display_avatar", None)
        if asset is not None:
            try:
                avatar = asset.replace(size=128).url
            except Exception:
                avatar = str(getattr(asset, "url", "") or "")

        from app.utils.db import set_profile_details
        set_profile_details(
            uid,
            username=getattr(user, "name", None),
            display_name=getattr(user, "global_name", None)
            or getattr(user, "display_name", None),
            avatar=avatar or None,
        )
    except Exception:
        pass          # never let bookkeeping break message handling


@bot.event
async def on_message(message):
    if message.author.id == bot.selfbot_id:
        if message.content.startswith(PREFIX):
            await bot.process_commands(message)
        return

    # Remember who this is, for the profile card in the panel. Every value is
    # already on the message object, so it costs nothing, and it belongs here
    # rather than on the reply path: the bot sees far more people than it
    # answers, and the ones it ignores are exactly the ones you want to look up.
    _cache_author(message.author)

    # They can message again, so whatever closed the channel has been undone.
    if message.author.id in _blocked_users:
        _blocked_users.discard(message.author.id)
        try:
            from app.utils.db import remove_blocked
            remove_blocked(message.author.id)
        except Exception:
            pass

    # Owner priority trigger: owner's own message starting with PRIORITY_PREFIX.
    # Must stay outside the selfbot guard, it fires on messages FROM the owner.
    if message.author.id == OWNER_ID and message.content.startswith(PRIORITY_PREFIX):
        hint = message.content[len(PRIORITY_PREFIX):].lstrip()
        target_msg = None

        # If the owner replied to someone, use that message
        if message.reference and message.reference.resolved:
            ref = message.reference.resolved
            if isinstance(ref, discord.Message):
                target_msg = ref

        # Otherwise find the last non-bot/non-owner message in this channel
        if target_msg is None:
            try:
                for msg_id, ref_id in reversed(list(_raw_reply_cache.items())):
                    cached = bot._connection._get_message(msg_id)
                    if cached and cached.channel.id == message.channel.id and cached.author.id != bot.selfbot_id and cached.author.id != OWNER_ID and cached.type == discord.MessageType.default:
                        target_msg = cached
                        break
                if target_msg is None:
                    async for msg in message.channel.history(limit=10):
                        if msg.author.id != bot.selfbot_id and msg.author.id != OWNER_ID and msg.type == discord.MessageType.default:
                            target_msg = msg
                            break
            except Exception as e:
                log_error("Priority Trigger", str(e))

        if target_msg is None:
            return

        user_id = target_msg.author.id
        key = f"{user_id}-{target_msg.channel.id}"

        if key not in bot.message_history:
            bot.message_history[key] = []

        combined = hint if hint else target_msg.content

        # Append `combined` (not the raw target message), when a hint is
        # supplied, generate_response() drives off history, so the hint must
        # live in history or it gets silently dropped.
        bot.message_history[key].append({"role": "user", "content": combined})
        if len(bot.message_history[key]) > MAX_HISTORY * 2:
            bot.message_history[key] = bot.message_history[key][-(MAX_HISTORY * 2):]

        history = bot.message_history[key]
        log_system(f"Priority trigger by owner → responding to {target_msg.author.name} in #{getattr(target_msg.channel, 'name', 'DM')}")
        response = await generate_response_and_reply(target_msg, combined, history, wait_time=0)
        if response:
            bot.message_history[key].append({"role": "assistant", "content": response})
        return

    if should_ignore_message(message):
        return

    # Ignore sticker-only messages, stickers show up as attachments with no text
    if message.stickers and not message.content:
        return

    if message.author.id in bot.paused_users:
        return

    if message.content.startswith(PREFIX) and message.author.id == OWNER_ID:
        await bot.process_commands(message)
        return

    channel_id = message.channel.id
    user_id = message.author.id
    current_time = time.time()
    batch_key = f"{user_id}-{channel_id}"
    is_server_channel = isinstance(message.channel, (discord.TextChannel, discord.Thread, discord.ForumChannel, discord.StageChannel, discord.VoiceChannel))
    is_followup = batch_key in bot.user_message_batches and not is_server_channel
    is_trigger, content_has_trigger, mentioned = await is_trigger_message(message)

    if (is_trigger or (is_followup and bot.hold_conversation)) and not bot.paused:
        if (
            random.random() < IGNORE_CHANCE
            and not (content_has_trigger and TRIGGER_BYPASSES_IGNORE)
            and not (mentioned and MENTION_BYPASSES_IGNORE)
            and not message.content.startswith(PREFIX)
            and not message.content.startswith(PRIORITY_PREFIX)
        ):
            log_system(f"Ignored message from {message.author.name} (chance skip)")
            return

        if user_id in bot.user_cooldowns:
            cooldown_end = bot.user_cooldowns[user_id]
            if current_time < cooldown_end:
                return
            else:
                del bot.user_cooldowns[user_id]

        if user_id not in bot.user_message_counts:
            bot.user_message_counts[user_id] = []

        bot.user_message_counts[user_id] = [t for t in bot.user_message_counts[user_id] if current_time - t < SPAM_TIME_WINDOW]
        bot.user_message_counts[user_id].append(current_time)

        if len(bot.user_message_counts[user_id]) > SPAM_MESSAGE_THRESHOLD:
            bot.user_cooldowns[user_id] = current_time + COOLDOWN_DURATION
            return

        if batch_key not in bot.message_queues:
            bot.message_queues[batch_key] = deque()
            bot.processing_locks[batch_key] = Lock()

        bot.message_queues[batch_key].append(message)
        # Track DM messages for the nudge system, will be cleared once we reply
        if isinstance(message.channel, discord.DMChannel):
            nudge_cfg = config["bot"].get("nudge") or {}
            if nudge_cfg.get("enabled", False):
                add_unresponded(user_id, channel_id, message.content, time.time())
        if not bot.processing_locks[batch_key].locked():
            asyncio.create_task(process_message_queue(batch_key))


async def process_message_queue(batch_key):
    lock = bot.processing_locks.get(batch_key)
    if lock is None:
        return
    async with lock:
        try:
            while bot.message_queues.get(batch_key):
                message = bot.message_queues[batch_key].popleft()
                current_time = time.time()
                message_age = current_time - message.created_at.timestamp()

                if bot.batch_messages:
                    # A leftover batch entry (from an earlier error) would otherwise
                    # skip the block below and leave the reply variables unbound.
                    if batch_key in bot.user_message_batches:
                        bot.user_message_batches.pop(batch_key, None)
                    first_image_url = None
                    if message.attachments:
                        att = message.attachments[0]
                        if not (message.flags.value & (1 << 13)):
                            first_image_url = att.url
                    if not first_image_url:
                        first_image_url = _extract_image_url_from_message(message)
                    bot.user_message_batches[batch_key] = {
                        "messages": [message],
                        "last_time": current_time,
                        "image_url": first_image_url,
                    }
                    priority = message.content.startswith(PRIORITY_PREFIX)
                    wait_time = 0 if priority else get_batch_wait_time()
                    bot.user_message_batches[batch_key]["reply_at"] = current_time + wait_time
                    channel_name, guild_name = get_channel_context(message)
                    log_received(message.author.name, channel_name, guild_name, wait_time)
                    if not priority:
                        await asyncio.sleep(wait_time)

                    # Keep collecting messages until the user stops sending.
                    # High variance mimics real human pause patterns.
                    BATCH_TAIL_WAIT = random.uniform(BATCH_TAIL_WAIT_MIN, BATCH_TAIL_WAIT_MAX)
                    BATCH_POLL_INTERVAL = 0.3
                    last_received = time.time()
                    while True:
                        collected_any = False
                        while bot.message_queues[batch_key]:
                            next_message = bot.message_queues[batch_key][0]
                            if not next_message.content.startswith(PREFIX):
                                next_message = bot.message_queues[batch_key].popleft()
                                bot.user_message_batches[batch_key]["messages"].append(next_message)
                                if not bot.user_message_batches[batch_key]["image_url"] and next_message.attachments:
                                    bot.user_message_batches[batch_key]["image_url"] = next_message.attachments[0].url
                                last_received = time.time()
                                collected_any = True
                            else:
                                break
                        if not collected_any and time.time() - last_received >= BATCH_TAIL_WAIT:
                            break
                        await asyncio.sleep(BATCH_POLL_INTERVAL)

                    unique_messages = []
                    seen = set()
                    for msg in bot.user_message_batches[batch_key]["messages"]:
                        if msg.content not in seen:
                            seen.add(msg.content)
                            unique_messages.append(msg)
                    combined_content = "\n".join(msg.content for msg in unique_messages)
                    if combined_content.startswith(PRIORITY_PREFIX):
                        combined_content = combined_content[len(PRIORITY_PREFIX):].lstrip()
                    message_to_reply_to = unique_messages[-1]
                    image_url = bot.user_message_batches[batch_key]["image_url"]
                    del bot.user_message_batches[batch_key]
                else:
                    combined_content = message.content
                    message_to_reply_to = message
                    image_url = message.attachments[0].url if (message.attachments and not (message.flags.value & (1 << 13))) else _extract_image_url_from_message(message)
                    wait_time = 0

                key = f"{message_to_reply_to.author.id}-{message_to_reply_to.channel.id}"
                if key not in bot.message_history:
                    bot.message_history[key] = []
                bot.message_history[key].append({"role": "user", "content": combined_content})
                if len(bot.message_history[key]) > MAX_HISTORY * 2:
                    bot.message_history[key] = bot.message_history[key][-(MAX_HISTORY * 2):]
                history = bot.message_history[key]

                # ── Stale reply guard (servers & group chats only) ───────────────
                # If the channel moved on significantly since the triggering message,
                # skip the reply so the bot doesn't resurface a buried conversation.
                _is_public = isinstance(message_to_reply_to.channel, (
                    discord.TextChannel, discord.Thread, discord.ForumChannel,
                    discord.StageChannel, discord.GroupChannel,
                ))
                if _is_public and _STALE_CFG.get("enabled", False):
                    _stale_max_msgs = _STALE_CFG.get("max_messages", 10)
                    _stale_min_age  = _STALE_CFG.get("min_age", 120)
                    _msg_age = time.time() - message_to_reply_to.created_at.timestamp()
                    if _msg_age >= _stale_min_age:
                        try:
                            _newer_count = 0
                            async for _m in message_to_reply_to.channel.history(limit=_stale_max_msgs + 1):
                                if _m.id == message_to_reply_to.id:
                                    break
                                _newer_count += 1
                            if _newer_count >= _stale_max_msgs:
                                channel_name, guild_name = get_channel_context(message_to_reply_to)
                                log_system(
                                    f"Skipped stale reply to {message_to_reply_to.author.name} "
                                    f"in {channel_name}, {_newer_count} newer messages, "
                                    f"message was {int(_msg_age)}s old"
                                )
                                continue
                        except Exception:
                            pass
                # ─────────────────────────────────────────────────────────────────

                response = await generate_response_and_reply(message_to_reply_to, combined_content, history, image_url, wait_time=(wait_time + message_age))
                if response:
                    bot.message_history[key].append({"role": "assistant", "content": response})
                    record_user_message(message_to_reply_to.author.id, message_to_reply_to.author.name)
                    # Clear the nudge tracking entry, we've replied
                    nudge_cfg = config["bot"].get("nudge") or {}
                    if nudge_cfg.get("enabled", False) and isinstance(message_to_reply_to.channel, discord.DMChannel):
                        mark_responded(message_to_reply_to.author.id, message_to_reply_to.channel.id)
        finally:
            if bot.message_queues.get(batch_key):
                # A message landed while we were finishing: on_message saw the
                # lock held and skipped spawning, so it would sit unanswered
                # until the next message arrived. Pick it up here instead.
                asyncio.create_task(process_message_queue(batch_key))
            else:
                # Drop the per-conversation queue and lock once drained, so they
                # don't accumulate one entry per user+channel for the session.
                bot.message_queues.pop(batch_key, None)
                if bot.processing_locks.get(batch_key) is lock:
                    bot.processing_locks.pop(batch_key, None)


async def load_extensions():
    # Bundled modules aren't on disk when frozen, use an explicit list.
    if getattr(sys, "frozen", False):
        cog_modules = ["app.cogs.general", "app.cogs.management", "app.cogs.error_handler"]
        for module in cog_modules:
            try:
                await bot.load_extension(module)
            except Exception as e:
                print(f"Error loading cog {module}: {e}")
        return
    cogs_dir = os.path.join(getattr(sys, "_MEIPASS", os.path.abspath(".")), "app", "cogs")
    if not os.path.exists(cogs_dir):
        return
    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py"):
            try:
                await bot.load_extension(f"app.cogs.{filename[:-3]}")
            except Exception as e:
                print(f"Error loading cog {filename}: {e}")


# ── Role entry point ─────────────────────────────────────────────────────────
# The supervisor imports this module and calls run_discord_role(); the account
# index is pinned via DISCORD_ACCOUNT_INDEX before import, so ACCOUNT_TOKEN is
# already the right one.


def _bad_token(token: str, index: int):
    masked = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
    bar = "=" * 60
    print(
        "\n" + bar + "\n"
        f"  ✗  INVALID OR EXPIRED TOKEN (token #{index}: {masked})\n"
        "  →  Discord rejected the token.\n"
        "  →  Update DISCORD_TOKEN in config/.env with a fresh token.\n"
        + bar + "\n"
    )


async def _run_token(token: str, index: int):
    try:
        await bot.start(token)
    except discord.errors.LoginFailure:
        # Rejected at REST login (malformed/expired token), never reaches the
        # gateway, so ConnectionClosed 4004 is not raised.
        _bad_token(token, index)
    except discord.errors.ConnectionClosed as e:
        if e.code == 4004:
            _bad_token(token, index)
        else:
            raise


def run_discord_role(account: int | None = None):
    """Run exactly one Discord account in this process (blocking)."""
    if account is not None and account != ACCOUNT_INDEX:
        log_system(
            f"Requested account #{account} but this process is pinned to "
            f"#{ACCOUNT_INDEX}; set DISCORD_ACCOUNT_INDEX before import."
        )
    if len(TOKENS) > 1:
        print(f"Starting Discord account #{ACCOUNT_INDEX} of {len(TOKENS)}...")
    asyncio.run(_run_token(ACCOUNT_TOKEN["token"], ACCOUNT_INDEX))


if __name__ == "__main__":
    # Direct execution is supported for debugging a single account.
    run_discord_role()
