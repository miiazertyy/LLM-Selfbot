"""TikTok beyond the inbox: the persona watches the TikToks it is sent (app/utils/tiktokwatch.py).

Run for real, in a throwaway data folder:
  * a post's page: its rehydration data read for a video and for a photo post, its facts, where its video and its
    sound alone can be downloaded (the smallest first), its photos
  * watching: frames from across a real little video (made with ffmpeg here, when there is one), its sound, and sound
    alone (TikTok's smallest videos carry none: it is a stream of its own)
  * what was seen kept per video for a month, a few hundred at most, and read back for the panel
  * one watch per video and a short rest for one that could not be read; a LIVE line never waits for a video
  * the note the model gets, and the message it goes in: a watched one needs no cover, one that could not be watched
    falls back to TikTok's oEmbed caption and cover, as before
  * the Chats tab's TikTok card says what the persona saw, once it has

Read from the source: the engine, Discord's own reply path and the TikTok runner hand over shared TikToks to it, and
its settings are placed, described and shipped.
"""
import asyncio
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

DATA = Path(tempfile.mkdtemp(prefix="llmbot_ttsocial_"))
(DATA / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def page(item, scope="webapp.video-detail"):
    data = {"__DEFAULT_SCOPE__": {"webapp.app-context": {}, scope: {"statusCode": 0, "itemInfo": {"itemStruct": item}}}}
    return ('<html><head></head><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
            + json.dumps(data) + "</script></body></html>")


VIDEO = {
    "id": "7686945827008433439", "desc": "trying  something new\ncan start with your DMs", "createTime": int(time.time()) - 3 * 86400,
    "author": {"uniqueId": "dinewithkent", "nickname": "Dine with Kent", "verified": True},
    "music": {"title": "original sound", "authorName": "Kent"},
    "stats": {"diggCount": 10900, "commentCount": 2567, "playCount": 458300, "shareCount": 718, "collectCount": "934"},
    "statsV2": {"diggCount": "10900", "playCount": "458300"},
    "video": {
        "duration": 120, "cover": "https://p16.tiktokcdn.com/cover.jpeg", "playAddr": "https://v16.tiktok.com/play.mp4",
        "downloadAddr": "https://v16.tiktok.com/download.mp4",
        "bitrateInfo": [
            {"Bitrate": 692983, "GearName": "normal_720_0", "PlayAddr": {"DataSize": "10441016", "UrlList": ["https://v16.tiktok.com/720.mp4"]}},
            {"Bitrate": 340864, "GearName": "adapt_540_1", "PlayAddr": {"DataSize": "4113948", "UrlList": ["https://v16.tiktok.com/540a.mp4", "https://v19.tiktok.com/540b.mp4"]}},
            {"Bitrate": 9_000_000, "GearName": "huge", "PlayAddr": {"DataSize": "90000000", "UrlList": ["https://v16.tiktok.com/huge.mp4"]}},
        ],
        "bitrateAudioInfo": [
            {"Bitrate": 128000, "UrlList": {"MainUrl": "https://v16.tiktok.com/a128.m4a", "BackupUrl": "", "FallbackUrl": "http://plain"}},
            {"Bitrate": 48969, "UrlList": {"MainUrl": "https://v16.tiktok.com/a48.m4a", "BackupUrl": "https://v19.tiktok.com/a48.m4a"}},
        ],
    },
}
PHOTO = {
    "id": "7300000000000000001", "desc": "dump", "createTime": int(time.time()) - 3600 * 5,
    "author": {"uniqueId": "mila.png", "nickname": "mila.png"},
    "music": {"title": "espresso", "authorName": "Sabrina"},
    "stats": {"diggCount": 12, "commentCount": 0, "playCount": 0},
    "video": {"duration": 0},
    "imagePost": {
        "images": [{"imageURL": {"urlList": [f"https://p16.tiktokcdn.com/{i}.webp", f"https://p19.tiktokcdn.com/{i}.jpeg"]}}
                   for i in range(6)],
        "cover": {"imageURL": {"urlList": ["https://p16.tiktokcdn.com/photocover.jpeg"]}},
    },
}

from app.utils import tiktoklinks, tiktokwatch, videos, videowatch  # noqa: E402
from app.utils import ai  # noqa: E402

# ── A post's page ────────────────────────────────────────────────────────────
print("== a post's page ==")
item = tiktokwatch.page_item(page(VIDEO))
check("its rehydration data gives the post", item.get("id") == VIDEO["id"])
check("a page without it gives nothing (a check, a private post)", tiktokwatch.page_item("<html>nope</html>") == {})
check("nor does broken data", tiktokwatch.page_item('<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{bad</script>') == {})
check("a photo post under another scope is found too", tiktokwatch.page_item(page(PHOTO, "webapp.photo-detail")).get("id") == PHOTO["id"])
f = tiktokwatch.facts(item)
check("whose, by @handle and name", f["author"] == "dinewithkent" and f["name"] == "Dine with Kent" and f["verified"])
check("its caption on one line", f["caption"] == "trying something new can start with your DMs")
check("its numbers, as numbers", (f["views"], f["likes"], f["comments"], f["saves"]) == (458300, 10900, 2567, 934))
check("its length, sound and cover", f["duration"] == 120 and f["music"] == "original sound" and f["cover"].endswith("cover.jpeg"))
check("its own address, whatever link led to it", f["url"] == "https://www.tiktok.com/@dinewithkent/video/7686945827008433439")
src = tiktokwatch.video_sources(item)
check("the smallest video first, every copy of it, the oversized one left out",
      src[:2] == ["https://v16.tiktok.com/540a.mp4", "https://v19.tiktok.com/540b.mp4"] and "https://v16.tiktok.com/huge.mp4" not in src)
check("then the bigger ones, and the page's own play and download addresses",
      src[2] == "https://v16.tiktok.com/720.mp4" and src[-2:] == ["https://v16.tiktok.com/play.mp4", "https://v16.tiktok.com/download.mp4"])
check("its sound alone, the smallest first, https only",
      tiktokwatch.audio_sources(item) == ["https://v16.tiktok.com/a48.m4a", "https://v19.tiktok.com/a48.m4a", "https://v16.tiktok.com/a128.m4a"])
p = tiktokwatch.facts(PHOTO)
check("a photo post is one, with how many photos and no length", p["kind"] == "photo" and p["photos"] == 6 and p["duration"] == 0)
check("its cover is its own", p["cover"].endswith("photocover.jpeg") and p["url"].endswith("/photo/7300000000000000001"))
check("its first four photos, every copy of each", len(tiktokwatch.photo_sources(PHOTO)) == 4
      and tiktokwatch.photo_sources(PHOTO)[0] == ["https://p16.tiktokcdn.com/0.webp", "https://p19.tiktokcdn.com/0.jpeg"])
check("a post's id from any full link", tiktokwatch.video_id("https://www.tiktok.com/@a.b/photo/7300000000000000001?x=1") == "7300000000000000001")
check("and none from a short one it has not followed yet", tiktokwatch.video_id("https://vm.tiktok.com/ZMabc123/") == "")

# ── Watching ─────────────────────────────────────────────────────────────────
print("\n== watching ==")
cfg = tiktokwatch.settings()
check("on, listening, up to three minutes, as shipped", cfg == {"enabled": True, "listen": True, "max_seconds": 180})
if not videos.available():
    print("  SKIP  needs ffmpeg")
else:
    ffmpeg = videos.tools()[0]
    work = Path(tempfile.mkdtemp(prefix="ttwatch_"))
    clip, sound_only = work / "clip.mp4", work / "sound.m4a"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=15",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "4", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)], check=True, capture_output=True)
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(clip), "-vn", "-c:a", "copy", str(sound_only)],
                   check=True, capture_output=True)
    board, sound, length = videowatch.look_video(clip.read_bytes(), dict(cfg))
    check("frames from across it on one picture", board[:3] == b"\xff\xd8\xff" and len(board) > 5000)
    check("and its sound, to be transcribed, and how long it is", bool(sound) and len(sound) > 2000 and 3.5 < length < 4.5)
    _, quiet, _ = videowatch.look_video(clip.read_bytes(), dict(cfg, listen=False))
    check("not listened to when listening is off", quiet is None)
    alone = videowatch.spooled(sound_only.read_bytes(), ".m4a", lambda p: videowatch.listen_to(p, cfg))
    check("sound alone is heard too (TikTok's own sound stream)", bool(alone) and len(alone) > 2000)
    short = videos.sheet(clip, 6, 240, upto=1.0)
    check("only so much of a long one is looked at", short[:3] == b"\xff\xd8\xff")
    left = [p for p in Path(tempfile.gettempdir()).glob("llmselfbot-watch-*")]
    check("nothing is left behind", not left, str(left[:3]))
    from PIL import Image
    import io
    shots = []
    for color in ("red", "green", "blue"):
        buf = io.BytesIO()
        Image.new("RGB", (900, 1200), color).save(buf, "JPEG")
        shots.append(buf.getvalue())
    photos = videowatch.look_photos(shots + [b"not a picture"])
    im = Image.open(io.BytesIO(photos))
    check("a photo post's photos on one picture, each made small, the broken one skipped", im.size == (984, 1304), im.size)
    shutil.rmtree(work, ignore_errors=True)

