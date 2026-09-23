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

print()
print("== the waiting list carries the avatar ==")
# The rows showed a grey placeholder glyph for everyone, though the avatar has
# been in user_profiles the whole time. It is joined on in the route rather
# than asked of the runner: the runner may be mid-reply, sqlite is right here.
# The section above swapped the stub out for one that captures payloads.
chat_routes.ipc.send_and_wait = fake_send_and_wait
from app.utils.db import set_profile_details
set_profile_details(SNOWFLAKE, username="someone", display_name="Someone",
                    avatar="https://cdn.example/a.png")

_row = client.get("/api/chats").json()["users"][0]
check("the avatar comes through", _row.get("avatar") == "https://cdn.example/a.png",
      repr(_row.get("avatar")))
check("and the username with it", _row.get("username") == "someone", repr(_row.get("username")))
check("the id is still a string", isinstance(_row["id"], str))

# Someone with no profile row must not break the response.
async def _fake_two(target, cmd, payload=None, timeout=10.0):
    if cmd == "reply_check":
        return {"users": [
            {"id": SNOWFLAKE, "name": "someone", "snippet": "hi", "count": 1},
            {"id": 999, "name": "stranger", "snippet": "yo", "count": 1},
        ]}
    return {"ok": True}


chat_routes.ipc.send_and_wait = _fake_two
_rows = client.get("/api/chats").json()["users"]
check("an unprofiled user still appears", len(_rows) == 2, str(len(_rows)))
check("with an empty avatar rather than a missing key",
      _rows[1].get("avatar") == "", repr(_rows[1].get("avatar")))
chat_routes.ipc.send_and_wait = fake_send_and_wait

print()
print("== reply to all empties the list one person at a time ==")
# It used to be one request that took as long as every reply put together, then
# wiped the whole list at the end - indistinguishable from a hang.
_chats_ts = (ROOT / "webui" / "src" / "lib" / "chats.ts").read_text(encoding="utf-8")
_page = (ROOT / "webui" / "src" / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("it no longer calls the all-at-once endpoint",
      "api.replyAll(" not in _chats_ts)
check("and no longer wipes the list in one go", "clearChats" not in _chats_ts)
check("it replies one at a time", "for (const id of queue)" in _chats_ts)
check("dropping each row as that person is answered",
      "forget(target, id)" in _chats_ts)
check("only when the reply really went out",
      "if (r?.success || r?.dropped) forget(target, id)" in _chats_ts)
check("progress is published for the button",
      "replyAllProgress" in _chats_ts and "replyAllProgress" in _page)
check("and the run can be stopped",
      "if (!get(replyingAll)[target]) break" in _chats_ts)
check("the button says where it has got to",
      "allProgress.done" in _page and "allProgress.total" in _page)
check("the row shows a real avatar when there is one",
      "u.avatar && !brokenAvatars[u.id]" in _page)
check("falling back to the glyph when the CDN link is dead",
      "brokenAvatars = { ...brokenAvatars, [u.id]: true }" in _page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
