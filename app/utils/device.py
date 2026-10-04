"""app/utils/device.py - what this copy of the app is running on, and how it got there.

One answer, asked by three things that must agree: the update check (which
file on a release is this device's, and how to put it in place), the
compatibility notes (what works here and what does not), and the supervisor
(whether an account can have a process of its own, which a phone cannot).

LLMSELFBOT_DEVICE pretends to be another device ("android", "linux-arm64",
...), so how the app looks and behaves there can be seen and tested without
one. The phone apps set LLMSELFBOT_SHELL to "android" or "ios" before the app
is imported: that, not the platform alone, is what says this is the packaged
phone app rather than, say, Python run by hand in Termux.
"""

import os
import platform
import sys
from pathlib import Path

REPO = "miiazertyy/LLM-Selfbot"
RELEASES = f"https://github.com/{REPO}/releases/latest"

# Every device the app knows. `phone`: a device where the app is one process
# with a window of its own, not a desktop program.
DEVICES = {
    "windows-x64": {"label": "Windows", "family": "windows", "phone": False},
    "windows-arm64": {"label": "Windows on ARM", "family": "windows", "phone": False},
    "macos-arm64": {"label": "macOS", "family": "macos", "phone": False},
    "macos-x64": {"label": "macOS on Intel", "family": "macos", "phone": False},
    "linux-x64": {"label": "Linux", "family": "linux", "phone": False},
    "linux-arm64": {"label": "Linux on ARM", "family": "linux", "phone": False},
    "linux-arm": {"label": "32-bit ARM Linux", "family": "linux", "phone": False},
    "android": {"label": "Android", "family": "android", "phone": True},
    "ios": {"label": "iPhone", "family": "ios", "phone": True},
}

# The file each device downloads from a release. Windows has two, chosen by how
# it was installed. The workflow (.github/workflows/build-exe.yml) publishes
# exactly these names; tests/test_devices.py checks the two lists agree.
ASSETS = {
    "windows-installer": "LLMSelfbotSetup.exe",
    "windows-portable": "LLMSelfbot-portable.exe",
    "linux-x64": "LLMSelfbot-linux-x86_64",
    "linux-arm64": "LLMSelfbot-linux-aarch64",
    "macos-arm64": "LLMSelfbot-macos-arm64",
    "android": "LLMSelfbot-android.apk",
    "ios": "LLMSelfbot-ios.ipa",
}


def _machine() -> str:
    try:
        return (platform.machine() or "").lower()
    except Exception:
        return ""


def _is_android() -> bool:
    # 3.13 and later say so; Chaquopy's older builds say "linux" and have this.
    return sys.platform == "android" or hasattr(sys, "getandroidapilevel")


def _is_ios() -> bool:
    if sys.platform in ("ios", "ipados"):
        return True
    try:
        return platform.system() in ("iOS", "iPadOS")
    except Exception:
        return False


def detect() -> str:
    """This device's name, one of DEVICES."""
    pretend = os.environ.get("LLMSELFBOT_DEVICE", "").strip().lower()
    if pretend in DEVICES:
        return pretend
    shell = os.environ.get("LLMSELFBOT_SHELL", "").strip().lower()
    if shell in ("android", "ios"):
        return shell
    if _is_ios():
        return "ios"
    if _is_android():
        return "android"
    arm64 = _machine() in ("arm64", "aarch64", "armv8l", "armv8b")
    if sys.platform == "win32":
        return "windows-arm64" if arm64 else "windows-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if arm64 else "macos-x64"
    if arm64:
        return "linux-arm64"
    if _machine().startswith("arm"):
        return "linux-arm"
    return "linux-x64"


def label(name: str | None = None) -> str:
    name = name or detect()
    if name == "ios":
        # An iPad says so, for the one sentence where it matters.
        try:
            if "ipad" in (platform.ios_ver().model or "").lower():   # type: ignore[attr-defined]
                return "iPad"
        except Exception:
            pass
    return DEVICES.get(name, {}).get("label", name)


