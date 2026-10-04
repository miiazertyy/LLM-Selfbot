/**
 * platforms/snapchat/snapchat_runner.js
 *
 * Node/Puppeteer side of the Snapchat platform. Logs in, polls unread chats,
 * hands new messages to the Python bridge (ipc/snap_incoming.json) and sends
 * back the AI replies it reads from ipc/snap_responses.json.
 */

import SnapBot from "./snapbot.js";
import dotenv from "dotenv";
import fs from "fs";
import net from "net";
import path from "path";
import { fileURLToPath } from "url";
import { createHash, randomUUID } from "crypto";
import { createRequire } from "module";
import { patchConsole } from "./log.js";

// .env location: explicit override (set by the Python bridge) > bundled config
// (source) > repo config (frozen, where the bridge usually set it already).
const DOTENV_PATH = process.env.SNAP_DOTENV_PATH || "../../config/.env";
// quiet: from dotenv 17 on, every config() call prints a line - 17 with an
// advert, 18 with "injected env (N) from <file>" - and this process's output
// is the panel's Logs tab. 16 ignores the option, so it is safe on whichever
// version an install actually has in node_modules.
dotenv.config({ path: DOTENV_PATH, quiet: true });
if (!process.env.SNAP_USERNAME) {
  dotenv.config({ path: ".env", quiet: true });
}

// Reformats all console output into one clean style; respects SNAP_DEBUG.
patchConsole();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONFIG_DIR = path.resolve(__dirname, "../../config");

// Writable data dir (cookies/profile/temp media). Set by the Python bridge;
// falls back to the repo layout when run standalone from source.
const DATA_DIR = process.env.SNAP_DATA_DIR || path.resolve(__dirname, "../../");

// Message IPC files live in a top-level ipc/ folder, created on startup.
const IPC_DIR = path.join(DATA_DIR, "ipc");
if (!fs.existsSync(IPC_DIR)) fs.mkdirSync(IPC_DIR, { recursive: true });

// ── Account index ─────────────────────────────────────────────────────────────
// Multi-account: SNAP_ACCOUNT_INDEX (1-based). Account 1 keeps the legacy
// unsuffixed file names/env vars; accounts 2+ get an "_N" suffix.
const ACCOUNT_INDEX = parseInt(process.env.SNAP_ACCOUNT_INDEX || "1") || 1;
const SFX = ACCOUNT_INDEX === 1 ? "" : `_${ACCOUNT_INDEX}`;

// ── IPC file paths ────────────────────────────────────────────────────────────
const INCOMING_FILE  = path.join(IPC_DIR, `snap_incoming${SFX}.json`);
const RESPONSES_FILE = path.join(IPC_DIR, `snap_responses${SFX}.json`);
const OUTGOING_FILE  = path.join(IPC_DIR, `snap_outgoing${SFX}.json`);
const PROCESSED_FILE = path.join(IPC_DIR, `snap_processed${SFX}.json`);
const PORT_FILE      = path.join(IPC_DIR, `snap_port${SFX}`);
const STATE_FILE     = path.join(IPC_DIR, `snap_state${SFX}.json`);

/**
 * Say what the runner is actually doing, for the panel.
 *
 * "Running" used to mean only that the Node process existed. Waiting on an
 * email verification, or sitting behind a dialog, looked exactly like working
 * normally - so the account read as fine while it answered nobody, and the
 * only way to find out was to read the log.
 *
 * A file rather than the wake socket: the panel reads this when someone opens
 * the page, which may be long after it was written, and it has to survive the
 * runner being busy or wedged - which is the case it exists to report.
 */
let lastState = "";
let lastDetail = "";
let lastWrite = 0;
function setState(state, detail = "") {
  if (state === lastState && !detail) return;
  lastState = state;
  lastDetail = detail;
  lastWrite = Date.now();
  try {
    fs.writeFileSync(
      STATE_FILE,
      JSON.stringify({ state, detail, at: Date.now() / 1000, account: ACCOUNT_INDEX }, null, 2),
      "utf-8",
    );
  } catch {
    /* the log still carries it */
  }
}

/**
 * Keep the panel's picture of this account current: the name it shows, its
 * username, and its Bitmoji, read off the page into
 * config/identity_snap_N.json. The Bitmoji itself, and its background when it
 * has one, are saved beside it, so the panel shows them without ever asking
 * Snapchat. Discord accounts have had this from the start; a Snapchat card
 * was a generic ghost with the login name under it.
 *
 * Called whenever the app is (back) on screen: after logging in, after a
 * refresh, after logging back in. Pictures are only fetched again when their
 * address changes.
 */
const IDENTITY_FILE = path.join(DATA_DIR, "config", `identity_snap_${ACCOUNT_INDEX}.json`);
const PICTURE_HOSTS = /^https:\/\/([a-z0-9-]+\.)*(sc-cdn\.net|bitmoji\.com|snapchat\.com)\//i;

async function savePicture(url, stem, before) {
  if (!url || !PICTURE_HOSTS.test(url)) return "";
  if (before && before.url === url && before.file && fs.existsSync(path.join(DATA_DIR, "config", before.file))) {
    return before.file;
  }
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
    if (!res.ok) return "";
    const type = res.headers.get("content-type") || "";
    const ext = type.includes("png") ? "png" : type.includes("jpeg") ? "jpg" : type.includes("svg") ? "" : "webp";
    if (!ext) return "";
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length < 100 || buf.length > 4_000_000) return "";
    const file = `${stem}.${ext}`;
    fs.writeFileSync(path.join(DATA_DIR, "config", file), buf);
    return file;
  } catch {
    return "";
  }
}

const BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36";

/**
 * The account's public Snapchat page, read the way anyone could, without the
 * signed-in session: its profile photo when it has one, and its Bitmoji and
 * the Bitmoji's background. Accounts with a public profile carry
 * publicProfileInfo; the rest carry userInfo, with no photo.
 */
