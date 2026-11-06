"""iMessage, the sixth platform: texting as the persona through BlueBubbles Server on a Mac signed in to iMessage.

The runner and its BlueBubbles client (app/platforms/snapchat/imessage_runner.js, bluebubbles.js) are tested under
Node by tests/imessage_logic.mjs, run from here; this covers the rest of the app around them: the account and its
targets, the panel's routes, the address rule and the connection test, people and chat logs, the engine's
tapbacks, the bridge's parts, the settings, Telegram, and the panel's pages.
"""
import asyncio
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="llmbot_imsg_"))
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(ROOT))
(DATA / "config").mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== the account, and where its commands go ==")
for k in [k for k in os.environ if k.startswith("IMESSAGE_")]:
    os.environ.pop(k, None)
from app.core import ipc  # noqa: E402

check("no server saved: no account", ipc._count_imessage_accounts() == 0)
os.environ["IMESSAGE_SERVER_1"] = "https://a.trycloudflare.com"
os.environ["IMESSAGE_SERVER_2"] = "http://192.168.1.20:1234"
check("counted by its BlueBubbles server, contiguously", ipc._count_imessage_accounts() == 2)
check("its targets: imsg, imsg2", ipc.validate_target("imsg") == "imsg" and ipc.validate_target("imsg2") == "imsg2")
try:
    ipc.validate_target("imsg../x")
    check("and nothing else", False)
except ValueError:
    check("and nothing else", True)
check("run by the shared bridge, with no browser", ipc.is_bridged("imsg2") and not ipc.is_browser("imsg")
      and ipc.platform_of("imsg2") == "imessage" and ipc.imessage_index("imsg2") == 2)
check("its web ids, both ways", ipc.target_for("imessage_2") == "imsg2" and ipc.web_id_for("imsg") == "imessage_1")
targets = ipc.discover_targets()
check("among the accounts the panel knows", targets.get("imessage_2", {}).get("target") == "imsg2")
check("and never taken for Instagram's or Minecraft's", not ipc.is_instagram("imsg") and not ipc.is_minecraft("imsg")
      and ipc.platform_of("insta") == "instagram")
check("its command file in ipc/, as the bridge reads it", ipc.cmd_file("imsg").name == "tg_commands_imsg.json")
for k in ("IMESSAGE_SERVER_1", "IMESSAGE_SERVER_2"):
    os.environ.pop(k, None)

print("\n== a BlueBubbles address, as people paste one ==")
from app.utils import bluebubbles  # noqa: E402

check("an address and its port", bluebubbles.server_url("192.168.1.20:1234") == "http://192.168.1.20:1234")
check("a tunnel's, with its slash or its API path left off", bluebubbles.server_url("https://abc.trycloudflare.com/")
      == "https://abc.trycloudflare.com" and bluebubbles.server_url("https://x.ngrok.io/api/v1/ping?password=s")
      == "https://x.ngrok.io")
check("the Mac's own address typed bare: BlueBubbles' port (1234)", bluebubbles.server_url("192.168.1.20")
      == "http://192.168.1.20:1234" and bluebubbles.server_url("Alicias-MacBook.local") == "http://alicias-macbook.local:1234"
      and bluebubbles.server_url("macbook") == "http://macbook:1234")
check("a domain typed bare: https, as tunnels serve it", bluebubbles.server_url("abc.trycloudflare.com")
      == "https://abc.trycloudflare.com")
check("a port or a scheme typed: as typed", bluebubbles.server_url("192.168.1.20:80") == "http://192.168.1.20:80"
      and bluebubbles.server_url("http://192.168.1.20") == "http://192.168.1.20"
      and bluebubbles.server_url("home.ddns.net:1234") == "http://home.ddns.net:1234")
check("and nothing usable as nothing", all(bluebubbles.server_url(x) == "" for x in
                                           ("", "ftp://mac", "a b", "https://host:99999")))
check("the same rule as the runner's", "/\\/api\\/v1\\/?.*$/i" in read("app/platforms/snapchat/bluebubbles.js")
      and 're.sub(r"/api/v1/?.*$", ""' in read("app/utils/bluebubbles.py"))


