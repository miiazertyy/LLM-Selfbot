/**
 * The Chats tab's message formatting and live updates. Runs the real
 * webui/src/lib/discordmd.ts and the event merge in webui/src/lib/chats.ts
 * under Node.
 */
import { register } from "node:module";

// The app imports "./api" without an extension, which its bundler allows and
// Node does not. This resolves those to the .ts file, for this test only.
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(spec, ctx, next) {
  try { return await next(spec, ctx); }
  catch (e) {
    if (spec.startsWith(".") && !/\\.[a-z]+$/i.test(spec)) return next(spec + ".ts", ctx);
    throw e;
  }
}`));

const { discordInline: md } = await import("../webui/src/lib/discordmd.ts");
const { applyToUsers } = await import("../webui/src/lib/chats.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

// ── Formatting ─────────────────────────────────────────────────────────────
let h = md("**bold** *it* __under__ ~~gone~~ ||secret||");
check("bold, italic, underline, strike, spoiler",
      h.includes("<strong>bold</strong>") && h.includes("<em>it</em>") && h.includes("<u>under</u>")
      && h.includes("<del>gone</del>") && h.includes('class="dm-spoiler"'), h);

h = md('<img src=x onerror="alert(1)"> & <script>');
check("HTML in a message is escaped, never run",
      !h.includes("<img") && !h.includes("<script") && h.includes("&lt;img") && h.includes("&amp;"), h);

h = md("see https://example.com/a_b_c_d. ok");
check("a link keeps its underscores and drops the full stop",
      h.includes('href="https://example.com/a_b_c_d"') && !h.includes("<em>") && h.includes("</a>. ok"), h);

h = md("javascript:alert(1) and data:text/html,x");
check("only http(s) becomes a link", !h.includes("<a"), h);

h = md("`**not bold**` and ```\n*nor this*\n```");
check("code is left alone", h.includes('<code class="dm-code">**not bold**</code>')
      && h.includes('<pre class="dm-pre">*nor this*</pre>') && !h.includes("<strong>"), h);

h = md("> quoted\n# Big\n- item");
check("quotes, headings and list items",
      h.includes('<span class="dm-quote">quoted</span>') && h.includes('dm-h1">Big')
      && h.includes('<span class="dm-li">item</span>'), h);

h = md("hi <:wave:123456789012345678> <a:dance:123456789012345679>");
check("custom emoji become pictures, animated ones as gif",
      h.includes("emojis/123456789012345678.webp") && h.includes("emojis/123456789012345679.gif"), h);

h = md("snake_case_name and 2*3*4");
check("underscores and stars inside words are not emphasis", !h.includes("<em>"), h);

h = md('https://x.com/"onmouseover="alert(1)');
check("a quote cannot break out of a link", !/href="[^"]*"on/.test(h) && !h.includes('" onmouseover'), h);

// ── Live events ────────────────────────────────────────────────────────────
const base = [{ id: "1", name: "a", snippet: "hi", count: 1, mid: "10", state: { state: "failed", since: 0 } }];

let u = applyToUsers(base, { t: "msg", target: "discord_1", uid: "1", mid: "11", text: "again", snippet: "again", ts: 5 });
check("a new message from someone listed bumps the count and clears a failure",
      u[0].count === 2 && u[0].text === "again" && u[0].state === null && base[0].count === 1, JSON.stringify(u));

u = applyToUsers(base, { t: "msg", target: "discord_1", uid: "1", mid: "10", text: "hi", snippet: "hi" });
check("the same message twice is not counted twice", u[0].count === 1, JSON.stringify(u));

u = applyToUsers(base, { t: "msg", target: "discord_1", uid: "2", name: "b", mid: "20", text: "yo", snippet: "yo", ts: 6 });
check("someone new is added with their message", u.length === 2 && u[1].name === "b" && u[1].count === 1
      && Array.isArray(u[1].attachments), JSON.stringify(u));

u = applyToUsers(base, { t: "state", target: "discord_1", uid: "1", state: { state: "waiting", since: 1, eta: 9 } });
check("a state change lands on the row", u[0].state.eta === 9, JSON.stringify(u));

u = applyToUsers(base, { t: "done", target: "discord_1", uid: "1" });
check("answered comes off the list", u.length === 0);

u = applyToUsers(base, { t: "ignored", target: "discord_1", uid: "1", ignored: true });
check("turned off shows on the row", u[0].ignored === true);

u = applyToUsers(base, { t: "state", target: "discord_1", uid: "9", state: { state: "waiting" } });
check("an event for someone not listed changes nothing", u === base);

// ── Stop on Reply to all ───────────────────────────────────────────────────
// Snapchat writes each answer quickly and sends it later, so by the time Stop
// is pressed, answers are waiting to be sent and one is being written. Stop
// takes all of them back, not only the people after the one in flight.
{
  const chats = await import("../webui/src/lib/chats.ts");
  const { api } = await import("../webui/src/lib/api.ts");
  // A store's value, read the way svelte/store's get does (svelte itself resolves from webui/, not from here).
  const get = (store) => { let v; store.subscribe((x) => (v = x))(); return v; };
  const T = "snapchat_1";
  chats.chatCache.set({ [T]: { users: ["a", "b", "c"].map((id) => ({ id, name: id, snippet: "", count: 1 })),
                               fetched: Date.now(), loading: false, error: "" } });
  const asked = [], cancelled = [];
  let finishB = null;
  const real = { reply: api.reply, chatsCancel: api.chatsCancel, chats: api.chats };
  api.reply = (id) => {
    asked.push(id);
    if (id === "a") return Promise.resolve({ success: true, queued: true });
    return new Promise((resolve) => (finishB = resolve));          // b: being written
  };
  api.chatsCancel = async (id) => {
    cancelled.push(id);
    if (id === "b") finishB?.({ success: false, cancelled: true, reason: "you cancelled the reply" });
    return { ok: true, stopped: true };
  };
  api.chats = async () => ({ users: [] });
  const running = chats.sendReplyAll(T);
  for (let i = 0; i < 50 && !finishB; i++) await new Promise((r) => setTimeout(r, 5));
  check("Reply to all asks one at a time, the first answer written and queued", asked.join() === "a,b", asked.join());
  const stopping = chats.stopReplyAll(T);
  check("Stop says so on the button while it stops", get(chats.replyAllProgress)[T]?.stopping === true);
  await stopping;
  const res = await running;
  check("Stop cancels the reply being written and takes back the one waiting to be sent",
        cancelled.sort().join() === "a,b", cancelled.join());
  check("and nobody after is asked for", !asked.includes("c"), asked.join());
  check("the run says it was stopped, and that nobody was answered after all",
        res?.stopped === true && res.results.every((r) => !r.success && r.cancelled), JSON.stringify(res));
  check("and lets go of the button", !get(chats.replyingAll)[T] && !get(chats.replyAllProgress)[T]);
  Object.assign(api, real);
}

// ── Reacting ───────────────────────────────────────────────────────────────
{
  const chats = await import("../webui/src/lib/chats.ts");
  const { api } = await import("../webui/src/lib/api.ts");
  const get = (store) => { let v; store.subscribe((x) => (v = x))(); return v; };
  const { withReaction, reactionCode } = chats;
  let r = withReaction([{ name: "❤️", count: 1, mine: false }], { name: "❤️" }, true, false);
  check("adding to someone's reaction: two, one the account's", JSON.stringify(r) === '[{"name":"❤️","count":2,"mine":true}]', JSON.stringify(r));
  r = withReaction(r, { name: "😂" }, true, false);
  check("on Discord another is added beside it", r.length === 2 && r[1].mine, JSON.stringify(r));
  r = withReaction([{ name: "❤️", count: 1, mine: true }], { name: "😂" }, true, true);
  check("on Snapchat another replaces the account's own", JSON.stringify(r) === '[{"name":"😂","count":1,"mine":true}]', JSON.stringify(r));
  r = withReaction([{ name: "❤️", count: 2, mine: true }], { name: "❤️" }, false, false);
  check("taking it back leaves the others'", JSON.stringify(r) === '[{"name":"❤️","count":1,"mine":false}]', JSON.stringify(r));
  check("a custom Discord emoji is sent the way Discord writes one",
        reactionCode({ name: "pog", url: "https://cdn.discordapp.com/emojis/123.gif?size=44" }) === "<a:pog:123>"
        && reactionCode({ name: "🔥" }) === "🔥");

  const T = "discord_1", K = chats.convKey(T, "7");
  chats.conversations.set({ [K]: { messages: [{ mine: false, ts: 1, mid: "50", text: "hi" }], loading: false, error: "", at: 1 } });
  const real = api.chatsReact;
  let sent = null;
  api.chatsReact = async (...a) => { sent = a; return { ok: true }; };
  await chats.reactTo(T, "7", "50", { name: "🔥" }, true, false);
  check("a reaction shows at once and goes to the account",
        get(chats.conversations)[K].messages[0].reactions?.[0]?.name === "🔥" && sent?.join() === "7,50,🔥,false,discord_1", String(sent));
  api.chatsReact = async () => { throw new Error("that message is not there any more"); };
  let said = "";
  try { await chats.reactTo(T, "7", "50", { name: "😂" }, true, false); } catch (e) { said = e.message; }
  check("refused, it goes back as it was, and says why",
        said === "that message is not there any more"
        && JSON.stringify(get(chats.conversations)[K].messages[0].reactions) === '[{"name":"🔥","count":1,"mine":true}]');
  api.chatsReact = real;
}

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
