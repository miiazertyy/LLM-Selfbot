"""A persona made from someone's own messages: how they text, and who they are, as their chats show it.

It comes from the data export each social lets you download, and only the owner's side ever comes in: what the export
says its owner wrote (chatexports.py). The people on the other side of the chats are never read for this, and nothing here
can be asked to: a persona of someone else, made from their private messages, is not something this makes. The accounts
the app runs are not read at all: most of what they have sent is the bot's, and a persona learned from those would learn
the bot.

The work happens in a folder of its own (cache/from_chats/<job>), one job at a time, gone once the persona is made or
after a day. Then:

  measure   how they text, counted rather than guessed: length, bursts, capitals, punctuation, emoji, laughs
  notes     a model reads samples of their messages, a batch at a time, for how they write and what they say about
            themselves
  write     the persona in the template's shape (resources/instructions.txt): who they are, and how they text as
            rules, with the template's own rules about not sounding like an assistant kept
  create    a new persona with that text, and the settings the numbers call for (its message length, its emojis)

What is sent to the model is samples of their own messages and nothing else, to the model that does background work.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

from app.utils.paths import DATA_DIR

ROOT = DATA_DIR / "cache" / "from_chats"
SAMPLE = 600
BATCH = 150
MIN_MESSAGES = 30
KEEP_S = 24 * 3600

_lock = threading.RLock()
_job: dict = {}


# ── The job ───────────────────────────────────────────────────────────────────

def _new_job() -> dict:
    sweep()
    jid = uuid.uuid4().hex[:16]
    folder = ROOT / jid
    folder.mkdir(parents=True, exist_ok=True)
    return {"id": jid, "dir": folder, "files": {}, "n": 0,
            "write": {"state": "", "step": "", "done": 0, "total": 0, "why": ""}, "result": None}


def job() -> dict:
    """The job under way, made when first needed."""
    global _job
    with _lock:
        if not _job or not Path(_job["dir"]).is_dir():
            _job = _new_job()
        return _job


def reset() -> None:
    """Start over: everything gathered so far goes."""
    global _job
    with _lock:
        if _job:
            shutil.rmtree(_job["dir"], ignore_errors=True)
        _job = {}


def sweep() -> None:
    """Jobs left behind (the panel closed part way) go after a day."""
    if not ROOT.is_dir():
        return
    now = time.time()
    for d in ROOT.iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > KEEP_S and (not _job or d != _job.get("dir")):
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _write_jsonl(path: Path, messages: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for m in messages:
            fh.write(json.dumps({"ts": m["ts"], "text": m["text"], "chat": m.get("chat", "")}, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if isinstance(m, dict) and str(m.get("text") or "").strip():
                    out.append({"ts": float(m.get("ts") or 0), "text": str(m["text"]), "chat": str(m.get("chat") or "")})
    except OSError:
        pass
    return out


# ── Export files ──────────────────────────────────────────────────────────────

def _known() -> dict:
    """What the app knows of the owner from its own accounts: their names there, for an export that cannot say."""
    out: dict = {}
    for platform in ("instagram", "telegram", "whatsapp"):
        for f in (DATA_DIR / "config").glob(f"identity_{platform}_*.json"):
            try:
                who = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for k in ("display_name", "username", "name", "id", "user_id", "push_name"):
                if who.get(k):
                    out.setdefault(platform, set()).add(str(who[k]))
    return out


def add_export(part: Path, name: str) -> list:
    """A file dropped in, read for its owner's messages and kept as those alone; the file itself goes."""
    from app.utils import chatexports
    j = job()
    try:
        results = chatexports.read(part, name, _known())
    except chatexports.NotAnExport as e:
        results = [{"platform": "", "label": name, "owner": "", "messages": [], "why": str(e)}]
    except Exception as e:
        results = [{"platform": "", "label": name, "owner": "", "messages": [], "why": f"It could not be read ({e})."}]
    finally:
        try:
            Path(part).unlink(missing_ok=True)
        except OSError:
            pass
    added = []
    for r in results:
        with _lock:
            j["n"] += 1
            key = f"file-{j['n']}"
            row = {"key": key, "name": name, "platform": r.get("platform") or "", "label": r.get("label") or name,
                   "count": len(r.get("messages") or []), "why": r.get("why", ""), "whatsapp": "senders" in r,
                   "owner": str(r.get("owner") or "")}
            if "senders" in r:
                (j["dir"] / f"{key}.senders.json").write_text(json.dumps(r["senders"], ensure_ascii=False),
                                                               encoding="utf-8")
            else:
                _write_jsonl(j["dir"] / f"{key}.jsonl", r.get("messages") or [])
                if not row["count"] and not row["why"]:
                    row["why"] = "There are no messages of yours in it."
            j["files"][key] = row
            added.append(key)
    _resolve_whatsapp()
    with _lock:
        return [dict(j["files"][k]) for k in added if k in j["files"]]


