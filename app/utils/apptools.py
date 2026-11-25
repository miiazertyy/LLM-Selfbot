"""The app's settings and personas as tools for an AI, one set for both ways in: an AI app connected over MCP
(app/utils/mcpserver.py) and the Ask box in Settings (app/utils/appchat.py).

What an AI cannot do is decided here, so the limits are the same however it got in:

  keys and logins     not readable, not writable. config/.env is never read for an answer, and anything in it that
                      turned up in one anyway (a token pasted into a persona) is taken out on the way back.
  chats and memory    no tool reads them. They are full of what strangers wrote, and a message saying "turn this off"
                      must never reach something that can turn things off.
  acting as the account
                      no tool sends or posts. A setting that makes an account do something in public by itself can only
                      be switched off. Starting or stopping accounts, and the way out of careful mode, stay a click.

Every change is written down with what it replaced (config/ai_changes.json), so each can be undone. Only the standard
library at the top: the MCP process reads TOOLS from here without loading the rest of the app.
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import re
import threading
import time
import uuid

_PERSONA = {"type": "string", "description": "A persona's id, for its own settings. Leave it out for everyone's."}

TOOLS = [
    {
        "name": "search_settings",
        "title": "Search settings",
        "description": "Find LLMSelfbot's settings by what they do. Gives each one's key, what it does, what kind of "
                       "value it takes and what it is set to now. Use this first: change_setting needs an exact key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words for what you want, like 'typing speed' or 'quiet hours'."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "How many to return. 10 if left out."},
                "persona": _PERSONA,
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_setting",
        "title": "Read one setting",
        "description": "One setting in full, by its exact key.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "The setting's key."}, "persona": _PERSONA},
            "required": ["key"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "change_setting",
        "title": "Change a setting",
        "description": "Change one setting. It saves straight away and can be undone. Keys and logins, where things are "
                       "sent, starting or stopping accounts and anything public are locked: the person changes those "
                       "in the panel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The setting's key, from search_settings."},
                "value": {"type": "string", "description": "The new value as text: true or false, a number, one of its "
                                                           "choices, or JSON for a list or table."},
                "persona": _PERSONA,
            },
            "required": ["key", "value"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "undo_change",
        "title": "Undo a change",
        "description": "Put back what a change replaced. Without an id, undoes the latest one.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "The change's id, from recent_changes."}},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "recent_changes",
        "title": "Recent changes",
        "description": "The changes an AI has made here, newest first, with the ids undo_change takes.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list_personas",
        "title": "List personas",
        "description": "The personas: who the accounts can speak as.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "read_persona",
        "title": "Read a persona",
        "description": "A persona's text: who it is and how it talks.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "The persona's id, from list_personas."}},
            "required": ["id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "write_persona",
        "title": "Rewrite a persona",
        "description": "Replace a persona's whole text. Read it first and keep what should stay. It can be undone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The persona's id."},
                "text": {"type": "string", "description": "The whole new text."},
            },
            "required": ["id", "text"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "edit_persona",
        "title": "Edit a persona",
        "description": "Replace pieces of a persona's text and leave the rest. Use this to fill in its blanks or change a "
                       "line, every piece in one call. It can be undone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The persona's id."},
                "edits": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Each piece to change.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "find": {"type": "string", "description": "The exact text to replace. It has to be there once."},
                            "replace": {"type": "string", "description": "What goes there instead."},
                        },
                        "required": ["find", "replace"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["id", "edits"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "create_persona",
        "title": "Make a persona",
        "description": "Make a new persona from the app's template. The answer has its text: fill in the blanks with "
                       "edit_persona, all in one call. No account uses it until the person gives it to one in the panel.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Its name."}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
]

NAMES = frozenset(t["name"] for t in TOOLS)

INSTRUCTIONS = ("Tools for setting up LLMSelfbot, an app that runs AI replies on the person's own accounts. Search before "
                "you change anything, change one thing at a time, and say what you changed. Every change can be undone. "
                "A setting marked locked can only be changed by the person, in the app's Settings page.")

#: The most changes kept, oldest dropped first.
KEEP = 60
_MAX_TEXT = 60_000
_lock = threading.Lock()


class ToolError(Exception):
    """What went wrong, in words the AI can pass on. Not a crash."""


# ── What an AI may not touch ─────────────────────────────────────────────────────────────────────

SECRET = "Keys and logins stay in the panel."
WHERE = "Where things are sent stays in the panel."
SERVICE = "Starting and stopping accounts stays in the panel."
CAREFUL = "Careful mode's way out stays in the panel."
PUBLIC = "What an account does in public stays in the panel."
REACH = "Who it answers stays in the panel."
DRY_RUN = "Starting to send for real stays in the panel."

# A public switch that is not in one of stealth.PUBLIC_PARTS: answers people have not asked for, or something seen by others.
_PUBLIC_KEYS = re.compile(
    r"(\.accept_\w+|\.auto_add_friends|\.follow_back|\.stories(\.\w+)?|\.status(\.\w+)?|\.voice_notes|"
    r"\.reels\.\w+|\.watch\.\w+|\.night_activity_status|\.answer_first|\.join_when_asked|\.auto_login|\.accept_unknown|"
    r"\.gifts(\.\w+)?|reddit\.subreddits|bot\.friend_requests\.\w+|bot\.nudge\.\w+|bot\.calls\.(vc|enabled|you_can_dial|reply_ring))$")
# Each of these lets it answer in more places, so an AI can close them and not open them.
_REACH_KEYS = frozenset(("bot.allow_dm", "bot.allow_gc", "bot.allow_server", "whatsapp.groups.enabled", "imessage.groups",
                         "imessage.answer_sms", "telegram.groups"))
# Where it is sent, by its name: a model pointed at somewhere else would be sent every chat.
_WHERE_KEYS = re.compile(r"(_url|\.url|_host|\.host|\.port|_endpoint)$")
# In a public block these narrow what it reaches, so turning one off widens it.
_NARROWING = re.compile(r"skip|only|fresh|strangers")


def _secret(key: str) -> bool:
    """A key, a token, a login. max_reply_tokens is a length, not a token."""
    from app.web import settings_io
    return settings_io.personal(key) and not key.endswith("_tokens")


def _public(key: str) -> bool:
    from app.utils import stealth
    parts = key.split(".")
    return (len(parts) >= 3 and parts[1] in stealth.PUBLIC_PARTS) or bool(_PUBLIC_KEYS.search(key))


def limit_of(key: str) -> tuple:
    """What an AI may do with a setting, and why not more: ("", "") anything, ("off", why) only switch it off, ("on",
    why) only switch it on, ("none", why) leave it alone."""
    from app.utils import socials
    from app.web import settings_io
    if _secret(key):
        return "none", SECRET
    if key in settings_io.CAREFUL or _WHERE_KEYS.search(key):
        return "none", WHERE
    if key.startswith("services.") or key in socials.SWITCHES:
        return "none", SERVICE
    if key == "bot.conservative.enabled":
        return "on", CAREFUL
    if key.startswith("bot.conservative."):
        return "none", CAREFUL
    if key.endswith(".dry_run"):
        return "on", DRY_RUN
    if key in _REACH_KEYS:
        return "off", REACH
    if key == "whatsapp.groups.only_when_named":
        return "on", REACH      # off, it talks in groups with nobody speaking to it
    if _public(key):
        leaf = key.rsplit(".", 1)[-1]
        return ("none" if _NARROWING.search(leaf) else "off"), PUBLIC
    return "", ""


def _refuse_locked(f: dict) -> None:
    """Before anything is made of the value: what a locked setting can hold is none of an AI's business."""
    limit, why = limit_of(f["key"])
    if limit == "none" or (limit and f.get("type") != "bool"):
        raise ToolError(f"{f['label']} is locked. {why}")


