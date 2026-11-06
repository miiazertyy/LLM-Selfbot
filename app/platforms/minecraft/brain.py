"""The brain a Minecraft account thinks with: an OpenAI-shaped endpoint mindcraft calls, answered by the app.

mindcraft keeps its own agent loop (it has to: that loop is what walks, mines and builds), and asks a model what to
say and do through an OpenAI client pointed at this. Each request is one of five kinds, told apart by the marker the
app put on each of the profile's templates (profile.MARKERS):

  CONVERSE, with a player's line last   the persona answers, through engine.generate_ai_response: mood, memory,
                                        language, history, everything a reply gets on any other platform. What the
                                        game looks like (mindcraft's own rendered prompt: stats, inventory, the
                                        command docs) and what just happened in it go in as extra["context"], and
                                        extra["can_act"] lets the reply carry commands (engine.action_rules).
  CONVERSE, anything else last          a command's result, a self-prompt tick, a mode's narration: answered
                                        straight by the model, in character but with nothing remembered about
                                        anyone, so a mode ticking over never costs two more calls or a memory.
  CODE, MEMORY, RESPONDER               mindcraft's own housekeeping: straight to the model, no persona.
  VISION                                what a screenshot shows, through the app's vision model.

It never fails a request. mindcraft says "My brain disconnected, try again." out loud, in the game, when a request
errors; so a timeout, a budget spent or anything going wrong is answered with an empty reply instead, which mindcraft
takes as nothing to say (agent.js: `if (res.trim().length === 0) break`).

Served on the Minecraft worker's own loopback port, never the panel's (the panel can be bound to every interface,
and the per-account state the engine keeps lives in the worker), behind a token in the URL path: mindcraft reaches
it through its "lmstudio" provider, whose API key is a fixed placeholder, so the path is the only place a secret can
go (profile.py says why that provider). It answers mindcraft's embeddings as well, itself (embed_text).
"""
from __future__ import annotations

import asyncio
import re
import secrets
import time
from collections import deque

# At module level, not inside make_app: with `from __future__ import annotations` FastAPI reads a handler's
# annotations as strings and resolves them against this module, so a Request imported inside the function is a name
# it cannot find, and every request is refused with a 422. mindcraft does not catch that on its way to a reply, so
# it was the bot, not the request, that went down.
from fastapi import FastAPI, HTTPException, Request

from app.platforms.minecraft.profile import MARKERS

KIND_OF = {v: k for k, v in {
    "converse": MARKERS["conversing"], "code": MARKERS["coding"], "memory": MARKERS["saving_memory"],
    "responder": MARKERS["bot_responder"], "vision": MARKERS["image_analysis"],
}.items()}
# A marker, and the two that come in as a line of the game rather than on a template: a line typed in the panel for
# it to say word for word (by its id: the words themselves never pass through mindcraft's command parser), and its
# arrival in the world, which is mindcraft's init_message.
_MARKER_RE = re.compile(r"\[\[LSB:[A-Z]+(?::[A-Za-z0-9_-]{1,40})?\]\]")
_SAY_RE = re.compile(r"\[\[LSB:SAY:([A-Za-z0-9_-]{6,40})\]\]")
JOINED = "[[LSB:JOINED]]"
SAY_TTL = 120.0
# A Minecraft chat line is 256 characters at most; mindcraft sends the reply as one.
CHAT_MAX = 250
GREET_EVERY = 600.0
# A player's line as mindcraft's history writes it (history.js: `${name}: ${content}`). Minecraft names are 3 to 16
# letters, digits and underscores.
_PLAYER_RE = re.compile(r"^([A-Za-z0-9_]{3,16}): (.*)$", re.S)
RECENT_TURNS = 10
TURN_CHARS = 220


def new_token() -> str:
    return secrets.token_urlsafe(24)


def route(messages: list) -> tuple[str, list]:
    """(kind, the messages with every marker taken out). The marker sits at the start of the system prompt, which
    mindcraft built from the profile's template; a request with none is answered raw."""
    kind = "raw"
    out = []
    for i, m in enumerate(messages or []):
        content = m.get("content")
        if isinstance(content, str):
            if i == 0 and m.get("role") == "system":
                for marker, k in KIND_OF.items():
                    if marker in content:
                        kind = k
                        break
            content = _MARKER_RE.sub("", content)
        out.append({**m, "content": content})
    return kind, out


