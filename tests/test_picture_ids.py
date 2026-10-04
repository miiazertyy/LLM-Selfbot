"""Deleting a picture deletes that picture.

Deleting renumbers the rest (IMG_3 becomes IMG_2), and the page went by name:
it kept showing the old image under each name, so the card you saw as IMG_2
could be the file now called IMG_3, and Delete took the wrong one. Pictures
now have an id of their own that renaming does not change: the page shows,
keys and deletes by it. And deleting is quiet: the picture goes at once with
an undo, and from the disk when the undo runs out, instead of a box asking
first.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-pics-"))
(TMP / "config" / "pictures").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== the server ==")
pics = TMP / "config" / "pictures"
for i, colour in enumerate(["red", "green", "blue", "gold"], start=1):
    (pics / f"IMG_{i}.png").write_bytes(f"picture-{colour}".encode() * (i + 3))
    time.sleep(0.02)
from app.utils.db import init_db  # noqa: E402
init_db()
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import media_routes  # noqa: E402

app = FastAPI()
app.include_router(media_routes.router)
c = TestClient(app)
listed = c.get("/api/pictures").json()["pictures"]
ids = {p["name"]: p["id"] for p in listed}
check("each picture comes with an id", all(ids.values()) and len(set(ids.values())) == 4)
blue, gold = ids["IMG_3.png"], ids["IMG_4.png"]
r = c.get(f"/api/pictures/id/{blue}")
check("a picture is served by its id, kept for good", r.content.startswith(b"picture-blue")
      and "immutable" in r.headers.get("cache-control", ""))
check("by name it is always asked again", "no-cache" in c.get("/api/pictures/IMG_1.png").headers.get("cache-control", ""))
c.delete(f"/api/pictures/IMG_2.png?id={ids['IMG_2.png']}")
check("deleting renumbers the rest", sorted(os.listdir(pics)) == ["IMG_1.png", "IMG_2.png", "IMG_3.png"])
check("and a picture's id still finds it under its new name", c.get(f"/api/pictures/id/{blue}").content.startswith(b"picture-blue"))
r = c.delete(f"/api/pictures/IMG_4.png?id={gold}").json()
left = sorted((pics / f).read_bytes()[:11] for f in os.listdir(pics))
check("a delete by an old name and the id removes the picture that was seen, not what the name is now",
      r.get("deleted") == "IMG_3.png" and left == [b"picture-blu", b"picture-red"], str((r, left)))
check("an old name alone finds nothing, rather than another picture", c.delete("/api/pictures/IMG_4.png").status_code == 404)
listed = c.get("/api/pictures").json()["pictures"]
r = c.post("/api/pictures/delete", json={"items": [{"name": "IMG_7.png", "id": listed[0]["id"]}]}).json()
check("several at once by id too", r["deleted"] == 1 and os.listdir(pics) == ["IMG_1.png"]
      and (pics / "IMG_1.png").read_bytes().startswith(b"picture-blue"))
check("and by name still, for the bot's own commands", c.post("/api/pictures/delete", json={"names": ["nope.png"]}).json()["missing"] == ["nope.png"])
check("an id that is not one is refused", c.get("/api/pictures/id/..%2Fconfig").status_code == 404)

print("\n== the page ==")
page = read("pages/Pictures.svelte")
api = read("lib/api.ts")
check("pictures are shown by id", "api.pictureUrl(p.name, p.id, who)" in page
      and "id ? `/api/pictures/id/${encodeURIComponent(id)}`" in api)
check("the cards are keyed by id, so a renumber never gives a card another picture's image",
      "{#each shownPics as p (keyOf(p))}" in page and "const keyOf = (p: Pic) => p.id || p.name;" in page)
check("deletes, descriptions and describing again name the id", "api.deletePictures(batch.map((p) => ({ name: p.name, id: p.id })), owner)" in page
      and "api.setPictureDesc(editing.name, editDesc, editing.id, who)" in page and "api.analysePicture(p.name, p.id, who)" in page)
check("the selection is by id", "selected.has(keyOf(p))" in page)
check("no box asks first any more", 'title="Delete this picture?"' not in page and "confirmingBulk" not in page)
check("the picture goes at once, with an undo, and from the disk when that runs out", "function removeLater(" in page
      and "commitTimer = window.setTimeout(commit, UNDO_MS);" in page and "<UndoBar " in page)
check("leaving the page is the undo running out", "onDestroy(() => {\n    if (leaving.length) commit();" in page)
check("once it is being deleted, it cannot be brought back half way", "going = [...going, ...batch];" in page
      and "leaving = [];\n    going" in page)
check("it shrinks away and the others close up", "animate:flip" in page and "out:scale" in page)
check("Big Picture and search show pictures by id too (a video by its still)",
      'api.pictureThumb({ name: String(p.name), id: String(p.id ?? ""), video: !!p.video }' in read("lib/bigpicture/BigPicture.svelte")
      and 'api.pictureThumb({ name: String(p.name), id: String(p.id ?? ""), video: !!p.video })' in read("lib/search.ts")
      and "scoped(p.id ? `/api/pictures/id/${encodeURIComponent(p.id)}`" in read("lib/api.ts"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
