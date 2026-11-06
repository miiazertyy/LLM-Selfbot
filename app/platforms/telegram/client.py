"""app/platforms/telegram/client.py - the persona's Telegram account, through Telethon.

Telegram publishes its client API (MTProto), so this is a real account doing what a person's account does: reading
its chats, typing, answering, reacting, editing, sending photos and voice notes, and so on. Telethon is asyncio, so
there is no Node runner and no browser: the client lives on the bridge's own event loop
(app/platforms/snapchat_bridge.py, _telegram_main), which keeps the reply pipeline, the chat log, the people, the
stats and the panel's commands exactly as every other platform has them.

What this module owns is Telegram and nothing else: connecting, its events, and the calls that do things. What to
answer, and when, is the bridge's and the engine's, as always.
"""
from __future__ import annotations

import asyncio
import os
import random
import re
import time
import uuid
from pathlib import Path

from app.platforms.telegram import people

# A gift link someone sends in a chat: Telegram Premium, the way a Nitro gift arrives on Discord.
GIFT_RE = re.compile(r"(?:https?://)?t\.me/giftcode/([A-Za-z0-9_-]{6,64})", re.I)
# What a message is when it is not words, in the brackets the rest of the app uses.
KINDS = {"photo": "[image]", "video": "[video]", "voice": "[voice message]", "round": "[video note]",
         "sticker": "[sticker]", "gif": "[gif]", "file": "[file]", "poll": "[poll]", "location": "[location]",
         "contact": "[contact]", "story": "[story]"}


class Flood(Exception):
    """Telegram asked for a wait: how long, and what it was doing."""

    def __init__(self, seconds: int, doing: str = ""):
        super().__init__(f"Telegram asked to wait {seconds} s")
        self.seconds = int(seconds or 0)
        self.doing = doing


class Governor:
    """How often it may send, as the Node runners govern theirs (runner_core.js): a random gap between sends, a cap
    an hour, and quiet hours. A fresh account is what Telegram limits, so these start gentler than the others."""

    def __init__(self, min_gap_ms=8000, max_gap_ms=30000, per_hour=30, quiet=""):
        self.min_gap = max(0, int(min_gap_ms)) / 1000.0
        self.max_gap = max(self.min_gap, int(max_gap_ms) / 1000.0)
        self.per_hour = max(1, int(per_hour))
        self.quiet = str(quiet or "")
        self._sent: list = []
        self._last = 0.0
        self._gap = 0.0
        self.hold_until = 0.0            # a flood wait Telegram asked for

    def quiet_now(self) -> bool:
        m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", self.quiet)
        if not m:
            return False
        start, end = int(m.group(1)) % 24, int(m.group(2)) % 24
        h = time.localtime().tm_hour
        return start <= h < end if start <= end else (h >= start or h < end)

    def wait_for(self) -> float:
        """Seconds to wait before the next send may go out, 0 when it may go now."""
        now = time.time()
        if now < self.hold_until:
            return self.hold_until - now
        if self.quiet_now():
            return 60.0
        self._sent = [t for t in self._sent if now - t < 3600]
        if len(self._sent) >= self.per_hour:
            return max(1.0, 3600 - (now - self._sent[0]))
        return max(0.0, self._gap - (now - self._last))

    def sent(self) -> None:
        self._last = time.time()
        self._sent.append(self._last)
        self._gap = self.min_gap + random.random() * (self.max_gap - self.min_gap)
        if random.random() < 0.08:
            self._gap += 120 + random.random() * 180      # drifting off for a few minutes, as a person does

    def hold(self, seconds: float) -> None:
        self.hold_until = max(self.hold_until, time.time() + max(0.0, float(seconds)))


