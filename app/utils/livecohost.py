"""app/utils/livecohost.py - what the persona says on a TikTok LIVE, and whether it says anything.

A LIVE's chat is comments, gifts, follows, joins, shares and hearts; the persona co-hosts it with one short spoken
line at a time, typed in the chat and said out loud. Two places do this: the TikTok bridge on a real LIVE
(app/platforms/snapchat_bridge.py) and the panel's practice LIVE (Settings, TikTok, LIVE: app/web/routes/
livedemo_routes.py). Both come here, so what someone tries in the practice one is what a real one does: the same
settings, the same line, the same voice, the same pace (Pace).

The settings (tiktok.live) say:
  * whether and where it answers, and how fast: on, in the chat, out loud, so many a minute, a moment before each;
  * what it answers: comments (all, questions, or only when it is named), gifts worth so much, follows, joins,
    shares, hearts; and what it lets go: emoji-only comments, words on a list, viewers on a list, one viewer again
    too soon or too often;
  * how it comes across: its mood on the LIVE, what the LIVE is about, the language, how long a line is, names,
    emoji, the comment read out before the answer, a line of its own when the chat goes quiet;
  * how the OBS page shows its answers (app/web/routes/chat_routes.py hands those to LiveOverlay.svelte).

It also visits other people's LIVEs as a viewer (viewer_context, viewer_line): typed only, never said out loud.
"""
from __future__ import annotations

import re
import time

# What happened, said to the model; {name} and {text} are the viewer's.
SAID = {
    "comment": "{name} said in the chat: \"{text}\". Answer them.",
    "gift": "{name} just sent a gift ({text}). Thank them, warmly and briefly.",
    "follow": "{name} just followed you. Welcome them.",
    "join": "{name} just joined the LIVE. Greet them.",
    "share": "{name} shared the LIVE. Thank them.",
    "like": "{name} has been tapping hearts on your LIVE. Thank them, briefly.",
    "quiet": "The chat has gone quiet for a while. Say one short line to everyone watching to keep it going: a "
             "question for them, or what you are up to right now.",
}

# The tiktok.live settings, as config.yaml ships them.
DEFAULTS = {
    # The LIVE: on, where it answers, how fast, how a line sounds.
    "enabled": False, "chat": True, "voice": True, "per_minute": 4, "reply_delay": 2, "max_words": 15,
    "use_names": True, "language": "viewer",
    # What it answers, and what it lets go.
    "answer_comments": True, "answer_mode": "all", "thank_gifts": True, "gift_min_coins": 1,
    "welcome_follows": True, "greet_joins": False, "thank_shares": True, "thank_likes": False,
    "viewer_cooldown": 30, "max_per_viewer": 10, "skip_emoji_only": True, "blocked_words": [], "ignore_viewers": [],
    # How it comes across.
    "tone": "persona", "topic": "", "emoji": True, "read_comment": False, "fill_silence": False, "silence_seconds": 60,
    # The OBS page.
    "overlay_seconds": 8, "overlay_position": "bottom", "overlay_comment": True, "overlay_size": "medium",
    "overlay_theme": "dark",
}
RANGES = {"per_minute": (1, 30), "reply_delay": (0, 30), "max_words": (4, 40), "gift_min_coins": (1, 10000),
          "viewer_cooldown": (0, 600), "max_per_viewer": (1, 50), "silence_seconds": (15, 600),
          "overlay_seconds": (3, 30)}
CHOICES = {"language": ("viewer", "persona"), "answer_mode": ("all", "questions", "named"),
           "tone": ("persona", "hype", "chill", "funny", "sweet"), "overlay_position": ("bottom", "middle", "top"),
           "overlay_size": ("small", "medium", "large"), "overlay_theme": ("dark", "light", "tiktok")}

TONES = {
    "hype": "Bring big hype energy: excited, loud and fun, like a streamer on a roll.",
    "chill": "Keep it calm and laid back, easygoing, never loud.",
    "funny": "Be playful and joke around; a quick bit of humour in every line.",
    "sweet": "Be warm and sweet, a little bit soft with everyone.",
}

