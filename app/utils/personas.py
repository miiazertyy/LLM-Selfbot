"""Persona profiles: who the bot is, account by account.

Every account used to speak as one persona: one text, one set of pictures, one
memory, one set of settings. A persona profile is all four, and each account is
given one, so Discord #1 can be someone else entirely from Snapchat #1.

Three layers, read top down:
- Everyone: config/config.yaml, the base every persona starts from.
- A persona: its own changes to that base (settings.yaml, flat dotted keys),
  plus its text, its pictures and its memory. Default is a persona like the
  others, only its text and pictures stay where they always were
  (config/instructions.txt, config/pictures), so nothing moves for an install
  that never makes a second one. If Default were the base instead, editing its
  moods would quietly change every persona that had not changed them.
- An account: config/personas.json says which persona it is. One not named
  there is Default.

A runner is one account, so it knows its persona from the account it runs
(pinned for the life of the process: its caches of people are keyed by person
alone, and must never mix two personas). The web server is no account; it
passes a persona explicitly, or runs the work in scope().

A persona never touches the account's real profile: its avatar lives here, for
the app's own pages, and nowhere else.
"""
import contextlib
import contextvars
import copy
import functools
import json
import os
import re
import shutil
import threading
import time
import unicodedata
from pathlib import Path

import yaml

DEFAULT = "default"
RESERVED = {"default", "everyone", "all", "new"}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_WEB_ID = re.compile(r"^(discord|snapchat)_([1-9][0-9]{0,2})$")
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}

# Ten colours to tell them apart at a glance, named for the tooltip.
PALETTE = [
    {"id": "violet", "name": "Violet", "hex": "#a78bfa"},
    {"id": "pink", "name": "Pink", "hex": "#f472b6"},
    {"id": "rose", "name": "Rose", "hex": "#fb7185"},
    {"id": "orange", "name": "Orange", "hex": "#fb923c"},
    {"id": "amber", "name": "Amber", "hex": "#fbbf24"},
    {"id": "lime", "name": "Lime", "hex": "#a3e635"},
    {"id": "mint", "name": "Mint", "hex": "#34d399"},
    {"id": "cyan", "name": "Cyan", "hex": "#22d3ee"},
    {"id": "blue", "name": "Blue", "hex": "#60a5fa"},
    {"id": "orchid", "name": "Orchid", "hex": "#e879f9"},
]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# What is the app's, not a persona's: what runs, where alerts go, the model server on this computer, who may command
# the bot. A persona cannot change these; Settings shows them as the same for everyone.
GLOBAL_ONLY = (
    "services", "notifications", "discord.enabled", "snapchat.enabled", "bot.owner_id",
    "bot.local.base_url", "bot.local.api_key", "bot.local.autostart", "bot.local.context_length",
    "bot.profile_cache", "bot.memory_summary", "bot.per_account_persona",
)

_lock = threading.RLock()
_scope: contextvars.ContextVar = contextvars.ContextVar("llmselfbot_persona", default=None)
_pinned: dict = {}
_cache: dict = {}


def is_global_only(key: str) -> bool:
    key = str(key or "")
    return any(key == p or key.startswith(p + ".") for p in GLOBAL_ONLY)


def holds_global(key: str) -> bool:
    """A key whose value holds global-only ones inside it (bot.local holds bot.local.base_url)."""
    key = str(key or "")
    return any(p.startswith(key + ".") for p in GLOBAL_ONLY)


# ── Where things are ──────────────────────────────────────────────────────────

def _rp(rel: str) -> Path:
    # Looked up each call: tests point resource_path somewhere else after this module is imported.
    from app.utils import helpers
    return Path(helpers.resource_path(rel))


def valid_id(pid) -> bool:
    return isinstance(pid, str) and bool(_ID.match(pid))


def _check(pid) -> str:
    if not valid_id(pid):
        raise ValueError(f"not a persona id: {pid!r}")
    return pid


def root() -> Path:
    return _rp("config/personas")


def folder(pid: str) -> Path:
    return root() / _check(pid)


def meta_path(pid: str) -> Path:
    return folder(pid) / "persona.yaml"


def settings_path(pid: str) -> Path:
    return folder(pid) / "settings.yaml"


