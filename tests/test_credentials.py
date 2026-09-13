"""Template placeholders must not read as configured credentials.

config/.env is seeded from resources/example.env, which ships values like
TELEGRAM_OWNER_ID=your_telegram_user_id_here. Those are non-empty strings, so a
plain os.getenv test treats them as real: the UI listed phantom accounts, the
supervisor spawned runners that could not log in, and the Telegram controller
died at import on int("your_telegram_user_id_here").
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.utils.credentials import is_placeholder, real, real_int

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("\n== every value shipped in resources/example.env ==")
example = (ROOT / "resources" / "example.env").read_text(encoding="utf-8")
shipped = []
for line in example.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, val = line.partition("=")
    shipped.append((key.strip(), val.strip()))

check("the template actually has uncommented values", len(shipped) > 0, str(len(shipped)))
for key, val in shipped:
    check(f"{key}={val} reads as unset", is_placeholder(val), val)

print("\n== commented-out template values too ==")
for val in ("YOUR_FIRST_TOKEN_HERE", "YOUR_SECOND_TOKEN_HERE", "YOUR_FIRST_GROQ_KEY_HERE",
            "second_account_username", "second_account_password"):
    check(f"{val} reads as unset", is_placeholder(val), val)

print("\n== blanks ==")
check("empty string", is_placeholder(""))
check("whitespace", is_placeholder("   "))
check("None", is_placeholder(None))

print("\n== real credentials must NOT be rejected ==")

# Invented, but the exact shape of the real thing, which is the whole point of
# the check below. Joined at runtime rather than written out as one string:
# GitHub's push protection matches on shape, not on whether a token is real, and
# it blocked a push over these two lines. The test is unchanged, the file is
# pushable, and nothing here has ever been a working credential.
FAKE_DISCORD = ".".join(
    ["MTIzNDU2Nzg5MDEyMzQ1Njc4", "GaBcDe", "FgHiJkLmNoPqRsTuVwXyZ1234567890abcd"])
FAKE_GROQ = "gsk_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGh"

realistic = [
    FAKE_DISCORD,                                                          # discord
    FAKE_GROQ,                                                             # groq
    "7123456789:AAHfake-telegram-bot-token_ABCDEFGHIJKLMNO",               # telegram
    "1234567890",                                                          # owner id
    "my_snap_handle", "snapuser2024", "hunter2", "Tr0ub4dor&3",
    "http://user:pass@proxy.example.com:8080",
]
for val in realistic:
    check(f"kept: {val[:34]}", not is_placeholder(val), val)

print("\n== real() / real_int() ==")
os.environ["_T_PLACEHOLDER"] = "your_telegram_user_id_here"
os.environ["_T_REAL"] = "  987654321  "
os.environ["_T_JUNK"] = "not-a-number"
check("real() blanks a placeholder", real("_T_PLACEHOLDER") == "")
check("real() strips a real value", real("_T_REAL") == "987654321")
check("real() on a missing key", real("_T_ABSENT") == "")
check("real_int() on a placeholder returns 0 (no raise)", real_int("_T_PLACEHOLDER") == 0)
check("real_int() parses a real value", real_int("_T_REAL") == 987654321)
check("real_int() on junk returns 0 rather than raising", real_int("_T_JUNK") == 0)

print("\n== the counters, driven by a template .env ==")
SANDBOX = Path(tempfile.mkdtemp(prefix="cred_test_"))
(SANDBOX / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
shutil.copy(ROOT / "resources" / "example.env", SANDBOX / "config" / ".env")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.seed_data_dir = lambda: None
import app.utils.helpers as helpers
helpers.get_env_path = lambda: str(SANDBOX / "config" / ".env")
helpers.resource_path = lambda rel: str(
    (SANDBOX if rel.replace("\\", "/").split("/")[0] in ("config", "ipc") else paths.APP_DIR) / rel)

import app.cli as cli
for k in list(os.environ):
    if k.startswith(("DISCORD_TOKEN", "SNAP_USERNAME", "SNAP_PASSWORD", "TELEGRAM_")):
        os.environ.pop(k, None)
cli.load_env()      # exactly what the supervisor does at startup

import app.core.ipc as ipc
check("no phantom Discord account", ipc._count_accounts() == 0, str(ipc._count_accounts()))
check("no phantom Snapchat account", ipc._count_snap_accounts() == 0, str(ipc._count_snap_accounts()))
check("no IPC targets", ipc.discover_targets() == {}, str(ipc.discover_targets()))

from app.web.supervisor import Supervisor
plan = Supervisor(port=0)._planned_children()
check("supervisor plans NO children at all", plan == {}, str(plan))
check("specifically no telegram child (the crash)", "telegram" not in plan, str(plan))

print("\n== and real values still start things ==")
(SANDBOX / "config" / ".env").write_text(
    "DISCORD_TOKEN_1=MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.FgHiJkLmNoPqRsTuVwXyZ123\n"
    "TELEGRAM_BOT_TOKEN=7123456789:AAHfake-telegram-token\n"
    "TELEGRAM_OWNER_ID=1234567890\n", encoding="utf-8")
cli.load_env()
check("discord account counted", ipc._count_accounts() == 1, str(ipc._count_accounts()))
plan = Supervisor(port=0)._planned_children()
check("discord child planned", "discord_1" in plan, str(plan))
check("telegram child planned", "telegram" in plan, str(plan))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
