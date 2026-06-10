"""
platforms/snapchat_bridge.py — Python side of the Snapchat integration.

Architecture:
  Node.js snapchat_runner.js  ←→  JSON IPC files  ←→  This file  →  core/engine.py

Message IPC files (in ipc/):
  snap_incoming.json   — Node writes new messages here; Python consumes them
  snap_responses.json  — Python writes keyed responses here; Node reads & sends them
  snap_outgoing.json   — Python queues proactive sends here (e.g. Telegram /reply);
                          Node drains and sends them
  snap_processed.json  — bookkeeping of message ids already handled

Telegram control IPC files (in ipc/):
  tg_commands_snap.json  — Telegram controller writes commands here
  tg_results_snap.json   — this bridge writes command results here

The Snapchat bridge supports the same Telegram controller commands as the
Discord runner, minus the ones that only make sense on Discord (voice, friend
requests, profile pfp/banner/bio/status, server/GC/channel toggles). It shares
the same AI brain, memory, mood, leaderboard and pictures as Discord.

Message format in snap_incoming.json:
  [
    {
      "id": "uuid",
      "user_id": "chat-uuid-from-snapchat",
      "user_name": "Display Name",
      "channel_id": "chat-uuid-from-snapchat",
      "content": "hey what's up",
      "ts": 1718000000.0
    },
    ...
  ]

Response format in snap_responses.json:
  { "msg-uuid": "AI reply text", ... }

Outgoing (proactive) format in snap_outgoing.json:
  [ { "id": "uuid", "chat": "chat-uuid", "message": "text", "ts": 1718000000.0 }, ... ]
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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.engine as engine
from core.engine import generate_ai_response, IncomingMessage
from utils.ai import init_ai, generate_response, transcribe_voice
from utils.db import (
    init_db,
    get_ignored_users_snap,
    add_ignored_user_snap,
    remove_ignored_user_snap,
    get_leaderboard_snap,
)
from utils.memory import (
    init_memory,
    set_persona,
    clear_persona,
    get_persona,
)
import utils.mood as mood_mod
from utils.mood import mood_loop, shift_mood
from utils.humanize import humanize
from utils.helpers import resource_path, load_config
from utils.logger import log_system, log_error, log_incoming, log_response, separator, set_theme

# Snapchat message IPC files live in their own top-level `ipc/` folder (kept out
# of config/ so the config dir holds only user-editable settings). The folder is
# created on import so the first _write_json() has somewhere to land.
IPC_DIR = Path(resource_path("ipc"))
IPC_DIR.mkdir(parents=True, exist_ok=True)

# Multi-account support (mirrors Discord's DISCORD_TOKEN_1/_2). main.py launches
# one bridge per configured Snapchat account, passing SNAP_ACCOUNT_INDEX (1-based).
# Account 1 keeps the legacy unsuffixed file names / "snap" Telegram target so
# existing single-account setups are unaffected; accounts 2+ get an "_N" suffix
# and the "snapN" target.
ACCOUNT_INDEX = int(os.getenv("SNAP_ACCOUNT_INDEX", "1") or "1")
_SFX    = "" if ACCOUNT_INDEX == 1 else f"_{ACCOUNT_INDEX}"      # snap_incoming_2.json
_TG_SFX = "snap" if ACCOUNT_INDEX == 1 else f"snap{ACCOUNT_INDEX}"  # snap, snap2, snap3

INCOMING_FILE  = IPC_DIR / f"snap_incoming{_SFX}.json"
RESPONSES_FILE = IPC_DIR / f"snap_responses{_SFX}.json"
OUTGOING_FILE  = IPC_DIR / f"snap_outgoing{_SFX}.json"
PROCESSED_FILE = IPC_DIR / f"snap_processed{_SFX}.json"

# Telegram control IPC (kept in ipc/ alongside the other Snapchat IPC files)
CMD_FILE    = IPC_DIR / f"tg_commands_{_TG_SFX}.json"
RESULT_FILE = IPC_DIR / f"tg_results_{_TG_SFX}.json"
UPDATE_FLAG = Path(resource_path(f"config/update_{_TG_SFX}.flag"))

POLL_INTERVAL    = 2.0    # seconds between incoming-message polls
TG_POLL_INTERVAL = 2.0    # seconds between Telegram command polls
MAX_MSG_AGE      = 300.0  # ignore messages older than 5 minutes (stale)


def _snap_debug() -> bool:
    """True only when SNAP_DEBUG is an explicit on value — a disabled value like
    'false'/'0' in .env must NOT enable it."""
    return os.getenv("SNAP_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


# ── Runtime state (mirrors the per-bot attributes the Discord runner keeps) ──
STATE = {
    "paused": False,
    "paused_users": set(),   # chat ids the bot is paused for
    "ignore_users": set(),   # chat ids the bot ignores entirely
}

# chat_id -> display name, populated as messages arrive so /reply can label users
CHAT_NAMES: dict[str, str] = {}

# Serialises AI generation so the incoming-message loop and the Telegram /reply
# commands never interleave their awaits and corrupt the shared history ordering.
_GEN_LOCK = asyncio.Lock()


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
    """Write an AI reply for the Node runner to send.

    The chat id is embedded in the entry so the response is self-routing: if the
    Node runner restarts before draining it, it can still figure out which chat
    to send it to (its in-memory map is gone after a restart).
    """
    responses = _read_json(RESPONSES_FILE, {})
    if chat_id:
        responses[msg_id] = {"text": text, "chat": str(chat_id), "name": name or str(chat_id)}
    else:
        responses[msg_id] = text  # legacy string form
    _write_json(RESPONSES_FILE, responses)


def _queue_outgoing(chat_id: str, text: str, image: str = None):
    """Queue a proactive message (and/or picture) for the Node runner to send.

    When `image` is set, the Node runner sends it as a Snap to this chat
    (mirroring how the Discord side attaches a picture file).
    """
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
    """Apply the same output touch-ups the Discord runner does — strip em-dashes
    (an AI tell) and add the occasional realistic typo."""
    try:
        typo_chance = load_config().get("bot", {}).get("typo_chance", 0.05)
    except Exception:
        typo_chance = 0.05
    return humanize(text, typo_chance)


_CALL_LANG_NAMES = {
    "fr": "French", "en": "English", "es": "Spanish", "de": "German", "ar": "Arabic",
    "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "ru": "Russian", "tr": "Turkish",
}


async def _generate_call_decline(chat_id: str, name: str) -> str:
    """Craft a short, in-character chat that brushes off an incoming call."""
    from utils.helpers import load_instructions
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
        f"that brushes it off so you avoid the call — e.g. 'cant talk rn sorry', 'im busy atm cant rn'. "
        f"Reply in {lang_disp}. One short sentence, not rude, no over-explaining.]"
    )
    try:
        return await generate_response("(politely decline the call in one short message)", instr, history=None)
    except Exception:
        return None


def _notify_telegram_error(title: str, detail: str):
    """Forward an error to the Telegram controller if notifications are enabled.

    Mirrors the Discord runner's _notify_telegram_error: appends a
    send_error_notification entry to the Snapchat command file, which the
    Telegram controller's error loop drains and relays to the owner.
    """
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


def _mark_processed(msg_id: str):
    processed = _read_json(PROCESSED_FILE, [])
    if msg_id not in processed:
        processed.append(msg_id)
    if len(processed) > 500:
        processed = processed[-500:]
    _write_json(PROCESSED_FILE, processed)


# ── Incoming-message polling loop ────────────────────────────────────────────
async def process_incoming():
    """Read new Snapchat messages and generate AI responses (respecting pause/ignore)."""
    log_system("Snapchat bridge started — polling for messages")

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        messages = _read_json(INCOMING_FILE, [])
        if not messages:
            continue

        processed = set(_read_json(PROCESSED_FILE, []))
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
                    async with _GEN_LOCK:
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
                    # Keep the screenshot in config/temp so you can review what was
                    # captured. _cleanup_loop prunes old files so it stays bounded.
                except Exception as e:
                    log_error("Snap image read error", str(e))
                    image_url = None

            # Transcribe a voice message (file://) with Whisper, then fold the
            # transcript into the text so the AI replies to what was actually said
            # — same as the Discord side.
            if audio_url and audio_url.startswith("file://"):
                local_path = audio_url[7:]
                try:
                    with open(local_path, "rb") as af:
                        audio_bytes = af.read()
                    transcript = await transcribe_voice(audio_bytes, filename=os.path.basename(local_path))
                    # Voice clip is kept in config/temp too (pruned by _cleanup_loop).
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
            # When the bot is paused (globally or for this user) or the user is
            # ignored, we still record the message so /reply can answer it later,
            # but we don't auto-respond.
            if user_id in STATE["ignore_users"]:
                _mark_processed(msg_id)
                continue

            if STATE["paused"] or user_id in STATE["paused_users"]:
                engine.add_user_message(user_id, channel_id, content or "📸 sent a snap")
                log_system(f"Paused — recorded message from {user_name} for later /reply")
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
                async with _GEN_LOCK:
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

        # Re-read processed ids and prune the incoming file
        fresh_processed = set(_read_json(PROCESSED_FILE, []))
        remaining = [m for m in messages if m.get("id") not in fresh_processed]
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


# Commands that only make sense on Discord — acknowledged with a clear message.
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
        # Telegram controller already wrote the file — nothing to hold in memory.
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
        from utils.helpers import load_instructions
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
            "Keep it conversational — no bullet points, no formal structure, just talk like yourself. "
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
        # Spawn the replacement before exiting — os._exit() skips atexit handlers,
        # so the relaunch must happen here. Works when the bridge is launched
        # standalone (python main.py snapchat / direct). In a multi-process
        # "both" launch the parent owns the single-instance lock, so the user's
        # launcher/process manager is responsible for bringing it back.
        _kill_node_runner()  # close the OLD browser before the new bridge spawns one
        import subprocess as _sp
        try:
            _sp.Popen([sys.executable] + sys.argv, cwd=os.getcwd())
        except Exception as e:
            log_error("Snap restart", str(e))
        await asyncio.sleep(1)
        os._exit(0)

    elif cmd == "shutdown":
        log_system("Shutdown requested via Telegram (Snapchat)")
        _write_result(cmd_id, {"ok": True})
        _kill_node_runner()  # close the browser too — os._exit() skips the atexit hook
        await asyncio.sleep(1)
        os._exit(0)

    elif cmd == "update":
        source = payload.get("source", "release")
        if source not in ("release", "main"):
            source = "release"
        UPDATE_FLAG.write_text(source)
        _write_result(cmd_id, {"ok": True, "queued": True})

    elif cmd == "send_error_notification":
        # Passthrough — the Telegram error loop reads this from the file directly.
        _write_result(cmd_id, {"ok": True})

    else:
        _write_result(cmd_id, {"ok": False, "reason": f"Unknown command: {cmd}"})


async def _reply_to_chat(chat_id: str) -> tuple[bool, str]:
    """Generate a reply to the trailing unanswered messages and queue it for sending."""
    name = CHAT_NAMES.get(chat_id, chat_id)
    async with _GEN_LOCK:
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
        from utils.db import rename_picture_db
        for i, fname in enumerate(_img_files(), start=1):
            stem, ext = os.path.splitext(fname)
            if stem.startswith("IMG_") and stem[4:].isdigit() and int(stem[4:]) != i:
                new = f"IMG_{i}{ext}"
                os.rename(os.path.join(img_folder, fname), os.path.join(img_folder, new))
                rename_picture_db(fname, new)

    if cmd == "image_analyse":
        from utils.db import add_picture_description
        from utils.ai import _create_image_completion
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
        from utils.db import delete_picture_db
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
        from utils.db import delete_picture_db
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
        from utils.db import clear_all_pictures_db
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
                repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                import subprocess as _sp
                if sys.platform == "win32":
                    upd_path = os.path.join(repo_dir, "updater.bat")
                    _sp.Popen(
                        f'cmd /c start "Updating AI Selfbot..." /d "{repo_dir}" "{upd_path}" {source}',
                        shell=True, cwd=repo_dir, creationflags=0x00000010,
                    )
                else:
                    upd_path = os.path.join(repo_dir, "updater.sh")
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
        # passthroughs (which the Telegram controller's own loop drains) and
        # flush the file BEFORE executing anything. This is critical — terminal
        # commands like restart/shutdown call os._exit() mid-loop, so if we wrote
        # the pruned file only at the end, the restart entry would survive and
        # re-fire on every boot (an infinite restart loop).
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
    """Periodically prune the engine's unbounded in-memory caches (mirrors the
    Discord runner's cleanup loop so a long-running bridge doesn't leak memory)."""
    while True:
        await asyncio.sleep(3600)  # hourly
        try:
            cleared = []
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
            log_system(f"Hourly cleanup — {caches}; {files}.")
        except Exception:
            pass


def _prune_temp_media(max_age_seconds: float = 21600):  # 6 hours
    """Delete downloaded snap/voice/image files in config/temp older than the cap
    so the saved media doesn't grow without bound. Returns how many were removed."""
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
    tasks = [process_incoming(), tg_command_loop(), _cleanup_loop()]

    # Mood shifts over time, exactly like the Discord runner. Without this the
    # mood is stuck on its default forever.
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
    """Terminate the Node runner AND its child browser. Called from atexit *and*
    explicitly before os._exit() (which skips atexit). We kill the whole process
    tree because the Node runner spawns a Chrome/Chromium child via Puppeteer that
    would otherwise stay open after the bridge exits."""
    global _node_proc
    if not _node_proc or _node_proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            # /T kills the child Chrome too; /F forces it. Quiet on success/already-gone.
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


