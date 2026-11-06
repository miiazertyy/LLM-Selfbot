"""Add a Minecraft account by signing in to Microsoft from the panel, rather than by typing its name.

A Microsoft account already knows its Minecraft name, so asking for one asked the person to type what the sign-in
would tell us, and to get it exactly right: the name is also what the bot files its saved login under, so a name typed
differently meant signing in all over again, and a name that is not the account's own left the card showing the wrong
one. This runs ms_signin.mjs beside mindcraft: Microsoft's own code, typed (or opened with one click) at
microsoft.com/link, then the account's real name. The login it leaves behind is the one the bot finds when it plays.

One sign-in at a time, its state polled by the panel, as tiktok_browser_login.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_key = ""
_state: dict = {"running": False, "state": "idle", "code": "", "link": "", "uri": "", "expires": 0, "reason": ""}
_result: dict | None = None

# Every cache prismarine-auth writes for one login (MicrosoftAuthFlow's CACHE_IDS), named <sha1(key)[:6]>_<id>.
_CACHE_IDS = ("msal", "live", "sisu", "xbl", "bed", "mca", "mcs", "pfb")


def status() -> dict:
    with _lock:
        return dict(_state)


def take_result() -> dict | None:
    """Who signed in, once, then forgotten: {"name", "uuid"}."""
    global _result
    with _lock:
        got, _result = _result, None
        return got


def _set(**fields) -> None:
    with _lock:
        _state.update(fields)


def cache_folder() -> Path:
    """Where mineflayer keeps Microsoft logins: minecraft-folder-path's folder, then nmp-cache, as it works it out."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / ".minecraft"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "minecraft"
    else:
        base = Path.home() / ".minecraft"
    return base / "nmp-cache"


def _clear(key: str) -> None:
    """A sign-in that did not finish leaves a few empty files under its temporary key: they go."""
    if not key:
        return
    stem = hashlib.sha1(key.encode("latin-1", "replace")).hexdigest()[:6]
    for cid in _CACHE_IDS:
        try:
            (cache_folder() / f"{stem}_{cid}-cache.json").unlink(missing_ok=True)
        except OSError:
            pass


def cancel() -> dict:
    global _proc, _key
    with _lock:
        proc, key = _proc, _key
        _proc, _key = None, ""
    if proc and proc.poll() is None:
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:
            pass
    _clear(key)
    _set(running=False, state="idle", code="", link="", uri="", expires=0, reason="")
    return status()


def _requirements(script_name: str = "ms_signin.mjs") -> tuple[str, str, str]:
    """Node, mindcraft's prismarine-auth, and this build's script beside mindcraft: (node, script, "") or why not."""
    node = shutil.which("node")
    if not node:
        return "", "", "Signing in to Microsoft needs Node.js. Install it and reopen the app."
    from app.platforms.minecraft import install, worker
    if not (install.MC_DIR / "node_modules" / "prismarine-auth").is_dir():
        return "", "", "Minecraft is not installed yet. Install it from Settings, Minecraft."
    worker.sync_runner()   # puts this build's scripts beside mindcraft
    script = worker.RUNNER_DIR / script_name
    if not script.is_file():
        return "", "", "The script for it is missing from this build."
    return node, str(script), ""


def start() -> dict:
    """Ask Microsoft for a code. The panel shows it; the person signs in; status() says when, and with what name."""
    global _proc, _key, _result
    with _lock:
        if _state["running"]:
            return dict(_state)
    node, script, problem = _requirements()
    if problem:
        _set(running=False, state="failed", reason=problem)
        return status()
    from app.platforms.minecraft import install
    from app.utils.procs import quiet_kwargs
    key = f"lsbsignin{uuid.uuid4().hex[:10]}"
    env = {**os.environ, "LSB_MC_DIR": str(install.MC_DIR), "LSB_SIGNIN_KEY": key}
    with _lock:
        _result = None
        _key = key
        _state.update(running=True, state="asking", code="", link="", uri="", expires=0, reason="")
    try:
        proc = subprocess.Popen([node, script], cwd=str(install.MC_DIR), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8", errors="replace",
                                **quiet_kwargs())
    except Exception as exc:
        _clear(key)
        _set(running=False, state="failed", reason=f"The sign-in could not start ({type(exc).__name__}).")
        return status()
    with _lock:
        _proc = proc
    threading.Thread(target=_pump, args=(proc, key), daemon=True, name="minecraft-ms-signin").start()
    return status()


def _pump(proc: subprocess.Popen, key: str) -> None:
    """What the script says, as it says it. Only its JSON lines count: anything else is a package talking."""
    global _result, _proc, _key
    finished = False
    for raw in proc.stdout or []:
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("code"):
            _set(state="code", code=str(msg["code"]), link=str(msg.get("link") or ""),
                 uri=str(msg.get("uri") or "https://www.microsoft.com/link"), expires=int(msg.get("expires") or 0))
        elif msg.get("done"):
            from app.platforms.minecraft.profile import clean_name
            name = clean_name(str(msg.get("name") or ""))
            if not name:
                _set(running=False, state="failed", reason="Microsoft gave back a name Minecraft would not take.")
            else:
                with _lock:
                    _result = {"name": name, "uuid": str(msg.get("uuid") or "")}
                _set(running=False, state="done", code="", reason="")
            finished = True
        elif msg.get("error"):
            _set(running=False, state="failed", reason=str(msg["error"])[:300])
            finished = True
    try:
        proc.wait(timeout=10)
    except Exception:
        pass
    if not finished:
        _clear(key)
        _set(running=False, state="failed", reason="The sign-in stopped before it finished. Try again.")
    with _lock:
        if _proc is proc:
            _proc, _key = None, ""