class _BB(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        from urllib.parse import urlsplit, parse_qs
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        body = {"status": 200, "message": "Success", "data": "pong"}
        code = 200
        if q.get("password", [""])[0] != "pw":
            code, body = 401, {"status": 401, "message": "Unauthorized", "error": {"type": "Unauthorized", "error": "x"}}
        elif u.path == "/api/v1/server/info":
            body = {"status": 200, "message": "Success", "data": {"os_version": "15.1", "server_version": "1.9.9",
                                                                   "private_api": True, "helper_connected": False,
                                                                   "detected_imessage": "a@icloud.com"}}
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BB)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"127.0.0.1:{srv.server_address[1]}"
got = asyncio.run(bluebubbles.check(base, "pw"))
check("Test: it answers, and says what the Mac is", got.get("ok") and got.get("account") == "a@icloud.com"
      and got.get("macos") == "15.1" and got.get("private_api") is True and got.get("helper") is False, got)
check("a wrong password, said as one", "refused that password" in asyncio.run(bluebubbles.check(base, "no")).get("reason", ""))
check("no password at all: asked for", not asyncio.run(bluebubbles.check(base, "")).get("ok"))
check("nothing there, in words", "Nothing answered" in asyncio.run(bluebubbles.check("127.0.0.1:1", "pw", timeout=3)).get("reason", ""))
srv.shutdown()

print("\n== the Accounts page's routes ==")
from app.web.routes import account_routes  # noqa: E402

spec = account_routes.PLATFORMS["imessage"]
check("its slot: the server and its password, the password write-only; and an iPhone's relay secret",
      spec["fields"] == {"server": "IMESSAGE_SERVER", "password": "IMESSAGE_PASSWORD", "relay": "IMESSAGE_RELAY"}
      and spec["secret"] == ("password",) and spec["required"] == "server")
slots = account_routes._slots({"IMESSAGE_SERVER_1": "https://a.trycloudflare.com", "IMESSAGE_PASSWORD_1": "secret"})
check("listed with whether a password is set, never the password", slots == [
    {"id": "imessage_1", "platform": "imessage", "index": 1, "server": "https://a.trycloudflare.com", "password_set": True,
     "relay": ""}], slots)
b = {"server": "192.168.1.20:1234/"}
account_routes._imessage_body(b)
check("an address saved as its runner reads it", b["server"] == "http://192.168.1.20:1234")
try:
    account_routes._imessage_body({"server": "not an address"})
    check("and a 400 for one that is not", False)
except Exception as e:
    check("and a 400 for one that is not", getattr(e, "status_code", 0) == 400)
paths = [r.path for r in account_routes.router.routes]
check("Test has three parts to its path, so /api/accounts/{id}/{action} does not take it",
      "/api/accounts/imessage/connection/test" in paths)
from app.web.envfile import SECRET_KEYS  # noqa: E402

check("its password masked on the Keys page", bool(SECRET_KEYS.match("IMESSAGE_PASSWORD_1"))
      and not SECRET_KEYS.match("IMESSAGE_SERVER_1"))
from app.web.routes import env_routes  # noqa: E402

check("and listed there as an iMessage account", env_routes.KEY_FAMILIES["imessage"]["prefix"] == "IMESSAGE_SERVER")

print("\n== who is who ==")
from app.utils import snappeople, chatlog  # noqa: E402

check("its people by their number or email, its groups by their chat", snappeople.platform_of_user("im_p15551234567")
      == "imessage" and snappeople.platform_of_user("img_777777") == "imessage"
      and snappeople.platform_of_user("igg_1") == "instagram")
check("a number read back", snappeople.imessage_address("im_p33612345678") == "+33612345678"
      and snappeople.imessage_address("im_0612345678") == "0612345678")
check("an email read back, as the runner writes it",
      snappeople.imessage_address("im_theo_2e_wav_40_icloud_2e_com") == "theo.wav@icloud.com")
check("nothing for a group's, or a hashed one", snappeople.imessage_address("img_777") == ""
      and snappeople.imessage_address("im_h" + "a" * 24) == "")
pdir = DATA / "cache" / "imessage_people"
pdir.mkdir(parents=True, exist_ok=True)
(pdir / "contacts_1.json").write_text(json.dumps({"im_p15551234567": {"name": "Theo", "file": "1_im_p15551234567.png"}}))
(pdir / "1_im_p15551234567.png").write_bytes(b"\x89PNG" + b"0" * 200)
check("named and pictured from its runner's address book", snappeople.name_of(1, "im_p15551234567", "imessage") == "Theo"
      and snappeople.avatar_url(1, "im_p15551234567", "imessage").startswith("/api/chats/web-picture/imessage/1/"))
