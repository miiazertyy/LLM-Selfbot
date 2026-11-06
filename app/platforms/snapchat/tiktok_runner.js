/**
 * platforms/snapchat/tiktok_runner.js
 *
 * Node side of the TikTok platform: one account, in its own Chrome profile
 * (config/tiktok-<handle>-profile, made when it was signed in from the panel).
 * Reads its inbox, hands new messages to the Python bridge, and sends the
 * bridge's replies back, at a person's pace. The same files and wake socket as
 * the Snapchat runner (runner_core.js), so the same bridge serves both.
 *
 * Besides the inbox, all off unless switched on in Settings, TikTok:
 *   message requests accepted after a while,
 *   new followers followed back,
 *   new comments on the account's own videos answered (in public),
 *   its LIVE co-hosted: viewers' comments answered in the chat (and out loud,
 *   on the Python side), gifts thanked, follows welcomed,
 *   its "Activity status" hidden in the night hours.
 *
 * TIKTOK_DRY_RUN=true reads, writes replies to the log and types them, and
 * sends nothing.
 */
import dotenv from "dotenv";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { randomUUID } from "crypto";
import { patchConsole } from "./log.js";
import { createCore, createBudget, keyed, readJson, writeJson, delay } from "./runner_core.js";
import TikTokBot, { SEL, chatIdFor, handleOf, handleFromHref } from "./tiktokbot.js";
import { SiteWatch, applySiteFixes } from "./sitewatch.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: process.env.TIKTOK_DOTENV_PATH || "../../config/.env", quiet: true });
patchConsole();

const TAG = "[TikTok]";
const DATA_DIR = process.env.TIKTOK_DATA_DIR || process.env.SNAP_DATA_DIR || path.resolve(__dirname, "../../");
const ACCOUNT = parseInt(process.env.TIKTOK_ACCOUNT_INDEX || "1", 10) || 1;
const HANDLE = String(process.env[`TIKTOK_USERNAME_${ACCOUNT}`] || "").trim().replace(/^@/, "").toLowerCase();
const core = createCore({ prefix: "tiktok", env: "TIKTOK", account: ACCOUNT, dataDir: DATA_DIR, tag: TAG });

const HIDDEN = core.flag("HEADLESS", false);
const DRY_RUN = core.flag("DRY_RUN", false);
const LOCALE = core.text("LOCALE", "en-US") || "en-US";
const TIMEZONE = core.text("TIMEZONE", "");
const MONTH_FIRST = /^en-us/i.test(LOCALE);
const MAX_RECIPIENTS = core.num("MAX_RECIPIENTS", 15);
const RESPONSE_TTL_MS = Math.max(core.num("RESPONSE_TIMEOUT_MS", 90000), 120000);
const RELOAD_MS = core.num("RELOAD_INTERVAL_MS", 45 * 60 * 1000);
const ACCEPT_REQUESTS = core.flag("ACCEPT_MESSAGE_REQUESTS", false);
const FOLLOW_BACK = core.flag("FOLLOW_BACK", false);
const ACCEPT_DELAY_MIN = core.num("ACCEPT_DELAY_MIN", 300);
const ACCEPT_DELAY_MAX = core.num("ACCEPT_DELAY_MAX", 3600);
const COMMENTS = core.flag("COMMENTS", false);
const COMMENTS_PER_HOUR = core.num("COMMENTS_PER_HOUR", 10);
const COMMENTS_VIDEOS = core.num("COMMENTS_VIDEOS", 3);
const LIVE = core.flag("LIVE", false);
const LIVE_CHAT = core.flag("LIVE_CHAT", true);
const LIVE_PER_MINUTE = core.num("LIVE_PER_MINUTE", 4);
const NIGHT_ACTIVITY = core.flag("NIGHT_ACTIVITY_STATUS", false);
const NIGHT_HOURS = core.text("NIGHT_HOURS", "");
const TRIGGER = core.text("TRIGGER", "");
// Going out (Settings, TikTok): watching what is sent, their posts, likes and comments, visiting LIVEs, For You.
// Everything public is off until switched on; each has a daily limit.
const WATCH = core.flag("WATCH", true);
const THEIR_POSTS = core.flag("THEIR_POSTS", true);
const LIKE_SENT = core.flag("LIKE_SENT", false);
const LIKE_THEIRS = core.flag("LIKE_THEIRS", false);
const COMMENT_SENT = core.flag("COMMENT_SENT", false);
const COMMENT_THEIRS = core.flag("COMMENT_THEIRS", false);
const MENTIONS = core.flag("MENTIONS", false);
const VISITS = core.flag("VISITS", false);
const VISIT_CHATS = core.flag("VISITS_CHATS", true);
const VISIT_SHARED = core.flag("VISITS_SHARED", true);
const VISIT_FOLLOWING = core.flag("VISITS_FOLLOWING", false);
const VISIT_MINUTES = Math.max(1, core.num("VISIT_MINUTES", 10));
const VISIT_LINES = Math.max(0, core.num("VISIT_LINES", 3));
const VISIT_FOLLOW_HOST = core.flag("VISIT_FOLLOW_HOST", false);
const FORYOU = core.flag("FORYOU", false);
const FORYOU_MINUTES = Math.max(1, core.num("FORYOU_MINUTES", 5));
const FORYOU_LIKE_PERCENT = Math.max(0, Math.min(100, core.num("FORYOU_LIKE_PERCENT", 15)));
// TikTok's own chats: nobody there to answer.
const SYSTEM_CHATS = ["tiktok", "system notifications", "notifications système"];

const PROFILE_DIR = path.join(DATA_DIR, "config", `tiktok-${HANDLE}-profile`);
const IDENTITY_FILE = path.join(DATA_DIR, "config", `identity_tiktok_${ACCOUNT}.json`);
const PEOPLE_DIR = path.join(DATA_DIR, "cache", "tiktok_people");
const CONTACTS_FILE = path.join(PEOPLE_DIR, `contacts_${ACCOUNT}.json`);
const COMMENTS_FILE = path.join(PEOPLE_DIR, `comments_${ACCOUNT}.json`);
// What it has been doing out there: LIVEs visited and when, mentions answered, videos it saw and liked on For You.
const OUT_FILE = path.join(PEOPLE_DIR, `out_${ACCOUNT}.json`);
const SEEN_FILE = path.join(PEOPLE_DIR, `seen_${ACCOUNT}.json`);
// So many a day, whatever restarts in between (cache/tiktok_people/budget_N.json).
const budget = createBudget(path.join(PEOPLE_DIR, `budget_${ACCOUNT}.json`), {
  likes: core.num("LIKES_PER_DAY", 30), comments: core.num("COMMENTS_PER_DAY", 5), visits: core.num("VISITS_PER_DAY", 4),
  foryou: core.num("FORYOU_SESSIONS", 3), posts: core.num("POSTS_PER_DAY", 3),
});
// TikTok's picture hosts, and Google's (an account signed up with Google, before TikTok's own picture is known).
const PICTURE_HOSTS = /^https:\/\/([a-z0-9-]+\.)*(tiktokcdn(-[a-z]+)?\.com|ibyteimg\.com|byteoversea\.com|tiktokv\.com|tiktok\.com|googleusercontent\.com)\//i;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36";

