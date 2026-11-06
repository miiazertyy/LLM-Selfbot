/**
 * platforms/snapchat/bluebubbles.js
 *
 * A BlueBubbles Server, spoken to from here: how this computer reads and sends iMessages. iMessage only runs on
 * Apple's own machines, so a Mac signed in to it runs BlueBubbles Server (bluebubbles.app, free and open source),
 * which serves its Messages over a REST API and socket.io. What is used here was read off BlueBubbles' own source
 * (v1.9.9, packages/server/src/server/api/http). Node's own fetch and WebSocket speak both: nothing to install, no
 * browser.
 *
 * Also the shapes the iMessage runner needs, here so they can be tested on their own (tests/imessage_logic.mjs): who
 * a chat is in the app (its id, from its BlueBubbles chat), a tapback's emoji and name, what a message is when it is
 * not words.
 */
import { createHash } from "crypto";

// ── The server's address ──────────────────────────────────────────────────────

/** BlueBubbles Server's own port, which an address on the network is usually typed without. */
const DEFAULT_PORT = "1234";

/** A host on this network rather than a tunnel's or a domain's: an IP, a .local name, a computer's own name. */
const onTheNetwork = (host) => /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.startsWith("[") || /\.local$/i.test(host)
  || !host.includes(".");

/** A BlueBubbles address as people paste one ("192.168.1.20:1234", "https://abc.trycloudflare.com/", the API's own
 *  ".../api/v1"), as its base: scheme, host, port, no trailing slash. "" for nothing usable. Typed bare, with no port,
 *  one on the network gets BlueBubbles' own port (1234) and a domain gets https, as tunnels serve it. */
