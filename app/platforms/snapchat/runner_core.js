/**
 * What a browser runner shares with the Python bridge, whatever the platform:
 * the files and the wake socket they talk through, the state the panel shows,
 * the send governor (gaps, hourly cap, quiet hours), and the keys messages are
 * kept under. The same protocol as snapchat_runner.js, which keeps its own
 * copy; tiktok_runner.js is built on this one.
 *
 *   ipc/<p>_incoming.json   what the runner read, for the bridge to answer
 *   ipc/<p>_responses.json  the bridge's answers, for the runner to send
 *   ipc/<p>_outgoing.json   messages the bridge sends on its own (a Reply, a nudge, a picture)
 *   ipc/<p>_processed.json  ids the bridge has handled
 *   ipc/<p>_state.json      what the runner is doing, for the panel
 *   ipc/<p>_port            the bridge's wake socket, which carries pokes, panel requests and transcripts
 *
 * <p> is "tiktok" (or "snap"); account 2 on adds "_2" and so on.
 */
import fs from "fs";
import net from "net";
import path from "path";
import { createHash } from "crypto";

/** What goes out through an account's proxy with no browser to do it (baileys): an agent for it, or undefined for none.
 *  proxy-agent comes with Puppeteer, and speaks http and socks both. */
export async function agentFor(proxy) {
  const url = String(proxy || "").trim();
  if (!url) return undefined;
  const { ProxyAgent } = await import("proxy-agent");
  const whole = url.includes("://") ? url : `http://${url}`;
  return new ProxyAgent({ getProxyForUrl: () => whole });
}

export function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function readJson(filePath, defaultValue) {
  try {
    const text = fs.readFileSync(filePath, "utf-8").trim();
    if (!text) return defaultValue;
    return JSON.parse(text);
  } catch {
    return defaultValue;
  }
}

export function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmp = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), "utf-8");
  fs.renameSync(tmp, filePath);
}

