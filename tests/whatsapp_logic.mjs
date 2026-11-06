/**
 * whatsappbot.js's own logic, run for real.
 *
 * This is the test X's and Reddit's could not have. They are scrapers, so the only way to check them without an
 * account is a saved copy of a page in a headless browser, and even then "does the real site still look like
 * this" is unanswerable. WhatsApp has no page: what arrives is a message object, and a message object can be
 * written down exactly. So every shape WhatsApp sends is here, and the thing that reads them is run against all
 * of them - no Chrome, no fixtures of a page, no guessing.
 *
 * The module is imported as it is. It pulls in baileys only inside connect(), so nothing here needs the package
 * installed.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const BOT = path.join(ROOT, "app", "platforms", "snapchat", "whatsappbot.js");

let pass = 0;
const failed = [];
function check(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  PASS  ${name}`); }
  else { failed.push(name); console.log(`  FAIL  ${name}${extra ? `  [${extra}]` : ""}`); }
}

const m = await import(pathToFileURL(BOT).href);

const ME = "447711111111";
const THEM = "447700900123@s.whatsapp.net";
const GROUP = "120363045@g.us";

/** One message as WhatsApp sends it: the key, the push name, the stamp, and whichever shape it is. */
const msg = (message, over = {}) => ({
  key: { remoteJid: THEM, id: "A1", fromMe: false, ...(over.key || {}) },
  pushName: "Theo",
  messageTimestamp: 1793550000,
  message,
  ...Object.fromEntries(Object.entries(over).filter(([k]) => k !== "key")),
});

console.log("== who is who ==");
check("a person's id is wa_ and their number",
      m.chatIdFor(THEM) === "wa_447700900123" && m.chatIdFor("447700900123:17@s.whatsapp.net") === "wa_447700900123");
check("a group's is wag_ and its own id", m.groupIdFor(GROUP) === "wag_120363045");
check("and a status is nobody's conversation", m.idOf("status@broadcast") === "");
check("both read back to the id WhatsApp wants",
      m.jidOf("wa_447700900123") === THEM && m.jidOf("wag_120363045") === "120363045@g.us");
check("a group is told from a person before anything else is read",
      m.jidOf("wag_120363045").endsWith("@g.us") && m.isGroupId("wag_120363045") && !m.isGroupId("wa_1"));
check("and nothing else passes for a chat id",
      m.CHAT_ID.test("wa_447700900123") && m.CHAT_ID.test("wag_120363045")
      && !m.CHAT_ID.test("wa_") && !m.CHAT_ID.test("wa_12") && !m.CHAT_ID.test("rd_someone")
      && !m.CHAT_ID.test("wag_"));
check("a number that is not one gives nothing",
      m.numberOf("not-a-jid") === "" && m.chatIdFor("") === "" && m.jidOf("x_someone") === "");

console.log("\n== every shape a message comes in ==");
const cases = [
  ["plain words", { conversation: "hello there" }, { text: "hello there", kind: "" }],
  ["a long message, which WhatsApp wraps differently",
   { extendedTextMessage: { text: "a longer one" } }, { text: "a longer one", kind: "" }],
  ["a photo, with what was said about it",
   { imageMessage: { caption: "look at this", mimetype: "image/jpeg" } }, { text: "look at this", kind: "photo" }],
  ["a video", { videoMessage: { caption: "", mimetype: "video/mp4" } }, { text: "", kind: "video" }],
  ["a gif, which WhatsApp sends as a video that loops",
   { videoMessage: { gifPlayback: true } }, { kind: "gif" }],
  ["a voice note, which is an audio message that says it is one",
   { audioMessage: { ptt: true, seconds: 7 } }, { kind: "voice" }],
  ["music, which is the same shape and is not one", { audioMessage: { ptt: false } }, { kind: "audio" }],
  ["a sticker", { stickerMessage: { mimetype: "image/webp" } }, { kind: "sticker" }],
  ["a file", { documentMessage: { fileName: "x.pdf", caption: "" } }, { kind: "file" }],
  ["a place", { locationMessage: { degreesLatitude: 51.5 } }, { kind: "location" }],
  ["a poll", { pollCreationMessage: { name: "which?" } }, { kind: "poll" }],
];
for (const [what, body, want] of cases) {
  const got = m.shape(msg(body), ME);
  const ok = Object.entries(want).every(([k, v]) => got[k] === v);
  check(`  ${what}`, ok, JSON.stringify({ text: got.text, kind: got.kind }));
}

console.log("\n== the shapes wrapped inside other shapes ==");
check("a disappearing message is read as what is inside it",
      m.textOf({ ephemeralMessage: { message: { conversation: "gone later" } } }) === "gone later");
check("a view-once photo is still a photo",
      m.kindOf({ viewOnceMessageV2: { message: { imageMessage: { caption: "" } } } }) === "photo");
check("a file with words on it is still a file",
      m.kindOf({ documentWithCaptionMessage: { message: { documentMessage: { fileName: "a.pdf" } } } }) === "file");
check("and an edited message is read as its new words",
      m.textOf({ editedMessage: { message: { conversation: "fixed that" } } }) === "fixed that");

console.log("\n== replies, reactions and deletes ==");
const reply = m.shape(msg({
  extendedTextMessage: {
    text: "yes it is",
    contextInfo: { stanzaId: "B2", participant: `${ME}@s.whatsapp.net`,
                   quotedMessage: { conversation: "is that right?" } },
  },
}), ME);
check("a reply carries what it answers, and who said it",
      reply.quoted && reply.quoted.text === "is that right?" && reply.quoted.from === ME,
      JSON.stringify(reply.quoted));
