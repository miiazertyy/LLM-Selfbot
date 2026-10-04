/**
 * Splitting a message into text and @mentions. Runs the real
 * webui/src/lib/mentions.ts under Node.
 */
import { register } from "node:module";

// The app imports "./api" without an extension, which its bundler allows and
// Node does not. This resolves those to the .ts file, for this test only.
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(spec, ctx, next) {
  try { return await next(spec, ctx); }
  catch (e) {
    if (spec.startsWith(".") && !/\\.[a-z]+$/i.test(spec)) return next(spec + ".ts", ctx);
    throw e;
  }
}`));

const m = await import("../webui/src/lib/mentions.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};
const show = (s) => JSON.stringify(s);

let s = m.segments("hey did you see what <@105> said to <@!103>?");
check("text and mentions come out in order",
      show(s) === show([
        { kind: "text", text: "hey did you see what " }, { kind: "mention", id: "105" },
        { kind: "text", text: " said to " }, { kind: "mention", id: "103" }, { kind: "text", text: "?" },
      ]), show(s));
check("the nickname form <@!id> is a mention too", s[3].id === "103");
s = m.segments("<@692857354672275557>");
check("a message that is only a mention", s.length === 1 && s[0].id === "692857354672275557", show(s));
check("snowflakes stay exact strings", s[0].id === "692857354672275557");
s = m.segments("no mentions here, just <3 and <#123> and @everyone");
check("text with no user mention is left whole", s.length === 1 && s[0].kind === "text", show(s));
check("an empty message is nothing", m.segments("").length === 0);
check("hasMention agrees", m.hasMention("hi <@1>") && !m.hasMention("hi there"));
check("and gives the same answer when asked twice",
      m.hasMention("hi <@1>") && m.hasMention("hi <@1>") && m.hasMention("hi <@1>"));
// matchAll on a /g regex must not leave state behind between calls.
check("calling it twice gives the same answer",
      show(m.segments("a <@1> b")) === show(m.segments("a <@1> b")));

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
