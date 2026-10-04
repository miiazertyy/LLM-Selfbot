/**
 * Open a real browser at discord.com/login, let the person sign in themselves,
 * and read the token out of the session they end up with.
 *
 * This lives in the snapchat/ folder for one boring reason: Node's ESM resolver
 * looks for node_modules beside the script, and that is where Puppeteer is
 * installed. Nothing here touches Snapchat.
 *
 * Why a browser instead of posting the password to Discord's login API: the API
 * route answers a good half of real logins with a captcha, a new-device email
 * check, or a passkey prompt, and none of those can be answered from a script -
 * every one of them dead-ends in "go and paste a token instead". In a browser
 * the person just does what they would normally do, captcha included, and the
 * app never sees their password at all.
 *
 * Getting the token: not out of localStorage, which Discord deliberately makes
 * awkward to read and which is not where it will necessarily live next year.
 * The token is whatever the client puts in the Authorization header, so that is
 * what is read, straight off the wire through CDP. Any authenticated call the
 * app makes on its way in carries it.
 *
 * Talks to Python in JSON lines on stdout, one object per line.
 */
import fs from "fs";
import os from "os";
import path from "path";
import puppeteer from "puppeteer-extra";
import Stealth from "puppeteer-extra-plugin-stealth";

puppeteer.use(Stealth());

const TIMEOUT_MS = Number(process.env.DISCORD_LOGIN_TIMEOUT_MS || 10 * 60 * 1000) || 600000;
const PROXY = (process.env.DISCORD_LOGIN_PROXY || "").trim();
const LOCALE = (process.env.SNAP_LOCALE || "en-US").trim() || "en-US";

function say(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

/** Split http://user:pass@host:port into what Chrome and CDP each need. */
function parseProxy(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw.includes("://") ? raw : `http://${raw}`);
    return {
      server: `${u.protocol}//${u.host}`,
      username: decodeURIComponent(u.username || ""),
      password: decodeURIComponent(u.password || ""),
    };
  } catch {
    return { server: raw, username: "", password: "" };
  }
}

const proxy = parseProxy(PROXY);
// A throwaway profile, so this always starts at a signed-out Discord rather
// than whoever happened to be signed in last. Python hands one over and owns
// removing it: a cancelled sign-in kills this process, so anything cleaned up
// on the way out here would not be cleaned up then, and every cancel would
// leave a browser profile behind.
const profileDir = process.env.DISCORD_LOGIN_PROFILE
  || fs.mkdtempSync(path.join(os.tmpdir(), "llmselfbot-login-"));
const OWNS_PROFILE = !process.env.DISCORD_LOGIN_PROFILE;

let browser;
let settled = false;

function finish(result) {
  if (settled) return;
  settled = true;
  say(result);
  (async () => {
    try { await browser?.close(); } catch { /* going away anyway */ }
    if (OWNS_PROFILE) {
      try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch { /* best effort */ }
    }
    process.exit(result.ok ? 0 : 1);
  })();
}

try {
  say({ state: "opening", detail: "Starting the browser" });
  browser = await puppeteer.launch({
    headless: false,                       // the whole point is that a person uses it
    userDataDir: profileDir,
    ignoreDefaultArgs: ["--enable-automation"],
    defaultViewport: null,
    args: [
      "--disable-blink-features=AutomationControlled",
      `--lang=${LOCALE}`,
      "--start-maximized",
      ...(proxy ? [`--proxy-server=${proxy.server}`] : []),
      ...(process.platform === "linux" ? ["--no-sandbox", "--disable-setuid-sandbox"] : []),
    ],
  });

  const page = (await browser.pages())[0] || (await browser.newPage());
  if (proxy && proxy.username) {
    await page.authenticate({ username: proxy.username, password: proxy.password });
  }

  // Read the Authorization header off every request the page makes. CDP rather
  // than page.on("request") because this sees the headers the network stack
  // actually sent, which is the thing being looked for.
  const cdp = await page.createCDPSession();
  await cdp.send("Network.enable");
  cdp.on("Network.requestWillBeSent", (e) => {
    try {
      const url = e.request?.url || "";
      if (!url.includes("discord.com/api/")) return;
      const headers = e.request.headers || {};
      const auth = headers.Authorization || headers.authorization || "";
      // Bearer is an OAuth app token, not the account's own session token.
      if (auth && !auth.startsWith("Bearer ") && auth.length > 30) {
        finish({ ok: true, token: auth });
      }
    } catch { /* one bad event must not take the whole login down */ }
  });

  // If the person is already signed in, Discord goes straight to the app and
  // the header shows up within a second. Otherwise they sign in and it shows up
  // when they land.
  await page.goto("https://discord.com/login", { waitUntil: "domcontentloaded", timeout: 60000 });
  say({ state: "waiting", detail: "Sign in to Discord in the window that opened" });

  // Closing the window is a deliberate cancel, not a failure to report loudly.
  browser.on("disconnected", () => {
    finish({ ok: false, reason: "The browser was closed before the login finished." });
  });

  setTimeout(() => {
    finish({ ok: false, reason: "Timed out waiting for the login. Nothing was saved." });
  }, TIMEOUT_MS);
} catch (err) {
  finish({ ok: false, reason: `Could not start the browser: ${err.message}` });
}
