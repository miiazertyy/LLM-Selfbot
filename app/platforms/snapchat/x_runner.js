/**
 * The X account: its messages answered, the people who reply to it or @ it answered in the thread, posts of its
 * own, and the likes, reposts and follows that make an account look like somebody's.
 *
 * Built on runner_core.js, like the TikTok and Instagram runners, and laid out section for section like
 * instagram_runner.js so a change to one can be read against the other. The page itself is xbot.js.
 *
 * X minds an account that looks automated sooner than they do, and what it does about it is lock the account
 * rather than slow it down. So: everything public is off until it is switched on, every public thing it does is
 * capped for the day, and a login X refuses ends the process with code 4 - never a second try. The supervisor
 * leaves it stopped and tells the person (app/web/supervisor.py).
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { randomUUID } from "crypto";

import XBot, { SEL, chatIdFor, handleOf, groupIdFor, cleanHandle, CHAT_ID } from "./xbot.js";
import { SiteWatch, applySiteFixes } from "./sitewatch.js";
import { createCore, createBudget, keyed, readJson, writeJson, delay } from "./runner_core.js";
import { patchConsole } from "./log.js";

patchConsole();

const TAG = "[X]";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.X_DATA_DIR || process.env.SNAP_DATA_DIR || path.resolve(HERE, "../../../");
const ACCOUNT = parseInt(process.env.X_ACCOUNT_INDEX || "1", 10) || 1;

const envFor = (name) => process.env[`${name}_${ACCOUNT}`] ?? (ACCOUNT === 1 ? process.env[name] : "") ?? "";
const HANDLE = cleanHandle(envFor("X_USERNAME"));
const PASSWORD = String(envFor("X_PASSWORD") || "");
const TOTP_KEY = String(envFor("X_TOTP") || "").replace(/[\s-]/g, "");
const EMAIL = String(envFor("X_EMAIL") || "").trim();

const PROFILE_DIR = path.join(DATA_DIR, "config", `x-${HANDLE}-profile`);
const IDENTITY_FILE = path.join(DATA_DIR, "config", `identity_x_${ACCOUNT}.json`);
const PEOPLE_DIR = path.join(DATA_DIR, "cache", "x_people");
const CONTACTS_FILE = path.join(PEOPLE_DIR, `contacts_${ACCOUNT}.json`);
const MENTIONS_FILE = path.join(PEOPLE_DIR, `mentions_${ACCOUNT}.json`);
const SYSTEM_CHATS = ["x", "twitter", "x support", "grok"];
const PICTURE_HOSTS = /^(pbs|abs|ton)\.twimg\.com$|^abs-\d\.twimg\.com$/;

const core = createCore({
  prefix: "x", env: "X", account: ACCOUNT, dataDir: DATA_DIR, tag: TAG,
  // What it runs at when the settings file has no x: section - one written before this platform existed. The same
  // numbers as resources/config.yaml, so a fresh install and an old one behave alike.
  defaults: {
    POLL_INTERVAL_MS: 20000, MAX_RECIPIENTS: 8, RESPONSE_TIMEOUT_MS: 90000,
    MIN_SEND_GAP_MS: 30000, MAX_SEND_GAP_MS: 90000, MAX_SENDS_PER_HOUR: 12,
    RELOAD_INTERVAL_MS: 2700000, ACCEPT_MESSAGE_REQUESTS: false,
    MENTIONS: false, MENTION_REPLIES: true, OWN_REPLIES: true, OWN_POSTS_WATCHED: 3,
    MENTIONS_PER_HOUR: 3, MENTIONS_PER_PASS: 3, MENTION_SCROLLS: 3, SKIP_STRANGERS: true,
    LIKE_SENT: false, REPOST_SENT: false, LIKE_THEIRS: false, REPOST_THEIRS: false, FOLLOW_BACK: false,
    LIKES_PER_DAY: 10, REPOSTS_PER_DAY: 2, FOLLOWS_PER_DAY: 3, REPLIES_PER_DAY: 10,
    POSTING: false, POSTS_PER_DAY: 2, POST_MIN_GAP_MIN: 180, POST_MAX_CHARS: 270, THREAD_MAX: 1,
    POST_WITH_IMAGE: false, WATCH: true, THEIR_POSTS: true, THREADS: true,
    ACCEPT_DELAY_MIN: 120, ACCEPT_DELAY_MAX: 600,
  },
});

const HIDDEN = core.flag("HEADLESS", false);
const DRY_RUN = core.flag("DRY_RUN", false);
const LOCALE = core.text("LOCALE", "en-US");
const TIMEZONE = core.text("TIMEZONE", "");
const MONTH_FIRST = !/^(en-GB|fr|de|es|it|pt|nl|pl|ru)/i.test(LOCALE);
const MAX_RECIPIENTS = core.num("MAX_RECIPIENTS", 8);
const RESPONSE_TTL_MS = core.num("RESPONSE_TIMEOUT_MS", 90000) * 3;
const RELOAD_MS = core.num("RELOAD_INTERVAL_MS", 2700000);
const ACCEPT_REQUESTS = core.flag("ACCEPT_MESSAGE_REQUESTS", false);
const ACCEPT_DELAY_MIN = core.num("ACCEPT_DELAY_MIN", 120);
const ACCEPT_DELAY_MAX = core.num("ACCEPT_DELAY_MAX", 600);
const MENTIONS_ON = core.flag("MENTIONS", false);
const MENTION_REPLIES = core.flag("MENTION_REPLIES", true);
const OWN_REPLIES = core.flag("OWN_REPLIES", true);
const OWN_POSTS_WATCHED = core.num("OWN_POSTS_WATCHED", 3);
const MENTIONS_PER_HOUR = core.num("MENTIONS_PER_HOUR", 3);
const MENTIONS_PER_PASS = core.num("MENTIONS_PER_PASS", 3);
const MENTION_SCROLLS = core.num("MENTION_SCROLLS", 3);
const SKIP_STRANGERS = core.flag("SKIP_STRANGERS", true);
const LIKE_SENT = core.flag("LIKE_SENT", false);
const REPOST_SENT = core.flag("REPOST_SENT", false);
const LIKE_THEIRS = core.flag("LIKE_THEIRS", false);
const REPOST_THEIRS = core.flag("REPOST_THEIRS", false);
const FOLLOW_BACK = core.flag("FOLLOW_BACK", false);
const POSTING = core.flag("POSTING", false);
const POST_MIN_GAP_MIN = core.num("POST_MIN_GAP_MIN", 180);
const POST_MAX_CHARS = core.num("POST_MAX_CHARS", 270);
const THREAD_MAX = core.num("THREAD_MAX", 1);
const WATCH = core.flag("WATCH", true);
const THEIR_POSTS = core.flag("THEIR_POSTS", true);

fs.mkdirSync(PEOPLE_DIR, { recursive: true });
const budget = createBudget(path.join(PEOPLE_DIR, `budget_${ACCOUNT}.json`), {
  likes: core.num("LIKES_PER_DAY", 10),
  reposts: core.num("REPOSTS_PER_DAY", 2),
  follows: core.num("FOLLOWS_PER_DAY", 3),
  // Public answers: the @s and the replies under its own posts, together.
  replies: core.num("REPLIES_PER_DAY", 10),
  posts: core.num("POSTS_PER_DAY", 2),
});

// The few things that should always be on the pages it sits on, and a fix for any of its selectors without a new build
// (sitewatch.js). Only ever looked for on tabs it already has open.
applySiteFixes(SEL, "x", DATA_DIR, (m) => console.log(`${TAG} ${m}`));
const siteWatch = new SiteWatch({
  core: [
    { name: "the page itself", sel: SEL.primary, on: /(?:x|twitter)\.com\/(?:home|messages|notifications)/ },
    { name: "the list of chats", sel: SEL.conversation, on: /(?:x|twitter)\.com\/messages\/?$/ },
  ],
  pages: () => bot?.browser?.pages(),
  report: (missing) => core.keepSaying(missing.length ? { site: { missing } } : {}),
});

let bot = null;
let pending = new Map();        // what was handed over and is waiting on an answer
let listChanged = false;
let signInState = "";
let identityAt = 0;

// ── Who it has talked to ─────────────────────────────────────────────────────

function contacts() {
  const c = readJson(CONTACTS_FILE, {});
  return c && typeof c === "object" && !Array.isArray(c) ? c : {};
}

/** Keep what is known of someone, writing only when it actually changed. */
async function remember(chatId, name, avatar, extra = null) {
  if (!CHAT_ID.test(chatId)) return;
  const all = contacts();
  const was = all[chatId] || {};
  const next = { ...was, name: name || was.name || "", seen: Math.round(Date.now() / 1000), ...(extra || {}) };
  if (avatar && avatar !== was.url) {
    const file = await savePicture(avatar, `x_${ACCOUNT}_${chatId.replace(/[^a-z0-9_]/gi, "")}`);
    if (file) { next.file = path.basename(file); next.url = avatar; }
  }
  const same = JSON.stringify({ ...was, seen: 0 }) === JSON.stringify({ ...next, seen: 0 });
  if (same) return;
  all[chatId] = next;
  try { writeJson(CONTACTS_FILE, all); } catch { /* next time */ }
}

