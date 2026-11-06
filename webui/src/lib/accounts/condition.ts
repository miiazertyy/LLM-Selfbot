/**
 * What an account is doing, in one place.
 *
 * The old page showed the supervisor's word for it in a pill - "running",
 * "stopped" - and nothing else. That word is about the process, not the
 * account: a Snapchat login stuck on a verification screen is "running", so is
 * a Discord account that has been paused for a day, and "stopped" covers both
 * "you stopped it" and "it crashed ten times and was given up on". The card
 * needs to say which, and what to do about it.
 *
 * Pure functions over the three things the panel knows about an account (its
 * saved login, the worker running it, and what the worker last said about
 * itself), so they run under Node in tests/accounts_logic.mjs.
 */

export type Slot = {
  id: string;
  platform: string;
  index: number;
  token_set?: boolean;
  proxy?: string;
  username?: string;
  password_set?: boolean;
  /** Instagram's and X's 2FA key, when it was given one: it then signs itself back in unaided. */
  totp_set?: boolean;
  /** X's: the email or phone on the account, which X asks for when it questions a login. No secret. */
  email?: string;
  /** Minecraft's: the server it joins, and how it signs in there ("offline" or "microsoft"). Not secrets. */
  host?: string;
  port?: string;
  auth?: string;
  /** iMessage's: the BlueBubbles Server on a Mac it reads through (its password is password_set), or "phone": an
   *  iPhone or iPad carries the messages itself, posting them to /relay/imessage/<relay> from a Shortcuts
   *  automation. */
  server?: string;
  relay?: string;
  /** Telegram's: the number it signed in with, and whether its sign-in and api_hash are stored. */
  phone?: string;
  api_id?: string;
  api_hash_set?: boolean;
  session_set?: boolean;
};

/** An iMessage account read through an iPhone or iPad rather than a Mac. */
export const viaPhone = (slot: Slot | undefined) => slot?.platform === "imessage" && slot.server === "phone";

export type SnapState = {
  state: string;
  detail: string;
  at: number;
  stale: boolean;
  /** Minecraft's: what it is doing in the game, as mindcraft last said (minecraft_runner.mjs reportGame). */
  game?: {
    doing?: string; health?: number | null; hunger?: number | null; players?: string[]; biome?: string;
    time?: string; pos?: number[]; server?: string;
  };
};

export type Runtime = {
  id: string;
  platform: string;
  account: number | null;
  target: string;
  state: string;
  pid: number | null;
  restarts: number;
  uptime: number;
  retry_in?: number | null;
  gave_up?: boolean;
  /** False when the whole platform is switched off in Settings. */
  enabled?: boolean;
  last_error?: { text: string; ts: number } | null;
  snap?: SnapState | null;
  /** What a browser account's runner says it is doing (Snapchat's, TikTok's or Instagram's): signing in, a check
   *  to solve, a code to type, ready. */
  web?: SnapState | null;
  // Recorded by the runner when it connects, so it survives a stop.
  username?: string;
  display_name?: string;
  avatar?: string;
  /** The profile banner, and the colour picked instead of one. */
  banner?: string;
  accent?: string;
};

export type Details = {
  live: boolean;
  reason?: string;
  paused?: boolean;
  mood?: string;
  active_channels?: number;
  ignored_users?: number;
  presence?: string;
  night?: boolean;
  latency_ms?: number | null;
  guilds?: number;
  friends?: number;
  /** A TikTok or Instagram account's own counts, as its profile shows them. */
  followers?: number;
  following?: number;
  likes?: number;
  videos?: number;
  posts?: number;
  /** An iMessage account's Mac, as its runner last said: BlueBubbles' address, its live feed, its Private API. */
  imessage?: {
    server?: string; live?: boolean; private_api?: boolean; helper?: boolean; account?: string; macos?: string;
    bluebubbles?: string;
  };
};

export type Tone = "good" | "warn" | "bad" | "muted" | "accent";

/** Something that needs doing, and the one button that does it. */
export type Alert = {
  tone: "warn" | "bad";
  title: string;
  text: string;
  /** `url` opens `to` outside the panel (the phone's own browser in the phone app). */
  action?: { kind: "edit" | "logs" | "settings" | "start" | "url"; label: string; to?: string };
};

