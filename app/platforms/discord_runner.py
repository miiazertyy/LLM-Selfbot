import os
import asyncio
import shutil
import re
import random
import sys
import time

# lets you run this file directly: sys.path[0] is app/platforms/ and the app package isn't importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord

# No third-party property service: discord.py-self normally fetches its client
# properties from a selfbot-community endpoint (cordapi) before falling back to
# Discord's own pages. No real browser ever contacts that domain, so the fetch
# is a network-level tell once per login. Disable it and let the lib use its
# built-in path instead (build number from discord.com/login, Chrome version
# from Google's version API) - both are domains a real browser hits anyway.
try:
    import discord.utils as _dutils

    async def _no_cordapi(*_args, **_kwargs):
        raise RuntimeError("third-party property fetch disabled")

    _dutils.Headers.get_api_properties = staticmethod(_no_cordapi)
except Exception:
    pass
import app.utils.ai as ai_module

# discord keeps its own generate_response_and_reply() (typing, files, voice, TTS); snapchat calls core.engine.generate_ai_response() directly, both share utils/
from app.core.engine import is_refusal, style_block, reaction_rules, refusal_fallbacks  # reuse refusal list instead of duplicating
from app.utils.humanize import strip_meta, add_typo
from app.utils.pictures import is_picture_request, is_video_request

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
    pick_wait,
    typing_speed,
    think_delay,
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
# manual replies look up one message each, and only when unseen; they used the sweep's allowance above, the Chats page drained it within minutes, and Reply then failed with "no recent message found" for anyone uncached
_manual_history_budget = SlidingWindow(limit=120, window_seconds=3600)
# Searching a DM on Discord, from the Chats tab. Asked only on Enter or "more" (what is kept is searched as you type),
# and Discord limits searching harder than reading.
_search_budget = SlidingWindow(limit=24, window_seconds=300)
_SEARCH_HAS = ("link", "embed", "file", "video", "image", "sound", "sticker")

# How old a reply request may be when the runner reads it: a little past how long the panel waits for each (two
# minutes for a Reply, five for Reply to all). Anything older was queued while this account was not running, and
# whoever asked has given up on it.
_REPLY_REQUEST_TTL = {"reply_user": 130, "reply_all": 310}


def history_scan_allowed() -> bool:
    """True when a REST message-history fetch fits in the hourly budget."""
    return _history_scan_budget.allow()


def profile_fetch_allowed() -> bool:
    """True when a fresh user.profile() fetch fits in the hourly budget."""
    return _profile_fetch_budget.allow()


init()
set_theme("discord")


def get_batch_wait_time(server: bool = False):
    """How long to sit on a message before answering it. Servers get their own table when configured: ten minutes on a DM reads as away-from-phone, on a channel the chat has moved on and the reply lands on nothing; unset, servers fall back to the DM table."""
    b = config["bot"]
    wait_times = (b.get("server_batch_wait_times") if server else None)         or b["batch_wait_times"]
    # Picked by weight; a wait with a "to" is any whole second across its range (behavior.pick_wait).
    return pick_wait(wait_times)


config = load_config()

from app.utils.ai import init_ai, generate_response, generate_response_image, extract_memory, detect_memory_deletion, transcribe_voice, summarize_history, summarize_conversation, detect_language, generate_nudge, reset_client_index, fallback_model
from dotenv import load_dotenv
from discord.ext import commands
from app.utils.split_response import split_response
from datetime import datetime, timezone
from collections import deque
from asyncio import Lock

env_path = get_env_path()

load_dotenv(dotenv_path=env_path, override=True)

init_db()
init_ai()
init_memory()

TOKENS = load_tokens()

# which account this process drives (1-based); multi-account runs spawn one child per token with DISCORD_ACCOUNT_INDEX set, a single account is always #1
_PINNED_ACCOUNT = os.getenv("DISCORD_ACCOUNT_INDEX")  # set only in a per-account child
try:
    ACCOUNT_INDEX = min(max(1, int(_PINNED_ACCOUNT or 1)), len(TOKENS))
except ValueError:
    ACCOUNT_INDEX = 1
os.environ["DISCORD_ACCOUNT_INDEX"] = str(ACCOUNT_INDEX)  # picked up by the error relay
ACCOUNT_TOKEN = TOKENS[ACCOUNT_INDEX - 1]

# one IP for gateway and REST alike: build_session() falls back to this proxy unless overridden
set_default_proxy(ACCOUNT_TOKEN.get("proxy"))

PREFIX = config["bot"]["prefix"]
OWNER_ID = config["bot"]["owner_id"]
# How much discord.py is allowed to keep in memory. See create_bot().
_CACHE_CFG = config["bot"].get("cache") or {}

def _trigger_words(value) -> list:
    """The trigger words as the matcher has always used them: lowercased and split on commas, spacing kept. Empty ones are dropped: an empty word (a trailing comma, or no names at all) matched every message, so clearing the names on the Persona page would have made it answer everything said in a group chat."""
    return [w for w in str(value or "").lower().split(",") if w.strip()]


TRIGGER = _trigger_words(config["bot"].get("trigger"))


def _compile_triggers(words):
    """One compiled alternation for all trigger words, a pure speed change. Words are used exactly as config gives them, not stripped: "John, Jon" splits to ["john", " jon"], that leading space is part of what the old per-keyword search matched, and an alternation of the same escaped words is equivalent to any() over the same searches (leading-space words still miss at the very start of a message, which is pre-existing). No words, no pattern: nothing triggers."""
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

# random gap between any two replies, global not per-user; disable for a personal/single-user bot
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
    """Re-read config.yaml into everything cached above. These were read once at import, so panel edits to timings or chances did nothing until a restart; load_config() is mtime-cached, so re-reading is cheap and picks the new file up at once."""
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
    TRIGGER = _trigger_words(b.get("trigger"))
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
    """Align the whole process (gateway identify + every REST call) on one client profile: the desktop app when client_profile=desktop, otherwise the gateway's own live web headers. Runs from setup_hook, i.e. after login/startup with headers fetched and before the gateway connects, so the IDENTIFY super-properties match automatically."""
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
    # one visible line per login: what every REST call and the next IDENTIFY carries; check this if the profile indicator looks wrong
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


SERVER_CHANNELS = (discord.TextChannel, discord.Thread, discord.ForumChannel,
                   discord.StageChannel, discord.VoiceChannel)


def in_server(channel) -> bool:
    """Whether this channel is part of a guild rather than a DM."""
    return isinstance(channel, SERVER_CHANNELS)


def history_key(message) -> str:
    """Where this conversation's history lives. A DM is one conversation with one person, so both identify it; a server channel is one conversation with everyone in it, and keying per author gave the bot a private thread with each person and no idea what anybody else said, so a reply read like it walked in halfway through. Channel alone there. The prefix keeps the two apart since a channel id and a user id are both snowflakes."""
    if in_server(message.channel):
        return f"ch-{message.channel.id}"
    return f"{message.author.id}-{message.channel.id}"


def speaker_label(message) -> str:
    """How a user turn is attributed in a shared channel. Without this the model sees a single run of "user" turns from several different people and answers as if one person said all of it."""
    author = message.author
    return getattr(author, "display_name", None) or getattr(author, "name", "someone")


def _recent_speakers(message, limit: int = 6) -> list:
    """Who has been talking in this channel lately, newest first. Read off the history already kept rather than fetched: turns are stored as "Name: text", so the names are right there and asking Discord would be a round trip for something already in memory."""
    key = history_key(message)
    names, seen = [], set()
    for entry in reversed(bot.message_history.get(key, [])):
        if entry.get("role") != "user":
            continue
        head = str(entry.get("content", "")).split(":", 1)
        if len(head) == 2 and 0 < len(head[0]) <= 40:
            name = head[0].strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        if len(names) >= limit:
            break
    return names


def as_turn(message, content: str) -> str:
    """One user turn, attributed when the channel has more than one person in it."""
    if in_server(message.channel):
        return f"{speaker_label(message)}: {content}"
    return content


async def _answered_since(message) -> bool:
    """Whether this account has said anything in the conversation since `message`.

    Someone's last message stays their last message after it has been answered,
    so every path that finds it and replies (a manual Reply, Reply to all, the
    catch-up after a restart, a nudge) answered the same thing again each time
    it ran: the bot talking to itself, reacting to one old "LMAOOO" four times
    over an evening until the person blocked the account. The channel's cached
    last message answers most of the time; only then is Discord asked, from the
    manual allowance, and when that is spent the answer is "yes", since not
    replying is always the safe mistake here.
    """
    ch = message.channel
    me = getattr(bot, "selfbot_id", None) or bot.user.id
    last_id = getattr(ch, "last_message_id", None)
    if not last_id or last_id <= message.id:
        return False
    cached = ch._state._get_message(last_id)
    if cached is not None and cached.author.id == me:
        return True
    if not _manual_history_budget.allow():
        return True
    try:
        async for m in ch.history(limit=10, after=message):
            if m.author.id == me:
                return True
    except Exception:
        return True
    return False


# people this account has actually talked to, held by strong reference. discord.py's own user cache (ConnectionState._users) is a WeakValueDictionary: a User survives only while something else holds it, so trimming the member/message caches emptied it, get_user() started missing mid-conversation, and every miss fell through to fetch_user(). On a user account GET /users/{id} answers 403 40001 for anyone with no current mutual context, so a miss meant a hard failure (Reply in the panel, and the nudge loop, both). One dict of the people actually being spoken to is a few hundred entries at worst and restores the hit rate without asking Discord anything.
_seen_users: dict = {}
MAX_SEEN_USERS = 400

# what the Chats sweep last found in each DM, keyed by channel id: (last_message_id, entry or None); None means "checked, nobody waiting". See reply_check.
_dm_scan_memo: dict = {}


# summaries in progress, held so the garbage collector cannot drop a running task: asyncio keeps only a weak reference to it
_summary_tasks: set = set()


async def _conversation_lines(uid: int, count: int, include_mine: bool = True):
    """The last `count` messages with someone, as (speaker, text), oldest first. Returns (lines, their_name, source): held history is used when it covers enough, and the DM is read only when short, within the same history budget every other reader spends."""
    user, _why = await resolve_user(uid)
    name = (getattr(user, "global_name", None) or getattr(user, "name", None)
            or str(uid)) if user else str(uid)

    held = []
    for key, hist in bot.message_history.items():
        if key.startswith(f"{uid}-"):
            held = [e for e in hist
                    if e.get("content")
                    and not str(e["content"]).startswith("[Earlier in this conversation:")]
            break

    def _from_held():
        out = [((name if e.get("role") == "user" else "Me"), str(e["content"]))
               for e in held[-count:]]
        return [l for l in out if include_mine or l[0] != "Me"]

    if len(held) >= count or user is None or not history_scan_allowed():
        return _from_held(), name, "recent"

    try:
        dm = user.dm_channel or await user.create_dm()
        msgs = await asyncio.wait_for(_recent_messages(dm, count), timeout=20)
    except Exception:
        return _from_held(), name, "recent"
    me_id = getattr(bot, "selfbot_id", None) or bot.user.id
    lines = []
    for m in reversed(msgs):                     # history() is newest first
        mine = m.author.id == me_id
        if mine and not include_mine:
            continue
        text = m.content or ("[attachment]" if m.attachments else "")
        if text:
            lines.append(("Me" if mine else name, text))
    return (lines or _from_held()), name, ("live" if lines else "recent")


async def _recent_messages(channel, limit: int) -> list:
    """The newest `limit` messages in a channel, newest first."""
    return [m async for m in channel.history(limit=limit)]


def _preview_text(m) -> str:
    """A one-line preview for a message with no text: what is attached instead."""
    if m.content:
        return m.content
    if getattr(m, "stickers", None):
        return _sticker_names(m) or "[sticker]"
    atts = getattr(m, "attachments", None) or []
    if atts:
        ct = (getattr(atts[0], "content_type", "") or "")
        kind = "image" if ct.startswith("image/") else "video" if ct.startswith("video/") \
            else "voice message" if ct.startswith("audio/") else "file"
        return f"[{kind}]" if len(atts) == 1 else f"[{len(atts)} attachments]"
    if getattr(m, "embeds", None):
        return "[link]"
    return ""


def _message_payload(m) -> dict:
    """What the Chats tab shows of a message: all of its text, and what is attached.

    The tab used to get a 60-character plain snippet, so a long message was cut
    off, formatting showed as raw asterisks, and a picture or sticker was just
    "[attachment]". Discord's attachment links are signed and expire after a
    while, which is fine for a list of people waiting now.
    """
    text = (m.content or "")[:2000]
    stickers = []
    for s in getattr(m, "stickers", []) or []:
        fmt = getattr(getattr(s, "format", None), "value", None)
        # Its id and kind too: a Lottie sticker (Discord's own, "Wave" and the
        # rest) has no picture, only an animation, which the panel plays from
        # /api/media/sticker/<id>.json.
        stickers.append({"name": getattr(s, "name", ""),
                         "url": "" if fmt == 3 else str(getattr(s, "url", "") or ""),
                         "id": str(getattr(s, "id", "") or ""),
                         "format": {1: "png", 2: "apng", 3: "lottie", 4: "gif"}.get(fmt, "png")})
    # on_message puts "[sticker: name]" in place of an empty text for the
    # model; the picture says it better here.
    if stickers and text.strip() == _sticker_names(m):
        text = ""
    # The message id, so the panel can tell "this message again" (a sweep
    # overlapping a live event) from "another message", and count only the latter.
    out = {"text": text, "mid": str(m.id)}
    atts = []
    for a in getattr(m, "attachments", []) or []:
        atts.append({"url": a.url, "name": a.filename,
                     "type": getattr(a, "content_type", "") or "",
                     "w": getattr(a, "width", None), "h": getattr(a, "height", None),
                     "size": getattr(a, "size", 0) or 0})
    if atts:
        out["attachments"] = atts[:6]
    if stickers:
        out["stickers"] = stickers[:3]
    embeds = []
    for e in getattr(m, "embeds", []) or []:
        img = (e.image.url if e.image and e.image.url else None) or \
              (e.thumbnail.url if e.thumbnail and e.thumbnail.url else None)
        if img or e.title:
            embeds.append({"title": e.title or "", "url": e.url or "", "image": img or "",
                           "provider": getattr(getattr(e, "provider", None), "name", "") or ""})
    if embeds:
        out["embeds"] = embeds[:3]
    # Reactions on the message, so the Chats tab shows what a conversation
    # actually looks like: an answer that got a laughing face reads very
    # differently from one nobody reacted to, and the bot's own reactions were
    # invisible from the panel entirely.
    reactions = []
    for r in getattr(m, "reactions", []) or []:
        emoji = getattr(r, "emoji", None)
        if emoji is not None:
            reactions.append({**_reaction_emoji(emoji), "count": int(getattr(r, "count", 1) or 1),
                              "mine": bool(getattr(r, "me", False))})
    if reactions:
        out["reactions"] = reactions[:8]
    return out


def _reaction_emoji(emoji) -> dict:
    """A reaction's emoji as the Chats tab draws it: {"name": the character}, or a custom emoji's name and picture.
    The same for a message's reactions and for one arriving live, so the two are recognised as the same reaction."""
    if isinstance(emoji, str):
        return {"name": emoji}
    eid = getattr(emoji, "id", None)
    name = getattr(emoji, "name", "") or ""
    if not eid:
        return {"name": name}
    return {"name": name, "url": f"https://cdn.discordapp.com/emojis/{eid}."
                                 f"{'gif' if getattr(emoji, 'animated', False) else 'webp'}?size=44"}


def _waiting_entry(messages: list, selfbot_id: int):
    """What the waiting list shows for one DM, or None if nobody is waiting. Someone is waiting when their latest message is newer than the account's own latest one; the count is how many of theirs arrived since."""
    if not messages:
        return None
    last_other = next((m for m in messages if m.author.id != selfbot_id), None)
    last_bot = next((m for m in messages if m.author.id == selfbot_id), None)
    if last_other is None:
        return None
    if last_bot and last_bot.created_at > last_other.created_at:
        return None
    pending = sum(1 for m in messages
                  if m.author.id != selfbot_id
                  and (last_bot is None or m.created_at > last_bot.created_at))
    text = _preview_text(last_other)
    return {
        "snippet": (text[:60] + "\u2026") if len(text) > 60 else text,
        "count": max(pending, 1),
        "ts": last_other.created_at.timestamp(),
        **_message_payload(last_other),
    }


def remember_user(user) -> None:
    """Hold a strong reference to someone the bot has dealt with."""
    if user is None or getattr(user, "id", None) is None:
        return
    if len(_seen_users) >= MAX_SEEN_USERS and user.id not in _seen_users:
        # Oldest first: plain dicts keep insertion order.
        for stale in list(_seen_users)[:len(_seen_users) - MAX_SEEN_USERS + 1]:
            _seen_users.pop(stale, None)
    _seen_users[user.id] = user


async def resolve_user(uid: int, channel_id=None):
    """Find a user without asking Discord unless there is no other way. Returns (user, reason); a reason with no user means the lookup failed for good rather than transiently, so stop retrying."""
    cached = _seen_users.get(uid) or bot.get_user(uid)
    if cached is not None:
        remember_user(cached)
        return cached, ""
    # A DM channel carries its recipient, and reading one costs nothing.
    for ch in ([bot.get_channel(int(channel_id))] if channel_id else []) + list(bot.private_channels):
        if ch is None:
            continue
        for recipient in ([getattr(ch, "recipient", None)] + list(getattr(ch, "recipients", None) or [])):
            if recipient is not None and recipient.id == uid:
                remember_user(recipient)
                return recipient, ""
    try:
        fetched = await bot.fetch_user(uid)
        remember_user(fetched)
        return fetched, ""
    except discord.NotFound:
        return None, f"Discord does not know user {uid}"
    except discord.Forbidden:
        # 40001 on a user account means no mutual context any more: not friends, no shared server, DMs closed, and it doesn't clear by itself
        return None, "this account is not allowed to look that user up any more"


