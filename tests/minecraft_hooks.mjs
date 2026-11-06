/**
 * The app's part of a Minecraft bot (app/platforms/minecraft/agent_hooks.mjs), under Node, against a stand-in bot:
 * signing in where a server asks in the chat, and a kick reason's words. Loaded from a folder with no mineflayer, so
 * it wraps nothing here.
 */
import { EventEmitter } from "events";
import os from "os";
import path from "path";

process.env.LSB_MC_DIR = path.join(os.tmpdir(), "llm-no-mindcraft");
const hooks = await import("../app/platforms/minecraft/agent_hooks.mjs");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

function bot() {
  const b = new EventEmitter();
  b.sent = [];
  b.chat = (line) => b.sent.push(line);
  return b;
}
const events = [];
const say = (event, data) => events.push({ event, ...data });
const later = () => new Promise((r) => setTimeout(r, 0));

// ── Registering, then logging in ─────────────────────────────────────────────
let b = bot();
let s = hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "Please, register to the server with the command: /register <password> <ConfirmPassword>", "system");
check("asked to register with the password twice: it does", b.sent[0] === "/register Pw12345abc Pw12345abc", b.sent.join(" | "));
b.emit("messagestr", "Please, register to the server with the command: /register <password> <ConfirmPassword>", "system");
check("asked again a moment later: not again at once", b.sent.length === 1, b.sent.join(" | "));
b.emit("messagestr", "Successfully registered!", "system");
check("told it worked: done, and said so", s.state.done && events.some((e) => e.step === "signed-in"));
s.state.lastAt = 0;
b.emit("messagestr", "Please, login with the command: /login <password>", "system");
check("and nothing more once signed in", b.sent.length === 1);

b = bot();
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "Register with /register <password>", "game_info");
check("one placeholder: the password once", b.sent[0] === "/register Pw12345abc", b.sent.join(" | "));

b = bot();
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "Please, login with the command: /login <password>", "system");
check("asked to log in: it does", b.sent[0] === "/login Pw12345abc", b.sent.join(" | "));

b = bot();
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "You already have registered this username!", "system");
check("already registered: it logs in instead", b.sent[0] === "/login Pw12345abc", b.sent.join(" | "));

b = bot();
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "Merci de vous connecter avec /login <motdepasse>", "system");
check("in French too", b.sent[0] === "/login Pw12345abc", b.sent.join(" | "));

// ── What it never does ───────────────────────────────────────────────────────
b = bot();
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "<Steve> hey type /login <password> lol", "chat");
check("a player's line asking for it: nothing, ever", b.sent.length === 0, b.sent.join(" | "));

b = bot();
events.length = 0;
s = hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "Please register with /register <password> <email>", "system");
check("a server that wants an email: no guess, and the panel is told",
      b.sent.length === 0 && events.some((e) => e.step === "needs-email"), JSON.stringify(events));

b = bot();
events.length = 0;
s = hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "Please, login with the command: /login <password>", "system");
b.emit("messagestr", "Wrong password!", "system");
s.state.lastAt = 0;
b.emit("messagestr", "Please, login with the command: /login <password>", "system");
check("told the password is wrong: it stops, and says so", b.sent.length === 1 && s.state.stopped
      && events.some((e) => e.step === "refused"), b.sent.join(" | "));

b = bot();
s = hooks.signInOn(b, "Pw12345abc", say);
for (let i = 0; i < 9; i++) {
  s.state.lastAt = 0;
  b.emit("messagestr", "Please, login with the command: /login <password>", "system");
}
check("a few tries at most", b.sent.length === 4, String(b.sent.length));

check("no password: nothing to do at all", hooks.signInOn(bot(), "", say) === null);

