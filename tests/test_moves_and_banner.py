"""Things moved to where they belong, and the account card wears its banner.

  * Discord → Tokens and Snapchat → Logins were the Accounts page a second
    time. They are gone from Settings; everything that pointed there now points
    at Accounts, and the raw values are still under App, All variables.
  * The trigger words are the persona's names, so they are edited on the
    Persona page. Clearing them no longer makes an empty word that matched
    every message.
  * Every row in Chats has the X to ignore someone, the Answered history too.
  * The account card's top is the account's own Discord banner, or the colour
    it picked instead of one.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WEB = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


print("== logins live on the Accounts page ==")
smap = read("webui/src/lib/settingsmap.ts")
check("Settings has no Discord Tokens subtab", 'id: "tokens"' not in smap and 'name: "Tokens"' not in smap)
check("nor a Snapchat Logins one", 'id: "logins"' not in smap and 'name: "Logins"' not in smap)
check("and nothing points at either", "discord/tokens" not in smap and "snapchat/logins" not in smap)
check("the raw values still have a page", 'id: "env"' in smap and "extras: true" in smap)
settings = read("webui/src/pages/Settings.svelte")
check("Discord and Snapchat say where logins went", 'class="settings-pointer" href="#/accounts"' in settings)
system = read("app/web/routes/system_routes.py")
doctor = system[system.index('add("token", "Discord token"'):]
doctor = doctor[:doctor.index("return {")]
check("the doctor sends a missing token to Accounts", '"route": "accounts"' in doctor and "Tokens" not in doctor, doctor)

search = read("webui/src/lib/search.ts")
m = re.search(r"const ACCOUNT_KEY = /(.+)/;", search)
rx = re.compile(m.group(1).replace("\\\\", "\\")) if m else None
check("searching a login finds it on Accounts",
      rx is not None and all(rx.match(k) for k in ("DISCORD_TOKEN_1", "DISCORD_PROXY_2", "SNAP_USERNAME", "SNAP_PASSWORD_3"))
      and not any(rx.match(k) for k in ("GROQ_API_KEY_1", "TELEGRAM_BOT_TOKEN", "DISCORD_TOKENS")))
check("other secrets open the page that lists them", 'section: "app/env"' in search)
check("and a search hit can say where in Settings to land",
      "if (h.section) settingsSection.set(h.section);" in read("webui/src/lib/components/CommandPalette.svelte"))
check("the Accounts page answers to token, proxy and login", re.search(r'accounts: "[^"]*\btoken\b[^"]*\bproxy\b[^"]*\blogin\b', search))

print("\n== the names it answers to ==")
from app.web import descriptions as desc
check("the trigger words are not in Settings any more", desc.is_hidden("bot.trigger"))
check("nor listed in its tree", '"bot.trigger"' not in smap)
check("the subtab they left is just Commands", 'name: "Commands"' in smap)
persona = read("webui/src/pages/Persona.svelte")
check("they are on the Persona page", "<TriggerEditor />" in persona and "Names it answers to" in persona)
editor = read("webui/src/lib/components/TriggerEditor.svelte")
check("saved as the same comma list the runner reads",
      'api.configField("bot.trigger", value, { persona })' in editor and 'names.join(", ")' in editor)
check("each name once, whatever its case", "x.toLowerCase() === n.toLowerCase()" in editor)

runner = read("app/platforms/discord_runner.py")
start, end = runner.index("def _trigger_words("), runner.index("TRIGGER_RE = _compile_triggers(TRIGGER)")
ns = {"re": re, "config": {"bot": {"trigger": ""}}}
exec(compile(runner[start:end], "triggers", "exec"), ns)
words, comp = ns["_trigger_words"], ns["_compile_triggers"]
check("names match exactly as before", words("Alicia, Ali, Alycia") == ["alicia", " ali", " alycia"])
check("no names means nothing triggers", comp(words("")) is None and comp(words(None)) is None)
check("and a trailing comma is not a word that matches everything",
      not comp(words("John, Jon,")).search("hey whats up") and comp(words("John, Jon,")).search("yo john"))
check("both places the runner reads them use it", runner.count("_trigger_words(") >= 3)

print("\n== the X on every row in Chats ==")
chats = read("webui/src/pages/Chats.svelte")
live = chats[chats.index('<div class="ch-item-wrap" class:is-bad'):]
live = live[:live.index("{/each}")]
check("every live row has it, not only a failed reply", 'class="ch-x"' in live and 's.phase === "needs"' not in live)
past = chats[chats.index("{#each shownArchived as c (c.id)}"):]
past = past[:past.index("{/each}")]
check("the Answered history has it too", 'class="ch-x" onclick={(e) => ignorePerson(c, e)}' in past)
check("and someone ignored leaves the history", "!ignoredIds.has(c.id)" in chats)
check("where the X always shows, the time moves over", ".ch-item-wrap.is-bad .ch-item-top { padding-right: 24px; }" in chats)

print("\n== the account card's banner ==")
start = runner.index("_banner = getattr(bot.user")
ident = runner[start:runner.index("_idpath", start)]
check("the runner records the banner and the colour", '"banner":' in ident and '"accent":' in ident)
check("from what Discord sent at login, with no extra request", "fetch_user" not in ident and "profile(" not in ident)

import app.utils.paths as paths
tmp = Path(tempfile.mkdtemp(prefix="llmbot_banner_"))
(tmp / "config").mkdir()
paths.DATA_DIR = tmp
from app.web.routes import status_routes


def ident_of(data):
    (tmp / "config" / "identity_1.json").write_text(json.dumps(data), encoding="utf-8")
    return status_routes._identity("discord", 1)


got = ident_of({"username": "a", "banner": "https://cdn.discordapp.com/banners/1/abc.png?size=600", "accent": "#E91E63"})
check("a real banner and colour reach the card", got["banner"].startswith("https://cdn.discordapp.com/banners/")
      and got["accent"] == "#e91e63", str(got))
got = ident_of({"banner": "https://evil.example/x.png", "accent": "red; background: url(https://evil.example)"})
check("anything else does not", got["banner"] == "" and got["accent"] == "", str(got))
got = ident_of({"banner": 'https://cdn.discordapp.com/banners/1/a.png" onerror="x', "accent": "#12345"})
check("not even from Discord's address with a quote in it, or a colour one digit short",
      got["banner"] == "" and got["accent"] == "", str(got))
check("an account from before has neither", ident_of({"username": "a"}) | {} == {"username": "a", "display_name": "",
                                                                                 "user_id": "", "avatar": "", "banner": "",
                                                                                 "accent": ""})
shutil.rmtree(tmp, ignore_errors=True)

card = read("webui/src/lib/accounts/AccountCard.svelte")
check("the card shows the banner", "{#if rt?.banner}" in card and 'class="acct-banner-img is-banner"' in card)
check("or a blur of the colour", "{:else if rt?.accent}" in card and "--acct-colour: ${rt.accent}" in card)
check("and otherwise its picture, as before", "{:else if rt?.avatar}" in card)
check("a stopped account's banner drains of colour too", ".acct.is-down .acct-banner-img.is-banner" in card
      and ".acct.is-down .acct-banner-colour" in card)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
