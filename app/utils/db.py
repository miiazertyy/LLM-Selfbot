import sqlite3
from contextlib import contextmanager

from app.utils.helpers import resource_path

db_path = "config/bot_data.db"

_pragmas_applied = False


@contextmanager
def _connect():
    """Open the shared DB with WAL + a busy timeout, always closing on exit.

    WAL lets the Discord runner, Snapchat bridge and Telegram controller read
    and write concurrently instead of tripping over "database is locked".
    """
    global _pragmas_applied
    conn = sqlite3.connect(resource_path(db_path), timeout=15)
    try:
        if not _pragmas_applied:
            conn.execute("PRAGMA journal_mode=WAL")
            _pragmas_applied = True
        conn.execute("PRAGMA busy_timeout=15000")
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

        # Snapchat chat ids are UUID strings, they can't live in an INTEGER PRIMARY
        # KEY column, so Snapchat keeps its own ignore table with a TEXT key.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ignored_users_snap (
                id TEXT PRIMARY KEY
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pictures (
                filename    TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT ''
            )
        """
        )

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
                ts       REAL    NOT NULL
            )
        """
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_log_user_ts ON message_log (user_id, ts)"
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
                ts       REAL    NOT NULL
            )
            """
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_log_snap_ts ON message_log_snap (chat_id, ts)"
        )


# ---------------------------------------------------------------------------
# Unresponded messages, nudge system
# ---------------------------------------------------------------------------

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


def add_blocked(user_id: int, reason: str = "") -> None:
    """Record that this person cannot be messaged.

    A 403 on a send means they blocked the account, closed their DMs, or are no
    longer a friend. None of that clears by itself, so the conversation must
    stay off the waiting list, and it has to survive a restart: keeping it in
    memory meant the same dead conversation reappeared on every launch.
    """
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
    """Forget every pending message from someone, whatever channel it was in.

    Used when a reply can never succeed, for instance the account was deleted or
    Discord does not know the id. Without this the conversation stays on the
    waiting list for good: every sweep finds it, every reply fails the same way,
    and Reply to all keeps trying it for ever.
    """
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


# ---------------------------------------------------------------------------
# Pictures, description cache
# ---------------------------------------------------------------------------

def add_picture_description(filename: str, description: str):
    """Store (or update) the AI description for a picture file."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO pictures (filename, description) VALUES (?, ?)",
            (filename, description),
        )


def get_picture_description(filename: str) -> str | None:
    """Return the stored description for a filename, or None if not found."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT description FROM pictures WHERE filename = ?", (filename,))
        row = cursor.fetchone()
    return row[0] if row else None


def get_all_picture_descriptions() -> dict[str, str]:
    """Every stored filename -> description, in one query.

    Picture selection needs the description of every file in the folder; doing
    that one lookup at a time opened a connection per image on every request.
    """
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT filename, description FROM pictures")
        rows = cursor.fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def delete_picture_db(filename: str):
    """Remove a picture's DB entry when the file is deleted."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pictures WHERE filename = ?", (filename,))


def rename_picture_db(old_filename: str, new_filename: str):
    """Update the filename key when images are renumbered after a deletion."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pictures SET filename = ? WHERE filename = ?",
            (new_filename, old_filename),
        )


def clear_all_pictures_db():
    """Wipe all picture descriptions, called when ,image delete all is used."""
    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pictures")


# ---------------------------------------------------------------------------
# User stats, leaderboard
# ---------------------------------------------------------------------------

def record_user_message(user_id: int, username: str):
    """Increment message count for a user and append a timestamped log row."""
    import time as _time
    now = _time.time()
    with _connect() as conn:
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
            "INSERT INTO message_log (user_id, username, ts) VALUES (?, ?, ?)",
            (user_id, username, now),
        )


# ---------------------------------------------------------------------------
# Snapchat user stats, leaderboard (text chat ids)
# ---------------------------------------------------------------------------

def record_user_message_snap(chat_id: str, username: str):
    """Snapchat equivalent of record_user_message, keyed on the chat UUID."""
    import time as _time
    now = _time.time()
    with _connect() as conn:
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
            "INSERT INTO message_log_snap (chat_id, username, ts) VALUES (?, ?, ?)",
            (str(chat_id), username, now),
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


# ---------------------------------------------------------------------------
# User profiles, persistent bio cache
# ---------------------------------------------------------------------------

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


# The table started as a bio cache. The panel shows a small profile card when
# you click a name, so it now also holds what is needed to draw one. Added with
# ALTER so existing databases pick the columns up without losing their bios.
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
    """Record whatever we know about a person. Only non-None values are written,
    so a later call with just an avatar does not wipe a stored bio."""
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
    """Return top users sorted by message count descending.

    Args:
        limit: Max rows to return.
        since: Optional unix timestamp. When given, counts only messages logged
               after this time (uses message_log). When None, uses the fast
               running-count in user_stats (all-time).
    """
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

