"""
utils/session.py - REST sessions aligned to the gateway's client profile.

Two goals:
  1. Every raw REST call (friend requests, voice, profile edits) presents the
     SAME fingerprint as the gateway connection, so Discord never sees two
     different "clients" on one account.
  2. Optional desktop-client spoof: instead of the web client profile
     (browser: Chrome), identify as the Discord desktop app
     (browser: "Discord Client") on both gateway and REST.

The gateway (discord.py-self) builds its live Headers once at startup. The
runner hands that object to set_gateway_headers() (web mode) or swaps in a
desktop profile via build_desktop_headers() and hands THAT in. make_chrome_headers()
then derives everything from the gateway object so the two sides can't drift.
"""

import base64
import json
import re

from curl_cffi.requests import AsyncSession, impersonate

# curl_cffi 0.14+: DEFAULT_CHROME is a concrete target (e.g. "chrome142").
# The gateway itself impersonates exactly this target for its websocket TLS,
# so REST should use the same one - a random older target (110-124) was a
# visible mismatch with the gateway's UA.
_TLS_TARGET = getattr(impersonate, "DEFAULT_CHROME", "chrome124")
_TLS_MAJOR = int(re.search(r"(\d+)", _TLS_TARGET).group(1)) if re.search(r"(\d+)", _TLS_TARGET) else 124

# Electron major for a given Chromium major (Electron 28=Chromium 120, +2/+1).
_CHROMIUM_TO_ELECTRON = {
    120: "28", 122: "29", 124: "30", 126: "31", 128: "32", 130: "33",
    132: "34", 134: "35", 136: "36", 138: "37", 140: "38", 142: "39",
    144: "40", 146: "41", 148: "42", 150: "43",
}

# Cached desktop-client version (discord/x.y.z). Fetched live once per process;
# this is the value shipped in the desktop UA.
_DESKTOP_VERSION = None
_DEFAULT_DESKTOP_VERSION = "1.0.9256"

# Fallback desktop build number. Cosmetic: Discord does not gate requests on
# it (discord.py-self itself falls back to a hardcoded value when its fetch
# fails). Override with bot.desktop.build_number in config.yaml.
_DEFAULT_DESKTOP_BUILD = 407894

# The live gateway Headers object (discord.utils.Headers), if the runner has
# synced it yet. None until login (calls before that use static defaults).
_gateway_headers = None

# Proxy shared by gateway and every REST call, so one account never appears
# from two different IPs. Set by the runner from the account token config.
_default_proxy = None


def set_default_proxy(proxy: str = None) -> None:
    global _default_proxy
    _default_proxy = proxy or None


def set_gateway_headers(headers) -> None:
    """Sync REST headers with the gateway's live Headers object."""
    global _gateway_headers
    _gateway_headers = headers


def _static_ua() -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{_TLS_MAJOR}.0.0.0 Safari/537.36"
    )


def _static_super_properties() -> str:
    props = {
        "os": "Windows",
        "browser": "Chrome",
        "device": "",
        "system_locale": "en-US",
        "browser_user_agent": _static_ua(),
        "browser_version": f"{_TLS_MAJOR}.0.0.0",
        "os_version": "10",
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": "stable",
        "client_build_number": 9999,
        "client_event_source": None,
    }
    return base64.b64encode(json.dumps(props, separators=(",", ":")).encode()).decode()


async def _fetch_desktop_version() -> str:
    """Live discord/x.y.z from Discord's own installer redirect. Cached."""
    global _DESKTOP_VERSION
    if _DESKTOP_VERSION:
        return _DESKTOP_VERSION
    url = ("https://discord.com/api/downloads/distributions/app/installers/"
           "latest?arch=x64&channel=stable&platform=win")
    try:
        async with AsyncSession(impersonate=_TLS_TARGET, timeout=15) as s:
            resp = await s.get(url, allow_redirects=False)
        location = resp.headers.get("location", "")
        m = re.search(r"/(\d+\.\d+\.\d+)/", location)
        if m:
            _DESKTOP_VERSION = m.group(1)
            return _DESKTOP_VERSION
    except Exception:
        pass
    return _DEFAULT_DESKTOP_VERSION


def desktop_ua(discord_version: str, chrome_major: int) -> str:
    electron = _CHROMIUM_TO_ELECTRON.get(chrome_major, "34")
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"discord/{discord_version} "
        f"Chrome/{chrome_major}.0.0.0 "
        f"Electron/{electron}.0.0 "
        "Safari/537.36"
    )


