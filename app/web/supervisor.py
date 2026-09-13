import os
import subprocess
import threading
import time
from dataclasses import dataclass

from app.core.launcher import spawn_role, clear_pid_file
from app.web.logbus import bus

BACKOFF_BASE = 5.0
BACKOFF_MAX = 300.0
STABLE_RESET = 60.0

# Hard ceilings. A worker that dies instantly and repeatedly is a bug, not a
# transient failure, give up rather than respawn forever, and never let the
# child table grow past a sane size.
MAX_RESTARTS = 10
MAX_CHILDREN = 32


@dataclass
class Child:
    child_id: str
    role: str
    account: int | None
    label: str
    proc: subprocess.Popen | None = None
    state: str = "stopped"          # running | stopped | starting | crashing
    restarts: int = 0
    started_at: float = 0.0
    backoff: float = BACKOFF_BASE
    _stop_requested: bool = False
    _reader: threading.Thread | None = None
    _retry_at: float = 0.0


class Supervisor:
    def __init__(self, port: int = 8787, no_web: bool = False):
        self.port = port
        self.no_web = no_web
        self.children: dict[str, Child] = {}
        self.lock = threading.RLock()
        self._running = False

    # ── Child management ─────────────────────────────────────────────────────
    def register(self, child_id: str, role: str, account: int | None, label: str):
        with self.lock:
            self.children[child_id] = Child(child_id, role, account, label)

    def _planned_children(self) -> dict:
        """Which children SHOULD run, from config + credentials."""
        from app.utils.helpers import load_config
        from app.core.ipc import _count_accounts, _count_snap_accounts
        out = {}
        config = load_config()
        services = config.get("services", {}) or {}
        discord_on = config.get("discord", {}).get("enabled", True) \
            and services.get("discord", {}).get("enabled", True)
        snap_on = config.get("snapchat", {}).get("enabled", False) \
            and services.get("snapchat", {}).get("enabled", True)
        tg_on = services.get("telegram", {}).get("enabled", True)

        if discord_on:
            n = _count_accounts()
            for i in range(1, n + 1):
                out[f"discord_{i}"] = ("discord", i, f"Discord #{i}")
        if snap_on:
            # No floor of 1: without SNAP_USERNAME there is no account to run,
            # and spawning one anyway just crash-loops a runner with no login.
            for i in range(1, _count_snap_accounts() + 1):
                out[f"snapchat_{i}"] = ("snapchat", i, f"Snapchat #{i}")
        if tg_on:
            # Both halves must be real: the controller needs a numeric owner id
            # and used to die at import on the template's placeholder text.
            from app.utils.credentials import real, real_int
            if real("TELEGRAM_BOT_TOKEN") and real_int("TELEGRAM_OWNER_ID"):
                out["telegram"] = ("telegram", None, "Telegram")
        return out

    def start(self, child_id: str):
        with self.lock:
            child = self.children.get(child_id)
            if not child:
                role, account, label = self._planned_children().get(child_id, (None, None, child_id))
                if role is None:
                    return {"ok": False, "reason": f"unknown child {child_id}"}
                self.register(child_id, role, account, label)
                child = self.children[child_id]
            if child.proc and child.proc.poll() is None:
                return {"ok": True, "state": "running"}
            child._stop_requested = False
            self._launch(child)
            return {"ok": True, "state": child.state}

    def _launch(self, child: Child):
        alive = sum(1 for c in self.children.values() if c.proc and c.proc.poll() is None)
        if alive >= MAX_CHILDREN:
            child.state = "stopped"
            bus.append("supervisor",
                       f"Refusing to start {child.label}: {alive} workers already running "
                       f"(limit {MAX_CHILDREN})", "error")
            return
        try:
            child.proc = spawn_role(child.role, child.account)
            child.state = "starting"
            child.started_at = time.time()
            child._reader = threading.Thread(
                target=self._read_output, args=(child,), daemon=True, name=f"log-{child.child_id}"
            )
            child._reader.start()
            bus.append("supervisor", f"{child.label} started (pid {child.proc.pid})")
        except Exception as e:
            child.state = "crashing"
            bus.append("supervisor", f"{child.label} failed to start: {e}", "error")

    def _read_output(self, child: Child):
        try:
            for line in child.proc.stdout:
                bus.append(child.child_id, line)
        except Exception:
            pass

    def _ipc_target(self, child: Child):
        """The IPC name for this child, or None if it has no command channel."""
        if child.role == "discord":
            return child.account or 1
        if child.role == "snapchat":
            n = child.account or 1
            return "snap" if n == 1 else f"snap{n}"
        return None

    def stop(self, child_id: str, graceful_seconds: float = 6.0):
        """Stop a worker, asking it to log out before killing it.

        terminate() on Windows is TerminateProcess: the worker dies on the spot
        with its gateway socket still open, so Discord keeps the session alive
        until the heartbeat times out and the account goes on showing as online
        for the best part of a minute. The runner already knows how to close the
        connection properly, so it is asked first and only killed if it will not
        go.
        """
        with self.lock:
            child = self.children.get(child_id)
            if not child:
                return {"ok": False, "reason": f"unknown child {child_id}"}
            child._stop_requested = True
            proc = child.proc

        clean = False
        if proc and proc.poll() is None:
            target = self._ipc_target(child)
            if target is not None:
                try:
                    from app.core import ipc
                    ipc.send_command(target, "shutdown")
                    deadline = time.time() + graceful_seconds
                    while time.time() < deadline:
                        if proc.poll() is not None:
                            clean = True
                            break
                        time.sleep(0.2)
                except Exception as exc:
                    bus.append("supervisor",
                               f"{child.label}: could not ask it to log out ({exc})", "warn")

        with self.lock:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        bus.append("supervisor", f"{child.label} would not exit", "error")
            clear_pid_file(child.role, child.account)
            child.state = "stopped"
            bus.append("supervisor",
                       f"{child.label} stopped"
                       + (" (logged out cleanly)" if clean else " (forced)"))
            return {"ok": True, "clean": clean}

    def _sweep_stale_pids(self):
        """Kill workers left behind by a previous run.

        A hard kill of the app (Task Manager, crash, power loss) orphans the
        child processes; they keep the Discord session alive, so the account
        still shows as connected from the OLD client after a relaunch. Every
        pid file we find that is not one of our own children gets killed
        before anything new is spawned.
        """
        from app.core.ipc import IPC_DIR
        if not IPC_DIR.exists():
            return
        ours = {c.proc.pid for c in self.children.values() if c.proc and c.proc.poll() is None}
        for path in IPC_DIR.glob("pid_*"):
            try:
                pid = int(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            if pid in ours or pid <= 0:
                continue
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F", "/T"],
                        capture_output=True, timeout=10,
                    )
                else:
                    os.kill(pid, 9)
                bus.append("supervisor", f"Killed stale worker from a previous run (pid {pid})")
            except Exception:
                pass
            try:
                path.unlink()
            except OSError:
                pass

    def restart(self, child_id: str):
        self.stop(child_id)
        return self.start(child_id)

    def start_all(self):
        self._running = True
        self._sweep_stale_pids()
        for child_id, (role, account, label) in self._planned_children().items():
            with self.lock:
                if child_id not in self.children:
                    self.register(child_id, role, account, label)
                self.start(child_id)
        threading.Thread(target=self._watchdog, daemon=True, name="supervisor-watchdog").start()

    def stop_all(self):
        """Stop every worker at once.

        Asking each in turn would serialise the log-out grace period, so
        shutting down three accounts would take three times as long. They are
        independent processes, so they can all be told at the same time.
        """
        self._running = False
        ids = list(self.children)
        if not ids:
            return
        threads = []
        for child_id in ids:
            t = threading.Thread(target=self._stop_quietly, args=(child_id,),
                                 daemon=True, name=f"stop-{child_id}")
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=15)

    def _stop_quietly(self, child_id: str):
        try:
            self.stop(child_id)
        except Exception as e:
            bus.append("supervisor", f"error stopping {child_id}: {e}", "error")

    def _watchdog(self):
        """Poll children and schedule restarts.

        Backoff is tracked as a wake-up deadline rather than a sleep: sleeping
        here (previously up to 5 minutes, while holding self.lock) froze every
        start/stop the UI asked for and stopped other children being noticed.
        """
        while self._running:
            time.sleep(1)
            now = time.time()
            to_relaunch = []
            with self.lock:
                for child in list(self.children.values()):
                    if not child.proc:
                        continue
                    code = child.proc.poll()
                    if code is None:
                        if child.state == "starting" and now - child.started_at > STABLE_RESET:
                            child.state = "running"
                            child.backoff = BACKOFF_BASE
                            child.restarts = 0
                        continue
                    # The process is gone; its pid file must not survive to the
                    # next app run (a reused pid would be killed by the sweep).
                    clear_pid_file(child.role, child.account)
                    if child._stop_requested:
                        child.state = "stopped"
                        continue
                    if child.state == "crashing":
                        # Already scheduled, relaunch once the deadline passes.
                        if now >= child._retry_at:
                            to_relaunch.append(child)
                        continue
                    child.restarts += 1
                    if child.restarts > MAX_RESTARTS:
                        child._stop_requested = True
                        child.state = "stopped"
                        bus.append(
                            "supervisor",
                            f"{child.label} crashed {child.restarts} times, giving up. "
                            f"Check the logs and start it again from the UI.",
                            "error",
                        )
                        continue
                    child.backoff = min(child.backoff * 2, BACKOFF_MAX)
                    child.state = "crashing"
                    child._retry_at = now + child.backoff
                    bus.append(
                        "supervisor",
                        f"{child.label} exited (code {code}), restart "
                        f"#{child.restarts}/{MAX_RESTARTS} in {int(child.backoff)}s",
                        "error",
                    )
            for child in to_relaunch:
                with self.lock:
                    if self._running and not child._stop_requested:
                        self._launch(child)

    # ── Status ───────────────────────────────────────────────────────────────
    def status(self) -> list:
        out = []
        for child in self.children.values():
            uptime = 0.0
            if child.state in ("running", "starting", "crashing") and child.started_at:
                uptime = time.time() - child.started_at
            out.append({
                "id": child.child_id,
                "role": child.role,
                "account": child.account,
                "label": child.label,
                "state": child.state,
                "pid": child.proc.pid if child.proc else None,
                "restarts": child.restarts,
                "uptime": round(uptime),
            })
        return out
