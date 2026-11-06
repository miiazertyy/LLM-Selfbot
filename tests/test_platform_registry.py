"""The one table of platforms (app/platforms/registry.py), and every place that has to know a new one.

This is what to run when adding a platform: docs/ADDING_A_PLATFORM.md. Put its row in the table, and this says which parts
do not know it yet, file by file. It also keeps a list of all the platforms from being written out again by hand: that is
how each new one came to be missing from some of them.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name

from app.platforms import registry  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


print("\n== the table says what the lists used to ==")
check("the ten, in the order they are shown",
      registry.IDS == ("discord", "snapchat", "tiktok", "instagram", "x", "reddit", "whatsapp", "minecraft", "imessage", "telegram"))
check("run by the bridge: all but Discord", registry.BRIDGED == registry.IDS[1:])
check("past Snapchat", registry.BRIDGED_BUT_SNAPCHAT == registry.IDS[2:])
check("driven through a website", registry.WEBSITES == ("snapchat", "tiktok", "instagram", "x", "reddit"))
check("with posts as well as messages", registry.FEEDS == ("tiktok", "instagram", "x", "reddit"))
check("what their IPC targets start with", registry.TARGETS == {
    "snapchat": "snap", "tiktok": "tiktok", "instagram": "insta", "minecraft": "mc", "imessage": "imsg",
    "telegram": "tg", "x": "x", "reddit": "reddit", "whatsapp": "wa"})
check("the endings of their tables", registry.TABLES == {
    "snapchat": "snap", "tiktok": "tiktok", "instagram": "instagram", "minecraft": "minecraft", "imessage": "imessage",
    "telegram": "telegram", "x": "x", "reddit": "reddit", "whatsapp": "whatsapp"})
check("what a person's id starts with", registry.HANDLED == {
    "tiktok": "tt_", "instagram": "ig_", "minecraft": "mc_", "x": "x_", "reddit": "rd_", "whatsapp": "wa_"})
check("a name written its own way", registry.name_of("tiktok") == "TikTok" and registry.name_of("imessage") == "iMessage"
      and registry.name_of("whatsapp") == "WhatsApp" and registry.name_of("someday") == "Someday")
check("an account's id", registry.ACCOUNT_ID.match("tiktok_12").groups() == ("tiktok", "12")
      and not registry.ACCOUNT_ID.match("tiktok_0") and not registry.ACCOUNT_ID.match("nope_1"))
check("only Discord and Telegram run on a phone: the rest need Node beside the app",
      tuple(p.id for p in registry.PLATFORMS if p.on_phone) == ("discord", "telegram"))

print("\n== everything else is made from it ==")
from app.utils import chatlog, db, snappeople, socials  # noqa: E402

check("the switches", socials.SOCIALS == registry.IDS)
check("the tables", db.WEB_TABLES is registry.TABLES and snappeople._TABLES is registry.TABLES)
check("each platform's own band of the chat log, with none shared",
      chatlog._WEB_BASES["reddit"] == (chatlog.REDDIT_BASE, "reddit") and chatlog._WEB_BASES["snapchat"] == (chatlog.SNAP_BASE, "snap")
      and len({p.log_base for p in registry.PLATFORMS}) == len(registry.PLATFORMS))
check("and the old names for the bands agree", all(
    registry.BY_ID[p].log_base == b for p, b in (("snapchat", chatlog.SNAP_BASE), ("tiktok", chatlog.TIKTOK_BASE),
                                                 ("instagram", chatlog.INSTAGRAM_BASE), ("minecraft", chatlog.MINECRAFT_BASE),
                                                 ("imessage", chatlog.IMESSAGE_BASE), ("telegram", chatlog.TELEGRAM_BASE),
                                                 ("x", chatlog.X_BASE), ("reddit", chatlog.REDDIT_BASE), ("whatsapp", chatlog.WHATSAPP_BASE))))

print("\n== the panel's table agrees with this one ==")
ts = read("webui/src/lib/platforms.ts")
# Its own order (where it shows them is its business), and its short name where it has one: "X (Twitter)" is X.
rows = {i: s or n for i, n, s in re.findall(r'^\s{2}(\w+): \{\n\s+id: "\w+", name: "([^"]+)"(?:, short: "([^"]+)")?', ts, re.M)}
check("the same platforms", set(rows) == set(registry.IDS), str(sorted(rows)))
check("under the same names", rows == {p.id: p.name for p in registry.PLATFORMS}, str(rows))
tones = dict(re.findall(r'id: "(\w+)", name: "[^"]+"(?:, short: "[^"]+")?, icon: "\w+", tone: "(#[0-9a-fA-F]+)"', ts))
differ = [p.id for p in registry.PLATFORMS if p.id in tones and tones[p.id].lower() != p.tone.lower()]
check("in the same colours", not differ, str(differ))

print("\n== no list of them written out by hand ==")
# A line naming most of the platforms, in code rather than a comment. A list that is only some of them is fine (what a
# phone cannot run, what has posts); one that is most of them and not all is a platform that got missed.
NAME = re.compile(r"(?<![A-Za-z0-9_.-])(" + "|".join(registry.IDS) + r")(?![A-Za-z0-9_-])")
# These are not lists to keep up to date: each says something about the platforms it names, or is the table itself.
ALLOWED = {
    "app/platforms/registry.py", "webui/src/lib/platforms.ts", "webui/src/lib/components/Icon.svelte",
    # "This file is the plain parts, and nothing else is imported": its own test runs it alone.
    "webui/src/lib/personas/logic.ts",
    # Words for people to read, or for a developer.
    "app/cli.py", "app/core/ipc.py", "app/utils/logger.py", "app/utils/snappeople.py",
    "app/web/descriptions.py",
    # The ones its page is for.
    "webui/src/lib/components/SnapchatSetup.svelte",
}
missed = []
for root in ("app", "webui/src"):
    for path in (ROOT / root).rglob("*"):
        if path.suffix not in (".py", ".ts", ".svelte", ".js", ".mjs") or "node_modules" in path.parts or "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if rel in ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith(("#", "//", "*", "/*", "<!--")):
                continue
            # A comment at the end of a line is words too.
            line = line.split("  # ")[0] if path.suffix == ".py" else line.split("  // ")[0]
            found = set(NAME.findall(line))
            if len(found) >= 6 and found != set(registry.IDS):
                missed.append(f"{rel}:{n} ({', '.join(sorted(set(registry.IDS) - found))} missing)")
check("every line naming most of them names them all, or uses registry.py instead", not missed, "; ".join(missed[:12]))

print("\n== what every platform has of its own ==")
# Each is a place a new platform has to go. {id}, {target} and {name} are filled in from its row.
OF_ITS_OWN = [
    ("webui/src/lib/platforms.ts", '  {id}: {{\n', "its row for the panel"),
    ("resources/config.yaml", "\n{id}:", "its section of settings"),
    ("app/web/routes/account_routes.py", '"{id}": {{', "which .env names hold an account's login"),
    ("webui/src/lib/settingsmap.ts", 'id: "{id}",', "its tab in Settings"),
    ("webui/src/lib/components/Icon.svelte", "{id}:", "its logo"),
    ("webui/src/app.css", ".settings-mark.is-{id} {{ --mark-s:", "its logo measured: same area, centred"),
]
for p in registry.PLATFORMS:
    for rel, want, what in OF_ITS_OWN:
        text = read(rel)
        check(f"{p.id}: {what}", want.format(id=p.id) in text, f"add it to {rel}: {want.format(id=p.id)!r}")
    if p.target and p.id != "snapchat":
        bridge = read("app/platforms/snapchat_bridge.py")
        check(f"{p.id}: its entry in the bridge's table", f'"{p.id}": {{' in bridge, "add it to PLATFORMS in app/platforms/snapchat_bridge.py")
    check(f"{p.id}: the supervisor knows how to count its accounts", f'"{p.id}": _count_' in read("app/web/supervisor.py"),
          "add it to counts in app/web/supervisor.py")
    check(f"{p.id}: Settings draws its switch as one", f'"services.{p.id if p.id != "telegram" else "telegram_accounts"}.enabled"' in read("webui/src/pages/Settings.svelte"),
          "add it to BOTH in webui/src/pages/Settings.svelte")

print("\n== a website changing ==")
watch = read("app/platforms/snapchat/sitewatch.js")
for p in registry.WEBSITES:
    runner = read(f"app/platforms/snapchat/{p}_runner.js")
    check(f"{p}: looks for what should be on its page", "new SiteWatch(" in runner and "siteWatch.tick()" in runner)
    if p != "snapchat":
        check(f"{p}: a fix goes in without a new build", f'applySiteFixes(SEL, "{p}", DATA_DIR' in runner)
check("what it finds stays said, whatever state comes next", "...standing, ...extra" in read("app/platforms/snapchat/runner_core.js"))
check("and reaches the panel", '"site": data["site"]' in read("app/web/routes/system_routes.py"))
check("and the card", "may have changed its page" in read("webui/src/lib/accounts/condition.ts"))
check("it opens and loads nothing", not re.search(r"\.(goto|reload|newPage)\(", watch))
check("a fix only ever names selectors: nothing in the file is run", "eval(" not in watch and "new Function" not in watch)
check("Snapchat's look is on the tab it already has: a new session is what it locks on",
      "pages: () => bot?.browser?.pages()" in read("app/platforms/snapchat/snapchat_runner.js"))

import shutil  # noqa: E402
import subprocess  # noqa: E402

node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "sitewatch_logic.mjs")], cwd=str(ROOT), capture_output=True, text=True,
                          timeout=120, encoding="utf-8", errors="replace")
    print("\n".join("  " + line for line in proc.stdout.strip().splitlines()[-3:]))
    check("sitewatch_logic.mjs passes", proc.returncode == 0, (proc.stdout + proc.stderr)[-700:])

print("\n== what a runner needs reaches where it runs ==")
# An installed app runs them from the data folder, copied there from the build (snapchat_bridge._sync_runner_files). Each
# file one of them imports beside it has to be copied too, or that runner stops at its first line.
import tempfile as _tf  # noqa: E402

from app.platforms import snapchat_bridge as _bridge  # noqa: E402

_runners = ROOT / "app/platforms/snapchat"
_needed = set()
for _f in list(_runners.glob("*.js")) + list(_runners.glob("*.mjs")):
    _needed |= set(re.findall(r"""from\s+["']\./([\w.-]+\.m?js)["']""", _f.read_text(encoding="utf-8")))
with _tf.TemporaryDirectory() as _dst:
    _copied = set(_bridge._sync_runner_files(_runners, Path(_dst)))
check("everything the runners import beside them is copied", _needed and not (_needed - _copied), str(sorted(_needed - _copied)))
check("the site watch among them", "sitewatch.js" in _copied)

print("\n== the doc ==")
doc = read("docs/ADDING_A_PLATFORM.md")
for needed in ("registry.py", "platforms.ts", "test_platform_registry.py", "sitefixes", "SiteWatch", "probe"):
    check(f"it mentions {needed}", needed in doc)

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
