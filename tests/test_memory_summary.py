"""The conversation summary on the Memory page.

Opening someone shows what you and they have been talking about, written from
their last few messages by whichever running account can read the chat. These
pin the parts that decide what you see: when a stored summary is reused, when
it is rewritten, which account is asked, and what happens when none answers.

No runner is started: the IPC call is replaced with a stub, so this checks the
panel's side of the conversation only.
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="summary_test_"))
for sub in ("config", "ipc", "logs"):
    (SANDBOX / sub).mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
(SANDBOX / "config" / ".env").write_text("DISCORD_TOKEN_1=aaa\n", encoding="utf-8")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.seed_data_dir = lambda: None
import app.utils.helpers as helpers
helpers.get_env_path = lambda: str(SANDBOX / "config" / ".env")
helpers.resource_path = lambda rel: str(
    (SANDBOX if rel.replace("\\", "/").split("/")[0] in ("config", "ipc") else paths.APP_DIR) / rel)
import app.web.envfile as envfile
envfile.ENV_PATH = SANDBOX / "config" / ".env"
import app.core.ipc as ipc
ipc.CONFIG_DIR = SANDBOX / "config"
ipc.IPC_DIR = SANDBOX / "ipc"
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"
# db.py finds its file through resource_path, patched above to the sandbox.
import app.utils.db as db
db.init_db()
from app.utils.memory import init_memory
init_memory()

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


import app.web.routes.chat_routes as chat_routes

# Two accounts, one per platform, and a log of who was asked what.
asked = []
answers = {}


async def fake_send_and_wait(target, cmd, payload=None, timeout=10.0):
    asked.append((target, cmd, payload))
    return answers.get(target)


chat_routes.ipc.send_and_wait = fake_send_and_wait
chat_routes.ipc.discover_targets = lambda: {
    "discord_1": {"target": 1},
    "snapchat_1": {"target": "snap"},
}

# Settings, changed between checks without touching disk.
SETTINGS = {}
_real_settings = chat_routes._summary_settings


def settings(**over):
    SETTINGS.clear()
    SETTINGS.update(over)


def _patched():
    out = dict(chat_routes._SUMMARY_DEFAULTS)
    out.update(SETTINGS)
    return out


chat_routes._summary_settings = _patched

from fastapi.testclient import TestClient
from app.web.server import create_app

client = TestClient(create_app(supervisor=None))
UID = "1234567890123456789"          # a real-shaped snowflake
SNAP = "3f1c9a2e-5b7d-4e8f-a1b2-c3d4e5f6a7b8"


def get(uid=UID, force=False):
    return client.get(f"/api/memory/{uid}/summary" + ("?force=true" if force else "")).json()


print("== the first open writes one ==")
settings()
answers[1] = {"ok": True, "summary": "They talked about the match.", "count": 20, "source": "live"}
r = get()
check("a summary comes back", r.get("summary") == "They talked about the match.", str(r))
check("written, not read from storage", r.get("cached") is False)
check("from the Discord account, for a numeric id", asked and asked[-1][0] == 1, str(asked))
check("asking for the configured number of messages", asked[-1][2]["count"] == 20)
check("with the id as an exact number", asked[-1][2]["user_id"] == int(UID))

print("\n== opening them again reuses it ==")
asked.clear()
r = get()
check("the stored one is served", r.get("cached") is True and r.get("summary"), str(r))
check("without asking the account again", asked == [], str(asked))

print("\n== Rewrite asks again ==")
answers[1] = {"ok": True, "summary": "Now they are planning Saturday.", "count": 20, "source": "live"}
r = get(force=True)
check("a new summary", r.get("summary") == "Now they are planning Saturday.", str(r))
check("and it replaces the stored one", get().get("summary") == "Now they are planning Saturday.")

print("\n== changing the settings makes the stored one stale ==")
asked.clear()
settings(length="short")
answers[1] = {"ok": True, "summary": "Short one.", "count": 20, "source": "live"}
r = get()
check("a different length is a different summary", r.get("summary") == "Short one.", str(r))
check("so the account was asked", len(asked) == 1)
check("with the new length", asked[-1][2]["length"] == "short")
asked.clear()
settings(length="short", messages=40)
get()
check("more messages is a different summary too", asked and asked[-1][2]["count"] == 40, str(asked))

print("\n== an old summary is rewritten ==")
settings(length="short", messages=40, refresh_minutes=0)
asked.clear()
get()
check("refresh_minutes 0 always writes a new one", len(asked) == 1, str(asked))

print("\n== a Snapchat chat goes to the Snapchat account ==")
settings()
asked.clear()
answers["snap"] = {"ok": True, "summary": "Snap chat.", "count": 6, "source": "recent"}
r = get(SNAP)
check("summary from Snapchat", r.get("summary") == "Snap chat.", str(r))
check("only the Snapchat account was asked", [a[0] for a in asked] == ["snap"], str(asked))
check("with the chat id as text", asked[-1][2]["user_id"] == SNAP)

print("\n== nobody can answer ==")
settings(refresh_minutes=0)
answers[1] = None                    # the account timed out
r = get()
check("the last summary is still shown", r.get("summary") and r.get("ok"), str(r))
check("marked as not refreshed", r.get("stale") is True)
check("with the reason", "did not answer" in (r.get("reason") or ""), str(r.get("reason")))
answers[1] = {"ok": False, "reason": "No messages with them that this account can read."}
r = get("555")
check("someone never summarised gets the reason, not a blank card",
      r.get("ok") is False and "No messages" in (r.get("reason") or ""), str(r))

print("\n== turned off in Settings ==")
settings(enabled=False)
asked.clear()
r = get()
check("the card is told it is off", r.get("enabled") is False, str(r))
check("and no account is asked", asked == [])

print("\n== forgetting someone forgets what you talked about ==")
settings()
client.request("DELETE", f"/api/memory/{UID}", json={})
check("the stored summary is gone", db.get_summary(UID) is None)

print("\n== the summary prompt describes the conversation, it does not join it ==")
from app.utils.ai import summary_instructions, SUMMARY_LENGTHS, _tidy_summary
txt = summary_instructions("Ana", "short", "auto")
check("it names who is who", "Me" in txt and "Ana" in txt)
check("it follows the conversation's language by default", "language the conversation" in txt)
check("or writes in the one chosen", "French" in summary_instructions("Ana", "short", "fr"))
check("each length has a size and an allowance",
      all(isinstance(v[0], str) and v[1] > 100 for v in SUMMARY_LENGTHS.values()))
check("an unknown length falls back instead of failing",
      "three or four points" in summary_instructions("Ana", "enormous", "auto"))

print("\n== a summary is read at a glance, not a wall of prose ==")
med = summary_instructions("Ana", "medium", "auto")
check("it asks for one bold headline", "**<what the conversation is mainly about" in med)
check("then short labelled points", "- **<Label>:**" in med and "three or four points" in med)
check("with anything still open said as such", "Waiting on" in med)
check("and nothing around it", "no intro" in med and "no closing line" in med)
check("the lengths are counts of points now", SUMMARY_LENGTHS["short"][0] == "two points")
messy = ("<think>let me see</think>\n```markdown\nHere is the summary:\n\n**Planning Saturday**\n\n"
         "* **Plans:** leaving at 8\n\n• **Vibe:** easy\n```")
check("a model's preamble, fence, thinking and blank lines are taken out",
      _tidy_summary(messy) == "**Planning Saturday**\n- **Plans:** leaving at 8\n- **Vibe:** easy",
      repr(_tidy_summary(messy)))
check("a summary that is already tidy is left as it is",
      _tidy_summary("**A**\n- **B:** c") == "**A**\n- **B:** c")
check("a stored summary in the old shape is written again the next time it is opened",
      chat_routes._summary_sig(chat_routes._SUMMARY_DEFAULTS).startswith(chat_routes._SUMMARY_FORMAT + "|"))

print("\n== the page reads that shape back ==")
import shutil as _sh
import subprocess as _sp
_node = _sh.which("node")
if not _node:
    print("  SKIP  needs Node")
else:
    _p = _sp.run([_node, str(ROOT / "tests" / "summarymd_logic.mjs")], cwd=ROOT / "webui",
                 capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(_p.stdout.strip())
    check("summarymd_logic.mjs passes", _p.returncode == 0, _p.stderr[-600:])
_ps = (ROOT / "webui" / "src" / "lib" / "components" / "PersonSummary.svelte").read_text(encoding="utf-8")
check("the Memory page draws it as a headline and points, not a block of text",
      "<SummaryText" in _ps and "whitespace-pre-line" not in _ps)

print("\n== the last few lines are kept with it ==")
settings()
answers[1] = {"ok": True, "summary": "**Saturday**\n- **Plans:** 8pm", "count": 12, "source": "live",
              "recent": [{"mine": False, "text": "what time?"}, {"mine": True, "text": "8pm works"},
                         {"mine": False, "text": ""}, "junk"]}
r = get("888", force=True)
check("they come back with a new summary", [l["text"] for l in r.get("recent", [])] == ["what time?", "8pm works"],
      str(r.get("recent")))
check("whose each one was", [l["mine"] for l in r["recent"]] == [False, True])
check("and with the stored one after", get("888").get("recent") == r["recent"])
long_line = [{"mine": False, "text": "x" * 900}] * 9
answers[1] = {"ok": True, "summary": "S", "count": 9, "source": "live", "recent": long_line}
r = get("889", force=True)
check("at most four, each cut to a length that fits a bubble",
      len(r["recent"]) == 4 and all(len(l["text"]) == 300 for l in r["recent"]), str(len(r.get("recent", []))))

print("\n== asking for the stored one only ==")
asked.clear()
r = client.get("/api/memory/888/summary?cached=true").json()
check("the stored one is given", r.get("ok") and r.get("summary", "").startswith("**Saturday**"), str(r))
check("without asking any account", asked == [], str(asked))
settings(refresh_minutes=0)
r = client.get("/api/memory/888/summary?cached=true").json()
check("even when it is old, marked so", r.get("ok") and r.get("stale") is True, str(r))
check("still without asking", asked == [], str(asked))
r = client.get("/api/memory/4242/summary?cached=true").json()
check("someone with none gets 'none yet', and nothing is written",
      r.get("ok") is False and r.get("missing") is True and asked == [] and db.get_summary("4242") is None, str(r))
settings(length="detailed")
r = client.get("/api/memory/888/summary?cached=true").json()
check("one written under other settings does not count", r.get("ok") is False and asked == [], str(r))
settings()

print("\n== the accounts send those lines ==")
_runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
_sum = _runner[_runner.index('elif cmd == "summarize_user":'):_runner.index('elif cmd == "analyse_user":')]
check("Discord sends the last four lines with the summary", '"recent":' in _sum and "lines[-4:]" in _sum)
_snap = (ROOT / "app" / "platforms" / "snapchat_bridge.py").read_text(encoding="utf-8")
_ssum = _snap[_snap.index('elif cmd == "summarize_user":'):_snap.index('elif cmd == "analyse_user":')]
check("and so does Snapchat", '"recent":' in _ssum and "lines[-4:]" in _ssum)

print("\n== a table from before the lines were kept ==")
import sqlite3 as _sq
_old = SANDBOX / "old.db"
_c = _sq.connect(_old)
_c.execute("CREATE TABLE user_summaries (user_key TEXT PRIMARY KEY, summary TEXT NOT NULL, generated_at REAL NOT NULL,"
           " message_count INTEGER NOT NULL DEFAULT 0, settings_sig TEXT NOT NULL DEFAULT '',"
           " source TEXT NOT NULL DEFAULT '')")
_c.execute("INSERT INTO user_summaries VALUES ('1', 'old one', 1.0, 3, 'x', '')")
db._ensure_summary_table(_c)
_cols = {r[1] for r in _c.execute("PRAGMA table_info(user_summaries)")}
check("gains the column in place, keeping what it had",
      "recent" in _cols and _c.execute("SELECT summary FROM user_summaries").fetchone()[0] == "old one")
_c.close()

print("\n== older config.yaml files ==")
# An existing config has no memory_summary section. The real reader must fill
# every key in, and the Settings page must show the default rather than blank.
chat_routes._summary_settings = _real_settings
got = _real_settings()
check("every setting has a value without the section",
      all(k in got for k in chat_routes._SUMMARY_DEFAULTS), str(got))
schema = client.get("/api/config/schema").json()
fields = {f["key"]: f for f in (schema.get("fields") or [])}
check("the settings appear in Settings", "bot.memory_summary.enabled" in fields)
check("with a real value, not an empty one",
      fields.get("bot.memory_summary.messages", {}).get("current") is not None,
      str(fields.get("bot.memory_summary.messages")))


print("\n== a double click writes one summary, not two ==")
import asyncio as _aio
chat_routes._summary_settings = _patched
settings(refresh_minutes=0)
calls = {"n": 0}


async def slow_answer(target, cmd, payload=None, timeout=10.0):
    calls["n"] += 1
    await _aio.sleep(0.3)
    return {"ok": True, "summary": "Once.", "count": 20, "source": "live"}


chat_routes.ipc.send_and_wait = slow_answer


async def _twice():
    return await _aio.gather(chat_routes.memory_summary(None, "777"),
                             chat_routes.memory_summary(None, "777"))

a, b = _aio.run(_twice())
check("the model is asked once", calls["n"] == 1, str(calls["n"]))
check("and both clicks get the answer", a.get("summary") == b.get("summary") == "Once.",
      f"{a.get('summary')} / {b.get('summary')}")
chat_routes.ipc.send_and_wait = fake_send_and_wait

print("\n== the Discord reader: who said what, in order ==")
# Pulled out of the runner and run against a stand-in bot, because the runner
# connects to Discord on import.
_rsrc = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
_fn = _rsrc[_rsrc.index("async def _conversation_lines("):_rsrc.index("async def _recent_messages(")]


class _Au:
    def __init__(self, i):
        self.id = i


class _M:
    def __init__(self, who, text, att=False):
        self.author = _Au(who)
        self.content = text
        self.attachments = [1] if att else []


class _U:
    def __init__(self):
        self.global_name, self.name, self.dm_channel = "Ana", "ana_", object()


class _Bot:
    def __init__(self, held):
        self.message_history = held
        self.selfbot_id = 1
        self.user = _Au(1)


def _run(held, live, scan_ok=True, include_mine=True, count=4):
    fetched = {"n": 0}

    async def _resolve(uid):
        return _U(), ""

    async def _recent(ch, n):
        fetched["n"] += 1
        return list(live)

    ns = {"bot": _Bot(held), "resolve_user": _resolve, "history_scan_allowed": lambda: scan_ok,
          "asyncio": _aio, "_recent_messages": _recent}
    exec(compile(_fn, "_conversation_lines", "exec"), ns)
    lines, name, source = _aio.run(ns["_conversation_lines"](9, count, include_mine))
    return lines, name, source, fetched["n"]


held = {"9-100": [{"role": "user", "content": "hey"}, {"role": "assistant", "content": "yo"},
                  {"role": "user", "content": "you free saturday?"},
                  {"role": "assistant", "content": "maybe, why"}]}
lines, name, source, n = _run(held, [])
check("what the bot already holds is used when it covers enough", n == 0 and source == "recent", f"{n} {source}")
check("their lines carry their name, the account's say Me",
      lines[0] == ("Ana", "hey") and lines[1] == ("Me", "yo"), str(lines))

# Newest first, the way Discord returns history.
live = [_M(9, "ok see you then"), _M(1, "7pm works"), _M(9, "what time?"), _M(9, "", att=True)]
lines, name, source, n = _run({}, live)
check("with too little held, it reads the DM", n == 1 and source == "live", f"{n} {source}")
check("oldest first, so the model reads it in order",
      [t for _, t in lines] == ["[attachment]", "what time?", "7pm works", "ok see you then"], str(lines))
lines, *_ = _run({}, live, include_mine=False)
check("'only their side' drops the account's messages", all(w != "Me" for w, _ in lines), str(lines))
lines, name, source, n = _run({"9-100": held["9-100"][:1]}, live, scan_ok=False)
check("with the history budget spent, it does not ask Discord", n == 0, str(n))
check("and uses what it has instead", lines == [("Ana", "hey")], str(lines))
check("the bot's own compressed-history note is not summarised as a message",
      "[Earlier in this conversation:" in _fn and "startswith(\"[Earlier in this conversation:\")" in _fn)
check("it runs as a task, so it cannot hold up the Chats list",
      "asyncio.create_task(_summarize())" in _rsrc)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