# ── Kept ─────────────────────────────────────────────────────────────────────
print("\n== what was seen, kept ==")
seen = dict(f, seen="A man cooks pasta in a small kitchen.", said="this is how my nonna does it", watched=int(time.time()))
tiktokwatch.keep(seen)
check("kept by the video's id", (tiktokwatch.cache_dir() / f"{VIDEO['id']}.json").exists())
check("read back", tiktokwatch.cached(VIDEO["id"]) == seen)
check("and for the panel by any full link to it", tiktokwatch.seen_for(f["url"] + "?is_from_webapp=1")["seen"] == seen["seen"])
check("not by a made-up id", tiktokwatch.cached("../../etc") is None and tiktokwatch.cached("12") is None)
old = tiktokwatch.cache_dir() / f"{VIDEO['id']}.json"
os.utime(old, (time.time() - 31 * 86400,) * 2)
check("forgotten after a month", tiktokwatch.cached(VIDEO["id"]) is None)
for i in range(5):
    tiktokwatch.keep(dict(seen, id=str(8000000000 + i)))
check("the month-old one is pruned as others are kept", not old.exists())
was = tiktokwatch.KEEP_MAX
tiktokwatch.KEEP_MAX = 3
tiktokwatch.keep(dict(seen, id="8000000009"))
tiktokwatch.KEEP_MAX = was
check("a few hundred at most, the newest kept", len(list(tiktokwatch.cache_dir().glob("*.json"))) == 3
      and (tiktokwatch.cache_dir() / "8000000009.json").exists())

# ── One at a time ────────────────────────────────────────────────────────────
print("\n== one at a time ==")
calls = []


async def fake_watch(url, cfg):
    calls.append(url)
    await asyncio.sleep(0.05)
    if "broken" in url:
        return None
    return dict(f, id="7111111111111111111", seen="Someone dances.", said="")


real_watch = tiktokwatch._watch
tiktokwatch._watch = fake_watch


async def twice():
    u = "https://www.tiktok.com/@x/video/7111111111111111111"
    a, b = await asyncio.gather(tiktokwatch.watch(u), tiktokwatch.watch(u))
    c = await tiktokwatch.watch(u)
    return a, b, c


