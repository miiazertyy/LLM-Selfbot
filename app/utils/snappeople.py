"""app/utils/snappeople.py - who each browser platform's chat is, for the panel.

The Snapchat runner reads every chat's name and picture (a Bitmoji or a photo)
off the chat list as it goes through it, and saves the picture under
cache/snap_people, with contacts_<account>.json saying which is whose. The
TikTok runner does the same under cache/tiktok_people, and the Instagram one
under cache/instagram_people. The Chats tab, the account cards and the stats
show those, the way they show a Discord account's people from its profile
cache. Nothing here asks Snapchat, TikTok or Instagram.

Which platform a person is on is read off their id (platform_of_user): Discord
ids are all digits, TikTok's start with "tt_" and Instagram's with "ig_" (the
username, dots as dashes), and anything else is a Snapchat chat id.
"""

import json
import re

from app.platforms import registry
from app.utils.paths import DATA_DIR

PEOPLE_DIR = DATA_DIR / "cache" / "snap_people"
TIKTOK_PEOPLE_DIR = DATA_DIR / "cache" / "tiktok_people"
INSTAGRAM_PEOPLE_DIR = DATA_DIR / "cache" / "instagram_people"
MINECRAFT_PEOPLE_DIR = DATA_DIR / "cache" / "minecraft_people"
IMESSAGE_PEOPLE_DIR = DATA_DIR / "cache" / "imessage_people"
TELEGRAM_PEOPLE_DIR = DATA_DIR / "cache" / "telegram_people"
X_PEOPLE_DIR = DATA_DIR / "cache" / "x_people"
REDDIT_PEOPLE_DIR = DATA_DIR / "cache" / "reddit_people"
WHATSAPP_PEOPLE_DIR = DATA_DIR / "cache" / "whatsapp_people"
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_cache: dict = {}
# A browser platform's tables in the database (app/utils/db.py WEB_TABLES).
_TABLES = registry.TABLES
# The platforms whose people are named by a username, each with the prefix its ids carry.
_HANDLED = registry.HANDLED


def platform_of_user(uid) -> str:
    """"discord", "tiktok", "instagram", "x", "reddit", "minecraft" or "snapchat", for a person's id. An
    Instagram group is "igg_" and its thread's number: the same platform, with no one username behind it. A
    Minecraft server's own events (deaths, joins) are "mcs_" and the server's address, the same way."""
    u = str(uid or "")
    if u.isdigit():
        return "discord"
    if u.startswith("igg_"):
        return "instagram"
    if u.startswith("mcs_"):
        return "minecraft"
    # X: a person by their @handle ("x_"), a group message by its conversation's number ("xg_"). An underscore is
    # legal in a handle, so "x_g_tom" is a person and only "xg_" without one is a group.
    if u.startswith("xg_"):
        return "x"
    # Reddit the same way: a person by their username ("rd_"), a group chat by its room ("rdg_"). An underscore is
    # legal in a username too, so "rd_g_tom" is a person.
    if u.startswith("rdg_"):
        return "reddit"
    # WhatsApp the same way: a person by their number ("wa_"), a group by its own id ("wag_").
    if u.startswith("wag_"):
        return "whatsapp"
    # iMessage: a person by their phone number or email ("im_"), a group by its chat's number ("img_").
    if u.startswith(("im_", "img_")):
        return "imessage"
    # Telegram: a person by their id ("tg_"), a group or channel by its chat's ("tgg_").
    if u.startswith(("tg_", "tgg_")):
        return "telegram"
    for platform, prefix in _HANDLED.items():
        if u.startswith(prefix):
            return platform
    return "snapchat"


def tiktok_id(handle: str) -> str:
    """A TikTok person's id from their @handle: "theo.wav" is "tt_theo-wav". Handles are letters, digits,
    underscores and dots, never dashes, so it reads back exactly (tiktok_handle), and it is a safe file name."""
    h = str(handle or "").strip().lstrip("@").lower()
    return "tt_" + re.sub(r"[^a-z0-9_]", "-", h)


