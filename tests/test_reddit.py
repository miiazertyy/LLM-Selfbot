"""Reddit, the sixth browser platform (2026-11-01).

The persona gets a Reddit account of its own: its chats answered, the replies and u/ mentions in its inbox
answered in the thread they were said in, comments where it was told it may comment, posts of its own, and the
upvotes, saves, joins and follows that make an account look alive. It is driven through reddit.com in its own
Chrome by the shared bridge, as Snapchat, TikTok, Instagram and X are - Reddit's API stopped taking new apps on
31 October 2026 and closes in March 2027, so the page is the only way in.

This file is the wiring: that every table a platform has to be in has Reddit in it, that its prefixes tell
nothing else apart, that every setting reaches the Node runner, that it only ever takes part where it was told
to, and that a login it cannot do by itself is never retried. What reddit.com's own pages look like is
redditbot.js's business and is checked against saved pages of it (tests/reddit_logic.mjs), not here.
"""
import copy
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRC = ROOT / "webui" / "src"
# The config the project ships, in a sandbox: config/ is only made by running the app, so a fresh checkout (CI) has none.
from fixtures import use_shipped_config  # noqa: E402

use_shipped_config()
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def leaves(d, prefix=""):
    """Every setting in a config block, as dotted keys."""
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            yield from leaves(v, key + ".")
        else:
            yield key, v


import yaml  # noqa: E402

CONFIG = yaml.safe_load(read("resources/config.yaml"))

print("== it is one of the socials ==")
from app.utils import socials  # noqa: E402

check("Reddit is in the list", "reddit" in socials.SOCIALS)
check("on until it is switched off", socials.on({})["reddit"] is True)
check("off by either of its two switches",
      socials.on({"reddit": {"enabled": False}})["reddit"] is False
      and socials.on({"services": {"reddit": {"enabled": False}}})["reddit"] is False)
check("the shipped config has both, on", (CONFIG["services"].get("reddit") or {}).get("enabled") is True
      and CONFIG["reddit"]["enabled"] is True)

print("\n== its name tells nothing else apart ==")
from app.core import ipc  # noqa: E402

check("its targets are its name and a number", ipc.platform_of("reddit") == "reddit"
      and ipc.platform_of("reddit2") == "reddit"
      and ipc.reddit_index("reddit") == 1 and ipc.reddit_index("reddit7") == 7)
check("and no other platform's target is read as Reddit",
      [ipc.platform_of(t) for t in ("snap", "tiktok2", "insta", "x", "mc", "imsg", "tg3", 1)]
      == ["snapchat", "tiktok", "instagram", "x", "minecraft", "imessage", "telegram", "discord"])
check("it is a browser platform, so its files live in ipc/", ipc.is_browser("reddit") and ipc.is_bridged("reddit"))
check("its web id goes both ways", ipc.web_id_for("reddit3") == "reddit_3"
      and ipc.target_for("reddit_3") == "reddit3")
check("a target that is not one is still refused",
      not any(ipc._VALID_TARGET.match(s) for s in ("reddit0", "reddit1", "redditx", "../reddit", "reddit1000")))

from app.utils import snappeople  # noqa: E402

check("a person is rd_ and their username, a group chat rdg_ and its room",
      snappeople.platform_of_user("rd_theo-wav") == "reddit"
      and snappeople.platform_of_user("rdg_abc123") == "reddit")
check("a username with an underscore of its own is still a person, not a group",
      snappeople.platform_of_user("rd_g_tom") == "reddit" and snappeople.handle_of("rd_g_tom") == "g_tom")
check("a hyphen in a username is kept, where the other platforms read one back as a dot",
      snappeople.handle_of("rd_theo-wav") == "theo-wav" and snappeople.handle_of("tt_theo-wav") == "theo.wav")
check("a username reads back exactly as it was",
      snappeople.reddit_user(snappeople.reddit_id("u/G_Tom")) == "g_tom")
check("and what Reddit could never call anyone gives nothing",
      snappeople.reddit_id("ab") == "" and snappeople.reddit_id("a" * 21) == ""
      and snappeople.reddit_id("theo.wav") == "")
check("its person id is not its account id, which would collide on a numeric name",
      snappeople.reddit_id("123") == "rd_123" and bool(ipc._WEB_ID.match("reddit_123")))

print("\n== every table a platform has to be in ==")
from app.utils import chatlog, compat, db, personas  # noqa: E402
from app.web.routes import chat_routes, stats_routes  # noqa: E402

