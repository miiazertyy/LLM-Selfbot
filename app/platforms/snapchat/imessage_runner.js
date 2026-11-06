/**
 * platforms/snapchat/imessage_runner.js
 *
 * Node side of the iMessage platform: one account, through a BlueBubbles Server on a Mac signed in to iMessage
 * (bluebubbles.js). No browser: it hears a new message the moment the Mac does (BlueBubbles' live feed, and a look at
 * what came in while that was down), hands it to the Python bridge, and sends the bridge's answer back the way a
 * person on an iPhone does: it reads the message (a read receipt), types (the dots), sometimes taps back, and sends
 * each line as its own bubble. The same files and wake socket as the other runners (runner_core.js), so the same
 * bridge serves it.
 *
 * Also: photos and videos looked at, voice messages heard; photos and voice messages sent; group chats, answered
 * when called by name; tapbacks, replies in a thread, edits and unsends seen and kept; names and pictures from the
 * Mac's address book; a FaceTime call it cannot take, answered with a text.
 *
 * Read receipts, the typing dots, tapbacks, replies in a thread, editing and unsending need BlueBubbles' Private API
 * on the Mac. Without it, it still reads and answers (AppleScript), and its card says what it does without.
 *
 * IMESSAGE_DRY_RUN=true reads, and writes its replies to the log, and sends nothing.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createHash, randomUUID } from "crypto";
import { patchConsole } from "./log.js";
import { createCore, readJson, writeJson, delay, isoDay } from "./runner_core.js";
import {
  BlueBubbles, liveFeed, readMessage, describe, logBody, chatIdOf, guidParts, personId, addressOf, sameAddress,
  TAPBACKS, tapbackName,
} from "./bluebubbles.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
patchConsole();

const TAG = "[iMessage]";
const DATA_DIR = process.env.IMESSAGE_DATA_DIR || process.env.SNAP_DATA_DIR || path.resolve(__dirname, "../../");
const ACCOUNT = parseInt(process.env.IMESSAGE_ACCOUNT_INDEX || "1", 10) || 1;
const SERVER = String(process.env[`IMESSAGE_SERVER_${ACCOUNT}`] || "").trim();
const PASSWORD = String(process.env[`IMESSAGE_PASSWORD_${ACCOUNT}`] || "");

// Texting is quicker than a social site's DMs: closer gaps, more an hour, by default.
const core = createCore({
  prefix: "imsg", env: "IMESSAGE", account: ACCOUNT, dataDir: DATA_DIR, tag: TAG,
  defaults: { MIN_SEND_GAP_MS: 4000, MAX_SEND_GAP_MS: 20000, MAX_SENDS_PER_HOUR: 60, POLL_INTERVAL_MS: 15000 },
});
const DRY_RUN = core.flag("DRY_RUN", false);
const READ_RECEIPTS = core.flag("READ_RECEIPTS", true);
const TYPING = core.flag("TYPING", true);
const TAPBACKS_ON = core.flag("TAPBACKS", true);
const GROUPS = core.flag("GROUPS", true);
const ANSWER_SMS = core.flag("ANSWER_SMS", true);
const VOICE_NOTES = core.flag("VOICE_NOTES", true);
const CALL_TEXT = core.flag("CALL_TEXT", true);
const EFFECTS_ON = core.flag("EFFECTS", true);
const FIX_TYPOS = core.flag("FIX_TYPOS", true);
// "auto": the Private API when it is connected, else AppleScript; or one of them, always.
const SEND_METHOD = core.text("SEND_METHOD", "auto").toLowerCase();
// Answering in a thread (iMessage's Reply): "never", "late" (when others wrote since what it answers), "always".
const THREAD_REPLIES = core.text("THREAD_REPLIES", "late").toLowerCase();
const TRIGGER = core.text("TRIGGER", "");
// Someone writing several messages in a row is answered once, after they stop for this long.
const BURST_MS = Math.max(0, core.num("BURST_MS", 4000));
const MAX_BURST_MS = 20000;
const RESPONSE_TTL_MS = Math.max(core.num("RESPONSE_TIMEOUT_MS", 120000), 120000);

const PEOPLE_DIR = path.join(DATA_DIR, "cache", "imessage_people");
const CONTACTS_FILE = path.join(PEOPLE_DIR, `contacts_${ACCOUNT}.json`);
const SEEN_FILE = path.join(PEOPLE_DIR, `seen_${ACCOUNT}.json`);
const IDENTITY_FILE = path.join(DATA_DIR, "config", `identity_imessage_${ACCOUNT}.json`);
const TEMP_DIR = path.join(DATA_DIR, "config", "temp");

const bb = new BlueBubbles({ url: SERVER, password: PASSWORD });
let feed = null;
let info = {};
let papi = false;                 // the Private API on, and its helper connected: tapbacks, dots, read receipts

// ── Small state ───────────────────────────────────────────────────────────────

const sha1 = (s) => createHash("sha1").update(String(s)).digest("hex");

/** A Map that forgets its oldest entries past `max`. */
function bounded(max) {
  const m = new Map();
  const set = m.set.bind(m);
  m.set = (k, v) => {
    if (m.has(k)) m.delete(k);
    set(k, v);
    while (m.size > max) m.delete(m.keys().next().value);
    return m;
  };
  return m;
}

let contacts = null;
function loadContacts() {
  if (contacts) return contacts;
  contacts = readJson(CONTACTS_FILE, {}) || {};
  return contacts;
}
function saveContacts() {
  try { writeJson(CONTACTS_FILE, contacts || {}); } catch { /* next time */ }
}

// The messages it has already dealt with, and the newest one's time: what a catch-up starts from after a restart.
const seen = readJson(SEEN_FILE, { at: 0, guids: [] }) || { at: 0, guids: [] };
const handled = new Set(Array.isArray(seen.guids) ? seen.guids.slice(-3000) : []);
let seenDirty = false;
function markHandled(guid, at = 0) {
  if (!guid) return;
  handled.add(guid);
  if (handled.size > 4000) handled.delete(handled.values().next().value);
  if (Number(at) > Number(seen.at || 0)) seen.at = Number(at);
  seenDirty = true;
}
function saveSeen() {
  if (!seenDirty) return;
  seenDirty = false;
  try { writeJson(SEEN_FILE, { at: seen.at || 0, guids: [...handled].slice(-3000) }); } catch { /* next time */ }
}

