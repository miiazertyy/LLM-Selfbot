import puppeteer from "puppeteer-extra";
import Stealth from "puppeteer-extra-plugin-stealth";

puppeteer.use(Stealth());

import fs from "fs";
import fsPromise from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Writable data dir (set by the Python bridge). Cookies, browser profiles and
// downloaded media live here so a frozen app dir can stay read-only.
const DATA_DIR = process.env.SNAP_DATA_DIR || path.resolve(__dirname, "../../");

// Downloaded media (snap screenshots, voice clips) lands here; Python prunes it.
const TEMP_DIR = path.join(DATA_DIR, "config", "temp");

// Human-ish name for temp media files, e.g. snap_Alexander_1781051313957.jpg
function _safeName(name) {
  const slug = String(name || "")
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}]+/gu, "_") // letters/numbers only (drops emoji, spaces, symbols)
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  return slug || "unknown";
}
function _mediaName(prefix, name, ext) {
  return `${prefix}_${_safeName(name)}_${Date.now()}${ext}`;
}

// Verbose debug flag, only explicit "on" values enable it.
const SNAP_DEBUG = ["1", "true", "yes", "on"].includes(
  String(process.env.SNAP_DEBUG || "").toLowerCase()
);

// Scroll the virtualized chat list to enumerate chats below the fold.
const SCROLL_CHAT_LIST = String(process.env.SNAP_SCROLL_CHAT_LIST || "true").toLowerCase() !== "false";
const MAX_SCROLL_STEPS = parseInt(process.env.SNAP_MAX_SCROLL_STEPS || "40") || 40;

// Random 40–120ms per-keystroke delay, fixed delays look mechanical to Snapchat.
const typeDelay = () => 40 + Math.random() * 80;

// Console palette, matches the Python logger's Snapchat gold accent so the
// whole shared window looks cohesive and premium.
const C = {
  reset: "\x1b[0m",
  dim: "\x1b[38;2;120;120;130m",
  gold: "\x1b[38;2;255;196;37m",
  red: "\x1b[38;2;235;87;87m",
};

function delay(time) {
  return new Promise(function (resolve) {
    setTimeout(resolve, time);
  });
}

const lastTestedVersion = "v13.64.0";

// ── save-in-chat budget ──────────────────────────────────────────────────────
// Saving a message means hovering its bubble and waiting for Snapchat's hover
// toolbar to render, which cannot be done in bulk. The cost is per bubble, per
// poll, so the budget has to be small: at the old 30 bubbles x 3 attempts x 5
// waits x 90ms, a chat whose toolbar never matched spent up to ~40 seconds
// hovering on every single cycle while replies queued behind it.
const MAX_SAVE_BUBBLES = 12;   // newest bubbles considered per pass
const SAVE_ATTEMPTS = 2;       // hover retries before giving up on a bubble
const SAVE_WAITS = 4;          // toolbar polls per attempt
const SAVE_WAIT_MS = 90;       // between those polls
const SAVE_MAX_MISSES = 2;     // consecutive total misses before leaving the chat

export default class SnapBot {
  constructor() {
    this.page = null;
    this.browser = null;
    this._seenVoice = new Set(); // voice-message srcs already grabbed this session
    this._seenImage = new Set(); // inline-image keys already grabbed this session
    this._savedSigs = new Set(); // message signatures already saved-in-chat this session
    this._savedChatsInit = new Set(); // chats whose existing history we've baselined
  }
  async launchSnapchat(obj, cookiefile) {
    try {
      const options = {
        ...obj,
        // Persistent profile per account = stable fingerprint + fewer logins.
        // Lives in the writable data dir (cookies/profile are state, not code).
        userDataDir: path.join(DATA_DIR, "config", `${cookiefile}-profile`),
        // executablePath: "/usr/bin/google-chrome",  // for docker
      };
      this.browser = await puppeteer.launch(options);

      // Load saved cookies if present; first run has none, which is fine.
      let cookiesLoaded = false;
      if (cookiefile) {
        const cookiePath = path.join(DATA_DIR, "config", `${cookiefile}-cookies.json`);
        if (fs.existsSync(cookiePath)) {
          try {
            const cookies = JSON.parse(fs.readFileSync(cookiePath, "utf-8"));
            if (Array.isArray(cookies) && cookies.length) {
              await this.browser.setCookie(...cookies);
              cookiesLoaded = true;
              console.log(`[SnapBot] Loaded ${cookies.length} saved cookie(s).`);
            }
          } catch (error) {
            console.warn("[SnapBot] Could not read saved cookies:", error.message);
          }
        } else {
          console.log("[SnapBot] No saved cookies yet, will log in and save them after.");
        }
      }

      const context = this.browser.defaultBrowserContext();

      await context.overridePermissions("https://web.snapchat.com", [
        "camera",
        "microphone",
      ]);
      await context.overridePermissions("https://accounts.snapchat.com", [
        "camera",
        "microphone",
      ]);

      this.page = await context.newPage();

      // Auto-dismiss "Leave site?" dialogs so navigation never freezes.
      this.page.on("dialog", async (dialog) => {
        try { await dialog.accept(); } catch { try { await dialog.dismiss(); } catch {} }
      });

      await this.page.setViewport({
        width: 1920,
        height: 1080,
        deviceScaleFactor: 1,
      });
      // No custom User-Agent: the bundled Chromium's real UA (patched by the
      // stealth plugin) stays consistent with the actual browser fingerprint.

      // Log the Snapchat web build version so selector drift is easy to spot.
      this.page.on("console", (msg) => {
        if (msg.type() === "log") {
          const text = msg.text();
          if (text.includes("Snapchat")) {
            const version = text.match(/v\d+\.\d+\.\d+/);
            if (version) {
              console.log("Snapchat for Web Build info:", text);
              if (version[0] != lastTestedVersion) {
                console.warn(
                  `⚠️  Warning: Some methods were last tested on version ${lastTestedVersion} \n\n` +
                  `Detected current version is ${version[0]}\n\n` +
                  `Some features might not work properly.\n` +
                  `If you encounter issues, please try updating the project using 'git pull'.\n` +
                  `If the problem persists, consider raising an issue or contacting the developer.`
                );
              }
            }
          }
        }
      });

      // With cookies go straight to the app; otherwise start at the login page.
      const startUrl = cookiesLoaded
        ? "https://web.snapchat.com/"
        : "https://accounts.snapchat.com/v2/login";
      await this.page.goto(startUrl, { waitUntil: "networkidle2", timeout: 60000 });

      // Dismiss the cookie-consent modal that blocks the login form.
      await this.acceptCookies();
    } catch (error) {
      console.error(`Error while Starting Snapchat : ${error}`);
    }
  }

  async login(credentials) {
    const { username, password } = credentials;
    if (username == "" || password == "") {
      throw new Error("Credentials cannot be empty");
    }
    try {
      // Land on the dedicated login page if not already there.
      if (!this.page.url().includes("accounts.snapchat.com")) {
        try {
          await this.page.goto("https://accounts.snapchat.com/v2/login", {
            waitUntil: "networkidle2",
            timeout: 60000,
          });
        } catch { /* best effort, selectors below still try */ }
      }

      await delay(2000);
      await this.acceptCookies();

      // Try every known username-field selector.
      const possibleUsernameSelectors = [
        'input[name="accountIdentifier"]',                    // accounts.snapchat.com (current)
        '#accountIdentifier',                                 // accounts.snapchat.com id
        'input[placeholder="Username or email address"]',     // www.snapchat.com legacy
        'input[placeholder*="Username"]',                     // partial match fallback
        'input[placeholder*="email"]',                        // partial match fallback
        'input[name="username"]',                             // older alternative
        '#ai_input',                                          // older sidebar
      ];

      let usernameSelector = null;
      console.log("Waiting for username field...");

      for (const selector of possibleUsernameSelectors) {
        console.log(`Trying selector: ${selector}`);
        try {
          const element = await this.page.waitForSelector(selector, {
            visible: true,
            timeout: 10000,
          });
          if (element) {
            usernameSelector = selector;
            console.log(`✅ Found username field with selector: ${selector}`);
            break;
          }
        } catch {
          console.log(`  Selector ${selector} not found, trying next...`);
        }
      }

      if (!usernameSelector) {
        // Dump the page's inputs + a screenshot so the selector can be fixed.
        try {
          const html = await this.page.content();
          const inputs = await this.page.evaluate(() =>
            [...document.querySelectorAll("input")].map(el => ({
              type: el.type, name: el.name, id: el.id, placeholder: el.placeholder
            }))
          );
          console.log("[Debug] Current URL:", this.page.url());
          console.log("[Debug] All input fields found on page:", JSON.stringify(inputs, null, 2));
          await this.page.screenshot({ path: path.join(__dirname, "login_debug.png") });
          console.log("[Debug] Screenshot saved to platforms/snapchat/login_debug.png");
        } catch (debugErr) {
          console.log("[Debug] Could not dump debug info:", debugErr.message);
        }
        throw new Error("Could not find username input field");
      }

      console.log("Entering username...");
      await this.page.type(usernameSelector, username, { delay: typeDelay() });

      // Click the login/next button
      await delay(500);
      const submitBtn = await this.page.$('button[type="submit"]');
      if (submitBtn) {
        await submitBtn.click();
        console.log("Clicked submit button for username.");
      } else {
        await this.page.keyboard.press("Enter");
        console.log("Pressed Enter to submit username.");
      }

      await delay(3000);
    } catch (e) {
      console.log("Username field error:", e);
    }

    try {
      // The cookie modal can resurface on the password step, clear it again.
      await this.acceptCookies();

      // Wait for password field - try multiple selectors
      console.log("Waiting for password field...");
      const possiblePasswordSelectors = [
        'input[type="password"]',              // most reliable - type never changes
        'input[name="password"]',
        '#password',
        'input[placeholder*="assword"]',       // placeholder fallback
      ];

      let passwordSelector = null;
      for (const selector of possiblePasswordSelectors) {
        try {
          const element = await this.page.waitForSelector(selector, {
            visible: true,
            timeout: 20000,
          });
          if (element) {
            passwordSelector = selector;
            console.log(`Found password field with selector: ${selector}`);
            break;
          }
        } catch {
          // Try next selector
        }
      }

      if (!passwordSelector) {
        throw new Error("Could not find password input field");
      }

      await this.page.type(passwordSelector, password, { delay: typeDelay() });
      console.log("Password field filled.");

      // Click submit button for password
      await delay(500);
      const submitBtn = await this.page.$('button[type="submit"]');
      if (submitBtn) {
        await submitBtn.click();
        console.log("Clicked submit button for password.");
      } else {
        await this.page.keyboard.press("Enter");
        console.log("Pressed Enter to submit password.");
      }
    } catch (e) {
      console.log("Password field loading error:", e);
    }

    await delay(10000);

    // Handle any popup (like "Not now" for notifications)
    try {
      // Try multiple possible selectors for the dismiss button
      const possibleSelectors = [
        'button[data-testid="notifications-dismiss"]',
        'button.NRgbw.eKaL7.Bnaur',
        'button:has-text("Not now")',
      ];

      console.log("Checking for 'Not now' button...");
      for (const selector of possibleSelectors) {
        try {
          const btn = await this.page.waitForSelector(selector, {
            visible: true,
            timeout: 3000,
          });
          if (btn) {
            await btn.click();
            console.log("Clicked 'Not now' button.");
            break;
          }
        } catch {
          // Try next selector
        }
      }
    } catch (e) {
      console.log("Popup handling: no popup found or already dismissed.");
    }
    await delay(1000);
  }

