"""
platforms/snapchat_bridge.py - Python side of the Snapchat integration.

Node runner ←→ JSON IPC files ←→ this bridge → core/engine.py → Groq AI.

IPC files (in ipc/):
  snap_incoming.json - Node writes new messages here; Python consumes them
  snap_responses.json - Python writes keyed replies here; Node reads & sends
  snap_outgoing.json - Python queues proactive sends here (e.g. /reply)
  snap_processed.json - bookkeeping of message ids already handled
  tg_commands_snap.json / tg_results_snap.json, Telegram controller IPC

Shares the same AI brain, memory, mood, leaderboard and pictures as Discord.
"""

import asyncio
import json
import time
import os
import sys
import base64
import mimetypes
import shutil
import atexit
import subprocess
import uuid as _uuid
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app.core.engine as engine
from app.core.engine import generate_ai_response, IncomingMessage
from app.utils.ai import init_ai, generate_response, transcribe_voice
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

# Multi-account: main.py launches one bridge per account with SNAP_ACCOUNT_INDEX
# (1-based). Account 1 keeps the legacy unsuffixed files; accounts 2+ get _N.
ACCOUNT_INDEX = int(os.getenv("SNAP_ACCOUNT_INDEX", "1") or "1")
_SFX    = "" if ACCOUNT_INDEX == 1 else f"_{ACCOUNT_INDEX}"
_TG_SFX = "snap" if ACCOUNT_INDEX == 1 else f"snap{ACCOUNT_INDEX}"

INCOMING_FILE  = IPC_DIR / f"snap_incoming{_SFX}.json"
RESPONSES_FILE = IPC_DIR / f"snap_responses{_SFX}.json"
OUTGOING_FILE  = IPC_DIR / f"snap_outgoing{_SFX}.json"
PROCESSED_FILE = IPC_DIR / f"snap_processed{_SFX}.json"

# Telegram control IPC (kept in ipc/ alongside the other Snapchat IPC files)
CMD_FILE    = IPC_DIR / f"tg_commands_{_TG_SFX}.json"
RESULT_FILE = IPC_DIR / f"tg_results_{_TG_SFX}.json"
UPDATE_FLAG = Path(resource_path(f"config/update_{_TG_SFX}.flag"))

# ── Wake channel ─────────────────────────────────────────────────────────────
# The JSON files below stay the transport: they are the durable record, they
# survive either side restarting, and they keep working on their own. What they
# could never do is tell the other side that something had arrived, so both ends
# polled on a timer and a reply carried roughly four seconds of pure waiting -
# up to two coming in, up to two going out - before the model was even asked.
#
# This is a loopback socket that carries nothing but "look again now". It holds
# no state and no payload, so losing it costs latency and never data: both sides
# still poll underneath at exactly the intervals they always did. Port 0 lets
# the OS pick a free port, published in PORT_FILE, so several accounts on one
# machine cannot collide.
PORT_FILE      = IPC_DIR / f"snap_port{_SFX}"

POLL_INTERVAL    = 2.0    # seconds between incoming-message polls
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

# One generation lock per conversation, not one for the whole account.
#
# The lock is there so the message loop and a /reply command cannot interleave
# their awaits and corrupt history ordering. That state is keyed per chat
# though - message_history by (user, channel), _memory_cache by user - so two
# different conversations never touch the same entries. A single account-wide
# lock meant a backlog of five chats cost five full generations strictly back to
# back, everyone waiting on whoever happened to be first.
_gen_locks: dict = {}

# ...but not unlimited concurrency either. Generations are Groq calls, and the
# account-wide lock was implicitly capping how many could be in flight at once.
# Lifting it entirely would let a burst of chats fan out into a burst of
# requests and trip rate limiting, which costs far more than it saves. A small
# ceiling keeps the throughput win without that.
_GEN_SLOTS = asyncio.Semaphore(3)


def _gen_lock(key: str) -> asyncio.Lock:
    """The generation lock for one conversation."""
    lock = _gen_locks.get(key)
    if lock is None:
        lock = _gen_locks[key] = asyncio.Lock()
    return lock

# Set when Node says new messages have landed; the incoming loop waits on this
# instead of sleeping out its full interval.
_wake_incoming = asyncio.Event()
# Connected Node clients, to poke when a reply is ready to send.
_node_writers: set = set()


