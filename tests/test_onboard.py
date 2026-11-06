"""This computer's own voice (app/voice/onboard.py): fetched when asked for, then hearing and speaking with no server
and no key (2026-11-05).

The real engine and models were fetched and used once by hand on the computer this was written on (whisper-tiny heard
a line in 0.2 s, Supertonic said one in 0.6 s, in French too); here a stand-in of PyPI and of the model releases serves
a stand-in engine, so the test needs no network and no 250 MB."""
import array
import asyncio
import hashlib
import http.server
import io
import json
import os
import platform
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name
(Path(_tmp.name) / "config").mkdir(parents=True, exist_ok=True)
(Path(_tmp.name) / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"),
                                                       encoding="utf-8")

from app.voice import onboard  # noqa: E402
from app.voice.audio import wav_bytes  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


# A stand-in engine: what the app asks of sherpa-onnx, kept so it can be looked at.
FAKE_ENGINE = '''
asked = []
class _Result:
    text = " heard you fine "
class _Stream:
    def __init__(self): self.result = _Result()
    def accept_waveform(self, rate, samples): asked.append(("waveform", rate, len(samples), type(samples).__name__))
class OfflineRecognizer:
    @staticmethod
    def from_whisper(**kw):
        asked.append(("whisper", kw)); return OfflineRecognizer()
    def create_stream(self): return _Stream()
    def decode_stream(self, s): asked.append(("decode",))
class GenerationConfig:
    def __init__(self): self.sid = 0; self.speed = 1.0; self.extra = {}
class OfflineTtsSupertonicModelConfig:
    def __init__(self, **kw): self.kw = kw
class OfflineTtsModelConfig:
    def __init__(self, **kw): self.kw = kw
class OfflineTtsConfig:
    def __init__(self, **kw): self.kw = kw
class _Audio:
    sample_rate = 44100
    samples = [0.0, 0.5, -0.5, 1.5, -1.5] * 100
class OfflineTts:
    def __init__(self, cfg): asked.append(("tts", cfg))
    def generate(self, text, cfg):
        asked.append(("say", text, cfg.sid, dict(cfg.extra)))
        return _Audio()
'''


def wheel(name: str, files: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for path, body in files.items():
            z.writestr(path, body)
    return out.getvalue()


MAIN = wheel("main", {"sherpa_onnx/__init__.py": FAKE_ENGINE, "sherpa_onnx-2.0.1.dist-info/METADATA": "x",
                      "../escape.txt": "no"})
CORE = wheel("core", {"sherpa_onnx/lib/onnxruntime.dll": "dll", "sherpa_onnx_core-2.0.1.data/data/Scripts/x.dll": "dll"})


def archive(folder: str, extra_outside: bool = True) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:bz2") as tar:
        names = [f"{folder}/tiny-encoder.int8.onnx", f"{folder}/tiny-decoder.int8.onnx", f"{folder}/tiny-tokens.txt",
                 f"{folder}/voice.bin"]
        if extra_outside:
            names.append("elsewhere/not-this.txt")
        for n in names:
            data = b"model bytes"
            info = tarfile.TarInfo(n)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


class Stand(http.server.BaseHTTPRequestHandler):
    files = {}
    seen = []

    def do_GET(self):
        Stand.seen.append(self.path)
        body = Stand.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stand)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
onboard.PYPI = BASE + "/pypi"
# This computer's wheel, worked out as onboard._platform_fits does: the CPU as well as the system. Linux was taken to be
# x86-64, and the build on the ARM runner (linux-aarch64) failed the run (v1.8.0).
ARM = platform.machine().lower() in ("arm64", "aarch64")
TAG = {"win32": "win_arm64" if ARM else "win_amd64",
       "darwin": "macosx_11_0_arm64" if ARM else "macosx_10_15_x86_64"}.get(
    sys.platform, "manylinux_2_17_aarch64.manylinux2014_aarch64" if ARM else "manylinux_2_17_x86_64.manylinux2014_x86_64")
PY = f"cp{sys.version_info.major}{sys.version_info.minor}"


def release(package, filename, body, sha=None):
    Stand.files[f"/files/{filename}"] = body
    Stand.files[f"/pypi/{package}/2.0.1/json"] = json.dumps({"urls": [
        {"filename": f"{package.replace('-', '_')}-2.0.1-cp39-cp39-win32.whl", "url": f"{BASE}/nope", "digests": {}},
        {"filename": filename, "url": f"{BASE}/files/{filename}",
         "digests": {"sha256": sha or hashlib.sha256(body).hexdigest()}}]}).encode()


release("sherpa-onnx", f"sherpa_onnx-2.0.1-{PY}-{PY}-{TAG}.whl", MAIN)
release("sherpa-onnx-core", f"sherpa_onnx_core-2.0.1-py3-none-{TAG}.whl", CORE)
for key in onboard.MODELS:
    onboard.MODELS[key]["url"] = f"{BASE}/models/{key}.tar.bz2"
    Stand.files[f"/models/{key}.tar.bz2"] = archive(onboard.MODELS[key]["folder"])


