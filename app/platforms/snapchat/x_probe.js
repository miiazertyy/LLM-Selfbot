/**
 * Calibration: what an X page is made of, so xbot.js's markers (SEL) can be checked against the real thing.
 *
 *   node x_probe.js <url> [profile dir] [--shot out.png] [--wait ms] [--html out.html]
 *
 * Prints the page's structure only: every data-testid with how many there are and where, every ARIA role and
 * label, the links by shape, what can be typed into, the file boxes. Never a message's words, a name or a
 * picture, so it is safe to run on a signed-in page.
 *
 * With a profile it runs as that account, which must not be running at the time. --html saves a sanitized copy of
 * the page for the fixture tests: every piece of text is replaced with x's of the same length and every address
 * with a made-up one, so the fixture carries the shape of the page and nobody's data.
 *
 * Which of xbot.js's markers matched is printed at the end, so what X changed is one line to read rather than a
 * page to compare. Signed out, x.com is a wall: that is itself worth probing, and it is what proves the
 * signed-out markers right without an account.
 */
import fs from "fs";
import { launchBrowser, delay } from "./browser.js";
import { SEL } from "./xbot.js";

const args = process.argv.slice(2);
const url = args[0] || "https://x.com/home";
const profileDir = args[1] && !args[1].startsWith("--") ? args[1] : "";
const arg = (name, dflt) => {
  const at = args.indexOf(name);
  return at >= 0 ? (args[at + 1] || dflt) : dflt;
};
const shot = arg("--shot", "");
const htmlOut = arg("--html", "");
const wait = Number(arg("--wait", 9000)) || 9000;