async function publicProfile(username) {
  try {
    const res = await fetch(`https://www.snapchat.com/add/${encodeURIComponent(username)}`, {
      headers: { "user-agent": BROWSER_UA, "accept-language": "en-US,en;q=0.9" },
      signal: AbortSignal.timeout(20000),
    });
    if (!res.ok) return null;
    const html = await res.text();
    const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
    if (!m) return null;
    const profile = JSON.parse(m[1])?.props?.pageProps?.userProfile || {};
    const info = profile.publicProfileInfo || profile.userInfo || {};
    // Whatever shape the Bitmoji comes in: its picture, and its background.
    const urls = [];
    (function walk(v, key) {
      if (!v) return;
      if (typeof v === "string") { if (/^https:\/\//.test(v)) urls.push([key, v]); return; }
      if (typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, `${key}.${k}`);
    })(info.bitmoji3d, "bitmoji3d");
    const bitmoji = (urls.find(([k]) => /avatar/i.test(k)) || urls.find(([k, u]) => !/background/i.test(k + u)) || [])[1] || "";
    const background = (urls.find(([k, u]) => /background/i.test(k + u)) || [])[1] || "";
    return {
      name: String(info.title || info.displayName || ""),
      // Asked for at 400px: the address it gives is for 90, which is soft on a card.
      photo: String(info.profilePictureUrl || "").replace(/_RS\d+,\d+_/, "_RS0,400_"),
      bitmoji,
      background,
    };
  } catch {
    return null;
  }
}

async function recordIdentity(bot, { maxAgeHours = 0 } = {}) {
  let before = {};
  try { before = JSON.parse(fs.readFileSync(IDENTITY_FILE, "utf-8")); } catch { /* first time */ }
  if (maxAgeHours && before.username && Date.now() / 1000 - (before.at || 0) < maxAgeHours * 3600) return;
  const me = await bot.whoAmI();
  if (!me) {
    console.warn("[Snap] Could not read who is signed in from Snapchat's account page; the panel keeps what it had.");
    return;
  }
  const pub = await publicProfile(me.username);
  const stem = `identity_snap_${ACCOUNT_INDEX}`;
  const was = { url: before.picture_url, file: before.picture };
  // The profile photo first, then the Bitmoji: what Snapchat itself shows as the account's picture.
  let picture = "", kind = "", pictureUrl = "";
  if (pub?.photo) {
    picture = await savePicture(pub.photo, stem, was);
    if (picture) { kind = "photo"; pictureUrl = pub.photo; }
  }
  if (!picture && pub?.bitmoji) {
    picture = await savePicture(pub.bitmoji, stem, was);
    if (picture) { kind = "bitmoji"; pictureUrl = pub.bitmoji; }
  }
  const background = await savePicture(pub?.background || "", `${stem}_bg`, { url: before.background_url, file: before.background });
  // A picture from before that is not the picture any more goes with it.
  for (const [old, now] of [[before.picture, picture], [before.background, background]]) {
    if (old && old !== now && /^identity_snap_\d+(_bg)?\.(webp|png|jpg)$/.test(old)) {
      try { fs.unlinkSync(path.join(DATA_DIR, "config", old)); } catch { /* already gone */ }
    }
  }
  const out = {
    username: me.username,
    display_name: me.display_name || pub?.name || "",
    picture, picture_kind: kind, picture_url: pictureUrl,
    background, background_url: background ? pub.background : "",
    at: Date.now() / 1000,
  };
  try {
    const tmp = `${IDENTITY_FILE}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(out, null, 2), "utf-8");
    fs.renameSync(tmp, IDENTITY_FILE);
  } catch {
    return;
  }
  if (before.username !== out.username || before.display_name !== out.display_name || before.picture !== out.picture) {
    const pic = kind === "photo" ? "its profile photo" : kind === "bitmoji" ? "its Bitmoji" : "no picture";
    console.log(`[Snap] Signed in as ${out.display_name || out.username} (@${out.username}), with ${pic}.`);
  }
}

/**
 * The login, with the name the account has now to try next when it has been
 * renamed since the login was saved (see SnapBot.enterUsername). Only a saved
 * username is swapped: an email address or a phone number does not change
 * with a rename.
 */
function loginDetails() {
  let now = "";
  try { now = JSON.parse(fs.readFileSync(IDENTITY_FILE, "utf-8")).username || ""; } catch { /* never recorded */ }
  const saved = String(CREDENTIALS.username || "");
  const isName = !saved.includes("@") && !/^\+?\d[\d\s-]{6,}$/.test(saved);
  return { ...CREDENTIALS, alternates: now && isName && now.toLowerCase() !== saved.toLowerCase() ? [now] : [] };
}

/**
 * Rewrite the current state once a minute while running.
 *
 * States are only written when they change, so without this a healthy runner
 * that had been "ready" for ten minutes looked exactly like one that had died
 * ten minutes ago - and the panel could not tell the two apart. A fresh
 * timestamp is what "still alive" means.
 */
function heartbeatState() {
  if (!lastState || Date.now() - lastWrite < 60 * 1000) return;
  const s = lastState;
  lastState = "";                 // force the write through
  setState(s, lastDetail);
}

// ── Wake channel ─────────────────────────────────────────────────────────────
// See the matching note in snapchat_bridge.py. The JSON files above remain the
// transport; this socket carries nothing but "look again now". Both sides still
// poll underneath, so if it never connects the only thing lost is the couple of
// seconds it saves in each direction.
let wakeSock = null;
let wakeBuf = "";
let onResponsePoke = null;     // set by the drain loop

function connectWake(retry = 0) {
  const backoff = () =>
    setTimeout(() => connectWake(Math.min(retry + 1, 6)), Math.min(1000 * 2 ** retry, 15000));

  let port = NaN;
  try {
    port = parseInt(fs.readFileSync(PORT_FILE, "utf-8").trim(), 10);
  } catch {
    /* the bridge has not published one yet */
  }
  if (!Number.isInteger(port) || port <= 0) {
    backoff();
    return;
  }

  const sock = net.createConnection({ host: "127.0.0.1", port }, () => {
    wakeSock = sock;
    wakeBuf = "";
  });
  sock.on("data", (chunk) => {
    wakeBuf += chunk.toString("utf-8");
    let i;
    while ((i = wakeBuf.indexOf("\n")) >= 0) {
      const line = wakeBuf.slice(0, i);
      wakeBuf = wakeBuf.slice(i + 1);
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        continue;
      }
      if (msg && msg.kind === "response" && onResponsePoke) onResponsePoke();
      // Something the panel's Chats tab wants done: read a conversation, send a message. Done at the next point the
      // bot is between two of its own steps (see processPanel); woken now if it is only waiting.
      if (msg && msg.kind === "panel" && msg.id) {
        panelQueue.push(msg);
        if (onResponsePoke) onResponsePoke();
      }
    }
  });
  sock.on("error", () => {
    try { sock.destroy(); } catch { /* already gone */ }
  });
  sock.on("close", () => {
    if (wakeSock === sock) wakeSock = null;
    backoff();
  });
}

/** Something for Python that is more than a poke: a request's answer, a conversation as read. */
function tellPython(data) {
  if (!wakeSock) return false;
  try {
    wakeSock.write(JSON.stringify(data) + "\n");
    return true;
  } catch {
    return false;
  }
}

/** Tell Python to look now. Silent no-op when nothing is connected. */
function pokePython(kind) {
  if (!wakeSock) return;
  try {
    wakeSock.write(JSON.stringify({ kind }) + "\n");
  } catch {
    /* the poll on the other side covers it */
  }
}

// ── Config ────────────────────────────────────────────────────────────────────
const POLL_INTERVAL_MS     = parseInt(process.env.SNAP_POLL_INTERVAL_MS  || "8000");
const RESPONSE_POLL_MS     = parseInt(process.env.SNAP_RESPONSE_POLL_MS  || "3000");
const RESPONSE_TIMEOUT_MS  = parseInt(process.env.SNAP_RESPONSE_TIMEOUT_MS || "60000");
const TYPING_DELAY_BASE_MS = parseInt(process.env.SNAP_TYPING_DELAY_MS   || "1200");
const MAX_RECIPIENTS       = parseInt(process.env.SNAP_MAX_RECIPIENTS     || "20");

// Only open chats the list shows as unread (bold/new). Set "false" if unread
// detection misbehaves on your build and replies stop.
const ONLY_UNREAD   = (process.env.SNAP_ONLY_UNREAD   || "true").toLowerCase() !== "false";
// Open + screenshot incoming Snaps so the AI can see them (only fires when a
// chat has an unopened snap, so it's cheap when idle).
const CAPTURE_SNAPS = (process.env.SNAP_CAPTURE_SNAPS || "true").toLowerCase() !== "false";
// Grab incoming voice messages and transcribe them on the Python side.
const CAPTURE_VOICE = (process.env.SNAP_CAPTURE_VOICE || "true").toLowerCase() !== "false";
// Auto-decline incoming calls and send a casual "can't talk rn" chat.
const DECLINE_CALLS = (process.env.SNAP_DECLINE_CALLS || "true").toLowerCase() !== "false";
// Automatically accept pending friend requests. OFF by default, bulk-accepting
// requests is a classic spam/automation flag. Enable only if you need it.
const AUTO_ADD_FRIENDS = (process.env.SNAP_AUTO_ADD_FRIENDS || "false").toLowerCase() === "true";
// Save every message in a chat (hover → "Save in Chat") so nothing disappears.
const SAVE_MESSAGES = (process.env.SNAP_SAVE_MESSAGES || "true").toLowerCase() !== "false";
// Accept a small batch every interval (interleaved with chatting).
const FRIEND_ADD_INTERVAL_MS = parseInt(process.env.SNAP_FRIEND_ADD_INTERVAL_MS || "20000"); // 20s
const FRIEND_ADD_BATCH = parseInt(process.env.SNAP_FRIEND_ADD_BATCH || "5");
// How long a friend request waits before it is accepted, in seconds, as Discord's do (bot.friend_requests).
const ACCEPT_DELAY_MIN = parseInt(process.env.SNAP_ACCEPT_DELAY_MIN || "0") || 0;
const ACCEPT_DELAY_MAX = parseInt(process.env.SNAP_ACCEPT_DELAY_MAX || "0") || 0;

// ── Anti-ban send governor ────────────────────────────────────────────────────
// The #1 flag trigger is BURSTS: many messages in a short window on a robotic
// cadence. This spaces outbound sends with a randomised human gap, caps sends
// per hour, and (optionally) goes silent during "sleep" hours.
const MIN_SEND_GAP_MS    = parseInt(process.env.SNAP_MIN_SEND_GAP_MS    || "12000");  // ≥ this between any two sends
const MAX_SEND_GAP_MS    = parseInt(process.env.SNAP_MAX_SEND_GAP_MS    || "40000");  // up to this (randomised)
const MAX_SENDS_PER_HOUR = parseInt(process.env.SNAP_MAX_SENDS_PER_HOUR || "30");    // rolling hourly cap
// Quiet hours, local time, "startHour-endHour" (24h), e.g. "2-9" = pause 2am–9am.
// Empty = always on. During quiet hours the bot reads but doesn't send.
const QUIET_HOURS = (process.env.SNAP_QUIET_HOURS || "").trim();
// How long to keep an awaited reply before giving up on it (ms).
const PENDING_TTL_MS = Math.max(RESPONSE_TIMEOUT_MS, 120000);
// Max retries for one reply before dropping it (prevents re-queueing forever).
const MAX_SEND_ATTEMPTS = 4;
// Show the live "typing…" indicator while the bot types (more human).
const SHOW_TYPING = (process.env.SNAP_SHOW_TYPING || "true").toLowerCase() !== "false";
// How often to reload the web app. 0 turns it off. Default 45 minutes: long
// enough that it is not a pattern, short enough that a sidebar which has gone
// stale is not stale for a whole evening.
const RELOAD_INTERVAL_MS = Math.max(0, Number(process.env.SNAP_RELOAD_INTERVAL_MS || 45 * 60 * 1000) || 0);

// Per-account credentials. Account 1 falls back to unsuffixed SNAP_USERNAME.
function snapEnv(base) {
  const perAccount = process.env[`${base}_${ACCOUNT_INDEX}`];
  if (perAccount) return perAccount;
  if (ACCOUNT_INDEX === 1 && process.env[base]) return process.env[base];
  return "";
}
const CREDENTIALS = {
  username: snapEnv("SNAP_USERNAME"),
  password: snapEnv("SNAP_PASSWORD"),
};

// Cookies are keyed by username, so accounts naturally get separate cookie files.
const COOKIE_FILE = snapEnv("SNAP_COOKIE_FILE") || CREDENTIALS.username;

// ── Helpers ───────────────────────────────────────────────────────────────────

function readJson(filePath, defaultValue) {
  try {
    const text = fs.readFileSync(filePath, "utf-8").trim();
    if (!text) return defaultValue;
    return JSON.parse(text);
  } catch {
    return defaultValue;
  }
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf-8");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Simulate realistic typing delay based on message length. ~3.5-7 chars/sec is
 * a real person on a keyboard or phone (research: ~36 WPM on mobile); the old
 * 10-18 was superhuman and visible to whoever is watching the typing bubble.
 */
function typingDelay(text) {
  const cps = 3.5 + Math.random() * 3.5; // chars per second
  const ms = Math.max(TYPING_DELAY_BASE_MS, (text.length / cps) * 1000);
  return delay(ms);
}

// ── Send governor state (anti-ban) ────────────────────────────────────────────
let _lastSendAt = 0;          // ms timestamp of the last outbound message
let _nextGap = 0;             // randomised min gap until the next send is allowed
let _sendTimes = [];          // send timestamps within the trailing hour
let _quietLogged = false;     // so we only announce "quiet hours" once per spell

function _inQuietHours() {
  const m = QUIET_HOURS.match(/^(\d{1,2})\s*-\s*(\d{1,2})$/);
  if (!m) return false;
  const start = parseInt(m[1]) % 24;
  const end = parseInt(m[2]) % 24;
  const h = new Date().getHours();
  const inside = start <= end ? h >= start && h < end : h >= start || h < end;
  if (inside && !_quietLogged) {
    console.log(`[Snap] 😴 Quiet hours (${start}:00–${end}:00), not sending until they pass.`);
    _quietLogged = true;
  }
  if (!inside) _quietLogged = false;
  return inside;
}

/**
 * May we send a message right now? False in quiet hours, over the hourly cap,
 * or inside the randomised gap since the last send. Non-blocking, callers
 * defer the message to a later cycle.
 */
function sendAllowed() {
  if (_inQuietHours()) return false;
  const now = Date.now();
  _sendTimes = _sendTimes.filter((t) => now - t < 3600000);
  if (_sendTimes.length >= MAX_SENDS_PER_HOUR) return false;
  if (now - _lastSendAt < _nextGap) return false;
  return true;
}

/** Record that a message just went out, and roll the next randomised gap. */
function recordSend() {
  _lastSendAt = Date.now();
  _sendTimes.push(_lastSendAt);
  _nextGap = MIN_SEND_GAP_MS + Math.random() * Math.max(0, MAX_SEND_GAP_MS - MIN_SEND_GAP_MS);
  // Humans drift off mid-conversation: occasionally the next reply takes a
  // few minutes, so the gap never settles into a metronome.
  if (Math.random() < 0.08) {
    _nextGap += (120 + Math.random() * 180) * 1000;
  }
}

/** Poll interval with ±30% jitter so the cadence isn't robotically constant. */
function jitteredPoll() {
  return Math.round(POLL_INTERVAL_MS * (0.7 + Math.random() * 0.6));
}

// ── Conversations for the panel's Chats tab ───────────────────────────────────
// Snapchat for Web gives its messages no ids and no times, only the day written
// above them. Each message read gets a key made of the chat, that day, who sent
// it, its words, and which of the same it is that day, so reading the same
// conversation again finds the same keys and the panel's log never doubles one.
const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const MONTHS_FR = ["janv", "fevr", "mars", "avr", "mai", "juin", "juil", "aout", "sept", "oct", "nov", "dec"];
const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const WEEKDAYS_FR = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"];
const MONTH_FIRST = /^en-us/i.test((process.env.SNAP_LOCALE || "en-US").trim());

function isoDay(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** The day a label above some messages names, as YYYY-MM-DD: "Today", "Yesterday", "Monday", "Sep 28", "September 28, 2025", "28/09/2025". "" when it names none. */
function dayOfLabel(label, now = new Date()) {
  let v = String(label || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[\u2018\u2019]/g, "'");
  v = v.replace(/\b\d{1,2}[:h]\d{2}(\s*[ap]m)?/g, " ").replace(/[,.]/g, " ").replace(/\s+/g, " ").trim();
  if (!v) return "";
  const ago = (days) => {
    const d = new Date(now);
    d.setHours(12, 0, 0, 0);
    d.setDate(d.getDate() - days);
    return isoDay(d);
  };
  if (/^(today|aujourd'?hui)$/.test(v)) return ago(0);
  if (/^(yesterday|hier)$/.test(v)) return ago(1);
  if (!/\d/.test(v)) {
    const i = [...WEEKDAYS, ...WEEKDAYS_FR].findIndex((w) => v.startsWith(w));
    if (i >= 0) {
      for (let k = 1; k <= 7; k++) {
        const d = new Date(now);
        d.setDate(d.getDate() - k);
        if (d.getDay() === i % 7) return ago(k);
      }
    }
    return "";
  }
  const num = v.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?$/);
  let y = 0, m = 0, d = 0;
  if (num) {
    const [a, b] = [+num[1], +num[2]];
    [m, d] = MONTH_FIRST ? (a > 12 ? [b, a] : [a, b]) : (b > 12 ? [a, b] : [b, a]);
    y = num[3] ? (+num[3] < 100 ? 2000 + +num[3] : +num[3]) : 0;
  } else {
    for (const w of v.split(" ")) {
      const mi = Math.max(MONTHS.findIndex((x) => w.startsWith(x)), MONTHS_FR.findIndex((x) => w.startsWith(x)));
      if (/^[a-z]/.test(w) && mi >= 0 && !m) m = mi + 1;
      else if (/^\d{4}$/.test(w)) y = +w;
      else if (/^\d{1,2}(st|nd|rd|th|er)?$/.test(w)) d = parseInt(w, 10);
    }
  }
  if (!m || !d) return "";
  if (!y) {
    y = now.getFullYear();
    if (new Date(y, m - 1, d) > now) y -= 1;       // "Dec 30" read in January was last year's
  }
  const at = new Date(y, m - 1, d, 12);
  return at.getMonth() === m - 1 ? isoDay(at) : "";
}

/** The messages as read, each with its key and its day. */
// Snapchat's reactions: in the order its React picker shows them, and the picture each is drawn with (the part of
// its address after /d/). A picture it does not know is shown as itself.
const REACTIONS = ["❤️", "😂", "🔥", "👍", "👎", "😰", "🤯", "❓"];
const REACTION_PICTURES = {
  zIo4rYPDHUTUzlJagiLos: "❤️", hPsjuqrILjrrdt6U3kt6h: "😂", lPdlkKti9OurpfsWYqnDq: "🔥", g1eEeq3Tau8maYLqViXt5: "👍",
  tfK3eLNpxqdRfwiUABOBQ: "👎", muOvtDsQWy321fbIYIm1R: "😰", ZfiC0jJB3F4WBbEGlIFqW: "🤯", "5vpAIaiDyVKWaLwcW4QVZ": "❓",
};

/** The reactions read off a message, one each per person, as the Chats tab draws them: one per emoji, how many, and whether the account's own is one. */
function reactionsFrom(raw) {
  const out = [];
  for (const r of Array.isArray(raw) ? raw : []) {
    const id = (String(r.src || "").match(/\/d\/([A-Za-z0-9_-]+)/) || [])[1] || "";
    const name = REACTION_PICTURES[id] || "";
    const key = name || r.src;
    let hit = out.find((x) => (x.name || x.url) === key);
    if (!hit) {
      hit = name ? { name, count: 0, mine: false } : { name: "", url: r.src, count: 0, mine: false };
      out.push(hit);
    }
    hit.count++;
    if (r.mine) hit.mine = true;
  }
  return out;
}

// The account's own name as Snapchat writes it over its reactions, learned from the React picker: tells its
// reactions from the other side's. Kept with the contacts, so a restart still knows it.
const SELF_FILE = path.join(DATA_DIR, "cache", "snap_people", `self_${ACCOUNT_INDEX}.json`);
let ownName = (() => {
  try {
    return String(JSON.parse(fs.readFileSync(SELF_FILE, "utf-8")).name || "");
  } catch {
    return "";
  }
})();
function rememberOwnName(name) {
  if (!name || name === ownName) return;
  ownName = name;
  try {
    fs.mkdirSync(path.dirname(SELF_FILE), { recursive: true });
    fs.writeFileSync(SELF_FILE, JSON.stringify({ name }));
  } catch { /* known for this run */ }
}

function keyed(chatId, raw) {
  const seen = new Map();
  let day = isoDay(new Date());
  // Messages above the first label Snapchat shows belong to the day of that label, not to today.
  const firstLabel = raw.find((m) => dayOfLabel(m.day));
  if (firstLabel) day = dayOfLabel(firstLabel.day);
  return raw.map((m) => {
    // The exact moment it was sent, where the page gives one, says the day better than any label.
    const named = m.at ? isoDay(new Date(m.at)) : dayOfLabel(m.day);
    if (named) day = named;
    const body = m.text || `[${m.kind || "message"}]`;
    const base = `${chatId}|${day}|${m.mine ? 1 : 0}|${body}`;
    const n = (seen.get(base) || 0) + 1;
    seen.set(base, n);
    return {
      key: "s" + createHash("sha1").update(`${base}|${n}`).digest("hex").slice(0, 24),
      mine: !!m.mine, text: m.text || "", kind: m.kind || "", day,
      at: m.at || 0, links: Array.isArray(m.links) ? m.links : [],
      reactions: reactionsFrom(m.reactions),
    };
  });
}

/** The open conversation, read and keyed. Empty when it is not open. `shownAs` is the id the page opened it under,
 * when that was through search and is not the one asked for. */
async function transcript(bot, chatId, shownAs = chatId) {
  try {
    return keyed(chatId, (await bot.readConversation(shownAs, ownName)) || []);
  } catch {
    return [];
  }
}

/** A reaction from the Chats tab on one message of the open conversation, found by its key; the message's reactions after. */
async function reactTo(bot, chatId, shownAs, req) {
  const choice = REACTIONS.indexOf(String(req.emoji || ""));
  if (choice < 0) return { ok: false, reason: `Snapchat only has ${REACTIONS.join(" ")}` };
  await delay(400);                         // the conversation finishes drawing
  const index = (await transcript(bot, chatId, shownAs)).findIndex((m) => m.key === String(req.key || ""));
  if (index < 0) return { ok: false, reason: "that message is not in the conversation on Snapchat's page any more" };
  const done = await bot.react(shownAs, index, choice, !!req.remove, ownName);
  rememberOwnName(done.name);
  if (!done.ok) return { ok: false, reason: done.reason };
  const after = await transcript(bot, chatId, shownAs);
  const m = after.find((x) => x.key === req.key) || after[index];
  const mine = (m?.reactions || []).find((r) => r.mine);
  // Read back off the page: the reaction is there, or gone, or Snapchat did not take it.
  if (req.remove ? mine?.name === req.emoji : mine?.name !== req.emoji) {
    return { ok: false, reason: "Snapchat did not take it; try again" };
  }
  return { ok: true, reactions: m?.reactions || [] };
}

/** Hand the conversation as it now reads to Python, which keeps it for the panel and tells the panel what is new. */
async function shareTranscript(bot, chatId, name) {
  if (!wakeSock) return;
  const messages = await transcript(bot, chatId);
  if (messages.length) tellPython({ kind: "transcript", chat: chatId, name: name || "", messages: messages.slice(-120) });
}

// Who each chat is, with their picture, for the panel: names and pictures are
// read off the chat list as the bot goes through it, and each picture is saved
// here (cache/snap_people) when it changes, so the panel never asks Snapchat.
const PEOPLE_DIR = path.join(DATA_DIR, "cache", "snap_people");
const CONTACTS_FILE = path.join(PEOPLE_DIR, `contacts_${ACCOUNT_INDEX}.json`);
let contacts = null;
let contactsDirty = false;
// Pictures that would not download this session: not asked for again on every pass.
const failedPictures = new Set();

function loadContacts() {
  if (contacts) return contacts;
  try {
    contacts = JSON.parse(fs.readFileSync(CONTACTS_FILE, "utf-8")) || {};
  } catch {
    contacts = {};
  }
  return contacts;
}

async function rememberContacts(list) {
  const known = loadContacts();
  let fetched = 0;
  for (const r of list || []) {
    if (!r || !r.id || !/^[A-Za-z0-9_-]{1,80}$/.test(r.id)) continue;
    const was = known[r.id] || {};
    const now = { ...was, name: r.name || was.name || "", seen: Date.now() / 1000 };
    // A row drawn without its picture yet keeps the one already saved: only a new picture replaces it.
    if (r.avatar && r.avatar !== was.url && !failedPictures.has(r.avatar)) {
      if (fetched < 3 && PICTURE_HOSTS.test(r.avatar)) {
        // A few at a time, between the bot's own steps; the rest on a later pass.
        fetched++;
        fs.mkdirSync(PEOPLE_DIR, { recursive: true });
        const file = await savePictureTo(r.avatar, path.join(PEOPLE_DIR, `${ACCOUNT_INDEX}_${r.id}`));
        if (file) {
          if (was.file && was.file !== file) {
            try { fs.unlinkSync(path.join(PEOPLE_DIR, was.file)); } catch { /* already gone */ }
          }
          now.url = r.avatar;
          now.file = file;
        } else {
          failedPictures.add(r.avatar);
        }
      }
    }
    if (JSON.stringify(now) !== JSON.stringify({ ...was, seen: now.seen }) || !was.seen || now.seen - was.seen > 3600) {
      known[r.id] = now;
      contactsDirty = true;
    }
  }
  if (contactsDirty) {
    contactsDirty = false;
    try {
      fs.mkdirSync(PEOPLE_DIR, { recursive: true });
      const tmp = `${CONTACTS_FILE}.${process.pid}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(known, null, 1), "utf-8");
      fs.renameSync(tmp, CONTACTS_FILE);
    } catch {
      contactsDirty = true;               // the next pass tries again
    }
  }
}

