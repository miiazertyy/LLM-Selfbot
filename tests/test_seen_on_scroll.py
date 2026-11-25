"""What was out of sight as a tab opened makes its entrance when it is scrolled to, sound and all (2026-11-09).

"Is it on screen" used to be asked once, as the tab opened. Open a subtab with the page scrolled down and everything
above the window had already skipped its entrance: scrolling up to it was silent. Part of the same bug: the setup pages
asked about their top card only, so the steps lit in full view with no sound when that card was scrolled out.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


cascade = read("lib/cascade.ts")
fn = cascade.split("export function onScreen")[1].split("\nfunction plain")[0]
print("== waiting to be seen ==")
check("it waits, and is not asked once and forgotten", "watched.set(node" in fn and "eyes.observe(node)" in fn and "io.disconnect()" not in fn)
check("true the moment it is on screen", "if (e.isIntersecting) settle(e.target, true)" in fn)
check("false if its tab goes first, so nothing waits for ever", "if (!el.isConnected) settle(el, false)" in fn)
check("a sliver at the window's edge has not been seen", 'rootMargin: "-16px 0px -16px 0px"' in fn)
check("with Animations off there is nothing to wait for", "if (!get(motionEnabled)) return resolve(true)" in fn)
check("one observer for them all, and no timer left once none are waiting", "eyes ??=" in fn and "clearInterval(rounds)" in cascade)

print("\n== what waits with it ==")
select = read("lib/components/Select.svelte")
check("a dropdown types its word when it is seen, not unseen and silent", "whenShown(el).then(() => onScreen(el)).then((seen) => {\n      heard = seen;" in select)
waits = read("lib/components/WaitTimes.svelte")
check("the waits grow when they can be heard growing", "whenShown(el).then(() => onScreen(el)).then((seen) => {\n      arrived = arriving = true;" in waits)
for name, other in (("MinecraftSetup", "list"), ("SnapchatSetup", "list"), ("ReadyHero", "ol")):
    src = read(f"lib/components/{name}.svelte")
    check(f"{name}: lights when its steps or its card come into view, whichever is first",
          f"heard = await Promise.race([onScreen(el), onScreen({other})]);" in src)
domino = read("lib/domino.ts")
check("a chime off screen holds its pop, so the two still go together",
      'node.dataset.arriving = "";' in domino and "delete node.dataset.arriving;" in domino and "if (seen) play(sound, { delay });" in domino)
flag = read("lib/components/LanguagePicker.svelte")
check("so does a language's flag", 'el.dataset.arriving = "";' in flag and "delete el.dataset.arriving;" in flag)
arrive = read("lib/arrive.ts")
check("a slider changed while it waited keeps the new value, and does not sweep to the old one",
      "if (Number(node.value) !== start) return letGo();" in arrive)
check("app.css holds what is marked", "[data-arriving] *" in read("app.css") and "animation-play-state: paused !important" in read("app.css"))

print("\n== nothing still says otherwise ==")
stale = [f.name for f in SRC.rglob("*") if f.suffix in (".svelte", ".ts") and "nobody would see" in f.read_text(encoding="utf-8")]
check("no comment still says it skips what nobody would see", not stale, str(stale))
users = [f for f in SRC.rglob("*") if f.suffix in (".svelte", ".ts") and re.search(r"import \{[^}]*\bonScreen\b[^}]*\} from \"[./]*cascade\"", f.read_text(encoding="utf-8"))]
check("every entrance goes through the one check", len(users) >= 14, str([f.name for f in users]))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
