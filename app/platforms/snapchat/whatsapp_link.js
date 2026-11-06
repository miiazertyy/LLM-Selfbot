/**
 * Link a WhatsApp number to this app, the way a second device is linked.
 *
 * Two ways, and WhatsApp allows exactly one of them per connection:
 *   - a pairing code: we ask for one for a number, WhatsApp gives eight characters, and a person types them into
 *     WhatsApp on the phone (Linked devices, Link with phone number). No camera.
 *   - a QR code: WhatsApp gives a string, the panel draws it, the phone's camera reads it. WhatsApp replaces it
 *     every twenty seconds or so, and each new one is sent on.
 *
 * Either way it ends with WhatsApp handing over a set of keys, which Baileys writes into the folder it was given.
 * Those keys ARE the login from then on; Python files them under the number (app/platforms/whatsapp/link.py).
 *
 * Talks to Python in JSON lines on stdout, one object per line: { detail }, { code }, { qr },
 * { linked, number, name }, { error }.
 */
import fs from "fs";
import { agentFor } from "./runner_core.js";

const AUTH = process.env.WHATSAPP_LINK_AUTH || "";
const WAY = (process.env.WHATSAPP_LINK_WAY || "code").toLowerCase() === "qr" ? "qr" : "code";
const NUMBER = String(process.env.WHATSAPP_LINK_NUMBER || "").replace(/\D/g, "");
const TIMEOUT_MS = Number(process.env.WHATSAPP_LINK_TIMEOUT_MS || 300000) || 300000;

function say(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

let settled = false;
let sock = null;

function finish(result) {
  if (settled) return;
  settled = true;
  (async () => {
    // Closed properly, so Baileys has written the last of the keys before Python moves the folder.
    try { sock?.end(undefined); } catch { /* going away anyway */ }
    await new Promise((r) => setTimeout(r, 600));
    say(result);
    process.exit(result.linked ? 0 : 1);
  })();
}

/** The number this app ended up linked as, out of the id WhatsApp gives its own side of the connection. */
function ownNumber(me) {
  const id = String(me?.id || "");
  const digits = id.split(":")[0].split("@")[0].replace(/\D/g, "");
  return digits.length >= 7 ? digits : "";
}

try {
  if (!AUTH) throw new Error("nowhere to put the keys");
  if (WAY === "code" && !NUMBER) throw new Error("a pairing code needs the number it is for");
  fs.mkdirSync(AUTH, { recursive: true });

  const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } =
    await import("baileys");

  say({ detail: "Asking WhatsApp" });
  const { state, saveCreds } = await useMultiFileAuthState(AUTH);
  // The protocol version WhatsApp Web is on today: asked for rather than pinned, because a stale one is refused.
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

  const agent = await agentFor(process.env.WHATSAPP_PROXY);
  sock = makeWASocket({
    auth: state,
    version,
    ...(agent ? { agent, fetchAgent: agent } : {}),
    // A pairing code and a QR are mutually exclusive: asking for a code means never printing one.
    printQRInTerminal: false,
    browser: ["LLMSelfbot", "Desktop", "1.0.0"],
    syncFullHistory: false,
    markOnlineOnConnect: false,
  });
  sock.ev.on("creds.update", saveCreds);

  setTimeout(() => finish({ error: "Timed out waiting for the link. Nothing was saved." }), TIMEOUT_MS);

  let asked = false;
  sock.ev.on("connection.update", async (up) => {
    const { connection, lastDisconnect, qr } = up;
    if (qr && WAY === "qr") say({ qr });
    // The code is asked for once, after the connection is open enough to ask on.
    if (!asked && WAY === "code" && !sock.authState.creds.registered) {
      asked = true;
      try {
        const code = await sock.requestPairingCode(NUMBER);
        say({ code: String(code || "").replace(/(.{4})(.+)/, "$1-$2") });
      } catch (e) {
        finish({ error: `WhatsApp would not give a code for that number: ${e.message}` });
      }
    }
    if (connection === "open") {
      const me = sock.user || {};
      const number = ownNumber(me) || NUMBER;
      if (!number) {
        finish({ error: "WhatsApp linked it, but would not say which number it is." });
        return;
      }
      finish({ linked: true, number, name: String(me.name || me.verifiedName || "") });
      return;
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (settled) return;
      // Baileys reconnects itself through these; a logout or a refusal is the end of it.
      if (code === DisconnectReason?.loggedOut) {
        finish({ error: "WhatsApp refused the link. Start again." });
      } else if (code === DisconnectReason?.restartRequired) {
        say({ detail: "WhatsApp asked for a restart of the connection" });
      } else if (code === 401 || code === 403) {
        finish({ error: "WhatsApp refused this device." });
      }
    }
  });
} catch (err) {
  const why = /Cannot find (module|package)/i.test(String(err && err.message))
    ? "WhatsApp's package is not installed yet. Install it from Settings, WhatsApp."
    : `Could not start the link: ${err.message}`;
  say({ error: why });
  // Nothing was opened, so nothing to close.
  process.exit(1);
}

// Keep the process alive while the connection does its work; finish() is what ends it.
process.stdin.resume();
