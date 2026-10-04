import re
import sys
import json
import time

from groq import AsyncGroq, RateLimitError
from os import getenv
from dotenv import load_dotenv
from app.utils.helpers import get_env_path, load_config
from app.utils.error_notifications import webhook_log, print_error
from app.utils.logger import log_model_fallback, log_system, log_thinking

# Active Groq clients, one per API key
_groq_clients = []   # list of {"client": AsyncGroq, "label": str}
_client_index = 0    # which key is currently active

# the local server, when any job uses it: same API shape as Groq, so the calls below work unchanged
_local_client = None
_local_model = ""
_local_vision = False
# per-capability local models, kept for the code and the logs that still ask about them; where each job actually runs is providers.plan()
_local_vision_model = ""
_local_stt_model = ""
_local_tts_model = ""
_local_tts_voice = ""
_local_base_url = ""
_local_api_key = ""

model = None
groq_models = []
current_model_index = 0

# Set by init_ai. The old "not _groq_clients and _local_client is None" test for "not set up yet" stayed true forever for someone who only uses OpenAI or Gemini, and re-ran init_ai on every call.
_initialised = False
# OpenAI-compatible clients for every provider other than Groq, built on first use: (provider, base_url, key) -> client
_provider_clients: dict = {}
# (provider, model) -> unix time. A reply chain entry that was just rate limited or down is tried last until then, rather than first on every single reply.
_resting: dict = {}
# who wrote the last reply, "Groq · openai/gpt-oss-120b", for the logs
last_reply_model = ""

# a local server raises openai's RateLimitError, Groq raises its own, different classes: catching only one meant a loaded local server fell into the generic handler and looked like a crash. openai isn't imported here (heavy, ~620ms on every worker launch); the first OpenAI-compatible client adds the class. every `except RATE_LIMITED` re-reads this global, so extending it later covers old handlers.
RATE_LIMITED = (RateLimitError,)


def _active_client():
    """Return the currently active Groq client."""
    return _groq_clients[_client_index]["client"]


def _plan_job(name: str) -> dict:
    from app.utils import providers
    return providers.job(load_config(), name)


def local_active() -> bool:
    """True when replies are written on this machine first."""
    from app.utils import providers
    chain = providers.reply_chain(load_config())
    return bool(chain) and chain[0]["provider"] == "local"


def groq_key_count() -> int:
    """How many Groq keys are loaded: rate limits are per key, so two keys really are two separate allowances."""
    if not _initialised:
        init_ai()
    return len(_groq_clients)


def groq_key_label(index: int) -> str:
    """The display label for one key, for logs."""
    if not _groq_clients:
        return ""
    return _groq_clients[index % len(_groq_clients)]["label"]


def vision_is_local() -> bool:
    """Whether pictures are read somewhere other than Groq, so Groq's keys do not limit them."""
    return _plan_job("vision")["provider"] != "groq"


def stt_is_local() -> bool:
    """Whether voice messages are transcribed somewhere other than Groq."""
    return _plan_job("stt")["provider"] != "groq"


def local_tts() -> dict:
    """What tts.py needs to speak through a provider other than Groq, or {} to use Groq. The name is from when the only other place was this computer; OpenAI's /audio/speech is the same call."""
    if not _initialised:
        init_ai()
    from app.utils import providers
    config = load_config()
    chosen = providers.job(config, "tts")
    if chosen["provider"] == "groq":
        return {}
    url = providers.base_url(chosen["provider"], config)
    if chosen["provider"] == "local":
        key = providers.local_settings(config)["api_key"]
    else:
        keys = providers.keys_for(chosen["provider"])
        key = keys[0] if keys else ""
    if not url or not key:
        return {}
    return {"base_url": url, "api_key": key, "model": chosen["model"],
            "voice": chosen.get("voice", ""), "provider": chosen["provider"]}


def tts_targets() -> list:
    """Every non-Groq speaker in the speaking chain, in order, with what tts.py needs for each.
    Groq comes after all of them, in tts.py."""
    if not _initialised:
        init_ai()
    from app.utils import providers
    config = load_config()
    out = []
    for e in providers.job_chain(config, "tts"):
        if e["provider"] == "groq":
            continue
        url = providers.base_url(e["provider"], config)
        if e["provider"] == "local":
            key = providers.local_settings(config)["api_key"]
        else:
            keys = providers.keys_for(e["provider"])
            key = keys[0] if keys else ""
        if url and key:
            out.append({"base_url": url, "api_key": key, "model": e["model"],
                        "voice": e.get("voice", ""), "provider": e["provider"]})
    return out


def _openai_client(pid: str, config: dict):
    """The OpenAI-compatible client for a provider other than Groq, or None when it has no key."""
    global RATE_LIMITED, _local_client
    from app.utils import providers
    url = providers.base_url(pid, config)
    if pid == "local":
        key = providers.local_settings(config)["api_key"]
    else:
        keys = providers.keys_for(pid)
        key = keys[0] if keys else ""
    if not url or not key:
        return None
    cache_key = (pid, url, key)
    client = _provider_clients.get(cache_key)
    if client is None:
        from openai import AsyncOpenAI
        from openai import RateLimitError as _OpenAIRateLimit
        if _OpenAIRateLimit not in RATE_LIMITED:
            RATE_LIMITED = (*RATE_LIMITED, _OpenAIRateLimit)
        # explicit timeouts: the SDK default is ten minutes. a local server may be loading a model into memory, so it gets longer; four minutes is already useless, this is a backstop not a target
        from app.utils import usage
        client = AsyncOpenAI(base_url=url, api_key=key,
                             timeout=240.0 if pid == "local" else 90.0,
                             max_retries=1 if pid == "local" else 0,
                             http_client=usage.http_client(pid))
        _provider_clients[cache_key] = client
        if pid == "local":
            _local_client = client
    return client


