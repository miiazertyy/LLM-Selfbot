"""
app/web/descriptions.py - plain descriptions, and full config coverage.

Two problems this solves:

  * the Settings page listed the dotted config key under every row, which means
    nothing unless you have read config.yaml
  * only 46 of the 75 settings in config.yaml had a control at all, so timings
    and chances could not be changed from the app

Descriptions are one straightforward line each, no dashes for punctuation.
Coverage comes from walking the real config, so a setting added to config.yaml
later shows up on its own instead of quietly having no control.
"""

DESCRIPTIONS = {
    "bot.owner_id": "Your Discord user ID. Owner only commands check against this.",
    "bot.prefix": "Character that starts a command, like ! or .",
    "bot.trigger": "Words that make the bot reply even when it was not mentioned.",
    "bot.default_language": "Language to fall back to when it cannot detect one.",
    "bot.allow_dm": "Reply to direct messages.",
    "bot.allow_gc": "Reply in group chats.",
    "bot.allow_server": "Reply when mentioned in a server.",
    "bot.realistic_typing": "Show the typing indicator, timed to the length of the reply.",
    "bot.batch_messages": "Wait for someone to finish a burst of messages, then reply once.",
    "bot.hold_conversation": "Keep replying for a while after the first message, with no trigger needed.",
    "bot.reply_ping": "Send as a Discord reply, which pings the person.",
    "bot.disable_mentions": "Strip mentions out of what the bot sends.",
    "bot.anti_age_ban": "Avoid wording that Discord flags for age related bans.",
    "bot.read_bios": "Read a profile bio for extra context about someone.",
    "bot.ignore_chance": "Chance of skipping a message entirely, so replies are not guaranteed.",
    "bot.typo_chance": "Chance of a small typo in a reply.",
    "bot.groq_models": "Models to try in order. If one fails it moves to the next.",
    "bot.groq_small_model": "Fast model for memory and language utility calls.",
    "bot.groq_tts_model": "Which voice model speaks.",
    "bot.tts.voice": "Whose voice it speaks in.",
    "bot.tts.tones": "How it is delivered.",
    "bot.max_reply_tokens": "Longest a single reply may be.",
    "bot.desktop.build_source": "Where the build number comes from.",
    "bot.server_batch_wait_times": "The same, for server channels.",
    "bot.groq_image_model": "Model used to look at images.",
    "bot.groq_whisper_model": "Model used to transcribe voice messages.",
    "bot.priority_prefix": "Prefix that makes a message jump the queue.",
    "bot.trigger_bypasses_ignore": "A trigger word still gets a reply even if the ignore roll said no.",
    "bot.mention_bypasses_ignore": "Being mentioned still gets a reply even if the ignore roll said no.",
    "bot.global_cooldown_enabled": "Enforce a pause between replies across every chat.",
    "bot.global_cooldown_min": "Shortest pause between any two replies, in seconds.",
    "bot.global_cooldown_max": "Longest pause between any two replies, in seconds.",
    "bot.batch_tail_wait_min": "Shortest wait after the last message before replying, in seconds.",
    "bot.batch_tail_wait_max": "Longest wait after the last message before replying, in seconds.",
    "bot.batch_wait_times": "Weighted list of wait times to pick from when batching.",
    "bot.read_delay_dm_min": "Shortest pause before reading a DM, in seconds.",
    "bot.read_delay_dm_max": "Longest pause before reading a DM, in seconds.",
    "bot.read_delay_group_min": "Shortest pause before reading a group message, in seconds.",
    "bot.read_delay_group_max": "Longest pause before reading a group message, in seconds.",
    "bot.read_delay_server_min": "Shortest pause before reading a server message, in seconds.",
    "bot.read_delay_server_max": "Longest pause before reading a server message, in seconds.",
    "bot.mood.enabled": "Let the bot drift between moods over time.",
    "bot.mood.change_interval_min": "Shortest time before the mood changes, in seconds.",
    "bot.mood.change_interval_max": "Longest time before the mood changes, in seconds.",
    "bot.mood.default": "Mood to start in.",
    "bot.mood.moods.chill": "How the bot behaves in the chill mood.",
    "bot.mood.moods.playful": "How the bot behaves in the playful mood.",
    "bot.mood.moods.busy": "How the bot behaves in the busy mood.",
    "bot.mood.moods.tired": "How the bot behaves in the tired mood.",
    "bot.mood.moods.annoyed": "How the bot behaves in the annoyed mood.",
    "bot.mood.moods.flirty": "How the bot behaves in the flirty mood.",
    "bot.status.enabled": "Rotate the account's Discord status.",
    "bot.status.change_interval_min": "Shortest time before the status changes, in seconds.",
    "bot.status.change_interval_max": "Longest time before the status changes, in seconds.",
    "bot.status.statuses": "Statuses to rotate through, such as online, idle and dnd.",
    "bot.tts.enabled": "Send voice messages instead of text sometimes.",
    "bot.tts.voice": "Which voice to speak with.",
    "bot.tts.tones": "Tone tags the voice is allowed to use.",
    "bot.pictures.enabled": "Let the bot send pictures from its gallery.",
    "bot.late_reply.enabled": "Open with an apology when replying long after a message.",
    "bot.late_reply.threshold": "How late a reply has to be to count as late, in seconds.",
    "bot.late_reply.openers_en": "English openers to use for a late reply.",
    "bot.late_reply.openers_fr": "French openers to use for a late reply.",
    "bot.late_reply.french_indicators": "Words that mark a conversation as French.",
    "bot.stale_reply.enabled": "Skip messages that have gone stale.",
    "bot.stale_reply.max_messages": "How many newer messages make an old one stale.",
    "bot.stale_reply.min_age": "How old a message must be to count as stale, in seconds.",
    "bot.nudge.enabled": "Message people who have gone quiet.",
    "bot.nudge.threshold_days": "Days of silence before a nudge.",
    "bot.nudge.check_interval_hours": "How often to look for people to nudge, in hours.",
    "bot.nudge.send_during_hours": "Hours of the day nudges may be sent, as start and end.",
    "bot.friend_requests.auto_accept": "Accept incoming friend requests automatically.",
    "bot.friend_requests.accept_delay_min": "Shortest wait before accepting, in seconds.",
    "bot.friend_requests.accept_delay_max": "Longest wait before accepting, in seconds.",
    "bot.profile_cache.enabled": "Store names, avatars and bios locally so clicking a name shows a profile card.",
    "bot.mood.shift_interval_min": "Shortest time before the mood shifts, in seconds.",
    "bot.mood.shift_interval_max": "Longest time before the mood shifts, in seconds.",
    "bot.friend_requests.enabled": "Handle incoming friend requests at all.",
    "snapchat.max_recipients": "Most people a single Snapchat send may go to.",
    "snapchat.min_send_gap_ms": "Shortest gap between two Snapchat sends, in milliseconds.",
    "snapchat.max_send_gap_ms": "Longest gap between two Snapchat sends, in milliseconds.",
    "snapchat.max_sends_per_hour": "Cap on Snapchat sends per hour. Over this it waits.",
    "snapchat.auto_add_friends": "Accept pending Snapchat friend requests automatically.",
    "discord.enabled": "Run the Discord accounts.",
    "snapchat.enabled": "Run the Snapchat accounts.",
    "snapchat.headless": "Run the Snapchat browser with no visible window.",
    "snapchat.poll_interval_ms": "How often to check Snapchat for new messages, in milliseconds.",
    "snapchat.response_timeout_ms": "How long to wait for a reply to send before giving up.",
    "snapchat.quiet_hours": "Hours to stay silent on Snapchat, written as start-end.",
    "notifications.error_webhook": "Discord webhook to post errors to.",
    "notifications.ratelimit_notifications": "Also post a notice when Discord rate limits the account.",
    "notifications.telegram_error_notifications": "Send errors to the Telegram controller.",
    "bot.groq_tts_model": "Voice used for voice messages.",
    "bot.groq_whisper_model": "Model that transcribes voice messages people send.",
    "bot.groq_image_model": "Model that describes pictures. It has to be one that can read images.",
    "bot.groq_small_model": "Cheaper model for background work like remembering facts, so the main one stays free for replies.",
    "bot.groq_tts_model": "The model that turns a reply into speech. Orpheus English and Arabic are the two Groq offers; the voices below belong to whichever is selected.",
    "bot.tts.voice": "Which of the model's voices speaks. Each model has its own set, so switching model changes what is available here.",
    "bot.tts.tones": "Delivery tags sent ahead of every line, like [casual] or [warm]. Stack two or three; more than that and they start fighting each other.",
    "bot.desktop.build_source": "Automatic reads Discord's current build number off its own web app when the account starts, so it does not drift out of date on its own. Discord publishes this nowhere official, so the number is read out of the web app's scripts - if that ever stops working the number below is used instead, which is only cosmetic anyway.",
    "bot.server_batch_wait_times": "How long it waits before answering in a server, kept separate from DMs. A ten minute pause reads as being away from your phone in a DM; in a channel the conversation has moved on and the reply lands on nothing. Clear it to make servers behave exactly like DMs.",
    "bot.max_reply_tokens": "Caps how long one reply may be. Groq counts the expected output against your per-minute allowance before generating anything, so with no cap it assumes the model's maximum and can refuse even a short reply.",
    "bot.per_account_persona": "Give each account its own persona file instead of sharing one. Account 2 reads instructions_2.txt, and so on.",
    "bot.client_profile": "Which client the account presents as. web is safer, desktop spoofs the app.",
    "bot.timezone": "Persona timezone, sent in requests and used for the night schedule.",
    "bot.locale": "Persona locale, sent in requests.",
    "snapchat.verify_wait_ms": "How long to wait for email/code verification. 0 waits indefinitely.",
    "snapchat.reload_interval_ms": "Reload the Snapchat page this often, so the chat list cannot go stale. 0 is off.",
    "bot.local.vision_model": "Local model that reads pictures. Empty sends them to Groq.",
    "bot.local.stt_model": "Local model that transcribes voice messages. Empty sends them to Groq.",
    "bot.local.tts_model": "Local model that speaks. Empty sends voice notes to Groq.",
    "bot.local.tts_voice": "Voice name for the local speech model, e.g. af_sky.",
    "bot.desktop.build_number": "Build number used for the desktop client spoof.",
    "bot.night_invisible.enabled": "Go invisible during the night window, while still replying.",
    "bot.night_invisible.hours": "Night hours in the persona timezone, written as start-end like 2-8.",
    "bot.night_invisible.status": "Which presence to show during the night window. Invisible is not offline: it still replies.",
    "bot.night_invisible.timezone": "Timezone the night hours are measured in.",
    "bot.message_style.mode": "How long replies are. short, balanced or chatty.",
    "bot.message_style.max_chunk_chars": "Longest one message may be before it is split.",
    "bot.reactions.enabled": "React with an emoji when the conversation calls for it.",
    "bot.reactions.chance": "How often a reaction the AI asked for is actually used. The AI reaches for one on almost every reply, so this is what keeps it occasional.",
    "bot.reactions.emojis": "The emoji this character reacts with. Anything outside this list is ignored.",
    "bot.reactions.react_only_max_ratio": "Cap on how often a reply is only a reaction, no text.",
    "bot.edit_after_send_chance": "Chance of fixing a small slip right after sending.",
    "services.discord.enabled": "Start Discord when the app launches. Both this and the platform switch below have to be on.",
    "services.snapchat.enabled": "Start Snapchat when the app launches. Both this and the platform switch below have to be on.",
    "discord.enabled": "The Discord platform itself. Off here means no account starts, whatever the switch above says.",
    "snapchat.enabled": "The Snapchat platform itself. Off here means no account starts, whatever the switch above says.",
    "services.telegram.enabled": "Start the Telegram controller when the app launches.",
    "services.webui.enabled": "Serve the webui.",
    "services.webui.port": "Port the webui listens on.",
    "services.webui.bind": "Address to listen on. Keep 127.0.0.1 unless you know why not.",
}