def _lines(turn: dict) -> list[str]:
    """A turn's lines. mindcraft's providers run its turns through strictFormat, which writes a game event as a
    user line beginning "SYSTEM: " and joins turns that follow one another from the same side with a newline, so
    one turn can carry a command's result and the line someone said after it."""
    content = turn.get("content")
    if not isinstance(content, str):
        return []
    # "SYSTEM:" with nothing after it is a marker's line once the marker is gone (a line said from the panel, its
    # arrival): nothing happened in the game.
    return [l.strip() for l in content.split("\n") if l.strip() and l.strip() not in ("_", "SYSTEM:")]


def special(messages: list) -> tuple[str, str]:
    """("say", id) for a line the panel gave it to say, ("joined", "") for its arrival in the world, ("", "")
    otherwise. Read off the last turn, before route() takes the markers out."""
    last = (messages or [{}])[-1] if messages else {}
    content = last.get("content") if isinstance(last, dict) else None
    if not isinstance(content, str):
        return "", ""
    m = _SAY_RE.search(content)
    if m:
        return "say", m.group(1)
    if JOINED in content.split("\n")[-1]:
        return "joined", ""
    return "", ""


# What a model writes for "nothing to say", told so in words: mindcraft's own prompt asks for a tab, and a model
# asked for "a single tab" wrote "tab", which mindcraft said out loud, in the game.
_NOTHING = {"tab", "\\t", "<tab>", "nothing", "none", "silence", "...", "…", ".", "_", "-"}
# A reply that is all one bracket or one pair of asterisks: narration ("(stirring awake and looking around, trying to
# figure out what is going on)", said in a server's chat on Oct 21), never words. It acts through its commands.
_NARRATION_RE = re.compile(r"^\s*(?:\([^()]*\)|\[[^\[\]]*\]|\*[^*]+\*)\s*$", re.S)


def quiet(reply: str) -> str:
    """The reply, or "" when it is only a way of saying nothing (_NOTHING) or narration, which mindcraft then says
    nothing for."""
    text = str(reply or "")
    core = text.strip().strip("[](){}*\"'`.!").strip().lower()
    return "" if not core or core in _NOTHING or _NARRATION_RE.match(text) else text


# A server's sign-in plugin asking for a password, as some networks send it: from a "player" that is not one
# (jartex.fun's "LOGIN: Please register with /register <password> <password>").
_AUTH_PROMPT_RE = re.compile(r"/(?:register|reg|login|log|l)\b[^\n]*[<\[(]", re.I)


def auth_prompt(text: str) -> bool:
    """A sign-in prompt, which the app's part in the bot answers by itself (agent_hooks.mjs): the persona is never
    asked it, the model never sees it, and nobody is remembered for it. On jartex.fun the persona was handed one
    every five seconds for three minutes, and "LOGIN" became the person it talked to most."""
    return bool(_AUTH_PROMPT_RE.search(str(text or "")))


_BANG_RE = re.compile(r"!(?=[A-Za-z_])")


def chat_line(text: str) -> str:
    """Words typed in the panel, as one line of Minecraft chat that mindcraft will say as they are: one line (it
    would turn newlines into spaces anyway), no longer than a chat line, and no "!" before a word, which mindcraft
    would take for a command and try to run ("hey!you" would be the command !you)."""
    line = " ".join(str(text or "").split())
    return _BANG_RE.sub("! ", line)[:CHAT_MAX].rstrip()


def player_line(turn: dict | None) -> tuple[str, str] | None:
    """("Steve", "come here") when the turn ends with someone speaking: mindcraft writes that line as
    "Steve: come here" (history.js). A turn ending in a game event ("SYSTEM: ...") is nobody speaking."""
    if not turn or turn.get("role") != "user":
        return None
    lines = _lines(turn)
    if not lines or lines[-1].startswith("SYSTEM:"):
        return None
    m = _PLAYER_RE.match(lines[-1])
    return (m.group(1), m.group(2).strip()) if m else None


