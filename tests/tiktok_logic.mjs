/**
 * TikTok's runner, its pure parts, under Node: the ids it gives people, the handles it reads off links, TikTok's
 * warnings said plainly, the days above messages, and the keys that keep a conversation read twice from doubling.
 *
 * tiktokbot.js imports the browser (puppeteer-extra) at the top, which only the app's install has: those two
 * packages are stood in for here, and nothing that needs a browser is called.
 */
import { registerHooks } from "node:module";

const STUBS = {
  "puppeteer-extra": "export default { use() {}, launch() { throw new Error('no browser in a test'); } };",
  "puppeteer-extra-plugin-stealth": "export default function Stealth() { return {}; }",
};
registerHooks({
  resolve(specifier, context, next) {
    if (STUBS[specifier]) return { url: "data:text/javascript," + encodeURIComponent(STUBS[specifier]), shortCircuit: true };
    return next(specifier, context);
  },
});

const bot = await import("../app/platforms/snapchat/tiktokbot.js");
const core = await import("../app/platforms/snapchat/runner_core.js");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

console.log("== who someone is ==");
check("a handle is a chat id the bridge keeps", bot.chatIdFor("@Theo.Wav") === "tt_theo-wav", bot.chatIdFor("@Theo.Wav"));
check("and reads back to the same handle", bot.handleOf("tt_theo-wav") === "theo.wav" && bot.handleOf("tt_mara_k") === "mara_k");
check("nothing in, nothing out", bot.chatIdFor("") === "" && bot.handleOf("123") === "" && bot.handleOf("snapchat-id") === "");
check("a chat id is never all digits (Discord's) and is a safe file name",
      !/^\d+$/.test(bot.chatIdFor("1234")) && /^tt_[a-z0-9_-]+$/.test(bot.chatIdFor("a.b_c.d")));
check("a profile link gives its handle", bot.handleFromHref("/@theo.wav") === "theo.wav"
      && bot.handleFromHref("https://www.tiktok.com/@Mara_K?lang=en") === "mara_k"
      && bot.handleFromHref("https://www.tiktok.com/@lakeside.films/video/7412345678901234567") === "lakeside.films");
check("and anything else none", bot.handleFromHref("/foryou") === "" && bot.handleFromHref("/@x") === ""
      && bot.handleFromHref("") === "");

console.log("\n== TikTok's warnings, said plainly ==");
check("too fast", /too fast/.test(bot.warningReason("You're sending messages too fast. Take a break.")));
check("only friends", /friends/.test(bot.warningReason("Only friends can send messages to each other")));
check("their privacy", /privacy/.test(bot.warningReason("Due to their privacy settings, you can't message")));
check("in French too", /too fast/.test(bot.warningReason("Vous envoyez des messages trop rapidement")));
check("not sent at all", /did not send/.test(bot.warningReason("This message couldn't be sent")));
check("an ordinary line is no warning", bot.warningReason("hey how are you") === "");

console.log("\n== the days above messages ==");
const now = new Date(2026, 9, 8, 15, 0);   // a Thursday
check("today and yesterday", core.dayOfLabel("Today", now) === "2026-10-08" && core.dayOfLabel("Yesterday 9:41 PM", now) === "2026-10-07");
check("in French", core.dayOfLabel("Aujourd'hui", now) === "2026-10-08" && core.dayOfLabel("hier", now) === "2026-10-07");
check("a weekday is the last one before today", core.dayOfLabel("Monday", now) === "2026-10-05");
check("a date with no year is this year, or last when it is still to come",
      core.dayOfLabel("Sep 28", now) === "2026-09-28" && core.dayOfLabel("Dec 30", now) === "2025-12-30");
check("day first outside the US", core.dayOfLabel("05/10/2026", now, false) === "2026-10-05"
      && core.dayOfLabel("10/05/2026", now, true) === "2026-10-05");
check("no day in it, none", core.dayOfLabel("", now) === "" && core.dayOfLabel("9:41 PM", now) === "");

console.log("\n== the time labels over messages ==");
const at = (y, mo, d, h, mi) => new Date(y, mo - 1, d, h, mi).getTime();
check("a time alone is today then", core.atOfLabel("14:05", now) === at(2026, 10, 8, 14, 5));
check("one still to come today was yesterday's (just after midnight)", core.atOfLabel("23:50", now) === at(2026, 10, 7, 23, 50));
check("TikTok's full label, the date then the time", core.atOfLabel("September 4, 2026 00:15", now) === at(2026, 9, 4, 0, 15));
check("with AM and PM", core.atOfLabel("Yesterday 9:41 PM", now) === at(2026, 10, 7, 21, 41)
      && core.atOfLabel("September 4, 2026 12:15 AM", now) === at(2026, 9, 4, 0, 15));