def init_ai():
    global _groq_clients, _client_index, model, groq_models, current_model_index
    global _local_client, _local_model, _local_vision
    global _local_vision_model, _local_stt_model, _local_tts_model
    global _local_tts_voice, _local_base_url, _local_api_key
    global _initialised
    env_path = get_env_path()
    config = load_config()
    load_dotenv(dotenv_path=env_path, override=True)

    from app.utils import localai, providers
    plan = providers.plan(config)
    chain = plan["replies"]

    # ── This computer, when any job runs there ───────────────────────────────
    _local_client, _local_model, _local_vision = None, "", False
    _local_vision_model = _local_stt_model = _local_tts_model = ""
    _local_tts_voice = _local_base_url = _local_api_key = ""
    uses_local = any(e["provider"] == "local" for e in chain) or \
        any(plan[j]["provider"] == "local" for j in providers.JOBS)
    if uses_local:
        cfg = localai.settings(config)
        _local_client = _openai_client("local", config)
        _local_base_url, _local_api_key = cfg["base_url"], cfg["api_key"]
        _local_model = next((e["model"] for e in chain if e["provider"] == "local"), "")
        _local_vision_model = plan["vision"]["model"] if plan["vision"]["provider"] == "local" else ""
        _local_stt_model = plan["stt"]["model"] if plan["stt"]["provider"] == "local" else ""
        _local_tts_model = plan["tts"]["model"] if plan["tts"]["provider"] == "local" else ""
        _local_tts_voice = plan["tts"].get("voice", "") if _local_tts_model else ""
        _local_vision = bool(_local_vision_model)

    # load GROQ_API_KEY_1, _2, ... and fall back to the legacy GROQ_API_KEY
    keys = []
    i = 1
    while True:
        k = getenv(f"GROQ_API_KEY_{i}")
        if not k:
            break
        keys.append((f"GROQ_API_KEY_{i}", k))
        i += 1
    if not keys:
        legacy = getenv("GROQ_API_KEY")
        if legacy:
            keys.append(("GROQ_API_KEY", legacy))

    # a missing Groq key is only fatal when nothing else can write replies
    others = [e for e in chain if e["provider"] != "groq" and providers.usable(e["provider"], config)]
    if not keys and not others:
        print("No model can write replies: no GROQ_API_KEY in .env, and no other provider set up "
              "under Settings > Models. Exiting.")
        sys.exit(1)

    from app.utils import usage
    _groq_clients = [
        {"client": AsyncGroq(api_key=key, http_client=usage.http_client("groq", label, sdk="groq")), "label": label}
        for label, key in keys
    ]
    _client_index = 0

    raw = config["bot"].get("groq_models") or []
    if isinstance(raw, str):
        groq_models = [m.strip() for m in raw.split(",") if m.strip()]
    else:
        groq_models = list(raw)
    current_model_index = 0
    model = chain[0]["model"] if chain else (groq_models[0] if groq_models else "")
    _initialised = True

    if len(chain) > 1 or (chain and chain[0]["provider"] != "groq"):
        log_system("Replies: " + " → ".join(providers.label(e) for e in chain))
    moved = [f"{n} on {providers.label(plan[j])}" for j, n in
             (("small", "background work"), ("vision", "pictures"),
              ("stt", "voice messages"), ("tts", "speaking")) if plan[j]["provider"] != "groq"]
    if moved:
        log_system("Also: " + ", ".join(moved))
    if keys:
        log_system(f"Loaded {len(keys)} Groq API key(s), {len(groq_models)} Groq model(s).")
    else:
        missing = [n for j, n in (("vision", "pictures"), ("stt", "voice messages"), ("tts", "speaking"))
                   if plan[j]["provider"] == "groq"]
        if missing:
            log_system(f"No Groq key set, so {', '.join(missing)} are off. "
                       "Pick another provider for them under Settings > Models.")


def _fallback_client():
    """Rotate to the next API key. Returns True if a new key is available."""
    global _client_index
    if len(_groq_clients) <= 1:
        return False
    next_index = _client_index + 1
    if next_index >= len(_groq_clients):
        return False  # All keys exhausted, let model fallback handle it
    old_label = _groq_clients[_client_index]["label"]
    _client_index = next_index
    new_label = _groq_clients[_client_index]["label"]
    log_system(f"Rate limited on {old_label} → switching to {new_label}")
    return True


def reset_client_index():
    """Reset key rotation back to the first key, called after a timed wait."""
    global _client_index
    _client_index = 0
    _resting.clear()


class RequestTooLarge(Exception):
    """One request needs more tokens than the plan allows per minute: not a rate limit, waiting/rotating doesn't help, the cap is on the organisation. Raised, not retried."""


_TOO_LARGE_MARKERS = ("request too large", "reduce your message size",
                      "please reduce the length",
                      # A model's context window, which is what a local server
                      # runs out of: llama.cpp and Ollama, OpenAI, Anthropic.
                      "exceeds the available context size", "exceed_context_size",
                      "context_length_exceeded", "maximum context length",
                      "prompt is too long", "context window")


def context_numbers(error) -> tuple:
    """(needed, available) tokens from a context-size error, or (0, 0)."""
    m = re.search(r"request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)", str(error))
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"maximum context length is (\d+) tokens.*?(\d+) tokens", str(error), re.S)
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def explain_too_large(error) -> str:
    """What to tell a person about a request the model had no room for."""
    need, have = context_numbers(error)
    if need and have:
        return (f"The model only has room for {have} tokens and this reply needs {need}: your persona, "
                "memory and the conversation. On this computer, Models > This computer sets how much room "
                "Ollama gives it (the app starts it with 16,384); a shorter persona helps too.")
    return "The request was too big for the model. Older messages are trimmed and it is tried again."

# same 429, two opposite fixes: input = conversation too big (send fewer messages), output = the expected reply is too big (Groq checks max_tokens, or the model default, before generating). trimming history for an output limit does nothing, hence "retrying with the last 7/4/2 messages" and the same refusal.
_OUTPUT_LIMIT_MARKERS = ("output tokens per minute", "otpm", "reduce max_tokens",
                         "expected output")

# cap the reply so Groq is asked for something that fits: without it, expected output includes a reasoning model's thinking, and a 1000/min tier refuses a short reply for wanting 1324. replies get cut to a few hundred chars anyway, so the cap loses nothing
DEFAULT_MAX_REPLY_TOKENS = 320
MIN_MAX_REPLY_TOKENS = 96


def is_request_too_large(error) -> bool:
    text = str(error).lower()
    return any(m in text for m in _TOO_LARGE_MARKERS) or is_output_limit(error)


def is_output_limit(error) -> bool:
    """True when the cap is on the reply, not on what was sent."""
    text = str(error).lower()
    return any(m in text for m in _OUTPUT_LIMIT_MARKERS)


def _reply_token_cap() -> int:
    try:
        cfg = load_config().get("bot", {}) or {}
        return max(MIN_MAX_REPLY_TOKENS,
                   int(cfg.get("max_reply_tokens", DEFAULT_MAX_REPLY_TOKENS)))
    except Exception:
        return DEFAULT_MAX_REPLY_TOKENS


def fallback_model():
    """Rotate to next model and reset key index."""
    global model, current_model_index, _client_index
    if not groq_models:
        return False
    old_model = model
    current_model_index += 1
    if current_model_index >= len(groq_models):
        # all models tried: go back to the first so the next request starts from the top, otherwise the rotation logs "x -> x" and retries the same model forever
        current_model_index = 0
        model = groq_models[0]
        _client_index = 0
        return False
    model = groq_models[current_model_index]
    _client_index = 0  # Reset to first key when switching models
    log_model_fallback(old_model, model)
    return True


