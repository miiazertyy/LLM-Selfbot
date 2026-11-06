"""Add a TikTok account by signing in, in a real browser window.

TikTok has no login a script can use: its own page asks for a QR code from the
phone, a password with a puzzle after it, or Google. So this opens Chrome at
tiktok.com/login, on a fresh profile, and the person signs in there however they
like (app/platforms/snapchat/tiktok_login.js). The app never sees a password.

The session TikTok gives that window stays in its profile, and the account runs
in that same profile from then on: once the script says which account signed in,
the profile is filed as config/tiktok-<handle>-profile, before the panel is told
"done", so the account's runner never starts on a profile that is not there yet.

One sign-in at a time, its state polled by the panel, as discord_browser_login.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import uuid

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_profile: str | None = None
_state: dict = {"running": False, "state": "idle", "detail": "", "reason": ""}
_handle: str | None = None


def _config_dir():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config"


# TikTok's own rule for a username: 2 to 24 letters, digits, underscores and dots. What the page said is checked
# against it before it names a folder or a slot.
HANDLE = re.compile(r"^[a-z0-9_.]{2,24}$")


def clean_handle(handle) -> str:
    """The @handle as stored and as its profile is named, or "" when it is not one TikTok could have given."""
    h = str(handle or "").strip().lstrip("@").lower()
    return h if HANDLE.match(h) and h.strip(".") else ""


def profile_dir(handle: str):
    """Where an account's browser profile lives, by its @handle (what tiktok_runner.js opens)."""
    return _config_dir() / f"tiktok-{clean_handle(handle) or 'unknown'}-profile"


def status() -> dict:
    with _lock:
        return dict(_state)


def take_handle() -> str | None:
    """The account that signed in, once, then forgotten."""
    global _handle
    with _lock:
        handle, _handle = _handle, None
        return handle


def _set(**fields) -> None:
    with _lock:
        _state.update(fields)


def _drop_profile() -> None:
    global _profile
    with _lock:
        path, _profile = _profile, None
    if path:
        shutil.rmtree(path, ignore_errors=True)


def _sweep_unfinished() -> None:
    """Profiles of sign-ins that never finished (cancelled, the app closed mid-way)."""
    root = _config_dir()
    try:
        for p in root.glob("tiktok-signin-*-profile"):
            shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def cancel() -> dict:
    global _proc
    with _lock:
        proc = _proc
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
    _drop_profile()
    _set(running=False, state="idle", detail="", reason="")
    return status()


def _requirements() -> tuple[str, str, str]:
    node = shutil.which("node")
    if not node:
        return "", "", "Signing in to TikTok needs Node.js. Install it and reopen the app."
    from app.platforms.snapchat_bridge import _sync_node_runner
    runner_dir = _sync_node_runner()
    script = os.path.join(runner_dir, "tiktok_login.js")
    if not os.path.isdir(os.path.join(runner_dir, "node_modules")):
        return "", "", "The browser packages are not installed yet. Install them from Settings > TikTok."
    if not os.path.exists(script):
        return "", "", "The sign-in script is missing from this build."
    return node, script, ""


def start(timeout_ms: int = 900_000, proxy: str = "") -> dict:
    """Open the window and wait for a sign-in, through the account's proxy if it has one. Returns the first state."""
    global _proc, _handle, _profile
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

    _sweep_unfinished()
    profile = _config_dir() / f"tiktok-signin-{uuid.uuid4().hex[:8]}-profile"
    profile.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SNAP_DATA_DIR": str(DATA_DIR), "TIKTOK_LOGIN_PROFILE": str(profile),
           "TIKTOK_LOGIN_TIMEOUT_MS": str(int(timeout_ms)), "LOGIN_PROXY": str(proxy or "")}
    try:
        from app.utils.helpers import load_config
        loc = ((load_config() or {}).get("bot") or {}).get("locale")
        if loc:
            env["TIKTOK_LOCALE"] = str(loc)
    except Exception:
        pass
    _, browser_path = installed_browser()
    if browser_path and "PUPPETEER_EXECUTABLE_PATH" not in os.environ:
        env["PUPPETEER_EXECUTABLE_PATH"] = browser_path

    with _lock:
        _handle = None
        _profile = str(profile)
        _state.update(running=True, state="opening", detail="Starting the browser", reason="")
    try:
        proc = subprocess.Popen([node, script], cwd=os.path.dirname(script), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8", errors="replace",
                                **quiet_kwargs())
    except Exception as exc:
        _drop_profile()
        _set(running=False, state="failed", detail="", reason=f"Could not start the browser ({type(exc).__name__}).")
        return status()
    with _lock:
        _proc = proc
    threading.Thread(target=_pump, args=(proc,), daemon=True, name="tiktok-browser-login").start()
    return status()


def _file_profile(handle: str) -> bool:
    """The signed-in profile, filed under the account's handle. An earlier profile of the same account (signed in
    again) is replaced: the new session is the one that works."""
    global _profile
    with _lock:
        src = _profile
    if not src:
        return False
    dst = profile_dir(handle)
    try:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        os.replace(src, dst)
    except OSError:
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            shutil.rmtree(src, ignore_errors=True)
        except OSError:
            return False
    with _lock:
        _profile = None
    return True


def _pump(proc: subprocess.Popen) -> None:
    global _handle
    result = None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if "ok" in msg:
                result = msg
            elif msg.get("state"):
                _set(state=str(msg["state"]), detail=str(msg.get("detail") or ""))
    except Exception:
        pass
    try:
        proc.wait(timeout=20)              # Chrome closed and the profile let go of, before it is moved
    except Exception:
        pass
    handle = clean_handle((result or {}).get("handle"))
    if result and result.get("ok") and handle:
        if _file_profile(handle):
            with _lock:
                _handle = handle
            _set(running=False, state="done", detail=f"Signed in as @{handle}", reason="")
            return
        _drop_profile()
        _set(running=False, state="failed", detail="", reason="Signed in, but the browser profile could not be kept.")
        return
    _drop_profile()
    _set(running=False, state="failed", detail="",
         reason=str((result or {}).get("reason") or "The browser closed without finishing the sign-in."))
