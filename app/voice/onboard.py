"""This computer's own voice: hearing and speaking with no server and no key.

llama.cpp, which runs the models on this computer, neither hears nor speaks, so a call on This computer still sent
its audio out. This hears with Whisper and speaks with Supertonic, in this process, through sherpa-onnx. None of it
comes with the app (the engine is 20 MB and each model over 100 MB, and most people never use them): the engine comes
from PyPI and the models from sherpa-onnx's own releases, into the data folder, when they are asked for under Calls.

Kokoro and Piper were tried first and left out: this engine's builds have no espeak-ng any more, without which
Kokoro drops every word it does not know and Piper says nothing at all. Supertonic reads the text itself.

Not on phones: the engine has no build for them (app/utils/compat.py says so).
"""
import array
import asyncio
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from app.utils.paths import DATA_DIR

ENGINE = ("sherpa-onnx", "sherpa-onnx-core")
ENGINE_VERSION = "2.0.1"
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
PYPI = "https://pypi.org/pypi"
# A model on This computer that is this engine's rather than a server's: "builtin:whisper-base".
PREFIX = "builtin:"

MODELS = {
    "whisper-tiny": {"job": "stt", "name": "Whisper tiny", "about": "quick, any language", "mb": 116,
                     "url": f"{RELEASES}/asr-models/sherpa-onnx-whisper-tiny.tar.bz2",
                     "folder": "sherpa-onnx-whisper-tiny"},
    "whisper-base": {"job": "stt", "name": "Whisper base", "about": "more accurate, any language", "mb": 208,
                     "url": f"{RELEASES}/asr-models/sherpa-onnx-whisper-base.tar.bz2",
                     "folder": "sherpa-onnx-whisper-base"},
    "supertonic-3": {"job": "tts", "name": "Supertonic 3", "about": "10 voices, many languages", "mb": 129,
                     "url": f"{RELEASES}/tts-models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2",
                     "folder": "sherpa-onnx-supertonic-3-tts-int8-2026-05-11"},
}

# Supertonic's ten voices, by the number it knows them by. Told apart here by their pitch, measured.
VOICES = [("F1", 0, "woman"), ("F2", 1, "woman, higher"), ("F3", 2, "woman, lower"), ("F4", 3, "woman"),
          ("F5", 4, "woman, lower"), ("M1", 5, "man"), ("M2", 6, "man, deep"), ("M3", 7, "man"), ("M4", 8, "man"),
          ("M5", 9, "man, deep")]

# Let go of a model this long after it was last used: they hold a few hundred MB each.
IDLE_S = 900


def home() -> Path:
    return DATA_DIR / "voice"


def engine_dir() -> Path:
    return home() / "engine"


def models_dir() -> Path:
    return home() / "models"


def is_builtin(model: str) -> bool:
    return str(model or "").startswith(PREFIX)


def _key(model: str) -> str:
    return str(model or "")[len(PREFIX):] if is_builtin(model) else str(model or "")


def supported() -> bool:
    from app.utils import device
    return not device.is_phone()


def engine_ready() -> bool:
    return (engine_dir() / "sherpa_onnx" / "__init__.py").is_file() and (engine_dir() / "sherpa_onnx" / "lib").is_dir()


def model_ready(key: str) -> bool:
    spec = MODELS.get(_key(key))
    return bool(spec) and (models_dir() / spec["folder"] / ".ready").is_file()


def installed(job: str = "") -> list:
    """The models that are here and can be used: ["builtin:whisper-base", ...]."""
    if not engine_ready():
        return []
    return [PREFIX + k for k, spec in MODELS.items() if (not job or spec["job"] == job) and model_ready(k)]


def voices(model: str = "") -> list:
    return [{"id": name, "name": name, "about": about} for name, _, about in VOICES]


# ── Getting it ──────────────────────────────────────────────────────────

_job = {"model": "", "state": "", "what": "", "done": 0, "total": 0, "error": "", "at": 0.0}
_job_lock = threading.Lock()


