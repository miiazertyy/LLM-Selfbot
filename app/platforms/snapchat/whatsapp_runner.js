/**
 * The WhatsApp account: its chats, its groups, the statuses it watches and puts up, and the calls it cannot
 * take. Laid out like imessage_runner.js, because they are the same kind of thing - a texting platform whose
 * messages arrive the moment they are sent, rather than a page walked on a timer.
 *
 * So there is no poll here in the sense the browser runners have one. WhatsApp pushes; the loop exists to answer
 * what the bridge wrote back, to do the slow things (statuses, groups), and to check in. The one thing that is
 * paced like a poll is burst coalescing: several messages in a row are one thought, and answering each line of
 * it separately is the plainest sign in the world that nobody is holding the phone.
 *
 * Its login is the folder of keys a person's phone handed over. Without that folder there is nothing to run: it
 * exits 4 and waits, which is what the supervisor reads as "a person has to".
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import WhatsAppBot, { CHAT_ID, describe, forUs, isGroupId, jidOf } from "./whatsappbot.js";
import { createCore, createBudget, keyed, readJson, writeJson, delay } from "./runner_core.js";
import { patchConsole } from "./log.js";

patchConsole();

const TAG = "[WhatsApp]";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.WHATSAPP_DATA_DIR || process.env.SNAP_DATA_DIR || path.resolve(HERE, "../../../");
const ACCOUNT = parseInt(process.env.WHATSAPP_ACCOUNT_INDEX || "1", 10) || 1;

const envFor = (name) => process.env[`${name}_${ACCOUNT}`] ?? (ACCOUNT === 1 ? process.env[name] : "") ?? "";
const NUMBER = String(envFor("WHATSAPP_NUMBER") || "").replace(/\D/g, "");

const AUTH_DIR = path.join(DATA_DIR, "config", `whatsapp-${NUMBER}-auth`);
const IDENTITY_FILE = path.join(DATA_DIR, "config", `identity_whatsapp_${ACCOUNT}.json`);
const PEOPLE_DIR = path.join(DATA_DIR, "cache", "whatsapp_people");
const CONTACTS_FILE = path.join(PEOPLE_DIR, `contacts_${ACCOUNT}.json`);
const SEEN_FILE = path.join(PEOPLE_DIR, `seen_${ACCOUNT}.json`);
const SYSTEM_CHATS = ["whatsapp", "0", "status"];
// Asked to go, in a group, by name. Narrow on purpose: "leave" on its own is half of what gets said in a
// group about leaving anywhere, and leaving by mistake cannot be undone from here.
const ASKED_TO_LEAVE = /\b(leave (this|the) (group|chat)|get out of (this|the) (group|chat)|remove yourself)\b/i;

const core = createCore({
  prefix: "wa", env: "WHATSAPP", account: ACCOUNT, dataDir: DATA_DIR, tag: TAG,
  // What it runs at when the settings file has no whatsapp: section - one written before this platform existed.
  // The same numbers as resources/config.yaml, so a fresh install and an old one behave alike.
  defaults: {
    POLL_INTERVAL_MS: 20000, RESPONSE_TIMEOUT_MS: 120000, BURST_MS: 4000, ACCEPT_UNKNOWN: false,
    MIN_SEND_GAP_MS: 4000, MAX_SEND_GAP_MS: 20000, MAX_SENDS_PER_HOUR: 60,
    ONLINE: false, TYPING: true, READ_RECEIPTS: false,
    GROUPS: true, ONLY_WHEN_NAMED: true, GROUPS_PER_PASS: 4, LEAVE_ON_REQUEST: false,
    STATUS_WATCH: true, STATUS_POST: false, STATUS_PER_DAY: 1,
    DECLINE_CALLS: true, CALL_SAY_WHY: true, CALL_TEXT: "",
    VOICE_NOTES: true, PICTURES: true,
    WATCH: true, THEIR_STATUS: true,
  },
});

const DRY_RUN = core.flag("DRY_RUN", false);
const FAKE = process.env.WHATSAPP_FAKE === "1";
const LOCALE = core.text("LOCALE", "en-US");
const MONTH_FIRST = !/^(en-GB|fr|de|es|it|pt|nl|pl|ru)/i.test(LOCALE);
const TRIGGER = core.text("TRIGGER", "");
const BURST_MS = core.num("BURST_MS", 4000);
const RESPONSE_TTL_MS = core.num("RESPONSE_TIMEOUT_MS", 120000) * 3;
const ACCEPT_UNKNOWN = core.flag("ACCEPT_UNKNOWN", false);
const ONLINE = core.flag("ONLINE", false);
const TYPING = core.flag("TYPING", true);
const READ_RECEIPTS = core.flag("READ_RECEIPTS", false);
const GROUPS_ON = core.flag("GROUPS", true);
const ONLY_WHEN_NAMED = core.flag("ONLY_WHEN_NAMED", true);
const LEAVE_ON_REQUEST = core.flag("LEAVE_ON_REQUEST", false);
const STATUS_WATCH = core.flag("STATUS_WATCH", true);
const STATUS_POST = core.flag("STATUS_POST", false);
const DECLINE_CALLS = core.flag("DECLINE_CALLS", true);
const CALL_SAY_WHY = core.flag("CALL_SAY_WHY", true);
const CALL_TEXT = core.text("CALL_TEXT", "");
const VOICE_NOTES = core.flag("VOICE_NOTES", true);
const PICTURES = core.flag("PICTURES", true);
const WATCH = core.flag("WATCH", true);
const THEIR_STATUS = core.flag("THEIR_STATUS", true);
const GROUPS_PER_PASS = core.num("GROUPS_PER_PASS", 4);

fs.mkdirSync(PEOPLE_DIR, { recursive: true });
const budget = createBudget(path.join(PEOPLE_DIR, `budget_${ACCOUNT}.json`), {
  statuses: core.num("STATUS_PER_DAY", 1),
});

let bot = null;
const pending = new Map();        // what was handed over and is waiting on an answer
const bursts = new Map();         // chat id -> { at, messages, timer }
const keysOf = new Map();         // chat id -> the newest message key, for reacting and read receipts
const rawOf = new Map();          // message id -> the message as WhatsApp sent it, for its file
let lastCall = 0;
let lastGroupPass = 0;

// ── Who it has talked to ────────────────────────────────────────────────────

function contacts() {
  return readJson(CONTACTS_FILE, {});
}

function remember(chatId, name, extra) {
  if (!chatId) return;
  const all = contacts();
  const now = { ...(all[chatId] || {}) };
  if (name && name !== chatId) now.name = String(name).slice(0, 80);
  if (extra && typeof extra === "object") Object.assign(now, extra);
  now.seen = Math.floor(Date.now() / 1000);
  all[chatId] = now;
  writeJson(CONTACTS_FILE, all);
}

function known(chatId) {
  return !!contacts()[chatId];
}

function recordIdentity() {
  writeJson(IDENTITY_FILE, {
    username: bot.me || NUMBER, name: bot.name || `+${bot.me || NUMBER}`,
    at: Math.floor(Date.now() / 1000),
  });
}

// ── What is said to it ──────────────────────────────────────────────────────

function keyedChat(chatId, messages) {
  // keyed() is given the whole conversation at once: it counts the same words said twice in a day, which it can
  // only do by seeing all of them.
  return keyed(chatId, messages.map((m) => ({ ...m, text: describe(m) })), { monthFirst: MONTH_FIRST, prefix: "w" });
}

function share(chatId, name, messages) {
  core.tellPython({ kind: "transcript", chat: chatId, name: name || chatId,
                    messages: keyedChat(chatId, messages).slice(-120) });
}

/**
 * A message, in. Nothing is answered here: it goes into that chat's burst, which is handed over once the other
 * person has stopped typing for BURST_MS. They arrive instantly, so without that it would answer each line.
 */
