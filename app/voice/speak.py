"""A voice saying one line - the free path's mouth.

A call says a line every few seconds, so this is not tts.py's voice note (which turns a whole reply into a file):
one sentence in, PCM out, as fast as the voice allows, and rotating Groq keys when one runs out of allowance mid-call
rather than going quiet.

Who speaks is the same speaking chain voice messages use (Settings > Models, then Groq's Orpheus), unless the call
picks a speaker of its own: any provider that speaks (app/voice/speech.py), this computer's own voice included. A
voice picked for calls wins over the voice messages'.
"""
import asyncio
import time

from app.voice.audio import read_wav

ELEVENLABS_URL = "https://api.elevenlabs.io/v1"
# The fastest ElevenLabs model, the one meant for talking back and forth.
ELEVENLABS_MODEL = "eleven_flash_v2_5"


class SpeakError(RuntimeError):
    pass


class Speaker:
    """One voice for one call. `say()` returns (pcm, rate): mono 16-bit PCM and its sample rate."""

    def __init__(self, *, kind: str = "chain", voice: str = "", model: str = "", tones: str = "",
                 elevenlabs_key: str = "", provider: str = ""):
        self.kind = kind                    # "chain" (the speaking chain), "provider" (picked for calls), "elevenlabs"
        self.provider = provider
        self.failed = ""                    # why the picked speaker could not say the last line, if it could not
        self.voice = voice
        self.model = model
        self.tones = tones
        self._el_key = elevenlabs_key
        self._groq = []                     # one client per Groq key, made as they are needed
        self._groq_at = 0
        self.last_ms = 0                    # how long the last line took, for the panel's speed check

    @classmethod
    def for_call(cls, cfg: dict = None, calls: dict = None) -> "Speaker":
        """The voice a call's free path speaks with. `calls` wins over what is saved: Try a call speaks with what
        is on screen, saved or not."""
        from app.utils.helpers import load_config
        cfg = cfg if cfg is not None else load_config()
        bot = (cfg or {}).get("bot") or {}
        calls = calls if calls is not None else (bot.get("calls") or {})
        voice = str(calls.get("voice") or "").strip()
        tones = " ".join((bot.get("tts") or {}).get("tones") or ["[casual]", "[warm]"])
        from app.voice.speech import entry_of
        speak = entry_of(calls.get("speak"))
        if speak:
            return cls(kind="provider", provider=speak["provider"], model=speak["model"], voice=voice, tones=tones)
        if str(calls.get("speaker") or "same") == "elevenlabs":
            # Picked before a call could have any speaker of its own, by the switch there was then.
            return cls(kind="provider", provider="elevenlabs", voice=voice,
                       model=str(calls.get("elevenlabs_model") or ELEVENLABS_MODEL))
        return cls(kind="chain", voice=voice, tones=tones)

    async def say(self, text: str) -> tuple:
        from app.utils import usage
        token = usage.JOB.set("tts")
        started = time.monotonic()
        try:
            if self.kind == "provider":
                out = await self._provider(text)
            elif self.kind == "elevenlabs":
                out = await self._elevenlabs(text)
            else:
                out = await self._chain(text)
        finally:
            usage.JOB.reset(token)
        self.last_ms = int((time.monotonic() - started) * 1000)
        return out

    async def _provider(self, text: str) -> tuple:
        """The speaker picked for calls. Should it fail, the voice messages' speakers say the line instead, in their
        own voices: a call whose voice changes is better than one that goes quiet."""
        from app.voice import speech
        line = f"{self.tones} {text}".strip() if self.tones and "orpheus" in self.model else text
        try:
            out = await speech.say(self.provider, self.model, self.voice, line)
            self.failed = ""
            return out
        except Exception as e:
            self.failed = str(e)[:200] or type(e).__name__
            return await Speaker(kind="chain", tones=self.tones)._chain(text)

    # ── The speaking chain: whoever speaks voice messages ──────────────────────

    async def _chain(self, text: str) -> tuple:
        from app.utils import ai, tts
        from app.voice import speech
        problems = []
        for i, target in enumerate(ai.tts_targets()):
            try:
                if speech.native("tts", target["provider"], target["model"]):
                    voice = (self.voice if i == 0 and self.voice else "") or target.get("voice") or ""
                    return await speech.say(target["provider"], target["model"], voice, text)
                client = tts._client_for(target)
                # A voice picked for calls goes to the first speaker; the rest keep their own.
                voice = (self.voice if i == 0 and self.voice else "") or target.get("voice") or "alloy"
                res = await client.audio.speech.create(model=target["model"], voice=voice, input=text,
                                                       response_format="wav")
                pcm, rate, channels = read_wav(await res.read())
                return _mono(pcm, channels), rate
            except Exception as e:
                ai.note_key_trouble(target.get("provider"), target.get("api_key"), e)
                problems.append(f"{target.get('provider')}: {type(e).__name__}")
        try:
            return await self._groq_say(text)
        except Exception as e:
            problems.append(f"groq: {e}")
        raise SpeakError("No voice could say it (" + "; ".join(problems) + ")")

    async def _groq_say(self, text: str) -> tuple:
        from app.utils import providers, tts
        from app.utils.helpers import load_config
        keys = providers.keys_for("groq")
        if not keys:
            raise SpeakError("no Groq key")
        if not self._groq:
            from groq import AsyncGroq
            from app.utils import usage
            self._groq = [AsyncGroq(api_key=k, http_client=usage.http_client("groq", sdk="groq")) for k in keys]
        bot = (load_config() or {}).get("bot") or {}
        model = self.model or tts._tts_model()
        voice = self.voice or (bot.get("tts") or {}).get("voice") or "autumn"
        # Orpheus reads its bracketed tones as direction; nothing else would know what they are.
        line = f"{self.tones} {text}".strip() if self.tones and "orpheus" in model else text
        last = None
        for _ in range(len(self._groq)):
            client = self._groq[self._groq_at % len(self._groq)]
            try:
                res = await client.audio.speech.create(model=model, voice=voice, input=line, response_format="wav")
                pcm, rate, channels = read_wav(await res.read())
                return _mono(pcm, channels), rate
            except Exception as e:
                last = e
                said = str(e).lower()
                if "429" in said or "rate" in said or "limit" in said:
                    # Out of allowance on this key: the next one, rather than going quiet mid-call.
                    self._groq_at += 1
                    continue
                raise
        raise SpeakError(f"every Groq key is out of speaking allowance ({last})")

    # ── ElevenLabs ──────────────────────────────────────────────────────────────

    async def _elevenlabs(self, text: str) -> tuple:
        if not self._el_key:
            raise SpeakError("ElevenLabs needs a key: add one under Settings > Models > Providers.")
        if not self.voice:
            raise SpeakError("Pick an ElevenLabs voice for calls first.")
        import httpx
        from app.utils import providers
        url = f"{ELEVENLABS_URL}/text-to-speech/{self.voice}?output_format=pcm_24000"
        problem = ""
        # The key it was given, then the account's others while they run out or are refused.
        for key in [self._el_key] + [k for k in providers.key_order("elevenlabs") if k != self._el_key]:
            async with httpx.AsyncClient(timeout=30.0) as http:
                r = await http.post(url, headers={"xi-api-key": key, "accept": "audio/pcm"},
                                    json={"text": text, "model_id": self.model or ELEVENLABS_MODEL})
            if r.status_code == 200:
                self._el_key = key
                return r.content[: len(r.content) - (len(r.content) % 2)], 24000
            problem = f"ElevenLabs said {r.status_code}: {r.text[:160]}"
            rest = providers.key_at_fault(r.status_code)
            if not rest:
                break
            providers.rest_key("elevenlabs", key, rest)
        raise SpeakError(problem)


def _mono(pcm: bytes, channels: int) -> bytes:
    if channels <= 1:
        return pcm
    from app.voice.audio import to_mono
    return to_mono(pcm, channels)


async def elevenlabs_voices(key: str) -> list:
    """The voices in an ElevenLabs account: its own, ones designed from a description on their site, and the
    library ones added to it. [{"id", "name", "about"}]."""
    import httpx
    async with httpx.AsyncClient(timeout=20.0) as http:
        r = await http.get(f"{ELEVENLABS_URL}/voices", headers={"xi-api-key": key})
    if r.status_code != 200:
        raise SpeakError(f"ElevenLabs said {r.status_code}: {r.text[:160]}")
    out = []
    for v in (r.json() or {}).get("voices") or []:
        labels = v.get("labels") or {}
        about = ", ".join(str(labels[k]) for k in ("gender", "age", "accent", "description") if labels.get(k))
        out.append({"id": str(v.get("voice_id") or ""), "name": str(v.get("name") or ""), "about": about})
    return [v for v in out if v["id"]]


async def gather_lines(speaker: Speaker, lines: list) -> list:
    """Several lines at once, in order - for things said often enough to keep ready (the fillers)."""
    results = await asyncio.gather(*(speaker.say(t) for t in lines), return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]