def _is_rate_limit(e) -> bool:
    text = str(e).lower()
    return isinstance(e, RATE_LIMITED) or "429" in text or "rate limit" in text or "rate_limit" in text


def _retry_after(e) -> float:
    """How long a rate limited entry rests, from the error when it says ("try again in 1m2.5s")."""
    m = re.search(r"try again in (?:(\d+)m\s*)?(?:(\d+(?:\.\d+)?)s)?", str(e))
    if m and (m.group(1) or m.group(2)):
        secs = int(m.group(1) or 0) * 60 + float(m.group(2) or 0)
        return max(5.0, min(600.0, secs + 1))
    return 20.0


# Providers that turned out not to take the sampling settings; asked once, then
# left alone for the rest of the run rather than failing a reply every time.
_no_sampling: set = set()
# What "I do not know that field" looks like coming back from one.
_SAMPLING_WORDS = ("frequency_penalty", "presence_penalty", "top_p", "temperature",
                   "unknown parameter", "unsupported parameter", "unrecognized",
                   "extra fields not permitted", "unexpected keyword")


def _rejects_sampling(exc) -> bool:
    """Whether this failure is the provider refusing a sampling setting, rather than something that would fail again without them."""
    text = str(exc).lower()
    if not any(w in text for w in _SAMPLING_WORDS):
        return False
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    # A 400/422 names a bad field; a 429 or a 500 mentioning one is about something else.
    return status in (400, 422, None) or isinstance(exc, TypeError)


async def _groq_chat(model_id, messages, max_tokens, sampling=None):
    """One Groq model, every key in turn before giving up on it."""
    global _client_index
    last = None
    sampling = sampling or {}
    for attempt in range(max(1, len(_groq_clients))):
        try:
            return await _active_client().chat.completions.create(
                model=model_id, messages=messages, max_tokens=max_tokens, **sampling)
        except Exception as e:
            # a too-big request can't be rotated around: same organisation, same cap, on every key and model
            if is_request_too_large(e):
                from app.utils import apihealth
                apihealth.record("rate_limit", str(e), model=model_id)
                raise RequestTooLarge(str(e)) from e
            last = e
            if not _is_rate_limit(e):
                print(f"[AI] {type(e).__name__} on {model_id}: {e}")
            if len(_groq_clients) > 1 and attempt < len(_groq_clients) - 1:
                old = _groq_clients[_client_index]["label"]
                _client_index = (_client_index + 1) % len(_groq_clients)
                log_system(f"{'Rate limited' if _is_rate_limit(e) else 'Failed'} on {old} → "
                           f"switching to {_groq_clients[_client_index]['label']}")
    raise last


# How many replies are being written right now. Used to spread concurrent
# replies across the chain instead of starting all of them on the same model.
_inflight_replies = 0


class ModelWontLoad(RuntimeError):
    """A local model the server cannot load ("error loading model ..."): asking again a minute later fails the same
    way, a few seconds each, so it is left alone for a while (app/utils/localfix.py), and said once, in words."""


# (provider, model): (until when it is left alone, why).
_wont_load: dict = {}
# What was last said, and when: the same failure is not logged on every message.
_said: dict = {}


def _first_time(text: str, within: float) -> bool:
    now = time.time()
    if now - _said.get(text, 0.0) < within:
        return False
    _said[text] = now
    return True


def _left_alone(entry: dict):
    """The ModelWontLoad for an entry that would not load a moment ago, or None."""
    until, why = _wont_load.get((entry["provider"], entry["model"]), (0.0, ""))
    if until <= time.time():
        return None
    from app.utils import providers
    return ModelWontLoad(f"{providers.label(entry)} will not load: {why}")


def unavailable_now(config: dict | None = None) -> str:
    """Why no model can write a reply right now, or "" when one can: every model in the reply chain is being left
    alone because it will not load (see _wont_load_now). Asking anyway fails the same way, a few seconds each, and
    each failure was logged again for every message waiting: the log filled with the same error."""
    from app.utils import providers
    try:
        chain = providers.reply_chain(config or load_config())
    except Exception:
        return ""
    first = ""
    for entry in chain:
        skipped = _left_alone(entry)
        if skipped is None:
            return ""
        first = first or str(skipped)
    return first


def say_once(text: str, within: float = 600.0) -> bool:
    """True the first time this is to be said in `within` seconds: for a line that would otherwise repeat."""
    return _first_time(text, within)


def _wont_load_now(entry: dict, config: dict, error) -> "ModelWontLoad | None":
    """A local model that failed to load: left alone, handed to the panel to look into, and said once. None for any
    other error."""
    from app.utils import localfix, providers
    if entry["provider"] != "local" or not localfix.load_failure(error):
        return None
    why = localfix.reason(error)
    _wont_load[(entry["provider"], entry["model"])] = (time.time() + localfix.REST, why)
    localfix.note_failure(entry["model"], providers.base_url("local", config), error)
    if _first_time(f"wont-load {entry['model']}", localfix.REST):
        log_system(f"{providers.label(entry)} will not load: {why}. Left alone for ten minutes while the panel "
                   f"looks into it.")
    return ModelWontLoad(f"{providers.label(entry)} will not load: {why}")


async def _create_completion(messages, max_tokens=None):
    """A reply: see _create_completion_inner. Counted as the replies job (app/utils/usage.py)."""
    global _inflight_replies
    from app.utils import usage
    token = usage.JOB.set("replies")
    _inflight_replies += 1
    try:
        return await _create_completion_inner(messages, max_tokens)
    finally:
        _inflight_replies -= 1
        usage.JOB.reset(token)


