"""Its own brain, out loud: hear, think, speak.

The persona that texts them, on the phone. Their audio is cut into turns by the voice detector (vad.py); each turn
is heard by whichever model hears voice messages, answered by the persona's own reply models with the call's
instructions, and said a sentence at a time, so the first sentence plays while the rest are still being made.

What keeps it from feeling like a walkie-talkie:
  - a turn is not over at the first pause: it waits ~0.65 s of quiet, and two quick turns in a row are heard as one
  - talked over for more than a moment, it stops mid-sentence and listens
  - when a reply is slow it sometimes makes a small thinking sound, the way people do, never twice running
"""
import asyncio
import random
import re
import time
from collections import deque

from app.voice.audio import BRAIN_RATE, wav_bytes
from app.voice.engines.base import Engine
from app.voice.persona import sentences, speakable
from app.voice.vad import Vad

FRAME = 2 * BRAIN_RATE * 20 // 1000        # one 20 ms frame, in bytes
SHORTEST_TURN_S = 0.35                       # anything shorter is a click, a cough, a breath
BARGE_IN_FRAMES = 12                         # ~240 ms of them talking over it before it stops
FILLER_AFTER_S = 0.9                         # a reply still not ready this long after they stopped...
FILLER_CHANCE = 0.4                          # ...gets a thinking sound this often

# What Whisper hears in near-silence: subtitle credits and sign-offs it learnt from video. Said by nobody.
def _plain(text: str) -> str:
    return re.sub(r"[^\w\s]", "", str(text or "").lower()).strip()


_PHANTOMS = {_plain(t) for t in (
    "thank you", "thanks for watching", "thank you for watching", "thank you so much for watching",
    "subtitles by the amara.org community", "sous-titres réalisés par la communauté d'amara.org",
    "sous-titrage st' 501", "you", "merci", "merci d'avoir regardé")}


def phantom(text: str, seconds: float) -> bool:
    said = _plain(text)
    return not said or (seconds < 2.0 and said in _PHANTOMS)


