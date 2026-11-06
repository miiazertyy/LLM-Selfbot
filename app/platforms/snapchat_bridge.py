"""Python side of the browser platforms' bridge, Snapchat's and TikTok's: Node runner <-> JSON IPC files <-> this bridge -> engine -> Groq. IPC files live in ipc/: snap_incoming (Node writes, we read), snap_responses (we write replies, Node sends), snap_outgoing (proactive sends like /reply), snap_processed (ids already handled), plus tg_commands_snap / tg_results_snap for the Telegram controller; TikTok's are the same with tiktok_ in place of snap_. Same AI brain, memory, mood, leaderboard and pictures as Discord.

Which platform a bridge serves is BRIDGE_PLATFORM, set by app/cli.py before this is imported (Snapchat when unset); everything that differs between them is in _PLATFORMS below."""

import asyncio
import json
import time
import os
import sys
import base64
import mimetypes
import random
import shutil
import atexit
import subprocess
import threading
import uuid as _uuid
from datetime import date, datetime, time as _dtime
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app.core.engine as engine
from app.platforms import registry as _registry
from app.core.engine import generate_ai_response, IncomingMessage
from app.utils.ai import init_ai, generate_response, transcribe_voice, ModelWontLoad
from app.utils.db import init_db
from app.utils import db as _db
from app.utils.memory import (
    init_memory,
    set_persona,
    clear_persona,
    get_persona,
)
import app.utils.mood as mood_mod
from app.utils.mood import mood_loop, shift_mood
from app.utils.humanize import humanize
from app.utils.helpers import resource_path, load_config
from app.utils.logger import log_system, log_error, log_incoming, log_response, separator, set_theme

# ── Which platform this bridge serves ─────────────────────────────────────────
# Snapchat and TikTok are both driven through a browser by a Node runner, and everything on this side of it, the
# replies, the panel's link, nudges, Telegram, is the same for both. What differs is here.
_PLATFORMS = {
    "snapchat": {
        "name": "Snapchat", "key": "snap", "env": "SNAP", "runner": "snapchat_runner.js",
        # Snapchat's own chats, never answered (the runner leaves them out of its passes too).
        "system_chats": {"my ai", "team snapchat"},
        # Its reactions, in the order its picker shows them: the only ones it has, one per person on a message.
        "reactions": ("❤️", "😂", "🔥", "👍", "👎", "😰", "🤯", "❓"),
        "photo": "📸 sent a snap", "calls": True,
    },
    "tiktok": {
        "name": "TikTok", "key": "tiktok", "env": "TIKTOK", "runner": "tiktok_runner.js",
        "system_chats": {"tiktok", "system notifications", "notifications système"},
        # TikTok's twelve, in the order its picker shows them (read off its own script, 2026-10).
        "reactions": ("❤️", "😂", "😡", "😭", "👍", "🤔", "🎉", "🤗", "😳", "😱", "🤪", "🙈"),
        "photo": "📸 sent a photo", "calls": False,
    },
    "instagram": {
        "name": "Instagram", "key": "insta", "env": "INSTAGRAM", "runner": "instagram_runner.js",
        # Instagram's own chats, and Meta AI, which sits in the inbox like a person: never answered.
        "system_chats": {"instagram", "meta ai", "instagram user"},
        # The six its picker offers at a glance; `any_reaction` because the picker's search takes any emoji.
        "reactions": ("❤️", "😂", "😮", "😢", "😡", "👍"),
        "any_reaction": True,
        "photo": "📷 sent a photo", "calls": True,
    },
    "x": {
        "name": "X", "key": "x", "env": "X", "runner": "x_runner.js",
        # X's own accounts, and Grok, which sits in the inbox like a person: never answered.
        "system_chats": {"x", "twitter", "x support", "grok"},
        # The seven its message picker opens with; `any_reaction` because that picker's search takes any emoji.
        "reactions": ("❤️", "😂", "😮", "😢", "🔥", "👍", "👎"),
        "any_reaction": True,
        "photo": "🖼️ sent a photo", "calls": False,
    },
    "reddit": {
        "name": "Reddit", "key": "reddit", "env": "REDDIT", "runner": "reddit_runner.js",
        # Reddit's own accounts, and the two bots that write to everybody: never answered.
        "system_chats": {"reddit", "reddit support", "redditcareresources", "automoderator", "u/reddit"},
        # Reddit chat takes any emoji there is; these are the ones its picker opens with.
        "reactions": ("❤️", "😂", "😮", "😢", "🔥", "👍", "👎"),
        "any_reaction": True,
        "photo": "🖼️ sent a photo", "calls": False,
    },
    # No browser at all: mindcraft-ce plays, and asks the brain this bridge serves what to say and do
    # (app/platforms/minecraft). The game has no system chats, reactions, photos or calls.
    "minecraft": {
        "name": "Minecraft", "key": "mc", "env": "MINECRAFT", "runner": "minecraft_runner.mjs",
        "system_chats": set(), "reactions": (), "photo": "", "calls": False,
    },
    # No browser at all, and no page: it speaks WhatsApp's own protocol over a WebSocket, the way the app on a
    # second device does (app/platforms/snapchat/whatsappbot.js, the baileys package). An account is a phone
    # number, linked once from the Accounts page; what that leaves behind is the login.
    "whatsapp": {
        "name": "WhatsApp", "key": "wa", "env": "WHATSAPP", "runner": "whatsapp_runner.js",
        # WhatsApp's own number, which writes about the account rather than to it.
        "system_chats": {"whatsapp", "0", "status"},
        # The six its picker opens with; it takes any emoji there is.
        "reactions": ("\U0001F44D", "\u2764\ufe0f", "\U0001F602", "\U0001F62E", "\U0001F622", "\U0001F64F"),
        "any_reaction": True,
        "photo": "\U0001F4F7 sent a photo", "calls": True,
    },
    # No browser either: a BlueBubbles Server on a Mac signed in to iMessage reads and sends for it
    # (app/platforms/snapchat/bluebubbles.js). Its reactions are iMessage's six tapbacks; a FaceTime call it cannot
    # take is answered with a text.
    "imessage": {
        "name": "iMessage", "key": "imsg", "env": "IMESSAGE", "runner": "imessage_runner.js",
        "system_chats": set(), "reactions": ("❤️", "👍", "👎", "😂", "‼️", "❓"),
        "photo": "📷 sent a photo", "calls": True,
    },
    # No runner at all: Telethon is Python, so the client lives on this bridge's own loop (_telegram_main). Not the
    # control bot (app/telegram_bot) - this is an account the persona chats from. Telegram takes any emoji as a
    # reaction; the few below are the ones its picker opens with.
    "telegram": {
        "name": "Telegram", "key": "tg", "env": "TELEGRAM", "runner": "",
        "system_chats": {"telegram"}, "reactions": ("👍", "👎", "❤️", "🔥", "🥰", "😁", "🤔", "😢"),
        "any_reaction": True, "photo": "📷 sent a photo", "calls": True,
    },
}
PLATFORM = os.getenv("BRIDGE_PLATFORM", "snapchat")
if PLATFORM not in _PLATFORMS:
    # Never another platform's bridge in its place: a Minecraft account that fell back to Snapchat's ran a second
    # copy of Snapchat account #1, under the first one's files.
    sys.stderr.write(f"This bridge does not serve {PLATFORM!r}.\n")
    sys.exit(2)
P = _PLATFORMS[PLATFORM]
PLATFORM_NAME = P["name"]
# The platforms that also go out in public (posts, likes, comments, what the people it talks to put up), as against
# Snapchat, which is only ever its inbox: what the out tab and the "going out" commands are for.
SOCIAL = PLATFORM in _registry.FEEDS
# Minecraft: no inbox to read, no browser, a brain of its own (_minecraft_main).
MINECRAFT = PLATFORM == "minecraft"
# iMessage: an inbox like Snapchat's, read through BlueBubbles on a Mac rather than a page: no browser, no npm packages.
IMESSAGE = PLATFORM == "imessage"
# WhatsApp: an inbox too, over WhatsApp's own protocol. No browser, but unlike iMessage it does have a package.
WHATSAPP = PLATFORM == "whatsapp"
# The ones with no browser to launch, so none of Chrome's checks apply to them. Not the same as "no packages":
# WhatsApp needs node_modules, iMessage needs nothing at all.
NO_BROWSER = IMESSAGE or WHATSAPP
# Telegram: the persona's own Telegram account, through Telethon, with no runner and no browser (app/platforms/
# telegram). The client runs here, so the queues below are its runner's half as well as the bridge's.
TELEGRAM = PLATFORM == "telegram"
# Its one error the glue below answers for: Telegram asking it to wait. Pure Python, no Telethon at import.
from app.platforms.telegram.client import Flood  # noqa: E402


# The ignore list and the leaderboard of this bridge's platform, under the names the code below has always used.
def get_ignored_users_snap():
    return _db.get_ignored_users_web(PLATFORM)


def add_ignored_user_snap(uid):
    _db.add_ignored_user_web(PLATFORM, uid)


def remove_ignored_user_snap(uid):
    _db.remove_ignored_user_web(PLATFORM, uid)


def get_leaderboard_snap(limit: int = 50, since=None):
    return _db.get_leaderboard_web(PLATFORM, limit, since)


# ── Message IPC files live in ipc/ (created on import) ────────────────────────
IPC_DIR = Path(resource_path("ipc"))
IPC_DIR.mkdir(parents=True, exist_ok=True)

# one bridge per account (SNAP_ACCOUNT_INDEX / TIKTOK_ACCOUNT_INDEX, 1-based); account 1 keeps the legacy files, 2+ get _N
ACCOUNT_INDEX = int(os.getenv(f"{P['env']}_ACCOUNT_INDEX", "1") or "1")
_SFX    = "" if ACCOUNT_INDEX == 1 else f"_{ACCOUNT_INDEX}"
_TG_SFX = P["key"] if ACCOUNT_INDEX == 1 else f"{P['key']}{ACCOUNT_INDEX}"

# iMessage with no Mac: the iPhone (or iPad) carries the messages itself, through a Shortcuts automation that posts
# each one to the panel (/relay/imessage/<token>) and sends back whatever comes back. The account's address says so
# ("phone" where a BlueBubbles server would be). Then there is no runner at all: a message from the phone goes into
# the same incoming queue a runner fills, the persona answers it the same way, and the answer goes back to the phone
# in the reply to its own request (_relay_cmd).
PHONE = IMESSAGE and os.getenv(f"IMESSAGE_SERVER_{ACCOUNT_INDEX}", "").strip().lower() == "phone"

INCOMING_FILE  = IPC_DIR / f"{P['key']}_incoming{_SFX}.json"
RESPONSES_FILE = IPC_DIR / f"{P['key']}_responses{_SFX}.json"
OUTGOING_FILE  = IPC_DIR / f"{P['key']}_outgoing{_SFX}.json"
PROCESSED_FILE = IPC_DIR / f"{P['key']}_processed{_SFX}.json"
# Messages the bot set out to answer and has not, for nudges: {chat id: {"content", "received_at", "nudged"}}, as the
# Discord side keeps them in its unresponded_messages table.
UNANSWERED_FILE = IPC_DIR / f"{P['key']}_unanswered{_SFX}.json"

# Telegram control IPC (kept in ipc/ alongside the other Snapchat IPC files)
CMD_FILE    = IPC_DIR / f"tg_commands_{_TG_SFX}.json"
RESULT_FILE = IPC_DIR / f"tg_results_{_TG_SFX}.json"
UPDATE_FLAG = Path(resource_path(f"config/update_{_TG_SFX}.flag"))

# wake channel: the JSON files stay the transport (durable, survive restarts, keep working) but can't tell the other side something arrived, so both ends polled and a reply waited ~4s before the model ran. loopback socket just says "look again now": no state, so losing it costs latency, never data, and both sides still poll underneath. port 0 = OS picks a free one (published in PORT_FILE), no account collisions.
PORT_FILE      = IPC_DIR / f"{P['key']}_port{_SFX}"

POLL_INTERVAL    = 2.0    # seconds between incoming-message polls
# The platform's own chats, never answered (the runner leaves them out of its passes too).
_SYSTEM_CHATS = P["system_chats"]
TG_POLL_INTERVAL = 2.0    # seconds between Telegram command polls
if PHONE:
    # The phone's messages come in as commands, and its request waits on each: looked for more often.
    TG_POLL_INTERVAL = 0.4
MAX_MSG_AGE      = 300.0  # ignore messages older than 5 minutes (stale)


def _snap_debug() -> bool:
    """True only when SNAP_DEBUG is an explicit on value."""
    return os.getenv("SNAP_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


# ── Runtime state (mirrors the per-bot attributes the Discord runner keeps) ──
STATE = {
    "paused": False,
    "paused_users": set(),   # chat ids the bot is paused for
    "ignore_users": set(),   # chat ids the bot ignores entirely
}

# chat_id -> display name, populated as messages arrive so /reply can label users
CHAT_NAMES: dict[str, str] = {}

# per-conversation generation lock, not one per account: the loop and /reply must not interleave awaits and corrupt history ordering. state is keyed per chat, so different conversations never touch the same entries; an account-wide lock made five chats queue up behind whoever was first.
_gen_locks: dict = {}

# but not unlimited concurrency either: a burst of chats fanning out into a burst of Groq requests trips rate limits. small ceiling keeps the throughput win without that.
_GEN_SLOTS = asyncio.Semaphore(3)


def _gen_lock(key: str) -> asyncio.Lock:
    """The generation lock for one conversation."""
    lock = _gen_locks.get(key)
    if lock is None:
        lock = _gen_locks[key] = asyncio.Lock()
    return lock

# ── The panel's Chats tab ─────────────────────────────────────────────────────
# A Snapchat conversation can be read and written from the Chats tab, as a
# Discord one can. The page belongs to the Node runner, so this asks it, over
# the wake socket, and it does it between its own steps (processPanel there).
# Whatever it reads of a conversation comes back as a transcript and is kept in
# the chat log (app/utils/chatlog.py) under account SNAP_BASE + this one's
# number: the tab's search, its pictures and links, and jumping back all work
# from there. What is new in it is pushed to the tab, as the Discord runner's
# events are.
from app.utils import chatlog
from app.utils import snappeople as _people
from app.core.launcher import under_panel as _under_panel


class _People:
    """app/utils/snappeople.py, for this bridge's platform: who each chat is, off the runner's chat list."""

    @staticmethod
    def avatar_url(account, chat):
        return _people.avatar_url(account, chat, PLATFORM)

    @staticmethod
    def name_of(account, chat):
        return _people.name_of(account, chat, PLATFORM)


snappeople = _People()

LOG_ACCOUNT = chatlog.web_account(PLATFORM, ACCOUNT_INDEX)
_CHAT_EVENT_MARK = "\x1eCHAT "
_EMIT_EVENTS = _under_panel()
# One writer at a time on stdout: the runner's relayed lines and the events share it, and an event is only one when
# it starts a line.
_OUT_LOCK = threading.Lock()
_PANEL_WAITERS: dict = {}
# Chats answered from the panel, and when: a reply the bot was still writing for them then is not sent after it.
_ANSWERED_BY_HAND: dict = {}
_PANEL_TASKS: set = set()


def _emit_chat(evt: dict) -> None:
    if not _EMIT_EVENTS:
        return
    try:
        with _OUT_LOCK:
            sys.stdout.write(_CHAT_EVENT_MARK + json.dumps(evt, ensure_ascii=True, default=str) + "\n")
            sys.stdout.flush()
    except Exception:
        pass


# Where each chat's reply is, for the Chats tab's tracker: the same states as Discord's (set_reply_state in the Discord
# runner), so a Snapchat row says "Writing a reply" or "Sends in 8s" rather than "Not picked up" while it is answered.
_REPLY_STATE: dict = {}
# The task writing or sending each chat's reply right now, so cancelling a reply from the panel can stop it in flight.
_REPLY_TASKS: dict = {}


def _set_state(chat_id: str, state: str, eta: float | None = None, reason: str = "") -> None:
    st = {"state": state, "since": time.time(), "eta": eta, "reason": reason}
    _REPLY_STATE[str(chat_id)] = st
    _emit_chat({"t": "state", "uid": str(chat_id), "state": st})


def _clear_state(chat_id: str) -> None:
    if _REPLY_STATE.pop(str(chat_id), None) is not None:
        _emit_chat({"t": "state", "uid": str(chat_id), "state": None})


def _seed_history(chat_id: str, before_ts: float) -> None:
    """The first reply in a chat since the bot started: the conversation before it, from the chat log (what the runner
    read off the page), as Discord's first reply after a restart picks up its channel's history. What is being
    answered now is left off the end: it comes in as this message."""
    key = f"{chat_id}-{chat_id}"
    if engine.message_history.get(key):
        return
    try:
        turns = chatlog.seed_turns(LOG_ACCOUNT, chat_id, before_ts + 1, limit=getattr(engine, "MAX_HISTORY", 20) * 2)
    except Exception:
        turns = []
    while turns and turns[-1]["role"] == "user":
        turns.pop()
    if turns:
        engine.message_history[key] = turns + list(engine.message_history.get(key, []))
        log_system(f"Picked up {len(turns)} earlier turns of the conversation before replying")


def _kept_unanswered(chat_id: str) -> str:
    """Their messages after the account's last one, as the chat log kept them: what a Reply answers when this run has
    nothing waiting for the chat (it came in while the bot was off, or before a restart)."""
    tail = []
    for m in reversed(chatlog.conversation(LOG_ACCOUNT, chat_id, 30)):
        if m.get("mine"):
            break
        text = str(m.get("text") or "").strip()
        if text and not m.get("deleted"):
            tail.insert(0, text)
    return "\n".join(tail[-8:])


# Chats whose reply was cancelled from the panel, and when: one the bot is writing or pacing then is not sent.
_CANCELLED: dict = {}


def _held_back(chat_id: str, name: str, began: float) -> bool:
    """A reply the bot wrote that must not go out after all: the bot was turned off for them, you cancelled it, or you
    answered them yourself from the panel, while it was being written or paced."""
    if _CANCELLED.get(chat_id, 0) >= began:
        log_system(f"Reply to {name} cancelled from the panel, not sent")
        _set_state(chat_id, "skipped", reason="you cancelled the reply")
        return True
    if chat_id in STATE["ignore_users"]:
        log_system(f"Not sending the reply to {name}: the bot was turned off for them")
        return True
    if _ANSWERED_BY_HAND.get(chat_id, 0) >= began:
        log_system(f"Not sending the reply to {name}: you answered them yourself from the panel")
        _set_state(chat_id, "skipped", reason="you answered them yourself")
        return True
    return False


async def _panel(op: str, timeout: float = 60.0, **kw) -> dict:
    """Ask the Node runner to do something in the page for the panel, and wait for its answer."""
    if TELEGRAM:
        return await _telegram_panel(op, **kw)
    if PHONE:
        return {"ok": False, "reason": "Through your iPhone it can only answer: sending from here needs a Mac"}
    if not _node_writers:
        return {"ok": False, "reason": f"{PLATFORM_NAME} is not ready yet; try again in a moment"}
    rid = _uuid.uuid4().hex
    fut = asyncio.get_running_loop().create_future()
    _PANEL_WAITERS[rid] = fut
    line = (json.dumps({"kind": "panel", "id": rid, "op": op, **kw}) + "\n").encode("utf-8")
    for writer in list(_node_writers):
        try:
            writer.write(line)
        except Exception:
            _node_writers.discard(writer)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "reason": f"{PLATFORM_NAME} did not answer in time; it may be busy, try again"}
    finally:
        _PANEL_WAITERS.pop(rid, None)


def _day_start(iso: str) -> float:
    try:
        return datetime.combine(date.fromisoformat(iso), _dtime.min).timestamp()
    except (TypeError, ValueError):
        return time.time() - 86400


def _body_of(m: dict) -> dict:
    """A message as the runner read it, as the chat log keeps it: its words (or what it was: "[video]"), its links,
    its reactions; a shared TikTok shown by its cover, with what the page says of it, as a preview; what it answers."""
    kind = str(m.get("kind") or "")
    text = str(m.get("text") or "")[:2000]
    # A video sent from their phone is "clip" to the TikTok runner (a shared TikTok is "video"): a video to anyone.
    body = {"text": text or (f"[{'video' if kind == 'clip' else kind}]" if kind else ""), "kind": kind}
    links = [{"url": str(l.get("url")), "title": str(l.get("title") or "")[:140]}
             for l in (m.get("links") or []) if isinstance(l, dict) and str(l.get("url") or "").startswith("http")]
    media = m.get("media") if isinstance(m.get("media"), dict) else {}
    cover = str(media.get("cover") or "")
    if kind == "video" and cover.startswith("https://"):
        links.insert(0, {"title": str(m.get("title") or "A TikTok")[:140], "image": cover, "provider": "TikTok"})
    if links:
        body["embeds"] = links[:3]
    if m.get("quote"):
        # What it answers, as the page quotes it: the same field as a Discord reply's.
        body["reply_to"] = {"text": str(m["quote"])[:200]}
    if m.get("reactions"):
        body["reactions"] = _clean_reactions(m["reactions"])
    return body


def _store_transcript(chat_id: str, name: str, messages: list) -> list:
    """A conversation as the runner read it, into the chat log. Snapchat for Web shows a day above its messages, not
    a time: a message seen as it arrives is kept with that moment, one from an earlier day with a time inside that
    day (marked approx, so the tab shows the day and not a made-up time). Returns the messages that are new at the
    end of a conversation already being kept, which the tab is told about; a first read tells it nothing, it is the
    conversation's past."""
    msgs = [m for m in messages if isinstance(m, dict) and m.get("key")]
    if not chat_id or not msgs:
        return []
    if name:
        CHAT_NAMES.setdefault(chat_id, name)
    known = chatlog.known_ts(LOG_ACCOUNT, chat_id, [m["key"] for m in msgs])
    tracked = chatlog.count(LOG_ACCOUNT, chat_id) > 0
    now = time.time()
    today = date.today().isoformat()
    rows, fresh = [], []
    # The reactions on messages already kept, as the page shows them now: someone reacted since, or took one back.
    reacted = {}
    prev = 0.0
    for i, m in enumerate(msgs):
        key = m["key"]
        if key in known:
            prev = max(prev, known[key])
            if "reactions" in m:
                reacted[key] = _clean_reactions(m["reactions"])
            continue
        later = next((known[x["key"]] for x in msgs[i + 1:] if x["key"] in known), None)
        newer_after = sum(1 for x in msgs[i + 1:] if x["key"] not in known)
        day = m.get("day") or today
        start = _day_start(day)
        sent_at = float(m.get("at") or 0) / 1000.0
        if sent_at > 0:
            # The page said when: that, exactly (a group's messages share one moment, so they keep their order by a
            # thousandth of a second each).
            ts, approx = max(sent_at, prev + 0.001), False
            prev = ts
            body = _body_of(m)
            rows.append((key, bool(m.get("mine")), ts, body))
            if tracked and later is None:
                fresh.append({"mid": key, "mine": bool(m.get("mine")), "ts": ts, **body})
            continue
        if later is not None:
            # Between two kept ones: halfway, so the order holds.
            ts, approx = prev + (later - prev) / 2 if later > prev else prev + 0.001, True
        elif day >= today:
            ts, approx = now - newer_after, not tracked
        else:
            ts, approx = start + 12 * 3600 + i, True
        ts = max(ts, prev + 0.001, start)
        prev = ts
        body = _body_of(m)
        if approx:
            body["approx"] = True
        rows.append((key, bool(m.get("mine")), ts, body))
        if tracked and later is None:
            fresh.append({"mid": key, "mine": bool(m.get("mine")), "ts": ts, **body})
    if rows:
        chatlog.put_many(LOG_ACCOUNT, chat_id, rows)
    for mid, now_reactions in chatlog.sync_reactions(LOG_ACCOUNT, reacted):
        _emit_chat({"t": "reactions", "uid": chat_id, "mid": mid, "reactions": now_reactions})
    return fresh


def _clean_reactions(raw) -> list:
    """Reactions as the runner read them off the page, checked: one of Snapchat's own by its character, or a picture
    it did not know (Snapchat added one), with how many and whether the account's own is among them."""
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "")[:16]
        url = str(r.get("url") or "")
        if not name and not url.startswith("https://"):
            continue
        out.append({"name": name, **({"url": url[:400]} if url.startswith("https://") and not name else {}),
                    "count": max(1, min(99, int(r.get("count") or 1))), "mine": bool(r.get("mine"))})
    return out[:8]


def _announce(chat_id: str, name: str, fresh: list) -> None:
    """What is new in a conversation, to the Chats tab: their messages as they come, the account's own as sent."""
    if not fresh:
        return
    avatar = snappeople.avatar_url(ACCOUNT_INDEX, chat_id)
    answered = False
    for m in fresh:
        words = m.get("text") or ""
        if m["mine"]:
            _emit_chat({"t": "sent", "uid": chat_id, "mid": m["mid"], "ts": m["ts"], "text": words})
            answered = True
        else:
            _emit_chat({"t": "msg", "uid": chat_id, "mid": m["mid"], "ts": m["ts"], "text": words,
                        "snippet": words[:60], "name": name or CHAT_NAMES.get(chat_id, chat_id), "avatar": avatar,
                        "ignored": chat_id in STATE["ignore_users"]})
            answered = False
    if answered:
        _REPLY_STATE.pop(chat_id, None)
        _note_answered(chat_id)
        _emit_chat({"t": "done", "uid": chat_id})


def _on_transcript(msg: dict) -> None:
    chat_id = str(msg.get("chat") or "")
    name = str(msg.get("name") or "")
    try:
        _announce(chat_id, name, _store_transcript(chat_id, name, msg.get("messages") or []))
    except Exception as e:
        log_error("Snap chat log", str(e))


# ── iMessage through the iPhone (no Mac) ─────────────────────────────────────
# A Shortcuts automation on the phone runs on every message it gets (Messages, from anybody, run immediately) and
# posts it here through the panel; the request waits for the persona's answer, and the phone sends that back to the
# one who wrote. Several in a row from one person are answered once, together, as on a Mac (imessage.burst_ms): the
# first request carries the answer and the others get nothing to send.
_RELAY_WAIT: dict = {}
_RELAY_BURST: dict = {}
# Shortcuts gives up on a request after a minute; the answer has to be back well before.
RELAY_ANSWER_WITHIN = 45.0
_RELAY_SEEN = {"last": 0.0}


def _relay_person(sender: str) -> tuple:
    """(their id, their name) from what the phone says of the sender: a contact's name, or the number or email of
    someone who is not one."""
    who = " ".join(str(sender or "").split())[:120]
    if not who:
        return "", ""
    return _people.imessage_person_id(who), who


def _relay_note(chat_id: str, name: str, key: str, mine: bool, text: str) -> None:
    """One message kept in the chat log and shown in the Chats tab, as a runner's transcript would be."""
    ts = time.time()
    try:
        chatlog.put(LOG_ACCOUNT, chat_id, key, mine, ts, {"text": text})
    except Exception as e:
        log_error("iMessage chat log", str(e))
    _announce(chat_id, name, [{"mid": key, "mine": mine, "ts": ts, "text": text}])


def _relay_answered(msg_id: str, text: str, chat_id: str = None, name: str = None) -> None:
    fut = _RELAY_WAIT.get(msg_id)
    if fut is not None and not fut.done():
        fut.set_result(text or "")


