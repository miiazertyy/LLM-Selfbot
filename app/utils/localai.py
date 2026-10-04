"""Running the brain on this machine instead of Groq. The obvious version is a box you paste a HuggingFace name into, which then downloads the model into the app's own folder and runs it; that does not work, for four reasons worth writing down so nobody tries again: the models this app actually uses cannot run on a desktop (gpt-oss-120b is about 65 GB even at 4-bit, the realistic local option is a 7-8B model), a HuggingFace repo name is not runnable on its own (those repos hold safetensors for `transformers`, which means bundling torch, a few hundred MB for the CPU build and 2-3 GB with CUDA, against a 175 MB app, consumer hardware wants GGUF quants which live in different repos again), a long persona is a couple of thousand tokens of prompt before a single token is generated, and on CPU that is slow enough to see, and it means writing and maintaining a download manager, a quantisation picker, GPU detection and an inference runtime inside a Discord selfbot. So the app does not run models, it talks to something that does: any server speaking the OpenAI chat API works, which is all of the usual ones (Ollama, LM Studio, Jan, GPT4All, KoboldCpp, llama.cpp's own server, LocalAI, vLLM and more), giving every upside that was actually being asked for (no rate limits, no keys, nothing leaving the machine) with none of the runtime. The one piece kept from the original idea is pulling a model by name, including a HuggingFace name, because Ollama can do that itself: it serves GGUF straight from `hf.co/<user>/<repo>`, so typing "openai/gpt-oss-20b" and having it download really does work, Ollama just does the downloading."""

import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def _server(sid, name, root, site, hint, start="", path="/v1", owner=(), mark="", can_pull=False, get=""):
    return {"id": sid, "name": name, "root": root, "path": path, "site": site, "hint": hint, "start": start,
            "owner": list(owner), "mark": mark, "can_pull": can_pull, "get": get}


# The servers people actually run, in the order worth showing. `root` is the server itself and `path` where its OpenAI API lives under it: Ollama's native API, which pulling needs, sits beside /v1 rather than under it.
# `start` is how the app can bring one up: "command" runs it hidden in the background, "app" opens its window (its server is a setting inside), and "" means it needs a model and flags only the person running it knows. Each of those also starts with the app (autostart below).
# `owner` is what its model list says in owned_by, and `mark` a page only it answers. Two pairs share a port by default (llama.cpp and LocalAI on 8080, the web UI and TabbyAPI on 5000), and those say which one is there. `hint` is how to turn its API on, with commands in backticks (and no full stop after one, where it would hang off the code). `get` is where its models come from, for one the app cannot give a model to (Ollama downloads them itself, and llama.cpp is given the file).
KNOWN_SERVERS = [
    _server("ollama", "Ollama", "http://127.0.0.1:11434", "https://ollama.com/download",
            "The easiest to start with. The app starts it for you.",
            start="command", owner=("library",), can_pull=True),
    _server("lmstudio", "LM Studio", "http://127.0.0.1:1234", "https://lmstudio.ai",
            "The app starts its server for you.", start="command", owner=("organization_owner",),
            get="Get models in LM Studio, on its Discover tab."),
    _server("jan", "Jan", "http://127.0.0.1:1337", "https://jan.ai",
            "Turn on Local API Server in its settings.", start="app", owner=("llama.cpp", "mlx"),
            get="Get models in Jan, from its Hub."),
    _server("gpt4all", "GPT4All", "http://127.0.0.1:4891", "https://www.nomic.ai/gpt4all",
            "Turn on Enable Local API Server in its settings.", start="app", owner=("humanity",),
            get="Get models in GPT4All, on its Models page."),
    _server("koboldcpp", "KoboldCpp", "http://127.0.0.1:5001", "https://github.com/LostRuins/koboldcpp/releases/latest",
            "Pick a model in its window and launch it.", start="app", owner=("koboldcpp",),
            get="KoboldCpp runs the model file picked in its window as it starts."),
    _server("llamacpp", "llama.cpp server", "http://127.0.0.1:8080", "https://github.com/ggml-org/llama.cpp",
            "The app starts it for you, with the models it downloads",
            start="command", owner=("llamacpp",), mark="/props"),
    _server("localai", "LocalAI", "http://127.0.0.1:8080", "https://localai.io",
            "Run its Docker image, or `local-ai run`", start="command", mark="/version",
            get="Install models from its gallery, or `local-ai models install <name>`"),
    _server("textgen", "Text Generation Web UI", "http://127.0.0.1:5000",
            "https://github.com/oobabooga/text-generation-webui", "Start it with `--api`", owner=("user",),
            get="Download models on its Model tab."),
    _server("tabbyapi", "TabbyAPI", "http://127.0.0.1:5000", "https://github.com/theroyallab/tabbyAPI",
            "Run its start script. Its key is in `api_tokens.yml`", owner=("tabbyAPI",), mark="/health",
            get="Put models in its `models` folder"),
    _server("docker", "Docker Model Runner", "http://127.0.0.1:12434", "https://docs.docker.com/ai/model-runner/",
            "Turn it on in Docker Desktop, with host-side TCP.", path="/engines/v1",
            get="Get models with `docker model pull <name>`"),
    _server("vllm", "vLLM", "http://127.0.0.1:8000", "https://docs.vllm.ai",
            "Run `vllm serve <model>`", owner=("vllm",), get="vLLM runs the model it was started with."),
    _server("sglang", "SGLang", "http://127.0.0.1:30000", "https://github.com/sgl-project/sglang",
            "Run `python -m sglang.launch_server --model-path <model>`", owner=("sglang",),
            get="SGLang runs the model it was started with."),
]

DEFAULT_ROOT = KNOWN_SERVERS[0]["root"]


def normalise_base_url(text: str) -> str:
    """Turn whatever someone typed into the OpenAI base URL for that server. People paste "localhost:11434", "http://localhost:11434/" and "http://localhost:11434/v1" interchangeably, and the client needs exactly the last form. Getting this wrong produces a 404 on every single request, which reads like the model is broken rather than like a typo."""
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


