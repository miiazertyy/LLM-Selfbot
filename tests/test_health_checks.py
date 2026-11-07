"""The health checks on the System page say where to go, and can be put away.

Three rows printed "[object Object]": the jump to the setting was handed over where the words for the fix go, so it came
out as text and no button appeared. All three also said the same vague sentence. Each now says what it is, names the
places to change it as buttons that go there, and has "Don't show again", with the ones put away still listed.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# The config the project ships, in a sandbox: config/ is only made by running the app, so a fresh checkout (CI) has none.
from fixtures import use_shipped_config  # noqa: E402

use_shipped_config()
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


import yaml

from app.utils import stealth
from app.web.routes import system_routes as sr

MAP = read("webui/src/lib/settingsmap.ts")
PATHS = set()
for tab in re.finditer(r'^\s{4}id: "([a-z-]+)",(.*?)(?=^\s{4}id: "[a-z-]+",|\Z)', MAP, re.M | re.S):
    for sub in re.finditer(r'(?:^\s{6,8}|\{ )id: "([a-z-]+)"', tab.group(2), re.M):
        PATHS.add(f"{tab.group(1)}/{sub.group(1)}")
check("the settings map was read", {"ai/careful", "tiktok/browser", "calls/voice"} <= PATHS and len(PATHS) > 60, str(len(PATHS)))


print("\n== where each one is changed ==")
everything_on = {"bot": {"calls": {"enabled": True, "vc": True}, "conservative": {}}}
shipped = yaml.safe_load(read("resources/config.yaml"))
for section in ("snapchat", "tiktok", "instagram", "x", "reddit"):
    block = dict(shipped.get(section) or {})
    block["headless"] = True
    # Whatever public part its section has, all on.
    for part in ("engage", "comments", "posting", "notes", "visits", "foryou", "mentions", "inbox", "live"):
        if part in block:
            block[part] = {"enabled": True}
    everything_on[section] = block
rows = {r["name"]: r for r in stealth.report(everything_on)}
check("careful mode off is not a problem to point at: it is a choice (2026-11-06)", "Careful mode" not in rows)
for name in ("Hidden browser windows", "Public actions", "Voice channels"):
    row = rows[name]
    check(f"{name}: is a problem here, with somewhere to go", row["ok"] is False and row["where"], str(row))
    missing = [p for p in row["where"] if p not in PATHS]
    check(f"  each place it names is a real page of Settings", not missing, str(missing))
check("each browser's own page, not the same one for all",
      rows["Hidden browser windows"]["where"] == ["snapchat/browser", "tiktok/browser", "instagram/browser", "x/browser", "reddit/browser"])
check("named as a person writes them", "TikTok" in rows["Hidden browser windows"]["detail"] and "tiktok" not in rows["Hidden browser windows"]["detail"])
check("every public thing that is on has its own place", "tiktok/engage" in rows["Public actions"]["where"]
      and "instagram/notes" in rows["Public actions"]["where"] and "x/mentions" in rows["Public actions"]["where"]
      and "reddit/inbox" in rows["Public actions"]["where"])
check("how many are on, and the places say which", re.fullmatch(r"\d+ are on", rows["Public actions"]["detail"]))
check("each says what it is about, in its own words, not one sentence for all",
      len({rows[n]["why"] for n in ("Hidden browser windows", "Public actions")}) == 2
      and all(len(rows[n]["why"]) < 70 for n in rows))
off = stealth.report({**everything_on, "services": {"tiktok": {"enabled": False}}})
off = {r["name"]: r for r in off}
check("a social switched off in Settings isn't mentioned",
      "tiktok/browser" not in off["Hidden browser windows"]["where"] and "TikTok" not in off["Hidden browser windows"]["detail"]
      and not any(p.startswith("tiktok/") for p in off["Public actions"]["where"]))
fine = {r["name"]: r for r in stealth.report({"bot": {"conservative": {"enabled": True}}, "tiktok": {"engage": {"enabled": True}}})}
check("careful mode on: public actions are off by definition, with nowhere to go",
      fine["Public actions"]["ok"] is True and fine["Public actions"]["where"] == [])


print("\n== what the panel is given ==")
real_report = stealth.report
stealth.report = lambda: list(real_report(everything_on))
checks = sr._doctor_checks(None)["checks"]
stealth.report = real_report
by_id = {c["id"]: c for c in checks}
check("the words for a fix are always words: an object there printed as [object Object]",
      all(isinstance(c["fix"], str) for c in checks), str([c["id"] for c in checks if not isinstance(c["fix"], str)]))
check("and so is what it is about", all(isinstance(c["why"], str) for c in checks))
check("a button is a button or none", all(c["action"] is None or isinstance(c["action"], dict) for c in checks))
hidden = by_id["stealth-hidden-browser-windows"]
check("its places come through, and its own sentence", hidden["places"][:2] == ["snapchat/browser", "tiktok/browser"]
      and hidden["why"] == rows["Hidden browser windows"]["why"])
check("named by what it is, so one put away stays put away when the rows above it change",
      {"stealth-public-actions", "stealth-voice-channels"} <= set(by_id) and "stealth-careful-mode" not in by_id)
good = [c for c in checks if c["ok"]]
check("one that passes has nothing to go to", good and all(c["places"] == [] and c["action"] is None for c in good))
stealth.report = lambda: list(real_report({"bot": {"conservative": {"enabled": True}}}))
twice = sr._doctor_checks(None)["checks"]
stealth.report = real_report
on = {c["id"]: c for c in twice}
check("careful mode on: one row that passes, saying until when and how much slower, in words",
      on["stealth-careful-mode"]["ok"] is True and "stealth-pace" not in on
      and "40% of the usual replies, waits 1.5× longer" in on["stealth-careful-mode"]["detail"])


print("\n== on the page ==")
page = read("webui/src/pages/System.svelte")
check("each place is a button that goes there", "{#each c.places as place (place)}" in page and "goToPlace(place)" in page
      and 'settingsSection.set(place);\n    window.location.hash = "/settings";' in page)
check("named as Settings names it, read from the same map", 'import { TABS, resolveTarget } from "../lib/settingsmap";' in page
      and "`${tab.name} › ${sub.name}`" in page)
check("every problem can be put away, with its own sound", ">Don't show again</button>" in page and 'play("off");' in page
      and 'data-sound="self" onclick={() => putCheckAway(c)}' in page)
check("and goes away with a slide", 'out:slide={moving(220)}' in page and "duration: get(motionEnabled) ? ms : 0" in page)
check("put away isn't gone: how many, and a press lists them", "{putAway.length} hidden" in page and "aria-expanded={showPutAway}" in page)
check("each with the way back, its places still there", ">Show again</button>" in page and 'play("on");' in page
      and "{@render problemRow(c, true)}" in page)
check("what is put away doesn't count: not in the headline, the ring or the card",
      "const failing = $derived(problems.length);" in page and "!c.ok && !$hiddenChecks.includes(c.id)" in page
      and "total={Math.max(1, passing.length + failing)}" in page)
check("nor is everything called fine: it says nothing ELSE needs a look, and how many are hidden",
      '"Nothing else needs a look"' in page and "`${putAway.length} hidden`" in page)
stores = read("webui/src/lib/stores.ts")
prefs = read("app/web/routes/prefs_routes.py")
check("remembered with the app", 'export const hiddenChecks = persisted<string[]>("hiddenChecks", [], true);' in stores
      and '"hiddenChecks",' in prefs)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
