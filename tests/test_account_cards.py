"""The Accounts page: what each account card is built from.

Each card shows its own account's replies, so replies now record which account
sent them. What is checked here:

  * old databases gain the column without losing a row, and old untagged rows
    are only counted for an account when there is no doubt whose they are
  * removing an account keeps every reply (and saved name and picture) with
    the account that sent it, although the later accounts are renumbered
  * /api/accounts says why a crashing account crashes - the exception, not the
    "Traceback (most recent call last):" line above it - and what a Snapchat
    login is waiting on
  * the page is wired up: warmed at launch, and "Its chats" / "Its log" open
    already pointed at the account
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui"
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="acct_cards_"))
for d in ("config", "ipc", "logs"):
    (SANDBOX / d).mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.seed_data_dir = lambda: None
import app.utils.helpers as helpers
helpers.DATA_DIR = SANDBOX
helpers.resource_path = lambda rel: str(
    (SANDBOX if rel.replace("\\", "/").split("/")[0] in ("config", "ipc") else paths.APP_DIR) / rel)
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"

import app.utils.db as db
assert str(SANDBOX) in db.resource_path(db.db_path), "the test database must be the sandbox's"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


# ── An existing database gains the column ───────────────────────────────────
print("== an old database is upgraded in place ==")
conn = db.connect_raw()
conn.execute("CREATE TABLE message_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
             "username TEXT NOT NULL, ts REAL NOT NULL)")
conn.execute("CREATE TABLE message_log_snap (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, "
             "username TEXT NOT NULL, ts REAL NOT NULL)")
now = time.time()
conn.executemany("INSERT INTO message_log (user_id, username, ts) VALUES (?, ?, ?)",
                 [(1, "old", now - 100), (1, "old", now - 200), (2, "older", now - 3 * 86400)])
conn.commit()
conn.close()
db.init_db()
conn = db.connect_raw()
cols = {r[1] for r in conn.execute("PRAGMA table_info(message_log)")}
check("message_log has an account column", "account" in cols, str(cols))
check("so does the Snapchat log", "account" in {r[1] for r in conn.execute("PRAGMA table_info(message_log_snap)")})
rows = conn.execute("SELECT username, account FROM message_log ORDER BY id").fetchall()
check("every old row is still there, untagged", rows == [("old", None), ("old", None), ("older", None)], str(rows))
conn.close()

db.record_user_message(10, "tagged", account=1)
db.record_user_message(20, "second", account=2)
db.record_user_message(20, "second", account=2)
db.record_user_message_snap("chat-x", "snappy", account=1)
db.record_user_message(30, "anonymous")          # callers that do not say
conn = db.connect_raw()
got = conn.execute("SELECT username, account FROM message_log WHERE username IN ('tagged','second','anonymous') "
                   "ORDER BY id").fetchall()
check("a reply records the account that sent it",
      got == [("tagged", 1), ("second", 2), ("second", 2), ("anonymous", None)], str(got))
check("Snapchat's too", conn.execute("SELECT account FROM message_log_snap").fetchone() == (1,))
conn.close()

# ── /api/accounts/activity ──────────────────────────────────────────────────
print("\n== each account's own figures ==")
from fastapi.testclient import TestClient
from app.web.server import create_app
from app.core import ipc


class FakeSup:
    port = 0
    rows = []

    def status(self):
        return self.rows

    def planned(self):
        return {"discord_1", "snapchat_1"}


sup = FakeSup()
client = TestClient(create_app(supervisor=sup))

one = {"discord_1": {"platform": "discord", "account": 1, "target": 1},
       "snapchat_1": {"platform": "snapchat", "account": 1, "target": "snap"}}
ipc.discover_targets = lambda: dict(one)
a = client.get("/api/accounts/activity?days=14").json()
d1 = a["accounts"]["discord_1"]
# today: 2 untagged + tagged + anonymous (untagged) = 4; the 2 from account 2
# belong to an account that does not exist here and are not counted.
check("one Discord account: the untagged history is its own", d1["today"] == 4, str(d1))
check("rows tagged with another account are not", d1["week"] == 5, str(d1))
check("a series is one entry per calendar day, today last",
      len(d1["series"]) == 14 and sum(d1["series"]) == 5 and len(a["dates"]) == 14
      and a["dates"][-1] == __import__("datetime").date.today().isoformat(), str((d1["series"], a["dates"][-2:])))
check("today is today's bar", d1["today"] == d1["series"][-1], str(d1))
check("the default is a week", len(client.get("/api/accounts/activity").json()["dates"]) == 7)
check("the last reply is the newest one", d1["last"] and d1["last"]["name"] in ("tagged", "anonymous"), str(d1["last"]))
check("people are ranked by how often", d1["top"][0]["name"] == "old" and d1["top"][0]["count"] == 2, str(d1["top"]))
check("ids go out as strings", all(isinstance(t["id"], str) for t in d1["top"]))
check("Snapchat has its own", a["accounts"]["snapchat_1"]["today"] == 1, str(a["accounts"]["snapchat_1"]))

two = dict(one, discord_2={"platform": "discord", "account": 2, "target": 2})
ipc.discover_targets = lambda: dict(two)
a = client.get("/api/accounts/activity?days=14").json()
check("two Discord accounts: untagged rows are nobody's, not guessed",
      a["accounts"]["discord_1"]["today"] == 1, str(a["accounts"]["discord_1"]))
check("each gets exactly what it sent", a["accounts"]["discord_2"]["today"] == 2, str(a["accounts"]["discord_2"]))
check("the window is capped", client.get("/api/accounts/activity?days=100000").json()["days"] == 90)

# ── Removing an account keeps history with its sender ───────────────────────
print("\n== removing one renumbers what is stored by number ==")
db.renumber_account_replies("discord", 1)
conn = db.connect_raw()
by = dict(conn.execute("SELECT username, account FROM message_log WHERE username IN ('tagged','second')").fetchall())
conn.close()
check("the removed account's replies are shown on no card", by.get("tagged") == 0, str(by))
check("the next account's replies move with it to #1", by.get("second") == 1, str(by))

from app.web.routes.account_routes import _renumber_account_data
for n, name in ((1, "Ann"), (2, "Bea"), (3, "Cy")):
    (SANDBOX / "config" / f"identity_{n}.json").write_text(json.dumps({"username": name}), encoding="utf-8")
_renumber_account_data("discord", 1, 3)
ident = {n: json.loads((SANDBOX / "config" / f"identity_{n}.json").read_text())["username"]
         for n in (1, 2) if (SANDBOX / "config" / f"identity_{n}.json").exists()}
check("the saved name and picture move up too", ident == {1: "Bea", 2: "Cy"}, str(ident))
check("and nothing is left at the old last number", not (SANDBOX / "config" / "identity_3.json").exists())

# ── /api/accounts: why, and what Snapchat is waiting on ─────────────────────
print("\n== what the page is told about each account ==")
ipc.discover_targets = lambda: dict(two)
sup.rows = [
    {"id": "discord_1", "state": "running", "pid": 1, "restarts": 0, "uptime": 50, "retry_in": None, "gave_up": False},
    {"id": "discord_2", "state": "crashing", "pid": 2, "restarts": 3, "uptime": 5, "retry_in": 40, "gave_up": False},
    {"id": "snapchat_1", "state": "running", "pid": 3, "restarts": 0, "uptime": 50, "retry_in": None, "gave_up": False},
]
bus = logbus.bus
bus.append("discord_1", "12:00:00 ✗ Nudge Loop: 403 Forbidden", "error")
bus.append("discord_2", "Traceback (most recent call last):")
bus.append("discord_2", '  File "discord_runner.py", line 1, in <module>')
bus.append("discord_2", "discord.errors.LoginFailure: Improper token has been passed.")
bus.append("discord_2", "Shutting down")
(SANDBOX / "ipc" / "snap_state.json").write_text(json.dumps(
    {"state": "awaiting-verification", "detail": "check your email", "at": time.time(), "account": 1}),
    encoding="utf-8")
acc = {x["id"]: x for x in client.get("/api/accounts").json()["accounts"]}
check("a crash reports the exception, not the traceback header",
      (acc["discord_2"].get("last_error") or {}).get("text") == "discord.errors.LoginFailure: Improper token has been passed.",
      str(acc["discord_2"].get("last_error")))
check("a plain error line is reported as it is",
      "Nudge Loop" in (acc["discord_1"].get("last_error") or {}).get("text", ""), str(acc["discord_1"].get("last_error")))
check("when a crashing account is tried again", acc["discord_2"]["retry_in"] == 40)
check("an account the supervisor would not start says so",
      acc["discord_2"]["enabled"] is False and acc["discord_1"]["enabled"] is True)
check("Snapchat's own report rides along",
      (acc["snapchat_1"].get("snap") or {}).get("state") == "awaiting-verification", str(acc["snapchat_1"].get("snap")))
check("Discord accounts do not carry one", "snap" not in acc["discord_1"])

from app.web.supervisor import Supervisor, MAX_RESTARTS
s = Supervisor()
s.register("discord_1", "discord", 1, "Discord #1")
ch = s.children["discord_1"]
ch.state, ch._retry_at = "crashing", time.time() + 30
st = s.status()[0]
check("the supervisor says when a crashing worker comes back", st["retry_in"] in (29, 30), str(st))
ch.state, ch.restarts = "stopped", MAX_RESTARTS + 1
check("and whether a stop was it giving up", s.status()[0]["gave_up"] is True)
ch.restarts = 0
check("a stop someone asked for is not", s.status()[0]["gave_up"] is False)

# ── The state logic, in Node ────────────────────────────────────────────────
print("\n== what a card says, for every state (Node) ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "accounts_logic.mjs")], cwd=WEB,
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("accounts_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

# ── Wiring ──────────────────────────────────────────────────────────────────
print("\n== the page is wired up ==")
src = WEB / "src"
read = lambda p: (src / p).read_text(encoding="utf-8")
page, card, warm, busy = read("pages/Accounts.svelte"), read("lib/accounts/AccountCard.svelte"), \
    read("lib/warm.ts"), read("lib/busy.ts")
warmed = set(re.findall(r'key: "([^"]+)"', warm))
for key in ("accounts", "accountSlots", "accountActivity"):
    check(f"{key} is loaded at launch", key in warmed)
    check(f"and loading it counts as the Accounts page being busy", f'{key}: "accounts"' in busy)
# The drift test warm.ts has always promised: every page resource is warmed.
used = set()
for f in src.rglob("*"):
    if f.suffix in (".svelte", ".ts") and f.name != "resource.ts":
        used |= set(re.findall(r'resource(?:<[^>]*>)?\(\s*"([^"]+)"', f.read_text(encoding="utf-8")))
check("every page resource is warmed at launch", used <= warmed, str(sorted(used - warmed)))
check("the moods are the configured ones, not a hard-coded list",
      "loadMoods" in page and "MOODS" not in page and "const MOODS" not in card)
check("the add/edit dialog is not a <form> (Button has no type, so Cancel would submit)",
      "</form>" not in page and not re.search(r"<form\s", page))
check("removal is in the menu, set apart", 'is-danger" role="menuitem" onclick={() => pick(ondelete)}' in card)
check("forgetting conversations takes two clicks", "confirmWipe" in card)
check("'Its chats' opens on that account",
      "chatsFocus.set(s.id)" in page and "get(chatsFocus)" in read("pages/Chats.svelte"))
check("'Its log' opens on that account",
      "logsFocus.set(s.id)" in page and "get(logsFocus)" in read("pages/Logs.svelte"))
check("there is always a way to add another", "add-tile" in page)
check("a first run gets a real start, not an empty list", "Connect your first account" in page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
