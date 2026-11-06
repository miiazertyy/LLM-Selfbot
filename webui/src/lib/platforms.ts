/**
 * The platforms the app runs accounts on, and what each one can do, in one
 * place. Pages used to ask "is it Snapchat?" and assume Discord otherwise; with
 * four there is no "otherwise", so they ask this instead: its name, its mark,
 * its colour, and whether it has calls, reactions, servers and so on.
 *
 * "browser" platforms (Snapchat, TikTok, Instagram) are driven through their
 * website by the shared bridge: slower to answer, their people known by text
 * ids, their conversations read from what is kept. Minecraft is run by the same
 * bridge without a browser, and is one too in every sense the panel uses the
 * word for: what it cannot do that they can is said by its own flags (media).
 */
export type PlatformId = "discord" | "snapchat" | "tiktok" | "instagram" | "x" | "reddit" | "whatsapp"
  | "minecraft" | "imessage" | "telegram";

export type Platform = {
  id: PlatformId;
  name: string;
  /** Its name where there is no room for the whole of it (a tab strip, a chip). Its name when it has none. */
  short?: string;
  /** Icon.svelte name of its mark. */
  icon: string;
  /** Its own colour, for marks and an empty banner. */
  tone: string;
  browser: boolean;
  /** A person with no picture shows the platform's empty silhouette (Snapchat's), not initials. */
  silhouette: boolean;
  /** What a request to talk is called there, and what adding someone is. */
  requests: string;
  add: string;
  /** Who someone is there, as a word: "friend", "follower". */
  people: string;
  calls: boolean;
  reactions: readonly string[];
  servers: boolean;
  groups: boolean;
  /** Custom statuses, presence: Discord's alone. */
  status: boolean;
  /** Voice notes it can send. */
  voice: boolean;
  /** Any emoji as a reaction, rather than only the few in `reactions`. */
  anyReaction?: boolean;
  /** Stories: watched, answered, and put up. */
  stories?: boolean;
  /** Pictures and files it can send; false where its chat is words only (Minecraft's). */
  media?: boolean;
};

