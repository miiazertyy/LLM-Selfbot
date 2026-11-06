/**
 * Playing a Minecraft account by hand from the panel (app/platforms/minecraft/agent_hooks.mjs: takeOver, input, act,
 * letGo, sayAs) and the rest of its screen (hudOf, plain, slotOf, loadPictures), under Node, against a stand-in bot
 * and a stand-in mindcraft agent. Loaded from a folder with no mineflayer, so it wraps nothing here.
 */
import { EventEmitter } from "events";
import fs from "fs";
import os from "os";
import path from "path";

process.env.LSB_MC_DIR = path.join(os.tmpdir(), "llm-no-mindcraft");
const hooks = await import("../app/platforms/minecraft/agent_hooks.mjs");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};
const later = (ms = 0) => new Promise((r) => setTimeout(r, ms));

const point = (x, y, z) => ({
  x, y, z,
  equals: (o) => o && o.x === x && o.y === y && o.z === z,
  minus: (o) => point(x - o.x, y - o.y, z - o.z),
  distanceTo: (o) => Math.hypot(x - o.x, y - o.y, z - o.z),
});

function bot() {
  const b = new EventEmitter();
  b.log = [];
  b.username = "Alicia";
  b.health = 20; b.food = 17; b.foodSaturation = 3; b.oxygenLevel = 20;
  b.entity = { position: point(10.5, 64, -3.25), yaw: 0, pitch: 0, effects: {}, velocity: { x: 0, z: 0 }, onGround: true };
  b.entities = {};
  b.players = {};
  b.time = { day: 3, timeOfDay: 1000, age: 5000 };
  b.game = { dimension: "minecraft:overworld", gameMode: "survival", difficulty: "hard" };
  b.experience = { level: 7, progress: 0.4 };
  b.registry = { effects: { 1: { name: "Speed", displayName: "Speed", type: "good" } }, foodsByName: { bread: {} } };
  const slots = new Array(46).fill(null);
  slots[36] = { name: "diamond_pickaxe", displayName: "Diamond Pickaxe", count: 1, maxDurability: 1561, durabilityUsed: 400 };
  slots[37] = { name: "bread", displayName: "Bread", count: 12 };
  slots[5] = { name: "iron_helmet", displayName: "Iron Helmet", count: 1 };
  slots[6] = { name: "diamond_chestplate", displayName: "Diamond Chestplate", count: 1 };
  slots[12] = { name: "oak_planks", displayName: "Oak Planks", count: 40 };
  b.inventory = { slots, quickBarSlot: 0 };
  b.heldItem = slots[36];
  b.controlState = { forward: false, back: false, left: false, right: false, jump: false, sprint: false, sneak: false };
  b.setControlState = (k, v) => { b.controlState[k] = v; b.log.push(`key ${k}=${v}`); };
  b.clearControlStates = () => { for (const k of Object.keys(b.controlState)) b.controlState[k] = false; b.log.push("clear"); };
  b.look = async (yaw, pitch) => { b.entity.yaw = yaw; b.entity.pitch = pitch; b.log.push(`look ${yaw.toFixed(2)} ${pitch.toFixed(2)}`); };
  b.chat = (line) => b.log.push(`chat ${line}`);
  b.cursorBlock = null;
  b.cursorEntity = null;
  b.blockAtCursor = () => b.cursorBlock;
  b.entityAtCursor = () => b.cursorEntity;
  b.canDigBlock = (blk) => blk.name !== "bedrock";
  b.digging = null;
  b.dig = (blk) => new Promise((resolve, reject) => { b.log.push(`dig ${blk.name}`); b.digging = { resolve, reject, blk }; });
  b.stopDigging = () => { if (b.digging) { b.log.push("stop dig"); b.digging.reject(new Error("aborted")); b.digging = null; } };
  b.attack = (e) => b.log.push(`attack ${e.name}`);
  b.swingArm = () => b.log.push("swing");
  b.activateBlock = async (blk, dir) => b.log.push(`use block ${blk.name} face ${dir.x},${dir.y},${dir.z}`);
  b.activateEntity = async (e) => b.log.push(`use entity ${e.name}`);
  b.activateItem = () => b.log.push("use item");
  b.deactivateItem = () => b.log.push("stop item");
  b.setQuickBarSlot = (n) => { b.inventory.quickBarSlot = n; b.log.push(`slot ${n}`); };
  b.digs = [];
  b._client = { write: (name, data) => {
    b.log.push(`packet ${name} ${data.status}`);
    if (name === "block_dig" && data.location && data.location.y > 1) b.digs.push(`${data.status}@${data.location.x},${data.location.y},${data.location.z}/${data.face}`);
    if (name === "chat_command") b.log.push(`command ${data.command}`);
  } };
  b.digTime = () => 120;
  b.supportFeature = (f) => f === "seperateSignedChatCommandPacket";
  b.equip = async (item, where) => b.log.push(`equip ${item.name} ${where}`);
  b.currentWindow = null;
  b.clickWindow = async (slot, button, mode) => b.log.push(`click ${slot} ${button} ${mode}`);
  b.closeWindow = () => b.log.push("close window");
  b.respawn = () => b.log.push("respawn");
  b.pathfinder = { stop: () => b.log.push("pathfinder stop") };
  b.autoEat = { disableAuto: () => b.log.push("autoeat off"), enableAuto: () => b.log.push("autoeat on") };
  // mindcraft's own, on the bot: modes run every tick.
  b.modeRuns = 0;
  b.modes = { update: async () => { b.modeRuns += 1; } };
  return b;
}

