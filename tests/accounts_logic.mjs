/**
 * What an account card says about an account, for every state it can be in.
 * Runs the real webui/src/lib/accounts/condition.ts under Node.
 */
const c = await import("../webui/src/lib/accounts/condition.ts");

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  [" + detail + "]"}`);
  ok ? pass++ : fail++;
};

const discord = { id: "discord_1", platform: "discord", index: 1, token_set: true };
const snap = { id: "snapchat_1", platform: "snapchat", index: 1, username: "maya", password_set: true };
const rt = (over = {}) => ({ id: "discord_1", platform: "discord", account: 1, target: 1, state: "running",
                             pid: 1, restarts: 0, uptime: 60, enabled: true, ...over });
const live = (over = {}) => ({ live: true, paused: false, presence: "online", ...over });

// ── Cannot run ───────────────────────────────────────────────────────────────
let k = c.condition({ ...discord, token_set: false }, rt({ state: "stopped" }));
check("no token: not set up, with a way to add it", k.label === "Not set up" && k.alert?.action?.kind === "edit", JSON.stringify(k));
check("and Start is not offered", k.canStart === false);
k = c.condition({ ...snap, password_set: false }, undefined);
check("a Snapchat login missing its password says so", /password/.test(k.alert?.text ?? ""), k.alert?.text);

k = c.condition(discord, rt({ state: "stopped", enabled: false }));
check("platform switched off: says where the switch is",
      k.label === "Switched off" && k.alert?.action?.kind === "settings" && k.alert.action.to === "app/services", JSON.stringify(k.alert));
check("and does not offer a Start that cannot work", !k.canStart);

// ── Went wrong ───────────────────────────────────────────────────────────────
k = c.condition(discord, rt({ state: "crashing", restarts: 3, retry_in: 40,
  last_error: { text: "15:36:11 ✗ Login: Improper token has been passed.", ts: 1 } }));
check("crashing: a red card that says why", k.tone === "bad" && k.alert?.tone === "bad", JSON.stringify(k));
check("the reason has the log's time and glyph trimmed off",
      k.alert.text.startsWith("Login: Improper token"), k.alert.text);
check("and says when it tries again", /Trying again in 40s/.test(k.alert.text), k.alert.text);
check("Stop and Restart still apply to a crashing worker", k.running === true);

k = c.condition(discord, rt({ state: "stopped", gave_up: true, restarts: 11 }));
check("gave up: not the same as stopped on purpose", k.label === "Gave up" && k.tone === "bad", k.label);
check("and can be started again", k.canStart);

// ── Stopped, starting ────────────────────────────────────────────────────────
k = c.condition(discord, rt({ state: "stopped", uptime: 0 }));
check("stopped: quiet, startable, no alarm", k.label === "Stopped" && k.canStart && !k.alert && !k.live);
k = c.condition(discord, rt({ state: "starting" }));
check("starting: shown as in progress", k.busy && k.label === "Starting");

// ── Up ───────────────────────────────────────────────────────────────────────
k = c.condition(discord, rt(), live());
check("running and answering: live, replying", k.live && k.reachable && k.line === "Replying to messages", JSON.stringify(k));
k = c.condition(discord, rt(), live({ presence: "dnd" }));
check("the label is the presence Discord shows", k.label === "Do Not Disturb", k.label);
k = c.condition(discord, rt(), live({ presence: "invisible", night: true }));
check("invisible at night is the schedule, and says so", /night/.test(k.line), k.line);
k = c.condition(discord, rt(), live({ paused: true }));
check("paused: amber, not replying, not 'live'", k.paused && k.tone === "warn" && !k.live, JSON.stringify(k));
k = c.condition(discord, rt(), undefined);
check("up but not answering the panel yet: still up, controls held back", k.running && !k.reachable && k.tone === "good");
k = c.condition(discord, rt(), { live: false, reason: "the account is not running" });
check("a failed status answer is not taken as paused", !k.paused);

// ── Snapchat's own report beats "the process exists" ─────────────────────────
const srt = (state, detail = "", stale = false) =>
  rt({ id: "snapchat_1", platform: "snapchat", target: "snap", snap: { state, detail, at: 1, stale } });
k = c.condition(snap, srt("awaiting-verification", "Check your email"), live());
check("awaiting verification: amber, with Snapchat's own words", k.label === "Verify login" && k.alert?.text === "Check your email", JSON.stringify(k));
k = c.condition(snap, srt("logged-out", "Login failed. Check the credentials."), live());
check("refused login: points at the login", k.tone === "bad" && k.alert?.action?.kind === "edit", JSON.stringify(k.alert));
k = c.condition(snap, srt("logged-out", "Logged out. Trying again in 5 min."), live());
check("signed out and retrying: points at the log instead", k.alert?.action?.kind === "logs", JSON.stringify(k.alert));
k = c.condition(snap, srt("ready", "Running, but Snapchat changed its page: X no longer found."), live());
check("page drift is a warning on a working account", k.live && k.alert?.tone === "warn", JSON.stringify(k));
k = c.condition(snap, srt("awaiting-verification", "old", true), live());
check("a stale report is not presented as current", k.label === "Online", k.label);

// ── The dot ──────────────────────────────────────────────────────────────────
check("dot: Discord shows its real presence", c.presenceOf(discord, rt(), live({ presence: "idle" })) === "idle");
check("dot: stopped is offline", c.presenceOf(discord, rt({ state: "stopped" }), live()) === "offline");
check("dot: Snapchat waiting on a login is not green",
      c.presenceOf(snap, srt("awaiting-verification"), live()) === "idle");
check("dot: Snapchat signed in is", c.presenceOf(snap, srt("ready"), live()) === "online");

// ── Small words ──────────────────────────────────────────────────────────────
check("attention counts cards with something to do",
      c.attentionCount([c.condition(discord, rt(), live()), c.condition(discord, rt({ state: "crashing" }))]) === 1);
check("uptime reads naturally", c.uptime(11600) === "3h 13m" && c.uptime(200000) === "2d 7h" && c.uptime(90) === "1m",
      [c.uptime(11600), c.uptime(200000), c.uptime(90)].join());
check("ago reads naturally", c.ago(1000, 1010) === "just now" && c.ago(0, 300) === "5 min ago"
      && c.ago(0, 86400 * 1.2) === "yesterday" && c.ago(0, 86400 * 3) === "3 days ago");

console.log(`\n${pass} passed, ${fail} failed`);
process.exitCode = fail ? 1 : 0;
