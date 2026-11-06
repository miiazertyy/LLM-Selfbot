"""Hearing and speaking with every provider that can (app/voice/speech.py), for voice messages and calls alike, and a
call's own picks of what hears, thinks and speaks (2026-11-05).

None of these providers could be tried with a real key here, so each is held to its own documentation against a
stand-in of its server on this computer: the address, the key where it wants it, the body, and what it answers.
Nothing here leaves this computer."""
import asyncio
import base64
import http.server
import json
import os
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name
(Path(_tmp.name) / "config").mkdir(parents=True, exist_ok=True)
(Path(_tmp.name) / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"),
                                                       encoding="utf-8")
for name in list(os.environ):
    if name.endswith("_API_KEY") or "_API_KEY_" in name:
        os.environ.pop(name)

from app.voice import speech  # noqa: E402
from app.voice.audio import read_wav, wav_bytes  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def run(coro):
    return asyncio.run(coro)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


PCM = bytes(range(0, 200, 2)) * 48          # some 16-bit samples
WAV = wav_bytes(PCM, 24000)
# What a server writes when it sends the header before it knows how long the audio is.
ENDLESS = WAV[:4] + b"\xff\xff\xff\xff" + WAV[8:40] + b"\xff\xff\xff\xff" + WAV[44:]


class Stand(http.server.BaseHTTPRequestHandler):
    """Every provider at once: what came in is kept, and what goes back is whatever `answers` says for its path."""
    seen = []
    answers = {}

    def _any(self, method):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        url = urllib.parse.urlsplit(self.path)
        got = {"method": method, "path": url.path, "query": dict(urllib.parse.parse_qsl(url.query)),
               "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
        Stand.seen.append(got)
        status, ctype, out = Stand.answers.get((method, url.path), (404, "application/json", b'{"message":"no"}'))
        if callable(out):
            status, ctype, out = out(got)
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        self._any("POST")

    def do_GET(self):
        self._any("GET")

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stand)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
for pid in speech.URLS:
    speech.URLS[pid] = BASE + {"deepgram": "/dg/v1", "cartesia": "/ca", "elevenlabs": "/el/v1", "gemini": "/ge/v1beta",
                               "mistral": "/mi/v1", "xai": "/xa/v1", "fish": "/fi", "rime": "/ri", "minimax": "/mm/v1"}[pid]
J = "application/json"


def last(path):
    return next(s for s in reversed(Stand.seen) if s["path"] == path)


def keys(**named):
    for k in list(os.environ):
        if k.endswith("_API_KEY") or "_API_KEY_" in k:
            os.environ.pop(k)
    os.environ.update(named)


counted = []
from app.utils import usage  # noqa: E402

usage.note = lambda provider, model, status, ms, headers=None: counted.append((provider, model, status))

print("== which provider goes through here ==")
check("hearing in their own APIs", all(speech.native("stt", p) for p in ("deepgram", "elevenlabs", "cartesia")))
check("speaking in theirs", all(speech.native("tts", p) for p in
                                ("elevenlabs", "deepgram", "cartesia", "gemini", "mistral", "xai", "fish", "rime", "minimax")))
check("OpenAI's shape stays with the OpenAI client", not any(speech.native(j, p) for j, p in
                                                             (("stt", "groq"), ("stt", "openai"), ("stt", "mistral"),
                                                              ("tts", "groq"), ("tts", "openai"))))
check("this computer's own voice goes through here, a server's models do not",
      speech.native("tts", "local", "builtin:supertonic-3") and not speech.native("tts", "local", "kokoro"))
check("a call's pick, read", speech.entry_of("deepgram:nova-3") == {"provider": "deepgram", "model": "nova-3"}
      and speech.entry_of("local:builtin:whisper-base") == {"provider": "local", "model": "builtin:whisper-base"})
check("nothing, or nonsense, is no pick", speech.entry_of("") is None and speech.entry_of("nobody:x") is None
      and speech.entry_of("groq:") is None)
m = speech.models_for("deepgram")
check("what each has, as the Models tab lists models", {"id": "nova-3", "capabilities": ["stt"]} in m
      and {"id": "aura-2", "capabilities": ["tts"]} in m)
check("Mistral's hearing and speaking both", {x["id"] for x in speech.models_for("mistral")}
      >= {"voxtral-mini-transcribe-3-0", "voxtral-mini-tts-3-0"})

