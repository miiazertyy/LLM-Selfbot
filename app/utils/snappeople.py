"""app/utils/snappeople.py - who each Snapchat chat is, for the panel.

The Snapchat runner reads every chat's name and picture (a Bitmoji or a photo)
off the chat list as it goes through it, and saves the picture under
cache/snap_people, with contacts_<account>.json saying which is whose. The
Chats tab, the account cards and the stats show those, the way they show a
Discord account's people from its profile cache. Nothing here asks Snapchat.
"""

import json
import re

from app.utils.paths import DATA_DIR

PEOPLE_DIR = DATA_DIR / "cache" / "snap_people"
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_cache: dict = {}


def contacts(account: int) -> dict:
    """{chat id: {"name", "file", "url", "seen"}} for one account, re-read only when the runner has written it."""
    path = PEOPLE_DIR / f"contacts_{int(account)}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    hit = _cache.get(account)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    _cache[account] = (mtime, data)
    return data


def picture_path(account: int, chat_id: str):
    """The saved picture of one chat, or None. Only ever a file the runner named for that chat."""
    chat_id = str(chat_id)
    if not _ID.fullmatch(chat_id):
        return None
    name = (contacts(account).get(chat_id) or {}).get("file") or ""
    if not re.fullmatch(rf"{int(account)}_{re.escape(chat_id)}\.(png|jpg|webp)", name):
        return None
    path = PEOPLE_DIR / name
    return path if path.is_file() else None


def avatar_url(account: int, chat_id: str) -> str:
    """Where the panel loads a chat's picture from, "" when there is none. Changes when the picture does."""
    path = picture_path(account, chat_id)
    if not path:
        return ""
    return f"/api/chats/snap-picture/{int(account)}/{chat_id}?v={int(path.stat().st_mtime)}"


def name_of(account: int, chat_id: str) -> str:
    return str((contacts(account).get(str(chat_id)) or {}).get("name") or "")


def _accounts() -> list:
    """Every Snapchat account whose runner has written its chat list."""
    out = []
    for path in PEOPLE_DIR.glob("contacts_*.json"):
        n = path.stem.split("_", 1)[1]
        if n.isdigit():
            out.append(int(n))
    return sorted(out) or [1]


def describe(uids) -> dict:
    """Snapchat people by chat id, for the pages that show a person (Memory, a name's card, the ignored list): their
    name and picture, from the runners' chat lists or else the message log, which remembers people Snapchat no
    longer lists; and how much they have written. Discord ids (all digits) are left out."""
    import time as _time
    ids = sorted({str(u) for u in uids if u and not str(u).isdigit()})
    if not ids:
        return {}
    out = {i: {"name": "", "avatar": "", "messages": 0, "messages_7d": 0, "first_seen": 0, "last_seen": 0,
               "platform": "snapchat"} for i in ids}
    for n in _accounts():
        for i in ids:
            out[i]["name"] = out[i]["name"] or name_of(n, i)
            out[i]["avatar"] = out[i]["avatar"] or avatar_url(n, i)
    try:
        from app.utils.db import connect_raw
        conn = connect_raw()
        try:
            week = _time.time() - 7 * 86400
            for start in range(0, len(ids), 400):
                part = ids[start:start + 400]
                marks = ",".join("?" * len(part))
                for cid, n, first, last, recent in conn.execute(
                        f"SELECT chat_id, COUNT(*), MIN(ts), MAX(ts), SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END) "
                        f"FROM message_log_snap WHERE chat_id IN ({marks}) GROUP BY chat_id", (week, *part)):
                    out[str(cid)].update(messages=n or 0, first_seen=first or 0, last_seen=last or 0,
                                         messages_7d=recent or 0)
                for cid, uname in conn.execute(
                        f"SELECT chat_id, username FROM user_stats_snap WHERE chat_id IN ({marks})", part):
                    if uname and str(cid) in out:
                        out[str(cid)]["name"] = out[str(cid)]["name"] or uname
        finally:
            conn.close()
    except Exception:
        pass
    return out
