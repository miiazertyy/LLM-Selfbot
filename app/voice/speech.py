"""Hearing and speaking with every provider that can, each in its own words.

Most providers hear and speak through the OpenAI-shaped /audio routes, which the OpenAI client already speaks
(ai._create_transcription, tts.py). These do not, so each has a few lines here: the models it has, the voices to
pick from, a function that hears a recording and one that says a line. Voice messages and calls both come through
here, so a provider added once works for both, and so does this computer's own voice (onboard.py).

Every speaker answers with mono 16-bit PCM and its rate: a call plays it as it is, a voice message wraps it in a WAV.
Each follows its provider's own documentation as it was in November 2026; the tests hold the requests to it against
stand-ins of their servers (tests/test_speech.py).
"""
import base64
import time

from app.voice.audio import read_wav

CARTESIA_VERSION = "2026-08-14"

# Where each one is. A module dict so the tests can point them at stand-ins.
URLS = {
    "deepgram": "https://api.deepgram.com/v1",
    "cartesia": "https://api.cartesia.ai",
    "elevenlabs": "https://api.elevenlabs.io/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "mistral": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "fish": "https://api.fish.audio",
    "rime": "https://coda.api.rime.ai",
    "minimax": "https://api.minimax.io/v1",
}

# How each one wants its key.
_AUTH = {
    "deepgram": lambda k: {"Authorization": f"Token {k}"},
    "cartesia": lambda k: {"Authorization": f"Bearer {k}", "Cartesia-Version": CARTESIA_VERSION},
    "elevenlabs": lambda k: {"xi-api-key": k},
    "gemini": lambda k: {"x-goog-api-key": k},
}

# What each hears and speaks with, in its own API: (model, a few words about it). The first is the default.
HEARS = {
    "deepgram": [("nova-3", "fast, many languages"), ("nova-2", "the one before")],
    "elevenlabs": [("scribe_v2", "very accurate")],
    "cartesia": [("ink-whisper", "made for calls")],
}
SPEAKS = {
    "elevenlabs": [("eleven_flash_v2_5", "the quickest"), ("eleven_turbo_v2_5", "quick"), ("eleven_v3", "most expressive")],
    # Deepgram's voice is its model: the model here is the family, and the voice picks one of it.
    "deepgram": [("aura-2", "made for calls")],
    "cartesia": [("sonic-3.6", "the newest"), ("sonic-3.5", ""), ("sonic-3", "")],
    "gemini": [("gemini-3.8-flash-tts", "quick"), ("gemini-3.8-flash-lite-tts", "quickest"),
               ("gemini-3.1-flash-tts-preview", ""), ("gemini-2.5-pro-preview-tts", "slower, richer")],
    "mistral": [("voxtral-mini-tts-3-0", "")],
    # xAI's speech takes no model at all: one name, so it can be picked like the others.
    "xai": [("grok-tts", "")],
    "fish": [("s2.1-pro", "the newest"), ("s2-pro", ""), ("s1", "the quickest"), ("s2.1-pro-free", "free tier")],
    "rime": [("coda", "")],
    "minimax": [("speech-2.8-turbo", "quick"), ("speech-2.8-hd", "richer"), ("speech-2.6-turbo", "")],
}
# OpenAI-shaped hearing these have, which are not always in their model lists.
HEARS_OPENAI_SHAPED = {
    "mistral": [("voxtral-mini-transcribe-3-0", "quick"), ("voxtral-small-transcribe-3-0", "more accurate")],
    "together": [("openai/whisper-large-v3", "")],
}


def native(job: str, pid: str, model: str = "") -> bool:
    """Whether this job on this provider goes through here rather than through the OpenAI client."""
    if pid == "local":
        from app.voice import onboard
        return onboard.is_builtin(model)
    return pid in (HEARS if job == "stt" else SPEAKS)


def models_for(pid: str) -> list:
    """The models a provider hears and speaks with here, as the Models tab lists models: [{id, capabilities}]."""
    out = [{"id": m, "capabilities": ["stt"]} for m, _ in HEARS.get(pid, []) + HEARS_OPENAI_SHAPED.get(pid, [])]
    out += [{"id": m, "capabilities": ["tts"]} for m, _ in SPEAKS.get(pid, []) if pid != "elevenlabs"]
    return out