print("\n== hearing ==")
keys(DEEPGRAM_API_KEY="dg-1")
Stand.answers[("POST", "/dg/v1/listen")] = (200, J, json.dumps(
    {"results": {"channels": [{"alternatives": [{"transcript": " hey there "}]}]}}).encode())
said = run(speech.hear("deepgram", "nova-3", WAV, "call.wav"))
got = last("/dg/v1/listen")
check("Deepgram: the words", said == "hey there", said)
check("its key as it wants it", got["headers"].get("authorization") == "Token dg-1")
check("the recording as it is, said to be a WAV", got["body"] == WAV and got["headers"]["content-type"] == "audio/wav")
check("Nova 3 told to hear any of its languages", got["query"].get("language") == "multi"
      and got["query"].get("model") == "nova-3" and got["query"].get("smart_format") == "true")
run(speech.hear("deepgram", "nova-2", b"OggS....", "voice.ogg"))
got = last("/dg/v1/listen")
check("an older one works out the language, and a voice note goes up as Ogg",
      got["query"].get("detect_language") == "true" and got["headers"]["content-type"] == "audio/ogg")

keys(ELEVENLABS_API_KEY="el-1")
Stand.answers[("POST", "/el/v1/speech-to-text")] = (200, J, b'{"text": "hello world"}')
said = run(speech.hear("elevenlabs", "", WAV, "call.wav"))
got = last("/el/v1/speech-to-text")
check("ElevenLabs: the words, with Scribe when nothing says", said == "hello world"
      and b'name="model_id"' in got["body"] and b"scribe_v2" in got["body"] and b'filename="call.wav"' in got["body"])
check("its key in its own header", got["headers"].get("xi-api-key") == "el-1")

keys(CARTESIA_API_KEY="ca-1")
Stand.answers[("POST", "/ca/stt")] = (200, J, b'{"type": "transcript", "text": "ink heard it"}')
said = run(speech.hear("cartesia", "ink-whisper", WAV, "call.wav"))
got = last("/ca/stt")
check("Cartesia: the words", said == "ink heard it")
check("with the version it is pinned to", got["headers"].get("cartesia-version") == speech.CARTESIA_VERSION == "2026-08-14"
      and got["headers"].get("authorization") == "Bearer ca-1" and b"ink-whisper" in got["body"])

print("\n== speaking ==")
keys(DEEPGRAM_API_KEY="dg-1")
Stand.answers[("POST", "/dg/v1/speak")] = (200, "audio/l16", PCM)
pcm, rate = run(speech.say("deepgram", "aura-2", "", "hello"))
got = last("/dg/v1/speak")
check("Deepgram: raw 16-bit at 24 kHz, as asked", pcm == PCM and rate == 24000 and got["query"] == {
    "model": "aura-2-thalia-en", "encoding": "linear16", "sample_rate": "24000", "container": "none"}, str(got["query"]))
check("its voice is its model: the voice picked goes in as the model",
      run(speech.say("deepgram", "aura-2", "aura-2-zeus-en", "hi")) and last("/dg/v1/speak")["query"]["model"] == "aura-2-zeus-en")
check("and the text as JSON", json.loads(got["body"]) == {"text": "hello"})

keys(CARTESIA_API_KEY="ca-1")
Stand.answers[("POST", "/ca/tts/bytes")] = (200, "application/octet-stream", PCM + b"\x01")
pcm, rate = run(speech.say("cartesia", "sonic-3.6", "voice-123", "hello"))
body = json.loads(last("/ca/tts/bytes")["body"])
check("Cartesia: raw 16-bit at 24 kHz, an odd byte at the end dropped", pcm == PCM and rate == 24000)
check("its body as its reference has it", body == {"model_id": "sonic-3.6", "transcript": "hello",
                                                   "voice": {"mode": "id", "id": "voice-123"},
                                                   "output_format": {"container": "raw", "encoding": "pcm_s16le",
                                                                     "sample_rate": 24000}}, str(body))
Stand.answers[("GET", "/ca/voices")] = (200, J, json.dumps({"data": [
    {"id": "v-1", "name": "Katie", "description": "friendly", "gender": "feminine"},
    {"id": "v-2", "name": "Blake", "description": "calm", "gender": "masculine"}], "has_more": False}).encode())
