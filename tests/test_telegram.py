"""Telegram, a seventh platform: the persona on a Telegram account of its own.

Not the control bot (app/telegram_bot), which is the bot you send commands to and which this must never be confused
with. This is an account the persona chats from, through Telethon (MTProto, the client API Telegram publishes),
run by the shared bridge with no Node runner at all: the client is Python, so it lives on the bridge's own loop.

Everything here runs offline: the ids, the sign-in's state machine, what a message becomes, the governor, the
settings, the routes and the panel's parts, with a stand-in Telethon. Talking to Telegram needs a real account.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="llmbot_tg_"))
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(ROOT))
(DATA / "config").mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
for k in [k for k in os.environ if k.startswith("TELEGRAM_")]:
    os.environ.pop(k, None)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== who its people are ==")
from app.platforms.telegram import people  # noqa: E402

check("a person is their own id, never bare digits, which mean Discord everywhere",
      people.person_id(133712345) == "tg_133712345" and people.person_id("-77") == "tg_77")
check("a group or a channel keeps its own number, without the wire's -100",
      people.group_id(-1001234567890) == "tgg_1234567890" and people.group_id(-987654) == "tgg_987654")
check("and back again", people.telegram_id("tg_133712345") == 133712345
      and people.telegram_id("tgg_1234567890") == 1234567890 and people.telegram_id("snapperson") == 0)
check("a group is told from a person", people.is_group("tgg_5") and not people.is_group("tg_5"))
check("Telegram's own bare peers, whose id is under a different name each",
      people.uid_of_peer(types.SimpleNamespace(user_id=7)) == "tg_7"
      and people.uid_of_peer(types.SimpleNamespace(channel_id=-1001)) == "tgg_1001"
      and people.uid_of_peer(types.SimpleNamespace(chat_id=9)) == "tgg_9"
      and people.uid_of_peer(types.SimpleNamespace()) == "")
check("what to call someone: their name, their @username, their number, in Telegram's own order",
      people.pretty("Theo Martin") == "Theo Martin" and people.pretty("", "theo") == "@theo"
      and people.pretty("", "", "+33 6 12") == "+33612" and people.pretty("", "", "", 42) == "tg_42")
check("a group message that calls it by name", people.mentioned("so alicia what do you think", ["Alicia"])
      and people.mentioned("hey @alicia_m", ["alicia_m"]) and not people.mentioned("hey bob", ["Alicia"]))
check("and one that only looks like it", not people.mentioned("aliciaaa", ["alicia"])
      and not people.mentioned("malicia", ["alicia"]))
check("the names it answers to: the persona's, its @username and its first name",
      people.trigger_names("Alicia, Ali", "alicia_m", "Alicia") == ["Alicia", "Ali", "alicia_m"])

print("\n== its account, and where its commands go ==")
from app.core import ipc  # noqa: E402

check("no sign-in saved: no account", ipc._count_telegram_accounts() == 0)
os.environ["TELEGRAM_SESSION_1"] = "1BQAsession"
os.environ["TELEGRAM_SESSION_2"] = "1BQAanother"
check("counted by the sign-in each one left behind", ipc._count_telegram_accounts() == 2)
check("its targets: tg, tg2", ipc.validate_target("tg") == "tg" and ipc.validate_target("tg2") == "tg2")
check("run by the shared bridge, with no browser", ipc.is_bridged("tg2") and not ipc.is_browser("tg")
      and ipc.platform_of("tg2") == "telegram" and ipc.telegram_index("tg2") == 2)
check("its web ids, both ways", ipc.target_for("telegram_2") == "tg2" and ipc.web_id_for("tg") == "telegram_1")
check("among the accounts the panel knows",
      ipc.discover_targets().get("telegram_2", {}).get("target") == "tg2")
check("and never taken for TikTok's, which also starts with a t",
      ipc.platform_of("tiktok2") == "tiktok" and not ipc.is_telegram("tiktok2"))

print("\n== signing in ==")
from app.platforms.telegram import signin  # noqa: E402

check("a number as people type one, as Telegram wants it", signin.clean_phone("+33 6 12 34 56 78") == "+33612345678"
      and signin.clean_phone("0033612345678") == "+33612345678" and signin.clean_phone("nope") == "")
check("what my.telegram.org gives, checked before Telegram is asked",
      signin.clean_api_id("123456") == 123456 and signin.clean_api_id("abc") == 0
      and signin.clean_api_hash("A" * 32) == "a" * 32 and signin.clean_api_hash("short") == "")
got = asyncio.run(signin.start("abc", "x", "+33612345678"))
check("a bad api_id is said in words, and Telegram is never called", got["state"] == "failed"
      and "my.telegram.org" in got["detail"], got)
got = asyncio.run(signin.start("123456", "a" * 32, "nope"))
check("and so is a number that is not one", got["state"] == "failed" and "phone number" in got["detail"], got)
check("nothing waiting: a code goes nowhere", asyncio.run(signin.give_code("12345"))["state"] == "failed")
src = read("app/platforms/telegram/signin.py")
check("the code and the password are each their own step, and the password is never stored",
      "SessionPasswordNeededError" in src and "_set(state=\"password\"" in src
      and "async def give_password" in src and "password" not in src.split("_STATE[\"login\"] = {")[1][:400])
check("the session string is handed over once and then forgotten",
      '_STATE.pop("login", None)' in src and "def take_login" in src)

print("\n== what a message is ==")
from app.platforms.telegram.client import GIFT_RE, Governor, Telegram  # noqa: E402

check("a Premium gift link", (GIFT_RE.search("here https://t.me/giftcode/AbCd1234EfGh") or [None]) and
      GIFT_RE.search("https://t.me/giftcode/AbCd1234EfGh").group(1) == "AbCd1234EfGh"
      and not GIFT_RE.search("https://t.me/someone"))


def msg(**kw):
    base = dict(poll=None, geo=None, contact=None, sticker=None, gif=None, voice=None, video_note=None,
                video=None, photo=None, document=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


for kind, m in (("voice", msg(voice=1)), ("photo", msg(photo=1)), ("video", msg(video=1)),
                ("round", msg(video_note=1)), ("sticker", msg(sticker=1)), ("gif", msg(gif=1)),
                ("poll", msg(poll=1)), ("file", msg(document=1)), ("", msg())):
    check(f"a message that is {kind or 'only words'}", Telegram.kind_of(m) == kind, Telegram.kind_of(m))
check("a sticker is a sticker before it is a document, and a voice note before a video",
      Telegram.kind_of(msg(sticker=1, document=1)) == "sticker"
      and Telegram.kind_of(msg(voice=1, video=1, document=1)) == "voice")

print("\n== how fast it may send ==")
g = Governor(min_gap_ms=1000, max_gap_ms=1000, per_hour=2, quiet="")
check("the first send goes at once", g.wait_for() == 0)
# One send in twelve "drifts off" for minutes at random, as a person does: seeded, so this one does not.
import random  # noqa: E402
random.seed(0)
g.sent()
check("then it waits the gap", 0.5 < g.wait_for() <= 1.0, g.wait_for())
g.sent()
check("and stops at the cap for the hour", g.wait_for() > 60, g.wait_for())
_h = time.localtime().tm_hour
g2 = Governor(per_hour=100, quiet=f"{_h}-{(_h + 1) % 24}")
check("quiet hours hold everything", g2.wait_for() > 0 and g2.quiet_now())
g3 = Governor(per_hour=100)
g3.hold(120)
check("and so does a wait Telegram asked for", 100 < g3.wait_for() <= 120, g3.wait_for())
check("a window that crosses midnight works as it reads",
      Governor(quiet="23-7").quiet_now() == (time.localtime().tm_hour >= 23 or time.localtime().tm_hour < 7))

print("\n== its settings ==")
from app.platforms.telegram.client import DEFAULTS, settings  # noqa: E402
from app.web import schema, descriptions  # noqa: E402

s = settings({})
check("a fresh account starts gentle: a wait between sends, and few an hour",
      s["min_send_gap_ms"] >= 5000 and s["max_sends_per_hour"] <= 40, s)
check("and keeps to itself: no groups, no channels, never writing first",
      not s["groups"] and not s["channels"] and not s["answer_first"])
check("the config's own values win over those", settings({"groups": True, "max_sends_per_hour": 7})["groups"]
      and settings({"max_sends_per_hour": 7})["max_sends_per_hour"] == 7)
os.environ["TELEGRAM_MAX_SENDS_PER_HOUR"] = "3"
check("and .env wins over the config, as the other platforms' runners read theirs",
      settings({"max_sends_per_hour": 7})["max_sends_per_hour"] == 3)
os.environ.pop("TELEGRAM_MAX_SENDS_PER_HOUR")
keys = {f["key"] for f in schema.CONFIG_SCHEMA if f["key"].startswith("telegram.")}
check("every setting is in the schema, said in words, and named",
      len(keys) >= 19 and all(descriptions.DESCRIPTIONS.get(k) for k in keys)
      and all(descriptions.label_for(k) for k in keys), sorted(keys - set(descriptions.DESCRIPTIONS)))
check("each one the client reads is one the panel can set",
      {f"telegram.{k}" for k in DEFAULTS} <= keys, sorted({f"telegram.{k}" for k in DEFAULTS} - keys))
cfg = read("resources/config.yaml")
check("a fresh install has them", "\ntelegram:\n" in cfg and "  max_sends_per_hour: 30" in cfg
      and "  telegram_accounts:\n    enabled: true" in cfg)

print("\n== kept where the other platforms keep theirs ==")
from app.utils import chatlog, db, snappeople  # noqa: E402

check("its conversations are numbered past iMessage's", chatlog.web_account("telegram", 2) == 6002)
check("its tables are its own", db.WEB_TABLES["telegram"] == "telegram"
      and snappeople._TABLES["telegram"] == "telegram")
check("its people are told from everyone else's", snappeople.platform_of_user("tg_7") == "telegram"
      and snappeople.platform_of_user("tgg_7") == "telegram" and snappeople.platform_of_user("77") == "discord")
check("a picture of theirs is kept under their own id, not only a number",
      chatlog.picture_name("t4821", 0, "image/jpeg") == "t4821_0.jpg"
      and chatlog.media_path("t4821_0.jpg") is None)   # none kept here, but the name is allowed

print("\n== the worker ==")
br = read("app/platforms/snapchat_bridge.py")
check("it is the bridge's own platform, with no runner to start",
      '"telegram": {' in br and '"name": "Telegram", "key": "tg", "env": "TELEGRAM", "runner": ""' in br
      and 'TELEGRAM = PLATFORM == "telegram"' in br)
check("its client runs beside the reply pipeline, as a task of its own",
      "tasks = [process_incoming(), tg_command_loop(), _cleanup_loop(), _nudge_loop(), _telegram_main()]" in br)
check("a message from Telegram goes into the same queue a runner fills",
      "_write_json(INCOMING_FILE, queued[-300:])" in br and "_wake_incoming.set()" in br)
check("a group message that does not call it by name is kept, not answered",
      'if entry.get("quiet"):' in br and "def _telegram_keep" in br)
check("its answers go out through the governor, a line at a time, with the dots",
      "async def _telegram_turn" in br and 'cfg.get("typing_indicator", True)' in br
      and "await tg.typing(chat," in br)
check("what it sent is kept and shown, the way a transcript would bring it back",
      "def _telegram_sent" in br and '_emit_chat({"t": "sent"' in br)
check("you answering from Telegram yourself drops the reply it had lined up",
      'if _drop_outgoing(chat):' in br and 'kind == "mine"' in br)
check("a wait Telegram asks for is said on the card and to you, not swallowed",
      "def _telegram_flood" in br and '_set_runner_state("needs-you"' in br and "_notify_owner(" in br)
check("a call it cannot take is declined and answered in words",
      "async def _telegram_call_text" in br and "_generate_call_decline" in br)
check("its chats, names and pictures kept for the panel", "async def _telegram_people_loop" in br
      and 'snappeople.remember(ACCOUNT_INDEX, row["id"], fields, "telegram")' in br)

cl = read("app/platforms/telegram/client.py")
check("the words go as the persona wrote them: no markdown eating its asterisks", "parse_mode=None" in cl)
check("every wait Telegram asks for reaches us rather than being slept through",
      "flood_sleep_threshold=0" in cl)
check("its own log lines never carry a connection's details",
      'logging.getLogger("telethon").setLevel(logging.WARNING)' in cl)
check("one message at a time, in order, and what was missed while it was away",
      "sequential_updates=True" in cl and "catch_up=True" in cl)
check("a session Telegram no longer takes is said, and not crash-looped",
      "PermissionError" in cl and "Sign the account in again" in cl)

print("\n== the panel ==")
check("its card: signed out, waiting, connecting, online",
      'label: "Signed out"' in read("webui/src/lib/accounts/condition.ts")
      and 'title: "Telegram asked it to wait"' in read("webui/src/lib/accounts/condition.ts")
      and 'if (s.platform === "telegram") return !!s.session_set;' in read("webui/src/lib/accounts/condition.ts"))
acc = read("webui/src/pages/Accounts.svelte")
check("adding one is signing in: its number, then the code, then a two-step password",
      "async function signInTelegram" in acc and 'tgStep === "code"' in acc and 'tgStep === "password"' in acc
      and "my.telegram.org" in acc)
check("its mark is a paper plane of our own", "TELEGRAM_PLANE" in read("webui/src/lib/brands.ts")
      and "telegram: TELEGRAM_PLANE," in read("webui/src/lib/components/Icon.svelte"))
plat = read("webui/src/lib/platforms.ts")
check("the platform: any emoji as a reaction, groups, stories, voice",
      'id: "telegram", name: "Telegram"' in plat and "anyReaction: true" in plat.split('telegram: {')[1][:600]
      and 'if (s.startsWith("tg_") || s.startsWith("tgg_")) return PLATFORMS.telegram;' in plat)
smap = read("webui/src/lib/settingsmap.ts")
check("its own page in Settings, and the word telegram pointing at it",
      'id: "telegram",\n    name: "Telegram",' in smap and 'telegram: "telegram/texting",' in smap
      and '"telegram bot": "app/telegram",' in smap)

print("\n== and the control bot, which is not it ==")
check("the bot that controls the app is no platform, so the panel does not hide the accounts with it",
      '"platform": "controller",' in read("app/web/routes/status_routes.py"))
for rel in ("webui/src/TrayPanel.svelte", "webui/src/pages/Profiles.svelte", "webui/src/lib/chats.ts",
            "webui/src/lib/bigpicture/world.svelte.ts", "webui/src/lib/components/PicturesPanel.svelte"):
    check(f"  hidden by what it is, in {Path(rel).name}", '!== "controller"' in read(rel)
          and '!== "telegram"' not in read(rel))
ctl = read("app/telegram_bot/telegram_controller.py")
check("and it can drive them: /account tg", 'r"(?:tg|telegram)(\\d*)"' in ctl and "NUM_TG_ACCOUNTS" in ctl
      and '"/account tg \\u2014 control the Telegram bot\\n"' in ctl)
check("its alerts reach you from them too", 'targets.append("tg" if i == 1 else f"tg{i}")' in ctl)

print("\n== its login, kept out of sight ==")
from app.web.envfile import SECRET_KEYS  # noqa: E402

check("the session and the api_hash are write-only; the number and api_id are not secret",
      SECRET_KEYS.fullmatch("TELEGRAM_SESSION_1") and SECRET_KEYS.fullmatch("TELEGRAM_API_HASH_2")
      and not SECRET_KEYS.fullmatch("TELEGRAM_PHONE_1") and not SECRET_KEYS.fullmatch("TELEGRAM_API_ID_1"))
from app.web.routes import account_routes  # noqa: E402

spec = account_routes.PLATFORMS["telegram"]
check("its slot is what signing in left behind", spec["required"] == "session"
      and set(spec["secret"]) == {"session", "api_hash"})
slots = account_routes._slots({"TELEGRAM_SESSION_1": "1BQAsecret", "TELEGRAM_PHONE_1": "+33612345678",
                               "TELEGRAM_API_ID_1": "123456", "TELEGRAM_API_HASH_1": "a" * 32})
check("listed without ever handing the session back", slots == [
    {"id": "telegram_1", "platform": "telegram", "index": 1, "session_set": True, "api_id": "123456",
     "api_hash_set": True, "phone": "+33612345678", "proxy": ""}], slots)
paths = {r.path for r in account_routes.router.routes}
check("its sign-in has a step for each thing Telegram asks",
      {"/api/accounts/telegram/sign-in/start", "/api/accounts/telegram/sign-in/code",
       "/api/accounts/telegram/sign-in/password", "/api/accounts/telegram/sign-in/cancel",
       "/api/accounts/telegram/sign-in/status"} <= paths)
try:
    account_routes._telegram_body({"phone": "+33"})
    check("an account cannot be typed in by hand", False)
except Exception as e:
    check("an account cannot be typed in by hand", getattr(e, "status_code", 0) == 400 and "signing in" in str(e.detail))

shutil.rmtree(DATA, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
