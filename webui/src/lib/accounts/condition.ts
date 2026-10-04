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
};

export type SnapState = {
  state: string;
  detail: string;
  at: number;
  stale: boolean;
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
};

export type Tone = "good" | "warn" | "bad" | "muted" | "accent";

/** Something that needs doing, and the one button that does it. */
export type Alert = {
  tone: "warn" | "bad";
  title: string;
  text: string;
  action?: { kind: "edit" | "logs" | "settings" | "start"; label: string; to?: string };
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

export function condition(slot: Slot, rt?: Runtime, d?: Details): Condition {
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
      : !slot.username ? "It has no username yet." : "It has no password yet.";
    return {
      ...base, label: "Not set up", tone: "muted", line: "Needs its login before it can start",
      alert: {
        tone: "warn", title: "Finish setting it up", text: missing,
        action: { kind: "edit", label: slot.platform === "discord" ? "Add the token" : "Add the login" },
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
             line: slot.platform === "discord" ? "Connecting to Discord" : "Opening Snapchat in the background" };
  }

  // ── Up ─────────────────────────────────────────────────────────────────────
  // A worker that has not answered the panel yet is still up; it just has
  // nothing to say about itself so far.
  const drift = snap?.state === "ready" && snap.detail
    ? { tone: "warn" as const, title: "Snapchat changed its page", text: snap.detail }
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
    const s = rt.snap && !rt.snap.stale ? rt.snap.state : "ready";
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
