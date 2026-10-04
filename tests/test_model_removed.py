"""A local model removed from the computer, and the settings that named it.

Seen on a real setup: the only model writing replies was removed on This computer, and it stayed. Every reply
tried it and failed, a warning said it was not on the server, Models still showed it ("won't load"), its x was
greyed out (the last reply model could not be taken off), and Change offered the removed model and not the one
downloaded since: the list of the computer's models was kept an hour.

Checked here, on a config of its own: a removed model is taken out of every setting that names it, a job left with
nothing goes back to its default (replies to Groq's models, said so), what was said about it not loading is
forgotten, a model not in use leaves the config alone; the computer's list is asked again soon and at once after a
download or a removal; the last reply model can be taken off, in the panel and by the server; and the Download
button says it is looking the model up during the wait before a download starts.
"""
import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="llm-removed-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
GONE = "hf.co/HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF:latest"
OTHER = "hf.co/x/other:latest"
BASE = yaml.safe_load((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"))
CONFIG = TMP / "config" / "config.yaml"
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def src(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def write(models, local):
    cfg = yaml.safe_load(yaml.safe_dump(BASE))
    cfg["bot"]["models"] = models
    cfg["bot"]["local"] = {**(cfg["bot"].get("local") or {}), **local}
    CONFIG.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def saved():
    from app.utils.helpers import invalidate_config_cache
    invalidate_config_cache()
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["bot"]


from app.utils import localfix as lf, providers  # noqa: E402
from app.utils.helpers import invalidate_config_cache, load_config  # noqa: E402

print("== the only reply model, removed ==")
write({"replies": [{"provider": "local", "model": GONE}], "vision": {"provider": "local", "model": GONE},
       "small": {"provider": "groq", "model": "openai/gpt-oss-20b"}},
      {"enabled": True, "model": GONE, "vision_model": GONE})
invalidate_config_cache()
with lf._state_lock:
    lf._state.update(model=GONE, state="stuck", why="the file is a draft model", to="", alt=None)
jobs = lf.drop(GONE)
bot = saved()
check("said which jobs used it", set(jobs) >= {"replies", "vision"}, str(jobs))
check("taken out of the replies: none left, so none picked", "replies" not in (bot.get("models") or {}))
check("taken out of reading pictures: back to its default", "vision" not in (bot.get("models") or {}))
check("a job that did not use it is left as it was", (bot["models"].get("small") or {}).get("model") == "openai/gpt-oss-20b")
check("the computer's own settings no longer name it", bot["local"].get("model") == "" and bot["local"].get("vision_model") == "")
check("and replies are no longer on this computer", bot["local"].get("enabled") is False)
invalidate_config_cache()
chain = providers.reply_chain(load_config())
check("replies go to Groq's models, as before anything was picked", chain and all(e["provider"] == "groq" for e in chain),
      str(chain))
check("what was said about it not loading is forgotten", lf.status().get("model") == "" and lf.status().get("state") == "")

print("\n== the note a failed reply left about it ==")
write({"replies": [{"provider": "local", "model": GONE}]}, {"enabled": True, "model": GONE})
invalidate_config_cache()
marker = lf._marker()
marker.parent.mkdir(parents=True, exist_ok=True)
marker.write_text('{"model": "%s", "base_url": "http://127.0.0.1:1/v1", "error": "x"}' % GONE, encoding="utf-8")
lf.drop(GONE)
check("removed with it: read again later, it put 'will not load' back on This computer", not marker.exists())
lfs = src("app/utils/localfix.py")
check("a note from before the start is not read again: what is in use is looked at then anyway",
      "seen = path.stat().st_mtime" in lfs)
check("nor one about a model no setting uses any more", "if model not in configured(load_config()):" in lfs)

print("\n== one of two ==")
write({"replies": [{"provider": "local", "model": GONE}, {"provider": "local", "model": OTHER}]},
      {"enabled": True, "model": GONE})
invalidate_config_cache()
jobs = lf.drop(GONE)
bot = saved()
check("the other one writes replies now", bot["models"]["replies"] == [{"provider": "local", "model": OTHER}],
      str(bot["models"].get("replies")))
check("and replies stay on this computer", bot["local"].get("enabled") is True)

print("\n== one nothing uses ==")
before = CONFIG.read_text(encoding="utf-8")
check("nothing to say", lf.drop("hf.co/never/used:latest") == [])
check("and the config is not written", CONFIG.read_text(encoding="utf-8") == before)

print("\n== removing one through the panel ==")
routes = src("app/web/routes/local_routes.py")
check("the removal takes it out of the settings, and says which", '"unused": await asyncio.to_thread(localfix.drop, name)' in routes)
la = src("webui/src/lib/components/LocalAI.svelte")
check("the panel says what that means for replies", "Replies used it, so they're on Groq again until you pick another." in la
      and "if (unused.length) loadProviders()" in la)
check("and asks the computer's list again", 'loadModels("local", true)' in la)

print("\n== the computer's list, current ==")
pv = src("app/utils/providers.py")
check("asked again within seconds, not an hour", "_LOCAL_TTL = 15.0" in pv and 'ttl = _LOCAL_TTL if pid == "local"' in pv)
la_py = src("app/utils/localai.py")


def body(name):
    """A function's source in localai.py, up to the next top-level definition."""
    start = la_py.index(f"\ndef {name}(")
    end = la_py.find("\ndef ", start + 1)
    return la_py[start:end if end > 0 else None]


check("and at once after a removal or a download, Ollama's or a llama.cpp file", "def forget(pid: str)" in pv
      and all("_models_changed()" in body(f) for f in ("_finish", "delete_model", "delete_file_model"))
      and all("_finish(" in body(f) for f in ("_run_ollama", "_run_file")))
providers._cache["local"] = {"at": 0, "models": [{"id": GONE, "capabilities": ["chat"]}], "error": ""}
providers.forget("local")
check("forgetting drops it", "local" not in providers._cache)
check("the panel's own copy is kept seconds too", 'const fresh = pid === "local" ? 15_000 : 10 * 60 * 1000;'
      in src("webui/src/lib/providers.ts"))

print("\n== the last reply model can be taken off ==")
mr = src("app/web/routes/models_routes.py")
check("the server takes none at all as none picked", "if replies and not chain:" in mr and 'models.pop("replies", None)' in mr)
mp = src("webui/src/lib/components/ModelsPanel.svelte")
check("its x is never greyed out", "disabled={chain.length <= 1}" not in mp and "if (chain.length <= 1) return;" not in mp)
check("and the panel says what happens with none", "None picked. Groq's models write replies until you add one." in mp)

print("\n== a model removed some other way: the warning says where, and stops it being used ==")
hr = src("app/web/routes/health_routes.py")
check("the warning says which jobs use it", '"vision": "reading pictures"' in hr and "{'uses' if len(uses) <= 1 else 'use'}" in hr)
check("and has a button that stops them using it", '"call": "local_forget"' in hr and '"Stop using it" if one else "Stop using them"' in hr)
check("which takes it out of every setting, only when the computer really has not got it",
      '@router.post("/api/local/forget")' in routes and "gone = [m for m in names if m not in probe[\"models\"]]" in routes
      and "jobs += await asyncio.to_thread(localfix.drop, m)" in routes)
il = src("webui/src/lib/components/IssueList.svelte")
check("the panel runs it and says what that means", "local_forget: (i) => api.localForget(i.fix?.models ?? [])," in il
      and '"Not used any more."' in il)

print("\n== a voice model is not offered for writing replies ==")
check("a speaking model, even one Ollama calls a text model, is offered for speaking only",
      providers.capabilities("local", "hf.co/Serveurperso/OmniVoice-GGUF:latest omnivoice-lm") == ["tts"])
check("one that hears is offered for hearing, though 'voice' is in its name",
      providers.capabilities("local", "sensevoice-small") == ["stt"]
      and providers.capabilities("local", "nvidia/parakeet-tdt") == ["stt"])
check("a chat model is still a chat model, one that sees still sees",
      providers.capabilities("local", "llama3.1:8b llama") == ["chat"]
      and providers.capabilities("local", "hf.co/x/Qwen3.6-35B:latest qwen35moe") == ["chat", "vision"])
check("the computer's own word for a model (its family) is read with its name",
      "capabilities(pid, f\"{m} {(family.get(m) or {}).get('family') or ''}\")" in pv)

print("\n== Try, when a model is too big for the computer ==")
import json as _json  # noqa: E402
said = providers.http_error("local", 500, _json.dumps({"error": {"message":
                            "model requires more system memory (24.1 GiB) than is available (5.3 GiB)"}}))[0]
check("said in words with the numbers, not 'answered 500'",
      said.startswith("Not enough memory: it needs 24.1 GB, and this computer has 5.3 GB free."), said)
check("graphics memory too", providers.http_error("local", 500, _json.dumps({"error": {"message":
      "model requires more gpu memory (6.0 GiB) than is available (3.9 GiB)"}}))[0].startswith("Not enough graphics memory"))
check("a runner that died while loading is said to be memory, most likely",
      "usually not enough memory" in providers.http_error("local", 500, _json.dumps({"error": "llama runner process has terminated: exit status 0xc0000409"}))[0])
check("anything else still says who answered what", providers.http_error("local", 500, '{"error": "odd"}')[0] == "This computer answered 500.")
check("the panel shows why under the model, in full, rather than cut to the row", 'class="mp-why"' in mp
      and "· did not answer" in mp)

print("\n== the wait before a download ==")
check("the button says it is looking the model up, with a spinner", "Looking it up" in la and 'class="lc-get-spin"' in la
      and "let asking = $state(false);" in la)
check("and the field shows a light running along it", ".lc-get.is-asking::after" in la and "@keyframes lc-ask-run" in la)
check("pressed twice, it starts once", "if (!name || asking) return;" in la)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
