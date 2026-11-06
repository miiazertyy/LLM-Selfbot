"""The phone app: LLMSelfbot's panel in a window of its own, the bot inside it.

On a computer the app is a server with a process for each account, and the
panel is a web page. A phone runs one app as one process, so here the same
server runs on a thread of this one (the accounts on threads of their own:
app/core/inprocess.py) and the panel shows in the app's own web view, pointed
at it. Its data lives in the app's private storage, where an update keeps it.

Links to anywhere but the panel open in the phone's browser instead of in
here, where there would be no way back to the panel (the panel sends the ones
it opens itself through /api/system/open-url, which calls open_outside).

The panel takes the whole screen. A plain window rather than Toga's
MainWindow, which put a title bar over it on both phones; on an iPhone the
panel also runs under the status bar and the home indicator (it pads itself
by the safe areas, webui/src/app.css), where Toga kept it out and left black
bands; and the bars that stay round it are the panel's own colour, followed
as the theme changes.

On Android the web view is also given a file picker and the microphone, which
it does not do by itself (webchrome.py).
"""

import asyncio
import os
import re
import socket
import threading
import urllib.request

import toga
from toga.style import Pack

PORT = 8787
# The panel's own colour before it has loaded, as the starting page's: what the bars round it are painted.
BACKGROUND = (13, 11, 20)

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
        # A plain window: a MainWindow has a title bar, which here was only a band with the app's name in it.
        self.main_window = toga.Window(title=self.formal_name)
        self.main_window.content = self.web
        self.main_window.show()
        self.edge_to_edge()
        self.paint_bars(BACKGROUND)
        self.android_chrome()

        threading.Thread(target=self.serve, name="panel", daemon=True).start()
        self.loop.create_task(self.wait_for_panel())

    # ── The whole screen ─────────────────────────────────────────────────────
    def edge_to_edge(self):
        """iPhone: the panel under the status bar and the home indicator too. Toga keeps a window's content below
        the status bar, and the web view keeps the page out of the safe areas, which showed as black bands; the page
        pads itself by them instead (viewport-fit=cover, env(safe-area-inset-*))."""
        if self.shell != "ios":
            return
        try:
            impl = self.main_window._impl
            container = impl.container

            def layout(c):
                c.top_inset = 0
                impl.notify_resize(c)

            container.on_native_layout = layout
            # UIScrollViewContentInsetAdjustmentNever: the page is given the safe areas, not kept out of them.
            self.web._impl.native.scrollView.contentInsetAdjustmentBehavior = 2
        except Exception as exc:  # an older or newer Toga: the panel still shows, with its bands
            print(f"[phone] Could not take the whole screen: {exc}")

    def android_chrome(self):
        """Android: a file picker and the microphone for the panel. Failing that it still runs, without them, and the
        panel says files can't be picked (app/utils/compat.py), which is why it is told here."""
        if self.shell != "android":
            return
        try:
            from .webchrome import PanelChrome
            self.web._impl.native.setWebChromeClient(PanelChrome(self))
            os.environ["LLMSELFBOT_FILE_PICKER"] = "1"
        except Exception as exc:
            print(f"[phone] No file picker or microphone: {exc}")

    def paint_bars(self, rgb):
        """What shows round the panel (the status bar's strip, the navigation bar, the page before it loads) in the
        panel's own colour, rather than black or a theme's purple."""
        r, g, b = rgb
        try:
            if self.shell == "android":
                from java import jclass
                color = jclass("android.graphics.Color").rgb(r, g, b)
                window = self._impl.native.getWindow()
                window.setStatusBarColor(color)
                window.setNavigationBarColor(color)
            else:
                from rubicon.objc import ObjCClass
                color = ObjCClass("UIColor").colorWithRed_green_blue_alpha_(r / 255, g / 255, b / 255, 1.0)
                self.main_window._impl.native.backgroundColor = color
                web = self.web._impl.native
                web.backgroundColor = color
                web.scrollView.backgroundColor = color
        except Exception as exc:
            print(f"[phone] Could not colour the bars: {exc}")

    async def follow_theme(self):
        """The panel's colour, read off the page every few seconds: a theme changed in the panel recolours the bars."""
        last = None
        while True:
            try:
                value = await self.web.evaluate_javascript(
                    "getComputedStyle(document.documentElement).backgroundColor")
                m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", str(value or ""))
                if m:
                    rgb = tuple(int(x) for x in m.groups())
                    if rgb != last:
                        last = rgb
                        self.paint_bars(rgb)
            except Exception:
                pass
            await asyncio.sleep(3)

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
                self.loop.create_task(self.follow_theme())
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
