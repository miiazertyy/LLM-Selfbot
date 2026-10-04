"""How a reply is sampled, set in Settings.

temperature and top_p are how varied the model lets itself be; the two
penalties push it away from repeating itself, which is what stops a character
answering several people with the same three sentences. Not every provider
takes all of them, and one unknown field is a 400 for the whole request, so
what is sent is filtered per provider and a refusal is recovered from rather
than losing the reply.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import providers as P

FULL = {"bot": {"sampling": {"temperature": 0.9, "top_p": 0.95,
                             "frequency_penalty": 0.6, "presence_penalty": 0.3}}}

print("== nothing is sent unless it is set ==")
check("an empty section sends nothing", P.sampling_args("groq", {"bot": {"sampling": {}}}) == {})
check("a missing section too", P.sampling_args("groq", {"bot": {}}) == {})
check("and a blank value is not a zero",
      P.sampling_args("openai", {"bot": {"sampling": {"temperature": ""}}}) == {})
check("nor is None", P.sampling_args("openai", {"bot": {"sampling": {"temperature": None}}}) == {})

print("\n== each provider gets only what it takes ==")
check("one that takes all four", P.sampling_args("openai", FULL) == {
    "temperature": 0.9, "top_p": 0.95, "frequency_penalty": 0.6, "presence_penalty": 0.3})
check("Groq takes them too", len(P.sampling_args("groq", FULL)) == 4)
for pid in ("anthropic", "gemini", "local"):
    got = P.sampling_args(pid, FULL)
    check(f"{pid} is sent no penalties, which it has none of",
          set(got) == {"temperature", "top_p"}, str(got))
check("a provider nobody listed gets the full set, since they all speak the same API",
      set(P.sampling_args("together", FULL)) == set(P.SAMPLING))

print("\n== values that would be refused are made sane first ==")
wild = {"bot": {"sampling": {"temperature": 9, "top_p": -3,
                             "frequency_penalty": 50, "presence_penalty": -50}}}
got = P.sampling_args("openai", wild)
check("temperature is capped at 2", got["temperature"] == 2.0, str(got))
check("top_p cannot go below 0", got["top_p"] == 0.0, str(got))
check("the penalties are held to -2..2", got["frequency_penalty"] == 2.0 and got["presence_penalty"] == -2.0, str(got))
check("something that is not a number is skipped, not crashed on",
      P.sampling_args("openai", {"bot": {"sampling": {"temperature": "hot"}}}) == {})

print("\n== a provider that refuses them still answers ==")
from app.utils.ai import _rejects_sampling


class _Err(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        if code is not None:
            self.status_code = code


check("a 400 naming one of the fields is recognised", _rejects_sampling(_Err("Unknown parameter: frequency_penalty", 400)))
check("so is an 'unsupported parameter'", _rejects_sampling(_Err("unsupported parameter: top_p", 400)))
check("and the SDK refusing the keyword outright", _rejects_sampling(TypeError("unexpected keyword argument 'presence_penalty'")))
check("a rate limit is not mistaken for one", not _rejects_sampling(_Err("rate limit exceeded", 429)))
check("nor is a real 400 about something else", not _rejects_sampling(_Err("context length exceeded", 400)))
check("nor a server error that happens to say temperature",
      not _rejects_sampling(_Err("temperature service unavailable", 503)))

AI = (ROOT / "app" / "utils" / "ai.py").read_text(encoding="utf-8")
check("the reply is sent again without them rather than lost", "_no_sampling.add(pid)" in AI)
check("and that provider is not asked again this run", "pid in _no_sampling" in AI)
check("it says so once, so this is not invisible", "does not take those sampling settings" in AI)
check("Groq's own path takes them as well", "async def _groq_chat(model_id, messages, max_tokens, sampling=None)" in AI)

print("\n== it is all in Settings ==")
cfg = yaml.safe_load((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"))
block = (cfg.get("bot") or {}).get("sampling")
check("the section exists", isinstance(block, dict) and set(block) == set(P.SAMPLING), str(block))
check("and every one starts unset, so nothing changes until it is asked for",
      all(v is None for v in block.values()), str(block))
from app.web.schema import CONFIG_SCHEMA
keys = {f["key"]: f for f in CONFIG_SCHEMA}
for name in P.SAMPLING:
    k = f"bot.sampling.{name}"
    check(f"{k} has a control", k in keys)
    check(f"{k} has its range", "min" in keys.get(k, {}) and "max" in keys.get(k, {}))
from app.web import descriptions as desc
check("each says what it does and when it is ignored",
      all(desc.DESCRIPTIONS.get(f"bot.sampling.{n}") for n in P.SAMPLING))
check("and the penalty one warns it is not taken everywhere",
      "not every provider" in desc.DESCRIPTIONS["bot.sampling.frequency_penalty"].lower())
smap = (ROOT / "webui" / "src" / "lib" / "settingsmap.ts").read_text(encoding="utf-8")
check("they have their own subtab", 'name: "How it writes"' in smap and '"bot.sampling.temperature"' in smap)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
