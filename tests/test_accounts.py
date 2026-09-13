"""Account slot CRUD: add / edit / delete, and the guarantees around them.

The two that matter most:
  * credentials are write-only, a GET must never return a token, even masked
  * deleting a middle slot must renumber the rest, because the account
    counters stop at the first gap in DISCORD_TOKEN_<n>
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="acct_test_"))
(SANDBOX / "config").mkdir(parents=True)
(SANDBOX / "ipc").mkdir(parents=True)
(SANDBOX / "logs").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
shutil.copy(ROOT / "resources" / "instructions.txt", SANDBOX / "config" / "instructions.txt")
(SANDBOX / "config" / ".env").write_text(
    "# a comment that must survive every write\n"
    "GROQ_API_KEY_1=gsk_fake\n", encoding="utf-8")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.seed_data_dir = lambda: None
import app.utils.helpers as helpers
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

from fastapi.testclient import TestClient
from app.web.server import create_app

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


client = TestClient(create_app(supervisor=None))
env = lambda: envfile.read_env()

print("\n== add ==")
r = client.post("/api/accounts/slots/discord", json={"token": "tokenAAA", "proxy": "http://a"})
check("first account added", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
r = client.post("/api/accounts/slots/discord", json={"token": "tokenBBB"})
r = client.post("/api/accounts/slots/discord", json={"token": "tokenCCC", "proxy": "http://c"})
slots = client.get("/api/accounts/slots").json()["slots"]
check("three discord slots", len([s for s in slots if s["platform"] == "discord"]) == 3, str(len(slots)))
check("written as DISCORD_TOKEN_1..3",
      [env().get(f"DISCORD_TOKEN_{i}") for i in (1, 2, 3)] == ["tokenAAA", "tokenBBB", "tokenCCC"],
      str(env()))
check("a token is required", client.post("/api/accounts/slots/discord", json={}).status_code == 400)
check("unknown platform rejected",
      client.post("/api/accounts/slots/myspace", json={"token": "x"}).status_code == 404)

print("\n== credentials are write-only ==")
body = client.get("/api/accounts/slots").text
check("no token value in the response", "tokenAAA" not in body and "tokenBBB" not in body, body[:200])
check("no masked token either", "…" not in body, body[:200])
check("token_set reported instead", all(s.get("token_set") for s in slots if s["platform"] == "discord"))
check("proxy IS returned (not a secret)", any(s.get("proxy") == "http://a" for s in slots))

print("\n== edit ==")
r = client.post("/api/accounts/slots/discord/2", json={"proxy": "http://newproxy"})
check("proxy updated", r.status_code == 200 and env()["DISCORD_PROXY_2"] == "http://newproxy",
      str(env().get("DISCORD_PROXY_2")))
check("blank token leaves the stored one alone", env()["DISCORD_TOKEN_2"] == "tokenBBB",
      str(env().get("DISCORD_TOKEN_2")))
client.post("/api/accounts/slots/discord/2", json={"token": "replacedBBB"})
check("a real token replaces it", env()["DISCORD_TOKEN_2"] == "replacedBBB", str(env().get("DISCORD_TOKEN_2")))
check("editing a missing slot 404s",
      client.post("/api/accounts/slots/discord/9", json={"token": "x"}).status_code == 404)

print("\n== delete renumbers ==")
r = client.delete("/api/accounts/slots/discord/2")
check("delete accepted", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
check("slot 3 moved down to 2", env().get("DISCORD_TOKEN_2") == "tokenCCC", str(env().get("DISCORD_TOKEN_2")))
check("its proxy moved with it", env().get("DISCORD_PROXY_2") == "http://c", str(env().get("DISCORD_PROXY_2")))
check("no gap left behind", "DISCORD_TOKEN_3" not in env() or not env()["DISCORD_TOKEN_3"], str(env()))
check("the counter sees exactly 2", ipc._count_accounts() == 2, str(ipc._count_accounts()))

print("\n== snapchat ==")
client.post("/api/accounts/slots/snapchat", json={"username": "snapuser", "password": "hunter2"})
slots = client.get("/api/accounts/slots").json()["slots"]
snap = [s for s in slots if s["platform"] == "snapchat"]
check("snapchat slot added", len(snap) == 1, str(snap))
check("username is visible", snap and snap[0].get("username") == "snapuser", str(snap))
check("password is not", "hunter2" not in client.get("/api/accounts/slots").text)
check("password_set reported", snap and snap[0].get("password_set") is True, str(snap))
check("counter sees the snap account", ipc._count_snap_accounts() == 1, str(ipc._count_snap_accounts()))

print("\n== the .env file survives ==")
text = (SANDBOX / "config" / ".env").read_text(encoding="utf-8")
check("comment preserved", "# a comment that must survive every write" in text, text[:200])
check("unrelated key preserved", "GROQ_API_KEY_1=gsk_fake" in text, text[:200])

print("\n== legacy unsuffixed keys fold into slot 1 ==")
envfile.write_env({"DISCORD_TOKEN": "legacyTok", "GROQ_API_KEY_1": "gsk_fake"})
envfile.reload_into_process()
slots = client.get("/api/accounts/slots").json()["slots"]
d = [s for s in slots if s["platform"] == "discord"]
check("legacy DISCORD_TOKEN shows as one account", len(d) == 1, str(d))
check("and is not duplicated", not (len(d) > 1), str(d))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
