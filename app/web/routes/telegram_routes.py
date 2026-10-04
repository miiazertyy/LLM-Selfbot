"""app/web/routes/telegram_routes.py - the Telegram page: connecting the control bot, and checking it works.

Setting it up used to mean finding two values and typing them into config/.env
by hand: a token from @BotFather, and your own numeric Telegram ID, which
Telegram shows nowhere. The page walks through it instead. The token is
checked with Telegram before it is saved (and names the bot it belongs to),
your ID is read off a message you send the bot, and a test message proves the
two fit together.

Telegram is asked directly, over its Bot API, so none of this needs the
controller to be running, or python-telegram-bot. The one thing that cannot
be done while it runs is reading the bot's messages (Telegram lets one reader
at a time), which is only needed while there is no owner, when it does not run.
"""

import asyncio
import hashlib
import time

from fastapi import APIRouter, HTTPException, Request

from app.telegram_bot import commands
from app.utils.credentials import real, real_int
from app.web.envfile import read_env, reload_into_process, write_env

router = APIRouter(tags=["telegram"])

_API = "https://api.telegram.org/bot{token}/{method}"


class _Refused(Exception):
    """Telegram answered, and said no."""


# What Telegram says, in the words the page shows.
_PLAIN = [
    ("unauthorized", "Telegram doesn't know that token. Copy it again from @BotFather."),
    ("not found", "Telegram doesn't know that token. Copy it again from @BotFather."),
    ("chat not found", "Telegram can't find you yet. Send your bot any message, then try again."),
    ("bot was blocked", "You've blocked the bot. Unblock it in Telegram, then try again."),
    ("conflict", "The controller is reading the bot's messages right now. Type your ID instead."),
    ("terminated by other getupdates", "The controller is reading the bot's messages right now. Type your ID instead."),
]


def _plain(text: str) -> str:
    low = (text or "").lower()
    # The more specific phrases first: "chat not found" before "not found".
    for key, said in sorted(_PLAIN, key=lambda kv: -len(kv[0])):
        if key in low:
            return said
    return text or "Telegram said no."


def _call(token: str, method: str, params: dict | None = None, timeout: float = 10.0):
    import httpx
    try:
        r = httpx.post(_API.format(token=token, method=method), json=params or {}, timeout=timeout)
    except Exception:
        raise _Refused("Couldn't reach Telegram. Check the connection and try again.")
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code == 404:
        raise _Refused(_plain("unauthorized"))
    if not data.get("ok"):
        raise _Refused(_plain(data.get("description") or f"HTTP {r.status_code}"))
    return data.get("result")


def _looks_like_token(token: str) -> bool:
    head, _, tail = (token or "").partition(":")
    return head.isdigit() and len(tail) >= 20


# Who a token belongs to, kept for a while: the page asks every time it opens.
_me_cache: dict[str, tuple[float, dict]] = {}
_ME_TTL = 600.0


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _bot(me: dict) -> dict:
    return {"id": me.get("id"), "username": me.get("username") or "",
            "name": me.get("first_name") or me.get("username") or "Your bot"}


def _me(token: str, fresh: bool = False) -> dict:
    k = _key(token)
    hit = _me_cache.get(k)
    if hit and not fresh and time.time() - hit[0] < _ME_TTL:
        return hit[1]
    bot = _bot(_call(token, "getMe") or {})
    _me_cache[k] = (time.time(), bot)
    return bot


def _state(request: Request) -> dict:
    """The controller as the supervisor sees it."""
    sup = getattr(request.app.state, "supervisor", None)
    try:
        child = next((c for c in (sup.status() if sup else []) if c.get("id") == "telegram"), None)
    except Exception:
        child = None
    return {"state": (child or {}).get("state") or "stopped", "uptime": (child or {}).get("uptime", 0)}


def _enabled() -> bool:
    from app.utils.helpers import load_config
    try:
        return bool(((load_config() or {}).get("services", {}) or {}).get("telegram", {}).get("enabled", True))
    except (Exception, SystemExit):         # load_config exits when there is no config at all
        return True


@router.get("/api/telegram")
def telegram_status(request: Request):
    token = real("TELEGRAM_BOT_TOKEN")
    owner = real_int("TELEGRAM_OWNER_ID")
    hit = _me_cache.get(_key(token)) if token else None
    return {
        "token_set": bool(token),
        "token_hint": f"…{token[-4:]}" if token else "",
        "owner_id": str(owner) if owner else "",
        "enabled": _enabled(),
        # Who the token belongs to, when that has been asked recently; the page asks (check) when it is not.
        "bot": hit[1] if hit and time.time() - hit[0] < _ME_TTL else None,
        **_state(request),
    }


