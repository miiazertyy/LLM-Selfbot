"""Snapchat, everywhere Discord is.

  * its people named and pictured on the Memory page, on a name's card and in the ignored list, and their names
    clickable wherever names are
  * summaries and "what do you think of them" read from the chat log, not only from what this run saw
  * friend requests read off its own requests panel and answered from the tab; accepted on their own after the same
    wait as Discord's, pressing Accept before any Add
  * where each reply is, on the Chats tab's tracker; the chance of leaving one unanswered; a reply cancelled while it
    is written or paced
  * the conversation before a first reply picked up from the chat log; Reply answering what the log kept
  * nudges for messages left unanswered; a picture's description written by hand; quiet hours on the account card
  * the typing dots; Big Picture's recent conversations, account details and friend requests for every account
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-snapparity-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
_cfg = yaml.safe_load((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"))
_cfg["bot"].setdefault("nudge", {})["enabled"] = True
(TMP / "config" / "config.yaml").write_text(yaml.safe_dump(_cfg, allow_unicode=True), encoding="utf-8")
(TMP / "config" / "instructions.txt").write_text("You are Lou.", encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
os.environ["SNAP_ACCOUNT_INDEX"] = "1"
os.environ.pop("SNAP_QUIET_HOURS", None)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def src(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


now = time.time()
import app.utils.db as db  # noqa: E402
from app.utils.db import connect_raw  # noqa: E402

db.init_db()
from app.utils.memory import init_memory, set_memory  # noqa: E402

init_memory()
conn = connect_raw()
try:
    conn.executemany("INSERT INTO message_log_snap (chat_id, username, ts, account) VALUES (?, ?, ?, ?)", [
        ("chat-a", "ana.s", now - 86400 * 10, 1), ("chat-a", "ana.s", now - 3600, 1)])
    conn.execute("INSERT INTO user_stats_snap (chat_id, username, message_count, first_seen) VALUES (?, ?, ?, ?)",
                 ("chat-b", "Bo", 3, now - 5000))
    conn.commit()
finally:
    conn.close()

print("== who a Snapchat chat is ==")
from app.utils import snappeople  # noqa: E402

snappeople.PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
(snappeople.PEOPLE_DIR / "1_chat-a.webp").write_bytes(b"RIFF....WEBPVP8 " + b"x" * 64)
(snappeople.PEOPLE_DIR / "contacts_1.json").write_text(json.dumps({"chat-a": {"name": "Ana S", "file": "1_chat-a.webp"}}),
                                                       encoding="utf-8")
info = snappeople.describe(["chat-a", "chat-b", "12345", ""])
a = info.get("chat-a") or {}
check("named and pictured as the chat list shows them", a.get("name") == "Ana S" and a.get("avatar", "").startswith("/api/chats/snap-picture/1/chat-a"), str(a))
check("with how much they wrote, and when", a.get("messages") == 2 and a.get("messages_7d") == 1
      and abs(a.get("first_seen", 0) - (now - 86400 * 10)) < 2 and abs(a.get("last_seen", 0) - (now - 3600)) < 2, str(a))
check("someone the list no longer shows keeps the name the bot logged", (info.get("chat-b") or {}).get("name") == "Bo", str(info.get("chat-b")))
check("a Discord id is left to Discord's own", "12345" not in info and "" not in info)

print("\n== the panel's pages ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.core import ipc  # noqa: E402
from app.web.routes import chat_routes, people_routes  # noqa: E402

ipc.discover_targets = lambda: {
    "discord_1": {"platform": "discord", "account": 1, "target": 1},
    "snapchat_1": {"platform": "snapchat", "account": 1, "target": "snap"},
}
asked, answers = [], {}


async def fake_send(target, cmd, payload=None, timeout=10.0):
    asked.append((target, cmd, payload, timeout))
    return answers.get(cmd)

ipc.send_and_wait = fake_send
app = FastAPI()
app.include_router(chat_routes.router)
app.include_router(people_routes.router)
client = TestClient(app)

set_memory("chat-a", "likes", "cats")
users = client.get("/api/memory").json()["users"]
row = next((u for u in users if u["user_id"] == "chat-a"), {})
check("the Memory page: a Snapchat person by name and picture, not by chat id",
      row.get("display_name") == "Ana S" and row.get("avatar", "").startswith("/api/") and row.get("platform") == "snapchat"
      and row.get("messages") == 2 and row.get("last_seen"), str(row))
card = client.get("/api/people/chat-a").json()
check("their card: name, picture, Snapchat, and how much they talk",
      card.get("display_name") == "Ana S" and card.get("platform") == "snapchat" and card.get("messages") == 2
      and card.get("messages_7d") == 1 and card.get("facts", {}).get("likes") == "cats", str(card))
db.add_ignored_user_snap("chat-a")
people = client.get("/api/chats/ignored?target=snapchat_1").json()["people"]
check("the ignored list names them too", people and people[0]["name"] == "Ana S" and people[0]["avatar"].startswith("/api/"), str(people))
answers["friends_pending"] = {"ok": True, "requests": [{"id": "Zoe", "username": "", "display_name": "Zoe", "incoming": True}]}
r = client.get("/api/friends?target=snapchat_1").json()
check("friend requests: Snapchat's, read off its own panel", r.get("supported") is True and r["requests"][0]["id"] == "Zoe"
      and asked[-1][:2] == ("snap", "friends_pending") and asked[-1][3] >= 60, str(r))
answers["friend_accept"] = {"ok": True}
r = client.post("/api/friends/accept", json={"target": "snapchat_1", "user_id": "Zoe"}).json()
check("and accepted from the tab, by the name it shows", r.get("ok") and asked[-1][1] == "friend_accept" and asked[-1][2] == {"user_id": "Zoe"})
check("a Discord one still wants its number", client.post("/api/friends/accept", json={"target": "discord_1", "user_id": "Zoe"}).status_code == 400)

print("\n== Snapchat's bridge ==")
from app.utils import chatlog  # noqa: E402
import app.platforms.snapchat_bridge as bridge  # noqa: E402

events, results = [], {}
bridge._emit_chat = events.append
bridge._write_result = lambda cmd_id, data: results.__setitem__(cmd_id, data)
L = bridge.LOG_ACCOUNT


def run(coro):
    return asyncio.run(coro)


async def settle(coro):
    await coro
    for _ in range(50):
        busy = [t for t in (bridge._SUMMARY_TASKS | bridge._PANEL_TASKS) if not t.done()]
        if not busy:
            return
        await asyncio.gather(*busy, return_exceptions=True)

# Where each reply is.
bridge._set_state("chat-t", "writing")
check("a reply being written is on the tracker, as Discord's are", events[-1] == {"t": "state", "uid": "chat-t", "state": bridge._REPLY_STATE["chat-t"]}
      and bridge._REPLY_STATE["chat-t"]["state"] == "writing")
bridge._set_state("chat-t", "cooldown", eta=now + 30)
bridge.CHAT_NAMES["chat-t"] = "Tia"
bridge._REPLY_STATE["chat-old"] = {"state": "sending", "since": now - 1000, "eta": None, "reason": ""}
bridge._REPLY_STATE["chat-quiet"] = {"state": "cooldown", "since": now - 1000, "eta": now + 3600, "reason": ""}
run(bridge._handle_command("reply_check", {}, "rc1"))
rows = {u["id"]: u for u in results["rc1"]["users"]}
check("the waiting list has whoever is being answered, with where their reply is", rows.get("chat-t", {}).get("state", {}).get("state") == "cooldown"
      and rows["chat-t"]["name"] == "Tia", str(rows.get("chat-t")))
check("and says whether the account is paused", results["rc1"].get("paused") is False)
check("one never sent a quarter of an hour on is not typing for ever", "chat-old" not in rows and "chat-old" not in bridge._REPLY_STATE)
check("one waiting out the quiet hours stays, with when it goes", "chat-quiet" in rows)
events.clear()
bridge._announce("chat-t", "Tia", [{"mid": "z1", "mine": True, "ts": now, "text": "hey"}])
check("sent: off the list, and the tracker let go", [e["t"] for e in events] == ["sent", "done"] and "chat-t" not in bridge._REPLY_STATE)

began = time.time() - 1
bridge._CANCELLED["chat-c"] = time.time()
check("cancelled while written or paced: not sent", bridge._held_back("chat-c", "C", began)
      and bridge._REPLY_STATE["chat-c"]["reason"] == "you cancelled the reply")
bridge.STATE["ignore_users"].add("chat-d")
check("the bot turned off for them meanwhile: not sent", bridge._held_back("chat-d", "D", began))
bridge._ANSWERED_BY_HAND["chat-e"] = time.time()
check("answered by hand meanwhile: not sent, and it says why", bridge._held_back("chat-e", "E", began)
      and bridge._REPLY_STATE["chat-e"]["reason"] == "you answered them yourself")
check("otherwise it goes", not bridge._held_back("chat-f", "F", began))
bridge.STATE["ignore_users"].discard("chat-d")
bridge._REPLY_STATE["chat-g"] = {"state": "writing", "since": now, "eta": None, "reason": ""}
run(bridge._handle_command("cancel_reply", {"user_id": "chat-g"}, "cr1"))
check("Cancel stops one being written, and says so", results["cr1"]["stopped"] and "chat-g" in bridge._CANCELLED
      and bridge._REPLY_STATE["chat-g"]["reason"] == "you cancelled the reply")

events.clear()
run(bridge._handle_command("ignore_add", {"user_id": "chat-i"}, "ig1"))
check("Bot off: the tab is told, and why it won't answer", {"t": "ignored", "uid": "chat-i", "ignored": True} in events
      and bridge._REPLY_STATE["chat-i"]["reason"] == "you are ignoring them")
run(bridge._handle_command("ignore_remove", {"user_id": "chat-i"}, "ig2"))
check("and back on", {"t": "ignored", "uid": "chat-i", "ignored": False} in events and "chat-i" not in bridge._REPLY_STATE)
run(bridge._handle_command("pause", {}, "p1"))
check("pausing the account is told to the tab", {"t": "meta", "paused": True, "cooldown_until": 0} in events)
run(bridge._handle_command("pause", {}, "p2"))

# The conversation before, from the chat log.
chatlog.put_many(L, "chat-s", [("k1", False, now - 600, {"text": "hi"}), ("k2", True, now - 590, {"text": "hey you"}),
                               ("k3", False, now - 30, {"text": "what are you up to"})])
bridge.engine.message_history.pop("chat-s-chat-s", None)
bridge._seed_history("chat-s", now - 20)
hist = bridge.engine.message_history.get("chat-s-chat-s", [])
check("a first reply after a restart starts from the conversation kept, as Discord's does",
      hist == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey you"}], str(hist))
bridge._seed_history("chat-s", now)
check("only once", bridge.engine.message_history["chat-s-chat-s"] == hist)
check("what they wrote since the account last did", bridge._kept_unanswered("chat-s") == "what are you up to")

chatlog.put_many(L, "chat-r", [("r1", True, now - 900, {"text": "night"}), ("r2", False, now - 60, {"text": "you there?"})])
seen = []


async def fake_generate(msg):
    seen.append(msg.content)
    return "yeah im here"

bridge.generate_ai_response = fake_generate
events.clear()
ok, why = run(bridge._reply_to_chat("chat-r"))
out = json.loads(bridge.OUTGOING_FILE.read_text(encoding="utf-8")) if bridge.OUTGOING_FILE.exists() else []
check("Reply answers what the log kept when this run has nothing waiting", ok and seen == ["you there?"]
      and any(e.get("chat") == "chat-r" for e in out), f"{ok} {why} {seen}")
check("and the tracker follows it", [e["state"]["state"] for e in events if e["t"] == "state"] == ["writing", "sending"])
chatlog.put_many(L, "chat-q", [("q1", False, now - 30, {"text": "u up"})])
run(settle(bridge._handle_command("reply_user", {"user_id": "chat-q"}, "ru1")))
check("a Reply says its answer is written and waiting to be sent, so Stop on Reply to all can still take it back",
      results.get("ru1") == {"success": True, "queued": True}, str(results.get("ru1")))

# Summaries and opinions from the log.
chatlog.put_many(L, "chat-m", [(f"m{i}", i % 2 == 1, now - 1000 + i, {"text": f"line {i}"}) for i in range(10)])
bridge.CHAT_NAMES["chat-m"] = "Mo"
got = {}


async def fake_summary(lines, name, length, language):
    got["lines"], got["name"] = lines, name
    return "They talk about lines."

import app.utils.ai as ai  # noqa: E402
ai.summarize_conversation = fake_summary
run(settle(bridge._handle_command("summarize_user", {"user_id": "chat-m", "count": 20}, "su1")))
check("a summary reads the chat log when this run has seen less of it",
      results.get("su1", {}).get("ok") and len(got.get("lines", [])) == 10 and got["lines"][0] == ("Mo", "line 0")
      and got["lines"][1] == ("Me", "line 1"), str(results.get("su1")))
prompts = []


async def fake_response(prompt, instructions, history=None):
    prompts.append(prompt)
    return "honestly they're fine"

bridge.generate_response = fake_response
run(bridge._handle_command("analyse_user", {"user_id": "chat-m"}, "an1"))
check("and so does what the bot thinks of them: their words only", results["an1"].get("ok") and "line 8" in prompts[-1]
      and "line 9" not in prompts[-1], str(results["an1"]))

# Friend requests.
calls = []


async def fake_panel(op, timeout=60.0, **kw):
    calls.append((op, kw))
    if op == "friends":
        return {"ok": True, "requests": [{"name": "Zoe", "username": "zoe.k", "avatar": ""}]}
    if op == "friend":
        return {"ok": True}
    return {"ok": False}

bridge._panel = fake_panel
run(bridge._friends_cmd("f1"))
check("friend requests off Snapchat's own panel", results["f1"]["ok"] and results["f1"]["requests"][0]["id"] == "Zoe"
      and results["f1"]["requests"][0]["username"] == "zoe.k")


async def busy_panel(op, timeout=60.0, **kw):
    return {"ok": False, "reason": "busy"}

bridge._panel = busy_panel
run(bridge._friends_cmd("f2"))
check("the runner busy with a reply: the ones it last read, not an error", results["f2"]["ok"] and results["f2"].get("stale")
      and results["f2"]["requests"][0]["id"] == "Zoe")
bridge._panel = fake_panel
run(bridge._friend_answer_cmd("fa1", "Zoe", True))
check("accepted from the tab", results["fa1"]["ok"] and calls[-1] == ("friend", {"name": "Zoe", "accept": True})
      and not bridge._FRIEND_REQUESTS)

# Nudges.
bridge._note_unanswered("chat-n", "you up?")
check("a message being answered is kept for a nudge", "chat-n" in json.loads(bridge.UNANSWERED_FILE.read_text(encoding="utf-8")))
bridge._announce("chat-n", "N", [{"mid": "n9", "mine": True, "ts": now, "text": "yes"}])
check("and let go of once the account has spoken", "chat-n" not in json.loads(bridge.UNANSWERED_FILE.read_text(encoding="utf-8")))
bridge.UNANSWERED_FILE.write_text(json.dumps({
    "chat-n1": {"content": "did you see my story", "received_at": now - 3 * 86400, "nudged": False},
    "chat-n2": {"content": "ok", "received_at": now - 3 * 86400, "nudged": False},
    "chat-n3": {"content": "later", "received_at": now - 600, "nudged": False}}), encoding="utf-8")
chatlog.put_many(L, "chat-n1", [("q1", False, now - 3 * 86400, {"text": "did you see my story"})])
chatlog.put_many(L, "chat-n2", [("q2", False, now - 3 * 86400, {"text": "ok"}), ("q3", True, now - 2 * 86400, {"text": "yeah"})])
nudged = []


async def fake_nudge(original, days, instructions):
    nudged.append((original, round(days)))
    return "omg just saw this, yes i did"

ai.generate_nudge = fake_nudge
_uniform = bridge.random.uniform
bridge.random.uniform = lambda lo, hi: 0.0
try:
    run(bridge._send_nudges(2 * 86400))
finally:
    bridge.random.uniform = _uniform
left = json.loads(bridge.UNANSWERED_FILE.read_text(encoding="utf-8"))
out = json.loads(bridge.OUTGOING_FILE.read_text(encoding="utf-8"))
check("a message left unanswered for days is answered after all, once", nudged == [("did you see my story", 3)]
      and left["chat-n1"]["nudged"] and any(e.get("chat") == "chat-n1" for e in out), str(nudged))
check("not when the account already had the last word", "chat-n2" not in left)
check("not before the threshold", left["chat-n3"]["nudged"] is False)

# A picture's description written by hand.
pics = TMP / "config" / "pictures"
pics.mkdir(parents=True, exist_ok=True)
(pics / "IMG_1.png").write_bytes(b"\x89PNG" + b"0" * 32)
run(bridge._handle_image_command("image_setdesc", {"name": "1", "description": "me at the beach"}, "is1"))
check("a picture's description set by hand, as on Discord", results["is1"].get("ok") and results["is1"]["name"] == "IMG_1.png")
run(bridge._handle_image_command("image_setdesc", {"name": "../x.png", "description": "x"}, "is2"))
check("never a file outside the pictures", not results["is2"].get("ok"))
check("and the command goes there", '"image_analyse", "image_setdesc", "image_delete"' in src("app/platforms/snapchat_bridge.py"))

# Quiet hours.
hour = time.localtime().tm_hour
os.environ["SNAP_QUIET_HOURS"] = f"{hour}-{(hour + 2) % 24}"
until = bridge._quiet_until()
check("inside the quiet hours: when they end", until is not None and now < until <= now + 2 * 3600 + 5, str(until))
run(bridge._handle_command("get_status", {}, "gs1"))
check("and the account card hears of it", results["gs1"].get("night") is True)
os.environ["SNAP_QUIET_HOURS"] = f"{(hour + 3) % 24}-{(hour + 5) % 24}"
check("outside them: none", bridge._quiet_until() is None)
os.environ.pop("SNAP_QUIET_HOURS", None)

bsrc = src("app/platforms/snapchat_bridge.py")
check("the chance of leaving a message unanswered, as on Discord", '(load_config().get("bot") or {}).get("ignore_chance")' in bsrc
      and 'reason="left unanswered on purpose (the ignore chance)"' in bsrc)
check("the typing dots, from Snapchat's chat list", 'msg.get("kind") == "typing"' in bsrc and '_emit_chat({"t": "typing", "uid": str(msg["chat"])})' in bsrc)
check("nudges run beside the bot's own loop", "_nudge_loop()]" in bsrc)
check("accepting friend requests waits as Discord's does", '("accept_delay_min", "SNAP_ACCEPT_DELAY_MIN")' in bsrc)

print("\n== Snapchat's runner ==")
runner = src("app/platforms/snapchat/snapchat_runner.js")
bot = src("app/platforms/snapchat/snapbot.js")
check("someone typing, told to the panel", 'tellPython({ kind: "typing", chat: r.id })' in runner
      and "typing = /\\btyping|is writing" in bot)
check("friend requests read and answered between the bot's steps, read at most every three minutes",
      'if (req.op === "friends")' in runner and "Date.now() - friendRequestsAt > 180000" in runner and "await bot.answerFriendRequest(" in runner)
check("only ever Accept for a request: Quick Add's Add buttons are strangers",
      bot.count('const isAdd = (t) => /^(accept|accepter)\\b/i.test((t || "").trim());') == 2)
check("nothing opened while no request is waiting", "if (!(await this.hasPendingFriendBadge())) return [];" in bot)
check("Chrome that updated itself overnight is started again: what it left on the profile closed first, hidden",
      "this.browser = await launchChrome(options);" in bot and "closeChromeOn(options.userDataDir);" in bot
      and "windowsHide: true" in bot and "Failed to launch the browser process" in bot)
check("the accepter of its own waits, and presses Accept before any Add",
      "if (!(await bot.hasPendingFriendBadge()))" in runner and "ACCEPT_DELAY_MAX > 0" in runner
      and "|| visible.find((b) => {" in bot)

print("\n== the panel ==")
bp = src("webui/src/lib/bigpicture/BigPicture.svelte")
check("Big Picture's recent conversations: every account's", "api.chatArchive(12, id)" in bp and "if (seq !== recentSeq) return;" in bp)
check("its account details and friend requests: Snapchat's too", 'a.state === "running" ? api.accountDetails(a.id)' in bp
      and 'const targets = accts.filter((a) => a.state === "running");' in bp)
check("and its friend requests say whose account they are on", "accounts.length > 1);" in src("webui/src/lib/bigpicture/BPFriends.svelte"))
for rel in ("webui/src/lib/components/StatDetail.svelte", "webui/src/lib/accounts/AccountCard.svelte", "webui/src/lib/dashboard/WidgetBody.svelte"):
    s = src(rel)
    check(f"names clickable for Snapchat people too: {rel.rsplit('/', 1)[-1]}", "<UserChip id={t.id} name={t.name} />" in s
          and 'platform === "discord"}<UserChip' not in s and '{#if t.platform === "discord"}' not in s)
chip = src("webui/src/lib/components/UserChip.svelte")
check("a Snapchat person's card says Snapchat, not a chat id", 'silhouette={person?.platform === "snapchat"}' in chip
      and '<Icon name="snapchat" size={10} /> Snapchat' in chip)
mem = src("webui/src/pages/Memory.svelte")
check("the Memory page marks Snapchat people", 'silhouette={u.platform === "snapchat"}' in mem and ".mem-snap {" in mem)
chats = src("webui/src/pages/Chats.svelte")
check("a Snapchat friend request on the Chats tab", "silhouette={isSnap} />" in chats and "wants to be friends" in chats
      and '`${isSnap ? "Snapchat" : "Discord"} refused that`' in chats)
check("the account card in the quiet hours", '"Quiet hours, replies wait"' in src("webui/src/lib/accounts/condition.ts"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
