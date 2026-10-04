"""Looks and touches for the bot's pictures.

Looks are a picture's colours changed the way a phone's filters change them (warm, golden hour, film, black and
white...), made with Pillow alone: numpy is kept out of the exe on purpose (packaging/specparts.py). A look goes on the
picture the bot sends, and the untouched original is kept beside it, so a look can be changed or taken off again
(app/web/routes/media_routes.py).

Touches are what a person puts on a selfie before sending it on Snapchat: a caption bar, big text, the time, the day,
an emoji, a look. The model decides them as a picture goes out (plan_touch), on the accounts chosen in Settings
(bot.pictures.touches), and they are drawn here (draw_touch) on a copy, never on the picture itself. The letters are
Windows' own Segoe UI; the emoji are Apple's, as an iPhone shows them (apple_emoji), with Windows' own Segoe UI Emoji
standing in for one that cannot be had.
"""

import io
import json
import os
import random
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

# id -> name, in the order the page shows them, a group at a time (GROUP_OF). The first twelve were colour and
# contrast mostly; the moods were asked for, the way Snapchat's filters change how a picture feels: a film still's
# teal and orange, a daydream's haze, a sunset over everything, a disposable camera's flash.
LOOKS: dict[str, str] = {
    "warm": "Warm",
    "golden": "Golden hour",
    "rosy": "Rosy",
    "cool": "Cool",
    "vivid": "Vivid",
    "soft": "Soft glow",
    "cinematic": "Cinematic",
    "dreamy": "Dreamy",
    "sunset": "Sunset",
    "moody": "Moody",
    "night": "Night",
    "neon": "Neon",
    "y2k": "Y2K",
    "film": "Film",
    "vintage": "Vintage",
    "faded": "Faded",
    "polaroid": "Polaroid",
    "disposable": "Disposable",
    "lomo": "Lomo",
    "matte": "Matte",
    "mono": "B&W",
    "noir": "Noir",
    "silver": "Silver",
    "sepia": "Sepia",
}
GROUPS = ("Colour", "Mood", "Film", "Black & white")
GROUP_OF: dict[str, str] = {
    **dict.fromkeys(("warm", "golden", "rosy", "cool", "vivid", "soft"), "Colour"),
    **dict.fromkeys(("cinematic", "dreamy", "sunset", "moody", "night", "neon", "y2k"), "Mood"),
    **dict.fromkeys(("film", "vintage", "faded", "polaroid", "disposable", "lomo", "matte"), "Film"),
    **dict.fromkeys(("mono", "noir", "silver", "sepia"), "Black & white"),
}

# What the AI may put on a picture as it sends it, as Settings lists them.
TOUCH_KINDS = ("caption", "big_text", "time", "day", "emoji", "look")
AUTO_MODES = ("off", "one", "random", "ai")
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
CAPTION_POS = {"upper": 0.3, "middle": 0.55, "lower": 0.74}
BIG_TEXT_POS = {"top": 0.07, "middle": 0.4, "bottom": 0.7}


class Animated(ValueError):
    """A moving picture: a look would keep only its first frame, so it is left as it is."""


# ── Curves ────────────────────────────────────────────────────────────────────

def _lut(fn) -> list:
    return [max(0, min(255, int(round(fn(v))))) for v in range(256)]


def _channels(img: Image.Image, r=None, g=None, b=None) -> Image.Image:
    """Each channel through its own curve, a function of 0..255."""
    same = list(range(256))
    return img.point((_lut(r) if r else same) + (_lut(g) if g else same) + (_lut(b) if b else same))


def _s_curve(k: float):
    """Deeper shadows and brighter highlights by k, the ends left where they are."""
    import math
    return lambda v: 255 * ((v / 255) - k * math.sin(2 * math.pi * v / 255) / (2 * math.pi))


def _vignette(img: Image.Image, amount: float) -> Image.Image:
    """Darker towards the corners, the middle untouched."""
    mask = Image.radial_gradient("L").resize(img.size, Image.BILINEAR)
    # Eased in, so no edge shows where the darkening starts.
    shade = mask.point(lambda v: 255 - int(amount * 255 * (max(0.0, v - 60) / 195) ** 1.8))
    return ImageChops.multiply(img, Image.merge("RGB", (shade, shade, shade)))


def _grain(img: Image.Image, amount: float) -> Image.Image:
    """Film grain: noise laid over the picture, neutral grey changing nothing."""
    noise = Image.effect_noise(img.size, 28 + 30 * amount)
    grained = ImageChops.overlay(img, Image.merge("RGB", (noise, noise, noise)))
    return Image.blend(img, grained, min(1.0, 0.35 * amount))