counted.clear()
pcm, _ = run(speech.say("cartesia", "", "", "no voice picked"))
check("no voice picked: the first of its voices", json.loads(last("/ca/tts/bytes")["body"])["voice"]["id"] == "v-1")
check("listing the voices is not counted as a model call; saying the line is", counted == [("cartesia", "sonic-3.6", 200)],
      str(counted))

keys(GEMINI_API_KEY="ge-1")
Stand.answers[("POST", "/ge/v1beta/interactions")] = (200, J, json.dumps({"steps": [
    {"type": "user_input"},
    {"type": "model_output", "content": [{"type": "audio", "data": base64.b64encode(WAV).decode()}]}]}).encode())
pcm, rate = run(speech.say("gemini", "gemini-3.8-flash-tts", "Puck", "hello"))
body = json.loads(last("/ge/v1beta/interactions")["body"])
check("Gemini: the audio of what it put out", pcm == PCM and rate == 24000)
check("asked the way its speech page asks", body["model"] == "gemini-3.8-flash-tts"
      and body["response_format"] == {"type": "audio"} and body["generation_config"] == {"speech_config": [{"voice": "Puck"}]}
      and body["input"][0]["content"][0] == {"type": "text", "text": "hello"}
      and last("/ge/v1beta/interactions")["headers"].get("x-goog-api-key") == "ge-1")
Stand.answers[("POST", "/ge/v1beta/interactions")] = (200, J, json.dumps({"candidates": [{"content": {"parts": [
    {"inlineData": {"data": base64.b64encode(WAV).decode()}}]}}]}).encode())
check("and from the older shape, should one come back", run(speech.say("gemini", "", "", "hi"))[0] == PCM)
Stand.answers[("POST", "/ge/v1beta/interactions")] = (200, J, b'{"steps": []}')
try:
    run(speech.say("gemini", "", "", "hi"))
    check("no audio in it is said, not played as silence", False)
except speech.SpeechError as e:
    check("no audio in it is said, not played as silence", "no audio" in str(e))

keys(MISTRAL_API_KEY="mi-1")
Stand.answers[("POST", "/mi/v1/audio/speech")] = (200, J, json.dumps({"audio_data": base64.b64encode(WAV).decode()}).encode())
pcm, rate = run(speech.say("mistral", "", "", "bonjour"))
body = json.loads(last("/mi/v1/audio/speech")["body"])
check("Mistral: base64 in audio_data", pcm == PCM)
check("its own fields, a preset voice when none is picked", body == {"model": "voxtral-mini-tts-3-0", "input": "bonjour",
                                                                     "voice_id": "voice_478", "response_format": "wav"},
      str(body))

keys(XAI_API_KEY="xa-1")
Stand.answers[("POST", "/xa/v1/tts")] = (200, J, json.dumps({"audio": base64.b64encode(WAV).decode(),
                                                             "content_type": "audio/wav"}).encode())
pcm, _ = run(speech.say("xai", "grok-tts", "ara", "hello"))
body = json.loads(last("/xa/v1/tts")["body"])
check("xAI: base64 in JSON, as its reference says", pcm == PCM and body["voice_id"] == "ara" and body["language"] == "auto"
      and body["output_format"] == {"codec": "wav", "sample_rate": 24000})
Stand.answers[("POST", "/xa/v1/tts")] = (200, "audio/wav", WAV)
check("or the audio as it is, as its own examples treat it", run(speech.say("xai", "", "", "hi"))[0] == PCM)

keys(FISH_API_KEY="fi-1")
Stand.answers[("POST", "/fi/v1/tts")] = (200, "audio/wav", ENDLESS)
pcm, rate = run(speech.say("fish", "s1", "ref-9", "hello"))
got = last("/fi/v1/tts")
body = json.loads(got["body"])
check("Fish Audio: a WAV whose header says it never ends", pcm == PCM and rate == 24000)
check("the model in its header, the voice as reference_id", got["headers"].get("model") == "s1"
      and body["reference_id"] == "ref-9" and body["format"] == "wav" and body["sample_rate"] == 24000)
run(speech.say("fish", "", "", "no voice"))
check("no voice picked: none sent, and its newest model", "reference_id" not in json.loads(last("/fi/v1/tts")["body"])
      and last("/fi/v1/tts")["headers"].get("model") == "s2.1-pro")

