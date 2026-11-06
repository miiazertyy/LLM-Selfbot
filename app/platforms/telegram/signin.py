"""app/platforms/telegram/signin.py - signing a Telegram account in, from the Accounts page.

Telegram signs in by phone: the app asks for a code, Telegram sends it to the account (in its app, or by SMS), the
person types it here, and an account with two-step verification asks for its password too. What comes out is a
session string, which IS the login from then on: it lives in config/.env, write-only, and never goes back to the
page.

Shaped like app/utils/instagram_signin.py (start / status / give_code / cancel) so the Accounts page drives it the
same way. Telethon is asyncio, so unlike Instagram's there is no browser and no subprocess: the client stays
connected here between the steps, because the code Telegram sent belongs to this connection.
"""
from __future__ import annotations

import asyncio
import re
import time

# The one sign-in in flight, if any. One at a time, as the Instagram one is.
_STATE: dict = {"state": "idle", "detail": "", "at": 0.0, "index": 0, "phone": ""}
_CLIENT = None
_SENT: dict = {}
_LOCK = asyncio.Lock()
# Telegram gives the code a few minutes; a sign-in nobody finished is dropped rather than left holding a connection.
GIVE_UP_AFTER = 600.0


def clean_phone(phone) -> str:
    """A number as people type one ("+33 6 12 34 56 78", "0033612345678") as Telegram wants it: digits, one +."""
    digits = re.sub(r"\D", "", str(phone or ""))
    digits = digits[2:] if digits.startswith("00") else digits
    return f"+{digits}" if 6 <= len(digits) <= 20 else ""


def clean_api_id(api_id) -> int:
    try:
        n = int(str(api_id).strip())
    except (TypeError, ValueError):
        return 0
    return n if 0 < n < 10 ** 12 else 0


def clean_api_hash(api_hash) -> str:
    h = str(api_hash or "").strip().lower()
    return h if re.fullmatch(r"[0-9a-f]{32}", h) else ""


def status() -> dict:
    """Where the sign-in has got to, for the page: idle, code, password, done, failed."""
    out = {k: _STATE[k] for k in ("state", "detail", "index", "phone")}
    if _STATE["state"] in ("code", "password") and time.time() - _STATE["at"] > GIVE_UP_AFTER:
        return {"state": "failed", "detail": "It took too long, so Telegram's code has expired. Start again.",
                "index": _STATE["index"], "phone": _STATE["phone"]}
    return out


def running() -> bool:
    return _STATE["state"] in ("sending", "code", "password")


def _set(**fields) -> None:
    _STATE.update(at=time.time(), **fields)


async def _drop() -> None:
    global _CLIENT
    client, _CLIENT = _CLIENT, None
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass


async def cancel() -> dict:
    """Forget the attempt and let the connection go."""
    async with _LOCK:
        await _drop()
        _SENT.clear()
        _set(state="idle", detail="", index=0, phone="")
        return status()


async def start(api_id, api_hash: str, phone: str, index: int = 0, proxy: str = "") -> dict:
    """Ask Telegram for a code. The client stays connected for the code step."""
    global _CLIENT
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (ApiIdInvalidError, FloodWaitError, PhoneNumberBannedError,
                                 PhoneNumberInvalidError)

    api_id, api_hash, phone = clean_api_id(api_id), clean_api_hash(api_hash), clean_phone(phone)
    if not api_id or not api_hash:
        return {"state": "failed", "detail": "That api_id or api_hash does not look right. Both come from "
                                             "my.telegram.org, under API development tools."}
    if not phone:
        return {"state": "failed", "detail": "That is not a phone number. Write it with its country code."}
    async with _LOCK:
        await _drop()
        _set(state="sending", detail="", index=int(index or 0), phone=phone)
        try:
            from app.utils import proxies
            client = TelegramClient(StringSession(), api_id, api_hash, proxy=proxies.for_telethon(proxy),
                                    device_model="Desktop", system_version="Windows", app_version="1.0")
            await client.connect()
            sent = await client.send_code_request(phone)
        except ApiIdInvalidError:
            _set(state="failed", detail="Telegram refused that api_id and api_hash pair.")
            return status()
        except PhoneNumberInvalidError:
            _set(state="failed", detail="Telegram does not know that number.")
            return status()
        except PhoneNumberBannedError:
            _set(state="failed", detail="Telegram has banned that number.")
            return status()
        except FloodWaitError as e:
            _set(state="failed", detail=f"Telegram asked to wait {int(getattr(e, 'seconds', 0))} s before trying "
                                        "again.")
            return status()
        except Exception as e:
            _set(state="failed", detail=f"Telegram would not take it: {e}")
            return status()
        _CLIENT = client
        _SENT.update(hash=sent.phone_code_hash, api_id=api_id, api_hash=api_hash, phone=phone)
        _set(state="code", detail="Telegram sent a code. It is in your Telegram app, or in a text message.")
        return status()


async def give_code(code: str) -> dict:
    """The code, typed in the panel. An account with two-step verification then asks for its password."""
    from telethon.errors import (PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError)

    code = re.sub(r"\D", "", str(code or ""))[:12]
    if not code:
        return {**status(), "detail": "That is not a code."}
    async with _LOCK:
        if _CLIENT is None or _STATE["state"] != "code":
            return {"state": "failed", "detail": "Nothing is waiting for a code.", "index": 0, "phone": ""}
        try:
            await _CLIENT.sign_in(_SENT["phone"], code, phone_code_hash=_SENT["hash"])
        except SessionPasswordNeededError:
            _set(state="password", detail="This account has two-step verification. Its password finishes it.")
            return status()
        except PhoneCodeInvalidError:
            _set(state="code", detail="That code is not right.")
            return status()
        except PhoneCodeExpiredError:
            await _drop()
            _set(state="failed", detail="That code has expired. Start again.")
            return status()
        except Exception as e:
            _set(state="code", detail=f"Telegram would not take it: {e}")
            return status()
        return await _finish()


async def give_password(password: str) -> dict:
    """The two-step verification password, for an account that has one."""
    from telethon.errors import PasswordHashInvalidError

    async with _LOCK:
        if _CLIENT is None or _STATE["state"] != "password":
            return {"state": "failed", "detail": "Nothing is waiting for a password.", "index": 0, "phone": ""}
        try:
            await _CLIENT.sign_in(password=str(password or ""))
        except PasswordHashInvalidError:
            _set(state="password", detail="That password is not right.")
            return status()
        except Exception as e:
            _set(state="password", detail=f"Telegram would not take it: {e}")
            return status()
        return await _finish()


async def _finish() -> dict:
    """Signed in: the session string and who it turned out to be, held for the route to store."""
    global _CLIENT
    me = await _CLIENT.get_me()
    session = _CLIENT.session.save()
    await _drop()
    _STATE["login"] = {
        "session": session, "api_id": _SENT["api_id"], "api_hash": _SENT["api_hash"], "phone": _SENT["phone"],
        "index": _STATE["index"],
        "username": (getattr(me, "username", "") or ""),
        "name": " ".join(x for x in (getattr(me, "first_name", ""), getattr(me, "last_name", "")) if x).strip(),
        "id": int(getattr(me, "id", 0) or 0),
    }
    _SENT.clear()
    _set(state="done", detail=f"Signed in as {_STATE['login']['name'] or _STATE['login']['phone']}.")
    return status()


def take_login() -> dict | None:
    """The finished sign-in, handed over once: the session string never goes anywhere else."""
    login = _STATE.pop("login", None)
    if login:
        _set(state="idle", detail="", index=0, phone="")
    return login
