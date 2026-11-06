/**
 * Calibration: what a TikTok page is made of, so tiktokbot.js's markers (SEL)
 * can be checked against the real thing. Prints the page's structure only:
 * its frames, every data-e2e marker with how many there are, their sizes and
 * where they sit, the ARIA roles, and the class-name fragments in use. Never a
 * message's words, a name or a picture: it can be run on a signed-in inbox.
 *
 *   node tiktok_probe.js <url> [profile dir] [--shot out.png] [--wait ms]
 *
 * With a profile it runs as that account (it must not be running at the time).
 */
import { launchBrowser, delay } from "./browser.js";

const args = process.argv.slice(2);
const url = args[0] || "https://www.tiktok.com/messages?lang=en";
const profileDir = args[1] && !args[1].startsWith("--") ? args[1] : "";
const shotAt = args.indexOf("--shot");
const shot = shotAt >= 0 ? args[shotAt + 1] : "";
const waitAt = args.indexOf("--wait");
const wait = waitAt >= 0 ? Number(args[waitAt + 1]) || 8000 : 8000;

function structure() {
  const out = { e2e: {}, roles: {}, classes: {}, editable: 0, iframes: [], scrollers: 0 };
  for (const el of document.querySelectorAll("[data-e2e]")) {
    const name = el.getAttribute("data-e2e");
    const r = el.getBoundingClientRect();
    const hit = out.e2e[name] || (out.e2e[name] = { n: 0, tag: el.tagName.toLowerCase(), w: 0, h: 0, x: 0, parents: "" });
    hit.n++;
    if (!hit.w) {
      hit.w = Math.round(r.width); hit.h = Math.round(r.height); hit.x = Math.round(r.left);
      const chain = [];
      for (let p = el.parentElement; p && chain.length < 4; p = p.parentElement) {
        if (p.hasAttribute("data-e2e")) chain.push(p.getAttribute("data-e2e"));
      }
      hit.parents = chain.join(" < ");
    }
  }
  for (const el of document.querySelectorAll("[role]")) {
    const role = el.getAttribute("role");
    out.roles[role] = (out.roles[role] || 0) + 1;
  }
  for (const el of document.querySelectorAll("[class]")) {
    for (const c of String(el.className || "").split(/\s+/)) {
      const m = c.match(/^(?:css-[a-z0-9]+-)?([A-Z][A-Za-z]+)$/);
      if (m) out.classes[m[1]] = (out.classes[m[1]] || 0) + 1;
    }
  }
  out.editable = document.querySelectorAll('[contenteditable="true"], [contenteditable="plaintext-only"], textarea').length;
  out.iframes = [...document.querySelectorAll("iframe")].map((f) => (f.getAttribute("src") || "").replace(/[?#].*$/, ""));
  out.scrollers = [...document.querySelectorAll("*")].filter((e) => /(auto|scroll)/.test(getComputedStyle(e).overflowY)
    && e.scrollHeight > e.clientHeight + 20).length;
  out.fileInputs = document.querySelectorAll('input[type="file"]').length;
  // Class fragments sorted by use, the commonest first; the rare ones are where the inbox's own parts are.
  out.classes = Object.fromEntries(Object.entries(out.classes).sort((a, b) => b[1] - a[1]).slice(0, 160));
  return out;
}

const browser = await launchBrowser({ profileDir: profileDir || undefined, hidden: true, locale: "en-US" });
try {
  const page = (await browser.pages())[0] || (await browser.newPage());
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await delay(wait);
  const report = { url: page.url().replace(/[?#].*$/, ""), signedIn: false, frames: [] };
  try {
    report.signedIn = (await page.cookies("https://www.tiktok.com")).some((c) => c.name === "sessionid");
  } catch { /* unknown */ }
  for (const f of page.frames()) {
    try {
      report.frames.push({ url: f.url().replace(/[?#].*$/, ""), main: f === page.mainFrame(), ...(await f.evaluate(structure)) });
    } catch (e) {
      report.frames.push({ url: f.url().replace(/[?#].*$/, ""), error: e.message });
    }
  }
  if (shot) await page.screenshot({ path: shot });
  console.log(JSON.stringify(report, null, 1));
} finally {
  await browser.close();
}
