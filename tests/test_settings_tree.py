"""Settings is tabs with subtabs, and nothing falls out of the tree.

The page used to be one flat list of 82 rows, most of them behind a "show 14
more advanced settings" button. It is now a tab per subject with subtabs inside,
and that tree lives in webui/src/lib/settingsmap.ts.

Two things can silently break it, and both are checked here:

  * a setting exists in config.yaml but no subtab lists it and no tab claims its
    prefix, so it has no control anywhere. That is exactly the bug the auto
    discovered field list was written to fix, and a hand written tree can
    reintroduce it.
  * the dependency doctor and the health banners send you straight to the
    setting that is wrong, naming it in words. If a name here and a name there
    drift apart the link lands on the wrong tab, or on nothing.

The tree is TypeScript, so it is read as text rather than imported. That is
enough: both checks only need the quoted strings.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


MAP = (ROOT / "webui" / "src" / "lib" / "settingsmap.ts").read_text(encoding="utf-8")

print("== the tree parses ==")
check("settingsmap.ts exists", bool(MAP.strip()))

# Tab ids and the prefixes each tab claims leftovers for.
tab_ids = re.findall(r'^\s{4}id: "([a-z-]+)",', MAP, re.M)
check("every tab is present", set(tab_ids) >= {"discord", "snapchat", "groq", "ai", "app", "look"},
      str(sorted(tab_ids)))

owns = set()
for block in re.findall(r"owns: \[([^\]]*)\]", MAP):
    owns.update(re.findall(r'"([^"]+)"', block))
check("tabs claim the config roots", owns >= {"bot", "discord", "snapchat", "services", "notifications"},
      str(sorted(owns)))

# Every dotted config key the tree names, wherever it names it.
listed = set(re.findall(r'"((?:bot|discord|snapchat|services|notifications)\.[a-z_.0-9]+)"', MAP))
check("the tree names a good number of keys", len(listed) > 50, str(len(listed)))

print("\n== nothing in config.yaml is unreachable ==")
from fixtures import use_shipped_config
use_shipped_config()

from app.utils.helpers import load_config
from app.web.schema import CONFIG_SCHEMA
from app.web import descriptions as desc

cfg = load_config()
keys = []
for field in CONFIG_SCHEMA:
    if not desc.is_hidden(field["key"]):
        keys.append(field["key"])
for key, _ in desc.walk(cfg):
    if key not in keys and not desc.is_hidden(key):
        keys.append(key)

check("the schema still has every setting", len(keys) > 70, str(len(keys)))


def claimed(key: str) -> bool:
    """Listed by name, or covered by a tab's leftovers."""
    if key in listed:
        return True
    return any(key == p or key.startswith(p + ".") for p in owns)


orphans = [k for k in keys if not claimed(k)]
check("every setting has a home", not orphans, ", ".join(orphans[:6]))

# A key listed in the tree that no longer exists is harmless, the page skips it,
# but a pile of them means the tree has drifted from the config.
stale = [k for k in sorted(listed) if k not in keys]
check("at most a couple of stale keys in the tree", len(stale) <= 3, ", ".join(stale))

print("\n== the pointers other pages use still resolve ==")
paths = set()
# A tab runs until the next one starts. The boundary is the four space indent
# alone: requiring `name:` on the very next line broke the moment a tab carried
# a comment, and silently merged that tab into the one before it.
for tab_block in re.finditer(r'^\s{4}id: "([a-z-]+)",(.*?)(?=^\s{4}id: "[a-z-]+",|\Z)',
                             MAP, re.M | re.S):
    tab = tab_block.group(1)
    # A subtab is written either over several lines or, when it is short, as
    # one object on a single line.
    for sub in re.findall(r'(?:^\s{6,8}|\{ )id: "([a-z-]+)",', tab_block.group(2), re.M):
        paths.add(f"{tab}/{sub}")
check("subtab paths were found", len(paths) > 15, str(len(paths)))

