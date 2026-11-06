/**
 * The app's own part of a Minecraft account's bot, inside mindcraft's agent process. Loaded before mindcraft is
 * (NODE_OPTIONS --import, set by minecraft_runner.mjs), it wraps mineflayer's createBot, so the bot mindcraft makes
 * comes with what the app adds to it, and nothing in mindcraft is changed:
 *
 *   - a live view of the world around it, for the panel to watch: prismarine-viewer's own page and renderer (in
 *     mindcraft's node_modules), served from here on this computer only, on the port the runner picked and under
 *     the path the panel serves it at (minecraft_routes.py), as the bot's own eyes or from above;
 *   - its sign-in on servers that ask for one in the chat (AuthMe and the like: /register, /login), with the
 *     password the app keeps for it on that server, typed straight to the server: never through mindcraft, its
 *     history or a model, and never in answer to something a player said;
 *   - what mindcraft hears as players talking, from players only: a server's own lines often read like chat ("[Iron]
 *     hrfd joined the lobby!", "JartexNetwork » Unknown command."), and mindcraft answered them out loud;
 *   - a server's resource pack accepted, as a player's client accepts it (a server kicks a client that refuses);
 *   - what happens to it, said to the runner as lines it reads (MARK + JSON).
 *
 * Loaded into the MindServer's process as well, which never makes a bot, so it does nothing there.
 */
import { createRequire } from "module";
import { throughProxy } from "./proxy_connect.mjs";
import path from "path";
import { pathToFileURL } from "url";

const MC_DIR = process.env.LSB_MC_DIR || process.cwd();
const require = createRequire(path.join(MC_DIR, "package.json"));
export const MARK = "\u001eLSB ";

function tell(event, data = {}) {
  try { process.stdout.write(`${MARK}${JSON.stringify({ event, ...data })}\n`); } catch { /* nobody listening */ }
}

/** A chat component (a kick reason, a server's message, a title, a scoreboard's name) as its plain words: JSON text,
 *  a component, prismarine-chat's own message, or the tags chat comes as from 1.20.3 on. */
export function plain(value) {
  return wordsOf(value).trim();
}

// The words of each part as they are, spaces and all: a line is often made of parts that end in one ("You are ").
function wordsOf(value) {
  if (value == null) return "";
  if (typeof value === "string") {
    const s = value.trim();
    if (s.startsWith("{") || s.startsWith("[") || s.startsWith("\"")) {
      try { return wordsOf(JSON.parse(s)); } catch { return value; }
    }
    return value;
  }
  if (typeof value !== "object") return String(value);
  if (Array.isArray(value)) return value.map(wordsOf).join("");
  // prismarine-chat's ChatMessage knows its own words.
  if (value.json !== undefined && typeof value.toString === "function" && value.toString !== Object.prototype.toString) {
    return String(value.toString());
  }
  // A tag ({type, value}): what it holds.
  if (typeof value.type === "string" && "value" in value && !("text" in value) && !("translate" in value)
      && !("extra" in value)) {
    return wordsOf(value.value);
  }
  let out = value.text != null ? wordsOf(value.text) : "";
  if (!out && value.translate != null) {
    const key = wordsOf(value.translate);
    const args = Array.isArray(value.with) ? value.with.map(wordsOf) : value.with != null ? [wordsOf(value.with)] : [];
    out = args.length ? `${key} ${args.join(" ")}` : key;
  }
  if (value.extra != null) out += wordsOf(value.extra);
  // A component as a tag keeps its own words under an empty name.
  if (!out && value[""] != null) out = wordsOf(value[""]);
  return out;
}

/** A server's own icons: characters from its resource pack (ranks, coins), which are only pictures with that pack
 *  and otherwise boxes ("<5x����09sakuraa>"), and the boxes themselves. */
const GLYPHS = /[\u{E000}-\u{F8FF}\u{F0000}-\u{FFFFD}\u{100000}-\u{10FFFD}\u{FFFD}]/gu;

/** Words without the colour codes some servers still put straight into text ("§aVIP §fSteve"). The game hides a "§"
 *  and whatever one character follows it, a code it knows or not ("§/" ends each line of Jartex's board). */
export const bare = (s) => String(s ?? "").replace(/§[\s\S]?/g, "").replace(GLYPHS, "").replace(/\s+/g, " ").trim();

// ── Who is talking ────────────────────────────────────────────────────────────
// mineflayer's "chat" and "whisper" come from a pattern run over every line, which takes the first word before a
// ":" or "»" for the one talking: a network's name, a rank in brackets, a sign-in plugin talking as "LOGIN". Players
// are the ones on the server's own list of them.
const hasPlayer = (bot, name) => !!name && Object.prototype.hasOwnProperty.call(bot.players || {}, name);
const isOn = (bot, name) => !!name && (name === bot.username || hasPlayer(bot, name));
// A name then what chat puts after one: "Steve » ", "<Steve> ", "Steve: ".
const SAID_RE = /(\w{1,16})>?\s?[>:»|~\])-]+\s/g;

/** [name, words] of whoever on the server said a line, as networks print chat: "[Iron] Steve » hi", "VIP Steve:
 *  hi", "<Steve> hi". The first name near the start that is a player's (itself too, unless `self` is false); null
 *  for none. */
export function spokenIn(bot, line, self = true) {
  const text = String(line || "");
  const re = new RegExp(SAID_RE.source, "g");
  for (let m = re.exec(text); m && m.index < 64; m = re.exec(text)) {
    if (m[1] === bot.username ? self : hasPlayer(bot, m[1])) return [m[1], text.slice(m.index + m[0].length)];
  }
  return null;
}

/** Who said a line mineflayer read as a player's ("chat", "whisper": its username and message, and the whole line
 *  when there is one), and what: [name, words], or null for the server's own. "[Iron] Steve » hi" comes as from
 *  "Iron", saying "Steve » hi": it is Steve's "hi". */
export function speaker(bot, username, message, line = "") {
  if (isOn(bot, username)) return [username, message];
  return spokenIn(bot, line) || spokenIn(bot, message);
}

// The whole line, which mineflayer passes its "chat" and "whisper" listeners after the parts (translate, message).
const lineOf = (more) => (more[1] && typeof more[1] === "object" ? String(more[1]) : "");

/** mindcraft's listeners for players talking ("chat", "whisper", all added after this) get players' lines only,
 *  under their own names: the server's never reach it, to be answered out loud or kept in its memory. */
export function playersOnly(bot) {
  const on = bot.on;
  const add = function (event, listener, ...rest) {
    if ((event === "chat" || event === "whisper") && typeof listener === "function" && !listener.__lsb) {
      const heard = function (username, message, ...more) {
        const who = speaker(bot, username, message, lineOf(more));
        if (who && who[0] !== bot.username) return listener.call(this, who[0], who[1], ...more);
        return undefined;
      };
      heard.listener = listener;   // so removeListener(event, listener) still finds it
      return on.call(this, event, heard, ...rest);
    }
    return on.call(this, event, listener, ...rest);
  };
  bot.on = add;
  bot.addListener = add;
}

// Commands with a message in them, the only ones the game signs.
const SIGNED_VERBS = /^(msg|tell|w|whisper|me|say|teammsg|tm|r|reply|m|t)$/i;

/** A command sent the way the game's own client sends it: plain ("chat_command", the command alone) when there is
 *  nothing in it to sign, which is every command but a message to someone. mineflayer signs them all, and a
 *  network's proxy may drop a signed command it cannot check: DonutSMP answered nothing to /settings or /bal. True
 *  when it was sent that way; false where the version has no such packet, and the caller sends it as before. */
export function sendPlainCommand(bot, line) {
  const command = String(line ?? "").trim().replace(/^\//, "").trim();
  if (!command || SIGNED_VERBS.test(command.split(/\s+/)[0])) return false;
  let plainPacket = false;
  try { plainPacket = typeof bot.supportFeature === "function" && bot.supportFeature("seperateSignedChatCommandPacket"); } catch { /* old */ }
  if (!plainPacket || !bot._client) return false;
  bot._client.write("chat_command", { command: command.slice(0, 255) });
  return true;
}

/** mindcraft sets its skin at every login, with "/skin clear" when its profile has none: a command of a server mod
 *  (Fabric Tailor) hardly any server has, so the rest answered "Unknown command." each time it joined. And every
 *  command it, the app or its owner sends goes the game's way (sendPlainCommand). */
export function noSkinClear(bot) {
  const chat = bot.chat;
  if (typeof chat !== "function" || chat.__lsb) return;
  const wrapped = function (message, ...rest) {
    const text = String(message ?? "").trim();
    if (text === "/skin clear") return undefined;
    if (text.startsWith("/") && !text.includes("\n")) {
      try { if (sendPlainCommand(bot, text)) return undefined; } catch { /* as mineflayer sends it, then */ }
    }
    return chat.call(this, message, ...rest);
  };
  wrapped.__lsb = true;
  bot.chat = wrapped;
}

// ── Signing in on servers that ask in the chat ────────────────────────────────
// What such plugins say (AuthMe, nLogin, OpeNLogin, in English and French, as they ship): asked to register or to
// log in, told it worked, told the password is wrong.
const REGISTER_RE = /\/(?:register|reg)\b(.*)/i;
const LOGIN_RE = /\/(?:login|log|l)\b/i;
// AuthMe's own: "You already have registered this username!"
const ALREADY_RE = /already (?:have |has )?(?:been )?registered|déjà (?:été )?(?:enregistré|inscrit)|ya est[aá]s registrado/i;
const SIGNED_IN_RE = new RegExp([
  "successfully registered", "registered successfully", "registration successful", "successful login",
  "successfully logged in", "logged in successfully", "login successful", "you are now logged in",
  "you have been logged in", "inscription réussie", "enregistré avec succès", "connexion réussie",
  "connecté avec succès", "vous êtes (?:maintenant )?connecté", "authentification réussie",
  // A sign-in the server remembers (the same address, a little while after): no prompt at all, only this.
  "logged.in due to session", "session (?:login|reconnection|restored|resumed)", "automatically logged in",
  "auto(?:matically)?.logged.in", "connecté automatiquement", "reconnecté automatiquement",
].join("|"), "i");
// What a line about signing in has in it: shown in the log while it signs in.
const SIGN_IN_WORDS_RE = /\b(?:register\w*|login|log ?in|logged|password|session|auth\w*|captcha|verif\w*|inscri\w*|connect\w*)\b/i;
const WRONG_RE = /wrong password|incorrect password|invalid password|password (?:is )?(?:wrong|incorrect)|mot de passe (?:incorrect|invalide|erroné)|contraseña incorrecta/i;

/**
 * Answers a server's own "/register <password> <password>" or "/login <password>" with the account's password for
 * it. Only lines the server sent (system messages): a player saying "/login" in the chat gets nothing out of it.
 * A few tries at most, and none after the server says the password is wrong: the panel is told instead.
 */
export function signInOn(bot, password, say = tell) {
  if (!password) return null;
  const state = { tries: 0, lastAt: 0, done: false, stopped: false, shown: 0, since: Date.now(), last: "", lastShownAt: 0 };
  // What the server says about signing in, for the log, while it is about it: what it was asked, or why nothing was
  // sent (a sign-in remembered from before, words it does not know). The password never, should a server repeat it.
  // Once a line: the same one comes whole ("LOGIN » Please register ...") and as mineflayer's "chat" (its words).
  const show = (t) => {
    if (state.shown >= 8 || Date.now() - state.since > 120000 || !SIGN_IN_WORDS_RE.test(t)) return;
    if (Date.now() - state.lastShownAt < 2000 && (state.last.endsWith(t) || t.endsWith(state.last))) return;
    state.last = t;
    state.lastShownAt = Date.now();
    state.shown += 1;
    say("auth", { step: "server", text: t.split(password).join("•••").slice(0, 200) });
  };
  const send = (line, step) => {
    if (state.done || state.stopped || state.tries >= 4 || Date.now() - state.lastAt < 4000) return false;
    state.tries += 1;
    state.lastAt = Date.now();
    try { bot.chat(line); } catch { return false; }
    say("auth", { step });
    return true;
  };
  const onLine = (text, position) => {
    if (position === "chat" || state.done || state.stopped) return;
    const t = String(text || "");
    show(t);
    if (SIGNED_IN_RE.test(t)) {
      state.done = true;
      say("auth", { step: "signed-in" });
      return;
    }
    if (WRONG_RE.test(t)) {
      state.stopped = true;
      say("auth", { step: "refused", text: t.slice(0, 200) });
      return;
    }
    const reg = t.match(REGISTER_RE);
    if (reg && !ALREADY_RE.test(t)) {
      const args = reg[1].match(/[<[({][^>\])}]+[>\])}]/g) || [];
      if (args.some((a) => /mail|courriel|correo/i.test(a))) {
        state.stopped = true;
        say("auth", { step: "needs-email", text: t.slice(0, 200) });
        return;
      }
      send(args.length === 1 ? `/register ${password}` : `/register ${password} ${password}`, "register");
      return;
    }
    if (LOGIN_RE.test(t) || ALREADY_RE.test(t)) send(`/login ${password}`, "login");
  };
  // Another player's line the server printed itself, as networks print chat: "[Iron] Steve » /login <password>".
  // Its own name is no reason to skip one ("[AuthMe] Alicia: please /login <password>"), and its own words coming
  // back ask for nothing: it cannot chat before it signs in, and once it has, nothing more is sent.
  bot.on("messagestr", (text, position) => {
    if (!spokenIn(bot, text, false)) onLine(text, position);
  });
  // Some networks' sign-in plugin talks as a player that is not one: jartex.fun's says "Please register with
  // /register <password> <password>" as a chat line from "LOGIN", which mindcraft took for someone talking to it,
  // and the line above leaves alone, being chat. A sender who is not a player is the server: what it asks for is
  // answered like a system line. (What is sent is a /login command to the server, never the password into the chat.)
  const fromServer = (username, message, ...more) => {
    if (!username || username === bot.username || hasPlayer(bot, username)) return;
    if (!spokenIn(bot, lineOf(more), false) && !spokenIn(bot, message, false)) onLine(message, "server");
  };
  fromServer.__lsb = true;   // the server's lines are what this one is for (playersOnly leaves it be)
  bot.on("chat", fromServer);
  return { state, onLine };
}

