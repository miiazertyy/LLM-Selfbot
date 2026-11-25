"""Something only a person can do for an account: a check to solve (a captcha), a code to type, an email check to
finish. Said at once wherever the person may be looking: a card on every page of the panel (it plays its own sound and
goes away by itself once the account is past it), a Windows notification by the clock, and the log.

The runners already wait for the person when this happens; until now the panel was told and did nothing with it, so a
check sat unsolved until someone happened to open the Accounts page.
"""
from __future__ import annotations

import time

#: The same thing from the same account is said once in this long, however often the runner asks.
QUIET_S = 120
_last: dict = {}

#: What each kind asks of the person, in a few words.
WORDS = {
    "captcha": "{name} put up a check. Solve it in its window.",
    "captcha_discord": "Discord wants a captcha. Do what it asked in the Discord app.",
    "code": "{name} sent a code to the account's email or phone. Type it on the Accounts page.",
    "code_mail": "{name} sent a code by email. Looking for it in your mailboxes.",
    "verify": "Snapchat wants its email check done. Finish it in its window.",
}


def _name(platform: str) -> str:
    from app.platforms import registry
    return registry.name_of(platform)


def text_for(platform: str, what: str) -> str:
    name = _name(platform)
    key = f"{what}_{platform}" if f"{what}_{platform}" in WORDS else what
    return WORDS.get(key, "{name} needs you.").format(name=name)


def raised(web_id: str, what: str, now: float | None = None) -> bool:
    """An account asked for a person. Returns whether it was said (not when the same was said just now)."""
    if what not in ("captcha", "code", "code_mail", "verify"):
        return False
    now = time.time() if now is None else now
    if now - _last.get((web_id, what), 0.0) < QUIET_S:
        return False
    _last[(web_id, what)] = now
    platform = web_id.split("_", 1)[0]
    name = _name(platform)
    text = text_for(platform, what)
    from app.web.logbus import bus
    bus.append(platform, text, "warn")
    bus.event("attention", {"id": web_id, "platform": platform, "what": what, "text": text, "at": now})
    # Looking in the mailboxes is the app's own work: only what needs the person goes to Windows.
    if what != "code_mail":
        try:
            from app import tray
            tray.notify(text, f"{name} needs you")
        except Exception:
            pass
    return True
