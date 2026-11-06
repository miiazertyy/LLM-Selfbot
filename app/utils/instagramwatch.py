"""app/utils/instagramwatch.py - an Instagram reel, post or story watched, the way someone who was sent one watches it.

Someone shares a reel in an Instagram DM, or drops an instagram.com link on
Discord, Snapchat or TikTok. Without this the model would only have the caption
off the embed page (app/utils/instagramlinks.py) and answer something it had not
seen. Now it is watched:
  * the embed page says what it is: whose it is, its caption, whether it moves;
  * the video is downloaded and frames from across it go to the vision model on
    one picture, as the persona's own videos are (app/utils/videos.py);
  * what is said in it is transcribed;
  * a post of several photos is looked at photo by photo.

Instagram hides most of this from anyone not signed in, and a story is never
public at all. So when the embed page will not give the media, a signed-in
Instagram account is asked to fetch it: its runner opens the post in its own
browser, saves the file beside the app's other temporary media, and says where
(the "fetch" request in instagram_runner.js). With no Instagram account running,
the caption and the picture are all there is, and the note says as much.

Each one is watched once. What was seen is kept in cache/instagram_watched/<code>.json
for a month, for every account and for the panel (the Chats tab shows it on the
card). At most two at a time, and never for long. Settings:
instagram.watch.enabled for Instagram links, on every platform; bot.videos
(listen, max_seconds) for how.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from app.utils import instagramlinks, videowatch

MAX_VIDEO_BYTES = 40_000_000
MAX_PHOTO_BYTES = 8_000_000
PHOTOS = 4
# The whole watch, page to caption: past this, the reply goes on with the caption and the picture.
TIMEOUT = 90.0
KEEP_DAYS = 30
KEEP_MAX = 500
# One that could not be read is not tried again for every message that has it.
_MISSED_FOR = 600
# How long a signed-in account is given to open a post and save its file.
FETCH_TIMEOUT = 85.0

_missed: dict = {}
_state: dict = {}
_CODE = re.compile(r"^[A-Za-z0-9_-]{5,24}$")


def settings() -> dict:
    """Whether Instagram links are watched (instagram.watch.enabled), and how: listening, how much of a long one
    (bot.videos, as for every video people send)."""
    out = dict(videowatch.settings())
    out["enabled"] = True
    try:
        from app.utils.helpers import load_config
        raw = (load_config().get("instagram") or {}).get("watch")
    except Exception:
        raw = None
    if isinstance(raw, dict) and raw.get("enabled") is not None:
        out["enabled"] = bool(raw["enabled"])
    return out


def key_of(url: str) -> str:
    """What this link is kept under: a post's own code, or "story_<user>_<id>" for a story."""
    code = instagramlinks.shortcode(url)
    if code:
        return code
    who, sid = instagramlinks.story_of(url)
    return f"story_{who.replace('.', '-')}_{sid}" if who and sid else ""


# ── What was seen, kept ───────────────────────────────────────────────────────

def cache_dir() -> Path:
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "instagram_watched"


def cached(key: str) -> dict | None:
    """What was seen of this post, when it was watched in the last month."""
    key = str(key or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,80}", key):
        return None
    path = cache_dir() / f"{key}.json"
    try:
        if time.time() - path.stat().st_mtime > KEEP_DAYS * 86400:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("key") == key else None


