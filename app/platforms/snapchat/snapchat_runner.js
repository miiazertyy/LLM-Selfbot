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
import { randomUUID } from "crypto";
import { createRequire } from "module";
import { patchConsole } from "./log.js";

// .env location: explicit override (set by the Python bridge) > bundled config
// (source) > repo config (frozen, where the bridge usually set it already).
const DOTENV_PATH = process.env.SNAP_DOTENV_PATH || "../../config/.env";
dotenv.config({ path: DOTENV_PATH });
if (!process.env.SNAP_USERNAME) {
  dotenv.config({ path: ".env" });
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
function setState(state, detail = "") {
  if (state === lastState && !detail) return;
  lastState = state;
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
 * Simulate realistic typing delay based on message length (~10-18 chars/sec).
 */
function typingDelay(text) {
  const cps = 10 + Math.random() * 8; // chars per second
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
}

/** Poll interval with ±30% jitter so the cadence isn't robotically constant. */
function jitteredPoll() {
  return Math.round(POLL_INTERVAL_MS * (0.7 + Math.random() * 0.6));
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
async function maybeAcceptFriends(bot) {
  if (!AUTO_ADD_FRIENDS) return;
  if (Date.now() - lastFriendAdd <= FRIEND_ADD_INTERVAL_MS) return;
  lastFriendAdd = Date.now();
  try {
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
async function attemptRelogin(bot) {
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
    await bot.login(CREDENTIALS);
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
    console.log(`[Snap] 📸 Sending picture to ${name}: ${image}`);
    try {
      await bot.sendImageSnap({ chat, name, imagePath: image, caption: message || "" });
      recordSend(); // governor: count it + roll the next gap
      console.log(`[Snap] ✅ Picture sent to ${name}`);
    } catch (err) {
      console.error(`[Snap] Picture send failed to ${name}:`, err.message);
    }
    return;
  }

  console.log(`[Snap] Proactive send to ${name}: ${String(message).slice(0, 80)}`);
  try {
    await typingDelay(message);
    const sent = await bot.sendMessage({ chat, message, alreadyOpen: false, exit: false });
    if (sent) { recordSend(); console.log(`[Snap] ✅ Proactive send complete to ${name}`); }
    else console.warn(`[Snap] ${name}'s chat wasn't visible, proactive send skipped.`);
  } catch (err) {
    console.error(`[Snap] Proactive send failed to ${name}:`, err.message);
  }
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
  await bot.launchSnapchat(
    {
      headless: process.env.SNAP_HEADLESS === "true",
      args: [
        "--start-maximized",
        "--force-device-scale-factor=1",
        "--allow-file-access-from-files",
        "--use-fake-ui-for-media-stream",
        "--enable-media-stream",
        "--no-sandbox",
        "--disable-setuid-sandbox",
      ],
    },
    COOKIE_FILE
  );

  const isLogged = await bot.isLogged();
  if (!isLogged) {
    console.log("[Snap] Not logged in, starting login flow...");
    await bot.login(CREDENTIALS);

    // ── Post-login navigation ─────────────────────────────────────────────────
    // After credentials are accepted, Snapchat lands on one of:
    //   • accounts.snapchat.com/v2/welcome  (account settings page, logged in!)
    //   • accounts.snapchat.com/v2/verify*  (email verification required)
    //   • web.snapchat.com                  (straight into the app)
    await new Promise((r) => setTimeout(r, 5000));

    let currentUrl = bot.page.url();
    console.log(`[Snap] Post-login URL: ${currentUrl}`);

    // Email or code interstitial: wait for it to be finished in the browser.
    // SNAP_VERIFY_WAIT_MS sets a limit for anyone who wants one; the default
    // of 0 waits indefinitely, because the browser staying open is the whole
    // point - closing it throws away a half-finished login and makes the next
    // attempt ask Snapchat for another code.
    if (currentUrl.includes("accounts.snapchat.com") && !currentUrl.includes("/welcome")) {
      const verifyWait = Number(process.env.SNAP_VERIFY_WAIT_MS || 0) || 0;
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
  const IGNORED_NAMES = ["my ai", "team snapchat"];

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
    try {
      // 0. A long-lived page stops listing some chats. Refresh before reading,
      // never mid-reply - periodicReload() defers itself if one is pending.
      if (RELOAD_INTERVAL_MS > 0) {
        try {
          if (await periodicReload(bot, reloadState)) {
            lastDialogCheck = Date.now();
            setState("ready");
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

      for (const recipient of targets) {
        if (!recipient.id) continue;
        await readChat(bot, recipient.id, recipient.name);
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
