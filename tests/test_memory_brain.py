"""The Memory page's brain has a job.

It used to be a glowing brain with sparks rising off it on a loop, and
nothing else. Now it is what the bot learned last: beside it, who and what
("Learned 5m ago: Mara's city: Paris"), and a click on either opens that
person with that fact lit. The page asks again every few seconds, and each
time the bot writes something new down the brain sparks (only then), with a
sound, and counts the people learned about since. With nothing timed yet it
opens the person it knows the most about.

For that each fact now keeps when it was learned: a learned_at column, added
in place to a memory table from before (every fact there at 0), set when the
bot writes a new or changed value, kept when the value is the same, and left
alone when the value is written by hand on the Memory page.
"""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-brain-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from app.utils import db  # noqa: E402

print("== a memory table from before ==")
path = db.resource_path(db.db_path)
Path(path).parent.mkdir(parents=True, exist_ok=True)
c = sqlite3.connect(path)
c.execute("CREATE TABLE user_memory (persona TEXT NOT NULL DEFAULT 'default', user_id INTEGER, key TEXT, value TEXT,"
          " PRIMARY KEY (persona, user_id, key))")
c.execute("INSERT INTO user_memory VALUES ('default', 11, 'city', 'Paris')")
c.execute("INSERT INTO user_memory VALUES ('default', 22, 'job', 'barista')")
c.commit()
c.close()

from app.utils import memory  # noqa: E402


def times():
    return {(u, k): t for u, k, t in sqlite3.connect(path).execute("SELECT user_id, key, learned_at FROM user_memory")}


memory.get_memory(11, persona="default")
cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(user_memory)")]
check("it gets a learned_at column, added in place", "learned_at" in cols)
check("what was there is kept, its time unknown (0)", times()[(11, "city")] == 0 and memory.get_memory(11, persona="default") == {"city": "Paris"})

print("\n== when a fact was learned ==")
memory.set_memory(11, "pet", "a cat", persona="default")
t = times()[(11, "pet")]
check("the bot writing a new fact down: now", abs(t - time.time()) < 5)
time.sleep(0.02)
memory.set_memory(11, "pet", "a cat", persona="default")
check("the same value again: the time it had", times()[(11, "pet")] == t)
memory.set_memory(11, "pet", "two cats", persona="default")
t2 = times()[(11, "pet")]
check("a changed value: learned again, now", t2 > t)
memory.set_memory(11, "pet", "three cats", persona="default", learned=False)
check("written by hand: the value changes, the time it had stays",
      memory.get_memory(11, persona="default")["pet"] == "three cats" and times()[(11, "pet")] == t2)
memory.set_memory(22, "music", "lo-fi", persona="default", learned=False)
check("a new one by hand: no time", times()[(22, "music")] == 0)
memory.copy_persona_memory("default", "nova")
copied = {(u, k): t for p, u, k, t in sqlite3.connect(path).execute("SELECT persona, user_id, key, learned_at FROM user_memory")
          if p == "nova"}
check("a copied persona keeps when each was learned", copied.get((11, "pet")) == t2)

print("\n== the list says what it learned last ==")
db.init_db()   # the rest of the app's tables, as a real install has them
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import chat_routes  # noqa: E402

app = FastAPI()
app.include_router(chat_routes.router)
cl = TestClient(app)
memory.set_memory(22, "plans", "lake trip on Saturday", persona="default")
r = cl.get("/api/memory").json()
latest = r.get("latest") or {}
check("the newest learned fact, whose and when", latest.get("user_id") == "22" and latest.get("key") == "plans"
      and latest.get("value") == "lake trip on Saturday" and latest.get("at", 0) > 0, str(latest))
by = {u["user_id"]: u for u in r["users"]}
check("each person: when the bot last learned something about them, and what",
      by["11"]["learned"] == "pet" and by["11"]["learned_at"] == t2 and by["22"]["learned"] == "plans", str(by["11"]))
memory.set_memory(11, "__persona__", "be short", persona="default")
r2 = cl.get("/api/memory").json()
check("their own tone is not a fact it learned", (r2.get("latest") or {}).get("key") == "plans")
check("written by hand from the page, it is not learned", "set_memory(uid, key, str(value), persona=pid, learned=False)"
      in read("app/web/routes/chat_routes.py"))
fresh = sqlite3.connect(path)
fresh.execute("UPDATE user_memory SET learned_at = 0")
fresh.commit()
fresh.close()
check("with every time unknown there is no latest", cl.get("/api/memory").json().get("latest") is None)
check("and a table that could not take the column still lists and writes",
      "except sqlite3.OperationalError:\n            # A table with no learned_at" in read("app/web/routes/chat_routes.py")
      and "# A table without the column (it could not be added): written as before, with no time." in read("app/utils/memory.py"))
check("a fresh database has the column from the start", "learned_at REAL NOT NULL DEFAULT 0" in read("app/utils/db.py"))

print("\n== the brain on the page ==")
page = read("webui/src/pages/Memory.svelte")
check("the brain is a button that opens what it learned last",
      '<button type="button" class="mm-orb" class:is-learning={learning} use:chime={"land"} onclick={openBrain}' in page
      and "const uid = latest?.user_id ?? best?.user_id;" in page)
check("beside it, who and what, said plainly, the same click",
      "Learned {ago(latest.at)}: <b>{latest.name || \"someone\"}</b>'s {words(latest.key)}" in page
      and 'class="mm-last" onclick={openBrain}' in page)
check("a fact's name read as words", 'const words = (k: string) => k.replace(/_/g, " ");' in page)
check("nothing timed yet: who it knows the most about", "Knows the most about <b>{nameOf(best)}</b>" in page)
check("opened, the fact it learned is lit and brought into view",
      "class:is-flash={flashKey === key} data-fact={key}" in page and "@keyframes mm-flash" in page
      and 'document.querySelector(`[data-fact="${CSS.escape(key)}"]`)' in page)
check("asked again every few seconds while in view",
      "visiblePoll(() => people.refresh({ force: true, quiet: true }), 12_000)" in page)
check("it sparks only when it learns, heard as a glint and a chime",
      ".mm-orb.is-learning .mm-spark { animation: mm-spark 1.1s ease-out backwards; }" in page
      and "animation: mm-spark 2.8s ease-out infinite" not in page
      and 'play("glint", { strong: true });' in page and 'play("done", { delay: 240, level: 0.45 });' in page
      and "@keyframes mm-burst" in page and "@keyframes mm-learn" in page)
check("what it knew when the page opened is not news", "lastHeard = at;" in page and "if (at > lastHeard) {" in page)
check("it counts the people learned about since, until pressed",
      "users.filter((u) => (u.learned_at ?? 0) > sinceAt).length" in page and "+{newPeople}" in page
      and "if (latest) sinceAt = latest.at;" in page)
check("a fresh count each persona", "sinceAt = -1;" in page)
check("motion off: still", ':global(:root[data-motion="off"]) .mm-orb::after,' in page
      and ':global(:root[data-motion="off"]) .mm-fact.is-flash,' in page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
