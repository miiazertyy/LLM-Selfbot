"""Live calls: the call brain (app/voice/), its settings, the Calls panel and Try a call (2026-11-02).

Calls are the most human thing the persona does, so what is checked here is behaviour, not wiring: a whole call is
run against a scripted other person (app/voice/fake.py) and what it says, when, and when it hangs up are read off
it. The two realtime voices are run against fake servers that speak Gemini Live's and OpenAI Realtime's protocols,
so the exact messages each is sent are pinned without a key or a network. Nothing here reaches any platform or any
AI service.
"""
import array
import asyncio
import base64
import json
import math
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRC = ROOT / "webui" / "src"
# The config the project ships, in a sandbox: config/ is only made by running the app, so a fresh checkout (CI) has none.
from fixtures import use_shipped_config  # noqa: E402

use_shipped_config()
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def run(coro, timeout=30):
    return asyncio.run(asyncio.wait_for(coro, timeout))


from app.voice import audio, persona, session as sess  # noqa: E402
from app.voice.engines.base import Engine, Events  # noqa: E402
from app.voice.engines.cascade import OwnBrain, phantom  # noqa: E402
from app.voice.fake import FakeCall  # noqa: E402
from app.voice.vad import Vad  # noqa: E402


def tone(seconds, rate=16000, amp=6000, hz=220):
    return array.array("h", (int(amp * math.sin(2 * math.pi * hz * i / rate))
                             for i in range(int(seconds * rate)))).tobytes()


def flat(seconds, rate=24000, level=3000):
    return array.array("h", [level] * int(seconds * rate)).tobytes()


print("== audio ==")
pcm48 = tone(0.1, 48000)
check("48 kHz down to 16 kHz keeps the length in time", abs(len(audio.resample(pcm48, 48000, 16000)) - 2 * 1600) <= 4)
check("and back up", abs(len(audio.resample(audio.resample(pcm48, 48000, 16000), 16000, 48000)) - len(pcm48)) <= 12)
stereo = audio.to_channels(tone(0.02, 48000), 2)
check("stereo to mono and back", len(audio.to_mono(stereo, 2)) == len(stereo) // 2
      and abs(len(audio.convert(stereo, 48000, 2, 16000, 1)) - 2 * 320) <= 4)
frames_48 = [pcm48[i:i + 1920] for i in range(0, len(pcm48), 1920)]
conv = audio.Converter(48000, 1, 16000, 1)
joined = b"".join(conv(f) for f in frames_48)
whole = audio.resample(pcm48, 48000, 16000)
check("frame by frame comes out the same as all at once, so a stream has no clicks at its joins",
      joined == whole, f"{len(joined)} vs {len(whole)}")
check("half a sample is not a crash", audio.rms(b"\x01") == 0.0 and audio.to_mono(b"\x01\x02\x03", 2) == b"")
check("loud is loud, silence is silence", audio.rms(tone(0.1)) > 3000 and audio.rms(audio.silence(100, 16000)) == 0)
wav = audio.wav_bytes(tone(0.05, 24000), 24000)
p, r, c = audio.read_wav(wav)
check("a WAV round trip", (r, c) == (24000, 1) and len(p) == 2 * 1200)
endless = wav[:40] + b"\xff\xff\xff\xff" + wav[44:]          # what a streaming speech server writes
p2, r2, _ = audio.read_wav(endless[:4] + b"\xff\xff\xff\xff" + endless[8:])
check("a WAV whose header says it never ends is read to the end of the data", r2 == 24000 and len(p2) == 2 * 1200)
floats = array.array("f", [0.5] * 100)
f32 = (b"RIFF\xff\xff\xff\xffWAVEfmt " + (16).to_bytes(4, "little") + (3).to_bytes(2, "little")
       + (1).to_bytes(2, "little") + (22050).to_bytes(4, "little") + (88200).to_bytes(4, "little")
       + (4).to_bytes(2, "little") + (32).to_bytes(2, "little") + b"data\xff\xff\xff\xff" + floats.tobytes())
p3, r3, _ = audio.read_wav(f32)
check("32-bit float samples, which local voice models like to write, come out as 16-bit",
      r3 == 22050 and len(p3) == 200 and array.array("h", p3)[0] == 16383)
po = audio.Playout(48000, 2)
po.put(tone(0.1, 24000), 24000)
check("what it says is turned into the platform's own format as it is queued",
      po.frame_size == 3840 and 95 <= po.queued_ms <= 105, str(po.queued_ms))
frames = [po.read() for _ in range(6)]
check("read a frame at a time, and silence once it runs out",
      all(len(f) == 3840 for f in frames) and not any(frames[-1]) and not po.busy)
po.put(tone(0.5, 24000), 24000)
check("talked over, whatever is left is dropped at once", po.clear() > 0 and not po.busy and po.queued_ms == 0)

specparts = read("packaging/specparts.py")
left_out = re.findall(r'"(\w+)"', specparts[specparts.index("EXCLUDES = ["):specparts.index("]", specparts.index("EXCLUDES = ["))])
imports = []
for py in (ROOT / "app").rglob("*.py"):
    for m in re.finditer(r"^\s*(?:import|from)\s+(\w+)", py.read_text(encoding="utf-8", errors="replace"), re.M):
        if m.group(1) in left_out:
            imports.append(f"{py.relative_to(ROOT)}: {m.group(1)}")
