"""When a local model will not load, and what the app does about it.

Ollama answered every reply with "llama-server process has terminated: exit
status 1: error loading model: check_tensor_dims: tensor 'output.weight' has
wrong shape; expected 5120, 248320, got 5120, 32768, 1, 1". That is Ollama
starting a file that is not a model on its own. The usual way to end up with
one: a HuggingFace repo holding the model in several sizes beside helper files,
a draft model for speculative decoding ("MTP", "draft") or the vision part of
the model ("mmproj"), downloaded by its name alone. Ollama then asks
HuggingFace for "latest", and when no file is named the way Ollama's default is
(Q4_K_M), HuggingFace hands over the first one, which can be the draft: 1.9B
parameters under a name that says 27B. Every reply failed the same way, a few
seconds each, and the log filled with the same error.

What happens now:
  - A model that will not load is left alone for ten minutes, not one, and the
    log says why once, in words (app/utils/ai.py), not on every message.
  - The panel looks at what the file really is (Ollama's /api/show). A helper
    file is replaced by the model itself, in the best size this computer has
    room for, and every setting that named the helper names the model instead.
  - Downloading a repo by its name alone gets the model itself to begin with
    (start_pull asks for_pull).
  - With no room for any size of it, it says how much is needed and downloads
    nothing.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from app.utils import localai

GB = 1024 ** 3

# How long a model that would not load is left alone: it will not load a minute later either.
REST = 600.0

_LOAD_FAILED = re.compile(
    r"error loading model|failed to load model|check_tensor_dims|has wrong shape|missing tensor|"
    r"unknown model architecture|unsupported model architecture|(llama-server|llama runner) process has terminated",
    re.I)


def load_failure(error) -> bool:
    """Whether a local server's error says the model itself will not load, rather than that the server is busy or down."""
    return bool(_LOAD_FAILED.search(str(error or "")))


def reason(error) -> str:
    """What a load failure means, in a few words."""
    text = str(error or "").lower()
    if "unknown model architecture" in text or "unsupported model architecture" in text:
        return "this version of Ollama does not know this kind of model yet"
    if "out of memory" in text or "cudamalloc" in text or "failed to allocate" in text or "more system memory" in text:
        return "there is not enough memory for it"
    if "wrong shape" in text or "missing tensor" in text or "check_tensor_dims" in text:
        return "the file is not a whole model, or not one this server can read"
    return "the server could not load it"


def _gb(n: int) -> str:
    return f"{n / GB:.1f} GB"


# ── Reported by a reply ───────────────────────────────────────────────────────
# The replies are written in the account processes; the fixing is done by the
# panel's, where downloads are shown. A failure is handed over as a file.

def _marker():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "local_wont_load.json"


def note_failure(model: str, base_url: str, error) -> None:
    """A reply found this model will not load: written down for the panel to look into."""
    try:
        path = _marker()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"model": model, "base_url": base_url, "error": str(error)[:600],
                                   "at": time.time()}), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


# ── What the file really is ───────────────────────────────────────────────────

_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*([BM])\b", re.I)


def _billions(text) -> float:
    m = _SIZE.search(str(text or ""))
    if not m:
        return 0.0
    n = float(m.group(1))
    return n / 1000 if m.group(2).upper() == "M" else n