async def _create_completion_inner(messages, max_tokens=None):
    """A reply, from the first model in the chain that answers. Each entry is tried in order; one that is rate limited, down or refusing its key hands over to the next, and rests for a while so the next reply does not start with it again. max_tokens is always sent since Groq checks the expected output against the per-minute allowance before generating.

    Several conversations are answered at once (discord.py runs each on_message as
    its own task), and they used to all start at the same entry: three replies
    being written together meant three calls to one model, which rate limited it,
    rested it, and pushed every one of them down the chain in lockstep. Replies
    already in flight step the starting point along instead, so concurrent
    replies spread across the models that are set up rather than queueing behind
    one. Order is otherwise unchanged, so a single reply still uses the first."""
    global model, last_reply_model
    if not _initialised:
        init_ai()
    from app.utils import providers, apihealth
    config = load_config()
    chain = providers.reply_chain(config)
    cap = max_tokens or _reply_token_cap()
    now = time.time()
    # Resting entries go last, not away: if everything is resting the first is still worth a try.
    order = sorted(range(len(chain)),
                   key=lambda i: (_resting.get((chain[i]["provider"], chain[i]["model"]), 0) > now, i))
    # This reply is counted in _inflight_replies already, so the first one shifts
    # by nothing and takes the chain as it is; each further one running at the
    # same time starts a step along and wraps around.
    others = max(0, _inflight_replies - 1)
    if others and len(order) > 1:
        shift = others % len(order)
        order = order[shift:] + order[:shift]

    last_error, too_large, prev, prev_error = None, None, None, None
    for i in order:
        entry = chain[i]
        pid, mid = entry["provider"], entry["model"]
        # Would not load a moment ago: asking again only spends seconds on the same failure.
        skipped = _left_alone(entry)
        if skipped is not None:
            last_error = last_error or skipped
            continue
        if pid == "groq":
            if not _groq_clients:
                continue
            client = None
        else:
            client = _openai_client(pid, config)
            if client is None:
                continue
        if prev is not None:
            log_model_fallback(providers.label(prev), providers.label(entry), _why_passed_over(prev_error))
        prev = entry
        prev_error = None
        sampling = {} if pid in _no_sampling else providers.sampling_args(pid, config)
        try:
            try:
                if pid == "groq":
                    response = await _groq_chat(mid, messages, cap, sampling)
                else:
                    response = await client.chat.completions.create(
                        model=mid, messages=messages, max_tokens=cap, **sampling)
            except Exception as e:
                # A provider that does not take one of these answers 400 for the
                # whole request. Rather than lose the reply over a setting, send
                # it again plainly and stop offering them to this one this run.
                if not sampling or not _rejects_sampling(e):
                    raise
                log_system(f"{providers.label(entry)} does not take those sampling settings; sending without them")
                _no_sampling.add(pid)
                if pid == "groq":
                    response = await _groq_chat(mid, messages, cap, {})
                else:
                    response = await client.chat.completions.create(
                        model=mid, messages=messages, max_tokens=cap)
            model = mid
            last_reply_model = providers.label(entry)
            _resting.pop((pid, mid), None)
            return response
        except RequestTooLarge as e:
            too_large = prev_error = e
        except Exception as e:
            prev_error = e
            if is_request_too_large(e):
                too_large = RequestTooLarge(str(e))
                continue
            wont = _wont_load_now(entry, config, e)
            if wont is not None:
                last_error = prev_error = wont
                apihealth.record("error", str(wont), model=mid)
                continue
            last_error = e
            limited = _is_rate_limit(e)
            _resting[(pid, mid)] = time.time() + (_retry_after(e) if limited else 60.0)
            if pid != "groq":
                apihealth.record("rate_limit" if limited else "error",
                                 f"{providers.label(entry)}: {e}", model=mid)
    # too large wins: generate_response answers it by sending less, which helps at least that entry
    if too_large is not None:
        raise too_large
    if last_error is not None:
        raise last_error
    raise RuntimeError("No model is set up to write replies. Add one under Settings > Models.")


def _why_passed_over(e) -> str:
    """Why a model was passed over for the next, in a few words, for the log line that says so."""
    if e is None:
        return ""
    if isinstance(e, ModelWontLoad):
        return "it will not load"
    if isinstance(e, RequestTooLarge) or is_request_too_large(e):
        return "the conversation was too long for it"
    if _is_rate_limit(e):
        return "rate limited"
    name = type(e).__name__.lower()
    text = str(e).lower()
    if "timeout" in name or "timed out" in text:
        return "it took too long to answer"
    if "connect" in name or "refused" in text or "connection" in text:
        return "it could not be reached"
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if status:
        return f"it answered {status}"
    return type(e).__name__


async def _job_call(name: str, call, groq_call):
    """One of the smaller jobs: see _job_call_inner. Counted under its own name (app/utils/usage.py)."""
    from app.utils import usage
    job_token, model_token = usage.JOB.set(name), usage.MODEL.set("")
    try:
        return await _job_call_inner(name, call, groq_call)
    finally:
        usage.JOB.reset(job_token)
        usage.MODEL.reset(model_token)


async def _job_call_inner(name: str, call, groq_call):
    """Run one of the smaller jobs where it is set to run, falling back to Groq. `call(client, model)` does the work on an OpenAI-compatible provider, `groq_call(model)` on Groq. Leaving a job unset keeps it on Groq exactly as before; a named one that fails hands over to Groq too, when there is a Groq key, so a flaky local server costs a slower answer rather than none."""
    from app.utils import providers, apihealth
    config = load_config()
    chain = providers.job_chain(config, name)
    last_error = None
    tried_groq = set()
    from app.utils import usage
    for i, entry in enumerate(chain):
        # Would not load a moment ago (see _wont_load_now): straight on to the next.
        skipped = _left_alone(entry)
        if skipped is not None:
            last_error = skipped
            continue
        if i and last_error is not None:
            log_system(f"{providers.label(chain[i - 1])} failed ({type(last_error).__name__}), "
                       f"trying {providers.label(entry)}")
        # a voice note goes up as a file, so its request does not say which model; this does
        usage.MODEL.set(entry["model"])
        try:
            if entry["provider"] == "groq":
                if not _groq_clients:
                    continue
                tried_groq.add(entry["model"])
                return await groq_call(entry["model"])
            client = _openai_client(entry["provider"], config)
            if client is None:
                continue
            return await call(client, entry["model"])
        except Exception as e:
            last_error = _wont_load_now(entry, config, e) or e
            if entry["provider"] != "groq":
                apihealth.record("rate_limit" if _is_rate_limit(e) else "error",
                                 f"{providers.label(entry)}: {e}", model=entry["model"])
    # Everything picked failed or could not be asked: Groq's own model for the job, last.
    fallback = providers.groq_fallback(config, name)["model"]
    if _groq_clients and fallback not in tried_groq:
        if last_error is not None:
            log_system(f"{providers.label(chain[-1])} failed ({type(last_error).__name__}), using Groq instead")
        usage.MODEL.set(fallback)
        return await groq_call(fallback)
    if last_error is not None:
        raise last_error
    names = ", ".join(sorted({providers.BY_ID[e["provider"]]["name"] for e in chain}))
    raise RuntimeError(f"{names} cannot be asked (no key), and there is no Groq key to fall back to.")