check("its conversations kept as 5000 + its number", chatlog.web_account("imessage", 2) == 5002
      and chatlog.log_account("imsg") == 5001 and chatlog.log_account("imsg3") == 5003
      and chatlog.log_account("insta2") == 3002)
from app.utils import db  # noqa: E402

db.init_db()
conn = db.connect_raw()
try:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
finally:
    conn.close()
check("its tables, as Minecraft's", {"message_log_imessage", "user_stats_imessage", "ignored_users_imessage"} <= tables)
db.record_user_message_web("imessage", "im_p15551234567", "Theo", account=1)
check("and counted there", db.get_leaderboard_web("imessage")[0]["username"] == "Theo")
described = snappeople.describe(["im_p15551234567", "im_p19998887777"])
check("described for the people pages: a name, else their number", described["im_p15551234567"]["name"] == "Theo"
      and described["im_p19998887777"]["name"] == "+19998887777", described)

print("\n== the engine: tapbacks ==")
import app.utils.ai as ai  # noqa: E402
import app.core.engine as engine  # noqa: E402


class _Comp:
    def __init__(self):
        self.reply = "ok"
        self.calls = []

    async def create(self, model=None, messages=None, **kw):
        self.calls.append(messages)
        sysmsg = next((m["content"] for m in messages if m["role"] == "system"), "")
        text = "en" if "language detector" in sysmsg else "{}" if "memory extractor" in sysmsg \
            else "[]" if "memory auditor" in sysmsg else self.reply
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))])


comp = _Comp()
ai._groq_clients = [{"client": types.SimpleNamespace(chat=types.SimpleNamespace(completions=comp)), "label": "K"}]
ai._initialised = True
ai._resting.clear()
ai._client_index = 0
ai.groq_models = ["m"]
ai.current_model_index = 0
ai.model = "m"
engine._spawn_memory_update = lambda *a, **k: None
SIX = ["❤️", "👍", "👎", "😂", "‼️", "❓"]


def ask(text, reply, tapbacks=True, platform="imessage", uid="im_p15551234567", effects=False):
    comp.reply = reply
    engine.message_history.clear()
    m = engine.IncomingMessage(platform=platform, user_id=uid, user_name="Theo", channel_id=uid, content=text,
                               extra={"account": 1, **({"tapbacks": SIX} if tapbacks else {}),
                                      **({"effects": True} if effects else {})})
    return asyncio.run(engine.generate_ai_response(m)), m


def prompt():
    for msgs in reversed(comp.calls):
        s = next((x["content"] for x in msgs if x["role"] == "system"), "")
        if "[OUTPUT RULES:" in s:
            return s
    return ""


_cfg = engine.load_config
engine.load_config = lambda: {**_cfg(), "bot": {**(_cfg().get("bot") or {}), "reactions": {"chance": 1.0}}}
out, m = ask("you made it home ok?", "yes!! [[REACT:❤️]]")
check("a reply with a tapback: the tag out of what is sent, the tapback handed to the bridge",
      out == "yes!!" and m.extra.get("react") == "❤️", (out, m.extra))
p = prompt()
check("taught iMessage's six, as Discord's reactions are", "[TAPBACKS:" in p and "❤️ 👍 👎 😂 ‼️ ❓" in p)
check("and not told it cannot react", "You cannot send a reaction here" not in p)
check("named iMessage, not 'Imessage'", "[PLATFORM: You are chatting on iMessage.]" in p)
out, m = ask("lmaooo", "[[REACT_ONLY:😂]]")
check("a tapback with nothing said: the whole answer, remembered as one", out == "" and m.extra.get("react") == "😂"
      and engine.get_history("im_p15551234567", "im_p15551234567")[-1]["content"] == "[tapped back 😂]")
out, m = ask("hey", "hiii [[REACT:🔥]]")
check("one it does not have: the tag still goes, nothing tapped", out == "hiii" and not m.extra.get("react"), (out, m.extra))
check("an effect's tag: out of the words, its id kept", engine.take_effect("I GOT THE JOB [[EFFECT:Confetti]]")
      == ("I GOT THE JOB", "com.apple.messages.effect.CKConfettiEffect")
      and engine.take_effect("aww [[EFFECT: invisible  ink]]")[1] == "com.apple.MobileSMS.expressivesend.invisibleink")
