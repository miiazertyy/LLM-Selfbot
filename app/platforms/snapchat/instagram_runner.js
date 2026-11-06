/**
 * platforms/snapchat/instagram_runner.js
 *
 * Node side of the Instagram platform: one account, in its own Chrome profile
 * (config/instagram-<username>-profile, made when it was added from the panel).
 * Reads its inbox, hands new messages to the Python bridge, and sends the
 * bridge's replies back, at a person's pace. The same files and wake socket as
 * the Snapchat and TikTok runners (runner_core.js), so the same bridge serves
 * all three.
 *
 * Unlike TikTok's, this one signs itself in: the account's username, password
 * and 2FA key live in config/.env, and it makes the six digits itself. A code
 * sent to the account's email or phone is the one thing it cannot make up, so
 * it says "needs a code" and waits for the panel to hand one over.
 *
 * Besides the inbox, all off unless switched on in Settings, Instagram:
 *   message requests accepted after a while,
 *   new followers followed back, follow requests accepted,
 *   the stories of the people it talks to watched, and some answered,
 *   new comments on its own posts answered (in public),
 *   Reels scrolled now and then, some liked,
 *   likes and comments on what it is sent and what they post,
 *   its Note set from its mood,
 *   its activity status hidden in the night hours.
 *
 * INSTAGRAM_DRY_RUN=true reads, writes replies to the log and types them, and
 * sends nothing.
 */
import dotenv from "dotenv";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { randomUUID } from "crypto";
import { patchConsole } from "./log.js";
import { createCore, createBudget, keyed, readJson, writeJson, delay } from "./runner_core.js";
import InstagramBot, { SEL, chatIdFor, usernameOf, cleanUsername } from "./instagrambot.js";
import { SiteWatch, applySiteFixes } from "./sitewatch.js";
import { showWindow, hideWindow } from "./browser.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: process.env.INSTAGRAM_DOTENV_PATH || "../../config/.env", quiet: true });
patchConsole();

const TAG = "[Instagram]";
const DATA_DIR = process.env.INSTAGRAM_DATA_DIR || process.env.SNAP_DATA_DIR || path.resolve(__dirname, "../../");
const ACCOUNT = parseInt(process.env.INSTAGRAM_ACCOUNT_INDEX || "1", 10) || 1;
const USERNAME = cleanUsername(process.env[`INSTAGRAM_USERNAME_${ACCOUNT}`] || "");
const PASSWORD = String(process.env[`INSTAGRAM_PASSWORD_${ACCOUNT}`] || "");
const TOTP_KEY = String(process.env[`INSTAGRAM_TOTP_${ACCOUNT}`] || "").replace(/[\s-]/g, "");
// What it runs at when the settings file has no instagram: section yet (one written before this platform
// existed). The same numbers as resources/config.yaml, so a fresh install and an old one behave alike.
const core = createCore({
  prefix: "insta", env: "INSTAGRAM", account: ACCOUNT, dataDir: DATA_DIR, tag: TAG,
  defaults: {
    POLL_INTERVAL_MS: 12000, MAX_RECIPIENTS: 10, RESPONSE_TIMEOUT_MS: 90000,
    MIN_SEND_GAP_MS: 20000, MAX_SEND_GAP_MS: 60000, MAX_SENDS_PER_HOUR: 20,
    RELOAD_INTERVAL_MS: 2700000, WATCH: true, THEIR_POSTS: true, STORIES_WATCH: true,
    LIKES_PER_DAY: 20, COMMENTS_PER_DAY: 3, REELS_SESSIONS: 3, REELS_MINUTES: 5,
    REELS_LIKE_PERCENT: 10, STORY_REPLIES_PER_DAY: 3, STORIES_PER_DAY: 2, POSTS_PER_DAY: 3,
    COMMENTS_PER_HOUR: 8, COMMENTS_POSTS: 3, NOTES_HOURS: 12,
  },
});

const HIDDEN = core.flag("HEADLESS", false);
const DRY_RUN = core.flag("DRY_RUN", false);
const LOCALE = core.text("LOCALE", "en-US") || "en-US";
const TIMEZONE = core.text("TIMEZONE", "");
const MONTH_FIRST = /^en-us/i.test(LOCALE);
const MAX_RECIPIENTS = core.num("MAX_RECIPIENTS", 10);
const RESPONSE_TTL_MS = Math.max(core.num("RESPONSE_TIMEOUT_MS", 90000), 120000);
const RELOAD_MS = core.num("RELOAD_INTERVAL_MS", 45 * 60 * 1000);
const ACCEPT_REQUESTS = core.flag("ACCEPT_MESSAGE_REQUESTS", false);
const FOLLOW_BACK = core.flag("FOLLOW_BACK", false);
const ACCEPT_FOLLOWS = core.flag("ACCEPT_FOLLOW_REQUESTS", false);
const ACCEPT_DELAY_MIN = core.num("ACCEPT_DELAY_MIN", 300);
const ACCEPT_DELAY_MAX = core.num("ACCEPT_DELAY_MAX", 3600);
const NIGHT_ACTIVITY = core.flag("NIGHT_ACTIVITY_STATUS", false);
const NIGHT_HOURS = core.text("NIGHT_HOURS", "");
const TRIGGER = core.text("TRIGGER", "");
// Going out (Settings, Instagram). Everything public is off until switched on; each has a daily limit.
const WATCH = core.flag("WATCH", true);
const THEIR_POSTS = core.flag("THEIR_POSTS", true);
const VOICE_NOTES = core.flag("VOICE_NOTES", false);
const STORIES_WATCH = core.flag("STORIES_WATCH", true);
const STORIES_REPLY = core.flag("STORIES_REPLY", false);
const REELS = core.flag("REELS", false);
const REELS_MINUTES = Math.max(1, core.num("REELS_MINUTES", 5));
const REELS_LIKE_PERCENT = Math.max(0, Math.min(100, core.num("REELS_LIKE_PERCENT", 10)));
const LIKE_SENT = core.flag("LIKE_SENT", false);
const LIKE_THEIRS = core.flag("LIKE_THEIRS", false);
const COMMENT_SENT = core.flag("COMMENT_SENT", false);
const COMMENT_THEIRS = core.flag("COMMENT_THEIRS", false);
const COMMENTS = core.flag("COMMENTS", false);
const COMMENTS_PER_HOUR = core.num("COMMENTS_PER_HOUR", 8);
const COMMENTS_POSTS = core.num("COMMENTS_POSTS", 3);
const NOTES = core.flag("NOTES", false);
const NOTES_HOURS = Math.max(1, core.num("NOTES_HOURS", 12));
// Instagram's own chats: nobody there to answer.
const SYSTEM_CHATS = ["instagram", "meta ai", "instagram user"];

const PROFILE_DIR = path.join(DATA_DIR, "config", `instagram-${USERNAME}-profile`);
const IDENTITY_FILE = path.join(DATA_DIR, "config", `identity_instagram_${ACCOUNT}.json`);
const PEOPLE_DIR = path.join(DATA_DIR, "cache", "instagram_people");
const CONTACTS_FILE = path.join(PEOPLE_DIR, `contacts_${ACCOUNT}.json`);
const COMMENTS_FILE = path.join(PEOPLE_DIR, `comments_${ACCOUNT}.json`);
// What it has been doing out there: stories seen, posts engaged with, reels it saw and liked.
const OUT_FILE = path.join(PEOPLE_DIR, `out_${ACCOUNT}.json`);
const SEEN_FILE = path.join(PEOPLE_DIR, `seen_${ACCOUNT}.json`);
// What the fake microphone plays: Chrome is told this file at launch, and each voice note is copied onto it first.
const VOICE_FILE = path.join(DATA_DIR, "config", "temp", `insta_${ACCOUNT}_voice_out.wav`);
// So many a day, whatever restarts in between (cache/instagram_people/budget_N.json).
const budget = createBudget(path.join(PEOPLE_DIR, `budget_${ACCOUNT}.json`), {
  likes: core.num("LIKES_PER_DAY", 20), comments: core.num("COMMENTS_PER_DAY", 3),
  reels: core.num("REELS_SESSIONS", 3), posts: core.num("POSTS_PER_DAY", 3),
  stories: core.num("STORIES_PER_DAY", 2), story_replies: core.num("STORY_REPLIES_PER_DAY", 3),
});
// Instagram's picture hosts (its CDN is Facebook's).
const PICTURE_HOSTS = /^https:\/\/([a-z0-9-]+\.)*(cdninstagram\.com|fbcdn\.net|instagram\.com)\//i;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36";

