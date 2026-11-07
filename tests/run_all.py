"""Run every test module in this directory. Usage: python tests/run_all.py"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# This runner prints what the modules print, emoji and all. Into a pipe on Windows (a CI log, a file) Python writes the
# code page, which has no character for them, and the first one stopped the whole run with a UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failed = []
total_pass = total_fail = 0

# On GitHub, each failure is also an annotation on the step. Its log is shown only to people signed in to GitHub, and
# the CI's ARM build failed twice with nothing to read but "exit code 1"; annotations anyone can see, on the run's page
# and through GitHub's API.
ON_GITHUB = __import__("os").environ.get("GITHUB_ACTIONS") == "true"
told = 0


def annotate(module: str, text: str) -> None:
    global told
    if not ON_GITHUB or told >= 10:          # GitHub keeps ten errors a step
        return
    told += 1
    text = text.strip().replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")[-1500:]
    print(f"::error title={module}::{text}", flush=True)

for path in sorted(HERE.glob("test_*.py")):
    print(f"\n{'=' * 60}\n  {path.name}\n{'=' * 60}")
    # Read back as the UTF-8 each module is told to write: Windows' own code page has no character for some bytes of
    # an emoji, and one in a check's name stopped the whole run.
    proc = subprocess.run(
        [sys.executable, str(path)], cwd=REPO,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = proc.stdout + proc.stderr
    for line in out.splitlines():
        if line.startswith(("  PASS", "  FAIL", "==")) or "passed," in line:
            print(line)
    # The LAST one: a module that runs a Node test first prints that test's
    # count before its own, and taking the first counted the sub-test instead
    # of the module, so the grand total came out lower than the real one.
    summary = next((l for l in reversed(out.splitlines()) if "passed," in l), "")
    if summary:
        p, f = summary.split(" passed, ")
        total_pass += int(p)
        total_fail += int(f.split(" ")[0])
    if proc.returncode != 0:
        failed.append(path.name)
        if not summary:
            print(out[-2000:])
        # What failed, in its own words: the FAIL lines, or how it ended when it stopped before saying.
        fails = [line.strip() for line in out.splitlines() if line.startswith("  FAIL")]
        annotate(path.name, "\n".join(fails[:8]) if fails else out[-1200:])

print(f"\n{'=' * 60}")
print(f"  {total_pass} passed, {total_fail} failed"
      + (f"  |  modules with errors: {', '.join(failed)}" if failed else ""))
print("=" * 60)
sys.exit(1 if failed else 0)
