/**
 * Calibration: what a Reddit page is made of, so redditbot.js's markers (SEL) can be checked against the real
 * thing.
 *
 *   node reddit_probe.js <url> [profile dir] [--shot out.png] [--wait ms] [--html out.html]
 *
 * Prints the page's structure only: every custom element with how many there are and which attributes it carries,
 * what is inside the shadow roots, every ARIA role and label, the links by shape, what can be typed into. Never a
 * post's words, a name or a picture, so it is safe to run on a signed-in page.
 *
 * Reddit is the first platform here that keeps half its page inside shadow roots, so this walks them: the count
 * of them, and which markers were only found by going in, is the one thing worth knowing before trusting a
 * selector. The readers in redditbot.js are written to need the light DOM only - a post's facts are attributes on
 * <shreddit-post> - and what this prints says whether that held.
 *
 * With a profile it runs as that account, which must not be running at the time. --html saves a sanitized copy of
 * the page for the fixture tests: every piece of text is replaced with x's of the same length and every address
 * with a made-up one, so the fixture carries the shape of the page and nobody's data.
 *
 * Which of redditbot.js's markers matched is printed at the end, so what Reddit changed is one line to read
 * rather than a page to compare.
 */
import fs from "fs";
import { launchBrowser, delay } from "./browser.js";
import { SEL } from "./redditbot.js";

const args = process.argv.slice(2);
const url = args[0] || "https://www.reddit.com/";
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
  const out = { custom: {}, roles: {}, labels: {}, links: {}, buttonWords: {},
                shadowRoots: 0, editable: 0, fileInputs: 0, videos: 0, deepButtons: 0 };
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  };
  // Reddit's own elements, and the attributes they carry: that is where a post's facts live, and the one part of
  // the page a redesign does not move.
  for (const el of document.querySelectorAll("*")) {
    const tag = el.tagName.toLowerCase();
    if (!tag.includes("-")) continue;
    const hit = out.custom[tag] || (out.custom[tag] = { n: 0, attrs: {}, ...box(el) });
    hit.n += 1;
    for (const a of el.attributes) {
      if (a.name.startsWith("on") || a.name === "style" || a.name === "class") continue;
      hit.attrs[a.name] = (hit.attrs[a.name] || 0) + 1;
    }
  }
  for (const el of document.querySelectorAll("[role]")) {
    const role = (el.getAttribute("role") || "").trim();
    if (role) out.roles[role] = (out.roles[role] || 0) + 1;
  }
  for (const el of document.querySelectorAll("[aria-label]")) {
    // The label's shape, not its words: a name would be somebody's.
    const label = (el.getAttribute("aria-label") || "").trim();
    if (!label) continue;
    const shape = label.replace(/[A-Za-z]+/g, "A").replace(/\d+/g, "9").slice(0, 24);
    out.labels[shape] = (out.labels[shape] || 0) + 1;
  }
  for (const a of document.querySelectorAll("a[href]")) {
    const href = a.getAttribute("href") || "";
    const shape = href
      .replace(/\/r\/[A-Za-z0-9_]+/, "/r/<sub>")
      .replace(/\/u(ser)?\/[A-Za-z0-9_-]+/, "/user/<name>")
      .replace(/\/comments\/[a-z0-9]+/, "/comments/<id>")
      .replace(/\/room\/[^/?#]+/, "/room/<id>")
      .split("?")[0].slice(0, 48);
    out.links[shape] = (out.links[shape] || 0) + 1;
  }
  for (const b of document.querySelectorAll("button, faceplate-button, [role='button']")) {
    const words = (b.textContent || "").trim().slice(0, 28);
    if (words) out.buttonWords[words] = (out.buttonWords[words] || 0) + 1;
  }
  out.editable = document.querySelectorAll('[contenteditable="true"], textarea').length;
  out.fileInputs = document.querySelectorAll('input[type="file"]').length;
  out.videos = document.querySelectorAll("video, shreddit-player, shreddit-player-2").length;

  // And the same again, inside every open shadow root: how much of the page is hidden from an ordinary query.
  const roots = [document];
  for (let i = 0; i < roots.length && roots.length < 3000; i++) {
    let all = [];
    try { all = Array.from(roots[i].querySelectorAll("*")); } catch { all = []; }
    for (const el of all) {
      if (el.shadowRoot) {
        roots.push(el.shadowRoot);
        out.shadowRoots += 1;
      }
    }
  }
  for (const root of roots.slice(1)) {
    try {
      out.deepButtons += root.querySelectorAll("button, faceplate-button, [role='button']").length;
      for (const b of root.querySelectorAll("[aria-label]")) {
        const label = (b.getAttribute("aria-label") || "").trim();
        if (!label) continue;
        const shape = "(deep) " + label.replace(/[A-Za-z]+/g, "A").replace(/\d+/g, "9").slice(0, 24);
        out.labels[shape] = (out.labels[shape] || 0) + 1;
      }
    } catch { /* a closed one, or one that went away mid-walk */ }
  }
  return out;
}

/** Which markers find anything, in the light DOM and inside the shadow roots. */
function markers(sel) {
  const deep = (q) => {
    const roots = [document];
    for (let i = 0; i < roots.length && roots.length < 3000; i++) {
      let found = null;
      try { found = roots[i].querySelector(q); } catch { found = null; }
      if (found) return i === 0 ? "light" : "deep";
      let all = [];
      try { all = Array.from(roots[i].querySelectorAll("*")); } catch { all = []; }
      for (const el of all) if (el.shadowRoot) roots.push(el.shadowRoot);
    }
    return "";
  };
  const out = {};
  for (const name of Object.keys(sel)) {
    for (const q of sel[name]) {
      const where = deep(q);
      if (where) { out[name] = { q, where }; break; }
    }
  }
  return out;
}

/** The page, with every word and address replaced, so a fixture carries its shape and nobody's data. */
function sanitize() {
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walk.nextNode()) texts.push(walk.currentNode);
  for (const node of texts) {
    const said = node.nodeValue || "";
    if (!said.trim()) continue;
    node.nodeValue = said.replace(/\S/g, "x");
  }
  for (const el of document.querySelectorAll("[src], [href], [alt], [title], [poster]")) {
    for (const a of ["src", "href", "alt", "title", "poster"]) {
      if (!el.hasAttribute(a)) continue;
      const was = el.getAttribute(a) || "";
      if (a === "href" && was.startsWith("/")) {
        el.setAttribute(a, was.replace(/[A-Za-z0-9_-]{3,}/g, (m) => "x".repeat(Math.min(m.length, 8))));
      } else {
        el.setAttribute(a, a === "src" || a === "poster" ? "about:blank" : "xxxx");
      }
    }
  }
  // The attributes a post's facts live in are the point of the fixture, so they stay - with made-up values.
  for (const el of document.querySelectorAll("shreddit-post, shreddit-comment")) {
    if (el.hasAttribute("author")) el.setAttribute("author", "xxxxxxxx");
    if (el.hasAttribute("post-title")) el.setAttribute("post-title", "xxxxx xxxx xxx");
  }
  for (const s of document.querySelectorAll("script, style, link[rel=stylesheet], noscript")) s.remove();
  return document.documentElement.outerHTML;
}