def game_context(system_prompt: str, turns: list, speaker: str = "") -> str:
    """What the game looks like, what just happened in it and who is speaking, for the persona to answer with.

    The engine answers from its own history of this person, not from mindcraft's turns, so without this the
    persona would never learn whether the command it ran worked, or what anyone else just said. And it is handed
    the line said without the name of who said it, which in a public chat left it guessing: asked to follow, it
    wrote !followPlayer("player"), for a player who does not exist."""
    events = []
    for t in turns:
        side = t.get("role")
        for line in _lines(t):
            if line.startswith("SYSTEM:"):
                events.append(f"- game: {line[7:].strip()}")
            elif side == "assistant":
                events.append(f"- you: {line}")
            else:
                events.append(f"- {line}")
    # The last one is the line being answered, which the persona is handed on its own.
    recent = [e[: TURN_CHARS + 8] for e in events[:-1][-RECENT_TURNS:]]
    # The moment, said once, here: the persona says who they are, never where they are (persona.PROMPT says why).
    parts = ["IN MINECRAFT, RIGHT NOW. You are in a Minecraft world, playing, and the people talking to you here are "
             "people you are playing with. Go along with what they ask you to do in the game: tease, grumble or make "
             "them wait a moment in words if that is like you, but do it, with its command, in the same reply. Only "
             "refuse what would hurt someone or wreck what someone built. A server's own commands (/spawn, /server "
             "survival, /play) are typed as your whole reply. What follows is the game as it stands, and how to act "
             "in it.", system_prompt.strip()]
    if recent:
        parts.append("WHAT JUST HAPPENED, oldest first:\n" + "\n".join(recent))
    if speaker:
        # Talk first, then the two things people ask most, spelled out, and only as answers to being asked: with
        # only the docs, asked to come over, a model answered "where?"; given the commands as bare examples, asked
        # who it was, it walked over to them.
        parts.append(f'SPEAKING TO YOU NOW: {speaker}, their exact name in the game. Most lines are just talk: '
                     f'answer those in words alone, with no command. Only when they ask for something to be done, '
                     f'do it with its command in this same reply: asked to come to them, !goToPlayer("{speaker}", 3); '
                     f'asked to follow them, !followPlayer("{speaker}", 3).')
    return "\n\n".join(p for p in parts if p)


# Commands it is never offered. Code it writes and runs itself (!newAction: only ever with insecure coding unlocked,
# see the settings), talking to other bots (there are none it should be talking to, and two that answer each other
# never stop), the wiki (a web search per question), and restarting itself or wiping its own chat, which a player
# could ask for to knock it over. And !stfu: it answered "hi! who are you?" with it, and it posts mindcraft's own
# canned "Shutting up." in place of the persona; saying nothing (a tab) is how it keeps quiet, and !stop and
# !endGoal still stop it. Left out of the docs here and blocked in mindcraft as well (BLOCKED_COMMANDS).
BLOCKED_COMMANDS = ("!newAction", "!startConversation", "!endConversation", "!searchWiki", "!restart", "!clearChat",
                    "!stfu", "!checkBlueprint", "!checkBlueprintLevel", "!getBlueprint", "!getBlueprintLevel")
_DOCS_RE = re.compile(r"\n?\*COMMAND DOCS\n.*?\n\*\n", re.S)
_CMD_RE = re.compile(r"^(!\w+): (.*)$")
_PARAM_RE = re.compile(r"^(\w+): \((\w+)\)")
_MODES_RE = re.compile(r"Agent Modes:\n((?:- \w+\((?:ON|OFF)\)\n?)+)")
_TYPES = {"string": "str", "number": "num", "bool": "bool"}


def _first_sentence(text: str, cap: int = 90) -> str:
    s = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return s if len(s) <= cap else s[: cap - 1].rstrip() + "…"


