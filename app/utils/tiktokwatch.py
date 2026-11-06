"""app/utils/tiktokwatch.py - a TikTok watched, the way someone who was sent one watches it.

Someone sends the persona a TikTok: in a TikTok DM, or as a link on Discord or Snapchat. Until now the model got the
caption from TikTok's oEmbed and, at best, the cover picture (app/utils/tiktoklinks.py), so the persona answered a
video it had not seen. Now it is watched:
- its public page says what it is: caption, author, sound, length, how many saw and liked it;
- the video itself is downloaded, and frames from across it go to the vision model on one picture, as the persona's
  own videos are described (app/utils/videos.py);
- what is said in it is transcribed;
- a photo post is looked at photo by photo.
What it saw goes in with the message, so the reply is to the video. It stays in the conversation after, so it is
remembered.

Each video is watched once. What was seen is kept in cache/tiktok_watched/<id>.json for a month, for every account
and for the panel (the Chats tab shows it on the TikTok's card). At most two are watched at a time, and never for
long. A video that will not download, or no ffmpeg, falls back to the caption and cover, as before. A LIVE line
(ai.REALTIME) never waits for a video. The watching itself (frames, sound, the vision model) is
app/utils/videowatch.py's, as for every video people send. Settings: tiktok.watch.enabled for TikToks, on every
platform; bot.videos (listen, max_seconds) for how.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from app.utils import tiktoklinks, videowatch

UA = videowatch.UA
_HEADERS = videowatch.HEADERS
_REHYDRATION = re.compile(r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)
_ID = re.compile(r"tiktok\.com/@[\w.]+/(?:video|photo)/(\d{6,25})", re.I)

PHOTOS = 4
MAX_VIDEO_BYTES = 40_000_000
MAX_PHOTO_BYTES = 8_000_000
MAX_AUDIO_BYTES = 12_000_000
# The whole watch, page to caption: past this, the reply goes on with the caption and cover.
TIMEOUT = 75.0
KEEP_DAYS = 30
KEEP_MAX = 500
# One that could not be read is not tried again for every message that has it.
_MISSED_FOR = 600

_missed: dict = {}
_short: dict = {}
_state: dict = {}


def settings() -> dict:
    """Whether TikToks are watched (tiktok.watch.enabled), and how: listening, how much of a long one (bot.videos, as
    for every video people send)."""
    out = dict(videowatch.settings())
    out["enabled"] = True
    try:
        from app.utils.helpers import load_config
        raw = (load_config().get("tiktok") or {}).get("watch")
    except Exception:
        raw = None
    if isinstance(raw, dict) and raw.get("enabled") is not None:
        out["enabled"] = bool(raw["enabled"])
    return out


def video_id(url: str) -> str:
    """The id in a full TikTok link, or that a short link was found to lead to; "" when not known yet."""
    m = _ID.search(url or "")
    return m.group(1) if m else _short.get((url or "").strip(), "")


# ── What a TikTok is, from its page ───────────────────────────────────────────

def page_item(html: str) -> dict:
    """The post on a TikTok page: the itemStruct in its rehydration data, {} when the page has none (a check, a
    private or removed post)."""
    m = _REHYDRATION.search(html or "")
    if not m:
        return {}
    try:
        scope = (json.loads(m.group(1)) or {}).get("__DEFAULT_SCOPE__") or {}
    except ValueError:
        return {}
    for key in ("webapp.video-detail", "webapp.photo-detail", *scope.keys()):
        item = ((scope.get(key) or {}).get("itemInfo") or {}).get("itemStruct") if isinstance(scope.get(key), dict) else None
        if isinstance(item, dict) and item.get("id"):
            return item
    return {}


def _int(*values) -> int:
    for v in values:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n:
            return n
    return 0


def _first_url(block) -> str:
    """The first address in TikTok's {"urlList": [...]} (or {"UrlList": [...]})."""
    if not isinstance(block, dict):
        return ""
    urls = block.get("urlList") or block.get("UrlList") or block.get("url_list") or []
    return next((u for u in urls if isinstance(u, str) and u.startswith("https://")), "")


