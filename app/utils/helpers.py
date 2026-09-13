import calendar as _cal
import os
import sys
from datetime import datetime, timedelta, timezone

import yaml

from app.utils.paths import APP_DIR, DATA_DIR, is_writable_state

_config_cache: dict = {"path": "", "mtime": 0.0, "data": None}


def clear_console():
    """Clear the console screen."""
    os.system("cls" if os.name == "nt" else "clear")


def resource_path(relative_path):
    """Route writable state (config/, ipc/) to DATA_DIR; everything else to APP_DIR."""
    if is_writable_state(relative_path):
        return str(DATA_DIR / relative_path)
    return str(APP_DIR / relative_path)


def get_env_path():
    return resource_path("config/.env")


def load_config():
    config_path = resource_path("config/config.yaml")
    try:
        mtime = os.path.getmtime(config_path)
        if _config_cache["path"] == config_path and _config_cache["mtime"] == mtime and _config_cache["data"] is not None:
            return _config_cache["data"]
    except OSError:
        pass
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
        _config_cache.update(path=config_path, mtime=os.path.getmtime(config_path), data=config)
        return config
    print("Config file not found. Please provide a config file in config/config.yaml")
    sys.exit(1)


def invalidate_config_cache():
    _config_cache["mtime"] = 0.0


def load_tokens() -> list[dict]:
    """Return all Discord tokens from .env as a list of {'token', 'proxy'} dicts.

    Supports DISCORD_TOKEN_1/DISCORD_PROXY_1, ... and the legacy unsuffixed pair.
    """
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=get_env_path(), override=True)

    tokens = []
    i = 1
    while True:
        t = os.getenv(f"DISCORD_TOKEN_{i}")
        if not t:
            break
        proxy = os.getenv(f"DISCORD_PROXY_{i}", "").strip() or None
        tokens.append({"token": t.strip(), "proxy": proxy})
        i += 1

    if not tokens:
        t = os.getenv("DISCORD_TOKEN")
        if t:
            proxy = os.getenv("DISCORD_PROXY", "").strip() or None
            tokens.append({"token": t.strip(), "proxy": proxy})

    if not tokens:
        print("No Discord token(s) found in config/.env. Please set DISCORD_TOKEN_1 (or DISCORD_TOKEN).")
        sys.exit(1)

    return tokens


def load_instructions(account: int = None):
    """The persona this account writes with.

    One persona for every account by default, which is what most people want:
    the same character on each. Turning on bot.per_account_persona gives each
    account its own file, config/instructions_2.txt and so on, so two accounts
    can be two different people. Account 1 keeps the plain instructions.txt, so
    switching the option on does not orphan the persona already written.

    A per account file that does not exist yet falls back to the shared one
    rather than leaving that account with no persona at all.
    """
    paths = []
    if account is None:
        try:
            account = int(os.getenv("DISCORD_ACCOUNT_INDEX", "1") or 1)
        except ValueError:
            account = 1

    per_account = False
    try:
        per_account = bool((load_config().get("bot", {}) or {}).get("per_account_persona"))
    except Exception:
        pass

    if per_account and account and account > 1:
        paths.append(resource_path(f"config/instructions_{account}.txt"))
    paths.append(resource_path("config/instructions.txt"))

    for path in paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as file:
                text = file.read()
            if text.strip():
                return text
    return ""


def france_time_str() -> str:
    """Current Paris time as a formatted string (empty on failure)."""
    try:
        now_utc = datetime.now(timezone.utc)
        y = now_utc.year

        def last_sunday(year, month):
            last_day = _cal.monthrange(year, month)[1]
            weekday = datetime(year, month, last_day).weekday()   # Mon=0 … Sun=6
            return last_day if weekday == 6 else last_day - weekday - 1

        # EU DST switches at 01:00 UTC in both directions.
        dst_start = datetime(y, 3, last_sunday(y, 3), 1, tzinfo=timezone.utc)
        dst_end = datetime(y, 10, last_sunday(y, 10), 1, tzinfo=timezone.utc)
        offset = timedelta(hours=2) if dst_start <= now_utc < dst_end else timedelta(hours=1)
        return (now_utc + offset).strftime("%A %d %B %Y, %H:%M")
    except Exception:
        return ""