function onMessage(m, raw) {
  if (!m.chat) {
    // A status, not a conversation: watched rather than answered.
    if (STATUS_WATCH && !m.mine) noteStatus(m);
    return;
  }
  if (m.mine) return;
  if (SYSTEM_CHATS.includes(String(m.author || "")) || SYSTEM_CHATS.includes(String(m.name || "").toLowerCase())) {
    return;
  }
  if (m.group && !GROUPS_ON) return;
  if (!m.group && !ACCEPT_UNKNOWN && !known(m.chat)) {
    console.log(`${TAG} Not answering ${m.author}: not a number it knows.`);
    return;
  }
  if (m.group && ONLY_WHEN_NAMED && !forUs(m, TRIGGER, bot.me)) return;
  if (m.group && LEAVE_ON_REQUEST && ASKED_TO_LEAVE.test(m.text) && forUs(m, TRIGGER, bot.me)) {
    // Said to it, by name, in a group: it goes rather than argue about it.
    console.log(`${TAG} Asked to leave ${m.name || m.chat}, so leaving.`);
    bot.leaveGroup(m.chat).catch(() => {});
    core.tellPython({ kind: "left", chat: m.chat });
    return;
  }
  if (m.reaction) {
    // A reaction is worth knowing about, never worth answering.
    core.tellPython({ kind: "reaction", chat: m.chat, emoji: m.reaction.emoji, to: m.reaction.to });
    return;
  }
  remember(m.chat, m.name, m.group ? { group: true } : null);
  if (m.key && m.key.id) keysOf.set(m.chat, m.key);
  if (raw && m.media.length) {
    rawOf.set(m.id, raw);
    // The newest few hundred only: this is for looking at what was just sent, not a record.
    if (rawOf.size > 300) rawOf.delete(rawOf.keys().next().value);
  }

  const burst = bursts.get(m.chat) || { messages: [], timer: null };
  burst.messages.push(m);
  if (burst.timer) clearTimeout(burst.timer);
  burst.timer = setTimeout(() => handOver(m.chat), BURST_MS);
  bursts.set(m.chat, burst);
  if (TYPING) bot.typing(m.chat, true).catch(() => {});
}

