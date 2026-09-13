import asyncio
import time

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc
from app.web.logbus import bus

router = APIRouter(tags=["status"])

START_TIME = time.time()


@router.get("/api/status")
async def status(request: Request):
    supervisor = request.app.state.supervisor
    return {
        "uptime": round(time.time() - START_TIME),
        "children": supervisor.status(),
        "port": supervisor.port,
    }


def _identity(platform: str, account) -> dict:
    """Who an account actually is, recorded by the runner when it connects.

    Read from a file rather than asked over IPC, so the panel can still show
    the username and avatar for an account that is currently stopped.
    """
    if platform != "discord" or not account:
        return {}
    try:
        import json
        from app.utils.paths import DATA_DIR
        path = DATA_DIR / "config" / f"identity_{account}.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "username": data.get("username", ""),
            "display_name": data.get("display_name", ""),
            "avatar": data.get("avatar", ""),
        }
    except Exception:
        return {}


@router.get("/api/accounts")
async def accounts(request: Request):
    supervisor = request.app.state.supervisor
    targets = ipc.discover_targets()
    children = {c["id"]: c for c in supervisor.status()}
    out = []
    for web_id, meta in targets.items():
        child = children.get(web_id, {})
        out.append({
            **_identity(meta["platform"], meta["account"]),
            "id": web_id,
            "platform": meta["platform"],
            "account": meta["account"],
            "target": meta["target"],
            "state": child.get("state", "stopped"),
            "pid": child.get("pid"),
            "restarts": child.get("restarts", 0),
            "uptime": child.get("uptime", 0),
        })
    tg_child = children.get("telegram")
    if tg_child:
        out.append({
            "id": "telegram",
            "platform": "telegram",
            "account": None,
            "target": "telegram",
            "state": tg_child.get("state", "stopped"),
            "pid": tg_child.get("pid"),
            "restarts": tg_child.get("restarts", 0),
            "uptime": tg_child.get("uptime", 0),
        })
    return {"accounts": out}


@router.post("/api/accounts/{child_id}/{action}")
async def account_action(request: Request, child_id: str, action: str):
    supervisor = request.app.state.supervisor
    if action == "start":
        return supervisor.start(child_id)
    if action == "stop":
        # stop() waits for the worker to log out of Discord, so it must not run
        # on the event loop: the whole panel would freeze while it waits.
        import asyncio
        return await asyncio.to_thread(supervisor.stop, child_id)
    if action == "restart":
        import asyncio
        return await asyncio.to_thread(supervisor.restart, child_id)
    # Everything below talks to the running account over IPC.
    _IPC_ACTIONS = {
        "pause": "pause",       # toggles
        "wipe": "wipe",         # clears conversation history
        "reload": "reload",     # reloads the command modules
    }
    if action in _IPC_ACTIONS:
        meta = ipc.discover_targets().get(child_id)
        if not meta:
            raise HTTPException(status_code=404, detail="unknown account")
        result = await ipc.send_and_wait(meta["target"], _IPC_ACTIONS[action], timeout=15.0)
        return result or {"ok": False, "reason": "no response (runner not running?)"}
    raise HTTPException(status_code=400, detail=f"unknown action {action}")


@router.get("/api/accounts/{child_id}/details")
async def account_details(request: Request, child_id: str):
    """Live detail for one account: mood, paused, how much it is watching.

    Fetched on demand when a row is expanded rather than folded into
    /api/accounts, which the pages poll every few seconds. One IPC round trip
    per account per poll would be a lot of file traffic for information nobody
    is looking at most of the time.
    """
    meta = ipc.discover_targets().get(child_id)
    if not meta:
        raise HTTPException(status_code=404, detail="unknown account")
    result = await ipc.send_and_wait(meta["target"], "get_status", timeout=8.0)
    if result is None:
        return {"live": False, "reason": "the account is not running"}
    return {"live": True, **result}


@router.post("/api/accounts/{child_id}/mood")
async def account_mood(request: Request, child_id: str):
    body = await request.json()
    mood = str(body.get("mood", "")).strip()
    if not mood:
        raise HTTPException(status_code=400, detail="mood required")
    meta = ipc.discover_targets().get(child_id)
    if not meta:
        raise HTTPException(status_code=404, detail="unknown account")
    result = await ipc.send_and_wait(meta["target"], "mood_set", {"mood": mood}, timeout=8.0)
    return result or {"ok": False, "reason": "no response (runner not running?)"}


@router.post("/api/services/{name}/{action}")
async def service_action(request: Request, name: str, action: str):
    supervisor = request.app.state.supervisor
    if name == "kill_switch":
        result = await asyncio.gather(*[
            ipc.send_and_wait(meta["target"], "pause", {}, timeout=5.0)
            for meta in ipc.discover_targets().values()
        ], return_exceptions=True)
        return {"ok": True, "results": [r for r in result if isinstance(r, dict)]}
    if name == "webui" and action == "stop":
        return {"ok": False, "reason": "cannot stop the server you are connected to"}
    if action == "start":
        return supervisor.start(name)
    if action == "stop":
        return supervisor.stop(name)
    if action == "restart":
        return supervisor.restart(name)
    raise HTTPException(status_code=400, detail=f"unknown action {action}")


@router.post("/api/command")
async def raw_command(request: Request):
    body = await request.json()
    target = body.get("target")
    cmd = body.get("cmd")
    payload = body.get("payload", {})
    if not target or not cmd:
        raise HTTPException(status_code=400, detail="target and cmd required")
    if isinstance(target, str) and target.startswith(("discord_", "snapchat_")):
        meta = ipc.discover_targets().get(target)
        target = meta["target"] if meta else target
    timeout = float(body.get("timeout", 15.0))
    result = await ipc.send_and_wait(target, cmd, payload, timeout=timeout)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    return result


@router.get("/api/logs")
async def logs(request: Request, n: int = 200, source: str = ""):
    lines = bus.tail(n)
    if source:
        lines = [l for l in lines if l["source"] == source]
    return {"lines": lines}
