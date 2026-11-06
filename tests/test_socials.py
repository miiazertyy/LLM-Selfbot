"""A social switched off in Settings is shown nowhere, and everything is on until someone turns one off.

Each social has two switches in config.yaml (services.X.enabled and X.enabled) and is on only when both are; a switch
not written down counts as on. app/utils/socials.py says which are on, and everything reads it: the supervisor (what
runs), the routes that list accounts and count replies (what the panel is sent), and webui/src/lib/socials.ts (what
the panel lists by itself), whose logic runs for real under Node in tests/socials_logic.mjs. Switching one off stops
its accounts at once; switching it back on starts them again, as the app does when it opens.

Also here, from the same round: Settings opens on App, then Models, AI behaviour and Appearance, the socials after;
each social's switch has its mark beside it; the mood on an account card is a real dropdown; and typing a new
profile's name is no longer wiped by the page asking for the profiles again.
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WEB = ROOT / "webui"
SRC = WEB / "src"
# The config the project ships, in a sandbox: config/ is only made by running the app, so a fresh checkout (CI) has none.
from fixtures import use_shipped_config  # noqa: E402

use_shipped_config()

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


from app.utils import socials  # noqa: E402

ALL_ON = {name: True for name in socials.SOCIALS}

# ── Which are on ─────────────────────────────────────────────────────────────────────────────────────────────────
print("== which are on ==")
check("every social is on with nothing written down", socials.on({}) == ALL_ON, str(socials.on({})))
check("and with only the app's own sections", socials.on({"bot": {}, "services": {"webui": {"enabled": True}}}) == ALL_ON)
check("off by its run switch", socials.on({"services": {"snapchat": {"enabled": False}}})["snapchat"] is False)
check("off by its own section's switch", socials.on({"tiktok": {"enabled": False}})["tiktok"] is False)
check("one off leaves the rest on",
      all(v for k, v in socials.on({"tiktok": {"enabled": False}}).items() if k != "tiktok"))
check("the persona's Telegram accounts go by services.telegram_accounts",
      socials.on({"services": {"telegram_accounts": {"enabled": False}}})["telegram"] is False)
check("not by the control bot's switch, which is not a social",
      socials.on({"services": {"telegram": {"enabled": False}}})["telegram"] is True)
check("a section that is not a table counts as on", socials.on({"snapchat": None, "services": None}) == ALL_ON)
check("the switches, both of each", socials.SWITCHES == frozenset(
    [f"{n}.enabled" for n in socials.SOCIALS]
    + [f"services.{'telegram_accounts' if n == 'telegram' else n}.enabled" for n in socials.SOCIALS]))
check("the control bot's switch is not one of them", "services.telegram.enabled" not in socials.SWITCHES)
off_tg = {**ALL_ON, "telegram": False}
check("the control bot is always on screen", socials.child_shown("telegram", None, off_tg) is True)
check("a persona's Telegram account goes with Telegram", socials.child_shown("telegram", 1, off_tg) is False)
check("anything that is not a social is on screen", socials.child_shown("panel", None, off_tg) is True)
cfg_text = read("resources/config.yaml")
services_block = cfg_text[cfg_text.index("\nservices:"):cfg_text.index("\n# ── Discord Platform")]
check("the shipped config has every one on",
      all(f"  {n}:\n    enabled: true" in services_block
          for n in ("discord", "snapchat", "tiktok", "instagram", "minecraft", "imessage", "telegram_accounts")))
for n in socials.SOCIALS:
    section = re.search(rf"^{n}:\n((?:[ #].*\n|\n)*)", cfg_text, re.M)
    check(f"and its own {n} section too", bool(section) and "\n  enabled: true" in "\n" + section.group(1).split("\n\n")[0]
          or (bool(section) and section.group(1).startswith("  enabled: true")),
          section.group(1)[:80] if section else "no section")

# ── What runs ────────────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== what runs, switched on and off ==")
from app.web.supervisor import Child, Supervisor  # noqa: E402


class Proc:
    def __init__(self, alive=True):
        self.alive = alive
        self.pid = 4242

    def poll(self):
        return None if self.alive else 0


def make(children, planned, before, now, switched_off=()):
    sup = Supervisor(port=0, no_web=True)
    sup._running = True
    sup._socials_seen = dict(before)
    sup._switched_off = set(switched_off)
    calls = {"stop": [], "start": [], "restart": []}
    lock = threading.Lock()

    def stop(cid, graceful_seconds=6.0):
        with lock:
            calls["stop"].append(cid)
        child = sup.children[cid]
        child._stop_requested = True
        child.state = "stopped"
        if child.proc:
            child.proc.alive = False
        return {"ok": True}

    def start(cid):
        calls["start"].append(cid)
        return {"ok": True}

    def restart(cid):
        calls["restart"].append(cid)

    sup.stop, sup.start, sup.restart = stop, start, restart
    for cid, role, account, state, alive in children:
        c = Child(cid, role, account, cid)
        c.state = state
        c.proc = Proc(alive) if alive is not None else None
        sup.children[cid] = c
    sup._planned_children = lambda: dict(planned)
    socials_on = socials.on
    socials.on = lambda config=None: dict(now)
    try:
        result = sup.apply_socials()
    finally:
        socials.on = socials_on
    # The control bot is restarted on a thread of its own.
    for t in threading.enumerate():
        if t.name == "restart-controller":
            t.join(timeout=5)
    return sup, result, calls


kids = [("discord_1", "discord", 1, "running", True), ("tiktok_1", "tiktok", 1, "running", True),
        ("telegram", "telegram", None, "running", True), ("telegram_1", "telegram", 1, "running", True)]
planned = {"discord_1": ("discord", 1, "Discord #1"), "discord_2": ("discord", 2, "Discord #2"),
           "telegram": ("telegram", None, "Telegram"), "telegram_1": ("telegram", 1, "Telegram #1")}
now = {**ALL_ON, "tiktok": False}
sup, result, calls = make(kids, planned, ALL_ON, now)
check("switched off: its accounts stop", calls["stop"] == ["tiktok_1"], str(calls))
check("nothing else stops", "discord_1" not in calls["stop"] and "telegram" not in calls["stop"], str(calls))
check("an account added and never started is left alone", "discord_2" not in calls["start"], str(calls))
check("the control bot starts again, to count its accounts again", calls["restart"] == ["telegram"], str(calls))
check("what was stopped is remembered", sup._switched_off == {"tiktok_1"}, str(sup._switched_off))
check("and what was seen", sup._socials_seen == now)

# Back on: the one it stopped starts again, and one added while it was off starts as the app would start it.
kids2 = [("discord_1", "discord", 1, "running", True), ("tiktok_1", "tiktok", 1, "stopped", False),
         ("telegram", "telegram", None, "running", True)]
planned2 = {**planned, "tiktok_1": ("tiktok", 1, "TikTok #1"), "tiktok_2": ("tiktok", 2, "TikTok #2")}
# As the first switch left it: tiktok_1 stopped by the switch.
sup2, result2, calls2 = make(kids2, planned2, now, ALL_ON, switched_off=sup._switched_off)
check("switched back on: every account of it starts, as when the app opens",
      sorted(calls2["start"]) == ["tiktok_1", "tiktok_2"], str(calls2))
check("still not the account added and never started on another social", "discord_2" not in calls2["start"])
check("nothing stops", calls2["stop"] == [], str(calls2))

# An account someone stopped by hand stays stopped when its social comes back on.
kids3 = [("tiktok_1", "tiktok", 1, "stopped", False), ("tiktok_2", "tiktok", 2, "stopped", False)]
sup3 = Supervisor(port=0, no_web=True)
sup3._switched_off = {"tiktok_2"}
sup3._running = True
sup3._socials_seen = dict(now)
calls3 = {"start": []}
sup3.start = lambda cid: calls3["start"].append(cid)
sup3.stop = lambda cid, graceful_seconds=6.0: None
for cid, role, account, state, alive in kids3:
    c = Child(cid, role, account, cid)
    c.state, c.proc = state, Proc(alive)
    sup3.children[cid] = c
sup3._planned_children = lambda: {"tiktok_1": ("tiktok", 1, "TikTok #1"), "tiktok_2": ("tiktok", 2, "TikTok #2")}
_on = socials.on
socials.on = lambda config=None: dict(ALL_ON)
try:
    sup3.apply_socials()
finally:
    socials.on = _on
check("one stopped by hand stays stopped; the one the switch stopped starts", calls3["start"] == ["tiktok_2"],
      str(calls3))

# A crashing account waiting to be restarted is stopped too, or the watchdog would bring it back.
kids4 = [("instagram_1", "instagram", 1, "crashing", False)]
sup4, result4, calls4 = make(kids4, {}, ALL_ON, {**ALL_ON, "instagram": False})
check("one waiting to restart after a crash is stopped", calls4["stop"] == ["instagram_1"], str(calls4))

# Off with Telegram: its accounts, never the control bot.
sup5, result5, calls5 = make(kids, planned, ALL_ON, {**ALL_ON, "telegram": False})
check("Telegram off: the persona's Telegram account stops", "telegram_1" in calls5["stop"], str(calls5))
check("the control bot is never stopped by it", "telegram" not in calls5["stop"], str(calls5))

# Nothing changed: nothing happens.
sup6, result6, calls6 = make(kids, planned, ALL_ON, ALL_ON)
check("nothing changed, nothing done", calls6 == {"stop": [], "start": [], "restart": []}, str(calls6))

sup_src = read("app/web/supervisor.py")
check("what runs is decided by the same switches", "on = socials.on(config)" in sup_src
      and 'config.get("snapchat", {}).get("enabled", False)' not in sup_src)
check("the app remembers which were on as it opens", "self._socials_seen = socials.on()" in sup_src)

# ── The routes ───────────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== what the panel is sent ==")
from app.core import ipc  # noqa: E402

real_discover, real_on = ipc.discover_targets, socials.on
ipc.discover_targets = lambda: {
    "discord_1": {"platform": "discord", "account": 1, "target": 1},
    "snapchat_1": {"platform": "snapchat", "account": 1, "target": "snap"},
    "telegram_1": {"platform": "telegram", "account": 1, "target": "tg"},
}
socials.on = lambda config=None: {**ALL_ON, "snapchat": False}
try:
    shown = ipc.shown_targets()
    check("the accounts listed leave out a social switched off", list(shown) == ["discord_1", "telegram_1"], str(shown))
    from app.web.routes import persona_routes
    check("so do the profiles' accounts", persona_routes._known_accounts() == ["discord_1", "telegram_1"])
    check("but deleting a profile still moves every account it had",
          persona_routes._known_accounts(everyone=True) == ["discord_1", "snapchat_1", "telegram_1"])
    from app.web.routes import account_routes
    values = {"DISCORD_TOKEN_1": "abc123xyz.test.value", "SNAP_USERNAME_1": "someone_test",
              "TIKTOK_USERNAME_1": "someone.else"}
    slots = account_routes._slots(values)
    check("the account slots leave it out", [s["platform"] for s in slots] == ["discord", "tiktok"],
          str([s["platform"] for s in slots]))
    check("and no login ever leaves the server", all("token" not in s and "password" not in s for s in slots))
finally:
    ipc.discover_targets, socials.on = real_discover, real_on

# The counts: a social switched off counts nothing, and its fields stay, as nothing, so the page's sums add up.
from app.web.routes import stats_routes  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="lsb-socials-"))
db = tmp / "stats.db"


def fill():
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(db)
    import time as _t
    now_ts = _t.time() - 3600
    conn.execute("CREATE TABLE message_log (user_id INTEGER, username TEXT, ts REAL)")
    for table in ("message_log_snap", "message_log_tiktok", "message_log_instagram", "message_log_minecraft",
                  "message_log_imessage"):
        conn.execute(f"CREATE TABLE {table} (chat_id TEXT, username TEXT, ts REAL)")
    for table in ("user_stats", "user_stats_snap", "user_stats_tiktok", "user_stats_instagram",
                  "user_stats_minecraft", "user_stats_imessage"):
        conn.execute(f"CREATE TABLE {table} (first_seen REAL)")
    conn.executemany("INSERT INTO message_log VALUES (?, ?, ?)", [(111, "faris", now_ts)] * 3)
    conn.executemany("INSERT INTO message_log_tiktok VALUES (?, ?, ?)", [("tt_theo", "theo", now_ts)] * 5)
    conn.execute("INSERT INTO user_stats VALUES (?)", (now_ts,))
    conn.execute("INSERT INTO user_stats_tiktok VALUES (?)", (now_ts,))
    conn.commit()
    conn.close()


real_connect = stats_routes.connect_raw
stats_routes.connect_raw = lambda: (fill(), sqlite3.connect(db))[1]
try:
    socials.on = lambda config=None: dict(ALL_ON)
    every = stats_routes.stats_detail(None, days=7)
    socials.on = lambda config=None: {**ALL_ON, "tiktok": False}
    det = stats_routes.stats_detail(None, days=7)
    check("with everything on, TikTok's replies count", every["platform"]["tiktok"] == 5 and every["total"] == 8,
          str(every["platform"]))
    check("switched off, they count nothing", det["platform"]["tiktok"] == 0 and det["total"] == 3, str(det["platform"]))
    check("its field stays, as nothing", set(det["platform"]) == {p for p, _, _ in stats_routes.LOGS})
    check("every day still has every platform",
          all(set(d) == {"day", *(p for p, _, _ in stats_routes.LOGS)} for d in det["series"]))
    check("its days are empty", sum(d["tiktok"] for d in det["series"]) == 0
          and sum(d["discord"] for d in det["series"]) == 3)
    check("the hours count only what is on", sum(h["count"] for h in det["hourly"]) == 3)
    check("its people are not among the busiest", all(t["platform"] != "tiktok" for t in det["top"]), str(det["top"]))
    check("nor among the people counted", det["people"]["window"] == 1 and det["people"]["new"] == 1, str(det["people"]))

    socials.on = lambda config=None: {**ALL_ON, "discord": False}
    ov = stats_routes.overview(None)
    check("the overview: Discord off counts none of Discord's", ov["total"] == 0 and ov["top"] == []
          and not any(h["count"] for h in ov["hourly"]), str({k: ov[k] for k in ("total", "top")}))
    check("and leaves the others", ov["total_tiktok"] == 5, str(ov.get("total_tiktok")))
    socials.on = lambda config=None: {**ALL_ON, "tiktok": False}
    ov = stats_routes.overview(None)
    check("TikTok off counts none of TikTok's", ov["total_tiktok"] == 0 and ov["tiktok_series"] == [] and ov["total"] == 3)
finally:
    stats_routes.connect_raw = real_connect
    socials.on = real_on
    shutil.rmtree(tmp, ignore_errors=True)

# Discord's whole log, asked for with no account named (Big Picture's recent conversations): nothing when it is off.
from app.web.routes import chat_routes  # noqa: E402

socials.on = lambda config=None: {**ALL_ON, "discord": False}
try:
    check("Discord off: its conversations are not handed out", chat_routes.archive(None, 12, "") == {"conversations": []})
finally:
    socials.on = real_on

# The System page's dependency check names only the socials that are on, and needs nothing for none.
from app.web.routes import system_routes  # noqa: E402


def doctor_rows(case):
    socials.on = lambda config=None: {**ALL_ON, **case}
    try:
        out = system_routes._doctor_checks(None)
    finally:
        socials.on = real_on
    rows = out["checks"] if isinstance(out, dict) else out
    return {r["id"]: r for r in rows if r["id"] in ("node", "npm", "snap")}


rows = doctor_rows({"snapchat": False})
check("the dependency check does not name Snapchat when it is off",
      rows and not any("Snapchat" in (r["name"] + r["why"] + r["fix"] + str(r["action"])) for r in rows.values()),
      str(rows))
check("and says who does need them",
      "TikTok, Instagram, X, Reddit, WhatsApp, Minecraft and iMessage run on it." == rows["node"]["why"]
      and rows["snap"]["name"] == "Browser packages", str(rows))
rows = doctor_rows({k: False for k in ("snapchat", "tiktok", "instagram", "x", "reddit")})
check("with no browser social on, the packages are WhatsApp's own, which is what they are for",
      rows.get("snap", {}).get("name") == "WhatsApp packages" and "Puppeteer" not in rows["snap"]["why"],
      str(rows.get("snap")))
rows = doctor_rows({k: False for k in ("snapchat", "tiktok", "instagram", "x", "reddit", "whatsapp")})
check("with nothing that needs them, no packages at all", "snap" not in rows and "node" in rows, str(list(rows)))
rows = doctor_rows({k: False for k in ("snapchat", "tiktok", "instagram", "x", "reddit", "whatsapp", "minecraft",
                                       "imessage")})
check("with none that runs on Node, nothing about Node", rows == {}, str(list(rows)))

src = {name: read(path) for name, path in {
    "status": "app/web/routes/status_routes.py", "health": "app/web/routes/health_routes.py",
    "config": "app/web/routes/config_routes.py", "chat": "app/web/routes/chat_routes.py",
    "tray": "app/tray.py", "ctl": "app/telegram_bot/telegram_controller.py",
    "desc": "app/web/descriptions.py", "personas": "app/utils/personas.py"}.items()}
check("/api/socials says which are on", '@router.get("/api/socials")' in src["status"] and '{"on": socials.on()}' in src["status"])
check("/api/accounts lists only what is shown", "targets = ipc.shown_targets()" in src["status"])
check("/api/status's workers too", "socials.child_shown(c.get(\"role\"), c.get(\"account\"), switches)" in src["status"])
check("no warnings about a social switched off", 'mc_n = ipc._count_minecraft_accounts() if on["minecraft"] else 0' in src["health"]
      and 'snap_on = on["snapchat"]' in src["health"]
      and "if not socials.child_shown(child.get(\"role\"), child.get(\"account\"), on):" in src["health"])
check("saving a switch starts or stops its accounts at once",
      "if key in socials.SWITCHES:\n        _apply_socials(request)" in src["config"]
      and "supervisor.apply_socials()" in src["config"])
check("and so does the raw editor, an import, or the whole config", src["config"].count("_apply_socials(request, before)") == 3)
check("a chat with no account named goes to one that is shown", "targets = ipc.shown_targets()" in src["chat"])
check("the tray leaves them out", "and on.get(c.get(\"role\"), True)]" in src["tray"])
check("the control bot does not offer them", src["ctl"].count('if _social_on("') == 9)
from app.web import descriptions as desc  # noqa: E402
check("no social's switch says it needs a restart", not [k for k in socials.SWITCHES if desc.needs_restart(k)],
      str([k for k in socials.SWITCHES if desc.needs_restart(k)]))
check("the control bot's still does", desc.needs_restart("services.telegram.enabled"))
from app.utils import personas as _personas  # noqa: E402
check("a profile cannot switch a social for itself", all(f"{k}.enabled" in _personas.GLOBAL_ONLY for k in socials.SOCIALS))

# ── The panel ────────────────────────────────────────────────────────────────────────────────────────────────────
print()
print("== the panel's own lists, in Node ==")
node = shutil.which("node")
if not node or not (WEB / "node_modules" / "svelte").is_dir():
    print("  SKIP  needs Node and webui/node_modules")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "socials_logic.mjs")], cwd=WEB,
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("socials_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])

print()
print("== Settings: the order, only what is on, and their marks ==")
smap = read("webui/src/lib/settingsmap.ts")
# The tabs are defined in the order they were added; one ORDER list says the order they read in, in runs
# (tests/test_settings_order.py has the order itself). What matters here is that every social is in it, after the
# app's own tabs, so a switched-off one is the only thing that ever takes a social out of the nav.
order_block = smap[smap.index("const ORDER:"):smap.index("export const TABS")]
order = [i.strip().strip('"') for ids in re.findall(r"ids:\s*\[([^\]]*)\]", order_block)
         for i in ids.split(",") if i.strip()]
own = ["app", "look", "groq", "ai", "calls"]
socials = ["discord", "telegram", "whatsapp", "imessage", "snapchat", "instagram", "tiktok", "x", "reddit",
           "minecraft"]
check("the app's own tabs come first, every social after them",
      order == own + socials, str(order))
check("and no social is left out of the order", set(socials) <= set(order), str(sorted(set(socials) - set(order))))
page = read("webui/src/pages/Settings.svelte")
check("only the socials that are on have a tab", "const tabs = $derived(TABS.filter((t) => platformOn($socialsOn, t.id)));" in page
      and "{#each tabs as t (t.id)}" in page and "{#each TABS as t" not in page)
check("on a social just switched off, the first tab instead", "if (tabs.length && !tabShown(id)) untrack(() => pickTab(tabs[0]));" in page)
check("searching Settings finds nothing of one switched off", "&& tabShown((homeOf(f.key) ?? restHomeOf(f.key) ?? \"app/\").split(\"/\")[0])" in page)
check("Settings opens on App", 'persisted<string>("settingsPath", "app/services")' in read("webui/src/lib/stores.ts"))
check("the Telegram accounts' two switches are one, like the others",
      '"services.telegram_accounts.enabled": "telegram.enabled",' in page)
# 19px in its 34px tile since 2026-11-01 ("at the right size": at 17 the marks looked lost in their tiles).
check("each social's switch has its mark beside it",
      'class="settings-mark is-social is-{p.id}" class:is-off={!lit} style="--tone: {p.tone}"' in page
      and "<Icon name={p.icon} size={19} />" in page)
marks_css = read("webui/src/app.css").replace("\r\n", "\n")
check("each mark centred in its tile and as big as the others, by measure",
      ".settings-mark.is-social > svg {\n  transform: scale(var(--mark-s, 1)) translate(var(--mark-dx, 0%), var(--mark-dy, 0%));" in marks_css
      and ".settings-mark.is-telegram { --mark-s: 1.202; --mark-dx: -2.77%; --mark-dy: -2.68%; }" in marks_css
      and all(f".settings-mark.is-{p} {{ --mark-s:" in marks_css for p in
              ("discord", "snapchat", "tiktok", "instagram", "x", "reddit", "whatsapp", "minecraft", "imessage", "telegram")))
check("flat tiles: no ring, no glow, no sheen on any of them",
      "254 44 85" not in marks_css.split(".settings-mark.is-social {")[1].split("@container")[0]
      and "box-shadow" not in marks_css.split(".settings-mark {")[1].split(".settings-row:has(> .settings-mark)")[0]
      and "radial-gradient" not in marks_css.split(".settings-mark {")[1].split(".settings-row:has(> .settings-mark)")[0])
check("and centred on the words beside them: the hidden line under the words takes no height there",
      ".settings-row:has(> .settings-mark) .settings-meta:not(:has(.settings-restart, button)) {\n  position: absolute;" in marks_css)
check("the other rows of What runs a quiet one, so the names line up", '"services.webui.enabled": "monitor",' in page)
css = read("webui/src/app.css")
check("a mark goes grey while its switch is off", ".settings-mark.is-social.is-off {\n  filter: grayscale(1);" in css)
check("Snapchat's ghost dark on its yellow", ".settings-mark.is-snapchat { color: #141414; }" in css)
check("Instagram's in its own gradient", "linear-gradient(45deg, #feda75, #fa7e1e 25%, #d62976 55%, #962fbf 80%, #4f5bd5)" in css)
check("saving a switch asks again which are on", "if (Object.keys(dirty).some((k) => k in SOCIAL_OF)) refreshSocials();" in page)

print()
print("== nowhere else either ==")
app = read("webui/src/App.svelte")
check("asked as the panel opens and on the health beat",
      "refreshSocials();" in app and "visiblePoll(() => { pollHealth(); refreshSocials(); }, 15000" in app)
check("a change from anywhere asks every list of accounts again",
      "const stopSocials = socialsOn.subscribe((on) => {" in app and "loadChatAccounts().catch(() => {});" in app
      and "stopSocials();" in app)
acc = read("webui/src/pages/Accounts.svelte")
for pid in ("discord", "snapchat", "tiktok", "instagram", "minecraft", "imessage", "telegram"):
    check(f"no way to add a {pid} account while it is off", acc.count(f'{{#if on("{pid}")}}') == 3,
          str(acc.count(f'{{#if on("{pid}")}}')))
check("its accounts are not listed", ".filter((s) => platformOn($socialsOn, s.platform)));" in acc)
check("with every social off, a way to Settings", "Every social is switched off." in acc and "Turn one on in Settings" in acc)
check("Chats has none of its accounts", "platformOn(on, a.platform));" in read("webui/src/lib/chats.ts"))
mem = read("webui/src/pages/Memory.svelte")
check("Memory has none of its people", "u.platform ? platformOn($socialsOn, u.platform) : personOn($socialsOn, u.user_id)" in mem
      and "return l && personOn($socialsOn, l.user_id) ? l : null;" in mem
      and ".filter((id) => personOn($socialsOn, id))" in mem)
check("Logs have none of its lines", "foldRows(lines).filter((r) => sourceOn($socialsOn, r.source))" in read("webui/src/pages/Logs.svelte")
      and "foldRows(lines).filter((r) => sourceOn($socialsOn, r.source))" in read("webui/src/lib/dashboard/LogWidget.svelte"))
search = read("webui/src/lib/search.ts")
check("the search finds none of it", "if (!settingShown(f.key)) continue;" in search
      and "if (!platformOn(on, a.platform)) continue;" in search and "if (!sourceOn(on, l.source)) continue;" in search)
check("the Accounts page is not described by every platform's name",
      'accounts: "Add, start and stop your accounts.",' in search)
check("the Dashboard's platforms leave it out", ".filter((r) => platformOn($socialsOn, String(r[1])))" in read("webui/src/lib/dashboard/WidgetBody.svelte")
      and "&& platformOn($socialsOn, k))" in read("webui/src/lib/components/StatDetail.svelte"))
pics = read("webui/src/pages/Pictures.svelte")
check("no posting to it from Pictures", 'p.video && $socialsOn.tiktok !== false' in pics
      and '$socialsOn.instagram !== false && { label: "Post to Instagram…"' in pics)
check("a persona's Telegram account is named in the log", "s.match(ACCOUNT_ID)" in read("webui/src/lib/logrows.ts")
      and "\n  telegram: {" in read("webui/src/lib/platforms.ts"))

print()
print("== the mood, as a dropdown ==")
card = read("webui/src/lib/accounts/AccountCard.svelte")
check("a real dropdown, the app's own",
      '<Select size="sm" prefix="Mood" value={d?.mood ?? ""} placeholder="Not set" options={moodOptions}' in card
      and 'onchange={(v) => onmood(String(v))}' in card)
check("the box of pills is gone", 'menu === "mood"' not in card and "moodEl" not in card)
check("each mood with a face, or a badge with its initial",
      "...(MOOD_MARK[m.toLowerCase()] ? { mark: MOOD_MARK[m.toLowerCase()] } : { badge: true })," in card
      and 'chill: "😌"' in card)
check("and the first line of what it tells it, under its name", "hint: firstLine(moodLines[m])," in card)
check("one it was set to that is not listed still shows", "d?.mood && !moods.includes(d.mood) ? [d.mood, ...moods] : moods" in card)
check("with no moods yet, a way to the Persona page", 'window.location.hash = "/persona";' in card)
check("what each mood says, loaded once per profile", "export function loadMoodLines(" in read("webui/src/lib/accounts/state.ts")
      and "moodLines={moodLinesBy[personaIdOf(r.slot)] ?? moodLines}" in acc)
sel = read("webui/src/lib/components/Select.svelte")
check("the dropdown can say what it is, in a quiet word", 'prefix = "",' in sel
      and '{#if prefix}<span class="sel-prefix">{prefix}</span>{/if}' in sel)

print()
print("== a new profile's name stays as it is typed ==")
newp = read("webui/src/lib/personas/NewPersona.svelte")
check("the form is cleared only as it opens, not each time the profiles are asked for: it is made new each time, and reads the list once",
      "let color = $state(untrack(() => nextColor(list, palette)));" in newp and "{#if newOpen}" in read("webui/src/pages/Profiles.svelte")
      and "$effect(() => {\n    if (!open)" not in newp)
check("the page does ask for them every few seconds (why it mattered)", "reloadPersonas();\n    }, 5000);" in read("webui/src/pages/Profiles.svelte"))
mc = read("webui/src/lib/components/ModelChooser.svelte")
check("the model picker's search is not wiped either",
      "    untrack(() => {\n      query = \"\";" in mc and "if (open) for (const p of connected) loadModels(p.id);" in mc)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
