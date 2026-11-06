"""External tools the app can fetch on demand. ffmpeg cannot be bundled into the Python exe (licence + ~80 MB), so it is downloaded into DATA_DIR/bin on request. Everything that shells out to ffmpeg finds it via PATH, which ensure_path() extends at startup."""

import os
import shutil
import zipfile

from app.utils.paths import APP_DIR, DATA_DIR

BIN_DIR = DATA_DIR / "bin"

# Static Windows build; gyan.dev is the build ffmpeg.org links to for Windows.
FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_EXE = ".exe" if os.name == "nt" else ""

# libopus for live Discord voice calls: decoded and encoded through discord.opus, which wants the shared library.
# PyOgg's Windows wheels carry a plain opus.dll (libopus is BSD, so bundling it is fine), and PyPI is a stable,
# checksummed host - fetched on demand, like ffmpeg, so nothing big ships inside the app.
PYOGG_JSON_URL = "https://pypi.org/pypi/PyOgg/json"


def ensure_path() -> None:
    """Put DATA_DIR/bin (and any bundled resources/bin) on PATH for this process and every child it spawns."""
    for d in (BIN_DIR, APP_DIR / "resources" / "bin"):
        if d.is_dir():
            current = os.environ.get("PATH", "")
            if str(d) not in current.split(os.pathsep):
                os.environ["PATH"] = str(d) + os.pathsep + current


def find(name: str) -> str | None:
    """Locate a tool, preferring our own bin dir over the system one."""
    ensure_path()
    local = BIN_DIR / f"{name}{_EXE}"
    if local.is_file():
        return str(local)
    return shutil.which(name)


def ffmpeg_status() -> dict:
    return {
        "ffmpeg": find("ffmpeg"),
        "ffprobe": find("ffprobe"),
        "bundled": (BIN_DIR / f"ffmpeg{_EXE}").is_file(),
        "bin_dir": str(BIN_DIR),
        "installable": os.name == "nt",
    }


def install_ffmpeg(progress=None) -> dict:
    """Download a static ffmpeg build into DATA_DIR/bin. progress: optional callable(str) for streaming status to the UI."""
    def say(msg):
        if progress:
            progress(msg)

    if os.name != "nt":
        return {"ok": False, "reason": "Auto-install is Windows-only - "
                                       "use your package manager (apt/brew install ffmpeg)."}
    if find("ffmpeg") and find("ffprobe"):
        return {"ok": True, "reason": "already installed", "path": find("ffmpeg")}

    import urllib.request

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    archive = BIN_DIR / "ffmpeg-download.zip"
    try:
        say("Downloading ffmpeg (~80 MB)...")
        last = [0]

        def _hook(blocks, block_size, total):
            if not total or not progress:
                return
            pct = min(100, int(blocks * block_size * 100 / total))
            if pct >= last[0] + 10:
                last[0] = pct
                say(f"Downloading ffmpeg... {pct}%")

        urllib.request.urlretrieve(FFMPEG_WIN_URL, archive, reporthook=_hook)

        say("Extracting...")
        wanted = {f"ffmpeg{_EXE}", f"ffprobe{_EXE}"}
        found = set()
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                base = member.rsplit("/", 1)[-1]
                if base in wanted:
                    with zf.open(member) as src, open(BIN_DIR / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.add(base)
        if not found:
            return {"ok": False, "reason": "archive did not contain ffmpeg"}
        ensure_path()
        say(f"ffmpeg installed to {BIN_DIR}")
        return {"ok": True, "path": str(BIN_DIR / f"ffmpeg{_EXE}"), "installed": sorted(found)}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    finally:
        archive.unlink(missing_ok=True)


def opus_status() -> dict:
    """Whether a libopus DLL is in place for voice calls, and where it is or would be."""
    dll = _opus_names()[0]
    return {"dll": str(dll) if dll.is_file() else "", "bundled": dll.is_file(), "bin_dir": str(BIN_DIR)}


def _opus_names() -> tuple:
    return (BIN_DIR / "opus.dll", BIN_DIR / "libopus-0.x64.dll", BIN_DIR / "libopus-0.dll")


def _opus_dll() -> str | None:
    """The opus library on disk, or None. Checks the bundled spots and anything discord.opus already loaded."""
    try:
        from discord import opus
        if opus.is_loaded():
            return "__loaded__"
    except Exception:
        pass
    for p in _opus_names():
        if p.is_file():
            return str(p)
    return None


def install_opus(progress=None) -> dict:
    """Fetch opus.dll (out of a PyOgg wheel, Windows-only) into DATA_DIR/bin, for voice calls."""
    def say(msg):
        if progress:
            progress(msg)

    if os.name != "nt":
        return {"ok": False, "reason": "Auto-install is Windows-only - "
                                       "use your package manager (apt/brew install libopus0)."}
    if _opus_dll():
        return {"ok": True, "reason": "already installed", "path": _opus_dll()}

    import json
    import urllib.request

    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        say("Finding the opus library...")
        with urllib.request.urlopen(PYOGG_JSON_URL, timeout=30) as r:
            meta = json.loads(r.read().decode("utf-8"))
        wheel = None
        for files in reversed(list((meta.get("releases") or {}).values())):
            for f in files or []:
                name = str(f.get("filename") or "")
                if name.endswith("win_amd64.whl"):
                    wheel = f.get("url")
                    break
            if wheel:
                break
        if not wheel:
            return {"ok": False, "reason": "no Windows build of PyOgg was found"}
        say("Downloading the opus library...")
        archive = BIN_DIR / "opus-download.zip"
        urllib.request.urlretrieve(wheel, archive)
        say("Extracting...")
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if member.rsplit("/", 1)[-1].lower() == "opus.dll":
                    with zf.open(member) as src, open(BIN_DIR / "opus.dll", "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break
            else:
                return {"ok": False, "reason": "the wheel did not contain opus.dll"}
        ensure_path()
        say(f"opus installed to {BIN_DIR}")
        return {"ok": True, "path": str(BIN_DIR / "opus.dll")}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    finally:
        for stray in ("opus-download.zip",):
            (BIN_DIR / stray).unlink(missing_ok=True)
