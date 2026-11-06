"""
What it saw online in its free time, per persona: the page, the site, and what it thought of it, in its own words.

Kept in the persona's own folder (personas.folder(pid)/web_journal.json), the KEEP newest. The replies are told about
the few freshest (prompt_block), to bring one up only when it fits, the way a person mentions something they saw
earlier. The Persona page lists them (app/web/routes/web_routes.py).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

KEEP = 40
SHOWN = 3
FRESH = 2 * 86400

_lock = threading.Lock()


def _pid(pid: str | None = None) -> str:
    from app.utils import personas
    return pid or personas.current() or personas.DEFAULT


def path(pid: str | None = None) -> Path:
    from app.utils import personas
    return personas.folder(_pid(pid)) / "web_journal.json"


def entries(pid: str | None = None) -> list:
    """Newest first: [{"ts", "title", "url", "site", "note"}]."""
    try:
        data = json.loads(path(pid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = [e for e in data if isinstance(e, dict) and e.get("url")] if isinstance(data, list) else []
    return sorted(rows, key=lambda e: -float(e.get("ts") or 0))


def add(pid: str | None, items: list) -> list:
    """These finds kept, newest first, one entry a page. What is kept now."""
    from app.utils.atomic import write_json_atomic
    now = time.time()
    with _lock:
        rows = entries(pid)
        for item in items:
            url = str(item.get("url") or "")
            note = " ".join(str(item.get("note") or "").split())[:400]
            if not url or not note:
                continue
            rows = [r for r in rows if r.get("url") != url]
            rows.insert(0, {"ts": now, "title": str(item.get("title") or "")[:200], "url": url,
                            "site": str(item.get("site") or "")[:80], "note": note})
        rows = rows[:KEEP]
        target = path(pid)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(target, rows, indent=1)
    return rows


def remove(pid: str | None, ts: float) -> bool:
    from app.utils.atomic import write_json_atomic
    with _lock:
        rows = entries(pid)
        left = [r for r in rows if abs(float(r.get("ts") or 0) - float(ts)) > 0.001]
        if len(left) == len(rows):
            return False
        write_json_atomic(path(pid), left, indent=1)
    return True


def _ago(ts: float, now: float) -> str:
    minutes = max(1, int((now - ts) // 60))
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 24 else "yesterday"


def prompt_block(pid: str | None = None) -> str:
    """The few freshest finds, for a reply: "" when there are none, or when browsing in its free time is off."""
    try:
        from app.utils.web import settings
        s = settings()
        if not s["free_time"]:
            return ""
        now = time.time()
        fresh = [e for e in entries(pid) if now - float(e.get("ts") or 0) < FRESH][:SHOWN]
    except Exception:
        return ""
    if not fresh:
        return ""
    seen = "; ".join(f"\"{e['title'] or e['site']}\" on {e['site']} ({_ago(float(e['ts']), now)}"
                     + (f", {e['url']}" if s["share_links"] else "") + f"): {e['note']}" for e in fresh)
    return (f"\n\n[THINGS YOU SAW ONLINE LATELY, in your free time: {seen}. Bring one up only when it fits the "
            "conversation naturally, never out of nowhere"
            + (", and paste its link only if they want to see it" if s["share_links"] else "") + ".]")
