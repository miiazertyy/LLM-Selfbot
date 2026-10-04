"""Telling running accounts that something they use changed.

A setting, a persona's text, someone's memory: written by the panel, read by
the accounts. Most of what a runner reads it reads again each time, but a
Discord runner holds a few things (its switches, timings read as it started,
its memory of each person) until told. This tells it, through its IPC file,
without waiting for the answer: the panel answers at once, and an account that
is mid-reply reads the message a moment later.
"""
import asyncio

# asyncio keeps only a weak reference to a running task: held here until done, or it can be collected first.
_tasks: set = set()


async def _send(target, cmd: str, payload: dict) -> None:
    from app.core import ipc
    try:
        await ipc.send_and_wait(target, cmd, payload, timeout=6.0)
    except Exception:
        pass


def running_accounts(request) -> set:
    """Web ids of the accounts that are up, or on their way up."""
    sup = getattr(getattr(request, "app", None), "state", None)
    sup = getattr(sup, "supervisor", None) if sup is not None else None
    if sup is None:
        return set()
    try:
        return set(sup.running_ids())
    except Exception:
        return set()


def push(request, cmd: str, payload: dict | None = None, persona: str | None = None,
         platforms=("discord", "snapchat")) -> list:
    """Send `cmd` to every running account on these platforms (only those speaking as `persona`, when one is named).
    Returns which were told. Fire and forget."""
    from app.core import ipc
    from app.utils import personas
    told = []
    for web_id in sorted(running_accounts(request)):
        if not any(web_id.startswith(p + "_") for p in platforms):
            continue
        if persona is not None and personas.persona_of(web_id) != persona:
            continue
        target = ipc.target_for(web_id)
        if target is None:
            continue
        told.append(web_id)
        try:
            task = asyncio.get_running_loop().create_task(_send(target, cmd, payload or {}))
        except RuntimeError:
            continue
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return told
