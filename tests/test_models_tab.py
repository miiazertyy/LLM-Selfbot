"""The Models tab: a model removed stays removed, restart means every local server, where a model is does not depend on
the server answering, the folder opens with nothing in it, and a model file can be brought in by hand."""
import os
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.utils import localai, localfix  # noqa: E402
from app.web.routes import local_routes  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def gguf(meta: dict) -> bytes:
    def text(s: str) -> bytes:
        b = s.encode()
        return struct.pack("<Q", len(b)) + b

    out = b"GGUF" + struct.pack("<IQQ", 3, 0, len(meta))
    for key, value in meta.items():
        out += text(key)
        out += struct.pack("<II", 4, value) if isinstance(value, int) else struct.pack("<I", 8) + text(value)
    return out


LLAMA = "http://127.0.0.1:8080/v1"
OLLAMA = "http://127.0.0.1:11434/v1"
folder = localai.app_models_dir()

print("\n== a model just removed stays off the list ==")
localai._note_removed(LLAMA, "Foo")
check("off the list of the server it was removed from", localai._without_removed(LLAMA, ["Bar", "Foo"]) == ["Bar"])
check("and it is still remembered", (localai.server_root(LLAMA), "Foo") in localai._removed)
check("another server's list changes nothing", localai._without_removed(OLLAMA, ["Foo"]) == ["Foo"])
check("nor forgets it", (localai.server_root(LLAMA), "Foo") in localai._removed)
localai._without_removed(LLAMA, ["Bar"])
check("forgotten once its server has let go of it", not localai._removed)
localai._note_removed(LLAMA, "Foo")
check("back on the list if that server has it after that",
      localai._without_removed(LLAMA, ["Bar"]) == ["Bar"] and localai._without_removed(LLAMA, ["Bar", "Foo"]) == ["Bar", "Foo"])
localai._removed[(localai.server_root(LLAMA), "Foo")] = time.time() - 121
check("and after two minutes whatever it says", localai._without_removed(LLAMA, ["Foo"]) == ["Foo"])

print("\n== removing one says a restart is under way before it returns ==")
gate = threading.Event()
real_restart = localai.restart_server
localai.restart_server = lambda sid, base: gate.wait(5) and {"ok": True}
(folder / "Soon-Q4.gguf").write_bytes(b"GGUF")
r = localai.delete_file_model("Soon-Q4", LLAMA)
check("the file is gone", r["ok"] and not (folder / "Soon-Q4.gguf").exists())
check("and the very next look knows", localai.restarting() is True)
check("and does not list it, even while the server still does",
      localai._without_removed(LLAMA, ["Other", "Soon-Q4"]) == ["Other"])
gate.set()
deadline = time.time() + 3
while time.time() < deadline and localai.restarting():
    time.sleep(0.02)
check("over when it is over", localai.restarting() is False)
localai.restart_server = real_restart
localai._removed.clear()

print("\n== restart means every local server ==")
real = {k: getattr(localai, k) for k in ("detect", "start_server", "installed", "probe", "_running_serves", "_end_process")}
def server(sid, name, **kw):
    return {"id": sid, "name": name, "running": False, "locked": False, "can_start": True,
            "base_url": f"http://127.0.0.1:{kw.pop('port', 1234)}/v1", **kw}
asked = []
localai.detect = lambda *a, **k: [server("ollama", "Ollama", port=11434, running=True), server("jan", "Jan", port=1337, running=True),
                                  server("vllm", "vLLM", port=8000, running=True), server("llamacpp", "llama.cpp server", port=8080),
                                  server("lmstudio", "LM Studio", port=1235)]
localai.restart_server = lambda sid, base: asked.append(sid) or (
    {"ok": False, "manual": True, "reason": "vLLM runs with settings only you know, so restart it yourself."} if sid == "vllm"
    else {"ok": True})
r = localai.restart_all(LLAMA)
check("each one running, and the one in use though it is not", asked == ["ollama", "jan", "vllm", "llamacpp"], str(asked))
check("not one that is only installed", "lmstudio" not in asked)
check("named in what it says", "Ollama" in r["said"] and "Jan" in r["said"] and "llama.cpp server" in r["said"], r["said"])
check("with why for the one it could not", "restart it yourself" in r["said"], r["said"])
check("and not called all right when one was left", r["ok"] is False)
localai.detect = lambda *a, **k: [server("ollama", "Ollama", port=11434, can_start=False)]
r = localai.restart_all(LLAMA)
check("nothing to restart is said, not an error", r["ok"] is False and not r["results"] and "No local server" in r["said"], str(r))
localai.restart_server = real_restart

