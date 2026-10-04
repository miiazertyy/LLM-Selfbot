import asyncio
import json
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.utils.paths import APP_DIR, seed_data_dir
from app.web.logbus import bus
from app.web.routes import (account_routes, appearance_routes, chat_routes,
                            config_routes, env_routes, health_routes,
                            local_routes, media_routes, models_routes, people_routes,
                            persona_routes, stats_routes, status_routes, system_routes,
                            prefs_routes, telegram_routes)


# ── Stall watchdog ── every page is served from one event loop, so one handler doing slow work on it freezes the whole panel, including fetching the code for the next tab, which is what "the app freezes when loading things" looked like. From the outside that is indistinguishable from the app hanging, so this notices it happening and says which requests were being answered at the time, in the log, so the next one names itself instead of needing to be hunted down.
STALL_WARN = 0.35            # seconds the loop was unable to run anything else
_IN_FLIGHT: dict = {}


class _InFlight:
    """Raw ASGI middleware: which paths are being answered right now."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        key = object()
        _IN_FLIGHT[key] = scope.get("path", "")
        try:
            await self.app(scope, receive, send)
        finally:
            _IN_FLIGHT.pop(key, None)


# What the event loop was doing when it stopped answering, seen from a thread of its own (below). The watchdog
# on the loop can only tell that it stalled, afterwards; this catches the line that did it.
_BEAT = {"t": 0.0}
_CAUGHT: dict = {"text": None}


def _app_frame(stack) -> str:
    """The innermost frame in the app's own code, as "chat_routes.py:223 in archive"."""
    for fr in reversed(stack):
        name = fr.filename.replace("\\", "/")
        if "/app/" in name or name.startswith("app/"):
            return f"{name.rsplit('/', 1)[-1]}:{fr.lineno} in {fr.name}"
    return ""


def _stall_sampler(loop_thread: int) -> None:
    import sys
    import threading
    import traceback
    while True:
        time.sleep(0.05)
        beat = _BEAT["t"]
        if not beat or _CAUGHT["text"] is not None or time.monotonic() - beat < STALL_WARN:
            continue
        frames = sys._current_frames()
        loop_frame = frames.get(loop_thread)
        stack = traceback.extract_stack(loop_frame) if loop_frame is not None else []
        where = _app_frame(stack)
        waiting = bool(stack) and stack[-1].name in ("select", "_poll", "poll", "_run_once", "sleep")
        if where and not waiting:
            _CAUGHT["text"] = f"It was busy in {where}."
            continue
        # The loop itself was idle, waiting its turn: another thread was holding Python.
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in frames.items():
            if ident in (loop_thread, threading.get_ident()):
                continue
            other = _app_frame(traceback.extract_stack(frame))
            if other:
                _CAUGHT["text"] = f"Another part of the app was holding it: {other} ({names.get(ident, 'a thread')})."
                break
        else:
            _CAUGHT["text"] = ""


async def _stall_watchdog():
    import threading
    tick = 0.1
    quiet_until = 0.0
    threading.Thread(target=_stall_sampler, args=(threading.get_ident(),), daemon=True, name="stall-sampler").start()
    while True:
        started = time.monotonic()
        _BEAT["t"] = started
        await asyncio.sleep(tick)
        stall = time.monotonic() - started - tick
        caught, _CAUGHT["text"] = _CAUGHT["text"], None
        # Over a minute is the computer having slept, not the panel stalling.
        if STALL_WARN <= stall < 60 and time.monotonic() >= quiet_until:
            quiet_until = time.monotonic() + 10        # one line per episode
            paths = sorted({p for p in _IN_FLIGHT.values() if not p.startswith("/assets/")})
            # Said so that it means something: the panel answers every page from one loop, so for this long
            # nothing on any page could load or respond.
            where = f" It was answering {', '.join(paths[:3])} at the time." if paths else ""
            bus.append("panel", f"⚠ The panel froze for {stall:.1f}s: no page could load or respond until it "
                                f"was done.{where} {caught or ''}".rstrip(), "warn")