def _spawn_node_runner():
    """Launch the Node browser runner as a child process in THIS console so both
    halves share one window and lifecycle (closing/Ctrl-C stops both).

    Disabled with SNAP_SPAWN_NODE=false if you'd rather run the runner yourself
    in a separate terminal (the old two-terminal workflow).
    """
    global _node_proc
    if os.getenv("SNAP_SPAWN_NODE", "true").lower() == "false":
        log_system("Node runner auto-start disabled (SNAP_SPAWN_NODE=false) — start it yourself.")
        return

    node_exe = shutil.which("node")
    if not node_exe:
        log_error("Snapchat", "Node.js not found in PATH — run the browser side manually: "
                              "cd platforms/snapchat && node snapchat_runner.js")
        return

    runner_dir = resource_path("platforms/snapchat")
    runner_js = os.path.join(runner_dir, "snapchat_runner.js")
    if not os.path.exists(runner_js):
        log_error("Snapchat", f"Runner not found: {runner_js}")
        return
    if not os.path.exists(os.path.join(runner_dir, "node_modules")):
        log_error("Snapchat", "Node deps not installed — run: cd platforms/snapchat && npm install")
        return

    try:
        # Inherit our stdout/stderr so the runner logs into the SAME window, and
        # pass our account index so it reads the matching credentials + IPC files.
        node_env = {**os.environ, "SNAP_ACCOUNT_INDEX": str(ACCOUNT_INDEX)}
        _node_proc = subprocess.Popen([node_exe, "snapchat_runner.js"], cwd=runner_dir, env=node_env)
        atexit.register(_kill_node_runner)
        log_system(f"Node runner started (PID {_node_proc.pid}, account #{ACCOUNT_INDEX}) — sharing this window")
    except Exception as e:
        log_error("Snapchat", f"Could not start Node runner: {e}")


def run():
    """Entry point — initialise all subsystems, launch the Node runner, then loop."""
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
    log_system("Bridge ready — waiting for messages from the Snapchat runner")
    separator()
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        log_system("Shutting down…")
    finally:
        _kill_node_runner()


if __name__ == "__main__":
    run()
