import asyncio
import re
import shutil
import time

import yaml
from fastapi import APIRouter, HTTPException, Request

from app.utils import configstore
from app.utils.helpers import invalidate_config_cache, load_config
from app.utils.paths import DATA_DIR
from app.web.envfile import (
    ENV_PATH,
    SECRET_KEYS as _SECRET_KEYS,
    mask as _mask,
    read_env as _read_env,
    write_env as _write_env,
)
from app.web.schema import CONFIG_SCHEMA, get_nested, set_nested

router = APIRouter(tags=["config"])

# The largest whole number a page can hold exactly. Discord IDs are bigger: the page's own JSON parser rounds 272402839874174976 to ...180, so an ID that went through it and back came out a different person.
_JS_SAFE = 2 ** 53 - 1


def _page_safe(value):
    """A value the page can hold without changing it: IDs past what it can count to go as text."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) > _JS_SAFE:
        return str(value)
    if isinstance(value, list):
        return [_page_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _page_safe(v) for k, v in value.items()}
    return value


def _write_config(cfg: dict):
    """Everyone's settings, written whole (app/utils/configstore.py: a backup first)."""
    configstore.write_base(cfg, CONFIG_PATH)


def _parse_text(text) -> object:
    """JSON sent as text, parsed here rather than on the page, so big IDs keep every digit."""
    import json as _json
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="The file is empty.")
    if len(text) > 2_000_000:
        raise HTTPException(status_code=400, detail="That file is too big to be a settings file.")
    try:
        return _json.loads(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"That is not valid JSON: {e}")

CONFIG_PATH = DATA_DIR / "config" / "config.yaml"
INSTRUCTIONS_PATH = DATA_DIR / "config" / "instructions.txt"


def _backup_config():
    """A copy before every write, only the newest forty kept (configstore.backup)."""
    configstore.backup(CONFIG_PATH)


def _dump(cfg: dict) -> None:
    """The config written, a backup first. Blocking: the routes run it on a thread."""
    configstore.write_base(cfg, CONFIG_PATH)


async def _live_apply(key: str, value=None, persona=None, request: Request | None = None):
    """A setting changed: the running Discord accounts it reaches read their settings again (app/web/live.py). The
    ones speaking as `persona`, or every one for a change to everyone's. They read the value from their own settings,
    never from this message: theirs may be their persona's own."""
    if request is None:
        return
    from app.web import live
    live.push(request, "config_update", {"key": key}, persona=persona or None, platforms=("discord",))


def _persona_param(persona) -> str:
    """A persona named by the page: one that exists, else none (everyone's settings)."""
    from app.utils import personas
    pid = str(persona or "").strip()
    if not pid:
        return ""
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    return pid


def _settings_for(persona: str) -> dict:
    """The settings an account with this persona runs with, or everyone's."""
    return configstore.effective(persona) if persona else load_config()


@router.get("/api/config")
async def get_config(request: Request, persona: str = ""):
    return _settings_for(_persona_param(persona))


@router.get("/api/config/raw")
def get_config_raw(request: Request):
    """The config as JSON text, for the raw editor. As text, not as a JSON body: the page parsing it rounded the owner ID, and saving wrote the rounded one back."""
    import json as _json
    return {"text": _json.dumps(load_config(), indent=2, ensure_ascii=False)}


@router.post("/api/config/raw")
async def post_config_raw(request: Request):
    body = await request.json()
    new_config = _parse_text(body.get("text"))
    if not isinstance(new_config, dict):
        raise HTTPException(status_code=400, detail="config must be an object")
    if "bot" not in new_config:
        raise HTTPException(status_code=400, detail="config is missing the required 'bot' section")
    _write_config(new_config)
    return {"ok": True}


