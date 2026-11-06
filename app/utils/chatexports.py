"""The files the socials let you download of your own data, read for the messages their owner wrote.

Each social has a "download your data" page, and what comes out is a zip (or a single file) in a shape of its own. This
reads the ones the app's platforms have: Discord's data package, Instagram's, Snapchat's, TikTok's, X's archive,
Reddit's, a Telegram Desktop export, and a WhatsApp chat export.

Only the owner's messages come out, and the file itself says whose they are: Discord's package holds nothing else,
Snapchat's marks the sender, Telegram's and X's name their account, Instagram's and TikTok's give the profile, Reddit's
the username. A WhatsApp chat says none of that, so its senders are handed back as they are and the owner is the name
in every chat dropped in (chatpersona.py). There is no way here to ask for anyone else's side.

read() returns {"platform", "label", "owner", "messages": [{"ts", "text", "chat"}], "senders" (WhatsApp only), "why"}.
A file it cannot read raises NotAnExport, with what to do in its words.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Bigger than any file of messages in an export: what is past this in a zip is media, or not an export.
MEMBER_MAX = 300 * 1024 * 1024


class NotAnExport(ValueError):
    pass


# ── Small helpers ─────────────────────────────────────────────────────────────

def _ts(value) -> float:
    """Seconds since 1970 from whatever an export wrote: a number of seconds or milliseconds, or a date in words."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)) or re.fullmatch(r"\d{9,16}(\.\d+)?", str(value).strip()):
        n = float(value)
        return n / 1000.0 if n > 1e12 else n
    text = str(value).strip().replace(" UTC", "+00:00").replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def _fix(text: str) -> str:
    """Instagram writes its text as UTF-8 bytes read as Latin-1 ("cafÃ©" for "café"): undone, where it is that."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _msg(ts, text, chat) -> dict | None:
    text = str(text or "").strip()
    return {"ts": _ts(ts), "text": text, "chat": str(chat or "")} if text else None


def _members(zf: zipfile.ZipFile, pattern: str) -> list[str]:
    rx = re.compile(pattern, re.I)
    return sorted(i.filename for i in zf.infolist() if rx.search(i.filename.replace("\\", "/"))
                  and 0 < i.file_size <= MEMBER_MAX)


def _read(zf: zipfile.ZipFile, name: str) -> str:
    with zf.open(name) as fh:
        return fh.read().decode("utf-8-sig", "replace")


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError as e:
        raise NotAnExport(f"It is not the JSON it should be ({e}).") from None


def _ytd(text: str):
    """X's archive files are JavaScript: `window.YTD.direct_messages.part0 = [...]`."""
    return _json(text[text.index("=") + 1:] if "=" in text[:200] else text)


# ── Discord: the data package ─────────────────────────────────────────────────

def _discord(zf: zipfile.ZipFile) -> dict:
    names = {}
    for idx in _members(zf, r"(^|/)messages/index\.json$"):
        try:
            names.update({str(k): str(v or "") for k, v in (_json(_read(zf, idx)) or {}).items()})
        except NotAnExport:
            pass
    owner = ""
    for user in _members(zf, r"(^|/)account/user\.json$"):
        try:
            owner = str((_json(_read(zf, user)) or {}).get("username") or "")
        except NotAnExport:
            pass
    out = []
    for name in _members(zf, r"(^|/)messages/c?\d+/messages\.(json|csv)$"):
        cid = re.search(r"messages/c?(\d+)/", name.replace("\\", "/")).group(1)
        chat = names.get(cid) or f"Channel {cid}"
        text = _read(zf, name)
        rows = _json(text) if name.lower().endswith(".json") else list(csv.DictReader(io.StringIO(text)))
        for r in rows or []:
            m = _msg(r.get("Timestamp") or r.get("timestamp"), r.get("Contents") or r.get("contents"), chat)
            if m:
                out.append(m)
    return {"platform": "discord", "label": "Discord data package", "owner": owner, "messages": out}


# ── Instagram ─────────────────────────────────────────────────────────────────

_IG_NOISE = re.compile(r"^(liked a message|reacted .{1,8} to your message|.{0,60} sent an attachment\.|"
                       r"you sent an attachment\.|.{0,60} shared a story\.|this message was unsent\.)$", re.I)


