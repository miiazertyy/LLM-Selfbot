import sys
import json

from groq import AsyncGroq, RateLimitError
from os import getenv
from dotenv import load_dotenv
from app.utils.helpers import get_env_path, load_config
from app.utils.error_notifications import webhook_log, print_error
from app.utils.logger import log_model_fallback, log_system

# Active Groq clients, one per API key
_groq_clients = []   # list of {"client": AsyncGroq, "label": str}
_client_index = 0    # which key is currently active

# The local server, when one is configured. It speaks the same API as Groq, so
# it is the same object shape and every call below works unchanged.
_local_client = None
_local_model = ""
_local_vision = False
# Per-capability models. Empty means "this server does not do that job", and the
# call falls through to Groq exactly as it always did. Naming a model is the
# opt-in: a server that has no /audio/speech route simply never gets one set.
_local_vision_model = ""
_local_stt_model = ""
_local_tts_model = ""
_local_tts_voice = ""
_local_base_url = ""
_local_api_key = ""

model = None
groq_models = []
current_model_index = 0

# A local server raises openai's RateLimitError, Groq raises its own, and they
# are different classes even though one SDK is built on the other. Catching only
# one of them meant a local server under load fell through to the generic
# handler and looked like a crash.
#
# openai is NOT imported here to widen the tuple. It is a heavy import - around
# 620ms on top of groq, measured, and paid by every worker process on every
# launch - and it is only ever needed when a local server is configured.
# init_ai() adds the class when it builds the local client, by which point
# openai is being imported anyway. Every `except RATE_LIMITED` re-reads this
# global, so extending it later covers the handlers that already exist.
RATE_LIMITED = (RateLimitError,)


def _active_client():
    """Return the currently active Groq client."""
    return _groq_clients[_client_index]["client"]


def local_active() -> bool:
    """True when replies are being generated on this machine."""
    return _local_client is not None


def groq_key_count() -> int:
    """How many Groq keys are loaded.

    Callers that can spread independent work across keys use this to decide how
    many to run at once. Rate limits are per key, so two keys really are two
    separate allowances rather than one shared faster one.
    """
    if not _groq_clients and _local_client is None:
        init_ai()
    return len(_groq_clients)


def groq_key_label(index: int) -> str:
    """The display label for one key, for logs."""
    if not _groq_clients:
        return ""
    return _groq_clients[index % len(_groq_clients)]["label"]


def vision_is_local() -> bool:
    """Whether pictures are read by the local server rather than by Groq."""
    return _local_client is not None and bool(_local_vision_model)


def stt_is_local() -> bool:
    """Whether voice messages are transcribed here rather than by Groq."""
    return _local_client is not None and bool(_local_stt_model)


def local_tts() -> dict:
    """What tts.py needs to talk to the local server, or {} if it cannot.

    Speech lives in its own module with its own client, so rather than export
    four globals it gets the one dict it would otherwise have to assemble.
    """
    if not _groq_clients and _local_client is None:
        init_ai()
    if _local_client is None or not _local_tts_model:
        return {}
    return {
        "base_url": _local_base_url,
        "api_key": _local_api_key,
        "model": _local_tts_model,
        "voice": _local_tts_voice,
    }


def _chat_client():
    """Whoever is writing the replies: the local server, or Groq.

    Each capability moves on its own. Chat follows the local server whenever one
    is configured; images, transcription and speech follow it only once a model
    has been named for that job, because most servers do not offer all four and
    silently losing voice messages would be worse than a request going out to an
    API. Name all four and no Groq key is needed at all.
    """
    return _local_client if _local_client is not None else _active_client()


def _chat_model() -> str:
    return _local_model if _local_client is not None else model


