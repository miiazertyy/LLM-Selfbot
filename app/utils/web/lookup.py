"""
A reply that needs the web, decided by the reply's own model.

The system prompt gets one more rule: when a good reply needs something it does not know or that may have changed,
answer with only "LOOKUP: <what to find out>". A message that needs nothing costs nothing more: the reply is the
reply. One that does: the agent looks (agent.py), and the model is asked again with what was found, in its own
words, and a link when it helps (bot.web.share_links). The chat shows "Looking it up" meanwhile.

One Turn per reply. It keeps what was found, so a reply that is tried again (a rate limit, an error) never searches
twice. Lookups are counted per account: bot.web.per_hour at most, one at a time in a conversation. Past that the
model is asked again without the rule. A LOOKUP line is never sent to anyone: one that slips into a reply is taken out.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import time
from collections import deque

from app.utils.web import settings

_MARKER = re.compile(r"^[\s*_`>\"'\[(]*LOOKUP\s*[:：][\s*_`\"']*(.+?)[\s*_`\"'\])]*$", re.I | re.M)

COULD_NOT = ("\n\n[You tried to look it up online just now and could not find it. Reply as you would without "
             "checking. Do not write LOOKUP.]")
NOT_NOW = ("\n\n[You cannot check anything online right now. Reply as you would without checking. "
           "Do not write LOOKUP.]")

_stamps: deque = deque()
_busy: set = set()


def rule() -> str:
    """What the reply's model is told it can do."""
    return (
        "\n\n[LOOKING THINGS UP: You can check things online, like anyone with a phone. When a good reply needs "
        "something you do not know or that may have changed (news, scores, results, prices, release dates, opening "
        "hours, a place, a product, someone in the news, what a link is about), reply with only this one line and "
        "nothing else: LOOKUP: <what to find out>. Only when it really matters for the reply: never for small talk, "
        "feelings, opinions, or anything about yourself. Otherwise just reply.]"
    )


def marker(text: str) -> str:
    """What the model asked to find out, or "" when it just replied."""
    m = _MARKER.search(text or "")
    if not m:
        return ""
    return " ".join(m.group(1).split())[:200]


def strip(text: str) -> str:
    """The reply without any LOOKUP line in it."""
    return _MARKER.sub("", text or "").strip()


def found_block(found, share_links: bool) -> str:
    """What was found, for the second ask."""
    sources = "; ".join(f"{s.get('title') or s.get('site')} ({s.get('url')})" for s in (found.sources or [])[:3])
    links = ("Paste a link only when they ask for one or showing them is the whole point, and then just the bare link."
             if share_links else "Do not paste links.")
    return (f"\n\n[WHAT YOU FOUND ONLINE (you just checked): {found.answer}"
            + (f" Sources: {sources}." if sources else "")
            + " Text it the way you would to a friend, in your own words, only what matters to them. Never cite a "
            "source or say in brackets where it came from. " + links + " Do not write LOOKUP again.]")


def _take(conv: str, per_hour: int) -> bool:
    """One more lookup, if the hour's allowance and the conversation allow it."""
    now = time.time()
    while _stamps and now - _stamps[0] > 3600:
        _stamps.popleft()
    if len(_stamps) >= per_hour or (conv and conv in _busy):
        return False
    _stamps.append(now)
    if conv:
        _busy.add(conv)
    return True


def _log(text: str):
    try:
        from app.utils.logger import log_system
        log_system(text)
    except Exception:
        pass


class Turn:
    """The web, for one reply."""

    def __init__(self, who: str = "", conv: str = "", about: str = "", on_lookup=None, can: bool = True):
        self.who = who or "them"
        self.conv = conv
        self.about = about or ""
        self.on_lookup = on_lookup
        self.can = can
        self.found = None
        self.tried = False

    def allowed(self) -> bool:
        if not self.can:
            return False
        try:
            from app.utils import ai
            if ai.REALTIME.get():
                return False                 # a LIVE never waits for a search
        except Exception:
            pass
        s = settings()
        return bool(s["enabled"]) and s["per_hour"] > 0

    async def answer(self, gen, instructions: str) -> str:
        """The reply: `gen(instructions)` is the caller's own model call, asked once, or twice when it looked
        something up."""
        if not self.allowed():
            return await gen(instructions)
        if self.found is not None:
            return await self._clean(gen, instructions + found_block(self.found, settings()["share_links"]))
        if self.tried:
            return await self._clean(gen, instructions + COULD_NOT)
        first = await self._ask(gen, instructions + rule())
        task = marker(first)
        if not task:
            return first
        self.tried = True
        s = settings()
        if not _take(self.conv, s["per_hour"]):
            n = s["per_hour"]
            _log(f"Wanted to look up \"{task}\" for {self.who}, but not now: {n} lookup{'' if n == 1 else 's'} "
                 "an hour at most")
            return await self._clean(gen, instructions + NOT_NOW)
        try:
            await self._notify(task)
            _log(f"Looking it up for {self.who}: {task}")
            from app.utils.web import agent, browser
            session = await browser.session()
            try:
                found = await agent.research(task, about=self.about, session=session,
                                             on_step=lambda kind, text: _log(text))
            finally:
                await browser.release(session)
        except Exception as e:
            _log(f"The lookup for {self.who} failed: {type(e).__name__}: {e}")
            found = None
        finally:
            _busy.discard(self.conv)
        await self._notify("")                    # done looking: the chat says it is writing again
        if not found or not found.answer:
            _log(f"Found nothing for {self.who}: {task}")
            return await self._clean(gen, instructions + COULD_NOT)
        self.found = found
        _log(f"Found it for {self.who} in {found.seconds:.0f}s: {found.answer[:160]}")
        self._show(found)
        return await self._clean(gen, instructions + found_block(found, s["share_links"]))

    @staticmethod
    async def _ask(gen, instructions: str) -> str:
        """The caller's model call. A gpt-oss model sometimes calls the browser it was trained with instead of
        writing LOOKUP, and Groq refuses the call (tool_use_failed): the search it wanted is taken as the LOOKUP."""
        try:
            return await gen(instructions)
        except Exception as e:
            from app.utils.ai import tool_attempt
            from app.utils.web.agent import parse_action
            action = parse_action(tool_attempt(e))
            if action and action.get("do") == "search" and action.get("q"):
                return f"LOOKUP: {action['q']}"
            raise

    async def _clean(self, gen, instructions: str) -> str:
        text = await self._ask(gen, instructions)
        if not marker(text):
            return text
        cleaned = strip(text)
        if cleaned:
            return cleaned
        # Asked to look again although it was told not to: once more, plainly.
        return strip(await self._ask(gen, instructions + NOT_NOW))

    async def _notify(self, task: str):
        if not self.on_lookup:
            return
        try:
            result = self.on_lookup(task)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, 5.0)
        except Exception:
            pass

    @staticmethod
    def _show(found):
        """In the panel's Logs (and Big Picture): what was found, where, and how, folded like a model's thinking."""
        try:
            from app.utils.logger import log_thinking
            body = [f"Looked up: {found.task}", "", found.answer]
            if found.sources:
                body += ["", "Sources:"] + [f"- {s.get('title')}: {s.get('url')}" for s in found.sources]
            if found.steps:
                body += ["", "How:"] + [f"- {s}" for s in found.steps]
            log_thinking("\n".join(body), "Web")
        except Exception:
            pass
