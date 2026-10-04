"""Export, backup and restore, against a sandbox data folder.

Exporting from the System page said "access denied": the data folder holds the
app window's own browser cache (webview/), which that browser keeps locked while
the app is open, and one unreadable file aborted the whole export. Restoring
wrote straight over files the running accounts had open. Checked here: the
cache is left out, a locked file is skipped rather than fatal, the database is
copied consistently while open, and a restore is staged and put in place at the
next start, with the old database's write-ahead log removed so it cannot be
replayed onto the restored one.
"""
import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SANDBOX = Path(tempfile.mkdtemp(prefix="llmbot_backup_"))
for d in ("config", "logs", "backups", "webview/EBWebView/Default/Cache", "snapchat"):
    (SANDBOX / d).mkdir(parents=True, exist_ok=True)

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"
import app.web.routes.system_routes as sr
sr.DATA_DIR = SANDBOX

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


cfg = SANDBOX / "config"
(cfg / "config.yaml").write_text("bot:\n  prefix: '!'\n", encoding="utf-8")
(cfg / ".env").write_text("GROQ_API_KEY_1=gsk_x\n", encoding="utf-8")
(SANDBOX / "webview" / "EBWebView" / "Default" / "Cache" / "data_0").write_bytes(b"locked cache")
(SANDBOX / "snapchat" / "profile.json").write_text("{}", encoding="utf-8")

# A live database in WAL mode, with a row still sitting in the write-ahead log.
db = sqlite3.connect(cfg / "bot_data.db")
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA wal_autocheckpoint=0")
db.execute("CREATE TABLE t (v TEXT)")
db.execute("INSERT INTO t VALUES ('in the wal')")
db.commit()

print("== exporting ==")
names = [n for _, n in sr._export_members()]
check("the app window's cache is left out", not any(n.startswith("webview/") for n in names), str(names))
check("the database's scratch files are left out", not any(n.endswith(("-wal", "-shm")) for n in names))
check("settings and the database are in", "config/config.yaml" in names and "config/bot_data.db" in names)

# The file another program has open.
real_write = zipfile.ZipFile.write


def locked_write(self, filename, arcname=None, *a, **k):
    if str(arcname).endswith("profile.json"):
        raise PermissionError(13, "Access is denied")
    return real_write(self, filename, arcname, *a, **k)


zipfile.ZipFile.write = locked_write
try:
    out = sr._write_export(SANDBOX / "backups" / "export.zip")
finally:
    zipfile.ZipFile.write = real_write
check("a locked file does not stop the export", out["ok"] and out["skipped_count"] == 1, json.dumps(out)[:200])
check("and says which it left out", any("profile.json" in s for s in out["skipped"]))

with zipfile.ZipFile(SANDBOX / "backups" / "export.zip") as zf:
    snap = SANDBOX / "snap.db"
    snap.write_bytes(zf.read("config/bot_data.db"))
rows = sqlite3.connect(snap).execute("SELECT v FROM t").fetchall()
check("the database copy includes what was still in its write-ahead log", rows == [("in the wal",)], str(rows))

print("\n== restoring ==")
# Change things, then restore the export over them.
(cfg / "config.yaml").write_text("bot:\n  prefix: '?'\n", encoding="utf-8")
db.execute("INSERT INTO t VALUES ('written after the backup')")
db.commit()
db.close()
(cfg / "bot_data.db-wal").write_bytes(b"stale wal from the old database")


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


r = asyncio.run(sr.import_everything(_Req({"path": str(SANDBOX / "backups" / "export.zip")})))
check("an import is staged, not written over the live files", r["ok"] and r["restart"]
      and (cfg / "config.yaml").read_text(encoding="utf-8").endswith("'?'\n"), str(r))
check("into the pending folder", (SANDBOX / paths.PENDING_RESTORE / "config" / "config.yaml").is_file())

moved = paths.apply_pending_restore()
check("the next start puts it in place", moved >= 3 and "'!'" in (cfg / "config.yaml").read_text(encoding="utf-8"),
      str(moved))
check("and clears the pending folder", not (SANDBOX / paths.PENDING_RESTORE).exists())
check("the old database's write-ahead log is gone", not (cfg / "bot_data.db-wal").exists())
rows = sqlite3.connect(cfg / "bot_data.db").execute("SELECT v FROM t").fetchall()
check("the database is the backed-up one", rows == [("in the wal",)], str(rows))
check("nothing pending means nothing to do", paths.apply_pending_restore() == 0)

bad = SANDBOX / "evil.zip"
with zipfile.ZipFile(bad, "w") as zf:
    zf.writestr("selfbot-export.json", "{}")
    zf.writestr("../outside.txt", "x")
try:
    asyncio.run(sr.import_everything(_Req({"path": str(bad)})))
    check("a path out of the folder is refused", False)
except Exception as e:
    check("a path out of the folder is refused", "unsafe path" in str(getattr(e, "detail", e)))

print("\n== both processes that own the folder apply it ==")
cli = (ROOT / "app" / "cli.py").read_text(encoding="utf-8")
desk = (ROOT / "app" / "desktop.py").read_text(encoding="utf-8")
check("the supervisor does, after taking the lock", "apply_pending_restore()" in cli
      and cli.index("acquire_single_instance()", cli.index("def run_supervisor")) < cli.index("apply_pending_restore()"))
check("and so does the desktop window", "apply_pending_restore()" in desk)
page = (ROOT / "webui" / "src" / "pages" / "System.svelte").read_text(encoding="utf-8")
check("the page offers the restart that finishes it", "restartApp(false)" in page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
