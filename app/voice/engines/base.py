"""What every engine is to the session that runs it.

An engine is given the persona's instructions and a voice, then fed the other person's audio and asked, now and
then, to say something on cue (picking up, checking they are still there, wrapping up). Everything it does back
goes through Events: audio to play, their words and its own as they are worked out, being talked over, and what it
is doing ("listening", "thinking", "speaking") for the panel.
"""


class Events:
    """What an engine tells the session. The session fills these in; the defaults do nothing."""

    def audio(self, pcm: bytes, rate: int) -> None:
        """Its voice, to play."""

    def heard(self, text: str) -> None:
        """Something they said, as words."""

    def said(self, text: str) -> None:
        """Something it said, as words."""

    def interrupted(self) -> None:
        """They started talking over it: stop playing now."""

    def state(self, name: str) -> None:
        """"listening", "thinking" or "speaking"."""

    def error(self, message: str) -> None:
        """Something went wrong the call cannot carry on through."""


class Engine:
    name = ""
    in_rate = 16000             # what feed() takes: mono 16-bit PCM at this rate

    def __init__(self, *, instructions: str, voice: str, events: Events, log=None):
        self.instructions = instructions
        self.voice = voice
        self.events = events
        self.log = log or (lambda *_: None)
        self.closed = False

    async def start(self) -> None:
        """Ready to hear. Raises if it cannot be (no key, no connection)."""

    async def feed(self, pcm: bytes) -> None:
        """Their audio, as it arrives."""

    async def cue(self, direction: str) -> None:
        """Say something now, on a stage direction (persona.direction)."""

    async def close(self) -> None:
        self.closed = True
