"""app/web/routes/account_routes.py - add, edit and remove account slots. An "account" is a numbered set of credentials in config/.env: Discord DISCORD_TOKEN_<n> / DISCORD_PROXY_<n>, Snapchat SNAP_USERNAME_<n> / SNAP_PASSWORD_<n>, TikTok TIKTOK_USERNAME_<n> (its login lives in its own browser profile, never in a file). The numbering must stay contiguous from 1, because the account counters stop at the first gap, so deleting slot 2 of 3 renumbers the old slot 3 down to 2. Credentials are write-only: a GET never returns a token or password, not even masked, it reports whether one is set, and the UI can only replace it."""

import asyncio
import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.utils import proxies
from app.utils.credentials import is_placeholder
from app.web.envfile import read_env, reload_into_process, write_env

router = APIRouter(tags=["accounts"])

PLATFORMS = {
    "discord": {
        "fields": {"token": "DISCORD_TOKEN", "proxy": "DISCORD_PROXY"},
        "secret": ("token",),
        "required": "token",
    },
    "snapchat": {
        "fields": {"username": "SNAP_USERNAME", "password": "SNAP_PASSWORD", "proxy": "SNAP_PROXY"},
        "secret": ("password",),
        "required": "username",
    },
    # The @handle it signed in as. Signing in happens in a browser window (tiktok_browser_login), which keeps the
    # session in that account's own profile; there is no password to store.
    "tiktok": {
        "fields": {"username": "TIKTOK_USERNAME", "proxy": "TIKTOK_PROXY"},
        "secret": (),
        "required": "username",
    },
    # Instagram signs itself in and back in, so it keeps the login: the username, the password, and the 2FA key the
    # six digits are made from. The last two are write-only, as Snapchat's password is.
    "instagram": {
        "fields": {"username": "INSTAGRAM_USERNAME", "password": "INSTAGRAM_PASSWORD", "totp": "INSTAGRAM_TOTP",
                   "proxy": "INSTAGRAM_PROXY"},
        "secret": ("password", "totp"),
        "required": "username",
    },
    # Minecraft: the name it plays as, the world it joins, and how it signs in there. Nothing secret: an offline
    # server needs no account, and a Microsoft one signs in through a code on its first run (the card asks for it).
    # X signs itself in and back in, so it keeps the whole login: the @handle, the password, the 2FA key the six
    # digits are made from, and the email or phone X asks for when it questions a login ("unusual login
    # activity"). Without that last one the sign-in has nowhere to go. The password and the key are write-only;
    # the email is not, so it can be seen and corrected.
    "x": {
        "fields": {"username": "X_USERNAME", "password": "X_PASSWORD", "totp": "X_TOTP", "email": "X_EMAIL",
                   "proxy": "X_PROXY"},
        "secret": ("password", "totp"),
        "required": "username",
    },
    # Reddit signs in the way TikTok does: a window opens, a person signs in, and the session stays in that
    # account's own browser profile. The username is what the window reported, and names that profile. The password
    # and the 2FA key are optional and write-only: they are only what lets it sign itself back in later, with
    # nobody there.
    "reddit": {
        "fields": {"username": "REDDIT_USERNAME", "password": "REDDIT_PASSWORD", "totp": "REDDIT_TOTP",
                   "proxy": "REDDIT_PROXY"},
        "secret": ("password", "totp"),
        "required": "username",
    },
    # WhatsApp keeps a number and nothing else. Its login is the set of keys the phone handed over when it was
    # linked (config/whatsapp-<number>-auth), so there is no password, no token and nothing write-only: the only
    # way in is a person with the phone. It is called "username" here because that is the name the slot
    # machinery and the panel already use for "the one thing that names this account".
    "whatsapp": {
        "fields": {"username": "WHATSAPP_NUMBER", "proxy": "WHATSAPP_PROXY"},
        "secret": (),
        "required": "username",
    },
    "minecraft": {
        "fields": {"username": "MINECRAFT_USERNAME", "host": "MINECRAFT_HOST", "port": "MINECRAFT_PORT",
                   "auth": "MINECRAFT_AUTH", "proxy": "MINECRAFT_PROXY"},
        "secret": (),
        "required": "username",
    },
    # iMessage reads and sends through a BlueBubbles Server on a Mac signed in to iMessage: its address, and its
    # password, write-only. The Apple account itself stays on the Mac: nothing of it is kept here.
    # Telegram: the persona's own Telegram account. Nothing here is typed in by hand - signing in writes all four,
    # and the session string it leaves is the login from then on, so it is the one that says the account exists.
    "telegram": {
        "fields": {"session": "TELEGRAM_SESSION", "api_id": "TELEGRAM_API_ID", "api_hash": "TELEGRAM_API_HASH",
                   "phone": "TELEGRAM_PHONE", "proxy": "TELEGRAM_PROXY"},
        "secret": ("session", "api_hash"),
        "required": "session",
    },
    "imessage": {
        # `server` is the Mac's BlueBubbles address, or "phone" for an iPhone or iPad carrying the messages itself
        # (a Shortcuts automation posting each to /relay/imessage/<relay>). `relay` is that address's secret: shown
        # on the Setup page so it can go into the shortcut, the one way the phone's messages get in.
        "fields": {"server": "IMESSAGE_SERVER", "password": "IMESSAGE_PASSWORD", "relay": "IMESSAGE_RELAY"},
        "secret": ("password",),
        "required": "server",
    },
}
MAX_SLOTS = 50

# The proxy typed in the add dialog, for an account added by signing in: the sign-in goes through it, and it is filed
# with whichever account that turns out to be. iMessage has none: it talks to your own Mac or phone, not to a service.
_signin_proxy: dict = {}


def _check_proxy(platform: str, body: dict) -> None:
    why = proxies.problem(body.get("proxy"), platform)
    if why:
        raise HTTPException(status_code=400, detail=why)


async def _proxy_for_signin(platform: str, request: Request) -> str:
    try:
        body = await request.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    _check_proxy(platform, body)
    proxy = str(body.get("proxy") or "").strip()
    _signin_proxy[platform] = proxy
    return proxy


def _keep_signin_proxy(platform: str, index: int, slots: list) -> list:
    """The account a sign-in just stored gets the proxy that sign-in went through."""
    proxy = _signin_proxy.pop(platform, "")
    if not proxy:
        return slots
    values = _migrate_legacy(read_env())
    values[_key(PLATFORMS[platform]["fields"]["proxy"], index)] = proxy
    write_env(values)
    reload_into_process(values)
    return _slots(values)


def _platform(name: str) -> dict:
    spec = PLATFORMS.get(name)
    if not spec:
        raise HTTPException(status_code=404, detail=f"unknown platform: {name}")
    return spec


def _key(prefix: str, index: int) -> str:
    return f"{prefix}_{index}"


def _migrate_legacy(values: dict) -> dict:
    """Fold the old unsuffixed keys (DISCORD_TOKEN) into slot 1. Both spellings are read by the counters, so leaving the bare key in place alongside a numbered one would make a single account look like two."""
    for spec in PLATFORMS.values():
        for prefix in spec["fields"].values():
            bare = values.pop(prefix, None)
            if bare and not values.get(_key(prefix, 1)):
                values[_key(prefix, 1)] = bare
    return values


