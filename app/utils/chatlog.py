"""app/utils/chatlog.py - every DM message an account has seen, kept.

The Chats tab used to read a conversation from Discord each time it was
opened, so reopening one cost another history fetch (on an hourly allowance),
a message someone deleted simply vanished, and after a restart the bot
answered someone's latest message with no idea what had been said before it.

Now the runner writes each DM message here as it sees it: the ones that come
in, its own replies, the ones read back from history. A conversation opened
again in the same session is read from here, not from Discord. A message
deleted on Discord is kept and marked, so the tab can show it with a bin. An
edit updates the text. And the first reply to someone after a restart starts
from what is here (seed_turns), rather than from a blank page.

Pictures in DMs are kept too (cache_dir), because Discord's links to them are
signed and stop working after a day or so, and go at once when the message is
deleted: the tab would show a broken image exactly where it matters.

In the same database as everything else (app/utils/db.py), so a backup
carries it. Each conversation keeps its newest KEEP messages.

It is also what the Chats tab searches, as you type: one conversation (any
case, accents ignored, from whom, with what, between when), or every
conversation at once; what was shared in one (pictures and videos, files,
links); and the messages around one, to jump to it. Deleted messages are
found too, which Discord's own search cannot do.
"""

import json
import re
import time
import unicodedata

from app.utils.db import connect_raw
from app.utils.paths import DATA_DIR

KEEP = 500
CACHE_DIR = DATA_DIR / "cache" / "chat_media"
_ready = False
# Snapchat accounts keep their conversations here too, as account 1000 + their number: one log, one search.
SNAP_BASE = 1000


def log_account(target) -> int:
    """The account a target's conversations are kept under: a Discord account by its number ("1" or 1), a
    Snapchat one ("snap", "snap2") by SNAP_BASE + its number."""
    if isinstance(target, str) and target.startswith("snap"):
        n = target[4:]
        return SNAP_BASE + (int(n) if n.isdigit() else 1)
    return int(target)