// ── What the panel draws over the picture ────────────────────────────────────
/** The last lines it heard, newest last. The view shows them as Minecraft does, which it could not before. */
const heard = [];
/** The rest of a player's screen, as the server sends it: a title and its subtitle and how long they stay, the line
 *  over the hotbar, when each effect on it was given (the server says how long one lasts as of then), and the
 *  world's age against the clock, which is how fast the server is really running. */
const screen = { title: "", subtitle: "", titleAt: 0, titleFor: 3500, overHotbar: "", overHotbarAt: 0,
                 effectsAt: new Map(), ages: [], scores: new Map(), boardFormat: new Map() };

function remember(text, from = "") {
  const line = String(text || "").replace(GLYPHS, "").trim();
  if (!line) return;
  heard.push({ text: line.slice(0, 300), from: String(from || "").slice(0, 40), at: Date.now() });
  if (heard.length > 120) heard.splice(0, heard.length - 120);
}

/** A line the server shows over the hotbar rather than in the chat ("game_info"). Many send one every second,
 *  which in the chat buried everything else. */
function heardOverHotbar(text) {
  screen.overHotbar = bare(text).slice(0, 200);
  screen.overHotbarAt = Date.now();
}

/** Everything a server puts on a player's screen besides the chat, followed as it comes. */
export function followScreen(bot) {
  bot.on("title", (text, kind) => {
    const words = bare(plain(text)).slice(0, 160);
    if (kind === "subtitle") {
      screen.subtitle = words;
    } else {
      screen.title = words;
      screen.titleAt = Date.now();
    }
  });
  bot.on("title_times", (fadeIn, stay, fadeOut) => {
    const ticks = Number(fadeIn) + Number(stay) + Number(fadeOut);
    if (Number.isFinite(ticks)) screen.titleFor = Math.max(800, Math.min(20000, ticks * 50));
  });
  bot.on("title_clear", () => {
    screen.title = screen.subtitle = "";
    screen.titleAt = 0;
  });
  bot.on("entityEffect", (entity, effect) => {
    if (entity === bot.entity && effect) screen.effectsAt.set(effect.id, Date.now());
  });
  bot.on("entityEffectEnd", (entity, effect) => {
    if (entity === bot.entity && effect) screen.effectsAt.delete(effect.id);
  });
  bot.on("time", () => {
    const age = Number(bot.time && bot.time.age);
    if (!Number.isFinite(age)) return;
    screen.ages.push([Date.now(), age]);
    if (screen.ages.length > 24) screen.ages.shift();
  });
  // The scores on each board, as the server sends them. mineflayer keeps its own, but from 1.20.3 on it waits for an
  // "action" the score packet no longer has, so its boards stay empty: a server's sidebar showed its title alone.
  const client = bot._client;
  if (!client || typeof client.on !== "function") return;
  client.on("scoreboard_objective", (p) => {
    const name = String((p && p.name) ?? "");
    if (!name) return;
    if (p.action === 1) {
      screen.scores.delete(name);
      screen.boardFormat.delete(name);
    } else if (p.number_format !== undefined && p.number_format !== null) {
      screen.boardFormat.set(name, Number(p.number_format));
    }
  });
  client.on("scoreboard_score", (p) => {
    const board = String((p && (p.scoreName ?? p.objective_name)) ?? "");
    const item = p && (p.itemName ?? p.entity_name);
    if (!board || item == null) return;
    if (p.action === 1) {
      const m = screen.scores.get(board);
      if (m) m.delete(String(item));
      return;
    }
    if (!screen.scores.has(board)) screen.scores.set(board, new Map());
    let shown = "", fixed = "";
    try { shown = p.display_name != null ? bare(plain(p.display_name)) : ""; } catch { /* its own name, then */ }
    try { fixed = Number(p.number_format) === 2 && p.styling != null ? bare(plain(p.styling)) : ""; } catch { /* the number */ }
    screen.scores.get(board).set(String(item), { value: Number(p.value ?? 0), shown, fixed,
                                                  blank: Number(p.number_format) === 0 });
  });
  client.on("reset_score", (p) => {
    const item = String((p && (p.entity_name ?? p.itemName)) ?? "");
    const board = p && p.objective_name;
    if (board) {
      const m = screen.scores.get(String(board));
      if (m) m.delete(item);
    } else {
      for (const m of screen.scores.values()) m.delete(item);
    }
  });
}

/** Ticks a second over the last half minute or so: 20 is a server keeping up. */
function ticksPerSecond() {
  const a = screen.ages;
  if (a.length < 3) return null;
  const [t0, g0] = a[0], [t1, g1] = a[a.length - 1];
  const secs = (t1 - t0) / 1000;
  if (secs < 2) return null;
  return Math.max(0, Math.min(20, Math.round(((g1 - g0) / secs) * 10) / 10));
}

// ── Pictures of what it holds ────────────────────────────────────────────────
/** Minecraft's own pictures, which prismarine-viewer ships for each version it draws (public/textures/<version>):
 *  each item's by its name ("items/diamond_pickaxe.png", "blocks/oak_planks.png"), each effect's, and the HUD's
 *  hearts, food and armour. They are served at the view's own address with the rest of its files, so the panel
 *  shows the real thing. */
const pictures = { version: "", items: new Map(), effects: new Set(), sprites: false };

export function loadPictures(version, root = "") {
  if (!version || pictures.version === version) return pictures;
  Object.assign(pictures, { version, items: new Map(), effects: new Set(), sprites: false });
  try {
    const fs = require("fs");
    const base = root || path.join(path.dirname(require.resolve("prismarine-viewer/public/index.js")), "textures", version);
    const files = new Set();
    for (const dir of ["items", "blocks", "mob_effect"]) {
      try { for (const f of fs.readdirSync(path.join(base, dir))) files.add(`${dir}/${f}`); } catch { /* none */ }
    }
    const list = JSON.parse(fs.readFileSync(path.join(base, "items_textures.json"), "utf8"));
    for (const it of Array.isArray(list) ? list : []) {
      // "minecraft:items/bread", "minecraft:block/dirt", "block/dirt", "items/bow": where it is in the folder.
      const rel = `${String(it.texture || "").replace(/^minecraft:/, "").replace(/^block\//, "blocks/")
        .replace(/^item\//, "items/")}.png`;
      if (files.has(rel)) pictures.items.set(String(it.name), rel);
    }
    for (const f of files) if (f.startsWith("mob_effect/")) pictures.effects.add(f);
    pictures.sprites = fs.existsSync(path.join(base, "gui", "sprites", "hud", "heart", "full.png"));
  } catch { /* none to show: the panel draws its own */ }
  return pictures;
}

/** One slot as the panel needs it: what it is, how many, how worn, its picture, and where it is (for a click). */
export function slotOf(item, slot = null) {
  if (!item) return null;
  const max = Number(item.maxDurability || 0);
  const used = Number(item.durabilityUsed || 0);
  let ench = false, custom = "";
  try { ench = !!(item.enchants && item.enchants.length); } catch { /* an item this version cannot read */ }
  try { custom = item.customName ? bare(plain(item.customName)) : ""; } catch { /* none */ }
  return {
    // A server's own name for it when it gave one ("Game Menu"), which is what a player would read.
    name: (custom || String(item.displayName || item.name || "")).slice(0, 48),
    id: String(item.name || ""),
    count: Number(item.count || 1),
    // 1 is untouched, 0 is about to break; absent on anything that does not wear out.
    left: max > 0 ? Math.max(0, Math.min(1, (max - used) / max)) : null,
    icon: pictures.items.get(String(item.name || "")) || "",
    ench,
    ...(slot == null ? {} : { slot }),
  };
}

// What each piece of armour is worth, as the game counts it: helmet, chestplate, leggings, boots.
const ARMOUR = { leather: [1, 3, 2, 1], golden: [2, 5, 3, 1], chainmail: [2, 5, 4, 1], iron: [2, 6, 5, 2],
                 copper: [2, 4, 3, 1], diamond: [3, 8, 6, 3], netherite: [3, 8, 6, 3], turtle: [2, 0, 0, 0] };
const PIECES = ["helmet", "chestplate", "leggings", "boots"];

/** Its armour bar: twenty is full. */
export function armourPoints(slots) {
  let n = 0;
  PIECES.forEach((piece, i) => {
    const m = String((slots && slots[5 + i] && slots[5 + i].name) || "").match(/^([a-z]+)_(helmet|chestplate|leggings|boots)$/);
    if (m && m[2] === piece && ARMOUR[m[1]]) n += ARMOUR[m[1]][i];
  });
  return Math.min(20, n);
}

/** The effects on it, each with what is left of it. */
function effectsOf(bot) {
  const out = [];
  const reg = (bot.registry && bot.registry.effects) || {};
  for (const e of Object.values((bot.entity && bot.entity.effects) || {})) {
    if (!e || e.id == null) continue;
    const info = reg[e.id] || {};
    // "MiningFatigue" is mob_effect/mining_fatigue.png.
    const file = `mob_effect/${String(info.name || "").replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase()}.png`;
    const total = Number(e.duration);
    const since = screen.effectsAt.get(e.id);
    // -1, or the longest a duration can be: it lasts as long as whatever gives it (a beacon, the server's own).
    const left = !Number.isFinite(total) || total < 0 || total >= 32767 || !since ? null
      : Math.max(0, Math.round(total / 20 - (Date.now() - since) / 1000));
    out.push({ id: Number(e.id), name: String(info.displayName || info.name || `Effect ${e.id}`),
               level: Number(e.amplifier || 0) + 1, left, good: info.type !== "bad",
               icon: pictures.effects.has(file) ? file : "" });
  }
  return out.slice(0, 12);
}

function bossBarsOf(bot) {
  let bars = [];
  try { bars = bot.bossBars || []; } catch { /* none */ }
  return bars.slice(0, 4).map((b) => ({
    title: bare(plain(b.title)).slice(0, 120),
    health: Math.max(0, Math.min(1, Number(b.health) || 0)),
    color: String(b.color || "pink"),
    notches: Number(b.dividers || 0),
  }));
}

/** The board down the right of the screen, as the server keeps it. */
function sidebarOf(bot) {
  let board = null;
  try { board = bot.scoreboard && bot.scoreboard.sidebar; } catch { /* none */ }
  if (!board) return null;
  let rows = [];
  try {
    const mine = screen.scores.get(String(board.name));
    if (mine && mine.size) {
      // Most servers write each line as a team's prefix and suffix around a blank entry ("§1"), so a line is what
      // its team makes of it; the numbers go when the server says to hide them, as the game does.
      const blankAll = screen.boardFormat.get(String(board.name)) === 0;
      rows = [...mine.entries()].sort((a, b) => b[1].value - a[1].value || a[0].localeCompare(b[0])).slice(0, 15)
        .map(([item, s]) => {
          let text = s.shown;
          if (!text) {
            const team = bot.teamMap ? bot.teamMap[item] : null;
            try { text = team && typeof team.displayName === "function" ? bare(plain(team.displayName(item))) : ""; } catch { /* its name */ }
          }
          return { text: (text || bare(item)).slice(0, 60), value: blankAll || s.blank ? null : s.value,
                   ...(s.fixed ? { fixed: s.fixed.slice(0, 20) } : {}) };
        });
    } else {
      rows = (board.items || []).slice(0, 15)
        .map((i) => ({ text: bare(plain(i.displayName ?? i.name)).slice(0, 60), value: Number(i.value) }));
    }
  } catch { /* it changed as it was read: the next look will do */ }
  return { title: bare(plain(board.title)).slice(0, 60), rows };
}

/** Everyone on the server, the nearest first, as the player list (Tab) shows them. */
function playersOf(bot, pos) {
  const out = [];
  for (const p of Object.values(bot.players || {})) {
    if (!p || !p.username) continue;
    const e = p.entity;
    out.push({
      name: String(p.username).slice(0, 32),
      shown: (bare(plain(p.displayName)) || String(p.username)).slice(0, 48),
      ping: Number(p.ping || 0),
      away: e && e.position && pos && e !== bot.entity ? Math.round(e.position.distanceTo(pos)) : null,
    });
  }
  out.sort((a, b) => (a.away ?? 1e9) - (b.away ?? 1e9) || a.name.localeCompare(b.name));
  return out.slice(0, 150);
}

/** A chest, a furnace, anything it has open: its own slots, each with where it is in that window. */
function windowOf(bot) {
  const w = bot.currentWindow;
  if (!w) return null;
  const n = Math.max(0, Math.min(90, Number(w.inventoryStart || 0)));
  const slots = [];
  for (let i = 0; i < n; i++) {
    const s = slotOf(w.slots[i], i);
    // What a menu's button says, for the panel's tooltip.
    if (s) s.lore = loreOf(w.slots[i]);
    slots.push(s);
  }
  return { title: bare(plain(w.title)).slice(0, 60), kind: String(w.type || ""), slots,
           // What the mouse is holding (a left click in a real chest picks a stack up).
           cursor: slotOf(w.selectedItem) };
}

// ── Its debug screen (F3) ────────────────────────────────────────────────────
const FACING = ["north", "west", "south", "east"];
const TOWARD = { north: "negative Z", west: "negative X", south: "positive Z", east: "positive X" };

