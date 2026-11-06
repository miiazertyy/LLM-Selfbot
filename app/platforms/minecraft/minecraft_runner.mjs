/**
 * Minecraft's runner: starts mindcraft-ce and speaks for it to the app.
 *
 *   the bridge (snapchat_bridge.py)  <- wake socket, ipc/mc_state.json ->  this runner
 *   this runner  -> node main.js, SETTINGS_JSON ->  mindcraft, and its MindServer (Socket.IO, a control token)
 *
 * mindcraft plays: it walks, mines and builds, and asks the app's brain (brain.py, served by the bridge) what to
 * say and do. This starts it, watches it, and passes on what the panel asks for:
 *   - its state, for the account's card: starting, joining, a Microsoft code to type, in the world, not let in;
 *   - what it is doing right now (the MindServer's state updates), for the panel and Telegram;
 *   - the panel's requests: a line to say (by its id: brain.say), leave the world, come back.
 *
 * Synced beside mindcraft (DATA_DIR/mindcraft/llmselfbot/) so Node finds mindcraft's node_modules from here. It is
 * started with none of the app's secrets in its environment (worker.runner_env), and starts mindcraft the same way.
 */
import { spawn, spawnSync } from "child_process";
import fs from "fs";
import net from "net";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";
import { io } from "socket.io-client";
import { createCore, delay, writeJson } from "./runner_core.mjs";
import { throughProxy } from "./proxy_connect.mjs";

const ACCOUNT = Math.max(1, parseInt(process.env.MINECRAFT_ACCOUNT_INDEX || "1", 10) || 1);
const DATA_DIR = process.env.MC_DATA_DIR || "";
const MC_DIR = process.env.MC_MINDCRAFT_DIR || "";
const BRAIN = process.env.MC_BRAIN_URL || "";
const NAME = process.env.MC_AGENT_NAME || "";
const CONTROL_TOKEN = process.env.MC_CONTROL_TOKEN || "";
const SERVER = process.env.MC_SERVER || "";
let SETTINGS = {};
try { SETTINGS = JSON.parse(process.env.MC_SETTINGS_JSON || "{}"); } catch { SETTINGS = {}; }
const TAG = "[Minecraft]";
const say = (s) => console.log(`${TAG} ${s}`);
// The password it signs in with on this server, where the server asks in the chat (agent_hooks.mjs): handed to the
// bot's own process only, never printed, never to mindcraft's settings or a model.
const PASSWORD = process.env.MC_SERVER_PASSWORD || "";
// Where the panel serves its live view (minecraft_routes.py), and how far it shows.
const VIEW_PREFIX = `/api/minecraft/minecraft_${ACCOUNT}/view`;
const VIEW_DISTANCE = String(process.env.MC_VIEW_DISTANCE || "6");
const VIEW_FILE = path.join(DATA_DIR, "ipc", `mc_view${ACCOUNT === 1 ? "" : `_${ACCOUNT}`}.json`);
// Version translation (ViaProxy), when this server needs it: { java, jar, dir, target, version }.
let VIAPROXY = null;
try { VIAPROXY = JSON.parse(process.env.MC_VIAPROXY || "null"); } catch { VIAPROXY = null; }
const HOOKS = path.join(path.dirname(fileURLToPath(import.meta.url)), "agent_hooks.mjs");
const MARK = "\u001eLSB ";

const core = createCore({ prefix: "mc", env: "MINECRAFT", account: ACCOUNT, dataDir: DATA_DIR, tag: TAG });

// Settings mindcraft reads from the environment on its own (main.js); SETTINGS_JSON is applied after them and
// carries every one of them anyway, so they are dropped rather than left to disagree.
const MINDCRAFT_OWN_ENV = ["MINECRAFT_PORT", "MINDSERVER_PORT", "PROFILES", "INSECURE_CODING", "BLOCKED_ACTIONS",
  "MAX_MESSAGES", "NUM_EXAMPLES", "LOG_ALL", "SETTINGS_JSON"];

/** A line of mindcraft's, safe for the log: the brain's address carries a token in its path. */
const redact = (line) => line.replace(/\/v1\/[A-Za-z0-9_-]{16,}/g, "/v1/…");

/** A port nothing is listening on, for the MindServer: mindcraft names the port it was given, not the one it got. */
function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.unref();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

/** Whether the brain answers: mindcraft is only started once it does, so its first question is never refused. */
async function waitForBrain(ms = 60000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try {
      const r = await fetch(`${BRAIN}/models`, { signal: AbortSignal.timeout(3000) });
      if (r.ok) return true;
    } catch { /* not up yet */ }
    await delay(500);
  }
  return false;
}

