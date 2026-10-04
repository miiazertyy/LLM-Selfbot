"""The Chats tab, live.

It used to learn anything only by asking: an IPC round trip that swept the DM
channels every 15 seconds while the tab was open, so a reply written and sent in
between never showed, and a new message took up to a quarter of a minute to
appear. Now the runner pushes each change on its stdout, the supervisor turns
those lines into events on the WebSocket the logs already use, and the page
applies them as they come.

Checked here: the runner emits what the page needs, including the whole
message; marker lines become events and never log lines; the server's cache
takes each event and a sweep in flight does not undo one; the page's copy of
the merge and the Discord formatting work (chats_live_logic.mjs); cancelling and
turning someone off actually stop the reply.
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="chatslive_"))
(SANDBOX / "logs").mkdir(parents=True)
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")

print("== the runner says what happened ==")
set_state = runner[runner.index("def set_reply_state"):runner.index("def clear_reply_state")]
check("every state change is pushed", 'emit_chat_event({"t": "state"' in set_state)
clear = runner[runner.index("def clear_reply_state"):runner.index("def emit_chat_meta")]
check("and being answered", '"t": "done"' in clear)
on_msg = runner[runner.index("async def on_message"):]
on_msg = on_msg[:on_msg.index("if should_ignore_message(message):")]
check("a new DM is pushed with the whole message", '"t": "msg"' in on_msg and "**_message_payload(message)" in on_msg)
check("and a new message lifts an old cancel", "bot.cancelled_replies.discard(message.author.id)" in on_msg)
check("our own message in a DM marks it answered", "clear_reply_state(_rcp.id)" in on_msg)
_launcher = (ROOT / "app" / "core" / "launcher.py").read_text(encoding="utf-8")
check("only when the panel is listening: a process it started, or on a phone a thread it runs",
      "_EMIT_EVENTS = _under_panel()" in runner
      and 'os.environ.get("LLMSELFBOT_CHILD") == "1"' in _launcher.split("def under_panel")[1]
      and "inprocess.current() is not None" in _launcher)
payload = runner[runner.index("def _message_payload"):runner.index("def _waiting_entry")]
check("the message carries its id, text, attachments, stickers and embeds",
      all(k in payload for k in ('"mid"', '"attachments"', '"stickers"', '"embeds"', '"text"')))

print("\n== a cancel stops the reply, wherever it is ==")
gen = runner[runner.index("async def generate_response_and_reply"):]
send = gen[gen.index('set_reply_state(message.author.id, "queued"') - 600:gen.index('set_reply_state(message.author.id, "queued"')]
check("checked again right before it is sent", "message.author.id in bot.cancelled_replies" in send)
# the command loop's own branches: _server_job, earlier in the file, has a cancel_reply branch of its own
_ign_at = runner.index('elif cmd == "ignore_toggle":')
ign = runner[_ign_at:runner.index('elif cmd == "cancel_reply":', _ign_at)]
check("turning someone off drops the reply already lined up",
      "bot.cancelled_replies.add(uid)" in ign and "user_message_batches.pop" in ign)
check("and the row hears about it", '"t": "ignored"' in ign)

print("\n== marker lines become events, not log lines ==")
from app.web import supervisor as sup
from app.web.routes import chat_routes


async def pipe():
    q = logbus.bus.subscribe()
    child = sup.Child(child_id="discord_1", role="discord", account=1, label="Discord #1")
    evt = {"t": "state", "uid": "42", "state": {"state": "waiting", "eta": 99}}
    child.proc = types.SimpleNamespace(stdout=iter([
        "a normal line\n", sup.CHAT_EVENT_MARK + json.dumps(evt) + "\n", "\x1eCHAT not json\n"]))
    before = len(logbus.bus.buffer)
    sup.Supervisor._read_output(sup.Supervisor.__new__(sup.Supervisor), child)
    await asyncio.sleep(0.05)
    got = []
    while not q.empty():
        got.append(q.get_nowait())
    logbus.bus.unsubscribe(q)
    return got, list(logbus.bus.buffer)[before:]

got, logged = asyncio.run(pipe())
events = [g for g in got if g.get("source") == "_event"]
check("the event reaches the socket", len(events) == 1 and events[0]["event"]["uid"] == "42"
      and events[0]["kind"] == "chat" and events[0]["event"]["target"] == "discord_1", json.dumps(got)[:300])
check("tagged with the account it came from", events and events[0]["event"]["target"] == "discord_1")
check("the normal line is still logged", any(e["text"] == "a normal line" for e in logged))
check("the event is not in the log", not any("CHAT" in e["text"] or "42" in e["text"] for e in logged),
      json.dumps(logged)[:200])

print("\n== the server's cache stays current ==")
chat_routes._CHATS_CACHE[1] = {"body": {"users": [{"id": "42", "count": 1, "mid": "1"}]}, "at": 0}
chat_routes.apply_chat_event("discord_1", {"t": "msg", "uid": "7", "name": "new", "mid": "3", "text": "yo"})
users = chat_routes._CHATS_CACHE[1]["body"]["users"]
check("a new message adds its sender", [u["id"] for u in users] == ["42", "7"], json.dumps(users))
chat_routes.apply_chat_event("discord_1", {"t": "done", "uid": "42"})
check("an answered one comes off", [u["id"] for u in chat_routes._CHATS_CACHE[1]["body"]["users"]] == ["7"])


async def sweep_race():
    """A reply goes out while the runner is sweeping: the sweep must not bring it back."""
    chat_routes._CHATS_CACHE.pop(1, None)

    async def slow_sweep(tgt, cmd, *a, **k):
        await asyncio.sleep(0.05)
        chat_routes.apply_chat_event("discord_1", {"t": "done", "uid": "42"})   # mid-sweep
        return {"users": [{"id": 42, "name": "x", "count": 1}, {"id": 7, "name": "y", "count": 1}]}

    real, chat_routes.ipc.send_and_wait = chat_routes.ipc.send_and_wait, slow_sweep
    real_profiles, chat_routes._profiles_for = chat_routes._profiles_for, lambda ids: {}
    try:
        return await chat_routes._chats_payload(1, fresh=True)
    finally:
        chat_routes.ipc.send_and_wait = real
        chat_routes._profiles_for = real_profiles

body = asyncio.run(sweep_race())
check("a sweep in flight does not undo an event", [u["id"] for u in body["users"]] == ["7"], json.dumps(body)[:200])
check("and says when it was true", body.get("swept_at", 0) > 0)



async def named_by_id():
    """Someone Discord's cache forgot comes back named by their id; the profile cache knows better."""
    chat_routes._CHATS_CACHE.pop(1, None)

    async def sweep(tgt, cmd, *a, **k):
        return {"users": [{"id": 1452800117257277594, "name": "1452800117257277594", "count": 1},
                          {"id": 5, "name": "maya", "count": 1}]}

    real, chat_routes.ipc.send_and_wait = chat_routes.ipc.send_and_wait, sweep
    real_profiles = chat_routes._profiles_for
    chat_routes._profiles_for = lambda ids: {"1452800117257277594": {"display_name": "Zerty", "username": "a3zertk",
                                                                     "avatar": ""},
                                             "5": {"display_name": "Maya B", "username": "maya", "avatar": ""}}
    try:
        return await chat_routes._chats_payload(1, fresh=True)
    finally:
        chat_routes.ipc.send_and_wait = real
        chat_routes._profiles_for = real_profiles

body = asyncio.run(named_by_id())
check("a person named by their id gets their name back", body["users"][0]["name"] == "Zerty", str(body["users"][0]))
check("a real name is left alone", body["users"][1]["name"] == "maya")

print("\n== the page's half ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "chats_live_logic.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("chats_live_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])
web = ROOT / "webui" / "src"
chats = (web / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("rows draw the whole message", "<MessageBody" in chats)
mb = (web / "lib" / "components" / "MessageBody.svelte").read_text(encoding="utf-8")
check("an old row's [attachment] reads as what it was, not as brackets",
      "placeholder" in mb and "Sent an attachment" not in mb and "attachment|image|video" in mb)
check("with Cancel and Turn off", "cancel(selected!)" in chats and "flipIgnore(selected!)" in chats)
app_svelte = (web / "App.svelte").read_text(encoding="utf-8")
check("the live feed starts with the app", "startChatLive()" in app_svelte)
sock = (web / "lib" / "logsocket.ts").read_text(encoding="utf-8")
check("events never reach log subscribers", 'entry.source === "_event"' in sock)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