def default_model(job: str, pid: str) -> str:
    table = HEARS if job == "stt" else SPEAKS
    if pid in table:
        return table[pid][0][0]
    if job == "stt":
        return {"groq": "whisper-large-v3-turbo", "openai": "gpt-4o-mini-transcribe",
                "mistral": "voxtral-mini-transcribe-3-0", "together": "openai/whisper-large-v3"}.get(pid, "")
    return {"groq": "canopylabs/orpheus-v1-english", "openai": "gpt-4o-mini-tts"}.get(pid, "")


class SpeechError(RuntimeError):
    pass


def entry_of(raw) -> dict | None:
    """{"provider", "model"} from what a call picked ("provider:model"), or None for nothing picked."""
    from app.utils import providers
    pid, _, model = str(raw or "").strip().partition(":")
    return {"provider": pid, "model": model} if pid in providers.BY_ID and model else None


def _name(pid: str) -> str:
    from app.utils import providers
    return (providers.BY_ID.get(pid) or {}).get("name") or pid.title()


def _said(r) -> str:
    """What a refusal said, in a line."""
    try:
        data = r.json()
        if isinstance(data, dict):
            for k in ("message", "detail", "error", "err_msg", "reason"):
                v = data.get(k)
                if isinstance(v, dict):
                    v = v.get("message") or v.get("status")
                if v:
                    return str(v)[:160]
    except Exception:
        pass
    return (r.text or "")[:160]


async def _ask(pid: str, model: str, method: str, url: str, *, status_of=None, timeout: float = 45.0, count: bool = True,
               **kw):
    """One request to a provider, with each of its keys while they run out or are refused. Counted like every model
    call (app/utils/usage.py), never with its key; a list of voices is not a model call and is not counted."""
    import httpx
    from app.utils import providers, usage
    keys = providers.key_order(pid)
    if not keys:
        raise SpeechError(f"{_name(pid)} needs a key: add one under Settings > Models > Providers.")
    auth = _AUTH.get(pid, lambda k: {"Authorization": f"Bearer {k}"})
    extra = kw.pop("headers", {}) or {}
    problem = ""
    for key in keys:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                r = await http.request(method, url, headers={**auth(key), **extra}, **kw)
        except httpx.HTTPError as e:
            if count:
                usage.note(pid, model, 0, int((time.monotonic() - started) * 1000))
            raise SpeechError(f"Could not reach {_name(pid)} ({type(e).__name__}).") from e
        status = status_of(r) if status_of else r.status_code
        if count:
            usage.note(pid, model, status, int((time.monotonic() - started) * 1000), headers=r.headers)
        if status < 300:
            return r
        problem = f"{_name(pid)} said {status}: {_said(r)}"
        rest = providers.key_at_fault(status)
        if not rest:
            break
        providers.rest_key(pid, key, rest)
    raise SpeechError(problem)


def _mime(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {"wav": "audio/wav", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg", "mp3": "audio/mpeg",
            "m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm", "flac": "audio/flac"}.get(ext, "application/octet-stream")


# ── Hearing ───────────────────────────────────────────────────────────────

async def hear(pid: str, model: str, audio: bytes, filename: str = "voice.wav") -> str:
    """The words in a recording."""
    model = model or default_model("stt", pid)
    if pid == "local":
        from app.voice import onboard
        return await onboard.hear(model, audio)
    if pid == "deepgram":
        params = {"model": model, "smart_format": "true"}
        # Nova 3 hears several languages in one go when told to; the older ones work out which one it is.
        params.update({"language": "multi"} if model.startswith("nova-3") else {"detect_language": "true"})
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/listen", params=params, content=audio,
                       headers={"Content-Type": _mime(filename)})
        channels = ((r.json() or {}).get("results") or {}).get("channels") or [{}]
        alternatives = (channels[0] or {}).get("alternatives") or [{}]
        return str((alternatives[0] or {}).get("transcript") or "").strip()
    if pid == "elevenlabs":
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/speech-to-text", data={"model_id": model},
                       files={"file": (filename, audio, _mime(filename))})
        return str((r.json() or {}).get("text") or "").strip()
    if pid == "cartesia":
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/stt", data={"model": model},
                       files={"file": (filename, audio, _mime(filename))})
        return str((r.json() or {}).get("text") or "").strip()
    raise SpeechError(f"{_name(pid)} does not hear here.")


