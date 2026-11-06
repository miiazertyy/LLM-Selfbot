"""The voices there are to pick from, and hearing one before picking it.

Realtime voices belong to the model (Gemini's thirty, OpenAI's ten, Grok's own); on its own brain the voice is
whoever speaks for the call: the voice messages' speaker, or one picked for calls from any provider that speaks
(app/voice/speech.py). A preview is the voice saying one line the way it would on a call - for a realtime voice that
means a few seconds of a real session, since nothing else makes that exact sound.
"""
import asyncio
import time

from app.voice.audio import wav_bytes
from app.voice.speech import XAI_VOICES

SAMPLE = "Hey, it's me. How's your day going?"

GEMINI_VOICES = [
    ("Zephyr", "bright"), ("Puck", "upbeat"), ("Charon", "informative"), ("Kore", "firm"), ("Fenrir", "excitable"),
    ("Leda", "youthful"), ("Orus", "firm"), ("Aoede", "breezy"), ("Callirrhoe", "easy-going"),
    ("Autonoe", "bright"), ("Enceladus", "breathy"), ("Iapetus", "clear"), ("Umbriel", "easy-going"),
    ("Algieba", "smooth"), ("Despina", "smooth"), ("Erinome", "clear"), ("Algenib", "gravelly"),
    ("Rasalgethi", "informative"), ("Laomedeia", "upbeat"), ("Achernar", "soft"), ("Alnilam", "firm"),
    ("Schedar", "even"), ("Gacrux", "mature"), ("Pulcherrima", "forward"), ("Achird", "friendly"),
    ("Zubenelgenubi", "casual"), ("Vindemiatrix", "gentle"), ("Sadachbia", "lively"),
    ("Sadaltager", "knowledgeable"), ("Sulafat", "warm"),
]
OPENAI_VOICES = [
    ("marin", "natural, warm"), ("cedar", "natural, deep"), ("alloy", "neutral"), ("ash", "soft"),
    ("ballad", "melodic"), ("coral", "bright"), ("echo", "calm"), ("sage", "gentle"), ("shimmer", "light"),
    ("verse", "expressive"),
]
ORPHEUS_VOICES = [
    ("autumn", "warm, female"), ("diana", "bright, female"), ("hannah", "soft, female"),
    ("austin", "relaxed, male"), ("daniel", "deep, male"), ("troy", "upbeat, male"),
]


def _rows(pairs):
    return [{"id": v, "name": v.capitalize() if v.islower() else v, "about": about} for v, about in pairs]


# Each voice model's voices.
REALTIME_VOICES = {"gemini": GEMINI_VOICES, "openai": OPENAI_VOICES, "xai": [(v, about) for v, _n, about in XAI_VOICES]}


async def catalogue(cfg: dict = None) -> dict:
    """Everything the Calls tab offers: each voice model's voices and whether it has its key, what hears, thinks and
    speaks on its own brain (as picked for calls, and as voice messages and replies have it), and this computer's
    own voice. A speaker's voices are asked for separately, once it is picked (/api/calls/speaker-voices)."""
    from app.utils import providers
    from app.voice import onboard
    from app.voice.session import calls_cfg
    calls = calls_cfg(cfg)
    return {
        "chosen": {k: calls.get(k) for k in ("engine", "realtime_provider", "realtime_voice", "speaker", "voice",
                                             "hear", "think", "speak")},
        "realtime": {pid: {"voices": _rows(pairs), "has_key": bool(providers.keys_for(pid))}
                     for pid, pairs in REALTIME_VOICES.items()},
        "legs": legs(cfg),
        "defaults": legs(cfg, picked=False),
        "local": onboard.status(),
    }


class _Collect:
    """Events that keep what the voice says, and notice when it has finished saying it."""

    def __init__(self):
        self.chunks = []
        self.rate = 24000
        self.done = asyncio.Event()
        self.spoke = False
        self.problem = ""

    def audio(self, pcm, rate):
        self.spoke = True
        self.rate = rate
        self.chunks.append(pcm)

    def heard(self, text):
        pass

    def said(self, text):
        pass

    def interrupted(self):
        pass

    def state(self, name):
        if name == "listening" and self.spoke:
            self.done.set()

    def error(self, message):
        self.problem = message
        self.done.set()


async def preview(engine: str, provider: str, voice: str, text: str = SAMPLE, model: str = "") -> bytes:
    """A WAV of this voice saying one line."""
    if engine == "realtime":
        from app.utils import providers
        from app.voice.engines.realtime import ENGINES
        keys = providers.keys_for(provider)
        name = _name_of(provider)
        if not keys:
            raise RuntimeError(f"Hearing a {name} voice needs a {name} key.")
        events = _Collect()
        cls = ENGINES.get(provider, ENGINES["gemini"])
        eng = cls(key=keys[0], instructions="You read lines out loud, exactly as written, in a natural warm voice.",
                  voice=voice, events=events)
        try:
            await eng.start()
            await eng.cue(f"Say exactly this, nothing else: {text}")
            await asyncio.wait_for(events.done.wait(), 20)
        finally:
            await eng.close()
        if events.problem and not events.chunks:
            raise RuntimeError(events.problem)
        return wav_bytes(b"".join(events.chunks), events.rate)
    if provider in ("", "same"):
        # The voice messages' speaker, with the voice picked for calls if there is one.
        from app.voice.speak import Speaker
        pcm, rate = await Speaker.for_call(calls={"voice": voice}).say(text)
    else:
        # Straight to the one picked, so a voice that cannot be heard says why rather than another speaking for it.
        from app.voice import speech
        pcm, rate = await speech.say(provider, model, voice, text)
    return wav_bytes(pcm, rate)


