"""More model servers on this computer, not just Ollama, LM Studio, llama.cpp and vLLM.

Jan, GPT4All, KoboldCpp, LocalAI, the text generation web UI, TabbyAPI, Docker
Model Runner and SGLang are found too. What is worth pinning is the part that
goes wrong quietly:

  * two pairs share a port by default (llama.cpp and LocalAI on 8080, the web
    UI and TabbyAPI on 5000), so which one answered is worked out from what it
    says, not assumed from the port
  * a server that wants a key answers 401, and that is "running, wants a key",
    not "nothing there" (but an empty 403, which is AirPlay on a Mac's port
    5000, is not a server at all)
  * Docker's API lives under /engines/v1, not /v1
  * an app like Jan is opened rather than started, and when its server is still
    off inside it, the answer says where the switch is
  * a llama-server too old to start without a model fails at once, not after
    the full wait

Fake servers stand in for the real ones, so none of them need installing.
"""
import json
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fixtures import use_shipped_config
use_shipped_config()

from app.utils import localai
# Imported before subprocess.Popen is faked below: asyncio subclasses Popen on
# Windows, and importing it for the first time under the fake breaks it.
import asyncio  # noqa: F401
import app.web.logbus  # noqa: F401

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== the servers it knows ==")
by_id = {k["id"]: k for k in localai.KNOWN_SERVERS}
for sid, port in [("ollama", 11434), ("lmstudio", 1234), ("jan", 1337), ("gpt4all", 4891),
                  ("koboldcpp", 5001), ("llamacpp", 8080), ("localai", 8080), ("textgen", 5000),
                  ("tabbyapi", 5000), ("docker", 12434), ("vllm", 8000), ("sglang", 30000)]:
    check(f"{sid} listens on {port}", sid in by_id and by_id[sid]["root"].endswith(f":{port}"),
          str(by_id.get(sid, {}).get("root")))
check("every one says how to turn it on", all(k["hint"] for k in localai.KNOWN_SERVERS))
check("and where to get it", all(k["site"].startswith("https://") for k in localai.KNOWN_SERVERS))
check("Docker's API is under /engines/v1",
      localai._base(by_id["docker"]) == "http://127.0.0.1:12434/engines/v1", localai._base(by_id["docker"]))
check("Ollama stays the default", localai.DEFAULT_ROOT == "http://127.0.0.1:11434")
check("Ollama, LM Studio, llama.cpp and LocalAI start hidden, and so with the app as well",
      sorted(k["id"] for k in localai.KNOWN_SERVERS if k["start"] == "command") == ["llamacpp", "lmstudio", "localai", "ollama"]
      and not any("autostart" in k for k in localai.KNOWN_SERVERS))
check("Jan, GPT4All and KoboldCpp are opened, not started",
      all(by_id[s]["start"] == "app" for s in ("jan", "gpt4all", "koboldcpp")))
check("llama.cpp and LocalAI can be started", by_id["llamacpp"]["start"] == by_id["localai"]["start"] == "command")
check("vLLM and SGLang are left to you", by_id["vllm"]["start"] == by_id["sglang"]["start"] == "")

print("\n== which one lives at an address ==")
for url, want in [("http://127.0.0.1:1337/v1", "jan"), ("localhost:4891", "gpt4all"),
                  ("http://127.0.0.1:5001/v1", "koboldcpp"), ("http://127.0.0.1:12434/engines/v1", "docker"),
                  ("http://127.0.0.1:30000/v1", "sglang"), ("http://127.0.0.1:8080/v1", "llamacpp"),
                  ("http://127.0.0.1:5000/v1", "textgen"), ("http://127.0.0.1:9999/v1", "ollama")]:
    check(f"{url} is {want}", localai.server_for(url) == want, localai.server_for(url))
check("a port none of them use is none of them", localai.known_at("http://127.0.0.1:9999/v1") is None)
check("names by id", localai.server_name("koboldcpp") == "KoboldCpp" and localai.server_name("nope") == "")
check("an app is opened, a server started",
      localai.start_word("jan") == "Open" and localai.start_word("ollama") == "Start")


print("\n== servers that want a key ==")


