"""This round of the panel: warnings where a device cannot do something, the
app's own question dialog, and a long list of things made to look and move
right.

  * NotHere says what does not work on this device where it would be used,
    and nothing at all where it works; the phone apps open links outside
  * questions before something that cannot be undone are the app's own
    dialog, which the Android app's web view (no dialogs) needs
  * dropdowns show a mark and a line for each choice, a highlight that
    glides, a search for long lists, and never run off the screen; the value
    types itself in without a caret left blinking
  * sliders either side of zero fill as a pill from the middle, and sweep in
    smoothly however short they are; nudge hours are a clock
  * the undo bar is centred on the screen; Big Picture's queue and chat
    scroll, its pictures open, its sky moves smoothly; messages say when
    they were sent; Discord's animated stickers play
"""
import shutil
import subprocess
import sys
import tempfile
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


print("== what does not work here, said where it is used ==")
nh = read("lib/components/NotHere.svelte")
dev = read("lib/device.ts")
check("nothing at all where the feature works", "{#if problem}" in nh and "$notHere(feature)" in nh)
check("a notice, a line or a tag, as the place allows", 'variant === "chip"' in nh and 'variant === "line"' in nh)
check("with what to do about it: a command to copy, or the page that does it",
      "problem.fix.command" in nh and "problem.fix.route" in nh)
check("in the warning colour, not the error one", "var(--color-warn)" in nh and "--color-bad" not in nh)
check("asked once, when the app starts", "loadDevice();" in read("App.svelte") and "api.device()" in dev)
settings = read("pages/Settings.svelte")
check("a setting that needs something says so under it, a combined switch for either half",
      '{#if f.needs ?? partnerOf(f)?.needs}<NotHere feature={(f.needs ?? partnerOf(f)?.needs)!} variant="line" />{/if}' in settings)
from app.web.schema import CONFIG_SCHEMA  # noqa: E402
needs = {f["key"]: f.get("needs") for f in CONFIG_SCHEMA if f.get("needs")}
check("voice messages and the Snapchat switch are marked", needs.get("bot.tts.enabled") == "voice_messages"
      and needs.get("snapchat.enabled") == "snapchat")
check("the Snapchat tab says so at the top", '{#if tab.id === "snapchat"}<NotHere feature="snapchat" />{/if}' in settings)
acc = read("pages/Accounts.svelte")
check("adding an account: the platform says whether it runs here", '<NotHere feature={editPlatform === "discord" ? "discord" : "snapchat"} />' in acc)
check("and one that cannot is not added", "!blocked &&" in acc)
check("without a browser to sign in with, a token is the way in", 'discordMode = missing("browser_login") ? "token" : "login";' in acc)
check("the add menu tags what does not run here", '<NotHere feature="snapchat" variant="chip" />' in acc)
check("a phone: keep it open, one Discord account at a time", '<NotHere feature="background" />' in acc
      and '<NotHere feature="discord_many"' in acc)
system = read("pages/System.svelte")
check("System lists everything that does not work here, only when there is something", "{#if cantHere.length}" in system
      and 'title="Not available here"' in system)
check("and names the device beside the version", "{device.label}" in system)
check("the update button says what it will do here", '"Download the update"' in system and '"Get the new IPA"' in system)
check("and is not offered where this release has nothing for this device", "update.ready !== false" in system)
check("folder buttons stay, and say why they cannot", 'disabled={!!$notHere("folders")}' in system)
check("Local AI on a phone: use a server on the network", '<NotHere feature="local_start" />' in read("lib/components/LocalAI.svelte"))
imp = read("lib/components/Importer.svelte")
check("a file drop says when files cannot be picked, instead of a button that does nothing",
      '<NotHere feature="files_pick" variant="line" />' in imp and 'class:hidden={!!$notHere("files_pick")}' in imp)
check("Pictures too, and when HEIC cannot be opened", '<NotHere feature="heic" variant="line" />' in read("pages/Pictures.svelte"))
check("the settings file buttons too", '<NotHere feature="files_save" variant="chip" />' in read("lib/components/SettingsFile.svelte"))
app = read("App.svelte")
check("in the phone apps, links to anywhere else open in the phone's browser",
      "inPhoneApp()" in app and "openUrl(a.href)" in app and 'document.addEventListener("click", onLink)' in app)
