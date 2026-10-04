/**
 * Searching a conversation, as the Chats tab does it: the real
 * webui/src/lib/chatsearch.ts, run under Node. Folding the way the server
 * does, words and quoted phrases, filters typed into chips, dates in the forms
 * people type them, and highlighting that keeps Discord's formatting whole.
 */
import { register } from "node:module";

register("data:text/javascript," + encodeURIComponent(`
export async function resolve(spec, ctx, next) {
  try { return await next(spec, ctx); }
  catch (e) {
    if (spec.startsWith(".") && !/\\.[a-z]+$/i.test(spec)) return next(spec + ".ts", ctx);
    throw e;
  }
}`));

const cs = await import("../webui/src/lib/chatsearch.ts");
const { discordInline } = await import("../webui/src/lib/discordmd.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

console.log("== folding and words ==");
check("any case, accents gone, as the server folds", cs.fold("Café ÉTÉ") === "cafe ete" && cs.fold("Straße") === "strasse",
      cs.fold("Café ÉTÉ"));
check("words split on spaces, quotes keep a phrase together",
      JSON.stringify(cs.splitWords('hey "good morning" you')) === JSON.stringify(["hey", "good morning", "you"]),
      JSON.stringify(cs.splitWords('hey "good morning" you')));

console.log("\n== what is highlighted ==");
let r = cs.matchRanges("On va au Café ce soir", ["cafe"]);
check("a word found with its accent, at the right place", r.length === 1 && "On va au Café ce soir".slice(r[0][0], r[0][1]) === "Café",
      JSON.stringify(r));
r = cs.matchRanges("ab ab", ["ab", "b a"]);
check("overlapping finds become one", r.length === 1 && r[0][0] === 0 && r[0][1] === 5, JSON.stringify(r));
r = cs.matchRanges("look <:cafe:12345> cafe", ["cafe"]);
check("never inside a custom emoji, which is drawn as a picture",
      r.length === 1 && r[0][0] === "look <:cafe:12345> ".length, JSON.stringify(r));
let h = cs.highlighted("**so** cafe time", ["cafe"], discordInline);
check("marked, with the formatting around it intact", h.includes("<strong>so</strong>") && h.includes("<mark>cafe</mark>"), h);
h = cs.highlighted("x https://a.com/b c", ["b c"], discordInline);
check("a mark never spans a tag: one across a link's end is two, each closed",
      !/<mark>[^<]*<(?!\/mark>)/.test(h) && (h.match(/<mark>/g) || []).length === 2
      && (h.match(/<\/mark>/g) || []).length === 2, h);
h = cs.highlighted("see https://x.com/cafe ok", ["cafe"], discordInline);
check("a link's address is left alone, only its words are marked",
      h.includes('href="https://x.com/cafe"') && h.includes("<mark>cafe</mark>"), h);
h = cs.highlighted("<b>cafe</b>", ["cafe"], discordInline);
check("the message's own markup stays escaped", h.includes("&lt;b&gt;") && !h.includes("<b>"), h);

console.log("\n== dates as typed ==");
const now = new Date(2026, 9, 1, 15, 0);
const day = (s) => { const x = cs.parseSpan(s, now); return x ? new Date(x.start * 1000).toDateString() : null; };
check("today and yesterday", day("today") === new Date(2026, 9, 1).toDateString()
      && day("Yesterday") === new Date(2026, 8, 30).toDateString());
check("2026-09-30, and a day written with slashes", day("2026-09-30") === new Date(2026, 8, 30).toDateString()
      && day("30/09/2026") === new Date(2026, 8, 30).toDateString());
check("month words: sep 30, 30 september 2025", day("sep 30") === new Date(2026, 8, 30).toDateString()
      && day("30 september 2025") === new Date(2025, 8, 30).toDateString());
const month = cs.parseSpan("2026-09", now);
check("a month is the whole month", !!month && (month.end - month.start) / 86400 >= 28 && (month.end - month.start) / 86400 <= 31);
const year = cs.parseSpan("2025", now);
check("a year is the whole year", !!year && year.label === "2025" && Math.round((year.end - year.start) / 86400) === 365);
check("nonsense is no date", cs.parseSpan("banana", now) === null && cs.parseSpan("31/02/2026", now) === null);

console.log("\n== filters typed into the box ==");
const them = { name: "Ry.55", username: "nibIII" };
let t = cs.takeFilters("from:me has:pics hello ", cs.noFilters(), them);
check("a finished filter becomes a chip and leaves the box", t.took === 2 && t.filters.from === "me"
      && t.filters.has.includes("image") && t.text.trim() === "hello", JSON.stringify(t));
t = cs.takeFilters("from:me", cs.noFilters(), them);
check("one still being typed stays as it is", t.took === 0 && t.text === "from:me");
t = cs.takeFilters("from:me", cs.noFilters(), them, true);
check("Enter takes it too", t.took === 1 && t.filters.from === "me");
t = cs.takeFilters("from:ry has:nonsense ", cs.noFilters(), them);
check("their name means them; something that is no kind stays as words",
      t.filters.from === "them" && t.filters.has.length === 0 && t.text.includes("has:nonsense"), JSON.stringify(t));
t = cs.takeFilters("after:2026-09-01 before:today ", cs.noFilters(), them);
const q = cs.toQuery(t.text, t.filters);
check("dates become a window: after one day, before another", q.before !== null && q.after !== null && q.after < q.before,
      JSON.stringify(q));
check("from whom goes as mine", cs.toQuery("", { from: "them", has: [], dates: [] }).mine === false
      && cs.toQuery("", { from: "me", has: [], dates: [] }).mine === true && cs.toQuery("x", cs.noFilters()).mine === null);
check("nothing asked is empty", cs.isEmpty(cs.toQuery("  ", cs.noFilters())) && !cs.isEmpty(cs.toQuery("a", cs.noFilters())));
const tok = cs.tokenAt("hello has:im", 12);
check("the token at the caret, key and value", tok.key === "has" && tok.value === "im" && tok.start === 6, JSON.stringify(tok));
check("what kind a word means", cs.hasFrom("pictures") === "image" && cs.hasFrom("voice") === "sound" && cs.hasFrom("zz") === null);

console.log("\n== links ==");
check("a link's site, without www", cs.domainOf("https://www.youtube.com/watch?v=1") === "youtube.com");
check("a link as a person reads it", cs.prettyUrl("https://www.x.com/a/b/") === "x.com/a/b");

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