async def _relay_cmd(cmd_id: str, payload: dict) -> None:
    """One message the phone passed on: answered (or not) by the persona, the answer handed back for it to send."""
    chat_id, name = _relay_person(payload.get("from") or "")
    text = str(payload.get("text") or "").strip()[:4000]
    _RELAY_SEEN["last"] = time.time()
    if not chat_id or not text:
        _write_result(cmd_id, {"ok": True, "reply": "", "why": "nothing to answer"})
        return
    _remember_relay_person(chat_id, name)
    _relay_note(chat_id, name, f"r{_uuid.uuid4().hex[:16]}", False, text)
    loop = asyncio.get_running_loop()
    held = _RELAY_BURST.get(chat_id)
    if held and not held["fut"].done():
        # Another message while the first is still gathering its company: it goes with that one.
        held["texts"].append(text)
        held["until"] = time.time() + _relay_burst_s()
        _write_result(cmd_id, {"ok": True, "reply": "", "why": "answered with the one before"})
        return
    fut = loop.create_future()
    held = {"texts": [text], "until": time.time() + _relay_burst_s(), "fut": fut}
    _RELAY_BURST[chat_id] = held
    while time.time() < held["until"]:
        await asyncio.sleep(0.25)
    _RELAY_BURST.pop(chat_id, None)
    msg_id = f"r{_uuid.uuid4().hex}"
    _RELAY_WAIT[msg_id] = fut
    queued = _read_json(INCOMING_FILE, [])
    queued = queued if isinstance(queued, list) else []
    # "relay": the phone waits RELAY_ANSWER_WITHIN for the answer, which a look online could outlast (no_web below).
    queued.append({"id": msg_id, "user_id": chat_id, "user_name": name, "channel_id": chat_id,
                   "content": "\n".join(held["texts"]), "ts": time.time(), "photo": False, "relay": True})
    _write_json(INCOMING_FILE, queued[-200:])
    _wake_incoming.set()
    try:
        reply = await asyncio.wait_for(fut, RELAY_ANSWER_WITHIN)
    except asyncio.TimeoutError:
        reply = ""
        log_system(f"[iMessage] The answer to {name} took too long for the iPhone to wait; it was not sent")
    finally:
        _RELAY_WAIT.pop(msg_id, None)
    # The phone sends it as one message: its parts one to a line, not apart with blank lines between.
    reply = "\n".join(line.strip() for line in str(reply or "").splitlines() if line.strip())
    if reply:
        _relay_note(chat_id, name, f"r{_uuid.uuid4().hex[:16]}", True, reply)
        log_system(f"sent to {name} (through your iPhone)")
    _write_result(cmd_id, {"ok": True, "reply": reply})


def _relay_burst_s() -> float:
    try:
        return max(0.0, min(10.0, float(_imessage_cfg().get("burst_ms", 4000)) / 1000.0))
    except (TypeError, ValueError):
        return 4.0


def _remember_relay_person(chat_id: str, name: str) -> None:
    """Their name in the people this account knows, so the Chats tab and People say it rather than an id."""
    CHAT_NAMES[chat_id] = name
    try:
        _people.remember(ACCOUNT_INDEX, chat_id, {"name": name}, "imessage")
    except Exception:
        pass


async def _phone_state_loop() -> None:
    """The account's state, written here since no runner writes it: up, and whether the phone has been heard from."""
    path = IPC_DIR / f"{P['key']}_state{_SFX}.json"
    while True:
        heard = _RELAY_SEEN["last"]
        detail = "" if heard else ("Waiting for your iPhone. Its shortcut is set up in Settings, iMessage, Setup.")
        try:
            _write_json(path, {"state": "ready", "detail": detail, "at": time.time(), "account": ACCOUNT_INDEX,
                               "phone": True, **({"heard": heard} if heard else {})})
        except Exception:
            pass
        await asyncio.sleep(20)


# ── Telegram: the client where a runner would be ─────────────────────────────

def _incoming_waiting() -> list:
    """The chats with a message waiting for an answer, so the panel can mark them as it does Discord's."""
    try:
        queued = _read_json(INCOMING_FILE, [])
        return [str(e.get("channel_id") or e.get("user_id") or "")
                for e in (queued if isinstance(queued, list) else [])]
    except Exception:
        return []


