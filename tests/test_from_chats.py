"""A persona from your own chats: the exports each social gives, and only ever the owner's side. Every export here is
made up in the test, with made-up people, and no model or account is reached."""
import asyncio
import csv
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name
TMP = Path(_tmp.name)
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"),
                                            encoding="utf-8")

from app.utils import chatexports, chatpersona  # noqa: E402

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


def zipped(name: str, files: dict) -> Path:
    path = TMP / name
    with zipfile.ZipFile(path, "w") as z:
        for k, v in files.items():
            z.writestr(k, v if isinstance(v, (str, bytes)) else json.dumps(v))
    return path


def texts(result) -> list:
    return [m["text"] for m in result["messages"]]


# ── The exports ───────────────────────────────────────────────────────────────
print("\n== Discord's data package ==")
p = zipped("package.zip", {
    "account/user.json": {"username": "sammy"},
    "messages/index.json": {"111": "Direct Message with alex#0"},
    "messages/c111/messages.json": [{"ID": 1, "Timestamp": "2024-03-01 18:02:11.123000+00:00", "Contents": "yo wsp",
                                     "Attachments": ""},
                                    {"ID": 2, "Timestamp": "2024-03-01T18:03:00+00:00", "Contents": "", "Attachments": "x"}],
    "messages/c222/messages.csv": "ID,Timestamp,Contents,Attachments\n3,2024-03-02 10:00:00+00:00,lmaooo ok,\n",
    "servers/index.json": {},
})
r = chatexports.read(p, "package.zip")[0]
check("found as Discord's, owner named", r["platform"] == "discord" and r["owner"] == "sammy")
check("its messages, the json and the csv ones, no empty ones", sorted(texts(r)) == ["lmaooo ok", "yo wsp"], texts(r))
check("named by its chat", any(m["chat"] == "Direct Message with alex#0" for m in r["messages"]))
check("dated", all(m["ts"] > 1.7e9 for m in r["messages"]))

print("\n== Instagram ==")
mangled = "cafÃ© demain ?"          # Instagram's own way of writing "café demain ?"
thread = lambda other, rows: {"participants": [{"name": "Sam Lee"}, {"name": other}], "title": other,
                              "messages": rows}
p = zipped("instagram.zip", {
    "your_instagram_activity/messages/inbox/alex_1/message_1.json": thread("Alex", [
        {"sender_name": "Sam Lee", "timestamp_ms": 1709300000000, "content": mangled},
        {"sender_name": "Alex", "timestamp_ms": 1709300100000, "content": "sure"},
        {"sender_name": "Sam Lee", "timestamp_ms": 1709300200000, "content": "Liked a message"}]),
    "your_instagram_activity/messages/inbox/jo_2/message_1.json": thread("Jo", [
        {"sender_name": "Sam Lee", "timestamp_ms": 1709400000000, "content": "ptdr non"}]),
})
r = chatexports.read(p, "instagram.zip")[0]
check("the owner is the one in every thread", r["owner"] == "Sam Lee", r["owner"])
check("only the owner's, its encoding mended, its own noise out", sorted(texts(r)) == ["café demain ?", "ptdr non"], texts(r))
one = TMP / "message_1.json"
one.write_text(json.dumps(thread("Alex", [{"sender_name": "Alex", "timestamp_ms": 1, "content": "hi"}])), encoding="utf-8")
try:
    chatexports.read(one, "message_1.json")
    check("one thread alone can't say whose is whose, so it is refused", False)
except chatexports.NotAnExport as e:
    check("one thread alone can't say whose is whose, so it is refused", "whole Instagram export" in str(e), str(e))
r = chatexports.read(one, "message_1.json", {"instagram": {"Sam Lee"}})[0]
check("unless the app knows the owner's name from its own account", r["owner"] == "Sam Lee" and texts(r) == [])

print("\n== Snapchat ==")
p = zipped("mydata.zip", {"json/chat_history.json": {"alex": [
    {"From": "sam", "Media Type": "TEXT", "Created": "2024-03-01 18:00:00 UTC", "Content": "omw", "IsSender": True},
    {"From": "alex", "Media Type": "TEXT", "Created": "2024-03-01 18:01:00 UTC", "Content": "ok", "IsSender": False},
    {"From": "sam", "Media Type": "MEDIA", "Created": "2024-03-01 18:02:00 UTC", "Content": "", "IsSender": True}]}})
