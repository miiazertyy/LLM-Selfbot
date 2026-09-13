"""Exercises the util/engine layers against a throwaway DB + picture folder."""
import os, sys, shutil, tempfile, time, pathlib

REPO = str(pathlib.Path(__file__).resolve().parent.parent)
SANDBOX = tempfile.mkdtemp(prefix="llmbot_test_")
shutil.copytree(os.path.join(REPO, "resources"), os.path.join(SANDBOX, "config"),
                ignore=shutil.ignore_patterns("*.db", ".env", "pictures"))
os.makedirs(os.path.join(SANDBOX, "config", "pictures"), exist_ok=True)
sys.path.insert(0, REPO)

import app.utils.helpers as helpers
_real_rp = helpers.resource_path
helpers.resource_path = lambda rel: os.path.join(SANDBOX, rel)

import app.utils.db as db
import app.utils.memory as memory
import app.utils.pictures as pictures
db.resource_path = helpers.resource_path
pictures.resource_path = helpers.resource_path

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))

print("\n== db / memory ==")
db.init_db(); memory.init_memory()

db.record_user_message(111, "alice")
db.record_user_message(111, "alice")
db.record_user_message(222, "bob")
lb = db.get_leaderboard()
check("leaderboard all-time ordering", [r["user_id"] for r in lb] == [111, 222], str(lb))
check("leaderboard counts", lb[0]["message_count"] == 2 and lb[1]["message_count"] == 1)
lb_recent = db.get_leaderboard(since=time.time() - 60)
check("leaderboard time-filtered", len(lb_recent) == 2 and lb_recent[0]["message_count"] == 2)
check("leaderboard old window empty", db.get_leaderboard(since=time.time() + 60) == [])

db.record_user_message_snap("uuid-a", "snapper")
snap_lb = db.get_leaderboard_snap()
check("snap leaderboard", snap_lb and snap_lb[0]["user_id"] == "uuid-a")

memory.set_memory(111, "city", "Paris")
memory.set_memory(111, "pet_name", "Rex")
check("memory read back", memory.get_memory(111) == {"city": "Paris", "pet_name": "Rex"})
memory.delete_memory(111, "city")
check("memory delete", memory.get_memory(111) == {"pet_name": "Rex"})
memory.set_persona(111, "be formal")
check("persona set/get", memory.get_persona(111) == "be formal")
check("persona hidden from prompt", "__persona__" not in memory.format_memory_for_prompt(memory.get_memory(111)))
memory.clear_persona(111)
check("persona clear", memory.get_persona(111) is None)
memory.clear_memory(111)
check("memory clear", memory.get_memory(111) == {})

# Connections must not leak when a statement blows up mid-transaction.
before = None
try:
    with db._connect() as conn:
        conn.execute("SELECT * FROM does_not_exist")
except Exception:
    pass
check("failed query still leaves DB usable", db.get_leaderboard() != [])

db.add_ignored_user(999); db.add_ignored_user(999)
check("ignored users dedupe", db.get_ignored_users() == [999])
db.remove_ignored_user(999)
check("ignored users remove", db.get_ignored_users() == [])
db.add_ignored_user_snap("uuid-x")
check("snap ignore list", db.get_ignored_users_snap() == ["uuid-x"])
db.add_channel(5); db.add_channel(6)
check("channels", sorted(db.get_channels()) == [5, 6])

db.add_unresponded(111, 222, "hey", time.time() - 100)
check("pending nudge found", len(db.get_pending_nudges(50)) == 1)
check("pending nudge not yet due", db.get_pending_nudges(500) == [])
db.mark_nudge_sent(111, 222)
check("nudge marked sent", db.get_pending_nudges(50) == [])
db.mark_responded(111, 222)

print("\n== pictures ==")
pic_dir = os.path.join(SANDBOX, "config", "pictures")
for n in (1, 2, 3):
    open(os.path.join(pic_dir, f"IMG_{n}.jpg"), "wb").write(b"x")
open(os.path.join(pic_dir, "notes.txt"), "w").write("ignore me")
for n in (1, 2, 3):
    db.add_picture_description(f"IMG_{n}.jpg", f"description {n}")
check("bulk descriptions", db.get_all_picture_descriptions() ==
      {f"IMG_{n}.jpg": f"description {n}" for n in (1, 2, 3)})
pics = pictures.get_picturable()
check("picturable skips non-images", len(pics) == 3, str(pics))

# Never the same photo twice in a row, and all photos stay reachable.
seen, prev = set(), None
for _ in range(200):
    path, _desc = pictures.pick_picture("u1")
    check_repeat = path != prev
    if not check_repeat:
        break
    prev = path; seen.add(path)
check("no consecutive repeat over 200 picks", prev is not None and len(seen) == 3)

open(os.path.join(pic_dir, "IMG_4.jpg"), "wb").write(b"x")   # no description stored
check("undescribed picture excluded", len(pictures.get_picturable()) == 3)
db.delete_picture_db("IMG_1.jpg")
check("delete description", db.get_picture_description("IMG_1.jpg") is None)
db.rename_picture_db("IMG_2.jpg", "IMG_1.jpg")
check("rename description", db.get_picture_description("IMG_1.jpg") == "description 2")
db.clear_all_pictures_db()
check("clear all descriptions", db.get_all_picture_descriptions() == {})

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