print("\n== a server the app did not start, or cannot ==")
localai.installed = lambda sid: ""
r = localai.restart_server("ollama", OLLAMA)
check("one running from nowhere the app knows is left alone", r["manual"] and "yourself" in r["reason"], str(r))
r = localai.restart_server("vllm", "http://127.0.0.1:8000/v1")
check("one with no way to start it too", r["manual"] and "yourself" in r["reason"], str(r))

print("\n== stopping: an app is asked first ==")
ends = []
quiet = {"at": 0}
localai.installed = lambda sid: "C:/apps/jan.exe"
localai._running_serves = lambda sid: [42]
localai._end_process = lambda pid, force=True: ends.append((pid, force)) or quiet.update(at=1)
localai.probe = lambda url, timeout=0.8, **k: {"ok": not quiet["at"], "models": [], "locked": False}
jan = next(s for s in localai.KNOWN_SERVERS if s["start"] == "app")
localai._stop_server(jan["id"], localai._base(jan))
check("its window asked to close, not its process killed", ends == [(42, False)], str(ends))
ends.clear()
quiet["at"] = 0
localai._stop_server("ollama", OLLAMA)
check("a server with no window is simply stopped", ends == [(42, True)], str(ends))
ends.clear()
quiet["at"] = 0
localai._end_process = lambda pid, force=True: ends.append((pid, force)) or (force and quiet.update(at=1))
real_quiet = localai._wait_until_quiet
localai._wait_until_quiet = lambda base, seconds: bool(quiet["at"])
localai._stop_server(jan["id"], localai._base(jan))
check("one that will not close is told", ends == [(42, False), (42, True)], str(ends))
localai._wait_until_quiet = real_quiet
for k, v in real.items():
    setattr(localai, k, v)

print("\n== where a model is ==")
(folder / "Loose-Q4_K_M.gguf").write_bytes(b"GGUF")
own = folder / "Vision-Model"
own.mkdir()
(own / "mmproj-Vision.gguf").write_bytes(b"GGUF" * 4)
(own / "Vision-Model-Q4.gguf").write_bytes(b"GGUF" * 2)
localai.probe = lambda url, timeout=0.8, **k: {"ok": False, "models": [], "locked": False}
check("a loose file", localai.file_model_path("Loose-Q4_K_M", "") == str(folder / "Loose-Q4_K_M.gguf"))
check("a folder of its own, not its vision part", localai.file_model_path("Vision-Model", "") == str(own / "Vision-Model-Q4.gguf"))
check("by a name with its maker in it too",
      localai.file_model_path("someone/Loose-Q4_K_M", "") == str(folder / "Loose-Q4_K_M.gguf"))
check("llama.cpp's models are looked for in the app's folder (they were looked for in Hugging Face's)",
      localai.model_file("Loose-Q4_K_M", LLAMA) == str(folder / "Loose-Q4_K_M.gguf"))
check("nothing is found by walking out of it", localai.file_model_path("../../Windows/notepad", "") == "")
localai.probe = real["probe"]

print("\n== the folder, with nothing in it ==")
check("llama.cpp's is the app's", localai.models_folder(LLAMA) == str(folder))
check("no address at all, the app's", localai.models_folder("") == str(folder))
real_ollama = os.environ.get("OLLAMA_MODELS")
own_ollama = Path(_tmp.name) / "ollama-models"
own_ollama.mkdir()
os.environ["OLLAMA_MODELS"] = str(own_ollama)
check("Ollama's own, where it says", localai.models_folder(OLLAMA) == str(own_ollama))
own_ollama.rmdir()
os.environ.pop("OLLAMA_MODELS")
if real_ollama:
    os.environ["OLLAMA_MODELS"] = real_ollama

print("\n== a file brought in ==")
check("a .gguf is fine", localai.import_problem("Model-Q4.gguf", 1000, LLAMA) == "")
for bad in ("notes.txt", "", ".hidden.gguf", "../../evil.gguf", "a/b.gguf", "c:\\x.gguf"):
    check(f"{bad!r} is not", "not a model file" in localai.import_problem(bad, 1000, LLAMA))