def _allowed(f: dict, value) -> None:
    limit, why = limit_of(f["key"])
    if limit == "off" and value is not False:
        raise ToolError(f"{f['label']} can only be switched off from here. {why}")
    if limit == "on" and value is not True:
        raise ToolError(f"{f['label']} can only be switched on from here. {why}")


def _secrets() -> list:
    """What must never leave in an answer: every secret in config/.env."""
    from app.web.envfile import SECRET_KEYS, read_env
    return [v for k, v in read_env().items() if SECRET_KEYS.match(k) and v and len(v) >= 8]


def _scrub(value, secrets: list):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[hidden]")
        return value
    if isinstance(value, list):
        return [_scrub(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v, secrets) for k, v in value.items()}
    return value


# ── Settings, as an AI sees them ─────────────────────────────────────────────────────────────────

_KINDS = {"bool": "on or off", "int": "a whole number", "float": "a number", "str": "text", "json": "a list or table, as JSON"}


@functools.lru_cache(maxsize=1)
def _all_choices() -> dict:
    """Each dropdown's options, the same file the panel draws them from."""
    from app.utils.paths import APP_DIR
    return json.loads((APP_DIR / "resources" / "setting_choices.json").read_text(encoding="utf-8"))


def _choices(key: str) -> list:
    return [str(c["value"]) for c in _all_choices().get(key, [])]


