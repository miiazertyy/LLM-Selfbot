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

// Every line handed on, as Settings' "Answer every line of chat" does: who is speaking is what this part is about.
process.env.LSB_ANSWER_ALL = "1";
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
delete process.env.LSB_ANSWER_ALL;

// ── Who it answers (worthAnswering) ──────────────────────────────────────────
hooks.forgetTalk();
const me = { username: "aliciamwwoff" };
const t0 = 1_000_000_000;
const quietly = { now: t0, roll: 0.99 };
check("a whisper, always", hooks.worthAnswering(me, "Steve", "yo", true, quietly));
check("its name in the game, any case", hooks.worthAnswering(me, "Steve", "AliciaMwwOff come here", false, quietly));
check("its persona's name", hooks.worthAnswering(me, "Steve", "alicia who tf is u", false, { ...quietly, called: ["alicia"] })
      && hooks.worthAnswering(me, "Steve", "hey @Alicia", false, { ...quietly, called: ["alicia"] }));
check("  but not inside another word", !hooks.worthAnswering(me, "Steve", "malicia lol", false, { ...quietly, called: ["alicia"] }));
check("the rest of the chat goes by", !hooks.worthAnswering(me, "Bob", "anyone selling iron", false, quietly));
check("and now and then it joins in", hooks.worthAnswering(me, "Bob", "anyone selling iron", false, { now: t0, roll: 0.01 }));
check("  not again straight after", !hooks.worthAnswering(me, "Carl", "lol", false, { now: t0 + 1000, roll: 0.01 }));
check("  only once a while has gone by", hooks.worthAnswering(me, "Carl", "lol", false, { now: t0 + hooks.CHIME_MS, roll: 0.01 }));
check("Settings' every line: all of it", hooks.worthAnswering(me, "Bob", "anyone selling iron", false, { ...quietly, all: true }));
check("the players it only talks with: every line of theirs",
      hooks.worthAnswering(me, "Steve", "nice", false, { ...quietly, only: ["steve"] })
      && !hooks.worthAnswering(me, "Bob", "nice", false, { ...quietly, only: ["steve"] }));
// It has just joined in, so nothing below is let through by chance.
hooks.forgetTalk();
hooks.worthAnswering(me, "Dan", "hi", false, { now: Date.now(), roll: 0 });
const busy = [];
b = bot();
b.username = "aliciamwwoff";
b.players = { aliciamwwoff: {}, Steve: {}, Bob: {} };
hooks.playersOnly(b);
b.on("chat", (u, m) => busy.push(`${u}: ${m}`));
b.on("whisper", (u, m) => busy.push(`${u}: ${m}`));
b.emit("chat", "Bob", "anyone selling iron");
b.emit("chat", "Steve", "aliciamwwoff wanna team");
b.emit("chat", "Steve", "i have a sword");
b.emit("chat", "Bob", "lol");
b.emit("whisper", "Bob", "psst");
check("in a busy chat: its name, that player's next lines, whispers, and nobody else",
      busy.join(" | ") === "Steve: aliciamwwoff wanna team | Steve: i have a sword | Bob: psst", busy.join(" | "));
check("  and that conversation ends when it goes quiet",
      !hooks.worthAnswering(me, "Steve", "hey", false, { now: Date.now() + hooks.TALKING_MS + 1, roll: 0.99 }));
hooks.forgetTalk();

// ── Playing on its own (playOn, keepPlaying) ─────────────────────────────────
function mind() {
  const sp = {
    state: 0, prompt: "", started: [],
    isActive() { return this.state === 1; },
    isPaused() { return this.state === 2; },
    start(p) { this.started.push(p); this.state = 1; this.prompt = p; },
  };
  return { self_prompter: sp, actions: { executing: false }, said: [],
           openChat(m) { this.said.push(m); return Promise.resolve(); } };
}
const G = "Play this server's game well";
let ag = mind();
let st = { quietSince: 0, lastGoal: "", gaveUp: false };
check("no goal of its own set: it waits to be told", !(await hooks.playOn(ag, st, { goal: "", now: t0 }))
      && ag.self_prompter.started.length === 0);
check("with nothing to do, a first look only notes the quiet", !(await hooks.playOn(ag, st, { goal: G, now: t0 }))
      && st.quietSince === t0);
check("  nothing before the while is up", !(await hooks.playOn(ag, st, { goal: G, now: t0 + hooks.RESUME_MS - 1 })));
check("  then its own goal", (await hooks.playOn(ag, st, { goal: G, now: t0 + hooks.RESUME_MS }))
      && ag.self_prompter.started.join() === G);
ag.self_prompter.prompt = "build a house";
check("a goal it has, its owner's: left alone", !(await hooks.playOn(ag, st, { goal: G, now: t0 + 100_000 }))
      && st.lastGoal === "build a house");
ag.self_prompter.state = 0;
const t1 = t0 + 200_000;
await hooks.playOn(ag, st, { goal: G, now: t1 });
check("that one done: its own does not take straight over",
      !(await hooks.playOn(ag, st, { goal: G, now: t1 + hooks.RESUME_MS })));
check("  only after a longer while", (await hooks.playOn(ag, st, { goal: G, now: t1 + hooks.AFTER_ENDED_MS }))
      && ag.self_prompter.started.at(-1) === G);
ag.actions.executing = true;
ag.self_prompter.state = 0;
check("in the middle of something (a player's !followPlayer): left alone",
      !(await hooks.playOn(ag, st, { goal: G, now: t1 + 10 ** 7 })) && st.quietSince === 0);
ag.actions.executing = false;
ag.self_prompter.state = 2;
check("a goal paused is a goal it has", !(await hooks.playOn(ag, st, { goal: G, now: t1 + 10 ** 7 })) && st.quietSince === 0);

ag = mind();
hooks.keepPlaying(bot(), ag);
st = ag.__lsbPlay;
ag.self_prompter.start(G);
await hooks.playOn(ag, st, { goal: G, now: t0 });
ag.self_prompter.state = 0;
await ag.openChat("Agent did not use command in the last 3 auto-prompts. Stopping auto-prompting.");
await ag.openChat("found diamonds");
check("mindcraft giving a goal up is not said in the game; the rest is", ag.said.join(" | ") === "found diamonds",
      ag.said.join(" | "));
await hooks.playOn(ag, st, { goal: G, now: t0 + 1000 });
check("  its own goal, given up, is back soon", st.gaveUp
      && (await hooks.playOn(ag, st, { goal: G, now: t0 + 1000 + hooks.RESUME_MS })));
hooks.keepPlaying(bot(), ag);
await ag.openChat("hi");
check("  and wrapped once, however often it spawns", ag.said.join(" | ") === "found diamonds | hi");
ag.self_prompter.state = 0;
await hooks.playOn(ag, st, { goal: G, now: t0 + 500_000 });
check("its own goal ended on purpose (a player's !endGoal): not straight back",
      !(await hooks.playOn(ag, st, { goal: G, now: t0 + 500_000 + hooks.RESUME_MS }))
      && (await hooks.playOn(ag, st, { goal: G, now: t0 + 500_000 + hooks.AFTER_ENDED_MS })));

// ── Its live view, lighter ───────────────────────────────────────────────────
check("the view draws one pixel a pixel, not two or three on a scaled screen",
      hooks.PAGE_PATCHES[0].shipped === hooks.PIXELS_AS_SHIPPED && hooks.PIXELS_AS_PATCHED.includes("Math.min("));

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
