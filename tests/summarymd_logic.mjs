/**
 * The Memory summary parser: the headline and the labelled points a summary is
 * drawn from (webui/src/lib/summarymd.ts), run for real under Node.
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

const { summaryBlocks } = await import("../webui/src/lib/summarymd.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};
const kinds = (bs) => bs.map((b) => b.kind).join(",");
const strip = (h) => h.replace(/<[^>]+>/g, "");

// ── The shape the model is asked for ──────────────────────────────────────
let b = summaryBlocks("**Planning Saturday at the lake**\n- **Plans:** leaving at 8, Ana drives\n- **Vibe:** easy, lots of jokes\n- **Waiting on:** you, for the time");
check("a bold first line is the headline", b[0].kind === "lead" && strip(b[0].html) === "Planning Saturday at the lake", JSON.stringify(b[0]));
check("then one point per bullet", kinds(b) === "lead,point,point,point", kinds(b));
check("each with its label and its text", b[1].label === "Plans" && strip(b[1].html) === "leaving at 8, Ana drives", JSON.stringify(b[1]));
check("Waiting on is kept as the label", b[3].label === "Waiting on", b[3].label);

// ── The ways a model drifts, all read the same ────────────────────────────
b = summaryBlocks("# Catching up after a while\n* **Mood:** warm\n* Topics: work and the trip");
check("a # heading is a headline too", b[0].kind === "lead" && strip(b[0].html) === "Catching up after a while");
check("a * bullet is a point", b[1].kind === "point" && b[1].label === "Mood");
check("a plain 'Label:' with no bold is NOT a label, it is text",
      b[2].kind === "point" && b[2].label === "" && strip(b[2].html) === "Topics: work and the trip", JSON.stringify(b[2]));

b = summaryBlocks("**Just chatting**\n- **Plans**: none really\n- **A long label that is really a sentence:** hello");
check("a colon outside the bold still reads as the label", b[1].label === "Plans" && strip(b[1].html) === "none really", JSON.stringify(b[1]));
check("a label of more than three words is not one", b[2].label === "" && strip(b[2].html).startsWith("A long label"), JSON.stringify(b[2]));

// ── An old prose summary, from before the shape ───────────────────────────
b = summaryBlocks("You and Ana talked about the match. She seemed a bit down.\nYou made a plan for Saturday.");
check("prose with no headline stays paragraphs", kinds(b) === "para,para", kinds(b));

// ── A short first line with points under it ───────────────────────────────
b = summaryBlocks("Weekend plans\n- **When:** Saturday");
check("a short first line before points is the headline", b[0].kind === "lead" && strip(b[0].html) === "Weekend plans");

// ── Safety: the text is escaped, the tags are ours ────────────────────────
b = summaryBlocks("- **Note:** <script>alert(1)</script> **bold** stays");
check("any HTML in the text is escaped", !b[0].html.includes("<script>") && b[0].html.includes("&lt;script&gt;"), b[0].html);
check("but our own bold is a real tag", b[0].html.includes("<strong>bold</strong>"), b[0].html);

// ── Nothing at all ────────────────────────────────────────────────────────
check("empty text is no blocks", summaryBlocks("").length === 0 && summaryBlocks("   \n  ").length === 0);

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
