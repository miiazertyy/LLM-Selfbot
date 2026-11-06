"""community_rules.py - what a community profile may hold, checked the same way on both sides.

Community profiles (Profiles, Community) are shared through the app's own GitHub repo with no server of our own: the
app sends a request (an issue) and GitHub Actions in the repo publishes it. Both sides check everything with this one
file: the app before sending and again before installing anything, the repo's workflow before publishing. The
workflow's scripts keep a byte-identical copy (community/scripts/community_rules.py; a test compares the two), so
this file imports nothing from the app: only the standard library, and Pillow, lazily, for pictures.

A shared profile is its text, the part of its settings that says who it is and how it talks (ALLOWED, exact keys
only), its face, and the pictures and short videos its author picked. Never memory, chats, accounts, keys, models or
limits. Every problem is said in a plain sentence, for the person who sent it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import unicodedata
import zipfile

RULES = 1
SCHEMA = 1

# Where the community lives in the app's repo, the same for both sides. The profiles have a branch of their own, so the
# app's code and history never mix with them. One release holds every profile's download (one file per version):
# GitHub counts each download, and it's marked as a pre-release so it's never taken for a version of the app. The
# issues the community uses all carry a label starting with "profile-".
DATA_BRANCH = "community-data"
RELEASE_TAG = "community-profiles"
_ASSET = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)-v([1-9]\d{0,5})\.zip$")


def label(kind: str) -> str:
    """The label for one kind of community issue: "request", "report", "published" and so on."""
    return f"profile-{kind}"


def asset_name(slug: str, version: int) -> str:
    """A version's file in the release. Never reused: a new version is a new file, so a count is never reset."""
    return f"{slug}-v{int(version)}.zip"


def parse_asset(name: str) -> tuple | None:
    """(slug, version) from a release file's name, or None when it isn't one of the community's."""
    m = _ASSET.match(str(name or ""))
    return (m.group(1), int(m.group(2))) if m else None


# The app version a profile was sent from, so everyone can see whether it was made for the app they have.
_APP = re.compile(r"^v?(\d{1,4}(?:\.\d{1,5}){1,3})(?:[-+][0-9A-Za-z.-]{1,24})?$")


def app_version(value) -> str:
    """An app version as it's shown ("1.7.1", from "v1.7.1" or "1.7.1-beta.2"); "" when it isn't one, or is a
    development build's "0.0.0-dev", which tells nobody anything."""
    m = _APP.match(str(value or "").strip())
    if not m or not any(int(n) for n in m.group(1).split(".")):
        return ""
    return m.group(1)


def version_key(value) -> tuple:
    """An app version as numbers to compare, "1.7" the same as "1.7.0"."""
    parts = [int(n) for n in (app_version(value) or "0").split(".")]
    return tuple(parts + [0] * (4 - len(parts)))

LIMITS = {
    "slug": (3, 32),
    "name": 40,
    "tagline": 90,
    "description": 600,
    "description_lines": 8,
    "author": (2, 32),
    "tags": 5,
    "tag": 20,
    "note": 200,
    "text": (200, 20_000),
    "text_words": 30,
    "text_lines": 600,
    "settings": 40,
    "pictures": 20,
    "videos": 4,
    "video_seconds": 30.5,
    "video_bytes": 20_000_000,
    "picture_bytes": 3_000_000,
    "package_bytes": 100_000_000,
    # The request's core (text, settings, face) rides in the issue itself, base64 inside a comment: GitHub keeps an
    # issue body to 65,536 characters, and a summary goes with it.
    "core_bytes": 42_000,
    "body_chars": 65_000,
    "avatar_side": 256,
    "picture_side": 1600,
    "thumb_side": 240,
    "part_chars": 900_000,
}

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
LANG = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
GIST = re.compile(r"^[0-9a-f]{20,40}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
MEDIA_NAME = re.compile(r"^m(\d{2})\.(jpg|mp4)$")

RESERVED = frozenset({
    "default", "everyone", "all", "new", "admin", "official", "community", "llmselfbot", "moderator", "staff",
    "support", "test", "help", "mod", "owner",
})
TAGS = (
    "chill", "funny", "flirty", "sweet", "sarcastic", "wholesome", "dramatic", "shy", "chaotic", "gamer", "anime",
    "student", "artist", "music", "sports", "roleplay", "friendly", "mysterious", "romantic", "nerdy",
)

# A blank left in the template: a word in capitals, then whatever hint follows it ("[HOBBIES - games, music...]").
_PLACEHOLDER = re.compile(r"\[[A-Z]{2,}[^\]\n]{0,80}\]")
# Control characters, zero-width and direction marks: kept out, so nothing can hide or turn text around.
_INVISIBLE = "".join(chr(c) for c in (*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065),
                                       *range(0x2066, 0x206A), 0xFEFF))
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f" + re.escape(_INVISIBLE) + "]")


