"""What an account is thinking, wherever it is shown: the Dashboard, its card, over what a Minecraft account sees, and Big
Picture, with its new scenes and every platform's logo. And the Ready card on the platforms with nothing to install."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name

from app.platforms.minecraft import brain as brain_mod  # noqa: E402
from app.utils import logger  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


print("\n== a Minecraft account's decisions ==")
said = []
real_log = logger.log_thinking


def fake_log(text, model=""):
    logger.thoughts_logged += 1
    said.append(text)


logger.log_thinking = fake_log
from app.platforms.minecraft import profile  # noqa: E402

b = brain_mod.Brain(1, server="test", public=True)


async def go(reply, reasons=False):
    async def raw(system, turns):
        if reasons:
            logger.log_thinking("Long reasoning first", "m")
        return reply
    b._raw = raw
    from app.platforms.minecraft import persona as persona_mod
    real_brief = persona_mod.brief

    async def brief():
        return ""
    persona_mod.brief = brief
    b.listening = lambda name="": True
    try:
        return await b.answer({"messages": [{"role": "system", "content": profile.MARKERS["conversing"] + " you play"},
                                            {"role": "user", "content": "Code output: done"}]})
    finally:
        persona_mod.brief = real_brief


out = asyncio.run(go("Getting dark. Dig in. !collectBlocks(\"dirt\", 8)"))
check("what it means to do next is a thought", said == ['Getting dark. Dig in. !collectBlocks("dirt", 8)'], str(said))
check("and it still says it", "collectBlocks" in out, out)
said.clear()
asyncio.run(go("!goToPlayer(\"x\", 2)", reasons=True))
check("a model that has just reasoned out loud is not talked over", said == ["Long reasoning first"], str(said))
logger.log_thinking = real_log

print("\n== the feed ==")
store = read("webui/src/lib/thoughts.ts")
check("from the log's own kind of line", 'e.level !== "think"' in store)
check("not twice when the socket says its last lines again", "known.has(" in store)
check("and what was thought before anyone looked", "api.logs(400)" in store)

print("\n== shown ==")
live = read("webui/src/lib/components/LiveThought.svelte")
check("typed out, however long, without taking long", "t.text.length / 400" in live)
check("not typed if it is old news", "Date.now() / 1000 - t.at > 20" in live)
check("a switched-off social's are not shown", "sourceOn($socialsOn, t.source)" in live)
check("no room at all on a card with nothing fresh", "{:else if showing && latest}" in live)
check("nothing moves behind the blur that is not there: no backdrop filter", "backdrop-filter" not in live)
check("on the Dashboard", '{:else if inst.type === "thoughts"}' in read("webui/src/lib/dashboard/WidgetBody.svelte")
      and '"thoughts"' in read("webui/src/lib/dashboard/widgets.ts"))
check("once on a Dashboard laid out before it existed, and it can be taken off",
      "withNewOnes(normalise(get(dashLayout)))" in read("webui/src/pages/Dashboard.svelte"))
check("on an account's card", '<LiveThought source={slot.id} variant="line" />' in read("webui/src/lib/accounts/AccountCard.svelte"))
watch = read("webui/src/lib/accounts/WatchView.svelte")
check("over what a Minecraft account sees, with a switch", '<LiveThought source={account} variant="overlay" />' in watch
      and "showThoughts = !showThoughts" in watch)
check("the whole of the log still has them, its Dashboard part leaves them out", 'l.level !== "think"' in read("webui/src/pages/Dashboard.svelte"))

print("\n== Big Picture ==")
bp = read("webui/src/lib/bigpicture/BigPicture.svelte")
world = read("webui/src/lib/bigpicture/world.svelte.ts")
director = read("webui/src/lib/bigpicture/director.ts")
check("whose thought it is, in the conversation or by name", "thought.source" in read("webui/src/lib/bigpicture/BPRail.svelte")
      and "t.source !== spot.target" in bp)
check("the Minecraft view comes round when there is one to watch", "minecraft: !!world.minecraft" in bp and "<BPMinecraft" in bp)
check("long enough for it to draw the world", "minecraft: 24" in director)
check("nothing on the picture takes the pointer", "pointer-events: none" in read("webui/src/lib/bigpicture/BPMinecraft.svelte"))
check("every platform's logo, with its week", "<PlatformMark" in read("webui/src/lib/bigpicture/BPAccounts.svelte") and "api.statsDetail(7)" in world)
check("a switched-off one is not on it", "on[p as keyof typeof on] !== false" in world)
check("a logo in the queue", "<PlatformMark" in read("webui/src/lib/bigpicture/BPQueue.svelte"))
check("on the stage", "<PlatformMark" in read("webui/src/lib/bigpicture/BPStage.svelte"))
check("in the list of what just happened", "<PlatformMark" in read("webui/src/lib/bigpicture/BPRail.svelte") and "platformOfUser(o.uid).id" in world)
check("on everyone it talks to", read("webui/src/lib/bigpicture/BPPeople.svelte").count("<PlatformMark") >= 2)

print("\n== the Ready card ==")
hero = read("webui/src/lib/components/ReadyHero.svelte")
ready = read("webui/src/lib/components/PlatformReady.svelte")
settings = read("webui/src/pages/Settings.svelte")
smap = read("webui/src/lib/settingsmap.ts")
check("Discord has it", '<PlatformReady platform="discord" />' in settings and 'panel: "discord-setup"' in smap)
check("Telegram has it", '<PlatformReady platform="telegram" />' in settings and 'panel: "telegram-setup"' in smap)
check("iMessage has it, both ways", read("webui/src/lib/components/ImessageSetup.svelte").count("<ReadyHero") == 2)
check("the same bar lighting, note by note, with the bell", 'play("rise"' in hero and 'play("done")' in hero)
check("the Ready badge only once it is", "{:else if ready}" in hero)
check("a part that stops being true goes out", "One that has stopped being true goes out" in hero)
check("what to do next is on the card", '"Add an account"' in ready and '"Choose a model"' in ready and "Start</Button>" in ready)
check("they belong to no persona", '"discord-setup", "telegram-setup"' in settings)
check("Telegram's accounts say what they are doing", 'if meta["platform"] in registry.BRIDGED:' in read("app/web/routes/status_routes.py"))
check("the name of a tab at the top goes to the start of it, not to its leftovers",
      smap.index("const tab = TABS.find((t) => t.id === q") < smap.index("if (KEY_HOME[want]) return KEY_HOME[want];"))

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
