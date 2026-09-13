"""Carrying the whole setup somewhere else, and running it from a folder.

Two related promises:

  * A folder called "portable" beside the app means everything lives there and
    nothing is written to AppData, so the app can be kept on a stick.
  * Export writes every file that matters, tokens included, and import puts
    them back. Anything less is not a backup: restoring without the .env gives
    you an app that cannot log in.

The import reads paths out of a zip, which is the one place an archive can
attack the machine that opens it, so a member called ../../.env has to be
refused rather than written where it asks.
"""
import asyncio
import io
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


SANDBOX = Path(tempfile.mkdtemp(prefix="portable_"))
DATA = SANDBOX / "data"
(DATA / "config" / "pictures").mkdir(parents=True)
for d in ("logs", "backups", "ipc", "snapchat/node_modules/dep", "snapchat/chrome/win64"):
    (DATA / d).mkdir(parents=True, exist_ok=True)

(DATA / "config" / "config.yaml").write_text("bot:\n  typo_chance: 0.03\n", encoding="utf-8")
(DATA / "config" / ".env").write_text("DISCORD_TOKEN_1=a-real-token\n", encoding="utf-8")
(DATA / "config" / "instructions.txt").write_text("be yourself", encoding="utf-8")
(DATA / "config" / "identity_1.json").write_text('{"username":"me"}', encoding="utf-8")
(DATA / "config" / "bot_data.db").write_bytes(b"sqlite-ish")
(DATA / "config" / "pictures" / "IMG_1.png").write_bytes(b"png-ish")
(DATA / "logs" / "app.jsonl").write_text("noise", encoding="utf-8")
(DATA / "backups" / "old.zip").write_bytes(b"old")
(DATA / "ipc" / "tg_commands_1.json").write_text("[]", encoding="utf-8")
(DATA / "snapchat" / "node_modules" / "dep" / "big.js").write_bytes(b"x" * 4096)
(DATA / "snapchat" / "chrome" / "win64" / "chrome.exe").write_bytes(b"x" * 8192)

import app.utils.paths as paths
paths.DATA_DIR = DATA
import app.web.logbus as logbus
logbus.LOGS_DIR = DATA / "logs"
logbus.bus.file_path = DATA / "logs" / "app.jsonl"
import app.web.routes.system_routes as system_routes
system_routes.DATA_DIR = DATA


class Req:
    def __init__(self, body=None):
        self._body = body or {}

    async def json(self):
        return self._body


# ── What an export contains ─────────────────────────────────────────────────
print("== an export carries everything that matters ==")
result = asyncio.run(system_routes.export_everything(Req()))
with zipfile.ZipFile(result["path"]) as zf:
    names = set(zf.namelist())

check("the config is in it", "config/config.yaml" in names)
check("the persona is in it", "config/instructions.txt" in names)
check("the database is in it", "config/bot_data.db" in names)
check("pictures are in it", "config/pictures/IMG_1.png" in names)
check("account identities are in it", "config/identity_1.json" in names)
# Without this the restored app cannot log in, which is the whole point.
check("the tokens are in it", "config/.env" in names)
check("it is marked as ours", "selfbot-export.json" in names)

print()
print("== and leaves out what would only bloat it ==")
check("no logs", not any(n.startswith("logs/") for n in names), str(names))
check("no backups of backups", not any(n.startswith("backups/") for n in names))
check("no live IPC files", not any(n.startswith("ipc/") for n in names))
check("no node_modules", not any("node_modules" in n for n in names))
check("no downloaded browser", not any("chrome" in n for n in names))

# ── Round trip ──────────────────────────────────────────────────────────────
print()
print("== and it all comes back ==")
shutil.rmtree(DATA / "config")
restored = asyncio.run(system_routes.import_everything(Req({"path": result["path"]})))
check("files were restored", restored["files"] >= 6, str(restored))
check("the token survived",
      (DATA / "config" / ".env").read_text(encoding="utf-8").strip() == "DISCORD_TOKEN_1=a-real-token")
check("the persona survived",
      (DATA / "config" / "instructions.txt").read_text(encoding="utf-8") == "be yourself")
check("the picture survived", (DATA / "config" / "pictures" / "IMG_1.png").read_bytes() == b"png-ish")
check("it says a restart is needed", "estart" in restored.get("note", ""))

# ── A hostile or foreign archive ────────────────────────────────────────────
print()
print("== an archive cannot write outside the data folder ==")
evil = SANDBOX / "evil.zip"
with zipfile.ZipFile(evil, "w") as zf:
    zf.writestr("selfbot-export.json", "{}")
    zf.writestr("../../../pwned.txt", "gotcha")
try:
    asyncio.run(system_routes.import_everything(Req({"path": str(evil)})))
    check("a traversing path is refused", False, "it was accepted")
except Exception as exc:
    detail = getattr(exc, "detail", str(exc))
    check("a traversing path is refused", "unsafe" in str(detail).lower(), str(detail))
check("nothing was written above the data folder", not (SANDBOX / "pwned.txt").exists())
check("nor beside it", not (DATA.parent / "pwned.txt").exists())

foreign = SANDBOX / "holiday-photos.zip"
with zipfile.ZipFile(foreign, "w") as zf:
    zf.writestr("beach/1.jpg", "not ours")
try:
    asyncio.run(system_routes.import_everything(Req({"path": str(foreign)})))
    check("someone else's zip is refused", False, "it was accepted")
except Exception as exc:
    check("someone else's zip is refused", True)

try:
    asyncio.run(system_routes.import_everything(Req({"path": str(SANDBOX / "nope.zip")})))
    check("a missing file is refused", False)
except Exception:
    check("a missing file is refused", True)

# ── Exporting somewhere the user chose ──────────────────────────────────────
print()
print("== exporting to a chosen folder ==")
chosen = SANDBOX / "usb stick"
chosen.mkdir()
out = asyncio.run(system_routes.export_everything(Req({"folder": str(chosen)})))
check("written where asked", Path(out["path"]).parent == chosen, out["path"])
check("and it is a real zip", zipfile.is_zipfile(out["path"]))
try:
    asyncio.run(system_routes.export_everything(Req({"folder": str(SANDBOX / "no such place")})))
    check("a folder that does not exist is refused", False)
except Exception:
    check("a folder that does not exist is refused", True)

# ── The portable folder ─────────────────────────────────────────────────────
print()
print("== a folder called portable takes over ==")
import importlib
app_dir = paths.APP_DIR
check("no portable folder means none is reported",
      paths.portable_root() is None or paths.portable_root().is_dir())

made = app_dir / paths.PORTABLE_DIR_NAME
created = False
if not made.exists():
    made.mkdir()
    created = True
try:
    check("the folder beside the app is found", paths.portable_root() == made, str(paths.portable_root()))
    check("and it is reported as portable", paths.is_portable() is True)
    check("the data dir resolves to it", paths._resolve_data_dir() == made,
          str(paths._resolve_data_dir()))
finally:
    if created:
        made.rmdir()
check("removing it goes back to normal", paths.portable_root() is None)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
