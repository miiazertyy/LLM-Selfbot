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

print("\n== a fresh install's template is not an account ==")
envfile.write_env({"DISCORD_TOKEN_1": "TOKEN_GOES_HERE", "SNAP_USERNAME_1": "your_snapchat_username",
                   "SNAP_PASSWORD_1": "your_snapchat_password", "GROQ_API_KEY_1": "gsk_fake"})
envfile.reload_into_process()
check("placeholders are not listed as accounts", client.get("/api/accounts/slots").json()["slots"] == [],
      str(client.get("/api/accounts/slots").json()["slots"]))
check("which matches what the workers count", ipc._count_accounts() == 0 and ipc._count_snap_accounts() == 0)
r = client.post("/api/accounts/slots/discord", json={"token": "realTokenXYZ"})
check("the first real account takes slot 1 over from the template",
      r.status_code == 200 and r.json().get("index") == 1 and env().get("DISCORD_TOKEN_1") == "realTokenXYZ",
      r.text[:150])
envfile.write_env({"SNAP_USERNAME_1": "realuser", "SNAP_PASSWORD_1": "your_snapchat_password"})
envfile.reload_into_process()
snap1 = [s for s in client.get("/api/accounts/slots").json()["slots"] if s["platform"] == "snapchat"]
check("a real login with the template's password reads as having none",
      len(snap1) == 1 and snap1[0].get("password_set") is False, str(snap1))
# Back to where the rest of this file expects to start.
(SANDBOX / "config" / ".env").write_text(
    "# a comment that must survive every write\n"
    "GROQ_API_KEY_1=gsk_fake\n", encoding="utf-8")
for k in ("DISCORD_TOKEN_1", "SNAP_USERNAME_1", "SNAP_PASSWORD_1"):
    os.environ.pop(k, None)
envfile.reload_into_process()

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

print("\n== adding a Discord account by signing in through a browser ==")
# Nothing here opens a browser: the helper's own state machine is driven with
# the lines the Node script would have printed, and what is checked is what the
# app does with each of them.
from app.utils import discord_browser_login as bl


class _FakeProc:
    """A finished node process that printed `lines`."""

    def __init__(self, lines):
        self.stdout = iter(lines)

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _drive(lines):
    bl._state.update(running=True, state="opening", detail="", reason="")
    bl._token = None
    bl._pump(_FakeProc(lines))
    return bl.status()


st = _drive(['{"state":"opening","detail":"Starting the browser"}',
             '{"state":"waiting","detail":"Sign in to Discord"}',
             '{"ok":true,"token":"TOK.FROM.BROWSER"}'])
check("a signed-in browser finishes the sign-in", st["state"] == "done" and not st["running"], str(st))
check("the token never appears in what the page is shown", "token" not in st, str(st))
check("but it is there to be taken once", bl.take_token() == "TOK.FROM.BROWSER")
check("and only once", bl.take_token() is None)

st = _drive(['{"state":"waiting"}',
             '{"ok":false,"reason":"The browser was closed before the login finished."}'])
check("closing the window is reported plainly",
      st["state"] == "failed" and "closed" in st["reason"], str(st))
check("and leaves no token behind", bl.take_token() is None)

st = _drive(['Debugger attached.', 'not json at all', '{"state":"waiting"}'])
check("a script that stops without an answer is a failure, not a hang",
      st["state"] == "failed" and not st["running"], str(st))

st = _drive(['{"state":"waiting"}', '{"ok":true}'])
check("an ok with no token is not treated as a success", st["state"] == "failed", str(st))

bl._state.update(running=True, state="waiting")
st = bl.cancel()
check("cancelling puts it back to idle", st["state"] == "idle" and not st["running"], str(st))

# Cancelling kills the browser, so the script cannot tidy up after itself; the
# profile is Python's to remove or every cancelled sign-in leaves one behind.
import tempfile as _tf
_prof = _tf.mkdtemp(prefix=bl._PROFILE_PREFIX)
bl._profile = _prof
bl.cancel()
check("and takes the browser profile with it", not os.path.isdir(_prof), _prof)
_stale = _tf.mkdtemp(prefix=bl._PROFILE_PREFIX)
bl._sweep_old_profiles()
check("a profile a previous run was killed with is swept up", not os.path.isdir(_stale), _stale)

# What it needs, reported as something to go and do rather than a stack trace.
import shutil as _sh
_orig_which = _sh.which
_sh.which = lambda name: None
try:
    _, _, why = bl._requirements()
finally:
    _sh.which = _orig_which
check("no Node.js is explained, with the fallback named",
      "Node.js" in why and "paste a token" in why, why)

envfile.write_env({"GROQ_API_KEY_1": "gsk_fake"})
envfile.reload_into_process()
for k in ("DISCORD_TOKEN_1", "DISCORD_PROXY_1"):
    os.environ.pop(k, None)

# The routes, with the browser half stubbed: what matters here is that a
# finished sign-in becomes a stored slot and that the token never comes back
# out through the API.
_started = {}
bl.start = lambda proxy=None, timeout_ms=600000: (
    _started.update(proxy=proxy) or {"running": True, "state": "opening", "detail": "", "reason": ""})

r = client.post("/api/accounts/discord/browser-login/start", json={"proxy": "http://p"})
check("starting opens the browser and says so", r.json().get("state") == "opening", r.text[:200])
check("the proxy is passed through to the browser", _started.get("proxy") == "http://p", str(_started))

bl.status = lambda: {"running": True, "state": "waiting", "detail": "Sign in", "reason": ""}
r = client.get("/api/accounts/discord/browser-login/status")
check("while it waits, nothing is added", r.json().get("state") == "waiting" and "DISCORD_TOKEN_1" not in env(), r.text[:200])

bl.status = lambda: {"running": False, "state": "done", "detail": "Signed in", "reason": ""}
bl.take_token = lambda: "BROWSER.TOKEN"
r = client.get("/api/accounts/discord/browser-login/status?proxy=http://p")
check("a finished sign-in adds the account", r.json().get("index") == 1, r.text[:200])
check("its token is stored, with the proxy",
      env().get("DISCORD_TOKEN_1") == "BROWSER.TOKEN" and env().get("DISCORD_PROXY_1") == "http://p")
check("and never sent back to the page", "BROWSER.TOKEN" not in r.text, r.text[:200])

# The token is taken once, so polling again must not add a second slot.
bl.take_token = lambda: None
r = client.get("/api/accounts/discord/browser-login/status")
check("polling again does not add it twice",
      "DISCORD_TOKEN_2" not in env() and r.json().get("state") == "done", r.text[:200])

bl.status = lambda: {"running": False, "state": "failed", "detail": "",
                     "reason": "The browser was closed before the login finished."}
r = client.get("/api/accounts/discord/browser-login/status")
check("a failed sign-in adds nothing and says why",
      "DISCORD_TOKEN_2" not in env() and "closed" in r.json().get("reason", ""), r.text[:200])

_cancelled = {}
bl.cancel = lambda: _cancelled.update(hit=True) or {"running": False, "state": "idle", "detail": "", "reason": ""}
r = client.post("/api/accounts/discord/browser-login/cancel")
check("cancelling closes the browser", _cancelled.get("hit") and r.json().get("state") == "idle", r.text[:200])

# The password route is gone. A catch-all further down answers the path now,
# so what matters is that it refuses rather than logging anybody in.
_gone = client.post("/api/accounts/discord/login", json={"email": "a", "password": "b"})
check("the password login route no longer logs anyone in",
      _gone.status_code >= 400 and "DISCORD_TOKEN_2" not in env(),
      f"{_gone.status_code}: {_gone.text[:120]}")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