def create_app(supervisor=None):
    seed_data_dir()
    # The stats/memory routes read the SQLite file directly, but only the bot runners ever called init_db(), so on a fresh install, before any account had started, /api/stats/leaderboard raised "no such table: user_stats" and the Stats page showed an Internal Server Error. The schema creation is CREATE TABLE IF NOT EXISTS throughout, so this is safe to repeat.
    try:
        from app.utils.db import init_db
        init_db()
    except Exception as e:      # a broken DB must not stop the panel booting
        print(f"[Supervisor] could not initialise the database: {e}", flush=True)
    # Persona folders, and the database given its persona column if it has none yet (repeatable; the supervisor
    # does it too, before any account starts).
    try:
        from app.utils import personas
        personas.startup()
    except Exception as e:
        print(f"[Supervisor] could not set up personas: {e}", flush=True)
    app = FastAPI(title="LLMSelfbot", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.supervisor = supervisor

    # Nothing was compressed before. The built panel is ~100KB of JS plus ~65KB of CSS, which gzip takes to roughly a third of that, and it is a real transfer, not just loopback, whenever services.webui.bind is opened up to the LAN. minimum_size keeps it off the many small JSON replies, where the header overhead would outweigh the saving.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(_InFlight)

    # account_routes FIRST: its literal /api/accounts/slots/... paths would otherwise be swallowed by status_routes' /api/accounts/{child_id}/{action}, which matches "slots" as a child id. FastAPI resolves in registration order.
    app.include_router(account_routes.router)
    app.include_router(status_routes.router)
    app.include_router(config_routes.router)
    app.include_router(env_routes.router)
    app.include_router(health_routes.router)
    app.include_router(people_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(media_routes.router)
    app.include_router(stats_routes.router)
    app.include_router(system_routes.router)
    app.include_router(prefs_routes.router)
    app.include_router(local_routes.router)
    app.include_router(models_routes.router)
    app.include_router(appearance_routes.router)
    app.include_router(telegram_routes.router)
    app.include_router(persona_routes.router)

    @app.websocket("/api/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        queue = bus.subscribe()
        try:
            for entry in bus.tail(50):
                await websocket.send_text(json.dumps(entry, ensure_ascii=False))
            while True:
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    await websocket.send_text(json.dumps({"ts": 0, "source": "_ping", "level": "ping", "text": "", "time": ""}))
                    continue
                await websocket.send_text(json.dumps(entry, ensure_ascii=False))
        except WebSocketDisconnect:
            pass
        finally:
            bus.unsubscribe(queue)

    # Ask each account who is waiting before anybody opens the Chats tab. That answer costs the runner a channel sweep, seconds, and it used to be the first visit that paid for it, on every single launch.
    @app.on_event("startup")
    async def _warm_caches():
        asyncio.create_task(chat_routes.warm_chats())
        asyncio.create_task(_stall_watchdog())
        asyncio.create_task(_warm_ai())

    _mount_spa(app)
    return app


async def _warm_ai():
    """The AI clients set up once, on a thread, as the panel starts: the first thing to need them (describing a
    picture, a summary) set them up on the event loop otherwise, loading the OpenAI library while every page waited."""
    await asyncio.sleep(3)
    try:
        from app.utils.ai import init_ai
        await asyncio.to_thread(init_ai)
    except BaseException:       # init_ai exits when no model is set up at all: nothing to warm then
        pass


def _mount_spa(app: FastAPI):
    # Registered after the real routers, so it only sees genuinely unknown API paths. Without it a POST to one falls through to the GET-only SPA handler and answers 405, which reads as "wrong method" rather than "no such route".
    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
                   include_in_schema=False)
    async def api_not_found(rest: str):
        return JSONResponse({"detail": "not found"}, status_code=404)

    dist = APP_DIR / "webui" / "dist"
    if not (dist / "index.html").exists():
        @app.get("/")
        async def missing_ui():
            return HTMLResponse(
                "<html><body style='font-family:sans-serif;background:#0b0b10;color:#eee;"
                "padding:2rem'><h1>Web UI not built</h1>"
                "<p>Run <code>cd webui && npm install && npm run build</code>.</p></body></html>"
            )
        return

    # The built asset filenames carry a content hash, so a given URL can never change and may be cached forever. index.html is the opposite: it is the thing that points at the current hashes, so it must never be served from cache or the app keeps loading the previous build's JavaScript. This mattered more than it looks: the desktop shell used to run the webview in private mode, which kept no cache at all, so a stale page was impossible; giving it real storage so preferences survive a restart also gave it a real HTTP cache, and without these headers a rebuilt panel could go on showing the old one indefinitely.
    IMMUTABLE = "public, max-age=31536000, immutable"
    NO_CACHE = "no-cache, no-store, must-revalidate"

    app.mount(
        "/assets",
        StaticFiles(directory=dist / "assets"),
        name="assets",
    )

    @app.middleware("http")
    async def cache_headers(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = IMMUTABLE
        elif not path.startswith("/api/"):
            response.headers["Cache-Control"] = NO_CACHE
            response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        # Unmatched API paths must 404, not fall through to index.html; a typo'd endpoint otherwise looks like a successful HTML response.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


DEFAULT_PORT = 8787


def run_server(supervisor=None, port: int | None = None, no_web: bool = False, bind: str | None = None):
    """Serve the webui. Explicit args win over config.yaml, which wins over the built-in defaults."""
    import uvicorn
    from app.utils.helpers import load_config

    if no_web:
        # No HTTP at all, keep the supervisor alive until Ctrl+C.
        import time
        print("[Supervisor] Web UI disabled, children are running.")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
        return

    cfg_port, cfg_bind = None, None
    try:
        webui_cfg = (load_config().get("services", {}) or {}).get("webui", {}) or {}
        cfg_port = int(webui_cfg["port"]) if webui_cfg.get("port") else None
        cfg_bind = str(webui_cfg["bind"]) if webui_cfg.get("bind") else None
    except Exception:
        pass

    port = port or cfg_port or DEFAULT_PORT
    bind = bind or cfg_bind or "127.0.0.1"

    if supervisor is None:
        from app.web.supervisor import Supervisor
        supervisor = Supervisor(port=port)
    supervisor.port = port

    url = f"http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{port}"
    bus.append("supervisor", f"Web UI on {url}")
    print(f"[Supervisor] webui: {url}", flush=True)
    if bind != "127.0.0.1":
        # The panel has no login, so reachability IS access: tokens, Groq keys and every control are open to anyone who can hit this port.
        warning = (f"Bound to {bind} with no password, anyone who can reach "
                   "this port has full control, including your tokens and keys. "
                   "Prefer 127.0.0.1 plus Tailscale or a Cloudflare Tunnel.")
        bus.append("supervisor", warning, level="warn")
        print(f"[Supervisor] WARNING: {warning}", flush=True)
    # Ollama / LM Studio, when something is set to run on it and it is installed
    # but not running. Here rather than in the app's startup hook: tests and the
    # sandbox build the app too, and must never launch a real program.
    def _autostart_local():
        try:
            from app.utils import localai
            localai.autostart(load_config())
        except Exception as e:
            bus.append("local", f"Could not start the local AI server: {e}", "warn")
        # Then, for as long as the app runs: a local model that will not load is looked into, and fixed where it
        # can be (app/utils/localfix.py).
        try:
            from app.utils import localfix
            localfix.watch(load_config)
        except Exception as e:
            bus.append("local", f"Stopped watching the local model: {e}", "warn")

    import threading
    threading.Thread(target=_autostart_local, daemon=True, name="local-autostart").start()
    uvicorn.run(create_app(supervisor), host=bind, port=port, log_level="warning")
