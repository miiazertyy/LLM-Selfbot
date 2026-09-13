import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

from app.utils.paths import DATA_DIR

# Target type: Discord account index (int) or "snap" / "snapN" for Snapchat.
CONFIG_DIR = DATA_DIR / "config"
IPC_DIR = DATA_DIR / "ipc"


def _count_accounts() -> int:
    """How many Discord accounts are actually configured, 0 is a real answer.

    This used to floor at 1, which invented an account with no token: the UI
    listed a phantom "Discord #1" and the supervisor spawned a runner for it
    that crash-looped forever.
    """
    from app.utils.credentials import real
    count = 0
    i = 1
    while real(f"DISCORD_TOKEN_{i}"):
        count = i
        i += 1
    if count == 0 and real("DISCORD_TOKEN"):
        count = 1
    return count


def _count_snap_accounts() -> int:
    from app.utils.credentials import real
    if not (real("SNAP_USERNAME") or real("SNAP_USERNAME_1")):
        return 0
    n = 1
    while real(f"SNAP_USERNAME_{n + 1}"):
        n += 1
    return n


_VALID_TARGET = re.compile(r"^(?:[1-9][0-9]{0,2}|snap(?:[2-9][0-9]{0,2})?)$")


def validate_target(target):
    """Normalise a target, rejecting anything that isn't a real account id.

    The target is interpolated into an IPC filename, so an unchecked value like
    "../../evil" would write outside the data directory.
    """
    t = str(target).strip()
    if not _VALID_TARGET.match(t):
        raise ValueError(f"invalid IPC target: {target!r}")
    return int(t) if t.isdigit() else t


def is_snap(account) -> bool:
    return isinstance(account, str) and account.startswith("snap")


def snap_index(account) -> int:
    if account == "snap":
        return 1
    try:
        return int(str(account)[4:])
    except (ValueError, TypeError):
        return 1


def cmd_file(target) -> Path:
    target = validate_target(target)
    if is_snap(target):
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        return IPC_DIR / f"tg_commands_{target}.json"
    return CONFIG_DIR / f"tg_commands_{target}.json"


def result_file(target) -> Path:
    target = validate_target(target)
    if is_snap(target):
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        return IPC_DIR / f"tg_results_{target}.json"
    return CONFIG_DIR / f"tg_results_{target}.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return default
        return json.loads(text)
    except Exception:
        return default


def _write_json_atomic(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def send_command(target, cmd: str, payload: dict = None) -> str:
    """Append a command to the target's IPC file (atomic write, merge-safe)."""
    cmd_id = str(uuid.uuid4())
    entry = {"id": cmd_id, "cmd": cmd, "payload": payload or {}, "ts": time.time()}
    f = cmd_file(target)
    for attempt in range(5):
        try:
            existing = _read_json(f, [])
            if not isinstance(existing, list):
                existing = []
            existing.append(entry)
            _write_json_atomic(f, existing)
            return cmd_id
        except Exception:
            time.sleep(0.05 * (attempt + 1))
    return ""


# Matches the runner's own cap. A result is only cleared when it is read, so
# anything whose caller timed out lingers; unbounded, the file grew to tens of
# megabytes and every read/write of it blocked the event loop.
MAX_RESULTS = 40


def _prune(results: dict) -> dict:
    if len(results) <= MAX_RESULTS:
        return results
    return dict(list(results.items())[-MAX_RESULTS:])


async def wait_for_result(target, cmd_id: str, timeout: float = 10.0) -> dict | None:
    """Poll the target's result file until the runner posts a result."""
    f = result_file(target)
    deadline = time.time() + timeout
    while time.time() < deadline:
        results = _read_json(f, {})
        if isinstance(results, dict) and cmd_id in results:
            result = results.pop(cmd_id)
            _write_json_atomic(f, _prune(results))
            return result
        await asyncio.sleep(0.3)
    # Timed out. Trim here too, so a run of timeouts cannot pile up unread
    # answers faster than the runner's own cap clears them.
    results = _read_json(f, {})
    if isinstance(results, dict) and len(results) > MAX_RESULTS:
        _write_json_atomic(f, _prune(results))
    return None


async def send_and_wait(target, cmd: str, payload: dict = None, timeout: float = 10.0) -> dict | None:
    cmd_id = send_command(target, cmd, payload)
    if not cmd_id:
        return {"ok": False, "reason": "could not write IPC command file"}
    return await wait_for_result(target, cmd_id, timeout)


def discover_targets() -> dict:
    """All reachable IPC targets keyed by a stable web id."""
    out = {}
    for n in range(1, _count_accounts() + 1):
        out[f"discord_{n}"] = {"platform": "discord", "account": n, "target": n}
    for n in range(1, _count_snap_accounts() + 1):
        key = "snap" if n == 1 else f"snap{n}"
        out[f"snapchat_{n}"] = {"platform": "snapchat", "account": n, "target": key}
    return out
