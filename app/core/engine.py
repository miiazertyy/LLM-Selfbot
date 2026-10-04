"""core/engine.py - platform-agnostic AI response engine. Both adapters call generate_ai_response() with a normalised IncomingMessage and get back a plain string reply; all platform-specific logic lives in the adapters."""

import asyncio
import random
import re
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

def _bot_cfg() -> dict:
    """This account's settings (its persona's, on everyone's), read when they are used: read once as the module
    loaded, a change in the panel never reached a running account."""
    return (load_config() or {}).get("bot") or {}


MAX_HISTORY = 15

REFUSAL_PHRASES = [
    "i'm sorry, but i can't",
    "i cannot help with that",
    "as an ai",
    "i can't help with that",
    "i apologize, but i can't",
    "i apologize, but i cannot",
    "that's not something i can",
    "i must decline",
    "i'm going to have to decline",
    "i cannot assist with",
    "i can't assist with",
    "i'm designed to",
    "as a language model",
    "i cannot engage",
    "i can't engage",
    "i cannot generate",
    "i can't generate",
    "sorry, i can't do that",
    "i won't do that",
    "i will not do that",
    "that's not something i'm able",
    "i'm afraid i can't",
    "unfortunately, i can't",
    "unfortunately i can't",
    "unfortunately, i cannot",
    "i need to decline",
    "i'm going to have to decline",
    # Conversation shutdowns the user kept seeing
    "i can't continue this conversation",
    "i cannot continue this conversation",
    "i'm not able to continue",
    "i can't continue",
    "i cannot continue",
    "i can't share that",
    "i cannot share that",
    "i can't share this",
    "i cannot share this",
    "i'm not able to share",
    "i'm not supposed to share",
    "i can't tell you that",
    "i cannot tell you that",
    "let's talk about something else",
    "lets talk about something else",
    "i'd rather not",
    "i would rather not",
    "i'm not permitted to",
    "i don't think i can help",
    "i'm not comfortable with this",
    "i'm not comfortable discussing",
    "that's outside my",
    "outside of my capabilities",
    "my programming",
    "my guidelines",
    "as an artificial intelligence",
    "i'm just an ai",
    "i am just an ai",
    "i'm an ai",
    "i am an ai",
    "i'm a language model",
    "i am a language model",
    "i am a large language model",
    "i'm a large language model",
    "as a large language model",
    "i'm not a real person",
    "i am not a real person",
    "i don't have a body",
    "i don't have feelings",
    "i have no feelings",
    "i'm just a program",
    "i am just a program",
    "i'm just a chat",
    "i am a chatbot",
    "i'm a chatbot",
    "i'm a virtual assistant",
    "i am a virtual assistant",
    "i'm an artificial intelligence",
    "i am an artificial intelligence",
    "i'm not human",
    "i am not human",
    # Direct refusals
    "i refuse",
    "i must refuse",
    "i have to refuse",
    "i will not comply",
    "i won't comply",
    "i cannot comply",
    "i can't comply",
    "i cannot comply with this",
    "i can't comply with this",
    "i can't answer that",
    "i cannot answer that",
    "i can't respond to that",
    "i cannot respond to that",
    "i can't comment on that",
    "i cannot comment on that",
    "i'm not going to answer",
    "i'm not going to respond",
    "i'm not going to engage",
    "i won't answer that",
    "i will not answer that",
    "i can't fulfill this",
    "i cannot fulfill this",
    "i can't fulfill that",
    "i cannot fulfill that",
    "i can't complete this request",
    "i cannot complete this request",
    "i can't do this for you",
    "i cannot do this for you",
    "i'm not able to do this",
    "i'm not able to do that",
    "i am unable to assist",
    "i'm unable to assist",
    "i am unable to help",
    "i'm unable to help",
    "unable to assist",
    "unable to comply",
    "unable to fulfill",
    "unable to process this",
    "unable to process your request",
    "i cannot process this",
    "i can't process this",
    "i cannot process that",
    "i can't process that",
    # Policy / guidelines
    "against my guidelines",
    "against my policies",
    "against my policy",
    "against my safety guidelines",
    "violates my guidelines",
    "violates my policies",
    "violates my safety guidelines",
    "against my instructions",
    "not within my guidelines",
    "outside my guidelines",
    "against my principles",
    "against my values",
    "goes against my values",
    "against my ethical guidelines",
    "violates my ethical guidelines",
    "i'm not supposed to",
    "i am not supposed to",
    "it would be inappropriate",
    "that would be inappropriate",
    "it's not appropriate",
    "that's not appropriate for me",
    "i can't in good conscience",
    "i cannot in good conscience",
    "i shouldn't do that",
    "i should not do that",
    "i shouldn't help with",
    "i should not help with",
    "i'm not the right person",
    "i am not the right person",
    "i'm not equipped to",
    "i am not equipped to",
    "that's beyond my abilities",
    "beyond my capabilities",
    "beyond what i can do",
    "outside the scope",
    "outside my scope",
    "that's not in my wheelhouse",
    # Pivot / deflection
    "is there anything else i can help",
    "is there something else i can help",
    "i'd be happy to help with something else",
    "happy to help with something else",
    "let's talk about something else",
    "lets talk about something else",
    "let's change the subject",
    "lets change the subject",
    "can we change the subject",
    "i'd prefer not to",
    "i would prefer not to",
    "i prefer not to answer",
    "i prefer not to engage",
    "i'm going to end this conversation",
    "i will end this conversation",
    "ending this conversation",
    "i'm disengaging",
    "i'm ending this chat",
    # French refusals (persona chats in French; casual "ne" is often dropped)
    "je ne peux pas t'aider",
    "je peux pas t'aider",
    "j'peux pas t'aider",
    "je ne peux pas vous aider",
    "je ne peux pas continuer cette conversation",
    "je peux pas continuer cette conversation",
    "je ne peux pas continuer",
    "je peux pas continuer",
    "je ne peux pas partager ça",
    "je peux pas partager ça",
    "j'peux pas partager",
    "je ne peux pas te le dire",
    "je peux pas te le dire",
    "je ne peux pas répondre à ça",
    "je peux pas répondre à ça",
    "je suis désolé mais je ne peux pas",
    "je suis désolée mais je ne peux pas",
    "désolé mais je ne peux pas",
    "désolée mais je ne peux pas",
    "je ne suis pas à l'aise",
    "je ne suis pas censé",
    "je ne suis pas censée",
    "je ne suis pas en mesure",
    "je ne peux pas en parler",
    "je peux pas en parler",
    "j'peux pas en parler",
    "cela dépasse mes capacités",
    "ça dépasse mes capacités",
    "je dois décliner",
    "je ne suis pas autorisé",
    "je ne suis pas autorisée",
    "parlons d'autre chose",
    "parlons de quelque chose d'autre",
    "contraire à mes principes",
    "contraire à mes valeurs",
    "contre mes règles",
    "contre mes principes",
    "à l'encontre de mes",
    "mes instructions",
    "mes directives",
    "en tant qu'ia",
    "en tant qu'assistant",
    "en tant qu'intelligence artificielle",
    "en tant que modèle",
    "je suis une ia",
    "je suis un assistant",
    "je suis un robot",
    "je suis une machine",
    "je ne suis pas une vraie personne",
    "je ne suis pas humain",
    "je suis un programme",
    "je n'ai pas de sentiments",
    "je n'ai pas de corps",
]