def is_phone(name: str | None = None) -> bool:
    return bool(DEVICES.get(name or detect(), {}).get("phone"))


def single_process() -> bool:
    """Whether accounts have to run inside this process rather than beside it.

    True in the phone apps: iOS never lets an app start another process, and
    Android has no Python for it to start. LLMSELFBOT_INPROCESS=1 forces it
    anywhere, which is how it is tested on a computer.
    """
    if os.environ.get("LLMSELFBOT_INPROCESS", "").strip() == "1":
        return True
    shell = os.environ.get("LLMSELFBOT_SHELL", "").strip().lower()
    return shell in ("android", "ios") or _is_ios()


def install() -> str:
    """How this copy was installed, which decides how it updates.

    "apk" / "ipa": the phone apps. "source": a checkout run with Python.
    "installer": the Windows folder build, which is what the installer puts in
    place. "portable": the single Windows exe. "binary": the single file built
    for Linux and macOS.
    """
    shell = os.environ.get("LLMSELFBOT_SHELL", "").strip().lower()
    # Pretending to be a phone pretends to be its app, too.
    pretend = os.environ.get("LLMSELFBOT_DEVICE", "").strip().lower()
    if shell == "android" or pretend == "android":
        return "apk"
    if shell == "ios" or pretend == "ios" or _is_ios():
        return "ipa"
    if not getattr(sys, "frozen", False):
        return "source"
    if sys.platform != "win32":
        return "binary"
    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "unins000.exe").exists():
        return "installer"
    # A single-file build unpacks itself somewhere else each run; the folder
    # build's files sit beside it (in _internal since PyInstaller 6).
    meipass = Path(getattr(sys, "_MEIPASS", exe_dir)).resolve()
    if meipass in (exe_dir, exe_dir / "_internal"):
        return "installer"
    return "portable"


def asset(name: str | None = None, how: str | None = None) -> str | None:
    """The release file this device updates from, or None if there is none."""
    name = name or detect()
    how = how or install()
    if name.startswith("windows"):
        # Windows on ARM runs the x64 build.
        return ASSETS["windows-portable" if how == "portable" else "windows-installer"]
    return ASSETS.get(name)


def update_method(name: str | None = None, how: str | None = None) -> str:
    """How an update is put in place here.

    "git": the source updater scripts. "installer": run the new installer
    quietly, then start the app again. "replace": swap the file for the new
    one and start it. "download": hand the new APK to Android, which asks to
    install it. "sideload": an iPhone app cannot replace itself; the new IPA
    is installed with AltStore or SideStore. "none": no build for this device.
    """
    name = name or detect()
    how = how or install()
    if how == "source":
        return "git"
    if asset(name, how) is None:
        return "none"
    return {"installer": "installer", "portable": "replace", "binary": "replace",
            "apk": "download", "ipa": "sideload"}.get(how, "none")


# The phone apps hand the app a way to open a link outside it: the panel runs
# in the app's own web view there, and following a link inside it would leave
# the panel with no way back.
_url_opener = None


def set_url_opener(fn) -> None:
    global _url_opener
    _url_opener = fn


def open_url(url: str) -> bool:
    """Open a link in the device's browser (or, for an APK, its installer)."""
    if _url_opener is not None:
        try:
            _url_opener(url)
            return True
        except Exception:
            return False
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        return False


def summary() -> dict:
    """Everything the panel needs to know about this device, in one answer."""
    name = detect()
    how = install()
    return {
        "name": name,
        "label": label(name),
        "family": DEVICES.get(name, {}).get("family", ""),
        "phone": is_phone(name),
        "install": how,
        "single_process": single_process(),
        "asset": asset(name, how),
        "update": update_method(name, how),
        "pretend": os.environ.get("LLMSELFBOT_DEVICE", "").strip().lower() in DEVICES,
    }