const react = m.shape(msg({ reactionMessage: { key: { id: "A1" }, text: "❤️" } }), ME);
check("a reaction is a reaction, not a message that says an emoji",
      react.kind === "reaction" && react.reaction.emoji === "❤️" && react.text === "");
check("a delete says so rather than coming through empty",
      m.kindOf({ protocolMessage: { type: 0 } }) === "deleted");

console.log("\n== whose a message is ==");
check("its own is known as its own",
      m.shape(msg({ conversation: "mine" }, { key: { fromMe: true } }), ME).mine === true);
check("and theirs is not", m.shape(msg({ conversation: "theirs" }), ME).mine === false);
const inGroup = m.shape(msg({ conversation: "hi all" },
                            { key: { remoteJid: GROUP, participant: THEM } }), ME);
check("in a group the sender is the participant, not the group",
      inGroup.group === true && inGroup.author === "447700900123" && inGroup.chat === "wag_120363045");
const status = m.shape(msg({ conversation: "a status" }, { key: { remoteJid: "status@broadcast", participant: THEM } }),
                       ME);
check("a status is marked as one and belongs to no chat", status.status === true && status.chat === "");

console.log("\n== what a message is when it has no words ==");
check("each kind says what it was, so the brain is never handed an empty line",
      m.describe({ text: "", kind: "voice" }) === "[voice note]"
      && m.describe({ text: "", kind: "photo" }) === "[photo]"
      && m.describe({ text: "hello", kind: "photo" }) === "hello"
      && m.describe({ text: "", kind: "", reaction: { emoji: "\u{1F525}" } }) === "[reacted \u{1F525}]");
check("and something it has never seen still says something", m.describe({ text: "", kind: "newthing" })
      === "[message]");

console.log("\n== when a group message is for it ==");
const g = (text, quotedFrom) => ({
  group: true, text,
  quoted: quotedFrom ? { from: quotedFrom, text: "", kind: "", id: "" } : null,
});
check("its own name, said in a group", m.forUs(g("has anyone seen Alicia today"), "Alicia, Ali", ME) === true);
check("one of its other names too", m.forUs(g("ali what do you think"), "Alicia, Ali", ME) === true);
check("a reply to something it said", m.forUs(g("that is true", ME), "Alicia", ME) === true);
check("but not a group it was only talking in", m.forUs(g("anyway, lunch?"), "Alicia", ME) === false);
check("and never a name inside another word",
      m.forUs(g("the generalisation is wrong"), "Ali", ME) === false);
check("with no names set it says nothing in a group at all",
      m.forUs(g("Alicia?"), "", ME) === false);
check("one to one it is always for it", m.forUs({ group: false, text: "hi" }, "", ME) === true);

console.log("\n== keys that do not move ==");
const { keyed } = await import(pathToFileURL(path.join(ROOT, "app", "platforms", "snapchat",
                                                       "runner_core.js")).href);
const convo = [m.shape(msg({ conversation: "one" }), ME),
               m.shape(msg({ conversation: "two" }, { key: { id: "A2" } }), ME),
               m.shape(msg({ conversation: "one" }, { key: { id: "A3" } }), ME)];
const once = keyed("wa_447700900123", convo.map((x) => ({ ...x, text: m.describe(x) })), { prefix: "w" });
const twice = keyed("wa_447700900123", convo.map((x) => ({ ...x, text: m.describe(x) })), { prefix: "w" });
check("the same conversation read twice gives the same keys",
      JSON.stringify(once.map((k) => k.key)) === JSON.stringify(twice.map((k) => k.key)));
check("the same words said twice in a day are still two messages",
      once[0].key !== once[2].key);
check("and they are WhatsApp's own, not another platform's", once.every((k) => k.key.startsWith("w")));

console.log("\n== a status goes to the people it is for ==");
// WhatsApp encrypts a status for the devices in statusJidList and for nobody else, so the list is not a filter on
// top of everybody - an empty one is a status no one can open, with no error to show for it.
{
  const bot = new m.default({ account: 1, number: ME, dataDir: HERE });
  let seen = null;
  bot.sock = { async sendMessage(jid, content, opts) { seen = { jid, content, opts }; return {}; } };
  const out = await bot.postStatus("at the beach", "", [THEM, "not-a-jid", THEM, GROUP]);
  check("it goes up as a status", out.ok === true && seen && seen.jid === "status@broadcast");
  check("for the people given, each once", seen && seen.opts.statusJidList.length === 1
        && seen.opts.statusJidList[0] === THEM, JSON.stringify(seen && seen.opts));
  check("never to a group, which is not where a status goes",
        seen && !seen.opts.statusJidList.some((j) => j.endsWith("@g.us")));
  check("and what it says is on it", seen && seen.content.text === "at the beach");
  seen = null;
  const none = await bot.postStatus("nobody is listening", "", []);
  check("with nobody to put it up for, it says so instead of putting up one nobody can read",
        none.ok === false && !seen, JSON.stringify(none));
}

console.log("\n== its login is a folder of keys ==");
const WhatsAppBot = m.default;
const bot = new WhatsAppBot({ account: 1, number: "447711111111", dataDir: path.join(HERE, "nowhere") });
check("named after the number it was linked as",
      path.basename(bot.authDir()) === "whatsapp-447711111111-auth");
check("and it knows it has none", bot.linked() === false);
const src = fs.readFileSync(BOT, "utf8");
check("and baileys is only reached for inside a connection, which is why none of the above needed it installed",
      !/^\s*import .*["']baileys["']/m.test(src) && /await import\("baileys"\)/.test(src));

console.log(`\n${pass} passed, ${failed.length} failed`);
process.exitCode = failed.length ? 1 : 0;