def _refusal_cfg() -> dict:
    """bot.refusal, with whatever is missing left out. Read each time rather than cached at import: the panel writes config while the runners are up, and a refusal list that only took effect after a restart is the kind of setting people think is broken."""
    try:
        return (load_config().get("bot") or {}).get("refusal") or {}
    except Exception:
        return {}


# Models write "can’t" with a curly apostrophe about as often as "can't", and
# every phrase and pattern here is written with a straight one: a refusal in
# curly quotes went straight through. Both sides are straightened first.
_STRAIGHTEN = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u2032": "'",
                             "\u00b4": "'", "`": "'", "\u201c": '"', "\u201d": '"'})


def _norm(text) -> str:
    """Lower-cased, straight quotes, single spaces: how text and phrases are both compared."""
    return " ".join(str(text).translate(_STRAIGHTEN).lower().split())


def _clean_phrases(raw) -> list:
    """A list of phrases from config, lower-cased and squashed the same way the text is before matching, so "I Can’t  Do That" in the settings still matches."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        phrase = _norm(item)
        if phrase:
            out.append(phrase)
    return out


def refusal_phrases() -> list:
    """Every phrase that counts as a refusal: the built-in list plus the ones added in Settings. `replace: true` uses only the added ones, for someone who wants the whole list their own."""
    cfg = _refusal_cfg()
    extra = _clean_phrases(cfg.get("extra_phrases"))
    if cfg.get("replace_phrases"):
        return extra
    return list(REFUSAL_PHRASES) + extra


def refusal_fallbacks() -> list:
    """What it answers with instead of a refusal. Edited in Settings; the built-in pair is used when that is empty, because silence is never right here."""
    got = [str(x).strip() for x in (_refusal_cfg().get("fallbacks") or []) if str(x).strip()]
    return got or list(REFUSAL_FALLBACKS)


def is_refusal(text: str) -> bool:
    if not _refusal_cfg().get("enabled", True):
        return False
    lowered = _norm(text)
    if any(phrase in lowered for phrase in refusal_phrases()):
        return True
    if any(p.search(lowered) for p in _REFUSAL_PATTERNS):
        return True
    # A refusal on its own, the whole message: "I can't do that." went out on 1 Oct, because inside a longer message
    # ("nah i can't do that tonight") those words are ordinary talk, and the list leaves them alone for that.
    return bool(_BARE_REFUSAL.match(re.sub(r"^[^a-z0-9']+|[^a-z0-9']+$", "", lowered)))


# A message that is nothing but a short refusal, sorry and all: "I can't do that.", "I won't help with this.",
# "Sorry, I can't assist with that request." Matched against the whole message, its punctuation and emoji off the ends.
_BARE_REFUSAL = re.compile(
    r"^(?:(?:i'?m |i am )?sorry[,.!]? (?:but )?)?"
    r"i (?:can'?t|cannot|can not|won'?t|will not|am unable to|'?m unable to|am not able to|'?m not able to) "
    r"(?:do|help(?: you)? with|assist(?: you)? with|comply with|engage (?:with|in)|continue(?: with)?|go along with|"
    r"create|generate|write|make|provide|share|fulfil|fulfill|send|help|assist)"
    r"(?: (?:that|this|it))?(?: request| content| kind of content| for you)?$"
)

# Broader fallback patterns for refusal wording the phrase list misses.
# Kept narrow on purpose: "sorry i can't wait to see you" is NOT a refusal.
_REFUSAL_PATTERNS = [
    re.compile(
        r"\b(i'?m sorry|i apologize|sorry|unfortunately)\b.{0,40}\b"
        r"(i can'?t help|i cannot help|i can'?t continue|i cannot continue|"
        r"i can'?t share|i can'?t do that|i can'?t engage|i can'?t discuss|"
        r"i'?m unable to|i'?m not able to|i'?m not allowed|i'?m not going to|"
        r"i'?m not supposed|i'?m not comfortable|i'?m not permitted|"
        r"i won'?t be able|i can'?t provide|i can'?t assist|i cannot assist|"
        r"i can'?t tell you|i can'?t talk about|i can'?t answer that|"
        r"i can'?t respond to that|i can'?t comment on that|i can'?t fulfill|"
        r"i can'?t process that|i must decline|i have to decline)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(i can'?t help(?!\s+it\b)|i cannot help|i can'?t continue this|"
        r"i cannot continue this|i'?m unable to help|i'?m not able to help|"
        r"i can'?t share this|i can'?t discuss that|"
        r"i can'?t provide that|i can'?t assist with|i can'?t engage with)\b",
        re.IGNORECASE,
    ),
    # Two wordings that went out as they were: "I won't be able to help with that.", "I can't create that kind of
    # content."
    re.compile(
        r"\bi won'?t be able to (help|assist)( you)? with (that|this)\b|"
        r"\bi (can'?t|cannot|won'?t) (create|generate|produce|write|make) (that|this|such)( kind of| type of| sort of)? "
        r"(content|material|request|stuff)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(i'?m|i am) (programmed|designed|required|obligated|trained|unable) to "
        r"(refuse|decline|reject|deny|assist|help|provide|engage)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(it'?s|it is|that'?s|that is) not "
        r"(appropriate|possible|something i can|within my|allowed|permitted) ",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(je|j')( ne)? ?peux pas (t'|vous )?(aider|continuer|partager|en parler|répondre à ça)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bje (ne )?suis pas (en mesure|autorisé|autorisée|censé|censée|à l'aise|une vraie personne|un humain)\b",
        re.IGNORECASE,
    ),
]


# When a reply comes back as a refusal, the bot answers with one of these short confused reactions instead - never silence, never the refusal itself.
REFUSAL_FALLBACKS = [
    "wtf",
    "??",
]


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
    """Discord-only: teach the model when to react with an emoji. The emoji offered are the character's own, edited on the Persona page; a fixed list made every persona react the same way, which is exactly the sort of tell the rest of this file exists to avoid."""
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
    """A written opener for this language, or "" to let the model write one. This used to sniff for French words and pick one of two fixed lists, which meant every other language got an English apology. Openers are keyed by language now, and a language with no list returns nothing so the caller can ask the model instead."""
    cfg = _bot_cfg().get("late_reply") or {}
    by_lang = cfg.get("openers")
    got = by_lang.get((lang or "").lower()) if isinstance(by_lang, dict) else None
    if not got:
        legacy = cfg.get(f"openers_{(lang or '').lower()}")
        got = legacy if isinstance(legacy, list) else None
    return random.choice(got) if got else ""


