"""Persona profiles in the panel: making them, giving them to accounts, and their text, face and settings.

What a persona is, and where it lives, is app/utils/personas.py. Everything here that touches a running account
says so to it (app/web/live.py), or restarts it when it is given another persona: an account keeps one persona for
as long as it runs.
"""
import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.utils import configstore, db, personas
from app.web import live

router = APIRouter(tags=["personas"])


def _need(pid: str) -> str:
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    return pid


def _known_accounts() -> list:
    """Every account set up, by web id, in their order: Discord's, then Snapchat's."""
    try:
        from app.core import ipc
        return list(ipc.discover_targets().keys())
    except Exception:
        return []


def _who_uses(accounts: list) -> dict:
    """{persona: [web ids]}: the accounts named nowhere are Default's."""
    out: dict = {}
    for acct in accounts:
        out.setdefault(personas.persona_of(acct), []).append(acct)
    return out


def _summary(pid: str, using: dict) -> dict:
    info = personas.get(pid) or {"id": pid, "name": pid, "color": "", "is_default": pid == personas.DEFAULT}
    text = personas.read_text(pid)
    return {
        **info,
        "avatar": f"/api/personas/{pid}/avatar?v={personas.avatar_version(pid)}" if personas.has_avatar(pid) else "",
        "line": personas.vibe(text),
        "words": personas.words(text),
        "pictures": personas.picture_count(pid),
        "people": db.persona_people(pid),
        "changed": len(personas.overrides(pid)),
        "accounts": using.get(pid, []),
    }


def _list() -> dict:
    accounts = _known_accounts()
    using = _who_uses(accounts)
    return {
        "personas": [_summary(pid, using) for pid in personas.ids()],
        "accounts": {acct: personas.persona_of(acct) for acct in accounts},
        "palette": personas.PALETTE,
    }


@router.get("/api/personas")
def list_personas(request: Request):
    # Plain def: it reads files and the database, on FastAPI's threadpool rather than the event loop.
    return _list()


@router.post("/api/personas")
async def create_persona(request: Request):
    body = await request.json()
    copy_from = body.get("copy_from") or None
    if copy_from is not None:
        _need(copy_from)
    try:
        made = await asyncio.to_thread(personas.create, str(body.get("name") or ""), str(body.get("color") or ""),
                                       copy_from, bool(body.get("copy_memory")))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    using = _who_uses(_known_accounts())
    return {"ok": True, "persona": _summary(made["id"], using)}


def _settings_diff(pid: str) -> list:
    """What this persona changes from everyone's settings, with a name for each and everyone's value beside it."""
    from app.utils.helpers import load_base_config
    from app.web import descriptions as desc
    base = load_base_config() or {}
    out = []
    for key, value in sorted(personas.overrides(pid).items()):
        out.append({"key": key, "label": desc.label_for(key), "value": value,
                    "base": configstore.get_nested(base, key)})
    return out


@router.get("/api/personas/{pid}")
def get_persona(request: Request, pid: str):
    _need(pid)
    using = _who_uses(_known_accounts())
    return {**_summary(pid, using), "settings": _settings_diff(pid)}


@router.patch("/api/personas/{pid}")
async def update_persona(request: Request, pid: str):
    _need(pid)
    body = await request.json()
    try:
        await asyncio.to_thread(personas.update, pid, name=body.get("name"), color=body.get("color"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    using = _who_uses(_known_accounts())
    return {"ok": True, "persona": _summary(pid, using)}


def _restart(request: Request, web_ids: list) -> list:
    """Start these accounts again, the ones that are running: a persona is the account's for as long as it runs."""
    sup = getattr(request.app.state, "supervisor", None)
    running = live.running_accounts(request)
    done = []
    for web_id in web_ids:
        if sup is None or web_id not in running:
            continue
        try:
            sup.restart(web_id)
            done.append(web_id)
        except Exception:
            pass
    return done


@router.delete("/api/personas/{pid}")
async def delete_persona(request: Request, pid: str):
    _need(pid)
    if pid == personas.DEFAULT:
        raise HTTPException(status_code=400, detail="Default can't be deleted.")
    accounts = _known_accounts()
    # Its accounts, as they stand now: the ones not named in the map were Default's already.
    moved = [a for a in accounts if personas.persona_of(a) == pid]
    try:
        await asyncio.to_thread(personas.delete, pid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    restarted = await asyncio.to_thread(_restart, request, moved)
    # Its pictures' originals no persona uses any more go too.
    try:
        from app.web.routes import media_routes
        await asyncio.to_thread(media_routes._sweep_originals)
    except Exception:
        pass
    return {"ok": True, "moved": moved, "restarted": restarted}


@router.post("/api/personas/{pid}/assign")
async def assign_persona(request: Request, pid: str):
    """Give an account this persona. A running account starts again with it."""
    _need(pid)
    body = await request.json()
    account = str(body.get("account") or "")
    if not re.fullmatch(r"(discord|snapchat)_[1-9][0-9]{0,2}", account):
        raise HTTPException(status_code=400, detail="That is not an account.")
    if personas.persona_of(account) == pid:
        return {"ok": True, "changed": False, "restarted": []}
    await asyncio.to_thread(personas.assign, account, pid)
    restarted = await asyncio.to_thread(_restart, request, [account])
    return {"ok": True, "changed": True, "restarted": restarted}


@router.get("/api/personas/{pid}/text")
def get_text(request: Request, pid: str):
    _need(pid)
    return {"text": personas.read_text(pid)}


@router.post("/api/personas/{pid}/text")
async def save_text(request: Request, pid: str):
    _need(pid)
    body = await request.json()
    text = body.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text required")
    await asyncio.to_thread(personas.save_text, pid, text)
    # Every account reads its text again on its next reply; the Discord runners also hold it, so they are told.
    told = live.push(request, "instructions_update", {}, persona=pid, platforms=("discord",))
    return {"ok": True, "told": told}


@router.get("/api/personas/{pid}/avatar")
def get_avatar(request: Request, pid: str):
    _need(pid)
    path = personas.avatar_path(pid)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no avatar")
    return FileResponse(str(path), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000"})


@router.post("/api/personas/{pid}/avatar")
async def set_avatar(request: Request, pid: str):
    """Its face for the app's own pages: one of its pictures (by name), or a file sent as the body. Never put on the
    account itself."""
    _need(pid)
    data = b""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        body = await request.json()
        name = str(body.get("picture") or "")
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise HTTPException(status_code=400, detail="picture required")
        path = personas.pictures_dir(pid) / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="That picture is not this persona's.")
        data = await asyncio.to_thread(path.read_bytes)
    else:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="file required")
        data = await upload.read()
    if not data or len(data) > 30 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="That is not a picture that can be used.")
    try:
        await asyncio.to_thread(personas.set_avatar, pid, data)
    except Exception:
        raise HTTPException(status_code=400, detail="That is not a picture that can be used.")
    return {"ok": True, "avatar": f"/api/personas/{pid}/avatar?v={personas.avatar_version(pid)}"}


@router.delete("/api/personas/{pid}/avatar")
async def clear_avatar(request: Request, pid: str):
    _need(pid)
    await asyncio.to_thread(personas.clear_avatar, pid)
    return {"ok": True}


@router.delete("/api/personas/{pid}/settings/{key:path}")
async def reset_setting(request: Request, pid: str, key: str):
    """This persona goes back to everyone's value for one setting."""
    _need(pid)
    gone = await asyncio.to_thread(configstore.reset, key, pid)
    if gone:
        live.push(request, "config_update", {"key": key}, persona=pid, platforms=("discord",))
    return {"ok": True, "reset": gone}
