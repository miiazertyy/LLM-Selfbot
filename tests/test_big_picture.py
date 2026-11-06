"""Big Picture Mode: the whole screen, a set of pages about everything the bots do, live.

A button at the top right (and Ctrl+Shift+B, and Ctrl+K) opens a full-screen
view. Left alone it plays: whoever is being answered goes on stage, and when
nobody is it walks round the same pages anyone can walk into. Reach out and
everything on screen can be pressed, with the mouse, the keys or a gamepad, and
nothing is taken from under you meanwhile. Each fact lives in one place. It takes
the whole screen and gives it back; it reads a conversation's history by itself
only for the one on stage, at most once every twenty seconds.
"""
import re
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
    return Path(p).read_text(encoding="utf-8").replace("\r\n", "\n")


def styles(text):
    """What a .svelte file's <style> says, without its comments, or a .css file's."""
    found = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S)
    return re.sub(r"/\*.*?\*/", "", "\n".join(found) if found else text, flags=re.S)


bp = read(BP / "BigPicture.svelte")
world = read(BP / "world.svelte.ts")
css = read(BP / "bp.css")
every_part = {f.name: read(f) for f in BP.iterdir() if f.suffix in (".svelte", ".ts", ".css")}

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
check("it enters on open and gives the screen back on close",
      "setFullscreen(true)" in bp and "setFullscreen(false)" in bp)
check("Esc leaves, once there is nothing to go back from", 'e.key === "Escape"' in bp and "function goBack()" in bp)

print("\n== light on the account ==")
check("history is read only when not already loaded", "get(conversations)[k]" in bp and "asked.has(k)" in bp)
check("at most once every twenty seconds", "Date.now() - lastHistory < 20000" in bp)
check("opening someone by hand reads them at once, as Chats does", "function openPerson(p: Person)" in bp
      and "loadConversation(p.target, p.id)" in bp)
check("the Chats feed is not started a second time", "startChatLive" not in bp and "startChatLive" not in world)
check("everything stops with the page hidden", bp.count("document.hidden") >= 2)
check("what is not on screen is not asked for: each page says when it comes up", "ensure(page: Page)" in world
      and "world.ensure(p)" in bp)

print("\n== it leaves in one quick fade ==")
motion = read(BP / "motion.ts")
stores = read(WEB / "lib" / "stores.ts")
check("nothing inside waits to finish while it closes", motion.count("bigPictureExit.on") >= 6)
check("and its clock stops at once, not after the fade", "const gone = () => !get(bigPicture);" in bp
      and "document.hidden || gone()" in bp)
check("every open and close goes through one place", "export function setBigPicture(" in stores
      and "setBigPicture(false)" in bp)

print("\n== opening and closing are light ==")
app_css = read(WEB / "app.css")
poll = read(WEB / "lib" / "poll.ts")
enter_leave = bp[bp.index("function enter("):bp.index("</script>")]
check("the entrance and the exit move opacity and scale only, no blur the size of the screen",
      "blur(" not in enter_leave and "opacity:${t}; transform: scale(" in enter_leave)
check("the app underneath fades out, then is not drawn at all while covered",
      "class:is-under={$bigPictureArriving}" in app and "class:is-covered={$bigPictureCovering}" in app
      and ".app-shell.is-covered { content-visibility: hidden; }" in app_css)
check("its moving background stops under it", ":root .app-backdrop.is-covered::before," in app_css
      and "animation-play-state: paused" in app_css)
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
      "function onceArrived(" in bp and "world.loadFriends()" in bp and "arrived = true;" in bp)
check("its code is fetched before the first open, while the app is idle", "requestIdleCallback" in app
      and "loadBigPicture()" in app)
check("pages under it stop polling, except the health it shows", "bigPictureCovering.subscribe(" in poll
      and "visiblePoll(() => { pollHealth(); refreshSocials(); }, 15000, { underBigPicture: true })" in app)