  /**
   * After credentials are submitted Snapchat sometimes shows an email
   * verification step. This waits (up to `timeoutMs`) for the user to click the
   * link in their inbox, at which point the browser lands on web.snapchat.com.
   *
   * @param {number} timeoutMs  How long to wait (default 5 minutes)
   * @returns {Promise<boolean>} true if verification completed, false if timed out
   */
  async awaitEmailVerification(timeoutMs = 5 * 60 * 1000) {
    const url = this.page.url();

    // Check if we're on a verification / "check your email" interstitial.
    // Snapchat uses several URL patterns for this step.
    const onVerificationScreen =
      url.includes("accounts.snapchat.com") &&
      (url.includes("verify") ||
        url.includes("email") ||
        url.includes("check") ||
        url.includes("confirm") ||
        url.includes("unlock") ||
        // Catch-all: still on accounts domain after login attempt
        true);

    if (!onVerificationScreen) return true; // already past it

    // Also try to detect the screen by page text
    try {
      const bodyText = await this.page.evaluate(() => document.body.innerText.toLowerCase());
      const isVerifyPage =
        bodyText.includes("check your email") ||
        bodyText.includes("verify your email") ||
        bodyText.includes("confirmation email") ||
        bodyText.includes("click the link") ||
        bodyText.includes("sent you an email") ||
        bodyText.includes("vérifi") || // French
        bodyText.includes("courriel");  // French

      if (!isVerifyPage) return true; // not a verification page, nothing to wait for
    } catch {
      // page evaluate failed, just wait anyway
    }

    console.log("[Snap] 📧  Email verification required.");
    console.log("[Snap]     Open your inbox and click the link Snapchat sent you.");
    console.log(`[Snap]     Waiting up to ${timeoutMs / 1000}s for you to verify...`);

    const start = Date.now();
    const pollMs = 3000;

    while (Date.now() - start < timeoutMs) {
      await delay(pollMs);
      try {
        const currentUrl = this.page.url();
        // /v2/welcome means auth succeeded, not a pending verification
        if (currentUrl.includes("/v2/welcome") || currentUrl.includes("/welcome")) {
          console.log("[Snap] ✅  Email verification completed (welcome page detected).");
          return true;
        }
        // Redirected away from accounts domain entirely, definitely through
        if (!currentUrl.includes("accounts.snapchat.com")) {
          console.log("[Snap] ✅  Email verification detected, continuing.");
          return true;
        }
        // Print a heartbeat every 30 s so the user knows the bot is still alive
        const elapsed = Math.round((Date.now() - start) / 1000);
        if (elapsed % 30 === 0) {
          console.log(`[Snap]     Still waiting for email verification... (${elapsed}s elapsed)`);
        }
      } catch {
        // page might be navigating, ignore and retry
      }
    }

    console.error("[Snap] ❌  Timed out waiting for email verification.");
    return false;
  }

  async isLogged() {
    const url = this.page.url();

    // Auth domain → not logged in.
    if (url.includes("accounts.snapchat.com")) return false;
    if (!url.includes("snapchat.com")) return false;

    // The authenticated web app lives under snapchat.com/web/... . The marketing
    // LANDING page is snapchat.com/ (root), it has a login form and a top nav
    // whose "Chat" link (a[href*="/chat"]) used to fool the old positive check
    // into thinking we were logged in. So gate on the /web path.
    let path = "/";
    try { path = new URL(url).pathname; } catch (_) { /* ignore */ }
    const onAppPath = path.startsWith("/web");

    // A login form or the "Log in to Snapchat" landing copy → logged OUT.
    try {
      const loginInput = await this.page.$(
        'input[name="accountIdentifier"], #accountIdentifier, ' +
        'input[placeholder*="Username" i], input[placeholder*="email" i]'
      );
      if (loginInput) return false;
      if (!onAppPath) {
        const landing = await this.page
          .evaluate(() => /log in to snapchat/i.test(document.body.innerText || ""))
          .catch(() => false);
        if (landing) return false;
      }
    } catch (_) { /* mid-navigation */ }

    // Strong positive: the real conversation list / sidebar that only exist in
    // the app (NOT the marketing nav).
    try {
      const chatGrid  = await this.page.$('div.ReactVirtualized__Grid__innerScrollContainer, ul.s7loS');
      const searchBox = await this.page.$('input[data-testid="search-input"], div[role="searchbox"]');
      const sidebar   = await this.page.$('#left-sidebar-header, div[data-testid="sidebar"]');
      if (chatGrid || searchBox || sidebar) return true;
    } catch (_) { /* not ready */ }

    // On /web with no login form and the app still painting → assume logged in.
    // Anywhere else (still the marketing page) → NOT logged in.
    return onAppPath;
  }

  /**
   * Dismiss the Snapchat cookie-consent modal ("Accept All" / "Essential Only")
   * that overlays accounts.snapchat.com and web.snapchat.com on first load and
   * blocks the login form. Tries a few times since it can appear slightly late.
   */
  async acceptCookies(attempts = 4) {
    for (let i = 0; i < attempts; i++) {
      try {
        const clicked = await this.page.evaluate(() => {
          const els = [...document.querySelectorAll("button, a, [role='button']")];
          const exact = ["accept all", "essential only", "allow all", "accept", "i agree", "agree", "got it"];
          let btn = els.find((b) => exact.includes((b.textContent || "").trim().toLowerCase()));
          if (!btn) {
            btn = els.find((b) => /accept all|essential only|allow all/i.test((b.textContent || "").trim()));
          }
          if (btn) {
            btn.click();
            return (btn.textContent || "").trim();
          }
          return null;
        });
        if (clicked) {
          console.log(`[SnapBot] Dismissed cookie consent ("${clicked}").`);
          await delay(1200);
          return true;
        }
      } catch {
        /* page mid-navigation, retry */
      }
      await delay(1000);
    }
    return false;
  }

