import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request

from app.utils.paths import DATA_DIR
# connect_raw() instead of a bare sqlite3.connect(): a plain connection sets
# no busy_timeout, so these queries failed with "database is locked" rather
# than waiting whenever a bot runner happened to be writing.
from app.utils.db import connect_raw

router = APIRouter(tags=["stats"])

DB_PATH = DATA_DIR / "config" / "bot_data.db"


@router.get("/api/stats/leaderboard")
async def leaderboard(request: Request, target: str = "", filter: str = ""):
    from app.core import ipc
    if target and (target.startswith("discord_") or target.startswith("snapchat_")):
        meta = ipc.discover_targets().get(target)
        tgt = meta["target"] if meta else None
    else:
        tgt = None
    if tgt is not None:
        result = await ipc.send_and_wait(tgt, "get_leaderboard", {"filter": filter or None}, timeout=10.0)
        if result:
            return result
    from app.utils.db import get_leaderboard
    from datetime import datetime
    since = None
    filter_label = "all time"
    if filter:
        import re as _re
        m = _re.fullmatch(r"(\d+(?:\.\d+)?)\s*([hdwm])", filter.strip().lower())
        if m:
            amount, unit = float(m.group(1)), m.group(2)
            seconds_map = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000}
            since = time.time() - amount * seconds_map[unit]
            unit_names = {"h": "hour", "d": "day", "w": "week", "m": "month"}
            n = int(amount) if amount == int(amount) else amount
            filter_label = f"last {n} {unit_names[unit]}{'s' if n != 1 else ''}"
    rows = get_leaderboard(limit=50, since=since)
    return {
        "rows": [{"username": r["username"], "message_count": r["message_count"],
                  "first_seen_fmt": datetime.fromtimestamp(r["first_seen"]).strftime("%d %b %Y")}
                 for r in rows],
        "filter_label": filter_label,
    }


@router.get("/api/stats/overview")
def overview(request: Request):
    """Everything the dashboard draws, on one connection.

    The dashboard polls this every five seconds. It used to open two
    connections and run three separate "COUNT(*) WHERE ts >= ?" scans; those
    are now one pass, and idx_message_log_ts means they use an index instead
    of walking the whole table. Plain def so FastAPI runs it on its threadpool
    rather than blocking the event loop on sqlite.
    """
    conn = connect_raw()
    try:
        try:
            total = conn.execute("SELECT COUNT(*) FROM message_log").fetchone()[0]
            total_snap = conn.execute("SELECT COUNT(*) FROM message_log_snap").fetchone()[0]
            day = 86400
            now = time.time()
            # One scan of the last 30 days, bucketed in SQL, instead of three
            # separate counts over overlapping ranges.
            row = conn.execute(
                "SELECT "
                "  SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END), "
                "  SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END), "
                "  COUNT(*) "
                "FROM message_log WHERE ts >= ?",
                (now - day, now - 7 * day, now - 30 * day),
            ).fetchone()
            buckets = {"today": row[0] or 0, "7d": row[1] or 0, "30d": row[2] or 0}
            per_day = conn.execute(
                "SELECT CAST(ts/86400 AS INT) AS d, COUNT(*) FROM message_log WHERE ts >= ? GROUP BY d ORDER BY d",
                (now - 14 * day,),
            ).fetchall()
        except sqlite3.OperationalError:
            total, total_snap, buckets, per_day = 0, 0, {}, []
        series = [{"day": int(d), "count": n} for d, n in per_day]
        extra = _extra_overview(conn)
    finally:
        conn.close()
    return {"total": total, "total_snapchat": total_snap, "windows": buckets,
            "series": series, **extra}