def create_bot() -> commands.Bot:
    """Instantiate a fully configured bot for this process's account."""
    # discord.py caches way more than this bot uses (only _save_pending_messages reads the message cache): member_cache_flags defaults to keeping every member of every guild, chunk_guilds_at_startup fetches them all over the gateway before the first reply, and max_messages holds 1000 Message objects; chunk_guilds is stated explicitly so an explicit True with no member cache can't raise, and message.author still works because discord.py builds it from the payload whether cached or not
    kwargs = {
        "command_prefix": PREFIX,
        "help_command": None,
        "member_cache_flags": discord.MemberCacheFlags.none(),
        "chunk_guilds_at_startup": False,
        "max_messages": _CACHE_CFG.get("max_messages", 200),
    }
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
    b.shown_status = None  # the presence this runner last set (online, idle, dnd, invisible), for the panel
    # Global send lock: one message sent at a time across ALL users.
    b.global_send_lock = Lock()
    b.last_global_send = 0.0  # timestamp of last sent message across all users
    b._lang_cache = {}  # uid -> {"tag": str, "count": int}
    # what the bot is doing about each person's latest message, for the Chats tab: waiting (with when), writing, cooldown, sending, skipped (with why) or failed; only "waiting" used to be visible, so anything being written or held for the cooldown read as "no reply scheduled"
    b.reply_state = {}
    # People whose in-flight or scheduled reply the panel cancelled. Checked
    # right before a reply is written/sent, so a "cancel" from Chats actually
    # stops it rather than only hiding the countdown.
    b.cancelled_replies = set()
    # the last message each person sent in a DM, as it arrived or as the Chats sweep found it: what a manual Reply answers, without a history fetch
    b.waiting_msgs = {}
    # the latest message in each server channel that asked for a reply (a mention, a reply to the bot), by channel id: a server conversation in the Chats tab
    b.server_waiting = {}
    return b


bot = create_bot()


# Chats-tab events, pushed to the panel as they happen.
#
# The tab used to learn anything only by asking: an IPC round trip that swept
# the DM channels, every 15 seconds while it was open. A reply that was written
# and sent in between never showed at all, and a new message took up to a
# quarter of a minute to appear. The runner already knows the moment each of
# these happens, so it says so on its own stdout, which the supervisor is
# reading anyway, and the panel hands it to the page over the WebSocket the
# logs already use. The marker (an ASCII record separator) keeps these lines
# out of the log; they are only written when the panel is the one listening.
_CHAT_EVENT_MARK = "\x1eCHAT "
from app.core.launcher import under_panel as _under_panel
_EMIT_EVENTS = _under_panel()


