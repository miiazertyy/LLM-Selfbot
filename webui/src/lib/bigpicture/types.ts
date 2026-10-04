/** The shapes Big Picture Mode's parts pass each other. */
import type { ChatAccount, ChatUser } from "../chats";
import type { Status } from "../chatstatus";

/** One conversation in the queue, from any account. `key` is unique across accounts: "target:rowId". */
export type QRow = { key: string; target: string; u: ChatUser; st: Status; account?: ChatAccount };

/** The conversation on stage; `answered` once its reply has gone and it has left the queue. */
export type Spot = QRow & { answered: boolean };

/** Something that just happened, for the feed. */
export type FeedItem = {
  id: number;
  kind: "arrive" | "write" | "sent" | "model" | "limit" | "friend" | "picture";
  text: string;
  avatar?: string;
  name?: string;
  at: number;
};

/** A reasoning model's thought, from the logs. */
export type Thought = { model: string; text: string; at: number };

/** One line of the log, tidied (logrows.ts): who wrote it, and what. */
export type LogLite = { id: number; at: number; level: string; text: string; who: string; avatar?: string; icon: string };

/** The model that answered last. */
export type Active = { provider: string; model: string; at: number; ms: number; ok: boolean };

/** One line of a conversation, as a Memory summary keeps it: whose, and what was said. */
export type MemoryLine = { mine: boolean; text: string };

/** Someone the idle "memory" scene shows: who they are, what you talk about, and how it last went. */
export type MemoryPerson = {
  id: string;
  name: string;
  avatar?: string;
  /** Messages from them in the log, all time. */
  messages: number;
  last_ts?: number;
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

/** Everything the scenes about the rest of the app show: the accounts, the pictures, the requests, the persona, the health. */
export type SceneWorld = {
  accounts: BPAccount[];
  activity: Record<string, BPActivity>;
  /** The calendar day of each entry of an activity series, oldest first. */
  dates: string[];
  pictures: Picture[];
  sent: Record<string, SentPicture>;
  /** The Pictures preference says blurred, and they have not been shown this visit. */
  picturesBlurred: boolean;
  friends: FriendReq[];
  friendGone: Record<string, "accept" | "decline">;
  persona: { lines: string[]; name: string; face: BPAccount | null };
  moods: string[];
  issues: HealthIssue[];
  /** Anything with an action on its way, by the id of what it is on. */
  busy: Record<string, boolean>;
};

/** What can be done from those scenes. */
export type SceneActions = {
  onpause?: (a: BPAccount) => void;
  onmood?: (a: BPAccount, mood: string, el: HTMLElement) => void;
  onanswer?: (r: FriendReq, action: "accept" | "decline", el: HTMLElement | null) => void;
  onreveal?: () => void;
  /** Something chosen by hand in a scene: keep it up a while. */
  onhold?: () => void;
  /** Leave Big Picture for a page of the app. */
  onopen?: (route: string) => void;
};
