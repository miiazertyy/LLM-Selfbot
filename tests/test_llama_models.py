"""llama.cpp gets its models from the app, and every server the app can start starts with it.

Ollama downloads models itself; llama.cpp has no download that works everywhere (its own `llama download` could
not reach Hugging Face on one computer), so the app fetches the model's file into its own models folder and starts
llama.cpp again on it, since it reads that folder only as it starts. One computer had Hugging Face cut about every
other connection as it opened, so the download carries on from where it stopped instead of failing.

Nothing here downloads anything real or starts a real server: Hugging Face is a small server on this machine that
drops the line on purpose, and starting a process is faked.
"""
import http.server
import os
import socket
import sys
import tempfile
import threading
import time
import types
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.utils import localai, localfix  # noqa: E402
import app.web.logbus  # noqa: E402,F401

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / "webui" / "src" / rel).read_text(encoding="utf-8")


tmp = Path(tempfile.mkdtemp(prefix="llama-models-"))
real = {k: getattr(localai, k) for k in ("app_models_dir", "installed", "pull_supported", "_restart_llama",
                                          "_save_base_url", "start_server", "time")}
localai.app_models_dir = lambda: tmp

print("== what was typed, as a Hugging Face repo and size ==")
check("user/model:size", localai._hf_name("bartowski/SmolLM2-135M-Instruct-GGUF:q4_k_m")
      == ("bartowski/SmolLM2-135M-Instruct-GGUF", "Q4_K_M"))
check("hf.co/, a link and :latest are the same repo, any size",
      localai._hf_name("hf.co/a/b") == localai._hf_name("https://huggingface.co/a/b?x=1")
      == localai._hf_name("a/b:latest") == ("a/b", ""))
check("an Ollama name is no Hugging Face repo", localai._hf_name("llama3.1:8b") == ("", ""))

print("\n== how llama.cpp is started ==")
argv = localai._argv("llamacpp", r"C:\x\llama.exe", "http://127.0.0.1:8080/v1", {})
check("the all-in-one llama serves the app's models folder",
      argv[:2] == [r"C:\x\llama.exe", "serve"] and argv[-2:] == ["--models-dir", str(tmp)], str(argv))
argv = localai._argv("llamacpp", r"C:\x\llama-server.exe", "http://127.0.0.1:8080/v1", {})
check("an older llama-server as before", argv[1] == "--host" and "--models-dir" not in argv, str(argv))
check("told apart by name", localai.is_llama_cli(r"C:\a\llama.EXE") and not localai.is_llama_cli("llama-server"))
cands = localai._candidates("llamacpp")
check("found where the Store and winget put it, the all-in-one first",
      any(c.endswith(os.path.join("WindowsApps", "llama.exe")) for c in cands)
      and cands.index(next(c for c in cands if c.endswith("llama.exe"))) < cands.index(
          next(c for c in cands if c.endswith("llama-server.exe"))))

print("\n== who gets a model how ==")
localai.pull_supported = lambda url: url.endswith(":11434/v1")
localai.installed = lambda sid: r"C:\x\llama.exe" if sid == "llamacpp" else ""
check("Ollama downloads it itself", localai.pull_kind("http://127.0.0.1:11434/v1") == "ollama")
check("llama.cpp is given the file", localai.pull_kind("http://127.0.0.1:8080/v1") == "file")
localai.installed = lambda sid: ""
check("and nothing for a llama.cpp that is not on this computer", localai.pull_kind("http://127.0.0.1:8080/v1") == "")
localai.installed = lambda sid: r"C:\x\llama.exe" if sid == "llamacpp" else ""

print("\n== picking the file ==")
files = [{"name": "M-Q4_K_M.gguf", "size": 2 * 10**9}, {"name": "M-Q8_0.gguf", "size": 4 * 10**9},
         {"name": "mmproj-M-F16.gguf", "size": 10**9}, {"name": "README.md", "size": 10}]
started = []
localfix_repo_files = localfix.repo_files
localfix.repo_files = lambda repo: files
real_thread = localai.threading.Thread
localai.threading = types.SimpleNamespace(Thread=lambda **kw: types.SimpleNamespace(start=lambda: started.append(kw)),
                                          Lock=threading.Lock)