aliases = dict(re.findall(r'^\s+"?([a-z ]+?)"?: "([a-z]+/[a-z-]+)",$', MAP, re.M))
check("aliases were found", len(aliases) > 10, str(sorted(aliases)))

bad_alias = {a: t for a, t in aliases.items() if t not in paths}
check("every alias points at a real subtab", not bad_alias, str(bad_alias))

# Whatever the doctor and the health checks ask for has to be one of them.
wanted = set()
for name in ("health_routes.py", "system_routes.py"):
    text = (ROOT / "app" / "web" / "routes" / name).read_text(encoding="utf-8")
    wanted.update(re.findall(r'"section": "([^"]+)"', text))
    wanted.update(re.findall(r'section="([^"]+)"', text))
wanted.discard("")
check("pointers were found", len(wanted) >= 5, str(sorted(wanted)))

unknown = sorted(w for w in wanted if w.lower() not in aliases and w.lower() not in paths)
check("every pointer resolves", not unknown, str(unknown))

print("\n== the advanced settings disclosure is gone ==")
page = (ROOT / "webui" / "src" / "pages" / "Settings.svelte").read_text(encoding="utf-8")
check("no show-more button", "Show {hiddenCount}" not in page)
check("nothing counts hidden fields any more", "hiddenCount" not in page)
check("no alwaysAdvanced preference", "alwaysAdvanced" not in page)
check("the preference is gone from the store",
      "alwaysAdvanced" not in (ROOT / "webui" / "src" / "lib" / "stores.ts").read_text(encoding="utf-8"))
check("and from what the server will store",
      "alwaysAdvanced" not in (ROOT / "app" / "web" / "routes" / "prefs_routes.py").read_text(encoding="utf-8"))
check("the subtab strip is rendered", "settings-subs" in page)
css = (ROOT / "webui" / "src" / "app.css").read_text(encoding="utf-8")
check("the strip is styled", "settings-sub" in css)

print("\n== the horizontal strips scroll ==")
# Both strips overflow on a narrow window, and both were unreachable with a
# mouse: no visible bar, no drag, and a wheel does nothing without help.
check("the rail is wrapped for scrolling", 'class="hscroll"' in page)
check("the subtab strip is too", "hscroll settings-subs-wrap" in page)
check("both use the action", page.count("use:hscroll") == 2, str(page.count("use:hscroll")))
check("the action exists", (ROOT / "webui" / "src" / "lib" / "hscroll.ts").is_file())

action = (ROOT / "webui" / "src" / "lib" / "hscroll.ts").read_text(encoding="utf-8")
for what, needle in (("a wheel scrolls it sideways", "onWheel"),
                     ("it can be dragged", "onPointerDown"),
                     ("a drag does not also pick a tab", "onClickCapture"),
                     ("it remeasures when the window changes", "ResizeObserver")):
    check(what, needle in action)

# The wrapper is a grid item, and a grid item will not shrink below its content
# unless told to. Without this the whole page grew wider than the window rather
# than the strip scrolling inside it, which is subtle enough to be worth pinning.
def rule(selector: str) -> str:
    """The body of one rule, matched at the start of a line.

    A plain substring search finds "  .settings-subs-wrap .hscroll-bar {" first
    and reads that instead, which is a different rule with a different job.
    """
    m = re.search(r"^" + re.escape(selector) + r" \{(.*?)^\}", css, re.M | re.S)
    return m.group(1) if m else ""

check("the wrapper is allowed to shrink", "min-width: 0" in rule(".hscroll"))
check("the bar is out of the layout", "position: absolute" in rule(".hscroll-bar"))
check("the bar starts hidden", "opacity: 0" in rule(".hscroll-bar"))
check("no native scrollbar is drawn for the rail",
      "::-webkit-scrollbar" not in css[css.index(".settings-rail {"):css.index(".settings-tab {")]
      or "display: none" in css[css.index(".settings-rail::-webkit-scrollbar"):][:80])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
