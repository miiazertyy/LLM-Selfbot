import asyncio
import sqlite3
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request

from app.core import ipc
from app.platforms import registry
from app.utils.paths import DATA_DIR
# connect_raw() instead of a bare sqlite3.connect(): a plain connection sets no busy_timeout, so these queries failed with "database is locked" rather than waiting whenever a bot runner happened to be writing.
from app.utils.db import connect_raw

router = APIRouter(tags=["chats"])

DB_PATH = DATA_DIR / "config" / "bot_data.db"


def _resolve_target(request: Request, explicit=None):
    if explicit:
        meta = ipc.discover_targets().get(explicit)
        if not meta:
            raise HTTPException(status_code=404, detail=f"unknown target {explicit}")
        return meta["target"]
    targets = ipc.shown_targets()
    if not targets:
        raise HTTPException(status_code=503, detail="no accounts configured")
    return next(iter(targets.values()))["target"]


# Discord IDs are 64-bit snowflakes, about 19 digits. JavaScript parses a JSON number into a double, which only holds integers exactly up to 2**53, so an id sent as a number comes back subtly different (1234567890123456789 -> 1234567890123456768), and Discord then answers "Unknown User" (error 10013) for an id that plainly exists. Sending ids as strings keeps them exact; the runner parses them back to int on arrival.
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
    """Avatar and names for these user ids, from the local profile cache. Read here rather than asked of the runner: the profiles are already in sqlite, written whenever the bot sees someone, so this costs one local query instead of a round trip to a process that may be mid-reply. Ids are matched as strings because a snowflake does not survive JSON as a number."""
    # Only the ones asked for, by the table's key: reading every profile to keep a few took a second on an account that
    # has met a lot of people, on the thread every page shares, and the panel froze for it.
    wanted = sorted({int(i) for i in (str(x) for x in ids if x is not None) if i.isdigit()})
    if not wanted:
        return {}
    out = {}
    conn = connect_raw()
    try:
        for start in range(0, len(wanted), 400):
            part = wanted[start:start + 400]
            for uid, display, uname, avatar in conn.execute(
                    f"SELECT user_id, display_name, username, avatar FROM user_profiles "
                    f"WHERE user_id IN ({','.join('?' * len(part))})", part):
                out[str(uid)] = {"display_name": display or "",
                                 "username": uname or "", "avatar": avatar or ""}
    except sqlite3.OperationalError:
        pass                      # nobody has been profiled on this install yet
    finally:
        conn.close()
    return out


# The last answer from each runner, so opening the Chats tab does not wait. Asking who is waiting is not a database read: the runner sweeps its DM channels and answers when it is done, which is seconds, and that cost was paid on every single visit to the tab, and nothing survived a relaunch, so it was paid again every time the app started. Held here rather than in the browser on purpose: the panel already learned this the hard way for preferences (see stores.ts), the desktop webview runs in private mode, so localStorage is wiped on exit, and it is keyed on the origin, so falling back to port 8788 because 8787 was busy starts from empty anyway. The server has neither problem.
_CHATS_CACHE: dict = {}
_CHATS_TTL = 20.0         # a sweep is seconds; asking again inside this is waste
_CHATS_LOCKS: dict = {}


# Live events from each runner (see emit_chat_event), the last few per account, so a sweep that was already under way when one arrived does not put back what the event changed.
_CHAT_EVENTS: dict = {}
# The calls going on now, per account and person, as the runners say them: given with the list, so a page opened during
# one shows it, and kept live by the same events.
_CALLS: dict = {}
# A TikTok account's LIVE as it goes: whether it is on, and its last lines and what the persona said, for a page (the
# LIVE view, the OBS page) opened in the middle of one.
_LIVE: dict = {}
# Someone else's LIVE the account is visiting as a viewer, the same way: whose, since when, its chat and its lines.
_VISITS: dict = {}
_MSG_FIELDS = ("text", "attachments", "stickers", "embeds")
_MSG_KEYS = _MSG_FIELDS + ("mid", "gift")


# Each browser platform's IPC target prefix: account 1 is the bare prefix, the rest carry their number.
_WEB_PREFIX = registry.TARGETS


def _ipc_target_for(web_id: str):
    """discord_2 -> 2, snapchat_2 -> "snap2", tiktok_1 -> "tiktok", instagram_2 -> "insta2": the key _CHATS_CACHE
    uses."""
    platform, _, n = str(web_id).partition("_")
    if platform == "discord" and n.isdigit():
        return int(n)
    prefix = _WEB_PREFIX.get(platform)
    if prefix and n.isdigit():
        return prefix if n == "1" else f"{prefix}{n}"
    return None


def _snap_number(tgt) -> int:
    """"snap" -> 1, "snap2" -> 2; "tiktok" -> 1, "tiktok3" -> 3; "insta" -> 1, "insta2" -> 2; "imsg2" -> 2.
    The longest prefixes first, and X's one letter last of all."""
    t = str(tgt)
    for prefix in sorted(registry.TARGETS.values(), key=len, reverse=True):
        if t.startswith(prefix):
            return int(t[len(prefix):] or 1)
    return 1


def _web_platform(tgt) -> str:
    """"snapchat", "tiktok" or "instagram" for a browser account's target, "" for Discord's."""
    if not isinstance(tgt, str):
        return ""
    for platform, prefix in _WEB_PREFIX.items():
        if tgt.startswith(prefix):
            return platform
    return ""


# The browser platforms' tables in the database (app/utils/db.py WEB_TABLES).
_WEB_TABLE = registry.TABLES


# What a server conversation's row carries beyond a person's: see server_row() in the runner.
_ROW_EXTRA = ("kind", "channel_id", "author_id", "where")


def apply_event(body: dict, evt: dict) -> dict:
    """One event applied to a waiting-list body, returning a new body. Never mutates the one passed in: this runs on a supervisor reader thread while the event loop may be serialising the same dict for a response."""
    kind = evt.get("t")
    uid = str(evt.get("uid", ""))
    users = list(body.get("users") or [])
    out = dict(body)
    if kind == "meta":
        out["paused"] = bool(evt.get("paused"))
        out["cooldown_until"] = evt.get("cooldown_until") or 0
        return out
    idx = next((i for i, u in enumerate(users) if str(u.get("id")) == uid), -1)
    if kind == "done":
        if idx >= 0:
            users.pop(idx)
    elif kind == "state" and idx >= 0:
        users[idx] = {**users[idx], "state": evt.get("state")}
    elif kind == "ignored" and any(str(u.get("id")) == uid or str(u.get("author_id") or "") == uid for u in users):
        # a person's server rows too: the bot is off for them wherever they ask
        users = [{**u, "ignored": bool(evt.get("ignored"))}
                 if str(u.get("id")) == uid or str(u.get("author_id") or "") == uid else u for u in users]
    elif kind == "payload" and idx >= 0:
        # The whole message, fetched on request for a row that only had its text: same message, so no count change.
        users[idx] = {**users[idx], **{k: evt[k] for k in _MSG_KEYS if k in evt}}
    elif kind == "msg":
        fresh = {k: evt[k] for k in _MSG_KEYS if k in evt}
        # A message with no attachments must clear the last one's pictures, and one that is not a gift must clear
        # the gift the last one was, or the row goes on saying "Sent a Nitro gift".
        for k in _MSG_FIELDS[1:]:
            fresh.setdefault(k, [])
        fresh.setdefault("gift", None)
        fresh.update(snippet=evt.get("snippet", ""), ts=evt.get("ts") or 0,
                     ignored=bool(evt.get("ignored")))
        if evt.get("kind") == "server":
            # someone else may be the one asking in that channel now
            fresh.update({k: evt[k] for k in (*_ROW_EXTRA, "name", "avatar") if k in evt})
        if idx >= 0:
            # The same message seen twice (a sweep that already had it) is not a second one.
            again = bool(evt.get("mid")) and users[idx].get("mid") == evt.get("mid")
            row = {**users[idx], **fresh, "count": int(users[idx].get("count") or 0) + (0 if again else 1)}
            # A new message is a new thing to answer: whatever happened to the last one no longer describes it.
            if (row.get("state") or {}).get("state") in ("skipped", "failed"):
                row.pop("state", None)
            users[idx] = row
        else:
            users.append({"id": uid, "name": evt.get("name") or uid, "username": evt.get("username") or "",
                          "avatar": evt.get("avatar") or "", "count": 1, "reply_at": None, **fresh,
                          # a server conversation says where it is and who wrote
                          **{k: evt[k] for k in _ROW_EXTRA if k in evt}})
    else:
        return body
    out["users"] = users
    return out


