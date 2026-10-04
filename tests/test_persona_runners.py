"""Each running account speaks as its persona, and nothing writes one persona's settings into everyone's.

  * a runner knows which account it is before anything reads a setting (cli.py), so it reads its persona's
  * the engine reads its settings as it works, not once at import, when they could be another account's
  * a change pushed to a runner makes it read its own settings again: never the value in the message, which is
    everyone's or another persona's and would cover this persona's own
  * nothing loads the settings, changes one and writes the whole file back: what a runner loads is its persona's
    on everyone's, and writing that back put the persona's own values into everyone's config.yaml
  * Telegram, the Discord commands and the Snapchat bridge work on the account's persona's text and pictures
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (APP / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


cli = read("cli.py")
engine = read("core/engine.py")
runner = read("platforms/discord_runner.py")
bridge = read("platforms/snapchat_bridge.py")
cogs = read("cogs/management.py")
tg = read("telegram_bot/telegram_controller.py")
config_routes = read("web/routes/config_routes.py")
pics = read("utils/pictures.py")

print("== a runner is its account's persona from the start ==")
for role, platform, module in (("_run_discord_role", "discord", "from app.platforms import discord_runner"),
                               ("_run_snapchat_role", "snapchat", "from app.platforms.snapchat_bridge import run")):
    body = cli[cli.index(f"def {role}("):]
    body = body[: body.index("\ndef ", 1)]
    set_at = body.find(f'os.environ["LLMSELFBOT_ACCOUNT"] = f"{platform}_{{account}}"')
    check(f"{platform}: the account is known before the runner is imported",
          0 <= set_at < body.find(module), body[:200])
check("the engine reads its settings as it works", "def _bot_cfg() -> dict:" in engine
      and not re.search(r"^_MOOD_CFG\s*=", engine, re.M) and not re.search(r"^config\s*=\s*load_config\(\)", engine, re.M))

print("\n== a change pushed is read from the account's own settings ==")
handler = runner[runner.index('elif cmd == "config_update":'):]
handler = handler[: handler.index("elif cmd ==", 10)]
check("the Discord runner reads everything again", "refresh_config(bot)" in handler)
check("and never applies the value in the message", "payload" not in handler, handler[:300])
check("the panel pushes only which setting changed", 'live.push(request, "config_update", {"key": key}' in config_routes)
check("a memory edited in the panel is read again by the runners",
      'elif cmd == "memory_changed":' in runner and 'elif cmd == "memory_changed":' in bridge)
check("the Discord runner reads its persona's text on every reply", runner.count("load_instructions()") >= 3)

print("\n== nothing writes one persona's settings into everyone's ==")
writers = []
for f in APP.rglob("*.py"):
    rel = f.relative_to(APP).as_posix()
    if rel in ("utils/configstore.py", "utils/paths.py", "utils/setup.py", "utils/personas.py"):
        continue
    src = f.read_text(encoding="utf-8")
    # config.yaml opened to be written, or a dump into a handle on it.
    if re.search(r"""config\.yaml["']\)?\s*,\s*["']w""", src) or re.search(r"_CONFIG_YAML\s*,\s*[\"']w", src):
        writers.append(rel)
check("no module opens config.yaml to write it but the config store", not writers, ", ".join(writers))
check("the runner's switches and voice autojoin go through the store",
      runner.count("set_effective(") >= 5 and '_cs_aj.set_effective("bot.autojoin_channel", None)' in runner)
check("so do the Discord commands", "def save_config" not in cogs and cogs.count("configstore.set_effective(") >= 5)
check("Telegram's /config writes where the value comes from, for the selected account's persona",
      "configstore.set_effective(dotted, new_val, persona=pid)" in tg and "def _save_config" not in tg)
check("the Snapchat bridge has no writer of its own", "def _save_config" not in bridge)

print("\n== text and pictures are the account's persona's ==")
check("pictures are found in the persona's own folder", "def pictures_folder(persona=None) -> str:" in pics)
check("the Snapchat bridge sends from it", "img_folder = pictures_folder()" in bridge)
check("Telegram works on the selected account's persona's pictures and text",
      "def _pictures_dir():" in tg and "personas.pictures_dir(pid)" in tg and "personas.instructions_path(_selected_persona())" in tg)
check("and only names Default's folder, never uses it", tg.count("_PICTURES_DIR") == 1, str(tg.count("_PICTURES_DIR")))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
