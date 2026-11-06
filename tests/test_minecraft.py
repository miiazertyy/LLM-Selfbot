"""Minecraft, the fifth platform: a persona playing with people through mindcraft-ce.

This file grows with each milestone. Today: mindcraft-ce installed on demand (app/platforms/minecraft/install.py,
app/web/routes/minecraft_routes.py, MinecraftSetup.svelte).
"""
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="llmbot_mc_"))
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from app.platforms.minecraft import install  # noqa: E402

print("== where it comes from ==")
check("one pinned commit, never a branch", len(install.MINDCRAFT_COMMIT) == 40
      and all(c in "0123456789abcdef" for c in install.MINDCRAFT_COMMIT))
check("the commit whose MindServer takes a control token", install.MINDCRAFT_COMMIT.startswith("236c252")
      and "control token" in read("app/platforms/minecraft/install.py"))
check("downloaded over https, from GitHub's own archive, no git needed",
      "https://codeload.github.com/{MINDCRAFT_REPO}/tar.gz/{MINDCRAFT_COMMIT}" in read("app/platforms/minecraft/install.py"))
check("kept apart from the app's own Minecraft files", install.MC_DIR == DATA / "mindcraft")
check("Node 22 or newer, as its package.json says", install.MIN_NODE == 22)

print("\n== an archive off the internet is not trusted ==")


