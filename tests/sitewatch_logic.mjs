// The site watch and site fixes, with nothing real behind them: a stand-in tab, and a fix file on disk.
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { SiteWatch, applySiteFixes } = await import(pathToFileURL(path.join(ROOT, "app/platforms/snapchat/sitewatch.js")).href);

let passed = 0, failed = 0;
const check = (name, ok, detail = "") => {
  if (ok) { passed++; console.log(`  PASS  ${name}`); } else { failed++; console.log(`  FAIL  ${name}  ${detail}`); }
};

console.log("\n== a fix on disk ==");
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sitefix-"));
const sel = { composer: ["div.old"], sendButton: "button.send", other: ["a"] };
const said = [];
check("no file, nothing changes", applySiteFixes(sel, "x", dir, (m) => said.push(m)).length === 0 && sel.composer.length === 1 && !said.length);
fs.mkdirSync(path.join(dir, "config", "sitefixes"), { recursive: true });
const file = path.join(dir, "config", "sitefixes", "x.json");
fs.writeFileSync(file, JSON.stringify({ composer: ["div.new"], sendButton: "button.go", nosuch: ["q"], other: [] }));
const done = applySiteFixes(sel, "x", dir, (m) => said.push(m));
check("what it names goes in front of what was there", sel.composer.join() === "div.new,div.old", sel.composer.join());
check("a selector that was one on its own too", sel.sendButton.join() === "button.go,button.send", String(sel.sendButton));
check("nothing else moves", sel.other.join() === "a");
check("a name there is no such thing as is said, not used", said.some((m) => /nosuch/.test(m)) && !("nosuch" in sel), said.join("; "));
check("it says what it used", done.join() === "composer,sendButton" && said.some((m) => /composer, sendButton/.test(m)), said.join("; "));
fs.writeFileSync(file, "{ not json");
const said2 = [];
const before = sel.composer.join();
check("a broken file is said, and left out", applySiteFixes(sel, "x", dir, (m) => said2.push(m)).length === 0 && sel.composer.join() === before && said2.length === 1, said2.join());

console.log("\n== the watch ==");
const tab = (url, frames) => ({ isClosed: () => false, url: () => url, frames: () => frames });
const frame = (has) => ({ evaluate: async (_fn, sels) => sels.some((s) => has.includes(s)) });
let page = ["a.list", "b.box"];
const tabNow = () => tab("https://example.com/messages", [frame(page)]);
const reports = [];
const w = new SiteWatch({
  core: [{ name: "the list", sel: ["a.list", "a.older"], on: /messages/ }, { name: "the box", sel: ["b.box"], on: /messages/ },
         { name: "the other page's", sel: ["z"], on: /elsewhere/ }],
  pages: () => [tabNow()],
  report: (m) => reports.push(m.join()),
  everyMs: 1000, misses: 3,
});
await w.look();
check("everything there: nothing said", !reports.length);
page = ["b.box"];
await w.look();
await w.look();
check("gone twice is not yet gone", !reports.length, reports.join("|"));
await w.look();
check("three looks running, it says so", reports.join("|") === "the list", reports.join("|"));
await w.look();
check("and says it once", reports.length === 1);
check("not what cannot be looked for from this address", !reports.join().includes("other page"));
page = ["a.older", "b.box"];
await w.look();
check("back again (by any of its selectors), and it is taken back", reports.at(-1) === "", reports.join("|"));

const inFrame = new SiteWatch({
  core: [{ name: "the list", sel: ["deep"], on: /./ }],
  pages: () => [tab("https://x/", [frame([]), frame(["deep"])])],
  report: () => { throw new Error("it was there, in a frame"); }, misses: 1,
});
await inFrame.look();
check("in a frame counts: TikTok's inbox is in one", (inFrame.count.get("the list") || 0) === 0);

const lost = [];
const gone = new SiteWatch({
  core: [{ name: "the list", sel: ["a"], on: /./ }],
  pages: () => [{ isClosed: () => false, url: () => "https://x/", frames: () => [{ evaluate: async () => { throw new Error("detached"); } }] }],
  report: (m) => lost.push(m), misses: 1,
});
await gone.look();
check("a tab that cannot be asked says nothing about the page", !lost.length && !gone.count.has("the list"));
const closed = new SiteWatch({
  core: [{ name: "the list", sel: ["a"], on: /./ }],
  pages: () => { throw new Error("no browser"); },
  report: (m) => lost.push(m), misses: 1,
});
await closed.look();
check("nor does no browser at all", !lost.length);

const ticks = [];
const timed = new SiteWatch({ core: [], pages: () => (ticks.push(1), []), report: () => {}, everyMs: 50 });
await timed.tick();
check("not looked at the moment it starts: the page is still loading", !ticks.length);
await new Promise((r) => setTimeout(r, 70));
await timed.tick();
await timed.tick();
check("then once each time one is due, however often it is asked", ticks.length === 1, String(ticks.length));

console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
