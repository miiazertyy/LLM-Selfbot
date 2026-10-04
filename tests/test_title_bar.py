"""The top of the window: the mark and the name, the page you are on, and the buttons.

It was a plain strip: the mark, the name, the page's name in small text, and five grey icons. Now each part answers
the pointer: the mark lifts and turns towards you and bounces as it opens its page (or shakes its head when that is
off), the name catches the light, the page's icon and name come in with each page, Settings says where in it you
are with the tab a click away, and the buttons sit in two groups, the app's own and the window's, each with a motion
of its own and a word under it on hover.

The mark opens the Life Is Strange page by default; a right-click on it turns that off and on again. It used to ask
on the second click, which the right-click replaces.
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


app, css, stores = read("App.svelte"), read("app.css"), read("lib/stores.ts")

print("== the mark ==")
check("opens the page by default", 'export const logoLinkOff = persisted<boolean>("logoLinkOff", false);' in stores
      and 'const LIS = "https://en.wikipedia.org/wiki/Life_Is_Strange";' in app)
tap = app[app.index("function tapLogo()"):app.index("function setLogoLink(")]
check("a click opens it, unless that is turned off", "if ($logoLinkOff) {" in tap and 'openExternal("lifeisstrange", LIS)' in tap)
check("a right-click turns that off, and on again", "use:contextMenu={logoMenu}" in app
      and '"Stop opening it on click"' in app and '"Open it on click again"' in app and "logoLinkOff.set(!on);" in app)
check("and says so, with the switch's own sound", 'playSound(on ? "on" : "off");' in app
      and "Right-click it to turn it back on." in app)
check("the page can still be opened from the menu when the click is off", '{ label: "Open it", icon: "external"' in app)
check("no more asking on the second click", "askStop" not in app and "Stop opening it\n" not in app and "logoOpens" not in app)
check("the tooltip says what a right-click does", "Right-click to turn this off" in app and "Right-click to make it open the page again" in app)
check("it bounces as it opens the page, and shakes its head when that is off",
      'moveLogo("boing")' in app and 'moveLogo("nope")' in app and "@keyframes brand-boing" in css and "@keyframes brand-nope" in css)
check("it lights up and turns as you point at it", ".brand-mark:hover {" in css and "rotate(-8deg) scale(1.08)" in css)
check("the name catches the light, and a press on it still drags the window",
      ".brand:hover .brand-name { background-position: 0 0; }" in css
      and re.search(r"\.brand-name \{[^}]*pointer-events: none;", css, re.S))

print("\n== the page ==")
check("its icon and name, in again with each page", '{#key route}\n        <div class="page-title pywebview-drag-region">' in app
      and '<Icon name={routes[route]?.icon ?? "dashboard"} size={13} />' in app and "@keyframes page-title-in" in css)
check("the words let a press through to the strip, which drags the window", ".page-title > * { pointer-events: none; }" in css)
check("in Settings, where in it: its tab and section", "const crumbs = $derived.by(() => {" in app
      and "$settingsPath" in app and "{crumbs.sub.name}" in app)
check("the tab a click away", "onclick={() => settingsSection.set(crumbs.tab.id)}" in app)
check("no room for that in a pocket-sized window", "@media (max-width: 760px) { .crumbs { display: none; } }" in css)
check("a thread of the accent under it", ".app-header::after {" in css)

print("\n== the buttons ==")
cluster = app[app.index('<div class="fixed right-2 top-1 z-50'):app.index("<!-- Under everything")]
check("in two groups: the app's own, and the window's", cluster.count('<div class="tb-group">') == 2
      and cluster.index("{@render speaker()}") < cluster.index("onclick={toggleSize}"))
check("each says what it is under it, a moment after the pointer arrives", ".tb-btn[data-tip]:hover::after" in css
      and "transition-delay: 0.35s" in css and all(f'data-tip="{w}"' in app for w in ("Minimise", "Close")))
check("the last one's word stays inside the window", "is-close is-edge" in app and ".tb-btn.is-edge[data-tip]::after" in css)
check("not a second, native tooltip on top of it", 'title="Minimise"' not in app and 'title="Close"' not in app)
check("each its own motion: the TV lights up, the cross turns red, the line drops, the speaker pulses",
      ".tb-btn.is-bp:hover" in css and ".tb-btn.is-close:hover .tb-ico { transform: rotate(90deg); }" in css
      and ".tb-btn.is-min:hover .tb-ico" in css and "@keyframes speaker-waves" in css)
check("in a browser, the same group in the header", '{#if !desktop}' in app
      and '<div class="tb-group">\n          {@render speaker()}\n          {@render bigPictureButton()}' in app)
check("the header still leaves room for them", "pr-[176px]" in app)
check("with Animations off, nothing moves", ':root[data-motion="off"] .brand-mark.is-boing' in css
      and ':root[data-motion="off"] .page-title' in css)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
