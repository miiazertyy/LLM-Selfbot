"""app/utils/videowatch.py - a video someone sent, watched the way they would watch it.

People send the persona videos: a clip in a Discord DM, a video snap or a video in a Snapchat chat, a video in a
TikTok chat, a Snapchat Spotlight, a TikTok. A picture model reads one picture, so it saw one frame of them at most (a
screenshot, a cover) and heard nothing. Here one is watched:
- frames from across it go to the vision model on one picture, numbered in order (app/utils/videos.py, as the
  persona's own videos are described);
- what is said in it is transcribed (bot.videos.listen), and goes into that description too;
- a note saying what happens and what is said goes in with their message, so the reply is to the video, and it stays
  in the conversation after.

Every platform comes here: Discord's own reply path for a video attachment, the browser bridge for what the Snapchat
and TikTok runners captured (the video itself, or frames when the page would not give the file), and Spotlight links
on any platform. app/utils/tiktokwatch.py uses the same pieces for TikToks, with what TikTok's page says of a post.

Each video is watched once: what was seen is kept for a month, by its content (cache/videos_watched/<sha1>.json) or
by its Spotlight's id. At most two are watched at a time, never for long. Settings: bot.videos (enabled, listen,
max_seconds).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
HEADERS = {"user-agent": UA, "accept-language": "en-US,en;q=0.9"}
# The bot.videos settings, as config.yaml ships them.
DEFAULTS = {"enabled": True, "listen": True, "max_seconds": 180}
FRAMES = 6
MAX_BYTES = 40_000_000
# The whole watch, file to description: past this, the reply goes on without it.
TIMEOUT = 75.0
KEEP_DAYS = 30
KEEP_MAX = 400
# Whisper on music alone: the same few lines every time, never anything said in the video.
_NOT_SAID = re.compile(r"thanks? (?:you )?for watching|subtitles? by|amara\.org|transcri(?:bed|ption) by|"
                       r"please subscribe|like and subscribe", re.I)
# A Spotlight as it is shared: its page, the app's short link, the older story link.
_SPOTLIGHT = re.compile(r"https?://(?:www\.)?snapchat\.com/(?:spotlight/[\w-]{8,}|t/[\w-]{4,})"
                        r"|https?://(?:t|story)\.snapchat\.com/(?:spotlight/)?[\w-]{4,}", re.I)
_SPOT_ID = re.compile(r"/spotlight/([\w-]{8,120})")

_state: dict = {}


def settings() -> dict:
    """The bot.videos settings, each one there and of its kind."""
    try:
        from app.utils.helpers import load_config
        raw = (load_config().get("bot") or {}).get("videos")
    except Exception:
        raw = None
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key in ("enabled", "listen"):
            if raw.get(key) is not None:
                out[key] = bool(raw[key])
        try:
            out["max_seconds"] = max(10, min(600, int(raw.get("max_seconds", out["max_seconds"]))))
        except (TypeError, ValueError):
            pass
    return out


# ── Looking at it ─────────────────────────────────────────────────────────────

def spooled(blob: bytes, suffix: str, work):
    """`work(path)` on these bytes kept in a file of their own for the while, then gone."""
    fd, name = tempfile.mkstemp(prefix="llmselfbot-watch-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(blob)
        return work(name)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def listen_to(path, cfg: dict) -> bytes | None:
    """Its sound, to be transcribed: None when it has none (or none worth a transcription)."""
    from app.utils import videos
    try:
        return videos.sound(path, min(90, cfg["max_seconds"]))
    except Exception:
        return None


def look_video(blob: bytes, cfg: dict, suffix: str = ".mp4") -> tuple[bytes, bytes | None, float]:
    """Frames from across the video on one picture, its sound to be transcribed (when it is listened to and has
    any), and how long it is."""
    from app.utils import videos

    def work(path):
        try:
            duration = videos.probe(path)["duration"]
        except Exception:
            duration = 0.0
        board = videos.sheet(path, FRAMES, 480, upto=cfg["max_seconds"])
        return board, (listen_to(path, cfg) if cfg["listen"] else None), duration
    return spooled(blob, suffix, work)


def look_photos(blobs: list[bytes]) -> bytes:
    """Pictures on one picture, in order, each made small: a photo post's photos, or frames taken off a page."""
    import io
    from PIL import Image
    from app.utils import videos
    shots = []
    for blob in blobs:
        try:
            img = Image.open(io.BytesIO(blob)).convert("RGB")
        except Exception:
            continue
        if img.width > 480:
            img = img.resize((480, max(1, round(img.height * 480 / img.width))))
        shots.append(img)
    return videos.board(shots) if shots else b""