/** The burst, once they have stopped: one thought, handed over once. */
function handOver(chatId) {
  const burst = bursts.get(chatId);
  bursts.delete(chatId);
  if (!burst || !burst.messages.length) return;
  const all = burst.messages;
  const last = all[all.length - 1];
  const content = all.map(describe).join("\n").slice(0, 4000);
  const key = `${last.id}|${content.slice(0, 80)}`;
  if (!core.isNew(chatId, key)) return;
  const id = `${chatId}:${last.id}`;
  pending.set(id, { at: Date.now(), chat: chatId });
  const row = contacts()[chatId] || {};
  core.handOver({
    id,
    user_id: chatId,
    user_name: last.name || row.name || chatId,
    channel_id: chatId,
    content,
    group: last.group || undefined,
    photo: true,
  });
  share(chatId, last.name || row.name, all);
  if (READ_RECEIPTS && keysOf.get(chatId)) bot.readReceipt(chatId, keysOf.get(chatId)).catch(() => {});
  console.log(`  ${last.name || chatId}: ${content.slice(0, 80)}`);
}

/**
 * Who a status of its own goes to: the numbers it has talked to.
 *
 * WhatsApp decides this per status and keeps no list of its own that a linked device can read, so this is the
 * nearest honest answer - the people in its own contacts file. Groups are left out: a status is not sent to one.
 */
function statusAudience() {
  const all = contacts();
  return Object.keys(all)
    .filter((c) => CHAT_ID.test(c) && !isGroupId(c))
    // The ones it has heard from most recently first, since WhatsApp will not take an unbounded list.
    .sort((a, b) => ((all[b] || {}).seen || 0) - ((all[a] || {}).seen || 0))
    .slice(0, 200)
    .map((c) => jidOf(c))
    .filter(Boolean);
}

/** A status somebody put up, looked at the way the persona looks at everything else. */
function noteStatus(m) {
  // watch.enabled is whether it looks at what people send at all; watch.their_status is this one kind of it.
  if (!WATCH || !THEIR_STATUS) return;
  core.tellPython({ kind: "posts", chat: m.author ? `wa_${m.author}` : "", newest: m.id, fresh: true });
}

/**
 * The groups it is in, read now and then.
 *
 * Nothing is said here: this is so a group is known before somebody in it says something - its name for the chat
 * list, how many are in it, and whether it is still in it at all. GROUPS_PER_PASS keeps a long list from being
 * walked in one go.
 */
