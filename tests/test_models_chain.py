"""Models: which provider does which job, and falling through the reply chain.

The app knew two places a model could live, Groq and a server on this machine,
and replies went to one or the other with a switch. Now replies are an ordered
chain across any provider (OpenAI, Anthropic, Gemini, OpenRouter, ...), and
each smaller job names one model, falling back to Groq. Checked here: an old
config means exactly what it used to; the chain falls through on a rate limit
and rests the entry that failed; a job on another provider falls back to Groq;
the reasoning of a thinking model is found wherever the provider put it and
kept out of the reply; and provider keys are masked like every other secret.
"""
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tempfile
_SB = Path(tempfile.mkdtemp(prefix="modelschain_"))
(_SB / "logs").mkdir()
import app.web.logbus as logbus          # rate limits are logged; keep them out of the real log
logbus.LOGS_DIR = _SB / "logs"
logbus.bus.file_path = _SB / "logs" / "app.jsonl"

from app.utils import providers
import app.utils.ai as ai

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def cfg(**bot):
    base = {"groq_models": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"],
            "groq_small_model": "openai/gpt-oss-20b", "groq_image_model": "img-model",
            "groq_whisper_model": "whisper-large-v3-turbo", "groq_tts_model": "orpheus",
            "local": {"enabled": False, "base_url": "http://127.0.0.1:11434/v1", "model": ""}}
    base.update(bot)
    return {"bot": base}


print("== an old config means what it always did ==")
c = cfg()
check("replies are Groq's list, in order",
      providers.reply_chain(c) == [{"provider": "groq", "model": "openai/gpt-oss-120b"},
                                   {"provider": "groq", "model": "llama-3.3-70b-versatile"}])
check("the jobs are Groq's models", providers.job(c, "vision") == {"provider": "groq", "model": "img-model"}
      and providers.job(c, "small")["model"] == "openai/gpt-oss-20b")
c = cfg(local={"enabled": True, "base_url": "http://127.0.0.1:11434/v1", "model": "llama3.1:8b"})
check("local switched on means local only, as it promised",
      providers.reply_chain(c) == [{"provider": "local", "model": "llama3.1:8b"}])
check("and background work there too", providers.job(c, "small") == {"provider": "local", "model": "llama3.1:8b"})
c = cfg(local={"enabled": False, "base_url": "http://127.0.0.1:11434/v1", "model": "", "vision_model": "llava"})
check("a local job works without local replies", providers.job(c, "vision") == {"provider": "local", "model": "llava"})

print("\n== the Models tab's own settings ==")
c = cfg(models={"replies": [{"provider": "openai", "model": "gpt-4o-mini"}, {"provider": "groq", "model": "x"},
                            {"provider": "nope", "model": "y"}, {"provider": "groq", "model": ""}],
                "vision": {"provider": "gemini", "model": "gemini-2.5-flash"},
                "stt": {"provider": "", "model": ""}})
check("the chain is taken as written, junk dropped",
      providers.reply_chain(c) == [{"provider": "openai", "model": "gpt-4o-mini"}, {"provider": "groq", "model": "x"}],
      str(providers.reply_chain(c)))
check("a chosen job wins", providers.job(c, "vision") == {"provider": "gemini", "model": "gemini-2.5-flash"})
check("an unset job stays on Groq", providers.job(c, "stt") == {"provider": "groq", "model": "whisper-large-v3-turbo"})

print("\n== what a model can do, from its name ==")
check("a GPT model writes and sees", providers.capabilities("openai", "gpt-4o") == ["chat", "vision"])
check("whisper hears", providers.capabilities("openai", "whisper-1") == ["stt"])
check("tts speaks", providers.capabilities("openai", "gpt-4o-mini-tts") == ["tts"])
check("embeddings do none of it", providers.capabilities("openai", "text-embedding-3-small") == [])
check("DeepSeek chat writes", providers.capabilities("deepseek", "deepseek-chat") == ["chat"])


# ── Fakes ────────────────────────────────────────────────────────────────────
class Resp:
    def __init__(self, content, reasoning=None):
        msg = types.SimpleNamespace(content=content, model_extra={})
        if reasoning:
            msg.reasoning = reasoning
        self.choices = [types.SimpleNamespace(message=msg)]


class FakeClient:
    def __init__(self, name, fail=None, reasoning=None):
        self.name, self.fail, self.calls, self.reasoning = name, fail, [], reasoning
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
        self.audio = types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=self._tx))

    async def _create(self, model, messages, **kw):
        self.calls.append(model)
        if self.fail:
            raise self.fail
        return Resp(f"{self.name}:{model}", self.reasoning)

    async def _tx(self, model, file, **kw):
        self.calls.append(model)
        if self.fail:
            raise self.fail
        return types.SimpleNamespace(text=f"{self.name}:{model}")


class RateLimited(Exception):
    pass