def _count(values: dict, platform: str) -> int:
    """How many accounts there are, counted the way the workers count them. A fresh install's .env is the template, whose values look filled in: DISCORD_TOKEN_1=TOKEN_GOES_HERE, SNAP_USERNAME_1=your_snapchat_username. Counting any non-empty value listed those as two accounts that could never start, the runtime (core.ipc) rightly ignores placeholders, so a new user saw two dead cards instead of the page for adding their first account. Adding one now takes slot 1 over from the placeholder, as it should."""
    prefix = PLATFORMS[platform]["fields"][PLATFORMS[platform]["required"]]
    n = 0
    while not is_placeholder(values.get(_key(prefix, n + 1), "")):
        n += 1
    return n


def _slots(values: dict) -> list:
    # A social switched off in Settings is shown nowhere, its accounts included (app/utils/socials.py).
    from app.utils import socials
    on = socials.on()
    out = []
    for platform, spec in PLATFORMS.items():
        if not on.get(platform, True):
            continue
        for i in range(1, _count(values, platform) + 1):
            row = {"id": f"{platform}_{i}", "platform": platform, "index": i}
            for field, prefix in spec["fields"].items():
                val = values.get(_key(prefix, i), "").strip()
                # A template value is as good as none: "password set" for your_snapchat_password would promise a login that fails.
                if is_placeholder(val):
                    val = ""
                if field in spec["secret"]:
                    # Never leaves the server, not even masked.
                    row[f"{field}_set"] = bool(val)
                else:
                    row[field] = val
            out.append(row)
    return out


@router.get("/api/accounts/slots")
async def list_slots(request: Request):
    return {"slots": _slots(_migrate_legacy(read_env())), "platforms": list(PLATFORMS)}


def _store_discord(values: dict, token: str, proxy: str = "") -> tuple[int, list]:
    """Write a Discord token (and optional proxy) as the next account slot. Shared by the paste-a-token path and the log-in path, so a token obtained either way lands in exactly the same place, config/.env, and is used the same way. The token never travels back to the browser."""
    index = _count(values, "discord") + 1
    values[_key("DISCORD_TOKEN", index)] = token.strip()
    values[_key("DISCORD_PROXY", index)] = (proxy or "").strip()
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


@router.post("/api/accounts/discord/browser-login/start")
async def discord_browser_login_start(request: Request):
    """Open a browser at discord.com/login and wait for the person to sign in. Nothing is returned but the state: the token is read from the browser session and written to config/.env by the status route, and never reaches the page. This is the path that copes with a captcha, a new-device email check or a passkey, because a person is answering them rather than a script."""
    from app.utils import discord_browser_login
    body = await request.json()
    proxy = str(body.get("proxy", "")).strip()
    state = await asyncio.to_thread(discord_browser_login.start, proxy or None)
    return state


@router.get("/api/accounts/discord/browser-login/status")
async def discord_browser_login_status(request: Request):
    """Where that sign-in has got to. When it has finished, the token is taken out of the helper here and stored, so the slot exists by the time the page sees "done"."""
    from app.utils import discord_browser_login
    state = discord_browser_login.status()
    if state.get("state") == "done":
        token = discord_browser_login.take_token()
        if token:
            proxy = str(request.query_params.get("proxy", "")).strip()
            index, slots = _store_discord(_migrate_legacy(read_env()), token, proxy)
            return {**state, "index": index, "slots": slots}
    return state


@router.post("/api/accounts/discord/browser-login/cancel")
async def discord_browser_login_cancel(request: Request):
    """Close the browser and forget the attempt."""
    from app.utils import discord_browser_login
    return await asyncio.to_thread(discord_browser_login.cancel)


def _store_tiktok(values: dict, username: str) -> tuple[int, list]:
    """A TikTok account signed in, stored as the next slot by its @handle. Its profile was opened under that handle,
    which is where the runner looks for it."""
    from app.utils.tiktok_browser_login import clean_handle
    handle = clean_handle(username)
    if not handle:
        raise HTTPException(status_code=400, detail="That is not a TikTok username.")
    # Signed in again as an account already here: the same slot, not a second one.
    for i in range(1, _count(values, "tiktok") + 1):
        if values.get(_key("TIKTOK_USERNAME", i), "").strip().lstrip("@").lower() == handle.lower():
            return i, _slots(values)
    index = _count(values, "tiktok") + 1
    values[_key("TIKTOK_USERNAME", index)] = handle
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


@router.post("/api/accounts/tiktok/browser-login/start")
async def tiktok_browser_login_start(request: Request):
    """Open a browser at tiktok.com/login and wait for the person to sign in, any way TikTok offers (the QR code from
    the phone, a password, Google), answering whatever check it asks for themselves. The session stays in that
    account's own browser profile, which the account then runs in."""
    from app.utils import tiktok_browser_login
    proxy = await _proxy_for_signin("tiktok", request)
    return await asyncio.to_thread(tiktok_browser_login.start, proxy=proxy)


@router.get("/api/accounts/tiktok/browser-login/status")
async def tiktok_browser_login_status(request: Request):
    """Where that sign-in has got to. Once it is done the account is stored here, so the slot exists by the time
    the page sees "done"."""
    from app.utils import tiktok_browser_login
    state = tiktok_browser_login.status()
    if state.get("state") == "done":
        handle = tiktok_browser_login.take_handle()
        if handle:
            index, slots = _store_tiktok(_migrate_legacy(read_env()), handle)
            return {**state, "index": index, "slots": _keep_signin_proxy("tiktok", index, slots)}
    return state


@router.post("/api/accounts/tiktok/browser-login/cancel")
async def tiktok_browser_login_cancel(request: Request):
    """Close the browser and forget the attempt."""
    from app.utils import tiktok_browser_login
    return await asyncio.to_thread(tiktok_browser_login.cancel)


def _store_reddit(values: dict, username: str) -> tuple[int, list]:
    """A Reddit account signed in, stored as the next slot by its username. Its profile was opened under that
    username, which is where the runner looks for it. Signing in again as an account already here keeps its slot,
    and keeps whatever password was saved for it."""
    from app.utils.reddit_signin import clean_username
    name = clean_username(username)
    if not name:
        raise HTTPException(status_code=400, detail="That is not a Reddit username.")
    for i in range(1, _count(values, "reddit") + 1):
        if clean_username(values.get(_key("REDDIT_USERNAME", i), "")) == name:
            return i, _slots(values)
    index = _count(values, "reddit") + 1
    values[_key("REDDIT_USERNAME", index)] = name
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


@router.post("/api/accounts/reddit/browser-login/start")
async def reddit_browser_login_start(request: Request):
    """Open a browser at reddit.com/login and wait for the person to sign in, any way Reddit offers, answering
    whatever check it asks for themselves. The session stays in that account's own browser profile, which the
    account then runs in."""
    from app.utils import reddit_signin
    proxy = await _proxy_for_signin("reddit", request)
    return await asyncio.to_thread(reddit_signin.start, proxy=proxy)


@router.get("/api/accounts/reddit/browser-login/status")
async def reddit_browser_login_status(request: Request):
    """Where that sign-in has got to. Once it is done the account is stored here, so the slot exists by the time
    the page sees "done"."""
    from app.utils import reddit_signin
    state = reddit_signin.status()
    if state.get("state") == "done":
        name = reddit_signin.take_handle()
        if name:
            index, slots = _store_reddit(_migrate_legacy(read_env()), name)
            return {**state, "index": index, "slots": _keep_signin_proxy("reddit", index, slots)}
    return state


