"""app/utils/tiktoksocial.py - what the persona knows of TikTok beyond its DMs, said to the model.

The TikTok runner goes out in a tab of its own (app/platforms/snapchat/tiktok_runner.js). Some of this it always does
(watching what it is sent, reading the posts of the people it talks to); the rest only when switched on in Settings
(For You, comments under videos, LIVE visits). This module says what came of it, for the engine:
  * who someone is on TikTok and what they post, in a DM with them (profile_block)
  * what it saw on For You today, so it has things to talk about (seen_block)
  * the comment it is about to write under someone's video (comment_context, clean_comment)
  * a TikTok to send when someone asks for one, on any platform whose persona has a TikTok account (wants_tiktok,
    pools_for, share_pick, share_context, mark_shared)

Everything here reads files the runner wrote (cache/tiktok_people) and what tiktokwatch kept: callers on an event
loop run it on a worker thread.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from app.utils import tiktokwatch


def people_dir() -> Path:
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "tiktok_people"


def _read(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _clip(text, n: int) -> str:
    return tiktokwatch._clip(str(text or ""), n)


# ── Who they are on TikTok, in a DM with them ────────────────────────────────

def profile_block(contact: dict, handle: str, newest: dict | None = None, news: bool = False) -> str:
    """Their TikTok, for the model: @handle and name, followers, bio, their latest posts, and their newest one as it
    was watched. `news`: they posted it since the persona last talked to them."""
    contact = contact if isinstance(contact, dict) else {}
    if not handle:
        return ""
    name = str(contact.get("name") or "").strip()
    who = f"@{handle}" + (f" ({_clip(name, 40)})" if name and name.lower().lstrip("@") != handle else "")
    bits = [who]
    if contact.get("followers"):
        bits.append(f"{tiktokwatch.count(int(contact['followers']))} followers")
    if contact.get("verified"):
        bits.append("verified")
    out = "THEIR TIKTOK: " + ", ".join(bits) + "."
    bio = " ".join(str(contact.get("bio") or "").split())
    if bio:
        out += f' Their bio: "{_clip(bio, 200)}".'
    posts = [p for p in (contact.get("posts") or []) if isinstance(p, dict)][:3]
    if posts:
        said = []
        for p in posts:
            line = f'"{_clip(p.get("caption"), 90)}"' if p.get("caption") else "one with no caption"
            if p.get("views"):
                line += f" ({p['views']} views)"
            if p.get("pinned"):
                line += " (pinned)"
            said.append(line)
        out += " Their latest posts: " + "; ".join(said) + "."
    if newest and (newest.get("seen") or newest.get("said")):
        out += " " + tiktokwatch.summary(newest, lead="their newest TikTok", react=False).strip("[]")
        if news:
            out += (" They posted it since you last talked: you can bring it up if it fits, the way a friend who saw "
                    "it would, without making a thing of it.")
    return out + " Only use any of this if it fits; never recite it."


def contact_of(account: int, chat_id: str) -> dict:
    from app.utils import snappeople
    return snappeople.contacts(account, "tiktok").get(str(chat_id)) or {}


def _told_path(account: int) -> Path:
    return people_dir() / f"told_{int(account)}.json"


def dm_context(account: int, chat_id: str, handle: str) -> str:
    """What the persona knows of this person's TikTok, for a DM with them; their newest post is news once."""
    contact = contact_of(account, chat_id)
    if not contact and not handle:
        return ""
    newest_id = str(contact.get("newest") or "")
    newest = tiktokwatch.cached(newest_id) if newest_id else None
    told = _read(_told_path(account), {})
    news = bool(newest and told.get(chat_id) != newest_id and contact.get("posts_at"))
    if newest_id and told.get(chat_id) != newest_id:
        told[chat_id] = newest_id
        try:
            from app.utils.atomic import write_json_atomic
            write_json_atomic(_told_path(account), told)
        except Exception:
            pass
    return profile_block(contact, handle, newest, news)


# ── What it saw on For You today ─────────────────────────────────────────────

def seen_pool(account: int) -> list:
    """The For You videos the account saw lately (the runner's seen_N.json): [{id, url, handle, caption, liked, at}]."""
    return [v for v in _read(people_dir() / f"seen_{int(account)}.json", []) if isinstance(v, dict) and v.get("id")]


