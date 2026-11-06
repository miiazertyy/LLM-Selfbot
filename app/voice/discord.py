"""Discord as a call platform: the voice connection, hearing the other person, and being heard.

app/voice/session.py's Adapter says what a platform must do for a call. This module is Discord's answer:

  ensure_opus()   the opus library, fetched on demand like ffmpeg (discord.py-self needs it to hear and speak)
  VoiceReceive    the voice connection's UDP stream, turned into PCM frames from the person talking
  VoiceSender     the call brain's PCM out, opus-encoded and sent 20 ms at a time
  DiscordVoiceAdapter   the two wired into the call session, plus the call written into the chat log after

Discord voice channels are the only platform whose API allows a live two-way call. Discord itself cannot be
answered in a DM (those calls are WebRTC, outside the gateway), which is why this module exists only for voice
channels.

Kept safe, because a selfbot in voice is the most visible thing it can do:

  - it never joins anywhere on its own: only the channel picked in Settings (autojoin), or one joined by hand
  - it opens its mouth only while a call session has something to say, and sends the "speaking" opcode exactly
    as a real client would (set while a packet plays, cleared when the line ends)
  - it decodes only the caller's packets, and only while a call is live
"""
import asyncio
import struct
import time

from app.voice.audio import silence
from app.voice.session import Adapter


# ── Opus ─────────────────────────────────────────────────────────────────────

def ensure_opus() -> str:
    """Make sure the opus library is loaded, downloading it like ffmpeg when it is not. Returns "" when ready,
    else a reason it is not (which the runner logs and Settings can show)."""
    try:
        from discord import opus
        if opus.is_loaded():
            return ""
        from app.utils.binaries import install_opus, _opus_dll
        dll = _opus_dll()
        if dll is None:
            result = install_opus()
            if not result.get("ok"):
                return f"opus library could not be installed ({result.get('reason')})"
            dll = result.get("path")
        if not dll or dll == "__loaded__":
            return "opus library could not be found"
        opus.load_opus(str(dll))
        return ""
    except Exception as e:
        return f"opus library could not be loaded ({type(e).__name__}: {e})"


# ── Decrypting what the other person's client sent ───────────────────────────

def _decrypt(datagram: bytes, connection) -> bytes:
    """The opus payload out of one RTP datagram, for the connection's mode. The nonce layouts mirror the
    library's own _encrypt_* methods, byte for byte."""
    import nacl.secret
    import nacl.bindings
    mode = getattr(connection, "mode", None)
    key = bytes(getattr(connection, "secret_key", None) or b"")
    if not key:
        return b""
    header = datagram[:12]
    body = datagram[12:]
    try:
        if mode == "xsalsa20_poly1305":
            nonce = bytearray(24)
            nonce[:12] = header
            return nacl.secret.SecretBox(key).decrypt(bytes(body), bytes(nonce))
        if mode == "xsalsa20_poly1305_suffix":
            return nacl.secret.SecretBox(key).decrypt(bytes(body[:-24]), bytes(body[-24:]))
        if mode == "xsalsa20_poly1305_lite":
            nonce = bytearray(24)
            nonce[:4] = body[-4:]
            return nacl.secret.SecretBox(key).decrypt(bytes(body[:-4]), bytes(nonce))
        if mode == "aead_xchacha20_poly1305_rtpsize":
            nonce = bytearray(24)
            nonce[:4] = body[-4:]
            return nacl.bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(
                bytes(body[:-4]), bytes(header), bytes(nonce), key)
    except Exception:
        return b""
    return b""


def _speaking_mic(flags: int) -> bool:
    return bool((int(flags) or 0) & 0x1)