keys(RIME_API_KEY="ri-1")
Stand.answers[("POST", "/ri/")] = (200, "audio/wav", WAV)
pcm, _ = run(speech.say("rime", "coda", "lyra", "hello"))
got = last("/ri/")
check("Rime: WAV asked for, as it must be", pcm == PCM and got["headers"].get("accept") == "audio/wav"
      and json.loads(got["body"]) == {"text": "hello", "speaker": "lyra", "samplingRate": 24000})

keys(MINIMAX_API_KEY="mm-1", MINIMAX_API_KEY_1="mm-2")
calls = {"n": 0}


def minimax(got):
    calls["n"] += 1
    if got["headers"].get("authorization") == "Bearer mm-1":
        return 200, J, json.dumps({"base_resp": {"status_code": 1004, "status_msg": "login fail"}}).encode()
    return 200, J, json.dumps({"data": {"audio": WAV.hex(), "status": 2}, "base_resp": {"status_code": 0}}).encode()


Stand.answers[("POST", "/mm/v1/t2a_v2")] = (200, J, minimax)
pcm, _ = run(speech.say("minimax", "", "", "hello"))
body = json.loads(last("/mm/v1/t2a_v2")["body"])
check("MiniMax: hex in data.audio", pcm == PCM and body["model"] == "speech-2.8-turbo"
      and body["voice_setting"]["voice_id"] == "English_Graceful_Lady" and body["audio_setting"]["format"] == "wav")
check("a key it refuses inside a 200 is rested, and the next one used", calls["n"] == 2)

keys(ELEVENLABS_API_KEY="el-1")
Stand.answers[("POST", "/el/v1/text-to-speech/v-77")] = (200, "audio/pcm", PCM)
pcm, _ = run(speech.say("elevenlabs", "", "v-77", "hello"))
got = last("/el/v1/text-to-speech/v-77")
check("ElevenLabs as it always was: PCM at 24 kHz, its quickest model", pcm == PCM
      and got["query"] == {"output_format": "pcm_24000"} and json.loads(got["body"])["model_id"] == "eleven_flash_v2_5")
try:
    run(speech.say("elevenlabs", "", "", "hi"))
    check("ElevenLabs with no voice picked says so", False)
except speech.SpeechError as e:
    check("ElevenLabs with no voice picked says so", "Pick an ElevenLabs voice" in str(e))

print("\n== keys ==")
keys(DEEPGRAM_API_KEY="dg-bad", DEEPGRAM_API_KEY_1="dg-good")
Stand.answers[("POST", "/dg/v1/speak")] = (200, J, lambda got: (
    (401, J, b'{"err_msg": "Invalid credentials."}') if got["headers"]["authorization"] == "Token dg-bad"
    else (200, "audio/l16", PCM)))
from app.utils import providers  # noqa: E402

providers._key_rest.clear()
counted.clear()
pcm, _ = run(speech.say("deepgram", "", "", "hi"))
check("a refused key: the next one says it", pcm == PCM)
check("and the refused one is left alone a while", providers.key_order("deepgram") == ["dg-good", "dg-bad"])
check("both tries counted, never the key itself", counted == [("deepgram", "aura-2-thalia-en", 401),
                                                              ("deepgram", "aura-2-thalia-en", 200)], str(counted))
keys()
try:
    run(speech.say("rime", "", "", "hi"))
    check("no key: says where to add one", False)
except speech.SpeechError as e:
    check("no key: says where to add one", "needs a key" in str(e) and "Providers" in str(e))
keys(RIME_API_KEY="ri-1")
Stand.answers[("POST", "/ri/")] = (400, J, b'{"message": "unknown speaker"}')
try:
    run(speech.say("rime", "", "nobody", "hi"))
    check("what the provider said is passed on", False)
except speech.SpeechError as e:
    check("what the provider said is passed on", "Rime said 400: unknown speaker" in str(e), str(e))

print("\n== voices ==")
for pid, n in (("deepgram", 80), ("mistral", 36), ("xai", 26), ("rime", 18), ("minimax", 6), ("openai", 13),
               ("gemini", 30), ("groq", 6)):
    got = run(speech.voices(pid))
    check(f"{pid}: {n}+ listed", len(got["voices"]) >= n and not got["typed"], str(len(got["voices"])))