export type Condition = {
  /** One or two words, for the pill. */
  label: string;
  tone: Tone;
  /** A short sentence under the name. */
  line: string;
  /** Doing its job right now: drawn lit, with the pulse. */
  live: boolean;
  /** Connecting, logging in: drawn as in progress. */
  busy: boolean;
  /** A worker exists that Stop and Restart would act on. */
  running: boolean;
  /** Start would work. */
  canStart: boolean;
  /** Pause, mood and the rest need an answering worker. */
  reachable: boolean;
  paused: boolean;
  alert?: Alert;
};

/** Whether a login has enough on it to be worth starting. */
export function ready(s: Slot): boolean {
  // A TikTok account is its signed-in browser profile: its handle is all it needs here.
  if (s.platform === "tiktok") return !!s.username;
  // And a Reddit account the same: it is signed in in a window, and the session stays in its profile. A password
  // may be saved afterwards so it can sign itself back in later, but nothing waits for one.
  if (s.platform === "reddit") return !!s.username;
  // A WhatsApp account is the number it was linked as: the keys its phone handed over are the login, and there
  // is nothing else to fill in.
  if (s.platform === "whatsapp") return !!s.username;
  // A Minecraft account is the name it plays as: an offline server needs nothing else, a Microsoft one signs in
  // through a code on its first run.
  if (s.platform === "minecraft") return !!s.username;
  // An iMessage account is a BlueBubbles server, its address and its password; or an iPhone, which needs nothing
  // here (its secret is made with it), only its shortcut made on the phone.
  if (s.platform === "imessage") return s.server === "phone" || !!(s.server && s.password_set);
  // A Telegram account is the sign-in it left behind: there is nothing else to fill in.
  if (s.platform === "telegram") return !!s.session_set;
  // Instagram and X keep the login and sign themselves in, so they need both halves, as Snapchat does.
  return s.platform === "discord" ? !!s.token_set : !!(s.username && s.password_set);
}

const PRESENCE: Record<string, string> = {
  online: "Online",
  idle: "Idle",
  dnd: "Do Not Disturb",
  invisible: "Invisible",
  offline: "Offline",
};

export function presenceName(p?: string): string {
  return PRESENCE[p || ""] ?? "Online";
}

export function platformName(p: string): string {
  if (p === "tiktok") return "TikTok";
  if (p === "instagram") return "Instagram";
  // The short one here: a card's title, where "X (Twitter)" would not fit.
  if (p === "x") return "X";
  if (p === "reddit") return "Reddit";
  if (p === "whatsapp") return "WhatsApp";
  if (p === "minecraft") return "Minecraft";
  if (p === "imessage") return "iMessage";
  return p === "snapchat" ? "Snapchat" : p === "discord" ? "Discord" : p[0].toUpperCase() + p.slice(1);
}

/** "40s", "3 min", "2 h" - how long until something. */
export function inShort(secs: number): string {
  if (secs < 60) return `${Math.max(1, Math.round(secs))}s`;
  if (secs < 3600) return `${Math.round(secs / 60)} min`;
  return `${Math.round(secs / 3600)} h`;
}