def _extra_overview(conn) -> dict:
    """The rest of what the dashboard draws: an hourly curve, who is most
    active, and how many distinct people have been spoken to.

    Takes the caller's connection; it used to open a second one for the same
    request.
    """
    import time as _t
    out = {"hourly": [], "top": [], "people": 0, "people_7d": 0, "snap_series": []}
    now = _t.time()
    try:
        rows = conn.execute(
            "SELECT CAST(ts/3600 AS INT) AS h, COUNT(*) FROM message_log "
            "WHERE ts >= ? GROUP BY h ORDER BY h", (now - 24 * 3600,)).fetchall()
        # Fill the gaps so a quiet hour is a zero, not a missing point.
        base = int((now - 24 * 3600) // 3600)
        counts = {int(h): n for h, n in rows}
        out["hourly"] = [{"hour": base + i, "count": counts.get(base + i, 0)}
                         for i in range(25)]

        out["top"] = [
            # The id rides along as a string: a Discord snowflake is 19
            # digits and JSON numbers lose precision past 2^53, which was
            # corrupting ids into ones that do not exist.
            {"user_id": str(uid), "username": u or str(uid), "count": n}
            for uid, u, n in conn.execute(
                "SELECT user_id, username, COUNT(*) AS n FROM message_log "
                "WHERE ts >= ? GROUP BY user_id ORDER BY n DESC LIMIT 5",
                (now - 7 * 86400,)).fetchall()
        ]
        out["people"] = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM message_log").fetchone()[0]
        out["people_7d"] = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM message_log WHERE ts >= ?",
            (now - 7 * 86400,)).fetchone()[0]
    except sqlite3.OperationalError:
        pass
    try:
        snap = conn.execute(
            "SELECT CAST(ts/86400 AS INT) AS d, COUNT(*) FROM message_log_snap "
            "WHERE ts >= ? GROUP BY d ORDER BY d", (_t.time() - 14 * 86400,)).fetchall()
        out["snap_series"] = [{"day": int(d), "count": n} for d, n in snap]
    except sqlite3.OperationalError:
        pass
    return out


# ── Drill-down ───────────────────────────────────────────────────────────────
# The dashboard tiles are a number each, which answers "how many" and nothing
# else. Clicking one opens this: the same figure broken down by time of day,
# day of week, platform and person, against the window before it.
#
# One connection, one pass per shape, all of it indexed on ts. The window is
# capped because this is a local sqlite file on someone's laptop, not a
# warehouse - 365 days of an active account is still a fast scan, more is not
# a question anyone is asking of a chat bot.
_MAX_WINDOW_DAYS = 365


