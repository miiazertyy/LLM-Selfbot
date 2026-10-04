"""Pictures, memory and summaries, each persona's own: the database change that makes it so.

The persona joins the key of three tables (pictures, user_memory, user_summaries). SQLite cannot change a primary
key, so an old table is rebuilt once, everything in it given to Default, inside one write transaction, after a copy
of the whole database is taken. This runs on someone's real memory, so it is checked here on an old-shape database
built the way an install from before personas has it: migrated twice (the second time does nothing), with another
connection reading the whole time, and nothing lost.
"""
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.utils import db, memory  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


TMP = Path(tempfile.mkdtemp(prefix="persona-db-"))
(TMP / "config").mkdir()
db.resource_path = lambda rel: str(TMP / rel)
DB = TMP / "config" / "bot_data.db"

print("== an install from before personas ==")
old = sqlite3.connect(DB)
old.executescript("""
    CREATE TABLE pictures (filename TEXT PRIMARY KEY, description TEXT NOT NULL DEFAULT '',
                           look TEXT NOT NULL DEFAULT '', strength REAL NOT NULL DEFAULT 0,
                           original TEXT NOT NULL DEFAULT '');
    CREATE TABLE user_memory (user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (user_id, key));
    CREATE TABLE user_summaries (user_key TEXT PRIMARY KEY, summary TEXT NOT NULL, generated_at REAL NOT NULL,
                                 message_count INTEGER NOT NULL DEFAULT 0, settings_sig TEXT NOT NULL DEFAULT '',
                                 source TEXT NOT NULL DEFAULT '');
    INSERT INTO pictures (filename, description, look, strength, original)
        VALUES ('IMG_1.jpg', 'a selfie by the lake', 'warm', 0.7, 'abc.jpg'), ('IMG_2.png', 'at a cafe', '', 0, '');
    INSERT INTO user_memory VALUES (272402839874174976, 'name', 'Mara'), (272402839874174976, 'city', 'Porto'),
                                   (111, '__persona__', 'be formal');
    INSERT INTO user_summaries (user_key, summary, generated_at, message_count) VALUES ('272402839874174976', 'lake trip', 1.0, 60);
""")
old.commit()
old.close()

# A reader that holds the database open the whole time, as a running account does.
reads, stop, ready = [], threading.Event(), threading.Event()


def keep_reading():
    reader = sqlite3.connect(DB, timeout=30)
    reader.execute("PRAGMA journal_mode=WAL")
    reader.execute("PRAGMA busy_timeout=30000")
    ready.set()
    while not stop.is_set():
        try:
            reads.append(reader.execute("SELECT COUNT(*) FROM user_memory").fetchone()[0])
        except sqlite3.Error as e:
            reads.append(str(e))
        time.sleep(0.005)
    reader.close()


t = threading.Thread(target=keep_reading, daemon=True)
t.start()
ready.wait(5)
time.sleep(0.05)
ok = db.migrate_personas()
time.sleep(0.05)
stop.set()
t.join()

conn = sqlite3.connect(DB)
cols = {table: [r[1] for r in conn.execute(f"PRAGMA table_info({table})")] for table in ("pictures", "user_memory", "user_summaries")}
check("each of the three tables has a persona now", ok and all("persona" in c for c in cols.values()), str(cols))
pk = {table: [r[1] for r in sorted(conn.execute(f"PRAGMA table_info({table})"), key=lambda r: r[5]) if r[5]]
      for table in cols}
check("and it is part of each key", pk == {"pictures": ["persona", "filename"], "user_memory": ["persona", "user_id", "key"],
                                          "user_summaries": ["persona", "user_key"]}, str(pk))
rows = conn.execute("SELECT persona, filename, description, look, strength, original FROM pictures ORDER BY filename").fetchall()
check("every picture is Default's, its description and its look kept",
      rows == [("default", "IMG_1.jpg", "a selfie by the lake", "warm", 0.7, "abc.jpg"), ("default", "IMG_2.png", "at a cafe", "", 0.0, "")],
      str(rows))
