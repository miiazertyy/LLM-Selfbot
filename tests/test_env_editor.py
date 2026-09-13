"""Editing config/.env from the app.

The important guarantee: a secret is shown masked, and sending that mask back
unchanged must NOT overwrite the real value with bullet characters. A round
trip through the UI that touches one field must leave every other field intact.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="env_test_"))
(SANDBOX / "config").mkdir(parents=True)
(SANDBOX / "ipc").mkdir(parents=True)
(SANDBOX / "logs").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
shutil.copy(ROOT / "resources" / "instructions.txt", SANDBOX / "config" / "instructions.txt")
(SANDBOX / "config" / ".env").write_text(
    "# keep me\n"
    "DISCORD_TOKEN_1=SuperSecretTokenValue123456\n"
    "GROQ_API_KEY_1=gsk_realkey_abcdefghijklmnop\n"
    "SNAP_HEADLESS=false\n", encoding="utf-8")

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
get = lambda: {v["key"]: v for v in client.get("/api/env").json()["vars"]}

print("\n== the whole file is listed ==")
rows = get()
for key in ("DISCORD_TOKEN_1", "GROQ_API_KEY_1", "SNAP_HEADLESS"):
    check(f"{key} listed", key in rows, str(sorted(rows))[:200])

print("\n== undocumented options are discoverable ==")
for key in ("SNAP_QUIET_HOURS", "SNAP_POLL_INTERVAL_MS", "SNAP_TYPING_DELAY_MS", "SNAP_AUTO_ADD_FRIENDS"):
    check(f"{key} offered from the template", key in rows, "not parsed from example.env")
check("unset options are flagged", rows["SNAP_QUIET_HOURS"]["set"] is False)
check("set options are flagged", rows["SNAP_HEADLESS"]["set"] is True)
check("template comments become help text",
      len(rows["SNAP_QUIET_HOURS"]["help"]) > 10, rows["SNAP_QUIET_HOURS"]["help"])
check("sections come from the template dividers",
      rows["SNAP_QUIET_HOURS"]["section"] != "Other", rows["SNAP_QUIET_HOURS"]["section"])

print("\n== secrets are masked on read ==")
body = client.get("/api/env").text
check("token value never sent", "SuperSecretTokenValue123456" not in body)
check("groq key value never sent", "gsk_realkey_abcdefghijklmnop" not in body)
check("token marked secret", rows["DISCORD_TOKEN_1"]["secret"] is True)
check("non-secret shown in the clear", rows["SNAP_HEADLESS"]["value"] == "false",
      rows["SNAP_HEADLESS"]["value"])
check("token flagged as account-managed", rows["DISCORD_TOKEN_1"]["managed"] is True)

print("\n== sending a mask back does not destroy the secret ==")
masked = rows["DISCORD_TOKEN_1"]["value"]
check("value came back masked", "…" in masked, masked)
r = client.post("/api/env", json={"updates": {"DISCORD_TOKEN_1": masked, "SNAP_HEADLESS": "true"}})
check("save accepted", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
check("real token untouched", env()["DISCORD_TOKEN_1"] == "SuperSecretTokenValue123456",
      env().get("DISCORD_TOKEN_1"))
check("the other edit did apply", env()["SNAP_HEADLESS"] == "true", env().get("SNAP_HEADLESS"))

print("\n== a real edit replaces the secret ==")
client.post("/api/env", json={"updates": {"GROQ_API_KEY_1": "gsk_brandnew_value"}})
check("secret replaced when actually typed", env()["GROQ_API_KEY_1"] == "gsk_brandnew_value",
      env().get("GROQ_API_KEY_1"))

print("\n== adding and deleting ==")
client.post("/api/env", json={"updates": {"SNAP_QUIET_HOURS": "2-9"}})
check("previously unset option now set", env().get("SNAP_QUIET_HOURS") == "2-9", str(env()))
check("and reads back as set", get()["SNAP_QUIET_HOURS"]["set"] is True)
client.post("/api/env", json={"updates": {}, "deletes": ["SNAP_QUIET_HOURS"]})
check("deleted from the file", "SNAP_QUIET_HOURS" not in env(), str(env()))
client.post("/api/env", json={"updates": {"TOTALLY_CUSTOM_VAR": "hello"}})
check("an arbitrary new key can be added", env().get("TOTALLY_CUSTOM_VAR") == "hello", str(env()))

print("\n== validation ==")
for bad in ("has space", "lower-case-dash", "1STARTSWITHDIGIT", ""):
    r = client.post("/api/env", json={"updates": {bad: "x"}})
    check(f"rejects key {bad!r}", r.status_code == 400, f"got {r.status_code}")
r = client.post("/api/env", json={"updates": "not-an-object"})
check("rejects a non-object updates", r.status_code == 400, f"got {r.status_code}")

print("\n== the file survives all of it ==")
text = (SANDBOX / "config" / ".env").read_text(encoding="utf-8")
check("comment preserved", "# keep me" in text, text[:200])
check("token still present", "SuperSecretTokenValue123456" in text, text[:200])

print("\n== changes reach this process immediately ==")
client.post("/api/env", json={"updates": {"SNAP_USERNAME": "someone"}})
check("os.environ updated for the counters", os.getenv("SNAP_USERNAME") == "someone",
      str(os.getenv("SNAP_USERNAME")))
check("account counter sees it", ipc._count_snap_accounts() == 1, str(ipc._count_snap_accounts()))

print("\n== numbered key families (unlimited Groq keys) ==")
# Start clean: the fixture set GROQ_API_KEY_1 earlier.
client.post("/api/env", json={"updates": {}, "deletes": ["GROQ_API_KEY_1", "GROQ_API_KEY"]})
keys = lambda: client.get("/api/env/keys/groq").json()["keys"]
check("starts empty", keys() == [], str(keys()))

for i, v in enumerate(["gsk_alpha", "gsk_bravo", "gsk_charlie"], start=1):
    r = client.post("/api/env/keys/groq", json={"value": v})
    check(f"added key {i}", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
check("three keys listed", len(keys()) == 3, str(keys()))
check("written as GROQ_API_KEY_1..3",
      [env().get(f"GROQ_API_KEY_{i}") for i in (1, 2, 3)] == ["gsk_alpha", "gsk_bravo", "gsk_charlie"],
      str({k: v for k, v in env().items() if "GROQ" in k}))
check("values never returned", "gsk_alpha" not in client.get("/api/env/keys/groq").text)

client.post("/api/env/keys/groq/2", json={"value": "gsk_replaced"})
check("replace hits the right slot", env().get("GROQ_API_KEY_2") == "gsk_replaced",
      str(env().get("GROQ_API_KEY_2")))

r = client.delete("/api/env/keys/groq/2")
check("delete accepted", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
check("numbering stays contiguous after a middle delete",
      [env().get("GROQ_API_KEY_1"), env().get("GROQ_API_KEY_2")] == ["gsk_alpha", "gsk_charlie"],
      str({k: v for k, v in env().items() if "GROQ" in k}))
check("no orphaned third slot", not env().get("GROQ_API_KEY_3"),
      str({k: v for k, v in env().items() if "GROQ" in k}))
check("two keys left", len(keys()) == 2, str(keys()))

check("unknown family 404s", client.get("/api/env/keys/nope").status_code == 404)
check("empty value rejected", client.post("/api/env/keys/groq", json={"value": "  "}).status_code == 400)
check("deleting a missing index 404s", client.delete("/api/env/keys/groq/9").status_code == 404)

print("\n== a legacy unsuffixed key folds in as #1 ==")
client.post("/api/env", json={"updates": {}, "deletes": ["GROQ_API_KEY_1", "GROQ_API_KEY_2"]})
client.post("/api/env", json={"updates": {"GROQ_API_KEY": "gsk_legacy"}})
check("legacy key seen as one entry", len(keys()) == 1, str(keys()))
client.post("/api/env/keys/groq", json={"value": "gsk_second"})
check("adding promotes it to the numbered form",
      env().get("GROQ_API_KEY_1") == "gsk_legacy" and env().get("GROQ_API_KEY_2") == "gsk_second",
      str({k: v for k, v in env().items() if "GROQ" in k}))
check("and drops the legacy key so it is not counted twice",
      "GROQ_API_KEY" not in env(), str({k: v for k, v in env().items() if "GROQ" in k}))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