win = read("lib/window.ts")
check("through the app, which asks the phone", "export async function openUrl(" in win and "api.openUrl(url)" in win)

print("\n== asking first, in the app's own dialog ==")
ask = read("lib/ask.ts")
check("ask() answers true or false, as confirm() did", "export function ask(" in ask and "Promise<boolean>" in ask)
check("shown once, for the whole app", "<AskHost />" in app)
left = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.svelte")
        if "confirm(" in p.read_text(encoding="utf-8") and "confirmDelete" not in p.read_text(encoding="utf-8")]
check("no confirm() is left, which the Android app would answer no without asking", not left, ", ".join(left))
check("a destructive yes is drawn in red", "danger: true" in read("pages/Memory.svelte"))

print("\n== dropdowns ==")
sel = read("lib/components/Select.svelte")
check("a choice can have an icon, a flag, or a badge with its initial", "o.icon" in sel and "o.mark" in sel and "o.badge" in sel)
check("and a line under it saying what it does", '<span class="sel-opt-hint">' in sel)
check("the chosen one's mark shows on the closed box", "{#if selected}{@render markOf(selected, true)}{/if}" in sel)
check("one highlight glides from row to row", 'class="sel-glide"' in sel and "transform: translateY({glide.y}px)" in sel)
check("rows settle in one after another", "calc(var(--i, 0) * 18ms)" in sel)
check("a long list can be searched", "const searchable = $derived(options.length > 8);" in sel and '<label class="sel-search">' in sel)
check("and it never runs off the screen", 'style="max-height: {room}px"' in sel and "options.some((o) => o.hint) ? 52 : 38" in sel)
check("the value still types itself in, with nothing left blinking",
      '<span class="sel-cursor"></span>' in sel and "@keyframes sel-blink" not in sel and "infinite" not in sel)
check("the typing starts from the first letter drawn", "typing = null;          // done: the plain label, no cursor" in sel)
check("each choice in Settings says what it is", '{ value: "short", label: "Short", hint: "One line, like a text"' in settings)
check("languages with their flags", 'mark: "🇫🇷"' in settings)
check("voices by name, with whose voice it is", "voiceName(v)" in settings and '"Woman\'s voice"' in settings
      and "badge: true" in settings)
check("context lengths with roughly how many words", "About ${(Math.round((c * 0.75) / 500) * 500).toLocaleString()} words"
      in read("lib/components/LocalAI.svelte"))
check("the label no longer repeats the choices", any(f["key"] == "bot.message_style.mode" and f["label"] == "Message style"
                                                     for f in CONFIG_SCHEMA))

print("\n== sliders and clocks ==")
css = (SRC / "app.css").read_text(encoding="utf-8").replace("\r\n", "\n")
check("a range either side of zero fills as a pill from the middle, round at zero",
      ".slider.is-centered:not(.is-blank)::-webkit-slider-runnable-track" in css
      and "radial-gradient(circle calc(var(--track) / 2) at var(--from, 50%) 50%" in css)
check("Firefox too", ".slider.is-centered:not(.is-blank)::-moz-range-track" in css)
check("the sliders that cross zero are marked so", "class:is-centered={(f.min ?? 0) < 0 && (f.max ?? 1) > 0}" in settings)
arr = read("lib/arrive.ts")
check("a sweep glides instead of stepping, the step lifted until it lands", 'node.setAttribute("step", "any")' in arr
      and 'node.setAttribute("step", step)' in arr)
check("and is timed from the first frame drawn, so it does not start with a leap", "if (!t0) {\n        t0 = now;" in arr)
check("nudge hours are a clock you drag, not [10, 22] in a box",
      '{:else if f.key === "bot.nudge.send_during_hours"}' in settings and "words={NUDGE_WORDS}" in settings)
check("said plainly", 'on: "Nudging now", off: "Not now"' in settings)
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("and a window past midnight works as the clock draws it",
      "in_window = current_hour >= send_hour_start or current_hour < send_hour_end" in runner)