class Telegram:
    """One Telegram account. The bridge gives it callbacks and then lets it run."""

    def __init__(self, api_id: int, api_hash: str, session: str, *, data_dir: Path, log=print,
                 on_message=None, on_changed=None, on_reaction=None, on_typing=None, on_call=None,
                 on_state=None, governor: Governor | None = None, proxy: str = ""):
        self.api_id, self.api_hash, self.session = int(api_id), str(api_hash), str(session)
        self.proxy = str(proxy or "")
        self.data_dir = Path(data_dir)
        self.log = log
        self.on_message = on_message or (lambda entry: None)
        self.on_changed = on_changed or (lambda kind, chat, mid, text: None)
        self.on_reaction = on_reaction or (lambda chat, mid, reactions: None)
        self.on_typing = on_typing or (lambda chat, on: None)
        self.on_call = on_call or (lambda chat, name, call: None)
        self.on_state = on_state or (lambda state, detail="": None)
        self.governor = governor or Governor()
        self.client = None
        self.me = None
        self.names: list = []            # what it answers to in a group
        self.answer_groups = False
        self.answer_channels = False
        self.keep_media = True
        self._stop = asyncio.Event()
        self._entities: dict = {}

    # ── Connecting ───────────────────────────────────────────────────────────

    async def start(self) -> dict:
        """Connect and say who it is. Raises when the session is no longer good, which means signing in again."""
        import logging
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from app.utils import proxies
        # Telethon's own debug lines carry connection details; the panel's Logs tab is no place for them.
        logging.getLogger("telethon").setLevel(logging.WARNING)
        self.client = TelegramClient(
            StringSession(self.session), self.api_id, self.api_hash,
            device_model="Desktop", system_version="Windows", app_version="1.0", proxy=proxies.for_telethon(self.proxy),
            auto_reconnect=True, retry_delay=5, connection_retries=-1,
            # Every wait Telegram asks for reaches us: left to itself Telethon sleeps through the short ones
            # inside the call, which hides a limit instead of showing it on the card.
            flood_sleep_threshold=0,
            # One message at a time, in the order they arrived, and whatever was missed while it was away.
            sequential_updates=True, catch_up=True)
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise PermissionError("Telegram no longer takes this sign-in. Sign the account in again.")
        self.me = await self.client.get_me()
        self._wire()
        return self.who()

    def who(self) -> dict:
        me = self.me
        return {
            "id": int(getattr(me, "id", 0) or 0),
            "username": str(getattr(me, "username", "") or ""),
            "name": people.name_of(me) if me is not None else "",
            "phone": str(getattr(me, "phone", "") or ""),
            "premium": bool(getattr(me, "premium", False)),
        }

    def _wire(self) -> None:
        from telethon import events
        from telethon.tl import types as t
        self.client.add_event_handler(self._incoming, events.NewMessage(incoming=True))
        self.client.add_event_handler(self._own, events.NewMessage(outgoing=True))
        self.client.add_event_handler(self._edited, events.MessageEdited(incoming=True))
        self.client.add_event_handler(self._deleted, events.MessageDeleted())
        self.client.add_event_handler(self._raw, events.Raw(types=[
            t.UpdateUserTyping, t.UpdateChatUserTyping, t.UpdateMessageReactions, t.UpdatePhoneCall]))

    async def run(self) -> None:
        """Stay connected until stop() is called. Telethon reconnects by itself; this notices when it has given up
        for good (a session pulled from Telegram's own Devices list) and says so rather than sitting there dead."""
        self.on_state("ready")
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
                return
            except asyncio.TimeoutError:
                pass
            if self.client is None or self.client.is_connected():
                continue
            try:
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    self.on_state("logged-out", "Telegram no longer takes this sign-in. Sign the account in again.")
                    return
                self.on_state("ready")
            except Exception as e:
                self.on_state("logged-out", f"Lost its connection to Telegram: {e}")

    async def stop(self) -> None:
        self._stop.set()
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass

    # ── What arrives ─────────────────────────────────────────────────────────

    async def _incoming(self, event) -> None:
        try:
            await self._read_message(event)
        except Exception as e:
            self.log(f"A message could not be read: {e}")

    async def _read_message(self, event) -> None:
        msg = event.message
        chat = await event.get_chat()
        group = bool(event.is_group or event.is_channel)
        if event.is_channel and not event.is_group:
            # A channel it follows: context, never answered (nobody is talking to it).
            if not self.answer_channels:
                return
        sender = await event.get_sender()
        chat_uid = people.chat_id_of(chat, group=group)
        who = people.name_of(sender) if sender is not None else people.name_of(chat)
        self._entities[chat_uid] = chat
        text = (msg.message or "").strip()
        entry = {
            "id": f"tg{uuid.uuid4().hex}", "user_id": chat_uid, "user_name": who, "channel_id": chat_uid,
            "content": text, "ts": msg.date.timestamp() if msg.date else time.time(),
            "mid": str(msg.id), "react_to": str(msg.id), "photo": True, "voice": True,
        }
        if group:
            entry["group"] = True
            entry["user_name"] = people.name_of(chat)
            entry["speaker"] = who
            # In a group it answers only when called: its name, its @username, or a reply to something it said.
            replied = await self._replies_to_me(msg)
            if not (replied or people.mentioned(text, self.names)):
                entry["quiet"] = True
        if msg.reply_to and not group:
            entry["reply_to_mid"] = str(getattr(msg.reply_to, "reply_to_msg_id", "") or "")
        await self._media_into(msg, entry)
        gift = GIFT_RE.search(text)
        if gift:
            entry["gift"] = gift.group(1)
        if not entry.get("content") and not entry.get("image_url") and not entry.get("kind"):
            return
        self.on_message(entry)

    async def _replies_to_me(self, msg) -> bool:
        try:
            if not msg.reply_to:
                return False
            replied = await msg.get_reply_message()
            return bool(replied and replied.out)
        except Exception:
            return False

    async def _media_into(self, msg, entry: dict) -> None:
        """What a message carries, as the bridge wants it: a file:// for anything it reads itself (a picture for the
        vision model, a voice note for Whisper, a video to watch), and a word in brackets for the rest."""
        kind = self.kind_of(msg)
        if not kind:
            return
        entry["kind"] = kind
        if not entry.get("content"):
            entry["content"] = KINDS.get(kind, "")
        if not self.keep_media or kind in ("poll", "location", "contact", "story"):
            return
        where = {"photo": "image_url", "video": "video_url", "voice": "audio_url", "round": "video_url",
                 "sticker": "image_url", "gif": "video_url"}.get(kind)
        if not where:
            return
        if kind == "sticker":
            # A still sticker is a picture the vision model can read; an animated one (.tgs, .webm) is not, and its
            # emoji says more than a file nothing here can open.
            mime = str(getattr(getattr(msg, "document", None), "mime_type", "") or "")
            emoji = str(getattr(msg, "file", None) and getattr(msg.file, "emoji", "") or "")
            entry["content"] = f"[sticker{': ' + emoji if emoji else ''}]"
            if not mime.startswith("image/"):
                return
        try:
            folder = self.data_dir / "config" / "temp"
            folder.mkdir(parents=True, exist_ok=True)
            path = await self.client.download_media(msg, file=str(folder / f"tg_{uuid.uuid4().hex[:12]}"))
            if path:
                entry[where] = Path(path).as_uri()
        except Exception as e:
            self.log(f"Could not fetch what they sent: {e}")

    @staticmethod
    def kind_of(msg) -> str:
        """What a message is, when it is not only words."""
        if getattr(msg, "poll", None):
            return "poll"
        if getattr(msg, "geo", None):
            return "location"
        if getattr(msg, "contact", None):
            return "contact"
        if getattr(msg, "sticker", None):
            return "sticker"
        if getattr(msg, "gif", None):
            return "gif"
        if getattr(msg, "voice", None):
            return "voice"
        if getattr(msg, "video_note", None):
            return "round"
        if getattr(msg, "video", None):
            return "video"
        if getattr(msg, "photo", None):
            return "photo"
        if getattr(msg, "document", None):
            return "file"
        return ""

    async def _own(self, event) -> None:
        """Something sent from Telegram itself (your phone, or Telegram on another computer): kept, so the
        conversation in the panel is the whole conversation, and so it does not answer what you just answered."""
        msg = event.message
        chat = await event.get_chat()
        group = bool(event.is_group or event.is_channel)
        self.on_changed("mine", people.chat_id_of(chat, group=group), str(msg.id), (msg.message or "").strip())

    async def _edited(self, event) -> None:
        msg = event.message
        chat = await event.get_chat()
        group = bool(event.is_group or event.is_channel)
        self.on_changed("edited", people.chat_id_of(chat, group=group), str(msg.id), (msg.message or "").strip())

    async def _deleted(self, event) -> None:
        chat = None
        try:
            entity = await event.get_chat()
            chat = people.chat_id_of(entity, group=bool(getattr(event, "is_group", False)))
        except Exception:
            chat = ""
        for mid in event.deleted_ids or []:
            self.on_changed("deleted", chat, str(mid), "")

    async def _raw(self, update) -> None:
        from telethon.tl import types as t
        try:
            if isinstance(update, (t.UpdateUserTyping, t.UpdateChatUserTyping)):
                uid = getattr(update, "user_id", None) or getattr(getattr(update, "from_id", None), "user_id", None)
                chat = getattr(update, "chat_id", None)
                self.on_typing(people.group_id(chat) if chat else people.person_id(uid), True)
            elif isinstance(update, t.UpdateMessageReactions):
                chat = people.uid_of_peer(getattr(update, "peer", None))
                if chat:
                    self.on_reaction(chat, str(update.msg_id), self._reactions_of(update.reactions))
            elif isinstance(update, t.UpdatePhoneCall):
                await self._phone_call(update.phone_call)
        except Exception as e:
            self.log(f"An update could not be read: {e}")

    @staticmethod
    def _reactions_of(reactions) -> list:
        out = []
        for r in getattr(reactions, "results", None) or []:
            emoji = getattr(getattr(r, "reaction", None), "emoticon", "")
            if emoji:
                out.append({"name": emoji, "count": int(getattr(r, "count", 1) or 1),
                            "mine": bool(getattr(r, "chosen_order", None) is not None)})
        return out[:8]

    async def _phone_call(self, call) -> None:
        """Someone calling. It cannot take a call, so the call is declined and the bridge answers in words."""
        from telethon.tl import types as t
        if not isinstance(call, t.PhoneCallRequested):
            return
        try:
            who = await self.client.get_entity(call.admin_id)
            name, chat = people.name_of(who), people.person_id(call.admin_id)
        except Exception:
            name, chat = "Someone", people.person_id(getattr(call, "admin_id", 0))
        await self.decline_call(call)
        self.on_call(chat, name, call)

    async def decline_call(self, call) -> None:
        from telethon.tl import functions, types as t
        try:
            await self.client(functions.phone.DiscardCallRequest(
                peer=t.InputPhoneCall(id=call.id, access_hash=call.access_hash),
                duration=0, reason=t.PhoneCallDiscardReasonBusy(), connection_id=0))
        except Exception as e:
            self.log(f"The call could not be declined: {e}")

    # ── Doing things ─────────────────────────────────────────────────────────

    async def _peer(self, chat_uid: str):
        """The Telegram chat behind one of our ids, remembered so it is looked up once."""
        if chat_uid in self._entities:
            return self._entities[chat_uid]
        from telethon.tl.types import PeerChannel, PeerChat, PeerUser
        tid = people.telegram_id(chat_uid)
        if not tid:
            raise ValueError(f"{chat_uid} is not a Telegram chat")
        # A group is a supergroup or channel most of the time, and an old small group now and then: both shapes are
        # tried rather than guessed from the id.
        tries = [PeerChannel(tid), PeerChat(tid)] if people.is_group(chat_uid) else [PeerUser(tid)]
        last = None
        for peer in tries:
            try:
                entity = await self.client.get_entity(peer)
            except Exception as e:
                last = e
                continue
            self._entities[chat_uid] = entity
            return entity
        raise ValueError(f"Telegram does not know {chat_uid}: {last}")

    async def _call(self, what: str, coro):
        """One Telegram call, with the waits it asks for turned into something the account card can say."""
        from telethon.errors import FloodWaitError, PeerFloodError, UserPrivacyRestrictedError
        try:
            return await coro
        except FloodWaitError as e:
            seconds = int(getattr(e, "seconds", 0) or 0)
            self.governor.hold(seconds)
            raise Flood(seconds, what) from e
        except PeerFloodError as e:
            # Telegram's "you are writing to too many people who do not know you": hours, not seconds.
            self.governor.hold(3600)
            raise Flood(3600, what) from e
        except UserPrivacyRestrictedError as e:
            raise PermissionError("Their settings do not let it write to them.") from e

    async def typing(self, chat_uid: str, seconds: float) -> None:
        """The dots, for as long as the words would take to type."""
        from telethon.tl import functions, types as t
        peer = await self._peer(chat_uid)
        end = time.time() + max(0.0, float(seconds))
        while time.time() < end and not self._stop.is_set():
            try:
                await self.client(functions.messages.SetTypingRequest(peer=peer, action=t.SendMessageTypingAction()))
            except Exception:
                return
            await asyncio.sleep(min(4.0, max(0.5, end - time.time())))

    async def read(self, chat_uid: str) -> None:
        """Mark their messages read, as opening the chat would."""
        try:
            await self.client.send_read_acknowledge(await self._peer(chat_uid))
        except Exception:
            pass

    async def send(self, chat_uid: str, text: str, *, reply_to=None, file=None, voice=False, round_video=False,
                   caption: str = "") -> int:
        """One message. Returns its id, so the chat log keeps the same id Telegram has."""
        peer = await self._peer(chat_uid)
        if file:
            msg = await self._call("sending a file", self.client.send_file(
                peer, str(file), caption=caption or None, voice_note=bool(voice), video_note=bool(round_video),
                reply_to=int(reply_to) if reply_to else None))
        else:
            # parse_mode=None on purpose: the persona writes plain words, and Telethon's markdown would eat its
            # asterisks and underscores, or refuse the message over an unmatched one.
            msg = await self._call("sending", self.client.send_message(
                peer, text, reply_to=int(reply_to) if reply_to else None, link_preview=False, parse_mode=None))
        self.governor.sent()
        return int(getattr(msg, "id", 0) or 0)

    async def react(self, chat_uid: str, mid, emoji: str) -> None:
        from telethon.tl import functions, types as t
        peer = await self._peer(chat_uid)
        await self._call("reacting", self.client(functions.messages.SendReactionRequest(
            peer=peer, msg_id=int(mid), reaction=[t.ReactionEmoji(emoticon=emoji)])))

    async def edit(self, chat_uid: str, mid, text: str) -> None:
        await self._call("editing", self.client.edit_message(await self._peer(chat_uid), int(mid), text))

    async def delete(self, chat_uid: str, mid) -> None:
        await self._call("deleting", self.client.delete_messages(await self._peer(chat_uid), [int(mid)], revoke=True))

    async def pin(self, chat_uid: str, mid) -> None:
        await self._call("pinning", self.client.pin_message(await self._peer(chat_uid), int(mid), notify=False))

    async def history(self, chat_uid: str, limit: int = 25, search: str = "", before=None) -> list:
        """What was said in a chat, oldest first, as the Chats tab draws it."""
        peer = await self._peer(chat_uid)
        got = await self.client.get_messages(peer, limit=max(1, min(200, int(limit))),
                                             search=search or None, max_id=int(before) if before else 0)
        out = []
        for m in reversed(list(got)):
            body = {"mid": str(m.id), "mine": bool(m.out), "ts": m.date.timestamp() if m.date else time.time(),
                    "text": (m.message or "")}
            kind = self.kind_of(m)
            if kind:
                body["kind"] = kind
                body["text"] = body["text"] or KINDS.get(kind, "")
            if getattr(m, "reactions", None):
                body["reactions"] = self._reactions_of(m.reactions)
            out.append(body)
        return out

    async def profile(self, chat_uid: str) -> dict:
        """Who someone is, for the People card."""
        from telethon.tl import functions
        entity = await self._peer(chat_uid)
        out = {"id": chat_uid, "name": people.name_of(entity),
               "username": str(getattr(entity, "username", "") or ""),
               "phone": str(getattr(entity, "phone", "") or ""),
               "bot": bool(getattr(entity, "bot", False)), "premium": bool(getattr(entity, "premium", False)),
               "contact": bool(getattr(entity, "contact", False))}
        try:
            full = await self.client(functions.users.GetFullUserRequest(entity))
            out["bio"] = str(getattr(full.full_user, "about", "") or "")
        except Exception:
            pass
        return out

    async def avatar(self, chat_uid: str, to: Path):
        """Their picture, saved where the panel reads it from."""
        try:
            path = await self.client.download_profile_photo(await self._peer(chat_uid), file=str(to))
            return Path(path) if path else None
        except Exception:
            return None

    async def add_contact(self, who: str, first_message: str = "") -> dict:
        """Someone new: by @username, or by phone number, which also adds them to the account's contacts."""
        from telethon.tl import functions, types as t
        who = str(who or "").strip()
        if who.startswith("@") or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", who):
            entity = await self.client.get_entity(who if who.startswith("@") else f"@{who}")
        else:
            phone = re.sub(r"\D", "", who)
            if not 6 <= len(phone) <= 20:
                raise ValueError("That is not a @username or a phone number.")
            r = await self._call("adding a contact", self.client(functions.contacts.ImportContactsRequest(
                [t.InputPhoneContact(client_id=0, phone=f"+{phone}", first_name=f"+{phone}", last_name="")])))
            if not r.users:
                raise ValueError("Nobody on Telegram has that number.")
            entity = r.users[0]
        chat = people.person_id(entity.id)
        self._entities[chat] = entity
        if first_message:
            await self.send(chat, first_message)
        return {"chat": chat, "name": people.name_of(entity), "username": str(getattr(entity, "username", "") or "")}

    # ── Itself ───────────────────────────────────────────────────────────────

    async def set_online(self, online: bool) -> None:
        from telethon.tl import functions
        try:
            await self.client(functions.account.UpdateStatusRequest(offline=not online))
        except Exception:
            pass

    async def set_profile(self, *, name: str = "", bio: str = "", photo=None) -> None:
        from telethon.tl import functions
        if name or bio:
            first = (name or "").split(" ")[0][:64] if name else None
            last = " ".join((name or "").split(" ")[1:])[:64] if name and " " in name else (None if not name else "")
            await self._call("changing its profile", self.client(functions.account.UpdateProfileRequest(
                first_name=first, last_name=last, about=(bio or None) and bio[:70])))
        if photo:
            uploaded = await self.client.upload_file(str(photo))
            await self._call("changing its photo",
                             self.client(functions.photos.UploadProfilePhotoRequest(file=uploaded)))

    async def post_story(self, file, caption: str = "") -> int:
        """A story, as the Pictures page posts one elsewhere. Telethon v1 leaves stories to the raw API."""
        from telethon.tl import functions, types as t
        uploaded = await self.client.upload_file(str(file))
        media = t.InputMediaUploadedPhoto(file=uploaded)
        r = await self._call("posting a story", self.client(functions.stories.SendStoryRequest(
            peer="me", media=media, privacy_rules=[t.InputPrivacyValueAllowContacts()],
            random_id=random.getrandbits(63), caption=caption[:200] or None, period=86400)))
        return int(getattr(getattr(r, "updates", [None])[0], "id", 0) or 0)

    # ── Premium gifts, the way Discord's Nitro ones are handled ──────────────

    async def gift(self, slug: str) -> dict:
        """What a gift link is for: {"ok", "what", "state"} without taking it."""
        from telethon.tl import functions
        try:
            info = await self.client(functions.payments.CheckGiftCodeRequest(slug=slug))
        except Exception as e:
            return {"ok": False, "state": "gone", "what": "a gift", "reason": str(e)}
        months = int(getattr(info, "months", 0) or 0)
        used = getattr(info, "used_date", None)
        return {"ok": True, "what": f"Telegram Premium, {months} month{'s' if months != 1 else ''}" if months
                else "Telegram Premium", "state": "taken" if used else "waiting"}

    async def take_gift(self, slug: str) -> dict:
        from telethon.tl import functions
        found = await self.gift(slug)
        if not found.get("ok") or found.get("state") != "waiting":
            return {**found, "ok": False, "reason": found.get("reason") or "It had already been used"}
        try:
            await self.client(functions.payments.ApplyGiftCodeRequest(slug=slug))
        except Exception as e:
            return {"ok": False, "state": "waiting", "what": found["what"], "reason": str(e)}
        return {"ok": True, "state": "accepted", "what": found["what"], "reason": ""}

    # ── Its chats, for the panel's list ──────────────────────────────────────

    async def chats(self, limit: int = 40, every: bool = False) -> list:
        """The conversations it has, newest first: who, and what the last message was.

        `every`: the channels it follows too, even where it is set not to answer in them. The Chats tab lists them
        so you can go and read one, which is a different thing from the persona speaking there."""
        out = []
        async for dialog in self.client.iter_dialogs(limit=max(1, min(200, int(limit)))):
            entity = dialog.entity
            group = bool(dialog.is_group or dialog.is_channel)
            # A broadcast channel: everyone reads, only its own people write.
            broadcast = bool(dialog.is_channel and not dialog.is_group)
            if broadcast and not self.answer_channels and not every:
                continue
            uid = people.chat_id_of(entity, group=group)
            self._entities[uid] = entity
            msg = dialog.message
            out.append({"id": uid, "name": people.name_of(entity), "group": group, "broadcast": broadcast,
                        "unread": int(getattr(dialog, "unread_count", 0) or 0),
                        "ts": msg.date.timestamp() if msg is not None and msg.date else 0,
                        "text": (getattr(msg, "message", "") or "") if msg is not None else "",
                        "mine": bool(getattr(msg, "out", False)) if msg is not None else False})
        return out


