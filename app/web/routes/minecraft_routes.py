"""Minecraft in the panel: installing mindcraft-ce, and what a running account's card asks of it.

The install itself lives in app/platforms/minecraft/install.py, so it can be run and tested without a web server;
these routes only start it on a thread, stream what it says into the log bus (source "minecraft-install", which the
setup panel tails), and report where it is.
"""
import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.platforms.minecraft import install
from app.web.logbus import bus

router = APIRouter(tags=["minecraft"])

_install_lock = threading.Lock()
LOG_SOURCE = "minecraft-install"


def _say(text, level=None):
    bus.append(LOG_SOURCE, str(text), level)


@router.get("/api/minecraft/status")
async def mc_status():
    from app.web.routes.system_routes import _snap_runner_states
    # Asking Node its version and measuring the disk are both blocking: never on the event loop.
    out = await asyncio.to_thread(install.status)
    out["installing"] = _install_lock.locked()
    # Each running account's own word on what it is doing (ipc/mc_state*.json), as the other platforms report.
    out["runners"] = await asyncio.to_thread(_snap_runner_states, "mc")
    return out


def _start(job, name: str) -> dict:
    if not _install_lock.acquire(blocking=False):
        return {"ok": False, "reason": "an install is already running"}

    def run():
        try:
            job(_say)
        except Exception as e:
            _say(f"{name} failed: {e}", "error")
        finally:
            _install_lock.release()

    threading.Thread(target=run, daemon=True, name=f"minecraft-{name.lower()}").start()
    return {"ok": True, "queued": True}


@router.post("/api/minecraft/install")
async def mc_install():
    """Install, or reinstall at the pinned commit. Minutes long: it runs on a thread and says how it is going."""
    return _start(install.install, "Install")


@router.post("/api/minecraft/uninstall")
async def mc_uninstall():
    """mindcraft-ce off the disk, keeping what its bots remember."""
    return _start(install.uninstall, "Uninstall")


# ── ViaProxy: joining a server of any version ────────────────────────────────
# Before the account routes below, whose /api/minecraft/{web_id}/{op} would otherwise take these.
_via_lock = threading.Lock()


@router.get("/api/minecraft/viaproxy/status")
async def via_status():
    from app.platforms.minecraft import viaproxy
    out = await asyncio.to_thread(viaproxy.status)
    out["installing"] = _via_lock.locked()
    return out


def _start_via(job, name: str) -> dict:
    if not _via_lock.acquire(blocking=False):
        return {"ok": False, "reason": "ViaProxy is already being installed"}

    def run():
        try:
            job(_say)
        except Exception as e:
            _say(f"ViaProxy {name.lower()} failed: {e}", "error")
        finally:
            _via_lock.release()

    threading.Thread(target=run, daemon=True, name=f"viaproxy-{name.lower()}").start()
    return {"ok": True, "queued": True}


@router.post("/api/minecraft/viaproxy/install")
async def via_install():
    """The newest ViaProxy, for the Java this computer has. Takes a minute: on a thread, saying how it goes."""
    from app.platforms.minecraft import viaproxy
    return _start_via(viaproxy.install, "Install")


@router.post("/api/minecraft/viaproxy/uninstall")
async def via_uninstall():
    from app.platforms.minecraft import viaproxy
    return _start_via(viaproxy.uninstall, "Uninstall")


# What a card asks of its account, as the bridge's commands (snapchat_bridge.py _mc_op_cmd, _mc_join_cmd).
_OPS = {"goal": "mc_tell", "leave": "mc_leave", "join": "mc_join", "state": "mc_state",
        "server": "mc_join_server", "home": "mc_join_server"}


@router.post("/api/minecraft/{web_id}/{op}")
async def mc_op(web_id: str, op: str, request: Request):
    """A goal for it to get done ("build a shelter before dark"), worked at by itself; leaving the world, and joining
    it again; or what it is doing right now."""
    from app.core import ipc
    if op not in _OPS:
        raise HTTPException(status_code=404, detail="not something Minecraft does")
    meta = ipc.discover_targets().get(web_id)
    if not meta or meta.get("platform") != "minecraft":
        raise HTTPException(status_code=404, detail="no such Minecraft account")
    payload = {}
    if op in ("goal", "server"):
        try:
            body = await request.json()
        except Exception:
            body = {}
    if op == "goal":
        text = " ".join(str((body or {}).get("text") or "").split())[:300]
        if not text:
            raise HTTPException(status_code=400, detail="what should it do?")
        payload = {"text": text}
    elif op == "server":
        address = str((body or {}).get("address") or "").strip()[:120]
        if not address:
            raise HTTPException(status_code=400, detail="which server?")
        payload = {"address": address, "by_owner": True}
    elif op == "home":
        payload = {"address": "home", "by_owner": True}
    if op == "goal":
        # A goal is for it to work at by itself: hands on it from the view would hold it still.
        await _let_go(web_id)
    r = await ipc.send_and_wait(meta["target"], _OPS[op], payload, timeout=50.0)
    return r or {"ok": False, "reason": "It did not answer. Is it running?"}


