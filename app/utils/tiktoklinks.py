"""app/utils/tiktoklinks.py - what a shared TikTok is, so the persona can answer it.

Someone sends a TikTok (in a TikTok DM, or as a link on Discord or Snapchat)
and the message is only a link: the model had nothing to go on. TikTok's own
public oEmbed endpoint says what the video is, its caption and its author, and
gives its cover picture, all without signing in. The message the model reads
gets a line saying so, and the cover goes to the vision model when the message
has no picture of its own, so the persona can react to what it actually is.

Remembered for a while, so the same link shared twice is asked about once.
Nothing here ever fails a reply: no answer in a few seconds is no line.
"""
from __future__ import annotations

import re
import time

# www.tiktok.com/@who/video/123, /photo/123, and the short links the app shares (vm., vt., tiktok.com/t/).
_LINK = re.compile(r"https?://(?:(?:www|m)\.)?tiktok\.com/@[\w.]+/(?:video|photo)/\d+[^\s]*"
                   r"|https?://(?:vm|vt)\.tiktok\.com/[\w]+/?"
                   r"|https?://(?:www\.)?tiktok\.com/t/[\w]+/?", re.I)
_CACHE: dict = {}
_TTL = 6 * 3600
_MAX = 300


def links_in(text: str) -> list[str]:
    seen = []
    for m in _LINK.finditer(str(text or "")):
        url = m.group(0).rstrip(".,);!?\"'")
        if url not in seen:
            seen.append(url)
    return seen[:3]


def describe(info: dict) -> str:
    """One line for the model: whose TikTok it is and what its caption says."""
    if not info:
        return ""
    who = info.get("author_unique_id") or info.get("author_name") or ""
    title = re.sub(r"\s+", " ", str(info.get("title") or "")).strip()
    if len(title) > 220:
        title = title[:217].rstrip() + "..."
    if who and title:
        return f'[The TikTok they shared is by @{who}, captioned: "{title}"]'
    if who:
        return f"[The TikTok they shared is by @{who}]"
    if title:
        return f'[The TikTok they shared is captioned: "{title}"]'
    return ""


async def lookup(url: str, timeout: float = 6.0) -> dict:
    """TikTok's oEmbed for one link: {"title", "author_name", "author_unique_id", "thumbnail_url", "id"}, {} when it
    will not say. "id" is the post's, which a short link does not show."""
    now = time.time()
    hit = _CACHE.get(url)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    info: dict = {}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"}) as client:
            r = await client.get("https://www.tiktok.com/oembed", params={"url": url})
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    info = {k: str(data.get(k) or "") for k in ("title", "author_name", "author_unique_id", "thumbnail_url")}
                    info["id"] = str(data.get("embed_product_id") or "")
    except Exception:
        info = {}
    if len(_CACHE) >= _MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[url] = (now, info)
    return info


async def enrich(content: str) -> tuple[str, str]:
    """(the message with a line about each TikTok in it, the first one's cover picture or "")."""
    urls = links_in(content)
    if not urls:
        return content, ""
    lines, cover = [], ""
    for url in urls:
        info = await lookup(url)
        line = describe(info)
        if line:
            lines.append(line)
        if not cover and info.get("thumbnail_url", "").startswith("https://"):
            cover = info["thumbnail_url"]
    return (content + ("\n" + "\n".join(lines) if lines else "")), cover
