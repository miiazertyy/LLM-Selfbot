import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.utils.paths import APP_DIR, DATA_DIR, is_portable
from app.version import __version__, is_newer
from app.utils.procs import quiet_kwargs
from app.web.logbus import bus

router = APIRouter(tags=["system"])

SNAP_DIR = DATA_DIR / "snapchat"
_install_lock = threading.Lock()


def _which(name: str) -> str | None:
    return shutil.which(name)


# ── Snapchat runtime probing ─────────────────────────────────────────────────
# `npm install` is not proof that Snapchat can run. Puppeteer downloads Chrome
# in a postinstall step, and that step can fail or be interrupted after the
# ~190 MB zip lands but before it is unpacked, leaving an empty version
# directory that Puppeteer then rejects with "Could not find Chrome". Since
# node_modules/ exists in that state, a check for it alone reports success
# while every launch dies. So ask Puppeteer itself where Chrome is, and
# confirm the file is really there.
_PUPPETEER_PATH_JS = (
    "import('puppeteer')"
    ".then(p => process.stdout.write(p.default.executablePath()))"
    ".catch(() => process.exit(1))"
)


def _snap_dir_for_probe() -> Path:
    """Where node_modules actually lives (data dir, or a source checkout)."""
    if (SNAP_DIR / "node_modules").is_dir():
        return SNAP_DIR
    src = APP_DIR / "app" / "platforms" / "snapchat"
    return src if (src / "node_modules").is_dir() else SNAP_DIR


# Starting node to ask Puppeteer where Chrome is takes about four and a half
# seconds. health_routes wrapped its own cache around this; /api/snapchat/status
# did not, and the Settings page polls that every 3 seconds, so the whole panel
# stalled in four-second blocks for as long as the page was open. The cache
# belongs on the call itself, where it covers every caller.
_chrome_path_cache = {"at": 0.0, "value": ""}
_CHROME_PATH_TTL = 900.0


def chrome_path(force: bool = False) -> str:
    """The Chrome executable Puppeteer would use, or "" if it is not usable.

    Cached for _CHROME_PATH_TTL: Chrome does not appear or vanish minute to
    minute. Pass force=True right after an install to re-probe immediately.
    """
    now = time.time()
    if not force and now - _chrome_path_cache["at"] <= _CHROME_PATH_TTL:
        return _chrome_path_cache["value"]
    value = _chrome_path_probe()
    _chrome_path_cache.update(at=now, value=value)
    return value


def _chrome_path_probe() -> str:
    node = _which("node")
    work = _snap_dir_for_probe()
    if not node or not (work / "node_modules").is_dir():
        return ""
    try:
        proc = subprocess.run([node, "-e", _PUPPETEER_PATH_JS], cwd=str(work),
                              capture_output=True, text=True, timeout=45,
                              **quiet_kwargs())
    except Exception:
        return ""
    path = (proc.stdout or "").strip()
    return path if path and Path(path).is_file() else ""


def _clear_broken_browsers():
    """Remove half-extracted browser directories so a retry re-downloads.

    Puppeteer skips a version it believes is already installed, so an empty
    win64-<version>/ folder makes every reinstall a no-op.
    """
    roots = [Path.home() / ".cache" / "puppeteer"]
    cache = os.environ.get("PUPPETEER_CACHE_DIR")
    if cache:
        roots.insert(0, Path(cache))
    for root in roots:
        for browser in ("chrome", "chrome-headless-shell"):
            base = root / browser
            if not base.is_dir():
                continue
            for version_dir in base.iterdir():
                if not version_dir.is_dir():
                    continue
                # A good install has an executable somewhere underneath it.
                if any(version_dir.rglob("*.exe")) or any(version_dir.rglob("chrome")):
                    continue
                try:
                    shutil.rmtree(version_dir)
                    bus.append("snapchat-install",
                               f"Removed incomplete browser download: {version_dir.name}")
                except OSError:
                    pass