# What TikTok's commoner gifts cost, in coins, by their name in the chat: a gift is worth this times how many were
# sent. One not here counts as the cheapest.
GIFT_COINS = {
    "rose": 1, "tiktok": 1, "gg": 1, "ice cream cone": 1, "heart me": 1, "thumbs up": 1, "heart": 1, "cake slice": 1,
    "glow stick": 1, "love you": 1, "finger heart": 5, "rosa": 10, "friendship necklace": 10, "perfume": 20,
    "doughnut": 30, "paper crane": 99, "cap": 99, "hand hearts": 100, "hand heart": 100, "confetti": 100,
    "corgi": 299, "money gun": 500, "swan": 699, "train": 899, "galaxy": 1000, "fireworks": 1088,
    "whale diving": 2150, "motorcycle": 2988, "private jet": 4888, "drama queen": 5000, "unicorn fantasy": 5000,
    "rocket": 20000, "lion": 29999, "universe": 34999, "tiktok universe": 44999,
}

_QUESTION_WORDS = re.compile(
    r"^\s*(?:what|why|how|where|when|who|whose|which|can|could|do|does|did|are|is|was|will|would|should|have|has|"
    r"qui|quoi|pourquoi|comment|où|ou|quand|quel|quelle|quels|quelles|est-ce|tu peux|vous pouvez)\b", re.I)


def settings(raw: dict | None) -> dict:
    """The LIVE settings (tiktok.live), each one there and of its kind, whatever was given."""
    raw = raw if isinstance(raw, dict) else {}
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    for key, default in DEFAULTS.items():
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if isinstance(default, bool):
            out[key] = bool(value)
        elif isinstance(default, int):
            lo, hi = RANGES.get(key, (0, 10 ** 6))
            try:
                out[key] = max(lo, min(hi, int(value)))
            except (TypeError, ValueError):
                pass
        elif key in CHOICES:
            out[key] = str(value) if str(value) in CHOICES[key] else default
        elif isinstance(default, list):
            items = value if isinstance(value, list) else re.split(r"[,\n]", str(value))
            out[key] = [" ".join(str(w).split())[:60] for w in items if str(w).strip()][:200]
        else:
            out[key] = " ".join(str(value).split())[:200]
    return out


def _listed(words) -> list[str]:
    """A list setting (or a comma separated one) as its entries: lower case, no @, no blanks."""
    items = words if isinstance(words, list) else re.split(r"[,\n]", str(words or ""))
    return [str(w).strip().lstrip("@").lower() for w in items if str(w).strip().lstrip("@")]


def gift_value(text: str) -> int:
    """What a gift in the chat is worth, in coins: "Rose x5" is 5, "Galaxy" is 1000. One it does not know, 1."""
    t = re.sub(r"^\s*(?:sent|a envoyé)\s+(?:(?:an?|une?)\s+)?", "", str(text or ""), flags=re.I).strip()
    m = re.match(r"^(.*?)\s*[x×]\s*(\d{1,5})\s*$", t)
    name, count = (m.group(1), int(m.group(2))) if m else (t, 1)
    return GIFT_COINS.get(name.strip().lower(), 1) * max(1, count)


def is_question(text: str) -> bool:
    t = str(text or "").strip()
    return "?" in t or bool(_QUESTION_WORDS.match(t))


# Words a name can start with that are not a name to be called by ("The Rock" is not answered to "the").
_NOT_NAMES = {"the", "and", "you", "its", "her", "his", "not", "mrs", "miss", "official", "real", "just"}


def addressed(text: str, names) -> bool:
    """Whether a line in the chat is to the persona: its @handle, or its name (or the first word of it) as a word."""
    words = str(text or "").lower()
    for n in names or []:
        n = str(n or "").strip().lower().lstrip("@")
        first = re.split(r"[\s._-]+", n)[0] if n else ""
        for call in {n, first}:
            if len(call) >= 3 and call not in _NOT_NAMES and re.search(rf"(?<![\w.]){re.escape(call)}(?![\w])", words):
                return True
    return False


def skip_reason(kind: str, text: str, live: dict, name: str = "", handle: str = "", names=()) -> str:
    """Why this is not answered, in a few words; "" when it is (the pace aside: Pace says that). `names` are what
    the persona is called, for answering only when it is named."""
    if kind not in SAID:
        return "Nothing to answer"
    who = {str(name or "").strip().lower(), str(handle or "").strip().lower().lstrip("@")} - {""}
    if kind != "quiet" and who & set(_listed(live.get("ignore_viewers"))):
        return "They are on the never-answer list"
    if kind == "comment":
        t = str(text or "").strip()
        if not t:
            return "Nothing to answer"
        if not live.get("answer_comments", True):
            return "Answering comments is off"
        if live.get("skip_emoji_only", True) and not re.search(r"[^\W\d_]", t):
            return "Only emoji"
        low = t.lower()
        if any(w in low for w in _listed(live.get("blocked_words"))):
            return "It has a word on the list"
        mode = live.get("answer_mode", "all")
        if mode == "questions" and not (is_question(t) or addressed(t, names)):
            return "Not a question"
        if mode == "named" and not addressed(t, names):
            return "It was not named"
    elif kind == "gift":
        if not live.get("thank_gifts", True):
            return "Thanking gifts is off"
        if gift_value(text) < int(live.get("gift_min_coins", 1) or 1):
            return "A smaller gift than it thanks"
    elif kind == "follow" and not live.get("welcome_follows", True):
        return "Welcoming followers is off"
    elif kind == "join" and not live.get("greet_joins", False):
        return "Greeting people who join is off"
    elif kind == "share" and not live.get("thank_shares", True):
        return "Thanking shares is off"
    elif kind == "like" and not live.get("thank_likes", False):
        return "Thanking hearts is off"
    elif kind == "quiet" and not live.get("fill_silence", False):
        return "Talking when it is quiet is off"
    return ""