def apply_chat_event(web_id: str, evt: dict) -> None:
    """Called by the supervisor for each event a runner pushes."""
    tgt = _ipc_target_for(web_id)
    if tgt is None:
        return
    # Typing lapses in seconds, and comes every few while someone types: not worth replaying, and it would crowd out what is.
    if evt.get("t") == "typing":
        return
    if evt.get("t") in ("live", "live_say", "live_state", "attention"):
        live = _LIVE.setdefault(tgt, {"on": False, "feed": deque(maxlen=80)})
        if evt["t"] == "live_state":
            live["on"] = bool(evt.get("live"))
        elif evt["t"] != "attention":
            live["feed"].append({**{k: v for k, v in evt.items() if k != "target"}, "at": time.time()})
        return
    if evt.get("t") in ("visit", "visit_say", "visit_said", "visit_state"):
        visit = _VISITS.setdefault(tgt, {"on": False, "host": "", "name": "", "why": "", "since": 0.0,
                                         "feed": deque(maxlen=80)})
        if evt["t"] == "visit_state":
            on = bool(evt.get("on"))
            if on:
                visit["feed"].clear()
                visit["since"] = time.time()
            visit.update(on=on, host=str(evt.get("host") or ""), name=str(evt.get("name") or ""),
                         why=str(evt.get("why") or ""))
        elif evt["t"] != "visit_said":
            visit["feed"].append({**{k: v for k, v in evt.items() if k != "target"}, "at": time.time()})
        return
    if evt.get("t") == "call":
        calls = _CALLS.setdefault(tgt, {})
        uid = str(evt.get("uid", ""))
        if isinstance(evt.get("call"), dict):
            calls[uid] = {**evt["call"], "uid": uid}
        else:
            calls.pop(uid, None)
        return
    _CHAT_EVENTS.setdefault(tgt, deque(maxlen=200)).append((time.time(), evt))
    hit = _CHATS_CACHE.get(tgt)
    if hit:
        _CHATS_CACHE[tgt] = {"body": apply_event(hit["body"], evt), "at": hit["at"]}


async def _chats_payload(tgt, fresh: bool = False) -> dict:
    """The waiting list for one runner, from cache unless it is stale."""
    hit = _CHATS_CACHE.get(tgt)
    if not fresh and hit and (time.time() - hit["at"]) < _CHATS_TTL:
        return hit["body"]

    # One sweep at a time per runner. Without this the page's own refresh and the background prefetch could ask the same bot twice at once, doubling the work it does to answer the same question.
    lock = _CHATS_LOCKS.setdefault(tgt, asyncio.Lock())
    async with lock:
        hit = _CHATS_CACHE.get(tgt)
        if not fresh and hit and (time.time() - hit["at"]) < _CHATS_TTL:
            return hit["body"]
        started = time.time()
        result = await ipc.send_and_wait(tgt, "reply_check", timeout=10.0)
        if result is None:
            # A runner that is busy or restarting should not blank the tab when there is a perfectly good answer from a moment ago.
            if hit:
                return hit["body"]
            raise HTTPException(status_code=504, detail="runner did not respond")
        users = _stringify_ids(result.get("users", []), "id")
        if _is_snap(tgt):
            from app.utils import snappeople
            n, plat = _snap_number(tgt), _web_platform(tgt)
            for u in users:
                u["avatar"] = u.get("avatar") or snappeople.avatar_url(n, u.get("id", ""), plat)
                if not u.get("name") or str(u.get("name")) == str(u.get("id")):
                    u["name"] = snappeople.name_of(n, u.get("id", ""), plat) or u.get("name")
        profiles = await asyncio.to_thread(_profiles_for, [u.get("id") for u in users])
        for u in users:
            meta = profiles.get(u.get("id")) or {}
            # a server row brings its own: it is keyed by channel, not by the person
            u["avatar"] = meta.get("avatar") or u.get("avatar") or ""
            u["username"] = meta.get("username") or u.get("username") or ""
            # The runner names someone by their id when Discord's user cache has lost them, which is often, for a DM found by the sweep or the stored list. The profile cache usually still knows them.
            if not u.get("name") or str(u.get("name")) == str(u.get("id")):
                u["name"] = meta.get("display_name") or meta.get("username") or u.get("name")
        body = {
            "users": users,
            "target": tgt,
            "truncated": bool(result.get("truncated")),
            "paused": result.get("paused", False),
            "cooldown_until": result.get("cooldown_until", 0),
            "cooldown_range": result.get("cooldown_range"),
        }
        # Anything that happened while the runner was sweeping is newer than what the sweep saw.
        for at, evt in list(_CHAT_EVENTS.get(tgt, ())):
            if at >= started:
                body = apply_event(body, evt)
        # When this answer was true, so the page can put its own newer events back over it.
        body["swept_at"] = started
        _CHATS_CACHE[tgt] = {"body": body, "at": time.time()}
        return body


async def warm_chats() -> None:
    """Fill the cache for every account, once, at startup. The tab is usually opened within a few seconds of the app appearing, and before this the first visit was the thing that paid for the sweep. Runners take a moment to come up, so this waits for them rather than asking a process that is not listening yet."""
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
                # Staggered: each one costs that bot a channel sweep, and sweeping every account at the same moment is the one shape worth avoiding.
                await _chats_payload(meta["target"], fresh=True)
                await asyncio.sleep(1.2)
            except Exception:
                pass          # a runner that is not ready gets picked up on the first real request instead
        return


@router.get("/api/chats")
async def chats(request: Request, target: str = "", fresh: bool = False):
    tgt = _resolve_target(request, target)
    body = await _chats_payload(tgt, fresh=fresh)
    # Calls are as they are now, not as the cached list last was.
    return {**body, "calls": list(_CALLS.get(tgt, {}).values())}


@router.get("/api/live/{web_id}")
def live_feed(web_id: str):
    """A TikTok account's LIVE: whether it is on, what was said and answered lately (newest last), and how the OBS
    page shows the answers (tiktok.live.overlay_*, as the account's persona has them)."""
    from app.utils import livecohost, personas
    from app.utils.helpers import load_config
    tgt = _ipc_target_for(web_id)
    if not isinstance(tgt, str) or not tgt.startswith("tiktok"):
        raise HTTPException(status_code=404, detail="not a TikTok account")
    live = _LIVE.get(tgt) or {"on": False, "feed": []}
    visit = _VISITS.get(tgt) or {}
    try:
        with personas.scope(personas.persona_of(web_id)):
            shown = livecohost.overlay(livecohost.settings(((load_config() or {}).get("tiktok") or {}).get("live")))
    except Exception:
        shown = livecohost.overlay(livecohost.settings(None))
    return {"live": bool(live["on"]), "feed": list(live["feed"]), "overlay": shown,
            # A LIVE it is visiting as a viewer, when it is in one.
            "visit": {"on": bool(visit.get("on")), "host": visit.get("host", ""), "name": visit.get("name", ""),
                      "why": visit.get("why", ""), "since": visit.get("since", 0.0),
                      "feed": list(visit.get("feed") or [])}}


@router.get("/api/live/{web_id}/audio/{name}")
def live_audio(web_id: str, name: str):
    """One spoken answer of the persona's on a LIVE, as the bridge made it (a short wav)."""
    import re as _re
    from fastapi.responses import FileResponse
    from app.utils.paths import DATA_DIR
    if not _re.fullmatch(r"\d{1,2}_[0-9a-f]{32}_\d{1,2}\.wav", name) or not web_id.startswith("tiktok_"):
        raise HTTPException(status_code=404, detail="no such audio")
    if name.split("_", 1)[0] != web_id.split("_", 1)[1]:
        raise HTTPException(status_code=404, detail="no such audio")
    path = DATA_DIR / "cache" / "live_audio" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such audio")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/api/chats/archive")
