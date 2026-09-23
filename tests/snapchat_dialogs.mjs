/**
 * handlePopup() against local pages. No Snapchat, no account: a plain browser
 * pointed at HTML served from this process.
 */
import http from "http";
import puppeteer from "puppeteer";
import SnapBot from "./snapbot.js";

const PAGES = {
  // What the user was stuck on: a card with a Next button, no form.
  "/web/welcome": `<div role="dialog" id="d"><p>Welcome to Snapchat for Web!</p>
      <button id="n" onclick="window.clicks=(window.clicks||0)+1;
        if(window.clicks>=2) document.getElementById('d').remove();
        else this.parentElement.querySelector('p').textContent='Step 2';">Next</button></div>`,
  // The sign-in page the probe landed on: Next is the form's submit.
  "/v2/login": `<form onsubmit="window.submits=(window.submits||0)+1;return false;">
      <input name="u"><button type="submit">Next</button></form>`,
  // A login form served somewhere that is not the auth path, to prove the
  // form rule holds on its own.
  "/web/other": `<form onsubmit="window.submits=(window.submits||0)+1;return false;">
      <input name="u"><button>Next</button></form>`,
  // Something that says Next but never goes away.
  "/web/stuck": `<div><button onclick="window.clicks=(window.clicks||0)+1">Next</button></div>`,
  // A chat as the bot knows it, every selector present.
  "/web/chat-ok": `<div role="listitem">Ana</div>
      <div id="cv-123"><ul><li class="T1yt2"><div class="KB4Aq"></div>
      <span class="ogn1z">hey</span></li></ul><div role="textbox"></div></div>`,
  // The same chat after a Snapchat build renamed the text class.
  "/web/chat-drift": `<div role="listitem">Ana</div>
      <div id="cv-123"><ul><li class="T1yt2"><div class="KB4Aq"></div>
      <span class="zz9Qx">hey</span></li></ul><div role="textbox"></div></div>`,
  // The app, with no chat open.
  "/web/sidebar": `<div role="listitem">Ana</div>`,
  // Buttons that must never be pressed.
  "/web/danger": `<div role="dialog"><button onclick="window.bad=1">Log out</button>
      <button onclick="window.bad=1">Allow</button><button onclick="window.bad=1">Delete</button></div>`,
};
const srv = http.createServer((req, res) => {
  res.setHeader("content-type", "text/html");
  res.end(`<!doctype html><body>${PAGES[req.url.split("?")[0]] || "not found"}</body>`);
}).listen(0);
const port = srv.address().port;

const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
const bot = new SnapBot();
bot.page = await browser.newPage();
bot.acceptCookies = async () => {};    // no consent banner on a local page

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};
const visit = async (p) => { await bot.page.goto(`http://127.0.0.1:${port}${p}`); };
const read = (k) => bot.page.evaluate((k) => window[k] || 0, k);

await visit("/web/welcome");
const w = await bot.handlePopup();
check("the welcome dialog is clicked through", (await read("clicks")) === 2, `clicks=${await read("clicks")}`);
check("and reported as cleared", w === 2, `returned ${w}`);

await visit("/v2/login");
await bot.handlePopup();
check("the sign-in page is left completely alone", (await read("submits")) === 0,
      `submits=${await read("submits")}`);

await visit("/web/other");
await bot.handlePopup();
check("a form's Next is never pressed, wherever it is", (await read("submits")) === 0,
      `submits=${await read("submits")}`);

await visit("/web/stuck");
await bot.handlePopup();
const stuck = await read("clicks");
check("a Next that never goes away is not pressed forever", stuck > 0 && stuck <= 3, `clicks=${stuck}`);

await visit("/web/danger");
await bot.handlePopup();
check("Log out / Allow / Delete are never pressed", (await read("bad")) === 0);

// ── selectorHealth() ─────────────────────────────────────────────────────
await visit("/web/chat-ok");
let h = await bot.selectorHealth();
check("a healthy chat reports nothing missing", h.missing.length === 0, JSON.stringify(h.missing));

await visit("/web/chat-drift");
h = await bot.selectorHealth();
check("a renamed class is named, not silently ignored",
      h.missing.length === 1 && h.missing[0].includes("span.ogn1z"), JSON.stringify(h.missing));

await visit("/web/sidebar");
h = await bot.selectorHealth();
check("chat selectors are not judged when no chat is open",
      h.missing.length === 0 && h.skipped.includes("message text"), JSON.stringify(h));

await browser.close();
srv.close();
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