/** A picture from Snapchat's CDN saved as `stem` plus its own extension. The file's name, or "" when it could not be. */
async function savePictureTo(url, stem) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000), headers: { "user-agent": BROWSER_UA } });
    if (!res.ok) return "";
    const type = res.headers.get("content-type") || "";
    const ext = type.includes("png") ? "png" : type.includes("jpeg") || type.includes("jpg") ? "jpg" : type.includes("webp") ? "webp" : "";
    if (!ext) return "";
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length < 100 || buf.length > 3_000_000) return "";
    fs.writeFileSync(`${stem}.${ext}`, buf);
    return path.basename(`${stem}.${ext}`);
  } catch {
    return "";
  }
}

// Snapchat's own chats: there is nobody in them to answer.
const SYSTEM_CHATS = ["my ai", "team snapchat"];

// The panel's requests, done one at a time between the bot's own steps: there
// is one page, and two things driving it at once would click into each other.
const panelQueue = [];

async function openChat(bot, chatId) {
  if (await bot.page.$(`#cv-${chatId}`).catch(() => null)) return true;
  try {
    await bot.sendMessage({ chat: chatId, message: "", alreadyOpen: false });
    await bot.page.waitForSelector(`#cv-${chatId}`, { timeout: 6000 });
    return true;
  } catch {
    return !!(await bot.page.$(`#cv-${chatId}`).catch(() => null));
  }
}

