"""Shared IPC files, written safely by several processes at once.

One night the Snapchat bridge died on a PermissionError writing
ipc/tg_commands_snap.json.tmp. The panel and the bridge both wrote the
command file through a temporary file of that same name, so two writes at
the same instant opened the same temporary file and Windows refused the
second. The Discord worker, the Telegram controller and the error alerts
shared another one. Then the dead bridge's process stayed up for ten hours,
waiting on a worker thread at exit, so the panel showed the account running
while it answered nobody.

  * every write has a temporary file of its own, and a write Windows refuses
    for a moment is tried again;
  * a command loop that hits an error logs it and carries on, and a command is
    never run twice when the file could not be rewritten after it;
  * a bridge whose loops die leaves at once, so it is restarted in seconds.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = str(Path(__file__).resolve().parent.parent)
SANDBOX = tempfile.mkdtemp(prefix="llmbot_ipcw_")
os.makedirs(os.path.join(SANDBOX, "config"), exist_ok=True)
os.makedirs(os.path.join(SANDBOX, "ipc"), exist_ok=True)
shutil.copy(os.path.join(REPO, "resources", "config.yaml"), os.path.join(SANDBOX, "config", "config.yaml"))
sys.path.insert(0, REPO)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def src(rel):
    return (Path(REPO) / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== one temporary file per write ==")
from app.utils.atomic import write_json_atomic  # noqa: E402

target = Path(SANDBOX) / "ipc" / "contended.json"
write_json_atomic(target, {"n": -1})
errors = []
stop_file = Path(SANDBOX) / "ipc" / "stop-readers"

# The readers are processes of their own, as the real ones are (the panel, a
# worker, the Telegram controller). Threads in this process would share its
# lock with the writers: a reader waiting for its turn holds the file open
# far longer than any real reader does, and on a busy machine that alone
# refused writes no real process would ever see.
READER = r"""
import json, sys, time
from pathlib import Path
target, stop = Path(sys.argv[1]), Path(sys.argv[2])
reads, bad = 0, []
while not stop.exists():
    try:
        # Opened the way Python opens files on Windows (no sharing of delete),
        # which is what makes a rename onto it fail there.
        with open(target, "rb") as fh:
            data = fh.read()
        json.loads(data)
        reads += 1
    except (FileNotFoundError, PermissionError):
        pass
    except ValueError as e:
        bad.append(str(e)[:80])
    time.sleep(0.002)
