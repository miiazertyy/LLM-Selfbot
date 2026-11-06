"""The Models tab: providers, their keys, and which model does which job.

See app/utils/providers.py for the shape of it. Everything that touches the
network (listing a provider's models, trying one) runs on a thread.
"""
import asyncio
import json
import time
import urllib.error
import urllib.request

import yaml
from fastapi import APIRouter, HTTPException, Request

from app.utils import providers
from app.utils.helpers import invalidate_config_cache, load_config
from app.web.envfile import read_env, reload_into_process, write_env
from app.web.routes.env_routes import _family_values, _write_family

router = APIRouter(tags=["models"])


def _provider_rows(config: dict) -> list:
    env = read_env()
    rows = []
    for p in providers.PROVIDERS:
        pid = p["id"]
        keys = providers.keys_for(pid)
        rows.append({
            "id": pid, "name": p["name"], "site": p["site"], "blurb": p["blurb"],
            "cost": providers.COST.get(pid, ("paid", ""))[0],
            "cost_note": providers.COST.get(pid, ("paid", ""))[1],
            "jobs": p["jobs"], "env": p["env"],
            "keys": len(keys),
            "ready": providers.usable(pid, config),
            "base_url": providers.base_url(pid, config),
            # Whether a key line exists at all, so "remove" knows there is something to remove.
            "stored": bool(p["env"]) and any(k == p["env"] or k.startswith(p["env"] + "_") for k in env),
        })
    return rows


def _scoped(persona: str) -> tuple:
    """(persona id or "", the settings it runs with): everyone's when none is named."""
    from app.utils import configstore, personas
    pid = str(persona or "").strip()
    if pid and not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    return pid, (configstore.effective(pid) if pid else load_config())


@router.get("/api/providers")
def list_providers(request: Request, persona: str = ""):
    _pid, config = _scoped(persona)
    bot = config.get("bot") or {}
    defaults = {j: providers.groq_fallback(config, j) for j in providers.JOBS}
    if (bot.get("tts") or {}).get("voice"):
        defaults["tts"]["voice"] = bot["tts"]["voice"]
    return {"providers": _provider_rows(config), "plan": providers.plan(config), "defaults": defaults,
            "explicit": bool(((config.get("bot") or {}).get("models") or {}).get("replies")),
            "max_reply_tokens": (config.get("bot") or {}).get("max_reply_tokens", 320)}


@router.get("/api/providers/{pid}/models")
async def provider_models(pid: str, refresh: bool = False):
    if pid not in providers.BY_ID:
        raise HTTPException(status_code=404, detail="unknown provider")
    config = load_config()
    return await asyncio.to_thread(providers.list_models, pid, config, refresh)


@router.post("/api/providers/{pid}/key")
async def set_key(pid: str, request: Request):
    """Save (or with an empty key, remove) a provider's API key in .env."""
    p = providers.BY_ID.get(pid)
    if not p or not p["env"]:
        raise HTTPException(status_code=400, detail="that provider takes no key")
    body = await request.json()
    key = str(body.get("key") or "").strip()
    if any(c.isspace() for c in key):
        raise HTTPException(status_code=400, detail="a key has no spaces in it")
    values = read_env()
    keys = _family_values(values, p["env"])
    if key in keys:
        return {"ok": True, "keys": len(providers.keys_for(pid))}
    if key and not keys:
        values[p["env"]] = key
    else:
        # Added behind the ones it has, or with no key at all, every one of them gone: Disconnect.
        _write_family(values, p["env"], [*keys, key] if key else [])
    await asyncio.to_thread(write_env, values)
    reload_into_process(values)
    providers._cache.pop(pid, None)
    return {"ok": True, "keys": len(providers.keys_for(pid))}


def _wont_load(model: str, config: dict, detail: str) -> str:
    """Why a model on this computer would not load, when the file says: llama.cpp's router answers only "failed to
    load", which Try showed as "This computer answered 500." for a LoRA downloaded as the model. "" otherwise."""
    from app.utils import localfix
    if not localfix.load_failure(detail):
        return ""
    base = providers.local_settings(config)["base_url"]
    try:
        info = localfix.inspect(model, base)
        if info and info["helper"]:
            return f"The file is {localfix.what(info['kind'])}, not the model itself."
        big = localfix.too_big(model, base)
    except Exception:
        return ""
    if big:
        return (f"It would not load: it needs about {big['need'] / localfix.GB:.1f} GB of memory, and this computer "
                f"can give a model about {big['budget'] / localfix.GB:.1f} GB.")
    return ""


