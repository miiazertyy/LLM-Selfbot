"""Reddit beyond the inbox, for the panel: what someone it talks to has posted, the replies and mentions waiting
in its inbox, upvoting and saving a post, commenting on one, the subreddits it may take part in and what each
said last time, what is left of today's allowances, and posting one of the persona's pictures.

The Reddit runner does each in its out tab (app/platforms/snapchat/reddit_runner.js), asked through the bridge
(app/platforms/snapchat_bridge.py, _OUT_OPS). Manual actions here work whatever the automatic switches say: they
are the user's own, counted in the day's allowances but never refused by them.

One thing is refused here and nowhere else: a subreddit the account was not told it may take part in. That list
is the whole of where it may speak (reddit.subreddits), and the panel is not a way around it.
"""
import os
import re

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc

router = APIRouter(tags=["reddit"])

_CHAT = re.compile(r"rd_[a-z0-9_-]{3,20}")
_POST = re.compile(r"https://(?:(?:www|old|new|np|m)\.)?reddit\.com/(?:r/[A-Za-z0-9_]{2,21}/)?comments/"
                   r"[a-z0-9]{2,12}[\w\-/]*|https://redd\.it/[a-z0-9]{2,12}")
_USERNAME = re.compile(r"[a-z0-9_-]{3,20}")
_SUB = re.compile(r"[A-Za-z0-9_]{2,21}")
_ACTIONS = ("upvote", "downvote", "save")


def _account(web_id: str) -> dict:
    """A Reddit account by its web id (reddit_1): its IPC target and number, or 404."""
    meta = ipc.discover_targets().get(str(web_id or ""))
    if not meta or meta.get("platform") != "reddit":
        raise HTTPException(status_code=404, detail="not a Reddit account")
    return meta


async def _ask(meta: dict, cmd: str, payload: dict, timeout: float) -> dict:
    result = await ipc.send_and_wait(meta["target"], cmd, payload, timeout=timeout)
    if result is None:
        raise HTTPException(status_code=504, detail="Reddit did not answer; is the account running?")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "Reddit would not do it")
    return result


def _theirs(meta: dict, user_id: str) -> dict:
    """What is already known of their posts, out of the runner's own people cache: no browser involved."""
    from app.utils import redditwatch, snappeople
    contact = snappeople.contacts(int(meta["account"]), "reddit").get(str(user_id)) or {}
    newest = str(contact.get("newest") or "")
    return {
        "username": snappeople.handle_of(user_id),
        "karma": contact.get("karma") or 0,
        "looked_at": contact.get("posts_at") or 0,
        "newest": newest,
        "post": redditwatch.cached(newest) if newest else None,
    }


@router.get("/api/reddit/theirs")
def their_posts(target: str, user_id: str):
    """Their newest post as it was last read. Plain def: it reads the runner's files."""
    meta = _account(target)
    if not _CHAT.fullmatch(str(user_id or "")):
        raise HTTPException(status_code=400, detail="which chat?")
    return _theirs(meta, user_id)


@router.post("/api/reddit/theirs/refresh")
async def their_posts_refresh(request: Request):
    """Their profile looked at again now, in the runner's out tab."""
    import asyncio
    body = await request.json()
    meta = _account(body.get("target"))
    user_id = str(body.get("user_id") or "")
    if not _CHAT.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="which chat?")
    await _ask(meta, "reddit_posts", {"user_id": user_id}, 80.0)
    return await asyncio.to_thread(_theirs, meta, user_id)


@router.get("/api/reddit/inbox")
async def inbox(target: str):
    """The replies and u/ mentions it has not answered."""
    return await _ask(_account(target), "reddit_inbox", {}, 80.0)


@router.get("/api/reddit/thread")
async def thread(target: str, url: str):
    """A post and what is said under it."""
    if not _POST.match(str(url or "")):
        raise HTTPException(status_code=400, detail="not a Reddit post")
    return await _ask(_account(target), "reddit_thread", {"url": url}, 80.0)


