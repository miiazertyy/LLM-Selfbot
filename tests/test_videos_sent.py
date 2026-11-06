"""Videos people send, watched on every platform (app/utils/videowatch.py).

Run for real, in a throwaway data folder (the vision and speech models stood in for):
  * a video's bytes watched: frames from across it and its sound, how long it is; once per video (kept by its
    content), never two of the same at once
  * frames a page gave instead of the file (a snap's player), looked at as a video's
  * a file on disk, and one too big or gone; a link downloaded (a Discord attachment)
  * Spotlights: their links in a message, what their public page says (creator, counts, title, the video), watched
  * the note the model gets: what happens, what is said, and saying so when it would not play
  * Discord: a video attachment told from a picture, by its type or its name on Discord's CDN
  * the bridge: a captured video watched, its still dropped once it was; nothing said when it would not play and
    there is a still

Read from the source: Discord's reply path, Snapchat's runner and bot (the video itself, or frames by seeking, a
snap's video, Spotlight links), TikTok's (a video in a chat), and the settings.
"""
import ast
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="llmbot_videos_"))
(DATA / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from app.utils import videos, videowatch  # noqa: E402

# The vision and speech models, stood in for: what they were asked, and an answer.
asked = {"caption": 0, "heard": 0}


async def fake_caption(board, said="", kind="video"):
    asked["caption"] += 1
    return f"A test pattern moves across the screen{' while someone talks' if said else ''}."


async def fake_heard(sound):
    asked["heard"] += 1
    return "one two three, testing"


videowatch.caption = fake_caption
videowatch.heard = fake_heard

print("== settings ==")
check("on, listening, up to three minutes, as shipped", videowatch.settings() == {"enabled": True, "listen": True,
                                                                                   "max_seconds": 180})

print("\n== watching a video ==")
clip = None
if not videos.available():
    print("  SKIP  needs ffmpeg")
else:
    ffmpeg = videos.tools()[0]
    work = Path(tempfile.mkdtemp(prefix="vw_"))
    clip = work / "clip.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=15",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "4", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)], check=True, capture_output=True)
    blob = clip.read_bytes()

    async def twice():
        return await asyncio.gather(videowatch.watch_bytes(blob), videowatch.watch_bytes(blob))

    a, b = asyncio.run(twice())
    check("what happens and what is said, and how long it is", a and a["seen"].startswith("A test pattern")
          and a["said"] == "one two three, testing" and 3.5 < a["duration"] < 4.5, a)
    check("the same video sent twice at once is watched once", asked["caption"] == 1 and asked["heard"] == 1 and a == b)
    c = asyncio.run(videowatch.watch_bytes(blob))
    check("and kept for next time", asked["caption"] == 1 and c["seen"] == a["seen"])
    from app.utils import helpers
    import yaml
    cfg_path = DATA / "config" / "config.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    raw["bot"]["videos"]["listen"] = False
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    helpers.invalidate_config_cache()
    quiet = asyncio.run(videowatch.watch_bytes(blob + b"\0"))
    check("not listened to when listening is off", quiet and quiet["said"] == "" and asked["heard"] == 1)
    raw["bot"]["videos"]["enabled"] = False
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    helpers.invalidate_config_cache()
    check("nothing watched when watching is off", asyncio.run(videowatch.watch_bytes(blob + b"\0\0")) is None)
    raw["bot"]["videos"].update(enabled=True, listen=True)
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    helpers.invalidate_config_cache()
    f = asyncio.run(videowatch.watch_file(clip))
    check("a file on this computer", f and f["seen"].startswith("A test pattern"))
    check("one that is not there: nothing", asyncio.run(videowatch.watch_file(work / "gone.mp4")) is None)
    was = videowatch.MAX_BYTES
    videowatch.MAX_BYTES = 100
    check("one too big: nothing", asyncio.run(videowatch.watch_file(clip)) is None)
    videowatch.MAX_BYTES = was
    frames = [videos.frame(clip, t, 200) for t in (0.5, 1.5, 2.5, 3.5)]
    fw = asyncio.run(videowatch.watch_frames(frames))
    check("frames a page gave are looked at as a video's, with no sound to hear", fw and fw["frames"] == 4
          and fw["said"] == "" and fw["seen"])
    check("garbage is not a video", asyncio.run(videowatch.watch_bytes(b"not a video at all" * 300)) is None
          or not asyncio.run(videowatch.watch_bytes(b"not a video at all" * 300)).get("seen"))
    left = list(Path(tempfile.gettempdir()).glob("llmselfbot-watch-*"))
    check("nothing is left behind", not left, str(left[:3]))
    kept = list(videowatch.cache_dir().glob("*.json"))
    check("what was seen is kept by the video's content", any(p.stem == __import__("hashlib").sha1(blob).hexdigest()
                                                              for p in kept))

