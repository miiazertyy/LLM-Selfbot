"""Every tab's opening starts the moment it is opened: no still pause first.

A tab's blocks drop into place in a wave (cascade.ts), and what each block
animates is held until it shows. It was held until the block had landed, half
a second and more, so a tab sat still before anything on it moved, and the
Profiles tab felt frozen for a second before its cards were dealt. Now what a
block holds is let go a moment into its drop; the wave itself is quicker; the
second waves inside a block (lists, charts) are barely behind it; and the
Profiles tab's own opening starts on its first frames. Also: the scroll wheel
at the top or the bottom of a box keeps it still there instead of jumping.
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


def num(src, name):
    m = re.search(rf"const {name} = ([\d.]+);", src)
    return float(m.group(1)) if m else None


cas = read("lib/cascade.ts")
dom = read("lib/domino.ts")
gro = read("lib/growin.ts")
css = read("app.css")
pro = read("pages/Profiles.svelte")

print("== a block lets what it holds move as it shows ==")
check("what a block animates is held only until it shows", "[data-arriving] *" in css
      and "animation-play-state: paused !important;" in css)
check("let go a moment into its drop, not once it has landed", "const RELEASE_MS = 40;" in cas
      and "setTimeout(() => delete el.dataset.arriving, delay + RELEASE_MS);" in cas
      and "anim.finished.then(() => delete el.dataset.arriving" not in cas)
release, duration = num(cas, "RELEASE_MS"), num(cas, "DURATION")
check("a small part of the drop, not most of it", release is not None and duration and release <= duration * 0.15,
      f"{release} of {duration}ms")
check("the wave down the tab quicker, and over sooner", num(cas, "PER_PX") <= 0.3 and num(cas, "MAX_DELAY") <= 240
      and num(cas, "DURATION") <= 440)
check("the second waves in a block barely behind the first: lists and charts alike",
      num(dom, "PER_PX") <= 0.12 and num(dom, "MAX_WAIT") <= 120 and num(gro, "PER_PX") <= 0.12 and num(gro, "MAX_WAIT") <= 120)
check("and the comments say so", "never after a still pause" in css and "never before it shows and never after a still pause" in cas)

print("\n== Profiles opens at once ==")
check("its cards are not held for the tab's wave: dealt from the first frames", '<div class="pr-grid" use:deal data-no-rise>' in pro)
deal = num(pro, "DEAL_STEP")
check("dealt close behind each other", deal is not None and deal <= 80, str(deal))
sheen = re.search(r"animation: pr-sheen ([\d.]+)s [^;]* ([\d.]+)s both;", pro)
check("the hero's light sweeps at once", sheen is not None and float(sheen.group(2)) <= 0.05, sheen and sheen.group(0))
check("its ring winds in with no wait", "animation: pr-ring-in 0.75s cubic-bezier(0.2, 0.9, 0.25, 1) backwards," in pro)
letters = re.search(r"animation-delay: calc\(([\d.]+)s \+ var\(--c\) \* (\d+)ms\);", pro)
check("its title's letters start rising straight away", letters is not None and float(letters.group(1)) <= 0.05
      and int(letters.group(2)) <= 20, letters and letters.group(0))
check("heard from the first frame: the whoosh 40ms in", 'use:chime={{ sound: "wind", delay: 40 }}' in pro)
first = [int(x) for x in re.findall(r"animation-delay: calc\(var\(--at\) \+ (\d+)ms", pro)]
check("what is on each card follows it within a few tenths of a second", first and max(first) <= 400, str(first))

print("\n== the wheel at either end of a box ==")
ss = read("lib/smoothscroll.ts")
check("a box still gliding to its end keeps the wheel, and for a moment after",
      "const LATCH_MS = 450;" in ss and 'if (g && (g.raf || performance.now() - g.ended < LATCH_MS)) return "hold";' in ss)
check("held: nothing moves, not the rest of the way in one jump, not the page behind it",
      'e.preventDefault();\n  if (el !== "hold") glide(el, dy);' in ss)
check("the moment counts from when its glide stopped", ss.count("g.ended = now;") == 2)
check("a box at its end that keeps its scroll to itself is left alone",
      'if (!root && getComputedStyle(el).overscrollBehaviorY !== "auto") return null;' in ss)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