def tiktok_handle(uid: str) -> str:
    u = str(uid or "")
    return u[3:].replace("-", ".") if u.startswith("tt_") else ""


def instagram_id(username: str) -> str:
    """An Instagram person's id from their username: "theo.wav" is "ig_theo-wav", as TikTok's "tt_" ids are."""
    u = str(username or "").strip().lstrip("@").lower()
    return "ig_" + re.sub(r"[^a-z0-9_]", "-", u)


def instagram_username(uid: str) -> str:
    u = str(uid or "")
    return u[3:].replace("-", ".") if u.startswith("ig_") else ""


def minecraft_id(name: str) -> str:
    """A Minecraft player's id from their name: "Steve_99" is "mc_steve_99". Minecraft names are letters, digits and
    underscores only, so nothing needs changing beyond the case; anything else is not a name and gives ""."""
    n = str(name or "").strip().lower()
    return "mc_" + n if re.fullmatch(r"[a-z0-9_]{3,16}", n) else ""


def minecraft_username(uid: str) -> str:
    u = str(uid or "")
    return u[3:] if u.startswith("mc_") else ""


def x_id(handle: str) -> str:
    """An X person's id from their @handle: "Theo_Wav" is "x_theo_wav". X handles are letters, digits and
    underscores only, so nothing needs changing beyond the case; anything else is not a handle and gives ""."""
    h = str(handle or "").strip().lstrip("@").lower()
    return "x_" + h if re.fullmatch(r"[a-z0-9_]{1,15}", h) else ""


def x_handle(uid: str) -> str:
    u = str(uid or "")
    return u[2:] if u.startswith("x_") else ""


def reddit_id(name: str) -> str:
    """A Reddit person's id from their username: "Theo-Wav" is "rd_theo-wav". Reddit allows a hyphen where X does
    not, so the hyphen is kept as it is and nothing is read back out of it."""
    h = str(name or "").strip().lstrip("@").removeprefix("u/").lower()
    return "rd_" + h if re.fullmatch(r"[a-z0-9_-]{3,20}", h) else ""


def reddit_user(uid: str) -> str:
    u = str(uid or "")
    return u[3:] if u.startswith("rd_") else ""


def whatsapp_id(number: str) -> str:
    """A WhatsApp person's id from their number: "+44 7700 900123" is "wa_447700900123". WhatsApp's own ids are
    the number with nothing in it but digits, which is what its JIDs carry."""
    n = re.sub(r"\D", "", str(number or ""))
    return "wa_" + n if 5 <= len(n) <= 20 else ""


def whatsapp_number(uid: str) -> str:
    u = str(uid or "")
    return u[3:] if u.startswith("wa_") else ""


def handle_of(uid: str) -> str:
    """The username behind a person's id, whichever platform names its people that way; "" for the others."""
    u = str(uid or "")
    if u.startswith("x_"):
        # Two letters, not three, and no dashes to read back: an X handle may hold an underscore of its own.
        return u[2:]
    if u.startswith("rd_"):
        # A dash is a real character in a Reddit username, so this one is never read back as a dot.
        return u[3:]
    if u.startswith("wa_"):
        # A number, so there is nothing in it to read back as anything else.
        return u[3:]
    return u[3:].replace("-", ".") if u.startswith(("tt_", "ig_", "mc_")) else ""


def imessage_person_id(address: str) -> str:
    """An iMessage person's id from their number, email, or contact name (bluebubbles.js personId, the same rule):
    "+33 6 12 34 56 78" is "im_p33612345678", anything else written character by character, too long a one hashed."""
    a = str(address or "").strip().lower()
    if not a:
        return ""
    phone = re.sub(r"[\s().-]", "", a)
    if re.fullmatch(r"\+?\d{3,20}", phone):
        return f"im_{'p' if phone.startswith('+') else ''}{phone.replace('+', '')}"
    out = "".join(ch if re.fullmatch(r"[a-z0-9]", ch) else f"_{ord(ch):x}_" for ch in a)
    pid = f"im_{out}"
    if len(pid) <= 80:
        return pid
    import hashlib
    return f"im_h{hashlib.sha1(a.encode('utf-8')).hexdigest()[:24]}"