def inspect(model: str, base_url: str, timeout: float = 15.0) -> dict | None:
    """What a model on Ollama really is; None when it is not Ollama there, or it does not have the model.

    `helper` is a file that is not a model on its own: the vision part of one, or a draft for speculative
    decoding. The file says so itself: its type, or how many parameters it has against the size its name gives
    (a 1.9B "27B"). Not by the words "MTP" or "draft" in its tags alone: those are the repo's, and the model
    itself carries them too."""
    req = urllib.request.Request(localai.server_root(base_url) + "/api/show",
                                 data=json.dumps({"model": model}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    info = data.get("model_info") or {}
    details = data.get("details") or {}
    has = float(info.get("general.parameter_count") or 0) / 1e9 or _billions(details.get("parameter_size"))
    said = _billions(info.get("general.size_label"))
    words = str(info.get("general.description") or "").lower()
    kind = ""
    if str(info.get("general.type") or "").lower() == "mmproj" or str(info.get("general.architecture") or "") == "clip":
        kind = "vision"
    elif (has and said and has < said / 3) or (not said and re.search(r"\bdraft\b", words)):
        kind = "draft"
    return {"helper": bool(kind), "kind": kind, "has": has, "said": said,
            "name": str(info.get("general.basename") or info.get("general.name") or "")}


def what(kind: str) -> str:
    return "the vision part of a model" if kind == "vision" else "a draft model, a small helper for a bigger one"


# ── The model itself, on HuggingFace ──────────────────────────────────────────

def hf_repo(model: str) -> tuple:
    """("org/repo", "tag") for "hf.co/org/repo:tag" (the tag "latest" when there is none); ("", "") otherwise."""
    name = (model or "").strip()
    low = name.lower()
    for prefix in ("hf.co/", "huggingface.co/"):
        if low.startswith(prefix):
            repo, _, tag = name[len(prefix):].partition(":")
            if repo.count("/") == 1:
                return repo, tag or "latest"
    return "", ""


def _hf_get(url: str, timeout: float = 20.0, accept: str = "application/json", tries: int = 4):
    """JSON from HuggingFace. It drops the connection now and then on a few quick requests in a row (WinError
    10054), so that is tried again after a moment; an answer it gives (a 400, a 404) is not."""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"accept": accept, "user-agent": "LLMSelfbot"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == tries - 1:
                raise
            time.sleep(0.8 * (attempt + 1))


def repo_files(repo: str) -> list:
    """Every file in a HuggingFace repo, with its size: [{"name", "size"}]."""
    data = _hf_get(f"https://huggingface.co/api/models/{repo}?blobs=true")
    return [{"name": s["rfilename"], "size": int(s.get("size") or 0)}
            for s in data.get("siblings") or [] if s.get("rfilename")]


# The sizes HuggingFace hands Ollama by name (hf.co/<repo>:<tag>), the 4-bit ones in the order it prefers them. A
# repo's own names it refuses: "Q4_K_P" answers "The specified tag is not a valid quantization scheme".
QUANTS = ("Q4_K_M", "Q4_K_S", "IQ4_XS", "IQ4_NL", "Q4_0", "Q4_1",
          "Q5_K_M", "Q5_K_S", "Q5_0", "Q5_1", "Q6_K", "Q8_0",
          "Q3_K_L", "Q3_K_M", "IQ3_M", "IQ3_S", "Q3_K_S", "IQ3_XS", "IQ3_XXS",
          "Q2_K", "Q2_K_S", "IQ2_M", "IQ2_S", "IQ2_XS", "IQ2_XXS", "IQ1_M", "IQ1_S",
          "BF16", "F16", "F32")
_TAG = re.compile(r"[-_.]((?:I?Q\d(?:_[A-Z0-9]+)*)|BF16|F16|F32)\.gguf$", re.I)
# Never the model itself: the vision part, a draft, the data a quant was made with, one part of a split file.
_NOT_MODEL = re.compile(r"mmproj|projector|draft|imatrix|-of-\d{3,}", re.I)


def model_files(files: list) -> list:
    """The repo's files that are the model itself, in a size that can be asked for by name: [{"name", "size", "tag"}]."""
    out = []
    for f in files:
        name = f["name"]
        if not name.lower().endswith(".gguf") or _NOT_MODEL.search(name):
            continue
        m = _TAG.search(name)
        if m and m.group(1).upper() in QUANTS:
            out.append({"name": name, "size": int(f.get("size") or 0), "tag": m.group(1).upper()})
    return out


_VISION_PREF = ("f16", "q8_0", "bf16", "f32")


def mmproj_file(files: list) -> dict | None:
    """The model's vision part, when the repo has one: without it a model that can see answers a picture with
    "image input is not supported". F16 first (every build reads it), then the smallest."""
    parts = [f for f in files if f["name"].lower().endswith(".gguf") and re.search(r"mmproj|projector", f["name"], re.I)]
    if not parts:
        return None

    def rank(f):
        low = f["name"].lower()
        pref = next((i for i, p in enumerate(_VISION_PREF) if re.search(rf"[-_.]{p}\.gguf$", low)), len(_VISION_PREF))
        return (pref, int(f.get("size") or 0))
    return min(parts, key=rank)


def model_size(model: str, base_url: str) -> int:
    """How big a model in use on this computer is: Ollama's own list says, else llama.cpp's file."""
    info = localai.ollama_models(base_url)
    if info is not None:
        return int(((info.get(model) or {}).get("size")) or 0)
    path = localai.file_model_path(model, base_url)
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def too_big(model: str, base_url: str, mach: dict | None = None) -> dict | None:
    """A model in use that this computer has no room to run at speed, and how far off it is; None when it fits (or
    its size is not known)."""
    size = model_size(model, base_url)
    if not size:
        return None
    mach = mach if mach is not None else machine()
    room = budget(mach)
    if not room or need(size) <= room:
        return None
    return {"model": model, "size": size, "need": need(size), "budget": room}


def too_big_words(big: dict) -> str:
    """Why it is so slow, in a line."""
    return (f"it needs about {_gb(big['need'])} of memory and this computer can give a model about "
            f"{_gb(big['budget'])}, so it runs from the disk and a reply takes minutes")


def _ram() -> int:
    if sys.platform == "win32":
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = _Status()
        st.dwLength = ctypes.sizeof(_Status)
        try:
            return int(st.ullTotalPhys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)) else 0
        except Exception:
            return 0
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0


_vram_seen = {"at": 0.0, "value": 0}


def _vram() -> int:
    """The biggest NVIDIA card's memory, from nvidia-smi; 0 without one, and the model runs from RAM. Asked once in
    ten minutes: the card does not change, and the health check asks every few seconds."""
    if _vram_seen["at"] and time.time() - _vram_seen["at"] < 600:
        return _vram_seen["value"]
    exe = shutil.which("nvidia-smi")
    value = 0
    if exe:
        from app.utils.procs import quiet_kwargs
        try:
            out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5, **quiet_kwargs()).stdout
            value = max((int(float(x)) for x in out.split() if x.strip()), default=0) * 1024 * 1024
        except Exception:
            value = 0
    _vram_seen.update(at=time.time(), value=value)
    return value


