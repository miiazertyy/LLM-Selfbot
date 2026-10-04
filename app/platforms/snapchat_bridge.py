"""Python side of the Snapchat bridge: Node runner <-> JSON IPC files <-> this bridge -> engine -> Groq. IPC files live in ipc/: snap_incoming (Node writes, we read), snap_responses (we write replies, Node sends), snap_outgoing (proactive sends like /reply), snap_processed (ids already handled), plus tg_commands_snap / tg_results_snap for the Telegram controller. Same AI brain, memory, mood, leaderboard and pictures as Discord."""

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
from app.core.engine import generate_ai_response, IncomingMessage
from app.utils.ai import init_ai, generate_response, transcribe_voice, ModelWontLoad
from app.utils.db import (
    init_db,
    get_ignored_users_snap,
    add_ignored_user_snap,
    remove_ignored_user_snap,
    get_leaderboard_snap,
)
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

# ── Snapchat message IPC files live in ipc/ (created on import) ───────────────
IPC_DIR = Path(resource_path("ipc"))
IPC_DIR.mkdir(parents=True, exist_ok=True)

# one bridge per account (SNAP_ACCOUNT_INDEX, 1-based); account 1 keeps the legacy files, 2+ get _N
ACCOUNT_INDEX = int(os.getenv("SNAP_ACCOUNT_INDEX", "1") or "1")
_SFX    = "" if ACCOUNT_INDEX == 1 else f"_{ACCOUNT_INDEX}"
_TG_SFX = "snap" if ACCOUNT_INDEX == 1 else f"snap{ACCOUNT_INDEX}"

INCOMING_FILE  = IPC_DIR / f"snap_incoming{_SFX}.json"
RESPONSES_FILE = IPC_DIR / f"snap_responses{_SFX}.json"
OUTGOING_FILE  = IPC_DIR / f"snap_outgoing{_SFX}.json"
PROCESSED_FILE = IPC_DIR / f"snap_processed{_SFX}.json"
# Messages the bot set out to answer and has not, for nudges: {chat id: {"content", "received_at", "nudged"}}, as the
# Discord side keeps them in its unresponded_messages table.
UNANSWERED_FILE = IPC_DIR / f"snap_unanswered{_SFX}.json"

# Telegram control IPC (kept in ipc/ alongside the other Snapchat IPC files)
CMD_FILE    = IPC_DIR / f"tg_commands_{_TG_SFX}.json"
RESULT_FILE = IPC_DIR / f"tg_results_{_TG_SFX}.json"
UPDATE_FLAG = Path(resource_path(f"config/update_{_TG_SFX}.flag"))

# wake channel: the JSON files stay the transport (durable, survive restarts, keep working) but can't tell the other side something arrived, so both ends polled and a reply waited ~4s before the model ran. loopback socket just says "look again now": no state, so losing it costs latency, never data, and both sides still poll underneath. port 0 = OS picks a free one (published in PORT_FILE), no account collisions.
PORT_FILE      = IPC_DIR / f"snap_port{_SFX}"

POLL_INTERVAL    = 2.0    # seconds between incoming-message polls
# Snapchat's own chats, never answered (the runner leaves them out of its passes too).
_SYSTEM_CHATS = {"my ai", "team snapchat"}
TG_POLL_INTERVAL = 2.0    # seconds between Telegram command polls
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
from app.utils import snappeople
from app.core.launcher import under_panel as _under_panel

LOG_ACCOUNT = chatlog.SNAP_BASE + ACCOUNT_INDEX
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
    if not _node_writers:
        return {"ok": False, "reason": "Snapchat is not ready yet; try again in a moment"}
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
        return {"ok": False, "reason": "Snapchat did not answer in time; it may be busy, try again"}
    finally:
        _PANEL_WAITERS.pop(rid, None)


def _day_start(iso: str) -> float:
    try:
        return datetime.combine(date.fromisoformat(iso), _dtime.min).timestamp()
    except (TypeError, ValueError):
        return time.time() - 86400


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
            kind = str(m.get("kind") or "")
            text = str(m.get("text") or "")[:2000]
            body = {"text": text or (f"[{kind}]" if kind else ""), "kind": kind}
            links = [{"url": str(l.get("url")), "title": str(l.get("title") or "")[:140]}
                     for l in (m.get("links") or []) if isinstance(l, dict) and str(l.get("url") or "").startswith("http")]
            if links:
                body["embeds"] = links[:3]
            if m.get("reactions"):
                body["reactions"] = _clean_reactions(m["reactions"])
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
        kind = str(m.get("kind") or "")
        text = str(m.get("text") or "")[:2000]
        body = {"text": text or (f"[{kind}]" if kind else ""), "kind": kind}
        links = [{"url": str(l.get("url")), "title": str(l.get("title") or "")[:140]}
                 for l in (m.get("links") or []) if isinstance(l, dict) and str(l.get("url") or "").startswith("http")]
        if links:
            body["embeds"] = links[:3]
        if m.get("reactions"):
            body["reactions"] = _clean_reactions(m["reactions"])
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