def _glow(img: Image.Image, amount: float) -> Image.Image:
    """A soft bloom: the picture screened over a blurred copy of itself."""
    blurred = img.filter(ImageFilter.GaussianBlur(max(2, min(img.size) // 50)))
    return Image.blend(img, ImageChops.screen(img, blurred), amount)


def _tone(img: Image.Image, shadow: tuple, highlight: tuple, amount: float, mid: tuple | None = None) -> Image.Image:
    """Split toning, how a grade changes a picture's mood: the shadows towards one colour and the light towards
    another (and the middle towards a third, given one), laid on as soft light so the picture's own detail stays."""
    tones = ImageOps.colorize(ImageOps.grayscale(img), black=shadow, white=highlight, mid=mid)
    return Image.blend(img, ImageChops.soft_light(img, tones), amount)


def _sky(img: Image.Image, top: tuple, bottom: tuple, amount: float) -> Image.Image:
    """A wash of colour down the picture, one colour at the top to another at the foot, as soft light."""
    down = Image.linear_gradient("L").resize(img.size, Image.BILINEAR)
    return Image.blend(img, ImageChops.soft_light(img, ImageOps.colorize(down, black=top, white=bottom)), amount)


# ── The looks ─────────────────────────────────────────────────────────────────

def _warm(im):
    im = _channels(im, r=lambda v: v * 1.06 + 6, g=lambda v: v * 1.01 + 2, b=lambda v: v * 0.88)
    return ImageEnhance.Color(im).enhance(1.08)


def _golden(im):
    im = _channels(im, r=lambda v: v * 1.08 + 10, g=lambda v: v * 1.02 + 5, b=lambda v: v * 0.8)
    return _glow(ImageEnhance.Contrast(im).enhance(1.05), 0.22)


def _rosy(im):
    im = _channels(im, r=lambda v: v * 1.05 + 8, g=lambda v: v * 0.97, b=lambda v: v * 1.02 + 6)
    return ImageEnhance.Color(im).enhance(1.05)


def _cool(im):
    im = _channels(im, r=lambda v: v * 0.92, g=lambda v: v + 2, b=lambda v: v * 1.08 + 8)
    return ImageEnhance.Color(im).enhance(0.96)


def _night(im):
    s = _s_curve(0.3)
    im = _channels(im, r=lambda v: s(v) * 0.85, g=lambda v: s(v) * 0.92, b=lambda v: s(v) * 1.04 + 6)
    return _vignette(ImageEnhance.Brightness(im).enhance(0.9), 0.45)


def _vivid(im):
    return ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.4)).enhance(1.12)


def _soft(im):
    return ImageEnhance.Contrast(_glow(im, 0.55)).enhance(0.94)


def _faded(im):
    lift = lambda v: 24 + v * 0.86  # noqa: E731
    return ImageEnhance.Color(_channels(im, lift, lift, lift)).enhance(0.82)


def _vintage(im):
    im = _channels(im, r=lambda v: 26 + v * 0.89, g=lambda v: 20 + v * 0.84, b=lambda v: 30 + v * 0.7)
    return _grain(_vignette(ImageEnhance.Color(im).enhance(0.78), 0.35), 0.5)


def _film(im):
    s = _s_curve(0.22)
    im = _channels(im, r=lambda v: s(v) * 0.98 + 4, g=lambda v: s(v) + 6, b=lambda v: s(v) * 0.95 + 10)
    return _grain(ImageEnhance.Color(im).enhance(0.9), 0.8)


def _mono(im):
    return ImageEnhance.Contrast(ImageOps.grayscale(im)).enhance(1.1).convert("RGB")


def _noir(im):
    g = ImageOps.grayscale(im).point(_lut(_s_curve(0.5)))
    return _vignette(ImageEnhance.Contrast(g).enhance(1.25).convert("RGB"), 0.6)


# ── Moods ──

def _cinematic(im):
    # A film still: teal in the shadows, orange where the light and the skin are, the contrast deepened.
    s = _s_curve(0.25)
    im = _channels(_tone(im, (0, 90, 110), (255, 175, 110), 0.85), s, s, s)
    return _vignette(ImageEnhance.Color(im).enhance(0.92), 0.3)


def _dreamy(im):
    # A daydream: a haze of light, the blacks lifted, lavender and pink through it.
    lift = lambda v: 28 + v * 0.86  # noqa: E731
    im = _channels(_glow(im, 0.7), r=lambda v: lift(v) * 1.03 + 4, g=lift, b=lambda v: lift(v) * 1.05 + 8)
    return ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(0.85)).enhance(0.92)


def _sunset(im):
    # The light at the end of the day: orange from the top, pink and purple at the foot, warm over all of it.
    im = _channels(_sky(im, (255, 140, 60), (170, 70, 160), 0.85), r=lambda v: v * 1.04 + 4, b=lambda v: v * 0.94)
    return _glow(ImageEnhance.Color(im).enhance(1.1), 0.18)


def _moody(im):
    # An overcast afternoon: dark and muted, a cold teal in the shadows.
    s = _s_curve(0.35)
    im = _channels(_tone(im, (10, 55, 55), (225, 220, 205), 0.7), s, s, s)
    return _vignette(ImageEnhance.Color(ImageEnhance.Brightness(im).enhance(0.88)).enhance(0.6), 0.5)


def _neon(im):
    # A club at night: purple shadows, cyan light, pink between.
    im = _tone(im, (80, 0, 120), (0, 235, 255), 0.9, mid=(255, 60, 170))
    return ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.3)).enhance(1.08)


def _y2k(im):
    # A digital camera's flash: cold, bright, the blacks crushed, the highlights blooming.
    s = _s_curve(0.4)
    im = _channels(im, r=lambda v: s(v) * 0.94, g=lambda v: s(v) + 2, b=lambda v: s(v) * 1.08 + 10)
    return _vignette(_glow(ImageEnhance.Color(im).enhance(1.1), 0.25), 0.2)


# ── Film ──

def _polaroid(im):
    # An instant photo: cyan in the shadows, cream in the light, faded and soft.
    lift = lambda v: 20 + v * 0.88  # noqa: E731
    im = _channels(_tone(im, (40, 80, 90), (255, 240, 205), 0.75), lift, lift, lift)
    return _glow(ImageEnhance.Color(im).enhance(0.85), 0.15)


def _disposable(im):
    # A disposable camera with its flash on: warm, punchy reds, heavy grain, dark corners.
    s = _s_curve(0.3)
    im = _channels(im, r=lambda v: s(v) * 1.04 + 6, g=lambda v: s(v) + 3, b=lambda v: s(v) * 0.88)
    return _vignette(_grain(ImageEnhance.Color(im).enhance(1.15), 0.95), 0.35)


def _lomo(im):
    # Cross-processed: saturated, deep contrast, blue lifted in the shadows, a heavy dark ring round the edge.
    s = _s_curve(0.45)
    im = _channels(im, r=s, g=lambda v: s(v) * 1.02, b=lambda v: 22 + v * 0.82)
    return _vignette(ImageEnhance.Color(im).enhance(1.35), 0.7)


def _matte(im):
    # Flat and calm: the blacks lifted to grey, the whites held down, the colour quietened.
    flat = lambda v: 30 + v * 0.8  # noqa: E731
    return ImageEnhance.Color(_channels(im, flat, flat, flat)).enhance(0.85)


# ── Black and white ──

def _silver(im):
    # Bright, soft black and white with a cool tint and a glow: airy rather than hard.
    g = ImageOps.grayscale(im).point(_lut(lambda v: 18 + v * 0.93))
    return _glow(ImageOps.colorize(g, black=(14, 17, 22), white=(250, 252, 255)), 0.3)


def _sepia(im):
    # The old brown photograph.
    g = ImageEnhance.Contrast(ImageOps.grayscale(im)).enhance(1.05)
    return _vignette(ImageOps.colorize(g, black=(38, 24, 12), white=(255, 240, 210), mid=(165, 120, 78)), 0.25)


_FUNCS = {"warm": _warm, "golden": _golden, "rosy": _rosy, "cool": _cool, "night": _night, "vivid": _vivid,
          "soft": _soft, "faded": _faded, "vintage": _vintage, "film": _film, "mono": _mono, "noir": _noir,
          "cinematic": _cinematic, "dreamy": _dreamy, "sunset": _sunset, "moody": _moody, "neon": _neon, "y2k": _y2k,
          "polaroid": _polaroid, "disposable": _disposable, "lomo": _lomo, "matte": _matte, "silver": _silver,
          "sepia": _sepia}


