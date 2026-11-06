"""Audio for calls: what a frame is, how it moves between rates, and the queue a call plays from.

Everything inside the call brain is 16-bit little-endian PCM. A platform hands in whatever it has (Discord's 48 kHz
stereo, a browser's 48 kHz mono) and plays whatever it wants; every conversion is here, so nothing else needs to
know what a sample rate is.

Built on audioop, not numpy: the exe leaves numpy out on purpose (packaging/specparts.py, 37 MB of OpenBLAS), and
audioop is already in it because discord.py's player imports it. It is C, so a frame costs nothing, and its resampler
carries state from one frame to the next, which is what stops a stream of frames clicking at every join.
"""
import array
import io
import threading
import wave
from collections import deque

try:
    import audioop
except ImportError:                     # Python 3.13 took it out; discord.py pulls in audioop-lts there, same name
    import audioop_lts as audioop       # type: ignore[no-redef]

# The rate the brain listens at. Speech needs nothing above 8 kHz, and both hearing paths want 16 kHz.
BRAIN_RATE = 16000
FRAME_MS = 20


def _whole(pcm: bytes, channels: int = 1) -> bytes:
    """Whole samples only: audioop refuses a fragment that stops part way through one."""
    size = 2 * max(1, channels)
    extra = len(pcm) % size
    return pcm[:-extra] if extra else pcm


def to_mono(pcm: bytes, channels: int) -> bytes:
    if channels <= 1:
        return pcm
    return audioop.tomono(_whole(pcm, 2), 2, 0.5, 0.5)


def to_channels(pcm: bytes, channels: int) -> bytes:
    if channels <= 1:
        return pcm
    return audioop.tostereo(_whole(pcm), 2, 1, 1)


class Converter:
    """One stream of audio from one format to another, a piece at a time.

    Keeps the resampler's state between pieces, so a stream of 20 ms frames comes out as one continuous sound.
    Going down in rate, audioop's one-pole filter is switched on, so the top end of 48 kHz does not fold back as hiss
    at 16 kHz. Its output length wanders by a sample or so from piece to piece, which is what a streaming resampler
    does: nothing downstream counts on a fixed length coming out of here.
    """

    def __init__(self, src_rate: int, src_channels: int, dst_rate: int, dst_channels: int):
        self.src_rate, self.src_channels = src_rate, src_channels
        self.dst_rate, self.dst_channels = dst_rate, dst_channels
        self.weights = (1, 1) if dst_rate < src_rate else (1, 0)
        self._state = None

    def __call__(self, pcm: bytes) -> bytes:
        if not pcm:
            return b""
        mono = _whole(to_mono(pcm, self.src_channels))
        if self.src_rate != self.dst_rate:
            mono, self._state = audioop.ratecv(mono, 2, 1, self.src_rate, self.dst_rate, self._state, *self.weights)
        return to_channels(mono, self.dst_channels)

    def reset(self) -> None:
        self._state = None


def resample(pcm: bytes, src: int, dst: int) -> bytes:
    """Mono PCM from one rate to another, as one whole piece."""
    if src == dst or not pcm:
        return pcm
    return Converter(src, 1, dst, 1)(pcm)


def convert(pcm: bytes, src_rate: int, src_channels: int, dst_rate: int, dst_channels: int) -> bytes:
    return Converter(src_rate, src_channels, dst_rate, dst_channels)(pcm)


def rms(pcm: bytes) -> float:
    pcm = _whole(pcm)
    return float(audioop.rms(pcm, 2)) if pcm else 0.0


def silence(ms: int, rate: int, channels: int = 1) -> bytes:
    return bytes(2 * channels * int(rate * ms / 1000))


