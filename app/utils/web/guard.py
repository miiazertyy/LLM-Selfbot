"""
Where the web helpers may go: http and https, to public addresses only.

A link anyone sends is opened by the bot, on this computer. Without this, http://127.0.0.1:8787/api/... would be the
panel's own API answering it, and http://192.168.1.1 the router: what came back would go into a reply. So a name is
looked up first and every address it has must be a public one, and the same again for every redirect. Names that
only mean something at home (localhost, .local, a name with no dot) are refused before they are looked up. The
browser (webbrowser.js) refuses the same before it loads anything.
"""
from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlsplit

# Names that only ever mean a machine nearby.
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa", ".corp", ".intranet")


class Blocked(ValueError):
    """Not a place the web helpers may go, and why."""


def _ip(text: str):
    try:
        return ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        return None


def public_ip(address) -> bool:
    """A public internet address: not loopback, private, link-local, shared, reserved or multicast."""
    ip = address if not isinstance(address, str) else _ip(address)
    if ip is None:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast and not ip.is_reserved


def check_url(url: str) -> str:
    """The link, when it may be opened at all, as far as can be told without looking its name up. Raises Blocked."""
    url = str(url or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        raise Blocked("not a link")
    if parts.scheme.lower() not in ("http", "https"):
        raise Blocked("only http and https links")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise Blocked("a link with no site")
    if parts.username or parts.password:
        raise Blocked("a link with a login in it")
    ip = _ip(host)
    if ip is not None:
        if not public_ip(ip):
            raise Blocked("an address inside this computer or network")
        return url
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host:
        raise Blocked("a name that only means something on this network")
    return url


def _all_public(host: str, infos) -> None:
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(public_ip(a) for a in addresses):
        raise Blocked(f"{host} points inside this computer or network")


async def check(url: str) -> str:
    """check_url, then its name looked up: every address it has must be public. Raises Blocked."""
    url = check_url(url)
    host = (urlsplit(url).hostname or "").rstrip(".")
    if _ip(host) is not None:
        return url
    try:
        infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, None), 8.0)
    except Exception:
        raise Blocked(f"{host} could not be found")
    _all_public(host, infos)
    return url


def check_sync(url: str) -> str:
    """check(), for code on a worker thread."""
    import socket
    url = check_url(url)
    host = (urlsplit(url).hostname or "").rstrip(".")
    if _ip(host) is not None:
        return url
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        raise Blocked(f"{host} could not be found")
    _all_public(host, infos)
    return url