thalia = next(v for v in run(speech.voices("deepgram"))["voices"] if v["id"] == "aura-2-thalia-en")
check("each with a few words about it", thalia["name"] == "Thalia" and thalia["about"].startswith("woman"))
check("a server on this computer: its voices are its own names, typed", run(speech.voices("local", "kokoro"))["typed"])
keys(CARTESIA_API_KEY="ca-1")
speech._fetched.clear()
got = run(speech.voices("cartesia"))
check("Cartesia's, fetched", [v["id"] for v in got["voices"]] == ["v-1", "v-2"] and got["voices"][0]["about"].startswith("woman"))
n = len([s for s in Stand.seen if s["path"] == "/ca/voices"])
run(speech.voices("cartesia"))
check("and kept for a while rather than asked for each time", len([s for s in Stand.seen if s["path"] == "/ca/voices"]) == n)
keys(FISH_API_KEY="fi-1")
Stand.answers[("GET", "/fi/model")] = (200, J, lambda got: (200, J, json.dumps({"total": 1, "items": [
    {"_id": "mine-1", "title": "My voice"}] if got["query"].get("self") == "true" else [
    {"_id": "pop-1", "title": "Popular", "languages": ["en"]}, {"_id": "mine-1", "title": "My voice"}]}).encode()))
got = run(speech.voices("fish"))
check("Fish Audio's: yours first, then the most used, once each", [v["id"] for v in got["voices"]] == ["mine-1", "pop-1"]
      and got["voices"][0]["about"] == "yours")
keys()
speech._fetched.clear()
got = run(speech.voices("cartesia"))
check("no key: typed, with why", got["typed"] and "needs a key" in got["error"])

print("\n== the providers ==")
ids = [p["id"] for p in providers.PROVIDERS]
check("five more that hear or speak", all(p in ids for p in ("deepgram", "cartesia", "fish", "rime", "minimax")))
check("This computer still last", ids[-1] == "local")
check("and some that only wrote now hear or speak too", {"stt", "tts"} <= set(providers.BY_ID["mistral"]["jobs"])
      and "tts" in providers.BY_ID["gemini"]["jobs"] and "tts" in providers.BY_ID["xai"]["jobs"]
      and "stt" in providers.BY_ID["elevenlabs"]["jobs"] and "stt" in providers.BY_ID["together"]["jobs"])
check("each says what it costs", all(p in providers.COST for p in ("deepgram", "cartesia", "fish", "rime", "minimax")))
check("a speaking model is not taken for a hearing one", providers.capabilities("mistral", "voxtral-mini-tts-3-0") == ["tts"]
      and providers.capabilities("mistral", "voxtral-mini-transcribe-3-0") == ["stt"])
keys(DEEPGRAM_API_KEY="dg-1")
providers._cache.pop("deepgram", None)
listed = providers.list_models("deepgram", {}, force=True)
check("a hearing-and-speaking provider's models, without asking it for a list",
      not listed["error"] and {m["id"] for m in listed["models"]} == {"nova-3", "nova-2", "aura-2"})
from app.utils import whatsleft  # noqa: E402

check("Usage says they keep what is left on their own pages", all(p in whatsleft.SILENT for p in
                                                                    ("deepgram", "cartesia", "fish", "rime", "minimax")))
ts = read("webui/src/lib/providers.ts")
check("each has its tile", all(f'{p}: "#' in ts for p in ("deepgram", "cartesia", "fish", "rime", "minimax")))
tile = read("webui/src/lib/components/ProviderTile.svelte")
for p in ("elevenlabs", "deepgram", "cartesia", "fish", "rime", "minimax"):
    logo = ROOT / "webui" / "public" / "providers" / f"{p}.png"
    check(f"{p} has its own mark, not its initials", f'"{p}"' in tile.split("const LOGOS", 1)[1].split("]);", 1)[0]
          and logo.is_file() and logo.read_bytes()[:4] == b"\x89PNG")
from PIL import Image  # noqa: E402

for p in ("elevenlabs", "deepgram", "cartesia", "fish", "rime", "minimax"):
    with Image.open(ROOT / "webui" / "public" / "providers" / f"{p}.png") as im:
        clear = sum(1 for a in im.getchannel("A").getdata() if a == 0) / (96 * 96)
        check(f"{p}'s is cut out, as the others are: no square behind it", im.size == (96, 96) and im.mode == "RGBA"
              and clear > 0.15, str(clear))

print("\n== voice messages, through the same ==")
import yaml  # noqa: E402

from app.utils import ai, tts  # noqa: E402

