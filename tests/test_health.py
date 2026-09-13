"""The attention dots: what counts as a problem, and which page fixes it.

Each issue must name a real route, or the sidebar would put a dot on nothing.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="health_test_"))
for sub in ("config", "ipc", "logs"):
    (SANDBOX / sub).mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
(SANDBOX / "config" / ".env").write_text("", encoding="utf-8")

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

from fastapi.testclient import TestClient
from app.web.server import create_app

# The routes the sidebar actually has; an issue pointing anywhere else would
# render a dot on no page at all.
ROUTES = {"dashboard", "accounts", "chats", "persona", "memory", "pictures",
          "stats", "logs", "settings", "snapchat", "system"}

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def clear_env():
    for k in list(os.environ):
        if k.startswith(("DISCORD_TOKEN", "GROQ_API_KEY", "SNAP_USERNAME", "TELEGRAM_")):
            os.environ.pop(k, None)


class Stub:
    port = 0

    def __init__(self, children=()):
        self._c = list(children)

    def status(self):
        return self._c


def health(supervisor=None):
    """The uncached answer.

    /api/health serves a snapshot refreshed on a worker thread, because working
    it out starts node and makes network calls, and doing that on the event loop
    froze the whole panel every time the cache expired. These tests change the
    conditions and immediately ask again, so they need the answer computed now
    rather than the one from a moment ago.
    """
    return TestClient(create_app(supervisor=supervisor)).get("/api/health/blocking").json()


print("\n== a blank install reports the real blockers ==")
clear_env()
h = health()
titles = [i["title"] for i in h["issues"]]
check("flags the missing Groq key", any("Groq" in t for t in titles), str(titles))
check("flags having no accounts", any("No accounts" in t for t in titles), str(titles))
check("both are errors, not warnings", h["errors"] >= 2, str(h))

print("\n== every issue points at a real page ==")
for issue in h["issues"]:
    check(f"{issue['title']!r} -> {issue['route']}", issue["route"] in ROUTES, issue["route"])
check("routes map is built from the issues",
      set(h["routes"]) <= ROUTES and set(h["routes"]) == {i["route"] for i in h["issues"]},
      str(h["routes"]))

print("\n== every issue explains itself ==")
for issue in h["issues"]:
    check(f"{issue['title']!r} has a usable explanation", len(issue["detail"]) > 25, issue["detail"])
    check(f"{issue['title']!r} has a known level",
          issue["level"] in ("error", "warn", "info"), issue["level"])

print("\n== configuring things clears them ==")
os.environ["GROQ_API_KEY_1"] = "gsk_real_key_value"
os.environ["DISCORD_TOKEN_1"] = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.FgHiJkLmNo"
(SANDBOX / "config" / "instructions.txt").write_text("you are a chill person", encoding="utf-8")
h = health()
titles = [i["title"] for i in h["issues"]]
check("Groq warning gone", not any("Groq" in t for t in titles), str(titles))
check("no-accounts warning gone", not any("No accounts" in t for t in titles), str(titles))
check("persona warning gone", not any("persona" in t.lower() for t in titles), str(titles))

print("\n== a crash-looping account is reported ==")
h = health(Stub([{"id": "discord_1", "label": "Discord #1", "state": "crashing", "restarts": 4}]))
crash = [i for i in h["issues"] if "crashing" in i["title"]]
check("crashing child flagged", len(crash) == 1, str([i["title"] for i in h["issues"]]))
check("and points at Accounts", crash and crash[0]["route"] == "accounts", str(crash))
check("as an error", crash and crash[0]["level"] == "error", str(crash))

print("\n== repeated restarts are a warning, not an error ==")
h = health(Stub([{"id": "discord_1", "label": "Discord #1", "state": "running", "restarts": 5}]))
warn = [i for i in h["issues"] if "restarted" in i["title"]]
check("restart loop flagged", len(warn) == 1, str([i["title"] for i in h["issues"]]))
check("as a warning", warn and warn[0]["level"] == "warn", str(warn))

print("\n== a healthy child produces nothing ==")
h = health(Stub([{"id": "discord_1", "label": "Discord #1", "state": "running", "restarts": 0}]))
acct = [i for i in h["issues"] if i["route"] == "accounts"]
check("no account issues when all is well", acct == [], str(acct))

print("\n== half-configured Telegram is caught ==")
os.environ["TELEGRAM_BOT_TOKEN"] = "7123456789:AAHfake"
os.environ.pop("TELEGRAM_OWNER_ID", None)
h = health()
tg = [i for i in h["issues"] if "Telegram" in i["title"]]
check("flagged", len(tg) == 1, str([i["title"] for i in h["issues"]]))
check("as a warning on Settings", tg and tg[0]["level"] == "warn" and tg[0]["route"] == "settings", str(tg))
os.environ["TELEGRAM_OWNER_ID"] = "1234567890"
h = health()
check("cleared once both halves are set",
      not [i for i in h["issues"] if "Telegram" in i["title"]], str(h["issues"]))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
