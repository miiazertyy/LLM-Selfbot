import sqlite3
from contextlib import contextmanager

from app.utils.helpers import resource_path

db_path = "config/bot_data.db"

_pragmas_applied = False


def connect_raw() -> sqlite3.Connection:
    """A connection with the pragmas this database needs, for callers that want to run several queries without reopening between each one. journal_mode is persistent in the file, but busy_timeout and synchronous are per-connection, so they have to be set every time: routes that used bare sqlite3.connect() got neither, which meant they raised "database is locked" immediately instead of waiting whenever a bot runner happened to be writing."""
    conn = sqlite3.connect(resource_path(db_path), timeout=15)
    global _pragmas_applied
    if not _pragmas_applied:
        conn.execute("PRAGMA journal_mode=WAL")
        _pragmas_applied = True
    conn.execute("PRAGMA busy_timeout=15000")
    # WAL already guarantees durability across process crashes; FULL adds an fsync per commit to also survive a power cut, which is not a trade worth making for a chat log written on every message.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def _connect():
    """Open the shared DB with WAL + a busy timeout, always closing on exit. WAL lets the Discord runner, Snapchat bridge and Telegram controller read and write concurrently instead of tripping over "database is locked"."""
    conn = connect_raw()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ignored_users (
                id INTEGER PRIMARY KEY
            )
        """
        )

        # Snapchat chat ids are UUID strings, they can't live in an INTEGER PRIMARY KEY column, so Snapchat keeps its own ignore table with a TEXT key.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ignored_users_snap (
                id TEXT PRIMARY KEY
            )
        """
        )

        # Each persona's pictures, memory and summaries are its own (app/utils/personas.py): the persona is part of
        # each key. A database from before that is given the column by migrate_personas, below.
        cursor.execute(_PERSONA_TABLES["pictures"].format(t="pictures", ine="IF NOT EXISTS "))
        cursor.execute(_PERSONA_TABLES["user_memory"].format(t="user_memory", ine="IF NOT EXISTS "))

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT    NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                first_seen    REAL    NOT NULL
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id     INTEGER PRIMARY KEY,
                bio         TEXT,
                fetched_at  REAL    NOT NULL
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS unresponded_messages (
                user_id     INTEGER NOT NULL,
                channel_id  INTEGER NOT NULL,
                content     TEXT    NOT NULL,
                received_at REAL    NOT NULL,
                nudge_sent  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, channel_id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS message_log (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER NOT NULL,
                username TEXT    NOT NULL,
                ts       REAL    NOT NULL,
                account  INTEGER
            )
        """
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_log_user_ts ON message_log (user_id, ts)"
        )
        # /api/stats/overview filters and groups on ts alone; the composite index above is useless for that, so those queries scanned the whole table.
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_log_ts ON message_log (ts)"
        )

        # Snapchat chat ids are UUID strings, separate text-keyed stats tables.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_stats_snap (
                chat_id       TEXT    PRIMARY KEY,
                username      TEXT    NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                first_seen    REAL    NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS message_log_snap (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id  TEXT    NOT NULL,
                username TEXT    NOT NULL,
                ts       REAL    NOT NULL,
                account  INTEGER
            )
            """
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_log_snap_ts ON message_log_snap (chat_id, ts)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_log_snap_tsonly ON message_log_snap (ts)"
        )
        # The unfiltered leaderboard orders by message_count, which had no index and so cost a full scan plus a sort every time.
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_stats_count ON user_stats (message_count DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_stats_snap_count "
            "ON user_stats_snap (message_count DESC)"
        )
        ensure_account_columns(conn)
        ensure_picture_columns(conn)
    ensure_persona_schema()


# ── A persona in every key ───────────────────────────────────────────────────
# Pictures, what it remembers about people, and the summaries of what they talked about belong to a persona. The
# tables keyed them by filename or person alone; the persona joins each key. SQLite cannot change a primary key, so
# an old table is rebuilt once, inside one write transaction, everything in it given to Default. A copy of the whole
# database is taken first: the change is one way, and what is in it is someone's memory.