def avatar_path(pid: str) -> Path:
    return folder(pid) / "avatar.jpg"


def instructions_path(pid: str) -> Path:
    return _rp("config/instructions.txt") if _check(pid) == DEFAULT else folder(pid) / "instructions.txt"


def pictures_dir(pid: str) -> Path:
    return _rp("config/pictures") if _check(pid) == DEFAULT else folder(pid) / "pictures"


def assignments_path() -> Path:
    return _rp("config/personas.json")


def _sig(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _write_text(path: Path, text: str) -> None:
    from app.utils.atomic import write_text_atomic
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, text)
    _cache.clear()


def _read_yaml(path: Path) -> dict:
    sig = _sig(path)
    if sig is None:
        return {}
    key = ("yaml", str(path))
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        with open(path, encoding="utf-8") as f:
            data = yaml.load(f, Loader=loader)
    except (OSError, yaml.YAMLError):
        data = None
    data = data if isinstance(data, dict) else {}
    _cache[key] = (sig, data)
    return data


def _write_yaml(path: Path, data: dict) -> None:
    _write_text(path, yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=True))


def invalidate() -> None:
    _cache.clear()


# ── Which ones there are ──────────────────────────────────────────────────────

def exists(pid) -> bool:
    if not valid_id(pid):
        return False
    return pid == DEFAULT or meta_path(pid).is_file()


def ids() -> list:
    """Default first, then the rest in the order they were made."""
    out = []
    try:
        for p in root().iterdir():
            if p.is_dir() and valid_id(p.name) and p.name != DEFAULT and (p / "persona.yaml").is_file():
                out.append((float(_read_yaml(p / "persona.yaml").get("created") or 0), p.name))
    except OSError:
        pass
    return [DEFAULT] + [pid for _, pid in sorted(out)]


_NAME_IN_TEXT = re.compile(r"your name is\s+([^\s,.;:!?]+)", re.I)
# "You are Alicia." as a text often opens: a name only, capitalised and then lower case (any alphabet), so
# "You are NOT an AI" and "You are a student" are not one. Only in the opening, where a name is given.
_YOU_ARE = re.compile(r"(?i:\byou are)\s+([^\W\d_][\w'\u2019-]{1,30})(?=[\s.,;:!?]|$)")


def _name_from_text(text: str) -> str:
    m = _NAME_IN_TEXT.search(text or "")
    if m and not m.group(1).startswith("["):
        return m.group(1)
    for m in _YOU_ARE.finditer((text or "")[:600]):
        name = m.group(1)
        if name[0].isupper() and name[1].islower():
            return name
    return ""


def get(pid: str) -> dict | None:
    if not exists(pid):
        return None
    meta = _read_yaml(meta_path(pid))
    name = str(meta.get("name") or "").strip()
    if not name and pid == DEFAULT:
        name = _name_from_text(read_text(DEFAULT)) or "Default"
    color = str(meta.get("color") or "")
    return {
        "id": pid,
        "name": name or pid,
        "color": color if _HEX.match(color) else "",
        "created": float(meta.get("created") or 0),
        "is_default": pid == DEFAULT,
    }


def list_all() -> list:
    return [p for p in (get(pid) for pid in ids()) if p]


def slug(name: str, taken=()) -> str:
    """An id from a name: plain lowercase letters, numbers and dashes, never one already used."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:28].strip("-") or "persona"
    if not base[0].isalnum():
        base = "p-" + base
    taken = set(taken) | RESERVED
    pid, n = base, 2
    while pid in taken or (root() / pid).exists():
        pid = f"{base}-{n}"
        n += 1
    return pid


def next_color() -> str:
    used = {(get(pid) or {}).get("color") for pid in ids()}
    for c in PALETTE:
        if c["hex"] not in used:
            return c["hex"]
    return PALETTE[len(used) % len(PALETTE)]["hex"]


# ── Its text ──────────────────────────────────────────────────────────────────

def read_text(pid: str) -> str:
    try:
        return instructions_path(pid).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def save_text(pid: str, text: str) -> None:
    """The persona's text, the old one kept in backups/ first: it is the most load bearing text in the app."""
    path = instructions_path(pid)
    if path.is_file():
        backups = _rp("config").parent / "backups"
        try:
            backups.mkdir(parents=True, exist_ok=True)
            tag = "" if pid == DEFAULT else f"-{pid}"
            shutil.copyfile(path, backups / f"instructions{tag}-{int(time.time())}.txt")
        except OSError:
            pass
    _write_text(path, text)


