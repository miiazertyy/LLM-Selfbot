"""The Dashboard as one living surface, and settings that arrive with their tab.

  * the widgets sit on one sheet, divided by seams, with a highlight that
    flows from one to the next and a ripple when a message comes or goes
  * figures count up to their value and glow when it changes
  * opening a tab, sliders sweep to their value, on switches slide on, the
    wait chart grows up out of its axis, and a dropdown types its value in,
    all as their row drops in, not after
  * "Messages to read" is a slider, "Default" is not in italics, a switch's
    undo button never pushes the switch along, and Quiet hours lines up
  * the Memory tab's brain is drawn from the side
"""
import re
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
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== one surface, not a phone's home screen ==")
dash = read("pages/Dashboard.svelte")
widgets = read("lib/dashboard/widgets.ts")
frame = read("lib/dashboard/WidgetFrame.svelte")
check("where each widget sits is worked out in one place, and tested under Node",
      "export function placeOnSheet(" in widgets and "const placed = $derived(placeOnSheet(layout));" in dash)
check("the widgets share one sheet", '<div class="pool-bg glass"' in dash and 'class="dash-cell pool-cell' in dash)
check("and are no longer cards of their own", 'class="widget-frame glass' not in frame
      and not re.search(r'<section[^>]*\bglass\b', frame))
check("seams divide them: one above unless it starts the page, one beside the right half",
      ".pool-cell::before" in dash and ".pool-cell.is-top::before { display: none; }" in dash
      and ".pool-cell.is-right::after" in dash)
check("a lone half takes the whole row", "{wide ? 'lg:col-span-2' : ''}" in dash)

print("\n== it moves like something alive ==")
check("colour drifts slowly under everything", all(f"@keyframes pool-drift-{x}" in dash for x in "abc"))
check("a highlight flows from widget to widget, taking each one's size",
      "function measure(cell: HTMLElement)" in dash and "cell.offsetWidth" in dash
      and 'class:is-on={flow.on && !arranging}' in dash)
check("it jumps into place the first time rather than flying in from the corner",
      "snap: !flow.on" in dash and ".pool-drop.is-snap" in dash)
check("a widget growing under the pointer takes the highlight with it", "new ResizeObserver(" in dash
      and "if (hovered?.isConnected) measure(hovered);" in dash)
check("the pointer is followed without redrawing the page",
      'pool.style.setProperty("--mx"' in dash and 'pool.style.setProperty("--my"' in dash)
check("a message in or a reply out sends a ripple from the widget it concerns",
      'if (entry.level === "reply" || entry.level === "recv") pulse(entry.level);' in dash
      and '.pool-cell[data-type="${t}"]' in dash)
check("but not a storm of them: one at most every second or so, three at once",
      "if (now - lastPulse < 1200) return;" in dash and "ripples.slice(-2)" in dash)
check("the Animations switch stills all of it",
      ':global(:root[data-motion="off"]) .pool-blob' in dash and "!get(motionEnabled)" in dash.split("function pulse")[1][:200])

print("\n== figures count ==")
num = read("lib/dashboard/Num.svelte")
body = read("lib/dashboard/WidgetBody.svelte")
check("a figure counts up to its value, fast then slow",
      "new Tween(0, { duration: 1100, easing: quintOut })" in num)
check("and glows for a moment when it changes", "class:is-bumped={bumped}" in num and ".num.is-bumped" in num)
check("number formats are made once, not on every frame", "const formats = new Map<number, Intl.NumberFormat>()" in num)
check("the Dashboard's figures use it", "<Num value={ctx.today} />" in body and "<Num value={ctx.week} />" in body)
check("the figures sit in one strip with seams, not four boxes", '<div class="figs ' in body and ".figs > .fig" in body)
accw = read("lib/dashboard/AccountsWidget.svelte")
check("an account that is running glows from within", ".aw-card.is-live" in accw and "radial-gradient(" in accw)
check("one in trouble is marked along its edge", ".aw-card.is-bad" in accw)
logw = read("lib/dashboard/LogWidget.svelte")
check("the log fades out at its edges instead of sitting in a dark box", "mask-image: linear-gradient(180deg" in logw)

print("\n== sliders arrive like the dials ==")
arrive = read("lib/arrive.ts")
settings = read("pages/Settings.svelte")
check("a slider sweeps to its value as its row appears", "export function sweep(node: HTMLInputElement)" in arrive
      and "whenShown(node).then(" in arrive)
check("on the dials' curve", "1 - Math.pow(1 - t, 5)" in arrive)
check("one either side of zero sweeps out from zero", "min < 0 && max > 0 ? 0 : min" in arrive)
check("it never changes the setting, only what is drawn", "setValue" not in arrive and "node.value = String(target)" in arrive)
check("a hand on it ends the show at once", 'node.addEventListener("pointerdown", stop)' in arrive
      and 'node.addEventListener("keydown", stop)' in arrive)
check("left blank, or with Animations off, it stays put",
      'node.classList.contains("is-blank")' in arrive and "!get(motionEnabled)" in arrive)
check("every slider in Settings does it", settings.count("use:sweep") >= 2)
for rel in ("lib/components/ReactionEditor.svelte", "lib/components/Appearance.svelte"):
    check(f"{rel.split('/')[-1]} sliders do it too", "use:sweep" in read(rel))

print("\n== switches, the wait chart and dropdowns arrive too ==")
toggle = read("lib/components/Toggle.svelte")
check("an on switch starts off and slides on as its row appears",
      "whenShown(el).then(" in toggle and "arrived = true;" in toggle and ".tg.is-on:not(.is-arrived)" in toggle)