class Pace:
    """What a LIVE has said, and to whom, to keep within its settings: one line at a time, so many a minute, a viewer
    not answered again too soon nor too often. Each LIVE (the real one, the practice one) keeps its own."""

    def __init__(self):
        self.said: list = []
        self.by_viewer: dict = {}
        self.busy = False

    def why_not(self, live: dict, viewer: str = "", now: float | None = None) -> str:
        now = now or time.time()
        self.said = [t for t in self.said if now - t < 60]
        if self.busy:
            return "Still answering someone"
        if len(self.said) >= live.get("per_minute", 4):
            return f"Already {live.get('per_minute', 4)} this minute"
        times = self.by_viewer.get(viewer, []) if viewer else []
        if times and live.get("viewer_cooldown", 0) and now - times[-1] < live["viewer_cooldown"]:
            return "Answered them a moment ago"
        if viewer and len(times) >= live.get("max_per_viewer", 50):
            return "Answered them enough this LIVE"
        return ""

    def note(self, viewer: str = "", now: float | None = None) -> None:
        now = now or time.time()
        self.said.append(now)
        if viewer:
            self.by_viewer[viewer] = (self.by_viewer.get(viewer, []) + [now])[-50:]
            while len(self.by_viewer) > 2000:
                self.by_viewer.pop(next(iter(self.by_viewer)))


def context(kind: str, name: str, text: str, live: dict | None = None) -> str:
    """What the model is told this is: live, out loud, to everyone, what just happened, and how to come across."""
    live = settings(live) if live is not None else settings(None)
    out = ("LIVE: you are live on TikTok right now, co-hosting your own stream, and what you say is read out loud to "
           "everyone watching and shown in the chat. " + SAID.get(kind, SAID["comment"]).format(name=name, text=text))
    if live.get("topic"):
        out += f" This LIVE is about: {live['topic']}. Keep to it when it fits."
    if TONES.get(live.get("tone")):
        out += " " + TONES[live["tone"]]
    out += f" One short spoken line, under {live['max_words']} words"
    if kind == "quiet":
        out += "."
    elif live.get("use_names", True):
        out += ", naming them."
    else:
        out += ". Do not say their name."
    out += " No emoji-only answers." if live.get("emoji", True) else " No emoji at all."
    return out


def viewer_id(name: str, handle: str = "", prefix: str = "live_") -> str:
    """Who a viewer is to the engine: their TikTok id when the page gave their @handle, else one made from their name
    (a viewer the persona answers twice is answered as the same person)."""
    if handle:
        return "tt_" + re.sub(r"[^a-z0-9_]", "-", handle.strip().lstrip("@").lower())
    return prefix + "".join(ch for ch in (name or "").lower() if ch.isalnum())[:30]


def clean(response: str | None, max_words: int = 0) -> str:
    """The line as it is said: humanised like every other reply, its first line only, short."""
    if not response:
        return ""
    from app.utils.helpers import load_config
    from app.utils.humanize import humanize
    try:
        typo_chance = (load_config().get("bot") or {}).get("typo_chance", 0.03)
    except Exception:
        typo_chance = 0.03
    line = humanize(response, typo_chance).strip().split("\n")[0][:150].strip()
    if max_words and len(line.split()) > max_words + 6:
        # A model past the length asked for by a lot: cut at the words, as a line a person says.
        line = " ".join(line.split()[: max_words + 6]).rstrip(",;:") + "..."
    return line


def _language(live: dict) -> str:
    """The language a line is in when the persona's is wanted over the viewer's (bot.default_language)."""
    if live.get("language") != "persona":
        return ""
    try:
        from app.utils.helpers import load_config
        return str((load_config().get("bot") or {}).get("default_language") or "en")
    except Exception:
        return "en"


