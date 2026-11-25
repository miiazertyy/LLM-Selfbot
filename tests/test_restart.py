"""Restart starts a real new copy of the app, and the panel waits for that copy (2026-11-08).

The single-file exe started its replacement with its own PyInstaller variables and from inside its unpack folder, so the
replacement ran as one of its workers, out of that folder. Its launcher then deleted the folder: 3,410 files to 0, and
the new app never answered. An in-app update went the same way. The panel also took the old server's answer, while it
was still stopping the accounts, for the new one, and reloaded into a server about to vanish.
"""
import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import use_shipped_config  # noqa: E402

use_shipped_config()

from app.core import update  # noqa: E402
from app.web.routes import system_routes as routes  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


UNPACK = str(ROOT / "made-up-unpack-folder" / "_MEI000034dc2")
INSIDE = str(Path(UNPACK) / "resources" / "bin")
KEPT = str(ROOT / "made-up-tools")

print("== what the new copy starts with ==")
os.environ["PATH"] = INSIDE + os.pathsep + KEPT
os.environ["LLMSELFBOT_CHILD"] = "1"
sys._MEIPASS = UNPACK
env = update.relaunch_env(8823)
check("a new copy with its own unpack folder, not a worker of this one", env.get("PYINSTALLER_RESET_ENVIRONMENT") == "1")
check("it waits for this copy's lock", env.get("LLMSELFBOT_RESTART") == "1")
check("on the same port", env.get("SELFBOT_PORT") == "8823")
check("as the app itself, not a child of it", "LLMSELFBOT_CHILD" not in env)
check("this copy's folder comes off PATH, and only that", env["PATH"] == KEPT, env["PATH"])
del os.environ["LLMSELFBOT_CHILD"]

print("\n== pressing Restart in the exe ==")


class Supervisor:
    port = 8823
    stopped = False

    def stop_all(self):
        Supervisor.stopped = True

    def start_all(self):
        pass


def press(frozen, flags=()):
    """The route, with the launch and the exit swapped for stand-ins. Returns (the answer, what it launched)."""
    seen, done = {}, threading.Event()

    def popen(argv, **kw):
        seen.update(kw, argv=argv, accounts_stopped_first=Supervisor.stopped)
        return SimpleNamespace(pid=1)

    def leave(code):
        seen["exit"] = code
        done.set()
        raise SystemExit     # the real one never returns

    Supervisor.stopped = False
    kept = subprocess.Popen, os._exit, sys.argv, routes.APP_DIR
    subprocess.Popen, os._exit, sys.argv, routes.APP_DIR = popen, leave, ["app", *flags], Path(UNPACK)
    if frozen:
        sys.frozen = True
    try:
        req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(supervisor=Supervisor())),
                              url=SimpleNamespace(port=8823))
        answer = asyncio.run(routes.restart_app(req))
        done.wait(15)
    finally:
        subprocess.Popen, os._exit, sys.argv, routes.APP_DIR = kept
        if frozen:
            del sys.frozen
    return answer, seen


answer, seen = press(frozen=True)
here = Path(sys.executable).resolve().parent
check("the accounts are stopped before the new copy starts", seen.get("accounts_stopped_first") is True, str(seen))
check("it starts the exe", seen.get("argv") == [sys.executable], str(seen.get("argv")))
check("from beside the exe: a program working from the unpack folder stops it being deleted", seen.get("cwd") == str(here),
      str(seen.get("cwd")))
check("with the new copy's environment", seen.get("env", {}).get("PYINSTALLER_RESET_ENVIRONMENT") == "1")
check("and this copy leaves", seen.get("exit") == 0)
check("the panel is told which run it was talking to", answer.get("boot") == routes.BOOT, str(answer))

_, seen = press(frozen=True, flags=["--no-window", "--port", "8823"])
check("started with no window, it comes back with no window", seen.get("argv") == [sys.executable, "--no-window"],
      str(seen.get("argv")))
_, seen = press(frozen=False)
check("from source it runs main.py from the app's folder", seen.get("argv") == [sys.executable, str(Path(UNPACK) / "main.py")]
      and seen.get("cwd") == UNPACK, str(seen))

print("\n== a phone restarts its accounts ==")
os.environ["LLMSELFBOT_INPROCESS"] = "1"
try:
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(supervisor=Supervisor())), url=SimpleNamespace(port=8823))
    phone = asyncio.run(routes.restart_app(req))
finally:
    del os.environ["LLMSELFBOT_INPROCESS"]
check("no new copy there, so nothing for the panel to wait for", phone.get("accounts_only") is True and "boot" not in phone,
      str(phone))

print("\n== the panel ==")
info = asyncio.run(routes.info(SimpleNamespace()))
check("each run of the app says which it is", info.get("boot") == routes.BOOT and len(routes.BOOT) >= 16)
system = read("webui/src/pages/System.svelte")
flow = system.split("async function restartApp")[1].split("async function ignoreUpdate")[0]
check("it reloads only for an answer from a different run", "info && info.boot !== r.boot" in flow)
check("before that it only keeps asking", flow.index("info.boot !== r.boot") < flow.index("location.reload()"))
check("the wait has an end, also when the old copy never leaves", "Date.now() > until" in flow and "} catch {" not in flow)
app = read("webui/src/App.svelte")
check("a page that will not load says so", 'toast("Could not open that page. Try again in a moment.", "err")' in app)

print("\n== the update takes the same road ==")
src = read("app/core/update.py")
check("the exe's update starts the new one with that environment", "cwd=str(exe.parent), env=relaunch_env(port)" in src)
check("and so does the installer's", "cwd=str(setup.parent), env=relaunch_env(port)" in src)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