# A disk of its own: what happens to be free on the one the tests run on is not the point (a nearly full one failed
# every check here), and a full one has a check of its own.
import shutil  # noqa: E402
real_disk_usage = shutil.disk_usage
disk = {"free": 500 * 10**9}
shutil.disk_usage = lambda path: types.SimpleNamespace(total=10**12, used=10**12 - disk["free"], free=disk["free"])
try:
    files[:] = [{"name": "M-Q4_K_M.gguf", "size": 2 * 10**9}]
    disk["free"] = 2 * 10**9
    r = localai._start_file_pull("org/M-GGUF:Q4_K_M", "http://127.0.0.1:8080/v1")
    check("a disk without room for it says so, and fetches nothing",
          not r["ok"] and "Not enough room on the disk" in r["reason"] and not started, str(r))
    disk["free"] = 500 * 10**9
    files[:] = [{"name": "M-Q4_K_M.gguf", "size": 2 * 10**9}, {"name": "M-Q8_0.gguf", "size": 4 * 10**9},
                {"name": "mmproj-M-F16.gguf", "size": 10**9}, {"name": "README.md", "size": 10}]
    r = localai._start_file_pull("org/M-GGUF:Q5_K_M", "http://127.0.0.1:8080/v1")
    check("a size the repo has not got is named, with the ones it has",
          not r["ok"] and "Q4_K_M" in r["reason"] and "Q8_0" in r["reason"], str(r))
    r = localai._start_file_pull("llama3.1:8b", "http://127.0.0.1:8080/v1")
    check("a name that is no repo says how to write one", not r["ok"] and "user/model" in r["reason"], str(r))
    files[:] = [{"name": "README.md", "size": 10}]
    r = localai._start_file_pull("org/M-GGUF", "http://127.0.0.1:8080/v1")
    check("a repo with no .gguf says so", not r["ok"] and ".gguf" in r["reason"], str(r))
    files[:] = [{"name": "M-Q4_K_M.gguf", "size": 2 * 10**9}]
    r = localai._start_file_pull("org/M-GGUF:Q4_K_M", "http://127.0.0.1:8080/v1")
    check("one that is there starts, named by repo and size, in the background",
          r["ok"] and r["model"] == "org/M-GGUF:Q4_K_M" and started and localai.pull_status()["active"], str(r))
    r2 = localai._start_file_pull("org/M-GGUF:Q4_K_M", "http://127.0.0.1:8080/v1")
    check("the same one twice is not fetched twice", not r2["ok"] and "already on its way" in r2["reason"], str(r2))
    files[:] = [{"name": "N-Q4_K_M.gguf", "size": 10**9}]
    r3 = localai.start_pull("org/N-GGUF:Q4_K_M", "http://127.0.0.1:8080/v1")
    check("another, asked for while one downloads, waits its turn in a queue",
          r3["ok"] and r3.get("queued") == 1 and localai.pull_status()["queue"] == [{"model": "org/N-GGUF:Q4_K_M"}]
          and len(started) == 1, str(r3))
    check("it can be taken out of the queue", localai.unqueue("org/N-GGUF:Q4_K_M")["ok"]
          and localai.pull_status()["queue"] == [])
    localai.start_pull("org/N-GGUF:Q4_K_M", "http://127.0.0.1:8080/v1")
    localai._finish("org/M-GGUF:Q4_K_M")
    st = localai.pull_status()
    check("when one ends the next starts, and how the one before ended is kept",
          len(started) == 2 and st["model"] == "org/N-GGUF:Q4_K_M" and st["active"] and st["queue"] == []
          and (st["last"] or {}).get("asked") == "org/M-GGUF:Q4_K_M", str(st))
    files[:] = [{"name": "V-Q4_K_M.gguf", "size": 2 * 10**9}, {"name": "mmproj-V-BF16.gguf", "size": 9 * 10**8},
                {"name": "mmproj-V-F16.gguf", "size": 8 * 10**8}, {"name": "mmproj-V-F32.gguf", "size": 16 * 10**8}]
    plan = localai._plan_file("org/V-GGUF:Q4_K_M", "http://127.0.0.1:8080/v1")
    check("a model that can see comes with its vision part, F16 first, counted in the size",
          plan["ok"] and plan["vision"]["name"] == "mmproj-V-F16.gguf" and plan["total"] == 2 * 10**9 + 8 * 10**8,
          str(plan))
finally:
    localfix.repo_files = localfix_repo_files
    localai.threading = threading
    shutil.disk_usage = real_disk_usage
    localai._queue.clear()
    localai._set(active=False)

print("\n== the download, through a line that drops ==")
DATA = os.urandom(3 * 1024 * 1024 + 123)
seen = {"ranges": [], "mode": "drop-once", "hits": 0}


