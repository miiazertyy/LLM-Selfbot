"""Small UI details that broke once and should stay fixed.

  * The subtab strip's scroll bar stopped appearing after switching tabs: only
    the buttons that existed when the page opened were watched, and the strip
    itself keeps its width, so nothing re-measured it.
  * Provider tiles show the provider's own logo, shipped with the app so it
    works offline, and a logo's padding is in pixels: a percentage padding is
    taken from the width of the card around it and blew the tile up.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== the subtab scroll bar ==")
hs = (WEB / "lib" / "hscroll.ts").read_text(encoding="utf-8")
check("new contents are noticed", "new MutationObserver(" in hs and "childList: true" in hs)
check("and the new buttons are watched too", "function watch()" in hs and "watch();" in hs.split("new MutationObserver(")[1])
check("the selected subtab is brought into view", "aria-selected=\"true\"" in hs)
check("and the observer goes away with the strip", "mo.disconnect()" in hs)
css = (WEB / "app.css").read_text(encoding="utf-8")
sub_bar = css[css.index(".settings-subs-wrap .hscroll-bar {"):][:400]
check("the subtabs' bar sits on top of them, next to the tabs' bar", "top: -6px" in sub_bar and "bottom: auto" in sub_bar)

print("\n== provider logos ==")
tile = (WEB / "lib" / "components" / "ProviderTile.svelte").read_text(encoding="utf-8")
logos = set(re.findall(r'"(\w+)"', tile[tile.index("new Set(["):tile.index("]);")]))
check("the main providers have one", {"groq", "openai", "anthropic", "gemini", "openrouter"} <= set(logos), str(logos))
missing = [n for n in logos if not (ROOT / "webui" / "public" / "providers" / f"{n}.png").is_file()]
check("every logo named is shipped with the app", not missing, str(missing))
big = [n for n in logos if (ROOT / "webui" / "public" / "providers" / f"{n}.png").stat().st_size > 40_000]
check("and small", not big, str(big))
check("a logo that fails falls back to initials", "onerror" in tile and "MONOGRAM" in tile)
check("no percentage padding on a tile", not re.search(r"padding:\s*\d+%", tile))
from PIL import Image
opaque = [n for n in logos if Image.open(ROOT / "webui" / "public" / "providers" / f"{n}.png").convert("RGBA").getpixel((1, 1))[3] > 20]
check("every logo is the mark alone, on no background of its own", not opaque, str(opaque))

print("\n== Chats in the pocket window ==")
chats = (WEB / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("an open conversation gets the whole narrow window",
      "class:narrow-hide={showDetail && !!selected}" in chats
      and ".ch-top.narrow-hide, .ch-friends.narrow-hide { display: none; }" in chats)
check("with a way back to the list", 'class="cd-back"' in chats)
m = re.search(r"Math\.max\((\d+), scroller\.clientHeight", chats)
check("the height floor fits the pocket window, so Reply stays on screen",
      bool(m) and int(m.group(1)) <= 320, m.group(1) if m else "no floor found")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
