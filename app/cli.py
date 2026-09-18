"""
app/cli.py - argv parsing and role dispatch.

This is the single place that decides what the process does. Both entry points
route through it:

  main.py           source checkouts  (python main.py ...)
  app/desktop.py    the frozen exe    (LLMSelfbot.exe ...)

That matters because the supervisor spawns workers by re-invoking its own
executable with --role. If an entry point ignores argv, every "worker" becomes
another supervisor and the process count explodes.
"""

import argparse
import os
import sys
import tempfile
import time

CHILD_ENV = "LLMSELFBOT_CHILD"
ROLES = ("supervisor", "discord", "snapchat", "telegram", "updater")


def ensure_std_streams():
    """A windowed PyInstaller build (console=False) leaves sys.stdout/stderr as
    None, so the first print() raises AttributeError. Give them a sink.

    This lives here rather than in main.py because the frozen exe enters through
    app/desktop.py and never executes main.py.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass


ensure_std_streams()


def is_child() -> bool:
    """True when this process was spawned as a worker by a supervisor."""
    return os.environ.get(CHILD_ENV) == "1"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="LLMSelfbot", description="LLMSelfbot")
    ap.add_argument("--role", choices=list(ROLES), default=None,
                    help="run a single worker instead of the supervisor")
    ap.add_argument("--account", type=int, default=None,
                    help="account index for --role discord/snapchat")
    ap.add_argument("--no-web", action="store_true",
                    help="supervisor without the webui")
    ap.add_argument("--port", type=int, default=None,
                    help="overrides services.webui.port in config.yaml")
    ap.add_argument("--no-window", action="store_true",
                    help="serve the webui without opening a desktop window")
    ap.add_argument("mode", nargs="?", choices=["discord", "snapchat", "both"],
                    help="legacy: run platforms directly, no webui")
    return ap


# ── Roles ────────────────────────────────────────────────────────────────────

def _run_discord_role(account: int):
    os.environ["DISCORD_ACCOUNT_INDEX"] = str(account)
    from app.platforms import discord_runner
    discord_runner.run_discord_role(account)


def _run_snapchat_role(account: int):
    os.environ["SNAP_ACCOUNT_INDEX"] = str(account)
    from app.platforms.snapchat_bridge import run
    run()


def _run_telegram_role():
    from app.telegram_bot import telegram_controller
    telegram_controller.main()


def _run_updater_role():
    """Download + stage the latest release, then swap and relaunch."""
    from app.utils.paths import APP_DIR
    sys.path.insert(0, str(APP_DIR / "scripts"))
    import updater
    updater.main()


# ── Supervisor ───────────────────────────────────────────────────────────────

_lock_handle = None     # module-level so the lock cannot be dropped by GC


def acquire_single_instance():
    """Take the cross-process lock, or exit if another instance holds it.

    This is the backstop against runaway process spawning: only one supervisor
    can ever hold it, so a bad --role dispatch cannot multiply.

    The handle is stored module-side as well as returned. An OS file lock lives
    only as long as its handle, so a caller that ignored the return value would
    otherwise have the lock silently released the moment it was collected.
    """
    global _lock_handle
    if _lock_handle is not None:
        return _lock_handle
    lock_path = os.path.join(tempfile.gettempdir(), "llmselfbot.lock")

    # A restart launches the replacement while the old process is still serving,
    # and the old process going away is the handover: it drops this lock and its
    # port at the same moment. So for that one case the lock is worth waiting
    # for. Everything else still fails immediately, which is what keeps a bad
    # role dispatch from multiplying.
    #
    # Popped rather than read: the workers this process goes on to spawn inherit
    # its environment, and a flag left set would make some later second instance
    # wait twenty seconds instead of saying so straight away.
    deadline = time.time() + (20.0 if os.environ.pop("LLMSELFBOT_RESTART", "") else 0.0)

    while True:
        try:
            handle = open(lock_path, "a+")
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_handle = handle
            return handle
        except Exception:
            try:
                handle.close()
            except Exception:
                pass
            if time.time() >= deadline:
                print("[LLMSelfbot] Another instance is already running.", flush=True)
                sys.exit(1)
            time.sleep(0.25)


def run_supervisor(port=None, no_web=False):
    """Serve the webui and own the platform workers (blocking)."""
    if is_child():
        # A worker must never become a supervisor, that is the fork bomb.
        print("[LLMSelfbot] Refusing to start a supervisor inside a worker process.", flush=True)
        sys.exit(2)

    from app.web.server import run_server
    from app.web.supervisor import Supervisor

    # A restart hands the port over, so the panel that asked for it reconnects
    # to the address it is already on rather than to nothing.
    if port is None:
        port = int(os.environ.get("SELFBOT_PORT", "") or 0) or None

    lock_file = acquire_single_instance()
    supervisor = Supervisor(port=port or 8787, no_web=no_web)
    try:
        supervisor.start_all()
        run_server(supervisor=supervisor, port=port, no_web=no_web)
    finally:
        supervisor.stop_all()
        lock_file.close()


# ── Legacy direct mode ───────────────────────────────────────────────────────

def _count_snap_accounts() -> int:
    from app.utils.credentials import real
    if not (real("SNAP_USERNAME") or real("SNAP_USERNAME_1")):
        return 0
    n = 1
    while real(f"SNAP_USERNAME_{n + 1}"):
        n += 1
    return n


def _count_discord_accounts() -> int:
    from app.utils.helpers import load_tokens
    return len(load_tokens())


def _legacy_mode(mode: str):
    from app.core.launcher import spawn_role
    print(f"[LLMSelfbot] Starting in mode: {mode}", flush=True)
    procs = []
    if mode in ("discord", "both"):
        for i in range(1, max(1, _count_discord_accounts()) + 1):
            procs.append(spawn_role("discord", i, capture=False))
    if mode in ("snapchat", "both"):
        for i in range(1, max(1, _count_snap_accounts()) + 1):
            procs.append(spawn_role("snapchat", i, capture=False))
    for p in procs:
        print(f"[LLMSelfbot] Started child PID {p.pid}", flush=True)
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\n[LLMSelfbot] Shutting down...", flush=True)
        for p in procs:
            p.terminate()


# ── Entry ────────────────────────────────────────────────────────────────────

def bootstrap():
    """Prepare the process: data dir, credentials, PATH for bundled tools."""
    from app.utils.paths import seed_data_dir
    from app.utils import binaries
    seed_data_dir()
    load_env()
    binaries.ensure_path()   # DATA_DIR/bin (ffmpeg), inherited by child roles


def load_env():
    """Load config/.env into this process.

    The runners each did this for themselves, but the supervisor never did - so
    it decided how many accounts to start from an environment that had no
    tokens in it. That was survivable only because the account counter used to
    floor at 1; with the counter reporting the truth, the supervisor would
    otherwise start nothing at all.
    """
    try:
        from dotenv import load_dotenv
        from app.utils.helpers import get_env_path
        load_dotenv(dotenv_path=get_env_path(), override=True)
    except Exception as e:
        print(f"[LLMSelfbot] could not read config/.env: {e}", flush=True)


def run(argv=None) -> bool:
    """Dispatch on argv.

    Returns True when a role/mode was handled, False when the caller should
    fall through to its own default (the desktop window).
    """
    args = build_parser().parse_args(argv)
    bootstrap()

    if args.role:
        if args.role == "discord":
            _run_discord_role(args.account or 1)
        elif args.role == "snapchat":
            _run_snapchat_role(args.account or 1)
        elif args.role == "telegram":
            _run_telegram_role()
        elif args.role == "updater":
            _run_updater_role()
        else:
            run_supervisor(port=args.port, no_web=args.no_web)
        return True

    if args.mode:
        lock_file = acquire_single_instance()
        try:
            _legacy_mode(args.mode)
        finally:
            lock_file.close()
        return True

    if args.no_window:
        run_supervisor(port=args.port, no_web=args.no_web)
        return True

    return False    # headless callers get the supervisor; desktop opens a window
