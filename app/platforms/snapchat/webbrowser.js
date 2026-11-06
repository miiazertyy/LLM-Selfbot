/**
 * The web, for the persona: a Chrome of its own that Python (app/utils/web/browser.py) asks things of, one line of
 * JSON at a time on stdin, each answered with one line of JSON on stdout carrying the same id.
 *
 *   start                     Chrome up (everything else waits for it anyway)
 *   tab                       a tab of its own for one lookup: {tab}
 *   open {tab, url}           the page, as it shows once its JavaScript ran: {page: {url, title, text, links}}
 *   google {tab, q, n}        a Google search, read off its page: {results}; {error: "captcha"} when it asks
 *   find {tab, q}             the open site's own search box, typed into: {page}
 *   shot {tab}                what the tab shows: {jpeg} (base64)
 *   close {tab}               the tab closed
 *
 * It lives in this folder for the reason discord_token.js does: Node finds node_modules beside the script, and
 * Puppeteer is installed here. Its Chrome runs on a profile of its own (LLMSELFBOT_WEB_PROFILE), never an account's,
 * with its window off the screen and out of the taskbar (browser.js, as a hidden account's).
 *
 * It only reads. Nowhere private: a link to this computer or the home network is refused before Chrome loads it,
 * the panel on 127.0.0.1 included, and every redirect is checked the same way. Downloads are refused, pop-ups closed,
 * dialogs dismissed. Typing happens in one place only, a site's own search box. With nothing to do for a few
 * minutes, or Python gone, it closes Chrome and ends.
 */
import { launchBrowser, closeChromeOn, delay } from "./browser.js";
import readline from "readline";
import dns from "dns/promises";
import net from "net";

const PROFILE = process.env.LLMSELFBOT_WEB_PROFILE || "";
const IDLE_MS = 180000;
const NAV_TIMEOUT = 20000;
const MAX_TEXT = 9000;

let browser = null;
let starting = null;
const tabs = new Map();
let nextTab = 1;
let idleTimer = null;

function answer(id, obj) {
  process.stdout.write(JSON.stringify({ id, ...obj }) + "\n");
}

// ── Nowhere private ─────────────────────────────────────────────────────────

function privateIp(ip) {
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split(".").map(Number);
    return a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31)
      || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || (a === 192 && b === 0)
      || (a === 198 && (b === 18 || b === 19));
  }
  const v6 = ip.toLowerCase();
  if (v6.startsWith("::ffff:")) return privateIp(v6.slice(7));
  return v6 === "::1" || v6 === "::" || /^f[cd]/.test(v6) || /^fe[89ab]/.test(v6) || v6.startsWith("ff");
}

function localName(host) {
  const h = String(host || "").toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (!h) return true;
  if (net.isIP(h)) return privateIp(h);
  return h === "localhost" || /\.(localhost|local|internal|lan|home|corp|intranet)$/.test(h) || h.endsWith(".home.arpa")
    || !h.includes(".");
}

const resolved = new Map();

/** A page Chrome may go to: http(s), a public name or address, every address of the name public. */
async function allowedPage(url) {
  let u;
  try { u = new URL(url); } catch { return false; }
  if (u.protocol !== "http:" && u.protocol !== "https:") return false;
  if (u.username || u.password) return false;
  const host = u.hostname.replace(/^\[|\]$/g, "");
  if (localName(host)) return false;
  if (net.isIP(host)) return true;
  const hit = resolved.get(host);
  if (hit && Date.now() - hit.at < 60000) return hit.ok;
  let ok = false;
  try {
    const all = await dns.lookup(host, { all: true });
    ok = all.length > 0 && all.every((a) => !privateIp(a.address));
  } catch { ok = false; }
  resolved.set(host, { ok, at: Date.now() });
  return ok;
}

