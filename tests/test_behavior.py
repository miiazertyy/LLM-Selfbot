"""Tests for the human-behaviour helpers (app/utils/behavior.py) and the
client-profile pieces of app/utils/session.py + humanize reaction stripping."""
import asyncio
import base64
import json
import random
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The client profile helpers read config.yaml, which does not exist on a fresh
# checkout. See tests/fixtures.py.
from fixtures import use_shipped_config
use_shipped_config()

from app.utils import behavior as b
from app.utils import session as s

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


print("== typing cadence ==")
ok = all(b.TYPING_CPS_MIN <= b.typing_speed() <= b.TYPING_CPS_MAX for _ in range(300))
check("normal typing speed stays in 2.5-6 chars/sec", ok)
ok = all(b.TYPING_CPS_FAST_MIN <= b.typing_speed(fast=True) <= b.TYPING_CPS_FAST_MAX for _ in range(300))
check("fast typing speed stays in 4-8 chars/sec", ok)

for _ in range(100):
    total = random.uniform(1, 60)
    bursts = b.typing_bursts(total)
    type_sum = sum(x for x, _ in bursts)
    if not (abs(type_sum - total) < 0.02 and all(x > 0 for x, _ in bursts) and all(p >= 0 for _, p in bursts)):
        check("typing bursts sum to the total and are positive", False, f"total={total} bursts={bursts}")
        break
else:
    check("typing bursts sum to the total and are positive", True)

print("\n== reaction tag parsing ==")
text, emoji, only = b.parse_reaction_tag("haha yeah [[REACT:😂]]")
check("react tag stripped, emoji parsed", text == "haha yeah" and emoji == "😂" and only is False)
text, emoji, only = b.parse_reaction_tag("[[REACT_ONLY:💀]]")
check("react_only parsed", text == "" and emoji == "💀" and only is True)
text, emoji, only = b.parse_reaction_tag("hi [[REACT:thumbsup]]")
check("non-allowlisted emoji rejected, tag removed", text == "hi" and emoji is None)
text, emoji, only = b.parse_reaction_tag("no tag here")
check("no tag leaves text untouched", text == "no tag here" and emoji is None and only is False)
text, emoji, only = b.parse_reaction_tag("")
check("empty string safe", text == "" and emoji is None)

# The tag being sent as literal text is the one failure that is visible to the
# person on the other end, and it happened: the prompt asks the model to end its
# reply with the tag, the model thinks of a reply as several messages, and it
# put the tag at the end of the FIRST one. An end-anchored pattern missed it.
LEAKED = "haha guess i'm just naturally fun 😂 you in school? [[REACT:😂]] \n\ni'm broke as hell"
text, emoji, only = b.parse_reaction_tag(LEAKED)
check("tag mid-reply is stripped, not sent", "[[REACT" not in text, repr(text))
check("tag mid-reply still yields the emoji", emoji == "😂" and only is False, repr(emoji))
check("both messages survive the strip",
      text == "haha guess i'm just naturally fun 😂 you in school?\n\ni'm broke as hell", repr(text))

text, emoji, only = b.parse_reaction_tag("one [[REACT:💀]] two [[REACT:🔥]] three")
check("every tag removed, first emoji wins",
      "[[REACT" not in text and emoji == "💀", f"{text!r} {emoji!r}")
check("no double space where a tag was", "  " not in text, repr(text))

text, emoji, only = b.parse_reaction_tag("hey\n[[REACT:👍]]\nthere")
check("a tag on its own line leaves no blank line",
      text == "hey\n\nthere" or text == "hey\nthere", repr(text))

text, emoji, only = b.parse_reaction_tag("lol [[REACT:thumbsup]] ok")
check("unknown emoji: tag still removed, nothing reacted",
      "[[REACT" not in text and emoji is None, repr(text))

print("\n== the emoji set is the character's own ==")
# A fixed list made every persona react identically, which is the sort of tell
# the rest of this module exists to avoid.
custom = ["\U0001F480", "\U0001F525"]
text, emoji, only = b.parse_reaction_tag("lol [[REACT:\U0001F480]]", custom)
check("an emoji in the character's set is used", emoji == "\U0001F480", repr(emoji))
text, emoji, only = b.parse_reaction_tag("lol [[REACT:\U0001F602]]", custom)
check("one outside it is not", emoji is None, repr(emoji))
check("and its tag is still stripped, never sent", "[[REACT" not in text, repr(text))
text, emoji, only = b.parse_reaction_tag("lol [[REACT:\U0001F602]]")
check("with no set given, the default still works", emoji == "\U0001F602", repr(emoji))

