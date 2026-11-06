"""iMessage with no Mac: through an iPhone or iPad.

iMessage only runs on Apple's own machines. With a Mac, BlueBubbles carries the messages (tests/test_imessage.py).
Without one, the phone itself can: a Shortcuts automation on it (Messages, from anybody, run immediately) posts each
message it gets to the panel's /relay/imessage/<secret>, and sends back to whoever wrote whatever comes back. The
account's worker answers it as it answers through a Mac - the persona, its memory, the conversation, the chat log -
with no runner at all.

Run here: the account and its secret, the relay's door (the secret, the test page, what a shortcut may send),
the ids people get, and the bridge's, the panel's and the pages' parts, read from the source. The whole way through,
panel and worker and model, is scratch's phone_proof.py: an answer in 7 to 9 seconds, several in a row answered once.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="llmbot_imsg_phone_"))
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(ROOT))
(DATA / "config").mkdir(parents=True, exist_ok=True)
(DATA / "ipc").mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
for k in [k for k in os.environ if k.startswith("IMESSAGE_")]:
    os.environ.pop(k, None)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== the account ==")
from app.web.routes import account_routes  # noqa: E402

b = {"server": "phone", "password": "whatever", "relay": "one-of-mine"}
account_routes._imessage_body(b)
check("the iPhone way: no address, no password, and a secret of its own made for it, never one sent in",
      b["server"] == "phone" and b["password"] == "" and len(b["relay"]) >= 24 and b["relay"] != "one-of-mine", b)
b2 = {"server": "PHONE"}
account_routes._imessage_body(b2)
check("each its own", b2["relay"] != b["relay"] and b2["server"] == "phone")
b3 = {"server": "192.168.1.20", "relay": "sneaked"}
account_routes._imessage_body(b3)
check("a Mac's is an address as before, and takes no relay secret", b3["server"] == "http://192.168.1.20:1234"
      and "relay" not in b3, b3)
slots = account_routes._slots({"IMESSAGE_SERVER_1": "phone", "IMESSAGE_RELAY_1": "s3cr3t-0123456789abcdef"})
check("listed as through the phone, with the secret its Setup page puts in the shortcut",
      slots[0]["server"] == "phone" and slots[0]["relay"] == "s3cr3t-0123456789abcdef" and "password" not in slots[0],
      slots)
src = read("app/web/routes/account_routes.py")
check("editing it keeps its secret; only a new one asked for replaces it",
      'renew = bool(body.pop("renew_relay", False))' in src
      and 'if was_phone and body.get("server") == "phone" and not renew:' in src)
from app.core import ipc  # noqa: E402

os.environ["IMESSAGE_SERVER_1"] = "phone"
os.environ["IMESSAGE_RELAY_1"] = "s3cr3t-0123456789abcdef"
check("counted as an account like a Mac's, and started the same", ipc._count_imessage_accounts() == 1)

print("\n== the door ==")
from app.web.routes import relay_routes  # noqa: E402

check("its secret opens it, and only its", relay_routes._account_for("s3cr3t-0123456789abcdef") == 1
      and relay_routes._account_for("s3cr3t-0123456789abcdeX") == 0 and relay_routes._account_for("") == 0
      and relay_routes._account_for("short") == 0)
os.environ["IMESSAGE_SERVER_2"] = "https://mac.example"
os.environ["IMESSAGE_RELAY_2"] = "mac-secret-0123456789abcdef"
check("a Mac's account takes no phone, whatever its relay says", relay_routes._account_for("mac-secret-0123456789abcdef") == 0)
check("compared in constant time", "hmac.compare_digest(" in read("app/web/routes/relay_routes.py"))


class FakeRequest:
    def __init__(self, body=b"", ctype="application/json", query=None):
        self._body, self.headers, self.query_params = body, {"content-type": ctype}, query or {}

    async def body(self):
        return self._body


got = asyncio.run(relay_routes._message_of(FakeRequest(json.dumps({"from": "Theo Martin", "text": "hey"}).encode())))
check("a shortcut's JSON", got == ("Theo Martin", "hey"), got)
got = asyncio.run(relay_routes._message_of(FakeRequest(b"from=%2B33612345678&text=salut%20%C3%A7a%20va",
                                                       "application/x-www-form-urlencoded")))
check("a form", got == ("+33612345678", "salut ça va"), got)
got = asyncio.run(relay_routes._message_of(FakeRequest(json.dumps({"Sender": "Ana", "Message": "yo"}).encode())))
check("its fields however they were named", got == ("Ana", "yo"), got)
got = asyncio.run(relay_routes._message_of(FakeRequest(b"", query={"from": "Kai", "text": "in the address"})))
check("or in the address itself", got == ("Kai", "in the address"), got)

state = DATA / "ipc" / "imsg_state.json"
state.write_text(json.dumps({"state": "ready", "phone": True, "at": time.time()}), encoding="utf-8")
check("the worker counts as up while it writes its state", relay_routes._worker_up(1))
state.write_text(json.dumps({"state": "ready", "phone": True, "at": time.time() - 300}), encoding="utf-8")
check("and not once it has stopped writing it", not relay_routes._worker_up(1))
page = relay_routes._page("Your iPhone reaches this PC", "x", ok=True)
check("the test page Safari opens says so, plainly", "Your iPhone reaches this PC" in page and "viewport" in page)

paths = {(r.path, tuple(sorted(r.methods or []))) for r in relay_routes.router.routes}
check("its routes: the shortcut's POST, the test GET, and the Setup page's",
      ("/relay/imessage/{token}", ("POST",)) in paths and ("/relay/imessage/{token}", ("GET",)) in paths
      and ("/api/imessage/relay/{index}", ("GET",)) in paths and ("/api/imessage/relay/status", ("GET",)) in paths)
server = read("app/web/server.py")
check("served by the panel, before its page's catch-all",
      server.index("app.include_router(relay_routes.router)") < server.index('@app.get("/{full_path:path}")'))
addrs = relay_routes._addresses()
check("the addresses a phone could use: Tailscale's, then the Wi-Fi's, never this PC's own loopback",
      all(not ip.startswith("127.") for ip, _ in addrs) and all(k in ("tailscale", "wifi") for _, k in addrs), addrs)

print("\n== who wrote ==")
from app.utils import snappeople  # noqa: E402

names = ["+33 6 12 34 56 78", "theo@icloud.com", "Theo Martin", "Zoë ❤️", "x" * 90]
py = [snappeople.imessage_person_id(n) for n in names]
node = shutil.which("node")
if node:
    js = subprocess.run([node, "-e", "import('./app/platforms/snapchat/bluebubbles.js').then(m => console.log("
                         + "JSON.stringify(" + json.dumps(names) + ".map(m.personId))))"],
                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    check("the same id as the Mac's runner would give them, number, email or contact name",
          json.loads(js.stdout or "[]") == py, (py, js.stdout, js.stderr[-300:]))
check("a number as its digits, a name character by character", py[0] == "im_p33612345678"
      and py[2] == "im_theo_20_martin" and py[4].startswith("im_h"))
snappeople.remember(1, "im_theo_20_martin", {"name": "Theo Martin"}, "imessage")
check("their name kept where a runner keeps it, for Chats and People",
      snappeople.name_of(1, "im_theo_20_martin", "imessage") == "Theo Martin")

print("\n== the worker ==")
br = read("app/platforms/snapchat_bridge.py")
check("it knows it is the iPhone way from its own account's address",
      'PHONE = IMESSAGE and os.getenv(f"IMESSAGE_SERVER_{ACCOUNT_INDEX}", "").strip().lower() == "phone"' in br)
check("no runner to start, and its state written itself",
      "    elif PHONE:\n        tasks = [process_incoming(), tg_command_loop(), _cleanup_loop(), _phone_state_loop()]" in br
      and "    elif PHONE:\n        log_system(f\"[iMessage] Account #{ACCOUNT_INDEX} reads through your iPhone" in br
      )
check("each message into the queue a runner fills, the answer back to the phone that waits",
      '_RELAY_WAIT[msg_id] = fut' in br and 'reply = await asyncio.wait_for(fut, RELAY_ANSWER_WITHIN)' in br
      and '_write_result(cmd_id, {"ok": True, "reply": reply})' in br)
check("several in a row from one person answered once", 'held["texts"].append(text)' in br
      and '"why": "answered with the one before"' in br)
check("nothing to answer, or nothing said: the phone stops waiting and sends nothing",
      "    if PHONE:\n        _relay_answered(msg_id, \"\")" in br)
check("never thinking for a minute: Shortcuts gives up on a request after one",
      "think = min(think, random.uniform(1.5, 4.5))" in br and "RELAY_ANSWER_WITHIN = 45.0" in br)
check("what only a Mac can do is not offered: effects, editing a typo, pictures",
      "IMESSAGE and not PHONE and _imessage_cfg().get(\"effects\", True)" in br
      and "IMESSAGE and not PHONE and _imessage_cfg().get(\"fix_typos\", True)" in br
      and "    if PHONE:\n        return {\"no_pictures\": True}" in br)
check("sending first is refused in words, not queued for nobody",
      'Through your iPhone it can only answer the messages it gets' in br
      and "    if PHONE:\n        log_system(f\"[iMessage] Not sent to" in br)
check("its conversations are the chat log", "    if PHONE:\n        # Nothing to read back from the phone" in br)

print("\n== the panel ==")
cond = read("webui/src/lib/accounts/condition.ts")
check("its card: waiting for the iPhone until the phone is heard from, with the way to set it up",
      'export const viaPhone = ' in cond and 'label: "Set up your iPhone"' in cond
      and 'action: { kind: "settings", label: "Show me", to: "imessage/setup" }' in cond
      and 'line: d?.night ? "Quiet hours, replies wait" : "Through your iPhone"' in cond)
acc = read("webui/src/pages/Accounts.svelte")
check("added as an iPhone or a Mac, the iPhone first", 'let imVia = $state<"phone" | "mac">("phone");' in acc
      and '{ id: "phone", label: "iPhone or iPad", icon: "phone", tone: "#30d158" }' in acc
      and '(imVia === "phone" ? { server: "phone", ...(imRenew ? { renew_relay: true } : {}) }' in acc)
check("and straight on to making its shortcut", 'if (editPlatform === "imessage" && imVia === "phone") openSettings("imessage/setup");' in acc)
setup = read("webui/src/lib/components/ImessageSetup.svelte")
check("Setup: its address with a QR code for the phone's camera, and a copy of it",
      '<div class="im-qr" role="img" aria-label="QR code of the address">{@html r.qr}</div>' in setup
      and 'await copyText(url, "Copied the address.");' in setup)
check("the four steps in Shortcuts", "Sender: <b>Anybody</b>" in setup and "<b>Get Contents of URL</b>" in setup
      and "Contents of URL <b>has any value</b>" in setup and "<b>Send Message</b>" in setup)
check("and why a phone cannot reach it, when the panel listens only on this PC", "Your iPhone can't reach this PC yet" in setup)
check("the panel's call", "imessageRelay: (index: number, base = \"\") =>" in read("webui/src/lib/api.ts"))
health = read("app/web/routes/health_routes.py")
check("no Node asked for, for the iPhone way", 'if os.getenv(f"IMESSAGE_SERVER_{i}", "").strip().lower() != "phone")' in health)

shutil.rmtree(DATA, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
