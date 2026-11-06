"""Every provider takes several API keys. When one runs out or is refused the next takes over, before anything hands over
to the next model. Nothing here reaches a real provider, and every key is made up."""
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name
for _name in list(os.environ):
    if re.fullmatch(r"[A-Z]+_API_KEY(_\d+)?", _name):
        os.environ.pop(_name)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.utils import ai, providers  # noqa: E402
from app.web import envfile  # noqa: E402
from app.web.routes import env_routes, models_routes  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


app = FastAPI()
app.include_router(env_routes.router)
app.include_router(models_routes.router)
client = TestClient(app)


def env():
    return envfile.read_env()


def put_key(pid, key):
    return client.post(f"/api/providers/{pid}/key", json={"key": key})


def clear():
    envfile.write_env({})
    envfile.reload_into_process({})
    providers._key_rest.clear()


keyed = [p for p in providers.PROVIDERS if p["env"]]

print("\n== every provider that takes a key takes several ==")
check("there are some to go round", len(keyed) >= 10, str(len(keyed)))
for p in keyed:
    clear()
    put_key(p["id"], f"{p['id']}-one")
    put_key(p["id"], f"{p['id']}-two")
    put_key(p["id"], f"{p['id']}-three")
    check(f"{p['name']} keeps all three, in order", providers.keys_for(p["id"]) == [f"{p['id']}-one", f"{p['id']}-two", f"{p['id']}-three"],
          str(providers.keys_for(p["id"])))
    listed = client.get(f"/api/env/keys/{p['id']}")
    check(f"and lists them to manage, hidden", listed.status_code == 200 and [k["index"] for k in listed.json()["keys"]] == [1, 2, 3]
          and all(f"{p['id']}-" not in k["preview"] or len(f"{p['id']}-one") <= 8 for k in listed.json()["keys"]), listed.text)
    check("the names are secret ones, masked everywhere", envfile.SECRET_KEYS.match(f"{p['env']}_2") is not None)

print("\n== how they are written ==")
clear()
put_key("openai", "first")
check("one key stays under the plain name", env().get("OPENAI_API_KEY") == "first" and not env().get("OPENAI_API_KEY_1"), str(env()))
put_key("openai", "second")
check("two move to the numbered names", env().get("OPENAI_API_KEY_1") == "first" and env().get("OPENAI_API_KEY_2") == "second", str(env()))
check("and neither is counted twice", providers.keys_for("openai") == ["first", "second"])
r = put_key("openai", "second")
check("the same one again changes nothing", r.json()["keys"] == 2 and providers.keys_for("openai") == ["first", "second"], r.text)
r = client.delete("/api/env/keys/openai/1")
check("removing one renumbers the rest", providers.keys_for("openai") == ["second"] and r.json()["keys"][0]["index"] == 1, r.text)
r = client.post("/api/env/keys/openai/1", json={"value": "third"})
check("replacing one", providers.keys_for("openai") == ["third"], r.text)
put_key("openai", "fourth")
r = put_key("openai", "")
check("no key at all disconnects it, every one", r.json()["keys"] == 0 and providers.keys_for("openai") == [], r.text)
check("left blank in the file, so an account already running lets go of them too",
      "OPENAI_API_KEY_1" in env() and not env()["OPENAI_API_KEY_1"], str(env()))

clear()
envfile.write_env({"GEMINI_API_KEY": "plain", "GEMINI_API_KEY_1": "one", "GEMINI_API_KEY_3": "past-a-gap", "MISTRAL_API_KEY": "your-key-here"})
envfile.reload_into_process()
listed = client.get("/api/env/keys/gemini").json()["keys"]
check("written by hand: everything it uses is listed", len(listed) == 3 and providers.keys_for("gemini") == ["plain", "one", "past-a-gap"], str(listed))
client.delete("/api/env/keys/gemini/2")
check("and survives a rewrite", providers.keys_for("gemini") == ["plain", "past-a-gap"], str(providers.keys_for("gemini")))
check("a leftover from the template is not a key", client.get("/api/env/keys/mistral").json()["keys"] == [])