def apply_look(img: Image.Image, look: str, strength: float = 1.0) -> Image.Image:
    """The picture with this look on it, `strength` of the way from the original (0) to the full look (1). Transparency
    is kept."""
    fn = _FUNCS.get(look or "")
    strength = max(0.0, min(1.0, float(strength or 0)))
    if not fn or strength <= 0:
        return img
    alpha = None
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        alpha, base = rgba.getchannel("A"), rgba.convert("RGB")
    else:
        base = img.convert("RGB")
    done = fn(base)
    if strength < 1:
        done = Image.blend(base, done, strength)
    if alpha is not None:
        done = done.convert("RGBA")
        done.putalpha(alpha)
    return done


# ── Reading and writing ───────────────────────────────────────────────────────

def _open(data: bytes, draft: int = 0) -> Image.Image:
    """A picture, upright. `draft` asks a JPEG to decode at about that size, which is most of the work for a preview."""
    from app.utils.imageimport import _ensure_openers
    _ensure_openers()
    img = Image.open(io.BytesIO(data))
    if getattr(img, "n_frames", 1) > 1:
        raise Animated("animated pictures can't take a filter")
    if draft and img.format == "JPEG":
        img.draft("RGB", (draft, draft))
    img.load()
    return ImageOps.exif_transpose(img)


def _has_alpha(img: Image.Image) -> bool:
    if img.mode not in ("RGBA", "LA", "PA"):
        return False
    lo, _hi = img.getchannel("A").getextrema()
    return lo < 255


def _flat(img: Image.Image) -> Image.Image:
    """No transparency: laid on white, as a sent JPEG would show it."""
    if img.mode in ("RGBA", "LA", "PA"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def encode(img: Image.Image, ext: str) -> tuple[bytes, str]:
    """Bytes in the picture's own format where that can hold the result, and the extension they are. A PNG too big to
    attach becomes a JPEG, as an import would make it (app/utils/imageimport.py)."""
    from app.utils.imageimport import TARGET_MAX_BYTES
    ext = (ext or "").lower()
    out = io.BytesIO()
    if ext in (".jpg", ".jpeg"):
        _flat(img).save(out, "JPEG", quality=92, optimize=True, progressive=True)
        return out.getvalue(), ext
    if ext == ".webp":
        img.save(out, "WEBP", quality=92, method=4)
        return out.getvalue(), ".webp"
    img.save(out, "PNG", compress_level=6)
    if out.tell() <= TARGET_MAX_BYTES:
        return out.getvalue(), ".png"
    for quality in (90, 80, 70):
        out = io.BytesIO()
        _flat(img).save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        if out.tell() <= TARGET_MAX_BYTES:
            break
    return out.getvalue(), ".jpg"


def render(data: bytes, ext: str, look: str, strength: float) -> tuple[bytes, str]:
    """The picture in these bytes with a look on it, as bytes and their extension. Raises Animated for a moving one."""
    return encode(apply_look(_open(data), look, strength), ext)


# A preview is asked for twelve times at once (every look on one picture): the picture is decoded once, small, and the
# looks are put on that.
_BASES: OrderedDict = OrderedDict()
_PREVIEWS: OrderedDict = OrderedDict()


def _remember(cache: OrderedDict, key, value, keep: int):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > keep:
        cache.popitem(last=False)
    return value


def preview(data: bytes, cache_key: str, look: str, strength: float, width: int) -> bytes:
    """A small JPEG of the picture with this look, for the page to show. A moving picture shows its first frame."""
    key = (cache_key, look, round(float(strength), 2), int(width))
    hit = _PREVIEWS.get(key)
    if hit is not None:
        _PREVIEWS.move_to_end(key)
        return hit
    base_key = (cache_key, int(width))
    base = _BASES.get(base_key)
    if base is None:
        try:
            img = _open(data, draft=width * 2)
        except Animated:
            img = Image.open(io.BytesIO(data))
            img.seek(0)
            img = img.convert("RGBA")
        img.thumbnail((width, width * 3), Image.LANCZOS)
        base = _remember(_BASES, base_key, img.copy(), 24)
    shown = apply_look(base, look, strength) if look else base
    out = io.BytesIO()
    _flat(shown).save(out, "JPEG", quality=84)
    return _remember(_PREVIEWS, key, out.getvalue(), 240)


_demo: list = []


def demo_scene() -> bytes:
    """A made-up picture to show a filter on when there is none of yours: a sunset over hills, a figure on them. Drawn
    once, as a JPEG."""
    if _demo:
        return _demo[0]
    w, h = 540, 720
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(250 - 70 * t), int(170 - 40 * t), int(120 + 90 * t)))
    d.ellipse((330, 170, 450, 290), fill=(255, 226, 150))
    d.polygon([(0, 470), (150, 400), (300, 455), (420, 410), (w, 445), (w, h), (0, h)], fill=(70, 120, 95))
    d.polygon([(0, 560), (200, 500), (380, 545), (w, 515), (w, h), (0, h)], fill=(45, 90, 70))
    d.ellipse((232, 380, 288, 436), fill=(232, 182, 150))
    d.rounded_rectangle((222, 436, 298, 590), 22, fill=(210, 80, 110))
    out = io.BytesIO()
    img.filter(ImageFilter.GaussianBlur(0.8)).save(out, "JPEG", quality=90)
    _demo.append(out.getvalue())
    return _demo[0]


# ── Settings ──────────────────────────────────────────────────────────────────

def _pictures_cfg() -> dict:
    try:
        from app.utils.helpers import load_config
        return ((load_config().get("bot") or {}).get("pictures") or {})
    except Exception:
        return {}


