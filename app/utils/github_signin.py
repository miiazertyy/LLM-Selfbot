"""github_signin.py - signing in with GitHub for community profiles, with a code instead of a password.

GitHub's device flow: the app asks GitHub for a short code, the person types it at github.com/login/device in their
own browser (where they are already signed in), and the app is handed a token. No password ever passes through the
app, and no secret is needed in it: the community's GitHub App only lets that token open requests in the profiles
repo and keep the person's own gists. Nothing else on their GitHub.

The token is kept in config/github_auth.json, never in the environment (the accounts' processes inherit that), never
in a response or a log, and never in a backup. It lasts hours; it is refreshed before it runs out, and if that fails
the person is simply signed out. One sign-in at a time, its state polled by the panel, like the browser sign-ins.
"""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import urlencode

from app.utils import ghhttp

_lock = threading.RLock()
_state: dict = {"state": "idle", "user_code": "", "uri": "", "expires_at": 0.0, "reason": ""}
_gen = 0
_stop = threading.Event()

DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"


def auth_path():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config" / "github_auth.json"


def _load() -> dict:
    try:
        data = json.loads(auth_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    from app.utils.atomic import write_json_atomic
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, data, indent=2)


def me() -> dict:
    """Who is signed in, safe to show: {signed_in, login, id, avatar}. Never the token."""
    data = _load()
    if not data.get("token"):
        return {"signed_in": False, "login": "", "id": 0, "avatar": ""}
    return {"signed_in": True, "login": str(data.get("login") or ""), "id": int(data.get("id") or 0),
            "avatar": str(data.get("avatar") or "")}


def status() -> dict:
    with _lock:
        out = dict(_state)
    out["me"] = me()
    out["left"] = max(0, int(out.get("expires_at", 0) - time.time())) if out["state"] == "waiting" else 0
    return out


def _set(**fields) -> None:
    with _lock:
        _state.update(fields)


def _form(url: str, fields: dict) -> dict:
    r = ghhttp.send("POST", url, headers={"Accept": "application/json",
                                          "Content-Type": "application/x-www-form-urlencoded"},
                    body=urlencode(fields).encode("ascii"), cap=64_000)
    data = r.json()
    if not isinstance(data, dict):
        raise ghhttp.GitHubError("GitHub's answer couldn't be read.", r.status)
    return data


def start(client_id: str) -> dict:
    """A new code to type on GitHub, or the one still waiting. Never raises: a problem becomes the state "failed"."""
    global _gen
    with _lock:
        if _state["state"] == "waiting" and _state["expires_at"] - time.time() > 30:
            return status()
    if not client_id:
        _set(state="failed", reason="Sharing isn't set up yet.", user_code="", uri="", expires_at=0.0)
        return status()
    _set(state="asking", reason="", user_code="", uri="", expires_at=0.0)
    try:
        data = _form(DEVICE_URL, {"client_id": client_id})
    except ghhttp.GitHubError as e:
        _set(state="failed", reason=str(e))
        return status()
    if data.get("error"):
        reason = "Sign-in with a code isn't turned on for this app yet." if data["error"] == "device_flow_disabled" \
            else "GitHub didn't give a code. Try again."
        _set(state="failed", reason=reason)
        return status()
    code, device = str(data.get("user_code") or ""), str(data.get("device_code") or "")
    if not code or not device:
        _set(state="failed", reason="GitHub didn't give a code. Try again.")
        return status()
    interval = max(5, int(data.get("interval") or 5))
    deadline = time.time() + max(60, int(data.get("expires_in") or 900))
    with _lock:
        _gen += 1
        gen = _gen
        _stop.clear()
        _state.update(state="waiting", user_code=code, uri=str(data.get("verification_uri") or
                                                               "https://github.com/login/device"),
                      expires_at=deadline, reason="")
    threading.Thread(target=_poll, args=(gen, client_id, device, interval, deadline), daemon=True,
                     name="github-signin").start()
    return status()


def _poll(gen: int, client_id: str, device: str, interval: int, deadline: float) -> None:
    while time.time() < deadline:
        if _stop.wait(interval) or gen != _gen:
            return
        try:
            data = _form(TOKEN_URL, {"client_id": client_id, "device_code": device,
                                     "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except ghhttp.GitHubError:
            interval = min(interval + 5, 30)
            continue
        if gen != _gen:
            return
        err = data.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval = int(data.get("interval") or interval + 5)
            continue
        if err == "expired_token":
            _set(state="expired", reason="The code ran out. Get a new one.", user_code="")
            return
        if err == "access_denied":
            _set(state="denied", reason="It was turned down on GitHub.", user_code="")
            return
        if err:
            _set(state="failed", reason="GitHub didn't sign you in. Try again.", user_code="")
            return
        token = str(data.get("access_token") or "")
        if not token:
            continue
        try:
            _, user = ghhttp.api("GET", "/user", token=token)
        except ghhttp.GitHubError as e:
            _set(state="failed", reason=str(e), user_code="")
            return
        _keep(client_id, data, user or {})
        _set(state="done", reason="", user_code="")
        return
    if gen == _gen:
        _set(state="expired", reason="The code ran out. Get a new one.", user_code="")


def _keep(client_id: str, data: dict, user: dict) -> None:
    now = time.time()
    old = _load()
    _save({
        "client_id": client_id,
        "token": str(data.get("access_token") or ""),
        "token_expires": now + int(data["expires_in"]) if data.get("expires_in") else 0,
        "refresh": str(data.get("refresh_token") or old.get("refresh") or ""),
        "refresh_expires": now + int(data["refresh_token_expires_in"]) if data.get("refresh_token_expires_in")
        else old.get("refresh_expires", 0),
        "login": str(user.get("login") or old.get("login") or ""),
        "id": int(user.get("id") or old.get("id") or 0),
        "avatar": str(user.get("avatar_url") or old.get("avatar") or ""),
        "saved": now,
    })


def cancel() -> dict:
    global _gen
    with _lock:
        _gen += 1
        _stop.set()
        _state.update(state="idle", user_code="", uri="", expires_at=0.0, reason="")
    return status()


def sign_out() -> dict:
    cancel()
    try:
        auth_path().unlink()
    except OSError:
        pass
    return status()


def token() -> str:
    """A token that works now ("" when signed out), refreshed first when it is about to run out."""
    with _lock:
        data = _load()
        tok = str(data.get("token") or "")
        if not tok:
            return ""
        expires = float(data.get("token_expires") or 0)
        if expires and expires - time.time() < 60:
            return _refresh(data)
        return tok


def _refresh(data: dict) -> str:
    refresh = str(data.get("refresh") or "")
    if not refresh or (data.get("refresh_expires") and float(data["refresh_expires"]) < time.time()):
        sign_out()
        return ""
    try:
        new = _form(TOKEN_URL, {"client_id": data.get("client_id") or "", "grant_type": "refresh_token",
                                "refresh_token": refresh})
    except ghhttp.GitHubError:
        return ""
    if new.get("error") or not new.get("access_token"):
        sign_out()
        return ""
    _keep(str(data.get("client_id") or ""), new, {"login": data.get("login"), "id": data.get("id"),
                                                  "avatar_url": data.get("avatar")})
    return str(new["access_token"])


def on_401() -> str:
    """GitHub said the token is no good: refreshed once, else signed out. The new token, or ""."""
    with _lock:
        data = _load()
        if not data.get("token"):
            return ""
        return _refresh(data)
