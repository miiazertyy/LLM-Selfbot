/**
 * The sidebar's "still loading on another page" rules, run against the real
 * webui/src/lib/busy.ts (Node strips the types itself).
 */
// Read a store without importing svelte here: tests/ has no node_modules, and
// busy.ts resolves svelte from webui/ on its own.
const get = (store) => { let v; store.subscribe((x) => (v = x))(); return v; };

const busy = await import("../webui/src/lib/busy.ts");
const { begin, track, trackUntil, busyRoutes, doneRoutes, progressText } = busy;

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const shown = (r) => !!get(busyRoutes)[r];
const ticked = (r) => !!get(doneRoutes)[r];

// A quick load never shows: a spinner that flashes on every click is noise.
let end = begin("quick", "fast");
await wait(120);
end();
await wait(400);
check("a load under 300ms never shows", !shown("quick"));
check("and leaves no tick behind", !ticked("quick"));

// A slow one shows, with what it is doing.
end = begin("slow", "Replying to 3 people");
await wait(380);
check("a load past 300ms shows", shown("slow"));
check("with what it is doing, for the tooltip",
      (get(busyRoutes).slow?.labels || []).includes("Replying to 3 people"), JSON.stringify(get(busyRoutes)));

// It does not blink off the moment it ends.
end();
await wait(60);
check("it stays a moment after ending, rather than blinking", shown("slow"));
await wait(700);
check("then it goes", !shown("slow"));
check("and a tick takes its place", ticked("slow"));
await wait(1800);
check("the tick has its moment and goes", !ticked("slow"));

// Ending twice is harmless, so it can live in a finally without care.
end = begin("twice");
end(); end();
check("ending twice does not throw or go negative", busy._activeJobs().twice === undefined);

// Two jobs on one page: it is busy until both are done.
const a = begin("pair", "one"), b = begin("pair", "two");
await wait(350);
a();
await wait(700);
check("still busy while the second runs", shown("pair"));
b();
await wait(700);
check("idle once both are done", !shown("pair"));

// New work on a page cancels its tick: it is busy again, not finished.
end = begin("again");
await wait(350);
end();
await wait(700);
check("finished work ticks", ticked("again"));
const e2 = begin("again");
check("new work clears the tick straight away", !ticked("again"));
e2();

// track() hands back exactly what the promise gives.
check("track resolves with the value", (await track("t", Promise.resolve(42))) === 42);
let caught = null;
try { await track("t", Promise.reject(new Error("nope"))); } catch (e) { caught = e.message; }
check("and rejects with the error", caught === "nope");
check("and ends either way", busy._activeJobs().t === undefined, JSON.stringify(busy._activeJobs()));

// Work running elsewhere, watched until it says it is done.
// Long enough to be worth showing: done on the 15th check, ~600ms in.
let polls = 0;
trackUntil("remote", "Downloading", async () => ++polls >= 15, 40);
await wait(400);
check("a remote job is shown while it runs", shown("remote"), `polls=${polls}`);
await wait(1200);
check("and ends once it reports done", busy._activeJobs().remote === undefined, `polls=${polls}`);
check("a failed check does not count as finished", await (async () => {
  let n = 0;
  const stop = trackUntil("flaky", "x", async () => { n++; throw new Error("blip"); }, 30);
  await wait(200);
  const still = busy._activeJobs().flaky === 1;
  stop();
  return still && n > 1;
})());


// ── Real progress ───────────────────────────────────────────────────────────
const info = (r) => get(busyRoutes)[r];

// Eight steps move it eight times, and each is exact.
let steps = begin("steps", "Replying to 8 people");
steps.progress(0, 8);
await wait(350);
const seen = [];
for (let i = 1; i <= 8; i++) {
  steps.progress(i, 8);
  seen.push(`${info("steps").done}/${info("steps").total}`);
}
check("eight steps move it eight times",
      new Set(seen).size === 8 && seen[7] === "8/8", seen.join(" "));
check("and each one is exactly where it is", seen[2] === "3/8", seen[2]);
check("a handful of steps reads as a count", progressText(info("steps")) === "8/8");
steps();

const pct = begin("pct", "Downloading");
await wait(350);
pct.progress(27, 100);
check("27% fills exactly 27/100", info("pct").done === 27 && info("pct").total === 100);
check("and reads as a percentage", progressText(info("pct")) === "27%");
pct.progress(270, 1000);
check("bytes read as a percentage too", progressText(info("pct")) === "27%", progressText(info("pct")));
pct.progress(1500, 1000);
check("it never goes past full", info("pct").done === 1000, String(info("pct").done));
pct.progress(-4, 1000);
check("or below empty", info("pct").done === 0, String(info("pct").done));
pct();

// A job with no progress does not drag a real one down.
const real = begin("mix", "Describing pictures"), vague = begin("mix", "Loading");
await wait(350);
real.progress(9, 10);
check("an unknown job leaves a real 9/10 alone", progressText(info("mix")) === "9/10", progressText(info("mix")));
const second = begin("mix", "Adding pictures");
second.progress(1, 4);
check("two real ones average, each counting equally",
      ["57%", "58%"].includes(progressText(info("mix"))), progressText(info("mix")));  // (90% + 25%) / 2 = 57.5, which floating point rounds either way
real(); vague(); second();

// Nothing known: a spinner, not a made-up number.
const spin = begin("spin", "Loading");
await wait(350);
check("no progress means no number", info("spin").total === null && progressText(info("spin")) === "");
spin();

// A remote job reporting as it goes.
let n = 0;
trackUntil("remote2", "Downloading", async (report) => { n++; report(n * 20, 100); return n >= 5; }, 60);
await wait(420);
check("a remote job's reports come through", (info("remote2")?.done ?? 0) > 0, JSON.stringify(info("remote2")));
await wait(900);
check("and it ends when it says so", busy._activeJobs().remote2 === undefined);

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
