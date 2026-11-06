/**
 * The Reddit account: its chats, its inbox, the comments it writes, its own posts, and the upvotes, saves, joins
 * and follows it does out there. Laid out section for section like x_runner.js, so a change to one can be read
 * against the other.
 *
 * Reddit minds an automated account as much as X does and does something quieter about it: it hides the account
 * rather than locking it, and says nothing. So everything public is off until it is switched on, every public
 * thing it does is capped for the day, it only ever takes part in the subreddits it was told to, and after it
 * says anything in public it checks that anybody else can see it (REDDIT_CHECK_SHADOWBAN). The moment that check
 * says no, everything public stops and the card says so.
 *
 * Its login is its browser profile, which a person made by signing in themselves in a window. Without that
 * profile there is nothing to run: it exits 4 and waits for a person, exactly as a refused login does.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import RedditBot, { SEL, chatIdFor, userOf, cleanUser, CHAT_ID, postUrl, readPostsInPage }
  from "./redditbot.js";
import { createCore, createBudget, keyed, readJson, writeJson, delay } from "./runner_core.js";
import { SiteWatch, applySiteFixes } from "./sitewatch.js";
import { patchConsole } from "./log.js";

patchConsole();

const TAG = "[Reddit]";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.REDDIT_DATA_DIR || process.env.SNAP_DATA_DIR || path.resolve(HERE, "../../../");
const ACCOUNT = parseInt(process.env.REDDIT_ACCOUNT_INDEX || "1", 10) || 1;

const envFor = (name) => process.env[`${name}_${ACCOUNT}`] ?? (ACCOUNT === 1 ? process.env[name] : "") ?? "";
const USERNAME = cleanUser(envFor("REDDIT_USERNAME"));
const PASSWORD = String(envFor("REDDIT_PASSWORD") || "");
const TOTP_KEY = String(envFor("REDDIT_TOTP") || "").replace(/[\s-]/g, "");

const PROFILE_DIR = path.join(DATA_DIR, "config", `reddit-${USERNAME}-profile`);
const IDENTITY_FILE = path.join(DATA_DIR, "config", `identity_reddit_${ACCOUNT}.json`);
const PEOPLE_DIR = path.join(DATA_DIR, "cache", "reddit_people");
const CONTACTS_FILE = path.join(PEOPLE_DIR, `contacts_${ACCOUNT}.json`);
const INBOX_FILE = path.join(PEOPLE_DIR, `inbox_${ACCOUNT}.json`);
const REFUSED_FILE = path.join(PEOPLE_DIR, `refused_${ACCOUNT}.json`);
const SYSTEM_CHATS = ["reddit", "reddit support", "redditcareresources", "automoderator", "u/reddit"];
const PICTURE_HOSTS = /^(i|preview|external-preview|a|styles|b)\.redd\.it$|redditmedia\.com$|redditstatic\.com$/;

const core = createCore({
  prefix: "reddit", env: "REDDIT", account: ACCOUNT, dataDir: DATA_DIR, tag: TAG,
  // What it runs at when the settings file has no reddit: section - one written before this platform existed. The
  // same numbers as resources/config.yaml, so a fresh install and an old one behave alike.
  defaults: {
    POLL_INTERVAL_MS: 25000, MAX_RECIPIENTS: 8, RESPONSE_TIMEOUT_MS: 90000,
    MIN_SEND_GAP_MS: 30000, MAX_SEND_GAP_MS: 90000, MAX_SENDS_PER_HOUR: 12,
    RELOAD_INTERVAL_MS: 2700000, ACCEPT_CHAT_INVITES: false, SUBREDDITS: "", CHECK_SHADOWBAN: true,
    INBOX: true, INBOX_REPLIES: true, INBOX_MENTIONS: true, INBOX_PER_HOUR: 3, INBOX_PER_PASS: 3,
    INBOX_SCROLLS: 3, SKIP_STRANGERS: true,
    COMMENTS: false, COMMENTS_PER_DAY: 6, COMMENT_MAX_CHARS: 1200, COMMENT_FRESH_ONLY: true,
    COMMENT_MIN_SCORE: 5, SKIP_LOCKED: true,
    POSTING: false, POST_WHERE: "profile", POSTS_PER_DAY: 1, POST_MIN_GAP_MIN: 240, POST_MAX_CHARS: 1500,
    POST_WITH_IMAGE: false, POST_FLAIR: true,
    UPVOTE_SENT: false, UPVOTE_THEIRS: false, SAVE: false, JOIN_SUBS: false, FOLLOW_USERS: false,
    UPVOTES_PER_DAY: 15, JOINS_PER_DAY: 2, FOLLOWS_PER_DAY: 3, REPLIES_PER_DAY: 10,
    WATCH: true, THEIR_POSTS: true, THREADS: true, LINKS: true,
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
const ACCEPT_INVITES = core.flag("ACCEPT_CHAT_INVITES", false);
const ACCEPT_DELAY_MIN = core.num("ACCEPT_DELAY_MIN", 120);
const ACCEPT_DELAY_MAX = core.num("ACCEPT_DELAY_MAX", 600);
const CHECK_SHADOWBAN = core.flag("CHECK_SHADOWBAN", true);
const INBOX_ON = core.flag("INBOX", true);
const INBOX_REPLIES = core.flag("INBOX_REPLIES", true);
const INBOX_MENTIONS = core.flag("INBOX_MENTIONS", true);
const INBOX_PER_HOUR = core.num("INBOX_PER_HOUR", 3);
const INBOX_PER_PASS = core.num("INBOX_PER_PASS", 3);
const INBOX_SCROLLS = core.num("INBOX_SCROLLS", 3);
const SKIP_STRANGERS = core.flag("SKIP_STRANGERS", true);
const COMMENTS_ON = core.flag("COMMENTS", false);
const COMMENT_MAX_CHARS = core.num("COMMENT_MAX_CHARS", 1200);
const COMMENT_FRESH_ONLY = core.flag("COMMENT_FRESH_ONLY", true);
const COMMENT_MIN_SCORE = core.num("COMMENT_MIN_SCORE", 5);
const SKIP_LOCKED = core.flag("SKIP_LOCKED", true);
const POSTING = core.flag("POSTING", false);
const POST_WHERE = core.text("POST_WHERE", "profile");
const POST_MIN_GAP_MIN = core.num("POST_MIN_GAP_MIN", 240);
const POST_MAX_CHARS = core.num("POST_MAX_CHARS", 1500);
const POST_FLAIR = core.flag("POST_FLAIR", true);
const UPVOTE_SENT = core.flag("UPVOTE_SENT", false);
const UPVOTE_THEIRS = core.flag("UPVOTE_THEIRS", false);
const SAVE_LIKED = core.flag("SAVE", false);
const JOIN_SUBS = core.flag("JOIN_SUBS", false);
const FOLLOW_USERS = core.flag("FOLLOW_USERS", false);
const WATCH = core.flag("WATCH", true);
const THEIR_POSTS = core.flag("THEIR_POSTS", true);

/** The subreddits it may take part in at all: the one thing that decides where it is allowed to open its mouth. */
const SUBREDDITS = core.text("SUBREDDITS", "")
  .replace(/[;\n]/g, ",").split(",")
  .map((s) => s.trim().replace(/^\/+/, "").replace(/^r\//i, "").replace(/\/+$/, "").toLowerCase())
  .filter((s) => s && s.length <= 21);

/** Its own profile always takes a post; a named subreddit only if it is on the list. */
function allowedIn(sub) {
  const name = String(sub || "").replace(/^r\//i, "").toLowerCase();
  if (!name || name.startsWith("u_")) return true;
  return SUBREDDITS.includes(name);
}

fs.mkdirSync(PEOPLE_DIR, { recursive: true });
const budget = createBudget(path.join(PEOPLE_DIR, `budget_${ACCOUNT}.json`), {
  upvotes: core.num("UPVOTES_PER_DAY", 15),
  joins: core.num("JOINS_PER_DAY", 2),
  follows: core.num("FOLLOWS_PER_DAY", 3),
  // Public answers: the replies in its inbox and the comments nobody asked for, together.
  replies: core.num("REPLIES_PER_DAY", 10),
  comments: core.num("COMMENTS_PER_DAY", 6),
  posts: core.num("POSTS_PER_DAY", 1),
});

// The few things that should always be on the pages it sits on, and a fix for any of its selectors without a new build
// (sitewatch.js). Only ever looked for on tabs it already has open.
applySiteFixes(SEL, "reddit", DATA_DIR, (m) => console.log(`${TAG} ${m}`));
const siteWatch = new SiteWatch({
  core: [
    { name: "the page itself", sel: SEL.appShell, on: /reddit\.com\// },
    { name: "the list of chats", sel: SEL.chatRoomList, on: /(?:chat\.reddit\.com|reddit\.com\/chat)/ },
  ],
  pages: () => bot?.browser?.pages(),
  report: (missing) => core.keepSaying(missing.length ? { site: { missing } } : {}),
});

let bot = null;
let pending = new Map();        // what was handed over and is waiting on an answer
let listChanged = false;
let signInState = "";
let identityAt = 0;
let hiddenSince = 0;            // when the shadowban check last said nobody else can see it
let lastPostAt = 0;
let inboxTimes = [];

// ── Who it has talked to ────────────────────────────────────────────────────

function contacts() {
  return readJson(CONTACTS_FILE, {});
}

function remember(chatId, name, avatar, extra) {
  if (!chatId) return;
  const all = contacts();
  const was = all[chatId] || {};
  const now = { ...was };
  if (name && name !== chatId) now.name = String(name).slice(0, 80);
  if (avatar) now.avatar = String(avatar).slice(0, 500);
  if (extra && typeof extra === "object") Object.assign(now, extra);
  now.seen = Math.floor(Date.now() / 1000);
  all[chatId] = now;
  writeJson(CONTACTS_FILE, all);
}

/** A person's picture, kept beside their name so the panel has one to draw. */
async function savePicture(chatId, url) {
  if (!url || !chatId) return;
  let host = "";
  try { host = new URL(url).hostname; } catch { return; }
  if (!PICTURE_HOSTS.test(host)) return;
  const dir = path.join(PEOPLE_DIR, `pictures_${ACCOUNT}`);
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${chatId.replace(/[^A-Za-z0-9_-]/g, "_")}.jpg`);
  if (fs.existsSync(file) && Date.now() - fs.statSync(file).mtimeMs < 7 * 86400000) return;
  const saved = await bot.captureMedia(url).catch(() => "");
  if (saved) {
    try { fs.renameSync(saved, file); } catch { /* the old one will do */ }
  }
}

/** Who this account is, for its card: its name and its picture. */
async function recordIdentity() {
  identityAt = Date.now();
  const info = await bot.profileInfo(USERNAME).catch(() => null);
  if (!info) return;
  writeJson(IDENTITY_FILE, {
    username: USERNAME, name: `u/${USERNAME}`, karma: info.karma || 0, years: info.years || 0,
    at: Math.floor(Date.now() / 1000),
  });
}

// ── Reading a chat ──────────────────────────────────────────────────────────

function describe(m) {
  if (m.text) return m.text;
  if (m.kind === "photo") return "[photo]";
  if (m.kind === "video") return "[video]";
  if (m.kind === "link") return `[link: ${(m.links || [])[0] || ""}]`;
  return "[message]";
}

function keyedChat(chatId, messages) {
  // keyed() is given the whole conversation at once: it counts the same words said twice in a day, which it can
  // only do by seeing all of them.
  return keyed(chatId, messages, { monthFirst: MONTH_FIRST, prefix: "r" });
}

/** The whole of a chat, for the panel's log. */
function share(chatId, name, messages) {
  core.tellPython({ kind: "transcript", chat: chatId, name: name || chatId,
                    messages: keyedChat(chatId, messages).slice(-120) });
}

function idOfRow(r) {
  return r.chat || "";
}

/** Read one chat and hand whatever is new to the brain. */
async function readChat(row) {
  const chatId = idOfRow(row);
  if (!chatId) return;
  const got = await bot.readChat(chatId, { scrollUps: 2 });
  if (!got.ok) return;
  const messages = got.messages || [];
  share(chatId, row.name, messages);
  const theirs = messages.filter((m) => !m.mine);
  const last = theirs[theirs.length - 1];
  if (!last) return;
  const key = `${last.idx}|${describe(last).slice(0, 80)}`;
  if (!core.isNew(chatId, key)) return;
  const id = `${chatId}:${Date.now()}`;
  pending.set(id, { at: Date.now(), chat: chatId });
  core.handOver({
    id,
    user_id: chatId,
    user_name: row.name || `u/${userOf(chatId)}`,
    channel_id: chatId,
    content: describe(last),
    group: row.group || undefined,
    photo: true,
  });
  for (const m of messages.slice(-4)) {
    for (const bit of m.media || []) {
      if (bit.kind === "photo") await savePicture(chatId, bit.url).catch(() => {});
    }
  }
}

// ── Sending what the bridge wrote ───────────────────────────────────────────

/** Answers that go at their own pace, not the chat governor's: they are handled by drainOwnWork. */
const OWN_PACE = new Set(["post", "comment"]);

async function drainResponses() {
  const now = Date.now();
  for (const [id, info] of [...pending]) if (now - info.at > RESPONSE_TTL_MS) pending.delete(id);
  const answers = core.responses();
  for (const id of Object.keys(answers)) {
    const val = answers[id];
    const kind = (val && typeof val === "object" && val.kind) || "";
    if (OWN_PACE.has(kind)) continue;
    // "comment" is an answer in its inbox; "post_comment" is one it decided to write itself. Both are a reply
    // under something, and the bridge hands the permalink back as `video`, as it does for X and TikTok.
    const inPublic = kind === "comment" || kind === "post_comment";
    if (inPublic ? !replyAllowed() : !core.sendAllowed()) break;
    const taken = core.take(id);
    if (taken === null) continue;
    const text = typeof taken === "string" ? taken : String(taken.text || "");
    const chatId = (taken && taken.chat) || (pending.get(id) || {}).chat || "";
    if (!text.trim()) { pending.delete(id); continue; }
    let out;
    if (inPublic) {
      out = await bot.replyTo(String(taken.video || taken.url || ""), text.slice(0, COMMENT_MAX_CHARS));
    } else {
      if (!CHAT_ID.test(chatId)) { pending.delete(id); continue; }
      // It reads it again before answering.
      await delay(800 + Math.random() * 2200);
      out = await bot.sendText(chatId, text);
    }
    if (out && out.ok) {
      pending.delete(id);
      if (inPublic) {
        budget.spend(kind === "post_comment" ? "comments" : "replies");
        replySent();
        await afterPublic(out.url);
      }
      else {
        core.recordSend();
        const again = await bot.readChat(chatId, { scrollUps: 0 }).catch(() => null);
        if (again && again.ok) share(chatId, (contacts()[chatId] || {}).name, again.messages || []);
      }
      continue;
    }
    // Three ways a send can fail, and each is answered differently.
    const why = String((out && out.reason) || "");
    const attempts = (typeof taken === "object" && taken._attempts) || 0;
    if (/wait|rate ?limit|too much|too fast|try again/i.test(why)) {
      core.putBack(id, typeof taken === "object" ? { ...taken, _attempts: attempts + 1 } : { text: taken, _attempts: 1 });
      core.recordSend();              // burn a slot: it is Reddit asking for room, not a lost message
      core.setState("waiting", why);
      break;
    }
    if (attempts >= 4 || /banned|suspended|not allowed|locked|archived|removed/i.test(why)) {
      console.warn(`${TAG} Giving up on one answer: ${why}`);
      pending.delete(id);
      continue;
    }
    core.putBack(id, typeof taken === "object" ? { ...taken, _attempts: attempts + 1 } : { text: taken, _attempts: 1 });
  }
}

/** Messages the bridge sends on its own: a Reply from the panel, a nudge, a picture. */
async function processOutgoing() {
  const queue = readJson(core.files.outgoing, []);
  if (!queue.length) return;
  const item = queue[0];
  // The tail is written back first: a crash drops one, never loops it.
  writeJson(core.files.outgoing, queue.slice(1));
  const chatId = String(item.chat || "");
  if (!CHAT_ID.test(chatId)) return;
  if (item.image) await bot.sendImage(chatId, item.image).catch(() => {});
  if (item.message) {
    await delay(core.typingTime(item.message) * 0.25);
    const out = await bot.sendText(chatId, item.message);
    if (out && out.ok) core.recordSend();
  }
  const again = await bot.readChat(chatId, { scrollUps: 0 }).catch(() => null);
  if (again && again.ok) share(chatId, (contacts()[chatId] || {}).name, again.messages || []);
}

/** Posts and comments, which go at their own pace rather than the chat governor's. */
async function drainOwnWork() {
  const answers = core.responses();
  for (const id of Object.keys(answers)) {
    const val = answers[id];
    const kind = (val && typeof val === "object" && val.kind) || "";
    if (!OWN_PACE.has(kind)) continue;
    if (kind === "post" && !postAllowed()) continue;
    if (kind === "comment" && !budget.allowed("comments")) continue;
    const taken = core.take(id);
    if (taken === null) continue;
    if (kind === "post") {
      // The bridge writes one piece of text for every platform. Reddit wants a title and a body, and the first
      // line is the title - the same split redditsocial.clean_post makes on the Python side.
      const said = String(taken.title ? `${taken.title}\n${taken.text || ""}` : taken.text || "").trim();
      const lines = said.split("\n").map((l) => l.trim()).filter(Boolean);
      const title = (lines[0] || "").replace(/^#+\s*/, "").replace(/^(title|post):\s*/i, "").slice(0, 300);
      const body = lines.slice(1).join("\n").slice(0, POST_MAX_CHARS);
      if (!title) continue;
      const where = POST_WHERE === "subreddits" ? pickSubreddit() : "";
      if (POST_WHERE === "subreddits" && !where) continue;
      const out = await bot.post({ title, text: body, where, image: taken.image || "",
                                   flair: POST_FLAIR, dryRun: DRY_RUN });
      if (out && out.ok) {
        budget.spend("posts");
        lastPostAt = Date.now();
        console.log(`${TAG} Posted${where ? ` to r/${where}` : " to its own profile"}${out.dry ? " (dry run)" : ""}.`);
        core.tellPython({ kind: "posts", chat: "", newest: out.url || "", fresh: true });
      } else {
        noteRefused(where, (out && out.reason) || "");
      }
    } else {
      const url = String(taken.url || "");
      const text = String(taken.text || "").slice(0, COMMENT_MAX_CHARS);
      if (!url || !text.trim()) continue;
      const out = await bot.replyTo(url, text);
      if (out && out.ok) {
        budget.spend("comments");
        await afterPublic(out.url || url);
      } else {
        noteRefused(subOf(url), (out && out.reason) || "");
      }
    }
  }
}

function subOf(url) {
  const m = String(url || "").match(/\/r\/([A-Za-z0-9_]{2,21})/);
  return m ? m[1].toLowerCase() : "";
}

/** A subreddit that refused it is remembered rather than tried again: that is how an account gets noticed. */
function noteRefused(sub, why) {
  if (!sub || !why) return;
  const all = readJson(REFUSED_FILE, {});
  all[sub] = { why: String(why).slice(0, 200), at: Math.floor(Date.now() / 1000) };
  writeJson(REFUSED_FILE, all);
  console.warn(`${TAG} r/${sub} would not take it: ${why}`);
}

function refused(sub) {
  const row = readJson(REFUSED_FILE, {})[String(sub || "").toLowerCase()];
  // A week is long enough for karma to have changed.
  return !!row && Date.now() / 1000 - (row.at || 0) < 7 * 86400;
}

function pickSubreddit() {
  const open = SUBREDDITS.filter((s) => !refused(s));
  return open.length ? open[Math.floor(Math.random() * open.length)] : "";
}

// ── What is said to it in public ────────────────────────────────────────────

function replyAllowed() {
  const now = Date.now();
  inboxTimes = inboxTimes.filter((t) => now - t < 3600000);
  return budget.allowed("replies") && inboxTimes.length < INBOX_PER_HOUR && !hiddenSince;
}

function replySent() {
  inboxTimes.push(Date.now());
}

function postAllowed() {
  if (!POSTING || hiddenSince) return false;
  if (!budget.allowed("posts")) return false;
  return Date.now() - lastPostAt >= POST_MIN_GAP_MIN * 60000;
}

/** The replies and u/ mentions it has not answered, handed over one at a time. */
async function maybeInbox() {
  if (!INBOX_ON || hiddenSince || !replyAllowed()) return;
  const rows = await bot.inbox({ scrolls: INBOX_SCROLLS }).catch(() => []);
  const seen = readJson(INBOX_FILE, {});
  let sent = 0;
  for (const row of rows) {
    if (sent >= INBOX_PER_PASS || !replyAllowed()) break;
    if (seen[row.id]) continue;
    const isMention = row.kind === "mention";
    if (isMention && !INBOX_MENTIONS) continue;
    if (!isMention && !INBOX_REPLIES) continue;
    if (!row.url || !row.author || row.author === USERNAME) continue;
    if (SYSTEM_CHATS.includes(row.author)) continue;
    if (SKIP_STRANGERS && isMention && !String(row.text || "").toLowerCase().includes(USERNAME)) continue;
    seen[row.id] = Math.floor(Date.now() / 1000);
    writeJson(INBOX_FILE, seen);
    const chatId = chatIdFor(row.author);
    const id = `inbox:${row.id}`;
    pending.set(id, { at: Date.now(), chat: chatId });
    core.handOver({
      id, kind: "comment",
      user_id: chatId, user_name: `u/${row.author}`,
      channel_id: `inbox_${row.id}`,
      content: String(row.text || "").slice(0, 2000),
      video: row.url,
      comment: { username: row.author, text: String(row.text || "").slice(0, 2000) },
      ...(isMention ? { mention: true } : {}),
    });
    sent += 1;
    await delay(600 + Math.random() * 1200);
  }
}

/** After anything public: is it still there for everybody else, or only for itself? */
async function afterPublic(url) {
  if (!CHECK_SHADOWBAN) return;
  await delay(4000 + Math.random() * 4000);
  const got = await bot.notHidden(url || "").catch(() => ({ hidden: false, checked: false }));
  if (got && got.hidden) {
    hiddenSince = Date.now();
    const why = got.why || "Nobody else can see what it says.";
    console.error(`${TAG} Reddit is hiding this account: ${why} Everything public has stopped.`);
    core.setState("needs-you", `Reddit is hiding this account. ${why}`);
    core.tellPython({ kind: "attention", what: "shadowbanned" });
  }
}

/** Chat invitations from people it does not know, after the same wait as Discord's friend requests. */
async function maybeInvites() {
  if (!ACCEPT_INVITES) return;
  const rooms = await bot.chatInvites().catch(() => []);
  for (const room of rooms.slice(0, 2)) {
    const waited = ACCEPT_DELAY_MIN + Math.random() * Math.max(0, ACCEPT_DELAY_MAX - ACCEPT_DELAY_MIN);
    if (Date.now() / 1000 - (room.at || 0) < waited) continue;
    const out = await bot.acceptInvite(room.room).catch(() => null);
    if (out && out.ok) console.log(`${TAG} Took a chat invitation.`);
    await delay(1500 + Math.random() * 2000);
  }
}

/** What the people it talks to have been posting, so it knows what they are up to. */
async function maybeTheirPosts() {
  if (!WATCH || !THEIR_POSTS) return;
  const all = contacts();
  const people = Object.keys(all).filter((id) => userOf(id)).slice(0, 20);
  if (!people.length) return;
  const chatId = people[Math.floor(Math.random() * people.length)];
  const row = all[chatId] || {};
  if (Date.now() / 1000 - (row.posts_at || 0) < 6 * 3600) return;
  const posts = await bot.theirPosts(userOf(chatId), 3).catch(() => []);
  remember(chatId, row.name, "", { posts_at: Math.floor(Date.now() / 1000),
                                   newest: (posts[0] || {}).url || row.newest || "" });
  if (posts[0]) core.tellPython({ kind: "posts", chat: chatId, newest: posts[0].url, fresh: true });
  if (UPVOTE_THEIRS && posts[0] && budget.allowed("upvotes") && !hiddenSince) {
    const out = await bot.press(posts[0].url, "upvote").catch(() => null);
    if (out && out.ok) budget.spend("upvotes");
  }
}

/** A comment nobody asked for, in one of the subreddits it was told it may take part in. */
async function maybeComments() {
  if (!COMMENTS_ON || hiddenSince || !budget.allowed("comments")) return;
  const sub = pickSubreddit();
  if (!sub) return;
  const page = await bot.outPage();
  await bot.goto(`https://www.reddit.com/r/${sub}/new/`, page);
  const rows = await bot.readInSteps(page, readPostsInPage, [SEL, USERNAME], (p) => p.id,
                                     { steps: 1, max: 20 }).catch(() => []);
  const fresh = rows.filter((p) => !p.mine && !p.promoted && !p.nsfw
    && (!SKIP_LOCKED || !p.locked)
    && (!COMMENT_FRESH_ONLY || !p.at || Date.now() - p.at < 36 * 3600000)
    && (p.score || 0) >= COMMENT_MIN_SCORE);
  if (!fresh.length) return;
  const pick = fresh[Math.floor(Math.random() * Math.min(fresh.length, 5))];
  const id = `comment:${pick.id}`;
  if (!core.isNew("__comments", pick.id)) return;
  const where = pick.url || postUrl(pick.subreddit, pick.id);
  pending.set(id, { at: Date.now(), chat: "" });
  core.handOver({
    id, kind: "post_comment",
    user_id: chatIdFor(pick.author) || `rd_${pick.author || "someone"}`,
    user_name: `u/${pick.author}`,
    channel_id: `post_${pick.id}`,
    content: `${pick.title}\n${String(pick.text || "").slice(0, 1500)}`.trim(),
    video: where,
    why: "theirs",
  });
}

/** Follow somebody whose posts it keeps reading, and join a subreddit it keeps reading, now and then. */
async function maybeFollow() {
  if (hiddenSince) return;
  if (FOLLOW_USERS && budget.allowed("follows")) {
    const all = contacts();
    const who = Object.keys(all).filter((id) => userOf(id) && !all[id].followed)[0];
    if (who) {
      const out = await bot.follow(userOf(who)).catch(() => null);
      if (out && out.ok) {
        budget.spend("follows");
        remember(who, all[who].name, "", { followed: true });
      }
    }
  }
  if (JOIN_SUBS && budget.allowed("joins")) {
    const sub = SUBREDDITS.find((s) => !refused(s));
    if (sub) {
      const out = await bot.joinSub(sub).catch(() => null);
      if (out && out.ok && !out.already) budget.spend("joins");
    }
  }
}

// ── What the panel asks for ─────────────────────────────────────────────────

async function panelRequest(req) {
  const op = String(req.op || "");
  const p = req.payload || {};
  try {
    if (op === "history" || op === "send" || op === "react") {
      const chatId = String(p.chat || p.chat_id || "");
      if (!CHAT_ID.test(chatId)) return { ok: false, reason: "not a chat id" };
      if (op === "history") {
        const got = await bot.readChat(chatId, { scrollUps: Number(p.scrolls) || 3 });
        if (!got.ok) return got;
        share(chatId, (contacts()[chatId] || {}).name, got.messages || []);
        return { ok: true, messages: keyedChat(chatId, got.messages || []) };
      }
      if (op === "send") {
        const out = await bot.sendText(chatId, String(p.text || ""));
        if (out.ok) core.recordSend();
        return out;
      }
      return await bot.react(chatId, p.idx, String(p.emoji || "👍"));
    }
    if (op === "friends") return { ok: true, friends: contacts() };
    if (op === "friend") {
      const info = await bot.profileInfo(String(p.username || ""));
      return info ? { ok: true, profile: info } : { ok: false, reason: "no such account" };
    }
    if (op === "add_friend" || op === "follow") return await bot.follow(String(p.username || ""));
    if (op === "posts") {
      const who = userOf(String(p.chat || "")) || String(p.username || "") || USERNAME;
      const posts = who === USERNAME ? await bot.ownPosts(Number(p.n) || 5)
        : await bot.theirPosts(who, Number(p.n) || 5);
      return { ok: true, posts };
    }
    if (op === "thread") {
      const got = await bot.readThread(String(p.url || ""), { scrolls: 2 });
      return got.post ? { ok: true, ...got } : { ok: false, reason: "nothing there to read" };
    }
    if (op === "inbox") {
      const rows = await bot.inbox({ scrolls: INBOX_SCROLLS });
      const seen = readJson(INBOX_FILE, {});
      return { ok: true, inbox: rows.filter((r) => !seen[r.id]) };
    }
    if (op === "subs") {
      // What it may take part in, and what each one said last time it tried.
      const was = readJson(REFUSED_FILE, {});
      return { ok: true, subreddits: SUBREDDITS.map((s) => ({ name: s, refused: was[s] || null })) };
    }
    if (op === "action") {
      const which = String(p.action || "upvote");
      if (which === "upvote" && !budget.allowed("upvotes")) return { ok: false, reason: "no upvotes left today" };
      const out = await bot.press(String(p.url || ""), which === "save" ? "save" : which);
      if (out.ok && which === "upvote") budget.spend("upvotes");
      return out;
    }
    if (op === "comment") {
      const out = await bot.replyTo(String(p.url || ""), String(p.text || "").slice(0, COMMENT_MAX_CHARS));
      if (out.ok) { budget.spend("comments"); await afterPublic(out.url); }
      return out;
    }
    if (op === "post") {
      const where = String(p.where ?? (POST_WHERE === "subreddits" ? pickSubreddit() : ""));
      if (where && !allowedIn(where)) return { ok: false, reason: `r/${where} is not on its list` };
      const out = await bot.post({ title: String(p.title || ""), text: String(p.text || ""),
                                   link: String(p.link || ""), image: (p.images || [])[0] || "",
                                   where, flair: POST_FLAIR, dryRun: !!p.dry_run || DRY_RUN });
      if (out.ok && !out.dry) { budget.spend("posts"); lastPostAt = Date.now(); }
      return out;
    }
    if (op === "out") {
      return {
        ok: true,
        left: { upvotes: budget.left("upvotes"), joins: budget.left("joins"), follows: budget.left("follows"),
                replies: budget.left("replies"), comments: budget.left("comments"), posts: budget.left("posts") },
        used: { upvotes: budget.used("upvotes"), joins: budget.used("joins"), follows: budget.used("follows"),
                replies: budget.used("replies"), comments: budget.used("comments"), posts: budget.used("posts") },
        hidden: !!hiddenSince,
      };
    }
    if (op === "fetch") {
      const file = await bot.captureMedia(String(p.url || ""));
      return file ? { ok: true, file } : { ok: false, reason: "nothing came back" };
    }
    if (op === "code") {
      codeWaiting.push(String(p.code || ""));
      return { ok: true };
    }
  } catch (e) {
    return { ok: false, reason: e.message };
  }
  return { ok: false, reason: `unknown request ${op}` };
}

async function processPanel() {
  while (core.panelQueue.length) {
    const req = core.panelQueue.shift();
    const out = await panelRequest(req);
    core.tellPython({ kind: "panel_result", id: req.id, ...out });
  }
}

// ── Signing in, when the session has finally run out ───────────────────────

const codeWaiting = [];

async function askForCode() {
  core.setState("needs-code", "Reddit sent a code to the account.");
  core.tellPython({ kind: "attention", what: "code" });
  for (let i = 0; i < 300; i++) {
    if (codeWaiting.length) return codeWaiting.shift();
    await core.sleepOrPoke(2000);
  }
  return "";
}

/**
 * The account signing itself back in. A person adding an account never comes through here - they sign in
 * themselves, in a window - so this only ever runs months later, when the session has run out, and only when a
 * password was saved for exactly that.
 */
async function signInNow() {
  const out = await bot.signIn({
    password: PASSWORD, totpKey: TOTP_KEY,
    onState: (state, detail) => { signInState = state; core.setState(state, detail || ""); },
    getCode: askForCode,
  });
  if (out.ok) {
    signInState = "";
    core.setState("ready");
    return true;
  }
  if (out.needs) {
    // A person has to. Started again it would try the same thing over, and that is how an account gets noticed.
    console.error(`${TAG} ${out.reason}`);
    core.setState("needs-you", out.reason);
    await delay(2000);
    process.exit(4);
  }
  return false;
}

async function checkCaptcha() {
  if (await bot.captchaShown().catch(() => false)) {
    core.setState("needs-you", "Reddit put up a check only a person can pass.");
    core.tellPython({ kind: "attention", what: "captcha" });
    await bot.showWindow().catch(() => {});
  }
}

async function waitSignedOut() {
  core.setState("logged-out", "waiting for a person");
  await delay(120000);
}

// ── Is the page still the page ──────────────────────────────────────────────

async function reportHealth() {
  const found = await bot.selectorHealth().catch(() => ({}));
  const missing = Object.keys(found).filter((k) => !found[k]);
  if (missing.length) {
    console.warn(`${TAG} Reddit's page has moved: ${missing.join(", ")} found nothing.`);
    core.setState("ready", `Reddit changed its page (${missing.join(", ")}).`, { health: found });
  }
}

/** The chat list, watched, so a new message wakes it rather than waiting out the poll. */
async function watchList() {
  if (!bot.page) return;
  await bot.page.exposeFunction("__llmPoke", () => { listChanged = true; core.wakeNow(); }).catch(() => {});
  await bot.page.evaluate((list) => {
    if (window.__llmWatching) return;
    let target = null;
    for (const q of list) {
      target = document.querySelector(q);
      if (target) break;
    }
    if (!target) return;
    window.__llmWatching = true;
    let last = 0;
    const observer = new MutationObserver(() => {
      // A list that mutates as fast as it scrolls means nothing without this.
      const now = Date.now();
      if (now - last < 2000) return;
      last = now;
      if (window.__llmPoke) window.__llmPoke();
    });
    observer.observe(target, { childList: true, subtree: true });
  }, SEL.chatRoomList).catch(() => {});
}

// ── The loop ────────────────────────────────────────────────────────────────

async function drainWindow(ms) {
  const started = Date.now();
  const until = started + ms;
  listChanged = false;
  while (Date.now() < until) {
    await core.sleepOrPoke(2000);
    try { await processPanel(); } catch { /* answered inside */ }
    try { await drainResponses(); } catch (e) { console.warn(`${TAG} Send error: ${e.message}`); }
    try { await drainOwnWork(); } catch { /* next time */ }
    if (listChanged && Date.now() - started > 4000) break;
  }
}

async function main() {
  if (!USERNAME) {
    console.error(`${TAG} No Reddit account ${ACCOUNT}: add one on the Accounts page.`);
    process.exit(1);
  }
  if (!fs.existsSync(PROFILE_DIR)) {
    // Its browser profile IS its login: a person made it by signing in, in a window. Without it there is nothing
    // to run, and nothing this process can do about that.
    console.error(`${TAG} Reddit account ${ACCOUNT} (u/${USERNAME}) has not been signed in. `
                  + "Sign it in on the Accounts page.");
    core.ensureFiles();
    core.setState("needs-you", "It has not been signed in yet. Sign it in on the Accounts page.");
    process.exit(4);               // a person has to: not started again by itself
  }

  bot = new RedditBot({ account: ACCOUNT, username: USERNAME, dataDir: DATA_DIR, locale: LOCALE,
                        timezone: TIMEZONE, tag: TAG });
  core.setState("starting", "launching the browser");
  console.log(`${TAG} Starting u/${USERNAME} (account #${ACCOUNT})${HIDDEN ? ", window hidden" : ""}`
              + `${DRY_RUN ? ", DRY RUN: nothing is sent" : ""}.`);
  await bot.launch({ hidden: HIDDEN, proxy: core.text("PROXY") });

  core.ensureFiles();
  core.connectWake();
  core.setState("starting", "opening its chats");
  for (let attempt = 1; ; attempt++) {
    try {
      await bot.goto("https://www.reddit.com/", bot.page);
      if (!(await bot.isLogged()) && !(await signInNow())) {
        if (signInState === "suspended") {
          await waitSignedOut();
          attempt = 0;
          continue;
        }
        await delay(60000);
        process.exit(3);
      }
      await checkCaptcha();
      await recordIdentity();
      if (CHECK_SHADOWBAN) {
        const got = await bot.notHidden().catch(() => ({ hidden: false }));
        if (got.hidden) {
          hiddenSince = Date.now();
          console.error(`${TAG} Reddit is hiding this account: ${got.why} Everything public stays off.`);
          core.setState("needs-you", `Reddit is hiding this account. ${got.why}`);
        }
      }
      await bot.openChatHome();
      break;
    } catch (e) {
      if (attempt >= 4) throw e;
      console.warn(`${TAG} Opening Reddit went wrong (${e.message}); trying again.`);
      await bot.ensure().catch(() => {});
      await delay(2500 * attempt);
    }
  }

  await watchList();
  await reportHealth();
  if (HIDDEN) await bot.hideWindow().catch(() => {});
  core.setState("ready");
  console.log(`${TAG} Ready. ${SUBREDDITS.length ? `Taking part in r/${SUBREDDITS.join(", r/")}.`
                                                 : "Its own profile and the threads it is already in."} `
              + `${core.minGap / 1000}-${core.maxGap / 1000}s between sends, at most ${core.perHour} an hour`
              + `${core.quiet ? `, quiet ${core.quiet}` : ""}.`);

  let reloadDue = Date.now() + RELOAD_MS * (0.75 + Math.random() * 0.5);
  let listFailures = 0;
  while (true) {
    core.heartbeatState();
    await siteWatch.tick().catch(() => {});
    try {
      if ((await bot.ensure()) !== "ok") {
        await bot.goto("https://www.reddit.com/", bot.page);
        if (!(await bot.isLogged()) && !(await signInNow())) { await waitSignedOut(); continue; }
        await watchList();
        core.setState("ready");
      }
      if (Date.now() - identityAt > 4 * 3600 * 1000) await recordIdentity().catch(() => {});
      await processPanel();
      await checkCaptcha();
      if (RELOAD_MS > 0 && Date.now() > reloadDue && !pending.size) {
        reloadDue = Date.now() + RELOAD_MS * (0.75 + Math.random() * 0.5);
        await bot.goto("https://chat.reddit.com/", bot.page);
        if (!(await bot.isLogged()) && !(await signInNow())) { await waitSignedOut(); continue; }
        await watchList();
        await reportHealth();
      }
      await drainResponses();
      await processOutgoing();

      let rows;
      try {
        rows = await bot.listRooms({ scrolls: 2 });
        listFailures = 0;
      } catch (e) {
        if (++listFailures >= 3) {
          console.warn(`${TAG} Its chats would not read three times over (${e.message}); reloading.`);
          listFailures = 0;
          await bot.goto("https://chat.reddit.com/", bot.page).catch(() => {});
          await reportHealth();
        }
        await drainWindow(core.jitteredPoll());
        continue;
      }
      for (const r of rows) {
        const id = idOfRow(r);
        if (!id) continue;
        await remember(id, r.name, r.avatar, r.room ? { room: r.room } : null);
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
      await maybeInvites();
      await maybeInbox();
      await maybeComments();
      await maybeFollow();
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
