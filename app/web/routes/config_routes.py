import re
import shutil
import time

import yaml
from fastapi import APIRouter, HTTPException, Request

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

CONFIG_PATH = DATA_DIR / "config" / "config.yaml"
INSTRUCTIONS_PATH = DATA_DIR / "config" / "instructions.txt"

def _backup_config():
    backups = DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CONFIG_PATH, backups / f"config-{int(time.time())}.yaml")


async def _live_apply(key: str, value, target=None):
    """Push a leaf key through the runner's config_update IPC when possible."""
    if target is None:
        return
    from app.core import ipc
    try:
        await ipc.send_and_wait(target, "config_update", {"key": key, "value": value}, timeout=6.0)
    except Exception:
        pass


@router.get("/api/config")
async def get_config(request: Request):
    return load_config()


@router.post("/api/config")
async def post_config(request: Request):
    body = await request.json()
    new_config = body.get("config")
    if not isinstance(new_config, dict):
        raise HTTPException(status_code=400, detail="config must be an object")
    # Guard against a partial/empty save wiping the file, every reader assumes
    # config["bot"] exists and the runners crash at import without it.
    if "bot" not in new_config:
        raise HTTPException(status_code=400, detail="config is missing the required 'bot' section")
    _backup_config()
    CONFIG_PATH.write_text(
        yaml.safe_dump(new_config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    invalidate_config_cache()
    return {"ok": True}


@router.post("/api/config/field")
async def set_field(request: Request):
    body = await request.json()
    key, value = body.get("key"), body.get("value")
    target = body.get("target")
    if not key:
        raise HTTPException(status_code=400, detail="key required")
    cfg = load_config()

    # A list or table (models, moods, openers, weight tables) is edited as JSON
    # text in the UI. Writing that string straight into config.yaml would turn
    # a list into a string and break every reader of it.
    existing = get_nested(cfg, key)
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

    try:
        set_nested(cfg, key, value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _backup_config()
    CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    invalidate_config_cache()
    await _live_apply(key, value, target)
    return {"ok": True, "value": value}


@router.get("/api/config/schema")
async def schema(request: Request):
    """Every setting in config.yaml, described.

    The curated list supplies labels, ranges and ordering; anything in the file
    it does not mention is appended automatically. Hand listing alone left 32 of
    75 settings with no control at all.
    """
    from app.web import descriptions as desc

    cfg = load_config()
    out, seen = [], set()

    for field in CONFIG_SCHEMA:
        # Moods and reactions are edited on the Persona page, where they belong.
        # Listing them here too would be two editors for one setting.
        if desc.is_hidden(field["key"]):
            continue
        f = dict(field)
        f["current"] = get_nested(cfg, f["key"])
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
    return {"fields": out}


@router.get("/api/models")
async def models(request: Request, refresh: bool = False):
    """Every model Groq currently offers, for the pickers in Settings.

    Model names are otherwise typed by hand, and Groq retires them without
    warning: the bot then fails every reply with a 404 that reads like it is
    simply broken. The live list removes the guesswork.
    """
    import asyncio
    from app.utils.groqmodels import available, check_configured

    def work():
        data = available(force=refresh)
        try:
            problems = check_configured(load_config())
        except Exception:
            problems = []
        return {**data, "problems": problems}

    # Asking Groq is a blocking HTTP call, so it runs on a thread: on the event
    # loop it froze every other request for the length of the round trip.
    return await asyncio.to_thread(work)


@router.get("/api/secrets")
async def get_secrets(request: Request):
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
async def get_instructions(request: Request):
    text = INSTRUCTIONS_PATH.read_text(encoding="utf-8") if INSTRUCTIONS_PATH.exists() else ""
    return {"text": text}


@router.post("/api/instructions")
async def post_instructions(request: Request):
    body = await request.json()
    text = body.get("text", "")
    target = body.get("target")
    backups = DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    if INSTRUCTIONS_PATH.exists():
        shutil.copyfile(INSTRUCTIONS_PATH, backups / f"instructions-{int(time.time())}.txt")
    INSTRUCTIONS_PATH.write_text(text, encoding="utf-8")
    if target:
        from app.core import ipc
        try:
            await ipc.send_and_wait(target, "instructions_update", {"text": text}, timeout=6.0)
        except Exception:
            pass
    return {"ok": True}