def _get(url: str, timeout: float = 2.0, api_key: str = ""):
    headers = {"accept": "application/json"}
    if api_key:
        # A server with a key set wants it here. The rest ignore it.
        headers["authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _models(base_url: str, timeout: float, api_key: str = "") -> tuple:
    """The model ids, and who each says owns it: that second part tells servers apart."""
    data = _get(normalise_base_url(base_url) + "/models", timeout=timeout, api_key=api_key)
    if not isinstance(data, dict):
        raise ValueError("That is not a model server")
    items = [m for m in (data.get("data") or []) if isinstance(m, dict)]
    return sorted(str(m["id"]) for m in items if m.get("id")), [str(m.get("owned_by") or "") for m in items]


def list_models(base_url: str, timeout: float = 4.0, api_key: str = "") -> list:
    """Model ids the server is offering, via the OpenAI /models endpoint. Typing a model name by hand is how you get a 404 on every request months later, so the picker offers what is actually loaded instead."""
    return _models(base_url, timeout, api_key)[0]


def _json_body(error) -> bool:
    try:
        json.loads(error.read().decode("utf-8", "replace"))
        return True
    except Exception:
        return False


def probe(base_url: str, timeout: float = 2.0, api_key: str = "") -> dict:
    """Is something answering there, and what has it got? `locked` is a server that answered but wants a key the app does not have: running, it just will not say what it has. A 403 only counts when it comes with JSON, because on a Mac port 5000 is AirPlay, which answers everything with an empty 403."""
    empty = {"ok": False, "models": [], "owners": [], "locked": False}
    try:
        models, owners = _models(base_url, timeout, api_key)
        return {"ok": True, "models": models, "owners": owners, "locked": False, "error": ""}
    except urllib.error.HTTPError as e:
        if e.code == 401 or (e.code == 403 and _json_body(e)):
            return {**empty, "locked": True, "error": "It answered, but wants an API key."}
        return {**empty, "error": f"HTTP {e.code} from the server"}
    except urllib.error.URLError as e:
        return {**empty, "error": f"Nothing answered ({e.reason})"}
    except Exception as e:
        return {**empty, "error": str(e)}


def _base(server: dict) -> str:
    """Where a known server's OpenAI API is, at its usual address."""
    return normalise_base_url(server["root"] + server["path"])


def _port(url: str):
    try:
        parts = urlsplit(url)
        return parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None


# Which server was last found at an address, so one on a shared port keeps its own name between looks.
_seen: dict = {}


def _remember(url: str, server_id: str) -> str:
    if server_id:
        _seen[normalise_base_url(url)] = server_id
    return server_id


def known(server_id: str):
    """The known server with this id, or None."""
    return next((k for k in KNOWN_SERVERS if k["id"] == server_id), None)


def known_at(base_url: str):
    """The known server at this address: the one last found there, else the one whose port it is (the first, where two share one). None for a port none of them use."""
    url = normalise_base_url(base_url)
    if url in _seen:
        return known(_seen[url])
    port = _port(url)
    return next((k for k in KNOWN_SERVERS if _port(k["root"]) == port), None)


def _answers(url: str, timeout: float, api_key: str = "") -> bool:
    try:
        _get(url, timeout=timeout, api_key=api_key)
        return True
    except Exception:
        return False


def identify(base_url: str, result: dict, timeout: float = 0.6, api_key: str = "") -> str:
    """Which known server answered here, from the probe's result: whose its models say they are, then which of two sharing this port answers its own page, then whose address it is. "" for one that cannot be told."""
    url = normalise_base_url(base_url)
    here = [s for s in KNOWN_SERVERS if _base(s) == url]
    owners = {o for o in result.get("owners") or [] if o}
    for pool in (here, KNOWN_SERVERS):
        for s in pool:
            if owners & set(s["owner"]):
                return _remember(url, s["id"])
    if len(here) > 1:
        root = server_root(url)
        for s in here:
            if s["mark"] and _answers(root + s["mark"], timeout, api_key):
                return _remember(url, s["id"])
    return _remember(url, here[0]["id"]) if here else ""


def _key() -> str:
    try:
        from app.utils.helpers import load_config
        return settings(load_config())["api_key"]
    except Exception:
        return ""


def detect(timeout: float = 0.6, api_key=None) -> list:
    """Which of the known servers are running right now. Deliberately a short timeout on each: this runs behind a page load, and servers that are not installed must not cost a second each. A closed port refuses immediately anyway, but a port that is open and unresponsive, or one being firewalled with a DROP rather than a refuse, waits out the whole timeout. Probing them together bounds that at one timeout rather than one each. Two that share an address are asked once, and told apart by what answered."""
    from concurrent.futures import ThreadPoolExecutor

    key = _key() if api_key is None else api_key
    urls = list(dict.fromkeys(_base(s) for s in KNOWN_SERVERS))
    with ThreadPoolExecutor(max_workers=len(urls) or 1) as pool:
        results = dict(zip(urls, pool.map(lambda u: probe(u, timeout=timeout, api_key=key), urls)))
        answered = [u for u in urls if results[u]["ok"] or results[u]["locked"]]
        who = dict(zip(answered, pool.map(lambda u: identify(u, results[u], timeout, key), answered)))
    out = []
    for server in KNOWN_SERVERS:
        # Where it answered: at its own address, unless that turned out to be
        # another server, or at another's, when its models say it is this one.
        at = next((u for u, sid in who.items() if sid == server["id"]), "")
        result = results[at] if at else {"ok": False, "locked": False, "models": []}
        exe = installed(server["id"])
        out.append({
            **server,
            "root": server_root(at) if at and at != _base(server) else server["root"],
            "running": bool(result["ok"]),
            "locked": bool(result["locked"]),
            "models": result["models"],
            "base_url": at or _base(server),
            "installed": bool(exe),
            "can_start": bool(server["start"]) and bool(exe),
        })
    return out


# ── Pulling a model ───────────────────────────────────────────────────────────

def ollama_name(text: str) -> str:
    """What Ollama should be asked for, given what someone typed. Its own models are bare names with a tag, like "llama3.1:8b". A name with a slash in it is a HuggingFace repo, which Ollama serves GGUF from under the hf.co prefix, so "openai/gpt-oss-20b" becomes "hf.co/openai/gpt-oss-20b". That is the whole reason typing a HuggingFace name works at all."""
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


# One pull at a time, reported the way the picture describer reports its batch: a dict the panel polls, rather than
# a socket it has to stay attached to. More can be asked for while one downloads: they wait their turn in a queue,
# each worked out (which file, does it fit) as it is asked for, so a mistake is said then, not when its turn comes.
_pull = {
    "active": False,
    "model": "",
    "status": "",
    "percent": 0,
    "done": 0,
    "total": 0,
    "error": "",
    "finished_at": 0.0,
    # Asked to stop: the download ends at the next line Ollama sends, or the next block of a file.
    "cancel": False,
    # How the one before ended, so a queue moving straight on to the next does not swallow it: {model, error, at}.
    "last": None,
}
_pull_lock = threading.Lock()
# Waiting their turn: [{"model", "kind": "ollama" | "file", "plan", "base_url"}].
_queue: list = []


def pull_status() -> dict:
    with _pull_lock:
        out = dict(_pull)
        out["queue"] = [{"model": q["model"]} for q in _queue]
        return out


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


def start_pull(model: str, base_url: str, as_typed: bool = False) -> dict:
    """Download a model in the background: through Ollama, which fetches it itself (it streams newline delimited JSON
    for the duration, which is where the progress comes from), or for llama.cpp the app fetches the file
    (_plan_file). A download is minutes long, so this returns straight away and the panel polls pull_status(). One
    asked for while another downloads waits its turn.

    A HuggingFace repo asked for by its name alone gets the model itself, not a helper file HuggingFace may hand over as its default (a draft, the vision part), which Ollama cannot run on its own: see app/utils/localfix.py. `as_typed` is for a name already worked out."""
    kind = "file" if pull_kind(base_url) == "file" else "ollama"
    plan = _plan_file(model, base_url) if kind == "file" else _plan_ollama(model, as_typed)
    if not plan.get("ok"):
        return plan
    job = {"model": plan["model"], "kind": kind, "plan": plan, "base_url": base_url}
    with _pull_lock:
        if (_pull["active"] and _pull["model"] == job["model"]) or any(q["model"] == job["model"] for q in _queue):
            return {"ok": False, "reason": f"{job['model']} is already on its way."}
        if _pull["active"]:
            _queue.append(job)
            return {"ok": True, "model": job["model"], "queued": len(_queue), "warning": plan.get("warning", "")}
        _begin(job)
    return {"ok": True, "model": job["model"], "warning": plan.get("warning", "")}


def _begin(job: dict) -> None:
    """Start one. Called with _pull_lock held."""
    _pull.update({"active": True, "model": job["model"], "status": "starting", "percent": 0, "done": 0,
                  "total": int(job["plan"].get("total") or 0), "error": "", "finished_at": 0.0, "cancel": False})
    run = _run_file if job["kind"] == "file" else _run_ollama
    threading.Thread(target=run, args=(job,), daemon=True, name=f"{job['kind']}-pull").start()


def _finish(name: str) -> None:
    """One ended: said, kept as the last one, and the next in the queue started."""
    with _pull_lock:
        _pull["active"] = False
        _pull["finished_at"] = time.time()
        # `asked` is what it was asked for by, `model` what it is called now it is in (llama.cpp: its file's name).
        _pull["last"] = {"model": _pull["model"] or name, "asked": name, "error": _pull["error"],
                         "cancelled": bool(_pull["cancel"]), "at": time.time()}
        done_as = dict(_pull)
    _models_changed()
    try:
        from app.web.logbus import bus
        if done_as["cancel"]:
            bus.append("local", f"Stopped downloading {name}")
        elif not done_as["error"]:
            bus.append("local", f"{done_as['model'] or name} is ready to use")
    except Exception:
        pass
    with _pull_lock:
        if not _pull["active"] and _queue:
            _begin(_queue.pop(0))


def unqueue(model: str) -> dict:
    """Take one out of the queue before its turn."""
    with _pull_lock:
        before = len(_queue)
        _queue[:] = [q for q in _queue if q["model"] != model]
        return {"ok": len(_queue) < before}


def _plan_ollama(model: str, as_typed: bool) -> dict:
    name = ollama_name(model)
    if not name:
        return {"ok": False, "reason": "No model name given."}
    if not as_typed:
        from app.utils import localfix
        name, why = localfix.for_pull(name)
        if not name:
            return {"ok": False, "reason": why}
    return {"ok": True, "model": name}


def _run_ollama(job: dict) -> None:
    name = job["model"]
    root = server_root(job["base_url"])
    from app.web.logbus import bus
    try:
        body = json.dumps({"model": name, "stream": True}).encode()
        req = urllib.request.Request(
            root + "/api/pull", data=body,
            headers={"content-type": "application/json"}, method="POST")
        bus.append("local", f"Downloading {name}")
        last_logged = 0.0
        # No timeout on the read: the server sends a line every second or so while it works, and a large model takes a long time between them.
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
                # Leaving the loop closes the stream, and Ollama stops when the stream it writes to closes.
                with _pull_lock:
                    if _pull["cancel"]:
                        break
                # One line a minute in the log, not one a second.
                if time.time() - last_logged > 20:
                    last_logged = time.time()
                    bus.append("local", f"{name}: {status}"
                               + (f" {percent}%" if total else ""))
        with _pull_lock:
            if _pull["cancel"]:
                _pull["status"] = "cancelled"
            elif not _pull["error"]:
                _pull["status"] = "ready"
                _pull["percent"] = 100
    except Exception as e:
        _set(error=str(e))
        try:
            bus.append("local", f"Download failed: {e}", "error")
        except Exception:
            pass
    finally:
        _finish(name)


# ── Getting a model for llama.cpp ────────────────────────────────────────────
# llama.cpp has no download of its own that works everywhere (`llama download`
# could not reach Hugging Face on one computer: its own HTTPS gave up), so the
# app fetches the model's file itself, into the folder it starts llama.cpp with
# (app_models_dir), and starts it again so it lists it: it reads the folder only
# as it starts. A model that can see comes with its vision part (mmproj), the
# two in a folder of their own, named as the model: llama.cpp pairs them only
# that way, and without it answers a picture "image input is not supported".

_GB = 1024 ** 3


def pull_kind(base_url: str) -> str:
    """How a model is got for the server at this address: "ollama" (it downloads it itself), "file" (the app
    downloads the file, for llama.cpp), or "" (by hand, in the server's own app)."""
    if pull_supported(base_url):
        return "ollama"
    if server_for(base_url) == "llamacpp" and installed("llamacpp"):
        return "file"
    return ""


def _hf_name(model: str) -> tuple:
    """("org/repo", "QUANT" or "") from what was typed: org/repo, org/repo:Q4_K_M, hf.co/org/repo, a link."""
    name = (model or "").strip()
    for prefix in ("https://huggingface.co/", "http://huggingface.co/", "huggingface.co/", "hf.co/"):
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
    name = name.split("?")[0].strip("/")
    repo, _, tag = name.partition(":")
    parts = [p for p in repo.split("/") if p]
    if len(parts) < 2:
        return "", ""
    return "/".join(parts[:2]), (tag.upper() if tag and tag.lower() != "latest" else "")


def _plan_file(model: str, base_url: str) -> dict:
    """Which files of a Hugging Face repo to fetch for llama.cpp: the model in the size this computer can run, unless
    one was named, and its vision part beside it when the repo has one. {"ok", "model", "repo", "pick", "vision",
    "total"}, or {"ok": False, "reason"}."""
    from app.utils import localfix
    repo, tag = _hf_name(model)
    if not repo:
        return {"ok": False, "reason": "Give it as a Hugging Face repo: user/model, or user/model:Q4_K_M."}
    try:
        files = localfix.repo_files(repo)
    except Exception as e:
        return {"ok": False, "reason": f"Hugging Face did not answer about {repo}: {_net_reason(e)}"}
    models = localfix.model_files(files)
    if not models:
        return {"ok": False, "reason": f"{repo} has no model file llama.cpp can run (a .gguf)."}
    try:
        free = shutil.disk_usage(app_models_dir()).free
    except OSError:
        free = 0
    vision = localfix.mmproj_file(files)
    extra = int(vision["size"]) if vision else 0
    mach = {"ram": localfix._ram(), "vram": localfix._vram(), "free": free - extra}
    warning = ""
    if tag:
        pick = next((f for f in models if f["tag"] == tag), None)
        if not pick:
            return {"ok": False, "reason": f"{repo} has no {tag}. It has {', '.join(sorted({f['tag'] for f in models}))}."}
        if pick["size"] + extra > free - _GB:
            return {"ok": False, "reason": f"Not enough room on the disk: it is {(pick['size'] + extra) / _GB:.1f} GB "
                                           f"and the disk has {max(0, free) / _GB:.1f} GB free."}
        # Asked for by name: fetched, but said plainly when this computer cannot run it at speed.
        if not localfix.fits_memory(pick["size"], mach):
            warning = (f"{tag} needs about {localfix.need(pick['size']) / _GB:.1f} GB of memory and this computer can "
                       f"give a model about {localfix.budget(mach) / _GB:.1f} GB: it will be slow.")
    else:
        picks, why = localfix.choices(files, mach)
        if not picks:
            return {"ok": False, "reason": f"No size of {repo} fits this computer: {why}."}
        pick = picks[0]
    return {"ok": True, "model": f"{repo}:{pick['tag']}", "repo": repo, "pick": pick, "vision": vision,
            "total": int(pick["size"]) + extra, "warning": warning}


def _start_file_pull(model: str, base_url: str) -> dict:
    """A llama.cpp download, by what was typed (kept for its callers: start_pull does the same)."""
    return start_pull(model, base_url)


def _run_file(job: dict) -> None:
    from app.web.logbus import bus
    plan = job["plan"]
    repo, pick, vision = plan["repo"], plan["pick"], plan["vision"]
    folder = app_models_dir()
    stem = os.path.splitext(os.path.basename(pick["name"]))[0]
    # A model that can see goes in a folder of its own, its vision part beside it: llama.cpp pairs the two only so,
    # and names the model after the folder (the same name as the file's).
    home = folder / stem if vision else folder
    target = home / os.path.basename(pick["name"])
    parts = [(pick, target)] + ([(vision, home / os.path.basename(vision["name"]))] if vision else [])
    grand = sum(int(f["size"] or 0) for f, _ in parts)
    label = job["model"]
    try:
        home.mkdir(parents=True, exist_ok=True)
        bus.append("local", f"Downloading {label} for llama.cpp" + (", with its vision part" if vision else ""))
        base_done = 0
        for f, dest in parts:
            size = int(f["size"] or 0)
            if dest.is_file() and size and dest.stat().st_size == size:
                base_done += size          # already here, whole
                continue
            part = dest.with_name(dest.name + ".part")
            _fetch_resuming(f"https://huggingface.co/{repo}/resolve/main/{f['name']}", part, size, label, bus,
                            base_done=base_done, grand=grand)
            with _pull_lock:
                cancelled = _pull["cancel"]
            if cancelled:
                part.unlink(missing_ok=True)
                _set(status="cancelled")
                return
            os.replace(part, dest)
            base_done += size
        # The same model fetched before without its vision part sat loose in the folder: one model, one place.
        loose = folder / os.path.basename(pick["name"])
        if vision and loose.is_file() and loose != target:
            loose.unlink(missing_ok=True)
        _remember_source(stem, repo, pick, vision)
        # Named from here on as llama.cpp lists it (the file's name), which is what is picked under Models.
        _set(status="starting llama.cpp", percent=100, done=grand, model=stem)
        # It lists its folder only as it starts: started again, the new one is there to pick.
        _restart_llama(job["base_url"])
        _set(status="ready")
    except Exception as e:
        # What came down so far is kept: asked for again, it carries on from there.
        why = _net_reason(e)
        _set(error=why)
        bus.append("local", f"Download failed: {why}", "error")
    finally:
        _finish(label)


# Where each file came from, so a model can be looked up again on Hugging Face: something smaller by the same maker
# for one too big for this computer (app/utils/localfix.py), the page it came from.
def _sources_path():
    return app_models_dir() / "sources.json"


def _remember_source(stem: str, repo: str, pick: dict, vision: dict | None) -> None:
    from app.utils.atomic import write_json_atomic
    try:
        data = json.loads(_sources_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[stem] = {"repo": repo, "tag": pick.get("tag", ""), "file": pick.get("name", ""),
                  "vision": (vision or {}).get("name", "")}
    try:
        write_json_atomic(_sources_path(), data, indent=2)
    except OSError:
        pass


def source_of(model: str) -> tuple:
    """("org/repo", "TAG") a llama.cpp model came from: as written down when it was fetched, else found on Hugging
    Face by its name. ("", "") when neither knows."""
    try:
        data = json.loads(_sources_path().read_text(encoding="utf-8"))
        hit = data.get(model) if isinstance(data, dict) else None
        if isinstance(hit, dict) and hit.get("repo"):
            return str(hit["repo"]), str(hit.get("tag") or "")
    except (OSError, ValueError):
        pass
    m = re.match(r"^(.*?)[-_.]((?:I?Q\d(?:_[A-Z0-9]+)*)|BF16|F16|F32)$", model or "", re.I)
    name, tag = (m.group(1), m.group(2).upper()) if m else (model or "", "")
    if not name:
        return "", ""
    try:
        from urllib.parse import quote
        from app.utils import localfix
        found = localfix._hf_get(f"https://huggingface.co/api/models?search={quote(name)}&limit=10", timeout=10.0)
    except Exception:
        return "", ""
    for item in found if isinstance(found, list) else []:
        rid = str(item.get("id") or item.get("modelId") or "")
        if rid.split("/", 1)[-1].lower().removesuffix("-gguf") == name.lower():
            return rid, tag
    return "", ""


def file_model_path(model: str, base_url: str = "") -> str:
    """The file of a model llama.cpp runs: in the app's folder (loose, or in a folder of its own with its vision part),
    else wherever its router says it is. "" when not found."""
    if not model or any(c in model for c in "/\\:") or model.startswith("."):
        return ""
    folder = app_models_dir()
    loose = folder / f"{model}.gguf"
    if loose.is_file():
        return str(loose)
    own = folder / model
    if own.is_dir():
        main = [f for f in own.glob("*.gguf") if not re.search(r"mmproj|projector", f.name, re.I)]
        if main:
            return str(max(main, key=lambda f: f.stat().st_size))
    if base_url:
        try:
            data = _get(normalise_base_url(base_url) + "/models", timeout=2.0)
            for item in data.get("data") or []:
                if item.get("id") == model:
                    args = ((item.get("status") or {}).get("args")) or []
                    if "--model" in args:
                        return str(args[args.index("--model") + 1])
        except Exception:
            pass
    return ""


def file_sizes() -> dict:
    """{model: bytes} for every model in the app's folder, its vision part counted with it."""
    out = {}
    try:
        folder = app_models_dir()
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() == ".gguf" and not re.search(r"mmproj|projector", p.name, re.I):
                out[p.stem] = p.stat().st_size
            elif p.is_dir() and not p.name.startswith("."):
                files = list(p.glob("*.gguf"))
                if files:
                    out[p.name] = sum(f.stat().st_size for f in files)
    except OSError:
        pass
    return out


# A connection that drops is tried again this many times in a row (any progress starts the count over), a little
# longer apart each time. One computer had Hugging Face cut about every other connection as it opened.
_FETCH_TRIES = 8


def _fetch_resuming(url: str, part, expected: int, label: str, bus, base_done: int = 0, grand: int = 0) -> None:
    """A big file down into `part`, carrying on from where it stopped: after a dropped connection, and from what an
    earlier try left. Stops early when the pull is cancelled. `base_done` and `grand` count it as one part of a
    download of several files (a model and its vision part), so the progress is the whole of it."""
    done = part.stat().st_size if part.exists() else 0
    if expected and done > expected:
        part.unlink()
        done = 0
    total, misses, last_logged = expected, 0, 0.0

    def show():
        whole = grand or total
        got = base_done + done
        _set(done=got, total=whole, percent=int(got * 100 / whole) if whole else 0)

    while True:
        headers = {"user-agent": "LLMSelfbot"}
        if done:
            headers["range"] = f"bytes={done}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                if done and r.status != 206:
                    # Asked to carry on, it sent the whole file instead: start the file over.
                    done = 0
                length = int(r.headers.get("content-length") or 0)
                total = (done + length) if length else (total or expected)
                _set(status="downloading")
                show()
                with open(part, "ab" if done else "wb") as out:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        misses = 0
                        show()
                        with _pull_lock:
                            if _pull["cancel"]:
                                return
                        if time.time() - last_logged > 20:
                            last_logged = time.time()
                            whole = grand or total
                            bus.append("local", f"{label}: {int((base_done + done) * 100 / whole) if whole else 0}%")
            if not total or done >= total:
                return
            # The answer ended short of the whole file: asked again for the rest.
            raise ConnectionResetError("the download stopped part way")
        except urllib.error.HTTPError as e:
            if e.code == 416 and done:
                return  # it has the whole file already
            if e.code not in (408, 429, 500, 502, 503, 504):
                raise
            err = e
        except (OSError, http.client.HTTPException) as e:
            err = e
        with _pull_lock:
            if _pull["cancel"]:
                return
        misses += 1
        if misses > _FETCH_TRIES:
            raise err
        _set(status="reconnecting")
        time.sleep(min(1.5 * misses, 8))


def _net_reason(e: Exception) -> str:
    """A download failure in plain words."""
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return "Hugging Face won't hand that one out without signing in (it's gated)."
        if e.code == 404:
            return "Hugging Face doesn't have that file."
        return f"Hugging Face answered {e.code}."
    reason = getattr(e, "reason", e)
    text = str(reason)
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError)) or "10054" in text or "10053" in text:
        return "The connection to Hugging Face kept dropping. Try again: it carries on from where it stopped."
    if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in text:
        return "Hugging Face stopped answering. Try again: it carries on from where it stopped."
    if isinstance(reason, socket.gaierror) or "getaddrinfo" in text:
        return "Couldn't reach Hugging Face. Is this computer online?"
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "The disk is full."
    return text