@router.post("/api/accounts/reddit/browser-login/cancel")
async def reddit_browser_login_cancel(request: Request):
    """Close the browser and forget the attempt."""
    from app.utils import reddit_signin
    return await asyncio.to_thread(reddit_signin.cancel)


def _store_whatsapp(values: dict, number: str) -> tuple[int, list]:
    """A WhatsApp number that just linked, stored as the next slot. Its keys were filed under that number, which
    is where the runner looks for them. Linking the same number again takes its own slot, not a second."""
    from app.platforms.whatsapp.link import clean_number
    num = clean_number(number)
    if not num:
        raise HTTPException(status_code=400, detail="That is not a phone number.")
    for i in range(1, _count(values, "whatsapp") + 1):
        if clean_number(values.get(_key("WHATSAPP_NUMBER", i), "")) == num:
            return i, _slots(values)
    index = _count(values, "whatsapp") + 1
    if index > MAX_SLOTS:
        raise HTTPException(status_code=400, detail="too many accounts")
    values[_key("WHATSAPP_NUMBER", index)] = num
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


@router.post("/api/accounts/whatsapp/link/start")
async def whatsapp_link_start(request: Request):
    """Ask WhatsApp to link this app as a device: an eight-character code for a number, or a QR code to scan.
    Nothing opens on this machine - the phone does the work."""
    from app.platforms.whatsapp import link
    body = await request.json()
    way = "qr" if str(body.get("way") or "").lower() == "qr" else "code"
    number = str(body.get("number") or body.get("username") or "")
    _check_proxy("whatsapp", body)
    proxy = str(body.get("proxy") or "").strip()
    _signin_proxy["whatsapp"] = proxy
    return await asyncio.to_thread(link.start, number, way, proxy=proxy)


@router.get("/api/accounts/whatsapp/link/status")
async def whatsapp_link_status(request: Request):
    """Where that link has got to: the code or the QR to show, or the number it finished as. Once it is linked
    the account is stored here, so the slot exists by the time the page sees it."""
    from app.platforms.whatsapp import link
    state = link.status()
    if state.get("qr"):
        # Dark modules on a transparent ground, drawn over a white plate in the page: an inverted code is what a
        # lot of phone scanners quietly refuse to read.
        try:
            import io as _io

            import segno
            buf = _io.BytesIO()
            segno.make(state["qr"], error="m").save(
                buf, kind="svg", scale=1, border=2, dark="#101018", light=None,
                svgclass=None, lineclass=None, omitsize=True, xmldecl=False, svgns=True)
            state = {**state, "qr_svg": buf.getvalue().decode("utf-8")}
        except Exception:
            state = {**state, "qr_svg": ""}
    if state.get("state") == "linked":
        done = link.take_login()
        if done:
            index, slots = _store_whatsapp(_migrate_legacy(read_env()), done["number"])
            return {**state, "index": index, "slots": _keep_signin_proxy("whatsapp", index, slots), "name": done.get("name", "")}
    return state


@router.post("/api/accounts/whatsapp/link/cancel")
async def whatsapp_link_cancel(request: Request):
    """Stop waiting, and forget the half-finished keys."""
    from app.platforms.whatsapp import link
    return await asyncio.to_thread(link.cancel)


@router.post("/api/accounts/reddit/sign-in/code")
async def reddit_sign_in_code(request: Request):
    """The code Reddit sent to the account, typed in the panel and handed to the running account's own runner.
    Nothing in the panel waits for one: a sign-in window is answered in the window."""
    body = await request.json()
    code = "".join(ch for ch in str(body.get("code") or "") if ch.isdigit())[:12]
    if not code:
        raise HTTPException(status_code=400, detail="That is not a code.")
    index = int(body.get("index") or 0)
    if not index:
        raise HTTPException(status_code=400, detail="Nothing is waiting for a code.")
    from app.core import ipc
    r = await ipc.send_and_wait(ipc.browser_target("reddit", index), "reddit_code", {"code": code}, timeout=25.0)
    return r or {"ok": False, "reason": "That account did not answer."}


def _instagram_body(body: dict) -> None:
    """An Instagram username and 2FA key in a body, as Instagram and RFC 6238 allow them, or a 400. The username
    names the account's browser profile, so it is checked before it names a folder."""
    if "username" in body and str(body.get("username") or "").strip():
        from app.utils.instagram_signin import clean_username
        name = clean_username(body["username"])
        if not name:
            raise HTTPException(status_code=400, detail="That is not an Instagram username.")
        body["username"] = name
    if "totp" in body and str(body.get("totp") or "").strip():
        from app.utils.instagram_signin import clean_totp
        key = clean_totp(body["totp"])
        if not key:
            raise HTTPException(status_code=400,
                                detail="That is not a 2FA key. It is the letters and digits Instagram shows beside "
                                       "the QR code, like G54M E4E3 T37W 6IXH.")
        body["totp"] = key


def _x_body(body: dict) -> None:
    """An X handle and 2FA key in a body, as X and RFC 6238 allow them, or a 400. The handle names the account's
    browser profile, so it is checked before it names a folder."""
    if "username" in body and str(body.get("username") or "").strip():
        from app.utils.x_signin import clean_handle
        name = clean_handle(body["username"])
        if not name:
            raise HTTPException(status_code=400,
                                detail="That is not an X handle. It is the @name, letters, digits and underscores, "
                                       "fifteen at most.")
        body["username"] = name
    if "totp" in body and str(body.get("totp") or "").strip():
        from app.utils.instagram_signin import clean_totp
        key = clean_totp(body["totp"])
        if not key:
            raise HTTPException(status_code=400,
                                detail="That is not a 2FA key. It is the letters and digits X shows beside the QR "
                                       "code, like G54M E4E3 T37W 6IXH.")
        body["totp"] = key


def _whatsapp_body(body: dict) -> None:
    """A phone number in a body, as WhatsApp's own ids carry it (digits, country code included), or a 400. It
    names the folder its keys live in, so it is checked before it names one."""
    if "username" in body and str(body.get("username") or "").strip():
        from app.platforms.whatsapp.link import clean_number
        number = clean_number(body["username"])
        if not number:
            raise HTTPException(status_code=400,
                                detail="That is not a phone number. It needs its country code and no symbols.")
        body["username"] = number


def _reddit_body(body: dict) -> None:
    """A Reddit username and 2FA key in a body, as Reddit and RFC 6238 allow them, or a 400. The username names the
    account's browser profile, so it is checked before it names a folder."""
    if "username" in body and str(body.get("username") or "").strip():
        from app.utils.reddit_signin import clean_username
        name = clean_username(body["username"])
        if not name:
            raise HTTPException(status_code=400,
                                detail="That is not a Reddit username. It is the u/ name, letters, digits, "
                                       "underscores and hyphens, three to twenty.")
        body["username"] = name
    if "totp" in body and str(body.get("totp") or "").strip():
        from app.utils.reddit_signin import clean_totp
        key = clean_totp(body["totp"])
        if not key:
            raise HTTPException(status_code=400,
                                detail="That is not a 2FA key. It is the letters and digits Reddit shows beside the "
                                       "QR code, like G54M E4E3 T37W 6IXH.")
        body["totp"] = key