/** A request any page may make: images and scripts from public places only. */
function allowedRequest(url) {
  try {
    const u = new URL(url);
    if (u.protocol === "data:" || u.protocol === "blob:") return true;
    if (u.protocol !== "http:" && u.protocol !== "https:") return false;
    return !localName(u.hostname);
  } catch { return false; }
}

// ── Chrome ──────────────────────────────────────────────────────────────────

async function ensureBrowser() {
  if (browser && browser.isConnected()) return browser;
  if (!starting) {
    starting = (async () => {
      const b = await launchBrowser({ profileDir: PROFILE, hidden: true, locale: "en-US" });
      b.on("disconnected", () => { browser = null; starting = null; tabs.clear(); });
      // A pop-up a page opened is closed: a lookup reads the pages it chose.
      b.on("targetcreated", async (target) => {
        try {
          if (target.type() !== "page" || !target.opener()) return;
          const p = await target.page();
          if (p && ![...tabs.values()].includes(p)) await p.close();
        } catch { /* gone already */ }
      });
      try {
        const cdp = await b.target().createCDPSession();
        await cdp.send("Browser.setDownloadBehavior", { behavior: "deny" });
      } catch { /* an older Chrome: pages still cannot write anywhere it reads */ }
      browser = b;
      return b;
    })().catch((err) => { starting = null; throw err; });
  }
  return starting;
}

async function newTab() {
  const b = await ensureBrowser();
  const page = await b.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  page.setDefaultNavigationTimeout(NAV_TIMEOUT);
  page.on("dialog", (d) => d.dismiss().catch(() => {}));
  await page.setRequestInterception(true);
  page.on("request", async (req) => {
    if (req.isInterceptResolutionHandled()) return;
    try {
      const ok = req.isNavigationRequest() && req.frame() === page.mainFrame()
        ? await allowedPage(req.url())
        : allowedRequest(req.url());
      if (ok) await req.continue();
      else await req.abort("blockedbyclient");
    } catch { /* the page went away */ }
  });
  const id = nextTab++;
  tabs.set(id, page);
  return id;
}

function tabOf(id) {
  const page = tabs.get(Number(id));
  if (!page || page.isClosed()) throw new Error("that tab is closed");
  return page;
}

// ── Reading a page ──────────────────────────────────────────────────────────

/** In the page: its words without menus, banners and footers, and its links. */
function readPage(maxText) {
  const hide = [...document.querySelectorAll(
    "nav,footer,aside,dialog,[role=navigation],[role=contentinfo],[aria-modal=true],[hidden]")];
  const before = hide.map((e) => e.getAttribute("style"));
  hide.forEach((e) => e.style.setProperty("display", "none", "important"));
  const main = document.querySelector("article, main, [role=main]");
  let text = (main && main.innerText && main.innerText.length >= 400 ? main.innerText : document.body?.innerText) || "";
  hide.forEach((e, i) => (before[i] === null ? e.removeAttribute("style") : e.setAttribute("style", before[i])));
  text = text.split("\n").map((l) => l.replace(/\s+/g, " ").trim()).filter((l) => l.length > 1).join("\n");
  const links = [];
  const seen = new Set();
  for (const a of document.querySelectorAll("a[href]")) {
    const href = a.href;
    if (!/^https?:/.test(href) || seen.has(href.split("#")[0]) || a.offsetParent === null) continue;
    const words = (a.innerText || a.getAttribute("aria-label") || a.title || "").replace(/\s+/g, " ").trim();
    if (!words) continue;
    seen.add(href.split("#")[0]);
    links.push({ text: words.slice(0, 90), url: href.split("#")[0] });
    if (links.length >= 120) break;
  }
  const meta = (name) => document.querySelector(`meta[name="${name}"], meta[property="${name}"]`)?.content || "";
  return { url: location.href, title: document.title || meta("og:title"), description: meta("og:description")
    || meta("description"), text: text.slice(0, maxText), links };
}