const recent = bounded(3000);         // guid -> the message as read (its words, for a quote, a tapback's target)
const reactionsOf = bounded(2000);    // guid -> Map(who -> {emoji, mine})
const primed = new Set();             // chats whose recent past was shared with the bridge in this run
const sentByUs = bounded(500);        // tempGuids and guids of what this runner sent
const sendingText = bounded(200);     // chat guid -> [{text, at}] of what it sent lately
const elsewhere = new Map();          // chat id -> when a person wrote in it from the Mac or the iPhone
const lastIn = new Map();             // chat id -> when anyone last wrote in it
const bursts = new Map();             // chat id -> {items, first, timer, name}
const pending = new Map();            // reply id -> {chatId, name, ts, replyTo, at}

// Event handling one at a time, in the order they came.
let chain = Promise.resolve();
function enqueue(fn) {
  chain = chain.then(fn).catch((e) => console.warn(`${TAG} ${e?.message || e}`));
  return chain;
}

// ── Who is who ────────────────────────────────────────────────────────────────

let book = [];                        // the Mac's address book: [{name, addrs, avatar}]
async function loadBook() {
  const list = await bb.contacts({ thumbnails: true });
  const out = [];
  for (const c of Array.isArray(list) ? list : []) {
    const name = String(c?.displayName || [c?.firstName, c?.lastName].filter(Boolean).join(" ") || c?.nickname || "").trim();
    const addrs = [...(c?.phoneNumbers || []), ...(c?.emails || [])]
      .map((x) => String((x && typeof x === "object" ? x.address : x) || "").trim()).filter(Boolean);
    if (name && addrs.length) out.push({ name, addrs, avatar: String(c?.avatar || "") });
  }
  book = out;
  console.log(`${TAG} ${book.length} people in the Mac's address book.`);
}
const bookEntry = (address) => book.find((e) => e.addrs.some((a) => sameAddress(a, address))) || null;

/** An address as a person would read it, when the address book has no name for it. */
function pretty(address) {
  const a = String(address || "");
  return a;
}
function personName(address) {
  return bookEntry(address)?.name || pretty(address);
}

/** A group's name: its own, else its people's first names. */
function groupName(chat, c = {}) {
  const own = String(chat?.displayName || "").trim();
  if (own) return own;
  const people = (chat?.participants || []).map((p) => personName(p?.address).split(" ")[0]).filter(Boolean);
  if (people.length) {
    return people.length <= 3 ? people.join(", ").replace(/, ([^,]*)$/, " and $1")
                              : `${people.slice(0, 2).join(", ")} and ${people.length - 2} others`;
  }
  return c.name || "a group";
}

function savePicture(chatId, base64) {
  if (!base64 || !/^[A-Za-z0-9_-]{1,80}$/.test(chatId)) return "";
  let buf;
  try { buf = Buffer.from(base64, "base64"); } catch { return ""; }
  if (buf.length < 100 || buf.length > 3_000_000) return "";
  const ext = buf[0] === 0x89 && buf[1] === 0x50 ? "png" : buf[0] === 0xff && buf[1] === 0xd8 ? "jpg"
            : buf.slice(8, 12).toString() === "WEBP" ? "webp" : "";
  if (!ext) return "";
  const file = `${ACCOUNT}_${chatId}.${ext}`;
  try {
    fs.mkdirSync(PEOPLE_DIR, { recursive: true });
    fs.writeFileSync(path.join(PEOPLE_DIR, file), buf);
    return file;
  } catch {
    return "";
  }
}

/** What is known of a chat, kept for the panel (cache/imessage_people) and to send to it again. */
function rememberChat(chatId, r) {
  const known = loadContacts();
  const was = known[chatId] || {};
  const now = { ...was, seen: Date.now() / 1000 };
  if (r.chatGuid) now.guid = r.chatGuid;
  const parts = guidParts(r.chatGuid);
  if (parts.service) now.service = parts.service;
  if (r.group) {
    now.group = true;
    now.name = groupName(r.chat, was);
    const people = (r.chat?.participants || []).map((p) => String(p?.address || "")).filter(Boolean);
    if (people.length) now.participants = people.slice(0, 40);
  } else {
    const address = parts.ident || r.address || was.address || addressOf(chatId);
    now.address = address;
    const entry = bookEntry(address);
    now.name = entry?.name || was.name || pretty(address);
    if (entry?.avatar) {
      const mark = sha1(entry.avatar).slice(0, 12);
      if (mark !== was.picture_mark) {
        const file = savePicture(chatId, entry.avatar);
        if (file) Object.assign(now, { file, picture_mark: mark });
      }
    }
  }
  if (JSON.stringify(now) !== JSON.stringify({ ...was, seen: now.seen })) {
    known[chatId] = now;
    saveContacts();
  } else {
    known[chatId] = now;
  }
  return now;
}

const chatGuidOf = (chatId) => String(loadContacts()[chatId]?.guid || "");
const nameOfChat = (chatId) => String(loadContacts()[chatId]?.name || addressOf(chatId) || chatId);

// ── What is said, for the bridge and its chat log ─────────────────────────────

const keyOf = (guid) => `b${guid}`;
const guidOfKey = (key) => (String(key || "").startsWith("b") ? String(key).slice(1) : "");

