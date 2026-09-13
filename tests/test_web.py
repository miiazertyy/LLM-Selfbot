"""Exercises the new app/web layer against a sandbox DATA_DIR."""
import sys, shutil, tempfile, json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SANDBOX = Path(tempfile.mkdtemp(prefix="llmbot_web_"))
(SANDBOX / "config").mkdir(parents=True, exist_ok=True)
(SANDBOX / "ipc").mkdir(parents=True, exist_ok=True)
(SANDBOX / "logs").mkdir(parents=True, exist_ok=True)
shutil.copy(REPO / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
shutil.copy(REPO / "resources" / "instructions.txt", SANDBOX / "config" / "instructions.txt")
(SANDBOX / "config" / ".env").write_text(
    "DISCORD_TOKEN_1=fake" + "z" * 30 + "\nGROQ_API_KEY_1=gsk_fake\n", encoding="utf-8")
sys.path.insert(0, str(REPO))

# Redirect DATA_DIR before anything imports it.
import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.REQUIRED_SUBDIRS = [SANDBOX / "config" / "pictures", SANDBOX / "config" / "temp",
                          SANDBOX / "ipc", SANDBOX / "logs", SANDBOX / "backups"]
for d in paths.REQUIRED_SUBDIRS:
    d.mkdir(parents=True, exist_ok=True)

import app.utils.helpers as helpers
helpers.resource_path = lambda rel: str(
    (SANDBOX if (rel.replace("\\", "/").split("/")[0] in ("config", "ipc")) else paths.APP_DIR) / rel)

import app.core.ipc as ipc
ipc.CONFIG_DIR = SANDBOX / "config"
ipc.IPC_DIR = SANDBOX / "ipc"

import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


# ── logbus ───────────────────────────────────────────────────────────────────
print("\n== logbus ==")
bus = logbus.bus
q = bus.subscribe()
bus.append("test", "hello world")
check("append lands in buffer", any(e["text"] == "hello world" for e in bus.tail(10)))
check("append writes to jsonl", bus.file_path.exists() and "hello world" in bus.file_path.read_text(encoding="utf-8"))
check("SUBSCRIBER RECEIVES the line", not q.empty(),
      "queue empty -> live log stream delivers nothing")
bus.append("test", "\x1b[31mred\x1b[0m text")
check("ANSI stripped", any(e["text"] == "red text" for e in bus.tail(5)))

# publish_sync contract
q2 = bus.subscribe()
bus.publish({"marker": "new-entry"})
got = q2.get_nowait() if not q2.empty() else None
check("publish delivers the entry", got is not None and got.get("marker") == "new-entry", f"got {got!r}")
bus.unsubscribe(q)
bus.unsubscribe(q2)

# ── server ───────────────────────────────────────────────────────────────────
print("\n== server ==")
from fastapi.testclient import TestClient
from app.web.server import create_app

paths.seed_data_dir = lambda: None      # already seeded above
app_obj = create_app(supervisor=None)
client = TestClient(app_obj)

# The panel has no login: every route answers straight away, and the auth
# endpoints must be gone rather than merely permissive.
r = client.get("/api/config")
check("GET works with no login", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

for gone in ("/api/auth/me", "/api/auth/login", "/api/auth/logout"):
    r = client.post(gone, json={}) if gone != "/api/auth/me" else client.get(gone)
    check(f"{gone} is gone", r.status_code == 404, f"got {r.status_code}")

r = client.post("/api/config", json={"config": {}})
check("mutation needs no csrf token", r.status_code != 403, f"got {r.status_code}")
check("empty config still rejected (would wipe the file)", r.status_code == 400, f"got {r.status_code}")
good = client.get("/api/config").json()
r = client.post("/api/config", json={"config": good})
check("valid config save allowed", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
check("config survived the round trip", "bot" in client.get("/api/config").json())

# Unmatched /api paths must 404, not fall through to the SPA
r = client.get("/api/definitely-not-a-route")
check("unmatched /api path returns 404 json", r.status_code == 404 and "html" not in r.text.lower(),
      f"{r.status_code} {r.text[:80]!r}")

# ── SPA path traversal ───────────────────────────────────────────────────────
print("\n== static file handler ==")
secret = SANDBOX / "config" / ".env"
for probe in ["../config/.env", "..%2fconfig%2f.env", "....//config/.env"]:
    r = client.get("/" + probe)
    leaked = "DISCORD_TOKEN" in r.text
    check(f"no traversal via {probe!r}", not leaked, "SERVED config/.env")

# ── IPC round trip ───────────────────────────────────────────────────────────
print("\n== ipc ==")
cid = ipc.send_command(1, "pause", {})
f = ipc.cmd_file(1)
check("command written to per-account file", f.exists() and json.loads(f.read_text())[0]["cmd"] == "pause")
check("command file is a list", isinstance(json.loads(f.read_text()), list))
cid2 = ipc.send_command(1, "wipe", {})
entries = json.loads(f.read_text())
check("second command appended, first kept", len(entries) == 2 and entries[0]["id"] == cid)
check("snap target routes to ipc dir", str(ipc.cmd_file("snap")).replace("\\", "/").endswith("ipc/tg_commands_snap.json"))
check("snap2 target routes correctly", str(ipc.cmd_file("snap2")).replace("\\", "/").endswith("ipc/tg_commands_snap2.json"))

import asyncio
rf = ipc.result_file(1)
rf.write_text(json.dumps({cid: {"paused": True}}), encoding="utf-8")
res = asyncio.run(ipc.wait_for_result(1, cid, timeout=2))
check("result read back", res == {"paused": True}, str(res))
check("result consumed from file", cid not in json.loads(rf.read_text()))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
