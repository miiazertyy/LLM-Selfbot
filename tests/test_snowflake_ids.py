"""Discord IDs must reach the browser as strings.

A snowflake is a 64-bit integer, about 19 digits. JavaScript parses a JSON
number into a double, which is exact only up to 2**53, so an id sent as a
number comes back changed:

    1234567890123456789  ->  1234567890123456768

Replying then failed with "404 (error code: 10013): Unknown User" for a user
that plainly exists. These tests pin the ids as strings on every response the
browser reads.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="ids_test_"))
for sub in ("config", "ipc", "logs"):
    (SANDBOX / sub).mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
(SANDBOX / "config" / ".env").write_text("DISCORD_TOKEN_1=aaa\n", encoding="utf-8")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.seed_data_dir = lambda: None
import app.utils.helpers as helpers
helpers.get_env_path = lambda: str(SANDBOX / "config" / ".env")
helpers.resource_path = lambda rel: str(
    (SANDBOX if rel.replace("\\", "/").split("/")[0] in ("config", "ipc") else paths.APP_DIR) / rel)
import app.web.envfile as envfile
envfile.ENV_PATH = SANDBOX / "config" / ".env"
import app.core.ipc as ipc
ipc.CONFIG_DIR = SANDBOX / "config"
ipc.IPC_DIR = SANDBOX / "ipc"
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"

import app.cli as cli
cli.load_env()

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


# A real-shaped snowflake, chosen to be corrupted by a double round trip.
SNOWFLAKE = 1234567890123456789
check("the test id really is unsafe for JS",
      int(float(SNOWFLAKE)) != SNOWFLAKE, "pick a bigger id")

# Stub the IPC so no runner is needed.
async def fake_send_and_wait(target, cmd, payload=None, timeout=10.0):
    if cmd == "reply_check":
        return {"users": [{"id": SNOWFLAKE, "name": "someone", "snippet": "hi", "count": 1}]}
    if cmd == "reply_all":
        return {"total": 1, "results": [{"id": SNOWFLAKE, "name": "someone", "success": True}]}
    return {"ok": True, "echo": payload}


import app.web.routes.chat_routes as chat_routes
chat_routes.ipc.send_and_wait = fake_send_and_wait

from fastapi.testclient import TestClient
from app.web.server import create_app

client = TestClient(create_app(supervisor=None))

print("\n== /api/chats ==")
raw = client.get("/api/chats").text
body = json.loads(raw)
uid = body["users"][0]["id"]
check("id is a string", isinstance(uid, str), f"{type(uid).__name__}: {uid!r}")
check("id is exact", uid == str(SNOWFLAKE), uid)
check("id is not serialised as a bare number", f'"id": {SNOWFLAKE}' not in raw and f'"id":{SNOWFLAKE}' not in raw)
check("surviving a JS-style parse leaves it intact",
      json.loads(raw)["users"][0]["id"] == str(SNOWFLAKE))

print("\n== /api/chats/reply-all ==")
body = client.post("/api/chats/reply-all", json={}).json()
rid = body["results"][0]["id"]
check("result id is a string", isinstance(rid, str), f"{type(rid).__name__}")
check("result id is exact", rid == str(SNOWFLAKE), rid)

print("\n== a string id round-trips back to the runner as an int ==")
sent = {}


async def capture(target, cmd, payload=None, timeout=10.0):
    sent.update(payload or {})
    return {"success": True}


chat_routes.ipc.send_and_wait = capture
r = client.post("/api/chats/reply", json={"user_id": str(SNOWFLAKE)})
check("reply accepted", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
check("runner receives the exact id", sent.get("user_id") == SNOWFLAKE,
      f"{sent.get('user_id')} vs {SNOWFLAKE}")
check("and as an int, which is what discord.py wants",
      isinstance(sent.get("user_id"), int), type(sent.get("user_id")).__name__)

print("\n== /api/memory ==")
from app.utils.db import init_db
from app.utils.memory import init_memory, set_memory
init_db()
init_memory()
set_memory(SNOWFLAKE, "likes", "pizza")

raw = client.get("/api/memory").text
data = json.loads(raw)
row = next((v for v in data.get("users", []) if str(v.get("user_id")) == str(SNOWFLAKE)), None)
if row is None:
    check("memory row present", False, raw[:250])
else:
    check("memory user_id is a string", isinstance(row["user_id"], str), type(row["user_id"]).__name__)
    check("memory user_id is exact", row["user_id"] == str(SNOWFLAKE), row["user_id"])
    check("not serialised as a bare number",
          f'"user_id": {SNOWFLAKE}' not in raw and f'"user_id":{SNOWFLAKE}' not in raw)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
