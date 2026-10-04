/**
 * Folding console log lines into rows (webui/src/lib/logrows.ts), shared by the
 * Logs page and the Dashboard's log widget, run for real under Node.
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

const { foldRows, sourceInfo, kindOf } = await import("../webui/src/lib/logrows.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const L = (text, over = {}) => ({ time: "12:00:00", source: "discord_1", text, level: "info", ts: 100, id: 0, ...over });

// ── A message under the line that introduces it ──────────────────────────
let rows = foldRows([
  L("faris in #DM (DM)", { level: "recv" }),
  L("  hey what are you up to", { level: "info" }),
  L("Responding to faris", { level: "reply" }),
  L("  ▸ not much lol", { level: "info" }),
]);
check("the message folds into the line above it", rows.length === 2, JSON.stringify(rows.map((r) => r.text)));
check("the incoming line keeps its kind and quotes the message",
      rows[0].level === "recv" && rows[0].more[0] === "hey what are you up to", JSON.stringify(rows[0]));
check("the reply quotes what was sent, its arrow marker stripped",
      rows[1].level === "reply" && rows[1].more[0] === "not much lol", JSON.stringify(rows[1]));

// ── A rule of box characters is dropped ──────────────────────────────────
rows = foldRows([L("a line"), L("────────────────────"), L("another")]);
check("a horizontal rule is dropped", rows.length === 2 && rows.every((r) => r.text !== ""), JSON.stringify(rows.map((r) => r.text)));

// ── A continuation only folds into the same source, close in time ────────
rows = foldRows([
  L("faris in #DM", { source: "discord_1", ts: 100 }),
  L("  a message", { source: "discord_2", ts: 100 }),
]);
check("a continuation from another account is its own row", rows.length === 2, String(rows.length));
rows = foldRows([L("x in #DM", { ts: 100 }), L("  much later", { ts: 200 })]);
check("and one long after is too", rows.length === 2, String(rows.length));

// ── A clock and glyph the console printed are taken off ───────────────────
rows = foldRows([L("12:00:05 ⚙ starting up", { level: "system" })]);
check("the printed time and glyph are stripped from the text", rows[0].text === "starting up", rows[0].text);

// ── Thinking is split into a heading and the thought ──────────────────────
rows = foldRows([L("thinking (qwen3)\nLet me work out what they meant.", { level: "think" })]);
check("a thought keeps its first line as the row", rows[0].text === "thinking (qwen3)", rows[0].text);
check("and the rest as the body, folded until opened", rows[0].think && rows[0].think.body === "Let me work out what they meant.", JSON.stringify(rows[0].think));

// ── Sources named the way the app names them ──────────────────────────────
check("an app source has a friendly name", sourceInfo("supervisor", []).name === "App");
check("an account uses its own name and picture when known",
      sourceInfo("discord_1", [{ id: "discord_1", display_name: "Alicia", avatar: "a.png" }]).name === "Alicia");
check("and its slot number when not", sourceInfo("discord_2", []).name === "Discord #2");

// ── An unknown level lands in "Other" ─────────────────────────────────────
check("a level that is not a known kind becomes info", kindOf("weird") === "info" && kindOf("reply") === "reply");

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
