import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.utils.paths import APP_DIR, seed_data_dir
from app.web.logbus import bus
from app.web.routes import (account_routes, appearance_routes, chat_routes,
                            config_routes, env_routes, health_routes,
                            local_routes, media_routes, people_routes,
                            stats_routes, status_routes, system_routes,
                            prefs_routes)


def create_app(supervisor=None):
    seed_data_dir()
    # The stats/memory routes read the SQLite file directly, but only the bot
    # runners ever called init_db(), so on a fresh install, before any account
    # had started, /api/stats/leaderboard raised "no such table: user_stats"
    # and the Stats page showed an Internal Server Error. The schema creation
    # is CREATE TABLE IF NOT EXISTS throughout, so this is safe to repeat.
    try:
        from app.utils.db import init_db
        init_db()
    except Exception as e:      # a broken DB must not stop the panel booting
        print(f"[Supervisor] could not initialise the database: {e}", flush=True)
    app = FastAPI(title="LLMSelfbot", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.supervisor = supervisor

    # Nothing was compressed before. The built panel is ~100KB of JS plus
    # ~65KB of CSS, which gzip takes to roughly a third of that - and it is a
    # real transfer, not just loopback, whenever services.webui.bind is opened
    # up to the LAN. minimum_size keeps it off the many small JSON replies,
    # where the header overhead would outweigh the saving.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # account_routes FIRST: its literal /api/accounts/slots/... paths would
    # otherwise be swallowed by status_routes' /api/accounts/{child_id}/{action},
    # which matches "slots" as a child id. FastAPI resolves in registration order.
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
    app.include_router(appearance_routes.router)

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

    _mount_spa(app)
    return app


def _mount_spa(app: FastAPI):
    # Registered after the real routers, so it only sees genuinely unknown API
    # paths. Without it a POST to one falls through to the GET-only SPA handler
    # and answers 405, which reads as "wrong method" rather than "no such route".
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

    # The built asset filenames carry a content hash, so a given URL can never
    # change and may be cached forever. index.html is the opposite: it is the
    # thing that points at the current hashes, so it must never be served from
    # cache or the app keeps loading the previous build's JavaScript.
    #
    # This mattered more than it looks. The desktop shell used to run the
    # webview in private mode, which kept no cache at all, so a stale page was
    # impossible. Giving it real storage so preferences survive a restart also
    # gave it a real HTTP cache, and without these headers a rebuilt panel
    # could go on showing the old one indefinitely.
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
        # Unmatched API paths must 404, not fall through to index.html - a
        # typo'd endpoint otherwise looks like a successful HTML response.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


DEFAULT_PORT = 8787


def run_server(supervisor=None, port: int | None = None, no_web: bool = False, bind: str | None = None):
    """Serve the webui. Explicit args win over config.yaml, which wins
    over the built-in defaults."""
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
        # The panel has no login, so reachability IS access: tokens, Groq keys
        # and every control are open to anyone who can hit this port.
        warning = (f"Bound to {bind} with no password, anyone who can reach "
                   "this port has full control, including your tokens and keys. "
                   "Prefer 127.0.0.1 plus Tailscale or a Cloudflare Tunnel.")
        bus.append("supervisor", warning, level="warn")
        print(f"[Supervisor] WARNING: {warning}", flush=True)
    uvicorn.run(create_app(supervisor), host=bind, port=port, log_level="warning")