function agent(b) {
  const a = { bot: b, shut_up: false, handled: [], interrupts: 0 };
  a.requestInterrupt = () => { a.interrupts += 1; };
  a.actions = {
    stopped: 0,
    runAction: async (label) => ({ success: true, message: `ran ${label}` }),
    resumeAction: async () => ({ success: true, message: "resumed" }),
    stop: async () => { a.actions.stopped += 1; },
  };
  a.self_prompter = {
    prompt: "build a house", state: "active", paused: 0, started: [],
    isActive() { return this.state === "active"; },
    async pause() { this.state = "paused"; this.paused += 1; },
    async stop(stopAction) { this.state = "stopped"; this.stopped = (this.stopped || 0) + 1; this.stoppedAction = stopAction; },
    start(p) { this.state = "active"; this.started.push(p); },
  };
  a.handleMessage = async (source, message) => { a.handled.push(`${source}: ${message}`); return true; };
  return a;
}

// ── Taking it over ───────────────────────────────────────────────────────────
let b = bot();
let a = agent(b);
let r = await hooks.takeOver(b, a);
check("taken over: it says so, with its AI paused", r.ok && r.driving && r.mind === "paused", JSON.stringify(r));
check("  its goal waits where it was, and what it was doing is asked to stop (never mindcraft's own stop, which ends its process after ten seconds)",
      a.self_prompter.stopped === 1 && a.self_prompter.stoppedAction === false && a.interrupts >= 1
      && a.actions.stopped === 0 && a.shut_up === true);
check("  it no longer eats by itself (that would swap what is in the hand)", b.log.includes("autoeat off"));
await b.modes.update();
check("  its modes skip their turn (fighting back, picking up, staring at passers-by)", b.modeRuns === 0);
r = await a.actions.runAction("action:goToPlayer", async () => {});
check("  an action already on its way is turned down, with the reason", r.success === false && /by hand/.test(r.message));
r = await a.handleMessage("Steve", "hi");
check("  and what it is told waits unanswered", r === false && a.handled.length === 0);

// ── Keys and looking ─────────────────────────────────────────────────────────
r = hooks.input(b, { keys: { forward: true, sprint: true }, yaw: 1.2, pitch: -0.4 });
check("the keys held go on as they are", r.ok && b.controlState.forward && b.controlState.sprint && !b.controlState.back);
check("  and it looks where the mouse says", Math.abs(b.entity.yaw - 1.2) < 1e-9 && Math.abs(b.entity.pitch + 0.4) < 1e-9);
hooks.input(b, { keys: { forward: true, sprint: true }, yaw: 1.2, pitch: -9 });
check("  never further up or down than straight", Math.abs(b.entity.pitch + Math.PI / 2) < 1e-9);
const keyLines = b.log.filter((l) => l.startsWith("key")).length;
hooks.input(b, { keys: { forward: true, sprint: true }, yaw: 1.2, pitch: 0 });
check("  a key already held is not set again", b.log.filter((l) => l.startsWith("key")).length === keyLines);
hooks.input(b, { keys: {}, yaw: 1.2, pitch: 0 });
check("  and one let go is let go", !b.controlState.forward && !b.controlState.sprint);

// ── Hitting, mining, using ───────────────────────────────────────────────────
b.cursorEntity = { name: "zombie", position: point(11, 64, -2) };
hooks.input(b, { keys: {}, attack: true });
check("a click on someone hits them", b.log.includes("attack zombie"));
hooks.input(b, { keys: {}, attack: false });
b.cursorEntity = null;
b.cursorBlock = { name: "stone", position: point(10, 63, -4), face: 1, intersect: point(10.5, 64, -3.5) };
b.digs.length = 0;
// The physics tick, after which the bot's look goes out: a dig starts straight after it.
const tick = async () => { b.emit("physicsTick"); await later(25); };
hooks.input(b, { keys: {}, attack: true });
check("  nothing is started before the tick has sent where it looks", b.digs.length === 0, b.digs.join(" "));
await tick();
check("held on a block, it starts breaking it, on the face looked at (not always the top)",
      b.digs[0] === "0@10,63,-4/1", b.digs.join(" "));
hooks.input(b, { keys: {}, attack: true });
await tick();
check("  and keeps at the same one rather than starting it again", b.digs.length === 1, b.digs.join(" "));
b.cursorBlock = { name: "dirt", position: point(10, 62, -4), face: 4, intersect: point(10, 62.5, -3.5) };
hooks.input(b, { keys: {}, attack: true });
await tick();
check("  moved onto another, it aborts the first and starts that, on its west face",
      b.digs.join(" ") === "0@10,63,-4/1 1@10,63,-4/1 0@10,62,-4/4", b.digs.join(" "));