a, b, c = asyncio.run(twice())
check("the same video asked for twice at once is watched once", len(calls) == 1 and a and b and a["seen"] == b["seen"] == c["seen"])
check("and kept for next time", tiktokwatch.cached("7111111111111111111") is not None)
calls.clear()
asyncio.run(tiktokwatch.watch("https://www.tiktok.com/@x/video/7222222222222222222?broken=1"))
asyncio.run(tiktokwatch.watch("https://www.tiktok.com/@x/video/7222222222222222222?broken=1"))
check("one that could not be read is left alone a while", len(calls) == 1)
os.environ.pop("LLMSELFBOT_WATCH_OFF", None)

# ── The note, and the message ────────────────────────────────────────────────
print("\n== the note the model gets ==")
now = time.time()
note = tiktokwatch.summary(dict(seen, created=int(now) - 3 * 86400), now=now)
check("what it is, whose, when, how long and how it is doing",
      note.startswith("[You watched the TikTok they shared: by @dinewithkent (Dine with Kent), posted 3 days ago, 2 minutes long, 458.3K views, 10.9K likes, 2567 comments."), note)
check("its caption and sound", 'Caption: "trying something new can start with your DMs".' in note and 'Sound: "original sound" by Kent.' in note)
check("what happens and what is said in it", "What happens in it: A man cooks pasta in a small kitchen." in note
      and 'What is said in it: "this is how my nonna does it".' in note)
check("and to react to it, not describe it back", note.endswith("do not describe it back to them.]"))
facts_only = tiktokwatch.summary(dict(f, created=0))
check("not watched: what it is only, with nothing to react to", facts_only.startswith("[About the TikTok they shared: by @dinewithkent")
      and "What happens" not in facts_only and "React" not in facts_only)
ph = tiktokwatch.summary(dict(p, seen="Three selfies on a beach.", created=int(now) - 5 * 3600), now=now)
check("a photo post is looked at, its photos counted, its song named",
      ph.startswith("[You looked at the TikTok they shared (a photo post): by @mila.png, posted 5 hours ago, 6 photos, 12 likes.")
      and 'Song: "espresso".' in ph and "What is in the photos: Three selfies on a beach." in ph, ph)
check("numbers as TikTok shows them", [tiktokwatch.count(n) for n in (999, 2567, 10900, 458300, 1_250_000, 2_000_000_000)]
      == ["999", "2567", "10.9K", "458.3K", "1.2M", "2B"])
check("ages as a person says them", [tiktokwatch.ago(now - s, now) for s in (60, 7200, 86400 * 1.5, 86400 * 9, 86400 * 20, 86400 * 100, 86400 * 800)]
      == ["within the hour", "2 hours ago", "yesterday", "9 days ago", "2 weeks ago", "3 months ago", "2 years ago"])
check("a long caption is cut at a word", tiktokwatch._clip("word " * 100, 30).endswith("...") and len(tiktokwatch._clip("word " * 100, 30)) <= 30)

lookups = []


async def fake_lookup(url, timeout=6.0):
    lookups.append(url)
    return {"title": "a cat", "author_name": "Cats", "author_unique_id": "cats", "thumbnail_url": "https://p16.tiktokcdn.com/oembed.jpeg", "id": ""}


tiktoklinks.lookup = fake_lookup
watched = {"https://www.tiktok.com/@x/video/7333333333333333333": dict(f, seen="A cat jumps.", said=""),
           "https://www.tiktok.com/@x/video/7444444444444444444": dict(f, seen="", said="")}


async def fake_watch2(url):
    return watched.get(url)


real_public_watch = tiktokwatch.watch
tiktokwatch.watch = fake_watch2
text, cover, was_watched = asyncio.run(tiktokwatch.enrich("lol https://www.tiktok.com/@x/video/7333333333333333333"))
check("a watched one goes in with the message, with no cover to look at again",
      text.startswith("lol https://") and "[You watched the TikTok they shared" in text and cover == "" and was_watched)
text, cover, was_watched = asyncio.run(tiktokwatch.enrich("https://www.tiktok.com/@x/video/7444444444444444444"))
check("one read but not watched: what it is, and its cover for the vision model",
      "[About the TikTok they shared" in text and cover.endswith("cover.jpeg") and not was_watched)
text, cover, was_watched = asyncio.run(tiktokwatch.enrich("https://vm.tiktok.com/ZMnope11/"))
check("one that will not open falls back to oEmbed, as before",
      '[The TikTok they shared is by @cats, captioned: "a cat"]' in text and cover.endswith("oembed.jpeg") and not was_watched)
lookups.clear()


async def realtime():
    token = ai.REALTIME.set(True)
    try:
        return await tiktokwatch.enrich("https://www.tiktok.com/@x/video/7333333333333333333")
    finally:
        ai.REALTIME.reset(token)


text, cover, was_watched = asyncio.run(realtime())
check("a LIVE line never waits for a video: oEmbed only", lookups and not was_watched and "You watched" not in text)
plain = asyncio.run(tiktokwatch.enrich("no links here"))
check("a message with no TikTok is left alone", plain == ("no links here", "", False))
tiktokwatch.watch = real_public_watch
tiktokwatch._watch = real_watch

# ── Where it is used ─────────────────────────────────────────────────────────
print("\n== where it is used ==")
eng = read("app/core/engine.py")
check("the engine watches shared TikToks, Instagram posts and Spotlights (every platform)",
      "await videowatch.enrich_links(msg.content)" in eng and "tiktoklinks.enrich(msg.content)" not in eng
      and '"snapchat.com"' in eng and '"instagram.com"' in eng)
