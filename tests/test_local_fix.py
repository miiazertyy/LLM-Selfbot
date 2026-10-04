"""A local model that will not load, fixed by the app.

Seen on a real setup: every reply answered "llama-server process has terminated: exit status 1: error loading
model: check_tensor_dims: tensor 'output.weight' has wrong shape; expected 5120, 248320, got 5120, 32768, 1, 1",
and the log filled with it. Ollama had been asked for a HuggingFace repo by its name alone, HuggingFace handed it
the repo's first file for "latest", and that was a 1.9B draft model for speculative decoding, not the 27B model.

Checked here, with a fake Ollama and no network: the failure is recognised and said in words; a draft or a vision
part is told from a model by what the file says about itself; the repo's own files are told apart (the draft, the
vision part and sizes HuggingFace will not hand over by name are left out); the size picked fits the computer, and
nothing is picked when nothing fits, saying why; a download by name alone gets the model itself; the repair
downloads it, moves every setting over and removes the draft; and a reply leaves the model alone for a while
instead of failing on it at every message.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-localfix-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
DRAFT = "hf.co/HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF:latest"
REPO = "HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF"
cfg = yaml.safe_load((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"))
cfg["bot"]["models"] = {"replies": [{"provider": "local", "model": DRAFT}, {"provider": "groq", "model": "x"}],
                        "vision": {"provider": "local", "model": DRAFT}}
cfg["bot"]["local"] = {"enabled": True, "base_url": "http://127.0.0.1:1/v1", "model": DRAFT, "vision_model": DRAFT}
(TMP / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import localai, localfix as lf  # noqa: E402

GB = lf.GB
ERROR = ("Error code: 500 - {'error': {'message': \"llama-server process has terminated: exit status 1: error loading "
         "model: check_tensor_dims: tensor 'output.weight' has wrong shape; expected 5120, 248320, got 5120, 32768, "
         "1, 1\"}}")

print("== the failure, in words ==")
check("recognised as a model that will not load", lf.load_failure(ERROR))
check("and said plainly", lf.reason(ERROR) == "the file is not a whole model, or not one this server can read")
check("a busy or missing server is not that", not lf.load_failure("Connection refused")
      and not lf.load_failure("Error code: 429 rate limited"))
check("an Ollama too old for the model is told apart",
      "version of Ollama" in lf.reason("error loading model: unknown model architecture: 'qwen9'"))

print("\n== what the file is ==")
SHOW = {
    DRAFT: {"model_info": {"general.parameter_count": 1863907840, "general.size_label": "27B",
                           "general.basename": "Qwen3.8-27B", "general.tags": ["mtp", "speculative-decoding"],
                           "general.description": "Optional FastMTP draft for the Qwen3.8-27B Aggressive variant."},
            "details": {"parameter_size": "1.86B"}},
    "hf.co/x/model:IQ4_XS": {"model_info": {"general.parameter_count": 27_100_000_000, "general.size_label": "27B",
                                            "general.tags": ["mtp", "speculative-decoding"]},
                             "details": {"parameter_size": "27.1B"}},
    "hf.co/x/vision:latest": {"model_info": {"general.type": "mmproj", "general.architecture": "clip"}, "details": {}},
}
shown = []


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        shown.append(body.get("model"))
        data = SHOW.get(body.get("model"))
        out = json.dumps(data or {"error": "not found"}).encode()
        self.send_response(200 if data else 404)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}/v1"

d = lf.inspect(DRAFT, BASE)
check("a 1.9B file under a 27B name is a draft, not the model", d and d["helper"] and d["kind"] == "draft", str(d))
m = lf.inspect("hf.co/x/model:IQ4_XS", BASE)
check("the model itself is not, though the repo tags both 'mtp'", m and not m["helper"], str(m))
v = lf.inspect("hf.co/x/vision:latest", BASE)
check("the vision part is told apart", v and v["helper"] and v["kind"] == "vision", str(v))
check("not Ollama, or no such model: nothing to say", lf.inspect("nope", BASE) is None)
check("the repo of a HuggingFace name", lf.hf_repo(DRAFT) == (REPO, "latest") and lf.hf_repo("hf.co/a/b") == ("a/b", "latest")
      and lf.hf_repo("llama3.1:8b") == ("", ""))

print("\n== the repo's own files ==")
FILES = [{"name": n, "size": s} for n, s in [
    (".gitattributes", 2619), ("README.md", 16474),
    ("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-FastMTP-32K.gguf", 903453952),
    ("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-IQ2_M.gguf", 10319906944),
    ("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-IQ3_M.gguf", 12789303424),
    ("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-IQ3_XS.gguf", 12175558784),
    ("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf", 15705860224),
    ("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf", 17923393664),
    ("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf", 31457990784),
    ("mmproj-Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-BF16.gguf", 931146624),
    ("Other-Q4_K_M-00001-of-00002.gguf", 9_000_000_000),
]]
tags = sorted(f["tag"] for f in lf.model_files(FILES))
check("the model's sizes, and not the draft, the vision part, a split part, or names HuggingFace refuses",
      tags == ["IQ2_M", "IQ3_M", "IQ3_XS", "IQ4_XS"], str(tags))

THIS_PC = {"ram": int(15.8 * GB), "vram": 4 * GB, "free": int(4.3 * GB)}
picks, why = lf.choices(FILES, THIS_PC)
check("on a small disk nothing is picked, and it says how much is needed and free",
      picks == [] and "9.6 GB" in why and "4.3 GB free" in why, why)
picks, why = lf.choices(FILES, {"ram": 32 * GB, "vram": 12 * GB, "free": 200 * GB})
check("with room, the 4-bit size first, then the biggest that fits",
      [p["tag"] for p in picks] == ["IQ4_XS", "IQ3_M", "IQ3_XS", "IQ2_M"], str([p["tag"] for p in picks]))
mach = {"ram": 26 * GB, "vram": 0, "free": 200 * GB}
picks, _ = lf.choices(FILES, mach)
check("what memory cannot run is not picked: the file and the room for the conversation fit in about half the RAM",
      [p["tag"] for p in picks] == ["IQ2_M"] and all(lf.need(p["size"]) <= lf.budget(mach) for p in picks),
      str([p["tag"] for p in picks]))
picks, why = lf.choices(FILES, {"ram": int(15.8 * GB), "vram": 4 * GB, "free": 200 * GB})
check("a 27B on a 16 GB computer with a 4 GB card: no size of it runs at speed, and it says why", picks == []
      and "needs about" in why and "this computer can give it" in why, why)
check("a 14.4 GB model on that computer is too big (it paged to the disk, and every reply gave up)",
      not lf.fits_memory(int(14.38 * GB), {"ram": int(15.8 * GB), "vram": 4 * GB})
      and lf.fits_memory(int(5.6 * GB), {"ram": int(15.8 * GB), "vram": 4 * GB}))

print("\n== a download by name alone ==")
real = {k: getattr(lf, k) for k in ("repo_files", "_hf_get", "machine", "resolves")}
MANIFESTS = {"latest": 903453952}
lf.repo_files = lambda repo: FILES
lf._hf_get = lambda url, **k: {"layers": [{"mediaType": "application/vnd.ollama.image.model",
                                           "size": MANIFESTS[url.rsplit("/", 1)[1]]}]}
lf.resolves = lambda repo, tag, size: True
lf.machine = lambda: {"ram": 32 * GB, "vram": 12 * GB, "free": 200 * GB}
check("a repo whose default is the draft is asked for in the model's own size",
      lf.for_pull(f"hf.co/{REPO}") == (f"hf.co/{REPO}:IQ4_XS", ""), str(lf.for_pull(f"hf.co/{REPO}")))
MANIFESTS["latest"] = 15705860224
check("one whose default is the model is left as typed", lf.for_pull(f"hf.co/{REPO}") == (f"hf.co/{REPO}", ""))
check("so is a size asked for by name, and an Ollama name", lf.for_pull(f"hf.co/{REPO}:IQ2_M")[0].endswith(":IQ2_M")
      and lf.for_pull("llama3.1:8b") == ("llama3.1:8b", ""))
MANIFESTS["latest"] = 903453952
lf.machine = lambda: THIS_PC
name, why = lf.for_pull(f"hf.co/{REPO}")
check("and where nothing fits, nothing is downloaded, and it says why", name == "" and "4.3 GB free" in why, why)
pulled = localai.start_pull(f"hf.co/{REPO}", BASE)
check("the panel's download refuses it with that reason", not pulled["ok"] and "does not fit" in pulled["reason"],
      str(pulled))

print("\n== the repair ==")
lf.machine = lambda: {"ram": 32 * GB, "vram": 12 * GB, "free": 200 * GB}
NEW = f"hf.co/{REPO}:IQ4_XS"
SHOW[NEW] = SHOW["hf.co/x/model:IQ4_XS"]
asked, removed = [], []
state = {"active": False, "error": "", "cancel": False}
real_local = {k: getattr(localai, k) for k in ("start_pull", "pull_status", "ollama_models", "delete_model")}


def fake_pull(name, base, as_typed=False):
    asked.append((name, as_typed))
    # Done at once: how it ended, as the downloader keeps it (queue moving on or not).
    state["last"] = {"asked": name, "model": name, "error": "", "cancelled": False, "at": time.time()}
    return {"ok": True, "model": name}


localai.start_pull = fake_pull
localai.pull_status = lambda: dict(state)
localai.ollama_models = lambda base, timeout=1.5: {DRAFT: {}}
localai.delete_model = lambda model, base: removed.append(model) or {"ok": True}
from app.web.logbus import bus  # noqa: E402
before = len(bus.buffer)
out = lf.repair(DRAFT, BASE, ERROR)
check("the model itself is downloaded, in the size picked, as worked out", asked == [(NEW, True)], str(asked))
check("and it says it is fixed, and with what", out["state"] == "fixed" and out["to"] == NEW, str(out))
saved = yaml.safe_load((TMP / "config" / "config.yaml").read_text(encoding="utf-8"))["bot"]
check("every setting that named the draft names the model now",
      saved["models"]["replies"][0]["model"] == NEW and saved["models"]["vision"]["model"] == NEW
      and saved["local"]["model"] == NEW and saved["local"]["vision_model"] == NEW, json.dumps(saved["models"]))
check("and nothing else was touched", saved["models"]["replies"][1] == {"provider": "groq", "model": "x"})
check("the draft is removed: of no use on its own", removed == [DRAFT], str(removed))
said = [e["text"] for e in list(bus.buffer)[before:]]
check("the log says what was wrong and what was done, in words",
      any("draft model" in t and "Downloading the model itself (IQ4_XS" in t for t in said)
      and any(t.startswith("Fixed:") for t in said), str(said))

lf.machine = lambda: THIS_PC
asked.clear()
out = lf.repair(DRAFT, BASE, ERROR)
check("with no room for it: nothing downloaded, and stuck with why", asked == [] and out["state"] == "stuck"
      and "4.3 GB free" in out["why"], str(out))
out = lf.repair("hf.co/x/model:IQ4_XS", BASE, "error loading model: unknown model architecture: 'qwen9'")
check("a whole model this Ollama cannot read: it says to update Ollama", out["state"] == "stuck"
      and "version of Ollama" in out["why"], str(out))
for k, f in real.items():
    setattr(lf, k, f)
for k, f in real_local.items():
    setattr(localai, k, f)

print("\n== a reply leaves it alone ==")
from app.utils import ai  # noqa: E402
calls = []


class Boom(Exception):
    status_code = 500


class Client:
    class chat:
        class completions:
            @staticmethod
            async def create(**k):
                calls.append(k["model"])
                raise Boom(ERROR)


ai._initialised = True
real_ai = (ai._openai_client, ai.load_config)
ai._openai_client = lambda pid, config: Client()
ai.load_config = lambda: {"bot": {"models": {"replies": [{"provider": "local", "model": "broken"}]},
                                  "local": {"base_url": BASE}}}
logged = []
real_log = ai.log_system
ai.log_system = logged.append


async def twice():
    errors = []
    for _ in range(2):
        try:
            await ai._create_completion_inner([{"role": "user", "content": "hi"}], 50)
        except Exception as e:
            errors.append(e)
    return errors


errors = asyncio.run(twice())
check("the first reply finds it will not load, and says so in words",
      isinstance(errors[0], ai.ModelWontLoad) and "will not load" in str(errors[0]) and "{" not in str(errors[0]),
      str(errors[0]))
check("the next one does not ask it again", calls == ["broken"] and isinstance(errors[1], ai.ModelWontLoad), str(calls))
check("said once in the log, not on every message", sum("will not load" in t for t in logged) == 1, str(logged))
marker = json.loads((TMP / "cache" / "local_wont_load.json").read_text(encoding="utf-8"))
check("and handed to the panel to look into", marker["model"] == "broken" and "check_tensor_dims" in marker["error"])
ai._openai_client, ai.load_config = real_ai
ai.log_system = real_log

print("\n== the panel ==")
src = (ROOT / "app" / "web" / "server.py").read_text(encoding="utf-8")
check("watched from start, for as long as the app runs", "localfix.watch(load_config)" in src)
routes = (ROOT / "app" / "web" / "routes" / "local_routes.py").read_text(encoding="utf-8")
check("its state is in the local status", '"fix": localfix.status()' in routes)
page = (ROOT / "webui" / "src" / "lib" / "components" / "LocalAI.svelte").read_text(encoding="utf-8")
check("and said on the This computer page", 'class="lc-fix"' in page and "will not load: {fix.why}" in page)
models = (ROOT / "webui" / "src" / "lib" / "components" / "ModelsPanel.svelte").read_text(encoding="utf-8")
check("and on its row under Models", 'text: localFix.state === "fixing"' in models and 'title={st.why ?? ""}' in models)

server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
