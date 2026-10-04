"""app/tray.py - the icon by the clock, and what it offers.

It used to be a plain four-line menu (Open window, which opened a browser tab
rather than the app; Pause / resume all; Restart; Quit), in the system's
light colours, on an icon that said nothing about how things were going.

Now:

  - The icon carries a coloured dot for how things are (green, all replying;
    amber, paused; red, an account crashed; grey, nothing running), and its
    tooltip says it in words.
  - A left click opens a small quick panel by the tray (the app's own page,
    "?tray", TrayPanel.svelte): every account with a switch to pause it,
    today's replies, the pages one click away, pause all, restart and quit.
    It closes itself when you click elsewhere.
  - A right click opens a menu, dark like the app, that is rebuilt as it
    opens, so what it says is current: how things are, each account with its
    own pause, restart and stop, the pages, and the app's own switches (keep
    running when the window is closed, start with Windows, alerts).
  - Closing the window keeps the app running here (the first time, it says
    so); Quit is what stops it.
  - An account that crashes, or is given up on, is announced with a
    notification, when alerts are on.

The window-side half (showing the main window, the panel's window, quitting)
lives in app/desktop.py, which calls start() once the window exists.
"""

import json
import os
import sys
import threading
import time

APP_TITLE = "LLMSelfbot"
PANEL_TITLE = "LLMSelfbot quick panel"
PANEL_W, PANEL_H = 340, 480

_STATE: dict = {"icon": None, "supervisor": None, "url": "", "snapshot": {}, "tone": None,
                "panel": None, "panel_hwnd": None, "panel_hidden_at": 0.0, "creating": False,
                "windows": None}


# ── The app's own switches, kept beside its config ────────────────────────────
def _prefs_path():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config" / "desktop.json"


def prefs() -> dict:
    out = {"close_to_tray": True, "alerts": True, "told_tray": False}
    try:
        out.update(json.loads(_prefs_path().read_text(encoding="utf-8")))
    except Exception:
        pass
    return out


def set_pref(key: str, value) -> None:
    data = prefs()
    data[key] = value
    try:
        path = _prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Start with Windows ────────────────────────────────────────────────────────
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def can_autostart() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def autostart_on() -> bool:
    if not can_autostart():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, APP_TITLE)
        return os.path.normcase(sys.executable) in os.path.normcase(str(value))
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    if not can_autostart():
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_TITLE, 0, winreg.REG_SZ, f'"{sys.executable}"')
            else:
                try:
                    winreg.DeleteValue(k, APP_TITLE)
                except OSError:
                    pass
    except OSError:
        pass


# ── How things are ────────────────────────────────────────────────────────────
def snapshot() -> dict:
    """Every account, whether it is running and replying, and the one word for it all."""
    sup = _STATE.get("supervisor")
    kids = []
    try:
        kids = [c for c in (sup.status() if sup else []) if c.get("role") in ("discord", "snapchat")]
    except Exception:
        pass
    paused = {}
    try:
        from app.web.routes.chat_routes import _CHATS_CACHE, _ipc_target_for
        for c in kids:
            hit = _CHATS_CACHE.get(_ipc_target_for(c["id"]))
            paused[c["id"]] = bool(hit and (hit.get("body") or {}).get("paused"))
    except Exception:
        pass
    running = [c for c in kids if c.get("state") == "running"]
    bad = [c for c in kids if c.get("state") == "crashing" or c.get("gave_up")]
    n_paused = sum(1 for c in running if paused.get(c["id"]))
    if bad:
        tone = "bad"
    elif running and n_paused == len(running):
        tone = "warn"
    elif running:
        tone = "good" if not n_paused else "warn"
    else:
        tone = "idle"
    words = [f"{len(running)} running" if running else "Nothing running"]
    if n_paused:
        words.append(f"{n_paused} paused")
    if bad:
        words.append(f"{len(bad)} need{'s' if len(bad) == 1 else ''} a look")
    return {"accounts": kids, "paused": paused, "tone": tone, "headline": " · ".join(words),
            "all_paused": bool(running) and n_paused == len(running)}


def _state_word(c: dict, paused: bool) -> str:
    if c.get("gave_up"):
        return "Stopped after crashing"
    st = c.get("state")
    if st == "crashing":
        return "Restarting"
    if st == "starting":
        return "Starting"
    if st != "running":
        return "Stopped"
    return "Paused" if paused else "Replying"


