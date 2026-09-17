import asyncio
import json
import os
import re
import threading
import time
from collections import deque
from itertools import islice
from datetime import datetime

from app.utils.paths import DATA_DIR

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Worker output arrives as plain text on a pipe, so the colours the runner
# prints are stripped along with the escape codes and every line looked
# identical in the panel. The glyphs the logger uses survive, so the kind of
# line can be recovered from those and coloured properly.
_MARKERS = (
    ("error", ("✗", "Traceback", "Exception", "error:", "Error:", "failed", "Failed")),
    ("warn", ("⚠", "⟳", "⏱", "RATE LIMITED", "rate limit",
              "warning", "Warning", "cooldown")),
    ("reply", ("↳", "Replied", "sent voice", "Queued picture")),
    ("recv", ("←", "in #", "waiting")),
    ("system", ("⚙",)),
)


def classify(text: str) -> str:
    """Best guess at the kind of line, used only for colour."""
    for level, needles in _MARKERS:
        if any(n in text for n in needles):
            return level
    return "info"


LOGS_DIR = DATA_DIR / "logs"
MAX_BUFFER = 2000
MAX_FILE_BYTES = 5 * 1024 * 1024


class LogBus:
    def __init__(self):
        self.buffer: deque = deque(maxlen=MAX_BUFFER)
        # queue -> the loop it belongs to, so entries published from a worker
        # thread can be handed over with call_soon_threadsafe.
        self.subscribers: dict = {}
        self.lock = threading.Lock()
        self.file_path = LOGS_DIR / "app.jsonl"
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        # Held open rather than reopened per line, with the size tracked in
        # memory so rotation costs no stat() on every write either.
        self._fh = None
        self._written = 0

    def _open(self):
        if self._fh is not None:
            return
        try:
            self._written = self.file_path.stat().st_size
        except OSError:
            self._written = 0
        self._fh = open(self.file_path, "a", encoding="utf-8")

    def _rotate(self):
        if self._written <= MAX_FILE_BYTES:
            return
        try:
            if self._fh is not None:
                self._fh.close()
            self._fh = None
            os.replace(self.file_path, self.file_path.with_suffix(".jsonl.1"))
        except OSError:
            pass
        self._written = 0

    def append(self, source: str, text: str, level: str = None):
        text = _ANSI_RE.sub("", str(text)).rstrip()
        if not text:
            return
        # Callers that know the level pass it; captured worker output does not,
        # so infer it rather than flattening everything to "info".
        if level is None:
            level = classify(text)
        entry = {
            "ts": time.time(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "source": source,
            "level": level,
            "text": text,
        }
        with self.lock:
            self.buffer.append(entry)
            try:
                self._rotate()
                self._open()
                line = json.dumps(entry, ensure_ascii=False) + "\n"
                self._fh.write(line)
                self._fh.flush()
                self._written += len(line.encode("utf-8"))
            except OSError:
                # Losing the line on disk must not lose it for live viewers;
                # the next append reopens.
                self._fh = None
        self.publish(entry)

    def tail(self, n: int = 100) -> list:
        with self.lock:
            # islice over the deque's tail, rather than copying all MAX_BUFFER
            # entries and then slicing: tail(50) copied 2000 of them.
            start = max(0, len(self.buffer) - n)
            return list(islice(self.buffer, start, None))

    def subscribe(self):
        q = asyncio.Queue(maxsize=500)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self.subscribers[q] = loop
        return q

    def unsubscribe(self, q):
        self.subscribers.pop(q, None)

    def publish(self, entry):
        """Hand an entry to every WebSocket subscriber.

        Called from supervisor reader threads, not from the event loop. A bare
        put_nowait from another thread does not wake the loop's selector, so
        the waiting coroutine only picked entries up when the loop happened to
        wake for something else - lines surfaced late, in bursts, or at the
        25s ping timeout. Handing the put to the owning loop is also the only
        thread-safe way to do it.
        """
        for q, loop in list(self.subscribers.items()):
            try:
                if loop is not None and not loop.is_closed():
                    loop.call_soon_threadsafe(self._offer, q, entry)
                else:
                    self._offer(q, entry)
            except RuntimeError:
                pass          # loop shut down between the check and the call

    @staticmethod
    def _offer(q, entry):
        """Put one entry on one subscriber's queue, on that queue's own loop."""
        try:
            q.put_nowait(entry)
        except asyncio.QueueFull:
            # Slow consumer, drop its oldest line to make room for this one.
            try:
                q.get_nowait()
                q.put_nowait(entry)
            except Exception:
                pass
        except Exception:
            pass


bus = LogBus()
