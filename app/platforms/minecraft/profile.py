"""The mindcraft profile an account plays under: mindcraft's own defaults, with the app as its brain.

mindcraft builds every prompt it sends from the profile's templates, filling in what it knows about the game
($STATS, $INVENTORY, $COMMAND_DOCS, ...). The app takes those templates from mindcraft's own
profiles/defaults/_default.json at the time it runs, so upstream improvements to them come through, and changes only:

  * who the bot is. mindcraft's conversing prompt opens with "an AI Minecraft bot", "a friendly, casual, effective,
    and efficient robot": a character of its own, which would fight the persona for the whole conversation. That
    opening goes; the mechanical rules it carries (act with a command at once, speak only as yourself, nothing when
    there is nothing to do) stay. The character comes from the persona, in the engine. mindcraft's own asks for "a
    tab" there, and told that in words, a model wrote the word: "tab", out loud, in the game.
  * its examples. Twenty-nine example conversations in mindcraft's voice drag a reply towards that voice harder than
    any instruction drags it away, so conversation_examples is empty. coding_examples stay: they teach JavaScript,
    not a voice.
  * where it thinks. Every model key points at the app's own brain (brain.py), on its own loopback port, behind a
    token in the URL path. Through mindcraft's "lmstudio" provider, which was made for exactly this (an
    OpenAI-shaped server on this machine), chosen over the two that look closer: "vllm" passes the OpenAI client an
    empty key, which the client it ships with now refuses outright; and "openai" reformats the system prompt into
    a user message and reads its key from OPENAI_API_KEY, which other parts of mindcraft would then carry to
    api.openai.com. lmstudio keeps the system prompt a system prompt, and its key is a placeholder, so the path is
    where the secret goes.
  * its embeddings. Pointed at the brain too, which answers them itself (brain.embed_text). Left unset, mindcraft
    builds one from the chat provider with no address at all; and with no conversation examples to embed at
    start, nothing would fail early enough to fall back, so the first embed of a real conversation would throw and
    the bot would never answer.
  * a marker on each template, so the brain knows which of mindcraft's five kinds of request it is answering
    (brain.route): only a conversation goes through the persona.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.platforms.minecraft.install import MC_DIR
from app.utils.paths import DATA_DIR

PROFILES_DIR = DATA_DIR / "minecraft" / "profiles"

# Inert lines the brain reads to route a request, then removes before any model sees them.
MARKERS = {
    "conversing": "[[LSB:CONVERSE]]",
    "coding": "[[LSB:CODE]]",
    "saving_memory": "[[LSB:MEMORY]]",
    "bot_responder": "[[LSB:RESPONDER]]",
    "image_analysis": "[[LSB:VISION]]",
}

# The conversing prompt, with mindcraft's own character taken out and its mechanics kept. The placeholders are
# mindcraft's, filled in by mindcraft.
CONVERSING = (
    "You are playing Minecraft as $NAME, in the world with the people talking to you, and you act in it by writing "
    "the commands documented below. $SELF_PROMPT\n"
    "Use a command the moment one is asked for, rather than saying you will: not 'Sure, I've stopped. *stops*', "
    "but 'Sure, I'll stop. !stop'. Speak only as $NAME, never write '(FROM OTHER BOT)' and never speak for "
    "anyone else. When there is nothing to say and nothing to do, reply with nothing at all.\n"
    "Summarized memory:'$MEMORY'\n$STATS\n$INVENTORY\n$COMMAND_DOCS\n" + "$MENU_DOCS" + "\n$EXAMPLES\nConversation Begin:"
)

# A server's own menus (chests whose items are buttons), which mindcraft has no commands for: the app adds these
# (agent_hooks.mjs MENU_COMMANDS), and says so here in the words mindcraft's own docs use.
MENU_DOCS = (
    "*SERVER MENUS: many servers open menus (a chest whose items are buttons) from an item like a compass named "
    "'Server Selector', or a command like /settings. Your inventory lists items with the server's own names.\n"
    "!useItem: Hold the item with this name and right-click it, as a player opens a server's menus. Says what "
    "opened.\nParams:\nname: (string) Part of its name as the server shows it, or its kind.\n"
    "!menu: Look at the menu open on your screen: its title, and each slot's item.\n"
    "!clickMenuSlot: Click a slot in the open menu, by its number from !menu.\nParams:\nslot: (number) The slot "
    "number.\n"
    "!closeMenu: Close the menu that is open.\n"
    "!runCommand: Run a server command, without the slash: settings, spawn, warp shop. Never one that pays, sells, "
    "trades or gives.\nParams:\ncommand: (string) The command.\n"
    "Click nothing marked (spends money) unless your owner asked you to.*"
)
CONVERSING = CONVERSING.replace("$MENU_DOCS", MENU_DOCS)

# The keys mindcraft's own defaults must still have, or the profile built from them is not the one this was built
# against: said in the log rather than generating a broken profile in silence.
EXPECTED = ("conversing", "coding", "saving_memory", "bot_responder", "modes", "coding_examples")


def defaults(mc_dir: Path = MC_DIR) -> dict:
    """mindcraft's own profile defaults, as installed."""
    return json.loads((mc_dir / "profiles" / "defaults" / "_default.json").read_text(encoding="utf-8"))


def missing_keys(base: dict) -> list[str]:
    return [k for k in EXPECTED if k not in base]


def clean_name(name: str) -> str:
    """A Minecraft name: 3 to 16 letters, digits and underscores. Anything else is dropped, not guessed at."""
    n = re.sub(r"[^A-Za-z0-9_]", "", str(name or ""))[:16]
    return n if len(n) >= 3 else ""


def build(name: str, brain_url: str, *, base: dict | None = None, modes: dict | None = None,
          cooldown_ms: int | None = None) -> dict:
    """The profile for one account. `brain_url` is the brain's base URL with its token in the path,
    e.g. http://127.0.0.1:51234/v1/<token>; mindcraft's OpenAI client posts to <brain_url>/chat/completions."""
    base = dict(base if base is not None else defaults())
    who = clean_name(name)
    if not who:
        raise ValueError(f"not a Minecraft name: {name!r}")
    model = {"api": "lmstudio", "model": "llmselfbot", "url": brain_url}
    profile = {
        "name": who,
        "model": model,
        "code_model": model,
        "vision_model": model,
        "embedding": {"api": "lmstudio", "model": "llmselfbot-words", "url": brain_url},
        "conversing": MARKERS["conversing"] + CONVERSING,
        "conversation_examples": [],
    }
    for key in ("coding", "saving_memory", "bot_responder", "image_analysis"):
        if base.get(key):
            profile[key] = MARKERS[key] + str(base[key])
    if base.get("coding_examples"):
        profile["coding_examples"] = base["coding_examples"]
    profile["modes"] = {**(base.get("modes") or {}), **(modes or {})}
    # Never cheating: it plays the game as a player does.
    profile["modes"]["cheat"] = False
    if cooldown_ms is not None:
        profile["cooldown"] = int(cooldown_ms)
    elif base.get("cooldown") is not None:
        profile["cooldown"] = base["cooldown"]
    return profile


def write(account: int, profile: dict) -> Path:
    """Saved where a reinstall of mindcraft never reaches (DATA_DIR/minecraft/profiles), as mindcraft reads it."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"account_{int(account)}.json"
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
