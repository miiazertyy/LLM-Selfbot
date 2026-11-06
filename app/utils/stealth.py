"""Careful mode, and the small tweaks that keep automated accounts from looking automated.

Modern platforms decide "bot" in layers - IP reputation, the TLS fingerprint of the client, header
consistency, browser fingerprinting, and behavioural patterns on top (fixed intervals, bursts, new
accounts doing too much too fast). The browser platforms already present a real Chrome with a real
fingerprint and persistent cookies, so the remaining layers are the behavioural ones, and that is what
this module owns:

  conservative()    is careful mode on right now, and by how much
  jitter()          a fixed interval, made a human one (±12%, per call)
  tone_down_env()   a browser runner's environment, paced down the same way
  quiet()           whether public actions (likes, comments, posts, follows) should stay off
  report()          the rows the System page's "Under the radar" section shows

Careful mode is for new or precious accounts: replies at a fraction of the pace, every wait stretched,
and nothing public at all - no likes, comments, posts, follows, statuses, notes, friend requests or
voice calls - until the date in `until` passes (empty: until it is switched off).
"""
import random
from datetime import datetime

DEFAULTS = {"enabled": False, "until": "", "reply_scale": 0.4, "wait_scale": 1.5}

#: The tail of a runner's env keys that carry a public action. In careful mode each is forced off.
_QUIET_KEYS = (
    "ACCEPT_MESSAGE_REQUESTS", "ACCEPT_FOLLOW_REQUESTS", "ACCEPT_CHAT_INVITES", "AUTO_ADD_FRIENDS",
    "COMMENT", "MENTION", "INBOX", "LIKE_", "UPVOTE_", "REPOST_", "FOLLOW_", "JOIN_SUBS", "SAVE",
    "NOTES", "VISITS", "FORYOU", "REELS", "POSTING", "POSTS_PER_DAY", "STATUS_POST", "STORIES_POST",
    "STORY_POST", "LIVE", "VOICE_NOTES", "FOLLOW_HOST",
)


def conservative(cfg: dict = None) -> dict:
    """What careful mode asks for right now: {"on", "reply_scale", "wait_scale", "until"}. `until` is
    checked against today, so a mode set to expire has switched itself off the morning after."""
    if cfg is None:
        from app.utils.helpers import load_config
        try:
            cfg = load_config() or {}
        except Exception:
            cfg = {}
    block = (cfg.get("bot") or {}).get("conservative") or {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in block.items() if v is not None})
    on = bool(out.get("enabled"))
    until = str(out.get("until") or "").strip()
    if on and until:
        try:
            if datetime.now() > datetime.strptime(until, "%Y-%m-%d"):
                on = False
        except ValueError:
            pass        # a date it cannot read is not a date that has passed
    out["on"] = on
    out["until"] = until if on else ""
    try:
        out["reply_scale"] = max(0.05, min(1.0, float(out["reply_scale"])))
        out["wait_scale"] = max(1.0, min(4.0, float(out["wait_scale"])))
    except (TypeError, ValueError):
        out["reply_scale"], out["wait_scale"] = DEFAULTS["reply_scale"], DEFAULTS["wait_scale"]
    return out


def quiet(cfg: dict = None) -> bool:
    """Whether anything public should stay off: careful mode is on. The one place every platform's
    public actions (and Discord's voice) check before going out."""
    return conservative(cfg)["on"]


def jitter(ms: int, pct: float = 12.0) -> int:
    """A fixed interval, made a human one: ±pct around the value, never under half a second. Called once
    per process, so each session's polls land differently and never lock-step with another account's."""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        ms = 5000
    return max(500, int(ms * (1 + random.uniform(-pct / 100.0, pct / 100.0))))


