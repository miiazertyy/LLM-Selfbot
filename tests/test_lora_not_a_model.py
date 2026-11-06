"""A LoRA downloaded as the model, and Try answering "This computer answered 500."

Seen on a real setup: "LessThanThreeAI/Qwen3.8-27B-Humanlike-Chat-GGUF" typed into This computer's download box.
Its every real size (14 GB and up) was too big for a 16 GB computer with a 4 GB card, so the app took the one file of
the repo that "fit": lora/Qwen3.8-27B-Humanlike-Chat-2.0-LoRA-r320-F16.gguf, 4.4 GB, a LoRA, an add-on that changes a
model it is put on and cannot answer on its own. llama.cpp's router answered every request for it with a 500, "model
name=... failed to load", which the app did not know as a load failure. So Try said "This computer answered 500.",
replies failed on it every message, and nothing was fixed: the app only knew how to ask Ollama what a file is.

Checked here, with a fake llama.cpp and Hugging Face, and GGUF headers written by hand (no network): the router's
words are a load failure, its "Failed to load image" is not; a GGUF header is read for what the file is (a LoRA, the
vision part, a draft, a model); a repo's LoRA is never picked as its model; a smaller copy of the very model by
someone else is found when its maker has no size that fits; the repair works for llama.cpp's files (said and offered
when nothing fits, the model itself fetched when it does); Try says what the file is.
"""
import json
import os
import struct
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-lora-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
STEM = "Qwen3.8-27B-Humanlike-Chat-2.0-LoRA-r320-F16"
REPO = "LessThanThreeAI/Qwen3.8-27B-Humanlike-Chat-GGUF"
cfg = yaml.safe_load((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"))
cfg["bot"]["models"] = {"replies": [{"provider": "local", "model": STEM}, {"provider": "groq", "model": "x"}]}
cfg["bot"]["local"] = {"enabled": True, "base_url": "http://127.0.0.1:1/v1", "model": STEM}
(TMP / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import localai, localfix as lf, providers  # noqa: E402

GB = lf.GB
ROUTER_SAID = f"model name={STEM} failed to load"


def gguf(path: Path, kv: dict, tensors: list) -> Path:
    """A GGUF header as llama.cpp writes one, without the tensors' data: `kv` values str, float, int or a list,
    `tensors` [(name, shape)]."""
    def s(text):
        b = text.encode()
        return struct.pack("<Q", len(b)) + b

    out = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(kv))
    for key, v in kv.items():
        out += s(key)
        if isinstance(v, str):
            out += struct.pack("<I", 8) + s(v)
        elif isinstance(v, float):
            out += struct.pack("<If", 6, v)
        elif isinstance(v, int):
            out += struct.pack("<IQ", 10, v)
        elif v and isinstance(v[0], str):
            out += struct.pack("<IIQ", 9, 8, len(v)) + b"".join(s(x) for x in v)
        else:
            out += struct.pack("<IIQ", 9, 5, len(v)) + struct.pack(f"<{len(v)}i", *v)
    for name, shape in tensors:
        out += s(name) + struct.pack("<I", len(shape)) + struct.pack(f"<{len(shape)}Q", *shape) + struct.pack("<IQ", 1, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


VOCAB = [f"tok{i}" for i in range(60000)]          # the tokenizer's lists are gone past, not kept


def model_header(path, label="27B", params=27_000_000_000, **extra):
    rows = params // 5120
    return gguf(path, {"general.architecture": "qwen35", "general.type": "model", "general.size_label": label,
                       "general.name": "Merged", "tokenizer.ggml.tokens": VOCAB,
                       "tokenizer.ggml.token_type": [1] * len(VOCAB), **extra},
                [("token_embd.weight", (5120, 248320)), ("blk.0.ffn_up.weight", (5120, rows - 248320))])


def lora_header(path):
    return gguf(path, {"general.architecture": "qwen35", "general.type": "adapter", "adapter.type": "lora",
                       "general.name": "R3 Combined", "adapter.lora.alpha": 320.0},
                [("blk.0.attn_q.weight.lora_a", (5120, 320)), ("blk.0.attn_q.weight.lora_b", (320, 6144))])


def mmproj_header(path):
    return gguf(path, {"general.architecture": "clip", "general.type": "mmproj", "general.size_label": "461M"},
                [("v.patch_embd.weight", (16, 16, 3, 1152))])


print("== the router's words ==")
check("llama.cpp's 'model name=... failed to load' is a model that will not load", lf.load_failure(ROUTER_SAID))
check("its 'Failed to load image' (a bad picture) is not", not lf.load_failure("Failed to load image or audio file"))
body = json.dumps({"error": {"code": 500, "message": ROUTER_SAID, "type": "server_error"}})
check("so Try says it would not load, not 'This computer answered 500.'",
      providers.http_error("local", 500, body)[0] == "It would not load on this computer.",
      str(providers.http_error("local", 500, body)))

print("\n== what a GGUF file says it is ==")
HEADS = TMP / "heads"
info = lf.gguf_info(lora_header(HEADS / "lora.gguf"))
check("a LoRA says so in its header", info and info["general.type"] == "adapter" and info["adapter.type"] == "lora"
      and info["general.parameter_count"] == 5120 * 320 + 320 * 6144, str(info))
t0 = time.perf_counter()
info = lf.gguf_info(model_header(HEADS / "model.gguf"))
took = time.perf_counter() - t0
check("a model: its type, its size, and its parameters counted from its tensors",
      info and info["general.type"] == "model" and info["general.size_label"] == "27B"
      and abs(info["general.parameter_count"] - 27e9) < 6000, str(info))
check("the tokenizer's long lists are passed over, not kept (and quickly)",
      "tokenizer.ggml.tokens" not in info and took < 2.0, f"{took:.2f}s")
info = lf.gguf_info(model_header(HEADS / "split.gguf", **{"split.count": 3}))
check("one part of a split file holds only some of the model: no parameter count from it",
      info and "general.parameter_count" not in info, str(info))
(HEADS / "README.md").write_text("# not a model", encoding="utf-8")
whole = (HEADS / "model.gguf").read_bytes()
(HEADS / "cut.gguf").write_bytes(whole[:len(whole) // 2])
check("a file that is not GGUF, or one cut short, is nothing", lf.gguf_info(HEADS / "README.md") is None
      and lf.gguf_info(HEADS / "cut.gguf") is None and lf.gguf_info(HEADS / "missing.gguf") is None)

print("\n== a llama.cpp model, looked at ==")
MODELS = TMP / "models"
real_dir = localai.app_models_dir
localai.app_models_dir = lambda: MODELS
lora_header(MODELS / STEM / f"{STEM}.gguf")
mmproj_header(MODELS / STEM / "mmproj-BF16.gguf")
model_header(MODELS / "Whole-Q4_K_M.gguf", label="8B", params=8_000_000_000)
model_header(MODELS / "Draft-Q8_0.gguf", label="27B", params=1_900_000_000)


class FakeLlama(BaseHTTPRequestHandler):
    """llama.cpp's router: no /api/show (a 404), and a 500 "failed to load" for any model asked to answer."""
    def log_message(self, *a):
        pass

    def _send(self, code, data):
        out = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": STEM, "status": {"value": "unloaded"}}]})
        self._send(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if self.path.endswith("/chat/completions"):
            return self._send(500, {"error": {"code": 500, "message": f"model name={body.get('model')} failed to load",
                                              "type": "server_error"}})
        self._send(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})


server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}/v1"

i = lf.inspect(STEM, BASE)
check("the downloaded 'model' is a LoRA: llama.cpp has no /api/show, so the file itself is asked",
      i and i["helper"] and i["kind"] == "adapter", str(i))
check("said in words", lf.what("adapter") == "a LoRA add-on for a model")
i = lf.inspect("Whole-Q4_K_M", BASE)
check("a whole model is not a helper", i and not i["helper"] and round(i["has"]) == 8, str(i))
i = lf.inspect("Draft-Q8_0", BASE)
check("a 1.9B file under a 27B name is a draft here too", i and i["helper"] and i["kind"] == "draft", str(i))
check("one that is not there is nothing to say", lf.inspect("Nope", BASE) is None)

print("\n== the repo's own files ==")
QWEN = [{"name": n, "size": int(s * GB)} for n, s in [
    (".gitattributes", 0), ("Qwen3.8-27B-Humanlike-Chat-BF16-00001-of-00002.gguf", 25.06),
    ("Qwen3.8-27B-Humanlike-Chat-BF16-00002-of-00002.gguf", 25.05), ("Qwen3.8-27B-Humanlike-Chat-IQ4_XS.gguf", 14.06),
    ("Qwen3.8-27B-Humanlike-Chat-Q4_K_M.gguf", 15.42), ("Qwen3.8-27B-Humanlike-Chat-Q5_K_M.gguf", 17.92),
    ("Qwen3.8-27B-Humanlike-Chat-Q6_K.gguf", 20.57), ("Qwen3.8-27B-Humanlike-Chat-Q8_0.gguf", 26.63),
    ("imatrix/imatrix.gguf", 0.01), ("lora/Qwen3.8-27B-Humanlike-Chat-2.0-LoRA-r320-F16.gguf", 4.35),
    ("mmproj/mmproj-BF16.gguf", 0.87)]]
tags = sorted(f["tag"] for f in lf.model_files(QWEN))
check("the LoRA in lora/ is not one of the model's sizes", tags == ["IQ4_XS", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"],
      str(tags))
check("nor one named so outside a lora/ folder, nor an adapter",
      lf.model_files([{"name": "Qwen3.8-27B-Humanlike-Chat-Step863-LoRA-F32.gguf", "size": 7 * GB},
                      {"name": "M-QLoRA-F16.gguf", "size": GB}, {"name": "adapters/M-F16.gguf", "size": GB}]) == [])
kept = [f["name"] for f in lf.model_files([{"name": "Llama-3-8B-LoRA-Merged-Q4_K_M.gguf", "size": 5 * GB},
                                           {"name": "Flora-7B-Q4_K_M.gguf", "size": 4 * GB}])]
check("one merged into the model is the model, and a name that only has the letters in it is kept",
      kept == ["Llama-3-8B-LoRA-Merged-Q4_K_M.gguf", "Flora-7B-Q4_K_M.gguf"], str(kept))
THIS_PC = {"ram": int(15.8 * GB), "vram": 4 * GB, "free": 82 * GB}
picks, why = lf.choices(QWEN, THIS_PC)
check("on that computer no size fits, and it says why (the LoRA was picked here before)",
      picks == [] and "14.1 GB" in why and "needs about" in why, f"{[p['name'] for p in picks]} {why}")

print("\n== something that fits instead: a smaller copy of it by someone else ==")
MAKER = [{"id": REPO, "tags": ["gguf"]}, {"id": "LessThanThreeAI/Qwen3.8-27B-Humanlike-Chat-2.0", "tags": ["safetensors"]},
         {"id": "LessThanThreeAI/Qwen3.8-27B-Humanlike-Chat-2.0-FP8", "tags": ["safetensors"]},
         {"id": "LessThanThreeAI/Gemma-4-31B-Humanlike-Chat-GGUF", "tags": ["gguf"]}]
COPIES = [{"id": REPO, "tags": ["gguf"], "downloads": 95491},
          {"id": "Ninja66666/Qwen3.8-27B-Humanlike-Chat-MTP-IQ2-GGUF", "tags": ["gguf"], "downloads": 255},
          {"id": "hum-ma/Qwen3.8-27B-Humanlike-Chat-MTP-IQ2-GGUF", "tags": ["gguf"], "downloads": 1041},
          {"id": "mradermacher/Qwen3.8-27B-Humanlike-Chat-2.0-i1-GGUF", "tags": ["gguf"], "downloads": 7600},
          {"id": "webmp3/Sakura-Humanlike-Chat-2.0-JEV-AutoRound-GGUF", "tags": ["gguf"], "downloads": 1934},
          {"id": "someone/Qwen3.8-9B-Humanlike-Chat-GGUF", "tags": ["gguf"], "downloads": 50}]
FILES = {
    REPO: QWEN,
    "LessThanThreeAI/Gemma-4-31B-Humanlike-Chat-GGUF": [
        {"name": "Gemma-4-31B-Humanlike-Chat-IQ4_XS.gguf", "size": int(15.59 * GB)},
        {"name": "lora/Gemma-4-31B-Humanlike-Chat-LoRA-r64-BF16.gguf", "size": int(0.91 * GB)}],
    "Ninja66666/Qwen3.8-27B-Humanlike-Chat-MTP-IQ2-GGUF": [
        {"name": "Qwen3.8-27B-Humanlike-Chat-MTP-IQ2_XXS.gguf", "size": int(8.25 * GB)}],
    "hum-ma/Qwen3.8-27B-Humanlike-Chat-MTP-IQ2-GGUF": [
        {"name": "Qwen3.8-27B-Humanlike-Chat-MTP-IQ2_XXS.gguf", "size": int(8.25 * GB)}],
    "mradermacher/Qwen3.8-27B-Humanlike-Chat-2.0-i1-GGUF": [
        {"name": "Qwen3.8-27B-Humanlike-Chat-2.0.i1-Q2_K.gguf", "size": int(10.12 * GB)}],
    "webmp3/Sakura-Humanlike-Chat-2.0-JEV-AutoRound-GGUF": [{"name": "Sakura-Q2_K.gguf", "size": 2 * GB}],
    "someone/Qwen3.8-9B-Humanlike-Chat-GGUF": [{"name": "Qwen3.8-9B-Humanlike-Chat-Q4_K_M.gguf", "size": 5 * GB}],
}
asked_hf, listed_files = [], []
real = {k: getattr(lf, k) for k in ("_hf_get", "repo_files", "machine")}


def fake_hf(url, **k):
    asked_hf.append(url)
    return MAKER if "author=" in url else COPIES if "search=" in url else {}


def fake_files(rid):
    listed_files.append(rid)
    return FILES[rid]


lf._hf_get, lf.repo_files = fake_hf, fake_files
alts = lf.alternatives(REPO, THIS_PC)
check("hum-ma's copy at 8 GB is offered first: the same model, the copy most people use",
      alts and alts[0]["repo"] == "hum-ma/Qwen3.8-27B-Humanlike-Chat-MTP-IQ2-GGUF" and alts[0]["tag"] == "IQ2_XXS"
      and alts[0]["by"] == "hum-ma", json.dumps(alts[:2]))
check("never a lookalike (Sakura), nor another size of it (a 9B), nor what does not fit",
      [a["repo"].split("/")[0] for a in alts] == ["hum-ma", "Ninja66666"], str([a["repo"] for a in alts]))
check("copies are looked for by the model's name, GGUF only",
      any("search=Qwen3.8-27B-Humanlike-Chat&filter=gguf" in u for u in asked_hf), str(asked_hf))
check("weights for other servers are not even opened", not any("2.0-FP8" in r or r.endswith("Chat-2.0") for r in listed_files),
      str(listed_files))
check("said in the log as a copy, with who made it",
      lf._offer(alts[0]).startswith(" A smaller copy of it by hum-ma fits: Qwen3.8-27B-Humanlike-Chat-MTP-IQ2-GGUF"),
      lf._offer(alts[0]))
check("the maker's own as before", "by the same maker" in lf._offer({**alts[0], "by": ""}))

print("\n== the repair, for llama.cpp ==")
from app.utils.atomic import write_json_atomic  # noqa: E402
write_json_atomic(MODELS / "sources.json", {STEM: {"repo": REPO, "tag": "F16",
                                                   "file": f"lora/{STEM}.gguf", "vision": "mmproj/mmproj-BF16.gguf"}})
real_local = {k: getattr(localai, k) for k in ("pull_kind", "start_pull", "pull_status", "delete_file_model")}
localai.pull_kind = lambda base: "file"
removed, pulled = [], []
localai.delete_file_model = lambda model, base: removed.append(model) or {"ok": True}
state = {"active": False}


def fake_pull(name, base, as_typed=False):
    pulled.append((name, as_typed))
    stem = f"{name.split('/')[-1].split(':')[0].removesuffix('-GGUF')}-{name.rsplit(':', 1)[1]}"
    state["last"] = {"asked": name, "model": stem, "error": "", "cancelled": False, "at": time.time()}
    return {"ok": True, "model": name}


localai.start_pull, localai.pull_status = fake_pull, lambda: dict(state)
lf.machine = lambda: dict(THIS_PC)
out = lf.repair(STEM, BASE)
check("nothing fits: stuck, saying it is a LoRA and the model itself does not fit",
      out["state"] == "stuck" and "LoRA add-on" in out["why"] and "does not fit" in out["why"], str(out))
check("with hum-ma's copy offered, one click away, and nothing downloaded or removed unasked",
      (out.get("alt") or {}).get("by") == "hum-ma" and pulled == [] and removed == [], str(out.get("alt")))
saved = yaml.safe_load((TMP / "config" / "config.yaml").read_text(encoding="utf-8"))["bot"]
check("the settings are left as they were", saved["models"]["replies"][0]["model"] == STEM)


def dropped(rid):
    import urllib.error
    raise urllib.error.URLError(ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host"))


lf.repo_files = dropped
out = lf.repair(STEM, BASE)
lf.repo_files = fake_files
check("Hugging Face dropping the line is said in words (the panel showed '<urlopen error [WinError 10054] ...>')",
      out["state"] == "stuck" and "could not be asked" in out["why"] and "asked again in a minute" in out["why"]
      and "urlopen" not in out["why"] and "10054" not in out["why"], out["why"])

lf.machine = lambda: {"ram": 64 * GB, "vram": 24 * GB, "free": 500 * GB}
out = lf.repair(STEM, BASE)
NEW = "Qwen3.8-27B-Humanlike-Chat-Q4_K_M"
check("with room for it: the model itself is downloaded, in the 4-bit size",
      pulled == [(f"hf.co/{REPO}:Q4_K_M", True)], str(pulled))
check("every setting names it by its file's name now, as llama.cpp lists it",
      out["state"] == "fixed" and out["to"] == NEW
      and yaml.safe_load((TMP / "config" / "config.yaml").read_text(encoding="utf-8"))["bot"]["models"]["replies"][0]["model"] == NEW,
      str(out))
check("and the LoRA is removed from the app's folder", removed == [STEM], str(removed))
for k, f in real_local.items():
    setattr(localai, k, f)

print("\n== Try says what the file is ==")
from app.web.routes import models_routes  # noqa: E402
conf = {"bot": {"local": {"base_url": BASE}, "max_reply_tokens": 100}}
lf.machine = lambda: dict(THIS_PC)
r = models_routes._try("local", STEM, conf)
check("a LoRA: said so, not 'This computer answered 500.'",
      not r["ok"] and r["error"] == "The file is a LoRA add-on for a model, not the model itself."
      and ROUTER_SAID in r["detail"], str(r))
lf.machine = lambda: {"ram": 1 * GB, "vram": 0, "free": 100 * GB}
r = models_routes._try("local", "Whole-Q4_K_M", conf)
check("a whole model too big for the computer: how much it needs and how much there is",
      not r["ok"] and r["error"].startswith("It would not load: it needs about") and "can give a model about" in r["error"],
      str(r))

print("\n== the download box ==")
real_mem = (lf._ram, lf._vram)
lf._ram, lf._vram = (lambda: int(15.8 * GB)), (lambda: 4 * GB)
import shutil  # noqa: E402
import types  # noqa: E402
real_disk = shutil.disk_usage
shutil.disk_usage = lambda path: types.SimpleNamespace(total=10**12, used=10**12 - 82 * GB, free=82 * GB)
try:
    plan = localai._plan_file(REPO, BASE)
finally:
    shutil.disk_usage = real_disk
    lf._ram, lf._vram = real_mem
check("the repo alone gets no LoRA: no size fits, and the copy that does is named to type in",
      not plan["ok"] and "No size of" in plan["reason"]
      and "hum-ma/Qwen3.8-27B-Humanlike-Chat-MTP-IQ2-GGUF:IQ2_XXS fits" in plan["reason"], str(plan))

print("\n== the panel ==")
src = (ROOT / "app" / "utils" / "localfix.py").read_text(encoding="utf-8")
check("a LoRA whose model does not fit is looked at again while nothing was found for it",
      're.search(r"^it is too big|does not fit|could not be asked"' in src)
page = (ROOT / "webui" / "src" / "lib" / "components" / "LocalAI.svelte").read_text(encoding="utf-8")
check("the page says when the offer is someone else's copy", "a smaller copy by ${fix.alt.by}" in page)

for k, f in real.items():
    setattr(lf, k, f)
localai.app_models_dir = real_dir
server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