# The settings most people actually touch. Settings opens on just these, with
# everything else one click away, because 78 rows at once is unreadable when
# you do not already know the app.
COMMON = {
    "bot.allow_dm", "bot.allow_gc", "bot.allow_server",
    "bot.ignore_chance", "bot.typo_chance",
    "bot.realistic_typing", "bot.batch_messages", "bot.hold_conversation",
    "bot.reply_ping", "bot.read_bios", "bot.batch_wait_times",
    "bot.global_cooldown_enabled",
    "bot.mood.enabled", "bot.status.enabled", "bot.tts.enabled",
    "bot.pictures.enabled", "bot.nudge.enabled", "bot.late_reply.enabled",
    "bot.friend_requests.auto_accept", "bot.profile_cache.enabled",
    "bot.client_profile", "bot.message_style.mode", "bot.reactions.enabled",
    "bot.night_invisible.enabled",
    "discord.enabled", "snapchat.enabled",
    "services.discord.enabled", "services.snapchat.enabled",
    "services.telegram.enabled", "services.webui.enabled",
}


# Where an auto discovered key lands, longest prefix wins.
_SECTIONS = {
    "bot.mood": "Mood",
    "bot.status": "Status",
    "bot.night_invisible": "Status",
    "bot.late_reply": "Conversation",
    "bot.stale_reply": "Conversation",
    "bot.nudge": "Conversation",
    "bot.friend_requests": "Behaviour",
    "bot.tts": "Behaviour",
    "bot.pictures": "Behaviour",
    "bot.message_style": "Humanization",
    "bot.reactions": "Humanization",
    "bot.desktop": "General",
    "snapchat": "Snapchat",
    "services": "Services",
    "notifications": "Notifications",
    "discord": "Services",
}

