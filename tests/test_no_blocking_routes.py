"""Nothing that can wait holds the panel's event loop.

The panel's own watchdog caught it: "The panel froze for 0.6s: no page could load or respond until it was done ...
busy in db.py in profile_cache_size". An `async def` route runs on the event loop, and one that read the database
there waited for whatever lock a bot runner held while writing, every other page waiting with it. Twenty routes did
it: the leaderboard, a person's card, memory and its summaries, picture descriptions, every settings write.

Checked here, by reading the routes: no async route calls the database (app/utils/db.py, memory.py, snappeople.py)
or reads or writes a file except through asyncio.to_thread or a function handed to it; routes that await nothing are
plain functions, which FastAPI runs on its threadpool. And the smaller things found on the way: the config read with
libyaml's reader, the backups it leaves trimmed, and the background's slow loops held still while the window is not
in front.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


blocking = set()
for mod in ("db", "memory", "snappeople"):
    for node in ast.parse((ROOT / "app/utils" / f"{mod}.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            blocking.add(node.name)
blocking |= {"read_text", "write_text", "read_bytes", "write_bytes", "connect_raw", "urlopen"}


def called(c: ast.Call) -> str:
    f = c.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


offenders = []
routes = sorted((ROOT / "app/web/routes").glob("*.py"))
for path in routes:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                   and d.func.attr in ("get", "post", "put", "delete", "patch") for d in fn.decorator_list):
            continue
        handed = set()
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and called(c) in ("to_thread", "run_in_executor"):
                handed |= {id(a) for a in ast.walk(c)}
            if isinstance(c, (ast.FunctionDef, ast.Lambda)) and c is not fn:
                handed |= {id(a) for a in ast.walk(c)}
        bad = sorted({called(c) for c in ast.walk(fn)
                      if isinstance(c, ast.Call) and id(c) not in handed and called(c) in blocking})
        if bad:
            offenders.append(f"{path.name}:{fn.lineno} {fn.name} -> {', '.join(bad)}")

print("== the event loop ==")
check(f"no async route of {len(routes)} files reads the database or a file on the event loop", not offenders,
      "; ".join(offenders[:6]))
people = (ROOT / "app/web/routes/people_routes.py").read_text(encoding="utf-8")
check("the count the watchdog caught is read on a thread", "size = await asyncio.to_thread(profile_cache_size)" in people)
config = (ROOT / "app/web/routes/config_routes.py").read_text(encoding="utf-8")
check("every settings write happens on a thread", config.count("await asyncio.to_thread(_dump,") == 3)
check("the settings schema, built from every setting, is a plain function (the threadpool's)",
      "\ndef schema(request: Request, persona: str = \"\"):" in config)

print("\n== smaller things ==")
helpers = (ROOT / "app/utils/helpers.py").read_text(encoding="utf-8")
check("the config is read with libyaml's reader where there is one", '_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)' in helpers
      and "yaml.load(file, Loader=_YAML_LOADER)" in helpers)
import yaml  # noqa: E402
text = (ROOT / "resources" / "config.yaml").read_text(encoding="utf-8")
check("and reads the shipped config the same as before", yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
      == yaml.safe_load(text))
store = (ROOT / "app/utils/configstore.py").read_text(encoding="utf-8")
check("a backup before every write, only the newest forty kept", "KEEP_BACKUPS = 40" in store
      and "[:-KEEP_BACKUPS]" in store and "configstore.write_base(cfg, CONFIG_PATH)" in config)
app = (ROOT / "webui/src/App.svelte").read_text(encoding="utf-8")
css = (ROOT / "webui/src/app.css").read_text(encoding="utf-8")
check("the background's slow loops hold still while the window is not in front",
      'window.addEventListener("blur", away);' in app and ":root[data-away] .pool-blob," in css
      and "animation-play-state: paused !important;" in css)

poll = (ROOT / "webui/src/lib/poll.ts").read_text(encoding="utf-8")
check("a window open but not in front asks a quarter as often, and catches up once clicked",
      "const period = () => (away ? Math.max(ms * 4, 20_000) : ms);" in poll
      and 'window.addEventListener("blur", onBlur);' in poll and "if (was) fn();" in poll)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
