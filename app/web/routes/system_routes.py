import asyncio
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


# ── Snapchat runtime probing ── `npm install` is not proof that Snapchat can run. Puppeteer downloads Chrome in a postinstall step, and that step can fail or be interrupted after the ~190 MB zip lands but before it is unpacked, leaving an empty version directory that Puppeteer then rejects with "Could not find Chrome". Since node_modules/ exists in that state, a check for it alone reports success while every launch dies. So ask Puppeteer itself where Chrome is, and confirm the file is really there.
_PUPPETEER_PATH_JS = (
    "import('puppeteer')"
    ".then(p => process.stdout.write(p.default.executablePath()))"
    ".catch(() => process.exit(1))"
)


# ── An already-installed browser beats a downloaded one ──────────────────────
# Puppeteer's postinstall pulls Chrome for Testing: about 180 MB down and 400 MB
# on disk, for a browser the machine very probably already has. A real consumer
# Chrome or Edge install is also the better thing to be driving - Chrome for
# Testing is a distinct build, and the whole point of the Snapchat runner's
# stealth setup is to look like the browser a person actually uses.
#
# Puppeteer reads PUPPETEER_EXECUTABLE_PATH natively, so finding one here is the
# entire integration; the bridge passes it down to Node. Chromium proper is
# accepted last: it is the same download size as Chrome, so it saves nothing,
# and it ships without the proprietary codecs Snapchat's web app wants for video
# and voice. It is only worth using if it is already sitting there.
_BROWSER_CANDIDATES = {
    "win32": [
        ("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("Chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("Chrome", os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")),
        ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("Edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ],
    "darwin": [
        ("Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ],
}
_BROWSER_ON_PATH = [
    ("Chrome", "google-chrome"), ("Chrome", "google-chrome-stable"),
    ("Edge", "microsoft-edge"), ("Edge", "microsoft-edge-stable"),
    ("Chromium", "chromium"), ("Chromium", "chromium-browser"),
]


def installed_browser() -> tuple[str, str]:
    """(name, path) of a browser already on this machine, or ("", "")."""
    override = os.environ.get("PUPPETEER_EXECUTABLE_PATH", "").strip()
    if override and Path(override).is_file():
        return "Custom", override
    for name, candidate in _BROWSER_CANDIDATES.get(sys.platform, []):
        if candidate and Path(candidate).is_file():
            return name, candidate
    for name, binary in _BROWSER_ON_PATH:
        found = _which(binary)
        if found:
            return name, found
    return "", ""


def _snap_dir_for_probe() -> Path:
    """Where node_modules actually lives (data dir, or a source checkout)."""
    if (SNAP_DIR / "node_modules").is_dir():
        return SNAP_DIR
    src = APP_DIR / "app" / "platforms" / "snapchat"
    return src if (src / "node_modules").is_dir() else SNAP_DIR


# Starting node to ask Puppeteer where Chrome is takes about four and a half seconds. health_routes wrapped its own cache around this; /api/snapchat/status did not, and the Settings page polls that every 3 seconds, so the whole panel stalled in four-second blocks for as long as the page was open. The cache belongs on the call itself, where it covers every caller.
_chrome_path_cache = {"at": 0.0, "value": ""}
_CHROME_PATH_TTL = 900.0


def chrome_path(force: bool = False) -> str:
    """The Chrome executable Puppeteer would use, or "" if it is not usable. Cached for _CHROME_PATH_TTL: Chrome does not appear or vanish minute to minute. Pass force=True right after an install to re-probe immediately."""
    now = time.time()
    if not force and now - _chrome_path_cache["at"] <= _CHROME_PATH_TTL:
        return _chrome_path_cache["value"]
    value = _chrome_path_probe()
    _chrome_path_cache.update(at=now, value=value)
    return value


def _chrome_path_probe() -> str:
    # An installed browser needs no node, no node_modules and no download, so it
    # is checked before the (four-and-a-half second) Puppeteer probe.
    _, found = installed_browser()
    if found:
        return found
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


def _browser_cache_roots() -> list:
    """Where Puppeteer keeps its downloaded browsers."""
    roots = [Path.home() / ".cache" / "puppeteer"]
    cache = os.environ.get("PUPPETEER_CACHE_DIR")
    if cache:
        roots.insert(0, Path(cache))
    return [r for r in roots if r.is_dir()]


def _clear_broken_browsers():
    """Remove half-extracted browser directories so a retry re-downloads. Puppeteer skips a version it believes is already installed, so an empty win64-<version>/ folder makes every reinstall a no-op."""
    for root in _browser_cache_roots():
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


def _drop_browser_archives() -> int:
    """Delete the .zip/.tar files Puppeteer leaves behind after unpacking. Returns the megabytes freed. The browser directory next to them is the one that gets used; the archive is only ever read once."""
    freed = 0
    for root in _browser_cache_roots():
        for archive in root.rglob("*"):
            if archive.suffix.lower() not in (".zip", ".gz", ".bz2", ".xz"):
                continue
            try:
                size = archive.stat().st_size
                archive.unlink()
                freed += size
            except OSError:
                pass
    return freed // (1024 * 1024)


@router.get("/api/system/doctor")
async def doctor(request: Request):
    """Wrapper: the probes below start node and touch the disk, which must not happen on the event loop or the whole panel waits for them."""
    import asyncio
    supervisor = getattr(request.app.state, "supervisor", None)
    return await asyncio.to_thread(_doctor_checks, supervisor)


def _doctor_checks(supervisor):
    """Every dependency, with a way to act on the ones that are missing. A red row that only says "not found" leaves you nowhere; each check carries a plain explanation of what it is for, and an action the panel can render: a button that installs it, a link to where you get it, or a jump to the settings page that fixes it."""
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

    # A phone has none of the tools below and never will: they are not
    # problems to fix there, and "Not available here" says what they are for.
    from app.utils import device
    here = device.detect()
    if device.is_phone(here):
        return _doctor_rest(checks, add, supervisor)

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
        "Puppeteer and its stealth plugins. Uses the browser you have, or "
        "downloads one.",
        "Install them from Settings, under Snapchat. Skip this if you only "
        "use Discord.",
        {"kind": "goto", "label": "Open Snapchat setup", "route": "settings",
         "section": "Snapchat setup"})

    from app.utils import binaries
    ffmpeg = binaries.find("ffmpeg")
    ffprobe = binaries.find("ffprobe")
    # The one-click download is a Windows build; elsewhere the system's
    # package manager has it (and on Linux on ARM, only it does).
    family = device.DEVICES.get(here, {}).get("family", "")
    if family == "windows":
        ffmpeg_fix = ("One click downloads a copy into the app data folder. Nothing is "
                      "installed system wide.")
        ffmpeg_act = {"kind": "install", "label": "Install ffmpeg", "target": "ffmpeg"}
    else:
        ffmpeg_fix = ("Install it with " + ("brew install ffmpeg" if family == "macos" else "sudo apt install ffmpeg")
                      + ", then reopen the app.")
        ffmpeg_act = None
    add("ffmpeg", "ffmpeg", bool(ffmpeg), ffmpeg or "not found",
        "Encodes voice messages. Everything else works without it.",
        ffmpeg_fix, ffmpeg_act)
    add("ffprobe", "ffprobe", bool(ffprobe), ffprobe or "not found",
        "Reads the length of a voice clip. Without it the length is estimated "
        "from the file header instead.",
        "Comes with ffmpeg, so installing ffmpeg fixes this too.", ffmpeg_act)

    return _doctor_rest(checks, add, supervisor)


def _doctor_rest(checks, add, supervisor):
    """The checks that apply on every device: the port, and what follows it."""

    port = supervisor.port if supervisor else 8787
    # This request arrived over that port, so it is necessarily in use by us; the old bind() probe always failed and reported the port as unavailable.
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

    # Where replies come from: any provider in the reply chain, or a server on this machine. Each is a complete answer, so the rows report what is in use rather than calling a deliberate setup without Groq a missing key.
    from app.utils import localai
    from app.utils.helpers import load_config as _cfg
    try:
        local_cfg = _cfg()
    except Exception:
        local_cfg = {}
    from app.utils import providers
    try:
        plan = providers.plan(local_cfg)
    except Exception:
        plan = {"replies": [], **{j: {"provider": "groq"} for j in providers.JOBS}}
    uses_local = any(e["provider"] == "local" for e in plan["replies"]) or \
        any(plan[j]["provider"] == "local" for j in providers.JOBS)
    if uses_local:
        local = localai.settings(local_cfg)
        up = localai.probe(local["base_url"], timeout=1.5, api_key=local["api_key"])
        sid = localai.server_for(local["base_url"])
        name = localai.server_name(sid) or "Local AI server"
        startable = localai.can_start(sid)
        starting = localai.starting()
        word = localai.start_word(sid)
        goto = {"kind": "goto", "label": "Open This computer", "route": "settings", "section": "local ai"}
        add("brain", name, up["ok"] or starting,
            "running" if up["ok"] else "wants a key" if up["locked"] else "starting" if starting else "not running",
            "The model server on this computer. Some jobs are set to run on it.",
            "It is running, but turns requests away without its key. Put it in under This computer."
            if up["locked"] else
            (f"{word} it here, or leave it: with Start it with the app on, {name} is "
             f"{'opened' if word == 'Open' else 'started'} whenever the app opens.") if startable else
            f"Start it at {local['base_url']}, or move those jobs to another model under Models.",
            goto if up["locked"] else
            {"kind": "start_local", "label": f"{word} {name}"} if startable else goto)
    usable = [e for e in plan["replies"] if providers.usable(e["provider"], local_cfg)]
    if not usable:
        add("groq", "AI for replies", False, "none set up",
            "The AI that writes the replies. Nothing answers without one.",
            "Connect a provider under Models, Providers (Groq is free), or run a model on "
            "this machine instead.",
            {"kind": "goto", "label": "Connect one", "route": "settings", "section": "providers"})
    elif not uses_local or any(e["provider"] != "local" for e in usable):
        add("groq", "AI for replies", True,
            ", ".join(sorted({providers.BY_ID[e["provider"]]["name"] for e in usable})),
            "The AI that writes the replies.", "", None)

    token = bool(_real_env("DISCORD_TOKEN"))
    add("token", "Discord token", token, "set" if token else "not set",
        "Signs the bot in to your Discord account.",
        "Add your account on the Accounts page, by pasting its token or by logging in.",
        {"kind": "goto", "label": "Add an account", "route": "accounts"})

    return {"checks": checks, "data_dir": str(DATA_DIR), "app_dir": str(APP_DIR),
            "frozen": bool(getattr(sys, "frozen", False))}


def _real_env(name: str) -> str:
    """An env value that is actually filled in, not a leftover template line. Numbered names count: keys are stored as GROQ_API_KEY_1, _2, _3 and the bare name is usually absent, so checking only that reported three working keys as "not set"."""
    try:
        from app.utils.credentials import real_any
        found = real_any(name)
        if found:
            return found
    except Exception:
        pass
    # The panel can be started without the .env having been loaded into the environment, in which case the file itself is the source of truth.
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
    # A persona's pictures, by its id: a folder of its own, made if it is not there yet.
    pid = str(body.get("persona") or "")
    if body.get("target") == "pictures" and pid:
        from app.utils import personas
        if not personas.exists(pid):
            raise HTTPException(status_code=404, detail="There is no such persona.")
        path = personas.pictures_dir(pid)
        path.mkdir(parents=True, exist_ok=True)
    if path is None or not Path(path).exists():
        raise HTTPException(status_code=404, detail="no such folder")
    from app.utils import compat
    problem = compat.check("folders")
    if problem:
        raise HTTPException(status_code=409, detail=problem["why"])
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


# Links the panel is allowed to open, by name. A named list rather than "open whatever URL the page sends": this runs on the host machine, and an endpoint that opens any URL handed to it is a launcher for anything that can reach the panel. The same reasoning as the folder targets above.
LINKS = {
    "project": "https://github.com/miiazertyy/LLM-Selfbot",
    "lifeisstrange": "https://en.wikipedia.org/wiki/Life_Is_Strange",
}


@router.post("/api/system/link")
async def open_link(request: Request):
    """Open one of the known links in the real browser. Only the desktop shell needs this: pywebview has no tab to open a link in, so window.open there either does nothing or replaces the panel itself. A browser tab opens its own links and never calls this, which also means a phone on Tailscale does not make the host machine open a window."""
    body = await request.json()
    url = LINKS.get(str(body.get("name") or ""))
    if not url:
        raise HTTPException(status_code=404, detail="no such link")
    from app.utils import device
    if not device.open_url(url):
        raise HTTPException(status_code=500, detail="could not open the browser")
    return {"ok": True, "url": url}


@router.post("/api/system/open-url")
async def open_url(request: Request):
    """Open a web link outside the app, for the phone apps only. There the panel
    is the app's own web view, and following a link inside it would leave the
    panel with no way back. Only the phone's own web view may ask (the request
    has to come from this device), and only for a web address: everywhere else
    a link opens in a tab of its own and this does not exist."""
    from app.utils import device
    if not device.single_process():
        raise HTTPException(status_code=404, detail="not here")
    host = getattr(request.client, "host", "") or ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="only from this device")
    body = await request.json()
    url = str((body or {}).get("url") or "").strip()
    if not url.startswith(("https://", "http://")) or len(url) > 2000:
        raise HTTPException(status_code=400, detail="not a web link")
    return {"ok": device.open_url(url), "url": url}


@router.get("/api/system/device")
async def device_info(request: Request):
    """This device, and what does not work on it (app/utils/compat.py)."""
    import asyncio
    from app.utils import compat
    # The probes look on disk and on PATH; not on the event loop.
    return await asyncio.to_thread(compat.report)


# ── Reaching the panel from another device ───────────────────────────────────
def _lan_ip() -> str:
    """This machine's address on the local network. Opening a UDP socket to a public address makes the OS pick the interface it would actually route through; nothing is sent. Beats gethostbyname, which tends to answer 127.0.0.1."""
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
def network(request: Request):
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
    # Only the LAN address is worth pointing a phone at, and only when the server is actually listening on something other than loopback.
    reachable = bool(lan_url) and bind != "127.0.0.1"

    svg = ""
    target = lan_url if reachable else local_url
    try:
        import segno
        # segno's SVG serialiser writes bytes, so a text buffer raises here.
        buf = io.BytesIO()
        # Dark modules on a transparent ground, drawn over a white plate in the page. An inverted code (light on dark) is what a lot of phone scanners quietly refuse to read.
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
    """Close the whole app and start it again, like quitting and reopening it by hand, which several changes need: a new port, a different data folder, or a setting the runners only read at import; doing it from here means not hunting for the window. The order matters, and each step is here because of what goes wrong without it: the workers are stopped first, since this process ends with os._exit, which runs no cleanup at all, so anything still running would be orphaned and the replacement would find its Discord accounts already signed in; the replacement is launched while this process still holds the single instance lock, and told to wait for it rather than give up, because that lock is the handover signal, released only when this process actually dies, which is the same moment the port it is serving on is freed (releasing it any earlier lets the replacement race ahead, fail to bind a port that is still in use, and exit, leaving nothing running at all, which the first version actually did); and the port is handed over deliberately, since the panel reloads itself by polling the address it is already on, so a replacement that picked a different port would leave the window pointing at nothing."""
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

    # A phone app is one process, and ending it would close the app rather
    # than restart it: there the accounts are what gets restarted, with the
    # settings read afresh. A new port or data folder waits for the next open.
    from app.utils import device
    if device.single_process():
        def _again():
            time.sleep(0.6)
            if supervisor is not None:
                try:
                    supervisor.stop_all()
                    supervisor.start_all()
                except Exception as exc:
                    bus.append("system", f"Could not restart the accounts: {exc}", "error")
        bus.append("system", "Restarting the accounts.")
        threading.Thread(target=_again, daemon=True, name="restart").start()
        return {"ok": True, "restarting": True, "accounts_only": True}

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
def backup(request: Request):
    """The quick backup: config, keys, memory and pictures, as a download. Plain def, it zips files."""
    backups = DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = backups / f"backup-{stamp}.zip"
    cfg = DATA_DIR / "config"
    members = [(cfg / rel, f"config/{rel}") for rel in ("config.yaml", "instructions.txt", ".env", "bot_data.db")]
    pics = cfg / "pictures"
    if pics.is_dir():
        members += [(f, f"config/pictures/{f.name}") for f in pics.iterdir() if f.is_file()]
    # The originals the looks were made from, so a look can still be taken off after a restore.
    originals = cfg / "pictures_originals"
    if originals.is_dir():
        members += [(f, f"config/pictures_originals/{f.name}") for f in originals.iterdir() if f.is_file()]
    # Every persona: which account is which, and each one's text, settings, face and pictures (app/utils/personas.py).
    members.append((cfg / "personas.json", "config/personas.json"))
    folder = cfg / "personas"
    if folder.is_dir():
        for f in folder.rglob("*"):
            rel = f.relative_to(folder)
            if f.is_file() and rel.parts and not rel.parts[0].startswith(".") and not f.name.endswith((".part", ".tmp")):
                members.append((f, "config/personas/" + rel.as_posix()))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        _zip_members(zf, [(src, name) for src, name in members if src.exists()])
    return FileResponse(path, filename=path.name)


def _stage_restore(zf: zipfile.ZipFile) -> int:
    """Check an archive and unpack it into the pending-restore folder. Returns the file count.

    Applied on the next start (paths.apply_pending_restore), not here: the
    running accounts have the database and settings open, and on Windows
    overwriting a file another process holds fails with "access denied".
    """
    from app.utils.paths import PENDING_RESTORE
    safe = []
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        clean = Path(name.replace("\\", "/"))
        # Never trust a path out of an archive: an entry called ../../Windows/System32 must not be written where it asks.
        if clean.is_absolute() or ".." in clean.parts or (clean.parts and ":" in clean.parts[0]):
            raise HTTPException(status_code=400, detail=f"unsafe path in the archive: {name}")
        safe.append((name, clean))
    if not any(n == "selfbot-export.json" for n, _ in safe) \
            and not any(c.parts and c.parts[0] == "config" for _, c in safe):
        raise HTTPException(status_code=400, detail="that does not look like a LLMSelfbot backup")

    pending = DATA_DIR / PENDING_RESTORE
    shutil.rmtree(pending, ignore_errors=True)
    count = 0
    for name, clean in safe:
        if name == "selfbot-export.json" or (clean.parts and clean.parts[0] in _EXPORT_SKIP_DIRS):
            continue
        dest = pending / clean
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(name))
        count += 1
    return count


@router.post("/api/system/restore")
async def restore(request: Request, file: UploadFile = File(...)):
    data = await file.read()

    def work():
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return _stage_restore(zf)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="not a zip file")

    count = await asyncio.to_thread(work)
    bus.append("system", f"Backup ready: {count} files. Restart the app to finish restoring.", "warn")
    return {"ok": True, "files": count, "restart": True}


# ── Taking everything with you ── the old backup listed four files by name, which quietly left out the account identities, the cached model list and anything added later. This walks the whole data folder instead and names what it deliberately leaves behind, so a new file is included by default rather than forgotten.
_EXPORT_SKIP_DIRS = {
    "webview",        # the app window's own browser cache and cookies: locked while it is open, and not settings
    "restore-pending",
    "logs",           # noisy, and worthless on another machine
    "backups",        # backups of backups
    "temp",
    "ipc",            # live command files, meaningless once the app is closed
    "node_modules",   # hundreds of megabytes, reinstallable in a click
    "__pycache__",
}
# A database's -wal and -shm are its live scratch files, written into the snapshot of it (see _zip_members) and meaningless on their own.
_EXPORT_SKIP_SUFFIXES = (".pyc", ".log", ".lock", ".db-wal", ".db-shm", ".db-journal")


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


def _zip_members(zf: zipfile.ZipFile, members) -> list:
    """Add files to an archive, snapshotting databases and skipping what is locked. Returns what was skipped.

    One file another program had open (the app window's cache, Chrome's
    profile under Snapchat) used to abort the whole export with "access
    denied". A database is copied through SQLite's own backup, so the copy is
    consistent even while an account is writing to it, and includes what is
    still sitting in its write-ahead log.
    """
    import sqlite3
    import tempfile
    skipped = []
    for path, name in members:
        try:
            if path.suffix == ".db":
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        snap = Path(tmp) / path.name
                        src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
                        try:
                            dst = sqlite3.connect(snap)
                            try:
                                src.backup(dst)
                            finally:
                                dst.close()
                        finally:
                            src.close()
                        zf.write(snap, name)
                    continue
                except sqlite3.Error:
                    pass          # not a database SQLite can read (damaged, or not one at all): copy it as it is
            zf.write(path, name)
        except OSError as e:
            skipped.append(f"{name} ({type(e).__name__})")
    return skipped


def _write_export(target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    members = list(_export_members())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        # A marker, so an import can tell one of ours from any other zip and say something useful instead of extracting nonsense.
        zf.writestr("selfbot-export.json", json.dumps({
            "version": __version__,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "portable": is_portable(),
        }, indent=2))
        skipped = _zip_members(zf, members)
    return {"ok": True, "path": str(target), "files": len(members) - len(skipped),
            "skipped": skipped[:20], "skipped_count": len(skipped),
            "size": target.stat().st_size}


@router.post("/api/system/export")
async def export_everything(request: Request):
    """Write a full export, either to a folder the user picked or to backups/. Includes the .env: the point is to be able to move the whole setup, and a copy without the tokens would not restore to a working app, which also makes the file worth keeping somewhere private."""
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
        # A thread: zipping a few hundred megabytes on the event loop froze the whole panel for the length of it.
        result = await asyncio.to_thread(_write_export, target)
    except OSError as exc:
        # Almost always the chosen folder itself: read-only, or a protected place like Program Files.
        raise HTTPException(status_code=500, detail=f"Could not write to that folder ({exc.strerror or exc}). "
                                                    "Pick another one, like Documents or Desktop.")
    bus.append("system", f"Exported {result['files']} files to {result['path']}"
               + (f", skipped {result['skipped_count']} in use" if result["skipped_count"] else ""))
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

    def work():
        try:
            with zipfile.ZipFile(path) as zf:
                return _stage_restore(zf)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="that is not a zip file")

    staged = await asyncio.to_thread(work)
    bus.append("system", f"Backup ready: {staged} files. Restart the app to finish restoring.", "warn")
    return {"ok": True, "files": staged, "restart": True,
            "note": "Restart the app to finish: the files are put in place before anything opens them."}


@router.get("/api/system/storage")
def storage(request: Request):
    """Where the data lives, and whether this is a portable install. Plain def: it walks and stats every file in the data folder, over six thousand with Snapchat installed, about a second and a half, and as async it did that on the event loop, freezing the whole panel each time System was opened."""
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

    def write():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": version}), encoding="utf-8")

    import asyncio
    await asyncio.to_thread(write)
    bus.append("system", f"Ignoring update {version}.")
    return {"ok": True, "ignored": version}


@router.get("/api/system/update/check")
async def update_check(request: Request):
    import asyncio
    # Synchronous httpx on the event loop stalled every other request for as long as GitHub took to answer. The client caches the result already.
    return await asyncio.to_thread(_update_check_blocking)


def _update_check_blocking():
    import urllib.error
    from app.core import update
    from app.utils import device
    try:
        release = update.latest(timeout=10)
    except urllib.error.HTTPError as e:
        return {"ok": False, "reason": f"GitHub API returned {e.code}"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    latest = release["tag"]
    # Which file on the release is this device's, and how it would go in:
    # the panel says "Update now" only where the app can do it itself.
    plan = update.plan(release)
    return {
        "ok": True,
        "current": __version__,
        "latest": latest or "unknown",
        # The comparison is the whole point: "latest is v1.6.0" says nothing unless you already know what you are running.
        "update_available": is_newer(latest, __version__),
        # Dismissed releases stay dismissed until a newer one appears.
        "ignored": _ignored_update() == latest,
        "url": release["page"],
        "notes": release["notes"],
        "published": release["published"],
        "device": device.label(),
        "method": plan["method"],
        "ready": plan["ready"],
        "why": plan["why"],
        "asset": plan["asset"]["name"] if plan["asset"] else None,
        "size": plan["asset"]["size"] if plan["asset"] else 0,
    }


@router.post("/api/system/update/run")
async def update_run(request: Request):
    """Update to the latest release, the way this copy was installed (see
    app/core/update.py). The download and the swap run on a thread; the
    answer says what is happening, or why it cannot."""
    import asyncio
    from app.core import update
    supervisor = getattr(request.app.state, "supervisor", None)
    port = getattr(supervisor, "port", None) or request.url.port
    result = await asyncio.to_thread(update.run, supervisor, port)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason") or "could not update")
    return result


# ── Snapchat on-demand installer ─────────────────────────────────────────────
@router.get("/api/snapchat/status")
async def snap_status(request: Request):
    import asyncio
    # Even cached, the first probe shells out to node for several seconds, and the .is_dir() checks touch disk. None of that belongs on the event loop.
    modules, chrome = await asyncio.to_thread(_snap_probe)
    return {
        "node": _which("node"),
        "npm": _which("npm"),
        "modules_installed": modules,
        "browser": chrome,
        # Which Chrome this is: one the machine already had, or one downloaded
        # for the app. The panel says so, because "installed" means different
        # things to someone deciding whether to click a 180 MB download.
        "browser_name": (await asyncio.to_thread(installed_browser))[0],
        # Only true when Snapchat can actually launch. Reporting node_modules alone said "installed" while every run failed on a missing Chrome.
        "deps_installed": bool(modules and chrome),
        "installing": _install_lock.locked(),
        "dir": str(SNAP_DIR),
        # What each runner is actually doing. "Running" used to mean only that the process existed, so an account sitting on a verification screen looked identical to one answering messages.
        "runners": await asyncio.to_thread(_snap_runner_states),
    }


# A running runner rewrites its state every minute, so one that has gone quiet for this long is not running any more. Its last state is still worth showing, "logged out" is the most useful thing to see after it stops, but as the last thing it said, not as what is happening now.
_SNAP_STATE_STALE = 180.0


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

    def _stream(argv, cwd, label, env=None) -> int:
        bus.append("snapchat-install", f"$ {label}")
        proc = subprocess.Popen(
            argv, cwd=str(cwd), env=env,
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

            # A previous run may have left an unpacked-but-empty browser dir. Puppeteer would treat that version as present and skip the download, so the install could never repair itself.
            _clear_broken_browsers()

            # chrome-headless-shell is another 113 MB that this app can never
            # use: the login and verification flow needs a real window. And when
            # the machine already has a browser, skip Puppeteer's own download
            # too - that is the whole 180 MB.
            name, existing = installed_browser()
            install_env = {**os.environ,
                           "PUPPETEER_SKIP_CHROME_HEADLESS_SHELL_DOWNLOAD": "true"}
            if existing:
                install_env["PUPPETEER_SKIP_DOWNLOAD"] = "true"
                bus.append("snapchat-install",
                           f"Found {name} already installed, skipping the browser "
                           f"download: {existing}")

            code = _stream([npm, "install", "--no-fund", "--no-audit"], SNAP_DIR,
                           "npm install", env=install_env)
            if code != 0:
                bus.append("snapchat-install", f"npm install failed with code {code}", "error")
                return

            # npm install alone is not enough: Puppeteer's browser download is a postinstall step that can fail quietly. Ask for the browser explicitly, then verify rather than trust the exit code.
            if not chrome_path(force=True):
                bus.append("snapchat-install",
                           "No browser found, downloading one (~180 MB).")
                argv = ([_which("npx"), "--yes", "puppeteer", "browsers", "install", "chrome"]
                        if _which("npx")
                        else [npm, "exec", "--yes", "--", "puppeteer", "browsers", "install", "chrome"])
                code = _stream(argv, SNAP_DIR, "puppeteer browsers install chrome",
                               env=install_env)
                if code != 0:
                    bus.append("snapchat-install",
                               f"Browser download failed with code {code}", "error")

            # The download leaves its archive behind: another 180 MB sitting
            # next to the browser it was already unpacked into.
            freed = _drop_browser_archives()
            if freed:
                bus.append("snapchat-install",
                           f"Removed {freed} MB of leftover download archives.")

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
