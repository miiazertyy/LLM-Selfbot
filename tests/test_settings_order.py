"""The order the Settings tabs read in (2026-11-05).

The tabs were in the order they were added over the months: App, Models, AI behaviour, Appearance, then every
platform in the order it was built. Now one list says the order, in runs - the app itself, the brain it answers
with, then the places it talks - and the definitions below it stay where they were written.

What matters is that the list cannot quietly lose a tab. A tab left out of it used to be a tab that vanished from
the nav, so the order is checked against the tabs that actually exist, not against itself.
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


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


smap = read("webui/src/lib/settingsmap.ts")

print("== one list says the order ==")
# A tab's own fields sit at four spaces; a subtab's at eight. That is what tells the two apart here.
defined = re.findall(r'^    id: "([a-z]+)",$', smap, re.M)
check("every tab is defined once", len(defined) == len(set(defined)) and len(defined) >= 14, str(defined))
block = re.search(r"const ORDER:[^=]+=\s*\[(.+?)\n\];", smap, re.S)
check("there is an ORDER list", block is not None)
runs = re.findall(r'\{\s*group:\s*"(\w+)",\s*ids:\s*\[([^\]]*)\]\s*\}', block.group(1) if block else "")
ordered = [i.strip().strip('"') for _, ids in runs for i in ids.split(",") if i.strip()]

check("it names every tab that exists", sorted(ordered) == sorted(defined),
      str(sorted(set(defined) ^ set(ordered))))
check("and names none twice", len(ordered) == len(set(ordered)))
check("the runs are the app, its brain, then where it talks",
      [g for g, _ in runs] == ["app", "brain", "chats", "feeds", "games"], str([g for g, _ in runs]))

print("\n== the order itself ==")
where = {tab: i for i, tab in enumerate(ordered)}
check("the app's own settings come first", ordered[:2] == ["app", "look"], str(ordered[:2]))
check("then what it thinks with, Calls last of the three",
      ordered[2:5] == ["groq", "ai", "calls"], str(ordered[2:5]))
check("Discord opens the platforms, being the one it was built on", ordered[5] == "discord")
check("the ones you message someone on come before the ones that are a feed",
      max(where[p] for p in ("discord", "telegram", "whatsapp", "imessage", "snapchat"))
      < min(where[p] for p in ("instagram", "tiktok", "x", "reddit")))
check("and the game is last of all", ordered[-1] == "minecraft")
check("Calls is no longer a page inside AI behaviour",
      smap.index('id: "calls",\n    name: "Calls",') > smap.index('id: "videos",'))

print("\n== the pages inside a tab ==")


def pages(tab_id):
    """The subtabs of one tab, in the order shown, as (id, name, [keys])."""
    # Anchored to the start of a line: a tab's id sits at four spaces, a subtab's at eight, and "telegram" is both
    # a tab and a page of App.
    at = smap.index(f'\n    id: "{tab_id}",')
    start = smap.index("    subs: [", at) + len("    subs: [")
    depth, i = 1, start
    while depth:
        depth += (smap[i] == "[") - (smap[i] == "]")
        i += 1
    body, out, deep, opened = smap[start:i - 1], [], 0, 0
    for j, ch in enumerate(body):
        if ch == "{":
            if not deep:
                opened = j
            deep += 1
        elif ch == "}":
            deep -= 1
            if not deep:
                piece = body[opened:j + 1]
                out.append((re.search(r'id: "([a-z_-]+)"', piece).group(1),
                            re.search(r'name: "([^"]+)"', piece).group(1),
                            re.findall(r'"([a-z_]+\.[a-z0-9_.]+)"', piece)))
    return out


ids = {t: [p[0] for p in pages(t)] for t in ordered}
names = {t: [p[1] for p in pages(t)] for t in ordered}
keys = {t: {p[0]: p[2] for p in pages(t)} for t in ordered}

# Appearance and Models are panels the whole way down and have no catch-all at all; the rest end with one.
check("a tab with an Everything else has it last",
      all(p[-1] == "rest" for p in ids.values() if "rest" in p),
      str([t for t, p in ids.items() if "rest" in p and p[-1] != "rest"]))
# Every platform you sign into through a browser reads the same way, so knowing one is knowing them all. The page
# ids differ ("pace" on some, "pacing" on others) because links to them are in released builds; the names are what
# anyone reads, and those match.
BROWSERS = ("snapchat", "instagram", "tiktok", "x", "reddit")
check("the browser platforms all open with setting it up, then the browser, then how it behaves",
      all(names[t][:3] == ["Install", "Browser", "Behaviour"] for t in BROWSERS),
      str({t: names[t][:3] for t in BROWSERS}))
FEEDS = ("instagram", "tiktok", "x", "reddit")
check("what it reads comes before what it does about what it read",
      all(ids[t].index("watch" if t in ("x", "reddit") else "watching") < ids[t].index("engage") for t in FEEDS),
      str({t: ids[t] for t in FEEDS}))
# Two different pages are called Comments. On Instagram and TikTok it is the comments under its own posts, so it
# follows Posting; on Reddit it is the ones it leaves under other people's, so it sits with the votes.
check("comments under its own posts follow Posting",
      all(ids[t].index("posting") < ids[t].index("comments") for t in ("instagram", "tiktok")))
check("comments it leaves on other people's go with the votes",
      ids["reddit"].index("engage") < ids["reddit"].index("comments") < ids["reddit"].index("posting"))
check("TikTok's five LIVE pages are together at the end, not across the middle",
      ids["tiktok"][-6:] == ["live", "live-answers", "live-style", "live-overlay", "visits", "rest"],
      str(ids["tiktok"]))
check("WhatsApp paces itself where Telegram and iMessage do, before its extras",
      ids["whatsapp"].index("pace") < ids["whatsapp"].index("status") < ids["whatsapp"].index("calls"),
      str(ids["whatsapp"]))
check("how it talks and how it writes are the same subject, so they are next to each other",
      names["ai"][:2] == ["How it talks", "How it writes"], str(names["ai"][:2]))

print("\n== the settings inside a page ==")
# The switches in What runs were in the order the platforms were built. A switch should be where its tab is.
switches = [k for k in keys["app"]["services"] if k.startswith("services.") and k.endswith(".enabled")]
platforms = [t for t in ordered if t not in ("app", "look", "groq", "ai", "calls")]
want = ["services." + ("telegram_accounts" if p == "telegram" else p) + ".enabled" for p in platforms]
check("the platform switches are in the same order as the tabs", switches[:len(want)] == want, str(switches))
check("and the bot you command and the panel come after them",
      switches[len(want):] == ["services.telegram.enabled", "services.webui.enabled"], str(switches[len(want):]))
# Both of these used to sit on the Comments page. The subreddits are what it may post to as well, and a hidden
# account stops everything public, not only its comments.
check("Reddit's subreddits and hidden-account check belong to the whole account",
      {"reddit.subreddits", "reddit.check_shadowban"} <= set(keys["reddit"]["pace"])
      and not {"reddit.subreddits", "reddit.check_shadowban"} & set(keys["reddit"]["comments"]))
check("the web's two caps sit together, not either side of the free-time browsing",
      keys["ai"]["web"].index("bot.web.per_hour") < keys["ai"]["web"].index("bot.web.free_time")
      < keys["ai"]["web"].index("bot.web.sessions_per_day"), str(keys["ai"]["web"]))

print("\n== what the nav draws ==")
check("the order is what the nav walks, not the order they were written",
      "export const TABS: Tab[] = (() => {" in smap and "for (const { group, ids } of ORDER)" in smap)
check("a tab not named in the list is kept, at the end",
      "...[...left.values()].map(" in smap)
settings = read("webui/src/pages/Settings.svelte")
check("a hairline sets each run apart", "runStarts" in settings
      and 'class="settings-rail-sep"' in settings and "firstSocial" not in settings)
# A social switched off has no tab at all (lib/socials.ts), so the runs are read off the tabs on screen: otherwise
# switching the last of a run off would leave a hairline with nothing under it.
check("read off the tabs on screen, so a switched-off social leaves no stray line",
      "tabs.filter((t, i) => i > 0 && t.group !== tabs[i - 1].group)" in settings)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
