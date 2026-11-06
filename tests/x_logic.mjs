/**
 * xbot.js's own logic, run for real: its pure functions under Node, and its page readers against saved copies of
 * X's pages in a headless Chrome (tests/fixtures/x_*.html).
 *
 * The readers are the half that cannot be checked by reading the code: they are selectors, and a selector is only
 * right or wrong against a page. There is no X account here yet, so the fixtures stand in for one; they carry the
 * shape of the real pages and nobody's words. When an account exists, x_probe.js --html writes real ones the same
 * way and they go in the same place.
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
const XBOT = path.join(ROOT, "app", "platforms", "snapchat", "xbot.js");
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
const source = fs.readFileSync(XBOT, "utf-8");
const pureSource = source
  .replace(/^import[\s\S]*?from "\.\/browser\.js";$/m, "")
  .replace(/^import \{ totp \} from "\.\/instagrambot\.js";$/m, "")
  .replace(/^export default class XBot \{[\s\S]*$/m, "");
const mod = await import(`data:text/javascript;base64,${Buffer.from(pureSource).toString("base64")}`);

console.log("== who is who ==");
check("an @handle, a bare one and a link all give the handle",
      mod.cleanHandle("@Theo_Wav") === "theo_wav" && mod.cleanHandle("theo_wav") === "theo_wav"
      && mod.cleanHandle("https://x.com/Jack") === "jack" && mod.cleanHandle("twitter.com/Elon") === "elon");
check("and what X could never call anyone gives nothing",
      [mod.cleanHandle("theo.wav"), mod.cleanHandle("sixteencharacters"), mod.cleanHandle(""),
       mod.cleanHandle("@")].every((h) => h === ""));
check("nor do X's own pages, which are not people",
      ["home", "messages", "i", "settings", "explore"].every((p) => mod.cleanHandle(p) === ""));
check("a person is x_ and their handle", mod.chatIdFor("Theo_Wav") === "x_theo_wav");
check("a group is xg_ and its conversation's number", mod.groupIdFor("1111-2222") === "xg_11112222");
check("a handle with an underscore of its own is read back whole, not as a group",
      mod.handleOf("x_g_tom") === "g_tom" && mod.handleOf("xg_11112222") === ""
      && mod.CHAT_ID.test("x_g_tom") && mod.CHAT_ID.test("xg_11112222"));
check("and nothing else passes for one",
      !mod.CHAT_ID.test("x_") && !mod.CHAT_ID.test("xg_") && !mod.CHAT_ID.test("ig_someone")
      && !mod.CHAT_ID.test("x_aaaaaaaaaaaaaaaa"));     // sixteen, one past what X allows
check("a post's number comes off its address",
      mod.statusIdFromHref("/someone/status/1234567890123456789") === "1234567890123456789"
      && mod.statusIdFromHref("/someone") === "");
check("and so does whose it is, on either of X's two names",
      mod.handleFromHref("https://twitter.com/Elon/status/9") === "elon"
      && mod.handleFromHref("/someone") === "someone" && mod.handleFromHref("/home") === "");
check("a conversation's number comes off its address",
      mod.conversationIdFromHref("/messages/1111-2222") === "1111-2222");
check("what X says when it is unhappy becomes one plain line",
      mod.warningReason("You are unable to follow more people at this time")
        === "X will not let this account follow anyone else for now"
      && mod.warningReason("Your account has been locked.").includes("locked")
      && mod.warningReason("hello") === "");
check("every marker is a list, so each can have a fallback",
      Object.values(mod.SEL).every((v) => Array.isArray(v) && v.length >= 1));
check("and the ones that matter go through X's own hooks, not its words",
      ["tweet", "composer", "dmComposer", "like", "repost", "conversation", "messageEntry"]
        .every((k) => mod.SEL[k][0].includes("data-testid")));

// ── The readers, against saved pages ─────────────────────────────────────────

const PORT = 9348;
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "x-logic-"));
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
  /** One of xbot.js's readers, run inside the page exactly as the bot runs it. */
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

  console.log("\n== the conversation list ==");
  await open("x_messages.html");
  const rows = await reader("readConversationsInPage", mod.SEL);
  check("every conversation on the page is read", rows.length === 3, JSON.stringify(rows.length));
  const one = rows.find((r) => r.handles.includes("someone"));
  check("a person's row gives their handle and its conversation",
        one && one.conversation === "1111-2222" && !one.group, JSON.stringify(one));
  check("and an unread one says so", one && one.unread === true, JSON.stringify(one?.unread));
  const group = rows.find((r) => r.conversation === "3333-4444");
  check("a group is known by having more than one person in it",
        group && group.group === true && group.handles.length === 2, JSON.stringify(group?.handles));
  check("X's own chats come through too, for the runner to leave alone",
        rows.some((r) => r.handles.includes("grok")));

  console.log("\n== the open conversation ==");
  const msgs = await reader("readDmInPage", mod.SEL, "aliciamwwoff");
  check("every message on the page is read", msgs.length === 4, JSON.stringify(msgs.length));
  check("whose is whose, by which side of the pane it is drawn on",
        msgs.map((m) => m.mine).join(",") === "false,false,true,false",
        JSON.stringify(msgs.map((m) => m.mine)));
  check("its words, without the time stuck on the end",
        msgs[0].text === "xxx xxxx xx xxxxx", JSON.stringify(msgs[0].text));
  check("a photo with no words is still a message, and says it is a photo",
        msgs[1].kind === "photo" && !msgs[1].text, JSON.stringify(msgs[1]));
  check("a link is kept whole", (msgs[3].links || [])[0] === "https://example.com/xxxx",
        JSON.stringify(msgs[3].links));
  check("the real moment, off X's own <time>, not guessed from \"2h\"",
        msgs.every((m) => m.at > 0) && msgs[0].at < msgs[2].at, JSON.stringify(msgs.map((m) => m.at)));
  check("a reaction on one is read", (msgs[2].reactions || []).includes("❤️"),
        JSON.stringify(msgs[2].reactions));
  check("and each knows where it sits, so it can be reacted to",
        msgs.map((m) => m.idx).join(",") === "0,1,2,3");

  console.log("\n== keys that do not move ==");
  // The same conversation read twice gives the same keys, or the panel's log doubles every message.
  const core = await import(pathToFileURL(path.join(ROOT, "app/platforms/snapchat/runner_core.js")).href);
  const first = core.keyed("x_someone", msgs, { prefix: "x" });
  const again = core.keyed("x_someone", await reader("readDmInPage", mod.SEL, "aliciamwwoff"), { prefix: "x" });
  check("reading it again gives the same keys",
        first.map((m) => m.key).join() === again.map((m) => m.key).join());
  check("and they are X's own, told apart from the other platforms'",
        first.every((m) => m.key.startsWith("x")));

  console.log("\n== posts ==");
  await open("x_timeline.html");
  const posts = await reader("readTweetsInPage", mod.SEL, "aliciamwwoff");
  check("every post on the page is read", posts.length === 3, JSON.stringify(posts.length));
  check("its number and its address come off the permalink",
        posts[0].id === "1234567890123456789"
        && posts[0].url === "https://x.com/someone/status/1234567890123456789", JSON.stringify(posts[0].url));
  check("whose it is", posts[0].handle === "someone" && !posts[0].mine && posts[1].mine);
  check("its words", posts[0].text.includes("@aliciamwwoff"));
  check("the real moment, again off X's own <time>", posts[0].at === Date.parse("2026-11-01T08:00:00.000Z"));
  check("what it already did to it: the hooks say unlike and unretweet when it has",
        posts[1].liked === true && posts[1].reposted === true
        && posts[0].liked === false && posts[0].reposted === false);
  check("the counts, which live in the buttons' labels and not in the words",
        posts[0].counts.replies === 12 && posts[0].counts.reposts === 3 && posts[0].counts.likes === 40,
        JSON.stringify(posts[0].counts));
  check("a picture on one is seen", posts[1].media.some((m) => m.kind === "photo"));
  check("a reply is known as one, and who it answers",
        posts[2].reply === true && posts[2].replyTo.includes("aliciamwwoff"), JSON.stringify(posts[2].replyTo));

  console.log("\n== signed in, or looking at a wall ==");
  const signedIn = await run(`(${((sel) => {
    const any = (sels) => sels.some((s) => document.querySelector(s));
    return any(sel.loggedIn) && !any(sel.loggedOut);
  }).toString()})(${JSON.stringify(mod.SEL)})`);
  check("a page with the rail on it reads as signed in", signedIn === true);

  ws.close();
  chrome.kill();
  await sleep(400);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may hold it a moment */ }
}

console.log(`\n${pass} passed, ${failed.length} failed`);
process.exitCode = failed.length ? 1 : 0;