async function groupPass() {
  if (!GROUPS_ON || !bot.live) return;
  if (Date.now() - lastGroupPass < 15 * 60000) return;
  lastGroupPass = Date.now();
  const all = await bot.groups().catch(() => []);
  if (!all.length) return;
  const known = contacts();
  // The ones it knows least about first, so a new group is read before one it saw an hour ago.
  const order = all.sort((a, b) => ((known[a.chat] || {}).read || 0) - ((known[b.chat] || {}).read || 0));
  for (const g of order.slice(0, Math.max(1, GROUPS_PER_PASS))) {
    remember(g.chat, g.name, { group: true, people: g.people || 0, admin: !!g.admin,
                               read: Math.floor(Date.now() / 1000) });
  }
  const here = new Set(all.map((g) => g.chat));
  const gone = Object.keys(known).filter((c) => isGroupId(c) && !here.has(c));
  if (gone.length) console.log(`${TAG} No longer in ${gone.length} group(s).`);
}

/** A call it cannot take. Declining is the point: an unanswered phone is what a dead account looks like. */
async function onCall(call) {
  if (!DECLINE_CALLS) return;
  if (Date.now() - lastCall < 20000) return;        // WhatsApp retries an offer; one decline is enough
  lastCall = Date.now();
  const chatId = call.from ? `wa_${call.from}` : "";
  try {
    await bot.sock.rejectCall?.(call.id, jidOf(chatId));
  } catch { /* it may have rung out already */ }
  core.tellPython({ kind: "call", chat: chatId, state: "declined" });
  if (!CALL_SAY_WHY || !chatId) return;
  if (CALL_TEXT) {
    if (core.sendAllowed()) {
      await bot.sendText(chatId, CALL_TEXT);
      core.recordSend();
    }
    return;
  }
  // Nothing written for it: the persona says why in its own words, through the bridge.
  const id = `call:${call.id || Date.now()}`;
  pending.set(id, { at: Date.now(), chat: chatId });
  core.handOver({
    id,
    user_id: chatId,
    user_name: (contacts()[chatId] || {}).name || chatId,
    channel_id: chatId,
    content: "[they tried to call, and you could not pick up]",
  });
}

// ── Sending what the bridge wrote ───────────────────────────────────────────

async function drainResponses() {
  const now = Date.now();
  for (const [id, info] of [...pending]) if (now - info.at > RESPONSE_TTL_MS) pending.delete(id);
  const answers = core.responses();
  for (const id of Object.keys(answers)) {
    if (!core.sendAllowed()) break;
    const taken = core.take(id);
    if (taken === null) continue;
    const text = typeof taken === "string" ? taken : String(taken.text || "");
    const chatId = (taken && taken.chat) || (pending.get(id) || {}).chat || "";
    if (!CHAT_ID.test(chatId) || !text.trim()) { pending.delete(id); continue; }
    if (DRY_RUN) {
      console.log(`${TAG} DRY RUN, not sent to ${chatId}: ${text.slice(0, 80)}`);
      pending.delete(id);
      continue;
    }
    if (TYPING) {
      await bot.typing(chatId, true).catch(() => {});
      await delay(core.typingTime(text));
    }
    const out = await bot.sendText(chatId, text);
    if (TYPING) await bot.typing(chatId, false).catch(() => {});
    if (out && out.ok) {
      pending.delete(id);
      core.recordSend();
      continue;
    }
    const why = String((out && out.reason) || "");
    const attempts = (typeof taken === "object" && taken._attempts) || 0;
    if (attempts >= 4 || /not-authorized|forbidden|blocked|not on whatsapp/i.test(why)) {
      console.warn(`${TAG} Giving up on one answer: ${why}`);
      pending.delete(id);
      continue;
    }
    core.putBack(id, typeof taken === "object" ? { ...taken, _attempts: attempts + 1 }
                                               : { text: taken, _attempts: 1 });
    core.setState("waiting", why);
    break;
  }
}

/** Messages the bridge sends on its own: a Reply from the panel, a nudge, a picture, a voice note. */
async function processOutgoing() {
  const queue = readJson(core.files.outgoing, []);
  if (!queue.length) return;
  const item = queue[0];
  // The tail is written back first: a crash drops one, never loops it.
  writeJson(core.files.outgoing, queue.slice(1));
  const chatId = String(item.chat || "");
  if (!CHAT_ID.test(chatId)) return;
  if (item.image && PICTURES) await bot.sendImage(chatId, item.image, "").catch(() => {});
  if (item.voice && VOICE_NOTES) await bot.sendVoice(chatId, item.voice).catch(() => {});
  if (item.message) {
    if (TYPING) await bot.typing(chatId, true).catch(() => {});
    await delay(core.typingTime(item.message) * 0.25);
    const out = await bot.sendText(chatId, item.message);
    if (TYPING) await bot.typing(chatId, false).catch(() => {});
    if (out && out.ok) core.recordSend();
  }
}