def _try(pid: str, model: str, config: dict) -> dict:
    """One tiny request, to see that a model answers and how fast: with the key a reply would use, and so on to the
    next the way a reply would."""
    if pid == "local":
        return _try_with(pid, model, config, providers.local_settings(config)["api_key"])
    keys = providers.key_order(pid)
    if not keys:
        return {"ok": False, "error": "No key set."}
    out = {}
    for key in keys:
        out = _try_with(pid, model, config, key)
        rest = providers.key_at_fault(out.pop("status", 0))
        if out["ok"] or not rest:
            break
        providers.rest_key(pid, key, rest)
    return out


def _try_with(pid: str, model: str, config: dict, key: str) -> dict:
    url = providers.base_url(pid, config).rstrip("/") + "/chat/completions"
    # The same cap a reply is sent with, so a model that passes here passes there too. It was 16, which a
    # model that thinks first (gpt-oss, qwen3, deepseek-r1) spends entirely on thinking: an empty answer.
    try:
        cap = max(96, int(((config or {}).get("bot") or {}).get("max_reply_tokens") or 320))
    except (TypeError, ValueError):
        cap = 320
    body = json.dumps({"model": model, "max_tokens": cap,
                       "messages": [{"role": "user", "content": "Reply with just the word: ok"}]}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "content-type": "application/json", "authorization": f"Bearer {key}",
        "user-agent": providers.user_agent()})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "reply": text.strip()[:80]}
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        error, detail = providers.http_error(pid, e.code, raw)
        if pid == "local":
            error = _wont_load(model, config, detail) or error
        return {"ok": False, "error": error, "detail": detail, "status": e.code}
    except Exception as e:
        slow = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
        if slow and pid == "local":
            # It answered nothing for 40 seconds: on this computer that has been a model too big for its memory,
            # paged to the disk as it works. Said so, rather than "Could not reach it (TimeoutError)".
            try:
                from app.utils import localfix
                big = localfix.too_big(model, providers.local_settings(config)["base_url"])
            except Exception:
                big = None
            if big:
                return {"ok": False, "error": f"No answer in 40 seconds: it is too big for this computer. "
                                              f"{localfix.too_big_words(big)[0].upper()}{localfix.too_big_words(big)[1:]}."}
            return {"ok": False, "error": "No answer in 40 seconds. It may still be loading: try again in a minute."}
        if slow:
            return {"ok": False, "error": "No answer in 40 seconds."}
        return {"ok": False, "error": f"Could not reach it ({type(e).__name__})."}


@router.post("/api/providers/{pid}/try")
async def try_model(pid: str, request: Request):
    if pid not in providers.BY_ID:
        raise HTTPException(status_code=404, detail="unknown provider")
    body = await request.json()
    model = str(body.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model required")
    return await asyncio.to_thread(_try, pid, model, load_config())


def _clean_entry(raw, job: str = "") -> dict | None:
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("provider") or "").strip()
    model = str(raw.get("model") or "").strip()
    if not pid and not model:
        return {"provider": "", "model": ""}          # unset: back to Groq's default
    if pid not in providers.BY_ID or not model:
        raise HTTPException(status_code=400, detail=f"{job or 'reply'}: pick a provider and a model")
    need = providers.JOBS[job]["needs"] if job else "chat"
    if need not in providers.BY_ID[pid]["jobs"]:
        raise HTTPException(status_code=400,
                            detail=f"{providers.BY_ID[pid]['name']} cannot do that job through this app")
    out = {"provider": pid, "model": model}
    if job == "tts" and raw.get("voice"):
        out["voice"] = str(raw["voice"]).strip()
    return out


