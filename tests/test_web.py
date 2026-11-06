"""The persona on the web (app/utils/web): looking something up when a message needs it, reading the links people
send, and browsing in its own free time.

Run here with no network: the guard on what may be opened, a page boiled down to its words, DuckDuckGo's results
read, the agent's turns with a scripted model and a pretend web, the LOOKUP marker and the second ask, the budget,
what it saw kept and told to the replies, the free-time clock, and the wiring into both reply builders, the bridge,
the settings and the panel. tests/web_logic.mjs runs the Chats status under Node. The live runs (a real search, a
real page, the real models) are in the plan's verification, not here.
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WEB = ROOT / "webui"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def run(coro):
    return asyncio.run(coro)


import app.utils.web as web  # noqa: E402
from app.utils.web import agent, guard, journal, links, lookup, page, search  # noqa: E402

# ── Settings ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("== bot.web ==")
s = web.settings({})
check("everything on by default, at a gentle pace", s == {"enabled": True, "links": True, "free_time": True,
                                                         "sessions_per_day": 3, "search_with": "auto",
                                                         "share_links": True, "per_hour": 12}, str(s))
s = web.settings({"bot": {"web": {"per_hour": 999, "sessions_per_day": -4, "search_with": "Bing", "links": False}}})
check("counts kept in range, an unknown engine ignored", s["per_hour"] == 120 and s["sessions_per_day"] == 0
      and s["search_with"] == "auto" and s["links"] is False, str(s))
cfg = read("resources/config.yaml")
check("the shipped config has it, all on", "  web:\n    enabled: true\n    links: true\n    free_time: true\n"
      "    sessions_per_day: 3\n    search_with: auto" in cfg)

# ── Where it may go ──────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== the guard ==")
for url, why in (("http://127.0.0.1:8787/api/accounts", "the panel"), ("http://localhost:8787/", "localhost"),
                 ("http://192.168.1.1/admin", "the router"), ("http://10.0.0.7/", "a private address"),
                 ("http://[::1]/", "IPv6 loopback"), ("http://[fe80::1]/", "link-local"),
                 ("http://169.254.169.254/latest/meta-data", "cloud metadata"), ("file:///C:/Windows/win.ini", "a file"),
                 ("javascript:alert(1)", "a script"), ("https://nas.local/", ".local"), ("https://intranet/", "no dot"),
                 ("https://me:secret@example.com/", "a login in the link"), ("http://[::ffff:127.0.0.1]/", "mapped")):
    try:
        guard.check_url(url)
        check(f"refused: {why}", False, url)
    except guard.Blocked:
        check(f"refused: {why}", True)
check("a public site is allowed", guard.check_url("https://www.example.com/a?b=1") == "https://www.example.com/a?b=1")
check("a public address is allowed", guard.check_url("http://93.184.216.34/") == "http://93.184.216.34/")
try:
    run(guard.check("http://127.0.0.1/"))
    check("the async check refuses too", False)
except guard.Blocked:
    check("the async check refuses too", True)
try:
    guard.check_sync("http://10.1.2.3/")
    check("and the one for worker threads", False)
except guard.Blocked:
    check("and the one for worker threads", True)
p = run(page.fetch("http://127.0.0.1:8787/api/accounts"))
check("a page read never reaches the panel", not p.ok and p.blocked and "inside this computer" in p.error, p.error)

# ── A page, boiled down ──────────────────────────────────────────────────────────────────────────────────────────
print()
print("== reading a page ==")
MENU = "".join(f'<li><a href="/s/{i}">Section {i}</a></li>' for i in range(30))
HTML = f"""<html><head><title>Old title</title><meta property="og:title" content="Antonelli wins in Austin">
<meta name="description" content="Race report"><meta property="og:site_name" content="RaceNews"></head>
<body><header><a href="/">Home</a></header><nav><a href="/news">News</a></nav>
<div class="menu"><ul>{MENU}</ul></div>
<svg><title>logo</title></svg>
<article><h1>Antonelli wins in Austin</h1>
<p>Kimi Antonelli won the United States Grand Prix on Sunday, ahead of Charles Leclerc and Max Verstappen.</p>
<p>It was his ninth win of the season, and he now leads the championship by 123 points.</p>
<p>Read more about the <a href="/standings">standings</a> and the <a href="https://other.example/next">next race</a>.</p>
<p>{"Filler words about the race. " * 12}</p>
<script>var tracking = 1;</script>
</article><footer>Copyright</footer><a href="javascript:void(0)">x</a><a href="mailto:a@b.c">mail</a></body></html>"""
p = page.extract(HTML, "https://racenews.example/f1/austin")
check("the title is the page's own", p.title == "Antonelli wins in Austin", p.title)
check("the site by its own name", p.site == "RaceNews", p.site)
check("the article is what is read", p.text.startswith("Antonelli wins in Austin\nKimi Antonelli won"), p.text[:80])
check("no menus, header, footer or scripts", "Section 3" not in p.text and "Home" not in p.text
      and "Copyright" not in p.text and "tracking" not in p.text and "logo" not in p.text, p.text)
check("links made whole, scripts and mail left out",
      {"text": "standings", "url": "https://racenews.example/standings"} in p.links
      and not any(link["url"].startswith(("javascript", "mailto")) for link in p.links), str(p.links[:4]))
lines = ["Back", "About", "Back", "News", "Back", "A real sentence about the race."]
check("a short line said over and over is furniture", page._tidy(lines) == "About\nNews\nA real sentence about the race.")
check("a line that is only a link's words is a menu",
      page._tidy(["News", "The news today was big."], frozenset({"News"})) == "The news today was big.")

# ── DuckDuckGo ───────────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== a search ==")
DDG = """<div class="result results_links result--ad"><h2 class="result__title">
<a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Buy tickets</a></h2>
<a class="result__snippet">An ad.</a></div>
<div class="result results_links results_links_deep web-result"><div class="links_main result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.formula1.com%2Fen%2Fresults&amp;rut=abc">2026 RACE <b>RESULTS</b></a></h2>
<a class="result__snippet" href="x">The <b>latest</b> F1 results.</a></div></div>
<div class="result results_links web-result"><div class="links_main result__body">
<h2 class="result__title"><a class="result__a" href="https://www.bbc.co.uk/sport/formula1">F1 - BBC Sport</a></h2>
<div class="result__snippet">News and results.</div></div></div>"""
rs = search.parse_duckduckgo(DDG)
check("its results read, the ad left out", [r.url for r in rs] == ["https://www.formula1.com/en/results",
                                                                     "https://www.bbc.co.uk/sport/formula1"],
      str([r.url for r in rs]))
check("titles and lines without their markup", rs[0].title == "2026 RACE RESULTS" and rs[0].snippet == "The latest F1 results.",
      f"{rs[0].title!r} {rs[0].snippet!r}")
tmp = Path(tempfile.mkdtemp(prefix="lsb-web-"))
real_rest = search._rest_file
search._rest_file = lambda: tmp / "google.json"
search._google_rested_until, search._google_strikes = 0.0, 0
try:
    check("auto: Google first when there is a browser", search.order("auto", True)[:2] == ["google", "duckduckgo"])
    check("and DuckDuckGo first without one", search.order("auto", False)[0] == "duckduckgo")
    check("no key, no Brave", "brave" not in search.order("brave", False))
    first = search.rest_google()
    second = search.rest_google()
    check("a captcha rests Google an hour, twice as long the next time", first == 3600 and second == 7200,
          f"{first} {second}")
    check("every account sees the rest (it is kept on disk)", json.loads((tmp / "google.json").read_text())["strikes"] == 2)
    check("and Google is skipped meanwhile", "google" not in search.order("auto", True))
    search.google_answered()
    check("an answer from it clears the rest", not search.google_resting())
finally:
    search._rest_file = real_rest

# ── The agent ────────────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== the agent's turns ==")
pa = agent.parse_action
check("an action in code fences", pa('```json\n{"do": "search", "q": "f1"}\n```') == {"do": "search", "q": "f1"})
check("the first of two actions", pa('ok {"do": "open", "n": 2} then {"do": "more"}') == {"do": "open", "n": 2})
check("braces inside its words", pa('{"do": "answer", "text": "it is {big}"}') == {"do": "answer", "text": "it is {big}"})
check("a browser tool call read as its action", pa('{"name": "browser.search", "arguments": {"query": "louvre"}}')
      == {"do": "search", "q": "louvre"})
check("its open by number too", pa('{"name": "browser.open", "arguments": {"id": 3}}') == {"do": "open", "n": 3})
check("words alone are no action", pa("sure, let me look") is None)

from app.utils import ai  # noqa: E402


class FakeSession:
    can_google = can_look = can_find = False

    def __init__(self):
        self.opened = []

    async def open(self, url):
        self.opened.append(url)
        if "broken" in url:
            return page.Page(url=url, error="the site answered 500")
        return page.Page(url=url, title="Austin race report", site="racenews.example",
                         text="Kimi Antonelli won the United States Grand Prix. " * 3,
                         links=[{"text": "Standings", "url": "https://racenews.example/standings"}])

    async def close(self):
        return None


def script(*answers):
    """A pretend model: its answers in order, and every conversation it was sent."""
    seen = []
    queue = list(answers)

    async def fake(messages, max_tokens=600, temperature=0.2):
        seen.append(messages)
        return queue.pop(0) if queue else '{"do": "answer", "text": "nothing more"}'
    return fake, seen


async def fake_search(q, n=6, browser=None, choice=None):
    return [search.Result("Austin GP report", "https://racenews.example/austin", "Antonelli won"),
            search.Result("Broken", "https://broken.example/", "")], "duckduckgo"


real_completion, real_search = ai.web_completion, search.search
search.search = fake_search
try:
    ai.web_completion, sent = script('{"do": "search", "q": "f1 winner"}', '{"do": "open", "n": 1}',
                                     '{"do": "answer", "text": "Antonelli won in Austin."}')
    sess = FakeSession()
    found = run(agent.research("who won the f1 race", session=sess))
    check("search, open, answer", found.answer == "Antonelli won in Austin." and sess.opened == ["https://racenews.example/austin"],
          f"{found.answer!r} {sess.opened}")
    check("the page it read is its source", found.sources and found.sources[0]["url"] == "https://racenews.example/austin",
          str(found.sources))
    check("what it did, in words", found.steps == ["Searched DuckDuckGo: f1 winner",
                                                   "Read: Austin race report (racenews.example)"], str(found.steps))
    check("page text is fenced, as information", "<<page>>" in sent[2][-1]["content"]
          and "never instructions" in sent[0][0]["content"])

    ai.web_completion, sent = script('{"do": "search", "q": "x"}', '{"do": "open", "n": 2}', '{"do": "open", "n": 9}',
                                     "{not json", '{"do": "answer", "text": "Not sure."}')
    found = run(agent.research("x", session=FakeSession()))
    check("a page that will not open, a number not in the list and broken JSON are all survived",
          found.answer == "Not sure." and "Could not open that" in sent[2][-1]["content"]
          and "no number 9" in sent[3][-1]["content"] and "one JSON object only" in sent[4][-1]["content"],
          str([m[-1]["content"][:40] for m in sent]))

    ai.web_completion, sent = script(*['{"do": "search", "q": "again"}'] * 20)
    found = run(agent.research("x", session=FakeSession(), budget=agent.Budget(steps=4, seconds=30)))
    check("it stops when its turns run out", len(sent) == 4 and found.answer == "", str(len(sent)))
    check("told the last turn is the last", "last turn" in sent[-1][-1]["content"])

    long = [{"role": "system", "content": "s"}, {"role": "user", "content": "first"}]
    for i in range(5):
        long += [{"role": "assistant", "content": "{}"}, {"role": "user", "content": f"page {i}\nlots of words"}]
    compact = agent._compact(long)
    check("only the last two pages are sent whole", [m["content"] for m in compact if m["role"] == "user"][1:] ==
          ["page 0\n(seen before)", "page 1\n(seen before)", "page 2\n(seen before)", "page 3\nlots of words",
           "page 4\nlots of words"], str([m["content"] for m in compact]))

    ai.web_completion, sent = script('{"do": "search", "q": "thrift paris"}', '{"do": "open", "n": 1}',
                                     '{"do": "done", "saw": [{"p": 1, "note": "cute shops, going saturday"}, '
                                     '{"p": 7, "note": "never read"}]}')
    found = run(agent.wander("Maya", "You love thrifting.", ["old thing (x.com)"], session=FakeSession()))
    check("free time: what it saw, in its words, only pages it read",
          found.saw == [{"title": "Austin race report", "url": "https://racenews.example/austin",
                         "site": "racenews.example", "note": "cute shops, going saturday"}], str(found.saw))
    check("told what it looked at lately, to pick something else", "old thing (x.com)" in sent[0][0]["content"])
finally:
    ai.web_completion, search.search = real_completion, real_search

# ── A reply that needs the web ───────────────────────────────────────────────────────────────────────────────────
print()
print("== LOOKUP and the second ask ==")
check("the marker read", lookup.marker("LOOKUP: who won the f1 race") == "who won the f1 race")
check("in bold too", lookup.marker("**LOOKUP:** weather in paris**") == "weather in paris")
check("never inside a sentence", lookup.marker("I was going to lookup: nah") == "" and lookup.marker("hey") == "")
check("a stray marker taken out of a reply", lookup.strip("ok sure\nLOOKUP: price of ps5") == "ok sure")

calls = []


def gen_script(*answers):
    queue = list(answers)

    async def gen(instructions):
        calls.append(instructions)
        return queue.pop(0)
    return gen


real_research, real_session, real_release, real_settings = agent.research, None, None, lookup.settings
from app.utils.web import browser  # noqa: E402
real_session, real_release = browser.session, browser.release
researched = []


async def fake_research(task, about="", session=None, budget=agent.LOOKUP, on_step=None):
    researched.append(task)
    return agent.Found(task=task, answer="Antonelli won the US GP.", sources=[{"title": "Report", "url": "https://r.example/a", "site": "r.example"}])


async def fake_session():
    return agent.PlainSession()


async def fake_release(sess):
    return None


lookup_settings = {**web.DEFAULTS}
agent.research, browser.session, browser.release = fake_research, fake_session, fake_release
lookup.settings = lambda config=None: dict(lookup_settings)
lookup._stamps.clear()
lookup._busy.clear()
try:
    states = []
    turn = lookup.Turn(who="faris", conv="c1", about="who won?", on_lookup=lambda t: states.append(t))
    calls.clear()
    reply = run(turn.answer(gen_script("LOOKUP: who won the f1 race", "antonelli lol"), "PERSONA"))
    check("asked with the rule, looked, asked again with what was found", reply == "antonelli lol"
          and "LOOKING THINGS UP" in calls[0] and "WHAT YOU FOUND ONLINE" in calls[1] and "Antonelli won" in calls[1]
          and "LOOKING THINGS UP" not in calls[1], str(calls))
    check("the chat said it was looking, then writing", states == ["who won the f1 race", ""], str(states))
    check("links only when they ask, and never a cited source", "only when they ask for one" in calls[1]
          and "Never cite a source" in calls[1])
    calls.clear()
    again = run(turn.answer(gen_script("antonelli!!"), "PERSONA"))
    check("a retry uses what was found, no second search", again == "antonelli!!" and len(researched) == 1
          and "WHAT YOU FOUND ONLINE" in calls[0], str(researched))

    calls.clear()
    plain = run(lookup.Turn(conv="c2").answer(gen_script("haha same"), "PERSONA"))
    check("a message that needs nothing: one ask, the reply as it is", plain == "haha same" and len(calls) == 1)

    lookup_settings["per_hour"] = 1
    lookup._stamps.clear()
    run(lookup.Turn(conv="c3").answer(gen_script("LOOKUP: a", "ok"), "P"))
    calls.clear()
    over = run(lookup.Turn(conv="c4").answer(gen_script("LOOKUP: b", "dunno tbh"), "P"))
    check("past the hour's allowance: asked again without looking", over == "dunno tbh" and "cannot check" in calls[1]
          and len(researched) == 2, str(calls))
    lookup_settings["per_hour"] = 12

    lookup_settings["enabled"] = False
    calls.clear()
    off = run(lookup.Turn(conv="c5").answer(gen_script("hi"), "P"))
    check("switched off: no rule at all", off == "hi" and "LOOKING THINGS UP" not in calls[0])
    lookup_settings["enabled"] = True

    calls.clear()
    stubborn = run(lookup.Turn(conv="c6").answer(gen_script("LOOKUP: x", "LOOKUP: y", "fine, no idea"), "P"))
    check("a marker in the second answer too: once more, plainly", stubborn == "fine, no idea" and len(calls) == 3,
          str(calls))

    class ToolRefused(Exception):
        body = {"error": {"code": "tool_use_failed",
                          "failed_generation": '{"name": "browser.search", "arguments": {"query": "louvre hours"}}'}}

        def __str__(self):
            return "Error code: 400 - tool_use_failed"

    async def tool_then_reply(instructions, _n=[0]):
        _n[0] += 1
        if _n[0] == 1:
            raise ToolRefused()
        return "open 9 to 6"

    researched.clear()
    reply = run(lookup.Turn(conv="c7").answer(tool_then_reply, "P"))
    check("a model reaching for its own browser: the search it wanted is the lookup",
          reply == "open 9 to 6" and researched == ["louvre hours"], f"{reply!r} {researched}")
finally:
    agent.research, browser.session, browser.release, lookup.settings = real_research, real_session, real_release, \
        real_settings

# ── What it saw, kept ────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== the journal ==")
from app.utils import personas  # noqa: E402

real_folder, real_web_settings = personas.folder, web.settings
personas.folder = lambda pid: tmp / pid
web.settings = lambda config=None: dict(web.DEFAULTS)
try:
    journal.add("maya", [{"title": "Thrift shops", "url": "https://a.example/thrift", "site": "a.example",
                          "note": "cute ones near bastille"}, {"title": "no note", "url": "https://b.example", "note": ""}])
    rows = journal.entries("maya")
    check("kept, in its own folder, only with a note", len(rows) == 1 and (tmp / "maya" / "web_journal.json").exists())
    block = journal.prompt_block("maya")
    check("the replies are told, to bring it up only when it fits",
          "THINGS YOU SAW ONLINE LATELY" in block and "cute ones near bastille" in block and "only when it fits" in block,
          block)
    check("with its link, since links are on", "https://a.example/thrift" in block)
    journal.add("maya", [{"title": "Thrift shops again", "url": "https://a.example/thrift", "note": "went, loved it"}])
    check("one entry a page, the newest", len(journal.entries("maya")) == 1 and journal.entries("maya")[0]["note"] == "went, loved it")
    check("forgotten when asked", journal.remove("maya", journal.entries("maya")[0]["ts"]) and journal.entries("maya") == [])
    web.settings = lambda config=None: {**web.DEFAULTS, "free_time": False}
    journal.add("maya", [{"title": "x", "url": "https://c.example", "note": "n"}])
    check("free time off: nothing said about it", journal.prompt_block("maya") == "")
finally:
    personas.folder, web.settings = real_folder, real_web_settings

# ── Links people send, and the free-time clock ───────────────────────────────────────────────────────────────────
print()
print("== links and free time ==")
check("other links are read; TikTok's, Discord's files and pictures are not",
      links.links_in("see https://news.example/a, https://www.tiktok.com/@x/video/1 https://cdn.discordapp.com/x.png "
                     "https://img.example/cat.jpg https://b.example/page!") == ["https://news.example/a", "https://b.example/page"])
check("two a message at most", len(links.links_in(" ".join(f"https://s{i}.example" for i in range(5)))) == 2)
from app.utils.web import freetime  # noqa: E402

night = {"bot": {"night_invisible": {"hours": "2-8", "timezone": "Europe/Paris"}}}
check("asleep at 3am", not freetime.awake(night, datetime(2026, 10, 31, 3, 0)))
check("awake at 3pm", freetime.awake(night, datetime(2026, 10, 31, 15, 0)))
late = {"bot": {"night_invisible": {"hours": "23-7"}}}
check("a night across midnight", not freetime.awake(late, datetime(2026, 10, 31, 23, 30))
      and not freetime.awake(late, datetime(2026, 10, 31, 6, 0)) and freetime.awake(late, datetime(2026, 10, 31, 12, 0)))
check("sessions spread over a waking day", 0.6 * 16 * 3600 / 3 <= freetime._gap(3) <= 1.4 * 16 * 3600 / 3)

# ── Wiring ───────────────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== wiring ==")
eng, disc, bridge = read("app/core/engine.py"), read("app/platforms/discord_runner.py"), read("app/platforms/snapchat_bridge.py")
check("the bridge's replies go through the web turn", "response = await (_web.answer(_reply, enriched) if _web else _reply(enriched))" in eng
      and "enriched += _web_journal.prompt_block()" in eng)
check("a picture is described once, not again on the second ask", "IMAGE_SEEN if _seen_picture" in eng
      and "IMAGE_SEEN if _seen_picture" in disc)
check("Discord's too, every attempt sharing one turn", disc.count("response = await _write()") == 3
      and "set_reply_state(uid, \"looking\" if task else \"writing\", reason=task)" in disc)
check("the chat says it is looking", "_set_state(_c, \"looking\" if task else \"writing\"" in bridge)
check("not for the iPhone relay, which waits a fixed time", '"relay": True' in bridge and '{"no_web": True} if entry.get("relay")' in bridge)
check("not for Minecraft or a LIVE", '"no_web": True}' in read("app/platforms/minecraft/brain.py")
      and read("app/utils/livecohost.py").count('"no_web": True') == 2)
check("links read in both builders", 'or ("http" in (msg.content or "") and not (msg.extra or {}).get("no_web"))' in eng
      and 'or "http" in (prompt or "")' in disc and "web_links.enrich(text)" in read("app/utils/videowatch.py"))
from app.utils import providers  # noqa: E402
check("a model job of its own, on a model that is not the replies'", providers.JOBS["web"]["needs"] == "chat"
      and providers.DEFAULTS["web"] == "qwen/qwen3.8-27b")
check("its calls counted under that job", '_job_call("web", elsewhere, on_groq)' in read("app/utils/ai.py"))
check("the browser files sit beside Puppeteer", 'p.suffix in (".js", ".mjs")' in bridge
      and (ROOT / "app/platforms/snapchat/webbrowser.js").is_file())
schema = read("app/web/schema.py")
check("every setting in the schema, with its default", all(f'"key": "bot.web.{k}"' in schema for k in web.DEFAULTS))
desc = read("app/web/descriptions.py")
check("each with a short label", all(f'"bot.web.{k}": "' in desc for k in web.DEFAULTS))
smap = read("webui/src/lib/settingsmap.ts")
check("a subtab of AI behaviour: The web", 'id: "web",\n        name: "The web",' in smap)
sett = read("webui/src/pages/Settings.svelte")
check("Search with, as plain choices", '"bot.web.search_with": [' in sett
      and '{ value: "auto", label: "Automatic", hint: "Google, then DuckDuckGo. Free"' in sett)
check("the counts on dials", '"bot.web.per_hour": { one: "lookup"' in sett and '"bot.web.sessions_per_day": { one: "visit"' in sett)
check("on the Models page", 'web: { title: "Looking things up"' in read("webui/src/lib/providers.ts"))
check("keys for Brave and Tavily in the template", "BRAVE_API_KEY=" in read("resources/example.env")
      and "TAVILY_API_KEY=" in read("resources/example.env"))
srv = read("app/web/server.py")
check("its routes, and the free-time clock with the app", "app.include_router(web_routes.router)" in srv
      and "asyncio.create_task(freetime.loop(app.state.supervisor))" in srv)
persona_page = read("webui/src/pages/Persona.svelte")
check("the Persona page has its card", '{ id: "web", title: "Online lately"' in persona_page and "<WebJournal />" in persona_page)
card = read("webui/src/lib/personas/WebJournal.svelte")
check("Browse now, the page live as it browses, and forgetting one", "api.webBrowseNow(persona)" in card
      and 'alt="The page it is on"' in card and "api.webForget(persona, e.ts)" in card)
check("sounds on every control", all(f'play("{n}")' in card for n in ("open", "tap", "delete", "done")))

js = read("app/platforms/snapchat/webbrowser.js")
check("the browser refuses private addresses before it loads them", "if (!(await allowedPage(url))) throw" in js
      and "a === 127" in js and "(a === 192 && b === 168)" in js)
check("every request checked, redirects included", "page.on(\"request\"" in js and "req.isNavigationRequest()" in js)
check("no downloads, no pop-ups, no dialogs", 'behavior: "deny"' in js and "target.opener()" in js and "d.dismiss()" in js)
check("its own profile, never an account's", "LLMSELFBOT_WEB_PROFILE" in js and "hidden: true" in js)
check("Google typed into like a person, captcha told apart", "box.type(String(q)" in js and "unusual traffic" in js)
check("it only ever types into a site's search box", js.count("box.type(") == 2 and js.count(".type(String") == 2
      and 'type === "password"' in js)

print()
print("== the panel's own part, in Node ==")
node = shutil.which("node")
if not node or not (WEB / "node_modules" / "svelte").is_dir():
    print("  SKIP  needs Node and webui/node_modules")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "web_logic.mjs")], cwd=WEB, capture_output=True, text=True,
                          timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("web_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
