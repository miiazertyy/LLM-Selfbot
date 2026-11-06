"""app/utils/instagramsocial.py - what the persona knows of Instagram beyond its DMs, said to the model.

The Instagram runner goes out in a tab of its own (app/platforms/snapchat/instagram_runner.js). Some of it it always
does (watching what it is sent, reading the posts and stories of the people it talks to); the rest only when switched
on in Settings (Reels, likes, comments, its own posts and stories, its Note). This module says what came of it, for
the engine:
  * who someone is on Instagram, what they post and whose story it just watched, in a DM with them (profile_block,
    dm_context)
  * what it saw on Reels today, so it has things to talk about (seen_block)
  * the comment it is about to write under someone's post (comment_context, clean_comment)
  * the Note it is about to set (note_context, clean_note)
  * a reel to send when someone asks for one, on any platform whose persona has an Instagram account (wants_reel,
    pools_for, share_pick, share_context, mark_shared)

Everything here reads files the runner wrote (cache/instagram_people) and what instagramwatch kept: callers on an
event loop run it on a worker thread.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from app.utils import instagramwatch


def people_dir() -> Path:
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "instagram_people"


def _read(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _clip(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3].rsplit(" ", 1)[0] + "..."


# ── Who they are on Instagram, in a DM with them ─────────────────────────────

def profile_block(contact: dict, username: str, newest: dict | None = None, news: bool = False,
                  story: dict | None = None) -> str:
    """Their Instagram, for the model: username and name, followers, bio, their latest posts, their newest one as it
    was watched, and the story of theirs it has just seen. `news`: they posted it since the persona last talked to
    them."""
    contact = contact if isinstance(contact, dict) else {}
    if not username:
        return ""
    name = str(contact.get("name") or "").strip()
    who = f"@{username}" + (f" ({_clip(name, 40)})" if name and name.lower().lstrip("@") != username else "")
    bits = [who]
    if contact.get("followers"):
        bits.append(f"{instagramwatch.count_str(int(contact['followers']))} followers")
    if contact.get("verified"):
        bits.append("verified")
    if contact.get("private"):
        bits.append("a private account")
    out = "THEIR INSTAGRAM: " + ", ".join(bits) + "."
    bio = " ".join(str(contact.get("bio") or "").split())
    if bio:
        out += f' Their bio: "{_clip(bio, 200)}".'
    posts = [p for p in (contact.get("posts") or []) if isinstance(p, dict)][:3]
    if posts:
        said = []
        for p in posts:
            line = f'"{_clip(p.get("caption"), 90)}"' if p.get("caption") else "one with no caption"
            if p.get("kind") == "reel":
                line += " (a reel)"
            said.append(line)
        out += " Their latest posts: " + "; ".join(said) + "."
    if newest and (newest.get("seen") or newest.get("said")):
        out += " " + instagramwatch.summary(newest, lead="their newest post", react=False).strip("[]")
        if news:
            out += (" They posted it since you last talked: you can bring it up if it fits, the way a friend who saw "
                    "it would, without making a thing of it.")
    if story and (story.get("seen") or story.get("caption")):
        seen = story.get("seen") or story.get("caption")
        out += (f' YOU SAW THEIR STORY today: {_clip(seen, 180)}. They can see that you watched it, so bringing it '
                'up is natural; only do it if the conversation goes there.')
    return out + " Only use any of this if it fits; never recite it."


def contact_of(account: int, chat_id: str) -> dict:
    from app.utils import snappeople
    return snappeople.contacts(account, "instagram").get(str(chat_id)) or {}


def _told_path(account: int) -> Path:
    return people_dir() / f"told_{int(account)}.json"


def dm_context(account: int, chat_id: str, username: str) -> str:
    """What the persona knows of this person's Instagram, for a DM with them; their newest post is news once."""
    contact = contact_of(account, chat_id)
    if not contact and not username:
        return ""
    newest_url = str(contact.get("newest") or "")
    newest = instagramwatch.seen_for(newest_url) if newest_url else None
    story = None
    story_key = str(contact.get("story_seen") or "")
    if story_key:
        story = instagramwatch.cached(story_key)
    told = _read(_told_path(account), {})
    news = bool(newest and told.get(chat_id) != newest_url and contact.get("posts_at"))
    if newest_url and told.get(chat_id) != newest_url:
        told[chat_id] = newest_url
        try:
            from app.utils.atomic import write_json_atomic
            write_json_atomic(_told_path(account), told)
        except Exception:
            pass
    return profile_block(contact, username, newest, news, story)


# ── What it saw on Reels today ───────────────────────────────────────────────

def seen_pool(account: int) -> list:
    """The reels the account saw lately (the runner's seen_N.json): [{id, url, handle, caption, liked, at}]."""
    return [v for v in _read(people_dir() / f"seen_{int(account)}.json", []) if isinstance(v, dict) and v.get("id")]


def seen_block(pool: list, now: float | None = None, most: int = 3) -> str:
    """A few things it watched on Reels today (the ones it watched properly), so it has things to talk about."""
    now = now or time.time()
    lines = []
    for v in reversed(pool):
        if now - float(v.get("at") or 0) > 86400:
            continue
        w = instagramwatch.cached(str(v.get("id") or ""))
        if not w or not w.get("seen"):
            continue
        line = f"@{w.get('author') or v.get('handle') or 'someone'}'s reel: {_clip(w['seen'], 160)}"
        if v.get("liked"):
            line += " (you liked it)"
        lines.append(line)
        if len(lines) >= most:
            break
    if not lines:
        return ""
    return ("THINGS YOU SAW ON INSTAGRAM TODAY, scrolling Reels: " + " | ".join(lines)
            + ". Bring one up only if the conversation goes there.")


