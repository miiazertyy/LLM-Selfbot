/**
 * Where each reply is, in words and as a stage on the tracker.
 *
 * Shared by the Chats tab and Big Picture Mode, so both say exactly the same
 * thing about the same reply: "Replies in 40s", "Writing a reply", "Typing…".
 * Pure functions of the row and the moment: the caller passes the clock, and
 * whether the account is paused, so nothing here keeps state of its own.
 */
import type { ChatUser } from "./chats";
import { fmtDate, HOUR_MINUTE } from "./fmt";

export type Phase = "live" | "needs" | "off";
export type Status = {
  phase: Phase;
  tone: "accent" | "good" | "warn" | "bad" | "muted";
  /** Short, for the list. */
  short: string;
  /** Long, for the conversation. */
  title: string;
  detail?: string;
  eta?: number | null;
  since?: number;
  /** Where it is on the tracker, 1 (waiting) to 4 (typing). */
  step?: number;
};

/** The tracker's stages, in order: a Status's `step` indexes into this. */
export const STEPS = ["Received", "Waiting", "Writing", "Pacing", "Typing", "Sent"];

export type StatusContext = {
  /** Unix seconds, from the caller's ticking clock. */
  now: number;
  /** The whole account is paused. */
  paused?: boolean;
  /** Rows a Reply to all tried and could not answer this run. */
  failed?: Set<string>;
};

/** "40s", "3m 12s", "1h 5m" until a moment, or "" once it has passed. */
export function countdown(at: number | null | undefined, now: number): string {
  if (!at) return "";
  const left = Math.max(0, Math.round(at - now));
  if (left <= 0) return "";
  if (left < 60) return `${left}s`;
  const m = Math.floor(left / 60);
  if (m < 60) return `${m}m ${left % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

const clock = (ts?: number | null) => (ts ? fmtDate(ts * 1000, HOUR_MINUTE) : "");

export function statusOf(u: ChatUser, ctx: StatusContext): Status {
  const { now } = ctx;
  if (u.ignored) {
    return { phase: "off", tone: "muted", short: "Bot off", title: "The bot is off for them",
             detail: "It will not answer them until you turn it back on." };
  }
  if (ctx.paused) {
    return { phase: "needs", tone: "warn", short: "Account paused", title: "Held, the account is paused",
             detail: "Resume it from Accounts to let it answer." };
  }
  const s = u.state;
  if (s) {
    const c = countdown(s.eta, now);
    switch (s.state) {
      case "waiting":
        return { phase: "live", tone: "accent", step: 1, short: c ? `Replies in ${c}` : "Replying any moment",
                 title: c ? `Replies in ${c}` : "Replying any moment",
                 detail: "Waiting in case they send more, then it reads everything and answers.",
                 eta: s.eta, since: s.since };
      case "writing":
        return { phase: "live", tone: "accent", step: 2, short: "Writing a reply", title: "Writing a reply",
                 detail: "The model is writing it now." };
      case "cooldown":
        return { phase: "live", tone: "accent", step: 3, short: c ? `Sends in ${c}` : "Sending soon",
                 title: c ? `Pacing, sends in ${c}` : "Sending any moment",
                 detail: "Held so replies to different people never land seconds apart.",
                 eta: s.eta, since: s.since };
      case "queued":
        return { phase: "live", tone: "accent", step: 4, short: "Next to send", title: "Next in line to send",
                 detail: "Another reply is going out first." };
      case "sending":
        return { phase: "live", tone: "good", step: 4, short: "Typing…", title: "Typing it out",
                 detail: "The typing indicator is up in their DM right now." };
      case "skipped":
        return { phase: "needs", tone: "muted", short: "Won't answer", title: "It won't answer this on its own",
                 detail: s.reason ? `Because ${s.reason}.` : undefined };
      case "failed":
        return { phase: "needs", tone: "bad", short: "Couldn't reply", title: "The reply did not go out",
                 detail: s.reason ? `${s.reason[0].toUpperCase()}${s.reason.slice(1)}.` : undefined };
    }
  }
  if (ctx.failed?.has(u.id)) {
    return { phase: "needs", tone: "bad", short: "Couldn't reply", title: "The reply did not go out",
             detail: "Logs has the reason." };
  }
  if (u.reply_at && countdown(u.reply_at, now)) {
    return { phase: "live", tone: "accent", step: 1, short: `Replies in ${countdown(u.reply_at, now)}`,
             title: `Replies in ${countdown(u.reply_at, now)}`, detail: `Around ${clock(u.reply_at)}.`, eta: u.reply_at };
  }
  if (u.ts && now - u.ts > 3600) {
    return { phase: "needs", tone: "warn", short: "Came in while off", title: "Arrived while the bot was off",
             detail: "It does not go back through old messages on its own. Reply now answers it." };
  }
  return { phase: "needs", tone: "muted", short: "Not picked up", title: "Not picked up",
           detail: "It won't answer this on its own. Reply now answers it." };
}

/** How far through its wait a countdown is, 0 to 1. */
export function progress(st: Status, now: number): number {
  if (!st.eta || !st.since || st.eta <= st.since) return 0;
  return Math.max(0, Math.min(1, (now - st.since) / (st.eta - st.since)));
}