class Hf(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        seen["hits"] += 1
        rng = self.headers.get("range")
        seen["ranges"].append(rng)
        mode = seen["mode"]
        if mode == "missing":
            self.send_error(404)
            return
        if mode == "gated":
            self.send_error(401)
            return
        start = int(rng.split("=")[1].split("-")[0]) if rng and mode != "ignore-range" else 0
        body = DATA[start:]
        self.send_response(206 if start else 200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if mode == "always-drop" or (mode == "drop-once" and seen["hits"] == 1):
            # A third of it (nothing at all, when it keeps dropping), then the line goes dead.
            if mode == "drop-once":
                self.wfile.write(body[: len(body) // 3])
                self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hf)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/m.gguf"
# No waiting between tries here: the waits are real elsewhere.
localai.time = types.SimpleNamespace(time=time.time, sleep=lambda s: None)
quiet = types.SimpleNamespace(append=lambda *a, **k: None)


def fetch(part, expected=len(DATA)):
    localai._set(active=True, cancel=False, error="", status="starting", done=0, total=0)
    try:
        localai._fetch_resuming(URL, part, expected, "m", quiet)
        return None
    except Exception as e:
        return e
    finally:
        localai._set(active=False)


part = tmp / "m.gguf.part"
err = fetch(part)
check("a dropped line is picked up where it stopped, not started over",
      err is None and part.read_bytes() == DATA and seen["ranges"][0] is None
      and (seen["ranges"][1] or "").startswith("bytes=") and seen["ranges"][1] != "bytes=0-", f"{err} {seen['ranges']}")
st = localai.pull_status()
check("and the progress says the whole of it", st["done"] == len(DATA) and st["percent"] == 100, str(st))

part.write_bytes(DATA[:1000])
seen.update(ranges=[], mode="ignore-range", hits=0)
err = fetch(part)
check("what an earlier try left is carried on from", seen["ranges"][0] == "bytes=1000-", str(seen["ranges"]))
check("and a server that sends it all again instead is written over, not added to",
      err is None and part.read_bytes() == DATA, str(err))

part.write_bytes(DATA[:500] + b"x" * len(DATA))
seen.update(ranges=[], mode="drop-once", hits=0)
err = fetch(part)
check("a leftover bigger than the file is thrown away first", err is None and part.read_bytes() == DATA
      and seen["ranges"][0] is None, f"{err} {seen['ranges']}")

part.write_bytes(DATA[:1000])
seen.update(ranges=[], mode="always-drop", hits=0)
err = fetch(part)
check("a line that keeps dropping with nothing coming down gives up after a few tries",
      err is not None and seen["hits"] == localai._FETCH_TRIES + 1, f"{err} hits={seen['hits']}")
check("and keeps what came down before, for next time", part.exists() and part.read_bytes() == DATA[:1000])

part.unlink()
seen.update(ranges=[], mode="missing", hits=0)
err = fetch(part)
check("a file that is not there is not asked for again and again",
      isinstance(err, urllib.error.HTTPError) and seen["hits"] == 1, f"{err} hits={seen['hits']}")
check("and says so in words", localai._net_reason(err) == "Hugging Face doesn't have that file.", localai._net_reason(err))
seen.update(mode="gated", hits=0)
err = fetch(part)
check("a gated one says it needs signing in", "gated" in localai._net_reason(err) and seen["hits"] == 1)
srv.shutdown()
localai.time = real["time"]

print("\n== failures in words ==")
reset = urllib.error.URLError(ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host"))
check("a dropped connection", localai._net_reason(reset).startswith("The connection to Hugging Face kept dropping"),
      localai._net_reason(reset))
check("a timeout", "stopped answering" in localai._net_reason(urllib.error.URLError(socket.timeout("timed out"))))
check("no internet", "online" in localai._net_reason(urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))))
check("none of them the raw error", "WinError" not in localai._net_reason(reset))

print("\n== removing one ==")
restarted = []
localai._restart_llama = lambda base: restarted.append(base)
(tmp / "Foo-Q4_K_M.gguf").write_bytes(b"GGUF")
r = localai.delete_file_model("Foo-Q4_K_M", "http://127.0.0.1:8080/v1")
deadline = time.time() + 3
while time.time() < deadline and not restarted:
    time.sleep(0.02)
check("by the name llama.cpp lists it under, the file goes", r["ok"] and not (tmp / "Foo-Q4_K_M.gguf").exists(), str(r))
check("and llama.cpp is started again without it", restarted == ["http://127.0.0.1:8080/v1"], str(restarted))
check("a name that is no file there is not removed",
      not localai.delete_file_model("../../Windows/x", "http://127.0.0.1:8080/v1")["ok"])

print("\n== starting with the app ==")
calls, saved = [], []
localai.start_server = lambda sid, base, wait=25.0: calls.append((sid, base)) or {"ok": True}
localai._save_base_url = lambda base: saved.append(base)
OLLAMA = "http://127.0.0.1:11434/v1"
groq_only = lambda base: {"bot": {"local": {"base_url": base}}}  # noqa: E731
replies_here = {"bot": {"local": {"enabled": True, "model": "qwen", "base_url": OLLAMA}}}

localai.installed = lambda sid: r"C:\x\llama.exe" if sid == "llamacpp" else ""
localai.autostart(groq_only(OLLAMA))
check("left at Ollama's address with Ollama not installed, the app moves to llama.cpp and starts it",
      calls == [("llamacpp", "http://127.0.0.1:8080/v1")] and saved == ["http://127.0.0.1:8080/v1"], f"{calls} {saved}")
calls.clear(), saved.clear()
localai.autostart(groq_only("http://127.0.0.1:8080/v1"))
check("llama.cpp picked: started, even before a job runs on it", calls == [("llamacpp", "http://127.0.0.1:8080/v1")]
      and not saved, str(calls))
calls.clear()
localai.autostart(groq_only("http://192.168.1.20:11434/v1"))
check("a server somewhere else on the network is not touched", not calls and not saved, f"{calls} {saved}")
localai.autostart({"bot": {"local": {"base_url": OLLAMA, "autostart": False}}})
check("nor anything when it is switched off", not calls and not saved)

localai.installed = lambda sid: r"C:\x\ollama.exe" if sid in ("ollama", "llamacpp") else ""
localai.autostart(groq_only(OLLAMA))
check("Ollama installed and nothing running on it: left alone, as before", not calls and not saved, str(calls))
localai.autostart(replies_here)
check("with replies on it, started", calls == [("ollama", OLLAMA)] and not saved, str(calls))
calls.clear()

localai.installed = lambda sid: r"C:\x\Jan.exe" if sid == "jan" else ""
localai.autostart(groq_only(OLLAMA))
check("an app (Jan) is never moved to or opened unasked", not calls and not saved, f"{calls} {saved}")
localai.autostart(groq_only("http://127.0.0.1:1337/v1"))
check("but Jan picked is opened with the app, like any server it can start", calls == [("jan", "http://127.0.0.1:1337/v1")],
      str(calls))
calls.clear()
for k, v in real.items():
    setattr(localai, k, v)

print("\n== the routes ==")
local_routes = (ROOT / "app" / "web" / "routes" / "local_routes.py").read_text(encoding="utf-8")
check("the status says how this server gets its models", '"pull_kind": pull_kind' in local_routes)
check("a download goes to whoever can take it", "localai.pull_kind, base" in local_routes
      and "localai.start_pull, name, base" in local_routes)
check("a removal of a file model goes to the folder, and the settings let go of it",
      "localai.delete_file_model, name, base" in local_routes and local_routes.count("localfix.drop, name") == 2)
src = (ROOT / "app" / "utils" / "localai.py").read_text(encoding="utf-8")
check("the file's name is what it is called once in, as llama.cpp lists it", "percent=100, done=grand, model=stem)" in src)
check("llama.cpp is started again on the new file", "_restart_llama(job[\"base_url\"])\n        _set(status=\"ready\")" in src)
check("a model that can see gets a folder of its own, its vision part beside it (llama.cpp pairs them only so)",
      "home = folder / stem if vision else folder" in src)
check("where each came from is written down, to find something smaller by the same maker later",
      "_remember_source(stem, repo, pick, vision)" in src and "def source_of(model: str)" in src)
check("the models folder is not committed", "/models/" in (ROOT / ".gitignore").read_text(encoding="utf-8"))

print("\n== the panel ==")
ui = read("lib/components/LocalAI.svelte")
check("the download box takes a Hugging Face repo for llama.cpp", 'pullKind === "file"' in ui and "SUGGESTED_FILES" in ui)
check("starting a server while the saved address has nothing there moves the app to it, saved",
      'await api.configField("bot.local.base_url", s.base_url);' in ui and "(!baseUrl || !reachable) && s.base_url !== stored" in ui)
check("the setting says it starts the server above, any of them", "The server above starts when the app opens." in ui)
check("the models are asked again while it is open, so ones removed elsewhere go",
      "visiblePoll(() => refreshModels(), 10_000)" in ui)
check("every other server says where its models come from, in the download box's place",
      all(k["get"] for k in localai.KNOWN_SERVERS if k["id"] not in ("ollama", "llamacpp"))
      and not any(k["get"] for k in localai.KNOWN_SERVERS if k["id"] in ("ollama", "llamacpp"))
      and "{:else if hero?.get}" in ui and "{@render said(hero.get)}" in ui)
system = (ROOT / "app" / "web" / "routes" / "system_routes.py").read_text(encoding="utf-8")
check("the checklist says any server it can start is started with the app", '"autostart"' not in system
      and "whenever the app opens." in system)

import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
