"""app/utils/compat.py - what does not work on this device, in a sentence each.

The panel asks once. It says nothing about what works, and puts a short warning
where something that does not would be used: on the Snapchat settings on a
phone, beside voice messages where there is no ffmpeg, on the Updates card of
an iPhone. Most answers are probes of this copy of the app (is there a Chrome,
is ffmpeg on PATH, is curl_cffi in this build), not a table of platforms, so a
Raspberry Pi with Chromium installed is not told Snapchat is impossible, and a
build that is missing a module says so rather than failing when it is used.

Each entry that does not work carries `why`, one short plain sentence, `tag`,
two or three words for where a sentence will not fit ("Needs ffmpeg", "Not on
Android"), and where there is something to do about it, `fix`: a command to
run, or the page that does it.
"""

import importlib.util
import os
import shutil

from app.utils import device

# Everything the panel may warn about, in the order the System page lists them.
FEATURES = {
    "discord": "Discord accounts",
    "discord_many": "Several Discord accounts",
    "browser_login": "Signing in with a browser",
    "snapchat": "Snapchat",
    "local_start": "Starting AI servers",
    "voice_messages": "Voice messages",
    "voice_calls": "Voice calls",
    "heic": "iPhone photos (HEIC)",
    "files_save": "Saving files",
    "files_pick": "Picking files",
    "folders": "Opening folders",
    "update": "Updating itself",
    "background": "Running in the background",
}


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _ffmpeg() -> bool:
    try:
        from app.utils import binaries
        return bool(binaries.find("ffmpeg"))
    except Exception:
        return bool(shutil.which("ffmpeg"))


def _chromium() -> bool:
    """A Chrome or Chromium this machine already has, for Linux on ARM."""
    override = os.environ.get("PUPPETEER_EXECUTABLE_PATH", "").strip()
    if override and os.path.isfile(override):
        return True
    return any(shutil.which(b) for b in ("chromium", "chromium-browser", "google-chrome",
                                          "google-chrome-stable", "microsoft-edge"))


def _install_hint(family: str, package: str) -> str:
    if family == "macos":
        return f"brew install {package}"
    return f"sudo apt install {package}"


def check(feature: str, name: str | None = None) -> dict | None:
    """None when `feature` works on this device, else {"why", "fix"?}."""
    name = name or device.detect()
    info = device.DEVICES.get(name, {})
    family = info.get("family", "")
    phone = bool(info.get("phone"))
    label = device.label(name)
    pretend = os.environ.get("LLMSELFBOT_DEVICE", "").strip().lower() in device.DEVICES

    if feature == "discord":
        # The iPhone build has no curl_cffi, which Discord's library needs for
        # every request (nobody publishes it for iOS). When only pretending to
        # be an iPhone, say what the real one would.
        if name == "ios" and (pretend or not _has("curl_cffi")):
            return {"why": "Discord doesn't run on iPhone yet."}
        if not pretend and not (_has("discord") and _has("curl_cffi")):
            return {"why": "Discord isn't in this build.", "tag": "Not in this build"}
        return None

    if feature == "discord_many":
        if phone or device.single_process():
            return {"why": f"One Discord account runs at a time on {_on(label)}.", "tag": "One at a time"}
        return None

    if feature == "browser_login":
        # It drives a Chrome window through Node, as Snapchat does.
        if phone:
            return {"why": "Needs a computer. Paste a token instead."}
        return None

    if feature == "snapchat":
        if phone:
            return {"why": "Snapchat needs a computer."}
        if name in ("linux-arm64", "linux-arm") and (pretend or not _chromium()):
            return {"why": "Needs Chromium. Chrome has no ARM Linux build.", "tag": "Needs Chromium",
                    "fix": {"command": "sudo apt install chromium"}}
        return None

    if feature == "local_start":
        if phone:
            return {"why": "Phones can't run AI servers. Use one on your network."}
        return None

    if feature == "voice_messages":
        if phone:
            return {"why": "Needs ffmpeg, which phones don't have."}
        if pretend or _ffmpeg():
            return None
        if family == "windows":
            return {"why": "Needs ffmpeg.", "tag": "Needs ffmpeg",
                    "fix": {"route": "system", "label": "Get it on System"}}
        return {"why": "Needs ffmpeg.", "tag": "Needs ffmpeg", "fix": {"command": _install_hint(family, "ffmpeg")}}

    if feature == "voice_calls":
        if phone:
            return {"why": "Needs a computer."}
        if not pretend and not (_has("davey") and _has("nacl")):
            return {"why": "Needs davey and PyNaCl.", "tag": "Needs davey",
                    "fix": {"command": "pip install davey pynacl"}}
        return None

    if feature == "heic":
        # An iPhone turns its photos into JPEGs as they are picked, so the
        # missing library only matters where HEIC files arrive as they are.
        if name == "ios":
            return None
        if (pretend and phone) or (not pretend and not _has("pillow_heif")):
            return {"why": "HEIC photos can't be opened here. Save them as JPEG.", "tag": "No HEIC"}
        return None

    if feature == "files_save":
        if phone:
            return {"why": f"Can't save files in the {label} app."}
        return None

    if feature == "files_pick":
        # iOS's web view brings up its own picker; Android's does nothing.
        if name == "android":
            return {"why": "Can't pick files in the Android app yet. Use a computer."}
        return None

    if feature == "folders":
        if phone:
            return {"why": "No file manager to open it in."}
        if family == "linux" and not pretend and not shutil.which("xdg-open"):
            return {"why": "No file manager to open it in.", "tag": "No file manager"}
        return None

    if feature == "update":
        method = device.update_method(name)
        if method == "sideload":
            return {"why": "iPhone apps can't update themselves. Reinstall the new IPA with AltStore or SideStore."}
        if method == "none":
            return {"why": f"No build for {label} is published, so it can't update itself.", "tag": "No build"}
        return None

    if feature == "background":
        if name == "ios":
            return {"why": "iOS pauses apps in the background. Keep it open.", "tag": "Keep it open"}
        if name == "android":
            return {"why": "Android may stop it in the background. Keep it open or turn off battery saving for it.",
                    "tag": "Keep it open"}
        return None

    return None


def _on(label: str) -> str:
    """"an iPhone", "Android": the article only where English wants one."""
    return f"an {label}" if label in ("iPhone", "iPad") else label


def report() -> dict:
    """This device, and each feature that does not work on it."""
    summary = device.summary()
    missing = {}
    for feature, title in FEATURES.items():
        try:
            problem = check(feature, summary["name"])
        except Exception:
            problem = None     # a probe that fails is not a reason to warn
        if problem:
            missing[feature] = {"label": title, "tag": f"Not on {summary['label']}", **problem}
    return {"device": summary, "missing": missing}
