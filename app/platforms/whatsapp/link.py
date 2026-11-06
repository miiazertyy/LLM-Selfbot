"""Linking a WhatsApp number, from the Accounts page.

WhatsApp has no password. A number is linked the way a second device is: either WhatsApp gives an eight-digit
code that a person types into WhatsApp on their phone (Linked devices, Link with phone number), or it draws a QR
code that the phone's camera reads. Both end the same way - WhatsApp hands this app a set of keys, and from then
on those keys ARE the login.

Those keys land in config/whatsapp-<number>-auth, which is what whatsapp_runner.js opens, exactly as a browser
profile is what the browser platforms open. Nothing secret is kept beside it in config/.env: the account's one
field is its number.

Shaped like app/platforms/minecraft/ms_signin.py - a Node helper printing JSON lines on stdout, pumped on a
thread into a state dict the panel polls - with Telegram's state vocabulary and its expiry, because a code
WhatsApp gave has only a few minutes in it.

One link at a time, as every other sign-in here is.
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
_scratch: str | None = None
_result: dict | None = None
_state: dict = {"running": False, "state": "idle", "way": "code", "number": "", "code": "", "qr": "",
                "detail": "", "reason": ""}
#: WhatsApp's pairing code is good for a couple of minutes and its QR for twenty seconds at a time; the helper
#: refreshes the QR itself. A link nobody finished is dropped rather than left holding a connection.
GIVE_UP_AFTER = 300.0


def _config_dir():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config"


def clean_number(number) -> str:
    """A phone number as WhatsApp's own ids carry it: digits only, no +, no spaces, country code included. "" when
    it could not be one."""
    n = re.sub(r"\D", "", str(number or ""))
    return n if 7 <= len(n) <= 20 else ""


def auth_dir(number: str):
    """Where a linked account's keys live. whatsapp_runner.js opens this, and it is the whole of the login."""
    return _config_dir() / f"whatsapp-{clean_number(number) or 'unknown'}-auth"


def linked(number: str) -> bool:
    """Whether that number has a session here. Baileys writes creds.json first and always."""
    return (auth_dir(number) / "creds.json").is_file()


def status() -> dict:
    import time
    with _lock:
        out = dict(_state)
    if out["state"] in ("asking", "code", "qr") and time.time() - out.get("at", 0) > GIVE_UP_AFTER:
        return {**out, "running": False, "state": "failed",
                "reason": "It took too long, so WhatsApp's code has expired. Start again."}
    return out


def running() -> bool:
    return status()["state"] in ("asking", "code", "qr")


def take_login() -> dict | None:
    """The finished link, handed over once: the number it turned out to be, and the name on it."""
    global _result
    with _lock:
        got, _result = _result, None
    if got:
        _set(running=False, state="idle", code="", qr="", number="", detail="", reason="")
    return got


def _set(**fields) -> None:
    import time
    with _lock:
        _state.update(fields)
        _state["at"] = time.time()


def _drop_scratch() -> None:
    global _scratch
    with _lock:
        path, _scratch = _scratch, None
    if path:
        shutil.rmtree(path, ignore_errors=True)


def _sweep_unfinished() -> None:
    """Keys from links that never finished (cancelled, the app closed mid-way)."""
    try:
        for p in _config_dir().glob("whatsapp-link-*-auth"):
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
    _drop_scratch()
    _set(running=False, state="idle", code="", qr="", number="", detail="", reason="")
    return status()


def _requirements() -> tuple[str, str, str]:
    node = shutil.which("node")
    if not node:
        return "", "", "Linking WhatsApp needs Node.js. Install it and reopen the app."
    from app.platforms.snapchat_bridge import _sync_node_runner
    runner_dir = _sync_node_runner()
    script = os.path.join(runner_dir, "whatsapp_link.js")
    if not os.path.isdir(os.path.join(runner_dir, "node_modules", "baileys")):
        return "", "", "WhatsApp's package is not installed yet. Install it from Settings > WhatsApp."
    if not os.path.exists(script):
        return "", "", "The linking script is missing from this build."
    return node, script, ""