@router.get("/api/system/doctor")
async def doctor(request: Request):
    """Wrapper: the probes below start node and touch the disk, which must not
    happen on the event loop or the whole panel waits for them."""
    import asyncio
    supervisor = getattr(request.app.state, "supervisor", None)
    return await asyncio.to_thread(_doctor_checks, supervisor)


def _doctor_checks(supervisor):
    """Every dependency, with a way to act on the ones that are missing.

    A red row that only says "not found" leaves you nowhere. Each check carries
    a plain explanation of what it is for, and an action the panel can render:
    a button that installs it, a link to where you get it, or a jump to the
    settings page that fixes it.
    """
    checks = []

    def add(cid, name, ok, detail="", why="", fix="", action=None):
        checks.append({
            "id": cid, "name": name, "ok": bool(ok), "detail": detail,
            "why": why, "fix": "" if ok else fix,
            "action": None if ok else action,
        })

    try:
        import fastapi as _  # noqa
        add("web", "Web server", True, "running",
            "Serves this panel and talks to the running accounts.")
    except Exception:
        add("web", "Web server", False, "fastapi missing",
            "Serves this panel and talks to the running accounts.",
            "The install is broken. Reinstall the app, or run "
            "pip install -r requirements.txt from source.")

    node = _which("node")
    npm = _which("npm")
    add("node", "Node.js", bool(node), node or "not found",
        "Only Snapchat needs it. It drives the browser Snapchat runs in.",
        "Install Node.js, then reopen the app so it is found on PATH. "
        "Discord works fine without it.",
        {"kind": "link", "label": "Get Node.js", "url": "https://nodejs.org/en/download"})
    add("npm", "npm", bool(npm), npm or "not found",
        "Ships with Node.js and installs the Snapchat packages.",
        "npm comes with Node.js, so installing Node fixes this too.",
        {"kind": "link", "label": "Get Node.js", "url": "https://nodejs.org/en/download"})

    snap_ready = ((SNAP_DIR / "node_modules").is_dir()
                  or (APP_DIR / "app" / "platforms" / "snapchat" / "node_modules").is_dir())
    add("snap", "Snapchat packages", snap_ready,
        "installed" if snap_ready else "not installed",
        "Puppeteer and its stealth plugins, about 180 MB with Chrome.",
        "Install them from Settings, under Snapchat. Skip this if you only "
        "use Discord.",
        {"kind": "goto", "label": "Open Snapchat setup", "route": "settings",
         "section": "Snapchat setup"})

    from app.utils import binaries
    ffmpeg = binaries.find("ffmpeg")
    ffprobe = binaries.find("ffprobe")
    add("ffmpeg", "ffmpeg", bool(ffmpeg), ffmpeg or "not found",
        "Encodes voice messages. Everything else works without it.",
        "One click downloads a copy into the app data folder. Nothing is "
        "installed system wide.",
        {"kind": "install", "label": "Install ffmpeg", "target": "ffmpeg"})
    add("ffprobe", "ffprobe", bool(ffprobe), ffprobe or "not found",
        "Reads the length of a voice clip. Without it the length is estimated "
        "from the file header instead.",
        "Comes with ffmpeg, so installing ffmpeg fixes this too.",
        {"kind": "install", "label": "Install ffmpeg", "target": "ffmpeg"})

    port = supervisor.port if supervisor else 8787
    # This request arrived over that port, so it is necessarily in use by us - 
    # the old bind() probe always failed and reported the port as unavailable.
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        sock.close()
        add("port", f"Port {port}", True, "listening",
            "The port this panel is served on.")
    except OSError as e:
        add("port", f"Port {port}", False, str(e),
            "The port this panel is served on.",
            "Another program is likely using it. Pick a different port in "
            "Settings, then restart the app.",
            {"kind": "goto", "label": "Change the port", "route": "settings",
             "section": "Services"})

    try:
        test = DATA_DIR / "config" / ".write_test"
        test.write_text("ok")
        test.unlink()
        add("data", "Data folder writable", True, str(DATA_DIR),
            "Holds your config, keys, database and pictures.")
    except OSError:
        add("data", "Data folder writable", False, str(DATA_DIR),
            "Holds your config, keys, database and pictures.",
            "Nothing can be saved. Give your user write access to that folder, "
            "or move the app out of a protected location like Program Files.",
            {"kind": "open", "label": "Open the folder", "target": "data"})

    built = (APP_DIR / "webui" / "dist" / "index.html").exists()
    add("webui", "Panel files", built, "bundled" if built else "missing",
        "The panel you are looking at right now.",
        "Running from source? Build it with npm run build inside webui.")

    # Where replies come from: a Groq key, or a server on this machine. Either
    # one is a complete answer, so the row reports whichever is in use rather
    # than calling a deliberate local setup a missing key.
    from app.utils import localai
    from app.utils.helpers import load_config as _cfg
    groq = bool(_real_env("GROQ_API_KEY"))
    try:
        local_cfg = _cfg()
    except Exception:
        local_cfg = {}
    if localai.active(local_cfg):
        local = localai.settings(local_cfg)
        up = localai.probe(local["base_url"], timeout=1.5)
        add("brain", "Local AI server", up["ok"],
            f"{local['model']} is ready" if up["ok"] else "not answering",
            "Replies are written on this machine instead of by Groq.",
            f"Start the server at {local['base_url']}, or turn local replies "
            "off to go back to Groq. " + (up["error"] or ""),
            {"kind": "goto", "label": "Open Local AI", "route": "settings",
             "section": "local ai"})
    else:
        add("groq", "Groq API key", groq, "set" if groq else "not set",
            "The AI that writes the replies. Nothing answers without it.",
            "Add at least one key, free from console.groq.com, or run a model "
            "on this machine instead.",
            {"kind": "goto", "label": "Add a key", "route": "settings",
             "section": "Groq keys"})

    token = bool(_real_env("DISCORD_TOKEN"))
    add("token", "Discord token", token, "set" if token else "not set",
        "Signs the bot in to your Discord account.",
        "Paste your account token under Discord, Tokens.",
        {"kind": "goto", "label": "Add a token", "route": "settings",
         "section": "Discord tokens"})

    return {"checks": checks, "data_dir": str(DATA_DIR), "app_dir": str(APP_DIR),
            "frozen": bool(getattr(sys, "frozen", False))}