def _running_llama() -> list:
    """PIDs of llama.cpp's server: `llama serve`, or the older llama-server."""
    if sys.platform != "win32":
        return []
    try:
        from app.utils.procs import quiet_kwargs
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'llama.exe' -and $_.CommandLine -match ' serve') "
             "-or $_.Name -eq 'llama-server.exe' } | ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=20, **quiet_kwargs())
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def _restart_llama(base_url: str) -> dict:
    """llama.cpp started again the app's way, on the app's models folder."""
    from app.utils.procs import quiet_kwargs
    for pid in _running_llama():
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, timeout=15,
                           **quiet_kwargs())
        except Exception:
            pass
    deadline = time.time() + 10
    while time.time() < deadline and probe(base_url, timeout=0.8)["ok"]:
        time.sleep(0.4)
    return start_server("llamacpp", base_url)


def delete_file_model(model: str, base_url: str) -> dict:
    """A model the app downloaded for llama.cpp, off the disk (its vision part with it), and llama.cpp started again
    without it."""
    if not model or any(c in model for c in "/\\:") or model.startswith("."):
        return {"ok": False, "reason": "That model is not in the app's models folder."}
    folder = app_models_dir()
    hits = [p for p in folder.glob("*.gguf") if p.stem == model or p.name == model]
    own = folder / model
    if not hits and not own.is_dir():
        return {"ok": False, "reason": "That model is not in the app's models folder."}
    for p in hits:
        p.unlink(missing_ok=True)
    if own.is_dir():
        shutil.rmtree(own, ignore_errors=True)
    _models_changed()
    threading.Thread(target=_restart_llama, args=(base_url,), daemon=True, name="llama-restart").start()
    try:
        from app.web.logbus import bus
        bus.append("local", f"Removed {model}")
    except Exception:
        pass
    return {"ok": True}


