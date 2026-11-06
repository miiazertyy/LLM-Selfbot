import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass

from app.core.launcher import spawn_role, clear_pid_file
from app.platforms import registry
from app.web.logbus import bus

# Written by the runners in front of a Chats event on their stdout.
CHAT_EVENT_MARK = "\x1eCHAT "
# ...and in front of a model's thinking (see logger.log_thinking).
THINK_MARK = "\x1eTHINK "
# ...and in front of a model having been used (see usage.emit).
MODEL_MARK = "\x1eMODEL "
# ...and in front of a request to a model starting or ending (see usage.work).
WORK_MARK = "\x1eWORK "
# A setting was just used (discord_runner.emit_use): its row in Settings lights up.
USE_MARK = "\x1eUSE "

BACKOFF_BASE = 5.0
BACKOFF_MAX = 300.0
STABLE_RESET = 60.0

# Hard ceilings. A worker that dies instantly and repeatedly is a bug, not a transient failure: give up rather than respawn forever, and never let the child table grow past a sane size.
MAX_RESTARTS = 10
# A worker that exits with this needs a person (its login was refused): it is left stopped, never restarted by itself.
# Started again it would log in again, and again, every couple of minutes: how a Snapchat account got locked.
NEEDS_SIGN_IN = 4
MAX_CHILDREN = 32


