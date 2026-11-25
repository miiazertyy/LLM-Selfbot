"""Codes from the owner's mail, typed where a social asks, and a person told at once when only they can do something
(app/utils/mailcodes.py, app/web/attention.py; 2026-11-11).

Everything here is made up: the mailboxes are a stand-in that answers like an IMAP server, the emails are written the
way each social writes its own. What matters most is what is not done: only the social's own messages are opened, the
mailbox is never changed, a code that is not clear is not typed, and a password never comes back out.
"""
import asyncio
import imaplib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import use_shipped_config  # noqa: E402

sandbox = use_shipped_config()

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.utils import mailcodes  # noqa: E402
from app.web import attention  # noqa: E402
from app.web.routes import mail_routes  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def mail(sender, subject, body, html=False):
    kind = "text/html" if html else "text/plain"
    return (f"From: {sender}\r\nSubject: {subject}\r\nContent-Type: {kind}; charset=utf-8\r\n\r\n{body}").encode("utf-8")


print("== the code in each social's email ==")
emails = {
    "instagram": ("123456 is your Instagram code", "Hi,\nSomeone tried to log in to your Instagram account.\n\n123456\n\nIf this was you, enter this code.", "123456"),
    "x": ("Your X confirmation code is 4hdk2pqx", "Please enter this verification code to get started on X: 4hdk2pqx\nX Corp. 1355 Market Street", "4hdk2pqx"),
    "reddit": ("Your Reddit verification code", "Here is your verification code: 482913\nThis code expires in 10 minutes. Reddit Inc, 2025", "482913"),
    "tiktok": ("Your verification code", "<p>Verification code</p><p style='font-size:24px'>739104</p><p>Copyright 2026</p>", "739104"),
}
for platform, (subject, text, want) in emails.items():
    got = mailcodes.extract(subject, mailcodes._text_of(__import__("email").message_from_bytes(mail("x@y.z", subject, text, html="<p" in text))))
    check(f"{platform}: {want}", got == want, repr(got))
check("a link only, no code: nothing typed", mailcodes.extract("Verify your email", "Click https://reddit.com/verify?t=12345678 to verify. Copyright 2024") == "")
check("a year is not a code", mailcodes.extract("Welcome", "Thanks for joining in 2026. Your code is coming soon.") == "")
check("two that look alike: not a guess worth typing", mailcodes.extract("Codes", "Code: 111111 or code: 222222") == "")
check("a code spoken of before it", mailcodes.extract("", "Enter 5821 to confirm.") == "5821")

print("\n== the model, only for that one message, and only what is in it ==")
asked = []


def fake_run(answer):
    def run(coro):
        coro.close()
        asked.append(answer)
        return answer
    return run


check("its answer is taken when it is in the message",
      mailcodes.ask_model("instagram", "Your login", "Use the code below to verify: 88a1 ... 77k3x9", run=fake_run("77k3x9")) == "77k3x9")
check("an answer that is not in the message is not taken",
      mailcodes.ask_model("instagram", "Your login", "Use this code: 554433", run=fake_run("999999")) == "")
check("NONE is nothing", mailcodes.ask_model("instagram", "Your code", "your code", run=fake_run("NONE")) == "")
n = len(asked)
check("no code spoken of at all: it is not even asked", mailcodes.ask_model("instagram", "Hello", "A new follower", run=fake_run("x1")) == "" and len(asked) == n)

print("\n== a mailbox, read-only ==")


class FakeBox:
    """Answers like an IMAP server holding a few messages, and remembers everything it was asked."""

    def __init__(self, held):
        self.held = held            # (folder, uid, sender, subject, body, internaldate)
        self.calls = []
        self.folder = None

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Junk) "/" "Spam"', b'(\\HasNoChildren) "/" "Work"']

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        self.folder = folder.strip('"')
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.calls.append(("uid", command) + tuple(str(a) for a in args))
        if command == "SEARCH":
            sender = args[-1].strip('"')
            found = [m[1] for m in self.held if m[0] == self.folder and sender in m[2]]
            return "OK", [" ".join(found).encode()]
        if command == "FETCH":
            for m in self.held:
                if m[0] == self.folder and m[1] == args[0]:
                    stamp = time.strftime('"%d-%b-%Y %H:%M:%S +0000"', time.gmtime(m[5]))
                    meta = f'{m[1]} (UID {m[1]} INTERNALDATE {stamp} RFC822.SIZE 300 BODY[] {{300}}'.encode()
                    return "OK", [(meta, mail(m[2], m[3], m[4]))]
        return "OK", [None]

    def logout(self):
        self.calls.append(("logout",))


