"""A round of polish, each asked for: the echo round the local server only while it works, Settings' subtabs as one
strip with a gliding highlight, text fields as wells, the notes at the foot of pages, the background, the panels and
the typeface changing the way a theme does, and the Snapchat setup card filling as one timeline with its finish.
"""
import asyncio
import io
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== the echo round the local server: only while it works ==")
import httpx  # noqa: E402
from app.utils import usage  # noqa: E402
import app.core.launcher as launcher  # noqa: E402

real_under, launcher.under_panel = launcher.under_panel, lambda: True
out, real_stdout = io.StringIO(), sys.stdout
sys.stdout = out
try:
    req = httpx.Request("POST", "http://127.0.0.1:11434/v1/chat/completions", json={"model": "qwen", "messages": []})
    usage.work("local", req, "r1", True)
    usage.work("local", req, "r1", False)
finally:
    sys.stdout = real_stdout
    launcher.under_panel = real_under
# split("\n"), not splitlines(): the mark's \x1e is a line break to splitlines.
lines = [l for l in out.getvalue().split("\n") if l.startswith(usage.WORK_MARK)]
evts = [json.loads(l[len(usage.WORK_MARK):]) for l in lines]
check("a request to a model says it has started, and ended", [e["state"] for e in evts] == ["start", "end"]
      and all(e["provider"] == "local" and e["model"] == "qwen" and e["rid"] == "r1" for e in evts), out.getvalue()[:300])
src = (ROOT / "app" / "utils" / "usage.py").read_text(encoding="utf-8")
check("from the HTTP client itself, for every request counted", 'work(provider, request, rid, True)' in src
      and 'work(provider, response.request, rid, False)' in src)

from app.web import supervisor as sup  # noqa: E402
import app.web.logbus as logbus  # noqa: E402

SANDBOX = Path(tempfile.mkdtemp(prefix="polish_"))
(SANDBOX / "logs").mkdir()
logbus.LOGS_DIR = SANDBOX / "logs"
logbus.bus.file_path = SANDBOX / "logs" / "app.jsonl"


async def pipe():
    q = logbus.bus.subscribe()
    child = sup.Child(child_id="discord_1", role="discord", account=1, label="Discord #1")
    child.proc = types.SimpleNamespace(stdout=iter([sup.WORK_MARK + json.dumps(evts[0]) + "\n", "a line\n"]))
    sup.Supervisor._read_output(sup.Supervisor.__new__(sup.Supervisor), child)
    await asyncio.sleep(0.05)
    got = []
    while not q.empty():
        got.append(q.get_nowait())
    logbus.bus.unsubscribe(q)
    return got


got = asyncio.run(pipe())
work = [g for g in got if g.get("source") == "_event" and g.get("kind") == "work"]
check("the panel passes it on to the pages, as its own kind, never as an answer counted",
      len(work) == 1 and work[0]["event"]["state"] == "start" and work[0]["event"]["target"] == "discord_1"
      and not any(g.get("kind") == "model" for g in got), json.dumps(got)[:300])
mu = read("lib/modelusage.ts")
check("the page keeps what is under way, and lets go of one that never ends", 'subscribeEvents("work"' in mu
      and "WORK_LIMIT_MS = 120_000" in mu and "export const busyOn" in mu)
lc = read("lib/components/LocalAI.svelte")
check("the echo only while the server is at work, a moment after so a quick one is seen",
      ".lc-hero.is-good.is-busy .lc-logo::after" in lc and 'busyOn($working, "local")' in lc
      and "class:is-busy={atWork && s.running}" in lc and "setTimeout(() => (atWork = false), 1400)" in lc)

print("\n== Settings' subtabs ==")
st, css = read("pages/Settings.svelte"), read("app.css")
check("one strip, the highlight gliding to the one you are on", "use:glide={path}" in st
      and '<span class="glide-mark settings-sub-glide" aria-hidden="true"></span>' in st and (SRC / "lib" / "glide.ts").is_file())
check("in a soft well, the highlight springing across", ".settings-subs {\n  position: relative;" in css
      and "transform: translate(var(--gx, 0), var(--gy, 0));" in css and "transition: transform 0.46s var(--spring)" in css)
check("there at once the first time, not travelling in from the corner", 'mark.classList.add("is-snap")' in read("lib/glide.ts"))
check("the icon pops as it is chosen", ".settings-sub.is-active :is(svg) {\n  color: var(--color-accent);\n  animation: icon-pop" in css)

print("\n== text fields ==")
check("a well set into the panel, the caret in the accent", "caret-color: var(--color-accent);" in css
      and "inset 0 1px 2px rgb(0 0 0 / 0.35)" in css)
check("lit when it has the cursor: a soft ring and a glow", ".field:focus {" in css
      and "0 0 0 3px color-mix(in srgb, var(--color-accent) 18%, transparent)" in css)
check("numbers the same as words", ".num-field:focus-within {" in css and ".num-field input { caret-color: var(--color-accent); }" in css)

print("\n== the notes at the foot of pages ==")
fn = read("lib/components/FootNote.svelte")
check("a soft strip with an icon, not a faint line", 'class="fn {cls}"' in fn and "fn-icon" in fn)
for rel in ("pages/Settings.svelte", "lib/components/SnapchatSetup.svelte", "lib/components/EnvEditor.svelte",
            "lib/components/UsagePanel.svelte", "lib/components/KeyList.svelte", "pages/System.svelte", "pages/Memory.svelte"):
    check(f"{rel.split('/')[-1]}", "<FootNote" in read(rel))
check("the old faint line is gone from Settings", '<p class="mt-6 text-[11px] text-faint">' not in st)

print("\n== the background, the panels and the typeface change like a theme ==")
sweep, ap = read("lib/themesweep.ts"), read("lib/components/Appearance.svelte")
check("one reveal for any change to how the app looks", "export function revealChange(apply: () => void" in sweep
      and "await tick();" in sweep and 'play("hover", { level: 0.85 });' in sweep)
check("the theme goes through it as before", "revealChange(() => {\n    applyTheme(id);\n    themeId.set(id);" in sweep)
check("the background, the panels and the typeface too", "revealChange(() => backdropId.set(id))" in ap
      and "revealChange(() => surfaceId.set(id))" in ap and "revealChange(() => fontId.set(id)" in ap
      and "document.fonts.load(" in ap)
check("each from the card clicked", ap.count("onclick={() => pick") == 4)

print("\n== the Snapchat setup card ==")
sn = read("lib/components/SnapchatSetup.svelte")
check("each part lights in turn: its segment fills, its tick pops", ".sn-seg.is-lit::before { transform: scaleX(1); }" in sn
      and ".sn-step.is-lit .sn-mark {" in sn and "class:is-lit={s.done && lit[s.name]}" in sn)
check("the count counts up as they light", "{#key litCount}<b class=\"sn-count\">{litCount}/4</b>{/key}" in sn)
check("the finish, with the bell: a shine along the bar, Ready springs up, the ghost hops",
      ".sn-hero.is-complete .sn-shine" in sn and ".sn-hero.is-complete .sn-ready" in sn and ".sn-hero.is-complete .sn-ghost" in sn
      and "class:is-complete={complete && doneCount === 4}" in sn)
check("nothing moves before the card has landed (a segment used to sit as a small square)",
      "@keyframes sn-fill" not in sn and "animation-delay: calc(var(--i) * 90ms)" not in sn)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
