"""app/core/update.py - updating to the latest release, on whatever this runs on.

The release is the tag: GitHub's latest release names the version, and each
device has its own file on it (app/utils/device.py knows which). Putting that
file in place depends on how this copy was installed:

  installer  Windows, installed: the new installer runs silently once this
             app has closed, then starts the app again.
  replace    the single Windows exe, and the Linux and macOS binaries: the new
             file takes the old one's place and is started. A running exe on
             Windows cannot be overwritten but can be renamed, so the old one
             steps aside first and is deleted on the next start.
  download   Android: the new APK is handed to Android, which asks to install
             it. It installs over the old one, keeping everything.
  sideload   iPhone: an app cannot replace itself, so the release page opens
             to get the new IPA, installed again with AltStore or SideStore.
  git        a source checkout: the updater scripts pull the release.

A download is checked against the size and, where GitHub gives it, the SHA-256
of the release asset before anything is replaced.
"""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from app.utils import device

API = f"https://api.github.com/repos/{device.REPO}/releases/latest"

# What each device's file has been called: the current name first, then the
# older one ("selfbot-linux-aarch64") that releases up to 1.7.0 used.
_NAMES = {
    "windows-installer": ("LLMSelfbotSetup.exe",),
    "windows-portable": ("LLMSelfbot-portable.exe",),
    "linux-x64": ("LLMSelfbot-linux-x86_64", "selfbot-linux-x86_64"),
    "linux-arm64": ("LLMSelfbot-linux-aarch64", "selfbot-linux-aarch64"),
    "macos-arm64": ("LLMSelfbot-macos-arm64", "selfbot-macos-arm64"),
    "android": ("LLMSelfbot-android.apk",),
    "ios": ("LLMSelfbot-ios.ipa",),
}

_busy = threading.Lock()


def _key(name: str, how: str) -> str:
    if name.startswith("windows"):
        return "windows-portable" if how == "portable" else "windows-installer"
    return name


def latest(timeout: float = 10) -> dict:
    """The latest release: its tag, page, notes and files."""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "LLMSelfbot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return {
        "tag": data.get("tag_name", ""),
        "page": data.get("html_url", "") or device.RELEASES,
        "notes": (data.get("body") or "")[:4000],
        "published": data.get("published_at", ""),
        "assets": [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
                    "size": int(a.get("size") or 0), "digest": a.get("digest") or ""}
                   for a in data.get("assets", []) or []],
    }


def pick(release: dict, name: str | None = None, how: str | None = None) -> dict | None:
    """This device's file on `release`, or None if it has none."""
    name = name or device.detect()
    how = how or device.install()
    wanted = _NAMES.get(_key(name, how), ())
    by_name = {a["name"]: a for a in release.get("assets", [])}
    for candidate in wanted:
        if candidate in by_name:
            return by_name[candidate]
    return None


def plan(release: dict, name: str | None = None, how: str | None = None, current: str | None = None) -> dict:
    """What updating to `release` would do here: the method, the file, and
    whether it can be done from the panel at all (`ready`), with the reason
    when it cannot."""
    name = name or device.detect()
    how = how or device.install()
    method = device.update_method(name, how)
    out = {"method": method, "asset": None, "ready": False, "why": ""}
    if method == "git":
        out["ready"] = True
        return out
    if method == "none":
        out["why"] = f"No build for {device.label(name)} is published."
        return out
    # A build made without a release tag reports 0.0.0-dev, so every release
    # looks newer than it; replacing it with one would as likely go back as
    # forward. Such a build says where the releases are and leaves it there.
    if current is None:
        from app.version import __version__ as current
    if str(current).startswith("0.0.0"):
        out["why"] = "This is a development build. Install a release to update from it."
        return out
    asset = pick(release, name, how)
    if asset is None:
        out["why"] = f"This release has no {device.label(name)} build."
        return out
    out["asset"] = {"name": asset["name"], "size": asset["size"], "url": asset["url"]}
    out["ready"] = True
    return out


# ── Doing it ─────────────────────────────────────────────────────────────────

def _say(text: str, level: str = "info"):
    try:
        from app.web.logbus import bus
        bus.append("system", text, level)
    except Exception:
        print(f"[Update] {text}", flush=True)


