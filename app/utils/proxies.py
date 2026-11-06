"""An account's own proxy: what can be said about one before anything tries to use it.

Set when the account is added (app/web/routes/account_routes.py), kept with its login as <PLATFORM>_PROXY_<n>, and read by
what connects that account: its browser, Telethon, baileys, the Minecraft connection. Written as a browser writes one,
http://user:pass@host:port or socks5://host:port, with http:// taken as read when nothing says.
"""
from urllib.parse import unquote, urlsplit

SCHEMES = ("http", "https", "socks5", "socks5h", "socks4")
# What runs in a Chrome of its own. Chrome takes a password for an http proxy and has no way to take one for SOCKS.
BROWSER_PLATFORMS = ("snapchat", "tiktok", "instagram", "x", "reddit")


def parse(raw) -> dict | None:
    """{"scheme", "host", "port", "username", "password"}, or None for nothing, or for something that is not one."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        u = urlsplit(text if "://" in text else f"http://{text}")
        port = u.port
    except ValueError:
        return None
    scheme = (u.scheme or "").lower()
    if scheme not in SCHEMES or not u.hostname or not port:
        return None
    return {"scheme": scheme, "host": u.hostname, "port": int(port), "username": unquote(u.username or ""),
            "password": unquote(u.password or "")}


def problem(raw, platform: str = "") -> str:
    """Why this would not work, in words, or "" when it would. Nothing at all is fine: no proxy."""
    if not str(raw or "").strip():
        return ""
    p = parse(raw)
    if not p:
        return "That is not a proxy. Write it like http://user:pass@host:port or socks5://host:port."
    if platform in BROWSER_PLATFORMS and p["scheme"].startswith("socks") and p["username"]:
        return "Chrome cannot use a password on a SOCKS proxy. Use an http:// one, or a SOCKS one with no password."
    return ""


def for_telethon(raw) -> dict | None:
    """What Telethon's proxy= takes (it reaches them through python-socks), or None for no proxy."""
    p = parse(raw)
    if not p:
        return None
    kind = {"socks5h": "socks5", "https": "http"}.get(p["scheme"], p["scheme"])
    out = {"proxy_type": kind, "addr": p["host"], "port": p["port"], "rdns": True}
    if p["username"]:
        out.update(username=p["username"], password=p["password"])
    return out