def _num(value, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def auto_look_cfg() -> dict:
    """bot.pictures.auto_look, filled in: what is put on a new picture."""
    raw = _pictures_cfg().get("auto_look") or {}
    mode = raw.get("mode")
    mode = "off" if mode in (None, False) else str(mode).strip().lower()
    look = str(raw.get("look") or "")
    return {
        "mode": mode if mode in AUTO_MODES else "off",
        "look": look if look in LOOKS else "warm",
        "looks": [str(x) for x in (raw.get("looks") or []) if str(x) in LOOKS],
        "strength": _num(raw.get("strength"), 0.7, 0.05, 1.0),
        "vary": _num(raw.get("vary"), 0.1, 0.0, 0.5),
    }


def touches_cfg() -> dict:
    """bot.pictures.touches, filled in: which accounts may add touches, how often, and which kinds."""
    raw = _pictures_cfg().get("touches") or {}
    kinds = raw.get("kinds")
    kinds = [k for k in (kinds if isinstance(kinds, list) else TOUCH_KINDS) if k in TOUCH_KINDS]
    return {
        "accounts": [str(a) for a in (raw.get("accounts") or []) if a],
        "chance": _num(raw.get("chance"), 0.5, 0.0, 1.0),
        "kinds": kinds,
    }


def varied(strength: float, vary: float) -> float:
    return round(max(0.05, min(1.0, strength + random.uniform(-vary, vary))), 2)


def pick_auto(cfg: dict | None = None) -> tuple[str, float]:
    """For the modes that need no model: the look a new picture gets, and how strong. ("", 0) when it gets none."""
    cfg = cfg or auto_look_cfg()
    if cfg["mode"] == "one":
        return cfg["look"], varied(cfg["strength"], cfg["vary"])
    if cfg["mode"] == "random":
        return random.choice(cfg["looks"] or list(LOOKS)), varied(cfg["strength"], cfg["vary"])
    return "", 0.0


# ── Asking the model ──────────────────────────────────────────────────────────

def _json_object(text: str) -> dict:
    text = (text or "").replace("```json", "").replace("```", "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _look_id(value) -> str:
    """A look the model named, by id or by the name the page shows ("Golden hour", "b&w")."""
    v = str(value or "").strip().lower()
    if v in LOOKS:
        return v
    for lid, name in LOOKS.items():
        if v == name.lower():
            return lid
    return {"black and white": "mono", "bw": "mono", "golden_hour": "golden", "soft_glow": "soft"}.get(v, "")


async def _small(system: str, prompt: str, max_tokens: int) -> str:
    from app.utils.ai import _create_small_completion
    try:
        resp = await _create_small_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens=max_tokens, temperature=0.8)
    except SystemExit:
        # init_ai() leaves a runner with no model at all; here, in the panel, it is only "no model".
        raise RuntimeError("no model is set up yet")
    return resp.choices[0].message.content or ""


async def ai_pick_look(description: str) -> str:
    """The look the utility model thinks suits a picture, from what it shows; "" when it can't say."""
    names = ", ".join(f"{lid} ({name})" for lid, name in LOOKS.items())
    try:
        text = await _small(
            "You pick a photo filter. You answer with one JSON object and nothing else.",
            f"A photo: {description or 'a selfie'}\nWhich one of these filters suits it best: {names}?\n"
            'Answer exactly: {"look": "<id>"}', 40)
    except Exception:
        return ""
    return _look_id(_json_object(text).get("look"))


_URL = re.compile(r"https?://\S+|www\.\S+", re.I)


def _words(value, limit: int) -> str:
    """Text the model wants on a picture: one line, no links or @names, and at most `limit` characters, cut between
    words."""
    if not isinstance(value, str):
        return ""
    text = _URL.sub("", value)
    text = re.sub(r"(?<!\w)@\w+", "", text)
    text = " ".join(text.split()).strip().strip("\"'“”‘’")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:-")
    if not text:
        return ""
    try:
        from app.core.engine import is_refusal
        if is_refusal(text):
            return ""
    except Exception:
        pass
    return text


def clean_touch(raw: dict, allowed) -> dict:
    """What the model asked for, kept to what is allowed and what can be drawn."""
    if not isinstance(raw, dict):
        return {}
    allowed = set(allowed or ())
    spec: dict = {}
    if "caption" in allowed:
        text = _words(raw.get("caption"), 60)
        if text:
            spec["caption"] = text
            pos = str(raw.get("caption_pos") or "")
            spec["caption_pos"] = pos if pos in CAPTION_POS else "middle"
    if "big_text" in allowed:
        text = _words(raw.get("big_text"), 40)
        if text:
            spec["big_text"] = text
            pos = str(raw.get("big_text_pos") or "")
            spec["big_text_pos"] = pos if pos in BIG_TEXT_POS else "top"
    if "time" in allowed and raw.get("time") is True:
        spec["time"] = True
    if "day" in allowed and raw.get("day") is True:
        spec["day"] = True
    if spec.get("time") or spec.get("day"):
        pos = str(raw.get("sticker_pos") or "")
        spec["sticker_pos"] = pos if pos in CORNERS else "top-right"
    if "emoji" in allowed:
        em = raw.get("emoji")
        em = [em] if isinstance(em, str) else (em if isinstance(em, list) else [])
        kept = []
        for e in em:
            e = "".join(ch for ch in str(e) if _is_emoji(ch))[:8]
            if e and any(_is_emoji(ch) and ord(ch) not in _JOINERS for ch in e):
                kept.append(e)
        if kept:
            spec["emoji"] = kept[:3]
            pos = str(raw.get("emoji_pos") or "")
            other = {"top-left": "bottom-right", "top-right": "bottom-left",
                     "bottom-left": "top-right", "bottom-right": "top-left"}.get(spec.get("sticker_pos", ""), "bottom-right")
            spec["emoji_pos"] = pos if pos in CORNERS and pos != spec.get("sticker_pos") else other
    if "look" in allowed:
        look = _look_id(raw.get("look"))
        if look:
            spec["look"] = look
    return spec


async def plan_touch(description: str, recent: list, reply: str, lang: str, allowed, their_name: str = "",
                     platform: str = "", strict: bool = False) -> dict:
    """What the model would put on this picture as it sends it, if anything: {} for nothing. One small JSON call; any
    trouble is nothing, so the picture still goes out (strict raises it instead, for a preview to say why)."""
    allowed = [k for k in TOUCH_KINDS if k in set(allowed or ())]
    if not allowed:
        return {}
    from app.utils.languages import language_name
    try:
        from app.utils.helpers import load_instructions
        persona = " ".join((load_instructions() or "").split())[:600]
    except Exception:
        persona = ""
    language = language_name(lang or "en", "English")
    fields = {
        "caption": ('"caption": a few words for the caption bar across the photo, or null',
                    '"caption_pos": "upper" | "middle" | "lower"'),
        "big_text": ('"big_text": a word or a few in big letters, or null',
                     '"big_text_pos": "top" | "middle" | "bottom"'),
        "time": ('"time": true to put the time on it, else false', '"sticker_pos": "top-left" | "top-right" | '
                 '"bottom-left" | "bottom-right"'),
        "day": ('"day": true to put the day of the week on it, else false', ""),
        "emoji": ('"emoji": a list of 1 to 3 emoji to stick on it, or []', '"emoji_pos": a corner, as for sticker_pos'),
        "look": (f'"look": one of {", ".join(LOOKS)}, or null', ""),
    }
    lines = []
    for k in allowed:
        lines += [f for f in fields[k] if f]
    chat = "\n".join(str(x) for x in (recent or [])[-8:] if x) or "(nothing yet)"
    prompt = (
        f"You are the person in this photo, about to send it{f' to {their_name}' if their_name else ''}"
        f"{f' on {platform}' if platform else ''}.\n"
        f"The photo: {description or 'a selfie'}\n"
        + (f"Who you are: {persona}\n" if persona else "")
        + f"The chat, latest last:\n{chat}\n"
        + (f'Your message going with it: "{reply}"\n' if reply else "")
        + "\nReal people usually add one thing, sometimes two, and often nothing: a short caption; or the time, maybe "
        "with the day; or an emoji or two; big text for a strong reaction; a filter now and then. Choose what you "
        f"would add this time, if anything. Few words, casual, in {language}, the way you text. Never repeat your "
        "message, never describe the photo, no hashtags, no links.\n"
        "Answer with one JSON object using only these keys:\n" + "\n".join(lines)
    )
    try:
        text = await _small("You decide how someone decorates a photo before sending it, the way people do on "
                            "Snapchat. You answer with one JSON object and nothing else.", prompt, 220)
    except Exception:
        if strict:
            raise
        return {}
    return clean_touch(_json_object(text), allowed)


def describe_touch(spec: dict) -> str:
    """What a touch added, for the log: "a caption, the time and an emoji"."""
    parts = []
    if spec.get("look"):
        parts.append(f"the {LOOKS[spec['look']]} filter")
    if spec.get("caption"):
        parts.append("a caption")
    if spec.get("big_text"):
        parts.append("big text")
    if spec.get("time"):
        parts.append("the time")
    if spec.get("day"):
        parts.append("the day")
    if spec.get("emoji"):
        parts.append("an emoji" if len(spec["emoji"]) == 1 else "emoji")
    if not parts:
        return "nothing"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


# ── Drawing ───────────────────────────────────────────────────────────────────

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_FONT_FILES = {
    "regular": ("segoeui.ttf", "arial.ttf"),
    "bold": ("segoeuib.ttf", "arialbd.ttf"),
    "semibold": ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"),
    "emoji": ("seguiemj.ttf",),
}
_fonts: dict = {}
# The caption and the big text are set in Inter (resources/fonts, SIL Open Font License), the free face closest to the
# San Francisco an iPhone writes them in: in Segoe UI they read as made on a PC, "edited". (weight, optical size).
_INTER = {"caption": (460, 18), "big": (720, 28)}


def _inter(kind: str, size: int):
    """Inter at this kind's weight, or None when the file is missing or unreadable."""
    from app.utils.paths import APP_DIR
    try:
        tf = ImageFont.truetype(str(APP_DIR / "resources" / "fonts" / "Inter-Variable.ttf"), size)
        wght, opsz = _INTER[kind]
        values = []
        for axis in tf.get_variation_axes():
            name = axis.get("name", b"")
            name = (name.decode("ascii", "replace") if isinstance(name, bytes) else str(name)).lower()
            values.append(wght if "weight" in name else opsz if "optical" in name else axis.get("default", 0))
        tf.set_variation_by_axes(values)
        return tf
    except Exception:
        return None


def _font(kind: str, size: int):
    """Windows' own font of this kind at this size; Pillow's own for text when that is missing, None for emoji."""
    size = max(8, int(size))
    key = (kind, size)
    if key in _fonts:
        return _fonts[key]
    if kind in _INTER:
        found = _inter(kind, size)
        if found is not None:
            _fonts[key] = found
            return found
        kind = "regular" if kind == "caption" else "bold"
    found = None
    for name in _FONT_FILES[kind]:
        path = os.path.join(_FONT_DIR, name)
        if os.path.exists(path):
            try:
                found = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
    if found is None and kind != "emoji":
        found = ImageFont.load_default(size=size)
    _fonts[key] = found
    return found


_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x2300, 0x23FF), (0x3030, 0x3030),
                 (0x303D, 0x303D), (0x3297, 0x3299), (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x2122, 0x2122))