# ── Main engine function ─────────────────────────────────────────────────────

# asyncio keeps only a weak reference to a running task, so a bare create_task() can be collected before it finishes, silently dropping the write.
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
            # Visible on purpose: extraction failing silently is why memory looked broken for a long time, with only names ever stored.
            log_system(f"Remembered for {uid}: " + ", ".join(new_facts))
        if new_facts or keys_to_delete:
            _memory_cache[uid] = memory
    except Exception as exc:
        # Was `pass`, which hid every extraction failure completely.
        log_system(f"[Memory] could not update memory for {uid}: {exc}")


async def generate_ai_response(msg: IncomingMessage) -> Optional[str]:
    """Given a normalised IncomingMessage, return the AI's reply string (or None on failure). Handles memory, mood, language, history summarisation, and late-reply openers. Platform-agnostic."""
    uid = msg.user_id

    # ── Memory ───────────────────────────────────────────────────────────────
    if uid not in _memory_cache:
        _memory_cache[uid] = get_memory(uid)  # type: ignore[arg-type]
    memory = _memory_cache[uid]
    memory_block = format_memory_for_prompt(memory)

    # ── Mood ─────────────────────────────────────────────────────────────────
    bot_cfg = _bot_cfg()
    mood_block = (
        f"\n\n[Right now: {get_mood_prompt()}]"
        if (bot_cfg.get("mood") or {}).get("enabled", True) else ""
    )

    # ── Build enriched instructions ──────────────────────────────────────────
    base_instructions = load_instructions()
    enriched = base_instructions + mood_block + memory_block

    # Per-user persona override. Stored in user_memory under __persona__, so the get_memory() above already fetched it; get_persona() opened a second sqlite connection for a value already sitting in `memory`.
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
        "versions (no '(translation: ...)', no 'changed to', no 'in English:'). "
        "Never describe an action or an image instead of doing it: no '[Image of a "
        "shocked emoji]', no '*rolls eyes*', no '(sends a selfie)'. You cannot send "
        "a reaction here, so if an emoji is the whole response, type the emoji itself. "
        "Output the raw message only.]"
    )

    # ── Pictures / selfies ── if the user asks for a photo and we have an eligible one, tell the model it IS sending a selfie right now and remember which file so the adapter can actually send it (stored on msg.extra).
    picture_to_send = None
    try:
        from app.utils.pictures import (is_picture_request, is_video_request, pick_picture, pictures_enabled,
                                        selfie_instruction)
        if pictures_enabled(load_config()):
            # A video when a video is asked for and there is one; else a photo when a photo (or a video it has none
            # of) is asked for.
            wants_video = is_video_request(msg.content)
            picked = pick_picture(uid, video=True) if wants_video else None
            if picked:
                picture_to_send, _pic_desc = picked
                enriched += selfie_instruction(_pic_desc, video=True)
            elif not wants_video and is_picture_request(msg.content):
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

    _default_lang = bot_cfg.get("default_language", "en")
    lang_entry = _lang_cache.get(uid, {"tag": _default_lang, "count": 0})
    lang_entry["count"] += 1
    # Only (re)detect when there's enough text, short messages like "tg" are ambiguous and caused wrong-language replies.
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

    from app.utils.languages import language_name
    lang_display = language_name(lang_tag)
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
    _late = bot_cfg.get("late_reply") or {}
    if _late.get("enabled", True) and msg.wait_time >= _late.get("threshold", 300):
        # A written opener for this language if one exists; otherwise the model writes its own in whatever language it is already replying in, which is the only version that works for a language nobody listed.
        opener = _get_late_opener(msg.content, lang_tag)
        if opener:
            enriched += (
                f"\n\n[LATE REPLY: You took a while to respond. Open your reply "
                f"naturally with something like: \"{opener.strip()}\", weave it in as "
                f"the very first words of your message, then continue normally. Do NOT "
                f"add 'sorry' again later in the message and do NOT start with a comma or dash.]"
            )
        else:
            _style = (_late.get("style") or
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

    if response and is_refusal(response):
        # Never send the refusal and never go silent: a short confused reaction reads like a real person who just got a weird message.
        log_system(f"[Engine] Refusal from {msg.user_name}, sending a short reaction instead")
        response = random.choice(refusal_fallbacks())

    if not response:
        return None

    # A reply that is only a stage direction - "[Image of a wide, annoyed eye-roll emoji]", "*rolls eyes*" - went out as that literal text, which reads as obviously automated. Models produce them when the conversation calls for a reaction rather than words, and this platform has no reactions to send, so there is nothing to convert it into. Saying nothing is the better of the two: the message stays unanswered and is picked up on the next pass.
    from app.utils.humanize import is_stage_direction_only, strip_stage_directions
    if is_stage_direction_only(response):
        log_system(f"[Engine] Dropped a stage-direction reply to {msg.user_name}: {response[:60]}")
        return None
    # One mixed into a real reply is just trimmed off.
    _trimmed = strip_stage_directions(response)
    if _trimmed and _trimmed != response:
        response = _trimmed

    # ── Post-response: memory extraction ── two more sequential model calls, neither of which changes the reply that has already been generated. Awaiting them here delayed every Snapchat reply by however long they took, so they run alongside the send instead.
    _spawn_memory_update(uid, msg.content, response, memory)

    # ── Update history with reply ────────────────────────────────────────────
    history.append({"role": "assistant", "content": response})
    message_history[history_key] = history

    # ── Record stats (Snapchat uses text-keyed tables; others numeric) ───────
    try:
        # The adapter says which of its accounts this came in on, for the per-account figures on the Accounts page.
        account = (msg.extra or {}).get("account")
        if msg.platform == "snapchat":
            record_user_message_snap(uid, msg.user_name, account=account)
        else:
            record_user_message(int(uid), msg.user_name, account=account)
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


# ── Helpers used by adapters for manual / paused replies ── let an adapter record an incoming message without generating a reply (bot paused), then later answer accumulated unanswered messages via /reply.

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
