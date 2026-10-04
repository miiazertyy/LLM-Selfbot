"""Settings: time you drag, not type.

Night hours are a 24-hour clock with the night drawn on it: drag the moon or
the sun, drag the night itself, or click the ring, instead of writing "2-8".
Timezones are picked from the real list, each with the time it is there now,
instead of typing "Europe/Paris" from memory. Amounts of time (seconds,
minutes) can be dragged sideways like a design tool's numbers.

The dial must never disagree with the runner about when it is night, so the
grid of cases here is run through both: the dial's arithmetic (clock.ts, under
Node) and the runner's own (app/utils/behavior.py).
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui" / "src"
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (WEB / rel).read_text(encoding="utf-8")


settings = read("pages/Settings.svelte")
dial = read("lib/components/HourRange.svelte")
picker = read("lib/components/TimezonePicker.svelte")
scrub = read("lib/scrub.ts")

print("== where they are ==")
check("night hours are a clock", 'f.key === "bot.night_invisible.hours"' in settings and "<HourRange" in settings)
check("that knows whose clock it is: the night timezone, else the persona's",
      "timezone={nightZone()}" in settings and '"bot.night_invisible.timezone"' in settings.split("const nightZone")[1][:400])
check("both timezones are picked, not typed",
      'f.key === "bot.night_invisible.timezone" || f.key === "bot.timezone"' in settings and "<TimezonePicker" in settings)

print("\n== the dial ==")
check("its ends are real sliders, for the keyboard too",
      dial.count('role="slider"') == 2 and "aria-valuenow" in dial and 'onkeydown={(e) => key("start", e)}' in dial)
check("the arrow keys move them an hour, page keys three", "ArrowRight: 1" in dial and "PageUp: 3" in dial)
check("the night itself can be dragged, the whole of it", 'grab("both", e)' in dial)
check("the ring is under the night, so a press on the night is not taken by the ring",
      dial.index('class="hr-hit"') < dial.index('class="hr-arc"'))
check("a click on the ring brings the nearer end", "nearer(hours, h)" in dial)
check("the ends glide the short way round, not back across the dial", "24 * Math.round((cur - h) / 24)" in dial)
check("it says whether the account is asleep now, and for how long", "untilChange(hours" in dial and "Asleep" in dial)
check("a value it cannot read is said, and dragging writes a good one", "is not a range" in dial)
check("it moves with the app's motion switch, not Windows'",
      "$motionEnabled" in dial and "prefers-reduced-motion" not in dial)

print("\n== the timezone picker ==")
check("a live clock set to that zone", "daySeconds(value, d)" in picker and "window.setTimeout(next" in picker)
check("its hands count on from when it was put up, never back round the dial",
      "const secAngle = $derived(s * 6)" in picker and "const minAngle = $derived(s * 0.1)" in picker
      and "const hourAngle = $derived(s / 120)" in picker and "s += ahead" in picker)
check("not from the seconds since 1970, an angle too large to draw exactly",
      "getTime() / 1000" not in picker)
check("a gap (sleep, a background tab, a new zone) jumps rather than spinning the hands round",
      "ahead <= 2" in picker and "class:is-jumping={jump}" in picker and ".tz-clock.is-jumping line { transition: none; }" in picker)
check("it ticks just after each second turns, not on a drifting interval",
      "1000 - (Date.now() % 1000)" in picker and "setInterval" not in picker)
check("every zone has its flag, or a globe for the ones in no country",
      "flagOf(code)" in picker and 'name="globe"' in picker and "tz-badge flag" in picker)
check("and its country's name, which finds it too", "whereOf(tz)" in picker and "nation.startsWith(s)" in read("lib/clock.ts"))
css = read("app.css")
check("flags come from a font of their own, as Windows draws them as letters",
      '"Twemoji Country Flags"' in css and "TwemojiCountryFlags.woff2" in css and "unicode-range: U+1F1E6-1F1FF" in css
      and (WEB / "assets" / "fonts" / "TwemojiCountryFlags.woff2").exists()
      and (WEB / "assets" / "fonts" / "TwemojiCountryFlags.LICENSE.md").exists())
check("searchable by city, region or offset", "searchZones(zones, q, now)" in picker)
check("with this computer's zone one click away", "localZone()" in picker)
check("a name this computer does not know is said, not quietly kept", "Not a timezone this computer knows" in picker)
check("a real listbox, with the keyboard", 'role="listbox"' in picker and '"ArrowDown"' in picker and '"Enter"' in picker)

print("\n== dragging amounts ==")
check("amounts of time can be dragged", "use:scrub" in settings and "timeStep(unitOf(f), from)" in settings)
check("an id or a build number cannot", "const scrubbable = (f: FieldDef) => !!unitOf(f) || f.min != null || f.max != null" in settings
      and "enabled: scrubbable(f)" in settings)
check("a click without a drag still types", "const SLOP" in scrub and 'addEventListener("click", click, true)' in scrub)
check("it stays inside the setting's bounds", "Math.max(opts.min, v)" in scrub and "Math.min(opts.max, v)" in scrub)

print("\n== the arithmetic ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "clock_logic.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("clock_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

    print("\n== the dial and the runner agree ==")
    par = subprocess.run([node, str(ROOT / "tests" / "clock_logic.mjs"), "--parity"], cwd=ROOT / "webui",
                         capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    try:
        grid = json.loads(par.stdout)
    except ValueError:
        grid = {}
    check("the dial's reading of the cases came back", bool(grid), par.stderr[-400:])
    from app.utils import behavior as b
    for spec, got in grid.items():
        want = b._parse_hours(spec)
        same = (got is None and want is None) or (got is not None and want is not None and tuple(got["hours"]) == tuple(want))
        check(f"{spec!r} is read the same by both", same, f"dial {got and got['hours']}, runner {want}")
        if not (got and want):
            continue
        nights, untils = [], []
        for hour in range(24):
            now = datetime(2026, 1, 15, hour, 30, tzinfo=timezone.utc)
            is_night, secs = b.night_window_state({"enabled": True, "hours": spec, "timezone": "UTC"}, now=now)
            nights.append(bool(is_night))
            untils.append(None if secs is None else secs // 60)
        check(f"{spec!r}: asleep at the same hours", nights == got["night"],
              f"dial {got['night']} runner {nights}")
        check(f"{spec!r}: the same time until it changes", untils == got["until"],
              f"dial {got['until']} runner {untils}")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