def _name_of(pid: str) -> str:
    from app.utils import providers
    return (providers.BY_ID.get(pid) or {}).get("name") or (pid.title() if pid else "")


def legs(cfg: dict = None, picked: bool = True) -> dict:
    """What a call on its own brain really uses, leg by leg: who hears the other person, who thinks of the reply,
    and who says it out loud.

    Each is the app's own job (Settings > Models: hearing and speaking as voice messages have them, thinking as
    replies do) unless the call picked its own (bot.calls.hear, think, speak), which then goes first. picked=False
    leaves the call's picks out: what each leg goes back to when its pick is taken away.
    """
    from app.utils import providers
    from app.utils.helpers import load_config
    from app.voice import onboard
    from app.voice.session import calls_cfg
    from app.voice.speech import entry_of
    cfg = cfg if cfg is not None else load_config()
    calls = calls_cfg(cfg)

    def leg(entry: dict, own: bool) -> dict:
        pid, model = entry.get("provider") or "", entry.get("model") or ""
        return {"provider": pid, "name": _name_of(pid), "model": model, "voice": entry.get("voice") or "",
                "local": pid == "local", "builtin": onboard.is_builtin(model), "own": own}

    hear, think, speak = (entry_of(calls.get(k)) if picked else None for k in ("hear", "think", "speak"))
    if picked and not speak and str(calls.get("speaker") or "same") == "elevenlabs":
        from app.voice.speak import ELEVENLABS_MODEL
        speak = {"provider": "elevenlabs", "model": str(calls.get("elevenlabs_model") or ELEVENLABS_MODEL)}
    out = {
        "hear": leg(hear or providers.job(cfg, "stt"), bool(hear)),
        "think": leg(think or (providers.reply_chain(cfg) or [{}])[0], bool(think)),
        "speak": leg(speak or providers.job(cfg, "tts"), bool(speak)),
    }
    out["all_local"] = all(out[k]["local"] for k in ("hear", "think", "speak"))
    return out


# A turn is hearing them, thinking, and the first words out. Under this it lands inside a normal pause; over it,
# they have started wondering whether the line dropped.
TURN_OK_MS = 2500


async def speed(cfg: dict = None) -> dict:
    """How long one turn takes on its own brain, leg by leg: hearing a sentence, thinking of a reply, saying it.

    What decides whether a call is worth having, above all on this computer. Each leg is measured twice and the
    second one counts, because the first warms a local model up. The audio it hears is its own voice saying a line,
    so hearing is timed on a real sentence rather than on silence, which every model answers unrealistically fast.
    """
    from app.utils import ai
    from app.voice.speak import Speaker
    out = {"legs": {}, "ms": 0, "ok": False, "reason": ""}

    async def timed(job, twice=True):
        if twice:
            await job()
        started = time.perf_counter()
        got = await job()
        return int((time.perf_counter() - started) * 1000), got

    from app.voice.session import call_legs, calls_cfg
    hear, think = call_legs(calls_cfg(cfg))
    said = b""
    rate = 24000
    speaker = Speaker.for_call(cfg)
    try:
        ms, (said, rate) = await timed(lambda: speaker.say("Yeah, that sounds good to me."))
        # The one picked for calls could not, and the voice messages' speaker said it instead: timed, but not it.
        failed = getattr(speaker, "failed", "")
        out["legs"]["speak"] = {"ms": ms, "reason": failed, "failed": True} if failed else {"ms": ms, "reason": ""}
    except Exception as e:
        out["legs"]["speak"] = {"ms": 0, "reason": str(e)[:200], "failed": True}

    audio = wav_bytes(said, rate) if said else wav_bytes(b"\0" * (2 * 16000), 16000)
    try:
        ms, _ = await timed(lambda: hear(audio, "call.wav"))
        out["legs"]["hear"] = {"ms": ms, "reason": "" if said else "Timed on silence: its voice could not be heard."}
    except Exception as e:
        out["legs"]["hear"] = {"ms": 0, "reason": str(e)[:200], "failed": True}

    try:
        ms, _ = await timed(lambda: think(
            "say hey back, two words", "You are on a phone call. Answer in a few words, as you would out loud."))
        out["legs"]["think"] = {"ms": ms, "reason": ""}
    except Exception as e:
        out["legs"]["think"] = {"ms": 0, "reason": str(e)[:200], "failed": True}

    broke = [k for k in ("hear", "think", "speak") if out["legs"][k].get("failed")]
    out["ms"] = sum(out["legs"][k]["ms"] for k in ("hear", "think", "speak"))
    if broke:
        out["reason"] = next(out["legs"][k]["reason"] for k in broke)
    elif out["ms"] > TURN_OK_MS:
        out["reason"] = "Slow for a call: they will hear a long gap before it answers."
    out["ok"] = not broke and out["ms"] <= TURN_OK_MS
    return out
