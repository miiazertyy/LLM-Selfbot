"""Pure, testable human-behaviour helpers: typing cadence, reaction tags, the night window, and style-aware chunking, all plain functions so tests can pin the exact ranges."""

import random
import re
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback, dev only
    ZoneInfo = None

# ── Typing cadence ────────────────────────────────────────────────────────────

# Humans: mobile ~36 WPM / desktop composition ~19-40 WPM, i.e. roughly 1.6-3.3 chars/sec for slow typists, up to ~6-8 for fast ones on desktop. The old 7-18 range was superhuman (up to 180 WPM).
TYPING_CPS_MIN, TYPING_CPS_MAX = 2.5, 6.0
TYPING_CPS_FAST_MIN, TYPING_CPS_FAST_MAX = 4.0, 8.0


# The longest anyone plausibly spends composing one message before sending it. A "chatty" chunk is 800 characters, which at the slow end of the range works out at over five minutes of continuous typing for a single message, and four of those in a row for one reply.
MAX_TYPING_SECONDS = 45.0

# Everything above, as the defaults for Settings > AI behaviour > Typing. A word is five characters, the usual measure, so 30-72 WPM is exactly the 2.5-6 chars/sec range.
TYPING_DEFAULTS = {"wpm_min": 30, "wpm_max": 72, "max_seconds": MAX_TYPING_SECONDS,
                   "think_min": 2.0, "think_max": 8.0, "pause_chance": 0.35}


def typing_settings() -> dict:
    """The typing settings, each one clamped to something that still reads as a person. Read on every message: load_config() is mtime-cached, and it means a change in the panel shows on the very next reply."""
    try:
        from app.utils.helpers import load_config
        raw = ((load_config().get("bot") or {}).get("typing")) or {}
    except Exception:
        raw = {}

    def num(key, lo, hi):
        try:
            v = float(raw.get(key, TYPING_DEFAULTS[key]))
        except (TypeError, ValueError):
            v = float(TYPING_DEFAULTS[key])
        return max(lo, min(hi, v))

    wmin, wmax = num("wpm_min", 5, 300), num("wpm_max", 5, 300)
    tmin, tmax = num("think_min", 0, 120), num("think_max", 0, 120)
    return {"wpm_min": min(wmin, wmax), "wpm_max": max(wmin, wmax),
            "max_seconds": num("max_seconds", 1, 600),
            "think_min": min(tmin, tmax), "think_max": max(tmin, tmax),
            "pause_chance": num("pause_chance", 0, 1)}


def typing_speed(fast: bool = False) -> float:
    """One typing speed in chars/sec for this message. The fast range (quick replies to a mention or a trigger) keeps its old proportion to the normal one: 4-8 against 2.5-6."""
    t = typing_settings()
    lo, hi = t["wpm_min"] * 5 / 60, t["wpm_max"] * 5 / 60
    if fast:
        lo, hi = lo * (TYPING_CPS_FAST_MIN / TYPING_CPS_MIN), hi * (TYPING_CPS_FAST_MAX / TYPING_CPS_MAX)
    return random.uniform(lo, hi)


def typing_time(text: str, fast: bool = False) -> float:
    """How long to spend typing this message, capped at something believable."""
    return min(typing_settings()["max_seconds"], len(text or "") / typing_speed(fast))


def pick_wait(wait_times) -> int:
    """One batch wait, in seconds, from a list of {time, weight}, picked by weight. A row with a "to" past its time is a range: the wait is then any whole second from time to to, so it never lands on exactly the same number twice in a row the way a fixed one does."""
    rows = [r for r in (wait_times or []) if isinstance(r, dict) and r.get("time") is not None]
    if not rows:
        return 0
    chosen = random.choices(rows, weights=[max(0, r.get("weight") or 0) for r in rows] if any(r.get("weight") for r in rows) else None, k=1)[0]
    low, high = chosen["time"], chosen.get("to")
    if isinstance(high, (int, float)) and high > low:
        return round(random.uniform(low, high))
    return low


def think_delay() -> float:
    """The pause between reading a message and starting to type the reply."""
    t = typing_settings()
    return random.uniform(t["think_min"], t["think_max"])


def typing_bursts(total_seconds: float, fast: bool = False) -> list:
    """Split a typing session into (type_seconds, pause_seconds) segments. Humans don't type a long message in one run: they type, stop to think, delete, retype. Each type burst lasts 2-6s and ~35% of the time it is followed by a 1.2-3.5s pause (the typing indicator stays up the whole time, Discord only clears it after ~10s of silence or on send)."""
    bursts = []
    remaining = total_seconds
    burst_max = 5.0 if fast else 6.0
    chance = typing_settings()["pause_chance"]
    pause_chance = chance * (0.20 / 0.35) if fast else chance
    while remaining > 0.01:
        burst = min(remaining, random.uniform(2.0, burst_max))
        remaining -= burst
        pause = 0.0
        if remaining > 2.5 and random.random() < pause_chance:
            pause = random.uniform(1.2, 3.5)
        bursts.append((burst, pause))
    return bursts