// The few things that should always be on the pages it sits on, and a fix for any of its selectors without a new build
// (sitewatch.js). Only ever looked for on tabs it already has open.
applySiteFixes(SEL, "instagram", DATA_DIR, (m) => console.log(`${TAG} ${m}`));
const siteWatch = new SiteWatch({
  core: [
    { name: "the list of chats", sel: SEL.threadList, on: /instagram\.com\/direct\/inbox/ },
    { name: "the box to write in", sel: SEL.composer, on: /instagram\.com\/direct\/t\// },
  ],
  pages: () => bot?.browser?.pages(),
  report: (missing) => core.keepSaying(missing.length ? { site: { missing } } : {}),
});

let bot = null;

// ── Who is who: names and pictures off the list, for the panel (cache/instagram_people) ──
let contacts = null;
function loadContacts() {
  if (contacts) return contacts;
  try { contacts = JSON.parse(fs.readFileSync(CONTACTS_FILE, "utf-8")) || {}; } catch { contacts = {}; }
  return contacts;
}
function saveContacts() {
  try { writeJson(CONTACTS_FILE, contacts || {}); } catch { /* next time */ }
}
/** The thread a person's conversation is, as learned when it was last open. */
function threadOf(chatId) {
  return String((loadContacts()[chatId] || {}).thread || "");
}
/** Whose conversation a thread is, the other way round. */
function chatOfThread(thread) {
  const known = loadContacts();
  for (const [id, c] of Object.entries(known)) if (c && String(c.thread) === String(thread)) return id;
  return "";
}
/**
 * Whoever is already known under the name a row shows.
 *
 * A display name is not a username, and Instagram's inbox rows carry nothing else: no link, no id. Making an id out
 * of the name meant any name shaped like a username became a person of that name, so the address book filled up
 * with people called Active and Mischievous who were never anybody. A row is only somebody once its conversation
 * has been opened and the real username read; until then it is matched by name against the people already known.
 */
function chatOfName(name) {
  const want = String(name || "").trim().toLowerCase();
  if (!want) return "";
  const known = loadContacts();
  for (const [id, c] of Object.entries(known)) {
    if (c && String(c.name || "").trim().toLowerCase() === want) return id;
  }
  return "";
}
/**
 * The people an older build invented, dropped once: a contact whose whole id is what its own display name would
 * make of it, which never had a conversation, never wrote and was never looked up. Those are the rows that were
 * read as people. Anyone real is known by their username from the profile link in their conversation, so their id
 * and their name do not agree like that; and one that did agree, with nothing behind it, is a name and a picture
 * that come back the moment the conversation is opened.
 */
function dropInvented() {
  const known = loadContacts();
  const gone = [];
  for (const [id, c] of Object.entries(known)) {
    if (!c || !id.startsWith("ig_") || c.thread || c.wrote || c.profiled) continue;
    if (chatIdFor(cleanUsername(c.name)) !== id) continue;
    if (c.file) { try { fs.unlinkSync(path.join(PEOPLE_DIR, c.file)); } catch { /* gone already */ } }
    delete known[id];
    gone.push(c.name || id);
  }
  if (gone.length) {
    saveContacts();
    console.log(`${TAG} Forgot ${gone.length} name${gone.length > 1 ? "s" : ""} an older build read off the inbox `
      + `rather than out of a conversation: ${gone.join(", ")}.`);
  }
}

async function savePicture(url, stem) {
  if (!url || !PICTURE_HOSTS.test(url)) return "";
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000), headers: { "user-agent": UA } });
    if (!res.ok) return "";
    const type = res.headers.get("content-type") || "";
    const ext = type.includes("png") ? "png" : type.includes("webp") ? "webp" : type.includes("jpeg") || type.includes("jpg") ? "jpg" : "";
    if (!ext) return "";
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length < 100 || buf.length > 3_000_000) return "";
    fs.mkdirSync(path.dirname(stem), { recursive: true });
    fs.writeFileSync(`${stem}.${ext}`, buf);
    return path.basename(`${stem}.${ext}`);
  } catch {
    return "";
  }
}

async function remember(chatId, name, avatar, extra = null) {
  if (!/^[A-Za-z0-9_-]{1,80}$/.test(chatId)) return;
  const known = loadContacts();
  const was = known[chatId] || {};
  const now = { ...was, name: name || was.name || "", seen: Date.now() / 1000, ...(extra || {}) };
  if (extra && extra.profile) {
    const p = extra.profile;
    delete now.profile;
    Object.assign(now, { bio: String(p.bio || "").slice(0, 400), followers: p.followers || 0,
                         verified: !!p.verified, private: !!p.private, profiled: Date.now() / 1000 });
  }
  if (avatar && avatar !== was.url) {
    const file = await savePicture(avatar, path.join(PEOPLE_DIR, `${ACCOUNT}_${chatId}`));
    if (file) {
      if (was.file && was.file !== file) { try { fs.unlinkSync(path.join(PEOPLE_DIR, was.file)); } catch { /* gone */ } }
      now.file = file;
      now.url = avatar;
    }
  }
  if (JSON.stringify(now) !== JSON.stringify(was)) {
    known[chatId] = now;
    saveContacts();
  }
}

/** Whether a contact's profile is worth reading (again): never read, or a week ago. */
function wantsProfile(chatId) {
  const c = loadContacts()[chatId];
  return !c || !c.profiled || Date.now() / 1000 - c.profiled > 7 * 86400;
}

/**
 * The account's own name, picture, bio and counts, as its Instagram profile shows them, for its card in the panel
 * (config/identity_instagram_N.json). Read at the start, then every few hours.
 */
let identityAt = 0;
async function recordIdentity() {
  const me = await bot.whoAmI();
  if (!me) return;
  identityAt = Date.now();
  let before = {};
  try { before = JSON.parse(fs.readFileSync(IDENTITY_FILE, "utf-8")); } catch { /* first time */ }
  if (!me.profiled && before.username === me.username && before.display_name) {
    identityAt = Date.now() - 3.5 * 3600 * 1000;          // asked again in half an hour
    return;
  }
  const stem = path.join(DATA_DIR, "config", `identity_instagram_${ACCOUNT}`);
  let picture = before.picture || "";
  const sameFile = (a, b) => String(a || "").split("?")[0] === String(b || "").split("?")[0];
  if (me.avatar && (!picture || !sameFile(me.avatar, before.picture_url))) picture = (await savePicture(me.avatar, stem)) || picture;
  const out = { username: me.username, display_name: me.name || before.display_name || "", picture,
                picture_url: me.avatar || before.picture_url || "", at: Date.now() / 1000 };
  for (const k of ["bio", "followers", "following", "posts", "verified", "private"]) {
    if (me[k] !== undefined) out[k] = me[k];
  }
  try { writeJson(IDENTITY_FILE, out); } catch { /* the card keeps what it had */ }
  if (me.username && me.username !== USERNAME) {
    console.warn(`${TAG} This profile is signed in as @${me.username}, not @${USERNAME}.`);
  }
  if (before.username !== out.username || before.display_name !== out.display_name) {
    console.log(`${TAG} Signed in as ${out.display_name || out.username} (@${out.username}).`);
  }
}

// ── Conversations ────────────────────────────────────────────────────────────

function keyedChat(chatId, messages) {
  return keyed(chatId, messages || [], { monthFirst: MONTH_FIRST, prefix: "i" });
}

/** The conversation as it reads now, to Python, which keeps it for the panel and says what is new. */
function share(chatId, name, messages) {
  if (!core.connected() || !messages.length) return;
  core.tellPython({ kind: "transcript", chat: chatId, name: name || "", messages: messages.slice(-120) });
}

/** What a message says, for the AI: its words, and what it is when it is not words. */
function describe(m) {
  const url = m.media?.url || "";
  const quote = m.quote ? `[replying to: "${m.quote.slice(0, 160)}"] ` : "";
  let said = m.text;
  if (m.kind === "reel") said = `[shared a reel${url ? `: ${url}` : ""}${m.title ? ` (${m.title})` : ""}]${m.text ? ` ${m.text}` : ""}`;
  else if (m.kind === "post") said = `[shared a post${url ? `: ${url}` : ""}${m.title ? ` (${m.title})` : ""}]${m.text ? ` ${m.text}` : ""}`;
  else if (m.kind === "story") said = `[shared a story${url ? `: ${url}` : ""}]${m.text ? ` ${m.text}` : ""}`;
  else if (m.kind === "storyreply") said = `[answering your story]${m.text ? ` ${m.text}` : ""}`;
  else if (m.kind === "heart") said = "[tapped the heart]";
  else if (m.kind === "gif") said = m.text || "[sent a GIF]";
  else if (m.kind === "sticker") said = m.text || "[sent a sticker]";
  else if (m.kind === "clip") said = m.text || "[sent a video]";
  else if (m.kind === "viewonce") said = "[sent a photo that can only be looked at once]";
  else if (m.kind === "unsent") said = "";
  else if (m.kind === "photo" || m.kind === "voice") said = m.text || "";
  return said ? quote + said : said;
}

const pending = new Map();      // reply id -> { chatId, name, ts }

