"""The app's sounds: clicks, ticks and chimes, and a speaker to turn them off.

Every button clicks as it is pressed, a switch flips with a two-part click
that rises or falls, a choice lands with a glassy click, every mark a clock's
hand passes and every notch of a number tape is a detent, and a notice
chimes by its kind. They are made on the spot (lib/uisound.ts, no files), and
go through a soft dark room for the dreamy feel the rest of the app has.

The speaker beside Big Picture, top right, turns them all off, Big Picture's
own included, and is remembered with the other panel preferences.

Each sound is also rendered offline and measured: audible, never clipping,
the clicks short, the chimes ringing on, the notices above the clicks.
"""
import json
import subprocess
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


snd = read("lib/uisound.ts")
print("== the sounds ==")
NAMES = ("tap", "up", "tick", "on", "off", "select", "open", "menu", "ok", "info", "err", "send", "receive", "delete", "undo")
# Things moving into place as a tab opens, and dragging.
ARRIVING = ("wind", "slide", "rise", "done", "key", "land", "pluck", "zip", "seat", "medal", "settle", "glint", "grow")
DRAGGING = ("lift", "slot", "drop", "grab", "release", "hover")
NEW = ARRIVING + DRAGGING
check("each one has a recipe", all(f'case "{n}":' in snd for n in NAMES + NEW))
check("and a least gap between two", all(f" {n}: " in snd[snd.index("const GAP"):snd.index("const booked")] for n in NAMES + NEW))
check("a tab opening sets off many at once: each quieter than the one before, never below two fifths",
      "const ARRIVING = new Set<UISound>([\"wind\", \"slide\", \"rise\", \"done\", \"key\", \"land\", \"pluck\", \"zip\", "
      "\"seat\", \"medal\", \"settle\", \"glint\",\n  \"grow\"]);" in snd
      and "level = Math.max(0.4, 1 / (1 + 0.08 * arrivals.length));" in snd and "peak * level" in snd)
check("notes picked from a pentatonic, so any run of them is a tune: a chart's bars, a domino of switches, Appearance's glints",
      "const PENTA = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24];" in snd and snd.count("PENTA[Math.round(") == 4)
check("the switches' domino step is above slide's least gap, or every other one would be lost",
      "slide: 30," in snd and "const STEP = 40;" in read("lib/components/Toggle.svelte"))
check("measured as heard: after the compressor has settled, as it has at the speakers",
      "lead = settled ? RENDER_LEAD : 0;" in snd and "a.currentTime + lead + at" in snd)
check("made on the spot: no files", "createOscillator" in snd and "createBufferSource" in snd and ".mp3" not in snd
      and ".wav" not in snd)
check("clicks are noise through a narrow band, chimes have a bell partial and a detuned twin",
      'band.type = "bandpass"' in snd and "freq * 2.76" in snd and "detune: 7" in snd)
check("all of it through a soft, dark room", "createConvolver()" in snd and 'dark.type = "lowpass"' in snd)
check("never a burst: each has a least gap between two, kept between when they are heard (one can be booked ahead)",
      "const GAP: Record<UISound, number>" in snd
      and "if (times.some((t) => Math.abs(t - when) < GAP[name])) return;" in snd
      and "lead = Math.max(0, when - performance.now()) / 1000;" in snd)
check("a run asked for in one go counts from one moment: the first sound waking the card does not push the rest late",
      "const now = askedAt();" in snd and "queueMicrotask(() => (asked = 0));" in snd)
check("the sound card is woken as the app starts, not in the middle of the first tab's opening",
      "requestIdleCallback(() => void audio(), { timeout: 300 })" in snd)
check("nothing is made while they are off", "if (!get(uiSound)) return false;" in snd)

print("\n== where they are heard ==")
check("buttons click as they are pressed, the keyboard's too", 'document.addEventListener("pointerdown"' in snd
      and 'e.key !== "Enter" && e.key !== " "' in snd)
