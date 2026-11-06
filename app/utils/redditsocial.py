"""What the persona knows of someone on Reddit, and how it speaks in public there.

The pair to app/utils/redditwatch.py: that one reads a post, this one says what it knows of a person - their
username, their karma, what they have been posting - so a reply can sound like it is talking to somebody rather
than to a text box. Built like app/utils/xsocial.py, and read by the bridge through _social().

Two things here are Reddit's alone:

  Where it may speak. reddit.subreddits is the whole of it: a list of names, and nothing outside that list is
  commented on or posted to, whatever else is switched on. allowed() is the one place that is decided.

  What a comment may look like. Reddit is markdown, it has no character limit worth the name, and a comment that
  opens with a hashtag pile or closes with "Hope this helps!" is read as a bot within a second. clean_comment
  takes those off.

Reddit does not share things the way Instagram shares reels, so the share pieces here answer "no" and stay out of
the way; they exist because the bridge asks every platform the same questions.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.utils import redditwatch


def people_dir() -> Path:
    from app.utils.paths import DATA_DIR
    p = DATA_DIR / "cache" / "reddit_people"
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
    return snappeople.contacts(account, "reddit").get(str(chat_id)) or {}


def _told_path(account: int) -> Path:
    return people_dir() / f"told_{int(account)}.json"


def profile_block(contact: dict, username: str, newest: dict | None = None, news: bool = False) -> str:
    """Their Reddit, for the model: their name, their karma, how long they have been there, and their newest post
    as it was read. `news`: they posted it since the persona last talked to them."""
    contact = contact if isinstance(contact, dict) else {}
    username = str(username or "").lstrip("@").removeprefix("u/")
    if not username:
        return ""
    bits = [f"u/{username}"]
    karma = contact.get("karma")
    if karma:
        bits.append(f"{redditwatch.count_str(karma)} karma")
    if contact.get("years"):
        bits.append(f"on Reddit {contact['years']} years")
    if contact.get("moderates"):
        bits.append("a moderator")
    out = "THEIR REDDIT: " + ", ".join(bits) + "."
    bio = " ".join(str(contact.get("bio") or "").split())
    if bio:
        out += f' Their about: "{_clip(bio, 200)}".'
    if newest and (newest.get("title") or newest.get("text") or newest.get("seen")):
        out += " " + redditwatch.summary(newest, lead="their newest post", react=False).strip("[]")
        if news:
            out += (" They posted it since you last talked: you can bring it up if it fits, the way somebody who "
                    "saw it would, without making a thing of it.")
    return out + " Only use any of this if it fits; never recite it."


def dm_context(account: int, chat_id: str, username: str) -> str:
    """What the persona knows of this person's Reddit, for a chat with them. Their newest post is news once."""
    contact = contact_of(account, chat_id)
    if not contact and not username:
        return ""
    newest_url = str(contact.get("newest") or "")
    newest = redditwatch.cached(newest_url) if newest_url else None
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

def mention_context(why: str = "", sub: str = "") -> str:
    """How to answer a reply or a u/ mention: it is public, it is permanent, and the room is reading."""
    where = f" in r/{str(sub).lstrip('r/')}" if sub else ""
    return (f"You are answering in public on Reddit{where}, under a post. Anyone can read it, and it stays there. "
            "Keep it to a line or two, in your own voice, and answer the person rather than the room. No hashtags, "
            "no sign-off, nothing that reads like a brand or like an assistant."
            + (f" {why}" if why else ""))


def comment_context(title: str = "", sub: str = "", why: str = "") -> str:
    """How to comment under somebody's post nobody asked it to. The bar is higher than a reply's: a comment that
    adds nothing is what gets an account noticed, and on Reddit noticed means hidden."""
    where = f"r/{str(sub).lstrip('r/')}" if sub else "a subreddit"
    out = (f"You are writing one comment under somebody's post in {where}. Say something you would actually say: "
           "answer what they asked, or add the one thing you know that the thread does not have yet. If you have "
           "nothing to add, say nothing. No sign-off, no 'hope this helps', no hashtags, no emoji.")
    if title:
        out += f' The post is titled: "{_clip(title, 200)}".'
    return out + (f" {why}" if why else "")


def clean_reply(text: str, most: int = 1200) -> str:
    """A public answer, tidied: no leading u/ (Reddit puts that there itself), no sign-off, short enough to post."""
    s = " ".join(str(text or "").split())
    while s.lower().startswith(("u/", "/u/", "@")):
        s = s.split(" ", 1)[1] if " " in s else ""
    s = s.strip().strip('"')
    return s[: most - 1].rstrip() + "…" if len(s) > most else s


