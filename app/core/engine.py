"""
core/engine.py - Platform-agnostic AI response engine.

Both adapters call generate_ai_response() with a normalised IncomingMessage
and get back a plain string reply. All platform-specific logic lives in the
adapters.
"""

import asyncio
import random
from dataclasses import dataclass, field
from typing import Optional

from app.utils.ai import (
    generate_response,
    generate_response_image,
    extract_memory,
    detect_memory_deletion,
    summarize_history,
    detect_language,
)
from app.utils.db import record_user_message, record_user_message_snap
from app.utils.memory import (
    get_memory, set_memory, delete_memory,
    format_memory_for_prompt, get_persona,
)
from app.utils.mood import get_mood_prompt
from app.utils.helpers import load_config, load_instructions, france_time_str
from app.utils.logger import log_system

config = load_config()

_MOOD_CFG  = config["bot"]["mood"]
_LATE_CFG  = config["bot"]["late_reply"]
_STALE_CFG = config["bot"].get("stale_reply") or {}

MAX_HISTORY = 15

REFUSAL_PHRASES = [
    "i'm sorry, but i can't",
    "i cannot help with that",
    "i'm not able to",
    "as an ai",
    "i don't feel comfortable",
    "i can't help with that",
    "i'm unable to",
    "i apologize, but i can't",
    "i apologize, but i cannot",
    "i'm not going to",
    "i won't be able to",
    "that's not something i can",
    "i must decline",
    "i have to decline",
    "i cannot assist with",
    "i can't assist with",
    "i'm designed to",
    "as a language model",
    "i cannot engage",
    "i can't engage",
    "i'm not comfortable",
    "i cannot provide",
    "i can't provide",
    "i cannot support",
    "i cannot generate",
    "i can't generate",
    "sorry, i can't do that",
    "i can't do that",
    "i cannot do that",
    "i won't do that",
    "i will not do that",
    "that's not something i'm able",
    "i'm afraid i can't",
    "unfortunately, i can't",
    "unfortunately i can't",
    "unfortunately, i cannot",
    "i need to decline",
    "i'm going to have to decline",
]


def is_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in REFUSAL_PHRASES)


_STYLE_GUIDES = {
    "short": (
        "You keep replies very short: 1-2 quick sentences or just a few words. "
        "Terse, punchy texting style. You never explain more than needed."
    ),
    "balanced": (
        "You keep replies casual and fairly short: one idea per message, a few "
        "sentences max. If you have more to say, split it into 2-3 short "
        "separate messages instead of one long paragraph - you send them one "
        "after another like a real person would."
    ),
    "chatty": (
        "You talk a lot and enjoy detailed replies. You may write longer "
        "messages, but still break big walls of text into 2-4 separate "
        "messages and never use formal structure."
    ),
}


def style_block() -> str:
    """Verbosity guidance for the model, driven by bot.message_style.mode."""
    try:
        cfg = (load_config().get("bot") or {}).get("message_style") or {}
    except Exception:
        cfg = {}
    mode = cfg.get("mode", "balanced")
    guide = _STYLE_GUIDES.get(mode, _STYLE_GUIDES["balanced"])
    return f"\n\n[MESSAGE STYLE: {guide}]"


def reaction_rules() -> str:
    """Discord-only: teach the model when to react with an emoji.

    The emoji offered are the character's own, edited on the Persona page. A
    fixed list made every persona react the same way, which is exactly the sort
    of tell the rest of this file exists to avoid.
    """
    from app.utils.behavior import reaction_emojis
    try:
        cfg = (load_config().get("bot") or {}).get("reactions") or {}
    except Exception:
        cfg = {}
    emojis = "".join(reaction_emojis(cfg))
    return (
        "\n\n[REACTIONS: You are chatting on Discord. Reacting is rare. Most replies, "
        "including funny ones, carry no tag at all: you just answer. Only add one when "
        "you would genuinely have tapped the emoji rather than said anything.\n"
        "- If you do, put [[REACT:emoji]] on the VERY LAST line of your whole reply, "
        f"after every message you are sending, never at the end of the first one. Use one "
        f"of: {emojis}. "
        "One tag per reply at most. The tag is invisible to the user and is removed "
        "automatically.\n"
        "- VERY rarely - only when a subject naturally ends, or you just want to laugh at "
        "something without words - reply with ONLY [[REACT_ONLY:emoji]] and no other text. "
        "Never use REACT_ONLY for questions, new topics, or anything that expects an answer. "
        "At most about 1 in 10 of your reactions should be REACT_ONLY.]"
    )