PHOTOS_PROMPT = (
    "These are the photos of one post, in order: left to right, then top to bottom. "
    "Describe the post like a short caption, in one or two sentences and under 40 words: "
    "who or what is in the photos, where, and any visible text. "
    "Plain words only, no markdown or lists, and do not begin with \"The photos\" or \"These photos\"."
)


async def caption(board: bytes, said: str = "", kind: str = "video") -> str:
    """What happens in it, in a sentence or two, from the vision model set up for pictures."""
    from app.utils import videos
    from app.utils.ai import _create_image_completion
    from app.utils.helpers import load_config
    from app.utils.pictures import DESCRIBE_MAX_TOKENS, clean_description
    model = (load_config().get("bot") or {}).get("groq_image_model", "meta-llama/llama-4-scout-17b-16e-instruct")
    data_url = "data:image/jpeg;base64," + base64.b64encode(board).decode()
    if kind == "photo":
        messages = [{"role": "user", "content": [{"type": "text", "text": PHOTOS_PROMPT},
                                                 {"type": "image_url", "image_url": {"url": data_url}}]}]
    else:
        messages = videos.describe_messages(data_url, said)
    resp = await _create_image_completion(model, messages=messages, max_tokens=DESCRIBE_MAX_TOKENS,
                                          reasoning_effort="none")
    return clean_description(resp.choices[0].message.content or "")


async def heard(sound: bytes) -> str:
    """What is said in it, when anything is: words, not a song's hum or Whisper's "thanks for watching"."""
    from app.utils import videos
    from app.utils.ai import transcribe_voice
    text = videos.heard(await transcribe_voice(sound, "sound.mp3"))
    return "" if text and len(text) < 90 and _NOT_SAID.search(text) else text


# ── What was seen, kept ───────────────────────────────────────────────────────

def cache_dir() -> Path:
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "videos_watched"


def _key_ok(key: str) -> bool:
    return bool(re.fullmatch(r"[\w-]{8,140}", key or ""))


