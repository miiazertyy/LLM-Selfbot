"""Where each AI job runs.

The app used to know two places a model could live: Groq, and a server on this
machine. Replies went to one or the other - a switch, on or off - and the three
smaller jobs (reading pictures, hearing voice messages, speaking) could only
move to the local server once replies had. There was no way to say "write with
my local model, and if it is down use Groq", or to use any other provider.

Now there is a list of providers, and a plan for each job:

  * Replies are a chain, tried top to bottom. When one is rate limited, down or
    out of credit, the next one writes the reply. The order is yours.
  * Background work (memory, language, summaries), pictures, voice messages and
    speaking each name one model. Leave one unset and it stays on Groq, exactly
    as before, and a named one that fails falls back to Groq too.

Every provider here except Groq is reached through its OpenAI-compatible
endpoint, so one client covers all of them: OpenAI itself, Anthropic, Google,
OpenRouter, Mistral, DeepSeek, xAI, Together, Cerebras, and any server on this
machine (Ollama, LM Studio, llama.cpp, vLLM). Groq keeps its own client because
of the key rotation it has always had.

A config written before this existed has no `bot.models` block; plan() reads
the old keys (groq_models, groq_*_model, bot.local.*) and gives the same
answer they always did, so nothing changes until someone edits the new tab.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

# The order is the order the Providers tab shows them in: Groq first because
# it is what the app was built on and is free, then the big names, then the
# aggregators and the fast-inference hosts. `jobs` is what each one can do
# through the OpenAI-compatible API, which is not always all it can do.
PROVIDERS = [
    {"id": "groq", "name": "Groq", "env": "GROQ_API_KEY", "multi": True,
     "base_url": "https://api.groq.com/openai/v1",
     "site": "https://console.groq.com/keys", "jobs": ["chat", "vision", "stt", "tts"],
     "blurb": "Fast and free to start. What the app was built on."},
    {"id": "openai", "name": "OpenAI", "env": "OPENAI_API_KEY",
     "base_url": "https://api.openai.com/v1",
     "site": "https://platform.openai.com/api-keys", "jobs": ["chat", "vision", "stt", "tts"],
     "blurb": "GPT models, Whisper and speech."},
    {"id": "anthropic", "name": "Anthropic", "env": "ANTHROPIC_API_KEY",
     "base_url": "https://api.anthropic.com/v1",
     "site": "https://console.anthropic.com/settings/keys", "jobs": ["chat", "vision"],
     "blurb": "Claude models."},
    {"id": "gemini", "name": "Google Gemini", "env": "GEMINI_API_KEY",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "site": "https://aistudio.google.com/apikey", "jobs": ["chat", "vision"],
     "blurb": "Gemini models, with a free tier."},
    {"id": "openrouter", "name": "OpenRouter", "env": "OPENROUTER_API_KEY",
     "base_url": "https://openrouter.ai/api/v1",
     "site": "https://openrouter.ai/keys", "jobs": ["chat", "vision"],
     "blurb": "Hundreds of models behind one key, some free."},
    {"id": "mistral", "name": "Mistral", "env": "MISTRAL_API_KEY",
     "base_url": "https://api.mistral.ai/v1",
     "site": "https://console.mistral.ai/api-keys", "jobs": ["chat", "vision"],
     "blurb": "Mistral and Pixtral models."},
    {"id": "deepseek", "name": "DeepSeek", "env": "DEEPSEEK_API_KEY",
     "base_url": "https://api.deepseek.com/v1",
     "site": "https://platform.deepseek.com/api_keys", "jobs": ["chat"],
     "blurb": "DeepSeek chat and reasoning models, cheap."},
    {"id": "xai", "name": "xAI", "env": "XAI_API_KEY",
     "base_url": "https://api.x.ai/v1",
     "site": "https://console.x.ai", "jobs": ["chat", "vision"],
     "blurb": "Grok models."},
    {"id": "together", "name": "Together AI", "env": "TOGETHER_API_KEY",
     "base_url": "https://api.together.xyz/v1",
     "site": "https://api.together.ai/settings/api-keys", "jobs": ["chat", "vision"],
     "blurb": "Open models, hosted."},
    {"id": "cerebras", "name": "Cerebras", "env": "CEREBRAS_API_KEY",
     "base_url": "https://api.cerebras.ai/v1",
     "site": "https://cloud.cerebras.ai", "jobs": ["chat"],
     "blurb": "Very fast open models."},
    {"id": "local", "name": "This computer", "env": "",
     "base_url": "",            # from bot.local.base_url
     "site": "https://ollama.com/download", "jobs": ["chat", "vision", "stt", "tts"],
     "blurb": "Ollama, LM Studio or any server on this machine. Nothing leaves it."},
]
BY_ID = {p["id"]: p for p in PROVIDERS}

# What each one costs, for the Free / Paid tags, so someone who does not know
# these services can tell which to try first. Free tiers are rate limited and
# their terms change, which the note says rather than promising anything.
COST = {
    "groq": ("free", "Free tier with rate limits. A paid plan raises them."),
    "local": ("free", "Runs on your own computer, so it costs nothing to use."),
    "gemini": ("free", "Free tier in Google AI Studio, with rate limits."),
    "cerebras": ("free", "Free tier with rate limits."),
    "mistral": ("free", "Free Experiment plan with rate limits."),
    "openrouter": ("some", "Some models are free (their names end in :free), the rest are pay per use."),
    "openai": ("paid", "Pay per use. The account needs credit."),
    "anthropic": ("paid", "Pay per use. The account needs credit."),
    "deepseek": ("paid", "Pay per use, and cheap. The account needs credit."),
    "xai": ("paid", "Pay per use. The account needs credit."),
    "together": ("paid", "Pay per use. The account needs credit."),
}

# The jobs besides replies, the capability each needs, and the old Groq key
# that holds its model when nothing else is chosen.
JOBS = {
    "small": {"needs": "chat", "groq_key": "groq_small_model", "local_key": ""},
    "vision": {"needs": "vision", "groq_key": "groq_image_model", "local_key": "vision_model"},
    "stt": {"needs": "stt", "groq_key": "groq_whisper_model", "local_key": "stt_model"},
    "tts": {"needs": "tts", "groq_key": "groq_tts_model", "local_key": "tts_model"},
}
DEFAULTS = {
    "small": "openai/gpt-oss-20b",
    "vision": "meta-llama/llama-4-scout-17b-16e-instruct",
    "stt": "whisper-large-v3-turbo",
    "tts": "canopylabs/orpheus-v1-english",
}


def _env_value(name: str) -> str:
    """A real value for NAME: from .env, which the panel edits, else the environment.

    The file first: the panel process loaded .env once at start, so a key added
    or removed in the Models tab would otherwise read the old way until a restart.
    """
    from app.utils.credentials import is_placeholder
    try:
        from app.web.envfile import read_env
        values = read_env()
        if name in values:
            value = values.get(name)
            return str(value).strip() if value and not is_placeholder(value) else ""
    except Exception:
        pass
    value = os.getenv(name)
    return value.strip() if value and not is_placeholder(value) else ""


def keys_for(pid: str) -> list:
    """Every key set for this provider. Groq alone takes several (_1, _2, ...)."""
    p = BY_ID.get(pid)
    if not p or not p["env"]:
        return []
    out = []
    first = _env_value(p["env"])
    if first:
        out.append(first)
    if p.get("multi"):
        for i in range(1, 21):
            k = _env_value(f"{p['env']}_{i}")
            if k and k not in out:
                out.append(k)
    return out


def local_settings(config: dict) -> dict:
    from app.utils import localai
    return localai.settings(config)


def base_url(pid: str, config: dict) -> str:
    if pid == "local":
        return local_settings(config)["base_url"]
    p = BY_ID.get(pid)
    return p["base_url"] if p else ""


def usable(pid: str, config: dict) -> bool:
    """Whether this provider can be asked at all: a key, or for local an address."""
    if pid == "local":
        return bool(local_settings(config)["base_url"])
    return bool(keys_for(pid))


def _entry(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("provider") or "").strip()
    model = str(raw.get("model") or "").strip()
    if pid not in BY_ID or not model:
        return None
    out = {"provider": pid, "model": model}
    if raw.get("voice"):
        out["voice"] = str(raw["voice"]).strip()
    return out


def _groq_models(bot: dict) -> list:
    raw = bot.get("groq_models") or []
    if isinstance(raw, str):
        raw = [m.strip() for m in raw.split(",")]
    return [m for m in raw if isinstance(m, str) and m.strip()]


def reply_chain(config: dict) -> list:
    """Who writes replies, in the order to try them."""
    bot = (config or {}).get("bot") or {}
    models = bot.get("models") or {}
    chain = [e for e in (_entry(r) for r in (models.get("replies") or [])) if e]
    if chain:
        return chain
    # Before the Models tab: the local server when it was switched on, and then
    # nothing else (that switch meant "never Groq"), otherwise Groq's list.
    local = local_settings(config)
    if local["enabled"] and local["model"]:
        return [{"provider": "local", "model": local["model"]}]
    return [{"provider": "groq", "model": m} for m in _groq_models(bot)]


def _chosen_chain(config: dict, name: str) -> list:
    """What was picked for a job under Models, in order: one entry, or a list of fallbacks."""
    bot = (config or {}).get("bot") or {}
    raw = (bot.get("models") or {}).get(name)
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for item in items:
        e = _entry(item)
        if not e:
            continue
        if name == "tts" and "voice" not in e:
            voice = ((bot.get("tts") or {}).get("voice") or "") if e["provider"] == "groq" \
                else local_settings(config).get("tts_voice", "")
            if voice:
                e["voice"] = voice
        if not any(x["provider"] == e["provider"] and x["model"] == e["model"] for x in out):
            out.append(e)
    return out


def job_chain(config: dict, name: str) -> list:
    """Who does one of the smaller jobs, in the order to try them. Groq's model for the job is
    not in it; it is what every job falls back to last (see ai._job_call)."""
    chosen = _chosen_chain(config, name)
    return chosen or [job(config, name)]


def job(config: dict, name: str) -> dict:
    """The first model for one of the smaller jobs: {provider, model[, voice]}."""
    spec = JOBS[name]
    bot = (config or {}).get("bot") or {}
    chosen = _chosen_chain(config, name)
    if chosen:
        return chosen[0]
    # The old way: a model named for this job on the local server wins, and
    # works whether or not replies are local - which is the point.
    if spec["local_key"]:
        local = local_settings(config)
        lm = local.get(spec["local_key"]) or ""
        if name == "vision" and not lm and local["vision"] and local["model"]:
            lm = local["model"]
        if lm:
            out = {"provider": "local", "model": lm}
            if name == "tts" and local.get("tts_voice"):
                out["voice"] = local["tts_voice"]
            return out
    if name == "small":
        # Replies on this computer used to mean background work there too.
        local = local_settings(config)
        if local["enabled"] and local["model"] and not (bot.get("models") or {}).get("replies"):
            return {"provider": "local", "model": local["model"]}
        small = bot.get("groq_small_model") or ""
        if not small:
            chain = _groq_models(bot)
            small = chain[-1] if chain else DEFAULTS["small"]
        return {"provider": "groq", "model": small}
    out = {"provider": "groq", "model": bot.get(spec["groq_key"]) or DEFAULTS[name]}
    if name == "tts":
        voice = (bot.get("tts") or {}).get("voice") or ""
        if voice:
            out["voice"] = voice
    return out


def groq_fallback(config: dict, name: str) -> dict:
    """What a job falls back to when its chosen provider fails: its Groq model."""
    bot = (config or {}).get("bot") or {}
    if name == "small":
        return {"provider": "groq", "model": bot.get("groq_small_model") or DEFAULTS["small"]}
    return {"provider": "groq", "model": bot.get(JOBS[name]["groq_key"]) or DEFAULTS[name]}


def plan(config: dict) -> dict:
    """Everything, for the Models tab and the health checks."""
    return {"replies": reply_chain(config), **{name: job(config, name) for name in JOBS},
            # Every model each job tries, in order; the entries above are each chain's first.
            "chains": {name: job_chain(config, name) for name in JOBS}}


# ── What each model can do ────────────────────────────────────────────────────

_NOT_CHAT = ("embed", "moderation", "guard", "dall-e", "gpt-image", "imagen", "rerank",
             "text-search", "similarity", "davinci-002", "babbage", "tts", "whisper",
             "transcribe", "speech", "realtime", "audio-preview", "search-preview", "veo")
_VISION = ("vision", "-vl", "vl-", "llava", "pixtral", "gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4",
           "claude", "gemini", "gemma-3", "llama-4", "scout", "maverick", "grok-4", "grok-2-vision",
           "qwen2.5-vl", "qwen3-vl", "qwen3.6", "qwen3.8", "minicpm-v", "moondream", "multimodal")
# Hearing first: SenseVoice hears, though "voice" is in its name. A voice model was offered for writing replies
# (OmniVoice, which Ollama itself calls a text model), so "voice" and the speech models' own names say speaking.
_STT = ("whisper", "transcribe", "voxtral", "stt", "sensevoice", "parakeet", "canary-", "moonshine", "wav2vec")
_TTS = ("tts", "speech", "orpheus", "kokoro", "playai", "voice", "parler", "chatterbox", "zonos", "piper")


def capabilities(pid: str, model_id: str) -> list:
    """What a model can be used for, as far as its name says.

    Groq has an exact table (groqmodels.CAPABILITIES). Nobody else publishes
    capabilities in the model list, so the rest is read off the name, generously
    towards chat: a text model wrongly hidden from the reply picker is worse than
    one wrongly offered.
    """
    if pid == "groq":
        from app.utils import groqmodels
        return sorted(groqmodels.capabilities(model_id))
    low = (model_id or "").lower()
    caps = set()
    if any(n in low for n in _STT):
        caps.add("stt")
    if any(n in low for n in _TTS) and "stt" not in caps:
        caps.add("tts")
    if not caps and not any(n in low for n in _NOT_CHAT):
        caps.add("chat")
        if any(n in low for n in _VISION):
            caps.add("vision")
    return sorted(caps)


# ── How a reply is sampled ────────────────────────────────────────────────────
# The knobs that change how a model writes. temperature and top_p are how varied
# it lets itself be; frequency_penalty and presence_penalty push it away from
# repeating itself, which is what stops a character answering four people with
# the same three sentences. Every one is optional: left unset, the provider's own
# default is used and nothing is sent.
SAMPLING = ("temperature", "top_p", "frequency_penalty", "presence_penalty")

# Which of them a provider will accept. Everything here speaks the OpenAI chat
# API, but not all of them take the whole of it, and one unknown field is a 400
# for the whole request rather than a warning. Anthropic and Gemini have no
# penalties at all; a local server takes whatever it was built with, so it gets
# the two that every implementation has.
_SAMPLING_SUPPORT = {
    "anthropic": ("temperature", "top_p"),
    "gemini": ("temperature", "top_p"),
    "local": ("temperature", "top_p"),
}


def sampling_support(pid: str) -> tuple:
    """The sampling settings this provider accepts."""
    return _SAMPLING_SUPPORT.get(pid, SAMPLING)


def sampling_args(pid: str, config: dict) -> dict:
    """The sampling settings to send to this provider, from bot.sampling. Anything unset, out of range or unsupported here is simply not sent, so the provider's own default stands."""
    raw = ((config.get("bot") or {}).get("sampling")) or {}
    allowed = sampling_support(pid)
    limits = {"temperature": (0.0, 2.0), "top_p": (0.0, 1.0),
              "frequency_penalty": (-2.0, 2.0), "presence_penalty": (-2.0, 2.0)}
    out = {}
    for name in SAMPLING:
        if name not in allowed:
            continue
        value = raw.get(name)
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        low, high = limits[name]
        out[name] = max(low, min(high, number))
    return out


