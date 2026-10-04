"""The right-click menu everywhere, tabs that fill in from the top, the new Add
an account dialog, the app's own scrollbars, and Discord's own logo.

  * one right-click menu for the whole app: a page offers items with use:menu,
    and text boxes, selected text, links and pictures get theirs anywhere
  * it animates open from the pointer, fades closed, flips at the edges, and
    works from the keyboard
  * opening a tab, its blocks drop into place top to bottom, following the
    app's Animations switch (not Windows' "reduce motion", which this PC has on)
  * no element brings back the system scrollbar with scrollbar-width
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


print("== one right-click menu ==")
core = read("lib/contextmenu.ts")
menu = read("lib/components/GlobalMenu.svelte")
check("a page offers items with use:menu", "export function menu(node: HTMLElement, provider: MenuProvider)" in core)
check("asked at the moment of the click, so they say what is true then", "return p(e);" in core)
check("only the nearest element with a menu is asked", "for (let el: Element | null = target; el; el = el.parentElement)" in core)
check("empty entries and stray lines are tidied away", "export function tidy(" in core and 'e === "sep"' in core)
check("the menu listens for right-clicks everywhere", 'window.addEventListener("contextmenu", onContext)' in menu)
check("a page that opened its own menu is left alone", "e.defaultPrevented" in menu)
check("and Shift gives the browser's own", "e.shiftKey" in menu)

print("\n== what it offers by itself ==")
check("text boxes get Undo, Cut, Copy, Paste and Select all",
      all(f'label: "{w}"' in menu for w in ("Undo", "Cut", "Copy", "Paste", "Select all")))
check("with their shortcuts shown", '"Ctrl Z"' in menu and '"Ctrl V"' in menu)
check("a password can be pasted into but not copied out", "secret || !sel" in menu)
check("paste reads the clipboard through the desktop app, without the browser's permission box",
      "read_clipboard_text" in core and "navigator.clipboard.readText" in core)
check("selected text can be copied or searched for", "Search for “" in menu and "searchFor(" in menu)
check("selected text comes first", "entries = [...picked, " in menu)
check("links can be opened and copied", '"Open link"' in menu and '"Copy link"' in menu)
check("pictures can be copied and saved, but not little icons", '"Copy image"' in menu and "img.width >= 40" in menu)
check("bare background gets Search, Big Picture and Reload", '"Search"' in menu and '"Big Picture Mode"' in menu
      and '"Reload"' in menu)
check("and in Big Picture, the way out instead", '"Leave Big Picture"' in menu)

print("\n== how it moves ==")
check("it springs open from the pointer", "@keyframes gm-in" in menu and "var(--jelly)" in menu)
check("the items settle in one after another", "animation-delay: calc(var(--i) * 16ms" in menu)
check("it fades closed, drawn until the fade ends", "gm-out" in menu and "LEAVE_MS" in menu)
check("near an edge it opens the other way, from that corner", 'ox = "right"' in menu and 'oy = "bottom"' in menu)
check("measured before it shows, so it never flashes in the wrong place", "visibility: hidden" in menu and "is-ready" in menu)
check("the Animations switch turns all of it off", ':root[data-motion="off"]) .gm' in menu)
check("keyboard: arrows, Enter, Escape, Home, End and a letter to jump",
      all(k in menu for k in ('"ArrowDown"', '"Enter"', '"Escape"', '"Home"', "startsWith(k.toLowerCase())")))
check("the Menu key opens it on whatever has the focus", 'pointerType === ""' in menu)
check("clicking an item keeps the text box's selection", "onmousedown={(e) => e.preventDefault()}" in menu)
check("it is a real menu to screen readers", 'role="menu"' in menu and 'role="menuitem"' in menu
      and "aria-activedescendant" in menu)

print("\n== the pages that offer their own ==")
for rel, marker in [
    ("lib/accounts/AccountCard.svelte", "use:contextMenu={cardMenu}"),
    ("pages/Chats.svelte", "use:contextMenu={() => rowMenu(u)}"),
    ("pages/Chats.svelte", "use:contextMenu={(e) => messageMenu(d.m, e)}"),
    ("pages/Memory.svelte", "use:contextMenu={() => personMenu(u)}"),
    ("pages/Memory.svelte", "factMenu(key, value)"),
    ("pages/Settings.svelte", "use:contextMenu={() => rowMenu(f, far)}"),
    ("pages/Pictures.svelte", "openMenuAt(e, ["),
    ("pages/Logs.svelte", "openMenuAt(e, ["),
    ("lib/dashboard/LogWidget.svelte", "onmenu={(e) => lineMenu(e, r)}"),
    ("lib/components/Avatar.svelte", "openMenuAt(e, ["),
]:
    check(f"{rel.split('/')[-1]}: {marker[:40]}", marker in read(rel))
card = read("lib/accounts/AccountCard.svelte")
check("an account offers Start or Restart by what it is doing", '"Restart"' in card and '"Start"' in card
      and "disabled: !cond.canStart" in card)
check("removing one is marked as dangerous", 'label: "Remove account", icon: "trash", danger: true' in card)
chats = read("pages/Chats.svelte")
check("someone waiting can be answered now, or not at all", '"Reply now"' in chats and '"Don\'t reply"' in chats)
settings = read("pages/Settings.svelte")
check("a setting can have its unsaved change undone or go back to its default",
      '"Undo this change"' in settings and '"Reset to default"' in settings)

print("\n== saving a picture, for real ==")
desktop = (ROOT / "app" / "desktop.py").read_text(encoding="utf-8")
window = read("lib/window.ts")
check("the desktop app saves through its own Save dialog", "def save_binary_file(self, filename, data_b64)" in desktop)
check("the page sends the picture there", "api.save_binary_file(filename, b64)" in window)
check("and names it with the extension it really has", '"image/png": "png"' in window)
check("the clipboard is read through the desktop app", "def read_clipboard_text(self)" in desktop)
import app.desktop as d
got = d.WindowApi().read_clipboard_text()
check("which answers with text, or None where it cannot", got is None or isinstance(got, str))

print("\n== opening a tab ==")
cascade = read("lib/cascade.ts")
app = read("App.svelte")
css = read("app.css")
check("the page's blocks drop in, top to bottom", "use:cascade={route}" in app
      and "a.r.top - b.r.top" in cascade)
check("from a little above, with the app's spring", 'translate3d(0, -12px, 0)' in cascade and '"--spring"' in cascade)
check("a Settings section does it too", "use:cascade={path}" in settings)
check("plain wrappers are opened up, cards are kept whole", "function plain(" in cascade and "plain(el)" in cascade)
check("a block that has moved is not moved again from inside", "seen.has(el)) continue" in cascade)
check("late content joins the wave (new blocks only, not what changes inside ones already moved)",
      "observer = new MutationObserver((records) =>" in cascade and "!inside(n)" in cascade and "WINDOW_MS" in cascade)
check("nothing below the fold, nothing left behind", "r.top < innerHeight" in cascade and 'fill: "backwards"' in cascade)
check("it follows the app's Animations switch", "!get(motionEnabled)" in cascade)
check("and not the system's reduce-motion, which is on here and would have stopped it",
      "prefers-reduced-motion" not in cascade)
check("the page itself only fades now, so nothing moves twice",
      "translate" not in css.split("@keyframes page-in")[1].split("}")[0] + css.split("@keyframes page-in")[1].split("}")[1])

print("\n== the tab opens first, then what is in it moves ==")
check("a block is marked while it is landing, and unmarked when it has",
      'el.dataset.arriving = ""' in cascade and "delete el.dataset.arriving" in cascade)
check("what is inside a landing block waits, held on its first frame",
      "[data-arriving] *" in css and "animation-play-state: paused !important" in css)
check("entrances of their own are not played on top of the wave",
      'const DOUBLES = ".card-enter, .stagger > *, .pop"' in cascade and 'x.style.animation = "none"' in cascade)
check("only on what is there as the tab opens, so a card added later still comes in",
      "el.querySelectorAll<HTMLElement>(DOUBLES)" in cascade)
check("motion driven from code can start as its block appears", "export function whenShown(" in cascade)
dial = read("lib/components/Dial.svelte")
hours = read("lib/components/HourRange.svelte")
for name, src in (("dials", dial), ("the night clock", hours)):
    check(f"{name} sweep in with the tab's opening, as their block appears (and not at all off screen)",
          "whenShown(el).then(() => onScreen(el))" in src and "shown = true;" in src and "if (!shown) return;" in src)
    check(f"{name} do not wait for the block to land", "afterLanding" not in src)

print("\n== the clocks ease out ==")
waits = read("lib/components/WaitTimes.svelte")
for name, src in (("dials", dial), ("the night clock", hours), ("the wait chart", waits)):
    check(f"{name}: quick off the mark, a long soft finish",
          'import { quintOut } from "svelte/easing"' in src and "easing: quintOut" in src and "easing: cubicOut" not in src)
check("the first sweep is the slow one, changes after it a little quicker",
      "swept ? 800 : 1100" in dial and "swept ? 800 : 1100" in hours)

print("\n== sliders, drawn like the dials ==")
sl = css.split("/* ── Sliders")[1].split("/* A stat tile")[0]
check("a thick groove, like a dial's track", "--track: 10px" in sl and "height: var(--track)" in sl)
check("filled with the dials' gradient up to the value",
      "var(--color-accent-2) var(--from, 0%)" in sl and "var(--color-accent) var(--fill, 50%)" in sl)
check("with quarter marks, like a gauge's ticks", "calc(25% - 1px)" in sl and "calc(75% + 1px)" in sl)
check("the knob is a dial's hand: a dark disc, a coloured ring, a dot",
      "border: 3px solid var(--color-accent)" in sl and "radial-gradient(circle, var(--color-accent) 0 2.6px, rgb(20 22 34)" in sl)
check("glowing like the dials' arcs, with a halo when pointed at", "0 0 14px color-mix" in sl
      and ".slider:hover::-webkit-slider-thumb" in sl and "0 0 0 6px" in sl)
check("left blank, no knob in an odd place: an empty track", ".slider.is-blank::-webkit-slider-thumb {\n  opacity: 0;" in sl)
check("and a plain Default button to go back to it", ".slider-clear {" in sl
      and '><Icon name="undo" size={11} />Default</button>' in read("pages/Settings.svelte"))
check("Firefox gets the same", ".slider::-moz-range-progress" in sl and "linear-gradient(90deg, var(--color-accent-2), var(--color-accent))" in sl)
check("the number beside it is a pill that lights when it changes",
      ".slider-value.is-bumped" in sl and "border-radius: 8px" in sl)

print("\n== adding an account ==")
acc = read("pages/Accounts.svelte")
seg = read("lib/components/Segmented.svelte")
check("the platform shows as itself: its mark on its colour", "DISCORD_MARK : SNAPCHAT_GHOST" in acc and "aa-mark" in acc)
check("which springs in, and turns when the platform changes", "{#key editPlatform}" in acc and "@keyframes aa-mark-in" in acc)
check("the choices are one control with a sliding pill", "<Segmented" in acc and "transform: translateX(calc(var(--at) * 100%))" in seg)
check("each platform brings its colour to it", 'tone: "#5865f2"' in acc and 'tone: "#fffc00"' in acc)
check("signing in shows its three steps, lit as they happen", "aa-steps" in acc and "loginState === 'waiting'" in acc)
check("the proxy folds away until wanted", "showProxy" in acc and "aa-more" in acc)
check("starting it straight away is a switch", '<Toggle size="sm" bind:checked={startNow}' in acc)
check("the old checkbox is gone", 'type="checkbox" class="accent-accent" bind:checked={startNow}' not in acc)

print("\n== scrollbars and logos ==")
offenders = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.svelte")
             if "scrollbar-width: thin" in p.read_text(encoding="utf-8")]
check("no element brings back the system scrollbar", not offenders, ", ".join(offenders))
check("Firefox, which has no styled scrollbars, gets thin ones instead",
      "@supports not selector(::-webkit-scrollbar)" in css)
icon = read("lib/components/Icon.svelte")
check("Discord's icon is its own logo", "discord: DISCORD_MARK," in icon and '"discord"' in icon.split("FILLED = new Set(")[1][:60])
check("the Settings tab for Discord shows it", 'name: "Discord",\n    icon: "discord",' in read("lib/settingsmap.ts").replace("\r\n", "\n"))

print("\n== dropdowns you can read ==")
sel = read("lib/components/Select.svelte")
check("the list is drawn at the end of the page, where no row below can paint over it",
      "use:portal" in sel and "document.body.appendChild(node)" in sel and "position: fixed;" in sel
      and "z-index: 1000;" in sel)
check("placed under its box, and a click in it is still a click in the dropdown",
      "top: r.bottom + 6, bottom: window.innerHeight - r.top + 6" in sel and "menuEl.contains(t)" in sel)
check("the glass of menus and lists filled enough to read over anything", "--float-fill: 74%;" in read("app.css")
      and "--float-fill: 88%;" in read("app.css"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
