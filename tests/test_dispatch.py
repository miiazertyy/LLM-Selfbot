"""Guards against runaway process spawning.

The frozen exe's entry point is app/desktop.py, and the supervisor spawns
workers by re-invoking that same executable with --role. If argv is ignored,
every worker becomes a supervisor that spawns more workers. These tests pin the
three independent guards that prevent it.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app import cli
from app.core import launcher

print("\n== argv dispatch ==")
p = cli.build_parser()
check("--role discord parses", p.parse_args(["--role", "discord", "--account", "2"]).role == "discord")
check("--account parses", p.parse_args(["--role", "discord", "--account", "2"]).account == 2)
for role in cli.ROLES:
    check(f"role '{role}' accepted", p.parse_args(["--role", role]).role == role)
check("bare argv means no role", p.parse_args([]).role is None)
check("legacy mode still parses", p.parse_args(["both"]).mode == "both")

print("\n== the spawn command the supervisor actually issues ==")
argv = launcher.role_argv("discord", 2)
check("worker argv carries --role", "--role" in argv and "discord" in argv, str(argv))
check("worker argv carries --account", "--account" in argv and "2" in argv, str(argv))
# Whatever the entry point, the argv the supervisor emits must be understood by
# the parser the entry point uses.
flags = argv[argv.index("--role"):]
parsed = cli.build_parser().parse_args(flags)
check("emitted argv round-trips through the parser",
      parsed.role == "discord" and parsed.account == 2)

print("\n== guard 2: a worker refuses to become a supervisor ==")
env = dict(os.environ, LLMSELFBOT_CHILD="1", PYTHONIOENCODING="utf-8")
r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, r'%s'); from app import cli; cli.run_supervisor()" % REPO],
    env=env, capture_output=True, text=True, timeout=120, cwd=REPO)
check("run_supervisor() exits non-zero when LLMSELFBOT_CHILD=1", r.returncode == 2,
      f"exit {r.returncode}: {(r.stdout + r.stderr)[-200:]}")
check("and says why", "worker process" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-200:])

print("\n== guard 3: only one supervisor can hold the lock ==")
holder = subprocess.Popen(
    [sys.executable, "-c",
     "import sys,time; sys.path.insert(0, r'%s'); from app import cli;"
     "cli.acquire_single_instance(); print('HELD', flush=True); time.sleep(30)" % REPO],
    env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO)
try:
    line = holder.stdout.readline()
    check("first instance takes the lock", "HELD" in line, repr(line))
    second = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from app import cli; cli.acquire_single_instance();"
         "print('ALSO HELD')" % REPO],
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        capture_output=True, text=True, timeout=60, cwd=REPO)
    check("second instance is refused", second.returncode == 1 and "ALSO HELD" not in second.stdout,
          f"exit {second.returncode}: {second.stdout.strip()}")
    check("and says why", "already running" in second.stdout, second.stdout.strip())
finally:
    holder.terminate()
    try:
        holder.wait(timeout=10)
    except Exception:
        holder.kill()

print("\n== guard 1: desktop entry dispatches instead of opening a window ==")
# --role telegram with no token configured returns immediately; the point is
# that it does NOT reach the desktop/supervisor path.
r = subprocess.run(
    [sys.executable, str(REPO / "app" / "desktop.py"), "--role", "updater", "--help"],
    env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    capture_output=True, text=True, timeout=120, cwd=REPO)
out = r.stdout + r.stderr
check("desktop entry exposes the CLI parser", "--role" in out and "usage:" in out.lower(), out[-300:])
check("desktop entry did not start a control panel", "Starting control panel" not in out, out[-200:])

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
