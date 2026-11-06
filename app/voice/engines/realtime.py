"""A voice model that hears and speaks for itself: Gemini Live, OpenAI Realtime, or Grok's voice agent.

The most human way to do a call: the model hears their tone rather than a transcript of it, decides for itself when
they have finished, can be talked over, and answers in about half a second. The persona's instructions, its memory
of this person and the speaking style go in once, as the session's instructions; after that it is audio both ways.

Both are spoken to over a plain WebSocket, so neither needs an SDK of its own: the messages are JSON, the audio in
them base64 16-bit PCM. Gemini takes 16 kHz and answers at 24 kHz; OpenAI takes and answers 24 kHz.
"""
import asyncio
import base64
import json

from app.voice.engines.base import Engine

GEMINI_URL = ("wss://generativelanguage.googleapis.com/ws/"
              "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent")
GEMINI_MODEL = "gemini-3.8-live"
OPENAI_URL = "wss://api.openai.com/v1/realtime"
OPENAI_MODEL = "gpt-realtime"
OPENAI_HEARING = "gpt-4o-mini-transcribe"
XAI_URL = "wss://api.x.ai/v1/realtime"
XAI_MODEL = "grok-voice-latest"


class RealtimeError(RuntimeError):
    pass


class Realtime(Engine):
    """One WebSocket, read on a task of its own. Subclasses say what the messages look like."""
    out_rate = 24000
    ready_timeout = 15.0

    provider = ""       # whose keys it uses, in app/utils/providers.py

    def __init__(self, *, key: str, model: str = "", connect=None, **kw):
        super().__init__(**kw)
        self.key = key
        self.model = model
        self._connect = connect                   # for the tests: a stand-in for websockets' connect
        self._ws = None
        self._reader = None
        self._ready = asyncio.Event()
        self._heard = []                          # their words, arriving in pieces
        self._said = []                           # its words, arriving in pieces
        self._speaking = False

    # ── For subclasses ──────────────────────────────────────────────────────────

    def url(self) -> str:
        raise NotImplementedError

    def headers(self) -> dict:
        return {}

    def setup(self) -> list:
        """What to send as soon as the socket opens."""
        return []

    def audio_message(self, b64: str) -> list:
        raise NotImplementedError

    def cue_messages(self, direction: str) -> list:
        raise NotImplementedError

    def handle(self, msg: dict) -> None:
        raise NotImplementedError

    # ── The connection ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self.key:
            raise RealtimeError(f"{self.name} needs a key")
        if self._connect is None:
            from websockets.asyncio.client import connect
            self._connect = connect
        try:
            self._ws = await self._connect(self.url(), additional_headers=self.headers() or None,
                                           max_size=None, open_timeout=self.ready_timeout)
        except Exception as e:
            raise RealtimeError(f"could not reach {self.name}: {e}") from e
        for m in self.setup():
            await self._send(m)
        self._reader = asyncio.ensure_future(self._read())
        try:
            await asyncio.wait_for(self._ready.wait(), self.ready_timeout)
        except asyncio.TimeoutError:
            await self.close()
            raise RealtimeError(f"{self.name} did not answer the setup") from None
        self.events.state("listening")

    async def _send(self, msg: dict) -> None:
        if self._ws is not None and not self.closed:
            await self._ws.send(json.dumps(msg))

    async def _read(self) -> None:
        reason = ""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                except Exception:
                    continue
                try:
                    self.handle(msg)
                except Exception as e:
                    self.log(f"{self.name}: could not read a message: {type(e).__name__}: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            reason = str(e)
        if not self.closed:
            # The far end hung up on us: a bad key, a model that does not exist, the session's time running out.
            close = getattr(self._ws, "close_reason", None) or getattr(self._ws, "close_code", None) or reason
            self.events.error(f"{self.name} closed the connection" + (f": {close}" if close else ""))

    async def feed(self, pcm: bytes) -> None:
        if self._ready.is_set() and pcm:
            await self._send_all(self.audio_message(base64.b64encode(pcm).decode("ascii")))

    async def cue(self, direction: str) -> None:
        await self._ready.wait()
        await self._send_all(self.cue_messages(direction))

    async def _send_all(self, msgs: list) -> None:
        for m in msgs:
            await self._send(m)

    async def close(self) -> None:
        await super().close()
        if self._reader:
            self._reader.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ── Shared bookkeeping ──────────────────────────────────────────────────────

    def _play(self, b64: str) -> None:
        if not self._speaking:
            self._speaking = True
            self._flush_heard()
            self.events.state("speaking")
        self.events.audio(base64.b64decode(b64), self.out_rate)

    def _flush_heard(self) -> None:
        text = "".join(self._heard).strip()
        self._heard = []
        if text:
            self.events.heard(text)

    def _flush_said(self) -> None:
        text = "".join(self._said).strip()
        self._said = []
        if text:
            self.events.said(text)

    def _turn_over(self) -> None:
        self._speaking = False
        self._flush_said()
        self.events.state("listening")


class GeminiLive(Realtime):
    name = "Gemini"
    provider = "gemini"
    in_rate = 16000

    def url(self) -> str:
        return f"{GEMINI_URL}?key={self.key}"

    def setup(self) -> list:
        setup = {
            "model": f"models/{self.model or GEMINI_MODEL}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice or "Kore"}}},
            },
            "systemInstruction": {"parts": [{"text": self.instructions}]},
            # Both sides as words too: for the live transcript, and for remembering the call afterwards.
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
        return [{"setup": setup}]

    def audio_message(self, b64: str) -> list:
        return [{"realtimeInput": {"audio": {"data": b64, "mimeType": f"audio/pcm;rate={self.in_rate}"}}}]

    def cue_messages(self, direction: str) -> list:
        return [{"realtimeInput": {"text": direction}}]

    def handle(self, msg: dict) -> None:
        if "setupComplete" in msg:
            self._ready.set()
            return
        sc = msg.get("serverContent") or {}
        if (sc.get("inputTranscription") or {}).get("text"):
            self._heard.append(sc["inputTranscription"]["text"])
        if (sc.get("outputTranscription") or {}).get("text"):
            self._said.append(sc["outputTranscription"]["text"])
        for part in (sc.get("modelTurn") or {}).get("parts") or []:
            data = (part.get("inlineData") or {}).get("data")
            if data:
                self._play(data)
        if sc.get("interrupted"):
            # Their voice cut in: whatever was still to be said is dropped, on both ends.
            self.events.interrupted()
            self._turn_over()
        elif sc.get("turnComplete"):
            self._flush_heard()
            self._turn_over()
        if "goAway" in msg:
            self.log("Gemini says the session ends soon")


class OpenAIRealtime(Realtime):
    name = "OpenAI"
    provider = "openai"
    in_rate = 24000

    def url(self) -> str:
        return f"{OPENAI_URL}?model={self.model or OPENAI_MODEL}"

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}

    def setup(self) -> list:
        return [{"type": "session.update", "session": {
            "type": "realtime",
            "instructions": self.instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": self.in_rate},
                    "transcription": {"model": OPENAI_HEARING},
                    # Its own judgement of when they have finished a thought, not just a pause length.
                    "turn_detection": {"type": "semantic_vad", "create_response": True, "interrupt_response": True},
                },
                "output": {"format": {"type": "audio/pcm", "rate": self.out_rate}, "voice": self.voice or "marin"},
            },
        }}]

    def audio_message(self, b64: str) -> list:
        return [{"type": "input_audio_buffer.append", "audio": b64}]

    def cue_messages(self, direction: str) -> list:
        return [{"type": "conversation.item.create",
                 "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": direction}]}},
                {"type": "response.create"}]

    def handle(self, msg: dict) -> None:
        kind = str(msg.get("type") or "")
        if kind == "session.updated":
            # Ready once it has taken the instructions and the voice, not merely connected.
            self._ready.set()
        elif kind in ("response.output_audio.delta", "response.audio.delta"):
            if msg.get("delta"):
                self._play(msg["delta"])
        elif kind in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
            self._said.append(str(msg.get("delta") or ""))
        elif kind == "conversation.item.input_audio_transcription.completed":
            text = str(msg.get("transcript") or "").strip()
            if text:
                self.events.heard(text)
        elif kind == "input_audio_buffer.speech_started":
            if self._speaking:
                self.events.interrupted()
                self._turn_over()
        elif kind == "response.created":
            self.events.state("thinking")
        elif kind == "response.done":
            self._turn_over()
        elif kind == "error":
            err = msg.get("error") or {}
            code = str(err.get("code") or "")
            # Cancelling a reply that already finished is not a problem worth ending a call over.
            if code in ("response_cancel_not_active", "conversation_already_has_active_response"):
                return
            self.events.error(f"{self.name}: {err.get('message') or code or 'error'}")