# Settings the running account picks up without being restarted. The runner
# re-reads config.yaml on any config_update, so this is nearly everything under
# bot.*; the exceptions are values baked into the connection itself.
_NEEDS_RESTART = {
    "bot.per_account_persona",
    "bot.owner_id",          # the gateway session is created with it
    "bot.client_profile",    # fingerprint is fixed at login
    "bot.timezone",          # baked into the gateway headers at login
    "bot.locale",
    "bot.desktop.build_number",
    "services.webui.port",   # the server is already bound
    "services.webui.bind",
    "services.discord.enabled",
    "services.snapchat.enabled",
    "services.telegram.enabled",
    "discord.enabled",
    "snapchat.enabled",
    "snapchat.headless",     # the browser is already launched
}


def section_for(key: str) -> str:
    for prefix, section in sorted(_SECTIONS.items(), key=lambda kv: -len(kv[0])):
        if key == prefix or key.startswith(prefix + "."):
            return section
    return "General"


def needs_restart(key: str) -> bool:
    return key in _NEEDS_RESTART


def infer_type(value) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (list, dict)):
        return "json"
    return "str"


def walk(node, prefix=""):
    """Every leaf in the config, as dotted keys."""
    for key, value in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from walk(value, path)
        else:
            yield path, value


# Explicit names for settings whose own last segment says nothing. Every
# service toggle ends in ".enabled", so all four rendered as "Enabled" in a
# list, one under the other, with no way to tell which was which.
LABELS = {
    "services.discord.enabled": "Start Discord with the app",
    "services.snapchat.enabled": "Start Snapchat with the app",
    "discord.enabled": "Discord platform",
    "snapchat.enabled": "Snapchat platform",
    "services.telegram.enabled": "Telegram controller",
    "services.webui.enabled": "webui",
    "services.webui.port": "webui port",
    "services.webui.bind": "Listen address",
    "bot.night_invisible.enabled": "Go invisible at night",
    "bot.night_invisible.hours": "Night hours",
    "bot.night_invisible.status": "Night status",
    "bot.night_invisible.timezone": "Night timezone",
    "bot.reactions.enabled": "React with emoji",
    "bot.reactions.chance": "How often it reacts",
    "bot.reactions.react_only_max_ratio": "How often a reaction replaces a reply",
    "bot.message_style.mode": "Reply length",
    "bot.message_style.max_chunk_chars": "Longest single message",
    "bot.profile_cache.enabled": "Profile cards",
    "bot.desktop.build_number": "Desktop build number",
    "bot.mood.enabled": "Moods",
    "bot.late_reply.enabled": "Late reply openers",
    "bot.stale_reply.enabled": "Stale reply handling",
    "bot.status.enabled": "Status cycling",
}