// ── What it is doing ────────────────────────────────────────────────────────
let child = null;
let control = null;
let inGame = false;
let latest = null;                 // the MindServer's last full state of it
let lastReason = "";
let retryAt = 0, retries = 0;
const RETRY_S = [20, 45, 90, 180, 300];
// Whether the version it plays was chosen here (start), and a stack being left out (onLine).
let chose = false, quietStack = false;
// Whether it got into the world since it last set out to join (onLine).
let spawnedThisTry = false;

function identity(inGame = "") {
  // Who it is in the game, for its card (status_routes._web_identity), as the other runners record theirs. The name
  // the bot itself reports, once it is in, beats the one it was added under: on a Microsoft account the two can
  // differ, and the card used to show whatever was typed. Without one yet, what is already there is kept.
  try {
    const file = path.join(DATA_DIR, "config", `identity_minecraft_${ACCOUNT}.json`);
    // What the bridge kept there stays: its picture, the skin drawn in 3D (skins.py).
    let was = {};
    try { was = JSON.parse(fs.readFileSync(file, "utf-8")) || {}; } catch { /* none yet */ }
    const real = String(inGame || "").trim() || was.in_game || "";
    const shown = real || NAME;
    writeJson(file, { ...was, username: shown, display_name: shown, ...(real ? { in_game: real } : {}),
                      login: NAME, server: SERVER, at: Date.now() / 1000 });
  } catch { /* the card shows the name it was added as */ }
}

// mindcraft's lines that say nothing to anyone reading the log, or say again what the line before said: every
// message is printed twice ("Alicia received message from" and "received message from"), every reply twice ("full
// response" and "Generated response"), and an object it logs comes out a field to a line. The log the panel shows
// is shared by every account, and a goal being worked at fills it in minutes with these.
const NOISE = /^(?:received message from |Generated response: |Client connected$|\s+[\w$]+: .*,?$|[{}[\]],?$)/;

/** What the app's part in the bot says (agent_hooks.mjs): the live view up, signing in on the server, kicked. */
function onHook(msg) {
  if (msg.event === "view") {
    if (msg.error) say(`The live view: ${msg.error}`);
    try {
      writeJson(VIEW_FILE, { port: msg.port || 0, prefix: msg.prefix || VIEW_PREFIX, version: msg.version || "",
                             error: msg.error || "", at: Date.now() / 1000 });
    } catch { /* the panel says there is nothing to watch */ }
  } else if (msg.event === "auth") {
    if (msg.step === "server") {
      say(`The server: ${redact(String(msg.text || ""))}`);
      return;
    }
    const said = { register: "Registering on the server", login: "Signing in on the server",
                   "signed-in": "Signed in on the server" };
    if (msg.step === "refused") {
      core.setState("needs-you", "The server says its password is wrong: this name was registered there with another "
        + "one. Change its name, or ask the server's staff to reset it.");
    } else if (msg.step === "needs-email") {
      core.setState("needs-you", "The server wants an email to register, which it does not have. Register it there "
        + "yourself, once.");
    } else {
      say(said[msg.step] || msg.step);
    }
    core.tellPython({ kind: "mc_event", event: "auth", step: msg.step });
  } else if (msg.event === "kicked") {
    lastReason = `Kicked: ${msg.reason || "no reason given"}`;
    // What it last sent, newest first: the clue when it was kicked for something it did.
    say(Array.isArray(msg.recent) && msg.recent.length ? `${lastReason} (it had just sent: ${msg.recent.join(", ")})` : lastReason);
    // The bridge takes it home from a server other than its own that will not have it.
    core.tellPython({ kind: "mc_event", event: "kicked", reason: msg.reason || "" });
  } else if (msg.event === "spawned") {
    say(`In the world, on ${msg.version}`);
    // The name it really plays as, which on a Microsoft account is Microsoft's: on its card from now on, and its
    // picture drawn from that player's skin (not from whoever owns the name it was added under).
    if (msg.name) {
      identity(msg.name);
      core.tellPython({ kind: "mc_event", event: "spawned", name: String(msg.name) });
    }
  } else if (msg.event === "menu") {
    // A server's menu on its screen (a chest of buttons, a real chest): what it is called, for the log.
    say(`A menu opened: ${msg.title || "untitled"}${msg.slots ? ` (${msg.slots} slots)` : ""}`);
  } else if (msg.event === "driving") {
    // Its owner playing it by hand from the panel's view, and mindcraft paused meanwhile.
    if (msg.on) say(msg.mind === "paused" ? "You took control. Its AI is paused." : "You took control.");
    else say(msg.why === "no word from the panel"
      ? "No word from the panel for a while, so it plays by itself again." : "You let go. It plays by itself again.");
  } else if (msg.event === "hook_error") {
    say(`The app's part of the bot failed: ${msg.error}`);
  }
}