clear()
envfile.write_env({"DISCORD_TOKEN": "old", "DISCORD_TOKEN_1": "new"})
check("an account's family keeps its own rule: a numbered one replaces the plain one",
      len(client.get("/api/env/keys/discord").json()["keys"]) == 1)
clear()

print("\n== which goes first ==")
envfile.write_env({"OPENAI_API_KEY_1": "a", "OPENAI_API_KEY_2": "b", "OPENAI_API_KEY_3": "c"})
check("in order", providers.key_order("openai") == ["a", "b", "c"] and providers.key_now("openai") == "a")
providers.rest_key("openai", "a", 60)
check("one resting goes last, not away", providers.key_order("openai") == ["b", "c", "a"] and providers.key_now("openai") == "b")
providers.rest_key("openai", "b", 60)
providers.rest_key("openai", "c", 60)
check("all resting, one is still offered", providers.key_now("openai") == "a")
providers.rest_key("openai", "a", -1)
check("and back when its rest is over", providers.key_now("openai") == "a")
providers._key_rest.clear()
check("rate limited, refused, out of credit: the key's doing",
      all(providers.key_at_fault(s) > 0 for s in (401, 402, 403, 429)))
check("anything else is not", all(providers.key_at_fault(s) == 0 for s in (0, 400, 404, 500, 503)))


class Err(Exception):
    def __init__(self, status, text="nope"):
        super().__init__(f"Error code: {status} - {text}")
        self.status_code = status


class Fake:
    """A client that answers as told, per key."""
    def __init__(self, key, script, log):
        self.key, self.script, self.log = key, script, log
        fake = self

        class Completions:
            async def create(self, **kw):
                fake.log.append(fake.key)
                out = fake.script.get(fake.key, "ok")
                if isinstance(out, Exception):
                    raise out
                return f"{fake.key}:{kw.get('model')}"

        class Chat:
            completions = Completions()

        self.chat = Chat()


def with_fakes(script):
    asked = []
    real = ai._openai_client
    ai._openai_client = lambda pid, config, key="": Fake(key or providers.key_now(pid), script, asked)
    return asked, lambda: setattr(ai, "_openai_client", real)


logged = []
real_log = ai.log_system
ai.log_system = lambda text: logged.append(text)
create = lambda c: c.chat.completions.create(model="m")

print("\n== going round them ==")
asked, done = with_fakes({"a": Err(429, "rate limit reached, try again in 45s")})
out = asyncio.run(ai._with_each_key("openai", {}, create))
check("rate limited, the next takes over in the same call", out == "b:m" and asked == ["a", "b"], str(asked))
check("and the one that ran out rests as long as it was told", 40 < providers._key_rest[("openai", "a")] - __import__("time").time() < 50)
asked.clear()
out = asyncio.run(ai._with_each_key("openai", {}, create))
check("so the next call does not start with it", out == "b:m" and asked == ["b"], str(asked))
done()
providers._key_rest.clear()

asked, done = with_fakes({"a": Err(401), "b": Err(402)})
out = asyncio.run(ai._with_each_key("openai", {}, create))
check("refused, or out of credit, the same", out == "c:m" and asked == ["a", "b", "c"], str(asked))
done()
providers._key_rest.clear()

asked, done = with_fakes({"a": Err(400, "bad request")})
try:
    asyncio.run(ai._with_each_key("openai", {}, create))
    check("something wrong with the request is not the key's fault", False)
except Err:
    check("something wrong with the request is not the key's fault", asked == ["a"], str(asked))
check("and that key does not rest for it", ("openai", "a") not in providers._key_rest)
done()

asked, done = with_fakes({"a": Err(429), "b": Err(429), "c": Err(429)})
try:
    asyncio.run(ai._with_each_key("openai", {}, create))
    check("all of them out: what the last one said comes out, for the next model to take over", False)
except Err as e:
    check("all of them out: what the last one said comes out, for the next model to take over",
          e.status_code == 429 and asked == ["a", "b", "c"], str(asked))
done()
providers._key_rest.clear()

said = " ".join(logged)
check("the log says which number, never the key", "key 1 of 3" in said and not re.search(r"\b[abc]\b:", said), said)

