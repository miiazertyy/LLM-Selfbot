"""WhatsApp beyond the chats, for the panel: the groups it is in, the statuses it has seen, what is left of
today's statuses, and putting one up.

Each is asked of the runner through the bridge (app/platforms/snapchat_bridge.py, _wa_op_cmd), which passes it to
whatsapp_runner.js. There is no browser anywhere in this: the runner speaks WhatsApp's own protocol, so what
answers here is the connection itself rather than a page being read.

Manual actions here work whatever the automatic switches say, as Reddit's and X's do - they are the user's own,
counted in the day's allowance but never refused by it. Putting up a status is the one exception the runner keeps:
it refuses when statuses are switched off, because a status is public and nothing else here is.
"""
import os
import re

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc

router = APIRouter(tags=["whatsapp"])

_CHAT = re.compile(r"wa_\d{5,20}")
_GROUP = re.compile(r"wag_[A-Za-z0-9-]{5,40}")


def _account(web_id: str) -> dict:
    """A WhatsApp account by its web id (whatsapp_1): its IPC target and number, or 404."""
    meta = ipc.discover_targets().get(str(web_id or ""))
    if not meta or meta.get("platform") != "whatsapp":
        raise HTTPException(status_code=404, detail="not a WhatsApp account")
    return meta


async def _ask(meta: dict, cmd: str, payload: dict, timeout: float) -> dict:
    result = await ipc.send_and_wait(meta["target"], cmd, payload, timeout=timeout)
    if result is None:
        raise HTTPException(status_code=504, detail="WhatsApp did not answer; is the account running?")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "WhatsApp would not do it")
    return result


def _settings() -> dict:
    """The whatsapp.status block, with what the shipped config carries."""
    from app.utils.helpers import load_config
    try:
        wa = (load_config() or {}).get("whatsapp") or {}
    except Exception:
        wa = {}
    status = wa.get("status") or {}
    return {
        "post": bool(status.get("post", False)),
        "per_day": int(status.get("per_day", 1) or 1),
    }


@router.get("/api/whatsapp/state")
async def state(target: str):
    """What the connection is doing: linked, live, and which number it is."""
    return await _ask(_account(target), "wa_state", {}, 30.0)


@router.get("/api/whatsapp/groups")
async def groups(target: str):
    """The groups it is in, as WhatsApp lists them: the name, how many are in it, and whether it is an admin."""
    return await _ask(_account(target), "wa_groups", {}, 70.0)


@router.post("/api/whatsapp/group/leave")
async def leave(request: Request):
    """Leave a group. Switched off by default (whatsapp.groups.leave_on_request), and the runner refuses it
    then - leaving cannot be undone from here."""
    body = await request.json()
    meta = _account(body.get("target"))
    chat = str(body.get("chat") or "")
    if not _GROUP.fullmatch(chat):
        raise HTTPException(status_code=400, detail="not a group")
    return await _ask(meta, "wa_group", {"chat": chat, "leave": True}, 70.0)


@router.get("/api/whatsapp/statuses")
async def statuses(target: str):
    """The statuses it has seen from the people it talks to, newest last."""
    return await _ask(_account(target), "wa_status", {}, 40.0)


@router.get("/api/whatsapp/posting")
async def posting():
    """Which WhatsApp accounts there are to put a status up with, and what a status may be."""
    from app.utils import socials
    cfg = _settings()
    accounts = [w for w, m in ipc.discover_targets().items() if m.get("platform") == "whatsapp"]
    return {"ok": True, "enabled": socials.on().get("whatsapp", True), "accounts": sorted(accounts),
            "subreddits": [], "where": "", "posts": cfg["post"], "per_day": cfg["per_day"],
            # WhatsApp's own limit on the words on a status.
            "max_chars": 700}


@router.post("/api/whatsapp/status")
async def post_status(request: Request):
    """Put up a status: words, and one of the persona's pictures if it was asked for."""
    body = await request.json()
    meta = _account(body.get("target"))
    text = str(body.get("text") or "").strip()
    name = str(body.get("picture") or "").strip()
    if not text and not name:
        raise HTTPException(status_code=400, detail="a status needs words or a picture")
    picture = ""
    if name:
        from app.utils.paths import DATA_DIR
        safe = os.path.basename(name)
        path = DATA_DIR / "pictures" / safe
        if safe != name or not path.exists():
            raise HTTPException(status_code=404, detail="no such picture")
        picture = str(path)
    return await _ask(meta, "wa_post_status", {
        "text": text[:700], "picture": picture, "dry_run": bool(body.get("dry_run")),
    }, 920.0)