print("\n== a link to a video (a Discord attachment) ==")
if clip is not None:
    served = {}

    async def fake_download(url, limit=videowatch.MAX_BYTES, headers=None):
        served["url"] = url
        return clip.read_bytes()

    real_download = videowatch.download
    videowatch.download = fake_download
    w = asyncio.run(videowatch.watch_url("https://cdn.discordapp.com/attachments/1/2/IMG_0412.MOV?ex=1&is=2&hm=3"))
    check("downloaded and watched, its kind from its name", w and w["seen"] and served["url"].endswith("hm=3"))
    videowatch.download = real_download

print("\n== Spotlights ==")
links = videowatch.spotlight_links("look https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYY21oam91Z3Z0AaE. "
                                   "and https://snapchat.com/t/AbCd1234 and https://story.snapchat.com/spotlight/W7_EDl12345")
check("its links, as they are shared", links == ["https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYY21oam91Z3Z0AaE",
                                                 "https://snapchat.com/t/AbCd1234",
                                                 "https://story.snapchat.com/spotlight/W7_EDl12345"], links)
check("not any snapchat link", videowatch.spotlight_links("https://www.snapchat.com/add/someone https://snapchat.com") == [])
PAGE = ('<html><head><link rel="canonical" href="https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPw"/>'
        '<meta property="og:title" content="1.2K likes, 14 comments, and 8 shares | Ella Shares a Sunny Day | '
        'Ella Morgan (@thisisellacat) | Date"/>'
        '<meta property="og:description" content="A relaxed moment outdoors on a sunny day."/>'
        '<meta property="og:video" content="https://cf-st.sc-cdn.net/d/JYpQj9.27.IRZXSOY?mo=Gl8&amp;uc=1"/></head></html>')
sf = videowatch.spotlight_facts(PAGE, "https://snapchat.com/t/AbCd1234")
check("its page says whose, how it is doing, what it is called, and where its video is",
      (sf["creator"], sf["name"], sf["likes"], sf["comments"], sf["shares"], sf["title"])
      == ("thisisellacat", "Ella Morgan", 1200, 14, 8, "Ella Shares a Sunny Day")
      and sf["video"] == "https://cf-st.sc-cdn.net/d/JYpQj9.27.IRZXSOY?mo=Gl8&uc=1" and sf["id"] == "W7_EDlXWTBiXAEEniNoMPw", sf)
check("a page that says nothing: nothing", videowatch.spotlight_facts("<html></html>") == {})
summary = videowatch.spotlight_summary(dict(sf, seen="A woman sunbathes beside her dog.", said="", duration=6))
check("the note: by whom, how long, how it is doing, what happens", summary.startswith(
    "[You watched the Spotlight they shared: by @thisisellacat (Ella Morgan), 6 seconds long, 1200 likes, 14 comments, 8 shares.")
      and 'It is called "Ella Shares a Sunny Day".' in summary and "What happens in it: A woman sunbathes" in summary, summary)
check("not watched: what Snapchat says of it, and nothing to react to", "Snapchat says of it: A relaxed moment"
      in videowatch.spotlight_summary(sf) and "React" not in videowatch.spotlight_summary(sf))

print("\n== the note the model gets ==")
n = videowatch.note({"seen": "A dog jumps into a lake.", "said": "go on, fetch", "duration": 12.4})
check("what happens and what is said in it, and to react to it",
      n == '[You watched the video they sent you (12 seconds long). What happens in it: A dog jumps into a lake. What is '
           'said in it: "go on, fetch". React to it like someone who just watched it; do not describe it back to them.]', n)
check("frames only: said to have no sound", "(no sound)" in videowatch.note({"seen": "x", "frames": 4}))
check("one that would not play is said so, not pretended", videowatch.note(None)
      == "[The video they sent you would not play for you, so you have not seen it.]")


async def fake_spot(url):
    return dict(sf, seen="A woman sunbathes beside her dog.", duration=6)

real_spot = videowatch.spotlight
videowatch.spotlight = fake_spot
text, cover, watched = asyncio.run(videowatch.enrich_links("lol https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPw"))
check("a Spotlight in a message goes in with it", text.startswith("lol https://") and "[You watched the Spotlight" in text
      and watched and cover == "")
from app.utils import ai  # noqa: E402


async def realtime():
    token = ai.REALTIME.set(True)
    try:
        return await videowatch.enrich_links("https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPw")
    finally:
        ai.REALTIME.reset(token)

check("a LIVE line never waits for one", asyncio.run(realtime())[2] is False)
videowatch.spotlight = real_spot

print("\n== Discord ==")
dr = read("app/platforms/discord_runner.py")
tree = ast.parse(dr)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_video_attachment_url")
ns = {"os": os}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "discord_runner.py", "exec"), ns)
video_url = ns["_video_attachment_url"]


class Att:
    def __init__(self, url, ctype):
        self.url, self.content_type = url, ctype


class Msg:
    def __init__(self, *atts):
        self.attachments = list(atts)


mov = "https://cdn.discordapp.com/attachments/1/2/IMG_0412.MOV?ex=1"
png = "https://cdn.discordapp.com/attachments/1/2/pic.png?ex=1"
check("a video they attached, by its type", video_url(Msg(Att(mov, "video/quicktime")), mov) == mov)
check("a picture is not one", video_url(Msg(Att(png, "image/png")), png) == "")
check("an earlier message's, by its name on Discord's CDN", video_url(Msg(), mov) == mov
      and video_url(Msg(), png) == "")
