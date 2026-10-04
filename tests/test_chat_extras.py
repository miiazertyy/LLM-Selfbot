"""Reactions, pasted pictures, and the right-click menus.

  * A message carries its reactions to the panel, and the Chats tab draws them.
  * A picture pasted into the composer is sent as an attachment, with limits on
    what and how much, and shown straight away rather than after the round trip.
  * Right-click menus appear under the cursor. A `position: fixed` menu does not,
    because the page wrapper keeps a transform after its entrance animation and
    so becomes the containing block; they are portalled to <body> instead.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


read = lambda rel: (SRC / rel).read_text(encoding="utf-8")
RUNNER = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "app" / "web" / "routes" / "chat_routes.py").read_text(encoding="utf-8")

print("== reactions reach the panel ==")
payload = RUNNER[RUNNER.index("def _message_payload"):RUNNER.index("def _waiting_entry")]
check("a message carries them", '"reactions"' in payload and "getattr(m, \"reactions\"" in payload)
check("a custom emoji comes with its picture", "cdn.discordapp.com/emojis/" in payload)
check("an animated one as a gif", "'gif' if getattr(emoji, 'animated'" in payload)
check("with how many reacted, and whether this account did",
      '"count"' in payload and '"mine"' in payload)
check("and a sane cap, so one message cannot flood the row", "reactions[:8]" in payload)
chats = read("pages/Chats.svelte")
check("the Chats tab draws them", "cd-reacts" in chats and "d.m.reactions" in chats)
check("this account's own are marked", "class:is-mine={r.mine}" in chats and ".cd-react.is-mine" in chats)
check("the type says what one looks like", "reactions?:" in read("lib/chats.ts"))

print("\n== a picture pasted into the composer ==")
check("Ctrl+V with a picture stages it", "function onComposerPaste" in chats and "clipboardData" in chats)
check("plain text still pastes as text", 'i.kind === "file"' in chats and "if (!files.length) return;" in chats)
check("there is a button for it too", "cd-attach" in chats and "filePick?.click()" in chats)
check("staged pictures are shown before they go", "cd-staged" in chats and "f.preview" in chats)
check("and can be taken off again", "function unstage" in chats and "revokeObjectURL" in chats)
check("a message may be only a picture", "if (!text && !files.length) return;" in chats)
check("what failed to send is given back, pictures included", "setStaged(k, files);" in chats)

print("\n== the limits on what can be sent ==")
fn = RUNNER[RUNNER.index("def _decode_files"):RUNNER.index("def _as_discord_files")]
check("only file types that make sense", "_ALLOWED_UPLOAD" in RUNNER and "png" in RUNNER.split("_ALLOWED_UPLOAD")[1][:120])
check("a cap on how many", "_MAX_FILES = 4" in RUNNER and "_MAX_FILES" in fn)
check("and on how big each is", "_MAX_FILE_BYTES" in fn)
check("a name cannot climb out of its folder", "os.path.basename" in fn)
check("bad base64 is refused rather than crashing", "validate=True" in fn and "could not be read" in fn)
check("each reason names the file it is about", fn.count("{name}:") >= 3)
check("the route caps them before the account is asked", "up to 4 files in one message" in ROUTES)
check("and waits longer when there is an upload", "90.0 if files else 30.0" in ROUTES)
check("the sent message comes back with its real links", "**_message_payload(sent)" in RUNNER)
check("so the local preview is swapped for them", "attachments: r.attachments" in read("lib/chats.ts"))


def _decode(raw):
    """The runner's own checker, run for real."""
    ns = {"os": __import__("os")}
    src = RUNNER[RUNNER.index("_MAX_FILES = 4"):RUNNER.index("def _as_discord_files")]
    exec(compile(src, "_decode", "exec"), ns)
    return ns["_decode_files"](raw)