mem = conn.execute("SELECT persona, user_id, key, value FROM user_memory ORDER BY user_id, key").fetchall()
check("every memory is Default's, a big Discord id kept to the last digit",
      mem == [("default", 111, "__persona__", "be formal"), ("default", 272402839874174976, "city", "Porto"),
              ("default", 272402839874174976, "name", "Mara")], str(mem))
summ = conn.execute("SELECT persona, user_key, summary, recent FROM user_summaries").fetchall()
check("a summary from before the recent lines were kept comes over, the column it lacked filled",
      summ == [("default", "272402839874174976", "lake trip", "")], str(summ))
conn.close()
snaps = list((TMP / "backups").glob("bot_data-before-personas-*.db"))
check("a copy of the whole database was taken first", len(snaps) == 1)
snap = sqlite3.connect(snaps[0])
check("and it is the old one, whole", snap.execute("SELECT COUNT(*) FROM user_memory").fetchone()[0] == 3
      and "persona" not in [r[1] for r in snap.execute("PRAGMA table_info(user_memory)")])
snap.close()
check("a running account reading all along was never turned away", reads and all(isinstance(r, int) for r in reads),
      str([r for r in reads if not isinstance(r, int)][:2]))

print("\n== done once ==")
check("a second time does nothing, and takes no second copy", db.migrate_personas()
      and len(list((TMP / "backups").glob("bot_data-before-personas-*.db"))) == 1)
db._persona_schema_ok = False
db.init_db()
check("starting the app on it is the same: tables made where missing, nothing touched",
      memory.get_memory(272402839874174976) == {"name": "Mara", "city": "Porto"})

print("\n== two personas, the same names ==")
db.add_picture_description("IMG_1.jpg", "on a bike", persona="juniper")
db.set_picture_look("IMG_1.jpg", "film", 0.5, "def.jpg", persona="juniper")
check("the same IMG_1 is two personas' pictures", db.get_all_picture_descriptions() == {"IMG_1.jpg": "a selfie by the lake", "IMG_2.png": "at a cafe"}
      and db.get_all_picture_descriptions("juniper") == {"IMG_1.jpg": "on a bike"})
db.delete_picture_db("IMG_1.jpg", persona="juniper")
check("removing one leaves the other's", db.get_picture_description("IMG_1.jpg") == "a selfie by the lake"
      and db.get_picture_description("IMG_1.jpg", persona="juniper") is None)
check("the originals swept against are everyone's", db.all_picture_originals() == {"abc.jpg"})
memory.set_memory(272402839874174976, "name", "M", persona="juniper")
check("the same person, remembered apart", memory.get_memory(272402839874174976) == {"name": "Mara", "city": "Porto"}
      and memory.get_memory(272402839874174976, persona="juniper") == {"name": "M"})
check("an id that comes as text still finds the number", memory.get_memory("272402839874174976") == {"name": "Mara", "city": "Porto"})
check("a person's own tone is per persona too", memory.get_persona(111) == "be formal" and memory.get_persona(111, persona="juniper") is None)
db.set_summary("272402839874174976", "bike ride", 10, "sig", persona="juniper")
check("summaries apart, and the newest of anyone's when no persona is named",
      db.get_summary("272402839874174976")["summary"] == "lake trip"
      and db.get_summary("272402839874174976", persona="juniper")["summary"] == "bike ride"
      and db.get_latest_summary("272402839874174976")["summary"] == "bike ride")
memory.copy_persona_memory("default", "nova")
db.copy_persona_pictures("default", "nova")
db.copy_persona_summaries("default", "nova")
check("a copy made with its memory knows what the other knew", memory.get_memory(272402839874174976, persona="nova")
      == {"name": "Mara", "city": "Porto"} and db.get_all_picture_descriptions("nova") == {"IMG_1.jpg": "a selfie by the lake", "IMG_2.png": "at a cafe"})
check("people counted per persona, a person's own tone not counted as a fact", db.persona_people("default") == 1
      and db.persona_people("juniper") == 1)
db.delete_persona_rows("juniper")
check("a deleted persona's rows go, and only its", memory.get_memory(272402839874174976, persona="juniper") == {}
      and db.get_summary("272402839874174976", persona="juniper") is None
      and memory.get_memory(272402839874174976) == {"name": "Mara", "city": "Porto"})

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