/** Someone's picture, kept beside the app. Only from X's own picture hosts. */
async function savePicture(url, stem) {
  try {
    const host = new URL(url).hostname;
    if (!PICTURE_HOSTS.test(host)) return "";
  } catch {
    return "";
  }
  try {
    const page = await bot.outPage();
    const got = await page.evaluate(async (u) => {
      const r = await fetch(u, { credentials: "include" });
      if (!r.ok) return null;
      const b = await r.arrayBuffer();
      if (b.byteLength < 100 || b.byteLength > 3e6) return null;
      return { type: r.headers.get("content-type") || "", data: [...new Uint8Array(b)] };
    }, url).catch(() => null);
    if (!got) return "";
    const ext = /png/.test(got.type) ? "png" : /webp/.test(got.type) ? "webp" : "jpg";
    const file = path.join(PEOPLE_DIR, `${stem}.${ext}`);
    fs.writeFileSync(file, Buffer.from(got.data));
    return file;
  } catch {
    return "";
  }
}

/** Its own name, handle, picture and counts, for the account card. Kept, not overwritten with nothing. */
async function recordIdentity() {
  const me = await bot.whoAmI().catch(() => ({}));
  if (!me || !me.handle) return;
  const was = readJson(IDENTITY_FILE, {});
  // The profile did not load: keep what was known rather than write the page's emptiness over it.
  if (!me.profiled && was.username) { identityAt = Date.now() - 3.5 * 3600 * 1000; return; }
  const out = {
    username: me.handle,
    display_name: me.name || was.display_name || "",
    picture: was.picture || "",
    picture_url: was.picture_url || "",
    bio: me.bio || "",
    followers: me.followers || 0,
    following: me.following || 0,
    posts: me.posts || 0,
    verified: !!me.verified,
    private: !!me.protected,
    at: Date.now() / 1000,
  };
  // The picture is fetched again only when its own path changed, not when its signed address did.
  const pathOf = (u) => { try { return new URL(u).pathname; } catch { return u || ""; } };
  if (me.avatar && pathOf(me.avatar) !== pathOf(was.picture_url)) {
    const file = await savePicture(me.avatar, `identity_x_${ACCOUNT}`);
    if (file) {
      const dest = path.join(DATA_DIR, "config", path.basename(file));
      try { fs.copyFileSync(file, dest); out.picture = path.basename(dest); out.picture_url = me.avatar; }
      catch { /* keep the old one */ }
    }
  }
  try { writeJson(IDENTITY_FILE, out); } catch { /* next time */ }
  identityAt = Date.now();
}