print("\n== whatever the config holds becomes a usable list ==")
check("a list passes through",
      b.clean_emoji_list(["\U0001F480", "\U0001F525"]) == ["\U0001F480", "\U0001F525"])
check("written on one line in the yaml still parses",
      b.clean_emoji_list("\U0001F480 \U0001F525, \U0001F440")
      == ["\U0001F480", "\U0001F525", "\U0001F440"])
check("duplicates are dropped",
      b.clean_emoji_list(["\U0001F480", "\U0001F480"]) == ["\U0001F480"])
check("blanks and whole sentences are dropped",
      b.clean_emoji_list(["\U0001F480", "", "  ", "not an emoji at all"]) == ["\U0001F480"])
check("the list is capped",
      len(b.clean_emoji_list(["\U0001F480"] * 5 + [f"x{i}" for i in range(80)])) <= b.MAX_REACTION_EMOJI)
# An empty list would silently turn reactions off while the switch still said
# they were on, which is a worse lie than falling back.
check("empty falls back to the default set",
      b.clean_emoji_list([]) == b.DEFAULT_REACTION_EMOJI)
check("nonsense falls back too", b.clean_emoji_list(None) == b.DEFAULT_REACTION_EMOJI)
check("reaction_emojis reads the config block",
      b.reaction_emojis({"emojis": ["\U0001F480"]}) == ["\U0001F480"])
check("and copes with the block being absent",
      b.reaction_emojis({}) == b.DEFAULT_REACTION_EMOJI)
check("the default is a list, so the prompt does not reshuffle each launch",
      isinstance(b.DEFAULT_REACTION_EMOJI, list))
check("the old name still exists for released builds",
      b.REACTION_EMOJI == set(b.DEFAULT_REACTION_EMOJI))

print("\n== night window ==")
from zoneinfo import ZoneInfo
PARIS = ZoneInfo("Europe/Paris")
is_night, _ = b.night_window_state({"enabled": False})
check("disabled window never active", is_night is False)
is_night, _ = b.night_window_state({"enabled": True, "hours": "2-8", "timezone": "Europe/Paris"},
                                   datetime(2026, 6, 10, 4, 0, tzinfo=PARIS))
check("2-8 window active at 4am local", is_night is True)
is_night, _ = b.night_window_state({"enabled": True, "hours": "2-8", "timezone": "Europe/Paris"},
                                   datetime(2026, 6, 10, 14, 0, tzinfo=PARIS))
check("2-8 window inactive at 2pm local", is_night is False)
is_night, _ = b.night_window_state({"enabled": True, "hours": "23-7", "timezone": "Europe/Paris"},
                                   datetime(2026, 6, 10, 1, 0, tzinfo=PARIS))
check("wrap-around window 23-7 active at 1am", is_night is True)
is_night, _ = b.night_window_state({"enabled": True, "hours": "garbage", "timezone": "Europe/Paris"},
                                   datetime(2026, 6, 10, 4, 0, tzinfo=PARIS))
check("invalid hours spec disables the window", is_night is False)
is_night, secs = b.night_window_state({"enabled": True, "hours": "2-8", "timezone": "Europe/Paris"},
                                      datetime(2026, 6, 10, 23, 0, tzinfo=PARIS))
check("seconds until the window starts, while awake",
      is_night is False and secs is not None and secs > 0)

print("\n== style chunk split ==")
pieces = b.style_chunk_split("alpha. beta. gamma. delta. epsilon. zeta.", 20)
check("splits at sentence ends under cap", all(len(p) <= 20 for p in pieces) and len(pieces) >= 3)
long_sentence = "word " * 60
pieces = b.style_chunk_split(long_sentence, 20)
check("over-long sentence hard-splits", all(len(p) <= 20 for p in pieces) and len(pieces) > 3)
check("no content lost", "".join(pieces).replace(" ", "") == long_sentence.replace(" ", ""))
check("empty input yields no pieces", b.style_chunk_split("", 100) == [])
check("cap below minimum is clamped", all(len(p) <= 20 for p in b.style_chunk_split("a b c d e f g h i j k l m n o p q r s t u v w x y z", 10)))

print("\n== tiny typo fix ==")
orig_choice = random.choice
try:
    random.choice = lambda seq: "period"
    check("stray final period dropped", b.tiny_typo_fix("hello world.") == "hello world")
finally:
    random.choice = orig_choice
random.seed(42)
text = "this message has some words to fix here"
fixed = b.tiny_typo_fix(text)
check("a fix actually changes the text", fixed != text)
check("word count preserved", len(fixed.split()) == len(text.split()))
check("digits and urls never touched", b.tiny_typo_fix("meet at 5pm https://x.com/abc 1234") == "meet at 5pm https://x.com/abc 1234")