// The friend requests last read, and when: the Chats tab and Big Picture both ask, and each look opens Snapchat's
// requests panel on the bot's page, so an answer up to three minutes old is given instead of opening it again.
let friendRequestsSeen = [];
let friendRequestsAt = 0;

async function panelRequest(bot, req) {
  // Friend requests are not about a chat.
  if (req.op === "friends") {
    if (Date.now() - friendRequestsAt > 180000) {
      friendRequestsSeen = await bot.readFriendRequests();
      friendRequestsAt = Date.now();
    }
    return { ok: true, requests: friendRequestsSeen };
  }
  if (req.op === "friend") {
    const done = await bot.answerFriendRequest(String(req.name || ""), req.accept !== false);
    friendRequestsAt = 0;                   // read again next time
    return done ? { ok: true } : { ok: false, reason: req.accept === false ? "Snapchat has no way to turn it down here" : "that request is not there any more" };
  }
  const chatId = String(req.chat || "");
  if (!/^[A-Za-z0-9_-]{1,80}$/.test(chatId)) return { ok: false, reason: "which chat?" };
  // Whether something new was waiting in it, asked before opening it, since opening it is what marks it read.
  const wasUnread = req.op === "history" ? await bot.isUnread(chatId) : false;
  // Not in the list right now (an older chat Snapchat no longer shows): opened through its search, by name, as the
  // bot's own fallback for sending does, and the search emptied again once done.
  let shownAs = chatId;
  let searched = false;
  if (!(await openChat(bot, chatId))) {
    const name = req.name || loadContacts()[chatId]?.name || "";
    const found = name ? await bot.openViaSearch(name) : "";
    if (!found) return { ok: false, reason: "that chat is not in Snapchat's list right now" };
    shownAs = found;
    searched = true;
  }
  try {
    return await panelAct(bot, req, chatId, shownAs, wasUnread);
  } finally {
    if (searched) await bot.clearSearch();
  }
}

async function panelAct(bot, req, chatId, shownAs, wasUnread) {
  if (req.op === "history") {
    await delay(450);                       // the conversation finishes drawing
    // Opened with something new in it, the bot would now never see it as unread: it is read the bot's own way as well,
    // and what is new is answered as usual. One already read is only looked at, so opening an old conversation never
    // has the bot answer a message from days ago.
    const name = req.name || loadContacts()[chatId]?.name || chatId;
    // Snapchat's own chats (My AI, Team Snapchat) are left out of the bot's passes, so never answered from here either.
    if (wasUnread && !SYSTEM_CHATS.includes(String(name).toLowerCase().trim())) {
      try { await readChat(bot, chatId, name); } catch { /* the transcript is still read below */ }
    }
    return { ok: true, messages: await transcript(bot, chatId, shownAs) };
  }
  if (req.op === "send") {
    const text = String(req.text || "").slice(0, 2000);
    const images = (Array.isArray(req.images) ? req.images : []).filter((p) => typeof p === "string" && fs.existsSync(p));
    if (!text && !images.length) return { ok: false, reason: "nothing to send" };
    for (const imagePath of images) {
      await bot.sendImageSnap({ chat: shownAs, name: req.name || chatId, imagePath, caption: "" });
      recordSend();
      await openChat(bot, shownAs);
    }
    if (text) {
      const sent = await bot.typeInOpenChat(shownAs, text);
      if (!sent) return { ok: false, reason: "Snapchat did not take the message; try again" };
      recordSend();
    }
    await delay(700);
    const messages = await transcript(bot, chatId, shownAs);
    let key = "";
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].mine && (!text || messages[i].text === text)) {
        key = messages[i].key;
        break;
      }
    }
    return { ok: true, messages, sent: key };
  }
  if (req.op === "react") return await reactTo(bot, chatId, shownAs, req);
  return { ok: false, reason: `unknown request ${req.op}` };
}

async function processPanel(bot) {
  while (panelQueue.length) {
    const req = panelQueue.shift();
    let out;
    try {
      out = await panelRequest(bot, req);
    } catch (e) {
      out = { ok: false, reason: (e && e.message) || String(e) };
    }
    tellPython({ kind: "panel_result", id: req.id, ...out });
  }
}

