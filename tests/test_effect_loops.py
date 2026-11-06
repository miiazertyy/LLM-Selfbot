"""No page can stop the panel (2026-10-31).

Opening Chats stopped the whole panel: clicking Accounts lit it in the sidebar, the page underneath stayed Chats, and
no tab changed after that. An effect on the Chats page subscribed to a store, and a store calls back at once (on
subscribe, and as refresh() marks it loading): the callback read the state it then wrote, inside the effect, so the
effect depended on its own write and ran again, forever. Svelte stops that with effect_update_depth_exceeded, and
the app's page switching stops with it. Now the store is subscribed to untracked, and every effect in the panel that
subscribes to a store and rewrites a state from itself is checked for the same.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def effects(text):
    """(line, body) of every $effect in a component."""
    for m in re.finditer(r"\$effect(?:\.pre)?\(\(\) => \{", text):
        start, depth = m.end() - 1, 0
        for k in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            if depth == 0:
                yield text[:m.start()].count("\n") + 1, text[start:k]
                break


print("== the Chats page's archives ==")
chats = (SRC / "pages" / "Chats.svelte").read_text(encoding="utf-8")
past = next(body for _, body in effects(chats) if "pastOf(t)" in body)
check("its store is subscribed to and refreshed untracked",
      "untrack(() => targets.map((t) => {" in past and past.index("untrack(") < past.index(".subscribe(")
      and past.index("untrack(") < past.index("r.refresh("))
check("only which accounts it reads is tracked", "const targets = pastTargets;" in past)

print("\n== nor any other effect ==")
risky = []
for path in sorted(SRC.rglob("*.svelte")):
    text = path.read_text(encoding="utf-8")
    for line, body in effects(text):
        # A state rewritten from itself (x = { ...x, ... } or x = [...x, ...]) in a store's callback.
        if ".subscribe(" in body and re.search(r"\b(\w+) = (?:\{ ?\.\.\.|\[\.\.\.)\1\b", body) and "untrack(" not in body:
            risky.append(f"{path.relative_to(SRC)}:{line}")
check("no effect rewrites a state from itself in a store's callback, tracked", not risky, ", ".join(risky))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
