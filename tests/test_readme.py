"""The README: one list of the platforms, and the pictures it shows are there.

The platforms used to be named all over it (the tagline, the pages, what works where, a section each), so a new one
meant finding every place, and four of them were missed. Now they are listed once, in the Platforms table: adding one
is adding its row there, and this says which are missing. Elsewhere it may name one (a command, the Telegram remote)
but never list them again.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.platforms import registry

readme = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")

print("== the platforms, listed once ==")
check("there is a Platforms section", "\n## Platforms\n" in readme)
section = readme.split("\n## Platforms\n", 1)[1].split("\n## ", 1)[0] if "\n## Platforms\n" in readme else ""
rows = [line for line in section.split("\n") if line.startswith("| **")]
named = [re.match(r"\| \*\*([^*]+)\*\*", r).group(1) for r in rows]
for p in registry.PLATFORMS:
    check(f"{p.name} has its row", named.count(p.name) == 1, f"rows: {named}")
check("and nothing in the table the app doesn't run", set(named) <= {p.name for p in registry.PLATFORMS}, str(named))
check("each row says how it connects, what it does and where it runs", all(r.count("|") == 5 for r in rows))

outside = readme.replace(section, "")
pattern = re.compile(r"\b(" + "|".join(re.escape(p.name) for p in registry.PLATFORMS if len(p.name) > 1) + r")\b")
lists = [line for line in outside.split("\n") if len(set(pattern.findall(line))) > 1]
check("no other line lists platforms again: a new one is one row", not lists, " / ".join(lists[:3]))

print("\n== its pictures ==")
media = re.findall(r'src="(\.github/[^"]+)"', readme)
check("it shows some", len(media) >= 5, str(media))
for m in media:
    check(f"{m} is there", (ROOT / m).is_file())
shown = {Path(m).name for m in media}
spare = [f.name for f in (ROOT / ".github" / "media").iterdir() if f.is_file() and f.name not in shown]
check("nothing left in .github/media that it doesn't show", not spare, ", ".join(spare))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
