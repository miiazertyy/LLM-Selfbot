"""The mailboxes the codes socials email at sign-in are read from (app/utils/mailcodes.py): added, checked and taken out
in Settings. A password goes into config/.env and never comes back out; a mailbox is only kept once it really opens."""
import asyncio
import re

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["mail"])

_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SERVER = re.compile(r"^[A-Za-z0-9.-]+(:\d{2,5})?$")


def _panel_only(request: Request) -> None:
    if request.headers.get("x-llmselfbot") != "1":
        raise HTTPException(status_code=403, detail="Only the panel itself can do that.")


def _shown(box: dict, found: dict) -> dict:
    return {"index": box["index"], "address": box["address"], "server": box["server"],
            "has_password": bool(box["password"]), "last": found.get(box["address"].lower())}


@router.get("/api/mail")
def mail_list(request: Request):
    _panel_only(request)
    from app.utils import mailcodes
    found = mailcodes.last_found()
    return {"mailboxes": [_shown(b, found) for b in mailcodes.mailboxes()]}


def _try(address: str, password: str, server: str) -> dict:
    """Find how to reach the mailbox (unless told), and open it once. Blocking: run on a thread."""
    from app.utils import mailcodes
    found = {"server": server, "note": "", "found": "you"} if server else mailcodes.discover(address)
    if not found["server"]:
        return {"ok": False, "reason": found["note"] or "There is no way in to that mailbox for a mail app.", **found}
    try:
        conn = mailcodes.connect(found["server"], address, password)
    except mailcodes.MailError as e:
        return {"ok": False, "reason": str(e), **found}
    try:
        conn.select("INBOX", readonly=True)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return {"ok": True, **found}


@router.post("/api/mail")
async def mail_add(request: Request):
    """Add a mailbox: the app finds its server, opens it once to be sure, and only then keeps it."""
    _panel_only(request)
    body = await request.json()
    address = str(body.get("address") or "").strip()
    password = str(body.get("password") or "")
    server = str(body.get("server") or "").strip()
    if not _ADDRESS.match(address):
        raise HTTPException(status_code=400, detail="That is not an email address.")
    if not password:
        raise HTTPException(status_code=400, detail="Put in its password.")
    if server and not _SERVER.match(server):
        raise HTTPException(status_code=400, detail="A server looks like imap.example.com or imap.example.com:993.")
    from app.utils import mailcodes
    from app.web.envfile import read_env, write_env
    if any(b["address"].lower() == address.lower() for b in mailcodes.mailboxes()):
        raise HTTPException(status_code=400, detail="That mailbox is here already.")
    tried = await asyncio.to_thread(_try, address, password, server)
    if not tried["ok"]:
        return tried
    env = read_env()
    taken = {b["index"] for b in mailcodes.mailboxes()}
    n = next(i for i in range(1, 100) if i not in taken)
    env.update({f"MAIL_{n}": address, f"MAIL_PASSWORD_{n}": password, f"MAIL_SERVER_{n}": tried["server"]})
    await asyncio.to_thread(write_env, env)
    return {"ok": True, "index": n, "server": tried["server"], "found": tried["found"], "note": tried["note"]}


@router.post("/api/mail/{index}/test")
async def mail_test(request: Request, index: int):
    """Open a mailbox again, to see that it still lets the app in."""
    _panel_only(request)
    from app.utils import mailcodes
    box = next((b for b in mailcodes.mailboxes() if b["index"] == index), None)
    if box is None:
        raise HTTPException(status_code=404, detail="There is no such mailbox.")
    return await asyncio.to_thread(_try, box["address"], box["password"], box["server"])


@router.delete("/api/mail/{index}")
async def mail_remove(request: Request, index: int):
    _panel_only(request)
    from app.web.envfile import read_env, write_env
    env = read_env()
    gone = [k for k in (f"MAIL_{index}", f"MAIL_PASSWORD_{index}", f"MAIL_SERVER_{index}") if k in env]
    if not gone:
        raise HTTPException(status_code=404, detail="There is no such mailbox.")
    for key in gone:
        env.pop(key)
    await asyncio.to_thread(write_env, env)
    return {"ok": True}