def _spawn_panel(coro) -> None:
    task = asyncio.create_task(coro)
    _PANEL_TASKS.add(task)
    task.add_done_callback(_PANEL_TASKS.discard)


# Snapchat's reactions, in the order its picker shows them: the only ones it has, one per person on a message.
SNAP_REACTIONS = ("❤️", "😂", "🔥", "👍", "👎", "😰", "🤯", "❓")


async def _react_cmd(cmd_id: str, payload: dict) -> None:
    """A reaction from the Chats tab, on a message in a conversation: the runner hovers it on Snapchat's page and
    picks from React, as a person does (react in snapchat_runner.js). Kept in the chat log, and shown live."""
    chat = str(payload.get("user_id") or "")
    key = str(payload.get("mid") or "")
    emoji = str(payload.get("emoji") or "")
    if emoji not in SNAP_REACTIONS:
        _write_result(cmd_id, {"ok": False, "reason": "Snapchat only has " + " ".join(SNAP_REACTIONS)})
        return
    r = await _panel("react", chat=chat, name=_name_for(chat), key=key, emoji=emoji,
                     remove=bool(payload.get("remove")), timeout=65.0)
    if not r.get("ok"):
        _write_result(cmd_id, {"ok": False, "reason": r.get("reason") or "Snapchat did not take it"})
        return
    reactions = _clean_reactions(r.get("reactions"))
    if chatlog.set_reactions(LOG_ACCOUNT, key, reactions) is not None:
        _emit_chat({"t": "reactions", "uid": chat, "mid": key, "reactions": reactions})
    _write_result(cmd_id, {"ok": True, "reactions": reactions})


async def _history_cmd(cmd_id: str, payload: dict) -> None:
    """The Chats tab opening a conversation: read from the page, kept, and given back as the tab draws it."""
    chat = str(payload.get("user_id") or "")
    limit = max(5, min(200, int(payload.get("limit") or 25)))
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


_PICTURE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


_REPLY_TASKS: dict = {}


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


async def _send_cmd(cmd_id: str, payload: dict) -> None:
    """A message typed in the Chats tab, sent as this account: words, and pictures as Snaps. A reply the bot had lined
    up for them is dropped, and what was sent goes into the bot's history as the account's own words."""
    chat = str(payload.get("user_id") or "")
    text = str(payload.get("text") or "").strip()[:2000]
    paths = []
    try:
        for f in (payload.get("files") or [])[:4]:
            name = os.path.basename(str((f or {}).get("name") or "picture.png"))
            ext = os.path.splitext(name)[1].lower()
            if ext not in _PICTURE_TYPES:
                _write_result(cmd_id, {"ok": False, "reason": f"{name}: Snapchat takes pictures from here"})
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
        r = await _panel("send", chat=chat, text=text, images=paths, name=name, timeout=150.0)
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
    _write_result(cmd_id, {"ok": True, "mid": key, "ts": ts, "text": text, "dropped_reply": dropped})


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
            row = conn.execute("SELECT username FROM message_log_snap WHERE chat_id = ? ORDER BY ts DESC LIMIT 1",
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
        log_system(f"Snapchat wake channel unavailable ({e}); polling only")
        return

    port = server.sockets[0].getsockname()[1]
    try:
        PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(port), encoding="utf-8")
    except OSError as e:
        log_system(f"Could not publish the wake port ({e}); polling only")
        return
    log_system(f"Snapchat wake channel listening on 127.0.0.1:{port}")
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


def _append_response(msg_id: str, text: str, chat_id: str = None, name: str = None):
    """Write an AI reply for the Node runner to send; the chat id rides along so it's self-routing even after a Node restart."""
    responses = _read_json(RESPONSES_FILE, {})
    if chat_id:
        responses[msg_id] = {"text": text, "chat": str(chat_id), "name": name or str(chat_id)}
    else:
        responses[msg_id] = text  # legacy string form
    _write_json(RESPONSES_FILE, responses)
    # file's already durable, this just saves Node the wait for its next drain tick; no-op if nothing's connected
    _poke_node("response")


