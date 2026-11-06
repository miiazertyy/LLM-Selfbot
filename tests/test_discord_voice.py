"""Discord voice calls: the pieces that live outside the call brain itself (2026-11-04).

app/voice/session.py owns everything a call does; app/voice/discord.py is Discord's voice connection around it.
What is checked here is that connection's wiring, without Discord and without the opus library:

  - the RTP decrypt mirrors the library's own encrypt, byte for byte, in all four modes
  - SPEAKING events build the ssrc -> user map and the mic flags, and a caller is filtered out of nothing
  - a packet is turned into PCM only for the live caller, and only while they are speaking
  - the adapter's frames() end when the call is hung up, and the call is written into the chat log after

Nothing here connects to Discord, and nothing needs opus.dll.
"""
import asyncio
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def run(coro, timeout=20):
    return asyncio.run(asyncio.wait_for(coro, timeout))


from app.voice import discord as vd  # noqa: E402
from app.voice.session import Adapter  # noqa: E402
from app.utils import chatlog as real_chatlog  # noqa: E402

import nacl.secret  # noqa: E402
import nacl.bindings  # noqa: E402


class FakeConn:
    """Enough of a VoiceConnectionState for the decrypt and the packet path."""
    def __init__(self, mode, key=None):
        self.mode = mode
        self.secret_key = list(key or bytes(32))
        self.dave_protocol_version = 0
        self.socket = None
        self._socket_reader = FakeReader()


class FakeReader:
    def __init__(self):
        self.cbs = []

    def register(self, cb):
        self.cbs.append(cb)

    def unregister(self, cb):
        try:
            self.cbs.remove(cb)
        except ValueError:
            pass


class FakeVC:
    def __init__(self, mode, key=None):
        self._connection = FakeConn(mode, key)
        self.ws = None


class FakeWS:
    def __init__(self):
        self.received_message = None


def rtp(ssrc, payload, pt=120):
    header = bytearray(12)
    header[0] = 0x80
    header[1] = pt
    struct.pack_into(">I", header, 8, ssrc)
    return bytes(header) + payload


print("== decrypt ==")
KEY = bytes(range(32))
BODY = bytes(range(7, 47))

# xsalsa20_poly1305: nonce = header + 12 zeros; box = header + encrypt(payload, nonce).ciphertext
header = rtp(42, b"")[:12]
nonce = bytearray(24)
nonce[:12] = header
cipher = nacl.secret.SecretBox(KEY).encrypt(bytes(BODY), bytes(nonce)).ciphertext
conn = FakeConn("xsalsa20_poly1305", KEY)
check("xsalsa20_poly1305 round-trips", vd._decrypt(rtp(42, cipher), conn) == BODY)

nonce24 = bytes(range(24))
cipher_suffix = nacl.secret.SecretBox(KEY).encrypt(bytes(BODY), nonce24).ciphertext + nonce24
conn = FakeConn("xsalsa20_poly1305_suffix", KEY)
check("xsalsa20_poly1305_suffix round-trips", vd._decrypt(rtp(42, cipher_suffix), conn) == BODY)

counter = struct.pack(">I", 9)
nonce_l = bytearray(24)
nonce_l[:4] = counter
cipher_lite = nacl.secret.SecretBox(KEY).encrypt(bytes(BODY), bytes(nonce_l)).ciphertext + counter
conn = FakeConn("xsalsa20_poly1305_lite", KEY)
check("xsalsa20_poly1305_lite round-trips", vd._decrypt(rtp(42, cipher_lite), conn) == BODY)

nonce_a = bytearray(24)
nonce_a[:4] = struct.pack(">I", 5)
cipher_aead = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_encrypt(
    bytes(BODY), bytes(header), bytes(nonce_a), KEY) + nonce_a[:4]
conn = FakeConn("aead_xchacha20_poly1305_rtpsize", KEY)
check("aead_xchacha20_poly1305_rtpsize round-trips", vd._decrypt(rtp(42, cipher_aead), conn) == BODY)

