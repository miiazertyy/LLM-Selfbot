"""app/web/settings_io.py - settings as a file you can keep or share. Export writes every setting to JSON with a short header saying what it is. Import is not the raw editor: a file from anywhere is read setting by setting, checked against what each setting holds here, and shown as a list of changes to pick from before anything is written. Personal settings (who owns the bot, the error webhook, the local server's key) stay out of an export unless asked for, because the file is made to be passed around. Import leaves them, and the settings that decide where things are sent, alone unless ticked: someone else's owner ID would hand them the bot's owner commands, and another address for the local server would send it every message."""

import copy
import re
import time

from app.web import descriptions as desc
from app.web.schema import CONFIG_SCHEMA, set_nested

FORMAT = 1
MAX_TEXT = 20_000

# Settings whose own keys are names someone chose: a mood per name, openers per language. They move whole, because taken apart, a mood that is only in the file would look like a setting this version does not have.
TABLES = {"bot.mood.moods", "bot.late_reply.openers"}

# Yours, not a preference: left out of an export unless asked for, and never imported unless ticked.
PERSONAL = {
    "bot.owner_id": "Who owns the bot and can use its owner commands",
    "notifications.error_webhook": "Where error alerts are posted",
    "bot.local.api_key": "The key for the model server on this computer",
}
# Where things are sent, and who can reach this panel: imported only when ticked. 0.0.0.0 as the bind opens the panel to the whole network.
CAREFUL = {
    "bot.local.base_url": "Where requests for this computer's models go",
    "services.webui.bind": "Who can reach this panel",
    "services.webui.port": "The port this panel listens on",
    "services.webui.enabled": "Whether this panel runs",
}
# Anything added later that is a secret by its name counts as personal too.
_SECRETISH = re.compile(r"token|secret|password|webhook|api_?key", re.I)

# Names for the settings edited outside the Settings list, which have no label of their own there.
_NAMES = {
    "bot.mood.moods": "Moods",
    "bot.late_reply.openers": "Late reply openers",
    "bot.groq_models": "Reply models",
    "bot.reactions.emojis": "Reaction emojis",
}

_SCHEMA = {f["key"]: f for f in CONFIG_SCHEMA}
_BARE_ROOTS = ("bot", "services", "discord", "snapchat", "notifications")


def personal(key: str) -> bool:
    return key in PERSONAL or bool(_SECRETISH.search(key.rsplit(".", 1)[-1]))


def label(key: str) -> str:
    return _NAMES.get(key) or _SCHEMA.get(key, {}).get("label") or desc.label_for(key)


def flatten(node, prefix: str = "") -> dict:
    """Every setting as a dotted key, with the named tables kept whole."""
    out = {}
    for key, value in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and path not in TABLES:
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def export(cfg: dict, include_personal: bool = False, version: str = "") -> dict:
    """The settings file: every setting, under a header that says what it is and when it was made."""
    settings: dict = {}
    for key, value in flatten(cfg).items():
        if personal(key) and not include_personal:
            continue
        set_nested(settings, key, copy.deepcopy(value))
    return {
        "app": "LLMSelfbot",
        "kind": "settings",
        "format": FORMAT,
        "version": version,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "personal": bool(include_personal),
        "settings": settings,
    }


def unwrap(data) -> tuple:
    """The settings in a file, and what its header says. config.yaml saved as JSON works too."""
    if isinstance(data, dict) and isinstance(data.get("settings"), dict) \
            and (data.get("kind") == "settings" or data.get("app") == "LLMSelfbot"):
        meta = {k: data.get(k) for k in ("version", "exported_at", "personal", "format")}
        return data["settings"], meta
    if isinstance(data, dict) and any(isinstance(data.get(k), dict) for k in _BARE_ROOTS):
        return data, {}
    raise ValueError("That is not a settings file from this app.")


def _kind(v) -> str:
    if v is None:
        return "none"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "table"
    return "other"


_WORDS = {"bool": "on or off", "number": "a number", "text": "text", "list": "a list", "table": "a table"}
_SCHEMA_KIND = {"bool": "bool", "int": "number", "float": "number", "str": "text"}


def _check(key: str, value, here, base):
    """The value to write for this setting, or ValueError saying why not. `here` is what it holds now, `base` what the app ships with."""
    field = _SCHEMA.get(key, {})
    refs = [x for x in (here, base, field.get("default")) if x is not None]
    want = _SCHEMA_KIND.get(field.get("type", "")) or (_kind(refs[0]) if refs else None)
    got = _kind(value)
    if got == "none":
        # Empty is a real value for some ("use the provider's default"), not for the rest.
        if here is None or base is None or ("default" in field and field["default"] is None):
            return None
        raise ValueError("cannot be left empty")
    if want is None:
        if got in ("bool", "number", "text"):
            return value
        raise ValueError("is not a plain value")
    if got != want:
        raise ValueError(f"should be {_WORDS.get(want, want)}")
    if want == "number":
        whole = field.get("type") == "int" or (not field and all(
            isinstance(r, int) and not isinstance(r, bool) for r in refs))
        if whole and isinstance(value, float):
            if not value.is_integer():
                raise ValueError("should be a whole number")
            value = int(value)
    elif want == "text" and len(value) > MAX_TEXT:
        raise ValueError("is too long")
    elif want in ("list", "table"):
        # Each entry the kind this setting's entries are, here or as shipped: strings where it keeps strings, rows where it keeps rows.
        items = value if want == "list" else list(value.values())
        allowed = {_kind(x) for r in refs if _kind(r) == want for x in (r if want == "list" else r.values())}
        if allowed and any(_kind(x) not in allowed for x in items):
            raise ValueError("holds entries of the wrong kind")
    return value


def plan(current: dict, template: dict, data) -> dict:
    """What importing this file would change, setting by setting, without writing anything."""
    settings, meta = unwrap(data)
    here, base = flatten(current), flatten(template)
    known = set(here) | set(base) | set(_SCHEMA)
    changes, skipped, same = [], [], 0
    for key, value in flatten(settings).items():
        if key not in known:
            skipped.append({"key": key, "label": label(key), "reason": "Not a setting in this version"})
            continue
        try:
            new = _check(key, value, here.get(key), base.get(key))
        except ValueError as e:
            skipped.append({"key": key, "label": label(key), "reason": f"It {e}"})
            continue
        old = here[key] if key in here else _SCHEMA.get(key, {}).get("default", base.get(key))
        if _kind(new) == _kind(old) and new == old:
            same += 1
            continue
        why = PERSONAL.get(key) or CAREFUL.get(key) or ("A secret" if personal(key) else "")
        changes.append({
            "key": key,
            "label": label(key),
            "section": desc.section_for(key),
            "old": old,
            "new": new,
            # Left unticked: yours, or where things go.
            "guarded": personal(key) or key in CAREFUL,
            "why": why,
            "restart": desc.needs_restart(key),
        })
    return {"meta": meta, "changes": changes, "same": same, "skipped": skipped}


def apply(current: dict, template: dict, data, keys) -> tuple:
    """The config with the chosen changes made, and the changes made. The page sends back which settings, never values: each is checked again here, from the file."""
    chosen = {str(k) for k in keys or []}
    cfg = copy.deepcopy(current)
    done = []
    for change in plan(current, template, data)["changes"]:
        if change["key"] not in chosen:
            continue
        try:
            set_nested(cfg, change["key"], copy.deepcopy(change["new"]))
        except ValueError:
            continue
        done.append(change)
    return cfg, done
