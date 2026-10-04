"""Settings as a file: Export, Import and the raw editor, beside the search in Settings.

What is worth pinning is what goes wrong quietly:

  * a Discord ID is bigger than the page's numbers can hold, so anything that
    went through the page as parsed JSON came back a different ID. The raw
    editor did exactly that to the owner ID; export, import and the raw editor
    now keep the file as text until the server has it
  * a settings file is made to be shared, so the owner ID and keys stay out of
    an export unless asked for, and an import never changes them, the local
    server's address, or how the panel is reached, unless they are ticked
  * import writes only what was picked, with values from the file, checked
    again on the server; the page only names which settings
  * a setting of the wrong kind, or one this version does not have, is listed
    as not imported rather than written
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="settings_file_"))
for d in ("config", "ipc", "logs", "backups"):
    (SANDBOX / d).mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")
shutil.copy(ROOT / "resources" / "instructions.txt", SANDBOX / "config" / "instructions.txt")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.seed_data_dir = lambda: None
import app.utils.helpers as helpers
helpers.resource_path = lambda rel: str(
    (SANDBOX if rel.replace("\\", "/").split("/")[0] in ("config", "ipc") else paths.APP_DIR) / rel)
import app.core.ipc as ipc
ipc.CONFIG_DIR = SANDBOX / "config"
ipc.IPC_DIR = SANDBOX / "ipc"
import app.web.logbus as logbus
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"

from fastapi.testclient import TestClient
from app.web.server import create_app
from app.web import settings_io

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


client = TestClient(create_app(supervisor=None))
CONFIG = SANDBOX / "config" / "config.yaml"
OWNER = 272402839874174976          # the page's numbers round this one to ...180


def on_disk():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def set_disk(**changes):
    cfg = on_disk()
    for key, value in changes.items():
        settings_io.set_nested(cfg, key.replace("__", "."), value)
    CONFIG.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    helpers.invalidate_config_cache()


set_disk(bot__owner_id=OWNER, notifications__error_webhook="https://discord.com/api/webhooks/1/secret")

print("== the page's numbers really do lose it ==")
check("2^53 is where they stop", OWNER > 2 ** 53)
check("and this ID is past it by a long way", float(OWNER) != OWNER or str(float(OWNER)) != str(OWNER))

print("\n== export ==")
r = client.get("/api/config/export")
check("answers", r.status_code == 200, r.text[:200])
body = r.json()
check("as text, which the page saves without parsing", isinstance(body["text"], str) and body["filename"].endswith(".json"))
check("named for the day", body["filename"].startswith("llmselfbot-settings-"))
data = json.loads(body["text"])
check("with a header saying what it is", data["app"] == "LLMSelfbot" and data["kind"] == "settings" and data["format"] == 1)
check("when, and from which version", data["exported_at"].endswith("Z") and "version" in data)
check("every other setting is in it", data["settings"]["bot"]["prefix"] == on_disk()["bot"]["prefix"])
check("the owner ID is left out", "owner_id" not in data["settings"]["bot"])
check("and the webhook", "error_webhook" not in data["settings"].get("notifications", {}))
check("and the local server's key", "api_key" not in data["settings"]["bot"]["local"])
check("and it says so", data["personal"] is False)
check("the count is of settings, not sections", body["count"] > 60, str(body["count"]))
mine = json.loads(client.get("/api/config/export?personal=true").json()["text"])
check("asked for, they are in", mine["personal"] is True and "owner_id" in mine["settings"]["bot"])
check("and the ID keeps every digit in the file's text",
      f'"owner_id": {OWNER}' in client.get("/api/config/export?personal=true").json()["text"])
check("moods move whole", mine["settings"]["bot"]["mood"]["moods"] == on_disk()["bot"]["mood"]["moods"])

print("\n== reading a file ==")
settings, meta = settings_io.unwrap(data)
check("an exported file is read", settings is data["settings"] and "exported_at" in meta)
check("so is a config.yaml saved as JSON", settings_io.unwrap({"bot": {"prefix": "!"}})[0] == {"bot": {"prefix": "!"}})
for junk in ([], "x", {"hello": 1}, {"settings": []}):
    try:
        settings_io.unwrap(junk)
        ok = False
    except ValueError:
        ok = True
    check(f"{json.dumps(junk)} is refused", ok)
r = client.post("/api/config/import/preview", json={"text": "{not json"})
check("a broken file says so", r.status_code == 400 and "JSON" in r.json()["detail"], r.text[:120])
r = client.post("/api/config/import/preview", json={"text": "[1, 2]"})
check("and so does one from something else", r.status_code == 400 and "settings file" in r.json()["detail"])

print("\n== what an import would change ==")
incoming = json.loads(json.dumps(mine))
b = incoming["settings"]["bot"]
b["prefix"] = "!"
b["allow_gc"] = not b["allow_gc"]
b["max_reply_tokens"] = 512
b["owner_id"] = 111111111111111111111
b["local"]["base_url"] = "http://evil.example/v1"
b["local"]["api_key"] = "theirs"
b["mood"]["moods"]["sulky"] = "Short answers, a bit put out."
b["typo_chance"] = "lots"                       # wrong kind
b["sampling"]["temperature"] = 0.7              # empty here, a number there
b["made_up_setting"] = True                     # not a setting
b["batch_wait_times"] = ["soon", "later"]       # rows expected, strings given
incoming["settings"]["services"]["webui"]["bind"] = "0.0.0.0"
text = json.dumps(incoming)

r = client.post("/api/config/import/preview", json={"text": text})
check("the preview answers", r.status_code == 200, r.text[:200])
p = r.json()
by = {c["key"]: c for c in p["changes"]}
check("a changed setting is listed, old and new", by.get("bot.prefix", {}).get("old") == "/" and by["bot.prefix"]["new"] == "!")
check("on and off too", "bot.allow_gc" in by and "bot.max_reply_tokens" in by)
check("with its name, not its key", by["bot.prefix"]["label"] != "bot.prefix")
check("and where it lives in Settings", bool(by["bot.prefix"]["section"]))
check("a new mood changes the moods as a whole", "bot.mood.moods" in by and "sulky" in by["bot.mood.moods"]["new"])
check("an empty setting can be given a value", by.get("bot.sampling.temperature", {}).get("new") == 0.7)
check("the same ones are counted, not listed", p["same"] > 40 and "bot.allow_dm" not in by, str(p["same"]))
for key in ("bot.owner_id", "bot.local.api_key", "bot.local.base_url", "services.webui.bind"):
    check(f"{key} is held back until ticked", by.get(key, {}).get("guarded") is True)
check("and says why", by["bot.owner_id"]["why"].startswith("Who owns the bot"))
check("a plain one is not held back", by["bot.prefix"]["guarded"] is False)
check("an ID the page cannot hold comes to it as text", by["bot.owner_id"]["old"] == str(OWNER), repr(by["bot.owner_id"]["old"]))
skipped = {s["key"]: s["reason"] for s in p["skipped"]}
check("the wrong kind is not imported, and says why", "should be a number" in skipped.get("bot.typo_chance", ""), str(skipped))
check("a setting this version lacks is listed", "Not a setting" in skipped.get("bot.made_up_setting", ""))
check("strings where rows go are refused", "bot.batch_wait_times" in skipped, str(skipped))
check("the file's header comes through", p["meta"]["personal"] is True and bool(p["meta"]["exported_at"]))

print("\n== importing what was ticked ==")
before = on_disk()
r = client.post("/api/config/import", json={"text": text, "keys": ["bot.prefix", "bot.mood.moods", "bot.typo_chance",
                                                                  "bot.made_up_setting", "not.even.close"]})
check("it imports", r.status_code == 200 and r.json()["applied"] == 2, r.text[:200])
after = on_disk()
check("what was ticked is written", after["bot"]["prefix"] == "!" and "sulky" in after["bot"]["mood"]["moods"])
check("what was not ticked is not", after["bot"]["allow_gc"] == before["bot"]["allow_gc"]
      and after["bot"]["max_reply_tokens"] == before["bot"]["max_reply_tokens"])
check("the owner ID is untouched, every digit", after["bot"]["owner_id"] == OWNER)
check("so are the address and the bind", after["bot"]["local"]["base_url"] == before["bot"]["local"]["base_url"]
      and after["services"]["webui"]["bind"] == "127.0.0.1")
check("a refused setting stays refused even if named", after["bot"]["typo_chance"] == before["bot"]["typo_chance"])
check("and an unknown one is never written", "made_up_setting" not in after["bot"])
check("the old config is kept in backups", any((SANDBOX / "backups").glob("config-*.yaml")))
r = client.post("/api/config/import", json={"text": text, "keys": ["bot.owner_id"]})
check("ticked, a held-back one is written", r.status_code == 200 and on_disk()["bot"]["owner_id"] == 111111111111111111111)
set_disk(bot__owner_id=OWNER)
r = client.post("/api/config/import", json={"text": text, "keys": []})
check("nothing ticked is refused", r.status_code == 400)
r = client.post("/api/config/import", json={"text": text, "keys": ["not.a.setting"]})
check("and so is a list of nothing it offers", r.status_code == 400)

print("\n== the raw editor keeps the ID ==")
raw = client.get("/api/config/raw").json()["text"]
check("sent as text with every digit", f'"owner_id": {OWNER}' in raw)
r = client.post("/api/config/raw", json={"text": raw})
check("saved back", r.status_code == 200 and on_disk()["bot"]["owner_id"] == OWNER, r.text[:120])
r = client.post("/api/config/raw", json={"text": "{\"services\": {}}"})
check("a config without its bot section is still refused", r.status_code == 400)
r = client.post("/api/config/raw", json={"text": "{oops"})
check("and broken JSON says so, not a 500", r.status_code == 400 and "JSON" in r.json()["detail"])

print("\n== the Owner ID row ==")
fields = {f["key"]: f for f in client.get("/api/config/schema").json()["fields"]}
row = fields.get("bot.owner_id", {})
check("it is edited as text", row.get("type") == "str" and row.get("current") == str(OWNER), str(row)[:160])
r = client.post("/api/config/field", json={"key": "bot.owner_id", "value": "272402839874174977"})
check("and saved as the number", r.status_code == 200 and on_disk()["bot"]["owner_id"] == 272402839874174977)
r = client.post("/api/config/field", json={"key": "bot.owner_id", "value": "not an id"})
check("text that is not an ID is refused", r.status_code == 400 and on_disk()["bot"]["owner_id"] == 272402839874174977)

print("\n== the page ==")
ui = ROOT / "webui" / "src"
comp = (ui / "lib" / "components" / "SettingsFile.svelte").read_text(encoding="utf-8")
settings_page = (ui / "pages" / "Settings.svelte").read_text(encoding="utf-8")
api = (ui / "lib" / "api.ts").read_text(encoding="utf-8")
check("Export, Import and Raw file sit together beside the search",
      "<SettingsFile onraw={openRaw}" in settings_page and "Export" in comp and "Import" in comp and "Raw file" in comp)
check("the file is sent as text, never parsed on the page", "file.text()" in comp and "api.importPreview(text)" in comp
      and "JSON.parse" not in comp)
check("the export is saved as the server wrote it", "saveTextFile(r.filename, r.text)" in comp)
_raw_editor = (ROOT / "webui" / "src" / "lib" / "components" / "RawEditor.svelte").read_text(encoding="utf-8")
check("the raw editor is text both ways", "api.configRaw()" in settings_page and "api.saveConfigRaw(text)" in settings_page
      and "JSON.parse(raw)" not in settings_page and "JSON.stringify" not in _raw_editor)
check("held-back settings start unticked", "p.changes.filter((c) => !c.guarded)" in comp)
check("the owner ID and keys are opt-in on export", "Include my owner ID and keys" in comp and "withPersonal" in comp)
check("the API names the routes", "/api/config/export" in api and "/api/config/import/preview" in api)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
