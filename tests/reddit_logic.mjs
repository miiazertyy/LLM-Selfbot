/**
 * redditbot.js's own logic, run for real: its pure functions under Node, and its page readers against saved
 * copies of Reddit's pages in a headless Chrome (tests/fixtures/reddit_*.html).
 *
 * The readers are the half that cannot be checked by reading the code: they are selectors, and a selector is only
 * right or wrong against a page. There is no Reddit account here yet, so the fixtures stand in for one; they
 * carry the shape of the real pages and nobody's words. When an account exists, reddit_probe.js --html writes
 * real ones the same way and they go in the same place.
 *
 * The one thing here that no other platform's test does is press a button through a shadow root: Reddit keeps its
 * buttons in them, so the fixtures build real ones and clickDeepInPage has to find its way in.
 *
 * Chrome is driven over its own debugging port rather than through Puppeteer: the runner's packages live in the
 * data directory, not in the checkout, and this has to run wherever the rest of the tests do.
 */
import { spawn } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const BOT = path.join(ROOT, "app", "platforms", "snapchat", "redditbot.js");
const FIXTURES = path.join(HERE, "fixtures");

let pass = 0;
const failed = [];
function check(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  PASS  ${name}`); }
  else { failed.push(name); console.log(`  FAIL  ${name}${extra ? `  [${extra}]` : ""}`); }
}

// ── The pure half, straight from the module ──────────────────────────────────
// Imported without its browser half: the file pulls in puppeteer through browser.js, which is not installed here,
// so the source is read and the pure parts are evaluated on their own.
const source = fs.readFileSync(BOT, "utf-8");
const pureSource = source
  .replace(/^import[\s\S]*?from "\.\/browser\.js";$/m, "")
  .replace(/^import \{ totp \} from "\.\/instagrambot\.js";$/m, "")
  .replace(/^export default class RedditBot \{[\s\S]*$/m, "");
const mod = await import(`data:text/javascript;base64,${Buffer.from(pureSource).toString("base64")}`);

console.log("== who is who ==");
check("a u/ name, a bare one and a link all give the username",
      mod.cleanUser("u/Theo-Wav") === "theo-wav" && mod.cleanUser("theo-wav") === "theo-wav"
      && mod.cleanUser("https://www.reddit.com/user/Theo-Wav/") === "theo-wav"
      && mod.cleanUser("/u/mara_k") === "mara_k");
check("a hyphen is a real character here, where X would have refused one",
      mod.cleanUser("a-b-c") === "a-b-c" && mod.chatIdFor("A-B-C") === "rd_a-b-c");
check("and what Reddit could never call anyone gives nothing",
      [mod.cleanUser("ab"), mod.cleanUser("a".repeat(21)), mod.cleanUser("theo.wav"), mod.cleanUser(""),
       mod.cleanUser("has space")].every((h) => h === ""));
check("nor do Reddit's own pages, which are not people",
      ["settings", "notifications", "submit", "r", "u", "all", "popular"].every((p) => mod.cleanUser(p) === ""));
check("a person is rd_ and their username", mod.chatIdFor("Theo-Wav") === "rd_theo-wav");
check("a group is rdg_ and its room, with Matrix's punctuation off",
      mod.groupIdFor("!abc123:reddit.com") === "rdg_abc123" && mod.groupIdFor("abc123") === "rdg_abc123");
check("a username with an underscore of its own is read back whole, not as a group",
      mod.userOf("rd_g_tom") === "g_tom" && mod.userOf("rdg_abc123") === ""
      && mod.CHAT_ID.test("rd_g_tom") && mod.CHAT_ID.test("rdg_abc123"));
check("and nothing else passes for one",
      !mod.CHAT_ID.test("rd_") && !mod.CHAT_ID.test("rdg_") && !mod.CHAT_ID.test("x_someone")
      && !mod.CHAT_ID.test("rd_ab") && !mod.CHAT_ID.test(`rd_${"a".repeat(21)}`));

console.log("\n== what a link says ==");
check("a post's id comes off its address, however it was written",
      mod.postIdFromHref("/r/cooking/comments/1abc2de/my_soup/") === "1abc2de"
      && mod.postIdFromHref("https://redd.it/1abc2de") === "1abc2de"
      && mod.postIdFromHref("/r/cooking/") === "");
check("a comment's id is the last piece of its permalink",
      mod.commentIdFromHref("/r/cooking/comments/1abc2de/my_soup/kk11aa1/") === "kk11aa1"
      && mod.commentIdFromHref("/r/cooking/comments/1abc2de/my_soup/") === "");
check("the subreddit comes off it too",
      mod.subOfHref("/r/AskReddit/comments/1abc2de/x/") === "AskReddit" && mod.subOfHref("/user/theo") === "");
check("and a post's address can be built back up",
      mod.postUrl("cooking", "1abc2de") === "https://www.reddit.com/r/cooking/comments/1abc2de/"
      && mod.postUrl("r/cooking", "1abc2de").includes("/r/cooking/"));
check("a thing id is the same id with its kind taken off",
      mod.bareId("t3_1abc2de") === "1abc2de" && mod.bareId("t1_kk11aa1") === "kk11aa1");
check("the username in a link is read back, and nothing else is",
      mod.userFromHref("/user/Theo-Wav/") === "theo-wav" && mod.userFromHref("/r/cooking/") === "");

console.log("\n== what Reddit says when it will not ==");
check("too much, too fast, and not enough karma each have a line",
      !!mod.warningReason("You're doing that too much. Try again in 7 minutes.")
      && !!mod.warningReason("This subreddit requires 50 karma to post")
      && !!mod.warningReason("Sorry, this post has been locked"));
check("and an ordinary page says nothing", mod.warningReason("xxxx xxxx xxxx") === "");

console.log("\n== the markers ==");
check("every one of them is a list, and none of them is empty",
      Object.values(mod.SEL).every((v) => Array.isArray(v) && v.length >= 1));
check("a post, a comment and the box to write in are looked for by Reddit's own elements first",
      mod.SEL.post[0] === "shreddit-post" && mod.SEL.comment[0] === "shreddit-comment"
      && mod.SEL.composer[0].includes("contenteditable"));

// ── The readers, against saved pages ─────────────────────────────────────────
const PORT = 9351;
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "reddit-logic-"));
const chromePaths = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
];
const chromeExe = chromePaths.find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!chromeExe) {
  console.log("\n== the readers ==\n  SKIP  no Chrome on this machine to read a page with");
} else {
  const chrome = spawn(chromeExe, ["--headless=new", `--remote-debugging-port=${PORT}`,
                                   `--user-data-dir=${profile}`, "--no-first-run", "--window-size=1000,700",
                                   "--allow-file-access-from-files", "about:blank"], { stdio: "ignore" });
  let ws = null;
  for (let i = 0; i < 60 && !ws; i++) {
    await sleep(250);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) ws = new WebSocket(page.webSocketDebuggerUrl);
    } catch { /* not up yet */ }
  }
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0;
  const waiting = new Map();
  ws.addEventListener("message", (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
  });
  const send = (method, params = {}) =>
    new Promise((r) => { const n = ++id; waiting.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  const run = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "threw");
    return r.result?.result?.value;
  };
  /** One of redditbot.js's readers, run inside the page exactly as the bot runs it. */
  const reader = async (name, ...args) => {
    const fn = mod[name];
    const call = `(${fn.toString().replace(/^export\s+/, "")})(${args.map((a) => JSON.stringify(a)).join(", ")})`;
    return run(call);
  };
  const open = async (file) => {
    await send("Page.enable");
    await send("Page.navigate", { url: pathToFileURL(path.join(FIXTURES, file)).href });
    await sleep(900);
  };

  console.log("\n== a feed ==");
  await open("reddit_feed.html");
  const posts = await reader("readPostsInPage", mod.SEL, "aliciamwwoff");
  check("every post on the page is read", posts.length === 4, JSON.stringify(posts.length));
  const one = posts.find((p) => p.id === "1abc2de");
  check("its facts come off its attributes, not its words",
        !!one && one.author === "xxxxxxxx" && one.subreddit === "xxxxxxx" && one.score === 128
        && one.comments === 41 && one.title === "xxxxx xxxx xxx",
        JSON.stringify(one));
  check("and so does its real moment, not a guess from \"2h\"",
        !!one && one.at === Date.parse("2026-10-31T09:14:00.000Z"));
  check("its address is absolute, so it can be opened from anywhere",
        !!one && one.url.includes("/r/xxxxxxx/comments/1abc2de/"));
  check("what it says is the slotted body", !!one && one.text.startsWith("xxxx xxxxxx"));
  check("a picture on a post is found", (posts.find((p) => p.id === "9xyz8fg") || {}).media.length === 1);
  check("a locked post says so, so it is left alone", (posts.find((p) => p.id === "9xyz8fg") || {}).locked === true);
  check("its own post is known to be its own",
        (posts.find((p) => p.id === "7mno4pq") || {}).mine === true
        && (posts.find((p) => p.id === "1abc2de") || {}).mine === false);
  check("an advert is marked as one, so it is never commented under",
        (posts.find((p) => p.id === "0ad0000") || {}).promoted === true);

  console.log("\n== a thread ==");
  await open("reddit_comments.html");
  const comments = await reader("readCommentsInPage", mod.SEL, "aliciamwwoff");
  check("every comment is read", comments.length === 3, JSON.stringify(comments.length));
  const top = comments.find((c) => c.id === "kk11aa1");
  check("with who said it, how deep it sits and what it scored",
        !!top && top.author === "xxxxxxx" && top.depth === 0 && top.score === 54);
  check("and what it said, off its slotted body", !!top && top.text.startsWith("xxxx xxxx"));
  check("its own comment is known to be its own, and carries the post it is under",
        (comments.find((c) => c.id === "kk22bb2") || {}).mine === true
        && (comments.find((c) => c.id === "kk22bb2") || {}).post === "1abc2de");
  check("a reply sits deeper than the comment it answers",
        (comments.find((c) => c.id === "kk22bb2") || {}).depth === 1);

  console.log("\n== the buttons, which are not in the page ==");
  const plain = await run(`document.querySelectorAll('button[slot="reply-button"]').length`);
  check("an ordinary query finds none of them: they are inside the shadow roots", plain === 0);
  const pressed = await run(`(${mod.clickDeepInPage.toString().replace(/^export\s+/, "")})(`
                            + `"shreddit-comment", "t1_kk11aa1", ${JSON.stringify(mod.SEL.commentReply)})`);
  check("and the deep one finds its way in and presses it", !!pressed && pressed.ok === true,
        JSON.stringify(pressed));
  const nowhere = await run(`(${mod.clickDeepInPage.toString().replace(/^export\s+/, "")})(`
                            + `"shreddit-comment", "t1_nothere", ${JSON.stringify(mod.SEL.commentReply)})`);
  check("one that has gone off the page says so rather than pressing something else",
        !!nowhere && nowhere.ok === false);

  console.log("\n== its inbox ==");
  await open("reddit_inbox.html");
  const inbox = await reader("readInboxInPage", mod.SEL);
  check("every row is read", inbox.length === 4, JSON.stringify(inbox.length));
  const reply = inbox.find((r) => r.id === "mm11aa1");
  check("a reply carries who, where and which post",
        !!reply && reply.author === "xxxxxxx" && reply.subreddit === "xxxxxxx" && reply.post === "1abc2de",
        JSON.stringify(reply));
  check("and its address is the comment's own, so the answer goes in the right place",
        !!reply && reply.url.includes("/mm11aa1/"));
  check("a mention is told from a reply by what the row says it is, not by its words",
        (inbox.find((r) => r.id === "mm22bb2") || {}).kind === "mention");
  check("and one already seen is not unread",
        (inbox.find((r) => r.id === "mm11aa1") || {}).unread === true
        && (inbox.find((r) => r.id === "mm33cc3") || {}).unread === false);

  console.log("\n== its chats ==");
  await open("reddit_chat.html");
  const rooms = await reader("readRoomsInPage", mod.SEL);
  check("every room is read", rooms.length === 3, JSON.stringify(rooms.length));
  const person = rooms.find((r) => r.room === "abc123");
  check("a person's room gives their name and whether it has something new",
        !!person && person.people.includes("xxxxxxxx") && person.unread === true && person.group === false,
        JSON.stringify(person));
  check("a group with two people in it is a group",
        (rooms.find((r) => r.room === "def456") || {}).group === true);
  check("and a read one is not unread", (rooms.find((r) => r.room === "ghi789") || {}).unread === false);

  const said = await reader("readChatInPage", mod.SEL, "aliciamwwoff");
  check("every message is read", said.length === 4, JSON.stringify(said.length));
  check("whose a message is comes off the sender where there is one",
        said[0].mine === false && said[1].mine === true);
  check("and off which side it is drawn on where there is not", said[2].mine === false);
  check("the time is not read back as part of what was said",
        !said[0].text.includes("18:02") && said[0].text.includes("xxxx xx xxxx xxxx?"),
        JSON.stringify(said[0].text));
  check("a picture with no words is a photo", said[2].kind === "photo" && said[2].media.length === 1);
  check("a link with no words is a link", said[3].kind === "link" && said[3].links.length === 1);
  check("and every one carries its real moment", said.every((m) => m.at > 0));

  console.log("\n== keys that do not move ==");
  const { keyed } = await import(pathToFileURL(path.join(ROOT, "app", "platforms", "snapchat",
                                                         "runner_core.js")).href);
  const once = keyed("rd_someone", said, { prefix: "r" });
  const twice = keyed("rd_someone", said, { prefix: "r" });
  check("the same chat read twice gives the same keys",
        JSON.stringify(once.map((k) => k.key)) === JSON.stringify(twice.map((k) => k.key)));
  check("and they are Reddit's own, not another platform's", once.every((k) => k.key.startsWith("r")));

  console.log("\n== signed in, or looking at a wall ==");
  // On the site itself, not in chat: chat.reddit.com is its own app and says none of this.
  await open("reddit_feed.html");
  const signedIn = await run(`(${((sel) => {
    const any = (sels) => sels.some((s) => document.querySelector(s));
    return any(sel.loggedIn) && !any(sel.loggedOut);
  }).toString()})(${JSON.stringify(mod.SEL)})`);
  check("a page with the user drawer on it reads as signed in", signedIn === true);

  ws.close();
  chrome.kill();
  await sleep(400);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may hold it a moment */ }
}

console.log(`\n${pass} passed, ${failed.length} failed`);
process.exitCode = failed.length ? 1 : 0;