check("and drops a cover the runner sent once the video itself was watched",
      'msg.image_url == (msg.extra or {}).get("tiktok_cover")' in eng)
dr = read("app/platforms/discord_runner.py")
check("Discord's own reply path watches them too, kept in the conversation",
      "await videowatch.enrich_links(prompt)" in dr and 'history[-1] = {**history[-1], "content":' in dr
      and "_with_note(_tt_note)" in dr)
check("and drops Discord's preview of one it watched", "def _tiktok_preview(message, image_url)" in dr
      and "if _tt_watched and image_url and _tiktok_preview(message, image_url):" in dr)
run = read("app/platforms/snapchat/tiktok_runner.js")
check("a TikTok DM card with a link is described by it, to be watched", "const url = m.media?.url ||" in run)
check("its cover is only sent when there is no link, and said to be one",
      '&& !m.media?.url).pop();' in run and "cover: cover || undefined," in run)
check("the bridge passes that on", '**({"tiktok_cover": image_url} if entry.get("cover") and image_url else {})'
      in read("app/platforms/snapchat_bridge.py"))
check("a short link's card finds what was seen by the post's id", 'info["id"] = str(data.get("embed_product_id") or "")'
      in read("app/utils/tiktoklinks.py"))
routes = read("app/web/routes/chat_routes.py")
check("the card route reads what was seen off the loop", "await asyncio.to_thread(tiktokwatch.cached, vid)" in routes)
card = read("webui/src/lib/components/TikTokCard.svelte")
check("the card says what the persona saw", "tt-seen" in card and '<Icon name="eye"' in card)
check("and asks again later for one not watched yet", "known.delete(u)" in card and "60_000" in card)

# ── Settings ─────────────────────────────────────────────────────────────────
print("\n== settings ==")
smap = read("webui/src/lib/settingsmap.ts")
schema = read("app/web/schema.py")
desc = read("app/web/descriptions.py")
yaml_text = read("resources/config.yaml")
for key in ("tiktok.watch.enabled", "bot.videos.enabled", "bot.videos.listen", "bot.videos.max_seconds"):
    check(f"{key}: shipped, typed, described, labelled and placed",
          f'"key": "{key}"' in schema and desc.count(f'"{key}": ') == 2 and f'"{key}",' in smap)
check("watching TikToks is its own sub of the TikTok tab", 'id: "watching",\n        name: "Watching",' in smap)
check("how videos are watched is one place for every platform", 'id: "videos",\n        name: "Videos they send",' in smap
      and '"tiktok.watch.listen"' not in smap and '"tiktok.watch.max_seconds"' not in smap)
check("shipped on, listening, three minutes", "  videos:\n    enabled: true\n    listen: true\n    max_seconds: 180" in yaml_text
      and "  watch:\n    enabled: true\n" in yaml_text and "listen" not in yaml_text.split("  watch:", 1)[1].split("\n\n", 1)[0])
check("read as each message comes: no restart", not any(f'"{k}"' in desc[desc.index("_NEEDS_RESTART = {"):
                                                                     desc.index("def section_for")]
                                                        for k in ("tiktok.watch.enabled", "bot.videos.enabled",
                                                                  "bot.videos.listen", "bot.videos.max_seconds")))
check("its length is in seconds on the dial", "in seconds" in desc.split('"bot.videos.max_seconds": ', 1)[1].split("\n", 1)[0])
for text_ in (read("app/utils/tiktokwatch.py"), read("app/utils/videowatch.py"), card):
    check("no em dashes", "\u2014" not in text_)

# ── What the persona knows of TikTok beyond its DMs ──────────────────────────
print("\n== their TikTok, in a DM with them ==")
from app.utils import tiktoksocial  # noqa: E402

people = tiktoksocial.people_dir()
people.mkdir(parents=True, exist_ok=True)
contact = {"name": "Theo", "bio": "film kid\nlakes and cameras", "followers": 12345, "verified": True,
           "posts": [{"id": "7500000000000000001", "url": "https://www.tiktok.com/@theo.wav/video/7500000000000000001",
                      "caption": "sunset over the lake", "views": "1.2K", "pinned": True},
                     {"id": "7500000000000000002", "url": "https://www.tiktok.com/@theo.wav/video/7500000000000000002",
                      "caption": "", "views": "830"}],
           "newest": "7500000000000000002", "posts_at": time.time(), "wrote": time.time()}
(people / "contacts_1.json").write_text(json.dumps({"tt_theo-wav": contact}), encoding="utf-8")
tiktokwatch.keep(dict(f, id="7500000000000000002", author="theo.wav", name="Theo", seen="Theo films ducks on a pier.",
                      said="", caption="", created=int(time.time()) - 7200))
block = tiktoksocial.profile_block(contact, "theo.wav", tiktokwatch.cached("7500000000000000002"), news=True)
check("who they are: @handle, name, followers, verified", block.startswith("THEIR TIKTOK: @theo.wav (Theo), 12.3K followers, verified."), block)
check("their bio on one line", 'Their bio: "film kid lakes and cameras".' in block)
check("their latest posts, pinned and uncaptioned said so", '"sunset over the lake" (1.2K views) (pinned)' in block
      and "one with no caption (830 views)" in block)
check("their newest, as it was watched, as background", "You watched their newest TikTok" in block
      and "Theo films ducks on a pier." in block and "React to it" not in block)
check("news once: they posted it since you last talked", "They posted it since you last talked" in block)
check("and never recited", block.endswith("never recite it."))
first = tiktoksocial.dm_context(1, "tt_theo-wav", "theo.wav")
second = tiktoksocial.dm_context(1, "tt_theo-wav", "theo.wav")
check("the new post is news in the first DM after it, not every one", "since you last talked" in first
      and "since you last talked" not in second and "THEIR TIKTOK" in second)