function linksIn(text) {
  return (String(text || "").match(/https?:\/\/[^\s<>"']+/g) || []).slice(0, 3).map((url) => ({ url, title: "" }));
}

/** Its tapbacks as the chat log keeps reactions: each emoji, how many, and whether the account's own is one. */
function reactionsFor(guid) {
  const map = reactionsOf.get(guid);
  if (!map || !map.size) return [];
  const by = new Map();
  for (const { emoji, mine } of map.values()) {
    const r = by.get(emoji) || { name: emoji, count: 0, mine: false };
    r.count += 1;
    r.mine = r.mine || mine;
    by.set(emoji, r);
  }
  return [...by.values()];
}

function noteTapback(r) {
  const target = r.tapback?.target;
  if (!target) return "";
  const who = r.mine ? "me" : r.address || "someone";
  const map = reactionsOf.get(target) || new Map();
  if (r.tapback.removed) map.delete(who);
  else map.set(who, { emoji: r.tapback.emoji, mine: r.mine });
  reactionsOf.set(target, map);
  return target;
}

function quoteOf(guid) {
  const q = recent.get(guid);
  return q ? (q.text || logBody(q).text) : "";
}

/** One message as the bridge keeps a conversation's (runner_core.js keyed()): BlueBubbles' guid is its key, its time
 *  exact, so reading it again never doubles it. */
function entryOf(r) {
  const { text, kind } = logBody(r);
  const at = r.at || Date.now();
  return {
    key: keyOf(r.guid), mine: !!r.mine, text, kind, day: isoDay(new Date(at)), at,
    links: linksIn(r.text), reactions: reactionsFor(r.guid),
    ...(r.group && !r.mine && r.address ? { author: personName(r.address) } : {}),
    ...(r.replyTo && quoteOf(r.replyTo) ? { quote: quoteOf(r.replyTo).slice(0, 200) } : {}),
  };
}

function share(chatId, name, entries) {
  if (!core.connected() || !entries.length) return;
  core.tellPython({ kind: "transcript", chat: chatId, name: name || "", messages: entries.slice(-120) });
}

/** A chat's last messages, oldest first, as read: tapbacks applied to what they are on, kept for quotes. */
async function readChat(chatGuid, limit = 30) {
  const list = await bb.chatMessages(chatGuid, { limit });
  const rs = (Array.isArray(list) ? list : []).map(readMessage).reverse();
  for (const r of rs) {
    if (r.tapback) noteTapback(r);
    else if (r.guid) recent.set(r.guid, r);
  }
  return rs.filter((r) => r.guid && !r.tapback && !r.event);
}

async function shareNew(chatId, name, r) {
  if (!primed.has(chatId) && r.chatGuid) {
    primed.add(chatId);
    const past = await readChat(r.chatGuid, 30).catch(() => null);
    if (past) {
      share(chatId, name, past.map(entryOf));
      if (past.some((x) => x.guid === r.guid)) return;
    }
  }
  share(chatId, name, [entryOf(r)]);
}

// ── What it hears ─────────────────────────────────────────────────────────────

/** Whether a message from the account was sent from here (else a person sent it, from the Mac or the iPhone). */
function ours(r) {
  if (sentByUs.has(r.guid) || (r.tempGuid && sentByUs.has(r.tempGuid))) return true;
  const lately = sendingText.get(r.chatGuid) || [];
  return lately.some((s) => s.text === r.text && Math.abs(s.at - (r.at || Date.now())) < 180000);
}

// The persona's names (bot.trigger, "John, Jon"), split on commas as Discord's are. None: nothing in a group calls it.
const TRIGGER_WORDS = TRIGGER.toLowerCase().split(",").map((w) => w.trim()).filter(Boolean);
function triggered(text) {
  const t = String(text || "").toLowerCase();
  return TRIGGER_WORDS.some((w) => new RegExp(`(^|[^\\p{L}\\p{N}])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^\\p{L}\\p{N}])`, "u").test(t));
}

async function onMessage(raw) {
  let r = readMessage(raw);
  if (!r.guid || handled.has(r.guid)) return;
  if (!r.chatGuid) {
    // A message given without its chat: asked for again, whole.
    const whole = await bb.message(r.guid).catch(() => null);
    if (whole) r = readMessage(whole);
    if (!r.chatGuid) return;
  }
  markHandled(r.guid, r.at);
  const chatId = chatIdOf(r.chat);
  if (!chatId) return;
  // BlueBubbles' live feed gives a message's chat without its people: a group's are asked for once, for its name.
  const was = loadContacts()[chatId];
  if (r.group && !(r.chat?.participants || []).length
      && (!was?.participants?.length || r.event?.what === "added" || r.event?.what === "removed" || r.event?.what === "left")) {
    const whole = await bb.chat(r.chatGuid).catch(() => null);
    if (whole) r.chat = { ...r.chat, ...whole };
  }
  if (r.event?.what === "renamed" && r.chat) r.chat = { ...r.chat, displayName: r.event.title };
  const c = rememberChat(chatId, r);
  const name = c.name || chatId;
  lastIn.set(chatId, r.at || Date.now());
  if (r.tapback) {
    const target = noteTapback(r);
    const t = recent.get(target);
    if (t) share(chatId, name, [entryOf(t)]);
    if (!r.mine) console.log(`${TAG} ${r.group ? `${personName(r.address)} in ${name}` : name} `
      + `${r.tapback.removed ? "took back their" : "tapped back"} ${r.tapback.emoji}`);
    return;
  }
  if (r.event) {
    const who = r.mine ? "You" : personName(r.address);
    const what = r.event.what === "renamed" ? `named the group "${r.event.title}"`
               : r.event.what === "added" ? `added ${personName(r.event.who)}`
               : r.event.what === "removed" ? `removed ${personName(r.event.who)}`
               : r.event.what === "left" ? "left the group" : "changed the group's picture";
    console.log(`${TAG} ${name}: ${who} ${what}.`);
    return;
  }
  recent.set(r.guid, r);
  await shareNew(chatId, name, r);
  if (r.mine) {
    if (!ours(r)) elsewhere.set(chatId, r.at || Date.now());
    return;
  }
  if (/^sms$/i.test(r.service) && !ANSWER_SMS) return;
  if (r.group && !GROUPS) return;
  addToBurst(chatId, name, r);
}

function addToBurst(chatId, name, r) {
  let b = bursts.get(chatId);
  if (!b) {
    b = { items: [], first: Date.now(), timer: null, name };
    bursts.set(chatId, b);
  }
  b.items.push(r);
  b.name = name;
  clearTimeout(b.timer);
  const wait = Math.max(0, Math.min(BURST_MS, b.first + MAX_BURST_MS - Date.now()));
  b.timer = setTimeout(() => enqueue(() => flushBurst(chatId)), wait);
}

const EXT = {
  "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp",
  "image/heic": "heic", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
  "audio/aac": "aac", "audio/x-caf": "caf", "audio/wav": "wav", "video/mp4": "mp4", "video/quicktime": "mov",
};

/** An attachment saved for the bridge to look at or listen to: its path, or "". */
async function fetchMedia(m, stem) {
  try {
    const { data, mime } = await bb.download(m.guid, m.kind === "photo" ? { width: 1600 } : {});
    if (!data?.length || data.length > 40 * 1024 * 1024) return "";
    const ext = EXT[mime.split(";")[0].trim()] || path.extname(m.name).slice(1).toLowerCase() || "bin";
    fs.mkdirSync(TEMP_DIR, { recursive: true });
    const file = path.join(TEMP_DIR, `imsg_${ACCOUNT}_${stem}_${Date.now()}.${ext}`);
    fs.writeFileSync(file, data);
    return file;
  } catch (e) {
    console.warn(`${TAG} Could not fetch a ${m.kind} from the Mac: ${e.message}`);
    return "";
  }
}

async function flushBurst(chatId) {
  const b = bursts.get(chatId);
  if (!b) return;
  bursts.delete(chatId);
  const items = b.items;
  if (!items.length) return;
  const group = !!items[0].group;
  const lines = items.map((r) => {
    const said = describe(r, { quote: r.replyTo ? quoteOf(r.replyTo) : "" });
    return group && said ? `${personName(r.address)}: ${said}` : said;
  }).filter(Boolean);
  let content = lines.join("\n");
  // In a group, only what calls the persona by name, as on Discord's servers, or answers one of its own messages.
  const toIt = items.some((r) => r.replyTo && recent.get(r.replyTo)?.mine);
  if (group && !toIt && !triggered(items.map((r) => r.text).join("\n"))) return;
  const media = items.flatMap((r) => r.media);
  const photo = [...media].reverse().find((m) => m.kind === "photo" || m.kind === "sticker" || m.kind === "gif");
  const voice = [...media].reverse().find((m) => m.kind === "voice");
  const video = [...media].reverse().find((m) => m.kind === "video");
  const image = photo ? await fetchMedia(photo, "photo") : "";
  const audio = voice ? await fetchMedia(voice, "voice") : "";
  const clip = video ? await fetchMedia(video, "video") : "";
  if (!content && !image && !audio && !clip) {
    if (!media.length) return;
    content = "[sent a photo]";
  }
  const newest = items[items.length - 1];
  const id = randomUUID();
  core.handOver({
    id, user_id: chatId, user_name: b.name, channel_id: chatId, content,
    ts: (newest.at || Date.now()) / 1000,
    image_url: image ? `file://${image}` : undefined,
    audio_url: audio ? `file://${audio}` : undefined,
    video_url: clip ? `file://${clip}` : undefined,
    group: group || undefined,
    photo: true,
    voice: VOICE_NOTES || undefined,
    react_to: newest.guid,
  });
  pending.set(id, { chatId, name: b.name, ts: Date.now(), replyTo: newest.guid, at: newest.at || Date.now() });
}

async function onUpdated(raw) {
  const r = readMessage(raw);
  if (!r.guid) return;
  const was = recent.get(r.guid);
  const chatId = r.chat ? chatIdOf(r.chat) : was?.chat ? chatIdOf(was.chat) : "";
  if (!chatId) return;
  if (r.unsent && !(was && was.unsent)) {
    recent.set(r.guid, { ...(was || r), unsent: r.unsent, text: "" });
    core.tellPython({ kind: "unsent", chat: chatId, key: keyOf(r.guid) });
    console.log(`${TAG} ${r.mine ? "A message to" : "A message from"} ${nameOfChat(chatId)} was unsent.`);
  } else if (r.edited && r.text && (!was || was.text !== r.text)) {
    recent.set(r.guid, { ...(was || r), text: r.text, edited: r.edited });
    core.tellPython({ kind: "edited", chat: chatId, key: keyOf(r.guid), text: logBody(r).text });
  }
}

function onTyping(d) {
  if (!d || !d.display || !d.guid) return;
  const chatId = chatIdOf({ guid: String(d.guid) });
  if (chatId) core.tellPython({ kind: "typing", chat: chatId });
}

/** A FaceTime call: on the Chats tab while it rings, and a text to say it could not be taken. */
function onFaceTime(raw, status = "") {
  let d = raw;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch { d = {}; } }
  const address = String(d?.caller || d?.address || d?.handle?.address || "");
  if (!address || d?.is_outgoing) return;
  const chatId = personId(address);
  if (!chatId) return;
  const state = status || String(d?.status || "incoming");
  if (state === "incoming") {
    core.tellPython({ kind: "call", chat: chatId, state: "ringing" });
    console.log(`${TAG} ${personName(address)} is calling on FaceTime.`);
    if (CALL_TEXT && chatGuidOf(chatId)) {
      core.handOver({ id: randomUUID(), user_id: chatId, user_name: personName(address), channel_id: chatId,
                      content: "[FaceTime call]", call: true });
    }
  } else if (state === "disconnected" || state === "ended") {
    core.tellPython({ kind: "call", chat: chatId, state: "ended" });
  }
}

function onEvent(name, data) {
  if (name === "new-message" || name === "group-name-change" || name.startsWith("participant-")) return onMessage(data);
  if (name === "updated-message") return onUpdated(data);
  if (name === "typing-indicator") return onTyping(data);
  if (name === "incoming-facetime") return onFaceTime(data, "incoming");
  if (name === "ft-call-status-changed") return onFaceTime(data);
  if (name === "message-send-error") {
    const r = readMessage(data);
    console.warn(`${TAG} The Mac could not send a message${r.chat ? ` to ${nameOfChat(chatIdOf(r.chat))}` : ""} (error ${r.error}).`);
  }
  return undefined;
}

/** What came in while it was not listening: since the newest it has dealt with (a day back at most; the last two
 *  minutes on a first start). Old ones are only kept, the bridge answers what is recent. */
async function catchUp() {
  const now = Date.now();
  const after = seen.at ? Math.max(seen.at - 15000, now - 24 * 3600 * 1000) : now - 120000;
  let list;
  try {
    list = await bb.messagesSince(after, { limit: 200 });
  } catch (e) {
    noteTrouble(e);
    return;
  }
  for (const m of Array.isArray(list) ? list : []) await onMessage(m);
  saveSeen();
}

// ── Answering ─────────────────────────────────────────────────────────────────

/** How it sends: the Private API when it can, else AppleScript (unless Settings says which). */
function method(needsPrivate = false) {
  if (SEND_METHOD === "apple-script" && !needsPrivate) return "apple-script";
  if (SEND_METHOD === "private-api" || needsPrivate) return "private-api";
  return papi ? "private-api" : "apple-script";
}

/** A reply's lines, one bubble each, as a person sends them (app/utils/split_response.py, for Discord). */
function bubbles(text) {
  const lines = String(text || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  return lines.length > 6 ? [...lines.slice(0, 5), lines.slice(5).join(" ")] : lines;
}

function noteSending(chatGuid, text) {
  const list = (sendingText.get(chatGuid) || []).filter((s) => Date.now() - s.at < 300000);
  list.push({ text, at: Date.now() });
  sendingText.set(chatGuid, list.slice(-20));
}

async function sendLine(chatGuid, line, replyTo = "", effectId = "") {
  const tempGuid = `temp-${randomUUID()}`;
  sentByUs.set(tempGuid, true);
  noteSending(chatGuid, line);
  const thread = replyTo && papi ? replyTo : "";
  const effect = effectId && papi && EFFECTS_ON ? effectId : "";
  const m = await bb.sendText({ chatGuid, message: line, method: method(!!(thread || effect)), tempGuid,
                                replyTo: thread || undefined, effectId: effect || undefined });
  if (m?.guid) {
    sentByUs.set(m.guid, true);
    markHandled(m.guid, m.dateCreated || Date.now());
    recent.set(m.guid, readMessage(m));
  }
  return m;
}

const MIME = { ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
               ".webp": "image/webp", ".heic": "image/heic", ".mp4": "video/mp4", ".mov": "video/quicktime",
               ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav" };

async function sendFile(chatGuid, chatId, name, file, { audio = false } = {}) {
  const ext = path.extname(file).toLowerCase();
  const data = fs.readFileSync(file);
  // As a phone names them: a photo IMG_1234, a voice message the Mac's own name for one.
  const onMac = audio ? "Audio Message.mp3" : `IMG_${1000 + Math.floor(Math.random() * 8999)}${ext === ".jpeg" ? ".jpg" : ext}`;
  if (DRY_RUN) {
    console.log(`  (dry run) ${audio ? "a voice message" : "a picture"} for ${name}`);
    return null;
  }
  const tempGuid = `temp-${randomUUID()}`;
  sentByUs.set(tempGuid, true);
  const m = await bb.sendAttachment({ chatGuid, data, name: onMac, mime: MIME[ext] || "application/octet-stream",
                                      method: method(), tempGuid, audio: audio && ext === ".mp3" });
  if (m?.guid) {
    sentByUs.set(m.guid, true);
    markHandled(m.guid, m.dateCreated || Date.now());
    share(chatId, name, [entryOf(readMessage(m))]);
  }
  console.log(`${TAG} ${audio ? "Voice message" : "Picture"} sent to ${name}`);
  return m;
}

/**
 * A reply, as a person sends one: their message read (a read receipt), a moment, a tapback when the persona taps
 * one, then each line typed (the dots) and sent as its own bubble, the first with an effect when it chose one. A
 * typo it was given is fixed a moment later, by editing the bubble, when `fixed` says what it meant.
 */
async function answer(chatGuid, chatId, name, text, { react = "", reactTo = "", replyTo = "", effect = "", fixed = "" } = {}) {
  if (READ_RECEIPTS && papi && !DRY_RUN) await bb.markRead(chatGuid).catch(() => {});
  await delay(700 + Math.random() * 1800);
  const tb = tapbackName(react);
  if (tb && reactTo && TAPBACKS_ON) {
    if (!papi) {
      console.log(`${TAG} Would have tapped back ${TAPBACKS[tb]} for ${name}: tapbacks need BlueBubbles' Private API.`);
    } else if (DRY_RUN) {
      console.log(`  (dry run) tapback ${TAPBACKS[tb]} for ${name}`);
    } else {
      try {
        await bb.react({ chatGuid, guid: reactTo, reaction: tb });
        const map = reactionsOf.get(reactTo) || new Map();
        map.set("me", { emoji: TAPBACKS[tb], mine: true });
        reactionsOf.set(reactTo, map);
        const t = recent.get(reactTo);
        if (t) share(chatId, name, [entryOf(t)]);
        console.log(`${TAG} Tapped back ${TAPBACKS[tb]} for ${name}`);
      } catch (e) {
        console.warn(`${TAG} The tapback for ${name} did not take: ${e.message}`);
      }
    }
    if (text) await delay(600 + Math.random() * 1400);
  }
  const lines = bubbles(text);
  const sent = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (TYPING && papi && !DRY_RUN) await bb.typing(chatGuid, true).catch(() => {});
    await delay(Math.min(core.typingTime(line), 14000));
    if (DRY_RUN) {
      console.log(`  (dry run) to ${name}: ${line}${i === 0 && effect ? " (with an effect)" : ""}`);
    } else {
      const m = await sendLine(chatGuid, line, i === 0 ? replyTo : "", i === 0 ? effect : "");
      sent.push(m || null);
    }
    if (i < lines.length - 1) await delay(500 + Math.random() * 1500);
  }
  if (TYPING && papi && !DRY_RUN && lines.length) await bb.typing(chatGuid, false).catch(() => {});
  const gone = sent.filter(Boolean);
  if (gone.length) share(chatId, name, gone.map((m) => entryOf(readMessage(m))));
  if (fixed && FIX_TYPOS && papi && !DRY_RUN) await fixTypos(chatId, name, lines, bubbles(fixed), sent);
  return { ok: true, sent: gone };
}

/** The bubble it sent with a slip in it, edited to what it meant, as people do a few seconds after sending. Only a
 *  bubble that is the same one, with a slip: never a rewrite. */
async function fixTypos(chatId, name, said, meant, sent) {
  if (said.length !== meant.length) return;
  for (let i = 0; i < said.length; i++) {
    const m = sent[i];
    if (!m?.guid || said[i] === meant[i] || Math.abs(said[i].length - meant[i].length) > 3) continue;
    await delay(2500 + Math.random() * 7000);
    try {
      await bb.edit(m.guid, meant[i]);
      const r = recent.get(m.guid);
      if (r) recent.set(m.guid, { ...r, text: meant[i] });
      core.tellPython({ kind: "edited", chat: chatId, key: keyOf(m.guid), text: meant[i] });
      console.log(`${TAG} Fixed a typo in what it sent ${name}`);
    } catch (e) {
      console.warn(`${TAG} Could not fix the typo for ${name}: ${e.message}`);
    }
  }
}

/** Whether to answer in a thread: never, always, or when others wrote in the chat after what it answers. */
function threadFor(chatId, p) {
  if (!p?.replyTo || THREAD_REPLIES === "never") return "";
  if (THREAD_REPLIES === "always") return p.replyTo;
  return (lastIn.get(chatId) || 0) > (p.at || 0) + 1 ? p.replyTo : "";
}

/** The conversation with someone it has no chat with yet: started, with the first thing it says. */
async function startChat(address, text = "") {
  const clean = String(address || "").trim();
  const bare = clean.replace(/[\s().-]/g, "");
  if (!/^\+?\d{6,20}$/.test(bare) && !/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(clean)) {
    return { ok: false, reason: "a phone number (with its country code) or an email address" };
  }
  const addr = /^\+?\d/.test(bare) && !clean.includes("@") ? bare : clean;
  const chatId = personId(addr);
  let service = "iMessage";
  if (papi) {
    const av = await bb.availability(addr).catch(() => null);
    if (av && av.available === false) service = "SMS";
  }
  const known = loadContacts();
  known[chatId] = { ...(known[chatId] || {}), address: addr, name: personName(addr), seen: Date.now() / 1000, service };
  saveContacts();
  if (!text) return { ok: true, chat: chatId, service, started: false };
  if (DRY_RUN) return { ok: true, chat: chatId, service, started: false, dry: true };
  const tempGuid = `temp-${randomUUID()}`;
  sentByUs.set(tempGuid, true);
  const chat = await bb.newChat({ addresses: [addr], message: text, method: method(), tempGuid, service });
  if (chat?.guid) {
    known[chatId].guid = chat.guid;
    saveContacts();
    for (const m of chat.messages || []) {
      if (m?.guid) { sentByUs.set(m.guid, true); markHandled(m.guid, m.dateCreated); }
    }
  }
  return { ok: true, chat: chatId, service, started: true };
}

/** Text to someone, in their chat, or in a new one when there is none yet (a person it has never written to). */
async function sendTo(chatId, name, text, opts = {}) {
  const guid = chatGuidOf(chatId);
  if (guid) return await answer(guid, chatId, name, text, opts);
  const address = loadContacts()[chatId]?.address || addressOf(chatId);
  if (!address) return { ok: false, reason: "no conversation with them yet" };
  const lines = bubbles(text);
  const first = await startChat(address, lines[0] || "");
  if (!first.ok) return first;
  const rest = lines.slice(1).join("\n");
  if (rest && chatGuidOf(chatId)) return await answer(chatGuidOf(chatId), chatId, name, rest, {});
  return { ok: true };
}

async function drainResponses() {
  const now = Date.now();
  for (const [id, p] of pending) if (now - p.ts > RESPONSE_TTL_MS) pending.delete(id);
  const waiting = core.responses();
  for (const id of Object.keys(waiting)) {
    if (!core.sendAllowed()) break;
    const val = core.take(id);
    if (val == null) continue;
    const obj = val && typeof val === "object" ? val : { text: String(val) };
    const p = pending.get(id) || {};
    pending.delete(id);
    const chatId = String(obj.chat || p.chatId || "");
    const name = String(obj.name || p.name || nameOfChat(chatId));
    const text = String(obj.text || "");
    const react = String(obj.react || "");
    if (!chatId || (!text && !react)) continue;
    // Answered by hand from the Mac or the iPhone since: the bot's answer is not sent on top.
    if ((elsewhere.get(chatId) || 0) > (p.at || obj.at || 0) && (p.at || obj.at)) {
      console.log(`${TAG} Not sending the reply to ${name}: someone answered from the Mac or the iPhone.`);
      continue;
    }
    const attempts = (Number(obj._attempts) || 0) + 1;
    let out;
    try {
      out = await sendTo(chatId, name, text, { react, reactTo: String(obj.react_to || p.replyTo || ""),
                                               replyTo: threadFor(chatId, p), effect: String(obj.effect || ""),
                                               fixed: String(obj.fixed || "") });
    } catch (e) {
      out = { ok: false, reason: e.message, again: !e.auth };
    }
    if (out.ok) {
      core.recordSend();
      if (text) console.log(`  sent to ${name}${DRY_RUN ? " (dry run)" : ""}`);
    } else if (out.again !== false && attempts < 3) {
      core.putBack(id, { ...obj, chat: chatId, name, at: p.at || obj.at, _attempts: attempts });
      break;
    } else {
      console.warn(`${TAG} Not sent to ${name}: ${out.reason || "it would not go"}.`);
    }
  }
}

/** Messages the bridge sends on its own: a Reply from the panel, a nudge, a picture, a voice message. */
async function processOutgoing() {
  const outgoing = readJson(core.files.outgoing, []);
  if (!Array.isArray(outgoing) || !outgoing.length || !core.sendAllowed()) return;
  const entry = outgoing[0];
  writeJson(core.files.outgoing, outgoing.slice(1));
  const { chat, message, image, voice } = entry || {};
  if (!chat || (!message && !image && !voice)) return;
  const name = entry.name || nameOfChat(chat);
  let guid = chatGuidOf(chat);
  try {
    if (!guid && message) {
      await sendTo(chat, name, message);
      core.recordSend();
      return;
    }
    if (!guid) {
      console.warn(`${TAG} No conversation with ${name} to send that to.`);
      return;
    }
    if (image && fs.existsSync(image)) await sendFile(guid, chat, name, image);
    if (voice) {
      if (!VOICE_NOTES) console.warn(`${TAG} Voice messages are off for this account (Settings, iMessage).`);
      else if (fs.existsSync(voice)) await sendFile(guid, chat, name, voice, { audio: true });
      try { fs.unlinkSync(voice); } catch { /* already gone */ }
    }
    if (message) await answer(guid, chat, name, message, {});
    core.recordSend();
  } catch (e) {
    console.warn(`${TAG} Not sent to ${name}: ${e.message}`);
  }
}

// ── The panel's requests ──────────────────────────────────────────────────────

function needsPrivate(what) {
  return papi ? null : { ok: false, reason: `${what} need BlueBubbles' Private API, which is off on the Mac` };
}

async function panelRequest(req) {
  if (req.op === "state") {
    return { ok: true, server: bb.host, live: !!feed?.connected, private_api: !!info.private_api,
             helper: !!info.helper_connected, account: String(info.detected_imessage || info.detected_icloud || ""),
             macos: String(info.os_version || ""), bluebubbles: String(info.server_version || "") };
  }
  // iMessage has no friend requests: anyone can write to anyone.
  if (req.op === "friends") return { ok: true, requests: [] };
  if (req.op === "friend") return { ok: false, reason: "iMessage has no requests to answer" };
  if (req.op === "add_friend") return await startChat(String(req.username || req.address || ""), String(req.text || ""));
  const chatId = String(req.chat || "");
  if (!/^(im_[a-z0-9_]{1,77}|img_[a-z0-9]{4,40})$/.test(chatId)) return { ok: false, reason: "which chat?" };
  const name = String(req.name || nameOfChat(chatId));
  const chatGuid = chatGuidOf(chatId);
  if (req.op === "history") {
    if (!chatGuid) return { ok: true, messages: [] };
    const msgs = await readChat(chatGuid, Math.max(10, Math.min(200, Number(req.limit) || 60)));
    return { ok: true, messages: msgs.map(entryOf) };
  }
  if (req.op === "send") {
    const text = String(req.text || "").slice(0, 4000);
    const images = (Array.isArray(req.images) ? req.images : []).filter((p) => typeof p === "string" && fs.existsSync(p));
    if (!text && !images.length) return { ok: false, reason: "nothing to send" };
    let guid = chatGuid;
    if (!guid && text) {
      const r = await startChat(loadContacts()[chatId]?.address || addressOf(chatId), text);
      if (!r.ok) return r;
      guid = chatGuidOf(chatId);
      core.recordSend();
      return { ok: true, messages: [], sent: "" };
    }
    if (!guid) return { ok: false, reason: "no conversation with them yet: write to them first" };
    for (const p of images) await sendFile(guid, chatId, name, p);
    let replied = false;
    const sent = [];
    if (text) {
      const target = guidOfKey(req.reply_to);
      if (target && papi) replied = true;
      const m = DRY_RUN ? null : await sendLine(guid, text, target);
      if (m) sent.push(m);
      if (DRY_RUN) console.log(`  (dry run) to ${name}: ${text}`);
    }
    core.recordSend();
    const messages = sent.map((m) => entryOf(readMessage(m)));
    return { ok: true, messages, sent: messages.length ? messages[messages.length - 1].key : "",
             replied: req.reply_to ? replied : undefined };
  }
  if (req.op === "react") {
    const no = needsPrivate("Tapbacks");
    if (no) return no;
    const target = guidOfKey(req.key);
    const tb = tapbackName(req.emoji);
    if (!target) return { ok: false, reason: "which message?" };
    if (!tb) return { ok: false, reason: `iMessage only has ${Object.values(TAPBACKS).join(" ")}` };
    await bb.react({ chatGuid, guid: target, reaction: req.remove ? `-${tb}` : tb });
    const map = reactionsOf.get(target) || new Map();
    if (req.remove) map.delete("me");
    else map.set("me", { emoji: TAPBACKS[tb], mine: true });
    reactionsOf.set(target, map);
    return { ok: true, reactions: reactionsFor(target) };
  }
  if (req.op === "unsend" || req.op === "edit") {
    const no = needsPrivate(req.op === "edit" ? "Edits" : "Unsending");
    if (no) return no;
    const target = guidOfKey(req.key);
    if (!target) return { ok: false, reason: "which message?" };
    if (req.op === "unsend") await bb.unsend(target);
    else await bb.edit(target, String(req.text || "").slice(0, 4000));
    return { ok: true };
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

// ── The Mac, and how it is ────────────────────────────────────────────────────

/** What it does without, said on its card: the Private API off, or its helper not connected. */
function missing() {
  if (!info.private_api) {
    return "BlueBubbles' Private API is off on the Mac: no typing dots, read receipts or tapbacks.";
  }
  if (!info.helper_connected) {
    return "BlueBubbles' Private API helper is not connected on the Mac: no typing dots, read receipts or tapbacks.";
  }
  if (!info.detected_imessage && !info.detected_icloud) return "The Mac does not seem to be signed in to iMessage.";
  return "";
}

let troubleSaid = "";
function noteTrouble(e) {
  const why = String(e?.message || e);
  if (why !== troubleSaid) console.warn(`${TAG} ${why}`);
  troubleSaid = why;
}

async function readInfo() {
  info = (await bb.serverInfo()) || {};
  papi = !!(info.private_api && info.helper_connected);
  return info;
}

/** The server, until it answers with its password taken. Says why on the card while it waits. */
async function reach() {
  for (let attempt = 0; ; attempt++) {
    try {
      await bb.ping();
      await readInfo();
      troubleSaid = "";
      return;
    } catch (e) {
      if (e.auth) {
        core.setState("needs-you", `BlueBubbles on ${bb.host} refused its password. Change it on the Accounts page.`);
        noteTrouble(new Error(`BlueBubbles on ${bb.host} refused the password.`));
        await delay(60000);
        continue;
      }
      const wait = [10, 20, 30, 60, 120][Math.min(attempt, 4)];
      core.setState("logged-out", `${e.message}. It tries again in ${wait} s.`);
      noteTrouble(e);
      await delay(wait * 1000);
    }
  }
}

async function recordIdentity() {
  const handle = String(info.detected_imessage || info.detected_icloud || "");
  let card = null;
  if (papi) card = await bb.ownCard().catch(() => null);
  const cardName = String(card?.name || card?.displayName
    || [card?.first_name || card?.firstName, card?.last_name || card?.lastName].filter(Boolean).join(" ") || "").trim();
  let before = {};
  try { before = JSON.parse(fs.readFileSync(IDENTITY_FILE, "utf-8")); } catch { /* first time */ }
  let picture = before.picture || "";
  if (card?.avatar) {
    try {
      const buf = Buffer.from(String(card.avatar), "base64");
      const ext = buf[0] === 0x89 ? "png" : "jpg";
      const file = `identity_imessage_${ACCOUNT}.${ext}`;
      fs.writeFileSync(path.join(DATA_DIR, "config", file), buf);
      picture = file;
    } catch { /* the card keeps what it had */ }
  }
  const out = {
    username: handle, display_name: cardName || (handle ? personName(handle) : "") || handle, picture,
    server: bb.host, macos: String(info.os_version || ""), bluebubbles: String(info.server_version || ""),
    private_api: !!info.private_api, helper: !!info.helper_connected, at: Date.now() / 1000,
  };
  try { writeJson(IDENTITY_FILE, out); } catch { /* the card keeps what it had */ }
  if (before.username !== out.username && handle) console.log(`${TAG} The Mac is signed in to iMessage as ${handle}.`);
}

function onFeedState(state, why) {
  if (state === "connected") {
    console.log(`${TAG} Live: new messages arrive the moment the Mac has them.`);
    enqueue(catchUp);
  } else if (state === "lost") {
    console.warn(`${TAG} The live feed dropped (${why}); looking every ${Math.round(core.jitteredPoll() / 1000)} s until it is back.`);
  } else if (state === "refused") {
    noteTrouble(new Error(`The live feed was refused (${why}).`));
  }
}

async function main() {
  if (!SERVER || !bb.base) {
    console.error(`${TAG} iMessage account ${ACCOUNT} has no BlueBubbles server saved. Add it on the Accounts page.`);
    core.ensureFiles();
    core.setState("needs-you", "No BlueBubbles server is saved for it. Add one on the Accounts page.");
    await delay(5000);
    process.exit(1);
  }
  if (!PASSWORD) {
    console.error(`${TAG} iMessage account ${ACCOUNT} has no BlueBubbles password saved. Add it on the Accounts page.`);
    core.ensureFiles();
    core.setState("needs-you", "Its BlueBubbles password is not saved. Add it on the Accounts page.");
    await delay(5000);
    process.exit(1);
  }
  core.ensureFiles();
  core.connectWake();
  core.setState("starting", `connecting to ${bb.host}`);
  console.log(`${TAG} Starting account #${ACCOUNT} through BlueBubbles on ${bb.host}${DRY_RUN ? ", DRY RUN: nothing is sent" : ""}.`);
  await reach();
  console.log(`${TAG} Connected: macOS ${info.os_version || "?"}, BlueBubbles ${info.server_version || "?"}, `
    + `Private API ${papi ? "on" : info.private_api ? "on, helper not connected" : "off"}.`);
  await loadBook().catch((e) => console.warn(`${TAG} The Mac's address book could not be read (${e.message}): people are shown by their number.`));
  await recordIdentity().catch(() => {});
  feed = liveFeed(bb, { onEvent: (name, data) => enqueue(() => onEvent(name, data)), onState: onFeedState });
  await enqueue(catchUp);
  core.setState("ready", missing());
  console.log(`${TAG} Ready. ${Math.round(core.minGap / 1000)} to ${Math.round(core.maxGap / 1000)}s between sends, at most ${core.perHour} an hour${core.quiet ? `, quiet ${core.quiet}` : ""}.`);

  let lastCatch = Date.now(), lastHealth = Date.now(), lastBook = Date.now();
  while (true) {
    core.heartbeatState();
    try {
      await processPanel();
      await drainResponses();
      await processOutgoing();
      const now = Date.now();
      // A look anyway, now and then: the live feed is for speed, this is so nothing is ever missed.
      if (now - lastCatch > (feed.connected ? 120000 : core.jitteredPoll())) {
        lastCatch = now;
        enqueue(catchUp);
      }
      if (now - lastHealth > 10 * 60000) {
        lastHealth = now;
        const was = `${papi}|${info.detected_imessage}`;
        try {
          await readInfo();
          troubleSaid = "";
          if (`${papi}|${info.detected_imessage}` !== was) await recordIdentity().catch(() => {});
          core.setState("ready", missing());
        } catch (e) {
          noteTrouble(e);
          if (e.auth) core.setState("needs-you", `BlueBubbles on ${bb.host} refused its password. Change it on the Accounts page.`);
          else core.setState("logged-out", `${e.message}. It keeps trying.`);
        }
      }
      if (now - lastBook > 6 * 3600 * 1000) {
        lastBook = now;
        await loadBook().catch(() => {});
        await recordIdentity().catch(() => {});
      }
      saveSeen();
    } catch (e) {
      console.error(`${TAG} Loop error: ${e.message}`);
    }
    await core.sleepOrPoke(1500);
  }
}

main().catch((err) => {
  console.error(`${TAG} Fatal error:`, err);
  process.exit(1);
});
