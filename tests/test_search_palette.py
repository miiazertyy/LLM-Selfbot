"""Ctrl+K: search everything, from the keyboard alone.

The palette finds pages, settings, people, accounts, pictures, log lines,
secrets and a few things to do, shows each for what it is (an icon, a face, a
thumbnail) with where it lives, and the one selected in full beside the list.
Every part of it works without the mouse.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


pal = (WEB / "lib" / "components" / "CommandPalette.svelte").read_text(encoding="utf-8")
idx = (WEB / "lib" / "search.ts").read_text(encoding="utf-8")
keys = pal[pal.index("function onKey("):pal.index("// ── The travelling highlight")]

print("== the keyboard ==")
check("arrows move, round from the bottom to the top", 'e.key === "ArrowDown") { e.preventDefault(); move(1)' in keys
      and "(sel + by + n) % n" in pal)
check("page keys move a page at a time", '"PageDown"' in keys and "move(6, false)" in keys)
check("Tab goes through the kinds of thing, Shift+Tab back", 'e.key === "Tab"' in keys and "nextScope(e.shiftKey ? -1 : 1)" in keys)
check("Enter opens or does it", 'e.key === "Enter"' in keys and "choose(current)" in keys)
check("Esc clears what is typed first, then closes", "if (q) q = \"\";" in keys and "else onclose?.();" in keys)
check("keys work wherever the focus is inside it", 'aria-label="Search" tabindex="-1" onkeydown={onKey}' in pal)
check("a real combobox and listbox, for screen readers", 'role="combobox"' in pal and "aria-activedescendant" in pal
      and 'role="listbox"' in pal and 'role="option"' in pal)
check("a kind with nothing for what is now typed falls back to All",
      'const tab = $derived(scopes.some((s) => s.id === scope) ? scope : "All");' in pal)

print("\n== what it shows ==")
check("each result says what it is: an icon, a face or a thumbnail", "{#snippet mark(" in pal and "<img src={h.image}" in pal)
check("and where it lives", "hit.where" in pal and "function whereIs(" in idx)
check("the one selected, in full beside the list", 'class="pal-preview"' in pal and "current.facts" in pal
      and "current.value" in pal)
check("matches lit in the accent, not boxed", ".pal :global(mark)" in pal and "background: none" in pal)
check("with nothing typed: what was opened last, and every page", "palette.recent" in pal and '"Recent"' in pal)
check("things it can do as well as open: themes, animations, snow", "Theme: ${t.name}" in pal
      and "Turn animations off" in pal and "Turn cursor snow on" in pal)
check("the log goes last, since it matches everything", 'if (d.group === "Logs") score -= 30;' in idx)
check("people are found by what is remembered about them", 'group: "People", kind: "person"' in idx
      and "JSON.stringify(facts)" in idx)
check("pictures carry their thumbnail, by id (a video's still)",
      'image: api.pictureThumb({ name: String(p.name), id: String(p.id ?? ""), video: !!p.video })' in idx)
check("a setting says what it is set to now", "value: valueOf(f.current)" in idx)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
