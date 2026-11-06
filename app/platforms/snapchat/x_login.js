/**
 * Sign an X account in: a real Chrome window at x.com/login, on the profile the account will run in, for a person
 * to sign in however X lets them (a password, a code, a passkey, Google, Apple), and to answer whatever check X
 * puts up. The app never sees a password.
 *
 * It used to type the login itself, from what was stored. It does not any more: X watches for a script signing in
 * harder than for anything else an account does, and locking the account is what it does about it. A person
 * signing in is a person signing in. A password may still be saved on the Accounts page afterwards, and that is
 * what xbot.js signIn() uses months later when the session finally runs out and nobody is here.
 *
 * Done when X has given the window its session (the auth_token cookie): says which account it is
 * ({ ok, handle }) and closes Chrome properly, so the session is written into the profile. Python then files the
 * profile under that handle (app/utils/x_signin.py).
 *
 * Talks to Python in JSON lines on stdout, one object per line.
 */
import { launchBrowser, delay } from "./browser.js";

const PROFILE = process.env.X_LOGIN_PROFILE || "";
const TIMEOUT_MS = Number(process.env.X_LOGIN_TIMEOUT_MS || 15 * 60 * 1000) || 900000;
const LOCALE = (process.env.X_LOCALE || "en-US").trim() || "en-US";

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
 * Who the window is signed in as. X's own hooks first, since those outlived the rename, then any profile link:
 *   - the Profile tab in the nav rail, whose href is /<handle>
 *   - the account switcher at the bottom of it, which has the @handle in its words
 */
async function whoAmI(page) {
  try {
    return await page.evaluate(() => {
      const ok = (h) => (/^[A-Za-z0-9_]{1,15}$/.test(String(h || "")) ? String(h).toLowerCase() : "");
      const taken = new Set(["home", "explore", "notifications", "messages", "i", "settings", "search",
                             "compose", "bookmarks", "jobs", "login", "logout", "intent"]);
      const tab = document.querySelector('[data-testid="AppTabBar_Profile_Link"]');
      const href = tab?.getAttribute("href") || "";
      const m = href.match(/^\/([A-Za-z0-9_]{1,15})\/?$/);
      if (m && ok(m[1]) && !taken.has(m[1].toLowerCase())) return { handle: ok(m[1]) };
      const sw = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
      const at = (sw?.innerText || "").match(/@([A-Za-z0-9_]{1,15})/);
      if (at && ok(at[1])) return { handle: ok(at[1]) };
      for (const a of document.querySelectorAll('a[role="link"][href^="/"]')) {
        const h = (a.getAttribute("href") || "").match(/^\/([A-Za-z0-9_]{1,15})\/?$/);
        if (h && ok(h[1]) && !taken.has(h[1].toLowerCase())) return { handle: ok(h[1]) };
      }
      return null;
    });
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
  // Never networkidle on x.com: its streams never go idle.
  await page.goto("https://x.com/i/flow/login", { waitUntil: "domcontentloaded", timeout: 60000 });
  say({ state: "waiting", detail: "Sign in to X in the window that opened" });
  setTimeout(() => finish({ ok: false, reason: "Timed out waiting for the sign-in. Nothing was saved." }), TIMEOUT_MS);
  while (!settled) {
    await delay(2000);
    let cookies = [];
    try { cookies = await page.cookies("https://x.com"); } catch { continue; }
    // auth_token is the session itself; ct0 is the CSRF token that rides with it.
    if (!cookies.some((c) => c.name === "auth_token" && c.value)) continue;
    say({ state: "checking", detail: "Signed in, finding out which account it is" });
    if (!/x\.com\/(home|$)/.test(page.url())) {
      try { await page.goto("https://x.com/home", { waitUntil: "domcontentloaded", timeout: 60000 }); } catch { /* still try */ }
    }
    let me = null;
    for (let i = 0; i < 10 && !me; i++) {
      await delay(1500);
      me = await whoAmI(page);
    }
    if (!me) {
      finish({ ok: false, reason: "Signed in, but X would not say which account it is. Try again." });
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
