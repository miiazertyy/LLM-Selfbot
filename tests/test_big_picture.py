"""Big Picture Mode: the whole screen, watching everything the bots do, live.

A button at the top right (and Ctrl+Shift+B, and Ctrl+K) opens a full-screen
view that plays by itself: the queue from every account, the conversation the
director picks, big, with every step of its reply, which model is working and
what it is thinking, and the day's numbers. With nobody waiting, a scene for
every part of the app: the accounts, the pictures, friend requests, the
persona, anything broken, named by chapters under the stage. It takes the
whole screen and gives it back; its sounds are off until turned on; it reads
a conversation's history only for the one on stage, at most once every twenty
seconds.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui" / "src"
BP = WEB / "lib" / "bigpicture"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(p):
    return Path(p).read_text(encoding="utf-8")


print("== the way in ==")
app = read(WEB / "App.svelte")
check("a button at the top right, with the window's own buttons", 'data-tip="Big Picture Mode (Ctrl+Shift+B)"' in app
      and app.count("{@render bigPictureButton()}") == 2
      and app.index("onclick={() => setBigPicture(true)}") < app.index("onclick={toggleSize}"))
check("and in a browser's header, where there are none", "{#if !desktop}" in app.split("<LoadingBadge {route} />")[1][:200])
check("Ctrl+Shift+B toggles it", 'e.shiftKey && e.key.toLowerCase() === "b"' in app)
check("Ctrl+K knows it", '"bigpicture"' in read(WEB / "lib" / "search.ts") and 'id === "bigpicture"' in app)
check("its code loads only when it is first opened", 'import("./lib/bigpicture/BigPicture.svelte")' in app
      and "import BigPicture" not in app)

print("\n== the whole screen ==")
desktop = read(ROOT / "app" / "desktop.py")
fs = desktop[desktop.index("def set_fullscreen"):]
fs = fs[:fs.index("\n    def ", 10)]
check("the app window goes fullscreen", "toggle_fullscreen()" in fs)
check("only when it has to change, so a second call cannot undo it", '_WINDOW.get("fullscreen")' in fs)
win = read(WEB / "lib" / "window.ts")
check("a browser asks for fullscreen itself", "requestFullscreen" in win and "exitFullscreen" in win)
bp = read(BP / "BigPicture.svelte")
check("it enters on open and gives the screen back on close",
      "setFullscreen(true)" in bp and "setFullscreen(false)" in bp)
check("Esc leaves", 'e.key === "Escape"' in bp)

print("\n== quiet by default, light on the account ==")
stores = read(WEB / "lib" / "stores.ts")
check("sounds are off until turned on, and remembered", 'persisted<boolean>("bigPictureSound", false' in stores)
sounds = read(BP / "sounds.ts")
check("made on the spot, with no files", "createOscillator" in sounds and ".mp3" not in sounds and ".wav" not in sounds)
check("and never a burst", "function once(" in sounds)
check("history is read only when not already loaded", "get(conversations)[k]" in bp and "asked.has(k)" in bp)
check("at most once every twenty seconds", "Date.now() - lastHistory < 20000" in bp)
check("the Chats feed is not started a second time", "startChatLive" not in bp)
check("everything stops with the page hidden", bp.count("document.hidden") >= 2)

print("\n== it leaves in one quick fade ==")
motion = read(BP / "motion.ts")
check("nothing inside waits to finish while it closes", motion.count("bigPictureExit.on") >= 6)
check("and its clock stops at once, not after the fade", "const gone = () => !get(bigPicture);" in bp
      and "document.hidden || gone()" in bp)
check("every open and close goes through one place", "export function setBigPicture(" in stores
      and "setBigPicture(false)" in bp)

print("\n== opening and closing are light ==")
app = read(WEB / "App.svelte")
css = read(WEB / "app.css")
poll = read(WEB / "lib" / "poll.ts")
wave = read(BP / "BPWave.svelte")
enter_leave = bp[bp.index("function enter("):bp.index("</script>")]
check("the entrance and the exit move opacity and scale only, no blur the size of the screen",
      "blur(" not in enter_leave and "opacity:${t}; transform: scale(" in enter_leave)
check("the app underneath fades out, then is not drawn at all while covered",
      "class:is-under={$bigPictureArriving}" in app and "class:is-covered={$bigPictureCovering}" in app
      and ".app-shell.is-covered { content-visibility: hidden; }" in css)
check("its moving background stops under it", ":root .app-backdrop.is-covered::before," in css
      and "animation-play-state: paused" in css)
check("fullscreen only once the app is hidden, so the resize lays out this view alone",
      bp.index("bigPictureCovering.set(true);") < bp.index("setFullscreen(true);"))
check("out of fullscreen before the app is drawn again, and drawn before the fade",
      "await leaveFullscreen();" in bp
      and bp.index("await leaveFullscreen();") < bp.index("bigPictureCovering.set(false);\n    await new Promise")
      and "setBigPicture(false);" in bp.split("await leaveFullscreen();")[1][:500])
check("every close takes that way out, the hotkey too", "bigPictureCloser.fn = close;" in bp
      and "if (!on && bigPictureCloser.fn)" in stores)
check("the window says whether it changed, so a close only waits for a resize that is coming",
      "changed = bool(_WINDOW.get(\"fullscreen\")) != want" in desktop and "return changed" in desktop
      and "Promise<boolean>" in win)
check("what is not on the first screen waits until the view has arrived",
      "function onceArrived(" in bp and "onceArrived(loadFriends)" in bp and "arrived = true;" in bp
      and "{#if arrived}" in bp)
check("its code is fetched before the first open, while the app is idle", "requestIdleCallback" in app
      and "loadBigPicture()" in app)
check("pages under it stop polling, except the health it shows", "bigPictureCovering.subscribe(" in poll
      and "visiblePoll(pollHealth, 15000, { underBigPicture: true })" in app)
check("nothing in it repaints every frame: its beat is a ring that scales and fades",
      "box-shadow" not in wave.split("@keyframes bpw-beat")[1].split("}")[0] and "transform: scale(1.45)" in wave)

print("\n== the same words as Chats ==")
chats = read(WEB / "pages" / "Chats.svelte")
check("Chats uses the shared reply stages", 'from "../lib/chatstatus"' in chats and "function statusOf" not in chats)
check("and so does Big Picture", 'from "../chatstatus"' in bp)

print("\n== the director ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "bigpicture_director.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("bigpicture_director.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print("\n== all of it there ==")
for part in ("BPBackdrop", "BPQueue", "BPStage", "BPBrain", "BPThoughts", "BPStats", "BPFeed", "BPScenes", "BPWave", "Counter",
             "BPAccounts", "BPPictures", "BPFriends", "BPPersona", "BPHealth", "BPChapters"):
    check(f"{part}", (BP / f"{part}.svelte").is_file())
stage = read(BP / "BPStage.svelte")
check("the stage pulls the next one up and lifts the last one off", "in:riseIn out:liftOut" in stage)
check("and the avatar flies in from its card", "receiveAvatar" in stage and "sendAvatar" in read(BP / "BPQueue.svelte"))
check("the motion setting is obeyed", motion.count("if (!moving())") >= 4)

print("\n== the button sits with the window's own ==")
cluster = app[app.index('<div class="fixed right-2 top-1 z-50'):app.index("onclick={toggleSize}")]
button = app[app.index("{#snippet bigPictureButton()}"):app.index("{/snippet}", app.index("{#snippet bigPictureButton()}"))]
check("a square the size of the window buttons, in their row", "h-7 w-7" in button and "justify-center" in button
      and "{@render bigPictureButton()}" in cluster)
check("the TV alone, no words beside it", ">Big Picture<" not in button and '<Icon name="bigpicture"' in button)
check("the header leaves room for the window's buttons, the speaker beside Big Picture included", "pr-[176px]" in app)
icons = read(WEB / "lib" / "components" / "Icon.svelte")
tv = icons[icons.index("bigpicture:"):].split('"')[1]
import re as _re
# Where each part of it starts: only the absolute moves, since the rest of a
# path is relative offsets and reads as nonsense coordinates.
_starts = [(float(a), float(b)) for a, b in _re.findall(r"M\s*(-?\d+(?:\.\d+)?)[ ,]+(-?\d+(?:\.\d+)?)", tv)]
check("the TV has its screen, its antenna and a play mark", len(_starts) == 3, str(_starts))
# Inset from the edges of the 24 grid, like every other icon: one drawn to the
# edges looks bigger than its neighbours in the window-button cluster.
check("drawn inset from the edges of the grid, like the others",
      all(2 <= x <= 22 and 2 <= y <= 22 for x, y in _starts), str(_starts))

print("\n== nothing runs into the panels at the sides ==")
check("the stage is exactly as wide as its column, whatever the name",
      "grid-template: minmax(0, 1fr) / minmax(0, 1fr)" in stage and "min-width: 0" in stage.split(".bps-layer {")[1][:400])
check("a long name shrinks to fit before it is cut", "use:fitText" in stage and (BP / "fit.ts").is_file())
scenes = read(BP / "BPScenes.svelte")
check("the podium's names are cut short instead of pushing past both sides", "max-width: 30%" in scenes)
check("and so are the chips under it", ".bsc-chip-name" in scenes)
check("a long channel name gives way in a queue card", "max-width: 45%" in read(BP / "BPQueue.svelte"))
check("a long model name in the brain's chain is cut, not spilled", ".bbr-chip-name" in read(BP / "BPBrain.svelte"))

print("\n== each panel as big as what it has to say ==")
check("with nobody waiting the queue's column folds away", "class:no-queue={!railed.length}" in bp
      and ".bp.no-queue .bp-main { --bp-lw: 0px; }" in bp)
check("smoothly, not in a jump", "transition: grid-template-columns" in bp)
check("the queue keeps its width as it folds, so it slides instead of squeezing", "width: var(--bp-lw-open)" in bp)
thoughts = read(BP / "BPThoughts.svelte")
check("thoughts open to the full column only while one is fresh", "is-open" in thoughts and "OPEN_FOR" in thoughts)
check("and fold back to a small card", "flex: 0 1 auto" in thoughts and "transition: flex-grow" in thoughts)
check("feed items give their room back as they go", "out:slideOut" in read(BP / "BPFeed.svelte"))
check("the idle kicker only says everyone is answered when they are", "waiting ?" in scenes
      and "everyone has been answered" in scenes and "waiting in the queue" in scenes)

print("\n== when it is quiet, the people you talk to ==")
check("a memory scene exists, with the summary and the last messages", (BP / "BPMemory.svelte").is_file()
      and "<SummaryText" in read(BP / "BPMemory.svelte") and "person.recent" in read(BP / "BPMemory.svelte"))
check("stored summaries are asked for first, which writes nothing", "api.memorySummary(c.id, false, true)" in bp)
check("new ones are written a handful at a time, well apart", "MEM_WRITES" in bp and "MEM_GAP" in bp)
check("and only while nothing else is on stage", "dir.spotlight) return" in bp.split("async function writeOneMemory")[1][:300])
check("the backdrop is their picture while they are on", 'case "memory":' in bp and 'art: memPerson.avatar' in bp)

print("\n== doing something about the conversation on stage ==")
stage_now = read(BP / "BPStage.svelte")
check("there is a box to write to them from here", "bps-say" in stage_now and "onsend" in stage_now)
check("and the same buttons the Chats tab has",
      "onreply" in stage_now and "oncancel" in stage_now and "onignore" in stage_now)
check("they are wired to the real actions",
      "sendReply(" in bp and "cancelReply(" in bp and "toggleIgnore(" in bp and "sendOwnMessage(" in bp)
check("acting on one holds the stage on it, so it cannot slide away mid-sentence",
      "dir = pick(dir, s.key, now)" in bp)
check("typing a letter is not a shortcut", 'el.tagName === "INPUT"' in bp and "if (typing && e.key" in bp)
check("a half-written line survives the stage moving on and back", "drafts[k]" in stage_now)

print("\n== the model shown is the one on this conversation ==")
usage_src = (ROOT / "app" / "utils" / "usage.py").read_text(encoding="utf-8")
runner_src = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("model events say whose conversation they were for", '"uid"' in usage_src and "CONV" in usage_src)
check("the runner tags them as it writes", "_usage.CONV.set(str(uid))" in runner_src)
check("the view keeps one per person", "byConv" in bp)
check("and the Brain is given that one, not the first in the chain", "active={brainModel}" in bp)
check("saying who it is writing to instead of 'first choice'", "writing to {forName}" in read(BP / "BPBrain.svelte"))

print("\n== the right column turns over by itself ==")
rot = read(BP / "BPRotate.svelte")
check("it has more than one face", '"feed"' in rot and '"today"' in rot and '"people"' in rot)
check("each stays up a while", "const HOLD" in rot)
check("but something arriving keeps the live one up", "beats a summary" in rot)
check("and it says which face is on", "bpr-dots" in rot)
check("a face with nothing on it is skipped, never shown empty",
      "const usable" in rot and 'out.push("feed")' in rot and "top.length" in rot)
check("the dots count the faces it will actually show", "{#each usable as f" in rot)
check("and the feed face looks back further than the live ticker does",
      "FEED_WINDOW" in rot and "15 * 60" in rot)
feed = read(BP / "BPFeed.svelte")
check("the ticker's own window is still short", "window: secs = 30" in feed)
check("but it can be told to look back further, and to say how long ago",
      "window?: number" in feed and "when?: boolean" in feed)

print("\n== the countdown is calm ==")
check("no spinner whipping round a face",
      "bps-spin" not in stage_now and "bpq-spin" not in read(BP / "BPQueue.svelte"))
check("a slow breath instead", "bps-breathe" in stage_now)
check("which is opacity only, so it composites", "opacity: 0.45" in stage_now)
check("and stops when motion is off",
      ':global(:root[data-motion="off"]) .bps-ring .fill' in stage_now)

print("\n== the glows read as light, not neon ==")
hard = []
for _f in sorted(BP.glob("*.svelte")):
    for _m in _re.finditer(r"(?<!0 )0 0 \d+px var\(--color-(?:accent|accent-2|good|warn|bad)\)",
                           _f.read_text(encoding="utf-8")):
        hard.append(f"{_f.name}: {_m.group(0)}")
check("every glow is mixed down rather than left at full strength", not hard, "; ".join(hard[:4]))

# A glow drawn outside an svg's viewBox is cut off square unless the svg lets it
# out, which is what put a hard flat edge under the gauges and the queue rings.
glow_svgs = []
for _f in sorted(BP.glob("*.svelte")):
    _t = _f.read_text(encoding="utf-8")
    for _m in _re.finditer(r"\.([a-z-]+)\s*\{[^}]*drop-shadow", _t):
        glow_svgs.append((_f.name, _m.group(1), _t))
missing = []
for _name, _cls, _t in glow_svgs:
    # the rule that draws the glow, or the svg it belongs to, has to allow overflow
    _near = _t[max(0, _t.index(f".{_cls}")) - 400: _t.index(f".{_cls}") + 700]
    if "overflow: visible" not in _near:
        missing.append(f"{_name}: .{_cls}")
check("no glow is cut off square by the box it is drawn in", not missing, "; ".join(missing[:4]))
check("the action buttons are as tall as the box beside them",
      "height: 48px" in stage_now.split(".bps-btn {")[1][:260], stage_now.split(".bps-btn {")[1][:200])
check("the queue leaves room for a card's glow rather than slicing it",
      "padding: 10px 16px 18px" in read(BP / "BPQueue.svelte"))

print("\n== the whole app, a scene each ==")
director = read(BP / "director.ts")
scenes_src = read(BP / "BPScenes.svelte")
check("the stage has a scene for every part of the app",
      all(f"<{p} " in scenes_src for p in ("BPMemory", "BPAccounts", "BPPictures", "BPFriends", "BPPersona", "BPHealth")))
check("the list is built from what there is to show", "export function cycleFor" in director and "cycleFor({" in bp)
check("friend requests and problems only come round while there are some",
      "friends: friendReqs.length > 0" in bp and "health: urgent.length > 0" in bp)
check("a scene on show is not swapped when the list changes under it", "function placeOf" in director)

print("\n== chapters under the stage ==")
chap = read(BP / "BPChapters.svelte")
check("one for each scene, named", "<BPChapters" in bp and "chapterOrder(cycle)" in bp and "CHAPTER[c].label" in chap)
check("a click or a number key goes straight to one", "ongo={goChapter}" in bp and "/^[1-9]$/.test(e.key)" in bp
      and "showScene(dir, s, cycle" in bp)
check("L, or Live, goes back to the conversations", 'k === "l"' in bp and "onlive={goLive}" in bp)
check("the one on show says how long it has left", "sceneProgress(dir, now)" in bp and "scaleX(var(--p))" in chap)
check("the top bar's faces and pills open their scenes",
      'goChapter("accounts")' in bp and 'goChapter("health")' in bp and 'goChapter("friends")' in bp)

print("\n== it holds still while you look ==")
check("the pointer moving over the stage holds it", "use:pointerActivity={holdStage}" in bp and "dir = hold(dir" in bp)
check("a held scene's clock stands still, so it is not out of time when let go", "function frozen" in director)
check("Space holds a scene as well as a conversation", "!s.spotlight && s.idle && held" in director)
check("anything done in a scene keeps it up a while", bp.count("hold(dir, Date.now() / 1000, MANUAL_HOLD)") >= 4)

print("\n== the accounts ==")
acc = read(BP / "BPAccounts.svelte")
check("each with its banner, its face lit by how it is doing, and its week",
      "a.banner" in acc and "data-tone={t}" in acc and "bpa-week" in acc)
check("paused and resumed from here, in the Accounts page's words",
      'api.accountAction(a.id, "pause")' in bp and "stopped replying" in bp and "is replying again" in bp)
check("a stopped account is drawn greyed, not as if it were on", 'data-state="stopped"' in acc and "grayscale" in acc)
check("the scene fetches fresh detail when it comes up, not every second",
      'scene === "accounts"' in bp and "Date.now() - accountsAt > 20000" in bp)

print("\n== the pictures ==")
pics = read(BP / "BPPictures.svelte")
check("blurred while the Pictures tab's own preference says so", "$picturesBlur && !picsShown" in bp and "blurred" in pics)
check("one button shows them for the rest of the visit", "Show pictures" in pics and "picsShown = true" in bp)
check("H blurs them too", "hideText" in pics and "is-veiled" in pics)
check("a picture the bot sends is marked with who it went to", "sentPictures(evt.attachments" in bp and "Sent to" in pics)
check("and never tints the room while it should be hidden", "if (!picturesBlurred && !hideText && pictures[0])" in bp)

print("\n== friend requests ==")
fr = read(BP / "BPFriends.svelte")
check("accepted or declined from here, with the same call as Chats", "api.friendAction(action, r.id, r.target)" in bp)
check("each look is a call to Discord, so they are not polled hard",
      "20000 - (Date.now() - friendsAt)" in bp and "slowTicks % 5 === 0" in bp)
check("one arriving is noticed from the log straight away", "FRIEND_ASK" in bp and "friendNews(text)" in bp)
check("an account that did not answer keeps its list rather than emptying it", "lists[i] ?? friendReqs.filter" in bp)
check("when it will take them by itself is said plainly", "untilText(r.accept_at, now)" in fr)
check("the last one answered leaves 'all caught up'", "All caught up" in fr)

print("\n== the persona ==")
pe = read(BP / "BPPersona.svelte")
check("who it is, from the opening of its instructions", "personaLines(personaText)" in bp)
check("its mood switched from here, as on the Accounts page", "api.accountMood(a.id, mood)" in bp and "onmood" in pe)
check("the moods are the configured ones (its persona's), not a list of its own", "loadMoods(false, pid)" in bp)

print("\n== health ==")
he = read(BP / "BPHealth.svelte")
check("the same list as the sidebar's dots, not a second poll", "$health.issues" in bp and "api.health" not in bp)
check("each problem opens the page that fixes it", "window.location.hash = `/${route}`" in bp and "onopen" in he)
check("the top bar says at a glance whether all is well", "All good" in bp and "to look at" in bp)

print("\n== the log, and moments that land ==")
check("the log has a face of its own on the right", '"log"' in rot and "{logs}" in bp)
check("log lines are drawn a frame at a time, not a render each", "logBuf" in bp and "requestAnimationFrame" in bp)
fx = read(BP / "fx.ts")
check("a reply going out ends in sparks", "use:sparkOnMount" in read(BP / "BPStage.svelte"))
check("so does accepting a friend or switching a mood", bp.count("burstFrom(el") >= 2)
check("the sparks are off with motion, and never while Big Picture closes",
      "get(motionEnabled)" in fx and "bigPictureExit.on" in fx)
check("new sounds, still made on the spot", all(f'case "{n}"' in sounds for n in ("friend", "accept", "picture", "tap")))
check("a list of every shortcut behind ?", 'e.key === "?"' in bp and "bp-help" in bp)
check("Esc puts that list away before it leaves", "if (help) help = false;" in bp)

print("\n== the stage moving on never breaks the avatar's flight ==")
stage_src = read(BP / "BPStage.svelte")
# A transition's parameters are read when it starts; by the time the face on the
# stage starts leaving, `spot` is the next person, or null when a scene came up.
check("the face on the stage leaves under the key it arrived with",
      "use:flightKey={spot.key}" in stage_src and "out:sendFace|global" in stage_src
      and "out:sendAvatar|global={{ key: spot.key }}" not in stage_src)
check("which it keeps on the element itself", "node.dataset.flight = key" in motion and "dataset.flight" in motion.split("function sendFace")[1][:200])

print("\n== every size of screen ==")
check("a scene taller than the stage keeps its heading in view", "justify-content: safe center" in stage_src
      and all("justify-content: safe center" in read(BP / f"{p}.svelte")
              for p in ("BPScenes", "BPAccounts", "BPPictures", "BPFriends", "BPPersona", "BPHealth", "BPMemory")))
check("and is cut at the stage's foot rather than drawn over the chapters", "overflow: clip" in scenes_src
      and "overflow-clip-margin" in scenes_src)
check("on a phone the view scrolls, and the stage grows with its scene",
      "min-height: auto; }" in bp.split("@media (max-width: 720px)")[1] and "flex: none" in stage_src)
check("accounts become rows where cards would not fit", "class:is-rows={rows}" in acc and ".bpa-card.is-row" in acc)
check("the persona tightens on a narrow or short stage", "class:is-tight={tight}" in pe and "lines.slice(0, 5)" in pe)
check("the picture is as tall as leaves room for the wall", "--frame-h" in pics and "var(--frame-h" in pics)
check("and shown whole, in its own shape: the frame takes each picture's proportions, learned as it loads",
      "img.naturalWidth / img.naturalHeight" in pics and 'style="width: {frame.w}px; height: {frame.h}px"' in pics
      and "if (w > maxW)" in pics)
check("easing from one shape to the next", "transition: width 0.8s var(--spring), height 0.8s var(--spring);" in pics)
check("with barely a drift, which would only cut into it now", "to { transform: scale(1.035); }" in pics)
check("its description drawn, not printed with its asterisks", "{@html discordInline(cur.description)}" in pics)
check("the chapter on show is kept in view when they do not all fit", "scrollBy" in chap)
check("a short screen gives the Brain's gauges up first", "@media (max-height: 800px)" in read(BP / "BPBrain.svelte"))
check("the right column's last panel is cut at its edge, not spilled", "overflow: hidden" in rot.split(".bpr {")[1][:500])

print("\n== small things that make it feel right ==")
check("a picture sent while the gallery is up is put up at once", "seenSent" in pics)
check("answered friend cards leave a gap the rest glide into", "animate:flip" in fr)
check("friend requests are not counted in red, only problems are", 'data-tone={tones[c] ?? "accent"}' in chap)
check("the health heading counts what the top bar counts", "const serious" in he)
check("an account with no name yet is called what the Accounts page calls it", "platformName(a.platform)" in bp)

print("\n== the room is whoever is on stage ==")
bpb = read(BP / "BPBackdrop.svelte")
sky = read(BP / "sky.ts")
check("a moving background drawn by the graphics card", "Sky.create(" in bpb and 'getContext("webgl"' in sky)
worker = read(BP / "sky.worker.ts")
check("drawn in a worker, off the page's own thread", "transferControlToOffscreen()" in bpb
      and 'new Worker(new URL("./sky.worker.ts", import.meta.url)' in bpb and "Sky.create(m.canvas" in worker)
check("and on the page only where it cannot be handed over, once the view has arrived",
      "sky = inWorker(c);" in bpb and "lightUp = setTimeout(async" in bpb)
check("its shader compiled without holding the page up", "KHR_parallel_shader_compile" in sky
      and "COMPLETION_STATUS_KHR" in sky)
check("told its size, never reading the layout every frame", "resize(w: number, h: number)" in sky
      and "clientWidth" not in sky.split("private draw()")[1] and "new ResizeObserver(" in bpb)
check("the pointer is sent once a frame at most", "if (queued) return;" in bpb)
check("in the colours of whoever is on stage, read from their picture", "loadPalette(a)" in bpb and "art: spot.u.avatar" in bp)
check("the same person brings the same weather, in a conversation or a memory",
      "look: lookFor(spot.u.id)" in bp and "look: lookFor(memPerson.id)" in bp)
check("each scene has its own", "SCENE_LOOK.accounts" in bp and "SCENE_LOOK.persona" in bp)
check("one room melts into the next rather than cutting", "private ease(" in sky and "Math.exp(-dt" in sky)
check("livelier while a reply is written and typed", "energy: energyFor(" in bp and "u_energy" in sky)
check("the blooms bounce like the app's jelly when the reply on stage goes out", "roomPulse += 1" in bp and "float bounce" in sky)
check("still a dark room: tone-mapped and capped", "min(col, vec3(0.45))" in sky and "1.0 - exp(-col" in sky)
check("soft blooms like the app's own background, no texture: no noise, no seams, no stars",
      "float bloom(" in sky and "snoise" not in sky and "fbm" not in sky and "seam" not in sky)
check("dithered, so its dark gradients do not band", "1.5 / 255.0" in sky)
check("smooth: half the resolution at about sixty frames a second, so the lights glide rather than step",
      "scale = 1 / 2" in sky and "1 / 66" in sky and "scale: 1 / 2" in bpb)
check("with a fixed dither, which does not shimmer once stretched", "hash21(gl_FragCoord.xy)" in sky
      and "fract(u_time" not in sky)
check("one still frame with the app's motion setting off", "setStill(!$motionEnabled)" in bpb and "if (this.still)" in sky)
check("not Windows' animation setting, which froze it on this PC", "prefers-reduced-motion" not in bpb)
check("a CSS room in the same colours where WebGL is not to be had", "flat = true" in bpb and "var(--c0)" in bpb)
check("it gives the graphics card back when Big Picture closes", "loseContext()" in sky)

print("\n== text reads cleanly over it ==")
check("no smudge of shadow behind any text", not [f.name for f in BP.glob("*.svelte") if "text-shadow" in read(f)])
for _name, _sel in (("BPStage", ".bps-name {"), ("BPMemory", ".bpm-name {"), ("BPPersona", ".bpe-name {"), ("BPAccounts", ".bpa-name {")):
    # The rule of its own, at the start of a line: a compact variant may come earlier in the file.
    _rule = read(BP / f"{_name}.svelte").split("\n  " + _sel)[1][:700]
    check(f"a big name in {_name} has room for an emoji", "padding-block: 0.1em" in _rule and "line-height: 1.16" in _rule)
check("a chapter's icon sits in the middle of its button", ".bpc-ch { gap: 0; padding: 0 9.5px; }" in chap)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
