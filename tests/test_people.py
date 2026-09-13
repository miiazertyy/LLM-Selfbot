"""The profile card behind a clicked username.

Two names matter and they are not interchangeable. The heading is the display
name, which is what Discord shows in chat and what you recognise someone by.
The @handle is the account name, which is the one you type to add them as a
friend. Showing the handle in both places, which is what happened when the
cache was empty, makes the card useless for the one thing it is for.

The cache was empty for almost everyone because set_profile_details was called
inside the "first time we learn their name" branch: anyone already known kept a
blank card forever, avatar included. That write now happens on every message,
and the card additionally backfills the display name from the "name" fact the
bot has been recording since long before the profile cache existed.
"""
import asyncio
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


# ── A sandbox data dir, so the real database is never touched ────────────────
SANDBOX = Path(tempfile.mkdtemp(prefix="people_"))
(SANDBOX / "config").mkdir(parents=True)
shutil.copyfile(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX

import app.utils.helpers as helpers
_orig_resource_path = helpers.resource_path


def _sandboxed(rel: str) -> str:
    p = str(rel).replace("\\", "/")
    if p == "config" or p.startswith("config/"):
        return str(SANDBOX / rel)
    return _orig_resource_path(rel)


helpers.resource_path = _sandboxed
helpers.invalidate_config_cache()

from app.utils.db import init_db, set_profile_details, get_profile_details
from app.utils.memory import init_memory, set_memory

init_db()
init_memory()

import app.web.routes.people_routes as people
people.DB_PATH = SANDBOX / "config" / "bot_data.db"

ALICE = 910680732408627231      # known only through the older code paths
BOB = 1104899235901624392       # seen since the fix, so fully cached

AVATAR = "https://cdn.discordapp.com/avatars/1104899235901624392/abc123.png?size=1024"


def card(uid: int) -> dict:
    return asyncio.run(people.person(None, str(uid)))


# ── Someone the profile cache never captured ────────────────────────────────
print("== a person known only from memory ==")
conn = sqlite3.connect(people.DB_PATH)
with conn:
    conn.execute("INSERT OR REPLACE INTO user_stats (user_id, username, message_count, first_seen)"
                 " VALUES (?, ?, ?, ?)", (ALICE, "11.0.0.1_", 4, time.time() - 86400))
    for _ in range(4):
        conn.execute("INSERT INTO message_log (user_id, username, ts) VALUES (?, ?, ?)",
                     (ALICE, "11.0.0.1_", time.time() - 3600))
conn.close()
set_memory(ALICE, "name", "! Alex")

a = card(ALICE)
check("handle is the @name you would add", a.get("username") == "11.0.0.1_", str(a.get("username")))
check("heading falls back to the remembered display name",
      a.get("display_name") == "! Alex", str(a.get("display_name")))
check("heading and handle are not the same string",
      a.get("display_name") != a.get("username"))
check("the name fact is not repeated in the remembered list",
      "name" not in (a.get("facts") or {}), str(list((a.get("facts") or {}).keys())))
check("message counts still come through", a.get("messages") == 4, str(a.get("messages")))

# ── Someone captured properly, which is every person from now on ────────────
print("\n== a person the cache has seen since the fix ==")
set_profile_details(BOB, username=".malakals", display_name="malakals", avatar=AVATAR)

stored = get_profile_details(BOB)
check("avatar round trips through the database", stored.get("avatar") == AVATAR,
      str(stored.get("avatar")))

b = card(BOB)
check("card serves the avatar", b.get("avatar") == AVATAR, str(b.get("avatar")))
check("card serves the display name", b.get("display_name") == "malakals")
check("card serves the handle", b.get("username") == ".malakals")

# ── A later call must not wipe fields it does not carry ─────────────────────
print("\n== partial updates keep what is already known ==")
set_profile_details(BOB, bio="huge rpg nerd")
after = get_profile_details(BOB)
check("bio added", after.get("bio") == "huge rpg nerd")
check("avatar survived a bio-only write", after.get("avatar") == AVATAR, str(after.get("avatar")))
check("handle survived a bio-only write", after.get("username") == ".malakals")

# ── The card is a local record of real people, so it can be switched off ────
print("\n== the whole feature can be turned off ==")
import app.web.routes.people_routes as pr
_real_enabled = pr._enabled
pr._enabled = lambda: False
off = card(BOB)
check("disabled card returns nothing about anyone",
      off.get("enabled") is False and "username" not in off, str(off))
pr._enabled = _real_enabled

# The write must happen for everyone the bot sees, not only those it answers.
print("\n== the caching runs on every message, not only on replies ==")
src = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")

check("there is a helper that records an author", "def _cache_author(" in src)

# on_message runs for every message; generate_response_and_reply only runs for
# the ones the bot decides to answer. The bot sees far more people than it
# answers, and the ones it ignores are exactly the ones you want to look up.
handler = src.index("async def on_message(message):")
head = src[handler:handler + 1200]
check("on_message records the author", "_cache_author(message.author)" in head, head[:200])

# Someone already in the database predates the cache, so waiting for them to
# message again is not an answer: the panel can ask a running account directly.
check("the runner answers a profile lookup", 'elif cmd == "get_profile":' in src)
people_src = (ROOT / "app" / "web" / "routes" / "people_routes.py").read_text(encoding="utf-8")
check("the card asks for it when nothing is cached",
      "_fetch_profile" in people_src and "get_profile" in people_src)
check("a silent account is not asked again straight away", "_RETRY_AFTER" in people_src)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
