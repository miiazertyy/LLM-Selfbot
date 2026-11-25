"""The MCP program an AI app starts (app/utils/mcpserver.py; 2026-11-09). It has to speak both generations of the protocol,
because AI apps are on either, and only protocol may reach stdout. Run for real at the end: main.py --mcp over pipes,
with a stand-in for the open app."""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import use_shipped_config  # noqa: E402

sandbox = use_shipped_config()

from app.utils import apptools, mcpserver  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


asked = []


def stand_in(tool, args, who):
    asked.append((tool, args, who))
    if tool == "change_setting":
        return {"ok": False, "error": "That one is locked."}
    return {"ok": True, "result": {"key": "bot.x", "note": "café"}}


def line(obj):
    return json.dumps(obj).encode("utf-8")


MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {},
               "io.modelcontextprotocol/clientInfo": {"name": "new-client", "title": "New Client", "version": "1"}}


def modern(method, id_=1, **params):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": {"_meta": MODERN_META, **params}}


def legacy(method, id_=1, **params):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}


print("== an older AI app ==")
s = mcpserver.Server(ask=stand_in)
r = s.handle_line(line(legacy("tools/list")))
check("before it opens, nothing is served", r["error"]["code"] == -32602, str(r))
r = s.handle_line(line(legacy("initialize", protocolVersion="2025-06-18", capabilities={}, clientInfo={"name": "old-client", "version": "1"})))
check("initialize answers with the version it asked for", r["result"]["protocolVersion"] == "2025-06-18", str(r))
check("and says it has tools", r["result"]["capabilities"] == {"tools": {}})
check("and who this is", r["result"]["serverInfo"]["name"] == "llmselfbot" and r["result"]["serverInfo"]["version"])
check("and how to use it", "Search before" in r["result"]["instructions"])
check("the initialized notification gets no answer", s.handle_line(line({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None)
r = s.handle_line(line(legacy("tools/list")))
check("the tools are listed", {t["name"] for t in r["result"]["tools"]} == apptools.NAMES, str(r)[:300])
check("each with a schema", all(t["inputSchema"]["type"] == "object" and t["description"] for t in r["result"]["tools"]))
check("nothing from the newer protocol", "resultType" not in r["result"] and "ttlMs" not in r["result"])
r = s.handle_line(line(legacy("tools/call", name="get_setting", arguments={"key": "bot.x"})))
check("a tool is passed on to the open app", asked[-1] == ("get_setting", {"key": "bot.x"}, "old-client"), str(asked[-1]))
check("and its answer comes back as text", json.loads(r["result"]["content"][0]["text"])["key"] == "bot.x" and r["result"]["isError"] is False, str(r))
r = s.handle_line(line(legacy("tools/call", name="change_setting", arguments={"key": "a", "value": "b"})))
check("a refusal is a tool error, for the AI to read", r["result"]["isError"] is True and "locked" in r["result"]["content"][0]["text"], str(r))
check("ping answers", s.handle_line(line(legacy("ping")))["result"] == {})
s2 = mcpserver.Server(ask=stand_in)
r = s2.handle_line(line(legacy("initialize", protocolVersion="1999-01-01", capabilities={}, clientInfo={"name": "x", "version": "1"})))
check("a version it does not know gets the newest old one", r["result"]["protocolVersion"] == mcpserver.LEGACY[0], str(r))

print("\n== a current AI app ==")
s = mcpserver.Server(ask=stand_in)
r = s.handle_line(line(modern("server/discover")))
result = r["result"]
check("discover works with no handshake", result["supportedVersions"] == ["2026-07-28"] and result["capabilities"] == {"tools": {}}, str(r))
check("every result says it is complete", result["resultType"] == "complete")
check("and who answered", result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "llmselfbot")
check("discover says how long to keep it", result["ttlMs"] > 0 and result["cacheScope"] == "public")
r = s.handle_line(line(modern("tools/list")))
check("tools/list too", {t["name"] for t in r["result"]["tools"]} == apptools.NAMES and r["result"]["resultType"] == "complete" and r["result"]["ttlMs"] > 0 and r["result"]["cacheScope"] == "public", str(r)[:200])
r = s.handle_line(line(modern("tools/call", name="list_personas", arguments={})))
check("a tool runs", r["result"]["resultType"] == "complete" and r["result"]["isError"] is False, str(r))
check("the AI app is named by its title", asked[-1][2] == "New Client", str(asked[-1]))
bad = dict(MODERN_META, **{"io.modelcontextprotocol/protocolVersion": "1900-01-01"})
r = s.handle_line(line({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {"_meta": bad}}))
check("a version it does not speak is the spec's own error", r["error"]["code"] == -32022 and r["error"]["data"]["requested"] == "1900-01-01"
      and "2026-07-28" in r["error"]["data"]["supported"], str(r))
missing = {k: v for k, v in MODERN_META.items() if "clientCapabilities" not in k}
r = s.handle_line(line({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {"_meta": missing}}))
check("a request missing a required field is refused", r["error"]["code"] == -32602, str(r))
r = s.handle_line(line({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}}))
check("as is one with no _meta and no handshake", r["error"]["code"] == -32602, str(r))

print("\n== what goes wrong ==")
r = s.handle_line(b"not json")
check("not JSON", r["error"]["code"] == -32700 and r["id"] is None, str(r))
r = s.handle_line(b'{"id":3,"method":"tools/list"}')
check("not JSON-RPC", r["error"]["code"] == -32600 and r["id"] == 3, str(r))
r = s.handle_line(b'[1,2]')
check("not an object", r["error"]["code"] == -32600 and r["id"] is None, str(r))
r = s.handle_line(line(modern("resources/list")))
check("a method it does not have", r["error"]["code"] == -32601, str(r))
r = s.handle_line(line(modern("tools/call", name="send_message", arguments={})))
check("a tool it does not have", r["error"]["code"] == -32602 and "send_message" in r["error"]["message"], str(r))
r = s.handle_line(line(modern("tools/call", name="get_setting", arguments="x")))
check("arguments that are not an object", r["error"]["code"] == -32602, str(r))
check("a cancel gets no answer", s.handle_line(line({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})) is None)
check("an answer to nothing gets no answer", s.handle_line(line({"jsonrpc": "2.0", "id": 5, "result": {}})) is None)


def blows_up(*a):
    raise RuntimeError("no")


r = mcpserver.Server(ask=blows_up).handle_line(line(modern("tools/call", name="list_personas", arguments={})))
check("a crash in one call is an error, and the connection lives", r["error"]["code"] == -32603, str(r))

print("\n== finding the open app ==")
check("before the app has said where it is, it is not open", mcpserver._panel_address() is None
      and mcpserver.ask_app("list_personas", {}, "x") == {"ok": False, "error": mcpserver.NOT_OPEN})
mcpserver.note_port(45123)
check("the panel's port is noted", mcpserver._panel_address() == "127.0.0.1:45123")
mcpserver.note_port(45124, "0.0.0.0")
check("open to the network, it is still reached on this computer", mcpserver._panel_address() == "127.0.0.1:45124")
mcpserver.note_port(45125, "100.64.0.7")
check("bound to one address, it is reached on that one", mcpserver._panel_address() == "100.64.0.7:45125")
(sandbox / "cache" / "panel.json").write_text("nonsense", encoding="utf-8")
check("a file it can't read means not open, not a guess at the usual port", mcpserver._panel_address() is None)
server_src = (ROOT / "app" / "web" / "server.py").read_text(encoding="utf-8")
check("the panel notes its port as it starts", "mcpserver.note_port(port, bind)" in server_src)


class Gone(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.send_response(404)
        self.send_header("content-length", "0")
        self.end_headers()


other = ThreadingHTTPServer(("127.0.0.1", 0), Gone)
threading.Thread(target=other.serve_forever, daemon=True).start()
mcpserver.note_port(other.server_address[1])
check("something else on that port means not open", mcpserver.ask_app("list_personas", {}, "x") == {"ok": False, "error": mcpserver.NOT_OPEN})
other.shutdown()
other.server_close()
check("only the standard library at the top", "fastapi" not in (ROOT / "app" / "utils" / "mcpserver.py").read_text(encoding="utf-8"))
check("no bootstrap, no lock: it starts before those", (ROOT / "app" / "cli.py").read_text(encoding="utf-8").index("if args.mcp:")
      < (ROOT / "app" / "cli.py").read_text(encoding="utf-8").index("    bootstrap()\n\n    if args.role"))

print("\n== for real, over pipes ==")
seen_requests = []


class Panel(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        seen_requests.append((self.path, self.headers.get("x-llmselfbot"), body))
        reply = {"ok": False, "error": "That one is locked."} if body["tool"] == "change_setting" \
            else {"ok": True, "result": {"note": "café \U0001f600"}}
        data = json.dumps(reply).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


panel = ThreadingHTTPServer(("127.0.0.1", 0), Panel)
threading.Thread(target=panel.serve_forever, daemon=True).start()
data_dir = Path(tempfile.mkdtemp(prefix="mcp-"))
(data_dir / "cache").mkdir()
(data_dir / "cache" / "panel.json").write_text(json.dumps({"port": panel.server_address[1]}), encoding="utf-8")
env = {**os.environ, "LLMSELFBOT_DATA_DIR": str(data_dir), "PYTHONIOENCODING": "utf-8", "HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}


def start():
    p = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--mcp"], cwd=str(ROOT), env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timer = threading.Timer(90, p.kill)
    timer.daemon = True
    timer.start()
    return p, timer


def rpc(p, obj):
    p.stdin.write(line(obj) + b"\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


p, timer = start()
r = rpc(p, legacy("initialize", protocolVersion="2025-11-25", capabilities={}, clientInfo={"name": "pipe-client", "version": "1"}))
check("it answers over stdout", r["result"]["serverInfo"]["name"] == "llmselfbot", str(r))
p.stdin.write(line({"jsonrpc": "2.0", "method": "notifications/initialized"}) + b"\n")
r = rpc(p, legacy("tools/list", 2))
check("the next line is the next answer", r["id"] == 2 and len(r["result"]["tools"]) == len(apptools.TOOLS), str(r)[:200])
r = rpc(p, legacy("tools/call", 3, name="read_persona", arguments={"id": "default"}))
text = r["result"]["content"][0]["text"]
check("a call reaches the open app, past any web proxy", seen_requests and seen_requests[-1][0] == "/api/apptools/call", str(r))
check("  saying it is the panel, and which AI app asked", seen_requests[-1][1] == "1" and seen_requests[-1][2]["who"] == "pipe-client", str(seen_requests[-1]))
check("accents and emoji survive", "café \U0001f600" in json.loads(text)["note"], text)
r = rpc(p, legacy("tools/call", 4, name="change_setting", arguments={"key": "a", "value": "b"}))
check("a refusal comes through", r["result"]["isError"] is True, str(r))
p.stdin.close()
code = p.wait(30)
check("it leaves when the AI app closes stdin", code == 0, str(code))
rest = p.stdout.read()
check("nothing else was on stdout", rest == b"", rest[:200].decode("utf-8", "replace"))
timer.cancel()

panel.shutdown()
panel.server_close()
p, timer = start()
r = rpc(p, modern("tools/call", name="list_personas", arguments={}))
check("with the app closed, it says to open it", r["result"]["isError"] is True and r["result"]["content"][0]["text"] == mcpserver.NOT_OPEN, str(r))
p.stdin.close()
p.wait(30)
timer.cancel()

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