# ── Reactions ─────────────────────────────────────────────────────────────────

# Deliberately not anchored to the end of the string. The prompt asks the model to end its reply with the tag, and it does, but it thinks of a reply as several messages and puts the tag at the end of the FIRST one ("haha guess i'm just naturally fun 😂 you in school? [[REACT:😂]]"), so with an end anchor the tag was sent as literal text.
# One or two closing brackets, because the model sometimes writes only one
# ("[[REACT:😂]"); the whole thing has to come out either way.
_REACT_RE = re.compile(r"\[\[REACT(_ONLY)?:([^\]\n]{1,40}?)\]{1,2}")
# A trailing tag with no closing bracket at all, e.g. "...talking 😭 [[REACT:" or
# "[[REACT:😂" at the very end. Only at the end, so text after a stray "[[" mid
# message is never eaten. This is exactly how "[[REACT:" once went out as words.
_REACT_TAIL_RE = re.compile(r"\[\[REACT(?:_ONLY)?:?[^\]\n]{0,40}$")

# The emoji this character reacts with, as a starting point. A list rather than a set because the order is the order they are offered to the model, and a set reshuffles itself between runs, which made the prompt differ every launch for no reason. It is only a default now: the real list is edited on the Persona page, because which emoji someone uses is a big part of how they come across, and a fixed set made every persona react identically.
DEFAULT_REACTION_EMOJI = [
    "😂", "🤣", "😭", "💀", "😅", "😆", "😊", "🥹", "😍", "😳",
    "🤔", "👍", "❤️", "🔥", "🙏", "😎", "🥲", "😢", "😤", "🫡",
    "🙂", "🫠", "🤝", "👀", "🙄", "😴", "🤷", "🫶", "😐", "🥰",
]

# The old name, kept because it is the spelling in released builds.
REACTION_EMOJI = set(DEFAULT_REACTION_EMOJI)

# Long enough for any character, short enough that the list does not eat the prompt. Thirty of these is already about sixty tokens on every single reply.
MAX_REACTION_EMOJI = 40


def clean_emoji_list(raw, fallback=None) -> list:
    """Tidy whatever came out of the config into a usable list. Hand edited YAML and a text box both produce the same mess: blank entries, duplicates, stray spaces, and the occasional whole sentence. Anything unusable is dropped rather than rejected, because a typo in one entry must not take reactions out altogether. An empty result falls back to the default set: turning reactions off is what the switch is for, an empty list here would silently do the same thing while the switch still said they were on."""
    if isinstance(raw, str):
        # A text box, or someone who wrote them on one line in the YAML.
        items = raw.replace(",", " ").split()
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = []

    out = []
    for item in items:
        entry = str(item).strip()
        # No length limit would let a pasted sentence become a "reaction" that Discord rejects on every use. Emoji are a handful of code points even with a skin tone and a variation selector.
        if not entry or len(entry) > 8:
            continue
        if entry not in out:
            out.append(entry)
        if len(out) >= MAX_REACTION_EMOJI:
            break
    return out or list(fallback if fallback is not None else DEFAULT_REACTION_EMOJI)


def reaction_emojis(reactions_cfg=None) -> list:
    """The emoji in use, from the bot.reactions config block."""
    cfg = reactions_cfg or {}
    return clean_emoji_list(cfg.get("emojis"))


def parse_reaction_tag(text: str, allowed=None):
    """Remove every [[REACT:emoji]] / [[REACT_ONLY:emoji]] tag from a reply. Returns (clean_text, emoji, react_only). `allowed` is the character's own emoji list: stripping never depends on it, only the choice of what to react with does, because a tag must come out of the text whatever it holds, or it gets sent as words. Every tag is removed wherever it sits, since the one thing that must never happen is the tag being sent as text, and only the first one with an allowlisted emoji is acted on (Discord rejects reactions it does not know). The hole the tag leaves is closed up too, otherwise stripping mid-line leaves a double space or a whitespace-only line, which is the sort of small wrongness that reads as a bot."""
    if not text:
        return text, None, False
    if "[[REACT" not in text:
        return text, None, False

    allowset = set(allowed) if allowed else REACTION_EMOJI
    found = {"emoji": None, "only": False}

    def take(m):
        if found["emoji"] is None:
            candidate = m.group(2).strip()
            if candidate in allowset:
                found["emoji"] = candidate
                found["only"] = bool(m.group(1))
        return ""

    cleaned = _REACT_RE.sub(take, text)
    # A cut-off tag at the very end that the pair-bracket form did not catch.
    if found["emoji"] is None:
        tail = _REACT_TAIL_RE.search(cleaned)
        if tail:
            candidate = tail.group(0).split(":", 1)[-1].strip()
            if candidate in allowset:
                found["emoji"] = candidate
                found["only"] = "REACT_ONLY" in tail.group(0).upper()
    cleaned = _REACT_TAIL_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+(\n|$)", r"\1", cleaned)
    return cleaned.strip(), found["emoji"], found["only"]