/** What the page is made of. Runs inside it, so it stands alone. */
function structure() {
  const out = { testids: {}, roles: {}, labels: {}, links: {}, buttonWords: {},
                editable: 0, fileInputs: 0, videos: 0, scrollers: 0, frames: 0 };
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top) };
  };
  // The hooks are what the bot leans on: X's own test ids, which outlive the words on its buttons.
  for (const el of document.querySelectorAll("[data-testid]")) {
    const id = (el.getAttribute("data-testid") || "").trim().slice(0, 48);
    if (!id) continue;
    const hit = out.testids[id] || (out.testids[id] = { n: 0, tag: el.tagName.toLowerCase(), ...box(el) });
    hit.n++;
  }
  for (const el of document.querySelectorAll("[role]")) {
    const role = el.getAttribute("role");
    const hit = out.roles[role] || (out.roles[role] = { n: 0, tag: el.tagName.toLowerCase() });
    hit.n++;
  }
  for (const el of document.querySelectorAll("[aria-label]")) {
    const label = (el.getAttribute("aria-label") || "").trim().slice(0, 40);
    if (!label) continue;
    out.labels[label] = (out.labels[label] || 0) + 1;
  }
  // Links by shape, not by who they point at.
  for (const a of document.querySelectorAll("a[href]")) {
    const shape = (a.getAttribute("href") || "")
      .replace(/\/status\/\d+/, "/status/<id>")
      .replace(/\/messages\/[0-9-]+/, "/messages/<id>")
      .replace(/^\/[A-Za-z0-9_]{1,15}\/?$/, "/<user>")
      .replace(/^\/[A-Za-z0-9_]{1,15}\//, "/<user>/")
      .replace(/[?#].*$/, "");
    out.links[shape] = (out.links[shape] || 0) + 1;
  }
  for (const b of document.querySelectorAll('div[role="button"], button, [role="menuitem"]')) {
    const words = (b.innerText || "").trim().slice(0, 30);
    if (words && words.length < 30 && !b.querySelector('div[role="button"], button')) {
      out.buttonWords[words] = (out.buttonWords[words] || 0) + 1;
    }
  }
  out.editable = document.querySelectorAll('[contenteditable="true"], textarea').length;
  out.fileInputs = document.querySelectorAll('input[type="file"]').length;
  out.videos = document.querySelectorAll("video").length;
  out.frames = document.querySelectorAll("iframe").length;
  out.scrollers = [...document.querySelectorAll("*")]
    .filter((e) => /(auto|scroll)/.test(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 20)
    .length;
  out.testids = Object.fromEntries(Object.entries(out.testids).sort((a, b) => b[1].n - a[1].n).slice(0, 150));
  out.labels = Object.fromEntries(Object.entries(out.labels).sort((a, b) => b[1] - a[1]).slice(0, 100));
  out.buttonWords = Object.fromEntries(Object.entries(out.buttonWords).sort((a, b) => b[1] - a[1]).slice(0, 80));
  return out;
}

/** The page with every word and address replaced, so its shape can be kept as a fixture and nobody's data is. */
function sanitized() {
  const doc = document.documentElement.cloneNode(true);
  for (const el of doc.querySelectorAll("script, style, link[rel=stylesheet], noscript")) el.remove();
  const walk = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walk.nextNode()) nodes.push(walk.currentNode);
  for (const n of nodes) {
    const t = n.nodeValue || "";
    // Times and numbers are kept: the readers lean on their shape.
    if (/^\s*$/.test(t) || /^[\d\s:.,/-]+$/.test(t)) continue;
    n.nodeValue = t.replace(/\S/g, "x");
  }
  for (const el of doc.querySelectorAll("[href]")) {
    const h = el.getAttribute("href") || "";
    el.setAttribute("href", h
      .replace(/\/status\/\d+/, "/status/1234567890123456789")
      .replace(/^\/[A-Za-z0-9_]{1,15}(?=[/?#]|$)/, "/someone")
      .replace(/\/messages\/[0-9-]+/, "/messages/1111-2222"));
  }
  for (const el of doc.querySelectorAll("[src]")) el.setAttribute("src", "about:blank");
  for (const el of doc.querySelectorAll("[alt]")) el.setAttribute("alt", "x");
  for (const el of doc.querySelectorAll("[aria-label]")) {
    // Labels are kept where they are X's own words and not somebody's name.
    const l = el.getAttribute("aria-label") || "";
    if (/@|\d{4}/.test(l)) el.setAttribute("aria-label", "x");
  }
  return `<!doctype html>${doc.outerHTML}`;
}

const browser = await launchBrowser({
  profileDir: profileDir || `${process.env.TEMP || "/tmp"}/x-probe-${Date.now()}`,
  hidden: false,
});
try {
  const page = (await browser.pages())[0] || (await browser.newPage());
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => {});
  await delay(wait);

  const report = { url: page.url(), title: await page.title().catch(() => "") };
  report.structure = await page.evaluate(structure).catch((e) => ({ error: e.message }));

  // Which of xbot.js's markers find anything here.
  report.markers = await page.evaluate((sel) => {
    const out = {};
    for (const [name, sels] of Object.entries(sel)) {
      if (!Array.isArray(sels)) continue;
      let n = 0;
      let which = "";
      for (const s of sels) {
        let found = 0;
        try { found = document.querySelectorAll(s).length; } catch { found = 0; }
        if (found && !which) which = s;
        n += found;
      }
      out[name] = { n, by: which };
    }
    return out;
  }, SEL).catch((e) => ({ error: e.message }));
  report.missing = Object.entries(report.markers || {}).filter(([, v]) => v && !v.n).map(([k]) => k);

  if (shot) {
    await page.screenshot({ path: shot, fullPage: false }).catch(() => {});
    report.shot = shot;
  }
  if (htmlOut) {
    const html = await page.evaluate(sanitized).catch(() => "");
    if (html) {
      fs.writeFileSync(htmlOut, html, "utf-8");
      report.html = { file: htmlOut, bytes: html.length };
    }
  }
  console.log(JSON.stringify(report, null, 1));
} finally {
  await browser.close();
}
