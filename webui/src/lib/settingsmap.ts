/**
 * How Settings is organised: tabs, and subtabs inside them.
 *
 * Settings used to be one flat list of 82 rows split into nine categories named
 * after the config file's own structure ("Humanization", "Conversation"), with
 * most rows hidden behind a "show 14 more advanced settings" button. Nothing
 * told you that the Discord token, the reply rules and the presence schedule
 * were the same subject, so finding anything meant searching for it.
 *
 * Now the top level is the thing you are configuring (Discord, Snapchat, Groq,
 * how the AI behaves, the app itself) and the second level is the part of it.
 * Every subtab is small enough to show in full, so nothing is hidden.
 *
 * A subtab is either a list of config keys, in the order written here, or a
 * bespoke panel. Keys named here that are absent from config.yaml are skipped,
 * and keys in config.yaml that are named nowhere land in the owning tab's
 * "Everything else" subtab, so a setting added later still gets a control.
 */

export type Sub = {
  id: string;
  name: string;
  blurb?: string;
  /** Config keys, in display order. */
  keys?: string[];
  /** A bespoke panel instead of a key list. */
  panel?: "theme" | "typeface" | "interface" | "profiles" | "snapchat-setup" | "env" | "local";
  /** For panel "env": which .env sections and key families to show. */
  env?: { sections?: string[]; keyLists?: string[]; extras?: boolean };
  /** Collects whatever keys in `owns` no subtab claimed. */
  rest?: boolean;
};

export type Tab = {
  id: string;
  name: string;
  icon: string;
  blurb: string;
  /** Dotted key prefixes whose leftovers belong to this tab. */
  owns?: string[];
  subs: Sub[];
};