def emit_chat_event(evt: dict):
    if not _EMIT_EVENTS:
        return
    try:
        import json as _json
        sys.stdout.write(_CHAT_EVENT_MARK + _json.dumps(evt, ensure_ascii=True, default=str) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


# ── The chat log (app/utils/chatlog.py) ───────────────────────────────────────
# Every DM message this account sees is kept: the Chats tab reads a conversation
# from it rather than from Discord each time, a deleted message is kept and
# marked, and the first reply after a restart starts from what was said before.
from app.utils import chatlog as _chatlog

_KEEP_PICTURE_BYTES = 8 * 1024 * 1024


def _dm_partner(message):
    """Whose DM a message is in: the other person, whoever wrote it. None outside a DM."""
    if not isinstance(message.channel, discord.DMChannel):
        return None
    rcp = getattr(message.channel, "recipient", None)
    if rcp is not None:
        return rcp.id
    return None if message.author.id == getattr(bot, "selfbot_id", None) else message.author.id


def _log_dm(message) -> None:
    """Keep a DM message in the chat log, and its pictures on disk."""
    try:
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return
        other = _dm_partner(message)
        if other is None:
            return
        mine = message.author.id == getattr(bot, "selfbot_id", None)
        _chatlog.put(ACCOUNT_INDEX, other, message.id, mine, message.created_at.timestamp(), _message_payload(message))
        _keep_pictures(message)
    except Exception:
        pass


def _keep_pictures(message) -> None:
    """A DM's pictures, saved: Discord's links to them expire, and go with the message when it is deleted."""
    for i, att in enumerate(getattr(message, "attachments", None) or []):
        ctype = (getattr(att, "content_type", "") or "").lower()
        if not ctype.startswith("image/") or (getattr(att, "size", 0) or 0) > _KEEP_PICTURE_BYTES:
            continue
        name = _chatlog.picture_name(message.id, i, ctype)
        if not name:
            continue
        path = _chatlog.CACHE_DIR / name
        if path.exists():
            continue

        async def fetch(att=att, path=path):
            try:
                data = await att.read()
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(path)
                _chatlog.prune_media()
            except Exception:
                pass
        try:
            asyncio.get_running_loop().create_task(fetch())
        except RuntimeError:
            pass


def _turn_text(m) -> str:
    """A message as a line of history: its words, or what it was when it had none."""
    text = (m.content or "").strip()
    if text:
        return text
    if getattr(m, "attachments", None):
        return "[picture]" if any((a.content_type or "").startswith("image/") for a in m.attachments) else "[attachment]"
    if getattr(m, "stickers", None):
        return f"[sticker: {m.stickers[0].name}]"
    return ""


async def seed_history(key: str, first_message) -> None:
    """What was said before `first_message`, for a conversation this session has no history of.

    History lives in memory, so after a restart the first reply to someone only
    ever saw their latest message and answered it cold: "yeah same" to a
    question that was two messages back, or a greeting in the middle of a
    conversation. A DM's history comes from the chat log, which costs nothing;
    a server channel's, or a DM the log has never seen, from one history read,
    within the hourly allowance. Once per conversation per session.
    """
    if bot.message_history.get(key):
        return
    seeded = getattr(bot, "_seeded_history", None)
    if seeded is None:
        seeded = bot._seeded_history = set()
    if key in seeded:
        return
    seeded.add(key)
    turns: list[dict] = []
    ch = first_message.channel
    try:
        other = _dm_partner(first_message)
        if other is not None:
            turns = _chatlog.seed_turns(ACCOUNT_INDEX, other, first_message.created_at.timestamp(), limit=MAX_HISTORY * 2)
        if not turns and history_scan_allowed():
            me = getattr(bot, "selfbot_id", None)
            msgs = [m async for m in ch.history(limit=MAX_HISTORY * 2, before=first_message)]
            msgs.reverse()
            if other is not None:
                _chatlog.put_many(ACCOUNT_INDEX, other, [(m.id, m.author.id == me, m.created_at.timestamp(), _message_payload(m))
                                                         for m in msgs if m.type in (discord.MessageType.default, discord.MessageType.reply)])
            for m in msgs:
                if m.type not in (discord.MessageType.default, discord.MessageType.reply):
                    continue
                text = _turn_text(m)
                if not text:
                    continue
                role = "assistant" if m.author.id == me else "user"
                line = text if role == "assistant" else as_turn(m, text)
                if turns and turns[-1]["role"] == role:
                    turns[-1]["content"] += "\n" + line
                else:
                    turns.append({"role": role, "content": line})
    except Exception:
        turns = []
    if turns:
        turns = turns[-MAX_HISTORY:]
        bot.message_history[key] = turns + list(bot.message_history.get(key, []))
        try:
            log_system(f"Picked up {len(turns)} earlier turns of the conversation before replying")
        except Exception:
            pass


# A setting was just used: a command run with the command prefix, a message
# carrying the priority prefix, a trigger word that woke it. The panel lights
# that setting's row in Settings, the way a model's row lights when it answers.
_USE_MARK = "\x1eUSE "


def emit_use(key: str, detail: str = ""):
    if not _EMIT_EVENTS:
        return
    try:
        import json as _json
        sys.stdout.write(_USE_MARK + _json.dumps({"key": key, "detail": detail[:60], "at": time.time()},
                                                  ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


async def _announce_command(ctx):
    """A command ran, so the command prefix was used."""
    emit_use("bot.prefix", f"{ctx.prefix or ''}{ctx.invoked_with or ''}")


bot.add_listener(_announce_command, "on_command")


def set_reply_state(uid, state, eta=None, reason=""):
    """Record where a person's reply is. See bot.reply_state. A server conversation waiting on them shows it too:
    its row is the channel's, but the reply in progress is still theirs."""
    try:
        st = {"state": state, "since": time.time(), "eta": eta, "reason": reason}
        bot.reply_state[int(uid)] = st
        emit_chat_event({"t": "state", "uid": str(uid), "state": st})
        for _cid, _sm in list(getattr(bot, "server_waiting", {}).items()):
            if _sm.author.id == int(uid):
                emit_chat_event({"t": "state", "uid": f"ch{_cid}", "state": st})
    except Exception:
        pass


def server_row(m) -> dict:
    """A server message as a Chats row: the channel is the conversation, the person who wrote is who it is with."""
    a = m.author
    guild = getattr(getattr(m, "guild", None), "name", "") or ""
    where = f"#{getattr(m.channel, 'name', 'channel')}" + (f" \u00b7 {guild}" if guild else "")
    txt = _preview_text(m)
    return {
        "id": f"ch{m.channel.id}", "kind": "server", "channel_id": str(m.channel.id), "author_id": str(a.id),
        "name": getattr(a, "global_name", None) or getattr(a, "display_name", None) or a.name,
        "username": a.name, "where": where,
        "avatar": str(a.display_avatar.url) if getattr(a, "display_avatar", None) else "",
        "snippet": (txt[:60] + "\u2026") if len(txt) > 60 else txt,
        "ts": m.created_at.timestamp(), "ignored": a.id in bot.ignore_users,
        **_message_payload(m),
    }


def clear_reply_state(uid):
    """They have been answered: off the waiting list."""
    try:
        bot.reply_state.pop(int(uid), None)
        bot.waiting_msgs.pop(int(uid), None)
        emit_chat_event({"t": "done", "uid": str(uid)})
    except Exception:
        pass


# A reply is lined up for someone in these states; "sending" is the bot's own reply going out.
_PENDING_STATES = ("waiting", "writing", "cooldown", "queued")


def _people_waiting() -> int:
    """How many conversations have a reply lined up right now. The gap between sends comes down when this is high, so a backlog is worked through instead of each person paying the full pause."""
    try:
        return sum(1 for st in bot.reply_state.values()
                   if (st or {}).get("state") in _PENDING_STATES)
    except Exception:
        return 0


# Replies asked for by hand (Reply now), being written, by whom they are for ("ch<id>" for a server channel): the
# Cancel button stops one mid-way, which the cancelled_replies check cannot, since a reply asked for by hand is
# deliberately not held back by it.
_manual_replies: dict = {}


def _stop_manual_reply(key) -> bool:
    task = _manual_replies.get(str(key))
    if task is None or task.done():
        return False
    task.cancel()
    return True


def cancel_pending_reply(uid, channel_id=None) -> bool:
    """Drop the reply lined up for someone: the batch timer, the messages queued for it, and one being written,
    which is checked before it is sent. True when there was one. Only when there was: an entry left in
    cancelled_replies with nothing pending would swallow the next real reply. With a channel, only the reply
    lined up there."""
    uid = int(uid)
    prefix = f"{uid}-{channel_id}" if channel_id is not None else f"{uid}-"
    batches = [k for k in list(bot.user_message_batches) if k.startswith(prefix)]
    pending = bool(batches) or (bot.reply_state.get(uid) or {}).get("state") in _PENDING_STATES
    if not pending:
        return False
    bot.cancelled_replies.add(uid)
    for _bk in batches:
        bot.user_message_batches.pop(_bk, None)
    for _bk in [k for k in list(bot.message_queues) if k.startswith(prefix)]:
        bot.message_queues.pop(_bk, None)
    return True


def emit_chat_meta():
    """The account-wide half of the tab: paused, and when the cooldown ends."""
    try:
        until = 0.0
        if GLOBAL_COOLDOWN_ENABLED:
            until = getattr(bot, "last_global_send", 0.0) + GLOBAL_COOLDOWN_MIN
        emit_chat_event({"t": "meta", "paused": bool(getattr(bot, "paused", False)),
                         "cooldown_until": until if until > time.time() else 0})
    except Exception:
        pass

# X-Context-Properties for a request made from the Friends list, as the client sends it.
_FRIENDS_CONTEXT = "eyJsb2NhdGlvbiI6IkZyaWVuZHMifQ=="   # {"location":"Friends"}


async def accept_friend_request(session, uid: int):
    """Accept a pending friend request, the way Discord's own client does.

    Discord now makes you confirm accepting a request from someone you share no
    server with: the client shows a "confirm" step and sends
    confirm_stranger_request. Without it the answer is 400, code 80013, "You
    must confirm the friend request to add this user", which is why every
    accept, automatic or by hand, was failing. The plain accept is tried first
    so an ordinary request looks exactly as it always has.
    """
    url = f"https://discord.com/api/v9/users/@me/relationships/{uid}"
    r = await session.put(url, json={"type": 1})
    if r.status_code == 400 and _discord_code(r) == 80013:
        r = await session.put(url, json={"confirm_stranger_request": True},
                              headers={"X-Context-Properties": _FRIENDS_CONTEXT})
    return r


def _discord_code(r):
    try:
        return (r.json() or {}).get("code")
    except Exception:
        return None


def discord_reason(r) -> str:
    """Why Discord refused, in its words when it gave some."""
    try:
        data = r.json() or {}
    except Exception:
        data = {}
    if data.get("captcha_key") or data.get("captcha_sitekey"):
        return "Discord wants a captcha for this, which the app cannot do. Accept it in Discord itself."
    if data.get("message"):
        return f"Discord said: {data['message']} ({r.status_code})"
    return f"Discord answered {r.status_code}"


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


def late_openers_for(lang: str) -> list:
    """The written openers for one language, if any exist. `openers` is keyed by language code, so adding Spanish means adding an "es" list rather than editing code. An empty result means the caller should ask the model to write one instead. The old openers_en / openers_fr keys are still read, so a config written before this keeps working untouched."""
    cfg = (_LATE_CFG or config["bot"].get("late_reply") or {})
    code = (lang or "").lower()
    by_lang = cfg.get("openers")
    if isinstance(by_lang, dict):
        got = by_lang.get(code)
        if isinstance(got, list) and got:
            return got
    legacy = cfg.get(f"openers_{code}")
    return legacy if isinstance(legacy, list) and legacy else []


def get_late_opener(prompt: str, lang: str = "en") -> str:
    """One written opener for this language, or "" when there are none."""
    openers = late_openers_for(lang)
    return random.choice(openers) if openers else ""


async def _simulate_typing(channel, text: str, fast: bool = False):
    """Type `text` at human speed (2.5-6 cps normal, 4-8 fast) in short bursts with occasional think-pauses. The typing indicator stays up the whole time; Discord only clears it ~10s after the last refresh."""
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
        # these two grow by one entry per unique user ever seen and were the only dicts here with no bound at all: _profile_seen holds the last time a profile was written, on a one-hour throttle, so anything older would be rewritten on sight anyway; _friend_due holds scheduled accept times, so anything in the past has already fired
        stale_seen = [uid for uid, at in _profile_seen.items() if now - at > 3600]
        for uid in stale_seen:
            _profile_seen.pop(uid, None)
        stale_friend = [uid for uid, at in _friend_due.items() if at < now]
        for uid in stale_friend:
            _friend_due.pop(uid, None)
        # remember_user() already caps this; trimming it here as well keeps a long-running process from holding 400 User objects it has not needed in hours
        _dropped_users = 0
        if len(_seen_users) > MAX_SEEN_USERS // 2:
            for uid in list(_seen_users):
                if uid not in bot._memory_cache and uid not in bot.active_conversations:
                    _seen_users.pop(uid, None)
                    _dropped_users += 1
                if len(_seen_users) <= MAX_SEEN_USERS // 2:
                    break
        log_system(
            f"Cleanup: pruned {len(stale_counts)} count(s), {len(expired_cd)} cooldown(s), "
            f"{len(stale_conv)} conversation(s), {len(stale_hist)} history entr(ies), "
            f"{len(stale_seen)} profile stamp(s), {len(stale_friend)} friend timer(s), "
            f"{_dropped_users} user ref(s)"
        )


def _pick_status(status_cfg: dict, status_map: dict, defaults: dict):
    """Choose the next presence from the configured statuses and weights. Everything here is defensive because this runs in a background task: an exception escaping it kills the presence loop for the rest of the session, silently, and a hand-written config can easily give fewer weights than statuses, a weight that is not a number, or weights that are all zero, none of which should stop the account changing status ever again."""
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
        # a short weights list leaves the rest at their defaults rather than dropping those statuses entirely, which would silently pin the account to whichever ones happened to be listed first
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
        # every weight was zero or unusable; online is the safe answer, and it's what a real account looks like most of the time anyway
        return status_map["online"]
    return random.choices([p[0] for p in pool], weights=[p[1] for p in pool], k=1)[0]


async def random_status_loop():
    """Realistic presence, not random flipping. Humans stay online for long stretches, occasionally idle out, rarely set dnd on purpose, and are invisible while asleep. Randomly switching status every 30-180 minutes is an automation signature, so this keeps one status until a change feels natural and never flips when the persona's local time falls inside the night window (still replies: invisible is not offline)."""
    await bot.wait_until_ready()
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    _DEFAULT_WEIGHTS = {"online": 0.85, "idle": 0.12, "dnd": 0.03, "invisible": 0.0}
    # wait 10-30 min before the FIRST change, flipping presence right after login is a classic automation tell
    await asyncio.sleep(random.uniform(600, 1800))
    _last_status = None
    while not bot.is_closed():
        status_cfg = config["bot"].get("status") or {}
        night_cfg = config["bot"].get("night_invisible") or {}
        night, secs_until_day = night_window_state(night_cfg)

        if night:
            # which status the night window uses is a setting; it was hardcoded to invisible, which is the sensible default but not everyone's: some accounts read as more natural asleep on dnd or idle
            target = status_map.get(
                str(night_cfg.get("status", "invisible")).strip().lower(),
                discord.Status.invisible,
            )
        else:
            target = _pick_status(status_cfg, status_map, _DEFAULT_WEIGHTS)

        if target != _last_status:
            try:
                await bot.change_presence(status=target)
                _last_status = target
                bot.shown_status = target
                log_system(f"Presence: {target}")
            except Exception as e:
                log_error("Presence", str(e))

        if night:
            # sleep through the night; wake 0-20 min after sunrise so the account doesn't flip online at exactly 8:00:00
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
    # wait a human-like 3-8 min before firing pending replies, replying seconds after startup looks like a bot
    await asyncio.sleep(random.uniform(180, 480))

    for key, data in pending.items():
        try:
            user_id = int(data["user_id"])
            channel_id = int(data["channel_id"])
            history = data.get("history", [])
            content = data["content"]

            # someone who cannot be messaged is the whole reason this loop kept repeating itself: the send fails with a 403, the conversation is never answered, it's still "unanswered" when the next shutdown writes this file, and the same dead reply retried on every restart. blocked ids are loaded before this task starts.
            if user_id in _blocked_users:
                log_system(f"Skipping pending reply to {user_id}: cannot be messaged")
                continue

            if history and history[-1].get("role") == "assistant":
                continue

            # cache, then the DM channel's own recipient, and only then ask Discord - see resolve_user()
            _chan_hint = key.split("-")[-1] if "-" in key else None
            user, _why = await resolve_user(user_id, _chan_hint)
            if user is None:
                log_error("Pending Reply", f"Could not reach user {user_id}: {_why}")
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

            if await _answered_since(last_msg):
                log_system(f"Not replying to {user.name}'s pending message: it was answered since")
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

            # distribute accepts in random bursts across a 6-hour window, mimicking a human who opens Discord a few times and clears requests
            num_bursts = random.randint(2, 3)
            burst_offsets = sorted(random.uniform(0, 21600) for _ in range(num_bursts))  # 6h window
            for i, rel in enumerate(pending):
                user_id = int(rel["id"])
                username = rel.get("user", {}).get("username", str(user_id))
                # assign this request to a burst, with intra-burst jitter (10-90s apart), plus +/-25% wobble on the total so two accepts never land on a metronome
                burst_base = burst_offsets[i % num_bursts]
                intra_jitter = random.uniform(10, 90) * (i // num_bursts)
                actual_delay = (delay + burst_base + intra_jitter) * random.uniform(0.75, 1.25)
                log_system(f"Pending friend request from {username}, accepting in {int(actual_delay)}s")
                _friend_due[user_id] = time.time() + actual_delay

                async def _accept(uid=user_id, uname=username, d=actual_delay):
                    await asyncio.sleep(d)
                    try:
                        async with build_session(bot._connection.http.token) as s:
                            r = await accept_friend_request(s, uid)
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
        # The panel draws this on a clock, so a window can run past midnight
        # (22 to 2); start == end is no window at all.
        if send_hour_start <= send_hour_end:
            in_window = send_hour_start <= current_hour < send_hour_end
        else:
            in_window = current_hour >= send_hour_start or current_hour < send_hour_end
        if in_window:
            threshold_seconds = threshold_days * 86400
            pending = get_pending_nudges(threshold_seconds)

            for entry in pending:
                try:
                    user_id = entry["user_id"]
                    channel_id = entry["channel_id"]
                    original_content = entry["content"]
                    days_elapsed = (time.time() - entry["received_at"]) / 86400

                    user, why = await resolve_user(user_id, channel_id)
                    if not user:
                        # logged once and taken off the list; before this the lookup raised, the whole entry fell to the generic handler, and the same 403 was printed on every sweep and after every restart, for ever
                        log_system(f"Nudge skipped for {user_id}: "
                                   f"{why or 'user not found'}")
                        mark_nudge_sent(user_id, channel_id)
                        continue

                    # a row can outlive its answer (a reply that never cleared it): if the bot spoke last, there is nothing to nudge, and a nudge then answers their old message a second time
                    try:
                        _ndm = user.dm_channel or await user.create_dm()
                        _nlast = None
                        if _ndm.last_message_id:
                            _nlast = _ndm._state._get_message(_ndm.last_message_id)
                        if _nlast is None and _manual_history_budget.allow():
                            async for _nm in _ndm.history(limit=1):
                                _nlast = _nm
                        if _nlast is not None and _nlast.author.id == (getattr(bot, "selfbot_id", None) or bot.user.id):
                            mark_responded(user_id, channel_id)
                            log_system(f"Nudge skipped for {user.name}: the conversation was already answered")
                            continue
                    except Exception:
                        pass

                    # Build minimal instructions for nudge tone
                    uid = user_id
                    if uid not in bot._memory_cache:
                        bot._memory_cache[uid] = get_memory(uid)
                    memory_block = format_memory_for_prompt(bot._memory_cache[uid])
                    mood_block = f"\n\n[Right now: {get_mood_prompt()}]" if _MOOD_CFG.get("enabled", True) else ""
                    nudge_instructions = load_instructions() + mood_block + memory_block

                    nudge_text = await generate_nudge(original_content, days_elapsed, nudge_instructions)
                    if not nudge_text or is_refusal(nudge_text):
                        continue
                    nudge_text = _strip_pic_tags(nudge_text)

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
                        # the bot has spoken now, so they are no longer waiting on it
                        mark_responded(user_id, channel_id)
                        log_system(f"Nudge sent to {user.name} ({days_elapsed:.1f}d elapsed)")

                        # add to history so the conversation continues naturally; a nudge is always a DM, so this is the DM key by construction - see history_key()
                        key = f"{user_id}-{channel_id}"
                        bot.message_history.setdefault(key, [])
                        bot.message_history[key].append({"role": "assistant", "content": nudge_text})

                    except discord.Forbidden:
                        # blocked, DMs closed, or no longer friends; a nudge is the one message that can never get through then, so stop trying rather than failing again in six hours
                        log_system(f"Nudge skipped for {user.name}: "
                                   "they have blocked the account or closed their DMs")
                        mark_nudge_sent(user_id, channel_id)
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
    """Rewrite the IPC command file, preserving entries added while we worked. Errors queued by _notify_telegram_error (or a second bot instance) land in this file mid-pass; a blind overwrite would silently drop them. A rewrite that fails is written to the log rather than raised: it used to end the command loop, after which neither the panel nor Telegram could reach this account."""
    kept_back = {e.get("id") for e in remaining}
    for e in handled:
        if e.get("id") and e.get("id") not in kept_back:
            _RAN_COMMANDS[e["id"]] = None
    while len(_RAN_COMMANDS) > 500:
        _RAN_COMMANDS.pop(next(iter(_RAN_COMMANDS)))
    try:
        _rewrite_commands(cmd_file, remaining, handled)
    except Exception as _e:
        log_error("TG IPC", f"could not rewrite the command file: {_e}")


# Command ids already run, newest last, so a pass that could not rewrite the
# command file never runs one of them a second time on the next.
_RAN_COMMANDS: dict = {}


def _rewrite_commands(cmd_file, remaining, handled):
    import json as _json
    handled_ids = {e.get("id") for e in handled} | set(_RAN_COMMANDS)
    keep = list(remaining)
    keep_ids = {e.get("id") for e in keep}
    try:
        current = _json.loads(cmd_file.read_text(encoding="utf-8"))
    except Exception:
        current = []
    if isinstance(current, list):
        for entry in current:
            eid = entry.get("id")
            if eid not in handled_ids and eid not in keep_ids:
                keep.append(entry)
                keep_ids.add(eid)
    from app.utils.atomic import write_json_atomic
    write_json_atomic(cmd_file, keep)


async def _tg_ipc_loop():
    """Poll for commands from the Telegram controller and execute them in-process. Each bot instance uses its own per-account IPC files (config/tg_commands_1.json / tg_results_1.json for account 1, etc.), the index matching the position of DISCORD_TOKEN_N in .env."""
    import json as _json
    from pathlib import Path as _Path

    await bot.wait_until_ready()

    _CMD_FILE    = _Path(resource_path(f"config/tg_commands_{ACCOUNT_INDEX}.json"))
    _RESULT_FILE = _Path(resource_path(f"config/tg_results_{ACCOUNT_INDEX}.json"))
    # half a second, not two: every panel request waited up to one full interval before the loop even read it, which is most of why the Chats and Accounts pages felt slow to answer. reading a small file twice a second costs nothing.
    _POLL_INTERVAL = 0.5

    # a result is only removed when someone reads it; anything whose caller timed out or went away stays until it is pruned, so only the newest few are kept
    _MAX_RESULTS = 40

    def _write_result(cmd_id: str, data: dict):
        # through the shared helper, in UTF-8 like every other side of the file. this used to read and write with the Windows default, cp1252, while the panel writes UTF-8: every emoji or accented letter in an answer still waiting came back as mojibake, was written out like that, and doubled again on the next pass, so a 60-character chat preview grew to tens of megabytes and the file to 900 MB. the helper also refuses to parse a file that size, so a damaged one is started over instead of carried forward.
        from app.core.ipc import append_result
        append_result(_RESULT_FILE, cmd_id, data, _MAX_RESULTS)

    async def _find_message_to_answer(u):
        """The message a manual Reply answers: the last one this person sent. In order of cost: the one the bot already has (it arrived while running, or the Chats sweep found it), the DM's last message from the client's own cache, and only then a history fetch on its own allowance, not the sweep's."""
        uid = u.id
        m = bot.waiting_msgs.get(uid)
        if m is not None:
            return m
        dm = u.dm_channel
        if dm is None:
            try:
                dm = await u.create_dm()
            except Exception:
                dm = None
        if dm is not None and dm.last_message_id:
            cached = dm._state._get_message(dm.last_message_id)
            if cached is not None and cached.author.id == uid:
                return cached
        channels = []
        for hk in bot.message_history:
            if hk.startswith(f"{uid}-"):
                ch = bot.get_channel(int(hk.split("-")[1]))
                if ch is not None:
                    channels.append(ch)
        if dm is not None:
            channels.append(dm)
        for ch in channels:
            if not _manual_history_budget.allow():
                break
            try:
                async for msg in ch.history(limit=10):
                    if msg.author.id == uid:
                        return msg
            except Exception:
                continue
        return None

    # ── Reacting, from the Chats tab ───────────────────────────────────────────
    async def _react_on(channel, cmd_id, payload):
        """A reaction on a message in that channel, added or taken back ("remove"). The emoji is the character, or a
        custom one as Discord writes it ("<:name:id>"). The chat log and the tab hear of it from Discord's own event
        (on_raw_reaction_add), the same way as a reaction from anyone else."""
        emoji = str(payload.get("emoji") or "").strip()
        if not emoji or len(emoji) > 100:
            _write_result(cmd_id, {"ok": False, "reason": "which emoji?"})
            return
        try:
            msg = await channel.fetch_message(int(payload.get("mid") or 0))
        except (discord.NotFound, ValueError):
            _write_result(cmd_id, {"ok": False, "reason": "that message is not there any more"})
            return
        what = discord.PartialEmoji.from_str(emoji) if emoji.startswith("<") else emoji
        try:
            if payload.get("remove"):
                await msg.remove_reaction(what, bot.user)
            else:
                await msg.add_reaction(what)
        except discord.Forbidden:
            _write_result(cmd_id, {"ok": False, "reason": "Discord would not let this account react there"})
            return
        except discord.HTTPException as e:
            _write_result(cmd_id, {"ok": False, "reason": "Discord does not know that emoji"
                                   if getattr(e, "code", 0) == 10014 else str(e)})
            return
        _write_result(cmd_id, {"ok": True})

    async def _react_job(cmd_id, payload):
        """A reaction on a DM message, from the Chats tab. Beside the command loop, like the other Discord calls."""
        try:
            u, why = await resolve_user(int(payload["user_id"]))
            if not u:
                _write_result(cmd_id, {"ok": False, "reason": why or "user not found"})
                return
            await _react_on(u.dm_channel or await u.create_dm(), cmd_id, payload)
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

    # ── A server conversation, row id "ch<channel id>" ─────────────────────────
    def _server_id(payload):
        raw = str((payload or {}).get("user_id") or "")
        return int(raw[2:]) if raw.startswith("ch") and raw[2:].isdigit() else None

    async def _server_job(cmd, cmd_id, cid, payload):
        """What a DM row can do, for a server channel: its latest message asking for a reply, its history, a Reply,
        a message typed in the panel, and cancelling the reply lined up."""
        me = getattr(bot, "selfbot_id", None) or bot.user.id
        waiting = bot.server_waiting.get(cid)
        ch = bot.get_channel(cid) or (waiting.channel if waiting is not None else None)
        if ch is None:
            _write_result(cmd_id, {"ok": False, "success": False, "dropped": True,
                                   "reason": "that channel is not available to this account any more"})
            bot.server_waiting.pop(cid, None)
            return
        if cmd == "chat_message":
            if waiting is None:
                _write_result(cmd_id, {"ok": False, "reason": "nothing is waiting there any more"})
                return
            body = _message_payload(waiting)
            emit_chat_event({"t": "payload", "uid": f"ch{cid}", **body})
            _write_result(cmd_id, {"ok": True, **body})
        elif cmd == "chat_history":
            if not _manual_history_budget.allow():
                _write_result(cmd_id, {"ok": False, "reason": "Discord limits how often history can be read; try again in a minute"})
                return
            limit = max(5, min(40, int(payload.get("limit") or 20)))
            out = []
            async for m in ch.history(limit=limit):
                if m.type not in (discord.MessageType.default, discord.MessageType.reply):
                    continue
                a = m.author
                out.append({"mine": a.id == me, "ts": m.created_at.timestamp(),
                            "author": {"id": str(a.id), "name": getattr(a, "global_name", None) or getattr(a, "display_name", None) or a.name,
                                       "avatar": str(a.display_avatar.url) if getattr(a, "display_avatar", None) else ""},
                            **_message_payload(m)})
            out.reverse()
            _write_result(cmd_id, {"ok": True, "messages": out})
        elif cmd == "cancel_reply":
            stopped = _stop_manual_reply(f"ch{cid}")
            if waiting is not None and (cancel_pending_reply(waiting.author.id, cid) or stopped):
                set_reply_state(waiting.author.id, "skipped", reason="you cancelled the reply")
            _write_result(cmd_id, {"ok": True, "stopped": stopped})
        elif cmd == "reply_user":
            if waiting is None:
                _write_result(cmd_id, {"success": False, "dropped": True, "reason": "nothing is waiting there any more"})
                return
            if await _answered_since(waiting):
                bot.server_waiting.pop(cid, None)
                emit_chat_event({"t": "done", "uid": f"ch{cid}"})
                _write_result(cmd_id, {"success": False, "dropped": True,
                                       "reason": "already answered, the bot has spoken there since"})
                return
            hk = history_key(waiting)
            await seed_history(hk, waiting)
            history = bot.message_history.get(hk, [])
            combined = as_turn(waiting, waiting.content or "[attachment]")
            if not history or history[-1].get("content") != combined:
                history.append({"role": "user", "content": combined})
                bot.message_history[hk] = history
            set_reply_state(waiting.author.id, "writing")
            resp = await generate_response_and_reply(waiting, combined, history, bypass_cooldown=True, bypass_typing=True)
            if resp:
                bot.message_history[hk].append({"role": "assistant", "content": resp})
                bot.server_waiting.pop(cid, None)
                emit_chat_event({"t": "done", "uid": f"ch{cid}"})
                _write_result(cmd_id, {"success": True})
            elif (_why_not := ai_module.unavailable_now()):
                # No model can reply right now: the reason, said once already, not a line for each channel.
                set_reply_state(waiting.author.id, "failed", reason=_why_not)
                _write_result(cmd_id, {"success": False, "retryable": True, "reason": _why_not})
            else:
                log_error("Reply", f"No reply sent in #{getattr(ch, 'name', cid)}: the model returned nothing "
                                   f"or the send was refused. It stays on the waiting list.")
                set_reply_state(waiting.author.id, "failed", reason="no reply was generated, see the log")
                _write_result(cmd_id, {"success": False, "retryable": True, "reason": "no reply was generated"})
        elif cmd == "react":
            await _react_on(ch, cmd_id, payload)
        elif cmd == "send_message":
            text = str(payload.get("text") or "").strip()
            if not text or len(text) > 2000:
                _write_result(cmd_id, {"ok": False, "reason": "nothing to send" if not text else "Discord takes up to 2000 characters in one message"})
                return
            dropped = waiting is not None and cancel_pending_reply(waiting.author.id, cid)
            async with bot.global_send_lock:
                # an answer to what was waiting, so it reads as one in the channel, without pinging them
                sent = await (waiting.reply(text, mention_author=False) if waiting is not None else ch.send(text))
            bot.last_global_send = time.time()
            bot.message_history.setdefault(f"ch-{cid}", []).append({"role": "assistant", "content": text})
            bot.server_waiting.pop(cid, None)
            emit_chat_event({"t": "sent", "uid": f"ch{cid}", "ts": sent.created_at.timestamp(), **_message_payload(sent)})
            emit_chat_event({"t": "done", "uid": f"ch{cid}"})
            _write_result(cmd_id, {"ok": True, "mid": str(sent.id), "ts": sent.created_at.timestamp(), "dropped_reply": dropped})

    async def _server_job_safe(cmd, cmd_id, cid, payload):
        if cmd == "reply_user":
            _manual_replies[f"ch{cid}"] = asyncio.current_task()
        try:
            await _server_job(cmd, cmd_id, cid, payload)
        except asyncio.CancelledError:
            # Cancelled from the panel while it was being written: whatever went out already stays.
            _write_result(cmd_id, {"ok": False, "success": False, "cancelled": True, "reason": "you cancelled the reply"})
        except discord.Forbidden:
            _write_result(cmd_id, {"ok": False, "success": False, "reason": "this account cannot post in that channel"})
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "success": False, "reason": str(e)})
        finally:
            if cmd == "reply_user" and _manual_replies.get(f"ch{cid}") is asyncio.current_task():
                _manual_replies.pop(f"ch{cid}", None)

    async def _message_job(cmd_id, payload):
        """Someone's last message in full, for a Chats row that only has "[attachment]".

        Rows from the stored waiting list kept only text, so a picture they sent
        was gone by the time the tab showed it. This finds the message the same
        way a manual Reply does, keeps it for the next sweep, and pushes it to
        the row.
        """
        try:
            uid = int(payload["user_id"])
            u, _why = await resolve_user(uid)
            if not u:
                _write_result(cmd_id, {"ok": False, "reason": _why or "user not found"})
                return
            m = await _find_message_to_answer(u)
            if m is None:
                _write_result(cmd_id, {"ok": False,
                                       "reason": "could not fetch it just now, Discord limits how often; try again in a minute"})
                return
            if isinstance(m.channel, discord.DMChannel):
                bot.waiting_msgs[uid] = m
            body = _message_payload(m)
            emit_chat_event({"t": "payload", "uid": str(uid), **body})
            _write_result(cmd_id, {"ok": True, **body})
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

    async def _history_job(cmd_id, payload):
        """The last messages of a DM, both sides, for the Chats tab's chat view.

        One history fetch, on the manual allowance, never the sweep's. It also
        refreshes what the bot holds as their latest message, so a row that
        only said "[attachment]" gets its picture back as a side effect.
        """
        try:
            uid = int(payload["user_id"])
            # Up to 200: older ones come out of the chat log, and only what it lacks from Discord.
            limit = max(5, min(200, int(payload.get("limit") or 20)))
            u, _why = await resolve_user(uid)
            if not u:
                _write_result(cmd_id, {"ok": False, "reason": _why or "user not found"})
                return
            dm = u.dm_channel
            if dm is None:
                try:
                    dm = await u.create_dm()
                except Exception as e:
                    _write_result(cmd_id, {"ok": False, "reason": f"no DM with them ({e})"})
                    return
            me = getattr(bot, "selfbot_id", None) or bot.user.id
            synced = getattr(bot, "_synced_dms", None)
            if synced is None:
                synced = bot._synced_dms = set()
            exhausted = getattr(bot, "_dm_start_reached", None)
            if exhausted is None:
                exhausted = bot._dm_start_reached = set()
            have = _chatlog.count(ACCOUNT_INDEX, uid)
            # Read from Discord this session already, and everything since has
            # come in live: the log has it all, and Discord is not asked again.
            if uid in synced and (have >= limit or uid in exhausted):
                _write_result(cmd_id, {"ok": True, "messages": _chatlog.conversation(ACCOUNT_INDEX, uid, limit), "from_log": True})
                return
            if not _manual_history_budget.allow():
                if have:
                    _write_result(cmd_id, {"ok": True, "messages": _chatlog.conversation(ACCOUNT_INDEX, uid, limit), "from_log": True})
                else:
                    _write_result(cmd_id, {"ok": False,
                                           "reason": "Discord limits how often history can be read; try again in a minute"})
                return
            fetched, latest_theirs = [], None
            if uid in synced:
                # Scrolling back past what is kept: only the older ones are read.
                first = _chatlog.conversation(ACCOUNT_INDEX, uid, have)[:1] if have else []
                before = discord.Object(id=int(first[0]["mid"])) if first else None
                async for m in dm.history(limit=limit - have, before=before):
                    if m.type in (discord.MessageType.default, discord.MessageType.reply):
                        fetched.append(m)
                if not fetched:
                    exhausted.add(uid)
            else:
                async for m in dm.history(limit=limit):
                    if m.type not in (discord.MessageType.default, discord.MessageType.reply):
                        continue
                    if m.author.id != me and latest_theirs is None:
                        latest_theirs = m
                    fetched.append(m)
                synced.add(uid)
                if len(fetched) < limit:
                    exhausted.add(uid)
            if fetched:
                _chatlog.put_many(ACCOUNT_INDEX, uid, [(m.id, m.author.id == me, m.created_at.timestamp(), _message_payload(m))
                                                       for m in fetched])
                for m in fetched:
                    _keep_pictures(m)
                # Kept here, but no longer on Discord, in the stretch just read: deleted while nobody was watching.
                stamps = [m.created_at.timestamp() for m in fetched]
                _chatlog.missing_since(ACCOUNT_INDEX, uid, min(stamps), max(stamps), [m.id for m in fetched])
            out = _chatlog.conversation(ACCOUNT_INDEX, uid, limit)
            # Still waiting on a reply (their message is the last one): that is what a manual Reply answers.
            if latest_theirs is not None and out and not out[-1]["mine"]:
                bot.waiting_msgs[uid] = latest_theirs
                emit_chat_event({"t": "payload", "uid": str(uid), **_message_payload(latest_theirs)})
            _write_result(cmd_id, {"ok": True, "messages": out})
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

    async def _dm_for(cmd_id, payload):
        """The DM with the person a Chats request is about, or None after answering why not."""
        u, _why = await resolve_user(int(payload["user_id"]))
        if not u:
            _write_result(cmd_id, {"ok": False, "reason": _why or "user not found"})
            return None
        try:
            return u.dm_channel or await u.create_dm()
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": f"no DM with them ({e})"})
            return None

    def _found(m, me) -> dict:
        return {"mine": m.author.id == me, "ts": m.created_at.timestamp(), **_message_payload(m)}

    async def _search_job(cmd_id, payload):
        """Discord's own search over a DM, for the Chats tab: everything ever said in it, not only what is kept here.

        25 at a time. Newest or oldest first pages on from the last one shown (cursor), the most relevant first by
        offset, as Discord's own app does. What it finds is shown, not kept: the chat log is one unbroken stretch of
        the conversation up to now, and odd old messages in it would break that.
        """
        try:
            uid = int(payload["user_id"])
            if not _search_budget.allow():
                _write_result(cmd_id, {"ok": False, "reason": "Discord limits how often you can search; try again in a minute"})
                return
            dm = await _dm_for(cmd_id, payload)
            if dm is None:
                return
            me = getattr(bot, "selfbot_id", None) or bot.user.id
            kw = {"limit": 25}
            words = " ".join(str(w) for w in payload.get("words") or [] if str(w).strip())
            if words:
                kw["content"] = words[:500]
            if payload.get("mine") is not None:
                kw["authors"] = [discord.Object(id=me if payload["mine"] else uid)]
            has = [h for h in payload.get("has") or [] if h in _SEARCH_HAS]
            if has:
                kw["has"] = has
            for edge in ("before", "after"):
                if payload.get(edge):
                    kw[edge] = datetime.fromtimestamp(float(payload[edge]), tz=timezone.utc)
            sort, cursor = payload.get("sort") or "newest", payload.get("cursor")
            if sort == "relevant":
                kw["most_relevant"] = True
                kw["offset"] = max(0, int(payload.get("offset") or 0))
            elif sort == "oldest":
                kw["oldest_first"] = True
                if cursor:
                    kw["after"] = discord.Object(id=int(cursor))
            elif cursor:
                kw["before"] = discord.Object(id=int(cursor))
            out, total, indexing = [], None, False
            async for m in dm.search(**kw):
                if total is None:
                    total = getattr(m, "total_results", None)
                    indexing = bool(getattr(m, "doing_deep_historical_index", False))
                out.append(_found(m, me))
            _write_result(cmd_id, {"ok": True, "messages": out, "total": total if total is not None else len(out),
                                   "more": len(out) >= 25, "indexing": indexing})
        except KeyError:
            # Discord answers 202 with no results while it is still indexing a conversation it had not searched before.
            _write_result(cmd_id, {"ok": False, "retry": True,
                                   "reason": "Discord is still getting this chat ready to search; try again in a moment"})
        except discord.HTTPException as e:
            _write_result(cmd_id, {"ok": False, "reason": f"Discord refused the search ({e.status})"})
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

    async def _window_job(cmd_id, payload):
        """Part of a DM read from Discord, for the Chats tab: the messages either side of one ("around", to jump to it
        from a search), before it ("older", scrolling back), after it ("newer", scrolling on towards now) or the very
        first ones ("first"). Shown, not kept, like a search's results; one history read, on the manual allowance."""
        try:
            direction = payload.get("dir") or "around"
            limit = max(5, min(100, int(payload.get("limit") or 50)))
            mid = int(payload["mid"]) if payload.get("mid") else None
            if direction != "first" and mid is None:
                _write_result(cmd_id, {"ok": False, "reason": "which message?"})
                return
            if not _manual_history_budget.allow():
                _write_result(cmd_id, {"ok": False, "reason": "Discord limits how often history can be read; try again in a minute"})
                return
            dm = await _dm_for(cmd_id, payload)
            if dm is None:
                return
            me = getattr(bot, "selfbot_id", None) or bot.user.id
            if direction == "first":
                kw = {"after": discord.Object(id=1), "oldest_first": True}
            elif direction == "older":
                kw = {"before": discord.Object(id=mid)}
            elif direction == "newer":
                kw = {"after": discord.Object(id=mid), "oldest_first": True}
            else:
                kw = {"around": discord.Object(id=mid)}
            got = [m async for m in dm.history(limit=limit, **kw)
                   if m.type in (discord.MessageType.default, discord.MessageType.reply)]
            got.sort(key=lambda m: m.id)
            _write_result(cmd_id, {"ok": True, "messages": [_found(m, me) for m in got], "more": len(got) >= limit})
        except discord.NotFound:
            _write_result(cmd_id, {"ok": False, "reason": "that message is not on Discord any more"})
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

    async def _send_message_job(cmd_id, payload):
        """A message typed in the Chats tab, sent as this account. A reply the bot had lined up for them is dropped
        first: you answered them yourself. It goes into the bot's history as the account's own words, so the next
        reply knows what was said."""
        try:
            uid = int(payload["user_id"])
            text = str(payload.get("text") or "").strip()
            files, why_files = _decode_files(payload.get("files"))
            if why_files:
                _write_result(cmd_id, {"ok": False, "reason": why_files})
                return
            if not text and not files:
                _write_result(cmd_id, {"ok": False, "reason": "nothing to send"})
                return
            if len(text) > 2000:
                _write_result(cmd_id, {"ok": False, "reason": "Discord takes up to 2000 characters in one message"})
                return
            u, _why = await resolve_user(uid)
            if not u:
                _write_result(cmd_id, {"ok": False, "reason": _why or "user not found"})
                return
            dropped = cancel_pending_reply(uid)
            clear_reply_state(uid)
            dm = u.dm_channel or await u.create_dm()
            async with bot.global_send_lock:
                sent = await dm.send(text or None, files=_as_discord_files(files) or None)
            bot.last_global_send = time.time()
            bot.message_history.setdefault(f"{uid}-{dm.id}", []).append(
                {"role": "assistant", "content": text or f"[sent {len(files)} picture(s)]"})
            try:
                mark_responded(uid, dm.id)
            except Exception:
                pass
            if dropped:
                log_system(f"You answered {u.name} from the panel, so the bot's reply was dropped")
            _write_result(cmd_id, {"ok": True, "mid": str(sent.id), "ts": sent.created_at.timestamp(),
                                   "dropped_reply": dropped, **_message_payload(sent)})
        except discord.Forbidden:
            _write_result(cmd_id, {"ok": False, "reason": "they have blocked the account or closed their DMs"})
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

    async def _reply_user_job(cmd_id, payload):
        """One manual Reply, run beside the command loop rather than in it. A reply takes as long as the bot takes to write and type it, up to a couple of minutes, and it used to run inline, so every other request from the panel (the Chats list, the account status) waited behind it and timed out. That was the "Chats sometimes does not work". Held in _manual_replies while it runs, so Cancel can stop it."""
        key = str(payload.get("user_id"))
        _manual_replies[key] = asyncio.current_task()
        try:
            await _reply_user_work(cmd_id, payload)
        except asyncio.CancelledError:
            # Cancelled from the panel while it was being written: whatever went out already stays.
            try:
                set_reply_state(int(key), "skipped", reason="you cancelled the reply")
            except Exception:
                pass
            log_system("A reply asked for from the panel was cancelled before it was finished")
            _write_result(cmd_id, {"success": False, "cancelled": True, "reason": "you cancelled the reply"})
        finally:
            if _manual_replies.get(key) is asyncio.current_task():
                _manual_replies.pop(key, None)

    async def _reply_user_work(cmd_id, payload):
        try:
            uid = int(payload["user_id"])
            # a failure that can never succeed takes the message off the waiting list too, or it comes back on every sweep
            from app.utils.db import drop_unresponded as _drop
            if uid == bot.user.id:
                _drop(uid)
                _write_result(cmd_id, {"success": False, "dropped": True,
                                       "reason": "that is this account, Discord has no DM with yourself"})
                return
            try:
                u, _why = await resolve_user(uid)
            except Exception as _fe:
                _write_result(cmd_id, {"success": False, "reason": str(_fe)})
                return
            if not u:
                _drop(uid)
                _write_result(cmd_id, {"success": False, "dropped": True,
                                       "reason": _why or "user not found"})
                return
            target_msg = await _find_message_to_answer(u)
            if not target_msg:
                log_error("Reply", f"Could not find {u.name}'s last message to answer. "
                                   f"Discord's history lookups are rate limited; try again shortly.")
                _write_result(cmd_id, {"success": False, "retryable": True,
                                       "reason": "could not find their last message just now, try again in a minute"})
                return
            if await _answered_since(target_msg):
                # their last message is still theirs, but it has had its answer: replying again is the bot talking to itself
                bot.waiting_msgs.pop(uid, None)
                clear_reply_state(uid)
                try:
                    if isinstance(target_msg.channel, discord.DMChannel):
                        mark_responded(uid, target_msg.channel.id)
                except Exception:
                    pass
                log_system(f"Not replying to {u.name}: their last message was already answered")
                _write_result(cmd_id, {"success": False, "dropped": True,
                                       "reason": "already answered, the bot has spoken since"})
                return
            set_reply_state(uid, "writing")
            hk = history_key(target_msg)
            await seed_history(hk, target_msg)
            history = bot.message_history.get(hk, [])
            combined = as_turn(target_msg, target_msg.content or "[attachment]")
            if not history or history[-1].get("content") != combined:
                history.append({"role": "user", "content": combined})
                bot.message_history[hk] = history
            resp = await generate_response_and_reply(target_msg, combined, history,
                                                     bypass_cooldown=True, bypass_typing=True)
            if resp:
                bot.message_history[hk].append({"role": "assistant", "content": resp})
                clear_reply_state(uid)
                # apart: a failure recording the stats used to skip taking them off the waiting list, which put them straight back on it
                try:
                    if isinstance(target_msg.channel, discord.DMChannel):
                        mark_responded(uid, target_msg.channel.id)
                except Exception:
                    pass
                try:
                    record_user_message(uid, u.name, account=ACCOUNT_INDEX)
                except Exception:
                    pass
                _write_result(cmd_id, {"success": True})
            elif uid in _blocked_users:
                _write_result(cmd_id, {"success": False, "dropped": True,
                                       "reason": "they have blocked the account or closed their DMs"})
            elif (_why_not := ai_module.unavailable_now()):
                # No model can reply right now: that is the reason, said once already, not a line for each person.
                set_reply_state(uid, "failed", reason=_why_not)
                _write_result(cmd_id, {"success": False, "retryable": True, "reason": _why_not})
            else:
                # left on the waiting list on purpose: unlike a block, this can succeed later; logged, so "see the log" has a line to see
                log_error("Reply", f"No reply sent to {u.name} ({uid}): the model returned "
                                   f"nothing or the send was refused. It stays on the waiting list.")
                set_reply_state(uid, "failed", reason="no reply was generated, see the log")
                _write_result(cmd_id, {"success": False, "retryable": True,
                                       "reason": "no reply was generated (model returned nothing or refused)"})
        except Exception as _e:
            log_error("Reply", f"{type(_e).__name__}: {_e}")
            try:
                _write_result(cmd_id, {"success": False, "retryable": True, "reason": str(_e)})
            except Exception:
                pass

    log_system("Telegram IPC bridge started")

    _FLAG_FILE = _Path(resource_path("config/update.flag"))

    while not bot.is_closed():
        await asyncio.sleep(_POLL_INTERVAL)

        # ── Check for update sentinel flag (written by Telegram controller) ──
        if _FLAG_FILE.exists():
            try:
                _flag_source = _FLAG_FILE.read_text(encoding="utf-8").strip() or "release"
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
            # UTF-8, as the panel and Telegram write it: read with the Windows default, any command carrying an emoji or an accent arrived here as mojibake
            raw = _CMD_FILE.read_text(encoding="utf-8")
            commands = _json.loads(raw)
        except Exception:
            continue
        if not commands:
            continue

        # error notifications are for the Telegram controller to consume, the runner only queues them, so they must survive this pass
        remaining = [e for e in commands if e.get("cmd") == "send_error_notification"]
        commands = [e for e in commands if e.get("cmd") != "send_error_notification"
                    and e.get("id") not in _RAN_COMMANDS]
        for entry in commands:
            cmd_id  = entry.get("id", "")
            cmd     = entry.get("cmd", "")
            payload = entry.get("payload", {})
            # a reply asked for before this worker was running: whoever asked stopped waiting long ago, and answering now is answering an old message out of nowhere. restarts used to replay an unfinished Reply to all every time.
            try:
                _age = time.time() - float(entry.get("ts") or 0) if entry.get("ts") else 0.0
            except (TypeError, ValueError):
                _age = 0.0
            if cmd in _REPLY_REQUEST_TTL and _age > _REPLY_REQUEST_TTL[cmd]:
                log_system(f"Dropped a {cmd} request from {int(_age)}s ago: it was waiting while the account was not running")
                _write_result(cmd_id, {"success": False, "reason": "expired: it was asked for before the account restarted"})
                continue
            try:
                # a server conversation's row, "ch<channel id>": first, before the same commands for a person's DM
                if cmd in ("chat_message", "chat_history", "cancel_reply", "reply_user", "send_message", "react") \
                        and _server_id(payload) is not None:
                    asyncio.create_task(_server_job_safe(cmd, cmd_id, _server_id(payload), payload))

                elif cmd == "pause":
                    bot.paused = not bot.paused
                    _write_result(cmd_id, {"paused": bot.paused})
                    emit_chat_meta()

                elif cmd == "wipe":
                    bot.message_history.clear()
                    _write_result(cmd_id, {"ok": True})

                # Written where the value came from (app/utils/configstore.py): this persona's own stays its own,
                # everyone's stays everyone's. Dumping the settings this account runs with would have written its
                # persona's values into everyone's.
                elif cmd == "toggle_dm":
                    from app.utils import configstore as _cs
                    bot.allow_dm = not bot.allow_dm
                    _cs.set_effective("bot.allow_dm", bot.allow_dm)
                    _write_result(cmd_id, {"allow_dm": bot.allow_dm})

                elif cmd == "toggle_gc":
                    from app.utils import configstore as _cs
                    bot.allow_gc = not bot.allow_gc
                    _cs.set_effective("bot.allow_gc", bot.allow_gc)
                    _write_result(cmd_id, {"allow_gc": bot.allow_gc})

                elif cmd == "toggle_server":
                    from app.utils import configstore as _cs
                    bot.allow_server = not getattr(bot, "allow_server", True)
                    _cs.set_effective("bot.allow_server", bot.allow_server)
                    _write_result(cmd_id, {"allow_server": bot.allow_server})

                elif cmd == "ignore_add":
                    uid = int(payload["user_id"])
                    if uid not in bot.ignore_users:
                        bot.ignore_users.append(uid)
                    # A reply already lined up for them stops too, as with the Bot off switch.
                    bot.cancelled_replies.add(uid)
                    for _bk in [k for k in list(bot.user_message_batches) if k.startswith(f"{uid}-")]:
                        bot.user_message_batches.pop(_bk, None)
                    for _bk in [k for k in list(bot.message_queues) if k.startswith(f"{uid}-")]:
                        bot.message_queues.pop(_bk, None)
                    set_reply_state(uid, "skipped", reason="you are ignoring them")
                    emit_chat_event({"t": "ignored", "uid": str(uid), "ignored": True})
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "ignore_remove":
                    uid = int(payload["user_id"])
                    if uid in bot.ignore_users:
                        bot.ignore_users.remove(uid)
                    if (bot.reply_state.get(uid) or {}).get("state") == "skipped":
                        bot.reply_state.pop(uid, None)
                        emit_chat_event({"t": "state", "uid": str(uid), "state": None})
                    emit_chat_event({"t": "ignored", "uid": str(uid), "ignored": False})
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
                    # Read from this account's persona, not taken from the message: whoever wrote it, the file is
                    # the one every account on that persona reads.
                    bot.instructions = load_instructions()
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "memory_changed":
                    # Someone's memory was edited in the panel: read again on their next message.
                    try:
                        bot._memory_cache.pop(int(payload.get("user_id")), None)
                    except (TypeError, ValueError):
                        bot._memory_cache.clear()
                    _write_result(cmd_id, {"ok": True})

                elif cmd == "config_update":
                    # Everything is read again from this account's settings, its persona's on everyone's: the
                    # switches the bot holds (allow_dm and the rest) and what was cached at import (timings,
                    # chances, mood, late and stale replies). Never the value in the message: that is everyone's
                    # or another persona's, and would cover this persona's own.
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
                            # same weak-cache problem as everywhere else: a miss here showed the raw snowflake as the person's name
                            u = _seen_users.get(uid) or bot.get_user(uid)
                            pending = [e["content"] for e in reversed(history) if e["role"] == "user"]
                            last = pending[0] if pending else ""
                            snippet = (last[:60] + "…") if len(last) > 60 else last
                            # when the bot will answer this one on its own, from the batch it is sitting in
                            _due = 0.0
                            try:
                                for _bk, _b in bot.user_message_batches.items():
                                    if _bk.startswith(f"{uid}-") and _b.get("reply_at"):
                                        _due = max(_due, float(_b["reply_at"]))
                            except Exception:
                                pass
                            _row = {
                                "reply_at": _due or None,
                                "id": uid,
                                "name": u.name if u else str(uid),
                                "snippet": snippet,
                                "count": len(pending),
                                "ts": 0,          # this session, so effectively now
                            }
                            # The message itself, when the bot saw it arrive:
                            # full text, pictures and stickers for the tab.
                            _wm = bot.waiting_msgs.get(uid)
                            if _wm is not None:
                                try:
                                    _row.update(_message_payload(_wm))
                                    _row["ts"] = _wm.created_at.timestamp()
                                except Exception:
                                    pass
                            users_out.append(_row)
                        except Exception:
                            pass

                    # Pass 2: live DM channel scan (catches post-restart gaps); the budget is spent once for the whole sweep, not per channel, since with 20 DMs the per-channel cost drained an hour of budget in three refreshes and conversations just vanished
                    _scanned = 0
                    # raised from 30, and - the part that actually mattered - the channels are now walked newest-first. the cap always truncated the SAME arbitrary 30, because private_channels comes back in whatever order Discord sent it, so anyone past position 30 in that list was never looked at once. an unread message is recent by definition, so sorting by last_message_id (a snowflake, so it sorts by time) puts the ones worth finding at the front and leaves only a long-idle tail to be cut
                    _SCAN_CAP = 80
                    _truncated = False
                    # the whole answer has to be back inside the panel's 10s IPC wait; raising the cap to 80 made a cold sweep take longer than that (each channel is a REST call), so the request timed out, everything found was thrown away, and the Chats tab would not load at all. stop fetching at this point and send what there is; the memo below means the next sweep starts where this one could not reach
                    _deadline = time.monotonic() + 6.0
                    try:
                        _selfbot_id = getattr(bot, "selfbot_id", None) or bot.user.id
                        # asked for only when a fetch is actually needed; it was taken on every sweep, memo hits and all, and the page sweeps every 15 seconds, so the hour's allowance of 60 was gone in 15 minutes, after which new unread DMs could no longer be found
                        _sweep_ok = None
                        _live_ids = set()
                        _dms = sorted(
                            (c for c in bot.private_channels
                             if isinstance(c, discord.DMChannel)),
                            key=lambda c: c.last_message_id or 0,
                            reverse=True,
                        )
                        for _ch in _dms:
                            if not isinstance(_ch, discord.DMChannel):
                                continue
                            _other = _ch.recipient
                            if _other is None or _other.id in seen_ids:
                                continue
                            # blocked: the DM still exists and still ends with their message, so this pass found it every time
                            if _other.id in _blocked_users:
                                continue
                            # Quick cache check, skip if bot sent the last message
                            _cached_last = None
                            if _ch.last_message_id:
                                _cached_last = _ch._state._get_message(_ch.last_message_id)
                            if _cached_last is not None and _cached_last.author.id == _selfbot_id:
                                continue
                            _live_ids.add(_ch.id)
                            # same last message as when this DM was last read: the answer cannot have changed, so no fetch. the bot's own reply moves last_message_id too, which is what invalidates an entry once someone is answered
                            _memo = _dm_scan_memo.get(_ch.id)
                            if _memo is not None and _memo[0] == _ch.last_message_id:
                                if _memo[1] is not None:
                                    seen_ids.add(_other.id)
                                    users_out.append({**_memo[1], "id": _other.id,
                                                      "name": _other.name})
                                continue
                            try:
                                # one budget unit covers the sweep; the cap keeps a huge DM list from turning into a REST storm. past the deadline, keep walking (memo hits further down are free) but fetch nothing more
                                if _sweep_ok is None:
                                    _sweep_ok = history_scan_allowed()
                                if (not _sweep_ok or _scanned >= _SCAN_CAP
                                        or time.monotonic() >= _deadline):
                                    _truncated = True
                                    continue
                                _scanned += 1
                                _left = max(0.5, _deadline - time.monotonic())
                                _last_msgs = await asyncio.wait_for(
                                    _recent_messages(_ch, 10), timeout=_left)
                                _entry = _waiting_entry(_last_msgs, _selfbot_id)
                                _dm_scan_memo[_ch.id] = (_ch.last_message_id, _entry)
                                # kept for a manual Reply, so answering someone this sweep found costs no second fetch
                                _lo = next((m for m in _last_msgs if m.author.id != _selfbot_id), None)
                                if _entry is not None and _lo is not None:
                                    bot.waiting_msgs[_other.id] = _lo
                                if _entry is not None:
                                    seen_ids.add(_other.id)
                                    users_out.append({**_entry, "id": _other.id,
                                                      "name": _other.name})
                            except asyncio.TimeoutError:
                                _truncated = True
                            except Exception:
                                continue
                        # Forget channels that are no longer in the DM list.
                        for _gone in [k for k in _dm_scan_memo if k not in _live_ids]:
                            _dm_scan_memo.pop(_gone, None)
                    except Exception:
                        pass

                    # Pass 3: the waiting list on disk; unresponded_messages has recorded this all along and nothing ever read it back, and it's the only source that survives a restart without needing the DM channel still in Discord's cache, so it catches people the two passes above can't see
                    try:
                        from app.utils.db import get_unresponded as _get_unres
                        for _row in _get_unres():
                            _ruid = int(_row["user_id"])
                            if _ruid in seen_ids or _ruid in _blocked_users:
                                continue
                            if _ruid == _selfbot_id:
                                continue
                            # the bot has the last word there already (a reply that did not clear this row): not waiting
                            try:
                                _rch = bot.get_channel(int(_row.get("channel_id") or 0))
                                _rlast = _rch._state._get_message(_rch.last_message_id) if _rch is not None and _rch.last_message_id else None
                                if _rlast is not None and _rlast.author.id == _selfbot_id:
                                    continue
                            except Exception:
                                pass
                            seen_ids.add(_ruid)
                            _ru = _seen_users.get(_ruid) or bot.get_user(_ruid)
                            _rtext = _row.get("content") or "[attachment]"
                            users_out.append({
                                "id": _ruid,
                                "name": _ru.name if _ru else str(_ruid),
                                "snippet": (_rtext[:60] + "…") if len(_rtext) > 60 else _rtext,
                                "count": 1,
                                "ts": _row.get("received_at") or 0,
                            })
                    except Exception as _dbe:
                        print(f"[Chats] could not read the stored waiting list: {_dbe}")

                    # Servers: the latest message in each channel that asked the bot for a reply, until it is answered
                    for _scid, _sm in list(bot.server_waiting.items()):
                        try:
                            _slast = _sm.channel._state._get_message(_sm.channel.last_message_id) if _sm.channel.last_message_id else None
                            if _slast is not None and _slast.author.id == _selfbot_id:
                                bot.server_waiting.pop(_scid, None)
                                continue
                            _srow = server_row(_sm)
                            _sdue = (bot.user_message_batches.get(f"{_sm.author.id}-{_scid}") or {}).get("reply_at")
                            _srow.update({"count": 1, "reply_at": _sdue or None})
                            _sst = bot.reply_state.get(_sm.author.id)
                            if _sst:
                                _srow["state"] = _sst
                            users_out.append(_srow)
                        except Exception:
                            continue

                    # why nothing has moved yet, so the page can say "in 40s" rather than leaving a list of unanswered people with no explanation; all of it is state the runner already holds
                    _cool_until = 0.0
                    if GLOBAL_COOLDOWN_ENABLED:
                        _cool_until = getattr(bot, "last_global_send", 0.0) + GLOBAL_COOLDOWN_MIN
                    _ignored_set = set(getattr(bot, "ignore_users", []))
                    for _u in users_out:
                        try:
                            _uid_i = int(_u["id"])
                            _st = bot.reply_state.get(_uid_i)
                            if _st:
                                _u["state"] = _st
                            if _uid_i in _ignored_set:
                                _u["ignored"] = True
                        except Exception:
                            pass
                    _write_result(cmd_id, {
                        "users": users_out,
                        # true when the DM sweep hit its cap, so the panel can say the list is the most recent N rather than all
                        "truncated": _truncated,
                        "paused": getattr(bot, "paused", False),
                        # Unix time when the next reply may be sent, or 0.
                        "cooldown_until": _cool_until if _cool_until > time.time() else 0,
                        "cooldown_range": [GLOBAL_COOLDOWN_MIN, GLOBAL_COOLDOWN_MAX]
                        if GLOBAL_COOLDOWN_ENABLED else None,
                    })

                elif cmd == "send_message":
                    # Off the loop, like a Reply: sending waits its turn behind the bot's own.
                    asyncio.create_task(_send_message_job(cmd_id, payload))

                elif cmd == "reply_user":
                    # Off the loop: see _reply_user_job.
                    asyncio.create_task(_reply_user_job(cmd_id, payload))

                elif cmd == "react":
                    asyncio.create_task(_react_job(cmd_id, payload))

                elif cmd == "chat_message":
                    # Off the loop too: it may fetch history.
                    asyncio.create_task(_message_job(cmd_id, payload))

                elif cmd == "chat_history":
                    asyncio.create_task(_history_job(cmd_id, payload))

                elif cmd == "chat_search":
                    # Off the loop: Discord can take seconds to answer a search.
                    asyncio.create_task(_search_job(cmd_id, payload))

                elif cmd == "chat_window":
                    asyncio.create_task(_window_job(cmd_id, payload))

                elif cmd == "reply_all":
                    # taken out of the command file before the run, not after: it runs for minutes, and a worker stopped part way through found it still there on the next start and ran it all again
                    _flush_commands(_CMD_FILE, remaining, commands)
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
                                _ra_u, _ra_why = await resolve_user(_ra_uid, _ra_cid)
                                if _ra_u is None:
                                    from app.utils.db import drop_unresponded as _ra_drop
                                    _ra_drop(_ra_uid)
                                    results_out.append({"id": _ra_uid, "name": str(_ra_uid),
                                                        "success": False, "dropped": True,
                                                        "reason": _ra_why or "user not found"})
                                    continue
                                _ra_ch2 = bot.get_channel(_ra_cid)
                                if _ra_ch2 is None:
                                    try:
                                        _ra_ch2 = await _ra_u.create_dm()
                                    except Exception:
                                        results_out.append({"id": _ra_uid, "name": _ra_u.name if _ra_u else str(_ra_uid), "success": False, "reason": "could not open DM"})
                                        continue
                                _ra_target = None
                                _ra_answered = False
                                if history_scan_allowed():
                                    async for _ra_m in _ra_ch2.history(limit=15):
                                        if _ra_m.author.id == _ra_selfbot_id:
                                            # the bot spoke after their last message: answered already
                                            _ra_answered = True; break
                                        if _ra_m.author.id == _ra_uid:
                                            _ra_target = _ra_m; break
                                if _ra_answered:
                                    try:
                                        if isinstance(_ra_ch2, discord.DMChannel):
                                            mark_responded(_ra_uid, _ra_ch2.id)
                                    except Exception:
                                        pass
                                    results_out.append({"id": _ra_uid, "name": _ra_u.name, "success": False,
                                                        "dropped": True, "reason": "already answered"})
                                    continue
                                if not _ra_target:
                                    results_out.append({"id": _ra_uid, "name": _ra_u.name, "success": False, "reason": "no recent message found"})
                                    continue
                                _ra_hk2 = _ra_hk or history_key(_ra_target)
                                _ra_hist = bot.message_history.get(_ra_hk2, [])
                                _ra_combined = "\n".join(e["content"] for e in _ra_hist[-3:] if e["role"] == "user") or (_ra_target.content or "[attachment]")
                                # Worked out before seeding: the seeded turns are what came before, not what is being answered.
                                if not _ra_hist:
                                    await seed_history(_ra_hk2, _ra_target)
                                    _ra_hist = bot.message_history.get(_ra_hk2, [])
                                if not _ra_hist or _ra_hist[-1].get("content") != _ra_combined:
                                    _ra_hist.append({"role": "user", "content": _ra_combined})
                                    bot.message_history[_ra_hk2] = _ra_hist
                                resp = await generate_response_and_reply(_ra_target, _ra_combined, _ra_hist, bypass_cooldown=True, bypass_typing=True)
                                if resp:
                                    bot.message_history[_ra_hk2].append({"role": "assistant", "content": resp})
                                    try:
                                        if isinstance(_ra_target.channel, discord.DMChannel):
                                            mark_responded(_ra_uid, _ra_target.channel.id)
                                    except Exception:
                                        pass
                                    results_out.append({"id": _ra_uid, "name": _ra_u.name, "success": True})
                                else:
                                    results_out.append({"id": _ra_uid, "name": _ra_u.name, "success": False, "reason": "no response generated"})
                            except Exception as _ra_e:
                                _ra_name = str(_ra_uid)
                                try:
                                    _ra_name = (await resolve_user(_ra_uid, _ra_cid))[0].name
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
                    # flush command file before exit so the restart entry is not re-processed on the next startup
                    _flush_commands(_CMD_FILE, remaining, commands)
                    await bot.close(); sys.exit(0)

                elif cmd == "get_status":
                    import app.utils.mood as _mood_mod
                    # the presence the account is actually showing, so the panel can put the same dot next to the avatar that Discord does; the client's own status (built from its sessions), not bot.user's: a user object carries no presence, so that read "offline" for an account that was online the whole time
                    try:
                        _pres = str(bot.status or "") or "offline"
                        if _pres == "offline" and not bot.is_closed():
                            # connected, so it is not offline: the sessions have not said yet, and the status this runner set is the one showing (online until it sets another)
                            _pres = str(getattr(bot, "shown_status", None) or "online")
                    except Exception:
                        _pres = "offline"
                    _night, _ = night_window_state(config["bot"].get("night_invisible") or {})
                    _write_result(cmd_id, {
                        "paused": bot.paused,
                        "mood": _mood_mod.current_mood,
                        "active_channels": len(bot.active_channels),
                        "ignored_users": len(bot.ignore_users),
                        "presence": _pres,
                        # worth saying: an account showing invisible at 3am is the night schedule doing its job, not a fault
                        "night": bool(_night),
                        "latency_ms": (round(bot.latency * 1000)
                                       if bot.latency and bot.latency == bot.latency else None),
                        "guilds": len(getattr(bot, "guilds", []) or []),
                        "friends": len(getattr(bot, "friends", []) or []),
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
                        # "Won't answer, turned off" no longer describes them.
                        if (bot.reply_state.get(uid) or {}).get("state") == "skipped":
                            bot.reply_state.pop(uid, None)
                            emit_chat_event({"t": "state", "uid": str(uid), "state": None})
                        _write_result(cmd_id, {"ok": True, "ignored": False})
                    else:
                        bot.ignore_users.append(uid)
                        from app.utils.db import add_ignored_user as _aiu
                        _aiu(uid)
                        # A reply already scheduled for them would otherwise
                        # still go out: turning them off stops that one too.
                        bot.cancelled_replies.add(uid)
                        for _bk in [k for k in list(bot.user_message_batches) if k.startswith(f"{uid}-")]:
                            bot.user_message_batches.pop(_bk, None)
                        for _bk in [k for k in list(bot.message_queues) if k.startswith(f"{uid}-")]:
                            bot.message_queues.pop(_bk, None)
                        set_reply_state(uid, "skipped", reason="you turned the bot off for them")
                        _write_result(cmd_id, {"ok": True, "ignored": True})
                    emit_chat_event({"t": "ignored", "uid": str(uid), "ignored": uid in bot.ignore_users})

                elif cmd == "cancel_reply":
                    uid = int(payload["user_id"])
                    # One being written because it was asked for by hand stops where it is.
                    _stopped = _stop_manual_reply(uid)
                    bot.cancelled_replies.add(uid)
                    # Drop the batch so a sleeping timer does not fire, and
                    # forget the queued messages so they do not re-trigger it.
                    for _bk in [k for k in list(bot.user_message_batches) if k.startswith(f"{uid}-")]:
                        bot.user_message_batches.pop(_bk, None)
                    for _bk in [k for k in list(bot.message_queues) if k.startswith(f"{uid}-")]:
                        bot.message_queues.pop(_bk, None)
                    set_reply_state(uid, "skipped", reason="you cancelled the reply")
                    _write_result(cmd_id, {"ok": True, "stopped": _stopped})

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

                # get_profile fills the panel's profile card for someone the bot hasn't spoken to since the cache existed; without it an avatar only appears after they happen to message again
                elif cmd == "get_profile":
                    _uid = int(payload["user_id"])
                    _user, _why = await resolve_user(_uid)
                    if _user is None:
                        _write_result(cmd_id, {"ok": False,
                                               "reason": _why or f"User {_uid} not found."})
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
                elif cmd == "summarize_user":
                    async def _summarize(cmd_id=cmd_id, payload=dict(payload)):
                        try:
                            _uid = int(payload["user_id"])
                            _count = max(5, min(100, int(payload.get("count") or 20)))
                            lines, name, source = await _conversation_lines(
                                _uid, _count, bool(payload.get("include_mine", True)))
                            if not lines:
                                _write_result(cmd_id, {
                                    "ok": False,
                                    "reason": "No messages with them that this account can read."})
                                return
                            text = await summarize_conversation(
                                lines, name, payload.get("length") or "medium",
                                payload.get("language") or "auto")
                            if not text:
                                _write_result(cmd_id, {"ok": False,
                                                       "reason": "The model returned nothing."})
                                return
                            # The last few lines go back with it: Big Picture shows them under the summary, and keeping them beside it means showing them never costs another read of the DM.
                            _write_result(cmd_id, {"ok": True, "summary": text,
                                                   "count": len(lines), "source": source,
                                                   "recent": [{"mine": _who == "Me", "text": str(_line)[:300]}
                                                              for _who, _line in lines[-4:]]})
                        except Exception as _se:
                            _write_result(cmd_id, {"ok": False, "reason": str(_se)[:200]})

                    _t = asyncio.create_task(_summarize())
                    _summary_tasks.add(_t)
                    _t.add_done_callback(_summary_tasks.discard)

                elif cmd == "analyse_user":
                    _uid = int(payload["user_id"])
                    _user, _why = await resolve_user(_uid)
                    if _user is None:
                        _write_result(cmd_id, {"ok": False,
                                               "reason": _why or f"User {_uid} not found."})
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
                        load_instructions() +
                        f"\n\nSomeone asked you to give your honest read on {_user.name} based on their messages. "
                        "Stay in character. Give your real unfiltered opinion like you would to a friend. "
                        "Be casual, funny, and direct. Roast them a bit but also be real about what you actually see. "
                        "Reference specific things they said to back up your points. "
                        "Keep it conversational, no bullet points, no formal structure, just talk like yourself. "
                        "Don't be overly mean but don't sugarcoat either. Max 3-4 short paragraphs."
                    )
                    _analyse_prompt = "Here are their messages: " + " | ".join(_msg_list[-200:])
                    _profile = await generate_response(_analyse_prompt, _analyse_instructions, history=None)
                    if _profile and is_refusal(_profile):
                        _profile = random.choice(refusal_fallbacks())
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
                    from app.utils import configstore as _cs_aj
                    _aj_args = payload.get("args", "").strip()
                    if not _aj_args or _aj_args.lower() == "off":
                        # To the layer it comes from (configstore.set_effective), as ,autojoin does: dumping this
                        # account's settings wrote its persona's own values into everyone's config.yaml.
                        _cs_aj.set_effective("bot.autojoin_channel", None)
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
                    _cs_aj.set_effective("bot.autojoin_channel",
                                         {"guild_id": _aj_target.guild.id, "channel_id": _aj_target.id})
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

                # friend requests, answered now rather than on a timer: the background loop spreads accepts over hours so the account doesn't look automated, which is right by default but wrong when you're watching one arrive, so the panel can take them straight away
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
                                    # none means no accept is scheduled: either automatic accepting is off, or this one arrived after the startup sweep
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
                                _fa_r = await accept_friend_request(_fa_s, _fa_uid)
                            else:
                                _fa_r = await _fa_s.delete(
                                    f"https://discord.com/api/v9/users/@me/relationships/{_fa_uid}")
                        if _fa_r.status_code in (200, 204):
                            _friend_due.pop(_fa_uid, None)
                            log_system(("Accepted" if _accepting else "Declined")
                                       + f" friend request from {_fa_uid}")
                            _write_result(cmd_id, {"ok": True})
                        else:
                            log_error("Friend Request", discord_reason(_fa_r))
                            _write_result(cmd_id, {"ok": False, "reason": discord_reason(_fa_r)})
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
                    # telegram writes config/update.flag directly; this keeps the Discord /update command working too
                    _upd_source = payload.get("source", "release")
                    if _upd_source not in ("release", "main"):
                        _upd_source = "release"
                    _upd_flag = _Path(resource_path("config/update.flag"))
                    _upd_flag.write_text(_upd_source, encoding="utf-8")
                    # do NOT re-append to remaining, the flag poller above would re-write the flag and fire the update twice
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
                    _ia_folder = _my_pictures()
                    _ia_path   = os.path.join(_ia_folder, _ia_name)
                    # if no b64 was sent (same-machine case), read the file from disk; otherwise decode and write it
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
                        from app.utils.pictures import DESCRIBE_MAX_TOKENS, clean_description, describe_messages
                        _ia_resp = await _cic_ia(
                            _ia_model,
                            messages=describe_messages(_ia_data_url),
                            max_tokens=DESCRIBE_MAX_TOKENS,
                            reasoning_effort="none",
                        )
                        _ia_desc = clean_description(_ia_resp.choices[0].message.content or "")
                        if not _ia_desc:
                            raise RuntimeError("The model answered with nothing.")
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
                    _isd_folder = _my_pictures()
                    _isd_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}
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
                    _img_folder = _my_pictures()
                    _img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}
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
                    _idm_folder = _my_pictures()
                    _idm_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}
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
                    _imgd_folder = _my_pictures()
                    _imgd_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}
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

    # record who this account actually is, so the panel can show the real username and avatar instead of just "Discord #1"; written to a file rather than fetched over IPC, so it is still there for a stopped account
    try:
        import json as _idjson
        # The profile banner, or the colour picked instead of one, for the card's top: Discord sends both
        # for your own account when it connects, so no extra request is made to learn them.
        _banner = getattr(bot.user, "banner", None)
        _accent = getattr(bot.user, "accent_colour", None)
        _identity = {
            "id": str(bot.user.id),
            "username": bot.user.name,
            "display_name": getattr(bot.user, "global_name", None) or bot.user.name,
            "avatar": str(bot.user.display_avatar.url) if getattr(bot.user, "display_avatar", None) else "",
            "banner": str(_banner.replace(format="png", size=600).url) if _banner else "",
            "accent": str(_accent) if _accent else "",
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

    # people who cannot be messaged, remembered across restarts; without this a blocked conversation reappeared on the waiting list on every launch, and every reply to it failed with the same 403
    try:
        from app.utils.db import blocked_users as _stored_blocked
        _blocked_users.update(_stored_blocked().keys())
        if _blocked_users:
            log_system(f"{len(_blocked_users)} conversation(s) cannot be messaged, skipping them")
    except Exception:
        pass

    asyncio.create_task(_reply_pending_messages())
    asyncio.create_task(_cleanup_loop())

    # ground truth for the client-profile question: ask Discord what clients it sees on this account. if an old web session from a previous run is still lingering (killed process, no close frame), it shows up here too, and Discord drops it within a minute or two
    asyncio.create_task(_log_active_sessions())

    nudge_cfg = config["bot"].get("nudge") or {}
    if nudge_cfg.get("enabled", False):
        asyncio.create_task(_nudge_loop())

    fr_cfg = config["bot"].get("friend_requests") or {}
    if fr_cfg.get("enabled", False):
        asyncio.create_task(_friend_request_loop())

    asyncio.create_task(_tg_ipc_loop())


async def _log_active_sessions():
    """Ask Discord's sessions endpoint which clients it sees on this account. One call per login, logged once; this is the authoritative answer to "does the profile say web or desktop", each session's client_info coming straight from what the IDENTIFY payload claimed."""
    try:
        await asyncio.sleep(3)
        async with build_session(bot._connection.http.token) as s:
            resp = await s.get("https://discord.com/api/v9/auth/sessions")
            if resp.status_code != 200:
                log_system(f"[SESSIONS] endpoint returned {resp.status_code}")
                return
            # Discord answers {"user_sessions": [...]}: walking that object went over its keys, and every login
            # ended in "'str' object has no attribute 'get'". Each session has os, platform and when it was last
            # used; its location is left out of the log.
            data = resp.json()
            sessions = data.get("user_sessions") if isinstance(data, dict) else data
            for sess in sessions or []:
                if not isinstance(sess, dict):
                    continue
                ci = sess.get("client_info") or {}
                log_system(
                    f"[SESSIONS] os={ci.get('os')} platform={ci.get('platform')} "
                    f"last used={sess.get('approx_last_used_time')}"
                )
    except Exception as e:
        log_error("Sessions Check", str(e))


async def setup_hook():
    bot.generate_response_and_reply = generate_response_and_reply
    await _apply_client_profile()

    # proof of what the gateway will identify as: logs the exact properties the IDENTIFY payload carries on the first connect of each session
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

# raw message_reference cache: message_id -> referenced_message_id. discord.py-self sometimes drops message.reference for server channels, so catch it here from the raw gateway payload before it's stripped
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

    _trig = (
        TRIGGER_RE.search(message.content.lower())
        if not is_server and TRIGGER_RE is not None else None
    )
    content_has_trigger = _trig is not None
    if _trig is not None:
        emit_use("bot.trigger", _trig.group(0))

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
    """Fetch profile info (status, bio, display name) as a context block. Bio is cached in-memory, then the DB, then fetched from Discord."""
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
                # 3. fetch from Discord and persist, budgeted so bulk sweeps (/analyse, /reply all) can't burst the profile endpoint; when the budget denies the fetch, leave the cache empty so a later message retries within the next window
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


def _sticker_image_url(message) -> str | None:
    """A picture URL for a message's first sticker, or None.

    Discord stickers come in three formats: PNG (1), APNG (2) and Lottie (3),
    plus GIF (4). The first, second and fourth are real images the vision model
    can look at once normalised to a still frame; Lottie is vector JSON and has
    no picture, so it is left to its name in the text instead.
    """
    for st in getattr(message, "stickers", []) or []:
        fmt = getattr(getattr(st, "format", None), "value", None)
        if fmt == 3:                       # Lottie, no raster image
            continue
        url = getattr(st, "url", None)
        if url:
            return str(url)
    return None


def _sticker_names(message) -> str:
    """"[sticker: wave]" style text for a message's stickers, for the prompt."""
    names = [getattr(st, "name", "") for st in (getattr(message, "stickers", []) or [])]
    names = [n for n in names if n]
    if not names:
        return ""
    return " ".join(f"[sticker: {n}]" for n in names)


def _extract_image_url_from_message(message) -> str | None:
    """Extract an image URL from message embeds or raw image URLs in content."""
    # A sticker is an image too; the vision path normalises it to a still frame.
    _sticker = _sticker_image_url(message)
    if _sticker:
        return _sticker

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


# The model is taught to emit control tokens the person must never see: a
# [[PIC:N|N2]] to choose a picture, a [[REACT:emoji]] or [[REACT_ONLY:emoji]] to
# react. Every one is the double-bracket form, and every one gives the account
# away the moment it is sent as text. The dedicated parsers take the well-formed
# ones (and act on them); this is the net under all of it, catching any [[...]]
# token whole or broken - one closing bracket, none, or a tag cut off at the very
# end of the reply - because a model that has seen the pattern emits broken
# versions of it, which is how "[[PIC:2]" and "[[REACT:" both went out once.
#
# Double brackets only, so ordinary writing - "[that's] crazy", "brb [2 min]" -
# is never touched: a person effectively never types "[[".
_CONTROL_TAG_RE = re.compile(r"\[\[[^\[\]\n]{0,80}\]{0,2}")
# A trailing, cut-off attempt: a "[[" opener with no close before the end, or a
# single-bracket echo of a known token name ("[PIC", "[REACT") running to the end.
_CONTROL_TAIL_RE = re.compile(r"\[\[[^\n]*$|\[(?:PIC|REACT(?:_ONLY)?)\b[^\n]*$", re.IGNORECASE)


def _strip_control_tags(text: str) -> str:
    """Every trace of a [[...]] control token gone, whole or broken, and the spaces it leaves behind tidied up. The one thing that must never happen is one of these being sent as words."""
    if not text or "[" not in text:
        return text
    out = _CONTROL_TAG_RE.sub("", text)
    out = _CONTROL_TAIL_RE.sub("", out)
    # Tidy what removing it left behind: a double space mid-line, a blank line
    # from a tag that was on its own, and leading or trailing space.
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# Kept as the name the picture code and its tests use; it is the general guard now.
_strip_pic_tags = _strip_control_tags


def _pick_pic_choice(text: str, count: int):
    """The picture the model chose, from a [[PIC:N|N2]] tag anywhere in the reply (the last one wins, since that is where it is asked for). Returns (first, second) indices in range, each or both None. Tolerant of a malformed tag so a broken one still both picks and gets stripped."""
    first = second = None
    matches = list(re.finditer(r"\[\[?\s*PIC\s*:?\s*(\d+)\s*(?:\|\s*(\d+))?", text, re.IGNORECASE))
    if matches:
        m = matches[-1]
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) is not None else None
        if 0 <= a < count:
            first = a
        if b is not None and 0 <= b < count:
            second = b
    return first, second


