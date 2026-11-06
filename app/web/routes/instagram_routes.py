"""Instagram beyond the inbox, for the panel: what someone it talks to posts and whether they have a story up (the
Chats tab's posts), watching or answering a story, liking, saving and commenting on a post, what the account is doing
out there (Reels, what is left of today's likes, comments, stories and posts), its Note, and posting the persona's
pictures as a post, a reel or a story.

The Instagram runner does each in its out tab (app/platforms/snapchat/instagram_runner.js), asked through the bridge
(app/platforms/snapchat_bridge.py, _OUT_OPS). Manual actions here work whatever the automatic switches say: they are
the user's own, counted in the day's likes and comments but never refused by them.
"""
import asyncio
import os
import re

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc

router = APIRouter(tags=["instagram"])

_CHAT = re.compile(r"ig_[a-z0-9_-]{1,40}")
_POST = re.compile(r"https://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_-]{5,24}/?")
_USERNAME = re.compile(r"[a-z0-9._]{1,30}")
_AS = ("post", "reel", "story")


def _account(web_id: str) -> dict:
    """An Instagram account by its web id (instagram_1): its IPC target and number, or 404."""
    meta = ipc.discover_targets().get(str(web_id or ""))
    if not meta or meta.get("platform") != "instagram":
        raise HTTPException(status_code=404, detail="not an Instagram account")
    return meta


async def _ask(meta: dict, cmd: str, payload: dict, timeout: float) -> dict:
    result = await ipc.send_and_wait(meta["target"], cmd, payload, timeout=timeout)
    if result is None:
        raise HTTPException(status_code=504, detail="Instagram did not answer; is the account running?")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "Instagram would not do it")
    return result


def _post_url(value) -> str:
    url = str(value or "").strip().split("?")[0]
    if not _POST.fullmatch(url) and not _POST.fullmatch(url + "/"):
        raise HTTPException(status_code=400, detail="That is not an Instagram post link")
    return url


def _theirs(meta: dict, user_id: str) -> dict:
    """What someone an Instagram account talks to posts, as the runner last read their profile, and what the persona
    saw in the ones it watched."""
    from app.utils import instagramwatch, snappeople
    c = snappeople.contacts(meta["account"], "instagram").get(user_id) or {}
    posts = []
    for p in (c.get("posts") or [])[:9]:
        if not isinstance(p, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{5,24}", str(p.get("id") or "")):
            continue
        w = instagramwatch.cached(str(p["id"])) or {}
        cover = str(p.get("cover") or "")
        posts.append({
            "id": str(p["id"]), "url": str(p.get("url") or ""), "caption": str(p.get("caption") or "")[:300],
            "kind": "reel" if p.get("kind") == "reel" else "post", "pinned": bool(p.get("pinned")),
            "cover": cover if cover.startswith("https://") else "",
            "seen": str(w.get("seen") or ""), "said": str(w.get("said") or ""),
            "likes": int(w.get("likes") or 0), "created": int(w.get("created") or 0),
        })
    story = instagramwatch.cached(str(c.get("story_seen") or "")) or {}
    return {"username": snappeople.instagram_username(user_id), "name": str(c.get("name") or ""),
            "bio": str(c.get("bio") or "")[:400], "followers": c.get("followers"),
            "verified": bool(c.get("verified")), "private": bool(c.get("private")),
            "posts": posts, "posts_at": float(c.get("posts_at") or 0), "newest": str(c.get("newest") or ""),
            "story": {"at": float(c.get("story_at") or 0), "seen": str(story.get("seen") or ""),
                      "url": str(story.get("url") or "")} if c.get("story_seen") else None}


@router.get("/api/instagram/theirs")
def their_posts(target: str, user_id: str):
    """Their posts and the story of theirs it last watched. Plain def: it reads the runner's files."""
    meta = _account(target)
    if not _CHAT.fullmatch(str(user_id or "")):
        raise HTTPException(status_code=400, detail="which chat?")
    return _theirs(meta, user_id)


@router.post("/api/instagram/theirs/refresh")
async def their_posts_refresh(request: Request):
    """Their profile looked at again now, in the runner's out tab."""
    body = await request.json()
    meta = _account(body.get("target"))
    user_id = str(body.get("user_id") or "")
    if not _CHAT.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="which chat?")
    await _ask(meta, "insta_posts", {"user_id": user_id}, 80.0)
    return await asyncio.to_thread(_theirs, meta, user_id)


