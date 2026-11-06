"""TikTok beyond the inbox, for the panel: what someone it talks to posts (the Chats tab's TikToks), liking, saving and
commenting on a video, what the account is doing out there (a LIVE it is visiting, For You, what is left of today's
likes and comments), and posting the persona's videos.

The TikTok runner does each in its out tab (app/platforms/snapchat/tiktok_runner.js), asked through the bridge
(app/platforms/snapchat_bridge.py, _OUT_OPS). Manual actions here work whatever the automatic switches say: they are
the user's own, counted in the day's likes and comments but never refused by them.
"""
import asyncio
import os
import re

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc

router = APIRouter(tags=["tiktok"])

_CHAT = re.compile(r"tt_[a-z0-9_-]{2,40}")
_VIDEO = re.compile(r"https://(?:www\.)?tiktok\.com/@[\w.]{1,24}/(?:video|photo)/\d{6,25}")
_HANDLE = re.compile(r"[a-z0-9._]{2,24}")
_PRIVACY = ("everyone", "friends", "only_me")


def _account(web_id: str) -> dict:
    """A TikTok account by its web id (tiktok_1): its IPC target and number, or 404."""
    meta = ipc.discover_targets().get(str(web_id or ""))
    if not meta or meta.get("platform") != "tiktok":
        raise HTTPException(status_code=404, detail="not a TikTok account")
    return meta


async def _ask(meta: dict, cmd: str, payload: dict, timeout: float) -> dict:
    result = await ipc.send_and_wait(meta["target"], cmd, payload, timeout=timeout)
    if result is None:
        raise HTTPException(status_code=504, detail="TikTok did not answer; is the account running?")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "TikTok would not do it")
    return result


def _video_url(value) -> str:
    url = str(value or "").strip().split("?")[0]
    if not _VIDEO.fullmatch(url):
        raise HTTPException(status_code=400, detail="That is not a TikTok video link")
    return url


def _theirs(meta: dict, user_id: str) -> dict:
    from app.utils import snappeople, tiktokwatch
    c = snappeople.contacts(meta["account"], "tiktok").get(user_id) or {}
    posts = []
    for p in (c.get("posts") or [])[:9]:
        if not isinstance(p, dict) or not re.fullmatch(r"\d{6,25}", str(p.get("id") or "")):
            continue
        w = tiktokwatch.cached(str(p["id"])) or {}
        cover = str(p.get("cover") or "")
        posts.append({
            "id": str(p["id"]), "url": str(p.get("url") or ""), "caption": str(p.get("caption") or "")[:300],
            "views": str(p.get("views") or "")[:12], "pinned": bool(p.get("pinned")),
            "cover": cover if cover.startswith("https://") else "", "photo": p.get("kind") == "photo",
            "seen": str(w.get("seen") or ""), "said": str(w.get("said") or ""),
            "likes": int(w.get("likes") or 0), "created": int(w.get("created") or 0),
        })
    return {"handle": snappeople.tiktok_handle(user_id), "name": str(c.get("name") or ""),
            "bio": str(c.get("bio") or "")[:400], "followers": c.get("followers"), "verified": bool(c.get("verified")),
            "posts": posts, "posts_at": float(c.get("posts_at") or 0), "newest": str(c.get("newest") or "")}


@router.get("/api/tiktok/theirs")
def their_posts(target: str, user_id: str):
    """What someone a TikTok account talks to posts, as the runner last read their profile, and what the persona saw
    in the ones it watched. Plain def: it reads the runner's files."""
    meta = _account(target)
    if not _CHAT.fullmatch(str(user_id or "")):
        raise HTTPException(status_code=400, detail="which chat?")
    return _theirs(meta, user_id)


@router.post("/api/tiktok/theirs/refresh")
async def their_posts_refresh(request: Request):
    """Their profile looked at again now, in the runner's out tab."""
    body = await request.json()
    meta = _account(body.get("target"))
    user_id = str(body.get("user_id") or "")
    if not _CHAT.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="which chat?")
    await _ask(meta, "tiktok_posts", {"user_id": user_id}, 80.0)
    return await asyncio.to_thread(_theirs, meta, user_id)


@router.post("/api/tiktok/action")
async def video_action(request: Request):
    """Like, save or comment on a video, as the account, from the panel."""
    body = await request.json()
    meta = _account(body.get("target"))
    url = _video_url(body.get("url"))
    action = str(body.get("action") or "")
    if action not in ("like", "save", "comment"):
        raise HTTPException(status_code=400, detail="like, save or comment")
    text = " ".join(str(body.get("text") or "").split())[:150]
    if action == "comment" and not text:
        raise HTTPException(status_code=400, detail="Write the comment first")
    return await _ask(meta, "tiktok_action", {"url": url, "action": action, "text": text}, 150.0)


@router.post("/api/tiktok/comment-text")
async def comment_text(request: Request):
    """A comment for a video, written by the persona after watching it, for the panel to show before it goes."""
    body = await request.json()
    meta = _account(body.get("target"))
    url = _video_url(body.get("url"))
    return await _ask(meta, "tiktok_comment_text", {"url": url, "why": "theirs"}, 150.0)