def init_ai():
    global _groq_clients, _client_index, model, groq_models, current_model_index
    global _local_client, _local_model, _local_vision
    global _local_vision_model, _local_stt_model, _local_tts_model
    global _local_tts_voice, _local_base_url, _local_api_key
    global RATE_LIMITED
    env_path = get_env_path()
    config = load_config()
    load_dotenv(dotenv_path=env_path, override=True)

    # ── The local server, if one is set up ────────────────────────────────────
    from app.utils import localai
    _local_client, _local_model, _local_vision = None, "", False
    _local_vision_model = _local_stt_model = _local_tts_model = ""
    _local_tts_voice = _local_base_url = _local_api_key = ""
    if localai.active(config):
        from openai import AsyncOpenAI
        # openai is loaded now regardless, so this is the moment to teach the
        # rate-limit check about its RateLimitError.
        from openai import RateLimitError as _OpenAIRateLimit
        if _OpenAIRateLimit not in RATE_LIMITED:
            RATE_LIMITED = (*RATE_LIMITED, _OpenAIRateLimit)
        cfg = localai.settings(config)
        # An explicit timeout, because the SDK's default is ten minutes and a
        # local server that accepts the connection and then never answers (one
        # that is loading a model, or wedged) would hold a reply open for all of
        # it. A reply that takes four minutes is already useless to a
        # conversation, so this is a backstop rather than a target.
        _local_client = AsyncOpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"],
                                    timeout=240.0, max_retries=1)
        _local_model = cfg["model"]
        _local_vision = cfg["vision"]
        _local_base_url = cfg["base_url"]
        _local_api_key = cfg["api_key"]
        # A separate vision model wins; otherwise the old "use it for images
        # too" switch means the chat model does both, which is how this worked
        # before there was anywhere to name a second one.
        _local_vision_model = cfg["vision_model"] or (_local_model if _local_vision else "")
        _local_stt_model = cfg["stt_model"]
        _local_tts_model = cfg["tts_model"]
        _local_tts_voice = cfg["tts_voice"]
        log_system(f"Replies run locally on {_local_model} via {cfg['base_url']}")
        extra = [n for n, m in (("images", _local_vision_model),
                                ("transcription", _local_stt_model),
                                ("speech", _local_tts_model)) if m]
        if extra:
            log_system(f"Local server also handles {', '.join(extra)}")

    # Load keys: GROQ_API_KEY_1, GROQ_API_KEY_2, ...
    # Falls back to legacy GROQ_API_KEY if no numbered keys are set.
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

    # Running locally is a complete answer to "where do replies come from", so
    # a missing Groq key is only fatal when nothing else can write them.
    if not keys and _local_client is None:
        print("No GROQ_API_KEY found in .env, exiting.")
        sys.exit(1)

    _groq_clients = [
        {"client": AsyncGroq(api_key=key), "label": label}
        for label, key in keys
    ]
    _client_index = 0

    raw = config["bot"]["groq_models"]
    if isinstance(raw, str):
        groq_models = [m.strip() for m in raw.split(",") if m.strip()]
    else:
        groq_models = list(raw)
    current_model_index = 0
    model = groq_models[0]

    key_count = len(_groq_clients)
    if key_count:
        log_system(f"Loaded {key_count} Groq API key(s), {len(groq_models)} model(s).")
    elif _local_client is not None:
        missing = [n for n, m in (("pictures", _local_vision_model),
                                  ("voice messages", _local_stt_model),
                                  ("speaking", _local_tts_model)) if not m]
        if missing:
            log_system("No Groq key set. Replies are local; "
                       f"{', '.join(missing)} are off.")
        else:
            log_system("No Groq key set, and none needed: everything is local.")


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


class RequestTooLarge(Exception):
    """One request needs more tokens than the plan allows per minute.

    Not a rate limit in the useful sense: waiting does not help, and neither
    does another key or another model, because the cap is on the organisation.
    The only fix is to send less, so this is raised rather than retried. It was
    being treated as a rate limit, which meant every key and every model was
    tried against a request that could never fit, three times a second.
    """


_TOO_LARGE_MARKERS = ("request too large", "reduce your message size",
                      "please reduce the length")

# The same 429 arrives for two completely different problems, and they need
# opposite fixes:
#
#   input  - the conversation sent is too big. Send fewer messages.
#   output - the reply the model is *expected* to produce is too big. Groq
#            enforces this before generating anything, against max_tokens, or
#            against the model's full default when max_tokens is not set.
#
# Trimming history for an output limit does nothing at all, which is exactly
# what it looked like: "retrying with the last 7 / 4 / 2 messages" and the same
# refusal each time, because the history was never the problem.
_OUTPUT_LIMIT_MARKERS = ("output tokens per minute", "otpm", "reduce max_tokens",
                         "expected output")

# A cap on the reply, so Groq is asked for something that fits.
#
# Without one, the expected output is whatever the model can produce - on a
# reasoning model that includes its thinking - and a free tier allowing 1000
# output tokens a minute refuses a short chat reply for wanting 1324. Replies
# here are cut to a few hundred characters before sending anyway, so a cap is
# not giving anything up.
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
        # Every model has been tried. Go back to the first one so the NEXT
        # request starts from the top: leaving `model` on the last one while
        # resetting only the index meant the next rotation logged
        # "gpt-oss-20b -> gpt-oss-20b" and retried the same model for ever.
        current_model_index = 0
        model = groq_models[0]
        _client_index = 0
        return False
    model = groq_models[current_model_index]
    _client_index = 0  # Reset to first key when switching models
    log_model_fallback(old_model, model)
    return True