class Fake(BaseHTTPRequestHandler):
    """An OpenAI-shaped server whose behaviour each test sets on the class."""
    key = ""
    owner = "koboldcpp"
    models = ["koboldcpp/Mistral-7B-Instruct-v0.3.Q4_K_M"]
    forbid_empty = False
    seen_auth = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, kind="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        Fake.seen_auth.append(self.headers.get("authorization", ""))
        if Fake.forbid_empty:
            return self._send(403, b"", "text/plain")
        if Fake.key and self.headers.get("authorization") != f"Bearer {Fake.key}":
            # Jan says it in plain text; the check is on the status, not the body.
            return self._send(401, b"Invalid or missing authorization token", "text/plain")
        if self.path == "/v1/models":
            return self._send(200, {"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": Fake.owner} for m in Fake.models]})
        return self._send(404, {"error": "no"})


server = HTTPServer(("127.0.0.1", 0), Fake)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}/v1"

Fake.key = "s3cret"
r = localai.probe(base, timeout=2.0)
check("without its key it is locked, not missing", r["locked"] and not r["ok"], str(r))
check("and says so in words", "key" in r["error"].lower(), r["error"])
r = localai.probe(base, timeout=2.0, api_key="wrong")
check("the wrong key is locked too", r["locked"], str(r))
r = localai.probe(base, timeout=2.0, api_key="s3cret")
check("the right key opens it", r["ok"] and not r["locked"] and r["models"] == Fake.models, str(r))
check("sent the way servers read it", Fake.seen_auth[-1] == "Bearer s3cret", Fake.seen_auth[-1])
check("the model list still reads the same way", localai.list_models(base, 2.0, "s3cret") == Fake.models)
Fake.key = ""
Fake.forbid_empty = True
r = localai.probe(base, timeout=2.0)
check("an empty 403 is not a server that wants a key", not r["locked"] and not r["ok"], str(r))
Fake.forbid_empty = False

print("\n== telling servers apart ==")
r = localai.probe(base, timeout=2.0)
check("who owns the models is read", r["owners"] == ["koboldcpp"], str(r.get("owners")))
check("KoboldCpp on a port of its own choosing is still KoboldCpp",
      localai.identify(base, r, 1.0) == "koboldcpp")
check("and remembered for that address", localai.server_for(base) == "koboldcpp")
Fake.owner = "someone"
check("a server nobody knows, on a port nobody uses, is not guessed at",
      localai.identify(f"http://localhost:{port}/v1", localai.probe(f"http://localhost:{port}/v1"), 1.0) == "")
Fake.owner = "koboldcpp"

real_answers = localai._answers
shared_8080 = "http://127.0.0.1:8080/v1"
shared_5000 = "http://127.0.0.1:5000/v1"
try:
    localai._answers = lambda url, timeout, api_key="": url.endswith("/version")
    check("on 8080 with no owner, one that answers /version is LocalAI",
          localai.identify(shared_8080, {"ok": True, "owners": []}) == "localai")
    check("and the address is LocalAI's from then on", localai.server_for(shared_8080) == "localai")
    localai._answers = lambda url, timeout, api_key="": url.endswith("/props")
    check("one that answers /props is llama.cpp",
          localai.identify(shared_8080, {"ok": True, "owners": []}) == "llamacpp")
    check("owned_by llamacpp settles it without asking",
          localai.identify(shared_8080, {"ok": True, "owners": ["llamacpp"]}) == "llamacpp")
    localai._answers = lambda url, timeout, api_key="": url.endswith("/health")
    check("on 5000, locked, one with an open /health is TabbyAPI",
          localai.identify(shared_5000, {"ok": False, "locked": True, "owners": []}) == "tabbyapi")
    localai._answers = lambda url, timeout, api_key="": False
    check("owned_by user is the web UI", localai.identify(shared_5000, {"ok": True, "owners": ["user"]}) == "textgen")
    check("and with nothing to go on, the first one that lives there",
          localai.identify(shared_5000, {"ok": True, "owners": []}) == "textgen")
finally:
    localai._answers = real_answers
    localai._seen.clear()

print("\n== looking for all of them at once ==")
calls = []
real_probe, real_installed = localai.probe, localai.installed


def fake_probe(url, timeout=2.0, api_key=""):
    calls.append(url)
    if url == "http://127.0.0.1:1337/v1":
        return {"ok": True, "models": ["jan-nano"], "owners": ["llama.cpp"], "locked": False, "error": ""}
    if url == "http://127.0.0.1:5000/v1":
        return {"ok": False, "models": [], "owners": [], "locked": True, "error": "It answered, but wants an API key."}
    if url == "http://127.0.0.1:8080/v1":
        return {"ok": True, "models": ["qwen"], "owners": ["llamacpp"], "locked": False, "error": ""}
    return {"ok": False, "models": [], "owners": [], "locked": False, "error": "Nothing answered"}