def archive(request: Request, limit: int = 40, target: str = ""):
    """Conversations that have already been dealt with. The waiting list answers "who needs me", and then a conversation vanishes from it the moment it is answered, which leaves no way to look back at someone you spoke to an hour ago. Read from the message log rather than asked over IPC: it survives restarts, covers every account, and costs a local query instead of a round trip to a bot that might be busy.

    With a target, one account's only: a Discord account's people, or a Snapchat account's chats (its own log, by
    chat id, named as Snapchat names them). Rows from before the log knew its account count as the first one's."""
    # Plain def: it only reads sqlite, and as async it did that on the event loop every page shares, during the startup warm-up of every tab.
    # With no account named it is Discord's whole log: nothing, when Discord is switched off (app/utils/socials.py).
    from app.utils import socials
    if not target and not socials.shown("discord"):
        return {"conversations": []}
    tgt = _resolve_target(request, target) if target else None
    snap = _is_snap(tgt)
    plat = _web_platform(tgt)
    table = _WEB_TABLE.get(plat, "snap")
    n = 0
    if tgt is not None:
        n = _snap_number(tgt) if snap else int(tgt)
    cap = max(1, min(limit, 200))
    conn = connect_raw()
    try:
        try:
            if snap:
                rows = conn.execute(
                    f"""
                    SELECT s.chat_id,
                           (SELECT s2.username FROM message_log_{table} s2 WHERE s2.chat_id = s.chat_id
                            ORDER BY s2.ts DESC LIMIT 1) AS name,
                           COUNT(*)  AS total,
                           MAX(s.ts) AS last_ts
                    FROM message_log_{table} s
                    WHERE s.account = ? OR (s.account IS NULL AND ? = 1)
                    GROUP BY s.chat_id
                    ORDER BY last_ts DESC
                    LIMIT ?
                    """,
                    (n, n, cap)).fetchall()
            else:
                where = "WHERE m.account = ? OR (m.account IS NULL AND ? = 1)" if n else ""
                rows = conn.execute(
                    f"""
                    SELECT m.user_id,
                           COALESCE(us.username, m.username) AS name,
                           COUNT(*)  AS total,
                           MAX(m.ts) AS last_ts
                    FROM message_log m
                    LEFT JOIN user_stats us ON us.user_id = m.user_id
                    {where}
                    GROUP BY m.user_id
                    ORDER BY last_ts DESC
                    LIMIT ?
                    """,
                    ((n, n, cap) if n else (cap,))).fetchall()
        except sqlite3.OperationalError:
            rows = []          # nothing has spoken to this install yet

    finally:
        conn.close()
    # The pictures and names of only these, not of everyone ever profiled.
    profiles = {} if snap else _profiles_for([uid for uid, *_ in rows])

    out = []
    if snap:
        from app.utils import snappeople
    for uid, name, total, last_ts in rows:
        meta = profiles.get(str(uid), {}) if not snap else {}
        out.append({
            "id": str(uid),
            "name": meta.get("display_name") or name or (snappeople.name_of(n, uid, plat) if snap else "") or str(uid),
            "username": meta.get("username", ""),
            "avatar": snappeople.avatar_url(n, uid, plat) if snap else meta.get("avatar", ""),
            "messages": total,
            "last_ts": last_ts,
        })
    return {"conversations": out}


@router.get("/api/chats/snap-picture/{account}/{chat_id}")
def snap_picture(account: int, chat_id: str):
    """A Snapchat chat's picture, as the runner saved it off the chat list (app/utils/snappeople.py)."""
    from fastapi.responses import FileResponse
    from app.utils import snappeople
    path = snappeople.picture_path(account, chat_id)
    if not path:
        raise HTTPException(status_code=404, detail="no picture")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


@router.get("/api/chats/web-picture/{platform}/{account}/{chat_id}")
def web_picture(platform: str, account: int, chat_id: str):
    """A TikTok, Instagram, X or Snapchat chat's picture, as its runner saved it off the chat list
    (app/utils/snappeople.py)."""
    from fastapi.responses import FileResponse
    from app.utils import snappeople
    if platform not in registry.BRIDGED:
        raise HTTPException(status_code=404, detail="no picture")
    path = snappeople.picture_path(account, chat_id, platform)
    if not path:
        raise HTTPException(status_code=404, detail="no picture")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


@router.get("/api/chats/tiktok-card")
async def tiktok_card(url: str = ""):
    """What a shared TikTok is, for its card in a conversation (any platform's): its caption, whose it is and its
    cover, from TikTok's public oEmbed (app/utils/tiktoklinks.py), and what the persona saw and heard in it once it
    has watched it (app/utils/tiktokwatch.py). Only TikTok links are asked about."""
    import asyncio
    from app.utils import tiktoklinks, tiktokwatch
    links = tiktoklinks.links_in(url)
    if not links or links[0] != url.strip().rstrip(".,);!?\"'"):
        raise HTTPException(status_code=400, detail="not a TikTok link")
    info = await tiktoklinks.lookup(links[0])
    if not info:
        raise HTTPException(status_code=404, detail="TikTok did not say")
    cover = info.get("thumbnail_url", "")
    vid = tiktokwatch.video_id(links[0]) or info.get("id", "")
    watched = await asyncio.to_thread(tiktokwatch.cached, vid) if vid else None
    return {
        "url": links[0],
        "title": info.get("title", ""),
        "author": info.get("author_unique_id", ""),
        "author_name": info.get("author_name", ""),
        "cover": cover if cover.startswith("https://") else "",
        "seen": (watched or {}).get("seen", ""),
        "said": (watched or {}).get("said", ""),
    }


def _post_card(url: str, found: dict, where_key: str, by_key: str) -> dict:
    """One shape for a Reddit card and an X one: they carry the same things under different names."""
    media = [m for m in (found.get("media") or []) if isinstance(m, dict) and m.get("url")]
    cover = str((media[0].get("url") if media else "") or "")
    return {
        "url": url,
        "author": str(found.get(by_key) or "").lstrip("@").removeprefix("u/"),
        "title": str(found.get("title") or "")[:300],
        "text": " ".join(str(found.get("text") or "").split())[:600],
        "where": str(found.get(where_key) or "").removeprefix("r/"),
        "score": int(found.get("score") or (found.get("counts") or {}).get("likes") or 0),
        "comments": int(found.get("comments") or (found.get("counts") or {}).get("replies") or 0),
        "cover": cover if cover.startswith("https://") else "",
        "seen": str(found.get("seen") or ""),
        "at": found.get("at") or 0,
    }


@router.get("/api/chats/reddit-card")
async def reddit_card(url: str = ""):
    """What a shared Reddit post is, for its card in a conversation (any platform's): its title, whose it is,
    which subreddit and what it scored. Reddit stopped taking new API apps and shows a signed-out visitor less
    every month, so this is what the account's own signed-in browser read (app/utils/redditwatch.py) - already
    kept, or asked for once. With no Reddit account running there is nothing to ask and no card is drawn."""
    from app.utils import redditwatch
    links = redditwatch.links(url)
    if not links or redditwatch.post_id(url) != redditwatch.post_id(links[0]):
        raise HTTPException(status_code=400, detail="not a Reddit link")
    found = redditwatch.cached(links[0]) or await redditwatch.watch(links[0])
    if not found:
        raise HTTPException(status_code=404, detail="nothing could read it")
    return _post_card(links[0], found, "subreddit", "author")


@router.get("/api/chats/x-card")
async def x_card(url: str = ""):
    """And the same for a shared X post: X's free tier cannot read one either, so it is what the account's own
    signed-in browser read (app/utils/xwatch.py)."""
    from app.utils import xwatch
    links = xwatch.links(url)
    if not links or xwatch.post_id(url) != xwatch.post_id(links[0]):
        raise HTTPException(status_code=400, detail="not an X link")
    found = xwatch.cached(links[0]) or await xwatch.watch(links[0])
    if not found:
        raise HTTPException(status_code=404, detail="nothing could read it")
    return _post_card(links[0], found, "", "handle")