def remember(account: int, chat_id: str, fields: dict, platform: str = "imessage") -> None:
    """Who a chat is, kept where a runner keeps it (contacts_<account>.json), for an account with no runner to keep
    it: iMessage through the iPhone, which only ever says a sender's name or number."""
    import time
    from app.utils.atomic import write_json_atomic
    path = _dir(platform) / f"contacts_{int(account)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data[str(chat_id)] = {**(data.get(str(chat_id)) or {}), **fields, "seen": time.time()}
    write_json_atomic(path, data)


def imessage_address(uid: str) -> str:
    """The phone number or email an iMessage person's id was made from (bluebubbles.js personId): "im_p33612345678"
    is "+33612345678", an email's every other character written as _<its code>_. "" for a group's, or a hashed one."""
    u = str(uid or "")
    if not u.startswith("im_") or re.fullmatch(r"im_h[0-9a-f]{24}", u):
        return ""
    rest = u[3:]
    if re.fullmatch(r"p\d{3,20}", rest):
        return "+" + rest[1:]
    if re.fullmatch(r"\d{3,20}", rest):
        return rest
    try:
        return re.sub(r"_([0-9a-f]{1,6})_", lambda m: chr(int(m.group(1), 16)), rest)
    except (ValueError, OverflowError):
        return ""


def _dir(platform: str):
    if platform == "tiktok":
        return TIKTOK_PEOPLE_DIR
    if platform == "instagram":
        return INSTAGRAM_PEOPLE_DIR
    if platform == "minecraft":
        return MINECRAFT_PEOPLE_DIR
    if platform == "imessage":
        return IMESSAGE_PEOPLE_DIR
    if platform == "telegram":
        return TELEGRAM_PEOPLE_DIR
    if platform == "x":
        return X_PEOPLE_DIR
    if platform == "reddit":
        return REDDIT_PEOPLE_DIR
    if platform == "whatsapp":
        return WHATSAPP_PEOPLE_DIR
    return PEOPLE_DIR


def contacts(account: int, platform: str = "snapchat") -> dict:
    """{chat id: {"name", "file", "url", "seen"}} for one account, re-read only when the runner has written it."""
    path = _dir(platform) / f"contacts_{int(account)}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    key = (platform, account)
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    _cache[key] = (mtime, data)
    return data


def picture_path(account: int, chat_id: str, platform: str = "snapchat"):
    """The saved picture of one chat, or None. Only ever a file the runner named for that chat."""
    chat_id = str(chat_id)
    if not _ID.fullmatch(chat_id):
        return None
    name = (contacts(account, platform).get(chat_id) or {}).get("file") or ""
    if not re.fullmatch(rf"{int(account)}_{re.escape(chat_id)}\.(png|jpg|webp)", name):
        return None
    path = _dir(platform) / name
    return path if path.is_file() else None


def avatar_url(account: int, chat_id: str, platform: str = "snapchat") -> str:
    """Where the panel loads a chat's picture from, "" when there is none. Changes when the picture does."""
    path = picture_path(account, chat_id, platform)
    if not path:
        return ""
    v = int(path.stat().st_mtime)
    if platform in registry.BRIDGED_BUT_SNAPCHAT:
        return f"/api/chats/web-picture/{platform}/{int(account)}/{chat_id}?v={v}"
    return f"/api/chats/snap-picture/{int(account)}/{chat_id}?v={v}"


def name_of(account: int, chat_id: str, platform: str = "snapchat") -> str:
    return str((contacts(account, platform).get(str(chat_id)) or {}).get("name") or "")


