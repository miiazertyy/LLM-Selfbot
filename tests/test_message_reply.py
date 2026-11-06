"""Replying to one message from the Chats tab, on every platform.

Reply on a message (beside it as the pointer passes, or in its right-click menu) puts a "Replying to" bar over the
message box; what is sent next goes as that message's answer: Discord's own reply (a message reference, without
pinging them), Snapchat's and TikTok's own Reply on the message, pressed in the page before typing. A reply is drawn
with what it answers above it, as the apps draw one, and pressed it goes to that message.

Run for real: Discord's message payload says what a reply answers (from a stand-in message), and its reference for a
reply is made only from a message id. The rest is read from the source.
"""
import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== Discord ==")
# The runner itself needs a token and a model to load: its few functions here are taken out of it and run as they are,
# with the real discord library.
import discord  # noqa: E402

_src = (ROOT / "app/platforms/discord_runner.py").read_text(encoding="utf-8")
_wanted = {"_message_payload", "_reply_reference", "_reaction_emoji", "_sticker_names", "gift_code"}
_ns = {"discord": discord, "re": re}
for node in ast.parse(_src).body:
    # What a message is includes the Nitro gift link in it, which is found with a pattern kept beside the function.
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_GIFT_RE" for t in node.targets):
        exec(compile(ast.Module(body=[node], type_ignores=[]), "discord_runner.py", "exec"), _ns)
    if isinstance(node, ast.FunctionDef) and node.name in _wanted:
        exec(compile(ast.Module(body=[node], type_ignores=[]), "discord_runner.py", "exec"), _ns)
dr = SimpleNamespace(**{k: _ns[k] for k in _wanted if k in _ns})

quoted = SimpleNamespace(content="are you coming saturday?", attachments=[], stickers=[],
                         author=SimpleNamespace(display_name="Mara", name="mara"))
msg = SimpleNamespace(id=42, content="yes!!", stickers=[], attachments=[], embeds=[], reactions=[],
                      reference=SimpleNamespace(message_id=41, resolved=quoted))
out = dr._message_payload(msg)
check("a reply says what it answers: its id, its words, who wrote it",
      out.get("reply_to") == {"mid": "41", "text": "are you coming saturday?", "name": "Mara"}, str(out.get("reply_to")))
plain = dr._message_payload(SimpleNamespace(id=43, content="hi", stickers=[], attachments=[], embeds=[], reactions=[],
                                            reference=None))
check("a plain message answers nothing", "reply_to" not in plain)
ref = dr._reply_reference("41", 7)
check("a reply goes as Discord's own reference to that message", ref is not None and ref.message_id == 41
      and ref.channel_id == 7 and ref.fail_if_not_exists is False)
check("only from a message id", dr._reply_reference("k1a2b", 7) is None and dr._reply_reference("", 7) is None)
run = read("app/platforms/discord_runner.py")
check("in a DM and in a server channel, without pinging them",
      run.count('_reply_reference(payload.get("reply_to")') == 2 and '"mention_author": False' in run
      and "reference=ref, mention_author=False" in run)

print("\n== Snapchat and TikTok ==")
route = read("app/web/routes/chat_routes.py")
check("the panel passes the message it answers, checked", 'payload["reply_to"] = reply_to' in route
      and 'raise HTTPException(status_code=400, detail="which message?")' in route)
bridge = read("app/platforms/snapchat_bridge.py")
check("the bridge hands it to the runner, and says whether the page's Reply took it",
      'reply_to=reply_to, timeout=150.0' in bridge and 'out["replied"] = bool(r.get("replied"))' in bridge)
snap, snaprun = read("app/platforms/snapchat/snapbot.js"), read("app/platforms/snapchat/snapchat_runner.js")
check("Snapchat: its own Reply on the message, in the toolbar over it, before typing", "async startReply(chatId, index" in snap
      and "reply|répondre|repondre" in snap and "replied = await bot.startReply(shownAs, index, ownName)" in snaprun)
tt, ttrun = read("app/platforms/snapchat/tiktokbot.js"), read("app/platforms/snapchat/tiktok_runner.js")
check("TikTok: its own Reply (dm-new-reply-btn), the box then quoting it", '[data-e2e="dm-new-reply-btn"]' in tt
      and '[data-e2e="dm-new-ref-close-btn"]' in tt and "replied = await bot.startReply(m.idx)" in ttrun)
check("and let go of again when the message did not go", "await bot.cancelReply()" in ttrun)
check("TikTok's quote is kept as what a reply answers, as Discord's is", 'body["reply_to"] = {"text": str(m["quote"])[:200]}' in bridge
      and '"reply_to"' in read("app/utils/chatlog.py"))

print("\n== the Chats tab ==")
chats, lib, api = read("webui/src/pages/Chats.svelte"), read("webui/src/lib/chats.ts"), read("webui/src/lib/api.ts")
check("Reply beside a message as the pointer passes, and in its menu", 'class="cd-react-add cd-reply-add"' in chats
      and '{ label: "Reply", icon: "reply", run: () => startReply(m) }' in chats)
check("a bar over the message box says what it answers, with a way out", 'class="cd-replying"' in chats
      and "Replying to <b>{replyHere.name}</b>" in chats and "onclick={letGoOfReply}" in chats)
check("Escape lets go of it", 'if (e.key === "Escape" && replyHere)' in chats)
check("one per conversation, kept if sending failed", "replyingTo = { ...replyingTo, [k]: answering }" in chats)
check("sent as that message's answer", "sendOwnMessage(target, who.id, text, files, answering)" in chats
      and 'replyTo?.mid ?? ""' in lib and "reply_to })" in api)
check("said when the page offered no Reply on it", "did not offer Reply on that one" in chats and 'r?.replied === false' in lib)
check("a reply is drawn with what it answers above it, which goes to it", 'class="cd-quote"' in chats
      and "void jumpTo(d.m.reply_to.mid)" in chats)
check("with sounds: picked, let go, pressed", 'playSound("select");\n    tick().then(() => composer?.focus());' in chats
      and 'playSound("off");' in chats and 'playSound("tap"); void jumpTo' in chats)
check("its own arrow", "    reply: " in read("webui/src/lib/components/Icon.svelte"))

print("\n== a picture that failed once ==")
avatar = read("webui/src/lib/components/Avatar.svelte")
check("tries once more a moment later", "retry=${attempt}" in avatar and "onerror={failed}" in avatar)
check("the header finds a picture its row came without", "const headAvatar = $derived(" in chats
      and "<Avatar src={headAvatar} name={selected.name} size={48}" in chats and "api.person(String(id))" in chats)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
