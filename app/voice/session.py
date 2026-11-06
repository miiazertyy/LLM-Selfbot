"""One call, from picking up to hanging up.

Everything that makes a call feel like a person picked up lives here, once, for every platform:

  - whether it answers at all (who is calling, its quiet hours, how many calls today) and how long it lets it ring
  - picking up the way the persona would, or saying why it called when it dialled
  - their words and its own, as a live transcript
  - being talked over: whatever was still to be said is dropped, on the spot
  - a long silence gets a "you still there?", and then a hang-up
  - goodbyes: once both have said one and its last words have played, it hangs up
  - the time limit: near the end it wraps up in its own words, then goes
  - afterwards the call goes into the chat log and what was said goes into its memory of them, so the text chat
    knows the call happened

A platform only has to hand in the other person's audio and play out `playout` (an Adapter).
"""
import asyncio
import json
import random
import re
import time
from datetime import datetime

from app.voice.audio import Converter, Playout
from app.voice.engines.base import Events
from app.voice.persona import call_instructions, direction, sounds_like_goodbye

DEFAULTS = {
    "enabled": False,
    "engine": "realtime",            # "realtime" (a voice model) or "own" (its own brain, spoken)
    "realtime_provider": "gemini",   # "gemini", "openai" or "xai"
    "realtime_model": "",            # empty: the provider's own default
    "realtime_voice": "Kore",
    "speaker": "same",               # the free path's voice: "same" as voice messages, or "elevenlabs"
    "voice": "",                     # empty: the voice messages' own voice
    # On its own brain, what hears, thinks and speaks, as "provider:model": empty is what voice messages and replies
    # use (Settings > Models). Each is tried first, and the rest after it.
    "hear": "",
    "think": "",
    "speak": "",
    "answer": "known",               # "known" (people it has talked to), "anyone", "nobody"
    "max_minutes": 10,
    "ring_seconds": [2, 7],
    "quiet_hours": "",
    "per_day": 10,
    "remember": True,
    "you_can_dial": True,
    "vc": False,                    # Discord: join the picked voice channel and talk there
    "reply_ring": True,             # Discord: text back, in character, when a DM call rings
}
SILENCE_CHECK_S = 25.0       # this long without a word from them, it checks they are still there
SILENCE_HANG_UP_S = 15.0     # ...and this long after asking, it hangs up
GOODBYE_GRACE_S = 1.5        # after both goodbyes and its last words played, this long for one more thing


def calls_cfg(cfg: dict = None) -> dict:
    """bot.calls over the defaults. Read through the persona's own settings when there is one."""
    if cfg is None:
        from app.utils.helpers import load_config
        cfg = load_config()
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (((cfg or {}).get("bot") or {}).get("calls") or {}).items() if v is not None})
    return out


def in_quiet_hours(spec: str, hour: int = None) -> bool:
    """"23-7" style, as every platform's quiet hours are written. Empty or malformed: never quiet."""
    try:
        start, end = (int(x) % 24 for x in str(spec or "").split("-", 1))
    except (ValueError, TypeError):
        return False
    h = datetime.now().hour if hour is None else hour
    return (start <= h < end) if start <= end else (h >= start or h < end)


def should_answer(calls: dict, *, known: bool, calls_today: int = 0, hour: int = None) -> tuple:
    """(answer it?, why not). Off, a stranger when only people it knows get through, its quiet hours, enough calls
    today: each is a call that rings out, and the platform's usual "could not pick up" message follows."""
    if not calls.get("enabled"):
        return False, "calls are off"
    who = str(calls.get("answer") or "known")
    if who == "nobody":
        return False, "it answers nobody"
    if who == "known" and not known:
        return False, "it only answers people it knows"
    if in_quiet_hours(calls.get("quiet_hours", ""), hour):
        return False, "quiet hours"
    if calls_today >= int(calls.get("per_day") or 0):
        return False, "enough calls today"
    return True, ""


def ring_delay(calls: dict) -> float:
    """How long it lets it ring before picking up: never on the first ring, never so long they give up."""
    span = calls.get("ring_seconds") or [2, 7]
    try:
        lo, hi = float(span[0]), float(span[1])
    except (TypeError, ValueError, IndexError):
        lo, hi = 2.0, 7.0
    return random.uniform(max(0.0, min(lo, hi)), max(lo, hi))


# ── Calls today, per account, so per_day means per day ───────────────────────

def _today_file():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "calls_today.json"