now = time.time()
held = [
    ("INBOX", "11", "Instagram <security@mail.instagram.com>", "111111 is your Instagram code", "111111", now - 3600),
    ("INBOX", "12", "Bank <alerts@mybank.example>", "Your code 999999", "999999", now - 10),
    ("Spam", "13", "Instagram <security@mail.instagram.com>", "246810 is your Instagram code", "Your code\n\n246810\n", now - 5),
    ("Work", "14", "Instagram <security@mail.instagram.com>", "135790 is your Instagram code", "135790", now - 4),
]
fake = FakeBox(held)
time.mktime(time.gmtime())
found = mailcodes.find_code("instagram", now - 30, boxes=[{"address": "me@example.test", "password": "pw", "server": "imap.example.test:993"}],
                            opener=lambda *a: fake, model=lambda *a: "")
check("the new code is found, in the spam folder too", found == {"code": "246810", "address": "me@example.test"}, str(found))
selects = [c for c in fake.calls if c[0] == "select"]
check("every folder opened read-only, so nothing is marked read", selects and all(c[2] is True for c in selects), str(selects))
check("only the inbox and spam are looked in", {c[1].strip('"') for c in selects} == {"INBOX", "Spam"}, str(selects))
searches = [c for c in fake.calls if c[:2] == ("uid", "SEARCH")]
check("only the social's own messages are looked for", searches and all("instagram.com" in c[-1] or "facebookmail.com" in c[-1] for c in searches), str(searches))
fetched = [c for c in fake.calls if c[:2] == ("uid", "FETCH")]
check("the bank's message is never opened", all(c[2] != "12" for c in fetched), str(fetched))
check("what is fetched is peeked at, not read", all("BODY.PEEK[]" in c[3] for c in fetched), str(fetched))
check("nothing changes the mailbox: no STORE, COPY, MOVE or EXPUNGE",
      not [c for c in fake.calls if c[0] == "uid" and c[1] in ("STORE", "COPY", "MOVE", "EXPUNGE")])
check("an hour-old code is not taken", found["code"] != "111111")
check("and the connection is closed", fake.calls[-1] == ("logout",))
again = mailcodes.find_code("instagram", now - 30, boxes=[{"address": "me@example.test", "password": "pw", "server": "s:993"}],
                            opener=lambda *a: FakeBox(held), model=lambda *a: "")
check("the same code is never typed twice", again is None or again["code"] != "246810", str(again))
seen = json.loads((sandbox / "cache" / "mail_codes.json").read_text(encoding="utf-8"))
check("when it gave a code is kept, never the code", seen.get("me@example.test", {}).get("platform") == "instagram"
      and "246810" not in json.dumps(seen), str(seen))


def refuses(*a):
    raise mailcodes.MailError("The password was refused.")


check("a mailbox that won't open is skipped, not a crash",
      mailcodes.find_code("x", now, boxes=[{"address": "a@b.c", "password": "p", "server": "s"}], opener=refuses, model=lambda *a: "") is None)
check("one with no server found yet is skipped", mailcodes.find_code("x", now, boxes=[{"address": "a@b.c", "password": "p", "server": ""}],
                                                                       opener=lambda *a: 1 / 0, model=lambda *a: "") is None)
mailcodes.EVERY_S = 0.01
t = time.time()
check("waiting has an end", mailcodes.wait_for_code("x", now, wait_s=0.2, boxes=[], model=lambda *a: "") is None and time.time() - t < 3)
check("and can be told to stop", mailcodes.wait_for_code("x", now, wait_s=30, stop=lambda: True, boxes=[]) is None)

print("\n== finding how to reach a mailbox ==")
check("the big providers are known", mailcodes.discover("a@gmail.com")["server"] == "imap.gmail.com:993"
      and "app password" in mailcodes.discover("a@gmail.com")["note"])
check("one with no way in for mail apps says so", mailcodes.discover("a@proton.me")["server"] == "" and "Bridge" in mailcodes.discover("a@proton.me")["note"])
answers = {}


class Answer:
    def __init__(self, text="", status=200, data=None):
        self.text, self.status_code, self._data = text, status, data

    def json(self):
        return self._data


def fake_http(url, timeout=8.0, headers=None):
    for part, answer in answers.items():
        if part in url:
            return answer
    return Answer("", 404)


real_http = mailcodes._ipv4_http
mailcodes._ipv4_http = fake_http
answers = {"thunderbird.net/v1.1/example.org": Answer('<clientConfig><emailProvider><incomingServer type="imap"><hostname>mail.%EMAILDOMAIN%</hostname>'
                                                       '<port>143</port><socketType>STARTTLS</socketType></incomingServer><incomingServer type="imap">'
                                                       '<hostname>imap.example.org</hostname><port>993</port><socketType>SSL</socketType></incomingServer>'
                                                       '</emailProvider></clientConfig>')}