def facts(item: dict, url: str = "") -> dict:
    """What a post is, before anyone watches it: whose, its caption, sound, numbers, length, cover."""
    author = item.get("author") or {}
    music = item.get("music") or {}
    stats, stats2 = item.get("stats") or {}, item.get("statsV2") or {}
    video = item.get("video") or {}
    post = item.get("imagePost") or {}
    handle = str(author.get("uniqueId") or "")
    vid = str(item.get("id") or "")
    kind = "photo" if post.get("images") else "video"
    images = [img for img in (post.get("images") or []) if isinstance(img, dict)]
    cover = (video.get("cover") or video.get("originCover") or _first_url((post.get("cover") or {}).get("imageURL"))
             or (_first_url(images[0].get("imageURL")) if images else ""))
    return {
        "id": vid,
        "url": f"https://www.tiktok.com/@{handle}/{kind}/{vid}" if handle and vid else url,
        "kind": kind,
        "author": handle,
        "name": str(author.get("nickname") or ""),
        "verified": bool(author.get("verified")),
        "caption": " ".join(str(item.get("desc") or "").split()),
        "music": str(music.get("title") or ""),
        "music_by": str(music.get("authorName") or ""),
        "views": _int(stats.get("playCount"), stats2.get("playCount")),
        "likes": _int(stats.get("diggCount"), stats2.get("diggCount")),
        "comments": _int(stats.get("commentCount"), stats2.get("commentCount")),
        "shares": _int(stats.get("shareCount"), stats2.get("shareCount")),
        "saves": _int(stats.get("collectCount"), stats2.get("collectCount")),
        "duration": _int(video.get("duration")) if kind == "video" else 0,
        "photos": len(images),
        "created": _int(item.get("createTime")),
        "cover": cover if isinstance(cover, str) and cover.startswith("https://") else "",
        "seen": "",
        "said": "",
    }


def video_sources(item: dict) -> list[str]:
    """Where its video can be downloaded, the smallest first: frames for a model need no more."""
    video = item.get("video") or {}
    sized = []
    for b in video.get("bitrateInfo") or []:
        if not isinstance(b, dict):
            continue
        play = b.get("PlayAddr") or {}
        size = _int(play.get("DataSize"))
        if size and size > MAX_VIDEO_BYTES:
            continue
        for u in play.get("UrlList") or play.get("urlList") or []:
            if isinstance(u, str) and u.startswith("https://"):
                sized.append((_int(b.get("Bitrate")) or 10 ** 9, u))
    out = [u for _, u in sorted(sized, key=lambda p: p[0])]
    for key in ("playAddr", "downloadAddr"):
        u = video.get(key)
        if isinstance(u, str) and u.startswith("https://") and u not in out:
            out.append(u)
    return out


def audio_sources(item: dict) -> list[str]:
    """Where its sound alone can be downloaded, the smallest first. TikTok's smallest videos carry no sound: it is a
    stream of its own beside them."""
    found = []
    for a in (item.get("video") or {}).get("bitrateAudioInfo") or []:
        if not isinstance(a, dict):
            continue
        urls = a.get("UrlList") or {}
        urls = [urls.get(k) for k in ("MainUrl", "BackupUrl", "FallbackUrl")] if isinstance(urls, dict) else urls
        for u in urls or []:
            if isinstance(u, str) and u.startswith("https://"):
                found.append((_int(a.get("Bitrate")) or 10 ** 9, u))
    return [u for _, u in sorted(found, key=lambda p: p[0])]


def photo_sources(item: dict) -> list[list[str]]:
    """The addresses of each photo of a photo post (its first few), every copy TikTok offers of each."""
    out = []
    for img in ((item.get("imagePost") or {}).get("images") or [])[:PHOTOS]:
        block = (img or {}).get("imageURL") or (img or {}).get("displayImage") or {}
        urls = [u for u in (block.get("urlList") or block.get("url_list") or []) if isinstance(u, str)
                and u.startswith("https://")]
        if urls:
            out.append(urls)
    return out


# ── What was seen, kept ───────────────────────────────────────────────────────

def cache_dir() -> Path:
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "tiktok_watched"


def cached(vid: str) -> dict | None:
    """What was seen of this video, when it was watched in the last month."""
    if not re.fullmatch(r"\d{6,25}", vid or ""):
        return None
    path = cache_dir() / f"{vid}.json"
    try:
        if time.time() - path.stat().st_mtime > KEEP_DAYS * 86400:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") == vid else None


