/**
 * Which socials are on (webui/src/lib/socials.ts), run for real under Node: what the panel remembers from last time,
 * what it takes from the server, and what each kind of id says about whether something belongs on screen.
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

// The browser's storage, with last time's answer in it: Snapchat was off.
const kept = new Map([["socials.on", JSON.stringify({ snapchat: false, discord: true })]]);
globalThis.localStorage = {
  getItem: (k) => (kept.has(k) ? kept.get(k) : null),
  setItem: (k, v) => kept.set(k, String(v)),
  removeItem: (k) => kept.delete(k),
};
// The server, answering /api/socials with whatever the test says.
let answer = null;
let asked = 0;
globalThis.fetch = async (path) => {
  asked++;
  if (answer instanceof Error) throw answer;
  return new Response(JSON.stringify(answer), { status: 200, headers: { "content-type": "application/json" } });
};

const S = await import("../webui/src/lib/socials.ts");
/** A store's value now (svelte/store's get, which this folder cannot import: svelte lives in webui). */
const get = (store) => { let v; store.subscribe((x) => (v = x))(); return v; };

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

// ── As the panel opens: last time's answer, before the server is asked ──────────────────────────────────────────
let on = get(S.socialsOn);
check("every platform has a switch", S.SOCIALS.length === 10 && S.SOCIALS.every((id) => id in on), JSON.stringify(on));
check("one that was off last time starts off, with no flash of it", on.snapchat === false, JSON.stringify(on));
check("the rest start on", S.SOCIALS.filter((id) => id !== "snapchat").every((id) => on[id] === true), JSON.stringify(on));

// ── The server's answer ──────────────────────────────────────────────────────────────────────────────────────────
answer = { on: { discord: true, snapchat: true, tiktok: false, instagram: true, minecraft: true, imessage: true, telegram: true } };
await S.refreshSocials();
on = get(S.socialsOn);
check("asked at /api/socials", asked === 1);
check("its answer is taken", on.snapchat === true && on.tiktok === false, JSON.stringify(on));
check("and kept for next time", JSON.parse(kept.get("socials.on")).tiktok === false, kept.get("socials.on"));

answer = { on: { discord: true } };
await S.refreshSocials();
on = get(S.socialsOn);
check("a platform it does not name counts as on (everything is on by default)",
      S.SOCIALS.every((id) => on[id] === true), JSON.stringify(on));

answer = { on: { tiktok: false } };
await S.refreshSocials();
const before = get(S.socialsOn);
answer = new Error("offline");
await S.refreshSocials();
check("the server not answering keeps the last answer", get(S.socialsOn).tiktok === false && get(S.socialsOn) === before);
answer = { nope: 1 };
await S.refreshSocials();
check("an answer of the wrong shape is ignored", get(S.socialsOn) === before);

let changes = 0;
const stop = S.socialsOn.subscribe(() => changes++);
answer = { on: { tiktok: false } };
await S.refreshSocials();
check("the same answer again changes nothing (pages are not told twice)", changes === 1, String(changes));
stop();

// ── What each id says ────────────────────────────────────────────────────────────────────────────────────────────
on = { ...get(S.socialsOn), tiktok: false, telegram: false, snapchat: false };
check("a platform off is off", S.platformOn(on, "tiktok") === false && S.platformOn(on, "discord") === true);
check("the control bot is not a social", S.platformOn(on, "controller") === true);
check("nothing named is shown", S.platformOn(on, "") === true && S.platformOn(on, undefined) === true);
check("an account of a social switched off is not shown", S.sourceOn(on, "tiktok_2") === false && S.sourceOn(on, "discord_1") === true);
check("a persona's Telegram account goes with Telegram", S.sourceOn(on, "telegram_1") === false);
check("the control bot's own log lines stay", S.sourceOn(on, "telegram") === true);
check("a social's setup goes with it", S.sourceOn(on, "snapchat-install") === false && S.sourceOn(on, "minecraft-install") === true);
check("the app's own sources stay", ["supervisor", "panel", "ai", "system", "updater"].every((s) => S.sourceOn(on, s)));
check("a person by their id: TikTok's", S.personOn(on, "tt_theo-wav") === false);
check("a person by their id: Discord's digits", S.personOn(on, "123456789012345678") === true);
check("a person by their id: Telegram's", S.personOn(on, "tg_42") === false && S.personOn(on, "tgg_7") === false);

console.log(`${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
