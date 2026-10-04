"""Things seen in the logs, put right, and two small asks.

  * the panel froze for a second looking up names: it read every profile ever
    saved to keep a few, on the thread every page shares
  * a reply Discord turned away for a moment (503) was lost: it is sent again
  * a model fallback says why the first model was passed over
  * a message of the account's that read like an assistant goes into the
    refusal phrases from its right-click menu
  * a picture card's buttons, and its check to select it
  * the sessions check failed at every Discord login on the shape of
    Discord's answer
"""
import asyncio
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-logfixes-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def src(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== looking up names, without freezing the panel ==")
from app.utils.db import connect_raw  # noqa: E402
from app.web.routes import chat_routes  # noqa: E402

conn = connect_raw()
conn.execute("CREATE TABLE IF NOT EXISTS user_profiles (user_id INTEGER PRIMARY KEY, display_name TEXT, username TEXT, avatar TEXT, bio TEXT, fetched_at REAL)")
conn.executemany("INSERT INTO user_profiles (user_id, display_name, username, avatar, fetched_at) VALUES (?, ?, ?, ?, ?)",
                 [(1000000000000000000 + i, f"Person {i}", f"p{i}", "", time.time()) for i in range(30000)])
conn.commit()
conn.close()
start = time.perf_counter()
got = chat_routes._profiles_for(["1000000000000000007", "1000000000000000123", "nope", None])
took = time.perf_counter() - start
check("only the ones asked for, by the table's key", set(got) == {"1000000000000000007", "1000000000000000123"}
      and got["1000000000000000007"]["display_name"] == "Person 7", str(got)[:200])
check("in a moment, among thirty thousand", took < 0.2, f"{took:.3f}s")
routes = src("app/web/routes/chat_routes.py")
check("and off the thread every page shares", "await asyncio.to_thread(_profiles_for, [u.get(\"id\") for u in users])" in routes
      and "await asyncio.to_thread(_profiles_for, {m[\"uid\"] for m in found})" in routes)
archive_fn = routes[routes.index("def archive("):routes.index('@router.get("/api/chats/snap-picture')]
check("the answered list asks for its own people only", "_profiles_for([uid for uid, *_ in rows])" in archive_fn
      and "FROM user_profiles" not in archive_fn)

print("\n== a send Discord turned away for a moment ==")
import discord  # noqa: E402

runner = src("app/platforms/discord_runner.py")
fn = runner[runner.index("async def _send_retrying("):runner.index("@bot.event\nasync def on_relationship_remove")]
said = []
ns = {"discord": discord, "asyncio": asyncio, "random": types.SimpleNamespace(random=lambda: 0.0),
      "log_system": said.append}
exec(fn, ns)
send_retrying = ns["_send_retrying"]
real_sleep = asyncio.sleep
ns["asyncio"] = types.SimpleNamespace(sleep=lambda s: real_sleep(0))


def server_error(status):
    return discord.DiscordServerError(types.SimpleNamespace(status=status, reason="x"), "upstream connect error")


tries = []


async def flaky():
    tries.append(1)
    if len(tries) < 3:
        raise server_error(503)
    return "sent"

check("a 503 is sent again, and goes through", asyncio.run(send_retrying(flaky, "Ana")) == "sent" and len(tries) == 3
      and "Discord was briefly unavailable (503) sending to Ana; trying again in a moment" in said, str(said))
tries.clear()


async def always():
    tries.append(1)
    raise server_error(503)

try:
    asyncio.run(send_retrying(always))
    gave_up = False
except discord.DiscordServerError:
    gave_up = True
check("three times at most, then it is a failure like any other", gave_up and len(tries) == 3)
tries.clear()


async def other():
    tries.append(1)
    raise server_error(500)

try:
    asyncio.run(send_retrying(other))
except discord.DiscordServerError:
    pass
check("anything but a 503 is not sent again: it may have arrived", len(tries) == 1)
check("every reply chunk goes through it", "sent_msg = await _send_retrying(_send_chunk, message.author.name)" in runner)

print("\n== a model fallback says why ==")
from app.utils import ai  # noqa: E402

check("too long", ai._why_passed_over(ai.RequestTooLarge("x")) == "the conversation was too long for it")
check("timed out", ai._why_passed_over(TimeoutError("Request timed out.")) == "it took too long to answer")
check("not reachable", ai._why_passed_over(ConnectionRefusedError("refused")) == "it could not be reached")
err = Exception("bad")
err.status_code = 500
check("an answer it gave", ai._why_passed_over(err) == "it answered 500")
check("nothing to say when nothing failed", ai._why_passed_over(None) == "")
check("and the log line carries it", "f\"{f' ({why})' if why else ''}{RESET}\"" in src("app/utils/logger.py")
      and "_why_passed_over(prev_error)" in src("app/utils/ai.py"))

print("\n== refusal phrases, from a message ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import config_routes  # noqa: E402
from app.utils.helpers import load_config  # noqa: E402

config_routes.CONFIG_PATH = TMP / "config" / "config.yaml"


async def no_live(*a, **k):
    return None

config_routes._live_apply = no_live
app = FastAPI()
app.include_router(config_routes.router)
client = TestClient(app)
r = client.post("/api/config/refusal-phrase", json={"phrase": "  I’m sorry, but I can’t   help with that. "}).json()
phrases = (load_config().get("bot") or {}).get("refusal", {}).get("extra_phrases")
check("added to the extra refusal phrases, tidied", r["added"] and phrases[-1] == "I’m sorry, but I can’t help with that.", str(phrases))
r = client.post("/api/config/refusal-phrase", json={"phrase": "i'm SORRY, but i can't help with that."}).json()
check("the same again, in any case or quoting, is not added twice", not r["added"]
      and len((load_config().get("bot") or {}).get("refusal", {}).get("extra_phrases")) == len(phrases))
check("a word or two is not a phrase", client.post("/api/config/refusal-phrase", json={"phrase": "ok"}).status_code == 400)
from app.core import engine  # noqa: E402

check("and the bot counts it as a refusal from its next reply", engine.is_refusal("I’m sorry, but I can’t help with that."))
chats = src("webui/src/pages/Chats.svelte")
check("on the account's own messages, all of it or the part selected",
      'label: picked ? "Add the selection to refusal phrases" : "Add to refusal phrases"' in chats
      and "m.mine && words.length >= 3" in chats and "use:contextMenu={(e) => messageMenu(d.m, e)}" in chats)

print("\n== refusals that still got through ==")
for t in ["I can’t do that.", "i can’t do that", "I won’t be able to help with that.", "I can’t create that kind of content.",
          "I’m srry, but I can’t help with that.", "Sorry, I can’t assist with that request."]:
    check(f"caught: {t}", engine.is_refusal(t))
for t in ["nah i can't do that tonight", "lol i can't do that", "i can't wait to see you", "sorry i can't make it tonight",
          "i won't be able to come tomorrow", "i can't believe you did that"]:
    check(f"left alone: {t}", not engine.is_refusal(t))
loop = runner[runner.index("# Last line of defence, per chunk"):runner.index("log_response(message.author.name, chunk)")]
check("the last check on each chunk comes before a typo is put in", loop.index("is_refusal(chunk)") < loop.index("add_typo(chunk"))

print("\n== a reply asked for by hand, cancelled while it is written ==")
check("each one is held while it runs, by whom it is for", "_manual_replies[key] = asyncio.current_task()" in runner
      and '_manual_replies[f"ch{cid}"] = asyncio.current_task()' in runner)
check("Cancel stops it, for a person and in a server channel", "_stopped = _stop_manual_reply(uid)" in runner
      and 'stopped = _stop_manual_reply(f"ch{cid}")' in runner)
check("and says so instead of leaving the panel waiting", runner.count('"cancelled": True, "reason": "you cancelled the reply"') == 2)
bridge = src("app/platforms/snapchat_bridge.py")
check("Snapchat too: the reply job held, cancelled, and what it queued taken back", "_REPLY_TASKS[uid] = task" in bridge
      and 'elif cmd == "cancel_reply":' in bridge and "_drop_lined_up(uid, by_hand=False) or _drop_outgoing(uid)" in bridge)
chats = src("webui/src/pages/Chats.svelte")
check("the button stays there, and works, while it is written",
      "{#if (cancellable(selected) || replying[selected.id]) && !selected.ignored}" in chats
      and "disabled={!!rowBusy[selected.id]}>" in chats and "if (res?.cancelled) return;" in chats)

print("\n== Snapchat's own chats ==")
snaprun = src("app/platforms/snapchat/snapchat_runner.js")
check("never answered from a chat opened in the panel", "!SYSTEM_CHATS.includes(String(name).toLowerCase().trim())" in snaprun
      and "const IGNORED_NAMES = SYSTEM_CHATS;" in snaprun)
check("nor by the bridge, whatever comes in", '_SYSTEM_CHATS = {"my ai", "team snapchat"}' in bridge
      and 'if (user_name or "").strip().lower() in _SYSTEM_CHATS:' in bridge)

print("\n== how things look ==")
check("the search over the list sits above it, with a pill that slides between the filters", 'class="ch-left"' in chats
      and 'class="ch-chip-pill"' in chats and "function placePill()" in chats and ".ch-chip-pill.is-moving {" in chats)
check("where the reply is, in one slim line", 'class="cd-strip is-live"' in chats and ".cd-strip {" in chats
      and "cd-track-now" not in chats)
search = src("webui/src/lib/components/ChatSearch.svelte")
check("the search panel's start: a row per filter, keycaps for the keys", 'class="cs-key"' in search and "<kbd>Enter</kbd>" in search)
css = src("webui/src/app.css")
check("menus and dropdowns in the panels' own material", ':root[data-surface="glass"] .glass.floating:not(.glow)' in css
      and 'class="gm float-surface"' in src("webui/src/lib/components/GlobalMenu.svelte"))
gm = src("webui/src/lib/components/GlobalMenu.svelte")
check("Reload in yellow, adding a refusal phrase in red", 'label: "Reload", icon: "refresh", keys: "Ctrl R", warn: true' in gm
      and ".gm-item.is-warn," in gm and "danger: true," in chats)
wb = src("webui/src/lib/dashboard/WidgetBody.svelte")
check("most active people: medals, a platform on each face, the share as a meter",
      "data-rank={i < 3 ? i + 1 : undefined}" in wb and 'class="ap-platform"' in wb and 'class="ap-share-bar"' in wb)

print("\n== a picture card's buttons ==")
pics = src("webui/src/pages/Pictures.svelte")
check("a row of its own: edit, describe, and delete on the far side", 'class="pc-actions"' in pics
      and 'class="pc-btn is-describe"' in pics and 'class="pc-btn is-danger"' in pics and ".pc-btn.is-danger { margin-left: auto; }" in pics)
check("a round check to select one, there on hover and once any is picked", 'class="pc-select"' in pics
      and ".pic-card:hover .pc-select, .pic-card.is-picking .pc-select" in pics and "@media (hover: none)" in pics)

print("\n== the sessions check at each Discord login ==")
import ast  # noqa: E402

_runner = ast.parse(src("app/platforms/discord_runner.py"))
_sessions_fn = next(n for n in _runner.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_log_active_sessions")


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _Session:
    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        return _Resp(self.data)


def sessions_logged(data):
    """The function itself, run against an answer of Discord's shape, with what it logs caught."""
    logged, errors = [], []
    ns = {
        "asyncio": types.SimpleNamespace(sleep=lambda s: asyncio.sleep(0)),
        "build_session": lambda token: _Session(data),
        "bot": types.SimpleNamespace(_connection=types.SimpleNamespace(http=types.SimpleNamespace(token="t"))),
        "log_system": logged.append,
        "log_error": lambda where, msg: errors.append(f"{where}: {msg}"),
    }
    exec(compile(ast.Module(body=[_sessions_fn], type_ignores=[]), "discord_runner.py", "exec"), ns)
    asyncio.run(ns["_log_active_sessions"]())
    return logged, errors


logged, errors = sessions_logged({"user_sessions": [
    {"id_hash": "a1", "approx_last_used_time": "2026-10-02T13:00:00+00:00",
     "client_info": {"os": "Windows", "platform": "Discord Client", "location": "Somewhere, Nowhere"}},
    {"id_hash": "b2", "approx_last_used_time": "2026-10-01T09:30:00+00:00",
     "client_info": {"os": "Android", "platform": "Discord Android", "location": "Somewhere, Nowhere"}},
]})
check("Discord's answer is read: a line per session, no error", errors == [] and logged == [
    "[SESSIONS] os=Windows platform=Discord Client last used=2026-10-02T13:00:00+00:00",
    "[SESSIONS] os=Android platform=Discord Android last used=2026-10-01T09:30:00+00:00",
], f"{logged} {errors}")
check("where a session is stays out of the log", not any("Somewhere" in line for line in logged))
logged, errors = sessions_logged({"user_sessions": None})
check("no sessions listed: nothing logged, no error", logged == [] and errors == [], f"{logged} {errors}")
logged, errors = sessions_logged([{"client_info": {"os": "Linux", "platform": "Chrome"}}, "odd"])
check("a bare list is read too, and anything odd in it skipped", errors == []
      and logged == ["[SESSIONS] os=Linux platform=Chrome last used=None"], f"{logged} {errors}")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