def keep(w: dict) -> None:
    """Remember what was seen of a video; the oldest go past a few hundred, or after a month."""
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{w['id']}.part"
    tmp.write_text(json.dumps(w, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, folder / f"{w['id']}.json")
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    now = time.time()
    for i, p in enumerate(files):
        try:
            if i >= KEEP_MAX or now - p.stat().st_mtime > KEEP_DAYS * 86400:
                p.unlink()
        except OSError:
            pass


def seen_for(url: str) -> dict | None:
    """What was seen of the TikTok at this link, when it has been watched (for the panel: reads the cache only)."""
    vid = video_id(url)
    return cached(vid) if vid else None


# ── Watching ──────────────────────────────────────────────────────────────────

def _loop_state() -> dict:
    """The locks of the loop this runs on: one watch per video at a time, two videos at once at most."""
    loop = asyncio.get_running_loop()
    if _state.get("loop") is not loop:
        _state.clear()
        _state.update(loop=loop, gate=asyncio.Semaphore(2), locks={})
    locks = _state["locks"]
    if len(locks) > 200:
        for key in [k for k, lock in locks.items() if not lock.locked()]:
            locks.pop(key, None)
    return _state


async def _fetch(client, urls: list[str], limit: int) -> bytes:
    """The first of these that downloads whole and under `limit` bytes; b"" when none does."""
    for src in urls:
        try:
            async with client.stream("GET", src, headers={"referer": "https://www.tiktok.com/"}) as r:
                if r.status_code not in (200, 206) or _int(r.headers.get("content-length")) > limit:
                    continue
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > limit:
                        break
                if 0 < len(buf) <= limit:
                    return bytes(buf)
        except Exception:
            continue
    return b""


async def _watch(url: str, cfg: dict) -> dict | None:
    import httpx
    from app.utils import videos
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=_HEADERS) as client:
        r = await client.get(url)
        item = page_item(r.text) if r.status_code == 200 else {}
        if not item:
            return None
        w = facts(item, str(r.url))
        if not w["id"]:
            return None
        if url.strip() != w["url"] and not _ID.search(url):
            _short[url.strip()] = w["id"]
            hit = await asyncio.to_thread(cached, w["id"])
            if hit:
                return hit
        board, sound = b"", None
        try:
            if w["kind"] == "video" and videos.available():
                blob = await _fetch(client, video_sources(item), MAX_VIDEO_BYTES)
                if blob:
                    board, sound, _ = await asyncio.to_thread(videowatch.look_video, blob, cfg)
                if blob and cfg["listen"] and not sound:
                    audio = await _fetch(client, audio_sources(item), MAX_AUDIO_BYTES)
                    if audio:
                        sound = await asyncio.to_thread(videowatch.spooled, audio, ".m4a",
                                                        lambda p: videowatch.listen_to(p, cfg))
            elif w["kind"] == "photo":
                blobs = [await _fetch(client, urls, MAX_PHOTO_BYTES) for urls in photo_sources(item)]
                board = await asyncio.to_thread(videowatch.look_photos, [b for b in blobs if b])
        except Exception:
            board, sound = b"", None
    if sound:
        try:
            w["said"] = await videowatch.heard(sound)
        except Exception:
            w["said"] = ""
    if board:
        try:
            w["seen"] = await videowatch.caption(board, w["said"], w["kind"])
        except Exception:
            w["seen"] = ""
    return w


async def watch(url: str) -> dict | None:
    """One TikTok, watched: its facts (facts()) with "seen", what happens in it, and "said", what is said in it.
    Only its facts when it could be read but not watched; None when not even that, or watching is off."""
    cfg = settings()
    url = (url or "").strip()
    if not cfg["enabled"] or not url:
        return None
    vid = video_id(url)
    if vid:
        hit = await asyncio.to_thread(cached, vid)
        if hit:
            return hit
    if time.time() - _missed.get(url, 0) < _MISSED_FOR:
        return None
    st = _loop_state()
    lock = st["locks"].setdefault(vid or url, asyncio.Lock())
    # Everything under the lock, the keeping too: whoever waited on it finds what was seen (or that it would not open).
    async with lock:
        if vid:
            hit = await asyncio.to_thread(cached, vid)
            if hit:
                return hit
        if time.time() - _missed.get(url, 0) < _MISSED_FOR:
            return None
        async with st["gate"]:
            started = time.time()
            try:
                w = await asyncio.wait_for(_watch(url, cfg), TIMEOUT)
            except Exception:
                w = None
        if not w:
            _missed[url] = time.time()
            while len(_missed) > 300:
                _missed.pop(next(iter(_missed)))
            return None
        if w.get("seen") or w.get("said"):
            w["watched"] = int(time.time())
            try:
                await asyncio.to_thread(keep, w)
            except OSError:
                pass
            try:
                from app.utils.logger import log_system
                log_system(f"Watched @{w['author']}'s TikTok ({time.time() - started:.0f}s): {w['seen'][:90]}")
            except Exception:
                pass
    return w