def _real_env(name: str) -> str:
    """An env value that is actually filled in, not a leftover template line.

    Numbered names count: keys are stored as GROQ_API_KEY_1, _2, _3 and the
    bare name is usually absent, so checking only that reported three working
    keys as "not set".
    """
    try:
        from app.utils.credentials import real_any
        found = real_any(name)
        if found:
            return found
    except Exception:
        pass
    # The panel can be started without the .env having been loaded into the
    # environment, in which case the file itself is the source of truth.
    try:
        from app.web.envfile import read_env
        values = read_env()
        from app.utils.credentials import is_placeholder
        for key in [name] + [f"{name}_{i}" for i in range(1, 21)]:
            value = values.get(key)
            if value and not is_placeholder(value):
                return str(value).strip()
    except Exception:
        pass
    return ""


@router.post("/api/system/open")
async def open_folder(request: Request):
    """Show a folder in the file manager, for the doctor's open action."""
    body = await request.json()
    targets = {"data": DATA_DIR, "app": APP_DIR,
               "pictures": DATA_DIR / "config" / "pictures",
               "logs": DATA_DIR / "logs"}
    path = targets.get(str(body.get("target") or "data"))
    if path is None or not Path(path).exists():
        raise HTTPException(status_code=404, detail="no such folder")
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], **quiet_kwargs())
        else:
            subprocess.Popen(["xdg-open", str(path)], **quiet_kwargs())
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "path": str(path)}