check("someone with nothing known: nothing", tiktoksocial.profile_block({}, "") == "")

print("\n== what it saw on For You ==")
tiktokwatch.keep(dict(f, id="7600000000000000001", author="cats", seen="A cat knocks a cup off a table.", said=""))
pool = [{"id": "7600000000000000001", "url": "https://www.tiktok.com/@cats/video/7600000000000000001", "handle": "cats",
         "caption": "lol", "liked": True, "at": time.time() - 600},
        {"id": "7600000000000000002", "url": "https://www.tiktok.com/@dogs/video/7600000000000000002", "handle": "dogs",
         "caption": "woof", "liked": False, "at": time.time() - 300},
        {"id": "7600000000000000003", "url": "https://www.tiktok.com/@old/video/7600000000000000003", "handle": "old",
         "caption": "", "liked": True, "at": time.time() - 5 * 86400}]
seen_text = tiktoksocial.seen_block(pool)
check("the ones it watched properly, today, said briefly", seen_text.startswith("THINGS YOU SAW ON TIKTOK TODAY")
      and "@cats's video: A cat knocks a cup off a table. (you liked it)" in seen_text and "dogs" not in seen_text)
check("brought up only if the talk goes there", seen_text.endswith("only if the conversation goes there."))
check("nothing watched today: nothing", tiktoksocial.seen_block(pool[1:]) == "")

print("\n== a comment under someone's video ==")
check("public, about the video, nothing private", all(w in tiktoksocial.comment_context("sent") for w in
      ("PUBLIC COMMENT", "a TikTok someone sent you", "No hashtags, no @mentions, nothing private")))
check("their newest, and For You, said as such", "newest TikTok of someone you talk to" in tiktoksocial.comment_context("theirs")
      and "on your For You" in tiktoksocial.comment_context("foryou"))
check("a comment goes up without tags, one line, short",
      tiktoksocial.clean_comment("this is so good #fyp @theo.wav\nsecond line") == "this is so good"
      and len(tiktoksocial.clean_comment("x" * 400)) == 150)

print("\n== sending a TikTok when asked ==")
asks = ["send me a tiktok", "got any good tiktoks?", "show me a funny TikTok pls", "envoie moi un tiktok",
        "t'as des tiktoks drôles ?", "share a tiktok with me"]
nots = ["i saw a tiktok yesterday", "tiktok is down", "j'ai vu un tiktok", "what's your tiktok?", "lol"]
check("asking for one, in English or French", all(tiktoksocial.wants_tiktok(t) for t in asks),
      [t for t in asks if not tiktoksocial.wants_tiktok(t)])
check("talking about one is not asking for one", not any(tiktoksocial.wants_tiktok(t) for t in nots),
      [t for t in nots if tiktoksocial.wants_tiktok(t)])
pick = tiktoksocial.share_pick(pool, "discord_1:42")
check("a liked one from the last three days first", pick and pick["id"] == "7600000000000000001")
tiktoksocial.mark_shared("discord_1:42", pick["id"])
check("then one not sent to them yet", tiktoksocial.share_pick(pool, "discord_1:42")["id"] == "7600000000000000002")
tiktoksocial.mark_shared("discord_1:42", "7600000000000000002")
check("and none once all were sent (the old one is too old)", tiktoksocial.share_pick(pool, "discord_1:42") is None)
check("someone else still gets the best one", tiktoksocial.share_pick(pool, "snapchat_1:x")["id"] == "7600000000000000001")
words = tiktoksocial.share_context(pool[0])
check("the model is told what it is sending and not to paste a link",
      words.startswith("YOU ARE SENDING THEM A TIKTOK") and "A cat knocks a cup" in words and "Do not paste a link" in words)
check("one never watched is said by its author and caption",
      "it is by @dogs, captioned \"woof\"" in tiktoksocial.share_context(pool[1]))
(people / "seen_1.json").write_text(json.dumps(pool), encoding="utf-8")
from app.utils import personas  # noqa: E402
check("a persona's pool is its TikTok accounts' (Default's here)", tiktoksocial.tiktok_accounts_of(personas.DEFAULT) == [1]
      and len(tiktoksocial.pools_for(personas.DEFAULT)) == 3)
check("off unless switched on", tiktoksocial.share_settings() is False)

print("\n== visiting someone's LIVE ==")
from app.utils import livecohost  # noqa: E402

vc = livecohost.viewer_context("mara_k", "named", "theo", "@theo.wav what do you think", ["a: hi", "b: lol"])
check("a viewer in their public chat, never the streamer", vc.startswith("LIVE: you are watching @mara_k's TikTok LIVE as a viewer")
      and "never the streamer" in vc)
check("the chat just now, and who talked to it", "The chat just now: a: hi | b: lol." in vc
      and 'theo said to you in the chat: "@theo.wav what do you think". Answer them.' in vc)
check("a hello when it arrives", "Say a short hello" in livecohost.viewer_context("mara_k", "arrive", "", ""))
check("talked to by @handle or by name", livecohost.addressed("hey @theo.wav!", ["theo.wav"])
      and livecohost.addressed("Imprimante you there?", ["imprimante"]))
check("not by a word inside another", not livecohost.addressed("theodore is here", ["theo"])
      and not livecohost.addressed("hello", ["", "ab"]))

os.environ["BRIDGE_PLATFORM"] = "tiktok"
import app.platforms.snapchat_bridge as bridge  # noqa: E402

