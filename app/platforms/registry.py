"""Every platform the app runs accounts on, in one place, and what the rest of the code needs to know about each.

The lists of platforms that used to be written out wherever one was needed (thirty files had one, and every new platform
was found missing from some of them only once it ran) are made from this. To add a platform, this is the first line;
docs/ADDING_A_PLATFORM.md has the rest, and tests/test_platform_registry.py names whatever still does not know it.

webui/src/lib/platforms.ts is this table for the panel. Nothing here is imported from the rest of the app, since the
logger and the command line need it before anything else is up.
"""
from __future__ import annotations

import re
from typing import NamedTuple


class Platform(NamedTuple):
    id: str
    name: str
    #: Its own colour, on a card with no picture.
    tone: str
    #: What its IPC targets start with: "snap", "snap2", and so on. Discord's are its own ("<n>") and it has none here.
    target: str
    #: The ending of its tables in the database (message_log_<table>), created from this.
    table: str
    #: What a person's id starts with where they are known by a username ("tt_someone"); "" where they are not.
    people: str
    #: Where its accounts' numbers start in the chat log (app/utils/chatlog.py): each gets a thousand. 0 for Discord's.
    log_base: int
    #: Driven through its website, in Chrome (app/platforms/snapchat/*bot.js).
    website: bool = False
    #: It has posts to read and make, as well as messages: an out tab, and the "going out" commands.
    feed: bool = False
    #: Can run on a phone: it is Python alone, with no Node or Chrome beside the app.
    on_phone: bool = False


PLATFORMS: tuple[Platform, ...] = (
    Platform("discord", "Discord", "#5865f2", "", "", "", 0, on_phone=True),
    Platform("snapchat", "Snapchat", "#fffc00", "snap", "snap", "", 1000, website=True),
    Platform("tiktok", "TikTok", "#fe2c55", "tiktok", "tiktok", "tt_", 2000, website=True, feed=True),
    Platform("instagram", "Instagram", "#e1306c", "insta", "instagram", "ig_", 3000, website=True, feed=True),
    # X's own colour is its near-white, the one its pages use on black: black itself would be a hole in the card.
    Platform("x", "X", "#e7e9ea", "x", "x", "x_", 7000, website=True, feed=True),
    Platform("reddit", "Reddit", "#ff4500", "reddit", "reddit", "rd_", 8000, website=True, feed=True),
    Platform("whatsapp", "WhatsApp", "#25d366", "wa", "whatsapp", "wa_", 9000),
    Platform("minecraft", "Minecraft", "#5b8731", "mc", "minecraft", "mc_", 4000),
    Platform("imessage", "iMessage", "#0a84ff", "imsg", "imessage", "", 5000),
    Platform("telegram", "Telegram", "#2aabee", "tg", "telegram", "", 6000, on_phone=True),
)

BY_ID = {p.id: p for p in PLATFORMS}
#: Every platform's id, in the order they are shown.
IDS = tuple(p.id for p in PLATFORMS)
#: The ones run by the shared bridge (app/platforms/snapchat_bridge.py): all but Discord, which has a runner of its own.
BRIDGED = tuple(p.id for p in PLATFORMS if p.target)
#: The same, past Snapchat, which has tables and records of its own from before there were others.
BRIDGED_BUT_SNAPCHAT = tuple(i for i in BRIDGED if i != "snapchat")
#: The ones driven through a website.
WEBSITES = tuple(p.id for p in PLATFORMS if p.website)
#: The ones with posts as well as messages.
FEEDS = tuple(p.id for p in PLATFORMS if p.feed)
#: {platform: what its IPC targets start with}.
TARGETS = {p.id: p.target for p in PLATFORMS if p.target}
#: {platform: the ending of its tables}.
TABLES = {p.id: p.table for p in PLATFORMS if p.table}
#: {platform: what a person's id starts with}, for the ones known by a username.
HANDLED = {p.id: p.people for p in PLATFORMS if p.people}
#: An account's id in the panel: "discord_1", "tiktok_12".
ACCOUNT_ID = re.compile(rf"^({'|'.join(IDS)})_([1-9][0-9]{{0,2}})$")


def name_of(platform: str) -> str:
    """How it is written ("TikTok", not "Tiktok"), whatever it is given."""
    p = BY_ID.get(platform)
    return p.name if p else str(platform).title()
