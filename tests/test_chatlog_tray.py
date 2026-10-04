"""Chats that remember, a Telegram bot that connects itself, and a tray worth clicking.

  * every DM message is kept (app/utils/chatlog.py): a conversation opened
    again is read from there, not from Discord; a deleted message is kept and
    marked, an edited one updated; pictures are kept on disk
  * after a restart, the first reply starts from what was said before
  * the Chats tab and Big Picture show the other person typing, a bin on a
    deleted message, and no "Reply now skips the wait" line
  * videos play in the app's own player; a picture pasted into Pictures is added
  * the Telegram page's routes check the token with Telegram, find your ID,
    send a test; the command list is one list for the controller and the
    panel; crash and silent alerts
  * the tray: a dot for how things are, a quick panel on a left click, a dark
    menu rebuilt as it opens, and the window hiding to it rather than closing
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-chatlog-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
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


print("== the chat log ==")
from app.utils import chatlog  # noqa: E402

t = time.time()
chatlog.put_many(1, 555, [
    (101, False, t - 300, {"text": "hey you there?"}),
    (102, True, t - 250, {"text": "yeah"}),
    (103, False, t - 200, {"text": "", "attachments": [{"url": "https://cdn.example/x.png", "type": "image/png", "name": "x.png"}]}),
    (104, False, t - 100, {"text": "so about saturday"}),
])
conv = chatlog.conversation(1, 555, 10)
check("a conversation comes back oldest first, both sides", [m["mid"] for m in conv] == ["101", "102", "103", "104"]
      and conv[1]["mine"] and not conv[0]["mine"])
check("it is one account's: another account has none of it", chatlog.conversation(2, 555, 10) == [])
check("the newest, when asked for fewer", [m["mid"] for m in chatlog.conversation(1, 555, 2)] == ["103", "104"])
chatlog.put(1, 555, 101, False, t - 300, {"text": "hey you there??"})
check("seen again, a message is updated, not doubled", chatlog.count(1, 555) == 4
      and chatlog.conversation(1, 555, 10)[0]["text"] == "hey you there??")
check("a deleted one is kept, marked, and says whose it was", chatlog.mark_deleted(1, 102) == "555"
      and chatlog.conversation(1, 555, 10)[1].get("deleted"))
chatlog.put(1, 555, 102, True, t - 250, {"text": "yeah"})
check("and seeing it again does not bring it back", chatlog.conversation(1, 555, 10)[1].get("deleted"))
check("an edit changes the words and says when", chatlog.mark_edited(1, 104, {"text": "so about sunday"}) == "555"
      and chatlog.conversation(1, 555, 10)[3]["text"] == "so about sunday" and chatlog.conversation(1, 555, 10)[3].get("edited"))
check("the same words again are no edit, and an unknown message is nothing",
      chatlog.mark_edited(1, 104, {"text": "so about sunday"}) is None and chatlog.mark_edited(1, 999, {"text": "x"}) is None)
gone = chatlog.missing_since(1, 555, t - 310, t - 90, [101, 104])
check("one Discord no longer has, in the stretch just read, was deleted while nobody watched",
      gone == ["103"] and chatlog.conversation(1, 555, 10)[2].get("deleted"), str(gone))
check("the picture of a message is kept under its id", chatlog.picture_name(103, 0, "image/png") == "103_0.png"
      and chatlog.picture_name(103, 0, "application/pdf") is None)
(chatlog.CACHE_DIR).mkdir(parents=True, exist_ok=True)
(chatlog.CACHE_DIR / "103_0.png").write_bytes(b"png")
pic = chatlog.conversation(1, 555, 10)[2]["attachments"][0]
check("and shown from there, since Discord's own link expires", pic["url"] == "/api/media/chat/103_0.png"
      and pic["remote"].startswith("https://"))
check("only a kept picture's own name is served", chatlog.media_path("103_0.png") is not None
      and chatlog.media_path("../config/.env") is None and chatlog.media_path("103_0.exe") is None)
seed = chatlog.seed_turns(1, 555, t - 50)
check("after a restart, the history starts from the log: their words, its words, deleted ones left out",
      seed == [{"role": "user", "content": "hey you there??\nso about sunday"}], str(seed))
chatlog.put_many(1, 777, [(i, i % 2 == 0, t + i, {"text": f"m{i}"}) for i in range(chatlog.KEEP + 60)])
check("a conversation keeps its newest few hundred", chatlog.count(1, 777) == chatlog.KEEP)

print("\n== the runner keeps it ==")
runner = app_src("app/platforms/discord_runner.py")
check("every DM message goes into the log, both sides", "async def on_message(message):\n    _log_dm(message)" in runner)
check("a deleted DM is marked, and the tab told", "async def on_raw_message_delete(payload):" in runner
      and '"t": "deleted"' in runner)
check("an edit too, but not an embed filling in", "async def on_raw_message_edit(payload):" in runner
      and 'if "content" not in data:' in runner)
check("someone typing is told to the tab", "async def on_typing(channel, user, when):" in runner and '"t": "typing"' in runner)
check("a DM's pictures are saved as they come", "await att.read()" in runner and "_KEEP_PICTURE_BYTES" in runner)
job = runner.split("async def _history_job(cmd_id, payload):")[1].split("async def _send_message_job")[0]
check("a conversation read this session is served from the log, not Discord",
      "if uid in synced and (have >= limit or uid in exhausted):" in job and '"from_log": True' in job)
check("scrolling back reads only what the log lacks", "limit=limit - have, before=before" in job)
check("the first read marks what Discord no longer has", "_chatlog.missing_since(" in job)
check("up to 200 back", "min(200," in job)
seeds = runner.count("await seed_history(")
check("every way a reply is written starts from what was said before", seeds >= 5, str(seeds))
check("seeded once per conversation per session, and not over history it already has",
      "if bot.message_history.get(key):" in runner and "_seeded_history" in runner)
check("reply to all works out what it answers before seeding", runner.index("_ra_combined = ") < runner.index("await seed_history(_ra_hk2, _ra_target)"))
routes = app_src("app/web/routes/chat_routes.py")
check("with the account stopped, the tab still reads the log", '"offline": True' in routes
      and "chatlog.conversation(chatlog.log_account(tgt)" in routes)
check("typing is not replayed to a page that connects later", 'if evt.get("t") == "typing":\n        return' in routes)
check("the kept pictures have a route", "/api/media/chat/{name}" in app_src("app/web/routes/media_routes.py"))

print("\n== the Chats tab and Big Picture ==")
chats = read("pages/Chats.svelte")
chats_ts = read("lib/chats.ts")
stage = read("lib/bigpicture/BPStage.svelte")
check("no more 'Reply now skips the wait'", "skips the wait" not in chats and "writes and sends one straight away" not in chats)
check("someone typing lapses on its own, and ends when their message comes",
      "setTimeout(() => setTyping(k, false), 10000)" in chats_ts and 'if (evt.t === "msg") setTyping(k, false);' in chats_ts)
check("their dots in the chat, and 'typing' in the list", 'class="cd-msg is-first is-last cd-their-typing"' in chats
      and 'class="ch-typing"' in chats)
check("and in Big Picture", "theyType" in stage and "{spot.u.name} is typing" in stage)
check("a deleted message stays, with a bin on it", 'class="cd-bin"' in chats and 'class="bps-bin"' in stage
      and ".cd-msg.is-deleted .cd-bubble" in chats)
check("an edited one says so", 'class="cd-edited"' in chats and "bps-edited" in stage)
check("a deletion or an edit reaches an open chat at once", 'evt.t === "deleted" || evt.t === "edited"' in chats_ts)
check("and scrolling back reads on, 50 at a time, as far back as there is",
      'api.chatsWindow(uid, target, "older", String(first.mid), 50)' in chats_ts and "start: !r.more" in chats_ts)

print("\n== video and pictures ==")
vp = read("lib/components/VideoPlayer.svelte")
check("a video plays in the app's own player", "<VideoPlayer src={a.url}" in read("lib/components/MessageBody.svelte")
      and "<video class=\"mb-vid\"" not in read("lib/components/MessageBody.svelte"))
for name, needle in (("speed", "const RATES = [0.25"), ("loop", "Loop"), ("picture in picture", "requestPictureInPicture"),
                     ("saving it", "saveUrlAs(src, name)"), ("full screen", "requestFullscreen"),
                     ("a seek bar that shows what has loaded and the time under the pointer", 'class="vp-tip"'),
                     ("the volume remembered", "llm-video-volume"), ("J and L, the arrows, M, F, 0 to 9", '/^[0-9]$/.test(k)')):
    check(f"with {name}", needle in vp)
check("its controls step aside while it plays", "idle = window.setTimeout(" in vp)
pics = read("pages/Pictures.svelte")
check("Ctrl+V adds the pictures on the clipboard", "<svelte:window onpaste={onPaste} />" in pics
      and 'i.type.startsWith("image/")' in pics)
check("but a paste into a box is still text", "if (inBox && items.some" in pics)
check("each named for when it was pasted", "`pasted-${stamp}" in pics)

print("\n== Telegram ==")
from app.telegram_bot import commands  # noqa: E402
ctl = app_src("app/telegram_bot/telegram_controller.py")
handled = set(__import__("re").findall(r'CommandHandler\("(\w+)"', ctl))
listed = {c for c, _ in commands.menu()}
aliases = {"analyze", "response", "imagelist", "imagedl", "clear"}
# /instructions is in the menu for the file you send with it, which a document handler takes.
menu_only = {"instructions"}
check("the command list is every command the controller answers", handled - aliases <= listed and listed - menu_only <= handled,
      str(sorted((handled - aliases) ^ (listed - menu_only))))
check("one list, for Telegram's menu and the panel", "_MENU_COMMANDS = [BotCommand(name, does) for name, does in _menu()]" in ctl)
check("crash alerts have their own switch, and all can come silently",
      'crash = payload.get("kind") == "crash"' in ctl and "disable_notification=quiet," in ctl)
sup = app_src("app/web/supervisor.py")
check("the supervisor queues a crash alert on the second crash in a row, and when it gives up",
      "if child.restarts == 2:" in sup and 'f"{child.label} stopped"' in sup and '"kind": "crash"' in sup)

from app.web.routes import telegram_routes as tg  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class FakeSup:
    def __init__(self):
        self.did = []

    def status(self):
        return [{"id": "telegram", "role": "telegram", "state": "stopped", "uptime": 0}]

    def start(self, cid):
        self.did.append(("start", cid))

    def restart(self, cid):
        self.did.append(("restart", cid))


said = []


def fake_call(token, method, params=None, timeout=10.0):
    said.append((method, params))
    if token.startswith("999"):
        raise tg._Refused(tg._plain("Unauthorized"))
    if method == "getMe":
        return {"id": 42, "username": "juni_ctl_bot", "first_name": "Juni control"}
    if method == "getUpdates":
        return [{"message": {"from": {"id": 5550142, "first_name": "Juni", "username": "juni"}, "chat": {"type": "private"}, "text": "hi", "date": 1}},
                {"message": {"from": {"id": 5550142, "first_name": "Juni"}, "chat": {"type": "private"}, "text": "again", "date": 2}},
                {"message": {"from": {"id": 7, "first_name": "Group"}, "chat": {"type": "group"}, "text": "x", "date": 3}}]
    if method == "sendMessage":
        return {"message_id": 1}
    return {}


tg._call = fake_call
app = FastAPI()
app.include_router(tg.router)
app.state.supervisor = FakeSup()
client = TestClient(app)
good = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabc"
check("a token that is not one is refused before Telegram is asked",
      client.post("/api/telegram/check", json={"token": "your_token_here"}).json()["ok"] is False and not said)
r = client.post("/api/telegram/check", json={"token": "999:ABCDEFGHIJKLMNOPQRSTUVWXYZabc"}).json()
check("a token Telegram does not know says so plainly", r["ok"] is False and "doesn't know that token" in r["reason"], str(r))
r = client.post("/api/telegram/token", json={"token": good})
check("a good one is kept, and names its bot", r.status_code == 200 and r.json()["bot"]["username"] == "juni_ctl_bot")
check("in config/.env", f"TELEGRAM_BOT_TOKEN={good}" in (TMP / "config" / ".env").read_text(encoding="utf-8"))
r = client.post("/api/telegram/find-owner").json()
check("who wrote to the bot, newest first, once each, private chats only",
      r["ok"] and [p["id"] for p in r["people"]] == ["5550142"] and r["people"][0]["said"] == "again", str(r))
check("reading them does not use them up (no offset)", all("offset" not in (p or {}) for m, p in said if m == "getUpdates"))
check("an ID that is not a number is refused", client.post("/api/telegram/owner", json={"id": "me"}).status_code == 400)
r = client.post("/api/telegram/owner", json={"id": "5550142"})
check("an ID is kept, and the controller started with both", r.status_code == 200 and ("start", "telegram") in app.state.supervisor.did)
r = client.post("/api/telegram/test").json()
check("the test message goes to the owner", r["ok"] and ("sendMessage", {"chat_id": 5550142, "text": said[-1][1]["text"]}) == said[-1])
st = client.get("/api/telegram").json()
check("the page is told what is set, never the token itself", st["token_set"] and st["owner_id"] == "5550142"
      and good not in str(st) and st["token_hint"] == "…" + good[-4:])
check("the commands, grouped", len(client.get("/api/telegram/commands").json()["groups"]) >= 6)

print("\n== the tray ==")
from app import tray  # noqa: E402


class TraySup:
    def __init__(self, kids):
        self.kids = kids

    def status(self):
        return self.kids


def snap_of(kids):
    tray._STATE["supervisor"] = TraySup(kids)
    return tray.snapshot()


ok = {"id": "discord_1", "role": "discord", "account": 1, "label": "Discord #1", "state": "running", "gave_up": False}
check("green with everything running", snap_of([ok])["tone"] == "good")
check("red with one given up on, and it says so", snap_of([ok, {**ok, "id": "discord_2", "state": "stopped", "gave_up": True}])["tone"] == "bad"
      and "needs a look" in tray.snapshot()["headline"])
check("grey with nothing running", snap_of([{**ok, "state": "stopped"}])["tone"] == "idle")
check("the Telegram controller is not an account", snap_of([ok, {"id": "telegram", "role": "telegram", "state": "running"}])["headline"] == "1 running")
import pystray  # noqa: E402
tray._STATE["windows"] = {"show_main": lambda r: None, "toggle_panel": lambda: None, "open_data": lambda: None, "quit": lambda: None}
tray._STATE["snapshot"] = snap_of([ok])
menu = tray._menu(pystray)
items = [i for i in menu.items if i is not pystray.Menu.SEPARATOR]
default = [i for i in items if i.default]
check("a left click opens the quick panel, which is not a line of the menu",
      len(default) == 1 and default[0].text == "Quick panel" and not default[0].visible)
texts = [i.text for i in items if i.visible]
check("the menu starts with how things are", texts[0].startswith("LLMSelfbot") and "running" in texts[0] and not items[1].enabled)
for want in ("Open LLMSelfbot", "Go to", "Accounts", "Pause all replies", "Restart all accounts", "Keep running when closed",
             "Alerts on this computer", "Open data folder", "Quit LLMSelfbot"):
    check(f"it has {want}", want in texts, str(texts))
acct = next(i for i in items if i.text == "Accounts")._action.items[0]
check("each account has its own pause, restart and stop", [i.text for i in acct._action.items] == ["Replying", "Restart", "Stop"])
check("the icon carries a dot", tray._with_dot(tray._base_image(), "bad").getpixel((50, 50))[:3] == tray._TONES["bad"])
check("the switches default to keeping it running, with alerts", tray.prefs()["close_to_tray"] and tray.prefs()["alerts"])
tray.set_pref("alerts", False)
check("and are kept", tray.prefs()["alerts"] is False and (TMP / "config" / "desktop.json").exists())
check("its menus are dark, like the app", "set_mode(2)" in app_src("app/tray.py"))
check("rebuilt as a right click opens it, on its own thread", "if lparam == w32.WM_RBUTTONUP:" in app_src("app/tray.py"))
desktop = app_src("app/desktop.py")
check("closing the window hides it while the tray is there, and Quit ends it",
      "window.events.closing += _on_closing" in desktop and "return False" in desktop.split("def _on_closing")[1][:400]
      and "os._exit(0)" in desktop.split("def _quit_app")[1][:500])
check("the first time, the tray says it is still running", 'tray.set_pref("told_tray", True)' in desktop)
check("the quick panel sits by the tray, out of the taskbar, round", "def _place_panel(hwnd)" in desktop
      and "WS_EX_TOOLWINDOW" in desktop and "DWMWCP_ROUND" in desktop)
check("a click on the icon while it is open closes it", "time.time() - _PANEL[\"hidden_at\"] < 0.4" in desktop)
check("it takes the keyboard even where Windows would refuse it, so clicking away closes it",
      "AttachThreadInput(mine, theirs, True)" in desktop)
check("and it closes when another window takes over, focus in the page or not", "form.Deactivate +=" in desktop)
check("Open window opens the app, not a browser tab", "w.show" in desktop.split("def _show_main")[1][:600])
panel = read("TrayPanel.svelte")
main = read("main.ts")
check("the quick panel is the app's own page", 'new URLSearchParams(location.search).has("tray")' in main and "TrayPanel" in main)
check("each account with a switch to pause it", '<Toggle checked={!paused[a.id]}' in panel and 'api.accountAction(a.id, "pause")' in panel)
check("today's replies, rolling", "<Odometer value={today} />" in panel)
check("the pages one click away, and pause all, restart all, quit", "bridge()?.open_main?.(route)" in panel
      and "pauseAll" in panel and "restartAll" in panel and "quit_app" in panel)
check("it closes when you click elsewhere", 'window.addEventListener("blur", onBlur);' in panel and "hide_panel" in panel)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