_PERSONA_TABLES = {
    "pictures": (
        "CREATE TABLE {ine}{t} ("
        " persona TEXT NOT NULL DEFAULT 'default', filename TEXT NOT NULL,"
        " description TEXT NOT NULL DEFAULT '', look TEXT NOT NULL DEFAULT '',"
        " strength REAL NOT NULL DEFAULT 0, original TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (persona, filename))"),
    # user_id keeps its INTEGER affinity: a Discord id that arrives as text must still match the number stored.
    # learned_at: when the bot wrote this value down (the Memory page's brain); 0 for one from before, or written by hand.
    "user_memory": (
        "CREATE TABLE {ine}{t} ("
        " persona TEXT NOT NULL DEFAULT 'default', user_id INTEGER, key TEXT, value TEXT,"
        " learned_at REAL NOT NULL DEFAULT 0,"
        " PRIMARY KEY (persona, user_id, key))"),
    "user_summaries": (
        "CREATE TABLE {ine}{t} ("
        " persona TEXT NOT NULL DEFAULT 'default', user_key TEXT NOT NULL,"
        " summary TEXT NOT NULL, generated_at REAL NOT NULL, message_count INTEGER NOT NULL DEFAULT 0,"
        " settings_sig TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', recent TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (persona, user_key))"),
}

_persona_schema_ok = False


def _tables_without_persona(conn) -> list:
    out = []
    for table in _PERSONA_TABLES:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        if cols and "persona" not in cols:
            out.append((table, cols))
    return out


def _snapshot(conn) -> None:
    import time as _time
    from pathlib import Path
    dest_dir = Path(resource_path(db_path)).parent.parent / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(dest_dir / f"bot_data-before-personas-{int(_time.time())}.db"))
    try:
        conn.backup(dest)
    finally:
        dest.close()


