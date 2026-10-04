"""The panel's side of persona profiles: the routes the Personas page, Settings, Pictures and Memory use.

On a sandbox, with a supervisor that only remembers what it was asked and no account really running: making and
changing personas, giving one to an account (a running one starts again), its text, face and settings, Settings and
Pictures and Memory each scoped to one persona, and the quick backup carrying them.
"""
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fixtures import use_shipped_config  # noqa: E402

SANDBOX = use_shipped_config()
from app.utils import db, helpers, memory, personas  # noqa: E402

db.resource_path = helpers.resource_path
from app.core import ipc  # noqa: E402

ipc.discover_targets = lambda: {
    "discord_1": {"platform": "discord", "account": 1, "target": 1},
    "discord_2": {"platform": "discord", "account": 2, "target": 2},
    "snapchat_1": {"platform": "snapchat", "account": 1, "target": "snap"},
}
sent = []


async def fake_send_and_wait(target, cmd, payload=None, timeout=10.0):
    sent.append((target, cmd, payload))
    return {"ok": True}

ipc.send_and_wait = fake_send_and_wait

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import (chat_routes, config_routes, media_routes, persona_routes,  # noqa: E402
                            status_routes, system_routes)

config_routes.CONFIG_PATH = SANDBOX / "config" / "config.yaml"
media_routes.PICTURES_DIR = SANDBOX / "config" / "pictures"
system_routes.DATA_DIR = SANDBOX


class Sup:
    port = 8787

    def __init__(self):
        self.restarted = []

    def running_ids(self):
        return {"discord_1", "snapchat_1"}

    def restart(self, child_id):
        self.restarted.append(child_id)

    def status(self):
        return [{"id": "discord_1", "state": "running"}, {"id": "snapchat_1", "state": "running"}]

    def planned(self):
        return {"discord_1", "discord_2", "snapchat_1"}


app = FastAPI()
app.state.supervisor = sup = Sup()
for r in (persona_routes, config_routes, media_routes, chat_routes, status_routes, system_routes):
    app.include_router(r.router)
c = TestClient(app)
db.init_db()
personas.startup()
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== the list ==")
r = c.get("/api/personas").json()
check("Default, with every account, and the colours to pick from", [p["id"] for p in r["personas"]] == ["default"]
      and r["personas"][0]["accounts"] == ["discord_1", "discord_2", "snapchat_1"] and len(r["palette"]) == 10, str(r)[:300])

print("\n== making one ==")
r = c.post("/api/personas", json={"name": "Juniper"}).json()
j = r["persona"]
check("made, named, coloured, answering to its name", r["ok"] and j["id"] == "juniper" and j["color"]
      and j["changed"] == 1 and j["accounts"] == [], str(j))
check("a copy of one that is not there is refused", c.post("/api/personas", json={"name": "X", "copy_from": "nope"}).status_code == 404)
r = c.patch("/api/personas/juniper", json={"name": "Juniper Moon", "color": "#22d3ee"}).json()
check("renamed and recoloured", r["persona"]["name"] == "Juniper Moon" and r["persona"]["color"] == "#22d3ee")

print("\n== given to an account ==")
r = c.post("/api/personas/juniper/assign", json={"account": "discord_1"}).json()
check("a running account is started again with it", r["changed"] and r["restarted"] == ["discord_1"] and sup.restarted == ["discord_1"])
r = c.post("/api/personas/juniper/assign", json={"account": "discord_2"}).json()
check("one not running is only given it", r["changed"] and r["restarted"] == [] and sup.restarted == ["discord_1"])
check("giving it again changes nothing", not c.post("/api/personas/juniper/assign", json={"account": "discord_2"}).json()["changed"])
check("only accounts", c.post("/api/personas/juniper/assign", json={"account": "../x"}).status_code == 400)
lst = c.get("/api/personas").json()
check("the list says who is whose", lst["accounts"] == {"discord_1": "juniper", "discord_2": "juniper", "snapchat_1": "default"}
      and next(p for p in lst["personas"] if p["id"] == "default")["accounts"] == ["snapchat_1"])
acc = c.get("/api/accounts").json()["accounts"]
check("each account row says its persona", {a["id"]: a.get("persona") for a in acc} ==
      {"discord_1": "juniper", "discord_2": "juniper", "snapchat_1": "default"}, str(acc)[:200])

print("\n== its text ==")
sent.clear()
r = c.post("/api/personas/juniper/text", json={"text": "Your name is Juniper. You love the sea."}).json()
check("saved, and its running Discord accounts told", r["ok"] and r["told"] == ["discord_1"])
check("read back", c.get("/api/personas/juniper/text").json()["text"].endswith("love the sea."))
check("Default's text is its own", "love the sea" not in c.get("/api/instructions").json()["text"])
lst = c.get("/api/personas").json()
check("its line is from its text", next(p for p in lst["personas"] if p["id"] == "juniper")["line"]
      == "Your name is Juniper. You love the sea.")