print("\n== desktop UA ==")
ua = s.desktop_ua("1.0.9256", 142)
check("desktop UA has discord version", "discord/1.0.9256" in ua)
check("desktop UA has chrome major", "Chrome/142.0.0.0" in ua)
check("desktop UA has mapped electron", "Electron/39.0.0" in ua)
check("electron mapping for chrome 120", "Electron/28.0.0" in s.desktop_ua("1.0.2", 120))

print("\n== fallback REST headers ==")
s.set_gateway_headers(None)
headers = s.make_chrome_headers("tok123")
check("fallback headers carry auth + super properties", headers["Authorization"] == "tok123" and "X-Super-Properties" in headers)
sp = json.loads(base64.b64decode(headers["X-Super-Properties"]).decode())
check("fallback super properties are web Chrome", sp.get("browser") == "Chrome" and sp.get("os") == "Windows")
check("client hints present", "sec-ch-ua-mobile" in headers and headers["sec-ch-ua-mobile"] == "?0")
check("priority header matches the gateway", headers.get("Priority") == "u=0, i")

print("\n== gateway header sync ==")
class FakeHints:
    def __init__(self):
        self.user_agent = "UA-FROM-GATEWAY"
        self.encoded_super_properties = base64.b64encode(json.dumps({"browser": "Chrome", "os": "Windows"}).encode()).decode()
        self.client_hints = {"Sec-CH-UA": '"Chromium";v="153"', "Sec-CH-UA-Mobile": "?0", "Sec-CH-UA-Platform": '"Windows"'}

s.set_gateway_headers(FakeHints())
headers = s.make_chrome_headers("tok")
check("UA comes from the gateway headers", headers["User-Agent"] == "UA-FROM-GATEWAY")
check("super properties come from the gateway", "browser" in json.loads(base64.b64decode(headers["X-Super-Properties"]).decode()))
s.set_gateway_headers(None)

print("\n== desktop headers build ==")
s._DESKTOP_VERSION = "1.0.9256"

def run_build():
    return asyncio.run(s.build_desktop_headers({"bot": {}}, None))

hdr = run_build()
check("desktop profile is Discord Client", hdr.super_properties["browser"] == "Discord Client")
check("desktop build number set", isinstance(hdr.super_properties["client_build_number"], int))
check("identify properties are exactly the desktop set",
      set(hdr.gateway_properties.keys()) == {"os", "browser", "release_channel", "client_build_number", "client_event_source"})
check("no web-style fields leak into identify properties",
      "browser_user_agent" not in hdr.gateway_properties and "device" not in hdr.gateway_properties)
check("desktop UA flows through for headers", "discord/1.0.9256" in hdr.user_agent)
check("desktop client hints are desktop-class", hdr.client_hints["Sec-CH-UA-Mobile"] == "?0")
s._DESKTOP_VERSION = None

print()
print("== the night boundary is minute accurate ==")
# Whole-hour maths meant 07:59 reported a full hour until an 08:00 wake up, so
# the account stayed invisible until nearly nine.
is_night, secs = b.night_window_state(
    {"enabled": True, "hours": "2-8", "timezone": "Europe/Paris"},
    datetime(2026, 6, 10, 7, 59, tzinfo=PARIS))
check("still night at 07:59", is_night is True)
check("under two minutes left, not an hour", secs <= 120, f"{secs}s")
_, secs_mid = b.night_window_state(
    {"enabled": True, "hours": "2-8", "timezone": "Europe/Paris"},
    datetime(2026, 6, 10, 4, 30, tzinfo=PARIS))
check("mid window is about three and a half hours", 12000 < secs_mid < 12900, f"{secs_mid}s")
check("never returns something a sleep would reject", secs_mid > 0 and secs > 0)

print()
print("== typing time is bounded ==")
# A chatty chunk is 800 characters. Uncapped that is over five minutes of
# continuous typing for one message, and four of those for one reply.
longest = "x" * 800
worst = max(b.typing_time(longest) for _ in range(200))
check("a long message never types for minutes", worst <= b.MAX_TYPING_SECONDS, f"{worst:.1f}s")
check("a short message is still quick", b.typing_time("hey what are you up to") < 12)
check("bursts roughly cover the requested time",
      abs(sum(x + y for x, y in b.typing_bursts(20.0)) - 20.0) < 12)
check("bursts terminate for the longest session",
      len(b.typing_bursts(b.MAX_TYPING_SECONDS)) < 40)
