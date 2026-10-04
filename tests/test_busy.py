"""The sidebar spinner for work still running on a page you have left.

The timing rules (nothing under 300ms, no blinking, a tick when done) are
checked by running the real webui/src/lib/busy.ts under Node in
tests/busy_logic.mjs. What is checked here is the wiring: which work reports
itself, and - just as much - which does not, because background work nobody
asked for would keep half the sidebar spinning.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui"
SRC = WEB / "src"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


print("== the timing rules, in Node ==")
node = shutil.which("node")
if not node or not (WEB / "node_modules" / "svelte").is_dir():
    print("  SKIP  needs Node and webui/node_modules")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "busy_logic.mjs")], cwd=WEB,
                          capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("busy_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print()
print("== what reports itself ==")
chats, res, app = read("lib/chats.ts"), read("lib/resource.ts"), read("App.svelte")
check("reply to all, the longest thing in the app", 'begin("chats", `Replying to' in chats)
check("a single reply", 'begin("chats", "Sending a reply")' in chats)
check("a page loading its own data", 'RESOURCE_ROUTES[key.split(":")[0]]' in res and "begin(route)" in res)
check("the Memory summary", 'track("memory"' in read("lib/components/PersonSummary.svelte"))
check("describing pictures", 'begin("pictures", "Describing pictures")' in read("lib/pictures.ts"))
check("a Local AI model download, after leaving Settings",
      'trackUntil("settings", `Downloading' in read("lib/components/LocalAI.svelte"))
check("installing Snapchat support",
      'trackUntil("settings", "Installing Snapchat support"' in read("lib/components/SnapchatSetup.svelte"))
check("starting and stopping accounts", 'track("accounts"' in read("pages/Accounts.svelte"))
check("export and import", read("pages/System.svelte").count('track("system"') == 2)

print()
print("== what does not ==")
check("the startup warm-up is quiet", "quiet: true" in read("lib/warm.ts"))
check("the Chats prefetch loop is quiet",
      "refreshChats(a.id, { maxAge: intervalMs / 2, quiet: true })" in chats)
check("a quiet resource load reports nothing", "!quiet && route ? begin(route) : null" in res)

print()
print("== what the sidebar shows ==")
check("only on pages you are not on", "route !== key && !!$busyRoutes[key]" in app)
check("a spinner beside the name", 'class="nav-spin ml-auto"' in app)
check("a ring on the icon in the collapsed rail", 'class="nav-ring"' in app)
check("a tick when it finishes", 'class="nav-done ml-auto"' in app)
check("and says what is running on hover", "in the background`" in app)
css = read("app.css")
# Two animations both setting transform: whichever holds its end state wins,
# and a scale-in held at scale(1) stopped the ring from turning at all.
ring = css[css.index(".nav-ring {"):css.index("}", css.index(".nav-ring {"))]
check("the rail ring's entrance does not fight its rotation",
      "nav-spin-in" not in ring and "nav-fade-in" in ring, ring)
check("motion can be turned off, with the app's own switch", ':root[data-motion="off"] .nav-spin' in css)
# Windows reports "reduce" whenever its animation effects are off, which is
# common: spinners that obeyed it stood still on such a PC and read as stuck
# (the Accounts page's Starting pill). The app's Motion switch decides instead,
# and the OS setting only seeds its default (stores.ts).
_stray = []
for _f in sorted((WEB / "src").rglob("*")):
    if _f.suffix in (".svelte", ".css", ".ts") and _f.name not in ("stores.ts", "Snow.svelte"):
        if "@media (prefers-reduced-motion" in _f.read_text(encoding="utf-8"):
            _stray.append(_f.name)
check("no spinner or animation stops for Windows' setting instead of the app's", not _stray, ", ".join(_stray))


print()
print("== real progress, where there is any ==")
check("reply to all moves one step per person", "job.progress(results.length, queue.length)" in chats)
check("describing pictures follows the server's count",
      "endDescribe.progress(s.done, s.total)" in read("lib/pictures.ts"))
check("adding several pictures moves one step per file, wherever the page is",
      "job.progress(next.done, next.total)" in read("lib/pictures.ts")
      and "addPictures(Array.from(files), () => load(), who)" in read("pages/Pictures.svelte"))
check("a model download reports its percentage",
      "report(s.percent, 100)" in read("lib/components/LocalAI.svelte"))
ring = read("lib/components/ProgressRing.svelte")
check("the ring fills to exactly done/total", "done / total" in ring and "stroke-dashoffset" in ring)
check("and spins only when progress is unknown", "class:spin={frac === null}" in ring)
check("the sidebar uses it", "<ProgressRing done={info?.done} total={info?.total}" in app)
check("and shows the count beside it", 'class="nav-pct"' in app)
badge = read("lib/components/LoadingBadge.svelte")
check("the header shows this page's real progress",
      "<ProgressRing done={own?.done} total={own?.total}" in badge)
check("the header no longer carries the logo", "icon.png" not in badge and "<img" not in badge)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