class VoiceReceive:
    """Hearing the channel: raw UDP datagrams, turned into the caller's PCM.

    Discord puts the other people's audio on the same UDP socket the client opened for its own, so the packets
    arrive whether the library reads them or not. The library's SocketReader (voice_state.py) reads them for its
    own purposes and lets others register a callback - that is the hook. Which packet is whose is said by
    SPEAKING events (op 5) on the voice websocket, which the library's handler does not know, so it is wrapped.

    One instance per connection, kept across calls. A call filters to its caller with listen_to(); between calls
    nothing is decoded, so sitting in a channel costs nothing and hears nothing.
    """

    RTP_OPUS = 120

    def __init__(self, vc, *, loop=None, on_speaker=None, log=None):
        self._vc = vc
        self._loop = loop or asyncio.get_running_loop()
        self._on_speaker = on_speaker          # called in the loop when someone starts talking: fn(user_id or ssrc)
        self.log = log or (lambda *_: None)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=40)
        self._ssrc_user: dict = {}             # ssrc -> user_id, from SPEAKING events
        self._speaking: dict = {}              # user_id -> {"ssrc", "mic", "at"}
        self._only = ""                        # the caller a live call listens to; "" = nobody
        self._only_ssrc = 0                    # the caller's ssrc, when Discord has not said their user id yet
        self._seen_ssrcs: set = set()          # ssrcs whose media has arrived: each reports a speaker once
        self._e2ee = False                     # the channel is using DAVE end-to-end encryption
        self._decoder = None
        self._orig_received = None
        self._reader = None

    # ── Attaching to the connection ──────────────────────────────────────────

    def attach(self) -> None:
        """Start hearing. The voice connection must be connected (wait_until_connected first)."""
        from discord import opus
        connection = self._vc._connection
        self._decoder = opus.Decoder()
        self._e2ee = self._e2ee_now()
        if self._e2ee:
            self.log("voice channel is end-to-end encrypted: hearing goes through the DAVE session")
        # SPEAKING events (op 5) carry which ssrc belongs to which user, and whether they are talking now.
        ws = self._vc.ws
        self._orig_received = ws.received_message

        async def wrapped(msg):
            try:
                await self._orig_received(msg)
            except Exception:
                pass
            if msg.get("op") == 5:
                self._on_speaking(msg.get("d") or {})

        ws.received_message = wrapped
        self._reader = connection._socket_reader
        self._reader.register(self._on_packet)

    def _e2ee_now(self) -> bool:
        """Whether the channel is end-to-end encrypted right now. Discord downgrades a DAVE channel to plain
        audio when someone joins who cannot do DAVE (this client), so the answer can change mid-call: checked on
        every packet rather than once."""
        try:
            return bool(getattr(self._vc._connection, "dave_protocol_version", 0) > 0)
        except Exception:
            return True

    def detach(self) -> None:
        """Stop hearing and put the connection back the way it was."""
        if self._orig_received is not None:
            try:
                self._vc.ws.received_message = self._orig_received
            except Exception:
                pass
            self._orig_received = None
        if self._reader is not None:
            try:
                self._reader.unregister(self._on_packet)
            except Exception:
                pass
            self._reader = None
        self._wake()

    def _wake(self) -> None:
        """Whatever is waiting on the queue ends now."""
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        except RuntimeError:
            pass

    # ── Who is talking ───────────────────────────────────────────────────────

    def _on_speaking(self, d) -> None:
        ssrc = int(d.get("ssrc") or 0)
        user = int(d.get("user_id") or 0)
        if not ssrc or not user:
            return
        mic = _speaking_mic(d.get("speaking"))
        was = self._speaking.get(user, {}).get("mic", False)
        self._ssrc_user[ssrc] = user
        self._speaking[user] = {"ssrc": ssrc, "mic": mic, "at": time.monotonic()}
        # The caller was known only by ssrc: Discord has now said who it is.
        if self._only_ssrc and ssrc == self._only_ssrc:
            self._only = str(user)
            self._only_ssrc = 0
            self.log(f"caller identified: user {user}")
        # The channel downgraded from E2EE (Discord does this when a plain client joins): hearing works again.
        if self._e2ee and not self._e2ee_now():
            self._e2ee = False
            self.log("voice channel went back to plain audio: she can hear again")
        if mic and not was and self._on_speaker is not None:
            try:
                self._loop.call_soon_threadsafe(self._on_speaker, user)
            except RuntimeError:
                pass

    # ── The packets ──────────────────────────────────────────────────────────

    def _on_packet(self, datagram: bytes) -> None:
        """One UDP datagram, off the library's socket reader thread.

        Media proves someone is talking, so the caller is tracked by ssrc even where Discord's SPEAKING events
        are sparse; those events only add the ssrc's user id when they arrive. Inbound payloads come in two
        forms - transport-encrypted, or (on some SFUs, for DAVE frames) raw - and both are handled.
        """
        try:
            if len(datagram) < 12:
                return
            if datagram[1] & 0x7F != self.RTP_OPUS:
                return
            ssrc = struct.unpack_from(">I", datagram, 8)[0]
            my_ssrc = int(getattr(self._vc, "ssrc", 0) or 0)
            if ssrc == my_ssrc:
                return
            user = self._ssrc_user.get(ssrc)
            if user is None and ssrc not in self._seen_ssrcs:
                # Someone is talking whose identity Discord has not announced: report them by ssrc, once.
                self._seen_ssrcs.add(ssrc)
                if self._on_speaker is not None:
                    try:
                        self._loop.call_soon_threadsafe(self._on_speaker, ssrc)
                    except RuntimeError:
                        pass
            if self._only_ssrc:
                if ssrc != self._only_ssrc:
                    return
                if user is None:
                    user = 0                      # unknown caller: the DAVE layer tries every group member
            elif user is None or str(user) != self._only:
                return
            payload = _decrypt(datagram, self._vc._connection)
            if not payload:
                # Some SFUs forward DAVE frames without transport encryption: the frame itself, if it ends
                # with the protocol's magic marker.
                raw = bytes(datagram[12:])
                payload = raw if raw.endswith(b"\xfa\xfa") else b""
                if not payload:
                    return
            if self._e2ee_now():
                payload = self._dave_decrypt(payload, user or 0)
                if not payload:
                    return
            pcm = self._decoder.decode(payload)
            if not pcm:
                return
            # 48 kHz stereo, as the decoder makes it: the adapter declares exactly that, the brain resamples.
            self._loop.call_soon_threadsafe(self._push, pcm)
        except RuntimeError:
            pass
        except Exception:
            pass

    def _dave_decrypt(self, payload: bytes, user: int) -> bytes:
        """A transport-decrypted payload, to plain opus.

        A DAVE frame ends with the protocol's magic marker and is unwrapped with the MLS session the connection
        negotiated. Anything else passes through untouched: while the group is still being negotiated, on a
        downgraded channel, or mid-transition, senders are in passthrough mode and the payload is already the
        opus it carries. A marker by chance (an opus payload can end in the same two bytes) fails decryption and
        passes through the same way - the same frame check first-party clients make. An unknown caller (user 0)
        is tried against every group member's decryptor.
        """
        try:
            session = getattr(self._vc._connection, "dave_session", None)
            if session is None or not session.ready:
                return payload
            if not payload.endswith(b"\xfa\xfa"):
                return payload
            import davey
            ids = [int(user)] if user else []
            if not ids:
                try:
                    ids = [int(x) for x in (session.get_user_ids() or [])]
                except Exception:
                    ids = []
            for uid in ids:
                try:
                    out = session.decrypt(uid, davey.MediaType.audio, payload)
                    if out:
                        return bytes(out)
                except Exception:
                    continue
            return payload
        except Exception:
            return payload

    def _push(self, pcm: bytes) -> None:
        try:
            self._queue.put_nowait(pcm)
        except asyncio.QueueFull:
            pass

    # ── What a call reads ────────────────────────────────────────────────────

    def listen_to(self, who, *, ssrc: bool = False) -> None:
        """Only this caller's audio reaches the queue: a user id from a SPEAKING event, or a bare ssrc (ssrc=True)
        while Discord has not said who it is."""
        who = str(who or "")
        self._only = who
        self._only_ssrc = int(who) if (ssrc and who.isdigit()) else 0

    def hush(self) -> None:
        """No caller: nothing is decoded until the next call."""
        self._only = ""
        self._only_ssrc = 0
        drained = True
        while drained:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                drained = False

    async def read(self) -> bytes:
        """One chunk of the caller's PCM (48 kHz stereo), or None when the stream has ended."""
        return await self._queue.get()


