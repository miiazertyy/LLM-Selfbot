"""What the bot remembers about each person, persona by persona.

Each persona remembers people on its own (app/utils/personas.py): two
personas talking to the same person each know only what was said to them.
Everything here takes persona=None, which means the persona this code works
as (an account's runner knows its own), else Default; the panel names one.
"""
import sqlite3
import time

from app.utils.db import _PERSONA_TABLES, _connect, ensure_persona_schema, persona_key


def init_memory():
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute(_PERSONA_TABLES["user_memory"].format(t="user_memory", ine="IF NOT EXISTS "))


def get_memory(user_id: int, persona=None) -> dict:
    """What this persona remembers about them. Someone linked to accounts on other platforms (`link`) is one person:
    it is everything remembered about any of them, the newest fact winning where two say different things."""
    ensure_persona_schema()
    ids = person_ids(user_id) or [user_id]
    marks = ",".join("?" * len(ids))
    with _connect() as conn:
        try:
            rows = conn.execute(
                f"SELECT key, value FROM user_memory WHERE persona = ? AND user_id IN ({marks}) "
                "ORDER BY COALESCE(learned_at, 0)", (persona_key(persona), *ids)).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(f"SELECT key, value FROM user_memory WHERE persona = ? AND user_id IN ({marks})",
                                (persona_key(persona), *ids)).fetchall()
    # Oldest first, so the last one read is the one kept.
    return {row[0]: row[1] for row in rows}


def set_memory(user_id: int, key: str, value: str, persona=None, learned: bool = True):
    """Write one fact down. `learned`: the bot found it out, so now is when it learned it, unless the value is the one
    it already had; False for one written by hand on the Memory page, which keeps the time it had (0 when new)."""
    ensure_persona_schema()
    row = (persona_key(persona), user_id, key, value, time.time() if learned else 0)
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO user_memory (persona, user_id, key, value, learned_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(persona, user_id, key) DO UPDATE SET value = excluded.value, learned_at = CASE "
                "WHEN excluded.learned_at > 0 AND user_memory.value IS NOT excluded.value THEN excluded.learned_at "
                "ELSE user_memory.learned_at END",
                row,
            )
        except sqlite3.OperationalError:
            # A table without the column (it could not be added): written as before, with no time.
            conn.execute("INSERT OR REPLACE INTO user_memory (persona, user_id, key, value) VALUES (?, ?, ?, ?)",
                         row[:4])


def delete_memory(user_id: int, key: str, persona=None):
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute("DELETE FROM user_memory WHERE persona = ? AND user_id = ? AND key = ?",
                     (persona_key(persona), user_id, key))


def clear_memory(user_id: int, persona=None):
    ensure_persona_schema()
    with _connect() as conn:
        conn.execute("DELETE FROM user_memory WHERE persona = ? AND user_id = ?", (persona_key(persona), user_id))


def copy_persona_memory(src: str, dst: str):
    """Everything one persona remembers, given to another (a copy made with its memory)."""
    ensure_persona_schema()
    with _connect() as conn:
        try:
            conn.execute("INSERT OR REPLACE INTO user_memory (persona, user_id, key, value, learned_at) "
                         "SELECT ?, user_id, key, value, learned_at FROM user_memory WHERE persona = ?", (dst, src))
        except sqlite3.OperationalError:
            conn.execute("INSERT OR REPLACE INTO user_memory (persona, user_id, key, value) "
                         "SELECT ?, user_id, key, value FROM user_memory WHERE persona = ?", (dst, src))


# ── One person, several accounts ──────────────────────────────────────────────
# The same human writes to the bot from Discord and from Snapchat, and until now it knew them as two strangers,
# learning everything twice. Linking them makes one person of them: what it remembers is shared, whichever account
# they write from. Who someone is does not depend on which persona is talking to them, so a link is not kept per
# persona; what is remembered still is.
#
# Nothing is merged on disk. Each account's facts stay under its own id, so unlinking one that was not the same
# person after all gives each of them back exactly what it had.

_LINKS = ("CREATE TABLE IF NOT EXISTS person_links ("
          " user_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, linked_at REAL NOT NULL DEFAULT 0)")
_links_ok = False


def _links(conn):
    """The table, made once per process."""
    global _links_ok
    if not _links_ok:
        conn.execute(_LINKS)
        conn.execute("CREATE INDEX IF NOT EXISTS person_links_group ON person_links(group_id)")
        _links_ok = True


