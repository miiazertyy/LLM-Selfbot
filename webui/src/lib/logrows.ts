/**
 * Log lines as the Logs page and the Dashboard's log widget draw them: one
 * row per thing that happened.
 *
 * The runners print for a console: their own clock and a glyph in front of
 * every line, a message someone sent as an indented line under "x in #DM", a
 * reply under "Responding to x", and a rule of box-drawing characters after
 * it. Folded here: a continuation goes under the line it belongs to, rules are
 * dropped, and a model's thinking is split into its heading and the thought.
 * Sources are named the way the rest of the app names them: the account's own
 * name and picture instead of "discord_1".
 */
import type { ChatAccount } from "./chats";

export type LogLine = { time: string; source: string; text: string; level: string; ts?: number; id?: number };

export type LogRow = {
  id: number;
  ts: number;
  time: string;
  source: string;
  level: string;
  text: string;
  more: string[];
  think?: { head: string; body: string };
};

export const KINDS = [
  { id: "error", label: "Errors", icon: "alertCircle" },
  { id: "warn", label: "Warnings", icon: "alert" },
  { id: "recv", label: "Incoming", icon: "inbox" },
  { id: "reply", label: "Replies", icon: "send" },
  { id: "think", label: "Thinking", icon: "sparkle" },
  { id: "system", label: "System", icon: "settings" },
  { id: "info", label: "Other", icon: "logs" },
];
export const kindOf = (level: string) => (KINDS.some((k) => k.id === level) ? level : "info");
export const ICON: Record<string, string> = Object.fromEntries(KINDS.map((k) => [k.id, k.icon]));

const APP_SOURCES: Record<string, { name: string; icon: string }> = {
  supervisor: { name: "App", icon: "dashboard" },
  panel: { name: "Panel", icon: "system" },
  ai: { name: "AI", icon: "sparkle" },
  local: { name: "This computer", icon: "monitor" },
  system: { name: "System", icon: "settings" },
  telegram: { name: "Telegram", icon: "chats" },
  updater: { name: "Updater", icon: "upload" },
  "ffmpeg-install": { name: "ffmpeg", icon: "upload" },
  "snapchat-install": { name: "Snapchat setup", icon: "snapchat" },
};

/** Who a line came from, by name: the account's own name and picture, or the part of the app. */
export function sourceInfo(s: string, accounts: ChatAccount[]): { name: string; icon: string; avatar?: string } {
  if (APP_SOURCES[s]) return APP_SOURCES[s];
  const m = s.match(/^(discord|snapchat)_(\d+)$/);
  if (m) {
    const a = accounts.find((x) => x.id === s);
    const slot = `${m[1] === "discord" ? "Discord" : "Snapchat"} #${m[2]}`;
    return { name: a?.display_name || a?.username || slot, icon: m[1] === "discord" ? "accounts" : "snapchat",
             avatar: a?.avatar };
  }
  return { name: s, icon: "logs" };
}

// The runners print their own clock and a glyph in front of every line, for
// the console. The row has both already.
const STAMP = /^\d{2}:\d{2}:\d{2}\s+/;
const GLYPH = /^(⚙|✗|⚠|⟳|⏱|↳|←|👁|💭|✓|✔|•|»)\s*/u;
export const tidy = (t: string) => t.replace(STAMP, "").replace(GLYPH, "").trim();
/** A continuation: the message under "x in #DM", or the reply under "Responding to x". */
export const isMore = (t: string) => /^\s+\S/.test(t) || /^\s*▸/.test(t);
export const isRule = (t: string) => /^[─━═\-\s]{8,}$/.test(t);

/** Lines into rows: continuations folded into the line they belong to, rules dropped. */
export function foldRows(lines: LogLine[]): LogRow[] {
  const out: LogRow[] = [];
  for (const l of lines) {
    const raw = l.text ?? "";
    if (isRule(raw.trim())) continue;
    const prev = out[out.length - 1];
    if (prev && isMore(raw) && prev.source === l.source && Math.abs((l.ts ?? 0) - prev.ts) < 3) {
      prev.more.push(raw.replace(/^\s*▸\s?/, "").trim());
      continue;
    }
    const level = kindOf(l.level);
    const row: LogRow = { id: l.id ?? 0, ts: l.ts ?? 0, time: l.time, source: l.source, level, text: tidy(raw), more: [] };
    if (level === "think") {
      const nl = raw.indexOf("\n");
      row.think = { head: nl < 0 ? raw : raw.slice(0, nl), body: nl < 0 ? "" : raw.slice(nl + 1).trim() };
      row.text = row.think.head;
    }
    out.push(row);
  }
  return out;
}