# ── Acting on accounts ────────────────────────────────────────────────────────
def _in_thread(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True, name="tray-action").start()


def _toggle_pause(child_id: str):
    import asyncio
    from app.core import ipc
    meta = ipc.discover_targets().get(child_id)
    if not meta:
        return
    try:
        asyncio.run(ipc.send_and_wait(meta["target"], "pause", {}, timeout=6.0))
    except Exception:
        pass


def _pause_all():
    snap = snapshot()
    want = not snap["all_paused"]
    for c in snap["accounts"]:
        if c.get("state") == "running" and bool(snap["paused"].get(c["id"])) != want:
            _toggle_pause(c["id"])


def _restart(child_id: str):
    sup = _STATE.get("supervisor")
    if sup:
        try:
            sup.restart(child_id)
        except Exception:
            pass


def _restart_all():
    for c in snapshot()["accounts"]:
        if c.get("state") == "running" or c.get("gave_up") or c.get("state") == "crashing":
            _restart(c["id"])


def _stop(child_id: str):
    sup = _STATE.get("supervisor")
    if sup:
        try:
            sup.stop(child_id)
        except Exception:
            pass


def _start(child_id: str):
    sup = _STATE.get("supervisor")
    if sup:
        try:
            sup.start(child_id)
        except Exception:
            pass


# ── The icon ──────────────────────────────────────────────────────────────────
_TONES = {"good": (35, 165, 90), "warn": (240, 178, 50), "bad": (242, 63, 67), "idle": (128, 132, 142)}


def _base_image():
    from PIL import Image, ImageDraw
    from app.utils.paths import APP_DIR
    icon = APP_DIR / "resources" / "icon.png"
    if icon.is_file():
        return Image.open(icon).convert("RGBA").resize((64, 64), Image.LANCZOS)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((4, 4, 60, 60), radius=14, fill=(124, 140, 255, 255))
    return img


def _with_dot(base, tone: str):
    """The icon with its dot: how things are, at a glance, even at 16 pixels."""
    from PIL import ImageDraw
    img = base.copy()
    d = ImageDraw.Draw(img)
    r = 11
    cx = cy = 64 - r - 3
    d.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), fill=(10, 10, 17, 255))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_TONES.get(tone, _TONES["idle"]) + (255,))
    return img


def _dark_menus():
    """Menus in the dark, like the app: the process asks Windows for dark menus (an undocumented call every dark app makes; Windows 10 1903 and later)."""
    if sys.platform != "win32":
        return
    try:
        if sys.getwindowsversion().build < 18362:
            return
        import ctypes
        ux = ctypes.WinDLL("uxtheme")
        set_mode = ux[135]              # SetPreferredAppMode
        set_mode.argtypes = [ctypes.c_int]
        set_mode(2)                     # ForceDark
        ux[136]()                       # FlushMenuThemes
    except Exception:
        pass


# ── The menu ──────────────────────────────────────────────────────────────────
def _act(fn, *args):
    """A menu action (pystray wants exactly (icon, item)) that runs `fn` off the tray's thread."""
    return lambda _icon, _item: _in_thread(fn, *args)


def _is(value):
    return lambda _item: value


