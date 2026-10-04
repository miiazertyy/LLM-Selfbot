"""Seeing a picture without a box over the page.

The full-size picture used to open in a dialog the width of the page, with a
title bar and a plate of empty space round a tall picture. Now it grows out of
its card to the middle of the window over a light veil, with what the bot
reads under it in a slim caption, steps to the others with the arrows (or ←
and →), and goes back into its card when put away: a click anywhere off it,
Escape, or the cross.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


page = read("pages/Pictures.svelte")
pv = read("lib/components/PictureViewer.svelte")

print("== the page ==")
check("no dialog for full size any more", "<Modal open={!!view}" not in page and "<PictureViewer items={shownPics} current={view}" in page)
check("each card's picture says which it is, to grow out of and go back into",
      "data-pic={keyOf(p)}" in page and 'document.querySelector<HTMLElement>(`img[data-pic="${CSS.escape(keyOf(x))}"]`)' in page)
check("Edit from it opens the description, the picture put away", "onedit={(x) => { view = null; openEdit(x); }}" in page)

print("\n== the viewer ==")
check("drawn over everything, on a light veil, not a dark room",
      "function portal(node: HTMLElement)" in pv and "background: rgb(6 6 14 / 0.42);" in pv and "blur(6px)" in pv)
check("it grows out of its card: the same shape, moved and scaled, landing with a little give",
      "async function growFrom(p: Pic)" in pv and "translate(${dx}px, ${dy}px) scale(${s})" in pv
      and "cubic-bezier(0.2, 0.95, 0.25, 1.04)" in pv)
check("where the picture really is inside its card (it fits the whole picture in)", "function shownRect(el: HTMLElement, aspect: number)" in pv)
check("put away: back into its card when that is on screen, shrinking away when not",
      "async function close()" in pv and "end && onScreen(end)" in pv and 'transform: "scale(0.92)"' in pv)
check("a click off it, Escape or the cross puts it away",
      'e.target === e.currentTarget || (e.target as HTMLElement).classList.contains("pv-stage")' in pv
      and 'if (e.key === "Escape") { e.preventDefault(); close(); }' in pv and 'class="pv-x" onclick={close}' in pv)
check("the arrows and ← → step through the rest, each sliding in from its side",
      'e.key === "ArrowRight"' in pv and 'e.key === "ArrowLeft"' in pv and "@keyframes pv-step" in pv
      and "translateX(calc(var(--dir) * 46px))" in pv and "(at + by + items.length) % items.length" in pv)
check("the ones either side fetched ahead", "for (const n of [items[at + 1], items[at - 1]]) if (n && !n.video) new Image().src = src(n);" in pv)
check("what the bot reads, in a slim caption under it, with its name, size and place",
      'class="pv-cap"' in pv and "{@html renderMarkdown(p.description)}" in pv and "{at + 1} of {items.length}" in pv
      and "No description, so the bot can never send this one." in pv)
check("a video plays with its sound and its controls", "controls autoplay loop playsinline" in pv)
check("heard: a whoosh opening, a slide each step", 'play("open");' in pv and 'play("slide", { level: 0.5 });' in pv)
check("on a phone the arrows go to the foot", "@media (max-width: 640px)" in pv and ".pv-nav { top: auto; bottom: 18px;" in pv)
check("motion off: no growing, sliding or fading", "const moving = () =>" in pv and "if (!el || !from || !moving()) return;" in pv
      and ':global(:root[data-motion="off"]) .pv,' in pv)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