check("no room is said before anything is copied", "Not enough room" in localai.import_problem("Huge.gguf", 10 ** 15, LLAMA))
check("nor one already here", "already in the models folder" in localai.import_problem("Loose-Q4_K_M.gguf", 1000, LLAMA))

restarted = []
real_soon = localai._restart_llama_soon
localai._restart_llama_soon = lambda base: restarted.append(base)
localai.installed = lambda sid: "C:/llama.exe" if sid == "llamacpp" else ""


def part(content: bytes) -> Path:
    p = folder / f".adding-{time.time_ns()}.part"
    p.write_bytes(content)
    return p


model = gguf({"general.architecture": "llama", "general.name": "New"})
p = part(model)
r = localai.finish_import(p, "New-Q4.gguf", LLAMA)
check("a model goes in the folder, under its own name", r["ok"] and (folder / "New-Q4.gguf").read_bytes() == model and r["model"] == "New-Q4", str(r))
check("nothing left of the copy", not p.exists())
check("and llama.cpp is started again to see it", restarted == [LLAMA], str(restarted))

for name, meta, words in (("a vision part", {"general.type": "mmproj"}, "the vision part"),
                          ("the old mark of one", {"general.architecture": "clip"}, "the vision part"),
                          ("a LoRA", {"general.type": "adapter"}, "LoRA"),
                          ("a draft", {"general.architecture": "llama", "general.description": "A draft model"}, "draft")):
    p = part(gguf(meta))
    r = localai.finish_import(p, "Part.gguf", LLAMA)
    check(f"{name} is refused, saying what it is", not r["ok"] and words in r["reason"] and not (folder / "Part.gguf").exists(), str(r))
    check("and is not left behind", not p.exists())

p = part(b"PK\x03\x04 not a model at all")
r = localai.finish_import(p, "Fake.gguf", LLAMA)
check("something only named .gguf is refused", not r["ok"] and "not a model file" in r["reason"] and not p.exists(), str(r))

p = part(gguf({"general.architecture": "llama", "split.count": 2}))
r = localai.finish_import(p, "Big-Q4-00001-of-00002.gguf", LLAMA)
check("one part of a split model goes in a folder named for the model",
      r["ok"] and r["model"] == "Big-Q4" and (folder / "Big-Q4" / "Big-Q4-00001-of-00002.gguf").exists(), str(r))
p = part(gguf({"general.architecture": "llama", "split.count": 2}))
r = localai.finish_import(p, "Big-Q4-00002-of-00002.gguf", LLAMA)
check("and the rest of it beside it", r["ok"] and (folder / "Big-Q4" / "Big-Q4-00002-of-00002.gguf").exists(), str(r))

print("\n== to Ollama, which keeps its own ==")
ran = []


class Done:
    def __init__(self, code=0, err=""):
        self.returncode, self.stderr, self.stdout = code, err, ""


real_run = localai.subprocess.run
localai.installed = lambda sid: "C:/ollama.exe" if sid == "ollama" else ""


def fake_create(argv, **kw):
    ran.append(argv)
    files = sorted(x.name for x in Path(kw["cwd"]).iterdir())
    ran.append(files)
    ran.append((Path(kw["cwd"]) / argv[-1]).read_text())
    return Done()


localai.subprocess.run = fake_create
p = part(model)
r = localai.finish_import(p, "My Model Q4.gguf", OLLAMA)
check("it is asked to make one from the file", r["ok"] and ran[0][1:3] == ["create", "my-model-q4"], str(ran))
check("by a path beside the Modelfile, with a space safe", ran[2].startswith("FROM ./") and ran[2].strip().endswith(".gguf"), str(ran[2]))
check("its copy, and the Modelfile, are gone after", not list(folder.glob(".adding-*")), str(list(folder.glob(".adding-*"))))
localai.subprocess.run = lambda argv, **kw: Done(1, "pulling\nError: unsupported architecture")
p = part(model)
r = localai.finish_import(p, "Bad.gguf", OLLAMA)
check("what it says when it will not", not r["ok"] and "unsupported architecture" in r["reason"], str(r))
check("and nothing left then either", not list(folder.glob(".adding-*")))
localai.subprocess.run = real_run
localai.installed = real["installed"]
localai._restart_llama_soon = real_soon