async def _telegram_panel(op: str, timeout: float = 60.0, **kw) -> dict:
    """What the panel asks for, done on the account itself. The same ops every runner answers, plus the ones only
    Discord could do before (a conversation searched, a window around a message, who someone is)."""
    tg = _TG.get("client")
    if tg is None:
        return {"ok": False, "reason": "Telegram is not connected yet; try again in a moment"}
    chat = str(kw.get("chat") or kw.get("user_id") or "")
    try:
        if op == "history":
            return {"ok": True, "messages": await tg.history(chat, int(kw.get("limit") or 25)),
                    "kept": True}
        if op == "search":
            return {"ok": True, "messages": await tg.history(chat, int(kw.get("limit") or 40),
                                                             search=str(kw.get("words") or ""))}
        if op == "window":
            return {"ok": True, "messages": await tg.history(chat, int(kw.get("limit") or 50),
                                                             before=kw.get("mid"))}
        if op == "profile":
            return {"ok": True, "profile": await tg.profile(chat)}
        if op == "send":
            mid = await _telegram_say(chat, str(kw.get("text") or ""), files=kw.get("images") or [],
                                      reply_to=kw.get("reply_to"))
            return {"ok": True, "mid": str(mid)}
        if op == "react":
            emoji = str(kw.get("emoji") or "")
            if not emoji:
                return {"ok": False, "reason": "Which reaction?"}
            await tg.react(chat, kw.get("key") or kw.get("mid"), emoji)
            return {"ok": True}
        if op == "unsend":
            await tg.delete(chat, kw.get("key") or kw.get("mid"))
            return {"ok": True}
        if op == "edit":
            await tg.edit(chat, kw.get("key") or kw.get("mid"), str(kw.get("text") or ""))
            return {"ok": True}
        if op == "add_friend":
            return {"ok": True, **await tg.add_contact(str(kw.get("username") or ""), str(kw.get("text") or ""))}
        if op == "friends":
            # Telegram has no requests waiting anywhere: anyone may write, and anyone may be written to.
            return {"ok": True, "requests": []}
        if op == "guilds":
            # Discord's servers, for Telegram: it has no server holding channels, so the one place it is all in is
            # the account itself, and its groups and the channels it follows are the two shelves.
            rows, waiting = [], set(_incoming_waiting())
            for c in await tg.chats(int(kw.get("limit") or 100), every=True):
                if not c.get("group"):
                    continue
                channel = bool(c.get("broadcast"))
                rows.append({"id": c["id"], "name": c["name"],
                             "category": "Channels" if channel else "Groups",
                             "category_at": 1 if channel else 0, "at": 0, "topic": "", "nsfw": False,
                             "voice": False,
                             # A channel it only follows cannot be posted in; a group it is in can.
                             "can_send": not channel, "waiting": c["id"] in waiting})
            if not rows:
                return {"ok": True, "guilds": []}
            who = _TG.get("who") or {}
            return {"ok": True, "guilds": [{
                "id": "telegram", "name": who.get("name") or "Telegram", "icon": "",
                "members": 0, "channels": rows}]}
        if op == "state":
            return {"ok": True, "state": _TG.get("state", "starting"), **(_TG.get("who") or {})}
        return {"ok": False, "unsupported": True, "reason": f"Not something Telegram has ({op})."}
    except Flood as e:
        _telegram_flood(e)
        return {"ok": False, "reason": f"Telegram asked to wait {e.seconds} s before doing that again."}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _telegram_flood(e) -> None:
    """Telegram asked for a wait: said on the card, and to you, and nothing is sent until it passes."""
    mins = max(1, int(e.seconds // 60))
    detail = (f"Telegram asked it to wait {mins} min before {e.doing or 'sending'} again. "
              "It carries on by itself afterwards.")
    log_error(PLATFORM_NAME, detail)
    _set_runner_state("needs-you", detail)
    _notify_owner("Telegram asked it to wait", detail)


def _set_runner_state(state: str, detail: str = "") -> None:
    """The account's own state file, which a runner would write (ipc/tg_state.json)."""
    _TG["state"] = state
    try:
        _write_json(IPC_DIR / f"{P['key']}_state{_SFX}.json",
                    {"state": state, "detail": detail, "at": time.time(), "account": ACCOUNT_INDEX,
                     **(_TG.get("who") or {})})
    except Exception:
        pass


async def _telegram_say(chat: str, text: str, files=None, reply_to=None, voice: str = "") -> int:
    """One answer on its way out: the wait the governor asks for, the dots while it types, then the words. Several
    lines go as several messages, the way a person sends them."""
    tg, cfg = _TG["client"], _TG["cfg"]
    if cfg.get("dry_run"):
        log_system(f"Dry run, not sent to {_name_for(chat)}: {text[:120]}")
        return 0
    last = 0
    for path in (files or [])[:4]:
        await _telegram_turn()
        last = await tg.send(chat, "", file=path, caption=text if not last else "")
    if voice:
        await _telegram_turn()
        return await tg.send(chat, "", file=voice, voice=True)
    if files and text and last:
        return last                                   # the words went as the picture's caption
    for i, line in enumerate([ln for ln in str(text or "").split("\n") if ln.strip()]):
        await _telegram_turn()
        if cfg.get("typing_indicator", True):
            await tg.typing(chat, min(8.0, max(1.2, len(line) / (3.5 + random.random() * 3.5))))
        last = await tg.send(chat, line, reply_to=reply_to if i == 0 else None)
    return last


async def _telegram_turn() -> None:
    """Wait until the governor allows the next send."""
    tg = _TG["client"]
    while True:
        wait = tg.governor.wait_for()
        if wait <= 0:
            return
        await asyncio.sleep(min(wait, 30.0))


def _telegram_incoming(entry: dict) -> None:
    """A message from Telegram, into the same queue a runner fills."""
    if entry.get("quiet"):
        # A group message that did not call it by name: kept for the conversation, never answered.
        _telegram_keep(entry)
        return
    queued = _read_json(INCOMING_FILE, [])
    queued = queued if isinstance(queued, list) else []
    queued.append(entry)
    _write_json(INCOMING_FILE, queued[-300:])
    _wake_incoming.set()


def _telegram_keep(entry: dict) -> None:
    """Kept in the chat log and shown in the Chats tab, without being answered."""
    chat, name = entry.get("channel_id", ""), entry.get("speaker") or entry.get("user_name", "")
    try:
        chatlog.put(LOG_ACCOUNT, chat, f"t{entry.get('mid')}", False, float(entry.get("ts") or time.time()),
                    {"text": entry.get("content", ""), **({"author": {"name": name}} if entry.get("group") else {})})
    except Exception:
        pass


async def _telegram_main() -> None:
    """The account: signed in with the session its sign-in left, then listening until the app stops."""
    from app.platforms.telegram.client import Governor, Telegram
    from app.utils.credentials import real
    from app.utils.paths import DATA_DIR
    cfg = _telegram_cfg()
    _TG["cfg"] = cfg
    api_id, api_hash = real(f"TELEGRAM_API_ID_{ACCOUNT_INDEX}"), real(f"TELEGRAM_API_HASH_{ACCOUNT_INDEX}")
    session = real(f"TELEGRAM_SESSION_{ACCOUNT_INDEX}")
    if not (api_id and api_hash and session):
        _set_runner_state("needs-you", "This Telegram account is not signed in yet. Sign it in on the Accounts page.")
        log_error(PLATFORM_NAME, "No sign-in saved for this account.")
        return
    _set_runner_state("starting", "Connecting to Telegram")
    from app.utils import stealth as _stealth
    _careful = _stealth.conservative()
    _g_min = _stealth.pace(cfg["min_send_gap_ms"])
    _g_max = max(_g_min, _stealth.pace(cfg["max_send_gap_ms"]))
    tg = Telegram(api_id, api_hash, session, data_dir=DATA_DIR, log=lambda s: log_system(f"[Telegram] {s}"),
                  governor=Governor(_g_min, _g_max, _stealth.rate(cfg["max_sends_per_hour"]),
                                    cfg["quiet_hours"]),
                  on_message=_telegram_incoming, on_changed=_telegram_changed, on_reaction=_telegram_reacted,
                  on_typing=lambda chat, on: _emit_chat({"t": "typing", "uid": chat}) if on else None,
                  on_call=_telegram_called, on_state=_set_runner_state,
                  proxy=os.getenv(f"TELEGRAM_PROXY_{ACCOUNT_INDEX}", "").strip())
    if _careful["on"]:
        log_system(f"[Telegram] Careful mode: replies at {_careful['reply_scale']:g}\u00d7, "
                   f"waits \u00d7{_careful['wait_scale']:g}.")
    _TG["client"] = tg
    try:
        who = await tg.start()
    except PermissionError as e:
        _set_runner_state("logged-out", str(e))
        log_error(PLATFORM_NAME, str(e))
        return
    except Exception as e:
        _set_runner_state("logged-out", f"Telegram would not let it in: {e}")
        log_error(PLATFORM_NAME, f"Could not connect: {e}")
        return
    _TG["who"] = who
    tg.answer_groups = bool(cfg.get("groups"))
    tg.answer_channels = bool(cfg.get("channels"))
    tg.keep_media = bool(cfg.get("keep_media", True))
    try:
        trigger = str(((load_config() or {}).get("bot") or {}).get("trigger") or "")
    except Exception:
        trigger = ""
    from app.platforms.telegram import people as tgpeople
    tg.names = tgpeople.trigger_names(trigger, who.get("username", ""), (who.get("name") or "").split(" ")[0])
    _telegram_identity(who)
    log_system(f"[Telegram] Signed in as {who['name'] or who['username'] or who['phone']}"
               + (f" (@{who['username']})" if who.get("username") else "")
               + f". {'Groups on' if tg.answer_groups else 'Groups off'}, "
               + f"{cfg['max_sends_per_hour']} sends an hour at most.")
    _set_runner_state("ready")
    _spawn_panel(_telegram_sender())
    _spawn_panel(_telegram_people_loop())
    await tg.run()


def _telegram_identity(who: dict) -> None:
    """Who the account is, for its card (status_routes._web_identity), as the other runners record theirs."""
    try:
        from app.utils.paths import DATA_DIR
        from app.utils.atomic import write_json_atomic
        write_json_atomic(DATA_DIR / "config" / f"identity_telegram_{ACCOUNT_INDEX}.json",
                          {"username": who.get("username") or who.get("phone") or str(who.get("id") or ""),
                           "display_name": who.get("name") or "", "at": time.time()})
    except Exception:
        pass


def _telegram_changed(kind: str, chat: str, mid: str, text: str) -> None:
    """A message edited, deleted, or sent from Telegram itself: kept, as the other platforms' are."""
    key = f"t{mid}"
    try:
        if kind == "deleted":
            uid = chatlog.mark_deleted(LOG_ACCOUNT, key)
            if uid:
                _emit_chat({"t": "deleted", "uid": uid, "mid": key, "at": time.time()})
        elif kind == "edited":
            uid = chatlog.mark_edited(LOG_ACCOUNT, key, {"text": text})
            if uid:
                _emit_chat({"t": "edited", "uid": uid, "mid": key, "text": text, "at": time.time()})
        elif kind == "mine" and chat:
            chatlog.put(LOG_ACCOUNT, chat, key, True, time.time(), {"text": text})
            _emit_chat({"t": "sent", "uid": chat, "mid": key, "ts": time.time(), "text": text})
            # You answered them yourself from Telegram: whatever the bot had lined up is dropped.
            if _drop_outgoing(chat):
                log_system(f"You answered {_name_for(chat)} on Telegram, so its reply was dropped")
            _REPLY_STATE.pop(chat, None)
    except Exception as e:
        log_error("Telegram chat log", str(e))


def _telegram_reacted(chat: str, mid: str, reactions: list) -> None:
    try:
        now = chatlog.set_reactions(LOG_ACCOUNT, f"t{mid}", reactions)
        if now is not None:
            _emit_chat({"t": "reactions", "uid": chat, "mid": f"t{mid}", "reactions": reactions})
    except Exception:
        pass


def _telegram_called(chat: str, name: str, call) -> None:
    """Someone calling: already declined, and answered in words when that is the setting."""
    log_system(f"[Telegram] {name} is calling.")
    _emit_chat({"t": "call", "uid": chat, "call": {"state": "ringing", "name": name, "at": time.time()}})
    if not _TG["cfg"].get("call_text", True):
        return
    _spawn_panel(_telegram_call_text(chat, name))


async def _telegram_call_text(chat: str, name: str) -> None:
    try:
        async with _gen_lock(chat), _GEN_SLOTS:
            words = await _generate_call_decline(chat, name)
    except Exception as e:
        log_error("Telegram call", str(e))
        return
    if words:
        words = _humanize_reply(words)
        log_system(f"Declined call from {name} → {words}")
        await _telegram_say(chat, words)
        _telegram_changed("mine", chat, str(int(time.time())), words)


async def _telegram_sender() -> None:
    """The answers and the messages the bridge queues, sent: what a Node runner's own loop does elsewhere."""
    tg = _TG["client"]
    while True:
        await asyncio.sleep(1.0)
        try:
            await _telegram_drain(tg)
        except Flood as e:
            _telegram_flood(e)
        except Exception as e:
            log_error(PLATFORM_NAME, f"Could not send: {e}")
            await asyncio.sleep(5)


async def _telegram_drain(tg) -> None:
    cfg = _TG["cfg"]
    answers = _read_json(RESPONSES_FILE, {})
    if isinstance(answers, dict):
        for msg_id, answer in list(answers.items()):
            if not isinstance(answer, dict):
                continue
            fresh = _read_json(RESPONSES_FILE, {})
            if msg_id not in fresh:
                continue
            del fresh[msg_id]
            _write_json(RESPONSES_FILE, fresh)
            chat = str(answer.get("chat") or "")
            if cfg.get("read_receipts", True):
                await tg.read(chat)
            if answer.get("react"):
                try:
                    await tg.react(chat, str(answer.get("react_to") or "").lstrip("t"), answer["react"])
                except Exception as e:
                    log_system(f"[Telegram] The reaction did not go: {e}")
            text = str(answer.get("text") or "")
            if text:
                mid = await _telegram_say(chat, text, voice=str(answer.get("voice") or ""))
                _telegram_sent(chat, mid, text)
                _handed_over(chat)
                if answer.get("fixed") and cfg.get("fix_typos", True) and mid:
                    await asyncio.sleep(random.uniform(2.5, 9.5))
                    try:
                        await tg.edit(chat, mid, str(answer["fixed"]))
                        _telegram_changed("edited", chat, str(mid), str(answer["fixed"]))
                        log_system(f"[Telegram] Fixed a typo in what it sent {_name_for(chat)}")
                    except Exception:
                        pass
    waiting = _read_json(OUTGOING_FILE, [])
    if isinstance(waiting, list) and waiting:
        entry = waiting[0]
        _write_json(OUTGOING_FILE, waiting[1:])
        if isinstance(entry, dict):
            chat = str(entry.get("chat") or "")
            mid = await _telegram_say(chat, str(entry.get("text") or entry.get("message") or ""),
                                      files=[entry["image"]] if entry.get("image") else None,
                                      voice=str(entry.get("voice") or ""))
            _telegram_sent(chat, mid, str(entry.get("text") or ""))
            _handed_over(chat)


def _telegram_sent(chat: str, mid, text: str) -> None:
    """What it just sent, kept and shown, the way a transcript would bring it back."""
    if not mid:
        return
    try:
        chatlog.put(LOG_ACCOUNT, chat, f"t{mid}", True, time.time(), {"text": text})
    except Exception:
        pass
    _emit_chat({"t": "sent", "uid": chat, "mid": f"t{mid}", "ts": time.time(), "text": text})
    log_system(f"sent to {_name_for(chat)}")


async def _telegram_people_loop() -> None:
    """Its chats, so the panel knows who everyone is: their names and pictures, kept as the other platforms keep
    them (cache/telegram_people). Also its presence at night, where that is on."""
    from app.utils import snappeople
    from app.utils.paths import DATA_DIR
    folder = DATA_DIR / "cache" / "telegram_people"
    tg = _TG["client"]
    night = None
    while True:
        try:
            for row in await tg.chats(60):
                CHAT_NAMES[row["id"]] = row["name"]
                fields = {"name": row["name"], **({"group": True} if row["group"] else {})}
                file = folder / f"{ACCOUNT_INDEX}_{row['id']}.jpg"
                if not file.exists():
                    folder.mkdir(parents=True, exist_ok=True)
                    if await tg.avatar(row["id"], file):
                        fields["file"] = file.name
                snappeople.remember(ACCOUNT_INDEX, row["id"], fields, "telegram")
        except Flood as e:
            _telegram_flood(e)
        except Exception as e:
            log_system(f"[Telegram] Could not read its chats: {e}")
        if _TG["cfg"].get("night_offline", True):
            want = not _quiet_until()
            if want != night:
                night = want
                try:
                    await tg.set_online(want)
                except Exception:
                    pass
        await asyncio.sleep(300)


def _spawn_panel(coro) -> None:
    task = asyncio.create_task(coro)
    _PANEL_TASKS.add(task)
    task.add_done_callback(_PANEL_TASKS.discard)


# The platform's reactions, in the order its picker shows them: the only ones it has, one per person on a message.
SNAP_REACTIONS = P["reactions"]


def _social():
    """The two modules this platform goes out with: what it watches links with, and what it says about them.
    (instagramwatch, instagramsocial) for Instagram, (tiktokwatch, tiktoksocial) for TikTok, (xwatch, xsocial) for
    X, (redditwatch, redditsocial) for Reddit; (None, None) for Snapchat, which never leaves its inbox."""
    if PLATFORM == "instagram":
        from app.utils import instagramsocial, instagramwatch
        return instagramwatch, instagramsocial
    if PLATFORM == "tiktok":
        from app.utils import tiktoksocial, tiktokwatch
        return tiktokwatch, tiktoksocial
    if PLATFORM == "x":
        from app.utils import xsocial, xwatch
        return xwatch, xsocial
    if PLATFORM == "reddit":
        from app.utils import redditsocial, redditwatch
        return redditwatch, redditsocial
    return None, None


def _profile_counts() -> dict:
    """A TikTok or Instagram account's followers, following and the rest, from what its runner last read off its
    profile (config/identity_<platform>_N.json). Nothing for Snapchat, whose page has no such counts."""
    if not SOCIAL:
        return {}
    from app.utils.paths import DATA_DIR
    try:
        data = json.loads((DATA_DIR / "config" / f"identity_{PLATFORM}_{ACCOUNT_INDEX}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: int(data[k]) for k in ("followers", "following", "likes", "videos", "posts")
            if isinstance(data.get(k), (int, float)) and not isinstance(data.get(k), bool)}


async def _react_cmd(cmd_id: str, payload: dict) -> None:
    """A reaction from the Chats tab, on a message in a conversation: the runner hovers it on Snapchat's page and
    picks from React, as a person does (react in snapchat_runner.js). Kept in the chat log, and shown live."""
    chat = str(payload.get("user_id") or "")
    key = str(payload.get("mid") or "")
    emoji = str(payload.get("emoji") or "")
    # Instagram's picker searches every emoji there is; the others have a fixed few.
    if not P.get("any_reaction") and emoji not in SNAP_REACTIONS:
        _write_result(cmd_id, {"ok": False, "reason": f"{PLATFORM_NAME} only has " + " ".join(SNAP_REACTIONS)})
        return
    if P.get("any_reaction") and not emoji:
        _write_result(cmd_id, {"ok": False, "reason": "which emoji?"})
        return
    r = await _panel("react", chat=chat, name=_name_for(chat), key=key, emoji=emoji,
                     remove=bool(payload.get("remove")), timeout=65.0)
    if not r.get("ok"):
        _write_result(cmd_id, {"ok": False, "reason": r.get("reason") or f"{PLATFORM_NAME} did not take it"})
        return
    reactions = _clean_reactions(r.get("reactions"))
    if chatlog.set_reactions(LOG_ACCOUNT, key, reactions) is not None:
        _emit_chat({"t": "reactions", "uid": chat, "mid": key, "reactions": reactions})
    _write_result(cmd_id, {"ok": True, "reactions": reactions})


async def _guilds_cmd(cmd_id: str, payload: dict) -> None:
    """The groups and channels this account is in, for the Chats tab to walk into."""
    _write_result(cmd_id, await _telegram_panel("guilds", limit=int(payload.get("limit") or 100)))


async def _history_cmd(cmd_id: str, payload: dict) -> None:
    """The Chats tab opening a conversation: read from the page, kept, and given back as the tab draws it."""
    chat = str(payload.get("user_id") or "")
    limit = max(5, min(200, int(payload.get("limit") or 25)))
    if PHONE:
        # Nothing to read back from the phone: every message it passed on, and every answer, was kept as it went.
        _write_result(cmd_id, {"ok": True, "messages": chatlog.conversation(LOG_ACCOUNT, chat, limit)})
        return
    r = await _panel("history", chat=chat, name=_name_for(chat), timeout=50.0)
    if r.get("ok"):
        _announce(chat, CHAT_NAMES.get(chat, ""), _store_transcript(chat, CHAT_NAMES.get(chat, ""), r.get("messages") or []))
        _write_result(cmd_id, {"ok": True, "messages": chatlog.conversation(LOG_ACCOUNT, chat, limit)})
        return
    kept = chatlog.conversation(LOG_ACCOUNT, chat, limit)
    if kept:
        _write_result(cmd_id, {"ok": True, "messages": kept, "from_log": True, "note": r.get("reason", "")})
    else:
        _write_result(cmd_id, {"ok": False, "reason": r.get("reason") or "could not read it"})


_OWN_BUSY = {"on": False}


def _drop_outgoing(chat: str) -> bool:
    """Messages queued for this chat and not sent yet (a Reply's answer waits there for the runner), taken back."""
    outgoing = _read_json(OUTGOING_FILE, [])
    if not isinstance(outgoing, list):
        return False
    keep = [e for e in outgoing if not (isinstance(e, dict) and str(e.get("chat")) == chat)]
    if len(keep) == len(outgoing):
        return False
    _write_json(OUTGOING_FILE, keep)
    return True


def _drop_lined_up(chat: str, by_hand: bool = True) -> bool:
    """A reply the bot had ready for this chat, not sent yet, taken back: it was answered by hand (or the bot was
    turned off for them, by_hand False)."""
    if by_hand:
        _ANSWERED_BY_HAND[chat] = time.time()
    responses = _read_json(RESPONSES_FILE, {})
    if not isinstance(responses, dict):
        return False
    gone = [k for k, v in responses.items() if isinstance(v, dict) and str(v.get("chat")) == chat]
    for k in gone:
        responses.pop(k, None)
    if gone:
        _write_json(RESPONSES_FILE, responses)
    return bool(gone)


#: What the panel's send box may attach as a picture (the same list pictures.py keeps for its own).
_PICTURE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


async def _send_cmd(cmd_id: str, payload: dict) -> None:
    """A message typed in the Chats tab, sent as this account: words, and pictures as Snaps. A reply the bot had lined
    up for them is dropped, and what was sent goes into the bot's history as the account's own words."""
    if PHONE:
        _write_result(cmd_id, {"ok": False, "reason": "Through your iPhone it can only answer the messages it gets. Sending first needs the Mac way (BlueBubbles)"})
        return
    chat = str(payload.get("user_id") or "")
    text = str(payload.get("text") or "").strip()[:2000]
    paths = []
    try:
        for f in (payload.get("files") or [])[:4]:
            name = os.path.basename(str((f or {}).get("name") or "picture.png"))
            ext = os.path.splitext(name)[1].lower()
            if ext not in _PICTURE_TYPES:
                _write_result(cmd_id, {"ok": False, "reason": f"{name}: {PLATFORM_NAME} takes pictures from here"})
                return
            try:
                data = base64.b64decode(str(f.get("data") or ""), validate=True)
            except Exception:
                _write_result(cmd_id, {"ok": False, "reason": f"{name}: the file could not be read"})
                return
            if not data or len(data) > 8 * 1024 * 1024:
                _write_result(cmd_id, {"ok": False, "reason": f"{name}: empty, or bigger than 8MB"})
                return
            folder = resource_path("config/temp")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"panel_{_uuid.uuid4().hex[:10]}{ext}")
            with open(path, "wb") as out:
                out.write(data)
            paths.append(path)
        if not text and not paths:
            _write_result(cmd_id, {"ok": False, "reason": "nothing to send"})
            return
        dropped = _drop_lined_up(chat)
        name = _name_for(chat)
        # A reply to one message: the runner presses the page's own Reply on it before typing.
        reply_to = str(payload.get("reply_to") or "")[:80]
        r = await _panel("send", chat=chat, text=text, images=paths, name=name, reply_to=reply_to, timeout=150.0)
    finally:
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
    if not r.get("ok"):
        _write_result(cmd_id, {"ok": False, "reason": r.get("reason") or "could not send it"})
        return
    _announce(chat, name, _store_transcript(chat, name, r.get("messages") or []))
    hist = engine.message_history.setdefault(f"{chat}-{chat}", [])
    hist.append({"role": "assistant", "content": text or "[sent a picture]"})
    log_system(f"You wrote to {name or chat} from the panel" + (", so the bot's reply was dropped" if dropped else ""))
    key = r.get("sent") or ""
    ts = chatlog.known_ts(LOG_ACCOUNT, chat, [key]).get(key, time.time()) if key else time.time()
    out = {"ok": True, "mid": key, "ts": ts, "text": text, "dropped_reply": dropped}
    if r.get("replied") is not None:
        # Asked as a reply: whether the page's own Reply took it, or it went as a plain message.
        out["replied"] = bool(r.get("replied"))
    _write_result(cmd_id, out)


def _name_for(chat: str) -> str:
    """A chat's name, from whatever knows it: this run's messages, the runner's chat list, or the message log, which
    remembers people whose chats Snapchat no longer lists (their chat is then opened through its search, by name)."""
    name = CHAT_NAMES.get(chat) or snappeople.name_of(ACCOUNT_INDEX, chat)
    if name:
        return name
    try:
        from app.utils.db import connect_raw
        conn = connect_raw()
        try:
            row = conn.execute(f"SELECT username FROM message_log_{_db.WEB_TABLES[PLATFORM]} WHERE chat_id = ? ORDER BY ts DESC LIMIT 1",
                               (chat,)).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            CHAT_NAMES[chat] = row[0]
            return row[0]
    except Exception:
        pass
    return ""


_FRIEND_REQUESTS: list = []


async def _read_friend_requests() -> bool:
    """The requests waiting, off Snapchat's own requests panel, into _FRIEND_REQUESTS; False when the runner could not
    look (busy with a reply, or not up yet). Accepting them on its own is the runner's (snapchat.auto_add_friends)."""
    global _FRIEND_REQUESTS
    r = await _panel("friends", timeout=50.0)
    if not r.get("ok"):
        return False
    _FRIEND_REQUESTS = [{"id": str(q.get("name")), "username": str(q.get("username") or ""),
                         "display_name": str(q.get("name")), "avatar": str(q.get("avatar") or ""), "incoming": True,
                         "accept_at": None}
                        for q in r.get("requests") or [] if isinstance(q, dict) and q.get("name")]
    return True


# Calls, as Snapchat's chat list says them ("Calling", "In a call"): the Chats tab shows them as it does Discord's.
_CALLS_SINCE: dict = {}


def _on_call(chat: str, state: str) -> None:
    if state not in ("ringing", "in_call"):
        _CALLS_SINCE.pop(chat, None)
        _emit_chat({"t": "call", "uid": chat, "call": None})
        return
    since = _CALLS_SINCE.setdefault(chat, time.time())
    _emit_chat({"t": "call", "uid": chat, "call": {"state": state, "name": _name_for(chat) or chat, "since": since,
                                                    "avatar": snappeople.avatar_url(ACCOUNT_INDEX, chat)}})


async def _friend_add_cmd(cmd_id: str, username: str, text: str = "") -> None:
    """A friend request from the Chats tab, by username: found in Snapchat's own add friends search and added there.
    iMessage's: a conversation started with a phone number or an email, `text` its first message."""
    username = username.strip().lstrip("@")
    if not username:
        _write_result(cmd_id, {"ok": False, "reason": "Whose username?" if not IMESSAGE else "Whose number or email?"})
        return
    r = await _panel("add_friend", username=username, text=text, timeout=80.0)
    if r.get("ok"):
        log_system(f"Started a conversation with {username}, from the panel" if IMESSAGE
                   else f"Added {username} as a friend, from the panel")
    _write_result(cmd_id, {"ok": bool(r.get("ok")), "reason": r.get("reason", ""),
                           **({k: r[k] for k in ("chat", "service", "started") if k in r} if IMESSAGE else {})})


async def _friends_cmd(cmd_id: str) -> None:
    """Friend requests waiting on this account, read off Snapchat's own requests panel. While the runner is busy with a
    reply, the ones it last read: the panel asks every so often on its own, and a busy runner is not news."""
    fresh = await _read_friend_requests()
    _write_result(cmd_id, {"ok": True, "requests": _FRIEND_REQUESTS, **({} if fresh else {"stale": True})})


async def _friend_answer_cmd(cmd_id: str, name: str, accept: bool) -> None:
    """Accept a friend request, or turn it down, from the panel, by the name it shows."""
    if not name:
        _write_result(cmd_id, {"ok": False, "reason": "which request?"})
        return
    global _FRIEND_REQUESTS
    r = await _panel("friend", name=name, accept=accept, timeout=50.0)
    if r.get("ok"):
        _FRIEND_REQUESTS = [q for q in _FRIEND_REQUESTS if q["id"] != name]
        log_system(f"{'Accepted' if accept else 'Turned down'} {name}'s friend request, from the panel")
    _write_result(cmd_id, {"ok": bool(r.get("ok")), "reason": r.get("reason", "")})


# ── Pictures only where they can go ──────────────────────────────────────────
# TikTok's website gives the photo button to some accounts and not others (it is rolling out by region): the persona
# offers a picture only in a chat where the runner saw one.
_PHOTO_OK: dict = {}


def _picture_rule(chat_id: str) -> dict:
    if PHONE:
        return {"no_pictures": True}
    if PLATFORM == "tiktok" and not _PHOTO_OK.get(str(chat_id)):
        return {"no_pictures": True}
    return {}


# ── Comments under its own videos (TikTok) or posts (Instagram) ──────────────

async def _answer_comment(entry: dict) -> None:
    """A new comment under one of the account's videos or posts, answered in public: one short line, as a creator
    answers."""
    uid = str(entry.get("user_id") or "")
    name = str(entry.get("user_name") or uid)
    channel = str(entry.get("channel_id") or "comment")
    text = str(entry.get("content") or "").strip()
    if not text:
        return
    msg = IncomingMessage(
        platform=PLATFORM, user_id=uid, user_name=name, channel_id=channel, content=text,
        is_private=False, wait_time=0.0,
        extra={"account": ACCOUNT_INDEX, "no_pictures": True,
               "context": (f"PUBLIC COMMENT: this is a comment under one of your own {PLATFORM_NAME} "
                           f"{'posts' if PLATFORM == 'instagram' else 'videos'}, and your answer goes under it in "
                           "public, where everyone can read it. Answer the way a creator answers their comments: one "
                           "short, natural line. Nothing private, nothing you would only say in a DM.")},
    )
    try:
        async with _gen_lock(channel), _GEN_SLOTS:
            response = await generate_ai_response(msg)
    except Exception as e:
        log_error(f"{PLATFORM_NAME} comment", str(e))
        return
    if not response:
        return
    response = _humanize_reply(response).strip().split("\n")[0][:150]
    responses = _read_json(RESPONSES_FILE, {})
    responses = responses if isinstance(responses, dict) else {}
    responses[str(entry.get("id") or _uuid.uuid4())] = {
        "text": response, "chat": channel, "name": name, "kind": "comment",
        "video": entry.get("video") or "", "comment": entry.get("comment") or {},
        # A comment that named the account under someone else's video: answered from the runner's out tab.
        **({"mention": True} if entry.get("mention") else {}),
    }
    _write_json(RESPONSES_FILE, responses)
    _poke_node("response")
    log_system(f"Comment from {name}: {text[:80]} -> {response}")


# ── TikTok: co-hosting its LIVE ──────────────────────────────────────────────
# While the account is live, viewers' comments are answered in one short line, in the chat and out loud (the app's
# own voice, played by the panel's LIVE view and its OBS page), gifts thanked and follows welcomed, as the LIVE
# settings say (app/utils/livecohost.py). At most a few a minute, so a busy chat is not a wall of answers; the newest
# comment wins when there is more than that. When the chat goes quiet it can say something of its own.
_LIVE: dict = {"on": False, "feed": [], "pace": None, "names": [], "last": 0.0}
LIVE_AUDIO_DIR = Path(resource_path("cache/live_audio"))


def _live_cfg() -> dict:
    try:
        return ((load_config() or {}).get("tiktok") or {}).get("live") or {}
    except Exception:
        return {}


def _live_pace():
    from app.utils import livecohost
    if _LIVE["pace"] is None:
        _LIVE["pace"] = livecohost.Pace()
    return _LIVE["pace"]


def _live_state(on: bool) -> None:
    from app.utils import livecohost
    if on and not _LIVE["on"]:
        # A new LIVE: nobody in it answered yet, and what it is called, to know when the chat talks to it.
        _LIVE.update(pace=livecohost.Pace(), names=_own_names(), last=time.time())
    _LIVE["on"] = on
    _emit_chat({"t": "live_state", "live": on})
    log_system("The account went LIVE: co-hosting" if on else "The LIVE has ended")


def _attention(what: str) -> None:
    """Something the site put up that only a person can do (a puzzle, a code from its email): said where they will
    see it."""
    if what == "captcha":
        _emit_chat({"t": "attention", "what": "captcha"})
        _notify_telegram_error("Needs you", f"{PLATFORM_NAME} put up a check (a puzzle). "
                                            f"Solve it in the {PLATFORM_NAME} window.")
    elif what == "code":
        _emit_chat({"t": "attention", "what": "code"})
        _notify_telegram_error("Needs a code", f"{PLATFORM_NAME} sent a code to the account's email or phone. "
                                               "Type it on the Accounts page.")


async def _live_event(evt: dict) -> None:
    """A line in the LIVE's chat: shown in the panel, and answered as app/utils/livecohost.py says (the practice
    LIVE in Settings answers the same way)."""
    kind = str(evt.get("event") or "")
    name = str(evt.get("name") or "").strip()[:40] or "someone"
    text = str(evt.get("text") or "").strip()[:300]
    _LIVE["feed"] = (_LIVE["feed"] + [{"kind": kind, "name": name, "text": text, "at": time.time()}])[-60:]
    _emit_chat({"t": "live", "event": kind, "name": name, "text": text})
    if kind == "comment":
        _LIVE["last"] = time.time()
    await _live_answer(kind, name, text, str(evt.get("handle") or ""))


async def _live_answer(kind: str, name: str, text: str, handle: str = "") -> None:
    """The persona's line on its LIVE, when the settings say this is answered and the pace allows it: one at a time,
    so many a minute, a viewer not again too soon or too often, never sooner than tiktok.live.reply_delay. Typed in
    the chat and said out loud (the comment read out first, when that is on)."""
    from app.utils import livecohost
    cfg = livecohost.settings(_live_cfg())
    if not cfg["enabled"] or STATE["paused"]:
        return
    if not _LIVE["names"]:
        _LIVE["names"] = _own_names()
    if livecohost.skip_reason(kind, text, cfg, name, handle, _LIVE["names"]):
        return
    uid = livecohost.viewer_id(name, handle) if kind != "quiet" else ""
    pace = _live_pace()
    if pace.why_not(cfg, uid):
        return
    pace.busy = True
    started = time.time()
    try:
        async with _GEN_SLOTS:
            response = await livecohost.line(kind, name, text, uid=uid or livecohost.viewer_id("everyone"),
                                             platform=PLATFORM, account=ACCOUNT_INDEX, live=cfg)
        if not response:
            return
        # A moment, as a person takes, before the answer shows: the time the model took counts toward it.
        await asyncio.sleep(max(0.0, cfg["reply_delay"] - (time.time() - started)))
        pace.note(uid)
        _LIVE["last"] = time.time()
        rid = _uuid.uuid4().hex
        if cfg["chat"]:
            responses = _read_json(RESPONSES_FILE, {})
            responses = responses if isinstance(responses, dict) else {}
            responses[rid] = {"text": response, "chat": "live", "name": name, "kind": "live"}
            _write_json(RESPONSES_FILE, responses)
            _poke_node("response")
        audio = []
        if cfg["voice"]:
            try:
                LIVE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                chunks = await livecohost.voice(response, livecohost.reading(kind, name, text, cfg))
                for i, wav in enumerate(chunks):
                    name_i = f"{ACCOUNT_INDEX}_{rid}_{i}.wav"
                    (LIVE_AUDIO_DIR / name_i).write_bytes(wav)
                    audio.append(name_i)
            except Exception as e:
                log_error("TikTok LIVE voice", str(e))
        _emit_chat({"t": "live_say", "id": rid, "to": name if kind != "quiet" else "", "text": response,
                    "audio": audio, "event": kind, "comment": text if kind == "comment" else ""})
        log_system(f"LIVE: {name if kind != 'quiet' else 'everyone'} ({kind}) -> {response}")
    except Exception as e:
        log_error("TikTok LIVE", str(e))
    finally:
        pace.busy = False


async def _live_quiet_loop() -> None:
    """While the account is live and the chat has been quiet for tiktok.live.silence_seconds, a line of its own to
    everyone watching (only when tiktok.live.fill_silence is on)."""
    from app.utils import livecohost
    while True:
        await asyncio.sleep(5)
        if not _LIVE["on"]:
            continue
        try:
            cfg = livecohost.settings(_live_cfg())
            if cfg["enabled"] and cfg["fill_silence"] and time.time() - _LIVE["last"] >= cfg["silence_seconds"]:
                _LIVE["last"] = time.time()
                await _live_answer("quiet", "", "")
        except Exception as e:
            log_error("TikTok LIVE", str(e))


# ── TikTok: going out (the runner's out tab) ─────────────────────────────────
# What the runner does beside the inbox, each when switched on in Settings (tiktok_runner.js): the posts of the people
# it talks to and what it saw on For You are watched (app/utils/tiktokwatch.py) to talk about; a comment under someone's
# video is written here; a LIVE it visits gets a hello, an answer when someone there talks to it, and now and then a
# line of its own (app/utils/livecohost.py), never more than its settings allow.
_VISIT: dict = {"on": False, "host": "", "name": "", "why": "", "feed": [], "said": [], "busy": False, "since": 0.0,
                "greeted": False, "names": []}


def _visits_cfg() -> dict:
    try:
        return ((load_config() or {}).get("tiktok") or {}).get("visits") or {}
    except Exception:
        return {}


def _own_names() -> list:
    """What the account is called on TikTok, to know when a LIVE's chat talks to it: its @handle and its name."""
    names = [os.getenv(f"TIKTOK_USERNAME_{ACCOUNT_INDEX}", "")]
    try:
        from app.utils.paths import DATA_DIR
        me = json.loads((DATA_DIR / "config" / f"identity_tiktok_{ACCOUNT_INDEX}.json").read_text(encoding="utf-8"))
        names += [str(me.get("username") or ""), str(me.get("display_name") or "")]
    except (OSError, ValueError):
        pass
    return sorted({n for n in names if n})


def _visit_state(evt: dict) -> None:
    on = bool(evt.get("on"))
    host = str(evt.get("host") or "")[:40]
    if on:
        _VISIT.update(on=True, host=host, name=str(evt.get("name") or host)[:60], why=str(evt.get("why") or ""),
                      feed=[], said=[], since=time.time(), greeted=False, names=_own_names())
        log_system(f"Visiting @{host}'s LIVE")
    else:
        _VISIT["on"] = False
        log_system(f"Left @{host}'s LIVE")
    _emit_chat({"t": "visit_state", "on": on, "host": host, "name": _VISIT.get("name") or host, "why": _VISIT["why"]})


def _visit_line_kind(kind: str, text: str, now: float) -> str:
    """Whether the persona says something to this line of the LIVE it is visiting, and as what: "arrive" (its hello,
    once), "named" (someone talked to it), "chat" (now and then, a line of its own), "" (nothing)."""
    from app.utils import livecohost
    if kind == "arrive":
        return "" if _VISIT["greeted"] else "arrive"
    if kind != "comment":
        return ""
    if livecohost.addressed(text, _VISIT.get("names") or []):
        return "named"
    quiet_for = now - max(_VISIT["said"] or [_VISIT["since"]])
    return "chat" if quiet_for > 90 and random.random() < 0.07 else ""


async def _visit_event(evt: dict) -> None:
    """A line in the chat of the LIVE it is visiting: shown in the panel, and answered as _visit_line_kind says, within
    tiktok.visits.lines_per_5min."""
    from app.utils import livecohost
    kind = str(evt.get("event") or "")
    host = str(evt.get("host") or _VISIT["host"])[:40]
    name = str(evt.get("name") or "").strip()[:40] or "someone"
    text = str(evt.get("text") or "").strip()[:300]
    if kind != "arrive":
        _VISIT["feed"] = (_VISIT["feed"] + [{"kind": kind, "name": name, "text": text, "at": time.time()}])[-60:]
        _emit_chat({"t": "visit", "event": kind, "name": name, "text": text, "host": host})
    if STATE["paused"] or not _VISIT["on"] or host != _VISIT["host"]:
        return
    now = time.time()
    limit = max(0, int(_visits_cfg().get("lines_per_5min", 3) or 0))
    _VISIT["said"] = [t for t in _VISIT["said"] if now - t < 300]
    if _VISIT["busy"] or len(_VISIT["said"]) >= limit:
        return
    say = _visit_line_kind(kind, text, now)
    if not say:
        return
    if say == "arrive":
        _VISIT["greeted"] = True
    _VISIT["busy"] = True
    try:
        recent = [f"{f['name']}: {f['text']}" for f in _VISIT["feed"][-8:] if f.get("kind") == "comment"]
        # Nobody's memory: whatever it knows of someone from their DMs stays out of a public chat.
        async with _GEN_SLOTS:
            line = await livecohost.viewer_line(host, say, name, text, recent, uid=f"visit_{host}",
                                                platform=PLATFORM, account=ACCOUNT_INDEX)
        if not line:
            return
        _VISIT["said"].append(time.time())
        rid = _uuid.uuid4().hex
        responses = _read_json(RESPONSES_FILE, {})
        responses = responses if isinstance(responses, dict) else {}
        responses[rid] = {"text": line, "chat": "visit", "name": host, "kind": "visit_say", "host": host}
        _write_json(RESPONSES_FILE, responses)
        _poke_node("response")
        _emit_chat({"t": "visit_say", "id": rid, "to": name if say == "named" else "", "text": line, "host": host})
        log_system(f"In @{host}'s LIVE ({say}): {line}")
    except Exception as e:
        log_error("TikTok LIVE visit", str(e))
    finally:
        _VISIT["busy"] = False


async def _write_video_comment(url: str, why: str) -> tuple[str, dict | None]:
    """The persona's comment for a video or a post: it is watched first, then one short public line about it,
    written with nobody's memory. ("", None) when it could not be watched."""
    watcher, social = _social()
    if not watcher:
        return "", None
    w = await watcher.watch(url) if url else None
    if not w:
        return "", None
    author = str(w.get("author") or "someone")
    channel = f"video_{w.get('id') or 'x'}"
    lead = "the post" if PLATFORM == "instagram" and w.get("kind") != "reel" else "the video"
    msg = IncomingMessage(
        platform=PLATFORM, user_id=f"video_{author}", user_name=f"@{author}", channel_id=channel,
        content=watcher.summary(w, lead=lead, react=False), is_private=False, wait_time=0.0,
        extra={"account": ACCOUNT_INDEX, "no_pictures": True, "no_memory": True, "no_stats": True,
               "context": social.comment_context(why)},
    )
    async with _gen_lock(channel), _GEN_SLOTS:
        response = await generate_ai_response(msg)
    return social.clean_comment(_humanize_reply(response or "")), w


async def _answer_video_comment(entry: dict) -> None:
    """A comment under someone's video or post (one it was sent, or the newest of someone it talks to), for the
    runner to post within the day's comments. TikTok's come as "video_comment", Instagram's as "post_comment", and go
    back the same way."""
    url = str(entry.get("video") or "")
    why = str(entry.get("why") or "sent")
    kind = "post_comment" if entry.get("kind") == "post_comment" else "video_comment"
    try:
        text, w = await _write_video_comment(url, why)
    except Exception as e:
        log_error(f"{PLATFORM_NAME} comment", str(e))
        return
    if not w:
        log_system(f"Not commenting on {url or 'a video'}: it could not be watched")
        return
    if not text:
        return
    author = str(w.get("author") or "someone")
    channel = f"video_{w.get('id') or 'x'}"
    responses = _read_json(RESPONSES_FILE, {})
    responses = responses if isinstance(responses, dict) else {}
    responses[str(entry.get("id") or _uuid.uuid4())] = {"text": text, "chat": channel, "name": f"@{author}",
                                                        "kind": kind, "video": url}
    _write_json(RESPONSES_FILE, responses)
    _poke_node("response")
    what = "post" if PLATFORM == "instagram" else "TikTok"
    log_system(f"Comment for @{author}'s {what} ({why}): {text}")


# ── Instagram: a word back about someone's story, and its Note ───────────────

async def _answer_story(entry: dict) -> None:
    """A word back about a story of theirs it just watched (instagram.stories.reply): the story watched properly
    first, then one short line in their DMs, as a story reply is. Their conversation is its context, as any DM's is."""
    from app.utils import instagramwatch
    chat = str(entry.get("user_id") or "")
    name = str(entry.get("user_name") or chat)
    url = str(entry.get("story") or "")
    if not chat or not url:
        return
    try:
        w = await instagramwatch.watch(url, ACCOUNT_INDEX)
    except Exception:
        w = None
    if not w or not (w.get("seen") or w.get("said") or w.get("caption")):
        log_system(f"Not answering {name}'s story: it could not be watched")
        return
    note = instagramwatch.summary(w, lead="their story", react=False)
    msg = IncomingMessage(
        platform=PLATFORM, user_id=chat, user_name=name, channel_id=chat,
        content=f"[they posted a story] {note}", is_private=True, wait_time=0.0,
        extra={"account": ACCOUNT_INDEX, "no_pictures": True, "no_stats": True,
               "context": ("STORY REPLY: you just watched a story they put up, and you are answering it, the way "
                           "people answer a story: one short, natural line about what is in it (a reaction, a "
                           "question, a joke). It lands in your DMs with them, under their story. Do not describe the "
                           "story back to them.")},
    )
    try:
        async with _gen_lock(chat), _GEN_SLOTS:
            response = await generate_ai_response(msg)
    except Exception as e:
        log_error("Instagram story reply", str(e))
        return
    if not response:
        return
    text = _humanize_reply(response).strip().split("\n")[0][:300]
    responses = _read_json(RESPONSES_FILE, {})
    responses = responses if isinstance(responses, dict) else {}
    responses[str(entry.get("id") or _uuid.uuid4())] = {"text": text, "chat": chat, "name": name,
                                                        "kind": "story_reply", "story": url}
    _write_json(RESPONSES_FILE, responses)
    _poke_node("response")
    log_system(f"Answer to {name}'s story: {text}")


async def _write_note(entry: dict) -> None:
    """Its Instagram Note, written from its mood now (instagram.notes): the little line above its name in everyone's
    inbox. Written with nobody's memory, as a public line is."""
    from app.utils import instagramsocial
    msg = IncomingMessage(
        platform=PLATFORM, user_id="note", user_name="its Note", channel_id="note",
        content="[write your Instagram Note now]", is_private=False, wait_time=0.0,
        extra={"account": ACCOUNT_INDEX, "no_pictures": True, "no_memory": True, "no_stats": True,
               "context": instagramsocial.note_context(str(getattr(mood_mod, "current_mood", "") or ""))},
    )
    try:
        async with _gen_lock("note"), _GEN_SLOTS:
            response = await generate_ai_response(msg)
    except Exception as e:
        log_error("Instagram Note", str(e))
        return
    text = instagramsocial.clean_note(_humanize_reply(response or ""))
    if not text:
        return
    responses = _read_json(RESPONSES_FILE, {})
    responses = responses if isinstance(responses, dict) else {}
    responses[str(entry.get("id") or _uuid.uuid4())] = {"text": text, "chat": "note", "name": "its Note", "kind": "note"}
    _write_json(RESPONSES_FILE, responses)
    _poke_node("response")
    log_system(f"Instagram Note: {text}")


async def _voice_for(msg, response: str, content: str) -> tuple[str, float]:
    """A voice note of the reply, when they asked for one and the account can send it (instagram.watch.voice_notes,
    and a microphone in this chat; imessage.voice_notes): (its file, its length in seconds), or ("", 0) to send the
    words instead. The Instagram runner plays the file into Instagram's page through a fake microphone
    (instagram_runner.js); iMessage's sends it as a voice message, an MP3 BlueBubbles makes Apple's own."""
    if PLATFORM not in ("instagram", "imessage", "telegram") or not msg.extra.get("voice_ok"):
        return "", 0.0
    try:
        from app.utils.tts_trigger import is_tts_request
        if not is_tts_request(content):
            return "", 0.0
        cfg = load_config() or {}
        if not ((cfg.get("bot") or {}).get("tts") or {}).get("enabled", True):
            return "", 0.0
        from app.utils.tts import generate_voice_message
        chunks = await generate_voice_message(response.replace("\u2014", "").replace("\u2013", ""))
        if not chunks:
            return "", 0.0
        from app.utils.paths import DATA_DIR
        folder = DATA_DIR / "config" / "temp"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{P['key']}_{ACCOUNT_INDEX}_voice_{_uuid.uuid4().hex[:10]}.wav"
        path.write_bytes(chunks[0])
        # Its length from the WAV header: the runner holds the microphone open that long.
        import wave
        try:
            with wave.open(str(path), "rb") as wf:
                seconds = wf.getnframes() / float(wf.getframerate() or 1)
        except Exception:
            seconds = max(2.0, len(response) / 14.0)
        if IMESSAGE:
            mp3 = await asyncio.to_thread(_to_mp3, path)
            if not mp3:
                return "", 0.0
            path = mp3
        elif TELEGRAM:
            from app.utils.voice_send import _wav_to_ogg_opus
            ogg, secs = (await asyncio.to_thread(_wav_to_ogg_opus, path.read_bytes()))[:2]
            if not ogg:
                return "", 0.0
            path = path.with_suffix(".ogg")
            path.write_bytes(ogg)
            seconds = secs or seconds
        return str(path), round(seconds, 1)
    except Exception as e:
        log_error(f"{PLATFORM_NAME} voice note", str(e))
        return "", 0.0


# What the panel and Telegram can ask a runner to do out there: the runner's op for each, and how long it may take
# (a post uploads first). TikTok's and Instagram's, each under its own command name; which ones a platform has is
# its runner's business, and one it does not know says so.
_OUT_OPS = {
    "tiktok_posts": ("posts", 60.0), "tiktok_action": ("video", 120.0), "tiktok_visit": ("visit", 60.0),
    "tiktok_leave": ("leave", 20.0), "tiktok_foryou": ("foryou", 60.0), "tiktok_out": ("out", 20.0),
    "tiktok_post": ("post", 900.0),
    # Instagram: someone's posts and stories, liking or commenting on one, a story watched or answered, a Reels
    # session, its Note, following someone, and posting (a post, a reel or a story).
    "insta_posts": ("posts", 60.0), "insta_stories": ("stories", 60.0), "insta_action": ("media", 120.0),
    "insta_story": ("story", 90.0), "insta_reels": ("reels", 60.0), "insta_out": ("out", 20.0),
    "insta_post": ("post", 900.0), "insta_note": ("note", 60.0), "insta_code": ("code", 20.0),
    # Another account (or this one) asking the runner to open a post in its signed-in browser and save its media,
    # so Instagram links can be watched at all (app/utils/instagramwatch.py).
    "insta_fetch": ("fetch", 85.0),
    "insta_follow": ("follow", 60.0),
    # X: someone's posts, a post of its own, liking or reposting one, what is left of the day's allowances, the @s
    # it has not answered, a post and its replies, following someone, a link opened in its signed-in browser, and
    # the code X emails when it questions a login.
    "x_posts": ("posts", 60.0), "x_post": ("post", 900.0), "x_action": ("action", 120.0),
    "x_out": ("out", 20.0), "x_mentions": ("mentions", 60.0), "x_thread": ("thread", 60.0),
    "x_follow": ("follow", 60.0), "x_fetch": ("fetch", 85.0), "x_code": ("code", 20.0),
    # Reddit: the same again, with a comment of its own under somebody's post, and the subreddits it may take part
    # in with what each one wants of a post (its flairs, and whether it refuses the account at all).
    "reddit_posts": ("posts", 60.0), "reddit_post": ("post", 900.0), "reddit_action": ("action", 120.0),
    "reddit_out": ("out", 20.0), "reddit_inbox": ("inbox", 60.0), "reddit_thread": ("thread", 60.0),
    "reddit_comment": ("comment", 180.0), "reddit_subs": ("subs", 60.0),
    "reddit_follow": ("follow", 60.0), "reddit_fetch": ("fetch", 85.0), "reddit_code": ("code", 20.0),
}


async def _out_cmd(cmd_id: str, cmd: str, payload: dict) -> None:
    if not SOCIAL:
        _write_result(cmd_id, {"ok": False,
                               "reason": "Only a TikTok, Instagram, X or Reddit account does that"})
        return
    # tiktok_* on an Instagram account, or the other way round, is nothing this runner knows.
    if not cmd.startswith(f"{P['key']}_"):
        _write_result(cmd_id, {"ok": False, "reason": f"That is not something a {PLATFORM_NAME} account does"})
        return
    op, timeout = _OUT_OPS[cmd]
    kw: dict = {}
    if op in ("posts", "stories"):
        kw = {"chat": str(payload.get("user_id") or "")}
    elif op in ("video", "media", "action"):
        kw = {"url": str(payload.get("url") or ""), "action": str(payload.get("action") or ""),
              "text": str(payload.get("text") or "")[:150]}
    elif op == "thread":
        kw = {"url": str(payload.get("url") or "")}
    elif op in ("mentions", "inbox"):
        kw = {"since": str(payload.get("since") or "")}
    elif op == "subs":
        kw = {}
    elif op == "comment":
        # A comment under somebody's post, written by the panel rather than by the loop.
        kw = {"url": str(payload.get("url") or ""), "text": str(payload.get("text") or "")[:9000],
              "dry_run": bool(payload.get("dry_run"))}
    elif op == "story":
        kw = {"chat": str(payload.get("user_id") or ""), "action": str(payload.get("action") or "watch"),
              "text": str(payload.get("text") or "")[:300], "emoji": str(payload.get("emoji") or "")}
    elif op == "visit":
        kw = {"handle": str(payload.get("handle") or "")}
    elif op == "note":
        kw = {"text": str(payload.get("text") or "")[:60]}
    elif op == "code":
        kw = {"code": str(payload.get("code") or "")[:12]}
    elif op == "fetch":
        kw = {"url": str(payload.get("url") or "")}
    elif op == "follow":
        kw = {"username": str(payload.get("username") or "")}
    elif op == "post" and PLATFORM == "x":
        # X posts words, with pictures beside them if there are any: the other two post a file with a caption.
        thread = payload.get("thread") or []
        kw = {"text": str(payload.get("text") or "")[:2000],
              "images": [str(p) for p in (payload.get("images") or [])][:4],
              "thread": [str(t)[:2000] for t in thread][:10] if isinstance(thread, list) else [],
              "dry_run": bool(payload.get("dry_run"))}
    elif op == "post" and PLATFORM == "reddit":
        # A Reddit post is a title and a body, to a subreddit or to its own page, with a flair where one is wanted.
        kw = {"title": str(payload.get("title") or "")[:300],
              "text": str(payload.get("text") or "")[:20000],
              "link": str(payload.get("link") or ""),
              "images": [str(p) for p in (payload.get("images") or [])][:1],
              "where": str(payload.get("where") or ""), "flair": str(payload.get("flair") or "")[:64],
              "dry_run": bool(payload.get("dry_run"))}
    elif op == "post":
        kw = {"file": str(payload.get("file") or ""), "caption": str(payload.get("caption") or "")[:2000],
              "privacy": str(payload.get("privacy") or "everyone"), "dry_run": bool(payload.get("dry_run"))}
        if PLATFORM == "instagram":
            # A post, a reel or a story: Instagram's three ways of putting something up.
            kw["as"] = str(payload.get("as") or "post")
    r = await _panel(op, timeout=timeout, **kw)
    out = {k: v for k, v in r.items() if k not in ("kind", "id")}
    _write_result(cmd_id, out)
    if op in ("video", "media", "action") and out.get("ok") and not out.get("dry"):
        log_system(f"From the panel: {kw['action']} on {kw['url']}" + (f": {kw['text']}" if kw.get("text") else ""))
    if op == "post" and out.get("ok"):
        what = ("post" if PLATFORM in ("x", "reddit")
                else kw.get("as", "video") if PLATFORM == "instagram" else "video")
        log_system(f"Posted a {what} to {PLATFORM_NAME}" + (" (dry run)" if out.get("dry") else ""))


async def _wa_op_cmd(cmd_id: str, op: str, payload: dict) -> None:
    """One of WhatsApp's own asks, passed to its runner: what the connection is doing, its groups, somebody's
    status, a status of its own, how it shows itself, and a picture off a message. Shaped like Minecraft's
    _mc_op_cmd, because these are the same kind of thing: what only this platform has."""
    kw: dict = {}
    if op in ("group", "status"):
        kw = {"chat": str(payload.get("chat") or payload.get("user_id") or "")}
    elif op == "post_status":
        kw = {"text": str(payload.get("text") or "")[:700], "picture": str(payload.get("picture") or ""),
              "dry_run": bool(payload.get("dry_run"))}
    elif op == "presence":
        kw = {"online": bool(payload.get("online"))}
    elif op == "fetch":
        kw = {"url": str(payload.get("url") or ""), "key": str(payload.get("key") or "")}
    timeout = 900.0 if op == "post_status" else 60.0
    r = await _panel(op, timeout=timeout, **kw)
    _write_result(cmd_id, {k: v for k, v in r.items() if k not in ("kind", "id")})
    if op == "post_status" and r.get("ok") and not r.get("dry"):
        log_system("Put up a status on WhatsApp")

async def _comment_text_cmd(cmd_id: str, payload: dict) -> None:
    url = str(payload.get("url") or "")
    try:
        text, w = await _write_video_comment(url, str(payload.get("why") or "theirs"))
    except Exception as e:
        _write_result(cmd_id, {"ok": False, "reason": str(e)[:200]})
        return
    if not w:
        _write_result(cmd_id, {"ok": False, "reason": "That video could not be watched"})
        return
    _write_result(cmd_id, {"ok": bool(text), "text": text, "reason": "" if text else "The AI did not write one"})


async def _watch_quietly(url: str, said: str = "") -> None:
    """Something the runner came across (someone's newest post, one on For You or Reels, a story it watched),
    watched now so it is known when it comes up; `said` is logged once it is."""
    watcher, _ = _social()
    if not watcher:
        return
    try:
        w = await (watcher.watch(url, ACCOUNT_INDEX) if PLATFORM == "instagram" else watcher.watch(url))
    except Exception:
        w = None
    if w and said:
        log_system(f"{said}: {w.get('seen') or w.get('caption') or ''}"[:200])


def _on_posts(evt: dict) -> None:
    chat = str(evt.get("chat") or "")
    url = str(evt.get("newest") or "")
    if not url:
        return
    what = "post" if PLATFORM == "instagram" else "TikTok"
    said = f"{_name_for(chat) or chat} posted a new {what}" if evt.get("fresh") else ""
    _spawn_panel(_watch_quietly(url, said))
    if evt.get("fresh"):
        _emit_chat({"t": "posts", "uid": chat})


def _on_story(evt: dict) -> None:
    """A story of theirs the runner just watched: watched properly here too, so a DM with them can mention it."""
    chat = str(evt.get("chat") or "")
    url = str(evt.get("url") or "")
    if not url:
        return
    _spawn_panel(_watch_quietly(url, f"Saw {_name_for(chat) or chat}'s story"))
    _emit_chat({"t": "story", "uid": chat})


def _read_files(paths: list) -> list:
    out = []
    for p in paths:
        try:
            out.append(Path(p).read_bytes())
        except OSError:
            continue
    return out


async def _watch_sent(video_url, frames: list, has_still: bool = False) -> tuple:
    """A video the runner captured from a chat, watched: (the note for the model, whether it was watched). When it
    would not play and there is a still of it, no note: the still is what the model goes on, as before."""
    from app.utils import videowatch
    if not videowatch.settings()["enabled"]:
        return "", False
    w = None
    try:
        if isinstance(video_url, str) and video_url.startswith("file://"):
            w = await videowatch.watch_file(video_url[7:])
        if not (w and (w.get("seen") or w.get("said"))) and frames:
            w = await videowatch.watch_frames(await asyncio.to_thread(_read_files, [f[7:] for f in frames]))
    except Exception as e:
        log_error(f"{PLATFORM_NAME} video", str(e))
    watched = bool(w and (w.get("seen") or w.get("said")))
    if not watched and has_still:
        return "", False
    return videowatch.note(w), watched


def _tiktok_dm_context(chat_id: str) -> str:
    """What the persona knows of this person on this platform and what it saw there today, for a DM with them
    (TikTok's and Instagram's). Reads the runner's files: on a worker thread."""
    _, social = _social()
    if not social:
        return ""
    from app.utils import snappeople
    parts = []
    try:
        block = social.dm_context(ACCOUNT_INDEX, chat_id, snappeople.handle_of(chat_id))
        if block:
            parts.append(block)
        seen = social.seen_block(social.seen_pool(ACCOUNT_INDEX))
        if seen:
            parts.append(seen)
    except Exception as e:
        log_error(f"{PLATFORM_NAME} context", str(e))
    return "\n".join(parts)


def _share_for(chat_id: str):
    """Something to send them now they asked for one (<platform>.share.enabled): a TikTok from what a TikTok account
    of this persona saw on For You, a reel from what an Instagram one saw on Reels. (entry, words for the model) or
    (None, "")."""
    _, social = _social()
    if not social:
        return None, ""
    from app.utils import personas
    try:
        pid = personas.persona_of(f"{PLATFORM}_{ACCOUNT_INDEX}")
        pick = social.share_pick(social.pools_for(pid), f"{PLATFORM}_{ACCOUNT_INDEX}:{chat_id}")
        return (pick, social.share_context(pick)) if pick else (None, "")
    except Exception as e:
        log_error(f"{PLATFORM_NAME} share", str(e))
        return None, ""


# ── Nudges ───────────────────────────────────────────────────────────────────

def _nudge_cfg() -> dict:
    try:
        return (load_config().get("bot") or {}).get("nudge") or {}
    except Exception:
        return {}


def _note_unanswered(chat_id: str, content: str) -> None:
    """A message the bot is about to answer, kept until it has (bot.nudge on only), as Discord's add_unresponded."""
    if not content or not _nudge_cfg().get("enabled", False):
        return
    data = _read_json(UNANSWERED_FILE, {})
    data = data if isinstance(data, dict) else {}
    data[str(chat_id)] = {"content": content[:1000], "received_at": time.time(), "nudged": False}
    _write_json(UNANSWERED_FILE, data)


def _note_answered(chat_id: str) -> None:
    if not UNANSWERED_FILE.exists():
        return
    data = _read_json(UNANSWERED_FILE, {})
    if isinstance(data, dict) and str(chat_id) in data:
        data.pop(str(chat_id), None)
        _write_json(UNANSWERED_FILE, data)


async def _send_nudges(threshold: float) -> None:
    """Each message left unanswered longer than the threshold answered after all, once, while it is still the last
    word in the chat: the tone shifts with how long it has been (generate_nudge)."""
    from app.utils.ai import generate_nudge
    from app.utils.helpers import load_instructions
    from app.utils.memory import format_memory_for_prompt, get_memory
    from app.utils.mood import get_mood_prompt
    data = _read_json(UNANSWERED_FILE, {})
    if not isinstance(data, dict):
        return
    for chat_id, entry in list(data.items()):
        now = time.time()
        if not isinstance(entry, dict) or entry.get("nudged") or now - float(entry.get("received_at") or now) < threshold:
            continue
        name = _name_for(chat_id) or chat_id
        last = chatlog.conversation(LOG_ACCOUNT, chat_id, 1)
        if last and last[-1].get("mine"):
            log_system(f"Nudge skipped for {name}: the conversation was already answered")
            _note_answered(chat_id)
            continue
        if STATE["paused"] or chat_id in STATE["ignore_users"] or chat_id in STATE["paused_users"]:
            continue
        days = (now - float(entry["received_at"])) / 86400
        memory = engine._memory_cache.get(chat_id) or get_memory(chat_id) or {}
        instructions = load_instructions()
        if memory.get("__persona__"):
            instructions += f"\n\n[PERSONA OVERRIDE FOR THIS USER: {memory['__persona__']}]"
        if ((load_config().get("bot") or {}).get("mood") or {}).get("enabled", True):
            instructions += f"\n\n[Right now: {get_mood_prompt()}]"
        instructions += format_memory_for_prompt(memory)
        text = await generate_nudge(str(entry.get("content") or ""), days, instructions)
        if not text or engine.is_refusal(text):
            continue
        text = _humanize_reply(text)
        await asyncio.sleep(random.uniform(30, 120))           # as a person gets round to it
        _queue_outgoing(chat_id, text)
        fresh = _read_json(UNANSWERED_FILE, {})
        if isinstance(fresh, dict) and isinstance(fresh.get(chat_id), dict):
            fresh[chat_id]["nudged"] = True
            _write_json(UNANSWERED_FILE, fresh)
        engine.message_history.setdefault(f"{chat_id}-{chat_id}", []).append({"role": "assistant", "content": text})
        log_system(f"Nudge sent to {name} ({days:.1f}d elapsed)")


async def _nudge_loop() -> None:
    """Messages left unanswered for days answered after all (bot.nudge), within its hours, as the Discord side does."""
    await asyncio.sleep(random.uniform(300, 600))
    while True:
        cfg = _nudge_cfg()
        wait = 3600.0
        try:
            if cfg.get("enabled", False):
                hours = cfg.get("send_during_hours") or [10, 22]
                start, end = int(hours[0]), int(hours[1])
                hour = datetime.now().astimezone().hour
                # A window can run past midnight (22 to 2); start == end is no window at all.
                in_window = start <= hour < end if start <= end else (hour >= start or hour < end)
                if in_window:
                    await _send_nudges(float(cfg.get("threshold_days", 2)) * 86400)
                wait = max(0.25, float(cfg.get("check_interval_hours", 6))) * 3600
        except Exception as e:
            log_error("Snap nudge", str(e))
        await asyncio.sleep(wait)


def _last_theirs(chat_id: str):
    """Their newest message kept, for the row the Chats list shows."""
    for m in reversed(chatlog.conversation(LOG_ACCOUNT, chat_id, 12)):
        if not m.get("mine"):
            return m
    return None


# set when Node says new messages landed, the incoming loop waits on this instead of sleeping out its full interval
_wake_incoming = asyncio.Event()
# Connected Node clients, to poke when a reply is ready to send.
_node_writers: set = set()


async def _wake_server():
    """Accept Node's connection and turn its pokes into an asyncio.Event; never raises, worst case we keep polling."""
    async def handle(reader, writer):
        _node_writers.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except Exception:
                    continue          # a malformed poke is not worth dying over
                if msg.get("kind") == "incoming":
                    _wake_incoming.set()
                elif msg.get("kind") == "panel_result":
                    fut = _PANEL_WAITERS.get(str(msg.get("id") or ""))
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                elif msg.get("kind") == "transcript":
                    _on_transcript(msg)
                elif msg.get("kind") == "typing" and msg.get("chat"):
                    # Someone writing to the account right now, as Snapchat's chat list says: the same dots as Discord's.
                    _emit_chat({"t": "typing", "uid": str(msg["chat"])})
                elif msg.get("kind") in ("unsent", "edited") and msg.get("key"):
                    _on_changed(msg)
                elif msg.get("kind") == "call" and msg.get("chat"):
                    _on_call(str(msg["chat"]), str(msg.get("state") or ""))
                elif msg.get("kind") == "live":
                    _spawn_panel(_live_event(msg))
                elif msg.get("kind") == "live_state":
                    _live_state(bool(msg.get("live")))
                elif msg.get("kind") == "attention":
                    _attention(str(msg.get("what") or ""))
                # Going out: someone's newest post, a video seen on For You, a LIVE it is visiting.
                elif msg.get("kind") == "posts":
                    _on_posts(msg)
                elif msg.get("kind") == "seen_video" and msg.get("url"):
                    _spawn_panel(_watch_quietly(str(msg["url"])))
                elif msg.get("kind") == "story":
                    _on_story(msg)
                elif msg.get("kind") == "visit_state":
                    _visit_state(msg)
                elif msg.get("kind") == "visit":
                    _spawn_panel(_visit_event(msg))
                elif msg.get("kind") == "visit_said":
                    _emit_chat({"t": "visit_said", "host": str(msg.get("host") or ""), "text": str(msg.get("text") or "")})
                elif msg.get("kind") == "mc_event" and msg.get("event") == "died":
                    # It died in the game: mindcraft tells the persona itself, which reacts in its own words.
                    log_system(f"Died in Minecraft: {str(msg.get('text') or '')[:200]}")
                elif msg.get("kind") == "mc_event" and msg.get("event") == "auth":
                    step = str(msg.get("step") or "")
                    server = (_MC.get("target") or {}).get("host", "the server")
                    if step in ("refused", "needs-email"):
                        _notify_owner("Could not sign in", f"{server} would not take its password"
                                      if step == "refused" else f"{server} wants an email to register")
                    elif step == "signed-in":
                        log_system(f"Signed in on {server}")
                elif msg.get("kind") == "mc_event" and msg.get("event") in ("kicked", "join_failed"):
                    _spawn_panel(_mc_turned_away(str(msg.get("reason") or "")))
                elif msg.get("kind") == "mc_event" and msg.get("event") == "in_world":
                    _MC["in_world_at"] = time.time()
                elif msg.get("kind") == "mc_event" and msg.get("event") == "spawned":
                    # The player it really is: a Microsoft account's name is Microsoft's, and need not be the one
                    # it was added under. Its card's picture is that player's skin, drawn again when it differs.
                    real = str(msg.get("name") or "").strip()
                    if real and real.lower() != str(_MC.get("picture_for") or "").lower():
                        _MC["picture_for"] = real
                        _spawn_panel(_mc_picture(real))
        except Exception:
            pass
        finally:
            _node_writers.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    try:
        # A conversation comes over it as one line: room for a long one.
        server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=8 * 1024 * 1024)
    except Exception as e:
        log_system(f"{PLATFORM_NAME} wake channel unavailable ({e}); polling only")
        return

    port = server.sockets[0].getsockname()[1]
    try:
        PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(port), encoding="utf-8")
    except OSError as e:
        log_system(f"Could not publish the wake port ({e}); polling only")
        return
    log_system(f"{PLATFORM_NAME} wake channel listening on 127.0.0.1:{port}")
    async with server:
        await server.serve_forever()