/** Open one conversation from the list, hand what is new in it to Python, and leave. */
async function readChat(row) {
  // Instagram's rows carry no id: opening one is what says which conversation it is.
  const thread = await bot.openRow(row);
  if (!thread) return;
  row.id = thread;
  await delay(600);
  const chat = await bot.readChat().catch(() => null);
  if (!chat) {
    console.warn(`${TAG} Opened ${row.name || "a chat"} but could not read it.`);
    return;
  }
  // The username the open conversation itself gives, never one read off a display name (see chatOfName).
  const username = cleanUsername(chat.username);
  // A group has no one username, and neither has a conversation that would not say: both are known by the thread.
  const chatId = row.group || !username ? `igg_${thread}` : chatIdFor(username);
  const name = row.name || chat.name || (username ? `@${username}` : "a group");
  const profile = !row.group && username && wantsProfile(chatId)
    ? await bot.profileInfo(username).catch(() => null) : null;
  await remember(chatId, name, row.avatar, { thread: row.id, ...(profile ? { profile } : {}) });
  const messages = keyedChat(chatId, chat.messages);
  share(chatId, name, messages);
  let lastMine = -1;
  messages.forEach((m, i) => { if (m.mine) lastMine = i; });
  const fresh = messages.slice(lastMine + 1).filter((m) => !m.mine && core.isNew(chatId, m.key));
  if (!fresh.length) return;
  noteWrote(chatId, fresh);
  let content = fresh.map(describe).filter(Boolean).join("\n");
  // In a group, only what calls the persona by name, as on Discord's servers. The names are a list ("John, Jon"):
  // matched whole, it was the words "John, Jon" together that were looked for, and nothing ever said them.
  if (row.group && TRIGGER && !TRIGGER.split(",").map((w) => w.trim()).filter(Boolean)
    .some((w) => new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(content))) return;
  let image = "", audio = "", video = "";
  if (fresh.some((m) => m.kind === "photo" || m.kind === "viewonce")) {
    image = await bot.capturePhoto(`insta_${ACCOUNT}_photo`).catch(() => "");
  }
  if (fresh.some((m) => m.kind === "voice")) audio = await bot.captureVoice(`insta_${ACCOUNT}_voice`).catch(() => "");
  if (fresh.some((m) => m.kind === "clip")) video = await bot.captureVideo(`insta_${ACCOUNT}_video`).catch(() => "");
  // A shared reel or post whose cover came with it, for the vision model, when nothing else did.
  const shared = fresh.filter((m) => ["reel", "post", "story"].includes(m.kind) && m.media?.cover && !m.media?.url).pop();
  let cover = false;
  if (!image && shared) {
    const file = await savePicture(shared.media.cover, path.join(DATA_DIR, "config", "temp", `insta_${ACCOUNT}_cover_${Date.now()}`));
    if (file) {
      image = path.join(DATA_DIR, "config", "temp", file);
      cover = true;
    }
  }
  if (!content && !image && !audio && !video) content = "[sent a photo]";
  const id = randomUUID();
  core.handOver({
    id, user_id: chatId, user_name: name, channel_id: chatId, content,
    image_url: image ? `file://${image}` : undefined,
    audio_url: audio ? `file://${audio}` : undefined,
    video_url: video ? `file://${video}` : undefined,
    cover: cover || undefined,
    group: !!row.group || undefined,
    photo: !!chat.photoButton,
    voice: !!chat.voiceButton && VOICE_NOTES,
  });
  pending.set(id, { chatId, name, ts: Date.now() });
}

async function openChat(chatId, name) {
  const thread = threadOf(chatId) || (String(chatId).startsWith("igg_") ? String(chatId).slice(4) : "");
  if (String(chatId).startsWith("igg_")) return await bot.openThread(thread);
  return await bot.openChatWith(usernameOf(chatId), { name, thread });
}

// Answers sent by loops of their own, at their own pace.
const OWN_PACE = new Set(["post_comment", "story_reply", "note"]);

/** Send the replies Python has finished, one a send slot, opening each conversation fresh. */
async function drainResponses() {
  const now = Date.now();
  for (const [id, p] of pending) if (now - p.ts > RESPONSE_TTL_MS) pending.delete(id);
  const waiting = core.responses();
  for (const id of Object.keys(waiting)) {
    const kind = (waiting[id] && typeof waiting[id] === "object" && waiting[id].kind) || "dm";
    if (OWN_PACE.has(kind)) continue;
    // A reply under its own posts waits for a comment slot rather than a send slot.
    if (kind === "comment" ? !commentAllowed() : !core.sendAllowed()) break;
    const val = core.take(id);
    if (val == null) continue;
    const text = val && typeof val === "object" ? val.text : val;
    const chatId = val && typeof val === "object" ? val.chat : pending.get(id)?.chatId;
    const name = (val && val.name) || pending.get(id)?.name || chatId;
    pending.delete(id);
    if (!text || !chatId) continue;
    const attempts = ((val && val._attempts) || 0) + 1;
    let out = { ok: false };
    try {
      if (kind === "comment") {
        out = await replyComment(val, text);
      } else if (await openChat(chatId, name)) {
        await delay(800 + Math.random() * 2200);           // reads it again before answering
        out = await bot.sendText(text, { dryRun: DRY_RUN });
      } else {
        out = { ok: false, reason: "could not open their conversation" };
      }
    } catch (e) {
      out = { ok: false, reason: e.message };
    }
    if (out.ok) {
      if (kind === "comment") commentSent(); else core.recordSend();
      console.log(`  sent to ${name}${out.dry ? " (dry run)" : ""}`);
      if (kind !== "comment") {
        const chat = await bot.readChat().catch(() => null);
        if (chat) share(chatId, name, keyedChat(chatId, chat.messages));
      }
      await delay(500 + Math.random() * 900);
    } else if (/too fast|limit|try again later/i.test(out.reason || "")) {
      // Instagram asked for a break: the reply waits, and so does everything else, for a good while.
      console.warn(`${TAG} ${out.reason}.`);
      core.putBack(id, { ...(typeof val === "object" ? val : { text, chat: chatId, name }), _attempts: attempts });
      core.recordSend();
      core.setState("ready", `${out.reason}.`);
      break;
    } else if (attempts >= 4 || /blocked|restricted|cannot message|suspended/i.test(out.reason || "")) {
      console.warn(`${TAG} Not sent to ${name}: ${out.reason || "it would not go"}.`);
    } else {
      core.putBack(id, { ...(typeof val === "object" ? val : { text, chat: chatId, name }), _attempts: attempts });
    }
  }
}

/** Messages Python sends on its own: a Reply from the panel, a nudge, a picture, a voice note. One a send slot. */
async function processOutgoing() {
  const outgoing = readJson(core.files.outgoing, []);
  if (!Array.isArray(outgoing) || !outgoing.length || !core.sendAllowed()) return;
  const entry = outgoing[0];
  writeJson(core.files.outgoing, outgoing.slice(1));
  const { chat, message, image, voice, seconds } = entry || {};
  if (!chat || (!message && !image && !voice)) return;
  const name = entry.name || chat;
  if (!(await openChat(chat, name))) {
    console.warn(`${TAG} Could not open ${name}'s conversation to send to them.`);
    return;
  }
  if (image) {
    const r = await bot.sendImage(image, { dryRun: DRY_RUN });
    console.log(r.ok ? `${TAG} Picture sent to ${name}` : `${TAG} Picture not sent to ${name}: ${r.reason}`);
    if (r.ok) core.recordSend();
  }
  if (voice) {
    if (!VOICE_NOTES) {
      console.warn(`${TAG} Voice notes are off for this account (Settings, Instagram).`);
    } else {
      let r = { ok: false, reason: "the voice note's file is not there" };
      try {
        // Its file box takes sound, so the file itself goes. A copy sits on the fake microphone's file too, for
        // the chats where Instagram offers a microphone instead (sendVoice picks whichever is there).
        try { fs.copyFileSync(voice, VOICE_FILE); } catch { /* the file box is the way, then */ }
        r = await bot.sendVoice(voice, { dryRun: DRY_RUN, seconds: Number(seconds) || 0 });
      } catch (e) {
        r = { ok: false, reason: e.message };
      }
      try { fs.unlinkSync(voice); } catch { /* already gone */ }
      console.log(r.ok ? `${TAG} Voice note sent to ${name}` : `${TAG} Voice note not sent to ${name}: ${r.reason}`);
      if (r.ok) core.recordSend();
    }
  }
  if (message) {
    await delay(core.typingTime(message) * 0.25);
    const r = await bot.sendText(message, { dryRun: DRY_RUN });
    if (r.ok) {
      core.recordSend();
      const chatNow = await bot.readChat().catch(() => null);
      if (chatNow) share(chat, name, keyedChat(chat, chatNow.messages));
    } else {
      console.warn(`${TAG} Not sent to ${name}: ${r.reason}`);
    }
  }
}

// ── The panel's requests, between the bot's own steps ─────────────────────────

let requestsSeen = [];
let requestsAt = 0;
// A code the panel typed, waiting for whoever asked for one.
let codeWaiting = "";
let codeWanted = false;

