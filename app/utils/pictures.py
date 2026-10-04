"""Shared "send a selfie / photo" support. Both platforms can send a picture of the bot when a user asks. Pictures live in the persona's own folder (app/utils/personas.py) and must have an AI-generated description in the DB (added automatically on upload), the description is fed to the model so it reacts naturally to the photo it's "sending"."""
import os
import re
import random

from app.utils.db import get_all_picture_descriptions

_PICTURE_REQUEST_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\b(send|show|post|drop|share).{0,20}(photo|pic|picture|selfie|image|face|look)\b",
    r"\b(photo|pic|picture|selfie|image).{0,15}(of you|of u|yourself|ur face|your face)\b",
    r"\b(let me|can i|may i|wanna|want to|id like to).{0,15}(see|look at).{0,10}(you|ur face|your face|what you look)\b",
    r"\bwhat (do you|does she|u) look like\b",
    r"\bshow me (you|ur|your)\b",
    r"\blet me see you\b",
    r"\bcan i see (you|ur|your|what you)\b",
    r"\bi wanna see (you|ur|your)\b",
    r"\bsend (me )?(a )?(pic|photo|selfie|image)\b",
    r"(envoie|montre|montre.moi|partage).{0,20}(photo|pic|selfie|image|tete|t[eê]te|gueule|visage|face)",
    r"(voir|see).{0,15}(ta |ton |te |t').{0,10}(tete|t[eê]te|gueule|visage|face|photo|pic|selfie)",
    r"(je peux|je pourrais|puis.je|peux.tu).{0,20}(voir|see).{0,20}(toi|tete|t[eê]te|gueule|visage|photo|face)",
    r"t.as.{0,10}(photo|pic|selfie|image)",
    r"(a quoi|[àa] quoi).{0,15}ressemble",
    r"ta (tete|t[eê]te|gueule|visage|face)",
    r"\b(face|look).{0,10}(like|at).{0,10}(you|u)\b",
]]

_PIC_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
# Videos are kept among the pictures as MP4 (app/utils/videos.py), and sent when a video is what was asked for.
_VIDEO_EXTS = {".mp4"}

# Asked for a video of it, not a photo: "send a vid", "film yourself", "une vidéo de toi".
_VIDEO_REQUEST_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\b(send|show|post|drop|share|make|record|film|take)\b.{0,25}\b(video|vid|vids|videos|clip|vlog)\b",
    r"\b(video|vid|clip)\b.{0,15}\b(of you|of u|of yourself|of urself|of ur face|of your face)\b",
    r"\b(film|record)\b.{0,10}\b(yourself|urself|you|u)\b",
    r"\b(can i|could i|wanna|want to|let me)\b.{0,15}\b(see|watch)\b.{0,10}\b(a )?(video|vid|clip)\b",
    r"(envoie|montre|fais|filme|partage).{0,25}(vid[ée]o|vid[ée]os|vid\b|clip)",
    r"(vid[ée]o|clip).{0,15}(de toi|de vous|toi)",
    r"\bfilme.{0,5}(toi|moi)\b",
]]

# uid -> path of the last picture sent, so the same photo is never sent twice in a row to the same person.
_last_sent: dict = {}


# A call is not a video to send: "make a video call", "facetime me", "appel vidéo".
_CALL = re.compile(r"\bvid(?:eo)?\s*-?\s*(?:call|chat)|\bfacetime\b|appel\s+vid[ée]o", re.IGNORECASE)


def is_video_request(text: str) -> bool:
    """True if the message asks the bot for a video of itself (checked before a photo: "send a video" is both)."""
    if not text or _CALL.search(text):
        return False
    return any(p.search(text) for p in _VIDEO_REQUEST_PATTERNS)


def is_picture_request(text: str) -> bool:
    """True if the message is asking the bot for a photo/selfie of itself."""
    if not text:
        return False
    return any(p.search(text) for p in _PICTURE_REQUEST_PATTERNS)


