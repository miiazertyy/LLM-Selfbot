/**
 * WhatsApp, spoken to directly: the connection, and the shapes the runner needs.
 *
 * There is no page here and no browser. WhatsApp's own multi-device protocol runs over a WebSocket, and the
 * baileys package speaks it - the same protocol the WhatsApp app on a linked phone or desktop uses. So unlike
 * every other platform in this folder there are no selectors, nothing to scrape, and nothing that breaks when a
 * redesign moves a button. What breaks instead is the protocol itself, which WhatsApp changes without notice;
 * that shows up as a connection that will not open, which the card says plainly.
 *
 * Split the way bluebubbles.js / imessage_runner.js are: the transport and the shapes live here so they can be
 * tested on their own (tests/whatsapp_logic.mjs), and the loop lives in whatsapp_runner.js. Everything below the
 * class is pure - a WhatsApp message in, the app's own shape out - and that is the half worth testing, because
 * it is the half that is easy to get quietly wrong.
 *
 * Its login is the folder of keys a person's phone handed over when they linked it
 * (config/whatsapp-<number>-auth), which is what a browser profile is to the other platforms. Without it there is
 * nothing to run.
 */
import fs from "fs";
import path from "path";
import { agentFor } from "./runner_core.js";

export const AUTH_SUFFIX = "-auth";

/** WhatsApp's own id for a person: their number, then the server. A group's ends @g.us, a status @broadcast. */
const PERSON = /^(\d{5,20})(?::\d+)?@s\.whatsapp\.net$/;
const GROUP = /^([\w-]{5,40})@g\.us$/;
const STATUS = "status@broadcast";

/** The number out of a JID, however much of it WhatsApp put there. "" when it is not a person's. */
export function numberOf(jid) {
  const m = PERSON.exec(String(jid || ""));
  return m ? m[1] : "";
}

/** The group's own id out of a JID, "" when it is not a group's. */
export function groupOf(jid) {
  const m = GROUP.exec(String(jid || ""));
  return m ? m[1] : "";
}

/** A person's chat id: "wa_" and their number. */
export function chatIdFor(jid) {
  const n = numberOf(jid);
  return n ? `wa_${n}` : "";
}

/** A group's chat id: "wag_" and its own id, with the punctuation WhatsApp allows taken out. */
export function groupIdFor(jid) {
  const g = groupOf(jid) || String(jid || "").split("@")[0];
  const clean = String(g).replace(/[^A-Za-z0-9-]/g, "");
  return clean ? `wag_${clean}` : "";
}

/** Either, from whichever kind of JID it is. "" for a status, which is nobody's conversation. */
export function idOf(jid) {
  const s = String(jid || "");
  if (s === STATUS) return "";
  return s.endsWith("@g.us") ? groupIdFor(s) : chatIdFor(s);
}

/**
 * Back the other way: the JID a chat id means. "wag_" is tested first, as every other platform's group prefix
 * is, so a chat id is never read as the wrong kind.
 */
export function jidOf(chatId) {
  const id = String(chatId || "");
  if (id.startsWith("wag_")) return `${id.slice(4)}@g.us`;
  if (id.startsWith("wa_")) return `${id.slice(3)}@s.whatsapp.net`;
  return "";
}

export const CHAT_ID = /^(wa_\d{5,20}|wag_[A-Za-z0-9-]{5,40})$/;

export function isGroupId(chatId) {
  return String(chatId || "").startsWith("wag_");
}

/**
 * What a WhatsApp message actually is, flattened.
 *
 * WhatsApp wraps a message in whichever of forty-odd shapes it is, and sometimes wraps that again
 * (ephemeralMessage, viewOnceMessage, documentWithCaptionMessage). Everything that reads a message goes through
 * here, so there is one place that knows the shapes - and one place to fix when WhatsApp adds the next one.
 */
export function unwrap(message) {
  let m = message || {};
  for (let i = 0; i < 5; i++) {
    const inner = m.ephemeralMessage?.message || m.viewOnceMessage?.message
      || m.viewOnceMessageV2?.message || m.viewOnceMessageV2Extension?.message
      || m.documentWithCaptionMessage?.message || m.editedMessage?.message;
    if (!inner) break;
    m = inner;
  }
  return m;
}

/** The words in a message, wherever this kind of message keeps them. */
export function textOf(message) {
  const m = unwrap(message);
  return String(
    m.conversation
    || m.extendedTextMessage?.text
    || m.imageMessage?.caption
    || m.videoMessage?.caption
    || m.documentMessage?.caption
    || m.buttonsResponseMessage?.selectedDisplayText
    || m.listResponseMessage?.title
    || m.templateButtonReplyMessage?.selectedDisplayText
    || "",
  ).trim();
}

