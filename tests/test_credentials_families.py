"""Several accounts, each with the fields that belong to it.

A Discord account is a token plus a proxy; a Snapchat account is a username
plus a password. They are stored as parallel numbered variables, so the pairing
is by index alone:

    DISCORD_TOKEN_2 goes with DISCORD_PROXY_2

Which means removing account 2 of 3 has to renumber every field together. Move
only the tokens and account 3's proxy stays behind on account 2, quietly
sending someone else's traffic through the wrong machine.
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


SANDBOX = Path(tempfile.mkdtemp(prefix="fam_"))
(SANDBOX / "config").mkdir(parents=True)
ENV = SANDBOX / "config" / ".env"

import app.web.envfile as envfile
envfile.ENV_PATH = ENV
import app.web.routes.env_routes as env_routes
env_routes.read_env = envfile.read_env
env_routes.write_env = envfile.write_env
env_routes.reload_into_process = lambda values: None


class Req:
    def __init__(self, body=None):
        self._body = body or {}

    async def json(self):
        return self._body


def env_text():
    return ENV.read_text(encoding="utf-8")


def reset():
    ENV.write_text(
        "DISCORD_TOKEN_1=tokenAAAAAAAAAAAAAAAAAAAA\n"
        "DISCORD_PROXY_1=http://one:1\n"
        "DISCORD_TOKEN_2=tokenBBBBBBBBBBBBBBBBBBBB\n"
        "DISCORD_PROXY_2=http://two:2\n"
        "DISCORD_TOKEN_3=tokenCCCCCCCCCCCCCCCCCCCC\n"
        "DISCORD_PROXY_3=http://three:3\n",
        encoding="utf-8")


# ── Reading them back ───────────────────────────────────────────────────────
print("== every account is listed with its own fields ==")
reset()
out = asyncio.run(env_routes.list_keys(Req(), "discord"))
check("all three accounts", len(out["keys"]) == 3, str(len(out["keys"])))
check("the token is masked, never returned",
      "tokenAAAA" not in str(out), "a token came back in full")
check("the proxy is not masked, it is not a secret",
      out["keys"][0]["extras"]["DISCORD_PROXY"]["preview"] == "http://one:1")
check("the extras are described for the UI",
      any(e["prefix"] == "DISCORD_PROXY" for e in out["extras"]))

# ── The pairing has to survive a removal ────────────────────────────────────
print()
print("== removing one keeps the rest paired ==")
reset()
asyncio.run(env_routes.delete_key(Req(), "discord", 2))
text = env_text()
check("account 2 is gone", "tokenBBBB" not in text)
check("the third token moved down", "DISCORD_TOKEN_2=tokenCCCCCCCCCCCCCCCCCCCC" in text, text)
check("and took its own proxy with it", "DISCORD_PROXY_2=http://three:3" in text, text)
check("the removed proxy is gone", "http://two:2" not in text, text)
check("numbering has no gap", "DISCORD_TOKEN_3" not in text, text)

# ── Editing one field without retyping the other ────────────────────────────
print()
print("== a proxy can be changed without retyping the token ==")
reset()
asyncio.run(env_routes.replace_key(
    Req({"value": "", "keep": True, "DISCORD_PROXY": "http://changed:9"}), "discord", 1))
text = env_text()
check("the token is untouched", "DISCORD_TOKEN_1=tokenAAAAAAAAAAAAAAAAAAAA" in text, text)
check("the proxy changed", "DISCORD_PROXY_1=http://changed:9" in text, text)

print()
print("== but a blank token with no keep is still refused ==")
reset()
try:
    asyncio.run(env_routes.replace_key(Req({"value": ""}), "discord", 1))
    check("an empty value is rejected", False, "it was accepted")
except Exception as exc:
    check("an empty value is rejected", "required" in str(getattr(exc, "detail", exc)))

# ── Snapchat pairs ──────────────────────────────────────────────────────────
print()
print("== snapchat logins are a username and a password ==")
ENV.write_text("SNAP_USERNAME=alice\nSNAP_PASSWORD=firstpw\n", encoding="utf-8")
asyncio.run(env_routes.add_key(Req({"value": "bob", "SNAP_PASSWORD": "secondpw"}), "snapchat"))
text = env_text()
check("the legacy unnumbered login became #1", "SNAP_USERNAME_1=alice" in text, text)
check("its password came with it", "SNAP_PASSWORD_1=firstpw" in text, text)
check("the new login is #2", "SNAP_USERNAME_2=bob" in text, text)
check("with its own password", "SNAP_PASSWORD_2=secondpw" in text, text)

out = asyncio.run(env_routes.list_keys(Req(), "snapchat"))
check("usernames are shown in full, they are not secret",
      out["keys"][0]["preview"] == "alice", out["keys"][0]["preview"])
check("passwords are masked", "firstpw" not in str(out), "a password came back in full")

# The count the supervisor uses has to agree, or it plans the wrong children.
import os
for key, value in envfile.read_env().items():
    os.environ[key] = value
from app.core import ipc
check("the supervisor sees two snapchat accounts", ipc._count_snap_accounts() == 2,
      str(ipc._count_snap_accounts()))

print()
print("== an unknown family is a clean 404, not a crash ==")
try:
    asyncio.run(env_routes.list_keys(Req(), "nonsense"))
    check("unknown family refused", False)
except Exception as exc:
    check("unknown family refused", "unknown key family" in str(getattr(exc, "detail", exc)))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
