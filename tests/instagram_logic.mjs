/**
 * Instagram's runner, its pure parts, under Node: the six digits it makes from a 2FA key (against RFC 6238's own
 * vectors), the ids it gives people and groups, the usernames and threads it reads off links, Instagram's refusals
 * said plainly, and the keys that keep a conversation read twice from doubling.
 *
 * instagrambot.js imports the browser (puppeteer-extra) at the top, which only the app's install has: those two
 * packages are stood in for here, and nothing that needs a browser is called.
 */
import { registerHooks } from "node:module";

const STUBS = {
  "puppeteer-extra": "export default { use() {}, launch() { throw new Error('no browser in a test'); } };",
  "puppeteer-extra-plugin-stealth": "export default function Stealth() { return {}; }",
};
registerHooks({
  resolve(specifier, context, next) {
    if (STUBS[specifier]) return { url: "data:text/javascript," + encodeURIComponent(STUBS[specifier]), shortCircuit: true };
    return next(specifier, context);
  },
});

const bot = await import("../app/platforms/snapchat/instagrambot.js");
const core = await import("../app/platforms/snapchat/runner_core.js");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

// ── The six digits from a 2FA key ────────────────────────────────────────────
// RFC 6238's own test vectors, for the SHA-1 key "12345678901234567890" written as base32.
console.log("== the code its 2FA key makes ==");
const RFC_KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
const VECTORS = [[59, "287082"], [1111111109, "081804"], [1111111111, "050471"],
                 [1234567890, "005924"], [2000000000, "279037"], [20000000000, "353130"]];
for (const [at, want] of VECTORS) {
  check(`at ${at}s it is ${want}`, bot.totp(RFC_KEY, at * 1000) === want, bot.totp(RFC_KEY, at * 1000));
}
check("a key as Instagram shows it, spaces and case and all",
      bot.totp("gezd gnbv gy3t qojq gezd gnbv gy3t qojq", 59000) === "287082");
check("and nothing from a key that is not one",
      ["", "nope!", "0189", null, undefined].every((k) => bot.totp(k, 59000) === ""));
// 0, 1, 8 and 9 are not base32 letters, so a key holding one could never have come from Instagram.
check("its bytes, or nothing", bot.base32Bytes("GEZDGNBVGY3TQOJQ")?.length === 10
      && bot.base32Bytes("G18M E4E3") === null && bot.base32Bytes("nope!") === null);
check("how long the code has left, so a stale one is not typed",
      bot.totpLeft(0) === 30 && bot.totpLeft(29000) === 1 && bot.totpLeft(30000) === 30);

// ── Who someone is ───────────────────────────────────────────────────────────
console.log("\n== who someone is ==");
check("a username as Instagram allows it", bot.cleanUsername("@Theo.Wav") === "theo.wav"
      && bot.cleanUsername("mara_k") === "mara_k" && bot.cleanUsername("a".repeat(30)) === "a".repeat(30));
check("anything else is none", ["", "a".repeat(31), ".theo", "theo.", "theo wav", "a/b", "../x"]
      .every((u) => bot.cleanUsername(u) === ""));
check("their id is ig_ and their username, dots as dashes", bot.chatIdFor("theo.wav") === "ig_theo-wav"
      && bot.chatIdFor("@MARA_K") === "ig_mara_k");
check("and reads back exactly", bot.usernameOf(bot.chatIdFor("theo.wav")) === "theo.wav"
      && bot.usernameOf("ig_mara_k") === "mara_k" && bot.usernameOf("tt_theo-wav") === "");
check("a group is igg_ and its thread", bot.groupIdFor("340282366841710300949128") === "igg_340282366841710300949128"
      && bot.groupIdFor("") === "");

// ── What a link points at ────────────────────────────────────────────────────
console.log("\n== what a link points at ==");
check("a profile link is a person", bot.usernameFromHref("/theo.wav/") === "theo.wav"
      && bot.usernameFromHref("https://www.instagram.com/mara_k") === "mara_k");
check("Instagram's own pages are not", ["/explore/", "/direct/", "/reels/", "/p/", "/accounts/", "/stories/"]
      .every((h) => bot.usernameFromHref(h) === ""));
