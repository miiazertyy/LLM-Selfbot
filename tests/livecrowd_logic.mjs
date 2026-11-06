/**
 * The practice LIVE's crowd (webui/src/lib/livecrowd.ts), under Node: who comes and what they do, how often, the
 * gifts and their combos, the pace of each crowd, who is watching, and the counts as TikTok writes them.
 */
const c = await import("../webui/src/lib/livecrowd.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

// A random function that plays back the same numbers every time.
const seeded = (seed = 7) => () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;

console.log("== what the crowd does ==");
const rnd = seeded(11);
const kinds = {};
for (let i = 0; i < 4000; i++) {
  const k = c.kindOf(rnd);
  kinds[k] = (kinds[k] ?? 0) + 1;
}
check("mostly comments and hearts, gifts and follows now and then, a share rarely",
      kinds.comment > kinds.like && kinds.like > kinds.join && kinds.join > kinds.gift && kinds.gift > kinds.share,
      JSON.stringify(kinds));
check("every kind happens", ["comment", "like", "join", "gift", "follow", "share"].every((k) => kinds[k] > 0));

const here = ["mara.k", "theo.wav"];
let joins = 0, joinedNew = 0, saidAgain = 0;
const recent = ["hiii", "omg hi!!"];
for (let i = 0; i < 600; i++) {
  const e = c.crowdEvent(rnd, recent, here);
  if (e.event === "join") { joins++; if (!here.includes(e.name)) joinedNew++; }
  if (e.event === "comment" && recent.includes(e.text)) saidAgain++;
  if (!e.name) check("every event has someone", false, JSON.stringify(e));
}
check("someone joining is someone not already in", joins > 0 && joinedNew === joins, `${joinedNew}/${joins}`);
check("what was just said is not said again straight away", saidAgain === 0, String(saidAgain));
const full = c.crowdEvent(() => 0.999, [], [...c.VIEWERS]);
check("with everyone in, a join turns into a comment", full.event !== "join", JSON.stringify(full));
let named = 0, said = 0;
for (let i = 0; i < 1500; i++) {
  const e = c.crowdEvent(rnd, [], here, "Lena");
  if (e.event !== "comment") continue;
  said++;
  if (e.text.includes("Lena")) named++;
  if (e.text.includes("{host}")) check("the host's name is put in", false, e.text);
}
check("now and then someone talks to the host by name", named > said * 0.08 && named < said * 0.3, `${named}/${said}`);
check("and never without a host to name", Array.from({ length: 400 }, () => c.crowdEvent(rnd, [], here))
      .every((e) => !c.TO_HOST.some((t) => e.text === t.replace("{host}", ""))));
check("a viewer keeps their level, 1 to 42", c.levelOf("mara.k") === c.levelOf("mara.k")
      && c.VIEWERS.every((n) => c.levelOf(n) >= 1 && c.levelOf(n) <= 42));
check("its badge coloured by tens", c.levelHue(3) === c.levelHue(9) && c.levelHue(3) !== c.levelHue(13)
      && c.levelHue(42) === c.levelHue(50));

console.log("\n== gifts ==");
const counts = { cheap: 0, dear: 0 };
for (let i = 0; i < 2000; i++) {
  const { gift, count } = c.giftOf(rnd);
  if (gift.coins <= 5) counts.cheap++; else counts.dear++;
  if (gift.coins > 5 && count !== 1) check("a dear gift comes one at a time", false, `${gift.name} x${count}`);
  if (count < 1 || count > 10) check("a combo is one to ten", false, String(count));
}
check("the cheap ones far more often", counts.cheap > counts.dear * 2, JSON.stringify(counts));
check("named as TikTok's chat names them", c.giftText(c.GIFTS[0], 5) === "Rose x5" && c.giftText(c.GIFTS[7]) === "Galaxy");

console.log("\n== the pace ==");
for (const level of ["quiet", "lively", "busy"]) {
  const [lo, hi] = c.LEVELS[level].gap;
  const waits = Array.from({ length: 200 }, () => c.nextDelay(level, rnd));
  check(`${level}: every wait in its range`, waits.every((w) => w >= lo && w <= hi), `${Math.min(...waits)}-${Math.max(...waits)}`);
}
check("busier crowds come faster", c.LEVELS.busy.gap[1] < c.LEVELS.lively.gap[1] && c.LEVELS.lively.gap[1] < c.LEVELS.quiet.gap[1]);

console.log("\n== who is watching ==");
let v = 5;
for (let i = 0; i < 80; i++) v = c.driftViewers(v, "busy", rnd);
check("a busy LIVE fills up", v >= c.LEVELS.busy.viewers[0], String(v));
let q = 2000;
for (let i = 0; i < 80; i++) q = c.driftViewers(q, "quiet", rnd);
check("and a quiet one empties out", q <= c.LEVELS.quiet.viewers[1] * 1.5, String(q));
check("never below one", c.driftViewers(1, "quiet", () => 0) >= 1);
check("counts as TikTok writes them", c.compactCount(999) === "999" && c.compactCount(1200) === "1.2K"
      && c.compactCount(2000) === "2K" && c.compactCount(45600) === "46K");
check("a viewer keeps their colour", c.hueOf("mara.k") === c.hueOf("mara.k") && c.hueOf("mara.k") !== c.hueOf("theo.wav"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
