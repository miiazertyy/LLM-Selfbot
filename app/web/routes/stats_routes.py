import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request

from app.utils.paths import DATA_DIR

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
async def overview(request: Request):
    conn = sqlite3.connect(DB_PATH)
    try:
        try:
            total = conn.execute("SELECT COUNT(*) FROM message_log").fetchone()[0]
            total_snap = conn.execute("SELECT COUNT(*) FROM message_log_snap").fetchone()[0]
            buckets = {}
            day = 86400
            now = time.time()
            for label, start in (("today", now - day), ("7d", now - 7 * day), ("30d", now - 30 * day)):
                n = conn.execute("SELECT COUNT(*) FROM message_log WHERE ts >= ?", (start,)).fetchone()[0]
                buckets[label] = n
            per_day = conn.execute(
                "SELECT CAST(ts/86400 AS INT) AS d, COUNT(*) FROM message_log WHERE ts >= ? GROUP BY d ORDER BY d",
                (now - 14 * day,),
            ).fetchall()
        except sqlite3.OperationalError:
            total, total_snap, buckets, per_day = 0, 0, {}, []
    finally:
        conn.close()
    series = [{"day": int(d), "count": n} for d, n in per_day]
    return {"total": total, "total_snapchat": total_snap, "windows": buckets,
            "series": series, **_extra_overview()}


def _extra_overview() -> dict:
    """The rest of what the dashboard draws: an hourly curve, who is most
    active, and how many distinct people have been spoken to."""
    import time as _t
    out = {"hourly": [], "top": [], "people": 0, "people_7d": 0, "snap_series": []}
    conn = sqlite3.connect(DB_PATH)
    try:
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
    finally:
        conn.close()
    return out