def compact(prompt: str, blocked=BLOCKED_COMMANDS) -> str:
    """mindcraft's prompt with its command docs on one line each, and its ten modes on two.

    The docs are generated (commands/index.js getCommandDocs) as a description per command and then a line per
    parameter, which comes to about 1,900 tokens; with a persona of several thousand on top, that put every reply
    over a free model tier's 8,000 a minute, and every model in the chain refused it. One line per command keeps what
    the model needs to write a command right (its name, its parameters in order, what kind each is, what it does)
    and drops the rest."""
    def docs(m: re.Match) -> str:
        entries, cur = [], None
        for line in m.group(0).split("\n"):
            cm = _CMD_RE.match(line)
            if cm:
                if cur:
                    entries.append(cur)
                cur = None if cm.group(1) in blocked else [cm.group(1), [], _first_sentence(cm.group(2))]
                continue
            pm = _PARAM_RE.match(line)
            if cur and pm:
                cur[1].append(f"{pm.group(1)}:{_TYPES.get(pm.group(2), pm.group(2))}")
        if cur:
            entries.append(cur)
        rows = [f"{n}({', '.join(p)}): {d}" if p else f"{n}: {d}" for n, p, d in entries]
        return ("\nCOMMANDS. To act, write one as !name, or !name(\"text\", 2) with its parameters in order; double "
                "quotes around text; one command per reply.\n" + "\n".join(rows) + "\n")

    def modes(m: re.Match) -> str:
        on = re.findall(r"- (\w+)\(ON\)", m.group(1))
        off = re.findall(r"- (\w+)\(OFF\)", m.group(1))
        return f"Modes on: {', '.join(on) or 'none'}. Off: {', '.join(off) or 'none'}.\n"

    return _MODES_RE.sub(modes, _DOCS_RE.sub(docs, prompt))


EMBED_DIM = 256


def embed_text(text: str) -> list[float]:
    """A word vector, hashed: each word adds to one of EMBED_DIM places, with a sign from its hash so collisions
    cancel rather than pile up. Two texts sharing words point the same way, which is all mindcraft asks of an
    embedding here (picking which command docs fit what was said), and it is answered on this machine, at once."""
    import hashlib
    import math
    vec = [0.0] * EMBED_DIM
    for word in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "little")
        vec[h % EMBED_DIM] += 1.0 if (h >> 31) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def until_stop(text: str, stop) -> str:
    """mindcraft asks for its reply to stop at "***"; honoured here, since the model behind this never saw it."""
    for s in ([stop] if isinstance(stop, str) else list(stop or [])):
        if s and s in text:
            text = text.split(s, 1)[0]
    return text


class Budget:
    """Calls an hour, at most. mindcraft calls on every line said and every command's result, and its prompts run to
    thousands of tokens; a free model tier is rate-limited in minutes without a ceiling."""

    def __init__(self, per_hour: int):
        self.per_hour = max(0, int(per_hour or 0))
        self.calls: deque = deque()

    def take(self) -> bool:
        if not self.per_hour:
            return True
        now = time.time()
        while self.calls and now - self.calls[0] > 3600:
            self.calls.popleft()
        if len(self.calls) >= self.per_hour:
            return False
        self.calls.append(now)
        return True