# ── Text ─────────────────────────────────────────────────────────────────────

def normalize_text(text) -> str:
    """Text as it is kept: NFC, LF line ends, no control characters, no spaces at line ends, no blank edges."""
    t = unicodedata.normalize("NFC", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    t = _CTRL.sub("", t)
    lines = [line.rstrip() for line in t.split("\n")]
    return "\n".join(lines).strip("\n")


def one_line(text, limit: int = 0) -> str:
    t = re.sub(r"\s+", " ", _CTRL.sub("", unicodedata.normalize("NFC", str(text or "")))).strip()
    return t[:limit].rstrip() if limit else t


def slug_from(name) -> str:
    """A slug from a name: plain lowercase letters, numbers and single dashes, 3 to 32 of them."""
    t = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    s = s[:32].strip("-")
    if len(s) < 3:
        s = f"{s}-profile" if s else "profile"
    return s


def words(text) -> int:
    return len(str(text or "").split())


# ── What can be found in text ────────────────────────────────────────────────
# Each kind has a pattern. The workflow refuses the dangerous ones (REFUSE); a handle is only pointed out; "yours"
# (the author's own usernames and ids) is the app's alone, as it knows them and the repo does not.

_TLD = (r"com|net|org|io|gg|me|co|ly|app|xyz|tv|link|site|online|shop|store|info|biz|live|club|top|fr|de|uk|us|ru|"
        r"cn|es|it|nl|be|ch|ca|au|br|in|jp|kr|pl|pt|se|no|dk|fi|cz|gr|tr|ua|vip|fun|pro|cc|to|sh|ai|so|gl|tk|ml|ga|cf")
_PATTERNS = [
    ("invite", re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:discord(?:app)?\.(?:gg|com/invite)|discord\.gg|t\.me|"
                          r"telegram\.(?:me|dog)|chat\.whatsapp\.com|wa\.me|snapchat\.com/add|instagram\.com|"
                          r"onlyfans\.com|fansly\.com|linktr\.ee|cash\.app)\S*")),
    ("email", re.compile(r"(?i)\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("link", re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9-]{1,62}\.(?:" + _TLD + r")\b(?:/\S*)?")),
    ("money", re.compile(r"(?i)\b(?:cash\s?app|venmo|paypal|zelle|revolut|western\s+union|moneygram|gift\s?cards?|"
                         r"steam\s?cards?|nitro\s+gift|bitcoin|btc|ethereum|usdt|crypto\s?wallet|wallet\s+address)\b|"
                         r"(?<![\w$])\$[A-Za-z][\w]{2,20}\b|\bbc1[a-z0-9]{20,60}\b|\b0x[a-fA-F0-9]{40}\b")),
    ("secret", re.compile(r"(?i)\b(?:passwords?|passcodes?|2fa|two[\s-]factor|verification\s+codes?|login\s+codes?|"
                          r"one[\s-]time\s+codes?|otp|seed\s+phrases?|recovery\s+phrases?|private\s+keys?|api\s+keys?|"
                          r"tokens?)\b")),
    ("id", re.compile(r"(?<!\d)\d{17,20}(?!\d)")),
    ("phone", re.compile(r"(?<![\w+])\+?\d[\d\s().-]{7,18}\d(?!\w)")),
    ("handle", re.compile(r"(?<![\w@./])@[A-Za-z0-9_.]{2,30}\b")),
]
REFUSE = frozenset({"invite", "link", "email", "money", "secret", "phone", "id"})
WARN = frozenset({"handle", "yours"})
KIND_WORDS = {
    "invite": "an invite or social link",
    "link": "a link",
    "email": "an email address",
    "money": "a payment or money word",
    "secret": "something about passwords or codes",
    "phone": "a phone number",
    "id": "a long number like an account id",
    "handle": "an @handle",
    "yours": "one of your own usernames or ids",
}


