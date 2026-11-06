/**
 * Big Picture Mode's logic, run for real under Node: what the screen shows and when it moves on
 * (webui/src/lib/bigpicture/director.ts), where an arrow key lands (spatial.ts), and what the pages work out (scenes.ts).
 */
const D = await import("../webui/src/lib/bigpicture/director.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const t = 1_000_000;
const row = (key, phase, step, extra = {}) => ({ key, phase, step, ts: t - 30, ...extra });
const TOUR = ["now", "today", "accounts", "pictures"];

// ── What gets the stage ───────────────────────────────────────────────────
let s = D.initial(t);
s = D.tick(s, [row("a", "live", 1, { eta: t + 60 }), row("b", "live", 2), row("c", "needs", 0, { ts: t - 5 })], t);
check("a reply being written beats one waiting and a new arrival", s.spotlight === "b", s.spotlight);
check("and someone on stage means the Now page", D.pageOf(s) === "now", D.pageOf(s));

s = D.initial(t);
const waits = [row("a", "live", 1, { eta: t + 90 }), row("b", "live", 1, { eta: t + 10 })];
s = D.tick(s, waits, t);
check("replies that are only waiting do not hold the stage: the tour plays", s.spotlight === null && s.idle !== null,
      String(s.spotlight));
check("though the queue still puts the one that fires sooner first", D.ranked(waits, t)[0].key === "b");
s = D.tick(s, [...waits, row("p", "live", 3, { eta: t + 20 })], t + 1);
check("nor does one pacing itself before it sends: that is waiting too", s.spotlight === null, String(s.spotlight));

s = D.initial(t);
s = D.tick(s, [row("old", "needs", 0, { ts: t - 600 }), row("new", "needs", 0, { ts: t - 5 })], t);
check("a message just arrived takes the stage", s.spotlight === "new", s.spotlight);
s = D.tick(s, [row("old", "needs", 0, { ts: t - 600 }), row("new", "needs", 0, { ts: t - 5 })], t + D.FRESH + 1);
check("for long enough to see it land, then the tour again", s.spotlight === null && s.idle !== null, String(s.spotlight));

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
check("written, then only waiting to be sent: the tour comes back", s.spotlight === null, String(s.spotlight));
s = D.tick(s, [row("w", "live", 4)], t + D.HOLD_MIN + 20);
check("and the moment it is typed out, it is live again", s.spotlight === "w", String(s.spotlight));

// ── An answered conversation stays up a moment ───────────────────────────
s = D.initial(t);
s = D.tick(s, [row("a", "live", 4), row("b", "live", 1, { eta: t + 5 })], t);
s = D.tick(s, [row("b", "live", 1, { eta: t + 5 })], t + 1);
check("once answered it stays, so the reply is seen", s.spotlight === "a", s.spotlight);
s = D.tick(s, [row("b", "live", 1, { eta: t + 5 })], t + 1 + D.AFTER_DONE + 1);
check("then, with the rest only waiting, the tour", s.spotlight === null, String(s.spotlight));
s = D.tick(s, [row("b", "live", 2)], t + 1 + D.AFTER_DONE + 2);
check("until the next one is being written", s.spotlight === "b", String(s.spotlight));

// ── The tour ─────────────────────────────────────────────────────────────
s = D.initial(t);
s = D.tick(s, [], t, TOUR);
check("with nobody waiting it starts at home, Now", s.spotlight === null && D.pageOf(s) === "now", D.pageOf(s));
s = D.tick(s, [], t + D.PAGE_TIME.now + 1, TOUR);
check("and moves on by itself", D.pageOf(s) === "today", D.pageOf(s));
s = D.tick(s, [], t + D.PAGE_TIME.now + D.PAGE_TIME.today + 2, TOUR);
check("round all of them", D.pageOf(s) === "accounts", D.pageOf(s));
s = D.tick(s, [row("n", "needs", 0, { ts: t + 30 })], t + 40, TOUR);
check("and a new message ends it", s.spotlight === "n" && s.idle === null, JSON.stringify(s));

check("the tour is at least home and the numbers", D.tourFor({}).join() === "now,today", D.tourFor({}).join());
const round = D.tourFor({ accounts: true, pictures: true, persona: true });
check("the rest take turns", round.join() === "now,today,accounts,pictures,persona", round.join());
const urgent = D.tourFor({ inbox: true, accounts: true });
check("anything that needs you comes straight after home", urgent[0] === "now" && urgent[1] === "inbox", urgent.join());
check("a page with nothing in it does not come round at all", !D.tourFor({ accounts: true }).includes("pictures"));
const short = D.tourFor({ people: true, accounts: true });
check("with people, one of them between every other page while the list is short",
      short.join() === "now,people,today,people,accounts,people", short.join());
const long = D.tourFor({ people: true, accounts: true, pictures: true, persona: true, minecraft: true });
check("and every third once it is long, so the rest still get their turn",
      long.filter((x) => x === "people").length === 3 && long.length === 9, long.join());
const every = D.tourFor({ people: true, accounts: true, pictures: true, persona: true, minecraft: true, inbox: true });
check("every page there is, once it has something in it", ["now", "inbox", "today", "accounts", "minecraft", "pictures", "persona", "people"].every((p) => every.includes(p)), every.join());

check("the tabs are every page, in their order", D.tabsFor({ minecraft: true, inbox: true }).join() === D.TABS.join());
check("Minecraft and Needs you only while there is something in them",
      D.tabsFor({}).join() === "now,people,accounts,today,persona,pictures", D.tabsFor({}).join());

// ── The page on show does not change under you ────────────────────────────
s = D.initial(t);
s = D.tick(s, [], t, ["today", "accounts", "pictures"]);
check("the first page of the tour", D.pageOf(s) === "today", D.pageOf(s));
s = D.tick(s, [], t + 3, ["inbox", "today", "accounts", "pictures"]);
check("something needing you arriving does not swap the page on show", D.pageOf(s) === "today", D.pageOf(s));
s = D.tick(s, [], t + D.PAGE_TIME.today + 1, ["inbox", "today", "accounts", "pictures"]);
check("the new tour only decides what comes next, and never the same one twice", D.pageOf(s) === "accounts", D.pageOf(s));
s = D.showPage(s, "inbox", ["inbox", "today", "accounts", "pictures"], t + 20);
s = D.tick(s, [], t + 21, ["today", "accounts", "pictures"]);
check("the last request answered, its page stays up to say so", D.pageOf(s) === "inbox", D.pageOf(s));
s = D.tick(s, [], t + 20 + D.MANUAL_HOLD + D.PAGE_TIME.inbox + 2, ["today", "accounts", "pictures"]);
check("then the page that took its place comes next", D.pageOf(s) === "today", D.pageOf(s));
const keys = new Set();
s = D.initial(t);
for (let i = 0; i < 8; i++) {
  s = D.tick(s, [], t + i * 30, ["today", "accounts", "people"]);
  keys.add(s.idle.scene);
}
check("every showing has its own number, so the screen changes even when a page comes round again", keys.size === 8, String(keys.size));

// ── By hand: nothing is taken from under anyone ───────────────────────────
const rows = [row("a", "live", 2), row("b", "live", 1, { eta: t + 20 }), row("c", "needs", 0, { ts: t - 10 })];
s = D.tick(D.initial(t), rows, t);
s = D.pick(s, "c", t + 1);
s = D.tick(s, rows, t + 5);
check("a press holds the stage on that one", s.spotlight === "c", s.spotlight);
s = D.tick(s, rows, t + 1 + D.MANUAL_HOLD + 1);
check("for a while, then the director takes over again", s.spotlight === "a", s.spotlight);

s = D.tick(D.initial(t), [row("a", "live", 2)], t, TOUR);
s = D.showPage(s, "pictures", TOUR, t + 1);
s = D.tick(s, [row("a", "live", 2)], t + 10, TOUR);
check("a page gone to stays, even while a reply is written", s.spotlight === null && D.pageOf(s) === "pictures", `${s.spotlight} ${D.pageOf(s)}`);
s = D.tick(s, [row("a", "live", 2), row("n", "needs", 0, { ts: t + 12 })], t + 12, TOUR);
check("and someone new writing does not move it", s.spotlight === null && D.pageOf(s) === "pictures", `${s.spotlight} ${D.pageOf(s)}`);
s = D.tick(s, [row("a", "live", 2)], t + 2 + D.MANUAL_HOLD, TOUR);
check("until Auto comes back, then the conversation", s.spotlight === "a", String(s.spotlight));
s = D.showPage(D.initial(t), "inbox", ["today"], t);
check("a page the tour does not visit still opens", D.pageOf(s) === "inbox", D.pageOf(s));

s = D.tick(D.initial(t), [], t, ["today", "accounts"]);
s = D.hold(s, t + 5);
s = D.tick(s, [], t + 5 + D.HOVER_HOLD - 1, ["today", "accounts"]);
check("the pointer moving holds a page past its time", D.pageOf(s) === "today", D.pageOf(s));
check("and its clock stands still meanwhile", D.pageProgress(s, t + 5 + D.HOVER_HOLD - 1) < 0.6, String(D.pageProgress(s, t + 5 + D.HOVER_HOLD - 1)));
s = D.tick(s, [], t + 5 + D.HOVER_HOLD + 3, ["today", "accounts"]);
check("let go, it still has the rest of its time", D.pageOf(s) === "today", D.pageOf(s));
s = D.tick(s, [], t + 5 + D.HOVER_HOLD + D.PAGE_TIME.today, ["today", "accounts"]);
check("and then moves on", D.pageOf(s) === "accounts", D.pageOf(s));

s = D.showPage(D.initial(t), "today", TOUR, t);
s = D.hold(s, t + 20);
check("someone who has pressed something is driving: moving the pointer gives them the whole time again",
      s.manualUntil === t + 20 + D.MANUAL_HOLD, String(s.manualUntil - t));
s = D.tick(D.initial(t), [], t, TOUR);
s = D.hold(s, t + 1);
check("someone who only passed by is held for a moment", s.manualUntil === t + 1 + D.HOVER_HOLD, String(s.manualUntil - t));

s = D.tick(D.initial(t), [], t, TOUR);
s = D.togglePin(s);
s = D.tick(s, [row("n", "needs", 0, { ts: t + 295 })], t + 300, TOUR);
check("Space stays put for good, whatever arrives", D.pageOf(s) === "now" && s.spotlight === null, `${D.pageOf(s)} ${s.spotlight}`);
s = D.togglePin(s);
s = D.tick(s, [row("n", "needs", 0, { ts: t + 295 })], t + 301, TOUR);
check("and let go, the director moves on at once", s.spotlight === "n", String(s.spotlight));
s = D.togglePin(D.tick(D.initial(t), [row("a", "live", 2)], t));
s = D.tick(s, [row("z", "live", 4)], t + 500);
check("stayed on a conversation, it stays even when that one is gone", s.pinned && s.spotlight === "a", JSON.stringify(s));
s = D.live(s);
check("Now lets go of every hold", !s.pinned && s.manualUntil === 0);

// ── Who has the screen, for the button that says so ───────────────────────
s = D.tick(D.initial(t), [], t, TOUR);
check("left alone it is Auto", D.autoState(s, t).mode === "auto");
s = D.showPage(s, "today", TOUR, t + 1);
const held = D.autoState(s, t + 11);
check("held, with how long is left of how long", held.mode === "held" && held.left === D.MANUAL_HOLD - 10 && held.of === D.MANUAL_HOLD, JSON.stringify(held));
check("and Auto once that has run out", D.autoState(s, t + 2 + D.MANUAL_HOLD).mode === "auto");
check("Space says so", D.autoState(D.togglePin(s), t + 2).mode === "pinned");

// ── The queue as it is read ───────────────────────────────────────────────
const g = D.groupQueue([row("typing", "live", 4), row("soon", "live", 1, { eta: t + 5 }), row("later", "live", 1, { eta: t + 100 }),
                        row("pacing", "live", 3, { eta: t + 30 }), row("writing", "live", 2), row("old", "needs", 0, { ts: t - 9000 }),
                        row("new", "needs", 0, { ts: t - 100 }), row("off", "off", 0)], t);
check("being answered first", g.answering.map((r) => r.key).join() === "typing,writing", g.answering.map((r) => r.key).join());
check("then who is next, pacing and the soonest first", g.next.map((r) => r.key).join() === "pacing,soon,later", g.next.map((r) => r.key).join());
check("then who is waiting on you, the newest first", g.waiting.map((r) => r.key).join() === "new,old", g.waiting.map((r) => r.key).join());
check("and nobody it is off for", ![...g.answering, ...g.next, ...g.waiting].some((r) => r.key === "off"));

// ── Where an arrow key lands ──────────────────────────────────────────────
const N = await import("../webui/src/lib/bigpicture/spatial.ts");
const box = (id, x, y, w = 100, h = 100) => ({ id, x, y, w, h });
const grid = [box("a", 0, 0), box("b", 120, 0), box("c", 240, 0), box("d", 0, 120), box("e", 120, 120), box("f", 240, 120)];
check("right along a row", N.nextFocus(grid, "a", "right") === "b");
check("left back", N.nextFocus(grid, "c", "left") === "b");
check("down a column", N.nextFocus(grid, "b", "down") === "e");
check("up it", N.nextFocus(grid, "f", "up") === "c");
check("nothing that way, nothing", N.nextFocus(grid, "a", "left") === null && N.nextFocus(grid, "a", "up") === null);
check("from nowhere, the first thing, reading from the top left", N.nextFocus(grid.slice().reverse(), null, "down") === "a");
const shelf = [box("nav", 0, 0, 80, 40), box("hero", 200, 80, 400, 300), ...[0, 1, 2, 3].map((i) => box(`s${i}`, i * 130, 420, 120, 120))];
check("straight ahead beats nearer off to the side", N.nextFocus(shelf, "s0", "right") === "s1");
check("up from the shelf finds what is over it", N.nextFocus(shelf, "s2", "up") === "hero");
const rails = [box("q1", 0, 100, 300, 80), box("q2", 0, 190, 300, 80), box("q3", 0, 280, 300, 80), box("write", 340, 600, 600, 44), box("model", 1000, 100, 300, 80)];
check("going down a column stays in the column", N.nextFocus(rails, "q1", "down") === "q2");
check("across the screen goes to what is level with it", N.nextFocus(rails, "q1", "right") === "model");
check("and something overlapping it is not that way", N.nextFocus([box("a", 0, 0, 100, 100), box("b", 40, 40, 20, 20)], "a", "right") === null);

// ── What the pages work out ───────────────────────────────────────────────
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
check("how long ago, for a sentence", S.ago(t - 5, t) === "just now" && S.ago(t - 240, t) === "4 min ago" && S.ago(t - 7200, t) === "2 h ago"
      && S.ago(t - 172800, t) === "2 d ago" && S.ago(null, t) === "", S.ago(t - 240, t));
check("and for a tight row", S.agoShort(t - 5, t) === "now" && S.agoShort(t - 12, t) === "12s" && S.agoShort(t - 240, t) === "4m" && S.agoShort(t - 7200, t) === "2h");
const day = S.lastDay([{ hour: 9, count: 5 }, { hour: 10, count: 7 }, { hour: 23, count: 1 }], 10);
check("the last 24 hours in the order they happened, this hour last", day.length === 24 && day[23].hour === 10 && day[23].count === 7 && day[22].count === 5 && day[0].hour === 11,
      JSON.stringify(day.slice(-2)));
check("against the stretch before it", S.trend(120, 100) === "+20%" && S.trend(90, 100) === "-10%" && S.trend(5, 0) === "" && S.trend(100, 100) === "");
const merged = S.mergePeople([[{ id: "x", target: "a", name: "X", last_ts: 10, messages: 1 }, { id: "y", target: "a", name: "Y", last_ts: 30, messages: 1 }],
                              [{ id: "x", target: "b", name: "X", last_ts: 20, messages: 1 }]]);
check("everyone once, the conversation last spoken in, the most recent first", merged.map((p) => `${p.id}${p.target}`).join() === "ya,xb", merged.map((p) => `${p.id}${p.target}`).join());
const ends = S.runsOf([{ mine: false, ts: 1 }, { mine: false, ts: 2 }, { mine: true, ts: 3 }, { mine: true, ts: 900 }]);
check("a run of messages ends where the side changes, or after a long gap, and at the last", ends.join() === "false,true,true,true", ends.join());
check("a big number short", S.compact(950) === "950" && S.compact(9500) === "9500" && S.compact(12400) === "12k" && S.compact(1200000) === "1.2M" && S.compact(23000000) === "23M");
check("every page has a name and an icon on its tab", Object.keys(S.PAGE).length === Object.keys(D.PAGE_TIME).length && D.TABS.every((p) => S.PAGE[p]?.label && S.PAGE[p]?.icon));

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
const all = [...(pal ?? []), ...(around ?? []), ...P.paletteFromSeed("abc"), ...P.paletteFromSeed("xyz")];
check("never so light it washes the room out, never so dull it cannot glow",
      all.every((c) => { const [, sat, l] = P.rgb2hsl(c); return l >= 0.41 && l <= 0.61 && sat >= 0.49; }));
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
check("every page has its own", Object.keys(LK.PAGE_LOOK).length === Object.keys(D.PAGE_TIME).length);
check("calm while a reply waits, livelier while it is written, most while it is typed",
      LK.energyFor("live", 1, false) < LK.energyFor("live", 2, false) && LK.energyFor("live", 2, false) < LK.energyFor("live", 4, false));
check("every dial of every look in range",
      LK.LOOK_NAMES.every((n) => LK.dials(LK.LOOKS[n]).every((v) => v >= 0 && v <= 1.5)));

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