print("\n== its settings ==")
sent.clear()
r = c.post("/api/config/field", json={"key": "bot.default_language", "value": "fr", "persona": "juniper"}).json()
check("a setting saved as its own", r["scope"] == "persona" and personas.overrides("juniper").get("bot.default_language") == "fr")
check("everyone's left as it was", helpers.load_base_config()["bot"]["default_language"] == "en")
check("and its accounts told to read again", any(cmd == "config_update" for _, cmd, _ in sent))
sch = c.get("/api/config/schema?persona=juniper").json()
f = next(x for x in sch["fields"] if x["key"] == "bot.default_language")
check("Settings sees its value, everyone's beside it, and that it is its own",
      f["current"] == "fr" and f["base"] == "en" and f["overridden"] is True and sch["persona"]["name"] == "Juniper Moon", str(f))
g = next(x for x in sch["fields"] if x["key"].startswith("services."))
check("what is the app's says so", g["global_only"] is True)
check("everyone's schema has no persona", c.get("/api/config/schema").json()["persona"] is None)
check("its effective settings", c.get("/api/config?persona=juniper").json()["bot"]["default_language"] == "fr")
d = c.get("/api/personas/juniper").json()
check("what it changes, named, with everyone's beside", any(s["key"] == "bot.default_language" and s["value"] == "fr"
                                                            and s["base"] == "en" for s in d["settings"]), str(d["settings"]))
r = c.delete("/api/personas/juniper/settings/bot.default_language").json()
check("back to everyone's", r["reset"] and "bot.default_language" not in personas.overrides("juniper"))
check("an unknown persona is refused", c.get("/api/config/schema?persona=nope").status_code == 404)

print("\n== its pictures ==")
from PIL import Image  # noqa: E402


def png(color):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "PNG")
    return buf.getvalue()


async def no_describe(name, data, ext, client_index=None):
    return "", "not now"

media_routes._describe = no_describe
c.post("/api/pictures", files={"file": ("a.png", png("red"), "image/png")})
c.post("/api/pictures?persona=juniper", files={"file": ("b.png", png("blue"), "image/png")})
c.post("/api/pictures?persona=juniper", files={"file": ("c.png", png("green"), "image/png")})
mine = c.get("/api/pictures?persona=juniper").json()["pictures"]
dflt = c.get("/api/pictures").json()["pictures"]
check("each persona has its own IMG_1", [p["name"] for p in dflt] == ["IMG_1.png"]
      and [p["name"] for p in mine] == ["IMG_1.png", "IMG_2.png"])
db.add_picture_description("IMG_2.png", "a blue square", persona="juniper")
r = c.post("/api/pictures/delete?persona=juniper", json={"items": [{"id": mine[0]["id"]}]}).json()
mine2 = c.get("/api/pictures?persona=juniper").json()["pictures"]
check("deleting renumbers only its own", r["deleted"] == 1 and [p["name"] for p in mine2] == ["IMG_1.png"]
      and mine2[0]["description"] == "a blue square" and [p["name"] for p in c.get("/api/pictures").json()["pictures"]] == ["IMG_1.png"])
check("a picture is found by its id whoever's it is", c.get(f"/api/pictures/id/{mine2[0]['id']}").status_code == 200)
r = c.post("/api/personas/juniper/avatar", json={"picture": "IMG_1.png"}).json()
check("its face, from one of its pictures", r["ok"] and personas.has_avatar("juniper")
      and c.get(r["avatar"]).headers["content-type"] == "image/jpeg")
check("not from another's", c.post("/api/personas/juniper/avatar", json={"picture": "IMG_9.png"}).status_code == 404)

print("\n== its memory ==")
memory.set_memory(42, "name", "Mara", persona="juniper")
memory.set_memory(42, "name", "M.", persona="default")
check("each persona's people", [u["facts"] for u in c.get("/api/memory?persona=juniper").json()["users"]] == [{"name": "Mara"}]
      and [u["facts"] for u in c.get("/api/memory").json()["users"]] == [{"name": "M."}])
sent.clear()
c.put("/api/memory/42?persona=juniper", json={"key": "city", "value": "Porto"})
check("written to its own, and the accounts speaking as it told", memory.get_memory(42, persona="juniper") == {"name": "Mara", "city": "Porto"}
      and memory.get_memory(42) == {"name": "M."} and any(cmd == "memory_changed" for _, cmd, _ in sent))
c.put("/api/memory/42?persona=juniper", json={"persona": "be playful"})
check("a person's own tone, its own too", memory.get_persona(42, persona="juniper") == "be playful" and memory.get_persona(42) is None)

print("\n== the backup ==")
r = c.get("/api/system/backup")
names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
check("carries every persona: who is whose, and each one's text, settings, face and pictures",
      "config/personas.json" in names and "config/personas/juniper/instructions.txt" in names
      and "config/personas/juniper/avatar.jpg" in names and "config/personas/juniper/pictures/IMG_1.png" in names,
      str([n for n in names if "persona" in n]))

print("\n== deleting one ==")
sup.restarted.clear()
r = c.delete("/api/personas/juniper").json()
check("its accounts are Default's again, the running one started again",
      sorted(r["moved"]) == ["discord_1", "discord_2"] and r["restarted"] == ["discord_1"])
check("gone, with what it remembered", not personas.exists("juniper") and memory.get_memory(42, persona="juniper") == {}
      and memory.get_memory(42) == {"name": "M."})
check("Default cannot be", c.delete("/api/personas/default").status_code == 400)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