class XaiRealtime(OpenAIRealtime):
    """Grok's voice agent: OpenAI's protocol, nearly. Its session takes the voice and the turn detection where its
    documentation puts them, it hears through grok-transcribe, and what it heard comes as a running transcript that
    grows ("...updated") rather than in one piece at the end; the last of it is what they said."""
    name = "Grok"
    provider = "xai"
    in_rate = 24000

    def __init__(self, **kw):
        super().__init__(**kw)
        self._heard_so_far = ""

    def url(self) -> str:
        return f"{XAI_URL}?model={self.model or XAI_MODEL}"

    def setup(self) -> list:
        return [{"type": "session.update", "session": {
            "instructions": self.instructions,
            "voice": (self.voice or "eve").lower(),
            "turn_detection": {"type": "server_vad"},
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": self.in_rate},
                          "transcription": {"model": "grok-transcribe"}},
                "output": {"format": {"type": "audio/pcm", "rate": self.out_rate}},
            },
        }}]

    def handle(self, msg: dict) -> None:
        kind = str(msg.get("type") or "")
        if kind == "conversation.item.input_audio_transcription.updated":
            self._heard_so_far = str(msg.get("transcript") or msg.get("text") or self._heard_so_far)
            return
        if kind == "conversation.item.input_audio_transcription.completed":
            self._heard_so_far = ""
        elif kind == "response.created" and self._heard_so_far.strip():
            # It is answering, so they have finished: what it heard so far is what they said.
            self.events.heard(self._heard_so_far.strip())
            self._heard_so_far = ""
        super().handle(msg)


# Whose voice model, by provider.
ENGINES = {"gemini": GeminiLive, "openai": OpenAIRealtime, "xai": XaiRealtime}