# What the Chats composer may attach to one message. Discord itself takes 25MB
# on a free account, but these arrive base64'd through the IPC file, so they are
# kept small enough that writing one is instant.
_MAX_FILES = 4
_MAX_FILE_BYTES = 8 * 1024 * 1024
_ALLOWED_UPLOAD = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "mov", "webm", "pdf", "txt"}


def _decode_files(raw):
    """Attachments from the panel, as [(filename, bytes)]. Returns (files, reason): reason is set, and files empty, when something is wrong with them."""
    import base64
    if not raw:
        return [], ""
    if not isinstance(raw, list):
        return [], "the attachments were not a list"
    if len(raw) > _MAX_FILES:
        return [], f"up to {_MAX_FILES} files in one message"
    out = []
    for item in raw:
        if not isinstance(item, dict):
            return [], "an attachment was not readable"
        name = os.path.basename(str(item.get("name") or "picture.png")).strip() or "picture.png"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in _ALLOWED_UPLOAD:
            return [], f"{name}: that kind of file cannot be sent from here"
        try:
            data = base64.b64decode(str(item.get("data") or ""), validate=True)
        except Exception:
            return [], f"{name}: the file could not be read"
        if not data:
            return [], f"{name}: the file was empty"
        if len(data) > _MAX_FILE_BYTES:
            return [], f"{name}: bigger than {_MAX_FILE_BYTES // (1024 * 1024)}MB"
        out.append((name, data))
    return out, ""