_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def _minecraft_body(body: dict) -> None:
    """A Minecraft name, server and sign-in in a body, as Minecraft allows them, or a 400. A server may come as one
    "host:port", the way addresses are passed around; it is split here."""
    if "username" in body and str(body.get("username") or "").strip():
        from app.platforms.minecraft.profile import clean_name
        raw = str(body["username"]).strip()
        name = clean_name(raw)
        if not name or name != raw:
            raise HTTPException(status_code=400,
                                detail="A Minecraft name is 3 to 16 letters, digits or underscores.")
        body["username"] = name
    host = str(body.get("host") or "").strip()
    if host:
        host = re.sub(r"^[a-z]+://", "", host, flags=re.I).rstrip("/")
        if ":" in host and host.count(":") == 1:
            host, _, port = host.partition(":")
            if port and not str(body.get("port") or "").strip():
                body["port"] = port
        if not _HOST_RE.match(host):
            raise HTTPException(status_code=400, detail="That is not a server address. It looks like play.example.net"
                                                        " or 192.168.1.20.")
        body["host"] = host
    port = str(body.get("port") or "").strip()
    if port:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise HTTPException(status_code=400, detail="A port is a number from 1 to 65535.")
        body["port"] = str(int(port))
    if "auth" in body:
        auth = str(body.get("auth") or "offline").strip().lower()
        if auth not in ("offline", "microsoft"):
            raise HTTPException(status_code=400, detail="It signs in either offline or with a Microsoft account.")
        body["auth"] = auth


def _telegram_body(body: dict) -> None:
    """Nothing is added by hand: a Telegram account exists once Telegram has let it in."""
    raise HTTPException(status_code=400, detail="A Telegram account is added by signing in, not by typing its "
                                                "details. Use Sign in on the Accounts page.")


def _store_telegram(values: dict, done: dict) -> tuple[int, list]:
    """An account that just signed in, as the next slot. Signing the same one in again takes its own slot back
    rather than making a second."""
    phone = str(done.get("phone") or "")
    index = 0
    for i in range(1, _count(values, "telegram") + 1):
        if values.get(_key("TELEGRAM_PHONE", i), "").strip() == phone:
            index = i
            break
    if not index:
        index = _count(values, "telegram") + 1
        if index > MAX_SLOTS:
            raise HTTPException(status_code=400, detail="too many accounts")
    values[_key("TELEGRAM_SESSION", index)] = str(done.get("session") or "")
    values[_key("TELEGRAM_API_ID", index)] = str(done.get("api_id") or "")
    values[_key("TELEGRAM_API_HASH", index)] = str(done.get("api_hash") or "")
    values[_key("TELEGRAM_PHONE", index)] = phone
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


@router.post("/api/accounts/telegram/sign-in/start")
async def telegram_sign_in_start(request: Request):
    """Ask Telegram for a code. api_id and api_hash come from my.telegram.org; the number is the account's own.
    Signing an account in again (its session pulled from Telegram's Devices list) reuses what is stored."""
    from app.platforms.telegram import signin
    body = await request.json()
    index = int(body.get("index") or 0)
    values = _migrate_legacy(read_env())
    if index:
        if not 1 <= index <= _count(values, "telegram"):
            raise HTTPException(status_code=404, detail="no such account")
        api_id = body.get("api_id") or values.get(_key("TELEGRAM_API_ID", index), "")
        api_hash = body.get("api_hash") or values.get(_key("TELEGRAM_API_HASH", index), "")
        phone = body.get("phone") or values.get(_key("TELEGRAM_PHONE", index), "")
    else:
        api_id, api_hash, phone = body.get("api_id"), body.get("api_hash"), body.get("phone")
        # The pair is the same for every account on one app, so the first account's stands in for either half that
        # was left blank - typing the id and not the hash, which is the one that is never shown back, is the usual way.
        if _count(values, "telegram"):
            api_id = api_id or values.get(_key("TELEGRAM_API_ID", 1), "")
            api_hash = api_hash or values.get(_key("TELEGRAM_API_HASH", 1), "")
    _check_proxy("telegram", body)
    proxy = str(body.get("proxy") or "").strip()
    _signin_proxy["telegram"] = proxy
    return await signin.start(api_id, api_hash, phone, index, proxy)


@router.get("/api/accounts/telegram/sign-in/status")
async def telegram_sign_in_status(request: Request):
    """Where that sign-in has got to. Once Telegram has let it in the account is stored here, so the slot exists by
    the time the page sees "done". The session string stops here and never goes back to the page."""
    from app.platforms.telegram import signin
    state = signin.status()
    if state.get("state") == "done":
        done = signin.take_login()
        if done:
            index, slots = _store_telegram(_migrate_legacy(read_env()), done)
            return {**{k: v for k, v in state.items()}, "index": index, "slots": _keep_signin_proxy("telegram", index, slots),
                    "name": done.get("name", ""), "username": done.get("username", "")}
    return state


@router.post("/api/accounts/telegram/sign-in/code")
async def telegram_sign_in_code(request: Request):
    """The code Telegram sent, typed in the panel."""
    from app.platforms.telegram import signin
    body = await request.json()
    return await signin.give_code(str(body.get("code") or ""))


@router.post("/api/accounts/telegram/sign-in/password")
async def telegram_sign_in_password(request: Request):
    """Its two-step verification password, for an account that has one. Never stored."""
    from app.platforms.telegram import signin
    body = await request.json()
    return await signin.give_password(str(body.get("password") or ""))


@router.post("/api/accounts/telegram/sign-in/cancel")
async def telegram_sign_in_cancel(request: Request):
    from app.platforms.telegram import signin
    return await signin.cancel()


def _imessage_body(body: dict) -> None:
    """A BlueBubbles address in a body, as people paste one ("192.168.1.20:1234", its Cloudflare or ngrok address),
    made the same one its runner reads, or a 400. "phone" is no address: the iPhone carries the messages, and gets a
    relay secret of its own (never one sent in)."""
    body.pop("relay", None)
    if str(body.get("server") or "").strip().lower() == "phone":
        import secrets
        body["server"] = "phone"
        body["password"] = ""
        body["relay"] = secrets.token_urlsafe(24)
        return
    if "server" in body and str(body.get("server") or "").strip():
        from app.utils.bluebubbles import server_url
        url = server_url(body["server"])
        if not url:
            raise HTTPException(status_code=400, detail="That is not a BlueBubbles address. It looks like "
                                                        "https://xyz.trycloudflare.com or 192.168.1.20:1234.")
        body["server"] = url


@router.post("/api/accounts/imessage/connection/test")
async def imessage_test(request: Request):
    """Whether a BlueBubbles server answers at that address with that password, and what it says of the Mac: the Add
    account dialog's Test, before the account is added. Editing one, a password left empty is the one saved."""
    from app.utils import bluebubbles
    body = await request.json()
    password = str(body.get("password") or "")
    index = body.get("index")
    if not password and str(index or "").isdigit():
        password = read_env().get(_key("IMESSAGE_PASSWORD", int(index)), "")
    return await bluebubbles.check(str(body.get("server") or ""), password)


def _minecraft_name_free(values: dict, name: str, except_index: int = 0) -> None:
    """One slot per name: two would share one Microsoft sign-in (mindcraft keeps it keyed by the name), and play as
    the same player besides."""
    n = 1
    while values.get(f"MINECRAFT_USERNAME_{n}"):
        if n != except_index and values[f"MINECRAFT_USERNAME_{n}"].strip().lower() == name.lower():
            raise HTTPException(status_code=400, detail=f"{name} is already Minecraft account #{n}.")
        n += 1