wt = read("lib/components/WaitTimes.svelte")
check("pulling a range out of a wait keeps moving: what was sent and what comes back are compared the same way",
      "lastSent = JSON.stringify(clean(rows));" in wt and "JSON.stringify(clean(value))" in wt)
check("and the waits are never re-seeded under a drag", "untrack(() => dragging) != null" in wt)

print("\n== the raw config, in a code editor ==")
rawed = read("lib/components/RawEditor.svelte")
check("a real editor: coloured JSON, line numbers, folding, matched brackets, search, checked as typed",
      all(x in rawed for x in ("syntaxHighlighting(colours)", "lineNumbers()", "foldGutter(", "bracketMatching()",
                               "search(", "linter(jsonParseLinter()")))
check("most of the window, not a small box", "width: min(1180px, 96vw);" in rawed and "height: min(88vh, 940px);" in rawed)
check("says whether the JSON is valid, and where it is not, jumping there on a click",
      "Valid JSON" in rawed and "Line {problem.line}</span>" in rawed and "{problem.message}</span>" in rawed
      and "function toProblem()" in rawed)
check("Ctrl+S saves, Escape closes, and leaving with changes asks first",
      '"Mod-s"' in rawed and 'e.key !== "Escape"' in rawed and 'ask("Leave without saving?"' in rawed)
askhost = read("lib/components/AskHost.svelte")
check("that question shows over the editor, not under it where X and Cancel seemed to do nothing",
      "z-index: 500;" in askhost and "document.body.appendChild(node)" in askhost)
check("a destructive question gives the safe answer the focus, Escape answers no",
      "(danger ? noBtn : yesBtn)?.focus()" in askhost and 'e.key === "Escape"' in askhost)
check("the error pill shortens its message rather than clipping its icon",
      '<span class="re-status-line">' in rawed and ".re-status-text {" in rawed and "text-overflow: ellipsis;" in rawed)
check("Format tidies without rounding the big owner ID", "formatJson(current)" in rawed
      and "JSON.parse" not in rawed)