def _menu(pystray):
    Item, Menu = pystray.MenuItem, pystray.Menu
    win = _STATE["windows"]

    def account_items():
        snap = _STATE.get("snapshot") or snapshot()
        out = []
        for c in snap["accounts"]:
            cid = c["id"]
            paused = bool(snap["paused"].get(cid))
            word = _state_word(c, paused)
            if c.get("state") == "running":
                sub = Menu(
                    Item("Replying", _act(_toggle_pause, cid), checked=_is(not paused)),
                    Item("Restart", _act(_restart, cid)),
                    Item("Stop", _act(_stop, cid)),
                )
            else:
                sub = Menu(Item("Start", _act(_start, cid)))
            out.append(Item(f"{c.get('label') or cid}  ·  {word}", sub))
        if not out:
            out.append(Item("No accounts yet", None, enabled=False))
        return tuple(out)

    def go(route):
        return lambda _i, _it: win["show_main"](route)

    def flip(key):
        def act(_i, _it):
            set_pref(key, not prefs().get(key))
        return act

    return Menu(
        # A left click on the icon: the quick panel. Not shown in the menu.
        Item("Quick panel", lambda _i, _it: win["toggle_panel"](), default=True, visible=False),
        Item(lambda _it: f"{APP_TITLE}  ·  {(_STATE.get('snapshot') or {}).get('headline', '')}", None, enabled=False),
        Menu.SEPARATOR,
        Item("Open LLMSelfbot", lambda _i, _it: win["show_main"]("")),
        Item("Go to", Menu(
            Item("Dashboard", go("dashboard")),
            Item("Chats", go("chats")),
            Item("Logs", go("logs")),
            Item("Settings", go("settings")),
            Item("System", go("system")),
        )),
        Menu.SEPARATOR,
        Item("Accounts", Menu(account_items)),
        Item("Pause all replies", _act(_pause_all),
             checked=lambda _it: bool((_STATE.get("snapshot") or {}).get("all_paused"))),
        Item("Restart all accounts", _act(_restart_all)),
        Menu.SEPARATOR,
        Item("Keep running when closed", flip("close_to_tray"), checked=lambda _it: bool(prefs().get("close_to_tray"))),
        Item("Start with Windows", lambda _i, _it: set_autostart(not autostart_on()),
             checked=lambda _it: autostart_on(), visible=can_autostart()),
        Item("Alerts on this computer", flip("alerts"), checked=lambda _it: bool(prefs().get("alerts"))),
        Item("Open data folder", lambda _i, _it: win["open_data"]()),
        Menu.SEPARATOR,
        Item("Quit LLMSelfbot", lambda _i, _it: win["quit"]()),
    )


# ── Keeping the icon, its words and the alerts current ────────────────────────
def _watch(icon, base):
    seen: dict = {}
    while True:
        try:
            snap = snapshot()
            _STATE["snapshot"] = snap
            if snap["tone"] != _STATE.get("tone"):
                _STATE["tone"] = snap["tone"]
                icon.icon = _with_dot(base, snap["tone"])
            title = f"{APP_TITLE} · {snap['headline']}"[:120]
            if icon.title != title:
                icon.title = title
            # An account that crashed, or was given up on, since the last look.
            for c in snap["accounts"]:
                was = seen.get(c["id"])
                now = "gave_up" if c.get("gave_up") else c.get("state")
                if was and was != now and prefs().get("alerts"):
                    label = c.get("label") or c["id"]
                    if now == "gave_up":
                        icon.notify("It crashed several times and was left stopped. Start it again from the app.", f"{label} stopped")
                    elif now == "crashing" and was == "running":
                        icon.notify("It stopped unexpectedly and is being restarted.", f"{label} crashed")
                seen[c["id"]] = now
        except Exception:
            pass
        time.sleep(3)


def start(url: str, supervisor, windows: dict):
    """The icon, its menu and its watcher. `windows` holds the window side: show_main(route), toggle_panel(), open_data(), quit()."""
    try:
        import pystray
    except Exception:
        return None
    _STATE.update(url=url, supervisor=supervisor, windows=windows)
    _dark_menus()
    base = _base_image()

    cls = pystray.Icon
    if sys.platform == "win32":
        class _Icon(pystray.Icon):
            """Rebuilds its menu as a right click opens it, on its own thread, so what it says is current."""
            def _on_notify(self, wparam, lparam):
                try:
                    from pystray._util import win32 as w32
                    if lparam == w32.WM_RBUTTONUP:
                        _STATE["snapshot"] = snapshot()
                        self._update_menu()
                except Exception:
                    pass
                return super()._on_notify(wparam, lparam)
        cls = _Icon

    _STATE["snapshot"] = snapshot()
    icon = cls(APP_TITLE, _with_dot(base, _STATE["snapshot"]["tone"]), APP_TITLE, menu=_menu(pystray))
    _STATE["icon"] = icon
    _STATE["tone"] = _STATE["snapshot"]["tone"]
    threading.Thread(target=icon.run, daemon=True, name="tray").start()
    threading.Thread(target=_watch, args=(icon, base), daemon=True, name="tray-watch").start()
    return icon


def running() -> bool:
    return _STATE.get("icon") is not None


def notify(message: str, title: str = APP_TITLE) -> None:
    icon = _STATE.get("icon")
    if icon is not None:
        try:
            icon.notify(message, title)
        except Exception:
            pass


def stop() -> None:
    icon = _STATE.get("icon")
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass
