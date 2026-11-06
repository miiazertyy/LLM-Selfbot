/**
 * The six digits an authentication app would show, from a 2FA key (RFC 6238).
 *
 * Only so that adding an Instagram account can show the code the key it was
 * given produces: the person checks it against their own authenticator and
 * knows the key is right before the account ever tries to sign in. The app
 * itself makes the code it signs in with on the Node side
 * (app/platforms/snapchat/instagrambot.js), never here.
 *
 * The key never leaves the page: this runs in the browser, over WebCrypto.
 */

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** A 2FA key as Instagram shows it ("G54M E4E3 T37W 6IXH") without its spaces; "" when it is not a base32 key. */
export function cleanKey(key: string | null | undefined): string {
  const k = String(key ?? "").toUpperCase().replace(/[\s-]/g, "").replace(/=+$/, "");
  return /^[A-Z2-7]{16,64}$/.test(k) ? k : "";
}

/** A base32 key as bytes; null when it is not one. */
export function keyBytes(key: string): Uint8Array | null {
  const clean = cleanKey(key);
  if (!clean) return null;
  const out: number[] = [];
  let bits = 0;
  let value = 0;
  for (const ch of clean) {
    value = (value << 5) | ALPHABET.indexOf(ch);
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return new Uint8Array(out);
}

/** Seconds the current code has left: one typed in its last moments may be stale by the time it lands. */
export function secondsLeft(at: number = Date.now(), step = 30): number {
  return step - (Math.floor(at / 1000) % step);
}

/** The code for this moment: HMAC-SHA1 over the 30-second step, six digits. "" for a key that is not one. */
export async function totp(key: string, at: number = Date.now(), step = 30, digits = 6): Promise<string> {
  const secret = keyBytes(key);
  if (!secret || !secret.length || !globalThis.crypto?.subtle) return "";
  const counter = Math.floor(at / 1000 / step);
  const msg = new Uint8Array(8);
  // The step as a 64-bit number, biggest byte first.
  new DataView(msg.buffer).setUint32(0, Math.floor(counter / 2 ** 32));
  new DataView(msg.buffer).setUint32(4, counter % 2 ** 32);
  try {
    const algo = { name: "HMAC", hash: "SHA-1" };
    const material = await crypto.subtle.importKey("raw", secret as BufferSource, algo, false, ["sign"]);
    const mac = new Uint8Array(await crypto.subtle.sign("HMAC", material, msg as BufferSource));
    const off = mac[mac.length - 1] & 0x0f;
    const bin = ((mac[off] & 0x7f) << 24) | (mac[off + 1] << 16) | (mac[off + 2] << 8) | mac[off + 3];
    return String(bin % 10 ** digits).padStart(digits, "0");
  } catch {
    return "";
  }
}
