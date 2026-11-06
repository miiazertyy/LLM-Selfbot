/**
 * The browser the TikTok runner drives: launching Chrome on an account's own
 * profile, and the small things every page bot needs (pauses, a human typing
 * speed, the window shown or hidden).
 *
 * Kept apart from snapbot.js so TikTok has none of Snapchat's quirks, and
 * Snapchat's file is left exactly as it is. It lives in this folder because
 * Node looks for node_modules beside the script, and Puppeteer is installed
 * here (see discord_token.js, the same reason).
 *
 * "Hidden" is not headless. TikTok and Instagram look hard at headless Chrome,
 * so a hidden account keeps a real window, with Chrome told not to slow a page
 * down for being out of sight: off the screen, and made a tool window so it has
 * no taskbar button and no Alt+Tab entry either. A captcha or a lost login
 * brings the window back (showWindow) for the person to deal with.
 */
import puppeteer from "puppeteer-extra";
import Stealth from "puppeteer-extra-plugin-stealth";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

puppeteer.use(Stealth());

export function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 80-220ms a keystroke: a real typist, as in snapbot.js. */
export const typeDelay = () => 80 + Math.random() * 140;

/** The Accept-Language a browser set to `locale` would send. */
export function acceptLanguage(locale) {
  const base = String(locale).split("-")[0];
  return base === locale ? locale : `${locale},${base};q=0.9`;
}

// Ordinary laptop and desktop sizes, one picked per profile and kept: same account, same "monitor".
const SIZES = [
  [1920, 1080], [1536, 864], [1600, 900], [1440, 900],
  [1366, 768], [1680, 1050], [1280, 800], [2560, 1440],
];

export function windowSizeFor(seed) {
  let h = 0;
  for (const ch of String(seed || "default")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return SIZES[h % SIZES.length];
}

/** Chrome left holding this profile, closed (only Chrome started on it, never anyone's own; see snapbot.js). */
export function closeChromeOn(profileDir) {
  if (process.platform !== "win32" || !profileDir) return;
  const needle = String(profileDir).replace(/'/g, "''");
  const ps = "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | " +
    `Where-Object { $_.CommandLine -and $_.CommandLine.Contains('${needle}') } | ` +
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }";
  try {
    spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", ps], { windowsHide: true, timeout: 30000 });
  } catch { /* nothing to close */ }
}

/** Split http://user:pass@host:port into what Chrome and CDP each need. */
export function parseProxy(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw.includes("://") ? raw : `http://${raw}`);
    return { server: `${u.protocol}//${u.host}`, username: decodeURIComponent(u.username || ""),
             password: decodeURIComponent(u.password || "") };
  } catch {
    return { server: raw, username: "", password: "" };
  }
}

// Off the screen, where a hidden account's window waits.
//
// Not -32000,-32000: that is the very spot Windows parks a minimised window at. Just left of the desktop is out of
// sight on any ordinary arrangement of monitors, and still a window that draws.
const OFF_SCREEN = [-2400, 60];