function onLine(raw) {
  if (raw.startsWith(MARK)) {
    let msg = null;
    try { msg = JSON.parse(raw.slice(MARK.length)); } catch { return; }
    if (msg && typeof msg === "object") onHook(msg);
    return;
  }
  const line = redact(raw);
  if (!line.trim()) return;
  // Where the version was chosen here (ViaProxy between, or a range around 1.21.4), mindcraft's own ping takes the
  // first version the server names and says the one it was given is wrong, stack and all: it is not, the line
  // before says which one it plays.
  if (quietStack && /^\s+at /.test(line)) return;
  quietStack = false;
  // (Nor that its ping got no answer: the runner's own did, a moment before.)
  const expected = chose && /^(?:Modded server found|Timeout pinging server|Error pinging server|Error getting server:|Attempting to connect anyway)/.test(line);
  if (expected) quietStack = true;
  if (!NOISE.test(line) && !expected) console.log(`[mindcraft] ${line}`);
  // A Microsoft sign-in, the first time on a real server: prismarine-auth prints Microsoft's own device-code line.
  const code = line.match(/\b(?:enter|use) the code ([A-Z0-9-]{6,12})\b/i);
  if (code && /microsoft\.com/i.test(line)) {
    core.setState("needs-you", `Sign in at microsoft.com/link with the code ${code[1]}`);
    return;
  }
  if (line.includes(`${NAME} logging into minecraft`)) {
    spawnedThisTry = false;
    core.setState("logging-in", `Joining ${SERVER}`);
  } else if (line.includes(`${NAME} spawned.`)) {
    inGame = true;
    spawnedThisTry = true;
    retries = 0;
    retryAt = 0;
    lastReason = "";
    identity();
    core.setState("ready");
    core.tellPython({ kind: "mc_event", event: "in_world" });
  } else if (line.includes("[LoginGuard]")) {
    // mindcraft's own reading of why it was let go: a name in use, not whitelisted, the server full or down.
    lastReason = line.slice(line.indexOf("[LoginGuard]") + 12).trim();
  } else if (/Bot has not spawned after \d+ seconds/.test(line)) {
    lastReason = "The server did not let it in in time";
  } else if (line.includes("exited too quickly and will not be restarted")) {
    // mindcraft gives up on an agent that falls over within ten seconds (the server is down, the name taken): it
    // is tried again from here, less and less often.
    inGame = false;
    const wait = RETRY_S[Math.min(retries, RETRY_S.length - 1)];
    retries += 1;
    retryAt = Date.now() + wait * 1000;
    core.setState("logged-out", `${lastReason || `Could not join ${SERVER}`}. It tries again in ${wait} s.`);
    core.tellPython({ kind: "mc_event", event: "join_failed", reason: lastReason || "" });
  } else if (line.includes("Restarting agent")) {
    inGame = false;
    // Not in the world once since it last tried (it never spawned, in time): not let in, as above.
    if (!spawnedThisTry) core.tellPython({ kind: "mc_event", event: "join_failed", reason: lastReason || "" });
    core.setState("logging-in", `Joining ${SERVER} again`);
  } else if (line.startsWith("Agent died:")) {
    core.tellPython({ kind: "mc_event", event: "died", text: line.slice(11).trim() });
  }
}

function pipeLines(stream) {
  let buf = "";
  stream.on("data", (chunk) => {
    buf += chunk.toString("utf-8");
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      onLine(buf.slice(0, i).replace(/\r$/, ""));
      buf = buf.slice(i + 1);
    }
  });
}

/** "go to player" for mindcraft's "action:goToPlayer", "self defense" for "mode:self_defense". */
const doingWords = (label) => String(label || "Idle").replace(/^(action|mode):/, "")
  .replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ").toLowerCase();

