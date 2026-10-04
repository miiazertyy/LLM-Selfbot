"""The Telegram controller's commands, in one place.

The controller registers them as the "/" menu Telegram shows, and the panel
lists them on its Telegram page so they can be found without opening
Telegram and scrolling a menu. Plain data, so the panel can read it without
importing python-telegram-bot.
"""

# (group, [(command, what it does)]), in the order they are shown.
GROUPS = [
    ("Getting around", [
        ("start", "Show the commands (/start snapchat for Snapchat's)"),
        ("help", "Show the command list"),
        ("account", "Show or switch the account commands go to"),
        ("status", "How the account is doing"),
        ("ping", "Check the controller is running"),
    ]),
    ("Replies", [
        ("pause", "Pause or resume replies"),
        ("reply", "Reply now: check, all, or a user's ID"),
        ("wipe", "Clear the conversation history"),
        ("mood", "See or set the mood"),
        ("toggledm", "Discord: replies in DMs on or off"),
        ("togglegc", "Discord: replies in group chats on or off"),
        ("toggleserver", "Discord: replies in servers on or off"),
        ("toggleactive", "Discord: replies in one channel on or off"),
    ]),
    ("People", [
        ("pauseuser", "Stop replying to someone"),
        ("unpauseuser", "Start replying to someone again"),
        ("ignore", "Ignore someone, or stop ignoring them"),
        ("persona", "Set or clear someone's own persona"),
        ("analyse", "A read of someone from their messages"),
        ("leaderboard", "Who talks to it most"),
        ("addfriend", "Discord: send a friend request"),
    ]),
    ("Persona and settings", [
        ("prompt", "See or set the instructions"),
        ("instructions", "Upload a new instructions.txt"),
        ("getinstructions", "Download instructions.txt"),
        ("config", "See or change a setting"),
        ("getconfig", "Download config.yaml"),
        ("setconfig", "Upload a new config.yaml"),
        ("reload", "Reload the instructions and settings"),
        ("getdb", "Download the memory database"),
    ]),
    ("Pictures", [
        ("imagels", "Browse the pictures"),
        ("imageupload", "Add pictures"),
        ("imagedownload", "Download a picture by number"),
        ("imagedesc", "Set a picture's description"),
        ("imagedelete", "Delete a picture by number"),
        ("imagedeleteall", "Delete every picture"),
    ]),
    ("Discord profile", [
        ("setstatus", "Set the custom status"),
        ("bio", "Set the bio"),
        ("pfp", "Change the profile picture"),
        ("banner", "Change the banner"),
    ]),
    ("Voice", [
        ("join", "Discord: join a voice channel"),
        ("leave", "Discord: leave voice"),
        ("autojoin", "Discord: join voice on start"),
    ]),
    ("The app", [
        ("restart", "Restart the bot"),
        ("shutdown", "Shut the bot down"),
        ("update", "Update to the latest version"),
    ]),
]


def menu() -> list[tuple[str, str]]:
    """Every command in order, for Telegram's "/" menu."""
    return [pair for _, pairs in GROUPS for pair in pairs]


def as_json() -> list[dict]:
    """The groups as the panel reads them."""
    return [{"group": name, "commands": [{"name": c, "does": d} for c, d in pairs]}
            for name, pairs in GROUPS]