bridge._VISIT.update(on=True, host="mara_k", greeted=False, said=[], since=time.time(), names=["theo.wav", "Theo"])
check("a hello once when it arrives", bridge._visit_line_kind("arrive", "", time.time()) == "arrive")
bridge._VISIT["greeted"] = True
check("not twice", bridge._visit_line_kind("arrive", "", time.time()) == "")
check("an answer when someone talks to it", bridge._visit_line_kind("comment", "theo are you real", time.time()) == "named")
check("nothing for a gift or a join", bridge._visit_line_kind("gift", "Rose", time.time()) == ""
      and bridge._visit_line_kind("join", "", time.time()) == "")
bridge._VISIT["said"] = [time.time()]
check("no line of its own right after the last", all(bridge._visit_line_kind("comment", "nice", time.time()) == ""
                                                     for _ in range(60)))
env = bridge._tiktok_env({"tiktok": {"watch": {"enabled": True, "their_posts": False},
                                     "engage": {"like_sent": True, "mentions": True, "likes_per_day": 12},
                                     "visits": {"enabled": True, "stay_minutes": 7, "lines_per_5min": 2},
                                     "foryou": {"enabled": True, "like_percent": 20}, "posting": {"per_day": 2}}})
check("the runner is told every going-out setting", {k: env.get(k) for k in (
    "TIKTOK_WATCH", "TIKTOK_THEIR_POSTS", "TIKTOK_LIKE_SENT", "TIKTOK_MENTIONS", "TIKTOK_LIKES_PER_DAY", "TIKTOK_VISITS",
    "TIKTOK_VISIT_MINUTES", "TIKTOK_VISIT_LINES", "TIKTOK_FORYOU", "TIKTOK_FORYOU_LIKE_PERCENT", "TIKTOK_POSTS_PER_DAY")}
      == {"TIKTOK_WATCH": "true", "TIKTOK_THEIR_POSTS": "false", "TIKTOK_LIKE_SENT": "true", "TIKTOK_MENTIONS": "true",
          "TIKTOK_LIKES_PER_DAY": "12", "TIKTOK_VISITS": "true", "TIKTOK_VISIT_MINUTES": "7", "TIKTOK_VISIT_LINES": "2",
          "TIKTOK_FORYOU": "true", "TIKTOK_FORYOU_LIKE_PERCENT": "20", "TIKTOK_POSTS_PER_DAY": "2"}, env)
check("the panel's asks are the runner's ops",
      {k: v[0] for k, v in bridge._OUT_OPS.items() if k.startswith("tiktok_")} == {
          "tiktok_posts": "posts", "tiktok_action": "video", "tiktok_visit": "visit", "tiktok_leave": "leave",
          "tiktok_foryou": "foryou", "tiktok_out": "out", "tiktok_post": "post"}
      and bridge._OUT_OPS["tiktok_post"][1] >= 600)
# Each platform answers only its own asks, so tiktok_* on an Instagram account is refused rather than guessed at.
check("and a platform only takes its own", 'cmd.startswith(f"{P[\'key\']}_")' in read("app/platforms/snapchat_bridge.py"))
ctx = bridge._tiktok_dm_context("tt_theo-wav")
check("a TikTok DM gets their TikTok and what it saw today", "THEIR TIKTOK: @theo.wav" in ctx and "THINGS YOU SAW" in ctx)

# ── The panel ────────────────────────────────────────────────────────────────
print("\n== the panel ==")
os.environ["TIKTOK_USERNAME_1"] = "imprimante13"
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import chat_routes, tiktok_routes  # noqa: E402

panel = FastAPI()
panel.include_router(tiktok_routes.router)
panel.include_router(chat_routes.router)
client = TestClient(panel)
r = client.get("/api/tiktok/theirs", params={"target": "tiktok_1", "user_id": "tt_theo-wav"})
body = r.json() if r.status_code == 200 else {}
check("their posts for the TikToks tab, with what was seen", r.status_code == 200 and body.get("handle") == "theo.wav"
      and len(body.get("posts", [])) == 2 and body["posts"][1]["seen"] == "Theo films ducks on a pier."
      and body.get("verified") is True and body.get("newest") == "7500000000000000002", r.text[:300])
check("only a TikTok account's", client.get("/api/tiktok/theirs", params={"target": "discord_1", "user_id": "tt_x"}).status_code == 404)
check("only a TikTok person", client.get("/api/tiktok/theirs", params={"target": "tiktok_1", "user_id": "../x"}).status_code == 400)
check("a like needs a real video link", client.post("/api/tiktok/action", json={"target": "tiktok_1", "url": "https://evil.example/x",
                                                                            "action": "like"}).status_code == 400)
check("an action is one of three", client.post("/api/tiktok/action", json={
    "target": "tiktok_1", "url": "https://www.tiktok.com/@a/video/7500000000000000001", "action": "follow"}).status_code == 400)
check("a comment needs words", client.post("/api/tiktok/action", json={
    "target": "tiktok_1", "url": "https://www.tiktok.com/@a/video/7500000000000000001", "action": "comment",
    "text": "   "}).status_code == 400)
check("a visit needs a TikTok username", client.post("/api/tiktok/visit", json={"target": "tiktok_1",
                                                                              "handle": "no spaces!"}).status_code == 400)
info = client.get("/api/tiktok/posting").json()
check("posting: on, the TikTok accounts, everyone at first", info == {"enabled": True, "accounts": ["tiktok_1"],
                                                                      "privacy": "everyone"}, info)
check("only a video is posted", client.post("/api/tiktok/post", json={"target": "tiktok_1", "persona": "", "name": "a.jpg",
                                                                      "caption": "x"}).status_code == 400)
check("and never one outside its folder", client.post("/api/tiktok/post", json={
    "target": "tiktok_1", "persona": "", "name": "../../x.mp4", "caption": "x"}).status_code == 400)