def _instagram_threads(threads: list[dict], profile_name: str, known: set) -> dict:
    everyone = [{_fix(str(p.get("name") or "")) for p in t.get("participants") or []} for t in threads]
    owner = _fix(profile_name) if profile_name else ""
    if not owner:
        common = set.intersection(*everyone) if everyone else set()
        if len(common) == 1:
            owner = next(iter(common))
        else:
            hit = [n for n in (common or set().union(*everyone) if everyone else set()) if n in known]
            owner = hit[0] if len(hit) == 1 else ""
    if not owner:
        raise NotAnExport("It can't tell which messages are yours from this file alone. Drop the whole Instagram "
                          "export (the .zip), so it can.")
    out = []
    for t, people in zip(threads, everyone):
        chat = _fix(str(t.get("title") or "")) or ", ".join(sorted(p for p in people if p != owner)) or "Instagram"
        for m in t.get("messages") or []:
            if _fix(str(m.get("sender_name") or "")) != owner:
                continue
            text = _fix(str(m.get("content") or ""))
            if text and not _IG_NOISE.match(text.strip()):
                one = _msg(m.get("timestamp_ms"), text, chat)
                if one:
                    out.append(one)
    return {"platform": "instagram", "label": "Instagram export", "owner": owner, "messages": out}


def _instagram(zf: zipfile.ZipFile, known: set) -> dict:
    threads = []
    for name in _members(zf, r"(^|/)messages/(inbox|message_requests)/[^/]+/message_\d+\.json$"):
        try:
            threads.append(_json(_read(zf, name)))
        except NotAnExport:
            pass
    profile = ""
    for name in _members(zf, r"personal_information\.json$"):
        try:
            data = _json(_read(zf, name))
            row = (data.get("profile_user") or [{}])[0].get("string_map_data") or {}
            profile = str((row.get("Name") or row.get("Username") or {}).get("value") or "")
        except (NotAnExport, AttributeError, IndexError):
            pass
    return _instagram_threads(threads, profile, known)


# ── Snapchat ──────────────────────────────────────────────────────────────────

def _snapchat(data) -> dict:
    out = []
    if isinstance(data, dict) and ("Sent Saved Chat History" in data or "Received Saved Chat History" in data):
        # The older shape: what was sent is a list of its own.
        for r in data.get("Sent Saved Chat History") or []:
            m = _msg(r.get("Created"), r.get("Text") or r.get("Content"), r.get("To"))
            if m:
                out.append(m)
    elif isinstance(data, dict) and any(isinstance(r, dict) and "IsSender" in r
                                        for rows in data.values() if isinstance(rows, list) for r in rows[:5]):
        for friend, rows in data.items():
            for r in rows if isinstance(rows, list) else []:
                if not isinstance(r, dict) or not r.get("IsSender"):
                    continue
                if str(r.get("Media Type") or "TEXT").upper() not in ("TEXT", ""):
                    continue
                micros = r.get("Created(microseconds)")
                m = _msg(float(micros) / 1e6 if micros else r.get("Created"), r.get("Content"),
                         r.get("Conversation Title") or friend)
                if m:
                    out.append(m)
    else:
        raise NotAnExport("This is not an export this knows. It reads Discord, Instagram, Snapchat, TikTok, X, "
                          "Reddit, Telegram and WhatsApp ones.")
    return {"platform": "snapchat", "label": "Snapchat export", "owner": "", "messages": out}


# ── TikTok ────────────────────────────────────────────────────────────────────

def _find(data, *keys):
    """The first of these keys anywhere in a nest of dicts: TikTok has renamed its sections more than once."""
    if isinstance(data, dict):
        for k in keys:
            if k in data:
                return data[k]
        for v in data.values():
            hit = _find(v, *keys)
            if hit is not None:
                return hit
    return None


def _tiktok(data) -> dict:
    # From its profile: other sections have usernames too (who it follows), and none of them is the owner.
    profile = data.get("Profile") if isinstance(data, dict) and isinstance(data.get("Profile"), dict) else data
    owner = str(_find(profile, "userName", "Username", "username") or "").strip()
    # "ChatHistory" sits inside a "Chat History" section: the inner one is the chats.
    chats = _find(data, "ChatHistory")
    if chats is None:
        chats = _find(data, "Chat History") or {}
    if not owner:
        raise NotAnExport("This TikTok export has no profile in it, so it can't tell which messages are yours.")
    out = []
    for title, rows in (chats.items() if isinstance(chats, dict) else []):
        chat = re.sub(r"^Chat History with\s*|:$", "", str(title)).strip()
        for r in rows or []:
            if isinstance(r, dict) and str(r.get("From") or "").strip().lower() == owner.lower():
                m = _msg(r.get("Date"), r.get("Content"), chat)
                if m:
                    out.append(m)
    return {"platform": "tiktok", "label": "TikTok export", "owner": owner, "messages": out}