class VoiceSender:
    """Being heard: the call brain's PCM out, opus-encoded and sent a frame at a time.

    The "speaking" opcode follows the audio the way a real client sends it: set while packets play, cleared the
    moment they stop. Sending it without audio, or audio without it, is exactly what a bot would do - and Discord
    drops audio that no speaking event introduced, so it would also not be heard.
    """

    FRAME_SAMPLES = 960                      # 20 ms at 48 kHz

    def __init__(self, vc, *, log=None):
        from discord import opus
        self._vc = vc
        self._encoder = opus.Encoder(application="voip", bitrate=64, fec=True, expected_packet_loss=0.15)
        self._speaking = False
        self.log = log or (lambda *_: None)

    async def send(self, pcm: bytes) -> None:
        """One frame of 48 kHz stereo PCM, as opus. Runs on the event loop."""
        self._vc.send_audio_packet(self._encoder.encode(pcm, self.FRAME_SAMPLES), encode=False)
        if not self._speaking:
            self._speaking = True
            try:
                await self._vc.ws.speak(1)          # SPEAKING, microphone
            except Exception:
                pass

    async def pause(self) -> None:
        """Nothing playing: say so, once."""
        if self._speaking:
            self._speaking = False
            try:
                await self._vc.ws.speak(0)
            except Exception:
                pass