async def _wake_server():
    """Accept Node's connection and turn its pokes into an asyncio.Event.

    Never raises into the caller: if the socket cannot be set up at all, the
    bridge simply keeps polling the way it always has.
    """
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
        except Exception:
            pass
        finally:
            _node_writers.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    try:
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_response(msg_id: str, text: str, chat_id: str = None, name: str = None):
    """Write an AI reply for the Node runner to send. The chat id is embedded
    so the entry is self-routing even if Node restarts before draining it."""
    responses = _read_json(RESPONSES_FILE, {})
    if chat_id:
        responses[msg_id] = {"text": text, "chat": str(chat_id), "name": name or str(chat_id)}
    else:
        responses[msg_id] = text  # legacy string form
    _write_json(RESPONSES_FILE, responses)
    # The file is written and durable; this only saves Node the wait until its
    # next drain tick. If nothing is connected it is a no-op and the poll picks
    # the reply up as before.
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


def _queue_picture_if_any(msg) -> None:
    """If the engine chose a selfie to send for this message, queue it as a Snap."""
    path = msg.extra.get("picture_to_send")
    if path:
        _queue_outgoing(msg.channel_id, "", image=path)
        name = CHAT_NAMES.get(msg.channel_id, msg.channel_id)
        log_system(f"Queued picture send to {name}: {path}")


def _humanize_reply(text: str) -> str:
    """Same output touch-ups as Discord, strip em-dashes, occasional typo."""
    try:
        typo_chance = load_config().get("bot", {}).get("typo_chance", 0.03)
    except Exception:
        typo_chance = 0.03
    return humanize(text, typo_chance)


_CALL_LANG_NAMES = {
    "fr": "French", "en": "English", "es": "Spanish", "de": "German", "ar": "Arabic",
    "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "ru": "Russian", "tr": "Turkish",
}


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
    lang_disp = _CALL_LANG_NAMES.get(lang_tag, "English")
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


# Python is the only writer of the processed ledger - Node creates it empty at
# startup if it is missing and never touches it again - so the in-memory copy is
# authoritative, and fresher than the file. It used to be read, parsed, appended
# to and rewritten in full on every single message: eight times per pass, up to
# 500 ids each way.
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
    # Still written on every mark: a crash part-way through a pass must not make
    # the bot answer the same message twice. What is saved is the read + parse.
    _write_json(PROCESSED_FILE, processed)


# ── Incoming-message polling loop ────────────────────────────────────────────
async def process_incoming():
    """Read new Snapchat messages and generate AI responses (respecting pause/ignore)."""
    log_system("Snapchat bridge started, polling for messages")

    while True:
        # Wake the moment Node says something landed, and fall back to the old
        # interval when the socket is not there.
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

            # ── Incoming call ────────────────────────────────────────────────
            # Node already clicked "Not Now"; here we send a casual "can't talk"
            # chat so the bot dodges the call naturally (respecting ignore/pause).
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

            # Transcribe a voice message (file://) with Whisper, then fold the
            # transcript into the text, same as the Discord side.
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
                _mark_processed(msg_id)
                continue

            # ── Pause / ignore gating ───────────────────────────────────────
            # Paused/ignored messages are still recorded so /reply can answer
            # them later, but we don't auto-respond.
            if user_id in STATE["ignore_users"]:
                _mark_processed(msg_id)
                continue

            if STATE["paused"] or user_id in STATE["paused_users"]:
                engine.add_user_message(user_id, channel_id, content or "📸 sent a snap")
                log_system(f"Paused - recorded message from {user_name} for later /reply")
                _mark_processed(msg_id)
                continue

            msg = IncomingMessage(
                platform="snapchat",
                user_id=user_id,
                user_name=user_name,
                channel_id=channel_id,
                content=content,
                image_url=image_url,
                is_private=True,  # Snapchat messages are always DMs
                wait_time=age,
            )

            log_incoming(user_name, "Snapchat DM", "Snapchat", content)

            try:
                async with _gen_lock(channel_id), _GEN_SLOTS:
                    response = await generate_ai_response(msg)
            except Exception as e:
                log_error("Snap AI Error", str(e))
                _notify_telegram_error("AI generation error", f"{user_name}: {e}")
                _mark_processed(msg_id)
                continue

            if response:
                response = _humanize_reply(response)
                log_response(user_name, response)
                separator()
                _append_response(msg_id, response, channel_id, user_name)
                _queue_picture_if_any(msg)
            else:
                log_system(f"No response generated for {user_name}")

            _mark_processed(msg_id)

        # Re-read the incoming file before pruning: Node keeps appending to it
        # while we generate replies, and writing back a filtered copy of the
        # stale list would silently drop those new messages. The processed
        # ledger needs no re-read - this process is its only writer, so the
        # in-memory copy is already the newest there is.
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


