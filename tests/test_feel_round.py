"""A round of feel, each asked for.

  * the numbers on lists: the first three of a ranking are medals, the rest glass chips, an order's first in the
    accent; they were flat dots and bare faint digits
  * switches arriving together go on one after another, like dominoes, very fast, each a note higher
  * a click never waits for an appearance reveal: it ends it, and goes on to what was under it
  * opening a dropdown's list never moves the page (it jumped up to the list and back)
  * a field springs wider while it is typed in, and back after
  * choices among a few are chips that pop, one of several with a highlight that springs across
  * the Snapchat card's shine is a soft light, not a band with hard sides
  * charts grow in as their tab opens, each bar a note, and the Dashboard's widgets are heard landing
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
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def code(text):
    """Without comments: what runs, not what is said about it."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", text)


print("== the numbers on lists ==")
rb = read("lib/components/RankBadge.svelte")
check("the first three of a ranking are medals: gold, silver and bronze coins with a rim and a ribbon",
      'kind === "rank" && n >= 1 && n <= 3' in rb and all(f".rk.is-{m} {{" in rb for m in ("gold", "silver", "bronze"))
      and "conic-gradient(" in rb and ".rk-ribbon::before" in rb)
check("the rest are glass chips the same size, not bare faint digits",
      "glass chips the medals' size" in rb and "var(--color-faint)" not in rb)
check("an order's first in the accent, no medals", ".rk.is-first .rk-coin {" in rb and 'class:is-first={kind === "step" && n === 1}' in rb)
check("the number centred on the digit itself", "text-box: trim-both cap alphabetic;" in rb)
check("a shine crosses the medals as the list arrives, bronze first, silently",
      "calc(var(--shine-at) + var(--order) * 150ms)" in rb and "--order: {3 - n}" in rb and "play(" not in rb)
for rel in ("lib/dashboard/WidgetBody.svelte", "lib/components/ModelsPanel.svelte", "lib/components/ModelPicker.svelte",
            "lib/bigpicture/BPRotate.svelte", "lib/bigpicture/BPScenes.svelte"):
    check(f"{rel.split('/')[-1]} numbers its rows with it", "<RankBadge" in read(rel))
check("the old dots are gone", ".ap-rank" not in read("lib/dashboard/WidgetBody.svelte")
      and ".mp-step" not in read("lib/components/ModelsPanel.svelte") and ".bpr-rank" not in read("lib/bigpicture/BPRotate.svelte"))
check("Big Picture's medals shine without a ting: it has its own sounds and shows the list again and again",
      "<RankBadge n={i + 1} size={18} quiet />" in read("lib/bigpicture/BPRotate.svelte") and " quiet />" in read("lib/bigpicture/BPScenes.svelte"))

print("\n== switches like dominoes ==")
tg = read("lib/components/Toggle.svelte")
check("a run in reading order, a step apart", "const STEP = 40;" in tg
      and ".sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left);" in tg)
check("each set going at once with how long to wait, the browser keeping the gaps (timers bunched up)",
      "w.go(run++, Math.round(at - now));" in tg and "setTimeout(() => w.go" not in tg
      and "calc(0.03s + var(--tg-wait, 0ms))" in tg and 'style="--tg-wait: {wait}ms"' in tg)
check("a new run starts from the bottom note after a pause", "if (now - lastAt > 250) run = 0;" in tg)
check("only a switch going on, seen, once its row has landed", "if (!get(motionEnabled) || !checked) {" in tg
      and "afterLanding(el, () =>" in tg and "if (!seen || !arriving) {" in tg)
check("a click before its turn takes over at once", "arriving = false;\n    arrived = true;\n    checked = !checked;" in tg)

print("\n== a click never waits for a reveal ==")
sw = read("lib/themesweep.ts")
check("a press, a key or the wheel ends it there and then", 'addEventListener("keydown", endReveal' in sw
      and 'addEventListener("wheel", endReveal' in sw and "t?.skipTransition();" in sw)
check("the press's click, which the browser gives the page's root, handed on to what was under it",
      "document.elementFromPoint(e.clientX, e.clientY)" in sw and "e.target !== document.documentElement" in sw
      and "(el as HTMLElement).click?.();" in sw)