/** A cookie banner in the way, answered: reading the page is all that is wanted. */
async function clearBanner(page) {
  try {
    await page.evaluate(() => {
      const words = /^(reject all|tout refuser|refuse all|decline all|accept all|tout accepter|accept|accepter|i agree|agree|j'accepte|allow all|got it|ok)$/i;
      for (const b of document.querySelectorAll("button, [role=button]")) {
        const t = (b.innerText || "").trim();
        if (t && t.length < 30 && words.test(t) && b.offsetParent !== null) { b.click(); return true; }
      }
      return false;
    });
  } catch { /* nothing to click */ }
}

async function settle(page) {
  try { await page.waitForNetworkIdle({ idleTime: 600, timeout: 3500 }); } catch { /* busy pages never go idle */ }
}

async function openPage(page, url) {
  if (!(await allowedPage(url))) throw new Error("that link points inside this computer or network");
  const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT });
  if (!(await allowedPage(page.url()))) {
    await page.goto("about:blank").catch(() => {});
    throw new Error("it went somewhere private");
  }
  await settle(page);
  await clearBanner(page);
  await delay(300);
  const status = resp ? resp.status() : 200;
  if (status >= 400) throw new Error(`the site answered ${status}`);
  return page.evaluate(readPage, MAX_TEXT);
}

// ── Google ──────────────────────────────────────────────────────────────────

/** Google's consent page, the first time on this profile: answered once, kept in its cookies after. */
async function consent(page) {
  if (!/consent\.google\./.test(page.url())) {
    // Or as a dialog over the page itself.
    const clicked = await page.evaluate(() => {
      const b = [...document.querySelectorAll("button")].find((x) => /^(reject all|tout refuser|accept all|tout accepter)$/i.test((x.innerText || "").trim()));
      if (b) { b.click(); return true; }
      return false;
    }).catch(() => false);
    if (clicked) await delay(800);
    return;
  }
  await page.evaluate(() => {
    const b = [...document.querySelectorAll("button")].find((x) => /reject all|tout refuser|accept all|tout accepter/i.test(x.innerText || ""));
    if (b) b.click();
  }).catch(() => {});
  await page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 10000 }).catch(() => {});
}

async function google(page, q, n) {
  // As a person searches: Google's own page, the words typed into its box at a person's pace, Enter. A search
  // address loaded straight off is what a script does, and Google answers that with a captcha.
  if (!/^https:\/\/www\.google\.[a-z.]+\//.test(page.url())) {
    await page.goto("https://www.google.com/?hl=en", { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT });
    await consent(page);
    if (!/^https:\/\/www\.google\./.test(page.url())) {
      await page.goto("https://www.google.com/?hl=en", { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT });
    }
    await delay(600 + Math.random() * 900);
  }
  const box = await page.$("textarea[name=q], input[name=q]");
  if (box) {
    await box.click({ clickCount: 3 });
    await page.keyboard.press("Backspace");
    await box.type(String(q).slice(0, 200), { delay: 55 + Math.random() * 60 });
    await delay(250 + Math.random() * 400);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT }).catch(() => {}),
      page.keyboard.press("Enter"),
    ]);
  } else {
    await page.goto(`https://www.google.com/search?q=${encodeURIComponent(q)}&hl=en`,
      { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT });
  }
  await consent(page);
  await settle(page);
  const blocked = /\/sorry\//.test(page.url()) || await page.evaluate(() =>
    !!document.querySelector("#captcha-form, form[action*='sorry'], iframe[src*='recaptcha']")
    || /unusual traffic|not a robot/i.test(document.body?.innerText || "")).catch(() => false);
  if (blocked) return { blocked: true };
  const results = await page.evaluate((max) => {
    const out = [];
    const seen = new Set();
    // Google's own short answer, when it gives one, first.
    const box = document.querySelector("[data-attrid] .hgKElc, .IZ6rdc, .Z0LcW, [data-attrid='wa:/description']");
    if (box && box.innerText.trim()) {
      out.push({ title: "Google's answer", url: location.href, snippet: box.innerText.replace(/\s+/g, " ").trim().slice(0, 300) });
    }
    for (const h3 of document.querySelectorAll("#search a h3, #rso a h3")) {
      const a = h3.closest("a");
      const href = a && a.href;
      if (!href || !/^https?:/.test(href) || /^https?:\/\/([a-z]+\.)?google\.[a-z.]+\//.test(href) || seen.has(href)) continue;
      seen.add(href);
      const card = a.closest("div.MjjYud, div.g, [data-hveid]") || a.parentElement;
      const line = card && card.querySelector("[data-sncf], .VwiC3b, [style*='-webkit-line-clamp']");
      const snippet = (line ? line.innerText : (card ? card.innerText.replace(h3.innerText, "") : ""))
        .replace(/\s+/g, " ").trim();
      out.push({ title: h3.innerText.trim(), url: href, snippet: snippet.slice(0, 300) });
      if (out.length >= max) break;
    }
    return out;
  }, n || 6);
  return { results };
}