/** The worker's last error, trimmed to something that fits in a card. */
function why(rt?: Runtime): string {
  const t = rt?.last_error?.text?.trim();
  if (!t) return "";
  // The logger leads each line with its time and a glyph ("15:36:11 ✗ ...").
  // Neither helps in a card that already says when and what kind.
  return t
    .replace(/^\[?\d{1,2}:\d{2}(:\d{2})?\]?\s*/, "")
    .replace(/^[^\w(]+/, "")
    .slice(0, 220);
}

/** Its condition, with what its website has stopped showing it said, unless something more pressing is on the card. */
export function condition(slot: Parameters<typeof conditionOf>[0], rt: Parameters<typeof conditionOf>[1],
                          d: Parameters<typeof conditionOf>[2]): ReturnType<typeof conditionOf> {
  const cond = conditionOf(slot, rt, d);
  const missing: string[] = (rt as any)?.web?.site?.missing ?? [];
  if (!missing.length || cond.alert || !(rt as any)?.web || (rt as any).web.stale) return cond;
  const list = missing.length > 1 ? `${missing.slice(0, -1).join(", ")} or ${missing[missing.length - 1]}` : missing[0];
  return { ...cond, alert: {
    tone: "warn",
    title: `${platformName(slot.platform)} may have changed its page`,
    text: `It cannot find ${list}, so it may not see or send messages until this is fixed.`,
  } };
}

function conditionOf(slot: Slot, rt?: Runtime, d?: Details): Condition {
  const platform = platformName(slot.platform);
  const state = rt?.state ?? "stopped";
  const running = state === "running" || state === "starting" || state === "crashing";
  const reachable = state === "running" && !!d?.live;
  const paused = reachable && !!d?.paused;
  const base = { live: false, busy: false, running, canStart: false, reachable, paused };

  // ── Cannot run at all ──────────────────────────────────────────────────────
  if (!ready(slot)) {
    const missing = slot.platform === "discord"
      ? "It has no token yet."
      : slot.platform === "whatsapp" ? "It has not been linked to a phone yet."
      : slot.platform === "tiktok" || slot.platform === "reddit" ? "It has not been signed in yet."
      : slot.platform === "imessage"
        ? (!slot.server ? "It has no BlueBubbles address yet." : "It has no BlueBubbles password yet.")
      : slot.platform === "telegram" ? "It has not been signed in to Telegram yet."
      : !slot.username ? "It has no username yet." : "It has no password yet.";
    return {
      ...base, label: "Not set up", tone: "muted", line: "Needs its login before it can start",
      alert: {
        tone: "warn", title: "Finish setting it up", text: missing,
        action: { kind: "edit", label: slot.platform === "discord" ? "Add the token"
                                     : slot.platform === "telegram" ? "Sign in"
                                     : slot.platform === "whatsapp" ? "Link a phone"
                                     : slot.platform === "tiktok" || slot.platform === "reddit" ? "Sign in"
                                     : slot.platform === "imessage" ? "Add the server" : "Add the login" },
      },
    };
  }
  if (rt && rt.enabled === false && !running) {
    return {
      ...base, label: "Switched off", tone: "muted", line: `${platform} is turned off in Settings`,
      alert: {
        tone: "warn", title: `${platform} is switched off`,
        text: `No ${platform} account can start until it is turned back on.`,
        action: { kind: "settings", label: "Open the switch", to: "app/services" },
      },
    };
  }

  // ── Went wrong ─────────────────────────────────────────────────────────────
  if (state === "crashing") {
    const back = rt?.retry_in != null ? ` Trying again in ${inShort(rt.retry_in)}.` : "";
    return {
      ...base, label: "Crashing", tone: "bad",
      line: `Restarted ${rt?.restarts ?? 0} time${rt?.restarts === 1 ? "" : "s"}`,
      alert: {
        tone: "bad", title: "It keeps stopping",
        text: (why(rt) || "The worker exited unexpectedly.") + back,
        action: { kind: "logs", label: "Read the log" },
      },
    };
  }
  if (state === "stopped" && rt?.gave_up) {
    return {
      ...base, label: "Gave up", tone: "bad", canStart: true,
      line: `Stopped after crashing ${rt.restarts} times`,
      alert: {
        tone: "bad", title: "It crashed too often and was stopped",
        text: why(rt) || "Nothing more was said. The log will have the rest.",
        action: { kind: "logs", label: "Read the log" },
      },
    };
  }

  // ── Not running ────────────────────────────────────────────────────────────
  if (!running) {
    return { ...base, label: "Stopped", tone: "muted", line: "Not running", canStart: true };
  }

  // ── TikTok, Instagram, X and Reddit report on themselves too: signing ────
  //    in, a check to solve, a code to type, being hidden.
  const own = slot.platform !== "discord" && slot.platform !== "snapchat" && rt?.web && !rt.web.stale ? rt.web : null;
  const tt = own;
  // ── iMessage says how its Mac is: not reached, its password refused, not signed in to iMessage, or up, with or
  //    without BlueBubbles' Private API (typing dots, read receipts, tapbacks). There is no window to look at.
  // ── iMessage through the iPhone: up as soon as its worker is; what it waits for is the phone's first message,
  //    which only comes once its Shortcuts automation is made.
  // ── Telegram: signed in, or not; Telegram's own waits said as waits, not as faults.
  if (own && slot.platform === "telegram") {
    if (own.state === "logged-out") {
      return {
        ...base, label: "Signed out", tone: "bad", line: "Telegram no longer takes its sign-in",
        alert: {
          tone: "bad", title: "Telegram signed it out",
          text: own.detail || "Its session was ended, from Telegram's own Devices list or by Telegram itself.",
          action: { kind: "edit", label: "Sign in again" },
        },
      };
    }
    if (own.state === "needs-you") {
      // Telegram asking it to wait: it carries on by itself once the wait passes.
      return {
        ...base, label: "Waiting", tone: "warn", busy: true, line: cap(own.detail || "Telegram asked it to wait"),
        alert: { tone: "warn", title: "Telegram asked it to wait", text: own.detail || "" },
      };
    }
    if (own.state === "starting") {
      return { ...base, label: "Connecting", tone: "warn", busy: true, line: "Connecting to Telegram" };
    }
    if (own.state === "ready") {
      if (paused) return { ...base, label: "Paused", tone: "warn", line: "Connected, not replying" };
      return { ...base, label: "Online", tone: "good", live: true,
               line: d?.night ? "Quiet hours, replies wait" : "Texting" };
    }
  }
  if (own && viaPhone(slot)) {
    if (own.state === "ready") {
      const waiting = /waiting for your iphone/i.test(own.detail || "");
      if (paused) return { ...base, label: "Paused", tone: "warn", line: "Through your iPhone, not replying" };
      if (waiting) {
        return {
          ...base, label: "Set up your iPhone", tone: "warn", line: "Waiting for your iPhone",
          alert: {
            tone: "warn", title: "Make its shortcut on your iPhone",
            text: "A Shortcuts automation passes each message here and sends back the reply. Four steps.",
            action: { kind: "settings", label: "Show me", to: "imessage/setup" },
          },
        };
      }
      return { ...base, label: "Online", tone: "good", line: d?.night ? "Quiet hours, replies wait" : "Through your iPhone",
               live: true };
    }
    return { ...base, label: "Starting", tone: "warn", busy: true, line: "Starting" };
  }
  if (own && slot.platform === "imessage") {
    if (own.state === "needs-you") {
      const detail = own.detail || "";
      const refused = /refused/i.test(detail) && /password/i.test(detail);
      const noPass = !refused && /password/i.test(detail);
      const server = !refused && !noPass && /server|address/i.test(detail);
      return {
        ...base, label: refused ? "Wrong password" : noPass ? "No password" : "Needs you", tone: refused ? "bad" : "warn",
        line: refused ? "BlueBubbles refused its password" : cap(detail || "Waiting for you"),
        alert: {
          tone: refused ? "bad" : "warn",
          title: refused ? "BlueBubbles refused its password" : noPass ? "Add its BlueBubbles password"
            : server ? "Add its BlueBubbles server" : "It is waiting for you",
          text: detail,
          action: refused || noPass || server
            ? { kind: "edit", label: refused ? "Change the password" : noPass ? "Add the password" : "Add the server" }
            : undefined,
        },
      };
    }
    if (own.state === "logged-out") {
      return {
        ...base, label: "Can't reach the Mac", tone: "bad", line: "BlueBubbles is not answering",
        alert: {
          tone: "bad", title: "It cannot reach BlueBubbles", text: own.detail || "It tries again by itself.",
          action: { kind: "edit", label: "Check the address" },
        },
      };
    }
    if (own.state === "starting") {
      return { ...base, label: "Connecting", tone: "warn", busy: true, line: own.detail ? cap(own.detail) : "Connecting to the Mac" };
    }
    if (own.state === "ready") {
      // Up. What it does without, when BlueBubbles' Private API is off: said, never as a fault.
      const without = own.detail
        ? { tone: "warn" as const, title: /signed in/i.test(own.detail) ? "Not signed in to iMessage" : "Without the Private API",
            text: own.detail }
        : undefined;
      if (paused) return { ...base, label: "Paused", tone: "warn", line: "Connected, not replying", alert: without };
      return { ...base, label: "Online", tone: "good", line: d?.night ? "Quiet hours, replies wait" : "Texting",
               live: true, alert: without };
    }
  }
  // ── Minecraft says its own things: mindcraft not installed yet, a Microsoft code to type, a server it could not
  //    reach. There is no window and no check to solve.
  if (own && slot.platform === "minecraft") {
    if (own.state === "needs-you") {
      const install = /install/i.test(own.detail || "");
      const signIn = /microsoft|code/i.test(own.detail || "");
      // Microsoft's own sign-in page takes the code in the address (?otc=), so the button opens it already filled
      // in: nothing to read off the card and type. The code is said too, for signing in on another device.
      const code = (own.detail || "").match(/\b([A-Z0-9]{4,}-?[A-Z0-9]{3,})\b/)?.[1] || "";
      return {
        ...base, label: install ? "Needs installing" : signIn ? "Sign in" : "Needs you", tone: "warn", busy: !install,
        line: install ? "Minecraft support is not installed" : signIn ? "Microsoft sign-in" : cap(own.detail || "Waiting for you"),
        alert: {
          tone: "warn",
          title: install ? "Install Minecraft support first" : signIn ? "Sign in to Microsoft, once" : "It is waiting for you",
          text: install || !code ? own.detail || ""
            : `Opens Microsoft's page with the code ${code} already in it. Sign in as the account that owns Minecraft.`,
          action: install ? { kind: "settings", label: "Install it", to: "minecraft/setup" }
            : code ? { kind: "url", label: "Sign in with browser", to: `https://www.microsoft.com/link?otc=${code}` }
              : undefined,
        },
      };
    }
    if (own.state === "logged-out") {
      return {
        ...base, label: "Not in the world", tone: "bad", line: "Could not join the server",
        alert: {
          tone: "bad", title: "It could not join the server", text: own.detail || "It tries again by itself.",
          action: { kind: "edit", label: "Check the server" },
        },
      };
    }
    if (own.state === "logging-in") {
      return { ...base, label: "Joining", tone: "warn", busy: true, line: own.detail ? cap(own.detail) : "Joining the server" };
    }
    if (own.state === "starting") {
      return { ...base, label: "Starting", tone: "warn", busy: true, line: own.detail ? cap(own.detail) : "Starting mindcraft" };
    }
    if (own.state === "ready") {
      // In the world, and what it is doing there, as mindcraft last said.
      const g = own.game;
      const doing = g?.doing ? cap(g.doing) : "In the world";
      const hurt = typeof g?.health === "number" && g.health <= 8 ? `, ${g.health}/20 health` : "";
      // Where, by the server's name: its own port left off when it is Minecraft's usual one.
      const where = g?.server ? `, on ${String(g.server).replace(/:25565$/, "")}` : "";
      if (paused) {
        return { ...base, label: "Paused", tone: "warn", line: "In the world, not answering", live: true };
      }
      return { ...base, label: "In the world", tone: "good", line: `${doing}${hurt}${where}`, live: true };
    }
  }
  if (own && slot.platform !== "minecraft" && slot.platform !== "imessage") {
    const ig = slot.platform === "instagram";
    if (own.state === "needs-login") {
      return {
        ...base, label: "Sign in", tone: "warn", busy: true, line: "Waiting for you to sign in",
        alert: {
          tone: "warn", title: `Sign in to ${platform} again`,
          text: own.detail || `Its ${platform} window is open. Sign in there; it carries on from there.`,
        },
      };
    }
    if (own.state === "logging-in") {
      return { ...base, label: "Signing in", tone: "warn", busy: true,
               line: own.detail ? cap(own.detail) : `Signing itself in to ${platform}` };
    }
    if (own.state === "needs-you") {
      // Instagram asks for two different things: a code from the account's email, or a check in its window.
      const code = ig && /\bcode\b/i.test(own.detail || "");
      return {
        ...base,
        label: code ? "Code needed" : "Check to solve",
        tone: "warn", busy: true,
        line: code ? `${platform} sent a code` : `${platform} put up a check`,
        alert: {
          tone: "warn",
          title: code ? `${platform} wants a code` : `${platform} wants a check solved`,
          text: own.detail || (code
            ? "Check the account's email or phone, and type the code on the Accounts page."
            : `Solve it in its ${platform} window. It carries on once it is done.`),
          action: code ? { kind: "edit", label: "Type the code" } : undefined,
        },
      };
    }
    if (own.state === "logged-out" && /suspended|disabled/i.test(own.detail || "")) {
      // Nothing on this side can undo it: no login to check, only the platform's own appeal.
      return {
        ...base, label: "Suspended", tone: "bad", line: `${platform} suspended this account`,
        alert: {
          tone: "bad", title: `${platform} suspended this account`,
          text: own.detail || `Appeal in the ${platform} app. It looks again every few hours.`,
          action: { kind: "logs", label: "Read the log" },
        },
      };
    }
    if (own.state === "logged-out") {
      const creds = /password|incorrect|refused/i.test(own.detail || "");
      return {
        ...base, label: "Logged out", tone: "bad", line: `Not signed in to ${platform}`,
        alert: {
          tone: "bad", title: creds ? `${platform} refused the login` : `${platform} signed it out`,
          text: own.detail || "It will try to sign in again by itself.",
          action: creds ? { kind: "edit", label: "Check the login" } : { kind: "logs", label: "Read the log" },
        },
      };
    }
    if (own.state === "starting") {
      return { ...base, label: "Starting", tone: "warn", busy: true,
               line: own.detail ? cap(own.detail) : `Opening ${platform} in the background` };
    }
  }

  // ── Snapchat reports on itself; trust that over "the process exists" ───────
  const snap = slot.platform === "snapchat" && rt?.snap && !rt.snap.stale ? rt.snap : null;
  if (snap) {
    if (snap.state === "awaiting-verification") {
      return {
        ...base, label: "Verify login", tone: "warn", busy: true, line: "Waiting for Snapchat to let it in",
        alert: {
          tone: "warn", title: "Snapchat wants to check it is you",
          text: snap.detail || "Approve the login from the email or the app. It waits, it does not give up.",
        },
      };
    }
    if (snap.state === "needs-login") {
      return {
        ...base, label: "Log in", tone: "warn", busy: true, line: "Waiting for you to log in",
        alert: {
          tone: "warn", title: "Log in yourself, once",
          text: snap.detail || "Snapchat turned down the automatic login. Log in yourself in its Chrome window; it carries on from there.",
          action: { kind: "logs", label: "Read the log" },
        },
      };
    }
    if (snap.state === "logged-out") {
      const creds = /credential|password|incorrect|failed/i.test(snap.detail);
      return {
        ...base, label: "Logged out", tone: "bad", line: "Not signed in to Snapchat",
        alert: {
          tone: "bad", title: creds ? "Snapchat refused the login" : "Snapchat signed it out",
          text: snap.detail || "It will try to sign in again by itself.",
          action: creds ? { kind: "edit", label: "Check the login" } : { kind: "logs", label: "Read the log" },
        },
      };
    }
    if (snap.state === "starting") {
      return { ...base, label: "Starting", tone: "warn", busy: true,
               line: snap.detail ? cap(snap.detail) : "Opening Snapchat in the background" };
    }
  }

  if (state === "starting" && !reachable) {
    return { ...base, label: "Starting", tone: "warn", busy: true,
             line: slot.platform === "discord" ? "Connecting to Discord" : `Opening ${platform} in the background` };
  }

  // ── Up ─────────────────────────────────────────────────────────────────────
  // A worker that has not answered the panel yet is still up; it just has
  // nothing to say about itself so far.
  const said = snap ?? tt;
  const drift = said?.state === "ready" && said.detail
    ? { tone: "warn" as const, title: `${platform} changed its page`, text: said.detail }
    : undefined;
  if (paused) {
    return {
      ...base, label: "Paused", tone: "warn",
      line: slot.platform === "discord" ? `${presenceName(d?.presence)}, not replying` : "Signed in, not replying",
      alert: drift,
    };
  }
  if (slot.platform === "discord") {
    const p = d?.presence;
    const label = !reachable ? "Running" : presenceName(p);
    const line = !reachable
      ? "Up, not answering the panel yet"
      : d?.night && p === "invisible" ? "Replying, invisible for the night"
      : "Replying to messages";
    return { ...base, label, tone: "good", line, live: true };
  }
  return { ...base, label: "Online", tone: "good", line: d?.night ? "Quiet hours, replies wait" : "Signed in and replying",
           live: true, alert: drift };
}

function cap(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/**
 * The dot next to the avatar. Discord's own presence for a Discord account.
 * Snapchat has none to show, so the same shapes stand for how its login is
 * doing: signed in, waiting on something (idle's crescent), or signed out.
 */
export function presenceOf(slot: Slot, rt?: Runtime, d?: Details): string {
  if (!rt || rt.state !== "running" || !d?.live) return "offline";
  if (slot.platform !== "discord") {
    const own = rt.web ?? rt.snap;
    const s = own && !own.stale ? own.state : "ready";
    return s === "ready" ? "online" : s === "logged-out" ? "offline" : "idle";
  }
  return d.presence || "online";
}

/** How many accounts need something done, for the page header. */
export function attentionCount(conds: Condition[]): number {
  return conds.filter((c) => c.alert).length;
}

/** "3h 12m", "2d 4h", "12m" */
export function uptime(secs?: number): string {
  if (!secs) return "";
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  return h ? `${h}h ${m}m` : `${m}m`;
}

/** "just now", "4 min ago", "3 h ago", "2 days ago" */
export function ago(ts: number, now = Date.now() / 1000): string {
  const s = Math.max(0, now - ts);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const days = Math.round(s / 86400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
