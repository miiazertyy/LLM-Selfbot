"""mindcraft-ce, fetched and installed on demand (Settings, Minecraft, Install).

Never vendored into the app: it is a whole Node app, about 1.4 GB once installed. It is downloaded at one pinned
commit over https, so no git is needed; unpacked with tarfile's "data" filter, so nothing in the archive can land
outside its folder; installed with npm; and then checked by actually importing it, because an install that exits 0
can still leave a native module that will not load.

Where things live:
  DATA_DIR/mindcraft/             mindcraft-ce itself, as upstream ships it, and its node_modules
  DATA_DIR/mindcraft/bots/        what mindcraft remembers per bot: kept across a reinstall and an uninstall
  DATA_DIR/mindcraft/.llmselfbot-install.json   which commit is installed, and when
The app's own Minecraft files (generated profiles, stats) live in DATA_DIR/minecraft/, apart from this, so a
reinstall never touches them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable

from app.utils.paths import DATA_DIR
from app.utils.procs import quiet_kwargs

MINDCRAFT_REPO = "mindcraft-ce/mindcraft-ce"
# develop@236c252: the commit whose contract this integration was built against and checked by reading its source.
# Its MindServer takes a control token, which `stable` (42da10d) does not: there, anything on the machine could
# drive the bot, and what it says is sent to every connection. A commit, never a branch: an upstream change to the
# profile or settings shape would otherwise break the generated profile without a word.
MINDCRAFT_COMMIT = "236c252467f565e55ffac7ab8dce7fb7ad95edf9"
MIN_NODE = 22                 # its package.json: "engines": {"node": ">=22.13.0"}
MIN_FREE_GB = 5.0             # 1.4 GB installed, npm's cache and the extract on top

MC_DIR = DATA_DIR / "mindcraft"
MARKER = MC_DIR / ".llmselfbot-install.json"
# What survives a reinstall and an uninstall: the bots' own memory, and node_modules on a reinstall (npm then only
# brings it up to date, which takes seconds instead of minutes).
_KEEP = {"bots", "node_modules", MARKER.name}

Say = Callable[..., None]


def _which(name: str) -> str | None:
    return shutil.which(name)


def node_version() -> tuple[str, int]:
    """("v24.16.0", 24), or ("", 0) when there is no Node."""
    node = _which("node")
    if not node:
        return "", 0
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20,
                             **quiet_kwargs()).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "", 0
    m = re.match(r"v(\d+)", out)
    return out, int(m.group(1)) if m else 0


def free_gb(where: Path = DATA_DIR) -> float:
    try:
        return round(shutil.disk_usage(where).free / 1e9, 1)
    except OSError:
        return 0.0


def installed_commit() -> str:
    try:
        return str(json.loads(MARKER.read_text(encoding="utf-8")).get("commit") or "")
    except (OSError, ValueError):
        return ""


def present() -> bool:
    """mindcraft is on disk and has its modules: what running it needs, whatever commit it is."""
    return ((MC_DIR / "main.js").is_file() and (MC_DIR / "node_modules" / "mineflayer").is_dir()
            and (MC_DIR / "node_modules" / "socket.io-client").is_dir())


def status() -> dict:
    """For the Minecraft setup panel. Blocking (it asks Node its version): call it on a thread."""
    version, major = node_version()
    commit = installed_commit()
    there = present()
    return {
        "node": _which("node") or "",
        "node_version": version,
        "node_ok": major >= MIN_NODE,
        "npm": _which("npm") or "",
        "installed": there,
        "commit": commit,
        "pinned": MINDCRAFT_COMMIT,
        # On disk but at another commit, or put there by hand: works, but is not the one this app was built for.
        "up_to_date": there and commit == MINDCRAFT_COMMIT,
        "dir": str(MC_DIR),
        "free_gb": free_gb(),
    }


def _stream(argv: list, cwd: Path, label: str, say: Say, env: dict | None = None) -> int:
    say(f"$ {label}")
    proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, encoding="utf-8", errors="replace", **quiet_kwargs())
    for line in proc.stdout:
        say(line)
    return proc.wait()


def _download(url: str, to: Path, say: Say) -> None:
    """The archive, tried three times: a GitHub download that drops halfway is not worth failing the install for."""
    for attempt in range(1, 4):
        try:
            started = time.time()
            with urllib.request.urlopen(url, timeout=60) as res, open(to, "wb") as out:
                while chunk := res.read(1 << 16):
                    out.write(chunk)
            say(f"Downloaded {to.stat().st_size / 1e6:.1f} MB in {time.time() - started:.1f}s.")
            return
        except OSError as e:
            if attempt == 3:
                raise
            say(f"The download stopped ({e}); trying again.", "warn")
            time.sleep(3 * attempt)


def _unpack(archive: Path, into: Path) -> int:
    """Everything under the archive's one top folder, into `into`, with that folder stripped. The "data" filter
    refuses absolute paths, "..", links out of the folder and device files: this is an archive off the internet."""
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        top = next((m.name.split("/")[0] for m in members if "/" in m.name), "")
        kept = []
        for m in members:
            parts = m.name.split("/", 1)
            if parts[0] != top or len(parts) == 1 or not parts[1]:
                continue
            m.name = parts[1]
            kept.append(m)
        tar.extractall(into, members=kept, filter="data")
    return len(kept)


def _clear_source(say: Say) -> None:
    """The old commit's files out of the way, so none of them outlive the upgrade. node_modules and the bots' memory
    stay (see _KEEP)."""
    if not MC_DIR.is_dir():
        return
    for p in MC_DIR.iterdir():
        if p.name in _KEEP:
            continue
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                p.unlink()
            except OSError:
                pass


def _verify(node: str, say: Say) -> bool:
    """Not that the files exist, but that they load: an install can exit 0 and still leave a native module that
    will not. These are the ones the runner and the bot cannot do without."""
    for must in ("main.js", "settings.js", "profiles/defaults/_default.json", "src/mindcraft/mindserver.js",
                 "node_modules/mineflayer", "node_modules/socket.io-client"):
        if not (MC_DIR / must).exists():
            say(f"Missing after the install: {must}", "error")
            return False
    probe = ("Promise.all(['mineflayer','socket.io-client','minecraft-data'].map(m=>import(m)))"
             ".then(()=>process.exit(0),e=>{console.error(String(e&&e.message||e));process.exit(1)})")
    try:
        r = subprocess.run([node, "-e", probe], cwd=str(MC_DIR), capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace", **quiet_kwargs())
    except (OSError, subprocess.SubprocessError) as e:
        say(f"Could not check the install: {e}", "error")
        return False
    if r.returncode != 0:
        say(f"Installed, but it does not load: {(r.stderr or r.stdout).strip()[:300]}", "error")
        return False
    return True


def install(say: Say) -> bool:
    """Download, unpack, npm install, verify, record. Blocking, minutes long: run it on a thread. `say(line, level)`
    is where every step is reported, as it happens, so the panel never looks stuck."""
    npm, node = _which("npm"), _which("node")
    if not npm or not node:
        say("Node.js is not installed. Install it from nodejs.org (version 22 or newer), then try again.", "error")
        return False
    version, major = node_version()
    if major < MIN_NODE:
        say(f"mindcraft needs Node.js {MIN_NODE} or newer; this computer has {version or 'an unknown version'}.",
            "error")
        return False
    room = free_gb()
    if room and room < MIN_FREE_GB:
        say(f"Only {room} GB free; mindcraft needs about {MIN_FREE_GB:.0f} GB to install.", "error")
        return False
    say(f"Installing mindcraft-ce at {MINDCRAFT_COMMIT[:7]} with Node {version}, {room} GB free. "
        "This takes about 5 to 15 minutes.")

    tmp_root = DATA_DIR / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mindcraft-", dir=tmp_root) as tmp:
        archive = Path(tmp) / f"mindcraft-{MINDCRAFT_COMMIT[:7]}.tar.gz"
        _download(f"https://codeload.github.com/{MINDCRAFT_REPO}/tar.gz/{MINDCRAFT_COMMIT}", archive, say)
        staged = Path(tmp) / "src"
        staged.mkdir()
        n = _unpack(archive, staged)
        if not (staged / "main.js").is_file() or not (staged / "package.json").is_file():
            say("The download was not mindcraft-ce: no main.js or package.json in it.", "error")
            return False
        MC_DIR.mkdir(parents=True, exist_ok=True)
        _clear_source(say)
        for p in staged.iterdir():
            dest = MC_DIR / p.name
            if p.name in _KEEP and dest.exists():
                continue
            shutil.move(str(p), str(dest))
        say(f"Unpacked {n} files into {MC_DIR}.")

    # patch-package runs as mindcraft's postinstall and is one of its devDependencies, so dev dependencies must be
    # installed: no --omit=dev, and no NODE_ENV=production leaking in from the environment, or the postinstall
    # fails and takes the whole install with it.
    env = {k: v for k, v in os.environ.items() if k != "NODE_ENV"}
    code = _stream([npm, "install", "--no-fund", "--no-audit", "--prefer-offline"], MC_DIR, "npm install", say,
                   env=env)
    if code != 0:
        say(f"npm install failed with code {code}. The lines above say why.", "error")
        return False
    if not _verify(node, say):
        return False
    MARKER.write_text(json.dumps({"commit": MINDCRAFT_COMMIT, "installed_at": time.time(), "node": version}),
                      encoding="utf-8")
    say(f"mindcraft-ce is installed ({MINDCRAFT_COMMIT[:7]}). Add a Minecraft account on the Accounts page to play.")
    return True


def uninstall(say: Say) -> float:
    """Everything but the bots' memory (DATA_DIR/mindcraft/bots), which is small and is what makes a reinstall pick
    up where it left off. Returns the GB freed."""
    if not MC_DIR.is_dir():
        return 0.0
    before = free_gb()
    for p in MC_DIR.iterdir():
        if p.name == "bots":
            continue
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                p.unlink()
            except OSError:
                pass
    freed = max(0.0, round(free_gb() - before, 1))
    say(f"mindcraft-ce removed, {freed} GB freed. What its bots remember is kept in {MC_DIR / 'bots'}.")
    return freed
