"""
utils/humanize.py — Output touch-ups that make replies look human.

Shared so every platform can apply the same anti-detection processing the
Discord runner already does inline:
  • strip_ai_tells  — remove em/en dashes (a well-known "this was written by an
                      LLM" giveaway).
  • add_typo        — occasionally introduce a realistic typo.
"""
import random
import re

# A line that begins with one of these is the model's meta-commentary
# (translation / reasoning / self-correction), not the actual message. When the
# real reply is followed by this stuff, we cut from the first such line onward.
_META_LINE_RE = re.compile(
    r"^\s*[\(\[\*\-]*\s*"
    r"(changed to|change to|translation|translated|in english|english version|"
    r"original|note to self|as an ai|thinking|reasoning|analysis|here'?s the translation)"
    r"\b",
    re.IGNORECASE,
)


def strip_meta(text: str) -> str:
    """Remove model meta-commentary (translations, reasoning, alternate versions)
    that sometimes leaks into a reply, keeping only the real message."""
    if not text:
        return text
    kept = []
    for line in text.split("\n"):
        if _META_LINE_RE.match(line):
            break
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if not cleaned:
        cleaned = text  # whole thing matched — don't send an empty message
    # Strip inline parenthetical/bracketed translation notes, e.g. "(translation: …)".
    cleaned = re.sub(
        r"[\(\[]\s*(translation|translated|english)\s*[:\-–][^)\]]*[\)\]]",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def strip_ai_tells(text: str) -> str:
    """Remove the punctuation tells that mark text as AI-written."""
    if not text:
        return text
    return text.replace("—", "").replace("–", "")  # — and –


def add_typo(text: str, typo_chance: float = 0.05) -> str:
    """With probability `typo_chance`, introduce one realistic typo into a word."""
    if not text or len(text) < 5 or random.random() > typo_chance:
        return text

    typo_type = random.choice(["swap", "double", "miss"])
    words = text.split()
    if not words:
        return text

    word_idx = random.randint(0, len(words) - 1)
    word = words[word_idx]
    if len(word) < 3:
        return text

    char_idx = random.randint(1, len(word) - 2)
    if typo_type == "swap" and char_idx < len(word) - 1:
        word = word[:char_idx] + word[char_idx + 1] + word[char_idx] + word[char_idx + 2:]
    elif typo_type == "double":
        word = word[:char_idx] + word[char_idx] + word[char_idx:]
    elif typo_type == "miss":
        word = word[:char_idx] + word[char_idx + 1:]

    words[word_idx] = word
    return " ".join(words)


def humanize(text: str, typo_chance: float = 0.05) -> str:
    """Apply the full human touch-up pass to a reply before sending."""
    return add_typo(strip_ai_tells(strip_meta(text)), typo_chance)