// ── Per-chat seen-message tracking (in memory, resets on restart) ─────────────
// key: chatId -> Set of message keys we've already processed this session
//
// Bounded, both ways. This grew one entry per message and one Map entry per
// chat, for as long as the process ran - which for this bot is days. Sets keep
// insertion order, so trimming from the front drops the oldest, and only the
// recent end is ever consulted: a message old enough to fall out is far below
// the last reply and can never be mistaken for unanswered.
const seenMessages = new Map();
const SEEN_PER_CHAT = 300;
const SEEN_CHATS = 200;

function rememberSeen(seen, key) {
  seen.add(key);
  if (seen.size > SEEN_PER_CHAT) {
    for (const old of seen) {
      seen.delete(old);
      if (seen.size <= SEEN_PER_CHAT) break;
    }
  }
}

/**
 * Given raw chat history from extractChatData(), extract UNANSWERED user
 * messages, the trailing run of the other person's messages that come AFTER
 * our own last reply ("Me"). This stops re-answering old history after a
 * restart while still picking up "New Chat" messages that arrived while we
 * were down. The per-session seen-set de-dupes across polls.
 */
function extractNewMessages(chatId, chatData) {
  if (!seenMessages.has(chatId)) {
    if (seenMessages.size >= SEEN_CHATS) {
      // Oldest chat first; Map keeps insertion order too.
      const oldest = seenMessages.keys().next().value;
      seenMessages.delete(oldest);
    }
    seenMessages.set(chatId, new Set());
  }
  const seen = seenMessages.get(chatId);

  // Flatten the conversation in chronological order.
  const flat = [];
  for (const block of chatData) {
    for (const entry of block.conversation || []) {
      flat.push({ from: entry.from, text: entry.text, time: block.time });
    }
  }

  // Find our last reply; only messages after it are unanswered.
  let lastMeIdx = -1;
  for (let i = flat.length - 1; i >= 0; i--) {
    if (flat[i].from === "Me") { lastMeIdx = i; break; }
  }
  const tail = flat.slice(lastMeIdx + 1);

  const newMsgs = [];
  for (const entry of tail) {
    const { from, text, time } = entry;
    if (!from || from === "Me" || !text) continue;
    // time+text dedup key (same text at different times = different messages)
    const key = `${time}|${from}|${text}`;
    if (!seen.has(key)) {
      rememberSeen(seen, key);
      newMsgs.push({ from, text, time });
    }
  }

  return newMsgs;
}

// Replies we've read and handed to Python, awaiting its AI response.
//   msgId -> { chatId, name, ts }
// Kept in memory so we can reply on a *later* poll cycle instead of sitting
// inside the chat blocking on the AI (read now, reply later = human-like).
const pendingReplies = new Map();

/**
 * Send any AI responses Python has finished. For each ready response we open
 * the chat fresh, type, send, and leave - mimicking a person coming back to
 * reply rather than camping in the conversation while the model thinks.
 */
async function drainReadyResponses(bot) {
  // Drop replies we've waited too long for so the map can't grow forever.
  const now = Date.now();
  for (const [id, meta] of pendingReplies) {
    if (now - meta.ts > PENDING_TTL_MS) pendingReplies.delete(id);
  }

  const responses = readJson(RESPONSES_FILE, {});
  const ids = Object.keys(responses);
  if (ids.length === 0) return;

  let changed = false;
  for (const msgId of ids) {
    // Governor: one reply per allowed slot (gap / hourly cap / quiet hours).
    if (!sendAllowed()) break;

    const val = responses[msgId];
    // Always consume the entry so RESPONSES_FILE doesn't grow unbounded.
    delete responses[msgId];
    changed = true;

    // Route the reply. Newer entries embed { text, chat, name } so they survive
    // a Node restart; older string entries fall back to the in-memory map.
    let text, chatId, name;
    if (val && typeof val === "object") {
      text = val.text;
      chatId = val.chat;
      name = val.name || val.chat;
    } else {
      text = val;
      const meta = pendingReplies.get(msgId);
      if (meta) { chatId = meta.chatId; name = meta.name; }
    }
    pendingReplies.delete(msgId);
    if (!chatId || !text) {
      console.warn(`[Snap] Dropping a reply, couldn't determine chat/text (id ${msgId}).`);
      continue;
    }

    const attempts = ((val && typeof val === "object" && val._attempts) || 0) + 1;
    let ok = false;
    try {
      if (await bot.isChatVisible(chatId)) {
        // Open it NOW (while visible) so list reordering during the typing delay
        // can't scroll it away before we send.
        await bot.sendMessage({ chat: chatId, message: "", alreadyOpen: false });
        await typingDelay(text);
        ok = await bot.typeInOpenChat(chatId, text);
        if (!ok) ok = await bot.sendMessage({ chat: chatId, message: text, alreadyOpen: false, exit: false });
      } else {
        // Off-screen: scroll the list to it, search as a last-ditch fallback.
        await typingDelay(text);
        ok = await bot.sendMessage({ chat: chatId, message: text, alreadyOpen: false, exit: false });
        if (!ok && attempts >= MAX_SEND_ATTEMPTS) {
          ok = await bot.sendMessageViaSearch(name, text);
        }
      }
    } catch (err) {
      console.error(`[Snap] Failed to send to ${name}:`, err.message);
    }

    if (ok) {
      recordSend(); // governor: count it + roll the next randomised gap
      console.log(`  ✅ sent to ${name}`);
      await shareTranscript(bot, chatId, name);
      // Small human gap, only after an actual send, never behind a failure.
      await delay(500 + Math.random() * 900);
    } else if (attempts >= MAX_SEND_ATTEMPTS) {
      console.warn(`[Snap] Giving up on reply to ${name} after ${attempts} tries (chat unreachable).`);
    } else {
      responses[msgId] = { text, chat: chatId, name, _attempts: attempts };
    }
  }
  if (changed) writeJson(RESPONSES_FILE, responses);
}

// caller name -> last-declined timestamp, so we don't spam decline chats.
const recentDeclines = new Map();

// chatId -> last time we handled a snap there, so an un-openable snap can't
// re-trigger every poll.
const snapCooldown = new Map();

// Last time we ran the friend-request acceptor (throttled).
let lastFriendAdd = 0;

/**
 * Throttled friend-request acceptor. Called from several points (loop top,
 * between chats, during reply-drain) so requests get accepted even while the
 * bot is busy. Cheap when idle (interval gate + pending-badge check).
 */
// When the requests seen waiting are accepted; 0 while none are.
let friendsDueAt = 0;

async function maybeAcceptFriends(bot) {
  if (!AUTO_ADD_FRIENDS) return;
  if (Date.now() - lastFriendAdd <= FRIEND_ADD_INTERVAL_MS) return;
  lastFriendAdd = Date.now();
  try {
    // A few minutes after a request shows, as Discord's are, not the moment it does.
    if (ACCEPT_DELAY_MAX > 0) {
      if (!(await bot.hasPendingFriendBadge())) {
        friendsDueAt = 0;
        return;
      }
      if (!friendsDueAt) {
        const lo = Math.max(0, ACCEPT_DELAY_MIN);
        const hi = Math.max(lo, ACCEPT_DELAY_MAX);
        const wait = (lo + Math.random() * (hi - lo) + Math.random() * 120) * 1000;
        friendsDueAt = Date.now() + wait;
        console.log(`[Snap] 👥 Friend request waiting, accepting in ${Math.round(wait / 1000)}s.`);
        return;
      }
      if (Date.now() < friendsDueAt) return;
      friendsDueAt = 0;
    }
    const added = await bot.addPendingFriends(FRIEND_ADD_BATCH);
    if (added > 0) console.log(`[Snap] 👥 Accepted ${added} friend request(s).`);
  } catch (frErr) {
    console.warn("[Snap] Friend-add error:", frErr.message);
  }
}

/**
 * Reload the web app periodically.
 *
 * Snapchat for Web is a long-lived single page, and left running for hours it
 * drifts: chats stop appearing in the sidebar even though messages are
 * arriving, because the client's own list went stale and nothing on the page
 * ever refetches it. A reload is the only reliable fix, and it is what a person
 * would do.
 *
 * Deliberately not on a fixed timer alone:
 *   - never while a reply is waiting to be sent, or the reload throws away a
 *     message the model has already generated;
 *   - the interval is jittered, because a page that reloads on the exact same
 *     boundary for days is a pattern nobody's browser has.
 *
 * Returns true if the page was reloaded.
 */
async function periodicReload(bot, state) {
  if (Date.now() < state.due) return false;
  if (pendingReplies.size > 0) {
    // Not now: come back in a minute rather than pushing the whole cycle out,
    // or a busy account would never reload at all.
    state.due = Date.now() + 60 * 1000;
    return false;
  }

  console.log("[Snap] Refreshing the page (periodic).");
  try {
    await bot.page.goto("https://web.snapchat.com/", {
      waitUntil: "networkidle2",
      timeout: 60000,
    });
    await delay(4000);
  } catch (e) {
    console.warn("[Snap] Refresh navigation problem:", e.message);
  }

  // A reload lands on a fresh page, so both of these are back.
  try { await bot.handlePopup(); } catch { /* not fatal */ }
  if (!SHOW_TYPING) {
    try { await bot.blockTypingNotifications(true); } catch { /* not fatal */ }
  }

  if (!(await bot.isLogged())) {
    console.warn("[Snap] Not logged in after the refresh, recovering...");
    await attemptRelogin(bot);
  }

  state.due = Date.now() + nextReloadGap();
  return true;
}