def _conn():
    global _ready
    conn = connect_raw()
    if not _ready:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_log (
                account INTEGER NOT NULL,
                uid     TEXT    NOT NULL,
                mid     TEXT    NOT NULL,
                mine    INTEGER NOT NULL,
                ts      REAL    NOT NULL,
                body    TEXT    NOT NULL,
                deleted REAL,
                edited  REAL,
                PRIMARY KEY (account, mid)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS chat_log_conv ON chat_log (account, uid, ts)")
        conn.commit()
        _ready = True
    return conn


def _body(payload: dict) -> str:
    keep = {k: payload[k] for k in ("text", "attachments", "stickers", "embeds", "reactions", "author", "reply_to",
                                    "kind", "approx")
            if k in payload and payload[k] not in (None, "", [], {})}
    return json.dumps(keep, ensure_ascii=False, default=str)


def put(account: int, uid, mid, mine: bool, ts: float, payload: dict) -> None:
    """One message, new or seen again. Seen again, its text and pictures are updated; being deleted is never undone."""
    put_many(account, uid, [(mid, mine, ts, payload)])


def put_many(account: int, uid, rows) -> None:
    rows = [(int(account), str(uid), str(mid), 1 if mine else 0, float(ts), _body(p)) for mid, mine, ts, p in rows if mid]
    if not rows:
        return
    conn = _conn()
    try:
        conn.executemany(
            """
            INSERT INTO chat_log (account, uid, mid, mine, ts, body) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account, mid) DO UPDATE SET body = excluded.body
            """,
            rows,
        )
        conn.commit()
        _trim(conn, int(account), str(rows[0][1]))
    finally:
        conn.close()


def _trim(conn, account: int, uid: str) -> None:
    n = conn.execute("SELECT COUNT(*) FROM chat_log WHERE account = ? AND uid = ?", (account, uid)).fetchone()[0]
    if n > KEEP + 50:
        conn.execute(
            """
            DELETE FROM chat_log WHERE account = ? AND uid = ? AND mid NOT IN (
                SELECT mid FROM chat_log WHERE account = ? AND uid = ? ORDER BY ts DESC LIMIT ?)
            """,
            (account, uid, account, uid, KEEP),
        )
        conn.commit()


def mark_deleted(account: int, mid) -> str | None:
    """A message deleted on Discord: kept, and marked. Whose conversation it was, when it is one kept here."""
    conn = _conn()
    try:
        row = conn.execute("SELECT uid FROM chat_log WHERE account = ? AND mid = ?", (int(account), str(mid))).fetchone()
        if not row:
            return None
        conn.execute("UPDATE chat_log SET deleted = ? WHERE account = ? AND mid = ? AND deleted IS NULL",
                     (time.time(), int(account), str(mid)))
        conn.commit()
        return row[0]
    finally:
        conn.close()


def mark_edited(account: int, mid, payload: dict) -> str | None:
    """A message edited on Discord: the new words, and when."""
    conn = _conn()
    try:
        row = conn.execute("SELECT uid, body FROM chat_log WHERE account = ? AND mid = ?", (int(account), str(mid))).fetchone()
        if not row:
            return None
        try:
            old = json.loads(row[1])
        except ValueError:
            old = {}
        # The same words again (Discord re-sends a message as its link preview fills in) is no edit.
        if "text" in payload and (old.get("text") or "") == (payload.get("text") or ""):
            return None
        # The pictures kept here stay: an edit only brings new text.
        merged = {**old, **{k: v for k, v in payload.items() if k != "attachments" or not old.get("attachments")}}
        conn.execute("UPDATE chat_log SET body = ?, edited = ? WHERE account = ? AND mid = ?",
                     (_body(merged), time.time(), int(account), str(mid)))
        conn.commit()
        return row[0]
    finally:
        conn.close()


def apply_reaction(reactions: list, emoji: dict, delta: int, mine: bool) -> list:
    """Reactions after one is added (delta 1) or taken back (-1): `emoji` is {"name"} or a custom one's {"name", "url"},
    `mine` whether it was the account's own. Its count goes up or down, the account's own mark with it, and a reaction
    nobody has any more goes."""
    out = [dict(r) for r in reactions or [] if isinstance(r, dict)]
    key = emoji.get("url") or emoji.get("name") or ""
    hit = next((r for r in out if (r.get("url") or r.get("name") or "") == key), None)
    if hit is None:
        if delta > 0 and key:
            out.append({"name": emoji.get("name") or "", **({"url": emoji["url"]} if emoji.get("url") else {}),
                        "count": 1, "mine": bool(mine)})
        return out
    hit["count"] = max(0, int(hit.get("count") or 0) + delta)
    if mine:
        hit["mine"] = delta > 0
    return [r for r in out if r["count"] > 0]


def set_reactions(account: int, mid, reactions: list) -> str | None:
    """A kept message's reactions as they are now. Whose conversation it is, when it is kept here."""
    conn = _conn()
    try:
        row = conn.execute("SELECT uid, body FROM chat_log WHERE account = ? AND mid = ?", (int(account), str(mid))).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[1])
        except ValueError:
            data = {}
        data["reactions"] = list(reactions or [])
        conn.execute("UPDATE chat_log SET body = ? WHERE account = ? AND mid = ?", (_body(data), int(account), str(mid)))
        conn.commit()
        return row[0]
    finally:
        conn.close()


def bump_reaction(account: int, mid, emoji: dict, delta: int, mine: bool) -> tuple:
    """Someone reacted to a kept message, or took it back: (whose conversation, its reactions now), or (None, [])
    when the message is not kept here."""
    conn = _conn()
    try:
        row = conn.execute("SELECT uid, body FROM chat_log WHERE account = ? AND mid = ?", (int(account), str(mid))).fetchone()
        if not row:
            return None, []
        try:
            data = json.loads(row[1])
        except ValueError:
            data = {}
        data["reactions"] = apply_reaction(data.get("reactions") or [], emoji, delta, mine)
        conn.execute("UPDATE chat_log SET body = ? WHERE account = ? AND mid = ?", (_body(data), int(account), str(mid)))
        conn.commit()
        return row[0], data["reactions"]
    finally:
        conn.close()


