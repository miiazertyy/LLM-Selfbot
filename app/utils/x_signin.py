"""Add an X account by signing in, in a real browser window.

A window opens on x.com's own login page and the person signs in there, however they like
(app/platforms/snapchat/x_login.js). The app never sees a password.

It used to type the login itself, from what was stored. It does not any more: X watches for a script signing in
harder than for anything else an account does, and what it does about one is lock the account, which takes a
person, a phone and a code to undo. A person signing in is a person signing in.

The session stays in that window's profile, filed as config/x-<handle>-profile, which is what x_runner.js opens
from then on. All of that machinery is browser_signin.Flow, shared with Reddit and Instagram.

A password, a 2FA key and the email X asks for may be saved afterwards, and are optional: they are only what lets
the account sign itself back in, months later, with nobody there (xbot.js signIn). They live in config/.env,
write-only, and nowhere else.
"""
from __future__ import annotations

import re

from app.utils.browser_signin import Flow

#: X's own rule for a handle: 1 to 15 letters, digits and underscores. No dots, which is what tells one from an
#: Instagram username.
HANDLE = re.compile(r"^[a-z0-9_]{1,15}$")


def clean_handle(handle) -> str:
    """The @handle as stored and as its profile is named, or "" when it is not one X could have given. Takes it
    however it was written: "@Theo_Wav", a link to the profile, or the handle itself."""
    h = str(handle or "").strip()
    m = re.search(r"(?:x|twitter)\.com/(?:#!/)?@?([A-Za-z0-9_]{1,15})", h, re.IGNORECASE)
    if m:
        h = m.group(1)
    h = h.lstrip("@").strip("/").lower()
    return h if HANDLE.match(h) else ""


def clean_totp(key) -> str:
    """The 2FA key, if one was given. The same rule Instagram's uses: one copy of it is enough."""
    from app.utils.instagram_signin import clean_totp as _clean
    return _clean(key)


FLOW = Flow(platform="x", name="X", script="x_login.js", clean=clean_handle, env="X")


def profile_dir(handle: str):
    """Where an account's browser profile lives, by its @handle (what x_runner.js opens)."""
    return FLOW.profile_dir(handle)


def status() -> dict:
    return FLOW.status()


def running() -> bool:
    return FLOW.running()


def take_handle() -> str | None:
    return FLOW.take_handle()


def start(timeout_ms: int = 900_000, proxy: str = "") -> dict:
    """Open the window and wait for a sign-in, through the account's proxy if it has one. Returns the first state."""
    return FLOW.start(timeout_ms, extra_env={"LOGIN_PROXY": proxy} if proxy else None)


def cancel() -> dict:
    return FLOW.cancel()


def drop_profile(handle: str) -> None:
    """Forget an account's session, when the account is removed from the panel."""
    FLOW.drop_profile_of(handle)


def give_code(code: str) -> dict:          # noqa: ARG001
    """Nothing here waits for a code any more: the person types it in the window they are signing in on. A code
    typed in the panel is for a running account's own runner instead, which account_routes hands it to."""
    return {"ok": False, "reason": "Nothing is waiting for a code."}