/** What kind of thing it is, in the app's own words: "", photo, video, voice, audio, sticker, file, location… */
export function kindOf(message) {
  const m = unwrap(message);
  if (m.imageMessage) return "photo";
  if (m.videoMessage) return m.videoMessage.gifPlayback ? "gif" : "video";
  if (m.audioMessage) return m.audioMessage.ptt ? "voice" : "audio";
  if (m.stickerMessage) return "sticker";
  if (m.documentMessage) return "file";
  if (m.locationMessage || m.liveLocationMessage) return "location";
  if (m.contactMessage || m.contactsArrayMessage) return "contact";
  if (m.pollCreationMessage || m.pollCreationMessageV3) return "poll";
  if (m.reactionMessage) return "reaction";
  if (m.protocolMessage) return m.protocolMessage.type === 0 ? "deleted" : "";
  return "";
}

/** The quoted message, when this one is a reply: what it said and who said it. */
export function quotedOf(message) {
  const ctx = unwrap(message).extendedTextMessage?.contextInfo
    || unwrap(message).imageMessage?.contextInfo
    || unwrap(message).videoMessage?.contextInfo
    || unwrap(message).audioMessage?.contextInfo;
  const inner = ctx?.quotedMessage;
  if (!inner) return null;
  return {
    id: String(ctx.stanzaId || ""),
    from: numberOf(ctx.participant) || "",
    text: textOf(inner),
    kind: kindOf(inner),
  };
}

/**
 * One WhatsApp message as the rest of the app wants it. `me` is the account's own number, so its own messages
 * are known as its own without guessing.
 *
 * Everything the runner and the panel read comes out of this one function, which is why it is exported and
 * tested against real-shaped messages rather than against a page.
 */
export function shape(raw, me = "") {
  const key = raw?.key || {};
  const remote = String(key.remoteJid || "");
  const group = remote.endsWith("@g.us");
  const status = remote === STATUS;
  // In a group the sender is the participant; one to one it is whoever the chat is with.
  const senderJid = group || status ? String(key.participant || raw?.participant || "") : remote;
  const body = unwrap(raw?.message || {});
  const reaction = body.reactionMessage || null;
  const at = Number(raw?.messageTimestamp || 0) * 1000 || 0;
  return {
    id: String(key.id || ""),
    chat: status ? "" : idOf(remote),
    group,
    status,
    mine: !!key.fromMe,
    author: numberOf(senderJid) || (key.fromMe ? String(me || "") : ""),
    name: String(raw?.pushName || ""),
    text: reaction ? "" : textOf(raw?.message),
    kind: kindOf(raw?.message),
    quoted: quotedOf(raw?.message),
    reaction: reaction ? { to: String(reaction.key?.id || ""), emoji: String(reaction.text || "") } : null,
    // Its own key, which is what WhatsApp wants back to react to it or to mark it read.
    key: { remoteJid: remote, id: String(key.id || ""), fromMe: !!key.fromMe,
           ...(key.participant ? { participant: String(key.participant) } : {}) },
    // Where the file is, for whatever wants to look at it; the runner fetches it through the socket.
    media: hasMedia(raw?.message) ? [{ kind: kindOf(raw?.message), id: String(key.id || "") }] : [],
    at,
    day: "",
  };
}

/** Whether there is a file on it at all: what captureMedia can be asked for. */
export function hasMedia(message) {
  const m = unwrap(message);
  return !!(m.imageMessage || m.videoMessage || m.audioMessage || m.stickerMessage || m.documentMessage);
}

/** What a message is when it has no words: the line the brain reads instead. */
export function describe(m) {
  if (m.text) return m.text;
  if (m.reaction) return `[reacted ${m.reaction.emoji}]`;
  const said = {
    photo: "[photo]", video: "[video]", gif: "[gif]", voice: "[voice note]", audio: "[audio]",
    sticker: "[sticker]", file: "[file]", location: "[location]", contact: "[contact]", poll: "[poll]",
    deleted: "[deleted it]",
  }[m.kind];
  return said || "[message]";
}

