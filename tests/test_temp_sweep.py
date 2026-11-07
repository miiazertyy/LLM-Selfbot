"""The single-file exe's old unpack folders cleared, and never one in use (app/utils/tempsweep.py, 2026-11-06).

221 _MEI folders of about 110 MB had piled up in the temp folder: the app ended rather than closed leaves its own. The
sweep clears the app's stale ones a minute after it starts. A folder whose Python DLL is loaded by a running copy is left
whole (Windows refuses to delete a loaded DLL; renaming the folder is allowed, so that proves nothing), as are recent
ones and other programs' folders.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import tempsweep  # noqa: E402

base = Path(tempfile.mkdtemp(prefix="sweep-"))
OLD = time.time() - 3600


def unpacked(name, ours=True, old=True, dll=True):
    folder = base / name
    (folder / "lib").mkdir(parents=True)
    (folder / "lib" / "thing.pyd").write_bytes(b"x" * 100)
    if ours:
        (folder / "resources").mkdir()
        (folder / "resources" / "config.yaml").write_text("bot: {}\n", encoding="utf-8")
        (folder / "webui").mkdir()
    if dll:
        if sys.platform == "win32":
            shutil.copy(Path(sys.base_prefix) / "python3.dll", folder / "python312.dll")
        else:
            (folder / "python312.dll").write_bytes(b"MZ")
    if old:
        for p in [folder, *folder.rglob("*")]:
            os.utime(p, (OLD, OLD))
    return folder


own = unpacked("_MEI100", old=False)
gone = unpacked("_MEI200")
busy = unpacked("_MEI300")
fresh = unpacked("_MEI400", old=False)
theirs = unpacked("_MEI500", ours=False)
(base / "notes").mkdir()

print("== which are looked at ==")
found = {p.name for p in tempsweep.stale(own)}
check("the app's own old ones", {"_MEI200", "_MEI300"} <= found, str(found))
check("never the one it is running from", "_MEI100" not in found)
check("nor one changed in the last ten minutes: a copy may be unpacking into it", "_MEI400" not in found)
check("nor another program's", "_MEI500" not in found)
check("nor anything not named as an unpack folder", "notes" not in found)

print("\n== in use, left whole ==")
holder = None
if sys.platform == "win32":
    holder = subprocess.Popen([sys.executable, "-c", "import ctypes, sys, time; ctypes.WinDLL(sys.argv[1]); "
                               "print('loaded', flush=True); time.sleep(60)", str(busy / "python312.dll")],
                              stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    check("a folder whose DLL a running copy has loaded is not cleared", tempsweep.clear(busy) is False)
    check("  and nothing in it was deleted", (busy / "python312.dll").exists() and (busy / "lib" / "thing.pyd").exists()
          and (busy / "resources" / "config.yaml").exists())
else:
    print("  SKIP  a loaded DLL can be deleted outside Windows, which is why the sweep only runs there")

print("\n== the sweep ==")
cleared, left = tempsweep.sweep(own)
check("the unused old one is cleared, all of it", not gone.exists(), str(list(base.iterdir())))
if holder:
    check("the one in use is counted as left", left == 1 and busy.exists(), f"{cleared} {left}")
    holder.kill()
    holder.wait()
check("the running one, the fresh one and another program's are all still there", own.exists() and fresh.exists()
      and theirs.exists())
src = (ROOT / "app" / "utils" / "tempsweep.py").read_text(encoding="utf-8")
check("only in the frozen Windows app, a while after it starts, off the main thread",
      'sys.platform != "win32" or not getattr(sys, "frozen", False)' in src and "time.sleep(delay)" in src
      and "daemon=True" in src)
check("started once the app is the one copy running", "tempsweep.start()" in (ROOT / "app" / "cli.py").read_text(encoding="utf-8"))
shutil.rmtree(base, ignore_errors=True)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