async def _let_go(web_id: str) -> None:
    """Whoever is playing it by hand from its view lets go (agent_hooks.mjs letGo). Nothing when nobody is."""
    import httpx
    view = _view_of(web_id)
    if not view:
        return
    url = f"http://127.0.0.1:{int(view['port'])}/api/minecraft/{web_id}/view/drive"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as c:
            await c.post(url, json={"on": False}, headers={"x-llmselfbot": "1"})
    except httpx.HTTPError:
        pass


# ── The live view, through the panel ─────────────────────────────────────────
# What it sees, as prismarine-viewer draws it: served by the bot's own process on this computer only
# (agent_hooks.mjs), at a port its runner writes down (ipc/mc_view*.json), under this very path, so the page and its
# socket can be passed through as they are. Through the panel, it works wherever the panel does (a phone on the same
# network included), and nothing about the bot listens anywhere else.
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
        "transfer-encoding", "upgrade", "host", "content-length", "content-encoding"}
_client = None

_NOT_YET = """<!doctype html><meta charset="utf-8"><title>Nothing to watch</title>
<body style="margin:0;height:100vh;display:grid;place-items:center;background:#120e12;color:#a59aa6;
font:14px system-ui,sans-serif;text-align:center"><div>Nothing to watch yet.<br>
<span style="opacity:.7">It shows once the account is in a world.</span></div>
<script>setTimeout(() => location.reload(), 4000)</script>"""


def _view_of(web_id: str) -> dict:
    import re
    from app.utils.paths import DATA_DIR
    m = re.fullmatch(r"minecraft_(\d{1,3})", web_id)
    if not m:
        return {}
    n = int(m.group(1))
    try:
        data = json.loads((DATA_DIR / "ipc" / f"mc_view{'' if n == 1 else f'_{n}'}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and int(data.get("port") or 0) > 0 else {}


@router.get("/api/minecraft/{web_id}/view/status")
async def mc_view_status(web_id: str):
    view = _view_of(web_id)
    return {"ready": bool(view), "version": view.get("version", ""), "error": view.get("error", "")}


@router.get("/api/minecraft/{web_id}/view")
async def mc_view_page(web_id: str, request: Request):
    # The page finds its socket at its own path plus "socket.io": it has to be loaded with the slash.
    query = request.url.query
    return RedirectResponse(f"/api/minecraft/{web_id}/view/" + (f"?{query}" if query else ""))


def _same_site(origin: str, host: str) -> bool:
    """A page of the panel's own: no Origin (not a browser page's request), or one naming the panel's own host."""
    if not origin:
        return True
    from urllib.parse import urlparse
    try:
        return urlparse(origin).netloc.lower() == str(host or "").lower()
    except ValueError:
        return False


@router.api_route("/api/minecraft/{web_id}/view/{path:path}", methods=["GET", "POST"])
async def mc_view(web_id: str, path: str, request: Request):
    global _client
    import httpx
    view = _view_of(web_id)
    if not view:
        return HTMLResponse(_NOT_YET, status_code=503)
    # The view's own requests carry its keys and clicks now: another site's page may not send them through.
    if request.method == "POST" and not _same_site(request.headers.get("origin", ""), request.headers.get("host", "")):
        return Response(status_code=403)
    if _client is None:
        # Long-polling holds a request open for up to half a minute.
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
    url = f"http://127.0.0.1:{int(view['port'])}/api/minecraft/{web_id}/view/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    # Says it came through the panel: the bot's end opens its connection to nothing else (agent_hooks.mjs).
    headers["x-lsb-panel"] = "1"
    try:
        r = await _client.request(request.method, url, params=list(request.query_params.multi_items()),
                                  content=await request.body(), headers=headers)
    except httpx.HTTPError:
        return HTMLResponse(_NOT_YET, status_code=503)
    return Response(content=r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in _HOP})


@router.websocket("/api/minecraft/{web_id}/view/socket.io/")
async def mc_view_socket(ws: WebSocket, web_id: str):
    """The view's socket, passed through frame for frame. Its page's address rides along as the referer, which is
    how the bot's end tells its eyes from a view from above."""
    import websockets
    view = _view_of(web_id)
    if not view:
        await ws.close(code=1013)
        return
    # The keys and the mouse go over this connection: only the panel's own pages may open it (a browser lets any
    # site's page open a socket anywhere, so its Origin is what tells).
    if not _same_site(ws.headers.get("origin", ""), ws.headers.get("host", "")):
        await ws.close(code=1008)
        return
    upstream = f"ws://127.0.0.1:{int(view['port'])}/api/minecraft/{web_id}/view/socket.io/?{ws.url.query}"
    await ws.accept()
    referer = ws.headers.get("referer", "")
    passed = {"X-Lsb-Panel": "1", **({"Referer": referer} if referer else {})}
    try:
        async with websockets.connect(upstream, max_size=None, open_timeout=10, additional_headers=passed) as up:
            async def down():
                async for message in up:
                    if isinstance(message, (bytes, bytearray)):
                        await ws.send_bytes(bytes(message))
                    else:
                        await ws.send_text(message)

            async def back():
                while True:
                    message = await ws.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        await up.send(message["bytes"])
                    elif message.get("text") is not None:
                        await up.send(message["text"])

            tasks = [asyncio.create_task(down()), asyncio.create_task(back())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except Exception:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
