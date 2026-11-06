"""A persona from your own chats, in the panel. What it reads and what it never does is app/utils/chatpersona.py.

Every route here reads what someone has said, so only the panel itself may call them: the header it sends on every
request is required, and a page somewhere else can't send it.
"""
import asyncio
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.requests import ClientDisconnect

from app.utils import chatpersona

router = APIRouter(tags=["from-chats"])

# Left free on the disk after an export is copied in: Instagram's, with its pictures, can be gigabytes.
ROOM = 300 * 1024 * 1024
_TASKS: set = set()


def _panel_only(request: Request) -> None:
    if request.headers.get("x-llmselfbot") != "1":
        raise HTTPException(status_code=403, detail="Only the panel itself can do that.")


@router.get("/api/from-chats/status")
async def status(request: Request):
    _panel_only(request)
    return await asyncio.to_thread(chatpersona.status)


@router.post("/api/from-chats/upload")
async def upload(request: Request, name: str = ""):
    """An export dropped in: its bytes are the body, written to the job's folder as they come, read for the owner's
    messages, and then the file goes."""
    _panel_only(request)
    name = Path(str(name or "")).name[:200]
    if not re.search(r"\.(zip|json|csv|txt|js)$", name, re.I):
        raise HTTPException(status_code=400, detail="Drop the file the social gave you: a .zip, or the .json, .csv or "
                                                    ".txt from inside one.")
    try:
        size = int(request.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    job = chatpersona.job()
    try:
        free = shutil.disk_usage(job["dir"]).free
    except OSError:
        free = 0
    if size and free and size + ROOM > free:
        raise HTTPException(status_code=507, detail=f"Not enough room: it is {size / 1e9:.1f} GB, and there is "
                                                    f"{free / 1e9:.1f} GB free.")
    part = job["dir"] / f".upload-{uuid.uuid4().hex}.part"
    buf = bytearray()
    try:
        with open(part, "wb") as fh:
            async for chunk in request.stream():
                buf += chunk
                if len(buf) >= 8 * 1024 * 1024:
                    await asyncio.to_thread(fh.write, bytes(buf))
                    buf.clear()
            if buf:
                await asyncio.to_thread(fh.write, bytes(buf))
    except ClientDisconnect:
        part.unlink(missing_ok=True)
        raise HTTPException(status_code=499, detail="Stopped.")
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise HTTPException(status_code=507, detail=f"Could not write it: {exc}")
    added = await asyncio.to_thread(chatpersona.add_export, part, name)
    return {**await asyncio.to_thread(chatpersona.status), "added": added}


@router.post("/api/from-chats/remove")
async def remove(request: Request):
    _panel_only(request)
    body = await request.json()
    await asyncio.to_thread(chatpersona.remove_export, str(body.get("key") or ""))
    return await asyncio.to_thread(chatpersona.status)


@router.post("/api/from-chats/write")
async def write(request: Request):
    """Write the persona from the exports dropped in. It takes a minute: the status says how far it has got."""
    _panel_only(request)
    if chatpersona.job()["write"].get("state") == "writing":
        raise HTTPException(status_code=409, detail="It is writing it already.")
    chatpersona.job()["write"].update(state="writing", step="reading", why="")
    task = asyncio.create_task(chatpersona.write())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return await asyncio.to_thread(chatpersona.status)


@router.post("/api/from-chats/create")
async def create(request: Request):
    """The persona, made from what was written. A new one: nothing that exists changes."""
    _panel_only(request)
    body = await request.json()
    try:
        made = await asyncio.to_thread(chatpersona.create, str(body.get("name") or ""), str(body.get("color") or ""),
                                       str(body.get("color2") or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "persona": made}


@router.post("/api/from-chats/reset")
async def reset(request: Request):
    _panel_only(request)
    await asyncio.to_thread(chatpersona.reset)
    return await asyncio.to_thread(chatpersona.status)