async def _create_completion(messages, max_tokens=None):
    """Attempt completion with automatic key + model fallback on rate limit.

    max_tokens caps the reply. It is always sent: Groq checks the *expected*
    output against the per-minute output allowance before generating anything,
    and with no cap the expectation is the model's full default.
    """
    if not _groq_clients and _local_client is None:
        init_ai()

    # A local server has no keys to rotate and one model to rotate to, so none
    # of the fallback machinery below means anything: a failure is a failure.
    #
    # It deliberately does not fall back to Groq either. Turning this on is a
    # decision that these conversations do not leave the machine, and quietly
    # sending them to an API the moment the server stops would be the one
    # outcome nobody asked for. It is recorded instead, so the red mark in the
    # logs says what happened.
    if _local_client is not None:
        try:
            return await _local_client.chat.completions.create(
                model=_local_model,
                messages=messages,
                max_tokens=max_tokens or _reply_token_cap(),
            )
        except Exception as e:
            from app.utils import apihealth
            kind = "rate_limit" if isinstance(e, RATE_LIMITED) else "error"
            apihealth.record(kind, f"local server: {e}", model=_local_model)
            raise

    while True:
        try:
            response = await _active_client().chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens or _reply_token_cap(),
            )
            return response
        except RateLimitError as e:
            # A request that is simply too big cannot be rotated around: same
            # organisation, same cap, on every key and every model.
            if is_request_too_large(e):
                from app.utils import apihealth
                apihealth.record("rate_limit", str(e), model=model)
                raise RequestTooLarge(str(e)) from e
            if _fallback_client():
                continue
            if fallback_model():
                continue
            raise
        except Exception as e:
            if is_request_too_large(e):
                from app.utils import apihealth
                apihealth.record("rate_limit", str(e), model=model)
                raise RequestTooLarge(str(e)) from e
            if "rate" not in str(e).lower() and "429" not in str(e):
                print(f"[AI] {type(e).__name__} on {model}: {e}")
            if _fallback_client():
                continue
            if fallback_model():
                continue
            raise


async def _create_image_completion(image_model, messages, client_index=None, **extra):
    """Image description call with key fallback (no model fallback, image model is fixed).

    `extra` carries optional parameters such as max_tokens and reasoning_effort.
    Not every model accepts every one of them, so a rejection of the parameters
    themselves is retried without them rather than failing the whole call.

    `client_index` pins the call to one specific Groq key instead of using
    whichever is currently active. That is for callers running several of these
    at once - describing a folder of pictures, say - where each worker wants its
    own key and its own rate-limit allowance. A pinned call does not rotate on
    failure: rotating would land it on a key another worker is already using,
    and the caller is the one that knows how to back off. Left as None it
    behaves exactly as it always did.
    """
    if not _groq_clients and _local_client is None:
        init_ai()
    params = dict(extra)

    # Only when the local model was told it can read images. Most cannot, and a
    # text model handed a picture does not say so, it describes something it
    # never saw.
    if _local_client is not None and _local_vision_model:
        try:
            return await _local_client.chat.completions.create(
                model=_local_vision_model, messages=messages, **params
            )
        except Exception as e:
            from app.utils import apihealth
            apihealth.record("error", f"local vision: {e}", model=_local_vision_model)
            raise
    if not _groq_clients:
        raise RuntimeError(
            "Reading images needs a Groq key, or a local vision model set under "
            "Local AI.")

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
            # An unknown parameter is a 400 about the argument, not about the
            # image. Drop the optional ones once and try again.
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
    """Whisper transcription call with key fallback."""
    if not _groq_clients and _local_client is None:
        init_ai()
    # An OpenAI-compatible server with a whisper model loaded answers the same
    # /audio/transcriptions route Groq does, so the call below is identical.
    # Only servers that implement it get a model named here.
    if _local_client is not None and _local_stt_model:
        try:
            return await _local_client.audio.transcriptions.create(
                model=_local_stt_model, file=audio_file,
            )
        except Exception as e:
            from app.utils import apihealth
            apihealth.record("error", f"local transcription: {e}",
                             model=_local_stt_model)
            raise
    if not _groq_clients:
        raise RuntimeError(
            "Transcribing a voice message needs a Groq key, or a local speech "
            "to text model set under Local AI.")
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
    """The dedicated model for utility calls (memory, language, summaries).

    Falls back to the last configured chat model when no small model is set,
    so existing configs keep working.
    """
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
    """Utility completion (memory, language, summaries) with key fallback.

    Runs on the small model when one is available (these calls are frequent
    and don't need a 120B model), and falls back to the main chat model if
    the small one is rate limited or unavailable.
    """
    if not _groq_clients and _local_client is None:
        init_ai()
    # Locally there is one model, so the "cheap model for background work"
    # split does not apply: it is the same model either way.
    if _local_client is not None:
        return await _local_client.chat.completions.create(
            model=_local_model, messages=messages, **kwargs
        )
    small = _small_model_name()
    targets = [small] if small == model else [small, model]
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


