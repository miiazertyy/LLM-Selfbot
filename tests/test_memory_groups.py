"""One person, several accounts.

The same human writes to the bot from Discord and from Snapchat, and it knew them as two strangers: it learned
their dog's name twice, and what it was told on one never reached the other. Linking two accounts makes one person
of them. What is remembered is shared whichever one they write from, and unlinking one that was not them after all
gives each of them back exactly what it had, because nothing is merged on disk: each account's facts stay under its
own id and only the reading puts them together.

A link says who someone is, which does not change with who is talking to them, so it is not kept per persona. What
is remembered still is: two personas linking the same pair each know only what was said to them.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


SANDBOX = Path(tempfile.mkdtemp(prefix="memgroups_"))
(SANDBOX / "config").mkdir(parents=True, exist_ok=True)
os.environ["LLMSELFBOT_DATA_DIR"] = str(SANDBOX)

from app.utils import memory as M  # noqa: E402

M.init_memory()

print("== two accounts, one person ==")
M.set_memory("184512330201", "likes", "la randonnée")
M.set_memory("184512330201", "works at", "une boulangerie")
M.set_memory("snap_marcdlb", "dog", "Pablo")
check("before linking, each knows only its own",
      M.get_memory("184512330201") == {"likes": "la randonnée", "works at": "une boulangerie"}
      and M.get_memory("snap_marcdlb") == {"dog": "Pablo"})
group = M.link_people("184512330201", "snap_marcdlb")
check("linked, they are one person", sorted(group) == ["184512330201", "snap_marcdlb"])
both = {"likes": "la randonnée", "works at": "une boulangerie", "dog": "Pablo"}
check("and it remembers all of it, from either of them",
      M.get_memory("184512330201") == both and M.get_memory("snap_marcdlb") == both)
check("their own id comes first, so a write goes to the account being asked about",
      M.person_ids("snap_marcdlb")[0] == "snap_marcdlb")

print("\n== a third account joins them ==")
M.set_memory("tg_99120033", "city", "Lyon")
M.link_people("snap_marcdlb", "tg_99120033")
check("linking to any of them takes in all of them",
      sorted(M.person_ids("184512330201")) == ["184512330201", "snap_marcdlb", "tg_99120033"])
check("and what it knows is the three together", M.get_memory("tg_99120033") == {**both, "city": "Lyon"})
check("every id says who else it is", sorted(M.linked_people()["tg_99120033"]) == ["184512330201", "snap_marcdlb"])
try:
    M.link_people("tg_99120033", "tg_99120033")
    same_refused = False
except ValueError:
    same_refused = True
check("linking an account to itself is refused", same_refused)

print("\n== when two of them disagree ==")
# They told Snapchat something newer than what Discord was told.
M.set_memory("snap_marcdlb", "likes", "les sushis")
check("the newest thing it was told is the one it goes by", M.get_memory("184512330201")["likes"] == "les sushis")

print("\n== unlinking one that was not them ==")
M.unlink_person("tg_99120033")
check("it keeps what it was told itself", M.get_memory("tg_99120033") == {"city": "Lyon"})
check("and the others no longer know it", "city" not in M.get_memory("184512330201"))
check("the rest stay one person", sorted(M.person_ids("snap_marcdlb")) == ["184512330201", "snap_marcdlb"])
M.unlink_person("snap_marcdlb")
check("a pair with one taken out is nobody's group", M.linked_people() == {})
check("and each has exactly what it was told",
      M.get_memory("184512330201") == {"likes": "la randonnée", "works at": "une boulangerie"}
      and M.get_memory("snap_marcdlb") == {"dog": "Pablo", "likes": "les sushis"})

print("\n== one persona's memory, every persona's person ==")
M.link_people("184512330201", "snap_marcdlb")
M.set_memory("snap_marcdlb", "secret", "told to Rosa", persona="rosa")
check("what one persona was told stays its own",
      "secret" in M.get_memory("184512330201", persona="rosa")
      and "secret" not in M.get_memory("184512330201"))

print("\n== the panel's side ==")
src = (ROOT / "app" / "web" / "routes" / "chat_routes.py").read_text(encoding="utf-8")
check("linking and unlinking have their own routes",
      '@router.post("/api/memory/link")' in src and '@router.post("/api/memory/unlink")' in src)
check("every running account is told, whatever platform and whatever persona it speaks as",
      "_EVERY_PLATFORM = registry.IDS" in src and "persona=None, platforms=_EVERY_PLATFORM" in src
      and "telegram" in __import__("app.platforms.registry", fromlist=["IDS"]).IDS)
check("the list says who else each person is", 'e["same_as"] = linked.get(str(e["user_id"]), [])' in src)
check("and counts the whole person's facts, so the number matches the facts under it",
      'whole |= keys_of.get(other, set())' in src)
check("forgetting someone forgets them on every account they write from, or it would come straight back",
      "whole = person_ids(uid) or [uid]" in src and "for one in whole:" in src)
check("a fact edited by hand is not undone by an older copy under another of their accounts",
      "for other in (person_ids(uid) or [])[1:]:" in src)

page = (ROOT / "webui" / "src" / "pages" / "Memory.svelte").read_text(encoding="utf-8")
check("the page says who they also are, and can unlink one",
      'class="mm-same glass"' in page and "async function unlinkFrom" in page and "Same person" in page)
check("linking is a picker of the others, searchable",
      "async function linkTo" in page and "const canLink = $derived.by" in page
      and '<div class="mm-link-pop unroll" data-link-picker' in page)
check("it says plainly what linking does",
      "It knows these are one person: what any of them says, it remembers about all of them." in page)
check("an account already linked is not offered again",
      "const taken = new Set([current.user_id, ...(current.same_as ?? [])]);" in page)
check("and the totals count a linked person once, not once per account",
      "const onePer = $derived.by" in page and "people: onePer.length," in page)
api = (ROOT / "webui" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
check("the panel has both calls", "memoryLink:" in api and "memoryUnlink:" in api)

import shutil  # noqa: E402

shutil.rmtree(SANDBOX, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