r = chatexports.read(p, "mydata.zip")[0]
check("what it marks as sent by the owner, words only", r["platform"] == "snapchat" and texts(r) == ["omw"], texts(r))
old = TMP / "chat_history.json"
old.write_text(json.dumps({"Sent Saved Chat History": [{"To": "alex", "Created": "2023-01-01 10:00:00 UTC", "Text": "brb"}],
                           "Received Saved Chat History": [{"From": "alex", "Text": "ok"}]}), encoding="utf-8")
check("the older shape too", texts(chatexports.read(old, "chat_history.json")[0]) == ["brb"])

print("\n== TikTok ==")
tt = {"Profile": {"Profile Information": {"ProfileMap": {"userName": "sam.tt"}}},
      "Following List": {"Following": [{"UserName": "someone_else"}]},
      "Direct Messages": {"Chat History": {"ChatHistory": {"Chat History with alex:": [
          {"Date": "2024-03-01 18:00:00", "From": "sam.tt", "Content": "this is so me"},
          {"Date": "2024-03-01 18:01:00", "From": "alex", "Content": "lol"}]}}}}
r = chatexports.read(zipped("tiktok.zip", {"user_data_tiktok.json": tt}), "tiktok.zip")[0]
check("the profile's username is the owner, not someone it follows", r["owner"] == "sam.tt" and texts(r) == ["this is so me"],
      str(r["owner"]))

print("\n== X ==")
p = zipped("twitter.zip", {
    "data/account.js": 'window.YTD.account.part0 = [{"account": {"accountId": "42", "username": "sam_x"}}]',
    "data/direct-messages.js": 'window.YTD.direct_messages.part0 = ' + json.dumps([{"dmConversation": {
        "conversationId": "42-7", "messages": [
            {"messageCreate": {"senderId": "42", "text": "deal https://t.co/abc", "createdAt": "2024-03-01T18:00:00.000Z"}},
            {"messageCreate": {"senderId": "7", "text": "ok", "createdAt": "2024-03-01T18:01:00.000Z"}}]}}]),
})
r = chatexports.read(p, "twitter.zip")[0]
check("the account's own id, its t.co tail taken off", r["owner"] == "sam_x" and texts(r) == ["deal"], texts(r))
dm = TMP / "direct-messages.js"
dm.write_text("window.YTD.direct_messages.part0 = []", encoding="utf-8")
try:
    chatexports.read(dm, "direct-messages.js")
    check("its messages alone are refused: the account is in another file", False)
except chatexports.NotAnExport as e:
    check("its messages alone are refused: the account is in another file", "whole X archive" in str(e))

print("\n== Reddit ==")
msgs = io.StringIO()
w = csv.writer(msgs)
w.writerow(["id", "permalink", "thread_id", "date", "ip", "from", "to", "subject", "body"])
w.writerow(["1", "", "", "2024-03-01 18:00:00 UTC", "", "sam_r", "alex_r", "hey", "you coming tonight?"])
w.writerow(["2", "", "", "2024-03-01 18:05:00 UTC", "", "alex_r", "sam_r", "re: hey", "yeah"])
w.writerow(["3", "", "", "2024-03-02 18:00:00 UTC", "", "jo_r", "sam_r", "hi", "hi"])
com = "id,permalink,date,ip,subreddit,gildings,link,parent,body,media\n1,,2024-03-03 12:00:00 UTC,,gaming,0,,,this game is peak,\n"
r = chatexports.read(zipped("reddit.zip", {"messages.csv": msgs.getvalue(), "comments.csv": com}), "reddit.zip")[0]
check("the name in every message is the owner's; its comments count too",
      r["owner"] == "sam_r" and sorted(texts(r)) == ["this game is peak", "you coming tonight?"], f"{r['owner']} {texts(r)}")

print("\n== Telegram Desktop ==")
tg = {"personal_information": {"user_id": 99, "first_name": "Sam"},
      "chats": {"list": [{"name": "Alex", "type": "personal_chat", "id": 5, "messages": [
          {"type": "message", "date_unixtime": "1709316000", "from": "Sam", "from_id": "user99",
           "text": ["check ", {"type": "bold", "text": "this"}]},
          {"type": "message", "date_unixtime": "1709316100", "from": "Alex", "from_id": "user5", "text": "nice"},
          {"type": "service", "date_unixtime": "1709316200", "from_id": "user99", "text": "joined"}]}]}}