/** What the game's F3 screen tells a player, as far as the bot knows it. Only worked out when it is open. */
function debugOf(bot) {
  const me = bot.entity || {};
  const p = me.position || { x: 0, y: 0, z: 0 };
  const bx = Math.floor(p.x), by = Math.floor(p.y), bz = Math.floor(p.z);
  let feet = null, looking = null, target = null;
  try { feet = bot.blockAt(p); } catch { /* not loaded yet */ }
  try { looking = bot.blockAtCursor(20); } catch { /* nothing there */ }
  try { target = bot.entityAtCursor(8); } catch { /* nobody */ }
  const deg = (r) => ((Number(r) || 0) * 180) / Math.PI;
  const yaw = deg(me.yaw);
  // mineflayer's yaw is 0 facing north and turns the other way round from the game's, which has 0 south.
  const facing = FACING[((Math.round(yaw / 90) % 4) + 4) % 4];
  const v = me.velocity || { x: 0, z: 0 };
  return {
    xyz: [p.x, p.y, p.z].map((n) => Math.round(n * 1000) / 1000),
    block: [bx, by, bz], chunk: [bx >> 4, by >> 4, bz >> 4], inChunk: [bx & 15, by & 15, bz & 15],
    facing, toward: TOWARD[facing],
    yaw: Math.round(((((180 - yaw) % 360) + 540) % 360 - 180) * 10) / 10,
    pitch: Math.round(-deg(me.pitch) * 10) / 10,
    biome: feet && feet.biome ? String(feet.biome.name || "") : "",
    light: feet ? Number(feet.light ?? 0) : null,
    sky: feet ? Number(feet.skyLight ?? 0) : null,
    looking: looking ? { name: String(looking.name), at: [looking.position.x, looking.position.y, looking.position.z] } : null,
    target: target ? { name: String(target.username || target.displayName || target.name || target.type || ""),
                       away: Math.round(target.position.distanceTo(p) * 10) / 10 } : null,
    speed: Math.round(Math.hypot(Number(v.x) || 0, Number(v.z) || 0) * 200) / 10,
    ground: !!me.onGround,
    entities: Object.keys(bot.entities || {}).length,
    players: Object.keys(bot.players || {}).length,
    ping: Number((bot.player && bot.player.ping) || 0),
    tps: ticksPerSecond(),
    version: String(bot.version || ""),
    brand: bare(bot.game && bot.game.serverBrand),
    difficulty: String((bot.game && bot.game.difficulty) || ""),
    memory: Math.round(process.memoryUsage().rss / 1048576),
    net: netOf(),
  };
}

/** Everything the panel's overlay shows, read off the bot each time it is asked: the player list and the debug
 *  screen only when they are open. */
export function hudOf(bot, ask = {}) {
  const me = bot.entity || {};
  const pos = me.position || { x: 0, y: 0, z: 0 };
  const inv = bot.inventory;
  const slots = (inv && inv.slots) || [];
  // The hotbar is the nine slots at 36..44, and quickBarSlot says which of them is in its hand.
  const hotbar = [];
  for (let i = 0; i < 9; i++) hotbar.push(slotOf(slots[36 + i], 36 + i));
  const carried = [];
  for (let i = 9; i < 36; i++) {
    const s = slotOf(slots[i], i);
    if (s) carried.push(s);
  }
  const near = [];
  for (const e of Object.values(bot.entities || {})) {
    if (!e || e === me || e.type !== "player" || !e.username) continue;
    const d = e.position && pos ? e.position.distanceTo(pos) : 0;
    near.push({ name: String(e.username).slice(0, 32), away: Math.round(d) });
  }
  near.sort((a, b) => a.away - b.away);
  const time = bot.time || {};
  const xp = bot.experience || {};
  const game = bot.game || {};
  const now = Date.now();
  const tab = bot.tablist || {};
  return {
    ok: true,
    who: String((bot.username || "")).slice(0, 32),
    health: Number(bot.health ?? 0), food: Number(bot.food ?? 0),
    saturation: Number(bot.foodSaturation ?? 0),
    air: bot.oxygenLevel == null ? null : Number(bot.oxygenLevel),
    at: { x: Math.round(pos.x), y: Math.round(pos.y), z: Math.round(pos.z) },
    where: String(game.dimension || "").replace("minecraft:", ""),
    day: Number(time.day ?? 0), ticks: Number(time.timeOfDay ?? 0),
    raining: Number(bot.isRaining ? 1 : 0),
    yaw: Number(me.yaw || 0), pitch: Number(me.pitch || 0),
    held: Number(inv && inv.quickBarSlot != null ? inv.quickBarSlot : (bot.quickBarSlot ?? 0)),
    hotbar, carried,
    armour: [5, 6, 7, 8].map((s) => slotOf(slots[s], s)),
    armourPoints: armourPoints(slots),
    offhand: slotOf(slots[45], 45),
    xp: { level: Number(xp.level || 0), progress: Math.max(0, Math.min(1, Number(xp.progress || 0))) },
    mode: String(game.gameMode || ""), hardcore: !!game.hardcore,
    effects: effectsOf(bot),
    bossBars: bossBarsOf(bot),
    sidebar: sidebarOf(bot),
    title: screen.titleAt && now - screen.titleAt < screen.titleFor
      ? { text: screen.title, sub: screen.subtitle, at: screen.titleAt, for: screen.titleFor } : null,
    overHotbar: screen.overHotbar && now - screen.overHotbarAt < 3000 ? screen.overHotbar : "",
    window: windowOf(bot),
    dead: Number(bot.health ?? 20) <= 0,
    sleeping: !!bot.isSleeping,
    driving: driving.on,
    near: near.slice(0, 20),
    chat: heard.slice(-60),
    // Where its pictures are (textures/<tex>/...), and whether that version has the HUD's own.
    tex: pictures.version, sprites: pictures.sprites,
    ...(ask.tab ? { players: playersOf(bot, pos), tabTop: bare(plain(tab.header)), tabBottom: bare(plain(tab.footer)) } : {}),
    ...(ask.debug ? { debug: debugOf(bot) } : {}),
  };
}

// ── Played by hand, from the panel ───────────────────────────────────────────
// Its owner can take the body over from the panel's view of it: walk, look, hit, mine, use, place, pick from the
// hotbar, drop, open a chest and empty it, type. While they do, mindcraft lets go of it completely, because each of
// its parts would take the body straight back: its modes (fighting back, picking things up, turning to stare at
// whoever passes), the action it was doing, its goal, its answers to the chat. The moment they let go it carries on.
// Nothing of mindcraft is changed on disk: its objects are wrapped while this process has them, as with the bot.
const KEYS = ["forward", "back", "left", "right", "jump", "sprint", "sneak"];
const driving = { on: false, since: 0, beat: 0, agent: null, goal: "", ate: false, keysOn: false,
                  mouse: { attack: false, use: false }, digging: null, usingItem: false, timer: null, cooldownUntil: 0 };
// What mindcraft's own commands are told if one already on its way runs while the owner has the body.
const BUSY = { success: false, message: "Your owner is playing as you by hand right now. Wait until they let go.",
               interrupted: false, timedout: false };
const QUIET = { success: false, message: null, interrupted: false, timedout: false };
const KEYS_IDLE_MS = 1500;    // no word from the panel for this long: every key let go, as hands coming off it
const GIVE_BACK_MS = 45000;   // and for this long: the body goes back to mindcraft, which carries on

/** mindcraft's agent for this bot. It hands the agent to the one object all of its modules share (serverProxy, in
 *  src/agent/mindserver_proxy.js), and this imports that module by the very address mindcraft's process loaded it
 *  from, so it is the same one. Only ever taken when it is this bot's own. */
async function agentOf(bot) {
  try {
    const fs = require("fs");
    const main = pathToFileURL(fs.realpathSync(process.argv[1]));
    const { serverProxy } = await import(new URL("../agent/mindserver_proxy.js", main).href);
    const agent = serverProxy && serverProxy.agent;
    return agent && agent.bot === bot ? agent : null;
  } catch {
    return null;
  }
}

/** mindcraft's hands kept off the body while its owner has it: its modes skip their turn, an action asked for is
 *  turned down with the reason, and whatever it is told waits unanswered. Wrapped once, live only while driving. */
function holdTheMind(bot, agent) {
  const modes = bot.modes;
  if (modes && typeof modes.update === "function" && !modes.__lsbHeld) {
    const update = modes.update;
    modes.update = function (...args) { return driving.on ? Promise.resolve() : update.apply(this, args); };
    modes.__lsbHeld = true;
  }
  if (!agent) return;
  const actions = agent.actions;
  if (actions && !actions.__lsbHeld) {
    const run = actions.runAction, resume = actions.resumeAction;
    actions.runAction = function (...args) { return driving.on ? Promise.resolve(BUSY) : run.apply(this, args); };
    actions.resumeAction = function (...args) { return driving.on ? Promise.resolve(QUIET) : resume.apply(this, args); };
    actions.__lsbHeld = true;
  }
  if (typeof agent.handleMessage === "function" && !agent.handleMessage.__lsbHeld) {
    const handle = agent.handleMessage;
    const held = function (...args) { return driving.on ? Promise.resolve(false) : handle.apply(this, args); };
    held.__lsbHeld = true;
    agent.handleMessage = held;
  }
}

/** What its AI is doing, asked to stop, again for a few seconds as mindcraft's own stop asks (actions.stop), but
 *  without that one's deadline: after ten seconds it ends mindcraft's whole process, and the bot left the server and
 *  joined again (a fight at night, a long walk). New actions are turned down meanwhile (holdTheMind). */
function interruptMind(agent) {
  const ask = () => { try { agent.requestInterrupt(); } catch { /* nothing to stop */ } };
  ask();
  const until = Date.now() + 8000;
  const nag = setInterval(() => {
    let busy = false;
    try { busy = !!(agent.actions && agent.actions.executing); } catch { /* gone */ }
    if (!busy || !driving.on || Date.now() > until) {
      clearInterval(nag);
      return;
    }
    ask();
  }, 300);
}

/** Every key and button let go: what happens when the hands come off the keyboard. */
function handsOff(bot) {
  driving.mouse = { attack: false, use: false };
  driving.keysOn = false;
  try { bot.clearControlStates(); } catch { /* not in a world */ }
  stopBreaking(bot);
  if (driving.usingItem) {
    try { bot.deactivateItem(); } catch { /* nothing in use */ }
    driving.usingItem = false;
  }
}

/** The body taken over from mindcraft. `given` is its agent where the caller already has it (a test). */
export async function takeOver(bot, given) {
  if (driving.on) {
    driving.beat = Date.now();
    return { ok: true, driving: true };
  }
  if (!bot.entity) return { ok: false, reason: "It is not in a world yet." };
  const agent = given !== undefined ? given : await agentOf(bot);
  driving.on = true;
  driving.since = driving.beat = Date.now();
  driving.agent = agent;
  driving.goal = "";
  holdTheMind(bot, agent);
  if (agent) {
    // Anything it is in the middle of saying stops at the next line, and its goal waits where it was.
    agent.shut_up = true;
    try {
      const sp = agent.self_prompter;
      if (sp && sp.isActive && sp.isActive()) {
        driving.goal = String(sp.prompt || "");
        // stop(false), not pause(): pause() waits on mindcraft's own stop of the action, which ends the whole
        // process when the action takes more than ten seconds to give up.
        await sp.stop(false);
      }
    } catch { /* its goal goes on where it was */ }
    interruptMind(agent);
  } else {
    // Without its agent, what it is doing is stopped through the bot all the same.
    try { bot.pathfinder && bot.pathfinder.stop(); } catch { /* not walking */ }
    try { bot.pvp && bot.pvp.stop(); } catch { /* not fighting */ }
    try { bot.collectBlock && bot.collectBlock.cancelTask(); } catch { /* not collecting */ }
  }
  try { bot.stopDigging(); } catch { /* not digging */ }
  // It eats when it is hungry by itself, which would swap what is in the owner's hand.
  driving.ate = false;
  try {
    if (bot.autoEat && typeof bot.autoEat.disableAuto === "function") {
      bot.autoEat.disableAuto();
      driving.ate = true;
    }
  } catch { /* no such plugin */ }
  handsOff(bot);
  clearInterval(driving.timer);
  driving.timer = setInterval(() => watchHands(bot), 500);
  tell("driving", { on: true, mind: agent ? "paused" : "partly" });
  return { ok: true, driving: true, mind: agent ? "paused" : "partly" };
}

export function letGo(bot, why = "") {
  if (!driving.on) return { ok: true, driving: false };
  driving.on = false;
  clearInterval(driving.timer);
  driving.timer = null;
  handsOff(bot);
  try { if (driving.ate) bot.autoEat.enableAuto(); } catch { /* gone */ }
  const agent = driving.agent;
  driving.agent = null;
  if (agent) {
    agent.shut_up = false;
    try { if (driving.goal && agent.self_prompter) agent.self_prompter.start(driving.goal); } catch { /* it waits */ }
  }
  driving.goal = "";
  // As mindcraft does when it finishes something: its modes back on, and anything it was keeping up resumed.
  try { bot.emit("idle"); } catch { /* not in a world */ }
  tell("driving", { on: false, ...(why ? { why } : {}) });
  return { ok: true, driving: false };
}

function watchHands(bot) {
  if (!driving.on) return;
  const quiet = Date.now() - driving.beat;
  if (quiet > GIVE_BACK_MS) letGo(bot, "no word from the panel");
  else if (quiet > KEYS_IDLE_MS && (driving.keysOn || driving.mouse.attack || driving.mouse.use)) handsOff(bot);
}

let VEC = null;
/** mindcraft's own Vec3 (mineflayer's), or a plain point where it is not to be had. */
function vec(x, y, z) {
  if (VEC === null) {
    try { VEC = require("vec3").Vec3; } catch { VEC = false; }
  }
  return VEC ? new VEC(x, y, z) : { x, y, z };
}
// prismarine-world's faces, by number: bottom, top, north, south, west, east.
const FACES = [[0, -1, 0], [0, 1, 0], [0, 0, -1], [0, 0, 1], [-1, 0, 0], [1, 0, 0]];
// Right-clicked, these do something of their own (open, press, ring), whatever is in the hand.
const OPENS = /chest|barrel|shulker_box|furnace|smoker|crafting_table|crafter|_door$|trapdoor|fence_gate|button|lever|_bed$|anvil|enchanting_table|brewing_stand|hopper|dispenser|dropper|loom|stonecutter|grindstone|cartography_table|smithing_table|beacon|note_block|repeater|comparator|daylight_detector|cake|bell|lectern|jukebox|composter|respawn_anchor|_sign$|decorated_pot|chiseled_bookshelf/;
// And these are used where they are, not on a block: eaten, drunk, drawn, thrown.
const USED_IN_HAND = /^(bow|crossbow|trident|shield|spyglass|goat_horn|fishing_rod|ender_pearl|ender_eye|snowball|egg|experience_bottle|.*potion|milk_bucket|honey_bottle|.*_stew|wind_charge|totem_of_undying)$/;

