"""
app/utils/localai.py - running the brain on this machine instead of Groq.

Why it is shaped this way
-------------------------
The obvious version of this feature is a box you paste a HuggingFace name into,
which then downloads the model into the app's own folder and runs it. That does
not work, for four reasons that are worth writing down so nobody tries again:

  * the models this app actually uses cannot run on a desktop. gpt-oss-120b is
    about 65 GB even at 4-bit. The realistic local option is a 7-8B model.
  * a HuggingFace repo name is not runnable on its own. Those repos hold
    safetensors for `transformers`, which means bundling torch: a few hundred MB
    for the CPU build and 2-3 GB with CUDA, against a 175 MB app. Consumer
    hardware wants GGUF quants, which live in different repos again.
  * a long persona is a couple of thousand tokens of prompt before a single
    token is generated, and on CPU that is slow enough to see.
  * it means writing and maintaining a download manager, a quantisation picker,
    GPU detection and an inference runtime, inside a Discord selfbot.

So the app does not run models. It talks to something that does.

Any server speaking the OpenAI chat API works, which is all of the usual ones:
Ollama, LM Studio, llama.cpp's own server, vLLM, LocalAI. That gives every
upside that was actually being asked for (no rate limits, no keys, nothing
leaving the machine) with none of the runtime.

The one piece kept from the original idea is pulling a model by name, including
a HuggingFace name, because Ollama can do that itself: it serves GGUF straight
from `hf.co/<user>/<repo>`. So typing "openai/gpt-oss-20b" and having it
download really does work, Ollama just does the downloading.
"""

import json
import threading
import time
import urllib.error
import urllib.request

# The servers people actually run, in the order worth trying. Each entry is the
# root, not the OpenAI path: Ollama needs its native API for pulling, which
# lives beside /v1 rather than under it.
KNOWN_SERVERS = [
    {"id": "ollama", "name": "Ollama", "root": "http://127.0.0.1:11434",
     "site": "https://ollama.com/download", "can_pull": True},
    {"id": "lmstudio", "name": "LM Studio", "root": "http://127.0.0.1:1234",
     "site": "https://lmstudio.ai", "can_pull": False},
    {"id": "llamacpp", "name": "llama.cpp server", "root": "http://127.0.0.1:8080",
     "site": "https://github.com/ggml-org/llama.cpp", "can_pull": False},
    {"id": "vllm", "name": "vLLM", "root": "http://127.0.0.1:8000",
     "site": "https://docs.vllm.ai", "can_pull": False},
]

DEFAULT_ROOT = KNOWN_SERVERS[0]["root"]


def normalise_base_url(text: str) -> str:
    """Turn whatever someone typed into the OpenAI base URL for that server.

    People paste "localhost:11434", "http://localhost:11434/" and
    "http://localhost:11434/v1" interchangeably, and the client needs exactly
    the last form. Getting this wrong produces a 404 on every single request,
    which reads like the model is broken rather than like a typo.
    """
    url = (text or "").strip().rstrip("/")
    if not url:
        return DEFAULT_ROOT + "/v1"
    if "://" not in url:
        url = "http://" + url
    if not url.endswith("/v1"):
        url += "/v1"
    return url


def server_root(base_url: str) -> str:
    """The server itself, with the OpenAI path taken back off."""
    url = (base_url or "").strip().rstrip("/")
    return url[:-3].rstrip("/") if url.endswith("/v1") else url


def _get(url: str, timeout: float = 2.0):
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def list_models(base_url: str, timeout: float = 4.0) -> list:
    """Model ids the server is offering, via the OpenAI /models endpoint.

    Typing a model name by hand is how you get a 404 on every request months
    later, so the picker offers what is actually loaded instead.
    """
    data = _get(normalise_base_url(base_url) + "/models", timeout=timeout)
    out = []
    for item in (data.get("data") or []):
        name = item.get("id")
        if name:
            out.append(name)
    return sorted(out)


def probe(base_url: str, timeout: float = 2.0) -> dict:
    """Is something answering there, and what has it got?"""
    try:
        models = list_models(base_url, timeout=timeout)
        return {"ok": True, "models": models, "error": ""}
    except urllib.error.HTTPError as e:
        return {"ok": False, "models": [], "error": f"HTTP {e.code} from the server"}
    except urllib.error.URLError as e:
        return {"ok": False, "models": [], "error": f"Nothing answered ({e.reason})"}
    except Exception as e:
        return {"ok": False, "models": [], "error": str(e)}


def detect(timeout: float = 0.6) -> list:
    """Which of the known servers are running right now.

    Deliberately a short timeout on each: this runs behind a page load, and
    servers that are not installed must not cost a second each. A closed port
    refuses immediately anyway - but a port that is open and unresponsive, or
    one being firewalled with a DROP rather than a refuse, waits out the whole
    timeout. Probing them together bounds that at one timeout rather than four.
    """
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(KNOWN_SERVERS) or 1) as pool:
        results = list(pool.map(lambda s: probe(s["root"], timeout=timeout),
                                KNOWN_SERVERS))
    return [
        {
            **server,
            "running": result["ok"],
            "models": result["models"],
            "base_url": normalise_base_url(server["root"]),
        }
        for server, result in zip(KNOWN_SERVERS, results)
    ]