# ── Room to run in ────────────────────────────────────────────────────────────
# A model answers at speed only while all of it sits in memory, the graphics card's and the RAM. The RAM is not all
# its own: Windows, the browser Snapchat runs in and whatever else is open take about half. Past that the computer
# pages the model to the disk as it answers and a reply takes minutes: a 14.4 GB model on a 16 GB computer did, the
# computer had 0.1 GB free, and every reply gave up waiting ("the runner did not respond"). On top of the file comes
# the room for the conversation it reads (its context) and for the work.

def budget(mach: dict) -> int:
    """The memory a model can run in here: most of the graphics card's and about half the RAM. 0 when unknown."""
    ram, vram = int(mach.get("ram") or 0), int(mach.get("vram") or 0)
    if not ram:
        return 0
    return int(vram * 0.85 + ram * 0.5)


def need(size: int) -> int:
    """What a model file takes to run: itself, the room for the conversation and the work."""
    return int(int(size or 0) * 1.1 + 1.5 * GB)


def fits_memory(size: int, mach: dict) -> bool:
    room = budget(mach)
    return not room or need(size) <= room


def models_dir() -> str:
    """Where Ollama keeps what it downloads."""
    return os.environ.get("OLLAMA_MODELS") or os.path.join(os.path.expanduser("~"), ".ollama", "models")


def machine() -> dict:
    """What this computer has room for: memory, the graphics card's, and the disk Ollama downloads to."""
    where = models_dir()
    try:
        free = shutil.disk_usage(where if os.path.isdir(where) else os.path.expanduser("~")).free
    except OSError:
        free = 0
    return {"ram": _ram(), "vram": _vram(), "free": free}


def choices(files: list, mach: dict) -> tuple:
    """The sizes of the model this computer can take, best first, or ([], why not).

    One fits when it goes on the disk with 2 GB to spare, and runs in the memory this computer can give a model
    (budget, need: the file, plus the room for the conversation, in most of the graphics card's memory and about
    half the RAM). Best is a 4-bit one, the usual balance of quality and speed and Ollama's own default, in the order
    HuggingFace prefers them; without one that fits, the biggest that does."""
    models = model_files(files)
    if not models:
        return [], "the repo has no file of it that Ollama can be given"
    disk = mach.get("free", 0) - 2 * GB
    fits = [f for f in models if f["size"] <= disk and fits_memory(f["size"], mach)]
    if not fits:
        small = min(models, key=lambda f: f["size"])
        if small["size"] > disk:
            return [], (f"its smallest size is {_gb(small['size'])} and the disk has "
                        f"{_gb(max(0, mach.get('free', 0)))} free")
        return [], (f"its smallest size is {_gb(small['size'])} and needs about {_gb(need(small['size']))} of memory "
                    f"to run, more than the {_gb(budget(mach))} this computer can give it")
    four = sorted((f for f in fits if f["tag"].lstrip("I").startswith("Q4")), key=lambda f: QUANTS.index(f["tag"]))
    rest = sorted((f for f in fits if f not in four), key=lambda f: -f["size"])
    return four + rest, ""