def sync_reactions(account: int, seen: dict) -> list:
    """Reactions as the page shows them now, {mid: reactions}, onto the kept messages: the ones that changed, as
    (mid, reactions). How Snapchat's are kept current, read off its page with each conversation."""
    if not seen:
        return []
    conn = _conn()
    try:
        mids = [str(m) for m in seen]
        rows = conn.execute(f"SELECT mid, body FROM chat_log WHERE account = ? AND mid IN ({','.join('?' * len(mids))})",
                            [int(account), *mids]).fetchall()
        changed = []
        for mid, body in rows:
            try:
                data = json.loads(body)
            except ValueError:
                data = {}
            now = list(seen.get(mid) or [])
            if (data.get("reactions") or []) == now:
                continue
            data["reactions"] = now
            conn.execute("UPDATE chat_log SET body = ? WHERE account = ? AND mid = ?", (_body(data), int(account), mid))
            changed.append((mid, now))
        if changed:
            conn.commit()
        return changed
    finally:
        conn.close()


def missing_since(account: int, uid, lo_ts: float, hi_ts: float, present) -> list[str]:
    """Messages kept here from a stretch of the conversation that Discord no longer has: deleted while nobody was watching. Marked, and returned."""
    present = {str(m) for m in present}
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT mid FROM chat_log WHERE account = ? AND uid = ? AND ts >= ? AND ts <= ? AND deleted IS NULL",
            (int(account), str(uid), lo_ts, hi_ts),
        ).fetchall()
        gone = [r[0] for r in rows if r[0] not in present]
        if gone:
            now = time.time()
            conn.executemany("UPDATE chat_log SET deleted = ? WHERE account = ? AND mid = ?",
                             [(now, int(account), m) for m in gone])
            conn.commit()
        return gone
    finally:
        conn.close()


def conversation(account: int, uid, limit: int = 25, before_ts: float | None = None) -> list[dict]:
    """The newest `limit` messages (before `before_ts`, when given), oldest first, as the Chats tab shows them."""
    conn = _conn()
    try:
        q = "SELECT mid, mine, ts, body, deleted, edited FROM chat_log WHERE account = ? AND uid = ?"
        args: list = [int(account), str(uid)]
        if before_ts is not None:
            q += " AND ts < ?"
            args.append(before_ts)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit))
        rows = conn.execute(q, args).fetchall()
    finally:
        conn.close()
    return [_message(r) for r in reversed(rows)]


def _message(row, pictures: bool = True) -> dict:
    """A kept row as the message the Chats tab draws. pictures=False leaves its pictures on Discord's links, which
    saves looking on disk for each while searching: the ones found get theirs after."""
    mid, mine, ts, body, deleted, edited = row
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    msg = {"mid": mid, "mine": bool(mine), "ts": ts, **data}
    if pictures:
        _local_pictures(msg)
    if deleted:
        msg["deleted"] = deleted
    if edited:
        msg["edited"] = edited
    return msg


_COLS = "mid, mine, ts, body, deleted, edited"


def _rows(account: int, uid) -> list:
    """Every message kept from one conversation, newest first, as rows."""
    conn = _conn()
    try:
        return conn.execute(f"SELECT {_COLS} FROM chat_log WHERE account = ? AND uid = ? ORDER BY ts DESC",
                            (int(account), str(uid))).fetchall()
    finally:
        conn.close()


# ── Searching ────────────────────────────────────────────────────────────────

URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+", re.IGNORECASE)
_IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".heic")
_VIDEO = (".mp4", ".webm", ".mov", ".mkv", ".m4v")
_SOUND = (".ogg", ".mp3", ".wav", ".m4a", ".opus", ".flac", ".aac")
HAS = ("link", "image", "video", "file", "sound", "sticker", "embed")
_MARKS: dict | None = None


def fold(text: str) -> str:
    """Lower case, accents gone: "Café" and "cafe" are the same word to a search."""
    global _MARKS
    if not text:
        return ""
    if text.isascii():
        return text.lower()
    if _MARKS is None:
        _MARKS = {c: None for c in range(0x10000) if unicodedata.combining(chr(c))}
    return unicodedata.normalize("NFKD", text).translate(_MARKS).casefold()