check("its own numbering for the chat log", chatlog.REDDIT_BASE == 8000 and chatlog.web_account("reddit", 2) == 8002)
check("and a target reads back to it", chatlog.log_account("reddit2") == 8002)
check("its tables in the database", db.WEB_TABLES["reddit"] == "reddit"
      and "CREATE TABLE IF NOT EXISTS message_log_reddit" in read("app/utils/db.py")
      and "CREATE TABLE IF NOT EXISTS user_stats_reddit" in read("app/utils/db.py")
      and "CREATE TABLE IF NOT EXISTS ignored_users_reddit" in read("app/utils/db.py"))
check("the account column is kept up to date on it", "message_log_reddit" in read("app/utils/db.py").split(
    "def ensure_account_columns")[1][:700])
check("its replies are counted", ("reddit", "message_log_reddit", "chat_id") in stats_routes.LOGS
      and stats_routes._STATS_TABLE["reddit"] == "user_stats_reddit")
check("the chat routes know its prefix and its table",
      chat_routes._WEB_PREFIX["reddit"] == "reddit" and chat_routes._WEB_TABLE["reddit"] == "reddit"
      and chat_routes._web_platform("reddit2") == "reddit" and chat_routes._snap_number("reddit2") == 2
      and chat_routes._web_platform("x2") == "x")
check("the panel may be told it cannot run here", compat.FEATURES["reddit"] == "Reddit")
check("a persona may be given one", bool(personas._WEB_ID.match("reddit_1")))
check("its people are cached under their own folder", snappeople._TABLES["reddit"] == "reddit"
      and snappeople._dir("reddit").name == "reddit_people")
from app.platforms import registry  # noqa: E402
check("and their pictures come from the browser platforms' endpoint, not Snapchat's",
      "reddit" in registry.BRIDGED_BUT_SNAPCHAT
      and "if platform in registry.BRIDGED_BUT_SNAPCHAT:" in read("app/utils/snappeople.py").split("def avatar_url")[1][:600])

print("\n== the bridge serves it ==")
import os  # noqa: E402

os.environ["BRIDGE_PLATFORM"] = "reddit"
from app.platforms import snapchat_bridge as bridge  # noqa: E402

check("there is a row for it", bridge.PLATFORM == "reddit" and bridge.P["key"] == "reddit"
      and bridge.P["env"] == "REDDIT" and bridge.P["runner"] == "reddit_runner.js")
check("and it goes out in public, so the out tab works", bridge.SOCIAL is True)
check("its own accounts are never answered", "automoderator" in bridge.P["system_chats"])
check("any emoji may be a reaction", bridge.P.get("any_reaction") is True)
src = read("app/platforms/snapchat_bridge.py")
check("the runner's files are copied into the data dir, or a build ships a stale one",
      'p.suffix in (".js", ".mjs")' in src.split("def _sync_runner_files")[1][:1600]
      and all((ROOT / "app/platforms/snapchat" / n).is_file()
              for n in ("redditbot.js", "reddit_runner.js", "reddit_login.js", "reddit_probe.js")))
check("it has the pair it goes out with", "from app.utils import redditsocial, redditwatch" in src)
check("the panel's commands reach its runner",
      all(k in bridge._OUT_OPS for k in ("reddit_posts", "reddit_post", "reddit_action", "reddit_out",
                                         "reddit_inbox", "reddit_thread", "reddit_comment", "reddit_subs",
                                         "reddit_follow", "reddit_fetch", "reddit_code")))
check("a post is a title and a body here, not a file with a caption",
      'elif op == "post" and PLATFORM == "reddit":' in src
      and src.index('elif op == "post" and PLATFORM == "reddit":') < src.index('elif op == "post":'))

print("\n== every setting reaches the runner ==")
env = bridge._reddit_env(CONFIG)
keys = [k for k, _ in leaves({"reddit": CONFIG["reddit"]})]
check("there are settings to hand over", len(keys) >= 45, str(len(keys)))
deaf = []
for key, value in leaves({"reddit": CONFIG["reddit"]}):
    if key == "reddit.enabled":
        continue                         # the supervisor's, never the runner's
    other = copy.deepcopy(CONFIG)
    node = other
    for part in key.split(".")[:-1]:
        node = node[part]
    node[key.rsplit(".", 1)[1]] = (not value) if isinstance(value, bool) else (
        value + 7 if isinstance(value, int) else "99-23")
    if bridge._reddit_env(other) == env:
        deaf.append(key)