def cancel_pull() -> dict:
    """Stop the download under way. What came down is kept, so asking for the same model again carries on from there.
    The queue moves on to the next."""
    with _pull_lock:
        if not _pull["active"]:
            return {"ok": False, "reason": "Nothing is downloading."}
        _pull["cancel"] = True
        _pull["status"] = "stopping"
    return {"ok": True}


# ── Starting a server ─────────────────────────────────────────────────────────
#
# A local server that is installed but not running was a dead end: the panel
# said "not answering" and you had to go and start it yourself. Ollama, LM
# Studio, llama.cpp and LocalAI can be started from a command, so the app does
# it from a button, and Ollama and LM Studio on their own at launch when
# something is set to run on them. Jan, GPT4All and KoboldCpp are apps with the
# server as a setting inside, so the button opens them. vLLM and the rest need a
# model and flags only the person running them knows.

import glob
import os
import shutil
import subprocess
import sys

_start = {"active": "", "error": "", "at": 0.0}
_start_lock = threading.Lock()


def _newest_first(paths) -> list:
    def mtime(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0
    return sorted(paths, key=mtime, reverse=True)


def _koboldcpp(home: str) -> list:
    """KoboldCpp is one file, run from wherever it was downloaded to."""
    found = []
    for folder in (os.path.join(home, "Downloads"), os.path.join(home, "Desktop"), home):
        for path in glob.glob(os.path.join(folder, "koboldcpp*")):
            name = os.path.basename(path).lower()
            if sys.platform == "win32" and not name.endswith(".exe"):
                continue
            # Its saved launch settings sit beside it, named the same way.
            if name.endswith((".kcpps", ".kcppt", ".json", ".txt", ".zip")) or not os.access(path, os.X_OK):
                continue
            found.append(path)
    return [shutil.which("koboldcpp") or ""] + _newest_first(found)


def _candidates(server_id: str) -> list:
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    programs = os.environ.get("ProgramFiles") or r"C:\Program Files"
    if server_id == "ollama":
        return [shutil.which("ollama") or "",
                os.path.join(local, "Programs", "Ollama", "ollama.exe"),
                "/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
                "/Applications/Ollama.app/Contents/Resources/ollama"]
    if server_id == "lmstudio":
        return [shutil.which("lms") or "",
                os.path.join(home, ".lmstudio", "bin", "lms.exe"),
                os.path.join(home, ".lmstudio", "bin", "lms"),
                os.path.join(home, ".cache", "lm-studio", "bin", "lms.exe"),
                os.path.join(home, ".cache", "lm-studio", "bin", "lms")]
    if server_id == "llamacpp":
        # winget puts it on the PATH through its Links folder, which a process
        # started before the install does not see yet. The all-in-one `llama`
        # (`llama serve`) comes first: installed from the Store it is an alias
        # in WindowsApps, and looking only for llama-server said "not installed".
        return [shutil.which("llama") or "",
                os.path.join(local, "Microsoft", "WindowsApps", "llama.exe"),
                os.path.join(local, "Microsoft", "WinGet", "Links", "llama.exe"),
                shutil.which("llama-server") or "",
                os.path.join(local, "Microsoft", "WinGet", "Links", "llama-server.exe"),
                "/opt/homebrew/bin/llama-server", "/usr/local/bin/llama-server"]
    if server_id == "localai":
        return [shutil.which("local-ai") or "", "/usr/local/bin/local-ai", "/opt/homebrew/bin/local-ai"]
    if server_id == "jan":
        return [os.path.join(local, "Jan", "Jan.exe"), os.path.join(local, "Programs", "Jan", "Jan.exe"),
                os.path.join(programs, "Jan", "Jan.exe"), "/Applications/Jan.app/Contents/MacOS/Jan",
                shutil.which("jan") or ""]
    if server_id == "gpt4all":
        return [os.path.join(home, "gpt4all", "bin", "chat.exe"), os.path.join(programs, "gpt4all", "bin", "chat.exe"),
                "/Applications/gpt4all/bin/gpt4all.app/Contents/MacOS/gpt4all",
                os.path.join(home, "gpt4all", "bin", "chat")]
    if server_id == "koboldcpp":
        return _koboldcpp(home)
    if server_id == "vllm":
        return [shutil.which("vllm") or ""]
    return []


def is_llama_cli(exe: str) -> bool:
    """The all-in-one `llama` (`llama serve`, `llama download`), not the older `llama-server`. Its name read past
    either kind of slash: a Windows path is the same program whatever system reads it."""
    name = re.split(r"[\\/]", exe or "")[-1]
    return os.path.splitext(name)[0].lower() == "llama"


def app_models_dir():
    """Where the app keeps the model files it downloads for a server that reads a folder (llama.cpp)."""
    from app.utils.paths import DATA_DIR
    folder = DATA_DIR / "models"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def installed(server_id: str) -> str:
    """The program that starts this server, or "" when it is not installed."""
    for path in _candidates(server_id):
        if path and os.path.isfile(path):
            return path
    return ""


def server_for(base_url: str) -> str:
    """Which known server lives at this address: the one last found there, else by its port. Ollama by default."""
    k = known_at(base_url)
    return k["id"] if k else "ollama"


def server_name(server_id: str) -> str:
    k = known(server_id)
    return k["name"] if k else ""


def can_start(server_id: str) -> bool:
    """Whether the app can bring this server up here: it knows how, and it is installed."""
    k = known(server_id)
    return bool(k and k["start"] and installed(server_id))


def start_word(server_id: str) -> str:
    """What the button that brings it up says: an app is opened, a server started."""
    k = known(server_id)
    return "Open" if k and k["start"] == "app" else "Start"


def _plain(hint: str) -> str:
    return hint.replace("`", "")


def start_status() -> dict:
    with _start_lock:
        return dict(_start)


def starting() -> bool:
    return bool(start_status()["active"])


def _argv(server_id: str, exe: str, base_url: str, env: dict) -> list:
    """The command that brings this server up at this address."""
    where = server_root(base_url).split("://", 1)[-1]
    host, _, port = where.rpartition(":")
    if server_id == "ollama":
        # Ollama listens where OLLAMA_HOST says; match the address the app is set to use.
        env["OLLAMA_HOST"] = where
        # And give models room to work. Ollama's default window is 4096
        # tokens, and a persona of a few pages is that on its own before a
        # single message: every reply failed "request exceeds the available
        # context size". Someone who set it themselves keeps their value.
        if not os.environ.get("OLLAMA_CONTEXT_LENGTH"):
            env["OLLAMA_CONTEXT_LENGTH"] = str(context_length())
        return [exe, "serve"]
    if server_id == "lmstudio":
        return [exe, "server", "start"]
    if server_id == "llamacpp":
        # With no model named, a recent llama-server starts as a router: it
        # lists the models it has downloaded and loads whichever one a request
        # asks for, each with the room set here. The all-in-one `llama` is the
        # same server as `llama serve`, and reads the app's own models folder,
        # where the downloads from This computer go (it lists that folder as it
        # starts, so a new one there has it started again).
        argv = [exe, "--host", host or "127.0.0.1", "--port", port or "8080", "--ctx-size", str(context_length())]
        if is_llama_cli(exe):
            argv[1:1] = ["serve"]
            argv += ["--models-dir", str(app_models_dir())]
        return argv
    if server_id == "localai":
        return [exe, "run", "--address", f"{host}:{port}"]
    # An app: open it, window and all.
    return [exe]


def start_server(server_id: str = "", base_url: str = "", wait: float = 25.0) -> dict:
    """Start a server the app knows how to start, and wait until it answers. Blocking: call it on a thread.

    A "command" server is started detached and without a window, so it keeps
    running on its own like it would from its own tray icon, and closing the app
    does not take the models down with it mid-reply. An "app" server is opened,
    window and all: its API is a setting inside it, so this waits a little for
    it and otherwise says where that setting is.
    """
    base_url = normalise_base_url(base_url or DEFAULT_ROOT)
    server_id = server_id or server_for(base_url)
    entry = known(server_id)
    if not entry:
        return {"ok": False, "reason": "That server cannot be started from here."}
    # A button for one server, pressed while the app is set to use another:
    # start it where it lives, not where the other one does.
    if server_for(base_url) != server_id:
        base_url = _base(entry)
    name, kind = entry["name"], entry["start"]
    if probe(base_url, timeout=1.5)["ok"]:
        return {"ok": True, "already": True, "server": server_id, "name": name}
    exe = installed(server_id)
    if not kind:
        return {"ok": False, "server": server_id, "name": name,
                "reason": f"{name} needs a model and settings to start, so start it yourself."}
    if not exe:
        return {"ok": False, "server": server_id, "name": name, "not_installed": True,
                "site": entry["site"], "reason": f"{name} is not installed on this computer."}

    with _start_lock:
        if _start["active"]:
            return {"ok": False, "server": server_id, "name": name, "reason": f"Already starting {_start['active']}."}
        _start.update(active=name, error="", at=time.time())
    try:
        env = dict(os.environ)
        argv = _argv(server_id, exe, base_url, env)
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                  "stderr": subprocess.DEVNULL, "env": env, "close_fds": True}
        if sys.platform == "win32":
            # A hidden console, not none at all. It was started DETACHED_PROCESS
            # (which also cancels CREATE_NO_WINDOW), so Ollama had no console, and
            # every model runner it spawns to load a model got a brand new,
            # visible one: a terminal window opening in your face each time. With
            # a hidden console its children inherit that and stay hidden too. Its
            # own process group keeps it from getting the app's Ctrl+C, so it
            # still outlives the app like it would from its tray icon.
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(argv, **kwargs)
        # An app only answers once its server is switched on inside it, so it
        # gets a shorter wait before being told where that is.
        deadline = time.time() + (min(wait, 15.0) if kind == "app" else wait)
        while time.time() < deadline:
            time.sleep(0.6)
            if probe(base_url, timeout=1.0)["ok"]:
                try:
                    from app.web.logbus import bus
                    bus.append("local", f"{'Opened' if kind == 'app' else 'Started'} {name}", "system")
                except Exception:
                    pass
                return {"ok": True, "server": server_id, "name": name}
            # Gone with an error: it is not coming up, so there is no point
            # waiting out the rest. An older llama-server without a model does
            # this. A clean exit is fine: `lms server start` hands the server to
            # LM Studio and returns, and an app already open passes the click on.
            code = getattr(proc, "poll", lambda: None)()
            if code not in (None, 0):
                reason = f"{name} stopped as it started (exit code {code})."
                if server_id == "llamacpp":
                    reason += " An older llama-server needs a model: llama-server -m <model.gguf>."
                _set_start_error(reason)
                return {"ok": False, "server": server_id, "name": name, "reason": reason}
        if kind == "app":
            return {"ok": False, "opened": True, "server": server_id, "name": name,
                    "reason": f"{name} is open. {_plain(entry['hint']).rstrip('.')}, then look again."}
        reason = f"{name} was started but did not answer within {int(wait)} seconds."
        _set_start_error(reason)
        return {"ok": False, "server": server_id, "name": name, "reason": reason}
    except Exception as e:
        reason = f"Could not start {name}: {e}"
        _set_start_error(reason)
        return {"ok": False, "server": server_id, "name": name, "reason": reason}
    finally:
        with _start_lock:
            _start["active"] = ""