chat_routes.apply_chat_event("tiktok_1", {"t": "visit_state", "on": True, "host": "mara_k", "name": "Mara", "why": "chats"})
chat_routes.apply_chat_event("tiktok_1", {"t": "visit", "event": "comment", "name": "zed", "text": "hi all", "host": "mara_k"})
chat_routes.apply_chat_event("tiktok_1", {"t": "visit_say", "to": "", "text": "hey mara!", "host": "mara_k"})
lv = client.get("/api/live/tiktok_1").json()
check("the LIVE view knows the LIVE it is visiting, and its chat", lv["visit"]["on"] and lv["visit"]["host"] == "mara_k"
      and [x["t"] for x in lv["visit"]["feed"]] == ["visit", "visit_say"] and lv["live"] is False, lv)
check("and the OBS page how to show its answers", lv.get("overlay") == {"seconds": 8, "position": "bottom", "comment": True,
                                                                         "size": "medium", "theme": "dark"}, lv.get("overlay"))
chat_routes.apply_chat_event("tiktok_1", {"t": "visit_state", "on": False, "host": "mara_k"})
check("and when it left", client.get("/api/live/tiktok_1").json()["visit"]["on"] is False)

# ── Read from the source ─────────────────────────────────────────────────────
print("\n== the runner and its bot ==")
bot_src = read("app/platforms/snapchat/tiktokbot.js")
run = read("app/platforms/snapchat/tiktok_runner.js")
core_src = read("app/platforms/snapchat/runner_core.js")
check("a tab of its own for going out, behaving as one in front", "async outPage()" in bot_src
      and 'send("Emulation.setFocusEmulationEnabled", { enabled: true })' in bot_src)
check("the side tab is dressed like the inbox (proxy, dialogs) and awake", "this.side = await this.newTab();" in bot_src
      and "await this.dress(page);\n    await this.awake(page);" in bot_src)
check("its own LIVE is looked for at its own address, not any LIVE", "includes(`/@${this.handle}/live`)" in bot_src)
for m in ("profilePosts(", "likeVideo(", "saveVideo(", "commentOnVideo(", "forYou()", "forYouNext()", "openLive(",
          "liveHearts(", "followLiveHost()", "followingLive()", "mentions()", "postVideo(", "resolveShared("):
    check(f"the bot can {m.rstrip('(')}", f"  async {m}" in bot_src or f"  {m}" in bot_src)
check("every outward action has a dry run", all(s in bot_src for s in ('(dry run) would have pressed', '(dry run) would have commented',
                                                                       '(dry run) would have posted', '(dry run) would have liked a For You')))
check("a shared card's link from the props its page drew it with", "const sharedOf = (el) =>" in bot_src
      and 'media.url = `https://www.tiktok.com/@${it.author || "i"}/video/${it.id}`;' in bot_src)
check("and by opening it when they do not say, never closing its own tabs", "!mine.includes(t)" in bot_src)
check("one job at a time in the out tab, the panel's first", "function outJob(name, fn)" in run and "if (outBusy) return false;" in run
      and "async function outNow(" in run and "outStop = true" in run)
check("long jobs stop when asked", "while (Date.now() < until && !outStop)" in run and run.count("!outStop") >= 2)
check("daily limits, kept across restarts", "createBudget(path.join(PEOPLE_DIR, `budget_${ACCOUNT}.json`)" in run
      and 'budget.allowed("likes")' in run and 'budget.allowed("comments")' in run and 'budget.allowed("visits")' in run
      and 'budget.allowed("foryou")' in run and 'budget.allowed("posts")' in run)
check("answers taken one at a time, never a stale copy written back", "core.take(id)" in run and "core.putBack(id" in run
      and "writeJson(core.files.responses" not in run and "function take(id)" in core_src)
snap_run = read("app/platforms/snapchat/snapchat_runner.js")
check("Snapchat's runner takes its replies the same way: one at a time, never a stale copy written back",
      "const val = takeResponse(msgId);" in snap_run and "putBackResponse(msgId," in snap_run
      and "writeJson(RESPONSES_FILE, responses)" not in snap_run)
check("answers with a pace of their own are left to their loops", 'const OWN_PACE = new Set(["live", "visit_say", "video_comment"]);' in run)
check("its own videos' comments wait while it is live (its LIVE has that tab)", "if (!COMMENTS || liveOn ||" in run)
check("every going-out switch is read", all(f'core.flag("{k}"' in run for k in (
    "WATCH", "THEIR_POSTS", "LIKE_SENT", "LIKE_THEIRS", "COMMENT_SENT", "COMMENT_THEIRS", "MENTIONS", "VISITS", "FORYOU"))
      and all(f'core.num("{k}"' in run for k in ("LIKES_PER_DAY", "COMMENTS_PER_DAY", "VISITS_PER_DAY", "FORYOU_SESSIONS",
                                                   "POSTS_PER_DAY", "VISIT_MINUTES", "VISIT_LINES")))
check("a mention already there when it started is its past", "if (first) continue;" in run.split("async function maybeMentions")[1])
check("a profile that would not read keeps what was known of their posts",
      "if (!posts.length) {" in run.split("async function maybeTheirPosts")[1].split("async function")[0])
check("in a LIVE it visits, its own lines are not taken for someone else's, by @handle or by name",
      "const mine = (r) => (r.handle && r.handle === HANDLE) || (!!ownName && r.name === ownName);" in run
      and "if (mine(r)) continue;" in run)
check("it never comments as @-tags in a visit, and leaves the stream", 'await bot.goto("about:blank", page)' in run)