def cached(key: str) -> dict | None:
    """What was seen of this video (by its key), when it was watched in the last month."""
    if not _key_ok(key):
        return None
    path = cache_dir() / f"{key}.json"
    try:
        if time.time() - path.stat().st_mtime > KEEP_DAYS * 86400:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def keep(key: str, w: dict) -> None:
    """Remember what was seen of a video; the oldest go past a few hundred, or after a month."""
    if not _key_ok(key):
        return
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{key}.part"
    tmp.write_text(json.dumps(w, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, folder / f"{key}.json")
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    now = time.time()
    for i, p in enumerate(files):
        try:
            if i >= KEEP_MAX or now - p.stat().st_mtime > KEEP_DAYS * 86400:
                p.unlink()
        except OSError:
            pass


# ── Watching ──────────────────────────────────────────────────────────────────

def _loop_state() -> dict:
    """The locks of the loop this runs on: one watch per video at a time, two at once at most."""
    loop = asyncio.get_running_loop()
    if _state.get("loop") is not loop:
        _state.clear()
        _state.update(loop=loop, gate=asyncio.Semaphore(2), locks={})
    locks = _state["locks"]
    if len(locks) > 200:
        for key in [k for k, lock in locks.items() if not lock.locked()]:
            locks.pop(key, None)
    return _state


async def _once(key: str, work) -> dict | None:
    """`work()` (the watching itself) once per key at a time, two at once at most, never long; what it saw kept."""
    hit = await asyncio.to_thread(cached, key)
    if hit:
        return hit
    st = _loop_state()
    lock = st["locks"].setdefault(key, asyncio.Lock())
    async with lock:
        hit = await asyncio.to_thread(cached, key)
        if hit:
            return hit
        async with st["gate"]:
            started = time.time()
            try:
                w = await asyncio.wait_for(work(), TIMEOUT)
            except Exception:
                w = None
        if w and (w.get("seen") or w.get("said")):
            w["watched"] = int(time.time())
            try:
                await asyncio.to_thread(keep, key, w)
            except OSError:
                pass
            try:
                from app.utils.logger import log_system
                log_system(f"Watched a video ({time.time() - started:.0f}s): {str(w.get('seen') or w.get('said'))[:90]}")
            except Exception:
                pass
    return w


async def _seen_and_said(board: bytes, sound: bytes | None) -> tuple[str, str]:
    said = ""
    if sound:
        try:
            said = await heard(sound)
        except Exception:
            said = ""
    seen = ""
    if board:
        try:
            seen = await caption(board, said, "video")
        except Exception:
            seen = ""
    return seen, said


async def watch_bytes(blob: bytes, suffix: str = ".mp4") -> dict | None:
    """A video file's bytes, watched: {"seen", "said", "duration"}. None when watching is off, there is no ffmpeg,
    or it would not play."""
    cfg = settings()
    from app.utils import videos
    if not cfg["enabled"] or not blob or not videos.available():
        return None

    async def work():
        board, sound, duration = await asyncio.to_thread(look_video, blob, cfg, suffix or ".mp4")
        seen, said = await _seen_and_said(board, sound)
        return {"seen": seen, "said": said, "duration": round(duration, 1)}
    return await _once(hashlib.sha1(blob).hexdigest(), work)


async def watch_file(path) -> dict | None:
    """A video file on this computer, watched (watch_bytes); too big or not there, None."""
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > MAX_BYTES:
            return None
        blob = await asyncio.to_thread(p.read_bytes)
    except OSError:
        return None
    return await watch_bytes(blob, p.suffix or ".mp4")


async def watch_frames(frames: list[bytes]) -> dict | None:
    """Frames of a video taken off a page that would not give the video itself (a snap's player), in order: looked
    at as a video's frames are, with no sound to hear."""
    frames = [f for f in frames if f][:FRAMES]
    if not settings()["enabled"] or not frames:
        return None

    async def work():
        board = await asyncio.to_thread(look_photos, frames)
        seen, _ = await _seen_and_said(board, None)
        return {"seen": seen, "said": "", "duration": 0, "frames": len(frames)}
    return await _once(hashlib.sha1(b"".join(frames)).hexdigest(), work)


async def download(url: str, limit: int = MAX_BYTES, headers: dict | None = None) -> bytes:
    """A video's bytes from a link, whole and under `limit`; b"" when it will not come."""
    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers={**HEADERS, **(headers or {})}) as c:
            async with c.stream("GET", url) as r:
                if r.status_code not in (200, 206):
                    return b""
                try:
                    if int(r.headers.get("content-length") or 0) > limit:
                        return b""
                except ValueError:
                    pass
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > limit:
                        return b""
                return bytes(buf)
    except Exception:
        return b""


async def watch_url(url: str, suffix: str = "") -> dict | None:
    """A video at a link (a Discord attachment), downloaded and watched."""
    if not settings()["enabled"]:
        return None
    blob = await download(url)
    if not suffix:
        suffix = os.path.splitext(url.split("?", 1)[0])[1].lower()[:8] or ".mp4"
    return await watch_bytes(blob, suffix) if blob else None


# ── Spotlights ────────────────────────────────────────────────────────────────

