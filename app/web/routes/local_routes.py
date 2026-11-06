"""Running the brain on this machine: finding a server, and fetching a model. The app does not run models itself, it talks to something that does; see app/utils/localai.py for why that is the right shape rather than a compromise. Every probe here touches the network, so all of it runs on a thread: the same mistake on /api/health once put a four second blocking call on the event loop every fifteen seconds and made the whole panel feel broken."""
import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.requests import ClientDisconnect

from app.utils import hfsearch, localai, localfix
from app.utils.helpers import load_config

router = APIRouter(tags=["local"])


@router.get("/api/local/detect")
async def detect(request: Request):
    """Which local servers are running, and what each one is offering."""
    servers = await asyncio.to_thread(localai.detect)
    for server in servers:
        server["pages"] = {m: localai.model_page(m, server["id"]) for m in server.get("models") or []}
    cfg = localai.settings(load_config())
    return {"servers": servers, "settings": cfg}


@router.get("/api/local/status")
async def status(request: Request):
    """Whether the configured server is actually there, and its model list."""
    cfg = localai.settings(load_config())
    # Independent of each other, and each waits out its own timeout when the server is not there, so they run together rather than back to back.
    # Ollama's own model list says it can download, and how big each model is, in one request; its /api/ps, which are loaded right now.
    result, info, loaded = await asyncio.gather(
        asyncio.to_thread(localai.probe, cfg["base_url"], 4.0, cfg["api_key"]),
        asyncio.to_thread(localai.ollama_models, cfg["base_url"]),
        asyncio.to_thread(localai.ollama_loaded, cfg["base_url"]),
    )
    sizes = None if info is None else {name: m["size"] for name, m in info.items()}
    # Ollama downloads models itself; for llama.cpp the app downloads the file (localai._start_file_pull).
    sid_guess = localai.server_for(cfg["base_url"])
    pull_kind = "ollama" if sizes is not None else (
        "file" if sid_guess == "llamacpp" and localai.installed("llamacpp") else "")
    can_pull = bool(pull_kind)
    if pull_kind == "file":
        # llama.cpp's own list says nothing of size: the files in the app's folder do.
        sizes = await asyncio.to_thread(localai.file_sizes)
    # A model set in config but missing from the server answers every request with a 404 that reads like the app is broken, so it is called out.
    missing = bool(cfg["model"]) and result["ok"] and cfg["model"] not in result["models"]
    # Who lives at that address, told apart by what answered where two share a port.
    sid = ""
    if result["ok"] or result["locked"]:
        sid = await asyncio.to_thread(localai.identify, cfg["base_url"], result, 1.0, cfg["api_key"])
    sid = sid or localai.server_for(cfg["base_url"])
    return {
        "settings": cfg,
        "reachable": result["ok"],
        # Answering, but wants a key the app does not have.
        "locked": result["locked"],
        # Who lives at that address, and whether the app can start it.
        "server": sid,
        "server_name": localai.server_name(sid),
        "can_start": localai.can_start(sid),
        "start_word": localai.start_word(sid),
        "starting": localai.starting(),
        # Being started again: for that long, its not answering is not news.
        "restarting": localai.restarting(),
        "error": result["error"],
        "models": result["models"],
        # Where each came from on the web, and how much disk it takes.
        "pages": {m: localai.model_page(m, sid) for m in result["models"]},
        "sizes": sizes or {},
        # Ollama's: how many parameters, how it is quantised, and which are in memory now.
        "details": info or {},
        "loaded": loaded,
        "can_pull": can_pull,
        "pull_kind": pull_kind,
        "model_missing": missing,
        "pull": localai.pull_status(),
        # A model that would not load, and what is being done about it (app/utils/localfix.py).
        "fix": localfix.status(),
    }


@router.post("/api/local/fix/use-alt")
async def fix_use_alt(request: Request):
    """Switch to the smaller model offered for one that does not fit this computer (app/utils/localfix.py)."""
    cfg = localai.settings(load_config())
    result = await asyncio.to_thread(localfix.use_alt, cfg["base_url"])
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "Could not switch")
    return result