# ── Model lists ───────────────────────────────────────────────────────────────

_cache: dict = {}
_TTL = 3600.0
_NEG_TTL = 60.0
# The server on this computer answers in a moment, and its list changes under the app's own hands (a model
# downloaded, one removed): kept an hour like the others, the picker went on offering a model removed long before
# and not the one downloaded since.
_LOCAL_TTL = 15.0


def forget(pid: str) -> None:
    """Its list asked for again next time: something changed it."""
    _cache.pop(pid, None)


def user_agent() -> str:
    """How the app names itself to a provider. Several sit behind Cloudflare, which turns Python's default "Python-urllib/3.x" away with a 403 ("error code: 1010") before the key is even looked at. Try then said "the key is not allowed to use this model" about a key every reply was using without trouble: replies go through the providers' own libraries, which name themselves."""
    try:
        from app.version import __version__ as version
    except Exception:
        version = "dev"
    return f"LLMSelfbot/{version}"


def http_error(pid: str, code: int, raw: str) -> tuple:
    """(what went wrong, the provider's own words) for an HTTP error, in terms a person can act on. Only an answer from the provider itself, which is JSON, can say anything about the key or the model. Anything else came from something in front of it, and blaming the key for that sends people off to make new keys that fail the same way."""
    name = BY_ID.get(pid, {}).get("name", pid)
    try:
        data = json.loads(raw)
    except Exception:
        data = None
    if not isinstance(data, dict):
        said = " ".join((raw or "").split())[:80]
        return (f"{name} turned the request away before checking the key"
                + (f" ({said})." if said else f" ({code})."), (raw or "")[:300])
    err = data.get("error")
    detail = (err.get("message") if isinstance(err, dict) else err) or data.get("message") or ""
    reason = {401: "The key was refused.",
              403: "This key is not allowed to use this model.",
              404: f"{name} does not have that model.",
              429: "Rate limited right now."}.get(code) or explain(str(detail)) or f"{name} answered {code}."
    return reason, str(detail)[:300]


