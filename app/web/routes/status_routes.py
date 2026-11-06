import asyncio
import re
import time

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc
from app.platforms import registry
from app.utils import personas
from app.web.logbus import bus

router = APIRouter(tags=["status"])

START_TIME = time.time()


@router.get("/api/status")
async def status(request: Request):
    supervisor = request.app.state.supervisor
    from app.utils import socials
    switches = socials.on()
    return {
        "uptime": round(time.time() - START_TIME),
        # Not the accounts of a social switched off in Settings (app/utils/socials.py).
        "children": [c for c in supervisor.status()
                     if socials.child_shown(c.get("role"), c.get("account"), switches)],
        "port": supervisor.port,
    }


@router.get("/api/socials")
def socials_on(request: Request):
    """Which socials are switched on. The panel shows the ones that are off nowhere (app/utils/socials.py)."""
    from app.utils import socials
    return {"on": socials.on()}


def _identity(platform: str, account) -> dict:
    """Who an account actually is, recorded by the runner when it connects. Read from a file rather than asked over IPC, so the panel can still show the username and avatar for an account that is currently stopped."""
    if platform == "snapchat" and account:
        return _snap_identity(account)
    if platform in registry.BRIDGED_BUT_SNAPCHAT and account:
        return _web_identity(platform, account, registry.BY_ID[platform].tone)
    if platform != "discord" or not account:
        return {}
    try:
        import json
        from app.utils.paths import DATA_DIR
        path = DATA_DIR / "config" / f"identity_{account}.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        # Both end up in the page, the colour inside a style attribute, so only a Discord CDN address and a
        # plain #rrggbb get through.
        banner = str(data.get("banner") or "")
        accent = str(data.get("accent") or "").lower()
        return {
            "username": data.get("username", ""),
            "display_name": data.get("display_name", ""),
            # the account's own Discord id, so a message that pings it can say its name
            "user_id": str(data.get("id") or ""),
            "avatar": data.get("avatar", ""),
            "banner": banner if banner.startswith("https://cdn.discordapp.com/banners/") and '"' not in banner else "",
            "accent": accent if re.fullmatch(r"#[0-9a-f]{6}", accent) else "",
        }
    except Exception:
        return {}


