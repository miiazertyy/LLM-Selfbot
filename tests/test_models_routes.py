"""The Models tab's routes, against a sandbox DATA_DIR.

Saving the plan writes bot.models and mirrors it into the old keys, so the
health checks, the Telegram status and anything else still reading groq_models
or bot.local agree with what the tab shows. Keys go to .env and are never sent
back. A job cannot be put on a provider that cannot do it.
"""
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SANDBOX = Path(tempfile.mkdtemp(prefix="llmbot_models_"))
for d in ("config", "ipc", "logs", "backups"):
    (SANDBOX / d).mkdir(parents=True, exist_ok=True)
shutil.copy(REPO / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
(SANDBOX / "config" / ".env").write_text("GROQ_API_KEY_1=gsk_fake_one\n", encoding="utf-8")
sys.path.insert(0, str(REPO))

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
import app.utils.helpers as helpers
helpers.resource_path = lambda rel: str(
    (SANDBOX if (rel.replace("\\", "/").split("/")[0] in ("config", "ipc")) else paths.APP_DIR) / rel)
import app.web.envfile as envfile
envfile.ENV_PATH = SANDBOX / "config" / ".env"
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"
import app.web.routes.config_routes as config_routes
config_routes.CONFIG_PATH = SANDBOX / "config" / "config.yaml"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.web.routes import models_routes
from app.utils import providers

app = FastAPI()
app.include_router(models_routes.router)
client = TestClient(app)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== what the tab reads ==")
d = client.get("/api/providers").json()
ids = [p["id"] for p in d["providers"]]
check("every provider is listed", {"groq", "openai", "anthropic", "gemini", "openrouter", "local"} <= set(ids))
groq = next(p for p in d["providers"] if p["id"] == "groq")
check("Groq is connected, with its key counted", groq["ready"] and groq["keys"] == 1)
check("OpenAI is not", not next(p for p in d["providers"] if p["id"] == "openai")["ready"])
check("no key ever comes back", "gsk_fake_one" not in str(d))
check("an untouched config plans replies on Groq", all(e["provider"] == "groq" for e in d["plan"]["replies"]))

print("\n== keys ==")
r = client.post("/api/providers/openai/key", json={"key": "sk-test-123"})
check("a key is saved", r.status_code == 200 and "OPENAI_API_KEY=sk-test-123" in envfile.ENV_PATH.read_text())
check("and the provider is connected", providers.usable("openai", {}))
client.post("/api/providers/groq/key", json={"key": "gsk_fake_two"})
check("a second Groq key goes in the next slot", "GROQ_API_KEY_2=gsk_fake_two" in envfile.ENV_PATH.read_text())
check("a key with spaces is refused", client.post("/api/providers/openai/key", json={"key": "a b"}).status_code == 400)

print("\n== saving the plan ==")
r = client.post("/api/models/plan", json={
    "replies": [{"provider": "local", "model": "llama3.1:8b"},
                {"provider": "groq", "model": "openai/gpt-oss-120b"},
                {"provider": "openai", "model": "gpt-4o-mini"},
                {"provider": "groq", "model": "openai/gpt-oss-120b"}],
    "vision": {"provider": "openai", "model": "gpt-4o"},
    "stt": {"provider": "local", "model": "whisper-1"},
    "tts": {"provider": "groq", "model": "canopylabs/orpheus-v1-english", "voice": "autumn"},
    "small": {"provider": "", "model": ""},
})
check("it saves", r.status_code == 200, r.text[:200])
cfg = helpers.load_config()
bot = cfg["bot"]
check("the chain is kept in order, without the duplicate",
      [e["provider"] for e in bot["models"]["replies"]] == ["local", "groq", "openai"])
check("Groq's models are mirrored into groq_models", bot["groq_models"] == ["openai/gpt-oss-120b"])
check("local replies switch the old local flag on", bot["local"]["enabled"] is True
      and bot["local"]["model"] == "llama3.1:8b")
check("a local job is mirrored into bot.local", bot["local"]["stt_model"] == "whisper-1")
check("a job moved off local clears its old key", bot["local"].get("vision_model") == "")
check("a Groq job writes the old Groq key", bot["groq_tts_model"] == "canopylabs/orpheus-v1-english")
check("and its voice", bot["tts"]["voice"] == "autumn")
check("an unset job is left off the plan", "small" not in bot["models"])
plan = providers.plan(cfg)
check("and reads back as planned", plan["vision"] == {"provider": "openai", "model": "gpt-4o"}
      and plan["stt"]["provider"] == "local")

print("\n== what cannot be saved ==")
r = client.post("/api/models/plan", json={"replies": [{"provider": "", "model": ""}]})
check("a list with nothing usable in it is refused", r.status_code == 400)
# None at all is allowed now: the only reply model could not be taken off before, even one removed from the computer.
r = client.post("/api/models/plan", json={"replies": []})
check("none at all is none picked: Groq's models write replies", r.status_code == 200
      and all(e["provider"] == "groq" for e in r.json()["plan"]["replies"]), r.text[:160])
r = client.post("/api/models/plan", json={"replies": [{"provider": "groq", "model": "x"}],
                                          "stt": {"provider": "deepseek", "model": "whatever"}})
check("a job on a provider that cannot do it is refused", r.status_code == 400, r.text[:120])
r = client.post("/api/models/plan", json={"replies": [{"provider": "nope", "model": "x"}]})
check("an unknown provider is refused", r.status_code == 400)

print("\n== the Settings rows it replaces are hidden ==")
from app.web import descriptions
check("the chain is not also a JSON box", descriptions.is_hidden("bot.models.replies"))
check("nor are the old model rows", descriptions.is_hidden("bot.groq_models"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
