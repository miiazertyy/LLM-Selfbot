"""Opening a busy settings page, and changing theme, without the stutter.

  * a subtab's rows go on the page a few at a time, and what arrives later
    joins the opening wave; the wave only looks again for new blocks, not for
    every change inside the ones it has moved
  * the dials' and clocks' marks are a few paths, not an element each; a
    pluck draws a line of its own; nothing is plucked while a dial sweeps in;
    the accent is read once, not for every mark; no blurs redrawn every frame
  * controls below the fold go straight to their value, no sweep nobody sees
  * the switch examples wake only when something changes, with no Svelte
    transitions measuring their lines, each in a box of its own
  * the theme spreads out from the swatch that was clicked, drawn by the
    browser's view transition: a blob with a wobbling edge, a thump as it
    lands, stars as the edge passes, and no colour transitions while it plays
"""
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


settings = read("pages/Settings.svelte")
cascade = read("lib/cascade.ts")
dial = read("lib/components/Dial.svelte")
hours = read("lib/components/HourRange.svelte")
tape = read("lib/components/Tape.svelte")
pluck = read("lib/pluck.ts")
demo = read("lib/components/SwitchDemo.svelte")
arrive = read("lib/arrive.ts")
sweep = read("lib/themesweep.ts")
css = read("app.css")

print("== a busy page opens in pieces ==")
check("the first rows go on at once, the rest a couple a frame", "const FIRST_ROWS = 4;" in settings
      and "n += 2;" in settings and "requestAnimationFrame(more)" in settings)
check("a new subtab starts from the first rows again, before it is drawn", "grown.path === path ? grown.n : FIRST_ROWS" in settings)
check("the typing preview waits for all the rows, rather than jumping down the page", 'sub.id === "typing" && drawnRows >= rowsOf(shown).length' in settings)
check("the wave only looks again for blocks it has not moved", "if (n instanceof HTMLElement && !inside(n))" in cascade
      and "seen.has(p)" in cascade)

print("\n== the dials are cheap to draw ==")
for name, src in (("the time dial", dial), ("the hour clock", hours)):
    check(f"{name}'s marks are a few paths", "marksPath(" in src and "{#each TICKS" not in src and "tickEls" not in src)
    # Sweeping in, it is heard (a soft detent each mark: the "wind" sound) but nothing is plucked.
    sweep_in = src[src.index("if (!plucking) {"):] if "if (!plucking) {" in src else ""
    sweep_in = sweep_in[:sweep_in.index("return;")] if "return;" in sweep_in else ""
    check(f"{name} plucks nothing while it sweeps in", sweep_in and "pluck(" not in sweep_in
          and "plucking = true;" in src and "}, seen ? 1200 : 0);" in src)
    check(f"{name}'s glow is two faint strokes, not a blur", "filter: blur" not in src and "is-wide" in src)
    check(f"{name} is laid out on its own", "contain: layout style;" in src)
    check(f"{name} goes straight to its value off screen", "whenShown(el).then(() => onScreen(el))" in src and "instant = !seen;" in src)
check("which marks are lit changes only as a hand crosses one", "const inFrom = $derived(Math.ceil(tA.current * 50 - 0.05));" in dial)
check("a pluck is a line of its own, taken away when it is done", 'document.createElementNS(SVG, "line")' in pluck
      and "anim.onfinish = anim.oncancel = () => line.remove();" in pluck)
check("the accent is read once, and again only when the theme changes it", "function accentNow()" in pluck
      and 'attributeFilter: ["style", "data-theme"]' in pluck)
check("the dial's words are measured after layout, not while the page is built", "new ResizeObserver(" in dial and "offsetWidth" not in dial)
check("the tape and the sliders skip their sweep off screen too", "instant = !seen;" in tape and "if (!seen) return stop();" in arrive)
check("the timezone is asked once", "zone ||= Intl.DateTimeFormat()" in read("lib/clock.ts"))
check("the typing keys start once their row has landed", "await sleep(750);" in read("lib/components/TypingSpeed.svelte"))

print("\n== the switch examples keep still until something changes ==")
check("no ticking every ninety milliseconds", "setInterval" not in demo and "moments.find((m) => m > at + 1)" in demo)
check("no Svelte transitions measuring each line", "svelte/transition" not in demo and "svelte/animate" not in demo
      and "@keyframes sd-in" in demo)
check("each in a box of its own", ".sd { contain: strict; }" in demo)
check("starting a moment after its row lands", "start = performance.now() + 450;" in demo)

print("\n== the theme ==")
check("drawn by the browser's own view transition", "startViewTransition(" in sweep and "::view-transition-new(root)" in sweep)
check("from where the pointer went down: the swatch clicked", 'window.addEventListener("pointerdown"' in sweep and "lastX >= 0 ? lastX" in sweep)
check("a blob with a wobbling edge, fast out of the gate", "function blob(" in sweep and "polygon(" in sweep and "[0.1, 0.16, 0.2]" in sweep)
check("a thump as it lands: a touch too big, a touch too small, then still", 'scale(1.025)' in sweep and 'scale(0.991)' in sweep)
check("the old theme sinks back as it is covered", "::view-transition-old(root)" in sweep and "scale(0.982)" in sweep)
check("stars pop as the edge passes, glowing without a filter", "function stars(" in sweep
      and "drop-shadow" not in css.split(".theme-sweep-star {")[1].split("}")[0])
check("no colour transitions while it plays", "html.theme-switching *," in css and "transition: none !important;" in css
      and 'root.classList.add("theme-switching")' in sweep)
check("the browser's own crossfade is off", "::view-transition-new(root) {\n  animation: none;" in css)
check("with no view transitions, the wipe, lighter", "function wipe(" in sweep and "theme-sweep-spark" not in css)
check("with Animations off, it simply changes", 'if (typeof document === "undefined" || !get(motionEnabled)) {\n    apply();' in sweep)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