def attachment_kind(a: dict) -> str:
    """"image", "video", "sound" or "file", from its type, or its name where the type is missing."""
    t = str(a.get("type") or "").lower()
    name = str(a.get("name") or a.get("url") or "").lower().split("?")[0]
    if t.startswith("image/") or name.endswith(_IMAGE):
        return "image"
    if t.startswith("video/") or name.endswith(_VIDEO):
        return "video"
    if t.startswith("audio/") or name.endswith(_SOUND):
        return "sound"
    return "file"


def kinds(msg: dict) -> set:
    """What a message has, in the words Discord's search uses (has:link, has:image ...). Any attachment is a file too,
    as on Discord."""
    out = set()
    if URL_RE.search(msg.get("text") or ""):
        out.add("link")
    for a in msg.get("attachments") or []:
        out.add(attachment_kind(a))
        out.add("file")
    if msg.get("embeds"):
        out.add("embed")
    if msg.get("stickers"):
        out.add("sticker")
    return out


def _searchable(msg: dict) -> str:
    """Everything a search looks in: the words, and the names of what came with them."""
    parts = [msg.get("text") or ""]
    parts += [str(a.get("name") or "") for a in msg.get("attachments") or []]
    parts += [str(e.get("title") or "") for e in msg.get("embeds") or []]
    parts += [str(st.get("name") or "") for st in msg.get("stickers") or []]
    return fold("\n".join(parts))


def _matches(msg: dict, words, mine, has, before, after) -> int:
    """0 when it does not match; otherwise how often the words appear, at least 1."""
    ts = msg["ts"]
    if before is not None and ts >= before:
        return 0
    if after is not None and ts < after:
        return 0
    if mine is not None and msg["mine"] != mine:
        return 0
    if has and not (set(has) & kinds(msg)):
        return 0
    if not words:
        return 1
    hay = _searchable(msg)
    if not all(w in hay for w in words):
        return 0
    return sum(hay.count(w) for w in words)


def _could_match(body: str, words) -> bool:
    """A quick look at the stored text before reading it properly: a message without every word somewhere in it is no
    match. (Words with what the stored text writes differently, a quote or a backslash, are left to the proper look.)"""
    if not words:
        return True
    hay = fold(body)
    return all(w in hay for w in words if '"' not in w and "\\" not in w)


def search(account: int, uid, words=(), mine=None, has=(), before=None, after=None,
           sort: str = "newest", limit: int = 50, offset: int = 0):
    """Messages in one conversation with every word in them (any case, accents ignored), from whom (mine: True, False
    or None for both), with any of what `has` names, between `after` and `before` (Unix seconds). Newest first, oldest
    first, or the most matches first ("relevant"). Returns (that page of them, how many there are in all)."""
    want = [fold(str(w)) for w in words if str(w).strip()]
    hits = []
    for row in _rows(account, uid):
        if not _could_match(row[3], want):
            continue
        msg = _message(row, pictures=False)
        score = _matches(msg, want, mine, has, before, after)
        if score:
            hits.append((score, msg))
    if sort == "oldest":
        hits.sort(key=lambda h: h[1]["ts"])
    elif sort == "relevant":
        hits.sort(key=lambda h: (-h[0], -h[1]["ts"]))
    page = [m for _, m in hits[offset:offset + limit]]
    for m in page:
        _local_pictures(m)
    return page, len(hits)


def search_all(account: int, words=(), mine=None, has=(), before=None, after=None, limit: int = 60) -> list:
    """The newest messages matching, across every conversation the account has, each with whose conversation it is
    (uid). For the search over the Chats list."""
    want = [fold(str(w)) for w in words if str(w).strip()]
    if not want and not has:
        return []
    conn = _conn()
    try:
        rows = conn.execute(f"SELECT uid, {_COLS} FROM chat_log WHERE account = ? ORDER BY ts DESC LIMIT 60000",
                            (int(account),)).fetchall()
    finally:
        conn.close()
    out = []
    for uid, *row in rows:
        if not _could_match(row[3], want):
            continue
        msg = _message(row, pictures=False)
        if _matches(msg, want, mine, has, before, after):
            _local_pictures(msg)
            msg["uid"] = uid
            out.append(msg)
            if len(out) >= limit:
                break
    return out