# What changes the emoji before it: a variation selector, a skin tone, a keycap, a flag's tags.
_MODIFIERS = {0xFE0F, 0xFE0E, 0x20E3, *range(0x1F3FB, 0x1F400), *range(0xE0020, 0xE0080)}
_JOINERS = {0x200D, *_MODIFIERS}


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return cp in _JOINERS or any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _starts_emoji(ch: str) -> bool:
    return _is_emoji(ch) and ord(ch) not in _JOINERS


def _pieces(text: str) -> list:
    """The text as pieces to draw: (False, letters) and (True, one emoji with what joins onto it: a skin tone, the
    rest of a ZWJ sequence, a flag's second letter)."""
    out: list = []
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        if _starts_emoji(text[i]):
            j = i + 1
            if 0x1F1E6 <= cp <= 0x1F1FF and j < n and 0x1F1E6 <= ord(text[j]) <= 0x1F1FF:
                j += 1
            while j < n:
                c = ord(text[j])
                if c in _MODIFIERS:
                    j += 1
                elif c == 0x200D and j + 1 < n:
                    j += 2
                else:
                    break
            out.append((True, text[i:j]))
            i = j
            continue
        j = i + 1
        while j < n and not _starts_emoji(text[j]):
            j += 1
        letters = "".join(ch for ch in text[i:j] if ord(ch) not in _JOINERS)
        if letters:
            if out and not out[-1][0]:
                out[-1] = (False, out[-1][1] + letters)
            else:
                out.append((False, letters))
        i = j
    return out


# ── Apple's emoji ─────────────────────────────────────────────────────────────
# The emoji on a picture are Apple's, as an iPhone shows them: 160px images from the emoji-data project
# (github.com/iamcal/emoji-data, pinned at v15.1.2), fetched once each as they are first needed and kept under
# cache/emoji_apple. The artwork is Apple's (© Apple Inc., not licensed for commercial use), so the app ships none of it:
# this machine fetches what it uses. Offline, or for an emoji that set does not have, Windows' own Segoe UI Emoji draws
# it instead, and Apple's is looked for again the next time.
_APPLE_SOURCES = (
    "https://cdn.jsdelivr.net/gh/iamcal/emoji-data@v15.1.2/img-apple-160/{name}.png",
    "https://raw.githubusercontent.com/iamcal/emoji-data/v15.1.2/img-apple-160/{name}.png",
)
_apple_missing: set = set()
_apple_images: OrderedDict = OrderedDict()
_tiles: OrderedDict = OrderedDict()


def _apple_dir():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "emoji_apple"