function canDig(bot, block) {
  try { return typeof bot.canDigBlock === "function" ? bot.canDigBlock(block) : !!block.diggable; } catch { return false; }
}

// ── Breaking blocks, the way the game's own client does ──────────────────────
// mineflayer's dig() names the top face whatever is looked at, takes the block away before the server has said so,
// and leaves the next one to start at once. A server's own checks (DonutSMP's) refused those breaks, and the block
// came back, over and over. This is the game's way: the face under the crosshair, a swing each tick, the finish a
// tick after the dig time, the block left to the server to take away, and the next one only once it has, five ticks
// on, as the game waits between blocks.
const DESTROY_DELAY_MS = 250;

/** Player digging: start (0), abort (1) or finish (2), with the face. Its number is the client's one rising count
 *  (playLikeTheGame), shared with everything else it predicts. */
function digPacket(bot, status, pos, face) {
  bot._client.write("block_dig", { status, location: pos, face, sequence: 0 });
}

/** The block being broken let go: aborted where it was not finished, as the game does when the button comes up. */
function stopBreaking(bot, abort = true) {
  const d = driving.digging;
  if (!d) return;
  driving.digging = null;
  clearTimeout(d.timer);
  clearInterval(d.swing);
  if (d.listener) bot.removeListener("blockUpdate", d.listener);
  if (abort && d.started && !d.finished) {
    try { digPacket(bot, 1, d.pos, d.face); } catch { /* gone */ }
  }
}

function startBreaking(bot, block) {
  const pos = block.position;
  const face = Number.isInteger(block.face) && block.face >= 0 && block.face <= 5 ? block.face : 1;
  let ms = 0;
  try { ms = Math.max(0, Math.ceil(Number(bot.digTime(block)) || 0)); } catch { ms = 0; }
  const d = { pos, face, name: block.name, finished: false, timer: null, swing: null, listener: null };
  driving.digging = d;
  // The server's word: gone (or anything else there now), and the next one after the game's own beat.
  d.listener = (oldBlock, newBlock) => {
    if (!newBlock || !newBlock.position || !newBlock.position.equals(pos) || newBlock.name === d.name) return;
    stopBreaking(bot, false);
    driving.cooldownUntil = Date.now() + DESTROY_DELAY_MS;
    setTimeout(() => { if (driving.on && driving.mouse.attack) keepDigging(bot); }, DESTROY_DELAY_MS + 10);
  };
  bot.on("blockUpdate", d.listener);
  let begun = false;
  const begin = () => {
    if (begun || driving.digging !== d) return;
    begun = true;
    d.started = true;
    digPacket(bot, 0, pos, face);
    try { bot.swingArm(); } catch { /* not in a world */ }
    if (ms === 0) {
      // It breaks at once (creative, or a tool that fast): the start is all the game sends.
      d.finished = true;
      d.timer = setTimeout(() => { if (driving.digging === d) stopBreaking(bot, false); }, 1000);
      return;
    }
    d.swing = setInterval(() => { try { bot.swingArm(); } catch { /* not in a world */ } }, 50);
    d.timer = setTimeout(() => {
      if (driving.digging !== d) return;
      clearInterval(d.swing);
      d.finished = true;
      // The game's own beat after a break, wherever the crosshair goes next.
      driving.cooldownUntil = Date.now() + DESTROY_DELAY_MS;
      try { digPacket(bot, 2, pos, face); } catch { /* gone */ }
      // No word from the server within a second: the next press, or the button still held, digs it again.
      d.timer = setTimeout(() => { if (driving.digging === d) stopBreaking(bot, false); }, 1000);
    }, ms + 50);
  };
  // On the next tick, after its look has gone out with it: the server knows where it is looking when it starts.
  bot.once("physicsTick", () => setImmediate(begin));
  d.timer = setTimeout(begin, 120);
}

/** Mining what is under the crosshair while the button is held: that block, and the next once the server has taken
 *  it away, as holding it does in the game. False when there is nothing there it can dig. */
function keepDigging(bot) {
  if ((driving.cooldownUntil || 0) > Date.now()) return true;
  let block = null;
  try { block = bot.blockAtCursor(4.5); } catch { /* nothing there */ }
  if (!block || block.name === "air" || !canDig(bot, block)) {
    stopBreaking(bot);
    return false;
  }
  const d = driving.digging;
  if (d && d.pos.equals(block.position)) return true;
  stopBreaking(bot);
  startBreaking(bot, block);
  return true;
}

function hit(bot) {
  let target = null;
  try { target = bot.entityAtCursor(3.5); } catch { /* nobody */ }
  if (target) {
    try { bot.attack(target); } catch { /* gone */ }
    return;
  }
  if (!keepDigging(bot)) { try { bot.swingArm(); } catch { /* not in a world */ } }
}

/** The held item used on a block at once, on the face under the crosshair: the game's own "use item on"
 *  (block_place). mineflayer's activateBlock first turns the head to the block's middle and waits for the turn: a
 *  block placed at the top of a jump went out as it fell again, and the server refused it. */
function useOnBlock(bot, block, face, at) {
  let direct = false;
  try { direct = typeof bot.supportFeature === "function" && bot.supportFeature("blockPlaceHasInsideBlock"); } catch { /* old */ }
  if (direct) {
    bot._client.write("block_place", { location: block.position, direction: face, hand: 0, cursorX: at.x, cursorY: at.y,
                                       cursorZ: at.z, insideBlock: false, sequence: 0, worldBorderHit: false });
    try { bot.swingArm(); } catch { /* not in a world */ }
    return;
  }
  const f = FACES[face] || FACES[1];
  Promise.resolve(bot.activateBlock(block, vec(f[0], f[1], f[2]), at)).catch(() => {});
}

function use(bot) {
  const held = bot.heldItem;
  const name = String((held && held.name) || "");
  const inHand = !!held && (!!(bot.registry && bot.registry.foodsByName && bot.registry.foodsByName[name])
    || USED_IN_HAND.test(name));
  let target = null, block = null;
  try { target = bot.entityAtCursor(3.5); } catch { /* nobody */ }
  if (target && !inHand) {
    Promise.resolve(bot.activateEntity(target)).catch(() => {});
    return;
  }
  try { block = bot.blockAtCursor(4.5); } catch { /* nothing there */ }
  if (block && (!inHand || OPENS.test(block.name))) {
    const at = block.intersect ? block.intersect.minus(block.position) : vec(0.5, 0.5, 0.5);
    useOnBlock(bot, block, Number.isInteger(block.face) ? block.face : 1, at);
    return;
  }
  if (held) {
    try {
      bot.activateItem();
      driving.usingItem = true;
    } catch { /* nothing to use */ }
  }
}

function press(bot, button, down) {
  const was = driving.mouse[button];
  driving.mouse[button] = down;
  if (button === "attack") {
    if (down && !was) hit(bot);
    else if (down) keepDigging(bot);
    else if (was) stopBreaking(bot);
  } else if (down && !was) {
    use(bot);
  } else if (!down && was && driving.usingItem) {
    try { bot.deactivateItem(); } catch { /* nothing in use */ }
    driving.usingItem = false;
  }
}

/** The keys held and where it looks, as the panel has them now: sent whole each time, so a lost one costs nothing. */
export function input(bot, body = {}) {
  if (!driving.on) return { ok: false, driving: false, reason: "Take control first." };
  driving.beat = Date.now();
  const keys = (body && body.keys) || {};
  let any = false;
  for (const k of KEYS) {
    const want = !!keys[k];
    any = any || want;
    try { if (!!bot.controlState[k] !== want) bot.setControlState(k, want); } catch { /* not in a world */ }
  }
  driving.keysOn = any;
  const yaw = Number(body.yaw), pitch = Number(body.pitch);
  if (Number.isFinite(yaw) && Number.isFinite(pitch)) {
    try {
      Promise.resolve(bot.look(yaw, Math.max(-Math.PI / 2, Math.min(Math.PI / 2, pitch)), true)).catch(() => {});
    } catch { /* not in a world */ }
  }
  if ("attack" in body) press(bot, "attack", !!body.attack);
  if ("use" in body) press(bot, "use", !!body.use);
  return { ok: true, driving: true };
}

/** The game's own "drop" and "swap hands" (player digging, statuses 3, 4 and 6), exactly as a client sends them. */
function handPacket(bot, status) {
  bot._client.write("block_dig", { status, location: vec(0, 0, 0), face: 0, sequence: 0 });
}

/** Where a piece of armour goes on, or the hand for anything else. */
function placeFor(item) {
  const m = String((item && item.name) || "").match(/_(helmet|chestplate|leggings|boots)$/);
  return m ? { helmet: "head", chestplate: "torso", leggings: "legs", boots: "feet" }[m[1]]
    : item && item.name === "elytra" ? "torso" : "hand";
}

/** One thing done, as a key or a click does it. */
export async function act(bot, body = {}) {
  const what = String(body.do || "");
  if (what === "respawn") {
    try { bot.respawn(); } catch { /* alive */ }
    return { ok: true };
  }
  if (what === "close") {
    try { if (bot.currentWindow) bot.closeWindow(bot.currentWindow); } catch { /* closed */ }
    return { ok: true };
  }
  if (!driving.on) return { ok: false, driving: false, reason: "Take control first." };
  driving.beat = Date.now();
  if (what === "slot") {
    bot.setQuickBarSlot(Math.max(0, Math.min(8, Math.trunc(Number(body.slot) || 0))));
  } else if (what === "drop") {
    if (bot.heldItem) handPacket(bot, body.all ? 3 : 4);
  } else if (what === "swap") {
    handPacket(bot, 6);
  } else if (what === "equip") {
    const item = bot.inventory && bot.inventory.slots[Math.trunc(Number(body.slot))];
    if (!item) return { ok: false, reason: "That slot is empty now." };
    await bot.equip(item, placeFor(item));
  } else if (what === "move" || what === "click") {
    // A server's menu, a chest, anything open: a slot clicked as the game clicks it, left or right, or with Shift
    // (and "move") to send it across.
    const w = bot.currentWindow;
    if (!w) return { ok: false, reason: "Nothing is open." };
    let slot = Math.trunc(Number(body.slot));
    // One of its own (9..44 in its inventory) is that many into the open window's inventory part.
    if (body.own) slot = Number(w.inventoryStart) + (slot - 9);
    if (!Number.isFinite(slot) || slot < 0 || slot >= w.slots.length) return { ok: false, reason: "No such slot." };
    const shift = what === "move" || !!body.shift;
    if (shift && !w.slots[slot]) return { ok: false, reason: "That slot is empty now." };
    await bot.clickWindow(slot, body.button === 1 ? 1 : 0, shift ? 1 : 0);
  } else {
    return { ok: false, reason: "not something it can do" };
  }
  return { ok: true };
}

/** A line typed into its chat from the panel, as it: words, or a /command. */
export function sayAs(bot, body = {}) {
  const text = String((body && body.text) || "").replace(/\s+/g, " ").trim().slice(0, 256);
  if (!text) return { ok: false, reason: "Nothing to say." };
  try {
    bot.chat(text);
  } catch (e) {
    return { ok: false, reason: String((e && e.message) || e).slice(0, 200) };
  }
  return { ok: true };
}

// ── A server's own menus ─────────────────────────────────────────────────────
// A server's menus are chests whose items are buttons: a compass named "Server Selector" opens one, /settings opens
// rows of toggles. mindcraft has no idea of them, so its AI stood in front of them with nothing to do. It is told
// what is in one, and given commands for them (registered by teachMenus, below): use an item by its name, look at
// the menu, click a slot, close it, run a server command.
let menuBusy = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Commands it never runs by itself: they pay, sell, trade, give away, or end it. Its owner's call, not its.
const NEVER_RUN = /^(pay|give|trade|sell|sellall|ah|auction|auctionhouse|bid|bounty|gamble|coinflip|cf|bet|lottery|jackpot|transfer|withdraw|deposit|kill|suicide|tpaccept|tpyes)$/i;
// What a menu item that costs something says.
const SPENDS = /\b(buy|sell|purchase|pay|cost|price|confirm|bid|auction|coins?|gems?|money|credits?)\b|\$/i;

function itemName(it) {
  let custom = "";
  try { custom = it.customName ? bare(plain(it.customName)) : ""; } catch { /* none */ }
  return custom || String(it.displayName || it.name || "");
}

/** An item's lines of description, as the server wrote them. */
export function loreOf(it) {
  try {
    let lines = it && it.customLore;
    for (let i = 0; i < 3 && lines && !Array.isArray(lines) && typeof lines === "object" && "value" in lines; i++) {
      lines = lines.value;
    }
    if (!lines) return [];
    return (Array.isArray(lines) ? lines : [lines]).map((l) => bare(plain(l))).filter(Boolean).slice(0, 4);
  } catch {
    return [];
  }
}

