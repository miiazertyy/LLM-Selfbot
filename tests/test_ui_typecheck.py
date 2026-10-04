"""The panel's code type-checks clean: no errors and no warnings.

There were fifteen errors for a long time, all in code that worked: props
declared with the old $props<T>() form (which leaves them untyped), untyped
parameters, and values TypeScript could not prove non-null inside a click
handler. Left alone, a real mistake shows up as the sixteenth line in a list
everyone has learned to ignore. Zero keeps the list worth reading.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


npx = shutil.which("npx") or shutil.which("npx.cmd")
if not npx or not (WEB / "node_modules").is_dir():
    print("  SKIP  needs Node and webui/node_modules")
    sys.exit(0)

proc = subprocess.run([npx, "svelte-check", "--threshold", "warning", "--output", "machine"], cwd=WEB,
                      capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
out = proc.stdout + proc.stderr
m = re.search(r"COMPLETED (\d+) FILES (\d+) ERRORS (\d+) WARNINGS", out)
check("svelte-check ran", bool(m), out[-300:])
if m:
    problems = [l for l in out.splitlines() if " ERROR " in l or " WARNING " in l]
    check("no type errors", m.group(2) == "0", "; ".join(problems[:5]))
    check("and no warnings", m.group(3) == "0", "; ".join(problems[:5]))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
