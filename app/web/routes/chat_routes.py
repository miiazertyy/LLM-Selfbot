import asyncio
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc
from app.utils.paths import DATA_DIR
# connect_raw() instead of a bare sqlite3.connect(): a plain connection sets
# no busy_timeout, so these queries failed with "database is locked" rather
# than waiting whenever a bot runner happened to be writing.
from app.utils.db import connect_raw

router = APIRouter(tags=["chats"])

DB_PATH = DATA_DIR / "config" / "bot_data.db"


def _resolve_target(request: Request, explicit=None):
    if explicit:
        meta = ipc.discover_targets().get(explicit)
        if not meta:
            raise HTTPException(status_code=404, detail=f"unknown target {explicit}")
        return meta["target"]
    targets = ipc.discover_targets()
    if not targets:
        raise HTTPException(status_code=503, detail="no accounts configured")
    return next(iter(targets.values()))["target"]


# Discord IDs are 64-bit snowflakes, about 19 digits. JavaScript parses a JSON
# number into a double, which only holds integers exactly up to 2**53, so an id
# sent as a number comes back subtly different:
#
#     1234567890123456789  ->  1234567890123456768
#
# Discord then answers "Unknown User" (error 10013) for an id that plainly
# exists. Sending ids as strings keeps them exact; the runner parses them back
# to int on arrival.
def _stringify_ids(rows, *fields):
    out = []
    for row in rows:
        row = dict(row)
        for f in fields:
            if row.get(f) is not None:
                row[f] = str(row[f])
        out.append(row)
    return out


def _profiles_for(ids) -> dict:
    """Avatar and names for these user ids, from the local profile cache.

    Read here rather than asked of the runner: the profiles are already in
    sqlite, written whenever the bot sees someone, so this costs one local
    query instead of a round trip to a process that may be mid-reply. Ids are
    matched as strings because a snowflake does not survive JSON as a number.
    """
    wanted = {str(i) for i in ids if i is not None}
    if not wanted:
        return {}
    out = {}
    conn = connect_raw()
    try:
        for uid, display, uname, avatar in conn.execute(
                "SELECT user_id, display_name, username, avatar FROM user_profiles"):
            if str(uid) in wanted:
                out[str(uid)] = {"display_name": display or "",
                                 "username": uname or "", "avatar": avatar or ""}
    except sqlite3.OperationalError:
        pass                      # nobody has been profiled on this install yet
    finally:
        conn.close()
    return out


# The last answer from each runner, so opening the Chats tab does not wait.
#
# Asking who is waiting is not a database read: the runner sweeps its DM
# channels and answers when it is done, which is seconds. That cost was paid on
# every single visit to the tab, and nothing survived a relaunch, so it was paid
# again every time the app started.
#
# Held here rather than in the browser on purpose. The panel already learned
# this the hard way for preferences (see stores.ts): the desktop webview runs in
# private mode, so localStorage is wiped on exit, and it is keyed on the origin,
# so falling back to port 8788 because 8787 was busy starts from empty anyway.
# The server has neither problem.
_CHATS_CACHE: dict = {}
_CHATS_TTL = 20.0         # a sweep is seconds; asking again inside this is waste
_CHATS_LOCKS: dict = {}


async def _chats_payload(tgt, fresh: bool = False) -> dict:
    """The waiting list for one runner, from cache unless it is stale."""
    hit = _CHATS_CACHE.get(tgt)
    if not fresh and hit and (time.time() - hit["at"]) < _CHATS_TTL:
        return hit["body"]

    # One sweep at a time per runner. Without this the page's own refresh and
    # the background prefetch could ask the same bot twice at once, doubling
    # the work it does to answer the same question.
    lock = _CHATS_LOCKS.setdefault(tgt, asyncio.Lock())
    async with lock:
        hit = _CHATS_CACHE.get(tgt)
        if not fresh and hit and (time.time() - hit["at"]) < _CHATS_TTL:
            return hit["body"]
        result = await ipc.send_and_wait(tgt, "reply_check", timeout=10.0)
        if result is None:
            # A runner that is busy or restarting should not blank the tab when
            # there is a perfectly good answer from a moment ago.
            if hit:
                return hit["body"]
            raise HTTPException(status_code=504, detail="runner did not respond")
        users = _stringify_ids(result.get("users", []), "id")
        profiles = _profiles_for(u.get("id") for u in users)
        for u in users:
            meta = profiles.get(u.get("id")) or {}
            u["avatar"] = meta.get("avatar") or ""
            u["username"] = meta.get("username") or ""
        body = {
            "users": users,
            "target": tgt,
            "paused": result.get("paused", False),
            "cooldown_until": result.get("cooldown_until", 0),
            "cooldown_range": result.get("cooldown_range"),
        }
        _CHATS_CACHE[tgt] = {"body": body, "at": time.time()}
        return body


