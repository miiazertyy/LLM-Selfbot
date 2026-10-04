// The arithmetic behind Settings' dials and language pickers, run under Node:
// amounts of time said in words, placed round a dial and snapped (durations.ts),
// the scales the dials use for time, typing speed and counts (dialscale.ts),
// and the language lists (languages.ts).
//   node tests/settings_dials.mjs           the checks
//   node tests/settings_dials.mjs --codes   every language code, as JSON, for the Python side
const D = await import("../webui/src/lib/durations.ts");
const S = await import("../webui/src/lib/dialscale.ts");
const L = await import("../webui/src/lib/languages.ts");
const K = await import("../webui/src/lib/clock.ts");

if (process.argv.includes("--codes")) {
  console.log(JSON.stringify(L.LANGUAGE_CODES));
} else {
  let pass = 0, fail = 0;
  const check = (name, cond, extra = "") => {
    if (cond) pass++; else fail++;
    console.log((cond ? "  PASS  " : "  FAIL  ") + name + (!cond && extra ? `  [${extra}]` : ""));
  };
  const near = (a, b) => Math.abs(a - b) < 1e-6;

  console.log("== saying amounts of time ==");
  check("seconds", D.say(45, "s") === "45 s");
  check("minutes and seconds", D.say(150, "s") === "2 min 30 s", D.say(150, "s"));
  check("hours and minutes", D.say(3900, "s") === "1 h 5 min", D.say(3900, "s"));
  check("days", D.say(3 * 86400, "s") === "3 days" && D.say(1, "days") === "1 day");
  check("halves of a second", D.say(2.5, "s") === "2.5 s", D.say(2.5, "s"));
  check("milliseconds as seconds once there are some", D.say(8000, "ms") === "8 s" && D.say(800, "ms") === "800 ms");
  check("only parts next to each other: an hour and twenty seconds is an hour", D.say(3620, "s") === "1 h", D.say(3620, "s"));
  check("a setting kept in minutes", D.say(90, "min") === "1 h 30 min", D.say(90, "min"));
  check("nothing", D.say(0, "s") === "0 s");
  check("two amounts as one range", D.sayRange(2, 8, "s") === "2–8 s" && D.sayRange(120, 600, "s") === "2–10 min",
        D.sayRange(120, 600, "s"));
  check("in their own units when they differ", D.sayRange(45, 120, "s") === "45 s – 2 min", D.sayRange(45, 120, "s"));
  check("and once when they are the same", D.sayRange(5, 5, "s") === "5 s");
  check("short labels for the rim", D.short(30, "s") === "30s" && D.short(300, "s") === "5m" && D.short(3600, "s") === "1h"
        && D.short(2, "days") === "2d" && D.short(500, "ms") === "500ms" && D.short(0, "s") === "0");

  console.log("\n== typing them ==");
  check("a plain number is in the setting's own unit", D.readTime("8000", "ms") === 8000 && D.readTime("45", "s") === 45);
  check("anything else says its own", D.readTime("2m", "s") === 120 && D.readTime("1h 30m", "s") === 5400
        && D.readTime("45 s", "ms") === 45000 && D.readTime("1.5 min", "s") === 90, `${D.readTime("1h 30m", "s")}`);
  check("in whatever unit the setting keeps", D.readTime("2h", "min") === 120 && D.readTime("3 days", "h") === 72);
  check("and nothing for what is not a time", ["", "abc", "2 parsecs", "5m then"].every((t) => D.readTime(t, "s") === null));
  check("labels under a scale, short", D.compact(20) === "20s" && D.compact(70) === "1m10s" && D.compact(300) === "5m"
        && D.compact(5400) === "1h30m" && D.compact(172800) === "2d");
  const ts = S.timeScale("s", { integer: true });
  check("the dial's box reads it the same way", ts.read("2m 30s") === 150 && ts.example.length > 0);
  check("a speed or a count is just a number", S.wpmScale().read("72") === 72 && S.countScale({ one: "a", many: "b" }).read("x") === null);

  console.log("\n== placing them round a dial ==");
  check("round the dial and back", [0, 1, 10, 100, 599, 600].every((v) => near(D.valueAt(D.fracOf(v, 0, 600), 0, 600), v)));
  check("with a minimum", near(D.valueAt(D.fracOf(120, 30, 1800), 30, 1800), 120));
  check("small amounts get more of the dial than their share", D.fracOf(60, 0, 600) > 0.1 + 0.05, D.fracOf(60, 0, 600));
  check("and it only ever goes one way", [1, 2, 5, 10, 50, 100, 300].every((v, i, a) => i === 0 || D.fracOf(v, 0, 600) > D.fracOf(a[i - 1], 0, 600)));
  check("never off the dial", D.fracOf(-5, 0, 600) === 0 && D.fracOf(9999, 0, 600) === 1);

  console.log("\n== snapping to round numbers ==");
  check("half seconds under ten seconds", D.stepFor(5, "s") === 0.5);
  check("seconds under a minute", D.stepFor(30, "s") === 1);
  check("five seconds under ten minutes", D.stepFor(300, "s") === 5);
  check("a minute past an hour", D.stepFor(7200, "s") === 60);
  check("in the setting's own unit", D.stepFor(8000, "ms") === 500 && D.stepFor(30, "min") === 0.5, `${D.stepFor(30, "min")}`);
  check("never finer than the setting allows", D.stepFor(5, "s", 1) === 1);
  check("a drag lands on 2 min 25 s, not 2 min 27 s", D.snap(147, "s") === 145, D.snap(147, "s"));
  check("milliseconds on whole seconds", D.snap(12345, "ms") === 12000, D.snap(12345, "ms"));
  check("whole numbers for a whole-number setting", Number.isInteger(D.snap(7.3, "s", { integer: true })));
  check("inside the setting's bounds", D.snap(5, "s", { lo: 30 }) === 30 && D.snap(9000, "s", { hi: 3600 }) === 3600);

  console.log("\n== how big a dial is ==");
  check("room to turn it up: twice its value, to a round amount", D.niceTop(600, "s", 30) === 1800, D.niceTop(600, "s", 30));
  check("a few seconds get a dial to half a minute", D.niceTop(8, "s") === 30);
  check("in the setting's unit", D.niceTop(8000, "ms") === 30000);
  check("nothing still gets a dial", D.niceTop(0, "ms") === 10000);
  const m = D.marks(0, 3600, "s");
  check("round amounts marked on the rim", m.length >= 2 && m.every((x) => x.frac > 0 && x.frac < 1), JSON.stringify(m));
  check("spaced so they do not crowd", m.every((x, i) => i === 0 || x.frac - m[i - 1].frac >= 0.2));
  check("and clear of the ends, which have their own labels", m.every((x) => x.frac >= 0.2 && x.frac <= 0.8));

  console.log("\n== the scales ==");
  const t = S.timeScale("s", { min: 30, max: 3600, integer: true });
  check("time: a drag snaps and stays whole", t.snap(47.3, 30, 3600) === 47 && t.snap(20, 30, 3600) === 30);
  check("time: a typed amount is kept as typed, only whole", t.exact(47.6) === 48 && S.timeScale("s", { least: 0.5 }).exact(2.26) === 2.5);
  check("time: said in words", t.say(150) === "2 min 30 s");
  check("time: fitted to its value", t.fit(600) === 1800);
  const w = S.wpmScale({ min: 5, max: 300 });
  check("speed: fitted with room", w.fit(72) === 120 && w.fit(250) === 300, `${w.fit(72)} ${w.fit(250)}`);
  check("speed: said", w.say(30) === "30 wpm" && w.sayRange(30, 72) === "30–72");
  check("speed: an even scale", near(w.fracOf(62.5, 5, 120), 0.5));
  check("speed: marks inside the dial", w.marks(5, 120).every((x) => x.v > 5 && x.v < 120));
  const c = S.countScale({ min: 1, max: 50, one: "chat", many: "chats" });
  check("count: one and many", c.say(1) === "1 chat" && c.say(20) === "20 chats");
  check("count: whole numbers", c.snap(20.4, 1, 30) === 20 && c.exact(3.6) === 4);
  check("count: fitted, never past its maximum", c.fit(20) === 30 && c.fit(45) === 50);

  console.log("\n== languages ==");
  const codes = L.DISCORD_LOCALES.map((l) => l.code);
  check("Discord's own 32 languages", codes.length === 32 && new Set(codes).size === 32);
  check("with the codes Discord sends", ["en-US", "en-GB", "pt-BR", "es-419", "zh-TW", "fr", "ja"].every((x) => codes.includes(x)));
  check("a flag for each that is a country's", L.DISCORD_LOCALES.filter((l) => !l.flag).map((l) => l.code).join() === "es-419");
  check("every ISO 639-1 language for the fallback", L.LANGUAGE_CODES.length === 183
        && L.LANGUAGE_CODES.every((x) => /^[a-z]{2}$/.test(x)) && new Set(L.LANGUAGE_CODES).size === 183);
  check("the most used ones are among them", L.COMMON_LANGUAGES.every((x) => L.LANGUAGE_CODES.includes(x)));
  const all = L.allLanguages();
  const fr = all.find((l) => l.code === "fr");
  check("named in English and in itself", fr?.name === "French" && fr?.native === "Français", JSON.stringify(fr));
  check("in English alphabetical order", all[0].name <= all[1].name && all[5].name <= all[6].name);
  check("found without its accents", L.searchLanguages(all, "francais")[0]?.code === "fr");
  check("found in its own script", L.searchLanguages(all, "日本")[0]?.code === "ja");
  check("found by code, the exact one first", L.searchLanguages(all, "pt")[0]?.code === "pt");
  check("Discord's found by what they are", L.searchLanguages(L.DISCORD_LOCALES, "brazil")[0]?.code === "pt-BR");
  const flagless = all.filter((l) => !l.flag).map((l) => l.code).sort();
  check("every language with a country has its flag", JSON.stringify(flagless) === JSON.stringify([...L.NO_FLAG].sort()),
        flagless.join());
  const flagOfLang = (c) => all.find((l) => l.code === c)?.flag;
  check("the country most tied to it", flagOfLang("fr") === "FR" && flagOfLang("en") === "GB" && flagOfLang("ja") === "JP"
        && flagOfLang("pt") === "PT" && flagOfLang("la") === "VA", ["fr", "en", "ja", "pt", "la"].map(flagOfLang).join());
  check("Welsh and Scottish Gaelic with their own flags", flagOfLang("cy") === "GB-WLS" && flagOfLang("gd") === "GB-SCT");
  check("and every flag is one the flag font can draw",
        all.every((l) => !l.flag || K.flagOf(l.flag) !== ""), all.filter((l) => l.flag && !K.flagOf(l.flag)).map((l) => l.code).join());
  check("Wales is the black flag and the tag letters g b w l s", K.flagOf("GB-WLS")
        === String.fromCodePoint(0x1f3f4, 0xe0067, 0xe0062, 0xe0077, 0xe006c, 0xe0073, 0xe007f));

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exitCode = fail ? 1 : 0;
}
