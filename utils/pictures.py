"""
utils/pictures.py — Shared "send a selfie / photo" support.

Both the Discord runner and the Snapchat bridge can offer to send a picture of
the bot when a user asks for one. Pictures live in config/pictures and must have
an AI-generated description stored in the DB (added automatically on upload) to
be eligible — the description is fed to the model so it reacts naturally to the
photo it's "sending".

This is the platform-agnostic core of the same behaviour the Discord runner
already implements inline; the Snapchat bridge uses it to send real Snaps.
"""
import os
import re
import random

from utils.helpers import resource_path
from utils.db import get_picture_description

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

# uid -> set of picture paths already sent this session, so the same photo isn't
# sent twice in a row to the same person.
_sent_pictures: dict = {}


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
    out = []
    for f in os.listdir(folder):
        if os.path.splitext(f)[1].lower() not in _PIC_EXTS:
            continue
        desc = get_picture_description(f)
        if desc:
            out.append((os.path.join(folder, f), desc))
    return out


def pick_picture(uid: str):
    """Pick a picture for this user that hasn't been sent recently.

    Returns (abs_path, description) or None when there are no eligible pictures.
    """
    pics = get_picturable()
    if not pics:
        return None
    sent = _sent_pictures.get(uid, set())
    available = [p for p in pics if p[0] not in sent]
    if not available:                       # all sent — reset and reuse
        _sent_pictures[uid] = set()
        available = pics
    choice = random.choice(available)
    _sent_pictures.setdefault(uid, set()).add(choice[0])
    return choice


def selfie_instruction(description: str = "") -> str:
    """The system-prompt block that makes the model react like it just sent a
    selfie — identical in spirit to the Discord runner's injection."""
    return (
        "\n\n[IMPORTANT: You ARE sending the user a photo of yourself RIGHT NOW in this very reply. "
        + (f"The photo shows: {description} " if description else "")
        + "The image is already attached and being sent. "
        "NEVER say 'maybe later', 'not right now', 'later', 'next time', 'maybe another time', or anything that implies you are NOT sending a photo — you already are. "
        "Do NOT describe or caption the photo. "
        "Just react casually like a real person who just hit send on a selfie — short, natural, confident.]"
    )