# ── Pulling a model ───────────────────────────────────────────────────────────

def ollama_name(text: str) -> str:
    """What Ollama should be asked for, given what someone typed.

    Its own models are bare names with a tag, like "llama3.1:8b". A name with a
    slash in it is a HuggingFace repo, which Ollama serves GGUF from under the
    hf.co prefix, so "openai/gpt-oss-20b" becomes "hf.co/openai/gpt-oss-20b".
    That is the whole reason typing a HuggingFace name works at all.
    """
    name = (text or "").strip()
    if not name or "/" not in name:
        return name
    lowered = name.lower()
    if lowered.startswith("huggingface.co/"):
        return "hf.co/" + name.split("/", 1)[1]
    for prefix in ("hf.co/", "registry.ollama.ai/", "ollama.com/"):
        if lowered.startswith(prefix):
            return name
    return "hf.co/" + name


# One pull at a time, reported the way the picture describer reports its batch:
# a dict the panel polls, rather than a socket it has to stay attached to.
_pull = {
    "active": False,
    "model": "",
    "status": "",
    "percent": 0,
    "done": 0,
    "total": 0,
    "error": "",
    "finished_at": 0.0,
}
_pull_lock = threading.Lock()


def pull_status() -> dict:
    with _pull_lock:
        return dict(_pull)


def _set(**fields):
    with _pull_lock:
        _pull.update(fields)


def pull_supported(base_url: str) -> bool:
    """Only Ollama can fetch a model for you; the others are pointed at files."""
    root = server_root(base_url)
    try:
        _get(root + "/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def start_pull(model: str, base_url: str) -> dict:
    """Download a model through Ollama, in the background.

    Ollama streams newline delimited JSON for the duration, which is where the
    progress comes from. A download is minutes long, so this returns straight
    away and the panel polls pull_status().
    """
    name = ollama_name(model)
    if not name:
        return {"ok": False, "reason": "No model name given."}
    with _pull_lock:
        if _pull["active"]:
            return {"ok": False, "reason": f"Already downloading {_pull['model']}."}
        _pull.update({"active": True, "model": name, "status": "starting",
                      "percent": 0, "done": 0, "total": 0, "error": "",
                      "finished_at": 0.0})

    root = server_root(base_url)

    def work():
        from app.web.logbus import bus
        try:
            body = json.dumps({"model": name, "stream": True}).encode()
            req = urllib.request.Request(
                root + "/api/pull", data=body,
                headers={"content-type": "application/json"}, method="POST")
            bus.append("local", f"Downloading {name}")
            last_logged = 0.0
            # No timeout on the read: the server sends a line every second or so
            # while it works, and a large model takes a long time between them.
            with urllib.request.urlopen(req, timeout=60) as stream:
                for raw in stream:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("error"):
                        _set(error=str(event["error"]))
                        bus.append("local", f"Download failed: {event['error']}", "error")
                        break
                    status = event.get("status") or ""
                    total = int(event.get("total") or 0)
                    done = int(event.get("completed") or 0)
                    percent = int(done * 100 / total) if total else 0
                    _set(status=status, total=total, done=done, percent=percent)
                    # One line a minute in the log, not one a second.
                    if time.time() - last_logged > 20:
                        last_logged = time.time()
                        bus.append("local", f"{name}: {status}"
                                   + (f" {percent}%" if total else ""))
            with _pull_lock:
                if not _pull["error"]:
                    _pull["status"] = "ready"
                    _pull["percent"] = 100
        except Exception as e:
            _set(error=str(e))
            try:
                bus.append("local", f"Download failed: {e}", "error")
            except Exception:
                pass
        finally:
            _set(active=False, finished_at=time.time())
            try:
                from app.web.logbus import bus as b
                if not pull_status()["error"]:
                    b.append("local", f"{name} is ready to use")
            except Exception:
                pass

    threading.Thread(target=work, daemon=True, name="ollama-pull").start()
    return {"ok": True, "model": name}


# ── What the rest of the app asks ─────────────────────────────────────────────

def settings(config: dict) -> dict:
    """The local block, with every default filled in.

    Read through one function so a config written before this feature existed
    behaves exactly like one that turned it off, rather than raising KeyError
    somewhere deep in a reply.
    """
    bot = (config or {}).get("bot") or {}
    local = bot.get("local") or {}
    return {
        "enabled": bool(local.get("enabled", False)),
        "base_url": normalise_base_url(local.get("base_url") or DEFAULT_ROOT),
        "model": (local.get("model") or "").strip(),
        # Some servers want any non-empty string, and reject a blank one.
        "api_key": (local.get("api_key") or "local").strip() or "local",
        "vision": bool(local.get("vision", False)),
    }


def active(config: dict) -> bool:
    """True when replies should be generated locally rather than by Groq."""
    cfg = settings(config)
    return cfg["enabled"] and bool(cfg["model"])
