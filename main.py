"""
main.py — Unified launcher for the LLM Selfbot.

Usage:
  python main.py              → run all enabled platforms
  python main.py discord      → Discord only
  python main.py snapchat     → Snapchat bridge only (pair with: cd platforms/snapchat && npm start)
  python main.py both         → Discord + Snapchat bridge concurrently

The Snapchat platform is split across two processes:
  • Python bridge (this file / platforms/snapchat_bridge.py) — handles AI
  • Node.js runner (platforms/snapchat/snapchat_runner.js)   — handles browser

Start them together:
  python main.py snapchat   # in one terminal
  cd platforms/snapchat && npm start   # in another terminal

Or use run.sh / run.bat which handles both automatically.
"""

import sys
import os
import asyncio
import subprocess
import tempfile

# Ensure repo root is on the path so utils/ and core/ are importable
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from utils.ai import init_ai
from utils.db import init_db
from utils.memory import init_memory
from utils.helpers import load_config


def _parse_mode() -> str:
    """Return 'discord', 'snapchat', or 'both' based on argv or config."""
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode in ("discord", "snapchat", "both"):
            return mode

    config = load_config()
    snap_cfg    = config.get("snapchat", {})
    discord_cfg = config.get("discord", {})

    snap_enabled    = snap_cfg.get("enabled", False)
    discord_enabled = discord_cfg.get("enabled", True)  # Discord on by default

    if snap_enabled and discord_enabled:
        return "both"
    if snap_enabled and not discord_enabled:
        return "snapchat"
    if discord_enabled and not snap_enabled:
        return "discord"

    print("[Main] Both discord.enabled and snapchat.enabled are false — nothing to run.")
    sys.exit(0)


def run_discord():
    """Import and run the Discord platform runner (mirrors original main.py behaviour)."""
    # Signal to discord_runner that the single-instance lock is already held by a
    # parent process. In "both" mode this function runs inside a spawned child
    # process (which does NOT inherit the sys attribute set in __main__), so we
    # must set it here too — otherwise the child would try to re-acquire the same
    # lock file held by the parent, fail, and exit immediately.
    sys._llmselfbot_lock_held = True
    # The discord runner uses its own asyncio.run() at the bottom, so we just exec it.
    import runpy
    runpy.run_path(
        os.path.join(os.path.dirname(__file__), "platforms", "discord_runner.py"),
        run_name="__main__",
    )


def _count_snap_accounts() -> int:
    """How many Snapchat accounts are configured (mirrors Discord's token scan).

    Account 1 = SNAP_USERNAME or SNAP_USERNAME_1; then SNAP_USERNAME_2, _3, ...
    counted contiguously. Returns 0 if none configured.
    """
    if not (os.getenv("SNAP_USERNAME") or os.getenv("SNAP_USERNAME_1")):
        return 0
    n = 1
    while os.getenv(f"SNAP_USERNAME_{n + 1}"):
        n += 1
    return n


def _run_snap_account(index: int):
    """Child-process entry point: pin this process to one account, then run its
    bridge. Setting the env var BEFORE importing the bridge is essential — the
    bridge reads SNAP_ACCOUNT_INDEX at import time to pick its IPC files."""
    os.environ["SNAP_ACCOUNT_INDEX"] = str(index)
    from platforms.snapchat_bridge import run
    run()


def run_snapchat_bridge():
    """Run the Snapchat bridge(s) — one process per configured account.

    A single account runs in-process (legacy behaviour). Multiple accounts each
    get their own child process so they have independent browsers + IPC channels.
    """
    from dotenv import load_dotenv
    base = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(dotenv_path=os.path.join(base, "config", ".env"), override=True)

    n = max(1, _count_snap_accounts())
    if n == 1:
        _run_snap_account(1)
        return

    import multiprocessing
    procs = []
    for i in range(1, n + 1):
        p = multiprocessing.Process(target=_run_snap_account, args=(i,), name=f"snap-{i}", daemon=False)
        p.start()
        procs.append(p)
        print(f"[Main] Snapchat bridge #{i} PID: {p.pid}")
    print(f"[Main] {n} Snapchat accounts running. Ctrl+C to stop.")
    try:
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        print("\n[Main] Shutting down Snapchat accounts...")
        for p in procs:
            p.terminate()
        for p in procs:
            p.join(timeout=5)


_tg_proc = None


def _spawn_telegram_controller():
    """Launch the Telegram controller as a child process in THIS console, so it
    starts together with the bot and its output (including the 'CONNECTED as @…'
    line and any errors) shows in the same window — no separate window needed.

    Skipped if TELEGRAM_BOT_TOKEN isn't configured. Disable with
    TELEGRAM_AUTOSTART=false if you'd rather run the controller yourself.
    """
    global _tg_proc
    base = os.path.dirname(os.path.abspath(__file__))
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(base, "config", ".env"), override=True)
    if os.getenv("TELEGRAM_AUTOSTART", "true").lower() == "false":
        return
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return
    controller = os.path.join(base, "telegram", "telegram_controller.py")
    if not os.path.exists(controller):
        return
    try:
        # Inherit stdout/stderr so it logs into the same window.
        _tg_proc = subprocess.Popen([sys.executable, controller], cwd=base)
        import atexit
        atexit.register(lambda: _tg_proc and _tg_proc.poll() is None and _tg_proc.terminate())
        print(f"[Main] Telegram controller started (PID {_tg_proc.pid}) — sharing this window")
    except Exception as e:
        print(f"[Main] Could not start Telegram controller: {e}")


def run_both():
    """Run the Discord runner + one Snapchat bridge per account, concurrently."""
    import multiprocessing
    from dotenv import load_dotenv

    base = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(dotenv_path=os.path.join(base, "config", ".env"), override=True)
    n = max(1, _count_snap_accounts())

    procs = []

    discord_proc = multiprocessing.Process(target=run_discord, name="discord", daemon=False)
    discord_proc.start()
    procs.append(discord_proc)
    print(f"[Main] Discord runner PID: {discord_proc.pid}")

    for i in range(1, n + 1):
        p = multiprocessing.Process(target=_run_snap_account, args=(i,), name=f"snap-{i}", daemon=False)
        p.start()
        procs.append(p)
        print(f"[Main] Snapchat bridge #{i} PID: {p.pid}")

    print(f"[Main] Discord + {n} Snapchat account(s) running. Ctrl+C to stop.")

    try:
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        print("\n[Main] Shutting down...")
        for p in procs:
            p.terminate()
        for p in procs:
            p.join(timeout=5)


if __name__ == "__main__":
    # Single-instance lock (prevents duplicate launches)
    lock_path = os.path.join(tempfile.gettempdir(), "llmselfbot.lock")
    try:
        lock_file = open(lock_path, "w")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        print("[Main] Another instance is already running.")
        sys.exit(1)

    # Signal to discord_runner that main.py already holds the lock
    sys._llmselfbot_lock_held = True

    mode = _parse_mode()
    print(f"[Main] Starting in mode: {mode}")

    # Start the Telegram controller in this same console, alongside the bot.
    _spawn_telegram_controller()

    try:
        if mode == "discord":
            run_discord()
        elif mode == "snapchat":
            run_snapchat_bridge()
        elif mode == "both":
            run_both()
    finally:
        lock_file.close()
