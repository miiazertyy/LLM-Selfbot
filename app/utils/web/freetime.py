"""
Its free time: a few times a day (bot.web.sessions_per_day) it browses on its own, like a person on their phone, and
keeps what it saw (journal.py) to bring up later in its chats.

One loop in the app's own process (server.py starts it), for every persona with an account running: one that runs
nowhere is not on its phone either. Sessions are spread over its waking hours: never at night (bot.night_invisible's
hours, in its timezone), never two personas at once. Browse now on the Persona page starts one straight away
(app/web/routes/web_routes.py), and the page watches it as it goes: the step it is on and a picture of the page.
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime

from app.utils.web import settings

# A waking day, about: sessions are spread over this much of it.
AWAKE_SECONDS = 16 * 3600

_next: dict = {}          # persona -> when its next session is due
_count: dict = {}         # (persona, day) -> sessions that day
now_state: dict = {"busy": False, "persona": "", "name": "", "step": "", "steps": [], "url": "", "title": "",
                   "since": 0.0, "shot": b"", "shot_at": 0.0, "last": None}


def _log(text: str):
    try:
        from app.utils.logger import log_system
        log_system(text)
    except Exception:
        pass


def awake(config: dict, now: datetime | None = None) -> bool:
    """Not its night: bot.night_invisible.hours ("2-8"), in that section's timezone."""
    night = ((config or {}).get("bot") or {}).get("night_invisible") or {}
    try:
        start, end = (int(x) % 24 for x in str(night.get("hours") or "2-8").split("-", 1))
    except ValueError:
        start, end = 2, 8
    try:
        from zoneinfo import ZoneInfo
        now = now or datetime.now(ZoneInfo(str(night.get("timezone") or "Europe/Paris")))
    except Exception:
        now = now or datetime.now()
    h = now.hour
    asleep = start <= h < end if start <= end else (h >= start or h < end)
    return not asleep


def _gap(per_day: int) -> float:
    """Until the next session: its share of a waking day, give or take."""
    return AWAKE_SECONDS / max(1, per_day) * random.uniform(0.6, 1.4)


def _personas(supervisor) -> list:
    """The personas with an account running, one of each."""
    try:
        from app.utils import personas, socials
        on = socials.on()
        ids = supervisor.running_ids() if supervisor is not None else set()
        return sorted({personas.persona_of(i) for i in ids
                       if i.split("_")[0] in on and on.get(i.split("_")[0], True)})
    except Exception:
        return []


def _config_of(pid: str) -> dict:
    from app.utils import personas
    from app.utils.helpers import load_config
    with personas.scope(pid):
        return load_config()


async def loop(supervisor) -> None:
    """The app's free-time clock: once a minute, whoever is due browses."""
    await asyncio.sleep(120)              # the accounts settle first
    while True:
        try:
            await _tick(supervisor)
        except Exception as e:
            _log(f"Free-time browsing hit a snag: {type(e).__name__}: {e}")
        await asyncio.sleep(60)


async def _tick(supervisor) -> None:
    if now_state["busy"]:
        return
    now = time.time()
    day = datetime.now().strftime("%Y-%m-%d")
    for pid in _personas(supervisor):
        cfg = _config_of(pid)
        s = settings(cfg)
        if not (s["free_time"] and s["sessions_per_day"] > 0):
            _next.pop(pid, None)
            continue
        if pid not in _next:
            # The first of the day comes a little after the app opens, not the moment it does.
            _next[pid] = now + random.uniform(600, 2400)
            continue
        if now < _next[pid]:
            continue
        if not awake(cfg) or _count.get((pid, day), 0) >= s["sessions_per_day"]:
            _next[pid] = now + random.uniform(1500, 3000)
            continue
        await browse(pid)
        _count[(pid, day)] = _count.get((pid, day), 0) + 1
        _next[pid] = time.time() + _gap(s["sessions_per_day"])
        return                            # one session a minute at most, whoever is due next waits


async def browse(pid: str) -> dict:
    """One session for this persona, now. {"ok", "saw" | "reason"}. Never raises."""
    if now_state["busy"]:
        return {"ok": False, "reason": "it is already browsing"}
    from app.utils import personas
    from app.utils.web import agent, browser, journal
    info = personas.get(pid) or {}
    name = str(info.get("name") or pid)
    now_state.update(busy=True, persona=pid, name=name, step="Picking something to look at", steps=[], url="",
                     title="", since=time.time(), shot=b"", shot_at=0.0)
    _log(f"{name} is browsing in its free time")
    session = None
    watcher = None
    try:
        with personas.scope(pid):
            text = personas.read_text(pid) or ""
            recent = [f"{e.get('title')} ({e.get('site')})" for e in journal.entries(pid)[:8]]
            session = await browser.session()
            if isinstance(session, browser.Session):
                watcher = asyncio.create_task(_watch(session))

            def step(kind: str, said: str):
                now_state["step"] = said
                now_state["steps"] = (now_state["steps"] + [said])[-12:]
                _log(f"{name}: {said}")

            found = await agent.wander(name, text, recent, session=session, on_step=step)
        if found.saw:
            journal.add(pid, found.saw)
            for item in found.saw:
                _log(f"{name} saw {item['title']} ({item['site']}): {item['note'][:120]}")
        else:
            _log(f"{name} browsed for {found.seconds:.0f}s and kept nothing")
        now_state["last"] = {"persona": pid, "at": time.time(), "saw": found.saw, "seconds": found.seconds}
        return {"ok": True, "saw": found.saw}
    except Exception as e:
        _log(f"{name}'s browsing stopped: {type(e).__name__}: {e}")
        return {"ok": False, "reason": str(e)}
    finally:
        if watcher:
            watcher.cancel()
        if session is not None:
            await browser.release(session)
        now_state.update(busy=False, step="")


async def _watch(session) -> None:
    """A picture of the page every couple of seconds, for the Persona page to show while it browses."""
    while True:
        try:
            shot = await session.screenshot()
            if shot:
                now_state["shot"], now_state["shot_at"] = shot, time.time()
                now_state["url"] = session.url
        except Exception:
            pass
        await asyncio.sleep(2.5)


def next_at(pid: str) -> float | None:
    return _next.get(pid)