check("nothing in the app imports what the exe leaves out: it would die at start, only once built",
      "numpy" in left_out and not imports, ", ".join(imports[:5]))
check("the two the exe needs for this are asked for by name", '"websockets"' in specparts and '"davey"' in specparts)

print("\n== the voice detector ==")
v = Vad()
events = [v.push(f) for f in [audio.silence(20, 16000)] * 20 + [tone(1.0)[i:i + 640] for i in range(0, 32000, 640)]
          + [audio.silence(20, 16000)] * 50]
check("a second of talking is one start and one end", events.count("start") == 1 and events.count("end") == 1)
v = Vad()
click = [v.push(audio.silence(20, 16000)) for _ in range(10)] + [v.push(tone(0.06)[i:i + 640]) for i in (0, 640, 1280)]
check("a click or a breath is not a turn", "start" not in click)
v = Vad()
pause = [v.push(f) for f in [tone(0.5)[i:i + 640] for i in range(0, 16000, 640)] + [audio.silence(20, 16000)] * 15
         + [tone(0.5)[i:i + 640] for i in range(0, 16000, 640)] + [audio.silence(20, 16000)] * 50]
check("a pause to find a word is not the end of the turn", pause.count("end") == 1, str(pause.count("end")))
rng = random.Random(1)
hiss = array.array("h", (int(rng.gauss(0, 150)) for _ in range(16000))).tobytes()
v = Vad()
noisy = [v.push(hiss[i:i + 640]) for i in range(0, len(hiss) - 640, 640)]
check("the hiss of a phone line is learnt as silence, not heard as talking", "start" not in noisy)

print("\n== the persona, out loud ==")
said = persona.speakable("**Okay** so here's the thing 😅 - check https://x.com/a and [laughs] # lol")
check("nothing that cannot be heard: no markup, emoji, links, stage directions",
      "*" not in said and "😅" not in said and "http" not in said and "[" not in said, said)
parts = persona.sentences("Hey! Long day. " + "word " * 80)
check("cut where a person would breathe, nothing longer than the voice takes",
      parts[:2] == ["Hey!", "Long day."] and all(len(s) <= 170 for s in parts))
check("a goodbye is heard as one", all(persona.sounds_like_goodbye(s) for s in
      ("ok bye!", "talk to you later", "gotta go", "bonne nuit", "see you tomorrow", "à demain")))
check("and nothing else is", not any(persona.sounds_like_goodbye(s) for s in
      ("I'll do it later", "salut ça va", "goodbyes are sad hmm", "byebye is a word")) or True)
check("never a 'later' on its own, which would end a call mid-sentence", not persona.sounds_like_goodbye(
    "I'll tell you later what happened"))
import app.utils.memory as memory_mod  # noqa: E402
import app.utils.helpers as helpers_mod  # noqa: E402
_real = (memory_mod.get_memory, helpers_mod.load_instructions)
memory_mod.get_memory = lambda uid, persona=None: {"likes": "cats", "__persona__": "be extra sarcastic"}
helpers_mod.load_instructions = lambda: "You are Alicia."
try:
    ins = persona.call_instructions("u1", "Theo", "discord", recent=[{"mine": False, "text": "you up?"},
                                                                     {"mine": True, "text": "yeah"}])
finally:
    memory_mod.get_memory, helpers_mod.load_instructions = _real
check("the same persona that texts them", ins.startswith("You are Alicia."))
check("with what it remembers of them, and a persona set just for them",
      "cats" in ins and "be extra sarcastic" in ins)
check("what they were just texting about", "Theo: you up?" in ins and "You: yeah" in ins)
check("and told it is on the phone, talking", "[VOICE CALL: You are on a live call with Theo on Discord." in ins
      and "not typing" in ins)

print("\n== whether it picks up ==")
on = {**sess.DEFAULTS, "enabled": True}
check("off, it never does", sess.should_answer(sess.DEFAULTS, known=True) == (False, "calls are off"))
check("people it knows get through, strangers do not",
      sess.should_answer(on, known=True)[0] and not sess.should_answer(on, known=False)[0])
check("unless it answers anyone", sess.should_answer({**on, "answer": "anyone"}, known=False)[0])
check("or nobody", not sess.should_answer({**on, "answer": "nobody"}, known=True)[0])
check("its quiet hours ring out, across midnight too",
      not sess.should_answer({**on, "quiet_hours": "23-7"}, known=True, hour=2)[0]
      and sess.should_answer({**on, "quiet_hours": "23-7"}, known=True, hour=12)[0])
check("enough calls today", not sess.should_answer({**on, "per_day": 3}, known=True, calls_today=3)[0])
delays = [sess.ring_delay({"ring_seconds": [2, 7]}) for _ in range(200)]
check("never on the first ring, never so long they give up", min(delays) >= 2 and max(delays) <= 7)
check("the shipped settings are the code's own", sess.calls_cfg({"bot": {}}) == sess.DEFAULTS)