// ── Reading a conversation ───────────────────────────────────────────────────

const keyedChat = (chatId, msgs) => keyed(chatId, msgs, { monthFirst: MONTH_FIRST, prefix: "x" });

/** The whole conversation sent up, so the panel's Chats tab shows it as it is. */
function share(chatId, name, messages) {
  core.tellPython({ kind: "transcript", chat: chatId, name, messages: messages.slice(-120) });
}

/** A message turned into something the persona can read. */
function describe(m) {
  if (m.text) return m.text;
  if (m.kind === "photo") return "[sent a photo]";
  if (m.kind === "video") return "[sent a video]";
  if (m.kind === "link") return `[shared a link: ${(m.links || [])[0] || ""}]`;
  return "[sent something]";
}

/** The chat id for a row of the conversation list. */
function idOfRow(row) {
  if (!row.group && row.handles.length === 1) return chatIdFor(row.handles[0]);
  if (row.conversation) return groupIdFor(row.conversation);
  return row.handles.length === 1 ? chatIdFor(row.handles[0]) : "";
}

/** Open a conversation, read it, and hand over whatever is new and theirs. */
async function readChat(row) {
  const chatId = idOfRow(row);
  if (!chatId || !CHAT_ID.test(chatId)) return;
  if (SYSTEM_CHATS.includes(String(row.name || "").toLowerCase().trim())) return;
  const opened = await bot.openChat(chatId, { conversation: row.conversation });
  if (!opened) return;
  await remember(chatId, row.name, row.avatar, row.conversation ? { conversation: row.conversation } : null);
  const chat = await bot.readChat().catch(() => null);
  if (!chat) return;
  const msgs = keyedChat(chatId, chat.messages);
  share(chatId, row.name, msgs);
  // Everything after the last thing it said itself.
  let from = 0;
  for (let i = msgs.length - 1; i >= 0; i--) if (msgs[i].mine) { from = i + 1; break; }
  const fresh = msgs.slice(from).filter((m) => !m.mine && core.isNew(chatId, m.key));
  if (!fresh.length) return;
  const content = fresh.map(describe).filter(Boolean).join("\n").slice(0, 4000);
  if (!content) return;
  const id = randomUUID();
  core.handOver({
    id,
    user_id: chatId,
    user_name: row.name || `@${handleOf(chatId)}`,
    channel_id: chatId,
    content,
    group: row.group || undefined,
    photo: true,
  });
  pending.set(id, { chatId, name: row.name, ts: Date.now() });
  console.log(`  ${row.name || chatId}: ${content.slice(0, 80)}`);
}

// ── Sending what the bridge wrote ────────────────────────────────────────────

/** Answers that wait for a slot of their own, not a message's. */
const OWN_PACE = new Set(["post", "thread"]);

