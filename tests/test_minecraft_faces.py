"""The people on Minecraft have a picture drawn from their skin, the way the account's own is. Nothing here reaches Mojang."""
import asyncio
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name

from PIL import Image  # noqa: E402

from app.platforms.minecraft import skins  # noqa: E402
from app.utils import snappeople as people  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def skin(colour=(200, 40, 40, 255)) -> bytes:
    img = Image.new("RGBA", (64, 64), colour)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


asked = []
real_lookup = skins.lookup
skins.lookup = lambda name, timeout=8.0: asked.append(name) or {"png": skin(), "slim": False, "source": "mojang", "skin": ""}

print("\n== drawing one ==")
folder = Path(_tmp.name) / "cache" / "minecraft_people"
uid = people.minecraft_id("Notch")
check("a player has an id the panel takes for a chat's picture", bool(uid) and people._ID.fullmatch(uid) is not None, uid)
t0 = time.perf_counter()
file = skins.save_player_picture(1, uid, "Notch", folder)
ms = (time.perf_counter() - t0) * 1000
check("it is named for the account and the chat, as the panel will only take", file == f"1_{uid}.png", file)
img = Image.open(folder / file)
check("a small square picture", img.size == (128, 128) and img.format == "PNG", str(img.size))
check("with something on it", img.convert("RGBA").getextrema()[3][1] > 0)
check(f"quick to make, off the loop anyway ({ms:.0f} ms)", ms < 2000)
before = (folder / file).stat().st_mtime_ns
time.sleep(0.02)
skins.save_player_picture(1, uid, "Notch", folder)
check("the same picture again leaves the file alone, so the panel's address for it stays", (folder / file).stat().st_mtime_ns == before)
skins.lookup = lambda name, timeout=8.0: {"png": skin((20, 200, 40, 255)), "slim": True, "source": "mojang", "skin": ""}
skins.save_player_picture(1, uid, "Notch", folder)
check("a new skin makes a new file", (folder / file).stat().st_mtime_ns != before)
skins.lookup = lambda name, timeout=8.0: {"png": b"", "slim": False, "source": "default", "skin": "steve"}
check("no skin to draw from, no file named", skins.save_player_picture(1, "mc_nobody", "nobody", folder) == "")

print("\n== the panel finds it ==")
(folder / f"contacts_1.json").write_text(json.dumps({uid: {"name": "Notch", "file": file}}), encoding="utf-8")
if hasattr(people, "_contacts_cache"):
    people._contacts_cache.clear()
real_dir = people.MINECRAFT_PEOPLE_DIR
people.MINECRAFT_PEOPLE_DIR = folder
path = people.picture_path(1, uid, "minecraft")
check("by the chat", path is not None and path.name == file, str(path))
url = people.avatar_url(1, uid, "minecraft")
check("at the address every page draws pictures from", url.startswith(f"/api/chats/web-picture/minecraft/1/{uid}?v="), url)
people.MINECRAFT_PEOPLE_DIR = real_dir

print("\n== from the runner ==")
src = (ROOT / "app/platforms/snapchat_bridge.py").read_text(encoding="utf-8")
check("someone met gets one", "_mc_face_soon(uid, name, data[uid])" in src)
check("behind whatever asked, off the loop: Mojang can take seconds", "await asyncio.to_thread(skins.save_player_picture" in src)
check("about once a day each", 'time.time() - float(row.get("face_at") or 0) < 86400' in src)
check("and the ones it already knows, at its start, a few seconds apart",
      "asyncio.create_task(_mc_faces_of_everyone())" in src and "await asyncio.sleep(3)" in src)

print("\n== the summary in Memory ==")
card = (ROOT / "webui/src/lib/components/PersonSummary.svelte").read_text(encoding="utf-8")
smooth = (ROOT / "webui/src/lib/smoothheight.ts").read_text(encoding="utf-8")
check("the card glides to its new height", 'relative overflow-hidden rounded-2xl p-4" use:smoothHeight>' in card)
check("its one child is what is measured", "node.firstElementChild" in smooth and "seen.observe(inner)" in smooth)
check("a change part way goes on from where it is", "moving ? node.getBoundingClientRect().height : height" in smooth)
check("not with Animations off", "get(motionEnabled)" in smooth)

skins.lookup = real_lookup
print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
