"""Tests the JSON IPC contracts between the runners and the Telegram controller."""
import os, sys, json, shutil, tempfile
from pathlib import Path

REPO = str(Path(__file__).resolve().parent.parent)
SANDBOX = tempfile.mkdtemp(prefix="llmbot_ipc_")
os.makedirs(os.path.join(SANDBOX, "config"), exist_ok=True)
os.makedirs(os.path.join(SANDBOX, "ipc"), exist_ok=True)
shutil.copy(os.path.join(REPO, "resources", "config.yaml"), os.path.join(SANDBOX, "config", "config.yaml"))
sys.path.insert(0, REPO)

import app.utils.helpers as helpers
helpers.resource_path = lambda rel: os.path.join(SANDBOX, rel)
import app.utils.error_notifications as en
en.resource_path = helpers.resource_path

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ── notify_telegram_error ────────────────────────────────────────────────────
print("\n== notify_telegram_error ==")
cmd1 = os.path.join(SANDBOX, "config", "tg_commands_1.json")
cmd2 = os.path.join(SANDBOX, "config", "tg_commands_2.json")

os.environ.pop("DISCORD_ACCOUNT_INDEX", None)
en.notify_telegram_error("Boom", "stack trace here")
check("writes to account 1 by default", os.path.exists(cmd1) and read(cmd1)[0]["cmd"] == "send_error_notification")
check("payload carried", read(cmd1)[0]["payload"]["title"] == "Boom")

en.notify_telegram_error("Second", "more")
check("appends without clobbering", len(read(cmd1)) == 2)

os.environ["DISCORD_ACCOUNT_INDEX"] = "2"
en.notify_telegram_error("Acct2", "x")
check("honours account index", os.path.exists(cmd2) and len(read(cmd2)) == 1)
check("account 1 untouched", len(read(cmd1)) == 2)
os.environ.pop("DISCORD_ACCOUNT_INDEX", None)

en.notify_telegram_error("Long", "y" * 5000)
check("detail truncated to 1500", len(read(cmd1)[-1]["payload"]["detail"]) == 1500)

cfg_path = os.path.join(SANDBOX, "config", "config.yaml")
raw = Path(cfg_path).read_text(encoding="utf-8")
Path(cfg_path).write_text(raw.replace("telegram_error_notifications: true",
                                      "telegram_error_notifications: false"), encoding="utf-8")
before = len(read(cmd1))
en.notify_telegram_error("Ignored", "should not appear")
check("no-op when notifications disabled", len(read(cmd1)) == before)
Path(cfg_path).write_text(raw, encoding="utf-8")

# ── _flush_commands: runner must not drop entries added mid-pass ─────────────
print("\n== runner _flush_commands ==")
import importlib.util


def load_flush():
    """Pull _flush_commands out of discord_runner without importing discord."""
    src = Path(os.path.join(REPO, "app", "platforms", "discord_runner.py")).read_text(encoding="utf-8")
    start = src.index("def _flush_commands(")
    end = src.index("async def _tg_ipc_loop():")
    ns = {}
    exec(src[start:end], ns)
    return ns["_flush_commands"]


flush = load_flush()
f = Path(os.path.join(SANDBOX, "config", "flushtest.json"))

# Runner read A+B, handled both, and an error notification landed while it worked.
handled = [{"id": "a", "cmd": "pause"}, {"id": "b", "cmd": "wipe"}]
f.write_text(json.dumps(handled + [{"id": "err1", "cmd": "send_error_notification"}]), encoding="utf-8")
flush(f, [], handled)
left = read(f)
check("handled commands removed", not any(e["id"] in ("a", "b") for e in left), str(left))
check("late notification preserved", [e["id"] for e in left] == ["err1"], str(left))

# Notifications passed through as `remaining` must survive and not duplicate.
keep = [{"id": "err1", "cmd": "send_error_notification"}]
f.write_text(json.dumps(handled + keep), encoding="utf-8")
flush(f, keep, handled)
check("no duplicate on passthrough", [e["id"] for e in read(f)] == ["err1"], str(read(f)))

# A brand-new command queued mid-pass must not be lost.
f.write_text(json.dumps(handled + [{"id": "c", "cmd": "get_status"}]), encoding="utf-8")
flush(f, [], handled)
check("new command preserved", [e["id"] for e in read(f)] == ["c"], str(read(f)))

