"""
app/utils/credentials.py - tell a real credential from a template placeholder.

config/.env is seeded from resources/example.env on first run, and that file
ships filled-in-looking values:

    DISCORD_TOKEN=TOKEN_GOES_HERE
    TELEGRAM_BOT_TOKEN=your_token_here
    TELEGRAM_OWNER_ID=your_telegram_user_id_here
    SNAP_USERNAME=your_snapchat_username

Every one of those is a non-empty string, so a plain `os.getenv(...)` test
treats them as configured. That produced phantom accounts in the UI, spawned
runners with no usable login, and crashed the Telegram controller on
int("your_telegram_user_id_here").

Nothing here imports from the rest of the app, so it is safe to use from the
low-level modules (core.ipc, cli) as well as the web layer.
"""

import os
import re

# Exact values shipped in resources/example.env, lowercased.
_KNOWN = {
    "token_goes_here",
    "groq_api_key_goes_here",
    "your_token_here",
    "your_key_here",
    "your_telegram_user_id_here",
    "your_snapchat_username",
    "your_snapchat_password",
    "second_account_username",
    "second_account_password",
}

# The shapes those follow, so a placeholder we forgot to list is still caught:
#   YOUR_FIRST_TOKEN_HERE / your_token_here / TOKEN_GOES_HERE / <changeme>
_SHAPES = re.compile(
    r"^(your[_-].*|.*[_-]goes[_-]here|.*[_-]here|changeme|xxx+|<.*>)$",
    re.IGNORECASE,
)


def is_placeholder(value) -> bool:
    """True when this looks like the template's value rather than a real one."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.lower() in _KNOWN or bool(_SHAPES.match(text))


def real(name: str, default: str = "") -> str:
    """os.getenv, but a placeholder reads as unset."""
    value = os.getenv(name)
    return default if is_placeholder(value) else str(value).strip()


def real_any(name: str) -> str:
    """The first real value of NAME, NAME_1, NAME_2, and so on.

    Keys and tokens are stored numbered (GROQ_API_KEY_1, DISCORD_TOKEN_1) so
    several can be used in turn, and the unnumbered name is often absent
    entirely. Checking only the bare name reported a perfectly working setup as
    "not set".
    """
    found = real(name)
    if found:
        return found
    for i in range(1, 21):
        found = real(f"{name}_{i}")
        if found:
            return found
    return ""


def real_int(name: str, default: int = 0) -> int:
    """As `real`, parsed as an int. A non-numeric value returns the default
    rather than raising, a bad .env must not crash a worker at import time."""
    text = real(name)
    try:
        return int(text)
    except (TypeError, ValueError):
        return default
