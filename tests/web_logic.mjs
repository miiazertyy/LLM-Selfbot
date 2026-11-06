/**
 * The web, in the panel, run for real under Node: the Chats status while a reply looks something up
 * (webui/src/lib/chatstatus.ts), and the "how long ago" each thing it saw online is shown with.
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

const { statusOf, STEPS } = await import("../webui/src/lib/chatstatus.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const now = 1_800_000_000;
const user = (state) => ({ id: "1", name: "faris", ts: now - 30, state });

let s = statusOf(user({ state: "looking", since: now - 4, eta: null, reason: "who won the f1 race" }), { now });
check("a reply looking something up says so", s.short === "Looking it up" && s.title === "Looking it up online",
      JSON.stringify(s));
check("with what it is finding out", s.detail === "Finding out: who won the f1 race", s.detail);
check("it is live, on the writing step", s.phase === "live" && STEPS[s.step] === "Writing", JSON.stringify(s));
s = statusOf(user({ state: "looking", since: now, eta: null, reason: "" }), { now });
check("and without a reason, still something plain", s.detail === "Checking online before it answers.", s.detail);
s = statusOf(user({ state: "writing", since: now, eta: null, reason: "" }), { now });
check("back to writing once it has looked", s.short === "Writing a reply", s.short);

console.log(`${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
