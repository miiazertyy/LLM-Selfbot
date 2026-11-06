"""ViaProxy, on demand: what lets a Minecraft account join a server of any version.

The bot (mineflayer, in mindcraft) plays the version mindcraft knows best, and ViaProxy, between it and the server,
speaks the server's own, older or newer, both ways: ViaVersion, ViaBackwards, ViaRewind and ViaLegacy, put together
as a proxy by the ViaVersion project. It is to this bot what ViaFabricPlus is to a Fabric client (the bot is not a
Fabric client, so no client mod loads into it).

Downloaded from ViaProxy's own GitHub releases when Settings, Minecraft asks, the newest release then, since servers
move to new versions all the time and a pinned one would fall behind. Java runs it: the Java this computer has, 8 or
newer (ViaProxy publishes a build for Java 8, and its main one for 21 and up).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

from app.utils.paths import DATA_DIR

VIA_DIR = DATA_DIR / "minecraft" / "viaproxy"
JAR = VIA_DIR / "ViaProxy.jar"
MARKER = VIA_DIR / ".llmselfbot-install.json"
RELEASES = "https://api.github.com/repos/ViaVersion/ViaProxy/releases/latest"
# The version the bot plays when ViaProxy is between it and the server: mindcraft's own, and the newest the live
# view has pictures for.
BOT_VERSION = "1.21.4"


def java() -> tuple[str, int]:
    """(path, major version) of the Java on this computer's PATH; ("", 0) with none. "1.8.0_431" is Java 8."""
    from app.utils.procs import quiet_kwargs
    exe = shutil.which("java")
    if not exe:
        return "", 0
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=30, **quiet_kwargs())
    except Exception:
        return exe, 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', (r.stderr or "") + (r.stdout or ""))
    if not m:
        return exe, 0
    major = int(m.group(1))
    if major == 1 and m.group(2):
        major = int(m.group(2))
    return exe, major


def present() -> bool:
    return JAR.is_file() and MARKER.is_file()


def status() -> dict:
    exe, major = java()
    info = {}
    if MARKER.is_file():
        try:
            info = json.loads(MARKER.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    return {"java": exe, "java_major": major, "java_ok": major >= 8, "installed": present(),
            "version": str(info.get("version") or ""), "build": str(info.get("build") or "")}


def pick_asset(release: dict, java_major: int) -> dict | None:
    """The jar for this Java: the "+java8" build below Java 21, the main one from 21 on."""
    jars = [a for a in release.get("assets") or [] if str(a.get("name", "")).endswith(".jar")]
    eight = [a for a in jars if "+java8" in a["name"]]
    main = [a for a in jars if "+java" not in a["name"]]
    if java_major >= 21 and main:
        return main[0]
    return (eight or main or [None])[0] if java_major >= 8 else None


def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "LLMSelfbot", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download(url: str, dest: Path, say, tries: int = 3) -> None:
    """To dest, whole or not at all, a few tries: this computer's connection drops now and then."""
    part = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LLMSelfbot"})
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as out:
                total = int(r.headers.get("Content-Length") or 0)
                got, shown = 0, 0.0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
                    if total and time.time() - shown > 3:
                        shown = time.time()
                        say(f"Downloading ViaProxy: {got * 100 // total}%")
            if total and part.stat().st_size != total:
                raise OSError(f"got {part.stat().st_size} of {total} bytes")
            os.replace(part, dest)
            return
        except Exception as e:          # a dropped connection: again, from the start
            last = e
            say(f"The download stopped ({e}); trying again ({attempt}/{tries})")
            time.sleep(2 * attempt)
    part.unlink(missing_ok=True)
    raise RuntimeError(f"ViaProxy could not be downloaded: {last}")


def is_viaproxy_jar(path: Path) -> bool:
    """A jar, and ViaProxy's: its manifest names ViaProxy's own main class."""
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as z:
            manifest = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
        return "net.raphimc.viaproxy" in manifest
    except (OSError, KeyError, zipfile.BadZipFile):
        return False


def install(say) -> None:
    exe, major = java()
    if major < 8:
        raise RuntimeError("ViaProxy runs on Java, and this computer has none that it can find. Install Java "
                           "(adoptium.net, version 21 or newer), then try again.")
    say(f"Java {major} found. Looking up the newest ViaProxy")
    release = json.loads(_get(RELEASES).decode("utf-8"))
    asset = pick_asset(release, major)
    if not asset:
        raise RuntimeError("ViaProxy's newest release has no jar for this Java")
    VIA_DIR.mkdir(parents=True, exist_ok=True)
    new = VIA_DIR / "ViaProxy.new.jar"
    say(f"Downloading {asset['name']} ({int(asset.get('size') or 0) // (1 << 20)} MB)")
    _download(asset["browser_download_url"], new, say)
    if not is_viaproxy_jar(new):
        new.unlink(missing_ok=True)
        raise RuntimeError("What was downloaded is not ViaProxy; nothing was changed")
    os.replace(new, JAR)
    MARKER.write_text(json.dumps({"version": str(release.get("tag_name") or ""), "build": asset["name"],
                                  "java": major, "at": time.time()}), encoding="utf-8")
    say(f"ViaProxy {release.get('tag_name', '')} is ready")


def uninstall(say) -> None:
    if VIA_DIR.exists():
        shutil.rmtree(VIA_DIR, ignore_errors=True)
    say("ViaProxy removed")


def config_for(target_host: str, target_port: int, auth: str, mode: str) -> dict | None:
    """What the runner needs to put ViaProxy in front of this server, or None to join it directly: when
    translation is off or not installed, without Java, or for a server that needs a Microsoft sign-in (ViaProxy
    would need the account itself, from its own window; mineflayer joins those from 1.8 to 26.1 by itself).
    mode "auto" leaves the runner to ask the server its version first and only use it off 1.21; "always", for
    every server."""
    if mode not in ("auto", "always") or auth != "offline" or not present():
        return None
    exe, major = java()
    if major < 8:
        return None
    return {"java": exe, "jar": str(JAR), "dir": str(VIA_DIR), "target": f"{target_host}:{int(target_port)}",
            "version": BOT_VERSION, "mode": mode}