def resolves(repo: str, tag: str, size: int) -> bool:
    """Whether HuggingFace hands Ollama that very file for that tag: its model layer is the file's size."""
    try:
        data = _hf_get(f"https://huggingface.co/v2/{repo}/manifests/{tag}",
                       accept="application/vnd.docker.distribution.manifest.v2+json")
    except Exception:
        return False
    for layer in data.get("layers") or []:
        if str(layer.get("mediaType") or "").endswith(".model"):
            return abs(int(layer.get("size") or 0) - size) <= max(1, size // 50)
    return False


def _best(repo: str, files: list) -> tuple:
    """(the file to get, "") or (None, why not)."""
    picks, why = choices(files, machine())
    for f in picks[:4]:
        if resolves(repo, f["tag"], f["size"]):
            return f, ""
    return None, why or "HuggingFace would not hand over any size of it by name"


def for_pull(name: str) -> tuple:
    """What a download should ask Ollama for: (name, "") or ("", why not).

    A repo by its name alone is asked for as "latest", which is whatever HuggingFace picks. When that is not one of
    the model's own files (a draft, the vision part), the best size this computer has room for is asked for by name
    instead. Anything else is left exactly as typed."""
    repo, tag = hf_repo(name)
    if not repo or tag.lower() != "latest":
        return name, ""
    try:
        files = repo_files(repo)
        manifest = _hf_get(f"https://huggingface.co/v2/{repo}/manifests/latest",
                           accept="application/vnd.docker.distribution.manifest.v2+json")
    except Exception:
        return name, ""          # HuggingFace not answering: Ollama will ask it itself, as before
    size = next((int(l.get("size") or 0) for l in manifest.get("layers") or []
                 if str(l.get("mediaType") or "").endswith(".model")), 0)
    if any(abs(f["size"] - size) <= max(1, size // 50) for f in model_files(files)):
        return name, ""
    pick, why = _best(repo, files)
    if not pick:
        return "", f"Its default file is not the model itself, and the model does not fit: {why}."
    return f"hf.co/{repo}:{pick['tag']}", ""


# ── Something smaller by the same maker ───────────────────────────────────────
# A model with no size this computer has room for is no use however it is fixed. The same maker often has the same
# kind of model smaller (HauhauCS's Qwen 27B "Uncensored Aggressive" comes at 9B, 4B and 2B too): the closest of
# those that fits is offered, one click away, never switched to unasked.

_SIZE_WORD = re.compile(r"\d+(\.\d+)?|[a-z]?\d+(\.\d+)?[bm]|a\d+b|gguf|mtp|qat|draft|v\d+(\.\d+)*")


def _flavour(name: str) -> set:
    """The words of a repo's name that say what kind of model it is, its size, version and packaging left out:
    {"qwen3", "uncensored", "hauhaucs", "aggressive"}."""
    return {w for w in re.split(r"[-_. /]+", (name or "").lower()) if w and not _SIZE_WORD.fullmatch(w)}


def alternatives(repo: str, mach: dict, room_back: int = 0, look_at: int = 8) -> list:
    """The maker's other models of the same kind this computer has room for, best first: [{"model", "repo", "tag",
    "size", "label"}]. Best is the closest kind, then one in a 4-bit size (a bigger model squeezed to 2 bits answers
    worse than a smaller one at 4), then the most parameters. `room_back` is disk that switching frees: the file that
    does not load goes first."""
    author, _, name = (repo or "").partition("/")
    if not author or not name:
        return []
    try:
        listed = _hf_get(f"https://huggingface.co/api/models?author={author}&limit=200")
    except Exception:
        return []
    mine = _flavour(name)
    near = []
    for m in listed if isinstance(listed, list) else []:
        rid = str(m.get("id") or m.get("modelId") or "")
        if not rid or rid == repo or "/" not in rid:
            continue
        score = len(mine & _flavour(rid.split("/", 1)[1]))
        if score >= max(2, len(mine) - 1):
            near.append((score, _billions(rid.split("/", 1)[1]), rid))
    room = dict(mach, free=mach.get("free", 0) + max(0, room_back))
    out = []
    for score, params, rid in sorted(near, key=lambda x: (-x[0], -x[1]))[:look_at]:
        try:
            picks, _ = choices(repo_files(rid), room)
        except Exception:
            continue
        if not picks:
            continue
        best = picks[0]
        out.append({"model": f"hf.co/{rid}:{best['tag']}", "repo": rid, "tag": best["tag"], "size": best["size"],
                    "label": rid.split("/", 1)[1], "_rank": (score, best["tag"].lstrip("I").startswith("Q4"), params)})
    out.sort(key=lambda a: a["_rank"], reverse=True)
    return [{k: v for k, v in a.items() if k != "_rank"} for a in out]


# ── Fixing it ─────────────────────────────────────────────────────────────────

# Where the fixing is, for the panel: "" (nothing), "checking", "fixing" (downloading the model itself), "fixed" or
# "stuck" (with why, and `alt`: something smaller by the same maker that fits, when there is one).
_state = {"model": "", "state": "", "why": "", "to": "", "at": 0.0, "alt": None}
_state_lock = threading.Lock()
_busy = threading.Lock()


def status() -> dict:
    with _state_lock:
        return dict(_state)


def _say(state: str, model: str, why: str = "", to: str = "", log: str = "", level: str = "info", alt=None):
    with _state_lock:
        _state.update(model=model, state=state, why=why, to=to, at=time.time(), alt=alt)
    if log:
        try:
            from app.web.logbus import bus
            bus.append("local", log, level)
        except Exception:
            pass


def switch(old: str, new: str) -> int:
    """Every setting that names the old model names the new one: the reply chain, every job and its fallbacks, and
    the local server's own model settings. How many there were."""
    from app.utils.helpers import load_config
    cfg = copy.deepcopy(load_config())
    bot = cfg.get("bot") or {}
    n = 0
    for value in (bot.get("models") or {}).values():
        for e in value if isinstance(value, list) else [value]:
            if isinstance(e, dict) and e.get("provider") == "local" and e.get("model") == old:
                e["model"] = new
                n += 1
    local = bot.get("local") or {}
    for k in ("model", "vision_model", "stt_model", "tts_model"):
        if local.get(k) == old:
            local[k] = new
            n += 1
    if n:
        from app.web.routes.config_routes import _write_config
        _write_config(cfg)
    # And every persona that names it in its own settings.
    return n + _in_personas(old, new)


def drop(model: str) -> list:
    """A model removed from the server is named by no setting any more: taken out of the reply chain and every
    job's list (one left with nothing goes back to its default), and out of the local server's own model settings.
    Kept, every reply that tried it failed, a warning said it was missing, and the only reply model could not be
    taken off in the panel. What it is said about it here is forgotten too. The jobs it was taken out of."""
    from app.utils.helpers import load_config
    cfg = copy.deepcopy(load_config())
    bot = cfg.setdefault("bot", {})
    models = dict(bot.get("models") or {})
    jobs = []
    for name in list(models):
        value = models[name]
        items = value if isinstance(value, list) else [value]
        kept = [e for e in items
                if not (isinstance(e, dict) and e.get("provider") == "local" and e.get("model") == model)]
        if len(kept) == len(items):
            continue
        jobs.append(name)
        if not kept:
            models.pop(name)
        else:
            models[name] = kept if isinstance(value, list) or len(kept) > 1 else kept[0]
    local = dict(bot.get("local") or {})
    for k in ("model", "vision_model", "stt_model", "tts_model"):
        if local.get(k) == model:
            local[k] = ""
            jobs.append({"model": "replies", "vision_model": "vision", "stt_model": "stt", "tts_model": "tts"}[k])
    # Replies on this computer only while a model there still writes them.
    if not any(isinstance(e, dict) and e.get("provider") == "local" for e in models.get("replies") or []):
        local["enabled"] = False
    with _state_lock:
        if _state.get("model") == model:
            _state.update(model="", state="", why="", to="", at=time.time(), alt=None)
    # And the note a failed reply left about it: read again later, it would say it all over.
    try:
        path = _marker()
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("model") == model:
            path.unlink(missing_ok=True)
    except Exception:
        pass
    jobs = list(dict.fromkeys(jobs))
    if jobs:
        bot["models"] = models
        bot["local"] = local
        from app.web.routes.config_routes import _write_config
        _write_config(cfg)
    # A persona naming it in its own settings lets go of it too.
    _in_personas(model, None)
    return jobs


_LOCAL_MODEL_KEYS = ("bot.local.model", "bot.local.vision_model", "bot.local.stt_model", "bot.local.tts_model")


def _swap(value, old: str, new):
    """A models value (one job's entry, a list of them, or every job's) with the local model `old` as `new`, or
    taken out (new None; a job left with nothing goes, back to its default)."""
    if isinstance(value, dict) and "provider" in value:
        if value.get("provider") == "local" and value.get("model") == old:
            return None if new is None else {**value, "model": new}
        return value
    if isinstance(value, list):
        return [x for x in (_swap(v, old, new) for v in value) if x is not None]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            got = _swap(v, old, new)
            if got is not None and got != []:
                out[k] = got
        return out
    return value


def _in_personas(old: str, new) -> int:
    """Every persona's own settings that name the local model `old`: `new` in its place, or (None) taken out. How many
    personas changed."""
    try:
        from app.utils import personas
    except Exception:
        return 0
    n = 0
    for pid in personas.ids():
        ov = dict(personas.overrides(pid))
        changed = False
        for key in list(ov):
            if key == "bot.models" or key.startswith("bot.models."):
                got = _swap(ov[key], old, new)
            elif key in _LOCAL_MODEL_KEYS and ov[key] == old:
                got = new or ""
            else:
                continue
            if got != ov[key]:
                ov[key] = got
                changed = True
        if changed:
            personas.set_overrides(pid, ov)
            n += 1
    return n


# What the last download asked for here was called once in: llama.cpp names a model after its file, not after the
# repo and size it was asked for by.
_last_pulled: dict = {}


def _wait_for_pull(name: str, base_url: str, give_up: float) -> str:
    """Download through the panel's own downloader (so it shows there), in the queue behind any already under way. ""
    once it is in, otherwise why not."""
    _last_pulled.clear()
    t0 = time.time()
    started = localai.start_pull(name, base_url, as_typed=True)
    if not started.get("ok"):
        return started.get("reason") or "the download did not start"
    want = started.get("model") or name
    while True:
        last = localai.pull_status().get("last") or {}
        if last.get("at", 0) >= t0 and last.get("asked") == want:
            break
        if time.time() > give_up:
            return "the download took too long"
        time.sleep(3)
    if last.get("cancelled"):
        return "the download was stopped"
    if last.get("error"):
        return last["error"]
    _last_pulled.update(asked=want, model=last.get("model") or want)
    return ""


def _remove(model: str, base_url: str) -> None:
    """A model off this computer: Ollama's, or llama.cpp's file."""
    if localai.pull_kind(base_url) == "file":
        localai.delete_file_model(model, base_url)
    else:
        localai.delete_model(model, base_url)


def offer_smaller(model: str, base_url: str, big: dict) -> dict:
    """A model in use too big for this computer: said, with something smaller by the same maker that fits offered,
    one click away (use_alt). Never switched to unasked."""
    if not _busy.acquire(blocking=False):
        return status()
    try:
        kind = localai.pull_kind(base_url)
        repo, _ = hf_repo(model)
        if not repo and kind == "file":
            repo, _ = localai.source_of(model)
        alt = None
        if repo:
            try:
                # The room the big one gives back on the disk counts: it goes first.
                found = alternatives(repo, machine(), room_back=big["size"])
            except Exception:
                found = []
            # Ollama is handed a size by name, which HuggingFace has to resolve; llama.cpp is given the file itself.
            alt = next((a for a in found if kind == "file" or resolves(a["repo"], a["tag"], a["size"])), None)
        offer = (f" A smaller one by the same maker fits: {alt['label']} ({alt['tag']}, {_gb(alt['size'])}). "
                 f"Switch to it on This computer, in Settings, Models.") if alt else ""
        _say("stuck", model, f"it is too big for this computer: {too_big_words(big)}", alt=alt,
             log=f"{model} is too big for this computer: {too_big_words(big)}.{offer}", level="warn")
    finally:
        _busy.release()
    return status()


def repair(model: str, base_url: str, error: str = "") -> dict:
    """Look into a model that will not load, and fix what can be fixed. One at a time."""
    if not _busy.acquire(blocking=False):
        return status()
    try:
        return _repair(model, base_url, error)
    finally:
        _busy.release()


def _repair(model: str, base_url: str, error: str) -> dict:
    _say("checking", model)
    info = inspect(model, base_url)
    if info is None or not info["helper"]:
        why = reason(error) if error else "it would not load"
        tip = " Updating Ollama may fix it." if "version" in why or "read" in why else ""
        _say("stuck", model, why, log=f"{model} will not load: {why}.{tip}", level="warn")
        return status()
    part = what(info["kind"])
    repo, _ = hf_repo(model)
    if not repo:
        _say("stuck", model, f"the file is {part}, not the model itself",
             log=f"{model} will not load: the file is {part}, not the model itself. Download the model itself.",
             level="warn")
        return status()
    try:
        files = repo_files(repo)
    except Exception as e:
        _say("stuck", model, f"the file is {part}, and HuggingFace could not be asked for the model ({e})",
             log=f"{model} is {part}, not the model. HuggingFace did not answer, trying again later.", level="warn")
        return status()
    pick, why = _best(repo, files)
    if not pick:
        # Something smaller by the same maker that fits, counting the room the useless file gives back: offered.
        held = ((localai.ollama_models(base_url) or {}).get(model) or {}).get("size") or 0
        alt = next((a for a in alternatives(repo, machine(), held) if resolves(a["repo"], a["tag"], a["size"])), None)
        offer = (f" A smaller one by the same maker fits: {alt['label']} ({alt['tag']}, {_gb(alt['size'])}). "
                 f"Switch to it on This computer, in Settings, Models.") if alt else ""
        _say("stuck", model, f"the file is {part}, and the model itself does not fit: {why}", alt=alt,
             log=f"{model} will not load: Ollama downloaded {part}, not the model. The model itself does not "
                 f"fit on this computer: {why}.{offer}", level="warn")
        return status()
    new = f"hf.co/{repo}:{pick['tag']}"
    if new not in (localai.ollama_models(base_url) or {}):
        _say("fixing", model, f"downloading the model itself, {pick['tag']}, {_gb(pick['size'])}", new,
             log=f"{model} will not load: Ollama downloaded {part}, not the model. Downloading the model itself "
                 f"({pick['tag']}, {_gb(pick['size'])}), then replies use it.", level="warn")
        failed = _wait_for_pull(new, base_url, time.time() + 6 * 3600)
        if failed:
            _say("stuck", model, f"the model itself could not be downloaded: {failed}",
                 log=f"Could not download {new}: {failed}.", level="warn")
            return status()
    again = inspect(new, base_url)
    if again is not None and again["helper"]:
        _say("stuck", model, "that file is not the model either",
             log=f"{new} is not the model itself either. Pick another size under Models.", level="warn")
        return status()
    changed = switch(model, new)
    # Of no use on its own, and gigabytes on the disk.
    localai.delete_model(model, base_url)
    _say("fixed", model, "", new,
         log=f"Fixed: {new} is the model itself, and the {changed} setting{'s' if changed != 1 else ''} that "
             f"named the broken one use it now.")
    return status()


def use_alt(base_url: str) -> dict:
    """The smaller model offered for one that does not fit, asked for from the panel: the useless file removed (its
    room is part of what makes the other fit), the other downloaded through the panel's own downloader, so it shows
    there, and every setting that named the old one names it. On a thread: it is gigabytes."""
    st = status()
    alt, model = st.get("alt"), st.get("model")
    if st.get("state") != "stuck" or not alt or not model:
        return {"ok": False, "reason": "There is nothing to switch to."}
    if not _busy.acquire(blocking=False):
        return {"ok": False, "reason": "Already busy with it."}

    def run():
        try:
            _remove(model, base_url)
            _say("fixing", model, f"downloading {alt['label']}, {_gb(alt['size'])}", alt["model"], alt=alt,
                 log=f"Switching to {alt['label']} ({alt['tag']}, {_gb(alt['size'])}): {model} is removed, it is "
                     f"downloaded, then replies use it.")
            failed = _wait_for_pull(alt["model"], base_url, time.time() + 6 * 3600)
            if failed:
                _say("stuck", model, f"{alt['label']} could not be downloaded: {failed}", alt=alt,
                     log=f"Could not download {alt['model']}: {failed}.", level="warn")
                return
            # llama.cpp calls it by its file's name, Ollama by the name it was asked for.
            new = _last_pulled.get("model") or alt["model"]
            changed = switch(model, new)
            _say("fixed", model, "", new,
                 log=f"Switched: {alt['label']} replies now, in the {changed} setting{'s' if changed != 1 else ''} "
                     f"that named {model}.")
        except Exception as e:
            _say("stuck", model, f"switching failed: {e}", alt=alt, log=f"Switching to {alt['label']} failed: {e}",
                 level="warn")
        finally:
            _busy.release()

    threading.Thread(target=run, name="local-alt", daemon=True).start()
    return {"ok": True}


def configured(config: dict) -> list:
    """The local models the settings use: everyone's, and every persona's own (a model named only in one persona's
    settings is in use too)."""
    out = []
    sets = [config]
    try:
        from app.utils import configstore
        sets += [eff for pid, eff in configstore.all_effective() if pid]
    except Exception:
        pass
    for cfg in sets:
        bot = (cfg or {}).get("bot") or {}
        for value in (bot.get("models") or {}).values():
            for e in value if isinstance(value, list) else [value]:
                if isinstance(e, dict) and e.get("provider") == "local" and e.get("model"):
                    out.append(str(e["model"]))
        local = bot.get("local") or {}
        out += [str(local[k]) for k in ("model", "vision_model") if local.get(k)]
    return list(dict.fromkeys(out))


def check_configured(config: dict, models: list | None = None) -> None:
    """The models in use, looked at: a helper file taken for a model is fixed before a reply trips on it, and one too
    big for this computer is said, with something smaller offered."""
    base = localai.settings(config)["base_url"]
    for model in (models if models is not None else configured(config)):
        info = inspect(model, base)
        if info and info["helper"]:
            repair(model, base)
            continue
        big = too_big(model, base)
        if big:
            offer_smaller(model, base, big)


def watch(load_config, every: float = 15.0) -> None:
    """The panel's side, on a thread of its own from start: the models in use once, then whatever a reply reports
    (note_failure). The same model again is only looked into once it has rested."""
    seen, looked = 0.0, {}
    try:
        # A note left before this start is old news: the models in use are looked at just below anyway. Read again at
        # every start, a note about a model removed since put "will not load" back on This computer each time.
        path = _marker()
        if path.exists():
            seen = path.stat().st_mtime
    except Exception:
        pass
    try:
        config = load_config()
        check_configured(config)
        # Just looked at: a note a reply left before the start does not have it looked at (and said) again.
        looked = {model: time.time() for model in configured(config)}
    except Exception:
        pass
    while True:
        time.sleep(every)
        # A model too big for this computer with nothing smaller found for it yet: looked for again every few
        # minutes. Hugging Face drops connections now and then, and the first look, as the app starts, found nothing.
        try:
            st = status()
            if (st.get("state") == "stuck" and not st.get("alt") and str(st.get("why") or "").startswith("it is too big")
                    and time.time() - float(st.get("at") or 0) > 300 and st.get("model") in configured(load_config())):
                check_configured(load_config(), [st["model"]])
        except Exception:
            pass
        # A model newly put to use (picked under Models, downloaded and used) is looked at too, once.
        try:
            now_used = configured(load_config())
            fresh = [m for m in now_used if m not in looked]
            if fresh:
                for m in fresh:
                    looked[m] = time.time()
                check_configured(load_config(), fresh)
        except Exception:
            pass
        try:
            path = _marker()
            if not path.exists():
                continue
            at = path.stat().st_mtime
            if at <= seen:
                continue
            seen = at
            note = json.loads(path.read_text(encoding="utf-8"))
            model, base = str(note.get("model") or ""), str(note.get("base_url") or "")
            if not model or not base or time.time() - looked.get(model, 0) < REST:
                continue
            # About a model no setting uses any more (removed, or swapped for another): nothing to fix, nothing to say.
            if model not in configured(load_config()):
                continue
            looked[model] = time.time()
            repair(model, base, str(note.get("error") or ""))
        except Exception:
            continue
