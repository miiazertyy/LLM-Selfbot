"""Community profiles on the Profiles page, read from the source: where they sit on the page, that every control
and arrival has its sound (from the closed set), that the app's Animations switch reaches every new motion, that a
profile's words are only ever put on the page as text, and that the requests carry the panel's own header. The pure
logic runs under Node (tests/community_logic.mjs)."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (WEB / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


profiles = read("pages/Profiles.svelte")
parts = {p.name: p.read_text(encoding="utf-8") for p in sorted((WEB / "lib" / "community").glob("*.svelte"))}

print("== on the Profiles page ==")
check("yours or the community's, under the hero", "<CommunitySwitch {updates} />" in profiles
      and '{#if $profilesView === "community"}' in profiles
      and "<CommunityView personas={list} onshare={openShare} onupdate={openUpdate} />" in profiles)
check("your own cards stay exactly as they were", "{#each cards as c (c.p.id)}" in profiles and 'class="pr-new"' in profiles
      and "<b>New profile</b>" in profiles and "visiblePoll(() => {" in profiles)
check("the accounts aren't asked about while the community is up",
      'return visiblePoll(() => {\n      if (get(profilesView) === "community") return;' in profiles)
check("share one from its card's menu, never one that came from the community", "{#if !p.community}" in profiles
      and "Share to community" in profiles and "openShare(p.id)" in profiles)
check("a newer version waiting is a badge that opens what it changes", "Update to v{newer[p.id]?.to}" in profiles
      and "openUpdate(p.id)" in profiles and 'class="pr-badge pr-update"' in profiles)
check("the share and update sheets", "<ShareSheet bind:pid={shareFor}" in profiles and "<UpdateSheet bind:pid={updateFor_}" in profiles)
check("the menu's new item comes in after the others", ".pr-menu > :nth-child(6) { animation-delay: 150ms; }" in profiles)

print("\n== the parts ==")
want = {"CommunitySwitch.svelte", "CommunityView.svelte", "CommunityCard.svelte", "ProfileInspect.svelte",
        "UpdateSheet.svelte", "ShareSheet.svelte", "SignInPanel.svelte", "MyShared.svelte", "Moderation.svelte",
        "SettingRows.svelte", "RiskText.svelte", "DownloadsChart.svelte"}
check("every part is there", want <= set(parts), want - set(parts))

SOUNDS = set(re.findall(r'"(\w+)"', re.search(r"export type UISound =([^;]+);", read("lib/uisound.ts")).group(1)))
for name, src in parts.items():
    used = set(re.findall(r'play\(\s*"(\w+)"', src)) | set(re.findall(r'sound:\s*"(\w+)"', src)) \
        | set(re.findall(r'chime=\{"(\w+)"\}', src))
    check(f"{name}: sounds only from the set", used <= SOUNDS | {"pluck", "wind", "key", "seat"}, used - SOUNDS)
    moving = "@keyframes" in src or "transition:" in src
    check(f"{name}: the Animations switch reaches it", not moving or ':global(:root[data-motion="off"])' in src)
    check(f"{name}: never prefers-reduced-motion, confirm() or raw HTML", "prefers-reduced-motion" not in src
          and "confirm(" not in src and "{@html" not in src)
    check(f"{name}: no em dashes", chr(0x2014) not in src)

view = parts["CommunityView.svelte"]
card = parts["CommunityCard.svelte"]
inspect = parts["ProfileInspect.svelte"]
share = parts["ShareSheet.svelte"]
signin = parts["SignInPanel.svelte"]
mine = parts["MyShared.svelte"]
check("cards come in one after another, each with its note", 'use:domino={{ step: 55, sound: "pluck", max: 12 }}' in view
      and "<CommunityCard {p}" in view)
check("the stats count up, key by key", 'use:domino={{ step: 80, sound: "key", level: 0.45 }}' in view and "<Num value=" in view)
check("a search settles with one note, not one per key", 'play("slot", { level: 0.3 })' in view and "searchTimer" in view)
check("a card plays its own sound when it opens", 'data-sound="self"' in card and 'play("open")' in view)
check("Inspect arrives: rises, its face lands, its parts in turn", 'use:chime={{ sound: "rise", delay: 60 }}' in inspect
      and 'use:chime={{ sound: "land", delay: 160 }}' in inspect and 'sound: "wind"' in inspect)
check("added: done, then a glint", 'play("done");\n      play("glint", { delay: 180, strong: true });' in inspect)
check("what you'd keep is said before adding", "Only how it talks comes with it. Your accounts, models, keys and limits stay yours." in inspect)
check("the text shown as text, risky parts lit", "<RiskText segments={data.segments} />" in inspect
      and '<mark class="rt-mark is-{s.kind}"' in parts["RiskText.svelte"])
check("the sign-in code typed in, a key a letter", 'play("key", { level: 0.35' in signin and "typeIn(st.user_code)" in signin)
check("followed with visiblePoll, stopped when done or away", "visiblePoll(async () => {" in signin and "stopPoll?.();" in signin
      and "visiblePoll(async () => {" in share and "stopFollow?.();" in share and "visiblePoll(() => {" in mine)
check("what goes public is shown, and must be checked when it names you", "This goes public. Everything you send is public on GitHub." in share
      and "I checked the highlighted parts" in share and "preview.needs_check && !checked" in share)
check("never shared, said plainly", "Nor its memory, chats, accounts, keys, or the pictures you didn't pick." in share)
check("live is a medal, refused an error", 'play("medal");' in share and 'play("err", { level: 0.6 });' in share)
check("removing asks first, in the app's own way", "await ask(`Take ${slug} out of the community?`" in mine)
check("the author is a name they pick, not their GitHub one", "Not your GitHub name." in share)
check("links go through the app's own builder", all("openGitHub(" in s for s in (inspect, share, mine))
      and "window.open(" not in "".join(parts.values()))

print("\n== its version, and whether it was made for your app ==")
card = read("lib/community/CommunityCard.svelte")
check("beside each profile: its version, and up to date, an older app or a newer one",
      "const fit = $derived(appWords(p.app, app));" in card and "v{p.version}{#if fit.short}<i>{fit.short}</i>{/if}" in card
      and ".cc-v.is-warn i" in card)
check("and the app it was made with, in a sentence, where you look inside",
      "const fit = $derived(appWords(p?.app, home.app));" in inspect and "{fit.long}" in inspect)
check("yours shared from an older app is worth sending again", 'appFit(s.app, app)' in mine
      and 'kind={s.changed || fit === "older" ? "primary" : "ghost"}' in mine)
check("the catalog says which app you have, and each shared one which app it came from",
      '"app": rules.app_version(_version()),' in (ROOT / "app/utils/community.py").read_text(encoding="utf-8")
      and '"app": rules.app_version(e.get("app")),' in (ROOT / "app/utils/community.py").read_text(encoding="utf-8")
      and 'app={home.app ?? ""}' in read("lib/community/CommunityView.svelte"))
profiles_page = read("pages/Profiles.svelte")
check("your own cards say which version they are", "Community v{p.community.version}" in profiles_page
      and "Shared v{p.shared.version}" in profiles_page)

print("\n== the wire ==")
api = read("lib/api.ts")
check("every request says it is the panel", '{ "x-llmselfbot": "1", ...(options.headers as any) }' in api)
check("GitHub's pace isn't a stuck page", '"/api/community",' in api)
check("its loads count as the Profiles page's", 'community: "profiles",' in read("lib/busy.ts"))
win = read("lib/window.ts")
check("GitHub pages open from the app on the desktop, by the browser elsewhere", "export async function openGitHub(" in win
      and "api.communityLink(what, { ...opts, open: desktop })" in win)

print("\n== the logic, under Node ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "community_logic.mjs")], cwd=ROOT / "webui", capture_output=True,
                          text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "")
    check("community_logic.mjs passes", proc.returncode == 0, (proc.stdout + proc.stderr)[-800:])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
