/**
 * Calibration: what an Instagram page is made of, so instagrambot.js's markers
 * (SEL) can be checked against the real thing. Prints the page's structure
 * only: every ARIA role and label with how many there are, the sizes and where
 * they sit, the links by shape (/direct/t/, /reel/, /stories/), what can be
 * typed into, the file boxes, the videos and the audio. Never a message's
 * words, a name or a picture: it can be run on a signed-in inbox.
 *
 *   node instagram_probe.js <url> [profile dir] [--shot out.png] [--wait ms] [--html out.html]
 *
 * With a profile it runs as that account (it must not be running at the time).
 * --html saves a sanitized copy of the page for the logic tests: every piece of
 * text is replaced with x's of the same length, every address with a made-up
 * one, so a fixture carries the shape of the page and nobody's data.
 *
 * Which of instagrambot.js's markers matched is printed at the end, so what
 * Instagram changed is one line to read rather than a page to compare.
 */
import fs from "fs";
import { launchBrowser, delay } from "./browser.js";
import { SEL } from "./instagrambot.js";

const args = process.argv.slice(2);
const url = args[0] || "https://www.instagram.com/direct/inbox/";
const profileDir = args[1] && !args[1].startsWith("--") ? args[1] : "";
const arg = (name, dflt) => {
  const at = args.indexOf(name);
  return at >= 0 ? (args[at + 1] || dflt) : dflt;
};
const shot = arg("--shot", "");
const htmlOut = arg("--html", "");
const wait = Number(arg("--wait", 9000)) || 9000;

