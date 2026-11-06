"""Who is in each call, in the Chats tab's list of servers and channels.

The list showed a voice channel's name and nothing else, and only if someone had typed in it. Now every voice channel
is listed and the people in it sit under it, muted, deafened or live. It only looks: nothing here can join a call.
Everyone below is made up.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from fastapi import HTTPException

from app.utils import voicepeople as vp
from app.web.routes import chat_routes as cr


class Asset:
    def __init__(self, url):
        self.url = url

    def replace(self, size):
        return Asset(f"{self.url}?size={size}")


def member(name):
    return NS(display_name=name, display_avatar=Asset(f"https://cdn/{name}.png"))


def state(**on):
    base = dict(self_mute=False, mute=False, suppress=False, self_deaf=False, deaf=False, self_stream=False, self_video=False)
    return NS(**{**base, **on})


class Channel:
    def __init__(self, cid, states=None, can_see=True):
        self.id = cid
        self.can_see = can_see
        if states is not None:
            self.voice_states = states

    def permissions_for(self, _who):
        return NS(read_messages=self.can_see)


class Guild:
    def __init__(self, channels, members=None, answer=None):
        self.id = 500
        self.me = NS(id=1)
        self.channels = channels
        self.members = members or {}
        self.answer = answer or []
        self.asked = []

    def get_member(self, uid):
        return self.members.get(uid)

    async def query_members(self, **kw):
        self.asked.append(kw)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


print("== who is in each call ==")
g = Guild(
    [Channel(10),  # a text channel: no voice_states at all
     Channel(11, {}),  # a voice channel with nobody in it
     Channel(12, {2: state(self_mute=True), 3: state(self_deaf=True, self_stream=True), 4: state(self_video=True, deaf=True),
                  5: state(mute=True), 6: state(suppress=True)}),
     Channel(13, {7: state()}, can_see=False)],
    {2: member("zoe"), 3: member("Adam"), 4: member("mia"), 6: member("Bo")},
)
channels, unnamed = vp.roster(g, NS(get_user=lambda uid: member("Lou") if uid == 5 else None))
check("only the channels with someone in them", list(channels) == ["12"], str(list(channels)))
check("a channel it can't see stays unseen", "13" not in channels)
people = channels["12"]["people"]
check("how many, and each one", channels["12"]["count"] == 5 and {p["id"] for p in people} == {"2", "3", "4", "5", "6"})
by = {p["id"]: p for p in people}
check("muted by themselves, or by the server", by["2"]["muted"] and by["5"]["muted"] and not by["3"]["muted"])
check("a stage's audience can't speak either, and reads the same", by["6"]["muted"])
check("deafened by themselves, or by the server", by["3"]["deaf"] and by["4"]["deaf"] and not by["2"]["deaf"])
check("live, and with their camera on", by["3"]["live"] and by["4"]["video"] and not by["2"]["live"] and not by["2"]["video"])
check("a member's name and a small picture", by["2"]["name"] == "zoe" and by["2"]["avatar"] == "https://cdn/zoe.png?size=64")
check("someone not in the member cache but known to the account has theirs too", by["5"]["name"] == "Lou")
check("everyone had a name, so nothing to ask", unnamed == [])
check("the same order every time, by name", [p["name"] for p in people] == ["Adam", "Bo", "Lou", "mia", "zoe"])

g2 = Guild([Channel(20, {8: state(), 9: state()})], {9: member("Ana")})
channels, unnamed = vp.roster(g2)
check("someone with no name yet is still listed, last, with none", [p["name"] for p in channels["20"]["people"]] == ["Ana", ""])
check("and is what the query would ask about", unnamed == [8])
crowd = Guild([Channel(30, {i: state() for i in range(1000, 1250)})], {i: member(f"p{i}") for i in range(1000, 1250)})
channels, _ = vp.roster(crowd)
check("a stage of 250 lists the first hundred and counts them all",
      channels["30"]["count"] == 250 and len(channels["30"]["people"]) == vp.MOST)


def placed(cid, cat_at, at, uid):
    ch = Channel(cid, {uid: state()})
    ch.category = NS(position=cat_at)
    ch.position = at
    return ch


g3 = Guild([placed(40, 2, 0, 44), placed(41, 1, 5, 45), placed(42, 1, 1, 46), placed(43, 3, 0, 47)])
_, unnamed = vp.roster(g3)
check("the names go from the top of the list down, not in whatever order the cache has them", unnamed == [46, 45, 44, 47], str(unnamed))
_, unnamed = vp.roster(g3, None, ["43", "40"])
check("the calls on the panel's screen first: a query only holds a hundred", unnamed == [44, 47, 46, 45], str(unnamed))


print("\n== asking for the names it doesn't have ==")


def fresh(careful=False):
    vp._asked_at.clear()
    vp._no_answer.clear()
    vp._asking.clear()
    vp.quiet = lambda: careful


fresh()
g = Guild([], answer=[NS(id=8)])
asyncio.run(vp.learn_names(g, [8, 9, 8]))
check("one query, each id once, no presences, kept in the library's cache",
      len(g.asked) == 1 and g.asked[0]["user_ids"] == [8, 9] and g.asked[0]["presences"] is False and g.asked[0]["cache"] is True)
check("its limit is at least the five the query accepts", g.asked[0]["limit"] == 5)
asyncio.run(vp.learn_names(g, [8, 9]))
check("asked again straight away: nothing goes out", len(g.asked) == 1)
vp._asked_at.clear()
asyncio.run(vp.learn_names(g, [9]))
check("someone who got no answer is left alone for a while", len(g.asked) == 1 and 9 in vp._no_answer)
vp._asked_at.clear()
vp._no_answer[9] -= vp.NO_ANSWER_FOR + 1
asyncio.run(vp.learn_names(g, [9]))
check("and asked about again after it", len(g.asked) == 2)

fresh()
g = Guild([], answer=[])
asyncio.run(vp.learn_names(g, list(range(1, 300))))
check("a hundred at most in one query", len(g.asked[0]["user_ids"]) == 100 and g.asked[0]["limit"] == 100)

fresh(careful=True)
g = Guild([])
asyncio.run(vp.learn_names(g, [8]))
check("careful mode asks nothing", g.asked == [])
looked = []
vp.quiet = lambda: looked.append(1) or True
asyncio.run(vp.learn_names(g, [8]))
check("and the config is read at most once per wait, not on every look", looked == [])

fresh()
g = Guild([], answer=RuntimeError("gateway said no"))
asyncio.run(vp.learn_names(g, [8]))
check("a query that fails stays quiet and frees the server for later", 8 in vp._no_answer and vp._asking == set())
vp.quiet = lambda: False


print("\n== it only looks ==")
source = read("app/utils/voicepeople.py")
for word in (".connect(", "change_voice_state", ".move_to(", ".disconnect(", "edit(", ".send("):
    check(f"voicepeople.py never calls {word}", word not in source)
runner = read("app/platforms/discord_runner.py")
job = runner[runner.index("async def _voice_people_job"):runner.index("async def _send_message_job")]
check("the runner has the job and the command", 'elif cmd == "voice_people":' in runner and "_voice_people_job(cmd_id, payload)" in runner)
check("it answers at once, out of the cache: the names are looked for behind it",
      "await " not in job and "asyncio.create_task(_voicepeople.learn_names(g, unnamed))" in job)
for word in (".connect(", "change_voice_state", "CallSession", "send("):
    check(f"the job has no {word} in it", word not in job)
tree = read("webui/src/lib/components/ServerTree.svelte")
call = tree[tree.index('<ul class="st-call"'):tree.index("</ul>")]
check("a person is a row to read: nothing in it can be pressed", "<button" not in call and "onclick" not in call)
markup = tree[tree.index("</script>"):tree.index("<style>")]
for word in ("join", "Join", "Leave", "Unmute", "Mute ", "Deafen "):
    check(f"no control for it in the list: \"{word}\"", word not in markup)


print("\n== the route ==")
sent = []
answer = {"ok": True, "channels": {"12": {"count": 1, "people": []}}}


async def send_and_wait(tgt, cmd, payload, timeout):
    sent.append((tgt, cmd, payload, timeout))
    return answer


cr._resolve_target = lambda request, target: target or "discord_1"
cr.ipc.send_and_wait = send_and_wait
real_platform = cr.ipc.platform_of
cr.ipc.platform_of = lambda t: t.split("_")[0]
r = asyncio.run(cr.voice_people(None, "discord_1", "500"))
check("Discord asks its account, for that server",
      sent == [("discord_1", "voice_people", {"guild": "500", "first": []}, 12.0)] and r["supported"] and r["channels"]["12"]["count"] == 1)
sent.clear()
asyncio.run(cr.voice_people(None, "discord_1", "500", "12,x,13," + ",".join(str(n) for n in range(80))))
check("the calls on screen go along, ids only, and no more than fifty",
      sent[0][2]["first"][:2] == ["12", "13"] and len(sent[0][2]["first"]) == 50)
sent.clear()
for other in ("snapchat_1", "telegram_1", "tiktok_1"):
    r = asyncio.run(cr.voice_people(None, other, "500"))
    check(f"{other} has no voice channels: none, and nothing asked", r == {"channels": {}, "supported": False, "target": other} and not sent)


def refused(status, *a):
    try:
        asyncio.run(cr.voice_people(None, *a))
    except HTTPException as e:
        return e.status_code == status
    return False


check("a server that isn't an id is refused", refused(400, "discord_1", "abc") and not sent)
answer = None
check("an account that doesn't answer says so", refused(504, "discord_1", "500"))
answer = {"ok": False, "reason": "no"}
check("and one that couldn't read them", refused(502, "discord_1", "500"))
cr.ipc.platform_of = real_platform


print("\n== in the list ==")
api = read("webui/src/lib/api.ts")
check("the panel asks through its own route", "chatsVoice: (target: string, guild: string, first: string[] = []) =>" in api and "/api/chats/voice?target=" in api)
check("and it isn't a page being slow when it takes a moment", '"/api/chats/voice",' in api.split("SLOW_EXEMPT", 1)[1].split("];", 1)[0])
check("Discord's servers only", 'if (word !== "server" || !t || !g) return;' in tree)
check("at once, then every few seconds while the list is on screen",
      "void read();" in tree and "visiblePoll(read, CALLS_EVERY)" in tree and "const CALLS_EVERY = 6000;" in tree)
check("an answer for a server left meanwhile is dropped", "if (left) return;" in tree and "left = true;" in tree)
check("asked one at a time, so a slow or stopped account doesn't collect a queue of them", "if (asking || left) return;" in tree)
check("the calls on screen are said with each ask", "api.chatsVoice(t, g, inView())" in tree and "data-ch={ch.id}" in tree)
check("the first look's missing names come in a moment, not a few seconds", "setTimeout(read, 1500)" in tree)
check("hundreds of lists don't slide open at once: a first answer, or one after a long gap, just appears",
      "sliding = performance.now() - heardAt < CALLS_EVERY * 2.5" in tree and "return sliding && get(motionEnabled) ? slide(node" in tree and ": { duration: 0 };" in tree and "heardAt = 0;" in tree)
check("nor in a server with a thousand in calls, where each slide cost 14 ms of a held window every few seconds",
      "c.people.length, 0) <= SLIDE_UP_TO" in tree and "const SLIDE_UP_TO = 150;" in tree)
check("off screen a call isn't laid out, at the size it says it will be",
      "content-visibility: auto;" in tree and "contain-intrinsic-block-size: {(calls[ch.id].people.length + (calls[ch.id].count > calls[ch.id].people.length ? 1 : 0)) * 25 + 3}px" in tree)
check("and the column can't squeeze it: it would grow back as it came on screen, moving the scrollbar",
      ".st-call { display: flex; flex: 0 0 auto;" in tree)
check("kept as it came, not wrapped person by person", "let calls = $state.raw<Record<string, Call>>({});" in tree)
check("a list that isn't being searched isn't worked out again every few seconds",
      tree.index("if (words.length) {") < tree.index("(calls[ch.id]?.people ?? []).map((p) => p.name)"))
avatar = read("webui/src/lib/components/Avatar.svelte")
check("a thousand pictures aren't fetched for rows nobody has scrolled to",
      "zoom={false} lazy />" in tree and 'loading={lazy ? "lazy" : undefined}' in avatar
      and avatar.index('loading={lazy ? "lazy" : undefined}') < avatar.index("src={shownSrc}", avatar.index('loading={lazy ? "lazy" : undefined}')))
check("under its channel, keyed by person, sliding as they come and go",
      "{#each calls[ch.id].people as p (p.id)}" in tree and tree.count("transition:arrive={") == 2)
check("someone with no name yet", 'p.name || "Someone"' in tree)
check("muted, deafened, camera and live each say so",
      'title="Muted"' in tree and 'title="Deafened"' in tree and 'title="Camera on"' in tree and '<span class="st-live">Live</span>' in tree)
check("more than it lists says how many", "calls[ch.id].count > calls[ch.id].people.length" in tree and "more</li>" in tree)
check("the list's search finds someone in a call", "(calls[ch.id]?.people ?? []).map((p) => p.name)" in tree)
icons = read("webui/src/lib/components/Icon.svelte")
check("its marks are drawn", all(f"{n}: " in icons for n in ("micOff", "headphonesOff", "camera")))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