conn = FakeConn("xsalsa20_poly1305", KEY)
check("a wrong key gives nothing", vd._decrypt(rtp(42, cipher), FakeConn("xsalsa20_poly1305")) == b"")
check("an unknown mode gives nothing", vd._decrypt(rtp(42, b"x"), FakeConn("weird_mode", KEY)) == b"")


print("== hearing ==")

class StubDecoder:
    def decode(self, payload):
        return b"pcm" + payload[:2]


async def hearing_cases():
    vc = FakeVC("xsalsa20_poly1305", KEY)
    ws = FakeWS()
    vc.ws = ws
    calls = []
    r = vd.VoiceReceive(vc, on_speaker=lambda u: calls.append(u))
    r._decoder = StubDecoder()          # opus is not loaded here; the decode step is stubbed
    r._orig_received = ws.received_message
    r._on_speaking({"ssrc": 10, "user_id": 100, "speaking": 0})     # they exist but are not talking
    r._on_speaking({"ssrc": 10, "user_id": 100, "speaking": 1})     # now they are
    await asyncio.sleep(0)
    check("a person starting to talk is reported once", calls == [100])
    check("ssrc maps to the user", r._ssrc_user.get(10) == 100)

    r.listen_to("100")
    # The packet's own header is part of the nonce, so the cipher is made for this ssrc's header.
    nonce10 = bytearray(24)
    nonce10[:12] = rtp(10, b"")[:12]
    cipher10 = nacl.secret.SecretBox(KEY).encrypt(bytes(BODY), bytes(nonce10)).ciphertext
    packet = rtp(10, cipher10, pt=120)
    r._on_packet(packet)
    await asyncio.sleep(0.01)
    got = r._queue.get_nowait()
    check("the caller's speech arrives as PCM", got == b"pcm" + BODY[:2])

    r._on_speaking({"ssrc": 11, "user_id": 200, "speaking": 1})
    nonce11 = bytearray(24)
    nonce11[:12] = rtp(11, b"")[:12]
    cipher11 = nacl.secret.SecretBox(KEY).encrypt(bytes(BODY), bytes(nonce11)).ciphertext
    r._on_packet(rtp(11, cipher11, pt=120))
    await asyncio.sleep(0.01)
    check("someone else talking is not heard", r._queue.empty())

    r._on_speaking({"ssrc": 10, "user_id": 100, "speaking": 0})
    r._on_packet(rtp(10, cipher10, pt=120))
    await asyncio.sleep(0.01)
    check("a caller's media is heard with or without the mic flag", not r._queue.empty())
    r._queue.get_nowait()

    # A caller nobody has named yet: reported by ssrc, heard by ssrc, and identified once Discord says who.
    fresh = vd.VoiceReceive(vc, on_speaker=lambda u: calls.append(u))
    fresh._decoder = StubDecoder()
    nonce99 = bytearray(24)
    nonce99[:12] = rtp(99, b"")[:12]
    cipher99 = nacl.secret.SecretBox(KEY).encrypt(bytes(BODY), bytes(nonce99)).ciphertext
    fresh._on_packet(rtp(99, cipher99, pt=120))
    await asyncio.sleep(0.01)
    check("an unnamed speaker is reported by ssrc", 99 in calls)
    fresh.listen_to("99", ssrc=True)
    check("listening to a bare ssrc tracks the ssrc", fresh._only_ssrc == 99)
    fresh._on_packet(rtp(99, cipher99, pt=120))
    await asyncio.sleep(0.01)
    check("their media is heard before Discord names them", not fresh._queue.empty())
    fresh._queue.get_nowait()
    fresh._on_speaking({"ssrc": 99, "user_id": 700, "speaking": 1})
    check("a SPEAKING event names them and the call follows", fresh._only == "700" and fresh._only_ssrc == 0)

    r.hush()
    check("hush drains what was waiting", r._queue.empty())
    r._on_packet(rtp(10, cipher10, pt=120))
    await asyncio.sleep(0.01)
    check("nothing is decoded while hushed", r._queue.empty())


run(hearing_cases())

print("== the DAVE layer ==")

