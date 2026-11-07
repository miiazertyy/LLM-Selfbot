"""The same picture twice, ringed in red; and careful mode in plain words, no longer pushed by System (2026-11-06).

Asked for: duplicate pictures warned about, "like a red thing around the pic card", which can be put away for good;
careful mode made "logical" (its "0.4" and "1.5" said nothing, its date was an empty box) and no longer recommended
by System's health checks.
"""
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="dupes-"))
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


from PIL import Image, ImageDraw, ImageFilter  # noqa: E402


def photo(seed, size=(900, 1200)):
    r = random.Random(seed)
    im = Image.new("RGB", size, (r.randrange(256), r.randrange(256), r.randrange(256)))
    dr = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = r.randrange(size[0]), r.randrange(size[1])
        dr.ellipse((x, y, x + r.randrange(40, 300), y + r.randrange(40, 300)),
                   fill=(r.randrange(256), r.randrange(256), r.randrange(256)))
    return im.filter(ImageFilter.GaussianBlur(6))


pics = TMP / "config" / "pictures"
a = photo(1)
a.save(pics / "IMG_1.jpg", quality=92)
time.sleep(0.02)
shutil.copy(pics / "IMG_1.jpg", pics / "IMG_2.jpg")                         # the same file added again
a.resize((450, 600)).save(pics / "IMG_3.webp", quality=70)                   # saved again, smaller and as WebP
photo(2).save(pics / "IMG_4.jpg")                                            # another picture
Image.new("RGB", (800, 800), (0, 0, 0)).save(pics / "IMG_5.png")
Image.new("RGB", (800, 800), (255, 255, 255)).save(pics / "IMG_6.png")       # plain black and plain white
b = a.copy()
ImageDraw.Draw(b).rectangle((300, 300, 700, 800), fill=(10, 200, 30))
b.save(pics / "IMG_7.jpg")                                                   # the same photo, much changed
a.crop((0, 0, 900, 900)).save(pics / "IMG_8.jpg")                            # cropped to another shape

print("== which are the same picture ==")
from app.utils.db import init_db  # noqa: E402

init_db()
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import media_routes  # noqa: E402

app = FastAPI()
app.include_router(media_routes.router)
listing = TestClient(app).get("/api/pictures").json()["pictures"]
by_name = {p["name"]: p for p in listing}
ids = {p["id"]: p["name"] for p in listing}
twins = {n: sorted(ids[i] for i in p["dupes"]) for n, p in by_name.items()}
check("every picture says which others are the same picture", all(isinstance(p["dupes"], list) for p in listing))
check("a copy added again, and the photo saved again smaller in another format",
      twins["IMG_1.jpg"] == ["IMG_2.jpg", "IMG_3.webp"] and twins["IMG_3.webp"] == ["IMG_1.jpg", "IMG_2.jpg"], str(twins))
check("another picture is not", twins["IMG_4.jpg"] == [])
check("a plain black and a plain white are not, though their shapes in grey match", twins["IMG_5.png"] == []
      and twins["IMG_6.png"] == [])
check("the same photo much changed is not", twins["IMG_7.jpg"] == [])
check("nor one cropped to another shape", twins["IMG_8.jpg"] == [])
from app.utils import picdupes  # noqa: E402

check("asked again, nothing is worked out twice: kept by the picture's id",
      all(p["id"] in picdupes._seen for p in listing))

print("\n== on the Pictures page ==")
page = read("webui/src/pages/Pictures.svelte")
check("a card that is the same picture as another is ringed in red",
      'class:is-dupe={twins.length > 0}' in page and ".pic-card.is-dupe :global(.glass)" in page
      and "0 0 0 2px var(--color-bad)" in page)
check("saying which it is the same as", "Same picture as {twins.map((q) => q.name).join(\", \")}" in page)
check("Keep both puts it away for good, both cards at once", "function keepBoth(p: Pic, twins: Pic[])" in page
      and "keptDupes.update(" in page and 'play("off");' in page)
check("or delete this copy, with the page's own undo", "onclick={() => removeLater([p])}>" in page
      and "Delete this one" in page)
check("a copy kept is a pair, by the pictures' ids and per persona: a third copy is a new pair, and is warned about",
      "const pairKey = (a: string, b: string) => `${pid}:${[a, b].sort().join(\"|\")}`;" in page)
stores = read("webui/src/lib/stores.ts")
from app.web.routes import prefs_routes  # noqa: E402

check("remembered in the panel's preferences, on the server too",
      'export const keptDupes = persisted<string[]>("keptDupes", [], true);' in stores and "keptDupes" in prefs_routes.ALLOWED)

print("\n== careful mode, in plain words ==")
settings = read("webui/src/pages/Settings.svelte")
check("replies as a share of usual: 40%, not 0.4", '"bot.conservative.reply_scale": (v) => (v >= 1 ? "Usual" : `${Math.round(v * 100)}%`)' in settings)
check("waits as how much longer: 1.5× longer, not 1.5",
      '"bot.conservative.wait_scale": (v) => (v <= 1 ? "Usual" : `${+v.toFixed(2)}× longer`)' in settings)
check("its day picked on the calendar and said as a date, not typed into an empty box",
      '{:else if f.key === "bot.conservative.until"}' in settings and 'type="date" class="day-input"' in settings
      and "showPicker()" in settings and "Pick a day" in settings)
check("and never a day already here, which would switch it off at once", "min={tomorrow()}" in settings)
check("its day and pace shown only while it is on", '"bot.conservative.until": () => carefulOn()' in settings
      and '"bot.conservative.reply_scale": () => carefulOn()' in settings)
from app.web import descriptions, schema  # noqa: E402

fields = {f["key"]: f for f in schema.CONFIG_SCHEMA}
check("labels in plain words", fields["bot.conservative.until"]["label"] == "Switches off on"
      and fields["bot.conservative.reply_scale"]["label"] == "Replies" and fields["bot.conservative.wait_scale"]["label"] == "Waits")
check("in steps a person picks between: every 5%, every quarter", fields["bot.conservative.reply_scale"]["step"] == 0.05
      and fields["bot.conservative.wait_scale"]["step"] == 0.25)
words = {k: v for k, v in descriptions.DESCRIPTIONS.items() if k.startswith("bot.conservative.")}
check("each said in one short line", len(words) == 4 and all(len(v) <= 120 for v in words.values()), str(words))
check("no fractions or multipliers left to decode", not any("fraction" in v or "stretched" in v for v in words.values()))

print("\n== not pushed by System ==")
from app.utils import stealth  # noqa: E402

off = {r["name"]: r for r in stealth.report({"bot": {"conservative": {}}})}
check("off, it is not a problem the health checks point at", "Careful mode" not in off)
on = {r["name"]: r for r in stealth.report({"bot": {"conservative": {"enabled": True, "until": "2099-12-01"}}})}
check("on, it says so as a check that passes, in words", on["Careful mode"]["ok"] is True
      and on["Careful mode"]["detail"] == "on until Dec 1, 2099: 40% of the usual replies, waits 1.5× longer")
check("the bridge's log line says it the same way", "% of the usual replies, " in read("app/platforms/snapchat_bridge.py"))
shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