/** What the page is made of. Runs inside it, so it must stand alone. */
function structure() {
  const out = { roles: {}, labels: {}, links: {}, classes: {}, editable: 0, fileInputs: 0,
                videos: 0, audios: 0, scrollers: 0, canvases: 0, buttonWords: {} };
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top) };
  };
  for (const el of document.querySelectorAll("[role]")) {
    const role = el.getAttribute("role");
    const hit = out.roles[role] || (out.roles[role] = { n: 0, tag: el.tagName.toLowerCase(), ...box(el) });
    hit.n++;
  }
  // The labels are what the bot leans on: they are Instagram's own words for its buttons, and they are stable.
  for (const el of document.querySelectorAll("[aria-label]")) {
    const label = (el.getAttribute("aria-label") || "").trim().slice(0, 40);
    if (!label) continue;
    const hit = out.labels[label] || (out.labels[label] = { n: 0, tag: el.tagName.toLowerCase(), role: el.getAttribute("role") || "", ...box(el) });
    hit.n++;
  }
  // Links by shape, not by who they point at.
  for (const a of document.querySelectorAll("a[href]")) {
    const href = a.getAttribute("href") || "";
    const shape = href
      .replace(/\/direct\/t\/\d+/, "/direct/t/<id>")
      .replace(/\/(p|reel|reels|tv)\/[A-Za-z0-9_-]+/, "/$1/<code>")
      .replace(/\/stories\/[A-Za-z0-9._]+\/\d+/, "/stories/<user>/<id>")
      .replace(/^\/[A-Za-z0-9._]{1,30}\/?$/, "/<user>/")
      .replace(/[?#].*$/, "");
    out.links[shape] = (out.links[shape] || 0) + 1;
  }
  // The words on its buttons, which is how the bot presses the ones with no label.
  for (const b of document.querySelectorAll('div[role="button"], button, [role="menuitem"]')) {
    const words = (b.innerText || "").trim().slice(0, 30);
    if (words && words.length < 30 && !b.querySelector('div[role="button"], button')) {
      out.buttonWords[words] = (out.buttonWords[words] || 0) + 1;
    }
  }
  for (const el of document.querySelectorAll("[class]")) {
    for (const c of String(el.className || "").split(/\s+/)) {
      if (/^[a-z0-9_]{5,12}$/.test(c)) out.classes[c] = (out.classes[c] || 0) + 1;
    }
  }
  out.editable = document.querySelectorAll('[contenteditable="true"], [contenteditable="plaintext-only"], textarea').length;
  out.fileInputs = document.querySelectorAll('input[type="file"]').length;
  out.fileAccepts = [...document.querySelectorAll('input[type="file"]')].map((i) => i.getAttribute("accept") || "any");
  out.videos = document.querySelectorAll("video").length;
  out.audios = document.querySelectorAll("audio").length;
  out.canvases = document.querySelectorAll("canvas").length;
  out.scrollers = [...document.querySelectorAll("*")].filter((e) => /(auto|scroll)/.test(getComputedStyle(e).overflowY)
    && e.scrollHeight > e.clientHeight + 20).length;
  // Instagram's own generated class names say nothing; only how many there are is worth knowing.
  out.classes = Object.fromEntries(Object.entries(out.classes).sort((a, b) => b[1] - a[1]).slice(0, 40));
  out.labels = Object.fromEntries(Object.entries(out.labels).sort((a, b) => b[1].n - a[1].n).slice(0, 120));
  out.buttonWords = Object.fromEntries(Object.entries(out.buttonWords).sort((a, b) => b[1] - a[1]).slice(0, 80));
  return out;
}

/** Which of the bot's markers match here, and how many of each. */
function matches(sel) {
  const out = {};
  for (const [name, list] of Object.entries(sel)) {
    if (!Array.isArray(list)) continue;
    for (const s of list) {
      let n = 0;
      try { n = document.querySelectorAll(s).length; } catch { n = -1; }       // -1: this build's CSS rejects it
      if (n !== 0) { out[name] = { selector: s, n }; break; }
    }
    if (!out[name]) out[name] = { selector: "", n: 0 };
  }
  return out;
}

/**
 * The page with nobody's data in it, for a fixture: every run of text becomes x's of the same length, every address
 * a made-up one, every id a round number. The shape is kept exactly; nothing real is.
 */
function sanitized() {
  const clone = document.documentElement.cloneNode(true);
  for (const el of clone.querySelectorAll("script, style, link, meta, noscript")) el.remove();
  const walk = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walk.nextNode()) texts.push(walk.currentNode);
  for (const t of texts) {
    const v = t.nodeValue || "";
    if (!v.trim()) continue;
    // Times and short counts are shape, not data: kept as they are so the day labels still read.
    if (/^\s*(\d{1,2}:\d{2}( ?[AP]M)?|\d+[smhdw]|Today|Yesterday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*$/i.test(v)) continue;
    t.nodeValue = v.replace(/\S/g, "x");
  }
  let n = 0;
  for (const el of clone.querySelectorAll("*")) {
    for (const attr of [...el.attributes]) {
      if (/^(src|srcset|href|poster|data-src)$/i.test(attr.name)) {
        const was = attr.value || "";
        if (/\/direct\/t\//.test(was)) el.setAttribute(attr.name, `/direct/t/${100000000000 + (n += 1)}/`);
        else if (/\/(p|reel|reels|tv)\//.test(was)) el.setAttribute(attr.name, `/reel/AAAA${n += 1}/`);
        else if (/\/stories\//.test(was)) el.setAttribute(attr.name, `/stories/person${n += 1}/${300000000000 + n}/`);
        else if (/^https?:/.test(was)) el.setAttribute(attr.name, "https://example.invalid/x.jpg");
        else if (/^\//.test(was)) el.setAttribute(attr.name, `/person${n += 1}/`);
      } else if (/^(alt|title|placeholder)$/i.test(attr.name)) {
        el.setAttribute(attr.name, (attr.value || "").replace(/\S/g, "x"));
      } else if (attr.name === "aria-label") {
        // Instagram's own words for its buttons: the whole point of a fixture, so they stay.
        continue;
      }
    }
  }
  return `<!doctype html>\n<html>${clone.innerHTML}</html>`;
}

const browser = await launchBrowser({ profileDir: profileDir || undefined, hidden: true, locale: "en-US" });
try {
  const page = (await browser.pages())[0] || (await browser.newPage());
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await delay(wait);
  const report = { url: page.url().replace(/[?#].*$/, ""), signedIn: false };
  try {
    report.signedIn = (await page.cookies("https://www.instagram.com")).some((c) => c.name === "sessionid" && c.value);
  } catch { /* unknown */ }
  report.page = await page.evaluate(structure).catch((e) => ({ error: e.message }));
  report.markers = await page.evaluate(matches, SEL).catch((e) => ({ error: e.message }));
  report.missing = Object.entries(report.markers || {}).filter(([, v]) => v && v.n === 0).map(([k]) => k);
  report.rejected = Object.entries(report.markers || {}).filter(([, v]) => v && v.n === -1).map(([k]) => k);
  if (shot) await page.screenshot({ path: shot });
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