cfg_path = Path(_tmp.name) / "config" / "config.yaml"
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
cfg["bot"].setdefault("models", {})
cfg["bot"]["models"]["tts"] = {"provider": "deepgram", "model": "aura-2", "voice": "aura-2-luna-en"}
cfg["bot"]["models"]["stt"] = {"provider": "deepgram", "model": "nova-3"}
# Something has to write replies or the app will not start its AI at all: a "server on this computer" that is the
# stand-in, so nothing here reaches Groq.
cfg["bot"]["models"]["replies"] = [{"provider": "local", "model": "stand-in"}]
cfg["bot"].setdefault("local", {})["base_url"] = BASE + "/local/v1"
cfg["bot"].setdefault("tts", {})["enabled"] = True              # voice messages are off in a fresh config
cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
keys(DEEPGRAM_API_KEY="dg-1", CARTESIA_API_KEY="ca-1")
Stand.answers[("POST", "/dg/v1/speak")] = (200, "audio/l16", PCM)
targets = ai.tts_targets()
check("a speaker of its own is one target, going round its keys itself", len([t for t in targets if t["provider"] == "deepgram"]) == 1)
out = run(tts.generate_voice_message("Hello there, this is a voice note."))
check("a voice note spoken by Deepgram, as a WAV", bool(out) and read_wav(out[0])[0] == PCM
      and last("/dg/v1/speak")["query"]["model"] == "aura-2-luna-en")
Stand.answers[("POST", "/dg/v1/listen")] = (200, J, json.dumps(
    {"results": {"channels": [{"alternatives": [{"transcript": "a voice note"}]}]}}).encode())
check("and one heard by it", run(ai.transcribe_voice(b"OggS-not-really", "voice.ogg")) == "a voice note")
check("going up as it came", last("/dg/v1/listen")["body"] == b"OggS-not-really")

print("\n== a call's own picks ==")
from app.voice import session  # noqa: E402

hear, think = session.call_legs({"hear": "cartesia:ink-whisper", "think": ""})
check("thinking not picked: the replies' own", think is ai.generate_response)
said = run(hear(WAV, "call.wav"))
check("hearing picked for calls: Cartesia first, though voice messages are on Deepgram", said == "ink heard it"
      and Stand.seen[-1]["path"] == "/ca/stt")
check("and only for the call: voice messages still go where they did", run(ai.transcribe_voice(WAV, "v.wav")) == "a voice note"
      and Stand.seen[-1]["path"] == "/dg/v1/listen")
Stand.answers[("POST", "/ca/stt")] = (500, J, b'{"message": "down"}')
check("the pick down: the rest after it, as a job's fallbacks are", run(hear(WAV, "call.wav")) == "a voice note")
Stand.answers[("POST", "/ca/stt")] = (200, J, b'{"type": "transcript", "text": "ink heard it"}')

from app.voice.speak import Speaker  # noqa: E402

spk = Speaker.for_call(cfg={"bot": {"calls": {"speak": "cartesia:sonic-3.6", "voice": "v-2"}}})
check("speaking picked for calls", spk.kind == "provider" and spk.provider == "cartesia" and spk.model == "sonic-3.6"
      and spk.voice == "v-2")
pcm, _ = run(spk.say("hello"))
check("says it there", pcm == PCM and json.loads(last("/ca/tts/bytes")["body"])["voice"]["id"] == "v-2" and not spk.failed)
Stand.answers[("POST", "/ca/tts/bytes")] = (503, J, b'{"message": "busy"}')
pcm, _ = run(spk.say("hello"))
check("down mid-call: the voice messages' speaker says it, and it is noted", pcm == PCM and "503" in spk.failed
      and Stand.seen[-1]["path"] == "/dg/v1/speak")
check("in its own voice, not the one picked for Cartesia", Stand.seen[-1]["query"]["model"] == "aura-2-luna-en")
old = Speaker.for_call(cfg={"bot": {"calls": {"speaker": "elevenlabs", "voice": "v-77"}}})
check("ElevenLabs picked the old way still speaks there", old.kind == "provider" and old.provider == "elevenlabs"
      and old.model == "eleven_flash_v2_5")

from app.voice import voices  # noqa: E402

lg = voices.legs({"bot": {**cfg["bot"], "calls": {"hear": "cartesia:ink-whisper", "speak": "local:builtin:supertonic-3"}}})
check("the legs show what the call picked", lg["hear"]["provider"] == "cartesia" and lg["hear"]["own"]
      and lg["speak"]["builtin"] and lg["speak"]["local"] and not lg["think"]["own"])
