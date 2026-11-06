"""Minecraft from wherever a persona talks: asked on Discord, Snapchat, TikTok, Instagram or in the game itself to come
play on a server, the persona can say yes, and its Minecraft account goes there.

The engine (engine.py) adds rule_for()'s few lines to a reply's instructions when the persona has a Minecraft account
and the message is about playing somewhere; the persona, agreeing, ends its reply with [MC JOIN <address>];
take_tags() takes that out before anyone sees it, and dispatch() asks the persona's Minecraft account to go, as the
panel or Telegram would (the bridge's mc_join_server, which checks Settings and tells the owner).
"""
from __future__ import annotations

import re

TAG_RE = re.compile(r"\s*\[\s*MC\s+JOIN\s+([^\]\n]{1,80}?)\s*\]\s*", re.I)
# Asked to "come play", "join", "hop on" somewhere, or a server named: worth the rule's few lines. Anything else is
# not, and pays nothing for it.
_ABOUT_RE = re.compile(r"minecraft|\bmc\b|\bserv(?:er|eur)\b|hypixel|2b2t|\bjoin\b|rejoin|hop on|come play|"
                       r"viens jouer|on joue|let'?s play|play with|jouer avec|\b[a-z0-9-]+\.(?:net|com|org|gg|fr|io|me|club)\b",
                       re.I)
# Big servers people name without an address.
WELL_KNOWN = {
    "hypixel": "mc.hypixel.net", "2b2t": "2b2t.org", "cubecraft": "play.cubecraft.net",
    "wynncraft": "play.wynncraft.com", "minemen": "minemen.club", "mineplex": "us.mineplex.com",
}


def _minecraft_accounts() -> list[str]:
    try:
        from app.core import ipc
        return [f"minecraft_{i}" for i in range(1, ipc._count_minecraft_accounts() + 1)]
    except Exception:
        return []


def accounts_for(persona_id: str) -> list[str]:
    """The Minecraft accounts that speak as this persona."""
    from app.utils import personas
    return [w for w in _minecraft_accounts() if personas.persona_of(w) == persona_id]


def _settings() -> dict:
    from app.platforms.minecraft import worker
    from app.utils.helpers import load_config
    try:
        return worker.section(load_config() or {})
    except BaseException:
        # load_config ends the process when there is no config.yaml at all: never from inside a reply.
        return worker.section({})


def _persona_here() -> str:
    from app.utils import personas
    return personas.persona_of(personas.current_account() or "")


def _auth_of(account: str, mc: dict) -> str:
    from app.platforms.minecraft import worker
    try:
        return worker.slot(int(account.rsplit("_", 1)[1]), mc)["auth"]
    except Exception:
        return "offline"


def rule_for(msg) -> str:
    """The lines a reply's instructions get when this persona plays Minecraft and the message is about playing
    somewhere; "" otherwise."""
    try:
        if not _ABOUT_RE.search(str(getattr(msg, "content", "") or "")):
            return ""
        mc = _settings()
        if not mc.get("enabled", True) or not mc.get("join_when_asked", True):
            return ""
        accounts = accounts_for(_persona_here())
        if not accounts:
            return ""
        offline = not any(_auth_of(a, mc) == "microsoft" for a in accounts)
    except Exception:
        return ""
    rule = ("\n\n[MINECRAFT: You also play Minecraft. If they ask you to come play on a Minecraft server and you "
            "want to go, end your reply with [MC JOIN address]: the server's address as they wrote it (like "
            "play.example.net), or a big one by its name (like hypixel). Only an address or name they actually "
            "gave you; never make one up, and only when you are going.")
    if offline:
        # The bridge refuses those anyway (worker.needs_microsoft): better the persona says no than "omw" and stays.
        rule += (" Your Minecraft account is a cracked (offline) one: Hypixel and the other big servers that need a "
                 "real account will not let you in, so say no to those.")
    return rule + "]"


def address_of(text: str) -> str:
    """The address an [MC JOIN ...] names: a big server's by its name, otherwise as written."""
    t = str(text or "").strip().strip("\"'`<>").lower()
    return WELL_KNOWN.get(t.replace(" ", ""), t)


def take_tags(text: str) -> tuple[str, list[str]]:
    """(the reply without its [MC JOIN ...], the addresses they named, first first)."""
    found = [address_of(m.group(1)) for m in TAG_RE.finditer(text or "")]
    if not found:
        return text, []
    return TAG_RE.sub(" ", text).strip(), found


def dispatch(addresses: list[str], msg) -> bool:
    """Asks the persona's Minecraft account to go to the first address: the one running if there is one, else the
    first. Queued as the panel's commands are; the bridge does the rest (and refuses what Settings rules out)."""
    if not addresses:
        return False
    try:
        from app.core import ipc
        accounts = accounts_for(_persona_here())
        if not accounts:
            return False
        target = ipc.target_for(accounts[0])
        if target is None:
            return False
        ipc.send_command(target, "mc_join_server", {
            "address": addresses[0], "asked_by": str(getattr(msg, "user_name", "") or ""),
            "platform": str(getattr(msg, "platform", "") or ""),
        })
        return True
    except Exception:
        return False