def wait():
    t = time.time()
    while onboard.status()["job"]["state"] in ("engine", "model", "unpacking") and time.time() - t < 30:
        time.sleep(0.05)
    return onboard.status()


print("== which build ==")
# One for every computer the app is built for, so whichever runs this finds its own among the others.
files = [{"filename": f} for f in (
    "sherpa_onnx-2.0.1-cp311-cp311-win_amd64.whl", f"sherpa_onnx-2.0.1-{PY}-{PY}-win_amd64.whl",
    f"sherpa_onnx-2.0.1-{PY}-{PY}-win_arm64.whl",
    f"sherpa_onnx-2.0.1-{PY}-{PY}-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
    f"sherpa_onnx-2.0.1-{PY}-{PY}-manylinux_2_17_aarch64.manylinux2014_aarch64.whl",
    f"sherpa_onnx-2.0.1-{PY}-{PY}-macosx_10_15_x86_64.whl",
    f"sherpa_onnx-2.0.1-{PY}-{PY}-macosx_11_0_arm64.whl", "sherpa_onnx-2.0.1.tar.gz")]
picked = onboard._wheel_for(files)
check("this Python's, for this computer", picked and PY in picked["filename"] and TAG.split(".")[0] in picked["filename"],
      str(picked))
check("a py3 wheel is fine too", onboard._wheel_for([{"filename": f"x-2.0.1-py3-none-{TAG}.whl"}]) is not None)
check("another Python's is not", onboard._wheel_for([{"filename": f"x-2.0.1-cp39-cp39-{TAG}.whl"}]) is None)
check("nor a source release", onboard._wheel_for([{"filename": "x-2.0.1.tar.gz"}]) is None)

print("\n== before it is fetched ==")
st = onboard.status()
check("it says it can run here, and that nothing is fetched yet", st["supported"] and not st["engine"]
      and not any(m["ready"] for m in st["models"]))
check("each model with what it does and how big it is", {m["id"]: (m["job"], m["mb"] > 0) for m in st["models"]} == {
    "builtin:whisper-tiny": ("stt", True), "builtin:whisper-base": ("stt", True), "builtin:supertonic-3": ("tts", True)})
check("nothing listed as usable", onboard.installed() == [])
try:
    asyncio.run(onboard.hear("builtin:whisper-tiny", wav_bytes(b"\0\0" * 1600, 16000)))
    check("using it before it is here says where to get it", False)
except RuntimeError as e:
    check("using it before it is here says where to get it", "Settings > Calls" in str(e))

print("\n== fetching it ==")
onboard.get("builtin:whisper-tiny")
st = wait()
check("the engine and the model, fetched", st["job"]["state"] == "ready" and st["engine"]
      and onboard.model_ready("whisper-tiny"), str(st["job"]))
eng = onboard.engine_dir()
check("only the package from each wheel", (eng / "sherpa_onnx" / "__init__.py").is_file()
      and (eng / "sherpa_onnx" / "lib" / "onnxruntime.dll").is_file()
      and not (eng / "sherpa_onnx_core-2.0.1.data").exists() and not (eng.parent / "escape.txt").exists())
models = onboard.models_dir()
check("the model's own folder and nothing else from the archive",
      (models / onboard.MODELS["whisper-tiny"]["folder"] / "tiny-encoder.int8.onnx").is_file()
      and not (models / "elsewhere").exists())
check("and no download left lying about", not list(models.glob("*.tar.bz2")) and not list(eng.parent.glob("*.whl")))
check("PyPI asked for the version it was made with", f"/pypi/sherpa-onnx/{onboard.ENGINE_VERSION}/json" in Stand.seen)
check("usable now, and listed", onboard.installed() == ["builtin:whisper-tiny"])
from app.utils import providers  # noqa: E402

providers.forget("local")
listed = providers.list_models("local", {"bot": {"local": {"base_url": BASE + "/no-server/v1"}}}, force=True)
check("among This computer's models even with no server running",
      {"id": "builtin:whisper-tiny", "capabilities": ["stt"]} in listed["models"], str(listed["models"])[:200])
n = len(Stand.seen)
onboard.get("builtin:supertonic-3")
wait()
check("the second model needs no engine fetched again", onboard.model_ready("supertonic-3")
      and not any("/pypi/" in p for p in Stand.seen[n:]))

print("\n== a bad download ==")
release("sherpa-onnx", f"sherpa_onnx-2.0.1-{PY}-{PY}-{TAG}.whl", MAIN, sha="0" * 64)
import shutil  # noqa: E402

shutil.rmtree(onboard.engine_dir())
onboard.get("builtin:whisper-base")
st = wait()
check("a checksum that does not match is refused, and said", st["job"]["state"] == "error"
      and "checksum" in st["job"]["error"] and not onboard.engine_ready())