let gameKey = "", gameAt = 0;
/** What it is doing in the game, in its state file for its card: written when it changes, and every half minute. */
function reportGame(s) {
  const play = s.gameplay || {};
  const pos = play.position || {};
  const game = {
    doing: doingWords(s.action?.current), health: play.health ?? null, hunger: play.hunger ?? null,
    players: (s.nearby?.humanPlayers || []).filter(Boolean).slice(0, 8), biome: String(play.biome || "").replace(/_/g, " "),
    time: play.timeLabel || "", pos: [Math.round(pos.x || 0), Math.round(pos.y || 0), Math.round(pos.z || 0)],
    server: SERVER,
  };
  const key = JSON.stringify([game.doing, game.health, game.hunger, game.players]);
  if (key === gameKey && Date.now() - gameAt < 30000) return;
  gameKey = key;
  gameAt = Date.now();
  if (inGame) core.setState("ready", "", { game });
}

function connectControl(port) {
  control = io(`http://127.0.0.1:${port}`, {
    auth: { controlToken: CONTROL_TOKEN }, reconnection: true, reconnectionDelay: 1000, reconnectionDelayMax: 5000,
  });
  control.on("connect", () => control.emit("listen-to-agents"));
  control.on("agents-status", (agents) => {
    const me = (agents || []).find((a) => a && a.name === NAME);
    const was = inGame;
    inGame = !!(me && me.in_game);
    if (inGame && !was) core.setState("ready");
  });
  control.on("state-update", (states) => {
    const s = states && states[NAME];
    if (s && !s.error) {
      latest = s;
      reportGame(s);
    }
  });
  control.on("control-error", (e) => say(`The MindServer refused a request: ${e?.error || "unauthorized"}`));
}

/** Whether something listens on this port on this computer yet. */
function portOpen(port) {
  return new Promise((resolve) => {
    const s = net.createConnection({ host: "127.0.0.1", port }, () => { s.destroy(); resolve(true); });
    s.on("error", () => resolve(false));
    s.setTimeout(1500, () => { s.destroy(); resolve(false); });
  });
}

// ViaProxy's lines worth a log line: its errors, and a player kicked or cut off, colours taken out. Not its
// warnings: a single join on an older server brought a hundred of "No light data found for chunk", all harmless.
const VIA_SHOWN = /\bERROR\b|Exception|Caused by|kick|disconnect/i;
let via = null;

/** ViaProxy between the bot and the server: the bot speaks the version mindcraft knows best, and ViaProxy the
 *  server's, whichever it is. On this computer only, offline sign-in (a server with online mode needs ViaProxy's
 *  own account, so those are joined directly). True once it listens. */
async function startViaProxy(port) {
  const args = ["-jar", VIAPROXY.jar, "cli", "--bind-address", `127.0.0.1:${port}`, "--target-address", VIAPROXY.target,
                ...(process.env.MC_PROXY ? ["--backend-proxy-url", process.env.MC_PROXY] : []),
                "--auth-method", "NONE", "--log-ips", "false"];
  try { fs.mkdirSync(VIAPROXY.dir, { recursive: true }); } catch { /* it says so below */ }
  via = spawn(VIAPROXY.java, args, { cwd: VIAPROXY.dir, stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
                                      detached: process.platform !== "win32" });
  const shown = (stream) => {
    let buf = "";
    stream.on("data", (chunk) => {
      buf += chunk.toString("utf-8");
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).replace(/\u001b\[[0-9;]*m/g, "").trim();
        buf = buf.slice(i + 1);
        if (line && VIA_SHOWN.test(line) && !/outdated Java|no longer officially supports|releases\/tag/i.test(line)) {
          console.log(`[ViaProxy] ${line.slice(0, 300)}`);
        }
      }
    });
  };
  shown(via.stdout);
  shown(via.stderr);
  via.on("error", (e) => say(`ViaProxy could not start: ${e.message}`));
  via.on("exit", (code) => {
    if (stopping) return;
    say(`ViaProxy stopped (${code}).`);
    core.setState("logged-out", "Version translation stopped. It restarts.");
    process.exit(3);
  });
  for (let i = 0; i < 90; i++) {
    if (await portOpen(port)) return true;
    if (via.exitCode !== null) return false;
    await delay(500);
  }
  return false;
}

/** The versions a server says it runs, from its own answer to a ping ("Paper 1.21.4", "Requires MC 1.8 / 1.21",
 *  "Velocity 3.3 (1.7.2-1.21.4)"); [] when it does not answer. */
async function serverVersions(target) {
  const [host, port] = target.split(/:(?=\d+$)/);
  try {
    const mc = (await import("minecraft-protocol")).default;
    const res = await new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error("no answer")), 8000);
      mc.ping(throughProxy({ host, port: Number(port) || 25565 }), (err, r) => { clearTimeout(t); err ? reject(err) : resolve(r); });
    });
    return String(res?.version?.name || "").match(/\d+\.\d+(?:\.\d+)?/g) || [];
  } catch {
    return [];
  }
}