async function panelRequest(req) {
  if (req.op === "friends") {
    if (Date.now() - requestsAt > 180000) {
      requestsSeen = (await bot.messageRequests().catch(() => [])).map((r) => ({ name: r.name, username: r.username || "",
                                                                                  avatar: r.avatar, preview: r.preview,
                                                                                  id: r.id }));
      requestsAt = Date.now();
    }
    return { ok: true, requests: requestsSeen };
  }
  if (req.op === "add_friend" || req.op === "follow") {
    return await outNow(`following @${cleanUsername(req.username || req.name || "")}`,
                        () => bot.follow(String(req.username || req.name || "")));
  }
  if (req.op === "friend") {
    // Instagram's own request rows carry no id: the name it shows is what the panel knows them by, and what the
    // bot opens them by. A thread, when one is known, is better still.
    const name = String(req.name || req.id || "");
    const known = requestsSeen.find((r) => r.name === name) || {};
    const r = await bot.answerRequest({ name: known.name || name, id: known.id || "" }, req.accept !== false);
    requestsAt = 0;
    return r;
  }
  if (req.op === "code") {
    const code = String(req.code || "").replace(/\D/g, "");
    if (!code) return { ok: false, reason: "that is not a code" };
    if (!codeWanted) return { ok: false, reason: "Instagram is not asking for a code right now" };
    codeWaiting = code;
    return { ok: true };
  }
  if (req.op === "note") {
    const text = String(req.text || "").trim().slice(0, 60);
    if (!text) {
      // Nothing said: Python writes one from its mood, and it comes back as a "note" response.
      core.handOver({ id: randomUUID(), kind: "note", user_id: "note", user_name: "its Note",
                      channel_id: "note", content: "" });
      return { ok: true, asked: true };
    }
    return await outNow("setting its Note", () => bot.setNote(text));
  }
  if (req.op === "fetch") {
    // Another account (or this one) asking for a post's media, so Python can watch it.
    const url = String(req.url || "");
    if (!/instagram\.com\/(p|reel|reels|tv|stories)\//.test(url)) return { ok: false, reason: "not an Instagram link" };
    return await outNow("opening a post", async () => {
      const got = await bot.captureMedia(url, `insta_${ACCOUNT}_watch`);
      return got.file ? { ok: true, file: got.file, kind: got.kind, facts: got.facts || {} }
                      : { ok: false, reason: "Instagram would not give that post's media", facts: got.facts || {} };
    }, { interrupt: false, waitMs: 30000 });
  }
  // ── Going out, asked for by the panel or Telegram: in the out tab ──
  if (req.op === "posts") {
    const chatId = String(req.chat || "");
    const username = usernameOf(chatId);
    if (!username) return { ok: false, reason: "which chat?" };
    return await outNow(`looking at @${username}'s posts`, async () => {
      const posts = await bot.profilePosts(username, 9);
      const c = loadContacts()[chatId];
      if (c && posts.length) {
        Object.assign(c, { posts: posts.map(({ id, kind, url, caption, pinned, cover }) => ({ id, kind, url, caption, pinned, cover })),
                           posts_at: Date.now() / 1000, newest: c.newest || (posts.find((p) => !p.pinned) || posts[0]).url });
        saveContacts();
      }
      return { ok: true, posts };
    }, { interrupt: false, waitMs: 20000 });
  }
  if (req.op === "stories") {
    const chatId = String(req.chat || "");
    const username = usernameOf(chatId);
    if (!username) return { ok: false, reason: "which chat?" };
    const p = await bot.profileInfo(username).catch(() => null);
    return { ok: true, story: !!(p && p.has_story), username, private: !!(p && p.private) };
  }
  if (req.op === "story") {
    const chatId = String(req.chat || "");
    const username = usernameOf(chatId);
    if (!username) return { ok: false, reason: "which chat?" };
    const action = String(req.action || "watch");
    return await outNow(`${action === "watch" ? "watching" : "answering"} @${username}'s story`, async () => {
      const seen = await bot.watchStories(username, { dryRun: DRY_RUN });
      if (!seen.ok) return seen;
      noteStorySeen(chatId, seen.seen);
      if (action !== "watch" && (req.text || req.emoji)) {
        if (!budget.allowed("story_replies")) {
          return { ok: false, reason: `Already ${budget.used("story_replies")} story replies today, the most Settings allows` };
        }
        const r = await bot.replyToStory(String(req.text || ""), { emoji: String(req.emoji || ""), dryRun: DRY_RUN });
        if (r.ok && !r.dry) budget.spend("story_replies");
        return { ...r, seen: seen.seen };
      }
      return seen;
    }, { waitMs: 60000 });
  }
  if (req.op === "media") {
    const url = String(req.url || "");
    const action = String(req.action || "");
    if (!/instagram\.com\/(p|reel|reels|tv)\//.test(url)) return { ok: false, reason: "That is not an Instagram post" };
    return await outNow(`${action === "comment" ? "commenting on" : action === "save" ? "saving" : "liking"} a post`, async () => {
      if (action === "like") {
        const r = await bot.likePost(url, { dryRun: DRY_RUN, watchMs: 800 });
        if (r.ok && !r.already && !r.dry) budget.spend("likes");
        return r;
      }
      if (action === "save") return await bot.savePost(url, { dryRun: DRY_RUN, watchMs: 800 });
      if (action === "comment") {
        const r = await bot.commentOnPost(url, String(req.text || "").slice(0, 150), { dryRun: DRY_RUN });
        if (r.ok && !r.dry) budget.spend("comments");
        return r;
      }
      return { ok: false, reason: `unknown action ${action}` };
    });
  }
  if (req.op === "reels") {
    if (!(await freeOut())) return { ok: false, reason: `Instagram is busy (${outBusy}); try again in a minute` };
    outJob("scrolling Reels", reelsSession);
    return { ok: true, started: true };
  }
  if (req.op === "out") {
    const left = Object.fromEntries(Object.keys(budget.limits).map((k) => [k, budget.left(k)]));
    return { ok: true, busy: outBusy, left,
             used: Object.fromEntries(Object.keys(budget.limits).map((k) => [k, budget.used(k)])) };
  }
  if (req.op === "post") {
    const as = String(req.as || "post");
    const which = as === "story" ? "stories" : "posts";
    if (!budget.allowed(which)) {
      return { ok: false, reason: `Already ${budget.used(which)} ${which === "stories" ? "stories" : "posts"} today, the most Settings allows` };
    }
    return await outNow(`posting a ${as}`, async () => {
      const r = await bot.postMedia(String(req.file || ""), String(req.caption || ""),
                                    { as, dryRun: DRY_RUN || !!req.dry_run });
      if (r.ok && !r.dry) budget.spend(which);
      return r;
    }, { waitMs: 60000 });
  }
  const chatId = String(req.chat || "");
  if (!/^(ig_[a-z0-9_-]{1,40}|igg_\d{5,40})$/.test(chatId)) return { ok: false, reason: "which chat?" };
  const name = req.name || loadContacts()[chatId]?.name || "";
  if (!(await openChat(chatId, name))) return { ok: false, reason: "Instagram did not open that conversation" };
  await delay(500);
  if (req.op === "history") {
    const chat = await bot.readChat().catch(() => null);
    const messages = keyedChat(chatId, chat?.messages || []);
    return { ok: true, messages };
  }
  if (req.op === "send") {
    const text = String(req.text || "").slice(0, 2000);
    const images = (Array.isArray(req.images) ? req.images : []).filter((p) => typeof p === "string" && fs.existsSync(p));
    if (!text && !images.length) return { ok: false, reason: "nothing to send" };
    for (const p of images) {
      const r = await bot.sendImage(p, { dryRun: DRY_RUN });
      if (!r.ok) return r;
      core.recordSend();
    }
    let replied = false;
    if (text) {
      if (req.reply_to) {
        const before = keyedChat(chatId, (await bot.readChat().catch(() => null))?.messages || []);
        const m = before.find((x) => x.key === String(req.reply_to));
        if (m && Number.isInteger(m.idx)) replied = await bot.startReply(m.idx).catch(() => false);
      }
      const r = await bot.sendText(text, { dryRun: DRY_RUN });
      if (!r.ok) {
        if (replied) await bot.cancelReply().catch(() => {});
        return r;
      }
      core.recordSend();
    }
    await delay(700);
    const chat = await bot.readChat().catch(() => null);
    const messages = keyedChat(chatId, chat?.messages || []);
    let key = "";
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].mine && (!text || messages[i].text.includes(text.slice(0, 40)))) { key = messages[i].key; break; }
    }
    return { ok: true, messages, sent: key, replied: req.reply_to ? replied : undefined };
  }
  if (req.op === "react") {
    const chat = await bot.readChat().catch(() => null);
    const messages = keyedChat(chatId, chat?.messages || []);
    const index = messages.findIndex((m) => m.key === String(req.key || ""));
    if (index < 0) return { ok: false, reason: "that message is not on Instagram's page any more" };
    const r = await bot.react(Number.isInteger(messages[index].idx) ? messages[index].idx : index, String(req.emoji || ""));
    if (!r.ok) return r;
    const after = keyedChat(chatId, (await bot.readChat().catch(() => null))?.messages || []);
    return { ok: true, reactions: (after.find((m) => m.key === req.key) || after[index] || {}).reactions || [] };
  }
  if (req.op === "unsend") {
    const chat = await bot.readChat().catch(() => null);
    const messages = keyedChat(chatId, chat?.messages || []);
    const m = messages.find((x) => x.key === String(req.key || ""));
    if (!m || !Number.isInteger(m.idx)) return { ok: false, reason: "that message is not on the page any more" };
    return await bot.unsend(m.idx);
  }
  return { ok: false, reason: `unknown request ${req.op}` };
}