def spotlight_links(text: str) -> list[str]:
    seen = []
    for m in _SPOTLIGHT.finditer(str(text or "")):
        url = m.group(0).rstrip(".,);!?\"'")
        if url not in seen:
            seen.append(url)
    return seen[:3]


def _meta(html: str, prop: str) -> str:
    m = re.search(rf'<meta[^>]+property="og:{prop}"[^>]+content="([^"]*)"', html or "") \
        or re.search(rf'<meta[^>]+content="([^"]*)"[^>]+property="og:{prop}"', html or "")
    if not m:
        return ""
    import html as _html
    return _html.unescape(m.group(1)).strip()


def _num(text: str) -> int:
    """'655', '1,234', '12.5K', '1.2M' as a number."""
    m = re.fullmatch(r"([\d.,]+)\s*([KkMm]?)", (text or "").strip())
    if not m:
        return 0
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0
    return int(n * {"k": 1000, "m": 1_000_000}.get(m.group(2).lower(), 1))


def spotlight_facts(html: str, url: str = "") -> dict:
    """What a Spotlight's public page says of it: its title, its creator, its likes, comments and shares, Snapchat's
    own words on it, and where its video is. {} when the page says nothing (a removed one)."""
    title = _meta(html, "title")
    video = _meta(html, "video") or _meta(html, "video:url") or _meta(html, "video:secure_url")
    if not title and not video:
        return {}
    parts = [p.strip() for p in title.split("|")]
    counts = parts[0] if parts and re.search(r"\d", parts[0]) else ""

    def count(word):
        m = re.search(rf"([\d.,]+\s*[KkMm]?)\s+{word}", counts)
        return _num(m.group(1)) if m else 0
    creator = next((p for p in parts if re.search(r"\(@[\w.-]+\)", p)), "")
    handle = (re.search(r"\(@([\w.-]+)\)", creator) or [None, ""])[1]
    name = re.sub(r"\s*\(@[\w.-]+\)\s*", "", creator).strip()
    words = next((p for p in parts[1 if counts else 0:] if p and p != creator and not re.match(r"^date\b", p, re.I)), "")
    canon = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html or "")
    page = canon.group(1) if canon else url
    sid = (_SPOT_ID.search(page or "") or _SPOT_ID.search(url or "") or [None, ""])[1]
    return {
        "id": sid, "url": page, "kind": "spotlight", "title": words, "creator": handle, "name": name,
        "likes": count("likes"), "comments": count("comment"), "shares": count("share"),
        "about": _meta(html, "description"), "video": video if video.startswith("https://") else "",
        "seen": "", "said": "", "duration": 0,
    }


async def spotlight(url: str) -> dict | None:
    """A Spotlight, watched: what its page says of it (spotlight_facts) with "seen" and "said". Its facts alone when
    the video would not come; None when the page says nothing, or watching is off."""
    if not settings()["enabled"]:
        return None
    sid = (_SPOT_ID.search(url) or [None, ""])[1]
    if sid:
        hit = await asyncio.to_thread(cached, f"spot_{sid}"[:140])
        if hit:
            return hit
    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=HEADERS) as c:
            r = await c.get(url)
            facts = spotlight_facts(r.text, str(r.url)) if r.status_code == 200 else {}
    except Exception:
        facts = {}
    if not facts:
        return None
    key = f"spot_{facts['id']}"[:140] if facts.get("id") else hashlib.sha1(url.encode()).hexdigest()

    async def work():
        blob = await download(facts["video"]) if facts.get("video") else b""
        w = dict(facts)
        if blob:
            from app.utils import videos
            if videos.available():
                board, sound, duration = await asyncio.to_thread(look_video, blob, settings(), ".mp4")
                w["seen"], w["said"] = await _seen_and_said(board, sound)
                w["duration"] = round(duration, 1)
        return w
    w = await _once(key, work)
    return w or facts


# ── Saying it to the model ────────────────────────────────────────────────────

def _clip(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3].rsplit(" ", 1)[0] + "..."