def start(number: str = "", way: str = "code", timeout_ms: int = 300_000, proxy: str = "") -> dict:
    """Ask WhatsApp to link this app as a device. `way` is "code" (an eight-digit code for a number) or "qr"."""
    global _proc, _result, _scratch
    if running():
        return status()
    way = "qr" if str(way).lower() == "qr" else "code"
    num = clean_number(number)
    if way == "code" and not num:
        return {**status(), "state": "failed",
                "reason": "That is not a phone number. It needs its country code and no symbols."}
    node, script, problem = _requirements()
    if problem:
        _set(running=False, state="failed", detail="", reason=problem, way=way)
        return status()

    from app.utils.paths import DATA_DIR
    from app.utils.procs import quiet_kwargs

    _sweep_unfinished()
    scratch = _config_dir() / f"whatsapp-link-{uuid.uuid4().hex[:8]}-auth"
    scratch.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SNAP_DATA_DIR": str(DATA_DIR), "WHATSAPP_DATA_DIR": str(DATA_DIR),
           "WHATSAPP_LINK_AUTH": str(scratch), "WHATSAPP_LINK_WAY": way,
           "WHATSAPP_LINK_NUMBER": num, "WHATSAPP_LINK_TIMEOUT_MS": str(int(timeout_ms)), "WHATSAPP_PROXY": str(proxy or "")}

    with _lock:
        _result = None
        _scratch = str(scratch)
        _state.update(running=True, state="asking", way=way, number=num, code="", qr="",
                      detail="Asking WhatsApp" if way == "code" else "Asking WhatsApp for a QR code", reason="")
    _set()
    try:
        proc = subprocess.Popen([node, script], cwd=os.path.dirname(script), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8",
                                errors="replace", **quiet_kwargs())
    except Exception as exc:
        _drop_scratch()
        _set(running=False, state="failed", reason=f"Could not start it ({type(exc).__name__}).")
        return status()
    with _lock:
        _proc = proc
    threading.Thread(target=_pump, args=(proc,), daemon=True, name="whatsapp-link").start()
    return status()


def _file_keys(number: str) -> bool:
    """The keys WhatsApp just handed over, filed under the number they belong to. Linking the same number again
    replaces what was there: the newer session is the one that works."""
    global _scratch
    with _lock:
        src = _scratch
    if not src:
        return False
    dst = auth_dir(number)
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
        _scratch = None
    return True


def _pump(proc: subprocess.Popen) -> None:
    """What the helper says, as it says it. Only its JSON lines count: anything else is a package talking."""
    global _result
    done = None
    for raw in proc.stdout or []:
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("code"):
            _set(state="code", code=str(msg["code"])[:12],
                 detail="Type this into WhatsApp on the phone: Linked devices, Link with phone number.")
        elif msg.get("qr"):
            _set(state="qr", qr=str(msg["qr"])[:4000],
                 detail="Scan this with the phone: WhatsApp, Linked devices, Link a device.")
        elif msg.get("linked"):
            done = msg
        elif msg.get("error"):
            _set(running=False, state="failed", reason=str(msg["error"])[:300])
            break
        elif msg.get("detail"):
            _set(detail=str(msg["detail"])[:200])
    try:
        proc.wait(timeout=20)          # it closes the connection as it goes, before the keys are moved
    except Exception:
        pass
    number = clean_number((done or {}).get("number"))
    if done and number:
        if _file_keys(number):
            with _lock:
                _result = {"number": number, "name": str(done.get("name") or "")[:80]}
            _set(running=False, state="linked", code="", qr="", number=number,
                 detail=f"Linked as {done.get('name') or number}.", reason="")
            return
        _drop_scratch()
        _set(running=False, state="failed", reason="WhatsApp linked it, but its keys could not be kept.")
        return
    _drop_scratch()
    if status()["state"] != "failed":
        _set(running=False, state="failed",
             reason=str((done or {}).get("error") or "It stopped before the link was finished."))
