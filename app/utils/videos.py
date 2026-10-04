"""Videos among the pictures (app/web/routes/media_routes.py): any kind in, an MP4 out that Discord, Snapchat and
every browser plays, made smaller when it is too big to send, and what happens in it put into words from a handful
of its frames, with what is said in it when something is.

ffmpeg and ffprobe do the work. app/utils/binaries.py finds them, and fetches them on Windows (the System page)."""
import io
import json
import math
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.utils import binaries
from app.utils.procs import quiet_kwargs

# Every kind a phone, a camera, a screen recorder or an old download makes: each one becomes an MP4.
VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".qt", ".webm", ".mkv", ".avi", ".wmv", ".asf", ".flv", ".f4v", ".3gp", ".3g2",
    ".mpg", ".mpeg", ".mpe", ".m2v", ".ts", ".mts", ".m2ts", ".vob", ".ogv", ".dv", ".mxf", ".rm", ".rmvb",
    ".divx", ".xvid", ".hevc", ".h264", ".h265", ".264", ".265", ".y4m", ".nut", ".gifv",
}
# How one is kept: H.264 video and AAC sound in an MP4, which everything plays.
KEPT_EXT = ".mp4"
# Discord takes 10 MB without Nitro: one bigger is made smaller to fit (bot.pictures.video_max_mb).
DEFAULT_MAX_MB = 10
# The longest side it is kept at: as sharp as a phone shows it in a chat, at a fraction of the bytes of 4K.
MAX_SIDE = 1280
MAX_FPS = 30
# Under this many kilobits a second of picture it is mush: too long for the size it has to fit in.
MIN_VIDEO_KBPS = 90


class VideoError(ValueError):
    """What to tell the person: no ffmpeg, not a video, too long to fit."""


# ── What a file is ────────────────────────────────────────────────────────────

# The brands of an ISO media file (MP4, MOV, 3GP) that are pictures, not videos: HEIC and AVIF photos.
_IMAGE_BRANDS = {b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis", b"jpeg"}


def sniff(head: bytes) -> bool:
    """A video by its first bytes, whatever it is called: for a file sent with no extension, or the wrong one."""
    if len(head) < 12:
        return False
    if head[4:8] == b"ftyp":
        return head[8:12] not in _IMAGE_BRANDS
    if head[:4] == b"\x1aE\xdf\xa3":                      # Matroska, WebM
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return True
    if head[:3] == b"FLV":
        return True
    if head[:4] == b"\x00\x00\x01\xba":                  # MPEG program stream
        return True
    if head[:4] == bytes.fromhex("3026b275"):            # ASF, WMV
        return True
    if head[:4] == b".RMF":
        return True
    return False


def is_video(name: str, head: bytes = b"") -> bool:
    ext = os.path.splitext(name or "")[1].lower()
    if ext in VIDEO_EXTS:
        return True
    return sniff(head)


def is_kept_video(name: str) -> bool:
    """One of the pictures that is a video (they are all kept as MP4)."""
    return os.path.splitext(name or "")[1].lower() == KEPT_EXT


# ── The tools ─────────────────────────────────────────────────────────────────

def tools() -> tuple[str, str]:
    ffmpeg, ffprobe = binaries.find("ffmpeg"), binaries.find("ffprobe")
    if not ffmpeg or not ffprobe:
        raise VideoError("Videos need ffmpeg. Get it on the System page, then add the video again.")
    return ffmpeg, ffprobe


def available() -> bool:
    return bool(binaries.find("ffmpeg") and binaries.find("ffprobe"))


def _run(args: list, timeout: float, data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=data, capture_output=True, timeout=timeout, **quiet_kwargs())


def probe(path) -> dict:
    """How long it is, its size on screen, its frame rate, and whether it has sound."""
    _, ffprobe = tools()
    try:
        out = _run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], 60)
        info = json.loads(out.stdout or b"{}")
    except (subprocess.TimeoutExpired, ValueError):
        raise VideoError("That video could not be read.")
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None:
        raise VideoError("There is no picture in that file: it is sound only, or not a video.")
    duration = _num((info.get("format") or {}).get("duration")) or _num(video.get("duration"))
    fps = 0.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = str(video.get(key) or "").partition("/")
        if _num(num) and _num(den):
            fps = _num(num) / _num(den)
            break
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    # A phone films sideways and says so: the picture is turned as it is converted, so it is the other way round.
    rotation = 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(_num(side["rotation"]))
    rotation = rotation or int(_num((video.get("tags") or {}).get("rotate")))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return {
        "duration": duration,
        "width": w,
        "height": h,
        "fps": fps,
        "audio": any(s.get("codec_type") == "audio" for s in streams),
        "codec": video.get("codec_name") or "",
    }