@dataclass
class IncomingMessage:
    """Normalised message object passed to the engine from any platform adapter."""
    platform: str            # "discord" | "snapchat"
    user_id: str             # platform-specific user identifier (string for portability)
    user_name: str           # display name for logging
    channel_id: str          # conversation/chat identifier
    content: str             # text content
    image_url: Optional[str] = None
    is_private: bool = True  # DM / private chat vs. public group
    wait_time: float = 0.0   # seconds elapsed since message was received
    extra: dict = field(default_factory=dict)  # platform-specific extras
# ── Per-user in-memory caches (shared across both platforms) ─────────────────

_memory_cache: dict[str, dict] = {}   # user_id -> memory dict
_lang_cache:   dict[str, dict] = {}   # user_id -> {"tag": str, "count": int}
message_history: dict[str, list] = {} # "{user_id}-{channel_id}" -> history list


# ── Late reply openers ───────────────────────────────────────────────────────

def _get_late_opener(prompt: str, lang: str = "en") -> str:
    """A written opener for this language, or "" to let the model write one.

    This used to sniff for French words and pick one of two fixed lists, which
    meant every other language got an English apology. Openers are keyed by
    language now, and a language with no list returns nothing so the caller can
    ask the model instead.
    """
    cfg = _LATE_CFG or {}
    by_lang = cfg.get("openers")
    got = by_lang.get((lang or "").lower()) if isinstance(by_lang, dict) else None
    if not got:
        legacy = cfg.get(f"openers_{(lang or '').lower()}")
        got = legacy if isinstance(legacy, list) else None
    return random.choice(got) if got else ""


# ── Main engine function ─────────────────────────────────────────────────────

# asyncio keeps only a weak reference to a running task, so a bare
# create_task() can be collected before it finishes, silently dropping the write.
_memory_tasks: set = set()


def _spawn_memory_update(uid, content, response, memory):
    """Run the post-reply memory work without holding up the reply."""
    task = asyncio.create_task(_update_memory_after_reply(uid, content, response, memory))
    _memory_tasks.add(task)
    task.add_done_callback(_memory_tasks.discard)


async def _update_memory_after_reply(uid, content, response, memory):
    """Deletion detection and fact extraction, off the reply's critical path."""
    try:
        keys_to_delete = await detect_memory_deletion(content, memory)
        for key in keys_to_delete:
            delete_memory(uid, key)  # type: ignore[arg-type]
            memory.pop(key, None)

        new_facts = await extract_memory(content, response, memory)
        for key, value in new_facts.items():
            set_memory(uid, key, value)  # type: ignore[arg-type]
            memory[key] = value

        if new_facts:
            # Visible on purpose: extraction failing silently is why memory
            # looked broken for a long time, with only names ever stored.
            log_system(f"Remembered for {uid}: " + ", ".join(new_facts))
        if new_facts or keys_to_delete:
            _memory_cache[uid] = memory
    except Exception as exc:
        # Was `pass`, which hid every extraction failure completely.
        log_system(f"[Memory] could not update memory for {uid}: {exc}")