def wav_bytes(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(_whole(pcm, channels))
    return buf.getvalue()


def read_wav(data: bytes) -> tuple:
    """(16-bit pcm, rate, channels) out of a WAV file.

    Read by hand rather than with `wave`, because of what speech servers write: a header saying the file is endless,
    since they send it before knowing how long it will be (`wave` reads that as nothing), and 32-bit float samples,
    which local models like to produce (`wave` refuses those outright).
    """
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos, rate, channels, kind, bits = 12, 24000, 1, 1, 16
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        if cid == b"fmt ":
            kind = int.from_bytes(data[pos + 8:pos + 10], "little")
            channels = int.from_bytes(data[pos + 10:pos + 12], "little") or 1
            rate = int.from_bytes(data[pos + 12:pos + 16], "little") or rate
            bits = int.from_bytes(data[pos + 22:pos + 24], "little") or bits
            if kind == 0xFFFE and size >= 26:           # the "extensible" form: the real kind is further in
                kind = int.from_bytes(data[pos + 32:pos + 34], "little")
        elif cid == b"data":
            body = data[pos + 8:]
            if 0 < size < len(body):
                body = body[:size]
            return _sixteen(body, kind, bits), rate, channels
        pos += 8 + size + (size & 1)
    raise ValueError("no audio in the WAV file")


def _sixteen(body: bytes, kind: int, bits: int) -> bytes:
    """Samples of any common kind, as 16-bit."""
    if kind == 3:                                       # floating point
        code = "d" if bits == 64 else "f"
        samples = array.array(code)
        samples.frombytes(body[: len(body) - (len(body) % samples.itemsize)])
        return array.array("h", (max(-32768, min(32767, int(s * 32767.0))) for s in samples)).tobytes()
    width = max(1, bits // 8)
    body = body[: len(body) - (len(body) % width)]
    if width == 2:
        return body
    if width == 1:                                      # 8-bit WAV samples are unsigned
        body = audioop.bias(body, 1, -128)
    return audioop.lin2lin(body, width, 2)


class Playout:
    """What a call is about to say, as frames the platform pulls at its own pace.

    Thread-safe, because Discord pulls from a player thread of its own. Everything put in is converted to the
    platform's own format straight away, so `read()` only ever slices.
    """

    def __init__(self, rate: int, channels: int = 1, frame_ms: int = FRAME_MS):
        self.rate = rate
        self.channels = channels
        self.frame_size = 2 * channels * rate * frame_ms // 1000
        self._buf = deque()
        self._len = 0
        self._lock = threading.Lock()
        self._conv = None
        self.played_ms = 0          # how much of its own voice has gone out, over the whole call

    def put(self, pcm: bytes, src_rate: int, src_channels: int = 1) -> None:
        if not pcm:
            return
        conv = self._conv
        if conv is None or (conv.src_rate, conv.src_channels) != (src_rate, src_channels):
            conv = self._conv = Converter(src_rate, src_channels, self.rate, self.channels)
        out = conv(pcm)
        with self._lock:
            self._buf.append(out)
            self._len += len(out)

    def read(self) -> bytes:
        """One frame: what is queued, padded with silence when it runs out mid-frame."""
        need = self.frame_size
        parts = []
        with self._lock:
            while need and self._buf:
                head = self._buf[0]
                if len(head) <= need:
                    parts.append(self._buf.popleft())
                    need -= len(head)
                    self._len -= len(head)
                else:
                    parts.append(head[:need])
                    self._buf[0] = head[need:]
                    self._len -= need
                    need = 0
        took = self.frame_size - need
        if took:
            self.played_ms += int(took / (2 * self.channels * self.rate) * 1000)
        if need:
            parts.append(bytes(need))
        return b"".join(parts)

    def clear(self) -> int:
        """Everything not yet played, dropped: they started talking over it."""
        with self._lock:
            dropped = self._len
            self._buf.clear()
            self._len = 0
        if self._conv is not None:
            self._conv.reset()
        return dropped

    @property
    def queued_ms(self) -> int:
        with self._lock:
            return int(self._len / (2 * self.channels * self.rate) * 1000)

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._len > 0
