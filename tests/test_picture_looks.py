"""Looks on the pictures, and what the AI adds to one as it sends it.

  * a look (warm, film, black and white...) changes a picture and keeps its size, its format and its transparency;
    nothing at strength 0; a moving picture is left alone
  * the original is kept, so a look can be changed or taken off; the look follows the picture through renumbering and
    a new description; originals nobody uses any more are swept
  * new pictures get the look Settings asks for: one, one at random, or the AI's pick
  * previews of every look, small and quick, drawn from the original
  * touches: a caption bar, big text, the time and the day on the persona's clock, Apple's emoji (fetched once each,
    Windows' own when they cannot be had); nothing drawn over anything else; a sample of every kind; what the AI asks
    for is kept to what is allowed and what can be drawn; any trouble sends the picture as it is
  * only on the accounts picked in Settings, and as often as it says
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-looks-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
CFG = yaml.safe_load((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"))
(TMP / "config" / "config.yaml").write_text(yaml.safe_dump(CFG, allow_unicode=True), encoding="utf-8")
(TMP / "config" / "instructions.txt").write_text("You are Lou, 22, casual.", encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
for k in ("GROQ_API_KEY", "GROQ_API_KEY_1"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def src(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def set_cfg(**pictures):
    cfg = yaml.safe_load((TMP / "config" / "config.yaml").read_text(encoding="utf-8"))
    for key, value in pictures.items():
        cfg["bot"]["pictures"][key] = value
    (TMP / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    import app.utils.helpers as helpers
    helpers._config_cache["data"] = None


def photo(w=360, h=640, fmt="JPEG", alpha=False) -> bytes:
    """A made-up photo: sky, sun, hills, a figure. Nothing real."""
    img = Image.new("RGBA" if alpha else "RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(90 + 120 * t), int(150 + 60 * (1 - t)), int(230 - 120 * t), 255 if not alpha else 200))
    d.ellipse((w * 0.6, h * 0.12, w * 0.85, h * 0.26), fill=(255, 214, 120, 255))
    d.polygon([(0, h * 0.73), (w * 0.33, h * 0.58), (w * 0.66, h * 0.72), (w, h * 0.62), (w, h), (0, h)], fill=(60, 140, 80, 255))
    d.rectangle((w * 0.35, h * 0.6, w * 0.65, h * 0.94), fill=(200, 60, 90, 255))
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def moving_gif() -> bytes:
    frames = [Image.new("RGB", (64, 64), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return out.getvalue()


print("== the looks ==")
from app.utils import looks  # noqa: E402

# Apple's emoji, never from the network here: a made-up image for the ones listed, "not there" for the rest, and
# "unreachable" while OFFLINE is set. MARK is a colour only these images have.
MARK = (255, 0, 200)
AVAILABLE = {"1f60d", "1f525", "2728", "2764-fe0f", "1f485", "1f697", "1f4a8", "2600-fe0f", "1f618", "1f48d", "1f5a4"}
OFFLINE = [False]
fetched = []


def fake_apple(name):
    fetched.append(name)
    if OFFLINE[0]:
        return 0, b""
    if name not in AVAILABLE:
        return 404, b""
    tile = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    for r in range(80, 0, -2):
        d.ellipse((80 - r, 80 - r, 80 + r, 80 + r), fill=(255 - r, 120 + r, r * 3 % 256, 255))
    d.rectangle((40, 40, 120, 120), fill=MARK + (255,))
    out = io.BytesIO()
    tile.save(out, "PNG")
    return 200, out.getvalue()

looks._fetch_apple = fake_apple

base = Image.open(io.BytesIO(photo())).convert("RGB")
changed_all = True
for lid in looks.LOOKS:
    out = looks.apply_look(base, lid, 0.85)
    if out.size != base.size or list(out.getdata())[:2000:97] == list(base.getdata())[:2000:97]:
        changed_all = False
        print("    look did nothing or changed size:", lid)
check(f"all {len(looks.LOOKS)} looks change the picture and keep its size", changed_all and len(looks.LOOKS) >= 10)
check("at strength 0, nothing", looks.apply_look(base, "film", 0) is base)
check("an unknown look is nothing", looks.apply_look(base, "nope", 1) is base)
half = looks.apply_look(base, "mono", 0.5).getpixel((180, 600))
full = looks.apply_look(base, "mono", 1).getpixel((180, 600))
orig = base.getpixel((180, 600))
check("half strength is between the picture and the full look",
      all(min(a, c) - 2 <= b <= max(a, c) + 2 for a, b, c in zip(orig, half, full)), f"{orig} {half} {full}")
blob, ext = looks.render(photo(), ".jpg", "warm", 0.7)
check("a JPEG stays a JPEG", ext == ".jpg" and blob[:2] == b"\xff\xd8")
blob, ext = looks.render(photo(fmt="PNG", alpha=True), ".png", "cool", 0.7)
check("a see-through PNG stays a PNG, and see-through", ext == ".png" and Image.open(io.BytesIO(blob)).mode == "RGBA"
      and Image.open(io.BytesIO(blob)).getchannel("A").getextrema()[0] < 255)
try:
    looks.render(moving_gif(), ".gif", "warm", 1)
    check("a moving picture is left alone", False)
except looks.Animated:
    check("a moving picture is left alone", True)
p1 = looks.preview(photo(), "k1", "film", 0.85, 120)
check("a preview: a small JPEG", p1[:2] == b"\xff\xd8" and Image.open(io.BytesIO(p1)).width <= 120)
check("asked again, the same one, not drawn again", looks.preview(photo(), "k1", "film", 0.85, 120) is p1)
t0 = time.time()
for lid in looks.LOOKS:
    looks.preview(photo(), "k2", lid, 0.85, 132)
check("every look's preview of one picture, quickly", time.time() - t0 < 3, f"{time.time() - t0:.2f}s")

print("\n== touches ==")
img = Image.open(io.BytesIO(photo())).convert("RGB")
when = datetime(2026, 10, 2, 22, 42)
check("the time as the sticker shows it", looks.clock_text(when, "en") == "10:42" and looks.clock_text(when, "fr") == "22:42")
check("the day, in their language", looks.day_text(when, "en") == "Friday" and looks.day_text(when, "fr") == "Vendredi")
bar = looks.draw_touch(img, {"caption": "bored af ngl", "caption_pos": "middle"}, "en", when)
y = int(img.height * looks.CAPTION_POS["middle"])
check("a caption bar across the picture, darker under it", bar.size == img.size
      and sum(bar.getpixel((5, y))[:3]) < sum(img.getpixel((5, y))[:3]) - 60)
big = looks.draw_touch(img, {"big_text": "guess where", "big_text_pos": "top"}, "en", when)
check("big text drawn at the top", big.crop((0, 0, img.width, int(img.height * 0.25))).convert("RGB").getcolors(100000)
      != img.crop((0, 0, img.width, int(img.height * 0.25))).getcolors(100000))
clock = looks.draw_touch(img, {"time": True, "day": True, "sticker_pos": "top-left"}, "en", when)
corner = clock.crop((0, 0, img.width // 2, img.height // 4)).convert("RGB")
whites = sum(1 for px in corner.getdata() if min(px) > 235)
check("the time and the day, white, in their corner", whites > 300, str(whites))
em = looks.draw_touch(img, {"emoji": ["😍"], "emoji_pos": "bottom-right"}, "en", when)
if looks._font("emoji", 40) is not None:
    region = em.crop((img.width // 2, img.height * 3 // 4, img.width, img.height)).convert("RGB")
    before = img.crop((img.width // 2, img.height * 3 // 4, img.width, img.height))
    check("a colour emoji, drawn in colour", len(set(region.getdata())) > len(set(before.getdata())) + 40)
else:
    check("a colour emoji, drawn in colour (no emoji font here: left out)", em.size == img.size)
mixed = looks.draw_touch(img, {"caption": "on my way 🚗💨", "caption_pos": "lower"}, "en", when)
check("words and emoji on one line", mixed.size == img.size)
blob, ext = looks.render_touch(photo(), {"caption": "hi", "time": True, "sticker_pos": "top-right"}, "en")
check("a touched picture is a JPEG to send", ext == ".jpg" and blob[:2] == b"\xff\xd8")

print("\n== Apple's emoji ==")
check("a line in pieces: a skin tone, a joined emoji and a flag each stay whole",
      looks._pieces("hi 👋🏽 ok ❤️\u200d🔥 🇫🇷 !") == [(False, "hi "), (True, "👋🏽"), (False, " ok "), (True, "❤️\u200d🔥"),
                                                   (False, " "), (True, "🇫🇷"), (False, " !")],
      str(looks._pieces("hi 👋🏽 ok ❤️\u200d🔥 🇫🇷 !")))
looks._apple_images.clear()
looks._tiles.clear()
for f in looks._apple_dir().glob("*.png"):
    f.unlink()
fetched.clear()
a1 = looks.apple_emoji("😘")
check("Apple's image of an emoji, fetched once and kept", a1 is not None and a1.size == (160, 160)
      and (looks._apple_dir() / "1f618.png").is_file() and fetched == ["1f618"], str(fetched))
looks._apple_images.clear()
check("after that read from what was kept, not fetched again", looks.apple_emoji("😘") is not None and fetched == ["1f618"])
fetched.clear()
check("a heart written plainly is found under its emoji name", looks.apple_emoji("❤") is not None
      and fetched == ["2764", "2764-fe0f"], str(fetched))
OFFLINE[0] = True
check("offline: drawn another way, and nothing given up on", looks.apple_emoji("🌙") is None
      and "1f319" not in looks._apple_missing)
OFFLINE[0] = False
AVAILABLE.add("1f319")
check("and Apple's once it can be reached again", looks.apple_emoji("🌙") is not None)
fetched.clear()
looks.apple_emoji("🫨")
check("one Apple's set does not have: asked once, then left to Windows' own", looks.apple_emoji("🫨") is None
      and fetched == ["1fae8", "1fae8-fe0f"], str(fetched))
cap = looks.draw_touch(img, {"caption": "hi 😘", "caption_pos": "middle"}, "en", when)
band = cap.crop((0, int(img.height * 0.5), img.width, int(img.height * 0.6))).convert("RGB")
check("an emoji in a caption is Apple's", any(px == MARK for px in band.getdata()))
stick = looks.draw_touch(img, {"emoji": ["🔥"], "emoji_pos": "bottom-right"}, "en", when).convert("RGB")
marks = sum(1 for px in stick.crop((img.width // 2, img.height * 3 // 4, img.width, img.height)).getdata() if px == MARK)
check("an emoji sticker is Apple's", marks > 50, str(marks))

print("\n== where each thing goes ==")
arr = looks._arrange({"big_text": "hey", "big_text_pos": "top", "time": True, "sticker_pos": "top-left",
                      "emoji": ["😍"], "emoji_pos": "bottom-left"})
check("the time moves down from under big text, on its own side", arr["sticker_pos"] == "bottom-left", str(arr))
check("the emoji go to a corner of their own", arr["emoji_pos"] == "bottom-right", str(arr))
check("a caption moves off big text's band", looks._arrange({"big_text": "hey", "big_text_pos": "bottom", "caption": "x",
                                                            "caption_pos": "lower"})["caption_pos"] == "upper")
check("nothing in the way: everything stays put", looks._arrange({"time": True, "sticker_pos": "top-right", "emoji": ["😍"],
                                                                  "emoji_pos": "bottom-left"})
      == {"time": True, "sticker_pos": "top-right", "emoji": ["😍"], "emoji_pos": "bottom-left"})
sample = looks.sample_touch(list(looks.TOUCH_KINDS), "en")
check("a sample of every kind", all(k in sample for k in ("caption", "big_text", "time", "day", "emoji", "look")))
check("and only of what is allowed", set(looks.sample_touch(["time", "day"], "en")) == {"time", "day", "sticker_pos"})
drawn = looks.draw_touch(img, sample, "en", when).convert("RGB")
low = drawn.crop((0, int(img.height * 0.78), img.width, img.height))
check("all of it drawn, the time among it", drawn.size == img.size and sum(1 for px in low.getdata() if min(px) > 235) > 150)

print("\n== what the AI asks for ==")
everything = list(looks.TOUCH_KINDS)
spec = looks.clean_touch({"caption": "x" * 30 + " " + "y" * 50, "big_text": "no", "time": True, "day": "yes",
                          "emoji": ["😍", "abc", "🔥🔥"], "look": "Golden hour", "sticker_pos": "middle"}, ["caption", "time", "emoji", "look"])
check("only what is allowed", "big_text" not in spec and "day" not in spec)
check("words cut short, between words", spec.get("caption") == "x" * 30, spec.get("caption", ""))
check("emoji only emoji", spec.get("emoji") == ["😍", "🔥🔥"], str(spec.get("emoji")))
check("a look by its name", spec.get("look") == "golden")
check("a corner that is not one becomes one", spec.get("sticker_pos") in looks.CORNERS and spec.get("emoji_pos") in looks.CORNERS
      and spec["emoji_pos"] != spec["sticker_pos"])
spec = looks.clean_touch({"caption": "see https://x.com/a @someone ok"}, ["caption"])
check("no links and no @names", spec.get("caption") == "see ok", str(spec))
check("nothing asked, nothing", looks.clean_touch({}, everything) == {} and looks.clean_touch("x", everything) == {})
check("a reply in a code block is still read", looks._json_object('```json\n{"time": true}\n```') == {"time": True}
      and looks._json_object("no json here") == {})
answers = []


async def fake_small(system, prompt, max_tokens):
    answers.append(prompt)
    return '{"caption": "outside rn", "caption_pos": "lower", "time": true, "look": "warm", "emoji": ["☀️"]}'

looks._small = fake_small
spec = asyncio.run(looks.plan_touch("a selfie outside", ["them: send a pic"], "here u go", "en", ["caption", "time"], "Max", "Snapchat"))
check("the AI's choice, kept to what it may use", spec == {"caption": "outside rn", "caption_pos": "lower", "time": True,
                                                         "sticker_pos": "top-right"}, str(spec))
check("it is told the photo, the chat, its message and what it may use", "a selfie outside" in answers[-1]
      and "them: send a pic" in answers[-1] and "here u go" in answers[-1] and '"caption"' in answers[-1]
      and '"emoji"' not in answers[-1] and "Lou" in answers[-1])
check("and that people usually add one thing, often nothing", "usually add one thing" in answers[-1])


async def broken_small(system, prompt, max_tokens):
    raise RuntimeError("no model")

looks._small = broken_small
check("the AI unreachable: nothing added", asyncio.run(looks.plan_touch("x", [], "", "en", everything)) == {})
try:
    asyncio.run(looks.plan_touch("x", [], "", "en", everything, strict=True))
    check("and a preview is told why", False)
except RuntimeError:
    check("and a preview is told why", True)
looks._small = fake_small
check("nothing allowed: not even asked", asyncio.run(looks.plan_touch("x", [], "", "en", [])) == {})

print("\n== at send time ==")
pic_dir = TMP / "config" / "pictures"
pic_dir.mkdir(parents=True, exist_ok=True)
(pic_dir / "IMG_9.jpg").write_bytes(photo())
path = str(pic_dir / "IMG_9.jpg")
set_cfg(touches={"accounts": ["snapchat_1"], "chance": 1.0, "kinds": everything})
got = asyncio.run(looks.touched_copy(path, "a selfie", [], "", "discord_1", "en"))
check("an account not picked sends it as it is", got == path)
got = asyncio.run(looks.touched_copy(path, "a selfie", [], "", "snapchat_1", "en"))
check("a picked one sends a copy with the touches", got != path and os.path.isfile(got) and "touched" in got
      and Image.open(got).size == Image.open(path).size)
got2 = asyncio.run(looks.touched_copy(path, "a selfie", [], "", "snapchat_1", "en", keep_name=True))
check("where the name shows, the copy has the picture's own name", os.path.basename(got2).startswith("IMG_9."))
looks.drop_copy(path, got2)
check("and is gone once sent", not os.path.exists(got2) and os.path.exists(path))
set_cfg(touches={"accounts": ["snapchat_1"], "chance": 0.0, "kinds": everything})
check("how often: never, never", asyncio.run(looks.touched_copy(path, "a selfie", [], "", "snapchat_1", "en")) == path)
set_cfg(touches={"accounts": ["snapchat_1"], "chance": 1.0, "kinds": everything})
looks._small = broken_small
check("the AI unreachable: the picture as it is", asyncio.run(looks.touched_copy(path, "x", [], "", "snapchat_1", "en")) == path)
looks._small = fake_small

print("\n== the Pictures tab ==")
import app.utils.db as db  # noqa: E402
db.init_db()
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import media_routes  # noqa: E402

(pic_dir / "IMG_9.jpg").unlink()


async def no_describe(name, data, ext, client_index=None):
    return "", "no model in the test"

media_routes._describe = no_describe
app = FastAPI()
app.include_router(media_routes.router)
client = TestClient(app)


def listing():
    return {p["name"]: p for p in client.get("/api/pictures").json()["pictures"]}

set_cfg(auto_look={"mode": "one", "look": "film", "looks": [], "strength": 0.6, "vary": 0.0})
first = photo()
r = client.post("/api/pictures", files={"file": ("me.jpg", first, "image/jpeg")}).json()
name = r["name"]
row = listing()[name]
check("a new picture gets the look Settings asks for", row["look"] == "film" and abs(row["strength"] - 0.6) < 0.01, str(row))
orig_files = list((TMP / "config" / "pictures_originals").glob("*"))
check("its original is kept", len(orig_files) == 1 and orig_files[0].read_bytes() == first)
check("and what is sent is not the original", (pic_dir / name).read_bytes() != first)
looks_list = client.get("/api/pictures/looks").json()
check("the looks the page offers", [l["id"] for l in looks_list["looks"]] == list(looks.LOOKS) and looks_list["auto"]["mode"] == "one")
pid = row["id"]
pv = client.get(f"/api/pictures/id/{pid}/preview?look=noir&strength=0.8&w=200")
check("a preview of another look, from the original", pv.status_code == 200 and pv.headers["content-type"] == "image/jpeg")
check("no such look", client.get(f"/api/pictures/id/{pid}/preview?look=bogus").status_code == 400)
check("no such picture", client.get("/api/pictures/id/abc123/preview?look=warm").status_code == 404)
r = client.post("/api/pictures/look", json={"items": [{"name": name, "id": pid}], "look": "mono", "strength": 1}).json()
row = listing()[name]
check("a look changed", r["results"][0]["look"] == "mono" and row["look"] == "mono")
check("made from the original, not on top of the last look",
      (pic_dir / name).read_bytes() == looks.render(first, ".jpg", "mono", 1.0)[0])
r = client.post("/api/pictures/look", json={"items": [{"name": name, "id": row["id"]}], "look": ""}).json()
check("and taken off: the original again, exactly", (pic_dir / name).read_bytes() == first and listing()[name]["look"] == "")
client.post("/api/pictures/look", json={"items": [{"name": name, "id": listing()[name]["id"]}], "look": "warm", "strength": 0.5})
db.add_picture_description(name, "A sunny hill.")
check("described again, the look stays", listing()[name]["look"] == "warm" and listing()[name]["description"] == "A sunny hill.")
db.rename_picture_db(name, "IMG_77.jpg")
os.rename(pic_dir / name, pic_dir / "IMG_77.jpg")
check("renumbered, the look goes with it", listing().get("IMG_77.jpg", {}).get("look") == "warm")
os.rename(pic_dir / "IMG_77.jpg", pic_dir / name)
db.rename_picture_db("IMG_77.jpg", name)
check("a bad request is refused", client.post("/api/pictures/look", json={"items": [], "look": "warm"}).status_code == 400
      and client.post("/api/pictures/look", json={"items": [{"name": name}], "look": "nope"}).status_code == 400)

set_cfg(auto_look={"mode": "one", "look": "warm", "looks": [], "strength": 0.7, "vary": 0.0})
r = client.post("/api/pictures", files={"file": ("dance.gif", moving_gif(), "image/gif")}).json()
gif = listing()[r["name"]]
check("a moving picture keeps its own look, and says it moves", gif["look"] == "" and gif["moving"] is True, str(gif))

set_cfg(auto_look={"mode": "random", "look": "warm", "looks": ["noir", "vivid"], "strength": 0.7, "vary": 0.1})
seen = {looks.pick_auto()[0] for _ in range(40)}
check("random: one of the ticked looks", seen <= {"noir", "vivid"} and len(seen) == 2, str(seen))
strengths = {looks.pick_auto()[1] for _ in range(40)}
check("and its strength varied a little", all(0.6 - 0.001 <= s_ <= 0.8 + 0.001 for s_ in strengths) and len(strengths) > 3)
set_cfg(auto_look={"mode": "off"})
check("off: nothing", looks.pick_auto() == ("", 0.0))
set_cfg(auto_look={"mode": False})
check("YAML's off (a false) is off", looks.auto_look_cfg()["mode"] == "off")
check("all at once, with nothing to put on: refused", client.post("/api/pictures/auto-look").status_code == 400)


async def ai_says(system, prompt, max_tokens):
    return '{"look": "vintage"}'

looks._small = ai_says
set_cfg(auto_look={"mode": "ai", "look": "warm", "looks": [], "strength": 0.7, "vary": 0.0})
new = media_routes._save(photo(w=200, h=300), "x.jpg")[0]
check("the AI's pick waits for the description", listing()[new]["look"] == "")
asyncio.run(media_routes._ai_look(new, "A girl on a hill."))
check("then goes on", listing()[new]["look"] == "vintage")
check("never on an old picture described again", asyncio.run(media_routes._ai_look(name, "x")) == name and listing()[name]["look"] == "warm")
media_routes._look_job.update(running=True, total=0, done=0)
asyncio.run(media_routes._auto_look_pass([new], looks.auto_look_cfg()))
check("all at once, in the background, with its progress", media_routes._look_job == {"running": False, "total": 0, "done": 1})
check("the progress is with the describing's", "looks" in client.get("/api/pictures/status").json())

(TMP / "config" / "pictures_originals" / "stray.jpg").write_bytes(b"x")
old = time.time() - 3600
os.utime(TMP / "config" / "pictures_originals" / "stray.jpg", (old, old))
for f in (TMP / "config" / "pictures_originals").iterdir():
    os.utime(f, (old, old))
media_routes._sweep_originals(force=True)
left = {f.name for f in (TMP / "config" / "pictures_originals").iterdir()}
used = {m["original"] for m in db.get_picture_looks().values() if m["original"]}
check("an original nobody uses is swept, the others kept", "stray.jpg" not in left and used <= left, f"{left} {used}")


async def touch_ai(system, prompt, max_tokens):
    return '{"caption": "hiii", "time": true}'

looks._small = touch_ai
row = listing()[name]
r = client.post("/api/pictures/touch-preview", json={"name": name, "id": row["id"], "kinds": ["caption", "time"]}).json()
check("what the AI would add, shown", r["image"].startswith("data:image/jpeg;base64,") and r["spec"]["caption"] == "hiii"
      and r["said"] == "a caption and the time", str({k: v for k, v in r.items() if k != "image"}))
looks._small = broken_small
r = client.post("/api/pictures/touch-preview", json={"name": name, "id": row["id"], "kinds": list(looks.TOUCH_KINDS),
                                                     "all": True}).json()
check("every kind at once, to see each one drawn, without asking the AI", r["image"].startswith("data:image/jpeg")
      and r["spec"].get("time") and r["spec"].get("day") and r["note"].startswith("Everything it can add") and r["sample"] is True)
check("the AI unreachable: the preview says so", client.post("/api/pictures/touch-preview",
      json={"name": name, "id": row["id"]}).status_code == 502)

pv = client.get("/api/pictures/sample-preview?look=film&strength=0.8&w=200")
check("a filter on a made-up picture, for when there is none of yours", pv.status_code == 200
      and pv.headers["content-type"] == "image/jpeg" and Image.open(io.BytesIO(pv.content)).width <= 200)
check("no such filter there either", client.get("/api/pictures/sample-preview?look=nope").status_code == 400)


async def ai_vintage(system, prompt, max_tokens):
    return '{"look": "vintage"}'

looks._small = ai_vintage
row = listing()[name]
r = client.post("/api/pictures/ai-look", json={"name": name, "id": row["id"]}).json()
check("which filter the AI would pick for a picture, and nothing put on it",
      r.get("look") == "vintage" and r.get("name") == "Vintage" and listing()[name]["look"] == "warm", str(r))
check("a picture with no description: the AI has nothing to go on",
      client.post("/api/pictures/ai-look", json={"name": gif["name"], "id": gif["id"]}).status_code == 409)

print("\n== where it is wired ==")
runner = src("app/platforms/discord_runner.py")
check("Discord: what goes out is the touched copy, gone after", "_pic_sent = await _looks.touched_copy(" in runner
      and 'f"discord_{ACCOUNT_INDEX}"' in runner and "_looks.drop_copy(pic_value, _pic_sent)" in runner
      and '{"file": discord.File(_pic_sent)}' in runner)
bridge = src("app/platforms/snapchat_bridge.py")
check("Snapchat: the same, as a Snap", bridge.count("await _queue_picture_if_any(msg, response)") == 2
      and 'f"snapchat_{ACCOUNT_INDEX}"' in bridge and "_queue_outgoing(chat, \"\", image=sent)" in bridge)
schema = src("app/web/schema.py")
check("Settings knows every picture setting", all(f'"bot.pictures.{k}"' in schema for k in (
    "auto_look.mode", "auto_look.look", "auto_look.looks", "auto_look.strength", "auto_look.vary",
    "touches.accounts", "touches.chance", "touches.kinds")))
check("off is written as a word, not YAML's false", 'mode: "off"' in src("resources/config.yaml"))
smap = src("webui/src/lib/settingsmap.ts")
check("a Pictures subtab of its own, drawn by its panel", 'panel: "pictures"' in smap
      and '{:else if sub.panel === "pictures"}' in src("webui/src/pages/Settings.svelte"))
panel = src("webui/src/lib/components/PicturesPanel.svelte")
check("the panel: a mode, looks, strength, accounts, how often, what, and a try", all(x in panel for x in (
    '"bot.pictures.auto_look.mode"', '"bot.pictures.touches.accounts"', '"bot.pictures.touches.chance"',
    '"bot.pictures.touches.kinds"', "api.touchPreview(", "api.autoLookAll(who)")))
check("hidden pictures stay hidden there, with a button to show them, remembered",
      "const veiled = $derived(!!sample && $picturesBlur && !reveal);" in panel and "class:is-veiled={veiled}" in panel
      and "function toggleReveal()" in panel and 'localStorage.setItem(REVEAL_KEY, reveal ? "1" : "0")' in panel)
check("the preview in the picture's own shape, not cut to 3:4", "ratio = img.naturalWidth / img.naturalHeight" in panel
      and "aspect-ratio: {ratio};" in panel and "aspect-ratio: 3 / 4" not in panel)
check("a preview beside the filters: the one under the pointer, the strength set, the original while held, the AI's pick",
      'class="pp-prev-frame"' in panel and "onmouseenter={() => (hovered = l.id)}" in panel
      and "api.samplePreviewUrl(previewLook, shownStrength, 520)" in panel and "onpointerdown={() => (holding = true)}" in panel
      and "api.aiLookFor(sample.name, sample.id, who)" in panel)
page = src("webui/src/pages/Pictures.svelte")
check("the tab: a look on each card, a button for it, one for a selection, and what new ones get",
      'class="pc-look"' in page and "openLook([p])" in page and "Filter {selected.size}" in page and "autoValue" in page
      and 'class="pt-bar' in page and "to change or remove several at once" not in page)
check("backups keep the originals", "config/pictures_originals/" in src("app/web/routes/system_routes.py"))
editor = src("webui/src/lib/components/LookEditor.svelte")
check("the filter window has Auto: the AI picks one from what the picture shows, shown on it at once",
      'class="le-auto"' in editor and "onclick={pickAuto}" in editor
      and "const r: any = await api.aiLookFor(first.name, first.id ?? \"\", persona);" in editor and "aiPick = r.look;" in editor)
check("thinking, a ring turns round it; the look picked pops and is marked", ".le-auto.is-thinking .le-auto-icon::after" in editor
      and "@keyframes le-turn" in editor and "class:is-ai={auto && aiPick === l.id}" in editor and "@keyframes le-picked" in editor)
check("never stuck while it picks: the window closes, and an answer that comes after is not used",
      "if (mine !== ticket || !open) return;" in editor and "const close = () => (onclose ? onclose() : (open = false));"
      in src("webui/src/lib/components/Modal.svelte"))
check("made over: the picture on a glow of its own colours, each look crossfading in, the looks as named tiles",
      'class="le-glow"' in editor and 'class="le-top"' in editor and "underSrc = shownSrc;" in editor
      and 'class="le-tile"' in editor and 'use:domino={{ step: 22, sound: "wind", level: 0.45, once: true }}' in editor)
check("heard: a glint as the pick arrives", 'play("glint", { p: 1, strong: true });' in editor)
check("several at once: each picture gets its own pick", "if (auto && still.length > 1) return applyEach();" in editor
      and "await api.putLook([{ name: p.name, id: p.id }], r.look, strength, persona);" in editor)
check("a picture with no description says why the AI cannot pick", 'toast(e?.message || "The AI could not pick one", "err");' in editor)

print("\n== moods, not only colour ==")
check("looks that change how a picture feels: cinematic, dreamy, sunset, moody, neon, Y2K",
      all(k in looks.LOOKS for k in ("cinematic", "dreamy", "sunset", "moody", "neon", "y2k")))
check("film ones: polaroid, disposable, lomo, matte; black and white: silver, sepia",
      all(k in looks.LOOKS for k in ("polaroid", "disposable", "lomo", "matte", "silver", "sepia")))
check("every look has a group, the groups in the order the page shows them",
      set(looks.GROUP_OF) == set(looks.LOOKS) and set(looks.GROUP_OF.values()) == set(looks.GROUPS)
      and [looks.GROUP_OF[k] for k in looks.LOOKS] == sorted((looks.GROUP_OF[k] for k in looks.LOOKS), key=looks.GROUPS.index))
check("graded, not only tinted: shadows one colour, the light another, as soft light",
      "def _tone(img: Image.Image, shadow: tuple, highlight: tuple, amount: float" in src("app/utils/looks.py")
      and "ImageChops.soft_light(img, tones)" in src("app/utils/looks.py"))
scene = Image.open(io.BytesIO(photo())).convert("RGB")
sunset_on = looks.apply_look(scene, "sunset", 1.0)


def mean(img, top):
    h = img.height // 6
    box = (0, 0, img.width, h) if top else (0, img.height - h, img.width, img.height)
    return img.crop(box).resize((1, 1)).getpixel((0, 0))


(r0, g0, b0), (r1, g1, b1) = mean(scene, True), mean(sunset_on, True)
(fr0, fg0, fb0), (fr1, fg1, fb1) = mean(scene, False), mean(sunset_on, False)
check("a sunset warms the top towards orange and turns the foot towards purple",
      (r1 - r0) - (b1 - b0) > 8 and (fb1 - fb0) - (fg1 - fg0) > 4,
      f"top {(r0, g0, b0)} -> {(r1, g1, b1)}, foot {(fr0, fg0, fb0)} -> {(fr1, fg1, fb1)}")
check("the page groups them under their names", "group" in looks_list["looks"][0]
      and '{#if i > 0 && l.group && l.group !== looks[i - 1].group}<span class="le-group">{l.group}</span>{/if}' in editor)

print("\n== adding pictures, wherever the page is ==")
lib = src("webui/src/lib/pictures.ts")
check("the adding and its count live outside the page: leaving the tab and coming back still shows it",
      "export const addState = writable<AddState | null>(null);" in lib and "export function addPictures(" in lib
      and "const adding = $derived($addState);" in page)
check("pictures dropped while others go in join the queue", "queue.push(...files.map((file) => ({ file, persona })));" in lib and "if (!adding) void addAll(after);" in lib)
check("many at once: one notice at the end, not one each", "toast(failed.length ? `Added ${added} of ${s.total} pictures." in lib
      and "} else if (!many) {" in lib)
check("heard filling up, a step higher with each", 'if (next.total > 1) play("rise", { p: next.done / next.total, level: 0.55 });' in lib)
check("seen filling up: a ring round a twinkling sparkle, the count rolling on, a light along the foot",
      'class="pz-ring"' in page and "stroke-dashoffset: {ringSpin ? 72 : 100 - ringPct}" in page
      and "adding.video ? adding.video.step === \"describe\" : adding.total === 1" in page
      and 'class="pz-n"' in page and 'class="pz-bar"' in page and "@keyframes pz-run" in page)
check("the filter new pictures get, picked right where they go in", 'class="pz-auto"' in page
      and "<Select size=\"sm\" value={autoChoice} options={autoOptions} onchange={setAuto} />" in page
      and 'await api.configField("bot.pictures.auto_look.mode", mode, { persona });' in page
      and 'await api.configField("bot.pictures.auto_look.look", look, { persona });' in page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