def _poke_node(kind: str):
    """Ask Node to look at the files now rather than at its next poll."""
    if not _node_writers:
        return
    payload = (json.dumps({"kind": kind}) + "\n").encode("utf-8")
    for writer in list(_node_writers):
        try:
            writer.write(payload)
        except Exception:
            _node_writers.discard(writer)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return default
        return json.loads(text)
    except Exception:
        return default


def _write_json(path: Path, data):
    from app.utils.atomic import write_json_atomic
    write_json_atomic(path, data, indent=2)


def _append_response(msg_id: str, text: str, chat_id: str = None, name: str = None, react: str = "",
                     react_to: str = "", effect: str = "", fixed: str = ""):
    """Write an AI reply for the Node runner to send; the chat id rides along so it's self-routing even after a Node restart. iMessage's extras: `react`, a tapback the persona chose, on `react_to`, the message it answers; `effect`, the message effect it sends with; `fixed`, its words without the typo it was given, which it edits to a moment after sending."""
    if PHONE:
        _relay_answered(msg_id, text, chat_id, name)
        return
    responses = _read_json(RESPONSES_FILE, {})
    if chat_id:
        responses[msg_id] = {"text": text, "chat": str(chat_id), "name": name or str(chat_id)}
        if react:
            responses[msg_id].update(react=react, react_to=str(react_to or ""))
        if effect:
            responses[msg_id]["effect"] = effect
        if fixed:
            responses[msg_id]["fixed"] = fixed
    else:
        responses[msg_id] = text  # legacy string form
    _write_json(RESPONSES_FILE, responses)
    # file's already durable, this just saves Node the wait for its next drain tick; no-op if nothing's connected
    _poke_node("response")


def _queue_outgoing(chat_id: str, text: str, image: str = None):
    """Queue a proactive message (and/or picture Snap) for the Node runner."""
    if PHONE:
        log_system(f"[iMessage] Not sent to {CHAT_NAMES.get(chat_id, chat_id)}: through the iPhone it only answers")
        return
    outgoing = _read_json(OUTGOING_FILE, [])
    if not isinstance(outgoing, list):
        outgoing = []
    entry = {
        "id": str(_uuid.uuid4()),
        "chat": chat_id,
        "name": CHAT_NAMES.get(chat_id, chat_id),
        "message": text,
        "ts": time.time(),
    }
    if image:
        entry["image"] = image
    outgoing.append(entry)
    _write_json(OUTGOING_FILE, outgoing)


def _queue_voice(chat_id: str, path: str, seconds: float) -> None:
    """A voice note for the runner to send (Instagram): the file, and how long to hold the microphone open."""
    outgoing = _read_json(OUTGOING_FILE, [])
    if not isinstance(outgoing, list):
        outgoing = []
    outgoing.append({"id": str(_uuid.uuid4()), "chat": chat_id, "name": CHAT_NAMES.get(chat_id, chat_id),
                     "message": "", "voice": path, "seconds": seconds, "ts": time.time()})
    _write_json(OUTGOING_FILE, outgoing)


async def _queue_picture_if_any(msg, reply: str = "") -> None:
    """If the engine chose a selfie to send for this message, queue it as a Snap, with what the AI chooses to put on
    it (a caption, the time, an emoji...) on the accounts allowed to (bot.pictures.touches)."""
    path = msg.extra.get("picture_to_send")
    if path:
        from app.utils import looks
        from app.utils.db import get_all_picture_descriptions
        chat = msg.channel_id
        hist = engine.message_history.get(f"{chat}-{chat}", [])
        recent = [f"{'them' if t.get('role') == 'user' else 'me'}: {t.get('content')}" for t in hist[-8:] if t.get("content")]
        try:
            description = get_all_picture_descriptions().get(os.path.basename(path), "")
        except Exception:
            description = ""
        lang = (engine._lang_cache.get(msg.user_id) or {}).get("tag", "en")
        sent = await looks.touched_copy(path, description, recent, reply, f"{PLATFORM}_{ACCOUNT_INDEX}", lang,
                                        their_name=msg.user_name, platform=PLATFORM_NAME)
        _queue_outgoing(chat, "", image=sent)
        name = CHAT_NAMES.get(chat, chat)
        log_system(f"Queued picture send to {name}: {sent}")


def _humanize_reply(text: str) -> str:
    """Same output touch-ups as Discord, strip em-dashes, occasional typo."""
    try:
        typo_chance = load_config().get("bot", {}).get("typo_chance", 0.03)
    except Exception:
        typo_chance = 0.03
    return humanize(text, typo_chance)


async def _generate_call_decline(chat_id: str, name: str) -> str:
    """Craft a short, in-character chat that brushes off an incoming call."""
    from app.utils.helpers import load_instructions
    instr = load_instructions()
    persona = get_persona(chat_id)
    if persona:
        instr += f"\n\n[PERSONA OVERRIDE FOR THIS USER: {persona}]"
    # Reply in the language we've been speaking with them, if known.
    try:
        lang_tag = engine._lang_cache.get(chat_id, {}).get("tag", "en")
    except Exception:
        lang_tag = "en"
    from app.utils.languages import language_name
    lang_disp = language_name(lang_tag, "English")
    instr += (
        f"\n\n[INCOMING CALL: {name} is trying to voice/video call you on Snapchat right now, "
        f"but you can't or don't want to hop on a call. Reply with ONE short, casual chat message "
        f"that brushes it off so you avoid the call, e.g. 'cant talk rn sorry', 'im busy atm cant rn'. "
        f"Reply in {lang_disp}. One short sentence, not rude, no over-explaining.]"
    )
    try:
        return await generate_response("(politely decline the call in one short message)", instr, history=None)
    except Exception:
        return None


def _notify_telegram_error(title: str, detail: str):
    """Forward an error to the Telegram controller if notifications are enabled."""
    try:
        cfg = load_config()
        if not cfg.get("notifications", {}).get("telegram_error_notifications", False):
            return
        entries = _read_json(CMD_FILE, [])
        if not isinstance(entries, list):
            entries = []
        entries.append({
            "id": f"err_{time.time()}",
            "cmd": "send_error_notification",
            "payload": {"title": f"[{PLATFORM_NAME}] {title}", "detail": str(detail)[:1500]},
            "ts": time.time(),
        })
        _write_json(CMD_FILE, entries)
    except Exception:
        pass


# Python is the only writer of this ledger (Node just creates it empty), so the in-memory copy is authoritative. it used to read/parse/append/rewrite the file on every message, 8x per pass.
_processed_cache = None


def _processed_list() -> list:
    """The processed-id ledger, loaded from disk once."""
    global _processed_cache
    if _processed_cache is None:
        raw = _read_json(PROCESSED_FILE, [])
        _processed_cache = raw if isinstance(raw, list) else []
    return _processed_cache


def _mark_processed(msg_id: str):
    if PHONE:
        _relay_answered(msg_id, "")
    processed = _processed_list()
    if msg_id not in processed:
        processed.append(msg_id)
    if len(processed) > 500:
        del processed[:-500]
    # still written every mark: a mid-pass crash must not make the bot answer the same message twice
    _write_json(PROCESSED_FILE, processed)


