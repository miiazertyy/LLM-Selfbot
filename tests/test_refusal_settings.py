"""The refusal catcher, editable from Settings.

A reply where the model refuses, or says it is an AI, is never sent: it gives
the account away in one line. One of the fallbacks goes instead. The wording it
catches, what it sends back, and whether it runs at all are settings now, so a
phrase a particular model keeps saying can be added without touching the code.
The regex patterns stay in the code on purpose: a bad one typed into Settings
would swallow real replies.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="refusal_test_"))
(SANDBOX / "config").mkdir(parents=True)
CFG = SANDBOX / "config" / "config.yaml"
shutil.copy(ROOT / "resources" / "config.yaml", CFG)

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
import app.utils.helpers as helpers
helpers.resource_path = lambda rel: str(SANDBOX / rel)
helpers.invalidate_config_cache()

from app.core import engine

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def write(**over):
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    cfg["bot"].setdefault("refusal", {}).update(over)
    CFG.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    helpers.invalidate_config_cache()


print("== it still catches what it always caught ==")
check("an assistant refusal", engine.is_refusal("I'm sorry, I can't help with that."))
check("a claim to be an AI", engine.is_refusal("I am just a program"))
check("the French wording too", engine.is_refusal("je ne suis pas humain"))
check("and a normal reply goes through", not engine.is_refusal("lol yeah sounds good"))
check("including one that only looks like a refusal", not engine.is_refusal("sorry i can't wait to see you"))

print("\n== however the apostrophes are written ==")
check("a refusal in curly quotes, the way models often write it",
      engine.is_refusal("I\u2019m sorry, but I can\u2019t help with that."))
check("an AI claim in curly quotes", engine.is_refusal("As an AI, I don\u2019t have feelings"))
check("the same normal reply still goes through", not engine.is_refusal("sorry i can\u2019t wait to see you"))

print("\n== the settings are in config.yaml ==")
block = (helpers.load_config().get("bot") or {}).get("refusal") or {}
check("with every part of it", set(block) >= {"enabled", "fallbacks", "extra_phrases", "replace_phrases"}, str(block))
check("on by default", block.get("enabled") is True)
check("and the built-in replies", engine.refusal_fallbacks() == ["wtf", "??"], str(engine.refusal_fallbacks()))

print("\n== a phrase added in Settings ==")
before = len(engine.refusal_phrases())
write(extra_phrases=["that's not something i can do"])
check("counts as a refusal", engine.is_refusal("hmm, that's not something i can do"))
check("however it is capitalised or spaced", engine.is_refusal("Hmm,  That's Not  Something I Can Do."))
check("or which apostrophe the reply uses", engine.is_refusal("that\u2019s not something i can do"))
write(extra_phrases=["that\u2019s not something i can do"])
check("or the phrase was typed with", engine.is_refusal("that's not something i can do"))
write(extra_phrases=["that's not something i can do"])
check("and is added to the built-in list, not instead of it",
      len(engine.refusal_phrases()) == before + 1 and engine.is_refusal("I am just a program"))

print("\n== or used on its own ==")
write(replace_phrases=True)
check("only the added phrases count", engine.is_refusal("that's not something i can do")
      and not engine.is_refusal("I am just a program"), str(len(engine.refusal_phrases())))
check("the patterns in the code still run, so the obvious wording is never missed",
      engine.is_refusal("I'm sorry, I can't help with that."))
write(replace_phrases=False, extra_phrases=[])

print("\n== what it sends instead ==")
write(fallbacks=["huh??", "bruh"])
check("is what was typed in", engine.refusal_fallbacks() == ["huh??", "bruh"], str(engine.refusal_fallbacks()))
write(fallbacks=[])
check("and an empty list falls back to the built-in pair, never silence",
      engine.refusal_fallbacks() == ["wtf", "??"], str(engine.refusal_fallbacks()))
write(fallbacks=["  ", ""])
check("blank entries are ignored the same way", engine.refusal_fallbacks() == ["wtf", "??"])
write(fallbacks=["wtf", "??"])

print("\n== turning it off ==")
write(enabled=False)
check("lets a refusal through as it is", not engine.is_refusal("I'm sorry, I can't help with that."))
write(enabled=True)
check("and turning it back on catches it again", engine.is_refusal("I'm sorry, I can't help with that."))

print("\n== it takes effect without a restart ==")
src = (ROOT / "app" / "core" / "engine.py").read_text(encoding="utf-8")
check("the settings are read when a reply is checked, not once at import",
      "def _refusal_cfg" in src and "load_config()" in src.split("def _refusal_cfg")[1][:700])

print("\n== every place that answers a refusal uses the edited list ==")
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
general = (ROOT / "app" / "cogs" / "general.py").read_text(encoding="utf-8")
check("the Discord runner", "refusal_fallbacks()" in runner and "REFUSAL_FALLBACKS" not in runner)
check("the engine", "random.choice(refusal_fallbacks())" in src)
check("and the command cog", "refusal_fallbacks()" in general and "REFUSAL_FALLBACKS" not in general)

print("\n== and they are in Settings ==")
sys.path.insert(0, str(ROOT))
from app.web.schema import CONFIG_SCHEMA
keys = {f["key"] for f in CONFIG_SCHEMA}
for k in ("bot.refusal.enabled", "bot.refusal.fallbacks", "bot.refusal.extra_phrases", "bot.refusal.replace_phrases"):
    check(f"{k} has a control", k in keys)
check("each with a default, so a config written before this still shows them",
      all("default" in f for f in CONFIG_SCHEMA if f["key"].startswith("bot.refusal.")))
from app.web import descriptions as desc
check("and each says what it does",
      all(desc.DESCRIPTIONS.get(k) for k in keys if k.startswith("bot.refusal.")))
smap = (ROOT / "webui" / "src" / "lib" / "settingsmap.ts").read_text(encoding="utf-8")
check("they have their own subtab, not lost in 'Everything else'",
      '"bot.refusal.enabled"' in smap and 'name: "Refusals"' in smap)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