async def line(kind: str, name: str, text: str, *, uid: str, platform: str = "tiktok", account=None,
               channel: str = "live", live: dict | None = None) -> str:
    """The persona's line to this viewer (or, for "quiet", to everyone): written by the engine as any reply is
    (persona, mood, language), in a public stream's register, with nothing to remember or count. "" when the model
    gave nothing."""
    from app.core.engine import IncomingMessage, generate_ai_response
    from app.utils import ai
    cfg = settings(live) if live is not None else settings(None)
    # No look online: a LIVE line is said now or not at all.
    extra = {"account": account, "no_pictures": True, "no_stats": True, "no_memory": True, "no_web": True,
             "context": context(kind, name, text, cfg)}
    if _language(cfg):
        extra["language"] = _language(cfg)
    msg = IncomingMessage(
        platform=platform, user_id=uid, user_name=name or "everyone", channel_id=channel, content=text or kind,
        is_private=False, wait_time=0.0, extra=extra,
    )
    # Said now or not at all: a rate-limited model hands over to the next at once instead of the line waiting it out.
    token = ai.REALTIME.set(True)
    try:
        return clean(await generate_ai_response(msg), cfg["max_words"])
    finally:
        ai.REALTIME.reset(token)


def reading(kind: str, name: str, text: str, live: dict) -> str:
    """What is read out before the answer, when the comment is read out (tiktok.live.read_comment): "" otherwise."""
    if kind != "comment" or not live.get("read_comment") or not str(text or "").strip():
        return ""
    return f"{name} says: {str(text).strip()[:150]}"


async def voice(text: str, read_first: str = "") -> list[bytes]:
    """The line said out loud: wav chunks from the voice set up under Models (none when there is none); the comment
    first, when it is read out."""
    from app.utils.tts import generate_voice_message
    chunks = []
    if read_first:
        chunks += await generate_voice_message(read_first) or []
    return chunks + (await generate_voice_message(text) or [])


def overlay(live: dict) -> dict:
    """How the OBS page shows the answers (tiktok.live.overlay_*), for LiveOverlay.svelte."""
    return {"seconds": live["overlay_seconds"], "position": live["overlay_position"],
            "comment": live["overlay_comment"], "size": live["overlay_size"], "theme": live["overlay_theme"]}


# ── Someone else's LIVE, as a viewer ─────────────────────────────────────────
# The persona visits a LIVE (tiktok.visits): a hello when it arrives, an answer when someone in the chat talks to it,
# and now and then a line of its own. It is a viewer there, never the host.

VISIT_SAID = {
    "arrive": "You just came into @{host}'s LIVE. Say a short hello in the chat, as viewers do when they arrive.",
    "named": "{name} said to you in the chat: \"{text}\". Answer them.",
    "chat": "{name} said in the chat: \"{text}\". Add one short line to the chat, about the stream or what is said.",
}


def viewer_context(host: str, kind: str, name: str, text: str, recent: list | None = None) -> str:
    """What the model is told when it writes a line in someone else's LIVE."""
    out = (f"LIVE: you are watching @{host}'s TikTok LIVE as a viewer, and what you type goes in its public chat, where "
           "the streamer and everyone watching read it. ")
    lines = [str(r) for r in (recent or []) if str(r).strip()][-6:]
    if lines:
        out += "The chat just now: " + " | ".join(lines) + ". "
    out += VISIT_SAID.get(kind, VISIT_SAID["chat"]).format(host=host, name=name, text=text)
    return out + " One short chat line, under 12 words, casual, no hashtags. You are a viewer, never the streamer."


async def viewer_line(host: str, kind: str, name: str, text: str, recent: list | None = None, *, uid: str,
                      platform: str = "tiktok", account=None) -> str:
    """The persona's line in someone's LIVE: written by the engine, now or not at all, remembered nowhere."""
    from app.core.engine import IncomingMessage, generate_ai_response
    from app.utils import ai
    msg = IncomingMessage(
        platform=platform, user_id=uid, user_name=name or host, channel_id=f"visit_{host}",
        content=text or f"(@{host}'s LIVE)", is_private=False, wait_time=0.0,
        extra={"account": account, "no_pictures": True, "no_stats": True, "no_memory": True, "no_web": True,
               "context": viewer_context(host, kind, name, text, recent)},
    )
    token = ai.REALTIME.set(True)
    try:
        return clean(await generate_ai_response(msg))
    finally:
        ai.REALTIME.reset(token)
