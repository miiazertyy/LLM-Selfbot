"""app/web/routes/relay_routes.py - iMessage with no Mac: what an iPhone or iPad posts its messages to.

iMessage only runs on Apple's own machines. With a Mac, BlueBubbles Server on it carries the messages
(app/platforms/snapchat/bluebubbles.js). Without one, the phone itself can: a Shortcuts automation that runs on every
message it gets (Messages, from anybody, run immediately) posts the message here, and sends back to whoever wrote
whatever this answers. The account's own worker writes the answer (app/platforms/snapchat_bridge.py, _relay_cmd),
with the persona, its memory and the conversation so far, the same way it answers through a Mac.

The address carries a secret of the account's own (IMESSAGE_RELAY_<n>, made when the account is added), which is
the only thing that lets a message in: the panel itself may be open to the network with no password.
"""
import hmac
import json
import os
import socket
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.core import ipc
from app.utils.paths import DATA_DIR

router = APIRouter()

# Shortcuts gives up on a request after a minute: the worker answers within 45 s, this waits a little longer.
WAIT_S = 55.0
# When each account last heard from its phone, and from the test page: the Setup page says so.
_HEARD: dict = {}


def _account_for(token: str) -> int:
    """Which iMessage account a relay secret is, 0 for none. Compared in constant time."""
    token = str(token or "")
    if len(token) < 16:
        return 0
    n = 1
    while os.getenv(f"IMESSAGE_SERVER_{n}"):
        if (os.getenv(f"IMESSAGE_SERVER_{n}", "").strip().lower() == "phone"
                and hmac.compare_digest(os.getenv(f"IMESSAGE_RELAY_{n}", ""), token)):
            return n
        n += 1
    return 0


def _worker_up(n: int) -> bool:
    """Whether the account's worker is running: it writes its state every 20 s while it is."""
    sfx = "" if n == 1 else f"_{n}"
    try:
        state = json.loads((DATA_DIR / "ipc" / f"imsg_state{sfx}.json").read_text(encoding="utf-8"))
        return bool(state.get("phone")) and time.time() - float(state.get("at") or 0) < 90
    except (OSError, ValueError, TypeError):
        return False


async def _message_of(request: Request) -> tuple:
    """(who sent it, what they said), however the shortcut sent them: a JSON body, a form, or the address."""
    raw = (await request.body())[:20000]
    data = {}
    ctype = request.headers.get("content-type", "")
    if raw:
        try:
            data = json.loads(raw.decode("utf-8")) if "json" in ctype or raw[:1] in (b"{", b"[") else {}
        except (ValueError, UnicodeDecodeError):
            data = {}
        if not data and "form" in ctype:
            data = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items() if v}
    data = data if isinstance(data, dict) else {}
    data = {**dict(request.query_params), **data}
    low = {str(k).lower(): v for k, v in data.items()}
    who = next((low[k] for k in ("from", "sender", "who", "name") if low.get(k)), "")
    text = next((low[k] for k in ("text", "message", "content", "body") if low.get(k)), "")
    return str(who)[:200], str(text)[:4000]


@router.post("/relay/imessage/{token}")
async def relay_message(request: Request, token: str):
    """One message the phone passed on. The answer comes back as the body, plain text, for the shortcut's Send
    Message; nothing at all when there is nothing to send (ignored, paused, several in a row answered once)."""
    n = _account_for(token)
    if not n:
        return PlainTextResponse("", status_code=404)
    who, text = await _message_of(request)
    _HEARD[n] = {"at": time.time(), "test": False}
    if not who or not text.strip() or not _worker_up(n):
        return PlainTextResponse("")
    result = await ipc.send_and_wait(ipc.browser_target("imessage", n), "relay", {"from": who, "text": text},
                                     timeout=WAIT_S)
    return PlainTextResponse(str((result or {}).get("reply") or ""))


@router.get("/relay/imessage/{token}")
async def relay_test(request: Request, token: str):
    """The address opened in Safari on the phone: proof the phone reaches this PC, before the shortcut is made."""
    n = _account_for(token)
    if not n:
        return HTMLResponse(_page("Not this address", "This link is not one of your iMessage accounts' any more. "
                                  "Copy it again from the app, Settings, iMessage, Setup.", ok=False), status_code=404)
    _HEARD[n] = {"at": time.time(), "test": True}
    up = _worker_up(n)
    return HTMLResponse(_page("Your iPhone reaches this PC" if up else "It reaches the PC, but the account is off",
                              "Put this same address in the shortcut's Get Contents of URL. Then every message you "
                              "get is answered from the PC." if up else
                              "Start iMessage account #%d in the app, then this works." % n, ok=up))