// The version mindcraft and the live view know best.
const BEST = [1, 21, 4];
const vparts = (v) => {
  const p = String(v).split(".").map((x) => parseInt(x, 10) || 0);
  // "1.21" on its own, as a network says it, is every 1.21.
  return [p[0] || 0, p[1] || 0, p.length > 2 ? p[2] : 99];
};
const vcmp = (x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2];

/** Whether a server takes 1.21.4, from the versions its ping names: one of them is a 1.21, or they are the ends of
 *  a range around it ("Velocity 1.7.2-26.3", "Requires MC 1.8 / 1.21"). */
function takesBest(versions) {
  if (versions.some((v) => /^1\.21(?:\.|$)/.test(v))) return true;
  if (versions.length < 2) return false;
  const parts = versions.map(vparts);
  const lo = parts.reduce((a, b) => (vcmp(a, b) <= 0 ? a : b));
  const hi = parts.reduce((a, b) => (vcmp(a, b) >= 0 ? a : b));
  return vcmp(lo, BEST) <= 0 && vcmp(BEST, hi) <= 0;
}

/** Whether to go through ViaProxy for this server: always when told so; on "auto", only for a server that does not
 *  take 1.21.4 (one that does not answer is joined directly: translating changes nothing about a server that is
 *  down). */
function wantViaProxy(versions) {
  if (!VIAPROXY) return false;
  if (VIAPROXY.mode === "always") return true;
  if (!versions.length || takesBest(versions)) return false;
  say(`${VIAPROXY.target} runs ${versions.join(" / ")}: joining through ViaProxy.`);
  return true;
}

async function start() {
  core.setState("starting", "Starting mindcraft");
  if (!NAME || !MC_DIR || !BRAIN || !fs.existsSync(path.join(MC_DIR, "main.js"))) {
    core.setState("needs-you", "Minecraft support is not installed. Install it in Settings, Minecraft.");
    await delay(5000);
    process.exit(3);
  }
  if (!(await waitForBrain())) {
    core.setState("logged-out", "Its brain did not start. It restarts.");
    process.exit(3);
  }
  const port = await freePort();
  const viewPort = await freePort();
  let settings = { ...SETTINGS, mindserver_port: port };
  // What the server says it runs, asked once: whether to translate, and which version to play. mindcraft's own
  // "auto" takes the first version a server names, so jartex.fun ("Velocity 1.7.2-26.3", every version between)
  // was joined as 1.7.2, older than anything the bot speaks; a server naming a range around 1.21.4 is played at it.
  const auto = String(SETTINGS.minecraft_version || "auto") === "auto";
  const versions = VIAPROXY || auto ? await serverVersions(VIAPROXY ? VIAPROXY.target : `${SETTINGS.host}:${SETTINGS.port}`) : [];
  const translate = wantViaProxy(versions);
  if (!translate && auto && versions.length > 1 && takesBest(versions)) {
    settings = { ...settings, minecraft_version: BEST.join(".") };
    chose = true;
    say(`${SETTINGS.host} takes ${versions.join(" to ")}: it plays ${BEST.join(".")}.`);
  }
  if (translate) {
    core.setState("starting", "Starting version translation");
    const vpPort = await freePort();
    if (await startViaProxy(vpPort)) {
      settings = { ...settings, host: "127.0.0.1", port: vpPort, minecraft_version: VIAPROXY.version || "1.21.4" };
      chose = true;
      say(`Through ViaProxy: it plays ${settings.minecraft_version}, ${VIAPROXY.target} gets its own version.`);
    } else {
      say("Version translation did not start; joining directly.");
    }
  }
  try { writeJson(VIEW_FILE, { port: 0, prefix: VIEW_PREFIX, at: Date.now() / 1000 }); } catch { /* none yet */ }
  const env = { ...process.env };
  for (const k of Object.keys(env)) {
    if (k.startsWith("MC_") || k.startsWith("LSB_") || MINDCRAFT_OWN_ENV.includes(k)) delete env[k];
  }
  env.SETTINGS_JSON = JSON.stringify(settings);
  env.MINDCRAFT_BIND_HOST = "127.0.0.1";
  env.MINDCRAFT_CONTROL_TOKEN = CONTROL_TOKEN;
  // The app's own part of the bot (agent_hooks.mjs), loaded before mindcraft in each of its processes.
  env.NODE_OPTIONS = `--import=${pathToFileURL(HOOKS).href}`;
  env.LSB_MC_DIR = MC_DIR;
  env.LSB_VIEW_PORT = String(viewPort);
  env.LSB_VIEW_PREFIX = VIEW_PREFIX;
  env.LSB_VIEW_DISTANCE = VIEW_DISTANCE;
  if (PASSWORD) env.LSB_SERVER_PASSWORD = PASSWORD;
  child = spawn(process.execPath, ["main.js"], {
    cwd: MC_DIR, env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
    // Its own process group, so the agent process it starts goes when it does (on Windows the bridge's taskkill /T
    // takes the whole tree, and a detached child would get a console window of its own).
    detached: process.platform !== "win32",
  });
  pipeLines(child.stdout);
  pipeLines(child.stderr);
  child.on("exit", (code, signal) => {
    if (stopping) return;
    say(`mindcraft stopped (${signal || code}).`);
    killTree(via);
    core.setState("logged-out", lastReason ? `${lastReason}. It restarts.` : "mindcraft stopped. It restarts.");
    process.exit(3);
  });
  say(`mindcraft started for ${NAME}, joining ${SERVER} (account #${ACCOUNT})`);
  connectControl(port);
}

