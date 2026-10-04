"""Small copies of pictures, for tiles and cards.

The face panel's tiles were the full photos, each decoded at full size and
blurred for a 58px square, and the grid had a fade mask on it: scrolling it
stuttered (measured in headless Chrome with 36 phone-sized photos: frames of
38 to 52ms on average and stalls up to 380ms, against 9 to 10ms and none over
25ms now). Each picture now has small copies, made once and kept by its id
(which never comes to mean another picture), and the scroller has no mask, and
holds off its tiles' hover zoom while it moves.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-thumbs-"))
(TMP / "config" / "pictures").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from PIL import Image  # noqa: E402

pics = TMP / "config" / "pictures"
Image.new("RGB", (3000, 4000), (200, 120, 90)).save(pics / "IMG_1.jpg", "JPEG", quality=90)
Image.new("RGB", (1600, 900), (40, 90, 160)).save(pics / "IMG_2.png", "PNG")

from app.utils.db import init_db  # noqa: E402
init_db()
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import media_routes  # noqa: E402

app = FastAPI()
app.include_router(media_routes.router)
c = TestClient(app)
ids = {p["name"]: p["id"] for p in c.get("/api/pictures").json()["pictures"]}

print("== the route ==")
r = c.get(f"/api/pictures/id/{ids['IMG_1.jpg']}/thumb?w=160")
im = Image.open(io.BytesIO(r.content))
check("a small JPEG, its shorter side the width asked for", r.status_code == 200 and im.format == "JPEG" and min(im.size) == 160
      and im.size == (160, 213), str(im.size))
check("far smaller than the picture", len(r.content) < (pics / "IMG_1.jpg").stat().st_size / 10)
check("kept for good, by the id", "immutable" in r.headers.get("cache-control", "")
      and (media_routes.THUMBS_DIR / f"{ids['IMG_1.jpg']}_160.jpg").is_file())
r = c.get(f"/api/pictures/id/{ids['IMG_2.png']}/thumb?w=200")
im = Image.open(io.BytesIO(r.content))
check("a width between sizes is the next size up, and a wide one is cut by its height", min(im.size) == 240 and im.size[0] > im.size[1],
      str(im.size))
check("one already small is not made bigger",
      min(Image.open(io.BytesIO(c.get(f"/api/pictures/id/{ids['IMG_2.png']}/thumb?w=5000").content)).size) == 640)
check("an id that is not one is refused", c.get("/api/pictures/id/..%2Fx/thumb").status_code == 404
      and c.get("/api/pictures/id/abcdef123456/thumb").status_code == 404)
c.delete(f"/api/pictures/IMG_1.jpg?id={ids['IMG_1.jpg']}")
check("deleting a picture takes its small copies too", not list(media_routes.THUMBS_DIR.glob(f"{ids['IMG_1.jpg']}_*.jpg")))

print("\n== the pages ==")
api = read("webui/src/lib/api.ts")
fp = read("webui/src/lib/personas/FacePicker.svelte")
page = read("webui/src/pages/Pictures.svelte")
check("the address of a small copy", "pictureSmall: (p: { name: string; id?: string; video?: boolean }, w = 160, persona = \"\")" in api
      and "/thumb?w=${w}" in api)
check("the face panel's tiles are small copies, decoded off the main thread",
      '<img src={api.pictureSmall(pic, 160, asked(p))} alt="" loading="lazy" decoding="async" />' in fp)
check("its scroller has no mask, and keeps its scroll to itself", "mask-image" not in fp and "overscroll-behavior: contain;" in fp)
check("while it scrolls, the tiles under the pointer do not zoom or unblur one after another",
      ".fp-grid.is-scrolling .fp-tile { pointer-events: none; }" in fp and "onscroll={onGridScroll}" in fp)
check("the Pictures page's cards are small copies too; opened, the picture itself",
      "const thumbOf = (p: Pic) => api.pictureSmall(p, 480, who);" in page
      and "src={(x) => api.pictureUrl(x.name, x.id, who)}" in page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
