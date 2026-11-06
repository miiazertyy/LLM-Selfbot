/**
 * The iMessage platform's BlueBubbles side (app/platforms/snapchat/bluebubbles.js), under Node: who a chat is in the
 * app, tapbacks, what a message is, and the live feed against a real socket.io 4 server (mindcraft's own copy, when
 * Minecraft support is installed: the version BlueBubbles serves).
 */
import fs from "fs";
import os from "os";
import path from "path";
import http from "http";
import { createRequire } from "module";
import {
  serverUrl, personId, addressOf, groupId, chatIdOf, guidParts, sameAddress, TAPBACKS, tapbackName, tapbackOf,
  tapbackTarget, readMessage, describe, logBody, mediaKind, appOf, liveFeed, BlueBubbles,
} from "../app/platforms/snapchat/bluebubbles.js";

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// ── The server's address ─────────────────────────────────────────────────────
check("an address as people paste one", serverUrl("192.168.1.20:1234") === "http://192.168.1.20:1234"
      && serverUrl("https://abc.trycloudflare.com/") === "https://abc.trycloudflare.com"
      && serverUrl("https://x.ngrok.io/api/v1/ping?password=a") === "https://x.ngrok.io", serverUrl("192.168.1.20:1234"));
check("the Mac's own address typed bare: BlueBubbles' port (1234)", serverUrl("192.168.1.20") === "http://192.168.1.20:1234"
      && serverUrl("Alicias-MacBook.local") === "http://alicias-macbook.local:1234" && serverUrl("macbook") === "http://macbook:1234",
      [serverUrl("192.168.1.20"), serverUrl("Alicias-MacBook.local"), serverUrl("macbook")]);
check("a domain typed bare: https, as tunnels serve it", serverUrl("abc.trycloudflare.com") === "https://abc.trycloudflare.com",
      serverUrl("abc.trycloudflare.com"));
check("a port or a scheme typed: as typed", serverUrl("192.168.1.20:80") === "http://192.168.1.20"
      && serverUrl("http://192.168.1.20") === "http://192.168.1.20" && serverUrl("home.ddns.net:1234") === "http://home.ddns.net:1234",
      [serverUrl("192.168.1.20:80"), serverUrl("http://192.168.1.20"), serverUrl("home.ddns.net:1234")]);
check("and nothing usable as nothing", serverUrl("") === "" && serverUrl("ftp://x") === "" && serverUrl("   ") === "");

// ── Who a chat is ────────────────────────────────────────────────────────────
check("a phone number by its digits", personId("+33 6 12 34 56 78") === "im_p33612345678" && personId("0612345678") === "im_0612345678");
check("an email, every character kept", personId("Theo.Wav@iCloud.com") === "im_theo_2e_wav_40_icloud_2e_com", personId("Theo.Wav@iCloud.com"));
check("and read back exactly", addressOf("im_p33612345678") === "+33612345678"
      && addressOf(personId("a_b-c.d@x.fr")) === "a_b-c.d@x.fr" && addressOf("im_0612345678") === "0612345678");
check("ids the app takes (letters, digits, _ and -, 80 at most)",
      [personId("+15551234567"), personId("someone.with.a.long.name@example.co.uk"), personId("x".repeat(90) + "@y.com")]
        .every((id) => /^[A-Za-z0-9_-]{1,80}$/.test(id)));
check("a group by its chat's number", groupId({ guid: "iMessage;+;chat123456789012345678", chatIdentifier: "chat123456789012345678" })
      === "img_123456789012345678");
check("a person's iMessage and SMS chats are the same person",
      chatIdOf({ guid: "iMessage;-;+15551234567" }) === chatIdOf({ guid: "SMS;-;+15551234567" })
      && chatIdOf({ guid: "any;-;+15551234567" }) === "im_p15551234567");
check("a group is a group, by its guid or its style", chatIdOf({ guid: "iMessage;+;chat99999" }).startsWith("img_")
      && chatIdOf({ guid: "x", style: 43, chatIdentifier: "chat4242" }) === "img_4242");
check("a guid's parts", same(guidParts("SMS;-;+1555"), { service: "SMS", group: false, ident: "+1555" }));
check("the same number however it is written", sameAddress("+33 6 12 34 56 78", "0612345678")
      && !sameAddress("+33612345678", "+33612345679") && sameAddress("A@B.com", "a@b.com") && !sameAddress("", ""));

// ── Tapbacks ─────────────────────────────────────────────────────────────────
check("the six, by emoji and by name", Object.keys(TAPBACKS).length === 6 && tapbackName("❤️") === "love"
      && tapbackName("😂") === "laugh" && tapbackName("‼️") === "emphasize" && tapbackName("question") === "question");
