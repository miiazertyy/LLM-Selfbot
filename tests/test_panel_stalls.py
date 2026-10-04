"""The panel freezing, and the things that caused it.

The big one: the Discord worker read and wrote the IPC files with the Windows
default encoding (cp1252) while the panel wrote UTF-8. An answer left in the
results file that held an emoji or an accent came back as mojibake, was written
out like that, and doubled in size on every pass. A 60-character chat preview
reached tens of megabytes, the file 900 MB, and the panel - which parsed the
whole file three times a second per waiting call, on its event loop - froze.

Checked here: the round trip is lossless and stable, a runaway file is started
over rather than parsed, an unchanged file is not re-read, the slow handlers
are off the event loop, the stall watchdog reports a stall, and the UI no
longer rebuilds date formatters or forces layouts where it did.
"""
import ast
import asyncio
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="stalls_"))
for d in ("config", "ipc", "logs"):
    (SANDBOX / d).mkdir(parents=True)

import app.core.ipc as ipc
ipc.CONFIG_DIR = SANDBOX / "config"
ipc.IPC_DIR = SANDBOX / "ipc"
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


# ── The round trip ──────────────────────────────────────────────────────────
print("== an answer with an emoji survives any number of passes ==")
f = ipc.result_file(1)
snippet = "t'es où 😭 ça va ?"
ipc.append_result(f, "left-behind", {"users": [{"id": "1", "snippet": snippet}]})
for n in range(40):
    ipc.append_result(f, f"answer-{n}", {"paused": False, "mood": "chill"})   # the worker
    found, _ = ipc._take_result(f, f"answer-{n}")                              # the panel
    assert found
left = json.loads(f.read_text(encoding="utf-8")).get("left-behind")
check("the text is exactly what was written", left and left["users"][0]["snippet"] == snippet,
      repr(left)[:120])
check("and the file has not grown", f.stat().st_size < 2000, str(f.stat().st_size))

print()
print("== a runaway file is started over, not parsed ==")
f.write_bytes(b'{"x": "' + b"\\u00c3" * (ipc.MAX_FILE_BYTES // 6 + 10) + b'"}')
t0 = time.perf_counter()
got = ipc._read_json(f, {})
check("an oversized file reads as empty", got == {}, str(type(got)))
check("without parsing it", time.perf_counter() - t0 < 1.0, f"{time.perf_counter() - t0:.2f}s")
check("and is replaced with an empty one", f.stat().st_size < 10, str(f.stat().st_size))
ipc.append_result(f, "fresh", {"ok": True})
check("the worker carries on writing to it", json.loads(f.read_text(encoding="utf-8")) == {"fresh": {"ok": True}})

print()
print("== the panel only re-reads the file when it changes ==")
reads = []
_real_take = ipc._take_result
ipc._take_result = lambda path, cid: (reads.append(1), _real_take(path, cid))[1]


async def _late_answer():
    await asyncio.sleep(1.0)
    ipc.append_result(f, "late", {"ok": "yes"})


async def _wait():
    task = asyncio.create_task(_late_answer())
    got = await ipc.wait_for_result(1, "late", timeout=4)
    await task
    return got


got = asyncio.run(_wait())
ipc._take_result = _real_take
check("it gets the answer", got == {"ok": "yes"}, str(got))
check("reading only when the file changed, not every 0.3s", len(reads) <= 3, f"{len(reads)} reads")
check("and takes its answer out of the file",
      "late" not in json.loads(f.read_text(encoding="utf-8")))

print()
print("== every process reads and writes the IPC files as UTF-8 ==")
for rel in ("app/platforms/discord_runner.py", "app/platforms/snapchat_bridge.py",
            "app/telegram_bot/telegram_controller.py", "app/core/ipc.py"):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    bare = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("read_text", "write_text")
            # personas.read_text is a persona's text, read as UTF-8 by that module, not a file read here.
            and not (isinstance(n.func.value, ast.Name) and n.func.value.id == "personas")
            and not any(k.arg == "encoding" for k in n.keywords)]
    check(f"{rel}: no read_text/write_text on the platform default", not bare, f"lines {bare}")
runner = (ROOT / "app/platforms/discord_runner.py").read_text(encoding="utf-8")
check("the worker posts answers through the shared helper", "append_result(_RESULT_FILE" in runner)

print()
print("== slow handlers are off the event loop ==")
for rel, name in (("app/web/routes/system_routes.py", "storage"),
                  ("app/web/routes/chat_routes.py", "memory_list"),
                  ("app/web/routes/chat_routes.py", "archive")):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    kinds = [type(n).__name__ for n in tree.body if getattr(n, "name", "") == name]
    check(f"{name} runs on a thread (plain def)", kinds == ["FunctionDef"], str(kinds))

print()
print("== a stall is reported, with what was being answered ==")
import app.web.server as server


async def _stall():
    dog = asyncio.create_task(server._stall_watchdog())
    await asyncio.sleep(0.15)
    key = object()
    server._IN_FLIGHT[key] = "/api/slow-thing"
    time.sleep(0.6)                      # a handler blocking the loop
    await asyncio.sleep(0.25)
    server._IN_FLIGHT.pop(key, None)
    dog.cancel()


asyncio.run(_stall())
lines = [e["text"] for e in logbus.bus.tail(20) if e["source"] == "panel"]
check("the watchdog logs it, saying what it meant", any("froze for" in t and "no page could load" in t for t in lines), str(lines))
check("naming the request in flight", any("/api/slow-thing" in t for t in lines), str(lines))

print()
print("== the UI side ==")
src = ROOT / "webui" / "src"
offenders = []
for p in src.rglob("*"):
    if p.suffix in (".svelte", ".ts") and p.name != "fmt.ts":
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"toLocale(Date|Time)?String\(\s*(undefined|\[\])\s*,", line):
                offenders.append(f"{p.name}:{i}")
check("dates use cached formatters (lib/fmt.ts), not a new one per call", not offenders, ", ".join(offenders))
app_svelte = (src / "App.svelte").read_text(encoding="utf-8")
check("the sidebar indicator measures once per frame",
      "new MutationObserver(queueMeasure)" in app_svelte and "new ResizeObserver(queueMeasure)" in app_svelte)
check("account cards are not flip-animated on every refresh",
      "animate:flip={" not in (src / "pages" / "Accounts.svelte").read_text(encoding="utf-8"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