def person_ids(user_id, conn=None) -> list:
    """Every id this person writes from, their own first, or [] when they are not linked to anyone."""
    if conn is None:
        with _connect() as c:
            return person_ids(user_id, c)
    _links(conn)
    row = conn.execute("SELECT group_id FROM person_links WHERE user_id = ?", (str(user_id),)).fetchone()
    if not row:
        return []
    ids = [r[0] for r in conn.execute(
        "SELECT user_id FROM person_links WHERE group_id = ? ORDER BY linked_at, user_id", (row[0],))]
    # Their own id first: where a fact is in two of them, the one being asked about is the one written to.
    return [str(user_id)] + [i for i in ids if i != str(user_id)]


def linked_people() -> dict:
    """Every linked person: each id to the other ids it is the same person as."""
    with _connect() as conn:
        _links(conn)
        by_group = {}
        for uid, gid in conn.execute("SELECT user_id, group_id FROM person_links ORDER BY linked_at, user_id"):
            by_group.setdefault(gid, []).append(str(uid))
    out = {}
    for ids in by_group.values():
        for uid in ids:
            out[uid] = [i for i in ids if i != uid]
    return out


def link_people(user_id, other_id) -> list:
    """Say these two accounts are one person. Either already being in a group joins the groups rather than making a
    third, so linking a third account to any member of a pair takes in all of them."""
    a, b = str(user_id), str(other_id)
    if a == b:
        raise ValueError("that is the same account")
    with _connect() as conn:
        _links(conn)
        now = time.time()
        ga = conn.execute("SELECT group_id FROM person_links WHERE user_id = ?", (a,)).fetchone()
        gb = conn.execute("SELECT group_id FROM person_links WHERE user_id = ?", (b,)).fetchone()
        if ga and gb:
            if ga[0] != gb[0]:
                conn.execute("UPDATE person_links SET group_id = ? WHERE group_id = ?", (ga[0], gb[0]))
        elif ga or gb:
            gid = (ga or gb)[0]
            conn.execute("INSERT OR REPLACE INTO person_links (user_id, group_id, linked_at) VALUES (?, ?, ?)",
                         (b if ga else a, gid, now))
        else:
            gid = f"grp_{int(now * 1000):x}"
            conn.execute("INSERT OR REPLACE INTO person_links (user_id, group_id, linked_at) VALUES (?, ?, ?)",
                         (a, gid, now))
            conn.execute("INSERT OR REPLACE INTO person_links (user_id, group_id, linked_at) VALUES (?, ?, ?)",
                         (b, gid, now + 0.001))
        return person_ids(a, conn)


def unlink_person(user_id) -> None:
    """Take one account out: it was not the same person after all. It keeps its own facts, and the rest stay linked;
    a pair left with one member is no group at all, so that one is let go too."""
    uid = str(user_id)
    with _connect() as conn:
        _links(conn)
        row = conn.execute("SELECT group_id FROM person_links WHERE user_id = ?", (uid,)).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM person_links WHERE user_id = ?", (uid,))
        left = [r[0] for r in conn.execute("SELECT user_id FROM person_links WHERE group_id = ?", (row[0],))]
        if len(left) < 2:
            conn.execute("DELETE FROM person_links WHERE group_id = ?", (row[0],))


# ── Per-user persona overrides ────────────────────────────────────────────────
# How this persona talks to one person in particular ("their own tone" on the Memory page).

def get_persona(user_id: int, persona=None) -> str | None:
    """Return a custom persona/tone instruction for this user, or None."""
    ensure_persona_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM user_memory WHERE persona = ? AND user_id = ? AND key = '__persona__'",
            (persona_key(persona), user_id),
        ).fetchone()
    return row[0] if row else None


def set_persona(user_id: int, tone: str, persona=None):
    """Store a custom persona/tone instruction for this user."""
    set_memory(user_id, "__persona__", tone, persona)


def clear_persona(user_id: int, persona=None):
    """Remove any custom persona for this user."""
    delete_memory(user_id, "__persona__", persona)


def format_memory_for_prompt(memory: dict) -> str:
    visible = {k: v for k, v in memory.items() if not k.startswith("__")}
    if not visible:
        return ""
    lines = "\n".join(f"- {k}: {v}" for k, v in visible.items())
    return (
        f"\nWhat you remember about this person (use it naturally when "
        f"relevant, never list it out loud and never mention that you "
        f"'remember' or 'stored' anything):\n{lines}"
    )