check("and the near ones a persona picks", tapbackName("🤣") === "laugh" && tapbackName("💕") === "love"
      && tapbackName("👍🏽") === "like" && tapbackName("🔥") === "");
check("one given, one taken back", same(tapbackOf("love"), { name: "love", emoji: "❤️", removed: false })
      && tapbackOf("-laugh").removed && tapbackOf("3001").removed === true && tapbackOf("0") === null && tapbackOf(null) === null);
check("an emoji one (iOS 18), its emoji out of its words", tapbackOf("2006", "Reacted 🔥 to “hey”")?.emoji === "🔥");
check("what it is on", tapbackTarget("p:0/ABC-123") === "ABC-123" && tapbackTarget("bp:XYZ") === "XYZ" && tapbackTarget("Q") === "Q");

// ── What a message is ────────────────────────────────────────────────────────
const dm = { guid: "iMessage;-;+15551234567", style: 45, chatIdentifier: "+15551234567", displayName: "" };
const grp = { guid: "iMessage;+;chat777777", style: 43, chatIdentifier: "chat777777", displayName: "Friends" };
const text = readMessage({ guid: "G1", text: "hey ￼ you", isFromMe: false, dateCreated: 1700000000000,
                           handle: { address: "+15551234567", service: "iMessage" }, chats: [dm] });
check("words, with nothing left where an attachment sat", text.text === "hey you", text.text);
check("its chat and its sender", text.chatGuid === dm.guid && text.address === "+15551234567" && !text.group && !text.mine);
const photo = readMessage({ guid: "G2", text: "￼", chats: [dm], handle: { address: "+15551234567" },
                            attachments: [{ guid: "A1", mimeType: "image/heic", transferName: "IMG_0001.HEIC" }] });
check("a photo is a photo, HEIC too", photo.media[0]?.kind === "photo" && photo.text === "");
check("and said as one in the chat log", same(logBody(photo), { text: "[a photo]", kind: "photo" }));
const voice = readMessage({ guid: "G3", chats: [dm], isAudioMessage: true,
                            attachments: [{ guid: "A2", mimeType: "audio/x-caf", transferName: "Audio Message.caf", uti: "com.apple.coreaudio-format" }] });
check("a voice message", voice.media[0]?.kind === "voice" && voice.audio);
check("a sticker, a GIF, a file", mediaKind({ isSticker: true }) === "sticker" && mediaKind({ mimeType: "image/gif" }) === "gif"
      && mediaKind({ mimeType: "application/pdf", transferName: "a.pdf" }) === "file");
check("a link's preview is just the link", readMessage({ guid: "L", chats: [dm], text: "https://x.com",
      balloonBundleId: "com.apple.messages.URLBalloonProvider",
      attachments: [{ guid: "P", transferName: "x.pluginPayloadAttachment" }] }).media.length === 0);
check("an iMessage app's", appOf("com.apple.messages.MSMessageExtensionBalloonPlugin:0000000000:com.gamerdelights.gamepigeon.ext")
      === "a GamePigeon game");
const slam = readMessage({ guid: "G4", chats: [dm], text: "WHAT", expressiveSendStyleId: "com.apple.MobileSMS.expressivesend.impact" });
check("an effect, said for the persona", slam.effect === "Slam" && describe(slam) === "[sent with Slam] WHAT", describe(slam));
check("a reply in a thread, with what it answers", describe(readMessage({ guid: "G5", chats: [dm], text: "yes", threadOriginatorGuid: "G1" }),
      { quote: "you coming?" }) === '[replying to: "you coming?"] yes');
const tb = readMessage({ guid: "T1", chats: [dm], associatedMessageType: "love", associatedMessageGuid: "p:0/G1",
                         text: "Loved “hey you”", handle: { address: "+15551234567" } });
check("a tapback, and the message it is on", tb.tapback?.emoji === "❤️" && tb.tapback.target === "G1");
const ren = readMessage({ guid: "E1", chats: [grp], itemType: 2, groupTitle: "Best friends", text: "" });
check("a group's own news", ren.group && ren.event?.what === "renamed" && ren.event.title === "Best friends");
check("an edit and an unsend", readMessage({ guid: "X", dateEdited: 5 }).edited === 5
      && logBody(readMessage({ guid: "X", text: "gone", dateRetracted: 9 })).kind === "unsent");
check("a group member's message", readMessage({ guid: "G6", chats: [grp], text: "yo", handle: { address: "a@b.c" } }).group);