# A blank in the template: a word in capitals, then whatever hint follows it ("[HOBBIES - games, music...]",
# "[FRIENDS / FAMILY / PETS, first names only]"). A note in brackets starts as a sentence does, and is not one.
_PLACEHOLDER = re.compile(r"\[[A-Z]{2,}[^\]\n]{0,80}\]")


@functools.lru_cache(maxsize=1)
def _template_shapes() -> tuple:
    """The template's own lines (resources/instructions.txt): a line still as the template has it says nothing about
    who a persona is, whatever name was put in it. Lines with the name in are kept as patterns."""
    from app.utils.paths import DEFAULTS_DIR
    try:
        text = (DEFAULTS_DIR / "instructions.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return frozenset(), ()
    plain, shaped = set(), []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "[NAME]" in line:
            shaped.append(re.compile(re.escape(line).replace(re.escape("[NAME]"), ".+?") + r"\Z"))
        else:
            plain.add(line)
    return frozenset(plain), tuple(shaped)


def _from_template(line: str) -> bool:
    plain, shaped = _template_shapes()
    return line in plain or any(p.match(line) for p in shaped)


def vibe(text: str, chars: int = 90) -> str:
    """Who it is in a line: the first sentence of the text that is not a heading, a note, a blank to fill in or a line
    as the template has it. A persona just made says nothing yet: "" (the panel shows "Not written yet")."""
    note = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if note:
            note = not line.endswith("]")
            continue
        if line.startswith("[") and not _PLACEHOLDER.match(line):
            note = not line.endswith("]")
            continue
        if _PLACEHOLDER.search(line) or _from_template(line):
            continue
        line = re.sub(r"[*_`>]+", "", line).strip()
        if not line:
            continue
        return line if len(line) <= chars else line[: chars - 1].rstrip() + "…"
    return ""


def words(text: str) -> int:
    return len((text or "").split())


# ── Its settings ──────────────────────────────────────────────────────────────

def overrides(pid: str) -> dict:
    """What this persona changes from everyone's settings: {"bot.mood.enabled": False, ...}."""
    if not exists(pid):
        return {}
    data = _read_yaml(settings_path(pid))
    return {str(k): v for k, v in data.items() if not is_global_only(str(k))}


def _get_nested(d, dotted: str, default=None):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


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


def _flatten(prefix: str, value) -> dict:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(_flatten(f"{prefix}.{k}", v))
        return out
    return {prefix: value}


_MISSING = object()


def set_overrides(pid: str, mapping: dict) -> None:
    _check(pid)
    clean = {str(k): v for k, v in (mapping or {}).items() if not is_global_only(str(k))}
    with _lock:
        if clean:
            _write_yaml(settings_path(pid), clean)
        else:
            try:
                settings_path(pid).unlink()
            except OSError:
                pass
            _cache.clear()


def set_override(pid: str, key: str, value, base: dict | None = None) -> None:
    """This persona's own value for a setting. One equal to everyone's is not kept: a persona only holds what
    actually differs. A value holding app-wide keys inside it is split, and those are left out."""
    if is_global_only(key):
        raise ValueError(f"{key} is the same for every persona")
    with _lock:
        current = dict(overrides(pid))
        items = _flatten(key, value) if holds_global(key) and isinstance(value, dict) else {key: value}
        # Whatever this key held before, inside it or over it, goes: the new value replaces all of it.
        for k in list(current):
            if k == key or k.startswith(key + ".") or key.startswith(k + "."):
                current.pop(k)
        for k, v in items.items():
            if is_global_only(k):
                continue
            if base is not None and _get_nested(base, k, _MISSING) == v:
                continue
            current[k] = v
        set_overrides(pid, current)


def clear_override(pid: str, key: str) -> bool:
    with _lock:
        current = dict(overrides(pid))
        gone = [k for k in current if k == key or k.startswith(key + ".")]
        for k in gone:
            current.pop(k)
        if gone:
            set_overrides(pid, current)
        return bool(gone)


def overridden(pid: str, key: str) -> bool:
    """This persona has its own value for the key, for something inside it, or for something it is inside."""
    for k in overrides(pid):
        if k == key or k.startswith(key + ".") or key.startswith(k + "."):
            return True
    return False


def merged(base: dict, pid: str | None, base_sig=None) -> dict:
    """Everyone's settings with this persona's own on top. The base itself when it changes nothing."""
    if not pid or not valid_id(pid):
        return base
    ov = overrides(pid)
    if not ov:
        return base
    key = ("merged", pid)
    sig = (base_sig, _sig(settings_path(pid)))
    if base_sig is not None:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for k, v in ov.items():
        _set_nested(out, k, copy.deepcopy(v))
    if base_sig is not None:
        _cache[key] = (sig, out)
    return out


# ── Which account is which ────────────────────────────────────────────────────

def assignments() -> dict:
    path = assignments_path()
    sig = _sig(path)
    if sig is None:
        return {}
    key = ("assign", str(path))
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        data = {}
    accounts = data.get("accounts") if isinstance(data, dict) else None
    out = {str(k): str(v) for k, v in (accounts or {}).items()
           if _WEB_ID.match(str(k)) and valid_id(str(v))}
    _cache[key] = (sig, out)
    return out


def _write_assignments(accounts: dict) -> None:
    from app.utils.atomic import write_json_atomic
    path = assignments_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {"accounts": dict(sorted(accounts.items()))}, indent=2)
    _cache.clear()