def context_length(config: dict | None = None) -> int:
    """How many tokens of context the app gives Ollama when it starts it."""
    if config is None:
        try:
            from app.utils.helpers import load_config
            config = load_config()
        except Exception:
            config = {}
    return settings(config)["context_length"]


def _running_serves(server_id: str) -> list:
    """PIDs of the server processes to stop for a restart: Ollama's `serve`, not its tray app."""
    if sys.platform != "win32" or server_id != "ollama":
        return []
    try:
        from app.utils.procs import quiet_kwargs
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='ollama.exe'\" | "
             "Where-Object { $_.CommandLine -match ' serve' } | ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=20, **quiet_kwargs())
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def restart_server(server_id: str = "", base_url: str = "") -> dict:
    """Stop Ollama's server and start it again the app's way (hidden, with the
    context length above). For a server that was started some other way with
    too small a window. Blocking: call it on a thread."""
    base_url = normalise_base_url(base_url or DEFAULT_ROOT)
    server_id = server_id or server_for(base_url)
    if server_id != "ollama":
        return {"ok": False, "reason": "Only Ollama can be restarted from here."}
    from app.utils.procs import quiet_kwargs
    for pid in _running_serves(server_id):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True,
                           timeout=15, **quiet_kwargs())
        except Exception:
            pass
    deadline = time.time() + 10
    while time.time() < deadline and probe(base_url, timeout=0.8)["ok"]:
        time.sleep(0.4)
    result = start_server(server_id, base_url)
    if result.get("already"):
        result["reason"] = ("Ollama came straight back on its own, probably from its tray app, so the new "
                            "context length could not be applied. Quit Ollama from the tray, then start it here.")
    return result


