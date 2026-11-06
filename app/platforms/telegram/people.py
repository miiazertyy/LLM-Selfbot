"""app/platforms/telegram/people.py - who a Telegram chat is, in the app's own terms.

Ids carry a prefix because a bare number means Discord everywhere in this app (app/utils/snappeople.py
platform_of_user, webui/src/lib/platforms.ts): a person is `tg_<their id>`, a group, supergroup or channel is
`tgg_<its id>`. Nothing here imports Telethon, so it can be read and tested on its own.
"""
from __future__ import annotations

import re

PERSON = re.compile(r"^tg_(\d{1,20})$")
GROUP = re.compile(r"^tgg_(\d{1,20})$")


def person_id(user_id) -> str:
    """A person's id: "tg_" and their own Telegram id."""
    try:
        return f"tg_{abs(int(user_id))}"
    except (TypeError, ValueError):
        return ""


def group_id(chat_id) -> str:
    """A group's, a supergroup's or a channel's. Telegram writes a channel's id as -100…; the id itself is kept."""
    try:
        n = abs(int(chat_id))
    except (TypeError, ValueError):
        return ""
    # -1001234567890 is channel 1234567890: the marker belongs to the wire, not to who the chat is.
    s = str(n)
    if s.startswith("100") and len(s) > 10:
        s = s[3:]
    return f"tgg_{int(s)}"


def telegram_id(uid: str) -> int:
    """The Telegram id behind one of ours, 0 for anything else."""
    m = PERSON.match(str(uid or "")) or GROUP.match(str(uid or ""))
    return int(m.group(1)) if m else 0


def is_group(uid: str) -> bool:
    return bool(GROUP.match(str(uid or "")))


def pretty(name: str, username: str = "", phone: str = "", uid=None) -> str:
    """What to call someone: their name, else their @username, else their number, else their id. The order Telegram
    itself shows them in."""
    name = " ".join(str(name or "").split())
    if name:
        return name[:80]
    if username:
        return f"@{str(username).lstrip('@')[:70]}"
    if phone:
        digits = re.sub(r"\D", "", str(phone))
        return f"+{digits}" if digits else ""
    return f"tg_{uid}" if uid else ""


def name_of(entity) -> str:
    """A Telethon user, chat or channel as a name, without importing Telethon: read off whatever it carries."""
    first = getattr(entity, "first_name", "") or ""
    last = getattr(entity, "last_name", "") or ""
    title = getattr(entity, "title", "") or ""
    return pretty(title or f"{first} {last}".strip(), getattr(entity, "username", "") or "",
                  getattr(entity, "phone", "") or "", getattr(entity, "id", None))


def chat_id_of(entity, *, group: bool) -> str:
    """The app's id for whatever a message arrived in."""
    return group_id(getattr(entity, "id", 0)) if group else person_id(getattr(entity, "id", 0))


def uid_of_peer(peer) -> str:
    """The app's id for one of Telegram's bare peers (PeerUser, PeerChat, PeerChannel), which carry their id under
    a different name each."""
    for field, group in (("user_id", False), ("chat_id", True), ("channel_id", True)):
        got = getattr(peer, field, None)
        if got:
            return group_id(got) if group else person_id(got)
    return ""


def mentioned(text: str, names) -> bool:
    """Whether a group message calls the account by name: one of its trigger names, or its @username, as a whole
    word. The same rule the other platforms' group chats use."""
    low = f" {str(text or '').lower()} "
    for name in names:
        n = str(name or "").strip().lower().lstrip("@")
        if not n:
            continue
        # An "@" right before it counts: "@alicia_m" is being called by name as much as "alicia" is.
        if re.search(rf"(?<![a-z0-9_]){re.escape(n)}(?![a-z0-9_])", low):
            return True
    return False


def trigger_names(trigger: str, username: str = "", first_name: str = "") -> list:
    """The names it answers to in a group: the persona's trigger words (a comma list, as bot.trigger is written),
    its @username and its first name."""
    out = [p.strip() for p in str(trigger or "").split(",") if p.strip()]
    for extra in (username, first_name):
        extra = str(extra or "").strip()
        if extra and extra.lower() not in {o.lower() for o in out}:
            out.append(extra)
    return out