async function drainResponses() {
  const now = Date.now();
  for (const [id, p] of pending) if (now - p.ts > RESPONSE_TTL_MS) pending.delete(id);
  const waiting = core.responses();
  for (const id of Object.keys(waiting)) {
    const kind = (waiting[id] && typeof waiting[id] === "object" && waiting[id].kind) || "dm";
    if (OWN_PACE.has(kind)) continue;
    if (kind === "comment" ? !mentionAllowed() : !core.sendAllowed()) break;
    const val = core.take(id);
    if (val == null) continue;
    const text = val && typeof val === "object" ? val.text : val;
    const chatId = val && typeof val === "object" ? val.chat : pending.get(id)?.chatId;
    const name = (val && val.name) || pending.get(id)?.name || chatId;
    pending.delete(id);
    if (!text) continue;
    const attempts = ((val && val._attempts) || 0) + 1;
    let out = { ok: false };
    try {
      if (kind === "comment") {
        out = await replyMention(val, text);
      } else if (chatId && (await bot.openChat(chatId))) {
        await delay(800 + Math.random() * 2200);          // it reads it again before answering
        out = await bot.sendText(text, { dryRun: DRY_RUN });
      } else {
        out = { ok: false, reason: "could not open their conversation" };
      }
    } catch (e) {
      out = { ok: false, reason: e.message };
    }
    if (out.ok) {
      if (kind === "comment") { mentionSent(); budget.spend("replies"); } else core.recordSend();
      console.log(`  sent to ${name}${out.dry ? " (dry run)" : ""}`);
      if (kind !== "comment" && chatId) {
        const chat = await bot.readChat().catch(() => null);
        if (chat) share(chatId, name, keyedChat(chatId, chat.messages));
      }
      await delay(500 + Math.random() * 900);
    } else if (/wait before|rate limit|too fast|try again/i.test(out.reason || "")) {
      // Told to slow down: put it back, burn a slot, and stop this pass.
      console.warn(`${TAG} ${out.reason}.`);
      core.putBack(id, { ...(typeof val === "object" ? val : { text, chat: chatId, name }), _attempts: attempts });
      core.recordSend();
      core.setState("ready", `${out.reason}.`);
      break;
    } else if (attempts >= 4 || /locked|suspended|cannot send|does not let/i.test(out.reason || "")) {
      console.warn(`${TAG} Not sent to ${name}: ${out.reason || "it would not go"}.`);
    } else {
      core.putBack(id, { ...(typeof val === "object" ? val : { text, chat: chatId, name }), _attempts: attempts });
    }
  }
}

/** Messages the bridge sends on its own: a Reply from the panel, a nudge, a picture. */
async function processOutgoing() {
  const queue = readJson(core.files.outgoing, []);
  if (!Array.isArray(queue) || !queue.length) return;
  if (!core.sendAllowed()) return;
  const item = queue[0];
  writeJson(core.files.outgoing, queue.slice(1));        // written back first: a crash drops one, never loops it
  const chatId = item.chat;
  if (!chatId || !CHAT_ID.test(chatId)) return;
  if (!(await bot.openChat(chatId))) return;
  let sent = false;
  if (item.image && fs.existsSync(item.image)) {
    const r = await bot.sendImage(item.image, { dryRun: DRY_RUN }).catch(() => ({ ok: false }));
    sent = sent || r.ok;
  }
  if (item.message) {
    await delay(core.typingTime(item.message) * 0.25);
    const r = await bot.sendText(item.message, { dryRun: DRY_RUN }).catch(() => ({ ok: false }));
    sent = sent || r.ok;
  }
  if (sent) {
    core.recordSend();
    const chat = await bot.readChat().catch(() => null);
    if (chat) share(chatId, item.name || chatId, keyedChat(chatId, chat.messages));
  }
}

/** Posts of its own, which wait for a post's own slot rather than a message's. */
async function drainOwnPosts() {
  const waiting = core.responses();
  for (const id of Object.keys(waiting)) {
    const val = waiting[id];
    const kind = (val && typeof val === "object" && val.kind) || "dm";
    if (!OWN_PACE.has(kind)) continue;
    if (!postAllowed()) return;
    const taken = core.take(id);
    if (taken == null) continue;
    const text = String(taken.text || "").slice(0, POST_MAX_CHARS);
    if (!text) continue;
    const thread = Array.isArray(taken.thread) ? taken.thread.slice(0, Math.max(0, THREAD_MAX - 1)) : [];
    const out = await bot.post(text, { images: taken.images || [], thread, dryRun: DRY_RUN })
      .catch((e) => ({ ok: false, reason: e.message }));
    if (out.ok) {
      postSent();
      budget.spend("posts");
      console.log(`${TAG} Posted${out.dry ? " (dry run)" : ""}: ${text.slice(0, 70)}`);
    } else {
      console.warn(`${TAG} The post did not go up: ${out.reason || "X would not take it"}.`);
    }
    return;                                              // one post a pass, whatever else is waiting
  }
}

// ── What is said to it in public ─────────────────────────────────────────────

let mentionTimes = [];
const mentionAllowed = () => {
  const now = Date.now();
  mentionTimes = mentionTimes.filter((t) => now - t < 3600000);
  return mentionTimes.length < MENTIONS_PER_HOUR && budget.allowed("replies");
};
const mentionSent = () => mentionTimes.push(Date.now());

let lastPostAt = 0;
const postAllowed = () => POSTING && budget.allowed("posts")
  && Date.now() - lastPostAt >= POST_MIN_GAP_MIN * 60 * 1000;
const postSent = () => { lastPostAt = Date.now(); };

/** Answer one @ or reply, in its own thread. */
async function replyMention(val, text) {
  const url = val.video || val.url || "";
  if (!url) return { ok: false, reason: "that post has no address" };
  return bot.replyTo(url, text, { dryRun: DRY_RUN });
}

function mentionLedger() {
  const l = readJson(MENTIONS_FILE, null);
  return l && Array.isArray(l.seen) ? l : { newest: "", seen: [] };
}