@router.post("/api/telegram/check")
async def telegram_check(request: Request):
    """Whose bot a token is: the one typed, or the saved one."""
    body = await _body(request)
    token = str(body.get("token") or "").strip() or real("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "reason": "No token yet."}
    if not _looks_like_token(token):
        return {"ok": False, "reason": "That doesn't look like a bot token. It's a number, a colon, then letters."}
    try:
        return {"ok": True, "bot": await asyncio.to_thread(_me, token, True)}
    except _Refused as e:
        return {"ok": False, "reason": str(e)}


@router.post("/api/telegram/token")
async def telegram_token(request: Request):
    """Save a token, once Telegram has said whose it is."""
    body = await _body(request)
    token = str(body.get("token") or "").strip()
    if not _looks_like_token(token):
        raise HTTPException(status_code=400, detail="That doesn't look like a bot token. It's a number, a colon, then letters.")
    try:
        bot = await asyncio.to_thread(_me, token, True)
    except _Refused as e:
        raise HTTPException(status_code=400, detail=str(e))
    _save("TELEGRAM_BOT_TOKEN", token)
    await _apply(request)
    return {"ok": True, "bot": bot}


@router.post("/api/telegram/find-owner")
async def telegram_find_owner(request: Request):
    """The people who have messaged the bot lately, newest first: one of them is you."""
    token = real("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "reason": "Add the bot's token first."}

    def look():
        # Without an offset, reading does not use the messages up: the controller still gets them later.
        return _call(token, "getUpdates", {"limit": 100, "timeout": 0, "allowed_updates": ["message"]}, timeout=12) or []

    try:
        updates = await asyncio.to_thread(look)
    except _Refused as e:
        return {"ok": False, "reason": str(e)}
    people: dict[int, dict] = {}
    for u in reversed(updates):
        msg = u.get("message") or {}
        who = msg.get("from") or {}
        if not who.get("id") or who.get("is_bot") or (msg.get("chat") or {}).get("type") != "private":
            continue
        if who["id"] in people:
            continue
        name = " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x) or who.get("username") or "Someone"
        people[who["id"]] = {"id": str(who["id"]), "name": name, "username": who.get("username") or "",
                             "said": (msg.get("text") or "")[:60], "at": msg.get("date") or 0}
    return {"ok": True, "people": list(people.values())[:6]}


@router.post("/api/telegram/owner")
async def telegram_owner(request: Request):
    body = await _body(request)
    owner = str(body.get("id") or "").strip()
    if not owner.isdigit() or len(owner) > 20:
        raise HTTPException(status_code=400, detail="Your Telegram ID is a number, like 123456789.")
    _save("TELEGRAM_OWNER_ID", owner)
    await _apply(request)
    return {"ok": True}


@router.post("/api/telegram/test")
async def telegram_test(request: Request):
    """A message to the owner, which proves the token and the ID fit together."""
    token = real("TELEGRAM_BOT_TOKEN")
    owner = real_int("TELEGRAM_OWNER_ID")
    if not token or not owner:
        return {"ok": False, "reason": "Add the token and your ID first."}
    text = "👋 Connected to LLMSelfbot. Send /help to see what you can do from here."
    try:
        await asyncio.to_thread(_call, token, "sendMessage", {"chat_id": owner, "text": text})
    except _Refused as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True}


@router.get("/api/telegram/commands")
async def telegram_commands():
    return {"groups": commands.as_json()}


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


def _save(key: str, value: str):
    values = read_env()
    values[key] = value
    write_env(values)
    reload_into_process(values)


async def _apply(request: Request):
    """A new token or owner: the controller reads them as it starts, so it starts again (or for the first time)."""
    sup = getattr(request.app.state, "supervisor", None)
    if sup is None or not _enabled() or not (real("TELEGRAM_BOT_TOKEN") and real_int("TELEGRAM_OWNER_ID")):
        return
    running = _state(request)["state"] in ("running", "starting", "crashing")
    try:
        await asyncio.to_thread(sup.restart if running else sup.start, "telegram")
    except Exception:
        pass
