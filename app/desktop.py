"""app/desktop.py - native window shell for the web UI, and the frozen exe's entry. Runs the supervisor + FastAPI server in a background thread, then opens a pywebview window pointed at the local UI, with a system tray icon, falling back to the default browser if WebView2/pywebview is unavailable. IMPORTANT: this is the PyInstaller entry point, so LLMSelfbot.exe lands here for EVERY invocation, including the workers the supervisor spawns as `LLMSelfbot.exe --role discord`; main() must dispatch on argv before it does anything else, or each worker becomes another supervisor spawning more workers, and the three guards below make that impossible."""

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


# ── The window side of the tray (app/tray.py has the icon and its menu) ──────
# Showing the main window again (it hides rather than closing, while the tray
# is there), the quick panel's own small window by the tray, opening the data
# folder, and quitting for real.
_APP: dict = {"url": "", "supervisor": None}
_PANEL: dict = {"w": None, "hwnd": 0, "hidden_at": 0.0, "shown": False, "creating": False}


def _own_hwnd(title: str) -> int:
    """One of this process's own top-level windows by title, shown or hidden (backdrop.find_hwnd only sees shown ones)."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = ctypes.c_void_p(0)
        buf = ctypes.create_unicode_buffer(512)
        me = os.getpid()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != me:
                return True
            user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value == title:
                found.value = hwnd
                return False
            return True

        user32.EnumWindows(_enum, 0)
        return found.value or 0
    except Exception:
        return 0


def _focus(hwnd) -> None:
    """Bring a window to the front, with the keyboard.

    Windows only lets a process take the foreground in some cases, and a click
    on the tray is not always one of them. Where it refuses, this process
    joins the foreground window's input for a moment, which it does allow. The
    quick panel needs it: it closes when it loses the focus, so without the
    focus it never would.
    """
    if not hwnd or sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
            return
        fg = user32.GetForegroundWindow()
        theirs = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        mine = kernel32.GetCurrentThreadId()
        if theirs and theirs != mine and user32.AttachThreadInput(mine, theirs, True):
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                user32.AttachThreadInput(mine, theirs, False)
    except Exception:
        pass


def _show_main(route: str = "") -> None:
    """The main window, shown and in front, on a page when one is named."""
    _hide_panel()
    w = _WINDOW.get("w")
    if not w:
        webbrowser.open(_APP["url"] + (f"#/{route}" if route else ""))
        return
    for step in (w.show, w.restore):
        try:
            step()
        except Exception:
            pass
    if route:
        try:
            import json as _json
            w.evaluate_js("location.hash = " + _json.dumps("#/" + route))
        except Exception:
            pass
    _focus(_WINDOW.get("hwnd") or _own_hwnd(APP_TITLE))


def _hide_main() -> None:
    """Closing the window, while the tray is there: it goes, the app keeps running. The first time, the tray says so."""
    from app import tray
    w = _WINDOW.get("w")
    if w:
        try:
            w.hide()
        except Exception:
            pass
    if not tray.prefs().get("told_tray"):
        tray.set_pref("told_tray", True)
        tray.notify("Still replying in the background. Click the icon here to open it, or right-click to quit.",
                    "LLMSelfbot is still running")


def _place_panel(hwnd) -> None:
    """The quick panel beside the tray: above the taskbar (or beside it, wherever it is), at the pointer, on its screen."""
    if not hwnd or sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        hmon = user32.MonitorFromPoint(pt, 2)                   # MONITOR_DEFAULTTONEAREST
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        work, mon = mi.rcWork, mi.rcMonitor
        gap = max(8, w // 36)
        x = min(max(pt.x - w // 2, work.left + gap), work.right - w - gap)
        y = min(max(pt.y - h // 2, work.top + gap), work.bottom - h - gap)
        if work.bottom < mon.bottom:
            y = work.bottom - h - gap                           # taskbar along the bottom
        elif work.top > mon.top:
            y = work.top + gap                                  # along the top
        elif work.right < mon.right:
            x = work.right - w - gap                            # on the right
        elif work.left > mon.left:
            x = work.left + gap                                 # on the left
        else:
            y = work.bottom - h - gap                           # hidden taskbar: the bottom
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, 0, 0, 0x0001)   # HWND_TOPMOST, SWP_NOSIZE
    except Exception:
        pass


def _style_panel(hwnd) -> None:
    """Out of the taskbar and Alt+Tab (a tool window), with round corners where Windows draws them (11)."""
    if not hwnd or sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        ex = user32.GetWindowLongW(hwnd, -20)                  # GWL_EXSTYLE
        user32.SetWindowLongW(hwnd, -20, (ex | 0x80) & ~0x40000)  # + WS_EX_TOOLWINDOW, - WS_EX_APPWINDOW
        pref = ctypes.c_int(2)                                  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass


def _reveal_panel() -> None:
    p, hwnd = _PANEL["w"], _PANEL["hwnd"] or _own_hwnd(PANEL_TITLE)
    _PANEL["hwnd"] = hwnd
    _place_panel(hwnd)
    try:
        p.show()
    except Exception:
        pass
    _place_panel(hwnd)          # again: showing can put it back where it was
    _focus(hwnd)
    _PANEL["shown"] = True
    try:
        p.evaluate_js("window.__trayShown && window.__trayShown()")
    except Exception:
        pass


def _hide_panel() -> None:
    p = _PANEL.get("w")
    if p is not None and _PANEL.get("shown"):
        _PANEL["shown"] = False
        _PANEL["hidden_at"] = time.time()
        try:
            p.hide()
        except Exception:
            pass


def _toggle_panel() -> None:
    """A left click on the tray icon: the quick panel opens, or closes if it is open."""
    if _PANEL["shown"]:
        _hide_panel()
        return
    # The click on the icon took the focus off the panel, which closed it: that click was to close it.
    if time.time() - _PANEL["hidden_at"] < 0.4:
        return
    if _PANEL["w"] is not None:
        _reveal_panel()
        return
    if _PANEL["creating"]:
        return
    try:
        import webview
    except Exception:
        _show_main("")
        return
    _PANEL["creating"] = True
    panel = webview.create_window(
        PANEL_TITLE, _APP["url"] + "?tray=1", width=PANEL_W, height=PANEL_H,
        frameless=True, easy_drag=False, resizable=False, on_top=True, hidden=True,
        background_color="#0a0a11", js_api=WindowApi(), focus=True,
    )
    _PANEL["w"] = panel

    def _ready():
        _PANEL["creating"] = False
        _PANEL["hwnd"] = _own_hwnd(PANEL_TITLE)
        _style_panel(_PANEL["hwnd"])
        # It goes when another window takes over: the form's own Deactivate, which
        # sees it even when the focus is not in the page (whose blur the page also watches).
        try:
            from webview.platforms.winforms import BrowserView
            form = BrowserView.instances.get(panel.uid)
            if form is not None:
                form.Deactivate += lambda *_: threading.Timer(0.05, _hide_panel).start()
        except Exception:
            pass
        _reveal_panel()

    panel.events.loaded += _ready


def _open_data() -> None:
    from app.utils.paths import DATA_DIR
    try:
        if sys.platform == "win32":
            os.startfile(str(DATA_DIR))                         # noqa: S606 - the user's own folder
        else:
            import subprocess
            from app.utils.procs import quiet_kwargs
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(DATA_DIR)], **quiet_kwargs())
    except Exception:
        pass


def _quit_app() -> None:
    """Quit for real: the accounts stop, the tray goes, the process ends."""
    from app import tray
    _hide_panel()
    sup = _APP.get("supervisor")
    try:
        if sup:
            sup.stop_all()
    except Exception:
        pass
    tray.stop()
    os._exit(0)


def _start_tray(url: str, supervisor) -> None:
    from app import tray
    _APP.update(url=url, supervisor=supervisor)
    tray.start(url, supervisor, {
        "show_main": _show_main,
        "toggle_panel": _toggle_panel,
        "open_data": _open_data,
        "quit": lambda: threading.Thread(target=_quit_app, daemon=True).start(),
    })


# The pywebview Window is kept OUT of the js_api object on purpose: pywebview walks the js_api instance to expose it as window.pywebview.api, and an attribute holding the Window makes it traverse window.native.browser.webview.*, touching WebView2 COM properties off the UI thread, which floods the log with "CoreWebView2 can only be accessed from the UI thread" and wedges the window into "not responding". Keeping the reference in a module-level dict avoids it. The window title, and the string used to find that window again, must be the same value (find_hwnd matches exactly), so keeping it in one place is the only thing stopping a rename in one spot breaking the other three.
APP_TITLE = "LLMSelfbot"
PANEL_TITLE = "LLMSelfbot quick panel"
PANEL_W, PANEL_H = 340, 480


def _drop_stale_webview_cache(storage, app_dir) -> None:
    """Throw away the webview's HTTP cache when the panel has been rebuilt. The panel is a web page, so the webview caches it; index.html is now served with no-store, but a copy cached before that header existed is still a cached copy, and the webview will happily keep serving it, so the app loads the previous build's JavaScript for ever and every fix looks like it did not work. The built asset filenames carry a content hash, so index.html changes on every rebuild: comparing it against the last one we launched with is an exact "is this a new build" test, and only then is the cache cleared. Storage that matters, the preferences, lives on the server, so nothing of the user's is lost either way."""
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
    """Exposed to the SPA as window.pywebview.api.* The window is frameless, so minimise / close / resize have no OS chrome to come from, the UI drives them through here. Methods only; no attributes."""

    def minimize(self):
        w = _WINDOW.get("w")
        if w:
            w.minimize()

    def close_window(self):
        """The window's own close button. With the tray there, the window hides and the app keeps running (the closing handler in main() sees to it); without, it closes."""
        w = _WINDOW.get("w")
        if w:
            w.destroy()

    def hide_panel(self):
        """The quick panel lost the focus, or Escape: it goes."""
        _hide_panel()

    def open_main(self, route=""):
        """A page chosen in the quick panel: the main window, on it."""
        _show_main(str(route or ""))

    def quit_app(self):
        threading.Thread(target=_quit_app, daemon=True).start()

    def set_size(self, width, height):
        w = _WINDOW.get("w")
        if w:
            w.resize(int(width), int(height))

    def get_size(self):
        w = _WINDOW.get("w")
        return [w.width, w.height] if w else [0, 0]

    def set_fullscreen(self, on=True):
        """Big Picture Mode takes the whole screen, and gives it back as it was. pywebview only has a toggle, so
        the state is kept here and the toggle only called when it has to change: a second "on" from the page
        must not take the window back out of fullscreen."""
        w = _WINDOW.get("w")
        if not w:
            return False
        want = bool(on)
        changed = bool(_WINDOW.get("fullscreen")) != want
        if changed:
            w.toggle_fullscreen()
            _WINDOW["fullscreen"] = want
        # Whether the window changed: the page waits for the resize only when one is coming.
        return changed

    def set_backdrop(self, kind="none"):
        """Keep the window dark and free of any system backdrop. The Mica/Acrylic themes are gone, so this only ever clears effects now; the UI still calls it on theme change to undo anything an older build left applied."""
        from app.utils import backdrop
        hwnd = _WINDOW.get("hwnd") or backdrop.find_hwnd(APP_TITLE)
        if hwnd:
            _WINDOW["hwnd"] = hwnd
        return bool(hwnd) and backdrop.apply(hwnd, str(kind))

    def backdrop_supported(self):
        from app.utils import backdrop
        return backdrop.supported()

    def save_text_file(self, filename, content):
        """Write text to wherever the user points a native Save dialog. A browser download is an anchor with a download attribute, which the embedded WebView has no download handler for, so clicking Download in the Logs tab did nothing at all, with nowhere to choose; the desktop shell has a real file dialog, so it uses that. Returns the path written, "" if the dialog was cancelled, or a string starting with "error:" so the page can say what went wrong."""
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

    def save_binary_file(self, filename, data_b64):
        """Write a file (a picture, from the right-click menu's Save as) wherever the user points a native Save dialog. The page sends it as base64, since the bridge carries text. Same answers as save_text_file: the path, "" when cancelled, or "error: ..."."""
        import base64
        import webview
        w = _WINDOW.get("w")
        if not w:
            return "error: no window"
        try:
            data = base64.b64decode(str(data_b64 or ""), validate=True)
            name = str(filename or "picture.png")
            result = w.create_file_dialog(webview.SAVE_DIALOG, save_filename=name)
            if not result:
                return ""
            path = result if isinstance(result, str) else result[0]
            pathlib.Path(path).write_bytes(data)
            return path
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    def read_clipboard_text(self):
        """The text on the clipboard, for Paste in the right-click menu. The embedded browser can read it too, but first asks permission in a box that looks like nothing else in the app, every time. None when it cannot be read here, so the page tries its own way."""
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.GetClipboardData.argtypes = [wintypes.UINT]
            user32.GetClipboardData.restype = wintypes.HANDLE
            user32.CloseClipboard.restype = wintypes.BOOL
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            CF_UNICODETEXT = 13
            for _ in range(5):
                # Another program can hold the clipboard for a moment; give it one.
                if user32.OpenClipboard(None):
                    break
                time.sleep(0.02)
            else:
                return None
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return None
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        except Exception:
            return None

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
    # Guard 1, honour argv. The supervisor spawns workers by re-invoking this same executable with --role; without this they would each open a window and start their own supervisor.
    if cli.run():
        return

    # Guard 2, a worker process must never open the desktop shell.
    if cli.is_child():
        print("[Desktop] Refusing to open a window inside a worker process.", flush=True)
        sys.exit(2)

    cli.bootstrap()

    # Guard 3, only one supervisor may exist, enforced by an OS-level lock.
    lock_file = cli.acquire_single_instance()
    # A restore chosen in the panel lands now, before any account opens its files.
    from app.utils.paths import apply_pending_restore
    if apply_pending_restore():
        cli.load_env()

    port = int(os.environ.get("SELFBOT_PORT", "") or 0) or find_port()
    url = f"http://127.0.0.1:{port}/"

    from app.web.server import run_server
    from app.web.supervisor import Supervisor

    supervisor = Supervisor(port=port)

    def _backend():
        supervisor.start_all()
        run_server(supervisor=supervisor, port=port)

    backend = threading.Thread(target=_backend, daemon=True, name="backend")
    backend.start()

    print(f"[Desktop] Starting webui at {url}")
    if not _wait_until_ready(url):
        print("[Desktop] Backend did not come up in time, check the logs.")
        sys.exit(1)

    _start_tray(url, supervisor)

    try:
        try:
            import webview

            # Only the element carrying .pywebview-drag-region drags; without this the class bubbles up the DOM and every button inside the title strip would drag the window instead of clicking.
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

            # Closing it (its own button, Alt+F4) hides it while the tray is there and says it should keep
            # running: the app goes on replying, and the tray brings the window back. Quit is what ends it.
            def _on_closing():
                from app import tray
                if sys.platform == "win32" and tray.running() and tray.prefs().get("close_to_tray"):
                    threading.Timer(0.01, _hide_main).start()
                    return False
                return None

            window.events.closing += _on_closing

            # Dark chrome, no backdrop, and clears any blur an older build of the app left on the window.
            def _on_shown():
                from app.utils import backdrop as bd
                hwnd = bd.find_hwnd(APP_TITLE)
                if hwnd:
                    _WINDOW["hwnd"] = hwnd
                    bd.apply(hwnd, "none")

            window.events.shown += _on_shown
            # pywebview defaults to private_mode=True, which runs the webview as a private session: localStorage is thrown away when the app closes. Every panel preference lives there, so the theme, the font and the dashboard layout reset on every launch. Giving it a real storage folder under the data dir keeps them, and follows a portable install into its own folder.
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
