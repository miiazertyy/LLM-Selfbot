"""Nitro gifts people send in a DM.

A gift link sent to the account in a DM is the account's own, and it expires.
So the account looks up what it is, keeps it with the message, tells you on
Telegram, and - when that is the setting - takes it the moment it lands. Either
way it draws in the Chats tab as a gift rather than as a link nobody can read,
with the button that takes it.

Only in DMs: a link in a server is first come first served, and racing other
people for it is not what this is.

The reading, the taking and what is kept are run for real against a stand-in
Discord; the panel's part is read from the source.
"""
import asyncio
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-gifts-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"),
                                            encoding="utf-8")
# The runner stops at once with nothing to write replies with; nothing here ever asks it to write one.
(TMP / "config" / ".env").write_text("GROQ_API_KEY_1=gsk_test\nDISCORD_TOKEN_1=test\n", encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def app_src(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== a gift link, found in what was said ==")
import discord  # noqa: E402
import app.platforms.discord_runner as dr  # noqa: E402

for link in ("https://discord.gift/aBc123XyZ9876543",
             "discord.gift/aBc123XyZ9876543",
             "https://discord.com/gifts/aBc123XyZ9876543",
             "http://discordapp.com/gifts/aBc123XyZ9876543",
             "here you go https://discord.gift/aBc123XyZ9876543 enjoy"):
    check(f"found in {link[:46]}", dr.gift_code(link) == "aBc123XyZ9876543", dr.gift_code(link))
for plain in ("", "https://discord.com/channels/1/2/3", "discord.gg/abcdef", "nitro for you",
              "https://example.com/gifts/aBc123XyZ9876543"):
    check(f"not a gift: {plain[:40] or '(nothing)'}", dr.gift_code(plain) == "", dr.gift_code(plain))

print("\n== what it is, and whether it can still be taken ==")


def fake_gift(name="Nitro Monthly", claimed=False, expired=False, uses=0, max_uses=1):
    return types.SimpleNamespace(
        code="aBc123XyZ9876543", subscription_plan=types.SimpleNamespace(name=name), store_listing=None,
        uses=uses, max_uses=max_uses, is_claimed=lambda: claimed, is_expired=lambda: expired, redeemed=claimed)


check("a Nitro plan by its name", dr.gift_says(fake_gift()) == "Nitro Monthly")
check("a game by its own", dr.gift_says(types.SimpleNamespace(
    subscription_plan=None,
    store_listing=types.SimpleNamespace(sku=types.SimpleNamespace(name="Celeste"), summary=""))) == "Celeste")
check("and one it cannot name is still a gift", dr.gift_says(
    types.SimpleNamespace(subscription_plan=None, store_listing=None)) == "a gift")
check("waiting while it is there", dr.gift_state(fake_gift()) == "waiting")
check("taken once someone has used it", dr.gift_state(fake_gift(claimed=True)) == "taken")
check("taken once its uses are gone", dr.gift_state(fake_gift(uses=1, max_uses=1)) == "taken")
check("run out when it has expired", dr.gift_state(fake_gift(expired=True)) == "expired")

print("\n== taking one ==")


class FakeGift:
    def __init__(self, **kw):
        self.g = fake_gift(**kw)
        self.redeemed_in = None
        self.raise_on_redeem = None
        for f in ("subscription_plan", "store_listing", "uses", "max_uses", "is_claimed", "is_expired"):
            setattr(self, f, getattr(self.g, f))

    async def redeem(self, payment_source=None, *, channel=None, **kw):
        if self.raise_on_redeem:
            raise self.raise_on_redeem
        self.redeemed_in = channel
        return types.SimpleNamespace(id=1)


class FakeBot:
    def __init__(self):
        self.gift = FakeGift()
        self.missing = False
        self.selfbot_id = 42

    async def fetch_gift(self, code, **kw):
        if self.missing:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "unknown gift")
        return self.gift

    def get_user(self, uid):
        return None


bot = FakeBot()
dr.bot = bot
took = asyncio.run(dr.take_gift("aBc123XyZ9876543", channel="dm"))
check("a gift that is there: taken, in the chat it came in", took["ok"] and took["state"] == "accepted"
      and took["what"] == "Nitro Monthly" and bot.gift.redeemed_in == "dm", took)
bot.gift = FakeGift(claimed=True)
took = asyncio.run(dr.take_gift("aBc123XyZ9876543"))
check("one already used: said so, not tried", not took["ok"] and took["state"] == "taken"
      and "already" in took["reason"].lower(), took)
bot.gift = FakeGift(expired=True)
check("one that ran out, likewise", asyncio.run(dr.take_gift("x"))["state"] == "expired")
bot.missing = True
took = asyncio.run(dr.take_gift("aBc123XyZ9876543"))
check("one Discord has never heard of", not took["ok"] and took["state"] == "gone", took)
bot.missing = False
bot.gift = FakeGift()
bot.gift.raise_on_redeem = discord.HTTPException(
    types.SimpleNamespace(status=400, reason="Bad Request"), {"message": "Payment source required"})
took = asyncio.run(dr.take_gift("aBc123XyZ9876543"))
check("one Discord wants a payment method for: said in words, still waiting",
      not took["ok"] and took["state"] == "waiting" and "payment method" in took["reason"], took)

print("\n== one arriving in a DM ==")
from app.utils import chatlog  # noqa: E402

EVENTS, NOTES = [], []
dr.emit_chat_event = lambda e: EVENTS.append(e)
dr.notify_telegram_info = lambda title, detail: NOTES.append((title, detail))
dr.log_system = lambda *a, **k: None
dr.log_error = lambda *a, **k: None
dr.ACCOUNT_INDEX = 1
MODE = {"mode": "notify", "only_friends": False}
dr.gift_settings = lambda: MODE


class FakeMessage:
    def __init__(self, mid, text, friend=True):
        self.id = mid
        self.content = text
        self.channel = "their-dm"
        self.created_at = types.SimpleNamespace(timestamp=lambda: time.time())
        self.author = types.SimpleNamespace(id=7, name="theo", display_name="Theo",
                                            is_friend=lambda: friend)
        self.attachments, self.stickers, self.embeds, self.reactions = [], [], [], []
        self.reference = None
        self.type = discord.MessageType.default


LINK = "a little something https://discord.gift/aBc123XyZ9876543"


def arrives(mid, mode, only_friends=False, friend=True, gift=None):
    """One lands, with the settings as they are. What is kept for the message comes back."""
    MODE.update(mode=mode, only_friends=only_friends)
    bot.gift = gift or FakeGift()
    bot.missing = False
    EVENTS.clear()
    NOTES.clear()
    m = FakeMessage(mid, LINK, friend=friend)
    chatlog.put(1, 7, mid, False, time.time(), dr._message_payload(m))
    asyncio.run(dr.gift_arrived(m))
    kept = [x for x in chatlog.conversation(1, 7, 50) if x["mid"] == str(mid)]
    return (kept[0].get("gift") or {}) if kept else {}


kept = arrives(201, "notify")
check("the message is kept as a gift, by its code, before anything is known of it",
      chatlog.conversation(1, 7, 50)[0]["gift"]["code"] == "aBc123XyZ9876543")
check("looked up: what it is for, and that it is waiting",
      kept.get("what") == "Nitro Monthly" and kept.get("state") == "waiting", kept)
check("an open Chats tab is told at once", EVENTS and EVENTS[-1]["t"] == "gift"
      and EVENTS[-1]["mid"] == "201" and EVENTS[-1]["gift"]["state"] == "waiting", EVENTS)
check("and you are told, by name, with what it is", NOTES and "Theo" in NOTES[-1][1]
      and "Nitro Monthly" in NOTES[-1][1] and "Accept it" in NOTES[-1][1], NOTES)
check("it is not taken: that was not the setting", bot.gift.redeemed_in is None)

kept = arrives(202, "accept")
check("set to accept: taken as it lands, in the chat it came in",
      kept.get("state") == "accepted" and bot.gift.redeemed_in == "their-dm", kept)
check("said as done, not as something to do", NOTES and "has been taken" in NOTES[-1][1], NOTES)

kept = arrives(203, "accept", only_friends=True, friend=False)
check("only friends' taken by themselves: a stranger's waits for you",
      kept.get("state") == "waiting" and bot.gift.redeemed_in is None
      and "friends" in (kept.get("reason") or ""), kept)
kept = arrives(204, "accept", only_friends=True, friend=True)
check("a friend's is still taken", kept.get("state") == "accepted")

kept = arrives(205, "off")
check("left alone: nothing looked up, nothing said, nothing taken",
      kept == {"code": "aBc123XyZ9876543", "state": "unknown"} and not NOTES and not EVENTS, (kept, NOTES))

kept = arrives(206, "notify", gift=FakeGift(claimed=True))
check("one that was already used: said so, and no button to press",
      kept.get("state") == "taken" and "already been used" in NOTES[-1][1], (kept, NOTES))

print("\n== taken from the panel afterwards ==")
uid = chatlog.set_gift(1, 201, {"state": "accepted"})
kept = [m for m in chatlog.conversation(1, 7, 50) if m["mid"] == "201"][0]["gift"]
check("where it stands is kept on the message, the rest of it left alone",
      uid == "7" and kept["state"] == "accepted" and kept["what"] == "Nitro Monthly", kept)
check("a message that is not kept here changes nothing", chatlog.set_gift(1, 999999, {"state": "accepted"}) is None)

print("\n== the account, the panel and the settings ==")
src = app_src("app/platforms/discord_runner.py")
check("only in DMs, and off the reply path so a slow look-up holds nothing up",
      'if isinstance(message.channel, discord.DMChannel) and gift_code(message.content or ""):' in src
      and "asyncio.create_task(gift_arrived(message))" in src)
check("the panel can ask for one to be taken", 'elif cmd == "gift_accept":' in src
      and "_g = await take_gift(_g_code, _g_ch)" in src)
routes = app_src("app/web/routes/chat_routes.py")
check("its route is the account's own, and Discord's alone",
      '@router.post("/api/gifts/accept")' in routes and 'ipc.platform_of(tgt) != "discord"' in routes
      and 'ipc.send_and_wait(tgt, "gift_accept"' in routes)
check("a later message clears the last one's gift, both sides of the wire",
      'fresh.setdefault("gift", None)' in routes
      and "attachments: [], stickers: [], embeds: [], gift: undefined" in read("lib/chats.ts"))
check("what is kept of a message keeps the gift", '"kind", "approx", "gift")' in app_src("app/utils/chatlog.py"))

chats = read("pages/Chats.svelte")
check("it draws as a gift in the conversation, with what it is for", '<div class="cd-gift"' in chats
      and '{g.what && g.what !== "a gift" ? g.what : "Nitro gift"}' in chats)
check("with the button that takes it, only on theirs and only while it can be taken",
      '{#if !d.m.mine && !GIFT_GONE.has(g.state ?? "") && g.state !== "accepted"}' in chats
      and "onclick={() => takeGift(d.m)}" in chats)
check("which is heard, and says how it went", 'playSound(r?.ok ? "ok" : "err");' in chats
      and "api.giftAccept(m.gift.code, target, m.mid ?? \"\", selected?.id ?? \"\")" in chats)
check("one already used, or run out, says so instead",
      'if (g.state === "taken") return "Already used";' in chats
      and 'const GIFT_GONE = new Set(["taken", "expired", "gone"]);' in chats)
check("the list says a gift rather than the link", 'if (u.gift) return u.gift.state === "accepted"' in chats)
check("and there is a gift to draw it with", '    gift: "M4 11.5h16' in read("lib/components/Icon.svelte"))
check("the panel's call", "giftAccept: (code: string, target = \"\", mid = \"\", user_id = \"\")" in read("lib/api.ts"))

from app.web import schema, descriptions  # noqa: E402

keys = {f["key"] for f in schema.CONFIG_SCHEMA}
check("both settings are in the schema, with telling me as the default",
      {"discord.gifts.mode", "discord.gifts.only_friends"} <= keys
      and next(f for f in schema.CONFIG_SCHEMA if f["key"] == "discord.gifts.mode")["default"] == "notify")
check("each says what it does, and is named", all(
    descriptions.DESCRIPTIONS.get(k) and descriptions.label_for(k) and not descriptions.is_hidden(k)
    for k in ("discord.gifts.mode", "discord.gifts.only_friends")))
smap = read("lib/settingsmap.ts")
check("on their own page under Discord", 'id: "gifts",' in smap and 'name: "Nitro gifts",' in smap
      and '"discord.gifts.mode"' in smap and '"discord.gifts.only_friends"' in smap)
check("the three choices are plain words", '{ value: "notify", label: "Tell me"' in read("pages/Settings.svelte")
      and '{ value: "accept", label: "Accept it"' in read("pages/Settings.svelte")
      and '{ value: "off", label: "Leave them"' in read("pages/Settings.svelte"))
cfg = app_src("resources/config.yaml")
check("and a fresh install has them", "  gifts:" in cfg and "    mode: notify" in cfg
      and "    only_friends: false" in cfg)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