let mentionsDueAt = 0;
async function maybeMentions() {
  if (!MENTIONS_ON || Date.now() < mentionsDueAt) return;
  mentionsDueAt = Date.now() + (10 + Math.random() * 10) * 60 * 1000;
  if (!mentionAllowed()) return;
  const found = [];
  if (MENTION_REPLIES) found.push(...await bot.mentions({ scrolls: MENTION_SCROLLS }).catch(() => []));
  if (OWN_REPLIES) found.push(...await bot.repliesToOwn({ posts: OWN_POSTS_WATCHED }).catch(() => []));
  if (!found.length) return;

  const ledger = mentionLedger();
  const known = new Set(ledger.seen);
  const first = !ledger.seen.length;
  const unseen = found.filter((t) => t.id && !known.has(t.id));
  for (const t of unseen) known.add(t.id);
  ledger.seen = [...known].slice(-500);
  ledger.newest = found.map((t) => t.id).sort().pop() || ledger.newest;
  try { writeJson(MENTIONS_FILE, ledger); } catch { /* counted again next time */ }
  if (first) {
    // The first look only writes down what is already there: it does not answer a backlog all at once.
    console.log(`${TAG} ${unseen.length} thing(s) said to it already; they are noted, not answered.`);
    return;
  }

  let done = 0;
  for (const t of unseen.sort((a, b) => (a.at || 0) - (b.at || 0))) {
    if (done >= MENTIONS_PER_PASS || !mentionAllowed()) break;
    if (SYSTEM_CHATS.includes(String(t.handle || "").toLowerCase())) continue;
    if (SKIP_STRANGERS && !t.text.toLowerCase().includes(String(HANDLE).toLowerCase())
        && !(t.replyTo || []).includes(HANDLE)) continue;
    const chatId = chatIdFor(t.handle);
    if (!chatId) continue;
    const id = randomUUID();
    core.handOver({
      id, kind: "comment",
      user_id: chatId, user_name: `@${t.handle}`,
      channel_id: `mention_${t.id}`,
      content: t.text.slice(0, 2000),
      video: t.url,
      comment: { username: t.handle, text: t.text.slice(0, 2000) },
    });
    pending.set(id, { chatId, name: `@${t.handle}`, ts: Date.now() });
    done++;
  }
  if (done) console.log(`${TAG} ${done} thing(s) said to it, being answered.`);
}

// ── Message requests, follows, what the people it talks to post ──────────────

let requestsDueAt = 0;
let lastRequestsLook = 0;
async function maybeAcceptRequests() {
  if (!ACCEPT_REQUESTS || Date.now() - lastRequestsLook < 5 * 60 * 1000) return;
  lastRequestsLook = Date.now();
  const waiting = await bot.messageRequests().catch(() => []);
  if (!waiting.length) { requestsDueAt = 0; return; }
  if (!requestsDueAt) {
    const wait = (ACCEPT_DELAY_MIN + Math.random() * Math.max(0, ACCEPT_DELAY_MAX - ACCEPT_DELAY_MIN)) * 1000;
    requestsDueAt = Date.now() + wait;
    console.log(`${TAG} ${waiting.length} message request(s) waiting, accepting in ${Math.round(wait / 60000)} min.`);
    return;
  }
  if (Date.now() < requestsDueAt) return;
  requestsDueAt = 0;
  const one = waiting[0];
  const r = await bot.answerRequest(one.id, true).catch(() => ({ ok: false }));
  if (r.ok) console.log(`${TAG} Took the message request from ${one.name || one.username}.`);
  await bot.openInbox().catch(() => {});
}

let followDueAt = 0;
async function maybeFollowBack() {
  if (!FOLLOW_BACK || Date.now() < followDueAt || !budget.allowed("follows")) return;
  followDueAt = Date.now() + (45 + Math.random() * 45) * 60 * 1000;
  const them = await bot.followers({ max: 20 }).catch(() => []);
  const back = them.filter((p) => !p.following).slice(0, 2);
  for (const p of back) {
    if (!budget.allowed("follows")) break;
    const r = await bot.follow(p.handle).catch(() => ({ ok: false }));
    if (r.ok && !r.already) {
      budget.spend("follows");
      console.log(`${TAG} Followed @${p.handle} back.`);
    }
    await delay(4000 + Math.random() * 8000);
  }
  await bot.openInbox().catch(() => {});
}

let theirPostsDueAt = 0;
async function maybeTheirPosts() {
  if (!WATCH || !THEIR_POSTS || Date.now() < theirPostsDueAt) return;
  theirPostsDueAt = Date.now() + (20 + Math.random() * 20) * 60 * 1000;
  const all = contacts();
  // One person a pass, the one looked at longest ago.
  const who = Object.entries(all)
    .filter(([id]) => id.startsWith("x_"))
    .sort((a, b) => (a[1].posts_at || 0) - (b[1].posts_at || 0))[0];
  if (!who) return;
  const [chatId, info] = who;
  if (Date.now() / 1000 - (info.posts_at || 0) < 6 * 3600) return;
  const handle = handleOf(chatId);
  if (!handle) return;
  const page = await bot.outPage();
  // Their profile read as a thread is read: the same posts, off the same page.
  const theirs = await bot.readThread(`https://x.com/${handle}`, { page, scrolls: 0 }).catch(() => []);
  const newest = (theirs || []).find((t) => t.handle === handle && !t.reply);
  const all2 = contacts();
  all2[chatId] = { ...(all2[chatId] || {}), posts_at: Math.round(Date.now() / 1000),
                   ...(newest ? { newest: newest.url } : {}) };
  try { writeJson(CONTACTS_FILE, all2); } catch { /* next time */ }
  if (newest && newest.url !== info.newest) {
    core.tellPython({ kind: "posts", chat: chatId, newest: newest.url, fresh: true });
    if (LIKE_THEIRS && budget.allowed("likes")) {
      const r = await bot.likePost(newest.url, { readMs: 2500 + Math.random() * 4000, dryRun: DRY_RUN })
        .catch(() => ({ ok: false }));
      if (r.ok && !r.already && !r.dry) { budget.spend("likes"); console.log(`${TAG} Liked @${handle}'s post.`); }
    }
    if (REPOST_THEIRS && budget.allowed("reposts")) {
      const r = await bot.repost(newest.url, { dryRun: DRY_RUN }).catch(() => ({ ok: false }));
      if (r.ok && !r.already && !r.dry) { budget.spend("reposts"); console.log(`${TAG} Reposted @${handle}.`); }
    }
  }
  await bot.openInbox().catch(() => {});
}

