"""The bot never answers the same message twice.

It looked like the bot talking by itself: "wdym", "ugh you're loud", "ok that
was a lot", "that's the biggest laugh rn", each minutes apart, with nothing
from the other person in between, until they blocked the account. Every one
was an answer to the same old "LMAOOO". A Reply to all answered it, but never
took them off the stored waiting list; two days later the nudge treated them
as never answered, and every restart replayed a Reply to all still sitting in
the command file, which found their last message and answered it again.
"""
import asyncio
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")

print("== has the bot spoken since their message? ==")
start = runner.index("async def _answered_since(")
end = runner.index("\ndef ", start)
ME, THEM = 1, 2


class Msg:
    def __init__(self, mid, author):
        self.id = mid
        self.author = types.SimpleNamespace(id=author)


class Channel:
    def __init__(self, messages, cached=True):
        self.messages = messages
        self.last_message_id = messages[-1].id if messages else None
        cache = {m.id: m for m in messages} if cached else {}
        self._state = types.SimpleNamespace(_get_message=cache.get)
        self.fetches = 0

    def history(self, limit=10, after=None):
        self.fetches += 1
        found = [m for m in self.messages if after is None or m.id > after.id][:limit]

        async def gen():
            for m in found:
                yield m
        return gen()


class Budget:
    def __init__(self, ok=True):
        self.ok = ok

    def allow(self):
        return self.ok


ns = {"bot": types.SimpleNamespace(selfbot_id=ME, user=types.SimpleNamespace(id=ME)),
      "_manual_history_budget": Budget(True)}
exec(compile(runner[start:end], "answered_since", "exec"), ns)
answered = ns["_answered_since"]


def ask(messages, index, cached=True, budget=True):
    ch = Channel(messages, cached)
    ns["_manual_history_budget"] = Budget(budget)
    m = messages[index]
    m.channel = ch
    return asyncio.run(answered(m)), ch.fetches


lmao = [Msg(10, THEM), Msg(11, ME)]
got, fetched = ask(lmao, 0)
check("their message with the bot's answer after it is answered", got is True)
check("known from the cache, with nothing fetched", fetched == 0)
got, fetched = ask(lmao, 0, cached=False)
check("and from Discord when the cache is cold, as after a restart", got is True and fetched == 1)
check("their message still last is not answered", ask([Msg(10, ME), Msg(11, THEM)], 1)[0] is False)
check("nor when only they have written since",
      ask([Msg(10, THEM), Msg(11, THEM), Msg(12, THEM)], 0, cached=False)[0] is False)
check("with no allowance left to ask, it does not reply", ask(lmao, 0, cached=False, budget=False)[0] is True)

print("\n== the stored waiting list ==")
tmp = Path(tempfile.mkdtemp(prefix="llmbot_selftalk_"))
import app.utils.db as db
db.db_path = str(tmp / "bot_data.db")
db._pragmas_applied = False
db.init_db()
db.add_unresponded(111, 5, "LMAOOO", 1000.0)
db.add_unresponded(222, 6, "hey", 2000.0)
db.mark_nudge_sent(111, 5)
waiting = [r["user_id"] for r in db.get_unresponded()]
check("someone nudged is not waiting any more", waiting == [222], str(waiting))
db.mark_responded(222, 6)
check("and someone answered comes off", db.get_unresponded() == [])
shutil.rmtree(tmp, ignore_errors=True)

print("\n== every path that answers asks first ==")
def body(name, until):
    i = runner.index(name)
    return runner[i:runner.index(until, i)]


job = body("async def _reply_user_job(", "log_system(\"Telegram IPC bridge started\")")
check("a manual Reply", job.index("await _answered_since(target_msg)") < job.index('set_reply_state(uid, "writing")'))
check("and one that was answered comes off the list instead", '"dropped": True' in job.split("await _answered_since(target_msg)")[1][:900])
ok = job[job.index('if resp:'):]
check("a reply clears the waiting list even when the stats fail",
      ok.index("mark_responded(uid, target_msg.channel.id)") < ok.index("record_user_message(uid") and ok.count("except Exception:") >= 2)

ra = body('elif cmd == "reply_all":', 'elif cmd == "restart":')
check("Reply to all leaves the command file before it runs",
      ra.index("_flush_commands(_CMD_FILE, remaining, commands)") < ra.index("_ra_candidates = []"))
check("stops at the bot's own message when looking for theirs",
      "if _ra_m.author.id == _ra_selfbot_id:" in ra and "_ra_answered = True" in ra)
check("and clears each person it answers", ra.count("mark_responded(") >= 2)

pend = body("async def _reply_pending_messages(", "async def _friend_request_loop(")
check("the catch-up after a restart", pend.index("await _answered_since(last_msg)") < pend.index('log_system(f"Replying to pending message'))

nudge = body("async def _nudge_loop(", "\nasync def ")
check("a nudge, for a conversation the bot already answered", "Nudge skipped for {user.name}: the conversation was already answered" in nudge
      and nudge.index("already answered") < nudge.index("generate_nudge("))
check("and a sent nudge takes them off the waiting list", re.search(r"await dm\.send\(nudge_text\)\s+mark_nudge_sent\(user_id, channel_id\)[\s\S]{0,120}mark_responded\(user_id, channel_id\)", nudge))

loop = body("for entry in commands:", 'if cmd == "pause":')
check("a reply request from before a restart is dropped, not run",
      "_REPLY_REQUEST_TTL" in loop and "continue" in loop and '_write_result(cmd_id, {"success": False' in loop)
ttl = re.search(r"_REPLY_REQUEST_TTL = \{\"reply_user\": (\d+), \"reply_all\": (\d+)\}", runner)
check("just past how long the panel waits for each", ttl and 120 < int(ttl.group(1)) < 200 and 300 < int(ttl.group(2)) < 400)

p3 = body("# Pass 3: the waiting list on disk", "_write_result(cmd_id, {")
check("Chats does not list someone the bot had the last word with", "_rlast.author.id == _selfbot_id" in p3)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
