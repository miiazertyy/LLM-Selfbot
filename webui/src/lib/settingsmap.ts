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
  panel?: "theme" | "typeface" | "interface" | "profiles" | "snapchat-setup" | "tiktok-setup"
    | "instagram-setup" | "x-setup" | "reddit-setup" | "whatsapp-setup" | "minecraft-setup"
    | "imessage-setup" | "discord-setup" | "telegram-setup" | "env" | "local"
    | "models" | "providers" | "usage" | "telegram" | "pictures" | "calls";
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
  /** Which run of tabs it sits in; ORDER below sets it, and the nav draws a hairline where it changes. */
  group?: Group;
};

/** The runs the nav shows, top to bottom: the app itself, the brain it answers with, then the places it talks. */
export type Group = "app" | "brain" | "chats" | "feeds" | "games";

const DEFINED: Tab[] = [
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
        // In the order the tabs are in (ORDER, below), so the switch for a
        // platform is in the same place in this list as its tab is in the nav.
        keys: [
          "services.discord.enabled",
          "discord.enabled",
          "services.telegram_accounts.enabled",
          "telegram.enabled",
          "services.whatsapp.enabled",
          "whatsapp.enabled",
          "services.imessage.enabled",
          "imessage.enabled",
          "services.snapchat.enabled",
          "snapchat.enabled",
          "services.instagram.enabled",
          "instagram.enabled",
          "services.tiktok.enabled",
          "tiktok.enabled",
          "services.x.enabled",
          "x.enabled",
          "services.reddit.enabled",
          "reddit.enabled",
          "services.minecraft.enabled",
          "minecraft.enabled",
          // Not a platform: the bot you send commands to, and the panel itself.
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
        blurb: "How much each provider says is left, and what each model has done today.",
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
        id: "careful",
        name: "Careful mode",
        blurb: "For a new or precious account: slower, quieter, and nothing public until the date passes.",
        keys: [
          "bot.conservative.enabled",
          "bot.conservative.until",
          "bot.conservative.reply_scale",
          "bot.conservative.wait_scale",
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
        id: "videos",
        name: "Videos they send",
        blurb: "Watching the videos people send, on every platform: clips, video snaps, Spotlights, TikToks.",
        keys: [
          "bot.videos.enabled",
          "bot.videos.listen",
          "bot.videos.max_seconds",
        ],
      },
      {
        // The web (app/utils/web): a look online when a message needs one, the links people send, and its free time.
        id: "web",
        name: "The web",
        blurb: "Looking things up, the links people send, and browsing in its free time.",
        keys: [
          // What it may do, then how much of it, then the free-time browsing
          // with its own cap: the two caps used to sit either side of it.
          "bot.web.enabled",
          "bot.web.links",
          "bot.web.search_with",
          "bot.web.share_links",
          "bot.web.per_hour",
          "bot.web.free_time",
          "bot.web.sessions_per_day",
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
    // Calls were a subtab of AI behaviour, below pictures and voice notes.
    // They have their own models (who hears, thinks and speaks), their own
    // voice to pick, and Try a call, which is the whole call brain with your
    // microphone standing in for the other person: too much for one row in a
    // list of nine other things.
    id: "calls",
    name: "Calls",
    icon: "phone",
    blurb: "Which models talk, its voice, picking up",
    owns: ["bot.calls"],
    subs: [
      {
        id: "voice",
        name: "How it sounds",
        blurb: "What hears, thinks and speaks on a call, the voice it talks in, and trying one.",
        panel: "calls",
        keys: [
          "bot.calls.engine",
          "bot.calls.realtime_provider",
          "bot.calls.realtime_model",
          "bot.calls.realtime_voice",
          "bot.calls.speaker",
          "bot.calls.voice",
          "bot.calls.hear",
          "bot.calls.think",
          "bot.calls.speak",
        ],
      },
      {
        id: "picking-up",
        name: "Picking up",
        blurb: "Whose calls it takes, and for how long.",
        keys: [
          "bot.calls.enabled",
          "bot.calls.answer",
          "bot.calls.ring_seconds",
          "bot.calls.max_minutes",
          "bot.calls.quiet_hours",
          "bot.calls.per_day",
          "bot.calls.remember",
          "bot.calls.you_can_dial",
          "bot.calls.vc",
          "bot.calls.reply_ring",
        ],
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
        id: "setup",
        name: "Setup",
        blurb: "What it needs, and how each account is doing.",
        panel: "discord-setup",
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
        id: "gifts",
        name: "Nitro gifts",
        blurb: "What happens when someone sends one in a DM.",
        keys: ["discord.gifts.mode", "discord.gifts.only_friends"],
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
    blurb: "Install, browser, behaviour",
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
          "snapchat.pictures.as_chat_picture",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "tiktok",
    name: "TikTok",
    icon: "tiktok",
    blurb: "Install, watching, For You, likes, posting, LIVE",
    owns: ["tiktok"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "TikTok has no API an account can use, so it drives a real browser, the same one as Snapchat.",
        panel: "tiktok-setup",
      },
      {
        id: "browser",
        name: "Browser",
        blurb: "Its Chrome window, and how long it waits.",
        keys: [
          "tiktok.headless",
          "tiktok.response_timeout_ms",
          "tiktok.reload_interval_ms",
        ],
      },
      {
        id: "pacing",
        name: "Behaviour",
        blurb: "How often it looks, how fast it may send, requests and followers.",
        keys: [
          "tiktok.poll_interval_ms",
          "tiktok.max_recipients",
          "tiktok.min_send_gap_ms",
          "tiktok.max_send_gap_ms",
          "tiktok.max_sends_per_hour",
          "tiktok.quiet_hours",
          "tiktok.accept_message_requests",
          "tiktok.follow_back",
          "tiktok.night_activity_status",
        ],
      },
      {
        id: "watching",
        name: "Watching",
        blurb: "Watching the TikToks people send, on every platform.",
        keys: [
          "tiktok.watch.enabled",
          "tiktok.watch.their_posts",
        ],
      },
      {
        id: "foryou",
        name: "For You",
        blurb: "Scrolling For You now and then, and sharing what it saw.",
        keys: [
          "tiktok.foryou.enabled",
          "tiktok.foryou.sessions_per_day",
          "tiktok.foryou.minutes",
          "tiktok.foryou.like_percent",
          "tiktok.share.enabled",
        ],
      },
      {
        id: "engage",
        name: "Likes and comments",
        blurb: "Liking and commenting on other people's videos, in public.",
        keys: [
          "tiktok.engage.like_sent",
          "tiktok.engage.like_theirs",
          "tiktok.engage.comment_sent",
          "tiktok.engage.comment_theirs",
          "tiktok.engage.mentions",
          "tiktok.engage.likes_per_day",
          "tiktok.engage.comments_per_day",
        ],
      },
      {
        id: "posting",
        name: "Posting",
        blurb: "Posting the persona's videos, from the Pictures page.",
        keys: [
          "tiktok.posting.enabled",
          "tiktok.posting.per_day",
          "tiktok.posting.privacy",
        ],
      },
      {
        id: "comments",
        name: "Comments",
        blurb: "Answering new comments under its own videos, in public.",
        keys: [
          "tiktok.comments.enabled",
          "tiktok.comments.per_hour",
          "tiktok.comments.videos",
        ],
      },
      {
        id: "live",
        name: "LIVE",
        blurb: "Co-hosting its LIVE: answers in the chat and out loud.",
        keys: [
          "tiktok.live.enabled",
          "tiktok.live.chat",
          "tiktok.live.voice",
          "tiktok.live.per_minute",
          "tiktok.live.reply_delay",
        ],
      },
      {
        id: "live-answers",
        name: "LIVE answers",
        blurb: "What it answers on its LIVE, and what it lets go.",
        keys: [
          "tiktok.live.answer_comments",
          "tiktok.live.answer_mode",
          "tiktok.live.thank_gifts",
          "tiktok.live.gift_min_coins",
          "tiktok.live.welcome_follows",
          "tiktok.live.greet_joins",
          "tiktok.live.thank_shares",
          "tiktok.live.thank_likes",
          "tiktok.live.viewer_cooldown",
          "tiktok.live.max_per_viewer",
          "tiktok.live.skip_emoji_only",
          "tiktok.live.blocked_words",
          "tiktok.live.ignore_viewers",
        ],
      },
      {
        id: "live-style",
        name: "LIVE style",
        blurb: "How it sounds on its LIVE.",
        keys: [
          "tiktok.live.tone",
          "tiktok.live.topic",
          "tiktok.live.language",
          "tiktok.live.max_words",
          "tiktok.live.use_names",
          "tiktok.live.emoji",
          "tiktok.live.read_comment",
          "tiktok.live.fill_silence",
          "tiktok.live.silence_seconds",
        ],
      },
      {
        id: "live-overlay",
        name: "OBS page",
        blurb: "How its answers show on the OBS page, over the stream.",
        keys: [
          "tiktok.live.overlay_seconds",
          "tiktok.live.overlay_position",
          "tiktok.live.overlay_comment",
          "tiktok.live.overlay_size",
          "tiktok.live.overlay_theme",
        ],
      },
      {
        id: "visits",
        name: "Visiting LIVEs",
        blurb: "Joining other people's LIVEs as a viewer.",
        keys: [
          "tiktok.visits.enabled",
          "tiktok.visits.chats",
          "tiktok.visits.shared",
          "tiktok.visits.following",
          "tiktok.visits.stay_minutes",
          "tiktok.visits.lines_per_5min",
          "tiktok.visits.per_day",
          "tiktok.visits.follow_host",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "instagram",
    name: "Instagram",
    icon: "instagram",
    blurb: "Install, watching, stories, Reels, likes, posting",
    owns: ["instagram"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "Instagram has no API an account can use, so it drives a real browser, the same one as Snapchat.",
        panel: "instagram-setup",
      },
      {
        id: "browser",
        name: "Browser",
        blurb: "Its Chrome window, and how long it waits.",
        keys: [
          "instagram.headless",
          "instagram.response_timeout_ms",
          "instagram.reload_interval_ms",
        ],
      },
      {
        id: "pace",
        name: "Behaviour",
        blurb: "How often it looks, how fast it may send, requests and followers.",
        keys: [
          "instagram.poll_interval_ms",
          "instagram.max_recipients",
          "instagram.min_send_gap_ms",
          "instagram.max_send_gap_ms",
          "instagram.max_sends_per_hour",
          "instagram.quiet_hours",
          "instagram.accept_message_requests",
          "instagram.follow_back",
          "instagram.accept_follow_requests",
          "instagram.night_activity_status",
        ],
      },
      {
        id: "watching",
        name: "Watching",
        blurb: "Watching the reels and posts people send, on every platform.",
        keys: [
          "instagram.watch.enabled",
          "instagram.watch.their_posts",
          "instagram.watch.voice_notes",
        ],
      },
      {
        id: "stories",
        name: "Stories",
        blurb: "Watching their stories, answering some, and putting up its own.",
        keys: [
          "instagram.stories.watch",
          "instagram.stories.reply",
          "instagram.stories.replies_per_day",
          "instagram.stories.post",
          "instagram.stories.post_per_day",
        ],
      },
      {
        id: "reels",
        name: "Reels",
        blurb: "Scrolling Reels now and then, and sending one when asked.",
        keys: [
          "instagram.reels.enabled",
          "instagram.reels.sessions_per_day",
          "instagram.reels.minutes",
          "instagram.reels.like_percent",
          "instagram.share.enabled",
        ],
      },
      {
        id: "engage",
        name: "Likes and comments",
        blurb: "Liking and commenting on other people's posts, in public.",
        keys: [
          "instagram.engage.like_sent",
          "instagram.engage.like_theirs",
          "instagram.engage.comment_sent",
          "instagram.engage.comment_theirs",
          "instagram.engage.likes_per_day",
          "instagram.engage.comments_per_day",
        ],
      },
      {
        id: "posting",
        name: "Posting",
        blurb: "Posting the persona's pictures, from the Pictures page.",
        keys: [
          "instagram.posting.enabled",
          "instagram.posting.per_day",
        ],
      },
      {
        id: "comments",
        name: "Comments",
        blurb: "Answering new comments under its own posts, in public.",
        keys: [
          "instagram.comments.enabled",
          "instagram.comments.per_hour",
          "instagram.comments.posts",
        ],
      },
      {
        id: "notes",
        name: "Notes",
        blurb: "The little note above its name in everyone's inbox.",
        keys: [
          "instagram.notes.enabled",
          "instagram.notes.every_hours",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "x",
    name: "X",
    icon: "x",
    blurb: "Install, messages, replies, likes, posting",
    owns: ["x"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "X has no API an account can use, so it drives a real browser, the same one as Snapchat.",
        panel: "x-setup",
      },
      {
        id: "browser",
        name: "Browser",
        blurb: "Its Chrome window, and how long it waits.",
        keys: [
          "x.headless",
          "x.response_timeout_ms",
          "x.reload_interval_ms",
        ],
      },
      {
        id: "pace",
        name: "Behaviour",
        blurb: "How often it looks, how fast it may send, and message requests.",
        keys: [
          "x.poll_interval_ms",
          "x.max_recipients",
          "x.min_send_gap_ms",
          "x.max_send_gap_ms",
          "x.max_sends_per_hour",
          "x.quiet_hours",
          "x.accept_message_requests",
        ],
      },
      {
        id: "mentions",
        name: "Replies",
        blurb: "Answering the people who reply to it or @ it. Off until you switch it on: a public answer is public.",
        keys: [
          "x.mentions.enabled",
          "x.mentions.replies",
          "x.mentions.own_posts",
          "x.mentions.own_posts_watched",
          "x.mentions.per_hour",
          "x.mentions.per_pass",
          "x.mentions.scrolls",
          "x.mentions.skip_strangers",
        ],
      },
      {
        id: "watch",
        name: "Watching",
        blurb: "The posts people send it, and what the people it talks to are posting.",
        keys: [
          "x.watch.enabled",
          "x.watch.their_posts",
          "x.watch.threads",
        ],
      },
      {
        id: "engage",
        name: "Likes and follows",
        blurb: "What it does about other people's posts, and how much of it in a day.",
        keys: [
          "x.engage.like_sent",
          "x.engage.repost_sent",
          "x.engage.like_theirs",
          "x.engage.repost_theirs",
          "x.engage.follow_back",
          "x.engage.likes_per_day",
          "x.engage.reposts_per_day",
          "x.engage.follows_per_day",
          "x.engage.replies_per_day",
        ],
      },
      {
        id: "posting",
        name: "Posting",
        blurb: "Posts of its own, in its own voice.",
        keys: [
          "x.posting.enabled",
          "x.posting.from.saw_online",
          "x.posting.from.on_its_mind",
          "x.posting.per_day",
          "x.posting.min_gap_minutes",
          "x.posting.max_chars",
          "x.posting.thread_max",
          "x.posting.with_image",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },


  {
    id: "reddit",
    name: "Reddit",
    icon: "reddit",
    blurb: "Install, chats, replies, votes, comments, posting",
    owns: ["reddit"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "Reddit's API stopped taking new apps, so it drives a real browser, the same one as Snapchat.",
        panel: "reddit-setup",
      },
      {
        id: "browser",
        name: "Browser",
        blurb: "Its Chrome window, and how long it waits.",
        keys: [
          "reddit.headless",
          "reddit.response_timeout_ms",
          "reddit.reload_interval_ms",
        ],
      },
      {
        id: "pace",
        name: "Behaviour",
        blurb: "How often it looks, how fast it may send, and chat invitations.",
        keys: [
          "reddit.poll_interval_ms",
          "reddit.max_recipients",
          "reddit.min_send_gap_ms",
          "reddit.max_send_gap_ms",
          "reddit.max_sends_per_hour",
          "reddit.quiet_hours",
          "reddit.accept_chat_invites",
          // Both of these were on the Comments page. The subreddits are what it may post to as well, and a hidden
          // account stops everything public, not just its comments, so they belong to the whole account.
          "reddit.subreddits",
          "reddit.check_shadowban",
        ],
      },
      {
        id: "inbox",
        name: "Replies",
        blurb: "Answering the replies under its own posts, and anyone who writes its u/ name.",
        keys: [
          "reddit.inbox.enabled",
          "reddit.inbox.replies",
          "reddit.inbox.mentions",
          "reddit.inbox.per_hour",
          "reddit.inbox.per_pass",
          "reddit.inbox.scrolls",
          "reddit.inbox.skip_strangers",
        ],
      },
      {
        id: "watch",
        name: "Watching",
        blurb: "The posts people send it, and what the people it talks to are posting.",
        keys: [
          "reddit.watch.enabled",
          "reddit.watch.their_posts",
          "reddit.watch.threads",
          "reddit.watch.links",
        ],
      },
      {
        id: "engage",
        name: "Votes and follows",
        blurb: "What it does about other people's posts, and how much of it in a day.",
        keys: [
          "reddit.engage.upvote_sent",
          "reddit.engage.upvote_theirs",
          "reddit.engage.save",
          "reddit.engage.join_subs",
          "reddit.engage.follow_users",
          "reddit.engage.upvotes_per_day",
          "reddit.engage.joins_per_day",
          "reddit.engage.follows_per_day",
          "reddit.engage.replies_per_day",
        ],
      },
      {
        id: "comments",
        name: "Comments",
        blurb: "Commenting where nobody asked it to. Off until you switch it on, and only in the subreddits you list.",
        keys: [
          "reddit.comments.enabled",
          "reddit.comments.per_day",
          "reddit.comments.max_chars",
          "reddit.comments.fresh_only",
          "reddit.comments.min_score",
          "reddit.comments.skip_locked",
        ],
      },
      {
        id: "posting",
        name: "Posting",
        blurb: "Posts of its own, in its own voice.",
        keys: [
          "reddit.posting.enabled",
          "reddit.posting.where",
          "reddit.posting.from.saw_online",
          "reddit.posting.from.on_its_mind",
          "reddit.posting.per_day",
          "reddit.posting.min_gap_minutes",
          "reddit.posting.max_chars",
          "reddit.posting.with_image",
          "reddit.posting.flair",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },


  {
    id: "whatsapp",
    name: "WhatsApp",
    icon: "whatsapp",
    blurb: "Install, messages, groups, status, calls",
    owns: ["whatsapp"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "No browser at all: it speaks WhatsApp's own protocol, and a phone links it.",
        panel: "whatsapp-setup",
      },
      {
        id: "messages",
        name: "Messages",
        blurb: "What it answers, what it sends, and what it shows of itself while it does.",
        keys: [
          "whatsapp.burst_ms",
          "whatsapp.accept_unknown",
          "whatsapp.presence.typing",
          "whatsapp.presence.read_receipts",
          "whatsapp.presence.online",
          "whatsapp.media.voice_notes",
          "whatsapp.media.pictures",
        ],
      },
      {
        id: "groups",
        name: "Groups",
        blurb: "The groups it is in, and when it says anything in one.",
        keys: [
          "whatsapp.groups.enabled",
          "whatsapp.groups.only_when_named",
          "whatsapp.groups.max_per_pass",
          "whatsapp.groups.leave_on_request",
        ],
      },
      {
        id: "pace",
        name: "Pace",
        blurb: "How fast it may answer. Texting is quicker than a social site's messages.",
        keys: [
          "whatsapp.min_send_gap_ms",
          "whatsapp.max_send_gap_ms",
          "whatsapp.max_sends_per_hour",
          "whatsapp.quiet_hours",
          "whatsapp.poll_interval_ms",
          "whatsapp.response_timeout_ms",
        ],
      },
      {
        id: "watch",
        name: "Watching",
        blurb: "The pictures and videos people send it.",
        keys: [
          "whatsapp.watch.enabled",
          "whatsapp.watch.their_status",
        ],
      },
      {
        id: "status",
        name: "Status",
        blurb: "Watching the statuses of the people it talks to, and putting up its own.",
        keys: [
          "whatsapp.status.watch",
          "whatsapp.status.post",
          "whatsapp.status.per_day",
        ],
      },
      {
        id: "calls",
        name: "Calls",
        blurb: "It cannot take a call, so what it does about one instead.",
        keys: [
          "whatsapp.calls.decline",
          "whatsapp.calls.say_why",
          "whatsapp.calls.text",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "minecraft",
    name: "Minecraft",
    icon: "minecraft",
    blurb: "Install, the world it joins, how it plays",
    owns: ["minecraft"],
    subs: [
      {
        id: "setup",
        name: "Install",
        blurb: "It plays through mindcraft-ce, which is installed here, on demand.",
        panel: "minecraft-setup",
      },
      {
        // The server and the sign-in are each account's own, on the Accounts page: two accounts, two servers.
        id: "world",
        name: "World",
        blurb: "How it joins. Each account picks its own server on the Accounts page.",
        keys: [
          "minecraft.version",
          "minecraft.translate_versions",
          "minecraft.auto_login",
          "minecraft.view_distance",
          "minecraft.show_window",
        ],
      },
      {
        id: "servers",
        name: "Other servers",
        blurb: "Going to play somewhere else when asked.",
        keys: [
          "minecraft.join_when_asked",
          "minecraft.never_join",
        ],
      },
      {
        id: "playing",
        name: "Playing",
        blurb: "Who it talks with, and what it does by itself.",
        keys: [
          "minecraft.only_chat_with",
          "minecraft.greet",
          "minecraft.remember_world",
          "minecraft.modes.self_defense",
          "minecraft.modes.hunting",
          "minecraft.modes.item_collecting",
          "minecraft.modes.torch_placing",
          "minecraft.modes.cowardice",
          "minecraft.cooldown_ms",
        ],
      },
      {
        id: "thinking",
        name: "Thinking",
        blurb: "How much it may ask of the model.",
        keys: [
          "minecraft.persona",
          "minecraft.max_brain_calls_per_hour",
          "minecraft.brain_timeout_s",
          "minecraft.max_messages",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "imessage",
    name: "iMessage",
    icon: "imessage",
    blurb: "Texting through your iPhone, or a Mac",
    owns: ["imessage"],
    subs: [
      {
        id: "setup",
        name: "Setup",
        blurb: "Through your iPhone or iPad, or through a Mac.",
        panel: "imessage-setup",
      },
      {
        id: "texting",
        name: "Texting",
        blurb: "What it does as it answers. The first three need BlueBubbles' Private API.",
        keys: [
          "imessage.read_receipts",
          "imessage.typing_indicator",
          "imessage.tapbacks",
          "imessage.thread_replies",
          "imessage.effects",
          "imessage.fix_typos",
          "imessage.voice_notes",
          "imessage.facetime_text",
        ],
      },
      {
        id: "who",
        name: "Who it answers",
        blurb: "Group chats, and green bubble texts.",
        keys: [
          "imessage.groups",
          "imessage.answer_sms",
        ],
      },
      {
        id: "pace",
        name: "Pace",
        blurb: "How fast it answers, and when it does not.",
        keys: [
          "imessage.burst_ms",
          "imessage.min_send_gap_ms",
          "imessage.max_send_gap_ms",
          "imessage.max_sends_per_hour",
          "imessage.quiet_hours",
        ],
      },
      {
        id: "mac",
        name: "The Mac",
        blurb: "How it talks to BlueBubbles.",
        keys: [
          "imessage.send_method",
          "imessage.poll_interval_ms",
          "imessage.response_timeout_ms",
          "imessage.dry_run",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },

  {
    id: "telegram",
    name: "Telegram",
    icon: "telegram",
    blurb: "Its own account: texting, groups, pace",
    owns: ["telegram"],
    subs: [
      {
        id: "setup",
        name: "Setup",
        blurb: "What it needs, and how each account is doing.",
        panel: "telegram-setup",
      },
      {
        id: "texting",
        name: "Texting",
        blurb: "What it does as it answers.",
        keys: [
          "telegram.read_receipts",
          "telegram.typing_indicator",
          "telegram.reactions",
          "telegram.voice_notes",
          "telegram.fix_typos",
          "telegram.keep_media",
        ],
      },
      {
        id: "who",
        name: "Who it answers",
        blurb: "Groups, channels, and whether it ever writes first.",
        keys: [
          "telegram.groups",
          "telegram.channels",
          "telegram.answer_first",
          "telegram.call_text",
        ],
      },
      {
        id: "pace",
        name: "Pace",
        blurb: "How fast it may send. A new account is limited quickly, so start low.",
        keys: [
          "telegram.min_send_gap_ms",
          "telegram.max_send_gap_ms",
          "telegram.max_sends_per_hour",
          "telegram.burst_ms",
          "telegram.quiet_hours",
        ],
      },
      {
        id: "itself",
        name: "Itself",
        blurb: "How it looks on Telegram, and what it does with gifts.",
        keys: [
          "telegram.night_offline",
          "telegram.stories",
          "telegram.gifts",
          "telegram.dry_run",
        ],
      },
      { id: "rest", name: "Everything else", rest: true },
    ],
  },
];

/**
 * The order the nav shows them in, in runs.
 *
 * The definitions above stay in the order they were written, which is the
 * order the tabs were added over the months; this is the order they read in.
 * The app itself first, then the brain it answers with, then the places it
 * talks: the ones you message someone on, the ones that are a feed, and the
 * game. A tab left out of this list lands at the end rather than vanishing.
 */
const ORDER: { group: Group; ids: string[] }[] = [
  { group: "app", ids: ["app", "look"] },
  { group: "brain", ids: ["groq", "ai", "calls"] },
  { group: "chats", ids: ["discord", "telegram", "whatsapp", "imessage", "snapchat"] },
  { group: "feeds", ids: ["instagram", "tiktok", "x", "reddit"] },
  { group: "games", ids: ["minecraft"] },
];

export const TABS: Tab[] = (() => {
  const left = new Map(DEFINED.map((t) => [t.id, t]));
  const out: Tab[] = [];
  for (const { group, ids } of ORDER) {
    for (const id of ids) {
      const tab = left.get(id);
      if (!tab) continue;
      left.delete(id);
      out.push({ ...tab, group });
    }
  }
  // Anything new, not named above yet: at the end, in the run the last one was in.
  return [...out, ...[...left.values()].map((t) => ({ ...t, group: out[out.length - 1]?.group }))];
})();

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
  "tiktok setup": "tiktok/setup",
  "instagram setup": "instagram/setup",
  "minecraft setup": "minecraft/setup",
  "imessage setup": "imessage/setup",
  "discord setup": "discord/setup",
  "telegram setup": "telegram/setup",
  bluebubbles: "imessage/setup",
  "private api": "imessage/setup",
  telegram: "telegram/texting",
  "telegram accounts": "telegram/texting",
  "telegram bot": "app/telegram",
  "control bot": "app/telegram",
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

  // A tab, before a key: "discord" is also the prefix its keys are owned by, which sent a press on its name at the top of
  // the page to its leftovers, usually empty.
  const tab = TABS.find((t) => t.id === q || t.name.toLowerCase() === q);
  if (tab) return `${tab.id}/${tab.subs[0].id}`;

  // A config key, so an issue can point at the exact setting.
  if (KEY_HOME[want]) return KEY_HOME[want];
  if (restHomeOf(want)) return restHomeOf(want);

  const byName = PATHS.find((p) => p.sub.name.toLowerCase() === q);
  if (byName) return byName.path;

  // Last resort: a leading word match, so "Snapchat browser" still lands.
  const starts = PATHS.find(
    (p) => `${p.tab.name} ${p.sub.name}`.toLowerCase().startsWith(q) || q.startsWith(p.tab.id),
  );
  return starts?.path;
}