def migrate_personas() -> bool:
    """Give pictures, user_memory and user_summaries a persona column, once. True when they have one (now or
    already), False when the change could not be made (it is tried again by the next process)."""
    conn = sqlite3.connect(resource_path(db_path), timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        if not _tables_without_persona(conn):
            return True
        _snapshot(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Looked at again inside the lock: another process may have just done it.
            for table, cols in _tables_without_persona(conn):
                tmp = f"{table}__p"
                conn.execute(f"DROP TABLE IF EXISTS {tmp}")
                conn.execute(_PERSONA_TABLES[table].format(t=tmp, ine=""))
                new_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({tmp})")}
                common = [c for c in cols if c in new_cols and c != "persona"]
                names = ", ".join(common)
                conn.execute(f"INSERT OR IGNORE INTO {tmp} (persona, {names}) SELECT 'default', {names} FROM {table}")
                conn.execute(f"DROP TABLE {table}")
                conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        print("[DB] Pictures, memory and summaries now belong to a persona; everything so far is Default's.",
              flush=True)
        return True
    except Exception as e:
        print(f"[DB] Could not give each persona its own pictures and memory yet: {e}", flush=True)
        return False
    finally:
        conn.close()


def ensure_persona_schema() -> None:
    """migrate_personas, once per process (tried again on the next call if it could not be done)."""
    global _persona_schema_ok
    if _persona_schema_ok:
        return
    if migrate_personas() and _ensure_learned_column():
        _persona_schema_ok = True


def _ensure_learned_column() -> bool:
    """When each fact was learned, on a memory table from before that was kept: a column added in place, every fact
    already there at 0 (not known). True when the table has it (or is not there yet: its CREATE has it)."""
    conn = sqlite3.connect(resource_path(db_path), timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        have = {row[1] for row in conn.execute("PRAGMA table_info(user_memory)")}
        if have and "learned_at" not in have:
            try:
                conn.execute("ALTER TABLE user_memory ADD COLUMN learned_at REAL NOT NULL DEFAULT 0")
            except sqlite3.OperationalError as e:
                # Another process added it a moment ago.
                if "duplicate column" not in str(e).lower():
                    raise
        return True
    except Exception as e:
        print(f"[DB] Could not note when facts are learned yet: {e}", flush=True)
        return False
    finally:
        conn.close()


def persona_key(persona=None) -> str:
    """The persona a row belongs to: the one named, else the one this code works as, else Default."""
    if persona:
        return str(persona)
    try:
        from app.utils import personas
        return personas.current() or "default"
    except Exception:
        return "default"


def delete_persona_rows(persona: str) -> None:
    """Everything a deleted persona had: its pictures' rows, its memory, its summaries."""
    ensure_persona_schema()
    with _connect() as conn:
        _ensure_summary_table(conn)
        for table in ("pictures", "user_memory", "user_summaries"):
            conn.execute(f"DELETE FROM {table} WHERE persona = ?", (persona,))


def copy_persona_pictures(src: str, dst: str) -> None:
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pictures (persona, filename, description, look, strength, original) "
            "SELECT ?, filename, description, look, strength, original FROM pictures WHERE persona = ?", (dst, src))


def copy_persona_summaries(src: str, dst: str) -> None:
    ensure_persona_schema()
    with _connect() as conn:
        _ensure_summary_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO user_summaries (persona, user_key, summary, generated_at, message_count, "
            "settings_sig, source, recent) SELECT ?, user_key, summary, generated_at, message_count, settings_sig, "
            "source, recent FROM user_summaries WHERE persona = ?", (dst, src))


def persona_people(persona: str) -> int:
    """How many people this persona remembers something about."""
    ensure_persona_schema()
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(DISTINCT user_id) FROM user_memory WHERE persona = ? AND key NOT LIKE '\\_\\_%' "
                           "ESCAPE '\\'", (persona,)).fetchone()
    return int(row[0] or 0) if row else 0


# which account sent each reply: the log didn't know at first, which didn't matter with one account but with several the Accounts page showed everybody's replies as everybody's; added with ALTER so an old database keeps its history, rows from before stay NULL and the reader decides what they can honestly be counted as (see /api/accounts/activity)
_account_columns_checked = False


def ensure_account_columns(conn) -> None:
    """Add the account column to the reply logs, once per process."""
    global _account_columns_checked
    if _account_columns_checked:
        return
    for table in ("message_log", "message_log_snap"):
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        # An empty answer means the table is not there yet, and the CREATE above already includes the column for when it is.
        if have and "account" not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN account INTEGER")
    _account_columns_checked = True


# The look on each picture (app/utils/looks.py): which, how strong, and the original it was made from, kept under
# config/pictures_originals by its content's hash. On the pictures row, so every renumber and delete that already goes
# through rename_picture_db and delete_picture_db carries it along without knowing about it.
_picture_columns_checked = False


def ensure_picture_columns(conn) -> None:
    """Add the look columns to the pictures table, once per process."""
    global _picture_columns_checked
    if _picture_columns_checked:
        return
    have = {row[1] for row in conn.execute("PRAGMA table_info(pictures)")}
    if have:
        for col, decl in (("look", "TEXT NOT NULL DEFAULT ''"), ("strength", "REAL NOT NULL DEFAULT 0"),
                          ("original", "TEXT NOT NULL DEFAULT ''")):
            if col not in have:
                conn.execute(f"ALTER TABLE pictures ADD COLUMN {col} {decl}")
        _picture_columns_checked = True


def renumber_account_replies(platform: str, removed: int) -> None:
    """Keep replies with the account that sent them when one is removed. Removing an account moves every later one up a number, but the replies they sent are tagged with their old number, so without this the account that became #1 would show the removed account's history as its own, and its own would belong to nobody. The removed account's replies are set to 0, which no account ever is: kept in the totals, shown on no card."""
    table = "message_log_snap" if platform == "snapchat" else "message_log"
    with _connect() as conn:
        ensure_account_columns(conn)
        conn.execute(f"UPDATE {table} SET account = 0 WHERE account = ?", (removed,))
        conn.execute(f"UPDATE {table} SET account = account - 1 WHERE account > ?", (removed,))


# ── Unresponded messages, nudge system ───────────────────────────────────────

def add_unresponded(user_id: int, channel_id: int, content: str, received_at: float):
    """Record a message that the bot received but hasn't replied to yet."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO unresponded_messages
                (user_id, channel_id, content, received_at, nudge_sent)
            VALUES (?, ?, ?, ?, 0)
            """,
            (user_id, channel_id, content, received_at),
        )


def mark_responded(user_id: int, channel_id: int):
    """Remove a user's unresponded entry once the bot has replied."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM unresponded_messages WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )


def _ensure_blocked_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blocked_users (
            user_id  INTEGER PRIMARY KEY,
            reason   TEXT    NOT NULL DEFAULT '',
            since    REAL    NOT NULL
        )
    """)