# ── Incoming-message polling loop ────────────────────────────────────────────
async def process_incoming():
    """Read new messages and generate AI responses (respecting pause/ignore)."""
    log_system(f"{PLATFORM_NAME} bridge started, polling for messages")

    while True:
        # wake as soon as Node says something landed, fall back to the old interval if the socket's gone
        try:
            await asyncio.wait_for(_wake_incoming.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass
        _wake_incoming.clear()

        messages = _read_json(INCOMING_FILE, [])
        if not messages:
            continue

        processed = set(_processed_list())
        pending = [m for m in messages if m.get("id") not in processed]

        if not pending:
            continue

        for entry in pending:
            msg_id     = entry.get("id", "")
            user_id    = str(entry.get("user_id", ""))
            user_name  = entry.get("user_name", "unknown")
            channel_id = str(entry.get("channel_id", user_id))
            content    = entry.get("content", "").strip()
            ts         = float(entry.get("ts", time.time()))
            image_url  = entry.get("image_url")  # optional
            audio_url  = entry.get("audio_url")  # optional (voice message)

            # A comment under one of the account's own videos (TikTok): answered in public, apart from the DMs.
            if entry.get("kind") == "comment":
                _mark_processed(msg_id)
                if not (STATE["paused"] or user_id in STATE["ignore_users"]):
                    _spawn_panel(_answer_comment(entry))
                continue
            # A comment to write under someone else's video or post (<platform>.engage): watched first, then written.
            if entry.get("kind") in ("video_comment", "post_comment"):
                _mark_processed(msg_id)
                if not (STATE["paused"] or user_id in STATE["ignore_users"]):
                    _spawn_panel(_answer_video_comment(entry))
                continue
            # A word back about a story of theirs it just watched (Instagram).
            if entry.get("kind") == "story_reply":
                _mark_processed(msg_id)
                if not (STATE["paused"] or user_id in STATE["paused_users"] or user_id in STATE["ignore_users"]):
                    _spawn_panel(_answer_story(entry))
                continue
            # Its Note, due again (Instagram).
            if entry.get("kind") == "note":
                _mark_processed(msg_id)
                if not STATE["paused"]:
                    _spawn_panel(_write_note(entry))
                continue

            if user_id:
                CHAT_NAMES[user_id] = user_name
            if "photo" in entry:
                _PHOTO_OK[channel_id] = bool(entry.get("photo"))

            # The platform's own chats: there is nobody there to answer.
            if (user_name or "").strip().lower() in _SYSTEM_CHATS:
                _mark_processed(msg_id)
                continue

            # incoming call: Node already clicked "Not Now"; send a casual "can't talk" chat so the bot dodges it naturally
            if entry.get("call"):
                if (user_id in STATE["ignore_users"] or STATE["paused"]
                        or user_id in STATE["paused_users"]):
                    _mark_processed(msg_id)
                    continue
                try:
                    async with _gen_lock(channel_id), _GEN_SLOTS:
                        decline = await _generate_call_decline(channel_id, user_name)
                except Exception as e:
                    log_error("Snap call decline", str(e))
                    decline = None
                if decline:
                    decline = _humanize_reply(decline)
                    log_system(f"Declined call from {user_name} → {decline}")
                    _append_response(msg_id, decline, channel_id, user_name)
                _mark_processed(msg_id)
                continue

            # Resolve a local snap screenshot (file://) into a base64 data URL
            if image_url and image_url.startswith("file://"):
                local_path = image_url[7:]
                try:
                    with open(local_path, "rb") as img_f:
                        img_bytes = img_f.read()
                    mime = mimetypes.guess_type(local_path)[0] or "image/jpeg"
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    image_url = f"data:{mime};base64,{b64}"
                    # Screenshot is kept in config/temp (pruned by _cleanup_loop).
                except Exception as e:
                    log_error("Snap image read error", str(e))
                    image_url = None

            # transcribe voice (file://) with Whisper and fold it into the text, same as Discord
            if audio_url and audio_url.startswith("file://"):
                local_path = audio_url[7:]
                try:
                    with open(local_path, "rb") as af:
                        audio_bytes = af.read()
                    transcript = await transcribe_voice(audio_bytes, filename=os.path.basename(local_path))
                    if transcript:
                        vm = f"[voice message: {transcript}]"
                        content = f"{content} {vm}".strip() if content else vm
                        log_system(f"Transcribed voice from {user_name}: {transcript}")
                except Exception as e:
                    log_error("Snap voice read error", str(e))

            # A video they sent (a video snap, a video in the chat), watched: the file itself when the runner got it,
            # else frames it took off the page (app/utils/videowatch.py). Watched, the still of it is not needed.
            video_url = entry.get("video_url")
            frames = [f for f in (entry.get("frames") or []) if isinstance(f, str) and f.startswith("file://")]
            if (isinstance(video_url, str) and video_url.startswith("file://")) or frames:
                note, watched = await _watch_sent(video_url, frames, has_still=bool(image_url))
                if note:
                    content = f"{content}\n{note}".strip() if content else note
                if watched:
                    image_url = None

            if not content and not image_url:
                _mark_processed(msg_id)
                continue

            # Drop stale messages
            age = time.time() - ts
            if age > MAX_MSG_AGE:
                log_system(f"Skipping stale message from {user_name} ({int(age)}s old)")
                _set_state(channel_id, "skipped", reason="it was already old when the bot saw it")
                _mark_processed(msg_id)
                continue

            # pause/ignore gating: paused/ignored messages are still recorded for /reply later, just no auto-respond
            if user_id in STATE["ignore_users"]:
                _mark_processed(msg_id)
                continue

            if STATE["paused"] or user_id in STATE["paused_users"]:
                engine.add_user_message(user_id, channel_id, content or P["photo"])
                log_system(f"Paused - recorded message from {user_name} for later /reply")
                if user_id in STATE["paused_users"]:
                    _set_state(channel_id, "skipped", reason="you paused replies to them")
                _mark_processed(msg_id)
                continue

            # The chance of leaving a message unanswered, as on Discord: kept in the conversation, so the next reply
            # still knows it was said, and Reply answers it.
            try:
                _skip = float((load_config().get("bot") or {}).get("ignore_chance") or 0)
            except Exception:
                _skip = 0.0
            if _skip > 0 and random.random() < _skip:
                engine.add_user_message(user_id, channel_id, content or P["photo"])
                log_system(f"Ignored message from {user_name} (chance skip)")
                _set_state(channel_id, "skipped", reason="left unanswered on purpose (the ignore chance)")
                _mark_processed(msg_id)
                continue

            _seed_history(channel_id, ts)

            # Their TikTok, and what it saw there today (a TikTok DM); a TikTok to send them when they asked for one.
            context = ""
            if SOCIAL and not entry.get("group"):
                context = await asyncio.to_thread(_tiktok_dm_context, channel_id)
            share = None
            _, _social_mod = _social()
            _asks = getattr(_social_mod, "wants_reel", None) or getattr(_social_mod, "wants_tiktok", None)
            if (not entry.get("group") and _social_mod and _social_mod.share_settings() and _asks(content)):
                share, share_words = await asyncio.to_thread(_share_for, channel_id)
                if share:
                    context = (context + "\n" + share_words).strip()

            msg = IncomingMessage(
                platform=PLATFORM,
                user_id=user_id,
                user_name=user_name,
                channel_id=channel_id,
                content=content,
                image_url=image_url,
                is_private=not entry.get("group"),  # a TikTok group is answered only when called by name
                wait_time=age,
                # So the reply is logged against this account, not just "Snapchat".
                extra={"account": ACCOUNT_INDEX, **_picture_rule(channel_id),
                       # Only a shared video's cover (TikTok): the engine drops it when the video itself was watched.
                       **({"tiktok_cover": image_url} if entry.get("cover") and image_url else {}),
                       # A voice note can go back here (Instagram, its microphone in this chat and voice notes on).
                       **({"voice_ok": True} if entry.get("voice") else {}),
                       # iMessage's tapbacks, which the persona may tap as Discord's react (engine.tapback_rules),
                       # and its message effects for a big moment (engine.effect_rules).
                       **({"tapbacks": list(SNAP_REACTIONS)}
                          if IMESSAGE and _imessage_cfg().get("tapbacks", True) and entry.get("react_to") else {}),
                       **({"effects": True} if IMESSAGE and not PHONE and _imessage_cfg().get("effects", True)
                          else {}),
                       **({"context": context} if context else {}),
                       # A look online for this reply (app/utils/web/lookup.py): the chat says so meanwhile. Not for
                       # the iPhone relay, which waits a fixed time for its answer.
                       **({"no_web": True} if entry.get("relay") else
                          {"on_lookup": lambda task, _c=channel_id: _set_state(_c, "looking" if task else "writing",
                                                                                 reason=task)})},
            )

            log_incoming(user_name, f"{PLATFORM_NAME} DM", PLATFORM_NAME, content)

            began = time.time()
            _note_unanswered(channel_id, content)
            _set_state(channel_id, "writing")
            try:
                async with _gen_lock(channel_id), _GEN_SLOTS:
                    response = await generate_ai_response(msg)
            except Exception as e:
                # A model that will not load is said once while it is left alone (app/utils/ai.py), not again for
                # every message, nor sent to Telegram each time; the chat says why.
                wont = isinstance(e, ModelWontLoad)
                if not wont:
                    log_error("Snap AI Error", str(e))
                    _notify_telegram_error("AI generation error", f"{user_name}: {e}")
                _set_state(channel_id, "failed", reason=str(e) if wont else "no reply was generated, see the log")
                _mark_processed(msg_id)
                continue

            # A tapback the persona chose (iMessage), on the message it answers, and an effect it sends with.
            react = str((msg.extra or {}).get("react") or "")
            effect = str((msg.extra or {}).get("effect") or "")
            fixed = ""
            if response and _held_back(channel_id, user_name, began):
                response = None
            elif response:
                clean = response
                response = _humanize_reply(response)
                # A typo the touch-ups gave it, fixed a moment after it is sent, as people do on an iPhone (iMessage's
                # edit, through BlueBubbles' Private API): half the time.
                if IMESSAGE and not PHONE and _imessage_cfg().get("fix_typos", True):
                    plain = humanize(clean, 0)
                    if plain != response and random.random() < 0.5:
                        fixed = plain
                log_response(user_name, response)
                separator()
                # A person reads the message and thinks before answering. The
                # Node side adds the send gap, this is the read/think part.
                think = random.uniform(3.0, 10.0)
                if random.random() < 0.12:
                    think += random.uniform(20.0, 90.0)
                if PHONE:
                    # The phone's request waits for this, and Shortcuts gives up on one after a minute.
                    think = min(think, random.uniform(1.5, 4.5))
                _set_state(channel_id, "cooldown", eta=time.time() + think)
                await asyncio.sleep(think)
                if not _held_back(channel_id, user_name, began):
                    voice, seconds = await _voice_for(msg, response, content)
                    if voice:
                        # Asked for a voice note, on an account that can send one: the reply goes as that.
                        _queue_voice(channel_id, voice, seconds)
                        log_system(f"Sending {user_name} a voice note ({seconds:.0f}s)")
                    else:
                        _append_response(msg_id, response, channel_id, user_name, react=react,
                                         react_to=str(entry.get("react_to") or ""), effect=effect, fixed=fixed)
                    await _queue_picture_if_any(msg, response)
                    if share and _social_mod:
                        # The TikTok, or the reel, as its own message after the reply.
                        _queue_outgoing(channel_id, share["url"])
                        await asyncio.to_thread(_social_mod.mark_shared, f"{PLATFORM}_{ACCOUNT_INDEX}:{channel_id}",
                                                str(share.get("id") or ""))
                        what = "a reel" if PLATFORM == "instagram" else "a TikTok"
                        log_system(f"Sending {user_name} {what}: {share['url']}")
                    _handed_over(channel_id)
            elif response == "" and react:
                # Only a tapback (iMessage): nothing said, the tap is the answer.
                if not _held_back(channel_id, user_name, began):
                    await asyncio.sleep(random.uniform(2.0, 6.0))
                    _append_response(msg_id, "", channel_id, user_name, react=react,
                                     react_to=str(entry.get("react_to") or ""))
                    log_response(user_name, f"[tapback only] {react}")
                    separator()
                    _handed_over(channel_id)
            elif channel_id not in STATE["ignore_users"]:
                log_system(f"No response generated for {user_name}")
                _set_state(channel_id, "failed", reason="no reply was generated, see the log")

            _mark_processed(msg_id)

        # re-read before pruning: Node keeps appending while we generate, and writing back our stale copy would drop the new ones. processed ledger needs no re-read, we're its only writer.
        fresh_processed = set(_processed_list())
        current = _read_json(INCOMING_FILE, [])
        if not isinstance(current, list):
            current = []
        remaining = [m for m in current if m.get("id") not in fresh_processed]
        _write_json(INCOMING_FILE, remaining)

# ── Telegram command IPC loop ────────────────────────────────────────────────
def _write_result(cmd_id: str, data: dict):
    results = _read_json(RESULT_FILE, {})
    if not isinstance(results, dict):
        results = {}
    results[cmd_id] = data
    _write_json(RESULT_FILE, results)


# Commands that only make sense on Discord, acknowledged with a clear message.
_DISCORD_ONLY = {
    "toggle_dm", "toggle_gc", "toggle_server", "toggle_active",
    "voice_join", "voice_leave", "voice_autojoin",
    "set_status", "set_bio", "set_pfp", "set_banner", "add_friend",
}


# Summaries being generated; asyncio only holds tasks weakly.
_SUMMARY_TASKS: set = set()


def _quiet_until() -> float | None:
    """While inside snapchat.quiet_hours ("start-end", this computer's clock), when the runner reads but does not send:
    when they end, as a Unix time. None outside them."""
    import re as _re
    from datetime import timedelta
    raw = os.environ.get(f"{P['env']}_QUIET_HOURS", "")
    if not raw:
        try:
            raw = str((load_config().get(PLATFORM) or {}).get("quiet_hours") or "")
        except Exception:
            raw = ""
    m = _re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", raw.strip())
    if not m:
        return None
    start, end = int(m.group(1)) % 24, int(m.group(2)) % 24
    now = datetime.now()
    if not (start <= now.hour < end if start <= end else (now.hour >= start or now.hour < end)):
        return None
    until = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if until <= now:
        until += timedelta(days=1)
    return until.timestamp()


def _quiet_now() -> bool:
    return _quiet_until() is not None


def _handed_over(chat_id: str) -> None:
    """A reply given to the runner to send: typing it out now, or, in the quiet hours, waiting for them to end."""
    quiet_end = _quiet_until()
    if quiet_end:
        _set_state(chat_id, "cooldown", eta=quiet_end)
    else:
        _set_state(chat_id, "sending")


def _ignored(uid: str) -> None:
    """Bot off for them: a reply lined up for them stops too, and the tab is told, as on Discord."""
    _drop_lined_up(uid, by_hand=False) or _drop_outgoing(uid)
    task = _REPLY_TASKS.get(uid)
    if task and not task.done():
        task.cancel()
    _set_state(uid, "skipped", reason="you are ignoring them")
    _emit_chat({"t": "ignored", "uid": uid, "ignored": True})


def _unignored(uid: str) -> None:
    if (_REPLY_STATE.get(uid) or {}).get("state") == "skipped":
        _clear_state(uid)
    _emit_chat({"t": "ignored", "uid": uid, "ignored": False})


async def _handle_command(cmd: str, payload: dict, cmd_id: str) -> None:
    """Execute a single Telegram command and write its result."""

    if cmd in _DISCORD_ONLY:
        _write_result(cmd_id, {"ok": False, "unsupported": True,
                               "reason": f"Not supported on {PLATFORM_NAME}."})
        return

    if cmd == "pause":
        STATE["paused"] = not STATE["paused"]
        _emit_chat({"t": "meta", "paused": STATE["paused"], "cooldown_until": 0})
        _write_result(cmd_id, {"paused": STATE["paused"]})

    elif cmd == "wipe":
        engine.message_history.clear()
        _write_result(cmd_id, {"ok": True})

    elif cmd == "pauseuser":
        STATE["paused_users"].add(str(payload["user_id"]))
        _write_result(cmd_id, {"ok": True})

    elif cmd == "unpauseuser":
        STATE["paused_users"].discard(str(payload["user_id"]))
        _write_result(cmd_id, {"ok": True})

    elif cmd == "ignore_toggle":
        uid = str(payload["user_id"])
        if uid in STATE["ignore_users"]:
            STATE["ignore_users"].discard(uid)
            remove_ignored_user_snap(uid)
            _unignored(uid)
            _write_result(cmd_id, {"ok": True, "ignored": False})
        else:
            STATE["ignore_users"].add(uid)
            add_ignored_user_snap(uid)
            _ignored(uid)
            _write_result(cmd_id, {"ok": True, "ignored": True})

    elif cmd == "ignore_add":
        uid = str(payload["user_id"])
        STATE["ignore_users"].add(uid)
        add_ignored_user_snap(uid)
        _ignored(uid)
        _write_result(cmd_id, {"ok": True})

    elif cmd == "ignore_remove":
        uid = str(payload["user_id"])
        STATE["ignore_users"].discard(uid)
        remove_ignored_user_snap(uid)
        _unignored(uid)
        _write_result(cmd_id, {"ok": True})

    elif cmd == "persona_set":
        uid = str(payload["user_id"])
        set_persona(uid, payload["persona"])
        engine._memory_cache.setdefault(uid, {})["__persona__"] = payload["persona"]
        _write_result(cmd_id, {"ok": True})

    elif cmd == "persona_clear":
        uid = str(payload["user_id"])
        clear_persona(uid)
        engine._memory_cache.get(uid, {}).pop("__persona__", None)
        _write_result(cmd_id, {"ok": True})

    elif cmd == "persona_get":
        uid = str(payload["user_id"])
        _write_result(cmd_id, {"persona": get_persona(uid)})

    elif cmd == "mood_set":
        mood_mod.current_mood = payload["mood"]
        _write_result(cmd_id, {"ok": True})

    elif cmd == "mood_get":
        _write_result(cmd_id, {"mood": mood_mod.current_mood})

    elif cmd == "instructions_update":
        # engine reads instructions from disk on every reply and TG already wrote the file, nothing to hold
        _write_result(cmd_id, {"ok": True})

    elif cmd == "memory_changed":
        # Someone's memory was edited in the panel: read again on their next message.
        engine._memory_cache.pop(str(payload.get("user_id")), None)
        _write_result(cmd_id, {"ok": True})

    elif cmd == "config_update":
        # most config is read live from disk; the few import-time caches kick in on restart
        _write_result(cmd_id, {"ok": True})

    elif cmd == "reload":
        # "reload cogs" is Discord-only; here we just confirm the engine picks up fresh instructions/config
        _write_result(cmd_id, {"ok": True, "errors": []})

    elif cmd == "get_status":
        status = {
            "paused": STATE["paused"],
            "mood": mood_mod.current_mood,
            "active_channels": len(CHAT_NAMES),
            "ignored_users": len(STATE["ignore_users"]),
            # Inside its quiet hours it reads but does not send: the panel says so, as it does Discord's night hours.
            "night": _quiet_now(),
            # A TikTok account's own counts, as its profile shows them (its card says them as Discord's says servers).
            **_profile_counts(),
        }
        if MINECRAFT and _node_writers:
            # Where it is and what it is doing in the game, as the MindServer last told its runner.
            r = await _panel("state", timeout=4.0)
            if r.get("ok"):
                status["game"] = {"in_game": bool(r.get("in_game")), "state": r.get("state"),
                                  "server": f"{_MC.get('slot', {}).get('host', '')}:{_MC.get('slot', {}).get('port', '')}"}
        if IMESSAGE and _node_writers:
            # The Mac it reads through: BlueBubbles' address, whether its live feed is up, what its Private API allows.
            r = await _panel("state", timeout=4.0)
            if r.get("ok"):
                status["imessage"] = {k: r.get(k) for k in ("server", "live", "private_api", "helper", "account",
                                                            "macos", "bluebubbles")}
        if WHATSAPP and _node_writers:
            # Its connection: linked or not, the number it is linked as, and what it is doing.
            r = await _panel("state", timeout=4.0)
            if r.get("ok"):
                status["whatsapp"] = {k: r.get(k) for k in ("linked", "number", "name", "live", "since")}
        _write_result(cmd_id, status)

    elif cmd == "get_leaderboard":
        import re as _re
        from datetime import datetime as _dt
        filter_str = payload.get("filter")
        since_ts = None
        filter_label = "all time"
        if filter_str:
            m = _re.fullmatch(r"(\d+(?:\.\d+)?)\s*([hdwm])", filter_str.strip().lower())
            if m:
                amount, unit = float(m.group(1)), m.group(2)
                seconds_map = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000}
                since_ts = time.time() - amount * seconds_map[unit]
                unit_names = {"h": "hour", "d": "day", "w": "week", "m": "month"}
                n = int(amount) if amount == int(amount) else amount
                filter_label = f"last {n} {unit_names[unit]}{'s' if n != 1 else ''}"
        rows = get_leaderboard_snap(limit=20, since=since_ts)
        serialized = [{
            "username": row["username"],
            "message_count": row["message_count"],
            "first_seen_fmt": _dt.fromtimestamp(row["first_seen"]).strftime("%d %b %Y"),
        } for row in rows]
        _write_result(cmd_id, {"rows": serialized, "filter_label": filter_label})

    elif cmd == "reply_check":
        users_out = []
        for chat_id, name in list(CHAT_NAMES.items()):
            if chat_id in STATE["ignore_users"]:
                continue
            if not engine.has_pending(chat_id, chat_id):
                continue
            hist = engine.message_history.get(f"{chat_id}-{chat_id}", [])
            pending = [e["content"] for e in reversed(hist) if e["role"] == "user"]
            # only the trailing unanswered run
            trailing = []
            for e in reversed(hist):
                if e["role"] != "user":
                    break
                trailing.insert(0, e["content"])
            last = trailing[-1] if trailing else (pending[0] if pending else "")
            snippet = (last[:60] + "…") if len(last) > 60 else last
            row = {
                "id": chat_id,
                "name": name,
                "snippet": snippet,
                "count": len(trailing),
                "avatar": snappeople.avatar_url(ACCOUNT_INDEX, chat_id),
            }
            last = _last_theirs(chat_id)
            if last:
                row.update(ts=last["ts"], mid=last["mid"], text=last.get("text") or snippet)
            if _REPLY_STATE.get(chat_id):
                row["state"] = _REPLY_STATE[chat_id]
            users_out.append(row)
        # Being answered right now, or left unanswered on purpose: on the list with where their reply is, as on Discord.
        listed = {u["id"] for u in users_out}
        for chat_id, st in list(_REPLY_STATE.items()):
            # One the runner never got to send (its chat gone from the list, say) is not "typing" a quarter of an
            # hour later.
            if (st.get("state") in ("writing", "cooldown", "sending") and time.time() - float(st.get("since") or 0) > 900
                    and float(st.get("eta") or 0) < time.time()):
                _REPLY_STATE.pop(chat_id, None)
                continue
            if chat_id in listed or chat_id in STATE["ignore_users"]:
                continue
            last = _last_theirs(chat_id)
            words = str((last or {}).get("text") or "")
            row = {"id": chat_id, "name": _name_for(chat_id) or chat_id, "count": 1, "state": st,
                   "snippet": (words[:60] + "…") if len(words) > 60 else words,
                   "avatar": snappeople.avatar_url(ACCOUNT_INDEX, chat_id)}
            if last:
                row.update(ts=last["ts"], mid=last["mid"], text=words)
            users_out.append(row)
        _write_result(cmd_id, {"users": users_out, "paused": STATE["paused"]})

    elif cmd == "chat_history" and MINECRAFT:
        # The game keeps no history to read back: the chat log is the conversation.
        chat = str(payload.get("user_id") or "")
        limit = max(5, min(200, int(payload.get("limit") or 25)))
        _write_result(cmd_id, {"ok": True, "messages": chatlog.conversation(LOG_ACCOUNT, chat, limit)})

    elif cmd == "send_message" and MINECRAFT:
        _spawn_panel(_mc_send_cmd(cmd_id, payload))

    elif cmd == "mc_join_server":
        if not MINECRAFT:
            _write_result(cmd_id, {"ok": False, "unsupported": True, "reason": f"Not supported on {PLATFORM_NAME}."})
        else:
            _spawn_panel(_mc_join_cmd(cmd_id, payload))

    elif cmd in ("mc_state", "mc_tell", "mc_leave", "mc_join"):
        if not MINECRAFT:
            _write_result(cmd_id, {"ok": False, "unsupported": True, "reason": f"Not supported on {PLATFORM_NAME}."})
        else:
            _spawn_panel(_mc_op_cmd(cmd_id, cmd[3:], payload))

    elif cmd in ("wa_state", "wa_groups", "wa_group", "wa_status", "wa_post_status", "wa_presence", "wa_fetch"):
        if not WHATSAPP:
            _write_result(cmd_id, {"ok": False, "unsupported": True, "reason": f"Not supported on {PLATFORM_NAME}."})
        else:
            _spawn_panel(_wa_op_cmd(cmd_id, cmd[3:], payload))

    elif MINECRAFT and cmd in ("react", "friends_pending", "friend_accept", "friend_decline", "friend_add"):
        _write_result(cmd_id, {"ok": False, "unsupported": True, "reason": "Not something Minecraft has."})

    elif cmd == "chat_history":
        # Off the command loop: the runner reads it between its own steps, which can take a few seconds.
        _spawn_panel(_history_cmd(cmd_id, payload))

    elif cmd == "guilds":
        # Discord's servers, asked of a bridged platform. Only Telegram has anything of the kind (its groups and the
        # channels it follows); the rest say so, and the Chats tab leaves the choice out for them.
        if not TELEGRAM:
            _write_result(cmd_id, {"ok": True, "guilds": [], "unsupported": True})
        else:
            _spawn_panel(_guilds_cmd(cmd_id, payload))

    elif cmd == "friends_pending":
        _spawn_panel(_friends_cmd(cmd_id))

    elif cmd in ("friend_accept", "friend_decline"):
        _spawn_panel(_friend_answer_cmd(cmd_id, str(payload.get("user_id") or ""), cmd == "friend_accept"))

    elif cmd == "relay":
        if not PHONE:
            _write_result(cmd_id, {"ok": False, "reason": "This iMessage account reads through a Mac, not a phone"})
        else:
            _spawn_panel(_relay_cmd(cmd_id, payload))

    elif cmd == "friend_add":
        _spawn_panel(_friend_add_cmd(cmd_id, str(payload.get("username") or ""), str(payload.get("text") or "")))

    elif cmd == "send_message":
        _spawn_panel(_send_cmd(cmd_id, payload))

    elif cmd == "react":
        _spawn_panel(_react_cmd(cmd_id, payload))

    elif cmd in _OUT_OPS:
        # Going out, asked for by the panel or Telegram: the runner does it in its out tab (tiktok_runner.js).
        _spawn_panel(_out_cmd(cmd_id, cmd, payload))

    elif cmd == "insta_comment_text":
        _spawn_panel(_comment_text_cmd(cmd_id, payload))
    elif cmd == "tiktok_comment_text":
        # A comment for a video, written by the persona for the panel to show (and edit) before it goes.
        _spawn_panel(_comment_text_cmd(cmd_id, payload))

    elif cmd == "reply_user":
        # Beside the command loop, held by chat, so Cancel can stop it while it is being written.
        uid = str(payload["user_id"])

        async def _reply_job():
            try:
                ok, reason = await _reply_to_chat(uid)
                # queued: written and waiting its turn to be sent, so a Stop on Reply to all can still take it back
                _write_result(cmd_id, {"success": True, "queued": True} if ok else {"success": False, "reason": reason})
            except asyncio.CancelledError:
                if uid not in STATE["ignore_users"]:
                    _set_state(uid, "skipped", reason="you cancelled the reply")
                _write_result(cmd_id, {"success": False, "cancelled": True, "reason": "you cancelled the reply"})
            finally:
                if _REPLY_TASKS.get(uid) is asyncio.current_task():
                    _REPLY_TASKS.pop(uid, None)

        task = asyncio.create_task(_reply_job())
        _REPLY_TASKS[uid] = task
        _PANEL_TASKS.add(task)
        task.add_done_callback(_PANEL_TASKS.discard)

    elif cmd == "cancel_reply":
        # The one being written by hand stops; the one the bot has written and not sent yet is taken back, and one it
        # is writing or pacing now is not sent when it gets there (_CANCELLED).
        uid = str(payload["user_id"])
        task = _REPLY_TASKS.get(uid)
        stopped = bool(task and not task.done())
        if stopped:
            task.cancel()
        busy = (_REPLY_STATE.get(uid) or {}).get("state") in ("writing", "cooldown")
        _CANCELLED[uid] = time.time()
        dropped = _drop_lined_up(uid, by_hand=False) or _drop_outgoing(uid)
        if stopped or busy or dropped:
            _set_state(uid, "skipped", reason="you cancelled the reply")
        _write_result(cmd_id, {"ok": True, "stopped": stopped or busy or dropped})

    elif cmd == "reply_all":
        results_out = []
        targets = [cid for cid in list(CHAT_NAMES.keys())
                   if cid not in STATE["ignore_users"] and engine.has_pending(cid, cid)]
        for cid in targets:
            ok, reason = await _reply_to_chat(cid)
            results_out.append({
                "id": cid,
                "name": CHAT_NAMES.get(cid, cid),
                "success": ok,
                **({} if ok else {"reason": reason}),
            })
        _write_result(cmd_id, {"total": len(results_out), "results": results_out})

    elif cmd == "summarize_user":
        # Snapchat has no history endpoint to read back from, so this works from what the bridge holds since it started, or the chat log (what the runner read off Snapchat's page) when that has more. With neither, it says so rather than summarising two lines as if they were the conversation.
        uid = str(payload["user_id"])
        count = max(5, min(100, int(payload.get("count") or 20)))
        include_mine = bool(payload.get("include_mine", True))
        name = _name_for(uid) or uid
        hist = engine.message_history.get(f"{uid}-{uid}", [])
        lines = [((name if e.get("role") == "user" else "Me"), str(e.get("content", "")))
                 for e in hist[-count:] if e.get("content")]
        # What the chat log kept of it (read off Snapchat's page) when that is more than this run has seen.
        kept = [(("Me" if m["mine"] else name), str(m.get("text") or ""))
                for m in chatlog.conversation(LOG_ACCOUNT, uid, count) if str(m.get("text") or "").strip()]
        if len(kept) > len(lines):
            lines = kept
        lines = [l for l in lines if include_mine or l[0] != "Me"]
        if not lines:
            _write_result(cmd_id, {"ok": False, "reason": "Nothing from this chat is kept yet, so there is nothing to read."})
            return

        async def _summarize():
            try:
                from app.utils.ai import summarize_conversation
                text = await summarize_conversation(
                    lines, name, payload.get("length") or "medium",
                    payload.get("language") or "auto")
                if text:
                    # the last few lines with it, as the Discord side sends them: Big Picture shows them under the summary
                    _write_result(cmd_id, {"ok": True, "summary": text,
                                           "count": len(lines), "source": "recent",
                                           "recent": [{"mine": who == "Me", "text": line[:300]}
                                                      for who, line in lines[-4:]]})
                else:
                    _write_result(cmd_id, {"ok": False, "reason": "The model returned nothing."})
            except Exception as e:
                _write_result(cmd_id, {"ok": False, "reason": str(e)[:200]})

        # a task, so a few seconds of generating don't hold up every other command for this account
        _t = asyncio.create_task(_summarize())
        _SUMMARY_TASKS.add(_t)
        _t.add_done_callback(_SUMMARY_TASKS.discard)

    elif cmd == "analyse_user":
        from app.utils.helpers import load_instructions
        uid = str(payload["user_id"])
        hist = engine.message_history.get(f"{uid}-{uid}", [])
        msgs = [e["content"] for e in hist if e.get("role") == "user" and e.get("content")]
        # Their words from the chat log too, when it has more of them than this run has seen.
        kept = [str(m.get("text") or "") for m in chatlog.conversation(LOG_ACCOUNT, uid, 400)
                if not m["mine"] and str(m.get("text") or "").strip() and not str(m.get("text")).startswith("[")]
        if len(kept) > len(msgs):
            msgs = kept
        if not msgs:
            _write_result(cmd_id, {"ok": False,
                                   "reason": "Nothing they have written is kept yet."})
            return
        name = _name_for(uid) or uid
        instructions = (
            load_instructions() +
            f"\n\nSomeone asked you to give your honest read on {name} based on their messages. "
            "Stay in character. Give your real unfiltered opinion like you would to a friend. "
            "Be casual, funny, and direct. Roast them a bit but also be real about what you actually see. "
            "Reference specific things they said to back up your points. "
            "Keep it conversational, no bullet points, no formal structure, just talk like yourself. "
            "Don't be overly mean but don't sugarcoat either. Max 3-4 short paragraphs."
        )
        prompt = "Here are their messages: " + " | ".join(msgs[-200:])
        try:
            profile = await generate_response(prompt, instructions, history=None)
        except Exception as e:
            _write_result(cmd_id, {"ok": False, "reason": str(e)})
            return
        if profile:
            _write_result(cmd_id, {"ok": True, "profile": profile})
        else:
            _write_result(cmd_id, {"ok": False, "reason": "AI returned an empty response."})

    elif cmd in ("image_analyse", "image_setdesc", "image_delete", "image_delete_multi",
                 "image_delete_all"):
        await _handle_image_command(cmd, payload, cmd_id)

    elif cmd == "restart":
        log_system(f"Restart requested via Telegram ({PLATFORM_NAME})")
        _write_result(cmd_id, {"ok": True})
        # Spawn the replacement before exiting, os._exit() skips atexit handlers.
        _kill_node_runner()  # close the OLD browser before the new bridge spawns one
        try:
            from app.core.launcher import spawn_role
            spawn_role(PLATFORM, ACCOUNT_INDEX, capture=False)
        except Exception as e:
            log_error("Snap restart", str(e))
        await asyncio.sleep(1)
        os._exit(0)

    elif cmd == "shutdown":
        log_system(f"Shutdown requested via Telegram ({PLATFORM_NAME})")
        _write_result(cmd_id, {"ok": True})
        _kill_node_runner()  # close the browser too, os._exit() skips the atexit hook
        await asyncio.sleep(1)
        os._exit(0)

    elif cmd == "update":
        source = payload.get("source", "release")
        if source not in ("release", "main"):
            source = "release"
        UPDATE_FLAG.write_text(source, encoding="utf-8")
        _write_result(cmd_id, {"ok": True, "queued": True})

    elif cmd == "send_error_notification":
        # Passthrough, the Telegram error loop reads this from the file directly.
        _write_result(cmd_id, {"ok": True})

    else:
        _write_result(cmd_id, {"ok": False, "reason": f"Unknown command: {cmd}"})