def tarball(entries):
    """A .tar.gz in memory: (name, data) files, or (name, None, linkname) symlinks."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for e in entries:
            if len(e) == 3:
                info = tarfile.TarInfo(e[0])
                info.type = tarfile.SYMTYPE
                info.linkname = e[2]
                tar.addfile(info)
            else:
                info = tarfile.TarInfo(e[0])
                info.size = len(e[1])
                tar.addfile(info, io.BytesIO(e[1]))
    path = DATA / f"t{len(list(DATA.glob('t*.tar.gz')))}.tar.gz"
    path.write_bytes(buf.getvalue())
    return path


good = tarball([("mindcraft-ce-abc/main.js", b"//"), ("mindcraft-ce-abc/src/a.js", b"//")])
into = DATA / "good"
into.mkdir()
n = install._unpack(good, into)
check("its one top folder is stripped", n == 2 and (into / "main.js").is_file() and (into / "src" / "a.js").is_file())

for label, entries in (
    ("a path climbing out of the folder", [("top/main.js", b"//"), ("top/../../escaped.txt", b"x")]),
    ("an absolute path", [("top/main.js", b"//"), ("top//abs-escaped.txt", b"x")]),
    ("a link pointing out of the folder", [("top/main.js", b"//"), ("top/out", None, "../../../../escaped-link")]),
):
    bad = tarball(entries)
    dest = DATA / f"bad{abs(hash(label))}"
    dest.mkdir()
    refused = False
    try:
        install._unpack(bad, dest)
    except Exception:
        refused = True
    landed = list(DATA.parent.glob("escaped*")) + list(DATA.glob("escaped*")) + list(DATA.glob("abs-escaped*"))
    check(f"{label} is refused, and nothing lands outside", (refused or not landed) and not landed,
          f"refused={refused} landed={landed}")
check("extracted with tarfile's data filter", 'filter="data"' in read("app/platforms/minecraft/install.py"))

print("\n== a reinstall keeps what it should ==")
install.MC_DIR.mkdir(parents=True, exist_ok=True)
for rel in ("main.js", "old-file.js", "src/x.js", "node_modules/mineflayer/index.js", "bots/andy/memory.json"):
    p = install.MC_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
install.MARKER.write_text(json.dumps({"commit": "old"}), encoding="utf-8")
install._clear_source(lambda *a, **k: None)
check("the old commit's files are gone, so none outlive the upgrade",
      not (install.MC_DIR / "old-file.js").exists() and not (install.MC_DIR / "src").exists())
check("node_modules stays, so npm only brings it up to date", (install.MC_DIR / "node_modules/mineflayer/index.js").exists())
check("what its bots remember stays", (install.MC_DIR / "bots/andy/memory.json").exists())

print("\n== installed means it loads ==")
check("present() wants main.js and the two modules the runner cannot do without",
      install.present() is False)          # no socket.io-client in this fake install
(install.MC_DIR / "node_modules/socket.io-client").mkdir(parents=True)
(install.MC_DIR / "main.js").write_text("//", encoding="utf-8")     # the clear above took it, as it should
check("and is true once they are there", install.present() is True)
check("a different commit on disk is installed but not up to date",
      install.installed_commit() == "old" and install.status()["up_to_date"] is False)
src = read("app/platforms/minecraft/install.py")
check("checked by importing it, not by the files being there", "import(m)" in src and "'mineflayer','socket.io-client'" in src)
check("dev dependencies installed: patch-package is one, and the postinstall runs it",
      "no --omit=dev" in src and 'k != "NODE_ENV"' in src)
check("the marker is written only after it loads", src.index("if not _verify(node, say):") < src.index("MARKER.write_text"))
check("too little room, or too old a Node, is said before anything downloads",
      src.index("node_version()") < src.index("_download(") and src.index("free_gb()") < src.index("_download("))

print("\n== uninstall ==")
freed_said = []
install.uninstall(lambda t, *a: freed_said.append(t))
check("everything goes but the bots' memory", (install.MC_DIR / "bots/andy/memory.json").exists()
      and not (install.MC_DIR / "node_modules").exists() and not (install.MC_DIR / "main.js").exists())
check("and it says what it kept", any("remember" in t for t in freed_said))

print("\n== the panel ==")
routes = read("app/web/routes/minecraft_routes.py")
check("status, install and uninstall routes", all(f'"/api/minecraft/{r}"' in routes for r in ("status", "install", "uninstall")))
check("one install at a time", "_install_lock.acquire(blocking=False)" in routes)
check("the install runs on a thread, never on the event loop",
      "threading.Thread(target=run" in routes and "asyncio.to_thread(install.status)" in routes)
check("registered with the app", "minecraft_routes.router" in read("app/web/server.py"))
check("its own log source, tailed by the panel and named on the Logs page",
      'LOG_SOURCE = "minecraft-install"' in routes
      and '"minecraft-install": { name: "Minecraft setup"' in read("webui/src/lib/logrows.ts")
      and 'entry.source === "minecraft-install"' in read("webui/src/lib/components/MinecraftSetup.svelte"))
setup = read("webui/src/lib/components/MinecraftSetup.svelte")
check("four steps: Node 22, npm, mindcraft, the pinned version",
      all(f'name: "{n}"' in setup for n in ("Node.js", "npm", "mindcraft-ce", "This version")))
check("the steps light with a note each and a bell at the end, like the other platforms'",
      'play("rise"' in setup and 'play("done")' in setup)
check("removing it asks first, in the app's own dialog", 'await ask("Remove mindcraft-ce?"' in setup and "danger: true" in setup)
smap = read("webui/src/lib/settingsmap.ts")
check("a Minecraft tab in Settings, with its Install page", 'id: "minecraft",' in smap and 'panel: "minecraft-setup"' in smap)
check("and Settings draws it", "<MinecraftSetup />" in read("webui/src/pages/Settings.svelte"))
check("its mark is a block, not Mojang's logo", "Deliberately not Mojang's own logo" in read("webui/src/lib/brands.ts")
      and "minecraft: MINECRAFT_CUBE," in read("webui/src/lib/components/Icon.svelte"))

print("\n== the brain: which of mindcraft's requests is which ==")
import asyncio  # noqa: E402

from app.platforms.minecraft import brain, persona, profile  # noqa: E402

kind, msgs = brain.route([{"role": "system", "content": "[[LSB:CONVERSE]]You are playing"},
                          {"role": "user", "content": "Tester: hi"}])
check("a conversation is told by its marker, which never reaches a model",
      kind == "converse" and "[[LSB" not in msgs[0]["content"] and msgs[0]["content"] == "You are playing")
check("so is mindcraft's housekeeping",
      [brain.route([{"role": "system", "content": profile.MARKERS[k] + "x"}])[0]
       for k in ("coding", "saving_memory", "bot_responder", "image_analysis")] == ["code", "memory", "responder", "vision"])
check("and anything without one is answered raw", brain.route([{"role": "system", "content": "plain"}])[0] == "raw")

check("a player's line, as mindcraft writes it", brain.player_line({"role": "user", "content": "Tester: come here"}) == ("Tester", "come here"))
check("found after a game event strictFormat joined to it",
      brain.player_line({"role": "user", "content": "SYSTEM: Agent executed !stats\nSteve_99: follow me"}) == ("Steve_99", "follow me"))
check("a turn ending in a game event is nobody speaking",
      brain.player_line({"role": "user", "content": "Tester: hi\nSYSTEM: Code output: done"}) is None)
check("nor is its own line, or a name Minecraft could not have",
      brain.player_line({"role": "assistant", "content": "Tester: hi"}) is None
      and brain.player_line({"role": "user", "content": "not a name!: hi"}) is None)

docs = ("Summarized memory:''\nAgent Modes:\n- self_preservation(ON)\n- cheat(OFF)\n\n*COMMAND DOCS\n You can use the "
        "following commands.\n!stats: Get your bot's location. And more.\n!goToPlayer: Go to the given player.\nParams:\n"
        "player_name: (string) The name of the player.\ncloseness: (number) How close.\n!newAction: Write code.\nParams:\n"
        "prompt: (string) What to do.\n!stfu: Stop chatting.\n*\nConversation Begin:")
small = brain.compact(docs)
check("each command on one line, its parameters in order with their kinds",
      "!goToPlayer(player_name:str, closeness:num): Go to the given player." in small and "Params:" not in small)
check("a description down to its first sentence", "!stats: Get your bot's location." in small and "And more" not in small)
check("commands it is never offered are not in its docs", "!newAction" not in small and "!stfu" not in small)
check("its ten modes on one line", "Modes on: self_preservation. Off: cheat." in small)
check("and the rest of the prompt left as it was", small.startswith("Summarized memory:''") and small.endswith("Conversation Begin:"))

ctx = brain.game_context("STATS ...", [{"role": "user", "content": "SYSTEM: Agent executed !goToPlayer"},
                                       {"role": "assistant", "content": "omw"},
                                       {"role": "user", "content": "Tester: thanks"}], speaker="Tester")
check("what just happened, oldest first, by who did it", "- game: Agent executed !goToPlayer" in ctx and "- you: omw" in ctx)
check("but not the line being answered, which is handed on its own", "Tester: thanks" not in ctx)
check("who is speaking, by the exact name a command needs", 'SPEAKING TO YOU NOW: Tester,' in ctx and '!goToPlayer("Tester", 3)' in ctx)
speaking = ctx[ctx.index("SPEAKING TO YOU NOW"):]
check("talk answered in words, a command only when something is asked for",
      speaking.index("Most lines are just talk") < speaking.index("!goToPlayer") and "Only when they ask" in speaking)
check("and that it is playing with them: grumble if it must, but do it", "people you are playing with" in ctx and "but do it" in ctx)
check("its reply stops where mindcraft asked", brain.until_stop("sure!***extra", "***") == "sure!")

e1, e2, e3 = brain.embed_text("mine some wood"), brain.embed_text("go mine wood"), brain.embed_text("trade with villager")
dot = lambda a, b: sum(x * y for x, y in zip(a, b))
check("embeddings answered here: a unit vector of a fixed size", len(e1) == brain.EMBED_DIM and abs(dot(e1, e1) - 1) < 1e-6)
check("texts sharing words point closer together", dot(e1, e2) > dot(e1, e3))

b2 = brain.Budget(2)
check("a ceiling on calls an hour", b2.take() and b2.take() and not b2.take())


class Exploding(brain.Brain):
    async def _answer(self, body):
        raise RuntimeError("the model fell over")


check("it never fails a request: mindcraft would say 'My brain disconnected' in the game",
      asyncio.run(Exploding(1).answer({"messages": []})) == "")
spent = brain.Brain(1, calls_per_hour=1)
spent.budget.take()
check("over budget is an empty reply, which mindcraft takes as nothing to say", asyncio.run(spent.answer({})) == "")
c = brain.completion("hi")
check("the reply in the shape mindcraft's client reads", c["choices"][0]["message"]["content"] == "hi"
      and c["choices"][0]["finish_reason"] == "stop")

from fastapi.testclient import TestClient  # noqa: E402


class Fixed(brain.Brain):
    async def _answer(self, body):
        return "hey"


client = TestClient(brain.make_app(Fixed(1), "secret-token"))
check("served behind a token in the path", client.post("/v1/secret-token/chat/completions", json={}).status_code == 200)
check("a wrong one is a 404, as if nothing were there", client.post("/v1/guess/chat/completions", json={}).status_code == 404
      and client.post("/v1/guess/embeddings", json={}).status_code == 404)
check("its embeddings route answers what mindcraft asks",
      len(client.post("/v1/secret-token/embeddings", json={"input": "wood"}).json()["data"][0]["embedding"]) == brain.EMBED_DIM)
check("FastAPI's types at module level, or every request is a 422",
      read("app/platforms/minecraft/brain.py").index("from fastapi import FastAPI, HTTPException, Request")
      < read("app/platforms/minecraft/brain.py").index("def make_app("))

print("\n== the profile it plays under ==")
base = {"conversing": "You are a friendly robot", "coding": "code $NAME", "saving_memory": "mem", "bot_responder": "resp",
        "image_analysis": "img", "modes": {"hunting": True, "cheat": True}, "coding_examples": [[{"role": "user", "content": "x"}]],
        "conversation_examples": [[{"role": "user", "content": "hi"}]], "cooldown": 3000}
p = profile.build("Alicia", "http://127.0.0.1:5000/v1/tok", base=base)
check("every model key on the brain, through mindcraft's lmstudio provider",
      all(p[k] == {"api": "lmstudio", "model": "llmselfbot", "url": "http://127.0.0.1:5000/v1/tok"}
          for k in ("model", "code_model", "vision_model")))
check("its embeddings on the brain too, never left to mindcraft's default", p["embedding"]["url"] == "http://127.0.0.1:5000/v1/tok")
check("mindcraft's own character gone from the conversation prompt",
      "friendly robot" not in p["conversing"] and p["conversing"].startswith(profile.MARKERS["conversing"]))
check("its placeholders kept for mindcraft to fill",
      all(t in p["conversing"] for t in ("$NAME", "$STATS", "$INVENTORY", "$COMMAND_DOCS", "$MEMORY")))
check("no example conversations in another voice", p["conversation_examples"] == [])
check("the housekeeping templates kept, marked", p["coding"] == profile.MARKERS["coding"] + "code $NAME")
check("it never cheats, whatever the defaults say", p["modes"]["cheat"] is False and p["modes"]["hunting"] is True)
def refuses(name):
    try:
        profile.build(name, "u", base=base)
    except ValueError:
        return True
    return False


check("a name Minecraft would not take is refused, not guessed at", refuses("a!") and refuses("no") and refuses("!!!"))
check("one it would is cleaned and kept", profile.build("Ali cia_1", "u", base=base)["name"] == "Alicia_1")
check("the defaults' expected keys are checked, so an upstream change is said, not silent",
      profile.missing_keys({"conversing": 1}) == ["coding", "saving_memory", "bot_responder", "modes", "coding_examples"])

print("\n== the persona, told briefly ==")
check("a brief is kept per persona", persona.key_of("a") != persona.key_of("b"))
check("and per wording of the prompt that made it", persona.PROMPT_VERSION in read("app/platforms/minecraft/persona.py")
      and "f\"{PROMPT_VERSION}\\n{full}\"" in read("app/platforms/minecraft/persona.py"))
check("the prompt asks for the character only, never where they are",
      "say nothing about where they are or what they are doing right now" in persona.PROMPT
      and "Minecraft" not in persona.PROMPT)
cut = persona.head("One. Two. " + "x" * 5000, chars=4000)
check("the last resort keeps the persona's opening, cut at a sentence", cut.startswith("One.") and len(cut) <= 4000)


async def _fake_condense(prompt, instructions, max_tokens=1100):
    return "You are Alicia. You write in lowercase."


import app.utils.ai as _ai  # noqa: E402

_real = _ai.condense
_ai.condense = _fake_condense
made = asyncio.run(persona.brief("You are Alicia, a long persona."))
check("written once by the model, and kept", made == "You are Alicia. You write in lowercase."
      and persona.cached("You are Alicia, a long persona.") == made)
check("and made again when the persona changes", persona.cached("A different persona.") == "")


async def _rambling(prompt, instructions, max_tokens=1100):
    return "x" * (persona.MAX_BRIEF_CHARS + 1)


_ai.condense = _rambling
fallback = asyncio.run(persona.brief("Another persona entirely. It goes on."))
check("a brief that is not brief is not trusted: the opening is used, and not kept",
      fallback.startswith("Another persona") and persona.cached("Another persona entirely. It goes on.") == "")
_ai.condense = _real
check("not written by generate_response, whose reply cap would cut it off halfway",
      "from app.utils.ai import condense" in read("app/platforms/minecraft/persona.py"))

print("\n== the engine, where a reply can act ==")
eng = read("app/core/engine.py")
check("the output rules that let it act, only where it can", "enriched += action_rules()" in eng
      and 'if (msg.extra or {}).get("can_act"):' in eng)
check("and the usual rules, byte for byte, everywhere else",
      "Never describe an action or an image instead of doing it: no '[Image of a " in eng)
from app.core import engine  # noqa: E402

check("acting means writing the command, never narrating it", "never narrate an action" in engine.action_rules()
      and "commands documented above" in engine.action_rules())
check("a platform can hand in its own telling of the character",
      'base_instructions = (msg.extra or {}).get("instructions") or load_instructions()' in eng)

print("\n== a line from the panel, said as it is ==")
check("its id is found in the last turn", brain.special([{"role": "user", "content": "SYSTEM: [[LSB:SAY:abc123xyz]]"}])
      == ("say", "abc123xyz"))
check("its arrival is found too, and nothing else is either",
      brain.special([{"role": "user", "content": "SYSTEM: [[LSB:JOINED]]"}]) == ("joined", "")
      and brain.special([{"role": "user", "content": "Tester: hi"}]) == ("", ""))
check("both are markers, never shown to a model",
      "[[LSB" not in brain.route([{"role": "system", "content": "[[LSB:CONVERSE]]x"},
                                  {"role": "user", "content": "SYSTEM: [[LSB:SAY:abc123xyz]]"}])[1][1]["content"])
check("and the line a marker leaves behind is nothing that happened in the game",
      brain._lines({"role": "user", "content": "SYSTEM: \nTester: hi"}) == ["Tester: hi"])
check("'nothing to say' in words is nothing, never said in the game as 'tab'",
      all(brain.quiet(x) == "" for x in ("tab", "[tab]", "\\t", "  ", "Nothing.", "(nothing)", "..."))
      and brain.quiet("nothing much, you?") == "nothing much, you?" and brain.quiet("hey") == "hey")
check("a reply that is all narration is nothing too: it acts through its commands",
      all(brain.quiet(x) == "" for x in ("(stirring awake and looking around, trying to figure out what the hell is "
                                         "going on)", "*waves at you*", "[walks over]"))
      and brain.quiet("ok (laughs)") == "ok (laughs)"
      and brain.quiet('(walks over) !goToPlayer("Steve", 3)') == '(walks over) !goToPlayer("Steve", 3)')
check("and the prompts ask for nothing at all, not for 'a tab'",
      "a single tab" not in profile.CONVERSING and "a single tab" not in read("app/core/engine.py"))
check("one line of chat, no longer than Minecraft takes", brain.chat_line("a\nb  c") == "a b c"
      and len(brain.chat_line("x" * 900)) == brain.CHAT_MAX)
check("no '!' before a word, which mindcraft would run as a command",
      brain.chat_line("hey!you, !stop that!") == "hey! you, ! stop that!")


async def _said_word_for_word():
    b = brain.Brain(1, calls_per_hour=1)
    b.budget.take()                           # the hour spent: a model call would be refused
    sid, done = b.say("from the panel!")
    out = await b.answer({"messages": [{"role": "system", "content": "[[LSB:CONVERSE]]x"},
                                       {"role": "user", "content": f"SYSTEM: [[LSB:SAY:{sid}]]"}]})
    again = await b.answer({"messages": [{"role": "user", "content": f"SYSTEM: [[LSB:SAY:{sid}]]"}]})
    return out, done.is_set(), again


out, was_set, again = asyncio.run(_said_word_for_word())
check("the panel's words come back as they are, without the model or the hour's budget",
      out == "from the panel!" and was_set)
check("and once only", again == "")


async def _goal_handed_over():
    b = brain.Brain(1)
    sid, done = b.goal('build a "big"\nshelter')
    return await b.answer({"messages": [{"role": "user", "content": f"SYSTEM: [[LSB:SAY:{sid}]]"}]}), done.is_set()


goal_reply, goal_set = asyncio.run(_goal_handed_over())
check("a goal goes to mindcraft as its own goal command, quotes made safe for it",
      goal_reply == "!goal(\"build a 'big' shelter\")" and goal_set)

_calls = []


async def _fake_generate(prompt, instructions, history=None):
    _calls.append(instructions)
    return "heyy, i'm here"


async def _no_brief(full=None):
    return ""


_real_generate = _ai.generate_response
_ai.generate_response = _fake_generate
_real_brief = persona.brief
persona.brief = _no_brief
joined = {"messages": [{"role": "system", "content": "[[LSB:CONVERSE]]x"},
                       {"role": "user", "content": "SYSTEM: [[LSB:JOINED]]"}]}
g = brain.Brain(1)
first = asyncio.run(g.answer(joined))
second = asyncio.run(g.answer(joined))
check("a few words on arriving, in its own voice", first == "heyy, i'm here" and "just come into" in _calls[-1])
check("not again on a reconnect a moment later", second == "")
check("and not at all when told not to", asyncio.run(brain.Brain(1, greet=False).answer(joined)) == "")

check("a server's sign-in prompt is told from talk",
      brain.auth_prompt("Please register with /register <password> <password>")
      and brain.auth_prompt("Merci de vous connecter avec /l <motdepasse>")
      and not brain.auth_prompt("i logged in yesterday, register me for the event?"))
n = len(_calls)
_turns_seen = []
asked = brain.Brain(1, on_turn=lambda *a: _turns_seen.append(a))
check("handed as a player's line (jartex.fun's LOGIN), the persona is never asked it, nor remembers anyone for it",
      asyncio.run(asked.answer({"messages": [{"role": "system", "content": "[[LSB:CONVERSE]]x"},
                                             {"role": "user", "content": "LOGIN: Please register with /register <password> <password>"}]})) == ""
      and len(_calls) == n and not _turns_seen and len(asked.budget.calls) == 0)
quiet = brain.Brain(1)
quiet.listening = lambda name: name != "Tester"
n = len(_calls)
check("a player it is not answering (ignored, paused) gets nothing, and costs no call",
      asyncio.run(quiet.answer({"messages": [{"role": "system", "content": "[[LSB:CONVERSE]]x"},
                                             {"role": "user", "content": "Tester: hi"}]})) == ""
      and len(_calls) == n)
turns_seen = []
talker = brain.Brain(1, server="localhost-25565", on_turn=lambda *a: turns_seen.append(a))
talker.last_speaker = "Steve"
reply = asyncio.run(talker.answer({"messages": [{"role": "system", "content": "[[LSB:CONVERSE]]x"},
                                                {"role": "user", "content": "SYSTEM: Agent executed !followPlayer"}]}))
check("what it says after acting carries on the last player's conversation",
      turns_seen == [("Steve", "", "heyy, i'm here", "mcs_localhost-25565")])
check("whose channel is the world's chat, or their own when it whispers",
      brain.Brain(1, server="h-1").channel_of("Ann") == "mcs_h-1"
      and brain.Brain(1, public=False).channel_of("Ann") == "mc_ann")
_ai.generate_response = _real_generate
persona.brief = _real_brief

print("\n== the worker: who it plays as, and where ==")
from app.platforms.minecraft import worker  # noqa: E402

mc = worker.section({"minecraft": {"host": "play.example.net", "port": 25570, "modes": {"hunting": False}}})
check("its settings over the defaults, its modes too", mc["host"] == "play.example.net" and mc["greet"] is True
      and mc["modes"]["hunting"] is False and mc["modes"]["self_defense"] is True)
check("a settings file from before Minecraft runs on the defaults", worker.section({})["port"] == 25565)
for k in [k for k in os.environ if k.startswith("MINECRAFT_")]:
    os.environ.pop(k)
os.environ.update({"MINECRAFT_USERNAME_2": "Alicia", "MINECRAFT_HOST_2": "10.0.0.5"})
s2 = worker.slot(2, mc)
check("its own server, with Minecraft's port, never the one Settings names for another",
      s2 == {"name": "Alicia", "host": "10.0.0.5", "port": 25565, "auth": "offline"})
os.environ.update({"MINECRAFT_USERNAME_3": "Bob_7"})
check("with none of its own, the server in Settings", worker.slot(3, mc)["host"] == "play.example.net"
      and worker.slot(3, mc)["port"] == 25570)
os.environ.update({"MINECRAFT_USERNAME_4": "no way", "MINECRAFT_AUTH_4": "MICROSOFT"})
check("a name typed into .env by hand is cleaned as the profile cleans it; its sign-in read in any case",
      worker.slot(4, mc)["name"] == "noway" and worker.slot(4, mc)["auth"] == "microsoft")
os.environ.update({"MINECRAFT_USERNAME_5": "ab", "MINECRAFT_AUTH_5": "cracked"})
check("too short is no name at all, and an unknown sign-in is offline",
      worker.slot(5, mc)["name"] == "" and worker.slot(5, mc)["auth"] == "offline")
check("the world as a piece of an id", worker.server_id("Play.Example.NET", 25565) == "play.example.net-25565"
      and worker.server_id("", 1) == "world-1")
check("only real names in who it talks with", worker.only_chat_with({"only_chat_with": ["Steve", "no!", "a b c d"]})
      == ["Steve", "abcd"] and worker.only_chat_with({"only_chat_with": "Ann, Bob_2"}) == ["Ann", "Bob_2"])

ms = worker.mindcraft_settings({"host": "h", "port": 1, "auth": "offline"}, worker.section({}), Path("p.json"))
check("what it never does: speak aloud, open a window, render, write code, chat to bots, narrate",
      ms["speak"] is False and ms["auto_open_ui"] is False and ms["render_bot_view"] is False
      and ms["allow_insecure_coding"] is False and ms["chat_bot_messages"] is False and ms["narrate_behavior"] is False)
check("commands are never shown in the chat, and the blocked ones are blocked",
      ms["show_command_syntax"] == "none" and "!newAction" in ms["blocked_actions"] and "!stfu" in ms["blocked_actions"])
check("it arrives with the marker the brain greets on, and mindcraft translates nothing",
      ms["init_message"] == brain.JOINED and ms["language"] == "en")
check("its memory of the world kept when Settings says so", ms["load_memory"] is True
      and worker.mindcraft_settings({"host": "h", "port": 1, "auth": "offline"},
                                    worker.section({"minecraft": {"remember_world": False}}), Path("p"))["load_memory"] is False)
check("the profile it plays under, and the server from its slot",
      ms["profiles"] == ["p.json"] and ms["host"] == "h" and ms["port"] == 1 and ms["mindserver_port"] == 0)

os.environ.update({"DISCORD_TOKEN_1": "secret-token", "GROQ_API_KEY": "gsk_secret", "INSTAGRAM_PASSWORD_1": "pw"})
renv = worker.runner_env({"MC_BRAIN_URL": "http://x"})
check("none of the app's secrets go to the runner or to mindcraft",
      not any(k in renv for k in ("DISCORD_TOKEN_1", "GROQ_API_KEY", "INSTAGRAM_PASSWORD_1"))
      and not any("secret" in str(v) for v in renv.values()))
check("but what Node and the system need does", "PATH" in {k.upper() for k in renv} and renv["MC_BRAIN_URL"] == "http://x")
for k in ("DISCORD_TOKEN_1", "GROQ_API_KEY", "INSTAGRAM_PASSWORD_1"):
    os.environ.pop(k, None)

synced = worker.sync_runner()
check("the runner written beside mindcraft, as a module, with the shared core",
      synced == install.MC_DIR / "llmselfbot" / "minecraft_runner.mjs" and synced.exists()
      and (install.MC_DIR / "llmselfbot" / "runner_core.mjs").exists())
check("from this build, byte for byte", synced.read_bytes() == (ROOT / "app/platforms/minecraft/minecraft_runner.mjs").read_bytes())

print("\n== what it said and did, in the chat log ==")
check("the words it said, then what it did", worker.chat_text('sure! !followPlayer("Tester", 3)') == "sure! *follows Tester*")
check("an item's name in words", worker.chat_text('!collectBlocks("oak_log", 10)') == "*collects 10 oak log*")
check("anything after the command is not said in the game, so not here either",
      worker.chat_text('ok !stop and more words') == "ok *stops*")
check("a command it has no words for is named", worker.chat_text("!fly") == "*fly*")
check("and a plain reply is itself", worker.chat_text("hey you") == "hey you")
check("its parts, as mindcraft reads them", worker.split_reply('go !goToCoordinates(1, 2.5, -3, 2)')
      == ("go", "goToCoordinates", ["1", "2.5", "-3", "2"]))

print("\n== the bridge, for Minecraft ==")
bridge_src = read("app/platforms/snapchat_bridge.py")
check("a platform of its own, never another one's bridge in its place",
      '"minecraft": {' in bridge_src and '"key": "mc"' in bridge_src and "sys.exit(2)" in bridge_src
      and 'PLATFORM = "snapchat"' not in bridge_src)
check("no inbox to poll and nothing to nudge, its own brain instead",
      "tasks = [tg_command_loop(), _cleanup_loop(), _wake_server(), _runner_watch(), _minecraft_main()]" in bridge_src)
check("the brain bound before the runner starts", bridge_src.index("url = session.bind()")
      < bridge_src.index("_node_proc = subprocess.Popen([shutil.which(\"node\"), str(runner)]"))
check("not installed: the card says so, and it starts once it is", "while not (shutil.which(\"node\") and mc_install.present()):" in bridge_src)
check("the panel's commands it answers its own way", all(c in bridge_src for c in (
    '"chat_history" and MINECRAFT', '"send_message" and MINECRAFT', '("mc_state", "mc_tell", "mc_leave", "mc_join")')))
check("the panel's words said the way it says everything, mindcraft handed only their id",
      "/msg" not in bridge_src and "sid, done = brain.say(text)" in bridge_src and 'await _panel("say", sid=sid' in bridge_src)
check("and a goal handed over as mindcraft's own goal command", "sid, done = brain.goal(text)" in bridge_src)
check("paused, or a player ignored: no answer", "brain.listening = _mc_listening" in bridge_src)
runner_src = read("app/platforms/minecraft/minecraft_runner.mjs")
check("the runner: mindcraft on a free port, behind its control token, bound to this computer",
      "freePort()" in runner_src and "MINDCRAFT_CONTROL_TOKEN = CONTROL_TOKEN" in runner_src
      and 'MINDCRAFT_BIND_HOST = "127.0.0.1"' in runner_src and "auth: { controlToken: CONTROL_TOKEN }" in runner_src)
check("only once the brain answers", "await waitForBrain()" in runner_src)
check("a Microsoft code becomes the card's", "Sign in at microsoft.com/link with the code" in runner_src)
check("which the card opens in a browser, the code already in it, rather than asking for it to be typed",
      'kind: "url", label: "Sign in with browser", to: `https://www.microsoft.com/link?otc=${code}`'
      in read("webui/src/lib/accounts/condition.ts")
      and "openUrl(mcSign.link || mcSign.uri)" in read("webui/src/pages/Accounts.svelte")
      and "The code is already filled in there." in read("webui/src/pages/Accounts.svelte"))
check("not let in: tried again, less and less often", "exited too quickly and will not be restarted" in runner_src
      and "RETRY_S" in runner_src)
check("the brain's token never in the log", "redact" in runner_src and "/v1/…" in runner_src)
check("mindcraft's doubled and field-by-field lines kept out of the shared log, and only out of the log",
      "const NOISE = " in runner_src and "if (!NOISE.test(line) && !expected) console.log(" in runner_src
      and runner_src.index("if (!NOISE.test(line)") < runner_src.index("const code = line.match("))
check("and ViaProxy's own difference not reported as a fault, nor mindcraft's ping when the runner's answered",
      "Timeout pinging server|Error pinging server|Error getting server:|Attempting to connect anyway" in runner_src
      and "VIA_SHOWN = /\\bERROR\\b" in runner_src)
check("what the server says about signing in shown in the log, through the runner's own redaction",
      'say(`The server: ${redact(String(msg.text || ""))}`);' in runner_src)
check("mindcraft goes when the bridge does", "process.kill(parent, 0)" in runner_src and "taskkill" in runner_src)
check("shipped with the exe", "minecraft_runner.mjs" in read("packaging/specparts.py"))
check("a role of its own on the command line", "def _run_minecraft_role" in read("app/cli.py"))

print("\n== its card: what it is doing, a goal, leaving and joining ==")
from fastapi import FastAPI  # noqa: E402

from app.core import ipc as _ipc  # noqa: E402
from app.web.routes import minecraft_routes  # noqa: E402

_sent = []


async def _fake_send(target, cmd, payload=None, timeout=10.0):
    _sent.append((target, cmd, payload))
    return {"ok": True}


_real_discover, _real_send = _ipc.discover_targets, _ipc.send_and_wait
_ipc.discover_targets = lambda: {"minecraft_1": {"platform": "minecraft", "account": 1, "target": "mc"},
                                 "discord_1": {"platform": "discord", "account": 1, "target": 1}}
_ipc.send_and_wait = _fake_send
_app = FastAPI()
_app.include_router(minecraft_routes.router)
cards = TestClient(_app)
r = cards.post("/api/minecraft/minecraft_1/goal", json={"text": "  build a\nshelter  "})
check("a goal from its card goes to the account, as its words", r.status_code == 200 and r.json() == {"ok": True}
      and _sent[-1] == ("mc", "mc_tell", {"text": "build a shelter"}))
check("an empty one is refused", cards.post("/api/minecraft/minecraft_1/goal", json={"text": " "}).status_code == 400)
cards.post("/api/minecraft/minecraft_1/leave")
cards.post("/api/minecraft/minecraft_1/join")
check("leaving the world and joining it again", [c for _, c, _ in _sent[-2:]] == ["mc_leave", "mc_join"])
check("nothing for an account that is not Minecraft's, or a request it does not know",
      cards.post("/api/minecraft/discord_1/leave").status_code == 404
      and cards.post("/api/minecraft/minecraft_1/fly").status_code == 404)
_ipc.discover_targets, _ipc.send_and_wait = _real_discover, _real_send

runner_src = read("app/platforms/minecraft/minecraft_runner.mjs")
check("what it is doing, written into its state for the card, when it changes",
      "function reportGame(s)" in runner_src and 'core.setState("ready", "", { game })' in runner_src
      and "reportGame(s);" in runner_src)
check("ready with no words beside it: for a browser platform those mean its page changed",
      'core.setState("ready");' in runner_src and 'core.setState("ready", `' not in runner_src)
check("and passed on by the state reader", '{"game": data["game"]}' in read("app/web/routes/system_routes.py"))
card = read("webui/src/lib/accounts/AccountCard.svelte")
check("the card: a goal box while it is in the world", 'slot.platform === "minecraft" && inWorld' in card
      and 'api.minecraftOp(slot.id, "goal", text)' in card and 'placeholder="Build a shelter before dark"' in card)
check("and leave or join from its menu", '"Leave the world" : "Join the world"' in card)
check("the people it met, not 'chats watched'", '"players met"' in card)
accounts_page = read("webui/src/pages/Accounts.svelte")
check("every way to add an account offers Minecraft too: the first-run cards, the header's menu, the tile",
      all(accounts_page.count(f'openAdd("{p}")') == 3 for p in ("discord", "snapchat", "tiktok", "instagram", "minecraft")),
      str({p: accounts_page.count(f'openAdd("{p}")') for p in ("discord", "snapchat", "tiktok", "instagram", "minecraft")}))

print("\n== the app's part in its bot, under Node ==")
import subprocess  # noqa: E402

_node = shutil.which("node")
if _node:
    _p = subprocess.run([_node, str(ROOT / "tests" / "minecraft_hooks.mjs")], cwd=ROOT, capture_output=True, text=True,
                        timeout=120, encoding="utf-8", errors="replace")
    print(_p.stdout.strip())
    check("minecraft_hooks.mjs passes", _p.returncode == 0, (_p.stdout + _p.stderr)[-400:])
hooks_src = read("app/platforms/minecraft/agent_hooks.mjs")
check("loaded into mindcraft before it, nothing in mindcraft changed",
      "env.NODE_OPTIONS = `--import=${pathToFileURL(HOOKS).href}`;" in runner_src
      and "mineflayer.createBot = wrapped;" in hooks_src)
check("its live view on this computer only, under the panel's path",
      'server.listen(port, "127.0.0.1"' in hooks_src and "LSB_VIEW_PREFIX" in hooks_src
      and "const VIEW_PREFIX = `/api/minecraft/minecraft_${ACCOUNT}/view`;" in runner_src)
check("its eyes, or from above, as each viewer asks", "/[?&]view=above\\b/.test(" in hooks_src
      and "socket.emit(\"position\", { pos, yaw, pitch: bot.entity.pitch });" in hooks_src
      and "pitch: LOOK_DOWN," in hooks_src)
check("a server's resource pack accepted, as a player's client does", "bot.acceptResourcePack()" in hooks_src)
check("the password reaches only the bot's own process, never mindcraft's settings",
      "env.LSB_SERVER_PASSWORD = PASSWORD" in runner_src and "PASSWORD" not in runner_src.split("env.SETTINGS_JSON")[1].split(";")[0])
check("and is never printed", "console.log" not in hooks_src.split("export function signInOn")[1].split("// ── The live view")[0])
check("mindcraft hears players only (the server's lines never reach the persona), and sends no /skin clear",
      hooks_src.index("signInOn(bot, process.env.LSB_SERVER_PASSWORD") < hooks_src.index("  playersOnly(bot);")
      and 'bot.on("login", () => {\n    noSkinClear(bot);' in hooks_src)
check("mindcraft's word that the version chosen here is wrong, and its stack, left out",
      "const expected = chose && " in runner_src and runner_src.count("chose = true;") == 2
      and "if (quietStack && /^\\s+at /.test(line)) return;" in runner_src)

print("\n== its password on servers that ask for one ==")
check("kept under its name and the server, as the server keeps it",
      worker.password_key("Alicia_2", "play.example.net-25565") == "MINECRAFT_PASSWORD_ALICIA_2__PLAY_EXAMPLE_NET_25565")
pw = worker.new_password()
check("letters and digits, at least one of each, long enough for any plugin's rules",
      len(pw) == 14 and pw.isalnum() and any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw))
os.environ.pop(worker.password_key("Alicia", "h-1"), None)
first = worker.server_password("Alicia", "h-1")
os.environ.pop(worker.password_key("Alicia", "h-1"), None)
check("made once, kept in .env, the same one every time after",
      first and worker.server_password("Alicia", "h-1") == first
      and f"{worker.password_key('Alicia', 'h-1')}={first}" in (DATA / "config" / ".env").read_text(encoding="utf-8"))
from app.web.envfile import SECRET_KEYS  # noqa: E402

check("and masked on the Keys page, as Instagram's password and 2FA key now are too",
      all(SECRET_KEYS.match(k) for k in ("MINECRAFT_PASSWORD_ALICIA__H_1", "INSTAGRAM_PASSWORD_1", "INSTAGRAM_TOTP_1",
                                          "SNAP_PASSWORD_2", "DISCORD_TOKEN_1"))
      and not SECRET_KEYS.match("MINECRAFT_USERNAME_1") and not SECRET_KEYS.match("TELEGRAM_OWNER_ID"))

print("\n== another server ==")
check("an address as people write one", worker.parse_address("play.example.net") == ("play.example.net", 25565)
      and worker.parse_address("MC.Foo.org:25570") == ("mc.foo.org", 25570)
      and worker.parse_address("192.168.1.20") == ("192.168.1.20", 25565))
check("and not a word, a website's link or a port out of range",
      all(worker.parse_address(x) is None for x in ("hello", "https://example.com", "a.b:99999", "300.1.1.1", "")))
check("never one Settings rules out, nor anything under it", worker.blocked("mc.hypixel.net", {"never_join": ["hypixel.net"]})
      and not worker.blocked("play.foo.net", {"never_join": ["hypixel.net"]}))
from app.platforms.minecraft import link  # noqa: E402

check("a persona's yes comes out of its reply, the server it named kept",
      link.take_tags("omw!! [MC JOIN play.example.net]") == ("omw!!", ["play.example.net"]))
check("a big one by its name", link.take_tags("ok [mc join Hypixel]")[1] == ["mc.hypixel.net"])
check("and a reply with none is left alone", link.take_tags("no tag here") == ("no tag here", []))


class _Msg:
    content = "come play on mc.foo.net with me"
    user_name = "Sam"
    platform = "discord"


(DATA / "config").mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
_real_accounts, _real_persona_here = link.accounts_for, link._persona_here
link.accounts_for = lambda pid: ["minecraft_1"]
link._persona_here = lambda: "default"
check("the rule, when its persona plays Minecraft and the message is about playing somewhere",
      "[MC JOIN address]" in link.rule_for(_Msg()))
os.environ.pop("MINECRAFT_AUTH_1", None)
check("an offline account: it knows the big servers will not let it in", "cracked (offline)" in link.rule_for(_Msg())
      and link.rule_for(_Msg()).endswith("]"))
os.environ["MINECRAFT_AUTH_1"] = "microsoft"
check("a Microsoft one: nothing of the sort", "cracked" not in link.rule_for(_Msg()))
os.environ.pop("MINECRAFT_AUTH_1", None)
_Msg.content = "how was your day"
check("and nothing at all, not a token, for anything else", link.rule_for(_Msg()) == "")
link.accounts_for = lambda pid: []
_Msg.content = "come play on mc.foo.net"
check("nor for a persona with no Minecraft account", link.rule_for(_Msg()) == "")
link.accounts_for, link._persona_here = _real_accounts, _real_persona_here
eng_src = read("app/core/engine.py")
check("the engine: the rule added, the tag taken out of what is sent and kept, the account asked to go",
      "enriched += _mc_link.rule_for(msg)" in eng_src and "response, _joins = _mc_link.take_tags(response)" in eng_src
      and eng_src.index("_mc_link.take_tags(response)") < eng_src.index('history.append({"role": "assistant", "content": response})'))
bridge_src = read("app/platforms/snapchat_bridge.py")
check("the bridge: a deliberate switch is not its runner falling over",
      'if code is not None and not _MC.get("switching"):' in bridge_src and "_MC[\"switching\"] = True" in bridge_src)
check("asked by someone else: only while Settings lets it, and the owner is told",
      'if not by_owner and not mc.get("join_when_asked", True):' in bridge_src
      and '_notify_owner("Joining another server"' in bridge_src)
check("and back to its own server", 'if address.lower() in ("home", "back", "its own", "own"):' in bridge_src)

print("\n== a server that will not have it ==")
check("turned away for good: a server that wants a Microsoft account, a ban, a whitelist",
      all(worker.refused_for_good(r) for r in (
          "Failed to verify username!", "You are not logged into your Minecraft account.",
          "This server is in online mode", "You are banned from this server.", "You are not whitelisted on this server!",
          "Outdated client! Please use 1.8.9")))
check("not for what may pass: a restart, a full server, a sign-in that timed out",
      not any(worker.refused_for_good(r) for r in ("Server closed", "The server is full!", "Login timeout exceeded", "")))
check("away is anywhere but its own server", worker.away({"host": "a.net", "port": 25565}, {"host": "b.net", "port": 25565})
      and not worker.away({"host": "a.net", "port": 25565}, {"host": "A.net", "port": "25565"})
      and not worker.away({"host": "a.net", "port": 25565}, {}))
check("the big networks that let in Microsoft accounts only", worker.needs_microsoft("mc.hypixel.net")
      and worker.needs_microsoft("2b2t.org") and not worker.needs_microsoft("jartex.fun")
      and not worker.needs_microsoft("nothypixel.net"))
check("the runner says when it is kicked, not let in, and in the world",
      'core.tellPython({ kind: "mc_event", event: "kicked", reason: msg.reason || "" });' in runner_src
      and runner_src.count('event: "join_failed"') == 2 and 'event: "in_world"' in runner_src)
check("the bridge: away, turned away for good or a few times, it goes home and the owner is told",
      'event") in ("kicked", "join_failed"):' in bridge_src and "async def _mc_turned_away(reason: str)" in bridge_src
      and 'if not mcw.refused_for_good(reason) and _MC["turned_away"] < 3:' in bridge_src
      and '_notify_owner("Back on its own server"' in bridge_src)
check("and never sets out for a network that needs a Microsoft account on an offline one",
      'if (_MC.get("slot") or {}).get("auth") != "microsoft" and mcw.needs_microsoft(host):' in bridge_src)
tg_src = read("app/telegram_bot/telegram_controller.py")
check("Telegram: /mc go <server>, /mc home, and the notice told as information",
      'if sub in ("go", "server", "play"):' in tg_src and 'if sub == "home":' in tg_src
      and 'info = payload.get("kind") == "info"' in tg_src)

print("\n== ViaProxy ==")
from app.platforms.minecraft import viaproxy  # noqa: E402

_rel = {"assets": [{"name": "ViaProxy-3.4.14+java8.jar"}, {"name": "ViaProxy-3.4.14.jar"}, {"name": "x.txt"}]}
check("the Java 8 build for Java 8 to 20, the main one from 21",
      viaproxy.pick_asset(_rel, 8)["name"].endswith("+java8.jar") and viaproxy.pick_asset(_rel, 21)["name"] == "ViaProxy-3.4.14.jar"
      and viaproxy.pick_asset(_rel, 0) is None)
_fake = DATA / "not-viaproxy.jar"
import zipfile  # noqa: E402

with zipfile.ZipFile(_fake, "w") as z:
    z.writestr("META-INF/MANIFEST.MF", "Main-Class: some.other.Thing\n")
check("what is downloaded is checked to be ViaProxy before it replaces anything", not viaproxy.is_viaproxy_jar(_fake))
check("not for a server that needs a Microsoft sign-in, off, or not installed",
      viaproxy.config_for("h", 1, "microsoft", "auto") is None and viaproxy.config_for("h", 1, "offline", "off") is None
      and (viaproxy.present() or viaproxy.config_for("h", 1, "offline", "auto") is None))
check("the runner asks the server its version first, and plays 1.21.4 where it is taken",
      "function wantViaProxy(versions)" in runner_src and "function takesBest(versions)" in runner_src
      and "minecraft_version: BEST.join(\".\")" in runner_src)
check("and starts it on this computer only, signing in offline", '"--bind-address", `127.0.0.1:${port}`' in runner_src
      and '"--auth-method", "NONE"' in runner_src)

print("\n== the panel: the view through it, ViaProxy, another server ==")
_ipc.discover_targets = lambda: {"minecraft_1": {"platform": "minecraft", "account": 1, "target": "mc"}}
_ipc.send_and_wait = _fake_send
_app2 = FastAPI()
_app2.include_router(minecraft_routes.router)
c2 = TestClient(_app2)
(DATA / "ipc").mkdir(parents=True, exist_ok=True)
(DATA / "ipc" / "mc_view.json").write_text(json.dumps({"port": 0}), encoding="utf-8")
check("nothing to watch yet: a page that says so, and looks again by itself",
      c2.get("/api/minecraft/minecraft_1/view/").status_code == 503
      and "Nothing to watch yet" in c2.get("/api/minecraft/minecraft_1/view/").text
      and c2.get("/api/minecraft/minecraft_1/view/status").json()["ready"] is False)
check("the page is served with its slash, which its socket's path needs",
      c2.get("/api/minecraft/minecraft_1/view", follow_redirects=False).headers.get("location") == "/api/minecraft/minecraft_1/view/")
check("ViaProxy's own routes come before the account ones",
      [r.path for r in minecraft_routes.router.routes].index("/api/minecraft/viaproxy/install")
      < [r.path for r in minecraft_routes.router.routes].index("/api/minecraft/{web_id}/{op}"))
_sent.clear()
c2.post("/api/minecraft/minecraft_1/server", json={"address": "play.example.net"})
c2.post("/api/minecraft/minecraft_1/home")
check("another server from its card, and its own again, both as its owner",
      _sent[-2:] == [("mc", "mc_join_server", {"address": "play.example.net", "by_owner": True}),
                     ("mc", "mc_join_server", {"address": "home", "by_owner": True})], str(_sent[-2:]))
_ipc.discover_targets, _ipc.send_and_wait = _real_discover, _real_send
card2 = read("webui/src/lib/accounts/AccountCard.svelte")
check("the card: Watch, another server, and its own again when it is away",
      "onwatch?.()" in card2 and "Play on another server" in card2 and "{#if away}" in card2
      and 'placeholder="play.example.net"' in card2)
check("the page opens its live view, wide, eyes or above",
      "<WatchView account={watchFor.id}" in read("webui/src/pages/Accounts.svelte")
      and '{ id: "above", label: "From above" }' in read("webui/src/lib/accounts/WatchView.svelte"))
check("ViaProxy installed from Settings, Minecraft", "api.viaProxyInstall()" in read("webui/src/lib/components/MinecraftSetup.svelte"))
check("and the new parts shipped with the exe", "agent_hooks.mjs" in read("packaging/specparts.py")
      and '(src / "minecraft" / "agent_hooks.mjs", "agent_hooks.mjs")' in read("app/platforms/minecraft/worker.py"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + "; ".join(FAIL))
shutil.rmtree(DATA, ignore_errors=True)
sys.exit(1 if FAIL else 0)