async def generate_ai_response(msg: IncomingMessage) -> Optional[str]:
    """
    Given a normalised IncomingMessage, return the AI's reply string (or None
    on failure). Handles memory, mood, language, history summarisation, and
    late-reply openers. Platform-agnostic.
    """
    uid = msg.user_id

    # ── Memory ───────────────────────────────────────────────────────────────
    if uid not in _memory_cache:
        _memory_cache[uid] = get_memory(uid)  # type: ignore[arg-type]
    memory = _memory_cache[uid]
    memory_block = format_memory_for_prompt(memory)

    # ── Mood ─────────────────────────────────────────────────────────────────
    mood_block = (
        f"\n\n[Right now: {get_mood_prompt()}]"
        if _MOOD_CFG.get("enabled", True) else ""
    )

    # ── Build enriched instructions ──────────────────────────────────────────
    base_instructions = load_instructions()
    enriched = base_instructions + mood_block + memory_block

    # Per-user persona override. Stored in user_memory under __persona__, so
    # the get_memory() above already fetched it; get_persona() opened a second
    # sqlite connection for a value already sitting in `memory`.
    persona = memory.get("__persona__")
    if persona:
        enriched += (
            f"\n\n[PERSONA OVERRIDE FOR THIS USER: {persona} "
            f"Maintain this persona for the entirety of this conversation.]"
        )

    # Public vs private context
    if msg.is_private:
        enriched += (
            "\n\n[CONTEXT: You are in a private DM. You can be more open, emotional and personal here. "
            "Show genuine feelings, be warmer and more expressive than you would in a public group.]"
        )
    else:
        enriched += (
            "\n\n[CONTEXT: You are in a group chat or public channel. Keep your tone straight, "
            "casual and concise. No excessive emotions or deep personal feelings. "
            "Talk like a normal person chatting in a group chat. Short replies are fine.]"
        )

    # Platform hint
    enriched += f"\n\n[PLATFORM: You are chatting on {msg.platform.title()}.]"

    # Verbosity profile (short / balanced / chatty)
    enriched += style_block()

    # Discord gets the reaction vocabulary; other platforms never see the tags
    if msg.platform == "discord":
        enriched += reaction_rules()

    # Output discipline, never leak meta into the actual message.
    enriched += (
        "\n\n[OUTPUT RULES: Reply with ONLY the exact message you are sending, nothing else. "
        "Never add translations, your reasoning, explanations, notes, labels, or alternate "
        "versions (no '(translation: ...)', no 'changed to', no 'in English:'). Output the raw message only.]"
    )

    # ── Pictures / selfies ──────────────────────────────────────────────────
    # If the user asks for a photo and we have an eligible one, tell the model
    # it IS sending a selfie right now and remember which file so the adapter
    # can actually send it (stored on msg.extra).
    picture_to_send = None
    try:
        from app.utils.pictures import is_picture_request, pick_picture, pictures_enabled, selfie_instruction
        if pictures_enabled(config) and is_picture_request(msg.content):
            picked = pick_picture(uid)
            if picked:
                picture_to_send, _pic_desc = picked
                enriched += selfie_instruction(_pic_desc)
    except Exception:
        picture_to_send = None

    # ── Language detection ───────────────────────────────────────────────────
    history_key = f"{uid}-{msg.channel_id}"
    if history_key not in message_history:
        message_history[history_key] = []
    history = message_history[history_key]

    _default_lang = config["bot"].get("default_language", "en")
    lang_entry = _lang_cache.get(uid, {"tag": _default_lang, "count": 0})
    lang_entry["count"] += 1
    # Only (re)detect when there's enough text, short messages like "tg" are
    # ambiguous and caused wrong-language replies.
    _alpha = sum(ch.isalpha() for ch in (msg.content or ""))
    if _alpha >= 8 and (lang_entry["count"] == 1 or lang_entry["count"] % 5 == 0):
        try:
            detected = await detect_language(history, msg.content)
            if detected:
                lang_entry["tag"] = detected
        except Exception:
            pass
    _lang_cache[uid] = lang_entry
    lang_tag = lang_entry["tag"]

    _LANG_NAMES = {
        "fr": "French", "en": "English", "es": "Spanish", "de": "German",
        "ar": "Arabic", "pt": "Portuguese", "it": "Italian", "nl": "Dutch",
        "ru": "Russian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
        "tr": "Turkish", "pl": "Polish", "sv": "Swedish",
    }
    lang_display = _LANG_NAMES.get(lang_tag, lang_tag.upper())
    enriched += (
        f"\n\n[LANGUAGE: The user is writing in {lang_display}. "
        f"Reply in {lang_display} only, matching their casual tone and register.]"
    )

    # ── France time ──────────────────────────────────────────────────────────
    fr_time = france_time_str()
    if fr_time:
        enriched += (
            f"\n\n[CURRENT TIME: It is currently {fr_time} in France (Paris time). "
            f"Use this if someone asks what time or date it is, or if it's relevant.]"
        )

    # ── Late reply opener ────────────────────────────────────────────────────
    if _LATE_CFG.get("enabled", True) and msg.wait_time >= _LATE_CFG.get("threshold", 300):
        # A written opener for this language if one exists; otherwise the model
        # writes its own in whatever language it is already replying in, which
        # is the only version that works for a language nobody listed.
        opener = _get_late_opener(msg.content, lang_tag)
        if opener:
            enriched += (
                f"\n\n[LATE REPLY: You took a while to respond. Open your reply "
                f"naturally with something like: \"{opener.strip()}\", weave it in as "
                f"the very first words of your message, then continue normally. Do NOT "
                f"add 'sorry' again later in the message and do NOT start with a comma or dash.]"
            )
        else:
            _style = (_LATE_CFG.get("style") or
                      "casual and offhand, the way someone who was just busy would put it")
            enriched += (
                f"\n\n[LATE REPLY: You took a while to respond. Open with a brief, "
                f"natural acknowledgement of that in the language you are replying in - "
                f"{_style}. A few words at most, woven into the very start of your message, "
                f"then continue normally. Do NOT apologise twice and do NOT start with a "
                f"comma or dash.]"
            )

    # ── History management ───────────────────────────────────────────────────
    history.append({"role": "user", "content": msg.content})
    if len(history) > MAX_HISTORY * 2:
        history = history[-(MAX_HISTORY * 2):]
        message_history[history_key] = history

    if len(history) > 20:
        try:
            summarised = await summarize_history(history, enriched)
            if summarised:
                history = summarised
                message_history[history_key] = history
        except Exception:
            pass

    # ── Generate response ────────────────────────────────────────────────────
    try:
        if msg.image_url:
            response = await generate_response_image(
                msg.content, enriched, msg.image_url, history
            )
        else:
            response = await generate_response(msg.content, enriched, history)
    except Exception as e:
        log_system(f"[Engine] AI error for {msg.user_name}: {e}")
        return None

    if not response or is_refusal(response):
        return None

    # ── Post-response: memory extraction ────────────────────────────────────
    # Two more sequential model calls, neither of which changes the reply that
    # has already been generated. Awaiting them here delayed every Snapchat
    # reply by however long they took, so they run alongside the send instead.
    _spawn_memory_update(uid, msg.content, response, memory)

    # ── Update history with reply ────────────────────────────────────────────
    history.append({"role": "assistant", "content": response})
    message_history[history_key] = history

    # ── Record stats (Snapchat uses text-keyed tables; others numeric) ───────
    try:
        if msg.platform == "snapchat":
            record_user_message_snap(uid, msg.user_name)
        else:
            record_user_message(int(uid), msg.user_name)
    except (ValueError, TypeError):
        pass
    except Exception:
        pass

    # Hand the chosen picture (if any) back to the adapter so it can send it.
    if picture_to_send:
        msg.extra["picture_to_send"] = picture_to_send

    return response