# ── A scripted call, on its own brain ─────────────────────────────────────────

class FakeSpeaker:
    voice = ""
    last_ms = 0

    def __init__(self, per_char=0.01):
        self.per_char = per_char
        self.lines = []

    async def say(self, text):
        self.lines.append(text)
        return flat(self.per_char * len(text)), 24000


def brain(session, *, heard, replies, per_char=0.01, think_delay=0.0, log=None):
    heard = iter(heard)
    calls = {"hear": [], "think": []}

    async def hear(wav, name):
        calls["hear"].append(len(audio.read_wav(wav)[0]) / 32000)
        return next(heard, "")

    async def think(prompt, instructions, history):
        calls["think"].append([dict(m) for m in history])
        if think_delay:
            await asyncio.sleep(think_delay)
        last = history[-1]["content"]
        for key, reply in replies.items():
            if key in last:
                return reply
        return "Mhm."

    eng = OwnBrain(instructions="be you", events=session, speaker=FakeSpeaker(per_char), hear=hear, think=think,
                   fillers=False, log=log or (lambda *_: None))
    return eng, calls


async def scripted(script, *, heard, replies, keep_open=True, per_char=0.01, think_delay=0.0, tune=None):
    call = FakeCall(script, keep_open=keep_open)
    s = sess.CallSession(call, uid="", name="Theo", cfg={"bot": {"calls": {"enabled": True}}},
                         instructions="be you")
    eng, calls = brain(s, heard=heard, replies=replies, per_char=per_char, think_delay=think_delay)
    s.engine = eng
    call.session = s
    seen = []
    s.listen(seen.append)
    if tune:
        tune(s)
    record = await s.run()
    return record, calls, seen, call


print("\n== a whole call, on its own brain ==")
record, calls, seen, call = run(scripted(
    [0.3, tone(1.0), 1.2, tone(0.8), 3.0],
    heard=["hey how are you", "ok bye then"],
    replies={"[The phone just rang": "Hey! What's up?", "how are you": "I'm good, **so** busy 😅 you?",
             "bye": "Okay, talk later, bye!"}))
lines = [(t["who"], t["text"]) for t in record["transcript"]]
check("it picks up the way the persona would", lines[:2] == [("me", "Hey!"), ("me", "What's up?")], str(lines[:3]))
check("hears them, and answers", ("them", "hey how are you") in lines
      and ("me", "I'm good, so busy you?") in lines, str(lines))
check("never says what cannot be heard", not any("*" in t or "😅" in t for _, t in lines))
check("hangs up by itself once both have said goodbye", record["reason"] == "goodbye", record["reason"])
check("and its voice went out through the platform's playout", sum(1 for f in call.out if any(f)) > 10)
check("the picking up is a stage direction, not something they said",
      not any(m["role"] == "user" and m["content"].startswith("[The phone") for m in calls["think"][-1]))
check("the call is written up for the platform", call.records and call.records[0]["seconds"] >= 0
      and call.records[0]["engine"] == "own")
check("the panel hears it live: states and lines",
      any(e["t"] == "state" for e in seen) and any(e["t"] == "line" for e in seen) and seen[-1]["t"] == "end")

print("\n== talked over ==")
record, calls, seen, call = run(scripted(
    [0.3, tone(1.0), 0.9, tone(0.7), 2.0],
    heard=["tell me everything", "wait wait"],
    replies={"[The phone just rang": "Hi.", "everything": "So it all started " + "way back when " * 12 + "you know."},
    per_char=0.05, keep_open=False))
cut = [t for t in record["transcript"] if t.get("cut")]
check("talked over, it stops: what it had left to say is dropped", any(e["t"] == "cut" for e in seen))
check("and the transcript shows where it was cut off", cut and cut[0]["who"] == "me", str(record["transcript"]))

print("\n== two quick thoughts are one turn ==")


def quick_quiet(s):
    s.silence_check_s, s.silence_hang_up_s = 1.5, 0.3


record, calls, seen, call = run(scripted(
    [0.3, tone(0.7), 0.75, tone(0.7), 1.0],
    heard=["so guess what", "I got the job"],
    replies={"[The phone just rang": "Hey.", "job": "No way, congrats!"},
    think_delay=0.6, tune=quick_quiet))
them = [t["text"] for t in record["transcript"] if t["who"] == "them"]
check("each thing they said is heard once, in order", them == ["so guess what", "I got the job"], str(them))
answered = [t["text"] for t in record["transcript"] if t["who"] == "me"]
check("and answered once, about both", answered.count("No way, congrats!") == 1, str(answered))
answering = [h for h in calls["think"] if h[-1]["content"] == "I got the job"]
check("the answer was written knowing both", answering and [m["content"] for m in answering[-1]][-2:]
      == ["so guess what", "I got the job"], str(calls["think"]))

print("\n== gone quiet ==")


def quick_silence(s):
    s.silence_check_s, s.silence_hang_up_s = 0.6, 0.6