_NEEDS = re.compile(r"requires more (system|gpu) memory \(([\d.]+)\s*([KMGT]i?B)\) than is available \(([\d.]+)\s*([KMGT]i?B)\)", re.I)
_NO_MEMORY = re.compile(r"out of memory|unable to allocate|cudaMalloc failed|insufficient memory|not enough memory|"
                        r"failed to allocate|memory allocation", re.I)


def explain(detail: str) -> str:
    """A server's error in words a person can act on, when it is one of the usual ones; "" otherwise. A model too big
    for the computer came back as "This computer answered 500." from Try, with the real reason only in a tooltip."""
    m = _NEEDS.search(detail or "")
    if m:
        where = "graphics memory" if m.group(1).lower() == "gpu" else "memory"
        return (f"Not enough {where}: it needs {m.group(2)} {m.group(3).replace('i', '')}, and this computer has "
                f"{m.group(4)} {m.group(5).replace('i', '')} free. A smaller model, or closing other apps, would fit.")
    if _NO_MEMORY.search(detail or ""):
        return "Not enough memory to load it on this computer. A smaller model, or closing other apps, would fit."
    # A file that is not the model (a draft, a vision part) or a format the server cannot read says so in its error;
    # a runner that simply died while loading, with nothing more, is almost always memory.
    specific = re.search(r"wrong shape|missing tensor|check_tensor_dims|unknown model architecture|version", detail or "", re.I)
    if not specific and re.search(r"runner process (has terminated|no longer running)", detail or "", re.I):
        return "It stopped while loading, which is usually not enough memory for it. A smaller model would fit."
    try:
        from app.utils import localfix
        if localfix.load_failure(detail):
            why = localfix.reason(detail)
            return f"It would not load: {why}." if why and "could not load it" not in why else \
                "It would not load on this computer."
    except Exception:
        pass
    return ""