def _queue_outgoing(chat_id: str, text: str, image: str = None):
    """Queue a proactive message (and/or picture Snap) for the Node runner."""
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
        sent = await looks.touched_copy(path, description, recent, reply, f"snapchat_{ACCOUNT_INDEX}", lang,
                                        their_name=msg.user_name, platform="Snapchat")
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
            "payload": {"title": f"[Snapchat] {title}", "detail": str(detail)[:1500]},
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
    processed = _processed_list()
    if msg_id not in processed:
        processed.append(msg_id)
    if len(processed) > 500:
        del processed[:-500]
    # still written every mark: a mid-pass crash must not make the bot answer the same message twice
    _write_json(PROCESSED_FILE, processed)


# ── Incoming-message polling loop ────────────────────────────────────────────
async def process_incoming():
    """Read new Snapchat messages and generate AI responses (respecting pause/ignore)."""
    log_system("Snapchat bridge started, polling for messages")

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

            if user_id:
                CHAT_NAMES[user_id] = user_name

            # Snapchat's own chats: there is nobody there to answer.
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
                engine.add_user_message(user_id, channel_id, content or "📸 sent a snap")
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
                engine.add_user_message(user_id, channel_id, content or "📸 sent a snap")
                log_system(f"Ignored message from {user_name} (chance skip)")
                _set_state(channel_id, "skipped", reason="left unanswered on purpose (the ignore chance)")
                _mark_processed(msg_id)
                continue

            _seed_history(channel_id, ts)

            msg = IncomingMessage(
                platform="snapchat",
                user_id=user_id,
                user_name=user_name,
                channel_id=channel_id,
                content=content,
                image_url=image_url,
                is_private=True,  # Snapchat messages are always DMs
                wait_time=age,
                # So the reply is logged against this account, not just "Snapchat".
                extra={"account": ACCOUNT_INDEX},
            )

            log_incoming(user_name, "Snapchat DM", "Snapchat", content)

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

            if response and _held_back(channel_id, user_name, began):
                response = None
            elif response:
                response = _humanize_reply(response)
                log_response(user_name, response)
                separator()
                # A person reads the message and thinks before answering. The
                # Node side adds the send gap, this is the read/think part.
                think = random.uniform(3.0, 10.0)
                if random.random() < 0.12:
                    think += random.uniform(20.0, 90.0)
                _set_state(channel_id, "cooldown", eta=time.time() + think)
                await asyncio.sleep(think)
                if not _held_back(channel_id, user_name, began):
                    _append_response(msg_id, response, channel_id, user_name)
                    await _queue_picture_if_any(msg, response)
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
    raw = os.environ.get("SNAP_QUIET_HOURS", "")
    if not raw:
        try:
            raw = str((load_config().get("snapchat") or {}).get("quiet_hours") or "")
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
                               "reason": "Not supported on Snapchat."})
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
        _write_result(cmd_id, {
            "paused": STATE["paused"],
            "mood": mood_mod.current_mood,
            "active_channels": len(CHAT_NAMES),
            "ignored_users": len(STATE["ignore_users"]),
            # Inside its quiet hours it reads but does not send: the panel says so, as it does Discord's night hours.
            "night": _quiet_now(),
        })

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

    elif cmd == "chat_history":
        # Off the command loop: the runner reads it between its own steps, which can take a few seconds.
        _spawn_panel(_history_cmd(cmd_id, payload))

    elif cmd == "friends_pending":
        _spawn_panel(_friends_cmd(cmd_id))

    elif cmd in ("friend_accept", "friend_decline"):
        _spawn_panel(_friend_answer_cmd(cmd_id, str(payload.get("user_id") or ""), cmd == "friend_accept"))

    elif cmd == "send_message":
        _spawn_panel(_send_cmd(cmd_id, payload))

    elif cmd == "react":
        _spawn_panel(_react_cmd(cmd_id, payload))

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
        log_system("Restart requested via Telegram (Snapchat)")
        _write_result(cmd_id, {"ok": True})
        # Spawn the replacement before exiting, os._exit() skips atexit handlers.
        _kill_node_runner()  # close the OLD browser before the new bridge spawns one
        try:
            from app.core.launcher import spawn_role
            spawn_role("snapchat", ACCOUNT_INDEX, capture=False)
        except Exception as e:
            log_error("Snap restart", str(e))
        await asyncio.sleep(1)
        os._exit(0)

    elif cmd == "shutdown":
        log_system("Shutdown requested via Telegram (Snapchat)")
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
            platform="snapchat",
            user_id=chat_id,
            user_name=name,
            channel_id=chat_id,
            content=combined,
            is_private=True,
            wait_time=0.0,
            extra={"account": ACCOUNT_INDEX},
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
    log_system("Telegram IPC bridge started (Snapchat)")

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