/**
 * Check the selectors and put anything broken where the panel can see it.
 *
 * The check itself only logs; this is what makes a rotated class name show up
 * on the Snapchat card as "2 selectors stopped matching" rather than as an
 * account that is running and inexplicably silent.
 */
async function reportSelectorHealth(bot) {
  let h;
  try {
    h = await bot.selectorHealth();
  } catch {
    return;
  }
  if (h.missing.length) {
    const names = h.missing.map((m) => m.replace(/\s*\(.*\)$/, "")).join(", ");
    setState("ready", `Running, but Snapchat changed its page: ${names} no longer found. Replies may fail.`);
  }
}

/** Jittered gap to the next reload, +/-25% of the configured interval. */
function nextReloadGap() {
  const base = RELOAD_INTERVAL_MS;
  return Math.round(base * (0.75 + Math.random() * 0.5));
}

/**
 * Recover when the session dropped mid-run (cookies expired / logged out →
 * bounced to the landing page). Tries a reload first, then a full re-login.
 * Returns true if back inside the app.
 */
// Re-login is rationed. The caller that matters fires after three failed
// chat-list reads, then resets its counter - so on an account that cannot log
// in (password changed, locked, flagged) this used to submit the login form
// about every 24 seconds, indefinitely. That is the fastest way to turn a
// logged-out account into a locked one. Now: a few spaced attempts, then stop
// and say so, and a person decides.
const RELOGIN_BACKOFF_MS = [2 * 60 * 1000, 10 * 60 * 1000, 30 * 60 * 1000];
const relogin = { attempts: 0, nextAt: 0, gaveUp: false };

async function attemptRelogin(bot) {
  if (relogin.gaveUp) return false;
  if (Date.now() < relogin.nextAt) return false;      // still backing off
  const ok = await _attemptReloginOnce(bot);
  if (ok) {
    relogin.attempts = 0;
    relogin.nextAt = 0;
    setState("ready");
    await recordIdentity(bot);
    return true;
  }
  relogin.attempts++;
  if (relogin.attempts > RELOGIN_BACKOFF_MS.length) {
    relogin.gaveUp = true;
    setState("logged-out",
             "Could not log back in after several tries, so it stopped trying. " +
             "Check the account, then stop and start it from the panel.");
    console.error("[Snap] Giving up on logging back in. Restart the account once it is sorted.");
    return false;
  }
  const wait = RELOGIN_BACKOFF_MS[relogin.attempts - 1];
  relogin.nextAt = Date.now() + wait;
  setState("logged-out", `Logged out. Trying again in ${Math.round(wait / 60000)} min.`);
  console.warn(`[Snap] Log-in attempt ${relogin.attempts} failed; next in ${Math.round(wait / 60000)} min.`);
  return false;
}

async function _attemptReloginOnce(bot) {
  console.warn("[Snap] Session looks logged out, attempting recovery...");
  try {
    await bot.page.goto("https://web.snapchat.com/", { waitUntil: "networkidle2", timeout: 60000 });
  } catch { /* ignore */ }
  await delay(3000);
  if (await bot.isLogged()) {
    console.log("[Snap] Recovered, authenticated after reload.");
    return true;
  }
  if (!CREDENTIALS.username || !CREDENTIALS.password) {
    console.error("[Snap] Logged out and no credentials available to re-login.");
    return false;
  }
  try {
    await bot.login(loginDetails());
    if (bot.lastLoginError && !(await handToPerson(bot, process.env.SNAP_HEADLESS === "true"))) return false;
    await delay(5000);
    if (bot.page.url().includes("accounts.snapchat.com")) {
      await bot.page.goto("https://web.snapchat.com/", { waitUntil: "networkidle2", timeout: 60000 });
      await delay(3000);
    }
    for (let i = 0; i < 8; i++) {
      if (await bot.isLogged()) {
        console.log("[Snap] Re-login successful.");
        try { await bot.saveCookies(CREDENTIALS.username); } catch { /* ignore */ }
        return true;
      }
      await delay(3000);
    }
  } catch (e) {
    console.error("[Snap] Re-login failed:", e.message);
  }
  return false;
}

/**
 * If there's an incoming call, click "Not Now" and queue a casual "can't talk"
 * chat to the caller (crafted by the AI on the Python side).
 */
async function handleIncomingCall(bot) {
  let info;
  try {
    info = await bot.declineIncomingCall();
  } catch {
    return;
  }
  if (!info) return; // no incoming call

  let callerName = (info.name || "").trim();
  // Guard against a bad parse (e.g. grabbing the whole sidebar), a real
  // Snapchat name is short and single-line.
  if (callerName.length > 40 || /\n/.test(callerName)) callerName = "";
  const shotNote = info.callShot ? ` 📸 saved ${path.basename(info.callShot)}` : "";
  console.log(`[Snap] 📞 Incoming call${callerName ? ` from ${callerName}` : ""}, declined.${shotNote}`);
  if (!callerName) return; // declined, but can't reliably message an unknown caller

  // Only send one decline chat per caller per minute (the overlay can linger).
  const key = callerName.toLowerCase();
  const now = Date.now();
  if (recentDeclines.has(key) && now - recentDeclines.get(key) < 60000) return;
  recentDeclines.set(key, now);

  // Resolve the caller's chat id by name so we can message them.
  let chatId = null;
  try {
    const recips = await bot.listRecipients();
    const match = recips.find((r) => (r.name || "").trim().toLowerCase() === key);
    if (match) chatId = match.id;
  } catch { /* ignore */ }
  if (!chatId) {
    console.warn(`[Snap] Couldn't find ${callerName}'s chat to send a decline message.`);
    return;
  }

  // Hand off to Python to craft a natural "can't talk rn" message (call: true).
  const msgId = randomUUID();
  const incoming = readJson(INCOMING_FILE, []);
  incoming.push({
    id: msgId,
    user_id: chatId,
    user_name: callerName,
    channel_id: chatId,
    content: "",
    call: true,
    ts: Date.now() / 1000,
  });
  writeJson(INCOMING_FILE, incoming);
  // The file is written; this just saves Python the wait until its next poll.
  pokePython("incoming");
  pendingReplies.set(msgId, { chatId, name: callerName, ts: Date.now() });
}

/**
 * Wait `ms` while actively sending replies as soon as they're generated (checks
 * every ~2s) and declining incoming calls. Fires replies within ~2s of the AI
 * finishing instead of waiting a whole poll cycle.
 */
/** Sleep, but return early if Python says a reply is ready. */
function sleepOrPoke(ms) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (onResponsePoke === finish) onResponsePoke = null;
      resolve();
    };
    const timer = setTimeout(finish, ms);
    onResponsePoke = finish;
  });
}

async function drainWindow(bot, ms) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    await sleepOrPoke(2000);
    try { await processPanel(bot); } catch { /* answered inside */ }
    if (DECLINE_CALLS) {
      try { await handleIncomingCall(bot); } catch { /* ignore */ }
    }
    try {
      await drainReadyResponses(bot);
    } catch (e) {
      console.warn("[Snap] Drain error:", e.message);
    }
    // Keep accepting friends even during long reply-drain windows (throttled).
    try { await maybeAcceptFriends(bot); } catch { /* ignore */ }
  }
}

/**
 * Open one chat, pull any new messages from the other person, hand them to the
 * Python bridge, and LEAVE - without waiting for the AI. The reply is sent
 * promptly (within ~2s) by the drain window once the AI has generated it.
 */
async function readChat(bot, chatId, chatName) {
  // Open the chat (empty message = open only). This is what marks it read.
  try {
    await bot.sendMessage({ chat: chatId, message: "", alreadyOpen: false });
    await delay(600);
  } catch {
    return;
  }

  let chatData;
  try {
    chatData = await bot.extractChatData(chatId);
  } catch {
    chatData = [];
  }
  // NOTE: do NOT return early on empty chatData, a Snap (or voice note) with no
  // text produces no text rows, and we still need to open & react to it.
  chatData = chatData || [];

  // Save the messages in chat (hover → "Save in Chat") so nothing disappears.
  if (SAVE_MESSAGES) {
    try {
      const n = await bot.saveMessagesInChat(chatId);
      if (n > 0) console.log(`[Snap] 📌 Saved ${n} message(s) in ${chatName}`);
    } catch (saveErr) {
      if (process.env.SNAP_DEBUG) console.warn(`[Snap] Save-in-chat failed:`, saveErr.message);
    }
  }

  const newMessages = extractNewMessages(chatId, chatData);
  // The panel keeps the conversation as it now reads, and shows what is new in it.
  await shareTranscript(bot, chatId, chatName);

  // Open + screenshot an incoming Snap so the AI can actually see it. Gated on
  // a cheap cue check + per-chat cooldown so an un-openable snap can't loop.
  let snapImagePath = null;
  let sawSnap = false;
  if (CAPTURE_SNAPS) {
    try {
      const lastSnap = snapCooldown.get(chatId) || 0;
      if (Date.now() - lastSnap > 45000 && (await bot.hasUnopenedSnap(chatId))) {
        sawSnap = true;
        snapCooldown.set(chatId, Date.now());
        snapImagePath = await bot.openAndScreenshotSnap(chatId, chatName);
        if (snapImagePath) console.log(`[Snap] 📸 Opened & captured a Snap in ${chatName}`);
        else console.log(`[Snap] Couldn't open the Snap in ${chatName}, replying without vision.`);
      }
    } catch (snapErr) {
      console.warn(`[Snap] Snap capture failed:`, snapErr.message);
    }
  }

  // Inline image (shared post / spotlight / attached photo already displayed, 
  // not a tap-to-view snap). Screenshot it so the AI can see it too.
  if (CAPTURE_SNAPS && !snapImagePath) {
    try {
      const imgPath = await bot.extractInlineImage(chatId, chatName);
      if (imgPath) {
        snapImagePath = imgPath;
        console.log(`[Snap] 🖼️ Captured an inline image in ${chatName}`);
      }
    } catch (imgErr) {
      console.warn(`[Snap] Inline image capture failed:`, imgErr.message);
    }
  }

  // Grab a voice message (transcribed to text on the Python side).
  let audioFilePath = null;
  if (CAPTURE_VOICE) {
    try {
      const voice = await bot.extractVoiceMessage(chatId, chatName);
      if (voice) {
        audioFilePath = voice.path;
        console.log(`[Snap] 🎤 Voice message captured in ${chatName}`);
      }
    } catch (vErr) {
      console.warn(`[Snap] Voice capture failed:`, vErr.message);
    }
  }

  // Nothing new, no text, no snap, no voice to react to.
  if (newMessages.length === 0 && !snapImagePath && !sawSnap && !audioFilePath) return;

  const combinedContent = newMessages.map((m) => m.text).join("\n");
  const senderName = newMessages.length
    ? (newMessages[0].from !== "Unknown" ? newMessages[0].from : chatName)
    : chatName;
  // (No log here, the Python bridge logs the incoming message in a nicer format.)

  const msgId = randomUUID();
  const incoming = readJson(INCOMING_FILE, []);
  incoming.push({
    id: msgId,
    user_id: chatId,
    user_name: senderName,
    channel_id: chatId,
    content: combinedContent || (audioFilePath ? "" : "📸 sent a snap"),
    image_url: snapImagePath ? `file://${snapImagePath}` : undefined,
    audio_url: audioFilePath ? `file://${audioFilePath}` : undefined,
    ts: Date.now() / 1000,
  });
  writeJson(INCOMING_FILE, incoming);
  // The file is written; this just saves Python the wait until its next poll.
  pokePython("incoming");

  // Remember where to send the reply once Python answers, then move on.
  pendingReplies.set(msgId, { chatId, name: senderName, ts: Date.now() });
}