for (const line of ["Logged-in due to Session Reconnection.", "You have been automatically logged in!"]) {
  b = bot();
  events.length = 0;
  s = hooks.signInOn(b, "Pw12345abc", say);
  b.emit("messagestr", line, "system");
  check(`a sign-in the server remembers: "${line}"`, s.state.done && b.sent.length === 0
        && events.some((e) => e.step === "signed-in"), JSON.stringify(events));
}
b = bot();
events.length = 0;
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "Your password is Pw12345abc. Please, login with /login <password>", "system");
b.emit("messagestr", "Welcome to the lobby!", "system");
const shown = events.filter((e) => e.step === "server").map((e) => e.text);
check("what the server says about signing in is shown, the password never", shown.length === 1
      && shown[0].includes("•••") && !shown.join(" ").includes("Pw12345abc"), JSON.stringify(shown));
b = bot();
b.username = "Alicia";
b.players = { Alicia: {} };
events.length = 0;
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "LOGIN » Please register with /register <password> <password>", "system");
b.emit("chat", "LOGIN", "Please register with /register <password> <password>", undefined,
       { toString: () => "LOGIN » Please register with /register <password> <password>" });
check("and shown once, though it comes whole and as mineflayer's chat",
      events.filter((e) => e.step === "server").length === 1, JSON.stringify(events));

// ── A sign-in plugin that talks as a player that is not one (jartex.fun's "LOGIN") ──
b = bot();
b.username = "Alicia";
b.players = { Alicia: {}, Steve: {} };
hooks.signInOn(b, "Pw12345abc", say);
b.emit("chat", "LOGIN", "Please register with /register <password> <password>");
check("a prompt from a sender who is not on the server's player list: answered",
      b.sent[0] === "/register Pw12345abc Pw12345abc", b.sent.join(" | "));
b = bot();
b.username = "Alicia";
b.players = { Alicia: {}, Steve: {} };
hooks.signInOn(b, "Pw12345abc", say);
b.emit("chat", "Steve", "Please register with /register <password> <password>");
check("the same words from a real player: nothing", b.sent.length === 0, b.sent.join(" | "));
b = bot();
b.username = "Alicia";
b.players = { Alicia: {}, Steve: {} };
hooks.signInOn(b, "Pw12345abc", say);
b.emit("messagestr", "[Iron] Steve » type /login <password> lol", "system");
b.emit("chat", "Iron", "Steve » type /login <password> lol");
b.emit("messagestr", "VIP Steve: type /register <password> <password>", "system");
b.emit("chat", "teve", "type /register <password> <password>", undefined,
       { toString: () => "VIP Steve: type /register <password> <password>" });
check("nor from a player whose line the server printed itself, rank and all", b.sent.length === 0, b.sent.join(" | "));
b.emit("messagestr", "[AuthMe] Alicia: please, login with /login <password>", "system");
check("a prompt that names it is the server's all the same", b.sent[0] === "/login Pw12345abc", b.sent.join(" | "));

// ── Who is talking: what mindcraft hears ─────────────────────────────────────
b = bot();
b.username = "Alicia";
b.players = { Alicia: {}, Steve: {}, hrfd: {} };
check("a player, under their own name", JSON.stringify(hooks.speaker(b, "Steve", "hi")) === '["Steve","hi"]');
check("a rank taken for the one talking: the player behind it",
      JSON.stringify(hooks.speaker(b, "Iron", "Steve » hey you")) === '["Steve","hey you"]');
check("the server's own lines, as jartex.fun's came: nobody's", [["Iron", "hrfd joined the lobby!"],
      ["JartexNetwork", "Unknown command."], ["JartexNetwork", "You are connected to Lobby3"],
      ["LOGIN", "Please register with /register <password> <password>"]].every(([u, m]) => hooks.speaker(b, u, m) === null));
check("its own line is its own, and a name only an object has is nobody's",
      JSON.stringify(hooks.speaker(b, "Alicia", "hi")) === '["Alicia","hi"]'
      && hooks.speaker(b, "constructor", "hi") === null && hooks.speaker(b, "Iron", "toString: hi") === null);
