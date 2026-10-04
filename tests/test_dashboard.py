"""The Dashboard's widgets: saving, cleaning up, and what the page does.

The layout logic runs for real under Node (tests/dashboard_layout.mjs). What is
checked here is the part that failed silently before it was caught: the server
has an allowlist of panel preferences, and without dashLayout on it the layout
lived only in the browser - which the desktop window clears on exit, so every
restart put the Dashboard back to its defaults.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui"
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== the layout logic, in Node ==")
node = shutil.which("node")
if not node or not (WEB / "node_modules" / "svelte").is_dir():
    print("  SKIP  needs Node and webui/node_modules")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "dashboard_layout.mjs")], cwd=WEB,
                          capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("dashboard_layout.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print()
print("== the layout survives a restart ==")
SANDBOX = Path(tempfile.mkdtemp(prefix="dash_test_"))
(SANDBOX / "config").mkdir(parents=True)
import app.web.routes.prefs_routes as prefs
prefs.PREFS_PATH = SANDBOX / "config" / "panel.json"
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI()
app.include_router(prefs.router)
client = TestClient(app)

layout = [{"id": "hours-abc123", "type": "hours", "collapsed": True, "size": "full",
           "options": {"days": 90}}]
r = client.post("/api/prefs", json={"prefs": {"dashLayout": layout}})
check("the server accepts the layout", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
back = client.get("/api/prefs").json()["prefs"].get("dashLayout")
check("and hands it back intact", back == layout, json.dumps(back))
check("it is on the allowlist", "dashLayout" in prefs.ALLOWED)
r = client.post("/api/prefs", json={"prefs": {"somethingElse": 1}})
check("the allowlist still refuses anything else", r.status_code == 400)
shutil.rmtree(SANDBOX, ignore_errors=True)

print()
print("== what the page does ==")
dash = (WEB / "src" / "pages" / "Dashboard.svelte").read_text(encoding="utf-8")
frame = (WEB / "src" / "lib" / "dashboard" / "WidgetFrame.svelte").read_text(encoding="utf-8")
check("widgets can be added from a gallery", "<AddWidget" in dash and "makeInstance(type)" in dash)
check("removing one can be undone", "function undo()" in dash and "<UndoBar" in dash)
check("the layout can be reset", "function resetLayout()" in dash)
check("moving is not mouse-only", "function move(id: string, delta: number)" in dash)
check("reordering animates", "animate:flip" in dash)
check("a folded widget's content is gone, not just hidden",
      "{#if !collapsed}" in frame and "transition:slide" in frame)
# The grid-row version of folding was measured in a browser: with the spring
# easing it passed through a negative fraction and the height lagged a click.
check("folding does not animate grid rows with an overshooting curve",
      "grid-template-rows" not in frame.split("<style>")[1] if "<style>" in frame else True)
check("widgets can be made half or full width", "function resize()" in frame)
check("each widget's settings are one click away", 'aria-label="Widget settings"' in frame)
check("animations follow the motion setting", "$motionEnabled" in frame and "motion(" in dash)

# Widgets lay out by their own width. They used the window's breakpoints, so a
# half-width widget split into two columns and left half of itself empty, and
# widening one changed nothing inside it.
body = (WEB / "src" / "lib" / "dashboard" / "WidgetBody.svelte").read_text(encoding="utf-8")
accw = (WEB / "src" / "lib" / "dashboard" / "AccountsWidget.svelte").read_text(encoding="utf-8")
check("a widget is a size container", '<div class="@container' in frame)
check("widget layouts follow the widget's width, not the window's",
      not __import__("re").search(r'class="[^"]*(?<![@\w-])(sm|md|lg|xl):', body + accw), "")
check("one account fills the widget (cards grow to fill their row)",
      "flex-wrap: wrap" in accw and "flex: 1 1 320px" in accw)
check("the accounts widget says what an account is doing, not its pid",
      "condition(" in accw and "pid" not in accw.split("<style>")[0].split("</script>")[1])
check("people are shown with their pictures", "t.avatar" in body)
check("someone waiting can be answered from the Dashboard", "sendReply(" in body)

# The gallery shows each widget as it will look: the real body, live data,
# laid out at its own width and scaled - not a name and a sentence.
gallery = (WEB / "src" / "lib" / "dashboard" / "AddWidget.svelte").read_text(encoding="utf-8")
check("the gallery previews the real widget", "<WidgetBody" in gallery and "{ctx}" in gallery)
check("with the Dashboard's data", "<AddWidget" in dash and "{ctx}" in dash.split("<AddWidget")[1].split("/>")[0])
check("previews cannot be clicked into by accident", " inert" in gallery)
check("and are not buttons inside a button",
      '<div class="add-card' in gallery and 'class="add-hit"' in gallery)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