def status() -> dict:
    return {
        "supported": supported(),
        "engine": engine_ready(),
        "models": [{"id": PREFIX + k, "job": spec["job"], "name": spec["name"], "about": spec["about"], "mb": spec["mb"],
                    "ready": engine_ready() and model_ready(k)} for k, spec in MODELS.items()],
        "job": dict(_job),
    }


def get(model: str) -> dict:
    """Fetch a model, and the engine first if it is not here yet, on a thread of its own. status() says how far."""
    key = _key(model)
    if key not in MODELS:
        raise ValueError("No such model.")
    if not supported():
        raise RuntimeError("This needs a computer.")
    with _job_lock:
        if _job["state"] in ("engine", "model", "unpacking"):
            return status()
        _job.update(model=PREFIX + key, state="engine" if not engine_ready() else "model", what="", done=0, total=0,
                    error="", at=time.time())
    threading.Thread(target=_get, args=(key,), name="voice-get", daemon=True).start()
    return status()


def remove(model: str) -> dict:
    key = _key(model)
    spec = MODELS.get(key)
    if spec:
        _drop(key)
        shutil.rmtree(models_dir() / spec["folder"], ignore_errors=True)
        from app.utils import providers
        providers.forget("local")
    return status()


def _get(key: str) -> None:
    try:
        if not engine_ready():
            _get_engine()
        if not model_ready(key):
            _get_model(key)
        _job.update(state="ready", what="", error="")
        from app.utils import providers
        providers.forget("local")
    except Exception as e:
        _job.update(state="error", error=str(e)[:300] or type(e).__name__)