print(json.dumps({"reads": reads, "bad": bad[:3]}))
"""


def writer(k):
    # A write every 5ms each: the real writers write every few seconds.
    for i in range(150):
        try:
            write_json_atomic(target, {"n": i, "w": k, "pad": "x" * 2000})
        except Exception as e:      # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
        time.sleep(0.005)


readers = [subprocess.Popen([sys.executable, "-c", READER, str(target), str(stop_file)], stdout=subprocess.PIPE, text=True)
           for _ in range(3)]
time.sleep(0.5)     # the readers going before the first write
writers = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
for t in writers:
    t.start()
for t in writers:
    t.join()
stop_file.write_text("stop", encoding="utf-8")
seen = [json.loads(r.communicate(timeout=60)[0] or "{}") for r in readers]
reads = [sum(x.get("reads", 0) for x in seen)]
bad_reads = [b for x in seen for b in x.get("bad", [])]
check("four writers at once, with three other processes reading it all the while: no write refused", not errors, str(errors[:3]))
check("and no reader ever saw half a file", not bad_reads and reads[0] > 0, f"{bad_reads[:2]} reads={reads[0]}")
check("no temporary file is left behind", [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")] == [])
held = open(target, "rb")
t0 = time.time()
try:
    write_json_atomic(target, {"n": "never"})
    landed = True
except PermissionError:
    landed = False
finally:
    held.close()
waited = time.time() - t0
check("a file held open the whole time: the write gives up after a few seconds, and says so, rather than hang",
      not landed and 1.5 < waited < 6 and json.loads(target.read_text(encoding="utf-8"))["n"] != "never", f"{landed} {waited:.1f}s")
check("leaving its temporary file behind it no more than a good write does",
      [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")] == [])
check("each write names its temporary file after the process and a random part, not just the file",
      'f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"' in src("app/utils/atomic.py"))
for rel in ("app/core/ipc.py", "app/platforms/snapchat_bridge.py", "app/platforms/discord_runner.py",
            "app/telegram_bot/telegram_controller.py", "app/utils/error_notifications.py"):
    text = src(rel)
    check(f"{rel} writes through it", "write_json_atomic(" in text and 'with_suffix(".tmp")' not in text
          and 'with_suffix(path.suffix + ".tmp")' not in text)

print("\n== the Snapchat bridge's command loop ==")
os.environ["SNAP_ACCOUNT_INDEX"] = "1"
import importlib  # noqa: E402
import app.utils.helpers as helpers  # noqa: E402
helpers.resource_path = lambda rel: os.path.join(SANDBOX, rel)
import app.utils.db as db  # noqa: E402
db.resource_path = helpers.resource_path
db.init_db()
import app.platforms.snapchat_bridge as bridge  # noqa: E402
importlib.reload(bridge)
bridge.CMD_FILE = Path(SANDBOX) / "ipc" / "tg_commands_snap.json"
bridge.UPDATE_FLAG = Path(SANDBOX) / "ipc" / "no_update_flag"
ran = []


async def fake_handle(cmd, payload, cmd_id):
    ran.append(cmd_id)

bridge._handle_command = fake_handle
bridge._write_result = lambda *a, **k: None
bridge._notify_telegram_error = lambda *a, **k: None
logged = []
bridge.log_error = lambda where, what: logged.append(f"{where}: {what}")

note = {"id": "n1", "cmd": "send_error_notification", "payload": {}}
bridge._write_json(bridge.CMD_FILE, [{"id": "a", "cmd": "get_status"}, note])
asyncio.run(bridge._tg_command_pass())
check("a command runs", ran == ["a"], str(ran))
check("and leaves the file, the error alert waiting for Telegram staying",
      bridge._read_json(bridge.CMD_FILE, []) == [note], str(bridge._read_json(bridge.CMD_FILE, [])))

real_write = bridge._write_json


def refused(path, data):
    raise PermissionError(13, "Permission denied", str(path) + ".tmp")

bridge._write_json = refused
bridge.CMD_FILE.write_text(json.dumps([{"id": "b", "cmd": "get_status"}, note]), encoding="utf-8")
asyncio.run(bridge._tg_command_pass())
check("a file that cannot be rewritten is written to the log, not raised", ran == ["a", "b"]
      and any("could not rewrite" in m for m in logged), str(logged))
bridge._write_json = real_write
asyncio.run(bridge._tg_command_pass())
check("and the command it ran is not run again on the next pass", ran == ["a", "b"], str(ran))
check("the file is tidied then", bridge._read_json(bridge.CMD_FILE, []) == [note])
bridge._write_json(bridge.CMD_FILE, [{"cmd": "get_status"}, note])
asyncio.run(bridge._tg_command_pass())
asyncio.run(bridge._tg_command_pass())
check("a command without an id runs once and is gone", len(ran) == 3 and bridge._read_json(bridge.CMD_FILE, []) == [note])

passes = {"n": 0}


async def flaky_pass():
    passes["n"] += 1
    if passes["n"] <= 2:
        raise PermissionError(13, "Permission denied")

bridge._tg_command_pass = flaky_pass
bridge.TG_POLL_INTERVAL = 0.01
try:
    asyncio.run(asyncio.wait_for(bridge.tg_command_loop(), timeout=0.5))
except (asyncio.TimeoutError, TimeoutError):
    pass
check("a pass that fails does not end the loop", passes["n"] >= 5 and sum("PermissionError" in m for m in logged) >= 2,
      f"passes={passes['n']}")

print("\n== a bridge whose loops die leaves at once ==")
code = f"""
import asyncio, os, sys, time
sys.path.insert(0, {REPO!r})
import app.utils.helpers as helpers
helpers.resource_path = lambda rel: os.path.join({SANDBOX!r}, rel)
import app.platforms.snapchat_bridge as b
async def main():
    # A worker thread still busy, which the interpreter's own exit waits for without a limit.
    asyncio.get_running_loop().run_in_executor(None, time.sleep, 60)
    await asyncio.sleep(0.2)
    async def broken():
        raise PermissionError(13, "Permission denied")
    b.process_incoming = b._cleanup_loop = b._wake_server = b.tg_command_loop = broken
    await b._main_async()
asyncio.run(main())
"""
t0 = time.time()
proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=90,
                      env={**os.environ, "SNAP_ACCOUNT_INDEX": "1"})
took = time.time() - t0
check("it exits with an error straight away, a worker thread still busy or not",
      proc.returncode == 1 and took < 45, f"code={proc.returncode} took={took:.1f}s {proc.stderr[-300:]}")
check("saying why", "PermissionError" in proc.stdout + proc.stderr)
bridge_src = src("app/platforms/snapchat_bridge.py")
check("and run() itself leaves the same way, the browser closed first",
      "_exit_now(code)" in bridge_src and "_kill_node_runner()\n    finally:" in bridge_src and "os._exit(code)" in bridge_src)

print("\n== the Discord worker's command loop ==")
dr = src("app/platforms/discord_runner.py")
flush = dr[dr.index("def _flush_commands("):dr.index("async def _tg_ipc_loop():")]
check("a rewrite that fails is logged, not raised: it used to end the loop", "except Exception as _e:" in flush
      and 'log_error("TG IPC", f"could not rewrite the command file: {_e}")' in flush)
check("and what ran is remembered, so it is not run again",
      "_RAN_COMMANDS[e[\"id\"]] = None" in flush and 'and e.get("id") not in _RAN_COMMANDS]' in dr)

shutil.rmtree(SANDBOX, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