def _accounts(platform: str = "snapchat") -> list:
    """Every account of the platform whose runner has written its chat list."""
    out = []
    for path in _dir(platform).glob("contacts_*.json"):
        n = path.stem.split("_", 1)[1]
        if n.isdigit():
            out.append(int(n))
    return sorted(out) or [1]


def describe(uids) -> dict:
    """Snapchat, TikTok and Instagram people by chat id, for the pages that show a person (Memory, a name's card,
    the ignored list): their name and picture, from the runners' chat lists or else the message log, which remembers
    people the platform no longer lists; and how much they have written. Discord ids (all digits) are left out."""
    import time as _time
    ids = sorted({str(u) for u in uids if u and not str(u).isdigit()})
    if not ids:
        return {}
    out = {i: {"name": "", "avatar": "", "messages": 0, "messages_7d": 0, "first_seen": 0, "last_seen": 0,
               "platform": platform_of_user(i)} for i in ids}
    for platform in registry.BRIDGED:
        mine = [i for i in ids if out[i]["platform"] == platform]
        if not mine:
            continue
        for n in _accounts(platform):
            for i in mine:
                out[i]["name"] = out[i]["name"] or name_of(n, i, platform)
                out[i]["avatar"] = out[i]["avatar"] or avatar_url(n, i, platform)
        t = _TABLES[platform]
        try:
            from app.utils.db import connect_raw
            conn = connect_raw()
            try:
                week = _time.time() - 7 * 86400
                for start in range(0, len(mine), 400):
                    part = mine[start:start + 400]
                    marks = ",".join("?" * len(part))
                    for cid, n, first, last, recent in conn.execute(
                            f"SELECT chat_id, COUNT(*), MIN(ts), MAX(ts), SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END) "
                            f"FROM message_log_{t} WHERE chat_id IN ({marks}) GROUP BY chat_id", (week, *part)):
                        out[str(cid)].update(messages=n or 0, first_seen=first or 0, last_seen=last or 0,
                                             messages_7d=recent or 0)
                    for cid, uname in conn.execute(
                            f"SELECT chat_id, username FROM user_stats_{t} WHERE chat_id IN ({marks})", part):
                        if uname and str(cid) in out:
                            out[str(cid)]["name"] = out[str(cid)]["name"] or uname
            finally:
                conn.close()
        except Exception:
            pass
        if platform == "imessage":
            for i in mine:
                # Nobody's name yet: their number or email, which is what Messages shows too.
                address = imessage_address(i)
                out[i]["name"] = out[i]["name"] or address or ("a group" if i.startswith("img_") else i)
                if address:
                    out[i]["address"] = address
        if platform in _HANDLED:
            for i in mine:
                # Nobody's name yet: their username, which is what the site shows too.
                out[i]["name"] = out[i]["name"] or ("@" + handle_of(i))
                # Their username, to find or copy, and what their profile says about them (its bio, its followers),
                # as the runner read it the first time it met them.
                out[i]["username"] = handle_of(i)
                for n in _accounts(platform):
                    c = contacts(n, platform).get(i) or {}
                    if c.get("bio") and not out[i].get("bio"):
                        out[i]["bio"] = str(c["bio"])[:400]
                    if c.get("followers") is not None and out[i].get("followers") is None:
                        out[i]["followers"] = int(c.get("followers") or 0)
                    if c.get("verified"):
                        out[i]["verified"] = True
                    # Their latest posts, as the runner last read their profile (<platform>.watch.their_posts).
                    if c.get("posts") and not out[i].get("posts"):
                        out[i]["posts"] = [
                            {"url": str(p.get("url") or ""), "caption": str(p.get("caption") or "")[:200],
                             "views": str(p.get("views") or "")[:12],
                             "cover": str(p.get("cover") or "") if str(p.get("cover") or "").startswith("https://") else ""}
                            for p in c["posts"][:3] if isinstance(p, dict) and str(p.get("url") or "").startswith("https://")]
    return out