def _get_json(url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": user_agent(), **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def list_models(pid: str, config: dict, force: bool = False, timeout: float = 8.0) -> dict:
    """{models: [{id, capabilities}], error} for one provider, cached for an hour."""
    now = time.time()
    hit = _cache.get(pid)
    ttl = _LOCAL_TTL if pid == "local" else (_TTL if hit and hit["models"] else _NEG_TTL)
    if hit and not force and now - hit["at"] < ttl:
        return {"models": hit["models"], "error": hit["error"]}

    models, error = [], ""
    if pid == "groq":
        from app.utils import groqmodels
        data = groqmodels.available(force=force)
        models = [{"id": m["id"], "capabilities": m.get("capabilities") or capabilities(pid, m["id"])}
                  for m in data["models"] if m.get("active", True)]
        error = data.get("error", "")
    elif pid == "local":
        from app.utils import localai
        result = localai.probe(base_url("local", config), timeout=min(timeout, 4.0))
        # Ollama's word for what a model is (its family, "omnivoice-lm") read with its name: a name alone can hide it.
        family = (localai.ollama_models(base_url("local", config)) or {}) if result["models"] else {}
        models = [{"id": m, "capabilities": capabilities(pid, f"{m} {(family.get(m) or {}).get('family') or ''}")}
                  for m in result["models"]]
        # A local model's name says little about it (a llava tag is obvious,
        # a custom one is not), so every job is offered and the person decides.
        for m in models:
            if not m["capabilities"]:
                m["capabilities"] = ["chat"]
        error = result["error"]
    else:
        keys = keys_for(pid)
        if not keys:
            error = "No key set."
        else:
            headers = {"Authorization": f"Bearer {keys[0]}"}
            if pid == "anthropic":
                headers.update({"x-api-key": keys[0], "anthropic-version": "2023-06-01"})
            try:
                data = _get_json(base_url(pid, config).rstrip("/") + "/models", headers, timeout)
                items = data.get("data") if isinstance(data, dict) else data
                for item in items or []:
                    mid = item.get("id") if isinstance(item, dict) else None
                    if not mid:
                        continue
                    # Gemini lists them as "models/gemini-2.5-flash".
                    if pid == "gemini" and mid.startswith("models/"):
                        mid = mid[len("models/"):]
                    models.append({"id": mid, "capabilities": capabilities(pid, mid)})
            except urllib.error.HTTPError as e:
                try:
                    raw = e.read().decode("utf-8", "replace")
                except Exception:
                    raw = ""
                error, _ = http_error(pid, e.code, raw)
                if e.code == 403 and error.startswith("This key"):
                    error = "The key was refused."
            except Exception as e:
                error = f"Could not reach {BY_ID[pid]['name']}: {type(e).__name__}"
    models.sort(key=lambda m: m["id"])
    _cache[pid] = {"at": now, "models": models, "error": error}
    return {"models": models, "error": error}


def label(entry: dict) -> str:
    """"Groq · openai/gpt-oss-120b", for logs."""
    p = BY_ID.get(entry.get("provider", ""), {})
    return f"{p.get('name', entry.get('provider', '?'))} · {entry.get('model', '')}"
