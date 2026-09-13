"""
utils/pictures.py - Shared "send a selfie / photo" support.

Both platforms can send a picture of the bot when a user asks. Pictures live
in config/pictures and must have an AI-generated description in the DB
(added automatically on upload), the description is fed to the model so it
reacts naturally to the photo it's "sending".
"""
import os
import re
import random

from app.utils.helpers import resource_path
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

# uid -> path of the last picture sent, so the same photo is never sent twice
# in a row to the same person.
_last_sent: dict = {}


def is_picture_request(text: str) -> bool:
    """True if the message is asking the bot for a photo/selfie of itself."""
    if not text:
        return False
    return any(p.search(text) for p in _PICTURE_REQUEST_PATTERNS)


def pictures_enabled(config) -> bool:
    pics_cfg = (config.get("bot", {}).get("pictures") or {}) if config else {}
    return pics_cfg.get("enabled", True)


def get_picturable() -> list:
    """Return [(abs_path, description)] for picture files that have a stored
    description (the description is what the model 'sees')."""
    folder = resource_path("config/pictures")
    if not os.path.exists(folder):
        return []
    descriptions = get_all_picture_descriptions()
    return [
        (os.path.join(folder, f), descriptions[f])
        for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in _PIC_EXTS and descriptions.get(f)
    ]


def pick_picture(uid: str):
    """Pick a picture for this user, never the one sent to them last.

    Returns (abs_path, description) or None when there are no eligible pictures.
    """
    pics = get_picturable()
    if not pics:
        return None
    last = _last_sent.get(uid)
    available = [p for p in pics if p[0] != last] or pics
    choice = random.choice(available)
    _last_sent[uid] = choice[0]
    return choice


def selfie_instruction(description: str = "") -> str:
    """The system-prompt block that makes the model react like it just sent a
    selfie - identical in spirit to the Discord runner's injection."""
    return (
        "\n\n[IMPORTANT: You ARE sending the user a photo of yourself RIGHT NOW in this very reply. "
        + (f"The photo shows: {description} " if description else "")
        + "The image is already attached and being sent. "
        "NEVER say 'maybe later', 'not right now', 'later', 'next time', 'maybe another time', or anything that implies you are NOT sending a photo - you already are. "
        "Do NOT describe or caption the photo. "
        "Just react casually like a real person who just hit send on a selfie, short, natural, confident.]"
    )