@router.get("/api/chats/instagram-card")
async def instagram_card(url: str = ""):
    """What a shared Instagram post or reel is, for its card in a conversation (any platform's): its caption, whose
    it is and its picture, from the embed page anyone can read (app/utils/instagramlinks.py), and what the persona
    saw and heard in it once it has watched it (app/utils/instagramwatch.py). Only Instagram links are asked about."""
    import asyncio
    from app.utils import instagramlinks, instagramwatch
    links = instagramlinks.links_in(url)
    if not links or links[0] != url.strip().rstrip(".,);!?\"'"):
        raise HTTPException(status_code=400, detail="not an Instagram link")
    watched = await asyncio.to_thread(instagramwatch.seen_for, links[0])
    info = watched or await instagramlinks.lookup(links[0])
    if not info:
        # A story, or a post Instagram will not embed: the card says what the link is and no more.
        kind = instagramlinks.kind_of(links[0])
        if not kind:
            raise HTTPException(status_code=404, detail="Instagram did not say")
        return {"url": links[0], "kind": kind, "title": "", "author": instagramlinks.story_of(links[0])[0],
                "author_name": "", "cover": "", "seen": "", "said": "", "private": True}
    cover = str(info.get("thumbnail") or "")
    return {
        "url": links[0],
        "kind": str(info.get("kind") or instagramlinks.kind_of(links[0]) or "post"),
        "title": str(info.get("caption") or ""),
        "author": str(info.get("author") or ""),
        "author_name": str(info.get("name") or ""),
        "cover": cover if cover.startswith("https://") else "",
        "seen": str(info.get("seen") or ""),
        "said": str(info.get("said") or ""),
        "likes": int(info.get("likes") or 0),
        "views": int(info.get("views") or 0),
    }


@router.get("/api/friends")
async def friends(request: Request, target: str = ""):
    """Friend requests waiting on this account: Discord's from its API, Snapchat's read off its own requests panel,
    TikTok's message requests off its inbox."""
    tgt = _resolve_target(request, target)
    if _is_snap(tgt):
        # Read off Snapchat's own requests panel, between the bot's steps: slower than Discord's.
        result = await ipc.send_and_wait(tgt, "friends_pending", timeout=60.0)
        if result is None:
            raise HTTPException(status_code=504, detail="runner did not respond")
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail=result.get("reason", "could not read them"))
        return {"requests": result.get("requests", []), "supported": True, "target": tgt}
    result = await ipc.send_and_wait(tgt, "friends_pending", timeout=15.0)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason", "could not read them"))
    return {"requests": _stringify_ids(result.get("requests", []), "id"),
            "supported": True, "target": tgt}


@router.get("/api/chats/servers")
async def servers(request: Request, target: str = ""):
    """The servers this account is in, with the text channels it may read, under the category they sit in.

    The Chats tab lists the channels someone has spoken to it in; this is the rest of them, so one can be walked
    into and typed in whether or not anyone is waiting there. Discord's servers hold channels and come out of the
    gateway's own cache, so asking costs nothing; Telegram has no server, so its groups and the channels it
    follows are arranged the same way under the account itself. The others have nothing of the kind and say so."""
    tgt = _resolve_target(request, target)
    # Snapchat, TikTok's and Instagram's reading is slower: it goes to the account, which answers between its steps.
    result = await ipc.send_and_wait(tgt, "guilds", {}, timeout=40.0 if _is_snap(tgt) else 20.0)
    if result is None:
        raise HTTPException(status_code=504, detail="the account did not answer; is it running?")
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason", "could not read them"))
    return {"guilds": result.get("guilds", []), "supported": not result.get("unsupported"), "target": tgt}


@router.get("/api/chats/voice")
async def voice_people(request: Request, target: str = "", guild: str = "", first: str = ""):
    """Who is in each voice channel of one server, asked every few seconds while the list of channels is open. `first`:
    the channels on screen, whose names it looks for first. Discord is the only platform here with voice channels, so
    the others answer with none. Only looks: nothing joins a call."""
    tgt = _resolve_target(request, target)
    if ipc.platform_of(tgt) != "discord":
        return {"channels": {}, "supported": False, "target": tgt}
    if not guild.isdigit():
        raise HTTPException(status_code=400, detail="which server?")
    looking = [c for c in first.split(",") if c.isdigit()][:50]
    result = await ipc.send_and_wait(tgt, "voice_people", {"guild": guild, "first": looking}, timeout=12.0)
    if result is None:
        raise HTTPException(status_code=504, detail="the account did not answer; is it running?")
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason", "could not read them"))
    return {"channels": result.get("channels", {}), "supported": True, "target": tgt}


@router.post("/api/gifts/accept")
async def gift_accept(request: Request):
    """Take the Nitro gift in a message, from the Chats tab. The account itself redeems it, so it is taken by the
    account the gift was sent to; the message it is in says afterwards what became of it."""
    body = await request.json()
    code = str(body.get("code") or "").strip()
    if not code or len(code) > 64 or not code.isalnum():
        raise HTTPException(status_code=400, detail="which gift?")
    tgt = _resolve_target(request, body.get("target", ""))
    if ipc.platform_of(tgt) != "discord":
        raise HTTPException(status_code=400, detail="Nitro gifts are a Discord thing")
    result = await ipc.send_and_wait(tgt, "gift_accept", {
        "code": code, "mid": str(body.get("mid") or ""), "user_id": str(body.get("user_id") or "")}, timeout=30.0)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    return result


@router.post("/api/friends/{action}")
async def friend_action(request: Request, action: str):
    """Accept or decline a request now, instead of on the background timer. The automatic accept deliberately waits, spread over hours, so the account does not look like a script; that is right when nobody is watching and wrong when you are looking straight at the request, so this takes it immediately.

    `add`: send one, by username (the Chats tab's "Add a friend"): Discord's by its API, Snapchat's through its own
    add friends search."""
    if action not in ("accept", "decline", "add"):
        raise HTTPException(status_code=400, detail="accept, decline or add")
    body = await request.json()
    if action == "add":
        username = str(body.get("username") or "").strip().lstrip("@")
        if not username or len(username) > 64 or any(ch.isspace() for ch in username):
            raise HTTPException(status_code=400, detail="a username, without spaces")
        tgt = _resolve_target(request, body.get("target", ""))
        # iMessage's: a conversation started with a number or an email, and the first thing said in it.
        text = str(body.get("text") or "").strip()[:2000]
        result = await ipc.send_and_wait(tgt, "friend_add", {"username": username, **({"text": text} if text else {})},
                                         timeout=90.0 if _is_snap(tgt) else 25.0)
        if result is None:
            raise HTTPException(status_code=504, detail="runner did not respond")
        return result
    user_id = body.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, body.get("target", ""))
    if _is_snap(tgt):
        # A Snapchat request is known by the name it shows, there being no id to go by.
        result = await ipc.send_and_wait(tgt, f"friend_{action}", {"user_id": str(user_id)}, timeout=60.0)
        if result is None:
            raise HTTPException(status_code=504, detail="runner did not respond")
        return result
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
    if _is_snap(tgt) or _server_row_id(user_id):
        user_id = str(user_id)
    else:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="user_id must be an integer for Discord")
    result = await ipc.send_and_wait(tgt, "reply_user", {"user_id": user_id}, timeout=120.0)
    _CHATS_CACHE.pop(tgt, None)     # that person is no longer waiting
    if result is None:
        # Two minutes and no reply yet: the account is still writing it (it sends when done), almost always because
        # the model is slow on this computer. Said so, not "the runner did not respond".
        raise HTTPException(status_code=504, detail=await asyncio.to_thread(_slow_reply_reason))
    return result


def _slow_reply_reason() -> str:
    """Why a reply is taking this long, in a line: a local model too big for this computer, when that is it."""
    try:
        from app.utils import localai, localfix, providers
        from app.utils.helpers import load_config
        config = load_config()
        base = localai.settings(config)["base_url"]
        for entry in providers.plan(config)["replies"]:
            if entry["provider"] == "local":
                big = localfix.too_big(entry["model"], base)
                if big:
                    return (f"Still writing after two minutes: {entry['model']} is too big for this computer, "
                            f"{localfix.too_big_words(big)}. It sends when it's done.")
                break
    except Exception:
        pass
    return "Still writing after two minutes. It sends when it's done."


