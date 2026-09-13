"""
app/utils/groqmodels.py - which models Groq actually has today.

Model names are typed into config.yaml by hand, and Groq retires them without
warning. When that happens every reply fails with a 404 that says
"model_decommissioned", which looks exactly like the bot being broken.

Groq publishes the live list, so there is no reason to guess:

    GET https://api.groq.com/openai/v1/models

The answer is cached on disk as well as in memory, so the panel still has
something to show when the network is down or every key is rate limited, and
so a dropdown does not cost a request every time it opens.
"""

import json
import os
import time

MODELS_URL = "https://api.groq.com/openai/v1/models"

# Long enough that opening Settings repeatedly costs nothing, short enough that
# a retirement shows up the same day.
TTL_SECONDS = 6 * 3600

# What each model is actually for.
#
# This was guessed from the name, which got it wrong in the way that mattered
# most: qwen3.6-27b and qwen3.8-27b are multimodal and accept images, but
# neither has "vision" or "vl" anywhere in the id, so the image model picker
# offered no vision models at all while the one in use was a vision model.
#
# Capabilities per Groq's own documentation. A model can do several things:
# the qwen 3.x models are chat models AND vision models, so they belong in both
# the reply list and the image describer.
#   https://console.groq.com/docs/models
#   https://console.groq.com/docs/vision
CAPABILITIES = {
    # Text and chat
    "llama-3.1-8b-instant": {"chat"},
    "llama-3.3-70b-versatile": {"chat"},
    "openai/gpt-oss-120b": {"chat"},
    "openai/gpt-oss-20b": {"chat"},
    "allam-2-7b": {"chat"},
    "minimaxai/minimax-m2.7": {"chat"},
    # Agentic: chat models that can also use tools on Groq's side
    "groq/compound": {"chat"},
    "groq/compound-mini": {"chat"},
    # Multimodal: chat models that can also read an image
    "qwen/qwen3.6-27b": {"chat", "vision"},
    "qwen/qwen3.8-27b": {"chat", "vision"},
    "meta-llama/llama-4-scout-17b-16e-instruct": {"chat", "vision"},
    "meta-llama/llama-4-maverick-17b-128e-instruct": {"chat", "vision"},
    # Speech in
    "whisper-large-v3": {"stt"},
    "whisper-large-v3-turbo": {"stt"},
    # Speech out
    "canopylabs/orpheus-v1-english": {"tts"},
    "canopylabs/orpheus-arabic-saudi": {"tts"},
    # Safety classifiers, not usable for conversation
    "meta-llama/llama-prompt-guard-2-22m": {"moderation"},
    "meta-llama/llama-prompt-guard-2-86m": {"moderation"},
    "openai/gpt-oss-safeguard-20b": {"moderation"},
}

# Groq adds models faster than any table can be maintained, so anything not
# listed above is placed by name. Deliberately generous towards "chat": a new
# text model wrongly hidden from the picker is worse than one wrongly offered,
# because the second is merely a bad suggestion and the first is unusable.
_NAME_RULES = (
    ({"whisper", "distil-whisper"}, {"stt"}),
    ({"orpheus", "tts", "playai", "speech"}, {"tts"}),
    ({"guard", "safeguard", "moderation", "shieldgemma"}, {"moderation"}),
    ({"vl", "vision", "llava", "scout", "maverick", "multimodal"}, {"chat", "vision"}),
)


def capabilities(model_id: str) -> set:
    """Everything this model can be used for."""
    known = CAPABILITIES.get(model_id)
    if known:
        return set(known)
    low = (model_id or "").lower()
    for needles, caps in _NAME_RULES:
        if any(n in low for n in needles):
            return set(caps)
    return {"chat"}


def can(model_id: str, capability: str) -> bool:
    return capability in capabilities(model_id)


def classify(model_id: str) -> str:
    """One word for the model, for grouping a list. Its main use."""
    caps = capabilities(model_id)
    for kind in ("stt", "tts", "moderation", "vision", "chat"):
        if kind in caps:
            return "audio" if kind in ("stt", "tts") else kind
    return "chat"


_cache = {"at": 0.0, "models": [], "error": ""}


def _cache_path():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config" / "groq_models.json"