print("\n== with the rest of the app ==")
asked, done = with_fakes({"a": Err(429)})
real_cfg, real_chain = ai.load_config, providers.reply_chain
ai.load_config = lambda: {}
providers.reply_chain = lambda cfg: [{"provider": "openai", "model": "m1"}, {"provider": "gemini", "model": "m2"}]
ai._initialised = True
ai._groq_clients = []
ai._resting.clear()
out = asyncio.run(ai._create_completion_inner([{"role": "user", "content": "hi"}]))
check("a reply: the next key before the next model", out == "b:m1" and asked == ["a", "b"], str(asked))
check("and the model does not rest, only the key", ("openai", "m1") not in ai._resting, str(ai._resting))
done()
providers._key_rest.clear()
ai.load_config, providers.reply_chain = real_cfg, real_chain

src = (ROOT / "app/utils/ai.py").read_text(encoding="utf-8")
check("every way a provider is asked goes round its keys",
      src.count("_with_each_key(") >= 6 and "await client.chat.completions.create(model=entry" not in src)

real_chain2, real_cfg2 = providers.job_chain, ai.load_config
ai.load_config = lambda: {}
providers.job_chain = lambda cfg, job: [{"provider": "openai", "model": "tts-1", "voice": "alloy"}]
real_base = providers.base_url
providers.base_url = lambda pid, cfg: "http://x/v1"
targets = ai.tts_targets()
check("speaking: each key a speaker of its own, in order", [t["api_key"] for t in targets] == ["a", "b", "c"], str(targets))
providers.rest_key("openai", "a", 60)
check("a resting one last", [t["api_key"] for t in ai.tts_targets()] == ["b", "c", "a"])
ai.note_key_trouble("openai", "b", Err(401))
check("and whoever spoke with it can rest it", [t["api_key"] for t in ai.tts_targets()][0] == "c")
ai.note_key_trouble("openai", "c", Err(500))
check("not for something else", [t["api_key"] for t in ai.tts_targets()][0] == "c")
providers._key_rest.clear()
envfile.write_env({"ELEVENLABS_API_KEY_1": "el-a", "ELEVENLABS_API_KEY_2": "el-b"})
providers.job_chain = lambda cfg, job: [{"provider": "elevenlabs", "model": "eleven_flash_v2_5", "voice": "v"}]
check("ElevenLabs once: it goes round its own", [t["api_key"] for t in ai.tts_targets()] == ["el-a"])
providers.job_chain, ai.load_config = real_chain2, real_cfg2
providers.base_url = real_base

print("\n== ElevenLabs ==")
import httpx  # noqa: E402

from app.voice.speak import Speaker, SpeakError  # noqa: E402

sent = []
answers = {"el-a": 401, "el-b": 200}


class FakeResponse:
    def __init__(self, code):
        self.status_code, self.text, self.content = code, "said no", b"\0\0" * 100


class FakeHttp:
    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        sent.append(headers["xi-api-key"])
        return FakeResponse(answers[headers["xi-api-key"]])


real_http = httpx.AsyncClient
httpx.AsyncClient = FakeHttp
s = Speaker(kind="elevenlabs", voice="v", elevenlabs_key="el-a")
pcm, rate = asyncio.run(s._elevenlabs("hello"))
check("a refused key: the account's next, without a word lost", sent == ["el-a", "el-b"] and rate == 24000 and pcm, str(sent))
check("and stays on the one that works", s._el_key == "el-b")
providers._key_rest.clear()
sent.clear()
answers.update({"el-a": 422, "el-b": 200})
try:
    asyncio.run(Speaker(kind="elevenlabs", voice="v", elevenlabs_key="el-a")._elevenlabs("hello"))
    check("a bad voice is not the key's doing", False)
except SpeakError as e:
    check("a bad voice is not the key's doing", sent == ["el-a"] and "422" in str(e), str(sent))
httpx.AsyncClient = real_http

print("\n== a realtime voice ==")
from app.voice import session as call_session  # noqa: E402
from app.voice.engines.realtime import GeminiLive, OpenAIRealtime  # noqa: E402

check("each knows whose keys it uses", GeminiLive.provider == "gemini" and OpenAIRealtime.provider == "openai")
envfile.write_env({"GEMINI_API_KEY_1": "g-a", "GEMINI_API_KEY_2": "g-b"})
providers._key_rest.clear()