# Links the panel is allowed to open, by name. A named list rather than "open
# whatever URL the page sends": this runs on the host machine, and an endpoint
# that opens any URL handed to it is a launcher for anything that can reach the
# panel. The same reasoning as the folder targets above.
LINKS = {
    "project": "https://github.com/miiazertyy/LLM-Selfbot",
    "lifeisstrange": "https://en.wikipedia.org/wiki/Life_Is_Strange",
}


@router.post("/api/system/link")
async def open_link(request: Request):
    """Open one of the known links in the real browser.

    Only the desktop shell needs this. pywebview has no tab to open a link in,
    so window.open there either does nothing or replaces the panel itself. A
    browser tab opens its own links and never calls this, which also means a
    phone on Tailscale does not make the host machine open a window.
    """
    body = await request.json()
    url = LINKS.get(str(body.get("name") or ""))
    if not url:
        raise HTTPException(status_code=404, detail="no such link")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "url": url}


# ── Reaching the panel from another device ───────────────────────────────────
def _lan_ip() -> str:
    """This machine's address on the local network.

    Opening a UDP socket to a public address makes the OS pick the interface it
    would actually route through; nothing is sent. Beats gethostbyname, which
    tends to answer 127.0.0.1.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return ""


@router.get("/api/system/network")
async def network(request: Request):
    """Where the panel can be reached, and a QR code for the phone."""
    from app.utils.helpers import load_config

    supervisor = getattr(request.app.state, "supervisor", None)
    port = supervisor.port if supervisor else 8787
    try:
        webui = (load_config().get("services", {}) or {}).get("webui", {}) or {}
        bind = str(webui.get("bind") or "127.0.0.1")
        enabled = bool(webui.get("enabled", True))
    except Exception:
        bind, enabled = "127.0.0.1", True

    ip = _lan_ip()
    local_url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{ip}:{port}" if ip else ""
    # Only the LAN address is worth pointing a phone at, and only when the
    # server is actually listening on something other than loopback.
    reachable = bool(lan_url) and bind != "127.0.0.1"

    svg = ""
    target = lan_url if reachable else local_url
    try:
        import segno
        # segno's SVG serialiser writes bytes, so a text buffer raises here.
        buf = io.BytesIO()
        # Dark modules on a transparent ground, drawn over a white plate in the
        # page. An inverted code (light on dark) is what a lot of phone
        # scanners quietly refuse to read.
        segno.make(target, error="m").save(
            buf, kind="svg", scale=1, border=2, dark="#101018", light=None,
            svgclass=None, lineclass=None, omitsize=True, xmldecl=False, svgns=True)
        svg = buf.getvalue().decode("utf-8")
    except Exception as exc:
        bus.append("system", f"QR code unavailable: {exc}", level="warn")
        svg = ""

    return {
        "port": port,
        "bind": bind,
        "enabled": enabled,
        "ip": ip,
        "local_url": local_url,
        "lan_url": lan_url,
        "reachable": reachable,
        "qr": svg,
        "qr_target": target,
    }


@router.post("/api/system/restart")
async def restart_app(request: Request):
    """Close the whole app and start it again.

    The same thing as quitting and reopening it by hand, which is what several
    changes need: a new port, a different data folder, or a setting the runners
    only read at import. Doing it from here means not hunting for the window.

    The order matters, and each step is here because of what goes wrong without
    it:

      * the workers are stopped first. This process ends with os._exit, which
        runs no cleanup at all, so anything still running would be orphaned and
        the replacement would find its Discord accounts already signed in.
      * the replacement is launched while this process still holds the single
        instance lock, and told to wait for it rather than give up. That lock is
        the handover signal: it is released only when this process actually
        dies, which is the same moment the port it is serving on is freed.
        Releasing it any earlier lets the replacement race ahead, fail to bind
        a port that is still in use, and exit, leaving nothing running at all.
        That is not theoretical, it is what the first version of this did.
      * the port is handed over deliberately. The panel reloads itself by
        polling the address it is already on, so a replacement that picked a
        different port would leave the window pointing at nothing.
    """
    import os
    import subprocess
    import sys
    import threading

    from app.utils.procs import quiet_kwargs

    if getattr(sys, "frozen", False):
        argv = [sys.executable]
    else:
        argv = [sys.executable, str(APP_DIR / "main.py")]

    supervisor = getattr(request.app.state, "supervisor", None)
    port = getattr(supervisor, "port", None) or request.url.port

    def _go():
        time.sleep(0.6)          # let this response reach the browser first

        if supervisor is not None:
            try:
                supervisor.stop_all()
            except Exception as exc:
                bus.append("system", f"Could not stop the accounts cleanly: {exc}", "warn")

        env = {k: v for k, v in os.environ.items() if k != "LLMSELFBOT_CHILD"}
        env["LLMSELFBOT_RESTART"] = "1"
        if port:
            env["SELFBOT_PORT"] = str(port)
        try:
            subprocess.Popen(argv, cwd=str(APP_DIR), env=env,
                             close_fds=True, **quiet_kwargs())
        except Exception as exc:
            bus.append("system", f"Could not relaunch: {exc}", "error")
            return
        # Going away is the handover: it drops the lock and the port together.
        os._exit(0)

    bus.append("system", "Restarting the app.")
    threading.Thread(target=_go, daemon=True, name="restart").start()
    return {"ok": True, "restarting": True}


@router.get("/api/system/backup")
async def backup(request: Request):
    backups = DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = backups / f"backup-{stamp}.zip"
    cfg = DATA_DIR / "config"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in ("config.yaml", "instructions.txt", ".env", "bot_data.db"):
            src = cfg / rel
            if src.exists():
                zf.write(src, f"config/{rel}")
        pics = cfg / "pictures"
        if pics.is_dir():
            for f in pics.iterdir():
                if f.is_file():
                    zf.write(f, f"config/pictures/{f.name}")
    return FileResponse(path, filename=path.name)


@router.post("/api/system/restore")
async def restore(request: Request, file: UploadFile = File(...)):
    data = await file.read()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                base = name.split("/", 1)[0]
                if base != "config":
                    raise ValueError("invalid backup archive")
            zf.extractall(DATA_DIR)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="not a zip file")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    bus.append("system", "Backup restored - restart the app to apply.")
    return {"ok": True}


# ── Taking everything with you ───────────────────────────────────────────────
# The old backup listed four files by name, which quietly left out the account
# identities, the cached model list and anything added later. This walks the
# whole data folder instead and names what it deliberately leaves behind, so a
# new file is included by default rather than forgotten.
_EXPORT_SKIP_DIRS = {
    "logs",           # noisy, and worthless on another machine
    "backups",        # backups of backups
    "temp",
    "ipc",            # live command files, meaningless once the app is closed
    "node_modules",   # hundreds of megabytes, reinstallable in a click
    "__pycache__",
}
_EXPORT_SKIP_SUFFIXES = (".pyc", ".log", ".lock")


def _export_members():
    """(absolute path, name inside the archive) for everything worth keeping."""
    for path in sorted(DATA_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(DATA_DIR)
        if any(part in _EXPORT_SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() in _EXPORT_SKIP_SUFFIXES:
            continue
        # A downloaded browser is ~500 MB and is not configuration.
        if rel.parts and rel.parts[0] == "snapchat" and len(rel.parts) > 1:
            if rel.parts[1] in ("chrome", "chrome-headless-shell"):
                continue
        yield path, str(rel).replace("\\", "/")


def _write_export(target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        # A marker, so an import can tell one of ours from any other zip and
        # say something useful instead of extracting nonsense.
        zf.writestr("selfbot-export.json", json.dumps({
            "version": __version__,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "portable": is_portable(),
        }, indent=2))
        for path, name in _export_members():
            zf.write(path, name)
            count += 1
    return {"ok": True, "path": str(target), "files": count,
            "size": target.stat().st_size}


@router.post("/api/system/export")
async def export_everything(request: Request):
    """Write a full export, either to a folder the user picked or to backups/.

    Includes the .env: the point is to be able to move the whole setup, and a
    copy without the tokens would not restore to a working app. That also makes
    the file worth keeping somewhere private.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    folder = (body or {}).get("folder") or ""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"selfbot-export-{stamp}.zip"

    if folder:
        base = Path(folder)
        if not base.is_dir():
            raise HTTPException(status_code=400, detail="that folder does not exist")
        target = base / name
    else:
        target = DATA_DIR / "backups" / name

    try:
        result = _write_export(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not write the export: {exc}")
    bus.append("system", f"Exported {result['files']} files to {result['path']}")
    return result


@router.post("/api/system/import")
async def import_everything(request: Request):
    """Restore an export written by this app, from a path the user picked."""
    body = await request.json()
    source = (body or {}).get("path") or ""
    if not source:
        raise HTTPException(status_code=400, detail="no file chosen")
    path = Path(source)
    if not path.is_file():
        raise HTTPException(status_code=400, detail="that file does not exist")

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            # Never trust a path out of an archive: an entry called
            # ../../Windows/System32 must not be written where it asks.
            safe = []
            for name in names:
                if name.endswith("/"):
                    continue
                clean = Path(name.replace("\\", "/"))
                if clean.is_absolute() or ".." in clean.parts:
                    raise HTTPException(status_code=400,
                                        detail=f"unsafe path in the archive: {name}")
                safe.append((name, clean))
            if not any(n == "selfbot-export.json" for n, _ in safe)                     and not any(c.parts and c.parts[0] == "config" for _, c in safe):
                raise HTTPException(status_code=400,
                                    detail="that does not look like a LLMSelfbot export")

            restored = 0
            for name, clean in safe:
                if name == "selfbot-export.json":
                    continue
                dest = DATA_DIR / clean
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
                restored += 1
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="that is not a zip file")

    from app.utils.helpers import invalidate_config_cache
    try:
        invalidate_config_cache()
    except Exception:
        pass
    bus.append("system", f"Imported {restored} files. Restart the app to apply.", "warn")
    return {"ok": True, "files": restored,
            "note": "Restart the app for everything to take effect."}


