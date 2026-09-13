"""
app/utils/imageimport.py - turning whatever someone drops into a sendable picture.

People have their selfies in a folder, or a zip straight off a phone, in every
format a camera or a screenshot tool produces. The bot can only send a handful
of those, so anything else has to be converted rather than refused.

Two rules shape the whole module:

  * If a file is already something the bot can send, it is written through
    untouched. Re-encoding a JPEG loses quality for nothing, and re-encoding a
    GIF loses the animation.
  * Otherwise it is converted, preferring PNG, falling back to JPEG when the
    PNG comes out too large to attach.

Nothing here trusts the names inside a zip. Entries are read by handle and
saved under a name this module generates, so a member called
"../../.env" is just a picture called IMG_7.png.
"""

import io
import os
import zipfile

# What Discord and Snapchat will actually take from us.
CANONICAL = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Roughly the attachment ceiling, with room for the multipart overhead. A file
# above this is re-encoded smaller rather than saved and silently rejected by
# Discord later.
TARGET_MAX_BYTES = 8 * 1024 * 1024

# A 12000px scan is a picture of nothing useful once it is sent. Anything wider
# is scaled down before conversion, which is also what keeps the PNG encoder
# from spending a minute on a single file.
MAX_EDGE = 4096

# Zip guards. A malicious or just silly archive should fail politely instead of
# filling the disk.
MAX_MEMBERS = 500
MAX_TOTAL_UNCOMPRESSED = 1024 * 1024 * 1024      # 1 GB
MAX_MEMBER_UNCOMPRESSED = 200 * 1024 * 1024      # 200 MB

_heif_registered = False


def _ensure_openers() -> None:
    """Teach Pillow about HEIC and AVIF if the optional plugin is installed.

    Every photo off a modern iPhone is HEIC, so without this the most likely
    thing anyone drops is the one thing that does not work.
    """
    global _heif_registered
    if _heif_registered:
        return
    _heif_registered = True
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass          # plain Pillow still covers everything else
    try:
        import pillow_avif  # noqa: F401
    except Exception:
        pass


def is_zip(data: bytes, filename: str = "") -> bool:
    """Zips are detected by their signature, not their name.

    A .zip that is really a JPEG, or an archive saved without an extension,
    should both end up doing the right thing.
    """
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return True
    return os.path.splitext(filename or "")[1].lower() == ".zip" and not data[:2] == b"\xff\xd8"


def convert(data: bytes, filename: str = "") -> tuple[bytes, str, str]:
    """Normalise one image.

    Returns (bytes, extension, note). The note is empty unless something was
    changed that is worth telling the user about. Raises ValueError when the
    bytes are not an image at all.
    """
    _ensure_openers()
    from PIL import Image, ImageSequence     # noqa: F401  (Pillow is a hard dependency)

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError(f"not an image ({type(exc).__name__})") from exc

    ext = os.path.splitext(filename or "")[1].lower()
    fmt = (img.format or "").upper()
    animated = getattr(img, "n_frames", 1) > 1
    oversized = max(img.size) > MAX_EDGE
    too_big = len(data) > TARGET_MAX_BYTES

    # Already sendable, sane size: keep the original bytes exactly as they are.
    canonical_fmt = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}.get(fmt)
    if canonical_fmt and not too_big and not oversized:
        # Trust the format, not the name: a .png that is really a JPEG gets the
        # extension it has actually earned.
        return data, canonical_fmt, "" if ext == canonical_fmt else f"saved as {canonical_fmt}"

    # An animated image cannot survive a still conversion, so the frames are
    # kept and only the container is normalised.
    if animated:
        if canonical_fmt:
            return data, canonical_fmt, ""
        out = io.BytesIO()
        try:
            img.save(out, format="GIF", save_all=True, optimize=True)
            return out.getvalue(), ".gif", f"converted from {fmt or 'unknown'}"
        except Exception:
            img.seek(0)      # fall through and save the first frame as a still

    if oversized:
        img.thumbnail((MAX_EDGE, MAX_EDGE))

    note = f"converted from {fmt or 'unknown'}" if not canonical_fmt else ""
    if oversized:
        note = (note + ", " if note else "") + f"scaled to {img.width}x{img.height}"

    # PNG first: lossless, and keeps transparency for stickers and screenshots.
    flat = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P", "PA") else img.convert("RGB")
    out = io.BytesIO()
    flat.save(out, format="PNG", optimize=True)
    if out.tell() <= TARGET_MAX_BYTES:
        return out.getvalue(), ".png", note

    # A photograph makes a huge PNG. JPEG is the right answer for those, so
    # transparency is flattened onto white rather than turning black.
    if flat.mode == "RGBA":
        from PIL import Image as _Image
        bg = _Image.new("RGB", flat.size, (255, 255, 255))
        bg.paste(flat, mask=flat.split()[-1])
        flat = bg
    else:
        flat = flat.convert("RGB")

    for quality in (88, 75, 60):
        out = io.BytesIO()
        flat.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        if out.tell() <= TARGET_MAX_BYTES:
            return out.getvalue(), ".jpg", (note + ", " if note else "") + "compressed to fit"

    # Still too big at low quality: shrink until it fits.
    shrunk = flat
    for _ in range(4):
        shrunk = shrunk.resize((max(1, shrunk.width // 2), max(1, shrunk.height // 2)))
        out = io.BytesIO()
        shrunk.save(out, format="JPEG", quality=80, optimize=True, progressive=True)
        if out.tell() <= TARGET_MAX_BYTES:
            return out.getvalue(), ".jpg", (note + ", " if note else "") + "resized to fit"
    raise ValueError("image is too large to send even after resizing")


def _worth_reading(info: zipfile.ZipInfo) -> bool:
    name = info.filename.replace("\\", "/")
    if info.is_dir():
        return False
    base = name.rsplit("/", 1)[-1]
    if not base or base.startswith("."):
        return False                       # .DS_Store and friends
    if name.startswith("__MACOSX/") or "/__MACOSX/" in name:
        return False                       # macOS resource forks, never images
    if info.file_size > MAX_MEMBER_UNCOMPRESSED:
        return False
    return True


def iter_zip(data: bytes):
    """Yield (member name, bytes) for every plausible file in an archive.

    Subfolders are walked, because "put the folder in a zip" is how anyone
    would actually send a batch of pictures. Order follows the names so the
    result is the same every time.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [i for i in zf.infolist() if _worth_reading(i)]
        members.sort(key=lambda i: i.filename.lower())
        if len(members) > MAX_MEMBERS:
            members = members[:MAX_MEMBERS]
        total = 0
        for info in members:
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                break
            try:
                with zf.open(info) as fh:
                    yield info.filename, fh.read()
            except Exception:
                continue
