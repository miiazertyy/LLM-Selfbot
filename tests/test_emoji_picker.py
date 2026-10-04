"""The emoji picker, made over: reacting to a message, and the persona's set of reactions.

Asked for: it looked plain, its nine categories wrapped onto a second line, and nothing moved. Checked here: the
categories are one row of their own emoji with a pill gliding under the open one, the ones used lately come first,
a category's emoji pop in one after another with a tick each, the one under the pointer is shown big with its name,
a picked emoji pops up and floats off from where it was pressed, and the reaction popup grows into the full picker
rather than jumping to its size. What it is used for has not changed: the same props, the same picks.
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


ep = read("lib/components/EmojiPicker.svelte")
rp = read("lib/components/ReactPicker.svelte")
bu = read("lib/burst.ts")
css = read("app.css")

print("== the categories ==")
check("one row of their own emoji, not words wrapping onto a second line",
      'class="ep-tabs"' in ep and "{MARK[g.name] ?? \"✨\"}" in ep and "flex-wrap" not in ep.split('class="ep-tabs"')[0][-200:])
check("a pill glides under the open one, with a jelly", 'class="ep-pill"' in ep
      and ".ep-pill.is-ready { opacity: 1; transition: transform 0.42s var(--jelly), width 0.42s var(--jelly); }" in ep)
check("heard as it moves along, a tick a step higher further along the row",
      'play("tick", { p: Math.max(0, at(name)) / Math.max(1, groups.length - 1) });' in ep and 'data-sound="self"' in ep)
check("the ones used lately come first, kept on this computer", 'const RECENT_KEY = "emoji.recent";' in ep
      and 'name: "Recent"' in ep and "remember(ch);" in ep)

print("\n== the grid ==")
check("a category's emoji pop in one after another, quickly, a dry tick each",
      'use:domino={{ step: 7, max: 48, sound: "wind", level: 0.35, once: true }}' in ep and "{#key `${group}|${q}`}" in ep)
check("from the side the category is on", "--ep-from: {dir * 10}px" in ep and "@keyframes ep-in" in ep)
check("bigger, lifting under the pointer, squashing as pressed", "font-size: 23px;" in ep
      and "transform: translateY(-2px) scale(1.22);" in ep and ".ep-e:active:not(:disabled) { transform: scale(0.88); }" in ep)
check("the one under the pointer shown big with its name", 'class="ep-foot"' in ep and 'class="ep-big"' in ep
      and "onpointerenter={() => (hovered = [ch, name])}" in ep)
check("nothing found says so", "Nothing matches that." in ep)

print("\n== picking ==")
check("a picked emoji pops up and floats off from where it was pressed, a ring going out under it",
      "export function burst(ch: string, from: Element | null)" in bu and "burst(ch, e.currentTarget as Element);" in ep
      and ".emoji-burst {" in css and ".emoji-burst-ring {" in css)
check("the reaction row's own emoji too, the popup already gone", "if (add && from) burst(e, from);" in rp
      and "onclick={(ev) => pick(e, ev.currentTarget)}" in rp)
check("the popup grows into the full picker rather than jumping to its size", "box.animate([" in rp
      and 'borderRadius: "999px"' in rp and 'borderRadius: "18px"' in rp)
check("the same props as before, so the persona's reactions still use it as they did",
      "chosen?: string[];" in ep and "full?: boolean;" in ep and "onpick: (emoji: string) => void;" in ep
      and "<EmojiPicker chosen={emojis} full={emojis.length >= MAX} onpick={toggleEmoji} />"
      in read("lib/components/ReactionEditor.svelte"))
check("with Animations off, no motion", ':global(:root[data-motion="off"]) .ep-pill' in ep and "if (!from || !get(motionEnabled)) return;" in bu)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