def _set_start_error(reason: str):
    with _start_lock:
        _start["error"] = reason
    try:
        from app.web.logbus import bus
        bus.append("local", reason, "warn")
    except Exception:
        pass


def _on_this_computer(base_url: str) -> bool:
    try:
        host = (urlsplit(normalise_base_url(base_url)).hostname or "").lower()
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _installed_instead() -> dict | None:
    """The first server on this computer the app can start by itself, hidden (llama.cpp, LM Studio, LocalAI), for an
    address that has nothing installed behind it. Not an app: opening a window no one asked for is not a start."""
    return next((k for k in KNOWN_SERVERS if k["start"] == "command" and installed(k["id"])), None)


def _uses_local(config: dict) -> bool:
    try:
        from app.utils import providers
        plan = providers.plan(config)
    except Exception:
        return False
    return any(e["provider"] == "local" for e in plan["replies"]) or \
        any(plan[j]["provider"] == "local" for j in providers.JOBS)


def autostart(config: dict) -> dict | None:
    """At launch, the local server started, so the first reply finds it up and the panel does not open on "not
    answering". Any the app knows how to bring up: Ollama, LM Studio, llama.cpp and LocalAI hidden, and one that is
    an app (Jan, KoboldCpp) opened. Off with bot.local.autostart: false.

    Ollama's address is the one every config starts with, so Ollama is started for it only when a job runs on it;
    any other address was picked, and its server starts. Left at Ollama's with Ollama not installed, the app moves
    to the first server here it can start (llama.cpp, say) instead of leaving that one sitting idle."""
    cfg = settings(config)
    if not cfg["autostart"] or not _on_this_computer(cfg["base_url"]):
        return None
    base = cfg["base_url"]
    sid = server_for(base)
    entry = known(sid)
    if not (entry and entry["start"] and installed(sid)):
        alt = _installed_instead() if base == normalise_base_url(DEFAULT_ROOT) else None
        if not alt:
            return None
        base = _base(alt)
        _save_base_url(base)
        try:
            from app.web.logbus import bus
            bus.append("local", f"{entry['name'] if entry else 'The server'} isn't installed: using {alt['name']}",
                       "system")
        except Exception:
            pass
        return start_server(alt["id"], base)
    if base == normalise_base_url(DEFAULT_ROOT) and not _uses_local(config):
        return None
    return start_server(sid, base)


