"""Settings you drag and pick, rather than type.

Amounts of time are dials, and the two ends of a range (a min and a max
setting) are one dial with a hand for each. Typing speed is a dial beside a
little keyboard typing at it. Languages are picked by name from the real
lists. The desktop build number fetches itself. The prefixes light up when
they are used. The sampling settings say "Default" when blank, not "null".
Lists are chips that run on like a sentence. Snapchat's tab is the same
instruments: dials, a clock for its quiet hours, a setup board.

The arithmetic runs under Node (tests/settings_dials.mjs); this checks the
wiring, and the pieces that live in Python.
"""
import asyncio
import json
import shutil
import subprocess
import sys
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
dial = read("lib/components/Dial.svelte")
speed = read("lib/components/TypingSpeed.svelte")
lists = read("lib/components/ListEditor.svelte")
langs = read("lib/components/LanguagePicker.svelte")
snap = read("lib/components/SnapchatSetup.svelte")
hours = read("lib/components/HourRange.svelte")
css = read("app.css")
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
supervisor = (ROOT / "app" / "web" / "supervisor.py").read_text(encoding="utf-8")

print("== time on dials ==")
check("every amount of time is a dial, not a number box",
      '(f.type === "int" || f.type === "float") && isTimeUnit(unitOf(f))' in settings and "<Dial values={[num(value(f))]}" in settings)
check("on a time scale in the setting's own unit, bounds and precision",
      'timeScale(u, { min: f.min, max: f.max, least: f.step, integer: f.type === "int" })' in settings)
check("the two ends of a range are one row with one dial", "function rowsOf(list: FieldDef[])" in settings
      and "{#each rowsOf(shown).slice(0, drawnRows) as f (f.key)}" in settings and "{#each rowsOf(results) as f (f.key)}" in settings)
for near, far in [("bot.typing.think_min", "bot.typing.think_max"), ("bot.read_delay_dm_min", "bot.read_delay_dm_max"),
                  ("bot.global_cooldown_min", "bot.global_cooldown_max"),
                  ("bot.friend_requests.accept_delay_min", "bot.friend_requests.accept_delay_max"),
                  ("bot.status.change_interval_min", "bot.status.change_interval_max"),
                  ("snapchat.min_send_gap_ms", "snapchat.max_send_gap_ms")]:
    check(f"{near.split('.')[-1]} and {far.split('.')[-1]} are one dial",
          f'"{near}": {{' in settings and f'max: "{far}"' in settings.split(f'"{near}": {{')[1][:120])
check("only the end that moved is written", "if (a !== num(value(f))) setValue(f, a);" in settings)
check("undo puts both ends back", "undo(f); if (far) undo(far);" in settings)
check("the counts on the subtabs are rows, not settings", "return rowsOf(fieldsFor(t, s)).length;" in settings)
check("a hand is never dragged past the other", "Math.min(x, nums[1])" in dial and "Math.max(x, nums[0])" in dial)
check("the arc between two hands moves both", 'grab("both", e)' in dial)
check("the hands are real sliders, for the keyboard", dial.count('role="slider"') == 2 and "onkeydown={(e) => key(" in dial)
check("the dial fits its value, and grows when pushed to the end",
      "scale.fit(peakOf(nums))" in dial and "peak >= hi * 0.98" in dial)
check("a click in the middle types an exact amount", "openEditor" in dial and "scale.exact(" in dial)
check("each dial's colours are its own", "let made = 0;" in dial and 'id="{uid}-arc"' in dial)
check("it moves with the app's motion switch", "$motionEnabled" in dial and "prefers-reduced-motion" not in dial)
check("what 0 means is said where it means something", '"snapchat.verify_wait_ms": "No limit"' in settings)

print("\n== typing speed ==")
check("the two speeds are one dial, on a speed scale", "<TypingSpeed slow={num(value(f))} fast={num(value(far))}" in settings
      and "scale={wpmScale({ min, max })}" in speed and 'tone="is-speed"' in speed)
check("and no number box", 'f.key === "bot.typing.wpm_min"' in settings.split("<TypingSpeed")[0][-200:])
check("a keyboard types real messages at them", 'const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];' in speed
      and "(Math.max(1, speed) * 5) / 60" in speed)
check("slowest, fastest, then anywhere between, like the runner", '["slowest", "fastest", "between"]' in speed)
check("only while on screen and with motion on", "IntersectionObserver" in speed and "!$motionEnabled" in speed)

print("\n== languages ==")
check("the persona locale is Discord's own list", 'f.key === "bot.locale"' in settings and "options={DISCORD_LOCALES}" in settings)
check("the fallback language is every language, most used first",
      'f.key === "bot.default_language"' in settings and "options={allLanguages()} common={COMMON_LANGUAGES}" in settings)
check("searchable by name in either language, or code", "searchLanguages(options, q)" in langs and 'role="listbox"' in langs)
check("both with flags, a globe for the ones that are no country's", 'mark="code"' not in settings
      and "flagOf(l.flag)" in langs and 'name="globe"' in langs and "lp-tile" not in langs)