# ── Speaking ──────────────────────────────────────────────────────────────

def _pcm(data: bytes, rate: int) -> tuple:
    """(pcm, rate) from what came back: a WAV says its own rate and sample size, anything else is taken as 16-bit at
    the rate asked for."""
    if data[:4] == b"RIFF":
        pcm, got, channels = read_wav(data)
        if channels > 1:
            from app.voice.audio import to_mono
            pcm = to_mono(pcm, channels)
        return pcm, got
    return data[: len(data) - (len(data) % 2)], rate


async def say(pid: str, model: str, voice: str, text: str) -> tuple:
    """One line out loud: (mono 16-bit pcm, its rate)."""
    model = model or default_model("tts", pid)
    voice = voice or DEFAULT_VOICE.get(pid, "")
    if pid == "local":
        from app.voice import onboard
        if onboard.is_builtin(model):
            return await onboard.say(model, voice, text)
    if pid == "elevenlabs":
        if not voice:
            raise SpeechError("Pick an ElevenLabs voice first.")
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/text-to-speech/{voice}", params={"output_format": "pcm_24000"},
                       json={"text": text, "model_id": model}, headers={"accept": "audio/pcm"})
        return _pcm(r.content, 24000)
    if pid == "deepgram":
        r = await _ask(pid, voice, "POST", f"{URLS[pid]}/speak", json={"text": text},
                       params={"model": voice, "encoding": "linear16", "sample_rate": "24000", "container": "none"})
        return _pcm(r.content, 24000)
    if pid == "cartesia":
        voice = voice or await _first_voice(pid)
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/tts/bytes", json={
            "model_id": model, "transcript": text, "voice": {"mode": "id", "id": voice},
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000}})
        return _pcm(r.content, 24000)
    if pid == "gemini":
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/interactions", json={
            "model": model,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": voice}]}})
        return _pcm(_gemini_audio(r.json()), 24000)
    if pid == "mistral":
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/audio/speech", json={
            "model": model, "input": text, "voice_id": voice, "response_format": "wav"})
        return _pcm(base64.b64decode((r.json() or {}).get("audio_data") or ""), 24000)
    if pid == "xai":
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/tts", json={
            "text": text, "voice_id": voice, "language": "auto", "output_format": {"codec": "wav", "sample_rate": 24000}})
        # Its reference says the audio comes back in JSON, as base64; its own examples save the body as it is.
        data = base64.b64decode(r.json().get("audio") or "") if "json" in r.headers.get("content-type", "") else r.content
        return _pcm(data, 24000)
    if pid == "fish":
        body = {"text": text, "format": "wav", "sample_rate": 24000, "latency": "balanced", "normalize": True}
        if voice:
            body["reference_id"] = voice
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/v1/tts", json=body, headers={"model": model})
        return _pcm(r.content, 24000)
    if pid == "rime":
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/", json={"text": text, "speaker": voice, "samplingRate": 24000},
                       headers={"Accept": "audio/wav"})
        return _pcm(r.content, 24000)
    if pid == "minimax":
        r = await _ask(pid, model, "POST", f"{URLS[pid]}/t2a_v2", status_of=_minimax_status, json={
            "model": model, "text": text, "stream": False,
            "voice_setting": {"voice_id": voice, "speed": 1, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 24000, "format": "wav", "channel": 1}, "output_format": "hex"})
        return _pcm(bytes.fromhex(((r.json() or {}).get("data") or {}).get("audio") or ""), 24000)
    return await _openai_shaped(pid, model, voice, text)


