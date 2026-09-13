"""Run every test module in this directory. Usage: python tests/run_all.py"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

failed = []
total_pass = total_fail = 0

for path in sorted(HERE.glob("test_*.py")):
    print(f"\n{'=' * 60}\n  {path.name}\n{'=' * 60}")
    proc = subprocess.run(
        [sys.executable, str(path)], cwd=REPO,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    for line in out.splitlines():
        if line.startswith(("  PASS", "  FAIL", "==")) or "passed," in line:
            print(line)
    summary = next((l for l in out.splitlines() if "passed," in l), "")
    if summary:
        p, f = summary.split(" passed, ")
        total_pass += int(p)
        total_fail += int(f.split(" ")[0])
    if proc.returncode != 0:
        failed.append(path.name)
        if not summary:
            print(out[-2000:])

print(f"\n{'=' * 60}")
print(f"  {total_pass} passed, {total_fail} failed"
      + (f"  |  modules with errors: {', '.join(failed)}" if failed else ""))
print("=" * 60)
sys.exit(1 if failed else 0)