def _bucket(conn, table, id_col, since, expr, extra_where=""):
    """COUNT(*) grouped by `expr` since `since`, as {bucket: count}."""
    try:
        rows = conn.execute(
            f"SELECT {expr} AS b, COUNT(*) FROM {table} WHERE ts >= ? {extra_where} GROUP BY b",
            (since,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {int(b): n for b, n in rows if b is not None}


@router.get("/api/stats/detail")
def stats_detail(request: Request, days: int = 30):
    """Everything behind one dashboard figure, for the last `days` days."""
    days = max(1, min(int(days or 30), _MAX_WINDOW_DAYS))
    now = time.time()
    day = 86400.0
    since = now - days * day
    prev_since = since - days * day

    conn = connect_raw()
    try:
        out: dict = {"days": days, "generated_at": now}

        # ── Totals, this window against the one before it ────────────────────
        def _count(table, frm, to=None):
            try:
                if to is None:
                    return conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE ts >= ?", (frm,)).fetchone()[0]
                return conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE ts >= ? AND ts < ?",
                    (frm, to)).fetchone()[0]
            except sqlite3.OperationalError:
                return 0

        discord_n = _count("message_log", since)
        snap_n = _count("message_log_snap", since)
        prev_n = _count("message_log", prev_since, since) + _count("message_log_snap", prev_since, since)
        out["total"] = discord_n + snap_n
        out["previous"] = prev_n
        out["platform"] = {"discord": discord_n, "snapchat": snap_n}

        # ── Per day, per platform. Faceted in the UI rather than drawn as two
        # coloured series: the app's two accent colours fail a colour-vision
        # separation check in four of its six themes, so one hue per chart is
        # the only encoding that holds up whatever theme is picked.
        d_days = _bucket(conn, "message_log", "user_id", since, "CAST(ts/86400 AS INT)")
        s_days = _bucket(conn, "message_log_snap", "chat_id", since, "CAST(ts/86400 AS INT)")
        first_day = int(since // day)
        out["series"] = [
            {"day": first_day + i,
             "discord": d_days.get(first_day + i, 0),
             "snapchat": s_days.get(first_day + i, 0)}
            for i in range(days + 1)
        ]

        # ── Shape of a day, and of a week ────────────────────────────────────
        # strftime on a unix ts: '%H' is 00-23 local-to-UTC, '%w' is 0=Sunday.
        d_hour = _bucket(conn, "message_log", "user_id", since,
                         "CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INT)")
        s_hour = _bucket(conn, "message_log_snap", "chat_id", since,
                         "CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INT)")
        out["hourly"] = [{"hour": h, "count": d_hour.get(h, 0) + s_hour.get(h, 0)}
                         for h in range(24)]

        d_dow = _bucket(conn, "message_log", "user_id", since,
                        "CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INT)")
        s_dow = _bucket(conn, "message_log_snap", "chat_id", since,
                        "CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INT)")
        out["weekday"] = [{"day": w, "count": d_dow.get(w, 0) + s_dow.get(w, 0)}
                          for w in range(7)]

        # ── Who ──────────────────────────────────────────────────────────────
        top = []
        try:
            for uid, uname, n in conn.execute(
                    "SELECT user_id, username, COUNT(*) AS n FROM message_log "
                    "WHERE ts >= ? GROUP BY user_id ORDER BY n DESC LIMIT 12",
                    (since,)).fetchall():
                # Ids go out as strings: a snowflake is 19 digits and a JSON
                # number loses precision past 2**53.
                top.append({"id": str(uid), "name": uname or str(uid),
                            "count": n, "platform": "discord"})
        except sqlite3.OperationalError:
            pass
        try:
            for cid, uname, n in conn.execute(
                    "SELECT chat_id, username, COUNT(*) AS n FROM message_log_snap "
                    "WHERE ts >= ? GROUP BY chat_id ORDER BY n DESC LIMIT 12",
                    (since,)).fetchall():
                top.append({"id": str(cid), "name": uname or str(cid),
                            "count": n, "platform": "snapchat"})
        except sqlite3.OperationalError:
            pass
        top.sort(key=lambda r: r["count"], reverse=True)
        out["top"] = top[:12]

        # ── People ───────────────────────────────────────────────────────────
        def _scalar(sql, args=()):
            try:
                return conn.execute(sql, args).fetchone()[0] or 0
            except sqlite3.OperationalError:
                return 0

        out["people"] = {
            "window": _scalar("SELECT COUNT(DISTINCT user_id) FROM message_log WHERE ts >= ?", (since,))
            + _scalar("SELECT COUNT(DISTINCT chat_id) FROM message_log_snap WHERE ts >= ?", (since,)),
            "previous": _scalar(
                "SELECT COUNT(DISTINCT user_id) FROM message_log WHERE ts >= ? AND ts < ?",
                (prev_since, since))
            + _scalar(
                "SELECT COUNT(DISTINCT chat_id) FROM message_log_snap WHERE ts >= ? AND ts < ?",
                (prev_since, since)),
            "all_time": _scalar("SELECT COUNT(DISTINCT user_id) FROM message_log")
            + _scalar("SELECT COUNT(DISTINCT chat_id) FROM message_log_snap"),
            # first_seen is when the row was created, so this really is "people
            # who had never been spoken to before this window".
            "new": _scalar("SELECT COUNT(*) FROM user_stats WHERE first_seen >= ?", (since,))
            + _scalar("SELECT COUNT(*) FROM user_stats_snap WHERE first_seen >= ?", (since,)),
        }

        # ── The single busiest hour and day, for the headline sentence ───────
        busiest_hour = max(out["hourly"], key=lambda h: h["count"], default=None)
        busiest_day = max(out["series"], key=lambda d: d["discord"] + d["snapchat"], default=None)
        out["busiest"] = {
            "hour": busiest_hour["hour"] if busiest_hour and busiest_hour["count"] else None,
            "hour_count": busiest_hour["count"] if busiest_hour else 0,
            "day": busiest_day["day"] if busiest_day else None,
            "day_count": (busiest_day["discord"] + busiest_day["snapchat"]) if busiest_day else 0,
        }
        return out
    finally:
        conn.close()