async function processPanel() {
  while (core.panelQueue.length) {
    const req = core.panelQueue.shift();
    let out;
    try { out = await panelRequest(req); } catch (e) { out = { ok: false, reason: (e && e.message) || String(e) }; }
    core.tellPython({ kind: "panel_result", id: req.id, ...out });
  }
}

// ── Message requests, followers ──────────────────────────────────────────────

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
  const r = await bot.answerRequest(waiting[0], true);
  if (r.ok) console.log(`${TAG} Accepted ${waiting[0].name}'s message request.`);
  else console.warn(`${TAG} Did not accept ${waiting[0].name}'s message request: ${r.reason}.`);
}

let nextFollowBack = Date.now() + 10 * 60 * 1000;
async function maybeFollowBack() {
  if ((!FOLLOW_BACK && !ACCEPT_FOLLOWS) || outBusy || Date.now() < nextFollowBack) return;
  nextFollowBack = Date.now() + (30 + Math.random() * 40) * 60 * 1000;
  outJob("following back", async () => {
    if (ACCEPT_FOLLOWS) {
      const let_in = await bot.acceptFollowRequests(2 + Math.floor(Math.random() * 2)).catch(() => []);
      if (let_in.length) console.log(`${TAG} Let ${let_in.map((h) => `@${h}`).join(", ")} follow it.`);
    }
    if (FOLLOW_BACK) {
      const done = await bot.followBack(1 + Math.floor(Math.random() * 2)).catch(() => []);
      if (done.length) console.log(`${TAG} Followed back ${done.map((h) => `@${h}`).join(", ")}.`);
    }
    await bot.openInbox();
  });
}

// ── Comments on its own posts (public replies) ───────────────────────────────

let commentTimes = [];
const commentAllowed = () => {
  commentTimes = commentTimes.filter((t) => Date.now() - t < 3600000);
  return commentTimes.length < COMMENTS_PER_HOUR;
};
const commentSent = () => commentTimes.push(Date.now());

let nextComments = Date.now() + 3 * 60 * 1000;
async function maybeComments() {
  if (!COMMENTS || Date.now() < nextComments || !commentAllowed()) return;
  nextComments = Date.now() + (8 + Math.random() * 8) * 60 * 1000;
  const ledger = readJson(COMMENTS_FILE, { posts: {} });
  ledger.posts = ledger.posts || {};
  const posts = await bot.ownPosts(COMMENTS_POSTS).catch(() => []);
  for (const post of posts) {
    const comments = await bot.readComments(post.url, await bot.sidePage()).catch(() => []);
    const seen = new Set(ledger.posts[post.id] || []);
    const first = !ledger.posts[post.id];
    for (const c of comments) {
      const key = `${c.username}|${c.text}`.slice(0, 300);
      if (seen.has(key)) continue;
      seen.add(key);
      // The comments already there when it started watching this post are its past: not answered.
      if (first || !c.username || c.username === USERNAME || c.mine) continue;
      core.handOver({
        id: randomUUID(), kind: "comment", user_id: chatIdFor(c.username), user_name: `@${c.username}`,
        channel_id: `comment_${post.id}`, content: c.text, video: post.url,
        comment: { username: c.username, text: c.text },
      });
    }
    ledger.posts[post.id] = [...seen].slice(-400);
    await delay(2000 + Math.random() * 3000);
  }
  writeJson(COMMENTS_FILE, ledger);
}

/** A public reply to a comment under its own post. */
async function replyComment(val, text) {
  const url = val.video || "";
  const want = val.comment || {};
  if (!url) return { ok: false, reason: "which post?" };
  const page = await bot.sidePage();
  const comments = await bot.readComments(url, page).catch(() => []);
  const c = comments.find((x) => x.username === want.username && x.text === want.text);
  if (!c) return { ok: false, reason: "the comment is not there any more" };
  return await bot.replyToComment(url, c.index, text, { dryRun: DRY_RUN, page });
}

// ── The out tab: one thing at a time ─────────────────────────────────────────

let outBusy = "";
let outStop = false;

function outJob(name, fn) {
  if (outBusy) return false;
  outBusy = name;
  outStop = false;
  Promise.resolve().then(fn)
    .catch((e) => console.warn(`${TAG} ${name}: ${e.message}`))
    .finally(() => { outBusy = ""; outStop = false; });
  return true;
}

async function outNow(name, fn, { interrupt = true, waitMs = 45000 } = {}) {
  const until = Date.now() + waitMs;
  if (outBusy && interrupt) outStop = true;
  while (outBusy && Date.now() < until) await delay(500);
  if (outBusy) return { ok: false, reason: `Instagram is busy (${outBusy}); try again in a minute`, busy: true };
  outBusy = name;
  outStop = false;
  try {
    return await fn();
  } finally {
    outBusy = "";
  }
}

async function freeOut(waitMs = 30000) {
  const until = Date.now() + waitMs;
  if (outBusy) outStop = true;
  while (outBusy && Date.now() < until) await delay(500);
  return !outBusy;
}

/** What it keeps about going out: stories seen, posts it has liked or commented on, reels it saw. */
let outLedger = null;
function ledger() {
  if (!outLedger) {
    outLedger = readJson(OUT_FILE, {});
    for (const k of ["stories", "engaged"]) outLedger[k] = outLedger[k] || {};
  }
  return outLedger;
}
function saveLedger() {
  const l = ledger();
  const weekAgo = Date.now() - 7 * 86400000;
  for (const [who, at] of Object.entries(l.stories)) if (at < weekAgo) delete l.stories[who];
  const engaged = Object.entries(l.engaged).sort((a, b) => b[1] - a[1]).slice(0, 400);
  l.engaged = Object.fromEntries(engaged);
  try { writeJson(OUT_FILE, l); } catch { /* next time */ }
}

const codeOf = (url) => (String(url || "").match(/\/(?:p|reel|reels|tv)\/([A-Za-z0-9_-]{5,24})/) || [])[1] || "";

// What was shared in DMs, waiting to be liked or commented on (Settings, Likes and comments).
const sentQueue = [];

/** Someone wrote: when (for their posts and their stories), and what they shared, for the jobs below. */
function noteWrote(chatId, fresh) {
  const known = loadContacts();
  if (known[chatId]) {
    known[chatId].wrote = Date.now() / 1000;
    saveContacts();
  }
  for (const m of fresh) {
    const url = m.media?.url || "";
    const code = codeOf(url);
    if (code && (LIKE_SENT || COMMENT_SENT) && !ledger().engaged[code]) {
      // Seen and done a little after, as a person watches it first.
      sentQueue.push({ url, chat: chatId, at: Date.now() + (40 + Math.random() * 200) * 1000 });
    }
  }
  while (sentQueue.length > 20) sentQueue.shift();
}

/** The stories of theirs it just watched, kept so a DM with them can bring one up. */
function noteStorySeen(chatId, seen) {
  if (!Array.isArray(seen) || !seen.length) return;
  const known = loadContacts();
  const c = known[chatId];
  if (!c) return;
  const last = seen[seen.length - 1];
  const who = usernameOf(chatId).replace(/\./g, "-");
  c.story_seen = `story_${who}_${last.id}`;
  c.story_at = Date.now() / 1000;
  saveContacts();
  ledger().stories[usernameOf(chatId)] = Date.now();
  saveLedger();
  // Python watches it properly, so what was in it is known when it comes up.
  for (const s of seen.slice(-2)) core.tellPython({ kind: "story", chat: chatId, url: s.url });
}

// ── Their posts and their stories ────────────────────────────────────────────

