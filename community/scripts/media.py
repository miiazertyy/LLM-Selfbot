"""media.py - a request's pictures and videos: fetched from the author's gist, checked, and made clean.

The app puts them in the author's own private gist, as base64 in parts (a gist file can't be very big), and pins the
gist's version and every file's checksum in the request. Here the gist is cloned with git (no API, so no rate limit),
put back together, checked against those checksums, and made again: pictures from their pixels (no EXIF, no GPS),
videos remuxed or re-encoded with no metadata, each with a small thumbnail for the catalog.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import community_rules as rules

_PART = re.compile(r"^m\d{2}\.(?:jpg|mp4)\.part\d{3}$")


def fetch_gist(gist_id: str, revision: str, dest: Path) -> Path:
    """The gist at exactly that version, cloned into dest."""
    if not rules.GIST.match(gist_id) or not rules.REVISION.match(revision):
        raise ValueError("The pictures and videos aren't where they should be.")
    url = f"https://gist.github.com/{gist_id}.git"
    try:
        subprocess.run(["git", "clone", "--quiet", "--no-tags", url, str(dest)], check=True, capture_output=True,
                       timeout=900)
        subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", revision], check=True, capture_output=True,
                       timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise ValueError("The pictures and videos couldn't be fetched. Send it again from the app.") from e
    return dest


def read_parts(folder: Path) -> dict:
    out = {}
    for p in Path(folder).iterdir():
        if p.is_file() and _PART.match(p.name):
            out[p.name] = p.read_text(encoding="ascii", errors="replace")
    return out


def files_from(parts: dict, manifest: list) -> dict:
    """Each listed file put back together and checked against its checksum and size: {name: bytes}."""
    out = {}
    for f in manifest:
        data = rules.join_parts(parts, f["name"])
        if len(data) != f["bytes"] or rules.sha256(data) != f["sha256"]:
            raise ValueError(f"{f['name']} doesn't match what the app sent.")
        out[f["name"]] = data
    return out


def ffmpeg_ready() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(args: list, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout)


def probe(path: Path) -> dict:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
              "-of", "json", str(path)], timeout=60)
    if r.returncode:
        raise ValueError("The video couldn't be read.")
    try:
        return json.loads(r.stdout or b"{}")
    except ValueError as e:
        raise ValueError("The video couldn't be read.") from e


def picture(data: bytes) -> tuple:
    """(the picture as kept, its thumbnail)."""
    kept = rules.reencode_image(data, side=rules.LIMITS["picture_side"], formats=("JPEG", "PNG", "WEBP"))
    thumb = rules.reencode_image(kept, side=rules.LIMITS["thumb_side"], quality=80)
    return kept, thumb


def video(data: bytes, work: Path) -> tuple:
    """(the video as kept, its poster as a thumbnail, its length in seconds). Raises ValueError, plainly."""
    if not ffmpeg_ready():
        raise RuntimeError("ffmpeg isn't installed on this runner.")
    work.mkdir(parents=True, exist_ok=True)
    src, out, poster = work / "in.mp4", work / "out.mp4", work / "poster.jpg"
    src.write_bytes(data)
    info = probe(src)
    try:
        seconds = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    if not 0 < seconds <= rules.LIMITS["video_seconds"]:
        raise ValueError(f"A video is longer than {int(rules.LIMITS['video_seconds'])} seconds.")
    streams = info.get("streams") or []
    v = [s for s in streams if s.get("codec_type") == "video"]
    a = [s for s in streams if s.get("codec_type") == "audio"]
    if not v:
        raise ValueError("A video has no picture in it.")
    plain = (v[0].get("codec_name") == "h264" and int(v[0].get("height") or 0) <= 1280
             and all(s.get("codec_name") == "aac" for s in a))
    base = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0"] + (["-map", "0:a:0"] if a else [])
    if plain:
        args = base + ["-c", "copy"]
    else:
        args = base + ["-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                       "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-b:a", "96k"] if a else [])
    args += ["-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", str(out)]
    if _run(args, timeout=600).returncode or not out.is_file():
        raise ValueError("A video couldn't be made clean.")
    kept = out.read_bytes()
    if len(kept) > rules.LIMITS["video_bytes"]:
        raise ValueError(f"A video is too big (at most {rules.LIMITS['video_bytes'] // 1_000_000} MB).")
    at = min(1.0, seconds / 2)
    if _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(out), "-frames:v", "1", str(poster)],
            timeout=60).returncode or not poster.is_file():
        raise ValueError("A video's first picture couldn't be read.")
    thumb = rules.reencode_image(poster.read_bytes(), side=rules.LIMITS["thumb_side"], quality=80)
    return kept, thumb, round(seconds, 1)
