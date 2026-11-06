/**
 * Memory's list, put in order, narrowed down and searched (webui/src/lib/memoryview.ts), run for real under Node on
 * made-up people: every order, every filter, the search word by word and by fact, and a kept view from another build.
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

const M = await import("../webui/src/lib/memoryview.ts");
const { arrange, filtersOn, marks, matchOf, mend, platformIdOf, terms, DEFAULT_VIEW, SORTS, TALKED, ONLY } = M;

let passed = 0;
let failed = 0;
function check(name, cond, extra = "") {
  if (cond) passed++;
  else failed++;
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${name}${!cond && extra ? `  [${extra}]` : ""}`);
}

// A fixed "now": noon on a known day, so today, this week and this month are the same on any machine.
const noon = new Date(2026, 10, 6, 12, 0, 0).getTime() / 1000;
const H = 3600;
const D = 24 * H;
const people = [
  { user_id: "111", username: "mara", facts: { city: "Paris", age: "17" }, fact_count: 2, messages: 40,
    last_seen: noon - 2 * H, first_seen: noon - 90 * D, learned_at: noon - 1 * H, learned: "city" },
  { user_id: "snap_theo", display_name: "Theo", platform: "snapchat", facts: { favourite_food: "sushi" }, fact_count: 1,
    messages: 5, last_seen: noon - 3 * D, first_seen: noon - 4 * D, learned_at: noon - 3 * D },
  { user_id: "tt_lou", display_name: "Lou", platform: "tiktok", facts: { pet: "a cat called Paris" }, fact_count: 1,
    messages: 120, last_seen: noon - 40 * D, first_seen: noon - 200 * D, persona: "be short" },
  { user_id: "222", username: "alex", facts: { city: "Lyon", job: "baker", school: "lycee" }, fact_count: 3, messages: 58,
    last_seen: noon - 20 * D, first_seen: noon - 30 * D, same_as: ["snap_theo"] },
  { user_id: "mc_steve", display_name: "Steve", platform: "minecraft", facts: {}, fact_count: 0, messages: 0 },
];
const nameOf = (p) => p.display_name || p.username || `#${p.user_id}`;
const run = (view, query = "", present) =>
  arrange(people, { ...DEFAULT_VIEW, ...view }, { query, now: noon, nameOf, present }).list.map(nameOf);

console.log("== a kept view ==");
check("nothing kept: the defaults", JSON.stringify(mend(undefined)) === JSON.stringify(DEFAULT_VIEW));
check("what another build kept and this one doesn't know is dropped, the rest kept",
      JSON.stringify(mend({ sort: "facts", talked: "fortnight", on: ["discord", "myspace", "discord", 3], only: ["tone", "x"] }))
      === JSON.stringify({ sort: "facts", talked: "any", on: ["discord"], only: ["tone"] }), JSON.stringify(mend({ sort: "facts", talked: "fortnight", on: ["discord", "myspace", "discord", 3], only: ["tone", "x"] })));
check("an unknown order is the usual one", mend({ sort: "loudest" }).sort === "recent");
check("nine orders, five times, four more filters", SORTS.length === 9 && TALKED.length === 5 && ONLY.length === 4);

console.log("\n== the orders ==");
check("most recent: who talked last first, never-heard-from last", run({ sort: "recent" }).join() === "mara,Theo,alex,Lou,Steve",
      run({ sort: "recent" }).join());
check("oldest: who talked longest ago first, a time nobody knows at the end, not the very oldest",
      run({ sort: "oldest" }).join() === "Lou,alex,Theo,mara,Steve", run({ sort: "oldest" }).join());
check("most remembered", run({ sort: "facts" }).join() === "alex,mara,Theo,Lou,Steve", run({ sort: "facts" }).join());
check("least remembered", run({ sort: "fewest" }).join() === "Steve,Theo,Lou,mara,alex", run({ sort: "fewest" }).join());
check("most messages", run({ sort: "messages" }).join() === "Lou,alex,mara,Theo,Steve", run({ sort: "messages" }).join());
check("just learned: the newest fact first", run({ sort: "learned" })[0] === "mara" && run({ sort: "learned" })[1] === "Theo");
check("newest: met most recently, unknown last", run({ sort: "newest" }).join() === "Theo,alex,mara,Lou,Steve", run({ sort: "newest" }).join());
check("known longest: met first", run({ sort: "longest" }).join() === "Lou,mara,alex,Theo,Steve", run({ sort: "longest" }).join());
check("A to Z, any case", run({ sort: "name" }).join() === "alex,Lou,mara,Steve,Theo", run({ sort: "name" }).join());
check("and the list it was given is left as it was", people.map(nameOf).join() === "mara,Theo,Lou,alex,Steve");

console.log("\n== when they last talked ==");
check("today", run({ talked: "today" }).join() === "mara");
check("this week", run({ talked: "week" }).join() === "mara,Theo");
check("this month", run({ talked: "month" }).join() === "mara,Theo,alex");
check("older: over a month, and never heard from", run({ talked: "older" }).join() === "Lou,Steve", run({ talked: "older" }).join());

console.log("\n== which platform ==");
check("a person's platform: what the list says, or what their id says",
      platformIdOf(people[0]) === "discord" && platformIdOf(people[1]) === "snapchat" && platformIdOf(people[4]) === "minecraft"
      && platformIdOf({ user_id: "tt_x", facts: {} }) === "tiktok");
check("one platform", run({ on: ["snapchat"] }).join() === "Theo");
check("several: any of them", run({ on: ["discord", "tiktok"] }).join() === "mara,alex,Lou", run({ on: ["discord", "tiktok"] }).join());
const present = ["discord", "snapchat", "tiktok", "minecraft"];
check("one kept from before with nobody on it now hides nobody", run({ on: ["whatsapp"] }, "", present).length === 5);
check("and is not counted as a filter on", filtersOn({ ...DEFAULT_VIEW, on: ["whatsapp"] }, present) === 0
      && filtersOn({ ...DEFAULT_VIEW, on: ["snapchat"], talked: "week", only: ["tone"] }, present) === 3);
check("the order is not a filter", filtersOn({ ...DEFAULT_VIEW, sort: "name" }) === 0);

console.log("\n== only ==");
check("learned today", run({ only: ["learned"] }).join() === "mara");
check("2+ facts", run({ only: ["several"] }).join() === "mara,alex");
check("their own tone", run({ only: ["tone"] }).join() === "Lou");
check("linked to another account", run({ only: ["linked"] }).join() === "alex");
check("several at once: each one more to meet", run({ only: ["several", "linked"] }).join() === "alex"
      && run({ only: ["tone", "linked"] }).length === 0);
check("with a time and a platform too", run({ talked: "month", on: ["discord"], only: ["several"] }).join() === "mara,alex");

console.log("\n== the search ==");
check("words, lowercased, any spacing", JSON.stringify(terms("  Paris   17 ")) === JSON.stringify([{ word: "paris" }, { word: "17" }]));
check("a word with a colon looks in one fact, its name as written or in words",
      JSON.stringify(terms("favourite_food:Sushi pet:")) === JSON.stringify([{ key: "favourite food", word: "sushi" }, { key: "pet", word: "" }]));
check("a colon at the start is just a character", JSON.stringify(terms(":)")) === JSON.stringify([{ word: ":)" }]));
check("a name", run({}, "MAR").join() === "mara");
check("an id", run({}, "snap_th").join() === "Theo");
check("a fact anywhere: Paris is Mara's city and Lou's cat", run({}, "paris").join() === "mara,Lou");
check("every word has to be found: Paris and 17 is only Mara", run({}, "paris 17").join() === "mara");
check("words found in different places count: a name and a fact", run({}, "alex baker").join() === "alex");
check("a word found nowhere: nobody", run({}, "paris zzz").length === 0);
check("in one fact: city:paris is Mara, not the cat", run({}, "city:paris").join() === "mara");
check("its name as written, or part of it", run({}, "favourite_food:sushi").join() === "Theo"
      && run({}, "favourite:sushi").join() === "Theo" && run({}, "food:sushi").join() === "Theo");
check("but not a fact of another name", run({}, "city:sushi").length === 0 && run({}, "pet:lyon").length === 0);
check("a fact's name alone: anyone with a pet written down", run({}, "pet:").join() === "Lou");
check("searched and filtered at once", run({ on: ["tiktok"] }, "paris").join() === "Lou");

const m1 = matchOf(people[0], "mara", terms("mara"));
const m2 = matchOf(people[2], "Lou", terms("paris"));
const m3 = matchOf(people[0], "mara", terms("mara 17"));
check("found by the name: nothing more to say", m1 && !m1.fact);
check("found by a fact: which one", m2?.fact?.key === "pet" && m2.fact.value === "a cat called Paris", JSON.stringify(m2));
check("a name and a fact: the fact is said, as it is why", m3?.fact?.key === "age", JSON.stringify(m3));
check("not found: null", matchOf(people[1], "Theo", terms("lyon")) === null);
check("no search: everyone, with nothing found to say", JSON.stringify(matchOf(people[1], "Theo", [])) === "{}");

console.log("\n== the words lit ==");
const lit = (t, q) => marks(t, terms(q)).map(([s, on]) => (on ? `[${s}]` : s)).join("");
check("in place, as written", lit("A cat called Paris", "paris") === "A cat called [Paris]");
check("every time it is there", lit("ana and anabel", "ana") === "[ana] and [ana]bel");
check("two words that overlap are one light", lit("Montenegro", "monte tene") === "[Montene]gro");
check("nothing found: the line as it is", lit("Lyon", "paris") === "Lyon" && marks("Lyon", []).length === 1);

console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
