"""Add an account by signing in yourself, in a real browser window.

This is TikTok's way of signing in (app/utils/tiktok_browser_login.py), made to
serve the other browser platforms too. A window opens on the site's own login
page, on a fresh profile, and the person signs in there however they like: a
password, a code, a passkey, Google, Apple, whatever check the site puts up. The
app never sees a password, and nothing it does looks like a script logging in,
which is what every one of these sites watches for.

The session the site gives that window stays in its profile, and the account
runs in that same profile from then on: once the script says which account
signed in, the profile is filed as config/<platform>-<name>-profile, before the
panel is told "done", so the account's runner never starts on a profile that is
not there yet.

One sign-in at a time per platform, its state polled by the panel, as
discord_browser_login and tiktok_browser_login are. The per-platform modules
(reddit_signin, x_signin, instagram_signin) each hold one of these and add
whatever else that platform needs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from typing import Callable


def _config_dir():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config"


class Flow:
    """One platform's sign-in window: start it, ask where it has got to, take the name it signed in as."""

    def __init__(self, platform: str, name: str, script: str, clean: Callable[[object], str],
                 env: str = "", settings_tab: str = ""):
        #: "reddit" - names the profile folders and the scratch ones.
        self.platform = platform
        #: "Reddit" - how it is spoken of in a message to the person.
        self.name = name
        #: "reddit_login.js", beside the other runners.
        self.script = script
        #: The platform's own rule for a username, which says what a folder may be called.
        self.clean = clean
        #: "REDDIT" - the prefix on the environment the script reads.
        self.env = env or platform.upper()
        #: Where the panel sends someone whose browser packages are missing.
        self.settings_tab = settings_tab or name
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._profile: str | None = None
        self._handle: str | None = None
        self._state: dict = {"running": False, "state": "idle", "detail": "", "reason": ""}

    # ── Where an account's session lives ─────────────────────────────────────
    def profile_dir(self, handle: str):
        """An account's browser profile, by the name it signed in as (what its runner opens)."""
        return _config_dir() / f"{self.platform}-{self.clean(handle) or 'unknown'}-profile"

    def drop_profile_of(self, handle: str) -> None:
        """Forget an account's session, when the account itself is removed."""
        if self.clean(handle):
            shutil.rmtree(self.profile_dir(handle), ignore_errors=True)

    # ── What the panel asks ──────────────────────────────────────────────────
    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def running(self) -> bool:
        with self._lock:
            return bool(self._state["running"])

    def take_handle(self) -> str | None:
        """The account that signed in, once, then forgotten."""
        with self._lock:
            handle, self._handle = self._handle, None
            return handle

    def _set(self, **fields) -> None:
        with self._lock:
            self._state.update(fields)

    def _drop_scratch(self) -> None:
        with self._lock:
            path, self._profile = self._profile, None
        if path:
            shutil.rmtree(path, ignore_errors=True)

    def _sweep_unfinished(self) -> None:
        """Profiles of sign-ins that never finished (cancelled, the app closed mid-way)."""
        try:
            for p in _config_dir().glob(f"{self.platform}-signin-*-profile"):
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass

    def cancel(self) -> dict:
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
        self._drop_scratch()
        self._set(running=False, state="idle", detail="", reason="")
        return self.status()

    def _requirements(self) -> tuple[str, str, str]:
        node = shutil.which("node")
        if not node:
            return "", "", f"Signing in to {self.name} needs Node.js. Install it and reopen the app."
        from app.platforms.snapchat_bridge import _sync_node_runner
        runner_dir = _sync_node_runner()
        script = os.path.join(runner_dir, self.script)
        if not os.path.isdir(os.path.join(runner_dir, "node_modules")):
            return "", "", f"The browser packages are not installed yet. Install them from Settings > {self.settings_tab}."
        if not os.path.exists(script):
            return "", "", "The sign-in script is missing from this build."
        return node, script, ""

    # ── Opening the window ───────────────────────────────────────────────────
    def start(self, timeout_ms: int = 900_000, extra_env: dict | None = None) -> dict:
        """Open the window and wait for a sign-in. Returns the first state."""
        with self._lock:
            if self._state["running"]:
                return dict(self._state)
        node, script, problem = self._requirements()
        if problem:
            self._set(running=False, state="failed", detail="", reason=problem)
            return self.status()

        from app.utils.paths import DATA_DIR
        from app.utils.procs import quiet_kwargs
        from app.web.routes.system_routes import installed_browser

        self._sweep_unfinished()
        profile = _config_dir() / f"{self.platform}-signin-{uuid.uuid4().hex[:8]}-profile"
        profile.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "SNAP_DATA_DIR": str(DATA_DIR),
               f"{self.env}_LOGIN_PROFILE": str(profile),
               f"{self.env}_LOGIN_TIMEOUT_MS": str(int(timeout_ms)),
               **(extra_env or {})}
        try:
            from app.utils.helpers import load_config
            loc = ((load_config() or {}).get("bot") or {}).get("locale")
            if loc:
                env[f"{self.env}_LOCALE"] = str(loc)
        except Exception:
            pass
        _, browser_path = installed_browser()
        if browser_path and "PUPPETEER_EXECUTABLE_PATH" not in os.environ:
            env["PUPPETEER_EXECUTABLE_PATH"] = browser_path

        with self._lock:
            self._handle = None
            self._profile = str(profile)
            self._state.update(running=True, state="opening", detail="Starting the browser", reason="")
        try:
            proc = subprocess.Popen([node, script], cwd=os.path.dirname(script), env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8",
                                    errors="replace", **quiet_kwargs())
        except Exception as exc:
            self._drop_scratch()
            self._set(running=False, state="failed", detail="",
                      reason=f"Could not start the browser ({type(exc).__name__}).")
            return self.status()
        with self._lock:
            self._proc = proc
        threading.Thread(target=self._pump, args=(proc,), daemon=True,
                         name=f"{self.platform}-browser-login").start()
        return self.status()

    def _file_profile(self, handle: str) -> bool:
        """The signed-in profile, filed under the account's name. An earlier profile of the same account (signed in
        again) is replaced: the new session is the one that works."""
        with self._lock:
            src = self._profile
        if not src:
            return False
        dst = self.profile_dir(handle)
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
        with self._lock:
            self._profile = None
        return True

    def _pump(self, proc: subprocess.Popen) -> None:
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
                    self._set(state=str(msg["state"]), detail=str(msg.get("detail") or ""))
        except Exception:
            pass
        try:
            proc.wait(timeout=20)          # the browser closed and the profile let go of, before it is moved
        except Exception:
            pass
        handle = self.clean((result or {}).get("handle"))
        if result and result.get("ok") and handle:
            if self._file_profile(handle):
                with self._lock:
                    self._handle = handle
                self._set(running=False, state="done", detail=f"Signed in as {handle}", reason="")
                return
            self._drop_scratch()
            self._set(running=False, state="failed", detail="",
                      reason="Signed in, but the browser profile could not be kept.")
            return
        self._drop_scratch()
        self._set(running=False, state="failed", detail="",
                  reason=str((result or {}).get("reason")
                             or "The browser closed without finishing the sign-in."))