def scan(fields: dict, yours=()) -> list:
    """Every risky thing in these texts ({field: text}): [{kind, field, match, start, end}], in reading order. `yours`
    is the author's own usernames and ids, found as whole words."""
    out = []
    needles = [str(y).strip().lstrip("@") for y in yours or () if len(str(y).strip().lstrip("@")) >= 3]
    for field, text in fields.items():
        text = str(text or "")
        taken: list = []
        for kind, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                s, e = m.start(), m.end()
                if kind == "phone" and sum(ch.isdigit() for ch in m.group(0)) < 9:
                    continue
                if any(s < te and ts < e for ts, te in taken):
                    continue
                taken.append((s, e))
                shown = m.group(0).strip().rstrip(".,;:!?)'\"")
                out.append({"kind": kind, "field": field, "match": shown[:80], "start": s, "end": e})
        for needle in needles:
            for m in re.finditer(rf"(?i)(?<![\w]){re.escape(needle)}(?![\w])", text):
                s, e = m.start(), m.end()
                if any(s < te and ts < e for ts, te in taken):
                    continue
                taken.append((s, e))
                out.append({"kind": "yours", "field": field, "match": m.group(0)[:80], "start": s, "end": e})
    out.sort(key=lambda f: (str(f["field"]), f["start"]))
    return out


def scan_problems(findings: list, field_names: dict | None = None) -> list:
    """The refused findings as sentences: "The text has a link (example.com).", one per kind and field."""
    names = field_names or {}
    seen, out = set(), []
    for f in findings:
        if f["kind"] not in REFUSE or (f["kind"], f["field"]) in seen:
            continue
        seen.add((f["kind"], f["field"]))
        where = names.get(f["field"]) or _field_word(f["field"])
        out.append(f"{where} has {KIND_WORDS[f['kind']]} ({f['match']}). Take it out and send it again.")
    return out


def _field_word(field: str) -> str:
    if field == "text":
        return "The text"
    if field.startswith("settings:"):
        return f"The setting {field.split(':', 1)[1]}"
    return f"The {field}"


# ── The details ──────────────────────────────────────────────────────────────

def check_meta(meta, *, tags=TAGS, reserved=RESERVED) -> tuple:
    """The details of a request ({slug, name, tagline, description, tags, color, author, adult, language, note}),
    cleaned, and what is wrong with them."""
    meta = meta if isinstance(meta, dict) else {}
    problems = []
    slug = str(meta.get("slug") or "")
    lo, hi = LIMITS["slug"]
    if not SLUG.match(slug) or not lo <= len(slug) <= hi:
        problems.append(f"The short name should be {lo} to {hi} lowercase letters, numbers or single dashes.")
    elif slug in set(reserved):
        problems.append(f'"{slug}" is kept for the app. Pick another short name.')
    name = one_line(meta.get("name"))
    if not name:
        problems.append("It needs a name.")
    elif len(name) > LIMITS["name"]:
        problems.append(f"The name is too long ({len(name)} of {LIMITS['name']} characters).")
    tagline = one_line(meta.get("tagline"))
    if len(tagline) > LIMITS["tagline"]:
        problems.append(f"The tagline is too long ({len(tagline)} of {LIMITS['tagline']} characters).")
    description = normalize_text(meta.get("description"))
    if len(description) > LIMITS["description"]:
        problems.append(f"The description is too long ({len(description)} of {LIMITS['description']} characters).")
    if description.count("\n") + 1 > LIMITS["description_lines"]:
        problems.append(f"The description has too many lines (at most {LIMITS['description_lines']}).")
    author = one_line(meta.get("author"))
    alo, ahi = LIMITS["author"]
    if not alo <= len(author) <= ahi:
        problems.append(f"The author name should be {alo} to {ahi} characters.")
    elif "@" in author:
        problems.append("The author name can't have an @ in it.")
    raw_tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    clean_tags = []
    for t in raw_tags:
        t = one_line(t).lower()
        if t and t not in clean_tags:
            clean_tags.append(t)
    if len(clean_tags) > LIMITS["tags"]:
        problems.append(f"At most {LIMITS['tags']} tags.")
    unknown = [t for t in clean_tags if tags and t not in tags]
    if unknown:
        problems.append(f"Not a tag here: {', '.join(unknown[:3])}.")
    color = str(meta.get("color") or "")
    if color and not COLOR.match(color):
        problems.append("The colour isn't a colour.")
    language = str(meta.get("language") or "")
    if language and not LANG.match(language):
        problems.append("The language isn't a language code.")
    note = one_line(meta.get("note"))
    if len(note) > LIMITS["note"]:
        problems.append(f"The version note is too long ({len(note)} of {LIMITS['note']} characters).")
    if not isinstance(meta.get("adult", False), bool):
        problems.append("The 18+ switch should be on or off.")
    findings = scan({"name": name, "tagline": tagline, "description": description, "author": author, "note": note})
    problems += scan_problems(findings, {"name": "The name", "tagline": "The tagline",
                                         "description": "The description", "author": "The author name",
                                         "note": "The version note"})
    clean = {"slug": slug, "name": name, "tagline": tagline, "description": description, "tags": clean_tags[:LIMITS["tags"]],
             "color": color.lower() if COLOR.match(color) else "", "author": author, "adult": bool(meta.get("adult")),
             "language": language if LANG.match(language) else "", "note": note}
    return clean, problems


