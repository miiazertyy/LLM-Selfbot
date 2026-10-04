"""Starting Ollama / LM Studio from the app, and the bits around it.

A local server that was installed but not running was a dead end: the panel
said "not answering" and you had to go and start it yourself. The app now
starts it from a button, and on its own at launch when something is set to run
on it. Nothing here really starts a server: the process launch is faked.
Also checked: Free / Paid on every provider, the notice card's Start button,
and fetching a message behind an "[attachment]" row.
"""
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# A data folder of its own, with the shipped config: run from a checkout the app reads config/ beside the code, which
# only this computer has (a build machine has none, and the app exits for want of a config).
TMP = Path(tempfile.mkdtemp(prefix="llm-launch-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

from app.utils import localai, providers
# Imported before subprocess.Popen is faked below: asyncio subclasses Popen on
# Windows, and importing it for the first time under the fake breaks it for the
# rest of the process.
import asyncio  # noqa: F401
import app.web.logbus  # noqa: F401
from app.web.routes.chat_routes import apply_event

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== which server, and whether it is here ==")
check("port 11434 is Ollama", localai.server_for("http://127.0.0.1:11434/v1") == "ollama")
check("port 1234 is LM Studio", localai.server_for("localhost:1234") == "lmstudio")
check("anything else is treated as Ollama", localai.server_for("http://127.0.0.1:9999/v1") == "ollama")
check("a missing program reads as not installed", localai.installed("vllm") == "")

print("\n== starting one ==")
state = {"probes": 0, "argv": None, "env": None}
real_probe, real_installed, real_popen = localai.probe, localai.installed, localai.subprocess.Popen


def fake_probe(url, timeout=2.0):
    state["probes"] += 1
    return {"ok": state["argv"] is not None and state["probes"] > 2, "models": [], "error": "refused"}


def fake_popen(argv, **kw):
    state["argv"], state["env"] = argv, kw.get("env", {})
    return types.SimpleNamespace(pid=1)


localai.probe = fake_probe
localai.installed = lambda sid: r"C:\\fake\\ollama.exe" if sid == "ollama" else ""
localai.subprocess.Popen = fake_popen
try:
    r = localai.start_server("ollama", "http://127.0.0.1:11434/v1", wait=10)
    check("it starts and waits until it answers", r["ok"] and not r.get("already"), str(r))
    check("with ollama serve", state["argv"][1:] == ["serve"], str(state["argv"]))
    check("listening where the app looks for it", state["env"].get("OLLAMA_HOST") == "127.0.0.1:11434")
    check("and is not marked as starting any more", not localai.starting())

    state.update(probes=0, argv=None)
    r = localai.start_server("lmstudio", "http://127.0.0.1:1234/v1", wait=2)
    check("one that is not installed says so", not r["ok"] and r.get("not_installed"), str(r))
    state.update(probes=0, argv=None)
    r = localai.start_server("vllm", "http://127.0.0.1:8000/v1", wait=2)
    check("one that needs a model to start is left to you", not r["ok"] and "yourself" in r["reason"], str(r))

    cfg_on = {"bot": {"local": {"enabled": True, "model": "qwen", "base_url": "http://127.0.0.1:11434/v1"}}}
    state.update(probes=0, argv=None)
    r = localai.autostart(cfg_on)
    check("at launch it starts the server replies run on", r and r["ok"] and state["argv"] is not None, str(r))
    state.update(probes=0, argv=None)
    off = {"bot": {"local": {**cfg_on["bot"]["local"], "autostart": False}}}
    check("unless that is switched off", localai.autostart(off) is None and state["argv"] is None)
    state.update(probes=0, argv=None)
    unused = {"bot": {"groq_models": ["x"], "local": {"enabled": False, "model": ""}}}
    check("and not when nothing runs on it", localai.autostart(unused) is None and state["argv"] is None)
finally:
    localai.probe, localai.installed, localai.subprocess.Popen = real_probe, real_installed, real_popen

print("\n== what the panel shows ==")
check("every provider is Free, Some free or Paid",
      all(providers.COST.get(p["id"], ("",))[0] in ("free", "some", "paid") for p in providers.PROVIDERS))
check("Groq, Gemini and this computer are free",
      all(providers.COST[p][0] == "free" for p in ("groq", "gemini", "local")))
check("OpenAI and Anthropic are paid", providers.COST["openai"][0] == providers.COST["anthropic"][0] == "paid")
health = (ROOT / "app" / "web" / "routes" / "health_routes.py").read_text(encoding="utf-8")
check("the not-running notice carries a Start button", '"call": "local_start"' in health)
check("and says nothing while the app is starting it", "localai.starting()" in health)
issues = (ROOT / "webui" / "src" / "lib" / "components" / "IssueList.svelte").read_text(encoding="utf-8")
check("the notice card runs it", "local_start: () => api.localStart()" in issues)
server = (ROOT / "app" / "web" / "server.py").read_text(encoding="utf-8")
check("the app starts it at launch", "localai.autostart" in server)
check("but only the real server does, never a test or sandbox building the app",
      server.index("localai.autostart") > server.index("def run_server"))

print("\n== the picture behind an [attachment] row ==")
body = {"users": [{"id": "5", "count": 2, "text": "[attachment]"}]}
out = apply_event(body, {"t": "payload", "uid": "5", "text": "", "mid": "9",
                         "attachments": [{"url": "https://cdn/x.png", "name": "x.png", "type": "image/png"}]})
check("the fetched message fills the row in", out["users"][0]["attachments"][0]["name"] == "x.png")
check("without counting it as a new message", out["users"][0]["count"] == 2)
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("the runner fetches it off the command loop", "asyncio.create_task(_message_job(cmd_id, payload))" in runner)
mb = (ROOT / "webui" / "src" / "lib" / "components" / "MessageBody.svelte").read_text(encoding="utf-8")
check("the chip is a button that opens the picture", "onclick={reveal}" in mb and "openWhenLoaded" in mb)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
