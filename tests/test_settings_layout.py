"""Where every setting lives, and that no page is pointless.

  * no subtab holds a single setting, and nothing is left for a catch-all
    "Everything else" on a fresh install
  * a setting sits with what it is about: the reply language with how it
    talks, Snapchat's browser timings with its browser, the WebUI's port with
    the switch that serves it
  * nothing is shown twice: the late reply openers are the Persona page's,
    the profile cards' switch the Stored profiles page's, and a platform's
    two switches are one
  * keys nothing reads any more are not shown at all
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


MAP = (ROOT / "webui" / "src" / "lib" / "settingsmap.ts").read_text(encoding="utf-8").replace("\r\n", "\n")
PAGE = (ROOT / "webui" / "src" / "pages" / "Settings.svelte").read_text(encoding="utf-8").replace("\r\n", "\n")

from fixtures import use_shipped_config  # noqa: E402
use_shipped_config()
from app.utils.helpers import load_config  # noqa: E402
from app.web.schema import CONFIG_SCHEMA  # noqa: E402
from app.web import descriptions as desc  # noqa: E402

cfg = load_config()
fields = [f["key"] for f in CONFIG_SCHEMA if not desc.is_hidden(f["key"])]
for key, _ in desc.walk(cfg):
    if key not in fields and not desc.is_hidden(key):
        fields.append(key)

tabs = {}
for tb in re.finditer(r'^\s{4}id: "([a-z-]+)",(.*?)(?=^\s{4}id: "[a-z-]+",|\Z)', MAP, re.M | re.S):
    subs = []
    for sb in re.finditer(r'(?:^\s{6,8}|\{ )id: "([a-z-]+)",\s*\n?\s*name: "([^"]+)"(.*?)(?=(?:^\s{6,8}|\{ )id: "|\Z)',
                          tb.group(2), re.M | re.S):
        body = sb.group(3)
        subs.append({"id": sb.group(1), "name": sb.group(2),
                     "keys": re.findall(r'"((?:bot|snapchat|services|notifications|discord)\.[a-z0-9_.]+)"', body),
                     "panel": 'panel: "' in body, "rest": "rest: true" in body})
    tabs[tb.group(1)] = subs
owns = {"discord": ["discord"], "snapchat": ["snapchat"], "ai": ["bot"], "app": ["services", "notifications"]}
listed = {k for subs in tabs.values() for s in subs for k in s["keys"]}

print("== no pointless pages ==")
leftover = {t: [k for k in fields if k not in listed and any(k == p or k.startswith(p + ".") for p in ps)]
            for t, ps in owns.items()}
check("a fresh install leaves nothing for any 'Everything else'", not any(leftover.values()), str(leftover))
partners = {"discord.enabled", "snapchat.enabled"}
thin = [f"{t}/{s['name']}" for t, subs in tabs.items() for s in subs
        if not s["panel"] and not s["rest"] and len([k for k in s["keys"] if k in fields and k not in partners]) < 2]
check("no page of settings holds just one", not thin, ", ".join(thin))
check("AI behaviour is eight pages, not ten", len([s for s in tabs["ai"] if not s["rest"]]) == 8,
      str([s["name"] for s in tabs["ai"]]))
check("Reply style and Human touches are one page", '"Reply style"' not in MAP and '"Human touches"' not in MAP
      and 'name: "How it talks"' in MAP)
check("Snapchat's single-switch Friends page is gone", 'name: "Friends"' not in MAP)
check("and so is the two-setting WebUI page", 'id: "panel"' not in MAP)

print("\n== each setting where it belongs ==")
home = {k: (t, s["name"]) for t, subs in tabs.items() for s in subs for k in s["keys"]}
check("the reply language is with how it talks, not Discord's fingerprint", home.get("bot.default_language") == ("ai", "How it talks"))
check("Snapchat's browser timings are with its browser",
      home.get("snapchat.verify_wait_ms") == ("snapchat", "Browser") and home.get("snapchat.reload_interval_ms") == ("snapchat", "Browser"))
check("accepting Snapchat friends is with how it behaves", home.get("snapchat.auto_add_friends") == ("snapchat", "Behaviour"))
check("the WebUI's port and address are with the switch that serves it",
      home.get("services.webui.port") == ("app", "What runs") and home.get("services.webui.bind") == ("app", "What runs"))
check("Discord's message cache is with its client", home.get("bot.cache.max_messages") == ("discord", "Client"))
check("links made before still land: the old names resolve", '"webui": "app/services"' in MAP
      and "humanization: \"ai/style\"" in MAP)

print("\n== nothing twice, nothing dead ==")
check("the late reply openers and their tone are the Persona page's only",
      desc.is_hidden("bot.late_reply.openers.en") and desc.is_hidden("bot.late_reply.style"))
check("the old opener keys nothing reads are not shown",
      all(desc.is_hidden(k) for k in ("bot.late_reply.openers_en", "bot.late_reply.openers_fr", "bot.late_reply.french_indicators")))
check("the profile cards' switch belongs to its own page", home.get("bot.profile_cache.enabled") == ("app", "Stored profiles"))
check("a platform's two switches are drawn as one, which sets both",
      '"services.discord.enabled": "discord.enabled",' in PAGE and "if (partner) setValue(partner, v);" in PAGE
      and "list.filter((f) => !list.some((g) => BOTH[g.key] === f.key))" in PAGE)
check("and it says so plainly, without 'both have to be on'",
      "have to be on" not in (ROOT / "app" / "web" / "descriptions.py").read_text(encoding="utf-8"))
check("servers' own waits have a row even on a config without the key",
      any(f["key"] == "bot.server_batch_wait_times" and f.get("default") == [] for f in CONFIG_SCHEMA))

print("\n== a field as wide as what is in it ==")
AW = (ROOT / "webui" / "src" / "lib" / "autowidth.ts").read_text(encoding="utf-8")
CSS = (ROOT / "webui" / "src" / "app.css").read_text(encoding="utf-8")
check("text fields hug their words, up to what the row gives them",
      'class="field max-w-full text-[13px] sm:max-w-[26rem]"' in PAGE and "use:autowidth={{ value: value(f) }}" in PAGE
      and "sm:w-56 lg:w-72" not in PAGE)
check("and number boxes their digits (three in all with the text one)", PAGE.count("use:autowidth={{ value: value(f) }}") == 3
      and "w-24 bg-transparent" not in PAGE)
check("no minimum wider than a short word, which left a gap after it", "use:autowidth={{ value: value(f), min:" not in PAGE)
check("measured with the field's own font, padding and border, the placeholder when empty",
      '"fontFamily", "fontSize", "fontWeight"' in AW and "(twin.style as any)[k] = cs[k];" in AW
      and "cs.font;" not in AW and "cs.paddingLeft" in AW and "cs.borderLeftWidth" in AW
      and 'node.value || node.placeholder || ""' in AW)
check("grows in the same frame as a letter, eases back as they go",
      'node.classList.toggle("is-growing", instant || want > now + 0.5);' in AW
      and ".field.is-auto.is-growing" in CSS and "transition: width 0.22s var(--swift)" in CSS)
check("never animates as the page opens", "fit(true);" in AW)
check("a value set from elsewhere resizes it too", "queueMicrotask(() => fit());" in AW)
check("motion off: no easing", ':root[data-motion="off"] input.is-auto { transition: none; }' in CSS)
FEEL = (ROOT / "webui" / "src" / "lib" / "feel.ts").read_text(encoding="utf-8")
check("a click is not typing: no field springs wider when clicked, or loses its width when left",
      "focusin" not in FEEL and "focusout" not in FEEL and "dataset.grown" not in FEEL and "input[data-grown]" not in CSS)
W = ROOT / "webui" / "src"
for rel, needle in (("lib/components/ModelsPanel.svelte", "use:autowidth={{ value: tokens }}"),
                    ("lib/components/MoodEditor.svelte", "use:autowidth={{ value: maxMinutes }}"),
                    ("lib/components/Profile.svelte", "use:autowidth={{ value: emoji }}"),
                    ("lib/components/TelegramPanel.svelte", "use:autowidth={{ value: ownerDraft }}"),
                    ("lib/components/EnvEditor.svelte", "use:autowidth={{ value: newKey }}"),
                    ("pages/Memory.svelte", "use:autowidth={{ value: newKey }}")):
    check(f"the value box in {rel.split('/')[-1]} fits its words too", needle in (W / rel).read_text(encoding="utf-8"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
