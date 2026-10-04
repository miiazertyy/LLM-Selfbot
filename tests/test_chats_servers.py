"""Server conversations in Chats, answerable from there like a DM.

The Chats tab only ever showed DMs: a server message that pinged the bot, or
replied to it, never appeared, so there was no way to see it waiting or to
answer it from the panel. Now the latest one in each channel is a row of its
own, keyed "ch<channel id>", with who asked and where, its channel's history
with everyone's own name and picture, and Reply, Cancel and the message box
working on it as on a DM.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.web.routes import chat_routes as cr

print("== a server conversation in the list ==")
evt = {"t": "msg", "uid": "ch555", "kind": "server", "channel_id": "555", "author_id": "108", "name": "Rayan",
       "avatar": "https://cdn/a.png", "where": "#general · Night Owls", "snippet": "you coming?", "ts": 10, "mid": "1"}
body = cr.apply_event({"users": []}, evt)
row = body["users"][0]
check("a new one arrives as its own row", row["id"] == "ch555" and row["kind"] == "server")
check("saying where it is and who asked", row["where"].startswith("#general") and row["author_id"] == "108"
      and row["name"] == "Rayan" and row["avatar"])
body = cr.apply_event(body, {**evt, "author_id": "109", "name": "Lou", "mid": "2"})
check("someone else asking in the same channel takes the row over", body["users"][0]["author_id"] == "109"
      and body["users"][0]["name"] == "Lou" and body["users"][0]["count"] == 2)
body = cr.apply_event(body, {"t": "ignored", "uid": "109", "ignored": True})
check("turning the bot off for a person reaches their server row", body["users"][0]["ignored"] is True)
body = cr.apply_event(body, {"t": "done", "uid": "ch555"})
check("and an answer takes it off", body["users"] == [])

print("\n== the panel passes its id through ==")
check("a server row's id stays as it is", cr._user_id_for("discord_1", "ch555") == "ch555")
check("a person's is still a number", cr._user_id_for("discord_1", "108") == 108)
check("and nothing else slips through as a row id", not cr._server_row_id("chx12") and not cr._server_row_id("555"))
src = (ROOT / "app" / "web" / "routes" / "chat_routes.py").read_text(encoding="utf-8")
check("Reply accepts it", "or _server_row_id(user_id):" in src)
check("its own picture is kept, not replaced by a profile's", 'u["avatar"] = meta.get("avatar") or u.get("avatar") or ""' in src)

print("\n== the runner ==")
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("a server message that asked for a reply is tracked by channel",
      "bot.server_waiting[channel_id] = message" in runner and '"uid": f"ch{channel_id}"' in runner)
check("and listed while it waits", "for _scid, _sm in list(bot.server_waiting.items()):" in runner)
check("the person's reply progress shows on it", 'emit_chat_event({"t": "state", "uid": f"ch{_cid}", "state": st})' in runner)
own = runner[runner.index("async def on_message(message):"):]
own = own[:own.index("# remember who this is")]
check("a message the account sends there answers it", "bot.server_waiting.pop(message.channel.id, None)" in own
      and 'emit_chat_event({"t": "done", "uid": f"ch{message.channel.id}"})' in own)
loop = runner[runner.index("for entry in commands:"):]
first = loop[:loop.index('elif cmd == "pause":')]
check("its commands are routed before a DM's same commands",
      '_server_id(payload) is not None' in first and "_server_job_safe" in first)
job = runner[runner.index("async def _server_job("):runner.index("async def _server_job_safe(")]
for cmd in ("chat_message", "chat_history", "cancel_reply", "reply_user", "send_message"):
    check(f"{cmd} works on a server row", f'cmd == "{cmd}"' in job)
check("a Reply there is never to something already answered", "await _answered_since(waiting)" in job)
check("a message typed there answers theirs, without pinging them", "waiting.reply(text, mention_author=False)" in job)
check("and drops only the reply lined up in that channel", "cancel_pending_reply(waiting.author.id, cid)" in job)
check("its history says who wrote each message", '"author": {"id": str(a.id)' in job)

print("\n== in the page ==")
chats = (ROOT / "webui" / "src" / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("the row says where", 'u.kind === "server" && u.where' in chats and 'class="ch-where"' in chats)
check("so does the header", 'selected.kind === "server" && selected.where' in chats)
check("each message has its own author's picture and name", "d.m.author?.avatar ?? selected.avatar" in chats
      and "d.m.author?.name ?? selected.name" in chats)
check("a new author starts a new group", 'x.author?.id ?? "them"' in chats)
check("ignoring from a server row ignores the person, not the channel", "ignorePerson(personOf(u), e)" in chats
      and "toggleIgnore(target, personOf(u).id)" in chats)
lib = (ROOT / "webui" / "src" / "lib" / "chats.ts").read_text(encoding="utf-8")
check("a ping of your own account says its name", "own[a.user_id] = a.display_name" in lib)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