@router.get("/api/system/storage")
async def storage(request: Request):
    """Where the data lives, and whether this is a portable install."""
    total = 0
    files = 0
    for path, _ in _export_members():
        try:
            total += path.stat().st_size
            files += 1
        except OSError:
            pass
    return {
        "data_dir": str(DATA_DIR),
        "portable": is_portable(),
        "portable_hint": str((Path(sys.executable).resolve().parent
                              if getattr(sys, "frozen", False) else APP_DIR) / "portable"),
        "files": files,
        "size": total,
    }


def _ignored_update() -> str:
    """The release the user chose not to be told about again."""
    try:
        path = DATA_DIR / "config" / "update_ignored.json"
        if path.exists():
            return str(json.loads(path.read_text(encoding="utf-8")).get("version", ""))
    except Exception:
        pass
    return ""


@router.post("/api/system/update/ignore")
async def ignore_update(request: Request):
    """Stop mentioning a release. A newer one than this still gets through."""
    body = await request.json()
    version = str((body or {}).get("version") or "").strip()
    if not version:
        raise HTTPException(status_code=400, detail="which version?")
    path = DATA_DIR / "config" / "update_ignored.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": version}), encoding="utf-8")
    bus.append("system", f"Ignoring update {version}.")
    return {"ok": True, "ignored": version}


