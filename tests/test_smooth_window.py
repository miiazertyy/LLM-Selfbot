"""The window stays smooth (2026-10-31).

The panel froze now and then. Measured in the app's own window: it draws on the laptop's integrated graphics, the
screen runs at 143Hz, and the backgrounds that move forever (the aurora, the Dashboard's pool, Big Picture's
blooms) were layers wider than the screen blurred 70-110px, redrawn blur and all 143 times a second: the graphics
process alone used well over a whole core and the panel stuttered with it. Now nothing that moves is blurred (the
blur's falloff is drawn into the gradients), the slow drifts step about fifteen times a second through eased frames
in between, and the ambient loops hold still once nobody has touched the window for a minute and a half.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def styles(text, svelte=False):
    """A file's CSS without its comments: a .css file whole, a .svelte file's <style>."""
    if svelte:
        text = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def rules(css):
    """(selectors, declarations) for every innermost rule."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield [s.strip() for s in m.group(1).split(",")], m.group(2)


def big_blur(decls):
    return any(float(v) >= 30 for v in re.findall(r"filter:[^;]*?blur\(([\d.]+)px\)", decls))


def forever(decls):
    return bool(re.search(r"animation(?:-iteration-count)?:[^;]*\binfinite\b", decls))


def keyframe_offsets(css, name):
    """The offsets (0-100) a @keyframes block names, with the implicit ends."""
    i = css.index(f"@keyframes {name} {{")
    depth, j = 0, css.index("{", i)
    for k in range(j, len(css)):
        depth += {"{": 1, "}": -1}.get(css[k], 0)
        if depth == 0:
            body = css[j + 1:k]
            break
    offsets = {0.0, 100.0}
    for sel, _ in rules(body):
        for s in sel:
            offsets.add({"from": 0.0, "to": 100.0}[s] if s in ("from", "to") else float(s.rstrip("%")))
    return sorted(offsets)


app_css = read("app.css")
dash = read("pages/Dashboard.svelte")
bpb = read("lib/bigpicture/BPBackdrop.svelte")
app = read("App.svelte")

print("== nothing that moves is blurred ==")
aurora = between(app_css, "/* Aurora:", "/* Nebula:")
check("the aurora's blooms carry no blur", "filter:" not in styles(aurora))
check("their softness is drawn into the gradients, stop by stop",
      aurora.count("color-mix(in srgb, var(--color-accent) ") >= 6 and aurora.count("transparent 90%)") == 2)
nebula = between(app_css, "/* Nebula:", "/* Ripple:")
check("the nebula's sweep carries none either; a mask fades its middle",
      "filter:" not in styles(nebula) and "mask-image: radial-gradient(" in nebula)
pool = between(dash, "  .pool-blob {", "@keyframes pool-drift-a")
check("the Dashboard's pool, none", "filter:" not in styles(pool))
check("its glow drawn on a layer half as big again, so it reaches as far",
      "inset: -25%;" in pool and "radial-gradient(circle closest-side," in pool)
blooms = between(bpb, "  .bpb-aurora i {", "@keyframes bpb-d1")
check("Big Picture's blooms, none", "filter:" not in styles(blooms))
art = between(bpb, "  .bpb-art {", "  }")
check("and the blurred picture under them holds still", "animation:" not in art and "@keyframes bpb-breathe" not in bpb)

print("\n== nor anything else, anywhere in the panel ==")
offenders = []
for path in sorted(SRC.rglob("*")):
    if path.suffix not in (".css", ".svelte"):
        continue
    css = styles(path.read_text(encoding="utf-8"), path.suffix == ".svelte")
    found = list(rules(css))
    blurred = {s for sels, d in found if big_blur(d) for s in sels}
    moving = {s for sels, d in found if forever(d) for s in sels}
    for sels, d in found:
        if big_blur(d) and forever(d):
            offenders.append(f"{path.name}: {sels[0]}")
    for b in blurred:
        for m in moving:
            if m == b or m.startswith((b + ".", b + ":", b + "[")):
                offenders.append(f"{path.name}: {m} (blurred as {b})")
check("no layer blurred 30px or more moves forever", not offenders, "; ".join(sorted(set(offenders))))

print("\n== the slow drifts step about fifteen times a second ==")
sources = {"app.css": styles(app_css), "Dashboard.svelte": styles(dash, True), "BPBackdrop.svelte": styles(bpb, True)}
slow = {"aurora-a", "aurora-b", "nebula-spin", "pool-drift-a", "pool-drift-b", "pool-drift-c",
        "bpb-d1", "bpb-d2", "bpb-d3", "bpb-d4", "halo-breathe", "dot-pulse"}
seen, off = set(), []
for name, css in sources.items():
    for anim, dur, n in re.findall(r"animation:\s*([\w-]+)\s+([\d.]+)s\s+steps\((\d+)\)\s+infinite", css):
        if anim not in slow:
            continue
        seen.add(anim)
        offsets = keyframe_offsets(css, anim)
        for a, b in zip(offsets, offsets[1:]):
            rate = int(n) / (float(dur) * (b - a) / 100)
            if not 10 <= rate <= 20:
                off.append(f"{anim} {dur}s steps({n}) {a}-{b}%: {rate:.1f}/s")
check("every slow loop is stepped", seen == slow, f"not stepped: {sorted(slow - seen)}")
check("at ten to twenty a second, in every part of the way", not off, "; ".join(off))
for name in ("aurora-a", "pool-drift-a", "bpb-d1"):
    css = next(c for c in sources.values() if f"@keyframes {name} {{" in c)
    check(f"{name} keeps its ease: frames every eighth of the way",
          keyframe_offsets(css, name) == [0, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100])
ring = between(app_css, "@keyframes ring-out {", "\n}")
check("the ripple's rings too, each part of the way in its own steps",
      ring.count("animation-timing-function: steps(") == 3)

print("\n== the window rests when nobody is there ==")
back = between(app, "const back = () => {", "};")
check("a minute and a half untouched counts as away, focused or not (a pointer only crossing it wakes it too)",
      "const IDLE_MS = 90_000;" in app and "idle = window.setTimeout(away, IDLE_MS);" in back and "hasFocus" not in back)
check("a move, click, key, wheel or touch brings it back, noticed once a second at most",
      'const INPUT = ["pointermove", "pointerdown", "keydown", "wheel", "touchstart"] as const;' in app
      and "for (const e of INPUT) window.addEventListener(e, touched, { passive: true });" in app
      and "if (now - lastTouch < 1000) return;" in app)
check("and every listener is taken off again", "for (const e of INPUT) window.removeEventListener(e, touched);" in app)
away = between(app_css, ":root[data-away] .app-backdrop::before,", "}")
check("away, the backgrounds, the pool and the rings hold still",
      all(s in away for s in (".app-backdrop::after", ".app-backdrop *", ".pool-blob", ".halo::before"))
      and "animation-play-state: paused !important;" in away)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
