"""X beyond the inbox, for the panel: what someone it talks to has posted, the @s and replies it has not
answered, liking and reposting a post, following someone, what is left of today's allowances, and posting one of
the persona's pictures.

X has had all of this in its runner since it was added (app/platforms/snapchat_bridge.py, _OUT_OPS) and no way
for the panel to reach any of it: there was no file like this one. Written alongside Reddit's, which is the same
shape, so the two can be read against each other.
"""
import os
import re

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc

router = APIRouter(tags=["x"])

_CHAT = re.compile(r"x_[a-z0-9_]{1,15}")
_POST = re.compile(r"https://(?:(?:www|mobile)\.)?(?:x|twitter)\.com/[A-Za-z0-9_]{1,15}/status/\d{1,25}")
_HANDLE = re.compile(r"[a-z0-9_]{1,15}")
_ACTIONS = ("like", "repost", "quote")


def _account(web_id: str) -> dict:
    """An X account by its web id (x_1): its IPC target and number, or 404."""
    meta = ipc.discover_targets().get(str(web_id or ""))
    if not meta or meta.get("platform") != "x":
        raise HTTPException(status_code=404, detail="not an X account")
    return meta


async def _ask(meta: dict, cmd: str, payload: dict, timeout: float) -> dict:
    result = await ipc.send_and_wait(meta["target"], cmd, payload, timeout=timeout)
    if result is None:
        raise HTTPException(status_code=504, detail="X did not answer; is the account running?")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "X would not do it")
    return result


def _theirs(meta: dict, user_id: str) -> dict:
    """What is already known of their posts, out of the runner's own people cache: no browser involved."""
    from app.utils import snappeople, xwatch
    contact = snappeople.contacts(int(meta["account"]), "x").get(str(user_id)) or {}
    newest = str(contact.get("newest") or "")
    return {
        "handle": snappeople.handle_of(user_id),
        "followers": contact.get("followers") or 0,
        "looked_at": contact.get("posts_at") or 0,
        "newest": newest,
        "post": xwatch.cached(newest) if newest else None,
    }


@router.get("/api/x/theirs")
def their_posts(target: str, user_id: str):
    """Their newest post as it was last read. Plain def: it reads the runner's files."""
    meta = _account(target)
    if not _CHAT.fullmatch(str(user_id or "")):
        raise HTTPException(status_code=400, detail="which chat?")
    return _theirs(meta, user_id)


@router.post("/api/x/theirs/refresh")
async def their_posts_refresh(request: Request):
    """Their profile looked at again now, in the runner's out tab."""
    import asyncio
    body = await request.json()
    meta = _account(body.get("target"))
    user_id = str(body.get("user_id") or "")
    if not _CHAT.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="which chat?")
    await _ask(meta, "x_posts", {"user_id": user_id}, 80.0)
    return await asyncio.to_thread(_theirs, meta, user_id)


@router.get("/api/x/mentions")
async def mentions(target: str, since: str = ""):
    """The @s and replies it has not answered."""
    return await _ask(_account(target), "x_mentions", {"since": since}, 80.0)


@router.get("/api/x/thread")
async def thread(target: str, url: str):
    """A post and the replies under it."""
    if not _POST.match(str(url or "")):
        raise HTTPException(status_code=400, detail="not an X post")
    return await _ask(_account(target), "x_thread", {"url": url}, 80.0)


@router.get("/api/x/out")
async def out_status(target: str):
    """What is left of today's likes, reposts, follows, public answers and posts."""
    return await _ask(_account(target), "x_out", {}, 25.0)


@router.post("/api/x/action")
async def action(request: Request):
    """Like, repost or quote one post."""
    body = await request.json()
    meta = _account(body.get("target"))
    url, what = str(body.get("url") or ""), str(body.get("action") or "")
    if not _POST.match(url):
        raise HTTPException(status_code=400, detail="not an X post")
    if what not in _ACTIONS:
        raise HTTPException(status_code=400, detail=f"{what or 'that'} is not something it does to a post")
    return await _ask(meta, "x_action", {"url": url, "action": what,
                                         "text": str(body.get("text") or "")[:150]}, 130.0)


@router.post("/api/x/follow")
async def follow(request: Request):
    """Follow somebody."""
    body = await request.json()
    meta = _account(body.get("target"))
    who = str(body.get("username") or "").strip().lstrip("@").lower()
    if not _HANDLE.fullmatch(who):
        raise HTTPException(status_code=400, detail="not an X handle")
    return await _ask(meta, "x_follow", {"username": who}, 70.0)


@router.get("/api/x/posting")
async def posting():
    """Which X accounts there are to post with, and how long a post may be."""
    from app.utils import socials, xsocial
    cfg = xsocial.settings()
    accounts = [w for w, m in ipc.discover_targets().items() if m.get("platform") == "x"]
    return {"ok": True, "enabled": socials.on().get("x", True), "accounts": sorted(accounts),
            "subreddits": [], "where": "", "max_chars": cfg["max_chars"]}


@router.post("/api/x/post")
async def post(request: Request):
    """Put up a post: words, and one of the persona's pictures if it was asked for."""
    body = await request.json()
    meta = _account(body.get("target"))
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="a post needs words")
    images = []
    name = str(body.get("picture") or "").strip()
    if name:
        from app.utils.paths import DATA_DIR
        safe = os.path.basename(name)
        path = DATA_DIR / "pictures" / safe
        if safe != name or not path.exists():
            raise HTTPException(status_code=404, detail="no such picture")
        images = [str(path)]
    return await _ask(meta, "x_post", {"text": text[:2000], "images": images, "thread": [],
                                       "dry_run": bool(body.get("dry_run"))}, 920.0)