def seen_block(pool: list, now: float | None = None, most: int = 3) -> str:
    """A few things it watched on For You today (the ones it watched properly), so it has things to talk about."""
    now = now or time.time()
    lines = []
    for v in reversed(pool):
        if now - float(v.get("at") or 0) > 86400:
            continue
        w = tiktokwatch.cached(str(v.get("id") or ""))
        if not w or not w.get("seen"):
            continue
        line = f"@{w.get('author') or v.get('handle') or 'someone'}'s video: {_clip(w['seen'], 160)}"
        if v.get("liked"):
            line += " (you liked it)"
        lines.append(line)
        if len(lines) >= most:
            break
    if not lines:
        return ""
    return ("THINGS YOU SAW ON TIKTOK TODAY, scrolling For You: " + " | ".join(lines)
            + ". Bring one up only if the conversation goes there.")


# ── A comment under someone's video ──────────────────────────────────────────

WHOSE = {
    "sent": "a TikTok someone sent you",
    "theirs": "the newest TikTok of someone you talk to",
    "foryou": "a TikTok on your For You",
}


def comment_context(why: str) -> str:
    return (f"PUBLIC COMMENT: you are writing a comment under {WHOSE.get(why, 'a TikTok')}, in public, where the "
            "person who posted it and everyone watching can read it. The message is what the video is, as you watched "
            "it. Write one short, natural comment about the video itself, the kind people leave under videos. No "
            "hashtags, no @mentions, nothing private, nothing from your DMs.")


def clean_comment(text: str) -> str:
    """A comment as it goes up: its first line, no hashtags or @mentions (TikTok would turn them into tags), short."""
    line = str(text or "").strip().split("\n")[0]
    line = re.sub(r"(?<!\w)[#@][\w.]+", "", line)
    line = re.sub(r"\s{2,}", " ", line).strip(" -")
    return line[:150].strip()


# ── Sharing a TikTok when someone asks for one ───────────────────────────────

_ASK = re.compile(
    r"\b(?:send|show|share|drop|give|got|have|any)\b[^.?!\n]{0,30}\btik\s?toks?\b"
    r"|\b(?:envoie|envoies|envoyer|montre|montres|partage|balance|t['’]?as|tu as)\b[^.?!\n]{0,30}\btik\s?toks?\b",
    re.I)


def wants_tiktok(text: str) -> bool:
    """Whether they are asking for a TikTok: "send me a tiktok", "got any good tiktoks?", "envoie moi un tiktok"."""
    return bool(_ASK.search(str(text or "")))


def tiktok_accounts_of(pid: str) -> list[int]:
    """The TikTok accounts that speak as this persona (whose pools a share can come from)."""
    from app.utils import personas
    out = []
    for path in people_dir().glob("seen_*.json"):
        n = path.stem.split("_", 1)[1]
        if n.isdigit() and personas.persona_of(f"tiktok_{n}") == pid:
            out.append(int(n))
    return sorted(out)


def pools_for(pid: str) -> list:
    pool = []
    for n in tiktok_accounts_of(pid):
        pool += seen_pool(n)
    return pool


def _shared_path() -> Path:
    return people_dir() / "shared.json"


def share_pick(pool: list, chat_key: str, now: float | None = None) -> dict | None:
    """A TikTok to send them: one it saw in the last three days and not sent to them yet, a liked one first, the
    newest first."""
    now = now or time.time()
    sent = set(_read(_shared_path(), {}).get(chat_key) or [])
    fresh = [v for v in pool if v.get("url") and v.get("id") not in sent and now - float(v.get("at") or 0) < 3 * 86400]
    if not fresh:
        return None
    fresh.sort(key=lambda v: (bool(v.get("liked")), float(v.get("at") or 0)), reverse=True)
    return fresh[0]


def mark_shared(chat_key: str, vid: str) -> None:
    data = _read(_shared_path(), {})
    data[chat_key] = ((data.get(chat_key) or []) + [vid])[-50:]
    while len(data) > 500:
        data.pop(next(iter(data)))
    try:
        from app.utils.atomic import write_json_atomic
        write_json_atomic(_shared_path(), data)
    except Exception:
        pass


def share_context(entry: dict) -> str:
    """Telling the model it is sending this TikTok, right after its reply, as its own message."""
    w = tiktokwatch.cached(str(entry.get("id") or ""))
    what = (tiktokwatch.summary(w, lead="it", react=False).strip("[]") if w and (w.get("seen") or w.get("said"))
            else f'it is by @{entry.get("handle") or "someone"}' + (f', captioned "{_clip(entry.get("caption"), 120)}"'
                                                                  if entry.get("caption") else ""))
    return ("YOU ARE SENDING THEM A TIKTOK: they asked for one, and right after this reply you send them one you saw on "
            f"TikTok: {what} Say something short to go with it, as you would when sending a friend a video. Do not "
            "paste a link: it goes on its own.")


def share_settings() -> bool:
    try:
        from app.utils.helpers import load_config
        return bool(((load_config().get("tiktok") or {}).get("share") or {}).get("enabled", False))
    except Exception:
        return False