await later(200);
check("  the finish goes a tick after its dig time", b.digs[3] === "2@10,62,-4/4", b.digs.join(" "));
check("  and the block is left for the server to take away (no flicker when it refuses)", !b.log.some((l) => l.startsWith("dig ")));
b.cursorBlock = { name: "stone", position: point(10, 61, -4), face: 1, intersect: point(10.5, 62, -3.5) };
hooks.input(b, { keys: {}, attack: true });
await tick();
check("  nothing new starts before the server has said this one is gone", b.digs.length === 4, b.digs.join(" "));
b.emit("blockUpdate", { name: "dirt", position: point(10, 62, -4) }, { name: "air", position: point(10, 62, -4) });
await later(280);
await tick();
check("  once it has, the next one starts after the game's own beat", b.digs[4] === "0@10,61,-4/1", b.digs.join(" "));
hooks.input(b, { keys: {}, attack: false });
check("  let go before it breaks: aborted, as the game does", b.digs[5] === "1@10,61,-4/1", b.digs.join(" "));
b.cursorBlock = { name: "bedrock", position: point(10, 0, -4), face: 1, intersect: point(10.5, 1, -3.5) };
b.log.length = 0;
b.digs.length = 0;
hooks.input(b, { keys: {}, attack: true });
check("  what cannot be dug is not tried: a swing, as the game does", b.log.includes("swing") && b.digs.length === 0);
hooks.input(b, { keys: {}, attack: false });

b.cursorBlock = { name: "grass_block", position: point(10, 63, -4), face: 3, intersect: point(10.5, 63.5, -3) };
b.log.length = 0;
hooks.input(b, { keys: {}, use: true });
check("right click on a block places or uses it, on the face looked at", b.log.includes("use block grass_block face 0,0,1"));
hooks.input(b, { keys: {}, use: false });
b.heldItem = b.inventory.slots[37];
b.log.length = 0;
hooks.input(b, { keys: {}, use: true });
check("  holding bread, it eats instead", b.log.includes("use item") && !b.log.some((l) => l.startsWith("use block")));
hooks.input(b, { keys: {}, use: false });
check("  and lets go of it when the button is let go", b.log.includes("stop item"));
b.cursorBlock = { name: "chest", position: point(10, 63, -4), face: 2, intersect: point(10.5, 63.5, -4) };
b.log.length = 0;
hooks.input(b, { keys: {}, use: true });
check("  but a chest opens, whatever is in the hand", b.log.some((l) => l.startsWith("use block chest")));
hooks.input(b, { keys: {}, use: false });
b.heldItem = b.inventory.slots[36];

// ── One thing done ───────────────────────────────────────────────────────────
b.log.length = 0;
await hooks.act(b, { do: "slot", slot: 4 });
check("a hotbar slot picked", b.inventory.quickBarSlot === 4 && b.log.includes("slot 4"));
await hooks.act(b, { do: "slot", slot: 40 });
check("  never one past the ninth", b.inventory.quickBarSlot === 8);
await hooks.act(b, { do: "drop" });
await hooks.act(b, { do: "drop", all: true });
await hooks.act(b, { do: "swap" });
check("drop one, drop all, swap hands: the game's own packets", b.log.includes("packet block_dig 4")
      && b.log.includes("packet block_dig 3") && b.log.includes("packet block_dig 6"), b.log.join(" | "));
await hooks.act(b, { do: "equip", slot: 12 });
check("something in the bag into the hand", b.log.includes("equip oak_planks hand"));
b.inventory.slots[20] = { name: "golden_boots", displayName: "Golden Boots", count: 1 };
await hooks.act(b, { do: "equip", slot: 20 });
check("  armour onto where it goes", b.log.includes("equip golden_boots feet"));
r = await hooks.act(b, { do: "move", slot: 0 });
check("moving out of a chest with none open says so", !r.ok && /Nothing is open/.test(r.reason));
b.currentWindow = { inventoryStart: 27, slots: Object.assign(new Array(63).fill(null), { 3: { name: "apple", count: 2 }, 30: { name: "oak_planks", count: 40 } }), title: '{"text":"Chest"}', type: "minecraft:generic_9x3" };
await hooks.act(b, { do: "move", slot: 3 });
check("  with one open, a click moves the slot across, as a shift-click", b.log.includes("click 3 0 1"));
await hooks.act(b, { do: "move", slot: 12, own: true });
check("  and its own slot is found in the open window", b.log.includes("click 30 0 1"), b.log.join(" | "));
const hudWin = hooks.hudOf(b);
check("  the open window is on its screen, by its own name", hudWin.window && hudWin.window.title === "Chest"
      && hudWin.window.slots.length === 27 && hudWin.window.slots[3].slot === 3);
await hooks.act(b, { do: "close" });
check("  and closed", b.log.includes("close window"));
b.currentWindow = null;

// ── Its chat ─────────────────────────────────────────────────────────────────
b.log.length = 0;
r = hooks.sayAs(b, { text: "  hello   there  " });
check("typed into its chat, as it", r.ok && b.log.includes("chat hello there"));
hooks.sayAs(b, { text: "/spawn" });
check("  a command too", b.log.includes("chat /spawn"));
r = hooks.sayAs(b, { text: "   " });
check("  nothing typed, nothing sent", !r.ok && b.log.length === 2);
hooks.sayAs(b, { text: "x".repeat(400) });
check("  never longer than the game takes", b.log[b.log.length - 1].length === "chat ".length + 256);

