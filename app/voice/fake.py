"""A call with nobody on the other end but a script.

What WHATSAPP_FAKE=1 is to WhatsApp: the whole call - the session, the engine, the turn-taking, the hang-up and the
write-up - run with nothing reaching any platform. Their side is a list of steps: a chunk of PCM (them talking), a
number (that many seconds of silence), or a callable (something to check or do at that point). What it says comes
out of `session.playout` like on any platform, and is kept.
"""
import asyncio

from app.voice.audio import BRAIN_RATE, silence
from app.voice.session import Adapter

FRAME_MS = 20


class FakeCall(Adapter):
    platform = "panel"
    counts = False                      # not a real call: never counted against the day's calls
    in_rate = BRAIN_RATE
    out_rate = BRAIN_RATE

    def __init__(self, script: list, *, speed: float = 0.0, keep_open: bool = False):
        """`speed` 0 hands the frames over as fast as the engine takes them; 1.0 is real time. `keep_open` leaves
        the line open after the script, so the session has to end the call itself."""
        self.script = script
        self.speed = speed
        self.keep_open = keep_open
        self.session = None
        self.out = []                   # everything it played, frame by frame, from the session's playout
        self.records = []
        self.hung_up = False

    def _frames_of(self, pcm: bytes):
        size = 2 * self.in_rate * FRAME_MS // 1000
        for i in range(0, len(pcm), size):
            yield pcm[i:i + size].ljust(size, b"\0")

    async def _tick(self) -> None:
        if self.session is not None:
            self.out.append(self.session.playout.read())
        await asyncio.sleep(FRAME_MS / 1000 * self.speed if self.speed else 0)

    async def frames(self):
        for step in self.script:
            if callable(step):
                result = step()
                if asyncio.iscoroutine(result):
                    await result
                continue
            pcm = silence(int(float(step) * 1000), self.in_rate) if isinstance(step, (int, float)) else step
            for frame in self._frames_of(pcm):
                if self.hung_up:
                    return
                await self._tick()
                yield frame
        while self.keep_open and not self.hung_up:
            await self._tick()
            yield silence(FRAME_MS, self.in_rate)

    async def hang_up(self) -> None:
        self.hung_up = True

    def write_up(self, record: dict) -> None:
        self.records.append(record)