const browser = await launchBrowser({
  profileDir: profileDir || `${process.env.TEMP || "/tmp"}/reddit-probe-profile`,
  hidden: false,
  locale: process.env.REDDIT_LOCALE || "en-US",
});
const page = (await browser.pages())[0] || (await browser.newPage());
try {
  console.log(`Opening ${url}${profileDir ? ` as the account in ${profileDir}` : " signed out"}`);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
  await delay(wait);

  const found = await page.evaluate(structure);
  const top = (obj, n = 25) => Object.entries(obj).sort((a, b) => {
    const av = typeof a[1] === "object" ? a[1].n : a[1];
    const bv = typeof b[1] === "object" ? b[1].n : b[1];
    return bv - av;
  }).slice(0, n);

  console.log(`\n== its own elements (${Object.keys(found.custom).length}) ==`);
  for (const [tag, info] of top(found.custom, 30)) {
    const attrs = Object.keys(info.attrs).slice(0, 14).join(" ");
    console.log(`  ${String(info.n).padStart(4)}  ${tag.padEnd(28)} ${attrs}`);
  }
  console.log(`\n== roles ==`);
  for (const [role, n] of top(found.roles)) console.log(`  ${String(n).padStart(4)}  ${role}`);
  console.log(`\n== labels, by shape ==`);
  for (const [shape, n] of top(found.labels, 20)) console.log(`  ${String(n).padStart(4)}  ${shape}`);
  console.log(`\n== links, by shape ==`);
  for (const [shape, n] of top(found.links, 20)) console.log(`  ${String(n).padStart(4)}  ${shape}`);
  console.log(`\n== button words ==`);
  for (const [words, n] of top(found.buttonWords, 20)) console.log(`  ${String(n).padStart(4)}  ${words}`);
  console.log(`\n== the rest ==`);
  console.log(`  shadow roots: ${found.shadowRoots}  (buttons inside them: ${found.deepButtons})`);
  console.log(`  boxes to type in: ${found.editable}   file boxes: ${found.fileInputs}   videos: ${found.videos}`);

  const hits = await page.evaluate(markers, SEL);
  const missing = Object.keys(SEL).filter((k) => !hits[k]);
  console.log(`\n== redditbot.js's markers on this page ==`);
  for (const name of Object.keys(hits)) {
    console.log(`  found ${name.padEnd(18)} ${hits[name].where.padEnd(6)} ${hits[name].q}`);
  }
  console.log(`\n  missing: ${missing.length ? missing.join(", ") : "none"}`);
  const deepOnes = Object.keys(hits).filter((k) => hits[k].where === "deep");
  if (deepOnes.length) console.log(`  only inside a shadow root: ${deepOnes.join(", ")}`);

  if (shot) {
    await page.screenshot({ path: shot, fullPage: false });
    console.log(`\n  picture: ${shot}`);
  }
  if (htmlOut) {
    const html = await page.evaluate(sanitize);
    fs.writeFileSync(htmlOut, html, "utf-8");
    console.log(`  page, with every word replaced: ${htmlOut}`);
  }
} finally {
  await browser.close().catch(() => {});
}
