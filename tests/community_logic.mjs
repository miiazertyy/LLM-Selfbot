/**
 * Community profiles' page logic (webui/src/lib/community/logic.ts), under Node: sorting and searching the catalog,
 * counts as people say them, which of yours has a newer version, what a request you sent is at, and short names made
 * exactly as the Python side makes them (the same fixture as tests/test_community_rules.py).
 */
import { readFileSync } from "node:fs";

const c = await import("../webui/src/lib/community/logic.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const P = (slug, o = {}) => ({ slug, name: slug, tagline: "", tags: [], color: "", author: "a", adult: false, version: 1,
                               downloads: 0, week: 0, avatar: "", ...o });
const list = [P("juni", { downloads: 50, week: 2, created: "2026-10-01" }), P("mara", { downloads: 10, week: 9, created: "2026-10-09" }),
              P("theo", { downloads: 50, week: 1, created: "2026-09-01", adult: true, tags: ["flirty"] }),
              P("heloise", { name: "Héloïse", downloads: 1, week: 0, created: "2026-08-01", tags: ["chill"], tagline: "Calm and kind" })];

console.log("== the catalog ==");
check("popular: most downloaded, then this week", c.sortProfiles(list, "popular").map((p) => p.slug).join() === "juni,theo,mara,heloise");
check("new: newest first", c.sortProfiles(list, "new").map((p) => p.slug).join() === "mara,juni,theo,heloise");
check("trending: most this week", c.sortProfiles(list, "trending")[0].slug === "mara");
check("18+ only when asked for", !c.filterProfiles(list, {}).some((p) => p.adult) && c.filterProfiles(list, { adult: true }).length === 4);
check("search ignores accents and case", c.filterProfiles(list, { q: "HELOISE" }).map((p) => p.slug).join() === "heloise"
      && c.filterProfiles(list, { q: "calm kind" }).length === 1);
check("tags: all of them", c.filterProfiles(list, { tags: ["chill"], adult: true }).map((p) => p.slug).join() === "heloise"
      && c.filterProfiles(list, { tags: ["chill", "flirty"], adult: true }).length === 0);

console.log("\n== counts and words ==");
check("counts as people say them", c.compact(999) === "999" && c.compact(1200) === "1.2K" && c.compact(45600) === "46K"
      && c.compact(1_250_000) === "1.3M" && c.compact(-3) === "0");
check("one and many", c.plural(1, "download", "downloads") === "1 download" && c.plural(2400, "download", "downloads") === "2.4K downloads");
check("sizes", c.sizeText(900) === "900 B" && c.sizeText(42_000) === "42 KB" && c.sizeText(3_400_000) === "3.4 MB");
const now = Date.parse("2026-10-10T12:00:00Z");
check("time ago", c.timeAgo("2026-10-10T08:00:00Z", now) === "today" && c.timeAgo("2026-10-09T08:00:00Z", now) === "yesterday"
      && c.timeAgo("2026-10-05T08:00:00Z", now) === "5 days ago" && c.timeAgo("2026-09-10T08:00:00Z", now) === "4 weeks ago"
      && c.timeAgo("nonsense", now) === "");
check("a setting's value, short", c.valueText(true) === "On" && c.valueText(null) === "Default" && c.valueText(["a", "b"]) === "a, b"
      && c.valueText({ chill: "x", sad: "y" }) === "2 entries");
check("the last days of a series, with their dates", JSON.stringify(c.lastDays([1, 2, 3], ["d1", "d2", "d3"], 2))
      === JSON.stringify([{ v: 2, day: "d2" }, { v: 3, day: "d3" }]));

console.log("\n== yours ==");
check("whether you have one, and a newer version", c.installState(list[0], {}) === "none"
      && c.installState(list[0], { juni: { pid: "juni", version: 1 } }) === "installed"
      && c.installState({ ...list[0], version: 3 }, { juni: { pid: "juni", version: 1 } }) === "update");
check("a newer version for one of your profiles", JSON.stringify(c.updateFor({ community: { slug: "juni", version: 1 } },
      [{ ...list[0], version: 2 }])) === JSON.stringify({ slug: "juni", to: 2 })
      && c.updateFor({ community: { slug: "juni", version: 2 } }, [{ ...list[0], version: 2 }]) === null
      && c.updateFor({}, list) === null);
check("what a request is at", c.requestLine({ state: "published", version: 3 }).text === "Live, v3"
      && c.requestLine({ state: "refused", reasons: ["It isn't yours."] }).text === "Refused: It isn't yours."
      && c.requestLine({ state: "checking" }).tone === "busy" && c.requestLine({ state: "checking", action: "remove" }).text === "Removing");

console.log("\n== made for your app, or not ==");
check("the same app, by major and minor: a fix release adds no settings", c.appFit("1.7.1", "1.7.3") === "same"
      && c.appWords("1.7.1", "1.7.3").short === "up to date" && c.appWords("1.7.1", "1.7.3").tone === "good");
check("an older app: settings added since aren't in it", c.appFit("1.6.0", "1.7.1") === "older"
      && c.appFit("1.9.0", "2.0.0") === "older" && c.appWords("1.6.0", "1.7.1").short === "older app"
      && c.appWords("1.6.0", "1.7.1").long.includes("1.6.0") && c.appWords("1.6.0", "1.7.1").tone === "warn");
check("a newer app: update yours to get all of it", c.appFit("1.10.0", "1.9.2") === "newer"
      && c.appWords("1.10.0", "1.9.2").long.includes("Update yours"));
check("nothing judged when either isn't known", c.appFit("", "1.7.1") === "" && c.appFit("1.7.1", "") === ""
      && c.appFit(undefined, undefined) === "" && c.appWords("", "1.7.1").long === ""
      && c.appWords("1.7.1", "").long === "Made with app 1.7.1." && c.appWords("1.7.1", "").short === "");

console.log("\n== short names, as Python makes them ==");
const fixture = JSON.parse(readFileSync(new URL("./community_fixtures/slugs.json", import.meta.url), "utf8"));
const wrong = Object.entries(fixture).filter(([name, want]) => c.slugFrom(name) !== want);
check("the same as community_rules.slug_from for every name in the fixture", wrong.length === 0,
      wrong.map(([n, w]) => `${n} -> ${c.slugFrom(n)} (want ${w})`).join("; "));
check("and each one a valid short name", Object.values(fixture).every((s) => c.SLUG.test(s)));

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
