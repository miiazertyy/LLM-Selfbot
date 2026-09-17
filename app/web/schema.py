"""Config.yaml field schema for the Settings UI.

Fields marked requires_restart are read once at runner import; everything else
applies on the next load_config() (mtime-cached) or via the config_update IPC.
"""

CONFIG_SCHEMA = [
    {"key": "bot.owner_id", "type": "int", "label": "Owner user ID",
     "section": "General", "requires_restart": True},
    {"key": "bot.prefix", "type": "str", "label": "Command prefix",
     "section": "General", "requires_restart": True},
    {"key": "bot.trigger", "type": "str", "label": "Trigger words (comma-separated)",
     "section": "General", "requires_restart": True},
    {"key": "bot.default_language", "type": "str", "label": "Fallback language",
     "section": "General", "requires_restart": True},
    {"key": "bot.allow_dm", "type": "bool", "label": "Respond in DMs", "section": "Behaviour"},
    {"key": "bot.allow_gc", "type": "bool", "label": "Respond in group chats", "section": "Behaviour"},
    {"key": "bot.allow_server", "type": "bool", "label": "Respond to mentions in servers", "section": "Behaviour"},
    {"key": "bot.realistic_typing", "type": "bool", "label": "Realistic typing", "section": "Behaviour"},
    {"key": "bot.batch_messages", "type": "bool", "label": "Batch messages before replying", "section": "Behaviour"},
    {"key": "bot.hold_conversation", "type": "bool", "label": "Hold conversations", "section": "Behaviour"},
    {"key": "bot.reply_ping", "type": "bool", "label": "Ping on replies", "section": "Behaviour"},
    {"key": "bot.disable_mentions", "type": "bool", "label": "Disable mentions",
     "section": "Behaviour"},
    {"key": "bot.anti_age_ban", "type": "bool", "label": "Anti age-ban obfuscation", "section": "Behaviour"},
    {"key": "bot.read_bios", "type": "bool", "label": "Read user bios for context", "section": "Behaviour"},
    {"key": "bot.ignore_chance", "type": "float", "label": "Chance to ignore a message",
     "section": "Humanization", "min": 0.0, "max": 1.0, "step": 0.01, "requires_restart": True},
    {"key": "bot.groq_small_model", "type": "str", "label": "Utility model (memory, language)",
     "section": "General"},
    {"key": "bot.typo_chance", "type": "float", "label": "Chance of a typo",
     "section": "Humanization", "min": 0.0, "max": 1.0, "step": 0.01},
    {"key": "bot.edit_after_send_chance", "type": "float", "label": "Chance of a typo fix after sending",
     "section": "Humanization", "min": 0.0, "max": 1.0, "step": 0.005},
    {"key": "bot.message_style.mode", "type": "str", "label": "Message style (short / balanced / chatty)",
     "section": "Humanization"},
    {"key": "bot.reactions.enabled", "type": "bool", "label": "Context-aware emoji reactions",
     "section": "Humanization"},
    {"key": "bot.reactions.react_only_max_ratio", "type": "float", "label": "Max ratio of reaction-only replies",
     "section": "Humanization", "min": 0.0, "max": 1.0, "step": 0.05},
    {"key": "bot.client_profile", "type": "str", "label": "Client profile (web / desktop)",
     "section": "General", "requires_restart": True},
    {"key": "bot.timezone", "type": "str", "label": "Persona timezone",
     "section": "General", "requires_restart": True},
    {"key": "bot.locale", "type": "str", "label": "Persona locale",
     "section": "General", "requires_restart": True},
    {"key": "bot.desktop.build_number", "type": "int", "label": "Desktop client build number",
     "section": "General", "requires_restart": True},
    {"key": "bot.night_invisible.enabled", "type": "bool", "label": "Invisible during night hours",
     "section": "Status"},
    {"key": "bot.night_invisible.hours", "type": "str", "label": "Night hours (24h, local, e.g. 2-8)",
     "section": "Status"},
    {"key": "bot.night_invisible.status", "type": "str", "label": "Status during night hours",
     "section": "Status"},
    {"key": "bot.priority_prefix", "type": "str", "label": "Priority prefix",
     "section": "General", "requires_restart": True},
    {"key": "bot.trigger_bypasses_ignore", "type": "bool", "label": "Triggers bypass ignore chance",
     "section": "Humanization", "requires_restart": True},
    {"key": "bot.mention_bypasses_ignore", "type": "bool", "label": "Mentions bypass ignore chance",
     "section": "Humanization", "requires_restart": True},
    {"key": "bot.global_cooldown_enabled", "type": "bool", "label": "Global reply cooldown",
     "section": "Humanization", "requires_restart": True},
    {"key": "bot.global_cooldown_min", "type": "int", "label": "Global cooldown min (s)",
     "section": "Humanization", "min": 5, "max": 600, "requires_restart": True},
    {"key": "bot.global_cooldown_max", "type": "int", "label": "Global cooldown max (s)",
     "section": "Humanization", "min": 5, "max": 3600, "requires_restart": True},
    {"key": "bot.mood.enabled", "type": "bool", "label": "Mood system", "section": "Mood",
     "requires_restart": True},
    {"key": "bot.mood.shift_interval_min", "type": "int", "label": "Mood shift min (s)",
     "section": "Mood", "min": 300, "requires_restart": True},
    {"key": "bot.mood.shift_interval_max", "type": "int", "label": "Mood shift max (s)",
     "section": "Mood", "min": 300, "requires_restart": True},
    {"key": "bot.status.enabled", "type": "bool", "label": "Status cycling",
     "section": "Status", "requires_restart": True},
    {"key": "bot.pictures.enabled", "type": "bool", "label": "Send pictures when asked",
     "section": "Behaviour"},
    {"key": "bot.tts.enabled", "type": "bool", "label": "Voice messages (TTS)", "section": "Behaviour"},
    {"key": "bot.late_reply.enabled", "type": "bool", "label": "Late reply openers",
     "section": "Conversation", "requires_restart": True},
    {"key": "bot.late_reply.threshold", "type": "int", "label": "Late reply threshold (s)",
     "section": "Conversation", "min": 30, "requires_restart": True},
    {"key": "bot.stale_reply.enabled", "type": "bool", "label": "Abandon stale replies",
     "section": "Conversation", "requires_restart": True},
    {"key": "bot.friend_requests.enabled", "type": "bool", "label": "Auto-accept friend requests",
     "section": "General", "requires_restart": True},
    {"key": "bot.friend_requests.accept_delay_min", "type": "int", "label": "Accept delay min (s)",
     "section": "General", "min": 30, "requires_restart": True},
    {"key": "bot.friend_requests.accept_delay_max", "type": "int", "label": "Accept delay max (s)",
     "section": "General", "min": 30, "requires_restart": True},
    {"key": "bot.nudge.enabled", "type": "bool", "label": "Nudge unanswered DMs",
     "section": "Conversation", "requires_restart": True},
    {"key": "bot.nudge.threshold_days", "type": "int", "label": "Nudge after (days)",
     "section": "Conversation", "min": 1, "requires_restart": True},
    {"key": "notifications.telegram_error_notifications", "type": "bool",
     "label": "Telegram error notifications", "section": "Notifications"},
    {"key": "snapchat.enabled", "type": "bool", "label": "Snapchat platform",
     "section": "Services"},
    {"key": "discord.enabled", "type": "bool", "label": "Discord platform", "section": "Services"},
    {"key": "snapchat.poll_interval_ms", "type": "int", "label": "Snapchat poll interval (ms)",
     "section": "Snapchat", "min": 2000, "requires_restart": True},
    {"key": "snapchat.max_recipients", "type": "int", "label": "Snapchat max chats per poll",
     "section": "Snapchat", "min": 1, "max": 50, "requires_restart": True},
    {"key": "snapchat.min_send_gap_ms", "type": "int", "label": "Snapchat min send gap (ms)",
     "section": "Snapchat", "min": 1000, "requires_restart": True},
    {"key": "snapchat.max_send_gap_ms", "type": "int", "label": "Snapchat max send gap (ms)",
     "section": "Snapchat", "min": 1000, "requires_restart": True},
    {"key": "snapchat.max_sends_per_hour", "type": "int", "label": "Snapchat sends per hour",
     "section": "Snapchat", "min": 1, "max": 200, "requires_restart": True},
    {"key": "snapchat.auto_add_friends", "type": "bool", "label": "Snapchat auto-add friends",
     "section": "Snapchat", "requires_restart": True},
    {"key": "snapchat.headless", "type": "bool", "label": "Snapchat headless browser",
     "section": "Snapchat", "requires_restart": True},
]


def get_schema() -> list:
    return CONFIG_SCHEMA


def get_nested(cfg: dict, dotted: str):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_nested(cfg: dict, dotted: str, value) -> dict:
    parts = dotted.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise ValueError(f"{dotted}: {part} is not a mapping")
    node[parts[-1]] = value
    return cfg