check("and click back up as they are let go, lighter and higher, by hand or by key",
      snd.count('play("up");') == 2 and 'document.addEventListener("pointerup", (e) => {\n    if (!pressed' in snd
      and 'document.addEventListener("keyup"' in snd and 'case "up":' in snd)
check("a press that was cancelled has no release", 'document.addEventListener("pointercancel", () => (pressed = false)' in snd)
app_src = read("App.svelte")
app_css = read("app.css")
check("the speaker opens out into a thin volume bar under the pointer, a line across its middle where the sounds were made",
      'class="vol-slider" min="0" max="2" step="0.05" value={$uiVolume} data-default="1"' in app_src
      and 'class="vol-mid"' in app_src and ".vol.is-open .vol-track { width: var(--vol-w);" in app_css)
check("a bar, not a knob, and a thin one: the fill's end says where it is",
      ".vol-slider::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 0; height: 0; }" in app_css
      and "height: 2.5px;" in app_css.split(".vol-slider::-webkit-slider-runnable-track {", 1)[1][:60]
      and "width: 1.5px;" in app_css.split(".vol-mid {", 1)[1][:120])
check("pulled out on a soft spring, the level pouring in behind it, the middle line drawn in after, a slide heard",
      "@property --vol-shown" in app_css and ".vol.is-open .vol-slider {\n  --vol-shown: var(--fill, 50%);" in app_css
      and "width 0.46s cubic-bezier(0.22, 1.25, 0.36, 1)" in app_css and ".vol.is-open .vol-mid {" in app_css
      and 'playSound("slide", { p: 0.62, level: 0.32 })' in app_src
      and ".vol.is-dragging .vol-slider { transition: none; }" in app_css and "class:is-dragging={volDrag}" in app_src)
check("it stays open through a drag that strays off it, and from the keyboard",
      "const volOpen = $derived(volHover || volKey || volDrag);" in app_src and "onpointerdown={grabVolume}" in app_src
      and 'matches(":focus-visible")' in app_src)
check("the header makes room as it opens, so the loading mark beside the window buttons moves along, not under it",
      "class:vol-open={desktop && volOpen}" in app_src
      and ".app-header.has-chrome.vol-open { padding-right: calc(176px + 78px); }" in app_css
      and "--vol-w: 78px;" in app_css)
check("the sounds follow it at once, eased so a drag has no clicks; measured renders keep their own level",
      "liveGraph.out.gain.setTargetAtTime(masterFor(v), live.currentTime, 0.015);" in snd and "const MASTER = 0.6;" in snd
      and 'export const uiVolume = persisted<number>("uiVolume", 1);' in read("lib/stores.ts"))
check("moving it while muted turns the sounds back on", "if (!$uiSound && v > 0) uiSound.set(true);" in app_src)
check("a bar's note rises with it as it grows, further the taller it is, and rings as it lands",
      'case "grow": {' in snd and "glide: to" in snd and "PENTA[Math.round(Math.min(1, Math.max(0, p)) * 8)]" in snd)
check("the medals shine without a ting: the three at the end of the opening were not liked",
      "play(" not in read("lib/components/RankBadge.svelte"))
check("a slider ticks, a checkbox flips", 'document.addEventListener("input"' in snd and 'play(t.checked ? "on" : "off")' in snd)
check("a slider by hand: taken hold of and let go, a detent per notch passed (not per pixel), firmer at zero or "
      "its default, a knock at either end, every press from the keyboard",
      'play("grab");' in snd and 'play("release");' in snd and "const notch = Math.max(Number(t.step) || 0, (hi - lo) / 20);" in snd
      and "t.dataset.default" in snd and 'return play("seat", { p, strong: true });' in snd and "held !== t ||" in snd)
check("Settings' sliders say where their default is", read("pages/Settings.svelte").count(
      'data-default={typeof f.default === "number" ? f.default : undefined}') == 2)
check("a notice chimes by its kind, once however many come together", "toasts.subscribe(" in snd
      and 'play(kind === "ok" ? "ok" : kind === "err" ? "err" : "info")' in snd)
