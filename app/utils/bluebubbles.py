"""app/utils/bluebubbles.py - a BlueBubbles Server from the panel's side: its address as people paste one, and a quick
look at whether it answers with its password, before an iMessage account is added (the Accounts page's Test).

iMessage only runs on Apple's own machines, so an iMessage account here reads and sends through BlueBubbles Server
(bluebubbles.app) on a Mac signed in to iMessage. The account itself talks to it from its runner
(app/platforms/snapchat/bluebubbles.js); this is the same address rule, in Python, and a ping.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

DOWNLOAD = "https://bluebubbles.app/downloads/"
GUIDE = "https://bluebubbles.app/install/"
# BlueBubbles Server's own port, which an address on the network is usually typed without.
DEFAULT_PORT = 1234


def _on_the_network(host: str) -> bool:
    """A host on this network rather than a tunnel's or a domain's: an IP, a .local name, a computer's own name."""
    return (bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host)) or ":" in host or host.lower().endswith(".local")
            or "." not in host)


def server_url(raw: str) -> str:
    """A BlueBubbles address as people paste one ("192.168.1.20:1234", "https://abc.trycloudflare.com/", the API's own
    ".../api/v1"), as its base: scheme, host, port, no trailing slash. "" for nothing usable. Typed bare, with no port,
    one on the network gets BlueBubbles' own port (1234) and a domain gets https, as tunnels serve it. The same as
    bluebubbles.js serverUrl()."""
    s = str(raw or "").strip()
    if not s or any(c.isspace() for c in s):
        return ""
    bare = not re.match(r"^[a-z][a-z0-9+.-]*://", s, re.I)
    if bare:
        s = "http://" + s
    try:
        parts = urlsplit(s)
        port = parts.port              # raises ValueError for a port out of range
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}|\[[0-9a-fA-F:.]+\]", parts.hostname if ":" not in parts.hostname
                        else f"[{parts.hostname}]"):
        return ""
    scheme = parts.scheme.lower()
    if bare and not port:
        if _on_the_network(parts.hostname):
            port = DEFAULT_PORT
        else:
            scheme = "https"
    path = re.sub(r"/api/v1/?.*$", "", parts.path, flags=re.I).rstrip("/")
    netloc = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    if port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, path, "", ""))


def _why(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"
    if "Timeout" in text:
        return "it did not answer in time"
    if "CERTIFICATE" in text.upper() or "SSL" in text.upper():
        return "its HTTPS certificate was refused"
    if "Name or service not known" in text or "getaddrinfo" in text or "nodename" in text:
        return "that address does not exist"
    if "refused" in text.lower() or "10061" in text:
        return "nothing is listening there (is BlueBubbles Server running on the Mac?)"
    return str(e) or type(e).__name__


async def check(raw_url: str, password: str, timeout: float = 15.0) -> dict:
    """Whether BlueBubbles answers at that address with that password, and what it says of the Mac:
    {"ok": True, "server", "account" (the Apple ID or number signed in to iMessage), "macos", "bluebubbles",
    "private_api", "helper"}, or {"ok": False, "reason"} in words. The password goes in the query, as BlueBubbles
    takes it, and is never given back."""
    import httpx
    base = server_url(raw_url)
    if not base:
        return {"ok": False, "reason": "That is not a BlueBubbles address. It looks like https://xyz.trycloudflare.com "
                                       "or 192.168.1.20:1234."}
    if not str(password or ""):
        return {"ok": False, "reason": "Its password, as set in BlueBubbles Server on the Mac, is needed too."}
    params = {"password": str(password)}
    headers = {"ngrok-skip-browser-warning": "1"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(f"{base}/api/v1/ping", params=params, headers=headers)
            if r.status_code == 401:
                return {"ok": False, "reason": "BlueBubbles answered, and refused that password."}
            if r.status_code >= 400:
                return {"ok": False, "reason": f"Something answered there, but not BlueBubbles (HTTP {r.status_code})."}
            try:
                pong = r.json()
            except ValueError:
                pong = None
            if not isinstance(pong, dict) or "status" not in pong:
                return {"ok": False, "reason": "Something answered there, but not BlueBubbles."}
            info_r = await client.get(f"{base}/api/v1/server/info", params=params, headers=headers)
            data = (info_r.json() or {}).get("data") or {} if info_r.status_code < 400 else {}
    except Exception as e:
        return {"ok": False, "reason": f"Nothing answered at {base}: {_why(e)}."}
    account = str(data.get("detected_imessage") or data.get("detected_icloud") or "")
    return {
        "ok": True, "server": base, "account": account,
        "macos": str(data.get("os_version") or ""), "bluebubbles": str(data.get("server_version") or ""),
        "private_api": bool(data.get("private_api")), "helper": bool(data.get("helper_connected")),
        **({} if account else {"warning": "The Mac does not seem to be signed in to iMessage."}),
    }