@router.post("/api/models/plan")
async def save_plan(request: Request, persona: str = ""):
    """Save which model does which job: for everyone, or as one persona's own (?persona=).

    Written to bot.models, and mirrored into the old keys (groq_models,
    groq_*_model, bot.local.*) so everything that still reads those - the
    health checks, the Telegram status, the Local AI panel - agrees with it.
    """
    pid, _cfg = _scoped(persona)
    body = await request.json()
    replies = body.get("replies")
    if not isinstance(replies, list):
        raise HTTPException(status_code=400, detail="replies: a list of models")
    chain = [e for e in (_clean_entry(r) for r in replies) if e and e["provider"]]
    # None at all is allowed: Groq's models, as before anything was picked. The only model left could not be taken
    # off otherwise, even one removed from the computer it ran on.
    if replies and not chain:
        raise HTTPException(status_code=400, detail="at least one model has to write replies")
    seen, uniq = set(), []
    for e in chain:
        if (e["provider"], e["model"]) not in seen:
            seen.add((e["provider"], e["model"]))
            uniq.append(e)
    # A job is one entry or a list of them, tried in order; an empty list is "Groq's default".
    jobs = {}
    for j in providers.JOBS:
        if j not in body:
            continue
        raw = body.get(j)
        items = raw if isinstance(raw, list) else [raw]
        cleaned = [e for e in (_clean_entry(x, j) for x in items if x) if e and e["provider"]]
        seen_j, uniq_j = set(), []
        for e in cleaned:
            if (e["provider"], e["model"]) not in seen_j:
                seen_j.add((e["provider"], e["model"]))
                uniq_j.append(e)
        jobs[j] = uniq_j

    from app.web.routes.config_routes import CONFIG_PATH

    def write():
        import copy
        from app.utils import configstore, personas
        from app.utils.helpers import load_base_config
        # Worked out on a copy of the settings it is for (never the cached dict every reader holds).
        cfg = copy.deepcopy(configstore.effective(pid) if pid else load_base_config())
        bot = cfg.setdefault("bot", {})
        models = dict(bot.get("models") or {})
        if uniq:
            models["replies"] = uniq
        else:
            models.pop("replies", None)
        groq_chain = [e["model"] for e in uniq if e["provider"] == "groq"]
        if groq_chain:
            bot["groq_models"] = groq_chain
        local = dict(bot.get("local") or {})
        local_models = [e["model"] for e in uniq if e["provider"] == "local"]
        local["enabled"] = bool(local_models)
        if local_models:
            local["model"] = local_models[0]
        for j, chain_j in jobs.items():
            spec = providers.JOBS[j]
            entry = chain_j[0] if chain_j else {"provider": "", "model": ""}
            if not chain_j:
                models.pop(j, None)
            else:
                models[j] = chain_j if len(chain_j) > 1 else chain_j[0]
                if entry["provider"] == "groq":
                    bot[spec["groq_key"]] = entry["model"]
            if spec["local_key"]:
                local[spec["local_key"]] = entry["model"] if entry["provider"] == "local" else ""
            if j == "tts":
                local["tts_voice"] = entry.get("voice", "") if entry["provider"] == "local" else ""
                if entry["provider"] == "groq" and entry.get("voice"):
                    bot.setdefault("tts", {})["voice"] = entry["voice"]
        local["vision"] = False           # superseded by vision_model
        bot["local"] = local
        bot["models"] = models
        if not pid:
            configstore.write_base(cfg, CONFIG_PATH)
            return
        # A persona's own: each part of the plan that differs from everyone's, kept as its own (the model server's
        # address and the like inside bot.local are everyone's, and left out: personas.set_override).
        base = load_base_config()
        touched = ["bot.models", "bot.groq_models", "bot.local", "bot.tts.voice"] + \
            [f"bot.{spec['groq_key']}" for spec in providers.JOBS.values() if spec.get("groq_key")]
        for key in dict.fromkeys(touched):
            value = configstore.get_nested(cfg, key)
            if value is None:
                personas.clear_override(pid, key)
            else:
                personas.set_override(pid, key, value, base=base)
        invalidate_config_cache()

    await asyncio.to_thread(write)
    _pid, after = _scoped(pid)
    from app.web import live
    live.push(request, "config_update", {"key": "bot.models"}, persona=pid or None, platforms=("discord",))
    return {"ok": True, "plan": providers.plan(after)}


# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get("/api/models/usage")
def models_usage(days: int = 7):
    """What each model has done, counted by the app from every answer (see app/utils/usage.py), and what is left
    of its limits from the latest answer's headers. Plain def: it is sqlite."""
    from app.utils import usage
    return usage.summary(days)


_left: dict = {"at": 0.0, "providers": []}
_left_lock = asyncio.Lock()


@router.get("/api/models/left")
async def models_left(refresh: bool = False):
    """What is left with each provider, asked of it (app/utils/whatsleft.py): at most every five minutes unless asked
    again by hand, and only one asking at a time, however many pages want it."""
    from app.utils import whatsleft
    async with _left_lock:
        if refresh or time.time() - _left["at"] > whatsleft.ASK_EVERY:
            _left["providers"] = await asyncio.to_thread(whatsleft.ask_all, load_config())
            _left["at"] = time.time()
    return {"providers": _left["providers"], "at": _left["at"]}
