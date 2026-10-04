"""Try, and the model lists, get through to the provider.

Try on a Groq model said "The key is not allowed to use this model." with keys
that were answering every reply. Groq sits behind Cloudflare, which turns
Python's default "Python-urllib/3.x" agent away with a 403 ("error code:
1010") before the key is looked at, and Try was the one thing sending that
agent: replies go through the providers' own libraries, which name themselves.
The same went for every model list fetched the same way. So the app names
itself, a block in front of a provider is no longer blamed on the key, and Try
sends a reply's own token cap, since 16 tokens was all thinking and no answer
for a model that thinks first.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


seen = []


class LikeCloudflare(BaseHTTPRequestHandler):
    """Refuses Python's default agent the way Cloudflare does; otherwise a provider that answers."""

    def log_message(self, *a):
        pass

    def _send(self, code, body, kind="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _blocked(self):
        agent = self.headers.get("user-agent", "")
        seen.append(agent)
        if agent.startswith("Python-urllib"):
            self._send(403, "error code: 1010\n", "text/plain; charset=UTF-8")
            return True
        return False

    def do_GET(self):
        if self._blocked():
            return
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "model-a"}, {"id": "model-b"}]})
        self._send(404, {"error": {"message": "nope"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if self._blocked():
            return
        seen.append(body)
        if body.get("model") == "blocked-model":
            return self._send(403, {"error": {"message": "The model `blocked-model` is blocked at the organization level.",
                                              "type": "permission_error"}})
        if body.get("model") == "missing":
            return self._send(404, {"error": {"message": "The model `missing` does not exist or you do not have access to it."}})
        self._send(200, {"choices": [{"message": {"content": "ok"}}]})


server = HTTPServer(("127.0.0.1", 0), LikeCloudflare)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}/v1"

from app.utils import providers
from app.web.routes import models_routes

providers.base_url = lambda pid, config: BASE
providers.keys_for = lambda pid: ["sk-test"]

print("== the app names itself ==")
agent = providers.user_agent()
check("as itself, not as Python", agent.startswith("LLMSelfbot/") and "urllib" not in agent.lower(), agent)

print("\n== Try gets through ==")
r = models_routes._try("openai", "model-a", {"bot": {}})
check("a model behind a Cloudflare-style guard answers", r.get("ok") is True and r.get("reply") == "ok", str(r))
check("because the request carried the app's name", seen and all(not str(a).startswith("Python-urllib")
                                                                  for a in seen if isinstance(a, str)), str(seen))
sent = [b for b in seen if isinstance(b, dict)][-1]
check("with a reply's own token cap, not 16", sent.get("max_tokens") == 320, str(sent.get("max_tokens")))
seen.clear()
models_routes._try("openai", "model-a", {"bot": {"max_reply_tokens": 500}})
check("including a cap changed in settings", [b for b in seen if isinstance(b, dict)][-1].get("max_tokens") == 500)

r = models_routes._try("groq", "blocked-model", {"bot": {}})
check("a model the key really cannot use still says so", r.get("error") == "This key is not allowed to use this model."
      and "organization level" in r.get("detail", ""), str(r))
r = models_routes._try("groq", "missing", {"bot": {}})
check("and a model the provider does not have says that", r.get("error") == "Groq does not have that model.", str(r))

print("\n== a block in front of the provider is not the key's fault ==")
error, detail = providers.http_error("groq", 403, "error code: 1010\n")
check("it says the request was turned away before the key was checked",
      "turned the request away before checking the key" in error and "1010" in error, error)
check("and never that the key is not allowed", "not allowed" not in error and "refused" not in error, error)
check("a real refusal still names the key", providers.http_error("openai", 401, '{"error": {"message": "Incorrect API key provided."}}')
      == ("The key was refused.", "Incorrect API key provided."))

print("\n== the model lists get through too ==")
providers._cache.clear()
seen.clear()
listed = providers.list_models("mistral", {"bot": {}}, force=True)
check("a provider's model list loads behind the same guard", [m["id"] for m in listed["models"]] == ["model-a", "model-b"]
      and not listed["error"], str(listed))
check("sent with the app's name", seen and seen[0].startswith("LLMSelfbot/"), str(seen[:1]))

server.shutdown()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