/** The open menu in words, for its AI: its title, and each slot that holds something, with what it says. */
export function describeMenu(bot) {
  const w = bot.currentWindow;
  if (!w) return "No menu is open.";
  const n = Math.max(0, Math.min(90, Number(w.inventoryStart || 0)));
  const lines = [`Menu open: "${bare(plain(w.title)) || "untitled"}" (${n} slots).`];
  let shown = 0;
  for (let i = 0; i < n && shown < 45; i++) {
    const it = w.slots[i];
    if (!it) continue;
    const name = itemName(it);
    const lore = loreOf(it);
    // Blank panes are the menu's frame, not buttons.
    if (/stained_glass_pane$|^glass_pane$/.test(it.name) && !lore.length && (!name.trim() || /glass pane/i.test(name))) continue;
    const words = `${name} ${lore.join(" ")}`;
    lines.push(`slot ${i}: ${name || it.name}${it.count > 1 ? ` x${it.count}` : ""}`
      + `${lore.length ? ` - ${lore.join(" / ").slice(0, 160)}` : ""}${SPENDS.test(words) ? " (spends money)" : ""}`);
    shown += 1;
  }
  if (!shown) lines.push("Nothing in it yet.");
  lines.push("Click one with !clickMenuSlot(slot), or close it with !closeMenu. Click nothing marked (spends money) unless your owner asked for it.");
  return lines.join("\n");
}

/** The next menu to open, or null after `ms`. */
function nextMenu(bot, ms) {
  return new Promise((resolve) => {
    const done = (w) => {
      clearTimeout(t);
      bot.removeListener("windowOpen", done);
      resolve(w || null);
    };
    const t = setTimeout(() => done(null), ms);
    bot.on("windowOpen", done);
  });
}

/** What the server says (its own lines, not players' chat) until stopped. */
function hearServer(bot) {
  const said = [];
  const listen = (text, position) => {
    const t = bare(text);
    if (position !== "chat" && t && said.length < 4) said.push(t.slice(0, 160));
  };
  bot.on("messagestr", listen);
  return () => {
    bot.removeListener("messagestr", listen);
    return said;
  };
}

export async function useNamedItem(bot, query) {
  const q = String(query || "").toLowerCase().trim();
  const slots = (bot.inventory && bot.inventory.slots) || [];
  const order = [36, 37, 38, 39, 40, 41, 42, 43, 44, 45];
  for (let i = 9; i < 36; i++) order.push(i);
  let found = -1;
  for (const s of order) {
    const it = slots[s];
    if (!it) continue;
    if (!q || itemName(it).toLowerCase().includes(q) || String(it.name).includes(q.replace(/\s+/g, "_"))) {
      found = s;
      break;
    }
  }
  if (found < 0) return `Nothing it carries is called "${query}".`;
  const it = slots[found];
  try {
    if (found >= 36 && found <= 44) bot.setQuickBarSlot(found - 36);
    else await bot.equip(it, "hand");
  } catch (e) {
    return `It could not take ${itemName(it)} in hand: ${String((e && e.message) || e).slice(0, 120)}`;
  }
  await sleep(250);
  menuBusy = true;
  const stop = hearServer(bot);
  const opened = nextMenu(bot, 2500);
  try { bot.activateItem(); } catch { /* nothing to use */ }
  await sleep(150);
  try { bot.deactivateItem(); } catch { /* done */ }
  const w = await opened;
  const said = stop();
  menuBusy = false;
  if (w) return `Used ${itemName(it)}.\n${describeMenu(bot)}`;
  return `Used ${itemName(it)}. No menu opened.${said.length ? ` The server said: ${said.join(" | ")}` : ""}`;
}

export async function clickMenu(bot, slot) {
  const w = bot.currentWindow;
  if (!w) return "No menu is open. Open one first, with !useItem or !runCommand.";
  const n = Number(w.inventoryStart || 0);
  if (!Number.isInteger(slot) || slot < 0 || slot >= n) return `This menu's slots are 0 to ${n - 1}.`;
  if (!w.slots[slot]) return `Slot ${slot} is empty.`;
  const name = itemName(w.slots[slot]);
  menuBusy = true;
  const stop = hearServer(bot);
  const opened = nextMenu(bot, 1500);
  let closed = false;
  const onClose = () => { closed = true; };
  bot.once("windowClose", onClose);
  try {
    await bot.clickWindow(slot, 0, 0);
    // Something left on the cursor (a real chest, not a menu) goes back where it came from.
    if (bot.currentWindow && bot.currentWindow.selectedItem) await bot.clickWindow(slot, 0, 0);
  } catch (e) {
    bot.removeListener("windowClose", onClose);
    stop();
    menuBusy = false;
    return `The click did not go through: ${String((e && e.message) || e).slice(0, 120)}`;
  }
  const next = await opened;
  bot.removeListener("windowClose", onClose);
  const said = stop();
  menuBusy = false;
  const heard = said.length ? `\nThe server said: ${said.join(" | ")}` : "";
  if (next) return `Clicked ${name}. Another menu opened.\n${describeMenu(bot)}${heard}`;
  if (closed || !bot.currentWindow) return `Clicked ${name}. The menu closed.${heard}`;
  return `Clicked ${name}.${heard}\n${describeMenu(bot)}`;
}

export function closeMenu(bot) {
  const w = bot.currentWindow;
  if (!w) return "No menu is open.";
  try { bot.closeWindow(w); } catch { /* closed */ }
  return "Closed it.";
}

export async function runServerCommand(bot, command) {
  const text = String(command || "").replace(/\s+/g, " ").trim().replace(/^\/+/, "").slice(0, 200);
  if (!text) return "Which command?";
  const verb = text.split(" ")[0].toLowerCase().replace(/^[a-z0-9_]+:/, "");
  if (NEVER_RUN.test(verb)) return `Not /${verb}: it pays, sells, trades or gives things away. That is your owner's call.`;
  menuBusy = true;
  const stop = hearServer(bot);
  const opened = nextMenu(bot, 2500);
  try {
    bot.chat(`/${text}`);
  } catch (e) {
    stop();
    menuBusy = false;
    return `/${text} could not be sent: ${String((e && e.message) || e).slice(0, 120)}`;
  }
  const w = await opened;
  const said = stop();
  menuBusy = false;
  if (w) return `/${text} opened a menu.\n${describeMenu(bot)}`;
  return said.length ? `/${text}: the server said ${said.join(" | ")}` : `/${text} was sent. The server said nothing back.`;
}

// The commands, as mindcraft writes its own (commands/actions.js), and the words its docs give them (profile.py).
export const MENU_COMMANDS = [
  { name: "!useItem", description: "Hold the item with this name and right-click it, as a player opens a server's menus.",
    params: { name: { type: "string", description: "Part of its name as the server shows it, or its kind." } },
    perform: async (agent, name) => useNamedItem(agent.bot, name) },
  { name: "!menu", description: "Look at the menu open on your screen: its title, and each slot's item.",
    perform: async (agent) => describeMenu(agent.bot) },
  { name: "!clickMenuSlot", description: "Click a slot in the open menu, by its number from !menu.",
    params: { slot: { type: "int", description: "The slot number.", domain: [0, 90] } },
    perform: async (agent, slot) => clickMenu(agent.bot, slot) },
  { name: "!closeMenu", description: "Close the menu that is open.", perform: async (agent) => closeMenu(agent.bot) },
  { name: "!runCommand", description: "Run a server command, without the slash.",
    params: { command: { type: "string", description: "The command, like settings or warp shop." } },
    perform: async (agent, command) => runServerCommand(agent.bot, command) },
];

/** Items with the server's own names, for its inventory: "compass: 'Server Selector (Right Click)'". */
function namedItems(bot) {
  const out = [];
  const slots = (bot.inventory && bot.inventory.slots) || [];
  for (let s = 9; s <= 45; s++) {
    const it = slots[s];
    if (!it) continue;
    let custom = "";
    try { custom = it.customName ? bare(plain(it.customName)) : ""; } catch { /* none */ }
    if (custom) out.push(`- ${it.name}: "${custom.slice(0, 60)}"${s >= 36 && s <= 44 ? ` (hotbar ${s - 35})` : ""}`);
  }
  return out.slice(0, 12);
}

/**
 * mindcraft's AI taught the menus. mindcraft looks each command up by name in one plain object (commandMap, in
 * src/agent/commands/index.js) and has no way to add one; a name the object lacks is looked up on its prototype, so
 * these sit there: never enumerated, never copied, under names only mindcraft's commands use ("!..."). Its stats
 * say when a menu is open, its inventory says what the server named its items, and a menu a server opens by itself
 * (a captcha, a welcome screen) is put to it while it is not busy with something else.
 */
export async function teachMenus(bot, agent, commandOf = null) {
  if (!agent) return false;
  for (const c of MENU_COMMANDS) {
    if (!Object.prototype.hasOwnProperty.call(Object.prototype, c.name)) {
      Object.defineProperty(Object.prototype, c.name, { value: c, enumerable: false, configurable: true, writable: true });
    }
  }
  try {
    let getCommand = commandOf;
    if (!getCommand) {
      const fs = require("fs");
      const main = pathToFileURL(fs.realpathSync(process.argv[1]));
      ({ getCommand } = await import(new URL("../agent/commands/index.js", main).href));
    }
    const wrap = (name, more) => {
      const c = getCommand(name);
      if (!c || c.__lsb) return;
      const perform = c.perform;
      c.perform = async function (a, ...rest) {
        const out = await perform.call(this, a, ...rest);
        try {
          const extra = more(a.bot);
          return extra ? `${out}\n${extra}` : out;
        } catch {
          return out;
        }
      };
      c.__lsb = true;
    };
    wrap("!stats", (b) => (b.currentWindow
      ? `- Menu open on your screen: "${bare(plain(b.currentWindow.title))}" (see it with !menu)` : ""));
    wrap("!inventory", (b) => {
      const named = namedItems(b);
      return named.length ? `WITH THE SERVER'S OWN NAMES (right-click one with !useItem):\n${named.join("\n")}` : "";
    });
  } catch { /* its stats as they were */ }
  let lastTold = 0;
  bot.on("windowOpen", () => {
    if (menuBusy || driving.on || Date.now() - lastTold < 15000) return;
    try { if (typeof agent.isIdle === "function" && !agent.isIdle()) return; } catch { return; }
    lastTold = Date.now();
    setTimeout(() => {
      if (!bot.currentWindow || driving.on) return;
      try { agent.handleMessage("system", `A menu opened on your screen by itself.\n${describeMenu(bot)}`); } catch { /* busy */ }
    }, 400);
  });
  return true;
}

// ── A 1.21 client, as a server expects one ───────────────────────────────────
// What the game's own client sends and mineflayer does not, which a strict server (DonutSMP) took for a cheat client:
// it ran none of its commands (no reply at all, not even to /msg) and refused its blocks. Measured there: with its
// keys sent as they are, /settings opened its menu at once.
//   - One numbering for everything it predicts (breaking, using an item, using one on a block), always rising.
//     mineflayer counts its item uses on their own and leaves breaking at 0, so the numbers went backwards.
//   - Its keys as they are (player_input, 1.21.2 on), whenever they change. mineflayer sends it for sneaking only,
//     every other key up, so the server was told nothing was held while it walked and dug.
export function playLikeTheGame(bot, given = null) {
  const client = bot._client;
  if (!client || client.__lsbGame) return false;
  client.__lsbGame = true;
  let types = given || {};
  if (!given) {
    try { types = require("minecraft-data")(bot.version).protocol.play.toServer.types || {}; } catch { /* unknown */ }
  }
  const numbered = JSON.stringify(types.packet_block_dig || "").includes("sequence");
  const write = client.write;
  let sequence = 0;
  if (numbered) {
    client.write = function (name, params) {
      const predicted = (name === "block_dig" && params && [0, 1, 2].includes(Number(params.status)))
        || name === "use_item" || name === "block_place";
      return write.call(this, name, predicted && params ? { ...params, sequence: ++sequence } : params);
    };
  }
  if (types.packet_player_input) {
    let last = "";
    const sendKeys = () => {
      const c = bot.controlState || {};
      const inputs = { forward: !!c.forward, backward: !!c.back, left: !!c.left, right: !!c.right, jump: !!c.jump,
                       shift: !!c.sneak, sprint: !!c.sprint };
      const now = JSON.stringify(inputs);
      if (now === last) return;
      last = now;
      try { write.call(client, "player_input", { inputs }); } catch { /* between worlds */ }
    };
    const set = bot.setControlState, clear = bot.clearControlStates;
    if (typeof set === "function") bot.setControlState = function (...a) { const r = set.apply(this, a); sendKeys(); return r; };
    if (typeof clear === "function") bot.clearControlStates = function (...a) { const r = clear.apply(this, a); sendKeys(); return r; };
  }
  // Not the end of each tick (tick_end), which the game's client also sends: with it, a server can tell exactly which
  // packets went in which tick and hold mineflayer to the game's order inside one, which it does not keep (its
  // actions arrive after its movement). DonutSMP kicked it for "Invalid sequence" within minutes of it, and its
  // commands work without it (measured: /settings opened with the keys alone).
  return true;
}

// ── What it sends and gets, for the debug screen ─────────────────────────────
// The packets that say what happened (a command, a dig, a click, a menu, a kick), not the stream of movement and
// world that is most of them.
const NOISY = /position|look|flying|keep_alive|entity|move|chunk|light|sound|particle|update_time|block_change|multi_block|ping|pong|bundle|tick|velocity|head_rotation|teleport|metadata|equipment|attributes|player_info|update_health|experience|map|boss_bar|scoreboard|teams|statistics|world_event|block_action|damage|animation|collect|hurt|arm_animation|player_chat|set_slot|spawn|steer|vehicle|world_border|chat_suggestions|declare|tags|recipe|advancement|tab_complete|custom_payload/;
const net = { sent: [], got: [] };

export function traceNet(bot) {
  const client = bot._client;
  if (!client || client.__lsbTraced) return;
  client.__lsbTraced = true;
  const write = client.write;
  client.write = function (name, params) {
    if (!NOISY.test(name)) {
      net.sent.push([name, Date.now()]);
      if (net.sent.length > 10) net.sent.shift();
    }
    return write.call(this, name, params);
  };
  client.on("packet", (_data, meta) => {
    const name = meta && meta.name;
    if (!name || NOISY.test(name)) return;
    net.got.push([name, Date.now()]);
    if (net.got.length > 10) net.got.shift();
  });
}