// Off the screen was not the whole of it. The window was still one Windows listed: it kept its taskbar button and
// its Alt+Tab entry, so a hidden account did not look hidden at all next to Snapchat, which may really run
// headless. What is left is to stop Windows listing it, and the way to do that is to make it a tool window:
// WS_EX_TOOLWINDOW on, WS_EX_APPWINDOW off. The taskbar reads those when a window is shown, so it is taken down and
// put straight back up, which nothing can see from off the screen.
//
// Hiding it outright (SW_HIDE) was the obvious thing and it is wrong: the page then paints no frames at all, calls
// into it time out and a screenshot never comes back. Chrome's headless mode can leave its window hidden because it
// draws without one; a Chrome with a window will not draw while that window is hidden. A tool window is still shown
// as far as Windows is concerned, so it carries on drawing.
//
// Windows has no way to say any of this from Node, so it goes through PowerShell, as closeChromeOn does. The script
// is written out beside the profile at launch rather than shipped as a file of its own: one less file to deploy, and
// it cannot drift from the code that calls it.
const WINDOW_PS = String.raw`
param([int]$TheProcess = 0, [string]$Mode = "off")
$ErrorActionPreference = "Stop"
Add-Type @"
using System;
using System.Collections.Generic;
using System.Text;
using System.Runtime.InteropServices;
public class LlmWindow {
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool EnumWindows(EnumProc cb, IntPtr p);
  delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern uint GetWindowThreadProcessId(IntPtr h, out uint id);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr GetWindowLongPtrW(IntPtr h, int index);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SetWindowLongPtrW(IntPtr h, int index, IntPtr v);
  const int GWL_EXSTYLE = -20;
  const long WS_EX_TOOLWINDOW = 0x00000080L;
  const long WS_EX_APPWINDOW  = 0x00040000L;

  public static int Apply(HashSet<uint> pids, string mode) {
    int seen = 0;
    // Held in a local the delegate stays reachable from: a collected one is an access violation mid-enumeration.
    EnumProc cb = delegate (IntPtr h, IntPtr p) {
      uint owner = 0;
      GetWindowThreadProcessId(h, out owner);
      if (!pids.Contains(owner)) return true;
      var cls = new StringBuilder(256);
      GetClassNameW(h, cls, 256);
      if (!cls.ToString().StartsWith("Chrome_WidgetWin")) return true;
      // The browser's own frames, not the invisible helpers Chrome keeps alongside them.
      var txt = new StringBuilder(256);
      GetWindowTextW(h, txt, 256);
      if (txt.Length == 0 || !IsWindowVisible(h)) return true;
      seen++;
      long ex = GetWindowLongPtrW(h, GWL_EXSTYLE).ToInt64();
      long before = ex;
      if (mode == "off") { ex |= WS_EX_TOOLWINDOW; ex &= ~WS_EX_APPWINDOW; }
      else { ex &= ~WS_EX_TOOLWINDOW; ex |= WS_EX_APPWINDOW; }
      if (ex != before) {
        ShowWindow(h, 0);
        SetWindowLongPtrW(h, GWL_EXSTYLE, new IntPtr(ex));
        ShowWindow(h, 8);
      }
      return true;
    };
    EnumWindows(cb, IntPtr.Zero);
    GC.KeepAlive(cb);
    return seen;
  }
}
"@
# Chrome relaunches itself, so the window belongs to the process we started or to one of its children.
$want = New-Object 'System.Collections.Generic.HashSet[uint32]'
$null = $want.Add([uint32]$TheProcess)
$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId
for ($depth = 0; $depth -lt 6; $depth++) {
  foreach ($one in $all) {
    if ($want.Contains([uint32]$one.ParentProcessId)) { $null = $want.Add([uint32]$one.ProcessId) }
  }
}
[LlmWindow]::Apply($want, $Mode)
`;

let scriptPath = "";

function windowScript(beside) {
  if (scriptPath) return scriptPath;
  for (const dir of [beside ? path.dirname(beside) : "", os.tmpdir()]) {
    if (!dir) continue;
    try {
      const file = path.join(dir, "llmselfbot-window.ps1");
      fs.writeFileSync(file, WINDOW_PS, "utf-8");
      scriptPath = file;
      return file;
    } catch { /* the next place */ }
  }
  return "";
}

/**
 * This browser's windows taken out of the taskbar and out of Alt+Tab (`on` false), or put back (`on` true).
 * Returns how many windows it found, so 0 means the window is not up yet, or that none of this could run (not
 * Windows, no PowerShell). The window is off the screen either way, so an account still runs; it just keeps its
 * taskbar button.
 */
export function windowInTaskbar(browser, on) {
  if (process.platform !== "win32") return 0;
  const proc = browser && typeof browser.process === "function" ? browser.process() : null;
  if (!proc || !proc.pid) return 0;
  const file = windowScript(browser.__profileDir);
  if (!file) return 0;
  try {
    const out = spawnSync("powershell.exe",
      ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", file,
       "-TheProcess", String(proc.pid), "-Mode", on ? "on" : "off"],
      { windowsHide: true, timeout: 30000, encoding: "utf-8" });
    const said = String((out && out.stdout) || "").trim().match(/-?\d+/);
    return said ? Number(said[0]) : 0;
  } catch {
    return 0;
  }
}

/** The same, waiting for the window to turn up: just after launch it is a moment behind Chrome itself. */
export async function hideFromTaskbar(browser, tries = 4) {
  for (let attempt = 1; attempt <= tries; attempt++) {
    if (windowInTaskbar(browser, false) > 0) return true;
    if (attempt < tries) await delay(500 * attempt);
  }
  return false;
}

/**
 * Chrome on this profile. `hidden`: a real window off the screen; otherwise a normal, maximised one.
 * Tried again (up to three times) when Chrome did not start, with any Chrome left on the profile closed first.
 */
