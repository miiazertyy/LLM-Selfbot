"""app/platforms/minecraft/skins.py - a Minecraft account's picture: its skin, drawn standing in 3D.

The skin is the one Mojang has for the name (a premium account's, as NameMC shows it), looked up through Mojang's
own API: the name to its id, its id to its textures. A name with no premium account behind it (an offline one) has
none, so it gets the default skin the game itself gives that name: one of the nine official ones (Steve, Alex and
the seven since 1.19.3), picked from the name exactly as the game picks it, so it looks here as it does to players.
Those nine are read from the bot's own install (minecraft-assets, in mindcraft), not kept here.

Drawn here, not fetched from a render site: each face of each box of the model (head, body, arms, legs, and the
outer layer over each) is its square of the skin under one affine transform, in an orthographic view from a little
above and to the side (NameMC's own angles: turned 30 degrees, looking down 21), lit as the game lights a block.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import urllib.request
import uuid as _uuid
from pathlib import Path

PROFILE = "https://api.mojang.com/users/profiles/minecraft/{}"
SESSION = "https://sessionserver.mojang.com/session/minecraft/profile/{}"
# The game's default skins since 1.19.3, in its own order (DefaultPlayerSkin): the slim ones, then the wide.
DEFAULTS = ["alex", "ari", "efe", "kai", "makena", "noor", "steve", "sunny", "zuri"]
NAME_RE = re.compile(r"[A-Za-z0-9_]{1,16}")


# ── Which skin ────────────────────────────────────────────────────────────────

def offline_uuid(name: str) -> _uuid.UUID:
    """The id an offline server gives a name: UUID.nameUUIDFromBytes("OfflinePlayer:" + name)."""
    md5 = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    md5[6] = (md5[6] & 0x0F) | 0x30
    md5[8] = (md5[8] & 0x3F) | 0x80
    return _uuid.UUID(bytes=bytes(md5))


def java_hash(u: _uuid.UUID) -> int:
    """java.util.UUID.hashCode()."""
    def s64(x):
        return x - (1 << 64) if x >= 1 << 63 else x
    hilo = s64(u.int >> 64) ^ s64(u.int & ((1 << 64) - 1))
    h = ((hilo >> 32) ^ hilo) & 0xFFFFFFFF
    return h - (1 << 32) if h >= 1 << 31 else h


def default_for(u: _uuid.UUID) -> tuple[str, bool]:
    """(which of the nine, slim) the game gives an id with no skin of its own."""
    i = java_hash(u) % (2 * len(DEFAULTS))
    return DEFAULTS[i % len(DEFAULTS)], i < len(DEFAULTS)


def _assets_dir() -> Path | None:
    from app.platforms.minecraft.install import MC_DIR
    base = MC_DIR / "node_modules" / "minecraft-assets" / "minecraft-assets" / "data"
    return base if base.is_dir() else None


def default_png(name: str, slim: bool) -> bytes:
    """One of the nine, from the newest version the bot's install has it for; Steve or Alex from an older one."""
    base = _assets_dir()
    if base is None:
        return b""

    def newest(paths):
        # data/<version>/entity/player/<model>/<name>.png, or data/<version>/entity/<name>.png before 1.19.3
        def key(p):
            return [int(x) if x.isdigit() else 0 for x in p.parts[-5 if "player" in p.parts else -3].split(".")]
        return sorted(paths, key=key)

    found = newest(base.glob(f"*/entity/player/{'slim' if slim else 'wide'}/{name}.png"))
    if not found:
        found = newest(base.glob(f"*/entity/{'alex' if slim else 'steve'}.png"))
    return found[-1].read_bytes() if found else b""


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "LLMSelfbot (account picture)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if r.status == 200 else b""


def lookup(name: str, timeout: float = 8.0) -> dict:
    """The skin for a name: {"png", "slim", "source" ("mojang" or "default"), "skin" (which default, or "")}.
    Mojang down or slow is the same as no premium account: the default the game would show."""
    name = str(name or "").strip()
    uid = None
    if NAME_RE.fullmatch(name):
        try:
            prof = json.loads(_get(PROFILE.format(name), timeout) or b"{}")
            uid = _uuid.UUID(prof["id"]) if prof.get("id") else None
            if uid is not None:
                sess = json.loads(_get(SESSION.format(uid.hex), timeout) or b"{}")
                for prop in sess.get("properties") or []:
                    if prop.get("name") != "textures":
                        continue
                    tex = json.loads(base64.b64decode(prop.get("value") or "")).get("textures") or {}
                    skin = tex.get("SKIN") or {}
                    if skin.get("url"):
                        png = _get(skin["url"].replace("http://", "https://"), timeout)
                        if png:
                            slim = (skin.get("metadata") or {}).get("model") == "slim"
                            return {"png": png, "slim": slim, "source": "mojang", "skin": ""}
        except Exception:
            pass
    which, slim = default_for(uid or offline_uuid(name))
    return {"png": default_png(which, slim), "slim": slim, "source": "default", "skin": which}