export function serverUrl(raw) {
  let s = String(raw || "").trim();
  if (!s) return "";
  const bare = !/^[a-z][a-z0-9+.-]*:\/\//i.test(s);
  if (bare) s = `http://${s}`;
  let u;
  try { u = new URL(s); } catch { return ""; }
  if (!/^https?:$/.test(u.protocol) || !u.hostname) return "";
  // Whether a port was typed is read off what was typed: URL drops a typed :80.
  if (bare && !/:\d+$/.test(s.slice(7).split(/[/?#]/)[0].replace(/^\[[^\]]*\]/, ""))) {
    if (onTheNetwork(u.hostname)) u.port = DEFAULT_PORT;
    else u.protocol = "https:";
  }
  u.hash = "";
  u.search = "";
  u.pathname = u.pathname.replace(/\/api\/v1\/?.*$/i, "").replace(/\/+$/, "");
  return u.toString().replace(/\/+$/, "");
}

/** The host a base names, for what is shown (never its password, which rides in the query). */
export function hostOf(base) {
  try { return new URL(base).host; } catch { return String(base || ""); }
}

// ── REST ──────────────────────────────────────────────────────────────────────

export class BBError extends Error {
  /** `auth`: the password was refused. `unreachable`: nothing answered at that address. `privateApi`: the call needs
   *  BlueBubbles' Private API, which is off or not connected on the Mac. */
  constructor(message, { status = 0, type = "", auth = false, unreachable = false, privateApi = false } = {}) {
    super(message);
    Object.assign(this, { status, type, auth, unreachable, privateApi });
  }
}

/** Why a request got no answer at all, in words. */
function unreachableWhy(e) {
  const code = String(e?.cause?.code || e?.code || "");
  if (e?.name === "TimeoutError" || /TIMEOUT/i.test(code)) return "it did not answer in time";
  if (code === "ECONNREFUSED") return "nothing is listening there (is BlueBubbles Server running?)";
  if (code === "ENOTFOUND" || code === "EAI_AGAIN") return "that address does not exist";
  if (/CERT|SSL|TLS/i.test(code + String(e?.cause?.message || ""))) return "its HTTPS certificate was refused";
  if (code === "ECONNRESET" || code === "UND_ERR_SOCKET") return "the connection was cut";
  return String(e?.cause?.message || e?.message || "no answer");
}

export class BlueBubbles {
  constructor({ url, password, timeoutMs = 30000 } = {}) {
    this.base = serverUrl(url);
    this.password = String(password || "");
    this.timeoutMs = timeoutMs;
  }

  get host() { return hostOf(this.base); }

  /** One call to the API: its `data`, or a BBError. `raw` gives the Response itself (a download). */
  async call(method, route, { query = {}, body, form, timeoutMs, raw = false } = {}) {
    if (!this.base) throw new BBError("no BlueBubbles server address", { unreachable: true });
    const params = new URLSearchParams({ password: this.password });
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
    const url = `${this.base}/api/v1/${String(route).replace(/^\/+/, "")}?${params}`;
    // ngrok's free tunnels put a page of their own in front of a browser; this says it is not one.
    const headers = { "ngrok-skip-browser-warning": "1" };
    if (body !== undefined) headers["content-type"] = "application/json";
    let res;
    try {
      res = await fetch(url, {
        method, headers, body: body !== undefined ? JSON.stringify(body) : form,
        signal: AbortSignal.timeout(timeoutMs ?? this.timeoutMs),
      });
    } catch (e) {
      throw new BBError(`${this.host} did not answer: ${unreachableWhy(e)}`, { unreachable: true });
    }
    if (raw && res.ok) return res;
    let data = null;
    try { data = await res.json(); } catch { /* not JSON: said below by its status */ }
    const status = Number(res.status || data?.status || 0);
    if (!res.ok || (data && Number(data.status) >= 400)) {
      const said = String(data?.error?.error || data?.error?.message || data?.message || res.statusText || "refused");
      const type = String(data?.error?.type || "");
      throw new BBError(said, {
        status, type, auth: status === 401,
        privateApi: /private api|helper/i.test(`${said} ${data?.message || ""}`),
      });
    }
    return data ? data.data : null;
  }

  ping() { return this.call("GET", "ping", { timeoutMs: 15000 }); }
  /** os_version, server_version, private_api, helper_connected, detected_icloud, detected_imessage, ... */
  serverInfo() { return this.call("GET", "server/info", { timeoutMs: 20000 }); }

  chats({ limit = 50, offset = 0 } = {}) {
    return this.call("POST", "chat/query", { body: { limit, offset, with: ["lastMessage", "participants"], sort: "lastmessage" } });
  }
  chat(guid) { return this.call("GET", `chat/${encodeURIComponent(guid)}`, { query: { with: "participants" } }); }

  /** A chat's messages, newest first unless `sort` says ASC; `before`/`after` in ms. */
  chatMessages(guid, { limit = 25, before, after, sort = "DESC" } = {}) {
    return this.call("GET", `chat/${encodeURIComponent(guid)}/message`,
                     { query: { limit, before, after, sort, with: "attachment,handle" } });
  }

  /** Every chat's messages since `after` (ms), oldest first: what came in while the live feed was down. */
  messagesSince(after, { limit = 200 } = {}) {
    return this.call("POST", "message/query", {
      body: { after: Math.max(0, Math.floor(after)), limit, sort: "ASC", with: ["chat", "chat.participants", "attachment", "handle"] },
    });
  }
  message(guid) { return this.call("GET", `message/${encodeURIComponent(guid)}`, { query: { with: "chats,attachment,handle" } }); }

  sendText({ chatGuid, message, method, tempGuid, replyTo, partIndex = 0, effectId, subject }) {
    const body = { chatGuid, message: String(message || ""), method, tempGuid };
    if (replyTo) Object.assign(body, { selectedMessageGuid: replyTo, partIndex });
    if (effectId) body.effectId = effectId;
    if (subject) body.subject = subject;
    return this.call("POST", "message/text", { body, timeoutMs: 120000 });
  }

  /** A file into a chat: a picture, or an MP3 sent as a voice message (BlueBubbles makes it Apple's own on the Mac). */
  async sendAttachment({ chatGuid, data, name, mime = "application/octet-stream", method, tempGuid, audio = false, replyTo }) {
    const form = new FormData();
    form.set("attachment", new Blob([data], { type: mime }), name);
    form.set("chatGuid", chatGuid);
    form.set("name", name);
    if (method) form.set("method", method);
    if (tempGuid) form.set("tempGuid", tempGuid);
    if (audio) form.set("isAudioMessage", "true");
    if (replyTo) form.set("selectedMessageGuid", replyTo);
    return this.call("POST", "message/attachment", { form, timeoutMs: 180000 });
  }

  /** A tapback (love, like, dislike, laugh, emphasize, question; "-love" takes one back). Private API. */
  react({ chatGuid, guid, reaction, partIndex = 0 }) {
    return this.call("POST", "message/react",
                     { body: { chatGuid, selectedMessageGuid: guid, reaction, partIndex }, timeoutMs: 90000 });
  }
  edit(guid, text, partIndex = 0) {
    return this.call("POST", `message/${encodeURIComponent(guid)}/edit`,
                     { body: { editedMessage: text, backwardsCompatibilityMessage: `Edited to “${text}”`, partIndex }, timeoutMs: 90000 });
  }
  unsend(guid, partIndex = 0) {
    return this.call("POST", `message/${encodeURIComponent(guid)}/unsend`, { body: { partIndex }, timeoutMs: 90000 });
  }
  /** "typing…" in the chat while it writes, and off again. Private API. */
  typing(chatGuid, on = true) {
    return this.call(on ? "POST" : "DELETE", `chat/${encodeURIComponent(chatGuid)}/typing`, { timeoutMs: 15000 });
  }
  markRead(chatGuid) { return this.call("POST", `chat/${encodeURIComponent(chatGuid)}/read`, { timeoutMs: 20000 }); }

  /** A conversation with someone new, by phone number or email. */
  newChat({ addresses, message = "", method, tempGuid, service = "iMessage" }) {
    const body = { addresses, method, tempGuid, service };
    if (message) body.message = message;
    return this.call("POST", "chat/new", { body, timeoutMs: 120000 });
  }
  /** Whether an address is on iMessage (else only SMS reaches it). Private API. */
  availability(address) {
    return this.call("GET", "handle/availability/imessage", { query: { address }, timeoutMs: 30000 });
  }

  /** An attachment's bytes, made viewable by BlueBubbles (a HEIC photo as a JPEG, a voice message as an MP3). */
  async download(guid, { width } = {}) {
    const res = await this.call("GET", `attachment/${encodeURIComponent(guid)}/download`,
                                { query: { original: "false", width }, raw: true, timeoutMs: 120000 });
    return { data: Buffer.from(await res.arrayBuffer()), mime: String(res.headers.get("content-type") || "") };
  }

  /** The Mac's address book, with each person's picture's thumbnail when asked (base64, in `avatar`). */
  contacts({ thumbnails = false } = {}) {
    return this.call("GET", "contact", { query: thumbnails ? { extraProperties: "contactImageThumbnail" } : {},
                                         timeoutMs: 60000 });
  }
  /** The account's own card, name and picture (Private API, macOS 12 and up). */
  ownCard() { return this.call("GET", "icloud/contact", { timeoutMs: 30000 }); }
}

// ── The live feed: socket.io, by hand ─────────────────────────────────────────
// BlueBubbles serves socket.io 4 (allowEIO3) on the same port, and checks the same password on the connection's
// query. Over a WebSocket, Engine.IO 4 is: "0{...}" open (with its ping interval), "2" a ping to answer "3", "1"
// close; and Socket.IO 4 inside it: "40" to connect, "40{sid}" connected, "41" let go, "44{...}" refused,
// "42[name, data]" an event.

/**
 * Connects, keeps the connection alive, reconnects when it drops (sooner at first, then every half minute), and
 * hands each event to `onEvent(name, data)`. `onState("connected" | "lost" | "refused", why)` says how it is.
 */
export function liveFeed(bb, { onEvent, onState = () => {}, WebSocketImpl = globalThis.WebSocket } = {}) {
  let ws = null, stopped = false, connected = false, retry = 0, retryTimer = null, watchdog = null;
  // BlueBubbles takes the connection, then checks the password and lets go of a wrong one at once: "connected" is
  // only said once it has held for a moment (or an event came), and a let-go inside that moment is a refusal.
  let announced = false, announceTimer = null;
  const HOLD_MS = 1500;
  const BACKOFF = [1000, 2000, 5000, 10000, 20000, 30000];
  function announce() {
    clearTimeout(announceTimer);
    if (announced || !connected) return;
    announced = true;
    retry = 0;
    onState("connected", "");
  }

  function feedUrl() {
    const u = new URL(`${bb.base}/socket.io/`);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.searchParams.set("EIO", "4");
    u.searchParams.set("transport", "websocket");
    u.searchParams.set("password", bb.password);
    return u.toString();
  }
  function arm(ms) {
    clearTimeout(watchdog);
    // No ping in that long: the connection is dead even if nothing said so.
    watchdog = setTimeout(() => { try { ws?.close(); } catch { /* gone */ } }, ms);
  }
  let pingWindow = 4 * 60 * 1000;
  function lost(why) {
    clearTimeout(watchdog);
    clearTimeout(announceTimer);
    const was = connected && announced;
    connected = false;
    announced = false;
    ws = null;
    if (stopped) return;
    if (was) onState("lost", why);
    const wait = BACKOFF[Math.min(retry, BACKOFF.length - 1)];
    retry += 1;
    retryTimer = setTimeout(open, wait);
  }
  function open() {
    if (stopped) return;
    if (typeof WebSocketImpl !== "function") {
      onState("refused", "this Node has no WebSocket (Node 22 or newer has one)");
      return;
    }
    let sock;
    try { sock = new WebSocketImpl(feedUrl()); } catch (e) { lost(String(e?.message || e)); return; }
    ws = sock;
    let ended = false;
    const end = (why) => { if (!ended) { ended = true; lost(why); } };
    sock.onmessage = (ev) => {
      const data = typeof ev.data === "string" ? ev.data : "";
      if (!data) return;                                 // binary frames: BlueBubbles sends none
      const kind = data[0];
      if (kind === "0") {
        try {
          const o = JSON.parse(data.slice(1));
          pingWindow = (Number(o.pingInterval) || 60000) + (Number(o.pingTimeout) || 120000) + 5000;
        } catch { /* the defaults, then */ }
        arm(pingWindow);
        sock.send("40");
      } else if (kind === "2") {
        sock.send("3");
        arm(pingWindow);
      } else if (kind === "1") {
        try { sock.close(); } catch { /* gone */ }
      } else if (kind === "4") {
        const sio = data[1];
        if (sio === "0") {
          connected = true;
          announceTimer = setTimeout(announce, HOLD_MS);
        } else if (sio === "1" || sio === "4") {
          // Let go before it held: the password, most likely (the REST calls say for sure). Once it has held,
          // being let go is the server going away or restarting: lost, and connected again.
          if (!announced) onState("refused", sio === "4" ? data.slice(2) : "the server let go of the live feed at once");
          try { sock.close(); } catch { /* gone */ }
        } else if (sio === "2") {
          let arr = null;
          try { arr = JSON.parse(data.slice(2).replace(/^\d+/, "")); } catch { return; }
          if (Array.isArray(arr) && typeof arr[0] === "string") {
            announce();
            try { onEvent(arr[0], arr[1]); } catch { /* the runner's own problem, said there */ }
          }
        }
      }
    };
    sock.onclose = (ev) => end(ev && ev.code ? `closed (${ev.code})` : "closed");
    sock.onerror = (ev) => end(String(ev?.message || ev?.error?.message || "connection error"));
  }

  open();
  return {
    get connected() { return connected && announced; },
    stop() {
      stopped = true;
      clearTimeout(retryTimer);
      clearTimeout(watchdog);
      clearTimeout(announceTimer);
      try { ws?.close(); } catch { /* gone */ }
    },
  };
}

// ── Who a chat is, in the app ─────────────────────────────────────────────────
// The app's ids are letters, digits, "_" and "-" (app/utils/snappeople.py). A person's is "im_" and their address:
// a phone number by its digits ("p" for its "+"), anything else (an email) with every character that is not a
// letter or a digit written as _<its code>_, so it reads back exactly. A group's is "img_" and its chat's number.

const sha1 = (s) => createHash("sha1").update(String(s)).digest("hex");

export function personId(address) {
  const a = String(address || "").trim().toLowerCase();
  if (!a) return "";
  const phone = a.replace(/[\s().-]/g, "");
  if (/^\+?\d{3,20}$/.test(phone)) return `im_${phone.startsWith("+") ? "p" : ""}${phone.replace("+", "")}`;
  let out = "";
  for (const ch of a) out += /[a-z0-9]/.test(ch) ? ch : `_${ch.codePointAt(0).toString(16)}_`;
  const id = `im_${out}`;
  return id.length <= 80 ? id : `im_h${sha1(a).slice(0, 24)}`;
}

/** The address a person's id was made from ("" for a group's, or one too long that was hashed). */
export function addressOf(id) {
  const s = String(id || "");
  if (!s.startsWith("im_") || /^im_h[0-9a-f]{24}$/.test(s)) return "";
  const rest = s.slice(3);
  if (/^p\d{3,20}$/.test(rest)) return `+${rest.slice(1)}`;
  if (/^\d{3,20}$/.test(rest)) return rest;
  try {
    return rest.replace(/_([0-9a-f]{1,6})_/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)));
  } catch {
    return "";
  }
}

/** A chat guid's parts: "iMessage;-;+15551234567" (a person), "iMessage;+;chat123456789" (a group). */
export function guidParts(guid) {
  const [service = "", kind = "", ident = ""] = String(guid || "").split(";");
  return { service, group: kind === "+", ident };
}

export function groupId(chat) {
  const ident = String(chat?.chatIdentifier || guidParts(chat?.guid).ident || "").toLowerCase();
  const m = ident.match(/^chat(\d{4,40})$/);
  return m ? `img_${m[1]}` : `img_h${sha1(chat?.guid || ident).slice(0, 20)}`;
}

export function isGroupChat(chat) {
  return Number(chat?.style) === 43 || guidParts(chat?.guid).group;
}

/** The app's id for a BlueBubbles chat. A person's is the same whatever the service (iMessage, SMS, RCS): the same
 *  person, the latest chat used to answer them. */
export function chatIdOf(chat) {
  if (!chat) return "";
  if (isGroupChat(chat)) return groupId(chat);
  return personId(guidParts(chat.guid).ident || chat.chatIdentifier || "");
}

/** Phone numbers compared as people write them: the same last nine digits are the same number. */
export function sameAddress(a, b) {
  const x = String(a || "").trim().toLowerCase(), y = String(b || "").trim().toLowerCase();
  if (!x || !y) return false;
  if (x.includes("@") || y.includes("@")) return x === y;
  const dx = x.replace(/\D/g, ""), dy = y.replace(/\D/g, "");
  if (dx.length < 6 || dy.length < 6) return dx === dy;
  return dx.slice(-9) === dy.slice(-9);
}

// ── Tapbacks ──────────────────────────────────────────────────────────────────

/** iMessage's six, by the names BlueBubbles takes and the emoji the app shows them as. */
export const TAPBACKS = { love: "❤️", like: "👍", dislike: "👎", laugh: "😂", emphasize: "‼️", question: "❓" };
const ALIASES = {
  love: ["❤", "♥️", "♥", "😍", "🥰", "💕", "💖", "💗", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍"],
  like: ["👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "👌"],
  dislike: ["👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿"],
  laugh: ["🤣", "😆", "😹", "haha", "lol"],
  emphasize: ["‼", "!!", "❗", "❕", "⁉️"],
  question: ["?", "❔", "🤔"],
};

/** The tapback an emoji is ("❤️" is "love"), or "" for one iMessage has no tapback for. */
export function tapbackName(emoji) {
  const e = String(emoji || "").trim();
  if (!e) return "";
  for (const [name, mark] of Object.entries(TAPBACKS)) if (e === mark || e === name) return name;
  for (const [name, list] of Object.entries(ALIASES)) if (list.includes(e.toLowerCase())) return name;
  return "";
}

const PICTOGRAPH = /\p{Extended_Pictographic}(?:\uFE0F|\u200D\p{Extended_Pictographic}|[\u{1F3FB}-\u{1F3FF}])*/u;

/** A message that is a tapback, as BlueBubbles gives it ("love", "-love" taken back, "2006" an emoji one of iOS 18
 *  with its emoji in the words, "sticker" one stuck on), or null. */
export function tapbackOf(type, text = "") {
  const t = String(type ?? "").trim();
  if (!t || t === "0" || t === "null") return null;
  const removed = t.startsWith("-") || /^3\d{3}$/.test(t);
  const name = t.replace(/^-/, "");
  if (TAPBACKS[name]) return { name, emoji: TAPBACKS[name], removed };
  if (name === "sticker" || t === "1000") return { name: "sticker", emoji: "🏷️", removed: false };
  if (/^[23]006$/.test(t)) {
    const m = String(text || "").match(PICTOGRAPH);
    return m ? { name: "emoji", emoji: m[0], removed } : null;
  }
  return /^[23]\d{3}$/.test(t) ? { name: "other", emoji: "👍", removed } : null;
}

/** The message a tapback is on: "p:0/<guid>" (its first part), "bp:<guid>", or the guid itself. */
export function tapbackTarget(associated) {
  return String(associated || "").replace(/^p:\d+\//, "").replace(/^bp:/, "");
}

// ── What a message is ─────────────────────────────────────────────────────────

// expressiveSendStyleId: the bubble effects and the screen effects, by the names the Messages app gives them.
export const EFFECTS = {
  "com.apple.MobileSMS.expressivesend.impact": "Slam", "com.apple.MobileSMS.expressivesend.loud": "Loud",
  "com.apple.MobileSMS.expressivesend.gentle": "Gentle", "com.apple.MobileSMS.expressivesend.invisibleink": "Invisible Ink",
  "com.apple.messages.effect.CKEchoEffect": "Echo", "com.apple.messages.effect.CKSpotlightEffect": "Spotlight",
  "com.apple.messages.effect.CKHappyBirthdayEffect": "Balloons", "com.apple.messages.effect.CKConfettiEffect": "Confetti",
  "com.apple.messages.effect.CKHeartEffect": "Love", "com.apple.messages.effect.CKLasersEffect": "Lasers",
  "com.apple.messages.effect.CKFireworksEffect": "Fireworks", "com.apple.messages.effect.CKSparklesEffect": "Celebration",
  "com.apple.messages.effect.CKShootingStarEffect": "Shooting Star",
};

/** What a message from an iMessage app is, by its balloon ("" for a link's preview, which is just the link). */
export function appOf(bundle) {
  const b = String(bundle || "");
  if (!b || b === "com.apple.messages.URLBalloonProvider") return "";
  if (/gamepigeon/i.test(b)) return "a GamePigeon game";
  if (/PeerPayment|ApplePay/i.test(b)) return "Apple Cash";
  if (/DigitalTouch/i.test(b)) return "a Digital Touch";
  if (/Handwriting/i.test(b)) return "a handwritten message";
  if (/findmy|location/i.test(b)) return "their location";
  if (/Polls?/i.test(b)) return "a poll";
  return "something from an iMessage app";
}

/** What an attachment is: "photo", "gif", "sticker", "video", "voice", "contact", or "file". */
export function mediaKind(a, message = {}) {
  const mime = String(a?.mimeType || "").toLowerCase();
  const uti = String(a?.uti || "").toLowerCase();
  const name = String(a?.transferName || "").toLowerCase();
  if (a?.isSticker) return "sticker";
  if (mime === "image/gif" || name.endsWith(".gif")) return "gif";
  if (mime.startsWith("image/") || /\.(heic|heif|jpe?g|png|webp)$/.test(name)) return "photo";
  if (mime.startsWith("video/") || /\.(mov|mp4|m4v)$/.test(name)) return "video";
  if (mime.startsWith("audio/") || uti.includes("coreaudio") || /\.(caf|m4a|mp3|amr|aac)$/.test(name)
      || message?.isAudioMessage) return "voice";
  if (mime.includes("vcard") || name.endsWith(".vcf")) return "contact";
  return "file";
}

// The character iMessage puts where an attachment sits in a message's words.
const OBJECT_MARK = /[\uFFFC\uFFFD]/g;

/**
 * A BlueBubbles message, as the runner uses it: whose chat, who sent it, its words, its media, and what else it is
 * (a tapback, a reply in a thread, an effect, a group's own news, an edit or an unsend).
 */
export function readMessage(m) {
  const chat = Array.isArray(m?.chats) && m.chats.length ? m.chats[0] : null;
  const shown = (m?.attachments || []).filter((a) => a && !a.hideAttachment
                                                   && !String(a.transferName || "").endsWith(".pluginPayloadAttachment"));
  const itemType = Number(m?.itemType || 0);
  const tapback = tapbackOf(m?.associatedMessageType, m?.text);
  let event = null;
  if (itemType === 1) event = { what: Number(m?.groupActionType) === 1 ? "removed" : "added", who: String(m?.otherHandle || "") };
  else if (itemType === 2) event = { what: "renamed", title: String(m?.groupTitle || "") };
  else if (itemType === 3) {
    const a = Number(m?.groupActionType);
    event = { what: a === 0 ? "left" : a === 1 ? "picture" : "picture removed" };
  }
  return {
    guid: String(m?.guid || ""),
    at: Number(m?.dateCreated || 0),
    mine: !!m?.isFromMe,
    address: String(m?.handle?.address || ""),
    service: String(m?.handle?.service || (chat ? guidParts(chat.guid).service : "") || ""),
    chat,
    chatGuid: String(chat?.guid || ""),
    group: chat ? isGroupChat(chat) : false,
    text: String(m?.text || "").replace(OBJECT_MARK, "").replace(/[ \t]{2,}/g, " ").trim(),
    subject: String(m?.subject || "").trim(),
    media: shown.map((a) => ({ guid: String(a.guid || ""), kind: mediaKind(a, m), mime: String(a.mimeType || ""),
                               name: String(a.transferName || ""), bytes: Number(a.totalBytes || 0) })),
    tapback: tapback ? { ...tapback, target: tapbackTarget(m?.associatedMessageGuid) } : null,
    replyTo: String(m?.threadOriginatorGuid || ""),
    effect: EFFECTS[String(m?.expressiveSendStyleId || "")] || "",
    app: appOf(m?.balloonBundleId),
    event,
    edited: Number(m?.dateEdited || 0),
    unsent: Number(m?.dateRetracted || 0),
    read: Number(m?.dateRead || 0),
    delivered: Number(m?.dateDelivered || 0),
    audio: !!m?.isAudioMessage,
    tempGuid: String(m?.tempGuid || ""),
    error: Number(m?.error || 0),
  };
}

const MEDIA_WORDS = {
  photo: "a photo", gif: "a GIF", sticker: "a sticker", video: "a video", voice: "a voice message",
  contact: "a contact card", file: "a file",
};

/** What a message says, for the AI: its words, and in brackets what it is when it is more than words. `quote` is the
 *  words of the message it answers in a thread, when that is known. */
export function describe(r, { quote = "" } = {}) {
  const parts = [];
  if (quote) parts.push(`[replying to: "${String(quote).slice(0, 160)}"]`);
  if (r.effect) parts.push(`[sent with ${r.effect}]`);
  if (r.subject) parts.push(r.subject);
  if (r.text) parts.push(r.text);
  for (const m of r.media) {
    if (m.kind === "photo" || m.kind === "voice") continue;       // looked at, or heard, by the bridge
    parts.push(m.kind === "file" && m.name ? `[sent a file: ${m.name}]` : `[sent ${MEDIA_WORDS[m.kind] || "a file"}]`);
  }
  if (r.app) parts.push(`[sent ${r.app}]`);
  return parts.join(" ").trim();
}

/** A message's words for the chat log and the Chats tab (no brackets for the AI), and what kind it is. */
export function logBody(r) {
  const first = r.media[0];
  let kind = first ? first.kind : r.app ? "app" : "";
  let text = [r.subject, r.text].filter(Boolean).join("\n");
  if (r.unsent) { kind = "unsent"; text = ""; }
  if (!text && first) text = `[${MEDIA_WORDS[first.kind] || "file"}]`;
  if (!text && r.app) text = `[${r.app}]`;
  return { text, kind };
}