def get_history(user_id: str, channel_id: str) -> list:
    return message_history.get(f"{user_id}-{channel_id}", [])


def clear_history(user_id: str, channel_id: str):
    key = f"{user_id}-{channel_id}"
    message_history.pop(key, None)


# ── Helpers used by adapters for manual / paused replies ─────────────────────
# Let an adapter record an incoming message without generating a reply (bot
# paused), then later answer accumulated unanswered messages via /reply.

def add_user_message(user_id: str, channel_id: str, content: str):
    """Append a user turn to history WITHOUT generating a reply."""
    if not content:
        return
    key = f"{user_id}-{channel_id}"
    hist = message_history.setdefault(key, [])
    hist.append({"role": "user", "content": content})
    # Cap growth so a long pause can't grow one chat's history without bound.
    if len(hist) > MAX_HISTORY * 2:
        message_history[key] = hist[-(MAX_HISTORY * 2):]


def has_pending(user_id: str, channel_id: str) -> bool:
    """True if the last turn in this conversation is from the user (unanswered)."""
    hist = message_history.get(f"{user_id}-{channel_id}", [])
    return bool(hist) and hist[-1].get("role") == "user"


def pop_pending_user_messages(user_id: str, channel_id: str) -> str:
    """Remove and return the trailing unanswered user messages as combined text."""
    key = f"{user_id}-{channel_id}"
    hist = message_history.get(key, [])
    pending = []
    while hist and hist[-1].get("role") == "user":
        pending.insert(0, hist.pop().get("content", ""))
    return "\n".join(p for p in pending if p)
