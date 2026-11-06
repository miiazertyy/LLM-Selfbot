"""TikTok, the third platform: driven through tiktok.com in the account's own Chrome, as Snapchat is.

Run for real, in a throwaway data folder:
  * the plumbing: its IPC targets and their files, the web ids, the chat log's numbers, the people's ids, its own
    database tables, the accounts the supervisor starts (none on a phone), the bridge as TikTok's
  * signing in: a slot is a TikTok username as TikTok allows it (it names the account's browser profile), so
    nothing else is stored, by the sign-in or by hand
  * a shared TikTok, on any platform: what it is, from TikTok's public oEmbed (stubbed here), for the persona and
    for its card in the Chats tab
  * the LIVE: what was said and answered, kept per account for the panel and the OBS page, and its voice files
    served by name only

Read from the source: the runner and its bot (both generations of TikTok's inbox, its warnings, the captcha
hand-over, the dry run, the probe that never dumps text), and the UI (the platform table, the Accounts sign-in,
Chats, Settings, the LIVE view and the OBS page, sounds and the Animations switch). And tiktok_logic.mjs runs the
runner's pure parts under Node.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="llmbot_tiktok_"))
(DATA / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
for k in list(os.environ):
    if k.startswith(("TIKTOK_USERNAME_", "SNAP_USERNAME", "DISCORD_TOKEN")):
        del os.environ[k]
os.environ["TIKTOK_USERNAME_1"] = "theo.wav"
os.environ["TIKTOK_USERNAME_2"] = "mara_k"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def refused(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


# ── Plumbing ─────────────────────────────────────────────────────────────────
print("== where its messages go ==")
from app.core import ipc  # noqa: E402

check("its accounts are counted from .env", ipc._count_tiktok_accounts() == 2)
check("its targets are tiktok, tiktok2 ...", ipc.validate_target("tiktok") == "tiktok" and ipc.validate_target("tiktok2") == "tiktok2")
check("and nothing else that looks like one", all(refused(ipc.validate_target, t) for t in ("tiktok1", "tiktok0", "tiktokx", "../tiktok")))
check("a target and a web id are each other's", ipc.target_for("tiktok_1") == "tiktok" and ipc.target_for("tiktok_2") == "tiktok2"
      and ipc.web_id_for("tiktok2") == "tiktok_2")
check("told apart from Snapchat's and Discord's", ipc.is_tiktok("tiktok2") and not ipc.is_tiktok("snap")
      and ipc.platform_of("tiktok") == "tiktok" and ipc.platform_of("snap2") == "snapchat" and ipc.platform_of(3) == "discord")
check("both are browser accounts, with their commands beside the bridge's files", ipc.is_browser("tiktok") and ipc.is_browser("snap")
      and not ipc.is_browser(1) and ipc.cmd_file("tiktok2").parent == ipc.cmd_file("snap").parent)
check("discovered with the rest", {"tiktok_1", "tiktok_2"} <= set(ipc.discover_targets()))

from app.utils import chatlog, snappeople  # noqa: E402

check("its chat log has numbers of its own", chatlog.log_account("tiktok") == 2001 and chatlog.log_account("tiktok2") == 2002
      and chatlog.log_account("snap") != 2001)
check("a person's id is tt_ and their handle, and reads back", snappeople.tiktok_id("@Theo.Wav") == "tt_theo-wav"
      and snappeople.tiktok_handle("tt_theo-wav") == "theo.wav")
check("which platform someone is on, by their id", snappeople.platform_of_user("tt_theo-wav") == "tiktok"
      and snappeople.platform_of_user("1234") == "discord" and snappeople.platform_of_user("abc-1") == "snapchat")

from app.utils import db  # noqa: E402

db.init_db()
db.record_user_message_web("tiktok", "tt_theo-wav", "Theo", account=1)
db.record_user_message_web("tiktok", "tt_theo-wav", "Theo", account=1)
db.add_ignored_user_web("tiktok", "tt_spam-bot")
board = db.get_leaderboard_web("tiktok")
check("its own leaderboard", board and str(board[0][0] if isinstance(board[0], (list, tuple)) else board[0].get("user_id")) == "tt_theo-wav",
      str(board))
check("and its own ignore list, apart from Snapchat's", "tt_spam-bot" in db.get_ignored_users_web("tiktok")
      and "tt_spam-bot" not in db.get_ignored_users_snap())

print("\n== what runs ==")
from app.web.supervisor import Supervisor  # noqa: E402

plan = Supervisor._planned_children(None)
check("each signed-in TikTok account runs", plan.get("tiktok_1", (None,))[0] == "tiktok" and "tiktok_2" in plan, str(sorted(plan)))
os.environ["LLMSELFBOT_DEVICE"] = "android"
try:
    phone = Supervisor._planned_children(None)
finally:
    del os.environ["LLMSELFBOT_DEVICE"]
check("but not on a phone, which has no Chrome to drive", not any(k.startswith("tiktok") for k in phone), str(sorted(phone)))
from app.utils import compat  # noqa: E402

check("a phone says why", (compat.check("tiktok", "android") or {}).get("why") == "TikTok needs a computer.")
check("ARM Linux needs Chromium, as Snapchat does", ((compat.check("tiktok", "linux-arm64") or {}).get("fix") or {}).get("command")
      == "sudo apt install chromium" or compat._chromium())

print("\n== settings ==")
from app.web.schema import CONFIG_SCHEMA  # noqa: E402
from app.web import descriptions as desc  # noqa: E402

keys = {f["key"] for f in CONFIG_SCHEMA}
for k in ("tiktok.enabled", "tiktok.min_send_gap_ms", "tiktok.max_sends_per_hour", "tiktok.accept_message_requests",
          "tiktok.follow_back", "tiktok.comments.enabled", "tiktok.live.enabled", "tiktok.live.voice", "tiktok.live.per_minute"):
    check(f"{k} is a setting, described", k in keys and bool(desc.DESCRIPTIONS.get(k) if hasattr(desc, "DESCRIPTIONS") else True))
cfg = read("resources/config.yaml")
check("comments and the LIVE are off until switched on", "comments:\n    enabled: false" in cfg and "live:\n    enabled: false" in cfg)
check("cautious by default: 20 sends an hour, 15 to 45 seconds apart", "max_sends_per_hour: 20" in cfg
      and "min_send_gap_ms: 15000" in cfg and "max_send_gap_ms: 45000" in cfg)

# ── The bridge, as TikTok's ─────────────────────────────────────────────────
print("\n== the bridge, as TikTok's ==")
os.environ["BRIDGE_PLATFORM"] = "tiktok"
os.environ["TIKTOK_ACCOUNT_INDEX"] = "2"
from app.platforms import snapchat_bridge as b  # noqa: E402

check("it says TikTok", b.PLATFORM == "tiktok" and b.PLATFORM_NAME == "TikTok")
check("its files are TikTok's, numbered", b.INCOMING_FILE.name == "tiktok_incoming_2.json" and b.CMD_FILE.name == "tg_commands_tiktok2.json"
      and b.LOG_ACCOUNT == 2002)
check("it runs TikTok's runner", b.P["runner"] == "tiktok_runner.js")
check("TikTok's own few reactions", b.SNAP_REACTIONS[:2] == b.P["reactions"][:2] and "❤️" in b.SNAP_REACTIONS)
env = b._tiktok_env({"tiktok": {"headless": True, "max_sends_per_hour": 12, "comments": {"enabled": True, "per_hour": 5},
                                "live": {"enabled": True, "chat": False}},
                     "bot": {"locale": "fr-FR", "trigger": "Alicia", "night_invisible": {"hours": "2-8"},
                             "friend_requests": {"accept_delay_min": 60, "accept_delay_max": 600}}})
check("its settings reach the runner", env.get("TIKTOK_HEADLESS") == "true" and env.get("TIKTOK_MAX_SENDS_PER_HOUR") == "12"
      and env.get("TIKTOK_COMMENTS") == "true" and env.get("TIKTOK_COMMENTS_PER_HOUR") == "5", str(env))
check("the LIVE, and whether it types in the chat", env.get("TIKTOK_LIVE") == "true" and env.get("TIKTOK_LIVE_CHAT") == "false")
check("the persona's language, name and nights", env.get("TIKTOK_LOCALE") == "fr-FR" and env.get("TIKTOK_TRIGGER") == "Alicia"
      and env.get("TIKTOK_NIGHT_HOURS") == "2-8")
check("requests wait as friend requests do", env.get("TIKTOK_ACCEPT_DELAY_MIN") == "60" and env.get("TIKTOK_ACCEPT_DELAY_MAX") == "600")
# Every script in the folder is, so a new one cannot be left out (tests/test_platform_registry.py runs the copy).
check("every runner file is mirrored to where Node runs it", 'p.suffix in (".js", ".mjs")' in read("app/platforms/snapchat_bridge.py")
      and all((ROOT / "app/platforms/snapchat" / n).is_file()
              for n in ("browser.js", "runner_core.js", "tiktokbot.js", "tiktok_runner.js", "tiktok_login.js", "tiktok_probe.js")))

# ── Signing in ───────────────────────────────────────────────────────────────
print("\n== signing in ==")
from app.utils import tiktok_browser_login as login  # noqa: E402

check("a username as TikTok allows it", login.clean_handle("@Theo.Wav") == "theo.wav" and login.clean_handle("mara_k") == "mara_k")
check("anything else is none", all(login.clean_handle(h) == "" for h in ("../x", "a/b", "x", "a" * 25, "..", "theo wav", "")))
check("its profile is named by it, inside the config folder", login.profile_dir("Theo.Wav").name == "tiktok-theo.wav-profile"
      and login.profile_dir("../../x").parent == login.profile_dir("theo.wav").parent)
check("nothing signing in yet", login.status().get("state") in ("idle", None, ""), str(login.status()))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import account_routes, chat_routes  # noqa: E402

app = FastAPI()
app.include_router(account_routes.router)
app.include_router(chat_routes.router)
client = TestClient(app)
st = client.get("/api/accounts/tiktok/browser-login/status")
check("the panel asks where a sign-in has got to", st.status_code == 200 and "state" in st.json(), st.text[:200])
r = client.post("/api/accounts/slots/tiktok", json={"username": "../../evil"})
check("a slot added by hand must be a TikTok username", r.status_code == 400, r.text[:200])
r = client.post("/api/accounts/slots/tiktok", json={"username": "@Kit.Films"})
slots = [s for s in (r.json().get("slots") or []) if s.get("platform") == "tiktok"] if r.status_code == 200 else []
check("and is stored as TikTok writes it", r.status_code == 200 and any(s.get("username") == "kit.films" for s in slots), r.text[:300])
check("signed in again as the same account: the same slot", r.status_code == 200 and account_routes._store_tiktok(
    account_routes._migrate_legacy(account_routes.read_env()), "@KIT.films")[0] == r.json().get("index"))

# ── A shared TikTok ──────────────────────────────────────────────────────────
print("\n== a shared TikTok ==")
from app.utils import tiktoklinks  # noqa: E402

url = "https://www.tiktok.com/@lakeside.films/video/7412345678901234567"
check("found in a message", tiktoklinks.links_in(f"look {url}?is_from_webapp=1 and https://vm.tiktok.com/ZMabc/ x")[1]
      == "https://vm.tiktok.com/ZMabc/")
check("and only TikTok's", tiktoklinks.links_in("https://example.com/@a/video/1 https://youtube.com/x") == [])
asked = []


async def fake_lookup(u, timeout=6.0):
    asked.append(u)
    return {"title": "golden hour at the lake", "author_name": "Lakeside Films", "author_unique_id": "lakeside.films",
            "thumbnail_url": "https://p16-sign.tiktokcdn.com/cover.jpg"}


real_lookup, tiktoklinks.lookup = tiktoklinks.lookup, fake_lookup
try:
    text, cover = asyncio.run(tiktoklinks.enrich(f"this is so your vibe {url}"))
    check("the persona is told whose it is and what it says", "@lakeside.films" in text and "golden hour at the lake" in text, text)
    check("and sees its cover", cover == "https://p16-sign.tiktokcdn.com/cover.jpg")
    card = client.get("/api/chats/tiktok-card", params={"url": url})
    check("its card in the Chats tab", card.status_code == 200 and card.json().get("author") == "lakeside.films"
          and card.json().get("cover", "").startswith("https://"), card.text[:200])
    check("only TikTok links are asked about", client.get("/api/chats/tiktok-card", params={"url": "https://evil.example/x"}).status_code == 400
          and all("tiktok.com" in u for u in asked))
finally:
    tiktoklinks.lookup = real_lookup
check("a link to nothing is no line", tiktoklinks.describe({}) == "")

# ── The LIVE ─────────────────────────────────────────────────────────────────
print("\n== the LIVE ==")
chat_routes.apply_chat_event("tiktok_1", {"t": "live_state", "live": True})
chat_routes.apply_chat_event("tiktok_1", {"t": "live", "event": "comment", "name": "noah.k", "text": "what camera is that??"})
chat_routes.apply_chat_event("tiktok_1", {"t": "live_say", "id": "a1", "to": "noah.k", "text": "a canonet", "audio": []})
feed = client.get("/api/live/tiktok_1").json()
check("whether it is live, and what was said and answered, in order", feed.get("live") is True
      and [x["t"] for x in feed.get("feed", [])] == ["live", "live_say"], str(feed))
check("only a TikTok account has one", client.get("/api/live/discord_1").status_code == 404)
check("its voice is served by name only", client.get("/api/live/tiktok_1/audio/..%2F..%2Fconfig.yaml").status_code in (400, 404)
      and client.get("/api/live/tiktok_1/audio/nothing.wav").status_code in (400, 404))
check("LIVE lines stay out of the conversations' own feed","live" not in str(chat_routes._CHAT_EVENTS.get("tiktok", "")))

# ── The runner and its bot, from the source ──────────────────────────────────
print("\n== the runner and its bot ==")
bot = read("app/platforms/snapchat/tiktokbot.js")
run = read("app/platforms/snapchat/tiktok_runner.js")
brw = read("app/platforms/snapchat/browser.js")
probe = read("app/platforms/snapchat/tiktok_probe.js")
loginjs = read("app/platforms/snapchat/tiktok_login.js")
check("both generations of TikTok's inbox: the frame and the old page", 'iframe[src*="/messages"]' in bot
      and "dm-new-" in bot and "chat-list-item" in bot)
check("it types like a person, a line at a time", "typeDelay" in bot and "Shift" in bot)
check("TikTok's warnings become reasons, and too fast waits", "const why = await this.warning();" in bot
      and "return warningReason(text);" in bot and "/too fast|limit/i.test(out.reason" in run)
check("a check from TikTok brings the window forward and waits for the person", "captchaShown" in bot and "needs-you" in run
      and "showWindow" in bot)
check("a hidden window is off the screen, not headless, which TikTok flags", "-32000" in brw)
check("a dry run reads and answers, and sends nothing", "DRY_RUN" in run and "dryRun" in bot)
check("the runner refuses a handle TikTok could not have given", "/^[a-z0-9_.]{2,24}$/.test(HANDLE)" in run)
check("the probe records the page's shape, never what anyone wrote", "innerText" not in probe and "textContent" not in probe)
check("signing in waits for TikTok's own session cookie", "sessionid" in loginjs)
check("LIVE answers are capped a minute", "LIVE_PER_MINUTE" in run)

print("\n== read off the signed-in inbox ==")
check("its messages and the time labels over them", '[data-e2e="dm-new-chat-item"]' in bot
      and '[data-e2e="dm-new-time-separator"]' in bot)
check("and each one's sender, from their picture's link: theirs or the account's", "messageAuthor" in bot
      and "author ? author === own" in bot)
check("TikTok's unread count on a row, not a guess", '[data-e2e="dm-new-conversation-unread"]' in bot
      and "unread: marked ? unreadCount > 0" in bot)
check("what only the app shows is said as that, not as TikTok's words", 'kind = "unsupported"' in bot
      and "can't show" in run)
check("a shared video's cover goes to the vision model", "media.cover" in bot and "shared.media.cover" in run)
check("TikTok's twelve reactions, picked by their data-emoji", "data-emoji" in bot
      and '"🤪", "🙈"' in read("app/platforms/snapchat_bridge.py") and '"🤪", "🙈"' in read("webui/src/lib/platforms.ts"))
check("a reaction finds its message by its place on the page", "messages[index].idx" in run)
check("a request's own box: Delete first, Accept last, in any language", '[data-e2e="dm-new-stranger-accept"]' in bot
      and "buttons[buttons.length - 1] : buttons[0]" in bot)
check("follow back from the activity panel's new followers", '[data-e2e="follow-back"]' in bot and '[data-e2e="nav-activity"]' in bot)
check("a picture through the chat's own photo button", '[data-e2e="dm-new-media-btn"]' in bot and "waitForFileChooser" in bot)
check("Enter sends; its send button where Enter did not", '[data-e2e="dm-new-send-btn"]' in bot)
check("the message box is only looked for with a chat open", 'names.push("composer")' in bot)
check("its name and picture are the TikTok profile's, not the login's", "profileInfo" in bot
      and "__UNIVERSAL_DATA_FOR_REHYDRATION__" in bot and "followers: n(s.followerCount)" in bot)
check("and kept up to date, with its counts", "identityAt > 4 * 3600 * 1000" in run and '"followers", "following", "likes", "videos"' in run)
check("a closed window or a page gone from under it is opened again", "async ensure()" in bot and "(await bot.ensure()) !== \"ok\"" in run
      and "this.browser.on(\"disconnected\"" in bot)
check("and a closed window is not taken for being signed out", "A closed window, or a page gone from under it, looks signed out" in run)
check("only the list is watched for changes, not the whole page", "SEL.conversationList, SEL.totalUnread" in run)
check("a page whose frame came loose is replaced before anything is asked of it (a loose frame throws at once)",
      "this.page.mainFrame().detached) await this.ensure();" in bot and "let f;\n  try { f = await bot.inbox(); } catch { return; }" in run)
check("getting in is tried again on a fresh page, not given up on", "Opening TikTok went wrong" in run and "attempt >= 4" in run)
check("an unread profile never swaps its name and picture for the login's", "profiled: false" in bot
      and "if (!me.profiled && before.username === me.handle && before.display_name)" in run)
check("a runner gone takes its bridge with it, so the account restarts instead of answering nobody",
      "async def _runner_watch():" in read("app/platforms/snapchat_bridge.py") and "_runner_watch()]" in read("app/platforms/snapchat_bridge.py"))
check("a Chrome left holding the profile after a stop is closed, and the start tried again",
      "Failed to launch the browser process|browser is already running" in brw
      and "Failed to launch the browser process|browser is already running" in read("app/platforms/snapchat/snapbot.js"))

print("\n== the account's counts and its people ==")
os.environ["BRIDGE_PLATFORM"] = "tiktok"
(DATA / "config" / "identity_tiktok_2.json").write_text(
    '{"username": "mara_k", "display_name": "Mara", "followers": 1200, "following": 3, "likes": 98000, "videos": 12}', encoding="utf-8")
counts = b._profile_counts()
check("its status says its followers, following, likes and videos", counts == {"followers": 1200, "following": 3, "likes": 98000,
                                                                               "videos": 12}, str(counts))
body = b._body_of({"kind": "video", "text": "", "title": "lake.films · golden hour", "quote": "you up?",
                   "media": {"cover": "https://p16-sign.tiktokcdn.com/c.jpg"}})
check("a shared video is kept with its cover as a preview", body["embeds"][0] == {"title": "lake.films · golden hour",
      "image": "https://p16-sign.tiktokcdn.com/c.jpg", "provider": "TikTok"} and body["text"] == "[video]", str(body))
check("and a reply with what it answers", body.get("reply_to") == {"text": "you up?"}, str(body))
check("not a cover from anywhere", "embeds" not in b._body_of({"kind": "video", "media": {"cover": "http://x/c.jpg"}}))
card = read("webui/src/lib/accounts/AccountCard.svelte")
check("the card says them as TikTok does (1.2K)", "followers</span>{/if}" in card and 'notation: "compact"' in card)
check("a TikTok person's card has their @handle and their bio", '"username", "bio", "followers", "verified"' in read("app/web/routes/people_routes.py")
      and 'out[i]["username"] = handle_of(i)' in read("app/utils/snappeople.py"))
chats_src = read("webui/src/pages/Chats.svelte")
# All chats reads every account's archive now, but each is still asked for by its own account, never by whichever
# one happens to be open - which is what this was always about.
check("each account's recent conversations are its own: the account is fixed when its list is made",
      "return resource(`chatArchive:${t}`, () => api.chatArchive(100, t)" in chats_src
      and "const r = pastOf(t);" in chats_src and "api.chatArchive(100, target)" not in chats_src)
check("a reply shows what it answers, above it", 'class="cd-quote"' in chats_src and ".cd-quote {" in chats_src)
check("what only TikTok's app shows is said plainly", '"Only shows in the TikTok app"' in read("webui/src/lib/components/MessageBody.svelte")
      and '"[unsupported]": "Only shows in the TikTok app"' in chats_src)

# ── The UI, from the source ──────────────────────────────────────────────────
print("\n== the panel ==")
web = ROOT / "webui" / "src"
plat = read("webui/src/lib/platforms.ts")
check("one table of what each platform can do", 'tiktok: {' in plat and 'requests: "Message requests"' in plat and 'add: "Follow"' in plat
      and "calls: false" in plat)
acc = read("webui/src/pages/Accounts.svelte")
check("Accounts: a TikTok card, menu item and sign-in", 'openAdd("tiktok")' in acc and "Open TikTok and sign in" in acc
      and "tiktokBrowserLoginStart" in read("webui/src/lib/api.ts"))
chats = read("webui/src/pages/Chats.svelte")
check("Chats: its own words, avatars and reactions", "const plat = $derived(platformOf(current?.platform));" in chats
      and "silhouette={plat.silhouette}" in chats and "set={isSnap ? plat.reactions : undefined}" in chats)
mb = read("webui/src/lib/components/MessageBody.svelte")
check("a shared TikTok is a card, on any platform", "<TikTokCard url={u} />" in mb and "tiktokLinks(text" in mb)
card = read("webui/src/lib/components/TikTokCard.svelte")
check("which sounds as it arrives, not when drawn again", "if (asked) play(" in card)
check("and follows the app's Animations switch", 'data-motion="off"' in card and "prefers-reduced-motion" not in card)
check("Settings: a TikTok tab with its LIVE and comments", 'id: "tiktok"' in read("webui/src/lib/settingsmap.ts")
      and '"tiktok.live.enabled"' in read("webui/src/lib/settingsmap.ts"))
live = read("webui/src/lib/accounts/LiveView.svelte")
check("the LIVE view looks at once, then keeps looking", "refresh();\n    return visiblePoll(refresh, 2500);" in live)
check("and sounds what arrives", 'play("receive"' in live and 'play("tick"' in live)
over = read("webui/src/LiveOverlay.svelte")
check("the OBS page's see-through styles are its own: they no longer hide the app",
      ":global(html.is-live-overlay)" in over and ":global(.app-shell)" not in over and ":global(html), :global(body)" not in over)
check("mounted alone on its own address", 'params.has("live") ? LiveOverlay' in read("webui/src/main.ts"))
cardsrc = read("webui/src/lib/accounts/AccountCard.svelte")
check("the card's LIVE button lights while it is live", "acct-live" in cardsrc and "look(true);" in cardsrc)

# ── Node ─────────────────────────────────────────────────────────────────────
print("\n== the runner's pure parts, under Node ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "tiktok_logic.mjs")], cwd=ROOT, capture_output=True, text=True,
                          timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("tiktok_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print("\n== a warning that comes off the card, and following back that sticks ==")
core_src = read("app/platforms/snapchat/runner_core.js")
check("a state is only skipped when nothing about it changed",
      "if (state === lastState && detail === lastDetail && !Object.keys(extra).length) return;" in core_src)
if node:
    state_dir = Path(tempfile.mkdtemp(prefix="llm_state_"))
    script = ("import { createCore } from './app/platforms/snapchat/runner_core.js';\n"
              "import fs from 'fs';\n"
              f"const core = createCore({{ prefix: 'tiktok', env: 'TIKTOK', account: 1, dataDir: {json.dumps(str(state_dir))}, tag: 't' }});\n"
              "core.setState('ready', 'Running, but TikTok changed its page');\n"
              "core.setState('ready');\n"
              "const s = JSON.parse(fs.readFileSync(core.files.state, 'utf-8'));\n"
              "console.log(JSON.stringify(s));\n"
              "process.exitCode = s.detail === '' && s.state === 'ready' ? 0 : 1;\n")
    proc = subprocess.run([node, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True,
                          timeout=60, encoding="utf-8", errors="replace")
    check("set again without words, the old warning goes (under Node, the real core)", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-400:])
    shutil.rmtree(state_dir, ignore_errors=True)
for rel in ("app/platforms/snapchat/tiktok_runner.js", "app/platforms/snapchat/instagram_runner.js"):
    check(f"{rel.rsplit('/', 1)[1]}: a page found whole again takes its warning off",
          '} else if (h && core.state === "ready") {\n    // Everything found again' in read(rel))
# One look eight seconds after a reload put "changed its page" on the card of an account reading its inbox fine -
# a hidden window, a For You tab playing beside it - and it stayed until the next reload, 45 minutes later. It keeps
# looking now, and the inbox being read is what takes a list warning off, at once.
for rel in ("app/platforms/snapchat/tiktok_runner.js", "app/platforms/snapchat/instagram_runner.js"):
    src = read(rel)
    body = src.split("async function reportHealth() {", 1)[1].split("\n}\n", 1)[0]
    name = rel.rsplit("/", 1)[1]
    check(f"{name}: it keeps looking for up to half a minute before a page warning, not one look at eight seconds",
          "waited < 25000; waited += 2500" in body and "await delay(8000);" not in body
          and body.index("waited < 25000") < body.index('core.setState("ready", `Running, but'))
    check(f"{name}: and remembers what it found missing", "healthMissing = [...h.missing];" in body)
    check(f"{name}: an inbox read fine takes a conversation-list warning off at once, not at the next reload",
          "function listSeenWorking()" in src and "listSeenWorking();" in src
          and src.index("listSeenWorking();") > src.index("function listSeenWorking()"))
    check(f"{name}: but a warning about the message box is left to its own check, a read list proving nothing of it",
          '"composer"' not in src.split("function listSeenWorking()", 1)[1].split("\n}\n", 1)[0])
snap_src = read("app/platforms/snapchat/snapchat_runner.js")
check("Snapchat's own copy of the state: only skipped when nothing changed, and its warning cleared when found again",
      "if (state === lastState && detail === lastDetail) return;" in snap_src
      and '} else if (lastState === "ready") {\n    // Everything found again' in snap_src)
snapbot_src = read("app/platforms/snapchat/snapbot.js")
check("Snapchat's saved cookies kept fresh: at the first good read and every half hour after, not only at a login",
      "let cookiesSavedAt = 0;" in snap_src and "Date.now() - cookiesSavedAt > 30 * 60 * 1000" in snap_src
      and "bot.saveCookies(COOKIE_FILE, { quiet: true })" in snap_src)
check("and written whole or not at all, never empty over a good file",
      "if (!cookies.length) return;" in snapbot_src and "fs.renameSync(`${cookiePath}.tmp`, cookiePath);" in snapbot_src)
ig_src = read("app/platforms/snapchat/instagram_runner.js")
check("Instagram signed out for good is waited out, not read on as if signed in",
      ig_src.count("await waitSignedOut();") == 4 and "if (!(await bot.isLogged())) await signInNow();" not in ig_src)
check("suspended: looked at again every 6 hours, the card saying so meanwhile",
      'const hours = signInState === "suspended" ? 6 : 0.5;' in ig_src and "core.heartbeatState();" in ig_src
      and "it looks again every 6 hours" in ig_src)
bot_src = read("app/platforms/snapchat/tiktokbot.js")
check("following back is a real press, and looked at again after",
      "const btn = await this.page.$('[data-llm-fb=\"1\"]');" in bot_src and "await btn.click()" in bot_src
      and "/friends|amis|following|abonn|message/i.test" in bot_src)
check("nobody is tried twice in a day, restarts included", "tiktok_followback_${this.account}.json" in bot_src
      and "24 * 3600 * 1000" in bot_src and "skip.includes(h)" in bot_src)
check("and the log says who TikTok did not take", "TikTok did not take following back" in read("app/platforms/snapchat/tiktok_runner.js"))


# ── A handle changed in the panel takes its session with it ─────────────────
# The profile folder is named after the handle (config/tiktok-<handle>-profile) and holds the signed-in session.
# Changing the handle used to leave the folder behind, so the account opened a fresh, signed-out profile and had to be
# signed in by hand again - which TikTok cannot do by script. Found when the account was renamed on TikTok.
print("\n== a new handle keeps the session ==")
import fastapi as _fa  # noqa: E402
from fastapi.testclient import TestClient as _TC  # noqa: E402
from app.web.routes import account_routes as _ar  # noqa: E402
from app.web import envfile as _ef  # noqa: E402

_cfg = DATA / "config"
(_cfg / ".env").write_text("TIKTOK_USERNAME_1=oldname.tt\n", encoding="utf-8")
_old = _cfg / "tiktok-oldname.tt-profile"
(_old / "Default").mkdir(parents=True, exist_ok=True)
(_old / "Default" / "Cookies").write_text("the session", encoding="utf-8")
(_cfg / "tiktok-oldname.tt-cookies.json").write_text("[]", encoding="utf-8")


class _Sup:
    """Records what it was asked, as the real supervisor would be."""
    def __init__(self, running):
        self.running, self.calls = set(running), []
    def running_ids(self):
        return set(self.running)
    def stop(self, child):
        self.calls.append(("stop", child)); self.running.discard(child)
    def start(self, child):
        self.calls.append(("start", child)); self.running.add(child)


_app = _fa.FastAPI()
_app.include_router(_ar.router)
_sup = _Sup({"tiktok_1"})
_app.state.supervisor = _sup
_client = _TC(_app)
_r = _client.post("/api/accounts/slots/tiktok/1", json={"username": "@NewName.TT"})
_new = _cfg / "tiktok-newname.tt-profile"
check("the handle is saved, as TikTok writes it", _r.status_code == 200
      and _ef.read_env().get("TIKTOK_USERNAME_1") == "newname.tt", _r.text[:200])
check("its browser profile moved to the new name, so it is still signed in",
      _new.is_dir() and not _old.exists()
      and (_new / "Default" / "Cookies").read_text(encoding="utf-8") == "the session")
check("  and its cookies file with it", (_cfg / "tiktok-newname.tt-cookies.json").exists()
      and not (_cfg / "tiktok-oldname.tt-cookies.json").exists())
check("it was stopped while the folder moved, and started again after, since it had been running",
      _sup.calls == [("stop", "tiktok_1"), ("start", "tiktok_1")], str(_sup.calls))

# Somewhere it cannot go: a profile already there under the new name is never overwritten.
(_cfg / "tiktok-taken.tt-profile").mkdir(exist_ok=True)
_sup2 = _Sup(set())
_app.state.supervisor = _sup2
_r2 = _client.post("/api/accounts/slots/tiktok/1", json={"username": "taken.tt"})
check("a profile already there under the new name is never overwritten: it says so, and changes nothing",
      _r2.status_code == 409 and _new.is_dir() and _ef.read_env().get("TIKTOK_USERNAME_1") == "newname.tt",
      f"{_r2.status_code} {_r2.text[:160]}")
check("  and an account that was not running is not started by it", ("start", "tiktok_1") not in _sup2.calls)

# The same handle again, or only its case, moves nothing.
_sup3 = _Sup({"tiktok_1"})
_app.state.supervisor = _sup3
_r3 = _client.post("/api/accounts/slots/tiktok/1", json={"username": "NewName.tt"})
check("the same handle written another way is no change, and the account is left running",
      _r3.status_code == 200 and _new.is_dir() and _sup3.calls == [], str(_sup3.calls))

shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
