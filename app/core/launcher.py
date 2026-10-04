import os
import subprocess
import sys

from app.utils.paths import APP_DIR
from app.utils.procs import quiet_kwargs


def is_child() -> bool:
    return os.environ.get("LLMSELFBOT_CHILD") == "1"


def under_panel() -> bool:
    """Whether the panel is reading this worker's output: a process it started,
    or, on a phone, a thread it runs (app/core/inprocess.py). Workers write
    their events for the panel (a chat changed, a model was used) only then."""
    if os.environ.get("LLMSELFBOT_CHILD") == "1":
        return True
    from app.core import inprocess
    return inprocess.current() is not None


def pid_file(role: str, account: int | None) -> str:
    """Path of the pid file written for one spawned worker."""
    from app.core.ipc import IPC_DIR
    IPC_DIR.mkdir(parents=True, exist_ok=True)
    return str(IPC_DIR / f"pid_{role}_{account or 'x'}")


def role_argv(role: str, account: int | None = None) -> list[str]:
    """argv that re-invokes THIS program in a different role."""
    if getattr(sys, "frozen", False):
        base = [sys.executable]
    else:
        base = [sys.executable, str(APP_DIR / "main.py")]
    argv = base + ["--role", role]
    if account is not None:
        argv += ["--account", str(account)]
    return argv


def spawn_role(role, account=None, capture=True, extra_env=None) -> subprocess.Popen:
    # A phone cannot start processes: there the role runs on a thread of this
    # one, behind the same interface (see app/core/inprocess.py).
    from app.utils import device
    if device.single_process():
        from app.core import inprocess
        return inprocess.start(role, account)
    env = {**os.environ, "LLMSELFBOT_CHILD": "1", **(extra_env or {})}
    proc = subprocess.Popen(
        role_argv(role, account), env=env, cwd=str(APP_DIR),
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
        **quiet_kwargs(),
    )
    try:
        with open(pid_file(role, account), "w", encoding="utf-8") as f:
            f.write(str(proc.pid))
    except OSError:
        pass
    return proc


def clear_pid_file(role: str, account: int | None) -> None:
    try:
        os.remove(pid_file(role, account))
    except OSError:
        pass


def spawn_process(argv, capture=True, extra_env=None) -> subprocess.Popen:
    """Spawn an arbitrary process (e.g. node runner) with unified pipe options."""
    env = {**os.environ, **(extra_env or {})}
    return subprocess.Popen(
        argv, env=env, cwd=str(APP_DIR),
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
        **quiet_kwargs(),
    )
