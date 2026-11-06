"""app/utils/instagramlinks.py - what an Instagram link is, from the page anyone can see.

Instagram has no oEmbed a person's app may use any more, but every public post
and reel still has an embed page, /p/<code>/embed/captioned/, which nobody has
to be signed in to read: it carries the caption, who posted it, the picture, and
for a reel the video itself. That is enough to say what a link is when there is
no Instagram account to look with (a link on Discord, say), and it is where
app/utils/instagramwatch.py starts before it watches one properly.

A private post, or one Instagram has decided to hide from embeds, says nothing:
the caller then falls back to the note the watcher writes, or to nothing.

Nothing here signs anything in, and nothing here needs an Instagram account.
"""
from __future__ import annotations

import html as _html
import json
import re

from app.utils import videowatch

HEADERS = {**videowatch.HEADERS, "accept": "text/html,application/xhtml+xml"}

# A post, a reel (/reel/ and the older /reels/), an IGTV page, and the share links that lead to one.
_LINK = re.compile(
    r"https?://(?:(?:www|m)\.)?instagram\.com/(?:[A-Za-z0-9._]{1,30}/)?"
    r"(?:p|reel|reels|tv)/[A-Za-z0-9_-]{5,24}/?(?:\?[^\s]*)?"
    r"|https?://(?:(?:www|m)\.)?instagram\.com/share/(?:p/|reel/)?[A-Za-z0-9_-]{5,40}/?"
    r"|https?://(?:(?:www|m)\.)?instagram\.com/stories/[A-Za-z0-9._]{1,30}/\d{6,25}/?(?:\?[^\s]*)?",
    re.I)
_CODE = re.compile(r"instagram\.com/(?:[A-Za-z0-9._]{1,30}/)?(p|reel|reels|tv)/([A-Za-z0-9_-]{5,24})", re.I)
_STORY = re.compile(r"instagram\.com/stories/([A-Za-z0-9._]{1,30})/(\d{6,25})", re.I)
# The embed page's own data, under whichever key the build of the day uses.
_EXTRA = re.compile(r"window\.__additionalDataLoaded\s*\(\s*'[^']*'\s*,\s*(\{.*?\})\s*\)\s*;", re.S)


def links_in(text: str) -> list[str]:
    """The Instagram links in a message, each once, at most three: they get a card and a watch."""
    out: list[str] = []
    for m in _LINK.finditer(str(text or "")):
        url = m.group(0).rstrip(".,);!?\"'")
        if url not in out:
            out.append(url)
    return out[:3]


def shortcode(url: str) -> str:
    """The post's own code ("DBx1y2zAbc") out of a link; "" for a story or anything else."""
    m = _CODE.search(str(url or ""))
    return m.group(2) if m else ""


def story_of(url: str) -> tuple[str, str]:
    """(whose story, which one) out of a story link; ("", "") for anything else."""
    m = _STORY.search(str(url or ""))
    return (m.group(1).lower(), m.group(2)) if m else ("", "")


def kind_of(url: str) -> str:
    """"reel", "post" or "story", as the link itself says."""
    m = _CODE.search(str(url or ""))
    if m:
        return "reel" if m.group(1).lower() in ("reel", "reels") else "post"
    return "story" if _STORY.search(str(url or "")) else ""


def embed_url(code: str) -> str:
    return f"https://www.instagram.com/p/{code}/embed/captioned/"


def canonical(code: str, kind: str = "post") -> str:
    return f"https://www.instagram.com/{'reel' if kind == 'reel' else 'p'}/{code}/"


def _dig(data, *keys):
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return None
    return data


def _media_of(blob: dict) -> dict:
    """The post inside the embed page's data, whichever shape it came in."""
    for path in (("shortcode_media",), ("graphql", "shortcode_media"), ("gql_data", "shortcode_media"),
                 ("data", "shortcode_media"), ("context", "media")):
        media = _dig(blob, *path)
        if isinstance(media, dict) and (media.get("shortcode") or media.get("id")):
            return media
    return {}


def _caption_of(media: dict) -> str:
    edges = _dig(media, "edge_media_to_caption", "edges")
    if isinstance(edges, list) and edges:
        text = _dig(edges[0], "node", "text")
        if isinstance(text, str):
            return " ".join(text.split())
    for key in ("caption", "accessibility_caption"):
        if isinstance(media.get(key), str):
            return " ".join(media[key].split())
    return ""