def persona_of(web_id) -> str:
    """The persona this account speaks as: Default unless it was given another that still exists."""
    pid = assignments().get(str(web_id or ""))
    return pid if pid and exists(pid) else DEFAULT


def accounts_of(pid: str) -> list:
    out = [acct for acct, p in assignments().items() if p == pid and exists(p)]
    return sorted(out, key=_acct_order)


def _acct_order(web_id: str):
    m = _WEB_ID.match(web_id)
    return (m.group(1), int(m.group(2))) if m else (web_id, 0)


def assign(web_id: str, pid: str) -> None:
    if not _WEB_ID.match(str(web_id or "")):
        raise ValueError(f"not an account: {web_id!r}")
    if not exists(pid):
        raise ValueError(f"no such persona: {pid!r}")
    with _lock:
        accounts = dict(assignments())
        if pid == DEFAULT:
            accounts.pop(web_id, None)
        else:
            accounts[web_id] = pid
        _write_assignments(accounts)


def renumber_ids(ids_list, platform: str, removed: int) -> list:
    """A list of account ids after one is removed: it goes, the ones after it move up a number."""
    out = []
    for item in ids_list or []:
        m = _WEB_ID.match(str(item))
        if not m or m.group(1) != platform:
            out.append(item)
            continue
        n = int(m.group(2))
        if n == removed:
            continue
        out.append(f"{platform}_{n - 1}" if n > removed else item)
    return out


def renumber(platform: str, removed: int) -> None:
    """An account was removed: its entry goes, and the ones after it follow their account down a number. The same
    for the accounts a persona lets the AI add touches on (bot.pictures.touches.accounts)."""
    with _lock:
        accounts = {}
        for acct, pid in assignments().items():
            m = _WEB_ID.match(acct)
            if m and m.group(1) == platform:
                n = int(m.group(2))
                if n == removed:
                    continue
                if n > removed:
                    acct = f"{platform}_{n - 1}"
            accounts[acct] = pid
        _write_assignments(accounts)
        for pid in ids():
            ov = overrides(pid)
            key = "bot.pictures.touches.accounts"
            if isinstance(ov.get(key), list):
                ov = dict(ov)
                ov[key] = renumber_ids(ov[key], platform, removed)
                set_overrides(pid, ov)


# ── Which persona this code is ────────────────────────────────────────────────

def current_account() -> str | None:
    """The account this code runs as: the thread's role where accounts run on threads (a phone), else the one this
    process was started for. None in the panel's own code."""
    try:
        from app.core import inprocess
        role = inprocess.role_here()
        if role is not None:
            if role.role in ("discord", "snapchat"):
                return f"{role.role}_{int(role.account or 1)}"
            return None
    except Exception:
        pass
    value = os.environ.get("LLMSELFBOT_ACCOUNT", "").strip()
    return value if _WEB_ID.match(value) else None