check("and changing any one of them changes what the runner is told", not deaf, ", ".join(deaf))
check("what is already in the environment wins, since that is where its login is",
      "if k not in os.environ" in src.split("def _reddit_env")[1][:4800])

print("\n== every setting has words on it ==")
from app.web import descriptions, schema  # noqa: E402

in_schema = {r["key"] for r in schema.CONFIG_SCHEMA}
no_words = [k for k in keys if k not in descriptions.DESCRIPTIONS
            or (k not in descriptions.LABELS and k not in in_schema)]
check("a description and a label for each", not no_words, ", ".join(no_words))
wrong_tab = [k for k in keys if descriptions.section_for(k) != "Reddit"]
check("and all of them under one tab", not wrong_tab, ", ".join(wrong_tab))
stale = [k for k in list(descriptions.DESCRIPTIONS) + list(descriptions.LABELS)
         if k.startswith("reddit.") and k not in keys]
check("and nothing described that is not there any more", not stale, ", ".join(sorted(set(stale))))
check("the ones handed over at launch say they need a restart",
      descriptions.needs_restart("reddit.poll_interval_ms") and descriptions.needs_restart("reddit.posting.enabled")
      and descriptions.needs_restart("reddit.subreddits"))
check("both switches are rows people see first",
      "reddit.enabled" in descriptions.COMMON and "services.reddit.enabled" in descriptions.COMMON)

print("\n== it only speaks where it was told to ==")
r = CONFIG["reddit"]
check("it answers its chats and its own inbox out of the box",
      r["enabled"] is True and r["inbox"]["enabled"] is True and r["poll_interval_ms"] >= 5000)
check("but comments and posts nowhere until it is told to",
      r["comments"]["enabled"] is False and r["posting"]["enabled"] is False
      and not any(r["engage"][k] for k in ("upvote_sent", "upvote_theirs", "save", "join_subs", "follow_users")))
check("with no subreddits on its list to begin with", r["subreddits"] == "")
check("and its own profile is where its posts go until somebody changes it",
      r["posting"]["where"] == "profile")
check("nothing public is unbounded", r["engage"]["upvotes_per_day"] <= 50 and r["engage"]["joins_per_day"] <= 10
      and r["posting"]["per_day"] <= 5 and r["comments"]["per_day"] <= 20)
check("it goes no faster than X, which is already the careful one",
      r["min_send_gap_ms"] >= CONFIG["x"]["min_send_gap_ms"]
      and r["max_sends_per_hour"] <= CONFIG["x"]["max_sends_per_hour"])
check("a post of its own comes from what it saw online or what is on its mind",
      set(r["posting"]["from"]) == {"saw_online", "on_its_mind"} and all(r["posting"]["from"].values()))
check("and the check that Reddit is not hiding it is on, because nothing else would say so",
      r["check_shadowban"] is True)

print("\n== what it reads and what it knows of people ==")
from app.utils import redditsocial, redditwatch  # noqa: E402

check("a reddit.com link to a post is spotted, however it was written",
      redditwatch.links("look https://www.reddit.com/r/cooking/comments/1abc2de/my_soup/ "
                        "and https://old.reddit.com/r/pics/comments/zz9/t/")
      == ["https://www.reddit.com/r/cooking/comments/1abc2de",
          "https://old.reddit.com/r/pics/comments/zz9"])
check("the same post sent twice is read once",
      len(redditwatch.links("https://redd.it/1abc2de https://www.reddit.com/r/x/comments/1abc2de/y/")) == 1)
check("and a subreddit or somebody else's site is not a post",
      not redditwatch.links("https://www.reddit.com/r/cooking/")
      and not redditwatch.links("https://example.com/comments/abcd/"))
check("counts read as Reddit writes them, with a small k",
      (redditwatch.count_str(40200), redditwatch.count_str(999), redditwatch.count_str(2_500_000))
      == ("40.2k", "999", "2.5m"))
check("a post read becomes one line for the model, the comments under it included",
      "1.2k upvotes" in redditwatch.summary({"author": "theo", "subreddit": "cooking", "score": 1200,
                                             "title": "soup", "comments_said": [{"author": "a", "text": "nice"}]})
      and redditwatch.summary({}) == "")
