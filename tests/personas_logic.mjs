/**
 * The plain parts of persona profiles in the panel: names, colours, what a list says.
 * Runs the real webui/src/lib/personas/logic.ts under Node.
 */
const L = await import("../webui/src/lib/personas/logic.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const P = (id, over = {}) => ({ id, name: id[0].toUpperCase() + id.slice(1), color: "", is_default: id === "default",
  avatar: "", line: "", words: 0, pictures: 0, people: 0, changed: 0, accounts: [], ...over });
const PALETTE = [{ id: "violet", name: "Violet", hex: "#a78bfa" }, { id: "pink", name: "Pink", hex: "#f472b6" },
                 { id: "cyan", name: "Cyan", hex: "#22d3ee" }];

// ── Colours ──────────────────────────────────────────────────────────────────
check("a persona is drawn in its own colour", L.colorOf({ color: "#22d3ee" }) === "#22d3ee");
check("one with none, and none at all, in the theme's accent",
      L.colorOf({ color: "" }) === "var(--color-accent)" && L.colorOf(null) === "var(--color-accent)");
check("a new one gets the next colour nobody has",
      L.nextColor([P("default", { color: "#a78bfa" })], PALETTE) === "#f472b6");
check("skipping any already taken", L.nextColor([P("a", { color: "#a78bfa" }), P("b", { color: "#f472b6" })], PALETTE) === "#22d3ee");
check("and round again once every one is taken",
      L.nextColor(PALETTE.map((c, i) => P(`p${i}`, { color: c.hex })), PALETTE) === PALETTE[0].hex);
check("with no palette, no colour", L.nextColor([], []) === "");

// ── Accounts ─────────────────────────────────────────────────────────────────
check("an account as people say it", L.accountLabel("discord_1") === "Discord #1" && L.accountLabel("snapchat_12") === "Snapchat #12");
check("anything else is left as it is", L.accountLabel("telegram") === "telegram" && L.accountLabel("") === "");
const list = { personas: [P("default"), P("nova", { color: "#22d3ee" })], accounts: { discord_2: "nova" }, palette: PALETTE };
check("an account given a persona speaks as it", L.personaOf(list, "discord_2")?.id === "nova");
check("one given none speaks as Default", L.personaOf(list, "discord_1")?.id === "default");
check("one given a persona since deleted speaks as Default too",
      L.personaOf({ ...list, accounts: { discord_3: "gone" } }, "discord_3")?.id === "default");

// ── Moving an account ────────────────────────────────────────────────────────
check("accounts in the order people count them, 10 after 9",
      JSON.stringify(["snapchat_1", "discord_10", "discord_2", "discord_9"].sort(L.byAccount))
        === '["discord_2","discord_9","discord_10","snapchat_1"]');
const two = { personas: [P("default", { accounts: ["discord_1", "snapchat_1"] }), P("nova", { accounts: ["discord_2"] })],
              accounts: { discord_1: "default", discord_2: "nova", snapchat_1: "default" }, palette: PALETTE };
const moved = L.withAccount(two, "discord_1", "nova");
check("given to another profile, an account leaves the one it was on",
      JSON.stringify(moved.personas[0].accounts) === '["snapchat_1"]', JSON.stringify(moved.personas[0].accounts));
check("and joins this one, in order", JSON.stringify(moved.personas[1].accounts) === '["discord_1","discord_2"]',
      JSON.stringify(moved.personas[1].accounts));
check("the map says so too, and the list it came from is left as it was",
      moved.accounts.discord_1 === "nova" && two.accounts.discord_1 === "default" && two.personas[1].accounts.length === 1);
check("given to the one it is on already: nothing doubles",
      JSON.stringify(L.withAccount(two, "discord_2", "nova").personas[1].accounts) === '["discord_2"]');

// ── Whether a profile is running ─────────────────────────────────────────────
check("no accounts: says so", L.runningLine(0, 0).text === "No accounts yet" && L.runningLine(0, 0).tone === "muted");
check("all up: running", L.runningLine(1, 1).text === "Running" && L.runningLine(3, 3).text === "Running on all 3"
      && L.runningLine(2, 2).tone === "good");
check("some up: how many of how many", L.runningLine(3, 1).text === "Running on 1 of 3");
check("none up, one on its way: what that one says, in amber", L.runningLine(2, 0, "Starting").text === "Starting"
      && L.runningLine(2, 0, "Paused").tone === "warn");
check("none at all: not running", L.runningLine(2, 0).text === "Not running" && L.runningLine(2, 0).tone === "muted");

// ── After a delete ───────────────────────────────────────────────────────────
const three = [P("default"), P("nova"), P("mara")];
check("the one before it is shown", L.afterDelete(three, "mara") === "nova");
check("the first deleted: the next one up", L.afterDelete([P("nova"), P("mara")], "nova") === "mara");
check("the last one left: Default", L.afterDelete([P("nova")], "nova") === "default");

// ── Words ────────────────────────────────────────────────────────────────────
check("a face's letters: the first of one word", L.monogram("juniper") === "J");
check("the first of each of two", L.monogram("Mary Jane Watson") === "MJ");
check("nothing to go on: a question mark", L.monogram("") === "?" && L.monogram("   ") === "?");
check("its own settings, said shortly",
      L.changedLine(0) === "Same as everyone" && L.changedLine(1) === "1 setting of its own" && L.changedLine(3) === "3 settings of its own");
check("a list as it is said",
      L.joinAnd([]) === "" && L.joinAnd(["Discord #1"]) === "Discord #1"
      && L.joinAnd(["Discord #1", "Snapchat #1"]) === "Discord #1 and Snapchat #1"
      && L.joinAnd(["a", "b", "c"]) === "a, b and c", L.joinAnd(["a", "b", "c"]));
check("a value for people: switches as On and Off", L.shortValue(true) === "On" && L.shortValue(false) === "Off");
check("nothing as None", L.shortValue(null) === "None" && L.shortValue(undefined) === "None" && L.shortValue("") === "None"
      && L.shortValue([]) === "None");
check("a list by its first items", L.shortValue(["a", "b", "c", "d", "e"]) === "a, b, c +2", L.shortValue(["a", "b", "c", "d", "e"]));
check("a table by its size", L.shortValue({ a: 1 }) === "1 item" && L.shortValue({ a: 1, b: 2 }) === "2 items");
const long = L.shortValue("x".repeat(60));
check("a long one cut short, with an ellipsis", long.length === 28 && long.endsWith("…"), long);

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
