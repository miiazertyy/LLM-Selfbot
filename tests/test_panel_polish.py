"""A batch of panel fixes, checked where they could quietly come undone.

  * @mentions in a message show the person, clickable, instead of <@1234...>
  * a reply that could not be sent says so in the log, and its row says so too
  * the Dashboard's small charts stay inside their tile
  * "WebUI" is written the one way everywhere it is shown
  * Settings: subtabs as pills with counts, visible fields with units, and a
    save bar that is actually on screen
  * System: the verdict first, problems before the checks that pass
"""
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "webui"
SRC = WEB / "src"
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


read = lambda rel: (SRC / rel).read_text(encoding="utf-8")

print("== mentions ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "mentions_logic.mjs")], cwd=WEB,
                          capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    print(proc.stdout.strip())
    check("mentions_logic.mjs passes", proc.returncode == 0, proc.stderr[-600:])
chats, body = read("pages/Chats.svelte"), read("lib/dashboard/WidgetBody.svelte")
check("the Chats preview draws mentions as people",
      "<MessageBody" in chats and "segments(text)" in read("lib/components/MessageBody.svelte"))
check("and so does the Dashboard's waiting list", "<MentionText text={u.snippet}" in body)
mt = read("lib/components/MentionText.svelte")
check("a mention is the same clickable name as everywhere else", "<UserChip" in mt)

print("\n== a reply that could not be sent ==")
runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
# The plain failure, not the one where no model can reply at all: that is said once (app/utils/ai.py), not per reply.
retry = runner[runner.index('"reason": "no reply was generated"') - 900: runner.index('"reason": "no reply was generated"')]
check("the runner logs why, instead of pointing at an empty log", 'log_error("Reply"' in retry)
check("an empty model answer is logged too", "The model returned an empty reply" in runner)
# The words live in lib/chatstatus.ts, shared with Big Picture Mode; Chats passes it the rows it tried.
_status = (ROOT / "webui" / "src" / "lib" / "chatstatus.ts").read_text(encoding="utf-8")
check("rows that could not be answered say so",
      "failed: failedReplies" in chats and "ctx.failed?.has(u.id)" in _status)

print("\n== the Dashboard's small charts stay in their tile ==")
spark = read("lib/dashboard/Spark.svelte")
style = spark.split("<style>")[1]
check("bars can shrink to fit", "min-width: 0" in style and "min-width: 2px" not in style)
check("and the chart clips rather than spilling", "overflow: hidden" in style)

print("\n== WebUI, written one way ==")
desc = (ROOT / "app" / "web" / "descriptions.py").read_text(encoding="utf-8")
shown_strings = []
for node_ in ast.walk(ast.parse(desc)):
    if isinstance(node_, ast.Dict):
        for v in node_.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                shown_strings.append(v.value)
bad = [s for s in shown_strings if re.search(r"\bwebui\b|\bWebui\b|\bWeb UI\b", s)]
check("no setting label or description says 'webui'", not bad, str(bad))
smap = read("lib/settingsmap.ts")
names = re.findall(r'name:\s*"([^"]+)"', smap)
check("nor does any Settings tab or subtab name", not [n for n in names if n.lower() == "webui" and n != "WebUI"])
check("the WebUI's port and address sit with the switch that serves it, spelled WebUI",
      '"services.webui.enabled",\n          "services.webui.port",' in smap.replace("\r\n", "\n")
      and "where the WebUI is served" in smap)

print("\n== Settings ==")
settings, css = read("pages/Settings.svelte"), read("app.css")
check("subtabs carry an icon and how many settings they hold",
      "subIcon(tab, s)" in settings and "settings-sub-n" in settings)
check("they wrap instead of hiding off the edge on a wide window", "flex-wrap: wrap" in css.split(".settings-subs {")[2])
check("numbers are real fields, with their unit", "num-field" in settings and "unitOf(f)" in settings)
check("and long ones are said in words", "human(f, value(f))" in settings)
check("chances read as percentages", "isChance(f) ? pct(value(f))" in settings)
check("the save bar appears when something is unsaved, and stays a moment to say it saved",
      "{#if changed || savedFlash}" in settings and "save-bar" in settings)
check("and is moved to <body>, so it is on screen and not under the fold", "use:toBody" in settings)

print("\n== System ==")
system = read("pages/System.svelte")
check("it opens on the verdict", "headline" in system and "sys-hero" in system)
check("problems come before the checks that pass",
      system.index("{#each problems as c") < system.index("{#each passing as c"))
check("the data folder's size is read when the page opens", "loadStorage();" in system.split("onMount(() => {")[1][:900])
check("it is two columns in an ordinary window, not one long scroll", "lg:grid-cols-" in system)

print("\n== problems and notices ==")
il = read("lib/components/IssueList.svelte")
check("the page banner and the Dashboard list are one component",
      "<IssueList" in read("lib/components/PageIssues.svelte") and "<IssueList" in read("pages/Dashboard.svelte"))
check("each level has its own icon", '"alertCircle"' in il and '"alert"' in il and '"info"' in il)
check("only notices can be dismissed, never problems", 'issue.level === "info"' in il.split('class="note-x"')[0][-300:])
check("no button that would only reload the page you are on", "i.route !== here" in il)
en = read("lib/components/ErrorNote.svelte")
check("a load failure says so in the same style, with a retry", "Could not load this" in en and "Try again" in en)

icons = read("lib/components/Icon.svelte")
key = re.search(r'paths\.key = "([^"]+)"', icons).group(1)
check("the key is one closed outline again (smooth), not loose strokes", "Z" in key and "l9-9" not in key)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
