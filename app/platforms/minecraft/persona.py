"""The persona, told briefly, for playing Minecraft.

Measured on a real persona: its instructions were about 5,800 tokens, and a reply in the game carries the game as
well (what the bot sees, its inventory, the commands it can use: about 1,100 more once compacted). Together that came
to 8,021 tokens against a free model tier's 8,000 a minute: refused, by every model in the chain. And the limit is a
minute's worth, so even a request that squeezes under leaves nothing for the next one, while mindcraft asks again
after every command's result.

So by default a Minecraft account plays the same character told briefly: the model condenses the persona once, keeping
who they are, what they are like and exactly how they talk, and leaving out what only means something in a messaging
app (photos, voice notes, read receipts, stories). Kept until the persona changes, which is seen by a hash of it, and
then made again. The whole persona is a setting away (minecraft.persona: full), for a model that can take it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

from app.utils.paths import DATA_DIR

BRIEF_FILE = DATA_DIR / "minecraft" / "persona_brief.json"
BRIEF_WORDS = 550
# Past this, a brief is not brief: a model that ignored the length is not trusted with the job.
MAX_BRIEF_CHARS = 7000

# The brief is the character and nothing else. An earlier wording asked for a brief "for someone who will play this
# character in Minecraft"; the persona said she plays Minecraft but not with strangers, and the model put the two
# together into a sentence that was never there ("You do not play actively; you are there for the social aspect"),
# so she refused every time she was asked to come over. Where she is and what she is doing is the game's to say
# (brain.game_context), never the brief's. PROMPT_VERSION is part of the cache key, so a brief written by an older
# wording is never used again.
PROMPT_VERSION = "2"
PROMPT = (
    "Below is the full description of a character. Condense it to at most {words} words.\n\n"
    "Keep, exactly: their name, age and where they are from; their personality and moods; the way they write "
    "(capital letters or not, punctuation, emoji, slang, how long their messages are, what language); what they "
    "like and dislike; anything they would never do or say. Keep the facts as they are: change nothing, add "
    "nothing, and say nothing about where they are or what they are doing right now.\n"
    "Leave out what only makes sense in a messaging app: photos, selfies, voice notes, calls, stories, read "
    "receipts, friend requests, notifications.\n\n"
    "Write it in the second person (\"You are ...\"), as plain sentences, no headings, no lists of rules. Reply with "
    "the condensed description only.\n\n--- THE CHARACTER ---\n{persona}"
)

_lock: asyncio.Lock | None = None


def key_of(full: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}\n{full}".encode("utf-8")).hexdigest()[:20]


def cached(full: str) -> str:
    """The brief made from exactly this persona, or "" when there is none yet."""
    try:
        data = json.loads(BRIEF_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("text") or "") if data.get("key") == key_of(full) else ""


def _save(full: str, text: str) -> None:
    BRIEF_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIEF_FILE.write_text(json.dumps({"key": key_of(full), "text": text, "made_at": time.time(),
                                      "from_chars": len(full)}, ensure_ascii=False), encoding="utf-8")


def head(full: str, chars: int = 4000) -> str:
    """The last resort when no model would write a brief: the persona's own opening, cut at a sentence. A persona
    starts with who they are, so this keeps the part that matters most; it is never cached, so a later try can do
    better."""
    if len(full) <= chars:
        return full
    cut = full[:chars]
    end = max(cut.rfind(". "), cut.rfind("\n"))
    return cut[: end + 1] if end > chars // 2 else cut


async def brief(full: str | None = None) -> str:
    """The brief persona: from the cache when the persona has not changed, else written now (once, however many
    replies are waiting for it)."""
    global _lock
    if full is None:
        from app.utils.helpers import load_instructions
        full = load_instructions()
    if not full:
        return ""
    hit = cached(full)
    if hit:
        return hit
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        hit = cached(full)                    # written while this one waited its turn
        if hit:
            return hit
        # Not generate_response: that is a chat reply, stopped at bot.max_reply_tokens, which would cut a brief of
        # this length off halfway.
        from app.utils.ai import condense
        text = (await condense(PROMPT.format(words=BRIEF_WORDS, persona=full),
                               "You condense character descriptions faithfully.") or "").strip()
        if not text or len(text) > MAX_BRIEF_CHARS:
            return head(full)
        _save(full, text)
        return text