r = chatexports.read(zipped("tg.zip", {"DataExport/result.json": tg}), "tg.zip")[0]
check("its user id is the owner, its formatted words joined", texts(r) == ["check this"], texts(r))
single = TMP / "result.json"
single.write_text(json.dumps(tg["chats"]["list"][0]), encoding="utf-8")
try:
    chatexports.read(single, "result.json")
    check("one chat exported on its own is refused", False)
except chatexports.NotAnExport:
    check("one chat exported on its own is refused", True)
check("unless the app knows its account's id", texts(chatexports.read(single, "result.json", {"telegram": {"99"}})[0]) == ["check this"])

print("\n== WhatsApp ==")
android = ("31/12/2023, 21:41 - Messages and calls are end-to-end encrypted.\n"
           "31/12/2023, 21:41 - Sam: happy new year!!\n"
           "31/12/2023, 21:42 - Alex: you too\nand more\n"
           "31/12/2023, 21:43 - Sam: <Media omitted>\n")
ios = ("‎[01/01/2024, 10:00:05] Jo: wsg\n"
       "[01/01/2024, 10:01:00] Sam: nm u\n")
a = chatexports.read(TMP.joinpath("a.txt") if TMP.joinpath("a.txt").write_text(android, encoding="utf-8") else None,
                     "WhatsApp Chat with Alex.txt")[0]
check("a chat says who wrote what, not whose it is", a["owner"] == "" and set(a["senders"]) == {"Sam", "Alex"}, str(a["senders"]))
check("a message on several lines is one, what was left out is left out",
      [m["text"] for m in a["senders"]["Alex"]] == ["you too\nand more"] and [m["text"] for m in a["senders"]["Sam"]] == ["happy new year!!"])
b = chatexports.read(TMP.joinpath("b.txt") if TMP.joinpath("b.txt").write_text(ios, encoding="utf-8") else None,
                     "WhatsApp Chat - Jo.txt")[0]
check("the iPhone's way of writing it too", set(b["senders"]) == {"Jo", "Sam"})
check("the owner is the one name in every chat", chatexports.whatsapp_owner([a, b], set()) == "Sam")
check("one chat alone can't tell", chatexports.whatsapp_owner([a], set()) == "")
check("unless the app's own WhatsApp account says its name", chatexports.whatsapp_owner([a], {"Sam"}) == "Sam")
us = chatexports.whatsapp("12/31/23, 9:41 PM - Sam: late\n1/2/24, 9:00 AM - Sam: early\n", "x")
stamps = [time.localtime(m["ts"]) for m in us["senders"]["Sam"]]
check("month first and a 12-hour clock, when that is what it is",
      (stamps[0].tm_mon, stamps[0].tm_mday, stamps[0].tm_hour) == (12, 31, 21) and stamps[1].tm_hour == 9, str(stamps[0]))

print("\n== anything else ==")
junk = TMP / "notes.zip"
with zipfile.ZipFile(junk, "w") as z:
    z.writestr("readme.md", "hello")
for path, name in ((junk, "notes.zip"),):
    try:
        chatexports.read(path, name)
        check("a zip that is no export is refused, saying what it reads", False)
    except chatexports.NotAnExport as e:
        check("a zip that is no export is refused, saying what it reads", "Discord, Instagram" in str(e))

# ── Measuring, sampling, writing ──────────────────────────────────────────────
print("\n== how they text, counted ==")
base = time.time() - 10_000
msgs = []
for i in range(80):
    chat = f"c{i % 4}"
    msgs.append({"ts": base + i * 30, "text": ["lmaooo", "nah fr 😭", "ok bet", "wait what", "hahaha no 💀"][i % 5],
                 "chat": chat, "source": "acct-discord_1"})
msgs.append({"ts": base, "text": "https://example.com", "chat": "c0", "source": "x"})
cleaned = chatpersona.clean(msgs)
check("a link on its own says nothing about how they text", len(cleaned) == 80)
stats = chatpersona.measure(cleaned)
check("lengths, lowercase, emoji and laughs counted", stats["median_length"] <= 12 and stats["lowercase"] == 1.0
      and "😭" in stats["top_emoji"] and "lmaoo" in " ".join(stats["laughs"]), str(stats))