def _save_base_url(base: str) -> None:
    """bot.local.base_url set to this, the way the panel's own Save does."""
    import copy
    from app.utils.helpers import load_config
    from app.web.routes.config_routes import _write_config
    cfg = copy.deepcopy(load_config())
    cfg.setdefault("bot", {}).setdefault("local", {})["base_url"] = base
    _write_config(cfg)


# ── Where a model is ──────────────────────────────────────────────────────────
# The model list was a row of names. Each one now opens where it came from on the
# web, and can be shown on this computer: the file is often tens of gigabytes,
# and "where did that go" is the first question when the disk fills up.

import re

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def _hf(org: str, repo: str) -> dict:
    return {"url": f"https://huggingface.co/{org}/{repo}", "site": "Hugging Face"}


def _hf_search(text: str) -> dict:
    from urllib.parse import quote
    return {"url": "https://huggingface.co/models?search=" + quote(text[:120], safe=""), "site": "Hugging Face"}


def _looks_like_path(name: str) -> bool:
    return ("\\" in name or name.startswith(("/", "~", "."))
            or bool(re.match(r"^[A-Za-z]:", name)) or name.lower().endswith(".gguf"))


def model_page(model: str, server: str = "ollama") -> dict:
    """The model's page on the web, worked out from its name alone: the Hugging Face repo it came from, or its page in Ollama's library. A name that says no more than a file does gets a Hugging Face search for it, which is one click from the right page. Only ever huggingface.co or ollama.com, with the name checked to be a plain repo name, so this cannot be made to point anywhere else."""
    name = (model or "").strip()
    if not name:
        return {}
    lowered = name.lower()
    for prefix in ("hf.co/", "huggingface.co/"):
        if lowered.startswith(prefix):
            parts = name[len(prefix):].split(":", 1)[0].split("/")
            if len(parts) >= 2 and _SEGMENT.match(parts[0]) and _SEGMENT.match(parts[1]):
                return _hf(parts[0], parts[1])
            return _hf_search(name[len(prefix):])
    if _looks_like_path(name):
        stem = re.split(r"[\\/]", name)[-1]
        stem = re.sub(r"\.gguf$", "", stem, flags=re.I)
        return _hf_search(stem) if stem else {}
    base = name.split(":", 1)[0]
    if server == "koboldcpp" and lowered.startswith("koboldcpp/"):
        # KoboldCpp names a model after its file.
        stem = re.sub(r"\.gguf$", "", name.split("/", 1)[1], flags=re.I)
        return _hf_search(stem) if stem else {}
    if server == "docker":
        # Docker's own models live on Docker Hub, as ai/<name>.
        ref = base[len("docker.io/"):] if base.lower().startswith("docker.io/") else base
        parts = ref.split("/")
        if len(parts) == 2 and all(_SEGMENT.match(x) for x in parts):
            return {"url": f"https://hub.docker.com/r/{parts[0]}/{parts[1]}", "site": "Docker Hub"}
        return {}
    if server == "gpt4all":
        # Named for people ("Llama 3 8B Instruct"), which a search finds.
        return _hf_search(base) if base.strip() else {}
    if server == "ollama":
        for prefix in ("registry.ollama.ai/", "ollama.com/"):
            if base.lower().startswith(prefix):
                base = base[len(prefix):]
        parts = base.split("/")
        if len(parts) == 2 and parts[0] == "library":
            parts = parts[1:]
        if len(parts) == 1 and _SEGMENT.match(parts[0]):
            return {"url": f"https://ollama.com/library/{parts[0]}", "site": "Ollama"}
        if len(parts) == 2 and all(_SEGMENT.match(x) for x in parts):
            return {"url": f"https://ollama.com/{parts[0]}/{parts[1]}", "site": "Ollama"}
        return {}
    # vLLM serves a model by its Hugging Face name, and llama.cpp's -hf does the
    # same with a quant after a colon. LM Studio's own names are close to one.
    parts = base.split("/")
    if len(parts) >= 2 and _SEGMENT.match(parts[0]) and _SEGMENT.match(parts[1]):
        return _hf(parts[0], parts[1])
    return _hf_search(base) if _SEGMENT.match(base) else {}


def ollama_models(base_url: str, timeout: float = 1.5):
    """{name: {size, params, quant, family}} for every model Ollama has, or None when nothing Ollama-shaped answers there. None rather than {} is what says "this is not Ollama": the same call is how the panel knows it can offer downloads. How big a model is (8B) and how it is squeezed (Q4_K_M) are what decide whether it fits a machine, and Ollama says both."""
    try:
        data = _get(server_root(base_url) + "/api/tags", timeout=timeout)
    except Exception:
        return None
    out = {}
    for m in data.get("models") or []:
        name = m.get("name") or m.get("model")
        if not name:
            continue
        details = m.get("details") or {}
        out[name] = {
            "size": int(m.get("size") or 0),
            "params": str(details.get("parameter_size") or ""),
            "quant": str(details.get("quantization_level") or ""),
            "family": str(details.get("family") or ""),
        }
    return out


def ollama_sizes(base_url: str, timeout: float = 1.5):
    """{name: bytes} for every model Ollama has, or None when it is not Ollama."""
    info = ollama_models(base_url, timeout)
    return None if info is None else {name: m["size"] for name, m in info.items()}


def ollama_loaded(base_url: str, timeout: float = 1.0) -> dict:
    """{name: bytes held in memory} for the models Ollama has loaded right now. A loaded model answers at once; the first request to one that is not waits while it is read off the disk. {} when none are, or it is not Ollama."""
    try:
        data = _get(server_root(base_url) + "/api/ps", timeout=timeout)
    except Exception:
        return {}
    out = {}
    for m in data.get("models") or []:
        name = m.get("name") or m.get("model")
        if name:
            out[name] = int(m.get("size_vram") or m.get("size") or 0)
    return out


