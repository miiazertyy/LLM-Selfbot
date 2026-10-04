"""The Dashboard's live log looks like the Logs page, not the console.

It used to print the runners' raw text: monospace lines, "discord_1" as the
source, a message split across lines with a rule of box characters under it.
Now it draws the same rows as the Logs page, from the same code: lines folded
into one row per thing that happened (lib/logrows.ts) and drawn by one row
component (LogRow.svelte), so the two cannot drift apart.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


print("== folding lines into rows ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "logrows_logic.mjs")], cwd=ROOT / "webui",
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("logrows_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print("\n== one set of rows, two places ==")
logs = read("pages/Logs.svelte")
widget = read("lib/dashboard/LogWidget.svelte")
body = read("lib/dashboard/WidgetBody.svelte")
check("the Logs page folds its lines with the shared code", "foldRows(lines)" in logs and "function tidy" not in logs)
check("and draws them with the shared row", "<LogRow" in logs and 'class="lg-row"' not in logs)
check("the Dashboard widget folds its lines the same way", "foldRows(lines)" in widget)
check("and draws the same row", "<LogRow" in widget)
check("the widget is used for the Live log", "<LogWidget" in body)
check("no raw console text is left in the widget",
      "font-mono" not in body.split('inst.type === "log"')[1].split("{:else if")[0])

print("\n== it keeps up, and lets you read ==")
check("it follows the newest while you are at that end", "stick" in widget and "scrollTo" in widget)
check("and uses the Logs page's own newest-first setting", '"logs.newestFirst"' in widget)
check("only lines that just came in slide in", "isFresh" in widget)
dash = read("pages/Dashboard.svelte")
check("the Dashboard numbers and times its lines, so they can fold", "id: logSeq++" in dash and "ts:" in dash)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