/**
 * Drain ipc/snap_outgoing.json, proactive messages queued by the Python
 * bridge (e.g. from a Telegram /reply command). Each entry is sent to its chat,
 * then removed from the queue.
 */
async function processOutgoing(bot) {
  const outgoing = readJson(OUTGOING_FILE, []);
  if (!Array.isArray(outgoing) || outgoing.length === 0) return;
  // Governor: if it's not a send slot yet, leave the queue untouched for later.
  if (!sendAllowed()) return;

  // Send the first entry, then rewrite the queue without it. Sending one per
  // poll keeps a natural gap between proactive messages.
  const entry = outgoing[0];
  const rest = outgoing.slice(1);
  writeJson(OUTGOING_FILE, rest);

  const { chat, message, image } = entry || {};
  if (!chat || (!message && !image)) return;

  const name = entry.name || chat;

  // ── Picture / Snap send (mirrors Discord attaching a photo) ───────────────
  if (image) {
    const kind = /\.mp4$/i.test(image) ? "Video" : "Picture";
    console.log(`[Snap] 📸 Sending ${kind.toLowerCase()} to ${name}: ${image}`);
    try {
      await bot.sendImageSnap({ chat, name, imagePath: image, caption: message || "" });
      recordSend(); // governor: count it + roll the next gap
      console.log(`[Snap] ✅ ${kind} sent to ${name}`);
    } catch (err) {
      console.error(`[Snap] ${kind} send failed to ${name}:`, err.message);
    }
    return;
  }

  console.log(`[Snap] Proactive send to ${name}: ${String(message).slice(0, 80)}`);
  try {
    await typingDelay(message);
    const sent = await bot.sendMessage({ chat, message, alreadyOpen: false, exit: false });
    if (sent) {
      recordSend();
      console.log(`[Snap] ✅ Proactive send complete to ${name}`);
      await shareTranscript(bot, chat, name);
    }
    else console.warn(`[Snap] ${name}'s chat wasn't visible, proactive send skipped.`);
  } catch (err) {
    console.error(`[Snap] Proactive send failed to ${name}:`, err.message);
  }
}

/**
 * Snapchat turned the automatic login down: say so, with what it said, and
 * wait for a person to log in in the window, however long that takes. The
 * window is the only place it can be done, so it stays open. Headless there is
 * no window to use, and the card says how to get one.
 * @returns {Promise<boolean>} true once someone has logged in
 */
