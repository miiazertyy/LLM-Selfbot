/**
 * Sign an Instagram account in: a real Chrome window at instagram.com/accounts/login, on the profile the account
 * will run in, for a person to sign in however Instagram lets them (a password, a code, a passkey, Facebook), and
 * to answer whatever check it puts up. The app never sees a password.
 *
 * It used to type the login itself, from what was stored. It does not any more: Instagram treats a scripted login
 * as the thing to act on, and the account that gets acted on here was suspended for it. A person signing in is a
 * person signing in. A password may still be saved on the Accounts page afterwards, and that is what
 * instagrambot.js signIn() uses months later when the session finally runs out and nobody is here.
 *
 * Done when Instagram has given the window its session (the sessionid cookie): says which account it is
 * ({ ok, handle }) and closes Chrome properly, so the session is written into the profile. Python then files the
 * profile under that username (app/utils/instagram_signin.py).
 *
 * Talks to Python in JSON lines on stdout, one object per line.
 */
import { launchBrowser, delay } from "./browser.js";

const PROFILE = process.env.INSTAGRAM_LOGIN_PROFILE || "";
const TIMEOUT_MS = Number(process.env.INSTAGRAM_LOGIN_TIMEOUT_MS || 15 * 60 * 1000) || 900000;
const LOCALE = (process.env.INSTAGRAM_LOCALE || "en-US").trim() || "en-US";

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
 * Who the window is signed in as. Three ways, first one that answers:
 *   - the form behind Edit profile, which is the one place Instagram states the username outright
 *   - the profile link in the nav bar, whose href is /<username>/
 *   - any profile link with the account's own avatar in it
 */
async function whoAmI(page) {
  try {
    return await page.evaluate(async () => {
      const ok = (h) => (/^[A-Za-z0-9._]{1,30}$/.test(String(h || "")) ? String(h).toLowerCase() : "");
      const taken = new Set(["explore", "reels", "direct", "accounts", "p", "stories", "about", "legal",
                             "privacy", "emails", "challenge", "api", "graphql"]);
      try {
        const r = await fetch("/api/v1/accounts/edit/web_form_data/",
                              { credentials: "include", headers: { "x-ig-app-id": "936619743392459" } });
        const name = (await r.json())?.form_data?.username;
        if (ok(name)) return { handle: ok(name) };
      } catch { /* the page's own links, below */ }
      const nav = document.querySelector('a[href^="/"][role="link"] img[alt*="profile picture"]')?.closest("a");
      const links = nav ? [nav, ...document.querySelectorAll('a[href^="/"]')]
                        : [...document.querySelectorAll('a[href^="/"]')];
      for (const a of links) {
        const m = (a.getAttribute("href") || "").match(/^\/([A-Za-z0-9._]{1,30})\/$/);
        if (m && ok(m[1]) && !taken.has(m[1].toLowerCase())) return { handle: ok(m[1]) };
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
  await page.goto("https://www.instagram.com/accounts/login/", { waitUntil: "domcontentloaded", timeout: 60000 });
  say({ state: "waiting", detail: "Sign in to Instagram in the window that opened" });
  setTimeout(() => finish({ ok: false, reason: "Timed out waiting for the sign-in. Nothing was saved." }), TIMEOUT_MS);
  while (!settled) {
    await delay(2000);
    let cookies = [];
    try { cookies = await page.cookies("https://www.instagram.com"); } catch { continue; }
    if (!cookies.some((c) => c.name === "sessionid" && c.value)) continue;
    say({ state: "checking", detail: "Signed in, finding out which account it is" });
    if (!/instagram\.com\/?($|\?)/.test(page.url())) {
      try {
        await page.goto("https://www.instagram.com/", { waitUntil: "domcontentloaded", timeout: 60000 });
      } catch { /* still try */ }
    }
    let me = null;
    for (let i = 0; i < 10 && !me; i++) {
      await delay(1500);
      me = await whoAmI(page);
    }
    if (!me) {
      finish({ ok: false, reason: "Signed in, but Instagram would not say which account it is. Try again." });
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