function netOf() {
  const now = Date.now();
  const say = (list) => list.slice(-6).reverse().map(([n, at]) => `${n} ${Math.max(0, Math.round((now - at) / 1000))}s`);
  return { sent: say(net.sent), got: say(net.got) };
}

// ── The names over players' heads ────────────────────────────────────────────
/** What prismarine-viewer's bundle does with a player's name, exactly as it ships it (viewer/lib/entities.js,
 *  built into public/index.js): a 500x100 canvas, black text, left-aligned at x=100, on a sprite left at one unit
 *  square. Dark on dark, squashed flat, and off to one side of the player it belongs to. */
export const NAMETAG_AS_SHIPPED =
  'const e=s(500,100),r=e.getContext("2d");r.font="50pt Arial",r.fillStyle="#000000",r.textAlign="left",' +
  'r.textBaseline="top";const a=t.username;r.fillText(a,100,0);const o=new n.Texture(e);o.needsUpdate=!0;' +
  'const l=new n.SpriteMaterial({map:o}),u=new n.Sprite(l);u.position.y+=t.height+.6,i.mesh.add(u)';

/** The same thing, drawn as the game draws it: white on a soft dark plate, centred over them, in proportion, and
 *  readable through what is in front of it, which is what Minecraft does with a name.
 *
 *  What it is given says what to draw (lookFor, below, on the bot's side): a name; "\u0001" and text, a line of a
 *  server's floating text, drawn alone with the stand it hangs on hidden; "\u0002" and a player's name, whose team
 *  hides it (their skin is still theirs); "name\u0003shown", a player whose team writes it "[VIP] Steve"; or
 *  "\u0004" and a picture's address, a dropped item drawn as its own picture. */
export const NAMETAG_AS_DRAWN = [
  'const z=String(t.username),k=z.charCodeAt(0),Q=z.indexOf("\\u0003"),',
  'U=k===1||k===4?"":k===2?z.slice(1):Q>=0?z.slice(0,Q):z,a=k===1?z.slice(1):k===2||k===4?"":Q>=0?z.slice(Q+1):z;let u=null;',
  'if(k===4){const L=new n.TextureLoader().load(z.slice(1));L.magFilter=n.NearestFilter,L.minFilter=n.NearestFilter;',
  'u=new n.Sprite(new n.SpriteMaterial({map:L,transparent:!0,alphaTest:.1})),u.scale.set(.4,.4,1),u.position.y+=.3,',
  'i.mesh.add(u),i.mesh.__lsbItem=u}',
  'if(a){const F=64,M=s(8,8).getContext("2d");M.font=F+"px sans-serif";',
  'const W=Math.ceil(M.measureText(a).width),P=Math.round(.45*F),cw=W+2*P,ch=Math.round(1.5*F),R=Math.round(.3*ch);',
  'const e=s(cw,ch),r=e.getContext("2d");r.font=F+"px sans-serif",r.textAlign="center",r.textBaseline="middle";',
  'r.beginPath(),r.moveTo(R,0),r.arcTo(cw,0,cw,ch,R),r.arcTo(cw,ch,0,ch,R),r.arcTo(0,ch,0,0,R),r.arcTo(0,0,cw,0,R),',
  'r.closePath(),r.fillStyle=k===1?"rgba(12,10,16,.38)":"rgba(12,10,16,.62)",r.fill();',
  'r.fillStyle="#ffffff",r.fillText(a,cw/2,ch/2+1);',
  'const o=new n.Texture(e);o.needsUpdate=!0,o.minFilter=n.LinearFilter;',
  'const l=new n.SpriteMaterial({map:o,transparent:!0,depthTest:!1}),H=.42;u=new n.Sprite(l);',
  'u.scale.set(H*cw/ch,H,1),u.position.y+=t.height+.45,u.renderOrder=999,i.mesh.add(u),',
  'u.__lsbW=H*cw/ch,u.__lsbH=H,i.mesh.__lsbTag=u}',
  '(k===1||k===4)&&i.mesh.children.forEach(c=>{c!==u&&(c.visible=!1)}),i.mesh.__lsbUser=U',
].join("");

/** The page's connection to the bot, kept where the panel around it can use it: the keys and the mouse go over it
 *  as they happen, rather than as a web request each, and the view turns from its eyes to above without reloading
 *  the whole world. */
export const SOCKET_AS_SHIPPED = 'o=i(8007)({path:window.location.pathname+"socket.io"});';
export const SOCKET_AS_PATCHED = 'o=window.__lsbSocket=i(8007)({path:window.location.pathname+"socket.io"});';

/** Its models' bones, which the viewer builds without their names (they live only in a table while it builds
 *  them): named, so the page script can find a player's legs, arms and head to move them. */
export const BONES_AS_SHIPPED = "i[t.name]=r,t.cubes)for(const i of t.cubes)";
export const BONES_AS_PATCHED = "i[t.name]=r,r.name=t.name,t.cubes)for(const i of t.cubes)";

// ── The camera and everyone in view, gliding ───────────────────────────────
// Each is the viewer's code exactly as it ships, and what it becomes: it stops tweening for 50 ms per update and says
// where each thing should be instead, for the app's script (lsbView, below) to ease it there every frame. Where that
// script is not loaded (window.__lsbView unset), each falls back to the viewer's own tween, so a page this does not
// fully fit still moves the way it always did.

/** The list of entities, handed to the page script. */
export const ENTITIES_AS_SHIPPED = "constructor(t){this.scene=t,this.entities={}}";
export const ENTITIES_AS_PATCHED = "constructor(t){this.scene=t,this.entities={},window.__lsbEntities=this}";

/** Every other player and mob: where it should be and which way it faces, rather than a 50 ms tween. */
export const ENTITY_MOVE_AS_SHIPPED =
  "t.pos&&new r.Tween(e.position).to({x:t.pos.x,y:t.pos.y,z:t.pos.z},50).start(),t.yaw){const i=(t.yaw-e.rotation.y)%(2*Math.PI),n=2*i%(2*Math.PI)-i;new r.Tween(e.rotation).to({y:e.rotation.y+n},50).start()}";
export const ENTITY_MOVE_AS_PATCHED =
  "t.pos&&(window.__lsbView?(e.__lsbGoal={x:t.pos.x,y:t.pos.y,z:t.pos.z},e.__lsbPlaced||(e.position.set(t.pos.x,t.pos.y,t.pos.z),e.__lsbPlaced=!0)):new r.Tween(e.position).to({x:t.pos.x,y:t.pos.y,z:t.pos.z},50).start()),void 0!==t.pitch&&(e.__lsbPitch=t.pitch),t.yaw){if(window.__lsbView){e.__lsbYaw=t.yaw,e.__lsbTurned||(e.rotation.y=t.yaw,e.__lsbTurned=!0)}else{const i=(t.yaw-e.rotation.y)%(2*Math.PI),n=2*i%(2*Math.PI)-i;new r.Tween(e.rotation).to({y:e.rotation.y+n},50).start()}}";

/** The camera: a goal and an aim, instead of a 50 ms tween for where it is and its turn set outright - which is
 *  what made looking around go in steps. */
export const CAMERA_AS_SHIPPED =
  'setFirstPersonCamera(t,e,i){if(t){let e=t.y+this.playerHeight;this.isSneaking&&(e-=.3),new r.Tween(this.camera.position).to({x:t.x,y:e,z:t.z},50).start()}this.camera.rotation.set(i,e,0,"ZYX")}';
export const CAMERA_AS_PATCHED =
  'setFirstPersonCamera(t,e,i){window.__lsbViewer=this;if(!window.__lsbView){if(t){let e=t.y+this.playerHeight;this.isSneaking&&(e-=.3),new r.Tween(this.camera.position).to({x:t.x,y:e,z:t.z},50).start()}this.camera.rotation.set(i,e,0,"ZYX");return}if(t){let e=t.y+this.playerHeight;this.isSneaking&&(e-=.3),this.__lsbGoal={x:t.x,y:e,z:t.z},this.__lsbPlaced||(this.camera.position.set(t.x,e,t.z),this.__lsbPlaced=!0)}this.__lsbYaw=e,this.__lsbPitch=i,this.__lsbAimed||(this.camera.rotation.set(i,e,0,"ZYX"),this.__lsbAimed=!0)}';

/** The bot's own body, drawn in the view from above: handed over too, so it walks as well. */
export const SELF_AS_SHIPPED =
  'i){e||(e=new a("1.16.4","player",u.scene).mesh,u.scene.add(e)),new n.Tween(e.position).to({x:t.x,y:t.y,z:t.z},50).start();const i=(r-e.rotation.y)%(2*Math.PI),o=2*i%(2*Math.PI)-i;new n.Tween(e.rotation).to({y:e.rotation.y+o},50).start()}';
export const SELF_AS_PATCHED =
  'i){e||(e=new a("1.16.4","player",u.scene).mesh,u.scene.add(e),window.__lsbSelf=e);if(window.__lsbView){e.__lsbGoal={x:t.x,y:t.y,z:t.z},e.__lsbPlaced||(e.position.set(t.x,t.y,t.z),e.__lsbPlaced=!0),e.__lsbYaw=r,e.__lsbTurned||(e.rotation.y=r,e.__lsbTurned=!0)}else{new n.Tween(e.position).to({x:t.x,y:t.y,z:t.z},50).start();const i=(r-e.rotation.y)%(2*Math.PI),o=2*i%(2*Math.PI)-i;new n.Tween(e.rotation).to({y:e.rotation.y+o},50).start()}}';

/** Every change made to the viewer's page, by what it is for. Each is applied on its own: one that no longer fits
 *  leaves only its own part as it was. */
export const PAGE_PATCHES = [
  { name: "the names over players' heads", shipped: NAMETAG_AS_SHIPPED, patched: NAMETAG_AS_DRAWN },
  { name: "the list of entities", shipped: ENTITIES_AS_SHIPPED, patched: ENTITIES_AS_PATCHED },
  { name: "how others move", shipped: ENTITY_MOVE_AS_SHIPPED, patched: ENTITY_MOVE_AS_PATCHED },
  { name: "how the camera moves", shipped: CAMERA_AS_SHIPPED, patched: CAMERA_AS_PATCHED },
  { name: "its own body from above", shipped: SELF_AS_SHIPPED, patched: SELF_AS_PATCHED },
  { name: "the bones of its models", shipped: BONES_AS_SHIPPED, patched: BONES_AS_PATCHED },
  { name: "its connection, for the panel", shipped: SOCKET_AS_SHIPPED, patched: SOCKET_AS_PATCHED },
];

/**
 * The app's part of the live view, running in the viewer's page (served as lsb_view.js and loaded after the viewer's
 * own bundle). It is written as an ordinary function so it can be read, but it never runs here: its source is sent,
 * so it may use nothing from this file.
 *
 *   - Glide. Everything eases toward where it was last told to be, every frame, the turn included and the short way
 *     round: smooth whatever the packets' timing, where 50 ms tweens stalled and jumped on every late one.
 *   - Walk. Legs swing opposite each other and arms opposite the legs, as far as each one is moving fast, settling
 *     still when it stops; heads look where they look.
 *   - Skins. Each player in their own, from the server's player list, fetched through the bot's own server so the
 *     page may paint with it. The default skin is one texture shared by everyone, so each gets a copy of its own.
 */