# memory-page summaries: what the conversation with each person has been about, written by the model when their card is opened, kept so opening them again is instant instead of another read plus another model call; settings_sig is the settings the summary was written under (message count, length, language), so changing any of them makes the stored one stale
def _ensure_summary_table(conn) -> None:
    ensure_persona_schema()
    conn.execute(_PERSONA_TABLES["user_summaries"].format(t="user_summaries", ine="IF NOT EXISTS "))
    # recent came later (the last few lines, for Big Picture): a table from before it gains the column in place.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_summaries)")}
    if "recent" not in cols:
        conn.execute("ALTER TABLE user_summaries ADD COLUMN recent TEXT NOT NULL DEFAULT ''")


def _summary_row(row) -> dict:
    import json as _json
    try:
        recent = _json.loads(row[5]) if row[5] else []
    except ValueError:
        recent = []
    return {"summary": row[0], "generated_at": row[1], "message_count": row[2],
            "settings_sig": row[3], "source": row[4],
            "recent": recent if isinstance(recent, list) else []}


def get_summary(user_key, persona=None) -> dict | None:
    """The stored summary for one person, by this persona, or None. Ids as strings throughout: Discord snowflakes and Snapchat chat ids share this table. recent is the last few lines it was written from, [{"mine", "text"}], empty for one written before those were kept."""
    with _connect() as conn:
        _ensure_summary_table(conn)
        row = conn.execute(
            "SELECT summary, generated_at, message_count, settings_sig, source, recent "
            "FROM user_summaries WHERE persona = ? AND user_key = ?", (persona_key(persona), str(user_key))).fetchone()
    return _summary_row(row) if row else None


def get_latest_summary(user_key) -> dict | None:
    """The newest summary of someone by any persona: for a page that shows a person without a persona of its own."""
    with _connect() as conn:
        _ensure_summary_table(conn)
        row = conn.execute(
            "SELECT summary, generated_at, message_count, settings_sig, source, recent "
            "FROM user_summaries WHERE user_key = ? ORDER BY generated_at DESC LIMIT 1", (str(user_key),)).fetchone()
    return _summary_row(row) if row else None


def set_summary(user_key, summary: str, message_count: int,
                settings_sig: str, source: str = "", recent: list | None = None, persona=None) -> float:
    """Store a summary, replacing any older one by this persona. Returns when it was written."""
    import json as _json
    import time as _time
    now = _time.time()
    lines = [{"mine": bool(r.get("mine")), "text": str(r.get("text", ""))[:300]}
             for r in (recent or []) if isinstance(r, dict) and r.get("text")][-4:]
    with _connect() as conn:
        _ensure_summary_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO user_summaries "
            "(persona, user_key, summary, generated_at, message_count, settings_sig, source, recent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (persona_key(persona), str(user_key), summary, now, int(message_count), settings_sig, source,
             _json.dumps(lines, ensure_ascii=False)))
    return now


def delete_summary(user_key, persona=None) -> None:
    """Forget someone's summary by this persona - when its memory of them is wiped, say."""
    with _connect() as conn:
        _ensure_summary_table(conn)
        conn.execute("DELETE FROM user_summaries WHERE persona = ? AND user_key = ?",
                     (persona_key(persona), str(user_key)))


def add_blocked(user_id: int, reason: str = "") -> None:
    """Record that this person cannot be messaged. A 403 on a send means they blocked the account, closed their DMs, or are no longer a friend. None of that clears by itself, so the conversation must stay off the waiting list, and it has to survive a restart: keeping it in memory meant the same dead conversation reappeared on every launch."""
    import time as _time
    with _connect() as conn:
        _ensure_blocked_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO blocked_users (user_id, reason, since) VALUES (?, ?, ?)",
            (user_id, reason, _time.time()))


def remove_blocked(user_id: int) -> None:
    """They messaged again, so whatever closed the channel has been undone."""
    with _connect() as conn:
        _ensure_blocked_table(conn)
        conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))


def blocked_users() -> dict:
    with _connect() as conn:
        _ensure_blocked_table(conn)
        return {row[0]: {"reason": row[1], "since": row[2]}
                for row in conn.execute("SELECT user_id, reason, since FROM blocked_users")}


def drop_unresponded(user_id: int) -> int:
    """Forget every pending message from someone, whatever channel it was in. Used when a reply can never succeed, for instance the account was deleted or Discord does not know the id. Without this the conversation stays on the waiting list for good: every sweep finds it, every reply fails the same way, and Reply to all keeps trying it for ever."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM unresponded_messages WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def mark_nudge_sent(user_id: int, channel_id: int):
    """Flag that a nudge has already been sent so we don't send another."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE unresponded_messages SET nudge_sent = 1 WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )


def get_unresponded() -> list[dict]:
    """Everyone who messaged and has not been answered, newest first. The table has held this all along and nothing read it back: the waiting list was built from the runner's in-memory history plus a live scan of the DM channels, both of which miss people. This is the copy that survives a restart and does not depend on a channel still being in Discord's cache. A nudged row is not waiting: the nudge was the bot speaking, and listing it had Reply to all answer their old message again."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT user_id, channel_id, content, received_at
            FROM unresponded_messages
            WHERE nudge_sent = 0
            ORDER BY received_at DESC
            """
        ).fetchall()
    return [
        {"user_id": r[0], "channel_id": r[1], "content": r[2], "received_at": r[3]}
        for r in rows
    ]


def get_pending_nudges(threshold_seconds: float) -> list[dict]:
    """Return all unresponded messages older than threshold that haven't been nudged yet."""
    with _connect() as conn:
        cursor = conn.cursor()
        import time as _time
        cutoff = _time.time() - threshold_seconds
        cursor.execute(
            """
            SELECT user_id, channel_id, content, received_at
            FROM unresponded_messages
            WHERE nudge_sent = 0 AND received_at <= ?
            """,
            (cutoff,),
        )
        rows = cursor.fetchall()
    return [
        {"user_id": r[0], "channel_id": r[1], "content": r[2], "received_at": r[3]}
        for r in rows
    ]


def add_channel(channel_id):
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO channels (id) VALUES (?)", (channel_id,))


def remove_channel(channel_id):
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM channels WHERE id = ?", (channel_id,))


def get_channels():
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM channels")
        channels = [row[0] for row in cursor.fetchall()]
    return channels


def add_ignored_user(user_id):
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO ignored_users (id) VALUES (?)", (user_id,))


def remove_ignored_user(user_id):
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ignored_users WHERE id = ?", (user_id,))


def get_ignored_users():
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ignored_users")
        users = [row[0] for row in cursor.fetchall()]
    return users


# ── Snapchat ignore list (TEXT chat ids) ────────────────────────────────────

def add_ignored_user_snap(chat_id: str):
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO ignored_users_snap (id) VALUES (?)", (str(chat_id),))


def remove_ignored_user_snap(chat_id: str):
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ignored_users_snap WHERE id = ?", (str(chat_id),))


def get_ignored_users_snap():
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ignored_users_snap")
        users = [row[0] for row in cursor.fetchall()]
    return users


# ── Pictures, description cache ──────────────────────────────────────────────
# Each persona has a folder of its own, so the same IMG_1.jpg can be two personas' pictures: every row is keyed by
# the persona as well as the name (persona=None: the one this code works as, else Default).

def add_picture_description(filename: str, description: str, persona=None):
    """Store (or update) the AI description for a picture file. Only the description: a replace would wipe the look
    the picture has on it."""
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pictures (persona, filename, description) VALUES (?, ?, ?) "
            "ON CONFLICT(persona, filename) DO UPDATE SET description = excluded.description",
            (persona_key(persona), filename, description),
        )


def get_picture_description(filename: str, persona=None) -> str | None:
    """Return the stored description for a filename, or None if not found."""
    ensure_persona_schema()
    with _connect() as conn:
        row = conn.execute("SELECT description FROM pictures WHERE persona = ? AND filename = ?",
                           (persona_key(persona), filename)).fetchone()
    return row[0] if row else None


def get_all_picture_descriptions(persona=None) -> dict[str, str]:
    """Every stored filename -> description of one persona's pictures, in one query. Picture selection needs the description of every file in the folder; doing that one lookup at a time opened a connection per image on every request."""
    ensure_persona_schema()
    with _connect() as conn:
        rows = conn.execute("SELECT filename, description FROM pictures WHERE persona = ?",
                            (persona_key(persona),)).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def delete_picture_db(filename: str, persona=None):
    """Remove a picture's DB entry when the file is deleted."""
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute("DELETE FROM pictures WHERE persona = ? AND filename = ?", (persona_key(persona), filename))


