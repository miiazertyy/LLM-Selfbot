"""Running the brain on this machine: finding a server, and fetching a model.

The app does not run models itself, it talks to something that does. See
app/utils/localai.py for why that is the right shape rather than a compromise.

Every probe here touches the network, so all of it runs on a thread. The same
mistake on /api/health once put a four second blocking call on the event loop
every fifteen seconds and made the whole panel feel broken.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.utils import localai
from app.utils.helpers import load_config

router = APIRouter(tags=["local"])


@router.get("/api/local/detect")
async def detect(request: Request):
    """Which local servers are running, and what each one is offering."""
    servers = await asyncio.to_thread(localai.detect)
    cfg = localai.settings(load_config())
    return {"servers": servers, "settings": cfg}


@router.get("/api/local/status")
async def status(request: Request):
    """Whether the configured server is actually there, and its model list."""
    cfg = localai.settings(load_config())
    result = await asyncio.to_thread(localai.probe, cfg["base_url"], 4.0)
    can_pull = await asyncio.to_thread(localai.pull_supported, cfg["base_url"])
    # A model set in config but missing from the server answers every request
    # with a 404 that reads like the app is broken, so it is called out.
    missing = bool(cfg["model"]) and result["ok"] and cfg["model"] not in result["models"]
    return {
        "settings": cfg,
        "reachable": result["ok"],
        "error": result["error"],
        "models": result["models"],
        "can_pull": can_pull,
        "model_missing": missing,
        "pull": localai.pull_status(),
    }


@router.post("/api/local/probe")
async def probe(request: Request):
    """Try a base URL the person typed, before they commit to it."""
    body = await request.json()
    url = (body.get("base_url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="base_url required")
    result = await asyncio.to_thread(localai.probe, url, 5.0)
    return {"base_url": localai.normalise_base_url(url), **result}


@router.post("/api/local/pull")
async def pull(request: Request):
    """Download a model through Ollama, by Ollama name or HuggingFace repo."""
    body = await request.json()
    name = (body.get("model") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="model required")
    cfg = localai.settings(load_config())
    base = (body.get("base_url") or cfg["base_url"]).strip()
    if not await asyncio.to_thread(localai.pull_supported, base):
        raise HTTPException(
            status_code=400,
            detail="That server cannot fetch models for you. Ollama can; for "
                   "the others you point them at a file yourself.")
    result = await asyncio.to_thread(localai.start_pull, name, base)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "Could not start"))
    return result


@router.get("/api/local/pull/status")
async def pull_progress(request: Request):
    return localai.pull_status()
