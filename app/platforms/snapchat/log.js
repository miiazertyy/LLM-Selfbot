// platforms/snapchat/log.js
// Premium, cohesive console logging for the Snapchat side - mirrors the Python
// logger's style (dim timestamps + Snapchat-gold accent) so the shared window
// looks like one clean app instead of two noisy processes.

const C = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[38;2;120;120;130m",
  gold: "\x1b[38;2;255;196;37m",
  goldDim: "\x1b[38;2;191;143;18m",
  white: "\x1b[38;2;235;235;235m",
  red: "\x1b[38;2;235;87;87m",
};

// Lazy so it reflects SNAP_DEBUG from .env (loaded after this module is imported).
function isVerbose() {
  return ["1", "true", "yes", "on"].includes(String(process.env.SNAP_DEBUG || "").toLowerCase());
}

function ts() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${C.dim}${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${C.reset}`;
}

export const log = {
  // High-level milestone (gold gear), always shown.
  sys: (m) => console.log(`${ts()} ${C.gold}⚙${C.reset} ${m}`),
  // Success (gold check), always shown.
  ok: (m) => console.log(`${ts()} ${C.gold}✓${C.reset} ${m}`),
  // Secondary / routine info, dimmed - always shown but quiet.
  dim: (m) => console.log(`${ts()} ${C.dim}· ${m}${C.reset}`),
  // Non-fatal notice, dimmed so it doesn't shout.
  warn: (m) => console.log(`${ts()} ${C.goldDim}⚠${C.reset} ${C.dim}${m}${C.reset}`),
  // Error (red cross).
  err: (ctx, m = "") =>
    console.log(`${ts()} ${C.red}✗ ${ctx}${C.reset}${m ? ` ${C.dim}${m}${C.reset}` : ""}`),
  // Verbose, only printed when SNAP_DEBUG is on (login internals, selectors…).
  trace: (m) => {
    if (isVerbose()) console.log(`${ts()} ${C.dim}  ${m}${C.reset}`);
  },
  isVerbose,
  C,
};

function _stringify(a) {
  if (typeof a === "string") return a;
  if (a && a.message) return a.message; // Error
  try { return String(a); } catch { return ""; }
}

// Noisy internals (login steps, selector probing, version banner) - hidden
// unless SNAP_DEBUG is on, so the console reads like clean app output.
const _NOISE =
  /^(trying selector|waiting for|found (username|password|chat input)|entering username|clicked submit|password field filled|checking for|clicked 'not now'|cookies set|snapchat for web build|version v|⚠️\s*warning|detected current version|some (methods|features)|if you encounter|if the problem|consider raising|✅ found|opening snap|snap screenshot saved|full-page snap|candidates:|snap cue present)/i;

const _SUCCESS = /✅|✓|👥|📸|🎤|\bsent\b|\bready\b|logged in successfully|captured|accepted|saved \d+ cookie/i;
const _SOFT =
  /giving up|wasn'?t visible|not in the visible|couldn'?t|skipped|could not|timed out|suppressed|no saved cookies|dismissed cookie|already logged in|disabled/i;
const _ERR = /\b(error|failed|fatal)\b|^✗/i;

/**
 * Reformat all console output from the Snapchat runner/SnapBot into one cohesive
 * premium style: dim timestamp + the message, colored by meaning, with the
 * legacy "[Snap]"/"[SnapBot]" prefixes stripped and verbose login noise hidden.
 * Call once at startup.
 */
export function patchConsole() {
  const orig = {
    log: console.log.bind(console),
    warn: console.warn.bind(console),
    error: console.error.bind(console),
  };

  const fmt = (args, kind) => {
    let msg = args
      .map(_stringify)
      .join(" ")
      .replace(/^\s*\[(snapbot|opensnap|capturesnap|snap)\]\s*/i, "")
      .trim();
    if (!msg) return null;
    // Test noise against an emoji-stripped copy so a leading ✅/📸 doesn't dodge it.
    const bare = msg.replace(/^[\s✅✓📸🎤👥⚠✗·‍️]+/, "").trim();
    if (!isVerbose() && _NOISE.test(bare)) return null; // suppress chatter

    let color = C.white;
    if (kind === "error" || _ERR.test(msg)) color = C.red;
    else if (_SUCCESS.test(msg)) color = C.gold;
    else if (kind === "warn" || _SOFT.test(msg)) color = C.dim;

    return `${ts()} ${color}${msg}${C.reset}`;
  };

  console.log = (...a) => { const s = fmt(a, "log"); if (s !== null) orig.log(s); };
  console.warn = (...a) => { const s = fmt(a, "warn"); if (s !== null) orig.warn(s); };
  console.error = (...a) => { const s = fmt(a, "error"); if (s !== null) orig.error(s); };
}