def check_text(text) -> tuple:
    """The persona's text, cleaned, and what is wrong with it."""
    t = normalize_text(text)
    problems = []
    lo, hi = LIMITS["text"]
    if len(t) < lo:
        problems.append(f"The text is too short ({len(t)} of at least {lo} characters). Say more about who it is.")
    if len(t) > hi:
        problems.append(f"The text is too long ({len(t)} of {hi} characters).")
    if words(t) < LIMITS["text_words"]:
        problems.append(f"The text needs at least {LIMITS['text_words']} words.")
    if t.count("\n") + 1 > LIMITS["text_lines"]:
        problems.append(f"The text has too many lines (at most {LIMITS['text_lines']}).")
    blank = _PLACEHOLDER.search(t)
    if blank:
        problems.append(f"The text still has a blank to fill in: {blank.group(0)[:40]}")
    problems += scan_problems(scan({"text": t}))
    return t, problems


# ── Settings ─────────────────────────────────────────────────────────────────
# Exact keys, never a prefix: a setting added to the app later is not shared until it is added here on purpose.
# Each one says who it is or how it talks. Never models, costs, limits, pace, accounts or anything an account does
# on its own.

COMMON_WORDS = frozenset({
    "hi", "hey", "hello", "yo", "the", "and", "you", "me", "lol", "ok", "okay", "yes", "no", "bot", "ai", "what",
    "why", "how", "who", "bro", "sis", "guys", "girl", "boy", "man", "dude", "babe", "baby", "love", "everyone",
    "all", "here", "there", "omg", "wtf", "haha",
})


def _bool(v):
    return (v, "") if isinstance(v, bool) else (None, "should be on or off")


def _int(lo, hi):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not v.is_integer()):
            return None, "should be a whole number"
        v = int(v)
        return (v, "") if lo <= v <= hi else (None, f"should be from {lo} to {hi}")
    return check


def _num(lo, hi, none=False):
    def check(v):
        if v is None and none:
            return None, ""
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None, "should be a number"
        v = float(v)
        return (round(v, 4), "") if lo <= v <= hi else (None, f"should be from {lo} to {hi}")
    return check


def _choice(*options):
    def check(v):
        return (v, "") if isinstance(v, str) and v in options else (None, "should be one of " + ", ".join(options))
    return check


def _text(lo, hi, pattern=None):
    def check(v):
        if not isinstance(v, str):
            return None, "should be text"
        t = normalize_text(v)
        if not lo <= len(t) <= hi:
            return None, f"should be {lo} to {hi} characters" if lo else f"should be at most {hi} characters"
        if pattern and not re.match(pattern, t):
            return None, "isn't in the right form"
        return t, ""
    return check


def _list(item, lo, hi):
    def check(v):
        if not isinstance(v, list):
            return None, "should be a list"
        if not lo <= len(v) <= hi:
            return None, f"should have {lo} to {hi} entries" if lo else f"should have at most {hi} entries"
        out = []
        for x in v:
            x, why = item(x)
            if why:
                return None, f"has an entry that {why}"
            out.append(x)
        return out, ""
    return check