// ── The panel's requests ─────────────────────────────────────────────────────
async function handle(req) {
  const op = req.op;
  if (op === "state") return { ok: true, in_game: inGame, state: latest, reason: lastReason };
  if (op === "history") return { ok: false, reason: "Kept by the app" };
  if (!control || !control.connected) return { ok: false, reason: "mindcraft is still starting" };
  if (op === "say" || op === "tell") {
    if (!inGame) return { ok: false, reason: "It is not in the world right now" };
    const from = String(req.from || "system");
    // "say": the id of a line the brain holds (brain.say), answered word for word when mindcraft asks for it.
    // "tell": words for it to take as from that player (a goal, "come here"), answered by the persona.
    const message = op === "say" ? `[[LSB:SAY:${String(req.sid || "")}]]` : String(req.text || "").slice(0, 500);
    control.emit("send-message", NAME, { from, message });
    return { ok: true };
  }
  if (op === "leave") {
    control.emit("stop-agent", NAME);
    inGame = false;
    retryAt = 0;
    core.setState("logged-out", "It left the world. Start it again from its card, or ask it to come back.");
    return { ok: true };
  }
  if (op === "join") {
    control.emit("start-agent", NAME);
    core.setState("logging-in", `Joining ${SERVER}`);
    return { ok: true };
  }
  return { ok: false, reason: `Not something Minecraft does: ${op}` };
}

async function loop() {
  const parent = process.ppid;
  for (;;) {
    await core.sleepOrPoke(1000);
    while (core.panelQueue.length) {
      const req = core.panelQueue.shift();
      let res;
      try { res = await handle(req); } catch (e) { res = { ok: false, reason: String(e?.message || e) }; }
      core.tellPython({ kind: "panel_result", id: req.id, ...res });
    }
    if (retryAt && Date.now() >= retryAt && control?.connected) {
      retryAt = 0;
      control.emit("start-agent", NAME);
      core.setState("logging-in", `Joining ${SERVER} again`);
    }
    core.heartbeatState();
    // The bridge gone without a word (killed outright): nothing would ever stop mindcraft, so this does.
    let alive = process.ppid === parent;
    try { process.kill(parent, 0); } catch { alive = false; }
    if (!alive) shutdown("the bridge is gone");
  }
}

/** A child and everything it started. */
function killTree(proc) {
  try {
    if (proc && proc.exitCode === null) {
      if (process.platform === "win32") {
        spawnSync("taskkill", ["/F", "/T", "/PID", String(proc.pid)], { windowsHide: true });
      } else {
        process.kill(-proc.pid, "SIGTERM");
      }
    }
  } catch { /* already gone */ }
}

let stopping = false;
function shutdown(why) {
  if (stopping) return;
  stopping = true;
  say(`Stopping mindcraft: ${why}`);
  killTree(child);
  killTree(via);
  setTimeout(() => process.exit(0), 300);
}
process.on("SIGTERM", () => shutdown("asked to stop"));
process.on("SIGINT", () => shutdown("asked to stop"));

core.connectWake();
start().catch((e) => {
  say(`Could not start mindcraft: ${e?.message || e}`);
  core.setState("logged-out", "mindcraft could not start. It restarts.");
  process.exit(3);
});
loop();