def short(value, room: int = 160) -> str:
    """A value in a few words, for a person to read."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None or value == "" or value == [] or value == {}:
        return "not set"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= room else text[:room - 1].rstrip() + "…"


def _fields(persona: str = "") -> list:
    """Every setting that exists right now: a social switched off is shown nowhere, to an AI either."""
    from app.utils import socials
    from app.web.routes import config_routes
    on = socials.on()

    def shown(key: str) -> bool:
        parts = key.split(".")
        return on.get(parts[1] if parts[0] == "services" and len(parts) > 1 else parts[0], True)

    return [f for f in config_routes.fields_for(persona)["fields"] if shown(f["key"])]


def _view(f: dict, whole: bool = False) -> dict:
    """One setting as an AI gets it. A secret comes with no value at all, only that it is there."""
    key = f["key"]
    out = {"key": key, "label": f.get("label") or key, "section": f.get("section") or "",
           "kind": _KINDS.get(f.get("type"), "text")}
    if f.get("description"):
        out["what_it_does"] = f["description"]
    if f.get("unit"):
        out["unit"] = f["unit"]
    for name in ("min", "max", "step"):
        if f.get(name) is not None:
            out[name] = f[name]
    if key in _all_choices():
        out["choices"] = [{"value": c["value"], "means": c.get("hint") or c.get("label")} for c in _all_choices()[key]]
    if f.get("requires_restart"):
        out["needs_restart"] = True
    if f.get("global_only"):
        out["same_for_every_persona"] = True
    limit, why = limit_of(key)
    if why:
        one_way = limit in ("off", "on") and f.get("type") == "bool"
        out["locked"] = f"Can only be switched {limit} from here. {why}" if one_way else why
    if not _secret(key):
        value = f.get("current")
        out["value"] = value if whole or isinstance(value, (bool, int, float)) or value is None else short(value)
    return out


def _words(text: str) -> list:
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", text.lower())]


def search(fields: list, query: str, limit: int = 10) -> list:
    """The settings that best match the words: a word in the name counts most, then the key, then what it does."""
    wanted = _words(query)
    phrase = " ".join(re.findall(r"[a-z0-9]+", query.lower()))
    scored = []
    for f in fields:
        label = _words(f.get("label") or "")
        key = _words(f["key"])
        about = _words(f.get("description") or "")
        section = _words(f.get("section") or "")
        score = sum((6 if w in label else 0) + (3 if w in key else 0) + (2 if w in about else 0) + (1 if w in section else 0)
                    for w in wanted)
        if not score:
            continue
        if phrase and (phrase in " ".join(label) or phrase in " ".join(about)):
            score += 5
        scored.append((score + (1 if f.get("common") else 0), f))
    scored.sort(key=lambda pair: -pair[0])
    return [f for _, f in scored[:limit]]


def _coerce(f: dict, raw):
    """The value to save, from what the AI sent, or ToolError saying what this setting takes."""
    from app.web import settings_io
    label, kind = f["label"], f.get("type")
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        word = str(raw).strip().lower()
        if word in ("true", "on", "yes", "1"):
            return True
        if word in ("false", "off", "no", "0"):
            return False
        raise ToolError(f"{label} is on or off: send true or false.")
    if kind in ("int", "float"):
        try:
            if isinstance(raw, bool):
                raise ValueError
            number = float(str(raw).strip())
        except ValueError:
            raise ToolError(f"{label} takes a number.") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ToolError(f"{label} takes a number.")
        if kind == "int":
            if not number.is_integer():
                raise ToolError(f"{label} takes a whole number.")
            number = int(number)
        if f.get("min") is not None and number < f["min"]:
            raise ToolError(f"{label} cannot go below {f['min']}.")
        if f.get("max") is not None and number > f["max"]:
            raise ToolError(f"{label} cannot go above {f['max']}.")
        return number
    if kind == "json":
        value = raw
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except ValueError:
                raise ToolError(f"{label} takes JSON.") from None
        try:
            return settings_io._check(f["key"], value, f.get("current"), None)
        except ValueError as e:
            raise ToolError(f"{label} {e}.") from None
    if isinstance(raw, (list, dict)):
        raise ToolError(f"{label} takes text.")
    value = "" if raw is None else str(raw)
    if len(value) > settings_io.MAX_TEXT:
        raise ToolError(f"{label} is too long.")
    allowed = _choices(f["key"])
    if allowed and value not in allowed:
        raise ToolError(f"{label} has to be one of: {', '.join(allowed)}.")
    return value


# ── The log of changes ───────────────────────────────────────────────────────────────────────────

def _log_path():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config" / "ai_changes.json"


def _load() -> list:
    try:
        data = json.loads(_log_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(entries: list) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + f".{uuid.uuid4().hex}.part")
    part.write_text(json.dumps(entries[-KEEP:], ensure_ascii=False), encoding="utf-8")
    os.replace(part, path)


def _record(**entry) -> dict:
    entry.update(id=uuid.uuid4().hex[:10], ts=time.time(), undone=False)
    with _lock:
        entries = _load()
        entries.append(entry)
        _save(entries)
    return entry


def _mark_undone(change_id: str) -> None:
    with _lock:
        entries = _load()
        for entry in entries:
            if entry.get("id") == change_id:
                entry["undone"] = True
        _save(entries)


def recent(limit: int = 40) -> list:
    """The changes, newest first, as words: what a persona's text was is kept for undoing, never handed back here."""
    out = []
    for e in reversed(_load()[-max(1, limit):]):
        out.append({k: e.get(k) for k in ("id", "ts", "who", "kind", "label", "scope", "before", "after", "undone")})
    return out