async def _create_image_completion(image_model, messages, client_index=None, **extra):
    """Image call, where pictures are set to be read; on Groq with key fallback (model fixed). `extra` holds optional params and a rejection of the params alone is retried without them. `client_index` pins a worker to its own key: no rotation, the caller does the backoff; None behaves like always."""
    if not _initialised:
        init_ai()

    async def elsewhere(client, mid):
        try:
            return await client.chat.completions.create(model=mid, messages=messages, **extra)
        except Exception as e:
            if extra and any(w in str(e).lower() for w in ("unrecognized", "unknown", "unsupported", "does not support")):
                return await client.chat.completions.create(model=mid, messages=messages)
            raise

    return await _job_call("vision", elsewhere,
                           lambda mid: _groq_image_completion(mid or image_model, messages, client_index, **extra))


async def _groq_image_completion(image_model, messages, client_index=None, **extra):
    params = dict(extra)
    if not _groq_clients:
        raise RuntimeError(
            "Reading images needs a Groq key, or another provider picked for pictures "
            "under Settings > Models.")

    pinned = client_index is not None
    if pinned:
        client = _groq_clients[client_index % len(_groq_clients)]["client"]

    while True:
        try:
            response = await (client if pinned else _active_client()).chat.completions.create(
                model=image_model,
                messages=messages,
                **params,
            )
            return response
        except RateLimitError as e:
            from app.utils import apihealth
            apihealth.record("rate_limit", str(e), model=image_model)
            if not pinned and _fallback_client():
                continue
            raise
        except Exception as e:
            text = str(e)
            # an unknown parameter is a 400 about the argument, not the image: drop the optional ones once and retry
            if params and ("unrecognized" in text.lower() or "unknown" in text.lower()
                           or "unsupported" in text.lower() or "does not support" in text.lower()):
                print(f"[AI] {image_model} rejected {list(params)}, retrying without")
                params = {}
                continue
            if "rate" not in text.lower() and "429" not in text:
                print(f"[AI] {type(e).__name__} on image model {image_model}: {e}")
                from app.utils import apihealth
                apihealth.record("error", text, model=image_model)
            else:
                from app.utils import apihealth
                apihealth.record("rate_limit", text, model=image_model)
            if not pinned and _fallback_client():
                continue
            raise


async def _create_transcription(whisper_model, audio_file):
    """Transcription, where voice messages are set to be heard; on Groq with key fallback."""
    if not _initialised:
        init_ai()

    async def elsewhere(client, mid):
        return await client.audio.transcriptions.create(model=mid, file=audio_file)

    async def on_groq(mid):
        # the same file object, read once already if another provider failed first
        try:
            audio_file.seek(0)
        except Exception:
            pass
        return await _groq_transcription(mid or whisper_model, audio_file)

    return await _job_call("stt", elsewhere, on_groq)


async def _groq_transcription(whisper_model, audio_file):
    if not _groq_clients:
        raise RuntimeError(
            "Transcribing a voice message needs a Groq key, or another provider picked "
            "for voice messages under Settings > Models.")
    while True:
        try:
            transcription = await _active_client().audio.transcriptions.create(
                model=whisper_model,
                file=audio_file,
            )
            return transcription
        except RateLimitError:
            if _fallback_client():
                continue
            raise
        except Exception as e:
            if "rate" not in str(e).lower() and "429" not in str(e):
                print(f"[AI] {type(e).__name__} on whisper model {whisper_model}: {e}")
            if _fallback_client():
                continue
            raise


def _small_model_name() -> str:
    """The Groq model for utility calls (memory, language, summaries); falls back to the last configured chat model."""
    try:
        from app.utils.helpers import load_config
        bcfg = load_config().get("bot") or {}
        small = bcfg.get("groq_small_model")
        if small:
            return small
        models = bcfg.get("groq_models") or []
        if models:
            return models[-1]
    except Exception:
        pass
    return model


async def _create_small_completion(messages, **kwargs):
    """Utility completion (memory, language, summaries): wherever background work is set to run, a small Groq model by default (frequent calls don't need a 120B), else the main chat model."""
    if not _initialised:
        init_ai()
    from app.utils import providers
    config = load_config()

    # No Groq key and background work left on Groq: it would fail every time, so it goes to whatever writes the replies instead.
    if not _groq_clients and providers.job(config, "small")["provider"] == "groq":
        for entry in providers.reply_chain(config):
            client = _openai_client(entry["provider"], config) if entry["provider"] != "groq" else None
            if client is not None:
                return await client.chat.completions.create(model=entry["model"], messages=messages, **kwargs)
        raise RuntimeError("No model is set up for background work.")

    async def elsewhere(client, mid):
        return await client.chat.completions.create(model=mid, messages=messages, **kwargs)

    async def on_groq(small):
        small = small or _small_model_name()
        main = next((e["model"] for e in providers.reply_chain(config) if e["provider"] == "groq"), small)
        targets = [small] if small == main else [small, main]
        while True:
            try:
                return await _active_client().chat.completions.create(
                    model=targets[0], messages=messages, **kwargs
                )
            except RateLimitError:
                if _fallback_client():
                    continue
                if len(targets) > 1:
                    targets.pop(0)
                    continue
                raise
            except Exception:
                if len(targets) > 1:
                    targets.pop(0)
                    continue
                raise

    return await _job_call("small", elsewhere, on_groq)


def _reasoning_of(response) -> str:
    """A reasoning model's thinking, when the provider sent it back.

    Groq puts it in `reasoning`, DeepSeek and vLLM in `reasoning_content`, and
    some models (qwen3, deepseek-r1 served raw) write it into the answer inside
    <think> tags. The Logs page shows it, folded, next to the reply.
    """
    try:
        msg = response.choices[0].message
    except Exception:
        return ""
    text = getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None)
    if not text:
        extra = getattr(msg, "model_extra", None) or {}
        text = extra.get("reasoning") or extra.get("reasoning_content")
    if not text:
        m = re.search(r"<think>(.*?)</think>", msg.content or "", re.S)
        text = m.group(1) if m else ""
    return (text or "").strip()


def _answer_of(response) -> str:
    """The reply text, with any <think> block taken out of it."""
    content = response.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>\s*", "", content, flags=re.S)


def _show_thinking(response):
    thought = _reasoning_of(response)
    if thought:
        log_thinking(thought, last_reply_model)


