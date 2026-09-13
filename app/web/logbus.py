import asyncio
import json
import os
import re
import threading
import time
from collections import deque
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
        self.subscribers: set = set()
        self.lock = threading.Lock()
        self.file_path = LOGS_DIR / "app.jsonl"
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    def _rotate(self):
        if self.file_path.exists() and self.file_path.stat().st_size > MAX_FILE_BYTES:
            try:
                os.replace(self.file_path, self.file_path.with_suffix(".jsonl.1"))
            except OSError:
                pass

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
                with open(self.file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                pass
        self.publish(entry)

    def tail(self, n: int = 100) -> list:
        with self.lock:
            return list(self.buffer)[-n:]

    def subscribe(self):
        q = asyncio.Queue(maxsize=500)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    def publish(self, entry):
        """Hand an entry to every WebSocket subscriber.

        Called from supervisor reader threads rather than the event loop, so it
        stays synchronous, put_nowait is safe cross-thread for a queue that is
        only awaited on one loop.
        """
        for q in list(self.subscribers):
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
