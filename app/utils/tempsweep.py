"""Old unpack folders (_MEI...) the single-file exe left in the temp folder when it was ended rather than closed.

The exe unpacks itself into a new _MEI folder each time it starts and deletes it when it closes. Ended from Task
Manager, by a crash, by Windows shutting down or by a script's taskkill /F, the part that deletes it is ended too, and
the folder (about 110 MB) stays: 221 of them had piled up on one PC (2026-11-06). A minute after the app starts, this
clears the ones nothing uses any more.

A folder in use is never touched. Renaming it proves nothing: Windows renames a folder even with a DLL in it loaded
(tried). What it never allows is deleting a DLL a program has loaded, and every running copy of the app has its own
Python DLL loaded from its folder, so that DLL is deleted first, and a refusal leaves the folder as it is. One changed in
the last ten minutes is left too (a copy may be unpacking into it now), and only the app's own: a folder without its
resources and panel inside belongs to some other program. Windows only, where the pile-up is and the test holds.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

_NAME = re.compile(r"^_MEI\d+$")
#: Seconds a folder must have gone unchanged before it is looked at.
MIN_AGE = 600


def _ours(folder: Path) -> bool:
    return (folder / "resources" / "config.yaml").is_file() and (folder / "webui").is_dir()


def stale(own: Path, now: float | None = None) -> list[Path]:
    """The app's other unpack folders beside its own one, unchanged for a while."""
    now = time.time() if now is None else now
    out = []
    try:
        entries = list(os.scandir(own.parent))
    except OSError:
        return out
    for e in entries:
        if not _NAME.match(e.name) or e.name == own.name:
            continue
        try:
            if not e.is_dir(follow_symlinks=False) or now - e.stat(follow_symlinks=False).st_mtime < MIN_AGE:
                continue
        except OSError:
            continue
        folder = Path(e.path)
        if _ours(folder):
            out.append(folder)
    return out


def clear(folder: Path) -> bool:
    """One folder deleted, if nothing has its Python DLL loaded. False when it is in use (and left as it was)."""
    for dll in folder.glob("python3*.dll"):
        try:
            dll.unlink()
        except OSError:
            return False        # loaded: a copy of the app is running from here
    shutil.rmtree(folder, ignore_errors=True)
    return True


def sweep(own: Path) -> tuple[int, int]:
    """Clear the stale folders beside `own`. Returns (cleared, left because in use)."""
    cleared = busy = 0
    for folder in stale(own):
        if clear(folder):
            cleared += 1
        else:
            busy += 1
    return cleared, busy


def start(delay: float = 60.0) -> None:
    """In the frozen Windows app: sweep once, a while after starting, off the main thread."""
    own = getattr(sys, "_MEIPASS", None)
    if not own or sys.platform != "win32" or not getattr(sys, "frozen", False):
        return

    def run():
        time.sleep(delay)
        try:
            cleared, busy = sweep(Path(own))
        except Exception:
            return
        if cleared:
            print(f"[LLMSelfbot] Cleared {cleared} old unpack folder(s) from the temp folder.", flush=True)

    threading.Thread(target=run, daemon=True, name="temp-sweep").start()