def _gemini_audio(data: dict) -> bytes:
    """The audio in a Gemini answer: the last audio piece of what the model put out."""
    found = ""
    for step in (data or {}).get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for part in step.get("content") or []:
            if part.get("type") == "audio" and part.get("data"):
                found = part["data"]
    if not found:
        # The older shape, should an answer come back in it.
        for cand in (data or {}).get("candidates") or []:
            for part in ((cand.get("content") or {}).get("parts")) or []:
                found = ((part.get("inlineData") or {}).get("data")) or found
    if not found:
        raise SpeechError("Gemini sent back no audio.")
    return base64.b64decode(found)


def _minimax_status(r) -> int:
    """MiniMax answers 200 and says what went wrong inside: its key refused and its rate limits are what matter."""
    if r.status_code != 200:
        return r.status_code
    try:
        code = int(((r.json() or {}).get("base_resp") or {}).get("status_code") or 0)
    except Exception:
        return 502
    return {0: 200, 1004: 401, 1002: 429, 1039: 429}.get(code, 400)


async def _openai_shaped(pid: str, model: str, voice: str, text: str) -> tuple:
    """Everyone who speaks through OpenAI's /audio/speech: OpenAI, Groq, a server on this computer."""
    from app.utils import ai
    from app.utils.helpers import load_config
    if not voice:
        voice = "marin" if "gpt-4o" in model else ("autumn" if "orpheus" in model else "alloy")

    async def once(client):
        res = await client.audio.speech.create(model=model, voice=voice, input=text, response_format="wav")
        return await res.read()

    return _pcm(await ai._with_each_key(pid, load_config(), once), 24000)


# ── Voices ────────────────────────────────────────────────────────────────

def _deepgram(rows: str, lang: str = "") -> list:
    out = []
    for row in rows.strip().splitlines():
        name, who, accent, traits = [x.strip() for x in row.split("|")]
        about = ("woman" if who == "f" else "man") + (f", {accent}" if accent else "") + f", {traits}"
        out.append((f"aura-2-{name}-{lang or 'en'}", name.capitalize(), about))
    return out


DEEPGRAM_VOICES = _deepgram("""
thalia|f||clear and confident
andromeda|f||casual and expressive
helena|f||caring and raspy
apollo|m||confident and casual
arcas|m||natural and smooth
aries|m||warm and energetic
amalthea|f|Filipino|cheerful
asteria|f||clear, knowledgeable
athena|f||calm, professional
atlas|m||enthusiastic, friendly
aurora|f||cheerful, energetic
callista|f||clear, energetic
cora|f||smooth and melodic
cordelia|f||approachable and warm
delia|f||casual and breathy
draco|m|British|warm baritone
electra|f||engaging
harmonia|f||empathetic and calm
hera|f||smooth and warm
hermes|m||expressive
hyperion|m|Australian|caring and warm
iris|f||cheerful and positive
janus|f|Southern|smooth
juno|f||natural and breathy
jupiter|m||expressive baritone
luna|f||friendly and natural
mars|m||patient baritone
minerva|f||positive and friendly
neptune|m||patient and polite
odysseus|m||calm and smooth
ophelia|f||enthusiastic
orion|m||approachable and calm
orpheus|m||clear and confident
pandora|f|British|calm and breathy
phoebe|f||energetic and casual
pluto|m||calm baritone
saturn|m||confident baritone
selene|f||expressive and energetic
theia|f|Australian|expressive and sincere
vesta|f||natural and patient
zeus|m||deep and smooth
""") + [(f"aura-2-{n}-{lang}", n.capitalize(), language) for lang, language, names in (
    ("es", "Spanish", "sirio nestor carina celeste alvaro diana aquila selena estrella javier agustina antonia gloria "
                      "luciano olivia silvia valerio"),
    ("fr", "French", "agathe hector"),
    ("de", "German", "elara aurelia lara julius fabian kara viktoria"),
    ("it", "Italian", "melia elio flavio maia cinzia cesare livia dionisio demetra"),
    ("nl", "Dutch", "beatrix daphne cornelia sander hestia lars roman rhea leda"),
    ("ja", "Japanese", "uzume ebisu fujin izanami ama"),
) for n in names.split()]

