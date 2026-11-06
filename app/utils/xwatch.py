"""A post on X, read: what it says, who wrote it, and what it carries.

Somebody sends an x.com link, in an X message or on any other platform, and the persona should know what is in it
rather than answer "nice link". X shows a signed-out visitor almost nothing, so the post is opened in the account's
own signed-in browser: its runner is asked over IPC (x_thread, x_fetch), exactly as Instagram's links are read
through its runner (app/utils/instagramwatch.py).

Each post is read once and kept, so the same link sent twice costs one read. What it carries - a picture, a video -
is watched by whatever bot.videos says to watch with, the same as everywhere else.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

#: An x.com or twitter.com link to one post. A post's number is long now, but the old ones are short - the first
#: post on the site is /status/20 - so any run of digits counts.
LINK = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/[A-Za-z0-9_]{1,15}/status/(\d{1,25})",
                  re.IGNORECASE)
KEEP = 400


def settings(config: dict | None = None) -> dict:
    """The x.watch block, with the defaults the shipped config carries."""
    if config is None:
        from app.utils.helpers import load_config
        try:
            config = load_config()
        except Exception:
            config = {}
    block = ((config or {}).get("x") or {}).get("watch") or {}
    return {
        "enabled": bool(block.get("enabled", True)),
        "their_posts": bool(block.get("their_posts", True)),
        "threads": bool(block.get("threads", True)),
    }


def links(text: str, most: int = 2) -> list[str]:
    """The posts in a message, each once, at most `most`: they are what gets read."""
    out = []
    for m in LINK.finditer(str(text or "")):
        url = m.group(0).split("?")[0]
        if url not in out:
            out.append(url)
        if len(out) >= most:
            break
    return out


def post_id(url: str) -> str:
    m = LINK.search(str(url or ""))
    return m.group(1) if m else ""


def _store() -> Path:
    from app.utils.paths import DATA_DIR
    p = DATA_DIR / "cache" / "x_people"
    p.mkdir(parents=True, exist_ok=True)
    return p / "watched.json"


def _read_all() -> dict:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cached(url: str) -> dict | None:
    """A post already read, or None."""
    pid = post_id(url)
    return _read_all().get(pid) if pid else None


def remember(url: str, found: dict) -> None:
    pid = post_id(url)
    if not pid:
        return
    all_of = _read_all()
    all_of[pid] = {**found, "at": time.time()}
    # The newest few hundred: a cache, not a record.
    if len(all_of) > KEEP:
        for key in sorted(all_of, key=lambda k: all_of[k].get("at", 0))[:len(all_of) - KEEP]:
            all_of.pop(key, None)
    try:
        from app.utils.atomic import write_json_atomic
        write_json_atomic(_store(), all_of)
    except Exception:
        pass


def count_str(n) -> str:
    """40200 as "40.2K", the way X writes it."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


def summary(found: dict, lead: str = "the post", react: bool = True) -> str:
    """One bracketed line about a post, for the model to read. Nothing of X's wording, only what it said."""
    if not found:
        return ""
    who = str(found.get("handle") or "").lstrip("@")
    bits = [f"@{who}" if who else "someone"]
    counts = found.get("counts") or {}
    if counts.get("likes"):
        bits.append(f"{count_str(counts['likes'])} likes")
    if found.get("media"):
        kinds = {m.get("kind") for m in found["media"] if isinstance(m, dict)}
        bits.append("with a video" if "video" in kinds else "with a picture")
    words = " ".join(str(found.get("text") or "").split())[:280]
    out = f"[{lead}, by " + ", ".join(bits) + "]"
    if words:
        out += f' It says: "{words}".'
    seen = str(found.get("seen") or "").strip()
    if seen:
        out += f" What is in it: {seen[:400]}."
    under = [str(r.get("text") or "") for r in (found.get("replies") or []) if isinstance(r, dict)][:3]
    under = [" ".join(u.split())[:120] for u in under if u.strip()]
    if under:
        out += " Underneath, people are saying: " + "; ".join(f'"{u}"' for u in under) + "."
    if react:
        out += " Say what you think of it, the way you would to a friend who sent it."
    return out


async def watch(url: str, account: int = 0) -> dict | None:
    """One X post, read in the account's own signed-in browser. None when watching is off, the link is not one, or
    nothing could be read. `account` is the X account to ask; 0 asks the first one running."""
    cfg = settings()
    url = (url or "").strip()
    if not cfg["enabled"] or not post_id(url):
        return None
    was = cached(url)
    if was:
        return was

    from app.core import ipc
    n = int(account or 1)
    target = ipc.browser_target("x", n)
    found: dict = {}
    try:
        r = await ipc.send_and_wait(target, "x_thread", {"url": url}, timeout=70.0)
    except Exception:
        r = None
    posts = (r or {}).get("posts") or []
    if not posts:
        return None
    # The first one is the post itself; what follows is said underneath it.
    head = posts[0] if isinstance(posts[0], dict) else {}
    found = {
        "url": url,
        "handle": head.get("handle") or "",
        "name": head.get("name") or "",
        "text": head.get("text") or "",
        "media": head.get("media") or [],
        "counts": head.get("counts") or {},
        "at": head.get("at") or 0,
    }
    if cfg["threads"]:
        found["replies"] = [{"handle": p.get("handle"), "text": p.get("text")}
                            for p in posts[1:6] if isinstance(p, dict) and p.get("text")]
    # A picture or a video on it, looked at the same way the persona looks at everything else (bot.videos): the
    # runner saves the file out of its signed-in browser, and videowatch turns it into words.
    media = [m for m in found["media"] if isinstance(m, dict) and m.get("url")]
    if media:
        found["seen"] = await _look_at(target, media[0]["url"])
    remember(url, found)
    return found


async def _look_at(target, media_url: str) -> str:
    """One picture or video off a post, in words. "" when there is nothing to look with, or nothing came back."""
    import asyncio
    import os

    from app.core import ipc
    from app.utils import videos, videowatch
    try:
        got = await ipc.send_and_wait(target, "x_fetch", {"url": media_url}, timeout=90.0)
    except Exception:
        got = None
    path = (got or {}).get("file") if (got or {}).get("ok") else ""
    if not path or not os.path.exists(path):
        return ""
    suffix = os.path.splitext(path)[1].lower() or ".jpg"
    try:
        from app.utils.helpers import load_config
        cfg = (load_config() or {}).get("bot", {}).get("videos", {}) or {}
        board = b""
        if suffix in (".jpg", ".jpeg", ".png", ".webp"):
            blob = await asyncio.to_thread(lambda: open(path, "rb").read())
            board = await asyncio.to_thread(videowatch.look_photos, [blob]) if blob else b""
        elif videos.available():
            blob = await asyncio.to_thread(lambda: open(path, "rb").read())
            if blob:
                board, _sound, _dur = await asyncio.to_thread(videowatch.look_video, blob, cfg, suffix)
        if not board:
            return ""
        return await videowatch.caption(board, "", "video" if suffix not in (".jpg", ".jpeg", ".png", ".webp")
                                        else "photo")
    except Exception:
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