@router.get("/api/imessage/relay/status")
async def relay_status(request: Request):
    """For the Setup page: when each account last heard from its phone, and which addresses this PC has that a
    phone could reach it at (the same Wi-Fi, or Tailscale), with whether the panel listens beyond this PC at all."""
    from app.utils.helpers import load_config
    web = ((load_config() or {}).get("services") or {}).get("webui") or {}
    bind = str(web.get("bind") or "127.0.0.1")
    port = int(request.url.port or web.get("port") or 8787)
    return {"heard": {str(k): v for k, v in _HEARD.items()}, "bind": bind,
            "open": bind not in ("127.0.0.1", "localhost", "::1"),
            "addresses": [{"url": f"http://{ip}:{port}", "kind": kind} for ip, kind in _addresses()]}


@router.get("/api/imessage/relay/{index}")
async def relay_address(request: Request, index: int, base: str = ""):
    """One iPhone account's address, for its Setup: the whole thing to paste into the shortcut, and a QR code of it
    for the phone's camera (which opens the test page, from where it can be copied). `base` is the address the page
    itself was opened at when that was not this PC: then it is the one the phone already reaches it by."""
    import io
    if (os.getenv(f"IMESSAGE_SERVER_{index}", "").strip().lower() != "phone"
            or not os.getenv(f"IMESSAGE_RELAY_{index}")):
        return {"ok": False, "reason": "That iMessage account does not go through an iPhone"}
    status = await relay_status(request)
    base = str(base or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")) or "127.0.0.1" in base or "localhost" in base:
        base = (status["addresses"] or [{"url": ""}])[0]["url"]
    url = f"{base}/relay/imessage/{os.getenv(f'IMESSAGE_RELAY_{index}')}" if base else ""
    svg = ""
    if url:
        try:
            import segno
            buf = io.BytesIO()
            segno.make(url, error="m").save(buf, kind="svg", scale=1, border=2, dark="#101018", light=None,
                                            svgclass=None, lineclass=None, omitsize=True, xmldecl=False, svgns=True)
            svg = buf.getvalue().decode("utf-8")
        except Exception:
            svg = ""
    return {"ok": True, "url": url, "qr": svg, "open": status["open"], "bind": status["bind"],
            "addresses": status["addresses"], "heard": status["heard"].get(str(index))}


def _addresses() -> list:
    """This PC's addresses another device could use: Tailscale's first (it works away from home), then the Wi-Fi's."""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    try:
        # The address the PC goes out on: the one its Wi-Fi gave it. A UDP "connect" sends nothing.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.insert(0, s.getsockname()[0])
    except OSError:
        pass
    # One of each kind: the PC's other adapters (WSL's, a virtual machine's) are private addresses too, and no phone
    # reaches them; the one it goes out on was put first above.
    out, kinds = [], set()
    for ip in found:
        if ip.startswith(("127.", "169.254.")):
            continue
        a, b = (int(x) for x in ip.split(".")[:2])
        kind = ("tailscale" if a == 100 and 64 <= b <= 127
                else "wifi" if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) else "")
        if not kind or kind in kinds:
            continue
        kinds.add(kind)
        if kind == "tailscale":
            out.insert(0, (ip, kind))
        else:
            out.append((ip, kind))
    return out


def _page(title: str, text: str, ok: bool) -> str:
    color = "#34c759" if ok else "#ff9f0a"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d0b14;color:#e9e6f2;
font-family:-apple-system,system-ui,sans-serif}}main{{max-width:340px;padding:28px;text-align:center}}
i{{display:inline-grid;place-items:center;width:64px;height:64px;border-radius:20px;font-style:normal;font-size:32px;
background:{color}22;color:{color};box-shadow:inset 0 0 0 1px {color}66}}h1{{font-size:20px;margin:18px 0 8px}}
p{{margin:0;color:#a8a3b8;font-size:15px;line-height:1.45}}</style></head>
<body><main><i>{"&#10003;" if ok else "!"}</i><h1>{title}</h1><p>{text}</p></main></body></html>"""