def shared(account: int, uid, kind: str, limit: int = 500) -> list:
    """What was shared in one conversation, newest first: "media" (pictures and videos), "files" (everything else
    attached, voice messages included) or "links" (the addresses in what was said, and the links Discord previewed).
    Each item says which message it came from, so the tab can jump there."""
    out = []
    for row in _rows(account, uid):
        if kind != "links" and '"attachments"' not in row[3]:
            continue
        msg = _message(row, pictures=kind == "media")
        base = {"mid": msg["mid"], "ts": msg["ts"], "mine": msg["mine"]}
        if msg.get("deleted"):
            base["deleted"] = msg["deleted"]
        if msg.get("author"):
            base["author"] = msg["author"]
        if kind == "links":
            seen = set()
            for url in URL_RE.findall(msg.get("text") or ""):
                url = url.rstrip(".,;:!?")
                if url not in seen:
                    seen.add(url)
                    out.append({**base, "url": url, "text": msg.get("text") or ""})
            for e in msg.get("embeds") or []:
                url = str(e.get("url") or "")
                if url.startswith(("http://", "https://")) and url not in seen:
                    seen.add(url)
                    out.append({**base, "url": url, "title": e.get("title") or "", "image": e.get("image") or "",
                                "text": msg.get("text") or ""})
        else:
            for a in msg.get("attachments") or []:
                k = attachment_kind(a)
                if (kind == "media") == (k in ("image", "video")):
                    out.append({**base, **a, "kind": k})
        if len(out) >= limit:
            break
    return out[:limit]


def window(account: int, uid, mid=None, direction: str = "around", n: int = 50):
    """Kept messages near one, oldest first: either side of it ("around", it included), before it ("older"), after
    it ("newer"), or the very first ones kept ("first", no mid). What jumping to a message and scrolling from there
    read when Discord cannot be asked (the account is stopped, or it is Snapchat). None when the message is not kept."""
    conn = _conn()
    try:
        where, args = "account = ? AND uid = ?", [int(account), str(uid)]
        if direction == "first":
            rows = conn.execute(f"SELECT {_COLS} FROM chat_log WHERE {where} ORDER BY ts ASC LIMIT ?", (*args, int(n))).fetchall()
            return [_message(r) for r in rows]
        row = conn.execute(f"SELECT ts FROM chat_log WHERE {where} AND mid = ?", (*args, str(mid))).fetchone()
        if not row:
            return None
        ts = row[0]
        older = newer = []
        if direction in ("around", "older"):
            take = n // 2 if direction == "around" else n
            older = conn.execute(f"SELECT {_COLS} FROM chat_log WHERE {where} AND ts < ? ORDER BY ts DESC LIMIT ?",
                                 (*args, ts, int(take))).fetchall()[::-1]
        if direction in ("around", "newer"):
            take = n - len(older) if direction == "around" else n
            newer = conn.execute(f"SELECT {_COLS} FROM chat_log WHERE {where} AND ts {'>=' if direction == 'around' else '>'} ? "
                                 f"ORDER BY ts ASC LIMIT ?", (*args, ts, int(take))).fetchall()
    finally:
        conn.close()
    return [_message(r) for r in list(older) + list(newer)]


def deleted_between(account: int, uid, lo: float, hi: float) -> list:
    """Messages kept from a stretch of a conversation that were deleted on Discord: Discord no longer returns them,
    so whatever is read from it gets these put back in."""
    conn = _conn()
    try:
        rows = conn.execute(f"SELECT {_COLS} FROM chat_log WHERE account = ? AND uid = ? AND ts >= ? AND ts <= ? "
                            f"AND deleted IS NOT NULL ORDER BY ts ASC", (int(account), str(uid), lo, hi)).fetchall()
    finally:
        conn.close()
    return [_message(r) for r in rows]