check("and one iMessage does not have, out all the same", engine.take_effect("ok [[EFFECT:explode]]") == ("ok", ""))
out, m = ask("I passed my exam!!!", "NO WAY congrats!! [[EFFECT:fireworks]]", effects=True)
check("an effect for a big moment, handed to the bridge", out == "NO WAY congrats!!"
      and m.extra.get("effect") == "com.apple.messages.effect.CKFireworksEffect" and "[EFFECTS:" in prompt(), (out, m.extra))
out, m = ask("ok", "ok [[EFFECT:slam]]", effects=False)
check("not asked for: the tag still goes, no effect", out == "ok" and not m.extra.get("effect"), (out, m.extra))
engine.load_config = lambda: {**_cfg(), "bot": {**(_cfg().get("bot") or {}), "reactions": {"chance": 0.0}}}
out, m = ask("how was it?", "so good [[REACT:❤️]]")
check("as rare as the persona's reaction chance says (bot.reactions.chance)", out == "so good" and not m.extra.get("react"))
engine.load_config = _cfg
out, m = ask("hey", "hello", tapbacks=False, platform="snapchat", uid="snapperson")
check("the other platforms' prompt as it was, word for word",
      "You cannot send a reaction here, so if an emoji is the whole response, type the emoji itself. Output the raw "
      "message only.]" in prompt() and "[TAPBACKS:" not in prompt())

print("\n== a reasoning model out of room (every platform) ==")


class _Thinker:
    """Thinks through the whole allowance the first time, as gpt-oss-20b did in the proof; answers when given room."""

    def __init__(self, first_finish="length", first_text=""):
        self.caps = []
        self.first_finish, self.first_text = first_finish, first_text

    async def create(self, model=None, messages=None, max_tokens=None, **kw):
        self.caps.append(max_tokens)
        first = len(self.caps) == 1
        msg = types.SimpleNamespace(content=self.first_text if first else "yeah im free, why",
                                    reasoning="We need to respond as Alicia. She is 18, confident...")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=msg, finish_reason=self.first_finish if first else "stop")])


def _think(thinker):
    ai._groq_clients = [{"client": types.SimpleNamespace(chat=types.SimpleNamespace(completions=thinker)), "label": "K"}]
    ai._resting.clear()
    return asyncio.run(ai.generate_response("hey! are you free tonight?", "You are Alicia."))


_saved_clients = ai._groq_clients
th = _Thinker()
out = _think(th)
check("its whole allowance spent thinking, no words: asked again with room for both, and the reply kept",
      out == "yeah im free, why" and len(th.caps) == 2 and th.caps[1] >= 3 * th.caps[0], (out, th.caps))
th = _Thinker(first_finish="stop", first_text="")
out = _think(th)
check("nothing said because it chose to: not asked again", out == "" and len(th.caps) == 1, (out, th.caps))
th = _Thinker(first_finish="length", first_text="yeah im fr")
out = _think(th)
check("cut short with words: those words, one call, as before", out == "yeah im fr" and len(th.caps) == 1, (out, th.caps))
ai._groq_clients = _saved_clients
ai._resting.clear()
check("the asking again is said in the log, with the numbers",
      'spent all {cap} tokens thinking and wrote nothing; asking again with {room}' in read("app/utils/ai.py"))

print("\n== the bridge ==")
bridge = read("app/platforms/snapchat_bridge.py")
check("its platform: the imsg files, iMessage's six tapbacks, calls", '"imessage": {' in bridge
      and '"key": "imsg", "env": "IMESSAGE", "runner": "imessage_runner.js"' in bridge
      and '"reactions": ("❤️", "👍", "👎", "😂", "‼️", "❓")' in bridge)
check("its runner started with no npm packages and no Chrome",
      'if not IMESSAGE and not os.path.isdir(os.path.join(runner_dir, "node_modules")):' in bridge
      # NO_BROWSER is iMessage and WhatsApp: neither opens one. The packages check above stays iMessage's alone,
      # because WhatsApp does need what is in that folder (baileys).
      and "NO_BROWSER = IMESSAGE or WHATSAPP" in bridge
      and "if not NO_BROWSER and not chrome_path():" in bridge)