# Corrupt file must not raise.
f.write_text("{not json", encoding="utf-8")
flush(f, [], handled)
check("survives corrupt file", read(f) == [])

# ── Snapchat incoming pruning ────────────────────────────────────────────────
print("\n== snapchat incoming pruning ==")
os.environ["SNAP_ACCOUNT_INDEX"] = "1"
import importlib
import app.utils.db as db
db.resource_path = helpers.resource_path
db.init_db()
import app.platforms.snapchat_bridge as bridge
importlib.reload(bridge)
bridge.IPC_DIR = Path(os.path.join(SANDBOX, "ipc"))
bridge.INCOMING_FILE = bridge.IPC_DIR / "snap_incoming.json"
bridge.PROCESSED_FILE = bridge.IPC_DIR / "snap_processed.json"

bridge._write_json(bridge.INCOMING_FILE, [{"id": "m1"}, {"id": "m2"}])
messages = bridge._read_json(bridge.INCOMING_FILE, [])
# Node appends m3 while Python is busy generating a reply for m1/m2.
bridge._write_json(bridge.INCOMING_FILE, messages + [{"id": "m3"}])
bridge._mark_processed("m1")
bridge._mark_processed("m2")

fresh_processed = set(bridge._read_json(bridge.PROCESSED_FILE, []))
current = bridge._read_json(bridge.INCOMING_FILE, [])
remaining = [m for m in current if m.get("id") not in fresh_processed]
bridge._write_json(bridge.INCOMING_FILE, remaining)
check("message arriving mid-batch survives", [m["id"] for m in bridge._read_json(bridge.INCOMING_FILE, [])] == ["m3"],
      str(bridge._read_json(bridge.INCOMING_FILE, [])))

check("processed list dedupes", bridge._read_json(bridge.PROCESSED_FILE, []) == ["m1", "m2"])
for i in range(700):
    bridge._mark_processed("x%d" % i)
check("processed list capped at 500", len(bridge._read_json(bridge.PROCESSED_FILE, [])) == 500)

check("read_json default on missing file", bridge._read_json(Path(SANDBOX) / "nope.json", "dflt") == "dflt")
(Path(SANDBOX) / "empty.json").write_text("", encoding="utf-8")
check("read_json default on empty file", bridge._read_json(Path(SANDBOX) / "empty.json", []) == [])
(Path(SANDBOX) / "bad.json").write_text("{{{", encoding="utf-8")
check("read_json default on corrupt file", bridge._read_json(Path(SANDBOX) / "bad.json", []) == [])

# ── Result files must stay bounded ───────────────────────────────────────────
# A result is only removed when it is read, so anything whose caller timed out
# lingered. reply_check answers are tens of KB each and this file reached 91 MB
# in real use; every IPC call then re-read and rewrote all of it synchronously,
# which stalled the whole panel while the log websocket kept working.
print("\n== result file stays bounded ==")
import asyncio as _asyncio
import app.core.ipc as ipc
ipc.CONFIG_DIR = Path(SANDBOX) / "config"
ipc.IPC_DIR = Path(SANDBOX) / "ipc"
ipc.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
ipc.IPC_DIR.mkdir(parents=True, exist_ok=True)

_f = ipc.result_file(1)
_big = {f"stale-{i}": {"users": [{"id": i, "snippet": "x" * 200}]} for i in range(500)}
ipc._write_json_atomic(_f, _big)
check("seeded an oversized result file", len(ipc._read_json(_f, {})) == 500)

# A timed-out wait should trim it rather than leave it to grow.
_asyncio.run(ipc.wait_for_result(1, "never-arrives", timeout=0.4))
_after = ipc._read_json(_f, {})
check("timed-out wait prunes the file", len(_after) <= ipc.MAX_RESULTS, str(len(_after)))

# And a successful read keeps it capped too.
_big2 = {f"stale-{i}": {"ok": True} for i in range(500)}
_big2["wanted"] = {"ok": True, "value": 42}
ipc._write_json_atomic(_f, _big2)
_got = _asyncio.run(ipc.wait_for_result(1, "wanted", timeout=1.0))
check("the wanted result still comes back", _got == {"ok": True, "value": 42}, str(_got))
_after = ipc._read_json(_f, {})
check("and the file is capped afterwards", len(_after) <= ipc.MAX_RESULTS, str(len(_after)))
check("newest entries are the ones kept",
      all(k.startswith("stale-4") or k.startswith("stale-3") for k in _after),
      str(list(_after)[:5]))



print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