check("a stored value not in the list is said, not replaced", "{unknown}" in langs)
from app.utils.languages import LANGUAGE_NAMES, language_name
node = shutil.which("node")
if node:
    codes = subprocess.run([node, str(ROOT / "tests" / "settings_dials.mjs"), "--codes"], cwd=ROOT / "webui",
                           capture_output=True, text=True, timeout=120, encoding="utf-8")
    try:
        ts_codes = json.loads(codes.stdout)
    except ValueError:
        ts_codes = []
    check("the runner can name every language Settings offers", sorted(ts_codes) == sorted(LANGUAGE_NAMES),
          f"{len(ts_codes)} offered, {len(LANGUAGE_NAMES)} named")
check("the runner names a language rather than shouting its code", language_name("hi") == "Hindi"
      and language_name("pt-BR") == "Portuguese" and language_name("xx") == "XX")
for path in ("app/core/engine.py", "app/platforms/discord_runner.py", "app/platforms/snapchat_bridge.py"):
    src = (ROOT / path).read_text(encoding="utf-8")
    check(f"{path} uses the shared names", "language_name(" in src and "_LANG_NAMES = {" not in src)

print("\n== the build number fetches itself ==")
check("a Latest button beside it", 'f.key === "bot.desktop.build_number"' in settings and "latestBuild(f)" in settings)
from app.utils import session
from app.web.routes import config_routes
real = session._fetch_build_number


async def fake():
    return 622805


session._fetch_build_number = fake
try:
    got = asyncio.run(config_routes.discord_build_number(None))
finally:
    session._fetch_build_number = real
check("the route answers with Discord's number", got == {"build_number": 622805}, str(got))


async def nothing():
    return None


session._fetch_build_number = nothing
try:
    asyncio.run(config_routes.discord_build_number(None))
    said = None
except Exception as e:  # HTTPException
    said = getattr(e, "status_code", None)
finally:
    session._fetch_build_number = real
check("and says so when it cannot read one, rather than inventing one", said == 502, str(said))

schema_src = (ROOT / "app" / "web" / "schema.py").read_text(encoding="utf-8")
check("a config without a build source shows the one the runner uses, not an empty choice",
      '"key": "bot.desktop.build_source"' in schema_src
      and '"default": "custom"' in schema_src.split('"key": "bot.desktop.build_source"')[1][:160]
      and 'desktop_cfg.get("build_source", "custom")' in (ROOT / "app" / "utils" / "session.py").read_text(encoding="utf-8"))

print("\n== the prefixes light up when used ==")
check("the runner says when a command runs", 'bot.add_listener(_announce_command, "on_command")' in runner
      and 'emit_use("bot.prefix"' in runner)
check("and when the priority prefix is used, both ways", runner.count('emit_use("bot.priority_prefix", PRIORITY_PREFIX)') == 2)
check("and when a trigger word wakes it", 'emit_use("bot.trigger", _trig.group(0))' in runner)
check("only when the panel is listening", "def emit_use" in runner and "if not _EMIT_EVENTS:" in runner.split("def emit_use")[1][:80])
check("the panel passes it on to the page", 'USE_MARK = "\\x1eUSE "' in supervisor and 'bus.event("use", evt)' in supervisor)
check("the row lights like a model's", 'subscribeEvents("use"' in read("lib/settinguse.ts")
      and '<span class="settings-used"' in settings and ".settings-used {" in css)

print("\n== small things ==")
check("delivery tags without their brackets", "{toneName(t)}" in settings and 'title="Sent as {t}"' in settings)
check("a blank sampling setting says Default, not null", '{blank ? "Default" :' in settings and "restOf(f)" in settings)
check("and can be put back to blank", "setValue(f, null)" in settings and "blankable(f)" in settings)
check("a range either side of zero fills from zero", "const origin = lo < 0 && hi > 0 ? 0 : lo;" in settings
      and "var(--from, 0%)" in css)
check("lists are chips that run on like a sentence", "flex-wrap: wrap" in lists and "longform" not in lists
      and "field-sizing: content" in lists)
check("removing one does not shift the others", ".le-x {" in lists and "position: absolute" in lists.split(".le-x {")[1][:60])

choices = settings.split("const CHOICES")[1].split("};")[0]
import re as _re
check("dropdown choices are plain words, not a word and an explanation",
      not _re.search(r'label: "[^"]*, [^"]*"', choices), _re.findall(r'label: "[^"]*, [^"]*"', choices))
from app.web import descriptions as _desc
check("no description runs on", max(len(v) for v in _desc.DESCRIPTIONS.values()) <= 170,
      max(_desc.DESCRIPTIONS.items(), key=lambda kv: len(kv[1]))[0])
check("the build source says what the two choices do, in a line",
      _desc.DESCRIPTIONS["bot.desktop.build_source"] == "Automatic keeps it matching Discord's latest build. Custom uses the number below.")

print("\n== the batch waits ==")
waits = read("lib/components/WaitTimes.svelte")
check("drawn as the odds over time: a stem per wait, a hill for the spread", "wt-stem" in waits and "const hill" in waits)
check("on a log scale, so seconds and minutes both get room", "Math.log(Math.max(t, LO) / LO)" in waits)
check("a dot drags sideways for the wait and up for its odds, the others giving way",
      "timeAt(from.hx + p.x - from.px)" in waits and "from.share + ((from.py - p.y) / (BASE - TOP)) * tallest" in waits
      and "function withShare(" in waits)