check("nor anything else", bot.usernameFromHref("/a/b/") === "" && bot.usernameFromHref("https://evil.example/theo/") === "");
check("a conversation's thread is in its own link", bot.threadIdFromHref("/direct/t/340282366841710300949128/")
      === "340282366841710300949128" && bot.threadIdFromHref("/direct/inbox/") === "");

// ── The markers it leans on ──────────────────────────────────────────────────
console.log("\n== the markers it leans on ==");
check("every one of them is a list of fallbacks", Object.values(bot.SEL).every((v) => Array.isArray(v) && v.length));
check("a conversation is found by its link, which the page cannot do without",
      bot.SEL.threadLink.some((s) => s.includes("/direct/t/")));
check("the box to type in, by what it is rather than how it looks",
      bot.SEL.composer.some((s) => s.includes('role="textbox"')));
check("and the rest by Instagram's own words for them",
      bot.SEL.reactButton.concat(bot.SEL.replyButton, bot.SEL.moreButton).every((s) => s.includes("aria-label")));

// ── The keys a conversation's messages get ───────────────────────────────────
console.log("\n== reading a conversation twice does not double it ==");
const raw = [
  { day: "Today", mine: false, text: "hey", kind: "" },
  { day: "", mine: true, text: "hey you", kind: "" },
  { day: "", mine: false, text: "hey", kind: "" },                 // the same words again, that same day
  { day: "", mine: false, text: "", kind: "reel", media: { url: "https://www.instagram.com/reel/ABCDE/" } },
];
const once = core.keyed("ig_theo-wav", raw, { prefix: "i" });
const twice = core.keyed("ig_theo-wav", raw, { prefix: "i" });
check("the same conversation reads to the same keys", once.map((m) => m.key).join() === twice.map((m) => m.key).join());
check("the same words twice are two messages, not one", new Set(once.map((m) => m.key)).size === 4);
check("whose each one is, and what it is when it is not words",
      once[1].mine === true && once[3].kind === "reel" && once[3].media.url.includes("/reel/ABCDE/"));
check("another conversation's are its own",
      core.keyed("ig_mara_k", raw, { prefix: "i" })[0].key !== once[0].key);
check("and Instagram's keys are not TikTok's", once[0].key.startsWith("i")
      && core.keyed("ig_theo-wav", raw, { prefix: "k" })[0].key !== once[0].key);

// ── The day over a run of messages ───────────────────────────────────────────
console.log("\n== the day over a run of messages ==");
const now = new Date(2026, 9, 11, 14, 30);
check("Instagram's own labels", core.dayOfLabel("Today", now) === "2026-10-11"
      && core.dayOfLabel("Yesterday", now) === "2026-10-10");
check("a weekday is the one just gone", core.dayOfLabel("Friday", now) === "2026-10-09");
check("a date in full", core.dayOfLabel("October 4, 2026", now) === "2026-10-04"
      && core.dayOfLabel("Oct 4", now) === "2026-10-04");
check("a time alone is that time today", core.atOfLabel("09:43", now) === new Date(2026, 9, 11, 9, 43).getTime());
// One still to come today was yesterday's: the inbox is read just after midnight too.
check("unless it is still to come, which means yesterday",
      core.atOfLabel("21:43", now) === new Date(2026, 9, 10, 21, 43).getTime());
check("and nothing at all when it says nothing", core.dayOfLabel("", now) === "" && core.atOfLabel("hey", now) === 0);

// ── Instagram's refusals, said plainly ───────────────────────────────────────
console.log("\n== Instagram's refusals, said plainly ==");
for (const [said, want] of [
  ["Couldn't send message", "send"],
  ["Try again later", "wait"],
  ["This account is restricted", "restrict"],
  ["You can't message this account", "message"],
]) {
  const why = bot.warningReason ? bot.warningReason(said) : "";
  check(`"${said}" becomes something a person can read`, !!why && new RegExp(want, "i").test(why), why);
}
check("and what it does not know becomes nothing", bot.warningReason ? bot.warningReason("hello there") === "" : true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
