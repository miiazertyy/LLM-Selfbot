"""The phone app: LLMSelfbot's panel in a window of its own, the bot inside it.

On a computer the app is a server with a process for each account, and the
panel is a web page. A phone runs one app as one process, so here the same
server runs on a thread of this one (the accounts on threads of their own:
app/core/inprocess.py) and the panel shows in the app's own web view, pointed
at it. Its data lives in the app's private storage, where an update keeps it.

Links to anywhere but the panel open in the phone's browser instead of in
here, where there would be no way back to the panel (the panel sends the ones
it opens itself through /api/system/open-url, which calls open_outside).
"""

import asyncio
import os
import socket
import threading
import urllib.request

import toga
from toga.style import Pack

PORT = 8787

STARTING = """<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  html, body { height: 100%; margin: 0; background: #0d0b14; color: #e9e6f2;
               font-family: -apple-system, system-ui, sans-serif; }
  body { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; }
  .ring { width: 36px; height: 36px; border-radius: 50%; border: 3px solid #ffffff1f;
          border-top-color: #f7a1c4; animation: turn 0.9s linear infinite; }
  @keyframes turn { to { transform: rotate(360deg); } }
  p { margin: 0; max-width: 80%; font-size: 14px; line-height: 1.5; text-align: center; color: #a9a3bb; }
</style></head>
<body><div class="ring"></div><p>{text}</p></body></html>"""


def free_port(preferred: int) -> int:
    """The usual port when it is free, which keeps the panel's saved state
    (the web view keeps it per address); any free one when it is not."""
    for port in (preferred, 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    return preferred


class LLMSelfbot(toga.App):
    def startup(self):
        self.shell = "android" if toga.platform.current_platform == "android" else "ios"
        self.port = free_port(PORT)
        self.panel = f"http://127.0.0.1:{self.port}/"
        self.failure = ""

        data = self.paths.data
        data.mkdir(parents=True, exist_ok=True)
        # Before anything of the app is imported: these decide where it keeps
        # its data, that accounts run on threads, and which port it serves on.
        os.environ["LLMSELFBOT_SHELL"] = self.shell
        os.environ.setdefault("LLMSELFBOT_DATA_DIR", str(data))
        os.environ["SELFBOT_PORT"] = str(self.port)

        self.web = toga.WebView(style=Pack(flex=1), on_navigation_starting=self.on_navigate)
        self.web.set_content(self.panel, STARTING.replace("{text}", "Starting LLMSelfbot"))
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = self.web
        self.main_window.show()

        threading.Thread(target=self.serve, name="panel", daemon=True).start()
        self.loop.create_task(self.wait_for_panel())

    # ── The server ───────────────────────────────────────────────────────────
    def serve(self):
        try:
            from app.utils import device
            device.set_url_opener(self.open_outside)
            from app.cli import bootstrap, run_supervisor
            bootstrap()
            run_supervisor(port=self.port)
        except BaseException as exc:          # SystemExit included: say why, not go blank
            self.failure = f"{type(exc).__name__}: {exc}"

    def answers(self) -> bool:
        try:
            with urllib.request.urlopen(self.panel + "api/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    async def wait_for_panel(self):
        loop = self.loop
        for _ in range(900):                  # three minutes; the first start unpacks a lot
            if self.failure:
                self.web.set_content(self.panel, STARTING.replace(
                    "{text}", "LLMSelfbot could not start.<br><br>" + self.failure.replace("<", "&lt;")))
                return
            if await loop.run_in_executor(None, self.answers):
                self.web.url = self.panel
                return
            await asyncio.sleep(0.2)
        self.web.set_content(self.panel, STARTING.replace("{text}", "LLMSelfbot is taking too long to start."))

    # ── Links ────────────────────────────────────────────────────────────────
    def on_navigate(self, widget, url, **kwargs):
        """The panel, and the page it starts from, load in here; the rest outside."""
        if not url or url.startswith((self.panel, "about:", "data:", "http://localhost:")):
            return True
        if url.startswith(f"http://127.0.0.1:{self.port}"):
            return True
        self.open_outside(url)
        return False

    def open_outside(self, url: str):
        """Hand a link to the phone: its browser, and through it, for an APK,
        its installer. Python's own webbrowser does it: on iOS since 3.13, on
        Android through the handler Toga registers. From the main thread,
        which is where both want it; the panel's server calls from its own."""
        import webbrowser
        self.loop.call_soon_threadsafe(webbrowser.open, url)


def main():
    return LLMSelfbot()