def _table(key_pattern, value, lo, hi):
    def check(v):
        if not isinstance(v, dict):
            return None, "should be a table"
        if not lo <= len(v) <= hi:
            return None, f"should have {lo} to {hi} entries"
        out = {}
        for k, x in v.items():
            if not isinstance(k, str) or not re.match(key_pattern, k):
                return None, f"has a name that isn't allowed ({str(k)[:24]})"
            x, why = value(x)
            if why:
                return None, f"has an entry that {why}"
            out[k] = x
        return out, ""
    return check


def _trigger(v):
    if not isinstance(v, str):
        return None, "should be text"
    names = [one_line(n) for n in v.split(",") if one_line(n)]
    if not 1 <= len(names) <= 6:
        return None, "should be 1 to 6 names, separated by commas"
    for n in names:
        if not 2 <= len(n) <= 24 or not re.match(r"^[\w' -]+$", n):
            return None, "should be names of 2 to 24 letters"
        if n.lower() in COMMON_WORDS:
            return None, f'can\'t answer to a common word ("{n}")'
    return ", ".join(names), ""


def _emoji(v):
    if not isinstance(v, str) or not 1 <= len(v) <= 16 or re.search(r"[A-Za-z0-9\s]", v):
        return None, "isn't a single emoji"
    return v, ""


ALLOWED = {
    "bot.trigger": _trigger,
    "bot.default_language": _text(2, 12, LANG.pattern),
    "bot.message_style.mode": _choice("short", "balanced", "chatty"),
    "bot.message_style.max_chunk_chars": _int(120, 1200),
    "bot.typo_chance": _num(0, 0.15),
    "bot.mood.enabled": _bool,
    "bot.mood.shift_interval_min": _int(300, 86400),
    "bot.mood.shift_interval_max": _int(300, 86400),
    "bot.mood.moods": _table(r"^[a-z][a-z0-9_]{0,23}$", _text(1, 400), 1, 12),
    "bot.reactions.enabled": _bool,
    "bot.reactions.chance": _num(0, 0.6),
    "bot.reactions.react_only_max_ratio": _num(0, 0.5),
    "bot.reactions.emojis": _list(_emoji, 1, 60),
    "bot.late_reply.enabled": _bool,
    "bot.late_reply.threshold": _int(30, 86400),
    "bot.late_reply.style": _text(0, 300),
    "bot.late_reply.openers": _table(LANG.pattern, _list(_text(1, 120), 1, 20), 1, 8),
    "bot.refusal.fallbacks": _list(_text(1, 60), 1, 12),
    "bot.refusal.extra_phrases": _list(_text(2, 120), 0, 40),
    "bot.sampling.temperature": _num(0, 1.6, none=True),
    "bot.sampling.top_p": _num(0.05, 1, none=True),
    "bot.sampling.frequency_penalty": _num(-2, 2, none=True),
    "bot.sampling.presence_penalty": _num(-2, 2, none=True),
    "bot.tts.voice": _text(2, 24, r"^[a-z][a-z0-9_-]{1,23}$"),
    "bot.tts.tones": _list(_text(3, 20, r"^\[[a-z][a-z ]{1,18}\]$"), 0, 4),
    "tiktok.live.tone": _choice("persona", "hype", "chill", "funny", "sweet"),
    "tiktok.live.topic": _text(0, 200),
    "tiktok.live.language": _choice("viewer", "persona"),
    "tiktok.live.max_words": _int(4, 40),
    "tiktok.live.use_names": _bool,
    "tiktok.live.emoji": _bool,
}

# Kept out on purpose, said by area in the share form so nobody wonders where the rest went.
NEVER = [
    ("Models, providers and anything that costs", ("bot.groq", "bot.local", "bot.max_reply_tokens", "bot.tts.enabled",
                                                    "bot.videos", "bot.pictures", "bot.memory_summary", "bot.models")),
    ("How fast and how often it sends", ("bot.typing", "bot.read_delay", "bot.realistic_typing", "bot.batch",
                                         "bot.server_batch", "bot.global_cooldown", "bot.ignore_chance",
                                         "bot.edit_after_send", "bot.stale_reply", "bot.trigger_bypasses",
                                         "bot.mention_bypasses")),
    ("Things it does on its own", ("bot.nudge", "bot.friend_requests", "bot.status", "bot.night_invisible")),
    ("Where it answers", ("bot.allow_", "bot.hold_conversation", "bot.reply_ping", "bot.disable_mentions",
                          "bot.read_bios", "bot.anti_age_ban", "bot.prefix", "bot.priority_prefix")),
    ("How your accounts look to the apps", ("bot.timezone", "bot.locale", "bot.client_profile", "bot.desktop")),
    ("Discord, Snapchat and TikTok", ("discord.", "snapchat.", "tiktok.")),
    ("Yours alone", ("bot.owner_id", "notifications.", "services.", "bot.refusal.enabled",
                     "bot.refusal.replace_phrases")),
]