def _key() -> str:
    """Any usable Groq key. The list endpoint does not care which."""
    from app.utils.credentials import real_any
    found = real_any("GROQ_API_KEY")
    if found:
        return found
    # The panel can run without the .env having reached the environment.
    try:
        from app.web.envfile import read_env
        from app.utils.credentials import is_placeholder
        values = read_env()
        for name in ["GROQ_API_KEY"] + [f"GROQ_API_KEY_{i}" for i in range(1, 21)]:
            value = values.get(name)
            if value and not is_placeholder(value):
                return str(value).strip()
    except Exception:
        pass
    return ""


def _read_disk() -> list:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            return data["models"]
    except Exception:
        pass
    return []


def _write_disk(models: list) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"at": time.time(), "models": models}, indent=2),
                        encoding="utf-8")
    except OSError:
        pass       # a read-only data dir must not break the fetch


def fetch(timeout: float = 8.0) -> tuple[list, str]:
    """Ask Groq for the live list. Returns (models, error)."""
    key = _key()
    if not key:
        return [], "No Groq API key, so the model list cannot be checked."
    try:
        import requests
        resp = requests.get(
            MODELS_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        if resp.status_code == 401:
            return [], "Groq rejected the API key."
        if resp.status_code != 200:
            return [], f"Groq answered {resp.status_code} when asked for its models."
        payload = resp.json()
    except Exception as exc:
        return [], f"Could not reach Groq: {type(exc).__name__}"

    models = []
    for item in payload.get("data", []) or []:
        model_id = item.get("id")
        if not model_id:
            continue
        models.append({
            "id": model_id,
            "kind": classify(model_id),
            "capabilities": sorted(capabilities(model_id)),
            "owned_by": item.get("owned_by", ""),
            "context_window": item.get("context_window"),
            "max_completion_tokens": item.get("max_completion_tokens"),
            # Groq marks a retired model inactive before removing it entirely.
            "active": bool(item.get("active", True)),
        })
    models.sort(key=lambda m: (m["kind"], m["id"]))
    return models, ""


def available(force: bool = False) -> dict:
    """The model list, from memory, disk or Groq, in that order of cheapness."""
    now = time.time()
    if not force and _cache["models"] and now - _cache["at"] < TTL_SECONDS:
        return {"models": _cache["models"], "fetched": _cache["at"],
                "error": _cache["error"], "source": "memory"}

    models, error = fetch()
    if models:
        _cache.update(at=now, models=models, error="")
        _write_disk(models)
        return {"models": models, "fetched": now, "error": "", "source": "groq"}

    # Offline or rate limited: yesterday's list still beats an empty dropdown.
    disk = _read_disk()
    if disk:
        _cache.update(at=now, models=disk, error=error)
        return {"models": disk, "fetched": now, "error": error, "source": "cache"}
    _cache.update(at=now, models=[], error=error)
    return {"models": [], "fetched": now, "error": error, "source": "none"}


def check_configured(config: dict) -> list:
    """Which configured models Groq no longer offers.

    Returns one entry per problem, empty when everything is fine or when the
    list could not be fetched. Silence on failure is deliberate: not being able
    to check is not evidence that anything is wrong.
    """
    data = available()
    if not data["models"]:
        return []
    known = {m["id"] for m in data["models"]}
    retired = {m["id"] for m in data["models"] if not m["active"]}

    # Which capability each setting needs. Using a speech model to write
    # replies, or a text model to read an image, fails on every request with an
    # error that does not obviously say the model was the wrong choice.
    NEEDS = {
        "groq_models": "chat",
        "groq_small_model": "chat",
        "groq_image_model": "vision",
        "groq_whisper_model": "stt",
        "groq_tts_model": "tts",
    }

    bot = (config.get("bot", {}) or {})
    wanted = []
    for value in (bot.get("groq_models") or []):
        if isinstance(value, str):
            wanted.append(("groq_models", value))
    for key in ("groq_small_model", "groq_image_model",
                "groq_whisper_model", "groq_tts_model"):
        value = bot.get(key)
        if isinstance(value, str) and value:
            wanted.append((key, value))

    problems = []
    for key, model_id in wanted:
        if model_id in retired:
            problems.append({"key": key, "model": model_id, "reason": "retired"})
        elif model_id not in known:
            problems.append({"key": key, "model": model_id, "reason": "unknown"})
        elif not can(model_id, NEEDS.get(key, "chat")):
            problems.append({"key": key, "model": model_id, "reason": "wrong_kind",
                             "needs": NEEDS.get(key, "chat")})
    return problems
