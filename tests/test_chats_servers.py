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
check("each message has its own author's picture and name", "d.m.author?.avatar ?? headAvatar" in chats
      and "d.m.author?.name ?? selected.name" in chats)
check("a new author starts a new group", 'x.author?.id ?? "them"' in chats)
check("ignoring from a server row ignores the person, not the channel", "ignorePerson(personOf(u), e, acc)" in chats
      and "toggleIgnore(accOf(u), personOf(u).id)" in chats)
lib = (ROOT / "webui" / "src" / "lib" / "chats.ts").read_text(encoding="utf-8")
check("a ping of your own account says its name", "own[a.user_id] = a.display_name" in lib)

# ── Walking into a server, rather than waiting to be spoken to ───────────────
# A channel was only ever reachable once someone had written in it. Servers in the list is the rest of them: the
# account's servers, their categories, their channels, any of which opens and can be typed in.
print("\n== going into a server yourself ==")
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("the runner can say what servers it is in, and their channels",
      'elif cmd == "guilds":' in runner and "async def _guilds_job" in runner)
job = runner.split("async def _guilds_job")[1].split("async def _send_message_job")[0]
check("  out of the gateway's own cache, so asking costs Discord nothing",
      "for g in sorted(bot.guilds" in job and "await " not in job)
check("  in the order Discord itself puts them, category by category",
      'rows.sort(key=lambda r: (r["category_at"], r["category"].lower(), r["at"], r["name"]))' in job)
check("  only the ones it may read, and it says which it may post in",
      "if perms is not None and not perms.read_messages:" in job and '"can_send": bool(' in job)
check("  a server with nothing it can read is left out", "if not rows:\n                    continue" in job)
check("  every voice and stage channel is there, typed in or not: people can be talking in one nobody wrote in",
      'vocal = (getattr(discord, "VoiceChannel", ()), getattr(discord, "StageChannel", ()))' in job
      and "last_message_id" not in job and '"voice": isinstance(ch, vocal),' in job)
src = (ROOT / "app" / "web" / "routes" / "chat_routes.py").read_text(encoding="utf-8")
check("the panel asks through its own route", '@router.get("/api/chats/servers")' in src
      and 'ipc.send_and_wait(tgt, "guilds"' in src)
check("and it waits longer on the platforms read off a page, which answer between their own steps",
      "timeout=40.0 if _is_snap(tgt) else 20.0" in src)
tree = (ROOT / "webui" / "src" / "lib" / "components" / "ServerTree.svelte").read_text(encoding="utf-8")
check("the servers along the top, its channels under their category",
      'class="st-rail"' in tree and 'class="st-cat"' in tree and 'class="st-chan"' in tree)
check("a channel someone is waiting in is marked", "waiting.has(ch.id) || ch.waiting" in tree)
check("one it cannot post in is dimmed, and the list's search narrows the channels",
      "class:is-quiet={!ch.can_send}" in tree and "words.every((w) => hay.includes(w))" in tree)
check("categories fold away, per server", 'shut[`${pickedId}:${name}`]' in tree)
check("two categories with one name don't stop the list: each group has a key of its own",
      "{#each groups as grp (grp.key)}" in tree and "key: `${ch.category}#${again}`" in tree)
check("picking a channel opens it like any other conversation: its row id is \"ch<id>\"",
      "const id = `ch${ch.id}`;" in chats and "function openChannel" in chats)
check("one someone is waiting in opens that row, not a second copy of it",
      "const already = users.find((u) => u.id === id && accOf(u) === target);" in chats)
check("a channel walked into is not called answered, since nothing is waiting in it",
      "browsed?: boolean;" in chats and "{#if selected.browsed}" in chats)
check("and one it may only read says so where the box would be",
      "{#if selected?.readonly}" in chats and "It can read this channel, not post in it." in chats)
check("it is offered even with nobody waiting in one",
      "{#if hasServers && !allView}" in chats)
check("including from inbox zero, which is exactly when you would want it",
      '!users.length && !selected && !browsingServers' in chats and "Go into its servers" in chats)