class StubDaveSession:
    """Enough of davey.DaveSession for the frame path: ready, and decrypt unwraps a FAFA frame."""
    def __init__(self, ready=True, fail=False):
        self.ready = ready
        self.fail = fail
        self.seen = []

    def decrypt(self, user_id, media_type, packet):
        self.seen.append((user_id, packet))
        if self.fail:
            raise ValueError("bad frame")
        return b"opus" + packet[:-2]


async def dave_cases():
    vc = FakeVC("xsalsa20_poly1305", KEY)
    r = vd.VoiceReceive(vc)
    r._decoder = StubDecoder()

    session = StubDaveSession()
    vc._connection.dave_session = session
    vc._connection.dave_protocol_version = 1
    check("an E2EE channel is seen as such", r._e2ee_now())

    check("a DAVE frame is unwrapped with the session", r._dave_decrypt(b"abcdef\xfa\xfa", 42) == b"opusabcdef")
    check("the frame went to the session", session.seen == [(42, b"abcdef\xfa\xfa")])

    check("a payload without the marker passes through untouched", r._dave_decrypt(b"plainopus", 42) == b"plainopus")

    vc._connection.dave_session = StubDaveSession(ready=False)
    check("a session still negotiating: passthrough", r._dave_decrypt(b"xyz", 42) == b"xyz")

    vc._connection.dave_session = StubDaveSession(fail=True)
    check("a marker by chance (decrypt fails): passthrough", r._dave_decrypt(b"lucky\xfa\xfa", 42) == b"lucky\xfa\xfa")

    vc._connection.dave_session = None
    check("no session at all: passthrough", r._dave_decrypt(b"plain", 42) == b"plain")
    vc._connection.dave_protocol_version = 0
    check("a downgraded channel is plain again", not r._e2ee_now())


run(dave_cases())

print("== the adapter ==")

class StubReceive:
    def __init__(self):
        self.q = asyncio.Queue()
        self.called = []

    def listen_to(self, uid, **kw):
        self.called.append(("listen", uid))

    def read(self):
        return self.q.get()

    def hush(self):
        self.called.append("hush")


class StubSender:
    async def send(self, pcm):
        pass

    async def pause(self):
        pass


async def adapter_cases():
    vc = FakeVC("xsalsa20_poly1305", KEY)
    receive = StubReceive()
    adapter = vd.DiscordVoiceAdapter(vc, receive, StubSender(), uid="123", name="them", chat_account=2)
    check("the adapter listens to its caller", receive.called == [("listen", "123")])
    check("it declares Discord's format", (adapter.in_rate, adapter.in_channels, adapter.out_rate,
                                           adapter.out_channels) == (48000, 2, 48000, 2))
    check("it is a call adapter like every platform's", isinstance(adapter, Adapter))

    frames = adapter.frames()
    receive.q.put_nowait(b"hello")
    check("frames() hands over what arrived", await frames.__anext__() == b"hello")
    await adapter.hang_up()
    check("hanging up hushes the receiver", "hush" in receive.called)
    try:
        await frames.__anext__()
        check("frames() ends after a hang-up", False)
    except StopAsyncIteration:
        check("frames() ends after a hang-up", True)

    written = []
    real_put = real_chatlog.put
    real_chatlog.put = lambda account, uid, mid, mine, ts, payload: written.append(
        (account, uid, mid, mine, ts, payload))
    try:
        adapter.write_up({"uid": "123", "name": "them", "platform": "discord", "chat_id": "",
                          "account": "discord_1", "seconds": 125, "reason": "goodbye", "dialed": False,
                          "engine": "own", "transcript": [], "at": 1700000000.0})
    finally:
        real_chatlog.put = real_put
    check("the call lands in the chat log of its account", written and written[0][0] == 2
          and written[0][1] == "123" and written[0][3] is False)
    check("and reads as a call", written and written[0][5].get("kind") == "call"
          and "2 min" in written[0][5].get("text", ""))


run(adapter_cases())

print("== opus lookup ==")
from app.utils import binaries
names = [p.name for p in binaries._opus_names()]
check("opus is looked for under the bundled names", "opus.dll" in names and any("libopus" in n for n in names))
check("opus status is a plain dict", isinstance(binaries.opus_status(), dict) and "dll" in binaries.opus_status())

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