def keep(w: dict) -> None:
    """Remember what was seen; the oldest go past a few hundred, or after a month."""
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{w['key']}.part"
    tmp.write_text(json.dumps(w, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, folder / f"{w['key']}.json")
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    now = time.time()
    for i, p in enumerate(files):
        try:
            if i >= KEEP_MAX or now - p.stat().st_mtime > KEEP_DAYS * 86400:
                p.unlink()
        except OSError:
            pass


def seen_for(url: str) -> dict | None:
    """What was seen of the Instagram link, when it has been watched (for the panel: reads the cache only)."""
    key = key_of(url)
    return cached(key) if key else None


# ── Asking a signed-in account to fetch it ────────────────────────────────────

def _instagram_targets() -> list:
    try:
        from app.core import ipc
        return [m["target"] for m in ipc.discover_targets().values() if m["platform"] == "instagram"]
    except Exception:
        return []


async def _fetch_signed_in(url: str, account: int = 0) -> dict:
    """A signed-in Instagram account asked to open this post and save its media: {file, kind, facts} or {}. `account`
    asks that one first (the account whose own DM it came in). Nothing when no Instagram account answers."""
    from app.core import ipc
    targets = _instagram_targets()
    if account:
        mine = ipc.browser_target("instagram", int(account))
        targets = [mine] + [t for t in targets if t != mine]
    for target in targets[:3]:
        try:
            r = await ipc.send_and_wait(target, "insta_fetch", {"url": url}, timeout=FETCH_TIMEOUT)
        except Exception:
            r = None
        if r and r.get("ok") and r.get("file"):
            return {"file": str(r["file"]), "kind": str(r.get("kind") or ""), "facts": r.get("facts") or {}}
    return {}


def _read_file(path: str, limit: int) -> bytes:
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > limit:
            return b""
        return p.read_bytes()
    except OSError:
        return b""


def _forget_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


# ── Watching ──────────────────────────────────────────────────────────────────

def _loop_state() -> dict:
    """The locks of the loop this runs on: one watch per post at a time, two posts at once at most."""
    loop = asyncio.get_running_loop()
    if _state.get("loop") is not loop:
        _state.clear()
        _state.update(loop=loop, gate=asyncio.Semaphore(2), locks={})
    locks = _state["locks"]
    if len(locks) > 200:
        for key in [k for k, lock in locks.items() if not lock.locked()]:
            locks.pop(key, None)
    return _state


async def _watch(url: str, key: str, cfg: dict, account: int) -> dict | None:
    from app.utils import videos
    info = await instagramlinks.lookup(url)
    w = {
        "key": key, "url": url, "id": str(info.get("id") or instagramlinks.shortcode(url)),
        "kind": info.get("kind") or instagramlinks.kind_of(url) or "post",
        "author": str(info.get("author") or ""), "name": str(info.get("name") or ""),
        "verified": bool(info.get("verified")), "caption": str(info.get("caption") or ""),
        "thumbnail": str(info.get("thumbnail") or ""), "likes": int(info.get("likes") or 0),
        "comments": int(info.get("comments") or 0), "views": int(info.get("views") or 0),
        "duration": int(info.get("duration") or 0), "created": int(info.get("created") or 0),
        "photos": len(info.get("photos") or []), "signed_in": False, "seen": "", "said": "",
    }
    board, sound = b"", None
    # The embed page's own video, when it gives one: nothing has to be signed in for that.
    if info.get("video") and videos.available():
        blob = await videowatch.download(info["video"], MAX_VIDEO_BYTES,
                                         {"referer": "https://www.instagram.com/"})
        if blob:
            board, sound, dur = await asyncio.to_thread(videowatch.look_video, blob, cfg, ".mp4")
            if dur and not w["duration"]:
                w["duration"] = int(dur)
    elif not info.get("is_video") and (info.get("photos") or info.get("thumbnail")):
        urls = [u for u in (info.get("photos") or [info.get("thumbnail")]) if u][:PHOTOS]
        blobs = [await videowatch.download(u, MAX_PHOTO_BYTES, {"referer": "https://www.instagram.com/"})
                 for u in urls]
        blobs = [b for b in blobs if b]
        if blobs:
            board = await asyncio.to_thread(videowatch.look_photos, blobs)
    # Nothing came of the public page (a story, a reel Instagram will not embed, a private account): the account's
    # own browser opens it instead.
    if not board:
        got = await _fetch_signed_in(url, account)
        if got.get("file"):
            w["signed_in"] = True
            path = got["file"]
            suffix = os.path.splitext(path)[1].lower() or ".mp4"
            try:
                if suffix in (".jpg", ".jpeg", ".png", ".webp"):
                    blob = await asyncio.to_thread(_read_file, path, MAX_PHOTO_BYTES)
                    if blob:
                        board = await asyncio.to_thread(videowatch.look_photos, [blob])
                elif videos.available():
                    blob = await asyncio.to_thread(_read_file, path, MAX_VIDEO_BYTES)
                    if blob:
                        board, sound, dur = await asyncio.to_thread(videowatch.look_video, blob, cfg, suffix)
                        if dur and not w["duration"]:
                            w["duration"] = int(dur)
            finally:
                await asyncio.to_thread(_forget_file, path)
            for field in ("author", "caption", "kind"):
                if not w.get(field) and got["facts"].get(field):
                    w[field] = str(got["facts"][field])
    if sound:
        try:
            w["said"] = await videowatch.heard(sound)
        except Exception:
            w["said"] = ""
    if board:
        try:
            w["seen"] = await videowatch.caption(board, w["said"], "video" if w["kind"] == "reel" else "photo")
        except Exception:
            w["seen"] = ""
    # Nothing at all: not even the page would say what it is.
    return w if (w["seen"] or w["said"] or w["caption"] or w["author"]) else None


async def watch(url: str, account: int = 0) -> dict | None:
    """One Instagram post, reel or story, watched: what its page says of it with "seen", what is in it, and "said",
    what is said in it. Only its facts when it could be read but not watched; None when not even that, or watching
    is off. `account` is the Instagram account whose DM it came in, asked first when it has to be opened signed in."""
    cfg = settings()
    url = (url or "").strip()
    if not cfg["enabled"] or not url:
        return None
    key = key_of(url)
    if not key:
        return None
    hit = await asyncio.to_thread(cached, key)
    if hit:
        return hit
    if time.time() - _missed.get(key, 0) < _MISSED_FOR:
        return None
    st = _loop_state()
    lock = st["locks"].setdefault(key, asyncio.Lock())
    # Everything under the lock, the keeping too: whoever waited on it finds what was seen (or that it would not open).
    async with lock:
        hit = await asyncio.to_thread(cached, key)
        if hit:
            return hit
        if time.time() - _missed.get(key, 0) < _MISSED_FOR:
            return None
        async with st["gate"]:
            started = time.time()
            try:
                w = await asyncio.wait_for(_watch(url, key, cfg, account), TIMEOUT)
            except Exception:
                w = None
        if not w:
            _missed[key] = time.time()
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
                log_system(f"Watched @{w['author'] or 'someone'}'s Instagram {w['kind']} "
                           f"({time.time() - started:.0f}s): {w['seen'][:90]}")
            except Exception:
                pass
    return w


# ── Saying it to the model ────────────────────────────────────────────────────

def count_str(n: int) -> str:
    """2567 as it is, 458300 as 458K, 1250000 as 1.2M: as Instagram shows its numbers."""
    n = int(n or 0)
    for unit, size in (("B", 10 ** 9), ("M", 10 ** 6), ("K", 10 ** 3)):
        if n >= max(size, 10_000):
            whole, tenth = divmod(n * 10 // size, 10)
            return f"{whole}.{tenth}{unit}" if tenth else f"{whole}{unit}"
    return str(n)


def summary(w: dict, lead: str = "the reel they shared", now: float | None = None, react: bool = True) -> str:
    """One bracketed note for the model about an Instagram post: what it is and, when it was watched, what is in it
    and what is said in it. `lead` names it: "the reel they shared", "their newest post", "their story"."""
    from app.utils import tiktokwatch           # ago() and _clip(): the same words for both
    kind = w.get("kind") or "post"
    who = "@" + w["author"] if w.get("author") else "someone"
    if w.get("name") and w["name"].lower() != (w.get("author") or "").lower():
        who += f" ({tiktokwatch._clip(w['name'], 40)})"
    bits = []
    if w.get("created"):
        bits.append("posted " + tiktokwatch.ago(w["created"], now))
    if kind != "reel" and w.get("photos", 0) > 1:
        bits.append(f"{w['photos']} photos")
    elif w.get("duration"):
        d = int(w["duration"])
        bits.append(f"{d} seconds long" if d < 90 else f"{round(d / 60)} minutes long")
    for key, label in (("views", "views"), ("likes", "likes"), ("comments", "comments")):
        if w.get(key):
            bits.append(f"{count_str(w[key])} {label}")
    watched = bool(w.get("seen") or w.get("said"))
    still = kind != "reel" and not w.get("duration")
    verb = ("You looked at" if still else "You watched") if watched else "About"
    out = f"[{verb} {lead}: by {who}"
    if bits:
        out += ", " + ", ".join(bits)
    out += "."
    if w.get("caption"):
        out += f' Caption: "{tiktokwatch._clip(w["caption"], 220)}".'
    if w.get("seen"):
        out += (" What is in it: " if still else " What happens in it: ") + w["seen"].rstrip(".") + "."
    if w.get("said"):
        out += f' What is said in it: "{tiktokwatch._clip(w["said"], 300)}".'
    if not watched:
        out += (" Instagram would not let it be watched without being signed in, so this is all there is about it: "
                "do not pretend to have seen it.")
    elif react:
        out += " React to it like someone who just watched it; do not describe it back to them."
    return out + "]"


async def enrich(content: str, account: int = 0) -> tuple[str, str, bool]:
    """(the message with a note about each Instagram link in it, a picture for the vision model or "", whether one
    was watched). A watched one needs no picture: its frames were already looked at."""
    urls = instagramlinks.links_in(content)
    if not urls:
        return content, "", False
    from app.utils import ai
    if ai.REALTIME.get() or not settings()["enabled"]:
        text, cover = await instagramlinks.enrich(content)
        return text, cover, False
    lines, cover, watched = [], "", False
    for i, url in enumerate(urls):
        w = await watch(url, account) if i < 2 else None
        if w:
            lead = {"reel": "the reel they shared", "story": "the story they shared"}.get(w.get("kind"),
                                                                                         "the post they shared")
            lines.append(summary(w, lead=lead))
            if w.get("seen") or w.get("said"):
                watched = True
            elif not cover and str(w.get("thumbnail") or "").startswith("https://"):
                cover = w["thumbnail"]
            continue
        info = await instagramlinks.lookup(url)
        line = instagramlinks.describe(info)
        if line:
            lines.append(line)
        if not cover and str(info.get("thumbnail") or "").startswith("https://"):
            cover = info["thumbnail"]
    return (content + ("\n" + "\n".join(lines) if lines else "")), cover, watched
