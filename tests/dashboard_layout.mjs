/**
 * The Dashboard's saved layout: building it, and cleaning up whatever an older
 * build, another machine, or a hand edit left in it. Runs the real
 * webui/src/lib/dashboard/widgets.ts under Node.
 */
import { register } from "node:module";

// The app imports "../stores" without an extension, which its bundler allows
// and Node does not. This resolves those to the .ts file, for this test only.
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(spec, ctx, next) {
  try { return await next(spec, ctx); }
  catch (e) {
    if (spec.startsWith(".") && !/\\.[a-z]+$/i.test(spec)) return next(spec + ".ts", ctx);
    throw e;
  }
}`));

const get = (store) => { let v; store.subscribe((x) => (v = x))(); return v; };

const stores = await import("../webui/src/lib/stores.ts");
const w = await import("../webui/src/lib/dashboard/widgets.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

// A fresh Dashboard shows what it always showed.
stores.dashOrder.set(null);
let fresh = w.initialLayout();
check("a fresh layout is the five it always had",
      fresh.map((x) => x.type).join() === "figures,activity,accounts,people,log", fresh.map((x) => x.type).join());

// Someone who had already rearranged keeps their order.
stores.dashOrder.set(["log", "people", "figures", "activity", "accounts"]);
const moved = w.initialLayout().map((x) => x.type).join();
check("an order arranged before widgets existed carries over",
      moved === "log,people,figures,activity,accounts", moved);
stores.dashOrder.set(["log", "gone-section"]);
const partial = w.initialLayout().map((x) => x.type).join();
check("and anything missing from it is added after", partial === "log,figures,activity,accounts,people", partial);

// Every widget starts with its defaults.
const people = w.makeInstance("people");
check("a new widget gets its default settings", people.options.days === 7 && people.options.count === 5,
      JSON.stringify(people.options));
check("and its natural width", people.size === "half" && w.makeInstance("figures").size === "full");
check("and a unique id", w.makeInstance("hours").id !== w.makeInstance("hours").id);

// Cleaning up a damaged or outdated layout.
const messy = [
  { id: "a", type: "people", options: { days: 30, count: 999 } },   // count no longer a choice
  { id: "b", type: "retired-widget" },                              // widget that no longer exists
  { id: "a", type: "people" },                                      // duplicate id
  { id: "c", type: "log", size: "enormous", collapsed: 1 },         // bad size, truthy fold
  null,
];
const clean = w.normalise(messy);
check("widgets that no longer exist are dropped", !clean.some((x) => x.type === "retired-widget"));
check("a duplicated widget is kept once", clean.filter((x) => x.id === "a").length === 1);
check("a setting that is still valid is kept", clean[0].options.days === 30);
check("one that is not falls back to its default", clean[0].options.count === 5, String(clean[0].options.count));
check("an impossible width falls back", clean[1].size === "half", clean[1].size);
check("folded state is a real boolean", clean[1].collapsed === true);
check("a missing layout builds a fresh one", w.normalise(null).length === 5);
check("so does one that is not a list", w.normalise({ nope: 1 }).length === 5);

// Changing one widget changes only that one, and saves.
stores.dashLayout.set([w.makeInstance("hours"), w.makeInstance("weekdays")]);
const [h, d] = get(stores.dashLayout);
w.updateWidget(h.id, { collapsed: true });
w.setOption(d.id, "days", 90);
const after = get(stores.dashLayout);
check("folding one widget folds only that one", after[0].collapsed === true && after[1].collapsed === false);
check("changing a setting changes only that widget", after[1].options.days === 90 && after[0].options.days === 30);
w.setOption(d.id, "days", 12345);
check("a value that is not one of the choices is refused on the next clean-up",
      w.normalise(get(stores.dashLayout))[1].options.days === 30);

// Every widget in the gallery is one the Dashboard can draw.
const body = (await import("node:fs")).readFileSync(
  new URL("../webui/src/lib/dashboard/WidgetBody.svelte", import.meta.url), "utf-8");
const undrawn = Object.keys(w.WIDGETS).filter((t) => !body.includes(`inst.type === "${t}"`));
check("every widget in the gallery has a body", undrawn.length === 0, undrawn.join());
check("every widget's defaults are among its own choices",
      Object.values(w.WIDGETS).every((d) => (d.options ?? []).every((o) => o.choices.some((c) => c.value === o.default))));

// The widgets share one sheet: where each sits decides its seams.
const at = (sizes) => w.placeOnSheet(sizes.map((size, i) => ({ id: "w" + i, type: "log", collapsed: false, size, options: {} })))
  .map((s) => `${s.row}${s.wide ? "W" : s.right ? "R" : "L"}`).join(" ");
check("two halves share a row, left then right", at(["half", "half"]) === "0L 0R", at(["half", "half"]));
check("a half with nothing beside it takes the whole row", at(["half", "full", "half"]) === "0W 1W 2W",
      at(["half", "full", "half"]));
check("three halves: a pair, then one across", at(["half", "half", "half"]) === "0L 0R 1W", at(["half", "half", "half"]));
check("a full widget always starts its own row", at(["full", "half", "half", "full"]) === "0W 1L 1R 2W",
      at(["full", "half", "half", "full"]));
check("an empty Dashboard has nothing to seat", w.placeOnSheet([]).length === 0);

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