def setup(config, groq, others):
    ai._initialised = True
    ai._groq_clients = [{"client": groq, "label": "GROQ_API_KEY_1"}] if groq else []
    ai._client_index = 0
    ai._resting.clear()
    ai.load_config = lambda: config
    ai._openai_client = lambda pid, c: others.get(pid)


print("\n== the reply chain falls through ==")
c = cfg(models={"replies": [{"provider": "openai", "model": "gpt-4o-mini"},
                            {"provider": "groq", "model": "openai/gpt-oss-120b"}]})
oa = FakeClient("openai", fail=RateLimited("Error code: 429 - rate limit, try again in 12s"))
gq = FakeClient("groq")
setup(c, gq, {"openai": oa})
r = asyncio.run(ai._create_completion([{"role": "user", "content": "hi"}]))
check("a rate limited first entry hands over to the next", r.choices[0].message.content == "groq:openai/gpt-oss-120b")
check("and says who wrote it", ai.last_reply_model == "Groq · openai/gpt-oss-120b", ai.last_reply_model)
check("the one that failed rests for as long as it was told",
      10 < ai._resting.get(("openai", "gpt-4o-mini"), 0) - __import__("time").time() <= 14)
oa.calls.clear()
asyncio.run(ai._create_completion([{"role": "user", "content": "hi"}]))
check("so the next reply starts with the one that works", oa.calls == [] or gq.calls[-1] == "openai/gpt-oss-120b")

oa2 = FakeClient("openai", fail=RateLimited("429"))
gq2 = FakeClient("groq", fail=RateLimited("Rate limit reached ... try again in 3s"))
setup(c, gq2, {"openai": oa2})
try:
    asyncio.run(ai._create_completion([{"role": "user", "content": "hi"}]))
    check("when every entry fails the last error comes out", False)
except RateLimited as e:
    check("when every entry fails the last error comes out", "Rate limit reached" in str(e), str(e))

c = cfg(models={"replies": [{"provider": "anthropic", "model": "claude"}]})
setup(c, None, {})
try:
    asyncio.run(ai._create_completion([{"role": "user", "content": "hi"}]))
    check("a chain with nothing usable says so", False)
except RuntimeError as e:
    check("a chain with nothing usable says so", "Settings > Models" in str(e), str(e))

print("\n== the smaller jobs ==")
c = cfg(models={"vision": {"provider": "gemini", "model": "gemini-2.5-flash"}})
gm = FakeClient("gemini")
gq = FakeClient("groq")
setup(c, gq, {"gemini": gm})
r = asyncio.run(ai._create_image_completion("img-model", [{"role": "user", "content": "x"}]))
check("pictures go where they are set to", r.choices[0].message.content == "gemini:gemini-2.5-flash")
gm.fail = RuntimeError("503 overloaded")
r = asyncio.run(ai._create_image_completion("img-model", [{"role": "user", "content": "x"}]))
check("and fall back to Groq's model when that fails", r.choices[0].message.content == "groq:img-model")
setup(cfg(), gq, {})
r = asyncio.run(ai._create_image_completion("img-model", [{"role": "user", "content": "x"}]))
check("unset, pictures stay on Groq", r.choices[0].message.content == "groq:img-model")

import io
c = cfg(models={"stt": {"provider": "openai", "model": "whisper-1"}})
setup(c, FakeClient("groq"), {"openai": FakeClient("openai", fail=RuntimeError("boom"))})
f = io.BytesIO(b"abc")
f.read()
r = asyncio.run(ai._create_transcription("whisper-large-v3-turbo", f))
check("voice messages fall back too, from the start of the file",
      r.text == "groq:whisper-large-v3-turbo" and f.tell() == 0)

c = cfg(models={"replies": [{"provider": "openai", "model": "gpt-4o-mini"}]})
oa = FakeClient("openai")
setup(c, None, {"openai": oa})
r = asyncio.run(ai._create_small_completion([{"role": "user", "content": "x"}]))
check("no Groq key: background work goes to whatever writes replies", r.choices[0].message.content == "openai:gpt-4o-mini")

print("\n== thinking ==")
check("Groq's reasoning field is found", ai._reasoning_of(Resp("hi", reasoning="I should greet")) == "I should greet")
r = Resp("<think>they said hi\nso hi back</think>\nhey!")
check("a <think> block is found", ai._reasoning_of(r) == "they said hi\nso hi back")
check("and kept out of the reply", ai._answer_of(r) == "hey!", repr(ai._answer_of(r)))
check("no thinking, nothing shown", ai._reasoning_of(Resp("hi")) == "")

print("\n== keys ==")
from app.web.envfile import SECRET_KEYS
check("every provider's key is masked like the others",
      all(SECRET_KEYS.match(p["env"]) for p in providers.PROVIDERS if p["env"]))
check("a Discord token still is", bool(SECRET_KEYS.match("DISCORD_TOKEN_2")))
check("an ordinary setting is not", not SECRET_KEYS.match("SNAP_USERNAME"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