def tone_down_env(env: dict, cfg: dict = None) -> dict:
    """A browser runner's environment, paced like a person. Always: the poll and reload intervals get
    jittered per session. In careful mode: sends-per-hour scaled down, send gaps stretched, and every
    public-action flag forced off. Only touches the keys already present, so nothing is invented."""
    careful = conservative(cfg)
    for key in list(env):
        upper = str(key).upper()
        try:
            value = int(env[key])
        except (TypeError, ValueError):
            value = None
        if upper.endswith(("_POLL_INTERVAL_MS", "_RELOAD_INTERVAL_MS")):
            if value is not None:
                env[key] = str(jitter(value))
            continue
        if not careful["on"]:
            continue
        if upper.endswith("_MAX_SENDS_PER_HOUR"):
            if value is not None:
                env[key] = str(max(1, int(value * careful["reply_scale"])))
        elif upper.endswith(("_MIN_SEND_GAP_MS", "_MAX_SEND_GAP_MS", "_VERIFY_WAIT_MS")):
            if value is not None:
                env[key] = str(max(1000, int(value * careful["wait_scale"])))
        elif any(frag in upper for frag in _QUIET_KEYS):
            env[key] = "false"
    return env


def pace(ms: int, cfg: dict = None) -> int:
    """One wait, as careful mode wants it: stretched, then jittered. For the platforms whose pacing lives
    in Python rather than the runner's environment (Telegram's governor)."""
    careful = conservative(cfg)
    out = int(ms)
    if careful["on"]:
        out = max(1000, int(out * careful["wait_scale"]))
    return jitter(out)


def rate(n: int, cfg: dict = None) -> int:
    """One count-per-hour, as careful mode allows it: scaled down, floored at one."""
    careful = conservative(cfg)
    out = int(n)
    if careful["on"]:
        out = max(1, int(out * careful["reply_scale"]))
    return out


#: The socials that run a browser, by the name a person writes.
_BROWSER_NAMES = {"snapchat": "Snapchat", "tiktok": "TikTok", "instagram": "Instagram", "x": "X", "reddit": "Reddit"}


def report(cfg: dict = None) -> list:
    """The rows the System page's health checks show: what is set, whether it is the careful thing, what that
    means (`why`), and where to change it (`where`: Settings subtabs, as "tab/sub", which the panel names and links).
    A social switched off in Settings isn't mentioned, as it is shown nowhere."""
    from app.utils import socials
    careful = conservative(cfg)
    if cfg is None:
        from app.utils.helpers import load_config
        try:
            cfg = load_config() or {}
        except Exception:
            cfg = {}
    bot = cfg.get("bot") or {}
    rows = []

    def row(platform, name, ok, detail, where=(), why=""):
        rows.append({"platform": platform, "name": name, "ok": bool(ok), "detail": detail, "where": list(where), "why": why})

    browsers = [s for s in _BROWSER_NAMES if socials.shown(s, cfg)]

    row("all", "Careful mode", careful["on"],
        ("on until " + careful["until"]) if careful["on"] and careful["until"] else
        ("on, until switched off" if careful["on"] else "off - new accounts are safer with it on"),
        ["ai/careful"], "Slower, quieter, and nothing public.")
    if careful["on"]:
        row("all", "Pace", True,
            f"{int(careful['reply_scale'] * 100)}% of replies, waits \u00d7{careful['wait_scale']:g}")

    headless = [s for s in browsers if (cfg.get(s) or {}).get("headless") is True]
    row("all", "Hidden browser windows", not headless,
        ("off everywhere" if not headless else "on for " + ", ".join(_BROWSER_NAMES[s] for s in headless)),
        [f"{s}/browser" for s in headless], "Sites spot a browser with no window more easily.")

    public = []
    for section in browsers:
        block = cfg.get(section) or {}
        # Any engage/comment/posting/notes/visits block with its `enabled` or first action on.
        for part in ("engage", "comments", "posting", "notes", "visits", "foryou", "mentions", "inbox", "live"):
            b = block.get(part) or {}
            if b.get("enabled") or any(v is True for k, v in b.items() if k in ("like_sent", "comment_sent",
                                       "like_theirs", "comment_theirs", "upvote_sent", "repost_sent", "follow_back")):
                public.append(f"{section}/{part}")
    if careful["on"]:
        public = []
    row("all", "Public actions", not public,
        ("all off" if not public else "1 is on" if len(public) == 1 else f"{len(public)} are on"),
        public, "What it does in public by itself. Platforms watch these the most.")

    calls = bot.get("calls") or {}
    voice_on = bool(calls.get("enabled") and calls.get("vc"))
    row("discord", "Voice channels", not (voice_on and not careful["on"]),
        ("off (careful mode)" if careful["on"] and voice_on else
         ("off" if not voice_on else "on - the most visible thing it does")), ["calls/voice"])

    return rows
