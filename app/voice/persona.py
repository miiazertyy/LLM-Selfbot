"""The persona, for talking out loud.

The same pieces a text reply is built from (app/core/engine.py: its instructions, its mood, what it remembers of
this person, a persona set just for them, the time) with one thing swapped: the rules for typing a message become
the rules for talking on the phone. A call has to sound like the same person who texts them, so nothing about who
it is comes from anywhere else.
"""
import re

PLATFORM_NAMES = {"discord": "Discord", "telegram": "Telegram", "snapchat": "Snapchat", "instagram": "Instagram",
                  "x": "X", "panel": ""}

SPEAKING = (
    "\n\n[VOICE CALL: You are on a live call with {name}{where}. You are talking out loud, not typing.\n"
    "- Talk like a real person on the phone: one or two short sentences, then let them talk.\n"
    "- Contractions and everyday words. A little \"um\", \"yeah\", \"oh wait\" or \"hmm\" now and then, never in "
    "every line.\n"
    "- React to what they said before moving on. Laugh if something is funny. Ask them things back.\n"
    "- Nothing that cannot be heard: no lists, no markdown, no emoji, no hashtags, no links.\n"
    "- Numbers, times and names the way people say them out loud.\n"
    "- If you did not catch something, say so and ask again.\n"
    "- Do not end the call unless they do, or you are told it is time to go.]"
)

# Stage directions: what the session asks of it at a given moment. In brackets, which the models read as direction
# rather than as something the other person said.
GREETING = ("[The phone just rang and you picked up: it is {name}. Say hello the way you would when they call, a "
            "few words at most, then wait for them.]")
DIALING = ("[You called {name} and they just picked up. Say hi and why you are calling, in a few words, the way you "
           "would.]")
CHECK_IN = "[It has gone quiet for a while. Check they are still there, in a few words.]"
WRAP_UP = "[You have to go now. Wrap the call up in one short sentence and say bye.]"


def call_instructions(uid: str, name: str, platform: str = "", *, language: str = "", recent: list = None,
                      persona_text: str = "") -> str:
    """Everything the voice is told before the call starts."""
    from app.utils.helpers import load_config, load_instructions, france_time_str

    base = persona_text or load_instructions()
    bot = (load_config() or {}).get("bot") or {}
    out = base

    try:
        if (bot.get("mood") or {}).get("enabled", True):
            from app.utils.mood import get_mood_prompt
            out += f"\n\n[Right now: {get_mood_prompt()}]"
    except Exception:
        pass

    memory = {}
    if uid:
        try:
            from app.utils.memory import format_memory_for_prompt, get_memory
            memory = get_memory(uid) or {}
            out += format_memory_for_prompt(memory)
        except Exception:
            memory = {}
    if memory.get("__persona__"):
        out += (f"\n\n[PERSONA OVERRIDE FOR THIS USER: {memory['__persona__']} "
                f"Keep to it for the whole call.]")

    # What the two of them were just texting about, so the call does not start from nothing.
    lines = [m for m in (recent or []) if str(m.get("text") or "").strip()][-10:]
    if lines:
        said = "\n".join(f"{'You' if m.get('mine') else name}: {str(m['text']).strip()[:200]}" for m in lines)
        out += f"\n\n[YOUR LAST MESSAGES WITH {name.upper()}, before this call:\n{said}]"

    where = PLATFORM_NAMES.get(platform, platform.title() if platform else "")
    out += SPEAKING.format(name=name or "them", where=f" on {where}" if where else "")

    if language:
        from app.utils.languages import language_name
        out += f"\n\n[LANGUAGE: Speak {language_name(language)}, unless they switch.]"
    else:
        out += "\n\n[LANGUAGE: Speak whatever language they speak to you in.]"

    try:
        when = france_time_str()
        if when:
            out += f"\n\n[CURRENT TIME: It is {when} in France (Paris time).]"
    except Exception:
        pass
    return out


def direction(kind: str, name: str = "") -> str:
    return {"greet": GREETING, "dial": DIALING, "check": CHECK_IN, "wrap": WRAP_UP}[kind].format(
        name=name or "them")


_MARKUP = re.compile(r"(\*{1,3}|_{1,3}|`{1,3}|#+\s|https?://\S+|\[[^\]]{0,80}\])")
_EMOJI = re.compile("[\U00010000-\U0010ffff☀-➿⬀-⯿️]+")


def speakable(text: str) -> str:
    """A reply as it can be said: no markup, no emoji, no links, no stage directions it echoed back."""
    text = _MARKUP.sub("", str(text or ""))
    text = _EMOJI.sub("", text)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str, longest: int = 170) -> list:
    """A reply cut where a person would breathe, so the first one can be said while the rest is still being made.
    Nothing longer than the voice will take in one go (Orpheus stops at 200 characters)."""
    out = []
    for part in _SENTENCE.split(text.strip()):
        part = part.strip()
        while len(part) > longest:
            cut = part.rfind(", ", 0, longest)
            cut = cut + 1 if cut > longest // 3 else part.rfind(" ", 0, longest)
            if cut <= 0:
                cut = longest
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


# A goodbye, said plainly. Not "later" alone ("I'll do it later") nor "salut", which is hello as often as bye: one
# false match here ends a call on someone mid-sentence.
_BYE = re.compile(r"\b(bye|byee+|goodbye|good night|gotta go|got to go|talk (to you )?(later|soon|tomorrow)|"
                  r"see (you|ya)( later| soon| tomorrow)?|ciao|cya|ttyl|bisous|a plus|à plus|à demain|bonne nuit|"
                  r"tchao)\b", re.I)


def sounds_like_goodbye(text: str) -> bool:
    return bool(_BYE.search(str(text or "")))
