"""Add a Discord account by signing in, in a real browser, instead of handing the app a password.

The password route (utils/discord_login) posts straight to Discord's login API.
It works when it works, but Discord answers a large share of real logins with a
captcha, a new-device email check, or a passkey prompt, and a script can answer
none of those - each one ends at "go and paste a token instead". So this opens
the browser the machine already has, at discord.com/login, and lets the person
sign in the way they always do. Whatever Discord asks for, they answer it.

The app never sees the password. It reads the token out of the Authorization
header the signed-in client sends, and stores it exactly where a pasted token
would have gone.

One process at a time, with its state polled by the panel: the browser window
is the interface, and there is no sense in opening two.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
# The browser profile for the run in progress. Python makes it and Python
# removes it: cancelling kills the Node process, so anything the script tidied
# up on its own way out would survive every cancel.
_profile: str | None = None
_PROFILE_PREFIX = "llmselfbot-login-"

# What the panel polls. `token` never leaves this module: the route reads it
# through take_token() and writes it to .env, and nothing puts it in a response.
_state: dict = {
    "running": False,
    "state": "idle",      # idle | opening | waiting | done | failed
    "detail": "",
    "reason": "",
}
_token: str | None = None


def status() -> dict:
    """The current state, safe to send to the page (never the token)."""
    with _lock:
        return dict(_state)


def take_token() -> str | None:
    """Read the captured token once, and forget it."""
    global _token
    with _lock:
        token, _token = _token, None
        return token


def _set(**fields) -> None:
    with _lock:
        _state.update(fields)


def _drop_profile() -> None:
    """Remove the browser profile for the run that just ended."""
    global _profile
    with _lock:
        path, _profile = _profile, None
    if path:
        shutil.rmtree(path, ignore_errors=True)


def _sweep_old_profiles() -> None:
    """Clear profiles a previous run was killed before it could finish with. Best effort: one still in use simply refuses to go, which is fine."""
    root = tempfile.gettempdir()
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if name.startswith(_PROFILE_PREFIX):
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def cancel() -> dict:
    """Close the browser and give up on this login."""
    global _proc
    with _lock:
        proc = _proc
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)      # so the profile is no longer locked
        except Exception:
            pass
    _drop_profile()
    _set(running=False, state="idle", detail="", reason="")
    return status()


def _requirements() -> tuple[str, str, str]:
    """(node, script, reason). reason is non-empty when it cannot run."""
    import shutil

    from app.platforms.snapchat_bridge import _sync_node_runner

    node = shutil.which("node")
    if not node:
        return "", "", ("Signing in through the browser needs Node.js. Install it, reopen the "
                        "app, or paste a token instead.")
    runner_dir = _sync_node_runner()
    script = os.path.join(runner_dir, "discord_token.js")
    if not os.path.isdir(os.path.join(runner_dir, "node_modules")):
        return "", "", ("The browser packages are not installed yet. Install them from "
                        "Settings > Snapchat, or paste a token instead.")
    if not os.path.exists(script):
        return "", "", "The login script is missing from this build."
    return node, script, ""


def start(proxy: str | None = None, timeout_ms: int = 600_000) -> dict:
    """Open the browser and begin waiting for a sign-in. Returns the first state."""
    global _proc, _token

    with _lock:
        if _state["running"]:
            return dict(_state)

    node, script, problem = _requirements()
    if problem:
        _set(running=False, state="failed", detail="", reason=problem)
        return status()

    from app.utils.procs import quiet_kwargs
    from app.utils.paths import DATA_DIR
    from app.web.routes.system_routes import installed_browser

    _sweep_old_profiles()
    profile = tempfile.mkdtemp(prefix=_PROFILE_PREFIX)
    env = {**os.environ,
           "SNAP_DATA_DIR": str(DATA_DIR),
           "DISCORD_LOGIN_PROFILE": profile,
           "DISCORD_LOGIN_TIMEOUT_MS": str(int(timeout_ms))}
    if proxy:
        env["DISCORD_LOGIN_PROXY"] = proxy
    # The browser this machine already has, same as the Snapchat runner uses.
    _, browser_path = installed_browser()
    if browser_path and "PUPPETEER_EXECUTABLE_PATH" not in os.environ:
        env["PUPPETEER_EXECUTABLE_PATH"] = browser_path

    global _profile
    with _lock:
        _token = None
        _profile = profile
        _state.update(running=True, state="opening",
                      detail="Starting the browser", reason="")

    try:
        proc = subprocess.Popen(
            [node, script], cwd=os.path.dirname(script), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            **quiet_kwargs(),
        )
    except Exception as exc:
        _drop_profile()
        _set(running=False, state="failed", detail="",
             reason=f"Could not start the browser ({type(exc).__name__}).")
        return status()

    with _lock:
        _proc = proc
    threading.Thread(target=_pump, args=(proc,), daemon=True,
                     name="discord-browser-login").start()
    return status()


def _pump(proc: subprocess.Popen) -> None:
    """Read the script's JSON lines until it finishes."""
    global _token
    saw_result = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue                      # a stray console line from a dependency
            if not isinstance(msg, dict):
                continue
            if "ok" in msg:
                saw_result = True
                if msg.get("ok") and msg.get("token"):
                    with _lock:
                        _token = str(msg["token"])
                    _set(running=False, state="done",
                         detail="Signed in", reason="")
                else:
                    _set(running=False, state="failed", detail="",
                         reason=str(msg.get("reason") or "The login did not finish."))
            elif msg.get("state"):
                _set(state=str(msg["state"]), detail=str(msg.get("detail") or ""))
    except Exception:
        pass
    finally:
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        _drop_profile()
        if not saw_result:
            _set(running=False, state="failed", detail="",
                 reason="The browser closed without finishing the login.")