async def generate_response(prompt, instructions, history=None):
    """Completion request returning the response text; if history is passed the caller already appended the user turn as the last entry and prompt is NOT added again, otherwise prompt is the sole user message."""
    if not _initialised:
        init_ai()
    try:
        messages = [{"role": "system", "content": instructions}]
        if history:
            messages += history
        else:
            messages.append({"role": "user", "content": prompt})

        cap = _reply_token_cap()
        try:
            response = await _create_completion(messages, max_tokens=cap)
        except RequestTooLarge as first:
            # same 429, two opposite fixes; asking for the wrong one is why this used to trim history three times and get refused three times
            if is_output_limit(first):
                # The allowance is on the reply. Ask for a shorter one.
                for _ in range(3):
                    cap = max(MIN_MAX_REPLY_TOKENS, cap // 2)
                    log_system(f"Reply allowance exceeded, retrying with max_tokens={cap}")
                    try:
                        response = await _create_completion(messages, max_tokens=cap)
                        break
                    except RequestTooLarge as again:
                        if not is_output_limit(again) or cap <= MIN_MAX_REPLY_TOKENS:
                            raise
                else:
                    raise
            else:
                # conversation outgrew one request: the cap is per organisation so no key/model can take it, send less; oldest turns go first, system prompt always kept
                trimmed = messages
                for _ in range(3):
                    head = [m for m in trimmed if m.get("role") == "system"]
                    rest = [m for m in trimmed if m.get("role") != "system"]
                    if len(rest) <= 2:
                        raise
                    rest = rest[len(rest) // 2:]
                    trimmed = head + rest
                    log_system(
                        f"Request too large, retrying with the last {len(rest)} messages")
                    try:
                        response = await _create_completion(trimmed, max_tokens=cap)
                        break
                    except RequestTooLarge:
                        continue
                else:
                    raise
        _show_thinking(response)
        return _answer_of(response)
    except Exception as e:
        # Rate-limit errors are handled and logged by the retry loop in main.py,
        # and a request too big for the model is explained there, in words.
        if isinstance(e, RequestTooLarge) or is_request_too_large(e):
            raise
        # A model that will not load is said once while it is left alone, not on every message.
        if isinstance(e, ModelWontLoad) and not _first_time(f"error {e}", 600.0):
            raise
        if "429" not in str(e) and "rate_limit_exceeded" not in str(e) and "Rate limit" not in str(e):
            print_error("AI Error", e)
            await webhook_log(None, e)
        raise


GROQ_IMAGE_SIZE_LIMIT = 20 * 1024 * 1024  # 20MB


# one aiohttp session for image fetches, instead of a fresh TCP connection and TLS handshake per image
_image_http_session = None


async def _image_session():
    """The shared aiohttp session, created on first use."""
    global _image_http_session
    import aiohttp
    if _image_http_session is None or _image_http_session.closed:
        _image_http_session = aiohttp.ClientSession()
    return _image_http_session


def _to_static_jpeg(data: bytes) -> bytes:
    """One frame of any image, as a plain JPEG under Groq's size limit.

    The vision model only accepts a still image it can decode. A GIF, an
    animated WebP, an APNG or a Discord sticker handed over as its raw bytes
    came back "invalid image data" (seen repeatedly in the log). Opening it
    with Pillow and saving the first frame as JPEG makes every one of those a
    valid still - and re-encoding a normal photo costs almost nothing.

    Blocking (Pillow), so it is always called on a thread.
    """
    import io
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    try:
        img.seek(0)          # first frame of an animated image
    except (EOFError, ValueError):
        pass
    if img.mode not in ("RGB", "L"):
        # Flatten transparency onto white so a sticker's cutout does not turn
        # into a black block.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")

    # Progressively reduce quality/size until under limit
    for quality in (85, 70, 55, 40):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        if buf.tell() <= GROQ_IMAGE_SIZE_LIMIT:
            break
        # Still too big, halve the dimensions (never below 1px)
        img = img.resize(
            (max(1, img.width // 2), max(1, img.height // 2)), Image.LANCZOS
        )
    buf.seek(0)
    return buf.read()


async def _prepare_image_url(image_url: str) -> str:
    """Fetch the image and return a base64 data URL (compressing if over the 20MB limit); Discord CDN links are authenticated and expiring, so Groq can't fetch them directly."""
    import io
    import base64

    try:
        if image_url.startswith("data:"):
            # Already a base64 data URL (e.g. a Snapchat snap screenshot).
            header, _, b64data = image_url.partition(",")
            content_type = (header[5:].split(";")[0] or "image/jpeg")
            data = base64.b64decode(b64data)
        else:
            import aiohttp
            session = await _image_session()
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    raise Exception(f"Image fetch failed with HTTP {resp.status}")
                content_type = resp.content_type or "image/jpeg"
                data = await resp.read()

        # Always normalise to a still JPEG rather than forwarding the raw bytes:
        # that is what makes stickers, GIFs and animated images work instead of
        # coming back "invalid image data". A data: URL that is already a plain
        # JPEG or PNG under the limit is passed straight through.
        if (image_url.startswith("data:") and content_type in ("image/jpeg", "image/png")
                and len(data) <= GROQ_IMAGE_SIZE_LIMIT):
            b64 = base64.b64encode(data).decode()
            return f"data:{content_type};base64,{b64}"
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            return image_url  # Pillow not installed, fall back to original
        # decode/first-frame/re-encode on a worker thread: it is CPU-bound, and
        # one large photo on the event loop stalled every other conversation.
        import asyncio
        jpeg = await asyncio.to_thread(_to_static_jpeg, data)
        b64 = base64.b64encode(jpeg).decode()
        return f"data:image/jpeg;base64,{b64}"

    except Exception:
        raise  # Propagate so generate_response_image can fall back to text-only


async def generate_response_image(prompt, instructions, image_url, history=None):
    if not _initialised:
        init_ai()
    try:
        _cfg = load_config()
        _image_model = _cfg["bot"].get("groq_image_model", "meta-llama/llama-4-scout-17b-16e-instruct")
        try:
            prepared_url = await _prepare_image_url(image_url)
        except Exception as img_err:
            print(f"[AI] Image preparation failed ({img_err}), falling back to text-only response")
            return await generate_response(prompt, instructions, history)

        image_response = await _create_image_completion(
            _image_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Describe / Explain in detail this image sent by a Discord user to an AI who will be responding to the message '{prompt}' based on your output as the AI cannot see the image. So make sure to tell the AI any key details about the image that you think are important to include in the response, especially any text on screen that the AI should be aware of.",
                        },
                        {"type": "image_url", "image_url": {"url": prepared_url}},
                    ],
                }
            ],
        )

        _image_desc = image_response.choices[0].message.content
        if getenv("SNAP_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
            _d = " ".join(str(_image_desc).split())  # collapse newlines/extra spaces (full text, one line)
            print(f"  👁 \033[2msaw:\033[0m {_d}")
        prompt_with_image = f"{prompt} [Image of {_image_desc}]"

        if history:
            # caller already appended the plain user message to history, swap the last entry for the image-enriched version
            if history[-1].get("role") == "user":
                history[-1] = {"role": "user", "content": prompt_with_image}
            else:
                history.append({"role": "user", "content": prompt_with_image})
            messages = [
                {
                    "role": "system",
                    "content": instructions + " Images sent to you appear as '[Image of ...]', treat that description as an image you can actually see.",
                },
                *history,
            ]
        else:
            history = [{"role": "user", "content": prompt_with_image}]
            messages = [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt_with_image},
            ]

        response = await _create_completion(messages)
        _show_thinking(response)
        answer = _answer_of(response)
        # Append the assistant turn only when history was created locally.
        if len(history) == 1 and history[0].get("content") == prompt_with_image:
            history.append({"role": "assistant", "content": answer})
        return answer
    except Exception as e:
        print_error("AI image Error", e)
        raise


