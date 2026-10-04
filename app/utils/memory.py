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
    ensure_persona_schema()
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM user_memory WHERE persona = ? AND user_id = ?",
                            (persona_key(persona), user_id)).fetchall()
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
