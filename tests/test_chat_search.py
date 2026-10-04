"""The Chats tab, searched and gone through like Discord's, and Snapchat's chats in it too.

  * a conversation searched as you type in what is kept (any case, accents
    ignored, from whom, with what, between when, deleted ones included), and
    all of it on Discord on Enter, 25 at a time; every chat searched at once
    from the list, with filters (unread, needs you, drafts ...)
  * what was shared in a conversation: pictures and videos, files, links
  * jumping to a message from a search, reading back and on from there, the
    first message, a conversation saved as text
  * drafts kept per conversation, across leaving the tab and a restart; files
    dropped onto a conversation; @usernames that can be copied
  * Snapchat: conversations read off its page and kept, messages sent from the
    tab, what is new pushed live, and each chat's picture
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-chatsearch-"))
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


print("== what is kept, searched ==")
from app.utils import chatlog  # noqa: E402

t = time.time()
chatlog.put_many(1, 7, [
    (201, False, t - 900, {"text": "On va au Café ce soir?"}),
    (202, True, t - 800, {"text": "oui, regarde https://maps.google.com/x?y=1."}),
    (203, False, t - 700, {"text": "", "attachments": [{"url": "https://cdn/x.png", "type": "image/png", "name": "photo.png"}]}),
    (204, False, t - 600, {"text": "voice", "attachments": [{"url": "https://cdn/v.ogg", "type": "audio/ogg", "name": "voice-message.ogg"}]}),
    (205, True, t - 500, {"text": "cafe cafe CAFÉ", "embeds": [{"title": "Le Café", "url": "https://cafe.fr", "image": ""}]}),
    (206, False, t - 400, {"text": "", "attachments": [{"url": "https://cdn/c.mp4", "type": "video/mp4", "name": "clip.mp4"},
                                                     {"url": "https://cdn/d.pdf", "type": "application/pdf", "name": "plan.pdf"}]}),
])
chatlog.put_many(1, 8, [(301, False, t - 50, {"text": "a cafe elsewhere"})])
chatlog.put_many(2, 7, [(401, False, t - 50, {"text": "cafe on another account"})])
chatlog.mark_deleted(1, 201)

page, total = chatlog.search(1, 7, ["cafe"])
check("any case, accents ignored, newest first", [m["mid"] for m in page] == ["205", "201"] and total == 2, str(page))
check("a deleted message is found too, and says so", page[-1].get("deleted"))
check("by best match: the most of the words first", [m["mid"] for m in chatlog.search(1, 7, ["cafe"], sort="relevant")[0]] == ["205", "201"])
check("oldest first", [m["mid"] for m in chatlog.search(1, 7, ["cafe"], sort="oldest")[0]] == ["201", "205"])
check("from whom", [m["mid"] for m in chatlog.search(1, 7, [], mine=True)[0]] == ["205", "202"])
check("has a picture, a video, a file, a voice message, a link",
      [m["mid"] for m in chatlog.search(1, 7, [], has=["image"])[0]] == ["203"]
      and [m["mid"] for m in chatlog.search(1, 7, [], has=["video"])[0]] == ["206"]
      and [m["mid"] for m in chatlog.search(1, 7, [], has=["sound"])[0]] == ["204"]
      and [m["mid"] for m in chatlog.search(1, 7, [], has=["file"])[0]] == ["206", "204", "203"]
      and [m["mid"] for m in chatlog.search(1, 7, [], has=["link"])[0]] == ["202"])
check("before and after a moment", [m["mid"] for m in chatlog.search(1, 7, [], before=t - 750)[0]] == ["202", "201"]
      and [m["mid"] for m in chatlog.search(1, 7, [], after=t - 450)[0]] == ["206"])
check("a file's name is searched too", [m["mid"] for m in chatlog.search(1, 7, ["plan"])[0]] == ["206"])
check("pages of it", [m["mid"] for m in chatlog.search(1, 7, [], limit=2, offset=2)[0]] == ["204", "203"]
      and chatlog.search(1, 7, [], limit=2)[1] == 6)
found = chatlog.search_all(1, ["cafe"])
check("every chat of one account at once, saying whose", [(m["uid"], m["mid"]) for m in found] == [("8", "301"), ("7", "205"), ("7", "201")],
      str([(m["uid"], m["mid"]) for m in found]))
check("and nothing at all asked is nothing found", chatlog.search_all(1, []) == [])

print("\n== what was shared ==")
media = chatlog.shared(1, 7, "media")
check("pictures and videos, newest first", [(i["mid"], i["kind"]) for i in media] == [("206", "video"), ("203", "image")])
files = chatlog.shared(1, 7, "files")
check("files and voice messages", [(i["mid"], i["kind"]) for i in files] == [("206", "file"), ("204", "sound")])
links = chatlog.shared(1, 7, "links")
check("links said and links previewed, without the full stop after one",
      [(i["mid"], i["url"]) for i in links] == [("205", "https://cafe.fr"), ("202", "https://maps.google.com/x?y=1")])
check("how far back what is kept reaches", chatlog.span(1, 7)[0] == 6 and round(t - chatlog.span(1, 7)[1]) == 900)

print("\n== around a message ==")
ids = lambda ms: [m["mid"] for m in ms]  # noqa: E731
check("either side of it, it included", ids(chatlog.window(1, 7, 204, "around", 4)) == ["202", "203", "204", "205"])
check("before it, and after it", ids(chatlog.window(1, 7, 204, "older", 2)) == ["202", "203"]
      and ids(chatlog.window(1, 7, 204, "newer", 5)) == ["205", "206"])
check("the very first ones", ids(chatlog.window(1, 7, None, "first", 2)) == ["201", "202"])
check("one not kept is nothing", chatlog.window(1, 7, 999, "around") is None)
check("the deleted ones in a stretch", ids(chatlog.deleted_between(1, 7, t - 1000, t)) == ["201"])
text = chatlog.as_text(chatlog.conversation(1, 7, 50), "Me", "Ry")
check("saved as text: when, who, what came with it, and what was deleted",
      "] Ry: On va au Café ce soir? (deleted)" in text and "Me: cafe cafe CAFÉ" in text and "[image: photo.png]" in text
      and "[file: plan.pdf]" in text, text[:300])
check("Snapchat's chats are kept apart, as account 1000 and up", chatlog.log_account("snap") == 1001
      and chatlog.log_account("snap3") == 1003 and chatlog.log_account(2) == 2 and chatlog.log_account("2") == 2)
check("which of these are kept, with their times", set(chatlog.known_ts(1, 7, ["201", "202", "999"])) == {"201", "202"})

print("\n== the routes ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.core import ipc  # noqa: E402
from app.web.routes import chat_routes  # noqa: E402

ipc.discover_targets = lambda: {
    "discord_1": {"platform": "discord", "account": 1, "target": 1},
    "snapchat_1": {"platform": "snapchat", "account": 1, "target": "snap"},
}
asked = []
answers = {}


async def fake_send(target, cmd, payload=None, timeout=10.0):
    asked.append((target, cmd, payload))
    return answers.get(cmd)

ipc.send_and_wait = fake_send
app = FastAPI()
app.include_router(chat_routes.router)
client = TestClient(app)

r = client.post("/api/chats/search", json={"target": "discord_1", "user_id": "7", "words": ["CAFE"]}).json()
check("searching one chat as you type: what is kept, and how far back that reaches",
      [m["mid"] for m in r["messages"]] == ["205", "201"] and r["kept"] == 6 and r["since"], str(r)[:200])
check("a server channel is not one of them", client.post("/api/chats/search", json={"target": "discord_1", "user_id": "ch55"}).status_code == 400)
answers["chat_search"] = {"ok": True, "messages": [{"mid": "900", "mine": False, "ts": t - 99999, "text": "old cafe"}], "total": 31, "more": True}
r = client.post("/api/chats/search-discord", json={"target": "discord_1", "user_id": "7", "words": ["cafe"], "has": ["image", "bogus"],
                                                    "mine": True, "cursor": "123", "sort": "oldest"}).json()
sent = asked[-1][2]
check("Discord's own search, with what was asked and nothing that is not a filter",
      r["total"] == 31 and asked[-1][1] == "chat_search" and sent["has"] == ["image"] and sent["mine"] is True
      and sent["cursor"] == "123" and sent["sort"] == "oldest", str(sent))
check("nothing to search for is not asked of Discord",
      client.post("/api/chats/search-discord", json={"target": "discord_1", "user_id": "7"}).status_code == 400)
check("and Snapchat has no search of its own to ask",
      client.post("/api/chats/search-discord", json={"target": "snapchat_1", "user_id": "x", "words": ["a"]}).status_code == 400)
answers["chat_search"] = {"ok": False, "retry": True, "reason": "still indexing"}
check("Discord still indexing says to try again",
      client.post("/api/chats/search-discord", json={"target": "discord_1", "user_id": "7", "words": ["a"]}).status_code == 409)
r = client.post("/api/chats/search-all", json={"target": "discord_1", "words": ["cafe"]}).json()
check("every chat at once, from the list", [m["uid"] for m in r["messages"]] == ["8", "7", "7"] and "people" in r)
r = client.post("/api/chats/shared", json={"target": "discord_1", "user_id": "7", "kind": "links"}).json()
check("what was shared", len(r["items"]) == 2 and r["kept"] == 6)
check("only the three kinds", client.post("/api/chats/shared", json={"target": "discord_1", "user_id": "7", "kind": "x"}).status_code == 400)

answers["chat_window"] = {"ok": True, "more": True, "messages": [
    {"mid": "200", "mine": True, "ts": t - 950, "text": "before"}, {"mid": "202", "mine": True, "ts": t - 800, "text": "x"}]}
r = client.post("/api/chats/around", json={"target": "discord_1", "user_id": "7", "mid": "202", "dir": "around"}).json()
check("around a message, from Discord, with the deleted one kept here put back where it was",
      [m["mid"] for m in r["messages"]] == ["200", "201", "202"] and asked[-1][1] == "chat_window"
      and asked[-1][2]["dir"] == "around", str(r)[:300])
answers["chat_window"] = None
r = client.post("/api/chats/around", json={"target": "discord_1", "user_id": "7", "mid": "204", "dir": "older", "limit": 5}).json()
check("the account stopped: from what is kept", r.get("offline") and [m["mid"] for m in r["messages"]] == ["201", "202", "203"])
check("which way is one of four", client.post("/api/chats/around", json={"target": "discord_1", "user_id": "7", "mid": "1", "dir": "up"}).status_code == 400)
r = client.post("/api/chats/export", json={"target": "discord_1", "user_id": "7", "name": "Ry", "me": "Me"}).json()
check("a chat saved as text", r["count"] == 6 and "Ry: On va au Café" in r["text"])

answers["chat_history"] = {"ok": True, "messages": [{"mid": "sabc", "mine": False, "ts": t, "text": "hi"}]}
r = client.post("/api/chats/history", json={"target": "snapchat_1", "user_id": "chat-1"})
check("a Snapchat chat is read like a Discord one", r.status_code == 200 and asked[-1][:2] == ("snap", "chat_history"))
answers["send_message"] = {"ok": True, "mid": "sdef", "ts": t}
r = client.post("/api/chats/send", json={"target": "snapchat_1", "user_id": "chat-1", "text": "hey"})
check("and written to", r.status_code == 200 and asked[-1][:2] == ("snap", "send_message") and asked[-1][2]["text"] == "hey")
check("routes: snapchat waits longer, its page is shared with the bot",
      "timeout=60.0 if _is_snap(tgt) else 25.0" in app_src("app/web/routes/chat_routes.py")
      and "160.0 if _is_snap(tgt)" in app_src("app/web/routes/chat_routes.py"))
check("Snapchat's events go into the server's list too", chat_routes._ipc_target_for("snapchat_1") == "snap"
      and chat_routes._ipc_target_for("snapchat_2") == "snap2" and chat_routes._ipc_target_for("discord_3") == 3)

print("\n== Snapchat's people ==")
from app.utils import snappeople  # noqa: E402

snappeople.PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
(snappeople.PEOPLE_DIR / "1_chat-1.webp").write_bytes(b"RIFF....WEBPVP8 " + b"x" * 200)
(snappeople.PEOPLE_DIR / "contacts_1.json").write_text(json.dumps({
    "chat-1": {"name": "Step", "file": "1_chat-1.webp", "url": "https://cf-st.sc-cdn.net/x"},
    "chat-2": {"name": "Alex", "file": "../../evil.webp"},
}), encoding="utf-8")
check("a chat's picture, by the file the runner named for it", snappeople.avatar_url(1, "chat-1").startswith("/api/chats/snap-picture/1/chat-1?v="))
check("never a file named for something else", snappeople.picture_path(1, "chat-2") is None and snappeople.picture_path(1, "../x") is None)
check("and its name", snappeople.name_of(1, "chat-1") == "Step")
pic = client.get("/api/chats/snap-picture/1/chat-1")
check("served to the panel", pic.status_code == 200 and pic.content.startswith(b"RIFF"))
check("and nothing else", client.get("/api/chats/snap-picture/1/chat-2").status_code == 404)
import app.utils.helpers as helpers  # noqa: E402
helpers.resource_path = lambda rel: os.path.join(str(TMP), rel)
import app.utils.db as db  # noqa: E402
db.resource_path = helpers.resource_path
db.init_db()
from app.utils.db import connect_raw  # noqa: E402

conn = connect_raw()
try:
    conn.execute("INSERT INTO message_log_snap (chat_id, username, ts, account) VALUES (?, ?, ?, ?)", ("chat-1", "Step", t, 1))
    conn.execute("INSERT INTO message_log (user_id, username, ts, account) VALUES (?, ?, ?, ?)", (555, "discordguy", t, 1))
    conn.commit()
finally:
    conn.close()
r = client.get("/api/chats/archive?target=snapchat_1").json()["conversations"]
check("a Snapchat account's answered chats are its own, with their pictures",
      [c["id"] for c in r] == ["chat-1"] and r[0]["avatar"].startswith("/api/chats/snap-picture/") and r[0]["name"] == "Step", str(r))
r = client.get("/api/chats/archive?target=discord_1").json()["conversations"]
check("and a Discord account's, its own", [c["id"] for c in r] == ["555"], str(r))

print("\n== Snapchat's bridge ==")
os.environ["SNAP_ACCOUNT_INDEX"] = "1"
import app.platforms.snapchat_bridge as bridge  # noqa: E402

events = []
bridge._emit_chat = events.append
day_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 3))
today = time.strftime("%Y-%m-%d")
first = [
    {"key": "s1", "mine": False, "text": "old one", "kind": "", "day": day_ago},
    {"key": "s2", "mine": True, "text": "", "kind": "snap", "day": day_ago},
    {"key": "s3", "mine": False, "text": "today hi", "kind": "", "day": today},
]
fresh = bridge._store_transcript("chat-9", "Step", first)
kept = chatlog.conversation(bridge.LOG_ACCOUNT, "chat-9", 10)
check("a first read is kept in order, and is the past: nobody is told of it", [m["mid"] for m in kept] == ["s1", "s2", "s3"] and fresh == [])
check("an earlier day's message has only its day, not a made-up time", kept[0].get("approx") and time.strftime("%Y-%m-%d", time.localtime(kept[0]["ts"])) == day_ago)
check("a Snap that is not words is kept as one", kept[1]["text"] == "[snap]" and kept[1]["kind"] == "snap")
exact_at = (time.time() - 7200) * 1000
bridge._store_transcript("chat-10", "Lou", [{"key": "x1", "mine": False, "text": "see https://a.com", "kind": "", "day": today,
                                           "at": exact_at, "links": [{"url": "https://a.com/", "title": "A"}]}])
x1 = chatlog.conversation(bridge.LOG_ACCOUNT, "chat-10", 5)[0]
check("a message the page gave a time for is kept at that time, exactly, with its link",
      abs(x1["ts"] - exact_at / 1000) < 0.01 and not x1.get("approx") and x1["embeds"][0]["url"] == "https://a.com/")
again = bridge._store_transcript("chat-9", "Step", first + [{"key": "s4", "mine": False, "text": "new!", "kind": "", "day": today},
                                                           {"key": "s5", "mine": True, "text": "answer", "kind": "", "day": today}])
check("read again, what is new at the end is told", [m["mid"] for m in again] == ["s4", "s5"] and not again[0].get("approx"))
ts = [m["ts"] for m in chatlog.conversation(bridge.LOG_ACCOUNT, "chat-9", 10)]
check("in order, and at about the moment it was seen", ts == sorted(ts) and abs(ts[-1] - time.time()) < 5)
bridge._announce("chat-9", "Step", again)
kinds = [e["t"] for e in events]
check("theirs as a message, the account's as sent, and then answered", kinds == ["msg", "sent", "done"], str(kinds))
check("with the chat's picture", events[0].get("avatar") == "" or events[0]["avatar"].startswith("/api/"))
bridge.RESPONSES_FILE = TMP / "ipc" / "snap_responses_test.json"
bridge.RESPONSES_FILE.parent.mkdir(parents=True, exist_ok=True)
bridge.RESPONSES_FILE.write_text(json.dumps({"a": {"text": "x", "chat": "chat-9"}, "b": {"text": "y", "chat": "other"}}), encoding="utf-8")
check("writing to them yourself takes back the reply the bot had ready", bridge._drop_lined_up("chat-9")
      and list(json.loads(bridge.RESPONSES_FILE.read_text(encoding="utf-8"))) == ["b"] and "chat-9" in bridge._ANSWERED_BY_HAND)
results = {}
bridge._write_result = lambda cmd_id, data: results.__setitem__(cmd_id, data)


async def fake_panel(op, timeout=60.0, **kw):
    if op == "history":
        return {"ok": True, "messages": first}
    return {"ok": True, "sent": "s9", "messages": first + [{"key": "s9", "mine": True, "text": kw.get("text", ""), "kind": "", "day": today}]}

bridge._panel = fake_panel
asyncio.run(bridge._history_cmd("h1", {"user_id": "chat-9", "limit": 10}))
check("the tab opening a chat gets it as the tab draws it", results["h1"]["ok"] and [m["mid"] for m in results["h1"]["messages"]][:3] == ["s1", "s2", "s3"])
asyncio.run(bridge._send_cmd("s1", {"user_id": "chat-9", "text": "from the panel"}))
check("a message sent from the tab: its key, so it is never there twice", results["s1"]["ok"] and results["s1"]["mid"] == "s9")
check("and the bot's memory has it as the account's own words",
      bridge.engine.message_history.get("chat-9-chat-9", [{}])[-1] == {"role": "assistant", "content": "from the panel"})
png = base64.b64encode(b"\x89PNG" + b"0" * 64).decode()
asyncio.run(bridge._send_cmd("s2", {"user_id": "chat-9", "files": [{"name": "a.pdf", "data": png}]}))
check("only pictures go to Snapchat from here", not results["s2"]["ok"] and "pictures" in results["s2"]["reason"])
src = app_src("app/platforms/snapchat_bridge.py")
check("its answer to a chat answered by hand is not sent", "_ANSWERED_BY_HAND.get(chat_id, 0) >= began" in src
      and "if response and _held_back(channel_id, user_name, began):" in src)
check("the conversation comes over the socket as one long line", "limit=8 * 1024 * 1024" in src)
check("events and the runner's lines take turns on the output", src.count("with _OUT_LOCK:") == 2)
check("the list's rows have their picture and their latest message", '"avatar": snappeople.avatar_url(ACCOUNT_INDEX, chat_id)' in src
      and "_last_theirs(chat_id)" in src)

print("\n== Snapchat's runner ==")
runner = app_src("app/platforms/snapchat/snapchat_runner.js")
bot = app_src("app/platforms/snapchat/snapbot.js")
check("the panel's requests over the wake socket, done between the bot's own steps",
      'msg.kind === "panel"' in runner and runner.count("await processPanel(bot)") >= 2 and "try { await processPanel(bot); }" in runner)
check("a chat read for the panel is read the bot's own way when something new was in it, so it is still answered",
      "await readChat(bot, chatId, name)" in runner and "const wasUnread = req.op === \"history\" ? await bot.isUnread(chatId) : false;" in runner
      and "if (wasUnread && !SYSTEM_CHATS.includes(" in runner and "async isUnread(chatId)" in bot)
check("each message keyed by its chat, day, side, words and which of the same", "createHash(\"sha1\").update(`${base}|${n}`)" in runner)
check("what the bot reads and sends goes to the panel", runner.count("await shareTranscript(bot,") == 3)
check("each chat's picture read off the list and saved", "rememberContacts(recipients)" in runner and "contacts_${ACCOUNT_INDEX}.json" in runner
      and bot.count('avatar: img ? img.currentSrc || img.src || "" : ""') == 1 and "const avatar = img ? img.currentSrc" in bot)
check("a conversation read whole, without a click or a hover", "async readConversation(chatId, " in bot)
check("a day line is a time straight in its row; a group's header time is when it was sent, read exactly",
      bot.count('li.querySelector(":scope > time")') == 1 and 'li.querySelector(":scope > time span")' in bot
      and 'header.querySelector("time[datetime]")' in bot and "m.at ? isoDay(new Date(m.at))" in runner)
check("a chat Snapchat no longer lists is opened through its search, by exact name, and the search emptied after",
      "async openViaSearch(name)" in bot and "await bot.openViaSearch(name)" in runner and "if (searched) await bot.clearSearch();" in runner
      and "def _name_for(chat: str)" in app_src("app/platforms/snapchat_bridge.py"))
node_check = subprocess.run(["node", "--check", str(ROOT / "app" / "platforms" / "snapchat" / "snapchat_runner.js")],
                            capture_output=True, text=True)
check("the runner still parses", node_check.returncode == 0, node_check.stderr[-300:])

print("\n== the Discord runner ==")
dr = app_src("app/platforms/discord_runner.py")
check("Discord's search, on its own allowance", "_search_budget = SlidingWindow(limit=24, window_seconds=300)" in dr
      and "async for m in dm.search(**kw):" in dr)
check("newest and oldest page on by the last one shown, the best matches by offset",
      'kw["before"] = discord.Object(id=int(cursor))' in dr and 'kw["most_relevant"] = True' in dr)
check("a stretch of history around, before, after a message, or the first ones",
      "async def _window_job(" in dr and '{"around": discord.Object(id=mid)}' in dr and '{"after": discord.Object(id=1), "oldest_first": True}' in dr)
check("both off the command loop", 'asyncio.create_task(_search_job(cmd_id, payload))' in dr and 'asyncio.create_task(_window_job(cmd_id, payload))' in dr)

print("\n== the page ==")
chats = read("pages/Chats.svelte")
check("a search over the list, and filters with how many each has", 'placeholder="Search chats"' in chats
      and '{ id: "drafts", label: "Drafts"' in chats and "listChips.length > 1" in chats)
check("found in what was said, across every chat", "api.chatsSearchAll(t," in chats and "openFromSearch(p, String(m.mid))" in chats)
check("and with nobody waiting, the same search over the recent conversations",
      'class="ch-find-box ch-recent-find"' in chats and "recentShown.slice(0, showAllRecent || searchingList" in chats
      and chats.count("openFromSearch(p, String(m.mid))") == 2)
check("buttons by the name: search, pictures and videos, files, links, more",
      all(f'toggleTools("{k}")' in chats for k in ("search", "media", "files", "links")) and "onclick={moreMenu}" in chats)
check("Ctrl+F searches the chat", 'e.key.toLowerCase() === "f" && canTools' in chats)
check("a message gone to is lit up, and an older stretch has its way back", "class:is-flash=" in chats
      and "data-mid={d.m.mid ?? null}" in chats and "Viewing older messages" in chats and "Jump to now" in chats)
check("scrolling to the top reads further back, keeping your place", "if (convBox.scrollTop < 160) void earlier();" in chats
      and "box.scrollTop = box.scrollHeight - h + top;" in chats)
check("a new message does not pull you down while you read further up", "if (!opened && !atBottom && !mine) return;" in chats)
check("drafts kept per conversation, and shown in the list", "setDraft(draftKey, e.currentTarget.value)" in chats
      and '<span class="ch-draft">Draft:</span>' in chats and "void loadDrafts();" in chats)
check("files dropped onto the conversation, and nowhere else opens them", "ondrop={onDrop}" in chats
      and "Drop to add to your message" in chats and "ondrop={guardDrop}" in chats)
check("the chat saved as text, and the first message", "saveTextFile(`Chat with ${safe}.txt`, r.text)" in chats and "jumpFirst()" in chats)
check("Snapchat's chats have the box to write in and their history too", "{#if !isSnap}" not in chats
      and "if (target && selectedId) loadConversation(target, selectedId);" in chats)
check("no hint under the box", "Sending this drops the reply" not in chats)
lib = read("lib/chats.ts")
check("drafts written a moment after typing stops, on the server too", '"chatDrafts"' in lib and "setTimeout(() => {" in lib
      and '"chatDrafts",' in app_src("app/web/routes/prefs_routes.py"))
check("the server's drafts are only read once and never wiped by an empty window",
      "draftsRead ??=" in lib and "if (draftsReady) pushDrafts();" in lib)
check("scrolling back asks for the 50 before the first shown", 'api.chatsWindow(uid, target, "older", String(first.mid), 50)' in lib)
check("a long conversation is not cut back to its last few dozen", "const KEEP_DRAWN = 1500;" in lib and ".slice(-60)" not in lib)
tools = read("lib/components/ChatTools.svelte")
search = read("lib/components/ChatSearch.svelte")
shared = read("lib/components/ChatShared.svelte")
check("the panel: four tabs, each kept as it was", all(f'id: "{k}"' in tools for k in ("search", "media", "files", "links"))
      and 'class:is-hidden={tab !== t.id}' in tools)
check("the search: chips, suggestions, results by day, Discord on Enter", "takeFilters(text, filters, them)" in search
      and 'role="listbox" aria-label="Suggestions"' in search and "dayLabel(m.ts)" in search and "if (discord) runRemote();" in search)
check("deleted ones put back among Discord's results", "if (!m.deleted || have.has(m.mid)) continue;" in search)
check("what was shared: a grid, a list, large with arrows, older from Discord", 'class="sh-grid"' in shared and 'class="sh-list"' in shared
      and 'e.key === "ArrowRight"' in shared and "Older on Discord" in shared)
api = read("lib/api.ts")
check("the calls", all(k in api for k in ("chatsSearch:", "chatsSearchDiscord:", "chatsSearchAll:", "chatsShared:", "chatsWindow:", "chatsExport:")))
card = read("lib/accounts/AccountCard.svelte")
check("an account's @username can be selected, copied in a click, and from the right-click menu",
      '<span class="selectable acct-handle truncate">@{handle}</span>' in card and "onclick={copyHandle}" in card
      and 'label: "Copy username"' in card)
check("the Dashboard's accounts too", "accountMenu(r)" in read("lib/dashboard/AccountsWidget.svelte"))
check("Snapchat's Snaps and calls said plainly", '"Sent a Snap"' in read("lib/components/MessageBody.svelte"))
settings = read("pages/Settings.svelte")
check("the restart badge, with its arrow", 'class="settings-restart"' in settings and ".settings-restart {" in read("app.css"))

print("\n== the search logic, under Node ==")
proc = subprocess.run(["node", str(ROOT / "tests" / "chatsearch_logic.mjs")], capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=120)
tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-300:]
check("chatsearch_logic.mjs passes", proc.returncode == 0 and tail.endswith("0 failed"), tail)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
