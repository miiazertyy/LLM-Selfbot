"""Videos among the pictures.

Any kind of video goes in (a phone's MOV, an MKV, an AVI, a WebM...) and is
kept as an MP4 that Discord, Snapchat and every browser plays: H.264 and AAC,
the longest side at most 1280, at most 30 frames a second, and made smaller
when it is bigger than Settings allows (10 MB, Discord's limit without Nitro).
It is described from frames across it on one picture, with what is said in it,
so the bot can pick it when someone asks for a video. On the page a video
shows its still and how long it is, plays muted under the pointer and with its
sound when opened, and the drop zone says how far a conversion has got.

The face of a profile is cropped by hand: the picture behind a round window,
dragged and zoomed, cut out at 512px on this computer.
"""
import asyncio
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "src"
TMP = Path(tempfile.mkdtemp(prefix="llm-videos-"))
(TMP / "config" / "pictures").mkdir(parents=True, exist_ok=True)
(TMP / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(ROOT))

PASS, FAIL, SKIP = [], [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def skip(name, why):
    SKIP.append(name)
    print(f"  SKIP  {name}  ({why})")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from app.utils import videos  # noqa: E402

print("== what is a video ==")
check("a phone's MOV, an MKV, an AVI, a WebM and the rest are videos by their name",
      all(videos.is_video(f"clip{e}") for e in (".mov", ".MKV", ".avi", ".webm", ".wmv", ".3gp", ".ts", ".m4v", ".flv")))
check("a photo is not", not any(videos.is_video(f"p{e}") for e in (".jpg", ".png", ".heic", ".gif", ".webp", ".zip")))
check("an MP4 with no name is known by its first bytes", videos.sniff(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00"))
check("and a QuickTime one", videos.sniff(b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00"))
check("but a HEIC or an AVIF photo, in the same kind of box, is not",
      not videos.sniff(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00") and not videos.sniff(b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00"))
check("Matroska and WebM, AVI, FLV, WMV by their bytes",
      videos.sniff(b"\x1aE\xdf\xa3" + b"\x00" * 12) and videos.sniff(b"RIFF\x00\x00\x00\x00AVI LIST")
      and videos.sniff(b"FLV\x01\x05" + b"\x00" * 8) and videos.sniff(bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")))
check("a JPEG or a zip is not", not videos.sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 12) and not videos.sniff(b"PK\x03\x04" + b"\x00" * 12))
check("a file sent with no extension is still found by its bytes",
      videos.is_video("upload", b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00"))
check("only an MP4 is kept", videos.is_kept_video("IMG_3.mp4") and not videos.is_kept_video("IMG_3.mov"))

print("\n== how big one may be ==")
check("10 MB unless Settings says otherwise, with room to spare", videos.max_bytes({}) == 9_600_000)
check("Settings' largest video", videos.max_bytes({"bot": {"pictures": {"video_max_mb": 25}}}) == 24_000_000)
check("never under 1 MB", videos.max_bytes({"bot": {"pictures": {"video_max_mb": 0.1}}}) == 960_000)
schema = read("app/web/schema.py")
check("the setting is in Settings, 1 to 500 MB", '"bot.pictures.video_max_mb"' in schema and '"Largest video"' in schema
      and '"max": 500' in schema.split('"bot.pictures.video_max_mb"')[1].split("}")[0])
check("described plainly", "Discord takes 10 MB without Nitro." in read("app/web/descriptions.py"))
check("and on a dial with its unit, in the Pictures and voice section",
      '"bot.pictures.video_max_mb": { one: "MB", many: "MB", hint: "per video, at most" }' in read("webui/src/pages/Settings.svelte")
      and '"bot.pictures.video_max_mb",' in read("webui/src/lib/settingsmap.ts"))
check("config.yaml has it", "video_max_mb: 10" in read("resources/config.yaml"))

print("\n== what is heard in it ==")
check("words are kept", videos.heard("  hey   look at the  sea ") == "hey look at the sea")
check("a music note or a syllable is not", videos.heard("♪ ♪") == "" and videos.heard("uh") == "")
check("a long one is cut at a word", len(videos.heard("word " * 200)) <= 300 and videos.heard("word " * 200).endswith("..."))
msgs = videos.describe_messages("data:image/jpeg;base64,AAAA", "we made it to the top")
text = msgs[0]["content"][0]["text"]
check("the model is told it is frames in order, and asked for a caption",
      "frames from one short video, in order" in text and "under 40 words" in text)
check("with what is said in it", 'What is said in it: "we made it to the top"' in text)
check("and the picture of the frames", msgs[0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg"))
check("nothing said, nothing added", "What is said" not in videos.describe_messages("data:x", "")[0]["content"][0]["text"])

print("\n== converting, with ffmpeg ==")
HAVE = videos.available()
if not HAVE:
    for n in ("converted", "smaller", "too long", "frames", "sound", "the route"):
        skip(n, "no ffmpeg on this machine")
else:
    ffmpeg, ffprobe = videos.tools()
    work = TMP / "work"
    work.mkdir()

    def make(name, args):
        path = work / name
        out = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", *args, str(path)], capture_output=True, timeout=180)
        assert out.returncode == 0, out.stderr.decode(errors="replace")[-400:]
        return path

    # A 1080p, 60 frames a second, MOV with sound, the way a phone makes one.
    phone = make("phone.mov", ["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60:duration=3",
                               "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                               "-c:v", "mpeg4", "-q:v", "4", "-c:a", "pcm_s16le", "-shortest"])
    steps = []
    info = videos.convert(phone, work / "out.mp4", 9_600_000, progress=steps.append)
    p = videos.probe(work / "out.mp4")
    check("a MOV becomes an MP4", (work / "out.mp4").read_bytes()[4:8] == b"ftyp")
    check("H.264, at most 1280 wide and 30 frames a second",
          p["codec"] == "h264" and max(p["width"], p["height"]) <= 1280 and p["fps"] <= 30.5, str(p))
    check("with its sound", p["audio"] and info["audio"])
    check("as long as it was", abs(info["duration"] - 3) < 0.3, str(info))
    check("not made smaller when it fits", info["smaller"] is False and info["size"] < 9_600_000)
    check("how far it has got is said as it goes, ending at 100", steps and steps[-1] == 100 and steps == sorted(steps), str(steps[:8]))
    moov = (work / "out.mp4").read_bytes()
    check("it starts playing before it has all arrived (moov first)", 0 <= moov.find(b"moov") < moov.find(b"mdat"))

    # Noise does not compress: far over a 1 MB limit at first.
    noisy = make("noisy.mkv", ["-f", "lavfi", "-i", "nullsrc=size=1280x720:rate=30:duration=4,geq=random(1)*255:128:128",
                               "-f", "lavfi", "-i", "anoisesrc=duration=4", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
                               "-c:a", "aac", "-shortest"])
    info = videos.convert(noisy, work / "small.mp4", 1_000_000)
    check("one too big is made smaller, to fit", info["smaller"] and info["size"] <= 1_000_000, str(info))

    long = make("long.webm", ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=120",
                              "-c:v", "libvpx", "-b:v", "50k", "-deadline", "realtime"])
    try:
        videos.convert(long, work / "long.mp4", 300_000)
        check("one too long for the size says so", False, "no error")
    except videos.VideoError as e:
        check("one too long for the size says so, and how long would fit", str(e).startswith("Too long to send at")
              and "fit" in str(e) and "Settings" in str(e), str(e))
    check("and leaves nothing half made behind", not list(work.glob(".*.part.mp4")) and not (work / "long.mp4").exists())

    rotated = make("tall.mov", ["-f", "lavfi", "-i", "testsrc2=size=360x640:rate=25:duration=1", "-c:v", "libx264"])
    p = videos.probe(rotated)
    check("its size is read the way it is shown", (p["width"], p["height"]) == (360, 640), str(p))

    from PIL import Image
    sheet = videos.sheet(work / "out.mp4")
    im = Image.open(io.BytesIO(sheet))
    check("its frames on one picture, three across and two down", im.format == "JPEG" and im.width > im.height, str(im.size))
    one = videos.sheet(make("blink.mp4", ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=0.3", "-c:v", "libx264"]))
    check("a blink of a video still gives a frame", Image.open(io.BytesIO(one)).format == "JPEG")
    still = videos.poster(work / "out.mp4", work / "poster.jpg")
    check("a still to show before it plays", Image.open(still).format == "JPEG" and Image.open(still).width == 640)
    heard = videos.sound(work / "out.mp4")
    check("its sound, small, for transcribing", heard is not None and heard[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
          and len(heard) < 200_000)
    check("none from a video with no sound", videos.sound(rotated) is None)
    try:
        videos.probe(make("beep.mp3", ["-f", "lavfi", "-i", "sine=duration=1"]))
        check("sound only is refused", False)
    except videos.VideoError as e:
        check("sound only is refused, plainly", "no picture" in str(e), str(e))

    print("\n== the route ==")
    from app.utils.db import init_db
    init_db()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.web.routes import media_routes

    told = []

    async def fake_describe(name, data, ext, client_index=None, video=False, sound=None):
        told.append({"name": name, "ext": ext, "video": video, "sound": bool(sound), "sheet": data[:3] == b"\xff\xd8\xff"})
        return "Someone waving at the sea.", ""
    media_routes._describe = fake_describe

    app = FastAPI()
    app.include_router(media_routes.router)
    c = TestClient(app)
    r = c.post("/api/pictures", files={"file": ("Beach day.MOV", phone.read_bytes(), "video/quicktime")}).json()
    check("a MOV goes in as the next number, an MP4", r.get("name") == "IMG_1.mp4" and r.get("video") is True, str(r))
    check("and is described", r.get("description") == "Someone waving at the sea.")
    check("from its frames on one picture, with its sound", told and told[-1]["video"] and told[-1]["sheet"]
          and told[-1]["sound"] and told[-1]["ext"] == ".jpg", str(told))
    listed = c.get("/api/pictures").json()["pictures"]
    v = listed[0] if listed else {}
    check("it is listed as a video, how long it is, and moving (so no filter goes on it)",
          v.get("video") is True and abs(v.get("duration", 0) - 3) < 0.3 and v.get("moving") is True, str(v))
    poster = c.get(f"/api/pictures/id/{v.get('id')}/poster")
    check("its still is served by its id, kept for good", poster.status_code == 200
          and poster.headers.get("content-type") == "image/jpeg" and "immutable" in poster.headers.get("cache-control", ""))
    played = c.get(f"/api/pictures/id/{v.get('id')}")
    check("and the video itself, as an MP4", played.status_code == 200 and played.headers.get("content-type") == "video/mp4")
    st = c.get("/api/pictures/status").json()
    check("the status says how far a conversion has got, idle now",
          st.get("video") == {"active": False, "name": "", "percent": 0, "step": ""}, str(st.get("video")))
    png = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 80)).save(png, "PNG")
    c.post("/api/pictures", files={"file": ("a.png", png.getvalue(), "image/png")})
    check("a picture after it takes the next number", any(n.startswith("IMG_2") for n in os.listdir(TMP / "config" / "pictures")))
    r = c.post("/api/pictures/look", json={"items": [{"name": "IMG_1.mp4", "id": v.get("id")}], "look": "warm", "strength": 0.5}).json()
    check("a filter is refused on a video", "videos can't take a filter" in str(r), str(r)[:200])
    r = c.post("/api/pictures", files={"file": ("x.mkv", b"\x1aE\xdf\xa3" + b"garbage" * 40, "video/x-matroska")})
    check("a broken video is refused with a reason", r.status_code == 400 and r.json().get("detail"), r.text[:200])
    c.delete(f"/api/pictures/IMG_1.mp4?id={v.get('id')}")
    check("deleting it takes its still too", not list((media_routes.POSTERS_DIR).glob(f"{v.get('id')}*")))

    # A zip with a video in it: converted too.
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("trip/clip.avi", make("clip.avi", ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=1",
                                                      "-c:v", "mpeg4"]).read_bytes())
    r = c.post("/api/pictures", files={"file": ("trip.zip", buf.getvalue(), "application/zip")}).json()
    check("a video in a zip goes in as an MP4", any(n.endswith(".mp4") for n in r.get("added", [])), str(r))

print("\n== the bot sends one when asked ==")
from app.utils import pictures as P  # noqa: E402
check("asked for a video", P.is_video_request("send me a video of you") and P.is_video_request("can u send a vid"))
check("and in French", P.is_video_request("envoie moi une vidéo"))
check("a video call is not a video", not P.is_video_request("wanna video call later?") and not P.is_video_request("facetime me"))
check("a photo is not a video", not P.is_video_request("send me a pic"))
check("videos are picked among videos, pictures among pictures", P.is_video_file("IMG_4.mp4") and not P.is_video_file("IMG_4.jpg"))
engine = read("app/core/engine.py")
check("the engine asks for a video before a photo", "wants_video = is_video_request(msg.content)" in engine
      and "elif not wants_video and is_picture_request(msg.content)" in engine and "video=True" in engine)
runner = read("app/platforms/discord_runner.py")
check("Discord picks among its videos when a video is asked for", 'exts = {".mp4"} if video else' in runner)
snap = read("app/platforms/snapchat/snapbot.js")
check("Snapchat sends one through the file input that takes videos", "isVideo" in snap and "video" in snap)
check("every gallery list counts videos, so numbers never clash",
      runner.count('".webp", ".mp4"}') >= 4 and '".webp", ".mp4"}' in read("app/platforms/snapchat_bridge.py")
      and '".webp", ".mp4"}' in read("app/utils/personas.py") and '".webp", ".mp4"}' in read("app/cogs/management.py"))
tg = read("app/telegram_bot/telegram_controller.py")
check("Telegram's /imagels shows a video as a video", "reply_video" in tg and "InputMediaVideo" in tg)

print("\n== the page ==")
page = read("webui/src/pages/Pictures.svelte")
lib = read("webui/src/lib/pictures.ts")
api = read("webui/src/lib/api.ts")
check("videos can be dropped, picked and pasted", "Drop pictures, videos or a zip here, or paste one" in page
      and "video/*" in page and 'i.type.startsWith("video/")' in page and "VIDEO_EXTS.join" in page)
check("the page knows every kind the server takes", all(e in lib for e in ('".mov"', '".mkv"', '".avi"', '".webm"', '".gifv"')))
check("a video's card shows its still", "api.pictureSmall(p, 480, who)" in page and "/poster`" in api
      and 'still = POSTERS_DIR / f"{pid}.jpg"' in read("app/web/routes/media_routes.py"))
check("plays muted under the pointer, from its still", "muted autoplay loop playsinline" in page and "live === keyOf(p)" in page)
check("with a play mark and how long it is", 'class="pc-play"' in page and "clock(p.duration)" in page)
check("opened, it plays with its sound and its controls",
      "controls autoplay loop playsinline" in read("webui/src/lib/components/PictureViewer.svelte"))
check("a video is never offered a filter or the clipboard", "!p.video && { label: \"Copy image\"" in page)
check("how long reads like a player", "export function clock" in lib)
check("the drop zone says it converts, then watches", "Converting <b" in page and "Watching <b" in page and "to describe it" in page)
check("the ring fills with the conversion, and turns while it watches", "ringPct" in page and "ringSpin" in page)
check("a click as it is converted, a glint as it lands", 'play("slot"' in page and 'play("glint"' in lib)
check("one made smaller says so", "made smaller to" in lib)
check("Big Picture and search show a video's still", "pictureThumb" in read("webui/src/lib/bigpicture/BigPicture.svelte")
      and "pictureThumb" in read("webui/src/lib/search.ts"))
check("the face picker and the filter samples leave videos out", "!x.moving" in read("webui/src/lib/personas/FacePicker.svelte")
      and "!p.moving" in read("webui/src/lib/components/PicturesPanel.svelte"))
check("motion off: the preview fades in and the mark shrinks without moving",
      ':global(:root[data-motion="off"]) .pc-live { animation: none; }' in page
      and ':global(:root[data-motion="off"]) .pc-play { transition: none; }' in page)

print("\n== a profile's face, cropped by hand ==")
crop = read("webui/src/lib/personas/FaceCrop.svelte")
# The face is picked in a small panel beside it (FacePicker.svelte), the crop inside it.
prof = read("webui/src/lib/personas/FacePicker.svelte")
check("a picture picked or uploaded opens the crop first", "onclick={() => pick(pic)}" in prof and "URL.createObjectURL(file)" in prof
      and "<FaceCrop" in prof)
check("behind a round window in the profile's colour", "color={colorOf(p)}" in prof and "fc-window" in crop
      and "var(--fc)" in crop)
check("dragged to move it, with a pinch, the wheel, the slider or the keys to zoom",
      "onpointerdown={onDown}" in crop and "pointers.size >= 2" in crop and '"wheel", onWheel, { passive: false }' in crop
      and 'type="range"' in crop and "ArrowLeft: [-step, 0]" in crop and 'e.key === "+"' in crop)
check("zoom keeps the point under the pointer where it is", "function zoomTo(nextSide: number, px" in crop)
check("pulled past an edge it gives and springs back", "GIVE" in crop and 'play(pulled ? "settle" : "release"' in crop)
check("thirds to line a face up by, only while it moves", ".fc-stage.is-drag .fc-thirds { opacity: 1; }" in crop)
check("the face as it will look, large and small", "fc-face is-big" in crop and "fc-face is-small" in crop)
check("cut out at 512px on this computer, and sent as an upload", "const OUT = 512" in crop and "c.toBlob(r, \"image/jpeg\", 0.92)" in crop
      and "api.uploadPersonaAvatar(pid, file)" in prof)
check("one the browser cannot open is sent as it is", "onfail" in crop and "async function cropFailed" in prof)
check("a tall picture starts a little above the middle", "(h - side) * 0.22" in crop)
check("sounds: grabbed, let go, zoomed by notches, started again",
      'play("grab"' in crop and 'play("tick", { level: 0.28' in crop and 'play("undo"' in crop and 'play("slide")' in prof)
check("a file's address is let go when it closes", "URL.revokeObjectURL(crop.src)" in prof)
check("plain words", "Drag to move it. Scroll or slide to zoom." in crop and ">Use this<" in crop and "How it shows" in crop)
check("motion off", ':global(:root[data-motion="off"]) .fc,' in crop and ':global(:root[data-motion="off"]) .fc-face img,' in crop)
check("a minus to zoom out with", 'minus: "M5 12h14"' in read("webui/src/lib/components/Icon.svelte"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed" + (f", {len(SKIP)} skipped" if SKIP else ""))
sys.exit(1 if FAIL else 0)