let nextPostsLook = Date.now() + 2 * 60 * 1000;
async function maybeTheirPosts() {
  if (!THEIR_POSTS || outBusy || Date.now() < nextPostsLook) return;
  nextPostsLook = Date.now() + (4 + Math.random() * 4) * 60 * 1000;
  const now = Date.now() / 1000;
  const known = loadContacts();
  const due = Object.entries(known)
    .filter(([id, c]) => c && c.wrote && now - c.wrote < 3 * 86400 && now - (c.posts_at || 0) > 6 * 3600 && usernameOf(id))
    .sort((a, b) => (b[1].wrote || 0) - (a[1].wrote || 0))[0];
  if (!due) return;
  const [chatId] = due;
  const username = usernameOf(chatId);
  outJob(`looking at @${username}'s posts`, async () => {
    const posts = await bot.profilePosts(username, 6);
    const c = loadContacts()[chatId];
    if (!c) return;
    if (!posts.length) {
      c.posts_at = Date.now() / 1000 - 5 * 3600;
      saveContacts();
      return;
    }
    const before = c.newest || "";
    const newest = (posts.find((p) => !p.pinned) || posts[0])?.url || "";
    Object.assign(c, { posts: posts.map(({ id, kind, url, caption, pinned, cover }) => ({ id, kind, url, caption, pinned, cover })),
                       posts_at: Date.now() / 1000, newest });
    saveContacts();
    if (!newest || newest === before) return;
    core.tellPython({ kind: "posts", chat: chatId, newest, fresh: !!before });
    const code = codeOf(newest);
    if (before && LIKE_THEIRS && budget.allowed("likes") && code && !ledger().engaged[code]) {
      await delay((20 + Math.random() * 60) * 1000);
      const r = await bot.likePost(newest, { dryRun: DRY_RUN });
      if (r.ok && !r.already && !r.dry) budget.spend("likes");
      if (r.ok) console.log(`${TAG} Liked @${username}'s new post${r.dry ? " (dry run)" : ""}.`);
      ledger().engaged[code] = Date.now();
      saveLedger();
    }
    if (before && COMMENT_THEIRS && budget.allowed("comments")) {
      core.handOver({ id: randomUUID(), kind: "post_comment", user_id: chatId, user_name: c.name || `@${username}`,
                      channel_id: `post_${code || "x"}`, content: "", video: newest, why: "theirs" });
    }
  });
}

const STORY_COOLDOWN_MS = 5 * 3600 * 1000;
let nextStoriesLook = Date.now() + 4 * 60 * 1000;
async function maybeTheirStories() {
  if (!STORIES_WATCH || outBusy || Date.now() < nextStoriesLook || core.inQuietHours()) return;
  nextStoriesLook = Date.now() + (6 + Math.random() * 6) * 60 * 1000;
  const now = Date.now() / 1000;
  const known = loadContacts();
  // Someone who wrote in the last three days, whose story has not been watched for a few hours.
  const due = Object.entries(known)
    .filter(([id, c]) => c && c.wrote && now - c.wrote < 3 * 86400 && usernameOf(id)
                         && Date.now() - (ledger().stories[usernameOf(id)] || 0) > STORY_COOLDOWN_MS)
    .sort((a, b) => (b[1].wrote || 0) - (a[1].wrote || 0))
    .slice(0, 5);
  if (!due.length) return;
  for (const [chatId] of due) {
    const username = usernameOf(chatId);
    const p = await bot.profileInfo(username).catch(() => null);
    if (!p || !p.has_story) {
      // Looked at anyway, so it is not asked about again in a minute.
      ledger().stories[username] = Date.now() - STORY_COOLDOWN_MS + 30 * 60 * 1000;
      saveLedger();
      await delay(900 + Math.random() * 1200);
      continue;
    }
    outJob(`watching @${username}'s story`, async () => {
      const seen = await bot.watchStories(username, { dryRun: DRY_RUN });
      if (!seen.ok) return;
      noteStorySeen(chatId, seen.seen);
      console.log(`${TAG} Watched @${username}'s story (${seen.seen.length})${DRY_RUN ? " (dry run)" : ""}.`);
      // Optionally a word back about it, which Python writes (kind "story_reply").
      if (STORIES_REPLY && budget.allowed("story_replies") && Math.random() < 0.4) {
        const last = seen.seen[seen.seen.length - 1];
        core.handOver({ id: randomUUID(), kind: "story_reply", user_id: chatId,
                        user_name: loadContacts()[chatId]?.name || `@${username}`,
                        channel_id: chatId, content: "", story: last?.url || "" });
      }
    });
    return;
  }
}

/** The persona's answers to a story, as Python writes them: said in the story's own reply box. */
async function drainStoryReplies() {
  if (outBusy) return;
  const waiting = Object.entries(core.responses()).find(([, v]) => v && v.kind === "story_reply");
  if (!waiting) return;
  if (!budget.allowed("story_replies")) {
    core.take(waiting[0]);
    return;
  }
  const val = core.take(waiting[0]);
  if (!val || !val.text) return;
  const username = usernameOf(String(val.chat || ""));
  if (!username) return;
  outJob(`answering @${username}'s story`, async () => {
    const opened = await bot.watchStories(username, { max: 1, dryRun: DRY_RUN });
    if (!opened.ok) return;
    const r = await bot.replyToStory(String(val.text).slice(0, 300), { dryRun: DRY_RUN });
    if (r.ok && !r.dry) budget.spend("story_replies");
    console.log(r.ok ? `${TAG} Answered @${username}'s story${r.dry ? " (dry run)" : ""}: ${val.text}`
                     : `${TAG} Did not answer @${username}'s story: ${r.reason}.`);
  });
}

// ── What people send it: liked, commented on ─────────────────────────────────

async function maybeEngageSent() {
  if (outBusy || !sentQueue.length || sentQueue[0].at > Date.now()) return;
  const item = sentQueue.shift();
  const code = codeOf(item.url);
  if (!code || ledger().engaged[code]) return;
  ledger().engaged[code] = Date.now();
  saveLedger();
  outJob("liking a post it was sent", async () => {
    if (LIKE_SENT && budget.allowed("likes")) {
      const r = await bot.likePost(item.url, { dryRun: DRY_RUN });
      if (r.ok && !r.already && !r.dry) budget.spend("likes");
      if (!r.ok) console.warn(`${TAG} Did not like a post it was sent: ${r.reason}.`);
    }
    if (COMMENT_SENT && budget.allowed("comments")) {
      const c = loadContacts()[item.chat] || {};
      core.handOver({ id: randomUUID(), kind: "post_comment", user_id: item.chat,
                      user_name: c.name || `@${usernameOf(item.chat)}`,
                      channel_id: `post_${code}`, content: "", video: item.url, why: "sent" });
    }
  });
}

/** The persona's comments under other people's posts, as Python writes them, within the day's comments. */
async function drainPostComments() {
  if (outBusy) return;
  const waiting = Object.entries(core.responses()).find(([, v]) => v && v.kind === "post_comment");
  if (!waiting) return;
  if (!budget.allowed("comments")) {
    core.take(waiting[0]);
    console.log(`${TAG} Not commenting: today's comments are used up.`);
    return;
  }
  const val = core.take(waiting[0]);
  if (!val || !val.video || !val.text) return;
  outJob("commenting", async () => {
    const r = await bot.commentOnPost(val.video, val.text, { dryRun: DRY_RUN });
    if (r.ok && !r.dry) budget.spend("comments");
    console.log(r.ok ? `${TAG} Commented on ${val.video}${r.dry ? " (dry run)" : ""}: ${val.text}`
                     : `${TAG} Did not comment on ${val.video}: ${r.reason}.`);
  });
}

// ── Reels, now and then ──────────────────────────────────────────────────────

let nextReels = Date.now() + (20 + Math.random() * 40) * 60 * 1000;
async function maybeReels() {
  if (!REELS || outBusy || Date.now() < nextReels || core.inQuietHours() || !budget.allowed("reels")) return;
  nextReels = Date.now() + (90 + Math.random() * 150) * 60 * 1000;
  outJob("scrolling Reels", reelsSession);
}

/** A few minutes on Reels: each one watched a few seconds, some liked, the best kept to talk about. */
async function reelsSession() {
  const first = await bot.reels();
  if (!first) return;
  budget.spend("reels");
  const until = Date.now() + REELS_MINUTES * 60000 * (0.7 + Math.random() * 0.6);
  const pool = readJson(SEEN_FILE, []);
  const ids = new Set(pool.map((v) => v.id));
  let told = 0, watched = 0, liked = 0;
  console.log(`${TAG} Scrolling Reels for about ${REELS_MINUTES} min${DRY_RUN ? " (dry run)" : ""}.`);
  while (Date.now() < until && !outStop) {
    const v = await bot.reelNow();
    if (v && v.id && !ids.has(v.id)) {
      ids.add(v.id);
      watched++;
      await delay((Math.random() < 0.25 ? 15 + Math.random() * 20 : 4 + Math.random() * 9) * 1000);
      let likedIt = false;
      if (!v.liked && Math.random() * 100 < REELS_LIKE_PERCENT && budget.allowed("likes")) {
        const r = await bot.reelLike(v.id, { dryRun: DRY_RUN });
        likedIt = r.ok;
        if (r.ok && !r.dry) budget.spend("likes");
        if (r.ok) liked++;
      }
      pool.push({ id: v.id, url: v.url, handle: v.handle, caption: v.caption, liked: likedIt, at: Date.now() / 1000 });
      // Two a session watched properly by Python, to have things to talk about: the liked ones first.
      if (told < 2 && v.url && (likedIt || Math.random() < 0.15)) {
        core.tellPython({ kind: "seen_video", url: v.url, liked: likedIt });
        told++;
      }
    }
    await bot.reelNext();
  }
  try { writeJson(SEEN_FILE, pool.slice(-50)); } catch { /* next session */ }
  await bot.goto("about:blank", await bot.outPage()).catch(() => {});
  console.log(`${TAG} Reels: ${watched} watched, ${liked} liked.`);
}