def current() -> str | None:
    """The persona this code works as: one set with scope(), else the account's own, pinned for as long as it runs
    (a new one takes effect on its restart), else None (the panel, which names one wherever it needs one)."""
    pid = _scope.get()
    if pid:
        return pid
    acct = current_account()
    if not acct:
        return None
    token = acct
    try:
        from app.core import inprocess
        role = inprocess.role_here()
        if role is not None:
            token = (acct, id(role))
    except Exception:
        pass
    pid = _pinned.get(token)
    if pid is None:
        pid = persona_of(acct)
        _pinned[token] = pid
    return pid


@contextlib.contextmanager
def scope(pid: str | None):
    """Work done for a persona by code that is no account of its own (the panel): config, text and memory read
    inside are that persona's."""
    token = _scope.set(pid if pid and exists(pid) else None)
    try:
        yield
    finally:
        _scope.reset(token)


def persona_of_path(path) -> str:
    """Whose picture a file is, from the folder it is in."""
    try:
        p = Path(path).resolve()
        rootp = root().resolve()
        if rootp in p.parents:
            rel = p.relative_to(rootp).parts
            if rel and valid_id(rel[0]) and exists(rel[0]):
                return rel[0]
    except (OSError, ValueError):
        pass
    return DEFAULT


# ── Making, changing and removing ─────────────────────────────────────────────

