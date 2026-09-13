"""Feature parity check: does the FROZEN exe do everything the script does?

Requires a build first:  pyinstaller packaging/selfbot.spec --noconfirm
Skips cleanly when dist/LLMSelfbot is absent so run_all.py stays green without it.

A watchdog force-kills every LLMSelfbot process if the count exceeds MAX_PROCS, 
an earlier build fork-bombed the machine and nothing here runs unguarded again.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE_DIR = ROOT / "dist" / "LLMSelfbot"
CONSOLE = EXE_DIR / "LLMSelfbot-console.exe"
PORT = 8811
MAX_PROCS = 8

if not CONSOLE.exists():
    print(f"SKIP: no build at {EXE_DIR}, run pyinstaller first.")
    print("0 passed, 0 failed")
    raise SystemExit(0)

stop = threading.Event()
breached = threading.Event()
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def nprocs():
    n = 0
    for name in ("LLMSelfbot-console.exe", "LLMSelfbot.exe"):
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        n += sum(1 for l in out.splitlines() if "LLMSelfbot" in l)
    return n


def kill_all():
    for name in ("LLMSelfbot-console.exe", "LLMSelfbot.exe"):
        subprocess.run(["taskkill", "/F", "/IM", name, "/T"], capture_output=True, text=True)


def watch():
    while not stop.is_set():
        if nprocs() > MAX_PROCS:
            print(f"\n!!! KILL SWITCH at {nprocs()} processes")
            breached.set(); kill_all(); stop.set(); return
        time.sleep(0.5)


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def req(path, method="GET", body=None, raw=None, ctype=None):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", ctype or "application/json")
    try:
        with urllib.request.urlopen(r, timeout=25) as resp:
            payload = resp.read().decode(errors="replace")
            try:
                return resp.status, json.loads(payload)
            except Exception:
                return resp.status, payload
    except urllib.error.HTTPError as e:
        payload = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, payload
    except Exception as e:
        return 0, str(e)


# ── Boot ─────────────────────────────────────────────────────────────────────
kill_all(); time.sleep(1)
FAKE = Path(tempfile.mkdtemp(prefix="llmbot_parity_"))
cfg = FAKE / "LLMSelfbot" / "config"
cfg.mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", cfg / "config.yaml")
shutil.copy(ROOT / "resources" / "instructions.txt", cfg / "instructions.txt")
(cfg / ".env").write_text("DISCORD_TOKEN_1=fakeAAA" + "z" * 28 + "\nGROQ_API_KEY_1=gsk_fake\n",
                          encoding="utf-8")

env = dict(os.environ, APPDATA=str(FAKE), PYTHONIOENCODING="utf-8", SELFBOT_PORT=str(PORT))
threading.Thread(target=watch, daemon=True).start()
print("=" * 64); print("  FROZEN EXE, FEATURE PARITY"); print("=" * 64)
proc = subprocess.Popen([str(CONSOLE)], env=env, cwd=str(EXE_DIR),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
lines = []
threading.Thread(target=lambda: [lines.append(l) for l in proc.stdout], daemon=True).start()

up = False
for _ in range(60):
    time.sleep(1)
    if req("/api/status")[0] == 200:
        up = True; break
    if breached.is_set():
        break

try:
    print("\n== boot ==")
    check("exe serves the API", up)
    if not up:
        raise SystemExit

    print("\n== no login gate ==")
    st, _ = req("/api/config")
    check("config reachable without a session", st == 200, str(st))
    st, _ = req("/api/auth/me")
    check("auth endpoints removed from the exe", st == 404, str(st))

    print("\n== config + secrets ==")
    st, conf = req("/api/config")
    check("config loads", st == 200 and "bot" in conf, str(st))
    st, sch = req("/api/config/schema")
    check("settings schema renders", st == 200 and len(sch.get("fields", [])) > 20,
          str(len(sch.get("fields", []))))
    st, sec = req("/api/secrets")
    tok = sec.get("secrets", {}).get("DISCORD_TOKEN_1", "")
    check("secrets are masked", "…" in tok and len(tok) < 20, tok)
    st, r = req("/api/config/field", "POST", {"key": "bot.typo_chance", "value": 0.09})
    check("config field write", st == 200, str(r))
    st, conf = req("/api/config")
    check("config change persisted", conf["bot"]["typo_chance"] == 0.09, str(conf["bot"]["typo_chance"]))

    print("\n== instructions (persona) ==")
    st, r = req("/api/instructions", "POST", {"text": "parity check persona"})
    check("instructions write", st == 200, str(r))
    st, r = req("/api/instructions")
    check("instructions read back", r.get("text") == "parity check persona", str(r)[:80])

    print("\n== accounts / supervisor ==")
    st, acc = req("/api/accounts")
    check("accounts endpoint", st == 200 and isinstance(acc.get("accounts"), list), str(st))
    names = [a.get("id") for a in acc.get("accounts", [])]
    check("discord account is managed", any("discord" in str(n) for n in names), str(names))

    print("\n== live logs (websocket path) ==")
    st, logs = req("/api/logs?n=50")
    entries = logs.get("lines", logs.get("logs", [])) if isinstance(logs, dict) else logs
    check("log buffer is populated", st == 200 and len(entries) > 0, f"{st} {str(logs)[:120]}")
    check("supervisor lines captured", any("upervisor" in json.dumps(e) for e in entries),
          json.dumps(entries)[:200])
    check("worker stdout captured (proves pipe capture works)",
          any("discord" in json.dumps(e).lower() for e in entries), json.dumps(entries)[-300:])

    print("\n== pictures (multipart upload) ==")
    # A real image, not a PNG header with padding behind it: the import decodes
    # what it is given so it can convert anything, which means junk that merely
    # looks like a picture is now correctly refused.
    import base64 as _b64
    png = _b64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///+/v7"
        "+jQ3Y5AAAADklEQVQI12P4AIX8EAgALgAD/aNpbtEAAAAASUVORK5CYII=")
    boundary = "----parity"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"parity.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + png + \
           f"\r\n--{boundary}--\r\n".encode()
    st, r = req("/api/pictures", "POST", raw=body, ctype=f"multipart/form-data; boundary={boundary}")
    check("multipart upload accepted (python-multipart bundled)", st in (200, 201), f"{st} {str(r)[:160]}")
    st, pics = req("/api/pictures")
    listed = pics.get("pictures", []) if isinstance(pics, dict) else pics
    check("uploaded picture listed (renamed to IMG_N by design)",
          st == 200 and len(listed) >= 1, str(pics)[:200])

    # Pillow and its HEIC plugin have to survive freezing, or every iPhone
    # photo fails in the built app while working perfectly from source.
    st, doc = req("/api/system/info")
    import io as _io
    import zipfile as _zip
    zbuf = _io.BytesIO()
    with _zip.ZipFile(zbuf, "w") as _z:
        _z.writestr("folder/inner.png", png)
    zbody = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"parity.zip\"\r\nContent-Type: application/zip\r\n\r\n").encode() \
        + zbuf.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    st, r = req("/api/pictures", "POST", raw=zbody,
                ctype=f"multipart/form-data; boundary={boundary}")
    check("zip import works in the frozen build",
          st == 200 and len((r or {}).get("added", [])) == 1, f"{st} {str(r)[:160]}")

    print("\n== stats (sqlite) ==")
    st, lb = req("/api/stats/leaderboard")
    check("leaderboard query runs", st == 200, f"{st} {str(lb)[:120]}")

    print("\n== system doctor ==")
    st, doc = req("/api/system/doctor")
    check("doctor runs", st == 200, str(st))
    # Keyed by id rather than name: the labels are user-facing prose and have
    # been reworded once already, which broke these assertions rather than
    # catching anything.
    checks = {c.get("id", c["name"]): c for c in doc.get("checks", [])}
    check("reports frozen build", doc.get("frozen") is True, str(doc.get("frozen")))
    check("data dir is APPDATA, not the install dir", "LLMSelfbot" in doc.get("data_dir", ""),
          doc.get("data_dir"))
    check("web UI bundled", checks.get("webui", {}).get("ok") is True, str(checks.get("webui")))
    check("port check no longer false-negative", checks.get("port", {}).get("ok") is True,
          json.dumps([{k: v.get("ok")} for k, v in checks.items()]))
    # Every red row must carry something to do about it, which is the whole
    # point of the doctor being clickable.
    unactionable = [k for k, c in checks.items()
                    if not c.get("ok") and not (c.get("action") or c.get("fix"))]
    check("failing checks all have a fix", not unactionable, str(unactionable))
    print("     doctor:", json.dumps({n: c.get("ok") for n, c in checks.items()}))

    print("\n== ffmpeg support ==")
    st, ff = req("/api/system/ffmpeg")
    check("ffmpeg endpoint present", st == 200, f"{st} {str(ff)[:120]}")
    check("ffmpeg discoverable or installable",
          bool(ff.get("ffmpeg")) or ff.get("installable"), str(ff))

    print("\n== snapchat on-demand installer ==")
    st, snap = req("/api/snapchat/status")
    check("snapchat status endpoint", st == 200, str(st))
    check("node detected on this machine", bool(snap.get("node")), str(snap))

    print("\n== update check ==")
    st, upd = req("/api/system/update/check")
    check("update check reachable", st == 200, str(st))

    print("\n== backup ==")
    st, _ = req("/api/system/backup")
    check("backup zip generated", st == 200, str(st))

    print("\n== SPA ==")
    st, html = req("/")
    check("control panel HTML served", st == 200 and "<html" in str(html).lower(), str(html)[:80])

finally:
    stop.set()
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    kill_all()
    peak_note = "KILL SWITCH FIRED" if breached.is_set() else "process count stayed sane"
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed   ({peak_note}; now {nprocs()} running)")
    print("\n--- first exe output lines ---")
    print("".join(lines[:8]))
    shutil.rmtree(FAKE, ignore_errors=True)

sys.exit(1 if FAIL else 0)