def _as_discord_files(files):
    """[(name, bytes)] as discord.File objects, each over its own buffer."""
    import io
    return [discord.File(io.BytesIO(data), filename=name) for name, data in files]


def _my_pictures() -> str:
    """This account's persona's pictures folder (app/utils/personas.py); the database calls default to the same
    persona."""
    from app.utils import personas as _personas
    return str(_personas.pictures_dir(_personas.current() or _personas.DEFAULT))


def _get_random_picture(video: bool = False) -> list | None:
    """Returns list of (type, path, description) tuples from this persona's pictures - only files with a stored description. `video`: its videos (MP4, app/utils/videos.py) instead."""
    folder_path = _my_pictures()
    if not os.path.exists(folder_path):
        return None
    exts = {".mp4"} if video else {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    descriptions = get_all_picture_descriptions()
    files = [
        ("file", os.path.join(folder_path, f), descriptions[f])
        for f in os.listdir(folder_path)
        if os.path.splitext(f)[1].lower() in exts and descriptions.get(f)
    ]
    return files if files else None


# asyncio only holds a weak reference to a running task, so a fire-and-forget create_task() can be collected before it finishes; keeping them here until they are done is the documented way to stop that
_memory_tasks: set = set()


def _spawn_memory_update(author, prompt, response):
    """Run the post-reply memory work without blocking the reply."""
    task = asyncio.create_task(_update_memory_after_reply(author, prompt, response))
    _memory_tasks.add(task)
    task.add_done_callback(_memory_tasks.discard)


async def _update_memory_after_reply(author, prompt, response):
    """Deletion detection and fact extraction, off the reply's critical path. Extraction runs on EVERY reply, same as the Snapchat engine path; the old "every 4th message" cadence silently dropped one-off facts ("my name is X") from short conversations. The extractor dedupes against stored facts and returns {} when there is nothing new, so the cost is one small-model call per reply, it just no longer happens where the user can feel it."""
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
    # Every model call made while writing this reply is tagged with whose
    # conversation it is for, so the panel can show which model is working on
    # the conversation you are looking at rather than whichever answered last
    # anywhere. A task has its own context, so this does not leak between replies.
    try:
        from app.utils import usage as _usage
        _usage.CONV.set(str(uid))
    except Exception:
        pass
    # Cancelled from the Chats tab while it was waiting or being written: stop
    # here, before anything is sent. Manual replies (bypass_cooldown) are the
    # user asking for it now, so they ignore a stale cancel.
    if not bypass_cooldown and uid in getattr(bot, "cancelled_replies", ()):
        bot.cancelled_replies.discard(uid)
        set_reply_state(uid, "skipped", reason="you cancelled the reply")
        return None
    # No model can reply right now (the one set up will not load): it is not asked again for every message waiting,
    # each failing the same way and each logged again. The messages stay on the waiting list; said once.
    _why_not = ai_module.unavailable_now()
    if _why_not:
        if ai_module.say_once(f"waiting {_why_not}"):
            log_system(f"Not replying for now: {_why_not}. Messages wait until a model can reply.")
        set_reply_state(uid, "failed", reason=_why_not)
        return None
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

    # The persona's text read for every reply (a stat when it has not changed): written in the panel, from Telegram
    # or by a command, every account on that persona speaks with the new one from its next reply.
    enriched_instructions = load_instructions() + mood_block + memory_block + profile_block

    # in a server the history is the whole channel, several people talking, and each of their turns is prefixed with who said it; the model has to be told that, or it reads the names as part of what was said and starts prefixing its own replies the same way
    if in_server(message.channel):
        _others = ", ".join(_recent_speakers(message)) or "a few people"
        enriched_instructions += (
            "\n\n[This is a group channel, not a private chat. Lines in the "
            "conversation are written as 'Name: what they said', because several "
            "people are talking. Read them as different people and keep track of "
            "who said what. Recently talking here: " + _others + ". "
            f"You are replying to {speaker_label(message)}. "
            "Write ONLY your reply, with no name prefix of your own, exactly as "
            "you would type it into the channel.]")

    # per-user persona override: inject a custom tone/personality for this user. it lives in user_memory under __persona__, so the get_memory() above has already fetched it (get_persona() would open a second sqlite connection for a value sitting in `memory`); format_memory_for_prompt() filters __-prefixed keys, so it never leaks into the memory block
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

    # detect the user's language, cached per user, re-checked every 5 messages so drift is caught without a Groq call per message
    _default_lang = config["bot"].get("default_language", "en")
    _lang_entry = bot._lang_cache.get(uid, {"tag": _default_lang, "count": 0})
    _lang_entry["count"] += 1
    # only (re)detect with enough text, short messages ("ok", "tg", "lol") are ambiguous and caused wrong-language replies
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

    from app.utils.languages import language_name
    _lang_display = language_name(_lang_tag)
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
    # A video when one is asked for and there is one (app/utils/pictures.py); a photo when a photo is.
    _wants_video = pics_cfg.get("enabled", True) and is_video_request(prompt)
    _available_pics = _get_random_picture(video=True) if _wants_video else None
    if not _wants_video and pics_cfg.get("enabled", True) and is_picture_request(prompt):
        _available_pics = _get_random_picture()
    _chosen_pic_idx = None
    _chosen_pic_idx2 = None
    if _available_pics:
        _pic_list_str = "\n".join(f"{i}: {desc}" for i, (_t, _p, desc) in enumerate(_available_pics))
        _what = "video" if _wants_video else "photo"
        enriched_instructions += (
            f"\n\n[IMPORTANT: You ARE sending the user a {_what} of yourself RIGHT NOW in this very reply. "
            f"The {'video' if _wants_video else 'image'} is already attached and being sent. "
            f"NEVER say 'maybe later', 'not right now', 'later', 'next time', 'maybe another time', or anything that implies you are NOT sending a {_what} - you already are. "
            f"Do NOT describe or caption the {_what}. "
            f"Just react casually like a real person who just hit send on {'a quick video of themselves' if _wants_video else 'a selfie'}, short, natural, confident.\n"
            f"Here are the {_what}s you could be sending, pick whichever best fits what was asked for "
            "(e.g. if they asked for a specific pose, outfit, or setting, match that):\n"
            f"{_pic_list_str}\n"
            "End your reply on its own new line with exactly: [[PIC:N|N2]] where N is your first-choice "
            f"{_what} number and N2 is your second-best choice (a different number), used as a fallback only "
            f"if your first choice turns out to be the same {_what} that was just sent last time. If there's "
            f"only one {_what} available, use the same number for both. If none fit better than any other, "
            "just pick 0|1 (or 0|0 if only one exists). This tag will be removed before the user sees your "
            "message - never mention it or the numbering in your visible reply.]"
        )

    late_opener = ""
    if _LATE_CFG.get("enabled", True) and wait_time >= _LATE_CFG.get("threshold", 300):
        # written openers for the language actually being spoken, if any exist. where there are none, which is every language nobody has written a list for, the model is asked for the same thing in its own words rather than being handed an English line to use in Portuguese
        _written = late_openers_for(_lang_tag)
        if _written:
            late_opener = random.choice(_written)
            enriched_instructions += (
                f"\n\n[LATE REPLY: You took a while to respond. Open your reply "
                f"naturally with something like: \"{late_opener.strip()}\", weave it in as "
                f"the very first words of your message, then continue normally. Do NOT "
                f"add 'sorry' again later in the message and do NOT start with a comma or dash.]"
            )
        else:
            _style = (_LATE_CFG.get("style") or
                      "casual and offhand, the way someone who was just busy would put it, "
                      "never formal and never an apology paragraph")
            enriched_instructions += (
                f"\n\n[LATE REPLY: You took a while to respond. Open with a brief, "
                f"natural acknowledgement of that in {_lang_display} - {_style}. A few words "
                f"at most, woven into the very start of your message, then continue normally. "
                f"Do NOT apologise twice and do NOT start with a comma or dash.]"
            )
            late_opener = "auto"

    if len(history) > 20:
        try:
            summarized = await summarize_history(history, enriched_instructions)
            if summarized:
                history = summarized
                key = history_key(message)
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

    # simulate the bot "reading" the message before it starts typing; DMs get a longer read delay (read receipts are visible there), and bypass_typing (fast-path replies) scales the same range down to ~40%
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

    # humans open the chat before typing, DMs show a read receipt, so ack the message now (before the typing indicator) like a real person would
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
                # never send a refusal and never go silent: replace it with a short confused reaction, which is what a real person sends when the conversation takes a weird turn
                log_error("AI Refusal", "Model refused, sending a short reaction instead")
                response = random.choice(refusal_fallbacks())
                break

            if response:
                # memory upkeep is two more sequential Groq round trips, and neither of them changes the reply that has just been generated; awaiting them here put 1-6 seconds between the reply existing and the user seeing it, so they run alongside the send instead. the trade is that a fact learned this turn may not be in the cache yet if the same person fires another message within a second or two
                _spawn_memory_update(message.author, prompt, response)

                if late_opener:
                    # Opener is injected via system instruction above, no prepend.
                    log_system(f"Late reply opener injected for {message.author.name}")

                break

        except Exception as e:
            error_msg = str(e)
            # One that will not load fails the same way however often it is asked: it has been said (app/utils/ai.py),
            # and asking twice more for this message only logged it twice more.
            if isinstance(e, ai_module.ModelWontLoad):
                set_reply_state(uid, "failed", reason=error_msg)
                return None
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
            # Too big for the model even after trimming the conversation: the
            # same request would fail the same way, so it is said once, plainly,
            # rather than logged as three raw 400s.
            if isinstance(e, ai_module.RequestTooLarge) or ai_module.is_request_too_large(e):
                log_error("AI Error", ai_module.explain_too_large(e))
                notify_telegram_error("AI Error", ai_module.explain_too_large(e))
                return None
            log_error("AI Error", error_msg)
            if attempt == max_retries - 1:
                notify_telegram_error("AI Error", error_msg)
                return None
            await asyncio.sleep(2)

    if not response:
        if not _was_rate_limited:
            # The long 120s wait only makes sense after an actual rate limit.
            log_error("AI Error", "The model returned an empty reply, nothing to send.")
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
        # if the last-ditch retry is still a refusal, answer with a short reaction rather than silence or the refusal itself
        if response and is_refusal(response):
            log_error("AI Refusal", "Final retry still a refusal, sending a short reaction instead")
            response = random.choice(refusal_fallbacks())

    if not response:
        return None

    response = strip_meta(response).replace("\u2014", "").replace("\u2013", "")

    # reaction handling: the model may end a reply with [[REACT:emoji]] (react + reply) or send only [[REACT_ONLY:emoji]] (react, no text); emoji are allowlisted in behavior.py, and react-only stays a rare human thing, capped and never used when it would leave a question unanswered (the prompt says so)
    _react_emoji, _react_only = None, False
    _react_cfg = config["bot"].get("reactions") or {}
    if _react_cfg.get("enabled", True):
        response, _react_emoji, _react_only = parse_reaction_tag(
            response, reaction_emojis(_react_cfg))
        # the tag is stripped whatever happens; whether it is acted on is a separate question, and telling a model to react "only when a human would" gets a reaction on nearly every reply, because from inside one reply there is always some reason to. this is the actual rate control. gated only when there is text to send: a reaction is the entire reply in the react-only case, and dropping it there would answer with silence, which is worse than reacting too often
        if _react_emoji and response.strip():
            if random.random() >= float(_react_cfg.get("chance", 0.3) or 0):
                _react_emoji = None
        # never react-only when a voice or photo was asked for, those need an actual reply
        if _react_emoji and _react_only and not response and not is_tts_request(prompt) and not _available_pics:
            bot._reply_total = getattr(bot, "_reply_total", 0) + 1
            ratio_cap = _react_cfg.get("react_only_max_ratio", 0.1)
            within_cap = getattr(bot, "_react_only_count", 0) / max(1, bot._reply_total) <= ratio_cap
            if within_cap:
                bot._react_only_count = getattr(bot, "_react_only_count", 0) + 1
            # react-only reply: acknowledge, send nothing. if the cap was hit we still react, silence would be worse than over-reacting
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
        _c1, _c2 = _pick_pic_choice(response, len(_available_pics))
        if _c1 is not None:
            _chosen_pic_idx = _c1
            _log_msg = f"[PIC] AI chose #{_c1}: {_available_pics[_c1][2][:60]}"
            if _c2 is not None:
                _chosen_pic_idx2 = _c2
                _log_msg += f" (2nd choice #{_c2}: {_available_pics[_c2][2][:40]})"
            log_system(_log_msg)
        else:
            if _c2 is not None:
                _chosen_pic_idx2 = _c2
            log_system(f"[PIC] No usable [[PIC:N|N2]] tag, falling back to random. Raw tail: {response[-80:]!r}")
    # Always strip the tag from what gets sent, whether or not pictures were offered
    # this turn and however malformed it is: the token must never reach the person.
    response = _strip_pic_tags(response)

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
                # the bot's own reply going out, like text: a message of yours during it would otherwise look like you answering them yourself
                set_reply_state(message.author.id, "sending")
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

    # style-aware chunking: humans send short messages, not paragraphs, so split long replies at sentence boundaries and cap chunk size and follow-up count per verbosity mode; overflow merges into the last message so nothing is dropped
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

    # global cooldown: human gap between replies so different conversations never land seconds apart; skipped with bypass_cooldown or when disabled
    if not bypass_cooldown and GLOBAL_COOLDOWN_ENABLED:
        _time_since_last = time.time() - bot.last_global_send
        _global_cooldown_gap = random.uniform(GLOBAL_COOLDOWN_MIN, GLOBAL_COOLDOWN_MAX)
        # With several people waiting, the gap comes down towards the minimum
        # rather than every one of them paying the full pause: a full gap each
        # meant the fourth person waited the better part of ten minutes. Someone
        # working through a backlog of messages does answer them in a burst, so
        # this reads more human than the flat pause did, not less.
        _waiting_now = _people_waiting()
        if _waiting_now > 1:
            _crowd = min(1.0, (_waiting_now - 1) / 3.0)
            _global_cooldown_gap = (_global_cooldown_gap * (1 - _crowd)
                                    + GLOBAL_COOLDOWN_MIN * 0.5 * _crowd)
        if _time_since_last < _global_cooldown_gap:
            set_reply_state(message.author.id, "cooldown",
                            eta=time.time() + (_global_cooldown_gap - _time_since_last))
            await asyncio.sleep(_global_cooldown_gap - _time_since_last)

    if not bypass_cooldown and message.author.id in bot.cancelled_replies:
        bot.cancelled_replies.discard(message.author.id)
        set_reply_state(message.author.id, "skipped", reason="you cancelled the reply")
        log_system(f"Reply to {message.author.name} cancelled from the panel, not sent")
        return None

    # Waiting its turn behind any other reply being sent, then sending.
    set_reply_state(message.author.id, "queued" if bot.global_send_lock.locked() else "sending")

    # small pre-lock jitter: prevents perfectly serialized sends from looking mechanical when multiple users are active at the same time
    await asyncio.sleep(random.uniform(0.1, 1.2))
    async with bot.global_send_lock:
        # waited its turn behind other replies; you may have answered them yourself meanwhile
        if not bypass_cooldown and message.author.id in bot.cancelled_replies:
            bot.cancelled_replies.discard(message.author.id)
            set_reply_state(message.author.id, "skipped", reason="you answered them yourself")
            return None
        set_reply_state(message.author.id, "sending")
        pics_cfg = config["bot"].get("pictures") or {}
        if _available_pics and pics_cfg.get("enabled", True):
            all_pics = _available_pics
            uid = message.author.id
            last_sent = bot.last_sent_picture.get(uid)
            # only exclude the single most-recently-sent picture (no consecutive repeats); falls back to the full list if there's only one picture
            available = [p for p in all_pics if p[1] != last_sent] or all_pics
            # try the AI's first choice, then its second choice, before falling back to a true random pick (only if both choices are unusable)
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
            from app.utils import looks as _looks
            _pic_sent = pic_value
            try:
                if bot.realistic_typing:
                    await asyncio.sleep(random.uniform(1, 3))
                if pic_type == "file":
                    # What the AI puts on it as it goes (a caption, the time, an emoji...), on the accounts allowed to
                    # (bot.pictures.touches); otherwise the picture as it is.
                    _pic_sent = await _looks.touched_copy(
                        pic_value, _pic_desc,
                        [f"{'them' if t.get('role') == 'user' else 'me'}: {t.get('content')}"
                         for t in (history or [])[-6:] if t.get("content")] + [f"them: {prompt}"],
                        response, f"discord_{ACCOUNT_INDEX}", _lang_tag,
                        their_name=getattr(message.author, "display_name", "") or message.author.name,
                        platform="Discord", keep_name=True)
                # same reply fallback as the text path: a channel that rejects a reply payload can still receive the picture perfectly well
                _pic_kwargs = {"file": discord.File(_pic_sent)} if pic_type == "file"                     else {"content": pic_value}
                await _send_here(message, _pic_kwargs)
            except Exception as _pe:
                _pd = _detail(_pe)
                log_error("Picture Send", str(_pe) + (f" | {_pd}" if _pd else ""))
            finally:
                _looks.drop_copy(pic_value, _pic_sent)

        channel_name, guild_name = get_channel_context(message)
        # Whether anything actually reached Discord, as opposed to being generated.
        _delivered = False
        for i, chunk in enumerate(chunks):
            if getattr(bot, "disable_mentions", DISABLE_MENTIONS):
                chunk = chunk.replace("@", "@\u200b")

            if bot.anti_age_ban:
                # only obfuscate numbers that appear in an age context, e.g. "I'm 12", not innocent content like "Chapter 5" or "3 cats"
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

            # Last line of defence, per chunk: neither a refusal nor a picture tag
            # ever leaves this process, whatever happened upstream. Looked at
            # before a typo goes in: "I'm srry, but I can't help with that." went
            # out once the typo had hidden the wording from it.
            chunk = _strip_pic_tags(chunk)
            if is_refusal(chunk):
                chunk = random.choice(refusal_fallbacks())
            chunk = add_typo(chunk, config["bot"]["typo_chance"])
            if not chunk.strip():
                continue
            if i == 0:
                log_incoming(message.author.name, channel_name, guild_name, prompt)
            log_response(message.author.name, chunk)
            separator()

            try:
                # react before replying when the model called for one, humans often drop the emoji first, then start typing
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
                        # short think before typing; follow-up chunks come 2-8s later (humans split a thought and hit send, they don't wander off for 15 seconds mid-message)
                        pre_delay = think_delay()
                        await asyncio.sleep(pre_delay)
                        await _simulate_typing(message.channel, chunk, fast=False)
                else:
                    if i > 0:
                        await asyncio.sleep(random.uniform(2, 8) if not bypass_typing else random.uniform(1.0, 2.5))

                async def _send_chunk(chunk=chunk):
                    if isinstance(message.channel, discord.DMChannel):
                        return await message.channel.send(chunk)
                    if message.channel.id in _no_reply_channels:
                        # this channel has already rejected a reply once, so don't spend another failed request finding that out again
                        return await message.channel.send(chunk)
                    try:
                        return await message.reply(
                            chunk, mention_author=config["bot"]["reply_ping"])
                    except discord.HTTPException as _re:
                        # 50035 is Discord rejecting the shape of the request, not the text; it happens on replies in some channels, group DMs among them, and the message itself is perfectly sendable, so send it plainly rather than dropping the reply entirely
                        if _re.code != 50035:
                            raise
                        _no_reply_channels.add(message.channel.id)
                        log_system(
                            "Replies are not accepted in this chat, "
                            f"sending without one from now on ({_detail(_re)})")
                        return await message.channel.send(chunk)

                sent_msg = await _send_retrying(_send_chunk, message.author.name)
                bot.last_global_send = time.time()
                _delivered = True
                emit_chat_meta()

                # Rare human behaviour: fix a small slip right after sending.
                if random.random() < config["bot"].get("edit_after_send_chance", 0.015):
                    asyncio.create_task(_maybe_edit_after_send(sent_msg, chunk))

            except discord.Forbidden:
                # 403 on a send means the door is shut: blocked, DMs closed, or no longer friends; that never clears by itself, so the conversation comes off the waiting list instead of being retried on every sweep for ever
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

    # the caller treats a returned string as "this was sent", and the panel reports it as a successful reply; returning the text after every send failed said the message had gone out when nothing had left the process, so the conversation stayed unanswered while the panel said otherwise
    if not _delivered:
        return None
    return response


async def _send_retrying(send, who: str = ""):
    """A send Discord turned away for a moment, tried again twice, a few seconds apart.

    A 503 ("upstream connect error or disconnect/reset before headers") is
    Discord's front door not reaching the service behind it: the message never
    got in, so sending it again cannot post it twice. discord.py retries a 500,
    502 and 504 by itself, not a 503, and the reply was simply lost.
    """
    for attempt in range(3):
        try:
            return await send()
        except discord.DiscordServerError as e:
            if getattr(e, "status", 0) != 503 or attempt == 2:
                raise
            log_system(f"Discord was briefly unavailable (503){f' sending to {who}' if who else ''}; trying again in a moment")
            await asyncio.sleep(2.5 + attempt * 4 + random.random() * 2)


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

        # previously-removed friends get a shorter delay, but never instant (0s accept = bot pattern)
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

        # per-user jitter so rapid incoming requests don't all fire at the exact same second (a bot-detection red flag)
        jitter = random.randint(0, 120)
        final_delay = delay + jitter

        async def _accept(u, d):
            try:
                if d > 0:
                    await asyncio.sleep(d)
                async with build_session(bot._connection.http.token) as session:
                    resp = await accept_friend_request(session, u.id)
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


# who we have already recorded recently, so a busy channel is not a database write per message
_profile_seen: dict = {}
_PROFILE_REFRESH = 3600.0

async def _send_here(message, kwargs: dict):
    """Send into this message's channel, replying to it where that is allowed. Discord rejects a reply payload in some channels with 50035, group DMs among them; the message itself is fine, so the reply is dropped rather than the message, and the channel is remembered so the next one goes straight out."""
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


# channels where Discord refuses a reply payload; learned the first time it happens, so the bot sends plainly there instead of failing every message
_no_reply_channels: set = set()


def _detail(exc) -> str:
    """The part of a Discord error that says what was actually wrong. str(HTTPException) is "400 Bad Request (error code: 50035): Invalid Form Body", which names the category and nothing else; the body carries the field that failed, and without it a 50035 is unfixable guesswork."""
    try:
        text = getattr(exc, "text", "") or ""
        errors = getattr(exc, "errors", None)
        if errors:
            import json as _json
            return _json.dumps(errors)[:400]
        return " ".join(text.split())[:400]
    except Exception:
        return ""


# people who have blocked the account or closed their DMs, noticed on a 403; recorded so the panel can say why a reply was abandoned rather than just reporting a failure that looks retryable
_blocked_users: set = set()

# when each pending friend request is due to be accepted, as a unix timestamp; the accepts are deliberately spread over hours so the account does not look scripted, which is right but opaque, so the panel reads this to say exactly when each one is coming, and to offer taking it now instead
_friend_due: dict = {}


def _cache_author(user) -> None:
    """Record a name, handle and avatar for the panel's profile card. Everything here is already on the message object, so there is no API call and no cost beyond an occasional row update; avatars are asked for at 128px because that is roughly twice the size the card draws them, which keeps them crisp on a high density screen."""
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
async def on_raw_message_delete(payload):
    """A message deleted on Discord: kept in the chat log, and marked, so the Chats tab shows it with a bin."""
    if payload.guild_id is not None:
        return
    try:
        uid = _chatlog.mark_deleted(ACCOUNT_INDEX, payload.message_id)
        if uid:
            emit_chat_event({"t": "deleted", "uid": str(uid), "mid": str(payload.message_id), "at": time.time()})
    except Exception:
        pass


@bot.event
async def on_raw_message_edit(payload):
    """A DM message edited: the new words, in the log and in an open chat view."""
    if payload.guild_id is not None:
        return
    data = getattr(payload, "data", None) or {}
    if "content" not in data:
        return          # an embed filled in, not an edit
    try:
        uid = _chatlog.mark_edited(ACCOUNT_INDEX, payload.message_id, {"text": (data.get("content") or "")[:2000]})
        if uid:
            emit_chat_event({"t": "edited", "uid": str(uid), "mid": str(payload.message_id),
                             "text": (data.get("content") or "")[:2000], "at": time.time()})
    except Exception:
        pass


async def _reaction_changed(payload, delta: int):
    """A reaction on a DM message, added (1) or taken back (-1), by them, by the account from the Chats tab, or by
    the account from Discord itself: the kept message's reactions follow, and an open chat view with them."""
    if payload.guild_id is not None:
        return
    try:
        me = getattr(bot, "selfbot_id", None) or bot.user.id
        uid, reactions = _chatlog.bump_reaction(ACCOUNT_INDEX, payload.message_id, _reaction_emoji(payload.emoji),
                                                delta, payload.user_id == me)
        if uid:
            emit_chat_event({"t": "reactions", "uid": str(uid), "mid": str(payload.message_id), "reactions": reactions})
    except Exception:
        pass


@bot.event
async def on_raw_reaction_add(payload):
    await _reaction_changed(payload, 1)


@bot.event
async def on_raw_reaction_remove(payload):
    await _reaction_changed(payload, -1)


@bot.event
async def on_typing(channel, user, when):
    """Someone typing to this account: the Chats tab and Big Picture show their dots, as they show the bot's."""
    try:
        if user is None or user.id == getattr(bot, "selfbot_id", None):
            return
        if isinstance(channel, discord.DMChannel):
            emit_chat_event({"t": "typing", "uid": str(user.id), "at": time.time()})
        elif in_server(channel) and channel.id in getattr(bot, "server_waiting", {}):
            emit_chat_event({"t": "typing", "uid": f"ch{channel.id}", "who": getattr(user, "display_name", None) or user.name,
                             "at": time.time()})
    except Exception:
        pass


@bot.event
async def on_message(message):
    _log_dm(message)
    if message.author.id == bot.selfbot_id:
        if isinstance(message.channel, discord.DMChannel):
            _rcp = getattr(message.channel, "recipient", None)
            if _rcp is not None:
                try:
                    emit_chat_event({"t": "sent", "uid": str(_rcp.id), "ts": message.created_at.timestamp(),
                                     **_message_payload(message)})
                except Exception:
                    pass
                _st = bot.reply_state.get(_rcp.id)
                if _st and _st.get("state") in _PENDING_STATES:
                    # you wrote to them yourself while the bot had a reply lined up: yours is the answer, so the bot's is dropped rather than sent after it
                    if cancel_pending_reply(_rcp.id):
                        log_system(f"You answered {_rcp.name} yourself, so the bot's reply was dropped")
                    clear_reply_state(_rcp.id)
                elif not _st or _st.get("state") in ("skipped", "failed", "sending"):
                    clear_reply_state(_rcp.id)
                try:
                    mark_responded(_rcp.id, message.channel.id)
                except Exception:
                    pass
        elif in_server(message.channel):
            _w = bot.server_waiting.get(message.channel.id)
            _ref = getattr(getattr(message, "reference", None), "message_id", None)
            _pending = any(k.endswith(f"-{message.channel.id}") for k in bot.user_message_batches)
            # the answer to it (a reply to that message), or with nothing else lined up in the channel
            if _w is not None and (_ref == _w.id or not _pending):
                bot.server_waiting.pop(message.channel.id, None)
                emit_chat_event({"t": "done", "uid": f"ch{message.channel.id}"})
        if message.content.startswith(PREFIX):
            await bot.process_commands(message)
        return

    # remember who this is, for the profile card in the panel; every value is already on the message object, so it costs nothing, and it belongs here rather than on the reply path: the bot sees far more people than it answers, and the ones it ignores are exactly the ones you want to look up
    _cache_author(message.author)
    # and hold the User itself, so looking them up later never has to ask Discord, which this account is not always allowed to do. see resolve_user()
    remember_user(message.author)

    # They can message again, so whatever closed the channel has been undone.
    if message.author.id in _blocked_users:
        _blocked_users.discard(message.author.id)
        try:
            from app.utils.db import remove_blocked
            remove_blocked(message.author.id)
        except Exception:
            pass

    # owner priority trigger: owner's own message starting with PRIORITY_PREFIX; must stay outside the selfbot guard, it fires on messages FROM the owner
    if message.author.id == OWNER_ID and message.content.startswith(PRIORITY_PREFIX):
        hint = message.content[len(PRIORITY_PREFIX):].lstrip()
        emit_use("bot.priority_prefix", PRIORITY_PREFIX)
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
        key = history_key(target_msg)

        await seed_history(key, target_msg)
        if key not in bot.message_history:
            bot.message_history[key] = []

        combined = hint if hint else target_msg.content

        # append `combined` (not the raw target message); when a hint is supplied, generate_response() drives off history, so the hint must live in history or it gets silently dropped
        bot.message_history[key].append(
            {"role": "user", "content": as_turn(target_msg, combined)})
        if len(bot.message_history[key]) > MAX_HISTORY * 2:
            bot.message_history[key] = bot.message_history[key][-(MAX_HISTORY * 2):]

        history = bot.message_history[key]
        log_system(f"Priority trigger by owner → responding to {target_msg.author.name} in #{getattr(target_msg.channel, 'name', 'DM')}")
        response = await generate_response_and_reply(target_msg, combined, history, wait_time=0)
        if response:
            bot.message_history[key].append({"role": "assistant", "content": response})
        return

    if (isinstance(message.channel, discord.DMChannel) and not message.author.bot
            and message.type in (discord.MessageType.default, discord.MessageType.reply)):
        bot.cancelled_replies.discard(message.author.id)
        try:
            _a = message.author
            _txt = _preview_text(message)
            emit_chat_event({
                "t": "msg", "uid": str(_a.id),
                "name": _a.name,
                "username": _a.name,
                "avatar": str(_a.display_avatar.url) if getattr(_a, "display_avatar", None) else "",
                "ts": message.created_at.timestamp(),
                "snippet": (_txt[:60] + "\u2026") if len(_txt) > 60 else _txt,
                "ignored": _a.id in bot.ignore_users,
                **_message_payload(message),
            })
        except Exception:
            pass

    if should_ignore_message(message):
        return

    # A sticker-only message used to be dropped, so a sticker never got a reply.
    # It carries meaning - a wave, a laugh - so it is answered like any other
    # message: its picture goes to the vision model (see _extract_image...),
    # and its name stands in for the empty text so the model has something to
    # read even for a Lottie sticker that has no picture.
    if message.stickers and not (message.content or "").strip():
        _sn = _sticker_names(message)
        if _sn:
            try:
                message.content = _sn
            except Exception:
                pass

    _is_dm = isinstance(message.channel, discord.DMChannel)
    if _is_dm:
        bot.waiting_msgs[message.author.id] = message

    if message.author.id in bot.paused_users:
        if _is_dm:
            set_reply_state(message.author.id, "skipped", reason="you paused replies to them")
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
            if _is_dm:
                set_reply_state(user_id, "skipped", reason="left unanswered on purpose (the ignore chance)")
            return

        if user_id in bot.user_cooldowns:
            cooldown_end = bot.user_cooldowns[user_id]
            if current_time < cooldown_end:
                if _is_dm:
                    set_reply_state(user_id, "skipped", eta=cooldown_end,
                                    reason="they sent a burst of messages, cooling down")
                return
            else:
                del bot.user_cooldowns[user_id]

        if user_id not in bot.user_message_counts:
            bot.user_message_counts[user_id] = []

        bot.user_message_counts[user_id] = [t for t in bot.user_message_counts[user_id] if current_time - t < SPAM_TIME_WINDOW]
        bot.user_message_counts[user_id].append(current_time)

        if len(bot.user_message_counts[user_id]) > SPAM_MESSAGE_THRESHOLD:
            bot.user_cooldowns[user_id] = current_time + COOLDOWN_DURATION
            if _is_dm:
                set_reply_state(user_id, "skipped", eta=current_time + COOLDOWN_DURATION,
                                reason="they sent a burst of messages, cooling down")
            return

        if batch_key not in bot.message_queues:
            bot.message_queues[batch_key] = deque()
            bot.processing_locks[batch_key] = Lock()

        bot.message_queues[batch_key].append(message)
        if is_server_channel:
            bot.server_waiting[channel_id] = message
            try:
                emit_chat_event({"t": "msg", "uid": f"ch{channel_id}", **server_row(message)})
            except Exception:
                pass
        # Track DM messages for the nudge system, will be cleared once we reply
        if isinstance(message.channel, discord.DMChannel):
            nudge_cfg = config["bot"].get("nudge") or {}
            if nudge_cfg.get("enabled", False):
                add_unresponded(user_id, channel_id, message.content, time.time())
        if not bot.processing_locks[batch_key].locked():
            asyncio.create_task(process_message_queue(batch_key))
    elif _is_dm:
        set_reply_state(user_id, "skipped",
                        reason="the account is paused" if bot.paused else "set not to reply in DMs")


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
                    # a leftover batch entry (from an earlier error) would otherwise skip the block below and leave the reply variables unbound
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
                    if priority:
                        emit_use("bot.priority_prefix", PRIORITY_PREFIX)
                    wait_time = 0 if priority else get_batch_wait_time(
                        server=in_server(message.channel))
                    bot.user_message_batches[batch_key]["reply_at"] = current_time + wait_time
                    set_reply_state(message.author.id, "waiting", eta=current_time + wait_time)
                    channel_name, guild_name = get_channel_context(message)
                    log_received(message.author.name, channel_name, guild_name, wait_time)
                    if not priority:
                        await asyncio.sleep(wait_time)

                    # keep collecting messages until the user stops sending; high variance mimics real human pause patterns
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
                    first_of_batch = unique_messages[0]
                    image_url = bot.user_message_batches[batch_key]["image_url"]
                    del bot.user_message_batches[batch_key]
                else:
                    combined_content = message.content
                    message_to_reply_to = message
                    first_of_batch = message
                    image_url = message.attachments[0].url if (message.attachments and not (message.flags.value & (1 << 13))) else _extract_image_url_from_message(message)
                    wait_time = 0

                key = history_key(message_to_reply_to)
                # After a restart: what was said before this, so the reply is not to this message alone.
                await seed_history(key, first_of_batch)
                if key not in bot.message_history:
                    bot.message_history[key] = []
                bot.message_history[key].append(
                    {"role": "user", "content": as_turn(message_to_reply_to, combined_content)})
                if len(bot.message_history[key]) > MAX_HISTORY * 2:
                    bot.message_history[key] = bot.message_history[key][-(MAX_HISTORY * 2):]
                history = bot.message_history[key]

                # stale reply guard (servers & group chats only): if the channel moved on significantly since the triggering message, skip the reply so the bot doesn't resurface a buried conversation
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

                set_reply_state(message_to_reply_to.author.id, "writing")
                response = await generate_response_and_reply(message_to_reply_to, combined_content, history, image_url, wait_time=(wait_time + message_age))
                if not response:
                    set_reply_state(message_to_reply_to.author.id, "failed",
                                    reason="no reply was generated, see the log")
                if response:
                    clear_reply_state(message_to_reply_to.author.id)
                    bot.message_history[key].append({"role": "assistant", "content": response})
                    record_user_message(message_to_reply_to.author.id, message_to_reply_to.author.name,
                                        account=ACCOUNT_INDEX)
                    # Clear the nudge tracking entry, we've replied
                    nudge_cfg = config["bot"].get("nudge") or {}
                    if nudge_cfg.get("enabled", False) and isinstance(message_to_reply_to.channel, discord.DMChannel):
                        mark_responded(message_to_reply_to.author.id, message_to_reply_to.channel.id)
        finally:
            if bot.message_queues.get(batch_key):
                # a message landed while we were finishing: on_message saw the lock held and skipped spawning, so it would sit unanswered until the next message arrived; pick it up here instead
                asyncio.create_task(process_message_queue(batch_key))
            else:
                # drop the per-conversation queue and lock once drained, so they don't accumulate one entry per user+channel for the session
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


# role entry point: the supervisor imports this module and calls run_discord_role(); the account index is pinned via DISCORD_ACCOUNT_INDEX before import, so ACCOUNT_TOKEN is already the right one


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
        # rejected at REST login (malformed/expired token), never reaches the gateway, so ConnectionClosed 4004 is not raised
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
    try:
        asyncio.run(_run_token(ACCOUNT_TOKEN["token"], ACCOUNT_INDEX),
                    loop_factory=_loop_factory())
    except OSError as exc:
        # WSAENOBUFS: select() on Windows cannot watch more than 512 sockets, and
        # every pass of the event loop fails once that is passed. Say so, instead
        # of a bare traceback out of selectors.py that names nothing.
        if getattr(exc, "winerror", None) == 10055:
            log_error("Sockets",
                      "This account ran out of sockets: Windows can watch 512 at once and something "
                      "opened more. It restarts by itself. If it keeps happening, lower the connection "
                      "pool (app/utils/usage.py, POOL_MAX) or use fewer API keys at once.")
        raise


def _loop_factory():
    """The event loop this process runs on. On Windows, the selector loop: everything Discord goes through curl_cffi, which needs loop.add_reader(), and Windows' default Proactor loop does not have one, so curl_cffi bridges the gap with a helper thread of its own (curl_cffi/_asyncio_selector.py) that polls the sockets and calls back into the loop. That bridge is where this process was dying: "BufferError: memoryview has 1 exported buffer" raised while the garbage collector cleared a buffer the native side was still writing into, then exit code 0xC0000005, an access violation, the crash trace running through _asyncio_selector.add_reader itself. The selector loop has add_reader natively, so curl_cffi takes the same direct path it takes on Linux and macOS and the helper thread never starts; what it cannot do on Windows is run subprocesses through asyncio, which nothing in this process does (ffmpeg and friends go through subprocess in a thread), and it caps out at 512 sockets. That cap is not theoretical: each AI client keeps its own connection pool, and with a pool per Groq key and per provider the count passed 512 under load, so every pass of the loop died with WinError 10055 and took the account with it. The pools are bounded in app/utils/usage.py (POOL_MAX) to keep the total well under it. None elsewhere: the default is right, and asyncio.run() treats None as "use it"."""
    # On a thread of the app (a phone), the loop is also handed to whatever
    # stops the account, so it can wake the loop to hear it.
    from app.core import inprocess
    if sys.platform == "win32":
        return inprocess.loop_factory(asyncio.SelectorEventLoop)
    return inprocess.loop_factory(None)


if __name__ == "__main__":
    # Direct execution is supported for debugging a single account.
    run_discord_role()