export async function launchBrowser({ profileDir, hidden = false, locale = "en-US", proxy = "", args = [] }) {
  const [w, h] = windowSizeFor(profileDir);
  const p = parseProxy(proxy);
  const options = {
    headless: false,
    userDataDir: profileDir,
    // navigator.webdriver genuinely false everywhere, workers and frames included (see snapbot.js).
    ignoreDefaultArgs: ["--enable-automation"],
    defaultViewport: null,
    args: [
      "--disable-blink-features=AutomationControlled",
      `--lang=${locale}`,
      // Hidden means silent too. Videos autoplay on these sites, and sound from a window nobody can see, with nothing
      // to close or mute, is a ghost. Only the output is muted: what a page does with audio inside itself still works.
      ...(hidden
        ? [`--window-position=${OFF_SCREEN[0]},${OFF_SCREEN[1]}`, `--window-size=${w},${h}`, "--mute-audio"]
        : ["--start-maximized"]),
      // A page out of sight is still a page in use: no slowing its timers or its frames.
      "--disable-background-timer-throttling",
      "--disable-renderer-backgrounding",
      "--disable-backgrounding-occluded-windows",
      "--disable-features=CalculateNativeWinOcclusion",
      "--autoplay-policy=no-user-gesture-required",
      ...(p ? [`--proxy-server=${p.server}`] : []),
      ...(process.platform === "linux" ? ["--no-sandbox", "--disable-setuid-sandbox"] : []),
      ...args,
    ],
  };
  for (let attempt = 1; ; attempt++) {
    try {
      const browser = await puppeteer.launch(options);
      browser.__proxyAuth = p && p.username ? { username: p.username, password: p.password } : null;
      // Chrome asks a page at a time, so each is given it as it opens: the sign-in windows, and every tab a runner opens.
      if (browser.__proxyAuth) {
        const give = async (target) => {
          try {
            const page = await target.page();
            if (page) await page.authenticate(browser.__proxyAuth);
          } catch { /* a target with no page, or one gone already */ }
        };
        browser.on("targetcreated", give);
        await Promise.all(browser.targets().map(give));
      }
      browser.__hidden = hidden;
      browser.__size = [w, h];
      browser.__profileDir = profileDir;
      // Hidden means hidden: nothing on the screen, nothing in the taskbar, nothing in Alt+Tab. It is off the
      // screen already, so failing here costs a taskbar button and nothing else.
      if (hidden && !(await hideFromTaskbar(browser))) {
        console.warn("[Browser] The window could not be taken out of the taskbar; it is off the screen only.");
      }
      return browser;
    } catch (err) {
      const msg = String((err && err.message) || err);
      // Chrome not starting, or one left on this profile (the account stopped, and its Chrome went on): the profile
      // is only ever ours, so whatever holds it is closed and it is tried again.
      if (attempt >= 3 || !/Failed to launch the browser process|browser is already running/i.test(msg)) throw err;
      console.warn(`[Browser] Chrome did not start (try ${attempt}); closing any Chrome left on this profile.`);
      closeChromeOn(profileDir);
      await delay(3000 * attempt);
    }
  }
}

/** The window this page is in, brought onto the screen (a captcha, a lost login): something a person must do. */
export async function showWindow(page) {
  try {
    // Back in the taskbar first, so the person has something to click on once it is up.
    try { windowInTaskbar(page.browser(), true); } catch { /* it was never taken out */ }
    const cdp = await page.createCDPSession();
    const { windowId } = await cdp.send("Browser.getWindowForTarget");
    await cdp.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "normal" } });
    await cdp.send("Browser.setWindowBounds", { windowId, bounds: { left: 80, top: 40 } });
    await page.bringToFront();
    await cdp.detach();
    return true;
  } catch {
    return false;
  }
}

/** And back off the screen once it is done, when the account runs hidden. */
export async function hideWindow(page) {
  try {
    const cdp = await page.createCDPSession();
    const { windowId } = await cdp.send("Browser.getWindowForTarget");
    await cdp.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "normal" } });
    await cdp.send("Browser.setWindowBounds", { windowId, bounds: { left: OFF_SCREEN[0], top: OFF_SCREEN[1] } });
    await cdp.detach();
    // Out of sight, then out of the taskbar too. Any window Chrome opened while it was up goes with it.
    await hideFromTaskbar(page.browser(), 2);
    return true;
  } catch {
    return false;
  }
}

/** The page's clock and language set to the persona's (see snapbot.js: one person, not three). */
export async function persona(page, { locale = "en-US", timezone = "" } = {}) {
  try { await page.setExtraHTTPHeaders({ "Accept-Language": acceptLanguage(locale) }); } catch { /* the default */ }
  if (timezone) {
    try { await page.emulateTimezone(timezone); } catch { /* an unknown zone keeps the machine's */ }
  }
}