print("\n== the same words as Chats ==")
chats = read(WEB / "pages" / "Chats.svelte")
check("Chats uses the shared reply stages", 'from "../lib/chatstatus"' in chats and "function statusOf" not in chats)
check("and so does Big Picture", 'from "../chatstatus"' in bp)

print("\n== the director, where an arrow lands, and what the pages work out ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "bigpicture_director.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("bigpicture_director.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print("\n== all of it there ==")
for part in ("BPBackdrop", "BPNav", "BPHints", "BPNow", "BPQueue", "BPStage", "BPRail", "BPPeople", "BPAccounts", "BPToday",
             "BPPersona", "BPPictures", "BPMinecraft", "BPInbox", "BPWho", "Rolling"):
    check(f"{part}", (BP / f"{part}.svelte").is_file())
for part in ("BPScenes", "BPChapters", "BPStats", "BPRotate", "BPThoughts", "BPFeed", "BPBrain", "BPMemory", "BPFriends", "BPHealth",
             "BPPlatforms", "BPWave", "Counter"):
    check(f"{part} is gone", not (BP / f"{part}.svelte").exists() and f"import {part}" not in "".join(every_part.values()))

print("\n== the button sits with the window's own ==")
cluster = app[app.index('<div class="fixed right-2 top-1 z-50'):app.index("onclick={toggleSize}")]
button = app[app.index("{#snippet bigPictureButton()}"):app.index("{/snippet}", app.index("{#snippet bigPictureButton()}"))]
check("a square the size of the window buttons, in their row", "h-7 w-7" in button and "justify-center" in button
      and "{@render bigPictureButton()}" in cluster)
check("the TV alone, no words beside it", ">Big Picture<" not in button and '<Icon name="bigpicture"' in button)
check("the header leaves room for the window's buttons, the speaker beside Big Picture included", "pr-[176px]" in app)
icons = read(WEB / "lib" / "components" / "Icon.svelte")
tv = icons[icons.index("bigpicture:"):].split('"')[1]
# Where each part of it starts: only the absolute moves, since the rest of a
# path is relative offsets and reads as nonsense coordinates.
_starts = [(float(a), float(b)) for a, b in re.findall(r"M\s*(-?\d+(?:\.\d+)?)[ ,]+(-?\d+(?:\.\d+)?)", tv)]
check("the TV has its screen, its antenna and a play mark", len(_starts) == 3, str(_starts))
# Inset from the edges of the 24 grid, like every other icon: one drawn to the
# edges looks bigger than its neighbours in the window-button cluster.
check("drawn inset from the edges of the grid, like the others",
      all(2 <= x <= 22 and 2 <= y <= 22 for x, y in _starts), str(_starts))

print("\n== pages you walk into, and a tour that walks them by itself ==")
nav = read(BP / "BPNav.svelte")
director = read(BP / "director.ts")
scenes = read(BP / "scenes.ts")
check("every page by name along the top, not an icon to guess at", "{PAGE[t].label}" in nav and 'label: "People"' in scenes)
check("a pill glides to the one on show", "use:glide=" in nav and "glide-mark" in nav)
check("with a line in it that fills as its time runs", "scaleX(var(--p))" in nav and "pageProgress(dir, now)" in bp)
check("the tour is the same pages: one list of them", "tourFor(" in bp and "tabsFor(" in bp and "export function tourFor" in director)
check("each opened by a press or a number", "ongo={goPage}" in bp and "/^[1-9]$/.test(e.key)" in bp)
check("Q and E go to the page before and after", 'k === "q"' in bp and 'k === "e"' in bp and "function stepPage(" in bp)
check("a page slides in from the way it was gone to", "in:pageIn={{ dir: slide }} out:pageOut={{ dir: slide }}" in bp
      and "export function pageIn(" in motion)
check("the tab for what needs you, and Minecraft, only while there is something in them",
      "tabsFor({ minecraft: !!world.minecraft" in bp and 'inbox: inboxCount > 0 || page === "inbox"' in bp)

print("\n== each fact lives in one place ==")
hints = read(BP / "BPHints.svelte")
check("the day's numbers: Today, with three on the bottom bar that open it", 'onscore={() => goPage("today")}' in bp
      and 'showScore={page !== "today"}' in bp)
check("the accounts: their page, with their faces on the top bar that open it", 'onclick={() => ongo?.("accounts")}' in nav)
check("what just happened: one list, not a turning panel", "<BPRail" in read(BP / "BPNow.svelte"))
check("only one thing moves by itself: nothing else keeps a clock to turn over on", "const HOLD" not in read(BP / "BPRail.svelte"))
check("a single helper says how long ago, not one per page", "export function ago(" in scenes
      and not [n for n, t in every_part.items() if re.search(r"function ago\(", t) and n != "scenes.ts"])

print("\n== nothing is taken from under you ==")
check("the Now tab says who is being answered, in faces, instead of going to them", "live={groups.answering}" in bp and "bpn-faces" in nav)
check("Auto says who has the screen, and how long is left", "autoState(dir, now)" in bp and "stroke-dashoffset: {C * (1 - ring)}" in nav
      and "export function autoState" in director)
check("Auto comes back forty-five seconds after the last thing done", "MANUAL_HOLD = 45" in director)
check("anything at all keeps a drive a drive", "Math.max(secs, state.holdFor)" in director)
check("Space stays put for good", "togglePin(dir)" in bp and 'e.key === " "' in bp)
check("the pointer moving holds it: nothing slides away from under a click", "use:pointerActivity={holdStage}" in bp)
check("a held page's clock stands still, so it is not out of time when let go", "function frozen" in director)
check("something done on a page keeps it up a while", world.count("this.hooks.hold(MANUAL_HOLD)") >= 4)
check("a conversation opened from a page goes back there", "cameFrom = was;" in bp and 'cameFrom ? "Back" : "Leave"' in bp)

print("\n== one highlight, whatever is moving it ==")
focus = read(BP / "focus.ts")
check("one plate, on a spring, told where to go", 'class="bp-plate" use:focusPlate' in bp and "translate3d(${box.x}px, ${box.y}px, 0)" in focus
      and "spring = p.animate([" in focus)
check("by transform alone: easing its size had the page laid out again every frame of every move",
      "transition: opacity 0.22s ease;" in css.split(".bp-plate {")[1].split("}")[0] and "width 0.42s" not in css)
check("the pointer moves it", 'node.addEventListener("pointerenter", enter)' in focus)
check("so do the arrow keys, to wherever is nearest that way", "moveFocus(" in bp and "nextFocus(boxes" in focus)
check("and at the edge of what there is it bumps", "function bump(dir: Dir)" in focus)
check("each step ticks, softer when the pointer did it", 'play("tick", { p: pitch(el), level: via === "pointer" ? 0.4 : 1 })' in focus)
check("it reads the layout only while something is moving", "if (performance.now() < followUntil) frame = requestAnimationFrame(place);" in focus)
check("Enter is the same as pressing it, seen and heard", "export function pressFocus()" in focus and "el.click();" in focus)
check("a page opened from the keys takes the focus with it", "focusPage(m)" in bp)
check("the room's light drifts behind what has it", "$focusAt" in bp and "focus={lightX} focusY={lightY}" in bp
      and "gl.uniform2f(L.u_focus, this.focus, this.focusY);" in read(BP / "sky.ts"))
pressable = sum(t.count("use:focusable") for n, t in every_part.items() if n.endswith(".svelte"))
check("everything to press can have it", pressable >= 30, str(pressable))
for part in ("BPPeople", "BPAccounts", "BPToday", "BPQueue", "BPRail", "BPInbox", "BPNav"):
    check(f"  on {part}", "use:focusable" in every_part[f"{part}.svelte"])

print("\n== the keys tell themselves, and a pad does what they do ==")
pad = read(BP / "gamepad.ts")
check("the bottom bar lists the keys that work now", "const hints = $derived.by<Key[]>" in hints and "canReply" in hints)
check("and a pad's buttons once a pad is in use", 'mode === "pad" ? h.pad : h.keys' in hints)
check("the whole list unrolls out of the bar, no dimmed window", 'class="bph-list unroll is-up" use:unroll' in hints
      and "backdrop" not in styles(hints))
check("the standard layout, a direction repeating as a key does", "12: \"up\"" in pad and "FIRST_REPEAT" in pad and "NEXT_REPEAT" in pad)
check("nothing runs until a pad has been seen", 'addEventListener("gamepadconnected", wake)' in pad)
check("wired to the same things the keys are", "startGamepad(onPad)" in bp and "function onPad(cmd: PadCommand)" in bp)
check("typing a letter is not a shortcut", 'el.tagName === "INPUT"' in bp and "if (typing && e.key" in bp)
check("Esc steps out of the box first", "(el as HTMLElement).blur();" in bp)
check("a press or a key on the bar does the same", "disabled={!h.run}" in hints)

print("\n== Now ==")
now_page = read(BP / "BPNow.svelte")
stage = read(BP / "BPStage.svelte")
queue = read(BP / "BPQueue.svelte")
rail = read(BP / "BPRail.svelte")
check("the queue read in the order it matters", "groupQueue(" in bp and '"Answering"' in queue and '"Up next"' in queue and '"Waiting on you"' in queue)
check("one flat list, so a row glides between them", "animate:flip" in queue and "{#each items as it (it.key)}" in queue)
check("what is waiting on you folds past a few, and opens in place", "const FOLD" in queue and "unfolded" in queue)
check("Reply now on a row, as the pointer comes", "bpq-now" in queue and ".bpq-rowwrap:hover .bpq-now" in queue)
check("brought into view in its own list, never by scrolling the view away from the stage", "scrollIntoView" not in queue and "list.scrollBy(" in queue)
check("the stage's buttons say what can be done now", "canHurry" in stage and "canCancel" in stage and "{#if spot.ignored}" in stage)
check("wired to the real actions", "sendReply(" in bp and "cancelReply(" in bp and "toggleIgnore(" in bp and "sendOwnMessage(" in bp)
check("acting on one holds the stage on it, so it cannot slide away mid-sentence", "dir = pick(dir, s.key, now)" in bp)
check("a half-written line is the Chats tab's own draft", "$drafts[draftKey]" in stage and "setDraft(draftKey" in stage)
check("six slim segments for where the reply is", "bps-track" in stage and "repeat(6, minmax(0, 1fr))" in stage)
check("each run of messages has one face and one time", "runsOf(shown)" in stage and "m.ts && ends[i]" in stage)
check("what it is thinking in the conversation, where the reply will land", "bps-thought" in stage and "thought={stageThought}" in bp)
check("folded away when it goes", "transition:slide" in stage and "thoughtOnStage" in bp)
check("the stage pulls the next one up and lifts the last one off", "in:riseIn out:liftOut" in now_page)
check("and the face flies in from its row", "receiveAvatar" in stage and "sendAvatar" in queue)
check("the face on the stage leaves under the key it arrived with", "use:flightKey={spot.key}" in stage and "out:sendFace|global" in stage
      and "node.dataset.flight = key" in motion)
check("with nobody on stage, the time, big, and how things stand", "bpw-clock" in now_page and "Everyone's answered" in now_page)
check("and its figures roll over on wheels", "<Odometer value={figures} />" in now_page)
check("the rails slide out of the way, keeping their width", "class:no-queue={!inQueue}" in now_page and "transition: grid-template-columns" in now_page
      and "width: var(--q)" in now_page)
check("the model on stage is the one on this conversation", '"uid"' in read(ROOT / "app" / "utils" / "usage.py")
      and "_usage.CONV.set(str(uid))" in read(ROOT / "app" / "platforms" / "discord_runner.py") and "world.byConv[spot.u.id]" in now_page)
check("what just happened opens the conversation it was about", "onopen?.(it.target!, it.uid!)" in rail and "target?: string;" in read(BP / "types.ts"))
check("and does not open empty", "seedFeed(rows: QRow[])" in world and "loadBacklog()" in world)
check("a thought is not put on the rail once it has been on the stage", "latestThought.at !== thoughtOnStage" in bp)

print("\n== People ==")
people = read(BP / "BPPeople.svelte")
check("everyone, on every account, once", "api.chatArchive(PEOPLE_PER_ACCOUNT, a.id)" in world and "mergePeople(lists)" in world)
check("a shelf along the bottom, the one in hand large above it", "bpe-shelf" in people and "bpe-hero" in people)
check("moving along it brings the card and the room with it", "onfocus: () => choose(p)" in people and 'act.light("people", { seed: p.id, art: p.avatar })' in people)
check("which only ever reads what is stored: no messages, no model", "api.memorySummary(id, false, true)" in world
      and "loadConversation" not in people)
check("a new summary only when pressed for, or a handful by themselves, well apart", "writeSummary(hero)" in people and "MEM_WRITES" in world and "MEM_GAP" in world)
check("and those only while nobody is on stage", "world.writeOneSummary(!dir.spotlight)" in bp)
check("pressing someone opens them", "act.openPerson(p)" in people)
check("the people talked to most, with their medals", "<RankBadge n={i + 1} size={26} quiet />" in people)
check("on the tour, someone new each time, with something written first", "world.turn" in people and "written.length ? written" in people)

print("\n== Accounts ==")
acc = read(BP / "BPAccounts.svelte")
check("each with its banner, its state and its week", "a.banner" in acc and "data-tone={t}" in acc and "bpa-week" in acc)
check("as big as the page has room for", "const cols = $derived.by" in acc and "repeat(var(--cols, 3)" in acc)
check("a card grows where it stands, and Esc puts it back", "async function rearrange(" in acc and "act.onBack(close)" in acc)
check("by transform and opacity alone: nothing painted again every frame", "clipPath" not in acc and "transformOrigin: \"0 0\"" in acc
      and "part.animate([{ opacity: 0 }" in acc)
check("no figure counted up in text, which repaints the card it is in every frame", "Counter" not in "".join(every_part.values())
      and "<Rolling value={act7?.today ?? 0} />" in acc)
check("the accent melts in ten steps set from code: a CSS transition styled the whole view every frame",
      "const MELT_STEPS = 10;" in bp and "--bp-accent" not in css)
check("a ring's arc too: four steps a second, not a style pass every frame for as long as it is open",
      all("transition: stroke-dashoffset 1s steps(4, jump-none);" in every_part[f] for f in ("BPNav.svelte", "BPQueue.svelte", "BPStage.svelte"))
      and not [n for n, t in every_part.items() if "stroke-dashoffset 1s linear" in t])
check("and a ring breathes on an svg of its own, which the graphics card fades by itself",
      ".bpq-ring.is-fill { animation: bpq-breathe" in queue and ".bps-ring.is-fill { animation: bps-breathe" in stage)
check("no dimmed window behind it", "Modal" not in acc)
check("paused and resumed from there, in the Accounts page's words", 'api.accountAction(a.id, "pause")' in world and "stopped replying" in world and "is replying again" in world)
check("put in a mood from there", "api.accountMood(a.id, mood)" in world and "world.setMood(a, m, e.currentTarget)" in acc)
check("every platform's logo, with its week, to show only that one's", "api.statsDetail(7)" in world and "setFilter(p.id)" in acc)
check("a stopped one is drawn greyed", 'data-state="stopped"' in acc and "grayscale" in acc)
check("fresh detail when the page comes up, not every second", "Date.now() - this.accountsAt > 20_000" in world)
check("watching a Minecraft account from its card", "<BPMinecraft account={a} inset />" in acc)

print("\n== Today ==")
today = read(BP / "BPToday.svelte")
check("the day's numbers count every platform", "api.statsDetail(1)" in world and "api.statsOverview" not in world and "api.statsOverview" not in bp)
check("the last 24 hours in order", "lastDay(d?.hourly" in world)
check("the wheels roll up as it lands", "<Rolling value={day.replies}" in today and "<Odometer value={text} />" in read(BP / "Rolling.svelte"))
check("sweep across the hours and the day plays its shape", "function fromPointer(e: PointerEvent)" in today and 'uiPlay("pluck", { p: hours[i].count / peak' in today)
check("the bars grow in with a note each, heard when it was opened by hand", "growIn(barsEl," in today and "driven" in today)
check("where it went, each opening those accounts", "toPlatform(p.id)" in today)
check("every model that can write one, in order, with what it has left", "plan?.replies" in today and "bpd-mleft" in today)

print("\n== the bot's own ==")
persona = read(BP / "BPPersona.svelte")
pics = read(BP / "BPPictures.svelte")
who = read(BP / "BPWho.svelte")
check("who it is, from the opening of its instructions", "personaLines(this.personaText)" in world)
check("its mood switched from there", "world.setMood(a, m, e.currentTarget)" in persona)
check("the moods are the configured ones (its persona's), not a list of its own", "loadMoods(false, pid)" in world)
check("every persona there is, not the first running Discord account's", "<BPWho" in persona and "<BPWho" in pics and "function chooseFace(" in bp and "c.persona === current" in who)
check("pictures blurred while the Pictures tab's own preference says so", "$picturesBlur && !picsShown" in bp and "blurred" in pics)
check("one button shows them for the rest of the visit", "Show pictures" in pics and "picsShown = true" in bp)
check("H blurs them too", "hideText" in pics and "is-veiled" in pics)
check("a picture the bot sends is marked with who it went to", "sentPictures(evt.attachments" in world and "Sent to" in pics)
check("and never tints the room while it should be hidden", 'act.light("pictures", cur && !veiled' in pics)
check("shown whole, in its own shape: the frame takes each picture's proportions, learned as it loads",
      "img.naturalWidth / img.naturalHeight" in pics and 'style="width: {frame.w}px; height: {frame.h}px"' in pics and "if (w > maxW)" in pics)
check("easing from one shape to the next", "transition: width 0.8s var(--spring), height 0.8s var(--spring);" in pics)
check("its description drawn, not printed with its asterisks", "{@html discordInline(cur.description)}" in pics)

print("\n== Needs you ==")
inbox = read(BP / "BPInbox.svelte")
check("accepted or declined from there, with the same call as Chats", "api.friendAction(action, r.id, r.target)" in world)
check("each look is a call to Discord, so they are not polled hard", "FRIENDS_EVERY - (Date.now() - this.friendsAt)" in world and "ticks % 5 === 0" in world)
check("one arriving is noticed from the log straight away", "FRIEND_ASK" in world and "this.friendNews(text)" in world)
check("an account that did not answer keeps its list rather than emptying it", "lists[i] ?? this.friends.filter" in world)
check("when it will take them by itself is said plainly", "untilText(r.accept_at, now)" in inbox)
check("the last one answered leaves 'all caught up'", "All caught up" in inbox)
check("answered cards leave a gap the rest glide into", "animate:flip" in inbox)
check("the same list as the sidebar's dots, not a second poll", "$health.issues" in bp and "api.health" not in bp and "api.health" not in world)
check("each problem opens the page that fixes it", "window.location.hash = `/${route}`" in bp and "act.leaveTo(it.route)" in inbox)
check("counted the way the tab counts: an update is a note, not a problem", 'i.level === "error" || i.level === "warn"' in bp and "const serious" in inbox)
check("no Accept in the colour of an error", "room.palette || !roomColour" in bp)

print("\n== the look: flat, quiet, and the room's ==")
sheets = {n: styles(t) for n, t in every_part.items() if n.endswith((".svelte", ".css"))}
for label, rx in (("no frosted glass, which has to be worked out again every frame the room moves", r"backdrop-filter\s*:"),
                  ("no rim round anything", r"inset 0 0 0 [\d.]+px"),
                  ("no spaced capitals", r"letter-spacing:\s*0\.[1-9]"),
                  ("no monospace", r"monospace")):
    bad = [n for n, t in sheets.items() if re.search(rx, t)]
    check(label, not bad, ", ".join(bad))
check("no sci-fi grid behind it", "bpb-grid" not in every_part["BPBackdrop.svelte"])
check("tiles, chips and buttons take the tint every button in the app has", all(c in app_css.split("Buttons with depth")[1].split("@layer components")[1][:900]
                                                                               for c in (".bp-btn", ".bp-chip", ".bp-tile")))
check("the old classes have left that list", ".bps-btn" not in app_css and ".bpq-card" not in app_css and ".bpfr-btn" not in app_css)
check("one stylesheet for what the pages are made of", 'import "./bp.css";' in bp and ".bp-tile {" in css and ".bp-row {" in css and ".bp-btn {" in css)
check("theme ink, not hard white", "color: var(--color-ink);" in css and "color: #fff;" not in styles(every_part["BPStage.svelte"]))
check("the accent is the room's, melting along with it", 'el.style.setProperty("--color-accent", rgbCss(c));' in bp and "bind:this={bpEl}" in bp)
check("and what is written on it reads, whichever way the room has gone", 'el.style.setProperty("--bp-on", onColour(c));' in bp
      and "color: var(--bp-on)" in css)
check("rows sit straight on the room", ".bp-row {" in css and "background" not in css.split(".bp-row {")[1].split("}")[0])
check("H blurs what is marked, in one place", 'class:is-private={hideText}' in bp and ".bp.is-private [data-private]" in css
      and "data-private" in stage and "data-private" in people)
for _name, _sel in (("bp.css", ".bp-name {"), ("BPPersona.svelte", ".bpz-name {"), ("BPAccounts.svelte", ".bpa-name {")):
    # The rule of its own: a compact variant may come earlier in the file.
    _rule = every_part[_name].split(_sel)[1][:520]
    check(f"a big name in {_name} has room for an emoji", "padding-block: 0.1em" in _rule and "line-height: 1.16" in _rule)
check("no smudge of shadow behind any text", not [n for n, t in sheets.items() if "text-shadow" in t])
check("a long name shrinks to fit before it is cut", "use:fitText" in stage and (BP / "fit.ts").is_file())

print("\n== sounds ==")
sounds = read(BP / "sounds.ts")
uisound = read(WEB / "lib" / "uisound.ts")
check("the bots' sounds on by default now, and remembered", 'persisted<boolean>("bigPictureSound", true' in stores)
check("made by the app's own, sharing one room and one volume", 'from "../uisound"' in sounds and "createOscillator" not in sounds)
check("and the speaker silences them", "!get(uiSound)" in sounds)
check("never a burst", "const GAP: Record<Sound, number>" in sounds)
check("Big Picture opening has a swell of its own, and a page sliding in a breath of air", 'case "dawn":' in uisound and 'case "whoosh":' in uisound
      and 'uiPlay("dawn")' in bp and 'uiPlay("whoosh")' in bp)
check("a page landing is heard when it was gone to by hand, booked to go with its tiles", "export function arrivals(" in sounds and "arrivals(6)" in bp)
check("not on the tour: a page turning by itself every ten seconds would be a clock in the room",
      bp.index("function afterGoing()") < bp.index('uiPlay("whoosh")') and "afterGoing" not in bp.split("// ── The queue")[1].split("function goPage")[0])
check("something done by hand always answers, whatever the bots' switch says", 'uiPlay("done")' in world and 'uiPlay("glint"' in world)
fx = read(BP / "fx.ts")
check("a reply going out ends in sparks", "use:sparkOnMount" in stage)
check("so does accepting a friend or switching a mood", world.count("burstFrom(el") >= 2)
check("the sparks are off with motion, and never while Big Picture closes", "get(motionEnabled)" in fx and "bigPictureExit.on" in fx)

print("\n== the room is whoever is on stage ==")
bpb = read(BP / "BPBackdrop.svelte")
sky = read(BP / "sky.ts")
worker = read(BP / "sky.worker.ts")
check("a moving background drawn by the graphics card", "Sky.create(" in bpb and 'getContext("webgl"' in sky)
check("drawn in a worker, off the page's own thread", "transferControlToOffscreen()" in bpb
      and 'new Worker(new URL("./sky.worker.ts", import.meta.url)' in bpb and "Sky.create(m.canvas" in worker)
check("and on the page only where it cannot be handed over, once the view has arrived",
      "sky = inWorker(c);" in bpb and "lightUp = setTimeout(async" in bpb)
check("its shader compiled without holding the page up", "KHR_parallel_shader_compile" in sky and "COMPLETION_STATUS_KHR" in sky)
check("told its size, never reading the layout every frame", "resize(w: number, h: number)" in sky
      and "clientWidth" not in sky.split("private draw()")[1] and "new ResizeObserver(" in bpb)
check("the pointer is sent once a frame at most", "if (queued) return;" in bpb)
check("in the colours of whoever is on stage, read from their picture", "loadPalette(a)" in bpb and 'art: spot.u.avatar' in bp)
check("the same person brings the same weather, in a conversation or on People",
      "look: lookFor(spot.u.id)" in bp and 'page === "people" ? lookFor(pageLight.seed)' in bp)
check("each page has its own", "PAGE_LOOK[page]" in bp and "PAGE_LOOK: Record<Page, LookName>" in read(BP / "looks.ts"))
check("one room melts into the next rather than cutting", "private ease(" in sky and "Math.exp(-dt" in sky)
check("livelier while a reply is written and typed", "energy: energyFor(" in bp and "u_energy" in sky)
check("the blooms bounce like the app's jelly when the reply on stage goes out", "pulse: () => (roomPulse += 1)" in bp and "float bounce" in sky)
check("a page leaving does not take the room from the page arriving", "pageLight?.page === from" in bp and "pageLight?.page === page" in bp)
check("still a dark room: tone-mapped and capped", "min(col, vec3(0.45))" in sky and "1.0 - exp(-col" in sky)
check("soft blooms like the app's own background, no texture: no noise, no seams, no stars",
      "float bloom(" in sky and "snoise" not in sky and "fbm" not in sky and "seam" not in sky)
check("dithered, so its dark gradients do not band", "1.5 / 255.0" in sky)
check("smooth: half the resolution at about sixty frames a second, so the lights glide rather than step",
      "scale = 1 / 2" in sky and "1 / 66" in sky and "scale: 1 / 2" in bpb)
check("with a fixed dither, which does not shimmer once stretched", "hash21(gl_FragCoord.xy)" in sky and "fract(u_time" not in sky)
check("one still frame with the app's motion setting off", "setStill(!$motionEnabled)" in bpb and "if (this.still)" in sky)
check("not Windows' animation setting, which froze it on this PC", "prefers-reduced-motion" not in bpb)
check("a CSS room in the same colours where WebGL is not to be had", "flat = true" in bpb and "var(--c0)" in bpb)
check("it gives the graphics card back when Big Picture closes", "loseContext()" in sky)

print("\n== every platform, every size of screen ==")
check("switched-off socials show nowhere", "platformOn(on, a.platform)" in world and "sourceOn($socialsOn, t.source)" in bp)
check("the bot that controls the app is no account", 'a.platform !== "controller"' in world)
check("one that has never connected is called what the Accounts page calls it", "platformName(a.platform)" in world)
check("on a phone the view scrolls, and each page is as tall as what is on it", "overflow-y: auto; grid-template-rows: auto auto auto; align-content: start;" in bp)
check("with its conversation still there", "flex: none; max-height: 56vh;" in stage)
check("and the rails give way on narrower screens first", "@media (max-width: 1100px)" in now_page)
check("a short screen keeps the conversation's room", "@media (max-height: 720px)" in stage)
check("the tab on show is kept in view when they do not all fit", "box.scrollBy(" in nav)
check("the motion setting is obeyed", motion.count("if (!moving())") >= 5)
check("nothing that moves forever is blurred", not [n for n, t in sheets.items()
                                                    if re.search(r"\{[^}]*filter:\s*blur[^}]*infinite[^}]*\}|\{[^}]*infinite[^}]*filter:\s*blur[^}]*\}", t)])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