# ── Saying it to the model ────────────────────────────────────────────────────

def count(n: int) -> str:
    """2567 as it is, 458300 as 458.3K, 1250000 as 1.2M: as TikTok shows its numbers (cut, not rounded up)."""
    n = int(n)
    for unit, size in (("B", 10 ** 9), ("M", 10 ** 6), ("K", 10 ** 3)):
        if n >= max(size, 10_000):
            whole, tenth = divmod(n * 10 // size, 10)
            return f"{whole}.{tenth}{unit}" if tenth else f"{whole}{unit}"
    return str(n)


def ago(ts: int, now: float | None = None) -> str:
    """How long ago a post went up, as a person says it."""
    secs = max(0, (now or time.time()) - ts)
    days = int(secs // 86400)
    if secs < 3600:
        return "within the hour"
    if days < 1:
        hours = int(secs // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    if days < 730:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 3].rsplit(" ", 1)[0] + "..."


def summary(w: dict, lead: str = "the TikTok they shared", now: float | None = None, react: bool = True) -> str:
    """One bracketed note for the model about a TikTok: what it is and, when it was watched, what happens and what is
    said in it. `lead` names it: "the TikTok they shared", "their newest TikTok". `react`: and that it is to be reacted
    to, as something just watched (not when it is only background)."""
    photo = w.get("kind") == "photo"
    who = "@" + w["author"] if w.get("author") else "someone"
    if w.get("name") and w["name"].lower() != (w.get("author") or "").lower():
        who += f" ({_clip(w['name'], 40)})"
    bits = []
    if w.get("created"):
        bits.append("posted " + ago(w["created"], now))
    if photo and w.get("photos"):
        bits.append(f"{w['photos']} photo{'s' if w['photos'] != 1 else ''}")
    elif w.get("duration"):
        d = int(w["duration"])
        bits.append(f"{d} seconds long" if d < 90 else f"{round(d / 60)} minutes long")
    for key, label in (("views", "views"), ("likes", "likes"), ("comments", "comments")):
        if w.get(key):
            bits.append(f"{count(w[key])} {label}")
    watched = bool(w.get("seen") or w.get("said"))
    verb = ("You looked at" if photo else "You watched") if watched else "About"
    out = f"[{verb} {lead}{' (a photo post)' if photo else ''}: by {who}"
    if bits:
        out += ", " + ", ".join(bits)
    out += "."
    if w.get("caption"):
        out += f' Caption: "{_clip(w["caption"], 220)}".'
    if w.get("music") and not photo:
        by = f" by {w['music_by']}" if w.get("music_by") else ""
        out += f' Sound: "{_clip(w["music"], 60)}"{by}.'
    elif w.get("music"):
        out += f' Song: "{_clip(w["music"], 60)}".'
    if w.get("seen"):
        out += (" What is in the photos: " if photo else " What happens in it: ") + w["seen"].rstrip(".") + "."
    if w.get("said"):
        out += f' What is said in it: "{_clip(w["said"], 300)}".'
    if watched and react:
        out += " React to it like someone who just watched it; do not describe it back to them."
    return out + "]"


async def enrich(content: str) -> tuple[str, str, bool]:
    """(the message with a note about each TikTok in it, a cover picture for the vision model or "", whether one was
    watched). A watched one needs no cover: its frames were already looked at. One that could not be watched falls
    back to its caption and cover, as tiktoklinks always did."""
    urls = tiktoklinks.links_in(content)
    if not urls:
        return content, "", False
    from app.utils import ai
    if ai.REALTIME.get() or not settings()["enabled"]:
        text, cover = await tiktoklinks.enrich(content)
        return text, cover, False
    lines, cover, watched = [], "", False
    for i, url in enumerate(urls):
        w = await watch(url) if i < 2 else None
        if w:
            lines.append(summary(w))
            if w.get("seen") or w.get("said"):
                watched = True
            elif not cover and w.get("cover"):
                cover = w["cover"]
            continue
        info = await tiktoklinks.lookup(url)
        line = tiktoklinks.describe(info)
        if line:
            lines.append(line)
        if not cover and str(info.get("thumbnail_url", "")).startswith("https://"):
            cover = info["thumbnail_url"]
    return (content + ("\n" + "\n".join(lines) if lines else "")), cover, watched