def _tiktok_txt(text: str) -> dict:
    owner = (re.search(r"^Username:\s*(\S+)", text, re.M) or [None, ""])[1]
    if not owner:
        raise NotAnExport("This TikTok export has no profile in it, so it can't tell which messages are yours.")
    out, chat = [], "TikTok"
    for block in re.split(r"\n\s*\n", text):
        head = re.match(r"\s*Chat History with\s*(.+?):?\s*$", block, re.M)
        if head and "Date:" not in block.split("\n", 1)[0]:
            chat = head.group(1)
        date = re.search(r"Date:\s*(.+)", block)
        sender = re.search(r"From:\s*(.+)", block)
        content = re.search(r"Content:\s*(.*)", block, re.S)
        if date and sender and content and sender.group(1).strip().lower() == owner.lower():
            m = _msg(date.group(1).strip(), content.group(1), chat)
            if m:
                out.append(m)
    return {"platform": "tiktok", "label": "TikTok export", "owner": owner, "messages": out}


# ── X ─────────────────────────────────────────────────────────────────────────

def _x(zf: zipfile.ZipFile) -> dict:
    me, owner = "", ""
    for name in _members(zf, r"(^|/)data/account\.js$"):
        acct = (_ytd(_read(zf, name)) or [{}])[0].get("account") or {}
        me, owner = str(acct.get("accountId") or ""), str(acct.get("username") or "")
    if not me:
        raise NotAnExport("This X archive has no account.js, so it can't tell which messages are yours.")
    out = []
    for name in _members(zf, r"(^|/)data/direct-messages(-group)?\.js$"):
        for conv in _ytd(_read(zf, name)) or []:
            c = conv.get("dmConversation") or {}
            chat = str(c.get("name") or c.get("conversationId") or "X")
            for m in c.get("messages") or []:
                mc = m.get("messageCreate") or {}
                if str(mc.get("senderId") or "") == me:
                    one = _msg(mc.get("createdAt"), re.sub(r"\s*https://t\.co/\S+$", "", str(mc.get("text") or "")), chat)
                    if one:
                        out.append(one)
    return {"platform": "x", "label": "X archive", "owner": owner, "messages": out}


# ── Reddit ────────────────────────────────────────────────────────────────────

def _reddit(files: dict[str, str]) -> dict:
    """`files`: the export's CSVs by name. Its messages hold both sides, so the owner is the name in every one of them
    (the account's own, from its statistics, when the export has them); comments and chats are all its own."""
    owner = ""
    stats = files.get("statistics.csv") or ""
    for row in csv.DictReader(io.StringIO(stats)):
        if str(row.get("statistic") or "").lower() in ("account name", "username"):
            owner = str(row.get("value") or "")
    messages = [r for k in ("messages.csv", "messages_archive.csv") for r in csv.DictReader(io.StringIO(files.get(k) or ""))]
    if not owner and messages:
        common = set.intersection(*[{str(r.get("from") or ""), str(r.get("to") or "")} for r in messages])
        common.discard("")
        if len(common) == 1:
            owner = next(iter(common))
    out = []
    for r in messages:
        if owner and str(r.get("from") or "") == owner:
            m = _msg(r.get("date"), r.get("body"), r.get("to") or r.get("subject") or "Reddit")
            if m:
                out.append(m)
    for r in csv.DictReader(io.StringIO(files.get("comments.csv") or "")):
        m = _msg(r.get("date"), r.get("body"), r.get("subreddit") and f"r/{r['subreddit']}" or "Reddit comments")
        if m:
            out.append(m)
    for r in csv.DictReader(io.StringIO(files.get("chat_history.csv") or "")):
        if owner and str(r.get("username") or "") == owner:
            m = _msg(r.get("created_at"), r.get("message"), r.get("channel_url") or "Reddit chat")
            if m:
                out.append(m)
    if not out and messages and not owner:
        raise NotAnExport("It can't tell which of these messages are yours. Drop the whole Reddit export (the .zip).")
    return {"platform": "reddit", "label": "Reddit export", "owner": owner, "messages": out}


