"""Every model's usage is counted, and its row lights up when it is used.

No provider lets an ordinary key ask for its usage (Groq's API reference has
no such endpoint), so the runners count every answer themselves, through the
SDK's own HTTP client, and keep the rate limit headers that came with it. The
panel shows it under Models, Usage, and each answer blinks its model's row.
"""
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


tmp = Path(tempfile.mkdtemp(prefix="llmbot_usage_"))
import app.utils.db as db
db.db_path = str(tmp / "bot_data.db")
db._pragmas_applied = False
from app.utils import usage

print("== what the headers say is left ==")
g = usage.parse_limits("groq", {
    "x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "999", "x-ratelimit-reset-requests": "1m26.4s",
    "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "7858", "x-ratelimit-reset-tokens": "1.06s"})
by = {(x["what"], x["window"]): x for x in g}
check("Groq's requests are counted per day", by.get(("requests", "day"), {}).get("remaining") == 999)
check("and its tokens per minute", by.get(("tokens", "minute"), {}).get("limit") == 8000)
check("with when each is full again", 80 < by[("requests", "day")]["reset_at"] - time.time() < 90)
c = usage.parse_limits("cerebras", {"x-ratelimit-limit-requests-day": "14400", "x-ratelimit-remaining-tokens-minute": "59000",
                                    "x-ratelimit-limit-tokens-minute": "60000"})
check("Cerebras names its windows", {(x["what"], x["window"]) for x in c} == {("requests", "day"), ("tokens", "minute")})
a = usage.parse_limits("anthropic", {"anthropic-ratelimit-requests-limit": "50", "anthropic-ratelimit-requests-remaining": "49"})
check("Anthropic's own header names", a and a[0]["remaining"] == 49)
m = usage.parse_limits("mistral", {"x-ratelimitbysize-limit-month": "1000000000", "x-ratelimitbysize-remaining-month": "999"})
check("Mistral's monthly tokens", m and m[0]["what"] == "tokens" and m[0]["window"] == "month")
check("nothing when a provider sends none", usage.parse_limits("gemini", {"content-type": "application/json"}) == [])
check("durations read the way providers write them",
      usage._duration("450ms") == 0.45 and usage._duration("1h2m3s") == 3723 and usage._duration("junk") is None)

print("\n== counting ==")
now = time.time()
base = {"provider": "groq", "model": "qwen/qwen3.8-27b", "job": "replies", "ok": True, "limited": False, "status": 200,
        "in": 1000, "out": 40, "reasoning": 0, "ms": 800, "key": "K1", "at": now,
        "limits": [{"what": "requests", "window": "day", "limit": 1000, "remaining": 990}]}
usage.save(base)
usage.save({**base, "in": 500, "out": 20, "ms": 400, "key": "K2",
            "limits": [{"what": "requests", "window": "day", "limit": 1000, "remaining": 1, "reset_at": now - 5}]})
usage.save({**base, "ok": False, "limited": True, "status": 429, "in": 0, "out": 0, "limits": []})
usage.save({**base, "job": "small", "in": 100, "out": 5})
s = usage.summary(7)
q = s["models"][0]
check("answers add up per model", q["today"]["requests"] == 3 and q["today"]["in"] == 1600 and q["today"]["out"] == 65)
check("a refusal is counted as one, not as a request", q["today"]["limited"] == 1)
check("by job", q["jobs"] == {"replies": 2, "small": 1}, str(q["jobs"]))
check("seven days, ending today", len(q["days"]) == 7 and q["days"][-1]["day"] == s["today"] and q["days"][-1]["requests"] == 3)
lim = q["limits"][0]
check("several keys add up, and one whose day has reset counts as full again",
      lim["keys"] == 2 and lim["limit"] == 2000 and lim["remaining"] == 1990, str(lim))

print("\n== read on the way back, without getting in the SDK's way ==")
import httpx
import openai

answers = []


def handler(request):
    answers.append(json.loads(request.content))
    return httpx.Response(200, json={
        "id": "x", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 78, "completion_tokens": 32, "total_tokens": 110,
                  "completion_tokens_details": {"reasoning_tokens": 20}},
    }, headers={"x-ratelimit-limit-tokens": "6000", "x-ratelimit-remaining-tokens": "5890"})


Orig = openai.DefaultAsyncHttpxClient


class Mocked(Orig):
    def __init__(self, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        super().__init__(**kw)


openai.DefaultAsyncHttpxClient = Mocked
os.environ["LLMSELFBOT_CHILD"] = "1"
out = io.StringIO()
real_stdout, sys.stdout = sys.stdout, out


async def call():
    client = openai.AsyncOpenAI(api_key="k", base_url="https://api.example.test/v1", http_client=usage.http_client("openai"))
    tok = usage.JOB.set("vision")
    try:
        return await client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
    finally:
        usage.JOB.reset(tok)


try:
    r = asyncio.run(call())
finally:
    sys.stdout = real_stdout
openai.DefaultAsyncHttpxClient = Orig
time.sleep(0.3)
check("the SDK still gets the whole answer", r.choices[0].message.content == "ok" and r.usage.prompt_tokens == 78)
mine = next((m for m in usage.summary(7)["models"] if m["model"] == "gpt-4o-mini"), None)
check("and the answer is counted, as the job it was for", mine and mine["today"]["in"] == 78
      and mine["today"]["out"] == 32 and mine["jobs"] == {"vision": 1}, str(mine))
# split on newlines only: str.splitlines() also breaks at the record separator, the mark's own first character
line = next((l for l in out.getvalue().split("\n") if l.startswith(usage.MODEL_MARK)), "")
evt = json.loads(line[len(usage.MODEL_MARK):]) if line else {}
check("the panel is told the moment it happens", evt.get("model") == "gpt-4o-mini" and evt.get("ok") is True
      and evt.get("provider") == "openai")

print("\n== wired in ==")
src = lambda p: (ROOT / p).read_text(encoding="utf-8")
ai = src("app/utils/ai.py")
check("every provider's client counts", "http_client=usage.http_client(pid)" in ai)
check("every Groq key's client too", 'usage.http_client("groq", label, sdk="groq")' in ai)
check("replies and jobs are told apart", 'usage.JOB.set("replies")' in ai and "usage.JOB.set(name)" in ai)
tts = src("app/utils/tts.py")
check("and speaking", tts.count("usage.http_client(") == 3 and 'usage.JOB.set("tts")' in tts)
sup = src("app/web/supervisor.py")
check("the supervisor passes each answer to the panel", 'MODEL_MARK = "\\x1eMODEL "' in sup and 'bus.event("model", evt)' in sup)
routes = src("app/web/routes/models_routes.py")
check("the panel reads the counts", '@router.get("/api/models/usage")' in routes)
check("and asks each provider what is left", '@router.get("/api/models/left")' in routes and "whatsleft.ask_all" in routes)
smap = src("webui/src/lib/settingsmap.ts")
check("Models has a Usage subtab", 'id: "usage"' in smap and 'panel: "usage"' in smap)
panel = src("webui/src/lib/components/ModelsPanel.svelte")
check("a model's row blinks when it answers", '{#key used}<span class="mp-blink"' in panel and "@keyframes mp-blink" in panel)
check("and says how often it has today", "today.toLocaleString()} today" in panel)
up = src("webui/src/lib/components/UsagePanel.svelte")
check("the usage page shows what is left of each limit", "us-gauge" in up and "{fmt(lim.remaining)}" in up and "of {fmt(lim.limit)}" in up)
check("with a hover layer on the week's bars", "data-tip=" in up and ".us-day:hover::after" in up)

print("\n== what is left, asked of each provider ==")
from app.utils import whatsleft  # noqa: E402

sent, answers = [], {}


class Answer:
    def __init__(self, status=200, headers=None, body=b"{}"):
        self.status, self.headers, self.body = status, type("H", (), {"items": lambda s, h=headers or {}: list(h.items())})(), body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def fake_open(req, timeout=0):
    url = req.full_url
    data = json.loads(req.data) if req.data else None
    sent.append((url, data, dict(req.headers)))
    got = answers(url, data, dict(req.headers))
    if isinstance(got, Exception):
        raise got
    return got


import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

real_open, real_keys, real_env, real_list = urllib.request.urlopen, whatsleft.providers.keys_for, whatsleft.providers._env_value, whatsleft.providers.list_models
urllib.request.urlopen = fake_open
keyring = {"groq": ["g1", "g2", "g3"], "openrouter": ["or"], "deepseek": ["ds"], "elevenlabs": ["el"], "gemini": ["ge"], "cerebras": ["ce"], "openai": ["oa"]}
whatsleft.providers.keys_for = lambda pid: keyring.get(pid, [])
whatsleft.providers._env_value = lambda name: {"GROQ_API_KEY_1": "g1", "GROQ_API_KEY_2": "g2", "GROQ_API_KEY_3": "g3"}.get(name, "")
config = {"bot": {"groq_models": ["qwen/qwen3.8-27b"], "models": {"replies": [{"provider": "groq", "model": "qwen/qwen3.8-27b"}, {"provider": "cerebras", "model": "gpt-oss-120b"}]}}}
GROQ_HEADERS = {"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "990", "x-ratelimit-limit-tokens": "8000",
                "x-ratelimit-remaining-tokens": "7900", "x-ratelimit-reset-requests": "1m26.4s", "x-ratelimit-reset-tokens": "547ms"}
answers = lambda url, data, headers: Answer(headers=GROQ_HEADERS)
g = whatsleft.ask("groq", config)
asked = [s for s in sent if s[0].endswith("/chat/completions")]
check("Groq: one token, of a model it uses, from each of its keys", len(asked) >= 3 and all(s[1]["max_tokens"] == 1 for s in asked)
      and {s[2].get("Authorization") for s in asked} == {"Bearer g1", "Bearer g2", "Bearer g3"}, str(len(asked)))
limits = {(x["what"], x["window"]): x for x in g["models"][0]["limits"]}
check("what they said, added up across its keys", limits[("requests", "day")]["remaining"] == 2970 and limits[("requests", "day")]["limit"] == 3000
      and limits[("tokens", "minute")]["remaining"] == 23700, str(limits))
check("said by key, three of them", g["keys"] == 3 and limits[("requests", "day")]["keys"] == 3)
usage.keep_limits("groq", "qwen/qwen3.8-27b", "GROQ_API_KEY_9", [{"what": "requests", "window": "day", "limit": 1000, "remaining": 1000}])
check("a key that was removed does not stay added in", whatsleft.ask("groq", config)["models"][0]["limits"][0]["limit"] == 3000)
day = usage.summary(1)["models"]
check("not counted as requests: they were not the app doing anything", not any(m["provider"] == "groq" and m["model"] == "qwen/qwen3.8-27b" and m["today"]["requests"] and m["today"]["in"] == 0 for m in day))
check("kept with what real answers said", usage.limits_of("groq")["qwen/qwen3.8-27b"][0]["limit"] > 0)

sent.clear()
answers = lambda url, data, headers: Answer(headers={"x-ratelimit-limit-tokens-day": "1000000", "x-ratelimit-remaining-tokens-day": "900000",
                                                     "x-ratelimit-limit-requests-day": "14400", "x-ratelimit-remaining-requests-day": "14000"})
c = whatsleft.ask("cerebras", config)
check("Cerebras: by the day, as its headers say", {(x["what"], x["window"]) for x in c["models"][0]["limits"]} == {("tokens", "day"), ("requests", "day")}, str(c))
check("each other provider once, its keys being kept as one", len(sent) == 1, str(len(sent)))

sent.clear()
answers = lambda url, data, headers: Answer(body=json.dumps({"data": {"usage": 3.5, "usage_daily": 0.25, "usage_monthly": 1.5, "limit": 10, "limit_remaining": 6.5, "is_free_tier": False}}).encode())
o = whatsleft.ask("openrouter", config)
check("OpenRouter: from its account, spending nothing", o["money"]["left"] == 6.5 and o["money"]["today"] == 0.25 and sent[0][0].endswith("/key") and sent[0][1] is None, str(o))
answers = lambda url, data, headers: Answer(body=json.dumps({"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": "12.30", "granted_balance": "0", "topped_up_balance": "12.30"}]}).encode())
d = whatsleft.ask("deepseek", config)
check("DeepSeek: its balance", d["money"] == {"currency": "USD", "left": 12.3, "granted": 0.0, "topped_up": 12.3}, str(d["money"]))
answers = lambda url, data, headers: Answer(body=json.dumps({"tier": "creator", "character_count": 100, "character_limit": 30000, "next_character_count_reset_unix": 1790000000}).encode())
e = whatsleft.ask("elevenlabs", config)
check("ElevenLabs: its characters, and when they come back", e["meters"][0]["what"] == "characters" and e["meters"][0]["remaining"] == 29900 and e["meters"][0]["reset_at"] == 1790000000 and e["plan"] == "Creator", str(e))
sent.clear()
ge = whatsleft.ask("gemini", config)
check("Google says nothing, so nothing is spent finding that out", not sent and "does not say" in ge["why"] and ge["link"].startswith("https://aistudio.google.com"))