check("the subreddits it may take part in are read as a list, however they were typed",
      redditsocial.subreddits({"reddit": {"subreddits": "r/AskReddit, cooking; /r/pics\nbaking"}})
      == ["askreddit", "cooking", "pics", "baking"])
check("nowhere outside that list is allowed, and its own profile always is",
      redditsocial.allowed("cooking", {"reddit": {"subreddits": "cooking"}})
      and not redditsocial.allowed("pics", {"reddit": {"subreddits": "cooking"}})
      and redditsocial.allowed("u_someone", {"reddit": {"subreddits": ""}}))
check("a public answer is tidied: no u/ in front, which Reddit puts there itself",
      redditsocial.clean_reply("u/someone  that is fair") == "that is fair")
check("and a comment of its own loses the sign-off and the hashtags that give a bot away",
      redditsocial.clean_comment("Try salting it first. Hope this helps! #cooking") == "Try salting it first.")
check("but keeps the sentence it was written with",
      redditsocial.clean_comment("Just salt it.") == "Just salt it.")
check("a post of its own is split the way Reddit wants it: a title and a body",
      redditsocial.clean_post("A soup I made\nIt took four hours.") == ("A soup I made", "It took four hours."))
check("and a title too long for Reddit is cut, not refused",
      len(redditsocial.clean_post("x" * 400 + "\nbody")[0]) <= 300)
check("where a post comes from follows the two switches",
      redditsocial.post_source("default") == ("", ""))     # posting is off in the shipped config
check("and Reddit shares nothing the way Instagram shares a reel, which the bridge asks every platform",
      redditsocial.share_settings() is False and redditsocial.wants_reel("send me a reel") is False
      and redditsocial.pools_for("default") == [])
check("what it knows of somebody is its own block, not another platform's",
      "THEIR REDDIT:" in redditsocial.profile_block({"karma": 40200}, "theo-wav"))

print("\n== its login is a window a person signs in ==")
from app.utils import reddit_signin  # noqa: E402
from app.web.routes import account_routes  # noqa: E402

spec = account_routes.PLATFORMS["reddit"]
check("the username, and a password and 2FA key it does not need",
      spec["fields"] == {"username": "REDDIT_USERNAME", "password": "REDDIT_PASSWORD", "totp": "REDDIT_TOTP", "proxy": "REDDIT_PROXY"}
      and spec["required"] == "username")
check("the password and the key are write-only", set(spec["secret"]) == {"password", "totp"})
from app.web.envfile import SECRET_KEYS  # noqa: E402

check("and the store itself keeps them back",
      all(SECRET_KEYS.match(k) for k in ("REDDIT_PASSWORD_1", "REDDIT_TOTP_1"))
      and not SECRET_KEYS.match("REDDIT_USERNAME_1"))
check("a username is cleaned, however it was typed",
      reddit_signin.clean_username("u/Theo-Wav") == "theo-wav"
      and reddit_signin.clean_username("https://www.reddit.com/user/Theo-Wav/") == "theo-wav"
      and reddit_signin.clean_username("theo.wav") == "")
check("its browser profile is named after it, inside the config folder",
      reddit_signin.profile_dir("Theo-Wav").name == "reddit-theo-wav-profile"
      and reddit_signin.profile_dir("../../x").parent == reddit_signin.profile_dir("theo-wav").parent)
check("nothing signing in yet", reddit_signin.status().get("state") in ("idle", None, "")
      and not reddit_signin.running(), str(reddit_signin.status()))
paths = {r.path for r in account_routes.router.routes}
check("the panel opens the window, watches it and can stop it",
      {f"/api/accounts/reddit/browser-login/{p}" for p in ("start", "status", "cancel")} <= paths)
check("and a code goes to a running account's own runner",
      "/api/accounts/reddit/sign-in/code" in paths)
acc = read("app/web/routes/account_routes.py")
check("a renamed account takes its signed-in profile with it",
      "_move_reddit_profile" in acc and "_drop_reddit_profile" in acc
      and '_renumber_web_identity(cfg, "identity_reddit"' in acc)
check("the window is TikTok's machinery, not a fourth copy of it",
      "from app.utils.browser_signin import Flow" in read("app/utils/reddit_signin.py"))
check("and X and Instagram sign in the same way now, rather than typing a password into a page",
      "from app.utils.browser_signin import Flow" in read("app/utils/x_signin.py")
      and "from app.utils.browser_signin import Flow" in read("app/utils/instagram_signin.py"))