// ── What the panel asks for ──────────────────────────────────────────────────

async function panelRequest(req) {
  const op = String(req.op || "");
  const chat = String(req.chat || "");

  if (op === "history" || op === "send" || op === "react") {
    if (!CHAT_ID.test(chat)) return { ok: false, reason: "that is not an X conversation" };
    if (!(await bot.openChat(chat))) return { ok: false, reason: "could not open their conversation" };
  }

  if (op === "history") {
    const c = await bot.readChat({ scrollUps: 2 });
    return { ok: true, messages: keyedChat(chat, c.messages) };
  }
  if (op === "send") {
    for (const file of (req.images || []).slice(0, 4)) {
      if (fs.existsSync(file)) await bot.sendImage(file, { dryRun: DRY_RUN }).catch(() => {});
    }
    const out = req.text ? await bot.sendText(req.text, { dryRun: DRY_RUN }) : { ok: true };
    if (!out.ok) return out;
    core.recordSend();
    const c = await bot.readChat();
    const msgs = keyedChat(chat, c.messages);
    const mine = msgs.filter((m) => m.mine);
    return { ok: true, messages: msgs, sent: mine.length ? mine[mine.length - 1].key : "" };
  }
  if (op === "react") {
    const c = await bot.readChat();
    const msgs = keyedChat(chat, c.messages);
    const want = msgs.find((m) => m.key === req.key);
    if (!want || !Number.isInteger(want.idx)) return { ok: false, reason: "that message is not on the page" };
    const out = await bot.react(want.idx, String(req.emoji || ""));
    if (!out.ok) return out;
    const after = await bot.readChat();
    const found = keyedChat(chat, after.messages).find((m) => m.key === req.key);
    return { ok: true, reactions: found ? found.reactions : [] };
  }
  if (op === "friends") {
    const waiting = await bot.messageRequests();
    return { ok: true, requests: waiting };
  }
  if (op === "friend") {
    return bot.answerRequest(String(req.name || ""), !!req.accept);
  }
  if (op === "add_friend" || op === "follow") {
    const r = await bot.follow(String(req.username || ""));
    if (r.ok && !r.already) budget.spend("follows");
    return r;
  }
  if (op === "posts") {
    const handle = handleOf(chat) || cleanHandle(req.username || "");
    if (!handle) return { ok: false, reason: "nobody to look at" };
    const theirs = await bot.readThread(`https://x.com/${handle}`, { scrolls: 1 });
    return { ok: true, posts: (theirs || []).filter((t) => t.handle === handle).slice(0, 12) };
  }
  if (op === "thread") {
    const posts = await bot.readThread(String(req.url || ""), { scrolls: 2 });
    return { ok: true, posts: posts || [] };
  }
  if (op === "mentions") {
    const found = await bot.mentions({ scrolls: 2 });
    return { ok: true, mentions: (found || []).map((t) => ({ id: t.id, url: t.url, handle: t.handle,
                                                             text: t.text, at: t.at })) };
  }
  if (op === "action") {
    const which = String(req.action || "");
    if (which === "quote") {
      const out = await bot.post(String(req.text || "").slice(0, POST_MAX_CHARS) + `\n${req.url}`,
                                 { dryRun: DRY_RUN });
      if (out.ok && !out.dry) budget.spend("posts");
      return out;
    }
    const out = await bot.press(String(req.url || ""), which, { dryRun: DRY_RUN });
    if (out.ok && !out.already && !out.dry) {
      if (which === "like") budget.spend("likes");
      if (which === "repost") budget.spend("reposts");
    }
    return out;
  }
  if (op === "post") {
    const out = await bot.post(String(req.text || "").slice(0, POST_MAX_CHARS),
                               { images: req.images || [], thread: req.thread || [], dryRun: DRY_RUN });
    if (out.ok && !out.dry) { budget.spend("posts"); postSent(); }
    return out;
  }
  if (op === "out") {
    return { ok: true, busy: false,
             left: { likes: budget.left("likes"), reposts: budget.left("reposts"), follows: budget.left("follows"),
                     replies: budget.left("replies"), posts: budget.left("posts") },
             used: { likes: budget.used("likes"), reposts: budget.used("reposts"), follows: budget.used("follows"),
                     replies: budget.used("replies"), posts: budget.used("posts") } };
  }
  if (op === "fetch") {
    const got = await bot.captureMedia(String(req.url || ""), "x_fetch");
    return got ? { ok: true, ...got } : { ok: false, reason: "nothing to take from that link" };
  }
  if (op === "code") {
    codeWaiting = String(req.code || "");
    return { ok: true };
  }
  return { ok: false, reason: `unknown request ${op}` };
}

