"""Writing to someone yourself, from Chats, drops the reply the bot had lined up.

The Chats tab only let the bot answer. Now it has a box to write in as the
account, and a message of yours, typed there or in Discord itself, while the
bot is waiting to reply, writing, cooling down or queued, is the answer: the
bot's reply is dropped instead of arriving after yours.
"""
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")

print("== dropping a reply that is lined up ==")
start = runner.index("# A reply is lined up for someone in these states")
end = runner.index("\ndef ", runner.index("def cancel_pending_reply("))
ns = {}
exec(compile(runner[start:end], "cancel_pending", "exec"), ns)
cancel, pending_states = ns["cancel_pending_reply"], ns["_PENDING_STATES"]


def fresh(batches=(), queues=(), state=None):
    ns["bot"] = types.SimpleNamespace(
        user_message_batches={k: {} for k in batches}, message_queues={k: [] for k in queues},
        cancelled_replies=set(), reply_state={7: {"state": state}} if state else {})
    return ns["bot"]


b = fresh(batches=["7-100"], queues=["7-100"], state="waiting")
check("a reply waiting to go is dropped", cancel(7) is True and 7 in b.cancelled_replies)
check("its timer and queued messages with it", not b.user_message_batches and not b.message_queues)
b = fresh(state="writing")
check("one being written is stopped before it is sent", cancel(7) is True and 7 in b.cancelled_replies)
b = fresh()
check("with nothing lined up, nothing is marked, so the next real reply still goes out",
      cancel(7) is False and not b.cancelled_replies)
b = fresh(state="sending")
check("the bot's own reply going out is not one of yours", cancel(7) is False and not b.cancelled_replies)
check("the states that count as lined up", set(pending_states) == {"waiting", "writing", "cooldown", "queued"})

print("\n== a message of yours ==")
own = runner[runner.index("async def on_message(message):"):]
own = own[:own.index("# remember who this is")]
check("typed in Discord while a reply is lined up drops it", "if _st and _st.get(\"state\") in _PENDING_STATES:" in own
      and "cancel_pending_reply(_rcp.id)" in own)
check("and takes them off the waiting list", "mark_responded(_rcp.id, message.channel.id)" in own)
voice = runner[runner.index("audio_chunks = await generate_voice_message(spoken_response)"):]
check("a voice note the bot sends counts as the bot's, not yours",
      voice.index('set_reply_state(message.author.id, "sending")') < voice.index("await send_voice_message("))
lock = runner[runner.index("async with bot.global_send_lock:\n        # waited its turn"):]
check("a reply that waited its turn checks again before it sends",
      lock.index("bot.cancelled_replies") < lock.index('set_reply_state(message.author.id, "sending")'))

job = runner[runner.index("async def _send_message_job("):runner.index("async def _reply_user_job(")]
check("the Chats box sends as the account, dropping the lined up reply first",
      job.index("cancel_pending_reply(uid)") < job.index("await dm.send("))
check("and the bot remembers it said it", '"role": "assistant", "content": text' in job)
check("with Discord's own limit", "2000" in job)
check("the runner listens for it", 'elif cmd == "send_message":' in runner)
routes = (ROOT / "app" / "web" / "routes" / "chat_routes.py").read_text(encoding="utf-8")
check("the panel passes it on", '@router.post("/api/chats/send")' in routes and '"send_message"' in routes)
check("Snapchat's too, typed out by its runner", "Snapchat messages cannot be sent from here yet" not in routes
      and "160.0 if _is_snap(tgt)" in routes)

print("\n== in the page ==")
chats = (ROOT / "webui" / "src" / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("a box to write in", 'class="cd-compose"' in chats and "sendDraft()" in chats)
check("Enter sends, Shift+Enter is a new line", 'e.key === "Enter" && !e.shiftKey' in chats)
check("no hint under the box: the reply being dropped is said once it is sent", "Sending this drops the reply" not in chats
      and "The bot's reply to ${who.name} was dropped" in chats)
check("a draft is kept per conversation", "$drafts[draftKey]" in chats and "setDraft(draftKey, e.currentTarget.value)" in chats)
lib = (ROOT / "webui" / "src" / "lib" / "chats.ts").read_text(encoding="utf-8")
send = lib[lib.index("export async function sendOwnMessage("):]
check("it shows at once, as sending", "pending: true" in send)
check("and is never there twice when the event beats the answer", "cur.messages.some((m) => m.mid === r.mid)" in send
      and "filter((m) => m.mid !== local)" in send)
check("a refusal stays, marked, and the text comes back to the box",
      "failed: true" in send and "setDraft(k, text);" in chats)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
