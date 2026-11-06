/**
 * Sign a Reddit account in: a real Chrome window at reddit.com/login, on the
 * profile the account will run in, for a person to sign in however Reddit lets
 * them (a password, a code, a passkey, Google, Apple), and to answer whatever
 * check Reddit puts up. The app never sees a password.
 *
 * Done when Reddit has given the window its session (the reddit_session
 * cookie): says which account it is ({ ok, handle }) and closes Chrome properly,
 * so the session is written into the profile. Python then files the profile
 * under that account's username (app/utils/reddit_signin.py).
 *
 * Talks to Python in JSON lines on stdout, one object per line.
 *
 * Nothing here has been seen against the real reddit.com - there was no account
 * to try it on - so whoAmI asks four different ways and takes the first that
 * answers. reddit_probe.js says which of them work.
 */
import { launchBrowser, delay } from "./browser.js";

const PROFILE = process.env.REDDIT_LOGIN_PROFILE || "";
const TIMEOUT_MS = Number(process.env.REDDIT_LOGIN_TIMEOUT_MS || 15 * 60 * 1000) || 900000;
const LOCALE = (process.env.REDDIT_LOCALE || "en-US").trim() || "en-US";

function say(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

let browser = null;
let settled = false;

function finish(result) {
  if (settled) return;
  settled = true;
  (async () => {
    // Closed before saying so: Chrome writes its cookies to the profile as it closes.
    try { await browser?.close(); } catch { /* going away anyway */ }
    say(result);
    process.exit(result.ok ? 0 : 1);
  })();
}

/**
 * Who the window is signed in as. Four ways, first one that answers:
 *   - Reddit's own /api/me.json, on the session's cookies. Still the cleanest, and still there until Reddit
 *     closes the public API in March 2027, which is why it is not the only way.
 *   - the user drawer at the top right, whose link is /user/<name>/
 *   - any /user/<name>/ link on the page that is not somebody else's post
 *   - <shreddit-app>, which carries the account on the element itself
 */
async function whoAmI(page) {
  try {
    return await page.evaluate(async () => {
      const ok = (n) => (/^[A-Za-z0-9_-]{3,20}$/.test(String(n || "")) ? String(n).toLowerCase() : "");
      try {
        const r = await fetch("https://www.reddit.com/api/me.json", { credentials: "include" });
        const d = (await r.json())?.data;
        if (ok(d?.name)) return { handle: ok(d.name) };
      } catch { /* the page's own links, below */ }
      const app = document.querySelector("shreddit-app");
      for (const attr of ["user-name", "username", "user"]) {
        if (ok(app?.getAttribute(attr))) return { handle: ok(app.getAttribute(attr)) };
      }
      const drawer = document.querySelector("#expand-user-drawer-button, [aria-label*='ccount'], #USER_DROPDOWN_ID");
      const near = drawer?.closest("*")?.querySelectorAll?.('a[href*="/user/"]') || [];
      for (const a of [...near, ...document.querySelectorAll('a[href^="/user/"], a[href*="reddit.com/user/"]')]) {
        const m = (a.getAttribute("href") || "").match(/\/user\/([A-Za-z0-9_-]{3,20})/);
        if (m && ok(m[1])) return { handle: ok(m[1]) };
      }
      return null;
    });
  } catch {
    return null;
  }
}

/** Reddit sends /user/me/ to whoever is signed in, so where it lands is the answer. */
async function whoAmIByRedirect(page) {
  try {
    await page.goto("https://www.reddit.com/user/me/", { waitUntil: "domcontentloaded", timeout: 45000 });
    const m = page.url().match(/\/user\/([A-Za-z0-9_-]{3,20})/);
    return m && m[1].toLowerCase() !== "me" ? { handle: m[1].toLowerCase() } : null;
  } catch {
    return null;
  }
}

try {
  if (!PROFILE) throw new Error("no profile to sign in on");
  say({ state: "opening", detail: "Starting the browser" });
  browser = await launchBrowser({ profileDir: PROFILE, hidden: false, locale: LOCALE, proxy: process.env.LOGIN_PROXY || "" });
  const page = (await browser.pages())[0] || (await browser.newPage());
  browser.on("disconnected", () => finish({ ok: false, reason: "The browser was closed before the sign-in finished." }));
  await page.goto("https://www.reddit.com/login/", { waitUntil: "domcontentloaded", timeout: 60000 });
  say({ state: "waiting", detail: "Sign in to Reddit in the window that opened" });
  setTimeout(() => finish({ ok: false, reason: "Timed out waiting for the sign-in. Nothing was saved." }), TIMEOUT_MS);
  while (!settled) {
    await delay(2000);
    let cookies = [];
    try { cookies = await page.cookies("https://www.reddit.com"); } catch { continue; }
    // reddit_session is the one a signed-in window gets; token_v2 rides along with it.
    if (!cookies.some((c) => (c.name === "reddit_session" || c.name === "token_v2") && c.value)) continue;
    say({ state: "checking", detail: "Signed in, finding out which account it is" });
    let me = null;
    for (let i = 0; i < 8 && !me; i++) {
      await delay(1500);
      me = await whoAmI(page);
    }
    if (!me) me = await whoAmIByRedirect(page);
    if (!me) {
      finish({ ok: false, reason: "Signed in, but Reddit would not say which account it is. Try again." });
      break;
    }
    // A moment for the session to settle before Chrome closes.
    await delay(2500);
    finish({ ok: true, handle: me.handle });
    break;
  }
} catch (err) {
  finish({ ok: false, reason: `Could not start the browser: ${err.message}` });
}
