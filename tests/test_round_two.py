"""A second round, each asked for.

  * the caption on a picture looks like Snapchat's, not edited: the letters are an iPhone's kind (Inter, shipped, in
    place of Segoe UI) on a half see-through band at the phone's proportions, and big text is bold with a soft shadow
    instead of a meme's outline
  * the "When it sends a picture" part of Settings: account cards, how often in a word, chips with icons, and a phone
    showing what it would send
  * a local model that will not load no longer fills the log: while no model can reply, nothing asks it again for
    every message waiting, it is said once; and when the model has no size this computer has room for, something
    smaller by the same maker that fits is found and offered, one click away

No network: HuggingFace and Ollama are stood in for.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-roundtwo-"))
(TMP / "config").mkdir(parents=True, exist_ok=True)
MODEL = "hf.co/HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF:latest"
REPO = "HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF"
cfg = yaml.safe_load((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"))
cfg["bot"]["models"] = {"replies": [{"provider": "local", "model": MODEL}]}
cfg["bot"]["local"] = {"enabled": True, "base_url": "http://127.0.0.1:1/v1", "model": MODEL}
(TMP / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== the caption, as Snapchat draws it ==")
from PIL import Image  # noqa: E402

from app.utils import looks  # noqa: E402

check("the letters an iPhone's kind: Inter, shipped with the app, with its licence",
      (ROOT / "resources" / "fonts" / "Inter-Variable.ttf").is_file()
      and "SIL Open Font License" in read("resources/fonts/Inter-OFL.txt")
      and looks._font("caption", 40).getname()[0] == "Inter" and looks._font("big", 80).getname()[0] == "Inter")
cap = looks._font("caption", 40)
axes = {(a["name"].decode() if isinstance(a["name"], bytes) else a["name"]): a for a in cap.get_variation_axes()}
check("a little heavier than regular for a caption, bold for big text", looks._INTER == {"caption": (460, 18), "big": (720, 28)}
      and "Weight" in axes)
src = read("app/utils/looks.py")
caption = src.split("def _caption_bar(")[1].split("\ndef ")[0]
check("at the phone's proportions on a half see-through band", '_fit(text, "caption", round(w * 0.0436)' in caption
      and "fill=(0, 0, 0, 128)" in caption)
big = src.split("def _big_text(")[1].split("\ndef ")[0]
check("big text lifted by a soft shadow, not outlined", "stroke" not in big and "GaussianBlur" in big)
img = Image.new("RGBA", (360, 640), (200, 200, 200, 255))
out = looks.draw_touch(img, {"caption": "told u i'm broke", "caption_pos": "middle"})
band = out.getpixel((5, int(640 * looks.CAPTION_POS["middle"])))
check("drawn: the picture the same size, the band half dark over it", out.size == img.size and 90 < band[0] < 115, str(band))
out = looks.draw_touch(img, {"big_text": "on my way", "big_pos": "upper"})
check("and big text drawn too", out.size == img.size)
check("without the shipped font, Windows' own is used", "kind = \"regular\" if kind == \"caption\" else \"bold\"" in src)

print("\n== the picture part of Settings ==")
pp = read("webui/src/lib/components/PicturesPanel.svelte")
check("the accounts as cards, each face with its platform on it, lit while it adds things",
      '<div class="pp-acct" class:is-on={on}>' in pp and "<Avatar src={a.avatar}" in pp)
check("how often, in a word as well", "const oftenWord = (v: number)" in pp and "{oftenWord(chance)}" in pp)
check("what it may add as chips, each with its icon", 'class="chips" data-sound="self"' in pp
      and '<span class="chip-mark"><Icon name={k.icon} size={13} /></span>' in pp)
icons = read("webui/src/lib/components/Icon.svelte")
check("icons for a caption, big text, the time and emoji", all(f"    {n}: " in icons for n in ("caption", "type", "clock", "smile")))
check("a phone with what it would send on its screen, beside the choices", 'class="pp-phone"' in pp
      and "{#key preview.image}" in pp and "@keyframes pp-snap-in" in pp)
check("hidden pictures stay hidden there", "class:is-veiled={veiled}" in pp)

print("\n== no model can reply: said once, not asked again for every message ==")
from app.utils import ai  # noqa: E402
from app.utils import providers  # noqa: E402

entry = providers.reply_chain(ai.load_config())[0]
check("one that answers: nothing in the way", ai.unavailable_now() == "")
ai._wont_load[(entry["provider"], entry["model"])] = (time.time() + 600, "the file is not a whole model")
why = ai.unavailable_now()
check("every model in the chain left alone: why, in words", "will not load: the file is not a whole model" in why, why)
check("said once in a while, not every time", ai.say_once("test line", 60) and not ai.say_once("test line", 60))
ai._wont_load.clear()
dr = read("app/platforms/discord_runner.py")
check("a reply is not even tried while no model can, and the messages wait", "_why_not = ai_module.unavailable_now()\n    if _why_not:" in dr
      and 'log_system(f"Not replying for now: {_why_not}. Messages wait until a model can reply.")' in dr)
check("one that will not load is not asked twice more for the same message", "if isinstance(e, ai_module.ModelWontLoad):\n"
      "                set_reply_state(uid, \"failed\", reason=error_msg)\n                return None" in dr)
check("Reply and Reply to all give that as the reason, not a line each", dr.count("elif (_why_not := ai_module.unavailable_now()):") == 2)
sb = read("app/platforms/snapchat_bridge.py")
check("Snapchat the same: not logged nor sent to Telegram for every message", "wont = isinstance(e, ModelWontLoad)" in sb
      and "if not wont:\n                    log_error(\"Snap AI Error\", str(e))" in sb)

print("\n== something smaller by the same maker ==")
from app.utils import localai, localfix as lf  # noqa: E402

GB = lf.GB
check("a repo's kind, its size and version left out", lf._flavour("Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF")
      == {"qwen3", "uncensored", "hauhaucs", "aggressive"})
LISTED = [{"id": REPO}, {"id": "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive"},
          {"id": "HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive"}, {"id": "HauhauCS/Qwen3.5-2B-Uncensored-HauhauCS-Aggressive"},
          {"id": "HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Balanced"}, {"id": "HauhauCS/Qwen3VL-8B-Uncensored-HauhauCS-Balanced"}]
FILES = {
    "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive": [("Q4_K_M", 5.6), ("Q2_K", 3.3)],
    "HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive": [("Q4_K_M", 2.5), ("Q8_0", 4.4)],
    "HauhauCS/Qwen3.5-2B-Uncensored-HauhauCS-Aggressive": [("Q4_K_M", 1.3)],
    "HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Balanced": [("Q4_K_M", 2.9)],
    "HauhauCS/Qwen3VL-8B-Uncensored-HauhauCS-Balanced": [("Q4_K_M", 2.0)],
}
lf._hf_get = lambda url, **k: LISTED
lf.repo_files = lambda rid: [{"name": f"{rid.split('/')[1]}-{t}.gguf", "size": int(s * GB)} for t, s in FILES[rid]]
mach = {"ram": 16 * GB, "vram": 4 * GB, "free": int(3.7 * GB)}
alts = lf.alternatives(REPO, mach, room_back=int(1.7 * GB))
names = [a["label"] for a in alts]
check("the same kind only: Qwen, uncensored, aggressive (not the Balanced Gemma or the vision one)",
      all("Aggressive" in n and "Qwen3.5" in n for n in names), str(names))
check("best first: a 4-bit 4B over the 9B squeezed to 2 bits, then the 2B",
      names[:3] == ["Qwen3.5-4B-Uncensored-HauhauCS-Aggressive", "Qwen3.5-2B-Uncensored-HauhauCS-Aggressive",
                    "Qwen3.5-9B-Uncensored-HauhauCS-Aggressive"] and alts[0]["tag"] == "Q4_K_M", str(names))
check("the room the useless file gives back counts", [a["label"] for a in lf.alternatives(REPO, mach)][:1]
      == ["Qwen3.5-2B-Uncensored-HauhauCS-Aggressive"])
check("asked for by name the way Ollama takes it", alts[0]["model"] == "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M")
check("offered when stuck for room, never switched to unasked", "alt = next((a for a in alternatives(repo, machine(), held)" in read("app/utils/localfix.py")
      and 'Switch to it on This computer, in Settings, Models.' in read("app/utils/localfix.py"))

done = []
localai.delete_model = lambda m, b: done.append(("delete", m)) or {"ok": True}
lf._wait_for_pull = lambda name, base, give_up: done.append(("pull", name)) or ""
lf.switch = lambda old, new: done.append(("switch", old, new)) or 2
lf._say("stuck", MODEL, "it does not fit", alt=alts[0])
r = lf.use_alt("http://127.0.0.1:1/v1")
for _ in range(100):
    if lf.status()["state"] == "fixed":
        break
    time.sleep(0.02)
check("switching: the useless file first, then the download, then every setting", r == {"ok": True}
      and [d[0] for d in done] == ["delete", "pull", "switch"] and done[2][2] == alts[0]["model"], str(done))
check("and the panel says it is fixed", lf.status()["state"] == "fixed" and lf.status()["to"] == alts[0]["model"])
check("nothing to switch to says so", lf.use_alt("x") == {"ok": False, "reason": "There is nothing to switch to."})
check("looked at once at the start, not again for a note left before it (it was said twice)",
      "looked = {model: time.time() for model in configured(config)}" in read("app/utils/localfix.py"))
ui = read("webui/src/lib/components/LocalAI.svelte")
check("the page offers it under the problem, one button", '{#if fix.state === "stuck" && fix.alt}' in ui
      and "await api.localFixUseAlt();" in ui and '"/api/local/fix/use-alt"' in read("webui/src/lib/api.ts")
      and '@router.post("/api/local/fix/use-alt")' in read("app/web/routes/local_routes.py"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