print("\n== the panel's pages ==")
tt = read("webui/src/lib/components/TheirTikToks.svelte")
tools = read("webui/src/lib/components/ChatTools.svelte")
lv_src = read("webui/src/lib/accounts/LiveView.svelte")
card_src = read("webui/src/lib/accounts/AccountCard.svelte")
post_src = read("webui/src/lib/components/PostTikTok.svelte")
chip = read("webui/src/lib/components/UserChip.svelte")
pics = read("webui/src/pages/Pictures.svelte")
check("a TikToks tab beside a TikTok person's chat", 'platform === "tiktok" && uid.startsWith("tt_")' in tools
      and "<TheirTikToks {target} {uid} {them} />" in tools and 'toggleTools("tiktoks")' in read("webui/src/pages/Chats.svelte"))
check("each post can be liked, saved and commented, with a comment the persona can write",
      'act(p, "like")' in tt and 'act(p, "save")' in tt and "api.tiktokCommentText" in tt and 'api.tiktokAction(target, p.url, "comment", text)' in tt)
check("what one conversation asked for is never shown for another", "if (t !== target || u !== uid) return;" in tt)
check("the LIVE view shows the LIVE it is visiting, with Leave, Visit and For You",
      "In @${visit.host}'s LIVE" in lv_src and "api.tiktokLeave" in lv_src and "api.tiktokVisit" in lv_src and "api.tiktokForYou" in lv_src)
check("the account card says where it is", "In @${visiting}'s LIVE" in card_src and "is-visiting" in card_src)
check("the person card: followers, a verified tick, their latest posts", "followers(person.followers)" in chip
      and "uc-tick" in chip and "person.posts" in chip)
check("a video in the Pictures page can be posted", 'p.video && $socialsOn.tiktok !== false\n        && { label: "Post to TikTok…"' in pics
      and "<PostTikTok" in pics)
check("posting can be tried first, and the persona writes the caption", "dry_run: trial" in post_src and "api.tiktokCaption" in post_src)
for name, src in (("TheirTikToks", tt), ("LiveView", lv_src), ("PostTikTok", post_src), ("UserChip", chip)):
    check(f"{name}: sounds as you use it", "play(" in src)
    check(f"{name}: follows the Animations switch, never Windows'", ':root[data-motion="off"]' in src
          and "prefers-reduced-motion" not in src)
for rel in ("app/utils/tiktoksocial.py", "app/web/routes/tiktok_routes.py", "app/platforms/snapchat/tiktok_runner.js",
            "app/platforms/snapchat/tiktokbot.js", "webui/src/lib/components/TheirTikToks.svelte",
            "webui/src/lib/components/PostTikTok.svelte"):
    check(f"no em dashes in {rel.rsplit('/', 1)[1]}", "\u2014" not in read(rel))
routes_src = read("app/web/routes/tiktok_routes.py")
import re as _re  # noqa: E402
blocking = [m.group(1) for m in _re.finditer(r"async def (\w+)\([^)]*\):\n(?:(?!\n(?:@|def |async def )).)*?"
                                              r"(?<!to_thread\()(?:snappeople\.|tiktokwatch\.cached|\.read_text|open\()",
                                              routes_src, _re.S)]
check("no async route reads files on the shared loop", not blocking, blocking)

print("\n== settings ==")
for key in ("tiktok.watch.their_posts", "tiktok.engage.like_sent", "tiktok.engage.like_theirs", "tiktok.engage.comment_sent",
            "tiktok.engage.comment_theirs", "tiktok.engage.mentions", "tiktok.engage.likes_per_day",
            "tiktok.engage.comments_per_day", "tiktok.visits.enabled", "tiktok.visits.chats", "tiktok.visits.shared",
            "tiktok.visits.following", "tiktok.visits.stay_minutes", "tiktok.visits.lines_per_5min", "tiktok.visits.per_day",
            "tiktok.visits.follow_host", "tiktok.foryou.enabled", "tiktok.foryou.sessions_per_day", "tiktok.foryou.minutes",
            "tiktok.foryou.like_percent", "tiktok.share.enabled", "tiktok.posting.enabled", "tiktok.posting.per_day",
            "tiktok.posting.privacy"):
    check(f"{key}: typed, described, labelled and placed", f'"key": "{key}"' in schema and desc.count(f'"{key}": ') == 2
          and f'"{key}",' in smap)
import yaml  # noqa: E402

shipped = yaml.safe_load(read("resources/config.yaml"))["tiktok"]
check("everything public is off as shipped", not any([shipped["engage"][k] for k in ("like_sent", "like_theirs", "comment_sent",
                                                                                        "comment_theirs", "mentions")])
      and not shipped["visits"]["enabled"] and not shipped["foryou"]["enabled"] and not shipped["share"]["enabled"])
check("what is private stays on: watching, their posts; posting is by hand", shipped["watch"]["enabled"]
      and shipped["watch"]["their_posts"] and shipped["posting"]["enabled"])
restart = desc[desc.index("_NEEDS_RESTART = {"):desc.index("def section_for")]
check("what the runner reads needs a restart; what Python reads does not", '"tiktok.visits.enabled"' in restart
      and '"tiktok.engage.likes_per_day"' in restart and '"tiktok.watch.their_posts"' in restart
      and '"tiktok.share.enabled"' not in restart and '"tiktok.posting.enabled"' not in restart)
page_src = read("webui/src/pages/Settings.svelte")
check("its subs have icons, and who can watch has its choices", all(f' {k}: "' in page_src for k in ("watching", "engage", "visits",
                                                                                                  "foryou", "posting"))
      and '"tiktok.posting.privacy": [' in page_src)
check("Telegram: /visit and /foryou", '("visit",' in read("app/telegram_bot/commands.py")
      and 'CommandHandler("visit",' in read("app/telegram_bot/telegram_controller.py")
      and 'CommandHandler("foryou",' in read("app/telegram_bot/telegram_controller.py"))

shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
