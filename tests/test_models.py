"""Credentials, model names, and saying so when the provider refuses.

Three bugs, all of the same shape: something was wrong and nothing said so.

  * The doctor reported three working Groq keys as "not set", because it looked
    only at GROQ_API_KEY while they are stored as GROQ_API_KEY_1, _2, _3.
  * A model Groq had retired failed every reply with a 404 that read like the
    bot was broken, with nothing anywhere naming the cause.
  * A 429 was swallowed whole: pictures simply had no description and no
    explanation, when the provider had answered with a perfectly clear message
    about which limit was hit.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


# ── Numbered credentials count as set ───────────────────────────────────────
print("== a key stored under a numbered name is still a key ==")
from app.utils.credentials import real, real_any, is_placeholder

for var in list(os.environ):
    if var.startswith(("GROQ_API_KEY", "DISCORD_TOKEN")):
        del os.environ[var]

# Invented values, assembled rather than written out. See test_credentials.py:
# GitHub's push protection matches the shape of a token, not whether it works,
# and a literal of this shape in a committed file blocks the push.
FAKE_GROQ = "gsk_" + "realkey0000000000000000000000"
FAKE_DISCORD = ".".join(["MTIzNDU2Nzg5MDEyMzQ1Njc4", "GaBcDe", "FgHiJkLmNoPqRsTu"])

os.environ["GROQ_API_KEY_1"] = FAKE_GROQ
os.environ["DISCORD_TOKEN_1"] = FAKE_DISCORD

check("the bare name alone finds nothing", real("GROQ_API_KEY") == "")
check("the numbered name is found", bool(real_any("GROQ_API_KEY")))
check("the same for a token", bool(real_any("DISCORD_TOKEN")))

os.environ["GROQ_API_KEY_2"] = "your_key_here"
check("a placeholder never counts", is_placeholder("your_key_here"))
os.environ.pop("GROQ_API_KEY_1")
check("only placeholders left reads as unset", real_any("GROQ_API_KEY") == "")
os.environ["GROQ_API_KEY_1"] = FAKE_GROQ

# ── Retired models ──────────────────────────────────────────────────────────
print("\n== a model Groq no longer offers ==")
from app.utils import groqmodels

groqmodels._cache.update(at=9e18, error="", models=[
    {"id": "openai/gpt-oss-120b", "kind": "chat", "active": True, "owned_by": "OpenAI",
     "context_window": 131072, "max_completion_tokens": 65536},
    {"id": "qwen/qwen3.6-27b", "kind": "chat", "active": True, "owned_by": "Alibaba",
     "context_window": 131072, "max_completion_tokens": 16384},
    {"id": "old-and-retired", "kind": "chat", "active": False, "owned_by": "x",
     "context_window": 8192, "max_completion_tokens": 4096},
])

problems = groqmodels.check_configured({"bot": {
    "groq_models": ["openai/gpt-oss-120b", "llama-3.1-70b-versatile"],
    "groq_image_model": "qwen/qwen3.6-27b",
}})
check("a model missing from the list is reported", len(problems) == 1, str(problems))
check("it names the model", problems and problems[0]["model"] == "llama-3.1-70b-versatile")
check("a configured model that exists is not reported",
      all(p["model"] != "openai/gpt-oss-120b" for p in problems))

retired = groqmodels.check_configured({"bot": {"groq_models": ["old-and-retired"]}})
check("a model marked inactive is reported as retired",
      retired and retired[0]["reason"] == "retired", str(retired))

# Not being able to check is not evidence of a problem.
saved = list(groqmodels._cache["models"])
groqmodels._cache.update(models=[])
try:
    quiet = groqmodels.check_configured({"bot": {"groq_models": ["anything-at-all"]}})
    check("no list means no accusation", quiet == [], str(quiet))
finally:
    groqmodels._cache.update(models=saved)

check("a vision-ish name is classified as such",
      groqmodels.classify("meta-llama/llama-4-scout-17b-16e-instruct") == "vision")
check("whisper is audio", groqmodels.classify("whisper-large-v3") == "audio")
check("an ordinary model is chat", groqmodels.classify("openai/gpt-oss-120b") == "chat")

# ── The provider refusing, in words ─────────────────────────────────────────
print("\n== a 429 turned into something readable ==")
from app.utils import apihealth

apihealth.clear()
REAL_429 = (
    "Error code: 429 - {'error': {'message': \"Request too large for model "
    "`qwen/qwen3.6-27b` in organization `org_01abc` service tier `on_demand` on output "
    "tokens per minute (OTPM): Limit 1000, Requested 1751. The request's expected output "
    "tokens exceed the enforced limit; reduce max_tokens (or the request's expected "
    "output) and try again.\", 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)
event = apihealth.record("rate_limit", REAL_429, model="qwen/qwen3.6-27b")
check("the limit and the ask both survive",
      "1000" in event["message"] and "1751" in event["message"], event["message"])
check("it says which limit", "output tokens per minute" in event["message"], event["message"])
check("no stray comma from the number", "1000," not in event["message"], event["message"])
check("it is not just the raw blob", "org_01abc" not in event["message"], event["message"])

summary = apihealth.summary()
check("a summary is offered while it is fresh", summary and summary["kind"] == "rate_limit")
check("nothing is reported once it has aged out", apihealth.summary(within=0) is None)

apihealth.clear()
check("cleared means quiet", apihealth.summary() is None)

# ── Reasoning and formatting stripped from a description ────────────────────
print("\n== a thinking model's answer, made readable ==")
from app.utils.humanize import plain_text, strip_reasoning

answer = (
    "<think>\nThe user wants a description. Wait, let me re-examine the bounding box.\n"
    "Actually it looks like 5 panels? Let me re-check.\n</think>\n\n"
    "**1. Overall Structure:**\nA vertical collage.\n"
    "-   **Subject:** A young woman.\n"
)
cleaned = plain_text(answer)
check("the monologue is gone", "bounding box" not in cleaned, cleaned[:80])
check("the answer survives", "vertical collage" in cleaned.lower(), cleaned[:80])
check("no bold markers", "**" not in cleaned, cleaned[:80])
check("no numbered heading", not cleaned.startswith("1."), cleaned[:40])
check("no bullet dashes at line starts",
      not any(l.startswith(("-", "*")) for l in cleaned.split("\n")), cleaned)

truncated = "<think>I should start by looking at the top panel and then"
check("an unclosed block leaves nothing to store", plain_text(truncated) == "",
      repr(plain_text(truncated)))
check("ordinary prose is untouched",
      strip_reasoning("A woman in a grey sweater.") == "A woman in a grey sweater.")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