def as_text(messages: list, me: str, them: str) -> str:
    """A conversation as plain text, a line per message, for saving: when, who, what, and what came with it."""
    lines = []
    for m in messages:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["ts"]))
        who = me if m.get("mine") else ((m.get("author") or {}).get("name") or them)
        parts = [(m.get("text") or "").strip()]
        for a in m.get("attachments") or []:
            parts.append(f"[{attachment_kind(a)}: {a.get('name') or 'file'}]")
        for st in m.get("stickers") or []:
            parts.append(f"[sticker: {st.get('name') or ''}]")
        for e in m.get("embeds") or []:
            if e.get("url") and e["url"] not in parts[0]:
                parts.append(e["url"])
        notes = (" (deleted)" if m.get("deleted") else "") + (" (edited)" if m.get("edited") and not m.get("deleted") else "")
        lines.append(f"[{when}] {who}: {' '.join(p for p in parts if p)}{notes}")
    return "\n".join(lines) + ("\n" if lines else "")


def span(account: int, uid) -> tuple:
    """How many messages are kept from a conversation, and when the oldest of them was sent: how far back a search
    of what is kept reaches."""
    conn = _conn()
    try:
        n, oldest = conn.execute("SELECT COUNT(*), MIN(ts) FROM chat_log WHERE account = ? AND uid = ?",
                                 (int(account), str(uid))).fetchone()
        return n, oldest
    finally:
        conn.close()


_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp", "image/avif": "avif"}


def picture_name(mid, index: int, content_type: str) -> str | None:
    """The file a message's picture is kept in (the runner saves it under this name), or None for one that is not kept."""
    ext = _EXT.get((content_type or "").lower().split(";")[0])
    return f"{mid}_{index}.{ext}" if ext else None


def _local_pictures(msg: dict) -> None:
    """Point a kept message's pictures at the copies kept on disk, where there are some: Discord's own links expire."""
    for i, a in enumerate(msg.get("attachments") or []):
        name = picture_name(msg["mid"], i, a.get("type", ""))
        if name and (CACHE_DIR / name).is_file():
            a["remote"] = a.get("url", "")
            a["url"] = f"/api/media/chat/{name}"


def known_ts(account: int, uid, mids) -> dict:
    """The kept messages among these, each with when it was sent."""
    mids = [str(m) for m in mids if m]
    out = {}
    if not mids:
        return out
    conn = _conn()
    try:
        for i in range(0, len(mids), 400):
            part = mids[i:i + 400]
            marks = ",".join("?" * len(part))
            for mid, ts in conn.execute(f"SELECT mid, ts FROM chat_log WHERE account = ? AND uid = ? AND mid IN ({marks})",
                                        (int(account), str(uid), *part)):
                out[mid] = ts
        return out
    finally:
        conn.close()


def count(account: int, uid) -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM chat_log WHERE account = ? AND uid = ?",
                            (int(account), str(uid))).fetchone()[0]
    finally:
        conn.close()


def seed_turns(account: int, uid, before_ts: float, limit: int = 20) -> list[dict]:
    """The conversation before a message, as the model's history: their words as the user's turns, the account's as its own.

    What the first reply after a restart starts from. Deleted messages are left
    out (the person took them back), and pictures are said as "[picture]", as
    the reply path says them.
    """
    turns = []
    for m in conversation(account, uid, limit=limit, before_ts=before_ts):
        if m.get("deleted"):
            continue
        text = (m.get("text") or "").strip()
        if not text:
            if m.get("attachments"):
                text = "[picture]" if any(str(a.get("type", "")).startswith("image/") for a in m["attachments"]) else "[attachment]"
            elif m.get("stickers"):
                text = f"[sticker: {m['stickers'][0].get('name', '')}]"
        if not text:
            continue
        role = "assistant" if m["mine"] else "user"
        # Two of the same side in a row are one turn, as the model expects them.
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})
    return turns


def media_path(name: str):
    """A kept picture, by its file name, or None for anything that is not one."""
    if not re.fullmatch(r"[0-9]{1,25}_[0-9]{1,2}\.(?:png|jpg|jpeg|gif|webp|avif)", name or ""):
        return None
    path = CACHE_DIR / name
    return path if path.is_file() else None


def prune_media(max_bytes: int = 500 * 1024 * 1024) -> None:
    """The oldest kept pictures go once they take more than max_bytes."""
    try:
        files = sorted((p for p in CACHE_DIR.glob("*") if p.is_file()), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for p in files:
            if total <= max_bytes:
                break
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
    except Exception:
        pass