#: Its settings, and what each is when nothing says otherwise. A fresh account is what Telegram limits, so the pace
#: starts gentler than the other platforms', and groups and stories start off.
DEFAULTS = {
    "min_send_gap_ms": 8000, "max_send_gap_ms": 30000, "max_sends_per_hour": 30, "quiet_hours": "",
    "read_receipts": True, "typing_indicator": True, "reactions": True, "groups": False, "channels": False,
    "voice_notes": True, "call_text": True, "fix_typos": True, "night_offline": True,
    "stories": False, "gifts": "notify", "keep_media": True, "answer_first": False, "dry_run": False,
}


def settings(cfg: dict | None = None) -> dict:
    """The telegram: settings as the bridge reads them, with anything set in .env winning (TELEGRAM_*), the way the
    other platforms' runners take their environment."""
    cfg = cfg or {}

    def flag(name, key):
        v = os.getenv(f"TELEGRAM_{name}")
        if v is None or v == "":
            got = cfg.get(key, DEFAULTS[key])
            return bool(DEFAULTS[key] if got is None else got)
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    def num(name, key):
        v = os.getenv(f"TELEGRAM_{name}")
        if v is None or v == "":
            v = cfg.get(key, DEFAULTS[key])
        try:
            return int(v)
        except (TypeError, ValueError):
            return DEFAULTS[key]

    def word(name, key):
        v = os.getenv(f"TELEGRAM_{name}")
        if v is None or v == "":
            v = cfg.get(key, DEFAULTS[key])
        return str(v or DEFAULTS[key])

    return {
        "min_send_gap_ms": num("MIN_SEND_GAP_MS", "min_send_gap_ms"),
        "max_send_gap_ms": num("MAX_SEND_GAP_MS", "max_send_gap_ms"),
        "max_sends_per_hour": num("MAX_SENDS_PER_HOUR", "max_sends_per_hour"),
        "quiet_hours": word("QUIET_HOURS", "quiet_hours"),
        "read_receipts": flag("READ_RECEIPTS", "read_receipts"), "typing_indicator": flag("TYPING", "typing_indicator"),
        "reactions": flag("REACTIONS", "reactions"), "groups": flag("GROUPS", "groups"),
        "channels": flag("CHANNELS", "channels"), "voice_notes": flag("VOICE_NOTES", "voice_notes"),
        "call_text": flag("CALL_TEXT", "call_text"),
        "fix_typos": flag("FIX_TYPOS", "fix_typos"), "night_offline": flag("NIGHT_OFFLINE", "night_offline"),
        "stories": flag("STORIES", "stories"), "gifts": word("GIFTS", "gifts"),
        "keep_media": flag("KEEP_MEDIA", "keep_media"), "answer_first": flag("ANSWER_FIRST", "answer_first"),
        "dry_run": flag("DRY_RUN", "dry_run"),
    }