# ── Drawing it ────────────────────────────────────────────────────────────────

def _legacy_to_modern(skin):
    """A 64x32 skin (before 1.8) as 64x64: the left arm and leg made from the right ones, mirrored, as the game does."""
    from PIL import Image, ImageOps
    out = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    out.paste(skin, (0, 0))

    def face(src_box, dst_xy):
        out.paste(ImageOps.mirror(skin.crop(src_box)), dst_xy)

    for sx, sy, dx, dy in ((0, 16, 16, 48), (40, 16, 32, 48)):     # leg, arm: (u, v) of the right one, of the left
        face((sx + 4, sy, sx + 8, sy + 4), (dx + 4, dy))           # top
        face((sx + 8, sy, sx + 12, sy + 4), (dx + 8, dy))          # bottom
        face((sx + 8, sy + 4, sx + 12, sy + 16), (dx, dy + 4))     # its left side becomes the right
        face((sx + 4, sy + 4, sx + 8, sy + 16), (dx + 4, dy + 4))  # front
        face((sx, sy + 4, sx + 4, sy + 16), (dx + 8, dy + 4))      # its right side becomes the left
        face((sx + 12, sy + 4, sx + 16, sy + 16), (dx + 12, dy + 4))  # back
    return out


def _boxes(slim: bool) -> list:
    """(texture u, v, size w h d, position x y z of its low corner, how much the outer layer is inflated): the model
    in the skin's own pixels, facing +z, the character's right hand at -x."""
    aw = 3 if slim else 4
    base = [
        ((0, 0), (8, 8, 8), (-4, 24, -4)),          # head
        ((16, 16), (8, 12, 4), (-4, 12, -2)),       # body
        ((40, 16), (aw, 12, 4), (-4 - aw, 12, -2)),  # right arm
        ((32, 48), (aw, 12, 4), (4, 12, -2)),       # left arm
        ((0, 16), (4, 12, 4), (-4, 0, -2)),         # right leg
        ((16, 48), (4, 12, 4), (0, 0, -2)),         # left leg
    ]
    # Each one's outer layer (the hat, the jacket, the sleeves, the trousers), a little bigger than what it covers.
    over = [(32, 0), (16, 32), (40, 32), (48, 48), (0, 32), (0, 48)]
    out = [(uv, size, pos, 0.0) for uv, size, pos in base]
    for i, ((_, size, pos), uv) in enumerate(zip(base, over)):
        out.append((uv, size, pos, 0.5 if i == 0 else 0.25))
    return out


def render(png: bytes, slim: bool, scale: int = 24, theta: float = 30.0, phi: float = 21.0):
    """The skin standing, turned `theta` degrees and seen from `phi` above, `scale` pixels to one of the skin's. An
    RGBA image cropped to the figure."""
    from PIL import Image
    skin = Image.open(io.BytesIO(png)).convert("RGBA")
    if skin.size == (64, 32):
        skin = _legacy_to_modern(skin)
    elif skin.size != (64, 64):
        skin = skin.resize((64, 64), Image.NEAREST)
    t, p = math.radians(theta), math.radians(phi)
    ct, st, cp, sp = math.cos(t), math.sin(t), math.cos(p), math.sin(p)

    def rot(v):
        x, y, z = v
        x1, z1 = x * ct + z * st, -x * st + z * ct
        return (x1, y * cp - z1 * sp, y * sp + z1 * cp)

    w, h = 26 * scale, 40 * scale
    cx, cy = w / 2, h * 0.5 + 16 * scale * 0.95
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    faces = []
    for (u, v), (bw, bh, bd), (x0, y0, z0), grow in _boxes(slim):
        x0, y0, z0 = x0 - grow, y0 - grow, z0 - grow
        x1, y1, z1 = x0 + bw + 2 * grow, y0 + bh + 2 * grow, z0 + bd + 2 * grow
        # (texture box, origin, U, V, normal, light): u to the right on the texture, v down it.
        spec = [
            ((u + bd, v, u + bd + bw, v + bd), (x0, y1, z0), (x1 - x0, 0, 0), (0, 0, z1 - z0), (0, 1, 0), 1.0),
            ((u + bd, v + bd, u + bd + bw, v + bd + bh), (x0, y1, z1), (x1 - x0, 0, 0), (0, -(y1 - y0), 0), (0, 0, 1), 0.9),
            ((u, v + bd, u + bd, v + bd + bh), (x0, y1, z0), (0, 0, z1 - z0), (0, -(y1 - y0), 0), (-1, 0, 0), 0.76),
            ((u + bd + bw, v + bd, u + 2 * bd + bw, v + bd + bh), (x1, y1, z1), (0, 0, -(z1 - z0)), (0, -(y1 - y0), 0),
             (1, 0, 0), 0.76),
            ((u + 2 * bd + bw, v + bd, u + 2 * bd + 2 * bw, v + bd + bh), (x1, y1, z0), (-(x1 - x0), 0, 0),
             (0, -(y1 - y0), 0), (0, 0, -1), 0.7),
        ]
        for box, origin, U, V, normal, light in spec:
            if rot(normal)[2] <= 1e-6:
                continue                                   # facing away
            tex = skin.crop(box)
            if tex.getbbox() is None:
                continue                                   # nothing drawn there (an empty outer layer)
            o, ru, rv = rot(origin), rot(U), rot(V)
            centre = rot(tuple(origin[i] + U[i] / 2 + V[i] / 2 for i in range(3)))
            faces.append((centre[2], tex, o, ru, rv, light))
    for _, tex, o, ru, rv, light in sorted(faces, key=lambda f: f[0]):
        tw, th = tex.size
        X0, Y0 = scale * o[0] + cx, -scale * o[1] + cy
        a = (scale * ru[0] / tw, -scale * ru[1] / tw)        # one texel along u, on the canvas
        b = (scale * rv[0] / th, -scale * rv[1] / th)        # and along v
        det = a[0] * b[1] - b[0] * a[1]
        if abs(det) < 1e-9:
            continue
        m00, m01, m10, m11 = b[1] / det, -b[0] / det, -a[1] / det, a[0] / det
        coeffs = (m00, m01, -(m00 * X0 + m01 * Y0), m10, m11, -(m10 * X0 + m11 * Y0))
        if light < 1.0:
            r, g, bl, al = tex.split()
            tex = Image.merge("RGBA", tuple(c.point(lambda q: int(q * light)) for c in (r, g, bl)) + (al,))
        canvas.alpha_composite(tex.transform(canvas.size, Image.AFFINE, coeffs, resample=Image.NEAREST,
                                             fillcolor=(0, 0, 0, 0)))
    box = canvas.getbbox()
    return canvas.crop(box) if box else canvas


