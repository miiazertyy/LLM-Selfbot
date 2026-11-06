"""X (Twitter), the fifth platform (2026-11-01).

The persona gets an X account of its own: its messages answered, the people who reply to it or @ it answered in the
thread, posts of its own, and the likes, reposts and follows that make an account look alive. It is driven through
x.com in its own Chrome by the shared bridge, as Snapchat, TikTok and Instagram are.

This file is the wiring: that every table a platform has to be in has X in it, that the one-letter prefix tells
nothing else apart, that every setting reaches the Node runner, and that a refused login is never retried. What
x.com's own pages look like is xbot.js's business and is checked against saved pages of it, not here.
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

check("X is in the list", "x" in socials.SOCIALS)
check("on until it is switched off", socials.on({})["x"] is True)
check("off by either of its two switches",
      socials.on({"x": {"enabled": False}})["x"] is False
      and socials.on({"services": {"x": {"enabled": False}}})["x"] is False)
check("the shipped config has both, on", (CONFIG["services"].get("x") or {}).get("enabled") is True
      and CONFIG["x"]["enabled"] is True)

print("\n== the one letter tells nothing else apart ==")
from app.core import ipc  # noqa: E402

check("its targets are the letter and a number", ipc.platform_of("x") == "x" and ipc.platform_of("x2") == "x"
      and ipc.x_index("x") == 1 and ipc.x_index("x7") == 7)
check("and no other platform's target is read as X",
      [ipc.platform_of(t) for t in ("snap", "tiktok2", "insta", "mc", "imsg", "tg3", 1)]
      == ["snapchat", "tiktok", "instagram", "minecraft", "imessage", "telegram", "discord"])
check("it is a browser platform, so its files live in ipc/", ipc.is_browser("x") and ipc.is_bridged("x"))
check("its web id goes both ways", ipc.web_id_for("x3") == "x_3" and ipc.target_for("x_3") == "x3")
check("a target that is not one is still refused",
      not any(ipc._VALID_TARGET.match(s) for s in ("x0", "x1", "xx", "../x", "x1000")))

from app.utils import snappeople  # noqa: E402

check("a person is x_ and their handle, a group message xg_ and a number",
      snappeople.platform_of_user("x_theo_wav") == "x" and snappeople.platform_of_user("xg_1588") == "x")
check("a handle with an underscore of its own is still a person, not a group",
      snappeople.platform_of_user("x_g_tom") == "x" and snappeople.handle_of("x_g_tom") == "g_tom")
check("a handle reads back exactly as it was", snappeople.x_handle(snappeople.x_id("@G_Tom")) == "g_tom")
check("and what X could never call anyone gives nothing",
      snappeople.x_id("theo.wav") == "" and snappeople.x_id("sixteencharacters") == "")

print("\n== every table a platform has to be in ==")
from app.utils import chatlog, compat, db, personas  # noqa: E402
from app.web.routes import chat_routes, stats_routes  # noqa: E402

check("its own numbering for the chat log", chatlog.X_BASE == 7000 and chatlog.web_account("x", 2) == 7002)
check("and a target reads back to it", chatlog.log_account("x2") == 7002)
check("its tables in the database", db.WEB_TABLES["x"] == "x"
      and 'CREATE TABLE IF NOT EXISTS message_log_x' in read("app/utils/db.py")
      and 'CREATE TABLE IF NOT EXISTS user_stats_x' in read("app/utils/db.py")
      and 'CREATE TABLE IF NOT EXISTS ignored_users_x' in read("app/utils/db.py"))
check("the account column is kept up to date on it", "message_log_x" in read("app/utils/db.py").split(
    "def ensure_account_columns")[1][:600])
check("its replies are counted", ("x", "message_log_x", "chat_id") in stats_routes.LOGS
      and stats_routes._STATS_TABLE["x"] == "user_stats_x")
check("the chat routes know its prefix and its table",
      chat_routes._WEB_PREFIX["x"] == "x" and chat_routes._WEB_TABLE["x"] == "x"
      and chat_routes._web_platform("x2") == "x" and chat_routes._snap_number("x2") == 2
      and chat_routes._snap_number("insta2") == 2)
check("the panel may be told it cannot run here", compat.FEATURES["x"] == "X (Twitter)")
check("a persona may be given one", bool(personas._WEB_ID.match("x_1")))
check("its people are cached under their own folder", snappeople._TABLES["x"] == "x"
      and snappeople._dir("x").name == "x_people")

print("\n== the bridge serves it ==")
import os  # noqa: E402

os.environ["BRIDGE_PLATFORM"] = "x"
from app.platforms import snapchat_bridge as bridge  # noqa: E402

check("there is a row for it", bridge.PLATFORM == "x" and bridge.P["key"] == "x" and bridge.P["env"] == "X"
      and bridge.P["runner"] == "x_runner.js")
check("and it goes out in public, so the out tab works", bridge.SOCIAL is True)
check("its own chats are never answered", "grok" in bridge.P["system_chats"])
check("any emoji may be a reaction", bridge.P.get("any_reaction") is True)
src = read("app/platforms/snapchat_bridge.py")
check("the runner's files are copied into the data dir, or a build ships a stale one",
      'p.suffix in (".js", ".mjs")' in src.split("def _sync_runner_files")[1][:1400]
      and all((ROOT / "app/platforms/snapchat" / n).is_file() for n in ("xbot.js", "x_runner.js", "x_login.js", "x_probe.js")))
check("it has the pair it goes out with", "from app.utils import xsocial, xwatch" in src)
check("the panel's commands reach its runner",
      all(k in bridge._OUT_OPS for k in ("x_posts", "x_post", "x_action", "x_out", "x_mentions", "x_thread",
                                         "x_follow", "x_fetch", "x_code")))
check("a post is words and pictures here, not a file with a caption",
      'elif op == "post" and PLATFORM == "x":' in src and src.index('elif op == "post" and PLATFORM == "x":')
      < src.index('elif op == "post":'))

print("\n== every setting reaches the runner ==")
env = bridge._x_env(CONFIG)
keys = [k for k, _ in leaves({"x": CONFIG["x"]})]
check("there are settings to hand over", len(keys) >= 38)
deaf = []
for key, value in leaves({"x": CONFIG["x"]}):
    if key == "x.enabled":
        continue                         # the supervisor's, never the runner's
    other = copy.deepcopy(CONFIG)
    node = other
    for part in key.split(".")[:-1]:
        node = node[part]
    node[key.rsplit(".", 1)[1]] = (not value) if isinstance(value, bool) else (
        value + 7 if isinstance(value, int) else "99-23")
    if bridge._x_env(other) == env:
        deaf.append(key)
check("and changing any one of them changes what the runner is told", not deaf, ", ".join(deaf))
check("what is already in the environment wins, since that is where its login is",
      'if k not in os.environ' in src.split("def _x_env")[1][:4200])

print("\n== every setting has words on it ==")
from app.web import descriptions, schema  # noqa: E402

in_schema = {r["key"] for r in schema.CONFIG_SCHEMA}
no_words = [k for k in keys if k not in descriptions.DESCRIPTIONS
            or (k not in descriptions.LABELS and k not in in_schema)]
check("a description and a label for each", not no_words, ", ".join(no_words))
wrong_tab = [k for k in keys if descriptions.section_for(k) != "X"]
check("and all of them under one tab", not wrong_tab, ", ".join(wrong_tab))
stale = [k for k in list(descriptions.DESCRIPTIONS) + list(descriptions.LABELS)
         if k.startswith("x.") and k not in keys]
check("and nothing described that is not there any more", not stale, ", ".join(sorted(set(stale))))
check("the ones handed over at launch say they need a restart",
      descriptions.needs_restart("x.poll_interval_ms") and descriptions.needs_restart("x.posting.enabled")
      and descriptions.needs_restart("x.engage.likes_per_day"))
check("both switches are rows people see first",
      "x.enabled" in descriptions.COMMON and "services.x.enabled" in descriptions.COMMON)

print("\n== everything public starts off ==")
x = CONFIG["x"]
check("it answers messages out of the box", x["enabled"] is True and x["poll_interval_ms"] >= 5000)
check("but says nothing in public until it is told to",
      x["mentions"]["enabled"] is False and x["posting"]["enabled"] is False
      and not any(x["engage"][k] for k in ("like_sent", "repost_sent", "like_theirs", "repost_theirs",
                                           "follow_back")))
check("and nothing public is unbounded", all(1 <= x["engage"][k] <= 50 for k in
      ("reposts_per_day", "follows_per_day")) and x["engage"]["likes_per_day"] <= 30
      and x["posting"]["per_day"] <= 5)
check("it goes slower than Instagram, which is already the careful one",
      x["min_send_gap_ms"] > CONFIG["instagram"]["min_send_gap_ms"]
      and x["max_sends_per_hour"] < CONFIG["instagram"]["max_sends_per_hour"])
check("a post of its own comes from what it saw online or what is on its mind",
      set(x["posting"]["from"]) == {"saw_online", "on_its_mind"} and all(x["posting"]["from"].values()))
check("and fits in a post", x["posting"]["max_chars"] <= 280)

print("\n== what it reads and what it knows of people ==")
from app.utils import xsocial, xwatch  # noqa: E402

check("an x.com link to a post is spotted, on either of X's two names",
      xwatch.links("look https://x.com/jack/status/20 and https://twitter.com/a/status/1234567890123456789")
      == ["https://x.com/jack/status/20", "https://twitter.com/a/status/1234567890123456789"])
check("a short number counts: the first post on the site is /status/20", xwatch.post_id("https://x.com/j/status/20")
      == "20")
check("and a profile or somebody else's site is not a post",
      not xwatch.links("https://x.com/jack") and not xwatch.links("https://example.com/a/status/9"))
check("counts read as X writes them", (xwatch.count_str(40200), xwatch.count_str(999), xwatch.count_str(2_500_000))
      == ("40.2K", "999", "2.5M"))
check("a post read becomes one line for the model, with no X wording in it",
      "40.2K likes" in xwatch.summary({"handle": "jack", "text": "hello", "counts": {"likes": 40200}})
      and xwatch.summary({}) == "")
check("a public answer is tidied: no @ in front, which X puts there itself",
      xsocial.clean_reply("@someone  that is fair") == "that is fair")
check("and a post of its own loses the hashtag pile that gives a bot away",
      xsocial.clean_post("something real #ai #bots") == "something real")
check("both are cut to fit a post", len(xsocial.clean_post("w " * 400)) <= 270
      and len(xsocial.clean_reply("w " * 400)) <= 270)
check("where a post comes from follows the two switches",
      xsocial.post_source("default") == ("", ""))         # posting is off in the shipped config
check("and X shares nothing the way Instagram shares a reel, which the bridge asks every platform",
      xsocial.share_settings() is False and xsocial.wants_reel("send me a reel") is False
      and xsocial.pools_for("default") == [])
check("what it knows of somebody is its own block, not another platform's",
      "THEIR X:" in xsocial.profile_block({"name": "Theo", "followers": 40200}, "theo_wav"))

print("\n== its login ==")
from app.utils import x_signin  # noqa: E402
from app.web.routes import account_routes  # noqa: E402

spec = account_routes.PLATFORMS["x"]
check("the handle, the password, the 2FA key and the email X asks for",
      spec["fields"] == {"username": "X_USERNAME", "password": "X_PASSWORD", "totp": "X_TOTP", "email": "X_EMAIL", "proxy": "X_PROXY"})
check("the password and the key are write-only; the email is not, so it can be corrected",
      set(spec["secret"]) == {"password", "totp"} and spec["required"] == "username")
from app.web.envfile import SECRET_KEYS  # noqa: E402
check("and the store itself keeps the two secrets back",
      all(SECRET_KEYS.match(k) for k in ("X_PASSWORD_1", "X_TOTP_1")) and not SECRET_KEYS.match("X_EMAIL_1"))
check("a handle is cleaned, however it was typed",
      x_signin.clean_handle("@Theo_Wav") == "theo_wav" and x_signin.clean_handle("https://x.com/jack") == "jack"
      and x_signin.clean_handle("twitter.com/Elon") == "elon" and x_signin.clean_handle("theo.wav") == "")
check("its browser profile is named after it", x_signin.profile_dir("Theo_Wav").name == "x-theo_wav-profile")
paths = {r.path for r in account_routes.router.routes}
check("the panel can sign one in, watch it, answer a code and stop it",
      {f"/api/accounts/x/sign-in/{p}" for p in ("start", "status", "code", "cancel")} <= paths)
acc = read("app/web/routes/account_routes.py")
check("a removed account's profile and identity go with it",
      "_drop_x_profile" in acc and '_renumber_web_identity(cfg, "identity_x"' in acc)

print("\n== a refused login is never tried again by itself ==")
from app.web import supervisor  # noqa: E402

sup_src = read("app/web/supervisor.py")
from app.platforms import registry  # noqa: E402
check("X is one of the accounts the supervisor plans", "x" in registry.IDS and '"x": _count_x_accounts' in sup_src
      and 'out[f"{p.id}_{i}"] = (p.id, i, f"{p.name} #{i}")' in sup_src)
check("and it is left stopped on a refused login, as the others are",
      supervisor.NEEDS_SIGN_IN == 4 and "self._mark_sign_in(child.child_id, True)" in sup_src)
real_dir = None
try:
    from app.utils import paths
    real_dir, paths.DATA_DIR = paths.DATA_DIR, Path(tempfile.mkdtemp())
    s = supervisor.Supervisor(port=0, no_web=True)
    s._mark_sign_in("x_1", True)
    check("remembered across a restart of the app", s.needs_sign_in() == {"x_1"})
    launched = []
    s._planned_children = lambda: {"x_1": ("x", 1, "X #1")}
    s._launch = lambda child: launched.append(child.child_id)
    s.start("x_1")
    check("until a person presses Start", s.needs_sign_in() == set() and launched == ["x_1"])
finally:
    if real_dir is not None:
        from app.utils import paths
        paths.DATA_DIR = real_dir

print("\n== the panel knows it ==")
plat = (SRC / "lib" / "platforms.ts").read_text(encoding="utf-8")
check("it is in the one table the panel reads", 'id: "x", name: "X (Twitter)", short: "X"' in plat
      and '| "x"' in plat)
check("driven through a browser, like the other three", re.search(r'id: "x",[^}]*browser: true', plat, re.S))
check("its colour is the near-white its own pages use, not a black hole in a card", '#e7e9ea' in plat)
check("a person's id routes to it, groups before people",
      's.startsWith("x_") || s.startsWith("xg_")' in plat)
check("its mark is there and drawn solid",
      "X_MARK" in (SRC / "lib" / "brands.ts").read_text(encoding="utf-8")
      and 'x: X_MARK' in (SRC / "lib" / "components" / "Icon.svelte").read_text(encoding="utf-8"))
icon = (SRC / "lib" / "components" / "Icon.svelte").read_text(encoding="utf-8")
check("filled, and pulled in like the other corner-to-corner marks",
      '"instagram", "x"' in icon and 'x: "translate(1.2 1.2) scale(0.9)"' in icon)
check("a log line of its own is hidden with it",
      "PLATFORM_IDS.join(" in (SRC / "lib" / "socials.ts").read_text(encoding="utf-8")
      and "\n  x: {" in (SRC / "lib" / "platforms.ts").read_text(encoding="utf-8"))

smap = (SRC / "lib" / "settingsmap.ts").read_text(encoding="utf-8")
check("it has a Settings tab, whose id is the platform's", 'id: "x",\n    name: "X",' in smap)
check("with its install panel", '"x-setup"' in smap)
check("and its switches in What runs", '"services.x.enabled",' in smap and '"x.enabled",' in smap)
tab = smap[smap.index('id: "x",\n    name: "X",'):]
tab = tab[:tab.index("{ id: \"rest\"")]
in_tab = set(re.findall(r'"(x\.[a-z_.]+)"', tab))
missed = [k for k in keys if k not in in_tab and k != "x.enabled"]
check("every setting has a home in it, so none fall into Everything else", not missed, ", ".join(missed))

settings = (SRC / "pages" / "Settings.svelte").read_text(encoding="utf-8")
check("its two switches are one switch on screen", '"services.x.enabled": "x.enabled"' in settings)
check("its install panel is the same for every profile", '"x-setup"' in settings)
cond = (SRC / "lib" / "accounts" / "condition.ts").read_text(encoding="utf-8")
check("its card reads the runner's own state, as the browser platforms do",
      'slot.platform !== "discord" && slot.platform !== "snapchat" && rt?.web' in cond)
accounts = (SRC / "pages" / "Accounts.svelte").read_text(encoding="utf-8")
check("it can be added, from all three places that offer it",
      accounts.count('openAdd("x")') == 3 and '{ id: "x", label: "X"' in accounts)
check("and its dialog is its own colour, not Discord's blue", '.aa[data-platform="x"] .aa-hero' in accounts)
check("the email X asks for is asked for", 'id="x-email"' in accounts and "fEmail" in accounts)
api = (SRC / "lib" / "api.ts").read_text(encoding="utf-8")
check("the panel can drive the sign-in", all(f"xSignIn{p}" in api for p in ("Start", "Status", "Code", "Cancel")))

print("\n== the runner gives up the two ways it should ==")
# Run for real, with no browser involved: both of these happen before one is opened. Exit 4 is the one that
# matters - the supervisor reads it as "a person has to" and never starts it again by itself, which is what keeps
# a refused login from becoming a login every two minutes.
import shutil  # noqa: E402
import subprocess  # noqa: E402

import os  # noqa: E402

node = shutil.which("node")
# Node looks for its packages beside the script. A source checkout may have them; an installed app keeps them in
# its data folder and runs the runner from there (snapchat_bridge._sync_node_runner), so both are looked in.
from app.utils.paths import DATA_DIR  # noqa: E402

homes = [ROOT / "app/platforms/snapchat", DATA_DIR / "snapchat",
         Path(os.environ.get("APPDATA", "")) / "LLMSelfbot" / "snapchat"]
runner_dir = next((h for h in homes if (h / "node_modules").is_dir() and (h / "x_runner.js").exists()), None)
RUNNER = runner_dir / "x_runner.js" if runner_dir else None
if not node or not runner_dir:
    print("  SKIP  needs Node and the browser packages")
else:
    def run_runner(extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("X_")}
        env.update({"X_DATA_DIR": tmp_dir, "SNAP_DATA_DIR": tmp_dir, "X_ACCOUNT_INDEX": "1", **extra})
        p = subprocess.run([node, str(RUNNER)], env=env, cwd=str(runner_dir), capture_output=True, text=True,
                           timeout=180, encoding="utf-8", errors="replace")
        return p.returncode, p.stdout + p.stderr

    with tempfile.TemporaryDirectory() as tmp_dir:
        code, said = run_runner({})
        check("with no account at all it says so and stops", code == 1
              and "add one on the accounts page" in said.lower(), f"exit {code}")
    with tempfile.TemporaryDirectory() as tmp_dir:
        code, said = run_runner({"X_USERNAME_1": "someone"})
        state = {}
        f = Path(tmp_dir) / "ipc" / "x_state.json"
        if f.exists():
            import json
            state = json.loads(f.read_text(encoding="utf-8"))
        check("with no signed-in profile it asks for a person, and exits 4 rather than trying", code == 4,
              f"exit {code}")
        check("and the card says what to do", state.get("state") == "needs-you"
              and "signed in" in (state.get("detail") or ""), str(state))
        made = sorted(p.name for p in (Path(tmp_dir) / "ipc").glob("x_*"))
        check("with all its files made, so the bridge finds them",
              {"x_incoming.json", "x_responses.json", "x_outgoing.json", "x_state.json"} <= set(made), str(made))

print("\n== the page itself, read for real ==")
# xbot.js's selectors can only be right or wrong against a page, so they are run against saved copies of X's
# (tests/fixtures/x_*.html) in a headless Chrome. With no X account yet, this is what stands in for one.
import shutil  # noqa: E402
import subprocess  # noqa: E402

node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "x_logic.mjs")], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
    print("\n".join("  " + line for line in proc.stdout.strip().splitlines()[-4:]))
    check("x_logic.mjs passes", proc.returncode == 0, (proc.stdout + proc.stderr)[-700:])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