print("\n== a login it cannot do by itself is never tried again ==")
from app.web import supervisor  # noqa: E402

from app.platforms import registry  # noqa: E402
sup_src = read("app/web/supervisor.py")
check("Reddit is one of the accounts the supervisor plans", "reddit" in registry.IDS and '"reddit": _count_reddit_accounts' in sup_src
      and 'out[f"{p.id}_{i}"] = (p.id, i, f"{p.name} #{i}")' in sup_src)
check("and it is left stopped when a person is needed, as the others are",
      supervisor.NEEDS_SIGN_IN == 4 and "self._mark_sign_in(child.child_id, True)" in sup_src)
real_dir = None
try:
    from app.utils import paths
    real_dir, paths.DATA_DIR = paths.DATA_DIR, Path(tempfile.mkdtemp())
    s = supervisor.Supervisor(port=0, no_web=True)
    s._mark_sign_in("reddit_1", True)
    check("remembered across a restart of the app", s.needs_sign_in() == {"reddit_1"})
    launched = []
    s._planned_children = lambda: {"reddit_1": ("reddit", 1, "Reddit #1")}
    s._launch = lambda child: launched.append(child.child_id)
    s.start("reddit_1")
    check("and pressing Start is what clears it", s.needs_sign_in() == set() and launched == ["reddit_1"])
finally:
    if real_dir is not None:
        paths.DATA_DIR = real_dir

print("\n== the panel knows it ==")
plat = (SRC / "lib" / "platforms.ts").read_text(encoding="utf-8")
check("it is in the one table the panel reads", 'id: "reddit", name: "Reddit"' in plat and '| "reddit"' in plat)
check("driven through a browser, like the other four",
      re.search(r'id: "reddit",[^}]*browser: true', plat, re.S))
check("its colour is Reddit's own orange", "#ff4500" in plat)
check("a person's id routes to it, groups before people",
      's.startsWith("rd_") || s.startsWith("rdg_")' in plat)
icon = (SRC / "lib" / "components" / "Icon.svelte").read_text(encoding="utf-8")
check("its mark is there and drawn solid",
      "REDDIT_SNOO" in (SRC / "lib" / "brands.ts").read_text(encoding="utf-8") and "reddit: REDDIT_SNOO" in icon)
check("filled solid like the other brand marks, and pulled in as a corner-to-corner one",
      'EVENODD = new Set(["instagram"])' in icon
      and 'reddit: "translate(1.2 1.2) scale(0.9)"' in icon)
check("and it is Simple Icons' own, not one of ours",
      "from Simple Icons (CC0 1.0)" in (SRC / "lib" / "brands.ts").read_text(encoding="utf-8")
      .split("REDDIT_SNOO")[0].rsplit("/**", 1)[-1])
check("a log line of its own is hidden with it",
      "PLATFORM_IDS.join(" in (SRC / "lib" / "socials.ts").read_text(encoding="utf-8")
      and "\n  reddit: {" in (SRC / "lib" / "platforms.ts").read_text(encoding="utf-8"))

smap = (SRC / "lib" / "settingsmap.ts").read_text(encoding="utf-8")
check("it has a Settings tab, whose id is the platform's", 'id: "reddit",\n    name: "Reddit",' in smap)
check("with its install panel", '"reddit-setup"' in smap)
check("and its switches in What runs", '"services.reddit.enabled",' in smap and '"reddit.enabled",' in smap)
tab = smap[smap.index('id: "reddit",\n    name: "Reddit",'):]
tab = tab[:tab.index('{ id: "rest"')]
in_tab = set(re.findall(r'"(reddit\.[a-z_.]+)"', tab))
missed = [k for k in keys if k not in in_tab and k != "reddit.enabled"]
check("every setting has a home in it, so none fall into Everything else", not missed, ", ".join(missed))

settings = (SRC / "pages" / "Settings.svelte").read_text(encoding="utf-8")
check("its two switches are one switch on screen", '"services.reddit.enabled": "reddit.enabled"' in settings)
check("its install panel is the same for every profile", '"reddit-setup"' in settings)
check("and where its posts go is a dropdown of plain words, not a string to type",
      '"reddit.posting.where": [' in settings and '"Its own profile"' in settings)
