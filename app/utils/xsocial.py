"""What the persona knows of someone on X, for a message with them.

The pair to app/utils/xwatch.py: that one reads a post, this one says what it knows of a person - their handle,
their followers, what they have been posting - so a reply can sound like it is talking to somebody rather than to
a text box. Built like app/utils/instagramsocial.py, and read by the bridge through _social().

X does not share things the way Instagram shares reels, so the share pieces here answer "no" and stay out of the
way; they exist because the bridge asks every platform the same questions.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.utils import xwatch


def people_dir() -> Path:
    from app.utils.paths import DATA_DIR
    p = DATA_DIR / "cache" / "x_people"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(path: Path, default):
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
        return out if isinstance(out, type(default)) else default
    except (OSError, ValueError):
        return default


def _clip(text, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def contact_of(account: int, chat_id: str) -> dict:
    from app.utils import snappeople
    return snappeople.contacts(account, "x").get(str(chat_id)) or {}


def _told_path(account: int) -> Path:
    return people_dir() / f"told_{int(account)}.json"


def profile_block(contact: dict, handle: str, newest: dict | None = None, news: bool = False) -> str:
    """Their X, for the model: their handle and name, their followers, their words, and their newest post as it
    was read. `news`: they posted it since the persona last talked to them."""
    contact = contact if isinstance(contact, dict) else {}
    handle = str(handle or "").lstrip("@")
    if not handle:
        return ""
    name = str(contact.get("name") or "").strip()
    who = f"@{handle}" + (f" ({_clip(name, 40)})" if name and name.lower().lstrip("@") != handle else "")
    bits = [who]
    if contact.get("followers"):
        bits.append(f"{xwatch.count_str(contact['followers'])} followers")
    if contact.get("verified"):
        bits.append("verified")
    if contact.get("private"):
        bits.append("a private account")
    out = "THEIR X: " + ", ".join(bits) + "."
    bio = " ".join(str(contact.get("bio") or "").split())
    if bio:
        out += f' Their bio: "{_clip(bio, 200)}".'
    if newest and (newest.get("text") or newest.get("seen")):
        out += " " + xwatch.summary(newest, lead="their newest post", react=False).strip("[]")
        if news:
            out += (" They posted it since you last talked: you can bring it up if it fits, the way somebody who "
                    "saw it would, without making a thing of it.")
    return out + " Only use any of this if it fits; never recite it."


def dm_context(account: int, chat_id: str, username: str) -> str:
    """What the persona knows of this person's X, for a message with them. Their newest post is news once."""
    contact = contact_of(account, chat_id)
    if not contact and not username:
        return ""
    newest_url = str(contact.get("newest") or "")
    newest = xwatch.cached(newest_url) if newest_url else None
    told = _read(_told_path(account), {})
    news = bool(newest and told.get(chat_id) != newest_url and contact.get("posts_at"))
    if newest_url and told.get(chat_id) != newest_url:
        told[chat_id] = newest_url
        try:
            from app.utils.atomic import write_json_atomic
            write_json_atomic(_told_path(account), told)
        except Exception:
            pass
    return profile_block(contact, username, newest, news)


# ── Answering in public ──────────────────────────────────────────────────────

def mention_context(why: str = "") -> str:
    """How to answer an @ or a reply: it is public, and it is read by people who are not in the conversation."""
    return ("You are answering in public on X, under a post. Anyone can read it. Keep it to a line or two, in "
            "your own voice, and answer the person rather than the room. No hashtags, no thread of your own, "
            "nothing that reads like a brand."
            + (f" {why}" if why else ""))


def clean_reply(text: str, most: int = 270) -> str:
    """A public answer, tidied: one piece, no leading @ (X puts that there itself), short enough to go up."""
    s = " ".join(str(text or "").split())
    while s.startswith("@"):
        s = s.split(" ", 1)[1] if " " in s else ""
    s = s.strip().strip('"')
    return s[: most - 1].rstrip() + "…" if len(s) > most else s


def post_context(mood: str = "", saw: str = "") -> str:
    """How to write a post of its own: what it would actually say, not an announcement."""
    out = ("Write one post for your own X, in your own voice: something you would actually say, not an "
           "announcement. No hashtags, no emoji strings, nobody tagged. One or two sentences.")
    if mood:
        out += f" You are feeling {mood}."
    if saw:
        out += f" Something you read earlier, if you want to post about it: {_clip(saw, 400)}"
    return out


def clean_post(text: str, most: int = 270) -> str:
    """A post of its own, tidied: no quotes around the whole thing, no hashtag pile, short enough for X."""
    s = " ".join(str(text or "").split()).strip().strip('"')
    # A trailing run of hashtags is the one thing that gives a written-by-a-bot post away.
    while s.endswith("#") or (s.rsplit(" ", 1)[-1].startswith("#") and " " in s):
        s = s.rsplit(" ", 1)[0].rstrip()
    return s[: most - 1].rstrip() + "…" if len(s) > most else s


def settings(config: dict | None = None) -> dict:
    """The x.posting and x.engage blocks, with what the shipped config carries."""
    if config is None:
        from app.utils.helpers import load_config
        try:
            config = load_config()
        except Exception:
            config = {}
    x = (config or {}).get("x") or {}
    posting = x.get("posting") or {}
    where = posting.get("from") or {}
    return {
        "posting": bool(posting.get("enabled", False)),
        "per_day": int(posting.get("per_day", 2) or 2),
        "max_chars": int(posting.get("max_chars", 270) or 270),
        "from_web": bool(where.get("saw_online", True)),
        "from_mind": bool(where.get("on_its_mind", True)),
        "mentions": bool((x.get("mentions") or {}).get("enabled", False)),
    }


def post_source(pid: str) -> tuple[str, str]:
    """Where the next post comes from, and what it has to go on: ("web", what it read) or ("mind", "").

    Both switches on means it picks per post, leaning to the web when its free-time browsing left something fresh
    there (app/utils/web/journal.py): a post with something real behind it beats one made up out of nothing.
    """
    cfg = settings()
    if not cfg["posting"]:
        return "", ""
    saw = ""
    if cfg["from_web"]:
        try:
            import random

            from app.utils.web import journal
            # The last two days of its free-time browsing: older than that and it is not something it just read.
            since = time.time() - 2 * 86400
            fresh = [e for e in journal.entries(pid)
                     if isinstance(e, dict) and e.get("note") and float(e.get("ts") or 0) >= since]
            if fresh:
                saw = str(random.choice(fresh[:5]).get("note") or "")
        except Exception:
            saw = ""
    if saw and (not cfg["from_mind"] or time.time() % 3 < 2):
        return "web", saw
    if cfg["from_mind"]:
        return "mind", ""
    return ("web", saw) if saw else ("", "")


# ── What the bridge asks every platform ─────────────────────────────────────
# X has nothing to share the way Instagram shares a reel, so these answer no and keep out of the way.

def share_settings() -> bool:
    return False


def wants_reel(text: str) -> bool:       # noqa: ARG001 - the bridge asks every platform the same question
    return False


def pools_for(pid: str) -> list:         # noqa: ARG001
    return []


def share_pick(pool: list, chat_key: str, now: float | None = None):   # noqa: ARG001
    return None


def share_context(entry: dict) -> str:   # noqa: ARG001
    return ""


def mark_shared(chat_key: str, code: str) -> None:   # noqa: ARG001
    return None