MISTRAL_VOICES = [(vid, name, lang) for vid, name, lang in (
    ("voice_478", "Sheila", "US English"), ("voice_447", "Margaret", "US English"), ("voice_485", "Rob", "US English"),
    ("voice_3150", "James", "US English"), ("voice_1787", "Mary", "UK English"), ("voice_1786", "Sky", "UK English"),
    ("voice_1788", "David", "UK English"), ("voice_590", "Harriet", "UK English"), ("voice_591", "Fred", "UK English"),
    ("voice_3149", "Hugo", "UK English"), ("voice_3147", "Howard", "UK English"), ("voice_592", "Marie", "French"),
    ("voice_3137", "Manon", "French"), ("voice_589", "Lea", "French"), ("voice_3141", "Camille", "French"),
    ("voice_483", "Elena", "Spanish"), ("voice_481", "Heidi", "German"), ("voice_482", "Lorenzo", "Italian"),
    ("voice_480", "Gabriela", "Portuguese"), ("voice_479", "Maryam", "Arabic"), ("voice_3143", "Jordi", "Catalan"),
    ("voice_3139", "Ananya", "Hindi"), ("voice_3153", "Himanshu", "Hindi"), ("voice_3146", "Olivia", "Hungarian"),
    ("voice_3133", "Haruto", "Japanese"), ("voice_3136", "Sung", "Korean"), ("voice_3135", "Jin", "Korean"),
    ("voice_3145", "Lotte", "Dutch"), ("voice_3134", "Lars", "Norwegian"), ("voice_3154", "Leon", "Polish"),
    ("voice_3155", "Irina", "Romanian"), ("voice_3132", "Tatiana", "Russian"), ("voice_3138", "Oran", "Turkish"),
    ("voice_3140", "Taras", "Ukrainian"), ("voice_3144", "Huong", "Vietnamese"), ("voice_3142", "Mei", "Chinese"))]

# The five its voice agent was made with first, then the rest of what its speech has.
XAI_VOICES = [(v, v.capitalize(), "") for v in (
    "eve ara rex sal leo carina zagan helix orion luna iris altair zenith perseus helios lux kepler rigel cosmo "
    "celeste ursa sirius lumen castor naksh atlas").split()]

RIME_VOICES = [
    ("astra", "Astra", "woman, bright and quick"), ("lyra", "Lyra", "woman, warm and lively"),
    ("luna", "Luna", "woman, bright and casual"), ("hesse", "Hesse", "woman, relaxed"),
    ("vespera", "Vespera", "woman, friendly"), ("clementine", "Clementine", "woman, warm and energetic"),
    ("eyre", "Eyre", "woman, calm and friendly"), ("lintel", "Lintel", "woman, polished"),
    ("celeste", "Celeste", "woman, young"), ("beatty", "Beatty", "man, easygoing"),
    ("godfrey", "Godfrey", "man, easygoing and lively"), ("cupola", "Cupola", "man, confident"),
    ("parapet", "Parapet", "man, fast Southern"), ("masonry", "Masonry", "man, low Southern"),
    ("albion", "Albion", "man, English"), ("bancroft", "Bancroft", "older man, composed"),
    ("marlu", "Marlu", "older man, Australian"), ("lawton", "Lawton", "older man")]

MINIMAX_VOICES = [
    ("English_Graceful_Lady", "Graceful Lady", "woman"), ("English_radiant_girl", "Radiant Girl", "young woman"),
    ("English_Insightful_Speaker", "Insightful Speaker", ""), ("English_Persuasive_Man", "Persuasive Man", "man"),
    ("English_expressive_narrator", "Expressive Narrator", ""), ("English_Lucky_Robot", "Lucky Robot", "a robot")]

OPENAI_VOICES = [
    ("marin", "Marin", "natural, warm"), ("cedar", "Cedar", "natural, deep"), ("alloy", "Alloy", "neutral"),
    ("ash", "Ash", "soft"), ("ballad", "Ballad", "melodic"), ("coral", "Coral", "bright"), ("echo", "Echo", "calm"),
    ("fable", "Fable", "warm"), ("nova", "Nova", "bright"), ("onyx", "Onyx", "deep"), ("sage", "Sage", "gentle"),
    ("shimmer", "Shimmer", "light"), ("verse", "Verse", "expressive")]