def portrait(body, size: int = 256):
    """Head and shoulders out of the standing figure, square, for a round picture."""
    from PIL import Image
    w, h = body.size
    top = int(h * 0.02)
    side = min(w, int(h * 0.56))
    left = max(0, (w - side) // 2)
    crop = body.crop((left, top, left + side, top + side))
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.alpha_composite(crop)
    return out.resize((size, size), Image.LANCZOS)


def save_picture(account: int, name: str, timeout: float = 8.0) -> dict:
    """The account's picture made from its skin and kept beside its identity (config/identity_minecraft_<n>), for its
    card. What it is made from comes back: {"ok", "source", "skin"}."""
    found = lookup(name, timeout)
    if not found["png"]:
        return {"ok": False, "source": found["source"], "skin": found["skin"]}
    return keep_picture(account, name, found["png"], found["slim"], found["source"], found["skin"])


def save_player_picture(account: int, uid: str, name: str, folder, timeout: float = 8.0) -> str:
    """Someone else's picture, drawn from their skin the way the account's own is, kept where the panel finds a chat's
    picture (snappeople.picture_path). Its file's name, "" with nothing to draw from. A file with the same picture is
    left alone: the panel's address for it changes when the file does."""
    found = lookup(name, timeout)
    if not found["png"]:
        return ""
    buf = io.BytesIO()
    portrait(render(found["png"], found["slim"], scale=12), 128).save(buf, "PNG", optimize=True)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    file = f"{int(account)}_{uid}.png"
    path = folder / file
    if not path.exists() or path.read_bytes() != buf.getvalue():
        path.write_bytes(buf.getvalue())
    return file


def skin_size(png: bytes) -> tuple[int, int] | None:
    """A PNG's width and height, from its header; None for anything that is not a PNG."""
    if len(png) < 24 or png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        return None
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def keep_picture(account: int, name: str, png: bytes, slim: bool, source: str, skin: str = "") -> dict:
    """The card's picture drawn from a skin already in hand (one just put on the account, say), rather than asked of
    Mojang, which goes on serving the old one for a while after a change."""
    from PIL import Image  # noqa: F401  (Pillow there, or nothing to draw with)
    from app.utils.atomic import write_json_atomic
    from app.utils.paths import DATA_DIR
    found = {"png": png, "slim": bool(slim), "source": source, "skin": skin}
    body = render(found["png"], found["slim"])
    cfg = DATA_DIR / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    stem = f"identity_minecraft_{int(account)}"
    buf = io.BytesIO()
    portrait(body).save(buf, "PNG", optimize=True)
    pic = cfg / f"{stem}.png"
    if not pic.exists() or pic.read_bytes() != buf.getvalue():
        pic.write_bytes(buf.getvalue())
    full = io.BytesIO()
    body.resize((body.width // 3, body.height // 3), Image.LANCZOS).save(full, "PNG", optimize=True)
    (cfg / f"{stem}_body.png").write_bytes(full.getvalue())
    info = cfg / f"{stem}.json"
    try:
        data = json.loads(info.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data.setdefault("username", name)
    data.setdefault("display_name", name)
    data.update(picture=pic.name, skin=found["skin"] or "", skin_source=found["source"], slim=found["slim"])
    write_json_atomic(info, data)
    return {"ok": True, "source": found["source"], "skin": found["skin"]}