#: The ways a model signs off, which no person on Reddit does.
_SIGN_OFFS = ("hope this helps", "hope that helps", "let me know if", "feel free to ask", "good luck!",
              "happy to help", "tl;dr:", "edit:")


def clean_comment(text: str, most: int = 1200) -> str:
    """A comment of its own, tidied: no quotes around the whole thing, no hashtag pile, no sign-off."""
    s = " ".join(str(text or "").split()).strip().strip('"')
    while s.endswith("#") or (" " in s and s.rsplit(" ", 1)[-1].startswith("#")):
        s = s.rsplit(" ", 1)[0].rstrip()
    low = s.lower()
    for tail in _SIGN_OFFS:
        at = low.rfind(tail)
        # Only when it is the last thing said, which is where a sign-off lives.
        if at >= 0 and at > len(s) - 120:
            # Only the join is taken off, never the sentence's own full stop.
            s = s[:at].rstrip(" ,-\u2014")
            low = s.lower()
    return s[: most - 1].rstrip() + "…" if len(s) > most else s


def post_context(mood: str = "", saw: str = "", sub: str = "") -> str:
    """How to write a post of its own: a title and a body, not an announcement."""
    where = f"r/{str(sub).lstrip('r/')}" if sub else "your own profile"
    out = (f"Write one post for {where}, in your own voice: something you would actually post, not an "
           "announcement. Give it a plain title on the first line and the post itself after it. No hashtags, no "
           "emoji in the title, nobody tagged.")
    if mood:
        out += f" You are feeling {mood}."
    if saw:
        out += f" Something you read earlier, if you want to post about it: {_clip(saw, 400)}"
    return out


def clean_post(text: str, most: int = 1500) -> tuple[str, str]:
    """A post of its own, split the way Reddit wants it: ("title", "body"). The first line is the title, which
    Reddit caps at 300 characters, and everything after it is the body."""
    s = str(text or "").strip().strip('"')
    lines = [ln.strip() for ln in s.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return "", ""
    title = lines[0].strip().strip('"').lstrip("#").strip()
    # A model that was told "title on the first line" sometimes writes "Title: ..." anyway.
    for lead in ("title:", "post:"):
        if title.lower().startswith(lead):
            title = title[len(lead):].strip()
    body = " ".join(lines[1:]).strip()
    if len(title) > 300:
        body = (title[297:] + " " + body).strip()
        title = title[:297].rstrip() + "…"
    return title, (body[: most - 1].rstrip() + "…" if len(body) > most else body)


def settings(config: dict | None = None) -> dict:
    """The reddit.posting, reddit.comments and reddit.engage blocks, with what the shipped config carries."""
    if config is None:
        from app.utils.helpers import load_config
        try:
            config = load_config()
        except Exception:
            config = {}
    reddit = (config or {}).get("reddit") or {}
    posting = reddit.get("posting") or {}
    comments = reddit.get("comments") or {}
    where = posting.get("from") or {}
    return {
        "posting": bool(posting.get("enabled", False)),
        "where": str(posting.get("where", "profile") or "profile"),
        "per_day": int(posting.get("per_day", 1) or 1),
        "max_chars": int(posting.get("max_chars", 1500) or 1500),
        "from_web": bool(where.get("saw_online", True)),
        "from_mind": bool(where.get("on_its_mind", True)),
        "comments": bool(comments.get("enabled", False)),
        "comment_chars": int(comments.get("max_chars", 1200) or 1200),
        "inbox": bool((reddit.get("inbox") or {}).get("enabled", True)),
        "subreddits": subreddits(config),
    }


def subreddits(config: dict | None = None) -> list[str]:
    """The subreddits it may take part in, lowercased and without their r/. Empty means its own profile and the
    threads it is already in, which is all a young account can do anyway."""
    if config is None:
        from app.utils.helpers import load_config
        try:
            config = load_config()
        except Exception:
            config = {}
    raw = ((config or {}).get("reddit") or {}).get("subreddits") or ""
    out = []
    for piece in str(raw).replace(";", ",").replace("\n", ",").split(","):
        name = piece.strip().lstrip("/").removeprefix("r/").strip("/ ").lower()
        if name and name not in out and len(name) <= 21:
            out.append(name)
    return out


def allowed(sub: str, config: dict | None = None) -> bool:
    """Whether it may say anything in this subreddit. The one place that is decided, so there is one answer to it
    wherever it is asked: its own profile is always allowed, a named subreddit only if it is on the list."""
    name = str(sub or "").strip().lstrip("/").removeprefix("r/").strip("/ ").lower()
    if not name or name.startswith("u_"):
        return True          # its own profile page, which always takes a post
    return name in subreddits(config)


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
# Reddit has nothing to share the way Instagram shares a reel, so these answer no and keep out of the way.

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
