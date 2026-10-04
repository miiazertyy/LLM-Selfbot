"""Reacting to messages from the Chats tab, on Discord and on Snapchat.

The tab showed reactions and could not add one. Now a message has React beside it, a reaction under it can be
pressed to add the account's own or take it back, and each platform offers its own: any emoji on Discord, and on
Snapchat the eight its React picker has, one per person on a message, picked on its page the way a person does
(tried on a real account: hover the message, press React, pick, and pressing the chosen one again takes it back).

Checked here: the chat log keeps reactions current (added, taken back, by whom); the route hands the reaction to
the account and says plainly when it did not take; Snapchat's bridge refuses what Snapchat does not have, keeps
what the page says after, and notices reactions that changed on messages it already kept; Snapchat's eight are the
same everywhere they are listed; and the Discord runner reacts, and hears reactions live.
"""
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-reactions-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
shutil.copy(ROOT / "resources" / "config.yaml", TMP / "config" / "config.yaml")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import chatlog  # noqa: E402

print("== the chat log keeps them current ==")
heart, custom = {"name": "❤️"}, {"name": "pog", "url": "https://cdn.discordapp.com/emojis/1.webp?size=44"}
r = chatlog.apply_reaction([], heart, 1, False)
check("someone's reaction is added", r == [{"name": "❤️", "count": 1, "mine": False}], str(r))
r = chatlog.apply_reaction(r, heart, 1, True)
check("the account's on top of it: two, one of them its own", r == [{"name": "❤️", "count": 2, "mine": True}], str(r))
r = chatlog.apply_reaction(r, heart, -1, True)
check("taken back: one left, not its own", r == [{"name": "❤️", "count": 1, "mine": False}], str(r))
r = chatlog.apply_reaction(r, heart, -1, False)
check("the last one taken back: gone", r == [], str(r))
r = chatlog.apply_reaction([], custom, 1, True)
check("a custom emoji by its picture", r == [{"name": "pog", "url": custom["url"], "count": 1, "mine": True}], str(r))

chatlog.put(1, "42", "m1", False, 100.0, {"text": "hey"})
uid, now = chatlog.bump_reaction(1, "m1", heart, 1, True)
check("a reaction on a kept message: whose conversation, and what is on it now",
      uid == "42" and now == [{"name": "❤️", "count": 1, "mine": True}], f"{uid} {now}")
check("kept with the message", chatlog.conversation(1, "42")[0]["reactions"] == now)
check("one on a message not kept here: nothing", chatlog.bump_reaction(1, "nope", heart, 1, True) == (None, []))
chatlog.set_reactions(1, "m1", [])
check("set to none, it has none", "reactions" not in chatlog.conversation(1, "42")[0])
chatlog.put(1, "42", "m2", True, 101.0, {"text": "yo", "reactions": [{"name": "😂", "count": 1, "mine": False}]})
changed = chatlog.sync_reactions(1, {"m1": [], "m2": [{"name": "😂", "count": 1, "mine": False}],
                                     "gone": [{"name": "x", "count": 1}]})
check("synced from what a page shows: nothing changed, nothing written", changed == [], str(changed))
changed = chatlog.sync_reactions(1, {"m2": [{"name": "🔥", "count": 1, "mine": True}]})
check("one that changed is written, and named", changed == [("m2", [{"name": "🔥", "count": 1, "mine": True}])]
      and chatlog.conversation(1, "42")[1]["reactions"][0]["name"] == "🔥", str(changed))