picked = chatpersona.sample(cleaned, 3)
check("samples come from every chat in turn, not one", len({m["chat"] for m in picked}) == 3, str(picked))
check("and never the same line twice", len({m["text"] for m in chatpersona.sample(cleaned, 50)}) == len(chatpersona.sample(cleaned, 50)))
settings = chatpersona.settings_for(stats, "Sam")
check("short texts make for short messages, its emojis for its reactions",
      settings["bot.message_style.mode"] == "short" and settings["bot.reactions.emojis"][:2] == ["😭", "💀"]
      and settings["bot.trigger"] == "Sam", str(settings))

print("\n== the persona, written ==")
FAKE = """[NAME]
Sam

[IDENTITY]
Your name is Sam and you are 19 years old, a guy.
You live in Lyon, France.
Your hobbies and interests: football, rap, Valorant.
Call me on +33 6 12 34 56 78 or sam@example.com

[STYLE]
- You write in lowercase, short, one thought a message.
- You laugh with "lmaooo" and "hahaha", never "lol".
- You use 😭 and 💀, rarely anything else.
- You say "fr", "bet" and "nah".
- Between 2019 - 2021 you played a lot.

[EXAMPLES]
- nah fr 😭
- ok bet
"""
parsed = chatpersona.parse_final(FAKE)
check("its name, its identity lines, its rules, its examples",
      parsed["name"] == "Sam" and len(parsed["style"]) == 5 and parsed["examples"] == ["nah fr 😭", "ok bet"]
      and "Your name is" in parsed["identity"], str(parsed))
text = chatpersona.assemble(parsed["identity"], parsed["style"], parsed["name"])
check("the template's identity filled in, what it did not say left for it to fill",
      "You live in Lyon, France." in text and "Your job / studies: [JOB OR SCHOOL]." in text)
check("how they text in place of the template's general style", "learned from your own messages" in text
      and '"lmaooo"' in text and "Mostly lowercase. You can capitalise" not in text)
check("the rules about not sounding like an assistant kept", "not a helpful assistant" in text and "em dashes" in text)
check("the rest of the template kept", "# ── HARD RULES" in text and "# ── MEMORY" in text)
check("no phone number or email gets in, a span of years does", "+33" not in text and "@example.com" not in text
      and "2019 - 2021" in "\n".join(parsed["style"]), text[:200])
renamed = chatpersona.assemble(parsed["identity"], parsed["style"], "Sammy")
check("given another name, it says that one", "Your name is Sammy and you are 19 years old" in renamed)


# A model that answers as the real one would, and is asked nothing it should not be.
asked = []


async def fake_condense(prompt, instructions, max_tokens=1100):
    asked.append((prompt, instructions))
    return FAKE if instructions == chatpersona.FINAL else "HOW THEY TEXT: short, lowercase.\nABOUT THEM: 19, Lyon."


from app.utils import ai  # noqa: E402

ai.condense = fake_condense
ai._initialised = True
job = chatpersona.job()
chatpersona._write_jsonl(job["dir"] / "file-1.jsonl", [m for m in cleaned])
asyncio.run(chatpersona.write())
st = chatpersona.status()
check("written, its numbers and its settings with it", st["write"]["state"] == "done" and st["result"]["name"] == "Sam"
      and st["result"]["count"] == 80, str(st["write"]))
check("the model was only ever given their own words", all("theirs" not in p and "c0" not in p for p, _ in asked))
check("the measured numbers went with the notes", "typical message is" in asked[-1][0])

few = chatpersona.job()
chatpersona.reset()
chatpersona._write_jsonl(chatpersona.job()["dir"] / "file-1.jsonl", cleaned[:5])
asyncio.run(chatpersona.write())
check("too few messages is said, not written", chatpersona.status()["write"]["state"] == "failed"
      and "too few" in chatpersona.status()["write"]["why"])
chatpersona.reset()
chatpersona.add_export(zipped("tg2.zip", {"result.json": tg}), "tg2.zip")
check("with no name in the messages, the one the export gives its owner", chatpersona.name_hint() == "Sam",
      chatpersona.name_hint())
chatpersona.reset()

