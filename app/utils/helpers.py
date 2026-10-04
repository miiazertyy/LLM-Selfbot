import calendar as _cal
import os
import sys
from datetime import datetime, timedelta, timezone

import yaml

from app.utils.paths import APP_DIR, DATA_DIR, is_writable_state

_config_cache: dict = {"path": "", "mtime": 0.0, "data": None}
# libyaml's reader where PyYAML was built with it (it is, in the exe): the same data, read seven times faster than the
# pure Python one, and the config is read again after every change by the panel and by each runner.
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def clear_console():
    """Clear the console screen, when there is one to see.

    Under the app, a runner's console is hidden (its output goes to the Logs
    page), so this only started a cmd.exe for nothing, and one started without a
    console of its own opens a window.
    """
    if os.environ.get("LLMSELFBOT_CHILD") == "1" or not getattr(sys.stdout, "isatty", lambda: False)():
        return
    os.system("cls" if os.name == "nt" else "clear")


def resource_path(relative_path):
    """Route writable state (config/, ipc/) to DATA_DIR; everything else to APP_DIR."""
    if is_writable_state(relative_path):
        return str(DATA_DIR / relative_path)
    return str(APP_DIR / relative_path)


def get_env_path():
    return resource_path("config/.env")


def load_base_config():
    """Everyone's settings: config/config.yaml as it is, before any persona's own. Cached on the file's mtime, and
    the cached dict itself is returned: read it, never change it (configstore writes)."""
    config_path = resource_path("config/config.yaml")
    try:
        mtime = os.path.getmtime(config_path)
        if _config_cache["path"] == config_path and _config_cache["mtime"] == mtime and _config_cache["data"] is not None:
            return _config_cache["data"]
    except OSError:
        pass
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.load(file, Loader=_YAML_LOADER)
        _config_cache.update(path=config_path, mtime=os.path.getmtime(config_path), data=config)
        return config
    print("Config file not found. Please provide a config file in config/config.yaml")
    sys.exit(1)


def load_base_config_copy():
    """A copy of everyone's settings, to change and write back."""
    import copy
    return copy.deepcopy(load_base_config())


def load_config():
    """The settings this code runs with. In an account's runner: everyone's, with its persona's own on top
    (app/utils/personas.py). In the panel, which is no account: everyone's, the same object as before."""
    base = load_base_config()
    try:
        from app.utils import personas
        pid = personas.current()
    except Exception:
        pid = None
    if not pid:
        return base
    from app.utils import personas
    return personas.merged(base, pid, base_sig=(_config_cache["path"], _config_cache["mtime"]))


def invalidate_config_cache():
    _config_cache["mtime"] = 0.0
    try:
        from app.utils import personas
        personas.invalidate()
    except Exception:
        pass


def load_tokens() -> list[dict]:
    """Return all Discord tokens from .env as a list of {'token', 'proxy'} dicts. Supports DISCORD_TOKEN_1/DISCORD_PROXY_1, ... and the legacy unsuffixed pair."""
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


# The Snapchat engine called load_instructions() on every single message, which meant an open() and a full read of config/instructions.txt per message. The Discord runner had sidestepped it by caching the result on the bot object; a cache here covers every caller instead.
_instructions_cache: dict = {}


def load_instructions(persona: str | None = None):
    """The text of the persona this code speaks as (app/utils/personas.py): the one named, else this account's,
    else Default's. Read through a cache keyed on the file's mtime and size, so an edit is picked up on the next
    call, by every account using that persona, whoever wrote it (the panel, Telegram, a command)."""
    from app.utils import personas
    pid = persona if persona and personas.exists(persona) else (personas.current() or personas.DEFAULT)
    path = str(personas.instructions_path(pid))
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _instructions_cache.get(key)
    if hit is None:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            hit = file.read()
        # A few personas can be read by one process (the panel reads any of them): kept, but never grown for ever.
        if len(_instructions_cache) > 16:
            _instructions_cache.clear()
        for old in [k for k in _instructions_cache if k[0] == path]:
            _instructions_cache.pop(old, None)
        _instructions_cache[key] = hit
    return hit


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
