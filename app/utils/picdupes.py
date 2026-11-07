"""Pictures that are the same picture: one file added twice, or the same photo saved again smaller, sharper or in
another format, which the Pictures page rings in red (with "Keep both" to put the warning away for good).

Each picture's look is boiled down to 64 bits: a difference hash, which side of each neighbour a pixel is lighter on,
of the picture in grey at 9x8, as it stands up (its EXIF turn applied). Two pictures are the same when their bits differ
in a few places at most, their shapes match, and their colours are close (a plain black picture and a plain white one
hash the same, and are not the same picture). Worked out once per picture, kept by its id (which changes with the file),
so the page asking again costs nothing. Videos are left out: their stills say little about the rest of them.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

#: Bits two pictures may differ in and still be one picture: a re-saved or resized copy moves a few at most.
NEAR = 5
#: How far their shapes may differ (width over height), as a share.
SHAPE = 0.03
#: How far apart their average colours may be, per channel, out of 255.
COLOUR = 28

_seen: dict = {}


def fingerprint(path: Path, key: str):
    """(hash, shape, colour) of one picture, kept by `key`; None for what cannot be read as a picture."""
    if key in _seen:
        return _seen[key]
    out = None
    try:
        with Image.open(path) as im:
            # A JPEG is read at a fraction of its size, which is all 9x8 needs, and far quicker.
            im.draft("RGB", (128, 128))
            im = ImageOps.exif_transpose(im).convert("RGB")
            w, h = im.size
            grey = im.convert("L").resize((9, 8), Image.LANCZOS)
            px = list(grey.getdata())
            bits = 0
            for row in range(8):
                for col in range(8):
                    bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
            colour = im.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
            out = (bits, (w / h) if h else 1.0, tuple(colour))
    except Exception:
        out = None
    _seen[key] = out
    return out


def same(a, b) -> bool:
    """Whether two fingerprints are one picture."""
    if not a or not b:
        return False
    return (bin(a[0] ^ b[0]).count("1") <= NEAR
            and abs(a[1] - b[1]) <= SHAPE * max(a[1], b[1])
            and all(abs(x - y) <= COLOUR for x, y in zip(a[2], b[2])))


def alike(items) -> dict:
    """{key: [the keys of the pictures that are the same picture]} for (key, path) pairs; a picture with none is left
    out. Each persona's pictures are asked for in turn, so what is kept is only thrown away once there is a lot of it."""
    items = list(items)
    if len(_seen) > 5000:
        _seen.clear()
    prints = [(k, fingerprint(p, k)) for k, p in items]
    out: dict = {}
    for i, (a, fa) in enumerate(prints):
        for b, fb in prints[i + 1:]:
            if same(fa, fb):
                out.setdefault(a, []).append(b)
                out.setdefault(b, []).append(a)
    return out