// ── Letting go ───────────────────────────────────────────────────────────────
let idled = 0;
b.on("idle", () => { idled += 1; });
b.controlState.forward = true;
r = hooks.letGo(b);
check("let go: every key up", r.ok && !r.driving && !b.controlState.forward);
check("  its goal picks up again, and it may answer again", a.self_prompter.started[0] === "build a house" && a.shut_up === false);
check("  it eats by itself again, and carries on as after any action", b.log.includes("autoeat on") && idled === 1);
await b.modes.update();
check("  its modes run again", b.modeRuns === 1);
r = await a.actions.runAction("action:goToPlayer", async () => {});
check("  and its actions", r.success === true);
r = hooks.input(b, { keys: { forward: true } });
check("keys with nobody in control are refused", !r.ok && !b.controlState.forward);
r = await hooks.act(b, { do: "slot", slot: 2 });
check("  and so are slots", !r.ok && b.inventory.quickBarSlot !== 2);

// Without an agent to hand (another mindcraft), the bot's own walking and fighting is stopped all the same.
const b2 = bot();
b2.log.length = 0;
r = await hooks.takeOver(b2, null);
check("taken over without its agent: still in control, and its walking stopped", r.ok && r.mind === "partly"
      && b2.log.includes("pathfinder stop"));
hooks.letGo(b2);
r = await hooks.takeOver({ ...bot(), entity: null }, null);
check("not in a world: nothing to take over", !r.ok);

// ── The rest of its screen ───────────────────────────────────────────────────
check("a title as a tag (1.20.3 on)", hooks.plain({ text: { type: "string", value: "Welcome" } }) === "Welcome");
check("  a whole component as a tag", hooks.plain({ type: "compound", value: { text: { type: "string", value: "Hi " }, extra: { type: "list", value: { type: "compound", value: [{ text: { type: "string", value: "there" } }] } } } }) === "Hi there");
check("  prismarine-chat's own message by its own words", hooks.plain({ json: {}, toString: () => "Lobby #3" }) === "Lobby #3");
check("colour codes left out", hooks.bare("§aVIP §fSteve§r ") === "VIP Steve");
check("  and any other character after a §, as the game hides it", hooks.bare("Rank: Player§/") === "Rank: Player");
check("  a server's own icon glyphs, boxes without its pack, left out; emoji kept",
      hooks.bare("<5x�09sakuraa> hi \u{1F600}") === "<5x09sakuraa> hi \u{1F600}");
check("armour points, as the game counts them", hooks.armourPoints(b.inventory.slots) === 2 + 8);

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "lsb-tex-"));
for (const d of ["items", "blocks", "mob_effect", "gui/sprites/hud/heart"]) fs.mkdirSync(path.join(tmp, d), { recursive: true });
for (const f of ["items/diamond_pickaxe.png", "items/bread.png", "blocks/oak_planks.png", "mob_effect/speed.png",
                 "gui/sprites/hud/heart/full.png"]) fs.writeFileSync(path.join(tmp, f), "");
fs.writeFileSync(path.join(tmp, "items_textures.json"), JSON.stringify([
  { name: "diamond_pickaxe", texture: "minecraft:items/diamond_pickaxe" }, { name: "bread", texture: "items/bread" },
  { name: "oak_planks", texture: "minecraft:block/oak_planks" }, { name: "barrier", texture: "minecraft:items/barrier" },
]));
const pics = hooks.loadPictures("9.9.9", tmp);
check("each item's own picture, from the viewer's textures", pics.items.get("diamond_pickaxe") === "items/diamond_pickaxe.png"
      && pics.items.get("oak_planks") === "blocks/oak_planks.png" && pics.items.get("bread") === "items/bread.png");
check("  none for one whose file is not there", !pics.items.has("barrier"));
check("  and the HUD's own hearts are there", pics.sprites === true);

hooks.followScreen(b);
b.entity.yaw = 0;
b.entity.pitch = 0;
b.entity.effects = { 1: { id: 1, amplifier: 1, duration: 600 } };
b.emit("entityEffect", b.entity, { id: 1 });
b.bossBars = [{ title: { json: {}, toString: () => "The Ender Dragon" }, health: 0.5, color: "purple", dividers: 0 }];
b.scoreboard = { sidebar: { title: '{"text":"JARTEX"}', items: [{ name: "a", value: 3, displayName: { json: {}, toString: () => "§eCoins: 120" } }] } };
b.players = { Steve: { username: "Steve", ping: 42, displayName: { json: {}, toString: () => "[VIP] Steve" } } };
b.tablist = { header: { json: {}, toString: () => "Welcome!" }, footer: { json: {}, toString: () => "play.example" } };
const h = hooks.hudOf(b, { tab: true, debug: true });
check("its screen: hotbar with pictures and where each slot is", h.hotbar[0].icon === "items/diamond_pickaxe.png"
      && h.hotbar[0].slot === 36 && h.hotbar[0].left > 0.7 && h.hotbar[0].left < 0.8);
