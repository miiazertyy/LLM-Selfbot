"""The This computer page, laid out by what matters, and with more to do.

It was one long column of boxes in the order they were written, with the
models last of all, under the address. Now the server has a card of its own
at the top: what it is, whether it runs, where, how many models and how much
disk, which jobs run on it, and whatever gets it going. Its models come next,
each with how many parameters and how it is quantised (Ollama says), which
are in memory right now, and a bin: Ollama's models are gigabytes each, and
removing one meant a terminal. A download says what it is doing in words,
with its speed and time left ("pulling 115e618e1f73" is a layer's name, not
news), and can be stopped. The settings follow, then every other server as
small chips.
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-localpage-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from app.utils import localai  # noqa: E402

deleted = []
MODELS = {
    "llama3.1:8b": {"size": 4920000000, "details": {"parameter_size": "8.0B", "quantization_level": "Q4_K_M", "family": "llama"}},
    "gemma3:4b": {"size": 3340000000, "details": {"parameter_size": "4.3B", "quantization_level": "Q4_K_M", "family": "gemma3"}},
}


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

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/v1/models":
            return self._send({"data": [{"id": m} for m in MODELS]})
        if self.path == "/api/tags":
            return self._send({"models": [{"name": m, "size": v["size"], "details": v["details"]} for m, v in MODELS.items()]})
        if self.path == "/api/ps":
            return self._send({"models": [{"name": "llama3.1:8b", "size": 6000000000, "size_vram": 5400000000}]})
        self._send({}, 404)

    def do_DELETE(self):
        body = self._body()
        if self.path == "/api/delete" and body.get("model") in MODELS:
            deleted.append(body["model"])
            return self._send({})
        self._send({"error": "model not found"}, 404)

    def do_POST(self):
        if self.path != "/api/pull":
            return self._send({}, 404)
        self._body()
        # A long download: a line every tenth of a second, a percent at a time.
        self.send_response(200)
        self.send_header("content-type", "application/x-ndjson")
        self.end_headers()
        try:
            for i in range(100):
                self.wfile.write((json.dumps({"status": "pulling 115e618e1f73", "total": 1000, "completed": i * 10}) + "\n").encode())
                self.wfile.flush()
                time.sleep(0.1)
            self.wfile.write(b'{"status":"success"}\n')
        except OSError:
            pass


server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}/v1"
localai.server_for = lambda base_url: "ollama"   # the fake is not on Ollama's port

print("== what Ollama says about its models ==")
info = localai.ollama_models(BASE)
check("how many parameters, how it is quantised, and its size",
      info["llama3.1:8b"] == {"size": 4920000000, "params": "8.0B", "quant": "Q4_K_M", "family": "llama"}, str(info))
check("the sizes still come from the same list", localai.ollama_sizes(BASE) == {m: v["size"] for m, v in MODELS.items()})
check("not Ollama: nothing, which is how the page knows", localai.ollama_models("http://127.0.0.1:1/v1") is None)
check("which are in memory right now, and how much of it", localai.ollama_loaded(BASE) == {"llama3.1:8b": 5400000000})
check("and none where nothing answers", localai.ollama_loaded("http://127.0.0.1:1/v1") == {})

print("\n== removing one ==")
check("a model Ollama has is removed", localai.delete_model("gemma3:4b", BASE) == {"ok": True} and deleted == ["gemma3:4b"])
r = localai.delete_model("nope:1b", BASE)
check("one it does not have says so", not r["ok"] and "does not have" in r["reason"], str(r))

print("\n== stopping a download ==")
check("nothing to stop when nothing downloads", not localai.cancel_pull()["ok"])
check("a download starts", localai.start_pull("llama3.1:8b", BASE)["ok"])
deadline = time.time() + 5
while time.time() < deadline and localai.pull_status()["percent"] < 3:
    time.sleep(0.05)
check("and goes up", localai.pull_status()["active"] and localai.pull_status()["percent"] >= 3, str(localai.pull_status()))
check("stopping it is taken", localai.cancel_pull()["ok"] and localai.pull_status()["status"] == "stopping")
deadline = time.time() + 5
while time.time() < deadline and localai.pull_status()["active"]:
    time.sleep(0.05)
st = localai.pull_status()
check("it ends at the next line, not at the end of the download", not st["active"] and st["percent"] < 50, str(st))
check("stopped, not failed and not ready", st["status"] == "cancelled" and not st["error"], str(st))
check("and the next download starts clean", localai.start_pull("llama3.1:8b", BASE)["ok"] and not localai.pull_status()["cancel"])
localai.cancel_pull()
deadline = time.time() + 5
while time.time() < deadline and localai.pull_status()["active"]:
    time.sleep(0.05)

print("\n== the routes ==")
localai.settings = lambda cfg: {"enabled": True, "base_url": BASE, "api_key": "", "model": "", "autostart": True,
                                "context_length": 16384}
localai.identify = lambda *a, **k: "ollama"
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import local_routes  # noqa: E402

app = FastAPI()
app.include_router(local_routes.router)
c = TestClient(app)
s = c.get("/api/local/status").json()
check("the status has each model's details and what is loaded",
      s["details"]["llama3.1:8b"]["params"] == "8.0B" and s["loaded"] == {"llama3.1:8b": 5400000000} and s["can_pull"], str(s)[:300])
check("a model the server does not list is not removed", c.post("/api/local/delete", json={"model": "../x"}).status_code == 404)
check("nor anything on a server that is not Ollama",
      c.post("/api/local/delete", json={"model": "llama3.1:8b", "base_url": "http://127.0.0.1:1/v1"}).status_code == 400)
r = c.post("/api/local/delete", json={"model": "llama3.1:8b"})
check("one it lists is", r.status_code == 200 and deleted[-1] == "llama3.1:8b", r.text)
check("stopping, with nothing going, says so", c.post("/api/local/pull/cancel").json()["ok"] is False)

print("\n== the page ==")
ui = read("lib/components/LocalAI.svelte")
order = [ui.find('<section class="lc-hero'), ui.find("<h3>Models</h3>"), ui.find("<h3>Settings</h3>"), ui.find("<h3>Also works with</h3>")]
check("the server first, then its models, then the settings, then the rest", all(i > 0 for i in order) and order == sorted(order), str(order))
check("the server's card says what it is doing, in a word", "const heroState = $derived.by(" in ui and '"Needs a key"' in ui
      and '"Not installed"' in ui)
check("and gives off a signal while it is at work, not all the time it runs",
      ".lc-hero.is-good.is-busy .lc-logo::after" in ui and "@keyframes lc-signal" in ui)
check("each model's facts once each", "function facts(" in ui and "d?.params, d?.quant" in ui)
check("the ones in memory say so", "loaded[m] != null" in ui and "In memory" in ui)
check("a bin that asks once, on itself, then removes", "askRemove(m)" in ui and "removeModel(m)" in ui
      and "api.localDelete(m, baseUrl)" in ui)
check("the download in words, with its speed and time left", "function stage(" in ui and '"Downloading"' in ui
      and "speed(rate)" in ui and "timeLeft(" in ui)
check("and a way to stop it", "api.localPullCancel()" in ui and "if (l.cancelled) toast(" in ui)
check("typed while one downloads, the next waits its turn: the box stays open, its button says Queue",
      'disabled={asking}\n          aria-label="Model to download"' in ui and '{pull?.active ? "Queue" : "Download"}' in ui
      and "api.localPullUnqueue(model)" in ui and '<ol class="lc-queue">' in ui)
check("each that ends is said once, even when the queue moves straight on", "async function sayEnded(p: Pull)" in ui
      and "l.at <= lastSaid" in ui)
check("the room for the conversation is picked on a slider of five", '<Segmented label="Room for the conversation"' in ui)
check("models come and go with a slide", "transition:slide" in ui)
api = read("lib/api.ts")
check("the calls exist", "localPullCancel:" in api and "localDelete:" in api)

server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