check("a control with its own sound is not also a button click", "[data-sound='self'], [data-sound='none']" in snd)
for rel, needle in (("lib/components/Toggle.svelte", 'play(checked ? "on" : "off");'),
                    ("lib/components/Segmented.svelte", 'play("select");'),
                    ("lib/components/Select.svelte", 'play("open");'),
                    ("lib/components/Dial.svelte", 'play("tick", { p: k / 50, strong: MARKS[k].major });'),
                    ("lib/components/HourRange.svelte", 'play("tick", { p: h / 24, strong: MARKS[h].major });'),
                    ("lib/components/Tape.svelte", 'play("tick");'),
                    ("lib/components/UndoBar.svelte", 'play("undo");'),
                    ("pages/Chats.svelte", 'playSound("receive");'),
                    ("lib/contextmenu.ts", 'play("menu");'),
                    ("lib/components/GlobalMenu.svelte", 'play("select");')):
    text = read(rel)
    check(f"{rel.split('/')[-1]}", needle in text)
print("\n== things arriving, as a tab opens ==")
for rel, needle, what in (
        ("lib/components/Toggle.svelte", 'onanimationstart={knobArrives}', "a switch pulled across and landing, heard with its knob's own animation"),
        ("lib/components/Dial.svelte", 'play("wind", { p: k / 50, strong: MARKS[k].major })', "a dial winding round to its value"),
        ("lib/components/HourRange.svelte", 'play("wind", { p: h / 24, strong: MARKS[h].major })', "the night sweeping in, an hour at a time"),
        ("lib/components/Tape.svelte", 'play("wind", { p: Math.min(1', "a number tape gliding in, a notch at a time"),
        ("lib/arrive.ts", 'play("wind", { p: pctOf(v) / 100, strong: k % 5 === 0 })', "a slider sweeping in"),
        ("lib/arrive.ts", 'play("zip", { p: pctOf(target) / 100 });', "setting off with a breath of air"),
        ("lib/arrive.ts", 'play("seat", { p: pctOf(target) / 100 });', "and a tock as it settles at its value"),
        ("lib/growin.ts", "play(sound, { p: h / max, level: soft, delay: i * stagger + 16 })",
         "a chart's bars growing up, each a note by its height, booked with its bar"),
        ("lib/accounts/WeekBars.svelte", '}, STAGGER, 1, "grow");', "an account's week, each note rising with its bar"),
        ("lib/dashboard/Spark.svelte", '}, stagger, 0.55, "grow");', "the Dashboard's little trends, the same"),
        ("lib/components/StatChart.svelte", 'kind === "bars" ? "pluck" : "wind"', "a chart's bars, or its line drawn a point at a time"),
        ("lib/dashboard/Num.svelte", 'play("wind", { p: c / target, level: 0.8 });', "a figure counting up like an odometer"),
        ("lib/dashboard/Num.svelte", 'play("seat", { p: 0.6, level: 0.7 });', "and settling"),
        ("lib/dashboard/WidgetBody.svelte", "use:arriving={{ heights: () => top.map((x: any) => x.count), stagger: 50, level: 0.7 }}",
         "the leaderboard's rows sliding in, each a note"),
        ("lib/cascade.ts", 'if (landed) play("settle");', "a Dashboard widget set down as it lands"),
        ("lib/feel.ts", 'play(on ? "select" : "off")', "a chip picked or let go, with its pop"),
        ("lib/components/WaitTimes.svelte", 'play("rise", { p: n > 1 ? i / (n - 1) : 0.5 })', "each wait growing up into place"),
        ("lib/components/SnapchatSetup.svelte", 'play("rise", { p: steps.indexOf(s) / 3 })', "the Snapchat bar filling, a note with each part as it lights"),
        ("lib/components/SnapchatSetup.svelte", 'if (heard && !quiet) play("done");', "and a soft bell with the finish, as it is seen"),
        ("lib/components/LanguagePicker.svelte", 'play("land")', "a language's flag landing"),
        ("lib/components/TypingSpeed.svelte", 'play("key", { strong: key === "space", level: 0.8 })', "the typing speed's keys, softly"),
        ("lib/components/TypingSpeed.svelte", 'play("send", { level: 0.4 })', "and its message sent off"),
        ("lib/components/Select.svelte", 'play("key")', "a dropdown's value typing itself in")):
    check(what, needle in read(rel))