@router.get("/api/system/update/check")
async def update_check(request: Request):
    import asyncio
    # Synchronous httpx on the event loop stalled every other request for as
    # long as GitHub took to answer. The client caches the result already.
    return await asyncio.to_thread(_update_check_blocking)


def _update_check_blocking():
    try:
        import httpx
        resp = httpx.get(
            "https://api.github.com/repos/miiazertyy/LLM-Selfbot/releases/latest", timeout=10
        )
        if resp.status_code != 200:
            return {"ok": False, "reason": f"GitHub API returned {resp.status_code}"}
        data = resp.json()
        latest = data.get("tag_name", "")
        return {
            "ok": True,
            "current": __version__,
            "latest": latest or "unknown",
            # The comparison is the whole point: "latest is v1.6.0" says nothing
            # unless you already know what you are running.
            "update_available": is_newer(latest, __version__),
            # Dismissed releases stay dismissed until a newer one appears.
            "ignored": _ignored_update() == latest,
            "url": data.get("html_url", ""),
            "notes": (data.get("body") or "")[:4000],
            "published": data.get("published_at", ""),
        }
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@router.post("/api/system/update/run")
async def update_run(request: Request):
    # Source installs use the git-based updater scripts; frozen installs get
    # the zip staged for the standalone updater.
    if getattr(sys, "frozen", False):
        # Re-invoke ourselves in the updater role; it stages the release, swaps
        # the app dir and relaunches. DATA_DIR is untouched.
        subprocess.Popen([sys.executable, "--role", "updater"], cwd=str(Path(sys.executable).parent))
        bus.append("system", "Updater launched - the app will restart when it finishes.")
        return {"ok": True, "queued": True}
    repo = APP_DIR
    script = repo / ("scripts/updater.bat" if os.name == "nt" else "scripts/updater.sh")
    if not script.exists():
        raise HTTPException(status_code=404, detail="updater script not found")
    if os.name == "nt":
        subprocess.Popen(f'cmd /c start "Updating" /d "{repo}" "{script}" release', shell=True, cwd=repo)
    else:
        subprocess.Popen(["bash", str(script), "release"], start_new_session=True, cwd=repo)
    bus.append("system", "Updater launched - the app will restart after updating.")
    return {"ok": True, "queued": True}


