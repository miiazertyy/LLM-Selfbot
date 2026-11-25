"""The AI tools over HTTP (app/utils/apptools.py): for the MCP program an AI app starts, and for the page's Ask box and its
list of changes. Everything here refuses a request that does not say it is the panel, so another website's page can't
make these calls."""
import asyncio
import json
import sys
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from app.utils import appchat, apptools
from app.utils.paths import APP_DIR

router = APIRouter(tags=["apptools"])

#: Questions kept for the page to read back; the oldest goes first.
_KEEP_JOBS = 8
_JOBS: dict = {}
_TASKS: set = set()
_MAX_QUESTION = 2000
#: A question still going after this long is stuck, and does not hold up the next one.
_STUCK = 600


def _panel_only(request: Request) -> None:
    if request.headers.get("x-llmselfbot") != "1":
        raise HTTPException(status_code=403, detail="Only the panel itself can do that.")


@router.post("/api/apptools/call")
async def call(request: Request):
    """One tool, for the MCP program. A refusal is an answer, for the AI to read."""
    _panel_only(request)
    body = await request.json()
    try:
        result = await apptools.call(str(body.get("tool") or ""), body.get("args"), request, who=body.get("who"))
    except apptools.ToolError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": result}


@router.get("/api/apptools/changes")
async def changes(request: Request):
    _panel_only(request)
    return {"changes": await asyncio.to_thread(apptools.recent)}


@router.post("/api/apptools/undo")
async def undo(request: Request):
    _panel_only(request)
    body = await request.json()
    try:
        return await apptools.call("undo_change", {"id": str(body.get("id") or "")}, request, who="You")
    except apptools.ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/apptools/connect")
def connect(request: Request):
    """What an AI app needs to start the MCP program on this computer. A phone can't run one for another app."""
    _panel_only(request)
    from app.utils import device
    if device.single_process():
        return {"available": False}
    args = ["--mcp"] if getattr(sys, "frozen", False) else [str(APP_DIR / "main.py"), "--mcp"]
    config = {"mcpServers": {"llmselfbot": {"command": sys.executable, "args": args}}}
    return {"available": True, "config": json.dumps(config, indent=2)}


@router.post("/api/apptools/ask")
async def ask(request: Request):
    """Start working on what someone typed in the Ask box. The page reads how it is going from the route below."""
    _panel_only(request)
    body = await request.json()
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Say what to change.")
    if len(text) > _MAX_QUESTION:
        raise HTTPException(status_code=400, detail="That is too long.")
    if any(not job["done"] and time.time() - job["started"] < _STUCK for job in _JOBS.values()):
        raise HTTPException(status_code=409, detail="Still working on the last one.")
    history = body.get("history") if isinstance(body.get("history"), list) else []
    persona = str(body.get("persona") or "").strip()
    job = {"id": uuid.uuid4().hex[:12], "started": time.time(), "done": False, "say": "", "error": "", "steps": []}
    _JOBS[job["id"]] = job
    while len(_JOBS) > _KEEP_JOBS:
        _JOBS.pop(next(iter(_JOBS)))

    async def work():
        try:
            job["say"] = await appchat.ask(text, history, request, persona, job["steps"].append)
        except appchat.NoModel as e:
            job["error"] = f"No model answered. {e}"[:400]
            job["where"] = "groq/providers"
        except Exception as e:
            job["error"] = f"That did not work: {type(e).__name__}"
        finally:
            job["done"] = True

    task = asyncio.create_task(work())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"id": job["id"]}


@router.get("/api/apptools/ask/{job_id}")
async def ask_status(request: Request, job_id: str):
    _panel_only(request)
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="That question is gone.")
    return job