export const PLATFORMS: Record<PlatformId, Platform> = {
  discord: {
    id: "discord", name: "Discord", icon: "discord", tone: "#5865f2", browser: false, silhouette: false,
    requests: "Friend requests", add: "Add friend", people: "friend", calls: true, reactions: [], servers: true,
    groups: true, status: true, voice: true,
  },
  snapchat: {
    id: "snapchat", name: "Snapchat", icon: "snapchat", tone: "#fffc00", browser: true, silhouette: true,
    requests: "Friend requests", add: "Add friend", people: "friend", calls: true,
    reactions: ["❤️", "😂", "🔥", "👍", "👎", "😰", "🤯", "❓"], servers: false, groups: false, status: false, voice: false,
  },
  tiktok: {
    id: "tiktok", name: "TikTok", icon: "tiktok", tone: "#fe2c55", browser: true, silhouette: false,
    requests: "Message requests", add: "Follow", people: "follower", calls: false,
    reactions: ["❤️", "😂", "😡", "😭", "👍", "🤔", "🎉", "🤗", "😳", "😱", "🤪", "🙈"], servers: false, groups: true, status: false,
    voice: false,
  },
  instagram: {
    id: "instagram", name: "Instagram", icon: "instagram", tone: "#e1306c", browser: true, silhouette: false,
    requests: "Message requests", add: "Follow", people: "follower", calls: true,
    // The six its picker offers at a glance; its search takes any emoji there is.
    reactions: ["❤️", "😂", "😮", "😢", "😡", "👍"], anyReaction: true,
    servers: false, groups: true, status: false, voice: true, stories: true,
  },
  // X, which most people still call Twitter, so both names are on it. Its brand is black on white or white on
  // black: on this panel that is the near-white its own pages use, since black would be invisible.
  x: {
    id: "x", name: "X (Twitter)", short: "X", icon: "x", tone: "#e7e9ea", browser: true, silhouette: false,
    requests: "Message requests", add: "Follow", people: "follower", calls: false,
    // The seven its picker opens with; its search takes any emoji there is.
    reactions: ["❤️", "😂", "😮", "😢", "🔥", "👍", "👎"], anyReaction: true,
    servers: false, groups: true, status: false, voice: false,
  },
  // Reddit: a person is a u/ name, a group chat is a room, and most of what is said to it is said in public
  // under something it wrote. Its own orange, which nothing else on this panel is near.
  reddit: {
    id: "reddit", name: "Reddit", icon: "reddit", tone: "#ff4500", browser: true, silhouette: false,
    requests: "Chat invitations", add: "Follow", people: "follower", calls: false,
    // The seven its picker opens with; Reddit chat takes any emoji there is.
    reactions: ["❤️", "😂", "😮", "😢", "🔥", "👍", "👎"], anyReaction: true,
    servers: false, groups: true, status: false, voice: false,
  },
  // WhatsApp: a phone number of its own, linked from a phone. No browser anywhere in it - it speaks
  // WhatsApp's own protocol - but "browser" in this table means what iMessage means by it: run by the bridge,
  // its people known by text ids, its conversations read from what is kept.
  whatsapp: {
    id: "whatsapp", name: "WhatsApp", icon: "whatsapp", tone: "#25d366", browser: true, silhouette: false,
    requests: "", add: "New message", people: "contact", calls: true,
    // The six its picker opens with; it takes any emoji there is.
    reactions: ["👍", "❤️", "😂", "😮", "😢", "🙏"], anyReaction: true,
    servers: false, groups: true, status: false, voice: true,
  },
  // A game's chat: words and the commands that make it play, nothing else. No requests to accept, nobody to add.
  minecraft: {
    id: "minecraft", name: "Minecraft", icon: "minecraft", tone: "#5b8731", browser: true, silhouette: false,
    requests: "", add: "", people: "player", calls: false, reactions: [], servers: false, groups: false,
    status: false, voice: false, media: false,
  },
  // The persona's own Telegram account (not the bot that controls the app): groups, channels, photos, voice
  // messages, any emoji as a reaction, calls it declines, and stories it can post.
  telegram: {
    id: "telegram", name: "Telegram", icon: "telegram", tone: "#2aabee", browser: true, silhouette: false,
    requests: "", add: "New message", people: "contact", calls: true,
    // The eight its picker opens with; any emoji works, which is why anyReaction is on.
    reactions: ["👍", "👎", "❤️", "🔥", "🥰", "😁", "🤔", "😢"], anyReaction: true,
    servers: false, groups: true, status: true, voice: true, stories: true,
  },
  // Texting, through BlueBubbles on a Mac: groups, photos, voice messages, iMessage's six tapbacks, FaceTime calls
  // seen. No requests: anyone can text anyone, and adding someone is writing to their number or email.
  imessage: {
    id: "imessage", name: "iMessage", icon: "imessage", tone: "#0a84ff", browser: true, silhouette: false,
    requests: "", add: "New message", people: "contact", calls: true,
    reactions: ["❤️", "👍", "👎", "😂", "‼️", "❓"], servers: false, groups: true, status: false, voice: true,
  },
};

/** Every platform, in the order they are shown. */
export const PLATFORM_IDS = Object.keys(PLATFORMS) as PlatformId[];
/** An account's id: "discord_1", "tiktok_12". */
export const ACCOUNT_ID = new RegExp(`^(${PLATFORM_IDS.join("|")})_(\\d+)$`);

/** The platform of an account ("tiktok_2"), a target, or a platform name; Discord when it is none of them. */
export function platformOf(id: string | null | undefined): Platform {
  const s = String(id ?? "");
  if (s.startsWith("tiktok")) return PLATFORMS.tiktok;
  if (s.startsWith("insta")) return PLATFORMS.instagram;
  if (s.startsWith("imsg") || s.startsWith("imessage")) return PLATFORMS.imessage;
  if (s.startsWith("tg") || s.startsWith("telegram")) return PLATFORMS.telegram;
  if (s.startsWith("snap")) return PLATFORMS.snapchat;
  if (s.startsWith("mc") || s.startsWith("minecraft")) return PLATFORMS.minecraft;
  if (s.startsWith("reddit")) return PLATFORMS.reddit;
  // Its targets are "wa" and a number; its name is spelled differently, so both are looked for.
  if (s.startsWith("whatsapp") || s.startsWith("wa")) return PLATFORMS.whatsapp;
  // X's targets are the one letter and a number ("x", "x2"), and nothing else here begins with it.
  if (s.startsWith("x") || s.startsWith("twitter")) return PLATFORMS.x;
  return PLATFORMS.discord;
}

