"""The models a local server has, as rows that go somewhere.

"Models it has" was a row of names. Each one now opens where it came from on
the web (its Hugging Face repo, or its page in Ollama's library), shows how big
it is, and has a button that shows the file on this computer: often tens of
gigabytes, so "where did that go" is a real question. And llama.cpp and vLLM
have their own logos instead of two letters.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="llmbot_modelrows_"))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import localai

print("== where a model lives on the web ==")
page = localai.model_page
check("a Hugging Face model opens its repo",
      page("hf.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:latest", "ollama")
      == {"url": "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive", "site": "Hugging Face"})
check("one of Ollama's own opens its library page",
      page("llama3.2:3b", "ollama") == {"url": "https://ollama.com/library/llama3.2", "site": "Ollama"})
check("and someone's model on Ollama opens theirs",
      page("mannix/llama3.1-8b:q4", "ollama")["url"] == "https://ollama.com/mannix/llama3.1-8b")
check("vLLM's names are Hugging Face names", page("Qwen/Qwen3-8B", "vllm")["url"] == "https://huggingface.co/Qwen/Qwen3-8B")
check("llama.cpp's -hf names too, without the quant",
      page("unsloth/Qwen3-8B-GGUF:Q4_K_M", "llamacpp")["url"] == "https://huggingface.co/unsloth/Qwen3-8B-GGUF")
check("a model served from a file searches for it",
      page(r"C:\models\qwen3-8b-q4_k_m.gguf", "llamacpp")["url"] == "https://huggingface.co/models?search=qwen3-8b-q4_k_m")
hostile = ["javascript:alert(1)", "hf.co/../../evil", "hf.co/a b/c", "https://evil.example/x", "hf.co/x/y\" onclick=1",
           "//evil.example", "ollama.com/../x", "a/b/../../c"]
urls = [page(n, sid).get("url", "") for n in hostile for sid in ("ollama", "lmstudio", "llamacpp", "vllm")]
check("whatever the name, it only ever leads to Hugging Face or Ollama",
      all(u == "" or u.startswith(("https://huggingface.co/", "https://ollama.com/")) for u in urls), str(urls))
check("with nothing in the path that could step out of it",
      all(".." not in u.split("?")[0] and '"' not in u and " " not in u for u in urls), str(urls))

print("\n== where it is on this computer ==")
blobs = TMP / "blobs"
blobs.mkdir()
weights = blobs / "sha256-aaaa"
weights.write_bytes(b"w" * 4000)
projector = blobs / "sha256-bbbb"
projector.write_bytes(b"p" * 100)
NAME = "hf.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:latest"


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._send({"data": [{"id": NAME}, {"id": "llama3.2:3b"}]})
        if self.path == "/api/tags":
            return self._send({"models": [{"name": NAME, "size": 22066041578}, {"name": "llama3.2:3b", "size": 2019393189}]})
        self._send({}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/show" and body.get("model") == NAME:
            # What Ollama really answers for a model with a vision part: two FROM lines.
            return self._send({"modelfile": f"# FROM {NAME}\n\nFROM {weights}\nFROM {projector}\nTEMPLATE x\n"})
        self._send({"error": "not found"}, 404)


server = HTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}/v1"
localai.server_for = lambda base_url: "ollama"   # the fake is not on Ollama's port

sizes = localai.ollama_sizes(BASE)
check("Ollama's list gives each model's size", sizes == {NAME: 22066041578, "llama3.2:3b": 2019393189}, str(sizes))
check("and a server that is not Ollama gives none, which is also how the panel knows it cannot download",
      localai.ollama_sizes("http://127.0.0.1:1/v1") is None)
check("Ollama's file is the weights, not the vision part beside it", localai.model_file(NAME, BASE) == str(weights))
check("a model Ollama does not know has no file", localai.model_file("nope:1b", BASE) == "")

lm = TMP / "lmstudio" / "lmstudio-community" / "Qwen3-8B-GGUF"
lm.mkdir(parents=True)
(lm / "Qwen3-8B-Q4_K_M.gguf").write_bytes(b"x" * 10)
(lm / "mmproj-Qwen3-8B-F16.gguf").write_bytes(b"x" * 20)
found = localai._search_dirs([str(TMP / "lmstudio")], "qwen/qwen3-8b")
check("LM Studio's files are found by name in its folders", found == str(lm / "Qwen3-8B-Q4_K_M.gguf"), found)
check("and a name that matches nothing finds nothing", localai._search_dirs([str(TMP / "lmstudio")], "mistral-7b") == "")

print("\n== showing it ==")
from app.web.routes import local_routes
from fastapi import HTTPException

shown = []
localai.show_in_folder = lambda path: shown.append(path)
local_routes.load_config = lambda: {"bot": {"local": {"base_url": BASE}}}


class Req:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def call(body):
    try:
        return asyncio.run(local_routes.reveal(Req(body)))
    except HTTPException as e:
        return {"status": e.status_code, "detail": e.detail}


r = call({"model": NAME})
check("the folder button shows the model's file", r.get("ok") and shown == [str(weights)], str(r))
shown.clear()
r = call({"model": str(weights)})
check("a path is not a model: nothing the server does not list is opened", r.get("status") == 404 and not shown, str(r))
r = call({"model": "llama3.2:3b"})
check("a listed model whose file cannot be found says so", r.get("status") == 404 and "find" in r.get("detail", ""), str(r))
check("and a request without a model is refused", call({}).get("status") == 400)

status = asyncio.run(local_routes.status(Req({})))
check("the panel is told each model's page", status["pages"].get(NAME, {}).get("site") == "Hugging Face", str(status.get("pages")))
check("and its size", status["sizes"].get(NAME) == 22066041578)
check("and still whether it can download", status["can_pull"] is True)

src = (ROOT / "app" / "utils" / "localai.py").read_text(encoding="utf-8")
body = src[src.index("def show_in_folder"):src.index("# ── What the rest of the app asks")]
check("Explorer opens on the file, selected", 'explorer /select,"{path}"' in body)
check("and a path with a quote in it is never put on that command line", "'\"' in path" in body)

print("\n== in the panel ==")
ui = (ROOT / "webui" / "src" / "lib" / "components" / "LocalAI.svelte").read_text(encoding="utf-8")
check("each model is a link that opens outside the app", 'class="lm-main" href={page.url} target="_blank"' in ui)
check("with the folder button beside it", 'class="lm-folder" onclick={() => reveal(m)}' in ui)
check("the ones a job uses are marked", "inUse.has(m)" in ui)
tile = (ROOT / "webui" / "src" / "lib" / "components" / "ProviderTile.svelte").read_text(encoding="utf-8")
check("llama.cpp and vLLM have logos", '"llamacpp", "vllm"' in tile)
from PIL import Image
for name in ("llamacpp", "vllm", "huggingface"):
    f = ROOT / "webui" / "public" / "providers" / f"{name}.png"
    ok = f.is_file()
    if ok:
        im = Image.open(f).convert("RGBA")
        corners = [im.getpixel(p)[3] for p in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1))]
        ok = max(corners) == 0 and im.getbbox() is not None
    check(f"{name}.png is the mark on nothing, like the others", ok)

server.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