def calls_today(account: str) -> int:
    try:
        data = json.loads(_today_file().read_text(encoding="utf-8"))
    except Exception:
        return 0
    return int((data.get(datetime.now().strftime("%Y-%m-%d")) or {}).get(account, 0))


def count_call(account: str) -> None:
    f = _today_file()
    day = datetime.now().strftime("%Y-%m-%d")
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data = {day: data.get(day) or {}}               # only today's are kept
    data[day][account] = int(data[day].get(account, 0)) + 1
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


# ── Which engine ──────────────────────────────────────────────────────────────

# What a realtime server says, one way or another, when it is the key it does not like.
_KEY_REFUSED = re.compile(r"\b(?:401|402|403|429)\b|api.?key|quota|exhausted|unauthori[sz]ed|permission", re.I)


def choose_engine(calls: dict, *, instructions: str, events: Events, log=None):
    """The engine this persona talks with. A realtime one needs its provider's key; without one the call still
    happens, on its own brain, and the log says why."""
    log = log or (lambda *_: None)
    if calls.get("engine") == "realtime":
        from app.utils import providers
        provider = str(calls.get("realtime_provider") or "gemini")
        keys = providers.key_order(provider)
        if keys:
            from app.voice.engines.realtime import ENGINES
            cls = ENGINES.get(provider, ENGINES["gemini"])
            return cls(key=keys[0], model=str(calls.get("realtime_model") or ""),
                       instructions=instructions, voice=str(calls.get("realtime_voice") or ""),
                       events=events, log=log)
        log(f"No {provider.title()} key for a realtime voice: talking with its own brain instead.")
    return own_brain(calls, instructions=instructions, events=events, log=log)


def own_brain(calls: dict, *, instructions: str, events: Events, log=None):
    from app.voice.engines.cascade import OwnBrain
    from app.voice.speak import Speaker
    hear, think = call_legs(calls)
    return OwnBrain(instructions=instructions, voice=str(calls.get("voice") or ""), events=events, log=log,
                    speaker=Speaker.for_call(calls=calls), hear=hear, think=think)


def call_legs(calls: dict) -> tuple:
    """(hear, think) for a call on its own brain: what voice messages and replies use, unless the call picked its own,
    which is then tried first and the rest after it, the way a job's fallbacks are (ai.FIRST)."""
    from app.utils import ai
    from app.voice.speech import entry_of

    def first(job, entry, fn):
        async def run(*args):
            token = ai.FIRST.set({**ai.FIRST.get(), job: entry})
            try:
                return await fn(*args)
            finally:
                ai.FIRST.reset(token)
        return run

    hear, think = entry_of(calls.get("hear")), entry_of(calls.get("think"))
    return (first("stt", hear, ai.transcribe_voice) if hear else ai.transcribe_voice,
            first("replies", think, ai.generate_response) if think else ai.generate_response)


class Adapter:
    """What a platform does for a call.

    `frames()` yields the other person's audio as it arrives (in_rate, in_channels) and ends when they hang up;
    the platform plays `session.playout` at its own pace (out_rate, out_channels); `hang_up()` ends it from this end.
    """
    platform = ""
    in_rate = 48000
    in_channels = 1
    out_rate = 48000
    out_channels = 1

    async def frames(self):
        if False:
            yield b""

    async def hang_up(self) -> None:
        pass

    def write_up(self, record: dict) -> None:
        """The call, into the platform's chat log. Nothing by default."""