def _server_row_id(raw) -> bool:
    """A server conversation's row, "ch<channel id>", rather than a person."""
    s = str(raw or "")
    return s.startswith("ch") and s[2:].isdigit()


def _user_id_for(tgt, raw):
    """Discord ids are ints on the runner's side; Snapchat and TikTok chat ids and server rows ("ch<channel id>") stay
    strings."""
    if _is_snap(tgt) or _server_row_id(raw):
        return str(raw)
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="user_id must be an integer for Discord")


@router.post("/api/chats/cancel")
async def cancel_reply(request: Request):
    """Stop the reply the bot has scheduled for someone, before it is sent.

    They stay on the waiting list, so they can still be answered by hand.
    """
    body = await request.json()
    if body.get("user_id") is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, body.get("target", ""))
    # No cache drop: the runner pushes the change, and apply_chat_event puts it in the cache.
    result = await ipc.send_and_wait(tgt, "cancel_reply",
                                     {"user_id": _user_id_for(tgt, body["user_id"])}, timeout=10.0)
    if result is None:
        raise HTTPException(status_code=504, detail="runner did not respond")
    return result


@router.post("/api/chats/react")
async def react(request: Request):
    """React to a message in a conversation, as the account, or take the reaction back ("remove"). Discord takes any
    emoji (a custom one as "<:name:id>"); Snapchat has eight of its own, picked the way a person does, on its page."""
    body = await request.json()
    mid, emoji = str(body.get("mid") or ""), str(body.get("emoji") or "").strip()
    if body.get("user_id") is None or not mid or not emoji:
        raise HTTPException(status_code=400, detail="user_id, mid and emoji required")
    if mid.startswith("local-"):
        raise HTTPException(status_code=400, detail="that message is still being sent")
    tgt = _resolve_target(request, body.get("target", ""))
    result = await ipc.send_and_wait(tgt, "react", {"user_id": _user_id_for(tgt, body["user_id"]), "mid": mid,
                                                   "emoji": emoji, "remove": bool(body.get("remove"))}, timeout=70.0)
    if result is None:
        raise HTTPException(status_code=504, detail="the account did not answer, it may be stopped or busy")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "it did not take")
    return result


@router.post("/api/chats/message")
async def chat_message(request: Request):
    """Fetch someone's last message in full, pictures included, for a row that only has its text."""
    body = await request.json()
    if body.get("user_id") is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, body.get("target", ""))
    if _is_snap(tgt):
        from app.utils.compat import FEATURES as _F
        raise HTTPException(status_code=400,
                            detail=f"{_F.get(_web_platform(tgt), 'Snapchat')} messages cannot be fetched again")
    result = await ipc.send_and_wait(tgt, "chat_message",
                                     {"user_id": _user_id_for(tgt, body["user_id"])}, timeout=25.0)
    if result is None:
        raise HTTPException(status_code=504, detail="the account did not answer, it may be stopped")
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason", "could not fetch it"))
    return result


@router.post("/api/chats/history")
async def chat_history(request: Request):
    """The last messages of a conversation, both sides, oldest first."""
    body = await request.json()
    if body.get("user_id") is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, body.get("target", ""))
    uid = _user_id_for(tgt, body["user_id"])
    limit = int(body.get("limit") or 20)
    # Snapchat's is read off its page, between the bot's own steps: it can take longer.
    result = await ipc.send_and_wait(tgt, "chat_history", {"user_id": uid, "limit": limit},
                                     timeout=60.0 if _is_snap(tgt) else 25.0)
    if result is None:
        # The account is stopped: what the chat log kept of the conversation, read only.
        from app.utils import chatlog
        try:
            kept = chatlog.conversation(chatlog.log_account(tgt), uid, max(5, min(200, limit)))
        except Exception:
            kept = []
        if kept:
            return {"ok": True, "messages": kept, "from_log": True, "offline": True}
        raise HTTPException(status_code=504, detail="the account did not answer, it may be stopped")
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason", "could not read it"))
    return result


# ── Searching a DM, what was shared in it, and jumping back to a message ─────
# What is kept (app/utils/chatlog.py) is searched as you type, deleted messages included; Discord's own search, for
# everything older, only when asked (Enter, or "Search all of Discord"), since it is slow and limited.

def _dm_of(request: Request, body: dict):
    """The account, the person, and the account their conversation is kept under (chatlog.log_account), for what
    only a one-to-one conversation has here. Snapchat's included: its conversations are kept too."""
    from app.utils.chatlog import log_account
    if body.get("user_id") is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, body.get("target", ""))
    if _server_row_id(body["user_id"]):
        raise HTTPException(status_code=400, detail="only one-to-one chats can be searched")
    return tgt, _user_id_for(tgt, body["user_id"]), log_account(tgt)


def _is_snap(tgt) -> bool:
    """An account the shared bridge runs, Snapchat's, TikTok's, Instagram's, X's, Reddit's, Minecraft's or
    iMessage's: slower to answer, known by string ids, and its conversations read from what is kept."""
    return isinstance(tgt, str) and tgt.startswith(("snap", "tiktok", "insta", "mc", "imsg", "tg", "x",
                                                    "reddit", "wa"))


def _query(body: dict) -> dict:
    """A search as the Chats tab sends it: words, from whom, with what, between when (Unix seconds), in what order."""
    from app.utils.chatlog import HAS

    def when(key):
        try:
            return float(body[key]) if body.get(key) is not None else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} must be a time in seconds")

    mine = body.get("mine")
    return {
        "words": [str(w)[:100] for w in (body.get("words") or []) if str(w).strip()][:12],
        "mine": None if mine is None else bool(mine),
        "has": [h for h in (body.get("has") or []) if h in HAS],
        "before": when("before"),
        "after": when("after"),
        "sort": body.get("sort") if body.get("sort") in ("newest", "oldest", "relevant") else "newest",
    }


def _number(body: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(body.get(key) or default)))
    except (TypeError, ValueError):
        return default


@router.post("/api/chats/search")
async def chat_search(request: Request):
    """One DM searched in what is kept of it: instant, deleted messages included. Says how far back that reaches."""
    from app.utils import chatlog
    body = await request.json()
    tgt, uid, acct = _dm_of(request, body)
    q = _query(body)
    found, total = await asyncio.to_thread(
        chatlog.search, acct, uid, q["words"], q["mine"], q["has"], q["before"], q["after"], q["sort"],
        _number(body, "limit", 50, 1, 100), _number(body, "offset", 0, 0, 100000))
    kept, since = await asyncio.to_thread(chatlog.span, acct, uid)
    return {"ok": True, "messages": found, "total": total, "kept": kept, "since": since}


@router.post("/api/chats/search-discord")
async def chat_search_discord(request: Request):
    """One DM searched by Discord: all of it, 25 at a time."""
    body = await request.json()
    tgt, uid, acct = _dm_of(request, body)
    if _is_snap(tgt):
        raise HTTPException(status_code=400, detail="Only Discord has a search of its own: what is kept is searched")
    q = _query(body)
    if not (q["words"] or q["has"] or q["mine"] is not None or q["before"] or q["after"]):
        raise HTTPException(status_code=400, detail="nothing to search for")
    cursor = str(body.get("cursor") or "")
    payload = {"user_id": uid, **q, "cursor": cursor if cursor.isdigit() else None,
               "offset": _number(body, "offset", 0, 0, 5000)}
    result = await ipc.send_and_wait(tgt, "chat_search", payload, timeout=40.0)
    if result is None:
        raise HTTPException(status_code=504, detail="the account did not answer; is it running?")
    if not result.get("ok"):
        raise HTTPException(status_code=409 if result.get("retry") else 502, detail=result.get("reason") or "could not search")
    return result


