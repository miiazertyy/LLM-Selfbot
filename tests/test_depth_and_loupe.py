"""Buttons with depth, dropdowns in the theme's colours, and a loupe on a profile picture.

Every button with a face of its own is tinted with the theme, the way Apple's
"tinted" buttons are: an even fill of the theme's own colour and nothing else.
No outline, no light on any edge, no shade at its foot, no shadow at rest:
each read as an old raised button ("legacy", three times, the last a glass
edge caught at two corners, white whatever the theme). Pointed at, the tint
deepens, a soft light of the theme sits where the pointer is and a glow of it
spreads under the button; pressed, the tint gives a little. It is drawn on a
layer behind each button's contents, in the components layer at no
specificity, so no button's own look or motion is touched, and a name you can
click stays text.

The dropdowns (the plain one, the language picker, the timezone picker) wear
the theme: a face tinted with the accent instead of a flat black one, the
caret on a disc of the accent that fills in while open, the open list rimmed
and lit in it.

An opened profile picture, held down on, shows a round loupe following the
pointer with the picture magnified in it; the wheel turns the magnification
up and down while it is held.
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


css = read("app.css")

print("== buttons with depth ==")
depth = css.split("/* ── Buttons with depth", 1)[1].split("/* A list or grid arriving", 1)[0]
lists = re.findall(r":where\(([^)]*)\)", depth)
families = [c.strip()[1:] for c in lists[0].split(",")] if lists else []
check("one list of buttons, the same in every rule", len(lists) == 6 and len(set(lists)) == 1 and len(families) > 80,
      f"{len(lists)} rules, {len(set(lists))} lists, {len(families)} families")
check("in the components layer, at no specificity: each button's own styles and utilities still win",
      "@layer components {" in depth and depth.index("@layer components {") < depth.index(":where(")
      and depth.count(":where(") == 6)
check("drawn behind its contents, on a layer of its own", "isolation: isolate;" in depth and "z-index: -1;" in depth
      and "inset: 0;" in depth and "border-radius: inherit;" in depth and "pointer-events: none;" in depth
      and "::after" not in depth)
check("an even fill of the theme's own colour",
      "linear-gradient(color-mix(in srgb, var(--color-accent) calc(8% + 5% * var(--d3-lit) - 3% * var(--d3-down)),\n"
      "                                rgb(255 255 255 / 0.035))," in depth)
check("nothing else: no outline, no light on any edge, no shade at its foot, no shadow at rest",
      "mask-composite" not in depth and "padding: 1px;" not in depth and "top / 100% 1px no-repeat" not in depth
      and "--d3-foot" not in css and "inset 0 -12px" not in depth and "box-shadow: 0 0 0 transparent;" in depth)
hard = re.findall(r"\b0 -?\d+px 0 rgb\(0 0 0[^)]*\)", depth)
check("no bevel: no hard dark line under it, no dark lip along its foot", not hard, ", ".join(hard))
check("of the theme: its fill, its light and its glow are the accent's",
      depth.count("var(--color-accent)") >= 4 and "--d3-sheen" not in css and "--d3-edge" not in css)
check("its tint and its light ease in and out: worked from registered numbers, which can be eased where a gradient cannot",
      '@property --d3-lit { syntax: "<number>"; inherits: false; initial-value: 0; }' in depth
      and '@property --d3-down { syntax: "<number>"; inherits: false; initial-value: 0; }' in depth
      and "transition: --d3-lit 0.3s var(--swift), --d3-down 0.14s var(--swift), box-shadow 0.3s var(--swift);" in depth)
feel = read("lib/feel.ts")
check("pointed at, a soft light of the theme sits where the pointer is", "at var(--mx, 50%) var(--my, -30%)" in depth
      and "color-mix(in srgb, var(--color-accent) calc(14% * var(--d3-lit)), transparent)" in depth
      and 'el.style.setProperty("--mx", `${Math.round(at.clientX - r.left)}px`);' in feel
      and 'if (e.pointerType === "touch") return;' in feel and "requestAnimationFrame(" in feel)
check("pointed at, the tint deepens and a glow of the theme spreads under it",
      ":hover:not(:disabled)::before {\n    --d3-lit: 1;" in depth
      and "box-shadow: 0 10px 26px -14px color-mix(in srgb, var(--color-accent) 45%, transparent);" in depth)
check("pressed, the tint gives a little; nothing sinks", ":active:not(:disabled)::before {\n    --d3-down: 1;" in depth
      and "inset 0 3px 6px" not in depth)
check("a disabled one lies flat", ":disabled::before { background: none; box-shadow: none; }" in depth)
check("with Animations off it changes without easing", ':root[data-motion="off"] :where(' in depth
      and "::before { transition: none; }" in depth)
check("the shared button is one of them", 'class="btn-3d jelly jelly-lift' in read("lib/components/Button.svelte")
      and "btn-3d" in families)
check("and the chips, the dropdowns, the send button, the call strip",
      {"chip", "sel-trigger", "lp-trigger", "tz-trigger", "cd-send", "ch-call", "ch-ignored-btn"} <= set(families))

texts = {p: p.read_text(encoding="utf-8") for p in SRC.rglob("*") if p.suffix in (".svelte", ".ts", ".css")}
unused = [f for f in families
          if not any(re.search(r"\b" + re.escape(f) + r"\b", t) for p, t in texts.items() if p.name != "app.css")
          and not re.search(r"(?<![\w-])\." + re.escape(f) + r"(?![\w-])", css.replace(depth, ""))]
check("every one of them is a button that exists", not unused, ", ".join(unused))
clash = []
for f in families:
    for p, t in texts.items():
        body = t.replace(depth, "") if p.name == "app.css" else t
        # The button's own ::before or ::after, not one of something inside it (".cd-toggle .cd-toggle-knob::after"),
        # and not a rule that only turns the shared layer's own numbers (an open dropdown's tint: --d3-lit: 1).
        for m in re.finditer(r"\." + re.escape(f) + r"(?![\w-])[^{};/\s>+~,]*::?(before|after)[^{]*\{([^}]*)\}", body):
            decls = [d.strip() for d in m.group(2).split(";") if d.strip()]
            if decls and all(d.startswith("--d3-") for d in decls):
                continue
            clash.append(f"{f} in {p.name}")
check("none of them draws a ::before or ::after of its own, which the layers would move", not clash, ", ".join(clash))
check("a name you can click stays text, underlined on hover, not a raised button", "user-chip" not in families
      and ".user-chip::after {" in css)

print("\n== dropdowns tinted with the theme, as Apple's pop-up buttons ==")
# 2026-11-02: a bordered box with a gradient face, a chevron on a disc of the accent filled in while open, icons in
# tiles, hints cut off and a list rimmed and lit in the accent were "legacy ugly".
sel = read("lib/components/Select.svelte")
lp = read("lib/components/LanguagePicker.svelte")
tz = read("lib/components/TimezonePicker.svelte")
mark = read("lib/components/PopupMark.svelte")


def rule(src, selector):
    return src.split(f"  {selector} {{", 1)[1].split("\n  }", 1)[0] if f"  {selector} {{" in src else ""


for name, src, trig in (("the dropdown", sel, ".sel-trigger"), ("the language picker", lp, ".lp-trigger"),
                        ("the timezone picker", tz, ".tz-trigger")):
    body = rule(src, trig)
    check(f"{name}: a button like the rest, tinted by the depth layer, with no border or face of its own",
          trig[1:] in families and "border:" not in body and "background" not in body
          and f"{trig}:hover {{" not in src)
    check(f"{name}: open, its tint stays deepened", (f"{trig}.is-open::before {{ --d3-lit: 1; }}" in src
          or f'{trig}[aria-expanded="true"]::before {{ --d3-lit: 1; }}' in src))
check("Apple's pop-up mark at the end, a chevron up over a chevron down, no disc",
      'd="M1.5 5 4.5 2 7.5 5M1.5 9 4.5 12 7.5 9"' in mark and '<span class="sel-caret" class:is-open={open}><PopupMark /></span>' in sel
      and '<PopupMark class="lp-chev" />' in lp and '<PopupMark class="tz-chev" />' in tz
      and "background: var(--color-accent); }" not in sel + lp + tz)
check("an option's icon stands as itself, not in a tile", ".sel-mark.is-icon { color: var(--color-accent); }" in sel)
check("what an option does reads in full, over up to two lines", "-webkit-line-clamp: 2;" in rule(sel, ".sel-opt-hint")
      and "text-overflow" not in rule(sel, ".sel-opt-hint"))
check("the open lists: a soft shadow, no ring of the accent or glow round them",
      rule(sel, ".sel-menu").strip().endswith("box-shadow: 0 22px 50px -20px rgb(0 0 0 / 0.7);")
      and all("border:" not in rule(s, p) and "0 0 30px -12px" not in rule(s, p) for s, p in ((lp, ".lp-pop"), (tz, ".tz-pop"))))
check("and they unroll out of the box like every menu, rather than spring",
      'class="sel-menu glass floating unroll"' in sel and 'use:unroll={".sel-opt"}' in sel
      and 'class="lp-pop unroll"' in lp and 'class="tz-pop unroll"' in tz
      and "@keyframes sel-in" not in sel and "@keyframes lp-in" not in lp and "@keyframes tz-in" not in tz)
check("the menus' material: an even fill, no sheen across the top, no line of light along it",
      "linear-gradient(180deg, rgb(255 255 255 / 0.09)" not in css and "inset 0 1px 0 rgb(255 255 255 / 0.14)" not in css)
check("their search boxes alike, with the accent's ring as they are typed in",
      all(f"{c}-search:focus-within {{ box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent); }}" in s
          for s, c in ((sel, ".sel"), (lp, ".lp"), (tz, ".tz"))))

print("\n== a loupe on a profile picture ==")
av = read("lib/components/Avatar.svelte")
check("held down on, the opened picture shows the loupe; let go, it is gone",
      av.count("onpointerdown={holdDown}") == 2 and av.count("onpointerup={holdUp}") == 2
      and av.count("onpointercancel={holdUp}") == 2 and "{#if loupe}" in av and '<div class="avatar-loupe"' in av)
check("it follows the pointer, even off the picture's edge", "img.setPointerCapture?.(e.pointerId);" in av
      and "Math.max(0, Math.min(r.width, e.clientX - r.left))" in av)
check("the picture under the pointer magnified in it, around that point",
      "width: {loupe.w * loupeZoom}px; height: {loupe.h * loupeZoom}px;" in av
      and "transform: translate({LOUPE / 2 - loupe.bx * loupeZoom}px, {LOUPE / 2 - loupe.by * loupeZoom}px)" in av)
check("a round glass, clipped to a true circle", "const LOUPE = 190;" in av and "clip-path: circle(50% at 50% 50%);" in av)
wz = av.split("function wheelZoom(node: HTMLElement) {", 1)[1].split("\n  }\n", 1)[0]
check("the wheel while it is held zooms in and out, and the page does not scroll",
      "use:wheelZoom" in av and "if (!loupe) return;" in wz and "e.preventDefault();" in wz
      and 'node.addEventListener("wheel", onWheel, { passive: false });' in wz)
check("smoothly, from 1.5x to 8x", "const MIN_ZOOM = 1.5;" in av and "const MAX_ZOOM = 8;" in av
      and "loupeZoom * Math.exp(-e.deltaY * 0.0018)" in wz and ".avatar-loupe.is-zooming img { transition:" in av)
check("the magnification said in the loupe as it changes, then gone", "{loupeZoom.toFixed(1)}×" in av
      and "}, 900);" in wz)
check("heard: lifted, a tick each half step a note higher as it goes in, put down",
      'play("lift", { level: 0.45 });' in av and 'play("release", { level: 0.4 });' in av
      and 'play("tick", { level: 0.3, p: (loupeZoom - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM) });' in wz
      and "if (n !== notch) {" in wz)
check("clicking the picture keeps it open; clicking beside it still closes it",
      av.count("onclick={(e) => e.stopPropagation()}") == 2 and "onclick={() => (open = false)}" in av)
check("and it says so, plainly", "Hold on it to look closer and scroll to zoom. Click outside it to close, right click to copy." in av)
check("the smooth scrolling leaves a wheel the loupe took", "e.defaultPrevented" in read("lib/smoothscroll.ts"))
check("with Animations off it simply appears", ':global(:root[data-motion="off"]) .avatar-loupe { animation: none; }' in av
      and ':global(:root[data-motion="off"]) .avatar-loupe img { transition: none; }' in av)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
