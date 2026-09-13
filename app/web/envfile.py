"""
app/web/envfile.py - read/write config/.env.

Shared by the secrets editor and the account manager, both of which change the
same file. Reading is plain; writing preserves comments, blank lines and key
order, and always leaves a .env.bak behind.
"""

import os
import re
import shutil

from app.utils.paths import DATA_DIR

ENV_PATH = DATA_DIR / "config" / ".env"

SECRET_KEYS = re.compile(
    r"^(DISCORD_TOKEN(?:_\d+)?|DISCORD_PROXY(?:_\d+)?|GROQ_API_KEY(?:_\d+)?|"
    r"TELEGRAM_BOT_TOKEN|SNAP_PASSWORD(?:_\d+)?)$"
)


def mask(value: str) -> str:
    if not value or not value.strip():
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}…{value[-4:]}"


def read_env() -> dict:
    out = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip()
    return out


def write_env(values: dict):
    """Rewrite .env in place, preserving comments, blank lines and ordering.

    An early version wrote only the parsed key/value pairs, which erased every
    comment in the file the first time secrets were saved from the UI.
    """
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ENV_PATH.exists():
        shutil.copyfile(ENV_PATH, ENV_PATH.parent / ".env.bak")

    remaining = dict(values)
    out = []
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                out.append(line)
                continue
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
            # A key dropped from `values` is removed from the file.
    for key, val in remaining.items():          # newly added keys
        out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")


def reload_into_process(values: dict | None = None):
    """Make .env changes visible to this process immediately.

    The account counters read os.environ, so without this a token added from
    the UI would not appear until the supervisor was restarted. Keys that were
    deleted from the file are removed from the environment too.
    """
    values = read_env() if values is None else values
    managed = {k for k in os.environ if SECRET_KEYS.match(k)
               or k.startswith(("DISCORD_TOKEN", "DISCORD_PROXY",
                                "SNAP_USERNAME", "SNAP_PASSWORD"))}
    for key in managed - set(values):
        os.environ.pop(key, None)
    for key, val in values.items():
        os.environ[key] = val