# ── Snapchat on-demand installer ─────────────────────────────────────────────
@router.get("/api/snapchat/status")
async def snap_status(request: Request):
    import asyncio
    # Even cached, the first probe shells out to node for several seconds, and
    # the .is_dir() checks touch disk. None of that belongs on the event loop.
    modules, chrome = await asyncio.to_thread(_snap_probe)
    return {
        "node": _which("node"),
        "npm": _which("npm"),
        "modules_installed": modules,
        "browser": chrome,
        # Only true when Snapchat can actually launch. Reporting node_modules
        # alone said "installed" while every run failed on a missing Chrome.
        "deps_installed": bool(modules and chrome),
        "installing": _install_lock.locked(),
        "dir": str(SNAP_DIR),
        # What each runner is actually doing. "Running" used to mean only that
        # the process existed, so an account sitting on a verification screen
        # looked identical to one answering messages.
        "runners": await asyncio.to_thread(_snap_runner_states),
    }


# A runner that has not written for this long is not telling us anything
# current - it may have been killed without clearing the file.
_SNAP_STATE_STALE = 300.0


def _snap_runner_states() -> list[dict]:
    """Each Snapchat runner's self-reported state, newest write first."""
    import json
    from app.utils.paths import DATA_DIR
    out = []
    ipc_dir = DATA_DIR / "ipc"
    try:
        paths = sorted(ipc_dir.glob("snap_state*.json"))
    except Exception:
        return out
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue        # half-written, or not ours
        at = float(data.get("at") or 0)
        out.append({
            "account": data.get("account"),
            "state": str(data.get("state") or ""),
            "detail": str(data.get("detail") or ""),
            "at": at,
            # The panel should not present a state from an hour ago as current.
            "stale": (time.time() - at) > _SNAP_STATE_STALE if at else True,
        })
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def _snap_probe() -> tuple[bool, str]:
    """(node_modules present, Chrome path). Blocking; call it on a thread."""
    modules = ((SNAP_DIR / "node_modules").is_dir()
               or (APP_DIR / "app" / "platforms" / "snapchat" / "node_modules").is_dir())
    return modules, (chrome_path() if modules else "")


