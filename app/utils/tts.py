import re
from os import getenv
from app.utils.helpers import load_config, get_env_path
from dotenv import load_dotenv

# The default. Configurable, because Groq offers more than one voice model and
# the English one is no use to someone whose persona speaks Arabic.
TTS_MODEL = "canopylabs/orpheus-v1-english"


def _tts_model() -> str:
    try:
        return (load_config().get("bot", {}) or {}).get("groq_tts_model") or TTS_MODEL
    except Exception:
        return TTS_MODEL
TTS_MAX_CHARS = 180  # Orpheus hard limit is 200, stay safe with 180


_client = None
_local_client = None
_local_key = None   # the settings the cached local client was built from


def _get_local():
    """The local speech backend, or None when none is configured.

    Servers like LocalAI and Kokoro-FastAPI implement OpenAI's /audio/speech,
    so once a model is named the call is byte-for-byte the one Groq gets. The
    cache is keyed on the settings so editing them in the panel takes effect
    without a restart.
    """
    global _local_client, _local_key
    from app.utils import ai
    cfg = ai.local_tts()
    if not cfg:
        _local_client, _local_key = None, None
        return None
    key = (cfg["base_url"], cfg["api_key"], cfg["model"])
    if _local_client is None or _local_key != key:
        from openai import AsyncOpenAI
        _local_client = AsyncOpenAI(base_url=cfg["base_url"],
                                    api_key=cfg["api_key"], timeout=180.0,
                                    max_retries=1)
        _local_key = key
    return {"client": _local_client, "model": cfg["model"],
            "voice": cfg["voice"]}


def _get_client():
    """Groq client for TTS, built once and reused."""
    global _client
    if _client is not None:
        return _client
    load_dotenv(dotenv_path=get_env_path())
    # Try GROQ_API_KEY first, then GROQ_API_KEY_1, _2, etc.
    api_key = getenv("GROQ_API_KEY")
    if not api_key:
        for i in range(1, 10):
            api_key = getenv(f"GROQ_API_KEY_{i}")
            if api_key:
                break
    # Say which thing is missing, rather than building a client with
    # api_key=None and failing somewhere inside the SDK.
    if not api_key:
        raise RuntimeError(
            "Voice messages need a Groq key, or a local speech model set under "
            "Local AI.")
    from groq import AsyncGroq
    _client = AsyncGroq(api_key=api_key)
    return _client


def _clean_text_for_tts(text: str) -> str:
    """Strip markdown, emojis, mentions and URLs so they aren't read aloud."""
    text = re.sub(r"<@!?\d+>", "", text)
    text = re.sub(r"(\*{1,3}|_{1,3}|`{1,3})", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(
        r"[\U00010000-\U0010ffff"
        r"\U0001F300-\U0001F5FF"
        r"\U0001F600-\U0001F64F"
        r"\U0001F680-\U0001F6FF"
        r"\u2600-\u26FF\u2700-\u27BF]+",
        "", text, flags=re.UNICODE
    )
    text = text.replace("\u2014", "").replace("\u2013", "")
    return text.strip()


def _chunk_text(text: str, max_chars: int = TTS_MAX_CHARS) -> list[str]:
    """
    Split text into chunks of max_chars, breaking on sentence boundaries
    where possible so the audio sounds natural between chunks.
    """
    if len(text) <= max_chars:
        return [text]
    chunks = []
    sentences = re.split(r'(?<=[.!?])\s+', text)
    current = ""

    for sentence in sentences:
        if len(sentence) > max_chars:
            words = sentence.split()
            for word in words:
                if len(current) + len(word) + 1 > max_chars:
                    if current:
                        chunks.append(current.strip())
                    current = word
                else:
                    current = f"{current} {word}".strip()
        elif len(current) + len(sentence) + 1 > max_chars:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if c]


async def generate_voice_message(text: str) -> list[bytes] | None:
    """
    Generate voice message audio, on the local server when one has a speech
    model set and on Groq Orpheus otherwise.
    Returns a list of wav byte chunks (one per 180-char segment), or None on
    failure. Orpheus has a 200-char limit, so long responses are split.
    """
    config = load_config()
    tts_cfg = config["bot"].get("tts") or {}

    if not tts_cfg.get("enabled", True):
        return None

    local = _get_local()
    voice = tts_cfg.get("voice", "autumn")
    # The bracketed tones are Orpheus prompt syntax, not something the audio
    # format carries. Any other engine has no idea and simply reads "casual
    # warm" out loud before the message, so they only go to Groq.
    tones = tts_cfg.get("tones", ["[casual]", "[warm]"])
    tone_prefix = "" if local else " ".join(tones)
    if local:
        model = local["model"]
        client = local["client"]
        # Voice names are per-engine - Orpheus has "autumn", Kokoro has
        # "af_sky" - so the local one is set alongside the local model.
        voice = local["voice"] or voice
    else:
        model = _tts_model()
        client = _get_client()

    cleaned = _clean_text_for_tts(text)
    if not cleaned:
        return None

    # Reserve space for tone prefix on every chunk so style is consistent throughout
    chunk_max = max(40, TTS_MAX_CHARS - len(tone_prefix) - 1)
    text_chunks = _chunk_text(cleaned, max_chars=chunk_max)

    audio_chunks = []

    for i, chunk in enumerate(text_chunks):
        tts_input = f"{tone_prefix} {chunk}".strip() if tone_prefix else chunk

        try:
            response = await client.audio.speech.create(
                model=model,
                voice=voice,
                input=tts_input,
                response_format="wav",
            )
            audio_chunks.append(await response.read())
        except Exception as e:
            import traceback
            print(f"[TTS] Error on chunk {i + 1}/{len(text_chunks)}: {type(e).__name__}: {e}")
            traceback.print_exc()
            if i == 0:
                return None
            break

    return audio_chunks if audio_chunks else None