check("in French", core.atOfLabel("4 septembre 2026 00:15", now) === at(2026, 9, 4, 0, 15));
check("no time in it, none", core.atOfLabel("September 4, 2026", now) === 0 && core.atOfLabel("", now) === 0);

console.log("\n== reading a conversation twice ==");
const raw = [
  { day: "Yesterday", mine: false, text: "hi" },
  { mine: true, text: "hey!" },
  { mine: false, text: "hi" },
  { mine: false, text: "", kind: "video", links: [{ url: "https://www.tiktok.com/@a.b/video/1" }] },
];
const a = core.keyed("tt_theo-wav", raw, { prefix: "k" });
const b = core.keyed("tt_theo-wav", raw, { prefix: "k" });
check("the same messages get the same keys", a.map((m) => m.key).join() === b.map((m) => m.key).join());
check("two of the same words the same day are two messages", a[0].key !== a[2].key);
check("keys carry the platform's prefix", a.every((m) => /^k[0-9a-f]{24}$/.test(m.key)));
check("another chat, other keys", core.keyed("tt_mara_k", raw, { prefix: "k" })[0].key !== a[0].key);
check("a shared video keeps its kind and link", a[3].kind === "video" && a[3].links[0].url.includes("/video/"));
check("each message keeps the day it was under", a.every((m) => /^\d{4}-\d{2}-\d{2}$/.test(m.day)));
const withAt = core.keyed("tt_theo-wav", [{ mine: false, text: "hi", at: at(2026, 9, 4, 0, 15), idx: 3, author: "theo.wav",
                                            quote: "you up?" }], { prefix: "k" });
check("a message with a time is on that day", withAt[0].day === "2026-09-04" && withAt[0].at === at(2026, 9, 4, 0, 15));
check("and keeps where it sits, who sent it and what it answers", withAt[0].idx === 3 && withAt[0].author === "theo.wav"
      && withAt[0].quote === "you up?");

// ── Going out: what may still be done today, and the bridge's answers taken one at a time ──
const fs = await import("node:fs");
const os = await import("node:os");
const path = await import("node:path");
const work = fs.mkdtempSync(path.join(os.tmpdir(), "tt_logic_"));

console.log("\n== so many a day ==");
const file = path.join(work, "budget_1.json");
const budget = core.createBudget(file, { likes: 3, comments: 1 });
check("a fresh day has all of them", budget.left("likes") === 3 && budget.allowed("comments") && budget.used("likes") === 0);
budget.spend("likes");
budget.spend("likes");
check("each one spent is counted", budget.used("likes") === 2 && budget.left("likes") === 1 && budget.allowed("likes"));
budget.spend("comments");
check("and the last one closes it for the day", !budget.allowed("comments") && budget.left("comments") === 0);
const again = core.createBudget(file, { likes: 3, comments: 1 });
check("a restart does not hand out a fresh day", again.used("likes") === 2 && !again.allowed("comments"));
fs.writeFileSync(file, JSON.stringify({ day: "2001-01-01", counts: { likes: 99 } }));
check("a new day starts again", again.left("likes") === 3 && again.allowed("comments"));
check("something with no limit is never allowed", !again.allowed("visits") && again.left("visits") === 0);
fs.writeFileSync(file, "{broken");
check("a broken file is a fresh day, not a crash", again.allowed("likes") && again.spend("likes") === 2);

console.log("\n== the bridge's answers, one at a time ==");
const prev = process.env.TIKTOK_MIN_SEND_GAP_MS;
const c = core.createCore({ prefix: "tiktok", env: "TIKTOK", account: 7, dataDir: work, tag: "[t]" });
c.ensureFiles();
fs.writeFileSync(c.files.responses, JSON.stringify({ a: { text: "one", kind: "dm" }, b: { text: "two", kind: "live" } }));
const seenFirst = c.responses();
const took = c.take("a");
check("one answer is taken off the file", took.text === "one" && !("a" in c.responses()) && "b" in c.responses());
// The bridge writes another while the runner is sending the first.
const meanwhile = c.responses();
meanwhile.c = { text: "three", kind: "dm" };
fs.writeFileSync(c.files.responses, JSON.stringify(meanwhile));
c.putBack("a", { ...took, _attempts: 1 });
const after = c.responses();
check("putting it back keeps what the bridge added meanwhile", after.a?._attempts === 1 && after.c?.text === "three" && after.b);
check("one taken by another loop is gone, not taken twice", c.take("zzz") === null && Object.keys(seenFirst).length === 2);
fs.writeFileSync(c.files.responses, "[1,2]");
check("a list where answers should be reads as none", Object.keys(c.responses()).length === 0);
if (prev === undefined) delete process.env.TIKTOK_MIN_SEND_GAP_MS;
fs.rmSync(work, { recursive: true, force: true });

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