def _snap_files(account, stem: str = "identity_snap") -> tuple:
    """(config dir, what the Snapchat runner recorded about who it is) for one account. stem="identity_tiktok":
    the TikTok runner's."""
    import json
    from app.utils.paths import DATA_DIR
    cfg = DATA_DIR / "config"
    try:
        data = json.loads((cfg / f"{stem}_{int(account)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}
    return cfg, data if isinstance(data, dict) else {}


def _snap_picture_file(account, key: str, stem: str = "identity_snap"):
    """The picture the runner saved (its Bitmoji, or that Bitmoji's background), when the file named is one of its own."""
    cfg, data = _snap_files(account, stem)
    name = str(data.get(key) or "")
    if not re.fullmatch(rf"{stem}_{int(account)}(_bg)?\.(webp|png|jpg)", name):
        return None
    path = cfg / name
    return path if path.is_file() else None


def _web_identity(platform: str, account, tone: str) -> dict:
    """A TikTok or Instagram account as its runner found it once signed in: its name, its username and its picture,
    read off the site and never changed. Until it has signed in once there is nothing, and the card shows the
    username it was added as. `tone` is the platform's own colour, for a card with no picture to blur."""
    try:
        stem = f"identity_{platform}"
        _, data = _snap_files(account, stem)
        if not data.get("username"):
            return {}
        n = int(account)
        path = _snap_picture_file(n, "picture", stem)
        avatar = f"/api/accounts/{platform}_{n}/picture?v={int(path.stat().st_mtime)}" if path else ""
        return {
            "username": str(data.get("username") or ""),
            "display_name": str(data.get("display_name") or ""),
            "avatar": avatar,
            "banner": "",
            "accent": "" if avatar else tone,
        }
    except Exception:
        return {}


def _snap_identity(account) -> dict:
    """A Snapchat account as its runner found it once signed in: the name it shows and its username, from Snapchat's account page, and its picture from its public profile, the profile photo before the Bitmoji, saved beside the file and served by the two routes below. With neither, the card draws Snapchat's empty silhouette, as Snapchat does, and takes Snapchat's yellow for its banner. Until the runner has signed in once there is nothing, and the card shows the login name."""
    try:
        _, data = _snap_files(account)
        if not data.get("username"):
            return {}
        n = int(account)

        def served(key, kind):
            path = _snap_picture_file(n, key)
            return f"/api/accounts/snapchat_{n}/{kind}?v={int(path.stat().st_mtime)}" if path else ""

        banner = served("background", "banner")
        avatar = served("picture", "picture")
        return {
            "username": str(data.get("username") or ""),
            "display_name": str(data.get("display_name") or ""),
            "avatar": avatar,
            # "photo" (its profile photo), "bitmoji", or "" when it has neither.
            "picture_kind": str(data.get("picture_kind") or ""),
            "banner": banner,
            # With a picture the card blurs it into its banner, as a Discord card does; Snapchat's yellow is for one with none.
            "accent": "" if (banner or avatar) else "#fffc00",
        }
    except Exception:
        return {}


def _snap_states(prefix: str = "snap") -> dict:
    """Each Snapchat runner's own account of itself, by account number. "Running" only says the process exists; an account sitting on a verification screen, or logged out and waiting to retry, is running too. prefix="tiktok": TikTok's."""
    try:
        from app.web.routes.system_routes import _snap_runner_states
        rows = _snap_runner_states(prefix)
    except Exception:
        return {}
    out = {}
    for row in rows:                       # newest first
        try:
            n = int(row.get("account") or 1)
        except (TypeError, ValueError):
            continue
        out.setdefault(n, row)
    return out


def _last_errors(ids: set) -> dict:
    """The most recent error line each account's worker printed. From the in-memory log, newest first, stopping once every account has one or the buffer runs out. "Crashing" with no reason sends you off to read the log; the line that says why is usually the last error it printed."""
    found: dict = {}
    # Walking backwards, the plain (unindented) line most recently passed for each source. When the error turns out to be "Traceback (most recent call last):", that is the line after its frames: the exception itself, which is the part worth showing. The traceback header says nothing.
    plain: dict = {}
    with bus.lock:
        entries = list(bus.buffer)
    for entry in reversed(entries):
        src = entry.get("source")
        if src not in ids or src in found:
            continue
        text = entry.get("text", "")
        if entry.get("level") == "error":
            if text.lstrip().startswith("Traceback") and plain.get(src):
                text = plain[src]
            found[src] = {"text": text[:300], "ts": entry.get("ts", 0)}
            if len(found) == len(ids):
                break
        elif text and not text[:1].isspace():
            plain[src] = text
    return found


@router.get("/api/accounts")
def accounts(request: Request):
    """Every account, and what it is doing. Plain def rather than async: it reads the identity and Snapchat state files and walks the log buffer, and none of that belongs on the event loop, so FastAPI runs it on its threadpool."""
    supervisor = request.app.state.supervisor
    # Not the accounts of a social switched off in Settings: the panel shows it nowhere.
    targets = ipc.shown_targets()
    children = {c["id"]: c for c in supervisor.status()}
    planned = getattr(supervisor, "planned", None)
    planned = planned() if callable(planned) else None
    in_use = {m["platform"] for m in targets.values()}
    says = {p: _snap_states(registry.TARGETS[p]) for p in registry.BRIDGED if p in in_use}
    errors = _last_errors(set(targets))
    out = []
    for web_id, meta in targets.items():
        child = children.get(web_id, {})
        row = {
            **_identity(meta["platform"], meta["account"]),
            "id": web_id,
            "platform": meta["platform"],
            "account": meta["account"],
            "target": meta["target"],
            "state": child.get("state", "stopped"),
            "pid": child.get("pid"),
            "restarts": child.get("restarts", 0),
            "uptime": child.get("uptime", 0),
            "retry_in": child.get("retry_in"),
            "gave_up": bool(child.get("gave_up")),
            # False when the platform is switched off: Start cannot work until it is turned back on, and the page should say so. A supervisor that cannot answer is not taken to mean "off".
            "enabled": (web_id in planned) if isinstance(planned, set) and planned else True,
            "last_error": errors.get(web_id),
            # Who it speaks as (app/utils/personas.py): Default unless it was given another.
            "persona": personas.persona_of(web_id),
        }
        if meta["platform"] == "snapchat":
            row["snap"] = says["snapchat"].get(meta["account"])
        if meta["platform"] in registry.BRIDGED:
            # What the runner says it is doing (signing in, a code to type, ready), as "web" for all of them:
            # Minecraft's and iMessage's runners report the same way, without a browser.
            row["web"] = says[meta["platform"]].get(meta["account"])
        out.append(row)
    tg_child = children.get("telegram")
    if tg_child:
        out.append({
            "id": "telegram",
            # Not a platform: the bot that controls the app. The persona's own Telegram accounts are
            # "telegram_<n>", with platform "telegram", and the panel tells them apart by this.
            "platform": "controller",
            "account": None,
            "target": "telegram",
            "state": tg_child.get("state", "stopped"),
            "pid": tg_child.get("pid"),
            "restarts": tg_child.get("restarts", 0),
            "uptime": tg_child.get("uptime", 0),
        })
    return {"accounts": out}


@router.post("/api/accounts/{child_id}/{action}")
async def account_action(request: Request, child_id: str, action: str):
    supervisor = request.app.state.supervisor
    if action == "start":
        return supervisor.start(child_id)
    if action == "stop":
        # stop() waits for the worker to log out of Discord, so it must not run on the event loop: the whole panel would freeze while it waits.
        import asyncio
        return await asyncio.to_thread(supervisor.stop, child_id)
    if action == "restart":
        import asyncio
        return await asyncio.to_thread(supervisor.restart, child_id)
    # Everything below talks to the running account over IPC.
    _IPC_ACTIONS = {
        "pause": "pause",       # toggles
        "wipe": "wipe",         # clears conversation history
        "reload": "reload",     # reloads the command modules
    }
    if action in _IPC_ACTIONS:
        meta = ipc.discover_targets().get(child_id)
        if not meta:
            raise HTTPException(status_code=404, detail="unknown account")
        result = await ipc.send_and_wait(meta["target"], _IPC_ACTIONS[action], timeout=15.0)
        return result or {"ok": False, "reason": "no response (runner not running?)"}
    raise HTTPException(status_code=400, detail=f"unknown action {action}")


def _snap_picture_response(child_id: str, key: str):
    from fastapi.responses import FileResponse
    m = re.fullmatch(rf"({'|'.join(registry.BRIDGED)})_(\d{{1,2}})", child_id)
    stem = f"identity_{m.group(1)}" if m and m.group(1) != "snapchat" else "identity_snap"
    path = _snap_picture_file(int(m.group(2)), key, stem) if m else None
    if not path:
        raise HTTPException(status_code=404, detail="no picture")
    # The address carries the file's time, so a new Bitmoji is a new address.
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/accounts/{child_id}/picture")
def account_picture(child_id: str):
    """A Snapchat account's Bitmoji, as its runner saved it."""
    return _snap_picture_response(child_id, "picture")


@router.get("/api/accounts/{child_id}/banner")
def account_banner(child_id: str):
    """The background of a Snapchat account's Bitmoji, for its card's banner."""
    return _snap_picture_response(child_id, "background")


@router.get("/api/accounts/{child_id}/details")
async def account_details(request: Request, child_id: str):
    """Live detail for one account: mood, paused, how much it is watching. Fetched on demand when a row is expanded rather than folded into /api/accounts, which the pages poll every few seconds; one IPC round trip per account per poll would be a lot of file traffic for information nobody is looking at most of the time."""
    meta = ipc.discover_targets().get(child_id)
    if not meta:
        raise HTTPException(status_code=404, detail="unknown account")
    result = await ipc.send_and_wait(meta["target"], "get_status", timeout=8.0)
    if result is None:
        return {"live": False, "reason": "the account is not running"}
    return {"live": True, **result}


@router.post("/api/accounts/{child_id}/mood")
async def account_mood(request: Request, child_id: str):
    body = await request.json()
    mood = str(body.get("mood", "")).strip()
    if not mood:
        raise HTTPException(status_code=400, detail="mood required")
    meta = ipc.discover_targets().get(child_id)
    if not meta:
        raise HTTPException(status_code=404, detail="unknown account")
    result = await ipc.send_and_wait(meta["target"], "mood_set", {"mood": mood}, timeout=8.0)
    return result or {"ok": False, "reason": "no response (runner not running?)"}


@router.post("/api/services/{name}/{action}")
async def service_action(request: Request, name: str, action: str):
    supervisor = request.app.state.supervisor
    if name == "kill_switch":
        result = await asyncio.gather(*[
            ipc.send_and_wait(meta["target"], "pause", {}, timeout=5.0)
            for meta in ipc.discover_targets().values()
        ], return_exceptions=True)
        return {"ok": True, "results": [r for r in result if isinstance(r, dict)]}
    if name == "webui" and action == "stop":
        return {"ok": False, "reason": "cannot stop the server you are connected to"}
    # stop() busy-waits up to graceful_seconds for the child to go, so these go to a thread exactly like the per-account versions above.
    if action == "start":
        return await asyncio.to_thread(supervisor.start, name)
    if action == "stop":
        return await asyncio.to_thread(supervisor.stop, name)
    if action == "restart":
        return await asyncio.to_thread(supervisor.restart, name)
    raise HTTPException(status_code=400, detail=f"unknown action {action}")


@router.post("/api/command")
async def raw_command(request: Request):
    body = await request.json()
    target = body.get("target")
    cmd = body.get("cmd")
    payload = body.get("payload", {})
    if not target or not cmd:
        raise HTTPException(status_code=400, detail="target and cmd required")
    if isinstance(target, str) and target.startswith(("discord_", "snapchat_", "tiktok_", "instagram_", "x_",
                                                      "reddit_", "whatsapp_", "minecraft_", "imessage_",
                                                      "telegram_")):
        meta = ipc.discover_targets().get(target)
        target = meta["target"] if meta else target
    timeout = float(body.get("timeout", 15.0))
    result = await ipc.send_and_wait(target, cmd, payload, timeout=timeout)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    return result


@router.get("/api/logs")
async def logs(request: Request, n: int = 200, source: str = ""):
    lines = bus.tail(n)
    if source:
        lines = [l for l in lines if l["source"] == source]
    return {"lines": lines}
