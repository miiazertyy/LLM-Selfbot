/**
 * Big Picture Mode's director, run for real under Node: what the centre stage
 * shows, and when it moves on (webui/src/lib/bigpicture/director.ts).
 */
const D = await import("../webui/src/lib/bigpicture/director.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const t = 1_000_000;
const row = (key, phase, step, extra = {}) => ({ key, phase, step, ts: t - 30, ...extra });

// ── What gets the stage ───────────────────────────────────────────────────
let s = D.initial(t);
s = D.tick(s, [row("a", "live", 1, { eta: t + 60 }), row("b", "live", 2), row("c", "needs", 0, { ts: t - 5 })], t);
check("a reply being written beats one waiting and a new arrival", s.spotlight === "b", s.spotlight);

s = D.initial(t);
const waits = [row("a", "live", 1, { eta: t + 90 }), row("b", "live", 1, { eta: t + 10 })];
s = D.tick(s, waits, t);
check("replies that are only waiting do not hold the stage: the scenes play", s.spotlight === null && s.idle !== null,
      String(s.spotlight));
check("though the queue still puts the one that fires sooner first", D.ranked(waits, t)[0].key === "b");
s = D.tick(s, [...waits, row("p", "live", 3, { eta: t + 20 })], t + 1);
check("nor does one pacing itself before it sends: that is waiting too", s.spotlight === null, String(s.spotlight));

s = D.initial(t);
s = D.tick(s, [row("old", "needs", 0, { ts: t - 600 }), row("new", "needs", 0, { ts: t - 5 })], t);
check("a message just arrived takes the stage", s.spotlight === "new", s.spotlight);
s = D.tick(s, [row("old", "needs", 0, { ts: t - 600 }), row("new", "needs", 0, { ts: t - 5 })], t + D.FRESH + 1);
check("for long enough to see it land, then the scenes again", s.spotlight === null && s.idle !== null, String(s.spotlight));

s = D.initial(t);
s = D.tick(s, [row("x", "needs", 0, { ts: t - 7200 }), row("off", "off", 0)], t);
check("old news and people it is off for do not take the stage", s.spotlight === null && s.idle !== null);

// ── It does not flicker, and never leaves mid-reply ──────────────────────
s = D.initial(t);
s = D.tick(s, [row("a", "live", 2)], t);
s = D.tick(s, [row("a", "live", 2), row("b", "live", 4)], t + 30);
check("a reply being written keeps the stage, however busy it gets", s.spotlight === "a", s.spotlight);

s = D.initial(t);
s = D.tick(s, [row("a", "live", 1, { eta: t + 100, ts: t })], t);
s = D.tick(s, [row("a", "live", 1, { eta: t + 100, ts: t }), row("b", "live", 2)], t + 3);
check("a reply being written waits a few seconds before it takes over", s.spotlight === "a", s.spotlight);
s = D.tick(s, [row("a", "live", 1, { eta: t + 100, ts: t }), row("b", "live", 2)], t + D.HOLD_MIN + 1);
check("and then does", s.spotlight === "b", s.spotlight);

s = D.initial(t);
s = D.tick(s, [row("w", "live", 2)], t);
s = D.tick(s, [row("w", "live", 3, { eta: t + 60 })], t + D.HOLD_MIN + 1);
check("written, then only waiting to be sent: the scenes come back", s.spotlight === null, String(s.spotlight));
s = D.tick(s, [row("w", "live", 4)], t + D.HOLD_MIN + 20);
check("and the moment it is typed out, it is live again", s.spotlight === "w", String(s.spotlight));

// ── An answered conversation stays up a moment ───────────────────────────
s = D.initial(t);
s = D.tick(s, [row("a", "live", 4), row("b", "live", 1, { eta: t + 5 })], t);
s = D.tick(s, [row("b", "live", 1, { eta: t + 5 })], t + 1);
check("once answered it stays, so the reply is seen", s.spotlight === "a", s.spotlight);
s = D.tick(s, [row("b", "live", 1, { eta: t + 5 })], t + 1 + D.AFTER_DONE + 1);
check("then, with the rest only waiting, the scenes", s.spotlight === null, String(s.spotlight));
s = D.tick(s, [row("b", "live", 2)], t + 1 + D.AFTER_DONE + 2);
check("until the next one is being written", s.spotlight === "b", String(s.spotlight));

// ── Nothing happening ────────────────────────────────────────────────────
s = D.initial(t);
s = D.tick(s, [], t);
check("with nobody waiting, the idle scenes", s.spotlight === null && D.sceneOf(s) === "recent", String(D.sceneOf(s)));
s = D.tick(s, [], t + D.IDLE_SCENE + 1);
check("which move on by themselves", D.sceneOf(s) === "today", String(D.sceneOf(s)));
s = D.tick(s, [], t + 2 * (D.IDLE_SCENE + 1));
check("round all of them", D.sceneOf(s) === "people", String(D.sceneOf(s)));
s = D.tick(s, [row("n", "needs", 0, { ts: t + 30 })], t + 40);
check("and a new message ends them", s.spotlight === "n" && s.idle === null, JSON.stringify(s));

// ── Idle scenes with people to show ──────────────────────────────────────
s = D.initial(t);
s = D.tick(s, [], t, D.MEMORY_CYCLE);
check("with summaries to show, a memory comes up first", D.sceneOf(s, D.MEMORY_CYCLE) === "memory", String(D.sceneOf(s, D.MEMORY_CYCLE)));
s = D.tick(s, [], t + D.SCENE_TIME.memory + 1, D.MEMORY_CYCLE);
check("a memory stays up longer than a number", D.sceneOf(s, D.MEMORY_CYCLE) === "today", String(D.sceneOf(s, D.MEMORY_CYCLE)));
s = D.tick(s, [], t + D.SCENE_TIME.memory + 1, D.MEMORY_CYCLE);
check("it does not move on before a plain scene's time is up", D.sceneOf(s, D.MEMORY_CYCLE) === "today");
s = D.tick(s, [], t + D.SCENE_TIME.memory + D.IDLE_SCENE + 2, D.MEMORY_CYCLE);
check("then a memory again, every other scene", D.sceneOf(s, D.MEMORY_CYCLE) === "memory", String(D.sceneOf(s, D.MEMORY_CYCLE)));

// ── By hand ──────────────────────────────────────────────────────────────
const rows = [row("a", "live", 2), row("b", "live", 1, { eta: t + 20 }), row("c", "needs", 0, { ts: t - 10 })];
s = D.tick(D.initial(t), rows, t);
s = D.pick(s, "c", t + 1);
s = D.tick(s, rows, t + 5);
check("a click holds the stage on that one", s.spotlight === "c", s.spotlight);
s = D.tick(s, rows, t + 1 + D.MANUAL_HOLD + 1);
check("for a while, then the director takes over again", s.spotlight === "a", s.spotlight);
s = D.step(s, rows, 1, t + 60);
check("the right arrow moves to the next in rank", s.spotlight === "b", s.spotlight);
s = D.step(s, rows, -1, t + 61);
check("and the left arrow back", s.spotlight === "a", s.spotlight);
s = D.step(s, rows, -1, t + 62);
check("round from the first to the last", s.spotlight === "c", s.spotlight);
s = D.togglePin(s);
s = D.tick(s, [row("z", "live", 4)], t + 500);
check("held with Space, it stays even when that one is gone", s.pinned && s.spotlight === "c", JSON.stringify(s));
s = D.togglePin(s);
s = D.tick(s, [row("z", "live", 4)], t + 501);
check("and let go, the director moves on at once", !s.pinned && s.spotlight === "z", s.spotlight);

// ── The scene list, from what there is to show ────────────────────────────
check("the day's numbers are always there", JSON.stringify(D.cycleFor({})) === '["today"]', JSON.stringify(D.cycleFor({})));
const round = D.cycleFor({ recent: true, people: true, accounts: true, pictures: true, persona: true });
check("the rest take turns, a number between two pictures",
      round.join() === "today,accounts,recent,pictures,people,persona", round.join());
const urgent = D.cycleFor({ friends: true, health: true, recent: true });
check("friend requests and anything broken come round first", urgent[0] === "friends" && urgent[1] === "health", urgent.join());
check("a scene with nothing in it does not come round at all", !D.cycleFor({ recent: true }).includes("pictures"));
const short = D.cycleFor({ memory: true, recent: true, people: true });
check("with summaries, a person between every other scene while the list is short",
      short.join() === D.MEMORY_CYCLE.join(), short.join());
const long = D.cycleFor({ memory: true, recent: true, people: true, accounts: true, pictures: true, persona: true });
check("and between every two once it is long, so the rest still get their turn",
      long.filter((x) => x === "memory").length === 3 && long.length === 9, long.join());

// ── The scene on show does not change under you ───────────────────────────
s = D.initial(t);
s = D.tick(s, [], t, ["today", "accounts", "pictures"]);
check("the first scene of the list", D.sceneOf(s) === "today", String(D.sceneOf(s)));
s = D.tick(s, [], t + 3, ["friends", "today", "accounts", "pictures"]);
check("a friend request arriving does not swap the scene on show", D.sceneOf(s) === "today", String(D.sceneOf(s)));
s = D.tick(s, [], t + D.IDLE_SCENE + 1, ["friends", "today", "accounts", "pictures"]);
check("the new list only decides what comes next, and never the same one twice",
      D.sceneOf(s) === "accounts", String(D.sceneOf(s)));
s = D.showScene(s, "friends", ["friends", "today", "accounts", "pictures"], t + 20);
s = D.tick(s, [], t + 21, ["today", "accounts", "pictures"]);
check("the last request answered, its scene stays up to say so", D.sceneOf(s) === "friends", String(D.sceneOf(s)));
s = D.tick(s, [], t + 20 + D.MANUAL_HOLD + D.SCENE_TIME.friends + 2, ["today", "accounts", "pictures"]);
check("then the scene that took its place comes next", D.sceneOf(s) === "today", String(D.sceneOf(s)));
const keys = new Set();
s = D.initial(t);
for (let i = 0; i < 8; i++) {
  s = D.tick(s, [], t + i * (D.IDLE_SCENE + 1), ["today", "recent", "people"]);
  keys.add(s.idle.scene);
}
check("every showing has its own number, so the stage changes even when a scene comes round again", keys.size === 8, String(keys.size));

// ── Held by hand ──────────────────────────────────────────────────────────
s = D.tick(D.initial(t), [], t, ["today", "recent"]);
s = D.hold(s, t + 5);
s = D.tick(s, [], t + 5 + D.HOVER_HOLD - 1, ["today", "recent"]);
check("the pointer over a scene holds it past its time", D.sceneOf(s) === "today", String(D.sceneOf(s)));
check("and its clock stands still meanwhile", D.sceneProgress(s, t + 5 + D.HOVER_HOLD - 1) < 0.5,
      String(D.sceneProgress(s, t + 5 + D.HOVER_HOLD - 1)));
s = D.tick(s, [], t + 5 + D.HOVER_HOLD + 3, ["today", "recent"]);
check("let go, it still has the rest of its time", D.sceneOf(s) === "today", String(D.sceneOf(s)));
s = D.tick(s, [], t + 5 + D.HOVER_HOLD + D.IDLE_SCENE, ["today", "recent"]);
check("and then moves on", D.sceneOf(s) === "recent", String(D.sceneOf(s)));

s = D.tick(D.initial(t), [], t, ["today", "recent"]);
s = D.hold(s, t + 1);
s = D.tick(s, [row("n", "live", 2)], t + 2, ["today", "recent"]);
check("someone arriving waits while the pointer is on a scene", s.spotlight === null, String(s.spotlight));
s = D.tick(s, [row("n", "live", 2)], t + 2 + D.HOVER_HOLD, ["today", "recent"]);
check("and takes the stage once it is let be", s.spotlight === "n", String(s.spotlight));
// n's reply went quiet (nobody answering it now) and m is about to send: without a hold, m takes the stage.
const quiet = [row("n", "needs", 0, { ts: t }), row("m", "live", 4)];
check("without a hand on it the stage goes to the busier one", D.tick(s, quiet, t + 25, ["today"]).spotlight === "m");
s = D.hold(s, t + 20);
s = D.tick(s, quiet, t + 25, ["today"]);
check("the pointer over a conversation holds that too, so a click lands on it", s.spotlight === "n", String(s.spotlight));

s = D.tick(D.initial(t), [], t, ["today", "recent"]);
s = D.togglePin(s);
s = D.tick(s, [row("n", "needs", 0, { ts: t + 5 })], t + 300, ["today", "recent"]);
check("Space holds a scene too, whatever arrives", D.sceneOf(s) === "today" && s.spotlight === null);
s = D.togglePin(s);
s = D.tick(s, [row("n", "needs", 0, { ts: t + 295 })], t + 301, ["today", "recent"]);
check("and let go, the director moves on at once", s.spotlight === "n", String(s.spotlight));

// ── Chapters ──────────────────────────────────────────────────────────────
s = D.tick(D.initial(t), [row("a", "live", 2)], t, ["today", "accounts", "pictures"]);
s = D.showScene(s, "pictures", ["today", "accounts", "pictures"], t + 1);
s = D.tick(s, [row("a", "live", 2)], t + 10, ["today", "accounts", "pictures"]);
check("a chapter picked goes to that scene, even while a reply is written", s.spotlight === null && D.sceneOf(s) === "pictures",
      `${s.spotlight} ${D.sceneOf(s)}`);
s = D.tick(s, [row("a", "live", 2)], t + 2 + D.MANUAL_HOLD, ["today", "accounts", "pictures"]);
check("for a while, then back to the conversation", s.spotlight === "a", String(s.spotlight));
s = D.showScene(D.initial(t), "health", ["today"], t);
check("a chapter that is not in the list still opens", D.sceneOf(s) === "health", String(D.sceneOf(s)));
s = D.step(D.tick(D.initial(t), [], t, ["today", "accounts", "pictures"]), [], -1, t + 1, ["today", "accounts", "pictures"]);
check("the left arrow goes round to the last scene", D.sceneOf(s) === "pictures", String(D.sceneOf(s)));
s = D.live(D.togglePin(s));
check("Live lets go of every hold", !s.pinned && s.manualUntil === 0);

// ── What the other scenes work out ────────────────────────────────────────
const S = await import("../webui/src/lib/bigpicture/scenes.ts");
const template = [
  "# ═══════", "# PERSONA - edit everything between the lines.", "# ═══════",
  "Your name is [NAME] and you are [AGE] years old, [GENDER].", "You live in [CITY, COUNTRY].", "",
  "[If anything above is still in square brackets, it was not filled in yet.", "Fill it in yourself.]",
  "# ═══════", "", "You are chatting with people you know on messaging apps.",
].join("\n");
check("a persona still full of placeholders has nothing to show", S.personaLines(template).length === 0,
      JSON.stringify(S.personaLines(template)));
const filled = template.replace("[NAME]", "Max").replace("[AGE]", "19").replace("[GENDER]", "a guy")
  .replace("[CITY, COUNTRY]", "Lyon, France");
const pl = S.personaLines(filled);
check("a filled one shows who it is, and not the rules after it",
      pl.length === 2 && pl[0].startsWith("Your name is Max") && !pl.join(" ").includes("messaging apps"), JSON.stringify(pl));
check("and the name it is told it has", S.personaName(pl) === "Max", S.personaName(pl));
const half = filled.replace("You live in Lyon, France.", "You live in [CITY, COUNTRY].");
check("a line still holding a placeholder is left out, the rest kept", S.personaLines(half).length === 1);
check("a persona written from scratch starts where its text does",
      S.personaLines("You are Chloe, 18, from Arcadia Bay.\nYou love photography.\n\nRules:\n- be brief")[1] === "You love photography.");
check("its own pictures are known by their file name",
      JSON.stringify(S.sentPictures([{ name: "IMG_3.jpg" }, { name: "cat.png" }], ["IMG_1.png", "IMG_3.jpg"])) === '["IMG_3.jpg"]');
check("and a message with none of them is not one", S.sentPictures([{ name: "photo.jpg" }], ["IMG_1.png"]).length === 0);
check("an accept on its own timer said plainly", S.untilText(t + 240, t) === "in 4 min" && S.untilText(t + 30, t) === "in 30 s"
      && S.untilText(t + 2, t) === "any moment" && S.untilText(null, t) === "", `${S.untilText(t + 240, t)}`);
check("each chapter once on the rail, in the order it first comes round",
      S.chapterOrder(["memory", "today", "memory", "recent"]).join() === "memory,today,recent");
check("and every scene has a name and an icon there", Object.keys(S.CHAPTER).length === 9);

// ── The room: the colours and the weather of whoever is on stage ─────────
const P = await import("../webui/src/lib/bigpicture/palette.ts");
const LK = await import("../webui/src/lib/bigpicture/looks.ts");
const img = (...runs) => runs.flatMap(([n, rgba]) => Array.from({ length: n }, () => rgba)).flat();
const pal = P.paletteFromPixels(img([250, [220, 30, 40, 255]], [150, [30, 60, 220, 255]]));
const hues = (pal ?? []).map((c) => P.rgb2hsl(c)[0]);
const isRed = (h) => h < 15 || h > 345;
check("a picture's colours are its own: red and blue give red and blue",
      pal?.length === 4 && hues.some(isRed) && hues.some((h) => h > 210 && h < 250), hues.map(Math.round).join());
check("the strongest of them first", isRed(hues[0]), String(hues[0]));
check("a grey picture has none, and the person's id is used instead",
      P.paletteFromPixels(img([400, [128, 128, 128, 255]])) === null);
check("see-through pixels are not part of the picture", P.paletteFromPixels(img([400, [255, 0, 0, 0]])) === null);
const around = P.paletteFromPixels(img([400, [40, 200, 90, 255]]));
check("one colour is built round into four", around?.length === 4
      && new Set(around.map((c) => Math.round(P.rgb2hsl(c)[0]))).size === 4);
const every = [...(pal ?? []), ...(around ?? []), ...P.paletteFromSeed("abc"), ...P.paletteFromSeed("xyz")];
check("never so light it washes the room out, never so dull it cannot glow",
      every.every((c) => { const [, s, l] = P.rgb2hsl(c); return l >= 0.41 && l <= 0.61 && s >= 0.49; }));
check("the same person always gets the same colours, and someone else others",
      JSON.stringify(P.paletteFromSeed("u1")) === JSON.stringify(P.paletteFromSeed("u1"))
      && JSON.stringify(P.paletteFromSeed("u1")) !== JSON.stringify(P.paletteFromSeed("u2")));
check("yellow leans to gold: darkened, it would be olive",
      Math.round(P.rgb2hsl(P.tame(P.hsl2rgb(60, 0.8, 0.5)))[0]) <= 47);
check("warnings are reds and oranges, no yellow",
      [...P.paletteForTrouble(true), ...P.paletteForTrouble(false)].every((c) => { const h = P.rgb2hsl(c)[0]; return h < 40 || h > 330; }));
check("six looks", LK.LOOK_NAMES.length === 6, LK.LOOK_NAMES.join());
check("each person brings the same look every time", LK.lookFor("u1") === LK.lookFor("u1"));
const spread = new Set(Array.from({ length: 60 }, (_, i) => LK.lookFor(`person${i}`)));
check("and people are spread across all of them", spread.size === 6, [...spread].join());
check("every scene has its own", Object.keys(LK.SCENE_LOOK).length === 9);
check("calm while a reply waits, livelier while it is written, most while it is typed",
      LK.energyFor("live", 1, false) < LK.energyFor("live", 2, false) && LK.energyFor("live", 2, false) < LK.energyFor("live", 4, false));
check("every dial of every look in range",
      LK.LOOK_NAMES.every((n) => LK.dials(LK.LOOKS[n]).every((v) => v >= 0 && v <= 1.5)));

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