# Every script in the runners' folder is copied, so neither can be left out (tests/test_platform_registry.py runs it).
check("and both files copied beside the others", 'p.suffix in (".js", ".mjs")' in bridge
      and (ROOT / "app/platforms/snapchat/bluebubbles.js").is_file()
      and (ROOT / "app/platforms/snapchat/imessage_runner.js").is_file())
check("its settings into its runner, .env first", "def _imessage_env(cfg: dict) -> dict:" in bridge
      and '"typing_indicator": "IMESSAGE_TYPING"' in bridge and 'out["IMESSAGE_TRIGGER"] = str(bot["trigger"])' in bridge)
check("the persona's tapback, on the message it answers", '**({"tapbacks": list(SNAP_REACTIONS)}' in bridge
      and 'react_to=str(entry.get("react_to") or "")' in bridge and 'elif response == "" and react:' in bridge)
check("unsends and edits kept, as Discord's are", 'elif msg.get("kind") in ("unsent", "edited") and msg.get("key"):' in bridge
      and '_emit_chat({"t": "deleted", "uid": str(uid), "mid": key, "at": time.time()})' in bridge)
check("a voice message as an MP3 BlueBubbles makes Apple's own", "def _to_mp3(wav: Path) -> Path | None:" in bridge
      and 'if PLATFORM not in ("instagram", "imessage", "telegram") or not msg.extra.get("voice_ok"):' in bridge)
check("a new conversation from the Chats tab, with its first message",
      '_friend_add_cmd(cmd_id, str(payload.get("username") or ""), str(payload.get("text") or ""))' in bridge
      and 'text = str(body.get("text") or "").strip()[:2000]' in read("app/web/routes/chat_routes.py"))
check("the Mac's state in get_status, for its card", 'status["imessage"] = {k: r.get(k) for k in' in bridge)
check("a typo it was given, fixed by an edit half the time (imessage.fix_typos)", "plain = humanize(clean, 0)" in bridge
      and "effect=effect, fixed=fixed)" in bridge)

print("\n== started, shown and told like the others ==")
cli = read("app/cli.py")
check("its own role", '"imessage"' in cli and 'os.environ["BRIDGE_PLATFORM"] = "imessage"' in cli)
sup = read("app/web/supervisor.py")
from app.platforms import registry  # noqa: E402
check("started by the supervisor, not on a phone", '"imessage": _count_imessage_accounts' in sup
      and not registry.BY_ID["imessage"].on_phone and "(device.is_phone() and not p.on_phone)" in sup)
status = read("app/web/routes/status_routes.py")
check("its card: its identity, and what its runner says", registry.BY_ID["imessage"].tone == "#0a84ff"
      and "_web_identity(platform, account, registry.BY_ID[platform].tone)" in status
      and registry.TARGETS["imessage"] == "imsg" and "says = {p: _snap_states(registry.TARGETS[p])" in status)
check("its colour in the log", '"imessage": ("\\033[38;2;10;132;255m"' in read("app/utils/logger.py"))
tg = read("app/telegram_bot/telegram_controller.py")
check("Telegram: /account imsg, its mark, its alerts", 'r"(?:imsg|imessage|im)(\\d*)"' in tg and '"💬 "' in tg
      and 'targets.append("imsg" if i == 1 else f"imsg{i}")' in tg)
check("health: Node, which it runs on", '"iMessage reads and sends through Node.' in read("app/web/routes/health_routes.py"))
check("stats: its replies counted", '("imessage", "message_log_imessage", "chat_id")' in read("app/web/routes/stats_routes.py"))

print("\n== its settings ==")
import yaml  # noqa: E402

cfg = yaml.safe_load(read("resources/config.yaml"))
im = cfg.get("imessage") or {}
check("an imessage: section, on by default, and a service switch", im.get("enabled") is True
      and (cfg.get("services") or {}).get("imessage", {}).get("enabled") is True)
from app.web import schema, descriptions  # noqa: E402