def _length(seconds) -> str:
    d = int(float(seconds or 0))
    if d <= 0:
        return ""
    return f"{d} seconds long" if d < 90 else f"{round(d / 60)} minutes long"


def note(w: dict | None, lead: str = "the video they sent you", react: bool = True) -> str:
    """One bracketed note for the model: what happens and what is said in the video. When it would not play, that
    it did not, so the persona can say so rather than pretend."""
    if not w or not (w.get("seen") or w.get("said")):
        return f"[{lead[0].upper() + lead[1:]} would not play for you, so you have not seen it.]"
    bits = [b for b in (_length(w.get("duration")), "no sound" if w.get("frames") else "") if b]
    out = f"[You watched {lead}" + (f" ({', '.join(bits)})" if bits else "") + "."
    if w.get("seen"):
        out += " What happens in it: " + str(w["seen"]).rstrip(".") + "."
    if w.get("said"):
        out += f' What is said in it: "{_clip(w["said"], 300)}".'
    if react:
        out += " React to it like someone who just watched it; do not describe it back to them."
    return out + "]"


def spotlight_summary(w: dict, lead: str = "the Spotlight they shared", react: bool = True) -> str:
    """One bracketed note about a Spotlight: whose, how it is doing, what it is called and, once watched, what
    happens and what is said in it."""
    from app.utils.tiktokwatch import count
    who = (f"@{w['creator']}" if w.get("creator") else "") + (f" ({_clip(w['name'], 40)})" if w.get("name") else "")
    bits = [b for b in (_length(w.get("duration")),
                        *(f"{count(w[k])} {k}" for k in ("likes", "comments", "shares") if w.get(k))) if b]
    watched = bool(w.get("seen") or w.get("said"))
    out = f"[{'You watched' if watched else 'About'} {lead}" + (f": by {who.strip()}" if who.strip() else "")
    out += (", " + ", ".join(bits) if bits else "") + "."
    if w.get("title"):
        out += f' It is called "{_clip(w["title"], 120)}".'
    if w.get("seen"):
        out += " What happens in it: " + str(w["seen"]).rstrip(".") + "."
    elif w.get("about"):
        out += f" Snapchat says of it: {_clip(w['about'], 220)}"
    if w.get("said"):
        out += f' What is said in it: "{_clip(w["said"], 300)}".'
    if watched and react:
        out += " React to it like someone who just watched it; do not describe it back to them."
    return out + "]"


async def enrich_links(content: str) -> tuple[str, str, bool]:
    """(the message with a note about each TikTok, Instagram post and Spotlight linked in it, a cover picture for the
    vision model or "", whether one was watched). TikToks go through app/utils/tiktokwatch.py, Instagram's through
    app/utils/instagramwatch.py; a Spotlight is watched here; any other link is read (app/utils/web/links.py). A
    LIVE line (ai.REALTIME) never waits for a video."""
    text, cover, watched = content, "", False
    if "tiktok.com" in (content or ""):
        from app.utils import tiktokwatch
        text, cover, watched = await tiktokwatch.enrich(text)
    if "instagram.com" in (content or ""):
        from app.utils import instagramwatch
        text, ig_cover, ig_watched = await instagramwatch.enrich(text)
        cover = cover or ig_cover
        watched = watched or ig_watched
    spots = spotlight_links(content)
    if spots:
        from app.utils import ai
        if ai.REALTIME.get() or not settings()["enabled"]:
            return text, cover, watched
        lines = []
        for url in spots[:2]:
            w = await spotlight(url)
            if w:
                lines.append(spotlight_summary(w))
                watched = watched or bool(w.get("seen") or w.get("said"))
        if lines:
            text = text + "\n" + "\n".join(lines)
    # Every other link: the page read, and a note on what it says (app/utils/web/links.py, bot.web.links).
    if "http" in (content or ""):
        try:
            from app.utils.web import links as web_links
            text = await web_links.enrich(text)
        except Exception:
            pass
    return text, cover, watched
