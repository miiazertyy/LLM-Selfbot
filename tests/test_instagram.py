"""Instagram, the fourth platform: driven through instagram.com in the account's own Chrome, as TikTok is.

Run for real, in a throwaway data folder: the plumbing (IPC targets, web ids, the chat log's numbers, people's ids,
its database tables, what the supervisor starts), its account slot (the password and the 2FA key write-only), the
sign-in helper, the bridge as Instagram's, the settings, and a shared reel's card.

Read from the source: the runner and its bot (the selectors, the sign-in, the dry run, the probe that never dumps
text) and the UI (the platform table, the Accounts form, Chats, Settings, the Pictures page). And
instagram_logic.mjs runs the runner's pure parts under Node.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="llmbot_insta_"))
(DATA / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
for k in list(os.environ):
    if k.startswith(("INSTAGRAM_", "TIKTOK_USERNAME_", "SNAP_USERNAME", "DISCORD_TOKEN")):
        del os.environ[k]
os.environ["INSTAGRAM_USERNAME_1"] = "theo.wav"
os.environ["INSTAGRAM_PASSWORD_1"] = "x" * 12
os.environ["INSTAGRAM_USERNAME_2"] = "mara_k"
os.environ["INSTAGRAM_PASSWORD_2"] = "y" * 12

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

check("its accounts are counted from .env", ipc._count_instagram_accounts() == 2)
check("its targets are insta, insta2 ...", ipc.validate_target("insta") == "insta"
      and ipc.validate_target("insta2") == "insta2")
check("and nothing else that looks like one",
      all(refused(ipc.validate_target, t) for t in ("insta1", "insta0", "instax", "../insta")))
check("a target and a web id are each other's", ipc.target_for("instagram_1") == "insta"
      and ipc.target_for("instagram_2") == "insta2" and ipc.web_id_for("insta2") == "instagram_2")
check("told apart from the others", ipc.is_instagram("insta2") and not ipc.is_instagram("snap")
      and not ipc.is_instagram("tiktok") and ipc.platform_of("insta") == "instagram"
      and ipc.platform_of("tiktok") == "tiktok" and ipc.platform_of("snap2") == "snapchat"
      and ipc.platform_of(3) == "discord")
check("a browser account, with its commands beside the bridge's files", ipc.is_browser("insta")
      and ipc.cmd_file("insta2").parent == ipc.cmd_file("snap").parent)
check("discovered with the rest", {"instagram_1", "instagram_2"} <= set(ipc.discover_targets()))

from app.utils import chatlog, snappeople  # noqa: E402

check("its chat log has numbers of its own", chatlog.log_account("insta") == 3001
      and chatlog.log_account("insta2") == 3002 and chatlog.web_account("instagram", 1) == 3001)
check("which are nobody else's", len({chatlog.log_account(t) for t in ("snap", "tiktok", "insta")}) == 3)
check("a person's id is ig_ and their username, and reads back", snappeople.instagram_id("@Theo.Wav") == "ig_theo-wav"
      and snappeople.instagram_username("ig_theo-wav") == "theo.wav" and snappeople.handle_of("ig_theo-wav") == "theo.wav")
check("which platform someone is on, by their id", snappeople.platform_of_user("ig_theo-wav") == "instagram"
      and snappeople.platform_of_user("igg_404") == "instagram"
      and snappeople.platform_of_user("tt_theo-wav") == "tiktok"
      and snappeople.platform_of_user("1234") == "discord" and snappeople.platform_of_user("abc-1") == "snapchat")

from app.utils import db  # noqa: E402

db.init_db()
db.record_user_message_web("instagram", "ig_theo-wav", "Theo", account=1)
db.record_user_message_web("instagram", "ig_theo-wav", "Theo", account=1)
db.add_ignored_user_web("instagram", "ig_spam-bot")
board = db.get_leaderboard_web("instagram")
check("its own leaderboard", board and str(board[0][0] if isinstance(board[0], (list, tuple))
                                            else board[0].get("user_id")) == "ig_theo-wav", str(board))
check("and its own ignore list, apart from the others", "ig_spam-bot" in db.get_ignored_users_web("instagram")
      and "ig_spam-bot" not in db.get_ignored_users_web("tiktok")
      and "ig_spam-bot" not in db.get_ignored_users_snap())
check("its tables are its own", db.WEB_TABLES["instagram"] == "instagram")

print("\n== what runs ==")
from app.web.supervisor import Supervisor  # noqa: E402

plan = Supervisor._planned_children(None)
check("each Instagram account runs", plan.get("instagram_1", (None,))[0] == "instagram"
      and "instagram_2" in plan, str(sorted(plan)))
os.environ["LLMSELFBOT_DEVICE"] = "android"
try:
    phone = Supervisor._planned_children(None)
finally:
    del os.environ["LLMSELFBOT_DEVICE"]
check("but not on a phone, which has no Chrome to drive", not any(k.startswith("instagram") for k in phone),
      str(sorted(phone)))
from app.utils import compat  # noqa: E402

check("a phone says why", (compat.check("instagram", "android") or {}).get("why") == "Instagram needs a computer.")
check("ARM Linux needs Chromium, as the others do",
      ((compat.check("instagram", "linux-arm64") or {}).get("fix") or {}).get("command") == "sudo apt install chromium"
      or compat._chromium())
from app.utils import logger  # noqa: E402

logger.set_theme("instagram")
check("its own colours in the console", "instagram" in logger._THEMES)
from app.utils import personas  # noqa: E402

check("an account can be given a persona", bool(personas._WEB_ID.match("instagram_2")))

# ── Settings ─────────────────────────────────────────────────────────────────
print("\n== settings ==")
from app.web.schema import CONFIG_SCHEMA  # noqa: E402
from app.web import descriptions as desc  # noqa: E402

keys = {f["key"] for f in CONFIG_SCHEMA}
for k in ("instagram.enabled", "instagram.min_send_gap_ms", "instagram.max_sends_per_hour",
          "instagram.accept_message_requests", "instagram.follow_back", "instagram.accept_follow_requests",
          "instagram.stories.watch", "instagram.stories.post", "instagram.reels.enabled",
          "instagram.comments.enabled", "instagram.notes.enabled", "instagram.share.enabled",
          "instagram.watch.enabled", "instagram.posting.enabled"):
    check(f"{k} is a setting, described in one line", k in keys and 0 < len(desc.DESCRIPTIONS.get(k, "")) <= 120,
          desc.DESCRIPTIONS.get(k, "missing"))
check("every description is one plain line", all("\n" not in desc.DESCRIPTIONS[k]
                                                 for k in desc.DESCRIPTIONS if k.startswith("instagram.")))
cfg = read("resources/config.yaml")
check("its own section", "\ninstagram:\n" in cfg and "services:\n" in cfg and "  instagram:\n    enabled: true" in cfg)
check("slower than TikTok by default: 20 an hour, 20 to 60 seconds apart",
      "max_sends_per_hour: 20" in cfg.split("\ninstagram:")[1] and "min_send_gap_ms: 20000" in cfg
      and "max_send_gap_ms: 60000" in cfg)
check("everything public is off until switched on", all(
    f"{k}: false" in cfg.split("\ninstagram:")[1] for k in
    ("accept_message_requests", "follow_back", "accept_follow_requests", "reply", "post", "like_sent", "like_theirs")))
import yaml  # noqa: E402

ig_cfg = yaml.safe_load(cfg)["instagram"]
check("the pieces it needs are all there", all(k in ig_cfg for k in
      ("watch", "stories", "reels", "engage", "comments", "notes", "share", "posting")), str(sorted(ig_cfg)))
check("stories are watched but not answered until asked for",
      ig_cfg["stories"]["watch"] is True and ig_cfg["stories"]["reply"] is False
      and ig_cfg["stories"]["post"] is False)
check("the settings tree gives it a tab of its own", 'id: "instagram",' in read("webui/src/lib/settingsmap.ts")
      and 'owns: ["instagram"],' in read("webui/src/lib/settingsmap.ts"))
check("with its install panel, as TikTok has", 'panel: "instagram-setup"' in read("webui/src/lib/settingsmap.ts")
      and '<SnapchatSetup platform="instagram" />' in read("webui/src/pages/Settings.svelte"))

BRIDGE_ONLY_ITS_OWN = 'cmd.startswith(f"{P[\'key\']}_")'

# ── The bridge, as Instagram's ───────────────────────────────────────────────
print("\n== the bridge, as Instagram's ==")
os.environ["BRIDGE_PLATFORM"] = "instagram"
os.environ["INSTAGRAM_ACCOUNT_INDEX"] = "2"
from app.platforms import snapchat_bridge as b  # noqa: E402

check("it says Instagram", b.PLATFORM == "instagram" and b.PLATFORM_NAME == "Instagram")
check("its files are its own, numbered", b.INCOMING_FILE.name == "insta_incoming_2.json"
      and b.CMD_FILE.name == "tg_commands_insta2.json" and b.LOG_ACCOUNT == 3002)
check("it runs its own runner", b.P["runner"] == "instagram_runner.js")
check("it goes out, as TikTok does", b.SOCIAL is True)
check("its system chats are never answered", {"instagram", "meta ai"} <= b.P["system_chats"])
check("the six at a glance, and any emoji behind them", b.SNAP_REACTIONS[0] == "❤️"
      and len(b.SNAP_REACTIONS) == 6 and b.P.get("any_reaction") is True)
check("it watches and talks with its own modules", [m.__name__.split(".")[-1] for m in b._social()]
      == ["instagramwatch", "instagramsocial"])
env = b._instagram_env({"instagram": {"headless": True, "max_sends_per_hour": 12,
                                      "watch": {"enabled": True, "their_posts": False, "voice_notes": True},
                                      "stories": {"watch": True, "reply": True, "replies_per_day": 2},
                                      "reels": {"enabled": True, "like_percent": 20},
                                      "engage": {"like_sent": True, "likes_per_day": 9},
                                      "comments": {"enabled": True, "per_hour": 5},
                                      "notes": {"enabled": True, "every_hours": 6},
                                      "posting": {"per_day": 2}},
                       "bot": {"locale": "fr-FR", "trigger": "Alicia", "night_invisible": {"hours": "2-8"},
                               "friend_requests": {"accept_delay_min": 60, "accept_delay_max": 600}}})
check("the runner is told every setting", {k: env.get(k) for k in (
    "INSTAGRAM_HEADLESS", "INSTAGRAM_MAX_SENDS_PER_HOUR", "INSTAGRAM_WATCH", "INSTAGRAM_THEIR_POSTS",
    "INSTAGRAM_VOICE_NOTES", "INSTAGRAM_STORIES_WATCH", "INSTAGRAM_STORIES_REPLY",
    "INSTAGRAM_STORY_REPLIES_PER_DAY", "INSTAGRAM_REELS", "INSTAGRAM_REELS_LIKE_PERCENT", "INSTAGRAM_LIKE_SENT",
    "INSTAGRAM_LIKES_PER_DAY", "INSTAGRAM_COMMENTS", "INSTAGRAM_COMMENTS_PER_HOUR", "INSTAGRAM_NOTES",
    "INSTAGRAM_NOTES_HOURS", "INSTAGRAM_POSTS_PER_DAY")} == {
    "INSTAGRAM_HEADLESS": "true", "INSTAGRAM_MAX_SENDS_PER_HOUR": "12", "INSTAGRAM_WATCH": "true",
    "INSTAGRAM_THEIR_POSTS": "false", "INSTAGRAM_VOICE_NOTES": "true", "INSTAGRAM_STORIES_WATCH": "true",
    "INSTAGRAM_STORIES_REPLY": "true", "INSTAGRAM_STORY_REPLIES_PER_DAY": "2", "INSTAGRAM_REELS": "true",
    "INSTAGRAM_REELS_LIKE_PERCENT": "20", "INSTAGRAM_LIKE_SENT": "true", "INSTAGRAM_LIKES_PER_DAY": "9",
    "INSTAGRAM_COMMENTS": "true", "INSTAGRAM_COMMENTS_PER_HOUR": "5", "INSTAGRAM_NOTES": "true",
    "INSTAGRAM_NOTES_HOURS": "6", "INSTAGRAM_POSTS_PER_DAY": "2"}, str(env))
check("the persona's language, name and nights", env.get("INSTAGRAM_LOCALE") == "fr-FR"
      and env.get("INSTAGRAM_TRIGGER") == "Alicia" and env.get("INSTAGRAM_NIGHT_HOURS") == "2-8")
check("requests wait as friend requests do", env.get("INSTAGRAM_ACCEPT_DELAY_MIN") == "60"
      and env.get("INSTAGRAM_ACCEPT_DELAY_MAX") == "600")
check("the login itself is never mapped from settings", not any("PASSWORD" in k or "TOTP" in k for k in env))
check("the panel's asks are the runner's ops", {k: v[0] for k, v in b._OUT_OPS.items() if k.startswith("insta_")} == {
    "insta_posts": "posts", "insta_stories": "stories", "insta_action": "media", "insta_story": "story",
    "insta_reels": "reels", "insta_out": "out", "insta_post": "post", "insta_note": "note", "insta_code": "code",
    "insta_fetch": "fetch", "insta_follow": "follow"}, str(sorted(b._OUT_OPS)))
check("and a TikTok ask on an Instagram account is refused rather than guessed at",
      BRIDGE_ONLY_ITS_OWN in read("app/platforms/snapchat_bridge.py"))
# Every script in the folder is, so a new one cannot be left out (tests/test_platform_registry.py runs the copy).
check("every runner file is mirrored to where Node runs it",
      'p.suffix in (".js", ".mjs")' in read("app/platforms/snapchat_bridge.py")
      and all((ROOT / "app/platforms/snapchat" / n).is_file() for n in
              ("instagrambot.js", "instagram_runner.js", "instagram_login.js", "instagram_probe.js")))

# ── Its login, and signing in ────────────────────────────────────────────────
print("\n== its login ==")
from app.utils import instagram_signin as login  # noqa: E402

check("a username as Instagram allows it", login.clean_username("@Theo.Wav") == "theo.wav"
      and login.clean_username("mara_k") == "mara_k" and login.clean_username("a" * 30) == "a" * 30)
check("anything else is none", all(login.clean_username(u) == "" for u in
      ("../x", "a/b", "a" * 31, ".theo", "theo.", "theo wav", "")))
check("a 2FA key as Instagram shows it, without its spaces",
      login.clean_totp("G54M E4E3 T37W 6IXH") == "G54ME4E3T37W6IXH"
      and login.clean_totp("g54me4e3t37w6ixh") == "G54ME4E3T37W6IXH")
check("and nothing that could not be one", all(login.clean_totp(k) == "" for k in ("nope1", "SHORT", "A" * 65, "0189")))
check("no key at all is fine: an account without 2FA", login.clean_totp("") == "" and login.clean_totp(None) == "")
check("its profile is named by its username, inside the config folder",
      login.profile_dir("Theo.Wav").name == "instagram-theo.wav-profile"
      and login.profile_dir("../../x").parent == login.profile_dir("theo.wav").parent)
check("nothing signing in yet", login.status().get("state") in ("idle", None, "") and not login.running(),
      str(login.status()))
check("a code handed over when nothing is waiting says so", login.give_code("123456").get("ok") is False)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import account_routes, chat_routes  # noqa: E402

app = FastAPI()
app.include_router(account_routes.router)
app.include_router(chat_routes.router)
client = TestClient(app)
st = client.get("/api/accounts/instagram/sign-in/status")
check("the panel asks where a sign-in has got to", st.status_code == 200 and "state" in st.json(), st.text[:200])
r = client.post("/api/accounts/slots/instagram", json={"username": "../../evil", "password": "x"})
check("a slot must be an Instagram username", r.status_code == 400, r.text[:200])
r = client.post("/api/accounts/slots/instagram", json={"username": "kit.films", "password": "x", "totp": "nope"})
check("and a 2FA key Instagram could have given", r.status_code == 400, r.text[:200])
r = client.post("/api/accounts/slots/instagram",
                json={"username": "@Kit.Films", "password": "secret-pw", "totp": "G54M E4E3 T37W 6IXH"})
slots = [s for s in (r.json().get("slots") or []) if s.get("platform") == "instagram"] if r.status_code == 200 else []
mine = [s for s in slots if s.get("username") == "kit.films"]
check("stored as Instagram writes it", r.status_code == 200 and bool(mine), r.text[:300])
check("its password and its key never come back, only that they are set",
      bool(mine) and mine[0].get("password_set") is True and mine[0].get("totp_set") is True
      and "password" not in mine[0] and "totp" not in mine[0], str(mine[:1]))
env_now = account_routes.read_env()
at = (mine[0].get("index") if mine else 0) or r.json().get("index")
check("they are in config/.env, write-only", env_now.get(f"INSTAGRAM_PASSWORD_{at}") == "secret-pw"
      and env_now.get(f"INSTAGRAM_TOTP_{at}") == "G54ME4E3T37W6IXH",
      str(sorted(k for k in env_now if "INSTAGRAM" in k)))
check("a code typed with nothing waiting and no account is turned down",
      client.post("/api/accounts/instagram/sign-in/code", json={"code": "abc"}).status_code == 400)
check("its browser profile goes when the account does",
      "_drop_instagram_profile" in read("app/web/routes/account_routes.py"))
check("the env editor lists the slot, its secrets marked",
      '"prefix": "INSTAGRAM_USERNAME"' in read("app/web/routes/env_routes.py")
      and '"prefix": "INSTAGRAM_PASSWORD", "label": "Password", "secret": True' in read("app/web/routes/env_routes.py")
      and '"prefix": "INSTAGRAM_TOTP", "label": "2FA key", "secret": True' in read("app/web/routes/env_routes.py"))


# ── What it does in a chat ───────────────────────────────────────────────────
print("\n== what it does in a chat ==")
bot_js = read("app/platforms/snapchat/instagrambot.js")
run_js = read("app/platforms/snapchat/instagram_runner.js")

check("it reads and acts on the page, never a private API",
      "api/v1/users/web_profile_info" in bot_js and "x-ig-app-id" in bot_js
      and "instagram.com/api/v1/direct" not in bot_js)
check("every marker is in one table, with fallbacks", bot_js.count("export const SEL = {") == 1
      and bot_js.count("'a[href^=\"/direct/t/\"]'") >= 1 and "selectorHealth" in bot_js)
check("a conversation is its thread, which is the one thing the page cannot do without",
      "threadIdFromHref" in bot_js and "/direct/t/${thread}" in bot_js)
for what in ("clip", "voice", "viewonce", "sticker", "heart", "storyreply", "unsent"):
    check(f"a {what} message is told apart", f'kind = "{what}"' in bot_js)
check("a photo is told from a GIF", '? "gif" : "photo"' in bot_js)
check("and a shared reel, post or story from each other",
      '? "story" : /\\/(reel|reels)\\//.test(shared.url) ? "reel" : "post"' in bot_js)
check("a reaction, an edit and what a message answers are noticed",
      "reactionShown" in bot_js and "edited:" in bot_js and "quote:" in bot_js)
check("whose it is in a group, by their own link", "author: mine ? \"\" : author" in bot_js)
for able in ("sendText", "sendImage", "sendVoice", "startReply", "react", "unsend", "editMessage"):
    check(f"it can {able}", f"async {able}(" in bot_js)
check("any emoji as a reaction, through the picker's own search", "emojiSearch" in bot_js)
check("where the site has no edit, it says so rather than going quiet",
      "has no Edit on a message" in bot_js
      and "Forward, Copy, Translate, Pin and Unsend" in bot_js)
check("one message is its bubble's own row, since none of Instagram's row markers match",
      'div[role="article"]' in bot_js and "one.parentElement || one" in bot_js
      and "with it went reactions, replies, unsending and editing" in bot_js)
check("the buttons beside the box are reached through the icon that carries the label",
      'div[role="button"]:has(svg[aria-label*="Add Photo" i])' in bot_js
      and 'div[role="button"]:has(svg[aria-label*="Voice" i])' in bot_js)
check("a reel's link keeps its closing slash, so an audio page is not taken for a reel",
      '\'a[href^="/reel/"]\'' in bot_js and "/reels/audio/<code>/" in bot_js
      and "audio|explore|direct|stories|accounts" in bot_js)
check("what people send is understood, each kind said plainly",
      all(s in run_js for s in ("[shared a reel", "[shared a post", "[shared a story", "[tapped the heart",
                                "[sent a photo that can only be looked at once", "[answering your story")))
check("a photo is seen, a video watched, a voice note transcribed",
      "capturePhoto" in run_js and "captureVideo" in run_js and "captureVoice" in run_js)
check("a call shows on the Chats tab and is never answered",
      'kind: "call"' in run_js and "answerCall" not in bot_js and "acceptCall" not in bot_js)
check("a group is answered only when it is named", "TRIGGER" in run_js and "row.group" in run_js)
check("its dry run types and sends nothing", "INSTAGRAM_DRY_RUN" in read("app/platforms/snapchat_bridge.py")
      or 'core.flag("DRY_RUN", false)' in run_js)
check("and says so on every send", run_js.count("dryRun: DRY_RUN") >= 6)

print("\n== stories, reels and the rest ==")
for able in ("watchStories", "replyToStory", "postStory", "reels", "reelLike", "profilePosts", "readComments",
             "replyToComment", "commentOnPost", "postMedia", "setNote", "setActivityStatus",
             "acceptFollowRequests", "followBack", "messageRequests", "answerRequest", "captureMedia"):
    check(f"it can {able}", f"async {able}(" in bot_js)
check("a story is watched at a person's pace, and they see it as seen",
      "Watched the way a person watches" in bot_js and "stories/${u}/" in bot_js)
check("a story goes up through the phone site, the only one that takes one",
      "phonePage" in bot_js and "iPhone" in bot_js)
check("and says plainly when neither site will", "will not put up a story" in bot_js)
check("its Note comes from its mood", "_write_note" in read("app/platforms/snapchat_bridge.py")
      and "note_context" in read("app/utils/instagramsocial.py"))
check("and the note sheet is found by the sheet it is in, which it says nothing in",
      'div[role="dialog"] textarea' in bot_js and "does not say \"note\" anywhere in its box" in bot_js
      and "async onlyTextBox(" in bot_js and "await this.onlyTextBox(page)" in bot_js)
check("a voice note is played in through a fake microphone",
      "use-file-for-fake-audio-capture" in run_js and "silentWav" in run_js)
check("what it saw on Reels can come up in a DM", "seen_video" in run_js
      and "seen_block" in read("app/utils/instagramsocial.py"))
check("the day's likes, comments, stories and posts are counted",
      all(k in run_js for k in ("createBudget", "likes:", "comments:", "stories:", "story_replies:")))

print("\n== signing itself in ==")
check("the runner signs itself in with what .env holds", "signInNow" in run_js and "INSTAGRAM_PASSWORD_" in run_js)
check("the six digits are made from the key, never stored anywhere else",
      "totpKey: TOTP_KEY" in run_js and "export function totp(" in bot_js)
check("a code from its email puts it in needs-you, with a field in the panel",
      'needs-you' in run_js and 'kind: "attention", what: "code"' in run_js
      and '"insta_code"' in read("app/web/routes/account_routes.py"))
check("a suspended account says so instead of trying forever", "suspended" in run_js and "has suspended" in bot_js)
check("a hidden window that stops reading comes back rather than going quiet",
      "so its window is on screen to be looked at" in run_js and "HIDDEN && !windowUp" in run_js
      and "Hiding is not the suspect here" in run_js)
browser_js = read("app/platforms/snapchat/browser.js")
check("and hidden means off the screen and out of the taskbar, not merely off the screen",
      "const OFF_SCREEN = [-2400, 60];" in browser_js and "WS_EX_TOOLWINDOW" in browser_js
      and "hideFromTaskbar(browser)" in browser_js)
check("a hidden window is never hidden outright, which stops Chrome drawing it",
      "paints no frames at all" in browser_js and "SW_HIDE" in browser_js)
check("bringing it back puts it in the taskbar first, and hiding it takes it out again",
      "windowInTaskbar(page.browser(), true)" in browser_js
      and "await hideFromTaskbar(page.browser(), 2)" in browser_js)
check("and a machine where none of that can run still runs the account",
      "it is off the screen only" in browser_js and 'process.platform !== "win32"' in browser_js)
check("a row's display name never becomes a person: Instagram gives its rows no id",
      "function chatOfName(" in run_js and "were never anybody" in run_js
      and "const id = r.id ? (chatOfThread(r.id) || `igg_${r.id}`) : chatOfName(r.name);" in run_js
      and "cleanUsername(r.name)" not in run_js)
check("whose conversation it is comes from the profile link in it, else from the thread",
      "const username = cleanUsername(chat.username);" in run_js
      and "neither has a conversation that would not say" in run_js)
check("and the people an older build invented are forgotten once, picture and all",
      "function dropInvented(" in run_js and "dropInvented();" in run_js
      and "chatIdFor(cleanUsername(c.name)) !== id" in run_js
      and "c.thread || c.wrote || c.profiled" in run_js
      and "fs.unlinkSync(path.join(PEOPLE_DIR, c.file))" in run_js)
check("message requests skip Instagram's own way into the hidden ones",
      "async requestRows(" in bot_js and "hidden requests|requests|general|primary" in bot_js)
check("and one is answered by the name it shows, there being no id on its row",
      "async answerRequest(want, accept)" in bot_js and "Block, Delete, Accept" in bot_js)
check("a captcha brings the window back for a person", "waitForPerson" in run_js and "captchaShown" in bot_js)
check("the window is hidden again once they are done", "hideIfHidden" in run_js)
check("the probe never prints a message, a name or a picture",
      "sanitized" in read("app/platforms/snapchat/instagram_probe.js")
      and 'replace(/\\S/g, "x")' in read("app/platforms/snapchat/instagram_probe.js"))

# ── The panel ────────────────────────────────────────────────────────────────
print("\n== the panel ==")
plat = read("webui/src/lib/platforms.ts")
check("the platform table has it", 'id: "instagram", name: "Instagram"' in plat
      and 'tone: "#e1306c"' in plat and "browser: true" in plat)
check("message requests, Follow, followers, calls, groups", 'requests: "Message requests"' in plat
      and 'add: "Follow"' in plat and 'people: "follower"' in plat)
check("its six reactions, and any emoji behind them", "anyReaction: true" in plat
      and '"❤️", "\U0001f602", "\U0001f62e"' in plat)
check("an account and a person are both placed by their id", 'if (s.startsWith("insta")) return PLATFORMS.instagram' in plat
      and 'if (s.startsWith("ig_") || s.startsWith("igg_")) return PLATFORMS.instagram' in plat)
check("a link in a message gets a card", "instagramLinks" in plat
      and "InstagramCard" in read("webui/src/lib/components/MessageBody.svelte"))
check("its mark is its own camera, in its gradient", "INSTAGRAM_MARK" in read("webui/src/lib/brands.ts")
      and "instagram: INSTAGRAM_MARK," in read("webui/src/lib/components/Icon.svelte")
      and 'EVENODD = new Set(["instagram"])' in read("webui/src/lib/components/Icon.svelte"))
acc = read("webui/src/pages/Accounts.svelte")
check("it is added with a username, a password and a 2FA key", 'openAdd("instagram")' in acc
      and 'id="ig-usr"' in acc and 'id="ig-pwd"' in acc and 'id="ig-totp"' in acc)
check("the key's own six digits are shown, to check it against your app",
      "igShown" in acc and "igLeft" in acc and "should match your authenticator app" in acc
      and "export async function totp(" in read("webui/src/lib/totp.ts"))
check("and a field for the code Instagram sends", 'id="ig-code"' in acc and "sendInstagramCode" in acc)
card = read("webui/src/lib/accounts/condition.ts")
check("the card says what it is doing: signing in, a code, a check, logged out",
      'own.state === "logging-in"' in card and 'code ? "Code needed" : "Check to solve"' in card
      and 'own.state === "logged-out"' in card and 'label: "Logged out"' in card)
check("and when Instagram changed its page", "changed its page" in card)
chats = read("webui/src/pages/Chats.svelte")
check("their stories and posts sit beside the conversation", "instaPerson" in chats
      and 'toolsTab === "posts"' in chats and "TheirPosts" in read("webui/src/lib/components/ChatTools.svelte"))
check("someone can be followed from there", 'plat.add === "Follow"' in chats)
check("its pictures can go up as a post, a reel or a story",
      "PostInstagram" in read("webui/src/pages/Pictures.svelte")
      and "Post to Instagram" in read("webui/src/pages/Pictures.svelte"))
for f in ("InstagramCard.svelte", "TheirPosts.svelte", "PostInstagram.svelte"):
    src = read(f"webui/src/lib/components/{f}")
    check(f"{f} plays its sounds and follows the Animations switch",
          'from "../uisound"' in src and 'data-motion="off"' in src)

# ── What the real page turned out to be (read off it, 2026-10) ──────────────
print("\n== read off the real page ==")
check("the conversation list is found by Instagram's own words for it",
      '\'[aria-label="Thread list"]\'' in bot_js and "threadRow:" in bot_js)
check("its rows are buttons with no link and no id, told apart by their shape",
      "r.width > 200 && r.height > 40 && r.height < 130" in bot_js
      and "Instagram's own inbox gives its rows no link and no id" in bot_js)
check("so a row is opened where it sits, and says which conversation it was",
      "async openRow(" in bot_js and "Instagram puts the id in the address once the conversation is open" in bot_js
      and "const thread = await bot.openRow(row);" in run_js)
check("the box to type in is its Lexical editor", "div[role=\"textbox\"][data-lexical-editor=\"true\"]" in bot_js)
check("the conversation is drawn in a pane it marks as an article", "pane: ['div[role=\"article\"]'" in bot_js)
check("the day over a run of messages is worked out the same way as the others",
      'import { atOfLabel } from "./runner_core.js";' in bot_js)
check("a voice note goes through the file box, which takes sound as well as pictures",
      "audioInput:" in bot_js and 'accept*="audio"' in bot_js
      and "Its file box takes sound as well as pictures" in bot_js)
check("it starts at its own pace even on a settings file written before it existed",
      "MIN_SEND_GAP_MS: 20000" in run_js and "MAX_SENDS_PER_HOUR: 20" in run_js
      and "defaults = {} }" in read("app/platforms/snapchat/runner_core.js"))
check("an empty inbox is not a changed page", 'const names = ["threadList"];' in bot_js
      and "that is not Instagram changing its page" in bot_js)
check("its two-step page is the one it really is", "two_(factor|step)" in bot_js)
check("and its code box is found even with no name, no label and no autocomplete",
      "async codeBox(" in bot_js and "boxes.length === 1 ? boxes[0] : null" in bot_js)
check("the device is trusted once, so it is not asked every time", "async trustDevice(" in bot_js)
check("a profile reads off the page when Instagram throttles its own endpoint",
      "async profileFromPage(" in bot_js and "Instagram throttles that endpoint" in bot_js
      and "Followers?," in bot_js)
check("and who it is signed in as comes from the page, which is never throttled",
      "profile picture/i.test" in bot_js and "nothing to be throttled" in bot_js)

# ── Its own logic, under Node ────────────────────────────────────────────────
print("\n== instagram_logic.mjs ==")
node = shutil.which("node")
if not node:
    check("Node is here to run it", False, "install Node.js to run the runner's own checks")
else:
    out = subprocess.run([node, str(ROOT / "tests" / "instagram_logic.mjs")], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", cwd=str(ROOT))
    for line in (out.stdout or "").splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    said = (out.stdout or "").strip().splitlines()[-1] if (out.stdout or "").strip() else ""
    check("instagram_logic.mjs passes", out.returncode == 0 and "0 failed" in said,
          (said or (out.stderr or "")[-300:]))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + ", ".join(FAIL))
shutil.rmtree(DATA, ignore_errors=True)
sys.exit(1 if FAIL else 0)