check("sounds that go with a held animation wait for its block to land", "export function afterLanding(" in read("lib/cascade.ts")
      and read("lib/components/SnapchatSetup.svelte").count("afterLanding(") == 2)
check("only what is on screen is heard arriving", "heardIn = seen;" in read("lib/components/Toggle.svelte")
      and "if (heardIn) play(\"slide\", { p: Math.min(k, 7) / 7, delay: ms + 30 });" in read("lib/components/Toggle.svelte")
      and "winding = seen" in read("lib/components/Tape.svelte") and "if (!seen || !get(motionEnabled)) return start(false);"
      in read("lib/growin.ts"))
check("switches arriving together go on one after another, in reading order, each a note higher",
      "function domino(el: Element, go: (k: number, wait: number) => void)" in read("lib/components/Toggle.svelte")
      and ".sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left);" in read("lib/components/Toggle.svelte"))
check("a Dashboard sheet does not set everything in it going at once: a second wave down each landed block",
      "const wait = Math.max(0, Math.min(MAX_WAIT, down * PER_PX));" in read("lib/growin.ts")
      and "data-rise\n        data-land-sound" in read("pages/Dashboard.svelte"))
check("the switch's sound starts with its knob, which waits for its row to land, not as the row starts to drop",
      'e.animationName.endsWith("tg-arrive")' in read("lib/components/Toggle.svelte"))
check("the Snapchat card: what is seen and heard are one timeline, begun once the card and its steps have landed",
      "afterLanding(el, () => afterLanding(list," in read("lib/components/SnapchatSetup.svelte")
      and "lit = { ...lit, [s.name]: true };" in read("lib/components/SnapchatSetup.svelte"))

print("\n== dragging ==")
for rel in ("lib/components/ModelsPanel.svelte", "lib/components/ModelPicker.svelte", "pages/Dashboard.svelte"):
    text = read(rel)
    check(f"{rel.split('/')[-1]}: lifted, a click at each place it passes, put down",
          'play("lift")' in text and 'play("slot", { p:' in text and 'play("drop")' in text)
for rel, hover in (("pages/Pictures.svelte", 'play("hover")'), ("lib/components/Importer.svelte", 'play("hover")'),
                   ("pages/Chats.svelte", 'playSound("hover")')):
    text = read(rel)
    check(f"{rel.split('/')[-1]}: a file held over it, and let go", hover in text and ("drop\")" in text))
for rel in ("lib/components/Dial.svelte", "lib/components/HourRange.svelte", "lib/components/Tape.svelte",
            "lib/components/WaitTimes.svelte", "lib/scrub.ts", "lib/hscroll.ts", "lib/components/VideoPlayer.svelte"):
    text = read(rel)
    check(f"{rel.split('/')[-1]}: taken hold of, and let go", 'play("grab")' in text and 'play("release")' in text)
check("a row's grip makes its own sound, not a button's tap as well",
      'title="Drag to change the order" data-sound="self"' in read("lib/components/ModelsPanel.svelte"))

check("the right-click menu pops as it opens, and its items do not also click as buttons",
      'class="gm float-surface"\n    data-sound="self"' in read("lib/components/GlobalMenu.svelte"))
check("switches and lists say they have their own", 'role="switch"\n  data-sound="self"' in read("lib/components/Toggle.svelte")
      and 'data-sound="self"' in read("lib/components/Select.svelte"))
check("the clocks tick with Animations off too, not inside the pluck that stops then",
      "play(" not in read("lib/pluck.ts"))