@router.post("/api/chats/search-all")
async def chat_search_all(request: Request):
    """Every DM kept for an account, searched at once: what the search over the Chats list finds in messages. With
    the names and pictures of whose conversations they are."""
    from app.utils import chatlog
    body = await request.json()
    tgt = _resolve_target(request, body.get("target", ""))
    q = _query(body)
    found = await asyncio.to_thread(chatlog.search_all, chatlog.log_account(tgt), q["words"], q["mine"], q["has"],
                                    q["before"], q["after"], _number(body, "limit", 60, 1, 200))
    if _is_snap(tgt):
        # Not people with a Discord profile: named and pictured from its own chat list.
        from app.utils import snappeople
        n, plat = _snap_number(tgt), _web_platform(tgt)

        def named() -> dict:
            return {u: {"display_name": snappeople.name_of(n, u, plat), "username": "",
                        "avatar": snappeople.avatar_url(n, u, plat)}
                    for u in {m["uid"] for m in found}}

        return {"ok": True, "messages": found, "people": await asyncio.to_thread(named)}
    return {"ok": True, "messages": found, "people": await asyncio.to_thread(_profiles_for, {m["uid"] for m in found})}


@router.post("/api/chats/shared")
async def chat_shared(request: Request):
    """What was shared in a DM, newest first: "media", "files" or "links". From what is kept; older ones come from
    Discord's search (has:image ...) when asked."""
    from app.utils import chatlog
    body = await request.json()
    tgt, uid, acct = _dm_of(request, body)
    kind = body.get("kind")
    if kind not in ("media", "files", "links"):
        raise HTTPException(status_code=400, detail="kind is media, files or links")
    items = await asyncio.to_thread(chatlog.shared, acct, uid, kind)
    kept, since = await asyncio.to_thread(chatlog.span, acct, uid)
    return {"ok": True, "items": items, "kept": kept, "since": since}


@router.post("/api/chats/around")
async def chat_around(request: Request):
    """Part of a conversation near one message, oldest first: either side of it ("around", jumping to it from a
    search), before it ("older", scrolling back), after it ("newer", scrolling on towards now), or the very first
    messages ("first"). Read from Discord while the account runs, since only Discord has all of it, with the deleted
    messages kept here put back in; from what is kept when it is stopped, and always for Snapchat."""
    from app.utils import chatlog
    body = await request.json()
    tgt, uid, acct = _dm_of(request, body)
    direction = body.get("dir") or "around"
    if direction not in ("around", "older", "newer", "first"):
        raise HTTPException(status_code=400, detail="dir is around, older, newer or first")
    mid = str(body.get("mid") or "")
    if direction != "first" and not mid:
        raise HTTPException(status_code=400, detail="mid required")
    limit = _number(body, "limit", 50, 5, 100)

    async def kept():
        found = await asyncio.to_thread(chatlog.window, acct, uid, mid or None, direction, limit)
        return {"ok": True, "messages": found or [], "more": len(found or []) >= limit, "from_log": True,
                "missing": found is None}

    if _is_snap(tgt) or (direction != "first" and not mid.isdigit()):
        return await kept()
    result = await ipc.send_and_wait(tgt, "chat_window", {"user_id": uid, "mid": mid or None, "dir": direction,
                                                          "limit": limit}, timeout=25.0)
    if result is None:
        return {**(await kept()), "offline": True}
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("reason") or "could not read it")
    found = result.get("messages") or []
    if found:
        # Deleted on Discord, so it no longer has them; kept here, so they are shown where they were.
        have = {m.get("mid") for m in found}
        lo, hi = found[0]["ts"], found[-1]["ts"]
        # The very start of the conversation reached: any deleted before it belong here too; the present, after.
        if direction == "first" or (direction == "older" and not result.get("more")):
            lo = 0.0
        if direction == "newer" and not result.get("more"):
            hi = time.time()
        gone =[m for m in await asyncio.to_thread(chatlog.deleted_between, acct, uid, lo, hi) if m["mid"] not in have]
        if gone:
            found = sorted(found + gone, key=lambda m: m["ts"])
    return {**result, "messages": found}


@router.post("/api/chats/export")
async def chat_export(request: Request):
    """Everything kept of a conversation as plain text, oldest first, to save as a file."""
    from app.utils import chatlog
    body = await request.json()
    tgt, uid, acct = _dm_of(request, body)
    messages = await asyncio.to_thread(chatlog.conversation, acct, uid, chatlog.KEEP + 100)
    text = chatlog.as_text(messages, str(body.get("me") or "Me")[:80], str(body.get("name") or uid)[:80])
    return {"ok": True, "text": text, "count": len(messages)}


@router.post("/api/chats/send")
async def send_message(request: Request):
    """Send a message as this account, typed in the Chats tab. A reply the bot had lined up for them is dropped:
    you answered them yourself."""
    body = await request.json()
    uid, text = body.get("user_id"), str(body.get("text") or "").strip()
    # Pictures pasted into the composer ride along base64'd; a message may be
    # only a picture, so text is no longer required on its own.
    files = body.get("files") or []
    if not isinstance(files, list) or len(files) > 4:
        raise HTTPException(status_code=400, detail="up to 4 files in one message")
    if uid is None or (not text and not files):
        raise HTTPException(status_code=400, detail="user_id and something to send are required")
    tgt = _resolve_target(request, str(body.get("target") or ""))
    payload = {"user_id": str(uid), "text": text}
    if files:
        payload["files"] = files
    # A reply to one message of theirs (or of its own): Discord's own reply, Snapchat's and TikTok's Reply on it.
    reply_to = str(body.get("reply_to") or "").strip()
    if reply_to:
        if len(reply_to) > 80 or not reply_to.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(status_code=400, detail="which message?")
        payload["reply_to"] = reply_to
    # Uploading takes longer than typing does; Snapchat types it out, between the bot's own steps.
    wait = 160.0 if _is_snap(tgt) else (90.0 if files else 30.0)
    result = await ipc.send_and_wait(tgt, "send_message", payload, timeout=wait)
    if result is None:
        raise HTTPException(status_code=504, detail="the account did not answer; is it running?")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "could not send it")
    return result


@router.get("/api/chats/ignored")
def ignored_list(request: Request, target: str = ""):
    """Everyone this account ignores, with names and pictures from the profile cache. Read from the
    database, so it shows even while the account is stopped. Plain def: it is sqlite."""
    tgt = _resolve_target(request, target)
    from app.utils import db
    if _is_snap(tgt):
        # Named and pictured as the Chats tab names them, not by their chat ids.
        from app.utils import snappeople
        ids = [str(i) for i in db.get_ignored_users_web(_web_platform(tgt))]
        info = snappeople.describe(ids)
        return {"people": [{"id": i, "name": (info.get(i) or {}).get("name") or "Someone", "username": "",
                            "avatar": (info.get(i) or {}).get("avatar") or ""} for i in ids]}
    ids = [str(i) for i in db.get_ignored_users()]
    profiles = _profiles_for(ids)
    people = []
    for i in ids:
        meta = profiles.get(i) or {}
        people.append({"id": i, "name": meta.get("display_name") or meta.get("username") or i,
                       "username": meta.get("username", ""), "avatar": meta.get("avatar", "")})
    return {"people": people}


@router.post("/api/chats/ignore/set")
async def ignore_set(request: Request):
    """Ignore someone, or stop ignoring them. Written to the database first, so it holds whether or not
    the account is running, then passed to the running account, which stops any reply it had lined up."""
    body = await request.json()
    if body.get("user_id") is None:
        raise HTTPException(status_code=400, detail="user_id required")
    want = bool(body.get("ignored", True))
    web_id = str(body.get("target") or "")
    tgt = _resolve_target(request, web_id)
    uid = _user_id_for(tgt, body["user_id"])
    from app.utils import db
    snap = _is_snap(tgt)
    if snap:
        (db.add_ignored_user_web if want else db.remove_ignored_user_web)(_web_platform(tgt), str(uid))
    else:
        (db.add_ignored_user if want else db.remove_ignored_user)(int(uid))
    await ipc.send_and_wait(tgt, "ignore_add" if want else "ignore_remove", {"user_id": uid}, timeout=6.0)
    if not snap and web_id:
        evt = {"t": "ignored", "uid": str(uid), "ignored": want, "target": web_id}
        apply_chat_event(web_id, evt)
        try:
            from app.web.logbus import bus
            bus.event("chat", evt)
        except Exception:
            pass
    return {"ok": True, "ignored": want}


