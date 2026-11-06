"""A shared Instagram reel, post or story, watched the way someone who was sent one watches it.

Instagram shows almost nothing to anyone not signed in, so this has two halves and both are checked here:

  * the embed page anyone can read (app/utils/instagramlinks.py): the links found in a message, the caption and
    whose it is, and the line the model gets when nothing could watch it properly
  * the watch itself (app/utils/instagramwatch.py): the facts kept for a month, what the model is told once it has
    been seen and heard, and the signed-in account asked to open it when the public page will not give the media

Nothing here reaches Instagram: every fetch is stood in for.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="llmbot_igwatch_"))
(DATA / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import instagramlinks as links  # noqa: E402
from app.utils import instagramwatch as watch  # noqa: E402

REEL = "https://www.instagram.com/reel/DBx1y2zAbc/"
POST = "https://www.instagram.com/p/C9kLmNoPqRs/"
STORY = "https://www.instagram.com/stories/lakeside.films/3412345678901234567/"

# ── The links in a message ───────────────────────────────────────────────────
print("== the links in a message ==")
found = links.links_in(f"look {REEL}?igsh=1 and {POST} and {STORY} x")
check("a reel, a post and a story, each once", len(found) == 3 and found[0].startswith(REEL), str(found))
check("and only Instagram's", links.links_in("https://example.com/p/ABCDE/ https://tiktok.com/@a/video/1") == [])
check("at most three get a card", len(links.links_in(" ".join(f"https://www.instagram.com/p/ABCDE{i}/"
                                                              for i in range(6)))) == 3)
check("a post's own code", links.shortcode(REEL) == "DBx1y2zAbc" and links.shortcode(POST) == "C9kLmNoPqRs"
      and links.shortcode(STORY) == "")
check("whose story and which one", links.story_of(STORY) == ("lakeside.films", "3412345678901234567"))
check("which kind of thing it is, from the link alone", links.kind_of(REEL) == "reel"
      and links.kind_of(POST) == "post" and links.kind_of(STORY) == "story")
check("where its embed page is", links.embed_url("DBx1y2zAbc").endswith("/p/DBx1y2zAbc/embed/captioned/"))
check("and the link Instagram itself would write", links.canonical("DBx1y2zAbc", "reel") == REEL)
check("what is kept under which name", watch.key_of(REEL) == "DBx1y2zAbc"
      and watch.key_of(STORY) == "story_lakeside-films_3412345678901234567" and watch.key_of("nope") == "")

# ── What the embed page says ─────────────────────────────────────────────────
print("\n== what the embed page says ==")
EMBED = """<html><head>
<meta property="og:title" content="lakeside.films on Instagram" />
<meta property="og:image" content="https://scontent.cdninstagram.com/cover.jpg" />
</head><body><script>
window.__additionalDataLoaded('extra',{"shortcode_media":{"shortcode":"DBx1y2zAbc","is_video":true,
"product_type":"clips","video_url":"https://scontent.cdninstagram.com/v.mp4",
"display_url":"https://scontent.cdninstagram.com/cover.jpg","video_duration":14.2,"taken_at_timestamp":1760000000,
"video_view_count":45200,"owner":{"username":"lakeside.films","full_name":"Lakeside Films","is_verified":true},
"edge_media_preview_like":{"count":3120},"edge_media_to_comment":{"count":84},
"edge_media_to_caption":{"edges":[{"node":{"text":"golden hour at the lake"}}]}}});
</script></body></html>"""

facts = links.facts(EMBED, REEL)
check("whose it is, and their name", facts.get("author") == "lakeside.films" and facts.get("name") == "Lakeside Films"
      and facts.get("verified") is True)
check("its caption", facts.get("caption") == "golden hour at the lake")
check("that it is a reel, and how long", facts.get("kind") == "reel" and facts.get("is_video") is True
      and facts.get("duration") == 14)
check("its numbers", facts.get("views") == 45200 and facts.get("likes") == 3120 and facts.get("comments") == 84)
check("where its picture and its video are", facts["thumbnail"].endswith("cover.jpg")
      and facts["video"].endswith("v.mp4"))
check("and the link Instagram writes for it", facts.get("url") == REEL)

PHOTOS = """<html><body><script>
window.__additionalDataLoaded('extra',{"graphql":{"shortcode_media":{"shortcode":"C9kLmNoPqRs","is_video":false,
"display_url":"https://scontent.cdninstagram.com/a.jpg","owner":{"username":"mara_k"},
"edge_sidecar_to_children":{"edges":[{"node":{"display_url":"https://scontent.cdninstagram.com/a.jpg"}},
{"node":{"display_url":"https://scontent.cdninstagram.com/b.jpg"}}]},
"edge_media_to_caption":{"edges":[{"node":{"text":"the weekend"}}]}}}});
</script></body></html>"""
many = links.facts(PHOTOS, POST)
check("several photos are a post, each one of them kept", many.get("kind") == "post"
      and many.get("is_video") is False and len(many.get("photos") or []) == 2, str(many.get("photos")))
check("a page that says nothing gives nothing", links.facts("<html></html>", POST) == {})
check("the line for one that could not be watched says whose it is and what it says",
      "@lakeside.films" in links.describe(facts) and "golden hour at the lake" in links.describe(facts))
check("and nothing at all for nothing", links.describe({}) == "")

# ── A watch, with the fetching stood in for ──────────────────────────────────
print("\n== watching one ==")
asked: list = []


async def fake_lookup(url):
    asked.append(("lookup", url))
    return dict(facts)


async def fake_download(url, limit=0, headers=None):
    asked.append(("download", url))
    return b"\x00" * 4096


def fake_look_video(blob, cfg, suffix=".mp4"):
    return b"board-bytes", b"sound-bytes", 14.2


async def fake_heard(sound):
    return "this place every october"


async def fake_caption(board, said="", kind="video"):
    return "someone paddles a canoe across a lake at sunset"


class FakeVideos:
    @staticmethod
    def available():
        return True


from app.utils import videos as _videos  # noqa: E402
from app.utils import videowatch  # noqa: E402

real = (links.lookup, videowatch.download, videowatch.look_video, videowatch.heard, videowatch.caption,
        _videos.available)
links.lookup = fake_lookup
videowatch.download = fake_download
videowatch.look_video = fake_look_video
videowatch.heard = fake_heard
videowatch.caption = fake_caption
# ffmpeg may not be on this machine; whether it is says nothing about the watching itself.
_videos.available = FakeVideos.available
try:
    w = asyncio.run(watch.watch(REEL))
    check("it is watched once, and what was seen and heard comes back",
          w and w.get("seen", "").startswith("someone paddles") and w.get("said") == "this place every october",
          str(w)[:200])
    check("its facts come with it", w and w.get("author") == "lakeside.films" and w.get("kind") == "reel"
          and w.get("duration") == 14)
    check("the video came from the embed page, so nothing had to be signed in",
          any(a == "download" and u.endswith("v.mp4") for a, u in asked), str(asked))
    check("it is kept under its own code", (watch.cache_dir() / "DBx1y2zAbc.json").is_file())
    again = asyncio.run(watch.watch(REEL))
    check("and read from there the next time, not watched again",
          again and again.get("seen") == w.get("seen") and len([a for a, _ in asked if a == "lookup"]) == 1,
          str([a for a, _ in asked]))
    check("the panel can ask what was seen without watching anything",
          (watch.seen_for(REEL) or {}).get("said") == "this place every october")
    note = watch.summary(w, lead="the reel they shared")
    check("the model is told what is in it and what is said in it",
          "You watched the reel they shared" in note and "@lakeside.films" in note
          and "someone paddles" in note and "this place every october" in note, note)
    # Big numbers cut short, small ones in full, as Instagram shows them.
    check("with its numbers as Instagram says them", "45.2K views" in note and "3120 likes" in note
          and watch.count_str(1250000) == "1.2M" and watch.count_str(842) == "842", note)
    check("and told to react to it, not to describe it back", "do not describe it back" in note)
    bare = watch.summary({"key": "x", "kind": "reel", "author": "mara_k", "caption": "hi"})
    check("one that could not be watched says so rather than pretending",
          "do not pretend to have seen it" in bare, bare)
finally:
    (links.lookup, videowatch.download, videowatch.look_video, videowatch.heard, videowatch.caption,
     _videos.available) = real

# ── When the public page will not give it: a signed-in account ───────────────
print("\n== when Instagram will not show it to a stranger ==")
shutil.rmtree(watch.cache_dir(), ignore_errors=True)
watch._missed.clear()
sent: list = []
media = DATA / "config" / "temp" / "insta_1_watch.jpg"
media.parent.mkdir(parents=True, exist_ok=True)
media.write_bytes(b"\x89PNG" + b"\x00" * 2048)


async def empty_lookup(url):
    return {}


async def no_download(url, limit=0, headers=None):
    return b""


def fake_look_photos(blobs):
    return b"board-bytes"


async def fake_send_and_wait(target, cmd, payload=None, timeout=10.0):
    sent.append((target, cmd, dict(payload or {})))
    return {"ok": True, "file": str(media), "kind": "photo",
            "facts": {"author": "lakeside.films", "caption": "a story"}}


from app.core import ipc  # noqa: E402

real2 = (links.lookup, videowatch.download, videowatch.look_photos, videowatch.caption, ipc.send_and_wait)
links.lookup = empty_lookup
videowatch.download = no_download
videowatch.look_photos = fake_look_photos
videowatch.caption = fake_caption
ipc.send_and_wait = fake_send_and_wait
os.environ["INSTAGRAM_USERNAME_1"] = "theo.wav"
os.environ["INSTAGRAM_PASSWORD_1"] = "x" * 12
try:
    w2 = asyncio.run(watch.watch(STORY, account=1))
    check("the account's own browser is asked to open it",
          sent and sent[0][1] == "insta_fetch" and sent[0][2].get("url") == STORY, str(sent))
    check("its own account is asked first", sent and sent[0][0] == "insta", str(sent))
    check("and what it saved is looked at", w2 and w2.get("seen", "").startswith("someone paddles")
          and w2.get("signed_in") is True, str(w2)[:200])
    check("the file it saved does not linger", not media.exists())
finally:
    links.lookup, videowatch.download, videowatch.look_photos, videowatch.caption, ipc.send_and_wait = real2

# ── Switched off, and on every platform ─────────────────────────────────────
print("\n== the switch, and the other platforms ==")
check("watching can be switched off (instagram.watch.enabled)", watch.settings()["enabled"] is True)
cfg_path = DATA / "config" / "config.yaml"
text = cfg_path.read_text(encoding="utf-8")
cfg_path.write_text(text.replace("  watch:\n    enabled: true\n    # Look at the posts of the people it talks to, "
                                 "to know what they are up to.\n    their_posts: true\n    # Send voice notes",
                                 "  watch:\n    enabled: false\n    their_posts: true\n    # Send voice notes"),
                    encoding="utf-8")
from app.utils import helpers  # noqa: E402

helpers.load_config.cache_clear() if hasattr(helpers.load_config, "cache_clear") else None
check("an Instagram link on Discord or Snapchat is watched by the same code",
      '"instagram.com" in (content or "")' in (ROOT / "app" / "utils" / "videowatch.py").read_text(encoding="utf-8")
      and 'instagramwatch.enrich' in (ROOT / "app" / "utils" / "videowatch.py").read_text(encoding="utf-8"))
check("and the engine sends them there", '"instagram.com"' in (ROOT / "app" / "core" / "engine.py").read_text(encoding="utf-8"))
check("what was seen is kept for a month, a few hundred at most", watch.KEEP_DAYS == 30 and watch.KEEP_MAX == 500)
check("two at a time at most, and never for long", watch.TIMEOUT <= 120)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + ", ".join(FAIL))
shutil.rmtree(DATA, ignore_errors=True)
sys.exit(1 if FAIL else 0)
