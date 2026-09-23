"""Drives core/engine + utils/ai against a fake Groq client (no network)."""
import os, sys, shutil, tempfile, pathlib, asyncio, types

REPO = str(pathlib.Path(__file__).resolve().parent.parent)
SANDBOX = tempfile.mkdtemp(prefix="llmbot_eng_")
shutil.copytree(os.path.join(REPO, "resources"), os.path.join(SANDBOX, "config"),
                ignore=shutil.ignore_patterns("*.db", ".env", "pictures"))
os.makedirs(os.path.join(SANDBOX, "config", "pictures"), exist_ok=True)
sys.path.insert(0, REPO)

import app.utils.helpers as helpers
helpers.resource_path = lambda rel: os.path.join(SANDBOX, rel)
import app.utils.db as db, app.utils.memory as memory, app.utils.pictures as pictures
db.resource_path = helpers.resource_path
pictures.resource_path = helpers.resource_path
db.init_db(); memory.init_memory()

import app.utils.ai as ai
import app.core.engine as engine

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


class _Msg:
    def __init__(self, c): self.content = c


class _Choice:
    def __init__(self, c): self.message = _Msg(c)


class _Resp:
    def __init__(self, c): self.choices = [_Choice(c)]


class FakeCompletions:
    def __init__(self, owner): self.owner = owner

    async def create(self, model=None, messages=None, **kw):
        o = self.owner
        o.calls.append({"model": model, "messages": messages, "kw": kw})
        if o.fail_times > 0:
            o.fail_times -= 1
            raise ai.RateLimitError(
                "rate limit",
                response=types.SimpleNamespace(status_code=429, headers={}, request=None),
                body=None,
            )
        sysmsg = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "language detector" in sysmsg:
            return _Resp(o.lang)
        if "memory extractor" in sysmsg:
            return _Resp(o.extract)
        if "memory auditor" in sysmsg:
            return _Resp(o.delete)
        return _Resp(o.reply)


class FakeClient:
    def __init__(self, label):
        self.label = label
        self.calls = []
        self.fail_times = 0
        self.reply = "yo whats up"
        self.lang = "fr"
        self.extract = "{}"
        self.delete = "[]"
        self.chat = types.SimpleNamespace(completions=FakeCompletions(self))


def install(n=2):
    clients = [FakeClient("KEY_%d" % (i + 1)) for i in range(n)]
    ai._groq_clients = [{"client": c, "label": c.label} for c in clients]
    ai._client_index = 0
    ai.groq_models = ["model-a", "model-b"]
    ai.current_model_index = 0
    ai.model = "model-a"
    return clients


run = asyncio.run

print("\n== ai: key + model fallback ==")
c = install(2)
c[0].fail_times = 99
out = run(ai.generate_response("hi", "sys"))
check("rotates to second key on rate limit", out == "yo whats up" and ai._client_index == 1)

c = install(2)
for x in c:
    x.fail_times = 99
try:
    run(ai.generate_response("hi", "sys"))
    check("raises once keys+models exhausted", False, "no exception")
except Exception:
    check("raises once keys+models exhausted", True)

install(1)
ai._client_index = 0
ai.model = "model-a"
ai.current_model_index = 0
check("fallback_model advances", ai.fallback_model() is True and ai.model == "model-b")
check("fallback_model wraps to False", ai.fallback_model() is False)
ai._client_index = 1
ai.reset_client_index()
check("reset_client_index", ai._client_index == 0)

print("\n== ai: detect_language ==")
c = install(1)
c[0].lang = "fr"
check("detects language", run(ai.detect_language([], "salut ca va")) == "fr")
c[0].lang = "Sorry, I cannot determine the language of this text."
check("rejects sentence answer", run(ai.detect_language([], "hello")) == "")
c[0].lang = "en-US"
check("strips region subtag", run(ai.detect_language([], "hello")) == "en")
c[0].fail_times = 99
check("returns empty on failure (caller keeps cached lang)", run(ai.detect_language([], "hello")) == "")