arrive_frames = toggle.split("@keyframes tg-arrive {")[1].split("\n  }\n")[0] if "@keyframes tg-arrive {" in toggle else ""
check("its own motion, not the click's quick slide: a snap into place, after its turn in a run of them",
      ".tg.is-on.is-arrived.is-arriving .tg-knob { animation: tg-arrive 0.5s calc(0.03s + var(--tg-wait, 0ms)) backwards; }" in toggle)
check("it hits the end, squashes against it 3px past where it rests, and springs back",
      "translateX(calc(var(--travel) + 3px)) scale(0.84, 1.08)" in arrive_frames
      and "100% { transform: translateX(var(--travel)) scale(1, 1); }" in arrive_frames)
check("pressed flat against the end, not poking out of the track: its right edge stays where it hit",
      # the knob's right edge, from its centre, at the hit (38%) and at the squash (48%): +1px at 1.06, +3px at 0.84
      abs((1 + 9 * 1.06) - (3 + 9 * 0.84)) < 0.1 and 3 + 9 * 0.84 - 9 < 3
      and "translateX(calc(var(--travel) + 1px)) scale(1.06, 0.97)" in arrive_frames)
check("no transform transition while it plays, or the keyframes would lose to it",
      "transform" not in toggle.split(".tg.is-arriving .tg-knob {")[1].split("}")[0])
check("a click during the arrival hands over to the click's slide",
      toggle.split("function toggle() {")[1].index("arriving = false;") < toggle.split("function toggle() {")[1].index("checked = !checked;"))
check("with Animations off, no keyframes either",
      ':global(:root[data-motion="off"]) .tg.is-arriving .tg-knob { transition: none; animation: none; }' in toggle)
check("the slow timing is in place before the switch goes on, and gone again for clicks",
      "arriving = true;" in toggle and "done = window.setTimeout(() => (arriving = false), 900 + ms);" in toggle)
check("with Animations off it is simply on", "if (!get(motionEnabled) || !checked) {" in toggle)
waits = read("lib/components/WaitTimes.svelte")
check("the wait chart grows up out of its axis, one wait after another",
      "whenShown(el).then(" in waits and "class:is-in={arrived}" in waits
      and ".wt:not(.is-in) .wt-stem" in waits and "calc(var(--i, 0) * 70ms)" in waits)
check("its heads rise by exactly the height of their stems", "--rise: ${BASE - w.y}px" in waits)
check("the slow rise is only for the arrival, hovering stays quick", ".wt.is-arriving .wt-end" in waits)
check("dragging is never slowed by it", ".wt.is-dragging .wt-rise" in waits)
select = read("lib/components/Select.svelte")
check("a dropdown types its value in, a letter at a time", "let typing = $state<number | null>(null);" in select
      and "whenShown(el).then(" in select and "{label.slice(0, typing)}<span class=\"sel-cursor\"></span>" in select)
check("each letter is there at once, as a typed one is, so the cursor sits right against it",
      "sel-letter" not in select and "margin-left: 0.5px;" in select)
check("a real text cursor: thin, in the text's colour, no glow",
      "width: 1.5px;" in select and "background: var(--color-ink);" in select.split(".sel-cursor {")[1][:300])
check("at a person's pace: uneven, a quick burst now and then, a beat after a space",
      "520 / label.length" in select and "Math.random() < 0.25" in select and 'label[typing - 1] === " "' in select)
check("the cursor rests a moment after the last letter before it goes", "timer = window.setTimeout(step, 240);" in select)
check("the cursor is its own thing, not the chevron's class (sharing it made the chevron a blinking bar)",
      '<span class="sel-cursor"></span>' in select and select.count("\n  .sel-caret {") == 1
      and 'class="sel-caret" aria-hidden' not in select)
check("nothing blinks, before or after", "@keyframes sel-blink" not in select and "infinite" not in select)
check("once the word is written the cursor is gone", "typing = null;          // done: the plain label, no cursor" in select)
check("a dropdown that goes away mid-word stops typing", "alive = false;" in select and "if (alive) timer" in select)
check("opening it, or the value changing, ends the typing", "async function openMenu() {\n    play(\"open\");\n    typing = null;" in select
      and "if (value !== typedFor)" in select)
check("screen readers hear the value, not the animation", '<span class="sr-only">{label}</span>' in select)
check("with Animations off it simply shows", "!get(motionEnabled)" in select)

print("\n== Settings fixes ==")
from app.web.schema import CONFIG_SCHEMA
field = next(f for f in CONFIG_SCHEMA if f["key"] == "bot.memory_summary.messages")
check("Messages to read has both ends set", field.get("min") == 5 and field.get("max") == 100)
check("and a whole number with both ends and no unit is a slider",
      '{:else if f.type === "int" && f.min != null && f.max != null && f.max - f.min <= 1000 && !unitOf(f)}' in settings)
css = (SRC / "app.css").read_text(encoding="utf-8").replace("\r\n", "\n")
blank = css.split(".slider-value.is-blank {")[1].split("}")[0]
check("\"Default\" beside a blank slider is not in italics", "italic" not in blank)
check("a switch's undo comes after the switch, so the switch never moves",
      "settings-undo" in settings and ".settings-row.is-switch .settings-undo {\n  order: 2;" in css)
check("Quiet hours, while off, lines up with the other switches",
      'f.key === "snapchat.quiet_hours" && !value(f)' in settings)

print("\n== the brain ==")
icon = read("lib/components/Icon.svelte")
brain = icon.split("    memory:\n")[1].split("\n")[0]
check("drawn from the side, with the stem and the folds", "A brain from the side" in icon
      and brain.count("M") == 9 and "Z" in brain)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