def _context():
    """The system's certificates and certifi's together: a source run's Python can lack the ones GitHub needs."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def _download(url: str, dest: Path, what: str, sha256: str = "") -> None:
    """A file, its progress in status(), tried three times: a download that drops halfway is not worth failing for."""
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_context()))
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "LLMSelfbot"})
            with opener.open(req, timeout=60) as res, open(dest, "wb") as out:
                _job.update(what=what, done=0, total=int(res.headers.get("content-length") or 0))
                digest = hashlib.sha256()
                while chunk := res.read(1 << 16):
                    out.write(chunk)
                    digest.update(chunk)
                    _job["done"] += len(chunk)
            if sha256 and digest.hexdigest() != sha256:
                raise RuntimeError(f"{dest.name} did not match its checksum.")
            return
        except OSError:
            if attempt == 3:
                raise
            time.sleep(3 * attempt)


def _platform_fits(tag: str) -> bool:
    import platform
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        return tag == ("win_arm64" if arm else "win_amd64")
    if sys.platform == "darwin":
        return tag.startswith("macosx") and tag.endswith(("arm64" if arm else "x86_64", "universal2"))
    return tag.startswith(("manylinux", "linux")) and tag.endswith("aarch64" if arm else "x86_64")


def _wheel_for(files: list) -> dict | None:
    """The wheel in a PyPI release that this Python on this computer takes."""
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    for f in files:
        name = f.get("filename") or ""
        if not name.endswith(".whl"):
            continue
        python, _abi, plats = name[:-4].split("-")[-3:]
        if any(p in (py, "py3") for p in python.split(".")) and any(_platform_fits(p) for p in plats.split(".")):
            return f
    return None


def _get_engine() -> None:
    _job.update(state="engine")
    staging = home() / "engine.part"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_context()))
    for package in ENGINE:
        with opener.open(f"{PYPI}/{package}/{ENGINE_VERSION}/json", timeout=60) as r:
            files = json.loads(r.read()).get("urls") or []
        wheel = _wheel_for(files)
        if not wheel:
            raise RuntimeError("There is no build of the voice engine for this computer.")
        part = home() / wheel["filename"]
        _download(wheel["url"], part, "the voice engine", (wheel.get("digests") or {}).get("sha256", ""))
        with zipfile.ZipFile(part) as z:
            for member in z.namelist():
                # Only the package itself: what a wheel puts elsewhere (scripts, a copy of the DLLs) is not needed.
                if member.startswith("sherpa_onnx/") and ".." not in member:
                    z.extract(member, staging)
        part.unlink(missing_ok=True)
    shutil.rmtree(engine_dir(), ignore_errors=True)
    staging.rename(engine_dir())


def _get_model(key: str) -> None:
    spec = MODELS[key]
    _job.update(state="model")
    models_dir().mkdir(parents=True, exist_ok=True)
    archive = models_dir() / (spec["folder"] + ".tar.bz2")
    _download(spec["url"], archive, spec["name"])
    _job.update(state="unpacking", what=spec["name"])
    target = models_dir() / spec["folder"]
    shutil.rmtree(target, ignore_errors=True)
    with tarfile.open(archive, "r:bz2") as tar:
        # "data" refuses absolute paths, "..", links out of the folder and device files: this came off the internet.
        tar.extractall(models_dir(), members=[m for m in tar.getmembers() if m.name.split("/")[0] == spec["folder"]],
                       filter="data")
    archive.unlink(missing_ok=True)
    if not target.is_dir():
        raise RuntimeError(f"{spec['name']} was not in what was downloaded.")
    (target / ".ready").write_text(str(time.time()), encoding="utf-8")


# ── Using it ────────────────────────────────────────────────────────────

_loaded: dict = {}          # model key -> [engine object, last used]
_locks: dict = {}
_load_lock = threading.Lock()


def _engine():
    """sherpa_onnx, from the data folder."""
    if "sherpa_onnx" in sys.modules:
        return sys.modules["sherpa_onnx"]
    if not engine_ready():
        raise RuntimeError("The voice on this computer is not set up: get it under Settings > Calls.")
    where = str(engine_dir())
    if where not in sys.path:
        sys.path.insert(0, where)
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(engine_dir() / "sherpa_onnx" / "lib"))
    import sherpa_onnx
    return sherpa_onnx


def _threads() -> int:
    return max(1, min(4, os.cpu_count() or 2))


def _load(key: str):
    with _load_lock:
        hit = _loaded.get(key)
        if hit:
            hit[1] = time.time()
            return hit[0]
        if not model_ready(key):
            raise RuntimeError(f"{MODELS[key]['name']} is not on this computer yet: get it under Settings > Calls.")
        s = _engine()
        folder = models_dir() / MODELS[key]["folder"]
        if MODELS[key]["job"] == "stt":
            find = lambda part: str(next(folder.glob(f"*{part}")))
            obj = s.OfflineRecognizer.from_whisper(encoder=find("encoder.int8.onnx"), decoder=find("decoder.int8.onnx"),
                                                   tokens=find("tokens.txt"), num_threads=_threads(), language="",
                                                   task="transcribe")
        else:
            f = lambda name: str(folder / name)
            obj = s.OfflineTts(s.OfflineTtsConfig(model=s.OfflineTtsModelConfig(
                supertonic=s.OfflineTtsSupertonicModelConfig(
                    duration_predictor=f("duration_predictor.int8.onnx"), text_encoder=f("text_encoder.int8.onnx"),
                    vector_estimator=f("vector_estimator.int8.onnx"), vocoder=f("vocoder.int8.onnx"),
                    tts_json=f("tts.json"), unicode_indexer=f("unicode_indexer.bin"), voice_style=f("voice.bin")),
                num_threads=_threads(), provider="cpu"), max_num_sentences=1))
        _loaded[key] = [obj, time.time()]
        _locks.setdefault(key, threading.Lock())
        _watch()
        return obj


def _drop(key: str) -> None:
    with _load_lock:
        _loaded.pop(key, None)


_watching = False


def _watch() -> None:
    """Lets go of what has not been used for a while, so a call an hour ago does not hold its memory for the day."""
    global _watching
    if _watching:
        return
    _watching = True

    def loop():
        global _watching
        while _loaded:
            time.sleep(60)
            for key, (_obj, used) in list(_loaded.items()):
                if time.time() - used > IDLE_S and not _locks[key].locked():
                    _drop(key)
        _watching = False

    threading.Thread(target=loop, name="voice-idle", daemon=True).start()


def _decode(audio: bytes) -> tuple:
    """(float samples, rate) of a recording: a WAV as it is, anything else (a voice note's Ogg) through ffmpeg."""
    from app.voice.audio import read_wav, to_mono
    if audio[:4] == b"RIFF":
        pcm, rate, channels = read_wav(audio)
        if channels > 1:
            pcm = to_mono(pcm, channels)
    else:
        from app.utils import binaries
        ffmpeg = binaries.find("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("Hearing a voice note on this computer needs ffmpeg (System has it).")
        from app.utils.procs import quiet_kwargs
        done = subprocess.run([ffmpeg, "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
                              input=audio, capture_output=True, timeout=60, **quiet_kwargs())
        if done.returncode:
            raise RuntimeError("ffmpeg could not read that recording.")
        pcm, rate = done.stdout, 16000
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    return [x / 32768.0 for x in samples], rate


async def hear(model: str, audio: bytes) -> str:
    key = _key(model)

    def run():
        samples, rate = _decode(audio)
        rec = _load(key)
        with _locks[key]:
            stream = rec.create_stream()
            stream.accept_waveform(rate, samples)
            rec.decode_stream(stream)
            return stream.result.text

    return (await asyncio.to_thread(run) or "").strip()


# The languages it is told about; anything else is read as English.
_WORDS = {
    "fr": "le la les un une des et est je tu il elle nous vous ils pas que qui ça c'est pour avec dans sur mais oui non "
          "bonjour salut merci très bien",
    "es": "el la los las un una y es yo tú él ella que no sí pero por para con muy bien hola gracias está",
    "pt": "o a os as um uma e é eu você ele ela que não sim mas por para com muito bem olá obrigado está",
    "de": "der die das ein eine und ist ich du er sie wir nicht ja nein aber mit für sehr gut hallo danke",
    "it": "il lo la gli le un una e è io tu lui lei che non sì ma per con molto bene ciao grazie",
    "nl": "de het een en is ik jij hij zij wij niet ja nee maar met voor heel goed hallo dank",
    "en": "the a an and is i you he she we they not yes no but for with very good hello thanks it's that",
}
_WORD_SETS = {lang: set(words.split()) for lang, words in _WORDS.items()}


def language_of(text: str) -> str:
    """Which language a line is in, near enough for the voice to pronounce it: by its script, then by its small words."""
    t = str(text or "")
    if re.search(r"[가-힣]", t):
        return "ko"
    if re.search(r"[぀-ヿ]", t):
        return "ja"
    if re.search(r"[一-鿿]", t):
        return "zh"
    if re.search(r"[Ѐ-ӿ]", t):
        return "ru"
    words = re.findall(r"[a-zà-ÿ']+", t.lower())
    if not words:
        return "en"
    best, score = "en", 0
    for lang, known in _WORD_SETS.items():
        hits = sum(1 for w in words if w in known)
        if hits > score:
            best, score = lang, hits
    return best


async def say(model: str, voice: str, text: str) -> tuple:
    key = _key(model)
    sid = next((n for name, n, _ in VOICES if name == voice), 0)
    lang = language_of(text)

    def run():
        tts = _load(key)
        s = _engine()
        with _locks[key]:
            cfg = s.GenerationConfig()
            cfg.sid = sid
            cfg.speed = 1.0
            if lang != "en":
                cfg.extra = {"lang": lang}
            audio = tts.generate(text, cfg)
        pcm = array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in audio.samples))
        if sys.byteorder == "big":
            pcm.byteswap()
        return pcm.tobytes(), audio.sample_rate

    pcm, rate = await asyncio.to_thread(run)
    if not pcm:
        raise RuntimeError("The voice on this computer said nothing.")
    return pcm, rate