check("not a video elsewhere, nor nothing", video_url(Msg(), "https://example.com/a.mp4") == "" and video_url(Msg(), None) == "")
check("watched in the reply path, not handed to the picture model", "_sent_video = _video_attachment_url(message, image_url)" in dr
      and "await videowatch.watch_url(_sent_video)" in dr and "image_url = None" in dr.split("_sent_video = ", 1)[1][:200])
check("and TikToks and Spotlights linked, the same way", '"snapchat.com" in (prompt or "")' in dr
      and "await videowatch.enrich_links(prompt)" in dr)
check("a video in its history says so", 'return "[video]" if any(t.startswith("video/") for t in types)' in dr)

print("\n== the bridge (Snapchat, TikTok) ==")
os.environ["BRIDGE_PLATFORM"] = "snapchat"
import app.platforms.snapchat_bridge as bridge  # noqa: E402

if clip is not None:
    note, watched = asyncio.run(bridge._watch_sent(f"file://{clip}", []))
    check("a video the runner captured is watched", watched and note.startswith("[You watched the video they sent you"))
    fdir = Path(tempfile.mkdtemp(prefix="vwf_"))
    paths = []
    for i, t in enumerate((0.7, 1.9, 3.1)):
        p = fdir / f"f{i}.jpg"
        p.write_bytes(videos.frame(clip, t, 180))
        paths.append(f"file://{p}")
    note, watched = asyncio.run(bridge._watch_sent(None, paths))
    check("frames, when the page would not give the file", watched and "(no sound)" in note)
    note, watched = asyncio.run(bridge._watch_sent("file://" + str(fdir / "gone.mp4"), [], has_still=True))
    check("one that would not play, with a still of it: nothing said, the still stands", (note, watched) == ("", False))
    note, watched = asyncio.run(bridge._watch_sent("file://" + str(fdir / "gone.mp4"), []))
    check("and with no still: said so", note.startswith("[The video they sent you would not play") and not watched)
bs = read("app/platforms/snapchat_bridge.py")
check("the bridge hands what was captured to the watcher, and drops the still once it was watched",
      'video_url = entry.get("video_url")' in bs and 'entry.get("frames")' in bs
      and "if watched:\n                    image_url = None" in bs)
check("a video from a TikTok chat reads as a video in the log", bridge._body_of({"kind": "clip", "text": ""})["text"] == "[video]")

print("\n== Snapchat's runner and bot ==")
sb = read("app/platforms/snapchat/snapbot.js")
sr = read("app/platforms/snapchat/snapchat_runner.js")
check("a video in the chat: the file itself, from inside the page", "async extractInlineVideo(chatId, name)" in sb
      and "async _videoFile(src, name)" in sb and "await fetch(src)" in sb.split("async _videoFile", 1)[1])
check("or frames across it, seeked to each, when the page will not give the file",
      "async _videoFrames(selector, name, count = 4)" in sb and "v.currentTime = t" in sb)
check("a video snap's video too, beside its still", "this.lastSnapVideo = { video: file };" in sb
      and "this.lastSnapVideo = { frames };" in sb)
check("only what came after its last reply, each once", sb.count("compareDocumentPosition") >= 5
      and "this._seenVideo.has(info.key)" in sb)
check("Spotlights by the links their cards carry", "async extractSpotlightLinks(chatId)" in sb
      and "snapchat\\.com\\/(spotlight\\/|t\\/)" in sb)
check("the runner hands them over: the video, its frames, the Spotlight's link with their words",
      "video_url: videoFilePath ? `file://${videoFilePath}` : undefined," in sr
      and "frames: framePaths.length ? framePaths.map((p) => `file://${p}`) : undefined," in sr
      and "...spotlights].filter(Boolean)" in sr)
check("a video alone is said to be one", '"🎬 sent a video"' in sr)

print("\n== TikTok's runner and bot ==")
tb = read("app/platforms/snapchat/tiktokbot.js")
tr = read("app/platforms/snapchat/tiktok_runner.js")
check("a video in a TikTok chat (not a shared TikTok)", 'else if (node.querySelector("video")) { kind = "clip"; media.video = true; }' in tb
      and "async captureVideo(stem)" in tb and "!x.closest(shared)" in tb)
check("captured and handed over to be watched", 'video = await bot.captureVideo(`tiktok_${ACCOUNT}_video`)' in tr
      and "video_url: video ? `file://${video}` : undefined," in tr and 'said = m.text || "[sent a video]"' in tr)

print("\n== settings ==")
smap = read("webui/src/lib/settingsmap.ts")
check("in one place, for every platform", 'id: "videos",\n        name: "Videos they send",' in smap)
for rel in ("app/utils/videowatch.py", "tests/test_videos_sent.py"):
    check(f"no em dashes in {rel.rsplit('/', 1)[1]}", chr(0x2014) not in read(rel))

shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