DEFAULT_VOICE = {"deepgram": "aura-2-thalia-en", "gemini": "Kore", "mistral": "voice_478", "xai": "eve",
                 "rime": "astra", "minimax": "English_Graceful_Lady"}


def _rows(items) -> list:
    return [{"id": i, "name": n, "about": a} for i, n, a in items]


# Fetched lists, for a while: {(pid, model): (at, rows)}.
_fetched: dict = {}
FETCHED_FOR = 600.0


async def voices(pid: str, model: str = "") -> dict:
    """{voices: [{id, name, about}], typed: bool, error}: the voices a speaker has, or typed when its voices are its
    own names and cannot be listed."""
    from app.voice import voices as call_voices
    static = {
        "deepgram": DEEPGRAM_VOICES, "mistral": MISTRAL_VOICES, "xai": XAI_VOICES, "rime": RIME_VOICES,
        "minimax": MINIMAX_VOICES, "openai": OPENAI_VOICES,
        "gemini": [(v, v, a) for v, a in call_voices.GEMINI_VOICES],
        "groq": [(v, v.capitalize(), a) for v, a in call_voices.ORPHEUS_VOICES],
    }
    if pid in static:
        rows = _rows(static[pid])
        # The one it speaks in when none is picked goes first, so the tab can show it as the one in use.
        rows.sort(key=lambda r: r["id"] != DEFAULT_VOICE.get(pid))
        return {"voices": rows, "typed": False, "error": ""}
    if pid == "local":
        from app.voice import onboard
        if onboard.is_builtin(model):
            return {"voices": onboard.voices(model), "typed": False, "error": ""}
        return {"voices": [], "typed": True, "error": ""}
    if pid not in ("cartesia", "fish", "elevenlabs"):
        return {"voices": [], "typed": True, "error": ""}
    hit = _fetched.get(pid)
    if hit and time.time() - hit[0] < FETCHED_FOR:
        return {"voices": hit[1], "typed": False, "error": ""}
    try:
        rows = await _fetch_voices(pid)
    except Exception as e:
        return {"voices": [], "typed": True, "error": str(e)[:200]}
    _fetched[pid] = (time.time(), rows)
    return {"voices": rows, "typed": False, "error": ""}


async def _fetch_voices(pid: str) -> list:
    if pid == "cartesia":
        r = await _ask(pid, "", "GET", f"{URLS[pid]}/voices", params={"limit": 100}, count=False)
        out = []
        for v in (r.json() or {}).get("data") or []:
            about = ", ".join(x for x in (str(v.get("gender") or "").replace("masculine", "man").replace("feminine", "woman"),
                                          str(v.get("description") or "")[:60]) if x and x != "None")
            out.append({"id": str(v.get("id") or ""), "name": str(v.get("name") or ""), "about": about})
        return [v for v in out if v["id"]]
    if pid == "fish":
        # Your own voices first, then the ones most used on Fish Audio.
        out, seen = [], set()
        for params in ({"self": "true", "page_size": 50}, {"page_size": 40, "sort_by": "task_count"}):
            r = await _ask(pid, "", "GET", f"{URLS[pid]}/model", params=params, count=False)
            for v in (r.json() or {}).get("items") or []:
                vid = str(v.get("_id") or "")
                if vid and vid not in seen:
                    seen.add(vid)
                    out.append({"id": vid, "name": str(v.get("title") or vid)[:40],
                                "about": "yours" if params.get("self") else ", ".join(v.get("languages") or [])[:40]})
        return out
    from app.utils import providers
    from app.voice.speak import elevenlabs_voices
    return await elevenlabs_voices(providers.key_now("elevenlabs"))


async def _first_voice(pid: str) -> str:
    rows = (await voices(pid)).get("voices") or []
    if not rows:
        raise SpeechError(f"Pick a {_name(pid)} voice first.")
    return rows[0]["id"]