@router.get("/api/instagram/stories")
async def stories(target: str, user_id: str):
    """Whether they have a story up right now."""
    meta = _account(target)
    if not _CHAT.fullmatch(str(user_id or "")):
        raise HTTPException(status_code=400, detail="which chat?")
    return await _ask(meta, "insta_stories", {"user_id": user_id}, 60.0)


@router.post("/api/instagram/story")
async def story(request: Request):
    """Watch their story now, or answer it: `action` is "watch" or "reply", with `text` or `emoji` for a reply."""
    body = await request.json()
    meta = _account(body.get("target"))
    user_id = str(body.get("user_id") or "")
    if not _CHAT.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="which chat?")
    action = str(body.get("action") or "watch")
    if action not in ("watch", "reply"):
        raise HTTPException(status_code=400, detail="watch or reply")
    text = " ".join(str(body.get("text") or "").split())[:300]
    emoji = str(body.get("emoji") or "")[:8]
    if action == "reply" and not (text or emoji):
        raise HTTPException(status_code=400, detail="Write the reply first")
    return await _ask(meta, "insta_story", {"user_id": user_id, "action": action, "text": text, "emoji": emoji}, 120.0)


@router.post("/api/instagram/action")
async def post_action(request: Request):
    """Like, save or comment on a post, as the account, from the panel."""
    body = await request.json()
    meta = _account(body.get("target"))
    url = _post_url(body.get("url"))
    action = str(body.get("action") or "")
    if action not in ("like", "save", "comment"):
        raise HTTPException(status_code=400, detail="like, save or comment")
    text = " ".join(str(body.get("text") or "").split())[:150]
    if action == "comment" and not text:
        raise HTTPException(status_code=400, detail="Write the comment first")
    return await _ask(meta, "insta_action", {"url": url, "action": action, "text": text}, 150.0)


@router.post("/api/instagram/comment-text")
async def comment_text(request: Request):
    """A comment for a post, written by the persona after watching it, for the panel to show before it goes."""
    body = await request.json()
    meta = _account(body.get("target"))
    url = _post_url(body.get("url"))
    return await _ask(meta, "insta_comment_text", {"url": url, "why": "theirs"}, 150.0)


@router.get("/api/instagram/out")
async def out_status(target: str):
    """What the account is doing out there now, and what is left of today's likes, comments, stories and posts."""
    meta = _account(target)
    return await _ask(meta, "insta_out", {}, 25.0)


@router.post("/api/instagram/reels")
async def reels(request: Request):
    """A few minutes on Reels, now."""
    body = await request.json()
    return await _ask(_account(body.get("target")), "insta_reels", {}, 80.0)


@router.post("/api/instagram/follow")
async def follow(request: Request):
    """Follow someone by their username, as the account."""
    body = await request.json()
    meta = _account(body.get("target"))
    username = str(body.get("username") or "").strip().lstrip("@").lower()
    if not _USERNAME.fullmatch(username):
        raise HTTPException(status_code=400, detail="That is not an Instagram username")
    return await _ask(meta, "insta_follow", {"username": username}, 80.0)


@router.post("/api/instagram/note")
async def note(request: Request):
    """Set its Note. With nothing typed, the persona writes one from its mood."""
    body = await request.json()
    meta = _account(body.get("target"))
    text = " ".join(str(body.get("text") or "").split())[:60]
    return await _ask(meta, "insta_note", {"text": text}, 80.0)


# ── Posting the persona's pictures ───────────────────────────────────────────

