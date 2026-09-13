"""A model has to be the right sort for the job it is given.

Five settings hold a Groq model id, and they need different things of it:
replies need a chat model, picture descriptions need one that accepts images,
transcription needs speech to text, voice messages need text to speech. Give
one the wrong sort and every single request fails, with an error that never
says the model was simply the wrong choice.

This was originally guessed from the name, and it got the important case wrong:
qwen3.6-27b and qwen3.8-27b accept images but have neither "vision" nor "vl" in
their id, so the picker showed no vision models at all while the model actually
in use was one.

    https://console.groq.com/docs/models
    https://console.groq.com/docs/vision
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.utils.groqmodels import CAPABILITIES, can, capabilities, check_configured, classify

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


print("== the models that read images ==")
# The whole reason this file exists: neither id contains a vision-ish word.
for model in ("qwen/qwen3.6-27b", "qwen/qwen3.8-27b"):
    check(f"{model} is known to read images", can(model, "vision"))
    check(f"{model} can still write replies too", can(model, "chat"))
    check(f"{model} has no vision hint in its name",
          "vision" not in model and "-vl" not in model)

for model in ("meta-llama/llama-4-scout-17b-16e-instruct",
              "meta-llama/llama-4-maverick-17b-128e-instruct"):
    check(f"{model.split('/')[-1]} reads images", can(model, "vision"))

print()
print("== and the ones that do not ==")
for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile",
              "allam-2-7b", "groq/compound"):
    check(f"{model} is text only", not can(model, "vision") and can(model, "chat"))

print()
print("== speech in, speech out, and neither is a chat model ==")
for model in ("whisper-large-v3", "whisper-large-v3-turbo"):
    check(f"{model} transcribes", can(model, "stt"))
    check(f"{model} is not offered for replies", not can(model, "chat"))
for model in ("canopylabs/orpheus-v1-english", "canopylabs/orpheus-arabic-saudi"):
    check(f"{model.split('/')[-1]} speaks", can(model, "tts"))
    check(f"{model.split('/')[-1]} is not offered for replies", not can(model, "chat"))

print()
print("== safety classifiers are not conversation models ==")
for model in ("meta-llama/llama-prompt-guard-2-22m", "openai/gpt-oss-safeguard-20b"):
    check(f"{model.split('/')[-1]} is moderation only",
          can(model, "moderation") and not can(model, "chat"))

print()
print("== a model Groq adds tomorrow ==")
# The table cannot keep up with releases, so an unknown id has to land
# somewhere sensible rather than vanishing from every picker.
check("an unknown id is assumed to chat", can("brand-new-model-9b", "chat"))
check("a vl name is read as vision", can("someone/new-vl-8b", "vision"))
check("a whisper name is read as speech", can("distil-whisper-large", "stt"))
check("a tts name is read as speech out", can("labs/new-tts-voice", "tts"))
check("a guard name is read as moderation", can("org/new-guard-1b", "moderation"))
check("an unknown id is never silently multi-purpose",
      capabilities("brand-new-model-9b") == {"chat"})

print()
print("== one word for grouping a list ==")
check("a multimodal model groups under vision", classify("qwen/qwen3.6-27b") == "vision")
check("speech groups under audio", classify("whisper-large-v3") == "audio")
check("a plain model groups under chat", classify("openai/gpt-oss-120b") == "chat")

print()
print("== the wrong sort of model is reported ==")
# check_configured needs the live list, which needs a key. Stub it so the test
# is about the matching, not about the network.
import app.utils.groqmodels as gm
gm._cache.update(at=9e18, error="", models=[
    {"id": mid, "kind": classify(mid), "capabilities": sorted(caps), "active": True}
    for mid, caps in CAPABILITIES.items()
])

good = {"bot": {
    "groq_models": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"],
    "groq_small_model": "openai/gpt-oss-20b",
    "groq_image_model": "qwen/qwen3.6-27b",
    "groq_whisper_model": "whisper-large-v3-turbo",
    "groq_tts_model": "canopylabs/orpheus-v1-english",
}}
check("a correct setup reports nothing", check_configured(good) == [], str(check_configured(good)))

bad = {"bot": {
    "groq_models": ["whisper-large-v3"],
    "groq_image_model": "openai/gpt-oss-120b",
    "groq_whisper_model": "canopylabs/orpheus-v1-english",
    "groq_tts_model": "openai/gpt-oss-20b",
}}
problems = {p["key"]: p for p in check_configured(bad)}
check("a speech model cannot write replies",
      problems.get("groq_models", {}).get("needs") == "chat", str(problems))
check("a text model cannot describe pictures",
      problems.get("groq_image_model", {}).get("needs") == "vision", str(problems))
check("a voice model cannot transcribe",
      problems.get("groq_whisper_model", {}).get("needs") == "stt", str(problems))
check("a text model cannot speak",
      problems.get("groq_tts_model", {}).get("needs") == "tts", str(problems))
check("all four are reported as the wrong sort",
      all(p["reason"] == "wrong_kind" for p in problems.values()), str(problems))

# Not being able to reach Groq must not turn into four accusations.
saved = list(gm._cache["models"])
gm._cache.update(models=[])
try:
    check("no list means no accusation", check_configured(bad) == [])
finally:
    gm._cache.update(models=saved)

print()
print("== every setting the panel offers a picker for is covered ==")
settings = ("groq_models", "groq_small_model", "groq_image_model",
            "groq_whisper_model", "groq_tts_model")
covered = {p["key"] for p in check_configured({"bot": {
    "groq_models": ["whisper-large-v3"],
    "groq_small_model": "whisper-large-v3",
    "groq_image_model": "whisper-large-v3",
    "groq_whisper_model": "openai/gpt-oss-20b",
    "groq_tts_model": "openai/gpt-oss-20b",
}})}
for key in settings:
    check(f"{key} is checked", key in covered, str(covered))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