def _alert_crash(child, title: str, detail: str):
    """Queue a crash alert for the Telegram controller.

    It polls each account's command file for alerts
    (telegram_controller._error_notification_loop), and the runners leave
    them there for it, so the alert goes in the file of the account that
    crashed. Only with Crash alerts on (Settings, App, Telegram); the
    controller itself has nobody to tell.
    """
    if child.role not in registry.IDS:
        return
    try:
        from app.utils.helpers import load_config
        notes = (load_config() or {}).get("notifications", {}) or {}
        if not notes.get("telegram_crash_alerts", True):
            return
        from app.core import ipc
        n = child.account or 1
        target = n if child.role == "discord" else ipc.browser_target(child.role, n)
        ipc.send_command(target, "send_error_notification", {"title": title, "detail": detail, "kind": "crash"})
    except Exception:
        pass


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
        # The accounts stopped because their social was switched off: switched on again, these start again.
        self._switched_off: set[str] = set()
        # Which socials were on when last looked at (app/utils/socials.py): as the app opened, then at each switch.
        self._socials_seen: dict | None = None

    # ── Child management ─────────────────────────────────────────────────────
    def register(self, child_id: str, role: str, account: int | None, label: str):
        with self.lock:
            self.children[child_id] = Child(child_id, role, account, label)

    def _planned_children(self) -> dict:
        """Which children SHOULD run, from config + credentials."""
        from app.utils.helpers import load_config
        from app.core.ipc import (_count_accounts, _count_snap_accounts, _count_tiktok_accounts,
                                  _count_instagram_accounts, _count_x_accounts, _count_reddit_accounts,
                                  _count_whatsapp_accounts, _count_minecraft_accounts, _count_imessage_accounts,
                                  _count_telegram_accounts)
        out = {}
        config = load_config()
        services = config.get("services", {}) or {}
        # Every social is on unless switched off, both of its switches counted (app/utils/socials.py). One with no
        # accounts yet runs nothing either way: they are added on the Accounts page. The persona's Telegram accounts
        # have a switch of their own there, never the control bot's (services.telegram, below).
        from app.utils import socials
        on = socials.on(config)
        tg_on = services.get("telegram", {}).get("enabled", True)

        from app.utils import device
        counts = {"discord": _count_accounts, "snapchat": _count_snap_accounts, "tiktok": _count_tiktok_accounts,
                  "instagram": _count_instagram_accounts, "x": _count_x_accounts, "reddit": _count_reddit_accounts,
                  "whatsapp": _count_whatsapp_accounts, "minecraft": _count_minecraft_accounts,
                  "imessage": _count_imessage_accounts, "telegram": _count_telegram_accounts}
        for p in registry.PLATFORMS:
            # A phone has no Chrome or Node beside the app to run the others with.
            if not on[p.id] or (device.is_phone() and not p.on_phone):
                continue
            # No floor of 1: without an account to run, spawning one anyway just crash-loops a runner with no log.
            n = counts[p.id]()
            # Where accounts run inside the app (a phone), Discord keeps its account in module state, so one runs at
            # a time; the panel says so.
            if p.id == "discord" and device.single_process():
                n = min(n, 1)
            for i in range(1, n + 1):
                out[f"{p.id}_{i}"] = (p.id, i, f"{p.name} #{i}")
        if tg_on:
            # Both halves must be real: the controller needs a numeric owner id and used to die at import on the template's placeholder text.
            from app.utils.credentials import real, real_int
            if real("TELEGRAM_BOT_TOKEN") and real_int("TELEGRAM_OWNER_ID"):
                out["telegram"] = ("telegram", None, "Telegram")
        return out

    # ── Accounts waiting for a person to sign them in (NEEDS_SIGN_IN) ────────
    # Kept on disk: the app opened again would otherwise start one at once and log it in again, once per launch.
    @staticmethod
    def _sign_in_file():
        from app.utils.paths import DATA_DIR
        return DATA_DIR / "needs_sign_in.json"

    def needs_sign_in(self) -> set:
        try:
            return set(json.loads(self._sign_in_file().read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return set()

    def _mark_sign_in(self, child_id: str, needs: bool):
        ids = self.needs_sign_in()
        if (child_id in ids) == needs:
            return
        ids = ids | {child_id} if needs else ids - {child_id}
        try:
            self._sign_in_file().write_text(json.dumps(sorted(ids)), encoding="utf-8")
        except OSError:
            pass

    def start(self, child_id: str):
        """Start one account. Asked for by a person (start_all and a social switched on skip the accounts waiting for
        a sign-in), so it is no longer waiting."""
        self._mark_sign_in(child_id, False)
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
                # A Chats event from the runner (see emit_chat_event), not a log line.
                if line.startswith(CHAT_EVENT_MARK):
                    self._chat_event(child, line[len(CHAT_EVENT_MARK):])
                    continue
                # A model was just used: the panel's Models rows light up and the Usage counts move.
                if line.startswith(MODEL_MARK):
                    try:
                        evt = json.loads(line[len(MODEL_MARK):])
                        if isinstance(evt, dict):
                            evt["target"] = child.child_id
                            bus.event("model", evt)
                    except ValueError:
                        pass
                    continue
                # A model at work: a request to it started, or ended.
                if line.startswith(WORK_MARK):
                    try:
                        evt = json.loads(line[len(WORK_MARK):])
                        if isinstance(evt, dict):
                            evt["target"] = child.child_id
                            bus.event("work", evt)
                    except ValueError:
                        pass
                    continue
                if line.startswith(USE_MARK):
                    try:
                        evt = json.loads(line[len(USE_MARK):])
                        if isinstance(evt, dict):
                            evt["target"] = child.child_id
                            bus.event("use", evt)
                    except ValueError:
                        pass
                    continue
                # A reasoning model's thinking: one line of JSON on the pipe, many in the log.
                if line.startswith(THINK_MARK):
                    try:
                        t = json.loads(line[len(THINK_MARK):])
                        head = f"Thinking ({t['model']})" if t.get("model") else "Thinking"
                        bus.append(child.child_id, f"{head}\n{t.get('text', '')}", "think")
                    except (ValueError, KeyError, TypeError):
                        pass
                    continue
                bus.append(child.child_id, line)
        except Exception:
            pass

    @staticmethod
    def _chat_event(child: Child, raw: str):
        try:
            evt = json.loads(raw)
        except ValueError:
            return
        if not isinstance(evt, dict):
            return
        evt["target"] = child.child_id
        try:
            from app.web.routes.chat_routes import apply_chat_event
            apply_chat_event(child.child_id, evt)
        except Exception:
            pass
        bus.event("chat", evt)

    def _ipc_target(self, child: Child):
        """The IPC name for this child, or None if it has no command channel."""
        if child.role == "discord":
            return child.account or 1
        if child.role in registry.BRIDGED:
            from app.core.ipc import browser_target
            return browser_target(child.role, child.account or 1)
        return None

    def stop(self, child_id: str, graceful_seconds: float = 6.0):
        """Stop a worker, asking it to log out before killing it. terminate() on Windows is TerminateProcess: the worker dies on the spot with its gateway socket still open, so Discord keeps the session alive until the heartbeat times out and the account goes on showing as online for the best part of a minute. The runner already knows how to close the connection properly, so it is asked first and only killed if it will not go."""
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
        """Kill workers left behind by a previous run. A hard kill of the app (Task Manager, crash, power loss) orphans the child processes; they keep the Discord session alive, so the account still shows as connected from the OLD client after a relaunch. Every pid file we find that is not one of our own children gets killed before anything new is spawned."""
        from app.core.ipc import IPC_DIR
        from app.utils import device
        # Accounts on threads leave no processes behind to sweep, and their
        # "pid" is this process's own.
        if device.single_process() or not IPC_DIR.exists():
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
                    # No window: this runs in the windowed app itself, at launch,
                    # after any run that was force-closed, and a console window
                    # flashed up for it every time.
                    from app.utils.procs import quiet_kwargs
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F", "/T"],
                        capture_output=True, timeout=10, **quiet_kwargs(),
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
        try:
            from app.utils import socials
            self._socials_seen = socials.on()
        except Exception:
            self._socials_seen = None
        self._sweep_stale_pids()
        # Before any account opens the database: the one-time change that gives each persona its own pictures and
        # memory runs with nobody else writing, and an old per-account persona setup is brought over.
        try:
            from app.utils import personas
            personas.startup()
        except Exception as e:
            print(f"[Supervisor] Personas could not be set up: {e}", flush=True)
        waiting = self.needs_sign_in()
        for child_id, (role, account, label) in self._planned_children().items():
            with self.lock:
                if child_id not in self.children:
                    self.register(child_id, role, account, label)
                if child_id in waiting:
                    bus.append("supervisor", f"{label} was left stopped: it needs you to sign it in again on "
                                             "Accounts, then start it.", "warn")
                    continue
                self.start(child_id)
        threading.Thread(target=self._watchdog, daemon=True, name="supervisor-watchdog").start()

    def stop_all(self):
        """Stop every worker at once. Asking each in turn would serialise the log-out grace period, so shutting down three accounts would take three times as long; they are independent processes, so they can all be told at the same time."""
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
        """Poll children and schedule restarts. Backoff is tracked as a wake-up deadline rather than a sleep: sleeping here (previously up to 5 minutes, while holding self.lock) froze every start/stop the UI asked for and stopped other children being noticed."""
        while self._running:
            time.sleep(1)
            now = time.time()
            to_relaunch = []
            alerts = []
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
                    # The process is gone; its pid file must not survive to the next app run (a reused pid would be killed by the sweep).
                    clear_pid_file(child.role, child.account)
                    if child._stop_requested:
                        child.state = "stopped"
                        continue
                    if code == NEEDS_SIGN_IN:
                        child._stop_requested = True
                        child.state = "stopped"
                        self._mark_sign_in(child.child_id, True)
                        bus.append("supervisor", f"{child.label} needs you to sign it in again. It was left stopped: "
                                                 "trying again by itself would only log in again and again.", "error")
                        alerts.append((child, f"{child.label} needs you",
                                       "Its login was refused. Sign it in again from Accounts, then start it."))
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
                        alerts.append((child, f"{child.label} stopped",
                                       f"It crashed {child.restarts} times in a row, so it was left stopped. "
                                       f"Start it again from the panel."))
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
                    # Once a streak, on the second crash: one crash can be a blip, two is a pattern.
                    if child.restarts == 2:
                        alerts.append((child, f"{child.label} keeps restarting",
                                       f"It stopped twice (exit code {code}). It is being restarted; the logs say why."))
            for child, title, detail in alerts:
                _alert_crash(child, title, detail)
            for child in to_relaunch:
                with self.lock:
                    if self._running and not child._stop_requested:
                        self._launch(child)

    def planned(self) -> set:
        """Ids of the workers config and credentials say should exist. An account can have credentials and still not be startable: its whole platform can be switched off in Settings. The Accounts page asks, so it can say that instead of offering a Start button that cannot work."""
        try:
            return set(self._planned_children())
        except Exception:
            return set()

    def apply_socials(self) -> dict:
        """A social was switched on or off in Settings, and it counts now rather than at the next launch. Off, its
        accounts stop: the panel shows it nowhere, so nothing of it may go on answering. Switched back on, its
        accounts start as they do when the app opens, except the ones someone had stopped by hand. Only the socials
        whose switch changed: an account added and not started yet is left alone."""
        from app.utils import socials
        on = socials.on()
        before = self._socials_seen or {}
        turned_on = {name for name, now in on.items() if now and before.get(name) is False}

        def social(role, account):
            # The control bot is role "telegram" with no account: not a social, never touched here.
            return role in on and not (role == "telegram" and account is None)

        stopping, starting = [], []
        with self.lock:
            for child_id, child in self.children.items():
                # One waiting to be restarted after a crash too, or the watchdog would bring it back.
                alive = (child.proc and child.proc.poll() is None) or child.state in ("starting", "crashing")
                if social(child.role, child.account) and not on[child.role] and alive:
                    stopping.append(child_id)
            waiting = self.needs_sign_in()
            for child_id, (role, account, label) in self._planned_children().items():
                if not social(role, account) or role not in turned_on or child_id in waiting:
                    continue
                child = self.children.get(child_id)
                if child is None:
                    self.register(child_id, role, account, label)
                    starting.append(child_id)
                elif child_id in self._switched_off and not (child.proc and child.proc.poll() is None):
                    starting.append(child_id)
        # Asking several to log out at once, not one after another (see stop_all).
        threads = [threading.Thread(target=self._stop_quietly, args=(c,), daemon=True, name=f"social-off-{c}")
                   for c in stopping]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self._switched_off.update(stopping)
        for child_id in starting:
            self._switched_off.discard(child_id)
            if self._running:
                self.start(child_id)
        # The control bot counts the accounts it can command as it starts: started again, a social switched off is
        # not among them, and one switched on is.
        changed = bool(before) and on != before
        ctl = self.children.get("telegram")
        if changed and ctl and ctl.account is None and ctl.proc and ctl.proc.poll() is None and self._running:
            threading.Thread(target=self.restart, args=("telegram",), daemon=True, name="restart-controller").start()
        self._socials_seen = on
        if stopping or starting:
            bus.append("supervisor", "Socials switched: " + ", ".join(
                [f"stopped {c}" for c in stopping] + [f"started {c}" for c in starting]))
        return {"stopped": stopping, "started": starting if self._running else []}

    def running_ids(self) -> set:
        """Ids of the workers that are up, or on their way up: the ones a change to their persona has to reach."""
        return {c.child_id for c in self.children.values() if c.state in ("running", "starting", "crashing")}

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
                # Seconds until a crashing worker is tried again, so the panel can say "back in 40s" rather than just "crashing".
                "retry_in": (max(0, round(child._retry_at - time.time()))
                             if child.state == "crashing" else None),
                # Stopped because it crashed too often, not because anyone asked: the one stopped state that needs looking at.
                "gave_up": child.state == "stopped" and child.restarts > MAX_RESTARTS,
            })
        return out
