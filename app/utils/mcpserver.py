"""The app's tools for an AI app, over MCP: an AI app (Claude Desktop, Cursor and the like) starts this as a small program
and talks to it on stdin and stdout, so nothing new listens on the network. It does no work itself: each call is passed
to the open app, which applies the limits (app/utils/apptools.py).

Two generations of the protocol are in use, and an AI app may be on either. The current one (2026-07-28) has no
handshake: every request says its version in _meta. Older ones (2025-11-25 and before) open with initialize. Which it is
comes from how the client opens, as the spec's "dual-era" servers do.

Only the standard library and app.utils.paths, so it starts fast and prints nothing but protocol on stdout.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from app.utils import apptools
from app.utils.paths import DATA_DIR

MODERN = ("2026-07-28",)
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
_VERSION = "io.modelcontextprotocol/protocolVersion"
_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
_CLIENT = "io.modelcontextprotocol/clientInfo"
_SERVER = "io.modelcontextprotocol/serverInfo"

_INVALID_REQUEST = -32600
_NO_METHOD = -32601
_INVALID_PARAMS = -32602
_INTERNAL = -32603
_PARSE = -32700
_UNSUPPORTED = -32022

NOT_OPEN = "LLMSelfbot is not open. Open it, then try again."
_ANSWER_TIMEOUT = 60


def _port_file():
    return DATA_DIR / "cache" / "panel.json"


def note_port(port: int, bind: str = "127.0.0.1") -> None:
    """Where the panel is listening: not always the configured port, which may have been taken."""
    try:
        path = _port_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        host = "127.0.0.1" if bind in ("", "0.0.0.0", "::") else bind
        path.write_text(json.dumps({"host": host, "port": int(port), "pid": os.getpid()}), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def _panel_address() -> str | None:
    """host:port of the open app. None when it has never said: guessing the usual port could find another copy."""
    try:
        data = json.loads(_port_file().read_text(encoding="utf-8"))
        return f"{data.get('host') or '127.0.0.1'}:{int(data['port'])}"
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _server_info() -> dict:
    from app.version import __version__
    return {"name": "llmselfbot", "title": "LLMSelfbot", "version": str(__version__)}


def ask_app(tool: str, args: dict, who: str) -> dict:
    """One tool run by the open app: {"ok": True, "result": ...} or {"ok": False, "error": words}."""
    where = _panel_address()
    if where is None:
        return {"ok": False, "error": NOT_OPEN}
    body = json.dumps({"tool": tool, "args": args, "who": who}).encode("utf-8")
    req = urllib.request.Request(f"http://{where}/api/apptools/call", data=body, method="POST",
                                 headers={"content-type": "application/json", "x-llmselfbot": "1"})
    # Straight to this computer: a proxy set for the web must not be asked for 127.0.0.1.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=_ANSWER_TIMEOUT) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:       # something else has that port now, or a copy from before this existed
            return {"ok": False, "error": NOT_OPEN}
        return {"ok": False, "error": f"LLMSelfbot could not do that (error {e.code})."}
    except (urllib.error.URLError, OSError):
        return {"ok": False, "error": NOT_OPEN}
    except ValueError:
        return {"ok": False, "error": "LLMSelfbot gave an answer that could not be read."}


class Server:
    """One connection: what a line in gets as a line out."""

    def __init__(self, ask=ask_app):
        self.ask = ask
        self.legacy = False
        self.client = "An AI app"

    def _name_client(self, info) -> None:
        if isinstance(info, dict) and info.get("name"):
            self.client = str(info.get("title") or info["name"])[:40]

    def handle_line(self, line: bytes) -> dict | None:
        try:
            message = json.loads(line)
        except ValueError:
            return self._error(None, _PARSE, "That was not JSON.")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(message.get("id") if isinstance(message, dict) else None, _INVALID_REQUEST, "Not a JSON-RPC 2.0 message.")
        if "method" not in message:
            return None         # an answer to something this never asked
        if "id" not in message:
            return None         # a notification: initialized and cancelled need nothing from this
        try:
            return self._request(message)
        except Exception as e:  # one bad call must not end the connection
            return self._error(message.get("id"), _INTERNAL, f"Something went wrong: {type(e).__name__}")

    @staticmethod
    def _error(id_, code: int, text: str, data=None) -> dict:
        error = {"code": code, "message": text}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": id_, "error": error}

    def _request(self, message: dict) -> dict:
        id_, method = message.get("id"), message.get("method")
        params = message.get("params")
        if params is not None and not isinstance(params, dict):
            return self._error(id_, _INVALID_PARAMS, "params has to be an object.")
        params = params or {}
        if method == "initialize":
            return self._initialize(id_, params)
        if method == "ping":
            return {"jsonrpc": "2.0", "id": id_, "result": {}}
        if method not in ("server/discover", "tools/list", "tools/call"):
            return self._error(id_, _NO_METHOD, f"There is no method called {method}.")

        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        modern = _VERSION in meta
        if modern:
            supported = [*MODERN, *LEGACY]
            if meta[_VERSION] not in MODERN:
                return self._error(id_, _UNSUPPORTED, "Unsupported protocol version",
                                   {"supported": supported, "requested": meta[_VERSION]})
            if _CAPABILITIES not in meta:
                return self._error(id_, _INVALID_PARAMS, f"_meta is missing {_CAPABILITIES}.")
            self._name_client(meta.get(_CLIENT))
        elif not self.legacy:
            return self._error(id_, _INVALID_PARAMS, f"_meta is missing {_VERSION}.")

        if method == "server/discover":
            result = {"supportedVersions": list(MODERN), "capabilities": {"tools": {}}, "instructions": apptools.INSTRUCTIONS,
                      "ttlMs": 3600000, "cacheScope": "public"}
        elif method == "tools/list":
            result = {"tools": apptools.TOOLS}
            if modern:
                result.update(ttlMs=3600000, cacheScope="public")
        else:
            name = params.get("name")
            if name not in apptools.NAMES:
                return self._error(id_, _INVALID_PARAMS, f"Unknown tool: {name}")
            args = params.get("arguments")
            if args is not None and not isinstance(args, dict):
                return self._error(id_, _INVALID_PARAMS, f"Invalid arguments for tool {name}: not an object.")
            result = self._call(name, args or {})
        if modern:
            result = {**result, "resultType": "complete", "_meta": {_SERVER: _server_info()}}
        return {"jsonrpc": "2.0", "id": id_, "result": result}

    def _initialize(self, id_, params: dict) -> dict:
        self.legacy = True
        self._name_client(params.get("clientInfo"))
        asked = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": asked if asked in LEGACY else LEGACY[0],
            "capabilities": {"tools": {}},
            "serverInfo": _server_info(),
            "instructions": apptools.INSTRUCTIONS,
        }}

    def _call(self, name: str, args: dict) -> dict:
        got = self.ask(name, args, self.client)
        if got.get("ok"):
            return {"content": [{"type": "text", "text": json.dumps(got.get("result"), ensure_ascii=False)}], "isError": False}
        return {"content": [{"type": "text", "text": str(got.get("error") or "That did not work.")}], "isError": True}


def run() -> None:
    """Answer on stdout until the AI app closes stdin."""
    if sys.stdin is None or sys.stdout is None:
        return
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    # Only protocol may reach stdout: anything printed from here on goes to stderr, which AI apps keep as a log.
    sys.stdout = sys.stderr
    server = Server()
    for line in source:
        if not line.strip():
            continue
        reply = server.handle_line(line)
        if reply is None:
            continue
        sink.write(json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        sink.flush()