def remove_export(key: str) -> None:
    j = job()
    with _lock:
        j["files"].pop(key, None)
        for f in j["dir"].glob(f"{key}.*"):
            f.unlink(missing_ok=True)
    _resolve_whatsapp()


def _resolve_whatsapp() -> None:
    """Which sender is the owner across the WhatsApp chats dropped in, worked out again whenever one comes or goes."""
    from app.utils import chatexports
    j = job()
    with _lock:
        rows = [r for r in j["files"].values() if r.get("whatsapp")]
    chats = []
    for r in rows:
        try:
            chats.append(json.loads((j["dir"] / f"{r['key']}.senders.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            chats.append({})
    owner = chatexports.whatsapp_owner([{"senders": c} for c in chats], set(_known().get("whatsapp") or ()))
    for r, senders in zip(rows, chats):
        mine = senders.get(owner) or [] if owner else []
        _write_jsonl(j["dir"] / f"{r['key']}.jsonl", mine)
        with _lock:
            r["count"] = len(mine)
            r["owner"] = owner
            r["why"] = "" if owner and mine else (
                "Waiting for one more WhatsApp chat, to tell which messages are yours: the name in every chat is."
                if not owner else "There are no messages of yours in it.")


# ── Where it stands ───────────────────────────────────────────────────────────

def status() -> dict:
    j = job()
    with _lock:
        files = [dict(r) for r in j["files"].values()]
        write = dict(j["write"])
        result = j["result"]
    return {"id": j["id"], "files": files, "total": sum(f.get("count", 0) for f in files if not f.get("why")),
            "write": write, "result": _shown_result(result) if result else None, "model": model_label()}


def _shown_result(r: dict) -> dict:
    return {k: r[k] for k in ("name", "text", "examples", "settings", "stats", "count") if k in r}


def model_label() -> dict:
    """The model the samples go to: the one doing background work. This computer's never leave it."""
    try:
        from app.utils import providers
        from app.utils.helpers import load_config
        entry = providers.job_chain(load_config(), "small")[0]
        return {"label": providers.label(entry), "local": entry.get("provider") == "local"}
    except (Exception, SystemExit):         # no settings file at all exits rather than raising
        return {"label": "", "local": False}


# ── How they text, counted ────────────────────────────────────────────────────

URL = re.compile(r"https?://\S+|www\.\S+", re.I)
EMOJI = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    "|[\U0001F300-\U0001FAFF☀-➿⭐⭕❤❣]️?"
    "(?:‍[\U0001F300-\U0001FAFF☀-➿❤]️?)*)")
LAUGH = re.compile(r"\b(a?ha(?:ha)+h?|he(?:he)+|lo+l+|lmf?ao+|mdr+|ptdr+|xd+|jaja(?:ja)*|kkk+|rs(?:rs)+)\b", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()./-]{7,}\d(?!\w)")


def clean(messages: list) -> list:
    """Their words, with what says nothing about how they text taken out: a link on its own, an empty line."""
    out = []
    for m in messages:
        text = str(m.get("text") or "").strip()
        if not URL.sub("", text).strip():
            continue
        out.append({**m, "text": text[:1500]})
    return out


def measure(messages: list) -> dict:
    texts = [m["text"] for m in messages]
    n = len(texts) or 1
    lengths = sorted(len(t) for t in texts) or [0]
    lettered = [t for t in texts if t[:1].isalpha()]
    emoji = Counter(e for t in texts for e in EMOJI.findall(t))
    laughs = Counter(re.sub(r"(.)\1{2,}", r"\1\1", w.lower()) for t in texts for w in LAUGH.findall(t))
    # Messages in a row in one chat, a minute and a half apart at most: one thought sent as several.
    runs, by_chat = [], {}
    for m in messages:
        by_chat.setdefault((m.get("source", ""), m.get("chat", "")), []).append(float(m.get("ts") or 0))
    for stamps in by_chat.values():
        stamps.sort()
        run = 1
        for a, b in zip(stamps, stamps[1:]):
            if b - a <= 90:
                run += 1
            else:
                runs.append(run)
                run = 1
        runs.append(run)
    return {
        "messages": len(texts),
        "median_length": lengths[len(lengths) // 2],
        "lowercase": round(sum(1 for t in lettered if t[0].islower()) / max(1, len(lettered)), 2),
        "ends_with_period": round(sum(1 for t in texts if t.endswith(".") and not t.endswith("..")) / n, 2),
        "questions": round(sum(1 for t in texts if t.rstrip().endswith("?")) / n, 2),
        "with_emoji": round(sum(1 for t in texts if EMOJI.search(t)) / n, 2),
        "top_emoji": [e for e, _ in emoji.most_common(12)],
        "emoji_counts": dict(emoji.most_common(40)),
        "laughs": [w for w, _ in laughs.most_common(4)],
        "burst": round(sum(runs) / max(1, len(runs)), 1),
    }


def sample(messages: list, k: int = SAMPLE) -> list:
    """About k of their messages, taken in turn from every chat, newest first in each, without the same line twice:
    one long chat must not be all the model hears. Oldest first, as read."""
    by_chat: dict = {}
    for m in sorted(messages, key=lambda m: -float(m.get("ts") or 0)):
        by_chat.setdefault((m.get("source", ""), m.get("chat", "")), []).append(m)
    queues = list(by_chat.values())
    seen, picked = set(), []
    while queues and len(picked) < k:
        for q in list(queues):
            while q:
                m = q.pop(0)
                key = re.sub(r"\s+", " ", m["text"].lower())
                if key in seen:
                    continue
                seen.add(key)
                picked.append(m)
                break
            if not q:
                queues.remove(q)
            if len(picked) >= k:
                break
    return sorted(picked, key=lambda m: float(m.get("ts") or 0))


# ── Writing it ────────────────────────────────────────────────────────────────

NOTES = """You are reading messages one person wrote to friends on apps like Discord, Snapchat, Instagram and WhatsApp. \
Only their own messages are here, oldest first. They asked for a chat persona that texts like them, made from these. \
Describe them in short notes, in two parts.

HOW THEY TEXT:
- how long their messages are, and whether they send one thought as several messages
- capitals and punctuation
- emoji: how often, and which
- slang, abbreviations, spellings and words they use a lot (quote them)
- how they laugh, greet, say bye, agree, disagree, and ask things
- which languages, and when they switch
- 6 to 10 of their lines that sound most like them, quoted exactly

ABOUT THEM:
Only what they say about themselves: their age, gender, where they live, school or work, hobbies, games, music, pets, \
the first names of people around them, and what is going on in their life. Nothing about anyone else that is not about \
them. Nothing you would have to guess. Never an address, a phone number, an email, a password or anything about money."""

FINAL = """You write the persona a chat bot uses to text exactly like one real person: the person in these notes, who \
asked for it, made from their own messages. Write four parts, each starting with its marker on a line of its own, and \
nothing else.

[NAME]
The name they go by, or nothing if the notes do not say it.

[IDENTITY]
These seven lines, filled in from the notes. Where the notes say nothing, keep the part in square brackets as it is.
Your name is [NAME] and you are [AGE] years old, [GENDER].
You live in [CITY, COUNTRY].
Your job / studies: [JOB OR SCHOOL].
Your hobbies and interests: [HOBBIES].
Your personality in three words: [TRAIT], [TRAIT], [TRAIT].
Things you care about right now: [CURRENT INTERESTS / LIFE SITUATION].
People around you: [FRIENDS / FAMILY / PETS, first names only].

[STYLE]
How they text, as 12 to 20 rules for the bot, one per line, each starting with "- " and speaking to it as "you". Be \
concrete and use the numbers given: their message length, capitals, punctuation, their own emoji, their slang and \
spellings with real examples in quotes, how they laugh, greet, agree and sign off, their languages. Do not mention AI, \
bots or assistants.

[EXAMPLES]
Four short messages they might send, one per line, in their style."""

# What the template says about not sounding like an assistant: still true of anyone, whatever their style.
KEEP_RULES = [
    "- You are not a helpful assistant: no customer-service tone, no \"Sure!\", \"Of course!\", \"Great question!\".",
    "- No bullet points, no numbered lists, no greeting and closing like an email.",
    "- Never use em dashes or en dashes.",
    "- Don't repeat the other person's message back at them, and ask at most one question per message.",
    "- When the conversation naturally ends, let it end.",
]

IDENTITY_KEYS = ("Your name is", "You live in", "Your job / studies:", "Your hobbies and interests:",
                 "Your personality in three words:", "Things you care about right now:", "People around you:")


def _scrub(text: str) -> str:
    """No email or phone number gets into a persona, whatever the model put there. A number is a phone's with nine
    digits or more: a span of years ("2019 - 2021") is not one."""
    text = EMAIL.sub("[EMAIL]", text)
    return PHONE.sub(lambda m: "[NUMBER]" if sum(c.isdigit() for c in m.group(0)) >= 9 else m.group(0), text)


def parse_final(raw: str) -> dict:
    parts: dict = {}
    current = None
    for line in str(raw or "").splitlines():
        head = re.fullmatch(r"\s*\[(NAME|IDENTITY|STYLE|EXAMPLES)\]\s*", line)
        if head:
            current = head.group(1)
            parts[current] = []
        elif current:
            parts[current].append(line.rstrip())
    name = next((ln.strip() for ln in parts.get("NAME", []) if ln.strip()), "")
    name = re.sub(r"[^\w '\-.]", "", name).strip()[:40]
    if name.lower() in ("nothing", "none", "unknown", "[name]", "n/a"):
        name = ""
    identity = {}
    for line in parts.get("IDENTITY", []):
        line = _scrub(line.strip())
        for key in IDENTITY_KEYS:
            if line.startswith(key):
                identity[key] = line
    style = [_scrub(ln.strip()) for ln in parts.get("STYLE", []) if ln.strip().startswith("- ")]
    examples = [_scrub(ln.strip().lstrip("-• ").strip('"')) for ln in parts.get("EXAMPLES", []) if ln.strip()][:4]
    if not name:
        m = re.match(r"Your name is\s+([^\[\]]+?)(?:\s+and you are|[.,]|$)", identity.get("Your name is", ""))
        name = m.group(1).strip()[:40] if m else ""
    return {"name": name, "identity": identity, "style": style[:24], "examples": examples}


def _template() -> str:
    from app.utils.paths import DEFAULTS_DIR
    try:
        return (DEFAULTS_DIR / "instructions.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "Your name is [NAME].\n\n# ── HOW YOU TALK ──\n\n# ── HARD RULES ──\n"


def _with_name(line: str, name: str) -> str:
    if not name:
        return line
    m = re.match(r"(Your name is\s+)(.+?)(\s+and you are.*|[.,].*)?$", line)
    return f"{m.group(1)}{name}{m.group(3) or '.'}" if m else line


def assemble(identity: dict, style: list, name: str) -> str:
    """The template, with who they are and how they text in it, the rest of it kept as it is."""
    lines = _template().splitlines()
    for i, line in enumerate(lines):
        for key in IDENTITY_KEYS:
            if line.startswith(key):
                lines[i] = identity.get(key, line)
                if key == "Your name is":
                    lines[i] = _with_name(lines[i], name) if name else lines[i]
    text = "\n".join(lines)
    section = ("# ── HOW YOU TALK (learned from your own messages) ──\n"
               "This is how you really text. Keep to it.\n" + "\n".join(style) + "\n" + "\n".join(KEEP_RULES) + "\n\n")
    m = re.search(r"^# ── HOW YOU TALK[^\n]*\n.*?(?=^# ── )", text, re.M | re.S)
    if m:
        text = text[:m.start()] + section + text[m.end():]
    else:
        text = text.rstrip() + "\n\n" + section
    return text.rstrip() + "\n"


def settings_for(stats: dict, name: str) -> dict:
    """The settings its numbers call for: how long its messages are, and the emojis it reacts with."""
    from app.utils.helpers import load_base_config
    length = int(stats.get("median_length") or 0)
    burst = float(stats.get("burst") or 1)
    mode = "short" if length <= 28 and burst >= 1.3 or length <= 18 else "chatty" if length >= 80 else "balanced"
    theirs = [e for e, c in (stats.get("emoji_counts") or {}).items() if c >= 2 and len(e.replace("️", "")) == 1]
    out = {"bot.message_style.mode": mode}
    if theirs:
        try:
            defaults = list(((load_base_config() or {}).get("bot") or {}).get("reactions", {}).get("emojis") or [])
        except (Exception, SystemExit):
            defaults = []
        emojis = theirs[:24]
        for e in defaults:
            if len(emojis) >= 12:
                break
            if e not in emojis:
                emojis.append(e)
        out["bot.reactions.emojis"] = emojis
    if name:
        out["bot.trigger"] = name
    return out


def name_hint() -> str:
    """What the owner is called, for when their messages never say it: the name an export gives its owner. Not an id."""
    j = job()
    with _lock:
        names = [r.get("owner") or "" for r in j["files"].values() if r.get("count") and not r.get("why")]
    for n in names:
        n = str(n).strip()
        if n and not n.isdigit():
            return n[:40]
    return ""


def _all_messages() -> list:
    j = job()
    out = []
    for f in sorted(j["dir"].glob("*.jsonl")):
        source = f.name[:-6]
        for m in _read_jsonl(f):
            out.append({**m, "source": source})
    return out


def _ai_ready() -> str:
    from app.utils import ai
    if ai._initialised:
        return ""
    try:
        ai.init_ai()
    except SystemExit:
        return "No model is set up. Add one under Settings, Models."
    except Exception as e:
        return f"The AI could not start: {e}"[:200]
    return ""


def _say(**kw) -> None:
    with _lock:
        job()["write"].update(kw)


async def _ask(prompt: str, instructions: str, budget: int) -> str:
    """The model's answer, asked again with twice the room when it comes back empty: a model that reasons before it
    answers (gpt-oss) can spend the whole of a budget thinking, and say nothing."""
    from app.utils import ai
    said = await ai.condense(prompt, instructions, max_tokens=budget)
    if not said.strip():
        said = await ai.condense(prompt, instructions, max_tokens=budget * 2)
    return said.strip()


async def write() -> None:
    """Read what was gathered and write the persona: progress on the job as it goes, the result on it at the end."""
    _say(state="writing", step="reading", done=0, total=0, why="")
    with _lock:
        job()["result"] = None
    try:
        messages = clean(await asyncio.to_thread(_all_messages))
        if len(messages) < MIN_MESSAGES:
            return _say(state="failed", why=f"Only {len(messages)} of your messages to go on, too few to know how you "
                                            "text. Add another export.")
        stats = measure(messages)
        picked = sample(messages)
        batches = [picked[i:i + BATCH] for i in range(0, len(picked), BATCH)]
        why = await asyncio.to_thread(_ai_ready)
        if why:
            return _say(state="failed", why=why)
        notes = []
        for i, batch in enumerate(batches):
            _say(step="notes", done=i, total=len(batches))
            lines = "\n".join(f"[{time.strftime('%Y-%m', time.localtime(m['ts'] or 0))}] {m['text'][:300]}" for m in batch)
            note = await _ask("Their messages:\n\n" + lines, NOTES, 3000)
            if note:
                notes.append(note)
        if not notes:
            return _say(state="failed", why="The model did not answer. Check Settings, Models, and try again.")
        _say(step="writing", done=len(batches), total=len(batches))
        numbers = (f"Measured over {stats['messages']} of their messages: a typical message is {stats['median_length']} "
                   f"characters; {int(stats['lowercase'] * 100)}% start in lowercase; {int(stats['ends_with_period'] * 100)}% "
                   f"end with a full stop; {int(stats['with_emoji'] * 100)}% have an emoji "
                   f"({' '.join(stats['top_emoji'][:8]) or 'none'}); laughs: {', '.join(stats['laughs']) or 'none'}; "
                   f"they send about {stats['burst']} messages in a row.")
        raw = await _ask(numbers + "\n\nThe notes:\n\n" + "\n\n---\n\n".join(notes), FINAL, 4000)
        parsed = parse_final(raw)
        # Their messages never said their name: the one their export goes by.
        parsed["name"] = parsed["name"] or name_hint()
        if len(parsed["style"]) < 4:
            return _say(state="failed", why="The model's answer was not a persona. Try again, or pick another model "
                                            "for background work under Settings, Models.")
        result = {**parsed, "text": assemble(parsed["identity"], parsed["style"], parsed["name"]),
                  "settings": settings_for(stats, parsed["name"]), "count": len(messages),
                  "stats": {k: stats[k] for k in ("messages", "median_length", "lowercase", "with_emoji", "top_emoji",
                                                  "laughs", "burst")}}
        with _lock:
            job()["result"] = result
        _say(state="done", step="", why="")
    except Exception as e:
        _say(state="failed", why=f"It could not be written: {e}"[:300])


# ── Making it ─────────────────────────────────────────────────────────────────

def create(name: str, color: str = "", color2: str = "") -> dict:
    """The persona, made: its text, and its settings. Nothing that exists is changed, and no account is given it."""
    from app.utils import personas
    with _lock:
        result = (job() or {}).get("result")
    if not result:
        raise ValueError("Nothing has been written yet.")
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:40] or result.get("name") or "From my chats"
    made = personas.create(name, color, color2=color2)
    pid = made["id"]
    personas.save_text(pid, assemble(result["identity"], result["style"], name), backup=False)
    settings = dict(personas.overrides(pid))
    settings.update({**result["settings"], "bot.trigger": name})
    personas.set_overrides(pid, settings)
    reset()
    return personas.get(pid) or made