// ── REST, against a stand-in ─────────────────────────────────────────────────
const seenReq = [];
const rest = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  seenReq.push(`${req.method} ${u.pathname} ${u.searchParams.get("password")}`);
  res.setHeader("content-type", "application/json");
  if (u.searchParams.get("password") !== "pw") {
    res.statusCode = 401;
    res.end(JSON.stringify({ status: 401, message: "You are not authorized to access this resource",
                             error: { type: "Unauthorized", error: "Missing server password!" } }));
    return;
  }
  if (u.pathname === "/api/v1/ping") return res.end(JSON.stringify({ status: 200, message: "Ping received!", data: "pong" }));
  if (u.pathname === "/api/v1/message/react") {
    res.statusCode = 500;
    return res.end(JSON.stringify({ status: 500, message: "iMessage Error",
      error: { type: "iMessage Error", error: "Please make sure you have completed the setup for the Private API, and your helper is connected!" } }));
  }
  res.statusCode = 404;
  res.end(JSON.stringify({ status: 404, message: "Not found", error: { type: "Not Found", error: "nope" } }));
});
await new Promise((r) => rest.listen(0, "127.0.0.1", r));
const port = rest.address().port;
const good = new BlueBubbles({ url: `127.0.0.1:${port}`, password: "pw" });
check("the API answers, its password in the query", (await good.ping()) === "pong" && seenReq[0] === "GET /api/v1/ping pw");
let err = null;
try { await new BlueBubbles({ url: `127.0.0.1:${port}`, password: "nope" }).ping(); } catch (e) { err = e; }
check("a wrong password is said as one", err?.auth === true && err.status === 401, String(err?.message));
err = null;
try { await good.react({ chatGuid: "c", guid: "g", reaction: "love" }); } catch (e) { err = e; }
check("and what needs the Private API, as that", err?.privateApi === true, String(err?.message));
err = null;
try { await new BlueBubbles({ url: "127.0.0.1:1", password: "pw" }).ping(); } catch (e) { err = e; }
check("nothing there: unreachable, in words", err?.unreachable === true && /did not answer/.test(err.message), String(err?.message));
rest.close();

// ── The live feed, against socket.io itself ──────────────────────────────────
const mc = path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "LLMSelfbot", "mindcraft");
let SocketServer = null;
try { SocketServer = createRequire(path.join(mc, "package.json"))("socket.io").Server; } catch { /* not installed */ }
if (!SocketServer || typeof globalThis.WebSocket !== "function") {
  console.log("  (the live feed is not tried here: no socket.io to try it against, or no WebSocket in this Node)");
} else {
  const httpServer = http.createServer();
  const io = new SocketServer(httpServer, { allowEIO3: true, transports: ["websocket", "polling"], pingInterval: 300, pingTimeout: 400 });
  io.on("connection", (socket) => {
    const pass = socket.handshake.query?.password ?? socket.handshake.query?.guid;
    if (pass !== "pw") { socket.disconnect(); return; }
    setTimeout(() => socket.emit("new-message", { guid: "LIVE1", text: "hello live" }), 50);
  });
  await new Promise((r) => httpServer.listen(0, "127.0.0.1", r));
  const p2 = httpServer.address().port;
  const got = [], states = [];
  const feed = liveFeed(new BlueBubbles({ url: `127.0.0.1:${p2}`, password: "pw" }),
                        { onEvent: (n, d) => got.push([n, d?.guid]), onState: (s) => states.push(s) });
  await new Promise((r) => setTimeout(r, 1500));
  check("connected, and an event heard, by name with its data", feed.connected && same(got[0], ["new-message", "LIVE1"]),
        JSON.stringify({ got, states }));
  check("and kept alive through socket.io's pings", feed.connected && !states.includes("lost"), states.join(","));
  io.disconnectSockets(true);
  await new Promise((r) => setTimeout(r, 2600));
  check("let go of by the server once it held: lost and back, never said as a refused password",
        states.includes("lost") && !states.includes("refused") && states.filter((s) => s === "connected").length >= 2
        && feed.connected, states.join(","));
  feed.stop();
  const refused = [];
  const bad = liveFeed(new BlueBubbles({ url: `127.0.0.1:${p2}`, password: "nope" }), { onEvent: () => {}, onState: (s) => refused.push(s) });
  await new Promise((r) => setTimeout(r, 800));
  check("a wrong password: refused, and no event", refused.includes("refused") && !bad.connected, refused.join(","));
  bad.stop();
  io.close();
  httpServer.close();
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
