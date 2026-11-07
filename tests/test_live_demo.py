"""The practice LIVE: Settings, TikTok, LIVE has a pretend TikTok LIVE to try the co-host in, without going live.

A made-up crowd joins, chats, taps hearts, follows and sends gifts (webui/src/lib/livecrowd.ts, played back under Node
in livecrowd_logic.mjs); you can be a viewer too. The persona answers exactly as on a real LIVE: one place
(app/utils/livecohost.py) says what is answered and writes the line, for the TikTok bridge and the practice LIVE
alike, with the LIVE settings on the page, saved or not; at the pace they set (one at a time, so many a minute, a
viewer not again too soon or too often, a moment before each); in the chat, out loud with its voice and over the
camera as the OBS page shows it. It speaks as the persona being edited, else the TikTok account's, else Default's,
and works before any account is set up. Nothing goes to TikTok, nobody is remembered, nothing is counted.

Run for real (in a throwaway data folder, the model and the voice stood in for): the shared rules and line, the real
LIVE's answers in the bridge, and the practice LIVE's routes. The page is read from the source.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="llmbot_livedemo_"))
(DATA / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
for k in list(os.environ):
    if k.startswith(("TIKTOK_USERNAME_", "SNAP_USERNAME", "DISCORD_TOKEN")):
        del os.environ[k]

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== what a LIVE answers, and how ==")
from app.utils import livecohost as lc  # noqa: E402

s = lc.settings({"chat": False, "per_minute": "6", "greet_joins": 1, "bogus": True})
check("its settings, each there and of its kind", s["chat"] is False and s["per_minute"] == 6 and s["greet_joins"] is True
      and s["voice"] is True and "bogus" not in s, str(s))
check("and as config.yaml ships them when nothing is given", lc.settings(None) == lc.DEFAULTS)
check("a pace from 1 to 30 a minute", lc.settings({"per_minute": 0})["per_minute"] == 1
      and lc.settings({"per_minute": 999})["per_minute"] == 30)
odd = lc.settings({"reply_delay": 99, "max_words": 1, "viewer_cooldown": -5, "silence_seconds": 1, "overlay_seconds": 0,
                   "tone": "angry", "answer_mode": "everything", "overlay_theme": "neon", "language": "persona",
                   "topic": "  cooking\n pasta  ", "gift_min_coins": "abc"})
check("every number kept in its range, every choice one of its own", odd["reply_delay"] == 30 and odd["max_words"] == 4
      and odd["viewer_cooldown"] == 0 and odd["silence_seconds"] == 15 and odd["overlay_seconds"] == 3
      and odd["tone"] == "persona" and odd["answer_mode"] == "all" and odd["overlay_theme"] == "dark"
      and odd["language"] == "persona" and odd["topic"] == "cooking pasta" and odd["gift_min_coins"] == 1, str(odd))
check("its word lists as lists, from a list or from commas", lc.settings({"blocked_words": "spam, promo"})["blocked_words"]
      == ["spam", "promo"] and lc.settings({"ignore_viewers": ["@a", " ", "b"]})["ignore_viewers"] == ["@a", "b"]
      and lc.settings(None)["blocked_words"] is not lc.DEFAULTS["blocked_words"])
on = lc.settings({})
check("a comment is answered", lc.skip_reason("comment", "where are you from?", on) == "")
check("an empty one is not", lc.skip_reason("comment", "  ", on) == "Nothing to answer")
check("hearts are thanked only when that is on", lc.skip_reason("like", "", on) == "Thanking hearts is off"
      and lc.skip_reason("like", "", {**on, "thank_likes": True}) == "")
check("gifts and follows by their switches", lc.skip_reason("gift", "Rose", {**on, "thank_gifts": False}) == "Thanking gifts is off"
      and lc.skip_reason("follow", "", {**on, "welcome_follows": False}) == "Welcoming followers is off"
      and lc.skip_reason("gift", "Rose", on) == "" and lc.skip_reason("follow", "", on) == "")
check("joins only when greeting them is on", lc.skip_reason("join", "", on) == "Greeting people who join is off"
      and lc.skip_reason("join", "", {**on, "greet_joins": True}) == "")
check("shares by their switch", lc.skip_reason("share", "", on) == ""
      and lc.skip_reason("share", "", {**on, "thank_shares": False}) == "Thanking shares is off")
check("comments not at all when that is off", lc.skip_reason("comment", "hi", {**on, "answer_comments": False})
      == "Answering comments is off")
check("emoji alone let go, unless that is off", lc.skip_reason("comment", "🔥🔥🔥", on) == "Only emoji"
      and lc.skip_reason("comment", "🔥🔥🔥", {**on, "skip_emoji_only": False}) == "")
check("only questions, or lines naming it, when asked to",
      lc.skip_reason("comment", "nice stream", {**on, "answer_mode": "questions"}) == "Not a question"
      and lc.skip_reason("comment", "where are you from", {**on, "answer_mode": "questions"}) == ""
      and lc.skip_reason("comment", "lena you rock", {**on, "answer_mode": "questions"}, names=["Lena"]) == "")
check("only when named, by name or @handle", lc.skip_reason("comment", "hi all", {**on, "answer_mode": "named"},
                                                            names=["Lena B", "lena.b"]) == "It was not named"
      and lc.skip_reason("comment", "hi Lena!", {**on, "answer_mode": "named"}, names=["Lena B"]) == ""
      and lc.skip_reason("comment", "@lena.b hi", {**on, "answer_mode": "named"}, names=["lena.b"]) == "")
check("words on the list, never", lc.skip_reason("comment", "Buy my Promo now", {**on, "blocked_words": "spam, promo"})
      == "It has a word on the list")
check("viewers on the list, never, by name or @handle",
      lc.skip_reason("comment", "hi", {**on, "ignore_viewers": "@troll_1, Bob"}, name="bob") == "They are on the never-answer list"
      and lc.skip_reason("gift", "Rose", {**on, "ignore_viewers": "troll_1"}, name="T", handle="Troll_1")
      == "They are on the never-answer list")
check("a gift by what it is worth", lc.gift_value("Rose x5") == 5 and lc.gift_value("Galaxy") == 1000
      and lc.gift_value("sent Corgi") == 299 and lc.gift_value("Mystery thing") == 1
      and lc.gift_value("sent a Rose ×3") == 3 and lc.gift_value("a envoyé une Galaxy") == 1000
      and lc.skip_reason("gift", "Rose x5", {**on, "gift_min_coins": 10}) == "A smaller gift than it thanks"
      and lc.skip_reason("gift", "Hand Hearts", {**on, "gift_min_coins": 10}) == "")
check("a line of its own when the chat is quiet, only when that is on",
      lc.skip_reason("quiet", "", on) == "Talking when it is quiet is off"
      and lc.skip_reason("quiet", "", {**on, "fill_silence": True}) == "")
ctx = lc.context("gift", "sunny", "Rose x5")
check("the model is told: live, out loud, what happened, one short line naming them",
      "LIVE" in ctx and "out loud" in ctx and "sunny just sent a gift (Rose x5)" in ctx
      and ctx.endswith("One short spoken line, under 15 words, naming them. No emoji-only answers."), ctx)
styled = lc.context("comment", "mara", "hi", {**on, "tone": "hype", "topic": "cooking pasta", "max_words": 8,
                                               "use_names": False, "emoji": False})
check("and how to come across, as the settings say", "This LIVE is about: cooking pasta." in styled
      and lc.TONES["hype"] in styled and "under 8 words" in styled and "Do not say their name." in styled
      and "No emoji at all." in styled, styled)
check("to everyone, when the chat is quiet", "The chat has gone quiet" in lc.context("quiet", "", "", {**on, "fill_silence": True})
      and "naming them" not in lc.context("quiet", "", ""))
check("the comment read out first, only when that is on", lc.reading("comment", "mara", "hi there", on) == ""
      and lc.reading("comment", "mara", "hi there", {**on, "read_comment": True}) == "mara says: hi there"
      and lc.reading("gift", "mara", "Rose", {**on, "read_comment": True}) == "")
check("how the OBS page shows it", lc.overlay(on) == {"seconds": 8, "position": "bottom", "comment": True,
                                                      "size": "medium", "theme": "dark"})
check("a viewer is the same person to the engine each time", lc.viewer_id("Mara K!") == lc.viewer_id("mara k")
      and lc.viewer_id("x", "Theo.Wav") == "tt_theo-wav" and lc.viewer_id("mara", prefix="livedemo_") == "livedemo_mara")
# Without humanize's random typo: one landing in "mara" failed the check now and then (the ARM build, 2026-11-06), and
# typos have checks of their own (tests/test_logic.py).
import app.utils.humanize as _hz  # noqa: E402
_typo, _hz.add_typo = _hz.add_typo, lambda text, chance=0.03: text
try:
    check("its line: the first line only, short", lc.clean("hi mara!!\nsecond line").startswith("hi mara")
          and "second" not in lc.clean("hi mara!!\nsecond line") and len(lc.clean("x" * 400)) <= 150 and lc.clean(None) == "")
    check("and cut at the words when far past its length", len(lc.clean(" ".join(["word"] * 40), 8).split()) <= 14)
finally:
    _hz.add_typo = _typo
check("with a typo too, the second line never joins it", all("second" not in lc.clean("hi mara!!\nsecond line")
                                                           for _ in range(300)))

print("\n== its pace ==")
pace = lc.Pace()
t0 = 1_000_000.0
quick = {**on, "per_minute": 3, "viewer_cooldown": 30, "max_per_viewer": 2}
check("free at first", pace.why_not(quick, "a", t0) == "")
pace.busy = True
check("one at a time", pace.why_not(quick, "a", t0) == "Still answering someone")
pace.busy = False
pace.note("a", t0)
check("the same viewer not again too soon", pace.why_not(quick, "a", t0 + 5) == "Answered them a moment ago"
      and pace.why_not(quick, "b", t0 + 5) == "")
check("and again once the wait is over", pace.why_not(quick, "a", t0 + 31) == "")
pace.note("a", t0 + 31)
pace.note("b", t0 + 40)
check("at most so many a minute", pace.why_not(quick, "c", t0 + 45) == "Already 3 this minute")
check("nor the same viewer too often in one LIVE", pace.why_not(quick, "a", t0 + 100) == "Answered them enough this LIVE"
      and pace.why_not(quick, "c", t0 + 101) == "")
check("a line to everyone is nobody's turn", pace.why_not({**quick, "per_minute": 30}, "", t0 + 50) == "")

print("\n== said now, or not at all ==")
from app.utils import ai  # noqa: E402
from app.core import engine as _engine  # noqa: E402


class _FakeClient:
    max_retries = 2

    def with_options(self, **kw):
        f = _FakeClient()
        f.max_retries = kw.get("max_retries")
        return f


_saved_clients = list(ai._groq_clients)
ai._groq_clients[:] = [{"client": _FakeClient(), "label": "test"}]
ai._client_index = 0
_seen = {}


async def _fake_generate(msg):
    _seen["retries"] = ai._active_client().max_retries
    _seen["extra"] = dict(msg.extra)
    return "hey mara!\nand a second line"


_real_generate = _engine.generate_ai_response
_engine.generate_ai_response = _fake_generate
try:
    out = asyncio.run(lc.line("comment", "mara", "hi", uid="live_mara"))
    asyncio.run(lc.line("comment", "mara", "hola", uid="live_mara", live={**on, "language": "persona", "tone": "chill"}))
finally:
    _engine.generate_ai_response = _real_generate
check("a LIVE's line never waits out a rate limit: the next model answers instead", _seen.get("retries") == 0, str(_seen))
check("a DM still does, as before", ai._active_client().max_retries == 2)
check("and its line is short, public, remembered by nobody", out == "hey mara!" and _seen["extra"].get("no_memory")
      and _seen["extra"].get("no_stats") and _seen["extra"].get("no_pictures"), str(out))
check("in the persona's own language when that is picked, with the mood asked for",
      _seen["extra"].get("language") == "en" and lc.TONES["chill"] in _seen["extra"].get("context", ""), str(_seen["extra"]))
eng = read("app/core/engine.py")
check("the engine keeps to a language it is given, without guessing", '_set_lang = str((msg.extra or {}).get("language") or "")'
      in eng and "if not _set_lang and _alpha >= 8" in eng and "lang_tag = _set_lang or lang_entry[\"tag\"]" in eng)
ai._groq_clients[:] = _saved_clients

print("\n== a real LIVE, in the bridge ==")
os.environ["BRIDGE_PLATFORM"] = "tiktok"
import app.platforms.snapchat_bridge as bridge  # noqa: E402

emitted, written, calls = [], {}, []
cfg_now = {}
bridge._emit_chat = lambda evt: emitted.append(evt)
bridge._read_json = lambda path, default=None: dict(written)
bridge._write_json = lambda path, data: (written.clear(), written.update(data))
bridge._poke_node = lambda kind: None
bridge._live_cfg = lambda: dict(cfg_now)


async def bridge_line(kind, name, text, *, uid, platform="tiktok", account=None, channel="live", live=None):
    calls.append({"kind": kind, "name": name, "uid": uid, "live": live})
    return f"hey {name}!" if kind != "quiet" else "what are you all up to?"


async def bridge_voice(text, read_first=""):
    calls.append({"voice": text, "read_first": read_first})
    return []


real_line, real_voice = lc.line, lc.voice
lc.line, lc.voice = bridge_line, bridge_voice
try:
    cfg_now.update(enabled=True, reply_delay=0, read_comment=True, blocked_words="promo")
    bridge._live_state(True)
    asyncio.run(bridge._live_event({"event": "comment", "name": "mara", "handle": "mara_k", "text": "where are you from?"}))
    say = [e for e in emitted if e.get("t") == "live_say"]
    check("a comment on its LIVE is answered, in the chat and out loud", len(say) == 1 and say[0]["text"] == "hey mara!"
          and say[0]["to"] == "mara" and list(written.values())[0]["kind"] == "live", str(emitted[-2:]))
    check("the OBS page told the comment it answers", say and say[0].get("comment") == "where are you from?"
          and say[0].get("event") == "comment")
    check("the comment read out before the answer, when that is on",
          any(c.get("read_first") == "mara says: where are you from?" for c in calls), str(calls))
    check("with the LIVE settings as they are", calls[0]["live"]["read_comment"] is True and calls[0]["uid"] == "tt_mara_k")
    asyncio.run(bridge._live_event({"event": "comment", "name": "mara", "handle": "mara_k", "text": "and your name?"}))
    check("the same viewer not again straight away", len([e for e in emitted if e.get("t") == "live_say"]) == 1)
    asyncio.run(bridge._live_event({"event": "comment", "name": "zed", "handle": "zed", "text": "PROMO here"}))
    check("a word on the list, never", len([e for e in emitted if e.get("t") == "live_say"]) == 1)
    check("every line still shown in the panel", [e["text"] for e in emitted if e.get("t") == "live"][-2:]
          == ["and your name?", "PROMO here"])
    asyncio.run(bridge._live_answer("quiet", "", ""))
    check("nothing of its own when the chat is quiet, unless that is on",
          len([e for e in emitted if e.get("t") == "live_say"]) == 1)
    cfg_now.update(fill_silence=True)
    asyncio.run(bridge._live_answer("quiet", "", ""))
    last = [e for e in emitted if e.get("t") == "live_say"][-1]
    check("and to everyone when it is", last["text"] == "what are you all up to?" and last["to"] == "", str(last))
    cfg_now.update(reply_delay=1)
    started = time.time()
    asyncio.run(bridge._live_event({"event": "comment", "name": "ines", "handle": "ines", "text": "hi!"}))
    check("never sooner than the wait before answering", time.time() - started >= 0.9)
    cfg_now.update(enabled=False)
    before = len(emitted)
    asyncio.run(bridge._live_event({"event": "comment", "name": "noah", "handle": "noah", "text": "hello?"}))
    check("and nothing at all while co-hosting is off", [e["t"] for e in emitted[before:]] == ["live"])
finally:
    lc.line, lc.voice = real_line, real_voice
bridge_src = read("app/platforms/snapchat_bridge.py")
check("a real LIVE answers through the same place as the practice one",
      "livecohost.skip_reason(kind, text, cfg, name, handle" in bridge_src and "await livecohost.line(kind, name, text"
      in bridge_src and "await livecohost.voice(response, livecohost.reading(" in bridge_src and "_LIVE_SAID" not in bridge_src)
check("and watches for the chat going quiet while it is live", "tasks.append(_live_quiet_loop())" in bridge_src)

print("\n== the practice LIVE ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import livedemo_routes as ld  # noqa: E402

app = FastAPI()
app.include_router(ld.router)
client = TestClient(app)
# No model set up at all (a fresh install): the panel says so and stays up. A runner exits there on purpose.
os.environ.pop("GROQ_API_KEY", None)
bare = client.get("/api/live-demo").json()
check("with no model set up it says so, plainly, and the panel stays up", "No model is set up" in (bare.get("not_ready") or "")
      and bare.get("voice") is False, str(bare))
nothing = client.post("/api/live-demo/answer", json={"event": "comment", "name": "mara", "text": "hi", "persona": "",
                                                      "live": lc.DEFAULTS}).json()
check("and each line says why it was not answered", nothing.get("answered") is False and "No model" in nothing.get("why", ""),
      str(nothing))
os.environ["GROQ_API_KEY"] = "gsk_test_never_called"
info = client.get("/api/live-demo").json()
check("with one, it is ready", info.get("not_ready") == "", str(info.get("not_ready")))
check("with no TikTok account, it speaks as Default, its host the persona itself",
      info["persona"]["id"] == "default" and info["host"]["handle"] == "" and info["account"] == "", str(info))
check("with the saved LIVE settings, every one of them", info["live"] == lc.settings(lc.DEFAULTS) and len(info["live"]) >= 30)
check("and says whether it can speak", isinstance(info["voice"], bool))

said = []
voiced = []


async def fake_line(kind, name, text, *, uid, platform="tiktok", account=None, channel="live", live=None):
    from app.utils import personas
    said.append({"kind": kind, "name": name, "uid": uid, "channel": channel, "persona": personas.current(), "live": live})
    await asyncio.sleep(0)
    return f"hey {name}!"


async def fake_voice(text, read_first=""):
    voiced.append(read_first)
    return [b"RIFF" + b"\0" * 64]


lc.line, lc.voice = fake_line, fake_voice
try:
    client.post("/api/live-demo/start")
    fast = {**lc.DEFAULTS, "viewer_cooldown": 0, "reply_delay": 0}
    body = {"event": "comment", "name": "mara", "text": "where are you from?", "persona": "", "live": fast}
    r = client.post("/api/live-demo/answer", json=body).json()
    check("a comment gets the persona's line", r.get("answered") is True and r.get("text") == "hey mara!", str(r))
    check("written as the persona, kept apart from anyone real", said and said[-1]["persona"] == "default"
          and said[-1]["uid"].startswith("livedemo_") and said[-1]["channel"] == "livedemo", str(said[-1:]))
    check("with the settings on the page", said[-1]["live"] == lc.settings(fast))
    off = client.post("/api/live-demo/answer", json={**body, "event": "gift", "text": "Rose",
                                                     "live": {**fast, "thank_gifts": False}}).json()
    check("the settings on the page decide, saved or not", off == {"answered": False, "why": "Thanking gifts is off"}, str(off))
    ld._pace().busy = True
    busy = client.post("/api/live-demo/answer", json=body).json()
    ld._pace().busy = False
    check("one at a time", busy == {"answered": False, "why": "Still answering someone"}, str(busy))
    for _ in range(3):
        client.post("/api/live-demo/answer", json=body)
    full = client.post("/api/live-demo/answer", json=body).json()
    check("at most so many a minute", full == {"answered": False, "why": "Already 4 this minute"}, str(full))
    client.post("/api/live-demo/start")
    again = client.post("/api/live-demo/answer", json=body).json()
    check("going live again starts the minute again", again.get("answered") is True, str(again))
    v = client.post("/api/live-demo/voice", json={"id": again["id"]}).json()
    check("its line said out loud, kept as a file to play", len(v.get("audio", [])) == 1
          and v["audio"][0] == f"demo_{again['id']}_0.wav", str(v))
    a = client.get(f"/api/live-demo/audio/{v['audio'][0]}")
    check("and played from here", a.status_code == 200 and a.headers.get("content-type") == "audio/wav")
    check("only its own files, by name", client.get("/api/live-demo/audio/..%2Fconfig.yaml").status_code == 404
          and client.get("/api/live-demo/audio/1_" + "a" * 32 + "_0.wav").status_code == 404)
    check("only a line it wrote is said", client.post("/api/live-demo/voice", json={"id": "f" * 32}).status_code == 404)

    client.post("/api/live-demo/start")
    slow = {**body, "live": {**lc.DEFAULTS, "reply_delay": 0}}
    first = client.post("/api/live-demo/answer", json=slow).json()
    second = client.post("/api/live-demo/answer", json=slow).json()
    other = client.post("/api/live-demo/answer", json={**slow, "name": "theo"}).json()
    check("the same viewer waits out the wait, someone else does not", first.get("answered") is True
          and second == {"answered": False, "why": "Answered them a moment ago"} and other.get("answered") is True, str(second))
    client.post("/api/live-demo/start")
    once = {**body, "live": {**fast, "max_per_viewer": 1}}
    client.post("/api/live-demo/answer", json=once)
    enough = client.post("/api/live-demo/answer", json=once).json()
    check("and is answered so many times a LIVE at most", enough == {"answered": False, "why": "Answered them enough this LIVE"},
          str(enough))
    client.post("/api/live-demo/start")
    named = {**body, "live": {**fast, "answer_mode": "named"}}
    not_named = client.post("/api/live-demo/answer", json={**named, "text": "hi everyone"}).json()
    by_name = client.post("/api/live-demo/answer", json={**named, "text": f"{info['host']['name']} hiii"}).json()
    check("only when named: its name, as the practice LIVE's host has it", not_named == {"answered": False, "why": "It was not named"}
          and by_name.get("answered") is True, f"{not_named} {by_name}")
    quiet = client.post("/api/live-demo/answer", json={"event": "quiet", "name": "", "text": "", "persona": "",
                                                       "live": {**fast, "fill_silence": True}}).json()
    check("a line of its own when the chat goes quiet, to everyone", quiet.get("answered") is True
          and said[-1]["kind"] == "quiet" and said[-1]["uid"] == "livedemo_everyone", str(said[-1]))
    client.post("/api/live-demo/start")
    read_out = client.post("/api/live-demo/answer", json={**body, "live": {**fast, "read_comment": True}}).json()
    client.post("/api/live-demo/voice", json={"id": read_out["id"]})
    check("the comment read out first, when that is on", voiced[-1] == "mara says: where are you from?", str(voiced[-1:]))
    client.post("/api/live-demo/start")
    started = time.time()
    waited = client.post("/api/live-demo/answer", json={**body, "live": {**fast, "reply_delay": 1}}).json()
    check("never sooner than the wait before answering", waited.get("answered") is True and time.time() - started >= 0.9)

    from app.core import engine
    engine.message_history["livedemo_mara-livedemo"] = [{"role": "user", "content": "hi"}]
    engine.message_history["123-456"] = [{"role": "user", "content": "keep"}]
    client.post("/api/live-demo/start")
    check("a new practice LIVE forgets the last one's viewers, and nobody else",
          "livedemo_mara-livedemo" not in engine.message_history and "123-456" in engine.message_history)
finally:
    lc.line, lc.voice = real_line, real_voice

routes = read("app/web/routes/livedemo_routes.py")
check("its own address, not a TikTok account's", '"/api/live-demo"' in routes and "app.include_router(livedemo_routes.router)"
      in read("app/web/server.py"))
check("nobody remembered, nothing counted, nothing sent", '"no_memory": True' in read("app/utils/livecohost.py")
      and '"no_stats": True' in read("app/utils/livecohost.py") and "RESPONSES_FILE" not in routes and "ipc.send" not in routes)
check("who it is, read off the shared loop", "await asyncio.to_thread(_who," in routes)

print("\n== its screen, a file of your own ==")
import io  # noqa: E402
from PIL import Image  # noqa: E402
from app.utils import personas, videos  # noqa: E402

H = {"x-llmselfbot": "1"}
SCREEN = "/api/live-demo/screen?persona=default"
shot = io.BytesIO()
Image.new("RGB", (300, 500), (40, 90, 200)).save(shot, "PNG")
png = {"file": ("shot.png", shot.getvalue(), "image/png")}
check("none of its own at first", client.get(SCREEN).json() == {"present": False})
check("only from the panel itself", client.post(SCREEN, files=png).status_code == 403
      and client.post(SCREEN, files=png, headers={**H, "origin": "https://evil.example"}).status_code == 403)
sent_before = sorted(p.name for p in personas.pictures_dir("default").glob("*")) \
    if personas.pictures_dir("default").is_dir() else []
pic = client.post(SCREEN, files=png, headers=H).json()
check("a picture of yours becomes its screen", pic.get("present") is True and pic.get("kind") == "image"
      and pic.get("version", 0) > 0, str(pic))
kept = sorted(p.name for p in personas.folder("default").glob("live_screen*"))
now_sent = sorted(p.name for p in personas.pictures_dir("default").glob("*")) \
    if personas.pictures_dir("default").is_dir() else []
check("kept in the persona's own folder, never with the pictures it sends", len(kept) == 1
      and kept[0].startswith("live_screen.") and now_sent == sent_before, f"{kept} {now_sent}")
got = client.get(f"/api/live-demo/screen/file?persona=default&v={pic['version']}")
check("and shown, kept for good", got.status_code == 200 and got.headers["content-type"].startswith("image/")
      and "immutable" in got.headers.get("cache-control", ""))
check("only a profile that's there", client.get("/api/live-demo/screen?persona=nobody").status_code == 404
      and client.get("/api/live-demo/screen?persona=..%2F..%2Fconfig").status_code == 404
      and client.get("/api/live-demo/screen/file?persona=nobody&v=1").status_code == 404)
bad = client.post(SCREEN, files={"file": ("notes.txt", b"hello there, not a picture", "text/plain")}, headers=H)
check("what isn't a picture or a video is said so, and the one it had stays", bad.status_code == 400
      and "isn't a picture" in bad.json().get("detail", "") and client.get(SCREEN).json().get("present") is True)
if videos.available():
    ffmpeg, _ = videos.tools()
    clip = DATA / "clip.mov"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=1",
                    "-pix_fmt", "yuv420p", "-c:v", "mpeg4", str(clip)], check=True)
    vid = client.post(SCREEN, files={"file": ("clip.mov", clip.read_bytes(), "video/quicktime")}, headers=H).json()
    folder = personas.folder("default")
    check("a video becomes an MP4 every browser plays, with a still for its tile, in place of the picture",
          vid.get("kind") == "video" and vid.get("still") is True and (folder / "live_screen.mp4").is_file()
          and not list(folder.glob("live_screen.png")) and not list(folder.glob(".live_screen-*")), str(vid))
    still = client.get(f"/api/live-demo/screen/file?persona=default&v={vid['version']}&still=true")
    plays = client.get(f"/api/live-demo/screen/file?persona=default&v={vid['version']}")
    check("its still and the video, each as what it is", still.headers.get("content-type") == "image/jpeg"
          and plays.headers.get("content-type") == "video/mp4", f"{still.headers} {plays.headers}")
else:
    print("  SKIP  a video of yours (needs ffmpeg)")
check("not removed by another website", client.delete(SCREEN).status_code == 403
      and client.get(SCREEN).json().get("present") is True)
check("removed, all of it", client.delete(SCREEN, headers=H).json() == {"present": False}
      and not list(personas.folder("default").glob("live_screen*")))
check("the upload, the conversion and the files off the shared loop",
      "await asyncio.to_thread(videos.spool, file.file" in routes
      and "await asyncio.to_thread(_save_screen, persona, tmp, original, head)" in routes
      and "def screen_info(persona" in routes and "def screen_remove(request" in routes)

print("\n== the settings ==")
import yaml  # noqa: E402

shipped = (yaml.safe_load(read("resources/config.yaml")).get("tiktok") or {}).get("live") or {}
check("config.yaml ships every LIVE setting, as livecohost reads them", shipped == lc.DEFAULTS,
      str(set(shipped) ^ set(lc.DEFAULTS)))
from app.web.schema import CONFIG_SCHEMA  # noqa: E402
from app.web import descriptions  # noqa: E402

schema_keys = {f["key"]: f for f in CONFIG_SCHEMA if f["key"].startswith("tiktok.live.")}
check("each one in Settings, with a label and one line", set(schema_keys) == {f"tiktok.live.{k}" for k in lc.DEFAULTS}
      and all(k in descriptions.DESCRIPTIONS and k in descriptions.LABELS for k in schema_keys),
      str({f"tiktok.live.{k}" for k in lc.DEFAULTS} ^ set(schema_keys)))
check("their ranges as livecohost keeps them", all(
    (schema_keys[f"tiktok.live.{k}"].get("min"), schema_keys[f"tiktok.live.{k}"].get("max")) == lo_hi
    for k, lo_hi in lc.RANGES.items() if k != "per_minute"))
smap = read("webui/src/lib/settingsmap.ts")
check("on four LIVE subtabs: the LIVE, what it answers, how it sounds, the OBS page", all(
    f'id: "{s}"' in smap for s in ("live", "live-answers", "live-style", "live-overlay")))
settings_src = read("webui/src/pages/Settings.svelte")
check("every choice a list of plain words", all(f'"tiktok.live.{k}": [' in settings_src for k in lc.CHOICES))
check("seconds on a dial, with what 0 means", '"tiktok.live.reply_delay": "At once"' in settings_src
      and '"tiktok.live.viewer_cooldown": "Any time"' in settings_src
      and all("in seconds" in descriptions.DESCRIPTIONS[f"tiktok.live.{k}"]
              for k in ("reply_delay", "viewer_cooldown", "silence_seconds", "overlay_seconds")))

print("\n== the page ==")
demo = read("webui/src/lib/components/LiveDemo.svelte")
check("under every LIVE subtab, with the settings as they are on the page, and kept going from one to the next",
      '{#if tab.id === "tiktok" && LIVE_SUBS.has(sub.id)}' in settings_src
      and 'const LIVE_SUBS = new Set(["live", "live-answers", "live-style", "live-overlay"]);' in settings_src
      and "<LiveDemo get={(k) => (byKey[k] ? value(byKey[k]) : undefined)} persona={scope} />" in settings_src
      and settings_src.index("<LiveDemo get=") > settings_src.index("{/key}"))
check("every LIVE setting off the page, each of its kind", "for (const [key, was] of Object.entries(base))" in demo
      and "get(`tiktok.live.${key}`)" in demo and "live: $state.snapshot(live)" in demo)
check("a LIVE as TikTok draws one: camera, who is watching, chat, hearts, gifts, captions",
      all(c in demo for c in ('class="ld-cam"', 'class="ld-viewers"', 'class="ld-chat"', 'class="ld-hearts"',
                              'class="ld-banner"', 'class="ld-caption"')))
check("and TikTok's own pieces: the host's follow, the top gifters, the ranking pill, levels, who joined, the comment box",
      all(c in demo for c in ('class="ld-follow"', 'class="ld-top-av is-{i + 1}"', 'class="ld-pill"', 'class="ld-lv"',
                              'class="ld-enter"', 'placeholder="Add comment..."', 'class="ld-line is-system"',
                              'class="ld-banner-x"')))
check("tapping the screen sends hearts", 'class="ld-tap" onclick={tapHeart}' in demo)
check("picked for you, the camera is its first video, else one of its pictures, else its face",
      "pics.find((p) => p.video)" in demo and "settled = stills.length ? pick(stills) : null;" in demo
      and "settled ? shown(settled) : face" in demo)
stores_src = read("webui/src/lib/stores.ts")
check("its screen is blurred unless you say otherwise, as the Pictures tab is", 'blur: "medium"' in stores_src
      and 'persisted<LiveScreen>("liveScreen", LIVE_SCREEN, true)' in stores_src and "--blur: {BLUR[look.blur]" in demo
      and "filter: blur(var(--blur, 0px))" in demo and '"liveScreen",' in read("app/web/routes/prefs_routes.py"))
check("what it shows is yours to pick: picked for you, its own pictures and videos, a file of yours, its face, nothing",
      all(k in demo for k in ('choose({ kind: "auto" })', 'choose({ kind: "own" })', 'choose({ kind: "face" })',
                              'choose({ kind: "none" })', 'choose({ kind: "pick", id: p.id, name: p.name })')))
check("saved for each persona; one picked that's gone since is picked for you again",
      "[pid]: s" in demo and 'return { cam: v ? shown(v) : settled ? shown(settled) : face, tile: "auto" };' in demo)
check("a file of yours by picking it, or by dropping it on the screen", "api.uploadLiveScreen(file, pid)" in demo
      and "ondrop={dropFile}" in demo and 'play("drop")' in demo)
check("blur, fit and a slow zoom of your choosing, and a wide one shown whole on a blurred copy of itself",
      "BLUR_OPTIONS" in demo and "FIT_OPTIONS" in demo and "look.zoom" in demo and 'class="ld-fill"' in demo)
check("its tiles blurred with it, until you look closer", ".ld-shots.is-blurred .ld-shot img { filter: blur(3px); }" in demo
      and ".ld-shots.is-blurred .ld-shot:hover img" in demo)
check("a crowd at the pace picked, that talks to the host by name, and you as a viewer",
      "crowdEvent(Math.random, recent, here, hostCall)" in demo and "nextDelay(level)" in demo
      and 'asYou("follow")' in demo and "send()" in demo and "giveRose" in demo)
check("it answers in the chat and out loud, one line after another", "api.liveDemoAnswer(" in demo
      and "api.liveDemoVoice(id)" in demo and "playNext()" in demo)
check("your own lines wait their turn and are answered once the pace allows; the crowd's are let go",
      'mark(line.id, "Waiting its turn")' in demo and "function pump()" in demo
      and "if (!line.mine && waiting.length && !coolingDown())" in demo and "later(pump, 400);" in demo)
check("a wait for the same viewer holds up only them", "const coolingDown = () => live.viewer_cooldown > 0" in demo
      and "/Still answering|this minute|a moment ago/" in demo)
check("a line of its own when the chat is quiet", 'kind: "quiet"' in demo and "live.fill_silence" in demo
      and "live.silence_seconds * 1000" in demo)
check("its answer over the camera as the OBS page shows it", 'data-pos={live.overlay_position}' in demo
      and "data-size={live.overlay_size}" in demo and "data-look={live.overlay_theme}" in demo
      and "live.overlay_comment && caption.comment" in demo and "live.overlay_seconds * 1000" in demo)
check("what it goes by, and why it let something go", 'class="ld-chips"' in demo and "{#if l.why}" in demo
      and "answersChips" in demo and "styleChips" in demo)
check("sounds: going live and ending, a gift, a follow, joining, sharing, its answer",
      'play("rise"' in demo and 'play("off"' in demo and '"medal" : "glint"' in demo and 'play("pluck"' in demo
      and 'play("receive"' in demo and '"seat"' in demo and '"zip"' in demo)
check("each button with a sound of its own, sounded once", demo.count('data-sound="self"') >= 12)
check("it stops on its own: off the page, out of sight, after a while", "return () => stop(false);" in demo
      and "document.hidden" in demo and "LIMIT_MS" in demo)
check("follows the app's Animations switch", ':global(:root[data-motion="off"]) .ld-pan' in demo
      and "duration: $motionEnabled ? 420 : 0" in demo
      and ':global(:root[data-motion="off"]) .ld-enter' in demo and "if (!$motionEnabled) return;" in demo
      and "prefers-reduced-motion" not in demo)
check("says plainly that nothing goes to TikTok", "Nothing goes to TikTok." in demo)

print("\n== the OBS page ==")
over = read("webui/src/LiveOverlay.svelte")
check("shows the answers as the settings say: how long, where, how big, which look, the comment",
      "if (r?.overlay) look = { ...look, ...r.overlay };" in over and "look.seconds" in over
      and 'class="ov is-{look.position} is-{look.size}"' in over and 'class="ov-cap is-{look.theme}"' in over
      and "look.comment && shown.comment" in over)
check("and never gone before its voice is", "await Promise.all([playAll([...say.audio]), minimum]);" in over)
check("its settings handed over with the feed, as the account's persona has them",
      '"overlay": shown' in read("app/web/routes/chat_routes.py")
      and "personas.scope(personas.persona_of(web_id))" in read("app/web/routes/chat_routes.py"))
check("no em dashes in what was written for this", all(chr(0x2014) not in read(p) for p in (
    "webui/src/lib/components/LiveDemo.svelte", "webui/src/LiveOverlay.svelte", "app/utils/livecohost.py",
    "app/web/routes/livedemo_routes.py", "webui/src/lib/livecrowd.ts")))

print("\n== the crowd, under Node ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "livecrowd_logic.mjs")], cwd=ROOT / "webui", capture_output=True,
                          text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("livecrowd_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
