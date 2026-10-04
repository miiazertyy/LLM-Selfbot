"""Smooth scrolling in the whole app, with its own switch.

A mouse wheel's notch glides the box under the pointer to where it goes,
easing in, instead of jumping there; notches in a row add up into one glide.
A touchpad, Ctrl+wheel, sideways scrolling and anything that answers the wheel
itself are left alone, and grabbing the scrollbar mid-glide hands back at once.
Settings, Appearance, Interface turns it off ("Smooth scrolling"), kept with
the app's other panel preferences. Checked in headless Chrome: with it on, a
notch went 100 -> 113 -> 141 -> 160 -> 173 -> 181 over a fifth of a second;
off, 0 -> 100 at once.
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


ss = read("lib/smoothscroll.ts")
app = read("App.svelte")

print("== the glide ==")
check("installed once for the whole app", 'import { installSmoothScroll } from "./lib/smoothscroll";' in app
      and "onMount(installSmoothScroll);" in app)
check("last in line for the wheel, so what answers it itself goes first",
      'window.addEventListener("wheel", onWheel, { passive: false });' in ss and "e.defaultPrevented" in ss)
check("easing in, frame by frame, catching up with where the wheel sent it",
      "const TAU = 0.09;" in ss and "g.pos += (g.target - g.pos) * (1 - Math.exp(-dt / TAU));" in ss)
check("notches in a row add up: the next one goes on from where the glide is going",
      "const aim = (el: HTMLElement) =>" in ss and "g.target = Math.max(0, Math.min(max, g.target + dy));" in ss)
check("only a notched wheel; a touchpad is smooth already", "function notched(e: WheelEvent)" in ss
      and "raw % 120 === 0" in ss and "!notched(e)" in ss)
check("Ctrl+wheel (zoom), Shift+wheel and sideways scrolling are the browser's",
      "e.ctrlKey || e.metaKey || e.shiftKey" in ss and "Math.abs(e.deltaX) > Math.abs(e.deltaY)" in ss)
check("the box under the pointer that can still go that way", "function scrollerFor(target: EventTarget | null, dy: number)" in ss
      and "(dy > 0 && at < max - 0.5) || (dy < 0 && at > 0.5)" in ss)
check("a box that keeps its scroll to itself stops there at its end", 'getComputedStyle(el).overscrollBehaviorY !== "auto"' in ss)
check("grabbing the scrollbar or a key mid-glide hands straight back", "Math.abs(g.el.scrollTop - g.held) > 1.5" in ss)
check("lines and pages turned into pixels", "e.deltaMode === 1 ? e.deltaY * LINE" in ss and "innerHeight * 0.9" in ss)
check("no CSS smooth scrolling fighting it on the page's own scroller",
      "scroll-behavior: smooth" not in app)

print("\n== its switch ==")
stores = read("lib/stores.ts")
ap = read("lib/components/Appearance.svelte")
cp = read("lib/components/CommandPalette.svelte")
check("a preference of its own, on by default, kept with the app",
      'export const smoothScroll = persisted<boolean>("smoothScroll", true, true);' in stores)
check("the glide asks it, and only it", "const wanted = () => get(smoothScroll);" in ss and "!wanted() ||" in ss
      and "motionEnabled" not in ss)
check("in Settings, Appearance, Interface, between Animations and Cursor snow, in plain words",
      ap.index(">Animations<") < ap.index(">Smooth scrolling<") < ap.index(">Cursor snow<")
      and "The mouse wheel glides instead of jumping." in ap
      and '<Toggle checked={$smoothScroll} name="Smooth scrolling" onchange={(v) => smoothScroll.set(v)} />' in ap)
check("and in the command palette", 'smooth ? "Turn smooth scrolling off" : "Turn smooth scrolling on"' in cp)

print("\n== every preference the panel keeps, the app takes ==")
prefs = (ROOT / "app" / "web" / "routes" / "prefs_routes.py").read_text(encoding="utf-8")
allowed = set(re.findall(r'"(\w+)"', prefs.split("ALLOWED = {", 1)[1].split("}", 1)[0]))
remote = set(re.findall(r'persisted<[^>]*>\("(\w+)",[^\n]*?, true\)', stores))
check("each one the panel sends is one the app keeps", remote and remote <= allowed, ", ".join(sorted(remote - allowed)))
check("smooth scrolling among them", "smoothScroll" in allowed)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
