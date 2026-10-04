"""Profiles in the panel: the Profiles page, the Persona page for one profile, the chip on each account, and
Pictures, Memory and Settings each set to one profile.

  * Profiles has a place of its own in the sidebar: a card each, whether it is running, on which accounts, and
    what each of those accounts is doing, its parts opening on it
  * every moment has its sound, in time: making, deleting, moving an account, taking one back, a new face
  * an account given to another profile flies from one card to the other
  * Persona shows one profile's persona, picked with a pill, in its colour, gliding (a registered colour); text
    with changes not saved holds it on its profile
  * the account card's chip opens the profiles, and picking one lights the banner and restarts the account
  * Pictures, Memory and Settings say whose they are, and every read and write carries it
  * Settings set to a profile: its own rows tagged, a way back to everyone's, the app's own rows said to be so
  * the pure parts (lib/personas/logic.ts) run under Node
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui"
SRC = WEB / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


profiles = read("pages/Profiles.svelte")
page = read("pages/Persona.svelte")
css = read("app.css")
orb = read("lib/personas/PersonaOrb.svelte")
dots = read("lib/personas/ColorDots.svelte")
menu = read("lib/personas/PersonaMenu.svelte")
scope_pill = read("lib/personas/PersonaScope.svelte")
newp = read("lib/personas/NewPersona.svelte")
acctmenu = read("lib/personas/AccountMenu.svelte")
logic = read("lib/personas/logic.ts")
icon = read("lib/components/Icon.svelte")
card = read("lib/accounts/AccountCard.svelte")
accounts = read("pages/Accounts.svelte")
state = read("lib/accounts/state.ts")
pics = read("pages/Pictures.svelte")
picslib = read("lib/pictures.ts")
looks = read("lib/components/LookEditor.svelte")
memory = read("pages/Memory.svelte")
summary = read("lib/components/PersonSummary.svelte")
settings = read("pages/Settings.svelte")
panel = read("lib/components/PicturesPanel.svelte")
models = read("lib/components/ModelsPanel.svelte")
providers = read("lib/providers.ts")
api = read("lib/api.ts")
bp = read("lib/bigpicture/BigPicture.svelte")
search = read("lib/search.ts")
palette = read("lib/components/CommandPalette.svelte")
modal = read("lib/components/Modal.svelte")
app = read("App.svelte")

print("== Profiles, a page of its own ==")
check("in the sidebar under Run, after the Dashboard, with an icon of its own",
      re.search(r'dashboard: \{[^\n]*\n\s*// [^\n]*\n\s*profiles:\s+\{ title: "Profiles",\s+icon: "layers"', app) is not None
      and "layers:" in icon)
check("and Persona is one profile's persona again", 'persona:   { title: "Persona",' in app)
check("a card each, in its colour", "{#each cards as c (c.p.id)}" in profiles and 'style="--pc: {colorOf(p)}"' in profiles)
check("whether it is running, from what its accounts are doing", "runningLine(accts.length, live, other)" in profiles
      and 'class="pr-state is-{c.state.tone}"' in profiles and "export function runningLine(" in logic)
check("its face breathes in its colour while one of its accounts is up, amber while one starts",
      "class:is-live={c.live > 0} class:is-busy={c.busy}" in profiles and ".pr-face.is-live::before" in profiles
      and "@keyframes pr-breathe" in profiles)
check("each account with what it is doing, said as the Accounts page says it",
      "condition(slot, rt, d)" in profiles and "presenceOf(slot, rt, d)" in profiles and 'class="pr-acct-state is-{a.tone}"' in profiles)
check("kept up to date while the page is open", "visiblePoll(() => {" in profiles)
check("start or stop all of its accounts, one after another", "async function power(c: Card" in profiles
      and "for (const a of targets)" in profiles and "api.accountAction(a.id, act)" in profiles)
check("its parts open on it: persona, pictures, memory, settings",
      all(f'route: "/{r}"' in profiles for r in ("persona", "pictures", "memory", "settings"))
      and "viewPersona.set(p.id);" in profiles and 'if (route === "/settings") settingsScope.set(p.id);' in profiles)
check("an account given to another profile flies across to its card",
      "in:receive={{ key: a.id }} out:send={{ key: a.id }}" in profiles and "personasRes.update((d) => withAccount(d, webId, pid))" in profiles
      and "export function withAccount(" in logic)
check("and the move restarts it, and says so", "api.assignPersona(pid, webId)" in profiles and "Restarting it." in profiles)
check("a dashed card makes another", 'class="pr-new"' in profiles and "<b>New profile</b>" in profiles)
check("its menu: its colour, rename, a new face, duplicate, delete",
      "<ColorDots palette={data.palette}" in profiles and all(s in profiles for s in ("Rename", "Change its face", "Duplicate", "Delete")))
check("the menu is solid: inside a glass card a blur has nothing to blur", 'class="pr-menu" role="menu"' in profiles
      and "background: linear-gradient(180deg, rgb(255 255 255 / 0.06), transparent 40%), var(--color-card);" in profiles)
check("each face in a ring of its colour", "conic-gradient(" in orb)
check("its colours as dots, picked with a glint", 'play("glint", { strong: true })' in dots)
fp = read("lib/personas/FacePicker.svelte")
check("a face is picked in a small panel beside it, not a box over the page",
      '<FacePicker persona={faceFor} anchor={faceAt} onclose={() => (faceId = "")} onchanged={afterFace} />' in profiles
      and "<Modal open={faceOpen}" not in profiles and "data-face={p.id}" in profiles
      and "openFace(p, e.currentTarget as HTMLElement)" in profiles and "function portal(node: HTMLElement)" in fp)
check("beside the face when there is room, under it when not, always on screen",
      "let left = r.right + 12;" in fp and "top = r.bottom + 10;" in fp and "Math.min(top, innerHeight - h - 8)" in fp)
check("put away by a click elsewhere, Escape (from the crop, back first), or the page scrolling",
      'window.addEventListener("pointerdown", off, true);' in fp and "if (crop) back();" in fp and "else onclose();" in fp)
check("pressed again: put away", "if (faceId === p.id) {" in profiles)
check("its pictures as small tiles, Upload first, the bin when it has a face",
      'class="fp-tile fp-up"' in fp and "grid-template-columns: repeat(5, minmax(0, 1fr));" in fp
      and "{#if p.avatar}" in fp and 'title="Take its face off"' in fp)
check("blurred while the preference is on, each clear under the pointer, the eye for all, blurred again each time it opens",
      "const blurred = $derived($picturesBlur && !shown);" in fp and 'class:is-blur={blurred}' in fp
      and ".fp-grid.is-blur .fp-tile:hover img { filter: none; }" in fp and "    shown = false;" in fp)
check("the crop in the same panel, which widens for it", "<FaceCrop src={crop.src}" in fp and ".fp.is-crop { width: min(460px" in fp)
check("it pops open from the face, its tiles one after another", "@keyframes fp-in" in fp and "@keyframes fp-tile" in fp
      and ':global(:root[data-motion="off"]) .fp,' in fp)

print("\n== sounds, in time with what moves ==")
check("making one: done, then a strong glint, and it pops in with a burst of its colours",
      'play("done");' in profiles and 'play("glint", { delay: 180, strong: true })' in profiles
      and "burstFrom(node" in profiles and "@keyframes pr-born" in profiles)
check("deleting one: delete, the rest sliding, the seat",
      'play("delete");' in profiles and 'play("slide", { delay: 120, level: 0.5 })' in profiles and 'play("seat", { delay: 480 })' in profiles
      and "animate:flip" in profiles)
check("giving it an account: a zip as it flies, the seat as it lands", 'play("zip");' in profiles and 'play("seat", { delay: 400 })' in profiles)
check("taking one back: a drop", 'play("drop");' in profiles)
check("a new face: it pops as it lands", 'play("land", { delay: 200 })' in profiles and "@keyframes pr-pop" in profiles)
print("\n== Profiles, opening ==")
check("the hero first: a light sweeps across it, with a whoosh once it has landed",
      '<section class="pr-hero glass" use:chime={{ sound: "wind", delay: 140 }}>' in profiles
      and "animation: pr-sheen 1.25s" in profiles and "@keyframes pr-sheen" in profiles)
check("its ring winds in round the orb, then turns slowly",
      "animation: pr-ring-in 1s cubic-bezier(0.2, 0.9, 0.25, 1) 0.1s backwards, pr-turn 7s linear 1.1s infinite;" in profiles)
check("the title's letters rise one after another, never breaking a word",
      'class="pr-l" style="--c: {w * 5 + i}"' in profiles and "animation-delay: calc(0.12s + var(--c) * 26ms);" in profiles
      and ".pr-word { display: inline-block; white-space: nowrap; }" in profiles and 'aria-label="Your profiles"' in profiles)
check("the stats tick in", 'use:domino={{ step: 80, sound: "key", level: 0.45 }}' in profiles)
check("the cards are dealt in, one after another, each tipping up into place",
      '<div class="pr-grid" use:deal>' in profiles and "const DEAL_STEP = 130;" in profiles
      and "@keyframes pr-deal" in profiles and "rotateX(18deg)" in profiles)
check("then what is on each arrives in turn: colour, face, name, accounts, parts, buttons",
      all(f"@keyframes {k}" in profiles for k in ("pr-wash", "pr-face-in", "pr-plug", "pr-tile", "pr-rise"))
      and "calc(var(--at) + 400ms + var(--j, 0) * 70ms)" in profiles and "calc(var(--at) + 520ms + var(--k, 0) * 55ms)" in profiles
      and 'style="--j: {j}"' in profiles and 'style="--k: {k}"' in profiles)
check("each step heard in time with it, booked from the frame the cards start in",
      "const base = frame - performance.now();" in profiles and 'play("pluck", {' in profiles
      and 'play("glint", { level: 0.26, delay: t + 300 })' in profiles and 'play("tick", { level: 0.2' in profiles
      and 'play("seat", { level: 0.28' in profiles)
check("held until the page lands, and cards off screen are simply there",
      "whenShown(node).then(() => afterLanding(node, () => onScreen(node)" in profiles and 'c.dataset.there = ""' in profiles)
check("only as the page opens", 'node.classList.remove("is-dealing")' in profiles)
print("\n== Profiles, open ==")
check("a card leans towards the pointer, a light in its colour following it",
      "use:tilt={2.5}" in profiles and "rotateX(var(--tx, 0deg)) rotateY(var(--ty, 0deg))" in profiles
      and "circle at var(--lx, 50%) var(--ly, 0%)" in profiles)
check("flat while its menu is open, whose items come down one after another",
      ".pr-card.is-raised { --tx: 0deg; --ty: 0deg; }" in profiles and "@keyframes pr-item" in profiles)
check("a light runs round a card while it starts, heard as on and off",
      "class:is-powering={acting === `${p.id}:start`}" in profiles and "@keyframes pr-spin { to { --pr-spin: 360deg; } }" in profiles
      and 'play(act === "start" ? "on" : "off");' in profiles)
check("a profile coming up flashes with a glint, not while the page first fills in",
      "class:is-lit={lit === p.id}" in profiles and "@keyframes pr-lit" in profiles
      and "performance.now() - openedAt < 4000" in profiles)
check("a new state slides in over the old one", "{#key c.state.text}" in profiles and "{#key a.label}" in profiles
      and "@keyframes pr-swap" in profiles and "@keyframes pr-chip" in profiles)
check("accounts lean in under the pointer, part icons bounce, the new tile lifts",
      ".pr-acct:hover { transform: translateX(3px);" in profiles
      and ".pr-part:hover .pr-part-head :global(svg) { transform: rotate(-12deg) scale(1.22); }" in profiles
      and "transform: translateY(-3px); }" in profiles)
check("motion off: all of it still", all(f':global(:root[data-motion="off"]) {sel}' in profiles for sel in
      (".pr-hero::after,", ".pr-l,", ".pr-grid *,", ".pr-card::before,", ".pr-card::after,", ".pr-acct,", ".pr-menu > *,")))

print("\n== Persona, one profile's ==")
check("a pill says whose, once there is more than one", '<PersonaScope value={selected} label="Persona of" onchange={select} />' in page
      and "{#if list.length > 1}" in page)
check("the page wears the profile's colour", 'style="--persona-color: {color}"' in page)
check("and glides to another's: the colour is registered, so it can",
      "@property --persona-color {" in css and 'syntax: "<color>";' in css and "transition: --persona-color 0.6s" in page)
check("the editors below are the picked profile's, made again for another",
      "providePersona(() => selected);" in page and page.count("{#key selected}") >= 1)
check("its text read and saved as its own", "api.personaText(pid)" in page and "api.savePersonaText(pid, text)" in page)
check("picking another: a glint, then the seat as it settles",
      'play("glint", { delay: 60, level: 0.5 })' in page and 'play("seat", { delay: 360 })' in page)
check("its name types itself in, a key a letter", 'sound: "key"' in page and 'class="ps-l"' in page)
check("what moved to Profiles is not here twice", "CastStrip" not in page and "AccountMenu" not in page and "deletePersona" not in page)
check("text with changes not saved holds the page on its profile",
      "async function mayLeave()" in page and "Save or cancel the text first." in page
      and "if (!(await mayLeave())) return;" in page)
check("another profile's text stays up, dimmed, until the picked one's arrives, then reads itself out",
      "{#key textFor}" in page and ".ps-doc.is-switching .ps-text" in page)

print("\n== nothing lost or misplaced ==")
check("New profile is not a form: Cancel never makes one", not re.search(r"<form\s", newp)
      and 'if (e.key === "Enter") submit();' in newp)
check("its wording", all(s in newp for s in ('title="New profile"', "Start from", "Copy its memory too", ">Create</Button>")))
check("the delete question says what goes and where its accounts go",
      "Its persona, pictures and memory go." in profiles and "joinAnd(deleteFor.accounts.map(accountLabel))" in profiles
      and "back to {defaultName}." in profiles)
check("a deleted profile is not left as the one the other pages open on",
      'if (get(viewPersona) === p.id) viewPersona.set("default");' in profiles)
check("moving an account: the menu of the others, each saying where it is now",
      "Move here" in acctmenu and "Every account is on it already." in acctmenu and "now <i" in acctmenu)
check("a dialog with nothing to type in still closes with Escape", "use:takeFocus" in modal
      and "node.focus({ preventScroll: true })" in modal)

print("\n== the chip on each account ==")
check("top left of the banner, the platform's twin, in the profile's colour",
      'class="acct-persona"' in card and 'style="--persona-color: {colorOf(persona)}"' in card and "left: 12px;" in card)
check("pressed, the profiles, with a way to the Profiles page",
      "<PersonaMenu bind:open={personaOpen}" in card and 'label: "Edit profiles"' in card and '(window.location.hash = "/profiles")' in card)
check("picking one lights the banner in its colour, screened onto any banner",
      'class="acct-banner-flash"' in card and "mix-blend-mode: screen;" in card and "@keyframes acct-flash" in card)
check("with a glint as it does", 'play("glint", { delay: 80 })' in card)
check("the chip grows to the new name rather than jumping", "$effect.pre(" in card and "el.animate([{ width: `${chipWas}px` }" in card)
check("the account restarts with it, and says so",
      "api.assignPersona(pid, s.id)" in accounts and "is ${name} now. Restarting it." in accounts)
check("each card's moods are its profile's", "loadMoods(false, pid)" in accounts
      and "moods={moodsBy[personaIdOf(r.slot)] ?? moods}" in accounts and "api\n      .config(persona)" in state)
check("a new account can be given one before it first starts",
      'aria-label="Profile"' in accounts and accounts.count("await giveNewPersona(id);") == 2)
check("the add tile's line", "Each one runs on its own, with its own login, mood and profile." in accounts)

print("\n== Pictures, one persona's ==")
check("a pill says whose, and switches", '<PersonaScope value={pid} label="Pictures of" onchange={switchTo} />' in pics)
check("the drop zone says whose they are going to", "Drop pictures or videos for <b" in pics)
check("one list per persona, Default's where it always was",
      'resource(as ? `pictures:${as}` : "pictures"' in pics)
check("pictures dropped go to the persona they were dropped for, even after a switch",
      "addPictures(Array.from(files), () => load(), who);" in pics and "{ file: File; persona: string }" in picslib
      and "api.uploadPicture(file, persona)" in picslib)
check("deletes waiting on their undo go from the persona they were deleted from",
      "const owner = who;" in pics and "api.deletePictures(batch.map((p) => ({ name: p.name, id: p.id })), owner)" in pics
      and "if (leaving.length) commit();" in pics)
check("every picture shown, by whose it is", "api.pictureUrl(p.name, p.id)" not in pics and "api.pictureUrl(p.name, p.id, who)" in pics)
check("the filter window works on that persona's", "persona={who}" in pics and "api.putLook(still.map((p) => ({ name: p.name, id: p.id })), look, strength, persona)" in looks)
check("what its new pictures get is its own setting",
      'api.configField("bot.pictures.auto_look.mode", mode, { persona })' in pics)

print("\n== Memory, one persona's ==")
check("a pill says whose", "<PersonaScope value={pid} onchange={switchTo} />" in memory)
check("the title says whose, typing itself in", "`What ${whoName} remembers`" in memory and 'sound: "key"' in memory)
check("every read and write carries it", all(s in memory for s in (
    "api.memoryUser(uid, who)", "api.memoryPut(selected, body, who)", "api.memoryDelete(selected, { key }, who)",
    "api.memoryDelete(selected, {}, who)")))
check("the summary is that persona's", "persona={who}" in memory and "api.memorySummary(who, force, false, as)" in summary)
check("a person's own tone is not called a persona any more",
      '"Own tone"' in memory and "How it talks to them" in memory and "Has its own tone" in memory
      and 'label: "Personas"' not in memory and "Persona for this person" not in memory)

print("\n== Settings, set to one persona ==")
check("a pill by the search: everyone's, or one persona's",
      '<PersonaScope value={scope} everyone label="Settings for" onchange={setScope} shake={scopeShake} />' in settings)
check("arriving from a persona's Change settings, set to it", "const want = $settingsScope;" in settings
      and 'settingsScope.set("");' in settings)
check("not switched with changes unsaved: the pill shakes no", "Save or undo first." in settings and "scopeShake = true;" in settings)
check("each scope its own schema, and the panels made again for another",
      "s ? `settingsSchema:${s}` : \"settingsSchema\"" in settings and "{#key `${path}|${scope}`}" in settings)
check("saved to the scope they were made in", "api.configField(key, v, persona ? { persona } : {})" in settings)
check("and the saved values read back, not a held answer from before the save", "await load(true);" in settings
      and "fresh === true ? { force: true } : { maxAge: 15000 }" in settings)
check("its own rows tagged in its colour, with a way back to everyone's",
      "{scopeName}'s own" in settings and "Use everyone's" in settings and "api.resetPersonaSetting(scope, x.key)" in settings)
check("the app's own rows say they are everyone's", "Same for everyone" in settings and "Same for every profile." in settings)
check("a dot in its colour on the tabs holding its own", settings.count('class="settings-own-dot"') == 2)
check("a settings file and the raw editor only for everyone's", "{#if !scope}\n      <div class=\"flex shrink-0 gap-2\">\n        <SettingsFile" in settings)
check("the bar says whose", "`Saved for ${scopeName}`" in settings)
check("the Pictures and Models panels follow it",
      "const persona = usePersona();" in panel and "api.configField(key, value, persona ? { persona } : {})" in panel
      and "planPersona.set(next);" in settings and "await api.savePlan(body, persona);" in models
      and "const d = await api.providers(persona);" in providers)

print("\n== the rest of the app ==")
check("every picture and memory call can name its persona", "function scoped(path: string, persona = \"\")" in api
      and "pictures: (persona = \"\") => request(scoped(\"/api/pictures\", persona))" in api
      and "memory: (persona = \"\") => request(scoped(\"/api/memory\", persona))" in api)
check("Big Picture shows the persona of the account on show",
      "api.personaText(pid)" in bp and "loadMoods(false, pid)" in bp and "api.instructions()" not in bp)
check("and only marks a picture sent as the gallery's own persona's", "const mine = (sender === \"default\" ? \"\" : sender) === picturesOf;" in bp)
check("search finds profiles, and opens on the one found",
      'group: "Profiles", kind: "persona"' in search and '{ id: "Profiles", icon: "layers" }' in palette
      and 'if (h.kind === "persona") { if (h.section) viewPersona.set(h.section); }' in palette)

print("\n== Animations off ==")
for name, src, rule in (
    ("the Persona page", page, ':global(:root[data-motion="off"]) .ps-orb'),
    ("the Profiles page", profiles, ':global(:root[data-motion="off"]) .pr-card.is-born'),
    ("the chip's flash", card, ':global(:root[data-motion="off"]) .acct-banner-flash { opacity: 0; }'),
    ("the scope tags", css, ':root[data-motion="off"] .settings-scope-tag { animation: none; }'),
    ("the scope pill", scope_pill, ':global(:root[data-motion="off"]) .psc-pill'),
    ("the persona menu", menu, ':global(:root[data-motion="off"]) .pm-row'),
):
    check(f"{name}: still with Animations off", rule in src)

print("\n== the plain parts (Node) ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "personas_logic.mjs")], cwd=WEB,
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("personas_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