def _fetch_apple(name: str) -> tuple[int, bytes]:
    """One emoji's image from the first source that has it: (200, the PNG), (404, b"") when none has it, or (0, b"")
    when none could be reached."""
    import httpx
    status = 0
    for url in _APPLE_SOURCES:
        try:
            r = httpx.get(url.format(name=name), timeout=8, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
        except Exception:
            continue
        if r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n":
            return 200, r.content
        if r.status_code == 404:
            status = 404
    return status, b""


def _emoji_names(cluster: str) -> list:
    """The file names an emoji may go by: as written, with the emoji presentation selector (❤ is 2764-fe0f), and
    without any."""
    cps = [ord(c) for c in cluster]
    name = lambda seq: "-".join(f"{c:x}" for c in seq)  # noqa: E731
    out = [name(cps)]
    if 0xFE0F not in cps:
        out.append(name([cps[0], 0xFE0F, *cps[1:]]))
    out.append(name([c for c in cps if c != 0xFE0F]))
    return [n for n in dict.fromkeys(out) if n]


def apple_emoji(cluster: str):
    """Apple's image of one emoji (RGBA, 160px), or None to draw it another way."""
    hit = _apple_images.get(cluster)
    if hit is not None:
        return hit
    folder = _apple_dir()
    for name in _emoji_names(cluster):
        if name in _apple_missing:
            continue
        path = folder / f"{name}.png"
        if path.is_file():
            data = path.read_bytes()
        else:
            status, data = _fetch_apple(name)
            if status == 404:
                _apple_missing.add(name)
                continue
            if status != 200:
                return None            # unreachable: Windows' own this time, Apple's looked for again next time
            try:
                folder.mkdir(parents=True, exist_ok=True)
                tmp = folder / f"{name}.{uuid.uuid4().hex[:8]}.part"
                tmp.write_bytes(data)
                os.replace(tmp, path)
            except OSError:
                pass
        try:
            img = Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception:
            continue
        return _remember(_apple_images, cluster, img, 128)
    return None


def _emoji_tile(cluster: str, size: int):
    """One emoji as an image `size` pixels high: Apple's, or Windows' own when Apple's cannot be had (that one is not
    kept, so Apple's is tried again)."""
    key = (cluster, size)
    hit = _tiles.get(key)
    if hit is not None:
        return hit
    src = apple_emoji(cluster)
    if src is not None:
        return _remember(_tiles, key, src.resize((size, size), Image.LANCZOS), 256)
    ef = _font("emoji", size)
    if ef is None:
        return None
    canvas = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((size, size), cluster, font=ef, anchor="mm", embedded_color=True)
    box = canvas.getbbox()
    if not box:
        return None
    tile = canvas.crop(box)
    return tile.resize((max(1, round(tile.width * size / tile.height)), size), Image.LANCZOS)


def _composite(layer: Image.Image, tile: Image.Image, x: float, y: float) -> None:
    """A tile laid over a layer at (x, y), properly blended, whatever of it is off the edge left off."""
    x, y = int(round(x)), int(round(y))
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(tile.width, layer.width - x), min(tile.height, layer.height - y)
    if right > left and bottom > top:
        layer.alpha_composite(tile.crop((left, top, right, bottom)), dest=(x + left, y + top))


def _emoji_em(tf) -> int:
    """How big an emoji sits in a line of this font: a touch taller than its capitals, as on a phone."""
    return max(8, round(getattr(tf, "size", 16) * 1.08))


def _width(text: str, tf) -> float:
    total = 0.0
    em = _emoji_em(tf)
    for is_emoji, piece in _pieces(text):
        if is_emoji:
            tile = _emoji_tile(piece, em)
            total += (tile.width + em * 0.08) if tile is not None else 0
        else:
            total += tf.getlength(piece)
    return total


def _draw_line(layer: Image.Image, x: float, baseline: float, text: str, tf, fill,
               stroke: int = 0, stroke_fill=None) -> None:
    """One line of letters and emoji on a shared baseline."""
    d = ImageDraw.Draw(layer)
    em = _emoji_em(tf)
    for is_emoji, piece in _pieces(text):
        if is_emoji:
            tile = _emoji_tile(piece, em)
            if tile is None:
                continue
            # On the line as a letter is: its foot a little under the baseline.
            _composite(layer, tile, x + em * 0.04, baseline - em * 0.86)
            x += tile.width + em * 0.08
        else:
            d.text((x, baseline), piece, font=tf, anchor="ls", fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
            x += tf.getlength(piece)


def _wrap(text: str, tf, max_w: float) -> list:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if not cur or _width(trial, tf) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit(text: str, kind: str, size: int, max_w: float, max_lines: int):
    """A font and the lines for this text, smaller until it fits in max_lines lines of max_w."""
    floor = max(10, int(size * 0.55))
    while True:
        tf = _font(kind, size)
        lines = _wrap(text, tf, max_w)
        fits = len(lines) <= max_lines and all(_width(ln, tf) <= max_w for ln in lines)
        if fits or size <= floor:
            return tf, lines[:max_lines], size
        size = max(floor, int(size * 0.9))


def _caption_bar(img: Image.Image, text: str, pos: str) -> Image.Image:
    """Snapchat's caption, as an iPhone draws it: a band of half-see-through black across the picture, white words
    centred on it in the phone's own kind of letters, at the phone's proportions (17pt type on a band about 37pt tall,
    across a screen 390pt wide). It was Segoe UI a size smaller on a darker band, and read as edited on a PC."""
    w, h = img.size
    tf, lines, size = _fit(text, "caption", round(w * 0.0436), w * 0.92, 3)
    asc, desc = tf.getmetrics()
    line_h = round((asc + desc) * 1.08)
    pad = round(size * 0.44)
    bar_h = line_h * len(lines) + pad * 2
    top = int(max(0, min(h - bar_h, CAPTION_POS.get(pos, 0.55) * h - bar_h / 2)))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle((0, top, w, top + bar_h), fill=(0, 0, 0, 128))
    y = top + pad + asc
    for line in lines:
        _draw_line(layer, (w - _width(line, tf)) / 2, y, line, tf, (255, 255, 255, 255))
        y += line_h
    return Image.alpha_composite(img, layer)


def _big_text(img: Image.Image, text: str, pos: str) -> Image.Image:
    """Snapchat's big text: large bold white letters, centred, lifted off the picture by a soft shadow. It had a thick
    dark outline, which is a meme's, not Snapchat's."""
    w, h = img.size
    tf, lines, size = _fit(text, "big", round(w * 0.085), w * 0.88, 3)
    asc, desc = tf.getmetrics()
    line_h = round((asc + desc) * 1.02)
    block = line_h * len(lines)
    top = int(max(0, min(h - block, BIG_TEXT_POS.get(pos, 0.07) * h)))
    letters = Image.new("RGBA", img.size, (0, 0, 0, 0))
    y = top + asc
    for line in lines:
        _draw_line(letters, (w - _width(line, tf)) / 2, y, line, tf, (255, 255, 255, 255))
        y += line_h
    # The shadow: the letters' own shape in black, softened and a touch lower, under them.
    alpha = letters.getchannel("A").filter(ImageFilter.GaussianBlur(max(1.5, size * 0.07)))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda a: int(a * 0.5)))
    lifted = Image.new("RGBA", img.size, (0, 0, 0, 0))
    lifted.paste(shadow, (0, max(1, round(size * 0.035))))
    return Image.alpha_composite(Image.alpha_composite(img, lifted), letters)


