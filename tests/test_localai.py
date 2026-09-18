"""Running the brain on this machine instead of Groq.

The app does not run models itself; it talks to anything speaking the OpenAI
chat API (Ollama, LM Studio, llama.cpp, vLLM). What is worth pinning is the
plumbing around that, because every one of these has a failure mode that looks
like the app being broken rather than a setting being wrong:

  * a base URL missing its /v1 answers 404 on every single request
  * a HuggingFace name has to become an hf.co name or Ollama cannot fetch it
  * turning local on must stop "No Groq API key" being reported as the problem
  * turning it on with no Groq key must not make the runner exit at startup
  * voice and images must fail with a sentence, not an IndexError

A fake OpenAI-compatible server stands in for the real thing, so none of this
needs Ollama installed.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


from fixtures import use_shipped_config
use_shipped_config()

from app.utils import localai

print("== base urls people actually type ==")
for typed, want in [
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434/v1"),
    ("http://127.0.0.1:11434/", "http://127.0.0.1:11434/v1"),
    ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1"),
    ("localhost:1234", "http://localhost:1234/v1"),
    ("  http://box:8080/v1/  ", "http://box:8080/v1"),
    ("", "http://127.0.0.1:11434/v1"),
]:
    got = localai.normalise_base_url(typed)
    check(f"{typed!r} becomes the OpenAI root", got == want, got)

check("the server root drops /v1 again",
      localai.server_root("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434")

print("\n== model names ==")
# A slash means HuggingFace, which is the whole reason typing a HuggingFace name
# works: Ollama serves GGUF from hf.co.
for typed, want in [
    ("llama3.1:8b", "llama3.1:8b"),
    ("openai/gpt-oss-20b", "hf.co/openai/gpt-oss-20b"),
    ("hf.co/openai/gpt-oss-20b", "hf.co/openai/gpt-oss-20b"),
    ("huggingface.co/bartowski/thing", "hf.co/bartowski/thing"),
    ("", ""),
]:
    got = localai.ollama_name(typed)
    check(f"{typed!r} asks Ollama for the right thing", got == want, got)

print("\n== settings, including a config written before this existed ==")
blank = localai.settings({})
check("an absent block still reads", blank["enabled"] is False and blank["model"] == "")
check("and has a usable default address", blank["base_url"].endswith("/v1"))
check("an empty api key becomes something servers accept",
      localai.settings({"bot": {"local": {"api_key": ""}}})["api_key"] == "local")
check("enabled with no model is not active",
      localai.active({"bot": {"local": {"enabled": True, "model": ""}}}) is False)
check("enabled with a model is active",
      localai.active({"bot": {"local": {"enabled": True, "model": "x"}}}) is True)
check("a model with the switch off is not active",
      localai.active({"bot": {"local": {"enabled": False, "model": "x"}}}) is False)

print("\n== against a server that speaks the OpenAI API ==")


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/v1/models":
            self._json(200, {"data": [{"id": "qwen2.5:7b"}, {"id": "llama3.1:8b"}]})
        elif self.path == "/api/tags":
            self._json(200, {"models": []})
        else:
            self._json(404, {"error": "no"})


server = HTTPServer(("127.0.0.1", 0), Fake)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

result = localai.probe(base)
check("a running server is found", result["ok"] is True, result["error"])
check("its models are listed", result["models"] == ["llama3.1:8b", "qwen2.5:7b"],
      str(result["models"]))
check("pulling is offered when the server can do it", localai.pull_supported(base) is True)

dead = localai.probe("http://127.0.0.1:1", timeout=0.5)
check("a dead address is reported, not raised", dead["ok"] is False and bool(dead["error"]))
check("and reads as plain English", "answered" in dead["error"].lower(), dead["error"])
check("a dead address cannot pull", localai.pull_supported("http://127.0.0.1:1") is False)

print("\n== the client the runner ends up with ==")
import app.utils.helpers as helpers
from app.utils import ai

real_load = helpers.load_config
base_cfg = real_load()


def with_local(**over):
    cfg = json.loads(json.dumps(base_cfg))
    cfg.setdefault("bot", {})["local"] = {
        "enabled": True, "base_url": base, "model": "qwen2.5:7b",
        "api_key": "local", "vision": False, **over,
    }
    return cfg


helpers.load_config = lambda: with_local()
ai.load_config = helpers.load_config
try:
    ai.init_ai()
    check("a local client is built", ai.local_active() is True)
    check("it points at the right server",
          str(ai._local_client.base_url).rstrip("/").endswith(f":{port}/v1"),
          str(ai._local_client.base_url))
    check("the chat model is the local one", ai._chat_model() == "qwen2.5:7b")
    check("the chat client is the local one", ai._chat_client() is ai._local_client)
finally:
    helpers.load_config = real_load
    ai.load_config = real_load

print("\n== with local on and no Groq key at all ==")
# init_ai() called sys.exit(1) on a missing key. With replies running locally
# that is no longer a reason to refuse to start, and exiting there would take
# the whole account down at launch.
import os

saved_env = {k: os.environ.pop(k) for k in list(os.environ)
             if k.startswith("GROQ_API_KEY")}
helpers.load_config = lambda: with_local()
ai.load_config = helpers.load_config
ai.getenv = lambda name, default=None: None
try:
    exited = False
    try:
        ai.init_ai()
    except SystemExit:
        exited = True
    check("it starts anyway", not exited)
    check("with no Groq clients", ai._groq_clients == [])
    check("and replies still have somewhere to come from", ai.local_active() is True)
finally:
    ai.getenv = __import__("os").getenv
    helpers.load_config = real_load
    ai.load_config = real_load
    os.environ.update(saved_env)

print("\n== what local cannot do says so ==")
import asyncio


async def voice():
    try:
        await ai._create_transcription("whisper-large-v3", b"x")
        return ""
    except Exception as e:
        return str(e)


message = asyncio.run(voice())
check("a voice message explains it needs Groq", "Groq key" in message, message[:90])
check("rather than an IndexError", "IndexError" not in message and "list index" not in message,
      message[:90])

from app.utils import tts

tts._client = None
# Emptying os.environ is not enough: _get_client calls load_dotenv first and
# reads the real key straight back off disk, which is what it should do. The
# lookup itself is what has to come back empty.
real_getenv = tts.getenv
tts.getenv = lambda name, default=None: None
try:
    reason = ""
    try:
        tts._get_client()
    except Exception as e:
        reason = str(e)
    check("speaking explains it needs Groq too", "Groq key" in reason, reason[:90])
    check("and does not build a client with no key", tts._client is None)
finally:
    tts.getenv = real_getenv
    tts._client = None

print()
print("== one model per job, so Groq can be dropped entirely ==")
# Chat was always allowed to move. Pictures, voice messages and speech only
# follow once a model is named for them, because most servers implement none of
# the three, and a text model handed a picture invents one rather than refusing.
try:
    helpers.load_config = lambda: with_local()
    ai.load_config = helpers.load_config
    ai.init_ai()
    check("chat alone leaves pictures on Groq", ai.vision_is_local() is False)
    check("and voice messages on Groq", ai.stt_is_local() is False)
    check("and speech on Groq", ai.local_tts() == {})

    # The switch that existed before there was anywhere to name a second model.
    helpers.load_config = lambda: with_local(vision=True)
    ai.load_config = helpers.load_config
    ai.init_ai()
    check("the old 'it can see too' switch still reads images locally",
          ai.vision_is_local() is True)
    check("using the chat model, since that is what it meant",
          ai._local_vision_model == "qwen2.5:7b")

    helpers.load_config = lambda: with_local(
        vision_model="llava", stt_model="whisper-1",
        tts_model="kokoro", tts_voice="af_sky")
    ai.load_config = helpers.load_config
    ai.init_ai()
    check("a named vision model reads images here", ai.vision_is_local() is True)
    check("and it is that model, not the chat one", ai._local_vision_model == "llava")
    check("a named speech-to-text model transcribes here", ai.stt_is_local() is True)
    speech = ai.local_tts()
    check("speech goes local with the right model", speech.get("model") == "kokoro")
    check("and its own voice name, which is per-engine",
          speech.get("voice") == "af_sky", str(speech))
    check("pointed at the local server, not Groq",
          speech.get("base_url") == localai.normalise_base_url(base),
          str(speech.get("base_url")))

    # The bracketed tones are Orpheus prompt syntax. Any other engine reads them
    # out loud, so they must not survive the trip to a local server.
    import app.utils.tts as tts
    tts._local_client = tts._local_key = None
    src = (ROOT / "app" / "utils" / "tts.py").read_text(encoding="utf-8")
    check("tone tags are dropped for a local engine",
          'tone_prefix = "" if local else' in src)
    backend = tts._get_local()
    check("tts.py finds the local backend",
          bool(backend) and backend["model"] == "kokoro")
    check("and caches the client it built",
          tts._get_local()["client"] is backend["client"])
finally:
    # Deliberately not re-running init_ai here: the real config has local off,
    # and this test process has no Groq key, so it would sys.exit(1).
    helpers.load_config = real_load
    ai.load_config = real_load
    import app.utils.tts as tts
    tts._local_client = tts._local_key = None

print("\n== the panel knows about it ==")
page = (ROOT / "webui" / "src" / "lib" / "components" / "LocalAI.svelte").read_text(encoding="utf-8")
check("there is a panel", "localDetect" in page and "localPull" in page)
tree = (ROOT / "webui" / "src" / "lib" / "settingsmap.ts").read_text(encoding="utf-8")
check("it has a home in Settings", '"local"' in tree and "Local AI" in tree)
check("and a pointer name", '"local ai"' in tree)
api = (ROOT / "webui" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
for name in ("localStatus", "localDetect", "localProbe", "localPull", "localPullStatus"):
    check(f"api.{name} exists", name in api)
check("the routes are registered",
      "local_routes" in (ROOT / "app" / "web" / "server.py").read_text(encoding="utf-8"))
check("bot.local is not also a row in Settings",
      '"bot.local"' in (ROOT / "app" / "web" / "descriptions.py").read_text(encoding="utf-8"))
cfg_text = (ROOT / "resources" / "config.yaml").read_text(encoding="utf-8")
check("the shipped config documents it", "local:" in cfg_text)
for key in ("vision_model", "stt_model", "tts_model", "tts_voice"):
    check(f"and ships {key}", f"{key}:" in cfg_text)
for key in ("visionModel", "sttModel", "ttsModel", "ttsVoice"):
    check(f"the panel edits {key}", key in page)

server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
