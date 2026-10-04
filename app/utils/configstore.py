"""Writing settings, for everyone or for one persona.

Every change to the settings goes through here. The old way, read the config,
change the dict, dump it, stopped being safe once an account's runner reads
everyone's settings with its persona's own on top (app/utils/personas.py): the
dict it holds is not the file, and dumping it would write that persona's
values into everyone's. So a write names where it goes:

- everyone (persona None): config/config.yaml, a copy kept in backups/ first;
- one persona: its own value, kept only where it differs from everyone's. The
  app-wide ones (what runs, the model server, who may command it) can't differ
  and always go to everyone.
"""
import shutil
import time
from pathlib import Path

import yaml

from app.utils import personas

# Only the newest forty copies are kept: one went in for every switch flipped and every slider let go.
KEEP_BACKUPS = 40


def config_path() -> Path:
    from app.utils.helpers import resource_path
    return Path(resource_path("config/config.yaml"))


def _backups_dir() -> Path:
    from app.utils.helpers import resource_path
    return Path(resource_path("config")).parent / "backups"


def backup(path=None) -> None:
    """A copy of everyone's settings before they change."""
    path = Path(path or config_path())
    if not path.is_file():
        return
    backups = _backups_dir()
    backups.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, backups / f"config-{int(time.time())}.yaml")
    try:
        old = sorted(backups.glob("config-*.yaml"), key=lambda p: p.stat().st_mtime)[:-KEEP_BACKUPS]
        for p in old:
            p.unlink(missing_ok=True)
    except OSError:
        pass


def write_base(cfg: dict, path=None) -> None:
    """Everyone's settings, written whole, a backup first. Blocking: routes run it on a thread."""
    from app.utils.atomic import write_text_atomic
    from app.utils.helpers import invalidate_config_cache
    path = Path(path or config_path())
    backup(path)
    write_text_atomic(path, yaml.safe_dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False))
    invalidate_config_cache()


def _set_nested(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def get_nested(d, dotted: str, default=None):
    cur = d
    for part in str(dotted).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_value(key: str, value, persona: str | None = None, path=None) -> str:
    """Set one setting: for everyone, or as this persona's own. Returns where it went, "base" or "persona"."""
    from app.utils.helpers import invalidate_config_cache, load_base_config, load_base_config_copy
    if persona and personas.exists(persona) and not personas.is_global_only(key):
        personas.set_override(persona, key, value, base=load_base_config())
        invalidate_config_cache()
        return "persona"
    cfg = load_base_config_copy()
    _set_nested(cfg, key, value)
    write_base(cfg, path)
    return "base"


def set_effective(key: str, value, persona: str | None = None) -> str:
    """A switch flipped from inside a runner (a Telegram toggle, a command): written where the value it replaces
    came from, so a persona's own stays its own and everyone's stays everyone's."""
    pid = persona if persona is not None else personas.current()
    if pid and personas.exists(pid) and personas.overridden(pid, key) and not personas.is_global_only(key):
        return set_value(key, value, pid)
    return set_value(key, value, None)


def reset(key: str, persona: str) -> bool:
    """This persona goes back to everyone's value for the setting."""
    from app.utils.helpers import invalidate_config_cache
    gone = personas.clear_override(persona, key)
    invalidate_config_cache()
    return gone


def effective(persona: str | None) -> dict:
    """The settings an account with this persona runs with."""
    from app.utils.helpers import _config_cache, load_base_config
    base = load_base_config()
    if not persona:
        return base
    return personas.merged(base, persona, base_sig=(_config_cache["path"], _config_cache["mtime"]))


def all_effective() -> list:
    """Everyone's settings, then each persona's that changes anything: for checks that must see every model or
    setting in use anywhere, not only the ones in everyone's."""
    from app.utils.helpers import load_base_config
    out = [(None, load_base_config())]
    for pid in personas.ids():
        if personas.overrides(pid):
            out.append((pid, effective(pid)))
    return out