export function isoDay(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const MONTHS_FR = ["janv", "fevr", "mars", "avr", "mai", "juin", "juil", "aout", "sept", "oct", "nov", "dec"];
const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const WEEKDAYS_FR = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"];

/**
 * The day a label above some messages names, as YYYY-MM-DD: "Today", "Yesterday", "Monday", "Sep 28",
 * "September 28, 2025", "28/09/2025", with a time in it or not. "" when it names none. `monthFirst` for en-US.
 */
export function dayOfLabel(label, now = new Date(), monthFirst = true) {
  let v = String(label || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[‘’]/g, "'");
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
  const num = v.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?$|^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  let y = 0, m = 0, d = 0;
  if (num && num[4]) {
    [y, m, d] = [+num[4], +num[5], +num[6]];
  } else if (num) {
    const [a, b] = [+num[1], +num[2]];
    [m, d] = monthFirst ? (a > 12 ? [b, a] : [a, b]) : (b > 12 ? [a, b] : [b, a]);
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
    if (new Date(y, m - 1, d) > now) y -= 1;
  }
  const at = new Date(y, m - 1, d, 12);
  return at.getMonth() === m - 1 ? isoDay(at) : "";
}

/**
 * The moment a time label over some messages names, in ms: "21:43" alone is today at that time, "September 4, 2026
 * 00:15" (or "Yesterday 9:41 PM") that day at that time. 0 when it names no time.
 */
export function atOfLabel(label, now = new Date(), monthFirst = true) {
  const v = String(label || "").trim();
  const t = v.match(/(\d{1,2})[:h](\d{2})(?:\s*([ap])\.?\s?m\.?)?/i);
  if (!t) return 0;
  let h = +t[1];
  const min = +t[2];
  if (t[3]) {
    const pm = /p/i.test(t[3]);
    if (pm && h < 12) h += 12;
    if (!pm && h === 12) h = 0;
  }
  if (h > 23 || min > 59) return 0;
  const rest = v.replace(t[0], "").replace(/[,.\s]+/g, " ").trim();
  const day = rest ? dayOfLabel(v, now, monthFirst) : isoDay(now);
  if (!day) return 0;
  const [y, mo, d] = day.split("-").map(Number);
  const at = new Date(y, mo - 1, d, h, min, 0, 0).getTime();
  // A time alone that is still to come today was yesterday's (read just after midnight).
  return !rest && at > now.getTime() + 60000 ? at - 86400000 : at;
}

/**
 * The messages of a conversation as read, each given a key that is the same every time the same conversation is
 * read: the chat, the day, who sent it, its words, and which of the same it is that day. Reading it again finds the
 * same keys, so the panel's log never doubles a message.
 */
export function keyed(chatId, raw, { monthFirst = true, prefix = "t" } = {}) {
  const seen = new Map();
  let day = isoDay(new Date());
  const firstLabel = raw.find((m) => dayOfLabel(m.day, new Date(), monthFirst));
  if (firstLabel) day = dayOfLabel(firstLabel.day, new Date(), monthFirst);
  return raw.map((m) => {
    const named = m.at ? isoDay(new Date(m.at)) : dayOfLabel(m.day, new Date(), monthFirst);
    if (named) day = named;
    const body = m.text || `[${m.kind || "message"}]`;
    const base = `${chatId}|${day}|${m.mine ? 1 : 0}|${body}`;
    const n = (seen.get(base) || 0) + 1;
    seen.set(base, n);
    return {
      key: prefix + createHash("sha1").update(`${base}|${n}`).digest("hex").slice(0, 24),
      mine: !!m.mine, text: m.text || "", kind: m.kind || "", day,
      at: m.at || 0, links: Array.isArray(m.links) ? m.links : [],
      reactions: Array.isArray(m.reactions) ? m.reactions : [],
      ...(m.media ? { media: m.media } : {}),
      // Where it sits on the page (to react to it), who sent it (in a group), what it shares or answers.
      ...(Number.isInteger(m.idx) ? { idx: m.idx } : {}),
      ...(m.author ? { author: m.author } : {}),
      ...(m.title ? { title: m.title } : {}),
      ...(m.quote ? { quote: m.quote } : {}),
    };
  });
}

/**
 * One runner's link to its bridge. `prefix` names its files ("tiktok"), `env` its settings ("TIKTOK"), `tag` its
 * log lines ("[TikTok]").
 *
 * `defaults` is what this platform runs at when nothing says otherwise: a settings file written before the
 * platform existed has no section for it, so without these it would fall back to another platform's pace.
 */
export function createCore({ prefix, env, account, dataDir, tag, defaults = {} }) {
  const SFX = account === 1 ? "" : `_${account}`;
  const IPC_DIR = path.join(dataDir, "ipc");
  fs.mkdirSync(IPC_DIR, { recursive: true });
  const files = {
    incoming: path.join(IPC_DIR, `${prefix}_incoming${SFX}.json`),
    responses: path.join(IPC_DIR, `${prefix}_responses${SFX}.json`),
    outgoing: path.join(IPC_DIR, `${prefix}_outgoing${SFX}.json`),
    processed: path.join(IPC_DIR, `${prefix}_processed${SFX}.json`),
    port: path.join(IPC_DIR, `${prefix}_port${SFX}`),
    state: path.join(IPC_DIR, `${prefix}_state${SFX}.json`),
  };
  const own = (name, dflt) => (defaults[name] !== undefined ? defaults[name] : dflt);
  const num = (name, dflt) => {
    const v = Number(process.env[`${env}_${name}`]);
    return Number.isFinite(v) && process.env[`${env}_${name}`] !== "" && process.env[`${env}_${name}`] != null
      ? v : own(name, dflt);
  };
  const flag = (name, dflt) => {
    const v = String(process.env[`${env}_${name}`] ?? "").toLowerCase();
    return v ? ["1", "true", "yes", "on"].includes(v) : own(name, dflt);
  };
  const text = (name, dflt = "") => String(process.env[`${env}_${name}`] ?? own(name, dflt)).trim();

  // ── What the runner is doing, for the panel (see snapchat_runner.js setState) ──
  let lastState = "", lastDetail = "", lastWrite = 0;
  /** Said along with every state from now on, until it is taken back: what the site watch has found. */
  let standing = {};
  function keepSaying(what) {
    standing = what;
    if (lastState) setState(lastState, lastDetail, { ...what });
  }
  function setState(state, detail = "", extra = {}) {
    // Skipped only when nothing changed. "No new words" used to be enough to skip, so a state set again without
    // them kept the old ones: a page warning from a moment at startup stayed on the card all day.
    if (state === lastState && detail === lastDetail && !Object.keys(extra).length) return;
    lastState = state;
    lastDetail = detail;
    lastWrite = Date.now();
    try {
      writeJson(files.state, { state, detail, at: Date.now() / 1000, account, ...standing, ...extra });
    } catch { /* the log still carries it */ }
  }
  function heartbeatState() {
    if (!lastState || Date.now() - lastWrite < 60 * 1000) return;
    const s = lastState;
    lastState = "";
    setState(s, lastDetail);
  }

  // ── The wake socket: pokes both ways, panel requests in, answers and transcripts out ──
  let sock = null;
  let buf = "";
  const panelQueue = [];
  let onPoke = null;
  function connectWake(retry = 0) {
    const backoff = () => setTimeout(() => connectWake(Math.min(retry + 1, 6)), Math.min(1000 * 2 ** retry, 15000));
    let port = NaN;
    try { port = parseInt(fs.readFileSync(files.port, "utf-8").trim(), 10); } catch { /* not published yet */ }
    if (!Number.isInteger(port) || port <= 0) return backoff();
    const s = net.createConnection({ host: "127.0.0.1", port }, () => { sock = s; buf = ""; });
    s.on("data", (chunk) => {
      buf += chunk.toString("utf-8");
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        let msg;
        try { msg = JSON.parse(line); } catch { continue; }
        if (msg && msg.kind === "response" && onPoke) onPoke();
        if (msg && msg.kind === "panel" && msg.id) {
          panelQueue.push(msg);
          if (onPoke) onPoke();
        }
      }
    });
    s.on("error", () => { try { s.destroy(); } catch { /* gone */ } });
    s.on("close", () => { if (sock === s) sock = null; backoff(); });
  }
  function tellPython(data) {
    if (!sock) return false;
    try { sock.write(JSON.stringify(data) + "\n"); return true; } catch { return false; }
  }
  const pokePython = (kind) => tellPython({ kind });
  const connected = () => !!sock;

  /** Wait, but wake early when the bridge says a reply is ready or the panel asks for something. */
  function sleepOrPoke(ms) {
    return new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        if (onPoke === finish) onPoke = null;
        resolve();
      };
      const timer = setTimeout(finish, ms);
      onPoke = finish;
    });
  }
  /** Something on the page changed (a new message in the list): stop waiting now. */
  const wakeNow = () => { if (onPoke) onPoke(); };

  // ── The send governor (see snapchat_runner.js): gaps, an hourly cap, quiet hours ──
  const minGap = num("MIN_SEND_GAP_MS", 15000);
  const maxGap = num("MAX_SEND_GAP_MS", 45000);
  const perHour = num("MAX_SENDS_PER_HOUR", 20);
  const quiet = text("QUIET_HOURS");
  let lastSendAt = 0, nextGap = 0, sendTimes = [], quietSaid = false;
  function inQuietHours() {
    const m = quiet.match(/^(\d{1,2})\s*-\s*(\d{1,2})$/);
    if (!m) return false;
    const start = parseInt(m[1]) % 24, end = parseInt(m[2]) % 24;
    const h = new Date().getHours();
    const inside = start <= end ? h >= start && h < end : h >= start || h < end;
    if (inside && !quietSaid) console.log(`${tag} Quiet hours (${start}:00 to ${end}:00), not sending until they pass.`);
    quietSaid = inside;
    return inside;
  }
  function sendAllowed() {
    if (inQuietHours()) return false;
    const now = Date.now();
    sendTimes = sendTimes.filter((t) => now - t < 3600000);
    if (sendTimes.length >= perHour) return false;
    return now - lastSendAt >= nextGap;
  }
  function recordSend() {
    lastSendAt = Date.now();
    sendTimes.push(lastSendAt);
    nextGap = minGap + Math.random() * Math.max(0, maxGap - minGap);
    if (Math.random() < 0.08) nextGap += (120 + Math.random() * 180) * 1000;      // drifting off for a few minutes
  }
  const pollMs = num("POLL_INTERVAL_MS", 10000);
  const jitteredPoll = () => Math.round(pollMs * (0.7 + Math.random() * 0.6));
  /** A person typing it: 3.5 to 7 characters a second, never under a beat. */
  const typingTime = (s) => Math.max(1200, (String(s || "").length / (3.5 + Math.random() * 3.5)) * 1000);

  // ── Messages already handed over, so the same one is never answered twice in a run (bounded both ways) ──
  const seen = new Map();
  function isNew(chatId, key) {
    if (!seen.has(chatId)) {
      if (seen.size >= 200) seen.delete(seen.keys().next().value);
      seen.set(chatId, new Set());
    }
    const set = seen.get(chatId);
    if (set.has(key)) return false;
    set.add(key);
    if (set.size > 300) set.delete(set.values().next().value);
    return true;
  }

  function ensureFiles() {
    if (!fs.existsSync(files.incoming)) writeJson(files.incoming, []);
    if (!fs.existsSync(files.responses)) writeJson(files.responses, {});
    if (!fs.existsSync(files.outgoing)) writeJson(files.outgoing, []);
    if (!fs.existsSync(files.processed)) writeJson(files.processed, []);
  }

  /** A message for the bridge to answer. */
  function handOver(entry) {
    const incoming = readJson(files.incoming, []);
    incoming.push({ ts: Date.now() / 1000, ...entry });
    writeJson(files.incoming, Array.isArray(incoming) ? incoming : [entry]);
    pokePython("incoming");
  }

  // ── The bridge's answers, taken one at a time ──
  // Each read and written back at once, with nothing awaited between: a copy read before a send and written after it
  // dropped whatever the bridge (or another of the runner's loops) added while it was sending.
  /** The answers waiting: {id: answer}. Read only; take() each one before acting on it. */
  const responses = () => {
    const r = readJson(files.responses, {});
    return r && typeof r === "object" && !Array.isArray(r) ? r : {};
  };
  /** One answer off the file, null when it is gone (taken by another loop). */
  function take(id) {
    const now = responses();
    if (!(id in now)) return null;
    const val = now[id];
    delete now[id];
    writeJson(files.responses, now);
    return val;
  }
  /** An answer put back, to be tried again. */
  function putBack(id, val) {
    const now = responses();
    now[id] = val;
    writeJson(files.responses, now);
  }

  return {
    files, num, flag, text, setState, keepSaying, heartbeatState, connectWake, tellPython, pokePython, connected, panelQueue,
    sleepOrPoke, wakeNow, sendAllowed, recordSend, inQuietHours, jitteredPoll, typingTime, isNew, ensureFiles, handOver,
    responses, take, putBack,
    get state() { return lastState; }, perHour, minGap, maxGap, quiet,
  };
}

/**
 * What may still be done today, kept in a file so a restart does not hand out a fresh day: likes, comments, LIVE
 * visits, For You sessions, posts. `limits` is {name: per day}; the day turns at local midnight.
 */
export function createBudget(file, limits = {}) {
  const load = () => {
    const today = isoDay(new Date());
    const b = readJson(file, null);
    return b && b.day === today && b.counts && typeof b.counts === "object" ? b : { day: today, counts: {} };
  };
  const used = (name) => Number(load().counts[name]) || 0;
  const left = (name) => Math.max(0, (Number(limits[name]) || 0) - used(name));
  const allowed = (name) => left(name) > 0;
  function spend(name, n = 1) {
    const b = load();
    b.counts[name] = (Number(b.counts[name]) || 0) + n;
    try { writeJson(file, b); } catch { /* counted again next time */ }
    return left(name);
  }
  return { used, left, allowed, spend, limits };
}