def never_reason(key: str) -> str:
    for why, prefixes in NEVER:
        if any(key == p.rstrip(".") or key.startswith(p) for p in prefixes):
            return why
    return "Not something a profile can share"


def text_values(settings: dict) -> dict:
    """The words inside the shared settings, for scan(): {"settings:<key>": text}."""
    out = {}
    for key, value in (settings or {}).items():
        parts = []
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts += [x for x in value if isinstance(x, str)]
        elif isinstance(value, dict):
            for x in value.values():
                if isinstance(x, str):
                    parts.append(x)
                elif isinstance(x, list):
                    parts += [y for y in x if isinstance(y, str)]
        if parts:
            out[f"settings:{key}"] = "\n".join(parts)
    return out


def check_settings(settings) -> tuple:
    """The shared settings ({dotted key: value}, tables whole), cleaned, and what is wrong with them. A key that may
    not be shared is a problem, not quietly dropped: the person sending should know."""
    settings = settings if isinstance(settings, dict) else {}
    clean, problems = {}, []
    if len(settings) > LIMITS["settings"]:
        problems.append(f"Too many settings ({len(settings)} of {LIMITS['settings']}).")
    for key, value in settings.items():
        check = ALLOWED.get(str(key))
        if not check:
            problems.append(f"{key} can't be shared ({never_reason(str(key)).lower()}).")
            continue
        v, why = check(value)
        if why:
            problems.append(f"{key} {why}.")
            continue
        clean[str(key)] = v
    lo, hi = clean.get("bot.mood.shift_interval_min"), clean.get("bot.mood.shift_interval_max")
    if lo is not None and hi is not None and lo > hi:
        problems.append("The mood's shortest change is longer than its longest.")
    problems += scan_problems(scan(text_values(clean)))
    return dict(sorted(clean.items())), problems


# ── Pictures ─────────────────────────────────────────────────────────────────

def _pillow():
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 40_000_000
    return Image, ImageOps


def reencode_image(data: bytes, *, side: int, square: bool = False, quality: int = 86,
                   formats=("JPEG", "PNG", "WEBP")) -> bytes:
    """A picture made again from its pixels alone, as a JPEG: no EXIF, no GPS, nothing hidden after it. `square`
    crops a little above the middle, where a face is, as the app's own faces are. Raises ValueError, plainly."""
    Image, ImageOps = _pillow()
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in formats:
                raise ValueError("It isn't a JPEG, PNG or WEBP picture.")
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            if min(w, h) < 64:
                raise ValueError("The picture is too small (at least 64 pixels a side).")
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                flat = Image.new("RGB", im.size, (255, 255, 255))
                flat.paste(im, mask=im.split()[-1])
                im = flat
            else:
                im = im.convert("RGB")
            if square:
                s = min(w, h)
                left = (w - s) // 2
                top = max(0, min(h - s, int((h - s) * 0.3)))
                im = im.crop((left, top, left + s, top + s)).resize((side, side), Image.LANCZOS)
            else:
                im.thumbnail((side, side), Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, "JPEG", quality=quality, optimize=True)
            return out.getvalue()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("The picture couldn't be read.") from e


def check_avatar(data: bytes) -> tuple:
    """(the face as kept: 256 px, JPEG, nothing hidden; problems)."""
    try:
        return reencode_image(data, side=LIMITS["avatar_side"], square=True, quality=88), []
    except ValueError as e:
        return b"", [f"The face: {e}"]


# ── Media in a request ───────────────────────────────────────────────────────

