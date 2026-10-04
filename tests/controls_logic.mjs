/**
 * The logic behind this round's controls, run for real under Node: which
 * marks a dial's hand went past (webui/src/lib/passed.ts), how big a notch of
 * the tape is (counts.ts), and the switch examples (switchdemos.ts).
 */
const { passed } = await import("../webui/src/lib/passed.ts");
const { stepFor } = await import("../webui/src/lib/counts.ts");
const demos = await import("../webui/src/lib/switchdemos.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

console.log("== the marks a hand goes past ==");
check("going up, every mark it reaches, the one it lands on included", same(passed(0.5, 2.5), [1, 2]), JSON.stringify(passed(0.5, 2.5)));
check("going down, the same, nearest first", same(passed(2.5, 0.5), [2, 1]), JSON.stringify(passed(2.5, 0.5)));
check("leaving a mark it rests on does not pluck it again, either way",
  same(passed(1, 3), [2, 3]) && same(passed(3, 1), [2, 1]));
check("not moving plucks nothing", same(passed(2, 2), []));
check("fractions of a dial: fifty marks round it", same(passed(0, 0.1, 1 / 50), [1, 2, 3, 4, 5]), JSON.stringify(passed(0, 0.1, 1 / 50)));
check("and no rounding slip at a mark", same(passed(0.02, 0.04, 1 / 50), [2]), JSON.stringify(passed(0.02, 0.04, 1 / 50)));
check("hours past midnight keep counting (the clock wraps them)", same(passed(23.5, 25.2), [24, 25]));
check("a jump across the whole dial plucks the nearest two dozen, not all", passed(0, 100).length === 24 && passed(0, 100).at(-1) === 100);
check("nonsense in, nothing out", same(passed(NaN, 3), []) && same(passed(0, 3, 0), []));

console.log("\n== the tape's notches ==");
check("small counts go one by one", stepFor(10) === 1 && stepFor(0) === 1 && stepFor(23) === 1, `${stepFor(10)} ${stepFor(23)}`);
check("a couple of dozen by twos, fifties by fives", stepFor(30) === 2 && stepFor(60) === 5, `${stepFor(30)} ${stepFor(60)}`);
check("a cache of two hundred by tens", stepFor(200) === 10, String(stepFor(200)));
check("thousands by hundreds, always 1, 2 or 5 times a power of ten",
  stepFor(1200) === 100 && [7, 44, 180, 999, 25000].every((v) => /^[125]0*$/.test(String(stepFor(v)))),
  [7, 44, 180, 999, 25000].map(stepFor).join(","));
check("never a fraction", [0.5, 3, 11].every((v) => Number.isInteger(stepFor(v)) && stepFor(v) >= 1));

console.log("\n== the switch examples ==");
const keys = Object.keys(demos.DEMOS);
check("most switches have one (at least thirty)", keys.length >= 30, String(keys.length));
let ordered = true, lapses = true, short = true, sides = true;
for (const k of keys) {
  const d = demos.DEMOS[k];
  if (!d.on || !d.off) sides = false;
  for (const side of [d.on, d.off]) {
    if (!("lines" in side)) continue;
    const at = side.lines.map((l) => l.at);
    if (at.some((t, i) => i && t < at[i - 1])) ordered = false;
    if (side.lines.some((l) => l.until != null && l.until <= l.at)) lapses = false;
    if (side.lines.some((l) => (l.text ?? "").replace(/[[\]]/g, "").length > 30)) short = false;
    if (side.lines.some((l) => l.at >= (d.loop ?? 5200) - 400)) ordered = false;
  }
}
check("each has an on and an off", sides);
check("lines come in order, and well before the loop fades out", ordered);
check("typing dots end after they start", lapses);
check("every line is short enough for the little box", short);
check("the mentions and triggers in a line are picked out",
  same(demos.parts("[@juni] thoughts?"), [{ text: "@juni", lit: true }, { text: " thoughts?", lit: false }]));
const typed = { lines: [{ at: 100, who: "me", kind: "typing", until: 900 }, { at: 900, who: "me", text: "ok" }] };
check("the dots show while typing, and the reply takes over from them",
  demos.linesAt(typed, 500).length === 1 && demos.linesAt(typed, 950).length === 1 && demos.linesAt(typed, 950)[0].text === "ok");
check("nothing shows before it comes", demos.linesAt(typed, 50).length === 0);
check("the anti age-ban switch has none (it is not something to act out)", !demos.hasDemo("bot.anti_age_ban"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