class Engine:
    name, provider = "Gemini", "gemini"
    started = []

    def __init__(self, key, fail):
        self.key, self.fail = key, fail

    async def start(self):
        Engine.started.append(self.key)
        if self.fail.get(self.key):
            raise RuntimeError(self.fail[self.key])


class Own:
    name = "own"

    async def start(self):
        Engine.started.append("own")


def calling(fail):
    Engine.started.clear()
    providers._key_rest.clear()
    real = call_session.choose_engine, call_session.own_brain
    call_session.choose_engine = lambda calls, **k: Engine(providers.key_now("gemini"), fail)
    call_session.own_brain = lambda calls, **k: Own()
    me = call_session.CallSession.__new__(call_session.CallSession)
    me.calls, me.instructions, me.log = {}, "", lambda *_: None
    me.engine = call_session.choose_engine({})
    asyncio.run(me._start_engine())
    call_session.choose_engine, call_session.own_brain = real
    return me


me = calling({"g-a": "could not reach Gemini: server rejected WebSocket connection: HTTP 401"})
check("a key turned away: the next, on the same call", Engine.started == ["g-a", "g-b"] and me.engine.key == "g-b", str(Engine.started))
me = calling({"g-a": "quota exhausted", "g-b": "HTTP 429"})
check("all turned away: its own brain, and the call goes on", Engine.started == ["g-a", "g-b", "own"] and me.engine.name == "own", str(Engine.started))
me = calling({"g-a": "could not reach Gemini: no route to host"})
check("no network is not the key's doing: straight to its own brain", Engine.started == ["g-a", "own"], str(Engine.started))

print("\n== trying a model, and its list ==")
envfile.write_env({"CEREBRAS_API_KEY_1": "c-a", "CEREBRAS_API_KEY_2": "c-b"})
providers._key_rest.clear()
tried = []
real_with = models_routes._try_with


def fake_try(pid, model, config, key):
    tried.append(key)
    return {"ok": False, "error": "Refused.", "status": 401} if key == "c-a" else {"ok": True, "ms": 5, "reply": "ok"}


models_routes._try_with = fake_try
r = models_routes._try("cerebras", "m", {})
check("Try goes on to the next the way a reply would", r["ok"] and tried == ["c-a", "c-b"] and "status" not in r, str(r))
providers._key_rest.clear()
tried.clear()
models_routes._try_with = lambda pid, model, config, key: tried.append(key) or {"ok": False, "error": "No such model.", "status": 404}
r = models_routes._try("cerebras", "m", {})
check("not for a model that is not there", not r["ok"] and tried == ["c-a"], str(r))
models_routes._try_with = real_with
providers._key_rest.clear()

real_models = providers._models_with
tried.clear()


def fake_models(pid, key, config, timeout):
    tried.append(key)
    return ([], "The key was refused.", 401) if key == "c-a" else ([{"id": "m", "capabilities": ["chat"]}], "", 0)


providers._models_with = fake_models
providers.forget("cerebras")
got = providers.list_models("cerebras", {}, force=True)
check("a list of models from the first key that will give one", [m["id"] for m in got["models"]] == ["m"] and not got["error"] and tried == ["c-a", "c-b"], str(got))
providers._models_with = real_models
ai.log_system = real_log

print("\n== the panel ==")
panel = (ROOT / "webui/src/lib/components/ProvidersPanel.svelte").read_text(encoding="utf-8")
keylist = (ROOT / "webui/src/lib/components/KeyList.svelte").read_text(encoding="utf-8")
check("every connected card can add another", '"Add key"' in panel and "Add another key" in panel and "p.multi" not in panel)
check("and manage its own", "<KeyList name={p.id}" in panel and "manage[p.id]" in panel)
check("one card opening does not open them all", "groqKeys" not in panel)
check("with several, no one press loses them all", "{#if p.keys <= 1}" in panel)
check("the list is read again when it changes elsewhere", "void stamp;" in keylist and "stamp={p.keys}" in panel)
check("and the card told when it changes here", "onchange?.()" in keylist and "onchange={() => loadProviders()}" in panel)
check("keys are not called accounts", "{#if accounts}" in keylist and "accounts={false}" in panel)

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