check("  experience, armour, and the other hand", h.xp.level === 7 && h.armourPoints === 10 && h.offhand === null);
check("  effects with their level, picture and time left",
      h.effects.length === 1 && h.effects[0].level === 2 && h.effects[0].icon === "mob_effect/speed.png" && h.effects[0].left === 30);
check("  boss bars", h.bossBars[0].title === "The Ender Dragon" && h.bossBars[0].health === 0.5 && h.bossBars[0].color === "purple");
check("  the server's board", h.sidebar.title === "JARTEX" && h.sidebar.rows[0].text === "Coins: 120");
check("  the player list, when asked", h.players[0].shown === "[VIP] Steve" && h.players[0].ping === 42
      && h.tabTop === "Welcome!" && h.tabBottom === "play.example");
check("  the debug screen, when asked: where, which way, how fast the server runs",
      h.debug.block.join() === "10,64,-4" && h.debug.chunk.join() === "0,4,-1" && h.debug.facing === "north"
      && Math.abs(h.debug.yaw) === 180 && typeof h.debug.memory === "number", JSON.stringify(h.debug).slice(0, 300));
const plainHud = hooks.hudOf(b);
check("  and neither when not asked", !("players" in plainHud) && !("debug" in plainHud));
b.emit("title", '{"text":"Round 2"}', "title");
b.emit("title", "Fight!", "subtitle");
check("titles as they come", hooks.hudOf(b).title?.text === "Round 2");
b.emit("title_clear");
check("  and cleared", hooks.hudOf(b).title === null);

fs.rmSync(tmp, { recursive: true, force: true });

// ── What there is to see in the view ────────────────────────────────────────
const vb = bot();
vb.registry.entitiesByName = {
  armor_stand: { metadataKeys: ["shared_flags", "air_supply", "custom_name", "custom_name_visible"] },
  text_display: { metadataKeys: Object.assign(new Array(23).fill("x"), { 0: "shared_flags", 2: "custom_name", 3: "custom_name_visible" }).concat(["text"]) },
};
vb.teamMap = {
  NPC_3: { nameTagVisibility: "never", displayName: () => "NPC_3" },
  Steve: { nameTagVisibility: "always", displayName: () => ({ json: {}, toString: () => "§6[VIP] §fSteve" }) },
};
const stand = (id, meta) => ({ id, type: "object", name: "armor_stand", metadata: meta, position: point(0, 70, 0), width: 0.5, height: 1.975 });
const hidden = stand(1, { 0: 0x20 });
const line = stand(2, { 0: 0x20, 2: '{"text":"§aBed Wars"}', 3: true });
const shownStand = stand(3, { 0: 0 });
const textLine = { id: 4, type: "object", name: "text_display", metadata: { 23: { text: "Click to play" } }, position: point(0, 71, 0), width: 0, height: 0 };
const npc = { id: 5, type: "player", name: "player", username: "NPC_3", metadata: {}, position: point(1, 70, 0), width: 0.6, height: 1.8 };
const steve = { id: 6, type: "player", name: "player", username: "Steve", metadata: {}, position: point(2, 70, 0), width: 0.6, height: 1.8 };
const ghost = { id: 7, type: "player", name: "player", username: "Staff", metadata: { 0: 0x20 }, position: point(3, 70, 0), width: 0.6, height: 1.8 };
for (const e of [hidden, line, shownStand, textLine, npc, steve, ghost]) vb.entities[e.id] = e;
check("an invisible stand is not drawn at all", hooks.lookFor(vb, hidden).show === false);
check("  one with its name showing is a line of floating text, its words alone",
      hooks.lookFor(vb, line).username === "\u0001Bed Wars" && hooks.lookFor(vb, line).name === "armor_stand");
check("  a text display too", hooks.lookFor(vb, textLine).username === "\u0001Click to play");
check("  a visible stand is drawn as it is", hooks.lookFor(vb, shownStand).show && hooks.lookFor(vb, shownStand).username === undefined);
check("a player whose team hides their name: no name, their skin still theirs", hooks.lookFor(vb, npc).username === "\u0002NPC_3");
check("  one their team writes out, as it writes it", hooks.lookFor(vb, steve).username === "Steve\u0003[VIP] Steve");
check("  an invisible player is not drawn", hooks.lookFor(vb, ghost).show === false);

const emitted = [];
const fakeSocket = { emit: (ev, d) => emitted.push([ev, d]), on: () => {} };
const seen = hooks.seenThrough(vb, fakeSocket);
for (const e of [hidden, line, steve]) seen.emit("entity", { id: e.id, name: e.name, pos: e.position, width: e.width, height: e.height, username: e.username });
seen.emit("entity", { id: 1, pos: point(0, 71, 0) });
seen.emit("entity", { id: 6, pos: point(2.5, 70, 0), yaw: 1 });
const ids = emitted.map(([, d]) => d.id);
check("the page is never told of what cannot be seen, its moves neither", !ids.includes(1));
check("  floating text and players are, as lookFor draws them",
      emitted.some(([, d]) => d.id === 2 && d.username === "\u0001Bed Wars") && emitted.some(([, d]) => d.id === 6 && d.username === "Steve\u0003[VIP] Steve"));
