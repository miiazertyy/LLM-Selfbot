"""Tabs that open with something to see and hear, each asked for.

  * one way for a list or a grid to arrive (lib/domino.ts): its items pop in one after another with a little jelly,
    each a note up the scale, booked with the item's own CSS delay, after its block has landed, only what is seen
  * Chats: the inbox, the friend requests and the recent conversations come in that way, the all-clear check chimes
  * Settings > Appearance: the theme, background, panel and typeface cards
  * Persona, made over: a face in a glowing orb, the persona's name typing itself in, how long it is counting up,
    the text a line at a time, and the rest of the character as cards, each set down with a thud
  * Memory, System, Logs and Pictures: their lists and figures arrive, and press with a squash
  * Settings > Models: the models plug in one by one, a beam of light across each, a tock as each lands
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


print("== a list arriving, one after another ==")
dm = read("lib/domino.ts")
css = read("app.css")
check("after its block lands, in a second wave down it, and only once it can be seen",
      "afterLanding(node, () => onScreen(node).then((seen) => {" in dm and "down * (quick ? 0.1 : PER_PX)" in dm)
check("only what is seen takes a turn, the rest simply there",
      "r.bottom > view.top && r.top < view.bottom" in dm and "c.dataset.there = \"\"" in dm and ".domino.is-in > :not([data-there])" in css)
check("seen means inside whatever scrolls around it too: a list scrolled to its end gives its turns to the lines shown",
      "function viewOf(node: HTMLElement)" in dm and "for (let el: HTMLElement | null = node; el; el = el.parentElement)" in dm)
logs_src = read("pages/Logs.svelte")
check("the Logs open straight at the newest lines, not gliding there, so those are the ones that come in",
      "if (box) box.scrollTop = newestFirst ? 0 : box.scrollHeight;" in logs_src)
check("each a note up the scale, booked with its item's CSS delay", "delay: base + i * step + (o.soundAt ?? 16)" in dm
      and "animation-delay: calc(var(--i, 0) * var(--domino-step, 40ms));" in css)
check("the notes counted from the frame the pops start in, not from when they were asked for (a busy tab's frame is late)",
      "requestAnimationFrame((frame) => {" in dm and "const base = frame - performance.now();" in dm)
check("a pop with a little jelly, and an item's own hover and press are its own after",
      "animation: domino-in var(--domino-dur, 0.55s) var(--jelly) backwards;" in css)
check("kept whole by the tab's opening wave, or an item would show, vanish, and pop again", 'node.dataset.rise = "";' in dm)
check("a list still on its way starts its run as it fills", "new MutationObserver(" in dm and "whenFilled(true)" in dm)
check("once, where a list has its own way of showing what comes later", "node.classList.remove(\"domino\")" in dm)
check("one thing popping on its own is heard as it pops, asked there and then",
      "export function chime(" in dm and "const r = node.getBoundingClientRect();" in dm.split("export function chime(")[1].split("\n}")[0])
check("with Animations off, all simply there", ':root[data-motion="off"] .domino > * {\n  opacity: 1;\n  animation: none;' in css)

print("\n== the tabs ==")
chats = read("pages/Chats.svelte")
check("Chats: the inbox, the friend requests and the recent conversations",
      chats.count("use:domino=") == 3 and '<div class="ch-recent-grid domino" use:domino={{ step: 35 }}>' in chats)
check("Chats: the recent cards' own entrance, which bunched up, is gone",
      "animation-delay: calc(var(--i, 0) * 28ms);" not in chats)
check("Chats: the all-clear check chimes as it pops", '<span class="ch-zero-mark" use:chime={"done"}>' in chats)
mem = read("pages/Memory.svelte")
check("Memory: the figures count up, popping in", "<Num value={s.n} />" in mem and "use:domino={{ step: 80 }}" in mem)
check("Memory: the people, and someone's facts as they are opened",
      "use:domino={{ step: 35, max: 14 }}" in mem and "{#key selected}" in mem)
check("Memory: a person pressed squashes", ".mm-row:active { transform: scale(0.97);" in mem)

print("\n== Settings > Appearance, its own way and faster: the colours flood in ==")
ap = read("lib/components/Appearance.svelte")
cw = read("lib/colorwave.ts")
check("every section of it, not the other tabs' drop and pop", ap.count('<section class="ap-sec" use:colorwave>') == 6
      and "use:domino" not in ap)
check("at once: left out of the tab's opening wave, nothing waits for a drop to land", 'node.dataset.noRise = "";' in cw
      and "requestAnimationFrame(() => {\n    frame" not in cw and "afterLanding" not in cw)
check("a diagonal wave from the top left, read off where each card is", "cols.indexOf(Math.round(c.offsetLeft)) + rows.indexOf(Math.round(c.offsetTop))" in cw
      and "calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms)" in ap)
check("out of grey into colour, quick and with no bounce", "filter: grayscale(1) brightness(0.5)" in ap
      and "animation: ap-flood 0.36s cubic-bezier(0.2, 0.8, 0.2, 1) backwards;" in ap)
check("a glint of light crosses each card", "@keyframes ap-sheen" in ap)
check("a theme's colours spill out, a background develops, a panel blooms, a typeface inks in",
      all(f"@keyframes {k}" in ap for k in ("ap-dot", "ap-develop", "ap-bloom", "ap-pane", "ap-ink")) and "--k: {k}" in ap)
check("the chosen one's tick pops last, and later ones from a click are quick",
      ".ap-sec:not(:global(.is-in)) .ap-tick { animation: none; }" in ap and ".ap-sec:global(.is-waving) .ap-tick" in ap)
check("heard as a run of glints up the scale, booked from the frame it starts in",
      'play("glint", { p: run > 1 ? i++ / (run - 1) : 0.5, delay: x.t + LAG' in cw and 'play("glint", { p: 1, strong: true' in cw)
snd = read("lib/uisound.ts")
check("the glint: a high glassy ping, gone in a tenth of a second", 'case "glint": {' in snd and " glint: 12," in snd)
sysp = read("pages/System.svelte")
check("System: the ring draws itself round, then its mark pops with a chime, together",
      "@keyframes sys-draw" in sysp and "sys-mark 0.6s var(--jelly) 0.5s backwards" in sysp
      and 'use:chime={{ sound: failing ? "land" : "done", delay: 500 }}' in sysp)
check("System: the checks, the backup and the about", sysp.count("use:domino=") == 4)
logs = read("pages/Logs.svelte")
check("Logs: the last hour's minutes grow up, a tick each", 'use:arriving={{ heights: () => chart.bars.map((x) => x.n), stagger: 8, level: 0.7, sound: "wind" }}' in logs
      and "@keyframes lg-grow" in logs)
check("Logs: the newest lines come in like a ticker starting, once", 'use:domino={{ step: 28, sound: "wind", level: 0.8, max: 16, once: true }}' in logs)
pics = read("pages/Pictures.svelte")
check("Pictures: the cards and the bar, once (a picture added grows in its own way)", pics.count("once: true }}") == 2)

print("\n== Persona, made over ==")
ps = read("pages/Persona.svelte")
orb = read("lib/personas/PersonaOrb.svelte")
pyp = (ROOT / "app" / "utils" / "personas.py").read_text(encoding="utf-8")
check("a face in a glowing orb, popping in with a sound", 'class="ps-orb"' in ps and 'use:chime={"land"}' in ps
      and "@keyframes ps-orb-in" in ps and "conic-gradient(" in orb)
check("the persona's name, as the text gives it, typing itself in a key at a time",
      '_NAME_IN_TEXT = re.compile(r"your name is\\s+([^\\s,.;:!?]+)", re.I)' in pyp
      and 'sound: "key"' in ps and 'class="ps-l"' in ps)
check("a [placeholder] is not a name", 'not m.group(1).startswith("[")' in pyp)
prof = read("pages/Profiles.svelte")
check("the faces of the accounts it runs on, on Profiles", 'class="pr-acct"' in prof and "<Avatar src={a.avatar}" in prof)
check("how long it is, counting up", ps.count("<Num value=") == 3)
check("formatted or raw on a sliding switch", '<Segmented label="How it is shown"' in ps)
check("the text a line at a time, a soft tick each", '<div class="ps-text markdown domino" use:domino={{ step: 34, sound: "wind"' in ps)
check("the rest of the character as cards, each set down with a thud, again for each persona",
      '<div class="ps-grid domino" use:domino={{ step: 90, sound: "seat", level: 0.5, once: true }}>' in ps
      and all(f'<{x} />' in ps for x in ("TriggerEditor", "OpenersEditor", "MoodEditor", "ReactionEditor")))
check("editing still read only until Edit, and saved as the persona picked", "async function save()" in ps
      and 'api.savePersonaText(pid, text)' in ps and "{#if editing}" in ps)

print("\n== a Memory summary types itself in ==")
tw = read("lib/typewrite.ts")
check("typed in fast, a caret running ahead, the speed fitting the length",
      "export function typewrite(" in tw and "const perSecond = Math.max(70, total / (opts.seconds ?? 1.5));" in tw
      and 'caret.className = "tw-caret";' in tw)
check("every letter there from the start, only unseen, so nothing below moves while it types",
      'rest.className = "tw-rest";' in tw and ".tw-rest { visibility: hidden; }" in css)
check("bold and code included: only the text is walked, never the markup", "NodeFilter.SHOW_TEXT" in tw)
check("heard as typing: a soft key every few letters, a firmer one on a space now and then",
      'play("key", { strong: typed.includes(" ") && Math.random() < 0.4, level: 0.32 });' in tw)
check("the caret blinks twice at the end, then goes", ".is-typed .tw-caret { animation: tw-blink 0.3s steps(1) 2; }" in css)
check("with Animations off, simply there", "if (!get(motionEnabled)) return;" in tw)
check("the summary card types each new one in, and again when rewritten",
      "{#key data.summary}<SummaryText text={data.summary} type />{/key}" in read("lib/components/PersonSummary.svelte")
      and "use:typing={type}" in read("lib/components/SummaryText.svelte"))

print("\n== Settings > Models: plugged in ==")
mp = read("lib/components/ModelsPanel.svelte")
check("a list can plug in, sliding across, with its note as it lands",
      'if (o.variant === "plug") node.classList.add("is-plug");' in dm and 'sound?: "pluck" | "wind" | "key" | "seat" | "none";' in dm
      and ".domino.is-plug.is-in > :not([data-there])" in css and "@keyframes domino-plug" in css)
check("the chain of models plugs in one by one, a woody tock each as it lands, quickly",
      'use:domino={{ step: 45, variant: "plug", sound: "seat", soundAt: 120, level: 0.85, once: true }}' in mp)
check("each job plugs in after it, its model a moment later, with its tock",
      'use:domino={{ step: 35, variant: "plug", sound: "seat", soundAt: 150, level: 0.65, once: true }}' in mp
      and '<div class="mp-job-wrap">' in mp)
check("a beam of light runs across each model, then its light comes on",
      "@keyframes mp-beam" in mp and "@keyframes mp-light" in mp and "var(--domino-step, 45ms) + 60ms" in mp
      and "var(--domino-step, 45ms) + 190ms" in mp)
check("the Models tabs open in under half the time: a quicker wave, and each item lands sooner",
      'data-cascade={tab.id === "groq" ? "quick" : undefined}' in read("pages/Settings.svelte")
      and "const QUICK = { perPx: 0.16, maxDelay: 140, duration: 340 };" in read("lib/cascade.ts")
      and '[data-cascade="quick"] { --domino-dur: 0.36s; }' in css)
check("a job's model plugs in from the right, and the icons pop",
      "@keyframes mp-plug" in mp and "translateX(22px)" in mp and "@keyframes mp-icon" in mp)
check("with Animations off, none of it", ':global(:root[data-motion="off"]) .mp-head-icon { animation: none; }' in mp
      and ':global(:root[data-motion="off"]) .mp-row::after' in mp)
check("only as the tab opens: a model added later or a reorder is not a show", mp.count("once: true }}") == 2)

print("\n== Settings > Models, made over ==")
mh = read("lib/components/ModelsHero.svelte")
st = read("pages/Settings.svelte")
check("each part opens on an orb with a ring of light turning round it, and how things stand there as chips",
      'class="mh-orb" use:chime={"land"}' in mh and "@keyframes mh-turn" in mh and 'class="mh-chips domino"' in mh
      and '{#if tab.id === "groq"}' in st and "<ModelsHero which={sub.id}" in st)
check("the chips say it in plain words: replies, providers, the computer's server, today's requests",
      "to fall back on" in mh and "connected" in mh and '"running" : "not running"' in mh and '"request") + " today"' in mh)
check("the order a reply tries its models in is drawn: a line of light from each number down to the next",
      ".mp-row + .mp-row::before {" in mp and ".mp-chain > .mp-row:first-child {" in mp)
pp = read("lib/components/ProvidersPanel.svelte")
check("each provider lit in its own colour, a check on its mark once connected, the cards coming in one by one",
      "--tint: {TINT[p.id] ?? 'var(--color-accent)'}" in pp and 'class="pp-ok"' in pp and pp.count("use:domino=") == 2)
us = read("lib/components/UsagePanel.svelte")
check("today's figures roll up, the models' cards come in one by one",
      "<Num value={totals.requests} />" in us and us.count("use:domino=") == 2)
check("a key icon for keys: it was asked for and drew nothing", "key:" in read("lib/components/Icon.svelte"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