async def _main_async():
    cfg = load_config()
    tasks = [process_incoming(), tg_command_loop(), _cleanup_loop(), _wake_server(), _nudge_loop()]

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
        log_error("Snapchat", "The bridge hit an error it could not carry on from; it restarts.")
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
    set_theme("snapchat")
    try:
        width = shutil.get_terminal_size().columns
    except Exception:
        width = 60
    width = max(40, min(width, 100))
    border = "═" * (width - 2)
    title = "Snapchat AI Bridge"
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
    for name in ("snapchat_runner.js", "snapbot.js", "log.js", "package.json",
                 "discord_token.js"):
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
    """Launch the Node runner as a child in THIS console; SNAP_SPAWN_NODE=false runs it yourself, and the snapchat config section maps into the runner env (.env wins)."""
    global _node_proc
    if os.getenv("SNAP_SPAWN_NODE", "true").lower() == "false":
        log_system("Node runner auto-start disabled (SNAP_SPAWN_NODE=false), start it yourself.")
        return

    node_exe = shutil.which("node")
    if not node_exe:
        log_error("Snapchat", "Node.js not found in PATH - install it from nodejs.org or "
                              "use the Snapchat page in the web UI.")
        return

    runner_dir = _sync_node_runner()
    runner_js = os.path.join(runner_dir, "snapchat_runner.js")
    if not os.path.exists(runner_js):
        log_error("Snapchat", f"Runner not found: {runner_js}")
        return
    if not os.path.isdir(os.path.join(runner_dir, "node_modules")):
        log_error("Snapchat", "Node deps not installed - use the Snapchat page in the "
                              "web UI, or: cd platforms/snapchat && npm install")
        return

    # node_modules alone isn't enough: Puppeteer's Chrome is a separate postinstall step, and a half-finished one makes deps look complete while every launch dies with "Could not find Chrome"
    try:
        from app.web.routes.system_routes import chrome_path
        if not chrome_path():
            log_error("Snapchat",
                      "Puppeteer's Chrome is missing or was only partly downloaded. "
                      "Open the Snapchat page in the app and run the installer again, "
                      "it clears the partial download and refetches it.")
            return
    except Exception:
        pass        # never block startup on the probe itself

    # ── config.yaml snapchat section → env (only where .env didn't set one) ──
    from app.utils.paths import DATA_DIR
    node_env = {**os.environ, "SNAP_ACCOUNT_INDEX": str(ACCOUNT_INDEX)}
    # Drive the browser this machine already has, when it has one. Puppeteer
    # reads this variable itself, so pointing it at an installed Chrome or Edge
    # is the whole integration - and a browser a person actually uses is a
    # better thing to be driving than Chrome for Testing, which is its own
    # distinct build.
    try:
        from app.web.routes.system_routes import installed_browser
        _bname, _bpath = installed_browser()
        if _bpath and "PUPPETEER_EXECUTABLE_PATH" not in os.environ:
            node_env["PUPPETEER_EXECUTABLE_PATH"] = _bpath
            log_system(f"Snapchat browser: {_bname} ({_bpath})")
    except Exception:
        pass
    # point Node at the writable data dir for cookies/profile/temp media, and the real .env
    node_env["SNAP_DATA_DIR"] = str(DATA_DIR)
    node_env["SNAP_DOTENV_PATH"] = os.path.join(DATA_DIR, "config", ".env")
    try:
        snap_cfg = load_config().get("snapchat") or {}
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
    except Exception:
        pass

    try:
        import threading
        from app.utils.procs import quiet_kwargs
        _node_proc = subprocess.Popen([node_exe, runner_js], cwd=runner_dir, env=node_env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, **quiet_kwargs())
        threading.Thread(target=_relay_node_output, args=(_node_proc,), daemon=True,
                         name="snap-node-output").start()
        atexit.register(_kill_node_runner)
        log_system(f"Node runner started (PID {_node_proc.pid}, account #{ACCOUNT_INDEX})")
    except Exception as e:
        log_error("Snapchat", f"Could not start Node runner: {e}")


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


def run():
    """Entry point, initialise all subsystems, launch the Node runner, then loop."""
    _print_banner()
    log_system("Initialising…")
    init_db()
    init_ai()
    init_memory()
    # Load persisted Snapchat ignored chat ids
    try:
        STATE["ignore_users"] = {str(u) for u in get_ignored_users_snap()}
    except Exception:
        pass
    _spawn_node_runner()
    log_system("Bridge ready, waiting for messages from the Snapchat runner")
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