# ── A comment under someone's post ───────────────────────────────────────────

WHOSE = {
    "sent": "a reel someone sent you",
    "theirs": "the newest post of someone you talk to",
    "reels": "a reel on your Reels",
    "mine": "one of your own posts",
}


def comment_context(why: str) -> str:
    return (f"PUBLIC COMMENT: you are writing a comment under {WHOSE.get(why, 'an Instagram post')}, in public, "
            "where the person who posted it and everyone else can read it. The message is what the post is, as you "
            "watched it. Write one short, natural comment about the post itself, the kind people leave under posts. "
            "No hashtags, no @mentions, nothing private, nothing from your DMs.")


def clean_comment(text: str) -> str:
    """A comment as it goes up: its first line, no hashtags or @mentions (Instagram would turn them into tags),
    short."""
    line = str(text or "").strip().split("\n")[0]
    line = re.sub(r"(?<!\w)[#@][\w.]+", "", line)
    line = re.sub(r"\s{2,}", " ", line).strip(" -")
    return line[:150].strip()


# ── Its Note ─────────────────────────────────────────────────────────────────

def note_context(mood: str = "") -> str:
    return ("YOUR INSTAGRAM NOTE: you are writing the little note that sits above your name in everyone's inbox for "
            "the next day. At most 60 characters, one line, no quotes and no hashtags: a thought, a mood, a lyric, "
            "something you would actually put there"
            + (f". Your mood right now is {mood}." if mood else "."))


def clean_note(text: str) -> str:
    """A Note as it goes up: one line, 60 characters, no quotes around it."""
    line = str(text or "").strip().split("\n")[0].strip().strip('"').strip("'")
    line = re.sub(r"\s{2,}", " ", line)
    return line[:60].strip()


# ── Sharing a reel when someone asks for one ─────────────────────────────────

_ASK = re.compile(
    r"\b(?:send|show|share|drop|give|got|have|any)\b[^.?!\n]{0,30}\b(?:reels?|insta(?:gram)?s?)\b"
    r"|\b(?:envoie|envoies|envoyer|montre|montres|partage|balance|t['’]?as|tu as)\b[^.?!\n]{0,30}"
    r"\b(?:reels?|insta(?:gram)?s?)\b",
    re.I)


def wants_reel(text: str) -> bool:
    """Whether they are asking for a reel: "send me a reel", "got any good reels?", "envoie moi un reel"."""
    return bool(_ASK.search(str(text or "")))


def instagram_accounts_of(pid: str) -> list[int]:
    """The Instagram accounts that speak as this persona (whose pools a share can come from)."""
    from app.utils import personas
    out = []
    for path in people_dir().glob("seen_*.json"):
        n = path.stem.split("_", 1)[1]
        if n.isdigit() and personas.persona_of(f"instagram_{n}") == pid:
            out.append(int(n))
    return sorted(out)


def pools_for(pid: str) -> list:
    pool = []
    for n in instagram_accounts_of(pid):
        pool += seen_pool(n)
    return pool


def _shared_path() -> Path:
    return people_dir() / "shared.json"


def share_pick(pool: list, chat_key: str, now: float | None = None) -> dict | None:
    """A reel to send them: one it saw in the last three days and not sent to them yet, a liked one first, the
    newest first."""
    now = now or time.time()
    sent = set(_read(_shared_path(), {}).get(chat_key) or [])
    fresh = [v for v in pool if v.get("url") and v.get("id") not in sent and now - float(v.get("at") or 0) < 3 * 86400]
    if not fresh:
        return None
    fresh.sort(key=lambda v: (bool(v.get("liked")), float(v.get("at") or 0)), reverse=True)
    return fresh[0]


def mark_shared(chat_key: str, code: str) -> None:
    data = _read(_shared_path(), {})
    data[chat_key] = ((data.get(chat_key) or []) + [code])[-50:]
    while len(data) > 500:
        data.pop(next(iter(data)))
    try:
        from app.utils.atomic import write_json_atomic
        write_json_atomic(_shared_path(), data)
    except Exception:
        pass


def share_context(entry: dict) -> str:
    """Telling the model it is sending this reel, right after its reply, as its own message."""
    w = instagramwatch.cached(str(entry.get("id") or ""))
    if w and (w.get("seen") or w.get("said")):
        what = instagramwatch.summary(w, lead="it", react=False).strip("[]")
    else:
        what = (f'it is by @{entry.get("handle") or "someone"}'
                + (f', captioned "{_clip(entry.get("caption"), 120)}"' if entry.get("caption") else ""))
    return ("YOU ARE SENDING THEM A REEL: they asked for one, and right after this reply you send them one you saw on "
            f"Instagram: {what} Say something short to go with it, as you would when sending a friend a reel. Do not "
            "paste a link: it goes on its own.")


def share_settings() -> bool:
    try:
        from app.utils.helpers import load_config
        return bool(((load_config().get("instagram") or {}).get("share") or {}).get("enabled", False))
    except Exception:
        return False


def story_settings() -> dict:
    """instagram.stories.*: whether it watches people's stories, answers some, and posts its own."""
    try:
        from app.utils.helpers import load_config
        raw = (load_config().get("instagram") or {}).get("stories")
    except Exception:
        raw = None
    raw = raw if isinstance(raw, dict) else {}
    return {"watch": bool(raw.get("watch", True)), "reply": bool(raw.get("reply", False)),
            "post": bool(raw.get("post", False)), "per_day": int(raw.get("replies_per_day") or 3)}