check("  and their moves follow", emitted.some(([, d]) => d.id === 6 && d.yaw === 1 && !d.name));
emitted.length = 0;
steve.metadata = { 0: 0x20 };
seen.changed(steve);
check("made invisible: taken off the page", emitted.length === 1 && emitted[0][1].delete === true && emitted[0][1].id === 6);
emitted.length = 0;
seen.changed(line);
check("  a look that did not change sends nothing", emitted.length === 0);

// The name tag as the page draws it (NAMETAG_AS_DRAWN), run against stand-ins for the viewer's canvas and three.js.
const tag = (username) => {
  const children = [{ visible: true }];
  const i = { mesh: { children, add(c) { children.push(c); } } };
  const ctx = { measureText: (x) => ({ width: x.length * 30 }), beginPath() {}, moveTo() {}, arcTo() {}, closePath() {}, fill() {}, fillText() {} };
  const s = () => ({ getContext: () => ctx });
  class Sprite { constructor(m) { this.material = m; this.scale = { set() {} }; this.position = { y: 0 }; this.visible = true; } }
  const n = { Texture: class {}, SpriteMaterial: class { constructor(o) { Object.assign(this, o); } }, Sprite, LinearFilter: 1 };
  new Function("t", "i", "s", "n", hooks.NAMETAG_AS_DRAWN)({ username, height: 1.8 }, i, s, n);
  return { user: i.mesh.__lsbUser, tags: children.length - 1, model: children[0].visible };
};
let tg = tag("Steve");
check("a name: drawn over them, and their skin looked up by it", tg.user === "Steve" && tg.tags === 1 && tg.model);
tg = tag("\u0001Bed Wars");
check("  floating text: its words alone, the stand it hangs on hidden", tg.user === "" && tg.tags === 1 && !tg.model);
tg = tag("\u0002NPC_3");
check("  a hidden name: none drawn, the skin still theirs", tg.user === "NPC_3" && tg.tags === 0 && tg.model);
tg = tag("Steve\u0003[VIP] Steve");
check("  as their team writes it, and their skin by their own name", tg.user === "Steve" && tg.tags === 1);
{
  const children = [{ visible: true }];
  const i = { mesh: { children, add(c) { children.push(c); } } };
  const ctx = { measureText: (x) => ({ width: x.length * 30 }), beginPath() {}, moveTo() {}, arcTo() {}, closePath() {}, fill() {}, fillText() {} };
  class Sprite { constructor(m) { this.material = m; this.scale = { set() {} }; this.position = { y: 0 }; } }
  new Function("t", "i", "s", "n", hooks.NAMETAG_AS_DRAWN)({ username: "Steve", height: 1.8 }, i,
    () => ({ getContext: () => ctx }), { Texture: class {}, SpriteMaterial: class {}, Sprite, LinearFilter: 1 });
  check("  the tag kept with its size, for the page to keep it from filling the screen up close",
        i.mesh.__lsbTag === children[1] && i.mesh.__lsbTag.__lsbW > 0 && i.mesh.__lsbTag.__lsbH === 0.42);
}
check("the viewer's bones get their names, so legs and arms can be found to move",
      hooks.BONES_AS_PATCHED === "i[t.name]=r,r.name=t.name,t.cubes)for(const i of t.cubes)"
      && hooks.PAGE_PATCHES.some((p) => p.shipped === hooks.BONES_AS_SHIPPED));

// ── The server's board, as 1.20.3 on sends it ───────────────────────────────
const sb = bot();
sb._client = new EventEmitter();
sb._client.write = () => {};
sb.teamMap = { "§1": { displayName: () => ({ json: {}, toString: () => "§eCoins: §f50" }) } };
sb.scoreboard = { sidebar: { name: "side", title: { json: {}, toString: () => "JartexNetwork" }, items: [] } };
hooks.followScreen(sb);
sb._client.emit("scoreboard_objective", { name: "side", action: 0, number_format: 0 });
sb._client.emit("scoreboard_score", { itemName: "§1", scoreName: "side", value: 3 });
sb._client.emit("scoreboard_score", { itemName: "Rank: VIP", scoreName: "side", value: 4 });
sb._client.emit("scoreboard_score", { itemName: "§2", scoreName: "side", value: 1, display_name: { text: "play.jartex.fun" } });
let rows = hooks.hudOf(sb).sidebar.rows;
check("its lines, which mineflayer leaves empty from 1.20.3 on, highest first",
      rows.map((r) => r.text).join(" | ") === "Rank: VIP | Coins: 50 | play.jartex.fun", JSON.stringify(rows));
check("  each line as its team writes it, the numbers hidden where the server hides them", rows.every((r) => r.value === null));
sb._client.emit("reset_score", { entity_name: "Rank: VIP", objective_name: "side" });
rows = hooks.hudOf(sb).sidebar.rows;
check("  and a line taken away goes", rows.length === 2 && !rows.some((r) => r.text === "Rank: VIP"));
sb._client.emit("scoreboard_score", { itemName: "§3", scoreName: "side", value: 9, number_format: 2, styling: { text: "NEW" } });
check("  a fixed text in place of a number is shown as it is", hooks.hudOf(sb).sidebar.rows[0].fixed === "NEW");

