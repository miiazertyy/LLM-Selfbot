"""
app/utils/backdrop.py - Windows window appearance for the desktop shell.

The app used to offer Windows 11 Mica/Acrylic backdrops behind a transparent
window. DWM tints those toward the desktop wallpaper, so the window came back
bright and inconsistent no matter how the tint was pinned, they were removed,
and the UI now paints its own opaque background.

What remains is the part that is still needed: mark the window dark, so Windows
doesn't draw light-mode chrome around it, and positively clear any backdrop or
blur a previous build left applied to the window.

Everything degrades to a no-op off Windows, and callers just get False back.
"""

import ctypes
import sys
from ctypes import wintypes

# DwmSetWindowAttribute attributes
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38

DWMSBT_NONE = 1            # solid, the only one we ask for now

# SetWindowCompositionAttribute (undocumented), used solely to switch OFF a
# blur/acrylic effect that an older version of this app may have enabled.
WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),   # 0xAABBGGRR
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attrib", ctypes.c_int),
        ("pvData", ctypes.c_void_p),
        ("cbData", ctypes.c_size_t),
    ]


def _build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def supported() -> bool:
    """True when this build of Windows understands the backdrop attributes."""
    return sys.platform == "win32" and _build() >= 22621


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    try:
        dwm = ctypes.windll.dwmapi
        val = ctypes.c_int(value)
        res = dwm.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), ctypes.c_uint(attr),
            ctypes.byref(val), ctypes.sizeof(val),
        )
        return res == 0
    except Exception:
        return False


def clear_composition(hwnd: int) -> bool:
    """Switch off any blur/acrylic previously applied to this window."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        fn = getattr(ctypes.windll.user32, "SetWindowCompositionAttribute", None)
        if fn is None:
            return False
        accent = ACCENT_POLICY(ACCENT_DISABLED, 0, 0, 0)
        data = WINDOWCOMPOSITIONATTRIBDATA(
            WCA_ACCENT_POLICY, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p),
            ctypes.sizeof(accent))
        return bool(fn(wintypes.HWND(hwnd), ctypes.byref(data)))
    except Exception:
        return False


def apply(hwnd: int, kind: str = "none", dark: bool = True) -> bool:
    """Put the window in dark mode with no system backdrop.

    `kind` is accepted for call compatibility; every value is treated as
    "none" now that the translucent themes are gone.
    """
    if not hwnd:
        return False
    # Without this Windows renders light-mode chrome around the window.
    _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    clear_composition(hwnd)
    if not supported():
        return True          # dark mode applied; the backdrop attr is optional
    return _set_attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)


def find_hwnd(title: str) -> int:
    """Locate a top-level window by exact title (pywebview doesn't expose its HWND)."""
    if sys.platform != "win32":
        return 0
    try:
        user32 = ctypes.windll.user32
        found = ctypes.c_void_p(0)
        buf = ctypes.create_unicode_buffer(512)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
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