# ── Telegram Desktop ──────────────────────────────────────────────────────────

def _tg_text(text) -> str:
    if isinstance(text, list):
        return "".join(t if isinstance(t, str) else str((t or {}).get("text") or "") for t in text)
    return str(text or "")


def _telegram(data, known_ids: set) -> dict:
    info = data.get("personal_information") or {}
    me = str(info.get("user_id") or "")
    shown = " ".join(str(info.get(k) or "") for k in ("first_name", "last_name")).strip()
    chats = ((data.get("chats") or {}).get("list")) if isinstance(data.get("chats"), dict) else None
    if chats is None and "messages" in data:
        chats = [data]                           # one chat, exported on its own
    ids = {f"user{me}"} if me else {f"user{i}" for i in known_ids}
    if not ids:
        raise NotAnExport("This Telegram chat was exported on its own, so it can't tell which messages are yours. "
                          "Export all your data from Telegram Desktop instead, or add your Telegram account first.")
    out = []
    for c in chats or []:
        chat = str(c.get("name") or "Telegram")
        for m in c.get("messages") or []:
            if m.get("type") == "message" and str(m.get("from_id") or "") in ids:
                one = _msg(m.get("date_unixtime") or m.get("date"), _tg_text(m.get("text")), chat)
                if one:
                    out.append(one)
    return {"platform": "telegram", "label": "Telegram export", "owner": shown or me, "messages": out}


# ── WhatsApp ──────────────────────────────────────────────────────────────────

_WA_LINE = re.compile(
    r"^‎?\[?(?P<a>\d{1,2})[/.](?P<b>\d{1,2})[/.](?P<y>\d{2,4}),? (?P<t>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?)"
    r"(?:\s?(?P<ap>[AaPp]\.?\s?[Mm]\.?))?\]?(?: -|:)? (?P<rest>.*)$")
_WA_SKIP = re.compile(r"^‎?(<media omitted>|<attached: .*>|(image|video|audio|sticker|gif|document) omitted|"
                      r"this message was deleted|you deleted this message|missed (voice|video) call|null|"
                      r"<this message was edited>)$", re.I)


def whatsapp(text: str, chat: str) -> dict:
    """A WhatsApp chat export, with every sender's messages: which of them is the owner, a chat cannot say."""
    text = text.replace(" ", " ").replace(" ", " ")
    lines = text.splitlines()
    parsed, pairs = [], []
    for line in lines:
        m = _WA_LINE.match(line)
        if m:
            parsed.append([m, line])
            pairs.append((int(m["a"]), int(m["b"])))
        elif parsed:
            parsed[-1].append(line)                # a message on several lines
    if not parsed:
        raise NotAnExport("This is not a WhatsApp chat export.")
    # 31/12 or 12/31: whichever of the two numbers goes past 12 somewhere is the day.
    day_first = not any(b > 12 for _, b in pairs) or any(a > 12 for a, _ in pairs)
    senders: dict = {}
    for m, _line, *more in parsed:
        rest = m["rest"].replace("‎", "")
        if ": " not in rest:
            continue                                # the chat's own news: someone joined, the number changed
        who, said = rest.split(": ", 1)
        said = "\n".join([said, *more]).strip()
        if not said or _WA_SKIP.match(said):
            continue
        day, month = (int(m["a"]), int(m["b"])) if day_first else (int(m["b"]), int(m["a"]))
        year = int(m["y"]) + (2000 if len(m["y"]) == 2 else 0)
        hh, mm = (int(x) for x in re.split(r"[:.]", m["t"])[:2])
        if m["ap"]:
            pm = m["ap"].lower().startswith("p")
            hh = (hh % 12) + (12 if pm else 0)
        try:
            ts = datetime(year, month, day, hh, mm).timestamp()
        except ValueError:
            continue
        senders.setdefault(who.strip(), []).append({"ts": ts, "text": said, "chat": chat})
    return {"platform": "whatsapp", "label": f"WhatsApp chat: {chat}", "owner": "", "messages": [], "senders": senders}


def _wa_chat_name(name: str) -> str:
    base = Path(name).stem
    return re.sub(r"^WhatsApp Chat (with|-) ", "", base).strip() or "WhatsApp"