// ── A 1.21 client, as a server expects one ───────────────────────────────────
{
  const gb = bot();
  const out = [];
  gb._client = new EventEmitter();
  gb._client.state = "play";
  gb._client.write = (n, d) => out.push([n, d]);
  hooks.playLikeTheGame(gb, { packet_block_dig: ["container", [{ name: "sequence", type: "varint" }]],
                             packet_player_input: {}, packet_tick_end: {} });
  gb._client.write("block_dig", { status: 0, location: point(1, 2, 3), face: 1 });
  gb._client.write("use_item", { hand: 0, sequence: 7 });
  gb._client.write("block_place", { location: point(1, 2, 3), sequence: 0 });
  gb._client.write("block_dig", { status: 4, location: point(0, 0, 0), face: 0, sequence: 0 });
  const seqs = out.map(([n, d]) => `${n}:${d.sequence}`).join(" ");
  check("one numbering for everything it predicts, always rising (a strict server kicked it for 'Invalid sequence')",
        seqs === "block_dig:1 use_item:2 block_place:3 block_dig:0", seqs);
  out.length = 0;
  gb.setControlState("forward", true);
  gb.setControlState("sprint", true);
  const inputs = out.filter(([n]) => n === "player_input").map(([, d]) => d.inputs);
  check("  its keys as they are, whenever they change (mineflayer sent sneaking only, every other key up)",
        inputs.length === 2 && inputs[1].forward === true && inputs[1].sprint === true && inputs[1].jump === false, JSON.stringify(inputs));
  gb.setControlState("forward", true);
  check("  and nothing when nothing changed", out.filter(([n]) => n === "player_input").length === 2);
  out.length = 0;
  for (let i = 0; i < 3; i++) {
    gb.emit("physicsTick");
    gb._client.write("position", { x: i });
  }
  // With the end of each tick the server held it to the game's order inside each tick, and kicked it.
  check("  but not the end of each tick, which got it kicked", !out.some(([n]) => n === "tick_end"),
        out.map(([n]) => n).join(" "));
  gb.emit("end");
}

// ── The held item used on a block at once ────────────────────────────────────
{
  const ub = bot();
  ub.supportFeature = (f) => f === "blockPlaceHasInsideBlock";
  ub.heldItem = { name: "dirt", count: 5 };
  const sent = [];
  ub._client.write = (n, d) => sent.push([n, d]);
  ub.activateBlock = async () => sent.push(["activateBlock"]);
  await hooks.takeOver(ub, null);
  ub.cursorBlock = { name: "stone", position: point(5, 63, 5), face: 1, intersect: point(5.5, 64, 5.25) };
  hooks.input(ub, { keys: {}, use: true });
  const place = sent.find(([n]) => n === "block_place");
  check("a block placed at once on the face under the crosshair, without turning to its middle first",
        place && place[1].direction === 1 && place[1].cursorY === 1 && !sent.some(([n]) => n === "activateBlock"),
        JSON.stringify(sent).slice(0, 200));
  hooks.input(ub, { keys: {}, use: false });
  hooks.letGo(ub);
}

// ── Commands, the game's way ─────────────────────────────────────────────────
{
  const cb = bot();
  cb.log.length = 0;
  hooks.noSkinClear(cb);
  cb.chat("/settings");
  cb.chat("/msg Steve hi");
  check("a command with nothing to sign goes plain, as the game sends it", cb.log.includes("command settings"), cb.log.join(" | "));
  check("  a message to someone still goes the signed way", cb.log.includes("chat /msg Steve hi"), cb.log.join(" | "));
  const old = bot();
  old.supportFeature = () => false;
  hooks.noSkinClear(old);
  old.log.length = 0;
  old.chat("/spawn");
  check("  on an older version, as before", old.log.includes("chat /spawn"), old.log.join(" | "));
}