# ── Minecraft with a Microsoft account: signed in, not typed in ─────────────
# The server it is for rides along with the sign-in, so the account is added whole once Microsoft has let it in.
_MC_PENDING: dict = {}


def _store_minecraft_microsoft(got: dict, pending: dict) -> tuple[int, list]:
    """A Microsoft account that just signed in, stored under the name Microsoft gave: the name the bot plays as and
    finds its saved login by. Signing an account in again takes its own slot back rather than making a second."""
    values = _migrate_legacy(read_env())
    name = got["name"]
    index = int(pending.get("index") or 0)
    if not index:
        n = 1
        while values.get(f"MINECRAFT_USERNAME_{n}"):
            if values[f"MINECRAFT_USERNAME_{n}"].strip().lower() == name.lower():
                index = n
                break
            n += 1
    if index:
        _minecraft_name_free(values, name, except_index=index)
    else:
        _minecraft_name_free(values, name)
        index = _count(values, "minecraft") + 1
        if index > MAX_SLOTS:
            raise HTTPException(status_code=400, detail="too many accounts")
    values[_key("MINECRAFT_USERNAME", index)] = name
    values[_key("MINECRAFT_AUTH", index)] = "microsoft"
    if pending.get("host"):
        values[_key("MINECRAFT_HOST", index)] = str(pending["host"])
        values[_key("MINECRAFT_PORT", index)] = str(pending.get("port") or "")
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


@router.post("/api/accounts/minecraft/sign-in/start")
async def minecraft_sign_in_start(request: Request):
    """Microsoft's code for a Minecraft account. The server it will play on is checked now, before anyone goes off to
    sign in, and kept until it has. With an index, an account already here signs in again."""
    from app.platforms.minecraft import ms_signin
    try:
        body = await request.json()
    except Exception:
        body = {}
    probe = {"host": str(body.get("host") or "").strip(), "port": str(body.get("port") or "").strip()}
    if probe["host"]:
        _minecraft_body(probe)
    _MC_PENDING.clear()
    _MC_PENDING.update(host=probe.get("host", ""), port=probe.get("port", ""), index=int(body.get("index") or 0))
    return await asyncio.to_thread(ms_signin.start)


@router.get("/api/accounts/minecraft/sign-in/status")
async def minecraft_sign_in_status(request: Request):
    """Where the sign-in has got to. Once Microsoft has let it in, the account is stored here, under its real name,
    so it exists by the time the panel hears it is done."""
    from app.platforms.minecraft import ms_signin
    s = ms_signin.status()
    if s.get("state") == "done":
        got = ms_signin.take_result()
        if got:
            index, slots = await asyncio.to_thread(_store_minecraft_microsoft, got, dict(_MC_PENDING))
            _MC_PENDING.clear()
            return {**s, "name": got["name"], "index": index, "slots": slots}
    return s


@router.post("/api/accounts/minecraft/sign-in/cancel")
async def minecraft_sign_in_cancel(request: Request):
    from app.platforms.minecraft import ms_signin
    _MC_PENDING.clear()
    return await asyncio.to_thread(ms_signin.cancel)


# ── A premium account's skin ─────────────────────────────────────────────────
# Minecraft keeps it, so it is changed with the account's own Microsoft login (app/platforms/minecraft/skin_change).

def _minecraft_slot_values(index: int) -> dict:
    values = _migrate_legacy(read_env())
    if not 1 <= index <= _count(values, "minecraft"):
        raise HTTPException(status_code=404, detail="no such account")
    return values