def is_video_file(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in _VIDEO_EXTS


def pictures_enabled(config) -> bool:
    pics_cfg = (config.get("bot", {}).get("pictures") or {}) if config else {}
    return pics_cfg.get("enabled", True)


def pictures_folder(persona=None) -> str:
    """A persona's pictures (app/utils/personas.py): the one named, else the one this code works as, else Default's."""
    from app.utils import personas
    pid = persona if persona and personas.exists(persona) else (personas.current() or personas.DEFAULT)
    return str(personas.pictures_dir(pid))


def get_picturable(persona=None, video: bool = False) -> list:
    """Return [(abs_path, description)] for one persona's picture files that have a stored description (the description is what the model 'sees'). `video`: its videos instead of its photos."""
    folder = pictures_folder(persona)
    if not os.path.exists(folder):
        return []
    descriptions = get_all_picture_descriptions(persona)
    exts = _VIDEO_EXTS if video else _PIC_EXTS
    return [
        (os.path.join(folder, f), descriptions[f])
        for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in exts and descriptions.get(f)
    ]


def pick_picture(uid: str, persona=None, video: bool = False):
    """Pick a picture (or with `video`, a video) for this user, never the one sent to them last. Returns (abs_path, description) or None when there are no eligible ones."""
    pics = get_picturable(persona, video)
    if not pics:
        return None
    last = _last_sent.get(uid)
    available = [p for p in pics if p[0] != last] or pics
    choice = random.choice(available)
    _last_sent[uid] = choice[0]
    return choice


def selfie_instruction(description: str = "", video: bool = False) -> str:
    """The system-prompt block that makes the model react like it just sent a selfie (or a video of itself), identical in spirit to the Discord runner's injection."""
    if video:
        return (
            "\n\n[IMPORTANT: You ARE sending the user a video of yourself RIGHT NOW in this very reply. "
            + (f"The video shows: {description} " if description else "")
            + "The video is already attached and being sent. "
            "NEVER say 'maybe later', 'not right now', 'later', 'next time', or anything that implies you are NOT sending a video - you already are. "
            "Do NOT describe or caption the video. "
            "Just react casually like a real person who just hit send on a quick video of themselves, short, natural, confident.]"
        )
    return (
        "\n\n[IMPORTANT: You ARE sending the user a photo of yourself RIGHT NOW in this very reply. "
        + (f"The photo shows: {description} " if description else "")
        + "The image is already attached and being sent. "
        "NEVER say 'maybe later', 'not right now', 'later', 'next time', 'maybe another time', or anything that implies you are NOT sending a photo - you already are. "
        "Do NOT describe or caption the photo. "
        "Just react casually like a real person who just hit send on a selfie, short, natural, confident.]"
    )


# ── What a picture shows ──────────────────────────────────────────────────────
# Written by a vision model when a picture is added, and read by the bot when it
# sends that picture ("The photo shows: ..."). A caption is all that needs: the
# bot is told not to describe the photo, only to react like someone who just
# sent it. Four places asked for a description, three of them "in full
# detail", and got essays with bold and lists: a wall of text on the page, and
# a paragraph of tokens in the prompt every time the picture went out. An
# essay once ran to about 1700 output tokens, over Groq's free per minute
# ceiling, so the request was refused outright. They all ask this now.
DESCRIBE_PROMPT = (
    "Describe this photo like a short caption, in one or two sentences and under 40 words: "
    "who or what is in it, what they are doing or wearing, where, and any visible text. "
    "Plain words only, no markdown or lists, and do not begin with \"The image\" or \"This photo\"."
)
# Room for the caption, and a ceiling for a reasoning model that would spend the whole allowance thinking.
DESCRIBE_MAX_TOKENS = 400
# Longer than a caption needs to be (characters): the page offers to describe these again, shorter.
LONG_DESCRIPTION = 320

# "The image shows ...", "In this photo, ..." and a video's "These frames show ..." say nothing; the caption starts after them.
_PREAMBLE = re.compile(
    r"^(?:(?:the|this|these)\s+(?:image|photo|photograph|picture|selfie|shot|video|clip|footage|frames?)\s+"
    r"(?:shows?|depicts?|features?|captures?|is of|are of|contains?)\s+"
    r"|in\s+(?:the|this|these)\s+(?:image|photo|photograph|picture|selfie|shot|video|clip|footage|frames?)\s*,\s*)",
    re.IGNORECASE)


def describe_messages(data_url: str) -> list:
    """The request that asks a vision model for a picture's caption."""
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": DESCRIBE_PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }]


def clean_description(raw: str, max_words: int = 60) -> str:
    """A model's answer as a caption: no reasoning, no markdown, no "The image shows", one paragraph, and whole sentences up to about max_words when it ran long anyway."""
    from app.utils.humanize import plain_text
    # One paragraph. A line that ends without a stop (a heading, a list item) gets one, so the lines do not run together.
    lines = [re.sub(r"\s+", " ", line).strip() for line in plain_text(raw or "").split("\n")]
    text = " ".join(line if line[-1] in ".!?:;," else line + "." for line in lines if line)
    m = _PREAMBLE.match(text)
    if m and m.end() < len(text):
        text = text[m.end():]
        text = text[:1].upper() + text[1:]
    if len(text.split()) > max_words:
        kept, count = [], 0
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            n = len(sentence.split())
            if kept and count + n > max_words:
                break
            kept.append(sentence)
            count += n
        text = " ".join(kept)
    return text