// The few things that should always be on the pages it sits on, and a fix for any of its selectors without a new build
// (sitewatch.js). Only ever looked for on tabs it already has open.
applySiteFixes(SEL, "tiktok", DATA_DIR, (m) => console.log(`${TAG} ${m}`));
const siteWatch = new SiteWatch({
  core: [
    { name: "the list of chats", sel: SEL.conversationList, on: /tiktok\.com\/messages/ },
  ],
  pages: () => bot?.browser?.pages(),
  report: (missing) => core.keepSaying(missing.length ? { site: { missing } } : {}),
});

let bot = null;

// ── Who is who: names and pictures off the list, for the panel (cache/tiktok_people) ──
let contacts = null;
function loadContacts() {
  if (contacts) return contacts;
  try { contacts = JSON.parse(fs.readFileSync(CONTACTS_FILE, "utf-8")) || {}; } catch { contacts = {}; }
  return contacts;
}
function saveContacts() {
  try { writeJson(CONTACTS_FILE, contacts || {}); } catch { /* next time */ }
}
/** The handle behind a name, as learned when its conversation was last open. */
function handleByName(name) {
  const known = loadContacts();
  for (const [id, c] of Object.entries(known)) if (c && c.name === name) return handleOf(id);
  return "";
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

async function remember(chatId, name, avatar, profile = null) {
  if (!/^[A-Za-z0-9_-]{1,80}$/.test(chatId)) return;
  const known = loadContacts();
  const was = known[chatId] || {};
  const now = { ...was, name: name || was.name || "", seen: Date.now() / 1000 };
  if (profile) {
    // What their profile says, for their card: read once when they first write, again after a week.
    Object.assign(now, { bio: String(profile.bio || "").slice(0, 400), followers: profile.followers || 0,
                         verified: !!profile.verified, profiled: Date.now() / 1000 });
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
 * The account's own name, picture, bio and counts, as its TikTok profile shows them, for its card in the panel
 * (config/identity_tiktok_N.json). Read at the start, then every few hours.
 */
let identityAt = 0;
async function recordIdentity() {
  const me = await bot.whoAmI();
  if (!me) return;
  identityAt = Date.now();
  let before = {};
  try { before = JSON.parse(fs.readFileSync(IDENTITY_FILE, "utf-8")); } catch { /* first time */ }
  // Its profile not read this time (the page went away, TikTok said nothing): what was read off it before stays,
  // rather than the login's name and picture (a Google account's) replacing them.
  if (!me.profiled && before.username === me.handle && before.display_name) {
    identityAt = Date.now() - 3.5 * 3600 * 1000;          // asked again in half an hour
    return;
  }
  const stem = path.join(DATA_DIR, "config", `identity_tiktok_${ACCOUNT}`);
  let picture = before.picture || "";
  // The same picture comes back under a new signed address each time: saved again only when the file behind it changed.
  const sameFile = (a, b) => String(a || "").split("?")[0] === String(b || "").split("?")[0];
  if (me.avatar && (!picture || !sameFile(me.avatar, before.picture_url))) picture = (await savePicture(me.avatar, stem)) || picture;
  const out = { username: me.handle, display_name: me.name || before.display_name || "", picture,
                picture_url: me.avatar || before.picture_url || "", at: Date.now() / 1000 };
  for (const k of ["bio", "followers", "following", "likes", "videos", "verified", "private"]) {
    if (me[k] !== undefined) out[k] = me[k];
  }
  try { writeJson(IDENTITY_FILE, out); } catch { /* the card keeps what it had */ }
  if (me.handle && me.handle !== HANDLE) {
    console.warn(`${TAG} This profile is signed in as @${me.handle}, not @${HANDLE}.`);
  }
  if (before.username !== out.username || before.display_name !== out.display_name) {
    console.log(`${TAG} Signed in as ${out.display_name || out.username} (@${out.username}).`);
  }
}

// ── Conversations ────────────────────────────────────────────────────────────

function keyedChat(chatId, messages) {
  return keyed(chatId, messages || [], { monthFirst: MONTH_FIRST, prefix: "k" });
}

/** The conversation as it reads now, to Python, which keeps it for the panel and says what is new. */
function share(chatId, name, messages) {
  if (!core.connected() || !messages.length) return;
  core.tellPython({ kind: "transcript", chat: chatId, name: name || "", messages: messages.slice(-120) });
}

/** What a message says, for the AI: its words, and what it is when it is not words. */
function describe(m) {
  // A shared post's link, when the card gave it (bot.readChat): with it, Python watches the video (app/utils/tiktokwatch.py).
  const url = m.media?.url || (m.links || []).find((l) => /\/(video|photo)\//.test(l.url))?.url || "";
  const quote = m.quote ? `[replying to: "${m.quote.slice(0, 160)}"] ` : "";
  let said = m.text;
  if (m.kind === "video") said = `[shared a TikTok${url ? `: ${url}` : ""}${m.title ? ` (${m.title})` : ""}]${m.text ? ` ${m.text}` : ""}`;
  else if (m.kind === "live") said = `[shared a LIVE${m.title ? ` (${m.title})` : ""}]`;
  else if (m.kind === "unsupported") said = "[sent something TikTok's website can't show: a sticker, a voice note or a post, maybe]";
  else if (m.kind === "sticker") said = m.text || "[sent a sticker]";
  else if (m.kind === "clip") said = m.text || "[sent a video]";
  else if (m.kind === "photo" || m.kind === "voice") said = m.text || "";
  return said ? quote + said : said;
}

const pending = new Map();      // reply id -> { chatId, name, ts }

/** Open one conversation from the list, hand what is new in it to Python, and leave. */
async function readChat(row) {
  if (!(await bot.openRow(row))) return;
  await delay(500);
  const chat = await bot.readChat().catch(() => null);
  const handle = chat?.handle || row.handle || handleByName(row.name);
  if (!chat || !handle) {
    console.warn(`${TAG} Opened ${row.name || "a chat"} but could not tell whose it is.`);
    return;
  }
  const chatId = chatIdFor(handle);
  const name = row.name || chat.name || `@${handle}`;
  // Someone new (or not looked at for a week): their profile, once, for their card and the persona.
  const profile = !row.group && wantsProfile(chatId) ? await bot.profileInfo(handle).catch(() => null) : null;
  await remember(chatId, name, row.avatar, profile);
  const messages = keyedChat(chatId, chat.messages);
  share(chatId, name, messages);
  let lastMine = -1;
  messages.forEach((m, i) => { if (m.mine) lastMine = i; });
  const fresh = messages.slice(lastMine + 1).filter((m) => !m.mine && core.isNew(chatId, m.key));
  if (!fresh.length) return;
  // A shared video whose card did not say its link: opened to find it, so it can be watched (Settings, Watching).
  if (WATCH) {
    for (const m of fresh.filter((x) => x.kind === "video" && !x.media?.url && Number.isInteger(x.idx)).slice(0, 2)) {
      const url = await bot.resolveShared(m.idx).catch(() => "");
      if (url) m.media = { ...(m.media || {}), url };
    }
  }
  noteWrote(chatId, fresh);
  let content = fresh.map(describe).filter(Boolean).join("\n");
  // In a group, only what calls the persona by name, as on Discord's servers.
  if (row.group && TRIGGER && !new RegExp(`\\b${TRIGGER.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(content)) return;
  let image = "", audio = "", video = "";
  if (fresh.some((m) => m.kind === "photo")) image = await bot.capturePhoto(`tiktok_${ACCOUNT}_photo`).catch(() => "");
  if (fresh.some((m) => m.kind === "voice")) audio = await bot.captureVoice(`tiktok_${ACCOUNT}_voice`).catch(() => "");
  // A video they sent: watched on the Python side (app/utils/videowatch.py).
  if (fresh.some((m) => m.kind === "clip")) video = await bot.captureVideo(`tiktok_${ACCOUNT}_video`).catch(() => "");
  // A shared video's cover, for the vision model to see what it is, when nothing else came with it and there is no
  // link to watch it by.
  const shared = fresh.filter((m) => m.kind === "video" && m.media?.cover && !m.media?.url).pop();
  let cover = false;
  if (!image && shared) {
    const file = await savePicture(shared.media.cover, path.join(DATA_DIR, "config", "temp", `tiktok_${ACCOUNT}_cover_${Date.now()}`));
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
    // The picture is only a shared video's cover: not looked at when the video itself is watched.
    cover: cover || undefined,
    group: !!row.group || undefined,
    // Whether TikTok gave this chat a photo button: the persona offers a picture only where one can go.
    photo: !!chat.photoButton,
  });
  pending.set(id, { chatId, name, ts: Date.now() });
}

async function openChat(chatId, name) {
  const handle = handleOf(chatId);
  if (!handle) return false;
  return await bot.openChatWith(handle, { name });
}

// Answers sent by loops of their own, at their own pace: the account's LIVE, a LIVE it is visiting, comments under
// other people's videos (all in their own tabs).
const OWN_PACE = new Set(["live", "visit_say", "video_comment"]);

/** Send the replies Python has finished, one a send slot, opening each conversation fresh. */
async function drainResponses() {
  const now = Date.now();
  for (const [id, p] of pending) if (now - p.ts > RESPONSE_TTL_MS) pending.delete(id);
  const waiting = core.responses();
  for (const id of Object.keys(waiting)) {
    const kind = (waiting[id] && typeof waiting[id] === "object" && waiting[id].kind) || "dm";
    // A line for a LIVE it has left already is said nowhere.
    if (kind === "visit_say" && !visiting) { core.take(id); continue; }
    if (OWN_PACE.has(kind)) continue;
    // An answer to a mention goes in the out tab, once it is free; one under its own videos waits while it is live
    // (its LIVE has the side tab).
    if (kind === "comment" && (waiting[id].mention ? outBusy : liveOn)) continue;
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
        out = val.mention
          ? await outNow("answering a mention", () => replyComment(val, text, true), { interrupt: false, waitMs: 0 })
          : await replyComment(val, text);
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
    } else if (/too fast|limit/i.test(out.reason || "")) {
      // TikTok asked for a break: the reply waits, and so does everything else, for a good while.
      console.warn(`${TAG} ${out.reason}.`);
      core.putBack(id, { ...(typeof val === "object" ? val : { text, chat: chatId, name }), _attempts: attempts });
      core.recordSend();
      core.setState("ready", `${out.reason}.`);
      break;
    } else if (attempts >= 4 || /privacy|only friends|suspended|guidelines/i.test(out.reason || "")) {
      console.warn(`${TAG} Not sent to ${name}: ${out.reason || "it would not go"}.`);
    } else {
      core.putBack(id, { ...(typeof val === "object" ? val : { text, chat: chatId, name }), _attempts: attempts });
    }
  }
}

/** Messages Python sends on its own: a Reply from the panel, a nudge, a picture. One a send slot. */
async function processOutgoing() {
  const outgoing = readJson(core.files.outgoing, []);
  if (!Array.isArray(outgoing) || !outgoing.length || !core.sendAllowed()) return;
  const entry = outgoing[0];
  writeJson(core.files.outgoing, outgoing.slice(1));
  const { chat, message, image } = entry || {};
  if (!chat || (!message && !image)) return;
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

async function panelRequest(req) {
  if (req.op === "friends") {
    if (Date.now() - requestsAt > 180000) {
      requestsSeen = (await bot.messageRequests().catch(() => [])).map((r) => ({ name: r.name, username: r.handle || "",
                                                                                  avatar: r.avatar, preview: r.preview }));
      requestsAt = Date.now();
    }
    return { ok: true, requests: requestsSeen };
  }
  if (req.op === "add_friend") return await bot.follow(String(req.username || ""));
  if (req.op === "friend") {
    const r = await bot.answerRequest(String(req.name || ""), req.accept !== false);
    requestsAt = 0;
    return r;
  }
  // ── Going out, asked for by the panel or Telegram: in the out tab ──
  if (req.op === "posts") {
    // Someone's posts, looked at now (the Chats tab's TikToks).
    const chatId = String(req.chat || "");
    const handle = /^tt_[a-z0-9_-]{2,40}$/.test(chatId) ? handleOf(chatId) : "";
    if (!handle) return { ok: false, reason: "which chat?" };
    return await outNow(`looking at @${handle}'s posts`, async () => {
      const posts = await bot.profilePosts(handle, 9);
      const c = loadContacts()[chatId];
      if (c && posts.length) {
        Object.assign(c, { posts: posts.map(({ id, kind, url, caption, views, pinned, cover }) => ({ id, kind, url, caption, views, pinned, cover })),
                           posts_at: Date.now() / 1000, newest: c.newest || (posts.find((p) => !p.pinned) || posts[0]).id });
        saveContacts();
      }
      return { ok: true, posts };
    }, { interrupt: false, waitMs: 20000 });
  }
  if (req.op === "video") {
    // Like, save or comment on a video from the panel: the user's own choice, counted in the day's but never refused
    // by it.
    const url = String(req.url || "");
    const action = String(req.action || "");
    if (!idOf(url)) return { ok: false, reason: "That is not a TikTok video" };
    return await outNow(`${action === "comment" ? "commenting" : action === "save" ? "saving" : "liking"} a video`, async () => {
      if (action === "like") {
        const r = await bot.likeVideo(url, { dryRun: DRY_RUN, watchMs: 800 });
        if (r.ok && !r.already && !r.dry) budget.spend("likes");
        return r;
      }
      if (action === "save") return await bot.saveVideo(url, { dryRun: DRY_RUN, watchMs: 800 });
      if (action === "comment") {
        const r = await bot.commentOnVideo(url, String(req.text || "").slice(0, 150), { dryRun: DRY_RUN });
        if (r.ok && !r.dry) budget.spend("comments");
        return r;
      }
      return { ok: false, reason: `unknown action ${action}` };
    });
  }
  if (req.op === "visit") {
    const h = String(req.handle || "").trim().replace(/^@/, "").toLowerCase();
    if (!/^[a-z0-9._]{2,24}$/.test(h)) return { ok: false, reason: "That is not a TikTok username" };
    if (visiting === h) return { ok: true, started: true, already: true };
    const p = await bot.profileInfo(h).catch(() => null);
    if (p && !p.live) return { ok: false, reason: `@${h} is not live right now` };
    if (!(await freeOut())) return { ok: false, reason: `TikTok is busy (${outBusy}); try again in a minute` };
    outJob(`in @${h}'s LIVE`, () => visitLive(h, "asked"));
    return { ok: true, started: true };
  }
  if (req.op === "leave") {
    if (!visiting) return { ok: false, reason: "It is not in a LIVE" };
    outStop = true;
    return { ok: true };
  }
  if (req.op === "foryou") {
    if (!(await freeOut())) return { ok: false, reason: `TikTok is busy (${outBusy}); try again in a minute` };
    outJob("scrolling For You", forYouSession);
    return { ok: true, started: true };
  }
  if (req.op === "post") {
    if (!budget.allowed("posts")) return { ok: false, reason: `Already ${budget.used("posts")} posted today, the most Settings allows` };
    return await outNow("posting a video", async () => {
      const r = await bot.postVideo(String(req.file || ""), String(req.caption || ""),
                                    { privacy: String(req.privacy || "everyone"), dryRun: DRY_RUN || !!req.dry_run });
      if (r.ok && !r.dry) budget.spend("posts");
      return r;
    }, { waitMs: 60000 });
  }
  if (req.op === "out") {
    // What it is doing out there, and what is left of today's.
    const left = Object.fromEntries(Object.keys(budget.limits).map((k) => [k, budget.left(k)]));
    return { ok: true, busy: outBusy, visiting, left, used: Object.fromEntries(Object.keys(budget.limits).map((k) => [k, budget.used(k)])) };
  }
  const chatId = String(req.chat || "");
  if (!/^tt_[a-z0-9_-]{2,40}$/.test(chatId)) return { ok: false, reason: "which chat?" };
  const name = req.name || loadContacts()[chatId]?.name || "";
  if (!(await openChat(chatId, name))) return { ok: false, reason: "TikTok did not open that conversation" };
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
      // A reply to one message: TikTok's own Reply on it first, so what is typed goes as its answer.
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
    if (index < 0) return { ok: false, reason: "that message is not on TikTok's page any more" };
    // Its place among the page's messages, which is not its place in what was read (some are not messages).
    const r = await bot.react(Number.isInteger(messages[index].idx) ? messages[index].idx : index, String(req.emoji || ""));
    if (!r.ok) return r;
    const after = keyedChat(chatId, (await bot.readChat().catch(() => null))?.messages || []);
    return { ok: true, reactions: (after.find((m) => m.key === req.key) || after[index] || {}).reactions || [] };
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

// ── Message requests and followers ───────────────────────────────────────────

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
  const r = await bot.answerRequest(waiting[0].name, true);
  if (r.ok) console.log(`${TAG} Accepted ${waiting[0].name}'s message request.`);
}

let nextFollowBack = Date.now() + 10 * 60 * 1000;
async function maybeFollowBack() {
  if (!FOLLOW_BACK || Date.now() < nextFollowBack) return;
  nextFollowBack = Date.now() + (30 + Math.random() * 40) * 60 * 1000;
  const { done, refused } = await bot.followBack(2 + Math.floor(Math.random() * 2))
    .catch(() => ({ done: [], refused: [] }));
  if (done.length) console.log(`${TAG} Followed back ${done.map((h) => `@${h}`).join(", ")}.`);
  if (refused.length) {
    console.log(`${TAG} TikTok did not take following back ${refused.map((h) => `@${h}`).join(", ")}; `
      + "not trying them again today.");
  }
  await bot.openInbox();
}

// ── Comments on its own videos (public replies) ──────────────────────────────

let commentTimes = [];
const commentAllowed = () => {
  commentTimes = commentTimes.filter((t) => Date.now() - t < 3600000);
  return commentTimes.length < COMMENTS_PER_HOUR;
};
const commentSent = () => commentTimes.push(Date.now());

let nextComments = Date.now() + 3 * 60 * 1000;
async function maybeComments() {
  // Not while it is live: its LIVE is open in the same tab.
  if (!COMMENTS || liveOn || Date.now() < nextComments || !commentAllowed()) return;
  nextComments = Date.now() + (8 + Math.random() * 8) * 60 * 1000;
  const ledger = readJson(COMMENTS_FILE, { videos: {} });
  ledger.videos = ledger.videos || {};
  const videos = await bot.ownVideos(COMMENTS_VIDEOS).catch(() => []);
  for (const url of videos) {
    const vid = (url.match(/\/video\/(\d+)/) || [])[1];
    if (!vid) continue;
    const comments = await bot.readComments(url).catch(() => []);
    const seen = new Set(ledger.videos[vid] || []);
    const first = !ledger.videos[vid];
    for (const c of comments) {
      const key = `${c.handle}|${c.text}`.slice(0, 300);
      if (seen.has(key)) continue;
      seen.add(key);
      // The comments already there when it started watching this video are its past: not answered.
      if (first || !c.handle || c.handle === HANDLE) continue;
      core.handOver({
        id: randomUUID(), kind: "comment", user_id: chatIdFor(c.handle), user_name: c.name || `@${c.handle}`,
        channel_id: `comment_${vid}`, content: c.text, video: url, comment: { handle: c.handle, text: c.text },
      });
    }
    ledger.videos[vid] = [...seen].slice(-400);
    await delay(2000 + Math.random() * 3000);
  }
  writeJson(COMMENTS_FILE, ledger);
}

/** A public reply to a comment: under its own videos in the side tab, under someone else's (a mention) in the out tab. */
async function replyComment(val, text, out = false) {
  const url = val.video || "";
  const want = val.comment || {};
  if (!url) return { ok: false, reason: "which video?" };
  const page = out ? await bot.outPage() : null;
  const comments = await bot.readComments(url, page).catch(() => []);
  const c = comments.find((x) => x.handle === want.handle && x.text === want.text);
  if (!c) return { ok: false, reason: "the comment is not there any more" };
  return await bot.replyToComment(c.index, text, { dryRun: DRY_RUN, page });
}

// ── LIVE ─────────────────────────────────────────────────────────────────────

let liveOn = false;
let nextLiveLook = Date.now() + 30 * 1000;
const liveSeen = new Set();
let liveSaid = [];

async function maybeLive() {
  if (!LIVE) return;
  if (!liveOn && Date.now() < nextLiveLook) return;
  if (!liveOn) {
    nextLiveLook = Date.now() + 120 * 1000;
    liveOn = await bot.liveNow().catch(() => false);
    if (liveOn) {
      console.log(`${TAG} The account is LIVE: co-hosting.`);
      core.tellPython({ kind: "live_state", live: true });
      // What was said before it looked is not answered.
      for (const r of await bot.readLive().catch(() => [])) liveSeen.add(`${r.kind}|${r.name}|${r.text}`);
    }
    return;
  }
  const rows = await bot.readLive().catch(() => null);
  if (rows === null || (!rows.length && !(await bot.liveNow().catch(() => false)))) {
    liveOn = false;
    console.log(`${TAG} The LIVE has ended.`);
    core.tellPython({ kind: "live_state", live: false });
    return;
  }
  for (const r of rows) {
    const key = `${r.kind}|${r.name}|${r.text}`;
    if (liveSeen.has(key)) continue;
    liveSeen.add(key);
    if (liveSeen.size > 2000) liveSeen.delete(liveSeen.values().next().value);
    if (r.handle && r.handle === HANDLE) continue;
    core.tellPython({ kind: "live", event: r.kind, name: r.name, handle: r.handle, text: r.text });
  }
  // The persona's answers waiting to be said in the chat, at most so many a minute.
  for (const [id, waiting] of Object.entries(core.responses())) {
    if (!waiting || waiting.kind !== "live") continue;
    liveSaid = liveSaid.filter((t) => Date.now() - t < 60000);
    if (liveSaid.length >= LIVE_PER_MINUTE) break;
    const val = core.take(id);
    if (!val) continue;
    if (LIVE_CHAT && val.chat !== "voice") {
      const r = await bot.sendLive(String(val.text || "").slice(0, 150), { dryRun: DRY_RUN });
      if (r.ok) liveSaid.push(Date.now());
    }
  }
}

// ── The out tab: one thing at a time ─────────────────────────────────────────
// Going out (someone's posts, a video to like or comment on, a LIVE as a viewer, For You, posting) happens in a tab
// of its own while the inbox goes on being read and answered. One job at a time in it, run beside the main loop; a
// long one (a LIVE visit, a For You session) stops early when the panel needs the tab (outStop).
let outBusy = "";
let outStop = false;

/** `fn` in the out tab, in the background, when the tab is free: true when it started. */
function outJob(name, fn) {
  if (outBusy) return false;
  outBusy = name;
  outStop = false;
  Promise.resolve().then(fn)
    .catch((e) => console.warn(`${TAG} ${name}: ${e.message}`))
    .finally(() => { outBusy = ""; outStop = false; });
  return true;
}

/** `fn` in the out tab now, for the panel: what is going on there is asked to stop first (`interrupt`). */
async function outNow(name, fn, { interrupt = true, waitMs = 45000 } = {}) {
  const until = Date.now() + waitMs;
  if (outBusy && interrupt) outStop = true;
  while (outBusy && Date.now() < until) await delay(500);
  if (outBusy) return { ok: false, reason: `TikTok is busy (${outBusy}); try again in a minute`, busy: true };
  outBusy = name;
  outStop = false;
  try {
    return await fn();
  } finally {
    outBusy = "";
  }
}

/** The out tab free for something long the panel asked for (a visit, a For You session): true once it is. */
async function freeOut(waitMs = 30000) {
  const until = Date.now() + waitMs;
  if (outBusy) outStop = true;
  while (outBusy && Date.now() < until) await delay(500);
  return !outBusy;
}

/** What it keeps about going out: LIVEs visited and when, mentions seen, videos sent it that it has dealt with. */
let outLedger = null;
function ledger() {
  if (!outLedger) {
    outLedger = readJson(OUT_FILE, {});
    for (const k of ["visited", "mentions", "engaged"]) outLedger[k] = outLedger[k] || (k === "mentions" ? [] : {});
  }
  return outLedger;
}
function saveLedger() {
  const l = ledger();
  // A week of visits, the newest few hundred mentions and videos.
  const weekAgo = Date.now() - 7 * 86400000;
  for (const [h, at] of Object.entries(l.visited)) if (at < weekAgo) delete l.visited[h];
  l.mentions = l.mentions.slice(-400);
  const engaged = Object.entries(l.engaged).sort((a, b) => b[1] - a[1]).slice(0, 400);
  l.engaged = Object.fromEntries(engaged);
  try { writeJson(OUT_FILE, l); } catch { /* next time */ }
}

const idOf = (url) => (String(url || "").match(/\/(?:video|photo)\/(\d{6,25})/) || [])[1] || "";

// What was shared in DMs, waiting to be liked or commented on (Settings, Likes and comments), and LIVEs shared.
const sentQueue = [];
const liveQueue = [];

/** Someone wrote: when (for their posts and their LIVEs), and what they shared, for the jobs below. */
function noteWrote(chatId, fresh) {
  const known = loadContacts();
  if (known[chatId]) {
    known[chatId].wrote = Date.now() / 1000;
    saveContacts();
  }
  for (const m of fresh) {
    const url = m.media?.url || (m.links || []).find((l) => /\/(video|photo)\/\d+/.test(l.url))?.url || "";
    if (url && (LIKE_SENT || COMMENT_SENT) && idOf(url) && !ledger().engaged[idOf(url)]) {
      // Seen and done a little after, as a person watches it first.
      sentQueue.push({ url, chat: chatId, at: Date.now() + (40 + Math.random() * 200) * 1000 });
    }
    if (m.kind === "live" && m.media?.host && VISITS && VISIT_SHARED) liveQueue.push({ host: m.media.host, why: "shared", chat: chatId });
  }
  while (sentQueue.length > 20) sentQueue.shift();
  while (liveQueue.length > 10) liveQueue.shift();
}

// ── Their posts: what the people it talks to post ────────────────────────────

let nextPostsLook = Date.now() + 2 * 60 * 1000;
async function maybeTheirPosts() {
  if (!THEIR_POSTS || outBusy || Date.now() < nextPostsLook) return;
  nextPostsLook = Date.now() + (3 + Math.random() * 3) * 60 * 1000;
  const now = Date.now() / 1000;
  const known = loadContacts();
  // Someone who wrote in the last three days, not looked at for six hours: one profile a turn.
  const due = Object.entries(known)
    .filter(([id, c]) => c && c.wrote && now - c.wrote < 3 * 86400 && now - (c.posts_at || 0) > 6 * 3600 && handleOf(id))
    .sort((a, b) => (b[1].wrote || 0) - (a[1].wrote || 0))[0];
  if (!due) return;
  const [chatId] = due;
  outJob(`looking at @${handleOf(chatId)}'s posts`, async () => {
    const posts = await bot.profilePosts(handleOf(chatId), 6);
    const c = loadContacts()[chatId];
    if (!c) return;
    if (!posts.length) {
      // Nothing read (a private profile, a page that did not load): what was known stays, and it is asked again later.
      c.posts_at = Date.now() / 1000 - 5 * 3600;
      saveContacts();
      return;
    }
    const before = c.newest || "";
    // The newest that is not pinned: pinned ones sit first whatever their age.
    const newest = (posts.find((p) => !p.pinned) || posts[0])?.id || "";
    Object.assign(c, { posts: posts.map(({ id, kind, url, caption, views, pinned, cover }) => ({ id, kind, url, caption, views, pinned, cover })),
                       posts_at: Date.now() / 1000, newest });
    saveContacts();
    if (!newest || newest === before) return;
    const post = posts.find((p) => p.id === newest);
    // Python watches it, to know what it is; a new one since the last look (not the first look) is news.
    core.tellPython({ kind: "posts", chat: chatId, newest: post.url, fresh: !!before });
    if (before && LIKE_THEIRS && budget.allowed("likes") && !ledger().engaged[newest]) {
      await delay((20 + Math.random() * 60) * 1000);
      const r = await bot.likeVideo(post.url, { dryRun: DRY_RUN });
      if (r.ok && !r.already && !r.dry) budget.spend("likes");
      if (r.ok) console.log(`${TAG} Liked @${handleOf(chatId)}'s new post${r.dry ? " (dry run)" : ""}.`);
      ledger().engaged[newest] = Date.now();
      saveLedger();
    }
    if (before && COMMENT_THEIRS && budget.allowed("comments")) {
      core.handOver({ id: randomUUID(), kind: "video_comment", user_id: chatId, user_name: c.name || `@${handleOf(chatId)}`,
                      channel_id: `video_${newest}`, content: "", video: post.url, why: "theirs" });
    }
  });
}

// ── What people send it: liked, commented on ─────────────────────────────────

async function maybeEngageSent() {
  if (outBusy || !sentQueue.length || sentQueue[0].at > Date.now()) return;
  const item = sentQueue.shift();
  const vid = idOf(item.url);
  if (!vid || ledger().engaged[vid]) return;
  ledger().engaged[vid] = Date.now();
  saveLedger();
  outJob("liking a TikTok it was sent", async () => {
    if (LIKE_SENT && budget.allowed("likes")) {
      const r = await bot.likeVideo(item.url, { dryRun: DRY_RUN });
      if (r.ok && !r.already && !r.dry) budget.spend("likes");
      if (!r.ok) console.warn(`${TAG} Did not like a TikTok it was sent: ${r.reason}.`);
    }
    if (COMMENT_SENT && budget.allowed("comments")) {
      const c = loadContacts()[item.chat] || {};
      core.handOver({ id: randomUUID(), kind: "video_comment", user_id: item.chat, user_name: c.name || `@${handleOf(item.chat)}`,
                      channel_id: `video_${vid}`, content: "", video: item.url, why: "sent" });
    }
  });
}

/** The persona's comments under other people's videos, as Python writes them, within the day's comments. */
async function drainVideoComments() {
  if (outBusy) return;
  const waiting = Object.entries(core.responses()).find(([, v]) => v && v.kind === "video_comment");
  if (!waiting) return;
  if (!budget.allowed("comments")) {
    core.take(waiting[0]);
    console.log(`${TAG} Not commenting: today's comments are used up.`);
    return;
  }
  const val = core.take(waiting[0]);
  if (!val || !val.video || !val.text) return;
  outJob("commenting", async () => {
    const r = await bot.commentOnVideo(val.video, val.text, { dryRun: DRY_RUN });
    if (r.ok && !r.dry) budget.spend("comments");
    console.log(r.ok ? `${TAG} Commented on ${val.video}${r.dry ? " (dry run)" : ""}: ${val.text}`
                     : `${TAG} Did not comment on ${val.video}: ${r.reason}.`);
  });
}

// ── Visiting LIVEs, as a viewer ──────────────────────────────────────────────

let nextVisitLook = Date.now() + 5 * 60 * 1000;
let visiting = "";
const VISIT_COOLDOWN_MS = 6 * 3600 * 1000;
const visitedRecently = (h) => Date.now() - (ledger().visited[h] || 0) < VISIT_COOLDOWN_MS;

async function maybeVisits() {
  if (!VISITS || outBusy || Date.now() < nextVisitLook || core.inQuietHours() || !budget.allowed("visits")) return;
  nextVisitLook = Date.now() + (5 + Math.random() * 5) * 60 * 1000;
  // A LIVE shared in a DM first, then the people it talks to, then who it follows.
  let host = "";
  let why = "";
  while (liveQueue.length && !host) {
    const q = liveQueue.shift();
    if (!visitedRecently(q.host)) { host = q.host; why = "shared"; }
  }
  if (!host && VISIT_CHATS) {
    const now = Date.now() / 1000;
    const recent = Object.entries(loadContacts())
      .filter(([id, c]) => c && c.wrote && now - c.wrote < 7 * 86400 && handleOf(id) && !visitedRecently(handleOf(id)))
      .sort((a, b) => (b[1].wrote || 0) - (a[1].wrote || 0)).slice(0, 6);
    for (const [id] of recent) {
      const p = await bot.profileInfo(handleOf(id)).catch(() => null);
      if (p && p.live) { host = handleOf(id); why = "chats"; break; }
      await delay(800 + Math.random() * 1200);
    }
  }
  if (!host && VISIT_FOLLOWING) {
    outJob("looking for LIVEs", async () => {
      const live = (await bot.followingLive().catch(() => [])).filter((h) => !visitedRecently(h) && h !== HANDLE);
      if (live.length) {
        const pick = live[Math.floor(Math.random() * live.length)];
        outBusy = `in @${pick}'s LIVE`;
        await visitLive(pick, "following");
      }
    });
    return;
  }
  if (host) outJob(`in @${host}'s LIVE`, () => visitLive(host, why));
}

/**
 * Watch someone's LIVE for a while, as a viewer: greet once, answer when named, now and then a line of its own (what
 * to say is Python's, livecohost.viewer_line), a few hearts, then leave. Every line in the chat goes to Python (kind
 * "visit"), and its answers come back as "visit_say" responses.
 */
async function visitLive(host, why = "") {
  const opened = await bot.openLive(host);
  if (!opened.live) return;
  const page = await bot.outPage();
  visiting = host;
  ledger().visited[host] = Date.now();
  saveLedger();
  budget.spend("visits");
  const stay = VISIT_MINUTES * 60000 * (0.6 + Math.random() * 0.8);
  const until = Date.now() + stay;
  console.log(`${TAG} Visiting @${host}'s LIVE for ${Math.round(stay / 60000)} min${why ? ` (${why})` : ""}${DRY_RUN ? ", dry run" : ""}.`);
  core.tellPython({ kind: "visit_state", host, name: opened.name || host, on: true, why });
  if (VISIT_FOLLOW_HOST) await bot.followLiveHost().catch(() => false);
  const seen = new Set((await bot.readLive(page).catch(() => [])).map((r) => `${r.kind}|${r.name}|${r.text}`));
  // Its own lines come back in the chat, by its @handle or only by its name.
  const ownName = String(readJson(IDENTITY_FILE, {}).display_name || "").trim();
  const mine = (r) => (r.handle && r.handle === HANDLE) || (!!ownName && r.name === ownName);
  core.tellPython({ kind: "visit", host, event: "arrive", name: opened.name || host, text: "" });
  let said = [];
  let nextHearts = Date.now() + (20 + Math.random() * 60) * 1000;
  let nextCheck = Date.now() + 30000;
  try {
    while (Date.now() < until && !outStop) {
      for (const r of await bot.readLive(page).catch(() => [])) {
        const key = `${r.kind}|${r.name}|${r.text}`;
        if (seen.has(key)) continue;
        seen.add(key);
        if (seen.size > 2000) seen.delete(seen.values().next().value);
        if (mine(r)) continue;
        if (r.kind === "comment" || r.kind === "join" || r.kind === "gift") {
          core.tellPython({ kind: "visit", host, event: r.kind, name: r.name, handle: r.handle, text: r.text });
        }
      }
      // Its lines, at most so many in five minutes.
      for (const [id, waiting] of Object.entries(core.responses())) {
        if (!waiting || waiting.kind !== "visit_say") continue;
        said = said.filter((t) => Date.now() - t < 300000);
        const val = core.take(id);
        if (!val || val.host !== host || said.length >= VISIT_LINES) continue;
        await delay(core.typingTime(val.text) * 0.5);
        const r = await bot.sendLive(String(val.text || "").slice(0, 150), { dryRun: DRY_RUN, page });
        if (r.ok) {
          said.push(Date.now());
          core.tellPython({ kind: "visit_said", host, text: val.text });
        }
      }
      if (Date.now() > nextHearts) {
        nextHearts = Date.now() + (40 + Math.random() * 90) * 1000;
        if (!DRY_RUN) await bot.liveHearts(2 + Math.floor(Math.random() * 4));
      }
      if (Date.now() > nextCheck) {
        nextCheck = Date.now() + 30000;
        if (!(await bot.liveThere()).live) {
          console.log(`${TAG} @${host}'s LIVE ended.`);
          break;
        }
      }
      await delay(2500 + Math.random() * 1500);
    }
  } finally {
    visiting = "";
    core.tellPython({ kind: "visit_state", host, on: false });
    // Answers to the LIVE it left are not said anywhere else.
    for (const [id, waiting] of Object.entries(core.responses())) if (waiting?.kind === "visit_say") core.take(id);
    // Off the LIVE, so its stream stops.
    await bot.goto("about:blank", page).catch(() => {});
    console.log(`${TAG} Left @${host}'s LIVE.`);
  }
}

// ── For You, now and then ────────────────────────────────────────────────────

let nextForYou = Date.now() + (20 + Math.random() * 40) * 60 * 1000;
async function maybeForYou() {
  if (!FORYOU || outBusy || Date.now() < nextForYou || core.inQuietHours() || !budget.allowed("foryou")) return;
  // Spread over the day: a session, then a few hours.
  nextForYou = Date.now() + (90 + Math.random() * 150) * 60 * 1000;
  outJob("scrolling For You", forYouSession);
}

/** A few minutes on For You: each video watched a few seconds, some liked, the best kept to talk about. */
async function forYouSession() {
  const first = await bot.forYou();
  if (!first) return;
  budget.spend("foryou");
  const until = Date.now() + FORYOU_MINUTES * 60000 * (0.7 + Math.random() * 0.6);
  const pool = readJson(SEEN_FILE, []);
  const ids = new Set(pool.map((v) => v.id));
  let told = 0, watched = 0, liked = 0;
  console.log(`${TAG} Scrolling For You for about ${FORYOU_MINUTES} min${DRY_RUN ? " (dry run)" : ""}.`);
  while (Date.now() < until && !outStop) {
    const v = await bot.forYouNow();
    if (v && v.id && !ids.has(v.id)) {
      ids.add(v.id);
      watched++;
      // Most a few seconds, some to the end.
      await delay((Math.random() < 0.25 ? 15 + Math.random() * 20 : 4 + Math.random() * 9) * 1000);
      let likedIt = false;
      if (!v.liked && Math.random() * 100 < FORYOU_LIKE_PERCENT && budget.allowed("likes")) {
        const r = await bot.forYouLike(v.id, { dryRun: DRY_RUN });
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
    await bot.forYouNext();
  }
  try { writeJson(SEEN_FILE, pool.slice(-50)); } catch { /* next session */ }
  await bot.goto("about:blank", await bot.outPage()).catch(() => {});
  console.log(`${TAG} For You: ${watched} watched, ${liked} liked.`);
}

// ── Mentions: comments that name the account ─────────────────────────────────

let nextMentions = Date.now() + 4 * 60 * 1000;
async function maybeMentions() {
  if (!MENTIONS || outBusy || Date.now() < nextMentions) return;
  nextMentions = Date.now() + (10 + Math.random() * 8) * 60 * 1000;
  outJob("reading mentions", async () => {
    const rows = await bot.mentions();
    const l = ledger();
    const first = !l.mentions_started;
    l.mentions_started = true;
    for (const r of rows) {
      const key = `${r.handle}|${r.text}`.slice(0, 300);
      if (l.mentions.includes(key)) continue;
      l.mentions.push(key);
      // The ones there before it started looking are its past: not answered.
      if (first) continue;
      core.handOver({ id: randomUUID(), kind: "comment", user_id: chatIdFor(r.handle), user_name: r.name || `@${r.handle}`,
                      channel_id: `comment_${idOf(r.video)}`, content: r.text, video: r.video,
                      comment: { handle: r.handle, text: r.text }, mention: true });
    }
    saveLedger();
  });
}

// ── Night: TikTok's activity status off ──────────────────────────────────────

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
    console.warn(`${TAG} TikTok's settings have no Activity status switch for this account; leaving it.`);
    nextActivityLook = Date.now() + 6 * 3600 * 1000;
    return;
  }
  activityShown = want;
  console.log(`${TAG} Activity status ${want ? "shown" : "hidden for the night"}.`);
}

// ── Health, sign-in, captchas ────────────────────────────────────────────────

/** What the last health check found missing, so a part seen working again can take its own warning off. */
let healthMissing = [];

async function reportHealth() {
  // TikTok draws its inbox a moment after the page loads - longer with the window hidden and a For You tab playing
  // beside it. One look eight seconds in put "TikTok changed its page" on the card of an account reading its inbox
  // fine, and it stayed there until the next reload, three quarters of an hour later. So it keeps looking, for up to
  // half a minute, and says nothing unless the part is still not there.
  let h = await bot.selectorHealth().catch(() => null);
  for (let waited = 0; h && h.missing.length && waited < 25000; waited += 2500) {
    await delay(2500);
    h = await bot.selectorHealth().catch(() => null);
  }
  if (h && h.missing.length) {
    healthMissing = [...h.missing];
    const said = { conversationList: "the conversation list", conversation: "the conversation list", composer: "the message box" };
    core.setState("ready", `Running, but TikTok changed its page: ${h.missing.map((m) => said[m] || m).join(" and ")} not found. Replies may fail.`);
  } else if (h && core.state === "ready") {
    // Everything found again: a warning from an earlier look (a page not loaded yet) comes off the card.
    healthMissing = [];
    core.setState("ready");
  }
}

/**
 * The inbox was just read, so whatever a health check said about the conversation list was a page caught before it
 * had drawn: that warning comes off now rather than at the next reload. The message box is only proven by an open
 * conversation, so a warning about it is left to its own check.
 */
function listSeenWorking() {
  if (!healthMissing.length || !healthMissing.every((m) => m === "conversationList" || m === "conversation")) return;
  healthMissing = [];
  if (core.state === "ready") core.setState("ready");
}

/** Signed out: the window comes up for the person to sign in, and the runner carries on once they have. */
async function waitForSignIn() {
  // A closed window, or a page gone from under it, looks signed out: opened again first, and looked at again.
  if ((await bot.ensure().catch(() => "ok")) !== "ok") {
    await bot.openInbox();
    if (await bot.isLogged()) return;
  }
  core.setState("needs-login", "Sign in to TikTok in its window. It carries on once you are in.");
  console.warn(`${TAG} Not signed in. Sign in in the TikTok window; it carries on as soon as you are in.`);
  await bot.goto(`https://www.tiktok.com/login?lang=${bot.lang}`);
  await bot.waitForPerson(() => bot.hasSession());
  await delay(3000);
  await bot.openInbox();
}

async function checkCaptcha() {
  if (!(await bot.captchaShown().catch(() => false))) return;
  core.setState("needs-you", "TikTok wants a check solved. Solve it in its window.");
  core.tellPython({ kind: "attention", what: "captcha" });
  console.warn(`${TAG} TikTok put up a check (a puzzle). Solve it in its window.`);
  await bot.waitForPerson(async () => !(await bot.captchaShown().catch(() => false)));
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
  // A loose frame throws at once rather than failing its promise: nothing here is worth stopping for.
  let f;
  try { f = await bot.inbox(); } catch { return; }
  // The conversation list and the Messages count, not the whole page: the rest of TikTok's page never stops moving.
  await Promise.resolve().then(() => f.evaluate((listSels, countSels) => {
    if (window.__llmWatching) return;
    window.__llmWatching = true;
    let last = 0;
    const poke = () => {
      if (Date.now() - last < 2000) return;
      last = Date.now();
      try { (window.__llmPoke || window.parent.__llmPoke)?.(); } catch { /* not exposed here */ }
    };
    const watch = () => {
      const targets = [...listSels, ...countSels].map((s) => document.querySelector(s)).filter(Boolean);
      if (!targets.length) return false;
      const ob = new MutationObserver(poke);
      for (const t of targets) ob.observe(t.parentElement || t, { childList: true, subtree: true, characterData: true });
      return true;
    };
    // The list may not be drawn yet: looked for again until it is.
    if (!watch()) { const t = setInterval(() => { if (watch()) clearInterval(t); }, 3000); }
  }, SEL.conversationList, SEL.totalUnread)).catch(() => {});
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  // TikTok's own rule for a username; anything else would not name a profile of ours.
  if (!/^[a-z0-9_.]{2,24}$/.test(HANDLE)) {
    console.error(`${TAG} No TikTok account ${ACCOUNT}: sign one in from the Accounts page.`);
    process.exit(1);
  }
  bot = new TikTokBot({ account: ACCOUNT, handle: HANDLE, dataDir: DATA_DIR, locale: LOCALE, timezone: TIMEZONE, tag: TAG });
  core.setState("starting", "launching the browser");
  console.log(`${TAG} Starting @${HANDLE} (account #${ACCOUNT})${HIDDEN ? ", window hidden" : ""}${DRY_RUN ? ", DRY RUN: nothing is sent" : ""}.`);
  await bot.launch({ profileDir: PROFILE_DIR, hidden: HIDDEN, proxy: core.text("PROXY") });

  core.setState("starting", "opening the inbox");
  // Getting in: tried again (on a fresh page) when the page went away under it, which TikTok's own reloads do.
  for (let attempt = 1; ; attempt++) {
    try {
      await bot.openInbox();
      if (!(await bot.isLogged())) await waitForSignIn();
      await checkCaptcha();
      await recordIdentity();
      break;
    } catch (e) {
      if (attempt >= 4) throw e;
      console.warn(`${TAG} Opening TikTok went wrong (${e.message}); trying again.`);
      await bot.ensure().catch(() => {});
      await delay(2500 * attempt);
    }
  }
  core.ensureFiles();
  core.connectWake();
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
      // Its window closed, or its page went away (after a check, say): opened again, on the inbox, before anything.
      if ((await bot.ensure()) !== "ok") {
        await bot.openInbox();
        if (!(await bot.isLogged())) await waitForSignIn();
        await watchList();
        core.setState("ready");
      }
      // Its name, picture and counts, kept up to date.
      if (Date.now() - identityAt > 4 * 3600 * 1000) await recordIdentity().catch(() => {});
      await processPanel();
      await checkCaptcha();
      if (RELOAD_MS > 0 && Date.now() > reloadDue && !pending.size) {
        reloadDue = Date.now() + RELOAD_MS * (0.75 + Math.random() * 0.5);
        await bot.goto(`https://www.tiktok.com/messages?lang=${bot.lang}`);
        if (!(await bot.isLogged())) await waitForSignIn();
        await watchList();
        await reportHealth();
      }
      await drainResponses();
      await processOutgoing();
      await maybeLive();

      let rows;
      try {
        await bot.openInbox();
        rows = await bot.listConversations();
        listFailures = 0;
        listSeenWorking();
      } catch (e) {
        if (++listFailures >= 3) {
          listFailures = 0;
          if (!(await bot.isLogged())) await waitForSignIn();
          else await bot.goto(`https://www.tiktok.com/messages?lang=${bot.lang}`);
        }
        await drainWindow(core.jitteredPoll());
        continue;
      }
      // Names and pictures for the panel, and who is typing.
      for (const r of rows) {
        const handle = r.handle || handleByName(r.name);
        if (!handle) continue;
        const id = chatIdFor(handle);
        await remember(id, r.name, r.avatar);
        if (r.typing) core.tellPython({ kind: "typing", chat: id });
      }
      const targets = rows
        .filter((r) => r.unread && !r.request && !SYSTEM_CHATS.includes(String(r.name || "").toLowerCase().trim()))
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
      await maybeMentions();
      await maybeVisits();
      await maybeForYou();
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
    await core.sleepOrPoke(liveOn ? 3000 : 2000);
    try { await processPanel(); } catch { /* answered inside */ }
    try { await drainResponses(); } catch (e) { console.warn(`${TAG} Send error: ${e.message}`); }
    try { await maybeLive(); } catch { /* next time */ }
    try { await drainVideoComments(); } catch { /* next time */ }
    // Something changed on the page (a new message, most likely): look again now rather than at the end of the
    // wait, but never more often than every few seconds.
    if (listChanged && Date.now() - started > 4000) break;
  }
}

main().catch((err) => {
  console.error(`${TAG} Fatal error:`, err);
  process.exit(1);
});