class Brain:
    """One account's brain. `answer(body)` is the whole of it; make_app() puts it behind HTTP."""

    def __init__(self, account: int, *, server: str = "", public: bool = True, timeout_s: float = 45.0,
                 calls_per_hour: int = 120, persona: str = "brief", greet: bool = True, on_turn=None):
        self.account = int(account)
        self.server = server              # "host-port", for the public chat's channel
        self.public = public              # False when it whispers (mindcraft's only_chat_with)
        self.persona = persona            # "brief" (persona.py) or "full"
        self.greet = greet                # a few words on arriving in the world
        self.timeout_s = float(timeout_s)
        self.budget = Budget(calls_per_hour)
        # Told (player, what they said, the reply, the channel) for the chat log and the Chats tab: what they said
        # is "" for a line it says after acting (a command's result, a goal's next step), and the player is then
        # the last one who spoke to it, whose conversation it carries on.
        self.on_turn = on_turn
        self._locks: dict[str, asyncio.Lock] = {}
        self._sayings: dict[str, tuple[float, str, asyncio.Event]] = {}
        self._greeted_at = 0.0
        self.last_speaker = ""
        # Whether it answers now: the bridge's say (the account paused, a player ignored or paused from the panel).
        # Asked with a player's name, or "" for what it would say on its own. Not answered is an empty reply, which
        # mindcraft takes as nothing to say.
        self.listening = lambda name: True

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    def channel_of(self, name: str) -> str:
        """The conversation a player's lines are kept in by the engine: their own when it whispers, the world's
        public chat otherwise."""
        uid = f"mc_{name.lower()}"
        return uid if not self.public else (f"mcs_{self.server}" if self.server else "mcs_world")

    def say(self, text: str) -> tuple[str, asyncio.Event]:
        """A line for it to say word for word, from the panel or Telegram. mindcraft is handed only its id
        (SAY_RE), and asks for its next line as it would after anyone speaking; this answers with the words, and
        the event is set once it has, which is when they are on their way into the game."""
        return self._hold(chat_line(text))

    def goal(self, text: str) -> tuple[str, asyncio.Event]:
        """Something to get done, from the panel or Telegram ("build a shelter before dark"), handed to mindcraft as
        its own goal command, the way say() hands it words: mindcraft then works at it by itself, a step at a time,
        each one asked of the brain, until it is done or told to stop."""
        what = " ".join(str(text or "").replace('"', "'").split())[:300]
        return self._hold(f'!goal("{what}")')

    def _hold(self, reply: str) -> tuple[str, asyncio.Event]:
        now = time.time()
        for sid in [k for k, (at, _, _) in self._sayings.items() if now - at > SAY_TTL]:
            self._sayings.pop(sid, None)
        sid = secrets.token_urlsafe(9)
        done = asyncio.Event()
        self._sayings[sid] = (now, reply, done)
        return sid, done

    async def answer(self, body: dict) -> str:
        """The reply text for one of mindcraft's requests. Never raises: see the module's docstring."""
        try:
            return quiet(await asyncio.wait_for(self._answer(body), self.timeout_s))
        except Exception:
            return ""

    async def _answer(self, body: dict) -> str:
        what, sid = special(body.get("messages") or [])
        if what == "say":
            # The panel's words, as they are: no model, so nothing from the hour's budget.
            _, text, done = self._sayings.pop(sid, (0.0, "", None))
            if done is not None:
                done.set()
            return text
        kind, messages = route(body.get("messages") or [])
        system = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
        turns = messages[1:] if system else messages
        said = player_line(turns[-1] if turns else None) if kind == "converse" else None
        if said and auth_prompt(said[1]):
            return ""
        if (what == "joined" or kind == "converse") and not self.listening(said[0] if said else ""):
            return ""
        # Everything below asks the model.
        if not self.budget.take():
            return ""
        if what == "joined":
            return await self._arrived()
        if kind == "converse":
            system = compact(system)
            if said:
                return until_stop(await self._persona(said, system, turns), body.get("stop"))
            # A command's result, a goal's next step: nobody to remember, but still the character speaking. Without
            # this, what it said after following someone ("Sure, I'm following you!") came out in a generic
            # assistant's voice beside the persona's own: one bot, two voices.
            from app.platforms.minecraft import persona as persona_mod
            voice = await persona_mod.brief()
            if voice:
                system = f"{voice}\n\n{system}"
            from app.utils import ai, logger
            before = logger.thoughts_logged
            raw = until_stop(await self._raw(system, turns), body.get("stop"))
            # What it means to do next, commands and all, unless its model has just said what it thought on the way
            # there: a model that does not reason would show nothing, and this is the part worth watching.
            if logger.thoughts_logged == before:
                logger.log_thinking(raw, ai.last_reply_model)
            reply = quiet(raw)
            if self.on_turn and self.last_speaker and reply.strip():
                try:
                    self.on_turn(self.last_speaker, "", reply, self.channel_of(self.last_speaker))
                except Exception:
                    pass
            return reply
        if kind == "vision":
            return until_stop(await self._vision(system, turns), body.get("stop"))
        return until_stop(await self._raw(system, turns), body.get("stop"))

    async def _arrived(self) -> str:
        """A few words on coming into the world, in its own voice; nothing if it said hello a moment ago (a
        reconnect, a restart), or was told not to."""
        if not self.greet or time.time() - self._greeted_at < GREET_EVERY:
            return ""
        self._greeted_at = time.time()
        from app.platforms.minecraft import persona as persona_mod
        from app.utils.ai import generate_response
        voice = await persona_mod.brief()
        system = (f"{voice}\n\n" if voice else "") + (
            "You have just come into a Minecraft world, where you play with the people in it. Say hello in a few "
            "words, in your own voice, the way you would arriving somewhere. Only the words: no command, nothing "
            "in brackets.")
        return chat_line(await generate_response("Say it now.", system, None) or "")

    async def _persona(self, said: tuple[str, str], system: str, turns: list) -> str:
        from app.core.engine import IncomingMessage, generate_ai_response
        from app.platforms.minecraft import persona as persona_mod
        name, text = said
        uid = f"mc_{name.lower()}"
        channel = self.channel_of(name)
        self.last_speaker = name
        # No look online: mindcraft is an agent of its own, and a player waits seconds, not a minute.
        extra = {"context": game_context(system, turns, speaker=name), "can_act": True, "no_pictures": True,
                 "account": self.account, "no_web": True}
        if self.persona != "full":
            extra["instructions"] = await persona_mod.brief()
        msg = IncomingMessage(
            platform="minecraft", user_id=uid, user_name=name, channel_id=channel,
            # Who said it, in the line itself, as mindcraft writes its own: told only at the end of a long context,
            # the model still answered "there's no player name given" and guessed one for its command.
            content=f"{name}: {text}",
            is_private=not self.public, extra=extra,
        )
        # One reply at a time per person: mindcraft can have a conversation, a memory summary and a picture in flight
        # at once, and the engine's history for a person must not be written by two at the same time.
        async with self._lock(uid):
            reply = quiet(await generate_ai_response(msg) or "")
        if self.on_turn:
            try:
                self.on_turn(name, text, reply, channel)
            except Exception:
                pass
        return reply

    async def _raw(self, system: str, turns: list) -> str:
        from app.utils.ai import generate_response
        history = [{"role": t.get("role") if t.get("role") in ("user", "assistant") else "user",
                    "content": str(t.get("content") or "")} for t in turns if t.get("content")]
        if history and history[-1]["role"] == "user":
            return await generate_response("", system, history) or ""
        # mindcraft sends its housekeeping (a memory summary, whether to answer another bot) as a system prompt and
        # nothing else; a provider wants a user turn to answer.
        return await generate_response("Write it now.", system, None) or ""

    async def _vision(self, system: str, turns: list) -> str:
        from app.utils.ai import generate_response_image
        image, text = "", ""
        for t in reversed(turns):
            content = t.get("content")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url" and not image:
                        image = (part.get("image_url") or {}).get("url", "")
                    elif part.get("type") == "text" and not text:
                        text = part.get("text", "")
            if image:
                break
        if not image:
            return await self._raw(system, turns)
        return await generate_response_image(text or "What do you see?", system, image, None) or ""