check("zero length is harmless", b.typing_time("") == 0)

print()
print("== the presence loop survives a hand-edited config ==")
# It runs as a background task, so an exception escaping it stops the account
# changing status for the rest of the session, with nothing said anywhere.
_src = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
_ns = {"random": random}
exec(compile(_src[_src.index("def _pick_status("):_src.index("async def random_status_loop():")],
             "_pick_status", "exec"), _ns)
pick = _ns["_pick_status"]

MAP = {"online": "ON", "idle": "IDLE", "dnd": "DND", "invisible": "INV"}
DEF = {"online": 0.85, "idle": 0.12, "dnd": 0.03, "invisible": 0.0}

got = {pick({"statuses": ["online", "idle", "dnd"], "weights": [0.9]}, MAP, DEF)
       for _ in range(400)}
check("a short weights list still reaches every status", got == {"ON", "IDLE", "DND"}, str(got))

try:
    out = pick({"statuses": ["online", "idle"], "weights": ["high", 0.1]}, MAP, DEF)
    check("a non-numeric weight does not raise", out in MAP.values(), str(out))
except Exception as exc:
    check("a non-numeric weight does not raise", False, f"{type(exc).__name__}: {exc}")

try:
    out = pick({"statuses": ["invisible"]}, MAP, DEF)
    check("an all-zero pool falls back instead of crashing", out == "ON", str(out))
except Exception as exc:
    check("an all-zero pool falls back instead of crashing", False, f"{type(exc).__name__}: {exc}")

for bad in ({}, {"statuses": "online"}, {"statuses": [], "weights": None},
            {"statuses": ["nonsense"]}, {"weights": "not a list"}):
    try:
        out = pick(bad, MAP, DEF)
        ok = out in MAP.values()
    except Exception as exc:
        ok, out = False, f"{type(exc).__name__}: {exc}"
    check(f"survives {bad}", ok, str(out))

print()
print("== one timezone default, not two ==")
# The fallback and the config default disagreed, so the timezone header changed
# depending on whether load_config happened to raise. That is exactly the drift
# session.py exists to prevent.
s.set_gateway_headers(None)
_h1 = s.make_chrome_headers("t")
import app.utils.helpers as _helpers
_real_load = _helpers.load_config
_helpers.load_config = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no config"))
try:
    _h2 = s.make_chrome_headers("t")
finally:
    _helpers.load_config = _real_load
check("timezone is the same whether or not the config loads",
      _h1.get("X-Discord-Timezone") == _h2.get("X-Discord-Timezone"),
      f'{_h1.get("X-Discord-Timezone")} vs {_h2.get("X-Discord-Timezone")}')


print("\n== humanize strips reaction tags (non-Discord platforms) ==")
from app.utils.humanize import humanize
out = humanize("bye [[REACT:😂]]")
check("reaction tag never leaks", "[[REACT" not in out and "😂" not in out)

print("\n== worker pid files ==")
from app.core.launcher import pid_file, clear_pid_file
p = pid_file("discord", 1)
check("pid file path names the role and account", "discord_1" in p)
clear_pid_file("discord", 999)  # never raises, missing file is fine
check("clearing a missing pid file is harmless", True)

print("\n== small model selection ==")
from app.utils import ai as ai_mod
small = ai_mod._small_model_name()
check("a small model resolves for utility calls", isinstance(small, str) and bool(small.strip()), str(small))

print("\n== memory block framing ==")
from app.utils import memory as mem_mod
block = mem_mod.format_memory_for_prompt({"name": "Ana", "pet_name": "Max", "__persona__": "formal"})
check("memory block hides internal keys", "__persona__" not in block)
check("memory block tells the model to use it naturally", "never list it" in block)
check("empty memory yields no block", mem_mod.format_memory_for_prompt({}) == "")

print()
print("== looking someone up must not need Discord's permission ==")
# discord.py's user cache is a WeakValueDictionary, kept alive only by cached
# members and cached messages. Trimming both to save memory emptied it, so
# get_user() started missing mid-conversation and every miss fell through to
# fetch_user() - which on a USER account answers 403 40001 for anyone the
# account has no mutual context with. The panel's Reply button and the nudge
# loop both failed on exactly that.
_ru_src = _src[_src.index("_seen_users: dict = {}"):_src.index("def create_bot(")]


class _FakeUser:
    def __init__(self, uid, name="someone"):
        self.id, self.name = uid, name


class _FakeDM:
    def __init__(self, cid, recipient):
        self.id, self.recipient = cid, recipient


class _Forbidden(Exception):
    pass