class CallSession(Events):
    def __init__(self, adapter: Adapter, *, uid: str, name: str, chat_id: str = "", account: str = "",
                 cfg: dict = None, recent: list = None, dialed: bool = False, engine=None, instructions: str = "",
                 clock=time.monotonic, log=None):
        self.adapter = adapter
        self.uid = str(uid or "")
        self.name = name or "them"
        self.chat_id = chat_id or self.uid
        self.account = account or adapter.platform
        self.calls = calls_cfg(cfg)
        self.recent = recent or []
        self.dialed = dialed
        self.clock = clock
        self.log = log or (lambda *_: None)
        self.playout = Playout(adapter.out_rate, adapter.out_channels)
        self.transcript = []
        self.engine = engine
        self.engine_state = "ringing"
        self.instructions = instructions
        self.started = None
        self.ended = None
        self.reason = ""
        self._done = asyncio.Event()
        self._listeners = []
        self._last_them = 0.0
        self._checked_at = 0.0
        self._wrap_at = 0.0
        self._bye = {"them": False, "me": False}
        self._bye_at = 0.0
        # The timings, as attributes so a test can shorten them without waiting out a real call.
        self.limit_s = max(1.0, float(self.calls.get("max_minutes") or 10)) * 60
        self.wrap_before_s = 20.0
        self.silence_check_s = SILENCE_CHECK_S
        self.silence_hang_up_s = SILENCE_HANG_UP_S
        self.goodbye_grace_s = GOODBYE_GRACE_S
        self.wrap_grace_s = 6.0              # after its wrap-up line, this long for them to say bye back

    # ── Watching it live (the panel's Listen and Try a call) ──────────────────

    def listen(self, fn) -> None:
        self._listeners.append(fn)

    def _emit(self, event: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(event)
            except Exception:
                pass

    @property
    def shown_state(self) -> str:
        """What it is doing, as the panel says it: still speaking while its voice is playing out."""
        if self.ended:
            return "ended"
        if self.playout.busy:
            return "speaking"
        return self.engine_state

    # ── What the engine tells it ──────────────────────────────────────────────

    def audio(self, pcm: bytes, rate: int) -> None:
        self.playout.put(pcm, rate)

    def heard(self, text: str) -> None:
        self._line("them", text)
        self._last_them = self.clock()
        self._checked_at = 0.0
        if sounds_like_goodbye(text):
            self._goodbye("them")

    def said(self, text: str) -> None:
        self._line("me", text)
        if sounds_like_goodbye(text):
            self._goodbye("me")

    def interrupted(self) -> None:
        dropped = self.playout.clear()
        if dropped and self.transcript and self.transcript[-1]["who"] == "me":
            self.transcript[-1]["cut"] = True
        if dropped:
            self._emit({"t": "cut"})

    def state(self, name: str) -> None:
        self.engine_state = name
        self._emit({"t": "state", "state": self.shown_state})

    async def _start_engine(self) -> None:
        """Its engine going. A realtime voice that turns a key away gets the provider's others. One that will not
        connect at all (model gone, no network): the call still goes on, on its own brain."""
        from app.utils import providers
        tried = set()
        while True:
            try:
                return await self.engine.start()
            except Exception as e:
                if getattr(self.engine, "name", "") == "own":
                    raise
                pid, key = getattr(self.engine, "provider", ""), getattr(self.engine, "key", "")
                tried.add(key)
                if pid and _KEY_REFUSED.search(str(e)):
                    providers.rest_key(pid, key, 600.0)
                    if set(providers.keys_for(pid)) - tried:
                        self.log(f"{self.engine.name} turned a key away; trying the next.")
                        self.engine = choose_engine(self.calls, instructions=self.instructions, events=self, log=self.log)
                        continue
                self.log(f"{self.engine.name} would not start ({e}); talking with its own brain instead.")
                self.engine = own_brain(self.calls, instructions=self.instructions, events=self, log=self.log)

    def error(self, message: str) -> None:
        self.log(f"Call with {self.name}: {message}")
        self.end(f"error: {message}")

    def _line(self, who: str, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        self.transcript.append({"who": who, "text": text, "at": round(self.clock() - (self.started or self.clock()),
                                                                          1)})
        self._emit({"t": "line", "who": who, "text": text})

    def _goodbye(self, who: str) -> None:
        self._bye[who] = True
        if all(self._bye.values()):
            self._bye_at = self.clock()

    # ── The call ──────────────────────────────────────────────────────────────

    def end(self, reason: str) -> None:
        if not self._done.is_set():
            self.reason = reason
            self._done.set()

    def hang_up(self) -> None:
        """From the panel: you ended it."""
        self.end("you hung up")

    async def run(self) -> dict:
        """The whole call. Returns what it was (the record the write-up gets)."""
        self.started = self.clock()
        self._last_them = self.started
        if getattr(self.adapter, "counts", True):
            count_call(self.account)
        if not self.instructions:
            self.instructions = call_instructions(self.uid, self.name, self.adapter.platform, recent=self.recent)
        if self.engine is None:
            self.engine = choose_engine(self.calls, instructions=self.instructions, events=self, log=self.log)
        await self._start_engine()
        self._emit({"t": "state", "state": "listening", "engine": self.engine.name})
        await self.engine.cue(direction("dial" if self.dialed else "greet", self.name))
        pump = asyncio.ensure_future(self._pump())
        watch = asyncio.ensure_future(self._watch())
        await self._done.wait()
        for task in (pump, watch):
            task.cancel()
        self.ended = self.clock()
        try:
            await self.engine.close()
        except Exception:
            pass
        try:
            await self.adapter.hang_up()
        except Exception:
            pass
        record = self.record()
        self._emit({"t": "end", "reason": self.reason, "seconds": record["seconds"]})
        self._write_up(record)
        return record

    async def _pump(self) -> None:
        a, e = self.adapter, self.engine
        # One for the whole call: it carries the resampler's state, so a stream of frames joins up without a click.
        to_engine = Converter(a.in_rate, a.in_channels, e.in_rate, 1)
        try:
            async for frame in a.frames():
                if self._done.is_set():
                    break
                await e.feed(to_engine(frame))
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            self.log(f"Call with {self.name}: their audio stopped ({type(ex).__name__}: {ex})")
        self.end("they hung up")

    async def _watch(self) -> None:
        while not self._done.is_set():
            await asyncio.sleep(0.05 if self.limit_s < 60 else 0.25)
            now = self.clock()
            talking = self.playout.busy or self.engine_state in ("thinking", "speaking")
            # Near the limit: it wraps up in its own words, then goes once they are said.
            if not self._wrap_at and now - self.started > self.limit_s - self.wrap_before_s:
                self._wrap_at = now
                await self.engine.cue(direction("wrap", self.name))
            if self._wrap_at and now - self._wrap_at > self.wrap_grace_s and not talking:
                self.end("time was up")
            if now - self.started > self.limit_s + 30:
                self.end("time was up")
            # Both said goodbye and its last words have played: it hangs up, unless they carry on.
            if self._bye_at and not talking and now - self._bye_at > self.goodbye_grace_s \
                    and self._last_them <= self._bye_at:
                self.end("goodbye")
            # Gone quiet: it checks they are still there, and if nothing comes back, hangs up.
            if not talking and not self._checked_at and now - self._last_them > self.silence_check_s:
                self._checked_at = now
                await self.engine.cue(direction("check", self.name))
            if self._checked_at and not talking and now - self._checked_at > self.silence_hang_up_s \
                    and self._last_them < self._checked_at:
                self.end("they went quiet")

    # ── Afterwards ────────────────────────────────────────────────────────────

    def record(self) -> dict:
        seconds = int(round((self.ended or self.clock()) - (self.started or self.clock())))
        return {"uid": self.uid, "name": self.name, "platform": self.adapter.platform, "chat_id": self.chat_id,
                "account": self.account, "seconds": seconds, "reason": self.reason, "dialed": self.dialed,
                "engine": getattr(self.engine, "name", ""), "transcript": list(self.transcript),
                "at": time.time() - seconds}

    def _write_up(self, record: dict) -> None:
        try:
            self.adapter.write_up(record)
        except Exception as e:
            self.log(f"Could not put the call in the chat log: {e}")
        if self.calls.get("remember", True) and self.uid and record["transcript"]:
            asyncio.ensure_future(remember(record, self.log))


async def remember(record: dict, log=None) -> None:
    """What was said on the call, into its memory of them - so a text the next day can bring it up."""
    theirs = " ".join(t["text"] for t in record["transcript"] if t["who"] == "them")
    mine = " ".join(t["text"] for t in record["transcript"] if t["who"] == "me")
    if not theirs:
        return
    try:
        from app.utils.ai import extract_memory
        from app.utils.memory import get_memory, set_memory
        existing = get_memory(record["uid"]) or {}
        found = await extract_memory(f"[on a voice call] {theirs[:3000]}", mine[:3000], existing)
        for key, value in (found or {}).items():
            if key and value and not str(key).startswith("__"):
                set_memory(record["uid"], str(key), str(value))
        minutes = max(1, round(record["seconds"] / 60))
        set_memory(record["uid"], "last call", f"{datetime.now():%Y-%m-%d}, about {minutes} min")
    except Exception as e:
        (log or (lambda *_: None))(f"Could not remember the call: {e}")


def call_line(record: dict) -> str:
    """How a call reads in the chat log: "📞 Call · 6 min"."""
    seconds = int(record.get("seconds") or 0)
    length = f"{seconds} s" if seconds < 60 else f"{round(seconds / 60)} min"
    return f"\U0001F4DE {'Called them' if record.get('dialed') else 'Call'} · {length}"
