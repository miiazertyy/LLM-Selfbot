"""No em dashes anywhere in the project. No exceptions.

The owner asked for them gone from the whole codebase: a comma where a comma
works, a hyphen where one is genuinely needed. This pins it, because a single
careless paste puts one back and nobody notices until it surfaces in the UI.

The three functions that strip an em dash out of what the model wrote still
need the character to search for, so they spell it as a unicode escape
instead of typing it. The behaviour is identical and the file stays clean, which is why this test
can demand zero occurrences rather than keeping a list of exempt files.

Those strippers are asserted separately below. A blanket sweep once rewrote
humanize.strip_ai_tells into text.replace(", ", ""), silently deleting every
comma from every reply the bot sent, so "the character is gone" is not on its
own enough to prove the sweep was harmless.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EM = "\u2014"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".venv", "venv",
             "build", ".pytest_cache", "logs", "backups", "temp"}
EXTS = {".py", ".svelte", ".ts", ".js", ".md", ".txt", ".yaml", ".yml", ".json",
        ".html", ".css", ".spec", ".bat", ".sh", ".iss"}

# Where the project's own code and shipped text lives. Scanning the whole tree
# swept up the persona and mood files someone writes for their own bot, which
# are their words, not ours, and not something this test has any business
# reformatting.
SOURCE_ROOTS = ("app", "webui/src", "tests", "scripts", "packaging", "resources", ".github")
SOURCE_FILES = ("README.md", "main.py", "requirements.txt", "requirements-dev.txt", ".gitignore")


def in_scope(rel: Path) -> bool:
    if str(rel).replace("\\", "/") in SOURCE_FILES:
        return True
    head = str(rel).replace("\\", "/")
    return any(head == r or head.startswith(r + "/") for r in SOURCE_ROOTS)


print("== no em dashes in source ==")
offenders = []
for path in sorted(ROOT.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(ROOT)
    if not in_scope(rel):
        continue
    if any(part in SKIP_DIRS for part in rel.parts):
        continue
    if path.suffix.lower() not in EXTS:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    if EM in text:
        line = next(i for i, l in enumerate(text.split("\n"), 1) if EM in l)
        offenders.append(f"{rel}:{line}")

check("no em dash in any source file", not offenders,
      ", ".join(offenders[:5]) + (f" and {len(offenders) - 5} more" if len(offenders) > 5 else ""))

print("\n== the strippers still strip ==")
from app.utils.humanize import strip_ai_tells

check("em dash removed from a reply", strip_ai_tells(f"a {EM} b") == "a  b",
      repr(strip_ai_tells(f"a {EM} b")))
check("en dash removed too", strip_ai_tells("a \u2013 b") == "a  b")
check("commas survive", strip_ai_tells("one, two, three") == "one, two, three",
      repr(strip_ai_tells("one, two, three")))
check("normal text untouched", strip_ai_tells("hey what are you up to")
      == "hey what are you up to")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