@router.post("/api/local/probe")
async def probe(request: Request):
    """Try a base URL the person typed, before they commit to it."""
    body = await request.json()
    url = (body.get("base_url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="base_url required")
    # The key being typed beside it, when there is one, else the saved one.
    key = body.get("api_key")
    key = key.strip() if isinstance(key, str) else localai.settings(load_config())["api_key"]
    result = await asyncio.to_thread(localai.probe, url, 5.0, key)
    sid = ""
    if result["ok"] or result["locked"]:
        sid = await asyncio.to_thread(localai.identify, url, result, 1.0, key)
    sid = sid or localai.server_for(url)
    return {"base_url": localai.normalise_base_url(url), **result, "server": sid,
            "server_name": localai.server_name(sid),
            "pages": {m: localai.model_page(m, sid) for m in result["models"]}}


@router.post("/api/local/pull")
async def pull(request: Request):
    """Download a model through Ollama, by Ollama name or HuggingFace repo."""
    body = await request.json()
    name = (body.get("model") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="model required")
    cfg = localai.settings(load_config())
    base = (body.get("base_url") or cfg["base_url"]).strip()
    if not await asyncio.to_thread(localai.pull_kind, base):
        raise HTTPException(
            status_code=400,
            detail="That server cannot be given models from here: load one in its own app.")
    result = await asyncio.to_thread(localai.start_pull, name, base)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "Could not start"))
    return result


@router.get("/api/local/hf/search")
async def hf_search(request: Request, q: str = "", sort: str = "popular", kind: str = "", size: str = "",
                    cursor: str = ""):
    """Models on Hugging Face that can run here, by what was typed, or what is popular; of a kind and a size, and
    the batch after one already shown."""
    return await asyncio.to_thread(hfsearch.search, q, sort, kind, size, cursor)


@router.get("/api/local/hf/sizes")
async def hf_sizes(request: Request, repo: str = "", kind: str = "file"):
    """The sizes one comes in, and which of them this computer can run."""
    return await asyncio.to_thread(hfsearch.sizes, repo, kind)


@router.get("/api/local/hf/pictures")
async def hf_pictures(request: Request, authors: str = ""):
    """Which of these makers' pictures are in. The rest are fetched behind this, a few at once."""
    return await asyncio.to_thread(hfsearch.pictures, authors.split(",")[:80])


@router.get("/api/local/hf/picture")
async def hf_picture(request: Request, author: str = ""):
    """The picture of whoever made a model, once it is in."""
    path = await asyncio.to_thread(hfsearch.picture, author)
    if not path:
        raise HTTPException(status_code=404, detail="no picture")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=604800"})


@router.get("/api/local/pull/status")
async def pull_progress(request: Request):
    return localai.pull_status()


@router.post("/api/local/pull/cancel")
async def pull_cancel(request: Request):
    """Stop the model download under way. The next in the queue starts."""
    return localai.cancel_pull()


@router.post("/api/local/pull/unqueue")
async def pull_unqueue(request: Request):
    """Take a model out of the download queue before its turn."""
    body = await request.json()
    name = (body.get("model") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="model required")
    return localai.unqueue(name)


@router.post("/api/local/delete")
async def delete_model(request: Request):
    """Remove a model from Ollama. Only one the server itself lists, by its name there."""
    body = await request.json()
    name = (body.get("model") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="model required")
    cfg = localai.settings(load_config())
    base = (body.get("base_url") or cfg["base_url"]).strip()
    info = await asyncio.to_thread(localai.ollama_models, base)
    if info is None:
        # llama.cpp: a model the app downloaded is a file in its models folder.
        if await asyncio.to_thread(localai.pull_kind, base) != "file":
            raise HTTPException(status_code=400, detail="Only Ollama and llama.cpp can remove models from here.")
        result = await asyncio.to_thread(localai.delete_file_model, name, base)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("reason") or "That server does not have this model")
        return {**result, "unused": await asyncio.to_thread(localfix.drop, name)}
    if name not in info:
        raise HTTPException(status_code=404, detail="That server does not have this model")
    result = await asyncio.to_thread(localai.delete_model, name, base)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason") or "Could not remove it")
    # Gone from the server, gone from the settings: the jobs that used it go back to what they had besides it.
    return {**result, "unused": await asyncio.to_thread(localfix.drop, name)}