async def warm_chats() -> None:
    """Fill the cache for every account, once, at startup.

    The tab is usually opened within a few seconds of the app appearing, and
    before this the first visit was the thing that paid for the sweep. Runners
    take a moment to come up, so this waits for them rather than asking a
    process that is not listening yet.
    """
    for attempt in range(12):                 # up to a minute
        await asyncio.sleep(5)
        try:
            targets = ipc.discover_targets()
        except Exception:
            continue
        if not targets:
            continue
        for meta in targets.values():
            try:
                # Staggered: each one costs that bot a channel sweep, and
                # sweeping every account at the same moment is the one shape
                # worth avoiding.
                await _chats_payload(meta["target"], fresh=True)
                await asyncio.sleep(1.2)
            except Exception:
                pass          # a runner that is not ready gets picked up on the
                              # first real request instead
        return


@router.get("/api/chats")
async def chats(request: Request, target: str = "", fresh: bool = False):
    tgt = _resolve_target(request, target)
    return await _chats_payload(tgt, fresh=fresh)


@router.get("/api/chats/archive")
async def archive(request: Request, limit: int = 40):
    """Conversations that have already been dealt with.

    The waiting list answers "who needs me", and then a conversation vanishes
    from it the moment it is answered, which leaves no way to look back at
    someone you spoke to an hour ago.

    Read from the message log rather than asked over IPC: it survives restarts,
    covers every account, and costs a local query instead of a round trip to a
    bot that might be busy.
    """
    conn = connect_raw()
    try:
        try:
            rows = conn.execute(
                """
                SELECT m.user_id,
                       COALESCE(us.username, m.username) AS name,
                       COUNT(*)  AS total,
                       MAX(m.ts) AS last_ts
                FROM message_log m
                LEFT JOIN user_stats us ON us.user_id = m.user_id
                GROUP BY m.user_id
                ORDER BY last_ts DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),)).fetchall()
        except sqlite3.OperationalError:
            rows = []          # nothing has spoken to this install yet

        profiles = {}
        try:
            for uid, display, uname, avatar in conn.execute(
                    "SELECT user_id, display_name, username, avatar FROM user_profiles"):
                profiles[str(uid)] = {
                    "display_name": display or "",
                    "username": uname or "",
                    "avatar": avatar or "",
                }
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    out = []
    for uid, name, total, last_ts in rows:
        meta = profiles.get(str(uid), {})
        out.append({
            "id": str(uid),
            "name": meta.get("display_name") or name or str(uid),
            "username": meta.get("username", ""),
            "avatar": meta.get("avatar", ""),
            "messages": total,
            "last_ts": last_ts,
        })
    return {"conversations": out}


@router.get("/api/friends")
async def friends(request: Request, target: str = ""):
    """Friend requests waiting on this account.

    Snapchat has no equivalent, so it answers with an empty list rather than an
    error: the page asks for whichever account is selected.
    """
    tgt = _resolve_target(request, target)
    if isinstance(tgt, str) and tgt.startswith("snap"):
        return {"requests": [], "supported": False}
    result = await ipc.send_and_wait(tgt, "friends_pending", timeout=15.0)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason", "could not read them"))
    return {"requests": _stringify_ids(result.get("requests", []), "id"),
            "supported": True, "target": tgt}


@router.post("/api/friends/{action}")
async def friend_action(request: Request, action: str):
    """Accept or decline a request now, instead of on the background timer.

    The automatic accept deliberately waits, spread over hours, so the account
    does not look like a script. That is right when nobody is watching and
    wrong when you are looking straight at the request, so this takes it
    immediately.
    """
    if action not in ("accept", "decline"):
        raise HTTPException(status_code=400, detail="accept or decline")
    body = await request.json()
    user_id = body.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, body.get("target", ""))
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="user_id must be a number")
    result = await ipc.send_and_wait(
        tgt, f"friend_{action}", {"user_id": user_id}, timeout=20.0)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    return result


@router.post("/api/chats/reply")
async def reply(request: Request):
    body = await request.json()
    target = body.get("target", "")
    user_id = body.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, target)
    if isinstance(tgt, str) and tgt.startswith("snap"):
        user_id = str(user_id)
    else:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="user_id must be an integer for Discord")
    result = await ipc.send_and_wait(tgt, "reply_user", {"user_id": user_id}, timeout=120.0)
    _CHATS_CACHE.pop(tgt, None)     # that person is no longer waiting
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    return result


@router.post("/api/chats/reply-all")
async def reply_all(request: Request):
    body = await request.json()
    tgt = _resolve_target(request, body.get("target", ""))
    result = await ipc.send_and_wait(tgt, "reply_all", timeout=300.0)
    _CHATS_CACHE.pop(tgt, None)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    if isinstance(result.get("results"), list):
        result["results"] = _stringify_ids(result["results"], "id")
    return result


def _conn():
    return connect_raw()


@router.get("/api/memory")
async def memory_list(request: Request):
    """Everyone the bot remembers something about, with enough to sort by.

    The page used to show a name and a fact count, which is not enough to know
    who is worth opening. Message counts, the last time they spoke and whether
    they have their own persona all come from tables that are already there.
    """
    conn = _conn()
    try:
        try:
            rows = conn.execute(
                """
                SELECT m.user_id, m.key, m.value, COALESCE(us.username, '') as username
                FROM user_memory m
                LEFT JOIN user_stats us ON us.user_id = m.user_id
                ORDER BY m.user_id, m.key
                """
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        stats = {}
        try:
            for uid, count, first in conn.execute(
                    "SELECT user_id, message_count, first_seen FROM user_stats"):
                stats[str(uid)] = {"messages": count, "first_seen": first}
        except sqlite3.OperationalError:
            pass
        last = {}
        try:
            for uid, ts in conn.execute(
                    "SELECT user_id, MAX(ts) FROM message_log GROUP BY user_id"):
                last[str(uid)] = ts
        except sqlite3.OperationalError:
            pass
        profiles = {}
        try:
            for uid, display, uname, avatar in conn.execute(
                    "SELECT user_id, display_name, username, avatar FROM user_profiles"):
                profiles[str(uid)] = {"name": display or uname or "", "avatar": avatar or ""}
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    users = {}
    for uid, key, value, username in rows:
        uid = str(uid)
        entry = users.setdefault(uid, {
            "user_id": uid, "username": username, "facts": {}, "persona": "",
        })
        # The persona rides in the same table under a reserved key, so it has
        # to be split back out rather than listed as a fact.
        if key == "__persona__":
            entry["persona"] = value
        else:
            entry["facts"][key] = value

    out = []
    for uid, entry in users.items():
        profile = profiles.get(uid) or {}
        entry["display_name"] = profile.get("name", "")
        # A face makes a list of names scannable in a way that a list of names
        # is not.
        entry["avatar"] = profile.get("avatar", "")
        entry["messages"] = stats.get(uid, {}).get("messages", 0)
        entry["first_seen"] = stats.get(uid, {}).get("first_seen", 0)
        entry["last_seen"] = last.get(uid, 0)
        entry["fact_count"] = len(entry["facts"])
        out.append(entry)
    out.sort(key=lambda u: (u["last_seen"], u["fact_count"]), reverse=True)
    return {"users": out}


@router.get("/api/memory/{uid}")
async def memory_get(request: Request, uid: str):
    from app.utils.memory import get_memory, get_persona
    facts = get_memory(int(uid)) if uid.isdigit() else get_memory(uid)
    persona = get_persona(int(uid)) if uid.isdigit() else get_persona(uid)
    return {"facts": facts, "persona": persona}


@router.put("/api/memory/{uid}")
async def memory_put(request: Request, uid: str):
    body = await request.json()
    from app.utils.memory import set_memory, clear_persona, set_persona
    key = body.get("key")
    value = body.get("value", "")
    persona = body.get("persona")
    if key:
        set_memory(uid, key, str(value))
    if persona is not None:
        if persona:
            set_persona(uid, persona)
        else:
            clear_persona(uid)
    return {"ok": True}


@router.delete("/api/memory/{uid}")
async def memory_delete(request: Request, uid: str):
    body = await request.json()
    from app.utils.memory import delete_memory
    key = body.get("key", "")
    if key:
        delete_memory(uid, key)
    else:
        from app.utils.memory import clear_memory
        clear_memory(uid)
    return {"ok": True}