def check_media(media) -> list:
    """What is wrong with a request's media list (where it is and what it holds; the files are checked when read)."""
    if not media:
        return []
    if not isinstance(media, dict):
        return ["The pictures and videos list is broken."]
    problems = []
    if not GIST.match(str(media.get("gist") or "")):
        problems.append("The pictures and videos aren't where they should be.")
    if not REVISION.match(str(media.get("revision") or "")):
        problems.append("The pictures and videos have no fixed version.")
    files = media.get("files") if isinstance(media.get("files"), list) else []
    pictures = [f for f in files if isinstance(f, dict) and f.get("kind") == "picture"]
    videos = [f for f in files if isinstance(f, dict) and f.get("kind") == "video"]
    if len(pictures) + len(videos) != len(files):
        problems.append("Something in the pictures and videos is neither.")
    if len(pictures) > LIMITS["pictures"]:
        problems.append(f"Too many pictures ({len(pictures)} of {LIMITS['pictures']}).")
    if len(videos) > LIMITS["videos"]:
        problems.append(f"Too many videos ({len(videos)} of {LIMITS['videos']}).")
    names = set()
    total = 0
    for f in pictures + videos:
        m = MEDIA_NAME.match(str(f.get("name") or ""))
        ext = "jpg" if f.get("kind") == "picture" else "mp4"
        if not m or m.group(2) != ext or f["name"] in names:
            problems.append("A picture or video has a name that isn't allowed.")
            continue
        names.add(f["name"])
        size = f.get("bytes")
        cap = LIMITS["picture_bytes"] if ext == "jpg" else LIMITS["video_bytes"]
        if not isinstance(size, int) or not 0 < size <= cap:
            problems.append(f"{f['name']} is too big (at most {cap // 1_000_000} MB).")
        else:
            total += size
        if not re.match(r"^[0-9a-f]{64}$", str(f.get("sha256") or "")):
            problems.append(f"{f['name']} has no checksum.")
        if ext == "mp4":
            secs = f.get("seconds")
            if not isinstance(secs, (int, float)) or isinstance(secs, bool) or not 0 < secs <= LIMITS["video_seconds"]:
                problems.append(f"{f['name']} is longer than {int(LIMITS['video_seconds'])} seconds.")
    if total > LIMITS["package_bytes"]:
        problems.append(f"The pictures and videos are too big together (at most {LIMITS['package_bytes'] // 1_000_000} MB).")
    return problems


def split_parts(data: bytes, chars: int | None = None) -> list:
    """A file as base64 text in parts, for the gist (one file there can't be very big)."""
    text = base64.b64encode(data).decode("ascii")
    step = chars or LIMITS["part_chars"]
    return [text[i:i + step] for i in range(0, len(text), step)] or [""]


def part_name(name: str, n: int) -> str:
    return f"{name}.part{n:03d}"


def join_parts(parts: dict, name: str) -> bytes:
    """A file put back together from its parts ({part name: text}). Raises ValueError when one is missing."""
    found = sorted((k for k in parts if re.match(re.escape(name) + r"\.part\d{3}$", k)), key=lambda k: int(k[-3:]))
    if not found or [int(k[-3:]) for k in found] != list(range(len(found))):
        raise ValueError(f"{name} is missing a part.")
    try:
        return base64.b64decode("".join(parts[k].strip() for k in found), validate=True)
    except Exception as e:
        raise ValueError(f"{name} is damaged.") from e


# ── Files ────────────────────────────────────────────────────────────────────

CORE = ("profile.json", "persona.txt", "settings.json", "avatar.jpg")
_CAPS = {"profile.json": 8_000, "persona.txt": 96_000, "settings.json": 64_000, "avatar.jpg": 200_000}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj) -> bytes:
    """JSON as it is kept and hashed: keys sorted, two-space indent, a newline at the end."""
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def build_zip(files: dict) -> bytes:
    """A zip that is the same bytes for the same files: fixed dates and order, text deflated, pictures stored."""
    order = [n for n in CORE if n in files] + sorted(n for n in files if n not in CORE)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in order:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            if name.endswith((".json", ".txt")):
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, files[name], compresslevel=9)
            else:
                info.compress_type = zipfile.ZIP_STORED
                z.writestr(info, files[name])
    return out.getvalue()