def refusal(status, body=b"{}"):
    import io
    return urllib.error.HTTPError("u", status, "no", type("H", (), {"items": lambda s: []})(), io.BytesIO(body))


answers = lambda url, data, headers: refusal(401)
check("a key refused says so", "refused" in whatsleft.ask("groq", config)["why"])
check("on an account route too", "refused" in whatsleft.ask("deepseek", config)["why"])
answers = lambda url, data, headers: OSError("down")
check("no answer says so, and does not fall over", "Could not reach" in whatsleft.ask("deepseek", config)["why"])
calls = []


def wants_other_field(url, data, headers):
    calls.append(data)
    if "max_tokens" in data:
        return refusal(400, b"Unsupported parameter: use max_completion_tokens instead")
    return Answer(headers={"x-ratelimit-limit-requests": "500", "x-ratelimit-remaining-requests": "499"})


answers = wants_other_field
whatsleft.providers.list_models = lambda pid, cfg, force=False, timeout=8.0: {"models": [{"id": "gpt-x", "capabilities": ["chat"]}]}
oa = whatsleft.ask("openai", {"bot": {"groq_models": []}})
check("a model that takes the limit under another name is asked again that way", any("max_completion_tokens" in x for x in calls) and oa["models"][0]["limits"][0]["limit"] == 500, str(oa))
whatsleft.providers.list_models = lambda pid, cfg, force=False, timeout=8.0: {"models": [{"id": "whisper-x", "capabilities": ["stt"]}]}
check("nothing that can answer: nothing asked", "no model" in whatsleft.ask("together", {"bot": {}})["why"] if keyring.setdefault("together", ["t"]) else False)
keyring.clear()
keyring.update({"groq": ["g1"], "deepseek": ["ds"]})
answers = lambda url, data, headers: Answer(headers=GROQ_HEADERS, body=json.dumps({"is_available": True, "balance_infos": []}).encode())
order = [p["id"] for p in whatsleft.ask_all(config)]
check("only those with a key, and never this computer", order == ["groq", "deepseek"], str(order))
urllib.request.urlopen, whatsleft.providers.keys_for, whatsleft.providers._env_value, whatsleft.providers.list_models = real_open, real_keys, real_env, real_list

print("\n== the page ==")
check("what is left comes first, from each of them", up.index("What is left") < up.index(">Today<") and "api.modelsLeft(again)" in up)
check("its money, its meters, and each model's limits", "p.money?.left" in up and "{#each p.meters as lim" in up and "{#each p.models as m (m.model)}" in up)
check("each with its logo", '<ProviderTile id={p.id} size={28} />' in up)
check("asked again by hand", ">Ask again" in up or "Ask again" in up)
check("what one will not say is said, with the way to its own page", "{p.why}" in up and 'href={p.link}' in up)
check("one row a model, not a card", 'class="us-row"' in up and "us-card" not in up and "us-tile" not in up)
check("nothing there twice: the head says the day's totals, and nothing under it does", "totals.requests" not in up)
check("no outlines or shadows at rest", "box-shadow" not in up)
check("its note in the strip every page's note is in", "<FootNote" in up)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