localai.probe = fake_probe
localai.installed = lambda sid: r"C:\fake\ollama.exe" if sid == "ollama" else ""
localai._answers = lambda url, timeout, api_key="": url.endswith("/health")
try:
    found = {s["id"]: s for s in localai.detect(timeout=0.2, api_key="")}
    check("every known server is reported", set(found) == set(by_id), str(sorted(found)))
    check("an address two share is asked once", calls.count("http://127.0.0.1:8080/v1") == 1
          and calls.count("http://127.0.0.1:5000/v1") == 1, str(calls))
    check("Jan is running, with its models", found["jan"]["running"] and found["jan"]["models"] == ["jan-nano"])
    check("llama.cpp is the one on 8080", found["llamacpp"]["running"] and not found["localai"]["running"])
    check("TabbyAPI is running and wants a key", found["tabbyapi"]["locked"] and not found["tabbyapi"]["running"])
    check("the web UI is not also marked as there", not found["textgen"]["locked"])
    check("Docker is asked at its own path", "http://127.0.0.1:12434/engines/v1" in calls)
    check("an installed server that starts from here says so",
          found["ollama"]["installed"] and found["ollama"]["can_start"])
    check("one that is not installed cannot be started", not found["gpt4all"]["can_start"])
    check("each carries how to turn it on", all(s["hint"] for s in found.values()))
finally:
    localai.probe, localai.installed, localai._answers = real_probe, real_installed, real_answers
    localai._seen.clear()

print("\n== starting and opening ==")
state = {"argv": None, "probes": [], "code": None}
real_popen = localai.subprocess.Popen


def never_up(url, timeout=2.0, api_key=""):
    state["probes"].append(url)
    return {"ok": False, "models": [], "owners": [], "locked": False, "error": "refused"}


def fake_popen(argv, **kw):
    state["argv"] = argv
    return types.SimpleNamespace(pid=1, poll=lambda: state["code"])


localai.probe = never_up
localai.subprocess.Popen = fake_popen
try:
    localai.installed = lambda sid: r"C:\fake\Jan.exe" if sid == "jan" else ""
    t0 = time.time()
    r = localai.start_server("jan", "http://127.0.0.1:1337/v1", wait=2)
    check("Jan is opened", state["argv"] == [r"C:\fake\Jan.exe"], str(state["argv"]))
    check("and with its server still off, it says where the switch is",
          r.get("opened") and not r["ok"] and "Local API Server" in r["reason"] and "look again" in r["reason"], str(r))
    check("without backticks in a toast", "`" not in r["reason"])
    check("within the wait it was given", time.time() - t0 < 6)

    localai.installed = lambda sid: r"C:\fake\llama-server.exe" if sid == "llamacpp" else ""
    state.update(argv=None, code=1)
    t0 = time.time()
    r = localai.start_server("llamacpp", "http://127.0.0.1:8080/v1", wait=20)
    check("llama-server starts without a model, as a router",
          state["argv"][:5] == [r"C:\fake\llama-server.exe", "--host", "127.0.0.1", "--port", "8080"], str(state["argv"]))
    check("with the room the app gives models", "--ctx-size" in state["argv"])
    check("one that stops at once is reported at once", not r["ok"] and time.time() - t0 < 5, f"{time.time() - t0:.1f}s")
    check("with what an older one needs", "llama-server -m" in r["reason"], r.get("reason"))

    state.update(argv=None, code=None, probes=[])
    localai.installed = lambda sid: r"C:\fake\lms.exe" if sid == "lmstudio" else ""
    localai.start_server("lmstudio", "http://127.0.0.1:11434/v1", wait=1)
    check("a button for LM Studio, with the app set to Ollama, starts it where LM Studio lives",
          state["probes"] and all(":1234/" in u for u in state["probes"]), str(state["probes"][:2]))

    r = localai.start_server("sglang", "http://127.0.0.1:30000/v1", wait=1)
    check("SGLang is left to you", not r["ok"] and "yourself" in r["reason"], str(r))

    # It stops at once (code 1), so the start does not wait out its 25 seconds.
    state.update(argv=None, code=1)
    localai.installed = lambda sid: r"C:\fake\llama-server.exe"
    cfg = {"bot": {"local": {"enabled": True, "model": "qwen", "base_url": "http://127.0.0.1:8080/v1"}}}
    localai.autostart(cfg)
    check("llama.cpp starts with the app too, not Ollama and LM Studio alone",
          (state["argv"] or [None])[0] == r"C:\fake\llama-server.exe", str(state["argv"]))
    state.update(argv=None, code=1)
    picked = {"bot": {"local": {"base_url": "http://127.0.0.1:8080/v1"}}}
    localai.autostart(picked)
    check("one picked by its address starts even before a job runs on it", state["argv"] is not None)
    state.update(argv=None, code=None)
