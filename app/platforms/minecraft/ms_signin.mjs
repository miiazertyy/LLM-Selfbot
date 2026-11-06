/**
 * A Microsoft sign-in for a Minecraft account, done from the panel before the account exists: Microsoft's own code
 * (typed at microsoft.com/link), and then the account's real Minecraft name - so nobody has to type a name that
 * Microsoft already knows. Run by app/platforms/minecraft/ms_signin.py, written beside mindcraft by
 * worker.sync_runner() so it finds mindcraft's packages.
 *
 * It signs in exactly the way mineflayer does when the account plays (minecraft-protocol's microsoftAuth.js:
 * prismarine-auth, the Nintendo Switch title, the "live" flow, the nmp-cache folder), so the login it leaves behind
 * is the one the bot finds, and the bot never shows a code of its own. Mineflayer looks a login up by the name it is
 * given, and the real name is only known once signed in: so the login is made under a temporary key and renamed to
 * the real name at the end, with prismarine-auth's own hash, which is the one mineflayer will use.
 *
 * It says what happens as lines, one JSON object each:
 *   {"code", "uri", "link", "expires"}   once Microsoft has a code for it
 *   {"done": true, "name", "uuid"}       signed in, and the Minecraft name that comes with the account
 *   {"error"}                            and why not
 */
import { createRequire } from "module";
import fs from "fs";
import path from "path";

const MC_DIR = process.env.LSB_MC_DIR || process.cwd();
const require = createRequire(path.join(MC_DIR, "package.json"));
const say = (o) => process.stdout.write(`${JSON.stringify(o)}\n`);

// Every cache prismarine-auth may write for one login (its MicrosoftAuthFlow CACHE_IDS).
const CACHE_IDS = ["msal", "live", "sisu", "xbl", "bed", "mca", "mcs", "pfb"];

async function main() {
  const { Authflow, Titles } = require("prismarine-auth");
  let createHash;
  try {
    ({ createHash } = require("prismarine-auth/src/common/Util"));
  } catch {
    // Its own, if a later version moved it: the same sha1, cut to six, it has always used.
    const crypto = await import("crypto");
    createHash = (s) => crypto.createHash("sha1").update(s ?? "", "binary").digest("hex").substr(0, 6);
  }
  const folder = path.join(require("minecraft-folder-path"), "nmp-cache");
  fs.mkdirSync(folder, { recursive: true });

  // Chosen by ms_signin.py, so it can clear this sign-in's files away even if it is stopped before the end (a few
  // empty ones are made the moment it starts). Letters and digits, so it is never anyone's real name.
  const key = (process.env.LSB_SIGNIN_KEY || `lsbsignin${Math.random().toString(36).slice(2, 10)}`).trim();
  const own = (h) => CACHE_IDS.map((id) => path.join(folder, `${h}_${id}-cache.json`));
  const clearKey = () => { for (const f of own(createHash(key))) { try { fs.unlinkSync(f); } catch { /* none */ } } };
  const flow = new Authflow(key, folder,
    { authTitle: Titles.MinecraftNintendoSwitch, deviceType: "Nintendo", flow: "live" },
    (r) => say({ code: r.user_code, uri: r.verification_uri, expires: r.expires_in,
                 // Microsoft's own link with the code already in it: one click instead of copying it across.
                 link: `https://www.microsoft.com/link?otc=${encodeURIComponent(r.user_code)}` }));
  let profile;
  try {
    ({ profile } = await flow.getMinecraftJavaToken({ fetchProfile: true }));
  } catch (e) {
    clearKey();
    const why = String((e && e.message) || e);
    say({ error: /not found|does not own|entitlement/i.test(why)
      ? "This Microsoft account does not have Minecraft: Java Edition."
      : /expired|timed? ?out/i.test(why) ? "The code ran out before it was used. Try again."
      : `Microsoft did not let it in: ${why.slice(0, 160)}` });
    return;
  }
  if (!profile || !profile.name) {
    clearKey();
    say({ error: "This Microsoft account has no Minecraft profile yet. Open Minecraft once and pick a name." });
    return;
  }
  // Filed under the real name, which is the name the account will play as and mineflayer will look it up by.
  const from = createHash(key), to = createHash(profile.name);
  for (const id of CACHE_IDS) {
    const a = path.join(folder, `${from}_${id}-cache.json`);
    if (fs.existsSync(a)) fs.renameSync(a, path.join(folder, `${to}_${id}-cache.json`));
  }
  say({ done: true, name: profile.name, uuid: profile.id || "" });
}

main().then(() => { process.exitCode = 0; }, (e) => {
  say({ error: `The sign-in could not start: ${String((e && e.message) || e).slice(0, 160)}` });
  process.exitCode = 1;
});