// ── A server's menus, for its AI ─────────────────────────────────────────────
{
  const mb = bot();
  const cmpCustom = (name, lore) => ({ name: "compass", displayName: "Compass", count: 1, customName: JSON.stringify({ text: name }), customLore: lore });
  mb.inventory.slots[38] = cmpCustom("§aServer Selector §7(Right Click)");
  mb.currentWindow = null;
  mb.activateItem = () => {
    mb.log.push("use item");
    mb.currentWindow = { id: 3, inventoryStart: 27, title: '{"text":"Game Menu"}', slots: Object.assign(new Array(63).fill(null), {
      0: { name: "gray_stained_glass_pane", displayName: "Gray Stained Glass Pane", count: 1, customName: JSON.stringify({ text: " " }) },
      11: { name: "red_bed", displayName: "Red Bed", count: 1, customName: JSON.stringify({ text: "BedWars" }), customLore: [JSON.stringify({ text: "§7Click to play!" })] },
      15: { name: "gold_ingot", displayName: "Gold Ingot", count: 1, customName: JSON.stringify({ text: "Shop" }), customLore: [JSON.stringify({ text: "Buy ranks for $5" })] },
    }) };
    setTimeout(() => mb.emit("windowOpen", mb.currentWindow), 30);
  };
  let r = await hooks.useNamedItem(mb, "server selector");
  check("an item used by the name the server gave it: held, right-clicked, and the menu it opened read out",
        mb.inventory.quickBarSlot === 2 && mb.log.includes("use item") && /Menu open: "Game Menu"/.test(r), r);
  check("  each button with what it says, the frame's blank panes left out",
        /slot 11: BedWars - Click to play!/.test(r) && !/slot 0:/.test(r), r);
  check("  and what costs money marked as such", /slot 15: Shop - Buy ranks for \$5 \(spends money\)/.test(r), r);
  mb.clickWindow = async (slot, button, mode) => {
    mb.log.push(`click ${slot} ${button} ${mode}`);
    mb.currentWindow = null;
    setTimeout(() => mb.emit("windowClose"), 20);
  };
  r = await hooks.clickMenu(mb, 11);
  check("a slot clicked as the game clicks it, and what happened said", mb.log.includes("click 11 0 0") && /Clicked BedWars. The menu closed/.test(r), r);
  r = await hooks.clickMenu(mb, 11);
  check("  with nothing open, it says how to open one", /No menu is open/.test(r), r);
  r = await hooks.runServerCommand(mb, "/pay Steve 1000000");
  check("never a command that pays, sells, trades or gives", /^Not \/pay/.test(r) && !mb.log.some((l) => /pay/.test(l)), r);
  hooks.noSkinClear(mb);
  setTimeout(() => mb.emit("messagestr", "You have $1,300", "system"), 30);
  r = await hooks.runServerCommand(mb, "bal");
  check("  any other command run, and the server's answer heard (not players' chat)", mb.log.includes("command bal") && /the server said You have \$1,300/.test(r), r);

  const ma = agent(mb);
  const stats = { name: "!stats", perform: async () => "STATS\n- Health: 20" };
  const inventory = { name: "!inventory", perform: async () => "INVENTORY\n- compass: 1" };
  mb.currentWindow = { id: 9, inventoryStart: 27, title: '{"text":"Settings"}', slots: new Array(63).fill(null) };
  const added = await hooks.teachMenus(mb, ma, (name) => ({ "!stats": stats, "!inventory": inventory })[name]);
  const lookup = {};
  check("its AI given the menu commands, where mindcraft looks commands up by name",
        added && ["!useItem", "!menu", "!clickMenuSlot", "!closeMenu", "!runCommand"].every((n) => lookup[n] && typeof lookup[n].perform === "function")
        && !Object.keys(lookup).length && JSON.stringify(lookup) === "{}");
  check("  its stats say a menu is open", /Menu open on your screen: "Settings"/.test(await stats.perform(ma)));
  check("  its inventory says what the server named its items", /compass: "Server Selector \(Right Click\)" \(hotbar 3\)/.test(await inventory.perform(ma)));
  for (const c of hooks.MENU_COMMANDS) delete Object.prototype[c.name];
}

// ── Creatures and things the viewer has no model for ─────────────────────────
{
  const eb = bot();
  hooks.loadModels(["player", "zombie", "skeleton", "armor_stand", "cow"]);
  hooks.loadPictures("9.9.8", (() => {
    const t = fs.mkdtempSync(path.join(os.tmpdir(), "lsb-tex2-"));
    fs.mkdirSync(path.join(t, "items"));
    fs.writeFileSync(path.join(t, "items", "diamond.png"), "");
    fs.writeFileSync(path.join(t, "items_textures.json"), JSON.stringify([{ name: "diamond", texture: "minecraft:items/diamond" }]));
    return t;
  })());
  const ent = (name, type, extra = {}) => ({ id: 1, name, type, metadata: {}, position: point(0, 64, 0), displayName: name, ...extra });
  check("a creature it has a model for, as it is", hooks.lookFor(eb, ent("zombie", "hostile")).name === "zombie");
  check("  one it lacks, as the nearest it has (bogged as a skeleton)", hooks.lookFor(eb, ent("bogged", "hostile")).name === "skeleton");
  check("  one with nothing near: its name, floating where it is, never a magenta box",
        hooks.lookFor(eb, ent("sniffer", "animal", { displayName: "Sniffer" })).username === "\u0001Sniffer");
  check("  a dropped item, as its own picture",
        hooks.lookFor(eb, ent("item", "other", { getDroppedItem: () => ({ name: "diamond" }) })).username === "\u0004textures/9.9.8/items/diamond.png");
  check("  boats, falling blocks and the like: left out", hooks.lookFor(eb, ent("oak_boat", "other")).show === false);
  hooks.loadModels(null);
}

// ── The world sent a chunk at a time ─────────────────────────────────────────
{
  const loaded = [];
  // Each chunk takes a while to pack, as a real one does.
  const world = { loadChunk: async (p) => { loaded.push(p.x); await later(20); } };
  hooks.loadGently(world);
  const first = world._loadChunks([{ x: 1 }, { x: 2 }, { x: 3 }, { x: 4 }]);
  await later(30);
  const second = world._loadChunks([{ x: 9 }]);
  await Promise.all([first, second]);
  check("chunks one at a time, and a newer list ends an older one",
        loaded.includes(9) && !loaded.includes(4) && loaded[0] === 1, loaded.join(","));
}

await later();
console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
