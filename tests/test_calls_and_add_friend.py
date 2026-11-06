"""Calls and adding a friend, on the Chats tab, for Discord and Snapchat alike.

Someone calling the account in a DM, or in a call there, shows as it happens:
a strip at the top of the list (their picture with rings going out while it
rings, "is calling" or "in a call" and for how long), "Calling" or "In a call"
on their row, and the same on their open conversation. Discord says it with
its call events and their voice state in that DM; Snapchat with its chat
list's status line. The panel keeps what is going on now per account, so a
page opened mid-call shows it, and a call starting is heard.

"Add friend" beside the list sends a friend request by username from that
account: Discord's through its own API (by username, or by id when it is all
digits), Snapchat's through its own add friends search, pressing Add only on
the result whose username is exactly the one typed.

The event part is run for real (apply_chat_event and GET /api/chats), the
rest is read from the source.
"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


dr = read("app/platforms/discord_runner.py")
br = read("app/platforms/snapchat_bridge.py")
sb = read("app/platforms/snapchat/snapbot.js")
sr = read("app/platforms/snapchat/snapchat_runner.js")
cr = read("app/web/routes/chat_routes.py")
ct = read("webui/src/lib/chats.ts")
api = read("webui/src/lib/api.ts")
ch = read("webui/src/pages/Chats.svelte")
icon = read("webui/src/lib/components/Icon.svelte")

print("== Discord: its call events ==")
check("a call starting, changing and ending is each heard", "async def on_call_create(call):" in dr
      and "async def on_call_update(before, after):" in dr and "async def on_call_delete(call):" in dr)
check("and someone joining or leaving a DM's call, by their voice state there",
      "async def on_voice_state_update(member, before, after):" in dr and "isinstance(ch, discord.DMChannel)" in dr)
dm = dr.split("def _dm_call(call)", 1)[1].split("\ndef ", 1)[0]
check("only a DM's call: the person on the other end, in it", 'other = getattr(channel, "recipient", None)' in dm
      and "if other.id not in present:" in dm and "present = {u.id for u in call.members}" in dm)
check("ringing while it rings the account, together once the account is in it, in a call otherwise",
      'state = "ringing" if me in ringing else ("together" if me in present else "in_call")' in dm
      and "ringing = {u.id for u in call.ringing}" in dm)
emit = dr.split("def _emit_call(channel)", 1)[1].split("\n@bot.event", 1)[0]
check("said only when it changes", '(seen or {}).get("state") == (info or {}).get("state")' in emit)
check("its start kept across a ring turning into a call", 'info["since"] = (seen or {}).get("since") or time.time()' in emit)
check("sent to the panel as a chat event", 'emit_chat_event({"t": "call", "uid": uid, "call": info})' in emit)
check("and its end", 'emit_chat_event({"t": "call", "uid": str(other.id), "call": None})' in dr)

print("\n== Snapchat: its chat list ==")
check("the status line read for a call, in English and French, on both lists",
      sb.count("incoming (video |voice )?call") == 2 and sb.count("appel en cours") == 2
      and sb.count("a rejoint l.appel") == 2)
check("a missed, ended or declined call is not one going on", sb.count("missed|ended|declined|manqu|termin|refus") == 2)
check("each chat says its call, and typing, on the plain list too", "typing: /\\btyping|is writing" in sb
      and "            call,\n" in sb and "byId.set(id, { id, name, unread, avatar, typing, call })" in sb)
check("the runner says when one starts, changes or ends", "let callsSeen = new Map();" in sr
      and 'if (callsSeen.get(chat) !== state) tellPython({ kind: "call", chat, state });' in sr
      and 'if (!callsNow.has(chat)) tellPython({ kind: "call", chat, state: "" });' in sr)
check("the bridge hands it to the panel", 'elif msg.get("kind") == "call" and msg.get("chat"):' in br
      and '_on_call(str(msg["chat"]), str(msg.get("state") or ""))' in br)
oc = br.split("def _on_call(chat: str, state: str)", 1)[1].split("\nasync def ", 1)[0]
check("with their name, picture and when it began", '"name": _name_for(chat) or chat' in oc
      and "snappeople.avatar_url(ACCOUNT_INDEX, chat)" in oc and "_CALLS_SINCE.setdefault(chat, time.time())" in oc)
check("and its end", '_emit_chat({"t": "call", "uid": chat, "call": None})' in oc)

print("\n== the panel keeps them ==")
from app.web.routes import chat_routes  # noqa: E402

chat_routes._CALLS.clear()
chat_routes.apply_chat_event("discord_1", {"t": "call", "uid": "42", "call": {"state": "ringing", "name": "Mara", "since": 5}})
chat_routes.apply_chat_event("snapchat_1", {"t": "call", "uid": "abc", "call": {"state": "in_call", "name": "Kit"}})
check("a call starting is kept per account and person",
      chat_routes._CALLS.get(1, {}).get("42", {}).get("state") == "ringing"
      and chat_routes._CALLS.get("snap", {}).get("abc", {}).get("uid") == "abc", str(chat_routes._CALLS))
check("not kept as a replayed event, which would put it back after it ended",
      all(e.get("t") != "call" for _, e in chat_routes._CHAT_EVENTS.get(1, [])))


async def _fake_payload(tgt, fresh=False):
    return {"users": [], "paused": False}


class _Req:
    query_params = {}
    headers = {}


_real_payload, _real_resolve = chat_routes._chats_payload, chat_routes._resolve_target
chat_routes._chats_payload = _fake_payload
chat_routes._resolve_target = lambda request, explicit=None: chat_routes._ipc_target_for(explicit)
try:
    body = asyncio.run(chat_routes.chats(_Req(), target="discord_1"))
    check("the list comes with the calls going on now", [c.get("uid") for c in body.get("calls", [])] == ["42"]
          and body.get("users") == [], str(body))
    chat_routes.apply_chat_event("discord_1", {"t": "call", "uid": "42", "call": None})
    body = asyncio.run(chat_routes.chats(_Req(), target="discord_1"))
    check("and not one that is over", body.get("calls") == [], str(body))
finally:
    chat_routes._chats_payload, chat_routes._resolve_target = _real_payload, _real_resolve
    chat_routes._CALLS.clear()

print("\n== the Chats tab shows them ==")
check("kept live per conversation, filled from the list as it comes",
      "export const callsNow = writable<Record<string, CallInfo>>({});" in ct
      and "setCallsFor(target, data.calls);" in ct
      and 'if (evt.t === "call") return setCall(target, String(evt.uid ?? ""), evt.call ?? null);' in ct)
check("a call starting is heard, and its end, softly",
      'if (call?.state === "ringing" && was?.state !== "ringing") play("receive", { level: 0.75 });' in ct
      and 'else if (!call && was) play("off", { level: 0.4 });' in ct)
check("one already going on is heard as it shows, and a ring answered",
      'else if (call && !was) play("glint", { level: 0.4 });' in ct
      and 'else if (call && was && call.state !== was.state) play("seat", { level: 0.4 });' in ct)
check("but not a page opened mid-call: the list fills them in quietly",
      "play(" not in ct.split("function setCallsFor(target: string, list: unknown) {", 1)[1].split("\n}\n", 1)[0])
check("a strip of them at the top of the list, ringing first",
      '<div class="ch-calls"' in ch and "Number(b.state === \"ringing\") - Number(a.state === \"ringing\")" in ch)
check("rings going out from their picture while it rings",
      ".ch-call.is-ringing .ch-call-ring { animation: ch-call-ring 1.6s ease-out infinite; }" in ch
      and ".ch-call.is-ringing .ch-call-ring.is-late { animation-delay: 0.8s; }" in ch)
check("in plain words, and for how long, as a call screen says it",
      'state === "ringing" ? "is calling" : state === "together" ? "on a call with you" : "in a call"' in ch
      and 'return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;' in ch)
check("pressing one opens the conversation, with a sound", "function openCall(c:" in ch
      and 'playSound("select");' in ch.split("function openCall(c:", 1)[1].split("}\n", 1)[0])
check("their row says it where the last message would be, on the row's own account", '<span class="ch-call-tag"' in ch
      and '{callOf(u.id, acc).state === "ringing" ? "Calling" : "In a call"}' in ch
      and ch.index("{#if callOf(u.id, acc)}") < ch.index("{:else if $typingNow[convKey(acc, u.id)]}"))
check("and their open conversation, by their name", '<span class="cd-call"' in ch and "{#if callOf(selected.id)}" in ch)
check("with a phone icon", re.search(r"\bphone:\s*[`'\"]", icon) is not None or '"phone"' in icon)
check("still with motion off", ':global(:root[data-motion="off"]) .ch-call-ring' in ch
      and ':global(:root[data-motion="off"]) .cd-call' in ch)

print("\n== adding a friend ==")
fa = cr.split("async def friend_action(request: Request, action: str):", 1)[1].split("\n@router", 1)[0]
check("the route takes add, by username", 'if action not in ("accept", "decline", "add"):' in fa
      and 'username = str(body.get("username") or "").strip().lstrip("@")' in fa)
check("a username, not a sentence", 'any(ch.isspace() for ch in username)' in fa and "len(username) > 64" in fa)
check("sent to that account, given longer on Snapchat, which searches for them",
      'await ipc.send_and_wait(tgt, "friend_add", {"username": username, **({"text": text} if text else {})},' in fa
      and 'timeout=90.0 if _is_snap(tgt) else 25.0)' in fa)
check("a stopped account says so", 'raise HTTPException(status_code=504, detail="runner did not respond")' in fa)
fad = dr.split('elif cmd == "friend_add":', 1)[1].split('elif cmd == "add_friend":', 1)[0]
check("Discord: by username through its own request", "await bot.send_friend_request(_fa_who)" in fad)
check("or by id, when it is all digits", "elif _fa_who.isdigit():" in fad
      and "users/@me/relationships/{int(_fa_who)}" in fad)
check("its refusals said plainly", '"Nobody on Discord has that username"' in fad
      and '"Discord asked for a captcha: send it from the Discord app"' in fad)
check("Snapchat: through its own add friends panel", 'elif cmd == "friend_add":' in br
      and '_spawn_panel(_friend_add_cmd(cmd_id, str(payload.get("username") or ""), str(payload.get("text") or "")))' in br
      and 'await _panel("add_friend", username=username, text=text, timeout=80.0)' in br
      and 'if (req.op === "add_friend") return await bot.addFriendByUsername(String(req.username || ""));' in sr)
af = sb.split("async addFriendByUsername(username) {", 1)[1].split("\n  async listRecipients()", 1)[0]
check("only a real Snapchat username is searched for", "/^[a-z0-9][a-z0-9._-]{1,29}$/.test(want)" in af)
check("Add pressed only on the result whose username is exactly it",
      "const isIt = (t) => (t || \"\").trim().toLowerCase().replace(/^@/, \"\") === want;" in af
      and "el.children.length || !isIt(el.textContent)" in af)
check("already friends, or already asked, is said, not pressed again", '"A request to them is already waiting"' in af
      and '"You are already friends"' in af)
check("the panel closed again afterwards", 'await this.page.keyboard.press("Escape");' in af and "await close();" in af)
check("the panel's call", 'friendAdd: (username: string, target = "", text = "") =>' in api
      and 'request("/api/friends/add", { method: "POST", body: JSON.stringify({ username, target, ...(text ? { text } : {}) }) })' in api)
check("an Add friend button beside the list, opening a small form (Follow, on TikTok and Instagram)",
      '<span class="ch-btn-label">{plat.add}</span>' in ch and "aria-label={plat.add}" in ch
      and '<form class="ch-add glass floating"' in ch
      and '{plat.add === "Follow" ? `Follow someone on ${plat.name}` : `Add a friend on ${plat.name}`}' in ch)
check("in a narrow window it and Ignored are their icons, and the account's name is never covered by them",
      ".ch-top-actions .ch-btn-label { display: none; }" in ch and ".ch-top-account { order: 1; flex: 1 1 9rem; }" in ch
      and "max-width: 100%;" in ch.split(".ch-account {", 1)[1].split("}", 1)[0]
      and ".ch-slot-chip { display: none; }" in ch)
check("it opens with a sound and puts the cursor in it",
      'playSound("open");' in ch.split("async function toggleAdd()", 1)[1].split("}\n", 1)[0]
      and "addBox?.focus();" in ch)
check("closed by Escape or a click elsewhere", 'if (e.key === "Escape") addOpen = false;' in ch
      and '?.closest?.("[data-add-friend]")) addOpen = false;' in ch)
check("the answer said in a toast", 'toast(plat.id === "tiktok" ? `Following ${name} on TikTok.`' in ch
      and 'plat.id === "instagram" ? `Following ${name} on Instagram.`' in ch
      and 'toast(r?.reason ||' in ch)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
