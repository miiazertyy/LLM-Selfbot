"""Community profiles in the panel (Profiles, Community): the catalog, looking inside one, adding and updating it,
sharing your own, following what you sent, signing in with GitHub, reports and moderation.

The work is app/utils/community.py; here it is put on worker threads (it reads files and talks to GitHub) and kept
safe from other websites: every change needs the panel's own header, and a request from another site's page is
refused, since some of these act as the person on GitHub.
"""
import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.utils import community, community_rules, github_signin, personas
from app.web import live

router = APIRouter(tags=["community"])

_TYPES = {".jpg": "image/jpeg", ".json": "application/json", ".txt": "text/plain; charset=utf-8"}


def _guard(request: Request) -> None:
    """Only the panel itself: its own header, and no other site's page."""
    if request.headers.get("x-llmselfbot") != "1":
        raise HTTPException(status_code=403, detail="Refused.")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host", ""):
        raise HTTPException(status_code=403, detail="Refused.")


def _fail(e: community.CommunityError):
    raise HTTPException(status_code=e.status, detail=str(e))


async def _run(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except community.CommunityError as e:
        _fail(e)


def _slug(slug: str) -> str:
    if not community_rules.SLUG.match(slug or ""):
        raise HTTPException(status_code=404, detail="No such profile.")
    return slug


def _pid(pid: str) -> str:
    if not personas.valid_id(pid) or not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There's no such profile.")
    return pid


# ── The catalog ──────────────────────────────────────────────────────────────

@router.get("/api/community")
def home(request: Request, force: bool = False):
    # Plain def: it reads files and may ask GitHub, on FastAPI's threadpool.
    return community.home(force)


@router.get("/api/community/stats")
def stats(request: Request, force: bool = False):
    return community.stats(force)


@router.get("/api/community/profiles/{slug}")
def inspect(request: Request, slug: str):
    try:
        return community.inspect(_slug(slug))
    except community.CommunityError as e:
        _fail(e)


@router.get("/api/community/files/{slug}/{name:path}")
def site_file(request: Request, slug: str, name: str, v: int = 1):
    """A live profile's face, thumbnail, text or settings, through the app: kept per version, so it is fetched once."""
    try:
        data = community.site_file(_slug(slug), name, v)
    except community.CommunityError as e:
        _fail(e)
    kind = next((t for ext, t in _TYPES.items() if name.endswith(ext)), "application/octet-stream")
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=31536000, immutable",
                                                     "X-Content-Type-Options": "nosniff"})


# ── Adding and updating ──────────────────────────────────────────────────────

@router.post("/api/community/install")
async def install(request: Request):
    _guard(request)
    body = await request.json()
    out = await _run(community.install, _slug(str(body.get("slug") or "")), bool(body.get("copy")))
    from app.web.routes.persona_routes import _summary, _who_uses, _known_accounts

    def summary():
        return _summary(out["pid"], _who_uses(_known_accounts()))
    return {"ok": True, "persona": await asyncio.to_thread(summary)}


@router.get("/api/community/installed/{pid}/update")
def update_preview(request: Request, pid: str):
    try:
        return community.update_preview(_pid(pid))
    except community.CommunityError as e:
        _fail(e)


@router.post("/api/community/installed/{pid}/update")
async def update(request: Request, pid: str):
    _guard(request)
    body = await request.json()
    out = await _run(community.update, _pid(pid), bool(body.get("confirm")))
    # Accounts speaking as it read their text and settings again (the Discord ones hold them).
    told = live.push(request, "instructions_update", {}, persona=pid, platforms=("discord",))
    live.push(request, "config_update", {"key": "bot"}, persona=pid, platforms=("discord",))
    return {"ok": True, "version": out["version"], "told": told}


# ── Sharing your own ─────────────────────────────────────────────────────────

@router.get("/api/community/share/{pid}")
def share_form(request: Request, pid: str):
    try:
        return community.share_form(_pid(pid))
    except community.CommunityError as e:
        _fail(e)


@router.post("/api/community/share/{pid}/preview")
async def share_preview(request: Request, pid: str):
    _guard(request)
    body = await request.json()
    return await _run(community.preview, _pid(pid), body if isinstance(body, dict) else {})


@router.post("/api/community/share/{pid}")
async def share_send(request: Request, pid: str):
    _guard(request)
    body = await request.json()
    out = await _run(community.send, _pid(pid), body if isinstance(body, dict) else {})
    return {"ok": True, **out}


@router.post("/api/community/remove")
async def remove(request: Request):
    _guard(request)
    body = await request.json()
    out = await _run(community.remove, _slug(str(body.get("slug") or "")))
    return {"ok": True, **out}


@router.get("/api/community/mine")
def mine(request: Request, force: bool = False):
    return community.mine(force)


@router.post("/api/community/report")
async def report(request: Request):
    _guard(request)
    body = await request.json()
    out = await _run(community.report, _slug(str(body.get("slug") or "")), str(body.get("reason") or ""),
                     str(body.get("details") or ""))
    return {"ok": True, **out}


# ── Moderators ───────────────────────────────────────────────────────────────

@router.get("/api/community/queue")
def queue(request: Request):
    try:
        return community.queue()
    except community.CommunityError as e:
        _fail(e)


@router.post("/api/community/moderate")
async def moderate(request: Request):
    _guard(request)
    body = await request.json()
    out = await _run(community.moderate, str(body.get("command") or ""), str(body.get("target") or ""),
                     str(body.get("reason") or ""), int(body.get("number") or 0))
    return out


# ── Signing in with GitHub ───────────────────────────────────────────────────

@router.get("/api/community/signin")
def signin_status(request: Request):
    return github_signin.status()


@router.post("/api/community/signin")
async def signin_start(request: Request):
    _guard(request)
    return await asyncio.to_thread(github_signin.start, community.client_id())


@router.delete("/api/community/signin")
async def signin_cancel(request: Request):
    _guard(request)
    return await asyncio.to_thread(github_signin.cancel)


@router.post("/api/community/signout")
async def signout(request: Request):
    _guard(request)
    return await asyncio.to_thread(github_signin.sign_out)


# ── Links ────────────────────────────────────────────────────────────────────

@router.post("/api/community/link")
async def link(request: Request):
    """A GitHub address made from known parts only. With open, the computer running the app opens it (the desktop
    window has no tab of its own); only for a request from this computer."""
    _guard(request)
    body = await request.json()
    url = community.link(str(body.get("what") or ""), str(body.get("slug") or ""), int(body.get("number") or 0))
    if not url:
        raise HTTPException(status_code=400, detail="Not a link the app makes.")
    opened = False
    host = request.client.host if request.client else ""
    if body.get("open") and host in ("127.0.0.1", "::1", "localhost"):
        from app.utils import device
        await asyncio.to_thread(device.open_url, url)
        opened = True
    return {"url": url, "opened": opened}