print("\n== the routes ==")
app = FastAPI()
app.include_router(local_routes.router)
client = TestClient(app)
shown = []
real_show = localai.show_in_folder
localai.show_in_folder = lambda path: shown.append(path)
real_settings = localai.settings
local_routes.load_config = lambda: {}
localai.settings = lambda cfg: {"base_url": LLAMA, "api_key": "", "autostart": True, "context_length": 16384, "enabled": False, "model": ""}
localai.probe = lambda url, timeout=0.8, api_key="", **k: {"ok": False, "models": [], "locked": False, "error": "down"}

r = client.post("/api/local/open-folder", json={"base_url": LLAMA})
check("the folder opens though there may be nothing in it", r.status_code == 200 and shown == [str(folder)], r.text)
shown.clear()
r = client.post("/api/local/reveal", json={"model": "Loose-Q4_K_M", "base_url": LLAMA})
check("a model is shown with its server down, as it is for a moment after every download",
      r.status_code == 200 and shown == [str(folder / "Loose-Q4_K_M.gguf")], r.text)
r = client.post("/api/local/reveal", json={"model": "Nothing-Like-It", "base_url": LLAMA})
check("one that does not exist is said", r.status_code == 404)

localai._restart_llama_soon = lambda base: None
localai.installed = lambda sid: "C:/llama.exe" if sid == "llamacpp" else ""
r = client.post("/api/local/import?name=Sent-Q4.gguf", content=model, headers={"content-type": "application/octet-stream"})
check("a file sent as the body lands", r.status_code == 200 and (folder / "Sent-Q4.gguf").read_bytes() == model, r.text)
big = gguf({"general.architecture": "llama"}) + b"\0" * (9 * 1024 * 1024)
r = client.post("/api/local/import?name=Sent-Big.gguf", content=big)
check("all of one bigger than the write-out size", r.status_code == 200 and (folder / "Sent-Big.gguf").stat().st_size == len(big), r.text)
r = client.post("/api/local/import?name=Sent-Q4.gguf", content=model)
check("the same one again is refused", r.status_code == 400 and "already" in r.json()["detail"], r.text)
r = client.post("/api/local/import?name=notes.txt", content=b"hello")
check("something else is refused", r.status_code == 400 and "not a model file" in r.json()["detail"], r.text)
r = client.post("/api/local/import?name=Liar.gguf", content=b"hello")
check("and so is a file that only says it is one", r.status_code == 400 and not (folder / "Liar.gguf").exists(), r.text)
check("no half-copied file is ever left", not list(folder.glob(".adding-*")))

localai.show_in_folder = real_show
localai.settings = real_settings
for k, v in real.items():
    setattr(localai, k, v)
localai._restart_llama_soon = real_soon

print("\n== the panel ==")
src = (ROOT / "webui/src/lib/components/LocalAI.svelte").read_text(encoding="utf-8")
hero = (ROOT / "webui/src/lib/components/ModelsHero.svelte").read_text(encoding="utf-8")
api = (ROOT / "webui/src/lib/api.ts").read_text(encoding="utf-8")
check("a server being restarted keeps its list", "if (serverBack && !s.reachable) return;" in src)
check("and is looked at again until it is back", "setTimeout(refreshModels, 1500)" in src)
check("the card says Restarting", 'word: "Restarting"' in src)
check("a model removed stays off whatever an answer on its way says", "filter((m: string) => !gone.has(m))" in src)
check("and off the answer kept for next time", "statusRes.update(" in src)
check("the row says it is going", '<span class="lm-removing" role="status">Removing</span>' in src)
check("for long enough to read", "new Promise((done) => setTimeout(done, 600))" in src)
check("the button is about all of them", "Restart local servers" in src and "Restart Ollama" not in src)
check("and says what it did", "r?.said" in src)
check("the folder button is always there, not only beside a model", src.index("openFolder}") < src.index("{#if canPull}\n      <!-- A search of Hugging Face"))
check("a file can be dropped anywhere on the tab", "<svelte:window ondragenter={fileHeld}" in src)
check("only a file, not a row being dragged", 'types?.includes("Files")' in src)
check("or chosen", 'type="file" accept=".gguf"' in src)
check("it can be stopped", "stopAdding()" in src and "abort: () => xhr.abort()" in api)
check("sent from the disk as it goes, not read into memory", "xhr.send(file)" in api)
check("and every control heard", 'play("lift")' in src and 'play("drop")' in src and 'play("done")' in src)
check("the chips at the top change with it", 'resource("localStatus"' in hero and "api.localStatus().then" not in hero)

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