# ── The routes ────────────────────────────────────────────────────────────────
print("\n== the routes ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import fromchats_routes  # noqa: E402

chatpersona.reset()
app = FastAPI()
app.include_router(fromchats_routes.router)
# Opened as a context, so its loop keeps running between requests: the persona is written by a task the route starts.
client = TestClient(app).__enter__()
H = {"x-llmselfbot": "1"}

check("nothing for a page that is not the panel", client.get("/api/from-chats/status").status_code == 403
      and client.post("/api/from-chats/write").status_code == 403)
for route, method in (("sources", "get"), ("gather", "post"), ("download", "post")):
    check(f"the accounts are not read, and {route} is gone", getattr(client, method)(f"/api/from-chats/{route}", headers=H).status_code in (404, 405))

r = client.post("/api/from-chats/upload?name=package.zip", headers=H,
                content=(TMP / "package.zip").read_bytes()).json()
check("an export dropped in is read for its owner's messages", r["added"][0]["count"] == 2 and r["added"][0]["platform"] == "discord")
check("and the file itself goes", not list(chatpersona.job()["dir"].glob("*.part")))
r = client.post("/api/from-chats/upload?name=notes.zip", headers=H, content=junk.read_bytes()).json()
check("one that is no export is set aside, saying why", r["added"][0]["why"] and not r["added"][0]["count"])
check("a file that is no export at all by its name is refused before a byte",
      client.post("/api/from-chats/upload?name=evil.exe", headers=H, content=b"MZ").status_code == 400)
key = r["added"][0]["key"]
r = client.post("/api/from-chats/remove", headers=H, json={"key": key}).json()
check("and taken out again", all(f["key"] != key for f in r["files"]))

for chat_txt, fname in ((android, "WhatsApp Chat with Alex.txt"),):
    r = client.post(f"/api/from-chats/upload?name={fname}", headers=H, content=chat_txt.encode()).json()
check("one WhatsApp chat waits for another to tell which is you", "one more WhatsApp chat" in r["added"][0]["why"])
r = client.post("/api/from-chats/upload?name=WhatsApp Chat - Jo.txt", headers=H, content=ios.encode()).json()
wa = [f for f in r["files"] if f["platform"] == "whatsapp"]
check("with a second, both are read as yours", all(f["count"] >= 1 and not f["why"] for f in wa), str(wa))

r = client.get("/api/from-chats/status", headers=H).json()
check("what the exports gave, counted", r["total"] >= 3 and "accounts" not in r and "reading" not in r, str(sorted(r)))
folder = chatpersona.job()["dir"]
# Enough of them to go on: more exports' worth than the ones above.
chatpersona._write_jsonl(folder / "file-98.jsonl", cleaned[:40])

ai.condense = fake_condense
fromchats_routes.chatpersona.job()["write"]["state"] = ""
client.post("/api/from-chats/write", headers=H)
for _ in range(50):
    st = client.get("/api/from-chats/status", headers=H).json()
    if st["write"]["state"] in ("done", "failed"):
        break
    time.sleep(0.05)
check("written from the routes", st["write"]["state"] in ("done", "failed"), str(st["write"]))
if st["write"]["state"] == "done":
    r = client.post("/api/from-chats/create", headers=H, json={"name": "Sam", "color": "#7c8cff", "color2": "#f472b6"}).json()
    from app.utils import personas  # noqa: E402
    pid = r["persona"]["id"]
    check("made: a new persona with its text and its settings", personas.exists(pid)
          and "learned from your own messages" in personas.read_text(pid)
          and personas.overrides(pid).get("bot.trigger") == "Sam"
          and personas.overrides(pid).get("bot.message_style.mode") in ("short", "balanced", "chatty"))
    check("in the colours picked on the card", personas.get(pid).get("color2") == "#f472b6", str(personas.get(pid)))
    check("and the job's folder gone with what it gathered", not folder.exists())
else:
    check("made from the routes", False, st["write"]["why"])
import re  # noqa: E402

PERSON = re.compile(r"\b(user_id|uid|person|contact)\b")
check("no route takes a person to copy", not PERSON.search(read("app/web/routes/fromchats_routes.py")))

budgets = []


async def stingy(prompt, instructions, max_tokens=1100):
    budgets.append(max_tokens)
    return "" if len(budgets) == 1 else "notes"


ai.condense = stingy
check("a model that thought its whole budget away is asked again with twice the room",
      asyncio.run(chatpersona._ask("p", "i", 3000)) == "notes" and budgets == [3000, 6000], str(budgets))

print("\n== the accounts are not read at all ==")
for rel, gone in (("app/platforms/discord_runner.py", "own_messages"), ("app/platforms/snapchat_bridge.py", "own_messages"),
                  ("app/platforms/snapchat/imessage_runner.js", "own_messages"), ("app/platforms/snapchat/bluebubbles.js", "ownMessages"),
                  ("app/utils/db.py", "def first_answer"), ("app/utils/chatlog.py", "def own_before"),
                  ("app/utils/chatpersona.py", "def account_sources"), ("app/utils/chatpersona.py", "def gather"),
                  ("app/utils/chatpersona.py", "def dump_zip")):
    check(f"no {gone} in {rel.split('/')[-1]}", gone not in read(rel))

print("\n== how to get each export ==")
guides = read("webui/src/lib/personas/exports.ts")
ids = re.findall(r'^    id: "(\w+)",$', guides, re.M)
check("each social it can read has a guide, in the order of the tabs",
      ids == ["discord", "telegram", "whatsapp", "snapchat", "instagram", "tiktok", "x", "reddit"], str(ids))
sources = read("app/utils/chatexports.py")
check("and each is one it can read", all(f'"{i}"' in sources for i in ids), str([i for i in ids if f'"{i}"' not in sources]))
check("none for what has no export, or is not texting", '"imessage"' not in guides and '"minecraft"' not in guides)
bits = guides.split('    id: "')[1:]
check("each with how long it takes, steps to follow, and the way there", all("wait:" in b and "steps: [" in b and 'link: { url: "https://' in b for b in bits))
check("short steps, as the panel's words are", all(len(s) <= 90 for s in re.findall(r'^      "(.+)",$', guides, re.M)),
      str([s for s in re.findall(r'^      "(.+)",$', guides, re.M) if len(s) > 90]))
check("Discord's as its own dialog has it: tick Messages, wait up to 30 days", "Tick only Messages, then Request My Data." in guides and 'wait: "Up to 30 days"' in guides)
check("what would surprise someone is said before they start", "Only messages you or they saved are in it." in guides
      and "It takes two or more to tell which messages are yours." in guides)
check("as many messages as the writing needs", f"ENOUGH = {chatpersona.MIN_MESSAGES};" in guides)

print("\n== the panel ==")
page = read("webui/src/lib/personas/FromExports.svelte")
card = read("webui/src/lib/personas/NewPersona.svelte")
persona = read("webui/src/pages/Persona.svelte")
profiles = read("webui/src/pages/Profiles.svelte")
check("in the new profile card, not a window over a dimmed page", "<FromExports bind:name" in card and "Modal" not in page and "Modal" not in card)
check("from the Profiles page", "oncreated={madeFromChats}" in profiles and "<FromChats" not in profiles)
check("and the Persona page's button grows the same card where it stands", '<NewPersona bind:open={fromChats} only="chats"' in persona
      and "chatsFrom = (e.currentTarget as HTMLElement).getBoundingClientRect()" in persona and "FromChats" not in persona)
check("each social with its logo", "<PlatformMark platform={g.id} size={26} />" in page)
check("a social switched off is not on it", "platformOn($socialsOn, g.id)" in page)
check("pressed, how to get its export", "{#each opened.steps as step, i (i)}" in page and "opened.link.url" in page)
check("its panel opens and closes: the slide on what the {#if} holds, as inside a {#key} it never plays",
      'class="fx-guide" transition:slide=' in page
      and "{#key" not in page.split("{#if opened}", 1)[1].split('class="fx-guide"', 1)[0])
check("from one social to another it glides to the new height, and the new steps fade in",
      "use:smoothHeight=" in page and "{#key opened.id}" in page and "in:fade=" in page)
check("and nothing jumps as it starts or ends: its margin folds with it, not the card's gap", ".fx-guide { margin-top: 6px;" in page)
check("its tile says what its exports gave", "of yours" in page and "counts[g.id]" in page)
check("the name, the colours and the picture are the card's", "bind:name" in card and "color2={second}" in card and "oncreated?.(p, face)" in card
      and "api.fromChatsCreate(name.trim(), color, color2)" in page and "uploadPersonaAvatar(made.id, face)" in profiles)
check("not written with too little to go on", "disabled={total < ENOUGH}" in page)
check("says it learns from you, never the people you talk to", "never from the people you talk to" in page)
check("no control anywhere to pick someone else", not PERSON.search(page))
check("says where the samples go", "Samples of your messages go to" in page and "nothing leaves it" in page)
check("every arrival heard", 'play("lift")' in page and 'play("drop")' in page and 'play("rise")' in page and 'play("done")' in page and 'play(guide ? "open" : "tick")' in page)

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
