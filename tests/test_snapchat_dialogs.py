"""The Snapchat dialog-dismisser, run in a real browser against local pages.

handlePopup() clicks buttons by the words on them, which is what fixed the bot
sitting behind "Welcome to Snapchat for Web!" for ever. It is also exactly the
kind of code that does damage quietly: the first version clicked "Next" six
times on the SIGN-IN page, where Next is the login form's submit button - an
empty login submitted over and over on a real account.

Nothing here touches Snapchat or any account. A plain browser is pointed at
HTML this test serves itself (tests/snapchat_dialogs.mjs).

Needs Node and Puppeteer. Puppeteer only exists once the Snapchat dependencies
have been installed from the panel, so on a machine without them this skips
rather than fails - the same arrangement as test_exe_parity.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "platforms" / "snapchat"


def _node_modules():
    """Wherever the Snapchat dependencies were installed, if anywhere."""
    candidates = [SRC / "node_modules"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "LLMSelfbot" / "snapchat" / "node_modules")
    for c in candidates:
        if (c / "puppeteer").is_dir():
            return c
    return None


def _link(target: Path, link: Path) -> bool:
    """Make `link` point at `target` without needing admin rights."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except Exception:
        return False


node = shutil.which("node")
modules = _node_modules()
if not node or not modules:
    print("  SKIP  needs Node and the Snapchat dependencies installed")
    print("\n0 passed, 0 failed")
    sys.exit(0)

work = Path(tempfile.mkdtemp(prefix="snapdlg_"))
try:
    # The test imports ./snapbot.js and resolves puppeteer by walking up to a
    # node_modules folder, so the pieces are assembled side by side.
    for name in ("snapbot.js", "log.js", "package.json"):
        shutil.copy(SRC / name, work / name)
    shutil.copy(ROOT / "tests" / "snapchat_dialogs.mjs", work / "snapchat_dialogs.mjs")
    if not _link(modules, work / "node_modules"):
        print("  SKIP  could not link node_modules here")
        print("\n0 passed, 0 failed")
        sys.exit(0)

    env = dict(os.environ, SNAP_DATA_DIR=str(work))
    proc = subprocess.run([node, "snapchat_dialogs.mjs"], cwd=work, env=env,
                          capture_output=True, text=True, timeout=180,
                          encoding="utf-8", errors="replace")
    out = "\n".join(l for l in proc.stdout.splitlines() if not l.startswith("[Snap]"))
    print("== the dialog dismisser, in a real browser ==")
    print(out.strip())
    if proc.returncode != 0 and "passed" not in out:
        print(proc.stderr[-1500:])
    sys.exit(proc.returncode)
finally:
    # Remove the junction itself first: rmtree must not follow it into the
    # real node_modules.
    nm = work / "node_modules"
    try:
        if os.name == "nt":
            os.rmdir(nm)
        else:
            nm.unlink()
    except Exception:
        pass
    shutil.rmtree(work, ignore_errors=True)