// ── What the panel asks for ─────────────────────────────────────────────────

async function panelRequest(req) {
  const op = String(req.op || "");
  const p = req.payload || {};
  try {
    if (op === "state") {
      return { ok: true, linked: bot.linked(), number: bot.me || NUMBER, name: bot.name,
               live: !!bot.live, since: bot.since };
    }
    if (op === "history") {
      const chatId = String(p.chat || p.chat_id || "");
      if (!CHAT_ID.test(chatId)) return { ok: false, reason: "not a chat id" };
      // WhatsApp keeps no history a linked device may ask for: what there is, is what was seen.
      return { ok: true, messages: [] };
    }
    if (op === "send") {
      const chatId = String(p.chat || "");
      if (!CHAT_ID.test(chatId)) return { ok: false, reason: "not a chat id" };
      const out = await bot.sendText(chatId, String(p.text || ""));
      if (out.ok) core.recordSend();
      return out;
    }
    if (op === "react") {
      const chatId = String(p.chat || "");
      const key = keysOf.get(chatId);
      if (!key) return { ok: false, reason: "nothing recent to react to" };
      return await bot.react(chatId, key.id, String(p.emoji || "\u{1F44D}"));
    }
    if (op === "friends") return { ok: true, friends: contacts() };
    if (op === "groups") return { ok: true, groups: await bot.groups() };
    if (op === "group") {
      const chatId = String(p.chat || "");
      if (!isGroupId(chatId)) return { ok: false, reason: "not a group" };
      if (!LEAVE_ON_REQUEST && p.leave) return { ok: false, reason: "leaving groups is switched off" };
      return p.leave ? await bot.leaveGroup(chatId) : { ok: true, group: (await bot.groups())
        .find((g) => g.chat === chatId) || null };
    }
    if (op === "status") {
      const seen = readJson(SEEN_FILE, {});
      return { ok: true, statuses: Object.values(seen).slice(-40) };
    }
    if (op === "post_status") {
      if (!STATUS_POST && !p.dry_run) return { ok: false, reason: "putting up statuses is switched off" };
      if (!budget.allowed("statuses")) return { ok: false, reason: "no statuses left today" };
      if (p.dry_run || DRY_RUN) return { ok: true, dry: true };
      const out = await bot.postStatus(String(p.text || ""), String(p.picture || ""), statusAudience());
      if (out.ok) budget.spend("statuses");
      return out;
    }
    if (op === "presence") {
      await bot.presence(!!p.online);
      return { ok: true };
    }
    if (op === "fetch") {
      const raw = rawOf.get(String(p.key || ""));
      if (!raw) return { ok: false, reason: "that message is not here any more" };
      const file = await bot.captureMedia(raw);
      return file ? { ok: true, file } : { ok: false, reason: "nothing came back" };
    }
    if (op === "out") {
      return { ok: true, left: { statuses: budget.left("statuses") },
               used: { statuses: budget.used("statuses") } };
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

// ── The loop ────────────────────────────────────────────────────────────────

async function main() {
  if (!NUMBER) {
    console.error(`${TAG} No WhatsApp account ${ACCOUNT}: add one on the Accounts page.`);
    process.exit(1);
  }
  if (!FAKE && !fs.existsSync(path.join(AUTH_DIR, "creds.json"))) {
    // Its keys ARE its login: a person made them by linking a phone. Without them there is nothing to run, and
    // nothing this process can do about that.
    console.error(`${TAG} WhatsApp account ${ACCOUNT} (+${NUMBER}) has not been linked. `
                  + "Link it on the Accounts page.");
    core.ensureFiles();
    core.setState("needs-you", "It has not been linked to a phone yet. Link it on the Accounts page.");
    process.exit(4);               // a person has to: not started again by itself
  }

  bot = new WhatsAppBot({ account: ACCOUNT, number: NUMBER, dataDir: DATA_DIR, tag: TAG,
                          fake: FAKE ? await fakeSocket() : null });
  bot.onMessage = (m, raw) => {
    try { onMessage(m, raw); } catch (e) { console.error(`${TAG} Reading a message went wrong: ${e.message}`); }
  };
  bot.onCall = (c) => { onCall(c).catch(() => {}); };
  bot.onState = (state, detail) => {
    core.setState(state, detail || "");
    if (state === "needs-you") {
      // The phone unlinked it. Started again it would sit there unlinked for ever.
      console.error(`${TAG} ${detail}`);
      setTimeout(() => process.exit(4), 2000);
    }
  };

  core.ensureFiles();
  core.connectWake();
  core.setState("starting", "connecting to WhatsApp");
  console.log(`${TAG} Starting +${NUMBER} (account #${ACCOUNT})${DRY_RUN ? ", DRY RUN: nothing is sent" : ""}.`);
  await bot.connect({ online: ONLINE });

  for (let i = 0; i < 60 && !bot.live; i++) await delay(1000);
  if (bot.live) {
    recordIdentity();
    core.setState("ready");
    console.log(`${TAG} Ready as +${bot.me || NUMBER}. ${core.minGap / 1000}-${core.maxGap / 1000}s between `
                + `sends, at most ${core.perHour} an hour${core.quiet ? `, quiet ${core.quiet}` : ""}.`);
  }

  while (true) {
    core.heartbeatState();
    try {
      await processPanel();
      await drainResponses();
      await processOutgoing();
      await groupPass();
      if (Date.now() - (bot.since || 0) > 4 * 3600 * 1000 && bot.live) recordIdentity();
    } catch (e) {
      console.error(`${TAG} Loop error: ${e.message}`);
    }
    // Nothing to poll: WhatsApp pushes. This is the check-in, and what wakes it when the bridge writes.
    await core.sleepOrPoke(Math.min(core.jitteredPoll(), 20000));
  }
}

/**
 * The stand-in socket the tests use: the whole loop runs against it with nothing reaching WhatsApp.
 *
 * Everything it is asked to do is written to WHATSAPP_FAKE_SENT, a line of JSON each, because the test is not in
 * this process and that file is the only way it can see what the runner did. WHATSAPP_FAKE_EVENTS is what
 * WhatsApp "sends": an array of messages, or {messages, calls} for both.
 */
async function fakeSocket() {
  const file = process.env.WHATSAPP_FAKE_EVENTS || "";
  const canned = file && fs.existsSync(file) ? readJson(file, []) : [];
  const events = Array.isArray(canned) ? { messages: canned, calls: [] } : canned;
  const log = process.env.WHATSAPP_FAKE_SENT || "";
  const sent = [];
  const listeners = {};
  const note = (what) => {
    sent.push(what);
    if (log) { try { fs.appendFileSync(log, `${JSON.stringify(what)}\n`); } catch { /* the test went away */ } }
  };
  return {
    sent,
    user: { id: `${NUMBER}:1@s.whatsapp.net`, name: "Fake" },
    async sendMessage(jid, content) {
      note({ did: "send", jid, content });
      return { key: { id: `fake${sent.length}` } };
    },
    async sendPresenceUpdate(state, jid) { note({ did: "presence", state, jid: jid || "" }); },
    async readMessages(keys) { note({ did: "read", keys }); },
    async rejectCall(id, from) { note({ did: "decline", id, from }); },
    async groupFetchAllParticipating() {
      return Object.fromEntries((events.groups || []).map((g) => [g.id, g]));
    },
    async groupLeave(jid) { note({ did: "leave", jid }); },
    end() {},
    // Baileys' own event bus, in the small: the bot binds its handlers to this exactly as it would to the real
    // one, so a fixture holds what WhatsApp emits and the handlers that read it are the real ones.
    ev: {
      on(name, fn) { (listeners[name] || (listeners[name] = [])).push(fn); },
      emit(name, payload) { for (const fn of listeners[name] || []) fn(payload); },
    },
    bind() {
      // Everything the fixture holds, played in as if WhatsApp had just sent it.
      setTimeout(() => {
        this.ev.emit("messages.upsert", { type: "notify", messages: events.messages || [] });
        // History arriving behind it: the same messages again, which must not be answered twice.
        this.ev.emit("messages.upsert", { type: "append", messages: events.messages || [] });
        if ((events.calls || []).length) this.ev.emit("call", events.calls);
      }, 50);
    },
  };
}

main().catch((err) => {
  console.error(`${TAG} Fatal error:`, err);
  process.exit(1);
});