def _minecraft_premium(index: int) -> str:
    """The Minecraft name of a Microsoft account here, which its login is kept under. Any other is refused."""
    values = _minecraft_slot_values(index)
    if values.get(_key("MINECRAFT_AUTH", index), "").strip().lower() != "microsoft":
        raise HTTPException(status_code=400, detail="Only a Microsoft account has a skin of its own to change.")
    name = values.get(_key("MINECRAFT_USERNAME", index), "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="This account has no Minecraft name yet.")
    return name


@router.get("/api/accounts/minecraft/{index}/skin")
async def minecraft_skin(index: int):
    """What its card knows of its skin: classic or slim, and its picture standing up."""
    from app.platforms.minecraft import skin_change
    values = _minecraft_slot_values(index)
    premium = values.get(_key("MINECRAFT_AUTH", index), "").strip().lower() == "microsoft"
    return {"ok": True, "premium": premium, **await asyncio.to_thread(skin_change.current, index)}


@router.post("/api/accounts/minecraft/{index}/skin")
async def minecraft_skin_change(index: int, file: UploadFile | None = File(None), variant: str = Form("classic")):
    """A picture put on it as its skin (a 64 by 64 PNG), with classic or slim arms. With no picture, the skin it has
    goes back on with the arms asked for: Minecraft only changes the arms with a skin."""
    from app.platforms.minecraft import skin_change
    name = _minecraft_premium(index)
    if file is None:
        # The skin it has, as Minecraft has it on this account (never one looked up by name: the name it was added
        # under need not be the one it plays as), back on with these arms.
        return await asyncio.to_thread(skin_change.change, index, name, None, variant == "slim", keep=True)
    png = await file.read(skin_change.MAX_BYTES + 1)
    why = skin_change.check_png(png)
    if why:
        raise HTTPException(status_code=400, detail=why)
    return await asyncio.to_thread(skin_change.change, index, name, png, variant == "slim")


@router.delete("/api/accounts/minecraft/{index}/skin")
async def minecraft_skin_reset(index: int):
    """Its skin taken off: it wears the game's default for it again."""
    from app.platforms.minecraft import skin_change
    name = _minecraft_premium(index)
    return await asyncio.to_thread(skin_change.change, index, name, None)


@router.post("/api/accounts/instagram/sign-in/start")
async def instagram_sign_in_start(request: Request):
    """Open a browser at instagram.com's own login page and wait for the person to sign in, any way Instagram
    offers, answering whatever check it asks for themselves. The session stays in that account's own browser
    profile, which the account then runs in. Nothing is typed by the app: a scripted login is what Instagram acts
    on, and the account it acted on here was suspended for it."""
    from app.utils import instagram_signin
    proxy = await _proxy_for_signin("instagram", request)
    return await asyncio.to_thread(instagram_signin.start, proxy=proxy)


@router.get("/api/accounts/instagram/sign-in/status")
async def instagram_sign_in_status(request: Request):
    """Where that sign-in has got to. Once Instagram has let it in, a new account is stored here, so the slot exists
    by the time the page sees "done"."""
    from app.utils import instagram_signin
    state = instagram_signin.status()
    if state.get("state") == "done":
        username = instagram_signin.take_handle()
        if username:
            index, slots = _store_instagram(_migrate_legacy(read_env()), {"username": username})
            return {**state, "index": index, "slots": _keep_signin_proxy("instagram", index, slots)}
    return state


@router.post("/api/accounts/instagram/sign-in/code")
async def instagram_sign_in_code(request: Request):
    """The code Instagram sent to the account's email or phone, typed in the panel, handed to whoever is waiting for
    it: the sign-in window, or a running account's own runner."""
    from app.utils import instagram_signin
    body = await request.json()
    code = "".join(ch for ch in str(body.get("code") or "") if ch.isdigit())[:12]
    if not code:
        raise HTTPException(status_code=400, detail="That is not a code.")
    index = int(body.get("index") or 0)
    if instagram_signin.running():
        return await asyncio.to_thread(instagram_signin.give_code, code)
    # No sign-in window open: the account is running and asked for one, so its runner is told.
    if not index:
        raise HTTPException(status_code=400, detail="Nothing is waiting for a code.")
    from app.core import ipc
    r = await ipc.send_and_wait(ipc.browser_target("instagram", index), "insta_code", {"code": code}, timeout=25.0)
    return r or {"ok": False, "reason": "That account did not answer."}


@router.post("/api/accounts/instagram/sign-in/cancel")
async def instagram_sign_in_cancel(request: Request):
    """Close the window and forget the attempt."""
    from app.utils import instagram_signin
    return await asyncio.to_thread(instagram_signin.cancel)


def _store_instagram(values: dict, done: dict) -> tuple[int, list]:
    """An Instagram account that just signed in, stored as the next slot: its username, and its password and 2FA key
    write-only beside it. Signing the same account in again takes its own slot, not a second one."""
    from app.utils.instagram_signin import clean_username
    username = clean_username(done.get("username"))
    if not username:
        raise HTTPException(status_code=400, detail="That is not an Instagram username.")
    index = 0
    for i in range(1, _count(values, "instagram") + 1):
        if values.get(_key("INSTAGRAM_USERNAME", i), "").strip().lower() == username:
            index = i
            break
    if not index:
        index = _count(values, "instagram") + 1
        if index > MAX_SLOTS:
            raise HTTPException(status_code=400, detail="too many accounts")
    values[_key("INSTAGRAM_USERNAME", index)] = username
    if done.get("password"):
        values[_key("INSTAGRAM_PASSWORD", index)] = str(done["password"])
    if done.get("totp"):
        values[_key("INSTAGRAM_TOTP", index)] = str(done["totp"])
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


@router.post("/api/accounts/x/sign-in/start")
async def x_sign_in_start(request: Request):
    """Open a browser at x.com's own login page and wait for the person to sign in, any way X offers, answering
    whatever check it asks for themselves. The session stays in that account's own browser profile, which the
    account then runs in. Nothing is typed by the app: a scripted login is what X locks an account over."""
    from app.utils import x_signin
    proxy = await _proxy_for_signin("x", request)
    return await asyncio.to_thread(x_signin.start, proxy=proxy)


@router.get("/api/accounts/x/sign-in/status")
async def x_sign_in_status(request: Request):
    """Where that sign-in has got to. Once X has let it in, a new account is stored here, so the slot exists by the
    time the page sees "done"."""
    from app.utils import x_signin
    state = x_signin.status()
    if state.get("state") == "done":
        handle = x_signin.take_handle()
        if handle:
            index, slots = _store_x(_migrate_legacy(read_env()), {"username": handle})
            return {**state, "index": index, "slots": _keep_signin_proxy("x", index, slots)}
    return state


@router.post("/api/accounts/x/sign-in/code")
async def x_sign_in_code(request: Request):
    """The code X sent to the account's email or phone, typed in the panel, handed to whoever is waiting for it:
    the sign-in window, or a running account's own runner."""
    from app.utils import x_signin
    body = await request.json()
    code = "".join(ch for ch in str(body.get("code") or "") if ch.isdigit())[:12]
    if not code:
        raise HTTPException(status_code=400, detail="That is not a code.")
    index = int(body.get("index") or 0)
    if x_signin.running():
        return await asyncio.to_thread(x_signin.give_code, code)
    # No sign-in window open: the account is running and asked for one, so its runner is told.
    if not index:
        raise HTTPException(status_code=400, detail="Nothing is waiting for a code.")
    from app.core import ipc
    r = await ipc.send_and_wait(ipc.browser_target("x", index), "x_code", {"code": code}, timeout=25.0)
    return r or {"ok": False, "reason": "That account did not answer."}


@router.post("/api/accounts/x/sign-in/cancel")
async def x_sign_in_cancel(request: Request):
    """Close the window and forget the attempt."""
    from app.utils import x_signin
    return await asyncio.to_thread(x_signin.cancel)


def _store_x(values: dict, done: dict) -> tuple[int, list]:
    """An X account that just signed in, stored as the next slot: its handle, its email, and its password and 2FA
    key write-only beside them. Signing the same account in again takes its own slot, not a second one."""
    from app.utils.x_signin import clean_handle
    handle = clean_handle(done.get("username"))
    if not handle:
        raise HTTPException(status_code=400, detail="That is not an X handle.")
    index = 0
    for i in range(1, _count(values, "x") + 1):
        if values.get(_key("X_USERNAME", i), "").strip().lower() == handle:
            index = i
            break
    if not index:
        index = _count(values, "x") + 1
        if index > MAX_SLOTS:
            raise HTTPException(status_code=400, detail="too many accounts")
    values[_key("X_USERNAME", index)] = handle
    if done.get("password"):
        values[_key("X_PASSWORD", index)] = str(done["password"])
    if done.get("totp"):
        values[_key("X_TOTP", index)] = str(done["totp"])
    if done.get("email"):
        values[_key("X_EMAIL", index)] = str(done["email"])
    write_env(values)
    reload_into_process(values)
    return index, _slots(values)


def _tiktok_username(body: dict) -> None:
    """A TikTok username in a body, as TikTok allows it (it names the account's browser profile), or a 400."""
    if "username" in body and str(body.get("username") or "").strip():
        from app.utils.tiktok_browser_login import clean_handle
        handle = clean_handle(body["username"])
        if not handle:
            raise HTTPException(status_code=400, detail="That is not a TikTok username.")
        body["username"] = handle


@router.post("/api/accounts/slots/{platform}")
async def add_slot(request: Request, platform: str):
    """Append a new account. The body carries its initial credentials."""
    spec = _platform(platform)
    body = await request.json()
    if platform == "tiktok":
        _tiktok_username(body)
    if platform == "instagram":
        _instagram_body(body)
    if platform == "x":
        _x_body(body)
    if platform == "reddit":
        _reddit_body(body)
    if platform == "whatsapp":
        _whatsapp_body(body)
    if platform == "minecraft":
        _minecraft_body(body)
    if platform == "imessage":
        _imessage_body(body)
    if platform == "telegram":
        _telegram_body(body)
    values = _migrate_legacy(read_env())

    _check_proxy(platform, body)
    required = spec["required"]
    if not str(body.get(required, "")).strip():
        raise HTTPException(status_code=400, detail=f"{required} is required")
    if platform == "minecraft":
        _minecraft_name_free(values, body["username"])
    index = _count(values, platform) + 1
    if index > MAX_SLOTS:
        raise HTTPException(status_code=400, detail="too many accounts")

    for field, prefix in spec["fields"].items():
        values[_key(prefix, index)] = str(body.get(field, "")).strip()

    write_env(values)
    reload_into_process(values)
    return {"ok": True, "index": index, "slots": _slots(values)}


@router.post("/api/accounts/slots/{platform}/{index}")
async def update_slot(request: Request, platform: str, index: int):
    """Replace fields on an existing account. A field that is absent, or sent as an empty string, is left untouched, which is what lets the UI edit the proxy without knowing the token."""
    spec = _platform(platform)
    body = await request.json()
    # Only what is being changed: one kept since before these were checked should not stop the rest of the form being saved.
    if str(body.get("proxy") or "").strip() != read_env().get(_key(spec["fields"].get("proxy", ""), index), "").strip():
        _check_proxy(platform, body)
    if platform == "tiktok":
        _tiktok_username(body)
    if platform == "instagram":
        _instagram_body(body)
    if platform == "x":
        _x_body(body)
    if platform == "reddit":
        _reddit_body(body)
    if platform == "whatsapp":
        _whatsapp_body(body)
    if platform == "minecraft":
        _minecraft_body(body)
    if platform == "imessage":
        renew = bool(body.pop("renew_relay", False))
        was_phone = (read_env().get(_key("IMESSAGE_SERVER", index), "") or "").strip().lower() == "phone"
        _imessage_body(body)
        if was_phone and body.get("server") == "phone" and not renew:
            body.pop("relay", None)
    values = _migrate_legacy(read_env())

    if not 1 <= index <= _count(values, platform):
        raise HTTPException(status_code=404, detail="no such account")
    if platform == "minecraft" and str(body.get("username") or "").strip():
        _minecraft_name_free(values, body["username"], except_index=index)

    # A TikTok handle names the browser profile its session lives in, so a new one takes the profile with it - with
    # the account stopped while it moves, and started again after if it was running.
    restart_after = ""
    if platform == "reddit" and str(body.get("username") or "").strip():
        from app.utils.reddit_signin import clean_username
        old_name = values.get(_key("REDDIT_USERNAME", index), "")
        if clean_username(old_name) and clean_username(old_name) != body["username"]:
            supervisor = getattr(request.app.state, "supervisor", None)
            child_id = f"reddit_{index}"
            if supervisor is not None:
                if child_id in supervisor.running_ids():
                    restart_after = child_id
                await asyncio.to_thread(supervisor.stop, child_id)
            why = await asyncio.to_thread(_move_reddit_profile, old_name, body["username"])
            if why:
                if restart_after and supervisor is not None:
                    await asyncio.to_thread(supervisor.start, restart_after)
                raise HTTPException(status_code=409, detail=why)
    if platform == "tiktok" and str(body.get("username") or "").strip():
        from app.utils.tiktok_browser_login import clean_handle
        old_handle = values.get(_key("TIKTOK_USERNAME", index), "")
        if clean_handle(old_handle) and clean_handle(old_handle) != body["username"]:
            supervisor = getattr(request.app.state, "supervisor", None)
            child_id = f"tiktok_{index}"
            if supervisor is not None:
                if child_id in supervisor.running_ids():
                    restart_after = child_id
                await asyncio.to_thread(supervisor.stop, child_id)
            why = await asyncio.to_thread(_move_tiktok_profile, old_handle, body["username"])
            if why:
                if restart_after and supervisor is not None:
                    await asyncio.to_thread(supervisor.start, restart_after)
                raise HTTPException(status_code=409, detail=why)

    for field, prefix in spec["fields"].items():
        if field not in body:
            continue
        new = str(body[field] or "").strip()
        if not new:
            # Clearing the required field would orphan the slot; use DELETE.
            if field == spec["required"] or field in spec["secret"]:
                continue
            values[_key(prefix, index)] = ""
        else:
            values[_key(prefix, index)] = new

    write_env(values)
    reload_into_process(values)
    supervisor = getattr(request.app.state, "supervisor", None)
    if restart_after and supervisor is not None:
        # Back up under its new name, in the profile that moved with it: still signed in.
        await asyncio.to_thread(supervisor.start, restart_after)
    return {"ok": True, "slots": _slots(values)}


def _renumber_account_data(platform: str, index: int, total: int) -> None:
    """Move what is stored per account number along with the renumbering. The reply log and each Discord account's saved name and picture are kept by number; after slot `index` goes and the later ones move up, those would otherwise describe the wrong account until each one reconnected."""
    try:
        from app.utils.db import renumber_account_replies
        renumber_account_replies(platform, index)
    except Exception:
        pass
    # Which persona each account is, and the accounts a persona lets the AI add touches on (everyone's list too).
    try:
        from app.utils import configstore, personas
        from app.utils.helpers import load_base_config
        personas.renumber(platform, index)
        # Only with a config file to change: with none, reading it ends the process (SystemExit gets past except).
        if configstore.config_path().is_file():
            touches = configstore.get_nested(load_base_config() or {}, "bot.pictures.touches.accounts")
            if isinstance(touches, list) and touches:
                moved = personas.renumber_ids(touches, platform, index)
                if moved != touches:
                    configstore.set_value("bot.pictures.touches.accounts", moved)
    except Exception:
        pass
    from app.utils.paths import DATA_DIR
    cfg = DATA_DIR / "config"
    if platform == "snapchat":
        _renumber_snap_identity(cfg, index, total)
        return
    if platform == "tiktok":
        _renumber_web_identity(cfg, "identity_tiktok", index, total)
        return
    if platform == "instagram":
        _renumber_web_identity(cfg, "identity_instagram", index, total)
        return
    if platform == "x":
        _renumber_web_identity(cfg, "identity_x", index, total)
        return
    if platform == "reddit":
        _renumber_web_identity(cfg, "identity_reddit", index, total)
        return
    if platform == "whatsapp":
        _renumber_web_identity(cfg, "identity_whatsapp", index, total)
        return
    if platform == "imessage":
        _renumber_web_identity(cfg, "identity_imessage", index, total)
        return
    if platform != "discord":
        return
    try:
        (cfg / f"identity_{index}.json").unlink(missing_ok=True)
        for i in range(index + 1, total + 1):
            src = cfg / f"identity_{i}.json"
            if src.exists():
                src.replace(cfg / f"identity_{i - 1}.json")
    except OSError:
        pass


def _renumber_snap_identity(cfg, index: int, total: int) -> None:
    """A Snapchat account's name and pictures (identity_snap_N.json, its Bitmoji and background beside it) moved along with the renumbering, the file names inside the json with them."""
    _renumber_web_identity(cfg, "identity_snap", index, total)


def _renumber_web_identity(cfg, stem: str, index: int, total: int) -> None:
    """A browser account's name and pictures (<stem>_N.json and the pictures beside it, Snapchat's or TikTok's) moved
    along with the renumbering, the file names inside the json with them."""
    import json
    import re

    def own(n):
        # identity_snap_1* also matches identity_snap_10.json: only this number's own files.
        out = []
        for p in cfg.glob(f"{stem}_{n}*"):
            m = re.fullmatch(rf"{stem}_{n}((_bg)?\.(json|webp|png|jpg))", p.name)
            if m:
                out.append((p, m.group(1)))
        return out

    try:
        for p, _ in own(index):
            p.unlink(missing_ok=True)
        for i in range(index + 1, total + 1):
            for p, tail in own(i):
                p.replace(cfg / f"{stem}_{i - 1}{tail}")
            j = cfg / f"{stem}_{i - 1}.json"
            if j.exists():
                data = json.loads(j.read_text(encoding="utf-8"))
                for key in ("picture", "background"):
                    if data.get(key):
                        data[key] = re.sub(rf"^{stem}_{i}(?=[._])", f"{stem}_{i - 1}", str(data[key]))
                j.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass


def _drop_instagram_profile(username: str) -> None:
    """A removed Instagram account's browser profile goes too: it holds that account's signed-in session. Best
    effort, after its runner (and so its Chrome) has stopped."""
    import shutil
    from app.utils.instagram_signin import clean_username, profile_dir
    username = clean_username(username)
    if username:
        shutil.rmtree(profile_dir(username), ignore_errors=True)


def _drop_x_profile(handle: str) -> None:
    """A removed X account's browser profile goes too: it holds that account's signed-in session. Best effort,
    after its runner (and so its Chrome) has stopped."""
    import shutil
    from app.utils.x_signin import clean_handle, profile_dir
    handle = clean_handle(handle)
    if handle:
        shutil.rmtree(profile_dir(handle), ignore_errors=True)


def _move_reddit_profile(old: str, new: str) -> str:
    """A Reddit account's browser profile is named after its username (reddit_runner.js opens
    config/reddit-<name>-profile), and it is what holds the account's signed-in session - all of it, since nothing
    here needs a password. When the name changes, the profile goes with it; otherwise the account opens a fresh,
    signed-out one under the new name and has to be signed in by hand again.

    The account's runner has to be stopped first: Chrome holds the folder while it runs, and can outlive its runner
    by a few seconds, so the move is tried again for a little while. "" when it moved or there was nothing to move;
    otherwise what stopped it, and nothing has been changed."""
    import time
    from app.utils.reddit_signin import clean_username, profile_dir
    old, new = clean_username(old), clean_username(new)
    if not old or not new or old == new:
        return ""
    src, dst = profile_dir(old), profile_dir(new)
    if not src.exists():
        return ""   # never signed in under the old name: there is no session to carry
    if dst.exists():
        return f"There is already a Reddit profile for u/{new}, so neither was touched."
    for attempt in range(8):
        try:
            src.rename(dst)
            break
        except OSError as e:
            if attempt == 7:
                return f"Its browser profile is still in use ({e.__class__.__name__}); stop the account and try again."
            time.sleep(2)
    return ""


def _drop_reddit_profile(username: str) -> None:
    """A removed Reddit account's browser profile goes too: it holds that account's signed-in session, and on
    Reddit that is the whole of its login. Best effort, after its runner (and so its Chrome) has stopped."""
    from app.utils.reddit_signin import drop_profile
    drop_profile(username)


def _drop_whatsapp_keys(number: str) -> None:
    """A removed WhatsApp account's keys go too: they are the whole of its login, and WhatsApp still counts it as
    a linked device until the phone says otherwise. Best effort, after its runner has stopped."""
    import shutil
    from app.platforms.whatsapp.link import auth_dir, clean_number
    if clean_number(number):
        shutil.rmtree(auth_dir(number), ignore_errors=True)


def _move_tiktok_profile(old: str, new: str) -> str:
    """A TikTok account's browser profile is named after its handle (tiktok_runner.js opens
    config/tiktok-<handle>-profile), and it is what holds the account's signed-in session. When the handle changes -
    the account renamed on TikTok, say - the profile goes with it; otherwise the account opens a fresh, signed-out one
    under the new name and has to be signed in by hand all over again, which TikTok cannot do by script.

    The account's runner has to be stopped first: Chrome holds the folder while it runs, and can outlive its runner by
    a few seconds, so the move is tried again for a little while. "" when it moved or there was nothing to move;
    otherwise what stopped it, and nothing has been changed."""
    import time
    from app.utils.paths import DATA_DIR
    from app.utils.tiktok_browser_login import clean_handle, profile_dir
    old, new = clean_handle(old), clean_handle(new)
    if not old or not new or old == new:
        return ""
    src, dst = profile_dir(old), profile_dir(new)
    if not src.exists():
        return ""   # never signed in under the old name: there is no session to carry
    if dst.exists():
        return f"There is already a TikTok profile for @{new}, so neither was touched."
    for attempt in range(8):
        try:
            src.rename(dst)
            break
        except OSError as e:
            if attempt == 7:
                return f"Its browser profile is still in use ({e.__class__.__name__}); stop the account and try again."
            time.sleep(2)
    cookies = DATA_DIR / "config" / f"tiktok-{old}-cookies.json"
    if cookies.exists():
        try:
            cookies.rename(DATA_DIR / "config" / f"tiktok-{new}-cookies.json")
        except OSError:
            pass   # the profile is what carries the session; this file is only a copy of its cookies
    return ""


def _drop_tiktok_profile(handle: str) -> None:
    """A removed TikTok account's browser profile goes too: it holds that account's signed-in session, which nothing
    should keep once the account is gone. Best effort, after its runner (and so its Chrome) has stopped."""
    import shutil
    from app.utils.paths import DATA_DIR
    from app.utils.tiktok_browser_login import clean_handle, profile_dir
    handle = clean_handle(handle)
    if handle:
        shutil.rmtree(profile_dir(handle), ignore_errors=True)
        (DATA_DIR / "config" / f"tiktok-{handle}-cookies.json").unlink(missing_ok=True)


@router.delete("/api/accounts/slots/{platform}/{index}")
async def delete_slot(request: Request, platform: str, index: int):
    """Remove an account and close the gap so the numbering stays contiguous."""
    spec = _platform(platform)
    values = _migrate_legacy(read_env())
    total = _count(values, platform)
    if not 1 <= index <= total:
        raise HTTPException(status_code=404, detail="no such account")

    gone_handle = values.get(_key("TIKTOK_USERNAME", index), "").strip().lstrip("@") if platform == "tiktok" else ""
    gone_insta = values.get(_key("INSTAGRAM_USERNAME", index), "").strip() if platform == "instagram" else ""
    gone_x = values.get(_key("X_USERNAME", index), "").strip() if platform == "x" else ""
    gone_reddit = values.get(_key("REDDIT_USERNAME", index), "").strip() if platform == "reddit" else ""
    gone_wa = values.get(_key("WHATSAPP_NUMBER", index), "").strip() if platform == "whatsapp" else ""
    for prefix in spec["fields"].values():
        # Shift every later slot down one, then drop the now-duplicate tail.
        for i in range(index, total):
            values[_key(prefix, i)] = values.get(_key(prefix, i + 1), "")
        values.pop(_key(prefix, total), None)

    write_env(values)
    reload_into_process(values)
    await asyncio.to_thread(_renumber_account_data, platform, index, total)

    # Stop the child that was running this slot, if any: its credentials are gone and the numbering it was started with no longer refers to it.
    supervisor = request.app.state.supervisor
    if supervisor is not None:
        # Each stop() busy-waits up to graceful_seconds for the child to go, so a handful of slots could hold the event loop for most of a minute.
        def _stop_all():
            for child_id in (f"{platform}_{i}" for i in range(index, total + 1)):
                try:
                    supervisor.stop(child_id)
                except Exception:
                    pass

        await asyncio.to_thread(_stop_all)
    if gone_handle:
        await asyncio.to_thread(_drop_tiktok_profile, gone_handle)
    if gone_insta:
        await asyncio.to_thread(_drop_instagram_profile, gone_insta)
    if gone_x:
        await asyncio.to_thread(_drop_x_profile, gone_x)
    if gone_reddit:
        await asyncio.to_thread(_drop_reddit_profile, gone_reddit)
    if gone_wa:
        await asyncio.to_thread(_drop_whatsapp_keys, gone_wa)

    return {"ok": True, "slots": _slots(values)}