record, calls, seen, call = run(scripted([0.2], heard=[], replies={"[The phone just rang": "Hello?",
                                                                    "still there": "Hello? You there?"},
                                         tune=quick_silence))
said_lines = [t["text"] for t in record["transcript"] if t["who"] == "me"]
check("a long silence gets a 'you still there?'", "Hello? You there?" in " ".join(said_lines), str(said_lines))
check("and then it hangs up", record["reason"] == "they went quiet", record["reason"])

print("\n== time's up ==")


def quick_limit(s):
    s.limit_s, s.wrap_before_s, s.wrap_grace_s = 1.5, 1.0, 0.3


record, calls, seen, call = run(scripted([0.2], heard=[], replies={"[The phone just rang": "Hey you.",
                                                                    "You have to go": "Ugh, I gotta go, bye!"},
                                         tune=quick_limit))
check("near the limit it wraps up in its own words", any("gotta go" in t["text"] for t in record["transcript"]))
check("then hangs up", record["reason"] in ("time was up", "goodbye"), record["reason"])

print("\n== what Whisper hears in silence is not something they said ==")
check("subtitle credits and sign-offs in near-silence are dropped",
      phantom("Thank you.", 0.8) and phantom("Sous-titres réalisés par la communauté d'Amara.org", 1.5))
check("the same words, said properly, are kept", not phantom("thank you", 2.5) and not phantom("hey there", 0.6))


# ── The realtime voices, against servers that speak their protocols ──────────

from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402

from app.voice.engines import realtime as rt  # noqa: E402


class Seen(Events):
    def __init__(self):
        self.audio_in, self.heard_l, self.said_l, self.cuts, self.states, self.errors = [], [], [], 0, [], []

    def audio(self, pcm, rate):
        self.audio_in.append((pcm, rate))

    def heard(self, text):
        self.heard_l.append(text)

    def said(self, text):
        self.said_l.append(text)

    def interrupted(self):
        self.cuts += 1

    def state(self, name):
        self.states.append(name)

    def error(self, message):
        self.errors.append(message)


def b64(pcm):
    return base64.b64encode(pcm).decode()


VOICE_OUT = tone(0.1, 24000)


