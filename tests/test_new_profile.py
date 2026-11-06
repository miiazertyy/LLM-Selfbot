"""Making a profile, in place, in many more colours, and the things found fixing the look round it: the theme change that
turned the window black, and the Memory summary whose whole list jumped when it finished typing."""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name
(Path(_tmp.name) / "config").mkdir(parents=True, exist_ok=True)
(Path(_tmp.name) / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")

from app.utils import db, memory, personas  # noqa: E402

db.init_db()
memory.init_memory()
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def read(rel):
    return (ROOT / "webui" / "src" / rel).read_text(encoding="utf-8")


HEX = re.compile(r"^#[0-9a-f]{6}$")

print("\n== colours and themes ==")
check("plenty of colours, all different, in two even rows", len(personas.PALETTE) >= 24 and len(personas.PALETTE) % 2 == 0
      and len({c["hex"] for c in personas.PALETTE}) == len(personas.PALETTE), str(len(personas.PALETTE)))
check("each a colour, with a name and an id", all(HEX.match(c["hex"]) and c["name"] and c["id"] for c in personas.PALETTE))
check("the first ones as they were: the next colour for a new one is what it was", [c["id"] for c in personas.PALETTE[:3]] == ["violet", "pink", "rose"])
check("themes of two colours", len(personas.THEMES) >= 10 and all(HEX.match(t["a"]) and HEX.match(t["b"]) and t["a"] != t["b"] and t["name"] for t in personas.THEMES))
check("each named once", len({t["id"] for t in personas.THEMES}) == len(personas.THEMES) == len({t["name"] for t in personas.THEMES}))

print("\n== a profile with a theme ==")
made = personas.create("Sunny", "#fb923c", color2="#ec4899")
check("made with both", made["color"] == "#fb923c" and made["color2"] == "#ec4899", str(made))
check("kept", personas.get(made["id"])["color2"] == "#ec4899")
plain = personas.create("Plain", "#34d399")
check("one colour has no second", plain["color2"] == "")
check("anything that is not a colour is not kept", personas.create("Odd", "#34d399", color2="red;")["color2"] == "")
personas.update(made["id"], color="#60a5fa", color2="#c084fc")
check("changed together", personas.get(made["id"])["color"] == "#60a5fa" and personas.get(made["id"])["color2"] == "#c084fc")
personas.update(made["id"], color="#fbbf24")
check("a plain colour leaves no second behind from the theme it had", personas.get(made["id"])["color2"] == "")
personas.update(plain["id"], name="Still plain")
check("a rename touches neither", personas.get(plain["id"])["color"] == "#34d399" and personas.get(plain["id"])["name"] == "Still plain")

print("\n== through the routes ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import persona_routes  # noqa: E402

app = FastAPI()
app.include_router(persona_routes.router)
client = TestClient(app)
H = {"x-llmselfbot": "1"}
listed = client.get("/api/personas", headers=H).json()
check("the page gets the colours and the themes", len(listed["palette"]) == len(personas.PALETTE) and listed["themes"] == personas.THEMES)
check("and each one's second colour", any(p["name"] == "Sunny" and "color2" in p for p in listed["personas"]))
r = client.post("/api/personas", headers=H, json={"name": "Dusk", "color": "#818cf8", "color2": "#f472b6"}).json()
check("made with a theme", r["persona"]["color2"] == "#f472b6", str(r)[:200])
r = client.patch(f"/api/personas/{r['persona']['id']}", headers=H, json={"color": "#22d3ee", "color2": "#3b82f6"}).json()
check("changed to another", r["persona"]["color"] == "#22d3ee" and r["persona"]["color2"] == "#3b82f6")

print("\n== the card ==")
card = read("lib/personas/NewPersona.svelte")
page = read("pages/Profiles.svelte")
check("not a window: no dialog, nothing dimmed", "Modal" not in card and "<NewPersona " in page and "{#if newOpen}" in page)
check("where the tile was, across the row", "grid-column: 1 / -1;" in card and "{:else}\n      <button type=\"button\" class=\"pr-new\"" in page.replace("\r\n", "\n"))
check("it grows out of the tile, and goes back into it", 'newFrom = document.querySelector<HTMLElement>(".pr-new")?.getBoundingClientRect()' in page
      and "root?.animate([frame, { clipPath: WHOLE" in card and "{ ...frame, opacity: 0 }" in card)
check("nothing moves with Animations off", 'get(motionEnabled)' in card and ':root[data-motion="off"]' in card)
check("Escape puts it away", 'e.key === "Escape"' in card and "shut()" in card)
check("the name box ready to type in, without jumping the page", "field?.focus({ preventScroll: true })" in card)
check("it comes into view", "scrollIntoView" in card)
check("Duplicate pressed while it is open changes what it copies", "if (copyOf) {" in card)
check("what it will look like, as you type and pick", "<PersonaOrb p={preview}" in card and "np-show-name" in card)
check("the whole card takes its colour", "--color-accent: {color}" in card)
check("colours ease from one to the next", "@property --np-a" in card and "transition: --np-a" in card)
check("a theme or a colour, not both", "second = t.b;" in card and 'second = "";' in card)
check("a picture to go with it, picked or dropped", 'accept="image/*"' in card and "ondrop={dropped}" in card and "face," in card)
check("and it goes on the profile once there is one", "api.uploadPersonaAvatar(r.persona.id, face)" in page)
check("from your own chats too, in the same card", 'id: "chats"' in card and "<FromExports bind:name" in card and "oncreated={madeFromChats}" in page and "<FromChats" not in page)
check("said plainly whose messages that is", "never from the people you talk to" in read("lib/personas/FromExports.svelte"))
check("every control heard", 'play("glint", { strong: true })' in card and 'play("drop")' in card and 'play("lift")' in card)
dots = read("lib/personas/ColorDots.svelte")
check("the colours in the rainbow's order, in even rows", "byHue(palette)" in dots and "Math.ceil(palette.length / 2)" in card)
check("its menu can change to a theme later", 'themes={data.themes}' in page and "recolor(p, hex, second)" in page and "api.updatePersona(p.id, { color: hex, color2: second })" in page)
orb = read("lib/personas/PersonaOrb.svelte")
check("its face and its ring run between the two", "--po-c2: {far}" in orb and "var(--po-rim)" in orb)
check("one colour looks as it did", "p?.color2 || `color-mix(in srgb, ${color} 30%, transparent)`" in orb and 'p?.color2 || "transparent"' in orb)
check("its card too", "--pc2: {p.color2 || colorOf(p)}" in page and "var(--pc2) var(--pc2-share)" in page)

print("\n== changing theme: the window stays there ==")
sweep = read("lib/themesweep.ts")
css = read("app.css")
blob = css.split(".theme-sweep-blob {")[1].split("}")[0]
check("what pours keeps what is under it: light stays light, dark stays dark", ".theme-sweep.is-wash { mix-blend-mode: color; }" in css)
check("not the new background over everything, which is close to black in every theme", '"--color-bg"' not in sweep.split("function reveal")[1].split("function stars")[0])
check("its colour greyed down: a theme's panels are only faintly tinted", "color-mix(in srgb, ${accent} 30%, #808080)" in sweep)
check("nothing covers the page", "opacity" not in blob)
check("the blend sits straight on the page, or it would reach nothing", "document.body.append(wash, layer)" in sweep and 'wash.className = "theme-sweep is-wash"' in sweep)
check("and the stars beside it, not tinted away", 'layer.className = "theme-sweep";' in sweep and "stars(layer, x, y, R)" in sweep)
check("nothing left behind", "wash.remove();" in sweep and "layer.remove();" in sweep)
check("what fades is the blend", "wash.animate([{ opacity: 1 }, { opacity: 0 }]" in sweep)

print("\n== Memory: the summary stays where it is ==")
tw = read("lib/typewrite.ts")
caret = css.split(".tw-caret {")[0].rsplit("\n", 1)[0] + css.split(".tw-caret::after {")[1].split("}")[0]
check("only words are typed: a space between a list's rows made a row of its own, and every line a letter wide", r"/\S/.test(n.textContent" in tw)
check("the caret is no box in the line: a line can break either side of one", ".tw-caret { position: relative; }" in css and "display: inline-block" not in css.split(".tw-caret { position: relative; }")[1].split("}")[1])
summary = read("lib/components/PersonSummary.svelte")
check("what is under it moves once, when the words come", "style:min-height={loading && !data?.summary && held" in summary and "$effect.pre(" in summary)
memory = read("pages/Memory.svelte")
check("never the last person's facts under this one's name", "detail = details.get(key) ?? null;" in memory and "if (uid !== selected) {" in memory)
check("an answer for someone else does not land", "if (asked !== pid || uid !== selected) return;" in memory)
check("their place held while they come", "mm-facts-wait" in memory)
check("forgetting someone says whose memory, not their name", "await api.memoryDelete(selected, {}, who);" in memory and "const name = current.display_name" in memory)

print("\n== the little things ==")
trimmed = []
for path in (ROOT / "webui" / "src").rglob("*.svelte"):
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"\{#if [^{}]*\} · |\{:else(?: if [^{}]*)?\} · | · \{/if\}| · \{:else", line):
            trimmed.append(f"{path.name}:{i}")
check("Svelte drops a space at the edge of a block: no separator written so runs into the word before it", not trimmed, ", ".join(trimmed))

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