@router.post("/api/chats/ignore")
async def toggle_ignore(request: Request):
    """Stop (or start again) the bot answering someone. Returns the new state."""
    body = await request.json()
    if body.get("user_id") is None:
        raise HTTPException(status_code=400, detail="user_id required")
    tgt = _resolve_target(request, body.get("target", ""))
    # No cache drop: the runner pushes the change, and apply_chat_event puts it in the cache.
    result = await ipc.send_and_wait(tgt, "ignore_toggle",
                                     {"user_id": _user_id_for(tgt, body["user_id"])}, timeout=10.0)
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


def _memory_persona(persona: str) -> str:
    """The persona whose memory a request is about (?persona=), Default when none is named."""
    from app.utils import personas
    pid = str(persona or "").strip() or personas.DEFAULT
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    return pid


def _memory_changed(request: Request, uid: str, persona: str) -> None:
    """The running accounts speaking as this persona read this person's memory again on their next message: they
    hold it, and an edit here never reached them before."""
    from app.web import live
    live.push(request, "memory_changed", {"user_id": uid}, persona=persona)


@router.get("/api/memory")
def memory_list(request: Request, persona: str = ""):
    """Everyone one persona remembers something about, with enough to sort by. The page used to show a name and a fact count, which is not enough to know who is worth opening. Message counts, the last time they spoke and whether they have their own persona all come from tables that are already there."""
    # Plain def, so FastAPI runs it on a thread: it reads the whole memory table, and on the event loop that held up every other request meanwhile.
    pid = _memory_persona(persona)
    from app.utils.db import ensure_persona_schema
    ensure_persona_schema()
    conn = _conn()
    try:
        try:
            rows = conn.execute(
                """
                SELECT m.user_id, m.key, m.value, COALESCE(us.username, '') as username, COALESCE(m.learned_at, 0)
                FROM user_memory m
                LEFT JOIN user_stats us ON us.user_id = m.user_id
                WHERE m.persona = ?
                ORDER BY m.user_id, m.key
                """, (pid,)
            ).fetchall()
        except sqlite3.OperationalError:
            # A table with no learned_at (it could not be added): every fact's time unknown.
            try:
                rows = [(*r, 0) for r in conn.execute(
                    "SELECT m.user_id, m.key, m.value, COALESCE(us.username, '') FROM user_memory m "
                    "LEFT JOIN user_stats us ON us.user_id = m.user_id WHERE m.persona = ? ORDER BY m.user_id, m.key",
                    (pid,)).fetchall()]
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
    for uid, key, value, username, learned in rows:
        uid = str(uid)
        entry = users.setdefault(uid, {
            "user_id": uid, "username": username, "facts": {}, "persona": "", "learned_at": 0, "learned": "",
        })
        # The persona rides in the same table under a reserved key, so it has to be split back out rather than listed as a fact.
        if key == "__persona__":
            entry["persona"] = value
        else:
            entry["facts"][key] = value
            # What it learned about them last, and when.
            if learned and learned > entry["learned_at"]:
                entry["learned_at"] = learned
                entry["learned"] = key

    out = []
    for uid, entry in users.items():
        profile = profiles.get(uid) or {}
        entry["display_name"] = profile.get("name", "")
        # A face makes a list of names scannable in a way that a list of names is not.
        entry["avatar"] = profile.get("avatar", "")
        entry["messages"] = stats.get(uid, {}).get("messages", 0)
        entry["first_seen"] = stats.get(uid, {}).get("first_seen", 0)
        entry["last_seen"] = last.get(uid, 0)
        entry["fact_count"] = len(entry["facts"])
        out.append(entry)
    # Snapchat's and TikTok's people (their ids are chat ids, not numbers): named, pictured and counted from what their
    # runners read and the bot logged, as Discord's are from the profile cache.
    snap_ids = [e["user_id"] for e in out if not str(e["user_id"]).isdigit()]
    if snap_ids:
        from app.utils import snappeople
        info = snappeople.describe(snap_ids)
        for e in out:
            i = info.get(e["user_id"])
            if i:
                e["display_name"] = e.get("display_name") or i["name"]
                e["avatar"] = e.get("avatar") or i["avatar"]
                e["messages"] = e.get("messages") or i["messages"]
                e["first_seen"] = e.get("first_seen") or i["first_seen"]
                e["last_seen"] = e.get("last_seen") or i["last_seen"]
                e["platform"] = i.get("platform") or "snapchat"
    # The same person on another platform: their ids, so the page can show who, and unlink one that was wrong.
    from app.utils.memory import linked_people as _groups

    linked = _groups()
    keys_of = {str(e["user_id"]): set(e["facts"]) for e in out}
    for e in out:
        e["same_as"] = linked.get(str(e["user_id"]), [])
        # Linked, what it knows about them is the whole person's, so the count beside their name is too: the same
        # number the facts below it come to, rather than this one account's share of them.
        if e["same_as"]:
            whole = set(e["facts"])
            for other in e["same_as"]:
                whole |= keys_of.get(other, set())
            e["fact_count"] = len(whole)
    out.sort(key=lambda u: (u["last_seen"], u["fact_count"]), reverse=True)
    # The last thing it learned about anyone: what the brain at the top of the page opens.
    newest = max(out, key=lambda u: u["learned_at"], default=None)
    latest = None
    if newest and newest["learned_at"]:
        key = newest["learned"]
        latest = {"user_id": newest["user_id"], "name": newest.get("display_name") or newest.get("username") or "",
                  "key": key, "value": newest["facts"].get(key, ""), "at": newest["learned_at"]}
    return {"users": out, "latest": latest}


# Linking is about who someone is, not about one persona's memory of them, and the whole point of it is that it
# reaches the other platforms, so every running account is told, whoever it speaks as.
_EVERY_PLATFORM = registry.IDS


def _person_changed(request: Request, uid: str) -> None:
    from app.web import live
    live.push(request, "memory_changed", {"user_id": uid}, persona=None, platforms=_EVERY_PLATFORM)


@router.post("/api/memory/link")
async def memory_link(request: Request):
    """Say two accounts are one person. From then on what is remembered about either is remembered about both, on
    every persona: who someone is does not change with who is talking to them.

    Nothing is merged on disk, so unlinking gives each of them back exactly what it had."""
    import asyncio as _aio
    from app.utils.memory import link_people
    body = await request.json()
    a, b = str(body.get("user_id") or "").strip(), str(body.get("other_id") or "").strip()
    if not a or not b:
        raise HTTPException(status_code=400, detail="which two?")
    try:
        ids = await _aio.to_thread(link_people, a, b)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Both sides are now one person to every running account, whatever persona it speaks as.
    for uid in ids:
        _person_changed(request, uid)
    return {"ok": True, "group": ids}


@router.post("/api/memory/unlink")
async def memory_unlink(request: Request):
    """Take one account back out of a person: it was not them after all. It keeps its own facts."""
    import asyncio as _aio
    from app.utils.memory import person_ids, unlink_person
    body = await request.json()
    uid = str(body.get("user_id") or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="which one?")
    was = await _aio.to_thread(person_ids, uid)
    await _aio.to_thread(unlink_person, uid)
    for other in was or [uid]:
        _person_changed(request, other)
    return {"ok": True}


@router.get("/api/memory/{uid}")
def memory_get(request: Request, uid: str, persona: str = ""):
    # Plain def: the database is read on FastAPI's threadpool, not on the event loop.
    from app.utils.memory import get_memory, get_persona
    pid = _memory_persona(persona)
    key = int(uid) if uid.isdigit() else uid
    return {"facts": get_memory(key, persona=pid), "persona": get_persona(key, persona=pid)}


@router.put("/api/memory/{uid}")
async def memory_put(request: Request, uid: str, persona: str = ""):
    """A fact, or this person's own tone (body "persona": the text), in what one persona (?persona=) remembers."""
    import asyncio as _aio
    pid = _memory_persona(persona)
    body = await request.json()
    key = body.get("key")
    value = body.get("value", "")
    tone = body.get("persona")

    def write():
        from app.utils.memory import delete_memory, person_ids, set_memory, clear_persona, set_persona
        if key:
            # Written by hand: not something the bot learned.
            set_memory(uid, key, str(value), persona=pid, learned=False)
            # On a linked person the same key may also sit under one of their other accounts, with a time on it;
            # that one would win the next read and quietly undo this. What you typed is the answer, so it goes.
            for other in (person_ids(uid) or [])[1:]:
                delete_memory(other, key, persona=pid)
        if tone is not None:
            if tone:
                set_persona(uid, tone, persona=pid)
            else:
                clear_persona(uid, persona=pid)

    await _aio.to_thread(write)
    _memory_changed(request, uid, pid)
    return {"ok": True}