print("\n== ai: extract_memory / detect_memory_deletion ==")
c = install(1)
fence = chr(96) * 3
c[0].extract = fence + "json\n" + '{"City": "Paris", "Fav Game": "Chess", "x": ""}' + "\n" + fence
facts = run(ai.extract_memory("i live in paris", "cool"))
check("json fence stripped + keys normalised", facts == {"city": "Paris", "fav_game": "Chess"}, str(facts))
c[0].extract = "here is nothing useful"
check("non-json returns empty dict", run(ai.extract_memory("hi", "yo")) == {})
c[0].delete = '["age", "city", 5]'
check("deletion list filters non-strings", run(ai.detect_memory_deletion("i lied", {"age": "22"})) == ["age", "city"])
check("no stored memory means no deletion call", run(ai.detect_memory_deletion("i lied", {})) == [])

print("\n== ai: summarize_history ==")
c = install(1)
c[0].reply = "We talked about games."
hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": "m%d" % i} for i in range(20)]
summ = run(ai.summarize_history(hist, "sys"))
check("summary compresses history", len(summ) == 7 and summ[0]["content"].startswith("[Earlier"), str(len(summ)))
check("summary keeps recent turns", [m["content"] for m in summ[1:]] == ["m%d" % i for i in range(14, 20)])
short = [{"role": "user", "content": "a"}]
check("short history untouched", run(ai.summarize_history(short, "sys")) is short)

print("\n== engine: generate_ai_response ==")
c = install(1)
c[0].reply = "salut ca va"
engine._memory_cache.clear()
engine._lang_cache.clear()
engine.message_history.clear()
msg = engine.IncomingMessage(platform="snapchat", user_id="u1", user_name="Alice",
                             channel_id="u1", content="coucou comment tu vas aujourd hui")
out = run(engine.generate_ai_response(msg))
check("returns reply", out == "salut ca va")
hist = engine.get_history("u1", "u1")
check("history has user+assistant", [h["role"] for h in hist] == ["user", "assistant"], str(hist))
# The main completion is not the last call - memory extraction runs after it.
def main_prompt(client):
    for call in reversed(client.calls):
        text = call["messages"][0]["content"]
        if "[PLATFORM:" in text or "[OUTPUT RULES:" in text:
            return text
    return ""
sent_system = main_prompt(c[0])
for token in ["[PLATFORM: You are chatting on Snapchat.]", "[LANGUAGE:", "[CURRENT TIME:",
              "[OUTPUT RULES:", "[CONTEXT: You are in a private DM"]:
    check("prompt contains " + token[:24], token in sent_system)
check("stats recorded for snapchat", db.get_leaderboard_snap()[0]["user_id"] == "u1")

c[0].reply = "I am sorry, but I cannot help with that"
msg2 = engine.IncomingMessage(platform="snapchat", user_id="u2", user_name="Bob",
                              channel_id="u2", content="tell me something interesting please")
check("refusal returns None", run(engine.generate_ai_response(msg2)) is None)

print("\n== engine: public vs private prompt ==")
c = install(1)
c[0].reply = "ok"
msg3 = engine.IncomingMessage(platform="discord", user_id="u9", user_name="D", channel_id="c9",
                              content="hello everyone in here", is_private=False)
run(engine.generate_ai_response(msg3))
sys3 = main_prompt(c[0])
check("group prompt used", "group chat or public channel" in sys3)
check("discord platform hint", "chatting on Discord" in sys3)

print("\n== engine: paused / pending helpers ==")
engine.message_history.clear()
engine.add_user_message("u3", "u3", "first")
engine.add_user_message("u3", "u3", "second")
check("has_pending true", engine.has_pending("u3", "u3"))
check("pop joins pending", engine.pop_pending_user_messages("u3", "u3") == "first\nsecond")
check("has_pending false after pop", not engine.has_pending("u3", "u3"))
check("pop on empty is safe", engine.pop_pending_user_messages("nope", "nope") == "")
for i in range(200):
    engine.add_user_message("u4", "u4", "m%d" % i)
