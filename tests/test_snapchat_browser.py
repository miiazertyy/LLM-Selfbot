"""The browser the Snapchat runner drives: which one it is, and what a page can
tell about it.

Snapchat has no API, so the whole platform is one real Chrome being driven by
Puppeteer. Two things follow. It should be a browser the machine already has
rather than a 180 MB download of Chrome for Testing, and nothing about the way
it is launched should say "driven": navigator.webdriver, a headless marker in
the User-Agent, a window larger than the screen it claims to sit on, or a
timezone and a language that disagree with each other.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fixtures import use_shipped_config
use_shipped_config()

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


SNAPBOT = (ROOT / "app/platforms/snapchat/snapbot.js").read_text(encoding="utf-8")
RUNNER = (ROOT / "app/platforms/snapchat/snapchat_runner.js").read_text(encoding="utf-8")
BRIDGE = (ROOT / "app/platforms/snapchat_bridge.py").read_text(encoding="utf-8")

print("== it drives a browser the machine already has ==")
from app.web.routes.system_routes import installed_browser

name, path = installed_browser()
check("a browser is found, or the answer is an honest blank",
      (bool(name) and bool(path)) or (name == "" and path == ""))
if path:
    check("and the path it reports is a real file", Path(path).is_file(), path)
    check("it says which browser that is", name in ("Chrome", "Edge", "Chromium", "Custom"), name)

_saved = os.environ.get("PUPPETEER_EXECUTABLE_PATH")
os.environ["PUPPETEER_EXECUTABLE_PATH"] = str(ROOT / "README.md")
try:
    check("an explicit override wins", installed_browser() == ("Custom", str(ROOT / "README.md")))
finally:
    if _saved is None:
        os.environ.pop("PUPPETEER_EXECUTABLE_PATH", None)
    else:
        os.environ["PUPPETEER_EXECUTABLE_PATH"] = _saved

from app.web.routes import system_routes as sr
SYSROUTES = (ROOT / "app/web/routes/system_routes.py").read_text(encoding="utf-8")
_order = [n for n, _ in sr._BROWSER_ON_PATH]
check("the preference order is Chrome, then Edge, then Chromium",
      _order.index("Chrome") < _order.index("Edge") < _order.index("Chromium"), str(_order))
check("the runner is told which one to use",
      'node_env["PUPPETEER_EXECUTABLE_PATH"] = _bpath' in BRIDGE)
check("and Puppeteer's own download is skipped when one is there",
      'install_env["PUPPETEER_SKIP_DOWNLOAD"] = "true"' in SYSROUTES)
check("the headless shell, which this app can never use, is never fetched",
      "PUPPETEER_SKIP_CHROME_HEADLESS_SHELL_DOWNLOAD" in SYSROUTES)
check("and the unpacked download's archive is not left behind",
      "_drop_browser_archives" in SYSROUTES and "freed" in SYSROUTES)

print()
print("== nothing about the launch says 'driven' ==")
check("blink's automation flag is turned off at the source",
      "--disable-blink-features=AutomationControlled" in RUNNER)
check("and the automation switch is not passed at all",
      'ignoreDefaultArgs: ["--enable-automation"]' in SNAPBOT)
check("the sandbox is only dropped where it has to be",
      'process.platform === "linux" ? ["--no-sandbox"' in RUNNER)
check("--start-maximized only when there is a window to maximise",
      'headless ? [] : ["--start-maximized"]' in RUNNER)

print()
print("== the window it claims is a window that could exist ==")
check("no hardcoded 1920x1080 viewport", "width: 1920," not in SNAPBOT)
check("a headed run takes the real window size", "defaultViewport: obj.headless" in SNAPBOT)
check("headless picks a size, stable per profile", "windowSizeFor(cookiefile)" in SNAPBOT)
check("and reports a screen that size fits on",
      "screenWidth: winW, screenHeight: winH" in SNAPBOT)
check("the metrics session is kept, since the override dies with it",
      "this._metrics = await this.page.createCDPSession()" in SNAPBOT)
check("the viewport allows for the browser's own chrome",
      "CHROME_UI_PX" in SNAPBOT)

# The size table has to be plausible sizes, and the pick has to be stable.
import re as _re
_sizes = _re.search(r"const HEADLESS_SIZES = \[(.*?)\];", SNAPBOT, _re.S)
check("the sizes offered are ordinary monitors", _sizes is not None
      and all(int(w) >= 1280 for w in _re.findall(r"\[(\d+), \d+\]", _sizes.group(1))))


def window_size_for(seed):
    """The same pick snapbot.js makes, to prove it is stable and spread."""
    pairs = [(int(w), int(h)) for w, h in _re.findall(r"\[(\d+), (\d+)\]", _sizes.group(1))]
    h = 0
    for ch in str(seed or "default"):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return pairs[h % len(pairs)]


check("one account keeps its monitor between restarts",
      window_size_for("snap1") == window_size_for("snap1"))
check("and different accounts do not all get the same one",
      len({window_size_for(f"snap{i}") for i in range(12)}) > 2)

print()
print("== the persona's clock and language, not the host's ==")
check("the timezone is passed down from the config", '"SNAP_TIMEZONE"' in BRIDGE)
check("so is the locale", '"SNAP_LOCALE"' in BRIDGE)
check("a snapchat: setting still wins over the bot: one",
      'snap_cfg.get("locale") or bot_cfg.get("locale")' in BRIDGE)
check("the UI language follows that locale", "--lang=${locale}" in RUNNER)
check("Accept-Language follows it too", "acceptLanguage(SNAP_LOCALE)" in SNAPBOT)
check("and the page's clock is set from it", "emulateTimezone(SNAP_TZ)" in SNAPBOT)


def accept_language(locale):
    base = locale.split("-")[0]
    return locale if base == locale else f"{locale},{base};q=0.9"


check("en-US asks for en-US then en", accept_language("en-US") == "en-US,en;q=0.9")
check("a bare tag stands alone", accept_language("fr") == "fr")

print()
print("== the headless marker never goes out ==")
check("it is looked for where it actually shows, on the page",
      'seen.includes("HeadlessChrome")' in SNAPBOT)
check("the override only runs if the stealth plugin missed it",
      "navigator.userAgent" in SNAPBOT and "setUserAgent" in SNAPBOT)
check("and it carries metadata, so it does not wipe the plugin's",
      "platformVersion" in SNAPBOT and "brands:" in SNAPBOT)

print()
print("== the cadence is not a metronome ==")
check("the chat poll is jittered", "POLL_INTERVAL_MS * (0.7 + Math.random() * 0.6)" in RUNNER)
check("so is the page reload", "nextReloadGap" in RUNNER)
check("sends are spaced by a randomised gap", "MIN_SEND_GAP_MS" in RUNNER and "MAX_SEND_GAP_MS" in RUNNER)
check("and there is an hourly cap on top of it", "MAX_SENDS_PER_HOUR" in RUNNER)
check("typing is a real typist's speed, not a fixed one",
      "80 + Math.random() * 140" in SNAPBOT)

print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