class DiscordVoiceAdapter(Adapter):
    """A Discord voice channel as the other end of a call.

    The channel's audio goes to the call brain as 48 kHz stereo PCM; the brain's voice comes back out the same
    shape, 20 ms at a time, at the pace `playout` hands it over (pump_playout, below). Only the caller is heard:
    anyone else in the channel is ignored for the whole call.
    """
    platform = "discord"
    in_rate = 48000
    in_channels = 2
    out_rate = 48000
    out_channels = 2

    def __init__(self, vc, receive: VoiceReceive, sender: VoiceSender, *, uid: str, name: str,
                 account: str = "", chat_account: int = 1, no_log: bool = False, log=None):
        self._vc = vc
        self._receive = receive
        self._sender = sender
        self.uid = str(uid or "")
        self.name = name or "them"
        self.account = account or "discord"
        self._chat_account = int(chat_account or 1)
        self._no_log = no_log                # a caller known only by ssrc: nothing to file under
        self.log = log or (lambda *_: None)
        self._open = True
        # The receiver keys its caller on a raw ssrc until Discord names them; the session's uid keeps the
        # "vc<ssrc>" form for the transcript.
        placeholder = self.uid.startswith("vc")
        token = self.uid[2:] if placeholder else self.uid
        self._receive.listen_to(token, ssrc=placeholder)

    async def frames(self):
        while self._open:
            pcm = await self._receive.read()
            if pcm is None or not self._open:
                return
            yield pcm

    async def hang_up(self) -> None:
        self._open = False
        self._receive.hush()

    def write_up(self, record: dict) -> None:
        """The call, into the chat log as a message of kind "call" ("📞 Call · 6 min"). A caller known only by
        ssrc has no conversation to file it under."""
        from app.utils import chatlog
        from app.voice.session import call_line
        if self._no_log:
            return
        try:
            chatlog.put(self._chat_account, self.uid, f"call-{int(time.time() * 1000)}",
                        bool(record.get("dialed")), record.get("at") or time.time(),
                        {"kind": "call", "text": call_line(record)})
        except Exception as e:
            self.log(f"Could not put the call in the chat log: {e}")


async def pump_playout(session, sender: VoiceSender, done: asyncio.Task) -> None:
    """The session's voice, out into the channel at the pace it would play: one 20 ms frame at a time, so the
    session can still see "has something left to say" (playout.busy) and stop being talked over. `done` is the
    session's run() task: the pump lives exactly as long as the call."""
    loop = asyncio.get_running_loop()
    tick = loop.time()
    while not done.done():
        if session.playout.busy:
            await sender.send(session.playout.read())
        else:
            await sender.pause()
        tick += 0.02
        await asyncio.sleep(max(0.0, tick - loop.time()))
    await sender.pause()


def quiet_pcm(rate: int, channels: int, seconds: float = 0.5) -> bytes:
    """Half a second of silence, for the very start of a call: Discord discards the first few packets otherwise,
    and her greeting would open with a clipped first word."""
    return silence(int(seconds * 1000), rate, channels)