# ── Telegram gets what Discord gets ─────────────────────────────────────────
# Telegram has no server holding channels, so there is nothing to mirror one for one. What it does have is groups
# and the channels it follows, and those go into the same list, under the account itself.
print("\n== and the same for Telegram, which has no servers but has groups ==")
bridge = (ROOT / "app" / "platforms" / "snapchat_bridge.py").read_text(encoding="utf-8")
check("the bridge answers it, for Telegram", 'elif cmd == "guilds":' in bridge
      and "async def _guilds_cmd" in bridge and 'if op == "guilds":' in bridge)
check("a platform with nothing of the kind says so instead of failing",
      '_write_result(cmd_id, {"ok": True, "guilds": [], "unsupported": True})' in bridge)
check("its groups and the channels it follows are the two shelves",
      '"category": "Channels" if channel else "Groups",' in bridge)
check("a channel it only follows is marked as one it cannot post in",
      '"can_send": not channel' in bridge)
check("and one with someone waiting is marked, as Discord's are", "_incoming_waiting()" in bridge)
client = (ROOT / "app" / "platforms" / "telegram" / "client.py").read_text(encoding="utf-8")
check("the client can list the channels it follows even where it is set not to answer in them",
      "async def chats(self, limit: int = 40, every: bool = False)" in client
      and "if broadcast and not self.answer_channels and not every:" in client
      and '"broadcast": broadcast,' in client)
check("the route lets both through, and says when a platform has none",
      '"supported": not result.get("unsupported")' in src and "_is_snap(tgt)" in src.split(
          '@router.get("/api/chats/servers")')[1][:900])
check("the panel offers it on both, in that platform's own word",
      'const hasServers = $derived(plat.id === "discord" || plat.id === "telegram");' in chats
      and '"Its groups and channels" : "Its servers and channels"' in chats
      and 'word={plat.id === "telegram" ? "group" : "server"}' in chats)
check('and writes a name the way that platform writes it: "#general", but "Les Potes"',
      'const named = plat.id === "discord" ? `#${ch.name}` : ch.name;' in chats
      and '{#if word === "server"}<span class="st-hash">' in tree)


# ── A way in, not a way of narrowing ────────────────────────────────────────
# It sat among the chips that filter who is waiting, looking like one more of them, when what it does is swap the
# whole column for something else.
print("\n== going in is a button, not a filter ==")
check("it is not one of the filters any more",
      '"all" | "unread" | "needs" | "live" | "answered" | "drafts";' in chats
      and 'id: "servers", label:' not in chats)
check("it is a button of its own, above them", 'class="ch-go"' in chats and "function toggleServers" in chats)
check("and it says which way it goes",
      '"Back to chats"' in chats and '"Its groups and channels"' in chats and '"Its servers and channels"' in chats)
check("the filters are put away while you are in there, having nothing left to filter",
      "{#if listChips.length > 1 && !browsingServers}" in chats)
check("and the box above searches whichever of the two is in the column",
      'placeholder={browsingServers ? "Search channels" : "Search chats"}' in chats)
check("an account with no servers, or All chats, leaves it rather than showing nothing",
      "if (serversOpen && (allView || !hasServers)) serversOpen = false;" in chats)
check("the servers themselves can be dragged along, with a bar that shows while you do",
      "use:hscroll" in tree and 'class="hscroll st-rail-wrap"' in tree)


# ── A way in, not a way of narrowing ────────────────────────────────────────
# It sat among the chips that filter who is waiting, looking like one more of them, when what it does is swap the
# whole column for something else.
print("\n== going in is a button, not a filter ==")
check("it is not one of the filters any more",
      '"all" | "unread" | "needs" | "live" | "answered" | "drafts";' in chats
      and 'id: "servers", label:' not in chats)
check("it is a button of its own, above them", 'class="ch-go"' in chats and "function toggleServers" in chats)
check("and it says which way it goes",
      '"Back to chats"' in chats and '"Its groups and channels"' in chats and '"Its servers and channels"' in chats)
check("the filters are put away while you are in there, having nothing left to filter",
      "{#if listChips.length > 1 && !browsingServers}" in chats)
check("and the box above searches whichever of the two is in the column",
      'placeholder={browsingServers ? "Search channels" : "Search chats"}' in chats)
check("an account with no servers, or All chats, leaves it rather than showing nothing",
      "if (serversOpen && (allView || !hasServers)) serversOpen = false;" in chats)
check("the servers themselves can be dragged along, with a bar that shows while you do",
      "use:hscroll" in tree and 'class="hscroll st-rail-wrap"' in tree)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