def completion(text: str, model: str = "llmselfbot") -> dict:
    """The OpenAI chat.completion shape mindcraft's client reads: choices[0].message.content, and a finish_reason
    of "stop" (it treats "length" as the context overflowing, and retries with less)."""
    return {
        "id": f"chatcmpl-{secrets.token_hex(8)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def make_app(brain: Brain, token: str):
    """The brain behind HTTP: /v1/<token>/chat/completions and /v1/<token>/models. A wrong token is a 404, as if
    there were nothing here at all."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def guard(given: str):
        if not secrets.compare_digest(given, token):
            raise HTTPException(status_code=404)

    @app.get("/v1/{given}/models")
    async def models(given: str):
        guard(given)
        return {"object": "list", "data": [{"id": "llmselfbot", "object": "model", "owned_by": "llmselfbot"}]}

    @app.post("/v1/{given}/chat/completions")
    async def chat(given: str, request: Request):
        guard(given)
        try:
            body = await request.json()
        except Exception:
            body = {}
        return completion(await brain.answer(body), str(body.get("model") or "llmselfbot"))

    @app.post("/v1/{given}/embeddings")
    async def embeddings(given: str, request: Request):
        guard(given)
        try:
            body = await request.json()
        except Exception:
            body = {}
        given_input = body.get("input")
        texts = given_input if isinstance(given_input, list) else [given_input or ""]
        return {"object": "list", "model": str(body.get("model") or "llmselfbot-words"),
                "data": [{"object": "embedding", "index": i, "embedding": embed_text(str(t))}
                         for i, t in enumerate(texts)],
                "usage": {"prompt_tokens": 0, "total_tokens": 0}}

    return app