async function processPanel() {
  while (core.panelQueue.length) {
    const req = core.panelQueue.shift();
    let out;
    try { out = await panelRequest(req); } catch (e) { out = { ok: false, reason: (e && e.message) || String(e) }; }
    core.tellPython({ kind: "panel_result", id: req.id, ...out });
  }
}

// ── Signing in, and the checks X puts up ─────────────────────────────────────

let codeWaiting = "";

/** Wait for a code typed in the panel, up to five minutes. */
async function askForCode() {
  codeWaiting = "";
  core.setState("needs-you", "X sent a code. Type it on the Accounts page.");
  core.tellPython({ kind: "attention", what: "code" });
  for (let i = 0; i < 150; i++) {
    await core.sleepOrPoke(2000);
    await processPanel().catch(() => {});
    if (codeWaiting) { const c = codeWaiting; codeWaiting = ""; return c; }
  }
  return "";
}

async function signInNow() {
  signInState = "";
  core.setState("logging-in", "signing in to X");
  const out = await bot.signIn({
    password: PASSWORD, totpKey: TOTP_KEY, email: EMAIL,
    onState: (state, detail) => { signInState = state; core.setState(state === "signing-in" ? "logging-in" : state, detail); },
    getCode: askForCode,
    onPerson: async (what) => {
      core.tellPython({ kind: "attention", what });
      if (HIDDEN) await bot.showWindow();
      core.setState("needs-you", "X put up a check. Solve it in the window.");
      for (let i = 0; i < 90; i++) {
        await core.sleepOrPoke(2000);
        if (!(await bot.captchaShown())) { if (HIDDEN) await bot.hideWindow(); return true; }
      }
      if (HIDDEN) await bot.hideWindow();
      return false;
    },
  }).catch((e) => ({ ok: false, needs: true, reason: e.message }));
  if (out.ok) {
    core.setState("ready");
    return true;
  }
  console.error(`${TAG} ${out.reason}`);
  core.setState("logged-out", out.reason);
  if (out.needs) {
    // A person has to. Started again it would sign in over and over, and that is how X locks an account.
    await delay(2000);
    process.exit(4);
  }
  return false;
}

async function checkCaptcha() {
  if (!(await bot.captchaShown())) return;
  core.tellPython({ kind: "attention", what: "captcha" });
  core.setState("needs-you", "X put up a check. Solve it in the window.");
  if (HIDDEN) await bot.showWindow();
  for (let i = 0; i < 150; i++) {
    await core.sleepOrPoke(2000);
    if (!(await bot.captchaShown())) break;
  }
  if (HIDDEN) await bot.hideWindow();
  core.setState("ready");
}

/** Signed out for good (suspended, locked): wait rather than hammer at it. */
async function waitSignedOut() {
  core.setState("logged-out", signInState === "locked" ? "X has locked this account" : "signed out of X");
  await core.sleepOrPoke(5 * 60 * 1000);
}

// ── Is the page still the page ───────────────────────────────────────────────

let healthSaid = false;
async function reportHealth() {
  const h = await bot.selectorHealth().catch(() => null);
  if (!h) return;
  if (!h.missing.length) {
    if (healthSaid) core.setState("ready");
    healthSaid = false;
    return;
  }
  // Give it 25 seconds before complaining: a list still drawing looks exactly like a page that changed.
  await delay(25000);
  const again = await bot.selectorHealth().catch(() => null);
  if (!again || !again.missing.length) return;
  healthSaid = true;
  const said = `X's page has changed: ${again.missing.join(", ")} not found.`;
  console.warn(`${TAG} ${said}`);
  core.setState("ready", said);
}

/** Tell the loop as soon as the list changes, rather than waiting out the poll. */
async function watchList() {
  try {
    await bot.page.exposeFunction("__llmPoke", () => { listChanged = true; core.wakeNow(); });
  } catch { /* already there */ }
  await bot.page.evaluate((sel) => {
    if (window.__llmWatching) return;
    window.__llmWatching = true;
    let last = 0;
    const fire = () => {
      // Hard throttle: a virtualized list mutates as fast as it scrolls, and without this the poll means nothing.
      const now = Date.now();
      if (now - last < 2000) return;
      last = now;
      try { window.__llmPoke(); } catch { /* gone */ }
    };
    const find = () => {
      for (const s of sel.dmScroller) { const el = document.querySelector(s); if (el) return el; }
      return document.querySelector('[data-testid="primaryColumn"]');
    };
    const target = find();
    if (!target) return;
    new MutationObserver(fire).observe(target, { childList: true, subtree: true });
  }, SEL).catch(() => {});
}

// ── The loop ─────────────────────────────────────────────────────────────────

