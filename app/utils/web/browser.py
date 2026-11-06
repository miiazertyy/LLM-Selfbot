"""
A Chrome of its own, for the web: Google asked like a person asks it, pages that need JavaScript, clicking around, a
look at the screen.

It is app/platforms/snapchat/webbrowser.js, run with Node beside the Puppeteer the Snapchat install put there (Node
looks for node_modules beside the script; _sync_node_runner keeps a copy of it there). One per process, started the
first time a lookup needs it, gone after a few minutes with nothing to do. Its window is off the screen and out of
the taskbar, as a hidden account's is, and it has a profile of its own (DATA_DIR/web/profile-<account>): never an
account's, which is signed in to something.

Python talks to it in lines of JSON, one question and one answer each, through a plain Popen and a reader thread:
an asyncio subprocess is not available on every event loop the runners use. Each lookup gets a tab of its own.
Without Node, without the packages, or with a Chrome that will not start, session() hands back the plain one
(agent.PlainSession) and everything still works, plainer.
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import json
import os
import shutil
import subprocess
import threading
import time

from app.utils.web import guard
from app.utils.web import page as pagemod

SCRIPT = "webbrowser.js"
START_TIMEOUT = 45.0
CALL_TIMEOUT = 30.0
# After a Chrome that would not start: plain pages only, for this long.
COOL_DOWN = 600.0

_helper = None
_lock = threading.Lock()
_broken_until = 0.0


def _owner() -> str:
    try:
        from app.utils import personas
        return personas.current_account() or "app"
    except Exception:
        return "app"


def requirements() -> tuple:
    """(node, folder of the script, why not). The last is "" when it can run."""
    node = shutil.which("node")
    if not node:
        return "", "", "Node.js is not installed"
    try:
        from app.platforms.snapchat_bridge import _sync_node_runner
        folder = _sync_node_runner()
    except Exception as e:
        return "", "", f"the browser files could not be set up ({e})"
    if not os.path.isdir(os.path.join(folder, "node_modules", "puppeteer-extra")):
        return "", "", "the browser packages are not installed (Settings, Snapchat, Install)"
    if not os.path.isfile(os.path.join(folder, SCRIPT)):
        return "", "", f"{SCRIPT} is missing"
    return node, folder, ""


class _Helper:
    """The Node process, and the questions waiting for its answers."""

    def __init__(self, node: str, folder: str):
        from app.utils.paths import DATA_DIR
        profile = DATA_DIR / "web" / f"profile-{_owner()}"
        profile.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "LLMSELFBOT_WEB_PROFILE": str(profile)}
        # The Chrome or Edge this computer already has, as the Snapchat runner drives (snapchat_bridge): Puppeteer
        # reads the variable itself, and falls back to its own download without it.
        try:
            from app.web.routes.system_routes import installed_browser
            exe = installed_browser()[1]
            if exe and "PUPPETEER_EXECUTABLE_PATH" not in env:
                env["PUPPETEER_EXECUTABLE_PATH"] = exe
        except Exception:
            pass
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            [node, os.path.join(folder, SCRIPT)], cwd=folder, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
        self.pending: dict = {}
        self.ids = itertools.count(1)
        self.write_lock = threading.Lock()
        self.last_err: list = []
        threading.Thread(target=self._read, daemon=True, name="web-browser-out").start()
        threading.Thread(target=self._read_err, daemon=True, name="web-browser-err").start()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            waiter = self.pending.pop(msg.get("id"), None)
            if waiter:
                loop, fut = waiter
                loop.call_soon_threadsafe(lambda f=fut, m=msg: f.done() or f.set_result(m))
        # The process is gone: nobody waits for an answer that will not come.
        for loop, fut in list(self.pending.values()):
            loop.call_soon_threadsafe(lambda f=fut: f.done() or f.set_result({"ok": False, "error": "the browser closed"}))
        self.pending.clear()

    def _read_err(self):
        for line in self.proc.stderr:
            line = line.rstrip()
            if line:
                self.last_err = (self.last_err + [line])[-12:]

    async def call(self, cmd: str, timeout: float = CALL_TIMEOUT, **args) -> dict:
        if not self.alive():
            return {"ok": False, "error": "the browser closed"}
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        n = next(self.ids)
        self.pending[n] = (loop, fut)
        try:
            with self.write_lock:
                self.proc.stdin.write(json.dumps({"id": n, "cmd": cmd, **args}) + "\n")
                self.proc.stdin.flush()
        except Exception as e:
            self.pending.pop(n, None)
            return {"ok": False, "error": f"the browser could not be asked ({type(e).__name__})"}
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.pending.pop(n, None)
            return {"ok": False, "error": "the browser took too long"}

    def stop(self):
        try:
            self.proc.kill()
        except Exception:
            pass


async def _get_helper():
    """The helper, started if need be; None when it cannot run."""
    global _helper, _broken_until
    if time.time() < _broken_until:
        return None
    with _lock:
        if _helper is not None and _helper.alive():
            return _helper
        node, folder, why = requirements()
        if why:
            return None
        try:
            _helper = _Helper(node, folder)
        except Exception:
            _broken_until = time.time() + COOL_DOWN
            return None
        helper = _helper
    ready = await helper.call("start", timeout=START_TIMEOUT)
    if not ready.get("ok"):
        why = ready.get("error") or " ".join(helper.last_err[-2:]) or "it did not start"
        helper.stop()
        _broken_until = time.time() + COOL_DOWN
        try:
            from app.utils.logger import log_system
            log_system(f"The web browser did not start ({why[:160]}): reading pages plainly for a while")
        except Exception:
            pass
        return None
    return helper


def _page(data: dict, url: str) -> pagemod.Page:
    p = data.get("page") or {}
    return pagemod.Page(
        url=str(p.get("url") or url), title=str(p.get("title") or "")[:200],
        site=pagemod.site_of(str(p.get("url") or url)), description=str(p.get("description") or "")[:400],
        text=str(p.get("text") or "")[:pagemod.MAX_TEXT],
        links=[{"text": str(x.get("text") or "")[:90], "url": str(x.get("url") or "")}
               for x in (p.get("links") or []) if str(x.get("url") or "").startswith(("http://", "https://"))][:80],
    )


class Session:
    """One tab of the helper's Chrome."""
    can_google = True
    can_look = True
    can_find = True

    def __init__(self, helper: _Helper, tab: int):
        self.helper = helper
        self.tab = tab
        self.url = ""

    async def open(self, url: str) -> pagemod.Page:
        try:
            url = await guard.check(url)
        except guard.Blocked as e:
            return pagemod.Page(url=url, error=str(e), blocked=True)
        data = await self.helper.call("open", tab=self.tab, url=url)
        if not data.get("ok"):
            # The browser could not: the plain way, which needs no JavaScript and often has enough.
            plain = await pagemod.fetch(url)
            return plain if plain.ok else pagemod.Page(url=url, error=str(data.get("error") or plain.error))
        p = _page(data, url)
        self.url = p.url
        return p

    async def google(self, q: str, n: int = 6) -> list:
        from app.utils.web import search
        data = await self.helper.call("google", tab=self.tab, q=q, n=n)
        if data.get("error") == "captcha":
            raise search.Captcha("Google asked for a captcha")
        if not data.get("ok"):
            raise search.Unavailable(str(data.get("error") or "Google could not be asked"))
        return [search.Result(title=str(r.get("title") or "")[:160], url=str(r.get("url") or ""),
                              snippet=" ".join(str(r.get("snippet") or "").split())[:300])
                for r in data.get("results") or [] if str(r.get("url") or "").startswith(("http://", "https://"))]

    async def find(self, q: str) -> pagemod.Page:
        data = await self.helper.call("find", tab=self.tab, q=q)
        if not data.get("ok"):
            return pagemod.Page(url=self.url, error=str(data.get("error") or "no search box on this page"))
        p = _page(data, self.url)
        self.url = p.url
        return p

    async def screenshot(self) -> bytes:
        data = await self.helper.call("shot", tab=self.tab)
        if not data.get("ok") or not data.get("jpeg"):
            return b""
        return base64.b64decode(data["jpeg"])

    async def look(self, words=()) -> str:
        """The page as it shows on screen, in words, from the vision model."""
        shot = await self.screenshot()
        if not shot:
            return ""
        return await describe(shot, " ".join(sorted(words))[:200])

    async def close(self) -> None:
        await self.helper.call("close", tab=self.tab, timeout=10.0)