check("stored as whole percentages that add up to 100", "function percents(" in waits)
check("the DM table always keeps one wait, as the runner cannot pick from nothing",
      "if (!canEmpty && waits.length <= 1) return;" in waits)
check("the server table can be emptied, and then says it follows the DMs", "Same waits as DMs" in waits
      and 'canEmpty={f.key === "bot.server_batch_wait_times"}' in settings)
check("times and odds can be typed", "readSpan(draft)" in waits and 'readTime(parts[0], "s")' in waits
      and 'what === "share"' in waits)

print("\n== typing on every clock ==")
check("a dial's middle opens a box that reads 2m or 1h 30m", "scale.read(String(d))" in dial and "scale.example" in dial)
check("the night clock's times can be clicked and typed", "readHour(draft)" in hours and 'class="hr-type"' in hours
      and "onclick={() => type(which)}" in hours)
check("and it is the size of the other dials", "const SIZE = 164;" in hours and "const W = 164;" in dial)

print("\n== on-off switches ==")
toggle = read("lib/components/Toggle.svelte")
check("kept quiet: a plain track and a round knob, no glow and no words in it", "tg-knob" in toggle
      and "tg-glow" not in toggle and "tg-word" not in toggle and "blur(" not in toggle)
check("on, a muted shade of the accent rather than the bright gradient",
      "color-mix(in srgb, var(--color-accent) 70%, var(--color-card))" in toggle and "linear-gradient" not in toggle)
check("the knob turns white when on, and stretches while held", ".tg.is-on .tg-knob" in toggle
      and "calc(var(--k) + var(--stretch))" in toggle)
check("a real switch for screen readers, named for what it switches", 'role="switch"' in toggle
      and "aria-checked={checked}" in toggle and "name={f.label}" in settings)
check("it follows the app's motion switch", ':root[data-motion="off"]) .tg-knob' in toggle)

print("\n== appearance ==")
look = read("lib/components/Appearance.svelte")
check("the tab is its own component", '<Appearance which={sub.panel} />' in settings and "uploadAppearance" not in settings)
check("each theme is its colours, side by side", "ap-swatches" in look and "t.vars[v]" in look and "ap-mini" not in look)
check("each kind of panel sits over colour", "ap-surface-pane is-{s.id}" in look)
check("each typeface is set in itself", 'class="ap-aa" style="font-family: {f.stack}"' in look)
check("motion, smooth scrolling and snow are rows in a card, like every other tab", look.count('class="settings-row') == 3)
check("no save note where nothing is saved",
      '{#if !(sub.panel === "theme" || sub.panel === "typeface" || sub.panel === "interface")}' in settings)

print("\n== Snapchat ==")
check("quiet hours on the night's clock, on this computer's time", 'f.key === "snapchat.quiet_hours"' in settings
      and "<HourRange value={value(f)} timezone={localZone()} words={QUIET_WORDS}" in settings)
check("switched off, they are blank, which the script reads as none", 'setValue(f, v ? "2-9" : "")' in settings)
check("the clock's words are the caller's", "words = NIGHT" in hours and "{words.none}" in hours)
check("counts on dials", '"snapchat.max_recipients": { one: "chat"' in settings and "countScale(" in settings)
labels = {f["key"]: f["label"] for f in __import__("app.web.schema", fromlist=["CONFIG_SCHEMA"]).CONFIG_SCHEMA}
check("its labels do not repeat Snapchat or their units", all(
    not labels[k].startswith("Snapchat") and "(ms)" not in labels[k]
    for k in labels if k.startswith("snapchat.") and k != "snapchat.enabled"),
    str([labels[k] for k in labels if k.startswith("snapchat.")]))
check("the setup board ticks off the four things it needs", "sn-steps" in snap and snap.count("name: \"") >= 4)
brands = read("lib/brands.ts")
check("Snapchat's own logo, as Snapchat draws it: a white ghost outlined in black, on its yellow",
      "<path d={SNAPCHAT_GHOST} />" in snap and "fill: #fff; stroke: #000" in snap and "CC0" in brands)
check("and its ghost for every Snapchat icon, not one drawn from memory",
      "snapchat: SNAPCHAT_GHOST," in read("lib/components/Icon.svelte"))
check("an account that stopped still shows what it last said", "last said" in snap)
check("installing is still tracked after leaving the page", 'trackUntil("settings", "Installing Snapchat support"' in snap)

print("\n== the Accounts page says online when it is ==")
check("the presence is the client's own, not the user object's, which carries none",
      '_pres = str(bot.status or "") or "offline"' in runner and "bot.user.status" not in runner)
check("connected but not told yet reads as what it set, not offline",
      '_pres = str(getattr(bot, "shown_status", None) or "online")' in runner and "bot.shown_status = target" in runner)

print("\n== the arithmetic ==")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "settings_dials.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("settings_dials.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