cond = (SRC / "lib" / "accounts" / "condition.ts").read_text(encoding="utf-8")
check("its card reads the runner's own state, as the browser platforms do",
      'slot.platform !== "discord" && slot.platform !== "snapchat" && rt?.web' in cond)
check("and its signed-in profile is its login, so a username alone is enough to start it",
      'if (s.platform === "reddit") return !!s.username;' in cond)
accounts = (SRC / "pages" / "Accounts.svelte").read_text(encoding="utf-8")
check("it can be added, from all three places that offer it",
      accounts.count('openAdd("reddit")') == 3 and '{ id: "reddit", label: "Reddit"' in accounts)
check("and its dialog is its own colour, not Discord's blue", '.aa[data-platform="reddit"] .aa-hero' in accounts)
check("adding one opens a window rather than asking for a password",
      '"Open Reddit and sign in"' in accounts
      and "reddit: { start: () => api.redditBrowserLoginStart(" in accounts)
check("and so does X's and Instagram's, now that they sign in the same way",
      '"Open X and sign in"' in accounts and '"Open Instagram and sign in"' in accounts)
api = (SRC / "lib" / "api.ts").read_text(encoding="utf-8")
check("the panel can drive the sign-in",
      all(f"redditBrowserLogin{p}" in api for p in ("Start", "Status", "Cancel")))

print("\n== the panel's own view of it ==")
from app.web.routes import reddit_routes, x_routes  # noqa: E402

rd_paths = {r.path for r in reddit_routes.router.routes}
check("its posts, its inbox, a thread, its subreddits and what is left of the day",
      {"/api/reddit/theirs", "/api/reddit/inbox", "/api/reddit/thread", "/api/reddit/subs",
       "/api/reddit/out"} <= rd_paths, str(sorted(rd_paths)))
check("upvoting, commenting, following and posting",
      {"/api/reddit/action", "/api/reddit/comment", "/api/reddit/follow",
       "/api/reddit/post"} <= rd_paths)
check("and X has one at last, which it never did",
      {"/api/x/theirs", "/api/x/mentions", "/api/x/out", "/api/x/action", "/api/x/post"}
      <= {r.path for r in x_routes.router.routes})
server = read("app/web/server.py")
check("both are served", "x_routes" in server and "reddit_routes" in server
      and "app.include_router(reddit_routes.router)" in server)
check("a subreddit it was not told it may use is refused by the server, not only by the loop",
      "redditsocial.allowed(where)" in read("app/web/routes/reddit_routes.py"))

print("\n== a link to one becomes a card ==")
chat_src = read("app/web/routes/chat_routes.py")
check("the panel can ask what a shared post is, on either platform",
      "/api/chats/reddit-card" in chat_src and "/api/chats/x-card" in chat_src)
check("and what it says comes from the account's own signed-in browser, which is the only thing that can read it",
      "redditwatch.cached" in chat_src and "xwatch.cached" in chat_src)
check("the panel finds the links in a message", "export function redditLinks" in plat
      and "export function xLinks" in plat)
body = (SRC / "lib" / "components" / "MessageBody.svelte").read_text(encoding="utf-8")
check("and draws one card for both, under the message",
      'platform="reddit"' in body and 'platform="x"' in body and "PostCard" in body)
check("a post that has a card is not also drawn as a plain grey bar",
      "!redditLinks(e.url).length" in body and "!xLinks(e.url).length" in body)

print("\n== and a picture can be sent to it ==")
pics = (SRC / "pages" / "Pictures.svelte").read_text(encoding="utf-8")
check("Pictures offers both, beside TikTok's and Instagram's",
      '"Post to Reddit…"' in pics and '"Post to X…"' in pics and "PostTo" in pics)
check("neither is offered when that social is switched off",
      "$socialsOn.reddit !== false" in pics and "$socialsOn.x !== false" in pics)

print("\n== the places a platform has to be named ==")
# Every one of these had X missing from it, and would have had Reddit missing too. The ones made from the one table
# (app/platforms/registry.py, webui/src/lib/platforms.ts) cannot miss it any more, and say so instead of its name.
for rel, want in (("webui/src/lib/logrows.ts", "s.match(ACCOUNT_ID)"),
                  ("webui/src/lib/personas/logic.ts", 'reddit: "Reddit"'),
                  ("webui/src/lib/components/StatDetail.svelte", "PLATFORM_IDS.map("),
                  ("webui/src/lib/dashboard/WidgetBody.svelte", 'class:is-reddit={tp.id === "reddit"}'),
                  ("webui/src/pages/Memory.svelte", 'u.platform === "reddit"'),
                  ("app/utils/snappeople.py", '"x", "reddit", "minecraft"'),
                  ("app/telegram_bot/telegram_controller.py", "NUM_REDDIT_ACCOUNTS"),
                  ("app/core/engine.py", "registry.name_of(msg.platform)")):
    check(f"  {rel.rsplit('/', 1)[-1]} names it", want in read(rel), want)
