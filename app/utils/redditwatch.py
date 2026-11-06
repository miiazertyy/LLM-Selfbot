"""A post on Reddit, read: its title, who wrote it, where, and what people said under it.

Somebody sends a reddit.com link, in a Reddit chat or on any other platform, and the persona should know what is in
it rather than answer "nice link". Reddit shows a signed-out visitor less and less, so the post is opened in the
account's own signed-in browser: its runner is asked over IPC (reddit_thread, reddit_fetch), exactly as X's links
are read through its runner (app/utils/xwatch.py).

Reddit is the one platform here where the comments are usually the point: a link to a thread is a link to the
argument under it, not to the thing itself. So what comes back carries the top comments, and the summary says what
they are saying.

Each post is read once and kept, so the same link sent twice costs one read. What it carries - a picture, a video -
is watched by whatever bot.videos says to watch with, the same as everywhere else.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

#: A link to one Reddit post, however it was written: the full permalink, a link to one comment under it, the
#: /comments/<id> short form, or a redd.it link. Reddit's ids are base 36 and have grown from four characters to
#: seven, so any run of them counts.
LINK = re.compile(
    r"https?://(?:(?:www|old|new|np|i|m)\.)?reddit\.com/(?:r/[A-Za-z0-9_]{2,21}/)?comments/([a-z0-9]{2,12})"
    r"|https?://redd\.it/([a-z0-9]{2,12})",
    re.IGNORECASE)
KEEP = 400


def settings(config: dict | None = None) -> dict:
    """The reddit.watch block, with the defaults the shipped config carries."""
    if config is None:
        from app.utils.helpers import load_config
        try:
            config = load_config()
        except Exception:
            config = {}
    block = ((config or {}).get("reddit") or {}).get("watch") or {}
    return {
        "enabled": bool(block.get("enabled", True)),
        "their_posts": bool(block.get("their_posts", True)),
        "threads": bool(block.get("threads", True)),
        "links": bool(block.get("links", True)),
    }


def links(text: str, most: int = 2) -> list[str]:
    """The posts in a message, each once, at most `most`: they are what gets read."""
    out, seen = [], set()
    for m in LINK.finditer(str(text or "")):
        url = m.group(0).split("?")[0]
        pid = (m.group(1) or m.group(2) or "").lower()
        if pid in seen:
            continue
        seen.add(pid)
        out.append(url)
        if len(out) >= most:
            break
    return out


def post_id(url: str) -> str:
    """The post's own id, which is the same whichever way the link was written."""
    m = LINK.search(str(url or ""))
    return (m.group(1) or m.group(2)).lower() if m else ""


def subreddit(url: str) -> str:
    """The subreddit a link names, without the r/, or "" when the link does not carry one."""
    m = re.search(r"reddit\.com/r/([A-Za-z0-9_]{2,21})", str(url or ""), re.IGNORECASE)
    return m.group(1) if m else ""


def _store() -> Path:
    from app.utils.paths import DATA_DIR
    p = DATA_DIR / "cache" / "reddit_people"
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
    """40200 as "40.2k", the way Reddit writes it: a small k, unlike X's."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if abs(n) < 1000:
        return str(n)
    if abs(n) < 1_000_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n / 1_000_000:.1f}m".replace(".0m", "m")


def summary(found: dict, lead: str = "the post", react: bool = True) -> str:
    """One bracketed line about a post, for the model to read. Nothing of Reddit's wording, only what it said."""
    if not found:
        return ""
    who = str(found.get("author") or "").lstrip("u/")
    sub = str(found.get("subreddit") or "").lstrip("r/")
    bits = [f"u/{who}" if who else "someone"]
    if sub:
        bits.append(f"in r/{sub}")
    if found.get("score"):
        bits.append(f"{count_str(found['score'])} upvotes")
    if found.get("comments"):
        bits.append(f"{count_str(found['comments'])} comments")
    if found.get("media"):
        kinds = {m.get("kind") for m in found["media"] if isinstance(m, dict)}
        bits.append("with a video" if "video" in kinds else "with a picture")
    out = f"[{lead}, by " + ", ".join(bits) + "]"
    title = " ".join(str(found.get("title") or "").split())[:300]
    if title:
        out += f' It is titled: "{title}".'
    words = " ".join(str(found.get("text") or "").split())[:600]
    if words:
        out += f' It says: "{words}".'
    seen = str(found.get("seen") or "").strip()
    if seen:
        out += f" What is in it: {seen[:400]}."
    # On Reddit the comments are usually the thing being shared, so they get more room than X's replies do.
    under = [c for c in (found.get("comments_said") or []) if isinstance(c, dict) and str(c.get("text") or "").strip()]
    if under:
        said = [f'u/{str(c.get("author") or "someone").lstrip("u/")}: "{" ".join(str(c["text"]).split())[:160]}"'
                for c in under[:4]]
        out += " Underneath, people are saying: " + "; ".join(said) + "."
    if react:
        out += " Say what you think of it, the way you would to a friend who sent it."
    return out


async def watch(url: str, account: int = 0) -> dict | None:
    """One Reddit post, read in the account's own signed-in browser. None when watching is off, the link is not
    one, or nothing could be read. `account` is the Reddit account to ask; 0 asks the first one running."""
    cfg = settings()
    url = (url or "").strip()
    if not cfg["enabled"] or not post_id(url):
        return None
    was = cached(url)
    if was:
        return was

    from app.core import ipc
    n = int(account or 1)
    target = ipc.browser_target("reddit", n)
    try:
        r = await ipc.send_and_wait(target, "reddit_thread", {"url": url}, timeout=70.0)
    except Exception:
        r = None
    post = (r or {}).get("post") or {}
    if not isinstance(post, dict) or not (post.get("title") or post.get("text")):
        return None
    found = {
        "url": url,
        "id": post.get("id") or post_id(url),
        "author": post.get("author") or "",
        "subreddit": post.get("subreddit") or subreddit(url),
        "title": post.get("title") or "",
        "text": post.get("text") or "",
        "media": post.get("media") or [],
        "score": post.get("score") or 0,
        "comments": post.get("comments") or 0,
        "at": post.get("at") or 0,
    }
    if cfg["threads"]:
        said = (r or {}).get("comments") or []
        found["comments_said"] = [{"author": c.get("author"), "text": c.get("text"), "score": c.get("score")}
                                  for c in said[:6] if isinstance(c, dict) and c.get("text")]
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
        got = await ipc.send_and_wait(target, "reddit_fetch", {"url": media_url}, timeout=90.0)
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