def rename_picture_db(old_filename: str, new_filename: str, persona=None):
    """Update the filename key when images are renumbered after a deletion."""
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute(
            "UPDATE pictures SET filename = ? WHERE persona = ? AND filename = ?",
            (new_filename, persona_key(persona), old_filename),
        )


def get_picture_looks(persona=None) -> dict[str, dict]:
    """filename -> {"look", "strength", "original"} for every picture of this persona that has a row."""
    ensure_persona_schema()
    with _connect() as conn:
        ensure_picture_columns(conn)
        rows = conn.execute("SELECT filename, look, strength, original FROM pictures WHERE persona = ?",
                            (persona_key(persona),)).fetchall()
    return {r[0]: {"look": r[1] or "", "strength": float(r[2] or 0), "original": r[3] or ""} for r in rows}


def get_picture_look(filename: str, persona=None) -> dict:
    return get_picture_looks(persona).get(filename) or {"look": "", "strength": 0.0, "original": ""}


def set_picture_look(filename: str, look: str, strength: float, original: str, persona=None):
    """The look a picture now has, and the original it was made from; its description is left as it is."""
    ensure_persona_schema()
    with _connect() as conn:
        ensure_picture_columns(conn)
        conn.execute(
            "INSERT INTO pictures (persona, filename, description, look, strength, original) "
            "VALUES (?, ?, '', ?, ?, ?) "
            "ON CONFLICT(persona, filename) DO UPDATE SET look = excluded.look, strength = excluded.strength, "
            "original = excluded.original",
            (persona_key(persona), filename, look or "", float(strength or 0), original or ""),
        )


def all_picture_originals() -> set:
    """Every original any persona's picture was made from: the shared originals folder is swept against these."""
    ensure_persona_schema()
    with _connect() as conn:
        ensure_picture_columns(conn)
        return {r[0] for r in conn.execute("SELECT DISTINCT original FROM pictures WHERE original != ''")}


def clear_all_pictures_db(persona=None):
    """Wipe one persona's picture descriptions, called when ,image delete all is used."""
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute("DELETE FROM pictures WHERE persona = ?", (persona_key(persona),))


# ── User stats, leaderboard ──────────────────────────────────────────────────

def record_user_message(user_id: int, username: str, account: int | None = None):
    """Increment message count for a user and append a timestamped log row. `account` is the Discord account the reply went out from."""
    import time as _time
    now = _time.time()
    with _connect() as conn:
        ensure_account_columns(conn)
        cursor = conn.cursor()
        # Update the fast running-count summary table (used for all-time leaderboard)
        cursor.execute(
            """
            INSERT INTO user_stats (user_id, username, message_count, first_seen)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                message_count = message_count + 1,
                username = excluded.username
            """,
            (user_id, username, now),
        )
        # Append a timestamped row so time-filtered leaderboard queries work
        cursor.execute(
            "INSERT INTO message_log (user_id, username, ts, account) VALUES (?, ?, ?, ?)",
            (user_id, username, now, account),
        )


# ── Snapchat user stats, leaderboard (text chat ids) ─────────────────────────