@router.post("/api/snapchat/install")
async def snap_install(request: Request):
    npm = _which("npm")
    if not npm:
        raise HTTPException(status_code=400, detail="npm not found - install Node.js first")
    if not _install_lock.acquire(blocking=False):
        return {"ok": False, "reason": "install already in progress"}
    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    def _stream(argv, cwd, label) -> int:
        bus.append("snapchat-install", f"$ {label}")
        proc = subprocess.Popen(
            argv, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            **quiet_kwargs(),
        )
        for line in proc.stdout:
            bus.append("snapchat-install", line)
        return proc.wait()

    def _run():
        try:
            src = APP_DIR / "app" / "platforms" / "snapchat"
            if not (SNAP_DIR / "package.json").exists() and src.exists():
                shutil.copyfile(src / "package.json", SNAP_DIR / "package.json")

            # A previous run may have left an unpacked-but-empty browser dir.
            # Puppeteer would treat that version as present and skip the
            # download, so the install could never repair itself.
            _clear_broken_browsers()

            code = _stream([npm, "install", "--no-fund", "--no-audit"], SNAP_DIR,
                           "npm install")
            if code != 0:
                bus.append("snapchat-install", f"npm install failed with code {code}", "error")
                return

            # npm install alone is not enough: Puppeteer's browser download is a
            # postinstall step that can fail quietly. Ask for the browser
            # explicitly, then verify rather than trust the exit code.
            if not chrome_path(force=True):
                bus.append("snapchat-install",
                           "Chrome not found after npm install, downloading it explicitly "
                           "(~180 MB).")
                argv = ([_which("npx"), "--yes", "puppeteer", "browsers", "install", "chrome"]
                        if _which("npx")
                        else [npm, "exec", "--yes", "--", "puppeteer", "browsers", "install", "chrome"])
                code = _stream(argv, SNAP_DIR, "puppeteer browsers install chrome")
                if code != 0:
                    bus.append("snapchat-install",
                               f"Browser download failed with code {code}", "error")

            found = chrome_path(force=True)
            if found:
                bus.append("snapchat-install",
                           f"Install complete, Chrome at {found}. "
                           "Start the Snapchat account to use it.")
            else:
                bus.append("snapchat-install",
                           "Install finished but Chrome still cannot be found. Check the log "
                           "above, then retry - a partial download is cleared automatically.",
                           "error")
        except Exception as e:
            bus.append("snapchat-install", f"Install error: {e}", "error")
        finally:
            _install_lock.release()

    threading.Thread(target=_run, daemon=True, name="snap-install").start()
    return {"ok": True, "queued": True}


# ── ffmpeg on-demand installer ───────────────────────────────────────────────
_ffmpeg_lock = threading.Lock()


@router.get("/api/system/ffmpeg")
async def ffmpeg_status(request: Request):
    from app.utils import binaries
    return {**binaries.ffmpeg_status(), "installing": _ffmpeg_lock.locked()}


@router.post("/api/system/ffmpeg/install")
async def ffmpeg_install(request: Request):
    from app.utils import binaries
    if not _ffmpeg_lock.acquire(blocking=False):
        return {"ok": False, "reason": "install already in progress"}

    def _run():
        try:
            result = binaries.install_ffmpeg(
                progress=lambda m: bus.append("ffmpeg-install", m)
            )
            if result.get("ok"):
                bus.append("ffmpeg-install", "ffmpeg ready - voice messages enabled.")
            else:
                bus.append("ffmpeg-install", f"Install failed: {result.get('reason')}", "error")
        finally:
            _ffmpeg_lock.release()

    threading.Thread(target=_run, daemon=True, name="ffmpeg-install").start()
    return {"ok": True, "queued": True}


@router.get("/api/system/info")
async def info(request: Request):
    import platform
    return {
        "version": __version__,
        "python": platform.python_version(),
        "os": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "data_dir": str(DATA_DIR),
    }