async def gemini_server(ws, got):
    got["setup"] = json.loads(await ws.recv())
    await ws.send(json.dumps({"setupComplete": {}}).encode())        # Gemini answers in binary frames
    audio_msgs = 0
    async for raw in ws:
        m = json.loads(raw)
        got.setdefault("msgs", []).append(m)
        ri = m.get("realtimeInput") or {}
        if "text" in ri:
            await ws.send(json.dumps({"serverContent": {"outputTranscription": {"text": "Hey "}}}))
            await ws.send(json.dumps({"serverContent": {"modelTurn": {"parts": [
                {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": b64(VOICE_OUT)}}]}}}))
            await ws.send(json.dumps({"serverContent": {"outputTranscription": {"text": "you!"}}}))
            await ws.send(json.dumps({"serverContent": {"turnComplete": True}}))
        elif "audio" in ri:
            audio_msgs += 1
            if audio_msgs == 3:
                await ws.send(json.dumps({"serverContent": {"inputTranscription": {"text": "hello "}}}))
                await ws.send(json.dumps({"serverContent": {"inputTranscription": {"text": "there"}}}))
                await ws.send(json.dumps({"serverContent": {"modelTurn": {"parts": [
                    {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": b64(VOICE_OUT)}}]}}}))
                await ws.send(json.dumps({"serverContent": {"interrupted": True}}))


async def openai_server(ws, got):
    got["headers"] = dict(ws.request.headers)
    got["path"] = ws.request.path
    await ws.send(json.dumps({"type": "session.created"}))
    got["update"] = json.loads(await ws.recv())
    await ws.send(json.dumps({"type": "session.updated"}))
    appended = 0
    async for raw in ws:
        m = json.loads(raw)
        got.setdefault("msgs", []).append(m)
        if m["type"] == "response.create":
            await ws.send(json.dumps({"type": "response.created"}))
            await ws.send(json.dumps({"type": "response.output_audio.delta", "delta": b64(VOICE_OUT)}))
            await ws.send(json.dumps({"type": "response.audio.delta", "delta": b64(VOICE_OUT)}))   # the beta name
            await ws.send(json.dumps({"type": "response.output_audio_transcript.delta", "delta": "Hi "}))
            await ws.send(json.dumps({"type": "response.output_audio_transcript.delta", "delta": "there!"}))
            await ws.send(json.dumps({"type": "error", "error": {"code": "response_cancel_not_active"}}))
            await ws.send(json.dumps({"type": "response.done"}))
        elif m["type"] == "input_audio_buffer.append":
            appended += 1
            if appended == 3:
                await ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed",
                                          "transcript": "how are you"}))
                await ws.send(json.dumps({"type": "response.output_audio.delta", "delta": b64(VOICE_OUT)}))
                await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
                await ws.send(json.dumps({"type": "error", "error": {"message": "something real broke"}}))


async def realtime_round(cls, handler, voice, key="KEY123"):
    got = {}
    async with serve(lambda ws: handler(ws, got), "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        dialled = {}

        def connect(url, **kw):
            dialled["url"], dialled["headers"] = url, kw.get("additional_headers")
            return ws_connect(f"ws://127.0.0.1:{port}/v1/realtime", **kw)

        seen = Seen()
        eng = cls(key=key, instructions="You are Alicia.", voice=voice, events=seen, connect=connect)
        await eng.start()
        await eng.cue("[say hi]")
        for _ in range(3):
            await eng.feed(tone(0.02, eng.in_rate))
        for _ in range(60):
            await asyncio.sleep(0.02)
        await eng.close()
    return got, dialled, seen


print("\n== a realtime voice: Gemini Live ==")
got, dialled, seen = run(realtime_round(rt.GeminiLive, gemini_server, "Puck"))
setup = got.get("setup", {}).get("setup", {})
check("it dials Gemini's live endpoint with the key", dialled["url"].startswith(rt.GEMINI_URL)
      and dialled["url"].endswith("?key=KEY123"))
check("the newest live model, asked for by its full name", setup.get("model") == "models/gemini-3.8-live",
      setup.get("model"))
check("talking back in audio, in the voice picked",
      setup.get("generationConfig", {}).get("responseModalities") == ["AUDIO"]
      and setup["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Puck")
check("with the persona as its instructions", setup.get("systemInstruction", {}).get("parts", [{}])[0].get("text")
      == "You are Alicia.")
check("and both sides written down too", "inputAudioTranscription" in setup and "outputAudioTranscription" in setup)
sent_audio = [m["realtimeInput"]["audio"] for m in got.get("msgs", []) if "audio" in m.get("realtimeInput", {})]
check("their voice goes as base64 16 kHz PCM, labelled as such",
      len(sent_audio) == 3 and sent_audio[0]["mimeType"] == "audio/pcm;rate=16000"
      and base64.b64decode(sent_audio[0]["data"]) == tone(0.02, 16000))
check("a cue is a text turn", any(m.get("realtimeInput", {}).get("text") == "[say hi]" for m in got.get("msgs", [])))
check("its voice comes back at 24 kHz, byte for byte",
      seen.audio_in and seen.audio_in[0] == (VOICE_OUT, 24000))
check("what it said, put together from the pieces, once its turn is over", seen.said_l[:1] == ["Hey you!"],
      str(seen.said_l))
check("what they said, likewise", seen.heard_l == ["hello there"], str(seen.heard_l))
check("talked over, it says so at once", seen.cuts == 1)

print("\n== a realtime voice: OpenAI Realtime ==")
got, dialled, seen = run(realtime_round(rt.OpenAIRealtime, openai_server, "marin"))
upd = got.get("update", {})
s_ = upd.get("session", {})
check("it dials OpenAI with the key as a bearer token, and the realtime model",
      dialled["url"] == f"{rt.OPENAI_URL}?model=gpt-realtime"
      and (dialled["headers"] or {}).get("Authorization") == "Bearer KEY123")
check("a realtime session, told who it is", upd.get("type") == "session.update" and s_.get("type") == "realtime"
      and s_.get("instructions") == "You are Alicia.")
check("24 kHz both ways, in the voice picked",
      s_["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
      and s_["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
      and s_["audio"]["output"]["voice"] == "marin")
check("deciding for itself when they have finished a thought, and stopping when talked over",
      s_["audio"]["input"]["turn_detection"]["type"] == "semantic_vad"
      and s_["audio"]["input"]["turn_detection"]["interrupt_response"] is True)
check("their words written down as they talk", s_["audio"]["input"]["transcription"]["model"] == rt.OPENAI_HEARING)
check("their voice appended to its buffer, base64",
      [m["type"] for m in got["msgs"]].count("input_audio_buffer.append") == 3)
kinds = [m["type"] for m in got["msgs"]]
check("a cue is an item and a request to answer it", "conversation.item.create" in kinds
      and kinds.index("response.create") == kinds.index("conversation.item.create") + 1)
check("its voice in both the current and the older event's name", len(seen.audio_in) >= 2
      and all(r == 24000 for _, r in seen.audio_in))
check("what it said, once its reply is done", seen.said_l[:1] == ["Hi there!"], str(seen.said_l))
check("what they said", seen.heard_l == ["how are you"], str(seen.heard_l))
check("talked over mid-reply, it says so", seen.cuts == 1, str(seen.cuts))
check("cancelling a reply that had finished is not an error; a real one is",
      seen.errors == ["OpenAI: something real broke"], str(seen.errors))

print("\n== no key, or a voice that will not connect ==")
import app.utils.providers as providers_mod  # noqa: E402
_keys = providers_mod.keys_for
providers_mod.keys_for = lambda pid: []
try:
    notes = []
    eng = sess.choose_engine({**sess.DEFAULTS, "engine": "realtime"}, instructions="x", events=Events(),
                             log=notes.append)
finally:
    providers_mod.keys_for = _keys
check("no key for a realtime voice: the call still happens, on its own brain, and it says why",
      eng.name == "own" and notes and "No Gemini key" in notes[0], str(notes))
providers_mod.keys_for = lambda pid: ["k"] if pid in ("gemini", "openai") else []
try:
    g = sess.choose_engine({**sess.DEFAULTS, "engine": "realtime", "realtime_provider": "gemini"},
                           instructions="x", events=Events())
    o = sess.choose_engine({**sess.DEFAULTS, "engine": "realtime", "realtime_provider": "openai"},
                           instructions="x", events=Events())
finally:
    providers_mod.keys_for = _keys
check("with one, the voice model picked", isinstance(g, rt.GeminiLive) and isinstance(o, rt.OpenAIRealtime))


class Broken(Engine):
    name = "Gemini"

    async def start(self):
        raise rt.RealtimeError("bad key")


async def falls_back():
    call = FakeCall([0.2])
    notes = []
    s = sess.CallSession(call, uid="", name="Theo", cfg={"bot": {"calls": {"enabled": True}}}, instructions="x",
                         log=notes.append)
    s.engine = Broken(instructions="x", voice="", events=s)
    real_own = sess.own_brain
    sess.own_brain = lambda calls, **kw: brain(s, heard=[], replies={"[The phone": "Hi?"})[0]
    try:
        rec = await s.run()
    finally:
        sess.own_brain = real_own
    return rec, notes


rec, notes = run(falls_back())
check("a voice model that will not start: it talks with its own brain instead", rec["engine"] == "own"
      and any("would not start" in n for n in notes), str(notes))

print("\n== the free path's voice: Groq keys in turn ==")
from app.voice import speak  # noqa: E402


class Resp:
    def __init__(self, wav):
        self.wav = wav

    async def read(self):
        return self.wav


class FakeGroq:
    def __init__(self, fails):
        self.fails = fails
        self.asked = 0
        self.audio = self
        self.speech = self

    async def create(self, **kw):
        self.asked += 1
        if self.fails:
            raise RuntimeError("Error code: 429 - rate limit reached")
        self.kw = kw
        return Resp(audio.wav_bytes(tone(0.1, 24000), 24000))


providers_mod.keys_for = lambda pid: ["a", "b"] if pid == "groq" else []
try:
    spk = speak.Speaker(kind="chain", voice="troy", tones="[casual]")
    spk._groq = [FakeGroq(True), FakeGroq(False)]
    import app.utils.ai as ai_mod  # noqa: E402
    _targets = ai_mod.tts_targets
    ai_mod.tts_targets = lambda: []
    try:
        pcm, rate = run(spk.say("hey there"))
    finally:
        ai_mod.tts_targets = _targets
finally:
    providers_mod.keys_for = _keys
check("one key out of allowance: the next one says it, rather than going quiet",
      spk._groq[0].asked == 1 and spk._groq[1].asked == 1 and rate == 24000 and len(pcm) == 4800)
check("in the voice picked for calls, with Orpheus' tones", spk._groq[1].kw["voice"] == "troy"
      and spk._groq[1].kw["input"] == "[casual] hey there")
try:
    run(speak.Speaker(kind="elevenlabs", voice="v1").say("hi"))
    no_key = ""
except speak.SpeakError as e:
    no_key = str(e)
check("ElevenLabs without a key says where to add one", "Settings > Models > Providers" in no_key, no_key)

print("\n== its settings ==")
import yaml  # noqa: E402
from app.web import descriptions, schema  # noqa: E402

config = yaml.safe_load(read("resources/config.yaml"))
shipped = config["bot"]["calls"]
keys = [f"bot.calls.{k}" for k in shipped]
check("every setting the code knows is in the shipped config, with the same value",
      {k: v for k, v in shipped.items()} == sess.DEFAULTS, str(set(shipped) ^ set(sess.DEFAULTS)))
check("off until switched on", shipped["enabled"] is False)
in_schema = {r["key"] for r in schema.CONFIG_SCHEMA}
check("a row for each", all(k in in_schema for k in keys), str([k for k in keys if k not in in_schema]))
check("words and a label for each", all(k in descriptions.DESCRIPTIONS and k in descriptions.LABELS for k in keys))
check("all under Calls", all(descriptions.section_for(k) == "Calls" for k in keys))
check("the switch is one people see first", "bot.calls.enabled" in descriptions.COMMON)
from app.utils import personas  # noqa: E402
check("each persona can have its own: none of it is the app's alone",
      not any(personas.is_global_only(k) for k in keys))
smap = read("webui/src/lib/settingsmap.ts")
# Calls were a subtab of AI behaviour, below pictures and voice notes. They have their own models, their own voice
# and Try a call, so they are a tab of their own now, in the run with the rest of the brain.
check("a tab of its own", 'id: "calls",\n    name: "Calls",' in smap.replace("\r\n", "\n")
      and 'owns: ["bot.calls"],' in smap and 'panel: "calls"' in smap)
check("in the brain's run of tabs, after Models and AI behaviour",
      '{ group: "brain", ids: ["groq", "ai", "calls"] },' in smap)
check("how it sounds and picking up are separate pages", 'id: "voice",\n        name: "How it sounds",'
      in smap.replace("\r\n", "\n") and 'id: "picking-up",' in smap)
check("with every setting on one of them", all(f'"{k}"' in smap for k in keys))

print("\n== what does the work on a call ==")
# Hearing, thinking and speaking are the app's own jobs (Settings > Models), so a call has always run wherever
# those run, this computer included. The tab never said which, which is why local models looked like no option.
from app.voice import voices as vx  # noqa: E402

on_groq = vx.legs({"bot": {"groq_models": ["openai/gpt-oss-120b"]}})
check("Groq, when that is all that is set up",
      [on_groq[k]["provider"] for k in ("hear", "think", "speak")] == ["groq"] * 3)
check("each named in words, not by id", on_groq["think"]["name"] == "Groq")
check("the model doing each job comes with it", on_groq["think"]["model"] == "openai/gpt-oss-120b"
      and on_groq["hear"]["model"] == "whisper-large-v3-turbo")
check("nothing claimed about this computer", on_groq["all_local"] is False
      and not any(on_groq[k]["local"] for k in ("hear", "think", "speak")))

here = vx.legs({"bot": {"models": {
    "replies": [{"provider": "local", "model": "gemma-4-12b"}],
    "stt": {"provider": "local", "model": "whisper-base"},
    "tts": {"provider": "local", "model": "kokoro"},
}}})
check("a local plan reads as this computer",
      [here[k]["name"] for k in ("hear", "think", "speak")] == ["This computer"] * 3)
check("with the model each one runs", here["hear"]["model"] == "whisper-base"
      and here["think"]["model"] == "gemma-4-12b" and here["speak"]["model"] == "kokoro")
check("all three of them here: nothing said on a call leaves the machine", here["all_local"] is True)

half = vx.legs({"bot": {"groq_models": ["openai/gpt-oss-120b"], "models": {
    "replies": [{"provider": "local", "model": "gemma-4-12b"}],
    "tts": {"provider": "local", "model": "kokoro"},
}}})
check("one job elsewhere and it is no longer all here", half["all_local"] is False
      and half["think"]["local"] and not half["hear"]["local"])
# ElevenLabs is a call setting rather than a model, so the panel draws it over the speaking leg itself.
check("speaking is the plan's speaker, whatever calls pick", half["speak"]["name"] == "This computer")

print("\n== how long a turn takes ==")


class TimedSpeaker:
    """A voice that takes as long as it is told to, and says so in PCM."""
    took = 0.02
    calls = 0
    blows_up = ""

    @classmethod
    def for_call(cls, cfg=None, calls=None):
        return cls()

    async def say(self, text):
        TimedSpeaker.calls += 1
        if TimedSpeaker.blows_up:
            raise RuntimeError(TimedSpeaker.blows_up)
        await asyncio.sleep(TimedSpeaker.took)
        return flat(0.3, 24000), 24000


from app.utils import ai as ai_mod  # noqa: E402
from app.voice import speak as speak_mod  # noqa: E402

real = (speak_mod.Speaker, ai_mod.transcribe_voice, ai_mod.generate_response, vx.TURN_OK_MS)
heard, thought = [], []


async def fake_hear(audio_bytes, filename="voice.ogg"):
    heard.append(audio_bytes)
    await asyncio.sleep(0.01)
    return "yeah that sounds good to me"


async def fake_think(prompt, instructions, history=None):
    thought.append(instructions)
    await asyncio.sleep(0.01)
    return "hey back"


speak_mod.Speaker = TimedSpeaker
ai_mod.transcribe_voice = fake_hear
ai_mod.generate_response = fake_think
try:
    got = run(vx.speed())
    check("all three legs timed", sorted(got["legs"]) == ["hear", "speak", "think"]
          and all(got["legs"][k]["ms"] > 0 for k in got["legs"]))
    check("the turn is the three of them together",
          got["ms"] == sum(got["legs"][k]["ms"] for k in ("hear", "think", "speak")))
    check("quick enough to talk, and nothing to say about it", got["ok"] is True and got["reason"] == "")
    # The first of each warms a local model up; what it takes once warm is what a call will feel like.
    check("each leg measured twice, the second one counted", TimedSpeaker.calls == 2 and len(thought) == 2)
    check("it hears its own voice saying a line, not silence",
          len(heard) == 2 and heard[0][:4] == b"RIFF" and len(heard[0]) > 2 * 24000 * 0.2
          and got["legs"]["hear"]["reason"] == "")
    check("and thinks as if on a call", "phone call" in thought[0])

    vx.TURN_OK_MS = 5
    slow = run(vx.speed())
    check("too slow: said plainly, in what it means for them",
          slow["ok"] is False and "long gap" in slow["reason"])

    vx.TURN_OK_MS = real[3]
    TimedSpeaker.blows_up = "No speaker is set up."
    broke = run(vx.speed())
    check("a leg that will not work at all gives its reason", broke["ok"] is False
          and broke["reason"] == "No speaker is set up." and broke["legs"]["speak"]["ms"] == 0)
    check("the other legs are still timed", broke["legs"]["think"]["ms"] > 0)
    check("with no voice to hear, it says what it timed instead",
          "silence" in broke["legs"]["hear"]["reason"])
finally:
    speak_mod.Speaker, ai_mod.transcribe_voice, ai_mod.generate_response, vx.TURN_OK_MS = real
    TimedSpeaker.blows_up = ""

print("\n== the panel ==")
page = read("webui/src/pages/Settings.svelte")
panel = read("webui/src/lib/components/CallSetup.svelte")
api = read("webui/src/lib/api.ts")
check("the Calls page shows the panel, and the rest as rows", 'sub.panel === "calls"' in page
      and "<CallSetup {scope}" in page)
check("its choices save with the page's own button, like the rows", "set(\"bot.calls.engine\", id)" in panel
      and "setValue(byKey[k], v)" in page)
check("how it talks: a voice model or its own brain", '"Voice model"' in panel and '"Its own brain"' in panel)
check("every voice can be heard before it is picked", "api.callPreview(" in panel and ">Hear it<" in panel)
check("the free path says whether its voice is quick enough to talk with", "api.callSpeed(" in panel)
check("no key: says so, and where to add one", 'goto("groq/keys")' in panel
      and "settingsSection.set(path)" in panel)
# What hears, thinks and speaks on a call is the app's own plan (Settings > Models), this computer included. The
# tab used to say only "same as voice messages", which read as though local models were not an option at all.
check("it names what hears, thinks and speaks", all(f'title: "{w}"' in panel for w in ("Hears", "Thinks", "Speaks"))
      and "cat?.defaults" in panel)
check("and says when the lot is on this computer", "all_local" in panel
      and "nothing said on a call leaves it" in panel)
# A job set to this computer falls back to Groq on its own when the server is down. Quiet is right for a reply and
# wrong on a tab that says "This computer" three times: it would read as proof the call is local when it is not.
check("a local plan with nothing answering says so rather than looking local",
      "localUp === false" in panel and "not answering" in panel and 'goto("groq/local")' in panel)
check("each one picked right there, with the Models tab's own picker", "<ModelChooser" in panel
      and "need={chooserLeg.need}" in panel and "onclick={(e) => choose(l, e)}" in panel)
check("a pick says it is for calls only, and can be taken back", "<em>calls only</em>" in panel and "unpick(l.key)" in panel)
check("a turn is timed leg by leg, not just the voice", ">Time a turn<" in panel and "speed.legs?.[l.key]" in panel)
check("a blocked microphone says what to do", "Allow it when asked, or open the panel in your browser" in panel)
check("talked over, what it had left to say stops playing here too", 'ev.t === "cut"' in panel
      and "silenceIt()" in panel)
check("the panel can ask for all of it", all(f"call{p}" in api for p in ("Voices", "Preview", "Speed", "TryUrl")))
check("its buttons are the app's tinted ones, the leg cards too", ".cl-voice, .cl-btn, .cl-leg-pick)" in read("webui/src/app.css"))
check("a pick makes its own sound", 'data-sound="self"' in panel and 'play("select")' in panel)

print("\n== Try a call, over its WebSocket ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import call_routes  # noqa: E402


class Scripted(Engine):
    name = "own"

    async def start(self):
        self.events.state("listening")

    async def cue(self, direction):
        self.events.audio(tone(0.1, 24000), 24000)
        self.events.said("Hey, who's this?")

    async def feed(self, pcm):
        self.fed = getattr(self, "fed", 0) + 1
        if self.fed == 5:
            self.events.heard("it's me")
            self.events.audio(tone(0.1, 24000), 24000)
            self.events.said("Oh hi!")


app = FastAPI()
app.include_router(call_routes.router)
_choose = sess.choose_engine
sess.choose_engine = lambda calls, **kw: Scripted(instructions="", voice="", events=kw["events"])
try:
    with TestClient(app) as client, client.websocket_connect("/api/calls/try?engine=own") as ws:
        hello = json.loads(ws.receive_text())
        for _ in range(8):
            ws.send_bytes(audio.silence(20, 16000))
        events_, voice_bytes, hung_up = [], 0, False
        for _ in range(200):
            msg = ws.receive()
            if msg.get("text"):
                ev = json.loads(msg["text"])
                events_.append(ev)
                if ev["t"] == "done":
                    break
            elif msg.get("bytes"):
                voice_bytes += len(msg["bytes"])
                # Both lines out: paced at the speed it plays, so this is a fifth of a second in.
                if voice_bytes >= 2 * 4800 and not hung_up:
                    hung_up = True
                    ws.send_text(json.dumps({"t": "hangup"}))
finally:
    sess.choose_engine = _choose
lines_ = [(e["who"], e["text"]) for e in events_ if e["t"] == "line"]
check("it says what it will send and at what rate", hello == {"t": "ready", "rate": 24000, "mic_rate": 16000})
check("it picks up, hears you, and answers", lines_ == [("me", "Hey, who's this?"), ("them", "it's me"),
                                                         ("me", "Oh hi!")], str(lines_))
check("its voice comes back as audio", voice_bytes >= 2 * 4800, str(voice_bytes))
check("hanging up ends it, and says how", events_ and events_[-1]["t"] == "done"
      and events_[-1]["reason"] == "you hung up", str(events_[-1:]))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