def _num(value) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else 0.0
    except (TypeError, ValueError):
        return 0.0


# ── Converting, and making it smaller ─────────────────────────────────────────

def max_bytes(config=None) -> int:
    """How big a kept video may be (bot.pictures.video_max_mb), with room to spare: platforms count a megabyte
    differently, and a file right at the limit is refused by some."""
    if config is None:
        try:
            from app.utils.helpers import load_config
            config = load_config()
        except Exception:
            config = {}
    pics = ((config or {}).get("bot") or {}).get("pictures") or {}
    mb = _num(pics.get("video_max_mb")) or DEFAULT_MAX_MB
    return int(max(1.0, mb) * 1_000_000 * 0.96)


def _scale(side: int) -> str:
    # The longest side at most `side` and never made bigger, both sides even (H.264 needs it), square pixels.
    return (f"scale=w='min({side},iw)':h='min({side},ih)':force_original_aspect_ratio=decrease,"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1")


def _encode(ffmpeg: str, src, dst, info: dict, side: int, video: list, audio_kbps: int, progress, span: tuple):
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "-1", "-vf", _scale(side)]
    if info["fps"] > MAX_FPS + 0.5:
        args += ["-r", str(MAX_FPS)]
    args += ["-c:v", "libx264", "-preset", "medium", "-profile:v", "high", "-pix_fmt", "yuv420p", *video]
    args += (["-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ac", "2" if audio_kbps >= 64 else "1"]
             if info["audio"] else ["-an"])
    args += ["-movflags", "+faststart", "-max_muxing_queue_size", "4096", "-progress", "pipe:1", "-nostats", str(dst)]
    duration = info["duration"] or 0
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **quiet_kwargs())
    errors: list = []

    import threading
    # What went wrong, if it does: read beside the progress, so neither pipe fills up and stalls ffmpeg.
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if progress and duration and line.startswith("out_time_us="):
            done = _num(line.split("=", 1)[1]) / 1e6
            lo, hi = span
            progress(int(lo + (hi - lo) * max(0.0, min(1.0, done / duration))))
    proc.wait()
    reader.join(timeout=5)
    if proc.returncode != 0:
        tail = (errors[0] if errors else b"").decode("utf-8", "replace").strip().splitlines()[-3:]
        raise VideoError("That video could not be converted" + (f": {tail[-1][:200]}" if tail else "."))


def convert(src, dst, limit: int | None = None, progress=None) -> dict:
    """`src` as an MP4 at `dst`: H.264 and AAC, the longest side at most 1280, at most 30 frames a second, and under
    `limit` bytes. First at a quality that looks like the original; if that is bigger than the limit, again at the
    bitrate that fits, smaller on screen when that bitrate is low, tighter each try. `progress(percent)` as it goes."""
    ffmpeg, _ = tools()
    limit = limit or max_bytes()
    info = probe(src)
    duration = info["duration"]
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    work = dst.with_name(f".{uuid.uuid4().hex}.part.mp4")
    try:
        _encode(ffmpeg, src, work, info, MAX_SIDE, ["-crf", "23"], 128, progress, (0, 100 if not duration else 70))
        smaller = False
        if work.stat().st_size > limit:
            if not duration:
                raise VideoError("That video is too big to send, and its length could not be read to make it smaller.")
            smaller = True
            # Everything it may take, a second: the sound first, the picture gets the rest.
            budget = limit * 8 / duration / 1000 * 0.92
            audio = 0 if not info["audio"] else 96 if budget > 700 else 64 if budget > 300 else 40
            kbps = budget - audio
            # Too long for the size: say how long would fit rather than send mush.
            if kbps < MIN_VIDEO_KBPS:
                fits = limit * 8 / ((MIN_VIDEO_KBPS + (40 if info["audio"] else 0)) * 1000)
                mb = limit / 1_000_000 / 0.96
                room = f"{fits / 60:.0f} minutes" if fits >= 90 else f"{max(1, int(fits))} seconds"
                raise VideoError(f"Too long to send at {mb:.{0 if mb >= 10 else 1}f} MB: about {room} fit. "
                                 "Trim it, or raise the largest video size in Settings.")
            for attempt in range(3):
                side = 1280 if kbps >= 1500 else 960 if kbps >= 800 else 720 if kbps >= 450 else 540 if kbps >= 250 else 426
                v = int(kbps)
                _encode(ffmpeg, src, work, info, side,
                        ["-b:v", f"{v}k", "-maxrate", f"{int(v * 1.4)}k", "-bufsize", f"{v * 2}k"], audio,
                        progress, (70 + attempt * 10, 80 + attempt * 10))
                if work.stat().st_size <= limit:
                    break
                kbps *= 0.82
            else:
                raise VideoError("That video could not be made small enough to send.")
        os.replace(work, dst)
        out = probe(dst)
        if progress:
            progress(100)
        return {"duration": out["duration"] or duration, "width": out["width"], "height": out["height"],
                "size": dst.stat().st_size, "smaller": smaller, "audio": out["audio"]}
    finally:
        try:
            work.unlink()
        except OSError:
            pass