def _save_config(cfg: dict):
    import yaml
    with open(resource_path("config/config.yaml"), "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


# Commands that only make sense on Discord, acknowledged with a clear message.
_DISCORD_ONLY = {
    "toggle_dm", "toggle_gc", "toggle_server", "toggle_active",
    "voice_join", "voice_leave", "voice_autojoin",
    "set_status", "set_bio", "set_pfp", "set_banner", "add_friend",
}


async def _handle_command(cmd: str, payload: dict, cmd_id: str) -> None:
    """Execute a single Telegram command and write its result."""

    if cmd in _DISCORD_ONLY:
        _write_result(cmd_id, {"ok": False, "unsupported": True,
                               "reason": "Not supported on Snapchat."})
        return

    if cmd == "pause":
        STATE["paused"] = not STATE["paused"]
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
            _write_result(cmd_id, {"ok": True, "ignored": False})
        else:
            STATE["ignore_users"].add(uid)
            add_ignored_user_snap(uid)
            _write_result(cmd_id, {"ok": True, "ignored": True})

    elif cmd == "ignore_add":
        uid = str(payload["user_id"])
        STATE["ignore_users"].add(uid)
        add_ignored_user_snap(uid)
        _write_result(cmd_id, {"ok": True})

    elif cmd == "ignore_remove":
        uid = str(payload["user_id"])
        STATE["ignore_users"].discard(uid)
        remove_ignored_user_snap(uid)
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
        # The engine reads instructions fresh from disk on every reply, and the
        # Telegram controller already wrote the file, nothing to hold in memory.
        _write_result(cmd_id, {"ok": True})

    elif cmd == "config_update":
        # Most config is read live from disk by the engine. A few values are
        # cached at import; those take effect on restart. Acknowledge either way.
        _write_result(cmd_id, {"ok": True})

    elif cmd == "reload":
        # Reloading "cogs" is Discord-only; for Snapchat we just confirm the
        # engine will pick up the latest instructions/config from disk.
        _write_result(cmd_id, {"ok": True, "errors": []})

    elif cmd == "get_status":
        _write_result(cmd_id, {
            "paused": STATE["paused"],
            "mood": mood_mod.current_mood,
            "active_channels": len(CHAT_NAMES),
            "ignored_users": len(STATE["ignore_users"]),
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
            users_out.append({
                "id": chat_id,
                "name": name,
                "snippet": snippet,
                "count": len(trailing),
            })
        _write_result(cmd_id, {"users": users_out})

    elif cmd == "reply_user":
        uid = str(payload["user_id"])
        ok, reason = await _reply_to_chat(uid)
        if ok:
            _write_result(cmd_id, {"success": True})
        else:
            _write_result(cmd_id, {"success": False, "reason": reason})

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

    elif cmd == "analyse_user":
        from app.utils.helpers import load_instructions
        uid = str(payload["user_id"])
        hist = engine.message_history.get(f"{uid}-{uid}", [])
        msgs = [e["content"] for e in hist if e.get("role") == "user" and e.get("content")]
        if not msgs:
            _write_result(cmd_id, {"ok": False,
                                   "reason": f"No messages found for chat {uid}."})
            return
        name = CHAT_NAMES.get(uid, uid)
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

    elif cmd in ("image_analyse", "image_delete", "image_delete_multi",
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
        UPDATE_FLAG.write_text(source)
        _write_result(cmd_id, {"ok": True, "queued": True})

    elif cmd == "send_error_notification":
        # Passthrough, the Telegram error loop reads this from the file directly.
        _write_result(cmd_id, {"ok": True})

    else:
        _write_result(cmd_id, {"ok": False, "reason": f"Unknown command: {cmd}"})


async def _reply_to_chat(chat_id: str) -> tuple[bool, str]:
    """Generate a reply to the trailing unanswered messages and queue it for sending."""
    name = CHAT_NAMES.get(chat_id, chat_id)
    async with _gen_lock(chat_id), _GEN_SLOTS:
        combined = engine.pop_pending_user_messages(chat_id, chat_id)
        if not combined:
            return False, "no unanswered message found"
        msg = IncomingMessage(
            platform="snapchat",
            user_id=chat_id,
            user_name=name,
            channel_id=chat_id,
            content=combined,
            is_private=True,
            wait_time=0.0,
        )
        try:
            response = await generate_ai_response(msg)
        except Exception as e:
            return False, str(e)
    if not response:
        return False, "couldn't generate response"
    response = _humanize_reply(response)
    _queue_outgoing(chat_id, response)
    _queue_picture_if_any(msg)
    log_system(f"Queued /reply to {name}")
    return True, ""


async def _handle_image_command(cmd: str, payload: dict, cmd_id: str):
    """Shared-pictures image commands (analyse/delete), mirroring the Discord runner."""
    img_folder = resource_path("config/pictures")
    exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

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
            resp = await _create_image_completion(
                model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in full detail exactly as you see it. Include all visible text, objects, people, colors, layout, and context."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }],
            )
            desc = resp.choices[0].message.content.strip()
            add_picture_description(name, desc)
            _write_result(cmd_id, {"ok": True, "description": desc})
        except Exception as e:
            log_error("Snap image_analyse", str(e))
            _write_result(cmd_id, {"ok": False, "reason": str(e)})

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


async def tg_command_loop():
    """Poll tg_commands_snap.json and execute Telegram controller commands."""
    log_system("Telegram IPC bridge started (Snapchat)")

    while True:
        await asyncio.sleep(TG_POLL_INTERVAL)

        # Update sentinel (snap-specific so it never collides with the Discord one)
        if UPDATE_FLAG.exists():
            try:
                source = UPDATE_FLAG.read_text().strip() or "release"
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
            continue
        commands = _read_json(CMD_FILE, [])
        if not commands:
            continue

        # Consume the commands up-front: keep only the error-notification
        # passthroughs and flush the file BEFORE executing anything. Terminal
        # commands (restart/shutdown) call os._exit() mid-loop, so writing the
        # pruned file only at the end would leave restart entries that re-fire
        # on every boot (an infinite restart loop).
        keep = [e for e in commands if e.get("cmd") == "send_error_notification"]
        to_run = [e for e in commands if e.get("cmd") != "send_error_notification"]
        if len(keep) != len(commands):
            _write_json(CMD_FILE, keep)

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
    tasks = [process_incoming(), tg_command_loop(), _cleanup_loop(), _wake_server()]

    # Mood shifts over time, exactly like the Discord runner.
    if cfg.get("bot", {}).get("mood", {}).get("enabled", True):
        shift_mood()                 # pick a starting mood now
        tasks.append(mood_loop())    # then keep shifting it on a timer
        log_system(f"Mood system active (current: {mood_mod.current_mood})")

    await asyncio.gather(*tasks)


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
    """Terminate the Node runner AND its Chrome child (via the whole process
    tree). Called from atexit *and* explicitly before os._exit()."""
    if not _node_proc or _node_proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            # /T kills the child Chrome too; /F forces it. Quiet on success.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(_node_proc.pid)],
                capture_output=True,
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
    """Ensure a writable copy of the Node runner exists next to node_modules.

    Returns the directory to run it from. When frozen, the bundled JS is
    read-only, so we mirror it into DATA_DIR/snapchat/ (where the web UI
    installs Node deps on demand). Node's ESM resolver needs node_modules
    beside the JS file, so we run from that mirrored directory.
    """
    from app.utils.paths import APP_DIR, DATA_DIR
    src_dir = Path(APP_DIR) / "app" / "platforms" / "snapchat"
    dst_dir = DATA_DIR / "snapchat"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not (src_dir / "snapchat_runner.js").exists():
        return str(src_dir)
    # Prefer the data dir when it already has deps; otherwise mirror files over.
    if (dst_dir / "node_modules").is_dir() and (dst_dir / "snapchat_runner.js").exists():
        return str(dst_dir)
    if (src_dir / "node_modules").is_dir():
        return str(src_dir)  # source install
    for name in ("snapchat_runner.js", "snapbot.js", "log.js", "package.json"):
        src, dst = src_dir / name, dst_dir / name
        try:
            if not dst.exists() or src.read_bytes() != dst.read_bytes():
                dst.write_bytes(src.read_bytes())
        except OSError:
            pass
    return str(dst_dir)


def _spawn_node_runner():
    """Launch the Node browser runner as a child process in THIS console.

    Disabled with SNAP_SPAWN_NODE=false to run the runner yourself.
    The snapchat section of config.yaml is mapped into the runner's env so it
    actually controls polling/sending behaviour (explicit .env vars win).
    """
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

    # node_modules alone does not mean Snapchat can run: Puppeteer's Chrome
    # download is a separate postinstall step, and a half-finished one leaves
    # the deps looking complete while every launch dies with "Could not find
    # Chrome". Say which of the two is actually missing.
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
    # Point the Node side at the writable data dir for cookies/profile/temp
    # media, and at the real .env location.
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
        }
        for yaml_key, env_key in env_map.items():
            val = snap_cfg.get(yaml_key)
            if val is not None and env_key not in os.environ:
                node_env[env_key] = "true" if val is True else ("false" if val is False else str(val))
    except Exception:
        pass

    try:
        from app.utils.procs import quiet_kwargs
        _node_proc = subprocess.Popen([node_exe, runner_js], cwd=runner_dir, env=node_env,
                                      **quiet_kwargs())
        atexit.register(_kill_node_runner)
        log_system(f"Node runner started (PID {_node_proc.pid}, account #{ACCOUNT_INDEX}) - sharing this window")
    except Exception as e:
        log_error("Snapchat", f"Could not start Node runner: {e}")


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
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        log_system("Shutting down…")
    finally:
        _kill_node_runner()


if __name__ == "__main__":
    run()
