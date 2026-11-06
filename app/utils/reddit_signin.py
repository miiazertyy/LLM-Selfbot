"""Add a Reddit account by signing in, in a real browser window.

A window opens on reddit.com's own login page and the person signs in there,
however they like (app/platforms/snapchat/reddit_login.js). The app never sees a
password, and nothing about it looks like a script logging in - which matters
more on Reddit than anywhere else here, because Reddit's answer to an account it
dislikes is not to lock it but to hide it, silently, from everybody else.

The session stays in that window's profile, filed as
config/reddit-<username>-profile, which is what reddit_runner.js opens from then
on. All of that machinery is browser_signin.Flow, shared with X and Instagram.

A password and a 2FA key may be saved afterwards, and are optional: they are
only what lets the account sign itself back in, months later, without anybody
there. They live in config/.env, write-only, and nowhere else.
"""
from __future__ import annotations

import re

from app.utils.browser_signin import Flow

#: Reddit's own rule for a username: 3 to 20 letters, digits, underscores and hyphens. A hyphen is a real
#: character here, unlike X's handles, so nothing is read back out of one.
USERNAME = re.compile(r"^[a-z0-9_-]{3,20}$")


def clean_username(name) -> str:
    """The username as stored and as its profile is named, or "" when it is not one Reddit could have given.
    Takes it however it was written: "u/Theo-Wav", "/u/theo-wav", a link to the profile, or the name itself."""
    n = str(name or "").strip()
    m = re.search(r"reddit\.com/u(?:ser)?/([A-Za-z0-9_-]{3,20})", n)
    if m:
        n = m.group(1)
    n = n.lstrip("@").strip("/")
    for prefix in ("u/", "user/"):
        if n.lower().startswith(prefix):
            n = n[len(prefix):]
    n = n.strip("/").lower()
    return n if USERNAME.match(n) else ""


def clean_totp(key) -> str:
    """The 2FA key, if one was given. The same rule Instagram's uses: one copy of it is enough."""
    from app.utils.instagram_signin import clean_totp as _clean
    return _clean(key)


FLOW = Flow(platform="reddit", name="Reddit", script="reddit_login.js", clean=clean_username, env="REDDIT")


def profile_dir(username: str):
    """Where an account's browser profile lives (what reddit_runner.js opens)."""
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
