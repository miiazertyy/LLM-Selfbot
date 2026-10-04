"""Today's fixes, kept fixed.

  * Replies failed on a local model: Ollama's default context is 4096 tokens and
    a persona of a few pages fills that alone. The app now starts Ollama with a
    bigger window, a too-small window is treated as a request too large (trim,
    retry once, then say so in words), and the raw 400 is not logged three times.
  * Accepting a friend request always failed with 400 / 80013, "You must confirm
    the friend request to add this user": Discord wants confirm_stranger_request
    for someone you share no server with.
  * Every job besides replies can have fallbacks, tried in order, then Groq.
  * Ignoring someone from Chats works whether or not the account is running.
"""
import asyncio
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SANDBOX = Path(tempfile.mkdtemp(prefix="llmbot_today_"))
(SANDBOX / "logs").mkdir()
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== a context that is too small ==")
import app.utils.ai as ai
err = Exception("Error code: 400 - {'error': {'message': '{\"error\":{\"code\":400,\"message\":\"request (5397 tokens) "
                "exceeds the available context size (4096 tokens), try increasing it\",\"type\":\"exceed_context_size_error\"}}'}}")
check("is treated as a request too large", ai.is_request_too_large(err) and not ai.is_output_limit(err))
check("with the numbers read out of it", ai.context_numbers(err) == (5397, 4096))
check("and a reason a person can act on", "4096" in ai.explain_too_large(err) and "This computer" in ai.explain_too_large(err))
from app.utils import localai
check("Ollama gets a real window by default", localai.settings({"bot": {}})["context_length"] >= 8192)
src = (ROOT / "app" / "utils" / "localai.py").read_text(encoding="utf-8")
check("which the app passes when it starts Ollama", 'env["OLLAMA_CONTEXT_LENGTH"]' in src)
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("and the runner does not send the same oversized request three times",
      "ai_module.explain_too_large(e)" in runner)

print("\n== accepting a friend request ==")
start = runner.index("_FRIENDS_CONTEXT = ")
end = runner.index("def get_channel_context(")
ns = {}
exec(compile(runner[start:end], "friend_helpers", "exec"), ns)


class R:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class S:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def put(self, url, json=None, headers=None):
        self.calls.append((json, headers or {}))
        return self.answers.pop(0)


s = S([R(400, {"message": "You must confirm the friend request to add this user.", "code": 80013}), R(204, {})])
r = asyncio.run(ns["accept_friend_request"](s, 42))
check("a stranger's request is confirmed, as Discord's own client does", r.status_code == 204
      and s.calls[1][0] == {"confirm_stranger_request": True}, str(s.calls))
check("from the Friends list, as the client says", "X-Context-Properties" in s.calls[1][1])
s = S([R(204, {})])
asyncio.run(ns["accept_friend_request"](s, 42))
check("an ordinary request is one plain accept", len(s.calls) == 1 and s.calls[0][0] == {"type": 1})
check("a refusal says why, in Discord's words",
      "confirm the friend request" in ns["discord_reason"](R(400, {"message": "You must confirm the friend request to add this user.", "code": 80013})))
check("and a captcha is named as one", "captcha" in ns["discord_reason"](R(400, {"captcha_key": ["x"]})))
check("the button and both automatic accepts use it", runner.count("await accept_friend_request(") >= 3)

print("\n== fallbacks for every job ==")
from app.utils import providers
cfg = {"bot": {"groq_image_model": "img", "models": {"vision": [
    {"provider": "gemini", "model": "g1"}, {"provider": "openai", "model": "o1"}, {"provider": "gemini", "model": "g1"}]}}}
check("a job's list is kept in order, once each",
      providers.job_chain(cfg, "vision") == [{"provider": "gemini", "model": "g1"}, {"provider": "openai", "model": "o1"}])
check("and its first is the job's model", providers.job(cfg, "vision") == {"provider": "gemini", "model": "g1"})
check("an unset job is just Groq's", providers.job_chain({"bot": {"groq_image_model": "img"}}, "vision")
      == [{"provider": "groq", "model": "img"}])


class Fake:
    def __init__(self, name, fail):
        self.name, self.fail = name, fail
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._c))

    async def _c(self, model, messages, **kw):
        if self.fail:
            raise RuntimeError(f"{self.name} down")
        return f"{self.name}:{model}"


tried = []
ai._initialised = True
ai.load_config = lambda: cfg
clients = {"gemini": Fake("gemini", True), "openai": Fake("openai", False)}
ai._openai_client = lambda pid, c: clients.get(pid)
ai._groq_clients = [{"client": object(), "label": "K"}]


async def on_groq(m):
    tried.append(m)
    return f"groq:{m}"

out = asyncio.run(ai._job_call("vision", lambda c, m: c.chat.completions.create(model=m, messages=[]), on_groq))
check("a job falls through its list to the next model", out == "openai:o1", str(out))
clients["openai"].fail = True
out = asyncio.run(ai._job_call("vision", lambda c, m: c.chat.completions.create(model=m, messages=[]), on_groq))
check("and to Groq's own model after the whole list", out == "groq:img", str(out))

print("\n== ignoring from Chats ==")
chat_routes = (ROOT / "app" / "web" / "routes" / "chat_routes.py").read_text(encoding="utf-8")
check("the ignore list is read from the database", "/api/chats/ignored" in chat_routes and "db.get_ignored_users()" in chat_routes)
check("and setting it writes the database first", "(db.add_ignored_user if want else db.remove_ignored_user)" in chat_routes)
chats = (ROOT / "webui" / "src" / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("rows that need you have the X", 'class="ch-x"' in chats and ("ignorePerson(u, e)" in chats or "ignorePerson(personOf(u), e)" in chats))
check("ignored people are off the list and under Ignored", "users.filter((u) => !u.ignored)" in chats and "unignore(p)" in chats)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
