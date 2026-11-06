"""WhatsApp, the tenth platform and the first that needs no browser at all (2026-11-01).

The persona gets a WhatsApp number of its own: its chats answered, the groups it was named in, the statuses of
the people it talks to, and the calls it cannot take declined. It is not scraped and it is not an API either -
baileys speaks WhatsApp's own multi-device protocol over a WebSocket, the same one a linked phone or desktop
speaks, so there are no selectors and no Chrome.

That is what makes this file different from test_reddit.py and test_x.py. Those can only check the wiring,
because whether a selector is right is a question about a page. Here the thing that matters is a message object,
so the last two sections run the real loop: the real event handlers, the real burst coalescing, the real governor,
against a stand-in socket that plays canned WhatsApp events (tests/fixtures/whatsapp_events.json) and writes down
everything it was asked to do. A message arrives, is handed to the bridge, an answer comes back, it is sent - and
nothing reaches WhatsApp.

What waits for a number: whether WhatsApp accepts the link, and whether the account survives. Nothing here needs
one, and nothing here sends anything anywhere.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRC = ROOT / "webui" / "src"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def leaves(d, prefix=""):
    """Every setting in a config block, as dotted keys."""
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            yield from leaves(v, key + ".")
        else:
            yield key, v


import yaml  # noqa: E402

CONFIG = yaml.safe_load(read("resources/config.yaml"))

print("== it is one of the socials ==")
from app.utils import socials  # noqa: E402

check("WhatsApp is in the list", "whatsapp" in socials.SOCIALS)
check("on until it is switched off", socials.on({})["whatsapp"] is True)
check("off by either of its two switches",
      socials.on({"whatsapp": {"enabled": False}})["whatsapp"] is False
      and socials.on({"services": {"whatsapp": {"enabled": False}}})["whatsapp"] is False)
check("the shipped config has both, on", (CONFIG["services"].get("whatsapp") or {}).get("enabled") is True
      and CONFIG["whatsapp"]["enabled"] is True)

print("\n== its name tells nothing else apart ==")
from app.core import ipc  # noqa: E402

check("its targets are wa and a number", ipc.platform_of("wa") == "whatsapp"
      and ipc.platform_of("wa2") == "whatsapp"
      and ipc.whatsapp_index("wa") == 1 and ipc.whatsapp_index("wa7") == 7)
check("and no other platform's target is read as WhatsApp",
      [ipc.platform_of(t) for t in ("snap", "tiktok2", "insta", "x", "reddit", "mc", "imsg", "tg3", 1)]
      == ["snapchat", "tiktok", "instagram", "x", "reddit", "minecraft", "imessage", "telegram", "discord"])
check("it is bridged, and it is not a browser platform",
      ipc.is_bridged("wa") and not ipc.is_browser("wa"))
check("its web id goes both ways", ipc.web_id_for("wa3") == "whatsapp_3"
      and ipc.platform_of(ipc.browser_target("whatsapp", 3)) == "whatsapp")
check("its files are the wa_ ones", ipc._PREFIX["whatsapp"] == "wa"
      and "wa2" in ipc.cmd_file("wa2").name and "wa2" not in ipc.cmd_file("wa").name,
      ipc.cmd_file("wa2").name)

print("\n== the bridge knows what kind of thing it is ==")
os.environ.setdefault("BRIDGE_PLATFORM", "whatsapp")
from app.platforms import snapchat_bridge as bridge  # noqa: E402

src = read("app/platforms/snapchat_bridge.py")
row = bridge._PLATFORMS["whatsapp"]
check("it is in the registry, with its own files and settings",
      row["name"] == "WhatsApp" and row["key"] == "wa" and row["env"] == "WHATSAPP"
      and row["runner"] == "whatsapp_runner.js")
check("WhatsApp's own number is not somebody to talk to", "whatsapp" in row["system_chats"])
check("it can be sent any emoji, not only the six in the picker",
      row.get("any_reaction") is True and len(row["reactions"]) == 6)
check("and a call it cannot take is something it knows about", row.get("calls") is True)
check("it has no out tab of posts and likes: its status is its own thing, as Minecraft's game is",
      'WHATSAPP = PLATFORM == "whatsapp"' in src and "SOCIAL = PLATFORM in" in src
      and "whatsapp" not in src.split("SOCIAL = PLATFORM in")[1].split("\n")[0])
check("it lands in the branch iMessage lands in, so it inherits the whole of a texting platform",
      'elif PLATFORM in ("imessage", "whatsapp"):' in src or "NO_BROWSER" in src)

print("\n== no browser, but it does have a dependency ==")
check("the Chrome checks are skipped for both platforms that need no browser",
      "NO_BROWSER = IMESSAGE or WHATSAPP" in src)
chrome = [line.strip() for line in src.splitlines() if "if not NO_BROWSER" in line]
check("by the one flag, not three copies of the same if", len(chrome) >= 2, str(chrome))
check("but the node_modules check stays live, because baileys has to be there",
      "if not IMESSAGE" in src.split("node_modules")[0][-400:]
      or "node_modules" in src.split("NO_BROWSER")[0][-4000:], "")
pkg = json.loads(read("app/platforms/snapchat/package.json"))
check("baileys is pinned exactly, since 7.x is a release candidate that moves",
      pkg["dependencies"]["baileys"] == "7.0.0-rc14", pkg["dependencies"].get("baileys", "missing"))
check("and its optional helper is the pure-JS one, because sharp would need a compiler",
      "jimp" in pkg["dependencies"] and "sharp" not in json.dumps(pkg))

print("\n== every setting reaches the runner ==")
env = bridge._whatsapp_env(CONFIG)
keys = [k for k, _ in leaves({"whatsapp": CONFIG["whatsapp"]})]
check("there are settings to hand over", len(keys) >= 26, str(len(keys)))
deaf = []
for key, value in leaves({"whatsapp": CONFIG["whatsapp"]}):
    if key == "whatsapp.enabled":
        continue                         # the supervisor's, never the runner's
    other = copy.deepcopy(CONFIG)
    node = other
    for part in key.split(".")[:-1]:
        node = node[part]
    node[key.rsplit(".", 1)[1]] = (not value) if isinstance(value, bool) else (
        value + 7 if isinstance(value, int) else "99-23")
    if bridge._whatsapp_env(other) == env:
        deaf.append(key)
check("and changing any one of them changes what the runner is told", not deaf, ", ".join(deaf))
check("what is already in the environment wins, since that is where its number is",
      "if k not in os.environ" in src.split("def _whatsapp_env")[1][:4800])
check("everything that reaches somebody who did not write first is off to begin with",
      CONFIG["whatsapp"]["accept_unknown"] is False and CONFIG["whatsapp"]["status"]["post"] is False
      and CONFIG["whatsapp"]["presence"]["online"] is False
      and CONFIG["whatsapp"]["presence"]["read_receipts"] is False)
check("it only speaks in a group when it is named", CONFIG["whatsapp"]["groups"]["only_when_named"] is True)
check("and it declines a call rather than letting it ring out", CONFIG["whatsapp"]["calls"]["decline"] is True)

print("\n== every setting has words on it ==")
from app.web import descriptions, schema  # noqa: E402

in_schema = {r["key"] for r in schema.CONFIG_SCHEMA}
no_words = [k for k in keys if k not in descriptions.DESCRIPTIONS
            or (k not in descriptions.LABELS and k not in in_schema)]
check("a description and a label for each", not no_words, ", ".join(no_words))
wrong_tab = [k for k in keys if descriptions.section_for(k) != "WhatsApp"]
check("and all of them under one tab", not wrong_tab, ", ".join(wrong_tab))
stale = [k for k in list(descriptions.DESCRIPTIONS) + list(descriptions.LABELS)
         if k.startswith("whatsapp.") and k not in keys]
check("and nothing described that is not there any more", not stale, ", ".join(sorted(set(stale))))
check("the ones handed over at launch say they need a restart",
      descriptions.needs_restart("whatsapp.poll_interval_ms") and descriptions.needs_restart("whatsapp.groups.enabled")
      and descriptions.needs_restart("whatsapp.calls.decline"))
check("both switches are rows people see first",
      "whatsapp.enabled" in descriptions.COMMON and "services.whatsapp.enabled" in descriptions.COMMON)

print("\n== the panel has a place for all of it ==")
smap = read("webui/src/lib/settingsmap.ts")
homeless = [k for k in keys if f'"{k}"' not in smap]
check("every setting is in the Settings tab", not homeless, ", ".join(homeless))
check("it has a tab of its own, with the install panel in it",
      '    id: "whatsapp",' in smap and '"whatsapp-setup"' in smap)
check("the card calls it linked once it has a number", 'if (s.platform === "whatsapp") return !!s.username;'
      in read("webui/src/lib/accounts/condition.ts"))
check("and says what to do when it has not been", "It has not been linked to a phone yet."
      in read("webui/src/lib/accounts/condition.ts"))

print("\n== its login is a folder of keys its phone made ==")
from app.platforms.whatsapp import link  # noqa: E402

check("a number is digits, however it was typed",
      link.clean_number(" +44 7700 900123 ") == "447700900123" and link.clean_number("+1 (555) 0100") == "15550100")
check("and nothing that is not one", link.clean_number("abc") == "" and link.clean_number("12") == ""
      and link.clean_number("9" * 30) == "")
check("the keys land beside the other logins, named after the number",
      link.auth_dir("+44 7700 900123").name == "whatsapp-447700900123-auth")
check("a link that nobody finishes is given up on", link.GIVE_UP_AFTER >= 120 and link.GIVE_UP_AFTER <= 900,
      str(link.GIVE_UP_AFTER))
check("nothing is in flight to begin with", link.status()["state"] == "idle")
check("and a finished link is handed over once", link.take_login() is None)
fields = read("app/web/routes/account_routes.py").split('"whatsapp": {')[1].split("},")[0]
check("the account itself keeps one field, and it is not a secret",
      "WHATSAPP_NUMBER" in fields and "password" not in fields and "write_only" not in fields,
      fields.strip()[:160])

print("\n== it is a role, a child and a set of tables ==")
check("it can be run on its own", '"whatsapp"' in read("app/cli.py") and "_run_whatsapp_role" in read("app/cli.py"))
sup = read("app/web/supervisor.py")
from app.platforms import registry  # noqa: E402
check("the supervisor starts one child per linked number",
      '"whatsapp": _count_whatsapp_accounts' in sup and 'out[f"{p.id}_{i}"] = (p.id, i, f"{p.name} #{i}")' in sup)
check("and not on a phone, which cannot run a Node runner",
      not registry.BY_ID["whatsapp"].on_phone and "(device.is_phone() and not p.on_phone)" in sup)
db = read("app/utils/db.py")
check("it has its own ignore list, stats and message log",
      all(f"{t}_whatsapp" in db for t in ("ignored_users", "user_stats", "message_log")))
check("its chat log has a band of its own, after Reddit's",
      registry.BY_ID["whatsapp"].log_base == 9000 > registry.BY_ID["reddit"].log_base
      and registry.TARGETS["whatsapp"] == "wa" and "WHATSAPP_BASE = 9000" in read("app/utils/chatlog.py"))
people = read("app/utils/snappeople.py")
check("a person is wa_ and their number, a group wag_",
      registry.HANDLED["whatsapp"] == "wa_" and "def whatsapp_id" in people and "def whatsapp_number" in people)

print("\n== the runner gives up where a person has to do something ==")
node = shutil.which("node")
RUNNER = ROOT / "app" / "platforms" / "snapchat" / "whatsapp_runner.js"
runner_dir = str(RUNNER.parent)
if not node:
    print("  SKIP  needs Node")
else:
    def run_runner(extra, timeout=120):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WHATSAPP_")}
        env.update({"WHATSAPP_DATA_DIR": tmp_dir, "SNAP_DATA_DIR": tmp_dir, "WHATSAPP_ACCOUNT_INDEX": "1",
                    **extra})
        p = subprocess.run([node, str(RUNNER)], env=env, cwd=runner_dir, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, p.stdout + p.stderr

    with tempfile.TemporaryDirectory() as tmp_dir:
        code, said = run_runner({})
        check("with no number at all it says so and stops", code == 1
              and "add one on the accounts page" in said.lower(), f"exit {code}: {said[-200:]}")
    with tempfile.TemporaryDirectory() as tmp_dir:
        code, said = run_runner({"WHATSAPP_NUMBER_1": "447700900123"})
        state = {}
        f = Path(tmp_dir) / "ipc" / "wa_state.json"
        if f.exists():
            state = json.loads(f.read_text(encoding="utf-8"))
        check("with no keys from a phone it asks for a person, and exits 4 rather than trying", code == 4,
              f"exit {code}: {said[-200:]}")
        check("and the card says what to do", state.get("state") == "needs-you"
              and "linked" in (state.get("detail") or ""), str(state))
        made = sorted(p.name for p in (Path(tmp_dir) / "ipc").glob("wa_*"))
        check("with all its files made, so the bridge finds them",
              {"wa_incoming.json", "wa_responses.json", "wa_outgoing.json", "wa_state.json"} <= set(made),
              str(made))

print("\n== the panel's own view of it ==")
from app.web.routes import whatsapp_routes  # noqa: E402

paths = {r.path for r in whatsapp_routes.router.routes}
check("the connection, its groups, the statuses it has seen, and what is left of the day",
      {"/api/whatsapp/state", "/api/whatsapp/groups", "/api/whatsapp/statuses",
       "/api/whatsapp/posting"} <= paths, str(sorted(paths)))
check("putting one up, and leaving a group",
      {"/api/whatsapp/status", "/api/whatsapp/group/leave"} <= paths)
server = read("app/web/server.py")
check("and they are served", "whatsapp_routes" in server
      and "app.include_router(whatsapp_routes.router)" in server)
check("a status says how long it lasts and how far it goes, since neither is obvious",
      "for a day" in read("webui/src/lib/components/PostTo.svelte"))
pics = read("webui/src/pages/Pictures.svelte")
check("one of its pictures can go up as a status, beside the other platforms' posts",
      '"Put up as a WhatsApp status…"' in pics and "PostTo" in pics)
check("and not when WhatsApp is switched off", "$socialsOn.whatsapp !== false" in pics)
api_ts = read("webui/src/lib/api.ts")
check("the panel can ask for all of it",
      all(f"whatsapp{p}" in api_ts for p in ("Posting", "Status", "Groups", "Leave", "SeenStatuses")))
check("a status with no words and no picture is refused before it reaches WhatsApp",
      "a status needs words or a picture" in read("app/web/routes/whatsapp_routes.py"))
check("and a picture that is not one of its own is refused too",
      'DATA_DIR / "pictures" / safe' in read("app/web/routes/whatsapp_routes.py"))

print("\n== and every switch does something ==")
# The deafness sweep above proves each setting reaches the runner. This is the other half: that something reads
# it. Four of these reached the runner and were read by nothing until the behaviour was written.
runner = read("app/platforms/snapchat/whatsapp_runner.js")
for setting, line in (
    ("whatsapp.media.pictures", "if (item.image && PICTURES)"),
    ("whatsapp.media.voice_notes", "if (item.voice && VOICE_NOTES)"),
    ("whatsapp.watch.their_status", "if (!WATCH || !THEIR_STATUS) return;"),
    ("whatsapp.groups.only_when_named", "if (m.group && ONLY_WHEN_NAMED && !forUs("),
    ("whatsapp.groups.leave_on_request", "if (m.group && LEAVE_ON_REQUEST && ASKED_TO_LEAVE.test(m.text)"),
    ("whatsapp.groups.max_per_pass", "order.slice(0, Math.max(1, GROUPS_PER_PASS))"),
    ("whatsapp.groups.enabled", "if (!GROUPS_ON || !bot.live) return;"),
    ("whatsapp.presence.typing", "if (TYPING) bot.typing(m.chat, true)"),
    ("whatsapp.presence.read_receipts", "if (READ_RECEIPTS && keysOf.get(chatId))"),
    ("whatsapp.presence.online", "await bot.connect({ online: ONLINE });"),
    ("whatsapp.accept_unknown", "if (!m.group && !ACCEPT_UNKNOWN && !known(m.chat))"),
    ("whatsapp.calls.decline", "if (!DECLINE_CALLS) return;"),
    ("whatsapp.calls.say_why", "if (!CALL_SAY_WHY || !chatId) return;"),
    ("whatsapp.status.watch", "if (STATUS_WATCH && !m.mine) noteStatus(m);"),
    ("whatsapp.status.post", 'if (!STATUS_POST && !p.dry_run)'),
    ("whatsapp.status.per_day", 'statuses: core.num("STATUS_PER_DAY", 1)'),
    ("whatsapp.burst_ms", "setTimeout(() => handOver(m.chat), BURST_MS)"),
):
    check(f"  {setting}", line in runner, line)
check("  whatsapp.quiet_hours, min and max gap, sends an hour: the governor's, as every platform's are",
      'core.sendAllowed()' in runner and 'core.recordSend()' in runner)
check("a leave is narrow on purpose: said to it, by name, and in so many words",
      "remove yourself" in runner and "forUs(m, TRIGGER, bot.me)) {" in runner)
# The two that are nobody's but the panel's, and the switch the supervisor reads: everything else above is a
# line in the runner. Nothing else is left.
PANELS = {"whatsapp.enabled", "whatsapp.response_timeout_ms", "whatsapp.quiet_hours",
          "whatsapp.min_send_gap_ms", "whatsapp.max_send_gap_ms", "whatsapp.max_sends_per_hour",
          "whatsapp.poll_interval_ms", "whatsapp.watch.enabled", "whatsapp.calls.text"}
reads = {"whatsapp.media.pictures": "PICTURES", "whatsapp.media.voice_notes": "VOICE_NOTES",
         "whatsapp.watch.their_status": "THEIR_STATUS", "whatsapp.groups.only_when_named": "ONLY_WHEN_NAMED",
         "whatsapp.groups.leave_on_request": "LEAVE_ON_REQUEST", "whatsapp.groups.max_per_pass": "GROUPS_PER_PASS",
         "whatsapp.groups.enabled": "GROUPS_ON", "whatsapp.presence.typing": "TYPING",
         "whatsapp.presence.read_receipts": "READ_RECEIPTS", "whatsapp.presence.online": "ONLINE",
         "whatsapp.accept_unknown": "ACCEPT_UNKNOWN", "whatsapp.calls.decline": "DECLINE_CALLS",
         "whatsapp.calls.say_why": "CALL_SAY_WHY", "whatsapp.status.watch": "STATUS_WATCH",
         "whatsapp.status.post": "STATUS_POST", "whatsapp.status.per_day": "STATUS_PER_DAY",
         "whatsapp.burst_ms": "BURST_MS"}
unread = [k for k in keys if k not in PANELS and k not in reads]
check("and there is no switch left that nothing reads", not unread, ", ".join(unread))
check("which is why there is no sticker switch: nothing here can write a 512x512 webp",
      "STICKERS" not in runner and "whatsapp.media.stickers" not in read("app/web/schema.py"))

print("\n== the whole loop, run for real ==")
# The one thing no browser platform here can be tested on without an account: the real runner, the real event
# handlers, the real burst coalescing and the real governor, against a socket that plays canned WhatsApp events
# and writes down what it was asked to do. Nothing reaches WhatsApp.
ME, THEO, STRANGER, GROUP = "447711111111", "447700900123", "447733333333", "wag_120363045"


def waitfor(what, fn, secs=25):
    end = time.time() + secs
    while time.time() < end:
        got = fn()
        if got:
            return got
        time.sleep(0.25)
    return None


if not node:
    print("  SKIP  needs Node")
else:
    tmp_dir = tempfile.mkdtemp()
    proc = None
    try:
        ipc_dir = Path(tmp_dir) / "ipc"
        people = Path(tmp_dir) / "cache" / "whatsapp_people"
        people.mkdir(parents=True, exist_ok=True)
        # It answers a number it has talked to before, and ignores one it has not. So one of the two is known.
        (people / "contacts_1.json").write_text(json.dumps({f"wa_{THEO}": {"name": "Theo", "seen": 1}}),
                                                encoding="utf-8")
        sent_log = Path(tmp_dir) / "sent.jsonl"
        env = {k: v for k, v in os.environ.items() if not k.startswith("WHATSAPP_")}
        env.update({
            "WHATSAPP_DATA_DIR": tmp_dir, "SNAP_DATA_DIR": tmp_dir, "WHATSAPP_ACCOUNT_INDEX": "1",
            "WHATSAPP_NUMBER_1": ME,
            "WHATSAPP_FAKE": "1",
            "WHATSAPP_FAKE_EVENTS": str(ROOT / "tests" / "fixtures" / "whatsapp_events.json"),
            "WHATSAPP_FAKE_SENT": str(sent_log),
            "WHATSAPP_TRIGGER": "Alicia, Ali",
            # Paced for a test, not for a person: a short burst, a quick loop, no typing pauses, and an hour's
            # worth of sending set to one, so what the governor holds back is exactly one answer.
            "WHATSAPP_BURST_MS": "400", "WHATSAPP_POLL_INTERVAL_MS": "800", "WHATSAPP_TYPING": "0",
            "WHATSAPP_MIN_SEND_GAP_MS": "0", "WHATSAPP_MAX_SEND_GAP_MS": "0",
            "WHATSAPP_MAX_SENDS_PER_HOUR": "1", "WHATSAPP_QUIET_HOURS": "0-0",
        })
        proc = subprocess.Popen([node, str(RUNNER)], env=env, cwd=runner_dir,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")

        def handed():
            f = ipc_dir / "wa_incoming.json"
            if not f.exists():
                return None
            try:
                rows = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                return None
            return rows if len(rows) >= 3 else None

        rows = waitfor("handovers", handed) or []

        # A declined call is handed over in that person's chat too, so it is kept out of what is counted as
        # their messages.
        def amessage(r):
            return not str(r.get("id", "")).startswith("call:")

        by_chat = {}
        for r in rows:
            if amessage(r):
                by_chat.setdefault(r.get("channel_id"), []).append(r)
        chats = {c: [r["content"] for r in rs] for c, rs in by_chat.items()}

        check("what it was told arrived", len(rows) >= 3, f"{len(rows)} rows: {chats}")
        check("two lines and a voice note from one person are one thought, handed over once",
              chats.get(f"wa_{THEO}", [""])[0] == "hey\nare you around?\n[voice note]", str(chats.get(f"wa_{THEO}")))
        check("a voice note is said to be one, so it is never an empty line",
              "[voice note]" in "".join(chats.get(f"wa_{THEO}", [])))
        check("the person's name comes with it",
              any(r.get("user_name") == "Theo" for r in by_chat.get(f"wa_{THEO}", [])))
        check("a number it does not know is not answered", f"wa_{STRANGER}" not in chats, str(list(chats)))
        check("a group it was named in is answered", chats.get(GROUP, [""])[0] == "Alicia what do you think",
              str(chats.get(GROUP)))
        check("and the line in that group that was not for it is not in what was handed over",
              "anyone else getting this" not in json.dumps(chats))
        check("it is told that one came from a group, so it knows it is not one to one",
              all(r.get("group") for r in by_chat.get(GROUP, [{}])))
        check("its own message coming back is not answered", "one of its own" not in json.dumps(chats))
        check("a reaction is not a message that says an emoji", "reacted" not in json.dumps(chats))
        check("a status is not a conversation", "at the beach" not in json.dumps(chats))
        check("history arriving behind it is not answered a second time",
              len(by_chat.get(f"wa_{THEO}", [])) == 1 and len(by_chat.get(GROUP, [])) == 1,
              json.dumps({k: len(v) for k, v in by_chat.items()}))
        calls = [r for r in rows if str(r.get("id", "")).startswith("call:")]
        check("a call it could not take is something to say sorry about, in its own words",
              len(calls) == 1 and calls[0]["channel_id"] == f"wa_{THEO}"
              and "could not pick up" in calls[0]["content"], str(calls))

        # Now the bridge's half: two answers written where the runner looks for them.
        answers = {}
        for r in rows:
            if r.get("channel_id") == f"wa_{THEO}" and amessage(r):
                answers[r["id"]] = "sorry, just got in"
            elif r.get("channel_id") == GROUP:
                answers[r["id"]] = "i think it is fine"
        (ipc_dir / "wa_responses.json").write_text(json.dumps(answers), encoding="utf-8")

        def did():
            if not sent_log.exists():
                return None
            lines = [json.loads(line) for line in sent_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            return lines if any(x["did"] == "send" for x in lines) else None

        lines = waitfor("a send", did) or []
        sends = [x for x in lines if x["did"] == "send"]
        check("the answer is sent, to WhatsApp's own id for that person",
              len(sends) >= 1 and sends[0]["jid"] == f"{THEO}@s.whatsapp.net"
              and sends[0]["content"].get("text") == "sorry, just got in", json.dumps(sends[:2]))
        check("the call was declined rather than left ringing",
              any(x["did"] == "decline" and x["from"] == f"{THEO}@s.whatsapp.net" for x in lines),
              json.dumps([x for x in lines if x["did"] != "send"]))
        check("it never said it was online, because that is off", not any(
            x["did"] == "presence" and x.get("state") == "available" for x in lines))
        check("and it left no read receipts, because those are off too",
              not any(x["did"] == "read" for x in lines))
        # One an hour means one: the other answer is still sitting there, not sent and not thrown away.
        time.sleep(2)
        left = json.loads((ipc_dir / "wa_responses.json").read_text(encoding="utf-8"))
        sends = [x for x in json.loads("[" + ",".join(
            line for line in sent_log.read_text(encoding="utf-8").splitlines() if line.strip()) + "]")
            if x["did"] == "send"]
        check("an hour's worth set to one answer means one answer", len(sends) == 1, json.dumps(sends))
        check("and the one it held back is still waiting, not lost", len(left) == 1, json.dumps(left))
        state = json.loads((ipc_dir / "wa_state.json").read_text(encoding="utf-8"))
        check("the card says it is connected", state.get("state") == "ready", str(state))
        ident = json.loads((Path(tmp_dir) / "config" / "identity_whatsapp_1.json").read_text(encoding="utf-8"))
        check("and the account knows which number it is", ident.get("username") == ME, str(ident))
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp_dir, ignore_errors=True)

print("\n== the message model, read for real ==")
# Every shape WhatsApp sends a message in, run through the thing that reads them. No page and no browser: this is
# the half that is easy to get quietly wrong, and the half that can be written down exactly.
if not node:
    print("  SKIP  needs Node")
else:
    p = subprocess.run([node, str(ROOT / "tests" / "whatsapp_logic.mjs")], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
    print("\n".join("  " + line for line in p.stdout.strip().splitlines()[-3:]))
    check("whatsapp_logic.mjs passes", p.returncode == 0, (p.stdout + p.stderr)[-700:])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