@router.get("/api/tiktok/out")
async def out_status(target: str):
    """What the account is doing out there now, and what is left of today's likes, comments, visits and posts."""
    meta = _account(target)
    return await _ask(meta, "tiktok_out", {}, 25.0)


@router.post("/api/tiktok/visit")
async def visit(request: Request):
    """Go to someone's LIVE now, as a viewer (it says hello, answers who talks to it, leaves after a while)."""
    body = await request.json()
    meta = _account(body.get("target"))
    handle = str(body.get("handle") or "").strip().lstrip("@").lower()
    if not _HANDLE.fullmatch(handle):
        raise HTTPException(status_code=400, detail="That is not a TikTok username")
    return await _ask(meta, "tiktok_visit", {"handle": handle}, 80.0)


@router.post("/api/tiktok/leave")
async def leave(request: Request):
    body = await request.json()
    return await _ask(_account(body.get("target")), "tiktok_leave", {}, 30.0)


@router.post("/api/tiktok/foryou")
async def foryou(request: Request):
    """A few minutes on For You, now."""
    body = await request.json()
    return await _ask(_account(body.get("target")), "tiktok_foryou", {}, 80.0)


# ── Posting the persona's videos ─────────────────────────────────────────────

def _video_file(persona: str, name: str):
    """One of a persona's videos on disk, by its name in the Pictures page; 404 when there is no such video."""
    from app.utils import personas, videos
    from app.utils.paths import DATA_DIR
    pid = str(persona or "").strip() or personas.DEFAULT
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    if os.path.basename(name) != name or not videos.is_kept_video(name):
        raise HTTPException(status_code=400, detail="Only a video can be posted")
    folder = DATA_DIR / "config" / "pictures" if pid == personas.DEFAULT else personas.pictures_dir(pid)
    path = folder / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That video is not there any more")
    return pid, path


def _posting_cfg() -> dict:
    from app.utils.helpers import load_config
    return ((load_config().get("tiktok") or {}).get("posting")) or {}


@router.get("/api/tiktok/posting")
def posting_info():
    """Whether videos can be posted from the panel, the TikTok accounts that can, and who can watch a new post at
    first (Settings, TikTok, Posting)."""
    cfg = _posting_cfg()
    accounts = sorted((k for k, v in ipc.discover_targets().items() if v.get("platform") == "tiktok"),
                      key=lambda k: int(k.split("_")[1]))
    privacy = str(cfg.get("privacy") or "everyone")
    return {"enabled": bool(cfg.get("enabled", True)), "accounts": accounts,
            "privacy": privacy if privacy in _PRIVACY else "everyone"}


def _caption_inputs(pid: str, name: str) -> tuple[str, str]:
    from app.utils import db, personas
    description = db.get_picture_description(name, persona=pid) or ""
    info = personas.get(pid) or {}
    return description, str(info.get("name") or pid)


@router.post("/api/tiktok/caption")
async def caption(request: Request):
    """A caption for one of the persona's videos, in the persona's voice, from what the video shows."""
    body = await request.json()
    pid, _path = await asyncio.to_thread(_video_file, str(body.get("persona") or ""), str(body.get("name") or ""))
    description, who = await asyncio.to_thread(_caption_inputs, pid, str(body.get("name") or ""))
    from app.web.routes.livedemo_routes import _ai_ready
    why = await asyncio.to_thread(_ai_ready)
    if why:
        raise HTTPException(status_code=409, detail=why)
    from app.utils import personas
    from app.utils.ai import generate_response
    from app.utils.helpers import load_instructions
    prompt = ("Write the caption for a TikTok you are posting of yourself. "
              + (f"The video: {description}. " if description else "")
              + "One short line in your own voice, casual, at most two hashtags at the end. No quotes, no emoji spam.")
    with personas.scope(pid):
        instructions = await asyncio.to_thread(load_instructions)
        text = await generate_response(prompt, instructions + f"\n\n[You are {who}, posting on TikTok.]")
    text = " ".join(str(text or "").replace('"', "").split())[:300]
    if not text:
        raise HTTPException(status_code=409, detail="The AI did not write one")
    return {"caption": text}


@router.post("/api/tiktok/post")
async def post_video(request: Request):
    """Post one of the persona's videos with a TikTok account: TikTok Studio's upload page, its caption, who can
    watch it. `dry_run` fills it all in and leaves without posting."""
    body = await request.json()
    cfg = await asyncio.to_thread(_posting_cfg)
    if not cfg.get("enabled", True):
        raise HTTPException(status_code=409, detail="Posting is off in Settings, TikTok, Posting")
    meta = _account(body.get("target"))
    _pid, path = await asyncio.to_thread(_video_file, str(body.get("persona") or ""), str(body.get("name") or ""))
    privacy = str(body.get("privacy") or "everyone")
    if privacy not in _PRIVACY:
        raise HTTPException(status_code=400, detail="everyone, friends or only_me")
    words = str(body.get("caption") or "").strip()[:2000]
    return await _ask(meta, "tiktok_post", {"file": str(path), "caption": words, "privacy": privacy,
                                            "dry_run": bool(body.get("dry_run"))}, 960.0)