async def _reply_to_chat(chat_id: str) -> tuple[bool, str]:
    """Generate a reply to the trailing unanswered messages and queue it for sending."""
    if PHONE:
        return False, "Through your iPhone it can only answer the messages it gets. Sending first needs the Mac way (BlueBubbles)"
    name = _name_for(chat_id) or chat_id
    async with _gen_lock(chat_id), _GEN_SLOTS:
        combined = engine.pop_pending_user_messages(chat_id, chat_id)
        if not combined:
            # Nothing waiting in this run's memory (it came in while the bot was off, or before a restart): what the
            # chat log kept of theirs since the account last wrote, with the conversation before it.
            combined = _kept_unanswered(chat_id)
            if combined:
                _seed_history(chat_id, time.time())
        if not combined:
            return False, "no unanswered message found"
        _set_state(chat_id, "writing")
        msg = IncomingMessage(
            platform=PLATFORM,
            user_id=chat_id,
            user_name=name,
            channel_id=chat_id,
            content=combined,
            is_private=True,
            wait_time=0.0,
            extra={"account": ACCOUNT_INDEX, **_picture_rule(chat_id)},
        )
        try:
            response = await generate_ai_response(msg)
        except Exception as e:
            _set_state(chat_id, "failed", reason=str(e) if isinstance(e, ModelWontLoad) else "no reply was generated, see the log")
            return False, str(e)
    if not response:
        _set_state(chat_id, "failed", reason="no reply was generated, see the log")
        return False, "couldn't generate response"
    response = _humanize_reply(response)
    _queue_outgoing(chat_id, response)
    await _queue_picture_if_any(msg, response)
    _handed_over(chat_id)
    log_system(f"Queued /reply to {name}")
    return True, ""


async def _handle_image_command(cmd: str, payload: dict, cmd_id: str):
    """This persona's image commands (analyse/delete), mirroring the Discord runner. The database calls default to
    the same persona, this account's."""
    from app.utils.pictures import pictures_folder
    img_folder = pictures_folder()
    exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}

    def _img_files():
        if not os.path.exists(img_folder):
            return []
        return sorted(
            [f for f in os.listdir(img_folder) if os.path.splitext(f)[1].lower() in exts],
            key=lambda f: int(os.path.splitext(f)[0][4:])
                if os.path.splitext(f)[0].startswith("IMG_") and os.path.splitext(f)[0][4:].isdigit()
                else 99999,
        )

    def _renumber():
        from app.utils.db import rename_picture_db
        for i, fname in enumerate(_img_files(), start=1):
            stem, ext = os.path.splitext(fname)
            if stem.startswith("IMG_") and stem[4:].isdigit() and int(stem[4:]) != i:
                new = f"IMG_{i}{ext}"
                os.rename(os.path.join(img_folder, fname), os.path.join(img_folder, new))
                rename_picture_db(fname, new)

    if cmd == "image_analyse":
        from app.utils.db import add_picture_description
        from app.utils.ai import _create_image_completion
        name = payload.get("name", "")
        b64 = payload.get("b64", "")
        ext = payload.get("ext", ".jpg")
        path = os.path.join(img_folder, name)
        if not b64:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
            else:
                _write_result(cmd_id, {"ok": False, "reason": f"Image file not found: {name}"})
                return
        elif not os.path.exists(path):
            os.makedirs(img_folder, exist_ok=True)
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
        try:
            cfg = load_config()
            model = cfg["bot"].get("groq_image_model", "meta-llama/llama-4-scout-17b-16e-instruct")
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                        ".gif": "image/gif", ".webp": "image/webp"}
            mime = mime_map.get(ext.lower(), "image/jpeg")
            data_url = f"data:{mime};base64,{b64}"
            log_system(f"Analysing image: {name}")
            from app.utils.pictures import DESCRIBE_MAX_TOKENS, clean_description, describe_messages
            resp = await _create_image_completion(
                model,
                messages=describe_messages(data_url),
                max_tokens=DESCRIBE_MAX_TOKENS,
                reasoning_effort="none",
            )
            desc = clean_description(resp.choices[0].message.content or "")
            if not desc:
                raise RuntimeError("The model answered with nothing.")
            add_picture_description(name, desc)
            _write_result(cmd_id, {"ok": True, "description": desc})
        except Exception as e:
            log_error("Snap image_analyse", str(e))
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

    elif cmd == "image_setdesc":
        # A description written by hand (Telegram's /setdesc), as the Discord side takes it.
        from app.utils.db import add_picture_description
        name = payload.get("name", "")
        desc = (payload.get("description") or "").strip()
        if name.isdigit():
            matches = [f for f in _img_files() if os.path.splitext(f)[0] == f"IMG_{name}"]
            name = matches[0] if matches else name
        if not desc:
            _write_result(cmd_id, {"ok": False, "reason": "Description can't be empty."})
        elif not name or os.path.basename(name) != name or not os.path.exists(os.path.join(img_folder, name)):
            _write_result(cmd_id, {"ok": False, "reason": f"Image `{name}` not found."})
        else:
            add_picture_description(name, desc)
            log_system(f"Description manually set for {name}: {desc[:80]}")
            _write_result(cmd_id, {"ok": True, "name": name, "description": desc})

    elif cmd == "image_delete":
        from app.utils.db import delete_picture_db
        name = payload.get("name", "")
        files = _img_files()
        if name.isdigit():
            matches = [f for f in files if os.path.splitext(f)[0] == f"IMG_{name}"]
            name = matches[0] if matches else name
        path = os.path.join(img_folder, name)
        if os.path.exists(path):
            os.remove(path)
            delete_picture_db(name)
            _renumber()
            _write_result(cmd_id, {"ok": True})
        else:
            _write_result(cmd_id, {"ok": False, "reason": f"Image `{name}` not found."})

    elif cmd == "image_delete_multi":
        from app.utils.db import delete_picture_db
        names = payload.get("names", [])
        files = _img_files()
        deleted, failed = [], []
        for n in names:
            matches = [f for f in files if os.path.splitext(f)[0] == f"IMG_{n}"]
            if matches:
                try:
                    os.remove(os.path.join(img_folder, matches[0]))
                    delete_picture_db(matches[0])
                    deleted.append(n)
                except Exception:
                    failed.append(n)
            else:
                failed.append(n)
        _renumber()
        _write_result(cmd_id, {"ok": True, "deleted": deleted, "failed": failed})

    elif cmd == "image_delete_all":
        from app.utils.db import clear_all_pictures_db
        files = _img_files()
        for f in files:
            try:
                os.remove(os.path.join(img_folder, f))
            except Exception:
                pass
        clear_all_pictures_db()
        _write_result(cmd_id, {"ok": True, "count": len(files)})


# Command ids already run, newest last, so a pass that could not rewrite the
# command file never runs one of them a second time on the next.
_RAN_COMMANDS: dict = {}


def _remember_ran(entries):
    for e in entries:
        if e.get("id"):
            _RAN_COMMANDS[e["id"]] = None
    while len(_RAN_COMMANDS) > 500:
        _RAN_COMMANDS.pop(next(iter(_RAN_COMMANDS)))


async def tg_command_loop():
    """Poll tg_commands_snap.json and execute Telegram controller and panel commands. One pass going wrong (a file another process had open at that instant, say) is written to the log and the next pass goes ahead: it used to end the loop, and with it the whole bridge."""
    log_system(f"Telegram IPC bridge started ({PLATFORM_NAME})")

    while True:
        await asyncio.sleep(TG_POLL_INTERVAL)
        try:
            await _tg_command_pass()
        except Exception as e:
            log_error("Snap TG IPC", f"{type(e).__name__}: {e}")


async def _tg_command_pass():
    """One look at the command file: the update flag, then any commands waiting."""
    # Update sentinel (snap-specific so it never collides with the Discord one)
    if UPDATE_FLAG.exists():
        try:
            source = UPDATE_FLAG.read_text(encoding="utf-8").strip() or "release"
            if source not in ("release", "main"):
                source = "release"
            UPDATE_FLAG.unlink(missing_ok=True)
            log_system(f"Update ({source}) triggered via flag file")
            repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import subprocess as _sp
            if sys.platform == "win32":
                upd_path = os.path.join(repo_dir, "scripts", "updater.bat")
                _sp.Popen(
                    f'cmd /c start "Updating LLMSelfbot..." /d "{repo_dir}" "{upd_path}" {source}',
                    shell=True, cwd=repo_dir, creationflags=0x00000010,
                )
            else:
                upd_path = os.path.join(repo_dir, "scripts", "updater.sh")
                try:
                    os.chmod(upd_path, 0o755)
                except Exception:
                    pass
                _sp.Popen(["bash", upd_path, source], start_new_session=True, cwd=repo_dir)
            await asyncio.sleep(2)
            _kill_node_runner()  # close the browser before the updater takes over
            os._exit(0)
        except Exception as e:
            log_error("Snap Update Flag", str(e))

    if not CMD_FILE.exists():
        return
    commands = _read_json(CMD_FILE, [])
    if not isinstance(commands, list) or not commands:
        return

    # consume the commands up-front and flush the file before running anything: restart/shutdown call os._exit() mid-loop, so a late write would leave restart entries that re-fire every boot
    to_run = [e for e in commands if isinstance(e, dict) and e.get("cmd") != "send_error_notification"
              and e.get("id") not in _RAN_COMMANDS]
    stale = [e for e in commands if isinstance(e, dict) and e.get("id") in _RAN_COMMANDS]
    if not to_run and not stale:
        return
    _remember_ran(to_run)
    try:
        # Read again just before writing: the panel may have added a command since, and a stale copy would drop it.
        current = _read_json(CMD_FILE, [])
        if not isinstance(current, list):
            current = []
        _write_json(CMD_FILE, [e for e in current if isinstance(e, dict) and (
            e.get("cmd") == "send_error_notification" or (e.get("id") and e.get("id") not in _RAN_COMMANDS))])
    except Exception as e:
        # Remembered above, so none of them runs twice; the file is tidied on a later pass.
        log_error("Snap TG IPC", f"could not rewrite the command file: {e}")

    for entry in to_run:
        cmd_id  = entry.get("id", "")
        cmd     = entry.get("cmd", "")
        payload = entry.get("payload", {})
        try:
            await _handle_command(cmd, payload, cmd_id)
        except Exception as e:
            log_error("Snap TG IPC", f"cmd={cmd} error={e}")
            _notify_telegram_error("Command error", f"cmd={cmd}: {e}")
            _write_result(cmd_id, {"ok": False, "error": str(e)})


async def _cleanup_loop():
    """Hourly prune of unbounded in-memory caches + old temp media."""
    while True:
        await asyncio.sleep(3600)  # hourly
        try:
            cleared = []
            # One lock per chat ever seen, so prune the idle ones.
            if len(_gen_locks) > 500:
                cleared.append("gen locks")
                for k in [k for k, v in list(_gen_locks.items()) if not v.locked()]:
                    _gen_locks.pop(k, None)
            if len(engine._lang_cache) > 500:
                cleared.append("language")
                engine._lang_cache.clear()
            if len(engine._memory_cache) > 1000:
                cleared.append("memory")
                engine._memory_cache.clear()
            # Drop history for chats we no longer track (e.g. scrolled out of view).
            if len(engine.message_history) > 1000:
                cleared.append("history")
                engine.message_history.clear()
            pruned = _prune_temp_media()

            caches = f"cleared {', '.join(cleared)} cache(s)" if cleared else "caches OK"
            files = f"removed {pruned} old temp file(s)" if pruned else "no temp files to prune"
            log_system(f"Hourly cleanup, {caches}; {files}.")
        except Exception:
            pass


def _prune_temp_media(max_age_seconds: float = 21600):  # 6 hours
    """Delete old downloaded snap/voice/image files in config/temp. Returns count."""
    temp_dir = resource_path("config/temp")
    if not os.path.isdir(temp_dir):
        return 0
    now = time.time()
    removed = 0
    for fname in os.listdir(temp_dir):
        fpath = os.path.join(temp_dir, fname)
        try:
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > max_age_seconds:
                os.remove(fpath)
                removed += 1
        except Exception:
            pass
    return removed


# A runner's exit code for "signed out, a person has to sign it in" (snapchat_runner.js), and the bridge's own the same:
# the supervisor does not start it again by itself (app/web/supervisor.py).
NEEDS_SIGN_IN = 4


async def _runner_watch():
    """The Node runner gone (it crashed, or its Chrome took it down with it): with nothing reading or sending, the
    bridge goes too, and the panel starts the account again, as after any crash. It used to stay up answering nobody,
    the account showing as running (and "starting") until someone restarted it by hand."""
    while True:
        await asyncio.sleep(5)
        code = _node_proc.poll() if _node_proc is not None else None
        if code is not None and not _MC.get("switching"):
            if code == NEEDS_SIGN_IN:
                # Signed out: a person signs it in again. Passed on, so the panel does not start it again by itself.
                log_error(PLATFORM_NAME, f"{PLATFORM_NAME} needs you to sign it in again; it is not tried again "
                                         "by itself.")
                _exit_now(NEEDS_SIGN_IN)
            log_error(PLATFORM_NAME, f"The {PLATFORM_NAME} runner stopped (code {code}); the account restarts.")
            _exit_now(3)


async def _main_async():
    cfg = load_config()
    if MINECRAFT:
        # No inbox to read and nothing to nudge: mindcraft asks, and its brain answers.
        tasks = [tg_command_loop(), _cleanup_loop(), _wake_server(), _runner_watch(), _minecraft_main()]
    elif TELEGRAM:
        # Its client is the runner: no Node, nothing to watch, and the wake socket has nobody on the other end.
        tasks = [process_incoming(), tg_command_loop(), _cleanup_loop(), _nudge_loop(), _telegram_main()]
    elif PHONE:
        tasks = [process_incoming(), tg_command_loop(), _cleanup_loop(), _phone_state_loop()]
    else:
        tasks = [process_incoming(), tg_command_loop(), _cleanup_loop(), _wake_server(), _nudge_loop(), _runner_watch()]
    if PLATFORM == "tiktok":
        tasks.append(_live_quiet_loop())

    # Mood shifts over time, exactly like the Discord runner.
    if cfg.get("bot", {}).get("mood", {}).get("enabled", True):
        shift_mood()                 # pick a starting mood now
        tasks.append(mood_loop())    # then keep shifting it on a timer
        log_system(f"Mood system active (current: {mood_mod.current_mood})")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        raise
    except BaseException:
        # One of the loops died. Left to asyncio.run, the exit waited on the
        # other loops and on worker threads still busy, and one night that
        # wait outlived the crash by ten hours: the process stayed up, so the
        # panel showed the account running while it answered nobody. Out now
        # instead; the panel starts it again within seconds.
        import traceback
        traceback.print_exc()
        log_error(PLATFORM_NAME, "The bridge hit an error it could not carry on from; it restarts.")
        _exit_now(1)


def _exit_now(code: int):
    """Close the browser and leave at once, without waiting on anything still running."""
    try:
        _kill_node_runner()
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(code)


# ── Node runner orchestration ────────────────────────────────────────────────
_node_proc = None


def _print_banner():
    """Pretty startup banner so the bridge console isn't a wall of plain text."""
    from colorama import init as _cinit, Fore, Style
    _cinit()
    set_theme(PLATFORM)
    try:
        width = shutil.get_terminal_size().columns
    except Exception:
        width = 60
    width = max(40, min(width, 100))
    border = "═" * (width - 2)
    title = f"{PLATFORM_NAME} AI Bridge"
    pad = max(0, (width - len(title) - 2) // 2)
    print(f"{Fore.YELLOW}╔{border}╗")
    print(f"║{' ' * pad}{Style.BRIGHT}{title}{Style.NORMAL}{' ' * (width - len(title) - 2 - pad)}║")
    print(f"╚{border}╝{Style.RESET_ALL}")


def _kill_node_runner():
    """Kill the Node runner and its Chrome child (whole process tree); called from atexit and before os._exit()."""
    if not _node_proc or _node_proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            # /T kills the child Chrome too; /F forces it. Quiet on success.
            from app.utils.procs import quiet_kwargs
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(_node_proc.pid)],
                capture_output=True, **quiet_kwargs(),
            )
        else:
            _node_proc.terminate()
            try:
                _node_proc.wait(timeout=5)
            except Exception:
                _node_proc.kill()
    except Exception:
        try:
            _node_proc.terminate()
        except Exception:
            pass


def _sync_node_runner() -> str:
    """Make sure a writable copy of the Node runner sits next to node_modules; frozen bundles are read-only, so we mirror into DATA_DIR/snapchat/ and run from there (Node's ESM resolver wants node_modules beside the JS)."""
    from app.utils.paths import APP_DIR, DATA_DIR
    src_dir = Path(APP_DIR) / "app" / "platforms" / "snapchat"
    dst_dir = DATA_DIR / "snapchat"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not (src_dir / "snapchat_runner.js").exists():
        return str(src_dir)
    # A source checkout with its own deps runs in place; nothing to mirror.
    if (src_dir / "node_modules").is_dir() and not (dst_dir / "node_modules").is_dir():
        return str(src_dir)

    # everything else runs from the data dir, so its JS copy must match THIS build, every launch. used to return early whenever node_modules existed (every launch after the first), so the sync never re-ran and installs kept their first Snapchat code forever. byte-compare, write only what changed, so it costs four small reads.
    _sync_runner_files(src_dir, dst_dir)
    return str(dst_dir)


def _sync_runner_files(src_dir, dst_dir) -> list:
    """Bring the data dir's runner up to date with this build; package.json rides along so dep changes are visible, installing stays a deliberate panel action."""
    changed = []
    # discord_token.js is the browser sign-in helper. It lives here because
    # Node looks for node_modules beside the script and Puppeteer is installed
    # here; it has nothing to do with Snapchat.
    # The other platforms' runners and what they are made of live here for the same reason, and so does the persona's
    # own browser for the web (app/utils/web/browser.py), on the same Puppeteer. Every script there is: a list of them
    # to keep up to date left out the one a new file was, and the runners that needed it stopped at their first line.
    names = sorted({p.name for p in Path(src_dir).iterdir() if p.is_file() and p.suffix in (".js", ".mjs")}
                   | {"package.json"})
    for name in names:
        src, dst = src_dir / name, dst_dir / name
        try:
            new = src.read_bytes()
            if not dst.exists() or dst.read_bytes() != new:
                dst.write_bytes(new)
                changed.append(name)
        except OSError:
            pass
    if changed:
        log_system(f"Snapchat runner updated from this build: {', '.join(changed)}")
    return changed