def tiny_typo_fix(text: str) -> str:
    """One small human edit, as if fixing a slip right after sending: drop a stray final period, swap two adjacent letters, or uncapitalise a word mid-message. Never touches numbers or anything that looks like a URL."""
    if not text or len(text) < 6:
        return text
    choice = random.choice(("period", "swap", "case"))
    if choice == "period" and text.rstrip().endswith("."):
        return text.rstrip().rstrip(".")
    words = text.split()
    if choice == "case":
        # Only words that actually start with a capital can be "fixed" this way; otherwise the edit would be a no-op.
        candidates = [
            i for i, w in enumerate(words)
            if 4 <= len(w) <= 30 and w[0].isupper() and not re.search(r"[\d:/@_]", w)
        ]
        if candidates:
            idx = random.choice(candidates)
            words[idx] = words[idx][0].lower() + words[idx][1:]
            return " ".join(words)
        choice = "swap"
    candidates = [
        i for i, w in enumerate(words)
        if 4 <= len(w) <= 30 and not re.search(r"[\d:/@_]", w)
    ]
    if not candidates:
        return text
    idx = random.choice(candidates)
    word = words[idx]
    j = random.randint(1, len(word) - 2)
    words[idx] = word[:j] + word[j + 1] + word[j] + word[j + 2:]
    return " ".join(words)


# ── Night window (invisible while "sleeping") ────────────────────────────────

def _parse_hours(spec: str):
    """Parse "2-8" or "23-7" into (start_hour, end_hour). None when invalid."""
    try:
        start_s, end_s = str(spec).split("-", 1)
        start, end = int(start_s.strip()), int(end_s.strip())
        if not (0 <= start <= 23 and 0 <= end <= 23):
            return None
        return start, end
    except (ValueError, AttributeError):
        return None


def _local_time(now: datetime, tz_name: str) -> datetime:
    """`now` as the persona would read it off their own clock."""
    if ZoneInfo is None or not tz_name:
        return now
    try:
        return now.astimezone(ZoneInfo(tz_name))
    except Exception:
        return now


def _local_hour(now: datetime, tz_name: str) -> int:
    return _local_time(now, tz_name).hour


def night_window_state(cfg: dict, now: datetime = None) -> tuple:
    """Night schedule state: (is_night, seconds_until_next_transition). cfg is the bot.night_invisible mapping with enabled, hours ("2-8") and timezone; hours are LOCAL to the persona timezone and support wrap-around ("23-7")."""
    enabled = bool(cfg.get("enabled")) if isinstance(cfg, dict) else False
    hours = _parse_hours(cfg.get("hours", "")) if isinstance(cfg, dict) else None
    if not enabled or hours is None:
        return False, None
    tz = cfg.get("timezone", "") if isinstance(cfg, dict) else ""
    now = now or datetime.now().astimezone()
    start, end = hours
    if start == end:
        return False, None
    cur = _local_hour(now, tz)
    wraps = start > end
    is_night = (cur >= start or cur < end) if wraps else (start <= cur < end)

    # Seconds until the next boundary, counted from the current minute rather than the current hour. Rounding to the hour meant that at 07:59, with the window ending at 08:00, the answer was a full hour: the account stayed invisible until nearly nine.
    local = _local_time(now, tz)
    next_hour = end if is_night else start
    hours_away = (next_hour - cur) % 24
    if hours_away == 0:
        hours_away = 24
    seconds = hours_away * 3600 - (local.minute * 60 + local.second)
    # Never return zero or a negative: the caller sleeps on this value.
    return is_night, max(60, int(seconds))


# ── Style-aware chunking ──────────────────────────────────────────────────────

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def style_chunk_split(text: str, max_chars: int) -> list:
    """Split text into pieces of at most max_chars, preferring sentence ends. Hard-splits a single over-long sentence (no words lost), and never returns empty strings."""
    if not text:
        return []
    max_chars = max(20, int(max_chars))
    pieces = []
    buffer = ""
    for part in _SENTENCE_SPLIT_RE.split(text):
        while len(part) > max_chars:
            if buffer:
                pieces.append(buffer.rstrip())
                buffer = ""
            pieces.append(part[:max_chars].rstrip())
            part = part[max_chars:].lstrip()
        if not buffer:
            buffer = part
        elif len(buffer) + 1 + len(part) <= max_chars:
            buffer += " " + part
        else:
            pieces.append(buffer.rstrip())
            buffer = part
    if buffer:
        pieces.append(buffer.rstrip())
    return [p for p in pieces if p]