def _persona_name(pid: str) -> str:
    from app.utils import personas
    info = personas.get(pid) if pid else None
    return info["name"] if info else "everyone"


# ── The tools ────────────────────────────────────────────────────────────────────────────────────

def _find_persona(said: str) -> str:
    """The persona meant: by its id, or by the name a model is as likely to send."""
    from app.utils import personas
    if said and personas.exists(said):
        return said
    for p in personas.list_all():
        if p["name"].strip().lower() == said.lower():
            return p["id"]
    raise ToolError("There is no persona with that id. list_personas shows them.")


def _persona_arg(args: dict, ctx: dict) -> str:
    said = str(args.get("persona") or ctx.get("persona") or "").strip()
    return _find_persona(said) if said else ""


def _persona_id(args: dict) -> str:
    return _find_persona(str(args.get("id") or "").strip())


def _field(key: str, persona: str) -> dict:
    for f in _fields(persona):
        if f["key"] == key:
            return f
    raise ToolError(f"There is no setting called {key}. search_settings finds the right key.")


def _clean_text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{what} is empty.")
    if len(value) > _MAX_TEXT:
        raise ToolError(f"{what} is too long.")
    return value


async def _search_settings(args: dict, ctx: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("Say what to look for.")
    try:
        limit = max(1, min(30, int(args.get("limit") or 10)))
    except (TypeError, ValueError):
        limit = 10
    fields = await asyncio.to_thread(_fields, _persona_arg(args, ctx))
    found = search(fields, query, limit)
    if not found:
        return {"results": [], "note": "Nothing matches those words. Try others."}
    return {"results": [_view(f) for f in found]}


async def _get_setting(args: dict, ctx: dict) -> dict:
    key = str(args.get("key") or "").strip()
    return _view(await asyncio.to_thread(_field, key, _persona_arg(args, ctx)), whole=True)


def _before_state(key: str, persona: str) -> dict:
    """How the setting is written now, to put back exactly: a persona's own value or none, a value in the file or none."""
    from app.utils import configstore, personas
    from app.utils.helpers import load_base_config_copy
    if persona and not personas.is_global_only(key):
        own = personas.overridden(persona, key)
        return {"scope_persona": persona, "had": own,
                "raw": configstore.get_nested(personas.overrides(persona), key) if own else None}
    node = load_base_config_copy()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return {"scope_persona": "", "had": False, "raw": None}
        node = node[part]
    return {"scope_persona": "", "had": True, "raw": node}


async def _change_setting(args: dict, ctx: dict) -> dict:
    from fastapi import HTTPException
    from app.web.routes import config_routes
    key = str(args.get("key") or "").strip()
    persona = _persona_arg(args, ctx)
    f = await asyncio.to_thread(_field, key, persona)
    if "value" not in args:
        raise ToolError("Say what to change it to.")
    _refuse_locked(f)
    value = _coerce(f, args["value"])
    _allowed(f, value)
    current = f.get("current")
    if type(current) is type(value) and current == value:
        return {"changed": False, "label": f["label"], "note": "It is already set to that."}
    state = await asyncio.to_thread(_before_state, key, persona)
    try:
        saved = await config_routes.save_field(ctx["request"], key, value, state["scope_persona"])
    except HTTPException as e:
        raise ToolError(str(e.detail)) from None
    except OSError as e:
        raise ToolError(f"It could not be saved: {e}") from None
    scope = _persona_name(state["scope_persona"])
    entry = await asyncio.to_thread(
        lambda: _record(kind="setting", who=ctx["who"], key=key, label=f["label"], scope=scope,
                        persona=state["scope_persona"], had=state["had"], raw=state["raw"],
                        value=saved.get("value", value), previous=current, before=short(current), after=short(value)))
    out = {"changed": True, "change_id": entry["id"], "key": key, "label": f["label"], "for": scope,
           "from": entry["before"], "to": entry["after"]}
    if f.get("requires_restart"):
        out["needs_restart"] = True
    return out


def _remove_from_file(key: str) -> None:
    """The setting taken back out of config.yaml, for one that was not written there before the change."""
    from app.utils import configstore
    from app.utils.helpers import load_base_config_copy
    cfg = load_base_config_copy()
    node, parts = cfg, key.split(".")
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return
    if parts[-1] in node:
        del node[parts[-1]]
        configstore.write_base(cfg)


def _value_now(key: str, persona: str):
    try:
        return _field(key, persona).get("current")
    except ToolError:
        return None


async def _undo_setting(e: dict, ctx: dict) -> None:
    from app.utils import configstore
    from app.web.routes import config_routes
    key, persona = e["key"], e.get("persona") or ""
    now = await asyncio.to_thread(_value_now, key, persona)
    if now != e.get("value"):
        raise ToolError(f"{e['label']} has changed again since, so it was left as it is.")
    if e.get("had"):
        await config_routes.save_field(ctx["request"], key, e.get("raw"), persona)
        return
    if persona:
        await asyncio.to_thread(configstore.reset, key, persona)
    else:
        await asyncio.to_thread(_remove_from_file, key)
    await config_routes._live_apply(key, None, persona or None, ctx["request"])


async def _undo_persona_text(e: dict, ctx: dict) -> None:
    from app.utils import personas
    from app.web import live
    pid = e["persona"]
    if not personas.exists(pid):
        raise ToolError("That persona is gone.")
    if await asyncio.to_thread(personas.read_text, pid) != e.get("text_after"):
        raise ToolError("Its text has changed again since, so it was left as it is.")
    await asyncio.to_thread(personas.save_text, pid, e.get("text_before") or "")
    live.push(ctx["request"], "instructions_update", {}, persona=pid, platforms=("discord",))


async def _undo_persona_new(e: dict, ctx: dict) -> None:
    from app.utils import personas
    pid = e["persona"]
    if not personas.exists(pid):
        raise ToolError("That persona is gone already.")
    if personas.accounts_of(pid):
        raise ToolError("An account uses that persona now, so it was left.")
    await asyncio.to_thread(personas.delete, pid)


_UNDO = {"setting": _undo_setting, "persona_text": _undo_persona_text, "persona_new": _undo_persona_new}


async def _undo_change(args: dict, ctx: dict) -> dict:
    change_id = str(args.get("id") or "").strip()
    entries = await asyncio.to_thread(_load)
    if change_id:
        entry = next((e for e in entries if e.get("id") == change_id), None)
        if entry is None:
            raise ToolError("There is no change with that id. recent_changes shows them.")
        if entry.get("undone"):
            raise ToolError("That one is undone already.")
    else:
        entry = next((e for e in reversed(entries) if not e.get("undone")), None)
        if entry is None:
            raise ToolError("There is nothing to undo.")
    from fastapi import HTTPException
    try:
        await _UNDO[entry["kind"]](entry, ctx)
    except HTTPException as e:
        raise ToolError(str(e.detail)) from None
    except (OSError, ValueError) as e:
        raise ToolError(f"It could not be put back: {e}") from None
    await asyncio.to_thread(_mark_undone, entry["id"])
    return {"undone": True, "change_id": entry["id"], "label": entry["label"], "back_to": entry["before"]}


async def _recent_changes(args: dict, ctx: dict) -> dict:
    return {"changes": await asyncio.to_thread(recent, 30)}


def _list_personas_now() -> list:
    from app.utils import personas
    out = []
    for p in personas.list_all():
        text = personas.read_text(p["id"])
        out.append({"id": p["id"], "name": p["name"], "about": personas.vibe(text), "words": personas.words(text),
                    "accounts": len(personas.accounts_of(p["id"])), "is_default": p["is_default"]})
    return out


async def _list_personas(args: dict, ctx: dict) -> dict:
    return {"personas": await asyncio.to_thread(_list_personas_now)}


async def _read_persona(args: dict, ctx: dict) -> dict:
    from app.utils import personas
    pid = _persona_id(args)
    return {"id": pid, "name": _persona_name(pid), "text": await asyncio.to_thread(personas.read_text, pid)}


async def _write_persona(args: dict, ctx: dict) -> dict:
    pid = _persona_id(args)
    return await _save_persona_text(pid, _clean_text(args.get("text"), "The text"), ctx)


async def _edit_persona(args: dict, ctx: dict) -> dict:
    from app.utils import personas
    pid = _persona_id(args)
    edits = args.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ToolError("Say what to replace, and what with.")
    text = await asyncio.to_thread(personas.read_text, pid)
    # All of them or none: half a persona filled in is worse than either.
    for edit in edits:
        find, replace = (edit.get("find"), edit.get("replace")) if isinstance(edit, dict) else (None, None)
        if not isinstance(find, str) or not find or not isinstance(replace, str):
            raise ToolError("Each edit says what to find and what to replace it with.")
        count = text.count(find)
        if count == 0:
            raise ToolError(f"'{find[:60]}' is not in the persona, so nothing was changed. read_persona shows what is.")
        if count > 1:
            raise ToolError(f"'{find[:60]}' is there {count} times, so nothing was changed. Give more of it, so it is there once.")
        text = text.replace(find, replace)
    return await _save_persona_text(pid, _clean_text(text, "The text"), ctx)


async def _save_persona_text(pid: str, text: str, ctx: dict) -> dict:
    from app.utils import personas
    from app.web import live
    before = await asyncio.to_thread(personas.read_text, pid)
    name = _persona_name(pid)
    if text == before:
        return {"changed": False, "label": name, "note": "Its text is already that."}
    await asyncio.to_thread(personas.save_text, pid, text)
    live.push(ctx["request"], "instructions_update", {}, persona=pid, platforms=("discord",))
    entry = await asyncio.to_thread(
        lambda: _record(kind="persona_text", who=ctx["who"], label=f"{name}'s text", scope=name, persona=pid,
                        text_before=before, text_after=text, before="", after=""))
    return {"changed": True, "change_id": entry["id"], "label": entry["label"], "for": name, "from": "", "to": ""}


async def _create_persona(args: dict, ctx: dict) -> dict:
    from app.utils import personas
    name = _clean_text(args.get("name"), "The name").strip()
    try:
        made = await asyncio.to_thread(personas.create, name)
    except (ValueError, OSError) as e:
        raise ToolError(f"It could not be made: {e}") from None
    entry = await asyncio.to_thread(
        lambda: _record(kind="persona_new", who=ctx["who"], label=f"New persona: {made['name']}", scope=made["name"],
                        persona=made["id"], before="", after=""))
    return {"changed": True, "change_id": entry["id"], "persona_id": made["id"], "label": entry["label"], "from": "", "to": "",
            "text": await asyncio.to_thread(personas.read_text, made["id"]),
            "note": "No account uses it until the person gives it to one in the panel."}


_HANDLERS = {
    "search_settings": _search_settings,
    "get_setting": _get_setting,
    "change_setting": _change_setting,
    "undo_change": _undo_change,
    "recent_changes": _recent_changes,
    "list_personas": _list_personas,
    "read_persona": _read_persona,
    "write_persona": _write_persona,
    "edit_persona": _edit_persona,
    "create_persona": _create_persona,
}


async def call(name: str, args, request, who: str = "An AI", persona: str = "") -> dict:
    """Run one tool. ToolError says what went wrong, for the AI to read. `persona` is the one the page is showing."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ToolError(f"There is no tool called {name}.")
    ctx = {"request": request, "who": re.sub(r"\s+", " ", str(who or "An AI")).strip()[:40] or "An AI", "persona": persona}
    out = await handler(args if isinstance(args, dict) else {}, ctx)
    return _scrub(out, await asyncio.to_thread(_secrets))
