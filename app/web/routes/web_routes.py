"""
The persona on the web, for the Persona page: what it saw online in its free time (app/utils/web/journal.py),
browsing now when asked, and the session as it happens, step and picture (app/utils/web/freetime.py).
"""
import asyncio
import base64

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["web"])

# A Browse now running, held so it is not collected before it finishes.
_tasks: set = set()


def _pid(persona: str) -> str:
    from app.utils import personas
    pid = str(persona or "").strip() or personas.DEFAULT
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    return pid


@router.get("/api/web/journal")
def journal(request: Request, persona: str = ""):
    """What it saw online, newest first, with its free-time settings and whether it can browse with a real browser."""
    from app.utils import personas
    from app.utils.helpers import load_config
    from app.utils.web import browser, freetime, journal as journal_mod, settings
    pid = _pid(persona)
    with personas.scope(pid):
        s = settings(load_config())
    return {
        "persona": pid,
        "entries": journal_mod.entries(pid),
        "free_time": s["free_time"],
        "sessions_per_day": s["sessions_per_day"],
        "next_at": freetime.next_at(pid),
        "browser": browser.status(),
        "busy": freetime.now_state["busy"],
    }


@router.post("/api/web/browse-now")
async def browse_now(request: Request):
    """A free-time session for this persona, now, in the background: the page follows it with /api/web/now."""
    from app.utils.web import freetime
    body = await request.json()
    pid = _pid(body.get("persona"))
    if freetime.now_state["busy"]:
        return {"ok": False, "reason": "It is already browsing."}
    task = asyncio.create_task(freetime.browse(pid))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"ok": True}


@router.get("/api/web/now")
def now(request: Request):
    """The session as it happens: who, the step it is on, the page, and a picture of it."""
    from app.utils.web import freetime
    st = freetime.now_state
    shot = st.get("shot") or b""
    return {
        "busy": bool(st["busy"]),
        "persona": st["persona"],
        "name": st["name"],
        "step": st["step"],
        "steps": list(st["steps"]),
        "url": st["url"],
        "since": st["since"],
        "shot": ("data:image/jpeg;base64," + base64.b64encode(shot).decode()) if shot and st["busy"] else "",
        "shot_at": st["shot_at"],
        "last": st.get("last"),
    }


@router.delete("/api/web/journal/{persona}/{ts}")
def forget(request: Request, persona: str, ts: float):
    """One thing it saw, forgotten: it will not bring it up."""
    from app.utils.web import journal as journal_mod
    pid = _pid(persona)
    if not journal_mod.remove(pid, ts):
        raise HTTPException(status_code=404, detail="It does not remember that one.")
    return {"ok": True, "entries": journal_mod.entries(pid)}
