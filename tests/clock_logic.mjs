/**
 * The arithmetic behind the clocks in Settings (webui/src/lib/clock.ts and the
 * drag steps in scrub.ts), run for real under Node. With --parity it prints
 * what it makes of a grid of night hours instead, for test_settings_clock.py
 * to hold against the runner's own rules in app/utils/behavior.py.
 */
import { register } from "node:module";

// The app imports "./uisound" without an extension (scrub.ts makes a sound as a number is dragged), which its
// bundler allows and Node does not. This resolves those to the .ts file, for this test only.
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(spec, ctx, next) {
  try { return await next(spec, ctx); }
  catch (e) {
    if (spec.startsWith(".") && !/\\.[a-z]+$/i.test(spec)) return next(spec + ".ts", ctx);
    throw e;
  }
}`));

const K = await import("../webui/src/lib/clock.ts");
const S = await import("../webui/src/lib/scrub.ts");

const SPECS = ["2-8", "23-7", "0-0", "12-12", "22-2", "0-23", " 5 - 9 ", "garbage", "24-3", "3-24", "-1-5", "7", ""];

if (process.argv.includes("--parity")) {
  const out = {};
  for (const spec of SPECS) {
    const h = K.parseHours(spec);
    out[spec] = h && { hours: [h.start, h.end], night: Array.from({ length: 24 }, (_, hour) => K.isNight(h, hour)),
                       until: Array.from({ length: 24 }, (_, hour) => K.untilChange(h, hour, 30)) };
  }
  console.log(JSON.stringify(out));
  process.exitCode = 0;
} else {
  let pass = 0, fail = 0;
  const check = (name, ok, detail = "") => {
    console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
    ok ? pass++ : fail++;
  };

  check("\"2-8\" reads as two to eight", JSON.stringify(K.parseHours("2-8")) === '{"start":2,"end":8}');
  check("past midnight too: \"23-7\"", JSON.stringify(K.parseHours("23-7")) === '{"start":23,"end":7}');
  check("what the runner would refuse is refused", ["garbage", "24-3", "3-24", "7", ""].every((s) => K.parseHours(s) === null));
  check("and written back the way it is stored", K.formatHours({ start: 23, end: 7 }) === "23-7");
  check("the night's length, round midnight", K.span({ start: 23, end: 7 }) === 8 && K.span({ start: 2, end: 8 }) === 6);
  check("the same hour at both ends is no night", K.span({ start: 5, end: 5 }) === 0 && !K.isNight({ start: 5, end: 5 }, 5));
  check("asleep at 3 with a 2-8 night, awake at 8", K.isNight({ start: 2, end: 8 }, 3) && !K.isNight({ start: 2, end: 8 }, 8));
  check("asleep at 1 with a 23-7 night", K.isNight({ start: 23, end: 7 }, 1) && !K.isNight({ start: 23, end: 7 }, 12));
  check("wakes in 4 h 30 min at 3:30 with a 2-8 night", K.untilChange({ start: 2, end: 8 }, 3, 30) === 270);
  check("goes to sleep in 10 h 30 min at 15:30", K.untilChange({ start: 2, end: 8 }, 15, 30) === 630);
  check("midnight at the top of the dial", K.hourAt(0, -50) === 0);
  check("six on the right, noon at the bottom, eighteen on the left",
        K.hourAt(50, 0) === 6 && K.hourAt(0, 50) === 12 && K.hourAt(-50, 0) === 18);
  check("a point between hours goes to the nearer one", K.hourAt(Math.sin((2.4 / 24) * Math.PI * 2), -Math.cos((2.4 / 24) * Math.PI * 2)) === 2);
  check("the short way round the clock", K.apart(23, 1) === 2 && K.apart(1, 23) === 2);
  check("a click moves the nearer end", K.nearer({ start: 23, end: 7 }, 1) === "start" && K.nearer({ start: 23, end: 7 }, 6) === "end");
  check("hours wrap onto the clock", K.wrap(25) === 1 && K.wrap(-1) === 23 && K.wrap(24) === 0);
  check("times said plainly", K.duration(270) === "4 h 30 min" && K.duration(45) === "45 min" && K.duration(120) === "2 h");
  check("hours written as a clock does", K.hh(2) === "02:00" && K.hh(23) === "23:00");
  check("an hour typed however it comes", [["7", 7], ["07", 7], ["7:00", 7], ["19h", 19], ["7pm", 19], ["7 PM", 19],
        ["12am", 0], ["12pm", 12], ["24", 0], ["0", 0], ["23:59", 23], ["7h30", 7]].every(([t, h]) => K.readHour(t) === h),
        [["7pm"], ["19h"], ["7h30"]].map(([t]) => `${t}=${K.readHour(t)}`).join());
  check("and nothing for what is not one", ["25", "abc", "", "-3", "7:0", "1000"].every((t) => K.readHour(t) === null));

  const at = new Date(Date.UTC(2026, 0, 15, 12, 0, 0));     // noon UTC, winter
  check("the time in Paris", JSON.stringify(K.zoneNow("Europe/Paris", at)) === '{"hour":13,"minute":0,"second":0}');
  check("and in Tokyo", K.zoneNow("Asia/Tokyo", at)?.hour === 21);
  check("with how far it is from UTC", K.zoneOffset("Asia/Tokyo", at) === "UTC+9" && K.zoneOffset("Europe/Paris", at) === "UTC+1");
  check("half hours as well", K.zoneOffset("Asia/Kolkata", at) === "UTC+5:30", K.zoneOffset("Asia/Kolkata", at));
  check("a zone that does not exist is known not to", !K.validZone("Nowhere/Atlantis") && K.zoneNow("Nowhere/Atlantis", at) === null);
  check("and a real one is", K.validZone("Europe/Paris") && K.validZone("UTC"));
  check("a zone's name read as a city and where it is",
        JSON.stringify(K.zoneLabel("America/Argentina/Buenos_Aires")) === '{"city":"Buenos Aires","region":"America · Argentina"}');
  const zones = K.allZones();
  check("the full list of zones, UTC among them", zones.length > 300 && zones.includes("UTC") && zones.includes("Europe/Paris"));
  check("searching by city finds it first", K.searchZones(zones, "tok", at)[0] === "Asia/Tokyo", K.searchZones(zones, "tok", at).slice(0, 3).join());
  check("by region too", K.searchZones(zones, "europe", at).every((z) => z.toLowerCase().includes("europe")));
  check("and by offset", K.searchZones(zones, "+9", at).includes("Asia/Tokyo"));

  check("a zone knows its country", K.countryOf("Europe/Paris") === "FR" && K.countryOf("Asia/Tokyo") === "JP");
  check("old spellings the browser still lists too", K.countryOf("Asia/Calcutta") === "IN" && K.countryOf("Europe/Kiev") === "UA");
  check("and the ones renamed across a border, by the zone they became",
        K.countryOf("Pacific/Truk") === "FM" && K.countryOf("Africa/Asmera") === "ER" && K.countryOf("America/Coral_Harbour") === "CA",
        [K.countryOf("Pacific/Truk"), K.countryOf("Africa/Asmera"), K.countryOf("America/Coral_Harbour")].join());
  check("UTC is in no country", K.countryOf("UTC") === "" && K.countryOf("Etc/GMT+3") === "");
  check("every zone this runtime lists that is in a country has one",
        zones.filter((z) => !K.countryOf(z) && !/^(UTC|Etc\/|GMT)/.test(z)).length === 0,
        zones.filter((z) => !K.countryOf(z) && !/^(UTC|Etc\/|GMT)/.test(z)).join());
  check("a flag is the two regional indicator letters", K.flagOf("FR") === "\u{1F1EB}\u{1F1F7}" && K.flagOf("jp") === "\u{1F1EF}\u{1F1F5}");
  check("and nothing for what is not a country code", K.flagOf("") === "" && K.flagOf("EUR") === "");
  check("countries by name", K.countryName("FR") === "France" && K.countryName("JP") === "Japan");
  check("searching a country finds its zones", K.searchZones(zones, "japan", at)[0] === "Asia/Tokyo" && K.searchZones(zones, "france", at).includes("Europe/Paris"));

  check("dragging seconds goes by seconds near a minute", S.timeStep("s", 30) === 1);
  check("by half minutes near half an hour", S.timeStep("s", 1800) === 30);
  check("by minutes past an hour", S.timeStep("s", 5400) === 60);
  check("milliseconds in useful lumps", S.timeStep("ms", 5000) === 100);

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exitCode = fail ? 1 : 0;
}
