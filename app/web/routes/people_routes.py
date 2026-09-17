"""
app/web/routes/people_routes.py - the profile card behind a clicked username.

Everything shown here is already on disk: the bio cache the bot fills when it
reads someone's profile, the facts it has remembered, and the message log. This
just gathers it into one place so a name anywhere in the panel can be clicked.

Nothing is fetched from Discord here. If the cache has not seen someone, the
card says so rather than going and asking, which keeps clicking a name free.

The whole feature can be switched off in Settings, and the cache can be
emptied, because it is a local record of real people.
"""

import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request

from app.utils.paths import DATA_DIR
# connect_raw() instead of a bare sqlite3.connect(): a plain connection sets
# no busy_timeout, so these queries failed with "database is locked" rather
# than waiting whenever a bot runner happened to be writing.
from app.utils.db import connect_raw

router = APIRouter(tags=["people"])

DB_PATH = DATA_DIR / "config" / "bot_data.db"


def _enabled() -> bool:
    try:
        from app.utils.helpers import load_config
        cfg = (load_config().get("bot", {}) or {}).get("profile_cache", {}) or {}
        return bool(cfg.get("enabled", True))
    except Exception:
        return True


@router.get("/api/people/settings")
async def people_settings(request: Request):
    from app.utils.db import profile_cache_size
    try:
        size = profile_cache_size()
    except Exception:
        size = 0
    return {"enabled": _enabled(), "cached": size}


@router.delete("/api/people/cache")
async def clear_cache(request: Request):
    from app.utils.db import clear_profile_cache
    try:
        removed = clear_profile_cache()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "removed": removed}


# Someone whose account is stopped cannot be looked up, and retrying on every
# card open would stall the modal every time. A short memory of failures keeps
# the card instant.
_no_answer: dict = {}
_RETRY_AFTER = 300.0


async def _fetch_profile(uid: str) -> dict | None:
    """Ask a running Discord account who someone is, once."""
    import time as _t
    if _t.time() - _no_answer.get(uid, 0.0) < _RETRY_AFTER:
        return None
    try:
        from app.core import ipc
        targets = ipc.discover_targets()
        for meta in targets.values():
            target = meta["target"]
            if isinstance(target, str) and target.startswith("snap"):
                continue          # Snapchat has no profile endpoint to ask
            result = await ipc.send_and_wait(
                target, "get_profile", {"user_id": int(uid)}, timeout=6.0)
            if result and result.get("ok"):
                return result
    except Exception:
        pass
    _no_answer[uid] = _t.time()
    return None


@router.get("/api/people/{uid}")
async def person(request: Request, uid: str):
    """One person's card. `uid` is a string: Discord ids are 64 bit and lose
    precision as JSON numbers."""
    if not _enabled():
        return {"enabled": False}

    out: dict = {"enabled": True, "user_id": uid, "cached": False}

    try:
        from app.utils.db import get_profile_details
        details = get_profile_details(int(uid)) if uid.isdigit() else None
    except Exception:
        details = None
    if details:
        out["cached"] = True
        out.update({
            "bio": details.get("bio"),
            "username": details.get("username"),
            "display_name": details.get("display_name"),
            "avatar": details.get("avatar"),
            "fetched_at": details.get("fetched_at"),
        })

    # What the bot has remembered about them.
    try:
        from app.utils.memory import get_memory, get_persona
        key = int(uid) if uid.isdigit() else uid
        facts = {k: v for k, v in (get_memory(key) or {}).items()
                 if k != "__persona__"}
        out["facts"] = facts
        out["persona"] = get_persona(key)
    except Exception:
        facts = {}
        out["facts"] = {}
        out["persona"] = None

    # The bot has been writing the display name into memory as a "name" fact
    # since long before the profile cache existed, so use it when the cache has
    # not caught up. Without this, everyone already in the database shows their
    # @handle as their name until they happen to message again.
    if not out.get("display_name") and facts.get("name"):
        out["display_name"] = facts["name"]

    # Nothing cached yet? Ask a running account once, rather than showing a
    # blank card forever. Anyone already in the database predates the cache, so
    # waiting for them to message again is not a real answer. One short IPC
    # call, and the result is stored so it never has to be asked twice.
    if not out.get("avatar") and uid.isdigit():
        fetched = await _fetch_profile(uid)
        if fetched:
            out["cached"] = True
            out["avatar"] = fetched.get("avatar") or out.get("avatar")
            out["username"] = fetched.get("username") or out.get("username")
            out["display_name"] = (out.get("display_name")
                                   or fetched.get("display_name"))

    # Shown as the heading already, so repeating it in the remembered list is
    # just noise.
    if out.get("facts", {}).get("name") == out.get("display_name"):
        out["facts"] = {k: v for k, v in out["facts"].items() if k != "name"}

    # And how much they actually talk.
    try:
        conn = connect_raw()
        try:
            row = conn.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts) FROM message_log WHERE user_id = ?",
                (int(uid),)).fetchone()
            if row and row[0]:
                out["messages"] = row[0]
                out["first_seen"] = row[1]
                out["last_seen"] = row[2]
            name = conn.execute(
                "SELECT username FROM user_stats WHERE user_id = ?", (int(uid),)).fetchone()
            if name and name[0] and not out.get("username"):
                out["username"] = name[0]
            week = conn.execute(
                "SELECT COUNT(*) FROM message_log WHERE user_id = ? AND ts >= ?",
                (int(uid), time.time() - 7 * 86400)).fetchone()
            out["messages_7d"] = week[0] if week else 0
        finally:
            conn.close()
    except Exception:
        pass

    return out