async function handToPerson(bot, headless) {
  const why = bot.lastLoginError;
  // The card gets Snapchat's first sentence; the log gets the rest.
  let said = (why.match(/^[^.!?]*[.!?]/) || [why])[0].trim();
  if (said.length > 90) said = said.slice(0, 88).trimEnd() + "…";
  setState("needs-login", headless
    ? `Snapchat blocked the automatic login ("${said}"). Turn off "Hide the browser window", restart it, and log in yourself in its window.`
    : `Snapchat blocked the automatic login ("${said}"). Log in yourself in its Chrome window, once; it carries on from there.`);
  if (/couldn.?t find|accountnotfound/i.test(why)) {
    console.error("[Snap] Snapchat says it cannot find the account to automatic logins it does not trust, even for accounts that exist.");
  }
  console.error("[Snap] Log in yourself in the Chrome window; it carries on as soon as you are in.");
  const through = await bot.awaitEmailVerification(0, "Waiting for you to log in in the Chrome window");
  if (!through) {
    console.error("[Snap] The window closed before anyone logged in. Start the account again from the panel.");
    return false;
  }
  setState("starting", "opening the chats");
  return true;
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  if (!CREDENTIALS.username || !CREDENTIALS.password) {
    console.error(
      "[Snap] ERROR: SNAP_USERNAME and SNAP_PASSWORD must be set in .env\n" +
      "  See config/example.env for the required variables."
    );
    process.exit(1);
  }

  const bot = new SnapBot();

  setState("starting", "launching the browser");
  console.log(`[Snap] Launching Snapchat (account #${ACCOUNT_INDEX}: ${CREDENTIALS.username})...`);
  const headless = process.env.SNAP_HEADLESS === "true";
  const locale = (process.env.SNAP_LOCALE || "en-US").trim() || "en-US";
  await bot.launchSnapchat(
    {
      headless,
      args: [
        // Turns off the flag Blink sets when it is being driven, so
        // navigator.webdriver is genuinely false everywhere - workers and
        // cross-origin frames included - instead of being patched to false in
        // the main world only.
        "--disable-blink-features=AutomationControlled",
        // navigator.languages and the UI language, kept in step with the
        // Accept-Language header and the emulated timezone set in snapbot.js.
        `--lang=${locale}`,
        // Maximised only when there is a window to maximise. Headless has no
        // window, so snapbot.js adds --window-size with the size it picked for
        // this profile; passing both makes Chrome report a viewport that does
        // not match the window it says it has.
        ...(headless ? [] : ["--start-maximized"]),
        "--force-device-scale-factor=1",
        "--allow-file-access-from-files",
        "--use-fake-ui-for-media-stream",
        "--enable-media-stream",
        // Only where it is actually needed: containers and root on Linux.
        // On Windows and macOS these turn off a sandbox that was working, for
        // nothing, and the switches are visible to anything that looks.
        ...(process.platform === "linux" ? ["--no-sandbox", "--disable-setuid-sandbox"] : []),
      ],
    },
    COOKIE_FILE
  );

  // Each step says what it is doing: "launching the browser" used to stand
  // for the whole minute or two of logging in, whatever was actually going on.
  setState("starting", "checking the saved login");
  const isLogged = await bot.isLogged();
  if (!isLogged) {
    console.log("[Snap] Not logged in, starting login flow...");
    setState("starting", "logging in");
    await bot.login(loginDetails());
    setState("starting", "waiting for Snapchat to let it in");

    // ── Post-login navigation ─────────────────────────────────────────────────
    // After credentials are accepted, Snapchat lands on one of:
    //   • accounts.snapchat.com/v2/welcome  (account settings page, logged in!)
    //   • accounts.snapchat.com/v2/verify*  (email verification required)
    //   • web.snapchat.com                  (straight into the app)
    await new Promise((r) => setTimeout(r, 5000));

    let currentUrl = bot.page.url();
    console.log(`[Snap] Post-login URL: ${currentUrl}`);
    const verifyWait = Number(process.env.SNAP_VERIFY_WAIT_MS || 0) || 0;

    // Turned down at the form, which is not a verification to wait out.
    // Snapchat says "couldn't find an account" to automatic logins it does not
    // trust, even for an account that exists; a person logging in once in
    // this window gets through, and the saved profile keeps it in after that.
    if (bot.lastLoginError) {
      const turnedDown = await handToPerson(bot, headless);
      if (!turnedDown) return;
      currentUrl = bot.page.url();
    }

    // Email or code interstitial: wait for it to be finished in the browser.
    // SNAP_VERIFY_WAIT_MS sets a limit for anyone who wants one; the default
    // of 0 waits indefinitely, because the browser staying open is the whole
    // point - closing it throws away a half-finished login and makes the next
    // attempt ask Snapchat for another code.
    if (currentUrl.includes("accounts.snapchat.com") && !currentUrl.includes("/welcome")) {
      setState("awaiting-verification",
               "Snapchat wants an email or code. Finish it in the Chrome window.");
      const verified = await bot.awaitEmailVerification(verifyWait);
      if (!verified) {
        setState("awaiting-verification",
                 "Not completed. The browser is still open so you can finish it.");
        console.error("[Snap] Verification was not completed. Leaving the browser open so you can finish it.");
        console.error("[Snap] Stop the account from the panel when you are done, and start it again.");
        // Deliberately no closeBrowser() and no exit: the window is the only
        // place the verification can be completed.
        return;
      }
      currentUrl = bot.page.url();
    }

    // Landed on accounts.snapchat.com/v2/welcome → authenticated, now navigate
    // into the actual web app.
    if (currentUrl.includes("accounts.snapchat.com")) {
      console.log("[Snap] Authenticated (welcome page). Navigating to web app...");
      await bot.page.goto("https://web.snapchat.com", { waitUntil: "networkidle2", timeout: 60000 });
      await new Promise((r) => setTimeout(r, 3000));
    }

    // ── Confirm we're inside the app ─────────────────────────────────────────
    setState("starting", "opening the chats");
    let loggedNow = false;
    for (let attempt = 0; attempt < 10; attempt++) {
      loggedNow = await bot.isLogged();
      if (loggedNow) break;
      console.log(`[Snap] Waiting for web app to load... (attempt ${attempt + 1}/10)`);
      await new Promise((r) => setTimeout(r, 3000));
    }

    if (!loggedNow) {
      // Still sitting on the auth domain means a challenge appeared late - a
      // code screen after the welcome page, say. That is something a person can
      // finish, so the window stays.
      const stuckOnAuth = (bot.page.url() || "").includes("accounts.snapchat.com");
      if (stuckOnAuth) {
        setState("awaiting-verification",
                 "A late verification step appeared. Finish it in the Chrome window.");
        console.error("[Snap] Snapchat is still asking for verification. Leaving the browser open.");
        console.error("[Snap] Finish it there, then stop and start the account from the panel.");
        return;
      }
      setState("logged-out", "Login failed. Check the credentials.");
      console.error("[Snap] Login failed. Check credentials / 2FA.");
      await bot.closeBrowser();
      process.exit(1);
    }
    console.log("[Snap] Logged in successfully. Saving cookies...");
    await bot.saveCookies(CREDENTIALS.username);
  } else {
    console.log("[Snap] Already logged in via cookies.");
    setState("starting", "opening the chats");
    // Refresh the saved cookies so they don't go stale over time.
    try {
      await bot.saveCookies(CREDENTIALS.username);
    } catch {
      /* non-fatal */
    }
  }

  await bot.handlePopup();
  // Typing notifications ON by default, the recipient seeing "typing…" while
  // the bot types reads far more human than instant sends.
  if (!SHOW_TYPING) {
    await bot.blockTypingNotifications(true);
    console.log("[Snap] Typing indicator suppressed (SNAP_SHOW_TYPING=false).");
  } else {
    console.log("[Snap] Typing indicator enabled, recipients will see 'typing…'.");
  }

  setState("ready");
  await reportSelectorHealth(bot);
  await recordIdentity(bot);
  console.log(`[Snap] Ready. Polling every ~${Math.round(POLL_INTERVAL_MS / 1000)}s for new messages...`);
  console.log(
    `[Snap] 🛡️ Anti-ban: ${Math.round(MIN_SEND_GAP_MS / 1000)}–${Math.round(MAX_SEND_GAP_MS / 1000)}s between sends, ` +
    `max ${MAX_SENDS_PER_HOUR}/hr${QUIET_HOURS ? `, quiet hours ${QUIET_HOURS}` : ""}.`
  );

  // Initialise IPC files
  if (!fs.existsSync(INCOMING_FILE)) writeJson(INCOMING_FILE, []);

  // Retries on its own if the bridge has not published its port yet.
  connectWake();
  if (!fs.existsSync(RESPONSES_FILE)) writeJson(RESPONSES_FILE, {});
  if (!fs.existsSync(OUTGOING_FILE)) writeJson(OUTGOING_FILE, []);
  if (!fs.existsSync(PROCESSED_FILE)) writeJson(PROCESSED_FILE, []);

  // Names to ignore (case-insensitive), Snapchat system bots
  const IGNORED_NAMES = SYSTEM_CHATS;

  // ── Main polling loop ─────────────────────────────────────────────────────
  // Each cycle: (1) send any replies the AI has finished, (2) drain proactive
  // sends, (3) read NEW messages from unread chats and hand them to Python.
  // Reading and replying are deliberately separated across cycles so the bot
  // never sits inside a chat waiting on the model.
  let listFailures = 0; // consecutive "couldn't list recipients", triggers re-login check
  // Snapchat puts its onboarding and announcement dialogs up whenever it feels
  // like it, not only at login - and one of those sitting over the app makes
  // every chat unclickable, so the bot goes quiet with nothing in the log to
  // say why. Checked on a slow cycle rather than every poll: it is a page
  // evaluate, cheap, but not free.
  let lastDialogCheck = Date.now();
  const DIALOG_CHECK_MS = 5 * 60 * 1000;
  const reloadState = { due: Date.now() + nextReloadGap() };
  if (RELOAD_INTERVAL_MS > 0) {
    console.log(`[Snap] Refreshing the page roughly every ${Math.round(RELOAD_INTERVAL_MS / 60000)} min.`);
  }

  while (true) {
    heartbeatState();
    try {
      await processPanel(bot);
      // 0. A long-lived page stops listing some chats. Refresh before reading,
      // never mid-reply - periodicReload() defers itself if one is pending.
      if (RELOAD_INTERVAL_MS > 0) {
        try {
          if (await periodicReload(bot, reloadState)) {
            lastDialogCheck = Date.now();
            setState("ready");
            // A reload is when a new Snapchat build arrives, so it is also
            // when a selector is most likely to have just stopped matching.
            await reportSelectorHealth(bot);
            await recordIdentity(bot, { maxAgeHours: 6 });
          }
        } catch (rlErr) {
          console.warn("[Snap] Refresh error:", rlErr.message);
        }
      }

      // 0. Anything covering the app, before trying to use it.
      if (Date.now() - lastDialogCheck >= DIALOG_CHECK_MS) {
        lastDialogCheck = Date.now();
        try {
          await bot.handlePopup();
        } catch (dlgErr) {
          console.warn("[Snap] Dialog check error:", dlgErr.message);
        }
      }

      // 0. Decline any incoming call first (time-sensitive).
      if (DECLINE_CALLS) {
        try {
          await handleIncomingCall(bot);
        } catch (callErr) {
          console.warn("[Snap] Call handling error:", callErr.message);
        }
      }

      // 0b. Accept a small batch of friend requests (throttled; only opens the
      // panel if a badge shows any). Also runs between chats + during draining.
      await maybeAcceptFriends(bot);

      // 1. Send AI responses that are ready (read-now / reply-later)
      try {
        await drainReadyResponses(bot);
      } catch (respErr) {
        console.warn("[Snap] Response drain error:", respErr.message);
      }

      // 2. Drain any proactive messages queued by the Python bridge
      try {
        await processOutgoing(bot);
      } catch (outErr) {
        console.warn("[Snap] Outgoing drain error:", outErr.message);
      }

      // 3. List recipients (with unread state when ONLY_UNREAD is on)
      let recipients;
      try {
        recipients = ONLY_UNREAD
          ? await bot.listRecipientsWithUnread()
          : await bot.listRecipients();
        listFailures = 0; // got the list, session is healthy
        try { await rememberContacts(recipients); } catch { /* names and pictures wait for the next pass */ }
        // Someone writing to the account right now, as the list says: the panel shows the same dots as for Discord.
        for (const r of recipients || []) {
          if (r.typing && !SYSTEM_CHATS.includes(String(r.name || "").toLowerCase().trim())) tellPython({ kind: "typing", chat: r.id });
        }
      } catch (err) {
        console.warn("[Snap] Could not list recipients:", err.message);
        // The chat list only goes missing when the app isn't open, usually a
        // dropped session. After a few in a row, check and re-login.
        if (++listFailures >= 3) {
          listFailures = 0;
          try {
            if (!(await bot.isLogged())) await attemptRelogin(bot);
          } catch (recErr) {
            console.warn("[Snap] Recovery check failed:", recErr.message);
          }
        }
        await drainWindow(bot, jitteredPoll());
        continue;
      }

      if (!recipients || recipients.length === 0) {
        await drainWindow(bot, jitteredPoll());
        continue;
      }

      let targets = recipients
        .filter((r) => !IGNORED_NAMES.includes((r.name || "").toLowerCase().trim()));

      // Only open chats flagged unread. Filter BEFORE capping so older unread
      // chats aren't cut by the cap just because read chats sat ahead of them.
      if (ONLY_UNREAD) targets = targets.filter((r) => r.unread);
      targets = targets.slice(0, MAX_RECIPIENTS);

      // A person glances at the app a beat before diving in; without this the
      // first chat of every pass opens right on the poll edge, every time.
      await delay(500 + Math.random() * 2500);

      for (const recipient of targets) {
        if (!recipient.id) continue;
        await readChat(bot, recipient.id, recipient.name);
        await processPanel(bot);
        // Accept pending friends BETWEEN conversations so a long backlog of
        // chats doesn't starve the acceptor (throttled inside).
        await maybeAcceptFriends(bot);
        // Small human gap between opening different chats.
        await delay(700 + Math.random() * 1200);
      }
    } catch (loopErr) {
      console.error("[Snap] Loop error:", loopErr.message);
    }

    // Spend the gap between read passes actively sending replies (every ~2s) so
    // responses go out right after they're generated, not a full cycle later.
    await drainWindow(bot, jitteredPoll());
  }
}

main().catch((err) => {
  console.error("[Snap] Fatal error:", err);
  process.exit(1);
});