print("\n== the route ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import chat_routes  # noqa: E402

asked = []
answer = {"ok": True}


async def fake_send(target, cmd, payload=None, timeout=10.0):
    asked.append((target, cmd, payload))
    return answer


chat_routes.ipc.send_and_wait = fake_send
targets = {"discord_1": 1, "snap1": "snap1"}
chat_routes._resolve_target = lambda request, explicit=None: targets[explicit or "discord_1"]
app = FastAPI()
app.include_router(chat_routes.router)
client = TestClient(app)
res = client.post("/api/chats/react", json={"user_id": "1234567890123456789", "mid": "99", "emoji": "❤️"})
check("a reaction goes to the account, the id exact", res.status_code == 200 and asked[-1] == (
    1, "react", {"user_id": 1234567890123456789, "mid": "99", "emoji": "❤️", "remove": False}), str(asked[-1:]))
client.post("/api/chats/react", json={"user_id": "chat-a", "mid": "s1", "emoji": "😂", "remove": True, "target": "snap1"})
check("Snapchat's chat ids stay as they are, and taking it back says so",
      asked[-1] == ("snap1", "react", {"user_id": "chat-a", "mid": "s1", "emoji": "😂", "remove": True}), str(asked[-1:]))
check("no message or emoji: refused", client.post("/api/chats/react", json={"user_id": "1", "mid": "", "emoji": "x"}).status_code == 400)
check("a message still being sent: refused", client.post("/api/chats/react", json={"user_id": "1", "mid": "local-3", "emoji": "x"}).status_code == 400)
answer = {"ok": False, "reason": "that message is not there any more"}
res = client.post("/api/chats/react", json={"user_id": "1", "mid": "99", "emoji": "❤️"})
check("the account saying no is said plainly", res.status_code == 409 and res.json()["detail"] == "that message is not there any more")
answer = None
check("an account that does not answer", client.post("/api/chats/react", json={"user_id": "1", "mid": "9", "emoji": "x"}).status_code == 504)

print("\n== Snapchat's bridge ==")
import app.platforms.snapchat_bridge as bridge  # noqa: E402

events, results = [], {}
bridge._emit_chat = events.append
bridge._write_result = lambda cmd_id, data: results.__setitem__(cmd_id, data)
panel_calls = []


async def fake_panel(op, timeout=60.0, **kw):
    panel_calls.append((op, kw))
    return {"ok": True, "reactions": [{"name": kw["emoji"], "count": 1, "mine": True}]}


bridge._panel = fake_panel
L = bridge.LOG_ACCOUNT
chatlog.put(L, "chat-a", "s1", False, 200.0, {"text": "hii"})
asyncio.run(bridge._react_cmd("r1", {"user_id": "chat-a", "mid": "s1", "emoji": "😂"}))
check("the runner is asked to react on the page, by the message's key",
      panel_calls[-1] == ("react", {"chat": "chat-a", "name": bridge._name_for("chat-a"), "key": "s1", "emoji": "😂",
                                    "remove": False}), str(panel_calls[-1:]))
check("what the page says after is kept, and shown live",
      chatlog.conversation(L, "chat-a")[0]["reactions"] == [{"name": "😂", "count": 1, "mine": True}]
      and events[-1] == {"t": "reactions", "uid": "chat-a", "mid": "s1",
                         "reactions": [{"name": "😂", "count": 1, "mine": True}]}, str(events[-1:]))
check("and answered", results["r1"] == {"ok": True, "reactions": [{"name": "😂", "count": 1, "mine": True}]})
asyncio.run(bridge._react_cmd("r2", {"user_id": "chat-a", "mid": "s1", "emoji": "🥳"}))
check("an emoji Snapchat does not have is refused, saying which it has",
      not results["r2"]["ok"] and "❤️ 😂 🔥 👍 👎 😰 🤯 ❓" in results["r2"]["reason"] and len(panel_calls) == 1)

events.clear()
bridge._store_transcript("chat-a", "A", [
    {"key": "s1", "mine": False, "text": "hii", "day": "2026-10-01",
     "reactions": [{"name": "🔥", "count": 2, "mine": True}]},
    {"key": "s9", "mine": False, "text": "new", "day": "2026-10-01", "at": 1790000000000,
     "reactions": [{"name": "❤️", "count": 1, "mine": False}, {"name": "<script>", "count": 1}, "junk"]},
])
kept = {m["mid"]: m for m in chatlog.conversation(L, "chat-a")}
check("a kept message whose reactions changed on the page: kept, and shown live",
      kept["s1"]["reactions"] == [{"name": "🔥", "count": 2, "mine": True}]
      and {"t": "reactions", "uid": "chat-a", "mid": "s1", "reactions": [{"name": "🔥", "count": 2, "mine": True}]} in events,
      str(events))
check("a new one is kept with its reactions, checked", kept["s9"]["reactions"][0] == {"name": "❤️", "count": 1, "mine": False}
      and all(isinstance(r, dict) for r in kept["s9"]["reactions"]), str(kept["s9"].get("reactions")))

print("\n== Snapchat's eight, the same everywhere ==")
runner = (ROOT / "app" / "platforms" / "snapchat" / "snapchat_runner.js").read_text(encoding="utf-8")
chats_ts = (ROOT / "webui" / "src" / "lib" / "chats.ts").read_text(encoding="utf-8")
in_runner = json.loads(re.search(r"const REACTIONS = (\[[^\]]+\]);", runner).group(1))
in_page = json.loads(re.search(r"export const SNAP_REACTIONS = (\[[^\]]+\]);", chats_ts).group(1))
check("the runner, the bridge and the tab list the same eight, in the picker's order",
      in_runner == list(bridge.SNAP_REACTIONS) == in_page and len(in_page) == 8, f"{in_runner} {in_page}")
pictures = re.search(r"const REACTION_PICTURES = \{(.+?)\};", runner, re.S).group(1)
check("each has the picture Snapchat draws it with", sorted(set(re.findall(r':\s*"([^"]+)"', pictures))) == sorted(in_runner))
snapbot = (ROOT / "app" / "platforms" / "snapchat" / "snapbot.js").read_text(encoding="utf-8")
react = snapbot[snapbot.index("  async react(chatId, index, choice, remove"):]
check("on the page: hover, React in the toolbar, then the choice; a reaction under a message is never the picker",
      "el.hover()" in react and 'button[data-tooltip]:not([disabled])' in react and "btn.click()" in react)
check("already as asked, nothing is pressed (pressing the chosen one again would take it back)",
      "if (remove ? !state.same : state.same)" in react)
check("the runner reads it back off the page, and says when Snapchat did not take it",
      'reason: "Snapchat did not take it; try again"' in runner and 'req.op === "react"' in runner)
check("reactions are read with every conversation", "reactions: reactionsFrom(m.reactions)" in runner
      and ':scope > ul button[data-tooltip]' in snapbot)

print("\n== Discord ==")
dr = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("the account reacts, or takes it back", "await msg.add_reaction(what)" in dr and "await msg.remove_reaction(what, bot.user)" in dr)
check("a custom emoji as Discord writes one", "discord.PartialEmoji.from_str(emoji)" in dr)
check("in a DM, and in a server conversation", 'elif cmd == "react":\n                    asyncio.create_task(_react_job' in dr
      and '"send_message", "react")' in dr and 'elif cmd == "react":\n            await _react_on(ch' in dr)
check("reactions arriving live, anyone's", "async def on_raw_reaction_add(payload):" in dr
      and "async def on_raw_reaction_remove(payload):" in dr and '"t": "reactions"' in dr)
check("drawn the same from a message and from a live event", dr.count("_reaction_emoji(") >= 3)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
