"""Settings, this round: steadier clocks, a wait chart that is easier to read,
counts on a tape, a save bar worth looking at, examples beside the switches,
and a Telegram page that connects the bot for you.

  * the switches slide in a moment sooner as a tab opens
  * the marks round every clock stretch as a hand passes them, the words in
    the middle keep their size, the night clock's times fit inside it and
    its "now" hand is gone, and nothing round a clock resizes as it moves
  * each wait's chance is written in its head, not in pills above it; the
    empty server table is one small line with the DM waits faint in it
  * counts with no top are a tape to pull, not a box
  * the save bar counts, names what changed, saves with Ctrl+S and says so
  * a switch row has a little example of what it does, played on a loop
  * the Telegram page: its steps, its checks, its commands, its alerts
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


settings = read("pages/Settings.svelte")
css = read("app.css")

print("== the switches, a little sooner ==")
toggle = read("lib/components/Toggle.svelte")
check("the snap starts 30ms after the row lands (and its turn in a run of them), not 80",
      "animation: tg-arrive 0.5s calc(0.03s + var(--tg-wait, 0ms)) backwards;" in toggle
      and "0.08s" not in toggle.split("/* Arriving")[1].split(":global")[0])

print("\n== the clocks ==")
pluck = read("lib/pluck.ts")
dial = read("lib/components/Dial.svelte")
hours = read("lib/components/HourRange.svelte")
check("a mark stretches out from its inner end and springs back, lit",
      "export function pluck(" in pluck and "scale(${stretch})" in pluck and "color-mix(in srgb, ${accentNow()} 65%, white)" in pluck
      and 'line.style.transformOrigin = `${a.x.toFixed(2)}px ${a.y.toFixed(2)}px`;' in pluck
      and 'line.setAttribute("vector-effect", "non-scaling-stroke");' in pluck)
check("and only with Animations on", "!get(motionEnabled)" in pluck)
for name, src, every in (("the time dials", dial, "1 / 50"), ("the hour clocks", hours, ", 1)")):
    check(f"{name} pluck the marks their hands pass",
          "passed(" in src and every in src and "pluck(plucks, MARKS[" in src and "<g bind:this={plucks}" in src)
    check(f"{name}' marks are a few paths, not one element each",
          "marksPath(MARKS.filter((m) => !m.major))" in src and "{#each TICKS" not in src)
check("the dial's words are not popped again at every step of a drag", "td-pop" not in dial and "{#key said}" not in dial)
check("nor flipped to a smaller size past nine letters", "is-long" not in dial and "said.length > 9" not in dial)
check("a line too wide for the middle is drawn smaller, smoothly, measured after layout",
      "function fit(" in dial and "new ResizeObserver(" in dial and "offsetWidth" not in dial
      and "transform: scale(var(--fit, 1));" in dial)
check("a range in two units is two lines", 'said.indexOf(" – ")' in dial and "<i>to</i>" in dial)
check("the night clock's 'now' hand is gone", "hr-now" not in hours and "nowHour" not in hours)
check("its two times sit one over the other, each by its moon or sun",
      'class="hr-row is-moon"' in hours and 'class="hr-row is-sun"' in hours and "flex-direction: column" in hours.split(".hr-big {")[1][:200])
check("and are not re-popped at every hour of a drag", "hr-pop" not in hours)
check("the clock and the line under it have a width of their own, so the row does not move",
      ".hr-wrap { display: flex; width: 200px;" in hours)

print("\n== the wait chart ==")
waits = read("lib/components/WaitTimes.svelte")
check("each chance is written in its head", 'class="wt-num"' in waits and "const HEAD = 12.5;" in waits)
check("no more pills lifted above the heads", "lifts" not in waits and "wt-pct > button" not in waits)
check("a head never sits down on the axis", "const LOWEST = BASE - HEAD - 3;" in waits and "Math.min(LOWEST, yOf(share))" in waits)
check("a drag moves a head from where it was taken hold of",
      "timeAt(from.hx + p.x - from.px)" in waits and "from.share + ((from.py - p.y) / (BASE - TOP)) * tallest" in waits)
check("a click on a head, not a drag, types its chance",
      "const clicked = !from.moved && hold.part === \"all\";" in waits and 'if (clicked) edit(k, "share");' in waits)
check("a shaky click is still a click", "Math.hypot(p.x - from.px, p.y - from.py) < 3" in waits)
check("the empty server table shows the DM waits, faintly, in one small line",
      "fallback" in waits and 'class="wt-ghost"' in waits and ".wt-empty svg.wt-ghost {" in waits
      and "display: inline-flex;" in waits.split(".wt-empty {")[1][:200])
check("and Settings gives it only the room it needs", "followsDms" in settings
      and 'byKey["bot.batch_wait_times"] ? value(byKey["bot.batch_wait_times"])' in settings)

print("\n== counts on a tape ==")
tape = read("lib/components/Tape.svelte")
check("the counts with no top are on a tape", "<Tape " in settings and '"bot.stale_reply.max_messages"' in settings
      and '"bot.cache.max_messages"' in settings)
check("and any other whole number with no top and no unit, bar the port and the build number",
      "const onTape = (f: FieldDef)" in settings and '"services.webui.port"' in settings.split("NOT_AMOUNTS")[1][:120])
check("pulled, it coasts on a flick and settles on a notch", 'busy = "coast";' in tape and "target = snap(at);" in tape)
check("past the bottom it gives a little and springs back", "const give = (d: number)" in tape)
check("- and + repeat, faster, while held", "gap = Math.max(45, gap * 0.8);" in tape)
check("the marks swell as they pass the middle", "Math.exp(-((x - MID) ** 2)" in tape)
check("the digits roll", "<Odometer value={showing} />" in tape and "translateY({-Number(ch) * 10}%)" in read("lib/components/Odometer.svelte"))
check("the wheel only sideways, so scrolling the page past it still scrolls", "Math.abs(e.deltaX) > Math.abs(e.deltaY)" in tape)
from fixtures import use_shipped_config  # noqa: E402
use_shipped_config()
from app.web.schema import CONFIG_SCHEMA  # noqa: E402
schema = {f["key"]: f for f in CONFIG_SCHEMA}
check("the counts have plain names", schema["bot.stale_reply.max_messages"]["label"] == "Stale after"
      and schema["bot.cache.max_messages"]["label"] == "Messages kept in memory")

print("\n== the save bar ==")
check("the count rolls, and it names what changed", "<Odometer value={changed} />" in settings and "{changedSummary}" in settings)
check("a pair's two ends are one change", "const near = NEAR_OF[key] && byKey[NEAR_OF[key]]" in settings)
check("Ctrl+S saves", "function saveKey(e: KeyboardEvent)" in settings and "<svelte:window onkeydown={saveKey} />" in settings)
check("once saved, it says so, then goes", "savedFlash = true;" in settings and '`Saved for ${scopeName}` : "Saved"}</b>' in settings
      and ".save-bar.is-leaving" in css)
check("an accent line along its top, and the Save key's shortcut on it", ".save-bar::before" in css and ".save-go kbd" in css)

print("\n== examples beside the switches ==")
demo = read("lib/components/SwitchDemo.svelte")
check("a switch row has the slot, empty or not, so the switches line up", 'class="settings-demo"' in settings
      and "<SwitchDemo key={f.key}" in settings)
check("only where the row is wide enough", "@container (min-width: 700px)" in css and ".settings-row { container-type: inline-size; }" in css)
check("flipping the switch plays the other version at once", "void on;" in demo and "start = performance.now();" in demo)
check("only while on screen and with Animations on", "new IntersectionObserver(" in demo and "still()" in demo)
check("screen readers skip it", 'aria-hidden="true"' in demo)
demos_ts = read("lib/switchdemos.ts")
bools = {k for k, f in schema.items() if f.get("type") == "bool"}
from app.web import descriptions as desc  # noqa: E402
from app.utils.helpers import load_config  # noqa: E402
for key, value in desc.walk(load_config()):
    if isinstance(value, bool):
        bools.add(key)
demo_keys = set(re.findall(r'^  "([a-z_.]+)": \{', demos_ts, re.M))
check("every example is for a switch that exists", demo_keys and demo_keys <= bools, str(sorted(demo_keys - bools)))
check("most switches have one", len(demo_keys) >= 30, str(len(demo_keys)))

print("\n== Telegram ==")
panel = read("lib/components/TelegramPanel.svelte")
smap = read("lib/settingsmap.ts")
check("its own page, with its alerts under the steps", 'panel: "telegram",' in smap and "<TelegramPanel>" in settings
      and "{#snippet alerts()}" in settings and "{@render alerts?.()}" in panel)
check("the token is checked with Telegram before it is kept", "api.telegramToken(token.trim())" in panel)
check("your ID is read off a message you send the bot", "api.telegramFindOwner()" in panel and "That's me" in panel)
check("a test message proves they fit", "api.telegramTest()" in panel)
check("every command, grouped and searchable, copied with a click", "copyText(`/${c.name}`" in panel and "Find a command" in panel)
check("the controller's state, and a start or restart", 'service(info?.state === "stopped" ? "start" : "restart")' in panel)
check("its alerts: errors, crashes, and silent ones",
      all(k in smap.split('id: "telegram"')[1][:900] for k in ("telegram_error_notifications", "telegram_crash_alerts", "telegram_quiet")))
check("which have plain names", schema["notifications.telegram_crash_alerts"]["label"] == "Crash alerts"
      and schema["notifications.telegram_quiet"]["label"] == "Silent alerts")

node = shutil.which("node")
if node and (ROOT / "webui" / "node_modules").is_dir():
    proc = subprocess.run([node, str(ROOT / "tests" / "controls_logic.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("controls_logic.mjs passes", proc.returncode == 0, proc.stderr[-400:])
else:
    print("  SKIP  needs Node and webui/node_modules")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
