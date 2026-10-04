"""app/core/inprocess.py - accounts on threads, where they cannot have processes.

Everywhere else each account is a process of its own, started by running this
same app again with --role. A phone allows neither half of that: iOS never lets
an app start another process, and the Android app has no Python to start. So
there each account runs on a thread of the app instead, and ThreadRole makes
that thread look enough like the subprocess.Popen the supervisor already
handles (pid, poll, wait, terminate, kill, and stdout as lines) that nothing
else needs to know which kind it has.

What a role prints goes to its own stdout, told apart by the thread it runs on
(and, for the work it hands to other threads, the context it hands with it);
everything else still reaches the real stdout.

Discord keeps its account in module state, one bot per module, so this way
only one Discord account runs at a time (see Supervisor._planned_children).
"""

import asyncio
import contextvars
import ctypes
import io
import os
import queue
import subprocess
import sys
import threading
import traceback

_current: contextvars.ContextVar = contextvars.ContextVar("llmselfbot_role", default=None)
_by_thread: dict[int, "ThreadRole"] = {}
_router_lock = threading.Lock()
_routed = False


class _Router(io.TextIOBase):
    """sys.stdout and sys.stderr while roles run on threads."""

    def __init__(self, real):
        super().__init__()
        self._real = real

    @staticmethod
    def _role():
        return _current.get() or _by_thread.get(threading.get_ident())

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        role = self._role()
        if role is not None:
            role._feed(text)
            return len(text)
        if self._real is None:
            return len(text)
        return self._real.write(text)

    def flush(self):
        try:
            if self._real is not None:
                self._real.flush()
        except Exception:
            pass

    def writable(self):
        return True

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"

    def fileno(self):
        if self._real is None:
            raise io.UnsupportedOperation("fileno")
        return self._real.fileno()


def _route_output():
    global _routed
    with _router_lock:
        if _routed:
            return
        sys.stdout = _Router(sys.stdout)
        sys.stderr = _Router(sys.stderr)
        _routed = True


class _Lines:
    """A role's output, a line at a time, ending when the role does."""

    def __init__(self, q: queue.Queue):
        self._q = q

    def __iter__(self):
        return self

    def __next__(self):
        line = self._q.get()
        if line is None:
            raise StopIteration
        return line

    def close(self):
        pass


class ThreadRole:
    """One role on a thread, shaped like the subprocess.Popen it stands in for."""

    def __init__(self, role: str, account, target):
        self.args = [role, account]
        self.role = role
        self.account = account
        # Its "process" is this one. Nothing may kill by this number: the
        # supervisor does not, and ThreadRole writes no pid file for it.
        self.pid = os.getpid()
        self.returncode = None
        self._q: queue.Queue = queue.Queue()
        self._buf = ""
        self._buf_lock = threading.Lock()
        self.stdout = _Lines(self._q)
        self._done = threading.Event()
        self._loop = None
        _route_output()
        self._thread = threading.Thread(target=self._run, args=(target,), daemon=True,
                                        name=f"role-{role}-{account or 0}")
        self._thread.start()

    # ── Output ───────────────────────────────────────────────────────────────
    def _feed(self, text: str):
        with self._buf_lock:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._q.put(line + "\n")

    # ── Running ──────────────────────────────────────────────────────────────
    def _run(self, target):
        ident = threading.get_ident()
        _by_thread[ident] = self
        _current.set(self)
        code = 0
        try:
            target()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except BaseException:
            traceback.print_exc()
            code = 1
        finally:
            with self._buf_lock:
                if self._buf:
                    self._q.put(self._buf + "\n")
                    self._buf = ""
            self.returncode = code
            _by_thread.pop(ident, None)
            self._q.put(None)
            self._done.set()

    def adopt_loop(self, loop):
        """The role's event loop, so stopping it can wake the loop up."""
        self._loop = loop

    # ── The Popen half ───────────────────────────────────────────────────────
    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def terminate(self):
        """Stop it: raise SystemExit on its thread, and wake its loop to see it."""
        if self._done.is_set():
            return
        ident = self._thread.ident
        if ident is not None:
            try:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), ctypes.py_object(SystemExit))
            except Exception:
                pass
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(lambda: None)
            except Exception:
                pass

    kill = terminate


# ── Starting one ─────────────────────────────────────────────────────────────

# What a role shares with the panel around it. Everything else of the app's
# own is loaded afresh for each start, as it would be in a process of its own:
# the modules keep an account's state (its bot, its API clients and their
# connections, bound to the event loop they were made on), and a restarted
# account reusing the stopped one's found them tied to a loop that was closed.
_SHARED = ("app.core", "app.web", "app.cli", "app.version", "app._build",
           "app.utils.paths", "app.utils.device", "app.utils.compat",
           "app.utils.procs", "app.utils.binaries")


def _fresh():
    for name in list(sys.modules):
        if name.startswith("app.") and not any(name == s or name.startswith(s + ".") for s in _SHARED):
            del sys.modules[name]


def _discord(account):
    def target():
        os.environ["DISCORD_ACCOUNT_INDEX"] = str(account or 1)
        _fresh()
        from app.platforms import discord_runner
        discord_runner.run_discord_role(account or 1)
    return target


def _telegram():
    def target():
        # A thread has no event loop of its own until it is given one, and
        # python-telegram-bot asks for the current one.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        role = _current.get()
        if role is not None:
            role.adopt_loop(loop)
        _fresh()
        from app.telegram_bot import telegram_controller
        telegram_controller.main()
    return target


def start(role: str, account=None) -> ThreadRole:
    """Start `role` on a thread. Snapchat drives Chrome through Node, which a
    phone has neither of, so it is refused rather than attempted."""
    if role == "discord":
        return ThreadRole(role, account, _discord(account))
    if role == "telegram":
        return ThreadRole(role, account, _telegram())
    raise RuntimeError(f"{role} can't run inside the app on this device")


def loop_factory(base=None):
    """An event loop factory that tells the role's ThreadRole about its loop.

    `base` is what the role would otherwise use (None for asyncio's default).
    Outside a ThreadRole it is handed back unchanged.
    """
    if _current.get() is None:
        return base

    def make():
        loop = base() if base is not None else asyncio.new_event_loop()
        role = _current.get()
        if role is not None:
            role.adopt_loop(loop)
        return loop
    return make


def current():
    """The ThreadRole this code runs under, or None."""
    return _current.get()


def role_here():
    """The ThreadRole this code runs for: the one handed along with the work, else the one whose thread this is.
    None in the app's own code (the panel)."""
    return _current.get() or _by_thread.get(threading.get_ident())