async def describe(jpeg: bytes, about: str = "") -> str:
    from app.utils.ai import _create_image_completion
    from app.utils.helpers import load_config
    model = (load_config().get("bot") or {}).get("groq_image_model", "meta-llama/llama-4-scout-17b-16e-instruct")
    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    prompt = ("This is a screenshot of a web page. Say what is on it, plainly: headlines, names, numbers, prices, "
              "scores, dates, and what the pictures show." + (f" What matters most: {about}." if about else ""))
    resp = await _create_image_completion(model, messages=[{"role": "user", "content": [
        {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_url}}]}], max_tokens=400)
    return " ".join((resp.choices[0].message.content or "").split())[:1500]


async def session():
    """A tab of the browser when it can run, else the plain way (agent.PlainSession). Never raises."""
    from app.utils.web.agent import PlainSession
    try:
        helper = await _get_helper()
        if helper is not None:
            opened = await helper.call("tab", timeout=20.0)
            if opened.get("ok"):
                return Session(helper, int(opened["tab"]))
    except Exception:
        pass
    return PlainSession()


async def release(sess) -> None:
    try:
        await sess.close()
    except Exception:
        pass


def status() -> dict:
    """For the panel: whether the browser can run here, and why not."""
    node, folder, why = requirements()
    return {"ready": not why, "why": why, "running": bool(_helper is not None and _helper.alive()),
            "resting": time.time() < _broken_until}
