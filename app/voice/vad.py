"""Whether someone is talking, one 20 ms frame at a time.

An energy detector whose floor follows the line: it learns how loud silence is on this call (Discord's is digital
zero, a phone's is a hiss) and calls it speech only well above that. Hysteresis both ways - a start needs a run of
loud frames and an end a run of quiet ones - so a breath or a click is not a turn, and a pause to find a word is not
the end of one.

The realtime engines do their own turn detection on the server; this is for the free path, which has to decide for
itself when the other person has finished.
"""
from app.voice.audio import rms


class Vad:
    def __init__(self, *, start_ms: int = 100, end_ms: int = 650, ratio: float = 3.0, floor_min: float = 350.0,
                 frame_ms: int = 20):
        self.start_frames = max(1, start_ms // frame_ms)
        self.end_frames = max(1, end_ms // frame_ms)
        self.ratio = ratio
        self.floor_min = floor_min
        self.floor = floor_min / ratio      # what silence sounds like here, learnt as it goes
        self.speaking = False
        self.level = 0.0
        self._loud = 0
        self._quiet = 0

    @property
    def threshold(self) -> float:
        return max(self.floor * self.ratio, self.floor_min)

    def push(self, frame: bytes) -> str:
        """"start" when they begin talking, "end" when they have finished, "" otherwise."""
        level = rms(frame)
        self.level = level
        loud = level > self.threshold
        # Ending needs it properly quiet again, not just under the line it took to start.
        quiet = level < self.threshold * 0.7
        if not self.speaking:
            # The floor learns from silence only: down fast (a quieter line than thought), up slowly (so a long
            # sentence does not teach it that speech is the new silence).
            if level < self.floor:
                self.floor = 0.85 * self.floor + 0.15 * level
            elif not loud:
                self.floor = 0.995 * self.floor + 0.005 * level
            self._loud = self._loud + 1 if loud else 0
            if self._loud >= self.start_frames:
                self.speaking = True
                self._quiet = 0
                return "start"
            return ""
        self._quiet = self._quiet + 1 if quiet else 0
        if self._quiet >= self.end_frames:
            self.speaking = False
            self._loud = 0
            return "end"
        return ""
