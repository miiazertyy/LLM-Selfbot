"""Writing a small file whole, from several processes at once.

The IPC files (commands, answers, the Snapchat queues) have more than one
writer: the panel, a worker, the Telegram controller. Each wrote through a
temporary file named after the real one ("tg_commands_snap.json.tmp"), so
two writers at the same instant opened the same temporary file, and Windows
turned the second away with a PermissionError. One night that killed the
Snapchat bridge, which then sat dead until morning.

Every write now has a temporary file of its own, and a write Windows refuses
for a moment (another process reading the file, or replacing it) is tried
again, for up to about five seconds: two and a half were not always enough
on a computer busy with a game, where a reader is held up mid-read for longer
and the file stays open under the writer. A write that still cannot
land raises: the loops that call this log it and write on their next pass,
which is safer than writing the file in place, where another process
reading half of it could write back what it read and lose the rest.
"""
import json
import os
import time
import uuid
from pathlib import Path


def write_text_atomic(path, text: str, *, tries: int = 20) -> None:
    """Replace `path` with `text` in one step: a reader sees the old file or the new one, never half of either."""
    path = Path(path)
    pause = 0.02
    for attempt in range(tries):
        # A new one each try: the last may still be held, by a virus scanner looking at a file just written, say.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(pause)
            pause = min(pause * 2, 0.3)
        finally:
            # Gone already when the write landed; otherwise not left lying about.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def write_json_atomic(path, data, *, indent=None, tries: int = 20) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=indent), tries=tries)