@router.get("/api/reddit/subs")
async def subs(target: str):
    """The subreddits it may take part in, and what each one said last time it tried."""
    return await _ask(_account(target), "reddit_subs", {}, 70.0)


@router.get("/api/reddit/out")
async def out_status(target: str):
    """What is left of today's upvotes, joins, follows, answers, comments and posts, and whether Reddit is hiding
    the account."""
    return await _ask(_account(target), "reddit_out", {}, 25.0)


@router.post("/api/reddit/action")
async def action(request: Request):
    """Upvote, downvote or save one post."""
    body = await request.json()
    meta = _account(body.get("target"))
    url, what = str(body.get("url") or ""), str(body.get("action") or "")
    if not _POST.match(url):
        raise HTTPException(status_code=400, detail="not a Reddit post")
    if what not in _ACTIONS:
        raise HTTPException(status_code=400, detail=f"{what or 'that'} is not something it does to a post")
    return await _ask(meta, "reddit_action", {"url": url, "action": what}, 130.0)


@router.post("/api/reddit/comment")
async def comment(request: Request):
    """A comment under one post, written here rather than by the loop."""
    body = await request.json()
    meta = _account(body.get("target"))
    url, text = str(body.get("url") or ""), str(body.get("text") or "").strip()
    if not _POST.match(url):
        raise HTTPException(status_code=400, detail="not a Reddit post")
    if not text:
        raise HTTPException(status_code=400, detail="nothing to say")
    return await _ask(meta, "reddit_comment", {"url": url, "text": text[:9000],
                                               "dry_run": bool(body.get("dry_run"))}, 190.0)


@router.post("/api/reddit/follow")
async def follow(request: Request):
    """Follow somebody."""
    body = await request.json()
    meta = _account(body.get("target"))
    who = str(body.get("username") or "").strip().lstrip("@").removeprefix("u/").lower()
    if not _USERNAME.fullmatch(who):
        raise HTTPException(status_code=400, detail="not a Reddit username")
    return await _ask(meta, "reddit_follow", {"username": who}, 70.0)


@router.get("/api/reddit/posting")
async def posting():
    """Which Reddit accounts there are to post with, and where a post may go: its own profile always, and
    whichever subreddits it was told it may take part in."""
    from app.utils import redditsocial, socials
    cfg = redditsocial.settings()
    accounts = [w for w, m in ipc.discover_targets().items() if m.get("platform") == "reddit"]
    return {"ok": True, "enabled": socials.on().get("reddit", True), "accounts": sorted(accounts),
            "subreddits": cfg["subreddits"], "where": cfg["where"], "max_chars": cfg["max_chars"]}


@router.post("/api/reddit/post")
async def post(request: Request):
    """Put up a post: a title, words, and one of the persona's pictures if it was asked for. `where` is a
    subreddit's name or "" for its own profile, which always takes one."""
    from app.utils import redditsocial
    body = await request.json()
    meta = _account(body.get("target"))
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="a post needs a title")
    where = str(body.get("where") or "").strip().removeprefix("r/")
    if where and not _SUB.fullmatch(where):
        raise HTTPException(status_code=400, detail="not a subreddit")
    # The one list that says where it may speak at all. The panel is not a way around it.
    if where and not redditsocial.allowed(where):
        raise HTTPException(status_code=403,
                            detail=f"r/{where} is not on its list. Add it in Settings, Reddit, Comments.")
    images = []
    name = str(body.get("picture") or "").strip()
    if name:
        from app.utils.paths import DATA_DIR
        safe = os.path.basename(name)
        path = DATA_DIR / "pictures" / safe
        if safe != name or not path.exists():
            raise HTTPException(status_code=404, detail="no such picture")
        images = [str(path)]
    return await _ask(meta, "reddit_post", {
        "title": title[:300], "text": str(body.get("text") or "")[:20000],
        "link": str(body.get("link") or ""), "images": images, "where": where,
        "flair": str(body.get("flair") or ""), "dry_run": bool(body.get("dry_run")),
    }, 920.0)