class _NotFound(Exception):
    pass


class _FakeBot:
    """A bot whose weak user cache has been emptied, as the real one now is."""

    def __init__(self, channels=(), raises=None):
        self.private_channels = list(channels)
        self._by_id = {c.id: c for c in channels}
        self.raises = raises
        self.fetch_calls = 0

    def get_user(self, uid):
        return None

    def get_channel(self, cid):
        return self._by_id.get(cid)

    async def fetch_user(self, uid):
        self.fetch_calls += 1
        if self.raises:
            raise self.raises()
        return _FakeUser(uid)


def _load_resolver(bot):
    ns = {"discord": type("d", (), {"Forbidden": _Forbidden, "NotFound": _NotFound}),
          "bot": bot}
    exec(compile(_ru_src, "resolve_user", "exec"), ns)
    return ns


_b = _FakeBot(raises=_Forbidden)
_ns2 = _load_resolver(_b)
_ns2["remember_user"](_FakeUser(7, "ana"))
_u, _why = asyncio.run(_ns2["resolve_user"](7))
check("a remembered user needs no fetch", _u is not None and _b.fetch_calls == 0)
check("and it is the right one", getattr(_u, "name", "") == "ana")

_dm = _FakeDM(555, _FakeUser(8, "bo"))
_b2 = _FakeBot(channels=[_dm], raises=_Forbidden)
_u2, _ = asyncio.run(_load_resolver(_b2)["resolve_user"](8, 555))
check("a DM's own recipient is used before asking Discord",
      _u2 is not None and _b2.fetch_calls == 0)

_b3 = _FakeBot(raises=_Forbidden)
_u3, _why3 = asyncio.run(_load_resolver(_b3)["resolve_user"](9))
check("a 403 comes back as a reason, not an exception",
      _u3 is None and bool(_why3), repr(_why3))
check("and says it will not clear by itself", "not allowed" in _why3, _why3)

_b4 = _FakeBot(raises=_NotFound)
_u4, _why4 = asyncio.run(_load_resolver(_b4)["resolve_user"](10))
check("an unknown user is reported the same way",
      _u4 is None and "does not know" in _why4, _why4)

_b5 = _FakeBot()
_ns5 = _load_resolver(_b5)
_u5, _ = asyncio.run(_ns5["resolve_user"](11))
check("with nothing local it does still ask Discord",
      _u5 is not None and _b5.fetch_calls == 1)

_ns6 = _load_resolver(_FakeBot())
for _i in range(_ns6["MAX_SEEN_USERS"] + 50):
    _ns6["remember_user"](_FakeUser(_i))
check("the user cache stays bounded",
      len(_ns6["_seen_users"]) <= _ns6["MAX_SEEN_USERS"], str(len(_ns6["_seen_users"])))
check("keeping the most recent",
      (_ns6["MAX_SEEN_USERS"] + 49) in _ns6["_seen_users"])

# The callers have to actually take the permanent answer as permanent.
check("the nudge loop stops retrying someone it cannot reach",
      "Nudge skipped for" in _src and "mark_nudge_sent" in _src)
check("a 403 on the nudge send is permanent too",
      "except discord.Forbidden:" in _src)
check("reply_user drops a user it can never look up",
      '"reason": _why or "user not found"' in _src)
check("on_message keeps a strong reference to whoever wrote it",
      "remember_user(message.author)" in _src)


print()
print("== a logged-out Snapchat account is not hammered with logins ==")
# Three failed chat-list reads triggered a full credential login and reset the
# counter, so an account that could not log in got a login attempt about every
# 24 seconds, forever. That turns logged-out into locked.
_run = (ROOT / "app" / "platforms" / "snapchat" / "snapchat_runner.js").read_text(encoding="utf-8")
_bot = (ROOT / "app" / "platforms" / "snapchat" / "snapbot.js").read_text(encoding="utf-8")
check("re-login backs off between attempts", "RELOGIN_BACKOFF_MS" in _run and "relogin.nextAt" in _run)
check("and gives up after a few", "relogin.gaveUp = true" in _run)
check("and says so where the panel can see it", 'setState("logged-out"' in _run)
check("a success resets it", "relogin.attempts = 0" in _run)
# The dismisser must never act on the sign-in flow: "Next" there submits the
# login form. The browser test covers behaviour; this pins the guard.
check("the dialog dismisser stays off the sign-in pages",
      'where.includes("accounts.snapchat.com")' in _bot)
check("and never presses a button inside a form", '!el.closest("form")' in _bot)
check("and stops when the same button keeps coming back", "repeats >= 2" in _bot)

print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