export function lsbView() {
  const BASE = location.pathname.replace(/[^/]*$/, "");    // the view's own folder, with its slash
  const CAMERA_RATE = 16, BODY_RATE = 14;                  // per second: catches up in a few frames, never jumps
  const WALK = 4.3;                                        // blocks a second, walking
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  const skins = new Map();
  let self = "";
  window.__lsbView = true;

  // Played by hand, the camera keeps up faster (it is following the hands, not watching), and from above it sits
  // behind the head along where it looks, as the game's own view from behind does.
  const CAMERA_RATE_PLAYED = 30, BEHIND = 4;
  // Its own body shows from above only; the panel says which (window.__lsbAbove) as it switches without reloading.
  window.__lsbAbove = /[?&]view=above\b/.test(location.search);

  function easeCamera(v, dt) {
    const cam = v.camera;
    // Played by hand: the panel around this page turns the camera with the mouse at once (window.__lsbLook), so
    // the eyes never wait the round trip for the bot's own turn.
    const own = window.__lsbLook;
    const played = !!own && Date.now() - own.at < 1000;
    const body = window.__lsbSelf;
    if (played && own.above && body) {
      const s = body.position, cp = Math.cos(own.pitch);
      cam.position.set(s.x + Math.sin(own.yaw) * cp * BEHIND, s.y + 1.62 - Math.sin(own.pitch) * BEHIND,
                       s.z + Math.cos(own.yaw) * cp * BEHIND);
      cam.rotation.set(own.pitch, own.yaw, 0, "ZYX");
      body.__lsbYaw = own.yaw;
      return;
    }
    const k = 1 - Math.exp(-dt * (played ? CAMERA_RATE_PLAYED : CAMERA_RATE)), g = v.__lsbGoal;
    if (g) {
      // A jump of more than a few blocks is a teleport, not walking: there, at once.
      if (Math.hypot(g.x - cam.position.x, g.z - cam.position.z) > 8) cam.position.set(g.x, g.y, g.z);
      cam.position.x += (g.x - cam.position.x) * k;
      cam.position.y += (g.y - cam.position.y) * k;
      cam.position.z += (g.z - cam.position.z) * k;
    }
    if (played) {
      cam.rotation.set(own.pitch, own.yaw, 0, "ZYX");
    } else if (v.__lsbYaw !== undefined) {
      cam.rotation.set(cam.rotation.x + (v.__lsbPitch - cam.rotation.x) * k,
                       cam.rotation.y + wrap(v.__lsbYaw - cam.rotation.y) * k, 0, "ZYX");
    }
  }

  function limbs(mesh) {
    if (mesh.__lsbLimbs !== undefined) return mesh.__lsbLimbs;
    const found = {};
    mesh.traverse((o) => {
      if (o.isBone && /^(head|leftArm|rightArm|leftLeg|rightLeg)$/.test(o.name) && !found[o.name]) {
        found[o.name] = { bone: o, rest: o.rotation.x };
      }
    });
    mesh.__lsbLimbs = Object.keys(found).length ? found : null;
    return mesh.__lsbLimbs;
  }

  function move(mesh, dt) {
    const k = 1 - Math.exp(-dt * BODY_RATE), g = mesh.__lsbGoal;
    let speed = 0;
    if (g) {
      const dx = g.x - mesh.position.x, dz = g.z - mesh.position.z;
      if (Math.hypot(dx, dz) > 8) mesh.position.set(g.x, g.y, g.z);
      // The goal leads the body by a steady distance while it moves, so that distance is its speed.
      else speed = Math.hypot(dx, dz) * BODY_RATE;
      mesh.position.x += (g.x - mesh.position.x) * k;
      mesh.position.y += (g.y - mesh.position.y) * k;
      mesh.position.z += (g.z - mesh.position.z) * k;
    }
    if (mesh.__lsbYaw !== undefined) mesh.rotation.y += wrap(mesh.__lsbYaw - mesh.rotation.y) * k;
    const l = limbs(mesh);
    if (!l) return;
    const stride = Math.min(1, speed / WALK);
    mesh.__lsbStride = (mesh.__lsbStride || 0) + (stride - (mesh.__lsbStride || 0)) * Math.min(1, dt * 8);
    mesh.__lsbPhase = (mesh.__lsbPhase || 0) + dt * (5 + 6 * mesh.__lsbStride);
    const swing = Math.sin(mesh.__lsbPhase) * 0.85 * mesh.__lsbStride;
    if (l.leftLeg) l.leftLeg.bone.rotation.x = l.leftLeg.rest + swing;
    if (l.rightLeg) l.rightLeg.bone.rotation.x = l.rightLeg.rest - swing;
    if (l.leftArm) l.leftArm.bone.rotation.x = l.leftArm.rest - swing * 0.75;
    if (l.rightArm) l.rightArm.bone.rotation.x = l.rightArm.rest + swing * 0.75;
    if (l.head && mesh.__lsbPitch !== undefined) {
      l.head.bone.rotation.x = l.head.rest + Math.max(-1.2, Math.min(1.2, -mesh.__lsbPitch));
    }
  }

  function dress(mesh, name) {
    if (!name || mesh.__lsbSkinned === name) return;
    const s = skins.get(name);
    if (!s) return;
    mesh.__lsbSkinned = name;
    const img = new Image();
    img.onload = () => {
      if (img.height < 64) return;   // an old 64x32 skin: the model is cut for 64x64, so the default stays
      mesh.traverse((o) => {
        if (!o.isSkinnedMesh || !o.material || !o.material.map) return;
        const tex = o.material.map.clone();
        tex.image = img;
        tex.needsUpdate = true;
        o.material = o.material.clone();
        o.material.__lsbOwn = true;
        o.material.map = tex;
        o.material.needsUpdate = true;
      });
    };
    img.src = `${BASE}skin/${s.hash}.png`;
  }

  /** A body's see-through-ness, on its own copy of its material (the default skin's is shared by everyone). */
  function fade(mesh, alpha) {
    if (mesh.__lsbAlpha === alpha) return;
    mesh.__lsbAlpha = alpha;
    mesh.traverse((o) => {
      if (!o.isSkinnedMesh || !o.material) return;
      if (!o.material.__lsbOwn) {
        o.material = o.material.clone();
        o.material.__lsbOwn = true;
      }
      o.material.transparent = true;
      o.material.opacity = alpha;
      o.material.depthWrite = alpha > 0.99;
    });
  }

  // Someone standing where the camera is (everyone arrives on the same spot in a lobby): their body filled the
  // screen with a few huge pixels of skin, and their name covered it whole. A body fades as it comes within a
  // block and a half and goes at under a block; a name never grows past its size five blocks away, and goes inside
  // a block.
  function near(mesh, cam) {
    const p = mesh.position, c = cam.position;
    const flat = Math.hypot(p.x - c.x, p.z - c.z);
    const level = c.y > p.y - 0.3 && c.y < p.y + 2.3;
    const alpha = !level || flat >= 1.6 ? 1 : Math.max(0, Math.min(1, (flat - 0.8) / 0.8));
    mesh.visible = alpha > 0.05;
    if (mesh.visible) fade(mesh, Math.round(Math.max(0.2, alpha) * 10) / 10);
    const tag = mesh.__lsbTag;
    if (!tag || !tag.__lsbW) return;
    const d = Math.hypot(flat, p.y + 2.2 - c.y);
    const k = Math.min(1, d / 5);
    tag.scale.set(tag.__lsbW * k, tag.__lsbH * k, 1);
    tag.visible = d > 1.1;
  }

  async function readSkins() {
    try {
      const r = await fetch(`${BASE}skins`, { cache: "no-store" });
      const all = await r.json();
      self = String(all.__self || "");
      for (const [name, s] of Object.entries(all)) if (name !== "__self" && s && s.hash) skins.set(name, s);
    } catch { /* between worlds: the next look will do */ }
  }

  // Frames a second, for the debug screen (F3), and pictures of the view (F2). The viewer draws in its own frame
  // callback, which runs before this one each frame, so the picture is still there to be taken.
  let frames = 0, counted = performance.now();
  const shots = [];
  window.__lsbShot = () => new Promise((resolve) => shots.push(resolve));

  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
    last = now;
    try {
      if (window.__lsbViewer) easeCamera(window.__lsbViewer, dt);
      const ents = window.__lsbEntities;
      const cam = window.__lsbViewer && window.__lsbViewer.camera;
      if (ents) {
        for (const mesh of Object.values(ents.entities)) {
          move(mesh, dt);
          dress(mesh, mesh.__lsbUser);
          if (cam) near(mesh, cam);
          // A dropped item bobs where it lies, as in the game.
          if (mesh.__lsbItem) mesh.__lsbItem.position.y = 0.3 + Math.sin(now / 350 + mesh.id) * 0.06;
        }
      }
      if (window.__lsbSelf) {
        window.__lsbSelf.visible = !!window.__lsbAbove;
        move(window.__lsbSelf, dt);
        dress(window.__lsbSelf, self);
      }
    } catch { /* one bad frame is not worth losing the view over */ }
    frames += 1;
    if (now - counted >= 1000) {
      window.__lsbFps = Math.round((frames * 1000) / (now - counted));
      frames = 0;
      counted = now;
    }
    if (shots.length) {
      let url = "";
      try { url = document.querySelector("canvas").toDataURL("image/png"); } catch { /* none */ }
      for (const done of shots.splice(0)) done(url);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  readSkins();
  setInterval(readSkins, 5000);
}

// ── What there is to see ─────────────────────────────────────────────────────
/** One of an entity's metadata, by the name the game gives it ("custom_name"), else at the index it has had since
 *  1.9. */
function metaOf(bot, e, key, index) {
  const meta = e && e.metadata ? e.metadata : {};
  let keys = null;
  try { keys = bot.registry && bot.registry.entitiesByName[e.name] && bot.registry.entitiesByName[e.name].metadataKeys; } catch { /* old data */ }
  const at = Array.isArray(keys) ? keys.indexOf(key) : -1;
  return meta[at >= 0 ? at : index];
}

/**
 * How the game would show an entity, which prismarine-viewer does not work out for itself:
 *   - an invisible one, not at all. A server's floating text is a column of invisible armour stands (or text
 *     displays), and the viewer drew every one as a wooden stand on a stone plate, stacked over people's heads;
 *   - a line of that floating text, as its words alone;
 *   - a player's name as their team writes it ("[VIP] Steve"), or none where their team hides it (a lobby's NPCs);
 *   - a mob's own name where the server shows it.
 * {show: false}, or {show: true, name (its type for the viewer), username (what NAMETAG_AS_DRAWN draws)}.
 */
export function lookFor(bot, e) {
  if (!e) return { show: false };
  const flags = Number(metaOf(bot, e, "shared_flags", 0) || 0);
  const invisible = (flags & 0x20) !== 0;
  let custom = "";
  try { custom = bare(plain(metaOf(bot, e, "custom_name", 2))); } catch { /* none */ }
  const customShown = metaOf(bot, e, "custom_name_visible", 3) === true;
  if (e.type === "player") {
    if (invisible) return { show: false };
    const user = String(e.username || "");
    if (!user) return { show: true, name: e.name };
    const team = bot.teamMap ? bot.teamMap[user] : null;
    if (team && String(team.nameTagVisibility || "always") === "never") {
      return { show: true, name: e.name, username: `\u0002${user}` };
    }
    let shown = user;
    try { if (team && typeof team.displayName === "function") shown = bare(plain(team.displayName(user))) || user; } catch { /* as is */ }
    return { show: true, name: e.name, username: shown === user ? user : `${user}\u0003${shown}` };
  }
  if (e.name === "text_display") {
    let text = "";
    try { text = bare(plain(metaOf(bot, e, "text", 23))); } catch { /* none */ }
    return text ? { show: true, name: "armor_stand", username: `\u0001${text.slice(0, 80)}` } : { show: false };
  }
  if (invisible) {
    return custom && customShown ? { show: true, name: "armor_stand", username: `\u0001${custom.slice(0, 80)}` }
      : { show: false };
  }
  const named = custom && customShown ? custom.slice(0, 48) : undefined;
  if (!models.names || models.names.has(e.name)) return { show: true, name: e.name, username: named };
  // The viewer has no model for it: it drew the first sight of it as nothing and every move after as a magenta box.
  if (e.name === "item") {
    // A dropped item, as its own picture, floating where it lies.
    let icon = "";
    try {
      const it = typeof e.getDroppedItem === "function" ? e.getDroppedItem() : null;
      icon = it ? pictures.items.get(String(it.name)) || "" : "";
    } catch { /* not readable yet */ }
    return icon && pictures.version ? { show: true, name: "armor_stand", username: `\u0004textures/${pictures.version}/${icon}` }
      : { show: false };
  }
  const stand = STAND_INS[e.name];
  if (stand && models.names.has(stand)) return { show: true, name: stand, username: named };
  // A creature with neither: its name where it is, as floating text, rather than nothing or a box.
  if (/^(hostile|passive|animal|water_creature|ambient|mob)$/.test(String(e.type || ""))) {
    const what = named || String(e.displayName || e.name || "").replace(/_/g, " ");
    return what ? { show: true, name: "armor_stand", username: `\u0001${what.slice(0, 48)}` } : { show: false };
  }
  // Boats, falling blocks, frames, paintings, markers: left out.
  return { show: false };
}

/** The viewer's models (its entities.json), loaded with the view; unknown (null) in a test, where all are drawn. */
const models = { names: null };
// The nearest model it has, for creatures it has none for.
const STAND_INS = { bogged: "skeleton", glow_squid: "squid", trader_llama: "llama", illusioner: "vindicator",
                    giant: "zombie", allay: "vex", zombie_horse: "horse", camel: "horse" };

export function loadModels(names) {
  models.names = names ? new Set(names) : null;
}

/**
 * What the viewer's world sends its page about entities, passed through lookFor: what cannot be seen is never
 * sent (nor its moves, which the page would otherwise draw as a magenta box for want of a spawn), and anything that
 * changes how it looks (made invisible, given a name) is drawn again as it now is.
 */
export function seenThrough(bot, socket) {
  const sent = new Map();   // id -> how it was last drawn ("" when it is not)
  const out = (data) => socket.emit("entity", data);
  const view = {
    on: (...args) => socket.on(...args),
    emit(event, data) {
      if (event !== "entity" || !data || data.id == null) return socket.emit(event, data);
      if (data.delete) {
        const had = sent.get(data.id);
        sent.delete(data.id);
        return had ? out(data) : true;
      }
      const e = bot.entities && bot.entities[data.id];
      if (!e) return out(data);
      const look = lookFor(bot, e);
      const key = look.show ? `${look.name}|${look.username ?? ""}` : "";
      const had = sent.get(data.id);
      if (!look.show) {
        if (had) out({ id: data.id, delete: true });
        sent.set(data.id, "");
        return true;
      }
      if (had !== key) {
        if (had) out({ id: data.id, delete: true });
        sent.set(data.id, key);
        out({ id: data.id, name: look.name, pos: e.position, width: e.width, height: e.height, username: look.username,
              ...(e.yaw !== undefined ? { yaw: e.yaw, pitch: e.pitch } : {}) });
        if (data.name) return true;   // a spawn, which that was
      }
      return out(data);
    },
    /** Its metadata changed (made invisible, given a name): drawn again only if it now looks different. */
    changed(e) {
      if (!e || e === bot.entity || !sent.has(e.id)) return;
      const look = lookFor(bot, e);
      if ((look.show ? `${look.name}|${look.username ?? ""}` : "") !== sent.get(e.id)) {
        view.emit("entity", { id: e.id, pos: e.position, yaw: e.yaw, pitch: e.pitch });
      }
    },
  };
  return view;
}

/** Each player's skin, as the server's player list gives it (mineflayer reads the textures property): the texture's
 *  hash, and whether it is the slim model. The bot's own name rides along, for its body seen from above. */
export function skinsOf(bot) {
  const out = { __self: String((bot && bot.username) || "") };
  for (const [name, p] of Object.entries((bot && bot.players) || {})) {
    const url = p && p.skinData && p.skinData.url;
    const m = url && String(url).match(/\/texture\/([0-9a-f]{20,80})$/i);
    if (m) out[name] = { hash: m[1].toLowerCase(), slim: p.skinData.model === "slim" };
  }
  return out;
}

/** Its page as it is, with that one piece redrawn. Says what it did, so a version it no longer fits is noticed
 *  rather than quietly shipping the old names. */
export function pageWithBetterNames(file) {
  let src;
  try {
    src = require("fs").readFileSync(file, "utf8");
  } catch {
    return null;
  }
  const fitted = [], missed = [];
  for (const patch of PAGE_PATCHES) {
    if (src.includes(patch.shipped)) {
      src = src.split(patch.shipped).join(patch.patched);
      fitted.push(patch.name);
    } else {
      missed.push(patch.name);
    }
  }
  if (!fitted.length) {
    tell("view", { names: "as the viewer draws them: its page is not the one this knows" });
    return null;
  }
  // What it could not change stays exactly as the viewer has it: said, so a newer viewer is noticed.
  tell("view", { patched: fitted, ...(missed.length ? { unchanged: missed, note: "its page is not the one this knows" } : {}) });
  return src;
}

// ── The live view ─────────────────────────────────────────────────────────────
/**
 * The viewer's world sent to the page a chunk at a time, with everything else let through between them. It packs
 * five at once (WorldView._loadChunks), each a whole column of a world as JSON, a few hundred kilobytes of work:
 * the bot's one thread stopped for that long, and keys, positions and the physics itself waited behind it, a key
 * taking half a second to show. A newer call (it moved on to another chunk) ends an older one, whose chunks still
 * wanted are in the newer one's list.
 */
export function loadGently(world) {
  world.__lsbGen = 0;
  world._loadChunks = async function (positions) {
    const gen = ++this.__lsbGen;
    for (const p of positions) {
      await new Promise((resolve) => setImmediate(resolve));
      if (this.__lsbGen !== gen) return;
      try { await this.loadChunk(p); } catch { /* not loaded on the bot's side yet: the next pass has it */ }
    }
  };
  return world;
}
/** prismarine-viewer's page and renderer, served from here: what mindcraft's render_bot_view would serve, but on
 *  this computer only, on the port given, under the panel's path, and for each viewer as it asks, its eyes (the
 *  default) or from above ("?view=above" on the page, which its socket's requests carry as their referer). */
function startView(bot) {
  const port = Number(process.env.LSB_VIEW_PORT || 0);
  const prefix = String(process.env.LSB_VIEW_PREFIX || "");
  const distance = Math.max(2, Math.min(12, Number(process.env.LSB_VIEW_DISTANCE || 6) || 6));
  if (!port) return;
  let pv, express, socketIo, http, common;
  try {
    pv = require("prismarine-viewer");
    common = require("prismarine-viewer/lib/common");
    express = require("express");
    socketIo = require("socket.io");
    http = require("http");
  } catch (e) {
    tell("view", { error: `the viewer could not load: ${e?.message || e}` });
    return;
  }
  const shown = require("prismarine-viewer/viewer/lib/version").getVersion(bot.version);
  if (!shown) tell("view", { error: `the view has no pictures for ${bot.version}; version translation shows it` });
  loadPictures(shown);
  try { loadModels(Object.keys(require("prismarine-viewer/viewer/lib/entity/entities.json"))); } catch { /* all drawn */ }
  const app = express();
  const server = http.createServer(app);
  // Only through the panel, which says so on every request it passes on (minecraft_routes.py): the keys and the
  // mouse go over this connection now, and a page of any other site could otherwise open one to it.
  const io = socketIo(server, {
    path: `${prefix}/socket.io`,
    allowRequest: (req, done) => done(null, req.headers["x-lsb-panel"] === "1"),
  });
  // Asked for by the panel's overlay, through the very path the picture comes down (minecraft_routes.py proxies
  // everything under the view), so there is nothing new to open or to let through.
  app.get(`${prefix}/hud`, (req, res) => {
    try {
      res.json(hudOf(bot, { debug: req.query.debug === "1", tab: req.query.tab === "1" }));
    } catch (e) {
      res.json({ ok: false, reason: String((e && e.message) || e) });
    }
  });
  // Played by hand from the panel, and typed into its chat. Only the panel itself: it sends its own header with
  // everything (api.ts), which another site's page cannot add without asking first, and the panel never says yes.
  const fromPanel = (req, res, next) => (req.get("x-llmselfbot")
    ? next() : res.status(403).json({ ok: false, reason: "Only the panel can do that." }));
  const body = express.json({ limit: "32kb" });
  const answer = (job) => async (req, res) => {
    try {
      res.json(await job(req.body || {}));
    } catch (e) {
      res.json({ ok: false, reason: String((e && e.message) || e).slice(0, 200) });
    }
  };
  app.post(`${prefix}/say`, fromPanel, body, answer((b) => sayAs(bot, b)));
  app.post(`${prefix}/drive`, fromPanel, body, answer((b) => (b.on ? takeOver(bot) : letGo(bot))));
  app.post(`${prefix}/input`, fromPanel, body, answer((b) => input(bot, b)));
  app.post(`${prefix}/act`, fromPanel, body, answer((b) => act(bot, b)));
  // Ahead of its own static files, so this one is the one served; everything else is its page untouched.
  const bundle = pageWithBetterNames(require.resolve("prismarine-viewer/public/index.js"));
  if (bundle) {
    app.get(`${prefix}/index.js`, (_req, res) => {
      res.type("application/javascript").send(bundle);
    });
    // The app's own part of the page, and the page loading it after the viewer's bundle. Only with the bundle
    // patched: the script has nothing to hold on to otherwise.
    const script = `(${lsbView.toString()})();`;
    app.get(`${prefix}/lsb_view.js`, (_req, res) => res.type("application/javascript").send(script));
    try {
      const html = require("fs").readFileSync(require.resolve("prismarine-viewer/public/index.html"), "utf8")
        .replace('src="index.js"></script>', 'src="index.js"></script>\n    <script src="lsb_view.js"></script>');
      app.get([`${prefix}/`, `${prefix}/index.html`], (_req, res) => res.type("text/html").send(html));
    } catch { /* the viewer's own page, then, moving as it always did */ }
  }
  // Each player's skin: which, and the picture itself - fetched here and served from the view's own address,
  // because a page may only paint with a picture from its own origin (or one that says it may be).
  app.get(`${prefix}/skins`, (_req, res) => res.json(skinsOf(bot)));
  const skinPictures = new Map();
  app.get(`${prefix}/skin/:file`, async (req, res) => {
    const hash = String(req.params.file || "").replace(/\.png$/i, "").toLowerCase();
    if (!/^[0-9a-f]{20,80}$/.test(hash)) return res.status(400).end();
    try {
      if (!skinPictures.has(hash)) {
        const r = await fetch(`https://textures.minecraft.net/texture/${hash}`);
        if (!r.ok) return res.status(404).end();
        skinPictures.set(hash, Buffer.from(await r.arrayBuffer()));
        if (skinPictures.size > 200) skinPictures.delete(skinPictures.keys().next().value);
      }
      res.type("image/png").set("Cache-Control", "max-age=86400").send(skinPictures.get(hash));
    } catch {
      res.status(502).end();
    }
  });
  common.setupRoutes(app, prefix);
  // Where the camera sits in the view from above: behind the bot and over it, looking back down at it.
  const BACK = 6, UP = 5;
  const LOOK_DOWN = -Math.atan2(UP, BACK);
  io.on("connection", (socket) => {
    const view = { above: /[?&]view=above\b/.test(String(socket.handshake.headers.referer || "")) };
    socket.emit("version", shown || bot.version);
    // What it sends about entities goes through lookFor: the invisible left out, floating text as its words.
    const seen = seenThrough(bot, socket);
    const world = new pv.viewer.WorldView(bot.world, distance, bot.entity.position, seen);
    loadGently(world);
    const looksChanged = (e) => seen.changed(e);
    bot.on("entityUpdate", looksChanged);
    world.init(bot.entity.position);
    // The page places its own camera on the first position it is sent and then leaves it there. Sending that one
    // first settles it; everything after is ours. Only from above, though: a packet with no pitch is what makes
    // the page draw the bot's own body, and in its own eyes that body is exactly where the camera is, so looking
    // through them meant looking at the inside of its own head.
    if (view.above) socket.emit("position", { pos: bot.entity.position, yaw: bot.entity.yaw, addMesh: true });
    // The hands, as they happen: keys, the mouse, one thing done. The same as the routes above, without a web
    // request each through the panel.
    socket.on("lsb:input", (b) => { try { input(bot, b || {}); } catch { /* the next one carries the same */ } });
    socket.on("lsb:act", async (b, reply) => {
      let r;
      try { r = await act(bot, b || {}); } catch (e) { r = { ok: false, reason: String((e && e.message) || e).slice(0, 200) }; }
      if (typeof reply === "function") reply(r);
    });
    // Its eyes, or from above, switched in place: the world it already has stays loaded.
    socket.on("lsb:view", (b) => {
      view.above = !!(b && b.above);
      if (view.above) socket.emit("position", { pos: bot.entity.position, yaw: bot.entity.yaw, addMesh: true });
    });
    let lastChunks = 0, lastDraw = 0;
    const draw = () => {
      lastDraw = Date.now();
      const pos = bot.entity.position;
      const yaw = bot.entity.yaw;
      if (view.above) {
        // A camera that follows, rather than one left where the bot spawned: that one was soon a long way off,
        // and underground as often as not, which is what "the camera goes into blocks" was. The page moves its
        // camera only when it is sent a pitch, so the shot is sent as one packet and the bot's own body as
        // another, which keeps it drawn and moving.
        socket.emit("position", {
          pos: { x: pos.x + Math.sin(yaw) * BACK, y: pos.y + UP, z: pos.z + Math.cos(yaw) * BACK },
          yaw, pitch: LOOK_DOWN,
        });
        socket.emit("position", { pos, yaw, addMesh: true });
      } else {
        socket.emit("position", { pos, yaw, pitch: bot.entity.pitch });
      }
      // The world itself is only re-centred now and then: it loads and builds chunks, which is work.
      const now = Date.now();
      if (now - lastChunks > 250) {
        lastChunks = now;
        world.updatePosition(pos);
      }
    };
    // Every physics tick, straight after it has moved the bot: twenty a second, and never a tick behind (a timer of
    // its own ran out of step with the physics, which put up to one more tick between a key and the picture). The
    // page glides between them, so sending them steadily is what turns a slideshow into movement. A slow timer
    // stands in should the ticks ever stop (dead, between worlds).
    bot.on("physicsTick", draw);
    const fallback = setInterval(() => { if (Date.now() - lastDraw > 250) draw(); }, 250);
    world.listenToBot(bot);
    socket.on("disconnect", () => {
      bot.removeListener("physicsTick", draw);
      clearInterval(fallback);
      bot.removeListener("entityUpdate", looksChanged);
      world.removeListenersFromBot(bot);
      world.__lsbGen = -1;
    });
  });
  server.on("error", (e) => tell("view", { error: String(e?.message || e) }));
  server.listen(port, "127.0.0.1", () => tell("view", { port, prefix, version: shown || bot.version }));
  bot.once("end", () => {
    driving.on = false;
    clearInterval(driving.timer);
    try { io.close(); } catch { /* gone */ }
    try { server.close(); } catch { /* gone */ }
  });
}

// ── Every bot mindcraft makes ─────────────────────────────────────────────────
function attach(bot) {
  bot.on("resourcePack", () => {
    try { bot.acceptResourcePack(); } catch { /* an older protocol with none */ }
  });
  signInOn(bot, process.env.LSB_SERVER_PASSWORD || "");
  // Every line as a player would read it, the server's own formatting and all ("<Steve> hi", "Steve joined"), and
  // the line over the hotbar kept apart from them.
  bot.on("messagestr", (text, position) => (position === "game_info" ? heardOverHotbar(text) : remember(text)));
  followScreen(bot);
  playersOnly(bot);
  // Ahead of mindcraft's own "login" listener, which sends the skin command (bot.chat is there by then).
  bot.on("login", () => {
    noSkinClear(bot);
    playLikeTheGame(bot);
    traceNet(bot);
  });
  bot.once("spawn", () => {
    // Its real name in the game, which on a Microsoft account is Microsoft's and need not be the one the account
    // was added under: the card shows this one.
    tell("spawned", { version: bot.version, name: String(bot.username || "") });
    try { startView(bot); } catch (e) { tell("view", { error: String(e?.message || e) }); }
    // Its AI taught the server's menus, once mindcraft has its agent (it does by the time the bot is in a world;
    // asked again a little later should it not).
    let tries = 0;
    const teach = async () => {
      const agent = await agentOf(bot);
      if (agent) await teachMenus(bot, agent);
      else if (++tries < 5) setTimeout(teach, 3000);
    };
    teach().catch(() => {});
  });
  // A menu a server opened, in the log: what it was called and how big.
  bot.on("windowOpen", (w) => {
    try { tell("menu", { title: bare(plain(w.title)).slice(0, 80), slots: Number(w.inventoryStart || 0) }); } catch { /* fine */ }
  });
  // With the last things it sent, so a kick for something it did says what that was.
  bot.on("kicked", (reason) => tell("kicked", { reason: plain(reason).slice(0, 300), recent: netOf().sent.slice(0, 6) }));
}

let mineflayer = null;
try { mineflayer = require("mineflayer"); } catch { /* not mindcraft's folder: nothing to do */ }
if (mineflayer && !mineflayer.createBot.__lsb) {
  const original = mineflayer.createBot;
  const wrapped = function createBot(options) {
    const bot = original.call(this, throughProxy(options));
    try { attach(bot); } catch (e) { tell("hook_error", { error: String(e?.message || e) }); }
    return bot;
  };
  wrapped.__lsb = true;
  mineflayer.createBot = wrapped;
}
// mindcraft's look at the server before it joins goes the same way, or the server would see this computer's address first.
let protocol = null;
try { protocol = require("minecraft-protocol"); } catch { /* not mindcraft's folder: nothing to do */ }
if (protocol && !protocol.ping.__lsb) {
  const original = protocol.ping;
  const wrapped = function ping(options, cb) { return original.call(this, throughProxy(options), cb); };
  wrapped.__lsb = true;
  protocol.ping = wrapped;
}
