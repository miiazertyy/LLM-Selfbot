"""Who is in each voice channel of a Discord server, for the list of channels in the Chats tab.

Only looks. All of it is what the gateway has already told the account, the same thing Discord's own client draws in
its channel list, and nothing in here joins, leaves or changes a call.

A big server doesn't send its members up front, so someone in a call can be an id with no name yet. Those go in one
gateway query, the kind Discord's client sends when it draws a list of people: at most one for a server every
QUERY_EVERY seconds, never in careful mode, and an id that got no answer is left alone for NO_ANSWER_FOR seconds. The
panel says "Someone" until then. A query holds a hundred and a big server can have a thousand people in calls, so the
calls on the panel's screen go first, then the rest from the top of the list down.
"""
from __future__ import annotations

import asyncio
import time

from app.utils.stealth import quiet

# Listed per channel: a stage can hold thousands, and the count still says how many.
MOST = 100
QUERY_EVERY = 10.0
NO_ANSWER_FOR = 600.0
# How long the answer to a query is waited for. It goes on behind the panel's answer, so nothing waits on it.
PATIENCE = 6.0

_asked_at: dict[int, float] = {}
_no_answer: dict[int, float] = {}
_asking: set[int] = set()


def _face(who) -> str:
    """Their picture at a small size: the list draws it at 20px, and the full one is what made pictures slow."""
    asset = getattr(who, "display_avatar", None)
    if asset is None:
        return ""
    try:
        return str(asset.replace(size=64).url)
    except Exception:
        return str(getattr(asset, "url", "") or "")


def _person(uid: int, state, who) -> dict:
    on = lambda name: bool(getattr(state, name, False))  # noqa: E731
    return {
        "id": str(uid),
        "name": str(getattr(who, "display_name", "") or getattr(who, "name", "") or ""),
        "avatar": _face(who),
        # A stage's audience (suppressed) can't speak either, so it reads the same.
        "muted": on("self_mute") or on("mute") or on("suppress"),
        "deaf": on("self_deaf") or on("deaf"),
        "live": on("self_stream"),
        "video": on("self_video"),
    }


def _place(ch, first: set[str]) -> tuple:
    """Where a channel comes when asking for names: on the panel's screen, then as the list has them."""
    cat = getattr(ch, "category", None)
    return (str(ch.id) not in first, getattr(cat, "position", -1) if cat is not None else -1, getattr(ch, "position", 0))


def roster(guild, client=None, first=()) -> tuple[dict, list[int]]:
    """{channel id: {"count", "people"}} for the voice channels with someone in them that the account may see, and the
    ids of those it has no name for yet, the ones in the `first` channels at the front. Touches nothing outside the
    library's cache."""
    mine = getattr(guild, "me", None)
    channels: dict[str, dict] = {}
    unnamed: list[int] = []
    looking = {str(c) for c in first}
    occupied = [(ch, states) for ch in list(guild.channels) if (states := getattr(ch, "voice_states", None))]
    occupied.sort(key=lambda pair: _place(pair[0], looking))
    for ch, states in occupied:
        perms = ch.permissions_for(mine) if mine is not None else None
        if perms is not None and not perms.read_messages:
            continue
        people = []
        for uid, state in list(states.items()):
            who = guild.get_member(uid) or (client.get_user(uid) if client is not None else None)
            person = _person(uid, state, who)
            if not person["name"]:
                unnamed.append(uid)
            people.append(person)
        # The same order every time, so nobody swaps places between one look and the next.
        people.sort(key=lambda p: (not p["name"], p["name"].casefold(), p["id"]))
        channels[str(ch.id)] = {"count": len(people), "people": people[:MOST]}
    return channels, unnamed


async def learn_names(guild, ids: list[int]) -> None:
    """Asks the gateway who these are. The library keeps the answer, so the next look at the roster has their names."""
    gid = guild.id
    now = time.monotonic()
    if not ids or gid in _asking or now - _asked_at.get(gid, -QUERY_EVERY) < QUERY_EVERY:
        return
    _asked_at[gid] = now
    if quiet():
        return
    for uid in [u for u, at in _no_answer.items() if now - at >= NO_ANSWER_FOR]:
        del _no_answer[uid]
    # 100 is the most the query takes, and 5 the least it takes as a limit.
    ask = [u for u in dict.fromkeys(ids) if u not in _no_answer][:100]
    if not ask:
        return
    _asking.add(gid)
    found: set[int] = set()
    try:
        got = await asyncio.wait_for(
            guild.query_members(user_ids=ask, limit=max(5, len(ask)), presences=False, cache=True), PATIENCE)
        found = {m.id for m in got}
    except Exception:
        pass  # no answer, or none in time: they stay "Someone"
    finally:
        _asking.discard(gid)
    for uid in ask:
        if uid not in found:
            _no_answer[uid] = now