# A leaf that carries no meaning on its own: the name has to come from what it
# belongs to, not from the last word.
_GENERIC_LEAVES = {"enabled", "port", "bind", "mode", "url", "token", "hours",
                   "timezone", "key", "name", "value", "id", "path"}


# Settings that have a better home elsewhere in the app. Leaving them here as
# well would mean two places to change one thing, and the other place is always
# the better editor.
HIDDEN = {
    "bot.mood.enabled",
    "bot.mood.moods",
    "bot.mood.shift_interval_min",
    "bot.mood.shift_interval_max",
    # Edited on the Persona page, where reacting instead of replying reads as
    # the character trait it is rather than as a number in a list.
    "bot.reactions.enabled",
    "bot.reactions.chance",
    "bot.reactions.react_only_max_ratio",
    "bot.reactions.emojis",
    # Edited under AI provider, Local AI, which finds the server for you and
    # lists the models it has. A free text box for a base URL and a model name
    # is how you get a 404 on every reply and no idea why.
    "bot.local",
}


def is_hidden(key: str) -> bool:
    """True for a key, or anything nested under one.

    walk() descends into mappings, so bot.mood.moods yields one field per mood
    (bot.mood.moods.chill, .playful, ...). Matching the exact key alone left
    all six of them listed individually.
    """
    if key in HIDDEN:
        return True
    return any(key.startswith(h + ".") for h in HIDDEN)


def label_for(key: str) -> str:
    if key in LABELS:
        return LABELS[key]
    parts = key.split(".")
    leaf = parts[-1]
    # "services.discord.enabled" reads as "Discord enabled", which at least
    # says which one, rather than four identical rows called "Enabled".
    if leaf in _GENERIC_LEAVES and len(parts) >= 3:
        parent = parts[-2].replace("_", " ")
        return f"{parent} {leaf.replace('_', ' ')}".strip().capitalize()
    return leaf.replace("_", " ").capitalize()
