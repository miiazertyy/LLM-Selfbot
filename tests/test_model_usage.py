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
check("and the balances a provider will give", "openrouter.ai/api/v1/key" in routes and "api.deepseek.com/user/balance" in routes)
smap = src("webui/src/lib/settingsmap.ts")
check("Models has a Usage subtab", 'id: "usage"' in smap and 'panel: "usage"' in smap)
panel = src("webui/src/lib/components/ModelsPanel.svelte")
check("a model's row blinks when it answers", '{#key used}<span class="mp-blink"' in panel and "@keyframes mp-blink" in panel)
check("and says how often it has today", "today.toLocaleString()} today" in panel)
up = src("webui/src/lib/components/UsagePanel.svelte")
check("the usage page shows what is left of each limit", "us-gauge" in up and "left of" in up)
check("with a hover layer on the week's bars", "data-tip=" in up and ".us-day:hover::after" in up)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