async def generate_response(prompt, instructions, history=None):
    """Send a completion request to Groq and return the response text.

    history: list of {"role", "content"} dicts. When provided, the caller MUST
    have already appended the current user turn as the last entry, `prompt`
    is NOT appended again. When omitted, `prompt` is the sole user message.
    """
    if not _groq_clients and _local_client is None:
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
            # Two different problems arrive as the same 429, and they need
            # opposite fixes. Asking for the wrong one is why this used to
            # trim the history three times and get refused three times.
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
                # The conversation has grown past what one request may spend.
                # The cap is per organisation, so no key or model can take it:
                # the only way through is to send less. Older turns matter
                # least, so they go first, and the system prompt is always kept.
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
        return response.choices[0].message.content
    except Exception as e:
        # Rate-limit errors are handled and logged by the retry loop in main.py
        if "429" not in str(e) and "rate_limit_exceeded" not in str(e) and "Rate limit" not in str(e):
            print_error("AI Error", e)
            await webhook_log(None, e)
        raise


GROQ_IMAGE_SIZE_LIMIT = 20 * 1024 * 1024  # 20MB


# One aiohttp session for image fetches, instead of building and tearing one
# down per image - each of which meant a fresh TCP connection and TLS handshake.
_image_http_session = None


async def _image_session():
    """The shared aiohttp session, created on first use."""
    global _image_http_session
    import aiohttp
    if _image_http_session is None or _image_http_session.closed:
        _image_http_session = aiohttp.ClientSession()
    return _image_http_session


def _shrink_to_limit(data: bytes) -> bytes:
    """Compress an image until it fits Groq's limit. Blocking; call on a thread."""
    import io
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
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
    else:
        raise Exception("Image still over Groq's size limit after compression")

    buf.seek(0)
    return buf.read()


async def _prepare_image_url(image_url: str) -> str:
    """Fetch the image, encode as base64 (compress if over Groq's 20MB limit).

    Always returns a base64 data URL, Discord CDN links are authenticated and
    expiring, so Groq's servers can't fetch them directly.
    """
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

        if len(data) <= GROQ_IMAGE_SIZE_LIMIT:
            # Always encode as base64, raw Discord URLs are inaccessible from Groq
            b64 = base64.b64encode(data).decode()
            return f"data:{content_type};base64,{b64}"

        # Need to compress, use Pillow
        try:
            from PIL import Image
        except ImportError:
            return image_url  # Pillow not installed, fall back to original

        # Decode, resample and re-encode on a worker thread. These are
        # CPU-bound and were running straight on the event loop, so compressing
        # one large photo stalled every other conversation on the account for
        # as long as it took.
        import asyncio
        jpeg = await asyncio.to_thread(_shrink_to_limit, data)
        b64 = base64.b64encode(jpeg).decode()
        return f"data:image/jpeg;base64,{b64}"

    except Exception:
        raise  # Propagate so generate_response_image can fall back to text-only


async def generate_response_image(prompt, instructions, image_url, history=None):
    if not _groq_clients and _local_client is None:
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
            # The caller already appended the plain user message to history, 
            # update that last entry in-place with the image-enriched version.
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
        # Append the assistant turn only when history was created locally.
        if len(history) == 1 and history[0].get("content") == prompt_with_image:
            history.append({"role": "assistant", "content": response.choices[0].message.content})
        return response.choices[0].message.content
    except Exception as e:
        print_error("AI image Error", e)
        raise


async def extract_memory(user_message: str, assistant_reply: str, existing_memory: dict = None) -> dict:
    """Ask the LLM to decide what's worth remembering, free-form key/value."""
    if not _groq_clients and _local_client is None:
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
    if not _groq_clients and _local_client is None:
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
    if not _groq_clients and _local_client is None:
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
    """LLM-detected language of the user from recent history.

    Looks at the last few user turns so gradual language drift is caught.
    Returns a BCP-47 tag like 'fr', 'en', 'es'. Falls back to 'en' on error.
    """
    if not _groq_clients and _local_client is None:
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
    if not _groq_clients and _local_client is None:
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


async def generate_nudge(original_message: str, days_elapsed: float, instructions: str) -> str:
    """Generate a natural nudge message for a conversation the bot never replied to.

    The tone shifts based on how many days have passed:
    - < 1.5 days : brief acknowledgement that we missed it
    - 1.5–3 days : casual brush-over, might or might not acknowledge the gap
    - 3+ days    : just resume conversation naturally, no acknowledgement at all
    """
    if not _groq_clients and _local_client is None:
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