def _spawn_node_runner():
    """Launch the Node runner as a child in THIS console; SNAP_SPAWN_NODE=false runs it yourself, and the platform's config section maps into the runner env (.env wins)."""
    global _node_proc
    if os.getenv(f"{P['env']}_SPAWN_NODE", "true").lower() == "false":
        log_system(f"Node runner auto-start disabled ({P['env']}_SPAWN_NODE=false), start it yourself.")
        return

    node_exe = shutil.which("node")
    if not node_exe:
        log_error(PLATFORM_NAME, "Node.js not found in PATH - install it from nodejs.org or "
                                 f"use the {PLATFORM_NAME} page in the web UI.")
        return

    runner_dir = _sync_node_runner()
    runner_js = os.path.join(runner_dir, P["runner"])
    if not os.path.exists(runner_js):
        log_error(PLATFORM_NAME, f"Runner not found: {runner_js}")
        return
    # iMessage's runner is Node's own (its fetch and WebSocket): nothing to install. WhatsApp's is not - it has
    # the baileys package - so this one still applies to it, and only the Chrome checks below do not.
    if not IMESSAGE and not os.path.isdir(os.path.join(runner_dir, "node_modules")):
        log_error(PLATFORM_NAME, f"Node deps not installed - use the {PLATFORM_NAME} page in the "
                                 "web UI, or: cd platforms/snapchat && npm install")
        return

    # node_modules alone isn't enough: Puppeteer's Chrome is a separate postinstall step, and a half-finished one makes deps look complete while every launch dies with "Could not find Chrome"
    try:
        from app.web.routes.system_routes import chrome_path
        if not NO_BROWSER and not chrome_path():
            log_error(PLATFORM_NAME,
                      "Puppeteer's Chrome is missing or was only partly downloaded. "
                      f"Open the {PLATFORM_NAME} page in the app and run the installer again, "
                      "it clears the partial download and refetches it.")
            return
    except Exception:
        pass        # never block startup on the probe itself

    # ── config.yaml snapchat section → env (only where .env didn't set one) ──
    from app.utils.paths import DATA_DIR
    node_env = {**os.environ, f"{P['env']}_ACCOUNT_INDEX": str(ACCOUNT_INDEX)}
    # Drive the browser this machine already has, when it has one. Puppeteer
    # reads this variable itself, so pointing it at an installed Chrome or Edge
    # is the whole integration - and a browser a person actually uses is a
    # better thing to be driving than Chrome for Testing, which is its own
    # distinct build.
    try:
        from app.web.routes.system_routes import installed_browser
        _bname, _bpath = installed_browser() if not NO_BROWSER else ("", "")
        if _bpath and "PUPPETEER_EXECUTABLE_PATH" not in os.environ:
            node_env["PUPPETEER_EXECUTABLE_PATH"] = _bpath
            log_system(f"{PLATFORM_NAME} browser: {_bname} ({_bpath})")
    except Exception:
        pass
    if IMESSAGE:
        node_env["IMESSAGE_DATA_DIR"] = str(DATA_DIR)
        try:
            node_env.update(_imessage_env(load_config() or {}))
        except Exception as e:
            log_error(PLATFORM_NAME, f"Its settings could not be read, so it runs on the defaults: {e}")
    if WHATSAPP:
        node_env["WHATSAPP_DATA_DIR"] = str(DATA_DIR)
        try:
            node_env.update(_whatsapp_env(load_config() or {}))
        except Exception as e:
            log_error(PLATFORM_NAME, f"Its settings could not be read, so it runs on the defaults: {e}")
    # point Node at the writable data dir for cookies/profile/temp media, and the real .env
    node_env["SNAP_DATA_DIR"] = str(DATA_DIR)
    node_env["SNAP_DOTENV_PATH"] = os.path.join(DATA_DIR, "config", ".env")
    if SOCIAL:
        env = P["env"]
        node_env[f"{env}_DATA_DIR"] = str(DATA_DIR)
        node_env[f"{env}_DOTENV_PATH"] = os.path.join(DATA_DIR, "config", ".env")
        try:
            cfg_now = load_config() or {}
            node_env.update({"instagram": _instagram_env, "tiktok": _tiktok_env, "x": _x_env,
                             "reddit": _reddit_env}[PLATFORM](cfg_now))
        except Exception as e:
            log_error(PLATFORM_NAME, f"Its settings could not be read, so it runs on the defaults: {e}")
    try:
        snap_cfg = load_config().get("snapchat") or {}
        if PLATFORM != "snapchat":
            raise _NotSnapchat
        env_map = {
            "poll_interval_ms": "SNAP_POLL_INTERVAL_MS",
            "response_timeout_ms": "SNAP_RESPONSE_TIMEOUT_MS",
            "max_recipients": "SNAP_MAX_RECIPIENTS",
            "headless": "SNAP_HEADLESS",
            "min_send_gap_ms": "SNAP_MIN_SEND_GAP_MS",
            "max_send_gap_ms": "SNAP_MAX_SEND_GAP_MS",
            "max_sends_per_hour": "SNAP_MAX_SENDS_PER_HOUR",
            "quiet_hours": "SNAP_QUIET_HOURS",
            "auto_add_friends": "SNAP_AUTO_ADD_FRIENDS",
            "verify_wait_ms": "SNAP_VERIFY_WAIT_MS",
            "reload_interval_ms": "SNAP_RELOAD_INTERVAL_MS",
        }
        # Nested, so it is not one of the flat ones above.
        pics = snap_cfg.get("pictures") or {}
        if pics.get("as_chat_picture") is not None and "SNAP_AS_CHAT_PICTURE" not in os.environ:
            node_env["SNAP_AS_CHAT_PICTURE"] = "true" if pics["as_chat_picture"] else "false"
        for yaml_key, env_key in env_map.items():
            val = snap_cfg.get(yaml_key)
            if val is not None and env_key not in os.environ:
                node_env[env_key] = "true" if val is True else ("false" if val is False else str(val))
        # Accepting friend requests waits as Discord's does (bot.friend_requests), rather than the moment one shows.
        _fr = (load_config().get("bot") or {}).get("friend_requests") or {}
        for _k, _env in (("accept_delay_min", "SNAP_ACCEPT_DELAY_MIN"), ("accept_delay_max", "SNAP_ACCEPT_DELAY_MAX")):
            if _fr.get(_k) is not None and _env not in os.environ:
                node_env[_env] = str(int(_fr[_k]))

        # The browser's clock and language come from the persona, not from
        # whatever the host machine happens to be set to. The Discord half of
        # the same persona already sends bot.locale and bot.timezone in its
        # headers; the Snapchat half was leaving the browser on the hardcoded
        # Europe/Paris and the host's own language, so one persona presented two
        # different people. A snapchat: entry still wins over the bot: one.
        bot_cfg = load_config().get("bot") or {}
        for env_key, value in (
            ("SNAP_LOCALE", snap_cfg.get("locale") or bot_cfg.get("locale")),
            ("SNAP_TIMEZONE", snap_cfg.get("timezone") or bot_cfg.get("timezone")),
        ):
            if value and env_key not in os.environ:
                node_env[env_key] = str(value)
    except _NotSnapchat:
        pass
    except Exception:
        pass

    try:
        import threading
        from app.utils.procs import quiet_kwargs
        # Stealth (app/utils/stealth.py): every poll interval jittered per session so accounts never
        # lock-step, and in careful mode the pace scales down and every public action turns off.
        from app.utils import stealth
        stealth.tone_down_env(node_env)
        if stealth.conservative()["on"]:
            log_system("[Stealth] Careful mode is on: this account runs slower, quieter, and does nothing public.")
        # Its own proxy, set when it was added, over any set for the whole platform.
        _own_proxy = os.getenv(f"{P['env']}_PROXY_{ACCOUNT_INDEX}", "").strip()
        if _own_proxy:
            node_env[f"{P['env']}_PROXY"] = _own_proxy
        _node_proc = subprocess.Popen([node_exe, runner_js], cwd=runner_dir, env=node_env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, **quiet_kwargs())
        threading.Thread(target=_relay_node_output, args=(_node_proc,), daemon=True,
                         name=f"{P['key']}-node-output").start()
        atexit.register(_kill_node_runner)
        log_system(f"Node runner started (PID {_node_proc.pid}, account #{ACCOUNT_INDEX})")
    except Exception as e:
        log_error(PLATFORM_NAME, f"Could not start Node runner: {e}")


class _NotSnapchat(Exception):
    """The snapchat: section's own mapping is Snapchat's alone."""


def _tiktok_env(cfg: dict) -> dict:
    """The tiktok: section, and what TikTok takes from the persona's settings, as the TikTok runner's environment
    (TIKTOK_*). A value already in the environment (.env) wins."""
    tt = cfg.get("tiktok") or {}
    bot = cfg.get("bot") or {}

    def flag(v):
        return "true" if v else "false"

    out = {}
    plain = {
        "headless": "TIKTOK_HEADLESS", "poll_interval_ms": "TIKTOK_POLL_INTERVAL_MS",
        "response_timeout_ms": "TIKTOK_RESPONSE_TIMEOUT_MS", "max_recipients": "TIKTOK_MAX_RECIPIENTS",
        "min_send_gap_ms": "TIKTOK_MIN_SEND_GAP_MS", "max_send_gap_ms": "TIKTOK_MAX_SEND_GAP_MS",
        "max_sends_per_hour": "TIKTOK_MAX_SENDS_PER_HOUR", "quiet_hours": "TIKTOK_QUIET_HOURS",
        "reload_interval_ms": "TIKTOK_RELOAD_INTERVAL_MS", "accept_message_requests": "TIKTOK_ACCEPT_MESSAGE_REQUESTS",
        "follow_back": "TIKTOK_FOLLOW_BACK", "night_activity_status": "TIKTOK_NIGHT_ACTIVITY_STATUS",
        "dry_run": "TIKTOK_DRY_RUN", "proxy": "TIKTOK_PROXY",
    }
    for key, env in plain.items():
        v = tt.get(key)
        if v is not None and v != "":
            out[env] = flag(v) if isinstance(v, bool) else str(v)
    comments = tt.get("comments") or {}
    if comments:
        out["TIKTOK_COMMENTS"] = flag(comments.get("enabled", False))
        for key, env in (("per_hour", "TIKTOK_COMMENTS_PER_HOUR"), ("videos", "TIKTOK_COMMENTS_VIDEOS")):
            if comments.get(key) is not None:
                out[env] = str(comments[key])
    live = tt.get("live") or {}
    if live:
        out["TIKTOK_LIVE"] = flag(live.get("enabled", False))
        out["TIKTOK_LIVE_CHAT"] = flag(live.get("chat", True))
        if live.get("per_minute") is not None:
            out["TIKTOK_LIVE_PER_MINUTE"] = str(live["per_minute"])
    # Going out (the runner's out tab): watching, their posts, likes and comments, LIVE visits, For You, posting.
    going_out = {
        "watch": {"enabled": "TIKTOK_WATCH", "their_posts": "TIKTOK_THEIR_POSTS"},
        "engage": {"like_sent": "TIKTOK_LIKE_SENT", "like_theirs": "TIKTOK_LIKE_THEIRS",
                   "comment_sent": "TIKTOK_COMMENT_SENT", "comment_theirs": "TIKTOK_COMMENT_THEIRS",
                   "mentions": "TIKTOK_MENTIONS", "likes_per_day": "TIKTOK_LIKES_PER_DAY",
                   "comments_per_day": "TIKTOK_COMMENTS_PER_DAY"},
        "visits": {"enabled": "TIKTOK_VISITS", "chats": "TIKTOK_VISITS_CHATS", "shared": "TIKTOK_VISITS_SHARED",
                   "following": "TIKTOK_VISITS_FOLLOWING", "stay_minutes": "TIKTOK_VISIT_MINUTES",
                   "lines_per_5min": "TIKTOK_VISIT_LINES", "per_day": "TIKTOK_VISITS_PER_DAY",
                   "follow_host": "TIKTOK_VISIT_FOLLOW_HOST"},
        "foryou": {"enabled": "TIKTOK_FORYOU", "sessions_per_day": "TIKTOK_FORYOU_SESSIONS",
                   "minutes": "TIKTOK_FORYOU_MINUTES", "like_percent": "TIKTOK_FORYOU_LIKE_PERCENT"},
        "posting": {"per_day": "TIKTOK_POSTS_PER_DAY"},
    }
    for section, keys in going_out.items():
        block = tt.get(section) or {}
        for key, env in keys.items():
            v = block.get(key)
            if v is not None and v != "":
                out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Requests wait as Discord's friend requests do; the browser's clock and language are the persona's.
    fr = bot.get("friend_requests") or {}
    for key, env in (("accept_delay_min", "TIKTOK_ACCEPT_DELAY_MIN"), ("accept_delay_max", "TIKTOK_ACCEPT_DELAY_MAX")):
        if fr.get(key) is not None:
            out[env] = str(int(fr[key]))
    for env, value in (("TIKTOK_LOCALE", tt.get("locale") or bot.get("locale")),
                       ("TIKTOK_TIMEZONE", tt.get("timezone") or bot.get("timezone")),
                       ("TIKTOK_TRIGGER", bot.get("trigger")),
                       ("TIKTOK_NIGHT_HOURS", (bot.get("night_invisible") or {}).get("hours"))):
        if value:
            out[env] = str(value)
    return {k: v for k, v in out.items() if k not in os.environ}


def _instagram_env(cfg: dict) -> dict:
    """The instagram: section, and what Instagram takes from the persona's settings, as the Instagram runner's
    environment (INSTAGRAM_*). A value already in the environment (.env) wins, which is where its login lives."""
    ig = cfg.get("instagram") or {}
    bot = cfg.get("bot") or {}

    def flag(v):
        return "true" if v else "false"

    out = {}
    plain = {
        "headless": "INSTAGRAM_HEADLESS", "poll_interval_ms": "INSTAGRAM_POLL_INTERVAL_MS",
        "response_timeout_ms": "INSTAGRAM_RESPONSE_TIMEOUT_MS", "max_recipients": "INSTAGRAM_MAX_RECIPIENTS",
        "min_send_gap_ms": "INSTAGRAM_MIN_SEND_GAP_MS", "max_send_gap_ms": "INSTAGRAM_MAX_SEND_GAP_MS",
        "max_sends_per_hour": "INSTAGRAM_MAX_SENDS_PER_HOUR", "quiet_hours": "INSTAGRAM_QUIET_HOURS",
        "reload_interval_ms": "INSTAGRAM_RELOAD_INTERVAL_MS",
        "accept_message_requests": "INSTAGRAM_ACCEPT_MESSAGE_REQUESTS",
        "follow_back": "INSTAGRAM_FOLLOW_BACK", "accept_follow_requests": "INSTAGRAM_ACCEPT_FOLLOW_REQUESTS",
        "night_activity_status": "INSTAGRAM_NIGHT_ACTIVITY_STATUS", "dry_run": "INSTAGRAM_DRY_RUN",
        "proxy": "INSTAGRAM_PROXY",
    }
    for key, env in plain.items():
        v = ig.get(key)
        if v is not None and v != "":
            out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Everything it does beyond answering: watching, stories, Reels, going out, comments, its Note, posting.
    going_out = {
        "watch": {"enabled": "INSTAGRAM_WATCH", "their_posts": "INSTAGRAM_THEIR_POSTS",
                  "voice_notes": "INSTAGRAM_VOICE_NOTES"},
        "stories": {"watch": "INSTAGRAM_STORIES_WATCH", "reply": "INSTAGRAM_STORIES_REPLY",
                    "replies_per_day": "INSTAGRAM_STORY_REPLIES_PER_DAY", "post": "INSTAGRAM_STORIES_POST",
                    "post_per_day": "INSTAGRAM_STORIES_PER_DAY"},
        "reels": {"enabled": "INSTAGRAM_REELS", "sessions_per_day": "INSTAGRAM_REELS_SESSIONS",
                  "minutes": "INSTAGRAM_REELS_MINUTES", "like_percent": "INSTAGRAM_REELS_LIKE_PERCENT"},
        "engage": {"like_sent": "INSTAGRAM_LIKE_SENT", "like_theirs": "INSTAGRAM_LIKE_THEIRS",
                   "comment_sent": "INSTAGRAM_COMMENT_SENT", "comment_theirs": "INSTAGRAM_COMMENT_THEIRS",
                   "likes_per_day": "INSTAGRAM_LIKES_PER_DAY", "comments_per_day": "INSTAGRAM_COMMENTS_PER_DAY"},
        "comments": {"enabled": "INSTAGRAM_COMMENTS", "per_hour": "INSTAGRAM_COMMENTS_PER_HOUR",
                     "posts": "INSTAGRAM_COMMENTS_POSTS"},
        "notes": {"enabled": "INSTAGRAM_NOTES", "every_hours": "INSTAGRAM_NOTES_HOURS"},
        "posting": {"per_day": "INSTAGRAM_POSTS_PER_DAY"},
    }
    for section, keys in going_out.items():
        block = ig.get(section) or {}
        for key, env in keys.items():
            v = block.get(key)
            if v is not None and v != "":
                out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Message requests wait as Discord's friend requests do; the browser's clock and language are the persona's.
    fr = bot.get("friend_requests") or {}
    for key, env in (("accept_delay_min", "INSTAGRAM_ACCEPT_DELAY_MIN"),
                     ("accept_delay_max", "INSTAGRAM_ACCEPT_DELAY_MAX")):
        if fr.get(key) is not None:
            out[env] = str(int(fr[key]))
    for env, value in (("INSTAGRAM_LOCALE", ig.get("locale") or bot.get("locale")),
                       ("INSTAGRAM_TIMEZONE", ig.get("timezone") or bot.get("timezone")),
                       ("INSTAGRAM_TRIGGER", bot.get("trigger")),
                       ("INSTAGRAM_NIGHT_HOURS", (bot.get("night_invisible") or {}).get("hours"))):
        if value:
            out[env] = str(value)
    return {k: v for k, v in out.items() if k not in os.environ}


def _x_env(cfg: dict) -> dict:
    """The x: section, and what X takes from the persona's own settings, as the X runner's environment (X_*). A
    value already in the environment (config/.env) wins, which is where its login lives."""
    x = cfg.get("x") or {}
    bot = cfg.get("bot") or {}

    def flag(v):
        return "true" if v else "false"

    out = {}
    plain = {
        "headless": "X_HEADLESS", "poll_interval_ms": "X_POLL_INTERVAL_MS",
        "response_timeout_ms": "X_RESPONSE_TIMEOUT_MS", "max_recipients": "X_MAX_RECIPIENTS",
        "min_send_gap_ms": "X_MIN_SEND_GAP_MS", "max_send_gap_ms": "X_MAX_SEND_GAP_MS",
        "max_sends_per_hour": "X_MAX_SENDS_PER_HOUR", "quiet_hours": "X_QUIET_HOURS",
        "reload_interval_ms": "X_RELOAD_INTERVAL_MS",
        "accept_message_requests": "X_ACCEPT_MESSAGE_REQUESTS",
        "dry_run": "X_DRY_RUN", "proxy": "X_PROXY",
    }
    for key, env in plain.items():
        v = x.get(key)
        if v is not None and v != "":
            out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Everything beyond answering a message: what is said to it in public, what it does about other people's
    # posts, what it puts up itself, and what it reads of theirs.
    going_out = {
        "mentions": {"enabled": "X_MENTIONS", "replies": "X_MENTION_REPLIES",
                     "own_posts": "X_OWN_REPLIES", "own_posts_watched": "X_OWN_POSTS_WATCHED",
                     "per_hour": "X_MENTIONS_PER_HOUR", "per_pass": "X_MENTIONS_PER_PASS",
                     "scrolls": "X_MENTION_SCROLLS", "skip_strangers": "X_SKIP_STRANGERS"},
        "engage": {"like_sent": "X_LIKE_SENT", "repost_sent": "X_REPOST_SENT",
                   "like_theirs": "X_LIKE_THEIRS", "repost_theirs": "X_REPOST_THEIRS",
                   "follow_back": "X_FOLLOW_BACK", "likes_per_day": "X_LIKES_PER_DAY",
                   "reposts_per_day": "X_REPOSTS_PER_DAY", "follows_per_day": "X_FOLLOWS_PER_DAY",
                   "replies_per_day": "X_REPLIES_PER_DAY"},
        "posting": {"enabled": "X_POSTING", "per_day": "X_POSTS_PER_DAY",
                    "min_gap_minutes": "X_POST_MIN_GAP_MIN", "max_chars": "X_POST_MAX_CHARS",
                    "thread_max": "X_THREAD_MAX", "with_image": "X_POST_WITH_IMAGE"},
        "watch": {"enabled": "X_WATCH", "their_posts": "X_THEIR_POSTS", "threads": "X_THREADS"},
    }
    for section, keys in going_out.items():
        block = x.get(section) or {}
        for key, env in keys.items():
            v = block.get(key)
            if v is not None and v != "":
                out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Where a post of its own comes from: one step further in than the rest (posting.from).
    where = ((x.get("posting") or {}).get("from") or {})
    for key, env in (("saw_online", "X_POST_FROM_WEB"), ("on_its_mind", "X_POST_FROM_MIND")):
        if where.get(key) is not None:
            out[env] = flag(where[key])
    # Message requests wait as Discord's friend requests do; the browser's clock and language are the persona's.
    fr = bot.get("friend_requests") or {}
    for key, env in (("accept_delay_min", "X_ACCEPT_DELAY_MIN"), ("accept_delay_max", "X_ACCEPT_DELAY_MAX")):
        if fr.get(key) is not None:
            out[env] = str(int(fr[key]))
    for env, value in (("X_LOCALE", x.get("locale") or bot.get("locale")),
                       ("X_TIMEZONE", x.get("timezone") or bot.get("timezone")),
                       ("X_TRIGGER", bot.get("trigger")),
                       ("X_NIGHT_HOURS", (bot.get("night_invisible") or {}).get("hours"))):
        if value:
            out[env] = str(value)
    return {k: v for k, v in out.items() if k not in os.environ}


def _reddit_env(cfg: dict) -> dict:
    """The reddit: section, and what Reddit takes from the persona's own settings, as the Reddit runner's
    environment (REDDIT_*). A value already in the environment (config/.env) wins, which is where its login
    lives."""
    reddit = cfg.get("reddit") or {}
    bot = cfg.get("bot") or {}

    def flag(v):
        return "true" if v else "false"

    out = {}
    plain = {
        "headless": "REDDIT_HEADLESS", "poll_interval_ms": "REDDIT_POLL_INTERVAL_MS",
        "response_timeout_ms": "REDDIT_RESPONSE_TIMEOUT_MS", "max_recipients": "REDDIT_MAX_RECIPIENTS",
        "min_send_gap_ms": "REDDIT_MIN_SEND_GAP_MS", "max_send_gap_ms": "REDDIT_MAX_SEND_GAP_MS",
        "max_sends_per_hour": "REDDIT_MAX_SENDS_PER_HOUR", "quiet_hours": "REDDIT_QUIET_HOURS",
        "reload_interval_ms": "REDDIT_RELOAD_INTERVAL_MS",
        "accept_chat_invites": "REDDIT_ACCEPT_CHAT_INVITES",
        # The one list that says where it may take part at all, and the check that it is not being hidden.
        "subreddits": "REDDIT_SUBREDDITS", "check_shadowban": "REDDIT_CHECK_SHADOWBAN",
        "dry_run": "REDDIT_DRY_RUN", "proxy": "REDDIT_PROXY",
    }
    for key, env in plain.items():
        v = reddit.get(key)
        if v is not None and v != "":
            out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Everything beyond answering a chat: its inbox, comments nobody asked for, what it puts up itself, what it
    # does about other people's posts, and what it reads of theirs.
    going_out = {
        "inbox": {"enabled": "REDDIT_INBOX", "replies": "REDDIT_INBOX_REPLIES",
                  "mentions": "REDDIT_INBOX_MENTIONS", "per_hour": "REDDIT_INBOX_PER_HOUR",
                  "per_pass": "REDDIT_INBOX_PER_PASS", "scrolls": "REDDIT_INBOX_SCROLLS",
                  "skip_strangers": "REDDIT_SKIP_STRANGERS"},
        "comments": {"enabled": "REDDIT_COMMENTS", "per_day": "REDDIT_COMMENTS_PER_DAY",
                     "max_chars": "REDDIT_COMMENT_MAX_CHARS", "fresh_only": "REDDIT_COMMENT_FRESH_ONLY",
                     "min_score": "REDDIT_COMMENT_MIN_SCORE", "skip_locked": "REDDIT_SKIP_LOCKED"},
        "posting": {"enabled": "REDDIT_POSTING", "where": "REDDIT_POST_WHERE", "per_day": "REDDIT_POSTS_PER_DAY",
                    "min_gap_minutes": "REDDIT_POST_MIN_GAP_MIN", "max_chars": "REDDIT_POST_MAX_CHARS",
                    "with_image": "REDDIT_POST_WITH_IMAGE", "flair": "REDDIT_POST_FLAIR"},
        "engage": {"upvote_sent": "REDDIT_UPVOTE_SENT", "upvote_theirs": "REDDIT_UPVOTE_THEIRS",
                   "save": "REDDIT_SAVE", "join_subs": "REDDIT_JOIN_SUBS",
                   "follow_users": "REDDIT_FOLLOW_USERS", "upvotes_per_day": "REDDIT_UPVOTES_PER_DAY",
                   "joins_per_day": "REDDIT_JOINS_PER_DAY", "follows_per_day": "REDDIT_FOLLOWS_PER_DAY",
                   "replies_per_day": "REDDIT_REPLIES_PER_DAY"},
        "watch": {"enabled": "REDDIT_WATCH", "their_posts": "REDDIT_THEIR_POSTS", "threads": "REDDIT_THREADS",
                  "links": "REDDIT_LINKS"},
    }
    for section, keys in going_out.items():
        block = reddit.get(section) or {}
        for key, env in keys.items():
            v = block.get(key)
            if v is not None and v != "":
                out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Where a post of its own comes from: one step further in than the rest (posting.from).
    where = ((reddit.get("posting") or {}).get("from") or {})
    for key, env in (("saw_online", "REDDIT_POST_FROM_WEB"), ("on_its_mind", "REDDIT_POST_FROM_MIND")):
        if where.get(key) is not None:
            out[env] = flag(where[key])
    # Chat invitations wait as Discord's friend requests do; the browser's clock and language are the persona's.
    fr = bot.get("friend_requests") or {}
    for key, env in (("accept_delay_min", "REDDIT_ACCEPT_DELAY_MIN"), ("accept_delay_max", "REDDIT_ACCEPT_DELAY_MAX")):
        if fr.get(key) is not None:
            out[env] = str(int(fr[key]))
    for env, value in (("REDDIT_LOCALE", reddit.get("locale") or bot.get("locale")),
                       ("REDDIT_TIMEZONE", reddit.get("timezone") or bot.get("timezone")),
                       ("REDDIT_TRIGGER", bot.get("trigger")),
                       ("REDDIT_NIGHT_HOURS", (bot.get("night_invisible") or {}).get("hours"))):
        if value:
            out[env] = str(value)
    return {k: v for k, v in out.items() if k not in os.environ}


def _whatsapp_env(cfg: dict) -> dict:
    """The whatsapp: section, and what WhatsApp takes from the persona's own settings, as the WhatsApp runner's
    environment (WHATSAPP_*). A value already in the environment (config/.env) wins, which is where its number
    lives."""
    wa = cfg.get("whatsapp") or {}
    bot = cfg.get("bot") or {}

    def flag(v):
        return "true" if v else "false"

    out = {}
    plain = {
        "poll_interval_ms": "WHATSAPP_POLL_INTERVAL_MS", "response_timeout_ms": "WHATSAPP_RESPONSE_TIMEOUT_MS",
        "burst_ms": "WHATSAPP_BURST_MS", "accept_unknown": "WHATSAPP_ACCEPT_UNKNOWN",
        "min_send_gap_ms": "WHATSAPP_MIN_SEND_GAP_MS", "max_send_gap_ms": "WHATSAPP_MAX_SEND_GAP_MS",
        "max_sends_per_hour": "WHATSAPP_MAX_SENDS_PER_HOUR", "quiet_hours": "WHATSAPP_QUIET_HOURS",
        "dry_run": "WHATSAPP_DRY_RUN",
    }
    for key, env in plain.items():
        v = wa.get(key)
        if v is not None and v != "":
            out[env] = flag(v) if isinstance(v, bool) else str(v)
    # Everything beyond answering a message: what it shows of itself, its groups, its statuses, what it does
    # about a call, and what it is willing to send.
    blocks = {
        "presence": {"online": "WHATSAPP_ONLINE", "typing": "WHATSAPP_TYPING",
                     "read_receipts": "WHATSAPP_READ_RECEIPTS"},
        "groups": {"enabled": "WHATSAPP_GROUPS", "only_when_named": "WHATSAPP_ONLY_WHEN_NAMED",
                   "max_per_pass": "WHATSAPP_GROUPS_PER_PASS", "leave_on_request": "WHATSAPP_LEAVE_ON_REQUEST"},
        "status": {"watch": "WHATSAPP_STATUS_WATCH", "post": "WHATSAPP_STATUS_POST",
                   "per_day": "WHATSAPP_STATUS_PER_DAY"},
        "calls": {"decline": "WHATSAPP_DECLINE_CALLS", "say_why": "WHATSAPP_CALL_SAY_WHY",
                  "text": "WHATSAPP_CALL_TEXT"},
        "media": {"voice_notes": "WHATSAPP_VOICE_NOTES", "pictures": "WHATSAPP_PICTURES"},
        "watch": {"enabled": "WHATSAPP_WATCH", "their_status": "WHATSAPP_THEIR_STATUS"},
    }
    for section, keys in blocks.items():
        block = wa.get(section) or {}
        for key, env in keys.items():
            v = block.get(key)
            if v is not None and v != "":
                out[env] = flag(v) if isinstance(v, bool) else str(v)
    # The names it answers to in a group, and the clock it keeps, are the persona's.
    for env, value in (("WHATSAPP_LOCALE", wa.get("locale") or bot.get("locale")),
                       ("WHATSAPP_TIMEZONE", wa.get("timezone") or bot.get("timezone")),
                       ("WHATSAPP_TRIGGER", bot.get("trigger")),
                       ("WHATSAPP_NIGHT_HOURS", (bot.get("night_invisible") or {}).get("hours"))):
        if value:
            out[env] = str(value)
    return {k: v for k, v in out.items() if k not in os.environ}