check("Thunderbird's list, the TLS one first", mailcodes.discover("a@example.org") == {"server": "imap.example.org:993", "note": "", "found": "Thunderbird's list"})
answers = {"dns-query?name=shop.example": Answer(data={"Answer": [{"data": "20 alt1.aspmx.l.google.com."}, {"data": "10 aspmx.l.google.com."}]})}
got = mailcodes.discover("a@shop.example")
check("a domain of its own on Google: found by where its mail goes", got["server"] == "imap.gmail.com:993" and got["found"] == "where its mail goes", str(got))
answers = {}
check("nothing found: a guess, said to be one", mailcodes.discover("a@nowhere.example") == {"server": "imap.nowhere.example:993", "note": "", "found": "a guess"})
mailcodes._ipv4_http = real_http
src = (ROOT / "app" / "utils" / "mailcodes.py").read_text(encoding="utf-8")
check("over IPv4 first, where IPv6 stalls here", 'local_address="0.0.0.0"' in src and "socket.AF_INET" in src)
# 2026-11-11: through the app's one context (app/utils/tls.py), certifi's list beside Windows' own, which also has
# the root an antivirus or a company proxy adds when it checks mail connections.
_tls = (ROOT / "app" / "utils" / "tls.py").read_text(encoding="utf-8")
check("certificates checked with the app's own list, beside the system's", "tls.context()" in src
      and "ssl.create_default_context()" in _tls and "ctx.load_verify_locations(certifi.where())" in _tls)

print("\n== the mailboxes in Settings ==")
app = FastAPI()
app.include_router(mail_routes.router)
client = TestClient(app)
PANEL = {"x-llmselfbot": "1"}
check("not the panel: refused", client.get("/api/mail").status_code == 403)
check("not an address: refused", client.post("/api/mail", json={"address": "nope", "password": "x"}, headers=PANEL).status_code == 400)
check("no password: refused", client.post("/api/mail", json={"address": "a@b.co", "password": ""}, headers=PANEL).status_code == 400)
real_try = mail_routes._try
mail_routes._try = lambda address, password, server: {"ok": False, "reason": "The password was refused.", "server": "imap.gmail.com:993",
                                                      "note": "Gmail takes an app password here", "found": "known"}
r = client.post("/api/mail", json={"address": "me@gmail.com", "password": "secret-made-up-1"}, headers=PANEL).json()
check("one that won't open is not kept, and says why and what it wants", not r["ok"] and "app password" in r["note"]
      and "MAIL_1" not in (sandbox / "config" / ".env").read_text(encoding="utf-8"), str(r))
mail_routes._try = lambda address, password, server: {"ok": True, "server": server or "imap.gmx.net:993", "note": "", "found": "known"}
r = client.post("/api/mail", json={"address": "me@gmx.net", "password": "secret-made-up-2"}, headers=PANEL).json()
env = (sandbox / "config" / ".env").read_text(encoding="utf-8")
check("one that opens is kept, its password with the other secrets", r["ok"] and "MAIL_1=me@gmx.net" in env
      and "MAIL_PASSWORD_1=secret-made-up-2" in env and "MAIL_SERVER_1=imap.gmx.net:993" in env, env)
from app.web.envfile import SECRET_KEYS  # noqa: E402
check("the password counts as a secret, so the Keys page masks it", SECRET_KEYS.match("MAIL_PASSWORD_1") is not None)
listed = client.get("/api/mail", headers=PANEL).json()
check("listed with no password in sight", listed["mailboxes"][0]["address"] == "me@gmx.net" and "secret-made-up-2" not in json.dumps(listed), str(listed))
check("the same one twice: refused", client.post("/api/mail", json={"address": "ME@gmx.net", "password": "x"}, headers=PANEL).status_code == 400)
check("a server put in by hand is checked for shape", client.post("/api/mail", json={"address": "b@c.de", "password": "x", "server": "a b"}, headers=PANEL).status_code == 400)
r = client.post("/api/mail", json={"address": "b@c.de", "password": "p2", "server": "imap.c.de:993"}, headers=PANEL).json()
check("the next one takes the next number", r["ok"] and r["index"] == 2 and r["server"] == "imap.c.de:993", str(r))
check("removed: gone from the file", client.delete("/api/mail/1", headers=PANEL).status_code == 200
      and "MAIL_PASSWORD_1" not in (sandbox / "config" / ".env").read_text(encoding="utf-8"))
check("removing one that is not there: 404", client.delete("/api/mail/9", headers=PANEL).status_code == 404)
mail_routes._try = real_try
check("found again by the reader", [b["address"] for b in mailcodes.mailboxes()] == ["b@c.de"])

