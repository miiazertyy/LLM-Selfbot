"""app/web/routes/account_routes.py - add, edit and remove account slots. An "account" is a numbered set of credentials in config/.env: Discord DISCORD_TOKEN_<n> / DISCORD_PROXY_<n>, Snapchat SNAP_USERNAME_<n> / SNAP_PASSWORD_<n>. The numbering must stay contiguous from 1, because the account counters stop at the first gap, so deleting slot 2 of 3 renumbers the old slot 3 down to 2. Credentials are write-only: a GET never returns a token or password, not even masked, it reports whether one is set, and the UI can only replace it."""

import asyncio
from fastapi import APIRouter, HTTPException, Request

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
        "fields": {"username": "SNAP_USERNAME", "password": "SNAP_PASSWORD"},
        "secret": ("password",),
        "required": "username",
    },
}
MAX_SLOTS = 50


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
    out = []
    for platform, spec in PLATFORMS.items():
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


@router.post("/api/accounts/slots/{platform}")
async def add_slot(request: Request, platform: str):
    """Append a new account. The body carries its initial credentials."""
    spec = _platform(platform)
    body = await request.json()
    values = _migrate_legacy(read_env())

    required = spec["required"]
    if not str(body.get(required, "")).strip():
        raise HTTPException(status_code=400, detail=f"{required} is required")
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
    values = _migrate_legacy(read_env())

    if not 1 <= index <= _count(values, platform):
        raise HTTPException(status_code=404, detail="no such account")

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
    import json
    import re

    def own(n):
        # identity_snap_1* also matches identity_snap_10.json: only this number's own files.
        out = []
        for p in cfg.glob(f"identity_snap_{n}*"):
            m = re.fullmatch(rf"identity_snap_{n}((_bg)?\.(json|webp|png|jpg))", p.name)
            if m:
                out.append((p, m.group(1)))
        return out

    try:
        for p, _ in own(index):
            p.unlink(missing_ok=True)
        for i in range(index + 1, total + 1):
            for p, tail in own(i):
                p.replace(cfg / f"identity_snap_{i - 1}{tail}")
            j = cfg / f"identity_snap_{i - 1}.json"
            if j.exists():
                data = json.loads(j.read_text(encoding="utf-8"))
                for key in ("picture", "background"):
                    if data.get(key):
                        data[key] = re.sub(rf"^identity_snap_{i}(?=[._])", f"identity_snap_{i - 1}", str(data[key]))
                j.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass


@router.delete("/api/accounts/slots/{platform}/{index}")
async def delete_slot(request: Request, platform: str, index: int):
    """Remove an account and close the gap so the numbering stays contiguous."""
    spec = _platform(platform)
    values = _migrate_legacy(read_env())
    total = _count(values, platform)
    if not 1 <= index <= total:
        raise HTTPException(status_code=404, detail="no such account")

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

    return {"ok": True, "slots": _slots(values)}
