"""A Snapchat account on its card: who it is, its picture, and what its login is doing.

A Snapchat card was a generic ghost with the login name under it, and while
the account started it said "launching the browser" for the whole minute or
two of logging in, whatever was going on. Now:

  * once it is in, the runner finds who is signed in on Snapchat's own account
    page, opened in a background tab and closed again, and the account's
    picture on its public profile: the profile photo first, the Bitmoji when
    there is no photo. The chat app's own user records were tried first and
    are no good for this: they have one shape for everybody, and the one
    behind the profile button follows whichever chat is open, which once
    named the account after a contact;
  * the panel serves the picture itself, and anywhere an account is shown
    without one draws Snapchat's own empty silhouette;
  * each step of the login says what it is doing, a login Snapchat turns down
    is reported as one and handed to a person, and a login saved under a name
    the account no longer has tries the name it has now;
  * and the runner's own lines reach the Logs page. Started with no window and
    nothing redirected, Node on Windows had a console of its own that nobody
    could see, so every word it said about logging in went nowhere.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(p):
    return (ROOT / p).read_text(encoding="utf-8").replace("\r\n", "\n")


bot = read("app/platforms/snapchat/snapbot.js")
run = read("app/platforms/snapchat/snapchat_runner.js")

print("== who is signed in ==")
who = bot[bot.index("async whoAmI()"):bot.index("async saveCookies(")]
check("read on Snapchat's own account page, in a tab opened in the background",
      '"Target.createTarget", { url: "about:blank", background: true }' in who
      and 'page.goto("https://accounts.snapchat.com/v2/welcome"' in who)
check("by the mark the page puts on the username for its own tests", '[data-testid="username"]' in who)
check("and the tab is closed again, whatever happens", "finally {\n      if (page) await page.close()" in who)
check("the chat app's user records are not read for it any more", "readSelf" not in bot and "__reactFiber" not in who)
check("nothing on the bot's own page is touched", ".click(" not in who and "this.page.goto" not in who)

print("\n== its picture ==")
pub = run[run.index("async function publicProfile("):run.index("async function recordIdentity(")]
check("from the public profile, read the way anyone could, without the signed-in session",
      "https://www.snapchat.com/add/${encodeURIComponent(username)}" in pub and "cookie" not in pub.lower())
check("from either shape of it: a public profile, or a plain account",
      "profile.publicProfileInfo || profile.userInfo" in pub and "__NEXT_DATA__" in pub)
check("the photo asked for at 400px, not the 90 it is linked at", '.replace(/_RS\\d+,\\d+_/, "_RS0,400_")' in pub)
rec = run[run.index("async function recordIdentity("):run.index("function loginDetails()")]
check("the profile photo first, the Bitmoji only when there is no photo",
      rec.index('kind = "photo"') < rec.index('kind = "bitmoji"') and "if (!picture && pub?.bitmoji)" in rec)
check("pictures only from Snapchat's and Bitmoji's own addresses",
      r"(sc-cdn\.net|bitmoji\.com|snapchat\.com)" in run and "if (!url || !PICTURE_HOSTS.test(url)) return \"\";" in run)
check("fetched again only when their address changes", "before.url === url" in run)
check("and one that is not the picture any more is removed", "fs.unlinkSync(path.join(DATA_DIR, \"config\", old))" in rec)
check("kept in config/identity_snap_N.json, written whole or not at all",
      "`identity_snap_${ACCOUNT_INDEX}.json`" in run and "fs.renameSync(tmp, IDENTITY_FILE)" in rec)
check("read after logging in and logging back in, and after a refresh when six hours old",
      run.count("await recordIdentity(bot);") == 2 and "await recordIdentity(bot, { maxAgeHours: 6 });" in run)
check("a page that cannot be read leaves the card with what it had", "the panel keeps what it had" in rec)

print("\n== the login says what it is doing ==")
for step in ("checking the saved login", "logging in", "waiting for Snapchat to let it in", "opening the chats"):
    check(f"\"{step}\"", f'setState("starting", "{step}")' in run)
check("and the card shows it", 'line: snap.detail ? cap(snap.detail)' in read("webui/src/lib/accounts/condition.ts"))

print("\n== a login Snapchat turns down ==")
refusal = bot[bot.index("async loginRefusal()"):bot.index("async enterUsername(")]
check("is read off the page: the reason in the address, and red text on screen",
      'searchParams.get("loginError")' in refusal and "c[0] > 170 && c[1] < 90 && c[2] < 110" in refusal)
check("not the page title a screen reader is told on every step, which stopped every login at the password",
      'e.closest("next-route-announcer, [role=\'alert\']")' in refusal and "box.width < 4" in refusal)
enter = bot[bot.index("async enterUsername("):bot.index("async login(credentials)")]
check("the answer to the name is waited for, the password box or the form again, not guessed after three seconds",
      "for (const until = Date.now() + 20000; Date.now() < until;)" in enter and "pw.boundingBox()" in enter)
check("a name Snapchat does not know tries the next one: the name the account has now",
      "accountnotfound|couldn.?t find" in enter and "continue;" in enter)
check("which the runner passes when the saved login is a username the account no longer has",
      "function loginDetails()" in run and run.count("await bot.login(loginDetails());") == 2
      and 'saved.includes("@")' in run)
hand = run[run.index("async function handToPerson("):run.index("// ── Main")]
check("a refusal is not waited on as a verification: it is handed to a person, with what Snapchat said",
      'setState("needs-login"' in hand and "${said}" in hand
      and run.index("if (bot.lastLoginError) {") < run.index('setState("awaiting-verification",'))
check("the card gets a short line: Snapchat's first sentence, cut at 90 characters",
      "(why.match(/^[^.!?]*[.!?]/) || [why])[0]" in hand and "said.length > 90" in hand)
check("with no window to log in to, the card says how to get one", 'Turn off "Hide the browser window"' in hand)
check("logging back in mid-run hands over the same way", "if (bot.lastLoginError && !(await handToPerson(bot, " in run)
cond = read("webui/src/lib/accounts/condition.ts")
check("the card says what to do", 'snap.state === "needs-login"' in cond and 'title: "Log in yourself, once"' in cond)
setup = read("webui/src/lib/components/SnapchatSetup.svelte")
check("and so does the Snapchat page", '"needs-login": "warn"' in setup and '"needs-login": "Waiting for you to log in"' in setup)

print("\n== the runner's own lines reach the Logs page ==")
bridge = read("app/platforms/snapchat_bridge.py")
spawn = bridge[bridge.index("_node_proc = subprocess.Popen("):bridge.index("def _relay_node_output")]
check("Node's output is taken, not left to a console nobody sees",
      "stdout=subprocess.PIPE" in spawn and "stderr=subprocess.STDOUT" in spawn and "stdin=subprocess.DEVNULL" in spawn)
check("still with no window of its own", "**quiet_kwargs()" in spawn)
check("and passed on line by line, never in the middle of a Chats event", "target=_relay_node_output" in spawn
      and "sys.stdout.write(line + " in bridge and "with _OUT_LOCK:" in bridge and "sharing this window" not in bridge)

print("\n== the panel ==")
import app.utils.paths as paths  # noqa: E402
tmp = Path(tempfile.mkdtemp(prefix="llmbot_snapid_"))
cfg = tmp / "config"
cfg.mkdir()
paths.DATA_DIR = tmp
from app.web.routes import status_routes, account_routes  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

check("an account that has not signed in yet has nothing to say", status_routes._identity("snapchat", 1) == {})
(cfg / "identity_snap_1.json").write_text(json.dumps({"username": "aliciamwwoff", "display_name": "Alicia", "picture": "",
                                                     "picture_kind": "", "background": ""}), encoding="utf-8")
got = status_routes._identity("snapchat", 1)
check("one with no picture: its name, and Snapchat's yellow for the banner",
      got == {"username": "aliciamwwoff", "display_name": "Alicia", "avatar": "", "picture_kind": "", "banner": "",
              "accent": "#fffc00"}, str(got))
(cfg / "identity_snap_2.jpg").write_bytes(b"\xff\xd8 photo")
(cfg / "identity_snap_2_bg.webp").write_bytes(b"RIFF0000WEBPVP8 background")
(cfg / "identity_snap_2.json").write_text(json.dumps({"username": "juni", "display_name": "Juniper", "picture_kind": "photo",
                                                     "picture": "identity_snap_2.jpg",
                                                     "background": "identity_snap_2_bg.webp"}), encoding="utf-8")
got = status_routes._identity("snapchat", 2)
check("one with a photo: the picture and a background, served by the panel",
      got["avatar"].startswith("/api/accounts/snapchat_2/picture?v=") and got["banner"].startswith("/api/accounts/snapchat_2/banner?v=")
      and got["accent"] == "" and got["picture_kind"] == "photo", str(got))
(cfg / "identity_snap_4.jpg").write_bytes(b"\xff\xd8 photo")
(cfg / "identity_snap_4.json").write_text(json.dumps({"username": "p", "picture": "identity_snap_4.jpg", "picture_kind": "photo"}),
                                         encoding="utf-8")
got = status_routes._identity("snapchat", 4)
check("a photo and no background: the card blurs the photo into its banner, not Snapchat's yellow",
      got["avatar"] and got["banner"] == "" and got["accent"] == "", str(got))
app = FastAPI()
app.include_router(status_routes.router)
c = TestClient(app)
check("the picture is served", c.get("/api/accounts/snapchat_2/picture").content.endswith(b"photo"))
check("and its background", c.get("/api/accounts/snapchat_2/banner").content.endswith(b"background"))
(cfg / "identity_snap_3.json").write_text(json.dumps({"username": "x", "picture": "identity_snap_2.jpg"}), encoding="utf-8")
check("a file named in the record that is not that account's own is not served",
      c.get("/api/accounts/snapchat_3/picture").status_code == 404 and status_routes._identity("snapchat", 3)["avatar"] == "")
(cfg / "identity_snap_3.json").write_text(json.dumps({"username": "x", "picture": "../../secret.jpg"}), encoding="utf-8")
check("nor anything outside the folder", c.get("/api/accounts/snapchat_3/picture").status_code == 404)
check("nor for an account that is not a Snapchat one", c.get("/api/accounts/discord_1/picture").status_code == 404)
check("Discord accounts are read as before", status_routes._identity("discord", 1) == {})

print("\n== removing an account ==")
(cfg / "identity_snap_3.json").write_text(json.dumps({"username": "three", "picture": "identity_snap_3.png"}), encoding="utf-8")
(cfg / "identity_snap_3.png").write_bytes(b"png three")
(cfg / "identity_snap_10.json").write_text(json.dumps({"username": "ten"}), encoding="utf-8")
account_routes._renumber_account_data("snapchat", 2, 3)
names = sorted(p.name for p in cfg.iterdir())
moved = json.loads((cfg / "identity_snap_2.json").read_text(encoding="utf-8"))
check("the removed account's name and pictures go", "identity_snap_2_bg.webp" not in names and "identity_snap_2.jpg" not in names)
check("the later ones move up a number, their pictures with them",
      moved["username"] == "three" and moved["picture"] == "identity_snap_2.png"
      and (cfg / "identity_snap_2.png").read_bytes() == b"png three" and "identity_snap_3.json" not in names, str(names))
check("and account 10 is not taken for account 1's", "identity_snap_10.json" in names
      and json.loads((cfg / "identity_snap_1.json").read_text(encoding="utf-8"))["username"] == "aliciamwwoff")
shutil.rmtree(tmp, ignore_errors=True)

print("\n== wherever an account is shown ==")
avatar = read("webui/src/lib/components/Avatar.svelte")
check("with no picture, Snapchat's own empty silhouette rather than a generic glyph",
      "silhouette = false," in avatar and "{:else if silhouette}" in avatar and 'class="avatar-silhouette' in avatar)
card = read("webui/src/lib/accounts/AccountCard.svelte")
check("on its card", "{#if rt?.avatar || silhouette}" in card and "{silhouette} />" in card
      and 'slot.platform === "snapchat" && !rt?.avatar && !!rt?.username' in card)
widget = read("webui/src/lib/dashboard/AccountsWidget.svelte")
check("and on the Dashboard", widget.count('silhouette={r.slot.platform === "snapchat" && !!r.rt?.username}') == 2)
check("the name it shows, with its @username under it", "rt?.display_name || rt?.username" in card
      and 'rt?.username && rt.username !== name ? rt.username : ""' in card)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