// ── Its Note ─────────────────────────────────────────────────────────────────

let nextNote = Date.now() + 5 * 60 * 1000;
async function maybeNote() {
  if (!NOTES || outBusy || Date.now() < nextNote || core.inQuietHours()) return;
  nextNote = Date.now() + NOTES_HOURS * 3600 * 1000 * (0.8 + Math.random() * 0.4);
  core.handOver({ id: randomUUID(), kind: "note", user_id: "note", user_name: "its Note",
                  channel_id: "note", content: "" });
}

/** The Note Python wrote, put up. */
async function drainNote() {
  const waiting = Object.entries(core.responses()).find(([, v]) => v && v.kind === "note");
  if (!waiting) return;
  const val = core.take(waiting[0]);
  if (!val || !val.text) return;
  if (DRY_RUN) {
    console.log(`${TAG} (dry run) would have set its Note: ${val.text}`);
    return;
  }
  const r = await bot.setNote(String(val.text).slice(0, 60));
  console.log(r.ok ? `${TAG} Note set: ${r.note}` : `${TAG} Note not set: ${r.reason}.`);
}

// ── Night: Instagram's activity status off ───────────────────────────────────

let activityShown = null;
let nextActivityLook = Date.now() + 60 * 1000;
function inNight() {
  const m = NIGHT_HOURS.match(/^(\d{1,2})\s*-\s*(\d{1,2})$/);
  if (!m) return false;
  const start = +m[1] % 24, end = +m[2] % 24, h = new Date().getHours();
  return start <= end ? h >= start && h < end : h >= start || h < end;
}
async function maybeActivityStatus() {
  if (!NIGHT_ACTIVITY || Date.now() < nextActivityLook) return;
  nextActivityLook = Date.now() + 10 * 60 * 1000;
  const want = !inNight();
  if (activityShown === want) return;
  const set = await bot.setActivityStatus(want).catch(() => null);
  if (set === null) {
    console.warn(`${TAG} Instagram's settings have no activity status switch for this account; leaving it.`);
    nextActivityLook = Date.now() + 6 * 3600 * 1000;
    return;
  }
  activityShown = want;
  console.log(`${TAG} Activity status ${want ? "shown" : "hidden for the night"}.`);
}

// ── Health, sign-in, checks ──────────────────────────────────────────────────

/** What the last health check found missing, so a part seen working again can take its own warning off. */
let healthMissing = [];

async function reportHealth() {
  // The inbox is drawn a moment after the page loads - longer with the window hidden. One look eight seconds in put
  // "Instagram changed its page" on the card of an account reading its inbox fine, and it stayed until the next
  // reload. So it keeps looking, for up to half a minute, and says nothing unless the part is still not there.
  let h = await bot.selectorHealth().catch(() => null);
  for (let waited = 0; h && h.missing.length && waited < 25000; waited += 2500) {
    await delay(2500);
    h = await bot.selectorHealth().catch(() => null);
  }
  if (h && h.missing.length) {
    healthMissing = [...h.missing];
    const said = { threadLink: "the conversation list", threadList: "the conversation list", composer: "the message box",
                   message: "the messages" };
    core.setState("ready", `Running, but Instagram changed its page: ${h.missing.map((m) => said[m] || m).join(" and ")} not found. Replies may fail.`);
  } else if (h && core.state === "ready") {
    // Everything found again: a warning from an earlier look comes off the card.
    healthMissing = [];
    core.setState("ready");
  }
}

/**
 * The inbox was just read, so whatever a health check said about the conversation list was a page caught before it
 * had drawn: that warning comes off now rather than at the next reload. The message box and the messages are only
 * proven by an open conversation, so warnings about them are left to their own check.
 */
function listSeenWorking() {
  if (!healthMissing.length || !healthMissing.every((m) => m === "threadLink" || m === "threadList")) return;
  healthMissing = [];
  if (core.state === "ready") core.setState("ready");
}

/** Signed out, and signing in again did not work (the account suspended, the login refused): the card keeps saying
 *  why, and it looks again later. It used to read on regardless, and finding no inbox on the page Instagram showed
 *  instead, it told the card Instagram had changed its page, for an account Instagram had suspended. The panel's
 *  requests meanwhile are answered at once rather than left to time out. */
async function waitSignedOut() {
  const hours = signInState === "suspended" ? 6 : 0.5;
  console.log(`${TAG} Not signed in to Instagram; it looks again in ${hours >= 1 ? `${hours} hours` : "half an hour"}.`);
  const until = Date.now() + hours * 3600 * 1000;
  while (Date.now() < until) {
    core.heartbeatState();
    while (core.panelQueue.length) {
      const req = core.panelQueue.shift();
      core.tellPython({ kind: "panel_result", id: req.id, ok: false, reason: "It is not signed in to Instagram right now" });
    }
    await core.sleepOrPoke(30000);
  }
}

/** A code typed in the panel, waited for; "" when nobody types one in time. */
async function waitForCode(waitMs = 10 * 60 * 1000) {
  codeWanted = true;
  codeWaiting = "";
  core.tellPython({ kind: "attention", what: "code" });
  const until = Date.now() + waitMs;
  while (Date.now() < until) {
    await processPanel().catch(() => {});
    if (codeWaiting) {
      const code = codeWaiting;
      codeWaiting = "";
      codeWanted = false;
      return code;
    }
    await delay(2000);
  }
  codeWanted = false;
  return "";
}

/**
 * Sign in, with what config/.env holds. The window comes up while Instagram wants a person (a check, a code), and
 * goes back off the screen after. True once it is in.
 */
// How the last sign-in ended ("done", "suspended", "bad_login", ...): how long to wait before looking again.
let signInState = "";

async function signInNow() {
  core.setState("logging-in", `Signing in as @${USERNAME}`);
  const r = await bot.signIn({
    password: PASSWORD,
    totpKey: TOTP_KEY,
    onState: (state, detail) => {
      const shown = { "opening": "starting", "signing-in": "logging-in", "two-factor": "logging-in",
                      "needs-code": "needs-you", "needs-you": "needs-you", "checking": "logging-in" }[state] || "logging-in";
      core.setState(shown, detail);
      console.log(`${TAG} ${detail || state}`);
    },
    getCode: async () => {
      core.setState("needs-you", "Instagram sent a code to the account's email or phone. Type it on the Accounts page.");
      await showIfHidden();
      const code = await waitForCode();
      if (!code) console.warn(`${TAG} No code was typed in; trying the sign-in again.`);
      return code;
    },
    onPerson: async (what) => {
      core.setState("needs-you", what === "captcha"
        ? "Instagram put up a check. Solve it in its window."
        : "Instagram needs you in its window.");
      core.tellPython({ kind: "attention", what: "captcha" });
      await bot.waitForPerson(async () => !(await bot.captchaShown().catch(() => false)), { timeoutMs: 15 * 60 * 1000 });
      return true;
    },
  });
  signInState = r.ok ? "done" : String(r.state || "failed");
  if (r.ok) {
    if (HIDDEN) await hideIfHidden();
    core.setState("ready");
    return true;
  }
  const why = {
    suspended: "Instagram has suspended this account. Nothing here can undo that; it looks again every 6 hours.",
    bad_login: `Instagram did not take the login: ${r.reason}. Check the password on the Accounts page.`,
    needs_code: "Instagram wants a code from the account's email or phone. Type it on the Accounts page.",
    captcha: "Instagram put up a check only a person can solve. Solve it in its window.",
  }[r.state] || `Instagram would not let it in: ${r.reason}`;
  core.setState(r.state === "suspended" ? "logged-out" : "needs-you", why);
  console.error(`${TAG} ${why}`);
  return false;
}

// The window is brought up only while a person is needed, and put back after.
let windowUp = false;
async function showIfHidden() {
  if (!HIDDEN || windowUp) return;
  await showWindow(bot.page).catch(() => {});
  windowUp = true;
}
async function hideIfHidden() {
  if (!HIDDEN || !windowUp) return;
  await hideWindow(bot.page).catch(() => {});
  windowUp = false;
}

async function checkCaptcha() {
  if (!(await bot.captchaShown().catch(() => false))) return;
  core.setState("needs-you", "Instagram wants a check solved. Solve it in its window.");
  core.tellPython({ kind: "attention", what: "captcha" });
  console.warn(`${TAG} Instagram put up a check. Solve it in its window.`);
  await showIfHidden();
  await bot.waitForPerson(async () => !(await bot.captchaShown().catch(() => false)));
  await hideIfHidden();
  core.setState("ready");
}

