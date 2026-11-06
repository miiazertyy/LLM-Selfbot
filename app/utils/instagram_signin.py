"""Add an Instagram account by signing in, in a real browser window.

A window opens on instagram.com's own login page and the person signs in there, however they like
(app/platforms/snapchat/instagram_login.js). The app never sees a password.

It used to type the login itself, from what was stored. It does not any more: Instagram treats a scripted login as
the thing to act on, and the test account here was suspended for it. A person signing in is a person signing in.

The session stays in that window's profile, filed as config/instagram-<username>-profile, which is what
instagram_runner.js opens from then on. All of that machinery is browser_signin.Flow, shared with X and Reddit.

A password and a 2FA key may be saved afterwards, and are optional: they are only what lets the account sign
itself back in, months later, with nobody there (instagrambot.js signIn). They live in config/.env, write-only,
and nowhere else.

clean_totp lives here and is used by the other two: the six digits from a 2FA key are RFC 6238 and nobody's in
particular, and one copy of the rule is better than three.
"""
from __future__ import annotations

import re

from app.utils.browser_signin import Flow

#: Instagram's own rule for a username: 1 to 30 letters, digits, dots and underscores, never starting or ending
#: with a dot.
USERNAME = re.compile(r"^[a-z0-9._]{1,30}$")


def clean_username(username) -> str:
    """The username as stored and as its profile is named, or "" when it is not one Instagram could have."""
    u = str(username or "").strip().lstrip("@").lower()
    return u if USERNAME.match(u) and not u.startswith(".") and not u.endswith(".") else ""


def clean_totp(key) -> str:
    """A 2FA key as Instagram shows it beside the QR code ("G54M E4E3 T37W 6IXH"), kept without its spaces; "" when
    it is not a base32 key the six digits could come from. An empty key is an account without 2FA, which is fine."""
    k = str(key or "").strip().upper().replace(" ", "").replace("-", "").rstrip("=")
    if not k:
        return ""
    return k if re.fullmatch(r"[A-Z2-7]{16,64}", k) else ""


FLOW = Flow(platform="instagram", name="Instagram", script="instagram_login.js", clean=clean_username,
            env="INSTAGRAM")


def profile_dir(username: str):
    """Where an account's browser profile lives, by its username (what instagram_runner.js opens)."""
    return FLOW.profile_dir(username)


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


def drop_profile(username: str) -> None:
    """Forget an account's session, when the account is removed from the panel."""
    FLOW.drop_profile_of(username)


def give_code(code: str) -> dict:          # noqa: ARG001
    """Nothing here waits for a code any more: the person types it in the window they are signing in on. A code
    typed in the panel is for a running account's own runner instead, which account_routes hands it to."""
    return {"ok": False, "reason": "Nothing is waiting for a code."}