# ── Seeing it ─────────────────────────────────────────────────────────────────

def frame(src, at: float, width: int = 480) -> bytes:
    """One frame, as a JPEG `width` wide."""
    ffmpeg, _ = tools()
    for t in (at, 0.0):
        out = _run([ffmpeg, "-hide_banner", "-nostdin", "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
                    "-vf", f"scale={int(width)}:-2", "-q:v", "3", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"], 60)
        if out.returncode == 0 and out.stdout:
            return out.stdout
    raise VideoError("No picture could be taken from that video.")


def poster(src, dst, width: int = 640) -> Path:
    """The still a video shows before it plays: a moment in, past a black first frame, kept as a JPEG."""
    duration = probe(src)["duration"]
    data = frame(src, min(1.0, duration * 0.15) if duration else 0.0, width)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dst)
    return dst


def sheet(src, count: int = 6, width: int = 480) -> bytes:
    """Frames from across the video, in order, on one picture: left to right, then down. A vision model reads one
    picture, so this is how it sees what happens in a video."""
    from PIL import Image, ImageDraw
    duration = probe(src)["duration"]
    if duration <= 0.5:
        times = [0.0]
    else:
        count = max(2, count)
        times = [duration * (0.06 + 0.88 * i / (count - 1)) for i in range(count)]
    shots = []
    for t in times:
        try:
            shots.append(Image.open(io.BytesIO(frame(src, t, width))).convert("RGB"))
        except Exception:
            continue
    if not shots:
        raise VideoError("No picture could be taken from that video.")
    cols = 1 if len(shots) == 1 else 2 if len(shots) <= 4 else 3
    rows = math.ceil(len(shots) / cols)
    w = max(s.width for s in shots)
    h = max(s.height for s in shots)
    gap = 8
    board = Image.new("RGB", (cols * w + (cols + 1) * gap, rows * h + (rows + 1) * gap), (18, 18, 22))
    draw = ImageDraw.Draw(board)
    for i, shot in enumerate(shots):
        x = gap + (i % cols) * (w + gap)
        y = gap + (i // cols) * (h + gap)
        board.paste(shot, (x, y))
        # Its place in the order, in the corner, so "first" and "last" mean something to the model.
        draw.rectangle((x + 6, y + 6, x + 30, y + 28), fill=(0, 0, 0))
        draw.text((x + 13, y + 10), str(i + 1), fill=(255, 255, 255))
    out = io.BytesIO()
    board.save(out, "JPEG", quality=85)
    return out.getvalue()


def sound(src, seconds: int = 90) -> bytes | None:
    """Its sound, the first `seconds` of it, small enough to be transcribed: None when it has none."""
    ffmpeg, _ = tools()
    if not probe(src)["audio"]:
        return None
    out = _run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(src), "-vn", "-t", str(int(seconds)), "-ac", "1",
                "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3", "pipe:1"], 120)
    return out.stdout if out.returncode == 0 and len(out.stdout or b"") > 2000 else None


def heard(text: str) -> str:
    """What a transcription of a video's sound is worth saying: words, not a music note or one syllable, and short."""
    text = " ".join((text or "").split())
    letters = sum(ch.isalpha() for ch in text)
    if letters < 6 or letters < len(text) * 0.5:
        return ""
    return text if len(text) <= 300 else text[:297].rsplit(" ", 1)[0] + "..."


DESCRIBE_PROMPT = (
    "These are frames from one short video, in order: left to right, then top to bottom. "
    "Describe the video like a short caption, in one or two sentences and under 40 words: "
    "who or what is in it, what happens, where, and any visible text. "
    "Plain words only, no markdown or lists, and do not begin with \"The video\", \"These frames\" or \"The frames\"."
)


def describe_messages(data_url: str, said: str = "") -> list:
    """The request that asks a vision model for a video's caption, from its frames (and what is said in it)."""
    text = DESCRIBE_PROMPT
    if said:
        text += f" What is said in it: \"{said}\". Say briefly what that is about too."
    return [{"role": "user", "content": [{"type": "text", "text": text},
                                         {"type": "image_url", "image_url": {"url": data_url}}]}]


def spool(stream, suffix: str = "") -> Path:
    """An upload copied to a file of its own, in pieces: a video can be far bigger than is worth holding in memory."""
    import shutil
    fd, name = tempfile.mkstemp(prefix="llmselfbot-video-", suffix=suffix or ".bin")
    with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(stream, out, 1024 * 1024)
    return Path(name)
