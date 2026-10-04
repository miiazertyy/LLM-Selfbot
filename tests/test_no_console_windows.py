"""No console windows popping up.

The packaged app is a windowed build with no console of its own, so any
console program it starts without CREATE_NO_WINDOW gets a brand new, visible
window: on Windows 11 a Terminal tab opening in your face. It happened at every
launch after a force-closed run (the supervisor's taskkill of the old workers),
and every time Ollama loaded a model, because the app started Ollama
DETACHED_PROCESS, with no console at all, so each model runner it spawned got
a visible one of its own.

This reads every subprocess call in the app and fails on one that has no
creationflags, unless it is one of the few that are meant to be seen.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


# (file, function) pairs allowed to start a process with a visible window, or
# where no window can appear: the updater is meant to be watched, the frozen
# updater role is itself a windowed build, and the POSIX branches have no
# consoles to open.
ALLOWED = {
    ("app/cogs/management.py", "update"),
    ("app/cogs/management.py", "restart"),
    # The source updater's console, meant to be watched (app/core/update.py
    # took it over from system_routes' update_run).
    ("app/core/update.py", "run"),
    # Only when running from source in a terminal, never in the packaged app:
    # restarting python after a config edit, and installing a missing library.
    ("app/cogs/management.py", "setconfig"),
    ("app/telegram_bot/telegram_controller.py", "_ensure_telegram_installed"),
}
CALLS = {"Popen", "run", "call", "check_output", "check_call"}


def offenders():
    out = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {"subprocess"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "subprocess" and a.asname:
                        names.add(a.asname)

        def visit(node, func):
            for child in ast.iter_child_nodes(node):
                f = func
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f = child.name
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and child.func.attr in CALLS and isinstance(child.func.value, ast.Name)
                        and child.func.value.id in names):
                    kws = child.keywords
                    quiet = any(k.arg == "creationflags" for k in kws) or any(
                        k.arg is None and isinstance(k.value, ast.Call) and getattr(k.value.func, "id", "") == "quiet_kwargs"
                        for k in kws) or any(k.arg == "start_new_session" for k in kws) or any(
                        k.arg is None and isinstance(k.value, ast.Name) for k in kws)   # **kwargs built above, checked below
                    if not quiet and (rel, f) not in ALLOWED:
                        out.append(f"{rel}:{child.lineno} in {f}()")
                visit(child, f)

        visit(tree, "<module>")
    return out


print("== every program the app starts is started without a window ==")
bad = offenders()
check("no subprocess call can open a console window", not bad, "; ".join(bad))

local = (ROOT / "app" / "utils" / "localai.py").read_text(encoding="utf-8")
start = local[local.index("def start_server"):local.index("def _set_start_error")]
check("Ollama gets a hidden console, so the model runners it spawns stay hidden too",
      "CREATE_NO_WINDOW" in start and "DETACHED_PROCESS" not in start.split("kwargs[\"creationflags\"]")[1][:200])
sup = (ROOT / "app" / "web" / "supervisor.py").read_text(encoding="utf-8")
check("clearing up after a force-closed run opens no window", "quiet_kwargs()" in sup[sup.index('"taskkill"') - 400:sup.index('"taskkill"') + 200])
helpers = (ROOT / "app" / "utils" / "helpers.py").read_text(encoding="utf-8")
check("a hidden console is not cleared with a cmd for nothing", 'os.environ.get("LLMSELFBOT_CHILD") == "1"' in helpers)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