check("another look picked meanwhile gets a reveal of its own, the newer one tidying up",
      "running" not in code(sw) and "if (mine === latest) root.classList.remove(\"theme-switching\");" in sw)

print("\n== a dropdown never moves the page ==")
il = read("lib/inlist.ts")
check("only the list scrolls, and focusing does not scroll", "box.scrollTop +=" in il and "scrollIntoView" not in code(il)
      and "focus({ preventScroll: true })" in il)
for rel in ("lib/components/TimezonePicker.svelte", "lib/components/LanguagePicker.svelte", "lib/components/Select.svelte",
            "lib/components/ModelChooser.svelte"):
    text = code(read(rel))
    check(f"{rel.split('/')[-1]}", "scrollIntoView" not in text and "showInList(" in text and "focusStill(" in text
          and ".focus()" not in text)

print("\n== fields and chips ==")
fe = read("lib/feel.ts")
check("a field no longer springs wider on a click: it grows as it is typed in (lib/autowidth.ts)",
      "focusin" not in fe and "dataset.grown" not in fe and "export function autowidth" in read("lib/autowidth.ts"))
check("a chip pops as it is clicked, bigger as it is picked, its mark jumping", "function chipPop(chip: HTMLElement)" in fe
      and 'chip.querySelector(".chip-mark")?.animate(' in fe)
check("installed once for the whole app", "onMount(installFeel);" in read("App.svelte"))
css = read("app.css")
check("chips: pills, squashed under the finger, filled when picked", ".chip:active {\n  transform: scale(0.93, 0.88);" in css
      and '.chip[aria-pressed="true"] {' in css)
check("one of several: a highlight that springs across to it, down a line too", ".chips.is-one .chip[aria-pressed=\"true\"]" in css
      and ".chip-glide {" in css)
st = read("pages/Settings.svelte")
check("Settings' choices among a few are chips", st.count('class="chip"') >= 3 and "jelly flex items-center gap-1.5 rounded-lg border" not in st)
check("the night's status is one of four, gliding", 'class="chips is-one w-full justify-end sm:w-80" data-sound="self" use:glide={value(f)}' in st)

print("\n== the Snapchat card's shine ==")
sn = read("lib/components/SnapchatSetup.svelte")
shine = sn.split("  .sn-shine {")[1].split("}")[0]
check("a soft round light, blurred at every edge", "radial-gradient(closest-side" in shine and "filter: blur(3px);" in shine
      and "border-radius: 50%;" in shine)
check("nothing clipping it flat: it fades in and out instead",
      "overflow: hidden" not in sn.split("  .sn-bar {")[1].split("}")[0] and "18% { opacity: 1; }" in sn)

print("\n== charts arriving ==")
gi = read("lib/growin.ts")
check("once their block has landed and they can be seen, in a second wave down it",
      "afterLanding(el, () => onScreen(el).then((seen) => {" in gi and "down * PER_PX" in gi)
check("rows that move by their own CSS wait for the list's moment (held in a dropping block, they all went at once)",
      'node.classList.add("is-in")' in gi and ".ap-list:global(.is-in) .ap-row {" in read("lib/dashboard/WidgetBody.svelte"))
for rel in ("lib/accounts/WeekBars.svelte", "lib/dashboard/Spark.svelte", "lib/components/StatChart.svelte"):
    check(f"{rel.split('/')[-1]} grows in", "growIn(" in read(rel))
check("a line is drawn at a pen's steady pace, a tick at each point", "transition-timing-function: linear;" in read("lib/components/StatChart.svelte"))
check("a bar's delay is only for growing in, not for a hover's colour after", "transition-delay:{growing ? i * STAGGER : 0}ms"
      in read("lib/accounts/WeekBars.svelte"))
check("the Dashboard's widgets drop in whole, each heard as it lands", "data-rise\n        data-land-sound" in read("pages/Dashboard.svelte")
      and 'if (landed) play("settle");' in read("lib/cascade.ts"))
check("a figure counts up with its block, not before it is seen", "whenShown(el).then(() => onScreen(el))" in read("lib/dashboard/Num.svelte"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