export const TABS: Tab[] = [
  {
    id: "discord",
    name: "Discord",
    icon: "accounts",
    blurb: "Tokens, where it replies, presence",
    owns: ["discord"],
    subs: [
      {
        id: "tokens",
        name: "Tokens",
        blurb: "One token per account. Each runs on its own.",
        panel: "env",
        env: { sections: ["Discord"], keyLists: ["discord"] },
      },
      {
        id: "replies",
        name: "Where it replies",
        blurb: "Which chats it answers in, and how.",
        keys: [
          "bot.allow_dm",
          "bot.allow_gc",
          "bot.allow_server",
          "bot.hold_conversation",
          "bot.reply_ping",
          "bot.read_bios",
          "bot.disable_mentions",
          "bot.anti_age_ban",
        ],
      },
      {
        id: "triggers",
        name: "Commands and triggers",
        blurb: "What makes it reply, and who may command it.",
        keys: ["bot.owner_id", "bot.prefix", "bot.priority_prefix", "bot.trigger"],
      },
      {
        id: "friends",
        name: "Friend requests",
        blurb: "Answered on a timer so it does not look automated.",
        keys: [
          "bot.friend_requests.enabled",
          "bot.friend_requests.accept_delay_min",
          "bot.friend_requests.accept_delay_max",
        ],
      },
      {
        id: "presence",
        name: "Presence",
        blurb: "Custom status, and going invisible at night.",
        keys: [
          "bot.status.enabled",
          "bot.status.statuses",
          "bot.status.change_interval_min",
          "bot.status.change_interval_max",
          "bot.night_invisible.enabled",
          "bot.night_invisible.hours",
          "bot.night_invisible.timezone",
          "bot.night_invisible.status",
        ],
      },
      {
        id: "fingerprint",
        name: "Client fingerprint",
        blurb: "What the account looks like to Discord. Leave it alone unless you know why not.",
        keys: [
          "bot.client_profile",
          "bot.timezone",
          "bot.locale",
          "bot.default_language",
          "bot.desktop.build_source",
          "bot.desktop.build_number",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "snapchat",
    name: "Snapchat",
    icon: "snapchat",
    blurb: "Install, logins, pacing",
    owns: ["snapchat"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "Snapchat has no API, so it drives a real browser.",
        panel: "snapchat-setup",
      },
      {
        id: "logins",
        name: "Logins",
        blurb: "Each login gets its own browser and cookies.",
        panel: "env",
        env: { sections: ["Snapchat account"], keyLists: ["snapchat"] },
      },
      {
        id: "browser",
        name: "Browser",
        keys: ["snapchat.headless", "snapchat.response_timeout_ms"],
      },
      {
        id: "pacing",
        name: "Polling and limits",
        blurb: "How often it looks, and how fast it is allowed to send.",
        keys: [
          "snapchat.poll_interval_ms",
          "snapchat.max_recipients",
          "snapchat.min_send_gap_ms",
          "snapchat.max_send_gap_ms",
          "snapchat.max_sends_per_hour",
          "snapchat.quiet_hours",
        ],
      },
      { id: "friends", name: "Friends", keys: ["snapchat.auto_add_friends"] },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "groq",
    // Still "groq" as an id, because released builds and the doctor point at it
    // by that name. The tab covers both providers now.
    name: "AI provider",
    icon: "sparkle",
    blurb: "Keys, models, and running it locally",
    subs: [
      {
        id: "keys",
        name: "API keys",
        blurb:
          "When one hits its rate limit the bot falls through to the next, then to the next model.",
        panel: "env",
        env: { sections: ["Groq API"], keyLists: ["groq"] },
      },
      {
        id: "models",
        name: "Models",
        blurb: "Each picker only offers models that can do that particular job.",
        keys: [
          "bot.groq_models",
          "bot.groq_small_model",
          "bot.max_reply_tokens",
          "bot.groq_image_model",
          "bot.groq_whisper_model",
          "bot.groq_tts_model",
        ],
      },
      {
        id: "local",
        name: "Local AI",
        blurb:
          "Write replies on this machine instead. No rate limits, no key, nothing leaves the computer.",
        panel: "local",
      },
    ],
  },

  {
    id: "ai",
    name: "AI behaviour",
    icon: "persona",
    blurb: "How human it reads",
    owns: ["bot"],
    subs: [
      {
        id: "style",
        name: "Reply style",
        // Reactions used to sit here. They are on the Persona page now, with
        // the moods, because how often this character laughs at something
        // without saying anything is a trait and not a preference.
        blurb: "How long replies are, and how they are broken up.",
        keys: ["bot.message_style.mode", "bot.message_style.max_chunk_chars"],
      },
      {
        id: "human",
        name: "Human touches",
        blurb: "Typing, typos, and not answering everything.",
        keys: [
          "bot.realistic_typing",
          "bot.typo_chance",
          "bot.edit_after_send_chance",
          "bot.ignore_chance",
          "bot.trigger_bypasses_ignore",
          "bot.mention_bypasses_ignore",
        ],
      },
      {
        id: "timing",
        name: "Timing",
        blurb: "Waiting out a burst of messages, and pacing between replies.",
        keys: [
          "bot.batch_messages",
          "bot.batch_wait_times",
          "bot.server_batch_wait_times",
          "bot.global_cooldown_enabled",
          "bot.global_cooldown_min",
          "bot.global_cooldown_max",
        ],
      },
      {
        id: "followups",
        name: "Follow-ups",
        blurb: "Coming back to a conversation late, or first.",
        keys: [
          "bot.late_reply.enabled",
          "bot.late_reply.threshold",
          "bot.stale_reply.enabled",
          "bot.stale_reply.max_messages",
          "bot.stale_reply.min_age",
          "bot.nudge.enabled",
          "bot.nudge.threshold_days",
          "bot.nudge.check_interval_hours",
          "bot.nudge.send_during_hours",
        ],
      },
      {
        id: "media",
        name: "Pictures and voice",
        blurb: "Sending a selfie or a voice note when it fits.",
        keys: ["bot.pictures.enabled", "bot.tts.enabled", "bot.tts.voice", "bot.tts.tones"],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "app",
    name: "App",
    icon: "system",
    blurb: "What runs, alerts, stored data",
    owns: ["services", "notifications"],
    subs: [
      {
        id: "services",
        name: "What runs",
        blurb: "Both switches for a platform have to be on for it to start.",
        keys: [
          "services.discord.enabled",
          "discord.enabled",
          "services.snapchat.enabled",
          "snapchat.enabled",
          "services.telegram.enabled",
          "services.webui.enabled",
        ],
      },
      {
        id: "panel",
        name: "webui",
        blurb: "This page, and who can reach it.",
        keys: ["services.webui.port", "services.webui.bind"],
      },
      {
        id: "telegram",
        name: "Telegram",
        blurb: "An optional second way to drive the bot, from your phone.",
        panel: "env",
        env: { sections: ["Telegram control bot"] },
      },
      {
        id: "alerts",
        name: "Error alerts",
        blurb: "Being told when something breaks.",
        keys: [
          "notifications.telegram_error_notifications",
          "notifications.error_webhook",
          "notifications.ratelimit_notifications",
        ],
      },
      {
        id: "profiles",
        name: "Stored profiles",
        blurb: "Names, avatars and bios kept on this machine.",
        panel: "profiles",
      },
      {
        id: "env",
        name: "All variables",
        blurb: "Every value in config/.env, including the ones nothing else shows.",
        panel: "env",
        env: { extras: true },
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "look",
    name: "Appearance",
    icon: "palette",
    blurb: "Theme, typeface, motion",
    subs: [
      { id: "theme", name: "Theme", panel: "theme" },
      { id: "typeface", name: "Typeface", panel: "typeface" },
      { id: "motion", name: "Interface", blurb: "Motion and decoration.", panel: "interface" },
    ],
  },
];

/** `tab/sub` for every subtab, flattened, for search results and deep links. */
export const PATHS: { tab: Tab; sub: Sub; path: string }[] = TABS.flatMap((tab) =>
  tab.subs.map((sub) => ({ tab, sub, path: `${tab.id}/${sub.id}` })),
);

/** Which subtab a key is listed in, or undefined if none claims it. */
const KEY_HOME: Record<string, string> = {};
for (const { sub, path } of PATHS) for (const k of sub.keys ?? []) KEY_HOME[k] = path;

export const homeOf = (key: string): string | undefined => KEY_HOME[key];

/**
 * Which tab's leftovers a key belongs to, by longest matching prefix.
 *
 * Without this a setting added to config.yaml later would have a control
 * nowhere, which is the bug the auto discovered list was written to fix.
 */
export function restHomeOf(key: string): string | undefined {
  let best: { path: string; len: number } | undefined;
  for (const tab of TABS) {
    const rest = tab.subs.find((s) => s.rest);
    if (!rest) continue;
    for (const prefix of tab.owns ?? []) {
      if ((key === prefix || key.startsWith(prefix + ".")) && prefix.length > (best?.len ?? -1)) {
        best = { path: `${tab.id}/${rest.id}`, len: prefix.length };
      }
    }
  }
  return best?.path;
}

/**
 * Names other parts of the app use to point here, mapped onto a subtab.
 *
 * The dependency doctor and the health banners send you straight to the setting
 * that is wrong. They name it in words, not as `tab/sub`, and the old category
 * names are baked into released builds and into tests, so both spellings work.
 */
const ALIASES: Record<string, string> = {
  // Current, written as words.
  "discord tokens": "discord/tokens",
  "groq keys": "groq/keys",
  "groq api keys": "groq/keys",
  "groq models": "groq/models",
  "local ai": "groq/local",
  "local models": "groq/local",
  "snapchat setup": "snapchat/setup",
  "snapchat logins": "snapchat/logins",
  telegram: "app/telegram",
  services: "app/services",
  "webui": "app/panel",
  "control panel": "app/panel",
  "error alerts": "app/alerts",
  // The old flat category names.
  general: "discord/triggers",
  behaviour: "discord/replies",
  humanization: "ai/human",
  conversation: "ai/followups",
  mood: "ai/human",
  status: "discord/presence",
  notifications: "app/alerts",
  snapchat: "snapchat/setup",
  appearance: "look/theme",
  environment: "app/env",
  "keys and secrets": "app/env",
};

/**
 * Resolve whatever another page asked for into a `tab/sub` path.
 *
 * Accepts a path, a tab id, an alias, a tab or subtab name, or a config key.
 */
export function resolveTarget(want: string): string | undefined {
  const q = want.trim().toLowerCase();
  if (!q) return undefined;

  if (PATHS.some((p) => p.path === q)) return q;
  if (ALIASES[q]) return ALIASES[q];

  // A config key, so an issue can point at the exact setting.
  if (KEY_HOME[want]) return KEY_HOME[want];
  if (restHomeOf(want)) return restHomeOf(want);

  const tab = TABS.find((t) => t.id === q || t.name.toLowerCase() === q);
  if (tab) return `${tab.id}/${tab.subs[0].id}`;

  const byName = PATHS.find((p) => p.sub.name.toLowerCase() === q);
  if (byName) return byName.path;

  // Last resort: a leading word match, so "Snapchat browser" still lands.
  const starts = PATHS.find(
    (p) => `${p.tab.name} ${p.sub.name}`.toLowerCase().startsWith(q) || q.startsWith(p.tab.id),
  );
  return starts?.path;
}