def _media_file(persona: str, name: str):
    """One of a persona's pictures or videos on disk, by its name in the Pictures page; 404 when there is none."""
    from app.utils import personas, videos
    from app.utils.paths import DATA_DIR
    pid = str(persona or "").strip() or personas.DEFAULT
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    if os.path.basename(name) != name:
        raise HTTPException(status_code=400, detail="That is not a file in the Pictures page")
    video = videos.is_kept_video(name)
    if not video and not re.search(r"\.(png|jpe?g|webp)$", name, re.I):
        raise HTTPException(status_code=400, detail="Only a picture or a video can be posted")
    folder = DATA_DIR / "config" / "pictures" if pid == personas.DEFAULT else personas.pictures_dir(pid)
    path = folder / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file is not there any more")
    return pid, path, video


def _posting_cfg() -> dict:
    from app.utils.helpers import load_config
    return ((load_config().get("instagram") or {}).get("posting")) or {}


@router.get("/api/instagram/posting")
def posting_info():
    """Whether pictures can be posted from the panel, and the Instagram accounts that can (Settings, Instagram,
    Posting)."""
    cfg = _posting_cfg()
    accounts = sorted((k for k, v in ipc.discover_targets().items() if v.get("platform") == "instagram"),
                      key=lambda k: int(k.split("_")[1]))
    return {"enabled": bool(cfg.get("enabled", True)), "accounts": accounts, "as": list(_AS)}


def _caption_inputs(pid: str, name: str) -> tuple[str, str]:
    from app.utils import db, personas
    description = db.get_picture_description(name, persona=pid) or ""
    info = personas.get(pid) or {}
    return description, str(info.get("name") or pid)


@router.post("/api/instagram/caption")
async def caption(request: Request):
    """A caption for one of the persona's pictures, in the persona's voice, from what it shows."""
    body = await request.json()
    pid, _path, _video = await asyncio.to_thread(_media_file, str(body.get("persona") or ""), str(body.get("name") or ""))
    description, who = await asyncio.to_thread(_caption_inputs, pid, str(body.get("name") or ""))
    from app.web.routes.livedemo_routes import _ai_ready
    why = await asyncio.to_thread(_ai_ready)
    if why:
        raise HTTPException(status_code=409, detail=why)
    from app.utils import personas
    from app.utils.ai import generate_response
    from app.utils.helpers import load_instructions
    what = str(body.get("as") or "post")
    prompt = (f"Write the caption for an Instagram {what if what in _AS else 'post'} you are putting up of yourself. "
              + (f"The picture: {description}. " if description else "")
              + "One short line in your own voice, casual, at most two hashtags at the end. No quotes, no emoji spam.")
    with personas.scope(pid):
        instructions = await asyncio.to_thread(load_instructions)
        text = await generate_response(prompt, instructions + f"\n\n[You are {who}, posting on Instagram.]")
    text = " ".join(str(text or "").replace('"', "").split())[:300]
    if not text:
        raise HTTPException(status_code=409, detail="The AI did not write one")
    return {"caption": text}


@router.post("/api/instagram/post")
async def post_media(request: Request):
    """Put one of the persona's pictures up with an Instagram account, as a post, a reel or a story. `dry_run` fills
    it all in and leaves without posting."""
    body = await request.json()
    cfg = await asyncio.to_thread(_posting_cfg)
    if not cfg.get("enabled", True):
        raise HTTPException(status_code=409, detail="Posting is off in Settings, Instagram, Posting")
    meta = _account(body.get("target"))
    _pid, path, video = await asyncio.to_thread(_media_file, str(body.get("persona") or ""),
                                                str(body.get("name") or ""))
    what = str(body.get("as") or "post")
    if what not in _AS:
        raise HTTPException(status_code=400, detail="post, reel or story")
    if what == "reel" and not video:
        raise HTTPException(status_code=400, detail="A reel has to be a video")
    words = str(body.get("caption") or "").strip()[:2200]
    return await _ask(meta, "insta_post", {"file": str(path), "caption": words, "as": what,
                                           "dry_run": bool(body.get("dry_run"))}, 960.0)