_DAYS = {
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "fr": ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"),
    "es": ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"),
    "de": ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"),
    "it": ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"),
    "pt": ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"),
    "nl": ("Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"),
}


def persona_now() -> datetime:
    """The time on the persona's own clock (bot.timezone), as the night schedule reads it."""
    now = datetime.now().astimezone()
    try:
        from app.utils.behavior import _local_time
        from app.utils.helpers import load_config
        return _local_time(now, str((load_config().get("bot") or {}).get("timezone") or ""))
    except Exception:
        return now


def clock_text(now: datetime, lang: str) -> str:
    """10:42 in English (no AM/PM, as the sticker shows it), 22:42 everywhere else."""
    if (lang or "en").lower().startswith("en"):
        return f"{now.hour % 12 or 12}:{now.minute:02d}"
    return f"{now.hour:02d}:{now.minute:02d}"


def day_text(now: datetime, lang: str) -> str:
    return _DAYS.get((lang or "en").lower()[:2], _DAYS["en"])[now.weekday()]


def _corner_xy(w: int, h: int, bw: int, bh: int, corner: str) -> tuple[int, int]:
    m = round(w * 0.055)
    x = m if corner.endswith("left") else w - m - bw
    y = round(h * 0.06) if corner.startswith("top") else h - round(h * 0.08) - bh
    return max(0, x), max(0, y)


def _clock_sticker(img: Image.Image, lines: list, corner: str) -> Image.Image:
    """The time and the day, white with a soft shadow, as Snapchat's stickers sit on a picture."""
    w, h = img.size
    fonts = [_font(kind, size) for _t, kind, size in lines]
    widths = [round(f.getlength(t)) for f, (t, _k, _s) in zip(fonts, lines)]
    heights = [round((f.getmetrics()[0] + f.getmetrics()[1]) * 0.95) for f in fonts]
    bw, bh = max(widths), sum(heights)
    x0, y0 = _corner_xy(w, h, bw, bh, corner)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    text = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ds, dt = ImageDraw.Draw(shadow), ImageDraw.Draw(text)
    off = max(1, round(w * 0.004))
    y = y0
    for f, (t, _k, _s), lw, lh in zip(fonts, lines, widths, heights):
        x = x0 if corner.endswith("left") else x0 + bw - lw
        base = y + f.getmetrics()[0]
        ds.text((x + off, base + off * 2), t, font=f, anchor="ls", fill=(0, 0, 0, 140))
        dt.text((x, base), t, font=f, anchor="ls", fill=(255, 255, 255, 255))
        y += lh
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, round(w * 0.006))))
    return Image.alpha_composite(Image.alpha_composite(img, shadow), text)


def _emoji_sticker(img: Image.Image, emoji: list, corner: str) -> Image.Image:
    """One to three emoji, large and a little tilted, from a corner inwards."""
    w, h = img.size
    size = round(w * 0.15)
    clusters = [piece for e in emoji for is_emoji, piece in _pieces(str(e)) if is_emoji][:3]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    step = round(size * 0.9)
    for i, cluster in enumerate(clusters):
        tile = _emoji_tile(cluster, size)
        if tile is None:
            continue
        tile = tile.rotate(random.uniform(-14, 14), resample=Image.BICUBIC, expand=True)
        x, y = _corner_xy(w, h, tile.width, tile.height, corner)
        x = x + i * step if corner.endswith("left") else x - i * step
        _composite(layer, tile, max(0, min(w - tile.width, x)), y)
    return Image.alpha_composite(img, layer)


_OPPOSITE = {"top-left": "bottom-right", "top-right": "bottom-left", "bottom-left": "top-right",
             "bottom-right": "top-left"}


def _free_corner(want: str, taken: set, big: str | None) -> str:
    """The corner wanted, or the nearest one that big text and the other sticker leave free: the same side further
    down (or up) first, then across, then the far corner."""
    want = want if want in CORNERS else "bottom-right"
    v, h = want.split("-")
    flip_v = {"top": "bottom", "bottom": "top"}[v]
    flip_h = {"left": "right", "right": "left"}[h]
    for c in (want, f"{flip_v}-{h}", f"{v}-{flip_h}", f"{flip_v}-{flip_h}"):
        if c in taken or (big == "top" and c.startswith("top")) or (big == "bottom" and c.startswith("bottom")):
            continue
        return c
    return want


def _arrange(spec: dict) -> dict:
    """Where each thing goes, moved apart where two would land on each other: the time under big text across the top,
    the caption off the big text's band, the emoji in a corner of their own."""
    s = dict(spec)
    big = s.get("big_text_pos", "top") if s.get("big_text") else None
    corner = None
    if s.get("time") or s.get("day"):
        corner = _free_corner(s.get("sticker_pos", "top-right"), set(), big)
        s["sticker_pos"] = corner
    if s.get("caption"):
        cap = s.get("caption_pos", "middle")
        cap = {("bottom", "lower"): "upper", ("middle", "middle"): "lower", ("top", "upper"): "middle"}.get((big, cap), cap)
        s["caption_pos"] = cap
    if s.get("emoji"):
        want = s.get("emoji_pos") or (_OPPOSITE.get(corner, "bottom-right") if corner else "bottom-right")
        s["emoji_pos"] = _free_corner(want, {corner} if corner else set(), big)
    return s


_SAMPLE_WORDS = {"en": ("on my way", "hiii"), "fr": ("j'arrive", "coucou"), "es": ("ya voy", "holaa"),
                 "de": ("bin unterwegs", "hallo"), "it": ("sto arrivando", "ciaoo"), "pt": ("tô chegando", "oii"),
                 "nl": ("onderweg", "hoii")}


