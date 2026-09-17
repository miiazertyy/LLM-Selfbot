"""
app/desktop.py - Native window shell for the web UI, and the frozen exe's entry.

Runs the supervisor + FastAPI server in a background thread, then opens a
pywebview window pointed at the local UI, with a system tray icon.
Falls back to the default browser if WebView2/pywebview is unavailable.

IMPORTANT: this is the PyInstaller entry point, so LLMSelfbot.exe lands here for
EVERY invocation, including the workers the supervisor spawns as
`LLMSelfbot.exe --role discord`. main() must therefore dispatch on argv before it
does anything else, or each worker becomes another supervisor spawning more
workers. Three guards below make that impossible.
"""

import os
import socket
import pathlib
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cli

DEFAULT_PORT = 8787


def _configured_port() -> int:
    try:
        from app.utils.helpers import load_config
        webui = (load_config().get("services", {}) or {}).get("webui", {}) or {}
        return int(webui.get("port") or DEFAULT_PORT)
    except Exception:
        return DEFAULT_PORT


def find_port(start: int | None = None) -> int:
    """The configured port, or the next free one above it."""
    port = start or _configured_port()
    for _ in range(20):
        try:
            sock = socket.socket()
            sock.bind(("127.0.0.1", port))
            sock.close()
            return port
        except OSError:
            port += 1
    raise OSError("no free port found")


