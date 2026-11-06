/** The shapes Big Picture Mode's parts pass each other. */
import type { ChatAccount, ChatUser } from "../chats";
import type { Status } from "../chatstatus";

/** One conversation in the queue, from any account. `key` is unique across accounts: "target:rowId". */
export type QRow = { key: string; target: string; u: ChatUser; st: Status; account?: ChatAccount };

/**
 * The conversation on stage. `answered` once its reply has gone and it has left
 * the queue; `browsing` when it was opened by hand and was never in the queue at
 * all; `ignored` when the bot has been turned off for them from here.
 */
export type Spot = QRow & { answered: boolean; browsing?: boolean; ignored?: boolean };

/** Something that just happened, for the list on the right. */
export type FeedItem = {
  id: number;
  kind: "arrive" | "write" | "sent" | "model" | "limit" | "friend" | "picture";
  text: string;
  avatar?: string;
  name?: string;
  /** Which app it happened on, for its logo. */
  platform?: string;
  /** Whose conversation it was, so pressing it opens that. */
  target?: string;
  uid?: string;
  at: number;
};

/** One line of the log, tidied (logrows.ts): who wrote it, and what. */
export type LogLite = { id: number; at: number; level: string; text: string; who: string; avatar?: string; icon: string };

/** The model that answered last. */
export type Active = { provider: string; model: string; at: number; ms: number; ok: boolean };

/** One line of a conversation, as a Memory summary keeps it: whose, and what was said. */
export type MemoryLine = { mine: boolean; text: string };

/** Someone it talks to, on any account. `key` is "target:id", as the queue's are. */
export type Person = {
  key: string;
  /** The account the conversation is on. */
  target: string;
  id: string;
  name: string;
  avatar?: string;
  platform: string;
  /** Messages from them in the log, all time. */
  messages: number;
  last_ts?: number;
  /** Messages from them this week. */
  week?: number;
};

/** What a person's stored Memory summary says. */
export type Remembered = {
  summary: string;
  generated_at?: number;
  /** How many messages the summary was written from. */
  count?: number;
  /** The last few messages, both sides, oldest first. */
  recent: MemoryLine[];
};

/**
 * An account as Big Picture shows it: who it is (recorded when it last
 * connected, so a stopped one still has its face), what the supervisor says of
 * its worker, and what the worker said of itself when it last answered.
 */
export type BPAccount = {
  id: string;
  platform: string;
  account: number | null;
  name: string;
  username?: string;
  avatar?: string;
  banner?: string;
  /** The colour picked instead of a banner, #rrggbb. */
  accent?: string;
  /** The supervisor's word: running, starting, stopped, crashing. */
  state: string;
  uptime?: number;
  /** False when the whole platform is switched off in Settings. */
  enabled?: boolean;
  /** The worker answered just now: the fields below are live. */
  live?: boolean;
  ping?: number | null;
  mood?: string;
  presence?: string;
  paused?: boolean;
  night?: boolean;
  guilds?: number;
  friends?: number;
};

/** What one account has been doing this week, from the message log. */
export type BPActivity = {
  today: number;
  week: number;
  people_week: number;
  /** Replies per day, oldest first, today last. */
  series: number[];
  top: { id: string; name: string; count: number; avatar?: string }[];
  last: { id: string; name: string; ts: number } | null;
};

/** The day's figures, on every platform together (api.statsDetail): nothing here is one platform's alone. */
export type DayStats = {
  replies: number;
  /** The same stretch before it. */
  repliesBefore: number;
  people: number;
  peopleBefore: number;
  /** The last 24 hours, this hour last. */
  hourly: { hour: number; count: number }[];
  /** Replies on each platform. */
  platform: Record<string, number>;
  loaded: boolean;
};

/** Someone asking one of the accounts to be friends. */
export type FriendReq = {
  id: string;
  username: string;
  display_name?: string;
  avatar?: string;
  /** Unix seconds when the account accepts it on its own, if that is scheduled. */
  accept_at?: number | null;
  /** The account it was sent to. */
  target: string;
};

/** One of the bot's own pictures, and what the model is told it shows. */
export type Picture = { name: string; description: string; url: string };

/** A picture that went out: to whom, and when. */
export type SentPicture = { to: string; avatar?: string; at: number };

/** Something on the Health list, as the panel's own poll has it (stores.ts). */
export type HealthIssue = { route: string; level: "error" | "warn" | "info"; title: string; detail: string };

/** What can be done from the pages, kept by the view itself: it knows who is on stage and what is held. */
export type PageActions = {
  /** Put this conversation on stage, in the queue or not. */
  open: (target: string, id: string, as?: { name: string; avatar?: string }) => void;
  openPerson: (p: Person) => void;
  /** Go to a page of the view. */
  go: (page: import("./director").Page) => void;
  /** Leave Big Picture for a page of the app. */
  leaveTo: (route: string) => void;
  /** Something chosen by hand: keep this up a while. */
  hold: () => void;
  /** What the room is lit for on this page, or null for the page's own. */
  light: (page: import("./director").Page, room: { seed: string; art?: string } | null) => void;
  /** Esc: this page has something open to close first. Give it back null when it has not. */
  onBack: (fn: (() => void) | null) => void;
  reply: (target: string, id: string) => void;
};