def sample_touch(kinds, lang: str = "en") -> dict:
    """Every kind allowed at once, to see how each one is drawn: a sample of all of it, not what the AI would do."""
    cap, big = _SAMPLE_WORDS.get((lang or "en").lower()[:2], _SAMPLE_WORDS["en"])
    allowed = set(kinds or ())
    spec: dict = {}
    if "caption" in allowed:
        spec.update(caption=f"{cap} ✨", caption_pos="lower")
    if "big_text" in allowed:
        spec.update(big_text=f"{big} 😘", big_text_pos="top")
    if "time" in allowed:
        spec["time"] = True
    if "day" in allowed:
        spec["day"] = True
    if spec.get("time") or spec.get("day"):
        spec["sticker_pos"] = "top-left"
    if "emoji" in allowed:
        spec.update(emoji=["😍", "🔥"], emoji_pos="bottom-right")
    if "look" in allowed:
        spec["look"] = "warm"
    return spec


def draw_touch(img: Image.Image, spec: dict, lang: str = "en", now: datetime | None = None) -> Image.Image:
    """The picture with what the spec asks for drawn on it: a look first, then words, then stickers, each where nothing
    else is."""
    spec = _arrange(spec)
    if spec.get("look"):
        img = apply_look(img, spec["look"], 0.75)
    out = img.convert("RGBA")
    if spec.get("big_text"):
        out = _big_text(out, spec["big_text"], spec.get("big_text_pos", "top"))
    if spec.get("caption"):
        out = _caption_bar(out, spec["caption"], spec.get("caption_pos", "middle"))
    if spec.get("time") or spec.get("day"):
        now = now or persona_now()
        w = out.width
        lines = []
        if spec.get("time"):
            lines.append((clock_text(now, lang), "bold", round(w * 0.13)))
        if spec.get("day"):
            lines.append((day_text(now, lang), "semibold", round(w * 0.065)))
        out = _clock_sticker(out, lines, spec.get("sticker_pos", "top-right"))
    if spec.get("emoji"):
        out = _emoji_sticker(out, spec["emoji"], spec.get("emoji_pos", "bottom-right"))
    return out


def source_bytes(path: str, spec: dict) -> bytes:
    """What a touch is drawn on: the picture, or its original when the touch brings a look of its own, so two looks
    are never stacked."""
    if spec.get("look"):
        try:
            from app.utils.db import get_picture_look
            from app.utils.helpers import resource_path
            meta = get_picture_look(os.path.basename(path))
            if meta["original"]:
                orig = os.path.join(resource_path("config/pictures_originals"), meta["original"])
                if os.path.isfile(orig):
                    with open(orig, "rb") as fh:
                        return fh.read()
        except Exception:
            pass
    with open(path, "rb") as fh:
        return fh.read()


def shrunk_touch(data: bytes, spec: dict, lang: str, width: int) -> bytes:
    """A touch drawn at full size, then made small, as a JPEG for the page to show."""
    img = draw_touch(_open(data), spec, lang)
    img.thumbnail((width, width * 3), Image.LANCZOS)
    out = io.BytesIO()
    _flat(img).save(out, "JPEG", quality=86)
    return out.getvalue()


def render_touch(data: bytes, spec: dict, lang: str = "en") -> tuple[bytes, str]:
    """A picture's bytes with a touch drawn on, as a JPEG (a PNG where it is see-through)."""
    img = _open(data)
    keep_alpha = _has_alpha(img.convert("RGBA")) if img.mode in ("RGBA", "LA", "PA", "P") else False
    out = draw_touch(img, spec, lang)
    return encode(out if keep_alpha else out.convert("RGB"), ".png" if keep_alpha else ".jpg")


# ── At send time ──────────────────────────────────────────────────────────────

def _sweep_touched(folder: str, older_than: float = 12 * 3600) -> None:
    """Copies left behind, after long enough that none is still waiting to go: Snapchat's can wait out its quiet
    hours."""
    now = time.time()
    try:
        for entry in os.scandir(folder):
            try:
                if now - entry.stat().st_mtime < older_than:
                    continue
                if entry.is_dir():
                    for inner in os.scandir(entry.path):
                        os.remove(inner.path)
                    os.rmdir(entry.path)
                else:
                    os.remove(entry.path)
            except OSError:
                continue
    except OSError:
        pass


async def touched_copy(path: str, description: str, recent: list, reply: str, account_id: str, lang: str = "en",
                       their_name: str = "", platform: str = "", keep_name: bool = False) -> str:
    """The picture to send: a copy with the touches the model chose, or `path` itself when touches are off for this
    account, the chance says not this time, or the model chose nothing. keep_name puts the copy in a folder of its own
    under the picture's own name, for a platform that shows the file's name (Discord); Snapchat never shows it. Never
    raises: any trouble sends the picture as it is."""
    import asyncio
    from app.utils.helpers import resource_path
    from app.utils.logger import log_system
    # A video goes as it is: touches are drawn on a still.
    if os.path.splitext(path or "")[1].lower() == ".mp4":
        return path
    try:
        cfg = touches_cfg()
        if account_id not in cfg["accounts"] or not cfg["kinds"] or random.random() >= cfg["chance"]:
            return path
        spec = await plan_touch(description, recent, reply, lang, cfg["kinds"], their_name, platform)
        if not spec:
            log_system(f"[PIC] It sent {os.path.basename(path)} as it is")
            return path
        data = await asyncio.to_thread(source_bytes, path, spec)
        blob, ext = await asyncio.to_thread(render_touch, data, spec, lang)
        root = os.path.join(resource_path("config/temp"), "touched")
        os.makedirs(root, exist_ok=True)
        _sweep_touched(root)
        stem = os.path.splitext(os.path.basename(path))[0]
        if keep_name:
            folder = os.path.join(root, uuid.uuid4().hex[:12])
            os.makedirs(folder, exist_ok=True)
            out = os.path.join(folder, stem + ext)
        else:
            out = os.path.join(root, f"{stem}_{uuid.uuid4().hex[:10]}{ext}")
        with open(out, "wb") as fh:
            fh.write(blob)
        log_system(f"[PIC] Added {describe_touch(spec)} to {os.path.basename(path)}")
        return out
    except Animated:
        return path
    except Exception as exc:
        try:
            log_system(f"[PIC] Sent {os.path.basename(path)} as it is: {type(exc).__name__}: {exc}")
        except Exception:
            pass
        return path


def drop_copy(original: str, sent: str) -> None:
    """A touched copy, gone once it is sent (and its folder, when it had one of its own)."""
    if not sent or sent == original:
        return
    try:
        os.remove(sent)
        folder = os.path.dirname(sent)
        if os.path.basename(os.path.dirname(folder)) == "touched" and not os.listdir(folder):
            os.rmdir(folder)
    except OSError:
        pass