@router.delete("/api/memory/{uid}")
async def memory_delete(request: Request, uid: str, persona: str = ""):
    import asyncio as _aio
    pid = _memory_persona(persona)
    body = await request.json()
    key = body.get("key", "")

    def forget():
        from app.utils.memory import delete_memory, person_ids
        # One fact can have been learned on any of the accounts that are this person: it goes from all of them, or
        # the next read would bring it straight back from the other one.
        whole = person_ids(uid) or [uid]
        if key:
            for one in whole:
                delete_memory(one, key, persona=pid)
            return
        from app.utils.memory import clear_memory
        for one in whole:
            clear_memory(one, persona=pid)
            # Forgetting someone includes what they talked about.
            try:
                from app.utils.db import delete_summary
                delete_summary(one, persona=pid)
            except Exception:
                pass

    # A write to the database, on a thread rather than holding the event loop while it waits for the lock.
    await _aio.to_thread(forget)
    _memory_changed(request, uid, pid)
    return {"ok": True}


# ── Conversation summary ── the card on the right of the Memory page: what you and this person have been talking about, written from the last few messages when you open them.
_SUMMARY_DEFAULTS = {
    "enabled": True,
    "messages": 20,
    "length": "medium",
    "language": "auto",
    "include_my_messages": True,
    "refresh_minutes": 30,
}
# One generation per person at a time: clicking someone twice, or the page and a retry landing together, must not ask the model twice for one answer.
_summary_locks: dict = {}


def _summary_settings() -> dict:
    """bot.memory_summary, with every missing key at its default. An existing config.yaml predates this section, and none of it may be required for the card to work."""
    from app.utils.helpers import load_config
    raw = ((load_config().get("bot") or {}).get("memory_summary")) or {}
    out = dict(_SUMMARY_DEFAULTS)
    out.update({k: v for k, v in raw.items() if v is not None})
    try:
        out["messages"] = max(5, min(100, int(out["messages"])))
    except (TypeError, ValueError):
        out["messages"] = _SUMMARY_DEFAULTS["messages"]
    try:
        out["refresh_minutes"] = max(0, int(out["refresh_minutes"]))
    except (TypeError, ValueError):
        out["refresh_minutes"] = _SUMMARY_DEFAULTS["refresh_minutes"]
    if out["length"] not in ("short", "medium", "detailed"):
        out["length"] = "medium"
    return out


# The shape summaries are written in. Part of the signature, so a new shape makes every stored one stale and each is rewritten the next time it is opened: v2 is the headline and labelled points, instead of a paragraph.
_SUMMARY_FORMAT = "v2"


def _summary_sig(s: dict) -> str:
    """What a stored summary was written under. A change means it is stale."""
    return (f"{_SUMMARY_FORMAT}|{s['messages']}|{s['length']}|{s['language']}"
            f"|{int(bool(s['include_my_messages']))}")


def _summary_out(row: dict, cached: bool, stale: bool = False, reason: str = "") -> dict:
    out = {"ok": True, "enabled": True, "summary": row["summary"],
           "generated_at": row["generated_at"], "count": row.get("message_count", 0),
           "source": row.get("source", ""), "recent": row.get("recent") or [],
           "cached": cached, "stale": stale}
    if reason:
        out["reason"] = reason
    return out


@router.get("/api/memory/{uid}/summary")
async def memory_summary(request: Request, uid: str, force: bool = False, cached: bool = False, persona: str = ""):
    """The summary for one person: the stored one while it is fresh, a new one from a running account when it is not (or when `force` is set). With `cached`, only ever the stored one, however old, as long as it was written under the current settings: Big Picture asks that way first for everyone it might show, since that costs nothing, and writes new ones only for the few who have none.

    Each persona has its own (?persona=, Default when none), written by an account speaking as it. Asked for only
    from the cache with no persona named, the newest by any persona is given."""
    import asyncio as _aio
    import time as _t
    from functools import partial
    from app.utils import personas
    from app.utils.db import get_latest_summary, get_summary, set_summary

    s = _summary_settings()
    if not s.get("enabled", True):
        return {"ok": False, "enabled": False}
    sig = _summary_sig(s)
    named = bool(str(persona or "").strip())
    pid = _memory_persona(persona)
    get_one = partial(get_summary, persona=pid)

    # The database on a thread: Big Picture asks for a dozen of these at once, and each read on the event loop held
    # every other page for as long as a bot runner's write did.
    stored = await _aio.to_thread(get_one if named or not cached else get_latest_summary, uid)
    if cached and not force:
        if stored is not None and stored.get("settings_sig") == sig:
            return _summary_out(stored, cached=True,
                                stale=_t.time() - stored["generated_at"] >= s["refresh_minutes"] * 60)
        return {"ok": False, "enabled": True, "missing": True, "reason": "No summary written yet."}
    fresh = (stored is not None and stored.get("settings_sig") == sig
             and _t.time() - stored["generated_at"] < s["refresh_minutes"] * 60)
    if fresh and not force:
        return _summary_out(stored, cached=True)

    lock = _summary_locks.setdefault((pid, uid), _aio.Lock())
    # Only a request that had to wait joins the other one's answer: that is a double click, or the page and a retry landing together. A time window instead ("written in the last few seconds") also swallowed a rewrite nobody else was doing, so refresh_minutes 0 did not always rewrite.
    waited = lock.locked()
    async with lock:
        if waited and not force:
            again = await _aio.to_thread(get_one, uid)
            if again and again.get("settings_sig") == sig:
                return _summary_out(again, cached=True)

        # A Discord id is a number; a Snapchat or TikTok chat id is not. Each account only knows its own platform's
        # conversations. (snappeople.platform_of_user's rule, said here: nothing on this loop calls into snappeople.)
        want_platform = ("discord" if str(uid).isdigit() else "tiktok" if str(uid).startswith("tt_")
                         else "instagram" if str(uid).startswith(("ig_", "igg_"))
                         else "minecraft" if str(uid).startswith(("mc_", "mcs_"))
                         else "imessage" if str(uid).startswith(("im_", "img_"))
                         else "telegram" if str(uid).startswith(("tg_", "tgg_"))
                         else "x" if str(uid).startswith(("x_", "xg_"))
                         else "reddit" if str(uid).startswith(("rd_", "rdg_"))
                         else "whatsapp" if str(uid).startswith(("wa_", "wag_")) else "snapchat")
        want_snap = want_platform != "discord"
        payload = {
            "user_id": uid if want_snap else int(uid),
            "count": s["messages"],
            "length": s["length"],
            "language": s["language"],
            "include_mine": bool(s["include_my_messages"]),
        }
        reason = "No account is running to read this conversation."
        try:
            targets = ipc.discover_targets()
        except Exception:
            targets = {}
        for web_id, meta in targets.items():
            target = meta["target"]
            if ipc.platform_of(target) != want_platform:
                continue
            # Only an account speaking as this persona writes its summary: another's is another person's view.
            if personas.persona_of(web_id) != pid:
                if reason.startswith("No account"):
                    reason = f"No account speaking as {(personas.get(pid) or {}).get('name', pid)} is running."
                continue
            result = await ipc.send_and_wait(target, "summarize_user", payload, timeout=90.0)
            if result and result.get("ok") and result.get("summary"):
                await _aio.to_thread(partial(set_summary, persona=pid), uid, result["summary"], result.get("count", 0),
                                     sig, result.get("source", ""), result.get("recent"))
                # Read back rather than echoed, so the lines are the ones kept: trimmed and checked the same way every time.
                return _summary_out(await _aio.to_thread(get_one, uid), cached=False)
            if result and result.get("reason"):
                reason = result["reason"]
            elif result is None:
                reason = "The account did not answer in time."

    # Nothing new could be written. The last one is still worth showing, as long as it says it is old.
    if stored:
        return _summary_out(stored, cached=True, stale=True, reason=reason)
    return {"ok": False, "enabled": True, "reason": reason}