def delete_model(model: str, base_url: str) -> dict:
    """Remove a model from Ollama, and the gigabytes it takes. Only Ollama can: the other servers use files you put there yourself."""
    req = urllib.request.Request(
        server_root(base_url) + "/api/delete",
        data=json.dumps({"model": model, "name": model}).encode(),
        headers={"content-type": "application/json"}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        return {"ok": False, "reason": "Ollama does not have that model." if e.code == 404
                else f"Ollama would not remove it ({e.code})."}
    except Exception as e:
        return {"ok": False, "reason": f"Could not reach Ollama: {e}"}
    _models_changed()
    try:
        from app.web.logbus import bus
        bus.append("local", f"Removed {model}")
    except Exception:
        pass
    return {"ok": True}


def _models_changed() -> None:
    """The server's model list is not what the pickers were told any more."""
    try:
        from app.utils import providers
        providers.forget("local")
    except Exception:
        pass


def _norm(text: str) -> str:
    """A name reduced to letters and digits, without the words that only say it is a GGUF or which quant."""
    t = re.sub(r"[^a-z0-9]", "", (text or "").lower())
    t = re.sub(r"gguf$", "", t)
    return re.sub(r"(i?q\d(k[sml]|k|0|1|xs|xxs|s|m|l|nl)*|f16|bf16|f32)$", "", t)


def _largest(paths) -> str:
    best, size = "", -1
    for path in paths:
        try:
            n = os.path.getsize(path)
        except OSError:
            continue
        if n > size:
            best, size = path, n
    return best


def _ollama_file(model: str, base_url: str) -> str:
    """Ollama keeps the weights as a blob named by its hash; /api/show names the file. A model with a vision part lists two, and the weights are the big one."""
    body = json.dumps({"model": model, "name": model}).encode()
    req = urllib.request.Request(server_root(base_url) + "/api/show", data=body,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return ""
    paths = []
    for line in (data.get("modelfile") or "").splitlines():
        if line.startswith("FROM "):
            path = line[5:].strip().strip('"')
            if os.path.isfile(path):
                paths.append(path)
    return _largest(paths)


def _search_dirs(dirs, model: str, depth: int = 3) -> str:
    """The model file under one of these folders whose name matches the model's, or its folder."""
    want = _norm(re.split(r"[\\/]", model.split(":", 1)[0].split("@", 1)[0])[-1])
    if len(want) < 3:
        return ""
    fallback = ""
    for root in dirs:
        if not root or not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for here, subdirs, files in os.walk(root):
            if here.count(os.sep) - base_depth >= depth:
                subdirs[:] = []
            weights = [os.path.join(here, f) for f in files if f.lower().endswith((".gguf", ".safetensors"))
                       and not f.lower().startswith("mmproj")]
            for f in weights:
                if _norm(os.path.splitext(os.path.basename(f))[0]) == want:
                    return f
            if weights and not fallback and _norm(os.path.basename(here)) == want:
                fallback = _largest(weights)
    return fallback


def _lmstudio_dirs() -> list:
    home = os.path.expanduser("~")
    dirs = []
    try:
        with open(os.path.join(home, ".lmstudio", "settings.json"), encoding="utf-8") as fh:
            folder = (json.load(fh) or {}).get("downloadsFolder")
            if folder:
                dirs.append(folder)
    except Exception:
        pass
    return dirs + [os.path.join(home, ".lmstudio", "models"), os.path.join(home, ".cache", "lm-studio", "models")]


def _jan_dirs() -> list:
    home = os.path.expanduser("~")
    roaming = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    data = [os.path.join(roaming, "Jan", "data"), os.path.join(home, "Library", "Application Support", "Jan", "data"),
            os.path.join(home, ".local", "share", "Jan", "data")]
    return [os.path.join(d, "llamacpp", "models") for d in data] + [os.path.join(home, "jan", "models")]


def _gpt4all_dir() -> str:
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    for folder in (os.path.join(local, "nomic.ai", "GPT4All"),
                   os.path.join(home, "Library", "Application Support", "nomic.ai", "GPT4All"),
                   os.path.join(home, ".local", "share", "nomic.ai", "GPT4All")):
        if os.path.isdir(folder):
            return folder
    return ""


def _hf_cache_dirs() -> list:
    home = os.path.expanduser("~")
    hf = os.environ.get("HF_HOME") or os.path.join(home, ".cache", "huggingface")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    return [os.path.join(hf, "hub"), os.path.join(local, "llama.cpp"), os.path.join(home, ".cache", "llama.cpp")]


def model_file(model: str, base_url: str) -> str:
    """Where this model's weights are on this computer, or "" when that cannot be known. Ollama says so itself. LM Studio, llama.cpp and vLLM keep files under folders of their own, which are searched by name; a server started on a file by path names it outright."""
    name = (model or "").strip()
    if not name:
        return ""
    server = server_for(base_url)
    if server == "ollama":
        return _ollama_file(name, base_url)
    if _looks_like_path(name):
        path = os.path.expanduser(name)
        return path if os.path.exists(path) else ""
    if server == "lmstudio":
        return _search_dirs(_lmstudio_dirs(), name)
    if server == "jan":
        return _search_dirs(_jan_dirs(), name)
    if server == "gpt4all":
        # Its names are for people, not files, so the folder they are all in is the best answer.
        folder = _gpt4all_dir()
        return (_search_dirs([folder], name) or folder) if folder else ""
    if server == "koboldcpp":
        stem = name.split("/", 1)[1] if name.lower().startswith("koboldcpp/") else name
        home = os.path.expanduser("~")
        return _search_dirs([os.path.join(home, d) for d in ("Downloads", "Desktop", "Documents", "models")], stem)
    if server == "vllm":
        parts = name.split(":", 1)[0].split("/")
        if len(parts) == 2:
            folder = os.path.join(_hf_cache_dirs()[0], f"models--{parts[0]}--{parts[1]}")
            if os.path.isdir(folder):
                return folder
    return _search_dirs(_hf_cache_dirs(), name, depth=4)


def show_in_folder(path: str) -> None:
    """Open the file manager on this file, selected, or on this folder."""
    from app.utils.procs import quiet_kwargs
    if not path or '"' in path or not os.path.exists(path):
        raise FileNotFoundError(path)
    if sys.platform == "win32":
        if os.path.isdir(path):
            os.startfile(path)  # noqa: S606
        else:
            # One string, not a list: explorer reads /select, and the quoted path as one argument.
            subprocess.Popen(f'explorer /select,"{path}"', **quiet_kwargs())
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path], **quiet_kwargs())
    else:
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)], **quiet_kwargs())


# ── What the rest of the app asks ─────────────────────────────────────────────

def settings(config: dict) -> dict:
    """The local block, with every default filled in. Read through one function so a config written before this feature existed behaves exactly like one that turned it off, rather than raising KeyError somewhere deep in a reply."""
    bot = (config or {}).get("bot") or {}
    local = bot.get("local") or {}
    return {
        "enabled": bool(local.get("enabled", False)),
        "base_url": normalise_base_url(local.get("base_url") or DEFAULT_ROOT),
        "model": (local.get("model") or "").strip(),
        # Some servers want any non-empty string, and reject a blank one.
        "api_key": (local.get("api_key") or "local").strip() or "local",
        "vision": bool(local.get("vision", False)),
        # One server, several jobs. Groq was the only thing that could read an image, hear a voice note or speak, which meant "run it locally" still needed a Groq key for any account that used those. Each is opt-in by naming a model: an OpenAI-compatible server that does not implement /audio/speech simply has no tts_model set, and that capability keeps going to Groq instead of failing.
        "vision_model": (local.get("vision_model") or "").strip(),
        "stt_model": (local.get("stt_model") or "").strip(),
        "tts_model": (local.get("tts_model") or "").strip(),
        "tts_voice": (local.get("tts_voice") or "").strip(),
        # The local server started with the app (autostart).
        "autostart": bool(local.get("autostart", True)),
        # The context window Ollama gets when the app starts it, in tokens.
        "context_length": max(2048, min(262144, int(local.get("context_length") or 16384))),
    }


def active(config: dict) -> bool:
    """True when replies should be generated locally rather than by Groq."""
    cfg = settings(config)
    return cfg["enabled"] and bool(cfg["model"])