def _wait_until_ready(url: str, timeout: float = 30.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status in (200, 401):
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def _run_tray(url: str, supervisor_holder: dict):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None

    def _icon_image():
        from app.utils.paths import APP_DIR
        icon = APP_DIR / "resources" / "icon.png"
        if icon.is_file():
            return Image.open(icon).convert("RGBA").resize((64, 64), Image.LANCZOS)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((4, 4, 60, 60), radius=14, fill=(124, 140, 255, 255))
        return img

    def _show(_icon, _item):
        # pywebview must run on the main thread, so from the tray we can only
        # fall back to the browser.
        webbrowser.open(url)

    def _pause_all(_icon, _item):
        """Pause/resume every account via IPC, the processes keep running."""
        sup = supervisor_holder.get("supervisor")
        if not sup:
            return
        import asyncio
        from app.core import ipc
        async def _toggle():
            for meta in ipc.discover_targets().values():
                await ipc.send_and_wait(meta["target"], "pause", {}, timeout=5.0)
        try:
            asyncio.run(_toggle())
        except Exception:
            pass

    def _restart(_icon, _item):
        """Restart every worker; the window and server stay up."""
        sup = supervisor_holder.get("supervisor")
        if sup:
            for child_id in list(sup.children):
                sup.restart(child_id)

    def _quit(_icon, _item):
        sup = supervisor_holder.get("supervisor")
        if sup:
            sup.stop_all()
        _icon.stop()
        os._exit(0)

    icon = pystray.Icon(
        "LLMSelfbot",
        _icon_image(),
        APP_TITLE,
        menu=pystray.Menu(
            pystray.MenuItem("Open window", _show, default=True),
            pystray.MenuItem("Pause / resume all", _pause_all),
            pystray.MenuItem("Restart", _restart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        ),
    )
    threading.Thread(target=icon.run, daemon=True, name="tray").start()
    return icon


# The pywebview Window is kept OUT of the js_api object on purpose.
# pywebview walks the js_api instance to expose it as window.pywebview.api, and
# an attribute holding the Window makes it traverse window.native.browser.webview.*,
# touching WebView2 COM properties off the UI thread. That floods the log with
# "CoreWebView2 can only be accessed from the UI thread" and wedges the window
# into "not responding". Keeping the reference in a module-level dict avoids it.
# The window title, and the string used to find that window again. find_hwnd
# matches exactly, so these must be the same value: keeping it in one place is
# the only thing stopping a rename in one spot breaking the other three.
APP_TITLE = "LLMSelfbot"


def _drop_stale_webview_cache(storage, app_dir) -> None:
    """Throw away the webview's HTTP cache when the panel has been rebuilt.

    The panel is a web page, so the webview caches it. index.html is now served
    with no-store, but a copy cached before that header existed is still a
    cached copy, and the webview will happily keep serving it: the app then
    loads the previous build's JavaScript for ever, and every fix looks like it
    did not work.

    The built asset filenames carry a content hash, so index.html changes on
    every rebuild. Comparing it against the last one we launched with is an
    exact "is this a new build" test, and only then is the cache cleared.
    Storage that matters, the preferences, lives on the server, so nothing of
    the user's is lost either way.
    """
    import hashlib
    import shutil

    try:
        index = app_dir / "webui" / "dist" / "index.html"
        if not index.exists():
            return
        build_id = hashlib.md5(index.read_bytes()).hexdigest()
        marker = storage / "build.id"
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == build_id:
            return

        for name in ("Cache", "Code Cache", "GPUCache", "Service Worker"):
            target = storage / "EBWebView" / "Default" / name
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        storage.mkdir(parents=True, exist_ok=True)
        marker.write_text(build_id, encoding="utf-8")
        print("[LLMSelfbot] Panel rebuilt, cleared the webview cache.", flush=True)
    except Exception:
        pass          # never let housekeeping stop the window opening


_WINDOW: dict = {"w": None}


class WindowApi:
    """Exposed to the SPA as window.pywebview.api.*

    The window is frameless, so minimise / close / resize have no OS chrome to
    come from, the UI drives them through here. Methods only; no attributes.
    """

    def minimize(self):
        w = _WINDOW.get("w")
        if w:
            w.minimize()

    def close_window(self):
        w = _WINDOW.get("w")
        if w:
            w.destroy()

    def set_size(self, width, height):
        w = _WINDOW.get("w")
        if w:
            w.resize(int(width), int(height))

    def get_size(self):
        w = _WINDOW.get("w")
        return [w.width, w.height] if w else [0, 0]

    def set_backdrop(self, kind="none"):
        """Keep the window dark and free of any system backdrop.

        The Mica/Acrylic themes are gone, so this only ever clears effects now;
        the UI still calls it on theme change to undo anything an older build
        left applied.
        """
        from app.utils import backdrop
        hwnd = _WINDOW.get("hwnd") or backdrop.find_hwnd(APP_TITLE)
        if hwnd:
            _WINDOW["hwnd"] = hwnd
        return bool(hwnd) and backdrop.apply(hwnd, str(kind))

    def backdrop_supported(self):
        from app.utils import backdrop
        return backdrop.supported()

    def save_text_file(self, filename, content):
        """Write text to wherever the user points a native Save dialog.

        A browser download is an anchor with a download attribute, which the
        embedded WebView has no download handler for: clicking Download in the
        Logs tab did nothing at all, with nowhere to choose. The desktop shell
        has a real file dialog, so it uses that.

        Returns the path written, "" if the dialog was cancelled, or a string
        starting with "error:" so the page can say what went wrong.
        """
        import webview
        w = _WINDOW.get("w")
        if not w:
            return "error: no window"
        try:
            name = str(filename or "export.txt")
            result = w.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=name)
            if not result:
                return ""                      # cancelled, not a failure
            path = result if isinstance(result, str) else result[0]
            pathlib.Path(path).write_text(str(content), encoding="utf-8")
            return path
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    def pick_folder(self):
        """A directory chosen by the user, for exports and portable installs."""
        import webview
        w = _WINDOW.get("w")
        if not w:
            return ""
        try:
            result = w.create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return ""
            return result if isinstance(result, str) else result[0]
        except Exception:
            return ""

    def pick_file(self, extensions=None):
        """One existing file chosen by the user, for restoring a backup."""
        import webview
        w = _WINDOW.get("w")
        if not w:
            return ""
        try:
            kwargs = {}
            if extensions:
                kwargs["file_types"] = tuple(extensions)
            result = w.create_file_dialog(webview.OPEN_DIALOG, **kwargs)
            if not result:
                return ""
            return result if isinstance(result, str) else result[0]
        except Exception:
            return ""


def main():
    # Guard 1, honour argv. The supervisor spawns workers by re-invoking this
    # same executable with --role; without this they would each open a window
    # and start their own supervisor.
    if cli.run():
        return

    # Guard 2, a worker process must never open the desktop shell.
    if cli.is_child():
        print("[Desktop] Refusing to open a window inside a worker process.", flush=True)
        sys.exit(2)

    cli.bootstrap()

    # Guard 3, only one supervisor may exist, enforced by an OS-level lock.
    lock_file = cli.acquire_single_instance()

    port = int(os.environ.get("SELFBOT_PORT", "") or 0) or find_port()
    url = f"http://127.0.0.1:{port}/"

    from app.web.server import run_server
    from app.web.supervisor import Supervisor

    supervisor = Supervisor(port=port)
    supervisor_holder = {"supervisor": supervisor}

    def _backend():
        supervisor.start_all()
        run_server(supervisor=supervisor, port=port)

    backend = threading.Thread(target=_backend, daemon=True, name="backend")
    backend.start()

    print(f"[Desktop] Starting control panel at {url}")
    if not _wait_until_ready(url):
        print("[Desktop] Backend did not come up in time, check the logs.")
        sys.exit(1)

    _run_tray(url, supervisor_holder)

    try:
        try:
            import webview

            # Only the element carrying .pywebview-drag-region drags; without
            # this the class bubbles up the DOM and every button inside the
            # title strip would drag the window instead of clicking.
            webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

            window = webview.create_window(
                APP_TITLE, url,
                width=430, height=620, min_size=(360, 420),   # pocket size; the UI can grow it
                frameless=True,          # no OS title bar; the app fills the window
                easy_drag=False,         # drag only from the marked strips
                resizable=True,
                transparent=False,       # the UI paints its own opaque background
                background_color="#0a0a11",
                js_api=WindowApi(),
            )
            _WINDOW["w"] = window

            # Dark chrome, no backdrop - and clears any blur an older build of
            # the app left on the window.
            def _on_shown():
                from app.utils import backdrop as bd
                hwnd = bd.find_hwnd(APP_TITLE)
                if hwnd:
                    _WINDOW["hwnd"] = hwnd
                    bd.apply(hwnd, "none")

            window.events.shown += _on_shown
            # pywebview defaults to private_mode=True, which runs the webview
            # as a private session: localStorage is thrown away when the app
            # closes. Every panel preference lives there, so the theme, the
            # font and the dashboard layout reset on every launch. Giving it a
            # real storage folder under the data dir keeps them, and follows a
            # portable install into its own folder.
            from app.utils.paths import DATA_DIR, APP_DIR
            storage = DATA_DIR / "webview"
            _drop_stale_webview_cache(storage, APP_DIR)
            try:
                storage.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            webview.start(private_mode=False, storage_path=str(storage))
        except Exception as e:
            print(f"[Desktop] pywebview unavailable ({e}), opening in the default browser.")
            webbrowser.open(url)
            while True:
                time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.stop_all()
        lock_file.close()


if __name__ == "__main__":
    main()