def download(asset: dict, dest: Path, progress=None) -> Path:
    """Fetch `asset` to `dest`, checked against its size and digest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    total = int(asset.get("size") or 0)
    done = 0
    last = -1
    req = urllib.request.Request(asset["url"], headers={"User-Agent": "LLMSelfbot"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        while True:
            block = r.read(1 << 16)
            if not block:
                break
            f.write(block)
            digest.update(block)
            done += len(block)
            if progress and total:
                pct = done * 100 // total
                if pct // 10 != last // 10:
                    progress(pct)
                    last = pct
    if total and done != total:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"the download stopped at {done} of {total} bytes")
    want = str(asset.get("digest") or "")
    if want.startswith("sha256:") and want[7:].lower() != digest.hexdigest():
        part.unlink(missing_ok=True)
        raise RuntimeError("the download does not match the release's checksum")
    os.replace(part, dest)
    return dest


def _relaunch_env(port) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "LLMSELFBOT_CHILD"}
    env["LLMSELFBOT_RESTART"] = "1"      # wait for this one's lock, not give up
    if port:
        env["SELFBOT_PORT"] = str(port)
    return env


def _stop(supervisor):
    if supervisor is None:
        return
    try:
        supervisor.stop_all()
    except Exception as exc:
        _say(f"Could not stop the accounts cleanly: {exc}", "warn")


def _replace_and_restart(new: Path, supervisor, port):
    """Swap the running file for `new` and start it. Does not return."""
    from app.utils.procs import quiet_kwargs
    exe = Path(sys.executable).resolve()
    if sys.platform == "win32":
        old = exe.with_name(exe.name + ".old")
        old.unlink(missing_ok=True)
        os.replace(exe, old)          # a running exe can be renamed, not overwritten
        try:
            os.replace(new, exe)
        except OSError:
            os.replace(old, exe)      # put it back rather than leave nothing
            raise
    else:
        os.chmod(new, 0o755)
        os.replace(new, exe)          # the running one keeps its open copy
    _stop(supervisor)
    subprocess.Popen([str(exe)], cwd=str(exe.parent), env=_relaunch_env(port), close_fds=True,
                     **quiet_kwargs())
    os._exit(0)


def _ps(path) -> str:
    """A path as a PowerShell string: quoted, with its own quotes doubled."""
    return "'" + str(path).replace("'", "''") + "'"


def _installer_and_restart(setup: Path, supervisor, port):
    """Run the new installer once this app has closed, then start it again."""
    from app.utils.procs import quiet_kwargs
    exe = Path(sys.executable).resolve()
    script = setup.with_name("update.ps1")
    # The installer's own "launch it" step is skipped when it runs silently,
    # so the script starts the app itself once the installer is done.
    script.write_text(
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"Wait-Process -Id {os.getpid()} -Timeout 60\n"
        f"Start-Process -FilePath {_ps(setup)} -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait\n"
        f"Start-Process -FilePath {_ps(exe)}\n"
        f"Remove-Item -LiteralPath {_ps(setup)} -Force\n",
        encoding="utf-8")
    _stop(supervisor)
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                      "-WindowStyle", "Hidden", "-File", str(script)],
                     cwd=str(setup.parent), env=_relaunch_env(port), close_fds=True, **quiet_kwargs())
    os._exit(0)


def run(supervisor=None, port=None, wait=False) -> dict:
    """Start updating to the latest release. Returns at once with what it is
    doing; the download and the swap happen on a thread, reported to the log.
    `wait` does it all before returning, for the command line."""
    from app.utils.paths import APP_DIR, DATA_DIR

    name = device.detect()
    how = device.install()
    method = device.update_method(name, how)

    if method == "git":
        script = APP_DIR / ("scripts/updater.bat" if os.name == "nt" else "scripts/updater.sh")
        if not script.exists():
            return {"ok": False, "reason": "The updater script is missing."}
        if os.name == "nt":
            subprocess.Popen(f'cmd /c start "Updating" /d "{APP_DIR}" "{script}" release', shell=True, cwd=APP_DIR)
        else:
            subprocess.Popen(["bash", str(script), "release"], start_new_session=True, cwd=APP_DIR)
        _say("Updater launched - the app will restart after updating.")
        return {"ok": True, "method": method, "queued": True}

    try:
        release = latest()
    except Exception as exc:
        return {"ok": False, "reason": f"Could not reach GitHub: {exc}"}
    p = plan(release, name, how)
    if not p["ready"]:
        return {"ok": False, "method": method, "reason": p["why"]}

    if method in ("download", "sideload"):
        # The phone does the installing. Android opens the APK and offers to
        # install it; an iPhone gets the release page and its IPA.
        url = p["asset"]["url"] if method == "download" else release["page"]
        opened = device.open_url(url)
        return {"ok": True, "method": method, "url": url, "opened": opened}

    if not _busy.acquire(blocking=False):
        return {"ok": False, "reason": "An update is already downloading."}

    asset = p["asset"]

    def work():
        try:
            _say(f"Downloading {release['tag']} ({asset['size'] // (1024 * 1024)} MB).")
            if method == "installer":
                dest = DATA_DIR / "update" / asset["name"]
            else:
                # Beside the running file, so the swap is a rename on one disk.
                exe = Path(sys.executable).resolve()
                dest = exe.with_name(exe.name + ".new")
            download(asset, dest, progress=lambda pct: _say(f"Downloading the update: {pct}%"))
            _say(f"Installing {release['tag']}. The app will restart.")
            if method == "installer":
                _installer_and_restart(dest, supervisor, port)
            else:
                _replace_and_restart(dest, supervisor, port)
        except Exception as exc:
            _say(f"The update failed: {exc}", "error")
        finally:
            _busy.release()

    if wait:
        work()
    else:
        threading.Thread(target=work, daemon=True, name="update").start()
    return {"ok": True, "method": method, "queued": True, "asset": asset["name"]}


def clean_leftovers():
    """Delete what the last update left: the old exe it stepped aside from, and
    a download it never finished. Called at startup."""
    if not getattr(sys, "frozen", False):
        return
    try:
        exe = Path(sys.executable).resolve()
        for extra in (exe.with_name(exe.name + ".old"), exe.with_name(exe.name + ".new.part")):
            if extra.exists():
                for _ in range(20):          # the old one may still be closing
                    try:
                        extra.unlink()
                        break
                    except OSError:
                        time.sleep(0.25)
    except Exception:
        pass