import base64
ok_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode()
check("a normal picture goes through", _decode([{"name": "a.png", "data": ok_png}])[0] and not _decode([{"name": "a.png", "data": ok_png}])[1])
check("nothing at all is fine, it is an optional field", _decode(None) == ([], ""))
check("an odd file type is refused", "cannot be sent" in _decode([{"name": "x.exe", "data": ok_png}])[1])
check("five files are refused", "up to 4" in _decode([{"name": f"{i}.png", "data": ok_png} for i in range(5)])[1])
check("an empty one is refused", "was empty" in _decode([{"name": "a.png", "data": ""}])[1])
check("broken base64 is refused", "could not be read" in _decode([{"name": "a.png", "data": "!!!!"}])[1])
big = base64.b64encode(b"x" * (9 * 1024 * 1024)).decode()
check("an oversized one is refused, by name", "bigger than" in _decode([{"name": "big.png", "data": big}])[1])
check("a name with a path in it is reduced to the name",
      _decode([{"name": "../../evil.png", "data": ok_png}])[0][0][0] == "evil.png",
      str(_decode([{"name": "../../evil.png", "data": ok_png}])[0]))

print("\n== right-click menus land under the cursor ==")
cm = read("lib/components/GlobalMenu.svelte")
app = read("App.svelte")
check("one menu for the whole app, mounted once", "<GlobalMenu />" in app)
check("outside the page wrapper, so a transform there cannot move it",
      app.index("<GlobalMenu />") > app.index("</main>"))
check("fixed, where the click was", "position: fixed" in cm and "e.clientX" in cm)
check("it opens the other way near an edge", "innerWidth - m" in cm and "innerHeight - m" in cm)
check("Escape closes it", 'k === "Escape"' in cm)
check("and so does a click elsewhere, a scroll or the window losing focus",
      '"pointerdown", away, true' in cm and '"wheel", quietly' in cm and '"blur", quietly' in cm)
check("with no layer over the page, so a right-click elsewhere opens a menu there", "cm-catcher" not in cm)
check("the old per-page menu is gone", not (SRC / "lib" / "components" / "ContextMenu.svelte").exists())

print("\n== and are used everywhere one is wanted ==")
pics = read("pages/Pictures.svelte")
check("the Pictures grid uses it", "openMenuAt(e, [" in pics and "oncontextmenu={(e) => openMenu(e, p)}" in pics)
check("and saves through a real Save dialog, not a link that did nothing", "saveUrlAs(api.pictureUrl(p.name, p.id, who)" in pics
      and "download={" not in pics)
avatar = read("lib/components/Avatar.svelte")
check("an opened profile picture can be copied with a right-click",
      "openMenuAt(e, [" in avatar and "oncontextmenu=" in avatar and "copyImageFrom" in avatar)
check("and saved", "saveUrlAs(shownBig" in avatar)
check("its edge follows the picture, not the box around it",
      ".avatar-big" in avatar and "ring-1 ring-edge" not in avatar.split("<figure")[1][:900])
logs = read("pages/Logs.svelte")
check("the log uses one instead of a copy button on every row",
      "openMenuAt(e, [" in logs and "lg-copy" not in read("lib/components/LogRow.svelte"))
check("with more than copying: filtering to that account or kind", "Only this kind" in logs)
check("copying the picture is shared, not written twice",
      "copyImageFrom" in pics and (SRC / "lib" / "imagecopy.ts").is_file() and "function toPng" not in pics)

print("\n== a picture on its own is shown as the picture ==")
mb = read("lib/components/MessageBody.svelte")
check("no plate behind it", "background: rgb(0 0 0 / 0.25)" not in mb)
for rel, sel in (("pages/Chats.svelte", ".cd-bubble"), ("lib/bigpicture/BPStage.svelte", ".bps-bubble")):
    body = read(rel)
    check(f"{sel} drops its bubble for a picture-only message",
          f"{sel}:has(:global(.mb-media))" in body and "padding: 0;" in body.split(f"{sel}:has(")[1][:260])

print("\n== a run of messages has one picture, on its last ==")
chats_now = read("pages/Chats.svelte")
row = chats_now[chats_now.index('<span class="cd-msg-av"'):]
row = row[:row.index("</span>") + 7]
check("the picture is drawn only on the last message of a run", "{#if d.last}" in row and "<Avatar" in row)
check("the ones above keep its column, so the bubbles line up", 'class="cd-msg-av"' in row
      and ".cd-msg-av { width: 26px; flex-shrink: 0; }" in chats_now)
check("and no faded copies above it any more", "is-tail" not in chats_now)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
