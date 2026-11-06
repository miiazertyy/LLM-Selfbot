"""Two fixes of 2026-10-31.

An account whose login is refused is not started again by itself. The Snapchat runner exited with an ordinary error,
the bridge called it a crash, and as each try ran over a minute it counted as a good run: the panel started it again
every two minutes, forever, each one a fresh login Snapchat counts (how an account gets locked). Now a refused
login is exit code 4, passed on by the bridge, and the supervisor leaves the account stopped and says so. It is
remembered on disk too: the app opening again leaves it stopped as well, until a person starts it.

An emoji in a dropdown (a mood's face) sits in the middle of its tile. It fell back from the flags font and sat on
the app font's baseline, high in the tile; it is drawn with the system's emoji font from the start now, measured
centred to the pixel (flags keep their own font).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


print("== a refused login is not tried again by itself ==")
runner = read("app/platforms/snapchat/snapchat_runner.js")
login_fail = runner[runner.index('setState("logged-out", "Login failed.'):][:600]
check("the Snapchat runner says so with its own code", "process.exit(4);" in login_fail and "process.exit(1)" not in login_fail)
check("and its card says what to do", 'setState("logged-out", "Login failed. Sign it in again from Accounts.")' in runner)
check("Instagram with no signed-in profile, the same",
      'Sign it in on the Accounts page.");\n    process.exit(4);'
      in read("app/platforms/snapchat/instagram_runner.js"))
bridge = read("app/platforms/snapchat_bridge.py")
check("the bridge passes it on instead of calling it a crash", "NEEDS_SIGN_IN = 4" in bridge
      and "if code == NEEDS_SIGN_IN:" in bridge and "_exit_now(NEEDS_SIGN_IN)" in bridge)
from app.web import supervisor  # noqa: E402
sup = read("app/web/supervisor.py")
check("the supervisor knows the code", supervisor.NEEDS_SIGN_IN == 4)
block = sup[sup.index("if code == NEEDS_SIGN_IN:"):][:700]
check("and leaves the account stopped, never restarting it", "child._stop_requested = True" in block
      and 'child.state = "stopped"' in block and "continue" in block)
check("telling the person, once", "needs you to sign it in again" in block and "alerts.append(" in block)
check("before it would count as a crash", sup.index("if code == NEEDS_SIGN_IN:") < sup.index("child.restarts += 1"))

print()
print("== nor at the app's next launch ==")
import tempfile  # noqa: E402
from app.utils import paths  # noqa: E402
real_data = paths.DATA_DIR
paths.DATA_DIR = Path(tempfile.mkdtemp())
try:
    s = supervisor.Supervisor()
    check("nothing waits to begin with", s.needs_sign_in() == set())
    s._mark_sign_in("snapchat_1", True)
    check("a refused login is remembered on disk", s.needs_sign_in() == {"snapchat_1"}
          and (paths.DATA_DIR / "needs_sign_in.json").exists())
    check("as the watchdog leaves it stopped", "self._mark_sign_in(child.child_id, True)" in block)
    launched = []
    s._planned_children = lambda: {"snapchat_1": ("snapchat", 1, "Snapchat #1")}
    s._launch = lambda child: launched.append(child.child_id)
    s.start("snapchat_1")
    check("started by hand, it no longer waits, and starts", s.needs_sign_in() == set() and launched == ["snapchat_1"])
finally:
    paths.DATA_DIR = real_data
start_all = sup[sup.index("    def start_all(self):"):sup.index("    def stop_all(self):")]
check("the app opening skips one that waits, saying why", "if child_id in waiting:" in start_all
      and start_all.index("if child_id in waiting:") < start_all.index("self.start(child_id)")
      and "needs you to sign it in again" in start_all)
check("and so does its social being switched back on", "or child_id in waiting:" in sup)

print()
print("== an emoji in the middle of its tile ==")
sel = read("webui/src/lib/components/Select.svelte")
check("flags told apart from other emoji", "const FLAG = /[\\u{1F1E6}-\\u{1F1FF}]/u;" in sel
      and 'class:is-emoji={!FLAG.test(o.mark)}' in sel)
css = sel[sel.index(".sel-mark.is-glyph.is-emoji {"):][:200]
check("an emoji drawn with the system's emoji font from the start",
      'font-family: "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", sans-serif;' in css)
check("its face brought to the middle", "padding-bottom: 0.1em;" in css)
check("flags keep their own font", '.sel-mark.is-glyph {\n    font-family: "Twemoji Country Flags"' in sel)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