  /**
   * Decline an incoming voice/video call ("Not Now") and return the caller's
   * name + a screenshot of the call screen. Null when there's no call.
   */
  async declineIncomingCall() {
    try {
      // Detect the call + caller name WITHOUT clicking yet, so we can snapshot.
      const info = await this.page.evaluate(() => {
        const clickables = [...document.querySelectorAll("button, [role='button'], a")];
        const notNow = clickables.find((b) => {
          const t = (b.textContent || "").trim().toLowerCase();
          const a = (b.getAttribute("aria-label") || "").toLowerCase();
          return t === "not now" || t === "decline" || /not now|decline/.test(a);
        });
        if (!notNow) return null;

        // Caller name comes from a SMALL "<name> is calling…" element.
        const re = /^(.{1,32}?)\s+(?:is calling|is video calling|t['’]?appelle|vous appelle|wants to call)/i;
        let name = "";
        let bestLen = Infinity;
        for (const el of document.querySelectorAll("h1, h2, h3, span, div, p, b, strong")) {
          const txt = (el.textContent || "").trim();
          if (!txt || txt.length > 48) continue; // skip big containers
          const m = txt.match(re);
          if (m && m[1].trim() && txt.length < bestLen) {
            name = m[1].trim();
            bestLen = txt.length;
          }
        }
        return { name };
      });
      if (!info) return null;

      // Snapshot the call screen (a video call shows the caller's camera).
      let callShot = null;
      try {
        await fsPromise.mkdir(TEMP_DIR, { recursive: true });
        callShot = path.join(TEMP_DIR, _mediaName("call", info.name, ".jpg"));
        await this.page.screenshot({ path: callShot, type: "jpeg", quality: 85 });
      } catch {
        callShot = null;
      }

      // Now decline ("Not Now").
      await this.page.evaluate(() => {
        const clickables = [...document.querySelectorAll("button, [role='button'], a")];
        const notNow = clickables.find((b) => {
          const t = (b.textContent || "").trim().toLowerCase();
          const a = (b.getAttribute("aria-label") || "").toLowerCase();
          return t === "not now" || t === "decline" || /not now|decline/.test(a);
        });
        if (notNow) notNow.click();
      });

      return { name: info.name, callShot };
    } catch {
      return null;
    }
  }

  async handlePopup() {
    // The cookie-consent modal can also show on the web app after login.
    await this.acceptCookies();

    const possibleSelectors = [
      'button[data-testid="notifications-dismiss"]',
      'button.NRgbw.eKaL7.Bnaur',
    ];

    console.log("Checking for popup 'Not now' button...");
    for (const selector of possibleSelectors) {
      try {
        const btn = await this.page.waitForSelector(selector, {
          visible: true,
          timeout: 3000,
        });
        if (btn) {
          await btn.click();
          console.log("Clicked 'Not now' button.");
          return;
        }
      } catch {
        // Try next selector
      }
    }
    console.log("No popup found.");
  }

  /**
   * Dump all visible buttons to console, run this when a selector breaks
   * so you can see what classes Snapchat is using in the current version.
   */
  async debugSelectors(label = "") {
    if (!SNAP_DEBUG) return; // verbose button dump, only when debugging
    try {
      const buttons = await this.page.evaluate(() =>
        [...document.querySelectorAll("button")].map(b => ({
          class: b.className,
          text: b.innerText.trim().slice(0, 40),
          ariaLabel: b.getAttribute("aria-label"),
          dataTestid: b.getAttribute("data-testid"),
          type: b.type,
          visible: b.offsetWidth > 0 && b.offsetHeight > 0,
        })).filter(b => b.visible)
      );
      console.log(`[Debug${label ? " " + label : ""}] Visible buttons (${buttons.length}):`);
      buttons.forEach((b, i) => console.log(`  [${i}] class="${b.class}" text="${b.text}" aria="${b.ariaLabel}" testid="${b.dataTestid}"`));

      const inputs = await this.page.evaluate(() =>
        [...document.querySelectorAll("input, div[role='textbox'], [contenteditable='true']")].map(el => ({
          tag: el.tagName,
          class: el.className,
          role: el.getAttribute("role"),
          placeholder: el.getAttribute("placeholder"),
          ariaLabel: el.getAttribute("aria-label"),
          visible: el.offsetWidth > 0 && el.offsetHeight > 0,
        })).filter(el => el.visible)
      );
      console.log(`[Debug${label ? " " + label : ""}] Visible inputs/textboxes (${inputs.length}):`);
      inputs.forEach((el, i) => console.log(`  [${i}] <${el.tag}> class="${el.class}" role="${el.role}" placeholder="${el.placeholder}" aria="${el.ariaLabel}"`));
    } catch (e) {
      console.log("[Debug] Could not dump selectors:", e.message);
    }
  }

  /**
   * Open Snapchat's camera / snap composer (the full-screen capture view). The
   * camera button's CSS classes rotate every build, so we try semantic selectors,
   * then an aria-label/text heuristic, then dump candidates for tuning. Returns
   * true if something was clicked.
   */
  async _openSnapCamera(chatId) {
    // Best entry point: the camera (📷) icon on the recipient's own chat row in
    // the sidebar, clicking it opens the FULL-SCREEN snap composer aimed at them
    // (unlike the bottom-bar paperclip, which only attaches a chat picture).
    if (chatId) {
      const rowCam = await this.page.evaluate((chatId) => {
        const title = document.getElementById("title-" + chatId);
        if (!title) return false;
        const row = title.closest("div[role='listitem']") || title.closest("li") || title.parentElement;
        if (!row) return false;
        const btns = [...row.querySelectorAll('button, [role="button"]')]
          .filter((b) => b.offsetWidth > 0 && b.offsetHeight > 0 && b.querySelector("svg"));
        if (!btns.length) return false;
        // The camera icon sits at the right edge of the row.
        btns.sort((a, b) => b.getBoundingClientRect().left - a.getBoundingClientRect().left);
        btns[0].click();
        return true;
      }, chatId).catch(() => false);
      if (rowCam) return true;
    }

    const selectors = [
      'button[aria-label="Camera"]',
      'button[aria-label*="camera" i]',
      'button[aria-label*="send a snap" i]',
      'button[aria-label*="take a snap" i]',
      'button[aria-label*="new snap" i]',
      'button[aria-label*="appareil photo" i]', // FR: camera
      'button[data-testid="camera-button"]',
      'button[data-testid="new-snap-button"]',
    ];
    for (const sel of selectors) {
      try {
        const btn = await this.page.$(sel);
        if (btn) {
          const vis = await btn.evaluate((e) => e.offsetWidth > 0 && e.offsetHeight > 0);
          if (vis) { await btn.click(); return true; }
        }
      } catch { /* try next */ }
    }
    // Heuristic: any visible button whose label/title hints camera or snap, and
    // (as a last resort) the camera-shaped icon in the top bar next to the
    // new-chat button, that's the "new snap" entry point in the screenshots.
    let clicked = await this.page.evaluate(() => {
      const vis = (b) => b.offsetWidth > 0 && b.offsetHeight > 0;
      const cands = [...document.querySelectorAll('button, [role="button"]')].filter(vis);
      for (const b of cands) {
        const s = ((b.getAttribute("aria-label") || "") + " " +
                   (b.getAttribute("title") || "")).toLowerCase();
        if (/\bcamera\b|send a snap|take a snap|new snap|appareil photo/.test(s)) {
          b.click();
          return true;
        }
      }
      return false;
    });
    // Position heuristic (pinned from a live dump on v13.79): the camera is the
    // LEFTMOST unlabeled svg icon button in the chat input bar at the bottom of
    // the conversation panel (right of the sidebar). e.g. ~x:361, y:1011.
    if (!clicked) {
      clicked = await this.page.evaluate(() => {
        const H = window.innerHeight;
        const cands = [...document.querySelectorAll('button, [role="button"]')].filter((b) => {
          if (!(b.offsetWidth > 0 && b.offsetHeight > 0)) return false;
          const r = b.getBoundingClientRect();
          // bottom bar, inside the conversation panel (past the ~340px sidebar),
          // an icon button with no text label.
          return r.top > H - 150 && r.left > 330 && b.querySelector("svg") &&
                 !(b.textContent || "").trim();
        });
        if (!cands.length) return false;
        cands.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
        cands[0].click(); // leftmost = camera
        return true;
      });
    }
    if (!clicked && !this._cameraDumped) {
      // Blocks the snap-send feature, so dump candidates ONCE per session even
      // without SNAP_DEBUG, paste this so the camera button can be pinned.
      this._cameraDumped = true;
      try {
        const cands = await this.page.evaluate(() => {
          const H = window.innerHeight;
          return [...document.querySelectorAll('button, [role="button"]')]
            .filter((b) => b.offsetWidth > 0 && b.offsetHeight > 0)
            .map((b) => {
              const r = b.getBoundingClientRect();
              return {
                aria: b.getAttribute("aria-label"),
                title: b.getAttribute("title"),
                text: (b.textContent || "").trim().slice(0, 16),
                hasSvg: !!b.querySelector("svg"),
                x: Math.round(r.left), y: Math.round(r.top),
              };
            })
            // top bar or bottom (near the chat input), where a camera lives.
            .filter((b) => b.y < 170 || b.y > H - 170);
        });
        console.log("[captureSnap] ⚠️ camera button not found. Candidate buttons (top/bottom bars):");
        console.log(JSON.stringify(cands));
      } catch { /* ignore */ }
    }
    return clicked;
  }

  /**
   * Put `obj.path` into the snap composer so it sends as a real Snap. Opens the
   * camera composer, uploads the image into its file input, adds a caption.
   */
  async captureSnap(obj) {
    if (!obj || !obj.path) return false;
    try {
      // Open the camera composer; refusing to fall back to a plain chat picture.
      const opened = await this._openSnapCamera(obj.chat);
      if (!opened) {
        console.warn(
          "[captureSnap] Couldn't open the camera composer, NOT sending " +
          "(refusing to attach it to the chat as a plain picture)."
        );
        return false;
      }
      await delay(1800);

      // Upload the picture into the composer's file input.
      let uploaded = false;
      const inputs = await this.page.$$('input[type="file"]');
      for (const inp of inputs) {
        try {
          const accept = await inp.evaluate((e) => e.getAttribute("accept") || "");
          if (accept && !/image|\*/.test(accept)) continue;
          await inp.uploadFile(obj.path);
          uploaded = true;
          break;
        } catch { /* try the next input */ }
      }
      if (!uploaded) {
        console.warn("[captureSnap] Composer opened but found no file input to upload into.");
        return false;
      }
      await delay(2500); // let the preview render

      // A real Snap shows a near-fullscreen preview; a small input-bar thumbnail
      // means it landed as a plain picture, cancel, never send it.
      if (!(await this._inSnapComposer())) {
        console.warn(
          "[captureSnap] Upload became a chat picture, not a Snap - cancelling it (not sending)."
        );
        await this._cancelChatAttachment();
        return false;
      }

      // Optional caption (best-effort, composer's text overlay).
      if (obj.caption) {
        try {
          for (const sel of ["div.IbBeS", "div.IbBeS img", "img.VcjuA"]) {
            const el = await this.page.$(sel);
            if (el) { await el.click().catch(() => {}); break; }
          }
          await delay(500);
          for (const sel of ['textarea[aria-label="Caption Input"]', "textarea.B9QiX", "textarea"]) {
            const ta = await this.page.$(sel);
            if (ta) { await ta.type(obj.caption, { delay: typeDelay() }); break; }
          }
        } catch { /* caption is optional */ }
      }
      return true;
    } catch (error) {
      if (SNAP_DEBUG) console.error("[captureSnap] error:", error.message);
      return false;
    }
  }

  /**
   * True only when the near-fullscreen Snap composer is showing. A chat picture
   * attachment is a tiny thumbnail, so this returns false for it.
   */
  async _inSnapComposer() {
    return await this.page.evaluate(() => {
      const W = window.innerWidth, H = window.innerHeight;
      for (const el of document.querySelectorAll("img, canvas, video")) {
        if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) continue;
        const r = el.getBoundingClientRect();
        if (r.width > W * 0.4 && r.height > H * 0.5) return true; // fullscreen preview
      }
      return false;
    }).catch(() => false);
  }

  /**
   * Remove a pending image attachment from the chat input. Best-effort:
   * Escape, then any remove/cancel/close (X) button.
   */
  async _cancelChatAttachment() {
    try { await this.page.keyboard.press("Escape"); } catch { /* ignore */ }
    await delay(300);
    try {
      await this.page.evaluate(() => {
        const btns = [...document.querySelectorAll('button, [role="button"]')]
          .filter((b) => b.offsetWidth > 0 && b.offsetHeight > 0);
        for (const b of btns) {
          const a = ((b.getAttribute("aria-label") || "") + " " +
                     (b.getAttribute("title") || "")).toLowerCase();
          if (/^(remove|cancel|close|delete|discard)\b|supprimer|annuler|retirer|fermer/.test(a)) {
            b.click();
            return;
          }
        }
      });
    } catch { /* ignore */ }
    await delay(300);
  }

  async send(person) {
    try {
      // Step 1: Click the send button to open the recipient panel
      const possibleSendButtonSelectors = [
        // Semantic / stable
        'button[aria-label="Send"]',
        'button[data-testid="send-button"]',
        'button[aria-label*="send" i]',
        // v13.64 class names
        "button.YatIx.fGS78.eKaL7.Bnaur",
        "button[type='button'].eKaL7.Bnaur",
        "button.eKaL7.Bnaur",
      ];

      let sendButtonFound = false;
      for (const selector of possibleSendButtonSelectors) {
        try {
          const button = await this.page.waitForSelector(selector, {
            visible: true,
            timeout: 5000,
          });
          if (button) {
            await button.click();
            console.log(`✅ Clicked send button: ${selector}`);
            sendButtonFound = true;
            break;
          }
        } catch {
          // Try next selector
        }
      }

      if (!sendButtonFound) {
        console.log("⚠️ Send button not found, dumping visible buttons for debugging:");
        await this.debugSelectors("send-step");
      }

      await delay(2000);

      // Step 2: Select the recipient
      const personLower = person.toLowerCase();

      // Check if it's a category (bestfriends, groups, friends) or a specific username
      if (personLower === "bestfriends") {
        const selected = "ul.s7loS li div.Ewflr.cDeBk.A8BRr";
        const accounts = await this.page.$$(selected);
        for (const account of accounts) {
          const isVisible = await account.evaluate((el) => el.offsetWidth > 0 && el.offsetHeight > 0);
          if (isVisible) {
            await account.click();
          }
        }
        console.log("✅ Selected best friends");
      } else if (personLower === "groups") {
        const selected = "li div.RbA83";
        const accounts = await this.page.$$(selected);
        for (const account of accounts) {
          const isVisible = await account.evaluate((el) => el.offsetWidth > 0 && el.offsetHeight > 0);
          if (isVisible) {
            await account.click();
          }
        }
        console.log("✅ Selected groups");
      } else if (personLower === "friends") {
        const selected = "li div.Ewflr";
        const accounts = await this.page.$$(selected);
        for (const account of accounts) {
          const isVisible = await account.evaluate((el) => el.offsetWidth > 0 && el.offsetHeight > 0);
          if (isVisible) {
            await account.click();
          }
        }
        console.log("✅ Selected all friends");
      } else {
        // Send to a specific user by display name
        console.log(`Looking for user: "${person}"`);

        // Find all user rows
        const userRows = await this.page.$$("li div.Ewflr");
        let userFound = false;

        for (const row of userRows) {
          try {
            // Get the display name from div.RBx9s.nonIntl
            const nameElement = await row.$("div.RBx9s.nonIntl");
            if (nameElement) {
              const displayName = await nameElement.evaluate((el) => el.textContent.trim());

              // Check if this is the user we're looking for (case-insensitive)
              if (displayName.toLowerCase() === person.toLowerCase() || displayName === person) {
                // Check if visible
                const isVisible = await row.evaluate((el) => el.offsetWidth > 0 && el.offsetHeight > 0);
                if (isVisible) {
                  await row.click();
                  console.log(`✅ Selected user: "${displayName}"`);
                  userFound = true;
                  break;
                }
              }
            }
          } catch {
            // Continue to next row
          }
        }

        if (!userFound) {
          console.log(`⚠️ User "${person}" not found in the list`);
        }
      }

      await delay(1000);

      // Step 3: Click the submit/send button
      const submitButton = await this.page.$("button[type='submit']");
      if (submitButton) {
        await submitButton.click();
        console.log("✅ Snap sent!");
      } else {
        console.log("⚠️ Submit button not found");
      }

      await delay(5000);
    } catch (error) {
      console.error("Error while sending snap:", error);
    }
  }

  /**
   * Send a picture file as a Snap to a single recipient (by display name),
   * mirroring how the Discord side attaches a photo when asked for a selfie.
   * Failures are non-fatal; the text reply is sent separately.
   */
  async sendImageSnap({ name, imagePath, caption, chat }) {
    if (!imagePath) throw new Error("No image path provided");
    if (!fs.existsSync(imagePath)) throw new Error(`Image not found: ${imagePath}`);
    if (!name) throw new Error("No recipient name provided");

    // Real Snap (tap-to-view): upload the image INTO the camera composer.
    const composed = await this.captureSnap({ path: imagePath, caption: caption || "", chat });
    if (!composed) {
      throw new Error("camera composer didn't open, snap not sent");
    }
    try {
      await delay(1000);
      await this.send(name); // Send-To → select recipient → submit
    } finally {
      // Recover the app view with Escape first, a full page reload after every
      // snap looks automated. Only reload if the composer refuses to close.
      try {
        for (let i = 0; i < 2; i++) {
          await this.page.keyboard.press("Escape").catch(() => {});
          await delay(500);
          if (!(await this._inSnapComposer())) break;
        }
        if (await this._inSnapComposer()) {
          await this.page.goto("https://web.snapchat.com/", { waitUntil: "networkidle2", timeout: 60000 });
          await delay(2500);
        }
      } catch { /* best effort */ }
    }
  }

  async closeBrowser() {
    await delay(5000);
    await this.browser.close();
    console.log("Snapchat closed");
  }

  async screenshot(obj) {
    await this.page.screenshot(obj);
  }

  async logout() {
    await this.page.waitForSelector("#downshift-1-toggle-button");
    await this.page.click("#downshift-1-toggle-button");
    await this.page.click("#downshift-1-item-9");
    console.log("Logged Out");
    await delay(12000);
  }

  async wait(time) {
    return new Promise(function (resolve) {
      setTimeout(resolve, time);
    });
  }
  //beta
  async openFriendRequests() {
    await this.page.waitForSelector('button[title="View friend requests"]');
    const requests = await this.page.$('button[title="View friend requests"]');
    await requests.click();
  }

  /**
   * Open the "Added me" panel (person+ icon with pending-count badge) and accept
   * a small batch by clicking each Add button. Returns how many it added.
   */
  async addPendingFriends(maxAdds = 5) {
    // Only open when there's a numeric pending-count badge top-left.
    const opened = await this.page
      .evaluate(() => {
        for (const b of document.querySelectorAll("button")) {
          if (!(b.offsetWidth > 0 && b.offsetHeight > 0)) continue;
          const r = b.getBoundingClientRect();
          if (r.top > 130 || r.left > 420) continue; // top-left only
          if (/\b\d{1,3}\b/.test((b.textContent || "").trim())) { b.click(); return true; }
        }
        return false;
      })
      .catch(() => false);
    if (!opened) return 0;
    await delay(1500);

    // Accept a SMALL batch per pass so chatting isn't blocked for long.
    let added = 0;
    for (let pass = 0; pass < maxAdds; pass++) {
      const clicked = await this.page.evaluate(() => {
        const exact = [
          "add", "accept", "add back", "add friend",
          "ajouter", "accepter", "ajouter en retour", "ajouter l'ami",
        ];
        const btn = [...document.querySelectorAll("button, [role='button']")].find((b) => {
          if (!(b.offsetWidth > 0 && b.offsetHeight > 0)) return false;
          const t = (b.textContent || "").trim().toLowerCase();
          const a = (b.getAttribute("aria-label") || "").toLowerCase();
          return exact.includes(t) || /^(add|accept|ajouter|accepter)\b/.test(t) ||
                 /^(add|accept|ajouter|accepter)\b/.test(a);
        });
        if (btn) { btn.click(); return true; }
        return false;
      });
      if (!clicked) break;
      added++;
      await delay(400);
    }

    if (SNAP_DEBUG && added === 0) {
      // Help tune the selector: dump the visible buttons in the panel.
      try {
        const btns = await this.page.evaluate(() =>
          [...document.querySelectorAll("button, [role='button']")]
            .filter((b) => b.offsetWidth > 0 && b.offsetHeight > 0)
            .slice(0, 25)
            .map((b) => ({ text: (b.textContent || "").trim().slice(0, 24), aria: b.getAttribute("aria-label") })));
        console.log("[addFriends] panel buttons:", JSON.stringify(btns));
      } catch { /* ignore */ }
    }

    // Close the panel so the chat list is usable again.
    try { await this.page.keyboard.press("Escape"); } catch { /* ignore */ }
    await delay(500);
    return added;
  }

  async listRecipients() {
    await this.page.waitForSelector(
      "div.ReactVirtualized__Grid__innerScrollContainer"
    );
    // One $$eval for the whole list. This used to walk the rows in Node and
    // make two separate page.evaluate() round trips per row just to read an id
    // and a string, so a 50-chat list cost ~100 CDP round trips - and
    // sendMessage() calls this on every chat open and every reply.
    const data = await this.page.$$eval("div[role='listitem']", (rows) =>
      rows
        .map((row) => {
          const titleSpan = row.querySelector("span[id^='title-']");
          if (!titleSpan) return null;
          return {
            id: titleSpan.id.replace(/^title-/, ""),
            name: (titleSpan.textContent || "").trim(),
          };
        })
        .filter(Boolean)
    );

    return data;
  }

  /**
   * Like listRecipients(), but also flags which chats are unread so the caller
   * can avoid opening every conversation on every poll. Unread heuristic:
   * bold title/status, or "New Snap"/"New Chat" style status text. "Read"
   * states (Opened/Delivered/Sent) clear the flag. Set SNAP_ONLY_UNREAD=false
   * if this is too aggressive on your Snapchat build.
   */
  async listRecipientsWithUnread() {
    await this.page.waitForSelector(
      "div.ReactVirtualized__Grid__innerScrollContainer"
    );
    // The chat list is virtualized, scroll top→bottom accumulating rows by id,
    // then return to the top so the next poll starts clean.
    return await this.page.evaluate(async (doScroll, maxSteps) => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

      const inner = document.querySelector("div.ReactVirtualized__Grid__innerScrollContainer");
      let scroller = inner ? inner.closest(".ReactVirtualized__Grid") : null;
      if (!scroller) {
        // Fallback: nearest scrollable ancestor of the inner container.
        let el = inner;
        while (el && el !== document.body) {
          const oy = getComputedStyle(el).overflowY;
          if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight) { scroller = el; break; }
          el = el.parentElement;
        }
      }

      const byId = new Map();
      const collect = () => {
        for (const item of document.querySelectorAll("div[role='listitem']")) {
          const titleSpan = item.querySelector("span[id^='title-']");
          if (!titleSpan) continue;
          const id = titleSpan.id.replace(/^title-/, "");
          const name = titleSpan.textContent.trim();

          let unread = false;
          try {
            const titleWeight = parseInt(getComputedStyle(titleSpan).fontWeight) || 400;
            if (titleWeight >= 600) unread = true;

            const statusEl = item.querySelector(`#status-${id}`);
            if (statusEl) {
              const statusWeight = parseInt(getComputedStyle(statusEl).fontWeight) || 400;
              const statusText = (statusEl.textContent || "").toLowerCase();
              if (statusWeight >= 600) unread = true;
              if (/\bnew\b|received|sent you/.test(statusText)) unread = true;
              if (/opened|delivered|^sent\b|sending|tap to chat/.test(statusText)) {
                unread = false;
              }
            }
          } catch {
            unread = true; // never miss a real message
          }

          // Keep first-seen order; if any pass flags it unread, keep it unread.
          if (!byId.has(id)) byId.set(id, { id, name, unread });
          else if (unread) byId.get(id).unread = true;
        }
      };

      collect();
      if (doScroll && scroller) {
        let lastTop = -1;
        for (let i = 0; i < maxSteps; i++) {
          scroller.scrollTop = scroller.scrollTop + Math.max(1, scroller.clientHeight * 0.85);
          await sleep(200); // let virtualization render the next window
          collect();
          if (scroller.scrollTop <= lastTop + 2) break; // hit the bottom
          lastTop = scroller.scrollTop;
        }
        scroller.scrollTop = 0; // back to top for the next poll
      }
      return [...byId.values()];
    }, SCROLL_CHAT_LIST, MAX_SCROLL_STEPS);
  }

  /**
   * Find the chat text input box, tries multiple selectors to handle
   * CSS class changes across Snapchat builds.
   */
  async _findChatInput() {    const selectors = [
      // Semantic (stable across versions)
      'div[role="textbox"][aria-label*="message" i]',
      'div[role="textbox"][aria-label*="chat" i]',
      '[contenteditable="true"][aria-label*="message" i]',
      '[contenteditable="true"][aria-label*="chat" i]',
      // data-testid
      '[data-testid="message-input"]',
      '[data-testid="chat-input"]',
      // v13.64 class
      'div[role="textbox"].euyIb',
      // Broad fallback, any visible contenteditable
      '[contenteditable="true"]',
      'div[role="textbox"]',
    ];
    for (const sel of selectors) {
      try {
        const el = await this.page.waitForSelector(sel, { visible: true, timeout: 3000 });
        if (el) return el; // (no log, fires on every send, pure noise)
      } catch { /* try next */ }
    }
    return null;
  }

  /**
   * Open a chat (by id) and optionally send one or more messages into it.
   * Returns true if the chat was found and handled, false if it scrolled out
   * of the visible list. message: "" = open only; "text" = type + Enter;
   * ["a","b"] = send each in turn.
   */
  /**
   * Scroll the virtualized chat list until the conversation with `chatId` is
   * rendered (older chats below the fold aren't in the DOM until scrolled to).
   * Returns true if it became present. Already-visible chats return immediately.
   */
  async _scrollListToChat(chatId) {
    if (!SCROLL_CHAT_LIST) return false;
    return await this.page.evaluate(async (chatId, maxSteps) => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const present = () => !!document.getElementById("title-" + chatId);
      if (present()) return true;

      const inner = document.querySelector("div.ReactVirtualized__Grid__innerScrollContainer");
      let scroller = inner ? inner.closest(".ReactVirtualized__Grid") : null;
      if (!scroller) {
        let el = inner;
        while (el && el !== document.body) {
          const oy = getComputedStyle(el).overflowY;
          if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight) { scroller = el; break; }
          el = el.parentElement;
        }
      }
      if (!scroller) return present();

      scroller.scrollTop = 0;
      await sleep(150);
      let lastTop = -1;
      for (let i = 0; i < maxSteps; i++) {
        if (present()) return true;
        scroller.scrollTop = scroller.scrollTop + Math.max(1, scroller.clientHeight * 0.85);
        await sleep(200);
        if (present()) return true;
        if (scroller.scrollTop <= lastTop + 2) break; // bottom
        lastTop = scroller.scrollTop;
      }
      return present();
    }, chatId, MAX_SCROLL_STEPS);
  }

  async sendMessage(obj) {
    await this.page.waitForSelector(
      "div.ReactVirtualized__Grid__innerScrollContainer"
    );
    // Bring off-screen chats into the rendered window first.
    if (obj.chat) {
      const here = await this.page.$(`#title-${obj.chat}`).catch(() => null);
      if (!here) await this._scrollListToChat(obj.chat);
    }
    const targetId = "title-" + obj.chat;
    let matched = false;
    let typedOk = true; // for open-only calls (no message), success == matched

    // Straight to the row we want. This used to walk every listitem, making two
    // CDP round trips per row just to compare an id - about a hundred of them
    // on a 50-chat list, on every chat open and every reply. Attribute form
    // rather than #id so an id that is not a valid CSS identifier (one starting
    // with a digit, say) still selects cleanly.
    const titleSpan = await this.page
      .$(`span[id="${targetId}"]`)
      .catch(() => null);

    if (titleSpan) {
      matched = true;

      // Never re-click an already-open chat, a second click toggles it closed.
      let alreadyOpen = obj.alreadyOpen;
      if (!alreadyOpen) {
        const openCv = await this.page.$(`#cv-${obj.chat}`);
        if (openCv) alreadyOpen = true;
      }
      if (!alreadyOpen) {
        await titleSpan.click();
        await delay(600); // let the chat panel load before typing
      }

      // An empty message means "just open the chat", do NOT type or press Enter.
      const messages = Array.isArray(obj.message)
        ? obj.message
        : (typeof obj.message === "string" && obj.message !== "" ? [obj.message] : []);

      for (const msg of messages) {
        const msgBox = await this._findChatInput();
        if (msgBox) {
          await msgBox.type(`${msg}`, { delay: typeDelay() });
          await this.page.keyboard.press("Enter");
        } else {
          typedOk = false; // found the chat but couldn't actually send
          console.log("⚠️ Chat input not found, dumping debug info:");
          await this.debugSelectors("chat-input");
        }
      }

      if (obj.exit) {
        await titleSpan.click(); // go back
      }
    }

    if (!matched) {
      // Expected when a chat scrolled out of the rendered list, debug-only noise.
      if (SNAP_DEBUG) console.warn(`[SnapBot] sendMessage: chat ${obj.chat} not in the visible list.`);
      return false;
    }
    return typedOk;
  }

  /** Fast check (no open), is this chat currently rendered in the chat list? */
  async isChatVisible(chatId) {
    try {
      return await this.page.evaluate(
        (id) => !!document.getElementById("title-" + id),
        chatId
      );
    } catch {
      return false;
    }
  }

  /**
   * Type into the conversation that's already open (#cv-<id>) without touching
   * the chat list. Returns true only if the message was actually sent.
   */
  async typeInOpenChat(chatId, message) {
    try {
      const open = await this.page.$(`#cv-${chatId}`);
      if (!open) return false;
      const box = await this._findChatInput();
      if (!box) return false;
      await box.type(`${message}`, { delay: typeDelay() });
      await this.page.keyboard.press("Enter");
      return true;
    } catch {
      return false;
    }
  }

  async _clearSearch(search) {
    try {
      await search.click();
      await this.page.keyboard.down("Control");
      await this.page.keyboard.press("KeyA");
      await this.page.keyboard.up("Control");
      await this.page.keyboard.press("Backspace");
    } catch { /* ignore */ }
  }

  /**
   * Reach a chat that has scrolled out of the rendered list: type the recipient
   * name into the search box, click the EXACT name match, send, then clear the
   * search. Returns true only if the message was actually typed and sent.
   */
  async sendMessageViaSearch(name, message) {
    if (!name || !message) return false;
    let search;
    try {
      search = await this.page.$('input[role="searchbox"], input[placeholder="Search" i]');
      if (!search) return false;

      await search.click();
      await this.page.keyboard.down("Control");
      await this.page.keyboard.press("KeyA");
      await this.page.keyboard.up("Control");
      await this.page.keyboard.press("Backspace");
      await search.type(name, { delay: typeDelay() });
      await delay(1800);

      // Click ONLY an exact name match, never a fuzzy/first result.
      const opened = await this.page.evaluate((name) => {
        const want = name.trim().toLowerCase();
        // 1) Chat-list style row (title span).
        for (const it of document.querySelectorAll("div[role='listitem']")) {
          const title = it.querySelector("span[id^='title-']");
          if (title && (title.textContent || "").trim().toLowerCase() === want) {
            title.click();
            return true;
          }
        }
        // 2) Any visible element whose OWN label text is exactly the name, 
        //    click its clickable row ancestor (the search-result entry).
        for (const el of document.querySelectorAll("span, div, a")) {
          if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) continue;
          if ((el.textContent || "").trim().toLowerCase() !== want) continue;
          const row = el.closest("div[role='listitem'], li, a, [role='button'], [role='option']") || el;
          row.click();
          return true;
        }
        return false;
      }, name);

      if (!opened) {
        await this._clearSearch(search);
        return false;
      }
      await delay(1200);

      const box = await this._findChatInput();
      if (!box) {
        await this._clearSearch(search);
        return false;
      }
      await box.type(message, { delay: typeDelay() });
      await this.page.keyboard.press("Enter");
      await delay(300);
      await this._clearSearch(search);
      return true;
    } catch {
      try { if (search) await this._clearSearch(search); } catch { /* ignore */ }
      return false;
    }
  }

  /**
   * Grab an UNANSWERED voice message from the currently-open conversation and
   * save its audio bytes to a file. "Unanswered" = the <audio> comes after our
   * last reply ("Me", red border), so a session seen-set de-dupes cleanly.
   */
  async extractVoiceMessage(chatId, name) {
    let src;
    try {
      src = await this.page.evaluate((chatId) => {
        const container = document.querySelector(`#cv-${chatId}`);
        if (!container) return null;
        // Find our last reply (Me messages have the red left border).
        let lastMe = null;
        for (const b of container.querySelectorAll(".KB4Aq")) {
          try {
            if (getComputedStyle(b).borderColor === "rgb(242, 60, 87)") lastMe = b;
          } catch { /* ignore */ }
        }
        const audios = [...container.querySelectorAll("audio")].filter((a) => a.src || a.currentSrc);
        if (!audios.length) return null;
        const last = audios[audios.length - 1];
        if (lastMe) {
          const pos = lastMe.compareDocumentPosition(last);
          if (!(pos & Node.DOCUMENT_POSITION_FOLLOWING)) return null; // already answered
        }
        return last.src || last.currentSrc || null;
      }, chatId);
    } catch {
      return null;
    }
    if (!src) return null;

    // Skip if we already grabbed this clip this session (read→reply gap).
    if (this._seenVoice.has(src)) return null;
    this._seenVoice.add(src);
    if (this._seenVoice.size > 200) {
      this._seenVoice = new Set([...this._seenVoice].slice(-100));
    }

    // Fetch the audio bytes from INSIDE the page so blob: URLs resolve.
    let data;
    try {
      data = await this.page.evaluate(async (src) => {
        try {
          const r = await fetch(src);
          const bytes = new Uint8Array(await r.arrayBuffer());
          let binary = "";
          const chunk = 0x8000;
          for (let i = 0; i < bytes.length; i += chunk) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
          }
          return { b64: btoa(binary), type: r.headers.get("content-type") || "" };
        } catch {
          return null;
        }
      }, src);
    } catch {
      return null;
    }
    if (!data || !data.b64) return null;

    const extMap = {
      "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/ogg": ".ogg",
      "audio/webm": ".webm", "audio/mp4": ".m4a", "audio/aac": ".aac",
      "audio/wav": ".wav", "audio/x-wav": ".wav",
    };
    const ext = extMap[(data.type || "").split(";")[0].trim().toLowerCase()] || ".mp3";
    const dir = TEMP_DIR;
    await fsPromise.mkdir(dir, { recursive: true });
    const filePath = path.join(dir, _mediaName("voice", name, ext));
    await fsPromise.writeFile(filePath, Buffer.from(data.b64, "base64"));
    return { path: filePath, mime: data.type };
  }

  /**
   * Capture an inline image already shown in the open conversation (a shared
   * post / spotlight / attached photo, NOT a tap-to-view snap). Screenshots
   * the largest content image after our last reply. Returns path or null.
   */
  async extractInlineImage(chatId, name) {
    let info;
    try {
      info = await this.page.evaluate((chatId) => {
        const container = document.querySelector(`#cv-${chatId}`);
        if (!container) return null;
        // Our last reply (red border), only look at images after it.
        let lastMe = null;
        for (const b of container.querySelectorAll(".KB4Aq")) {
          try {
            if (getComputedStyle(b).borderColor === "rgb(242, 60, 87)") lastMe = b;
          } catch { /* ignore */ }
        }
        // Content media only, big enough to not be an avatar/emoji/sticker.
        const media = [...container.querySelectorAll("img, canvas, video")].filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width >= 120 && r.height >= 120;
        });
        if (!media.length) return null;
        const last = media[media.length - 1];
        if (lastMe) {
          const pos = lastMe.compareDocumentPosition(last);
          if (!(pos & Node.DOCUMENT_POSITION_FOLLOWING)) return null; // already answered
        }
        const r = last.getBoundingClientRect();
        return {
          key: last.src || last.currentSrc || `${Math.round(r.x)},${Math.round(r.y)},${Math.round(r.width)},${Math.round(r.height)}`,
          box: { x: r.x, y: r.y, width: r.width, height: r.height },
        };
      }, chatId);
    } catch {
      return null;
    }
    if (!info) return null;

    // Skip if we already grabbed this image this session (read→reply gap).
    if (this._seenImage.has(info.key)) return null;
    this._seenImage.add(info.key);
    if (this._seenImage.size > 200) {
      this._seenImage = new Set([...this._seenImage].slice(-100));
    }

    const dir = TEMP_DIR;
    await fsPromise.mkdir(dir, { recursive: true });
    const filePath = path.join(dir, _mediaName("img", name, ".jpg"));
    try {
      await this.page.screenshot({ path: filePath, clip: info.box, type: "jpeg", quality: 85 });
    } catch {
      return null;
    }
    return filePath;
  }

  /**
   * Cheap check: does the currently-open conversation contain an UNOPENED snap?
   * Looks for the on-screen cue ("Click to view" / "New Snap") after our last
   * reply, so we only fire the slower open+screenshot when there's something.
   */
  async hasUnopenedSnap(chatId) {
    try {
      return await this.page.evaluate((chatId) => {
        const container = document.querySelector(`#cv-${chatId}`);
        if (!container) return false;
        const cues = /click to view|tap to view|hold to view|new snap|tap to load/;
        const snapEls = [...container.querySelectorAll("div, span, li")].filter((el) => {
          if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) return false;
          return cues.test((el.textContent || "").toLowerCase());
        });
        if (!snapEls.length) return false;
        // Only count it if the snap is AFTER our last reply (red-border "Me"),
        // so once we respond we don't keep re-triggering on the same snap.
        let lastMe = null;
        for (const b of container.querySelectorAll(".KB4Aq")) {
          try {
            if (getComputedStyle(b).borderColor === "rgb(242, 60, 87)") lastMe = b;
          } catch { /* ignore */ }
        }
        const lastSnap = snapEls[snapEls.length - 1];
        if (lastMe) {
          const pos = lastMe.compareDocumentPosition(lastSnap);
          if (!(pos & Node.DOCUMENT_POSITION_FOLLOWING)) return false;
        }
        return true;
      }, chatId);
    } catch {
      return false;
    }
  }

  /**
   * Open the unopened snap in the currently-open chat, screenshot it, and return
   * the saved file path (or null). The screenshot is sent to the vision model.
   * Set SNAP_DEBUG=1 to dump candidate elements when the cue is present but no
   * clickable element matches (useful for tuning on a new Snapchat build).
   */
  async openAndScreenshotSnap(chatId, name) {
    try {
      const snapHandle = await this.page.evaluateHandle((chatId) => {
        const container = document.querySelector(`#cv-${chatId}`) || document.body;
        const cues = ["click to view", "tap to view", "hold to view", "new snap", "tap to load"];
        const matches = [...container.querySelectorAll("div, button, span, li, a")].filter((el) => {
          if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) return false;
          const t = (el.innerText || el.textContent || "").trim().toLowerCase();
          const aria = (el.getAttribute("aria-label") || "").toLowerCase();
          return cues.some((c) => t.includes(c) || aria.includes(c));
        });
        if (!matches.length) return null;
        // Smallest match = the snap bubble itself, not a big wrapper.
        matches.sort((a, b) => a.offsetWidth * a.offsetHeight - b.offsetWidth * b.offsetHeight);
        return matches[0];
      }, chatId);

      const snapElement = snapHandle && snapHandle.asElement ? snapHandle.asElement() : null;
      if (!snapElement) {
        if (SNAP_DEBUG) {
          console.log("[openSnap] Snap cue present but no clickable element matched, dumping candidates:");
          try {
            const els = await this.page.evaluate((chatId) => {
              const container = document.querySelector(`#cv-${chatId}`) || document.body;
              return [...container.querySelectorAll("div, button, span")].filter((el) => {
                const t = (el.innerText || el.getAttribute("aria-label") || "").toLowerCase();
                return el.offsetWidth > 0 && el.offsetHeight > 0 &&
                  (t.includes("snap") || t.includes("view") || t.includes("tap"));
              }).slice(0, 15).map((el) => ({
                tag: el.tagName,
                class: String(el.className).slice(0, 60),
                text: (el.innerText || "").slice(0, 40),
                aria: el.getAttribute("aria-label"),
              }));
            }, chatId);
            console.log("[openSnap] Candidates:", JSON.stringify(els, null, 2));
          } catch { /* ignore */ }
        }
        return null;
      }

      const box = await snapElement.boundingBox();
      const cx = box ? box.x + box.width / 2 : null;
      const cy = box ? box.y + box.height / 2 : null;

      // An OPENED snap takes over the screen, look for media covering most of
      // the viewport, which the conversation view never does.
      const findFullscreenMedia = () =>
        this.page.evaluate(() => {
          const minW = window.innerWidth * 0.5;
          const minH = window.innerHeight * 0.5;
          const els = [...document.querySelectorAll("canvas, video, img")];
          let best = null, bestArea = 0;
          for (const el of els) {
            if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) continue;
            const r = el.getBoundingClientRect();
            const area = r.width * r.height;
            if (r.width >= minW && r.height >= minH && area > bestArea) {
              best = { x: r.x, y: r.y, width: r.width, height: r.height };
              bestArea = area;
            }
          }
          return best;
        });

      // Try a normal click first, then a press-and-hold (some builds need it).
      const tryOpen = async (hold) => {
        try {
          if (cx == null) { await snapElement.click(); return; }
          if (hold) {
            await this.page.mouse.move(cx, cy);
            await this.page.mouse.down();
            await delay(1200);
            await this.page.mouse.up();
          } else {
            await this.page.mouse.click(cx, cy);
          }
        } catch { /* ignore */ }
      };

      // (No "opening snap" log, the runner logs the captured-snap outcome.)
      let mediaBox = null;
      for (const hold of [false, true]) {
        await tryOpen(hold);
        for (let i = 0; i < 5; i++) {
          await delay(700);
          mediaBox = await findFullscreenMedia();
          if (mediaBox) break;
        }
        if (mediaBox) break;
      }

      if (!mediaBox) {
        // The snap never opened (no fullscreen content). Do NOT screenshot the
        // conversation, that gave the AI a bogus "black snap" description.
        console.warn("[openSnap] Snap didn't open (no fullscreen content), skipping vision.");
        try { await this.page.keyboard.press("Escape"); } catch { /* ignore */ }
        return null;
      }
      await delay(800); // let the snap finish painting
      mediaBox = (await findFullscreenMedia()) || mediaBox;

      const snapDir = TEMP_DIR;
      await fsPromise.mkdir(snapDir, { recursive: true });
      const snapPath = path.join(snapDir, _mediaName("snap", name, ".jpg"));
      try {
        await this.page.screenshot({ path: snapPath, clip: mediaBox, type: "jpeg", quality: 85 });
      } catch {
        await this.page.screenshot({ path: snapPath, type: "jpeg", quality: 80 });
      }
      // (No "screenshot saved" log + full path, the runner confirms the capture.)

      // Close the viewer robustly so the follow-up send isn't blocked by it.
      for (let i = 0; i < 2; i++) {
        try {
          const close = await this.page.$('[aria-label="Close"], button[aria-label*="close" i], [data-testid="close-button"]');
          if (close) await close.click();
          else await this.page.keyboard.press("Escape");
        } catch {
          try { await this.page.keyboard.press("Escape"); } catch { /* ignore */ }
        }
        await delay(400);
      }

      return snapPath;
    } catch (err) {
      console.error("[openSnap] Error:", err.message);
      return null;
    }
  }

  async saveCookies(username) {
    try {
      const cookies = await this.browser.cookies();
      const cookiePath = path.join(DATA_DIR, "config", `${username}-cookies.json`);
      fs.writeFileSync(cookiePath, JSON.stringify(cookies, null, 2));
      console.log(`[SnapBot] Saved ${cookies.length} cookie(s) to ${cookiePath}`);
    } catch (error) {
      console.error("Error in saving cookies", error);
    }
  }

  async useCookies(username) {
    try {
      const cookiePath = path.join(DATA_DIR, "config", `${username}-cookies.json`);
      const cookies = JSON.parse(fs.readFileSync(cookiePath, "utf-8"));
      await this.browser.setCookie(...cookies);
    } catch (error) {
      console.error("Error in using cookies", error);
    }
  }

  async extractChatData(userId) {
    return await this.page.evaluate((userId) => {
      const output = [];
      const $chatList = document.querySelector(`#cv-${userId}`);
      if (!$chatList) return [];

      const listItems = $chatList.querySelectorAll("li.T1yt2");

      let currentTime = null;
      let currentConvo = { time: "", conversation: [] };

      listItems.forEach((li) => {
        const timeElem = li.querySelector("time span");
        if (timeElem) {
          if (currentTime) output.push({ ...currentConvo });
          currentTime = timeElem.textContent.trim();
          currentConvo = { time: currentTime, conversation: [] };
          return;
        }

        const messageBlocks = li.querySelectorAll("li");

        if (messageBlocks.length > 0) {
          messageBlocks.forEach((block) => {
            let sender =
              block.querySelector("header .nonIntl")?.textContent.trim() || "";

            if (!sender) {
              const borderElem = block.querySelector(".KB4Aq");
              if (borderElem) {
                const color = getComputedStyle(borderElem).borderColor;
                if (color === "rgb(242, 60, 87)") sender = "Me";
                else if (color === "rgb(14, 173, 255)") sender = "Eren Yeager";
                else sender = "Unknown";
              }
            }

            const texts = Array.from(block.querySelectorAll("span.ogn1z")).map(
              (span) => span.textContent.trim()
            );

            texts.forEach((text) => {
              if (text) currentConvo.conversation.push({ from: sender, text });
            });
          });
        } else {
          const borderElem = li.querySelector(".KB4Aq");
          let sender = "Unknown";

          if (borderElem) {
            const color = getComputedStyle(borderElem).borderColor;
            sender = color === "rgb(242, 60, 87)" ? "Me" : "Unknown";
          }

          const text = li.querySelector("span.ogn1z")?.textContent.trim();
          if (text) currentConvo.conversation.push({ from: sender, text });
        }
      });

      if (currentConvo.conversation.length > 0) {
        output.push(currentConvo);
      }

      return output;
    }, userId);
  }

  /**
   * Save every message in the open chat (#cv-<userId>) so it doesn't disappear.
   * Hover each bubble, click "Save in Chat" (matched by label, EN/FR). Only
   * messages arriving AFTER the first baseline pass are saved, clicking an
   * already-saved message would UNSAVE it.
   */
  async saveMessagesInChat(userId) {
    const container = await this.page.$(`#cv-${userId}`);
    if (!container) return 0;

    // Only the most recent bubbles, never re-hover the whole history each poll.
    let bubbles = await container.$$("li.T1yt2 li, li.T1yt2");
    if (bubbles.length > MAX_SAVE_BUBBLES) bubbles = bubbles.slice(-MAX_SAVE_BUBBLES);

    // First time we open this chat, BASELINE its existing messages: record them
    // as handled WITHOUT clicking, since we can't tell if they're already saved.
    const firstPass = !this._savedChatsInit.has(userId);

    let saved = 0;
    let misses = 0;
    for (const bubble of bubbles) {
      try {
        const txt = await bubble
          .evaluate((el) => el.querySelector("span.ogn1z")?.textContent?.trim() || "")
          .catch(() => "");
        if (!txt) continue; // not a text bubble (snap/voice/etc.)
        const sig = `${userId}:${txt.slice(0, 80)}`;
        if (this._savedSigs.has(sig)) continue; // already handled this session
        if (firstPass) { this._savedSigs.add(sig); continue; } // baseline only, don't click

        // Re-hover (resetting the pointer each time) and POLL for the hover
        // toolbar to appear, with a synthetic-event nudge.
        const findAndSave = (el) => {
          const label = (b) =>
            ((b.getAttribute("aria-label") || "") + " " +
             (b.getAttribute("title") || "") + " " +
             (b.textContent || "")).toLowerCase();
          const row = el.closest("li.T1yt2") || el;
          const scopes = [el, el.parentElement, row, row.parentElement].filter(Boolean);
          for (const scope of scopes) {
            const btns = [...scope.querySelectorAll("button, [role='button']")]
              .filter((b) => b.offsetWidth > 0 && b.offsetHeight > 0);
            // 1) Match by label first (safest).
            for (const b of btns) {
              const s = label(b);
              if (/unsave|désenregistrer|enregistré|\bsaved\b/.test(s)) return "already";
              if (/save in chat|save to chat|enregistrer dans/.test(s)) { b.click(); return "saved"; }
            }
            // 2) Fallback: the 2nd button of a small hover toolbar (user's hint),
            //    guarded so we don't click unrelated page chrome.
            if (btns.length >= 2 && btns.length <= 5) {
              const b = btns[1];
              const s = label(b);
              if (/unsave|saved|désenregistrer/.test(s)) return "already";
              b.click();
              return "saved2";
            }
          }
          return "none";
        };

        let result = "none";
        for (let attempt = 0; attempt < SAVE_ATTEMPTS && result === "none"; attempt++) {
          // Reset the pointer so the next hover re-triggers the toolbar.
          try { await this.page.mouse.move(8, 8); } catch { /* ignore */ }
          try { await bubble.hover(); } catch { /* ignore */ }
          // Nudge: fire pointer events in case the real hover didn't wake React.
          await bubble.evaluate((el) => {
            const row = el.closest("li.T1yt2") || el;
            for (const t of ["pointerover", "mouseover", "mouseenter", "mousemove"]) {
              try { row.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true })); } catch {}
            }
          }).catch(() => {});
          // Poll for the toolbar to render.
          for (let w = 0; w < SAVE_WAITS && result === "none"; w++) {
            await delay(SAVE_WAIT_MS);
            result = await bubble.evaluate(findAndSave).catch(() => "none");
          }
        }

        if (result === "saved" || result === "saved2") {
          // "saved2" (2nd toolbar button) is the normal path on builds where
          // the save icon has no label, not an anomaly.
          saved++;
          misses = 0;
          this._savedSigs.add(sig);
          await delay(110);
        } else if (result === "already") {
          misses = 0;
          this._savedSigs.add(sig); // don't keep re-checking it
        } else if (result === "none" && SNAP_DEBUG) {
          // Only dump when a real (labelled) toolbar was present but unmatched.
          const dump = await bubble
            .evaluate((el) => {
              const row = el.closest("li.T1yt2") || el;
              return [...row.querySelectorAll("button, [role='button']")]
                .filter((b) => b.offsetWidth > 0 && b.offsetHeight > 0)
                .map((b) => ({
                  aria: b.getAttribute("aria-label"),
                  title: b.getAttribute("title"),
                  text: (b.textContent || "").trim().slice(0, 20),
                }));
            })
            .catch(() => []);
          const labelled = dump.some((b) => b.aria || b.title || b.text);
          if (labelled)
            console.log("[save] no save button matched; hover buttons:", JSON.stringify(dump));
        }
        if (result === "none") {
          // Nothing matched after the full retry budget. On a Snapchat build
          // whose hover toolbar this selector does not recognise, that is the
          // outcome for EVERY bubble - and paying the whole budget for each of
          // them turned one chat into tens of seconds of hovering and sleeping,
          // every poll, while replies queued behind it. A couple of misses in a
          // row is enough to conclude the toolbar is not matchable right now,
          // so give up on this chat until the next cycle. A build where saving
          // works never gets here, because the first bubble succeeds.
          if (++misses >= SAVE_MAX_MISSES) {
            if (SNAP_DEBUG)
              console.log(`[save] giving up on ${userId} this cycle after ${misses} misses`);
            break;
          }
        }
      } catch { /* ignore this bubble */ }
    }
    if (firstPass) this._savedChatsInit.add(userId); // baseline recorded
    return saved;
  }

  async userStatus() {
    await this.page.waitForSelector(
      "div.ReactVirtualized__Grid__innerScrollContainer"
    );
    const lists = await this.page.$$("div[role='listitem']");
    const data = [];

    for (const listItem of lists) {
      const titleSpan = await listItem.$("span[id^='title-']");
      if (titleSpan) {
        const id = await this.page.evaluate((el) => el.id, titleSpan);
        const name = await this.page.evaluate(
          (el) => el.textContent.trim(),
          titleSpan
        );

        // Get the status span container using the ID
        const cleanedID = id.replace(/^title-/, "");
        const statusContainer = await listItem.$(`#status-${cleanedID}`);
        const statusParent = statusContainer
          ? await this.page.evaluateHandle(
            (el) => el.parentElement,
            statusContainer
          )
          : null;
        let status = [];

        if (statusParent) {
          const statusSpans = await statusParent.$$("span");
          status = await Promise.all(
            statusSpans.map((span) =>
              this.page.evaluate((el) => el.textContent.trim(), span)
            )
          );
        }
        let cleanedStatus = [
          ...new Set(
            status
              .map((text) => text?.trim())
              .filter((text) => text && text !== "·")
          ),
        ];

        let structuredStatus = {
          type: cleanedStatus[0] || null,
          time: cleanedStatus[1] || null,
          streak: cleanedStatus[2] || null,
        };

        data.push({ id: cleanedID, name, status: structuredStatus });
      }
    }
    return data;
  }

  async blockTypingNotifications(shouldBlock) {
    const client = await this.page.createCDPSession();

    await client.send("Fetch.enable", {
      patterns: [
        {
          urlPattern: "*SendTypingNotification*",
          requestStage: "Request",
        },
      ],
    });

    client.on("Fetch.requestPaused", async (event) => {
      const url = event.request.url;

      if (
        shouldBlock &&
        url.includes(
          "https://web.snapchat.com/messagingcoreservice.MessagingCoreService/SendTypingNotification"
        )
      ) {
        // console.log("[CDPBlock] Aborting request:", url);
        await client.send("Fetch.failRequest", {
          requestId: event.requestId,
          errorReason: "Failed",
        });
      } else {
        await client.send("Fetch.continueRequest", {
          requestId: event.requestId,
        });
      }
    });
  }

  //select
  async useShortcut(shortcutsArray) {
    const button = await this.page.$("button.YatIx.fGS78.eKaL7.Bnaur");
    if (button) {
      console.log("Send Button found!");
      await button.click();
    } else {
      console.log("Send Button not found.");
    }
    await delay(2000);
    for (const emoji of shortcutsArray) {
      const clicked = await this.page.$$eval(
        "div.THeKv button",
        (buttons, emoji) => {
          const btn = buttons.find((b) => b.textContent.trim() === emoji);
          if (btn) {
            btn.click();
            //now press the select
            return true;
          }
          return false;
        },
        emoji
      );

      if (clicked) {
        await this.page.waitForSelector("button.Y7u8A");
        await this.page.click("button.Y7u8A");
        const reclick = await this.page.$$eval(
          "div.THeKv button",
          (buttons, emoji) => {
            const btn = buttons.find((b) => b.textContent.trim() === emoji);
            if (btn) {
              btn.click();
              return true;
            }
            return false;
          },
          emoji
        );
      }
      if (!clicked) {
        console.warn(`Shortcut "${emoji}" not found.`);
      }
    }
    //send button

    const sendButton = await this.page.$("button[type='submit']");
    await sendButton.click();
  }

  // add custom methods
  static extend(methods) {
    Object.assign(SnapBot.prototype, methods);
  }
}