release("sherpa-onnx", f"sherpa_onnx-2.0.1-{PY}-{PY}-{TAG}.whl", MAIN)
Stand.files[f"/pypi/sherpa-onnx-core/2.0.1/json"] = json.dumps({"urls": [{"filename": "x-2.0.1-cp39-cp39-win32.whl",
                                                                          "url": "", "digests": {}}]}).encode()
onboard.get("builtin:whisper-base")
st = wait()
check("no build for this computer: said in words", st["job"]["state"] == "error"
      and "no build of the voice engine for this computer" in st["job"]["error"])
release("sherpa-onnx-core", f"sherpa_onnx_core-2.0.1-py3-none-{TAG}.whl", CORE)
onboard.get("builtin:whisper-tiny")
wait()
check("and asked again, it is fetched", onboard.engine_ready())
try:
    onboard.get("builtin:nothing")
    check("a model it does not know is refused", False)
except ValueError:
    check("a model it does not know is refused", True)

print("\n== hearing ==")
said = asyncio.run(onboard.hear("builtin:whisper-tiny", wav_bytes(b"\x10\x00" * 3200, 16000)))
import sherpa_onnx as fake  # noqa: E402  (the stand-in, from the data folder)

check("the engine comes from the data folder", str(onboard.engine_dir()) in str(Path(fake.__file__)))
check("the words, trimmed", said == "heard you fine")
w = next(a for a in fake.asked if a[0] == "whisper")[1]
check("Whisper with its int8 files, any language", w["encoder"].endswith("tiny-encoder.int8.onnx")
      and w["decoder"].endswith("tiny-decoder.int8.onnx") and w["language"] == "" and w["task"] == "transcribe")
wave = next(a for a in fake.asked if a[0] == "waveform")
check("its audio as a plain list of samples, at its own rate: no numpy needed", wave[1:] == (16000, 3200, "list"))
check("loaded once, then kept", asyncio.run(onboard.hear("builtin:whisper-tiny", wav_bytes(b"\0\0" * 320, 16000)))
      and len([a for a in fake.asked if a[0] == "whisper"]) == 1)
from app.utils import binaries  # noqa: E402

found = binaries.find
binaries.find = lambda name: None
try:
    asyncio.run(onboard.hear("builtin:whisper-tiny", b"OggS not a wav"))
    check("a voice note with no ffmpeg to read it says so", False)
except RuntimeError as e:
    check("a voice note with no ffmpeg to read it says so", "ffmpeg" in str(e))
binaries.find = found

print("\n== speaking ==")
pcm, rate = asyncio.run(onboard.say("builtin:supertonic-3", "M2", "Hey, how are you?"))
say = [a for a in fake.asked if a[0] == "say"][-1]
check("in the voice picked, by its number", say[2] == 6)
check("English needs no word about it", say[3] == {})
samples = array.array("h")
samples.frombytes(pcm)
check("16-bit, at its own rate, the loud ones held at the edge", rate == 44100
      and list(samples[:5]) == [0, 16383, -16383, 32767, -32768])
asyncio.run(onboard.say("builtin:supertonic-3", "F1", "Salut, ça va ? Je suis contente de te voir."))
check("French is said in French", [a for a in fake.asked if a[0] == "say"][-1][3] == {"lang": "fr"})
check("a voice it does not have: its first", (asyncio.run(onboard.say("builtin:supertonic-3", "Nobody", "hi"))
                                              and [a for a in fake.asked if a[0] == "say"][-1][2] == 0))
for text, lang in (("Hola, ¿qué tal? Muy bien, gracias", "es"), ("Hallo, wie geht es dir? Sehr gut, danke", "de"),
                   ("Ciao, come stai? Molto bene, grazie", "it"), ("안녕하세요", "ko"), ("こんにちは", "ja"),
                   ("Привет, как дела", "ru"), ("ok", "en"), ("", "en")):
    check(f"{text[:20]!r} is {lang}", onboard.language_of(text) == lang, onboard.language_of(text))
check("ten voices, each told apart", [v["id"] for v in onboard.voices()] == ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3",
                                                                             "M4", "M5"]
      and all(v["about"].startswith(("woman", "man")) for v in onboard.voices()))

print("\n== putting it away ==")
onboard.remove("builtin:whisper-tiny")
check("removed: gone from the disk and the list", not onboard.model_ready("whisper-tiny")
      and "builtin:whisper-tiny" not in onboard.installed() and "whisper-tiny" not in onboard._loaded)
check("the rest stays", onboard.model_ready("supertonic-3"))

print("\n== where it can run ==")
from app.utils import compat  # noqa: E402

check("not on a phone, and it says so", compat.check("local_voice", "android") == {"why": "Needs a computer."}
      and compat.check("local_voice", "ios"))
check("on a computer, nothing to say", compat.check("local_voice", "windows-x64") is None
      and compat.check("local_voice", "linux-arm64") is None)
src = (ROOT / "app" / "voice" / "onboard.py").read_text(encoding="utf-8")
check("the archive is unpacked with the safe filter", 'filter="data"' in src)
check("certifi's certificates beside the system's", "certifi.where()" in src)

server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
