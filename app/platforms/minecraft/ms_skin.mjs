/**
 * A Microsoft account's Minecraft skin, changed from the panel: a picture put on it (64 by 64, or the old 64 by 32,
 * as Minecraft takes them), classic or slim arms, or its skin taken back off so it wears the game's default again.
 * Run by app/platforms/minecraft/skin_change.py, written beside mindcraft by worker.sync_runner() so it finds
 * mindcraft's packages.
 *
 * It uses the login the account already has, the one its bot plays with (prismarine-auth, the Nintendo Switch title,
 * the "live" flow, the nmp-cache folder, keyed by its Minecraft name: exactly as ms_signin.mjs leaves it). It never
 * starts a sign-in of its own: if that login has run out, it says so and stops.
 *
 *   LSB_MC_NAME        the name it was added under, which its login is kept under (not always the one it plays as)
 *   LSB_SKIN_FILE      the PNG to put on it, or
 *   LSB_SKIN_RESET=1   to take its skin off, or
 *   LSB_SKIN_KEEP=1    to put the skin it has back on with other arms (Minecraft changes arms only with a skin);
 *                      that skin is written to LSB_SKIN_OUT, for its card
 *   LSB_SKIN_VARIANT   "classic" or "slim"
 *
 * It says what happened as one line of JSON: {"done": true, "url", "variant", "id"}, or {"error"}.
 */
import { createRequire } from "module";
import fs from "fs";
import path from "path";

const MC_DIR = process.env.LSB_MC_DIR || process.cwd();
const require = createRequire(path.join(MC_DIR, "package.json"));
const say = (o) => process.stdout.write(`${JSON.stringify(o)}\n`);
const API = "https://api.minecraftservices.com/minecraft/profile";
const SIGN_IN_AGAIN = "Its Microsoft sign-in has run out. Sign it in again from its card, then try again.";

async function main() {
  const name = String(process.env.LSB_MC_NAME || "").trim();
  if (!/^\w{3,16}$/.test(name)) {
    say({ error: "This account has no Minecraft name yet." });
    return;
  }
  const { Authflow, Titles } = require("prismarine-auth");
  const folder = path.join(require("minecraft-folder-path"), "nmp-cache");
  const flow = new Authflow(name, folder,
    { authTitle: Titles.MinecraftNintendoSwitch, deviceType: "Nintendo", flow: "live" },
    // Asked for a code: there is no login to use. Nobody is there to type one, so it stops here.
    () => {
      say({ error: SIGN_IN_AGAIN });
      process.exit(2);
    });
  let token = "";
  try {
    ({ token } = await flow.getMinecraftJavaToken({ fetchProfile: false }));
  } catch (e) {
    say({ error: `Microsoft did not let it in: ${String((e && e.message) || e).slice(0, 160)}` });
    return;
  }
  const headers = { Authorization: `Bearer ${token}` };
  let res;
  try {
    if (process.env.LSB_SKIN_RESET === "1") {
      res = await fetch(`${API}/skins/active`, { method: "DELETE", headers });
    } else {
      let png;
      if (process.env.LSB_SKIN_KEEP === "1") {
        // Its own skin, as Minecraft has it on this very account: never one looked up by a name.
        const mine = await (await fetch(API, { headers })).json().catch(() => ({}));
        const now = (Array.isArray(mine.skins) ? mine.skins : []).find((s) => s && s.state === "ACTIVE");
        if (!now || !now.url) {
          say({ error: "It has no skin of its own yet. Choose one first." });
          return;
        }
        const got = await fetch(String(now.url).replace(/^http:/, "https:"));
        if (!got.ok) {
          say({ error: "Its skin could not be fetched from Minecraft. Try again in a moment." });
          return;
        }
        png = Buffer.from(await got.arrayBuffer());
        if (process.env.LSB_SKIN_OUT) fs.writeFileSync(process.env.LSB_SKIN_OUT, png);
      } else {
        png = fs.readFileSync(String(process.env.LSB_SKIN_FILE || ""));
      }
      const form = new FormData();
      form.append("variant", process.env.LSB_SKIN_VARIANT === "slim" ? "slim" : "classic");
      form.append("file", new Blob([png], { type: "image/png" }), "skin.png");
      res = await fetch(`${API}/skins`, { method: "POST", headers, body: form });
    }
  } catch (e) {
    say({ error: `Minecraft could not be reached: ${String((e && e.message) || e).slice(0, 160)}` });
    return;
  }
  if (!res.ok) {
    say({ error: res.status === 400 ? "Minecraft would not take that picture. A skin is a 64 by 64 PNG."
      : res.status === 401 || res.status === 403 ? SIGN_IN_AGAIN
      : res.status === 429 ? "Too many changes at once. Wait a minute, then try again."
      : `Minecraft said no (${res.status}).` });
    return;
  }
  let profile = {};
  try { profile = await res.json(); } catch { /* changed all the same */ }
  const active = (Array.isArray(profile.skins) ? profile.skins : []).find((s) => s && s.state === "ACTIVE") || {};
  say({ done: true, url: String(active.url || ""), variant: String(active.variant || "").toLowerCase(),
        id: String(profile.id || "") });
}

main().then(() => { process.exitCode = 0; }, (e) => {
  say({ error: `The skin could not be changed: ${String((e && e.message) || e).slice(0, 160)}` });
  process.exitCode = 1;
});