/**
 * The platform of a person by their id: Discord's are all digits, TikTok's start "tt_", Instagram's "ig_" (and a
 * group of theirs "igg_"), and anything else is a Snapchat chat id.
 */
export function platformOfUser(uid: string | number | null | undefined): Platform {
  const s = String(uid ?? "");
  if (/^\d+$/.test(s)) return PLATFORMS.discord;
  if (s.startsWith("tt_")) return PLATFORMS.tiktok;
  if (s.startsWith("ig_") || s.startsWith("igg_")) return PLATFORMS.instagram;
  // A player is "mc_" and their name; the server's own events "mcs_". Before the fallthrough, which is Snapchat's.
  if (s.startsWith("mc_") || s.startsWith("mcs_")) return PLATFORMS.minecraft;
  // iMessage: a person by their number or email ("im_"), a group by its chat's number ("img_").
  if (s.startsWith("im_") || s.startsWith("img_")) return PLATFORMS.imessage;
  // Telegram: a person by their id ("tg_"), a group or channel by its chat's ("tgg_").
  if (s.startsWith("tg_") || s.startsWith("tgg_")) return PLATFORMS.telegram;
  // X: a person by their @handle ("x_"), a group message by its conversation's number ("xg_"). An underscore is
  // legal in a handle, so "x_g_tom" is a person and only "xg_" without one is a group.
  if (s.startsWith("x_") || s.startsWith("xg_")) return PLATFORMS.x;
  // Reddit the same way: a person by their username ("rd_"), a group chat by its room ("rdg_"). A username may
  // hold an underscore too, so "rd_g_tom" is a person.
  if (s.startsWith("rd_") || s.startsWith("rdg_")) return PLATFORMS.reddit;
  // WhatsApp: a person by their number ("wa_"), a group by its own id ("wag_").
  if (s.startsWith("wa_") || s.startsWith("wag_")) return PLATFORMS.whatsapp;
  return PLATFORMS.snapchat;
}

export const platformName = (id: string | null | undefined) => platformOf(id).name;
/** Its name where there is no room: "X" rather than "X (Twitter)". */
export const platformShort = (id: string | null | undefined) => {
  const p = platformOf(id);
  return p.short ?? p.name;
};
export const platformIcon = (id: string | null | undefined) => platformOf(id).icon;
export const isBrowser = (id: string | null | undefined) => platformOf(id).browser;

/** "Discord #2", "TikTok #1", "X #1": the short name, so a card's title stays a title. */
export function accountLabel(id: string | null | undefined, n?: number | null): string {
  const m = String(id ?? "").match(/_(\d+)$/);
  return `${platformShort(id)} #${n ?? (m ? +m[1] : 1)}`;
}

const TT_LINK = /https?:\/\/(?:(?:www|m)\.)?tiktok\.com\/@[\w.]+\/(?:video|photo)\/\d+|https?:\/\/(?:vm|vt)\.tiktok\.com\/\w+\/?|https?:\/\/(?:www\.)?tiktok\.com\/t\/\w+\/?/gi;

/** The TikToks in a message (its text and its link previews), each once, at most three: they get a card. */
export function tiktokLinks(...sources: (string | null | undefined)[]): string[] {
  const out: string[] = [];
  for (const s of sources) for (const m of String(s ?? "").match(TT_LINK) ?? []) if (!out.includes(m)) out.push(m);
  return out.slice(0, 3);
}

/** A TikTok person's @handle out of their id ("tt_theo-wav" is "theo.wav"). */
export function tiktokHandle(uid: string): string {
  return uid.startsWith("tt_") ? uid.slice(3).replace(/-/g, ".") : "";
}