/** The wait between looks, spent sending what is ready and answering the panel. */
async function drainWindow(ms) {
  const started = Date.now();
  const until = started + ms;
  listChanged = false;
  while (Date.now() < until) {
    await core.sleepOrPoke(2000);
    try { await processPanel(); } catch { /* answered inside */ }
    try { await drainResponses(); } catch (e) { console.warn(`${TAG} Send error: ${e.message}`); }
    try { await drainOwnPosts(); } catch { /* next time */ }
    if (listChanged && Date.now() - started > 4000) break;
  }
}

async function main() {
  if (!HANDLE) {
    console.error(`${TAG} No X account ${ACCOUNT}: add one on the Accounts page.`);
    process.exit(1);
  }
  if (!fs.existsSync(PROFILE_DIR)) {
    // Its browser profile IS its login: a person made it by signing in, in a window. A password is optional and
    // only lets it sign itself back in later; without the profile there is nothing to run.
    console.error(`${TAG} X account ${ACCOUNT} (@${HANDLE}) has not been signed in. `
                  + "Sign it in on the Accounts page.");
    core.ensureFiles();
    core.setState("needs-you", "It has not been signed in yet. Sign it in on the Accounts page.");
    process.exit(4);               // a person has to: not started again by itself
  }

  bot = new XBot({ account: ACCOUNT, handle: HANDLE, dataDir: DATA_DIR, locale: LOCALE, timezone: TIMEZONE,
                   tag: TAG });
  core.setState("starting", "launching the browser");
  console.log(`${TAG} Starting @${HANDLE} (account #${ACCOUNT})${HIDDEN ? ", window hidden" : ""}`
              + `${DRY_RUN ? ", DRY RUN: nothing is sent" : ""}.`);
  await bot.launch({ profileDir: PROFILE_DIR, hidden: HIDDEN, proxy: core.text("PROXY") });

  core.ensureFiles();
  core.connectWake();
  core.setState("starting", "opening its messages");
  for (let attempt = 1; ; attempt++) {
    try {
      await bot.openInbox();
      if (!(await bot.isLogged()) && !(await signInNow())) {
        if (signInState === "suspended" || signInState === "locked") {
          await waitSignedOut();
          attempt = 0;
          continue;
        }
        await delay(60000);
        process.exit(3);
      }
      await bot.openInbox();
      await checkCaptcha();
      await recordIdentity();
      break;
    } catch (e) {
      if (attempt >= 4) throw e;
      console.warn(`${TAG} Opening X went wrong (${e.message}); trying again.`);
      await bot.ensure().catch(() => {});
      await delay(2500 * attempt);
    }
  }
  await watchList();
  core.setState("ready");
  await reportHealth();
  console.log(`${TAG} Ready. ${Math.round(core.minGap / 1000)} to ${Math.round(core.maxGap / 1000)}s between `
              + `sends, at most ${core.perHour} an hour${core.quiet ? `, quiet ${core.quiet}` : ""}.`);

  let reloadDue = Date.now() + RELOAD_MS * (0.75 + Math.random() * 0.5);
  let listFailures = 0;
  while (true) {
    core.heartbeatState();
    await siteWatch.tick().catch(() => {});
    try {
      if ((await bot.ensure()) !== "ok") {
        await bot.openInbox();
        if (!(await bot.isLogged()) && !(await signInNow())) { await waitSignedOut(); continue; }
        await watchList();
        core.setState("ready");
      }
      if (Date.now() - identityAt > 4 * 3600 * 1000) await recordIdentity().catch(() => {});
      await processPanel();
      await checkCaptcha();
      if (RELOAD_MS > 0 && Date.now() > reloadDue && !pending.size) {
        reloadDue = Date.now() + RELOAD_MS * (0.75 + Math.random() * 0.5);
        await bot.goto("https://x.com/messages", bot.page);
        if (!(await bot.isLogged()) && !(await signInNow())) { await waitSignedOut(); continue; }
        await watchList();
        await reportHealth();
      }
      await drainResponses();
      await processOutgoing();

      let rows;
      try {
        await bot.openInbox();
        rows = await bot.listThreads();
        listFailures = 0;
      } catch (e) {
        if (++listFailures >= 3) {
          console.warn(`${TAG} Its messages would not read three times over (${e.message}); reloading.`);
          listFailures = 0;
          await bot.goto("https://x.com/messages", bot.page).catch(() => {});
          await reportHealth();
        }
        await drainWindow(core.jitteredPoll());
        continue;
      }
      for (const r of rows) {
        const id = idOfRow(r);
        if (!id) continue;
        await remember(id, r.name, r.avatar, r.conversation ? { conversation: r.conversation } : null);
        if (r.typing) core.tellPython({ kind: "typing", chat: id });
      }
      const targets = rows
        .filter((r) => r.unread && !SYSTEM_CHATS.includes(String(r.name || "").toLowerCase().trim()))
        .slice(0, MAX_RECIPIENTS);
      if (targets.length) await delay(500 + Math.random() * 2500);
      for (const row of targets) {
        await readChat(row);
        await processPanel();
        await delay(700 + Math.random() * 1200);
      }
      await maybeAcceptRequests();
      await maybeMentions();
      await maybeFollowBack();
      await maybeTheirPosts();
    } catch (e) {
      console.error(`${TAG} Loop error: ${e.message}`);
    }
    await drainWindow(core.jitteredPoll());
  }
}

main().catch((err) => {
  console.error(`${TAG} Fatal error:`, err);
  process.exit(1);
});