async def build_desktop_headers(config: dict = None, web_headers=None):
    """Build a discord.utils.Headers instance that identifies as the desktop
    client. Reuses the lib's own class so client-hint greasing and the
    gateway_properties flow stay exactly consistent with it.

    Fidelity: the real desktop client's IDENTIFY properties contain ONLY
    os/browser/release_channel/client_build_number/client_event_source. Any
    web-style extras (device, browser_version, referrer, browser_user_agent)
    would mark the session as a browser, so they stay out of the properties.
    The desktop UA is used for the websocket/HTTP User-Agent header, which is
    where it belongs (pre-seeded into the cached property so it never leaks
    into super_properties)."""
    import discord  # heavy import, only when desktop profile is used

    config = config or {}
    bcfg = config.get("bot") or {}
    desktop_cfg = bcfg.get("desktop") or {}
    discord_version = await _fetch_desktop_version()
    build_number = int(desktop_cfg.get("build_number", _DEFAULT_DESKTOP_BUILD))
    ua = desktop_ua(discord_version, _TLS_MAJOR)

    properties = {
        "os": "Windows",
        "browser": "Discord Client",
        "release_channel": "stable",
        "client_build_number": build_number,
        "client_event_source": None,
    }
    encoded = base64.b64encode(
        json.dumps(properties, separators=(",", ":")).encode()
    ).decode()

    extra = {}
    if web_headers is not None:
        try:
            extra = dict(web_headers.extra_gateway_properties or {})
        except Exception:
            pass

    hdr = discord.utils.Headers(
        platform="Windows",
        major_version=_TLS_MAJOR,
        super_properties=properties,
        encoded_super_properties=encoded,
        extra_gateway_properties=extra,
    )
    # functools.cached_property reads instance __dict__ first, so this pins
    # the desktop UA for headers without putting it into super_properties.
    hdr.__dict__["user_agent"] = ua
    return hdr


# One default for each, used whether or not the config can be read. Two
# different fallbacks meant the timezone header flipped between them depending
# on whether load_config happened to throw, which is exactly the drift this
# module exists to prevent.
_DEFAULT_LOCALE = "en-US"
_DEFAULT_TIMEZONE = "Europe/Paris"


def _effective_headers():
    """(ua, super_properties_b64, client_hints, locale, timezone) for this process."""
    locale, timezone = _DEFAULT_LOCALE, _DEFAULT_TIMEZONE
    try:
        from app.utils.helpers import load_config  # late: avoids circular import
        bcfg = (load_config().get("bot") or {})
        locale = bcfg.get("locale", _DEFAULT_LOCALE)
        timezone = bcfg.get("timezone", _DEFAULT_TIMEZONE) or ""
    except Exception:
        pass

    h = _gateway_headers
    if h is not None:
        try:
            ua = h.user_agent
            sp = h.encoded_super_properties
            hints = dict(h.client_hints or {})
            return ua, sp, hints, locale, timezone
        except Exception:
            pass

    hints = {
        "sec-ch-ua": (
            f'"Chromium";v="{_TLS_MAJOR}", '
            f'"Google Chrome";v="{_TLS_MAJOR}", '
            f'"Not-A.Brand";v="99"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    return _static_ua(), _static_super_properties(), hints, locale, timezone


def make_chrome_headers(token: str, extra: dict = None) -> dict:
    """Browser headers matching the process's client profile (web or desktop)."""
    ua, super_properties, hints, locale, timezone = _effective_headers()

    headers = {
        "Authorization": token,
        "User-Agent": ua,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://discord.com",
        "Priority": "u=0, i",
        "Referer": "https://discord.com/channels/@me",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "X-Debug-Options": "bugReporterEnabled",
        "X-Discord-Locale": locale,
        "X-Super-Properties": super_properties,
    }
    for k, v in hints.items():
        headers[k] = v
    if timezone:
        headers["X-Discord-Timezone"] = timezone

    if extra:
        headers.update(extra)

    return headers


def build_session(token: str, extra_headers: dict = None, proxy: str = None) -> AsyncSession:
    """
    Return a curl_cffi AsyncSession impersonating the same Chrome target as
    the gateway (realistic JA3/TLS fingerprint). If no proxy is passed, the
    account-wide default set by the runner is used so gateway and REST never
    leave from different IPs.

    Use as an async context manager:  async with build_session(token) as s: ...
    """
    effective_proxy = proxy or _default_proxy
    kwargs = {"impersonate": _TLS_TARGET}
    if effective_proxy:
        kwargs["proxies"] = {"https": effective_proxy, "http": effective_proxy}
    session = AsyncSession(**kwargs)
    session.headers.update(make_chrome_headers(token, extra_headers))
    return session