check("installed once for the whole app", "onMount(installUISounds);" in read("App.svelte"))

print("\n== the speaker ==")
app = read("App.svelte")
check("top right beside Big Picture, in the window's buttons and in a browser's header",
      app.count("{@render speaker()}") == 2 and "{#snippet speaker()}" in app)
check("it says what it does, and which way it is", 'aria-pressed={$uiSound}' in app and '"speaker" : "speakerOff"' in app)
check("off says goodbye with a click before going quiet, on says hello",
      'playSound("off");\n      uiSound.set(false);' in app and 'uiSound.set(true);\n      playSound("on");' in app)
check("the header leaves room for it beside the window buttons", "pr-[176px]" in app)
stores = read("lib/stores.ts")
check("remembered, on the server too", 'export const uiSound = persisted<boolean>("uiSound", true, true);' in stores)
prefs = (ROOT / "app" / "web" / "routes" / "prefs_routes.py").read_text(encoding="utf-8")
check("which keeps it, and Big Picture's own switch, which it never did", '"uiSound", "bigPictureSound"' in prefs)
bp = read("lib/bigpicture/sounds.ts")
check("off silences Big Picture's sounds too", bp.count("!get(uiSound)") == 2)

print("\n== how they measure ==")
proc = subprocess.run(["node", str(ROOT / "tests" / "sounds_measure.mjs")], capture_output=True, text=True,
                      timeout=180, encoding="utf-8", errors="replace")
try:
    m = json.loads(proc.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    m = {"error": proc.stdout[-300:] + proc.stderr[-300:]}
if "skip" in m:
    print(f"  (skipped: {m['skip']})")
elif "error" in m:
    check("the sounds can be rendered", False, m["error"])
else:
    check("every one rendered", all(n in m for n in NAMES), str(sorted(m)))
    check("every one heard: none quieter than -36 dB", all(m[n]["median"] > -36 for n in NAMES),
          str({n: m[n]["median"] for n in NAMES}))
    check("none near clipping: the loudest of five tries under -8 dB", all(m[n]["loudest"] < -8 for n in NAMES),
          str({n: m[n]["loudest"] for n in NAMES}))
    check("a click and a detent are over in a few tens of milliseconds",
          m["tap"]["tailMs"] < 60 and m["tick"]["tailMs"] < 40, f'{m["tap"]["tailMs"]} {m["tick"]["tailMs"]}')
    check("a chime rings on in the room", all(m[n]["tailMs"] > 800 for n in ("ok", "info", "receive")),
          str({n: m[n]["tailMs"] for n in ("ok", "info", "receive")}))
    check("a notice stands above the clicks", m["ok"]["median"] > max(m[n]["median"] for n in ("tap", "tick", "on", "off", "select")))
    check("a detent is softer than a press: a drag is many of them", m["tick"]["median"] < m["tap"]["median"])
    check("the new ones rendered", all(n in m for n in NEW), str(sorted(m)))
    heard = {n: m[n]["heard"] for n in NAMES + NEW if n in m}
    check("as heard, none near clipping", all(m[n]["heardLoudest"] < -3 for n in heard),
          str({n: m[n]["heardLoudest"] for n in heard}))
    check("as heard, every new one there to hear", all(heard[n] > -30 for n in NEW), str({n: heard[n] for n in NEW}))
    check("what arrives by itself is quieter than a hand on a control: below a detent, a click and a switch",
          all(heard[n] < min(heard["tick"], heard["tap"], heard["on"]) for n in ARRIVING), str({n: heard[n] for n in ARRIVING}))
    check("dragging is no louder than a press", all(heard[n] <= heard["tap"] + 1 for n in DRAGGING),
          str({n: heard[n] for n in DRAGGING}))
    check("a row passing a place, many in a drag, softer than the detent of a slider",
          heard["slot"] < heard["tick"], f'{heard["slot"]} {heard["tick"]}')

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