keys = {f"imessage.{k}" for k in im}
schema_keys = {f["key"] for f in schema.get_schema() if f["key"].startswith("imessage.")}
check("every one in the schema", keys <= schema_keys, keys - schema_keys)
check("and described, in a line", all(k in descriptions.DESCRIPTIONS for k in keys),
      [k for k in keys if k not in descriptions.DESCRIPTIONS])
check("one line each, short", all(len(descriptions.DESCRIPTIONS[k]) <= 90 for k in keys),
      [k for k in keys if len(descriptions.DESCRIPTIONS[k]) > 90])
smap = read("webui/src/lib/settingsmap.ts")
check("every one on a page of Settings, iMessage", all(f'"{k}"' in smap for k in keys if k != "imessage.enabled")
      and 'panel: "imessage-setup"' in smap)
settings = read("webui/src/pages/Settings.svelte")
check("its two choices as words", '"imessage.thread_replies": [' in settings and '"imessage.send_method": [' in settings
      and '"services.imessage.enabled": "imessage.enabled"' in settings)
check("its own setup page", "<ImessageSetup />" in settings and "BlueBubbles Server" in read("webui/src/lib/components/ImessageSetup.svelte"))
check("the example .env", "IMESSAGE_SERVER_1=" in read("resources/example.env"))

print("\n== the panel's pages ==")
plat = read("webui/src/lib/platforms.ts")
check("a platform: its six tapbacks, groups, voice, calls", '"imessage"' in plat and 'reactions: ["❤️", "👍", "👎", "😂", "‼️", "❓"]' in plat)
check("its people by their ids", 'if (s.startsWith("im_") || s.startsWith("img_")) return PLATFORMS.imessage;' in plat)
check("its mark, a bubble, solid", "export const IMESSAGE_BUBBLE" in read("webui/src/lib/brands.ts")
      and "imessage: IMESSAGE_BUBBLE" in read("webui/src/lib/components/Icon.svelte"))
acc = read("webui/src/pages/Accounts.svelte")
check("added from every way to add one", acc.count('openAdd("imessage")') == 3)
check("its dialog: the address, the password, Test", 'id="im-server"' in acc and "testImessage" in acc
      and "api.imessageTest" in acc)
cond = read("webui/src/lib/accounts/condition.ts")
check("its card in its own words", 'label: "Can\'t reach the Mac"' in cond and '"Wrong password"' in cond
      and 'if (s.platform === "imessage") return s.server === "phone" || !!(s.server && s.password_set);' in cond)
chats = read("webui/src/pages/Chats.svelte")
check("Chats: someone new texted by number or email", '<span class="ch-add-head">Text someone new</span>' in chats)

print("\n== the runner, under Node ==")
node = shutil.which("node")
if node:
    p = subprocess.run([node, str(ROOT / "tests" / "imessage_logic.mjs")], cwd=ROOT, capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    print(p.stdout.strip())
    check("imessage_logic.mjs passes", p.returncode == 0, (p.stdout + p.stderr)[-400:])
    for f in ("bluebubbles.js", "imessage_runner.js"):
        r = subprocess.run([node, "--check", str(ROOT / "app" / "platforms" / "snapchat" / f)], capture_output=True, text=True)
        check(f"{f} parses", r.returncode == 0, r.stderr[-300:])
runner = read("app/platforms/snapchat/imessage_runner.js")
check("no package of its own: Node's own modules, and the runners' shared ones",
      all(("from \"" + m + "\"") in runner or ("from \"./" + m) in runner for m in ("fs", "path", "url", "crypto"))
      and "puppeteer" not in runner and "dotenv" not in runner)
check("its password never printed", "PASSWORD" not in "".join(l for l in runner.splitlines() if "console." in l))
check("several messages in a row answered once", "function addToBurst(chatId, name, r)" in runner)
check("a reply answered from the Mac or the iPhone is not sent again on top",
      "someone answered from the Mac or the iPhone" in runner)
check("an effect on its first bubble, and only through the Private API", "effectId: effect || undefined" in runner
      and "const effect = effectId && papi && EFFECTS_ON ? effectId : \"\";" in runner)
check("a typo fixed by editing that bubble, never a rewrite", "async function fixTypos(chatId, name, said, meant, sent)" in runner
      and "Math.abs(said[i].length - meant[i].length) > 3" in runner)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + "; ".join(FAIL))
shutil.rmtree(DATA, ignore_errors=True)
sys.exit(1 if FAIL else 0)