def read_zip(data: bytes, *, media: bool = False, limit: int | None = None) -> dict:
    """The files of a profile's zip, read strictly: only the names a profile has, each within its size, no
    encryption, nothing but stored or deflated, and the real sizes checked as they are read. Raises ValueError."""
    limit = limit or (LIMITS["package_bytes"] + 1_000_000 if media else 512_000)
    if len(data) > limit:
        raise ValueError("The file is too big.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("It isn't a profile file.") from e
    out = {}
    total = 0
    with z:
        infos = z.infolist()
        if len(infos) > len(CORE) + LIMITS["pictures"] + LIMITS["videos"]:
            raise ValueError("The file holds too much.")
        for info in infos:
            name = info.filename
            m = re.match(r"^media/(m\d{2}\.(?:jpg|mp4))$", name)
            if name in out or not (name in CORE or (media and m)):
                raise ValueError(f"The file holds something a profile can't ({name[:40]}).")
            if info.flag_bits & 0x1:
                raise ValueError("The file is locked.")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("The file is packed in a way that isn't allowed.")
            cap = _CAPS.get(name) or (LIMITS["video_bytes"] if name.endswith(".mp4") else LIMITS["picture_bytes"])
            with z.open(info) as f:
                blob = f.read(cap + 1)
            if len(blob) > cap:
                raise ValueError(f"{name} is too big.")
            total += len(blob)
            if total > LIMITS["package_bytes"] + 1_000_000:
                raise ValueError("The file holds too much.")
            out[name] = blob
    for need in ("profile.json", "persona.txt"):
        if need not in out:
            raise ValueError(f"The file has no {need}.")
    return out


# ── Requests and statuses, inside an issue ───────────────────────────────────

_REQUEST = re.compile(r"<!--\s*llmselfbot:request\s+(\{.*?\})\s*-->", re.S)
_PACKAGE = re.compile(r"<!--\s*llmselfbot:package\s*\n([A-Za-z0-9+/=\n]*?)\n?-->", re.S)
_STATUS = re.compile(r"<!--\s*llmselfbot:status\s+(\{.*?\})\s*-->", re.S)


def _marker_json(obj) -> str:
    # Nothing in it can end the comment it sits in.
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")


def render_request(request: dict, core: bytes, summary: str) -> str:
    """The body of a request issue: what it asks, a short summary people can read, and the core zip."""
    b64 = base64.b64encode(core).decode("ascii")
    lines = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))
    body = (f"<!-- llmselfbot:request {_marker_json(request)} -->\n{summary.strip()}\n\n"
            f"<!-- llmselfbot:package\n{lines}\n-->\n")
    return body


def parse_request(body: str) -> tuple:
    """(request, core zip bytes) from an issue body. Raises ValueError, plainly."""
    body = str(body or "").replace("\r\n", "\n")
    m = _REQUEST.search(body)
    if not m:
        raise ValueError("This isn't a request from the app.")
    try:
        request = json.loads(m.group(1))
    except ValueError as e:
        raise ValueError("The request is damaged.") from e
    if not isinstance(request, dict) or request.get("v") != 1:
        raise ValueError("The request is from a version of the app this repo doesn't know.")
    if request.get("action") not in ("publish", "update", "remove"):
        raise ValueError("The request doesn't say what to do.")
    if request["action"] == "remove":
        return request, b""
    p = _PACKAGE.search(body)
    if not p:
        raise ValueError("The request has no profile in it.")
    try:
        core = base64.b64decode(p.group(1).replace("\n", ""), validate=True)
    except Exception as e:
        raise ValueError("The profile in the request is damaged.") from e
    if len(core) > LIMITS["core_bytes"]:
        raise ValueError("The profile in the request is too big.")
    if request.get("sha256") != sha256(core):
        raise ValueError("The profile in the request doesn't match its checksum.")
    return request, core


def render_status(status: dict, text: str) -> str:
    return f"<!-- llmselfbot:status {_marker_json(status)} -->\n{text.strip()}\n"


def parse_status(body: str) -> dict | None:
    m = _STATUS.search(str(body or ""))
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def fence(text: str, lang: str = "text") -> str:
    """Untrusted text shown as text in Markdown: a fence longer than any run of backticks inside it."""
    longest = max((len(r) for r in re.findall(r"`+", text or "")), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{text}\n{ticks}"


def md_inline(text: str, limit: int = 120) -> str:
    """Untrusted text inline in Markdown, inert: no mentions, links, tables or formatting."""
    t = one_line(text, limit)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>@~])", r"\\\1", t)


# ── Who sent it, kept private ────────────────────────────────────────────────

def owner_key(secret: str, user_id) -> str:
    """The author of a profile as the public data keeps them: a keyed hash of their GitHub account number, so the
    repo can tell an author's own update from anyone else's while never naming the account."""
    return hmac.new(str(secret).encode("utf-8"), str(int(user_id)).encode("ascii"), hashlib.sha256).hexdigest()[:32]