check("a person's card says where they are from, whatever platform that is",
      'person?.platform && person.platform !== "discord"'
      in (SRC / "lib" / "components" / "UserChip.svelte").read_text(encoding="utf-8"))
check("the Dashboard counts every platform's replies, by its own total rather than a list to keep up to date",
      '"_x", "_reddit"' in (SRC / "pages" / "Dashboard.svelte").read_text(encoding="utf-8"))
check("and an X account's crash reaches Telegram, which it never did",
      'targets.append("x" if i == 1 else f"x{i}")' in read("app/telegram_bot/telegram_controller.py"))

print("\n== the runner gives up the two ways it should ==")
# Run for real, with no browser involved: both of these happen before one is opened. Exit 4 is the one that
# matters - the supervisor reads it as "a person has to" and never starts it again by itself, which is what keeps
# an account that cannot sign in from trying every two minutes.
import shutil  # noqa: E402
import subprocess  # noqa: E402

node = shutil.which("node")
# Node looks for its packages beside the script. A source checkout may have them; an installed app keeps them in
# its data folder and runs the runner from there (snapchat_bridge._sync_node_runner), so both are looked in.
from app.utils.paths import DATA_DIR  # noqa: E402

homes = [ROOT / "app/platforms/snapchat", DATA_DIR / "snapchat",
         Path(os.environ.get("APPDATA", "")) / "LLMSelfbot" / "snapchat"]
runner_dir = next((h for h in homes if (h / "node_modules").is_dir() and (h / "reddit_runner.js").exists()), None)
RUNNER = runner_dir / "reddit_runner.js" if runner_dir else None
if not node or not runner_dir:
    print("  SKIP  needs Node and the browser packages")
else:
    def run_runner(extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("REDDIT_")}
        env.update({"REDDIT_DATA_DIR": tmp_dir, "SNAP_DATA_DIR": tmp_dir, "REDDIT_ACCOUNT_INDEX": "1", **extra})
        p = subprocess.run([node, str(RUNNER)], env=env, cwd=str(runner_dir), capture_output=True, text=True,
                           timeout=180, encoding="utf-8", errors="replace")
        return p.returncode, p.stdout + p.stderr

    with tempfile.TemporaryDirectory() as tmp_dir:
        code, said = run_runner({})
        check("with no account at all it says so and stops", code == 1
              and "add one on the accounts page" in said.lower(), f"exit {code}: {said[-200:]}")
    with tempfile.TemporaryDirectory() as tmp_dir:
        code, said = run_runner({"REDDIT_USERNAME_1": "someone"})
        state = {}
        f = Path(tmp_dir) / "ipc" / "reddit_state.json"
        if f.exists():
            import json
            state = json.loads(f.read_text(encoding="utf-8"))
        check("with no signed-in profile it asks for a person, and exits 4 rather than trying", code == 4,
              f"exit {code}: {said[-200:]}")
        check("and the card says what to do", state.get("state") == "needs-you"
              and "signed in" in (state.get("detail") or ""), str(state))
        made = sorted(p.name for p in (Path(tmp_dir) / "ipc").glob("reddit_*"))
        check("with all its files made, so the bridge finds them",
              {"reddit_incoming.json", "reddit_responses.json", "reddit_outgoing.json",
               "reddit_state.json"} <= set(made), str(made))

print("\n== the page itself, read for real ==")
# redditbot.js's selectors can only be right or wrong against a page, so they are run against saved copies of
# Reddit's (tests/fixtures/reddit_*.html) in a headless Chrome. With no Reddit account yet, this is what stands in
# for one - including a real shadow root, because Reddit keeps its buttons in them.
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "reddit_logic.mjs")], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
    print("\n".join("  " + line for line in proc.stdout.strip().splitlines()[-4:]))
    check("reddit_logic.mjs passes", proc.returncode == 0, (proc.stdout + proc.stderr)[-700:])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