async def extract_memory(user_message: str, assistant_reply: str, existing_memory: dict = None) -> dict:
    """Ask the LLM to decide what's worth remembering, free-form key/value."""
    if not _initialised:
        init_ai()

    existing_block = ""
    if existing_memory:
        existing_block = (
            "\nAlready stored facts (do NOT re-extract these unless the value changed):\n"
            + "\n".join(f"  {k}: {v}" for k, v in existing_memory.items())
            + "\n"
        )

    prompt = (
        f'User message: "{user_message}"\n'
        f'Assistant reply: "{assistant_reply}"\n'
        f'{existing_block}\n'
        "Extract anything the USER said about themselves that would be useful to "
        "know in a later conversation.\n"
        "WORTH REMEMBERING (examples, not a fixed list):\n"
        "- who they are: name, age, where they live, language, job, school\n"
        "- what they like and dislike: games, music, films, food, teams\n"
        "- their life: pets, family, partner, friends they mention by name\n"
        "- what they do: hobbies, sports, what they are studying or working on\n"
        "- plans and events they mention, and anything they ask you to remember\n"
        "RULES:\n"
        "- Only extract from the USER message. Ignore the assistant reply.\n"
        "- Ignore Discord @mentions. They are not the user's name.\n"
        "- Ignore passing moods: tired, bored, sad, happy, busy right now.\n"
        "- Ignore empty values: yes, no, maybe, idk.\n"
        "- Ignore questions. A question tells you nothing about them.\n"
        "- Keys are short lowercase snake_case, like name, city, favourite_game, pet_name.\n"
        "- Prefer recording something over recording nothing, as long as the user "
        "actually said it about themselves.\n"
        "If there is genuinely nothing, return exactly: {}\n"
        "Return ONLY the JSON object. No explanation, no markdown, no extra text."
    )

    try:
        response = await _create_small_completion(
            [
                {
                    "role": "system",
                    "content": "You are a JSON-only memory extractor. Output nothing except a valid JSON object."
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        if not text.startswith("{"):
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return {}
        # Sanitise keys: lowercase, snake_case, max 40 chars
        clean = {}
        for k, v in parsed.items():
            key = str(k).lower().replace(" ", "_").replace("-", "_")[:40]
            val = str(v).strip()
            if key and val and len(val) >= 2:
                clean[key] = val
        return clean
    except json.JSONDecodeError:
        return {}
    except Exception as e:
        if "429" not in str(e) and "rate" not in str(e).lower():
            print_error("Memory Extract Error", e)
        return {}


async def detect_memory_deletion(user_message: str, current_memory: dict) -> list:
    """Ask the LLM to detect if the user is retracting, correcting, or joking about a stored fact."""
    if not _initialised:
        init_ai()
    if not current_memory:
        return []

    memory_lines = "\n".join(f"- {k}: {v}" for k, v in current_memory.items())
    prompt = (
        f'Stored facts about the user:\n{memory_lines}\n\n'
        f'New user message: "{user_message}"\n\n'
        "Does the user's message indicate that any stored fact is WRONG, was a JOKE, should be FORGOTTEN, "
        "or is being CORRECTED? This includes:\n"
        "- Explicit corrections: 'I'm not actually 22', 'my name isn't Jake', 'I lied about my job'\n"
        "- Jokes/retractions: 'lol I was kidding', 'that was a joke', 'I made that up'\n"
        "- Forget requests: 'forget what I said about my age', 'don't remember that', 'ignore that'\n"
        "- Contradictions: if they previously said location=Paris and now say 'I live in Tokyo'\n\n"
        "Return ONLY a JSON array of key names that should be DELETED from memory. "
        "Example: [\"age\", \"location\"]\n"
        "If nothing should be deleted, return exactly: []\n"
        "Return ONLY the JSON array. No explanation, no markdown, no extra text."
    )

    try:
        response = await _create_small_completion(
            [
                {
                    "role": "system",
                    "content": "You are a JSON-only memory auditor. You output nothing except valid JSON arrays of strings."
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=100,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        if not text.startswith("["):
            return []
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return []
        return [k for k in parsed if isinstance(k, str)]
    except json.JSONDecodeError:
        return []
    except Exception as e:
        if "429" not in str(e) and "rate" not in str(e).lower():
            print_error("Memory Deletion Detect Error", e)
        return []


async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe a voice message using Groq Whisper."""
    if not _initialised:
        init_ai()

    try:
        import io
        whisper_model = load_config()["bot"].get("groq_whisper_model", "whisper-large-v3-turbo")
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        transcription = await _create_transcription(whisper_model, audio_file)
        return transcription.text.strip()
    except Exception as e:
        print_error("Whisper Error", e)
        return ""


async def detect_language(history: list, current_message: str) -> str:
    """Detect the user's language from recent history (last few turns, catches drift); returns a BCP-47 tag like 'fr' or '' on failure."""
    if not _initialised:
        init_ai()

    # Compact view of recent user messages so the LLM can see drift
    recent_user_msgs = [
        m["content"] for m in history[-8:] if m.get("role") == "user"
    ]
    # Always include the current message (it may not be in history yet)
    if not recent_user_msgs or recent_user_msgs[-1] != current_message:
        recent_user_msgs.append(current_message)

    sample = "\n".join(f"- {m}" for m in recent_user_msgs[-5:])

    prompt = (
        "Identify the single most likely language the user is writing in based on these recent messages.\n\n"
        f"Messages:\n{sample}\n\n"
        "Reply with ONLY the BCP-47 language tag (e.g. 'en', 'fr', 'es', 'ar', 'de', 'pt', 'it', 'nl', 'ru', 'ja', 'zh').\n"
        "No explanation, no punctuation, no extra text."
    )

    try:
        response = await _create_small_completion(
            [
                {
                    "role": "system",
                    "content": "You are a language detector. Output only a BCP-47 language tag.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=8,
            temperature=0.0,
        )
        tag = response.choices[0].message.content.strip().lower().split("-")[0]
        # Basic sanity check, reject anything that looks like a sentence
        if not tag.isalpha() or len(tag) > 5:
            return ""
        return tag
    except Exception:
        # Empty means "couldn't tell", the caller keeps the language it had.
        return ""


async def summarize_history(history: list, instructions: str) -> list:
    """Compress long history into summary + recent messages to save tokens."""
    if not _initialised:
        init_ai()

    KEEP_RECENT = 6
    if len(history) <= KEEP_RECENT + 2:
        return history

    to_summarize = history[:-KEEP_RECENT]
    recent = history[-KEEP_RECENT:]

    lines = []
    for msg in to_summarize:
        role = "User" if msg["role"] == "user" else "You"
        lines.append(role + ": " + msg["content"])
    transcript = "\n".join(lines)

    summary_prompt = (
        "Here is a conversation transcript:\n\n" + transcript + "\n\n"
        "Write a brief summary of this conversation in 2-3 sentences from your perspective. "
        "Focus on key facts, topics discussed, and the emotional tone. "
        "Write in first person as if you are remembering what was discussed."
    )

    try:
        response = await _create_small_completion(
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": summary_prompt},
            ],
            max_tokens=200,
            temperature=0.3,
        )
        summary_text = response.choices[0].message.content.strip()
        summary_msg = {
            "role": "assistant",
            "content": "[Earlier in this conversation: " + summary_text + "]"
        }
        return [summary_msg] + recent
    except Exception:
        return history


# Memory-page summary lengths: how many points go under the headline, and the output allowance that fits them with room to spare (a model that reasons spends some of it thinking)
SUMMARY_LENGTHS = {
    "short": ("two points", 200),
    "medium": ("three or four points", 380),
    "detailed": ("five or six points", 600),
}

_LANGUAGE_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German",
    "pt": "Portuguese", "it": "Italian", "ar": "Arabic", "nl": "Dutch",
}


def summary_instructions(their_name: str, length: str = "medium",
                         language: str = "auto") -> str:
    """The system prompt for a Memory-page summary: deliberately not the persona, it describes the conversation for the account owner rather than taking part in it. The shape is fixed, a bold headline and a few short labelled points, because it is read at a glance (the Memory page, Big Picture) rather than studied: a paragraph of prose was a wall nobody read. webui/src/lib/summarymd.ts draws exactly this shape."""
    points = SUMMARY_LENGTHS.get(length, SUMMARY_LENGTHS["medium"])[0]
    if language and language != "auto":
        lang = f"Write it in {_LANGUAGE_NAMES.get(language, language)}, labels included."
    else:
        lang = "Write it in the language the conversation is mostly in, labels included."
    return (
        "You summarise a chat conversation for the person who owns the account. "
        f"Lines marked 'Me' were sent by that account; the others are from {their_name}. "
        "Reply with exactly this shape and nothing else:\n"
        "**<what the conversation is mainly about, at most 10 words>**\n"
        "- **<Label>:** <one short line, at most 14 words>\n"
        f"Under the headline, write {points}, one per line, each starting with '- '. "
        "A label is one to three words, like Topics, Vibe, Plans, Mood, Inside jokes or Waiting on. "
        f"Use Waiting on for anything left open: a question {their_name} is still waiting on, "
        "a plan, a promise. Say each thing once, in plain words. "
        "No other headings, no intro, no closing line, no quotes of whole messages. "
        "Refer to them by name and to the account as 'you'. "
        "Stick to what the messages actually say; do not guess at anything else. "
        + lang
    )


def _tidy_summary(text: str) -> str:
    """A summary as the Memory page draws it: a model's thinking, a code fence round the whole reply and its own preamble ("Here is the summary:") taken out, blank lines between points closed up, and "*" or "•" bullets made "-"."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not lines and re.match(r"(?i)^(here'?s|here is|summary)\b[^:\n]{0,40}:$", line):
            continue
        lines.append(re.sub(r"^[*•]\s+", "- ", line))
    return "\n".join(lines)


async def summarize_conversation(lines: list, their_name: str,
                                 length: str = "medium", language: str = "auto") -> str:
    """Summarise (speaker, text) pairs oldest-first, "" on failure; runs on the small model like the history compressor."""
    if not lines:
        return ""
    transcript = "\n".join(f"{who}: {text}" for who, text in lines)
    cap = SUMMARY_LENGTHS.get(length, SUMMARY_LENGTHS["medium"])[1]
    response = await _create_small_completion(
        [
            {"role": "system", "content": summary_instructions(their_name, length, language)},
            {"role": "user", "content": "The conversation, oldest first:\n\n" + transcript},
        ],
        max_tokens=cap,
        temperature=0.3,
    )
    # A reasoning model can leave its thinking in the reply; _tidy_summary takes it out with the rest.
    return _tidy_summary(response.choices[0].message.content or "")


async def generate_nudge(original_message: str, days_elapsed: float, instructions: str) -> str:
    """Nudge for a conversation the bot never replied to; tone shifts with the gap: <1.5 days brief ack, 1.5-3 days casual brush-over, 3+ days just resume naturally."""
    if not _initialised:
        init_ai()

    if days_elapsed < 1.5:
        tone_hint = (
            "You only just noticed you missed their message. Give a very brief, casual acknowledgement "
            "of missing it, one short phrase max, then respond to what they actually said. "
            "Examples of the acknowledgement part: 'omg just saw this', 'wait I missed this lol', 'my bad just seeing this'. "
            "Keep the whole message short and natural."
        )
    elif days_elapsed < 3:
        tone_hint = (
            "A couple of days have passed since their message. You may or may not acknowledge the gap, "
            "do what feels most natural. If you do acknowledge it, keep it very brief and casual. "
            "Either way, respond to what they actually said. Don't overthink it."
        )
    else:
        tone_hint = (
            "Several days have passed. Don't acknowledge the gap at all, just resume the conversation "
            "naturally as if you're picking up where you left off. Real people do this all the time."
        )

    prompt = (
        f"The person sent you this message {days_elapsed:.1f} day(s) ago and you never replied:\n"
        f"\"{original_message}\"\n\n"
        f"{tone_hint}\n\n"
        "Write your reply now. Stay completely in character. No bullet points, no formal structure."
    )

    try:
        response = await _create_completion([
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt},
        ])
        return response.choices[0].message.content.strip()
    except Exception as e:
        if "429" not in str(e) and "rate" not in str(e).lower():
            print_error("Nudge Generate Error", e)
        return ""