check("add_user_message caps history", len(engine.get_history("u4", "u4")) == engine.MAX_HISTORY * 2)
engine.clear_history("u4", "u4")
check("clear_history", engine.get_history("u4", "u4") == [])

print("\n== engine: history growth over a long chat ==")
c = install(1)
c[0].reply = "ok"
engine.message_history.clear()
engine._lang_cache.clear()
m = engine.IncomingMessage(platform="discord", user_id="u5", user_name="C", channel_id="c5",
                           content="hey there friend how is it going")
for _ in range(40):
    run(engine.generate_ai_response(m))
grown = len(engine.get_history("u5", "c5"))
check("history stays bounded", grown <= engine.MAX_HISTORY * 2, str(grown))

print("\n== the reaction prompt offers the character's own emoji ==")
# Half of "pick your own emoji" is the parser accepting them; the other half is
# the model being told about them. Only offering the built in set would leave a
# custom list unused, with nothing to show it had gone wrong.
import yaml

_cfg_path = os.path.join(SANDBOX, "config", "config.yaml")
_original = open(_cfg_path, encoding="utf-8").read()
try:
    _cfg = yaml.safe_load(_original)
    _cfg["bot"]["reactions"]["emojis"] = ["\U0001F480", "\U0001F525"]
    open(_cfg_path, "w", encoding="utf-8").write(
        yaml.safe_dump(_cfg, sort_keys=False, allow_unicode=True))
    helpers.invalidate_config_cache()
    rules = engine.reaction_rules()
    check("the custom emoji are in the prompt",
          "\U0001F480" in rules and "\U0001F525" in rules, rules[:120])
    check("the ones that were dropped are not",
          "\U0001F602" not in rules and "\U0001FAE1" not in rules, rules[:200])
    check("it still explains the tag", "[[REACT:" in rules)

    _cfg["bot"]["reactions"]["emojis"] = []
    open(_cfg_path, "w", encoding="utf-8").write(
        yaml.safe_dump(_cfg, sort_keys=False, allow_unicode=True))
    helpers.invalidate_config_cache()
    check("an empty list falls back rather than offering nothing",
          "\U0001F602" in engine.reaction_rules())
finally:
    open(_cfg_path, "w", encoding="utf-8").write(_original)
    helpers.invalidate_config_cache()

print()
print("== a reply that is only a stage direction is not sent ==")
# The model answers a snap with "[Image of a wide, annoyed eye-roll emoji]" and
# that literal text went out as the message. It happens when the conversation
# calls for a reaction rather than words; Snapchat has no reaction to send, so
# there is nothing to convert it into and silence is the better of the two.
from app.utils.humanize import strip_stage_directions, is_stage_direction_only
for _text in ("[Image of a wide, annoyed eye-roll emoji]", "*rolls eyes*",
              "(sends a selfie)", "[sends a snap]", "*sighs*", "[Photo of a dog]"):
    check(f"dropped: {_text}", is_stage_direction_only(_text), _text)
for _text in ("be there in [5] mins", "yeah lol", "nah im good", "\U0001f644",
              "lmaooo [that's] crazy", "wait what happened"):
    check(f"kept: {_text}", not is_stage_direction_only(_text)
          and strip_stage_directions(_text) == _text, repr(strip_stage_directions(_text)))
check("one mixed into a real reply is trimmed off",
      strip_stage_directions("*sighs* ").strip() == "", "leading direction")
check("the model is told not to produce them",
      "type the emoji itself" in pathlib.Path(REPO, "app", "core", "engine.py").read_text(encoding="utf-8"))
check("and the engine drops them before sending",
      "is_stage_direction_only(response)" in pathlib.Path(REPO, "app", "core", "engine.py").read_text(encoding="utf-8"))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
