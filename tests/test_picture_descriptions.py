"""A picture's description: a caption, drawn properly, opened out on a click.

Four places asked a vision model to describe a picture, three of them "in full
detail", and got essays with bold and lists: a wall of text on the Pictures
page, printed with its asterisks, and a paragraph of tokens in the prompt
every time the bot sent that picture. They all ask for the same thing now, a
caption of a line or two, and whatever comes back is cleaned into one.

On the page a description shows three lines, fading where there is more, its
Markdown drawn. A click opens it out in place, easing to its full height, and
another folds it back. Long ones from before can be described again, shorter.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-picdesc-"))
(TMP / "config" / "pictures").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def src(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== one prompt, a caption ==")
from app.utils.pictures import DESCRIBE_PROMPT, LONG_DESCRIPTION, clean_description, describe_messages  # noqa: E402

check("it asks for a line or two", "one or two sentences" in DESCRIBE_PROMPT and "under 40 words" in DESCRIBE_PROMPT)
check("in plain words", "no markdown" in DESCRIBE_PROMPT.lower())
msg = describe_messages("data:image/png;base64,xx")
check("the picture goes with it", msg[0]["content"][0]["text"] == DESCRIBE_PROMPT
      and msg[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,xx")
paths = {
    "the page's own describing": "app/web/routes/media_routes.py",
    "the Discord command that adds pictures": "app/cogs/management.py",
    "the panel's describe, run by the Discord bot": "app/platforms/discord_runner.py",
    "the same on Snapchat": "app/platforms/snapchat_bridge.py",
}
for name, rel in paths.items():
    text = src(rel)
    check(f"{name} asks it, and cleans the answer", "describe_messages(" in text and "clean_description(" in text
          and "DESCRIBE_MAX_TOKENS" in text)
check("nothing asks for full detail any more", not any("in full detail" in src(rel) for rel in paths.values()))

print("\n== the answer, cleaned into a caption ==")
check("no bold, no italics", clean_description("A woman in a **red** coat, *smiling*.") == "A woman in a red coat, smiling.")
check("no \"The image shows\"", clean_description("The image shows a dog on a beach.") == "A dog on a beach.")
check("no \"In this photo,\"", clean_description("In this photo, a man holds a cup.") == "A man holds a cup.")
check("but a picture frame is still a picture frame",
      clean_description("The picture frame on the wall is gold.") == "The picture frame on the wall is gold.")
check("no reasoning, headings or bullets, and lines do not run together",
      clean_description("<think>hmm</think>## Scene\n- A dog\n- On a beach") == "Scene. A dog. On a beach.")
essay = " ".join(f"Sentence {i} goes on for a few more words here." for i in range(20))
short = clean_description(essay)
check("an essay is cut at a sentence, near sixty words", 40 <= len(short.split()) <= 60 and short.endswith("."), short)
check("nothing stays nothing", clean_description("") == "" and clean_description("   ") == "")

print("\n== the long ones, described again ==")
pics = TMP / "config" / "pictures"
for n in (1, 2, 3):
    (pics / f"IMG_{n}.png").write_bytes(b"x" * (100 + n))
from app.utils.db import add_picture_description, init_db  # noqa: E402
init_db()
add_picture_description("IMG_2.png", "Mirror selfie, fairy lights behind.")
add_picture_description("IMG_3.png", "A long one. " * 40)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import media_routes  # noqa: E402


async def _nothing():
    return None

media_routes._describe_pending = _nothing
app = FastAPI()
app.include_router(media_routes.router)
c = TestClient(app)
r = c.post("/api/pictures/describe-missing").json()
check("by default only the ones with none, queued with the persona they are", r["queued"] == 1
      and media_routes._describe_queue == [("default", "IMG_1.png")], str(r))
media_routes._describe_queue.clear()
r = c.post("/api/pictures/describe-missing", json={"long": True}).json()
check("asked, the long ones as well", r["queued"] == 2
      and sorted(media_routes._describe_queue) == [("default", "IMG_1.png"), ("default", "IMG_3.png")],
      str(media_routes._describe_queue))
check("long means longer than a caption", LONG_DESCRIPTION == 320 and "const LONG_DESC = 320;" in read("pages/Pictures.svelte"))
media_routes._describe_queue.clear()

print("\n== on the page ==")
page = read("pages/Pictures.svelte")
check("Markdown is drawn, not printed", '{@html renderMarkdown(p.description)}' in page
      and 'import { renderMarkdown } from "../lib/markdown";' in page)
check("three lines, fading where there is more", ".pd-text {\n    max-height: 4.8em;" in page and "mask-image: linear-gradient(" in page)
check("whether there is more is measured, by one observer for every card", "function overflowing(" in page
      and "node.scrollHeight > node.clientHeight + 1" in page and page.count("new ResizeObserver(") == 1)
check("a click opens it out, easing to its full height, with a little landing",
      "async function toggleDesc(" in page and "height: `${text.scrollHeight}px`" in page and "cubic-bezier(0.22, 1.25, 0.36, 1)" in page)
check("and folds it back the same way, the fade coming back as it goes",
      "closing[k] = true;" in page and ".pd.is-closing .pd-text" in page)
check("selecting text is not a click to fold", "if (window.getSelection()?.toString()) return;" in page)
check("and it works from the keyboard", "e.key === \"Enter\" || e.key === \" \"" in page and "aria-expanded=" in page)
check("no more cutting at 240 characters", "p.description.slice(0, 240)" not in page
      and '"Show less" : "Read all of it"' not in page)
check("full size draws it too", "{@html renderMarkdown(p.description)}" in read("lib/components/PictureViewer.svelte")
      and "<PictureViewer items={shownPics} current={view}" in page)
check("the long ones are offered a shorter description, and the offer can be put away",
      "api.describeMissing({ long: true }, who)" in page and 'localStorage.setItem("pictures.longHidden", "1")' in page)
check("the editor counts words, and says when a line or two would do", "editWords > 60" in page)
check("describing again is marked on the right card", "busy[keyOf(p)]" in page and "busy[p.name]" not in page)
check("the call sends what to redo", 'describeMissing: (opts: { long?: boolean } = {}, persona = "") =>' in read("lib/api.ts"))

print("\n== the undo bar ==")
ub = read("lib/components/UndoBar.svelte")
check("the picture that went, blurred where the page is hiding its pictures",
      "veil = false" in ub and ".ub-pile.is-veiled .ub-pic" in ub and "veil={!shown}" in page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