def record_user_message_snap(chat_id: str, username: str, account: int | None = None):
    """Snapchat equivalent of record_user_message, keyed on the chat UUID."""
    import time as _time
    now = _time.time()
    with _connect() as conn:
        ensure_account_columns(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user_stats_snap (chat_id, username, message_count, first_seen)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                message_count = message_count + 1,
                username = excluded.username
            """,
            (str(chat_id), username, now),
        )
        cursor.execute(
            "INSERT INTO message_log_snap (chat_id, username, ts, account) VALUES (?, ?, ?, ?)",
            (str(chat_id), username, now, account),
        )


def get_leaderboard_snap(limit: int = 50, since: float | None = None) -> list[dict]:
    """Top Snapchat chats by message count. Mirrors get_leaderboard()."""
    with _connect() as conn:
        cursor = conn.cursor()
        if since is None:
            cursor.execute(
                """
                SELECT chat_id, username, message_count, first_seen
                FROM user_stats_snap
                ORDER BY message_count DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    ml.chat_id,
                    ml.username,
                    COUNT(*)                            AS message_count,
                    COALESCE(us.first_seen, MIN(ml.ts)) AS first_seen
                FROM message_log_snap ml
                LEFT JOIN user_stats_snap us ON us.chat_id = ml.chat_id
                WHERE ml.ts >= ?
                GROUP BY ml.chat_id
                ORDER BY message_count DESC
                LIMIT ?
                """,
                (since, limit),
            )
        rows = cursor.fetchall()
    return [
        {"user_id": r[0], "username": r[1], "message_count": r[2], "first_seen": r[3]}
        for r in rows
    ]


# ── User profiles, persistent bio cache ──────────────────────────────────────

def get_cached_profile(user_id: int) -> str | None:
    """Return the cached bio for a user, or None if not found."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT bio FROM user_profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    return row[0] if row else None


def set_cached_profile(user_id: int, bio: str | None):
    """Store or update the cached bio for a user."""
    import time as _time
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user_profiles (user_id, bio, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET bio = excluded.bio,
                                               fetched_at = excluded.fetched_at
            """,
            (user_id, bio, _time.time()),
        )


# The table started as a bio cache. The panel shows a small profile card when you click a name, so it now also holds what is needed to draw one. Added with ALTER so existing databases pick the columns up without losing their bios.
_PROFILE_COLUMNS = (
    ("username", "TEXT"),
    ("display_name", "TEXT"),
    ("avatar", "TEXT"),
)


def _ensure_profile_columns(conn) -> None:
    have = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)")}
    for name, kind in _PROFILE_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE user_profiles ADD COLUMN {name} {kind}")


def set_profile_details(user_id: int, *, username=None, display_name=None,
                        avatar=None, bio=None) -> None:
    """Record whatever we know about a person. Only non-None values are written, so a later call with just an avatar does not wipe a stored bio."""
    import time as _time
    with _connect() as conn:
        _ensure_profile_columns(conn)
        conn.execute(
            "INSERT OR IGNORE INTO user_profiles (user_id, fetched_at) VALUES (?, ?)",
            (user_id, _time.time()),
        )
        pairs = {"username": username, "display_name": display_name,
                 "avatar": avatar, "bio": bio}
        sets = [f"{k} = ?" for k, v in pairs.items() if v is not None]
        if not sets:
            return
        values = [v for v in pairs.values() if v is not None]
        conn.execute(
            f"UPDATE user_profiles SET {', '.join(sets)}, fetched_at = ? WHERE user_id = ?",
            (*values, _time.time(), user_id),
        )


def get_profile_details(user_id: int) -> dict | None:
    """Everything cached about one person, or None if never seen."""
    with _connect() as conn:
        _ensure_profile_columns(conn)
        row = conn.execute(
            "SELECT user_id, bio, fetched_at, username, display_name, avatar "
            "FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return {"user_id": row[0], "bio": row[1], "fetched_at": row[2],
            "username": row[3], "display_name": row[4], "avatar": row[5]}


def clear_profile_cache() -> int:
    """Forget every cached profile. Returns how many were removed."""
    with _connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM user_profiles").fetchone()[0]
        conn.execute("DELETE FROM user_profiles")
    return n


def profile_cache_size() -> int:
    with _connect() as conn:
        try:
            return conn.execute("SELECT COUNT(*) FROM user_profiles").fetchone()[0]
        except Exception:
            return 0


def get_leaderboard(limit: int = 50, since: float | None = None) -> list[dict]:
    """Return top users sorted by message count descending. limit caps the rows; since is an optional unix timestamp: when given, counts only messages logged after it (uses message_log), when None it uses the fast running-count in user_stats (all-time)."""
    with _connect() as conn:
        cursor = conn.cursor()
        if since is None:
            # Fast path, pre-aggregated summary table
            cursor.execute(
                """
                SELECT user_id, username, message_count, first_seen
                FROM user_stats
                ORDER BY message_count DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            # Time-filtered, aggregate from per-message log
            cursor.execute(
                """
                SELECT
                    ml.user_id,
                    ml.username,
                    COUNT(*)                            AS message_count,
                    COALESCE(us.first_seen, MIN(ml.ts)) AS first_seen
                FROM message_log ml
                LEFT JOIN user_stats us ON us.user_id = ml.user_id
                WHERE ml.ts >= ?
                GROUP BY ml.user_id
                ORDER BY message_count DESC
                LIMIT ?
                """,
                (since, limit),
            )
        rows = cursor.fetchall()
    return [
        {"user_id": r[0], "username": r[1], "message_count": r[2], "first_seen": r[3]}
        for r in rows
    ]