// ── A site's own search box ─────────────────────────────────────────────────

async function find(page, q) {
  const box = await page.$("input[type=search], input[name=q], input[name=query], input[name=search], "
    + "input[aria-label*=earch], input[placeholder*=earch], input[placeholder*=echerch]");
  if (!box) throw new Error("this page has no search box");
  const type = await box.evaluate((el) => (el.type || "").toLowerCase());
  if (type === "password" || type === "email") throw new Error("this page has no search box");
  await box.click({ clickCount: 3 });
  await box.type(String(q).slice(0, 120), { delay: 40 });
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT }).catch(() => {}),
    page.keyboard.press("Enter"),
  ]);
  if (!(await allowedPage(page.url()))) throw new Error("it went somewhere private");
  await settle(page);
  return page.evaluate(readPage, MAX_TEXT);
}

// ── The conversation with Python ────────────────────────────────────────────

function touch() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => shutdown(0), IDLE_MS);
}

async function handle(msg) {
  const { id, cmd } = msg;
  touch();
  try {
    if (cmd === "start") {
      await ensureBrowser();
      return answer(id, { ok: true });
    }
    if (cmd === "tab") return answer(id, { ok: true, tab: await newTab() });
    if (cmd === "open") return answer(id, { ok: true, page: await openPage(tabOf(msg.tab), String(msg.url || "")) });
    if (cmd === "google") {
      const r = await google(tabOf(msg.tab), String(msg.q || ""), Number(msg.n) || 6);
      return r.blocked ? answer(id, { ok: false, error: "captcha" }) : answer(id, { ok: true, results: r.results });
    }
    if (cmd === "find") return answer(id, { ok: true, page: await find(tabOf(msg.tab), String(msg.q || "")) });
    if (cmd === "shot") {
      const jpeg = await tabOf(msg.tab).screenshot({ type: "jpeg", quality: 60, encoding: "base64" });
      return answer(id, { ok: true, jpeg });
    }
    if (cmd === "close") {
      const page = tabs.get(Number(msg.tab));
      tabs.delete(Number(msg.tab));
      if (page && !page.isClosed()) await page.close().catch(() => {});
      return answer(id, { ok: true });
    }
    return answer(id, { ok: false, error: `unknown command ${cmd}` });
  } catch (err) {
    return answer(id, { ok: false, error: String((err && err.message) || err).slice(0, 300) });
  }
}

let closing = false;
async function shutdown(code) {
  if (closing) return;
  closing = true;
  try {
    if (browser) await Promise.race([browser.close(), delay(5000)]);
  } catch { /* closing anyway */ }
  if (PROFILE) closeChromeOn(PROFILE);
  process.exit(code);
}

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch { return; }
  handle(msg);
});
rl.on("close", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
touch();