finally:
    localai.probe, localai.installed, localai.subprocess.Popen = real_probe, real_installed, real_popen
    localai._seen.clear()

check("can_start needs it installed", localai.can_start("jan") == bool(localai.installed("jan")))
check("and a way to start it", localai.can_start("vllm") is False)

print("\n== model pages ==")
page = localai.model_page("koboldcpp/Mistral-7B-Instruct-v0.3.Q4_K_M", "koboldcpp")
check("a KoboldCpp model is searched for by its file name",
      page.get("url", "").startswith("https://huggingface.co/models?search=Mistral-7B"), str(page))
page = localai.model_page("ai/smollm2:latest", "docker")
check("a Docker model opens on Docker Hub", page == {"url": "https://hub.docker.com/r/ai/smollm2", "site": "Docker Hub"},
      str(page))
check("a Docker model from Hugging Face opens there",
      localai.model_page("hf.co/bartowski/Qwen-GGUF", "docker")["site"] == "Hugging Face")
page = localai.model_page("Llama 3 8B Instruct", "gpt4all")
check("GPT4All's names for people are searched for", "search=Llama%203%208B%20Instruct" in page.get("url", ""), str(page))
odd = [localai.model_page(n, s) for n in ("../../etc", "ai/../../x", "https://evil.example/x", "a/b/c/d", "koboldcpp/")
       for s in ("docker", "koboldcpp", "gpt4all")]
check("nothing points off those sites", all(
    not p or p["url"].startswith(("https://huggingface.co/", "https://hub.docker.com/r/", "https://ollama.com/"))
    for p in odd), str(odd))

print("\n== the panel ==")
ui = ROOT / "webui" / "src" / "lib"
panel = (ui / "components" / "LocalAI.svelte").read_text(encoding="utf-8")
check("installed and running ones are listed first", "const here = $derived(" in panel)
check("the rest are small tiles", "Also works with" in panel and "ls-grid" in panel and "ls-tile" in panel)
check("a tile opens to say how to turn it on", "said(opened.hint" in panel and "Use this address" in panel)
check("commands in a hint are set as code", 'text.split("`")' in panel and "ls-code" in panel)
check("a shared port shows the server that answered", "at.find((s) => s.running || s.locked)" in panel)
check("a key can be typed in", "bind:value={apiKey}" in panel and 'api.configField("bot.local.api_key"' in panel)
check("and is tried before saving", "api.localProbe(baseUrl, apiKey.trim()" in panel)
check("one that wants a key says so", "Needs a key" in panel and "wants its API key" in panel)
check("apps are opened", '"Open"' in panel and "r?.opened" in panel)
check("each server is started where it lives", "api.localStart(s.id, s.base_url)" in panel)
tile = (ui / "components" / "ProviderTile.svelte").read_text(encoding="utf-8")
logos = ROOT / "webui" / "public" / "providers"
for sid in ("jan", "gpt4all", "koboldcpp", "localai", "docker", "sglang", "textgen", "tabbyapi"):
    check(f"{sid} has its logo", f'"{sid}"' in tile and (logos / f"{sid}.png").is_file())
providers_ts = (ui / "providers.ts").read_text(encoding="utf-8")
check("and letters to fall back on, if a logo will not load", 'textgen: "TG"' in providers_ts and 'tabbyapi: "Tb"' in providers_ts)
icons = (ui / "components" / "Icon.svelte").read_text(encoding="utf-8")
check("there is a key icon", "paths.key = " in icons)
routes = (ROOT / "app" / "web" / "routes" / "local_routes.py").read_text(encoding="utf-8")
check("the status says who answered", "localai.identify" in routes and '"locked": result["locked"]' in routes)
check("and probes with the key", 'localai.probe, cfg["base_url"], 4.0, cfg["api_key"]' in routes)
health = (ROOT / "app" / "web" / "routes" / "health_routes.py").read_text(encoding="utf-8")
check("a locked server is its own notice, not 'not running'", 'wants an API key' in health and 'probe["locked"]' in health)
check("the notice's button opens an app", "localai.start_word(sid)" in health)

server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