# ── Which it is ───────────────────────────────────────────────────────────────

def read(path, name: str, known: dict | None = None) -> list[dict]:
    """What is in a file dropped in: one result, or several for a zip of WhatsApp chats. `known` is what the app knows
    of the owner already, {platform: {names or ids}}, for a file that cannot say on its own."""
    path, known = Path(path), known or {}
    lower = name.lower()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            if _members(zf, r"(^|/)messages/c?\d+/messages\.(json|csv)$"):
                return [_discord(zf)]
            if _members(zf, r"(^|/)messages/(inbox|message_requests)/[^/]+/message_\d+\.json$"):
                return [_instagram(zf, set(known.get("instagram") or ()))]
            if _members(zf, r"(^|/)data/direct-messages(-group)?\.js$"):
                return [_x(zf)]
            for hit in _members(zf, r"(^|/)chat_history\.json$"):
                return [_snapchat(_json(_read(zf, hit)))]
            for hit in _members(zf, r"(^|/)user_data(_tiktok)?\.json$"):
                return [_tiktok(_json(_read(zf, hit)))]
            for hit in _members(zf, r"(^|/)user_data(_tiktok)?\.txt$"):
                return [_tiktok_txt(_read(zf, hit))]
            for hit in _members(zf, r"(^|/)result\.json$"):
                return [_telegram(_json(_read(zf, hit)), set(known.get("telegram") or ()))]
            csvs = _members(zf, r"(^|/)(messages|messages_archive|comments|chat_history|statistics)\.csv$")
            if csvs:
                return [_reddit({Path(n).name.lower(): _read(zf, n) for n in csvs})]
            chats = []
            for hit in _members(zf, r"\.txt$"):
                try:
                    chats.append(whatsapp(_read(zf, hit), _wa_chat_name(name if hit.endswith("_chat.txt") else hit)))
                except NotAnExport:
                    pass
            if chats:
                return chats
        raise NotAnExport(f"{name} is not an export this knows. It reads Discord, Instagram, Snapchat, TikTok, X, "
                          "Reddit, Telegram and WhatsApp ones.")
    text = path.read_bytes()[:MEMBER_MAX].decode("utf-8-sig", "replace")
    if lower.endswith(".json"):
        data = _json(text)
        if isinstance(data, dict) and "participants" in data and "messages" in data:
            return [_instagram_threads([data], "", set(known.get("instagram") or ()))]
        if isinstance(data, dict) and ("personal_information" in data or "chats" in data
                                       or data.get("type") in ("personal_chat", "private_group", "private_supergroup")):
            return [_telegram(data, set(known.get("telegram") or ()))]
        if isinstance(data, list) and data and isinstance(data[0], dict) and ("Contents" in data[0] or "ID" in data[0]):
            return [{"platform": "discord", "label": "Discord messages", "owner": "",
                     "messages": [m for m in (_msg(r.get("Timestamp"), r.get("Contents"), "Discord") for r in data) if m]}]
        if _find(data, "ChatHistory", "Chat History") is not None:
            return [_tiktok(data)]
        if isinstance(data, dict):
            return [_snapchat(data)]
    if lower.endswith(".csv"):
        return [_reddit({Path(name).name.lower(): text})]
    if lower.endswith(".js"):
        raise NotAnExport("Drop the whole X archive (the .zip): the account it is from is in another file in it.")
    if lower.endswith(".txt"):
        if "Chat History with" in text and "Content:" in text:
            return [_tiktok_txt(text)]
        return [whatsapp(text, _wa_chat_name(name))]
    raise NotAnExport(f"{name} is not an export this knows. It reads Discord, Instagram, Snapchat, TikTok, X, Reddit, "
                      "Telegram and WhatsApp ones.")


def whatsapp_owner(chats: list[dict], known: set) -> str:
    """Which sender is the owner across WhatsApp chats: the one name in all of them, or a name the app knows is
    theirs. "" when it can't tell, and none of them is used."""
    names = [set(c.get("senders") or {}) for c in chats]
    if not names:
        return ""
    common = set.intersection(*names)
    if len(names) > 1 and len(common) == 1:
        return next(iter(common))
    hits = [n for n in set.union(*names) if n in known]
    return hits[0] if len(hits) == 1 else ""