class OwnBrain(Engine):
    name = "own"
    in_rate = BRAIN_RATE

    def __init__(self, *, instructions, voice="", events=None, log=None, speaker=None, hear=None, think=None,
                 vad=None, fillers=True, history=None):
        super().__init__(instructions=instructions, voice=voice, events=events, log=log)
        if speaker is None:
            from app.voice.speak import Speaker
            speaker = Speaker.for_call()
            if voice:
                speaker.voice = voice
        if hear is None or think is None:
            from app.utils import ai
            hear = hear or ai.transcribe_voice
            think = think or ai.generate_response
        self.speaker = speaker
        self.hear = hear
        self.think = think
        self.vad = vad or Vad()
        self.history = history if history is not None else []
        self.fillers_on = fillers
        self._carry = b""
        self._preroll = deque(maxlen=15)     # 300 ms before they started, so the first syllable is not lost
        self._utterance = []
        self._talked = 0                     # frames they have been talking for, this time
        self._barged = False
        self._turn = None                    # the answer being worked out or said, as a task
        self._turn_audio = b""               # what that answer is answering
        self._turn_heard = False             # whether those words are in the conversation yet
        self._phase = "listening"
        self._fillers = []
        self._last_filler = False

    async def start(self) -> None:
        if self.fillers_on:
            # Made once, so a thinking sound costs nothing when it is wanted. Sounds, not words: they work in any
            # language the call is in.
            from app.voice.speak import gather_lines
            self._fillers = await gather_lines(self.speaker, ["Hmm...", "Mm."])
        self.events.state("listening")

    # ── Their audio ─────────────────────────────────────────────────────────────

    async def feed(self, pcm: bytes) -> None:
        data = self._carry + pcm
        cut = len(data) - (len(data) % FRAME)
        self._carry = data[cut:]
        for i in range(0, cut, FRAME):
            self._frame(data[i:i + FRAME])

    def _frame(self, frame: bytes) -> None:
        event = self.vad.push(frame)
        if event == "start":
            self._utterance = list(self._preroll)
            self._talked = 0
            self._barged = False
        if self.vad.speaking or event == "end":
            self._utterance.append(frame)
        else:
            self._preroll.append(frame)
        if self.vad.speaking:
            self._talked += 1
            # Talked over for more than a moment: it stops, as a person would. Not while it is still working out an
            # answer - them adding something then is one turn, heard together (below). The session knows whether
            # its voice is still playing, which can be long after the last sentence was handed over.
            if not self._barged and self._talked >= BARGE_IN_FRAMES and self._phase != "thinking":
                self._barged = True
                if self._phase == "speaking":
                    self._stop_turn(keep_audio=False)
                self.events.interrupted()
        if event == "end":
            utterance = b"".join(self._utterance)
            self._utterance = []
            if len(utterance) / (2 * BRAIN_RATE) < SHORTEST_TURN_S:
                return
            if self._turn and not self._turn.done() and self._phase == "thinking":
                # They added something before it answered: one turn. Words already heard stay in the conversation
                # and only the new ones are heard; audio not heard yet is heard together with the new.
                audio = utterance if self._turn_heard else self._turn_audio + bytes(2 * BRAIN_RATE // 5) + utterance
                self._stop_turn(keep_audio=True)
            else:
                audio = utterance
            self._turn_audio = audio
            self._turn_heard = False
            self._turn = asyncio.ensure_future(self._answer(audio))

    def _stop_turn(self, keep_audio: bool) -> None:
        if self._turn and not self._turn.done():
            self._turn.cancel()
        if not keep_audio:
            self._turn_audio = b""

    # ── Answering ───────────────────────────────────────────────────────────────

    def _set(self, phase: str) -> None:
        self._phase = phase
        self.events.state(phase)

    async def _answer(self, audio: bytes) -> None:
        self._set("thinking")
        filler = asyncio.ensure_future(self._maybe_filler()) if self._fillers else None
        said = []
        try:
            seconds = len(audio) / (2 * BRAIN_RATE)
            started = time.monotonic()
            text = (await self.hear(wav_bytes(audio, BRAIN_RATE), "call.wav") or "").strip()
            heard_ms = int((time.monotonic() - started) * 1000)
            if phantom(text, seconds):
                return
            self.events.heard(text)
            self.history.append({"role": "user", "content": text})
            self._turn_heard = True
            reply = speakable(await self.think(None, self.instructions, self.history[-24:]) or "")
            think_ms = int((time.monotonic() - started) * 1000) - heard_ms
            if not reply:
                return
            if filler:
                filler.cancel()
            await self._say(reply, said)
            self.log(f"turn: heard in {heard_ms} ms, thought in {think_ms} ms, first words after "
                     f"{int((time.monotonic() - started) * 1000)} ms")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log(f"a turn failed: {type(e).__name__}: {e}")
        finally:
            if filler:
                filler.cancel()
            if said:
                self.history.append({"role": "assistant", "content": " ".join(said)})
            if self._phase != "listening":
                self._set("listening")

    async def _say(self, reply: str, said: list) -> None:
        for line in sentences(reply):
            pcm, rate = await self.speaker.say(line)
            if self._phase != "speaking":
                self._set("speaking")
            self.events.audio(pcm, rate)
            self.events.said(line)
            said.append(line)

    async def _maybe_filler(self) -> None:
        await asyncio.sleep(FILLER_AFTER_S)
        if self._phase != "thinking" or self._last_filler or random.random() > FILLER_CHANCE:
            self._last_filler = False
            return
        self._last_filler = True
        pcm, rate = random.choice(self._fillers)
        self.events.audio(pcm, rate)

    async def cue(self, direction: str) -> None:
        """Say something on cue. Not kept as something they said: only its answer goes into the conversation."""
        self._stop_turn(keep_audio=False)
        self._turn = asyncio.ensure_future(self._cued(direction))

    async def _cued(self, direction: str) -> None:
        self._set("thinking")
        said = []
        try:
            reply = speakable(await self.think(
                None, self.instructions, self.history[-24:] + [{"role": "user", "content": direction}]) or "")
            if reply:
                await self._say(reply, said)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log(f"could not say it: {type(e).__name__}: {e}")
        finally:
            if said:
                self.history.append({"role": "assistant", "content": " ".join(said)})
            if self._phase != "listening":
                self._set("listening")

    async def close(self) -> None:
        self._stop_turn(keep_audio=False)
        await super().close()
