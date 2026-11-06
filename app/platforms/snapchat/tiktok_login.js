/**
 * Sign a TikTok account in: a real Chrome window at tiktok.com/login, on the
 * profile the account will run in, for a person to sign in however TikTok lets
 * them (the QR code from the phone's app, a password, Google, a code), and to
 * answer whatever check TikTok puts up. The app never sees a password.
 *
 * Done when TikTok has given the window its session (the sessionid cookie):
 * says which account it is ({ ok, handle, name }) and closes Chrome properly,
 * so the session is written into the profile. Python then files the profile
 * under that account's @handle (app/utils/tiktok_browser_login.py).
 *
 * Talks to Python in JSON lines on stdout, one object per line.
 */
import { launchBrowser, delay } from "./browser.js";

const PROFILE = process.env.TIKTOK_LOGIN_PROFILE || "";
const TIMEOUT_MS = Number(process.env.TIKTOK_LOGIN_TIMEOUT_MS || 15 * 60 * 1000) || 900000;
const LOCALE = (process.env.TIKTOK_LOCALE || "en-US").trim() || "en-US";

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

async function whoAmI(page) {
  try {
    return await page.evaluate(async () => {
      try {
        const r = await fetch("https://www.tiktok.com/passport/web/account/info/?aid=1459", { credentials: "include" });
        const d = (await r.json())?.data;
        if (d && d.username) return { handle: String(d.username).toLowerCase(), name: d.screen_name || "" };
      } catch { /* the page's own link, below */ }
      const a = document.querySelector('a[data-e2e="nav-profile"]') || [...document.querySelectorAll('a[href^="/@"]')]
        .find((x) => /profile/i.test(x.getAttribute("data-e2e") || ""));
      const m = a ? (a.getAttribute("href") || "").match(/\/@([A-Za-z0-9._]{2,24})/) : null;
      return m ? { handle: m[1].toLowerCase(), name: "" } : null;
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
  await page.goto(`https://www.tiktok.com/login?lang=${LOCALE.split("-")[0]}`, { waitUntil: "domcontentloaded", timeout: 60000 });
  say({ state: "waiting", detail: "Sign in to TikTok in the window that opened" });
  setTimeout(() => finish({ ok: false, reason: "Timed out waiting for the sign-in. Nothing was saved." }), TIMEOUT_MS);
  while (!settled) {
    await delay(2000);
    let cookies = [];
    try { cookies = await page.cookies("https://www.tiktok.com"); } catch { continue; }
    if (!cookies.some((c) => c.name === "sessionid" && c.value)) continue;
    say({ state: "checking", detail: "Signed in, finding out which account it is" });
    // TikTok lands somewhere after signing in; the home page is the one that knows who you are.
    if (!/tiktok\.com\/(foryou|$|\?)/.test(page.url())) {
      try { await page.goto("https://www.tiktok.com/", { waitUntil: "domcontentloaded", timeout: 60000 }); } catch { /* still try */ }
    }
    let me = null;
    for (let i = 0; i < 10 && !me; i++) {
      await delay(1500);
      me = await whoAmI(page);
    }
    if (!me) {
      finish({ ok: false, reason: "Signed in, but TikTok would not say which account it is. Try again." });
      break;
    }
    // A moment for the session to settle before Chrome closes.
    await delay(2500);
    finish({ ok: true, handle: me.handle, name: me.name });
    break;
  }
} catch (err) {
  finish({ ok: false, reason: `Could not start the browser: ${err.message}` });
}
