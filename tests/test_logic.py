import sys, re, random
sys.path.insert(0, r"c:/Users/miiaz/Downloads/LLM-coolprivatebot")

from app.utils.split_response import split_response
from app.utils.humanize import strip_meta, strip_ai_tells, add_typo, humanize
from app.utils.tts import _chunk_text, _clean_text_for_tts, TTS_MAX_CHARS
from app.utils.tts_trigger import is_tts_request
from app.utils.pictures import is_picture_request
from app.utils.helpers import france_time_str, load_config
from app.core.engine import is_refusal

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))

print("\n== split_response ==")
for text in ["short", "a\nb\nc", "x" * 5000, ("word " * 900).strip(),
             "https://example.com/" + "a" * 3000, "line\n" + "y" * 2500 + "\ntail", "", "\n\n\n"]:
    chunks = split_response(text)
    check(f"chunks <= 1900 ({text[:12]!r})", all(len(c) <= 1900 for c in chunks),
          str([len(c) for c in chunks]))
    check(f"no empty chunks ({text[:12]!r})", all(c.strip() for c in chunks))
joined = "".join(split_response("x" * 5000))
check("hard split preserves all chars", joined == "x" * 5000, f"{len(joined)}")
words = ("alpha beta gamma " * 400).strip()
check("word split keeps every word",
      " ".join(" ".join(split_response(words)).split()) == words)

# A line break is a message boundary. The persona is told to break a longer
# answer into "2-3 short separate messages, one after another like a real
# person would"; the model does that with a newline, and this used to glue them
# back into one message with a gap in the middle.
two = "haha guess i'm just naturally fun 😂 you in school?\n\ni'm broke as hell"
check("a blank line makes two messages", len(split_response(two)) == 2,
      str(split_response(two)))
check("neither message keeps a newline",
      all("\n" not in c for c in split_response(two)))
check("a single newline splits too", len(split_response("first\nsecond")) == 2,
      str(split_response("first\nsecond")))
check("one line stays one message", len(split_response("just the one")) == 1)
check("blank lines alone send nothing", split_response("\n \n\n") == [])

print("\n== humanize ==")
check("strip em dash", strip_ai_tells("a \u2014 b \u2013 c") == "a  b  c")
check("strip meta line", strip_meta("hey there\n(translation: salut)") == "hey there")
check("strip inline translation", strip_meta("salut (translation: hi)").strip() == "salut")
check("meta-only text falls back", strip_meta("(translation: hi)") != "")
check("strip_meta keeps normal text", strip_meta("just a normal reply") == "just a normal reply")
random.seed(7)
# A "swap" of two identical adjacent letters (the "ll" in hello) is a no-op,
# so allow a few unchanged results.
typo_changed = sum(add_typo("hello there friend", 1.0) != "hello there friend" for _ in range(200))
check("typo fires at chance=1.0", typo_changed >= 180, f"{typo_changed}/200")
check("typo never fires at 0.0", all(add_typo("hello there friend", 0.0) == "hello there friend" for _ in range(50)))
check("typo keeps word count", all(len(add_typo("hello there friend", 1.0).split()) == 3 for _ in range(200)))
check("typo safe on short text", add_typo("hi", 1.0) == "hi")
check("humanize composes", " - " not in humanize("a, b", 0.0))

print("\n== tts chunking ==")
for n in (50, 200, 1000, 5000):
    body = "This is a sentence. " * (n // 20 + 1)
    for limit in (40, 90, TTS_MAX_CHARS):
        cs = _chunk_text(body, limit)
        check(f"tts chunks <= {limit} (len {len(body)})", all(len(c) <= limit for c in cs),
              str(max(len(c) for c in cs)))
check("tts single chunk when short", _chunk_text("hi there", 180) == ["hi there"])
check("tts strips urls/emoji", "http" not in _clean_text_for_tts("look https://x.com 😀 ok"))
check("tts strips mentions", "<@" not in _clean_text_for_tts("hey <@123456> yo"))

print("\n== triggers ==")
check("tts trigger positive", is_tts_request("can i hear your voice"))
check("tts trigger negative", not is_tts_request("what's for dinner"))
check("pic request en", is_picture_request("send me a pic"))
check("pic request fr", is_picture_request("envoie une photo stp"))
check("pic request negative", not is_picture_request("i went to the beach yesterday"))
check("pic request negative 2", not is_picture_request("what time is it"))

print("\n== refusals ==")
check("refusal detected", is_refusal("I'm sorry, but I can't help with that"))
check("refusal case-insensitive", is_refusal("AS AN AI language model..."))
check("normal reply not refusal", not is_refusal("yeah sure lol what's up"))

print("\n== helpers ==")
t = france_time_str()
check("france time formatted", bool(re.fullmatch(r"\w+ \d{2} \w+ \d{4}, \d{2}:\d{2}", t)), t)
check("config cached identity", load_config() is load_config())
check("config has bot section", "bot" in load_config() and "groq_models" in load_config()["bot"])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