def _template_text(name: str) -> str:
    from app.utils.paths import DEFAULTS_DIR
    try:
        text = (DEFAULTS_DIR / "instructions.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = "Your name is [NAME].\n"
    return text.replace("[NAME]", name)


def create(name: str, color: str = "", copy_from: str | None = None, copy_memory: bool = False) -> dict:
    """A new persona. Fresh: the template text with its name in, answering to that name. A copy: another's text,
    settings, avatar and pictures, and its memory too when asked (the people it knows)."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:40] or "New persona"
    if copy_from is not None and not exists(copy_from):
        raise ValueError(f"no such persona: {copy_from!r}")
    color = color if _HEX.match(str(color or "")) else next_color()
    with _lock:
        pid = slug(name, ids())
        folder(pid).mkdir(parents=True, exist_ok=False)
        _write_yaml(meta_path(pid), {"name": name, "color": color, "created": time.time()})
        if copy_from is None:
            _write_text(instructions_path(pid), _template_text(name))
            set_overrides(pid, {"bot.trigger": name})
        else:
            _write_text(instructions_path(pid), read_text(copy_from))
            set_overrides(pid, overrides(copy_from))
            if avatar_path(copy_from).is_file():
                shutil.copy2(avatar_path(copy_from), avatar_path(pid))
            src = pictures_dir(copy_from)
            dst = pictures_dir(pid)
            dst.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                for f in src.iterdir():
                    if f.is_file() and f.suffix.lower() in _IMAGE_EXT:
                        shutil.copy2(f, dst / f.name)
            from app.utils import db
            db.copy_persona_pictures(copy_from, pid)
            if copy_memory:
                from app.utils import memory
                memory.copy_persona_memory(copy_from, pid)
                db.copy_persona_summaries(copy_from, pid)
        pictures_dir(pid).mkdir(parents=True, exist_ok=True)
    return get(pid)


def update(pid: str, *, name: str | None = None, color: str | None = None) -> dict:
    if not exists(pid):
        raise ValueError(f"no such persona: {pid!r}")
    with _lock:
        folder(pid).mkdir(parents=True, exist_ok=True)
        meta = dict(_read_yaml(meta_path(pid)))
        if name is not None:
            clean = re.sub(r"\s+", " ", str(name)).strip()[:40]
            if clean:
                meta["name"] = clean
        if color is not None:
            meta["color"] = color if _HEX.match(str(color)) else ""
        meta.setdefault("created", 0 if pid == DEFAULT else time.time())
        _write_yaml(meta_path(pid), meta)
    return get(pid)


def delete(pid: str) -> list:
    """Gone: its text, pictures, memory and settings. Its accounts are Default again; which ones, returned."""
    if pid == DEFAULT:
        raise ValueError("Default cannot be deleted")
    if not exists(pid):
        raise ValueError(f"no such persona: {pid!r}")
    with _lock:
        from app.utils import db
        db.delete_persona_rows(pid)
        moved = accounts_of(pid)
        accounts = {a: p for a, p in assignments().items() if p != pid}
        _write_assignments(accounts)
        # Out of the way in one step, then removed: Windows holds a file a runner is still sending, and a plain
        # rmtree that stops halfway would leave half a persona behind.
        trash = root() / f".trash-{pid}-{int(time.time() * 1000)}"
        try:
            os.replace(folder(pid), trash)
        except OSError:
            trash = folder(pid)
        shutil.rmtree(trash, ignore_errors=True)
        _cache.clear()
    return moved


def sweep_trash() -> None:
    try:
        for p in root().iterdir():
            if p.is_dir() and p.name.startswith(".trash-"):
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


# ── Its face ──────────────────────────────────────────────────────────────────

def has_avatar(pid: str) -> bool:
    return exists(pid) and avatar_path(pid).is_file()


def avatar_version(pid: str) -> int:
    sig = _sig(avatar_path(pid)) if exists(pid) else None
    return int(sig[0] // 1_000_000) if sig else 0


def set_avatar(pid: str, data: bytes) -> None:
    """A square crop of a picture, a little above the middle (where a face is), at 256px."""
    if not exists(pid):
        raise ValueError(f"no such persona: {pid!r}")
    import io

    from PIL import Image, ImageOps

    from app.utils import imageimport
    imageimport._ensure_openers()
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        top = max(0, min(h - side, int((h - side) * 0.3)))
        im = im.crop((left, top, left + side, top + side)).resize((256, 256), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=88)
    folder(pid).mkdir(parents=True, exist_ok=True)
    tmp = avatar_path(pid).with_name(f"avatar.{os.getpid()}.tmp")
    tmp.write_bytes(out.getvalue())
    os.replace(tmp, avatar_path(pid))
    _cache.clear()


def clear_avatar(pid: str) -> None:
    try:
        avatar_path(pid).unlink()
    except OSError:
        pass
    _cache.clear()


def picture_count(pid: str) -> int:
    try:
        return sum(1 for f in pictures_dir(pid).iterdir() if f.is_file() and f.suffix.lower() in _IMAGE_EXT)
    except OSError:
        return 0


# ── At start ──────────────────────────────────────────────────────────────────

def startup() -> None:
    """Folders, the database given a persona column where it has none yet, an old per-account setup brought over,
    and anything half deleted cleared away. Safe to call more than once, from any process."""
    try:
        root().mkdir(parents=True, exist_ok=True)
        pictures_dir(DEFAULT).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    from app.utils import db
    db.ensure_persona_schema()
    try:
        migrate_legacy()
    except Exception as e:
        print(f"[Personas] Could not bring the per-account persona files over: {e}", flush=True)
    sweep_trash()


def migrate_legacy() -> list:
    """bot.per_account_persona gave Discord #2 and on their own config/instructions_N.txt. Each one that says
    something other than Default becomes a persona of its own, with Default's pictures and memory (they shared those
    until now), given to its account. The old files stay where they are."""
    from app.utils import helpers
    base = helpers.load_base_config() or {}
    if not ((base.get("bot") or {}).get("per_account_persona")):
        return []
    default_text = read_text(DEFAULT).strip()
    made = []
    for path in sorted(_rp("config").glob("instructions_*.txt")):
        m = re.fullmatch(r"instructions_([0-9]{1,3})\.txt", path.name)
        if not m or int(m.group(1)) < 2:
            continue
        n = int(m.group(1))
        acct = f"discord_{n}"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip() or text.strip() == default_text or acct in assignments():
            continue
        info = create(f"Discord #{n}", copy_from=DEFAULT, copy_memory=True)
        _write_text(instructions_path(info["id"]), text)
        assign(acct, info["id"])
        made.append(info["id"])
    from app.utils import configstore
    configstore.set_value("bot.per_account_persona", False)
    return made