def _template() -> dict:
    """The config the app ships with: what a setting holds when this one does not have it yet."""
    from app.utils.paths import DEFAULTS_DIR
    try:
        return yaml.safe_load((DEFAULTS_DIR / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


@router.get("/api/config/export")
def export_config(request: Request, personal: bool = False):
    """Every setting as a settings file. Sent as text for the same reason as the raw editor: an ID in it would be rounded by the page on its way to the file."""
    import json as _json
    from app.version import __version__
    from app.web import settings_io
    data = settings_io.export(load_config(), personal, __version__)
    stamp = time.strftime("%Y-%m-%d")
    return {"filename": f"llmselfbot-settings-{stamp}.json",
            "text": _json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            "count": len(settings_io.flatten(data["settings"]))}


@router.post("/api/config/import/preview")
async def import_preview(request: Request):
    """What importing this file would change, without writing anything."""
    from app.web import settings_io
    body = await request.json()
    data = _parse_text(body.get("text"))
    try:
        result = settings_io.plan(load_config(), _template(), data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _page_safe(result)


@router.post("/api/config/import")
async def import_settings(request: Request):
    """Write the settings picked from a file. The page names which ones; the values come from the file, checked again here."""
    from app.web import settings_io
    from app.web.logbus import bus
    body = await request.json()
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys:
        raise HTTPException(status_code=400, detail="Pick at least one setting to import.")
    data = _parse_text(body.get("text"))
    try:
        cfg, done = settings_io.apply(load_config(), _template(), data, keys)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not done:
        raise HTTPException(status_code=400, detail="None of those settings could be imported.")
    if "bot" not in cfg:
        raise HTTPException(status_code=400, detail="config is missing the required 'bot' section")
    _write_config(cfg)
    bus.append("system", f"Imported {len(done)} setting{'' if len(done) == 1 else 's'} from a file", "system")
    return {"ok": True, "applied": len(done), "restart": [c["label"] for c in done if c["restart"]]}


@router.post("/api/config")
async def post_config(request: Request):
    body = await request.json()
    new_config = body.get("config")
    if not isinstance(new_config, dict):
        raise HTTPException(status_code=400, detail="config must be an object")
    # Guard against a partial/empty save wiping the file, every reader assumes config["bot"] exists and the runners crash at import without it.
    if "bot" not in new_config:
        raise HTTPException(status_code=400, detail="config is missing the required 'bot' section")
    await asyncio.to_thread(_dump, new_config)
    return {"ok": True}


@router.post("/api/config/field")
async def set_field(request: Request):
    body = await request.json()
    key, value = body.get("key"), body.get("value")
    persona = _persona_param(body.get("persona"))
    if not key:
        raise HTTPException(status_code=400, detail="key required")
    # What it holds now, for the persona it is set for: the shape a new value has to have.
    cfg = _settings_for(persona)

    # A list or table (models, moods, openers, weight tables) is edited as JSON text in the UI. Writing that string straight into config.yaml would turn a list into a string and break every reader of it.
    existing = get_nested(cfg, key)
    # An ID comes back from the page as text (see _page_safe): written as text it would stop matching the number every reader compares it with.
    if isinstance(existing, int) and not isinstance(existing, bool) and isinstance(value, str):
        if re.fullmatch(r"\s*-?\d+\s*", value):
            value = int(value)
        elif key.endswith("_id"):
            raise HTTPException(status_code=400, detail=f"{key} should be a number")
    if isinstance(existing, (list, dict)) and isinstance(value, str):
        import json as _json
        try:
            value = _json.loads(value)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"{key} expects a list, and that is not valid JSON")
        if not isinstance(value, type(existing)):
            raise HTTPException(
                status_code=400,
                detail=f"{key} expects a {type(existing).__name__}")

    from app.utils import personas
    if persona and not personas.is_global_only(key):
        # This persona's own value (one the same as everyone's is not kept: configstore.set_value).
        await asyncio.to_thread(configstore.set_value, key, value, persona)
        await _live_apply(key, value, persona, request)
        return {"ok": True, "value": value, "scope": "persona"}
    # Everyone's: written to a copy, never to the cached dict every reader holds.
    from app.utils.helpers import load_base_config_copy
    base = load_base_config_copy()
    try:
        set_nested(base, key, value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Every switch and slider in Settings comes through here: written on a thread, not on the event loop.
    await asyncio.to_thread(_dump, base)
    await _live_apply(key, value, None, request)
    return {"ok": True, "value": value, "scope": "everyone"}


# Curly quotes and the rest, straight, the way the engine compares refusals (_norm in app/core/engine.py).
_STRAIGHT = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u2032": "'", "\u00b4": "'", "`": "'",
                           "\u201c": '"', "\u201d": '"'})


def _same_phrase(a, b) -> bool:
    norm = lambda s: " ".join(str(s).translate(_STRAIGHT).lower().split())  # noqa: E731
    return norm(a) == norm(b)


@router.post("/api/config/refusal-phrase")
async def add_refusal_phrase(request: Request):
    """A reply that read like an assistant, added to what counts as a refusal, from a message's right-click menu in
    Chats. Appended to bot.refusal.extra_phrases unless it is there already (in any case or quoting); the runners
    read it on their next reply, nothing restarts."""
    body = await request.json()
    phrase = " ".join(str(body.get("phrase") or "").split())[:300]
    if len(phrase) < 3:
        raise HTTPException(status_code=400, detail="too short to be a phrase")
    key = "bot.refusal.extra_phrases"
    # Everyone's, on a copy: the cached dict is every reader's.
    from app.utils.helpers import load_base_config_copy
    cfg = load_base_config_copy()
    current = get_nested(cfg, key)
    current = [p for p in current if isinstance(p, str)] if isinstance(current, list) else []
    enabled = (get_nested(cfg, "bot.refusal.enabled") is not False)
    if any(_same_phrase(p, phrase) for p in current):
        return {"ok": True, "added": False, "phrases": current, "enabled": enabled}
    current.append(phrase)
    try:
        set_nested(cfg, key, current)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await asyncio.to_thread(_dump, cfg)
    await _live_apply(key, current, None, request)
    return {"ok": True, "added": True, "phrases": current, "enabled": enabled}


@router.get("/api/config/schema")
def schema(request: Request, persona: str = ""):
    """Every setting in config.yaml, described. The curated list supplies labels, ranges and ordering; anything in the file it does not mention is appended automatically. Hand listing alone left 32 of 75 settings with no control at all.

    With a persona, each field's value is that persona's, and says whether it is the persona's own (`overridden`),
    what everyone has (`base`), and whether it can differ per persona at all (`global_only`)."""
    from app.utils import personas
    from app.web import descriptions as desc

    pid = _persona_param(persona)
    cfg = _settings_for(pid)
    base_cfg = load_config()
    out, seen = [], set()

    for field in CONFIG_SCHEMA:
        # Moods and reactions are edited on the Persona page, where they belong. Listing them here too would be two editors for one setting.
        if desc.is_hidden(field["key"]):
            continue
        f = dict(field)
        f["current"] = get_nested(cfg, f["key"])
        # A setting added after this config.yaml was written is missing from it, not switched off. Show what the app actually uses in that case.
        if f["current"] is None and "default" in f:
            f["current"] = f["default"]
        # An ID is edited as text: as a number field the page rounded it, and saved the rounded one.
        if f["key"].endswith("_id") and f["type"] == "int":
            f["type"] = "str"
            f["current"] = "" if f["current"] is None else str(f["current"])
        f["description"] = desc.DESCRIPTIONS.get(f["key"], "")
        f["requires_restart"] = desc.needs_restart(f["key"])
        f["common"] = f["key"] in desc.COMMON
        out.append(f)
        seen.add(f["key"])

    for key, value in desc.walk(cfg):
        if key in seen or desc.is_hidden(key):
            continue
        out.append({
            "key": key,
            "type": desc.infer_type(value),
            "label": desc.label_for(key),
            "section": desc.section_for(key),
            "description": desc.DESCRIPTIONS.get(key, ""),
            "requires_restart": desc.needs_restart(key),
            "common": key in desc.COMMON,
            "current": value,
        })
        seen.add(key)
    for f in out:
        f["global_only"] = personas.is_global_only(f["key"])
        if pid:
            f["overridden"] = personas.overridden(pid, f["key"])
            f["base"] = _page_safe(get_nested(base_cfg, f["key"]))
    info = personas.get(pid) if pid else None
    return {"fields": out, "persona": {"id": pid, "name": info["name"], "color": info["color"]} if info else None}


@router.get("/api/discord/build-number")
async def discord_build_number(request: Request):
    """Discord's current stable client build number, for the "Latest" button beside the desktop build number in Settings. It is read off Discord's web app the same way the automatic build source reads it (app/utils/session.py), freshly: the button is pressed to find out what it is now, not what it was this morning. Discord does not publish the number, so when it cannot be read this says so rather than inventing one."""
    from app.utils import session
    session._BUILD_FETCHED_AT = 0.0
    number = await session._fetch_build_number()
    if not number:
        raise HTTPException(status_code=502, detail="Could not read the build number off Discord just now. Try again in a moment.")
    return {"build_number": number}


@router.get("/api/models")
async def models(request: Request, refresh: bool = False):
    """Every model Groq currently offers, for the pickers in Settings. Model names are otherwise typed by hand, and Groq retires them without warning: the bot then fails every reply with a 404 that reads like it is simply broken. The live list removes the guesswork."""
    import asyncio
    from app.utils.groqmodels import available, check_configured

    def work():
        data = available(force=refresh)
        try:
            problems = check_configured(load_config())
        except Exception:
            problems = []
        return {**data, "problems": problems}

    # Asking Groq is a blocking HTTP call, so it runs on a thread: on the event loop it froze every other request for the length of the round trip.
    return await asyncio.to_thread(work)


@router.get("/api/secrets")
def get_secrets(request: Request):
    values = _read_env()
    masked = {k: (_mask(v) if _SECRET_KEYS.match(k) else v) for k, v in values.items()}
    return {"secrets": masked}


@router.post("/api/secrets")
async def post_secrets(request: Request):
    body = await request.json()
    updates = body.get("secrets", {})
    values = _read_env()
    for key, value in updates.items():
        if not isinstance(value, str):
            continue
        # Masked values are left untouched, only real changes are written.
        if _SECRET_KEYS.match(key) and value and value.count("…") == 1:
            continue
        values[key] = value
    _write_env(values)
    return {"ok": True}


@router.get("/api/instructions")
def get_instructions(request: Request):
    # Plain def: FastAPI reads the file on its threadpool, not on the event loop.
    text = INSTRUCTIONS_PATH.read_text(encoding="utf-8") if INSTRUCTIONS_PATH.exists() else ""
    return {"text": text}


def _save_instructions(text: str) -> None:
    backups = DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    if INSTRUCTIONS_PATH.exists():
        shutil.copyfile(INSTRUCTIONS_PATH, backups / f"instructions-{int(time.time())}.txt")
    INSTRUCTIONS_PATH.write_text(text, encoding="utf-8")


@router.post("/api/instructions")
async def post_instructions(request: Request):
    """Default's text (the Personas page saves any persona's through /api/personas/{id}/text)."""
    body = await request.json()
    text = body.get("text", "")
    await asyncio.to_thread(_save_instructions, text)
    from app.web import live
    live.push(request, "instructions_update", {}, persona="default", platforms=("discord",))
    return {"ok": True}