print("\n== a person told at once ==")
told, notified = [], []
from app.web import logbus  # noqa: E402
real_event, real_append = logbus.bus.event, logbus.bus.append
logbus.bus.event = lambda kind, payload: told.append((kind, payload))
logbus.bus.append = lambda *a, **k: None
import app.tray as tray  # noqa: E402
real_notify = tray.notify
tray.notify = lambda text, title="": notified.append((title, text))
check("a check: said", attention.raised("instagram_1", "captcha", now=1000.0))
check("  to the panel, at once", told[-1][0] == "attention" and told[-1][1]["id"] == "instagram_1" and "Solve it" in told[-1][1]["text"], str(told[-1]))
check("  and by the clock", notified[-1] == ("Instagram needs you", "Instagram put up a check. Solve it in its window."), str(notified))
check("the same again a moment later: not said twice", attention.raised("instagram_1", "captcha", now=1030.0) is False)
check("a while later: said again", attention.raised("instagram_1", "captcha", now=1000.0 + attention.QUIET_S + 1))
n = len(notified)
check("looking in the mail: said in the panel", attention.raised("x_1", "code_mail", now=5000.0) and told[-1][1]["what"] == "code_mail")
check("  but it is the app's own work: no Windows notice for it", len(notified) == n)
check("Discord's own words for its captcha", "Discord app" in attention.text_for("discord", "captcha"))
check("Snapchat's email check", "Snapchat" in attention.text_for("snapchat", "verify"))
check("anything else is not a person's job", attention.raised("x_1", "nonsense") is False)
logbus.bus.event, logbus.bus.append = real_event, real_append
tray.notify = real_notify

print("\n== where it is wired in ==")
bridge = (ROOT / "app" / "platforms" / "snapchat_bridge.py").read_text(encoding="utf-8")
check("a code asked for is looked for in the mailboxes first", 'if PLATFORM in _MAIL_CODES and _has_mailboxes():' in bridge
      and '_spawn_panel(_code_from_mail(time.time()))' in bridge)
check("  for the three that ask for one in the page", '_MAIL_CODES = ("instagram", "x", "reddit")' in bridge)
check("  typed through the same door as one typed in the panel", 'r = await _panel("code", timeout=20.0, code=found["code"])' in bridge)
check("  never logging the code", 'f"Typed the code {PLATFORM_NAME} emailed, found in {found[\'address\']}"' in bridge)
check("  and not found: the person is asked, as before", bridge.count("_ask_for_code()") >= 2)
check("  the model asked on the account's own loop", "asyncio.run_coroutine_threadsafe(coro, loop)" in bridge)
routes = (ROOT / "app" / "web" / "routes" / "chat_routes.py").read_text(encoding="utf-8")
check("what a runner asks a person for is no longer dropped", "attention.raised(web_id, str(evt.get(\"what\") or \"\"))" in routes)
snap = (ROOT / "app" / "platforms" / "snapchat" / "snapchat_runner.js").read_text(encoding="utf-8")
check("Snapchat's email check is said", snap.count('tellPython({ kind: "attention", what: "verify" });') == 2)
discord_src = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("Discord's captcha is said, wherever it comes from", "except discord.CaptchaRequired:" in discord_src
      and 'emit_chat_event({"t": "attention", "what": "captcha"})' in discord_src and "\n_watch_for_captchas()\n" in discord_src)
acct = (ROOT / "app" / "web" / "routes" / "account_routes.py").read_text(encoding="utf-8")
x_route = acct.split('@router.post("/api/accounts/x/sign-in/code")')[1].split("@router")[0]
check("X's codes keep their letters when typed in the panel", "ch.isalnum()" in x_route)
web = ROOT / "webui" / "src"
ny = (web / "lib" / "components" / "NeedsYou.svelte").read_text(encoding="utf-8")
check("the card listens for it, and goes when the account is past it", 'subscribeEvents("attention"' in ny and 'play("done")' in ny
      and "waiting(row.web?.state)" in ny)
check("on every page", "<NeedsYou />" in (web / "App.svelte").read_text(encoding="utf-8"))
check("put away by hand, it stays away until the account asks again", "dismissed.add(keyOf(a))" in ny
      and "dismissed.has(keyOf({ id: r.id, what }))" in ny and "dismissed.delete(keyOf(" in ny)
check("the mailboxes have their place in Settings", 'panel: "mail"' in (web / "lib" / "settingsmap.ts").read_text(encoding="utf-8")
      and "<MailboxesPanel />" in (web / "pages" / "Settings.svelte").read_text(encoding="utf-8"))
# 2026-11-11: it was a flat brown slab across the sidebar's rail and the page heading ("looking ugly").
_card = ny.split("  .ny-card {", 1)[1].split("}", 1)[0]
check("the card is the theme's, lifted off the page, its warning colour only on a badge on the site's mark",
      "color-mix(in srgb, var(--color-accent) 6%, var(--color-card))" in _card and "box-shadow" in _card
      and "var(--tone) 16%" not in ny and 'class="ny-badge"' in ny)
check("and it keeps clear of the sidebar's rail in a narrow window", "width: min(340px, calc(100vw - 6rem));" in ny)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