/** An Instagram person's username out of their id ("ig_theo-wav" is "theo.wav"); "" for a group of theirs. */
export function instagramHandle(uid: string): string {
  return uid.startsWith("ig_") ? uid.slice(3).replace(/-/g, ".") : "";
}

/**
 * The phone number or email an iMessage person's id was made from (bluebubbles.js personId): "im_p33612345678" is
 * "+33612345678", an email's every other character written as _<its code>_. "" for a group, or a hashed id.
 */
export function imessageAddress(uid: string): string {
  const s = String(uid ?? "");
  if (!s.startsWith("im_") || /^im_h[0-9a-f]{24}$/.test(s)) return "";
  const rest = s.slice(3);
  if (/^p\d{3,20}$/.test(rest)) return `+${rest.slice(1)}`;
  if (/^\d{3,20}$/.test(rest)) return rest;
  try {
    return rest.replace(/_([0-9a-f]{1,6})_/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)));
  } catch {
    return "";
  }
}

/** Whoever a person is on a platform that names its people that way; "" on the others. */
export function handleOf(uid: string): string {
  return tiktokHandle(uid) || instagramHandle(uid) || xHandle(uid) || redditUser(uid) || whatsappNumber(uid)
    || imessageAddress(uid);
}

/** A WhatsApp person's number from their id ("wa_447700900123"), "" for a group or anyone else's. */
export function whatsappNumber(uid: string): string {
  const s = String(uid ?? "");
  return s.startsWith("wa_") ? s.slice(3) : "";
}

/** An X person's @handle from their id ("x_theo_wav"), "" for a group message or anyone else's. */
export function xHandle(uid: string): string {
  const s = String(uid ?? "");
  return s.startsWith("x_") ? s.slice(2) : "";
}

/** A Reddit person's username from their id ("rd_theo-wav"); its hyphens are real, so nothing is read out. */
export function redditUser(uid: string): string {
  const s = String(uid ?? "");
  return s.startsWith("rd_") ? s.slice(3) : "";
}

const IG_LINK = /https?:\/\/(?:(?:www|m)\.)?instagram\.com\/(?:[\w.]+\/)?(?:p|reel|reels|tv)\/[\w-]+\/?|https?:\/\/(?:(?:www|m)\.)?instagram\.com\/stories\/[\w.]+\/\d+\/?/gi;

// A link to one Reddit post, however it was written: the permalink, one comment under it, or a redd.it short one.
const REDDIT_LINK = /https?:\/\/(?:(?:www|old|new|np|m)\.)?reddit\.com\/(?:r\/[A-Za-z0-9_]{2,21}\/)?comments\/[a-z0-9]{2,12}[\w\-/]*|https?:\/\/redd\.it\/[a-z0-9]{2,12}/gi;
// And one X post, on either of X's two names. The first post on the site is /status/20, so any run of digits.
const X_LINK = /https?:\/\/(?:(?:www|mobile)\.)?(?:x|twitter)\.com\/[A-Za-z0-9_]{1,15}\/status\/\d{1,25}/gi;

/** The Reddit posts in a message (its text and its link previews), each once, at most three: they get a card. */
export function redditLinks(...sources: (string | null | undefined)[]): string[] {
  const out: string[] = [];
  for (const s of sources) for (const m of String(s ?? "").match(REDDIT_LINK) ?? []) if (!out.includes(m)) out.push(m);
  return out.slice(0, 3);
}

/** The X posts in a message, the same way. */
export function xLinks(...sources: (string | null | undefined)[]): string[] {
  const out: string[] = [];
  for (const s of sources) for (const m of String(s ?? "").match(X_LINK) ?? []) if (!out.includes(m)) out.push(m);
  return out.slice(0, 3);
}

/** The Instagram posts in a message (its text and its link previews), each once, at most three: they get a card. */
export function instagramLinks(...sources: (string | null | undefined)[]): string[] {
  const out: string[] = [];
  for (const s of sources) for (const m of String(s ?? "").match(IG_LINK) ?? []) if (!out.includes(m)) out.push(m);
  return out.slice(0, 3);
}