def _imessage_env(cfg: dict) -> dict:
    """The imessage: section, and the persona's names (bot.trigger, for group chats), as the iMessage runner's
    environment (IMESSAGE_*). A value already in the environment (.env) wins, which is where its server and its
    password live."""
    im = cfg.get("imessage") or {}
    bot = cfg.get("bot") or {}
    plain = {
        "min_send_gap_ms": "IMESSAGE_MIN_SEND_GAP_MS", "max_send_gap_ms": "IMESSAGE_MAX_SEND_GAP_MS",
        "max_sends_per_hour": "IMESSAGE_MAX_SENDS_PER_HOUR", "quiet_hours": "IMESSAGE_QUIET_HOURS",
        "poll_interval_ms": "IMESSAGE_POLL_INTERVAL_MS", "response_timeout_ms": "IMESSAGE_RESPONSE_TIMEOUT_MS",
        "read_receipts": "IMESSAGE_READ_RECEIPTS", "typing_indicator": "IMESSAGE_TYPING",
        "tapbacks": "IMESSAGE_TAPBACKS", "groups": "IMESSAGE_GROUPS", "answer_sms": "IMESSAGE_ANSWER_SMS",
        "voice_notes": "IMESSAGE_VOICE_NOTES", "facetime_text": "IMESSAGE_CALL_TEXT",
        "send_method": "IMESSAGE_SEND_METHOD", "thread_replies": "IMESSAGE_THREAD_REPLIES",
        "burst_ms": "IMESSAGE_BURST_MS", "dry_run": "IMESSAGE_DRY_RUN",
        "effects": "IMESSAGE_EFFECTS", "fix_typos": "IMESSAGE_FIX_TYPOS",
    }
    out = {}
    for key, env in plain.items():
        v = im.get(key)
        if v is not None and v != "":
            out[env] = ("true" if v else "false") if isinstance(v, bool) else str(v)
    if bot.get("trigger"):
        out["IMESSAGE_TRIGGER"] = str(bot["trigger"])
    return {k: v for k, v in out.items() if k not in os.environ}


_TG: dict = {}


def _telegram_cfg() -> dict:
    """The telegram: settings, with anything set in .env winning, as the runners' env does elsewhere."""
    try:
        cfg = (load_config() or {}).get("telegram") or {}
    except Exception:
        cfg = {}
    from app.platforms.telegram.client import settings as tg_settings
    return tg_settings(cfg)


def _imessage_cfg() -> dict:
    try:
        return (load_config() or {}).get("imessage") or {}
    except Exception:
        return {}


def _on_changed(msg: dict) -> None:
    """A message unsent, or edited, on the platform (iMessage's, read through BlueBubbles): kept in the chat log and
    marked, as Discord's are, so the Chats tab shows it struck through with a bin, or with its new words."""
    key = str(msg.get("key") or "")
    try:
        if msg.get("kind") == "unsent":
            uid = chatlog.mark_deleted(LOG_ACCOUNT, key)
            if uid:
                _emit_chat({"t": "deleted", "uid": str(uid), "mid": key, "at": time.time()})
        else:
            text = str(msg.get("text") or "")[:2000]
            uid = chatlog.mark_edited(LOG_ACCOUNT, key, {"text": text})
            if uid:
                _emit_chat({"t": "edited", "uid": str(uid), "mid": key, "text": text, "at": time.time()})
    except Exception as e:
        log_error(f"{PLATFORM_NAME} chat log", str(e))


def _to_mp3(wav: Path) -> Path | None:
    """A voice message as iMessage takes one from here: an MP3, which BlueBubbles makes Apple's own on the Mac. ffmpeg
    makes it (installed from the System page); None without it, and the words go instead."""
    try:
        from app.utils import binaries
        from app.utils.procs import quiet_kwargs
        ffmpeg = binaries.find("ffmpeg")
        if not ffmpeg:
            log_system("No ffmpeg on this computer (System page), so the reply goes as words, not a voice message")
            return None
        mp3 = wav.with_suffix(".mp3")
        r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "64k",
                            "-ac", "1", str(mp3)], capture_output=True, timeout=60, **quiet_kwargs())
        if r.returncode != 0 or not mp3.is_file():
            log_error(f"{PLATFORM_NAME} voice message", (r.stderr or b"").decode("utf-8", "replace")[-300:])
            return None
        return mp3
    except Exception as e:
        log_error(f"{PLATFORM_NAME} voice message", str(e))
        return None
    finally:
        try:
            wav.unlink()
        except OSError:
            pass


def _relay_node_output(proc):
    """The runner's own lines, into this process's output, which is what the panel's Logs read. Started with no window and nothing redirected, Node on Windows got a console of its own that nobody could see: everything it said about logging in (each step, a verification it was waiting on, why it failed) went nowhere, and the Snapchat log showed the bridge starting and then nothing at all."""
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.strip():
                with _OUT_LOCK:
                    sys.stdout.write(line + "\n")
                    sys.stdout.flush()
    except Exception:
        pass


# ── Minecraft ────────────────────────────────────────────────────────────────
# The same bridge, with no inbox: mindcraft-ce plays, and asks the brain served here what to say and do
# (app/platforms/minecraft/brain.py). What is said in the game comes back through the brain (_mc_turn) and is kept in
# the chat log as a conversation per player, as every platform's conversations are.
_MC: dict = {}


def _mc_state(state: str, detail: str = "") -> None:
    """The account's state for its card, from here, before its runner is up to say it itself (runner_core setState)."""
    try:
        _write_json(IPC_DIR / f"mc_state{_SFX}.json",
                    {"state": state, "detail": detail, "at": time.time(), "account": ACCOUNT_INDEX})
    except Exception:
        pass


def _mc_listening(name: str) -> bool:
    """Whether the persona answers now: not with the account paused, nor a player ignored or paused from the panel."""
    if STATE["paused"]:
        return False
    if not name:
        return True
    uid = _people.minecraft_id(name)
    return uid not in STATE["ignore_users"] and uid not in STATE["paused_users"]


_MC_SEEN: dict = {}


def _mc_contact(uid: str, name: str) -> None:
    """A player, in the people list the panel names them from (snappeople.contacts), as other runners record theirs.
    Written when someone is new, or not seen for ten minutes."""
    now = time.time()
    if now - _MC_SEEN.get(uid, 0) < 600:
        return
    _MC_SEEN[uid] = now
    try:
        path = _people.MINECRAFT_PEOPLE_DIR / f"contacts_{ACCOUNT_INDEX}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _read_json(path, {})
        data = data if isinstance(data, dict) else {}
        data[uid] = {**(data.get(uid) or {}), "name": name, "seen": now}
        _write_json(path, data)
        _mc_face_soon(uid, name, data[uid])
    except Exception as e:
        log_error(PLATFORM_NAME, f"Could not keep {name} in its people: {e}")


_MC_FACES: set = set()      # being drawn right now


def _mc_face_soon(uid: str, name: str, row: dict) -> None:
    """Their picture drawn from their skin, behind whatever asked: Mojang can take seconds to answer. About once a day
    for each, since people change their skins."""
    if uid in _MC_FACES or time.time() - float(row.get("face_at") or 0) < 86400:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _MC_FACES.add(uid)
    loop.create_task(_mc_face(uid, name))


async def _mc_face(uid: str, name: str) -> None:
    try:
        from app.platforms.minecraft import skins
        folder = _people.MINECRAFT_PEOPLE_DIR
        file = await asyncio.to_thread(skins.save_player_picture, ACCOUNT_INDEX, uid, name, folder)
        path = folder / f"contacts_{ACCOUNT_INDEX}.json"
        data = _read_json(path, {})
        data = data if isinstance(data, dict) else {}
        data[uid] = {**(data.get(uid) or {}), "face_at": time.time(), **({"file": file} if file else {})}
        _write_json(path, data)
    except Exception as e:
        log_error(PLATFORM_NAME, f"{name}'s picture could not be made: {e}")
    finally:
        _MC_FACES.discard(uid)


async def _mc_faces_of_everyone() -> None:
    """The people it already knows who have no picture yet, or an old one, a few seconds apart: they may not talk to it
    again for days, and they are on the Chats tab meanwhile."""
    path = _people.MINECRAFT_PEOPLE_DIR / f"contacts_{ACCOUNT_INDEX}.json"
    data = _read_json(path, {})
    for uid, row in list(data.items() if isinstance(data, dict) else ()):
        if isinstance(row, dict) and row.get("name") and time.time() - float(row.get("face_at") or 0) >= 86400:
            await _mc_face(uid, str(row["name"]))
            await asyncio.sleep(3)


def _mc_turn(name: str, said: str, reply: str, channel: str) -> None:
    """A line said to it in the game and its answer (said is "" for a line it says after acting), into the chat log
    under the player's own conversation, and to the Chats tab."""
    from app.platforms.minecraft import worker as mcw
    uid = _people.minecraft_id(name)
    if not uid:
        return
    CHAT_NAMES[uid] = name
    _mc_contact(uid, name)
    now = time.time()
    rows, fresh = [], []
    for mine, text in ((False, str(said or "").strip()), (True, mcw.chat_text(reply))):
        if not text:
            continue
        mid, ts = f"mc-{_uuid.uuid4().hex[:16]}", now + (0.001 if mine else 0)
        rows.append((mid, mine, ts, {"text": text[:2000]}))
        fresh.append({"mid": mid, "mine": mine, "ts": ts, "text": text[:2000]})
    if rows:
        try:
            chatlog.put_many(LOG_ACCOUNT, uid, rows)
        except Exception as e:
            log_error("Minecraft chat log", str(e))
        _announce(uid, name, fresh)


async def _mc_send_cmd(cmd_id: str, payload: dict) -> None:
    """Words typed in the Chats tab, said in the game as the account's own, the way it says everything there: in
    the world's chat, or whispered to the players it only talks with. A player's conversation in the panel is then
    what was said in the game, word for word. mindcraft is handed only an id (brain.say), so the words are never
    taken for a command on the way in."""
    from app.platforms.minecraft import worker as mcw
    # No player (Telegram's /mc say): the world's own conversation.
    chat = str(payload.get("user_id") or "") or f"mcs_{_MC.get('server') or 'world'}"
    text = str(payload.get("text") or "").strip()
    brain = _MC.get("brain")
    if payload.get("files"):
        _write_result(cmd_id, {"ok": False, "reason": "Minecraft's chat takes words only"})
        return
    if not text:
        _write_result(cmd_id, {"ok": False, "reason": "nothing to send"})
        return
    if brain is None:
        _write_result(cmd_id, {"ok": False, "reason": "Minecraft is not ready yet; try again in a moment"})
        return
    name = CHAT_NAMES.get(chat) or _name_for(chat) or _people.minecraft_username(chat)
    only = mcw.only_chat_with(_MC.get("mc") or {})
    sid, done = brain.say(text)
    # Who mindcraft is told it is from: anyone but itself, and someone it listens to when it only talks with some.
    sender = name if name in only else (only[0] if only else "system")
    r = await _panel("say", sid=sid, timeout=15.0, **{"from": sender})
    if not r.get("ok"):
        _write_result(cmd_id, {"ok": False, "reason": r.get("reason") or "could not say it"})
        return
    try:
        await asyncio.wait_for(done.wait(), 30.0)
    except asyncio.TimeoutError:
        _write_result(cmd_id, {"ok": False, "reason": "mindcraft did not say it; it may be busy, try again"})
        return
    mid, ts = f"mc-{_uuid.uuid4().hex[:16]}", time.time()
    try:
        chatlog.put(LOG_ACCOUNT, chat, mid, True, ts, {"text": text[:2000]})
    except Exception as e:
        log_error("Minecraft chat log", str(e))
    _announce(chat, name, [{"mid": mid, "mine": True, "ts": ts, "text": text[:2000]}])
    # The persona's own words from now on, as if it had said them.
    if name:
        key = f"{chat}-{brain.channel_of(name)}"
        engine.message_history.setdefault(key, []).append({"role": "assistant", "content": text})
    log_system(f"You said to {name or chat} in Minecraft, from the panel")
    _write_result(cmd_id, {"ok": True, "mid": mid, "ts": ts, "text": text})


async def _mc_op_cmd(cmd_id: str, op: str, payload: dict) -> None:
    """The panel's and Telegram's other requests of a Minecraft account: what it is doing, something to get done,
    leaving the world and coming back."""
    kw = {}
    if op == "tell":
        from app.platforms.minecraft import worker as mcw
        text = str(payload.get("text") or "").strip()[:300]
        brain = _MC.get("brain")
        if not text:
            _write_result(cmd_id, {"ok": False, "reason": "what should it do?"})
            return
        if brain is None:
            _write_result(cmd_id, {"ok": False, "reason": "Minecraft is not ready yet; try again in a moment"})
            return
        only = mcw.only_chat_with(_MC.get("mc") or {})
        # Its own goal (brain.goal): mindcraft works at it by itself, a step at a time, until it is done or stopped.
        sid, done = brain.goal(text)
        r = await _panel("say", sid=sid, timeout=15.0, **{"from": only[0] if only else "system"})
        if r.get("ok"):
            try:
                await asyncio.wait_for(done.wait(), 30.0)
            except asyncio.TimeoutError:
                r = {"ok": False, "reason": "mindcraft did not take it; it may be busy, try again"}
            else:
                log_system(f"Minecraft goal, from the panel: {text}")
        _write_result(cmd_id, r if r.get("ok") else {"ok": False, "reason": r.get("reason") or "it did not answer"})
        return
    r = await _panel(op, timeout=15.0, **kw)
    _write_result(cmd_id, r if r.get("ok") else {"ok": False, "reason": r.get("reason") or "it did not answer"})


async def _minecraft_main():
    """A Minecraft account, from its brain to its runner. The brain is bound first and served on this loop, so
    mindcraft is only ever handed an address that already answers; while mindcraft is not installed, the card says
    so, and it starts the moment it is."""
    from app.platforms.minecraft import brain as mc_brain, install as mc_install, profile as mc_profile
    from app.platforms.minecraft import worker as mcw
    mc = mcw.section(load_config() or {})
    slot = mcw.slot(ACCOUNT_INDEX, mc)
    while not slot["name"]:
        _mc_state("needs-you", "Its name is not one Minecraft takes: 3 to 16 letters, digits or underscores.")
        await asyncio.sleep(60)
    server = mcw.server_id(slot["host"], slot["port"])
    brain = mc_brain.Brain(
        ACCOUNT_INDEX, server=server, public=not mcw.only_chat_with(mc),
        timeout_s=mcw._int(mc.get("brain_timeout_s"), 45, 5, 300),
        calls_per_hour=mcw._int(mc.get("max_brain_calls_per_hour"), 120, 10, 2000),
        persona="full" if str(mc.get("persona")) == "full" else "brief", greet=bool(mc.get("greet", True)),
        on_turn=_mc_turn)
    brain.listening = _mc_listening
    session = mcw.Session(brain)
    url = session.bind()
    _MC.update(mc=mc, slot=slot, server=server, brain=brain)
    serving = asyncio.create_task(session.serve())
    # Its picture for its card: its skin, standing in 3D (the premium account's of that name, else the default the
    # game gives the name), made off the loop since it asks Mojang. The name it was last seen playing as, where it
    # has been in a world before: a Microsoft account's own, which the name it was added under need not be.
    _MC["picture_for"] = _mc_played_as(slot)
    asyncio.create_task(_mc_picture(_MC["picture_for"]))
    asyncio.create_task(_mc_faces_of_everyone())

    said = 0.0
    while not (shutil.which("node") and mc_install.present()):
        if time.time() - said > 60:
            said = time.time()
            _mc_state("needs-you", "Minecraft support is not installed. Install it in Settings, Minecraft."
                      if shutil.which("node") else
                      "Node.js is not installed. Minecraft plays through it: install it from nodejs.org, then Minecraft support.")
        await asyncio.sleep(10)

    base = mc_profile.defaults()
    missing = mc_profile.missing_keys(base)
    if missing:
        log_error(PLATFORM_NAME, f"mindcraft's own profile no longer has {', '.join(missing)}; it plays, but on "
                                 "what was there. Reinstalling Minecraft support brings back the tested version.")
    prof = mc_profile.build(slot["name"], url, base=base, modes=mcw.modes(mc),
                            cooldown_ms=mcw._int(mc.get("cooldown_ms"), 2000, 0, 20000))
    _MC.update(profile_path=mc_profile.write(ACCOUNT_INDEX, prof), url=url, name=prof["name"])
    atexit.register(_kill_node_runner)
    _mc_start_runner(slot["host"], slot["port"])
    await serving


def _mc_start_runner(host: str, port: int) -> bool:
    """The runner, for this server: mindcraft's settings for it, its password there (for a server that asks in the
    chat), and version translation where the server needs it. The brain is as it was; only where it plays changes."""
    global _node_proc
    from app.platforms.minecraft import install as mc_install, viaproxy, worker as mcw
    from app.utils.paths import DATA_DIR
    mc, slot = _MC["mc"], _MC["slot"]
    target = {**slot, "host": str(host), "port": int(port)}
    server = mcw.server_id(host, port)
    _MC.update(target=target, server=server, started_at=time.time(), turned_away=0)
    _MC["brain"].server = server
    shown = f"{host}:{port}"
    extra = {"MC_VIEW_DISTANCE": mcw._int(mc.get("view_distance"), 6, 2, 12)}
    if mc.get("auto_login", True):
        try:
            extra["MC_SERVER_PASSWORD"] = mcw.server_password(_MC["name"], server)
        except Exception as e:
            log_error(PLATFORM_NAME, f"No password could be kept for {shown}, so it will not sign itself in there: {e}")
    via = viaproxy.config_for(host, port, target["auth"], str(mc.get("translate_versions") or "auto"))
    if via:
        extra["MC_VIAPROXY"] = json.dumps(via)
    _own_proxy = os.getenv(f"MINECRAFT_PROXY_{ACCOUNT_INDEX}", "").strip()
    if _own_proxy:
        extra["MC_PROXY"] = _own_proxy
    env = mcw.runner_env({
        "MINECRAFT_ACCOUNT_INDEX": ACCOUNT_INDEX, "MC_DATA_DIR": DATA_DIR, "MC_MINDCRAFT_DIR": mc_install.MC_DIR,
        "MC_BRAIN_URL": _MC["url"], "MC_AGENT_NAME": _MC["name"], "MC_CONTROL_TOKEN": mcw.new_control_token(),
        "MC_SERVER": shown, "MC_SETTINGS_JSON": json.dumps(mcw.mindcraft_settings(target, mc, _MC["profile_path"])),
        **extra,
    })
    runner = mcw.sync_runner()
    try:
        from app.utils.procs import quiet_kwargs
        _node_proc = subprocess.Popen([shutil.which("node"), str(runner)], cwd=str(runner.parent), env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      **quiet_kwargs())
        threading.Thread(target=_relay_node_output, args=(_node_proc,), daemon=True,
                         name="mc-node-output").start()
        log_system(f"Minecraft runner started (PID {_node_proc.pid}, account #{ACCOUNT_INDEX}): "
                   f"{_MC['name']} on {shown}, {target['auth']}" + (", through ViaProxy if it needs" if via else ""))
        return True
    except Exception as e:
        log_error(PLATFORM_NAME, f"Could not start the Minecraft runner: {e}")
        _mc_state("logged-out", f"Its runner could not start: {e}")
        return False


def _mc_played_as(slot: dict) -> str:
    """The name it plays as: the one the runner last saw it join a world as (identity_minecraft_<n>.json's in_game,
    minecraft_runner.mjs), else the one it was added under."""
    from app.utils.paths import DATA_DIR
    try:
        data = json.loads((DATA_DIR / "config" / f"identity_minecraft_{ACCOUNT_INDEX}.json").read_text(encoding="utf-8"))
        real = str((data or {}).get("in_game") or "").strip() if isinstance(data, dict) else ""
    except (OSError, ValueError):
        real = ""
    return real or str(slot.get("name") or "")


async def _mc_picture(name: str) -> None:
    try:
        from app.platforms.minecraft import skins
        r = await asyncio.to_thread(skins.save_picture, ACCOUNT_INDEX, name)
        if r.get("ok"):
            what = "its own skin" if r["source"] == "mojang" else f"the default skin the game gives the name, {r['skin'].capitalize()}"
            log_system(f"[Minecraft] Its picture: {what}")
    except Exception as e:
        log_error(PLATFORM_NAME, f"Its picture could not be made: {e}")


def _notify_owner(title: str, detail: str) -> None:
    """A word to the owner on Telegram, when its alerts are on: something it did, not something that went wrong."""
    try:
        entries = _read_json(CMD_FILE, [])
        entries = entries if isinstance(entries, list) else []
        entries.append({"id": f"info_{time.time()}", "cmd": "send_error_notification",
                        "payload": {"title": f"[{PLATFORM_NAME}] {title}", "detail": str(detail)[:1500], "kind": "info"},
                        "ts": time.time()})
        _write_json(CMD_FILE, entries)
    except Exception:
        pass


async def _mc_switch(host: str, port: int, why: str = "") -> dict:
    """Another server, or its own again: the runner, and mindcraft and the bot with it, start over there. The brain
    and everything it remembers stay."""
    if "brain" not in _MC or "url" not in _MC:
        return {"ok": False, "reason": "Minecraft is not ready yet; try again in a moment"}
    cur = _MC.get("target") or {}
    if str(cur.get("host", "")).lower() == str(host).lower() and int(cur.get("port") or 0) == int(port):
        return {"ok": True, "already": True, "server": f"{host}:{port}"}
    _MC["switching"] = True
    try:
        _kill_node_runner()
        await asyncio.sleep(1.5)
        started = _mc_start_runner(host, port)
    finally:
        _MC["switching"] = False
    log_system(f"Minecraft: going to {host}:{port}" + (f", {why}" if why else ""))
    return {"ok": started, "server": f"{host}:{port}"} if started else {"ok": False, "reason": "its runner did not start"}


async def _mc_turned_away(reason: str) -> None:
    """Kicked, or not let in, by a server other than its own: back to its own as soon as trying again is no use (a
    server that wants a Microsoft account, a ban), or after a few times, and the owner told. Asked in a DM to play on a
    server it cannot get into, it would otherwise try there for good. On its own server it keeps trying, as always."""
    from app.platforms.minecraft import worker as mcw
    slot, cur = _MC.get("slot") or {}, _MC.get("target") or {}
    if _MC.get("switching") or not mcw.away(slot, cur):
        return
    spawned = _MC.get("in_world_at", 0)
    if spawned > _MC.get("started_at", 0) and time.time() - spawned > 600:
        _MC["turned_away"] = 0          # after a good while playing there: trouble anew, not the same again
    _MC["turned_away"] = _MC.get("turned_away", 0) + 1
    if not mcw.refused_for_good(reason) and _MC["turned_away"] < 3:
        return
    where, home = f"{cur.get('host')}:{cur.get('port')}", f"{slot.get('host')}:{slot.get('port')}"
    log_system(f"Minecraft: {where} would not have it ({reason or 'no reason given'}); back to {home}")
    r = await _mc_switch(str(slot.get("host")), int(slot.get("port") or 25565), f"back from {where}")
    if r.get("ok"):
        why = reason.strip().rstrip(".!")
        _notify_owner("Back on its own server", f"{_MC.get('name', 'It')} could not play on {where}"
                      f"{': ' + why if why else ''}. It went back to {home}.")


async def _mc_join_cmd(cmd_id: str, payload: dict) -> None:
    """Joining a server: asked from the panel or Telegram (by its owner), or by someone its persona talks to, on any
    platform, who it said yes to (engine.py, its [MC JOIN ...]). The latter only while Settings lets it, never to a
    server Settings rules out, and the owner is told where it went and who asked."""
    from app.platforms.minecraft import worker as mcw
    mc = _MC.get("mc") or mcw.section(load_config() or {})
    address = str(payload.get("address") or "").strip()
    by_owner = bool(payload.get("by_owner"))
    if address.lower() in ("home", "back", "its own", "own"):
        slot = _MC.get("slot") or {}
        hostport = (slot.get("host"), slot.get("port")) if slot else None
    else:
        hostport = mcw.parse_address(address)
    if not hostport or not hostport[0]:
        _write_result(cmd_id, {"ok": False, "reason": f"Not a server address: {address[:60]}"})
        return
    host, port = hostport
    if not by_owner and not mc.get("join_when_asked", True):
        _write_result(cmd_id, {"ok": False, "reason": "Joining servers when asked is off in Settings, Minecraft"})
        return
    if mcw.blocked(host, mc):
        _write_result(cmd_id, {"ok": False, "reason": f"{host} is on the list of servers it never joins"})
        return
    if (_MC.get("slot") or {}).get("auth") != "microsoft" and mcw.needs_microsoft(host):
        _write_result(cmd_id, {"ok": False, "reason": f"{host} lets in Microsoft accounts only, and this one signs "
                                                      "in offline"})
        return
    who = str(payload.get("asked_by") or "").strip()
    where = str(payload.get("platform") or "").strip()
    why = f"asked by {who}{' on ' + where if where else ''}" if who else ("from the panel" if by_owner else "")
    r = await _mc_switch(host, int(port), why)
    if r.get("ok") and not r.get("already") and not by_owner:
        _notify_owner("Joining another server", f"{_MC.get('name', 'It')} is going to {host}:{port}, {why or 'asked to'}.")
    _write_result(cmd_id, r)


def run():
    """Entry point, initialise all subsystems, launch the Node runner, then loop."""
    _print_banner()
    log_system("Initialising…")
    init_db()
    init_ai()
    init_memory()
    # Load persisted ignored chat ids
    try:
        STATE["ignore_users"] = {str(u) for u in get_ignored_users_snap()}
    except Exception:
        pass
    if TELEGRAM:
        log_system("[Telegram] Signing in to its Telegram account.")
    elif PHONE:
        log_system(f"[iMessage] Account #{ACCOUNT_INDEX} reads through your iPhone: its Shortcuts automation sends "
                   "each message here, and takes the answer back.")
    elif not MINECRAFT:
        # Minecraft's runner starts from its own loop (_minecraft_main), once its brain is listening.
        _spawn_node_runner()
    log_system(f"Bridge ready, waiting for messages from the {PLATFORM_NAME} runner")
    separator()
    code = 0
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        log_system("Shutting down…")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    # Straight out, the browser closed first: the interpreter's own exit waits
    # without a limit for worker threads still busy (see _main_async).
    _exit_now(code)


if __name__ == "__main__":
    run()
