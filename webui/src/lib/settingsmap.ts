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
  panel?: "theme" | "typeface" | "interface" | "profiles" | "snapchat-setup" | "env" | "local"
    | "models" | "providers" | "usage" | "telegram" | "pictures";
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
    icon: "discord",
    blurb: "Where it replies, triggers, presence",
    owns: ["discord"],
    // No Tokens subtab: accounts, their tokens and proxies are added, edited and
    // removed on the Accounts page, and this was the same list a second time.
    // The raw values are still under App, All variables.
    subs: [
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
        // The trigger words moved to the Persona page, as the names it answers to.
        id: "triggers",
        name: "Commands",
        blurb: "Who may command it, and how.",
        keys: ["bot.owner_id", "bot.prefix", "bot.priority_prefix"],
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
        name: "Client",
        blurb: "What the account looks like to Discord. Leave it alone unless you know why not.",
        keys: [
          "bot.client_profile",
          "bot.timezone",
          "bot.locale",
          "bot.desktop.build_source",
          "bot.desktop.build_number",
          "bot.cache.max_messages",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "snapchat",
    name: "Snapchat",
    icon: "snapchat",
    blurb: "Install, browser, pacing",
    owns: ["snapchat"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "Snapchat has no API, so it drives a real browser.",
        panel: "snapchat-setup",
      },
      {
        id: "browser",
        name: "Browser",
        blurb: "The Chrome it drives: whether you see it, and how long it waits on it.",
        keys: [
          "snapchat.headless",
          "snapchat.response_timeout_ms",
          "snapchat.verify_wait_ms",
          "snapchat.reload_interval_ms",
        ],
      },
      {
        // "pacing" as an id, so links made before the rename still land here.
        id: "pacing",
        name: "Behaviour",
        blurb: "How often it looks, how fast it may send, and friend requests.",
        keys: [
          "snapchat.poll_interval_ms",
          "snapchat.max_recipients",
          "snapchat.min_send_gap_ms",
          "snapchat.max_send_gap_ms",
          "snapchat.max_sends_per_hour",
          "snapchat.quiet_hours",
          "snapchat.auto_add_friends",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "groq",
    // Still "groq" as an id, because released builds and the doctor point at it
    // by that name. It covers every provider now.
    name: "Models",
    icon: "sparkle",
    blurb: "Which AI writes, sees, hears and speaks",
    subs: [
      {
        id: "models",
        name: "Models",
        blurb: "Which model does each job, and what takes over when one is busy.",
        panel: "models",
      },
      {
        // "keys" as an id for the same reason: links to Groq's keys land here.
        id: "keys",
        name: "Providers",
        blurb: "Connect the services the models come from.",
        panel: "providers",
      },
      {
        id: "local",
        name: "This computer",
        blurb: "Run models on this machine. No rate limits, and nothing leaves it.",
        panel: "local",
      },
      {
        id: "usage",
        name: "Usage",
        blurb: "What each model has done today, and what is left of its limits.",
        panel: "usage",
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
        // Reply style and human touches used to be two subtabs, the first
        // holding a single setting. Reactions used to sit here too; they are on
        // the Persona page, with the moods, because how often this character
        // laughs at something without a word is a trait, not a preference.
        id: "style",
        name: "How it talks",
        blurb: "How long its replies are, the language it falls back to, typos, and not answering everything.",
        keys: [
          "bot.message_style.mode",
          "bot.message_style.max_chunk_chars",
          "bot.default_language",
          "bot.typo_chance",
          "bot.edit_after_send_chance",
          "bot.ignore_chance",
          "bot.trigger_bypasses_ignore",
          "bot.mention_bypasses_ignore",
        ],
      },
      {
        id: "typing",
        name: "Typing",
        blurb: "How long it reads and thinks before a reply, and how fast it types it.",
        keys: [
          "bot.realistic_typing",
          "bot.typing.wpm_min",
          "bot.typing.wpm_max",
          "bot.typing.think_min",
          "bot.typing.think_max",
          "bot.typing.pause_chance",
          "bot.typing.max_seconds",
          "bot.read_delay_dm_min",
          "bot.read_delay_dm_max",
          "bot.read_delay_group_min",
          "bot.read_delay_group_max",
          "bot.read_delay_server_min",
          "bot.read_delay_server_max",
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
        // The switches for pictures and voice notes as rows, and under them a
        // panel of its own (PicturesPanel.svelte): the look new pictures get,
        // and what the AI may put on a picture as it sends it, on which accounts.
        id: "media",
        name: "Pictures and voice",
        blurb: "Sending a selfie or a voice note, filters on pictures, and what the AI may add to one.",
        panel: "pictures",
        keys: [
          "bot.pictures.enabled",
          "bot.pictures.video_max_mb",
          "bot.tts.enabled",
          "bot.tts.voice",
          "bot.tts.tones",
          "bot.pictures.auto_look.mode",
          "bot.pictures.auto_look.look",
          "bot.pictures.auto_look.looks",
          "bot.pictures.auto_look.strength",
          "bot.pictures.auto_look.vary",
          "bot.pictures.touches.accounts",
          "bot.pictures.touches.chance",
          "bot.pictures.touches.kinds",
        ],
      },
      {
        id: "summaries",
        name: "Memory summaries",
        blurb: "The conversation summary shown when you open someone on the Memory page.",
        keys: [
          "bot.memory_summary.enabled",
          "bot.memory_summary.messages",
          "bot.memory_summary.length",
          "bot.memory_summary.language",
          "bot.memory_summary.include_my_messages",
          "bot.memory_summary.refresh_minutes",
        ],
      },
      {
        id: "sampling",
        name: "How it writes",
        blurb: "The sampling settings sent with every reply, where the provider takes them.",
        keys: [
          "bot.sampling.temperature",
          "bot.sampling.top_p",
          "bot.sampling.frequency_penalty",
          "bot.sampling.presence_penalty",
        ],
      },
      {
        id: "refusal",
        name: "Refusals",
        blurb: "Catching a reply that sounds like an assistant, and what to send instead.",
        keys: [
          "bot.refusal.enabled",
          "bot.refusal.fallbacks",
          "bot.refusal.extra_phrases",
          "bot.refusal.replace_phrases",
        ],
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
        // One switch a platform: each is drawn over both of its keys
        // (services.X.enabled and X.enabled), which both had to be on.
        id: "services",
        name: "What runs",
        blurb: "What starts with the app, and where the WebUI is served.",
        keys: [
          "services.discord.enabled",
          "discord.enabled",
          "services.snapchat.enabled",
          "snapchat.enabled",
          "services.telegram.enabled",
          "services.webui.enabled",
          "services.webui.port",
          "services.webui.bind",
        ],
      },
      {
        // Its own panel (TelegramPanel.svelte): connecting the bot step by
        // step, checking it, and what it can do. Two env values in boxes was
        // all there was, with the template's placeholder text in them. Its
        // alerts are here too, below the panel, since only it sends them.
        id: "telegram",
        name: "Telegram",
        blurb: "An optional second way to drive the bot, from your phone.",
        panel: "telegram",
        keys: [
          "notifications.telegram_error_notifications",
          "notifications.telegram_crash_alerts",
          "notifications.telegram_quiet",
        ],
      },
      {
        id: "alerts",
        name: "Error alerts",
        blurb: "Being told when something breaks, on a Discord webhook.",
        keys: [
          "notifications.error_webhook",
          "notifications.ratelimit_notifications",
        ],
      },
      {
        id: "profiles",
        name: "Stored profiles",
        blurb: "Names, avatars and bios kept on this machine.",
        panel: "profiles",
        // Drawn by the panel; named here so it is not listed again elsewhere.
        keys: ["bot.profile_cache.enabled"],
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
  "groq keys": "groq/keys",
  "groq api keys": "groq/keys",
  "groq models": "groq/models",
  "models": "groq/models",
  "ai provider": "groq/models",
  "providers": "groq/keys",
  "this computer": "groq/local",
  "local ai": "groq/local",
  "local models": "groq/local",
  usage: "groq/usage",
  "model usage": "groq/usage",
  "rate limits": "groq/usage",
  "snapchat setup": "snapchat/setup",
  telegram: "app/telegram",
  services: "app/services",
  "webui": "app/services",
  "control panel": "app/services",
  "error alerts": "app/alerts",
  // The old flat category names.
  general: "discord/triggers",
  behaviour: "discord/replies",
  humanization: "ai/style",
  conversation: "ai/followups",
  mood: "ai/style",
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
