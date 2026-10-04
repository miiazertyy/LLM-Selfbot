/**
 * A Memory summary into the blocks it is drawn as: a headline, then labelled
 * points. Runs the real webui/src/lib/summarymd.ts under Node, with the ways a
 * model drifts from the asked-for shape.
 */
import { register } from "node:module";

// The app imports "./discordmd" without an extension, which its bundler allows
// and Node does not. This resolves those to the .ts file, for this test only.
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
const kinds = (b) => b.map((x) => x.kind).join(",");
const show = (b) => JSON.stringify(b);

// ── The shape asked for ──────────────────────────────────────────────────
let b = summaryBlocks("**Planning Saturday at the lake**\n- **Plans:** leaving at 8, Ana drives\n- **Vibe:** easy\n- **Waiting on:** you, for the time");
check("a headline, then one point per line", kinds(b) === "lead,point,point,point", kinds(b));
check("the headline without its asterisks", b[0].html === "Planning Saturday at the lake", b[0].html);
check("each label apart from what it says", b[1].label === "Plans" && b[1].html === "leaving at 8, Ana drives", show(b[1]));
check("a label of more than one word", b[3].label === "Waiting on" && b[3].html === "you, for the time", show(b[3]));

// ── How models drift ─────────────────────────────────────────────────────
b = summaryBlocks("## Planning Saturday\n* **Plans**: leaving at 8\n• **Vibe:** easy");
check("a # heading for the headline, * and • for bullets, the colon outside the bold",
      kinds(b) === "lead,point,point" && b[0].html ===