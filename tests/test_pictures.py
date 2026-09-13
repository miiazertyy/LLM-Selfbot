"""Importing pictures: any format, and zips of them.

People keep their selfies in a folder in whatever their phone or screenshot
tool produced. The bot can only send png, jpg, gif and webp, so the import has
to convert rather than refuse, and it has to walk an archive because "zip the
folder" is how anyone would actually send a batch.

Two properties matter beyond "it works":

  * Something already sendable is written through byte for byte. Re-encoding a
    JPEG loses quality for no reason, and re-encoding a GIF loses the frames.
  * A name inside a zip is never used as a path. An entry called "../../.env"
    has to land as an ordinary IMG_n.png inside the pictures folder.
"""
import io
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


SANDBOX = Path(tempfile.mkdtemp(prefix="pics_"))
(SANDBOX / "config" / "pictures").mkdir(parents=True)
shutil.copyfile(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX

import app.utils.helpers as helpers
_orig = helpers.resource_path
helpers.resource_path = lambda rel: (
    str(SANDBOX / rel) if str(rel).replace("\\", "/").split("/")[0] in ("config", "ipc")
    else _orig(rel))
helpers.invalidate_config_cache()

from PIL import Image
from app.utils.imageimport import convert, is_zip, iter_zip


def img(fmt, size=(320, 240), mode="RGB", **kw):
    buf = io.BytesIO()
    colour = (200, 60, 90) if mode == "RGB" else (200, 60, 90, 128)
    Image.new(mode, size, colour).save(buf, format=fmt, **kw)
    return buf.getvalue()


# ── Formats the bot already speaks are left alone ───────────────────────────
print("== already sendable, so untouched ==")
for fmt, ext in (("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")):
    src = img(fmt)
    blob, got, _ = convert(src, f"x{ext}")
    check(f"{fmt} passes through byte for byte", blob == src and got == ext, f"{got}")

print("\n== animation survives ==")
frames = [Image.new("RGB", (48, 48), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
buf = io.BytesIO()
frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)
gif = buf.getvalue()
blob, ext, _ = convert(gif, "anim.gif")
check("animated gif keeps every frame",
      getattr(Image.open(io.BytesIO(blob)), "n_frames", 1) == 3 and ext == ".gif")

# ── Everything else is converted ────────────────────────────────────────────
print("\n== anything else is converted ==")
for fmt, name in (("BMP", "a.bmp"), ("TIFF", "b.tiff"), ("ICO", "c.ico")):
    src = img(fmt, size=(64, 64) if fmt == "ICO" else (320, 240))
    blob, ext, note = convert(src, name)
    ok = ext in (".png", ".jpg") and Image.open(io.BytesIO(blob)).format in ("PNG", "JPEG")
    check(f"{fmt} becomes something sendable", ok, f"{ext} {note}")

src = img("PNG", mode="RGBA")
blob, ext, _ = convert(src, "t.png")
check("transparency is not flattened", Image.open(io.BytesIO(blob)).mode in ("RGBA", "LA", "P"))

print("\n== the format wins over the file name ==")
blob, ext, note = convert(img("JPEG"), "actually_a_jpeg.png")
check("a JPEG named .png is saved as .jpg", ext == ".jpg", f"{ext} {note}")

print("\n== absurd sizes are brought down ==")
blob, ext, note = convert(img("PNG", size=(9000, 200)), "huge.png")
check("an oversized picture is scaled", max(Image.open(io.BytesIO(blob)).size) <= 4096, note)

print("\n== junk is refused with a reason ==")
try:
    convert(b"just some text, definitely not a picture", "notes.txt")
    check("non-image rejected", False, "it was accepted")
except ValueError as exc:
    check("non-image rejected", True)
    check("the reason says what is wrong", "not an image" in str(exc), str(exc))

# ── Archives ────────────────────────────────────────────────────────────────
print("\n== a zip, with subfolders and the junk an OS adds ==")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("selfies/one.jpg", img("JPEG"))
    z.writestr("selfies/nested/deep/two.png", img("PNG"))
    z.writestr("selfies/nested/three.bmp", img("BMP"))
    z.writestr("four.tiff", img("TIFF"))
    z.writestr("__MACOSX/selfies/._one.jpg", b"resource fork")
    z.writestr("selfies/.DS_Store", b"junk")
    z.writestr("notes.txt", b"not a picture")
    z.writestr("empty/", b"")
    z.writestr("../../escape.png", img("PNG"))
archive = buf.getvalue()

check("detected by signature, not by name", is_zip(archive, "photos") is True)
check("a jpeg is not mistaken for a zip", is_zip(img("JPEG"), "a.zip") is False)

members = list(iter_zip(archive))
names = [m for m, _ in members]
check("walks nested subfolders at any depth",
      "selfies/nested/deep/two.png" in names, str(names))
check("skips macOS resource forks", not any("__MACOSX" in n for n in names), str(names))
check("skips dotfiles", not any(n.endswith(".DS_Store") for n in names), str(names))
check("skips directory entries", "empty/" not in names, str(names))
check("keeps the non-image so it can be reported", "notes.txt" in names, str(names))

print("\n== a hostile member name is just a picture ==")
import app.web.routes.media_routes as media
media.PICTURES_DIR = SANDBOX / "config" / "pictures"

saved = []
for member, blob in members:
    try:
        name, _ = media._save(blob, member)
        saved.append(name)
    except ValueError:
        pass

check("every real image was imported", len(saved) == 5, f"{len(saved)}: {saved}")
check("all saved under generated names",
      all(n.startswith("IMG_") for n in saved), str(saved))
on_disk = sorted(p.name for p in (SANDBOX / "config" / "pictures").iterdir())
check("nothing escaped the pictures folder",
      len(on_disk) == 5 and all(n.startswith("IMG_") for n in on_disk), str(on_disk))
check("no stray file appeared beside the data dir",
      not (SANDBOX.parent / "escape.png").exists() and not (SANDBOX / "escape.png").exists())
check("names are numbered without gaps",
      sorted(int(n[4:].split(".")[0]) for n in on_disk) == [1, 2, 3, 4, 5], str(on_disk))

print("\n== the listing sees them all ==")
check("every imported file is listed", len(media._files()) == 5, str(media._files()))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