/** A new message in the list wakes the loop at once, instead of at its next look. */
let listChanged = false;
async function watchList() {
  try {
    await bot.page.exposeFunction("__llmPoke", () => {
      listChanged = true;
      core.wakeNow();
    });
  } catch { /* already exposed */ }
  await Promise.resolve().then(() => bot.page.evaluate((sels) => {
    if (window.__llmWatching) return;
    window.__llmWatching = true;
    let last = 0;
    const poke = () => {
      if (Date.now() - last < 2000) return;
      last = Date.now();
      try { window.__llmPoke?.(); } catch { /* not exposed here */ }
    };
    const watch = () => {
      const link = sels.map((s) => document.querySelector(s)).find(Boolean);
      if (!link) return false;
      // The list, not the whole page: Instagram's own stories bar never stops moving.
      let list = link;
      for (let i = 0; i < 6 && list.parentElement; i++) {
        list = list.parentElement;
        if (list.querySelectorAll('a[href^="/direct/t/"]').length > 1) break;
      }
      new MutationObserver(poke).observe(list, { childList: true, subtree: true, characterData: true });
      return true;
    };
    if (!watch()) { const t = setInterval(() => { if (watch()) clearInterval(t); }, 3000); }
  }, SEL.threadLink)).catch(() => {});
}

/** A quarter of a second of silence as a WAV file: what the fake microphone holds until there is a voice note. */
function silentWav(seconds = 0.25, rate = 16000) {
  const samples = Math.round(seconds * rate);
  const buf = Buffer.alloc(44 + samples * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + samples * 2, 4); buf.write("WAVE", 8);
  buf.write("fmt ", 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write("data", 36); buf.writeUInt32LE(samples * 2, 40);
  return buf;
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  if (!USERNAME) {
    console.error(`${TAG} No Instagram account ${ACCOUNT}: add one on the Accounts page.`);
    process.exit(1);
  }
  if (!fs.existsSync(PROFILE_DIR)) {
    // Its browser profile IS its login: a person made it by signing in, in a window. A password is optional and
    // only lets it sign itself back in later; without the profile there is nothing to run.
    console.error(`${TAG} Instagram account ${ACCOUNT} (@${USERNAME}) has not been signed in.`
                  + " Sign it in on the Accounts page.");
    core.ensureFiles();
    core.setState("needs-you", "It has not been signed in yet. Sign it in on the Accounts page.");
    process.exit(4);                 // a person has to: not started again by itself (snapchat_runner.js)
  }
  bot = new InstagramBot({ account: ACCOUNT, username: USERNAME, dataDir: DATA_DIR, locale: LOCALE,
                           timezone: TIMEZONE, tag: TAG });
  dropInvented();
  core.setState("starting", "launching the browser");
  console.log(`${TAG} Starting @${USERNAME} (account #${ACCOUNT})${HIDDEN ? ", window hidden" : ""}${DRY_RUN ? ", DRY RUN: nothing is sent" : ""}.`);
  // A voice note is played into the page through a fake microphone, which Chrome only takes at launch.
  const args = VOICE_NOTES
    ? ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
       `--use-file-for-fake-audio-capture=${VOICE_FILE}%noloop`]
    : [];
  if (VOICE_NOTES) {
    fs.mkdirSync(path.dirname(VOICE_FILE), { recursive: true });
    if (!fs.existsSync(VOICE_FILE)) fs.writeFileSync(VOICE_FILE, silentWav());
  }
  await bot.launch({ profileDir: PROFILE_DIR, hidden: HIDDEN, proxy: core.text("PROXY"), args });

  core.ensureFiles();
  core.connectWake();
  core.setState("starting", "opening the inbox");
  for (let attempt = 1; ; attempt++) {
    try {
      await bot.openInbox();
      if (!(await bot.isLogged()) && !(await signInNow())) {
        if (signInState === "suspended") {
          await waitSignedOut();
          attempt = 0;
          continue;
        }
        // Nothing here can fix it: the panel says what, and the supervisor tries again later.
        await delay(60000);
        process.exit(3);
      }
      await bot.openInbox();
      await checkCaptcha();
      await recordIdentity();
      break;
    } catch (e) {
      if (attempt >= 4) throw e;
      console.warn(`${TAG} Opening Instagram went wrong (${e.message}); trying again.`);
      await bot.ensure().catch(() => {});
      await delay(2500 * attempt);
    }
  }
  await watchList();
  core.setState("ready");
  await reportHealth();
  console.log(`${TAG} Ready. ${Math.round(core.minGap / 1000)} to ${Math.round(core.maxGap / 1000)}s between sends, at most ${core.perHour} an hour${core.quiet ? `, quiet ${core.quiet}` : ""}.`);

  let reloadDue = Date.now() + RELOAD_MS * (0.75 + Math.random() * 0.5);
  let listFailures = 0;
  while (true) {
    core.heartbeatState();
    await siteWatch.tick().catch(() => {});
    try {
      if ((await bot.ensure()) !== "ok") {
        await bot.openInbox();
        if (!(await bot.isLogged()) && !(await signInNow())) {
          await waitSignedOut();
          continue;
        }
        await watchList();
        core.setState("ready");
      }
      if (Date.now() - identityAt > 4 * 3600 * 1000) await recordIdentity().catch(() => {});
      await processPanel();
      await checkCaptcha();
      if (RELOAD_MS > 0 && Date.now() > reloadDue && !pending.size) {
        reloadDue = Date.now() + RELOAD_MS * (0.75 + Math.random() * 0.5);
        await bot.goto(`https://www.instagram.com/direct/inbox/`);
        if (!(await bot.isLogged()) && !(await signInNow())) {
          await waitSignedOut();
          continue;
        }
        await watchList();
        await reportHealth();
      }
      await drainResponses();
      await processOutgoing();

      let rows;
      try {
        await bot.openInbox();
        rows = await bot.listThreads();
        listSeenWorking();
        if (listFailures && HIDDEN && windowUp) {
          // Reading again: back off the screen, and the panel stops saying anything is wrong.
          await hideIfHidden();
          core.setState("ready");
        }
        listFailures = 0;
      } catch (e) {
        if (++listFailures >= 3) {
          listFailures = 0;
          if (!(await bot.isLogged())) {
            if (!(await signInNow())) {
              await waitSignedOut();
              continue;
            }
          } else await bot.goto(`https://www.instagram.com/direct/inbox/`);
        }
        // Hidden and still not reading after a reload and a fresh sign-in: the window comes up so there is
        // something to look at, rather than the account going quiet with nothing said. It goes back out of sight by
        // itself as soon as it reads again. Hiding is not the suspect here: a window off the screen draws and
        // answers presses exactly as one on it does (see browser.js).
        if (listFailures === 0 && HIDDEN && !windowUp) {
          await showIfHidden();
          const why = "Instagram would not read three times over, so its window is on screen to be looked at. "
            + "It goes back out of sight once it reads again.";
          core.setState("needs-you", why);
          console.warn(`${TAG} ${why}`);
        }
        await drainWindow(core.jitteredPoll());
        continue;
      }
      // Names and pictures for the panel, who is typing, and who is calling.
      for (const r of rows) {
        // A row the page gives a thread for is that thread; otherwise it is only whoever is already known under
        // the name it shows (chatOfName: a name is not a username). Anything else waits until it is opened.
        const id = r.id ? (chatOfThread(r.id) || `igg_${r.id}`) : chatOfName(r.name);
        if (!id) continue;
        await remember(id, r.name, r.avatar, r.id ? { thread: r.id } : null);
        if (r.typing) core.tellPython({ kind: "typing", chat: id });
        if (r.calling) core.tellPython({ kind: "call", chat: id, state: "ringing" });
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
      await maybeFollowBack();
      await maybeComments();
      await maybeActivityStatus();
      // Going out, each in the out tab beside the inbox, one at a time.
      await maybeEngageSent();
      await maybeTheirPosts();
      await maybeTheirStories();
      await maybeReels();
      await maybeNote();
    } catch (e) {
      console.error(`${TAG} Loop error: ${e.message}`);
    }
    await drainWindow(core.jitteredPoll());
  }
}

/** The wait between looks at the inbox, spent sending replies as they are ready and answering the panel. */
async function drainWindow(ms) {
  const started = Date.now();
  const until = started + ms;
  listChanged = false;
  while (Date.now() < until) {
    await core.sleepOrPoke(2000);
    try { await processPanel(); } catch { /* answered inside */ }
    try { await drainResponses(); } catch (e) { console.warn(`${TAG} Send error: ${e.message}`); }
    try { await drainPostComments(); } catch { /* next time */ }
    try { await drainStoryReplies(); } catch { /* next time */ }
    try { await drainNote(); } catch { /* next time */ }
    if (listChanged && Date.now() - started > 4000) break;
  }
}

main().catch((err) => {
  console.error(`${TAG} Fatal error:`, err);
  process.exit(1);
});
