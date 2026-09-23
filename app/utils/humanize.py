"""
utils/humanize.py - Output touch-ups that make replies look human.

Shared so every platform applies the same anti-detection processing:
  • strip_ai_tells, remove em/en dashes (a well-known LLM giveaway).
  • add_typo, occasionally introduce a realistic typo.
  • Discord reaction tags ([[REACT:...]]) are stripped here so they can
    never leak into a non-Discord message (Snapchat has no reactions).
"""
import random
import re

from app.utils.behavior import parse_reaction_tag

# A line that begins with one of these is the model's meta-commentary
# (translation / reasoning / self-correction), not the actual message. Cut from
# the first such line onward.
_META_LINE_RE = re.compile(
    r"^\s*[\(\[\*\-]*\s*"
    r"(changed to|change to|translation|translated|in english|english version|"
    r"original|note to self|as an ai|thinking|reasoning|analysis|here'?s the translation)"
    r"\b",
    re.IGNORECASE,
)


# A reasoning model narrates itself before answering. The narration arrives
# wrapped in tags, sometimes without the closing one when the answer was cut
# short by a token limit.
_THINK_RE = re.compile(r"<\s*(think|thinking|reasoning)\s*>.*?<\s*/\s*\1\s*>",
                       re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<\s*(think|thinking|reasoning)\s*>.*\Z",
                            re.IGNORECASE | re.DOTALL)


def strip_reasoning(text: str) -> str:
    """Drop a reasoning model's internal monologue.

    Models like qwen3 answer with a <think> block first. It is not part of the
    answer, and storing it as a picture description meant the model later
    matching pictures had to read paragraphs of "Wait, let me re-examine the
    bounding box" to find out what the picture showed.
    """
    if not text:
        return text
    cleaned = _THINK_RE.sub("", text)
    # An unclosed block means the answer was truncated mid thought, so there is
    # nothing after it worth keeping.
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    return cleaned.strip()


_MD_PATTERNS = (
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE), ""),        # headings
    (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), r"\1"),            # bold
    (re.compile(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", re.DOTALL), r"\1"),   # italics
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),             # bullets
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),             # numbered lists
    (re.compile(r"`{1,3}"), ""),                                 # code ticks
)


def plain_text(text: str) -> str:
    """Flatten a model's formatted answer into ordinary prose.

    Descriptions came back as a structured document with headings, numbered
    sections and bold labels. That reads badly in a card, and none of the
    scaffolding carries meaning: what is in the picture is the only part worth
    keeping.
    """
    if not text:
        return text
    out = strip_reasoning(text)
    for pattern, repl in _MD_PATTERNS:
        out = pattern.sub(repl, out)
    # Collapse the blank lines the headings left behind, keeping paragraphs.
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = "\n".join(line.rstrip() for line in out.split("\n"))
    return out.strip()


def strip_meta(text: str) -> str:
    """Remove model meta-commentary (translations, reasoning, alternate
    versions) that sometimes leaks into a reply."""
    if not text:
        return text
    kept = []
    for line in text.split("\n"):
        if _META_LINE_RE.match(line):
            break
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if not cleaned:
        cleaned = text  # whole thing matched, don't send an empty message
    # Strip inline parenthetical translation notes, e.g. "(translation: …)".
    cleaned = re.sub(
        # The class ends with an en dash, spelled as an escape in a plain string
        # spliced onto the raw one: inside a raw string a backslash-u is six
        # literal characters, not the dash.
        r"[\(\[]\s*(translation|translated|english)\s*[:\-" "\u2013]"
        r"[^)\]]*[\)\]]",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    # Both passes can strip everything (a reply that was nothing but a
    # note); returning "" would send a blank message, so keep the original.
    return cleaned or text.strip()




# A reply that is nothing but a description of something the model imagines it
# is doing: "[Image of a wide, annoyed eye-roll emoji]", "*rolls eyes*",
# "(sends a selfie)". Models produce these when the conversation calls for a
# reaction rather than words, and the whole bracket went out as the message -
# which reads as obviously automated to the person on the other end.
#
# Only whole-message directions are touched. A reply that happens to contain
# brackets ("be there in [5] mins") keeps them, because the text around the
# bracket is the message.
_STAGE_VERBS = (
    "image|picture|photo|pic|gif|video|selfie|snap|emoji|sticker|reaction|"
    "sends?|sending|sent|reacts?|reacting|replies|laughs?|laughing|smiles?|"
    "smiling|shrugs?|nods?|sighs?|rolls?|winks?|grins?|waves?|stares?|blinks?"
)
_STAGE_RE = re.compile(
    "^(?:"
    # [Image of ...] / (sends a selfie) - a bracket opening with one of the verbs
    r"[(\[*]\s*(?:" + _STAGE_VERBS + r")[^)\]*]*[)\]*]"
    # *rolls eyes* - asterisks with anything short between them
    r"|\*[^*]{1,80}\*"
    ")$",
    re.IGNORECASE | re.DOTALL,
)


def strip_stage_directions(text: str) -> str:
    """Drop a reply that is only a stage direction. Returns "" when it was.

    Unlike strip_meta(), an empty result here is meaningful and the caller is
    expected to act on it: sending the bracket is worse than sending nothing.
    """
    if not text:
        return text
    cleaned = text.strip()
    # Repeat, because these arrive stacked: "*sighs* [rolls eyes]".
    for _ in range(4):
        before = cleaned
        cleaned = _STAGE_RE.sub("", cleaned).strip()
        if cleaned == before:
            break
    return cleaned


def is_stage_direction_only(text: str) -> bool:
    """True when the whole reply was a stage direction and nothing else."""
    return bool(text and text.strip()) and not strip_stage_directions(text)


def strip_ai_tells(text: str) -> str:
    """Remove the punctuation tells that mark text as AI-written."""
    if not text:
        return text
    return text.replace("\u2014", "").replace("\u2013", "")  # em dash, en dash


def add_typo(text: str, typo_chance: float = 0.03) -> str:
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


def humanize(text: str, typo_chance: float = 0.03) -> str:
    """Apply the full human touch-up pass to a reply before sending."""
    text, _emoji, _react_only = parse_reaction_tag(text)
    return add_typo(strip_ai_tells(strip_meta(text)), typo_chance)