df = voices.legs({"bot": {**cfg["bot"], "calls": {"hear": "cartesia:ink-whisper"}}}, picked=False)
check("and what each goes back to without a pick", df["hear"]["provider"] == "deepgram" and not df["hear"]["own"]
      and df["speak"]["voice"] == "aura-2-luna-en")

print("\n== Grok's voice model ==")
from app.voice.engines import realtime  # noqa: E402


class Ev:
    def __init__(self):
        self.heard_lines, self.states = [], []

    def heard(self, t):
        self.heard_lines.append(t)

    def state(self, s):
        self.states.append(s)

    def __getattr__(self, name):
        return lambda *a, **k: None


ev = Ev()
eng = realtime.ENGINES["xai"](key="k", instructions="be you", voice="Ara", events=ev)
check("a voice model of its own", realtime.ENGINES["xai"] is realtime.XaiRealtime and eng.provider == "xai"
      and eng.url() == "wss://api.x.ai/v1/realtime?model=grok-voice-latest")
s_ = eng.setup()[0]
check("its session as xAI documents it", s_["type"] == "session.update" and s_["session"]["voice"] == "ara"
      and s_["session"]["turn_detection"] == {"type": "server_vad"}
      and s_["session"]["audio"]["input"]["transcription"] == {"model": "grok-transcribe"}
      and s_["session"]["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000})
for t in ("hey", "hey how", "hey how are you"):
    eng.handle({"type": "conversation.item.input_audio_transcription.updated", "transcript": t})
check("a running transcript is not said until they have finished", ev.heard_lines == [])
eng.handle({"type": "response.created"})
check("then the whole of it, once", ev.heard_lines == ["hey how are you"] and "thinking" in ev.states)
eng.handle({"type": "response.created"})
check("and not again", ev.heard_lines == ["hey how are you"])
cat = run(voices.catalogue({"bot": {"calls": {}}}))
check("its voices on offer, and whether there is a key", len(cat["realtime"]["xai"]["voices"]) == 26
      and cat["realtime"]["xai"]["voices"][0]["name"] == "Eve" and "has_key" in cat["realtime"]["xai"])
check("the Calls tab is told about this computer's own voice", cat["local"]["models"]
      and {m["id"] for m in cat["local"]["models"]} == {"builtin:whisper-tiny", "builtin:whisper-base", "builtin:supertonic-3"})
check("and what each leg goes back to", set(cat["defaults"]) >= {"hear", "think", "speak"})

print("\n== the routes ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import call_routes  # noqa: E402

app = FastAPI()
app.include_router(call_routes.router)
client = TestClient(app)
r = client.get("/api/calls/speaker-voices", params={"provider": "deepgram", "model": "aura-2"})
check("a speaker's voices, asked for", r.status_code == 200 and len(r.json()["voices"]) >= 80)
r = client.get("/api/calls/local")
check("this computer's own voice, as it stands", r.status_code == 200 and r.json()["engine"] is False
      and len(r.json()["models"]) == 3)
r = client.post("/api/calls/local/get", json={"model": "builtin:nothing"})
check("a model it does not know is refused", r.status_code == 409)
Stand.answers[("POST", "/dg/v1/speak")] = (200, "audio/l16", PCM)
r = client.post("/api/calls/preview", json={"engine": "own", "provider": "deepgram", "model": "aura-2",
                                            "voice": "aura-2-zeus-en"})
check("hearing any speaker's voice before picking it", r.status_code == 200 and r.content[:4] == b"RIFF"
      and Stand.seen[-1]["query"]["model"] == "aura-2-zeus-en")
check("the call is tried with what is on screen, the three included",
      {"hear", "think", "speak"} <= set(call_routes._ON_SCREEN))

print("\n== the panel ==")
panel = read("webui/src/lib/components/CallSetup.svelte")
check("Grok among the voice models", '{ id: "xai", label: "Grok" }' in panel)
check("the speaker's own voices asked for when it changes", "api.callSpeakerVoices(pid, model, scope)" in panel)
check("Try a call and Time a turn take the three as they are on screen", "...onScreen()" in panel
      and panel.count("...onScreen()") == 2 and 'hear: String(get("bot.calls.hear")' in panel)
check("a voice from one speaker is not kept for another", 'set("bot.calls.voice", "")' in panel)

speech.URLS.clear()
server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