@router.post("/api/local/forget")
async def forget_models(request: Request):
    """Settings that name models this computer does not have (removed some other way, or before a removal cleaned up
    after itself) name them no more: each job goes back to what it had besides them (app/utils/localfix.py drop). Only
    a model the server really has not got: one it has is left alone."""
    body = await request.json()
    names = [str(m).strip() for m in (body.get("models") or []) if str(m).strip()]
    if not names:
        raise HTTPException(status_code=400, detail="models required")
    cfg = localai.settings(load_config())
    probe = await asyncio.to_thread(localai.probe, cfg["base_url"], 4.0, cfg["api_key"])
    if not probe["ok"]:
        raise HTTPException(status_code=409, detail="The local server is not answering, so it can't say what it has.")
    gone = [m for m in names if m not in probe["models"]]
    jobs: list = []
    for m in gone:
        jobs += await asyncio.to_thread(localfix.drop, m)
    return {"ok": True, "forgotten": gone, "unused": list(dict.fromkeys(jobs))}


@router.post("/api/local/start")
async def start(request: Request):
    """Start a server the app knows how to start (or open its app), and wait until it answers."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    cfg = localai.settings(load_config())
    result = await asyncio.to_thread(localai.start_server, (body or {}).get("server", ""),
                                     (body or {}).get("base_url") or cfg["base_url"])
    return result


@router.post("/api/local/restart")
async def restart(request: Request):
    """Every local server that is running, started again the app's way: a new context length takes effect, a folder is
    read afresh, and one that has wedged comes back."""
    cfg = localai.settings(load_config())
    return await asyncio.to_thread(localai.restart_all, cfg["base_url"])


@router.post("/api/local/open-folder")
async def open_folder(request: Request):
    """The folder this server keeps its models in, opened in the file manager, whether it has any yet or not."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    base = str((body or {}).get("base_url") or localai.settings(load_config())["base_url"]).strip()
    path = await asyncio.to_thread(localai.models_folder, base)
    try:
        await asyncio.to_thread(localai.show_in_folder, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open the folder: {exc}")
    return {"ok": True, "path": path}


@router.post("/api/local/import")
async def import_model(request: Request, name: str = ""):
    """A model file dropped on the Models tab: its bytes are this request's body, so nothing has to be read into memory
    however big it is, and leaving part way leaves nothing behind."""
    cfg = localai.settings(load_config())
    try:
        size = int(request.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    problem = await asyncio.to_thread(localai.import_problem, name, size, cfg["base_url"])
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    part = localai.app_models_dir() / f".adding-{uuid.uuid4().hex}.part"
    buf = bytearray()
    try:
        with open(part, "wb") as fh:
            async for chunk in request.stream():
                buf += chunk
                # A few megabytes at a time, off the event loop: a slow disk must not hold the whole panel up.
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
    result = await asyncio.to_thread(localai.finish_import, part, name, cfg["base_url"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason") or "Could not add it.")
    return result


@router.get("/api/local/start/status")
async def start_progress(request: Request):
    return localai.start_status()


@router.post("/api/local/reveal")
async def reveal(request: Request):
    """Show a model's file on this computer, in the file manager. Only a model the server itself lists: the name is looked up on the server and the file found from that, so this cannot be pointed at any other path."""
    body = await request.json()
    name = (body.get("model") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="model required")
    cfg = localai.settings(load_config())
    base = (body.get("base_url") or cfg["base_url"]).strip()
    # A file in the app's own folder needs nobody's word: the name cannot walk out of it. llama.cpp is restarted after
    # every download, and for those few seconds asking it first said it did not have what was just installed.
    path = await asyncio.to_thread(localai.file_model_path, name, "")
    if not path:
        listed = await asyncio.to_thread(localai.probe, base, 4.0, cfg["api_key"])
        if name not in listed["models"]:
            raise HTTPException(status_code=404, detail="That server does not have this model")
        path = await asyncio.to_thread(localai.model_file, name, base)
    if not path:
        raise HTTPException(status_code=404, detail="Could not find where this model is stored")
    try:
        await asyncio.to_thread(localai.show_in_folder, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open the folder: {exc}")
    return {"ok": True, "path": path}