/** Whether a group message is for it: its own name said, or a reply to something it said. */
export function forUs(m, trigger, me = "") {
  if (!m.group) return true;
  if (m.quoted && m.quoted.from && String(m.quoted.from) === String(me)) return true;
  const names = String(trigger || "").split(",").map((n) => n.trim()).filter(Boolean);
  if (!names.length) return false;
  const said = String(m.text || "").toLowerCase();
  // Whole words only: the names are a list ("John, Jon"), and each is looked for on its own.
  return names.some((n) => new RegExp(`\\b${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(said));
}

/**
 * WhatsApp, connected. One socket, and everything the runner does to it.
 */
export default class WhatsAppBot {
  constructor({ account = 1, number = "", dataDir, tag = "[WhatsApp]", fake = null } = {}) {
    this.account = account;
    this.number = String(number || "").replace(/\D/g, "");
    this.dataDir = dataDir;
    this.tag = tag;
    //: A stand-in socket, for the tests: the whole loop runs against it with nothing reaching WhatsApp.
    this.fake = fake;
    this.sock = null;
    this.me = "";
    this.name = "";
    this.live = false;
    this.since = 0;
    this.gone = false;
    this.onMessage = () => {};
    this.onCall = () => {};
    this.onState = () => {};
  }

  authDir() {
    return path.join(this.dataDir, "config", `whatsapp-${this.number || "unknown"}${AUTH_SUFFIX}`);
  }

  linked() {
    return fs.existsSync(path.join(this.authDir(), "creds.json"));
  }

  /** Open the connection. Baileys reconnects itself; what this adds is saying so, and giving up on a logout. */
  async connect({ online = false } = {}) {
    if (this.fake) {
      this.sock = this.fake;
      this.me = this.number;
      this.live = true;
      this.since = Date.now();
      // The same handlers the real socket gets. Only the transport is fake.
      this.listen();
      this.fake.bind?.(this);
      this.onState("ready", "");
      return true;
    }
    const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } =
      await import("baileys");
    const { state, saveCreds } = await useMultiFileAuthState(this.authDir());
    const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));
    // Its own proxy, set when it was added: the connection, and what it uploads and fetches.
    const agent = await agentFor(process.env.WHATSAPP_PROXY);
    this.sock = makeWASocket({
      auth: state,
      version,
      ...(agent ? { agent, fetchAgent: agent } : {}),
      printQRInTerminal: false,
      browser: ["LLMSelfbot", "Desktop", "1.0.0"],
      syncFullHistory: false,
      markOnlineOnConnect: !!online,
    });
    this.sock.ev.on("creds.update", saveCreds);
    this.sock.ev.on("connection.update", (up) => {
      const { connection, lastDisconnect } = up;
      if (connection === "open") {
        this.live = true;
        this.since = Date.now();
        this.me = String(this.sock.user?.id || "").split(":")[0].split("@")[0].replace(/\D/g, "") || this.number;
        this.name = String(this.sock.user?.name || this.sock.user?.verifiedName || "");
        this.onState("ready", "");
      } else if (connection === "close") {
        this.live = false;
        const code = lastDisconnect?.error?.output?.statusCode;
        if (code === DisconnectReason?.loggedOut) {
          // The phone unlinked this device. Nothing here can undo that: a person links it again.
          this.gone = true;
          this.onState("needs-you", "The phone unlinked it. Link it again on the Accounts page.");
        } else {
          this.onState("logged-out", "The connection dropped; it comes back by itself.");
        }
      }
    });
    this.listen();
    return true;
  }

  /**
   * What arrives: messages and calls. Its own method because the stand-in socket the tests use is wired through
   * it too, so what a test exercises is these handlers and not a second copy of them.
   */
  listen() {
    this.sock.ev.on("messages.upsert", (up) => {
      // "notify" is a message as it happens. The other kinds are history being filled in behind it, which would
      // otherwise be answered as if it had just been said.
      if (up?.type !== "notify") return;
      // The shape for everything that reads it, and the message itself for anything that wants its file:
      // downloadMediaMessage needs the whole thing, not a flattened copy of it.
      for (const raw of up.messages || []) this.onMessage(shape(raw, this.me), raw);
    });
    this.sock.ev.on("call", (calls) => {
      for (const c of calls || []) {
        // An offer is a phone ringing; the rest of the states are it being picked up or given up on elsewhere.
        if (c?.status === "offer") this.onCall({ id: String(c.id || ""), from: numberOf(c.from) || "", at: Date.now() });
      }
    });
  }

  async sendText(chatId, text, { quote = null } = {}) {
    const jid = jidOf(chatId);
    if (!jid) return { ok: false, reason: "not a chat id" };
    try {
      await this.sock.sendMessage(jid, { text: String(text || "") }, quote ? { quoted: quote } : {});
      return { ok: true };
    } catch (e) {
      return { ok: false, reason: e.message };
    }
  }

  async sendImage(chatId, file, caption = "") {
    const jid = jidOf(chatId);
    if (!jid) return { ok: false, reason: "not a chat id" };
    try {
      await this.sock.sendMessage(jid, { image: { url: file }, caption: String(caption || "") });
      return { ok: true };
    } catch (e) {
      return { ok: false, reason: e.message };
    }
  }

  /** A voice note, which is what everybody actually sends on WhatsApp: ptt, so it draws as one. */
  async sendVoice(chatId, file) {
    const jid = jidOf(chatId);
    if (!jid) return { ok: false, reason: "not a chat id" };
    try {
      await this.sock.sendMessage(jid, { audio: { url: file }, ptt: true, mimetype: "audio/ogg; codecs=opus" });
      return { ok: true };
    } catch (e) {
      return { ok: false, reason: e.message };
    }
  }

  async react(chatId, messageId, emoji) {
    const jid = jidOf(chatId);
    if (!jid || !messageId) return { ok: false, reason: "nothing to react to" };
    try {
      await this.sock.sendMessage(jid, { react: { text: String(emoji || ""), key: { remoteJid: jid, id: messageId } } });
      return { ok: true };
    } catch (e) {
      return { ok: false, reason: e.message };
    }
  }

  /** The typing dots, and taking them away. WhatsApp shows them until something says otherwise. */
  async typing(chatId, on = true) {
    const jid = jidOf(chatId);
    if (!jid) return;
    try {
      await this.sock.sendPresenceUpdate(on ? "composing" : "paused", jid);
    } catch { /* presence is never worth failing a send over */ }
  }

  async readReceipt(chatId, key) {
    const jid = jidOf(chatId);
    if (!jid || !key) return;
    try {
      await this.sock.readMessages([key]);
    } catch { /* the same */ }
  }

  async presence(online) {
    try {
      await this.sock.sendPresenceUpdate(online ? "available" : "unavailable");
    } catch { /* the same */ }
  }

  /** The groups it is in, with their names, so the panel and the loop both know what they are. */
  async groups() {
    try {
      const all = await this.sock.groupFetchAllParticipating();
      return Object.values(all || {}).map((g) => ({
        chat: groupIdFor(g.id), name: String(g.subject || ""),
        people: (g.participants || []).length,
        admin: (g.participants || []).some((p) => numberOf(p.id) === this.me && p.admin),
      })).filter((g) => g.chat);
    } catch {
      return [];
    }
  }

  async leaveGroup(chatId) {
    const jid = jidOf(chatId);
    if (!jid || !isGroupId(chatId)) return { ok: false, reason: "not a group" };
    try {
      await this.sock.groupLeave(jid);
      return { ok: true };
    } catch (e) {
      return { ok: false, reason: e.message };
    }
  }

  /** Put up a status, which WhatsApp sends as a message to a broadcast address. */
  /**
   * A status, put up for `to` - the JIDs of the people who should be able to open it.
   *
   * That list is not a filter on top of "everybody": WhatsApp has no "everybody" here. A status is encrypted for
   * the devices in it and for nobody else, so an empty list is a status that goes up and that no one can read.
   */
  async postStatus(text, file = "", to = []) {
    const list = [...new Set((to || []).map(String).filter((j) => j.endsWith("@s.whatsapp.net")))];
    if (!list.length) return { ok: false, reason: "nobody to put it up for yet" };
    try {
      const content = file ? { image: { url: file }, caption: String(text || "") } : { text: String(text || "") };
      await this.sock.sendMessage(STATUS, content, { statusJidList: list });
      return { ok: true, to: list.length };
    } catch (e) {
      return { ok: false, reason: e.message };
    }
  }

  /** A file off a message, saved where the rest of the app can look at it. */
  async captureMedia(raw) {
    try {
      const { downloadMediaMessage } = await import("baileys");
      // The fourth argument is what makes an old message work: WhatsApp's media URLs expire after a few hours,
      // and reuploadRequest is how a linked device asks for the file to be put back up.
      const buf = await downloadMediaMessage(raw, "buffer", {}, {
        reuploadRequest: this.sock.updateMediaMessage,
        logger: this.sock.logger,
      });
      if (!buf || !buf.length) return "";
      const kind = kindOf(raw?.message);
      const ext = { photo: ".jpg", sticker: ".webp", video: ".mp4", gif: ".mp4", voice: ".ogg",
                    audio: ".ogg" }[kind] || ".bin";
      const dir = path.join(this.dataDir, "cache", "whatsapp_media");
      fs.mkdirSync(dir, { recursive: true });
      const file = path.join(dir, `wa_${Date.now()}_${Math.random().toString(36).slice(2, 8)}${ext}`);
      fs.writeFileSync(file, buf);
      return file;
    } catch {
      return "";
    }
  }

  async close() {
    try { this.sock?.end?.(undefined); } catch { /* going away anyway */ }
  }
}