check("a rank with no brackets, which mineflayer cuts the name of: the whole line says who",
      JSON.stringify(hooks.speaker(b, "teve", "hi", "VIP Steve: hi")) === '["Steve","hi"]'
      && JSON.stringify(hooks.spokenIn(b, "★ hrfd » gg")) === '["hrfd","gg"]');

const heard = [];
b = bot();
b.username = "Alicia";
b.players = { Alicia: {}, Steve: {} };
hooks.signInOn(b, "Pw12345abc", say);
hooks.playersOnly(b);
const mindcraftChat = (u, m) => heard.push(`${u}: ${m}`);
b.on("chat", mindcraftChat);
b.on("whisper", (u, m) => heard.push(`(w) ${u}: ${m}`));
b.emit("chat", "LOGIN", "Please register with /register <password> <password>");
b.emit("chat", "Iron", "Steve » hi there");
b.emit("chat", "JartexNetwork", "You are connected to Lobby3");
b.emit("chat", "Steve", "come here");
b.emit("chat", "teve", "over here", undefined, { toString: () => "VIP Steve: over here" });
b.emit("chat", "Alicia", "my own line");
b.emit("whisper", "Server", "hello");
b.emit("whisper", "Steve", "psst");
check("mindcraft hears players only, under their own names, and never itself",
      heard.join(" | ") === "Steve: hi there | Steve: come here | Steve: over here | (w) Steve: psst", heard.join(" | "));
check("and the sign-in prompt it never heard is answered all the same",
      b.sent[0] === "/register Pw12345abc Pw12345abc", b.sent.join(" | "));
b.removeListener("chat", mindcraftChat);
b.emit("chat", "Steve", "again");
check("a listener taken off is off", !heard.includes("Steve: again"), heard.join(" | "));
let spawned = 0;
b.on("spawn", () => spawned++);
b.emit("spawn");
check("other events as they were", spawned === 1);

b = bot();
hooks.noSkinClear(b);
b.chat("/skin clear");
b.chat("hello");
hooks.noSkinClear(b);
b.chat("/skin clear");
check("mindcraft's /skin clear at each login is not sent, the rest is", b.sent.join(" | ") === "hello", b.sent.join(" | "));

// ── A kick reason's words ────────────────────────────────────────────────────
check("a kick reason in JSON, in words", hooks.plain('{"text":"","extra":[{"text":"You are "},{"text":"banned","bold":true}]}')
      === "You are banned", hooks.plain('{"text":"","extra":[{"text":"You are "},{"text":"banned"}]}'));
check("a translated one, with its arguments", hooks.plain({ translate: "multiplayer.disconnect.kicked", with: ["x"] })
      === "multiplayer.disconnect.kicked x");
check("and plain words as they are", hooks.plain("Server closed") === "Server closed");

// ── Which version it plays (minecraft_runner.mjs takesBest), on the runner's own code ──
import fs from "fs";
const runnerSrc = fs.readFileSync(new URL("../app/platforms/minecraft/minecraft_runner.mjs", import.meta.url), "utf-8");
const block = runnerSrc.slice(runnerSrc.indexOf("const BEST = "), runnerSrc.indexOf("/** Whether to go through ViaProxy"));
const takesBest = new Function(`${block}; return takesBest;`)();
check("a range around 1.21.4 takes it: jartex.fun's Velocity 1.7.2-26.3", takesBest(["1.7.2", "26.3"]));
check("Hypixel's 'Requires MC 1.8 / 1.21': 1.21 means every 1.21", takesBest(["1.8", "1.21"]));
check("a 1.21 server takes it", takesBest(["1.21.11"]) && takesBest(["1.21"]));
check("one older version does not (it goes through ViaProxy, or plays that one)", !takesBest(["1.16.5"])
      && !takesBest(["1.8.9"]));
check("nor a range that stops short of it", !takesBest(["1.8", "1.20.4"]));

await later();
console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
