"""Persona profiles: who the bot is, account by account (app/utils/personas.py).

Three layers: everyone's settings (config.yaml), each persona's own changes to them, and which persona each account
is. Checked here on a sandbox: making one fresh or as a copy, its text and settings, giving it to accounts and
following them when one is removed, deleting it, and which persona a runner works as (and so which settings, text,
pictures and memory it uses).
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fixtures import use_shipped_config  # noqa: E402

SANDBOX = use_shipped_config()
from app.utils import configstore, db, helpers, memory, personas  # noqa: E402

db.resource_path = helpers.resource_path
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


db.init_db()
personas.startup()

print("== ids ==")
check("a name becomes a plain id", personas.slug("Juniper 🌙") == "juniper" and personas.slug("Zoé Lune") == "zoe-lune")
check("never one already used, nor a reserved word", personas.slug("Default") == "default-2"
      and personas.slug("x", taken=["x"]) == "x-2")
check("only plain ids are taken as paths", not personas.valid_id("../x") and not personas.valid_id("A")
      and personas.valid_id("juniper-2"))
try:
    personas.folder("../../Windows")
    check("a path cannot be smuggled in as an id", False)
except ValueError:
    check("a path cannot be smuggled in as an id", True)

print("\n== Default, as it always was ==")
check("Default is there with no setup, its text and pictures where they always were",
      personas.ids() == ["default"] and personas.instructions_path("default") == SANDBOX / "config" / "instructions.txt"
      and personas.pictures_dir("default") == SANDBOX / "config" / "pictures")
check("named after the name in its text when it has none of its own, else Default",
      personas.get("default")["name"] in ("Default",) or personas.get("default")["name"])

print("\n== a fresh one ==")
j = personas.create("Juniper")
check("made with an id, a name and a colour of its own", j["id"] == "juniper" and j["name"] == "Juniper"
      and j["color"].startswith("#") and j["color"] != "")
text = personas.read_text("juniper")
check("its text is the template with its name in", "Your name is Juniper" in text and "[NAME]" not in text)
check("it answers to its own name in a group, not to Default's", personas.overrides("juniper") == {"bot.trigger": "Juniper"})
check("its pictures folder is its own", personas.pictures_dir("juniper") == SANDBOX / "config" / "personas" / "juniper" / "pictures"
      and personas.pictures_dir("juniper").is_dir())
check("a second colour is not the first's", personas.create("Nova")["color"] != j["color"])

print("\n== its settings, on everyone's ==")
base = helpers.load_base_config()
configstore.set_value("bot.default_language", "fr", "juniper")
configstore.set_value("bot.mood.enabled", base["bot"]["mood"]["enabled"], "juniper")
check("its own value is kept, one the same as everyone's is not", personas.overrides("juniper") ==
      {"bot.trigger": "Juniper", "bot.default_language": "fr"}, str(personas.overrides("juniper")))
eff = configstore.effective("juniper")
check("its settings are everyone's with its own on top", eff["bot"]["default_language"] == "fr"
      and eff["bot"]["prefix"] == base["bot"]["prefix"] and helpers.load_base_config()["bot"]["default_language"] == "en")
check("and everyone's are left as they were", helpers.load_base_config()["bot"].get("default_language") == base["bot"]["default_language"])
where = configstore.set_value("services.webui.port", 8787, "juniper")
check("what is the app's (what runs, the model server, who commands it) goes to everyone's", where == "base"
      and "services.webui.port" not in personas.overrides("juniper"))
check("those are told apart", personas.is_global_only("bot.local.base_url") and personas.is_global_only("notifications.error_webhook")
      and not personas.is_global_only("bot.local.model") and not personas.is_global_only("bot.models"))
configstore.set_value("bot.local", {"model": "small", "base_url": "http://x:1/v1"}, "juniper")
check("a value holding app-wide ones is split, and they are left out",
      personas.overrides("juniper").get("bot.local.model") == "small" and "bot.local.base_url" not in personas.overrides("juniper"))
configstore.reset("bot.local", "juniper")
check("going back to everyone's for a setting", "bot.local.model" not in personas.overrides("juniper"))
check("overridden says so for the key, inside it, or around it", personas.overridden("juniper", "bot.default_language")
      and personas.overridden("juniper", "bot") and not personas.overridden("juniper", "bot.prefix"))

print("\n== which persona a runner is ==")
os.environ.pop("LLMSELFBOT_ACCOUNT", None)
check("the panel is no account, and reads everyone's", personas.current() is None
      and helpers.load_config()["bot"]["default_language"] == base["bot"]["default_language"])
personas.assign("discord_2", "juniper")
os.environ["LLMSELFBOT_ACCOUNT"] = "discord_2"
personas._pinned.clear()
check("an account's runner is its persona, and reads its settings", personas.current() == "juniper"
      and helpers.load_config()["bot"]["default_language"] == "fr")
check("and its text", helpers.load_instructions().startswith(personas.read_text("juniper")[:40]))
memory.set_memory(42, "name", "Mara")
check("and remembers people as itself", memory.get_memory(42, persona="juniper") == {"name": "Mara"}
      and memory.get_memory(42, persona="default") == {})
personas.assign("discord_2", "nova")
check("pinned for as long as it runs: a new persona takes effect on its restart", personas.current() == "juniper")
os.environ["LLMSELFBOT_ACCOUNT"] = "snapchat_1"
check("an account named nowhere is Default", personas.current() == "default")
from app.core import inprocess  # noqa: E402
role = types.SimpleNamespace(role="discord", account=2)
token = inprocess._current.set(role)
os.environ.pop("LLMSELFBOT_ACCOUNT", None)
check("on a phone, where accounts are threads, the thread's account decides", personas.current_account() == "discord_2"
      and personas.current() == "nova")
inprocess._current.reset(token)
with personas.scope("juniper"):
    check("the panel can work as a persona for a moment", personas.current() == "juniper"
          and helpers.load_config()["bot"]["default_language"] == "fr")
check("and is no persona again after", personas.current() is None)
personas.assign("discord_2", "juniper")

print("\n== accounts come and go ==")
personas.assign("discord_3", "nova")
personas.assign("snapchat_2", "nova")
configstore.set_value("bot.pictures.touches.accounts", ["discord_1", "discord_3", "snapchat_2"], "nova")
personas.renumber("discord", 2)
check("the removed account's entry goes, the ones after move up", personas.assignments() == {"discord_2": "nova", "snapchat_2": "nova"},
      str(personas.assignments()))
check("so do the accounts a persona lets the AI add touches on",
      personas.overrides("nova")["bot.pictures.touches.accounts"] == ["discord_1", "discord_2", "snapchat_2"])
check("a list of ids renumbered", personas.renumber_ids(["discord_1", "discord_2", "discord_3", "snapchat_1"], "discord", 1)
      == ["discord_1", "discord_2", "snapchat_1"])
try:
    personas.assign("../x", "nova")
    check("only accounts can be given a persona", False)
except ValueError:
    check("only accounts can be given a persona", True)

print("\n== a copy ==")
(personas.pictures_dir("juniper") / "IMG_1.jpg").write_bytes(b"jpg")
db.add_picture_description("IMG_1.jpg", "by the lake", persona="juniper")
c = personas.create("June", copy_from="juniper", copy_memory=True)
check("a copy has its text, settings and pictures", personas.read_text(c["id"]) == personas.read_text("juniper")
      and personas.overrides(c["id"]) == personas.overrides("juniper")
      and (personas.pictures_dir(c["id"]) / "IMG_1.jpg").read_bytes() == b"jpg"
      and db.get_all_picture_descriptions(c["id"]) == {"IMG_1.jpg": "by the lake"})
check("and what it remembers, when asked for", memory.get_memory(42, persona=c["id"]) == {"name": "Mara"})
c2 = personas.create("Blank memory", copy_from="juniper")
check("not unless asked: a copy is a new person to everyone it meets", memory.get_memory(42, persona=c2["id"]) == {})

print("\n== changed, and deleted ==")
personas.update("juniper", name="  Juniper   Moon ", color="#22d3ee")
check("renamed, recoloured, its id kept", personas.get("juniper")["name"] == "Juniper Moon"
      and personas.get("juniper")["color"] == "#22d3ee" and personas.exists("juniper"))
personas.update("juniper", color="red")
check("a colour that is not one is none (the theme's)", personas.get("juniper")["color"] == "")
personas.assign("discord_1", "juniper")
moved = personas.delete("juniper")
check("deleted: its accounts are Default's again, the others' left as they are",
      moved == ["discord_1"] and personas.persona_of("discord_1") == "default" and personas.persona_of("discord_2") == "nova",
      f"{moved} {personas.assignments()}")
check("its folder and rows are gone", not (SANDBOX / "config" / "personas" / "juniper").exists()
      and memory.get_memory(42, persona="juniper") == {} and db.get_all_picture_descriptions("juniper") == {})
check("nothing of it left half deleted", not list((SANDBOX / "config" / "personas").glob(".trash-*")))
try:
    personas.delete("default")
    check("Default cannot be deleted", False)
except ValueError:
    check("Default cannot be deleted", True)

print("\n== where a picture is from ==")
check("a picture in a persona's folder is that persona's", personas.persona_of_path(personas.pictures_dir("nova") / "IMG_1.jpg") == "nova")
check("one in the old folder is Default's", personas.persona_of_path(SANDBOX / "config" / "pictures" / "IMG_1.jpg") == "default")
check("a line for who it is, past the headings and the blanks to fill in",
      personas.vibe("# PERSONA\nYour name is [NAME].\n[note\nstill note]\nShe **loves** the sea.\n") == "She loves the sea.")
check("a blank with a hint in it is still a blank",
      personas.vibe("Your hobbies: [HOBBIES - games, music, sports, shows...].\nPeople: [FRIENDS / PETS, first names only]."
                    "\nShe loves the sea.") == "She loves the sea.")
_template = (ROOT / "resources" / "instructions.txt").read_text(encoding="utf-8")
check("one just made from the template says nothing yet, whatever its name",
      personas.vibe(_template.replace("[NAME]", "Ivy")) == "")
check("and once its first blanks are filled in, that is who it is",
      personas.vibe(_template.replace("[NAME]", "Ivy").replace("Your name is Ivy and you are [AGE] years old, [GENDER].",
                                                                "Your name is Ivy and you are 22.")) == "Your name is Ivy and you are 22.")
name_of = personas._name_from_text
check("a name from \"Your name is\", or from \"You are\" as a text opens",
      name_of("Your name is Juniper and you are 19.") == "Juniper" and name_of("You are Alicia. You feel everything.") == "Alicia"
      and name_of("you are Élodie, 20.") == "Élodie")
check("never a word that is not a name, nor a blank",
      name_of("You are NOT an AI. You are a student.") == "" and name_of(_template) == ""
      and name_of("You are NOT a bot. You are Kit.") == "Kit")

print("\n== an old per-account setup ==")
(SANDBOX / "config" / "instructions_3.txt").write_text("Your name is Kit. Short replies.", encoding="utf-8")
configstore.set_value("bot.per_account_persona", True)
made = personas.migrate_legacy()
check("each per-account file is a persona of its own, given to its account", len(made) == 1
      and personas.persona_of("discord_3") == made[0] and personas.read_text(made[0]).startswith("Your name is Kit"))
check("and the old switch is off", helpers.load_base_config()["bot"]["per_account_persona"] is False)
check("brought over once", personas.migrate_legacy() == [])

os.environ.pop("LLMSELFBOT_ACCOUNT", None)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