def _children(media: dict) -> list[dict]:
    edges = _dig(media, "edge_sidecar_to_children", "edges")
    if not isinstance(edges, list):
        return []
    return [e["node"] for e in edges if isinstance(e, dict) and isinstance(e.get("node"), dict)]


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def facts(page_html: str, url: str = "") -> dict:
    """What an embed page says of a post: whose, its caption, whether it is a video, its picture and its video. {}
    when the page says nothing (a private or removed post, or one Instagram will not embed)."""
    media: dict = {}
    for m in _EXTRA.finditer(page_html or ""):
        try:
            media = _media_of(json.loads(m.group(1)))
        except ValueError:
            media = {}
        if media:
            break
    code = shortcode(url)
    if media:
        owner = media.get("owner") if isinstance(media.get("owner"), dict) else {}
        kids = _children(media)
        is_video = bool(media.get("is_video")) or any(k.get("is_video") for k in kids)
        photos = [str(k.get("display_url") or "") for k in kids if str(k.get("display_url") or "").startswith("https://")]
        out = {
            "id": str(media.get("shortcode") or code or media.get("id") or ""),
            "kind": "reel" if (media.get("product_type") in ("clips", "igtv") or
                               (is_video and not kids)) else "post",
            "author": str(owner.get("username") or "").lower(),
            "name": str(owner.get("full_name") or ""),
            "verified": bool(owner.get("is_verified")),
            "caption": _caption_of(media),
            "is_video": is_video,
            "thumbnail": str(media.get("display_url") or media.get("thumbnail_src") or (photos[0] if photos else "")),
            "video": str(media.get("video_url") or next((str(k.get("video_url") or "") for k in kids
                                                         if k.get("video_url")), "")),
            "photos": photos[:4] or ([str(media.get("display_url") or "")] if media.get("display_url") else []),
            "likes": _int(_dig(media, "edge_media_preview_like", "count") or media.get("like_count")),
            "comments": _int(_dig(media, "edge_media_to_comment", "count") or media.get("comment_count")),
            "views": _int(media.get("video_view_count") or media.get("play_count")),
            "duration": int(float(media.get("video_duration") or 0)),
            "created": _int(media.get("taken_at_timestamp")),
            "seen": "",
            "said": "",
        }
        out["url"] = canonical(out["id"], out["kind"]) if out["id"] else (url or "")
        return out if out["id"] or out["caption"] or out["thumbnail"] else {}

    # No data on the page: its own markup. The captioned embed writes the caption in a block of its own, with the
    # account above it and the picture beside it.
    title = videowatch._meta(page_html, "title")
    image = videowatch._meta(page_html, "image")
    if not image:
        m = re.search(r'class="EmbeddedMediaImage"[^>]+src="([^"]+)"', page_html or "")
        image = _html.unescape(m.group(1)) if m else ""
    who = re.search(r'class="(?:UsernameText|Username)"[^>]*>([^<]{1,40})<', page_html or "")
    cap = re.search(r'class="Caption"[^>]*>(.*?)</div>', page_html or "", re.S)
    caption = ""
    if cap:
        caption = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", cap.group(1))).split())
        # The block starts with the account and ends with a time: the words between are the caption.
        caption = re.sub(r"^\s*[A-Za-z0-9._]{1,30}\s*", "", caption)
    if not image and not caption and not title:
        return {}
    author = (who.group(1).strip().lstrip("@").lower() if who else "")
    if not author:
        m = re.search(r"([A-Za-z0-9._]{1,30})\s+on Instagram", title or "")
        author = m.group(1).lower() if m else ""
    return {
        "id": code, "url": url or (canonical(code) if code else ""), "kind": kind_of(url) or "post",
        "author": author, "name": "", "verified": False, "caption": caption or title,
        "is_video": bool(re.search(r'class="EmbeddedMediaVideo"|is_video', page_html or "")),
        "thumbnail": image if image.startswith("https://") else "", "video": "",
        "photos": [image] if image.startswith("https://") else [],
        "likes": 0, "comments": 0, "views": 0, "duration": 0, "created": 0, "seen": "", "said": "",
    }


async def lookup(url: str) -> dict:
    """What Instagram's embed page says of a link, {} when it says nothing. One request, signed in to nothing."""
    code = shortcode(url)
    if not code:
        return {}
    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=HEADERS) as client:
            r = await client.get(embed_url(code))
            if r.status_code != 200:
                return {}
            got = facts(r.text, url)
    except Exception:
        return {}
    if got and not got.get("kind"):
        got["kind"] = kind_of(url) or "post"
    return got


def describe(info: dict) -> str:
    """One line about a link that could not be watched, as its page describes it."""
    if not info:
        return ""
    who = f"@{info['author']}" if info.get("author") else "someone"
    what = "reel" if info.get("kind") == "reel" else "post"
    line = f"[About the Instagram {what} they shared: by {who}"
    if info.get("name") and info["name"].lower() != (info.get("author") or ""):
        line += f" ({videowatch._clip(info['name'], 40)})"
    if info.get("caption"):
        line += f'. Caption: "{videowatch._clip(info["caption"], 220)}"'
    return line + ".]"


async def enrich(content: str) -> tuple[str, str]:
    """(the message with a line about each Instagram link in it, a picture for the vision model or ""). Used when
    nothing can watch them properly."""
    urls = links_in(content)
    if not urls:
        return content, ""
    lines, cover = [], ""
    for url in urls[:2]:
        info = await lookup(url)
        line = describe(info)
        if line:
            lines.append(line)
        if not cover and str(info.get("thumbnail") or "").startswith("https://"):
            cover = info["thumbnail"]
    return (content + ("\n" + "\n".join(lines) if lines else "")), cover