check("loaded only when it is opened", 'import("../lib/components/RawEditor.svelte")' in settings)
node = shutil.which("node")
if node and (ROOT / "webui" / "node_modules").is_dir():
    proc = subprocess.run([node, str(ROOT / "tests" / "jsontext_logic.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("jsontext_logic.mjs passes", proc.returncode == 0, proc.stderr[-400:])

print("\n== the Dashboard's undo ==")
ub = read("lib/components/UndoBar.svelte")
check("centred by a row, not a translate an animation fights",
      ".ub-row {" in ub and "justify-content: center;" in ub and "translate(-50%" not in ub)
check("the row spans the page, not the window, so the sidebar does not push the bar off centre",
      'document.querySelector("main")' in ub and "ro.observe(main);" in ub)
check("moved to <body>, so no wrapper decides what fixed means", "document.body.appendChild(node)" in ub)
check("the time left runs out round the bar's own edge", "@keyframes ub-run" in ub and 'class="ub-left"' in ub
      and 'pathLength="100"' in ub and "function edge(" in ub)
check("what went is shown: the picture, or a little pile of them", "images.slice(-3)" in ub and 'class="ub-pic"' in ub
      and "images={leaving.map(thumbOf)}" in read("pages/Pictures.svelte")
      and "const thumbOf = (p: Pic) => api.pictureSmall(p, 480, who);" in read("pages/Pictures.svelte"))
check("Ctrl+Z undoes it, unless a text box wants it", 'e.key.toLowerCase() !== "z"' in ub and "isContentEditable" in ub)
check("the old bar and its clipped line are gone", "undo-timer" not in read("pages/Dashboard.svelte") and ".undo-bar" not in css)

print("\n== Big Picture ==")
q = read("lib/bigpicture/BPQueue.svelte")
check("the queue scrolls instead of squeezing its cards together", "flex-shrink: 0;" in q and "overflow-y: auto;" in q)
check("fading at whichever edge has more", ".bpq-list.is-above" in q and ".bpq-list.is-below" in q)
check("whoever goes on stage is brought into view", 'scrollIntoView({ block: "nearest", behavior: "smooth" })' in q)
check("and a sticker reads as one", 'return m[2] ? `Sticker: ${m[2].trim()}` : "Sent a sticker";' in q)
stage = read("lib/bigpicture/BPStage.svelte")
check("the conversation scrolls back as far as it has been read", "messages.slice(-100)" in stage
      and "overflow-y: auto;" in stage)
check("reading further back at the top", "if (el.scrollTop < 80) onearlier?.();" in stage
      and "export async function loadEarlier(" in read("lib/chats.ts"))
check("keeping your place as earlier ones arrive", "el.scrollTop = beforeTop + (el.scrollHeight - beforeH);" in stage)
check("and a way back to the newest", 'class="bps-newest"' in stage)
mb = read("lib/components/MessageBody.svelte")
check("a picture opens over Big Picture, not behind it", "z-index: 400;" in mb)
check("and Escape closes the picture, not Big Picture", "e.stopImmediatePropagation();" in mb)

print("\n== when a message was sent ==")
fmt = read("lib/fmt.ts")
check("said as short as it can be", "export function whenSent(" in fmt and "`Yesterday ${time}`" in fmt)
check("beside a message in Chats as the pointer passes", '<span class="cd-time"' in read("pages/Chats.svelte")
      and ".cd-msg:hover .cd-time" in read("pages/Chats.svelte"))
check("and quietly beside every message in Big Picture", '<span class="bps-time"' in stage)
node = shutil.which("node")
if node and (ROOT / "webui" / "node_modules").is_dir():
    proc = subprocess.run([node, str(ROOT / "tests" / "fmt_logic.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("fmt_logic.mjs passes", proc.returncode == 0, proc.stderr[-400:])
else:
    print("  SKIP  needs Node and webui/node_modules")

print("\n== stickers ==")
check("a sticker's id and kind reach the panel", '"format": {1: "png", 2: "apng", 3: "lottie", 4: "gif"}' in runner)
check("an animated one is played, not named", "<LottieSticker" in mb and "playedStickers" in mb)
lottie = read("lib/components/LottieSticker.svelte")
check("with the light player, loaded the first time one is shown", 'import("lottie-web/build/player/lottie_light")' in lottie)
check("playing only while on screen, still with Animations off", "IntersectionObserver" in lottie
      and "goToAndStop(0, true)" in lottie)
check("and its name if it cannot be had", "Sticker: {name}" in lottie)

# The route that hands the panel a sticker's animation: fetched once, then kept.
sandbox = Path(tempfile.mkdtemp(prefix="stickers_"))
import app.web.routes.media_routes as media  # noqa: E402
media.STICKER_DIR = sandbox
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import httpx  # noqa: E402

calls = []


class Fake:
    def __init__(self, status, content):
        self.status_code = status
        self.content = content


def fake_get(url, **kw):
    calls.append(url)
    if url.endswith("/749054660769218631.json"):
        return Fake(200, b'{"v": "5.5.7", "layers": []}')
    if url.endswith("/1.json"):
        return Fake(200, b"<html>not an animation</html>")
    return Fake(404, b"")


real_get = httpx.get
httpx.get = fake_get
try:
    api = FastAPI()
    api.include_router(media.router)
    client = TestClient(api)
    r = client.get("/api/media/sticker/749054660769218631.json")
    check("an animated sticker comes through the app", r.status_code == 200 and r.json()["v"] == "5.5.7", r.text[:80])
    client.get("/api/media/sticker/749054660769218631.json")
    check("and is fetched from Discord once, then kept", len(calls) == 1 and (sandbox / "749054660769218631.json").exists())
    check("a page that is not an animation is not kept", client.get("/api/media/sticker/1.json").status_code == 404
          and not (sandbox / "1.json").exists())
    check("and nothing but a number is looked up", client.get("/api/media/sticker/..%2Fx.json").status_code in (404, 422)
          and client.get("/api/media/sticker/abc.json").status_code == 404)
finally:
    httpx.get = real_get
    shutil.rmtree(sandbox, ignore_errors=True)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
