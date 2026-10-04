import base64
import os

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile

from app.utils.paths import DATA_DIR
from app.web.logbus import bus


async def _persona_scope(persona: str = ""):
    """Every picture route works as the persona the page names (?persona=), Default when none: its folder, its rows
    in the database and its own settings (the filter its new pictures get) all follow from this. Set in the request's
    own context, which the route and anything it hands to a thread inherit."""
    from app.utils import personas
    pid = str(persona or "").strip() or personas.DEFAULT
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    personas._scope.set(pid)
    return pid


router = APIRouter(tags=["media"], dependencies=[Depends(_persona_scope)])

# Default's pictures, where they always were. Every other persona's are in its own folder (app/utils/personas.py):
# _dir() is the one for the persona this request works as.
PICTURES_DIR = DATA_DIR / "config" / "pictures"
# What a look was made from, by its content's hash (app/utils/looks.py), so a look can be changed or taken off again.
ORIGINALS_DIR = DATA_DIR / "config" / "pictures_originals"
# Videos sit among the pictures, every one kept as an MP4 (app/utils/videos.py).
_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}
# The still each video shows before it plays, by the video's id.
POSTERS_DIR = DATA_DIR / "cache" / "posters"
# Small copies for tiles and cards, by id and width (an id never comes to mean another picture, so they keep).
THUMBS_DIR = DATA_DIR / "cache" / "thumbs"
_THUMB_WIDTHS = (96, 160, 240, 360, 480, 640)


def _dir():
    """The pictures folder of the persona this request works as (personas.scope), Default's when none."""
    from app.utils import personas
    pid = personas.current() or personas.DEFAULT
    return PICTURES_DIR if pid == personas.DEFAULT else personas.pictures_dir(pid)


def _persona(value) -> str:
    """A persona the page names: one that exists, Default when none is named."""
    from app.utils import personas
    pid = str(value or "").strip()
    if not pid:
        return personas.DEFAULT
    if not personas.exists(pid):
        raise HTTPException(status_code=404, detail="There is no such persona.")
    return pid


def _scope(value):
    """Work as this persona for the rest of the request: its folder, its rows, its settings."""
    from app.utils import personas
    return personas.scope(_persona(value))


def _files():
    folder = _dir()
    if not folder.exists():
        return []
    return sorted(
        [f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in _EXTS],
        key=lambda f: int(os.path.splitext(f)[0][4:])
        if os.path.splitext(f)[0].startswith("IMG_") and os.path.splitext(f)[0][4:].isdigit()
        else 99999,
    )


# Each picture has an id of its own, made from the file itself (its index on
# disk, when it was written, its size), which renaming does not change.
#
# Pictures are renumbered whenever one is deleted, so the rest stay IMG_1 to
# IMG_n: what was IMG_3 becomes IMG_2. A picture's name therefore says nothing
# lasting about which picture it is, and everything that went by name went
# wrong after a delete. The page kept showing the old image for each name (the
# same address is not fetched again), so the card you saw as IMG_2 could be
# the file now called IMG_3, and deleting it by name removed another picture.
# The page now shows, keys and deletes pictures by this id.


def _pic_id(path) -> str:
    import hashlib
    st = path.stat()
    raw = f"{st.st_ino}:{st.st_mtime_ns}:{st.st_size}".encode()
    return hashlib.sha1(raw).hexdigest()[:12]


# One per folder: each persona's pictures have their own.
_ids_cache: dict = {}


def _by_id() -> dict:
    """id -> file name, worked out again only when the folder has changed."""
    folder = _dir()
    try:
        stamp = folder.stat().st_mtime_ns
    except OSError:
        return {}
    hit = _ids_cache.get(str(folder))
    if not hit or hit["stamp"] != stamp:
        by_id = {}
        for f in _files():
            try:
                by_id[_pic_id(folder / f)] = f
            except OSError:
                pass
        hit = {"stamp": stamp, "by_id": by_id}
        _ids_cache[str(folder)] = hit
    return hit["by_id"]


def _resolve(name: str, pid: str | None) -> str | None:
    """The file a request means: the one with this id, wherever renumbering has put it; by name only when no id is given."""
    if pid:
        found = _by_id().get(pid)
        if found:
            return found
        # The folder can change within one tick of its timestamp: look again, properly.
        _ids_cache.pop(str(_dir()), None)
        return _by_id().get(pid)
    if not name or os.path.basename(name) != name:
        return None
    return name if (_dir() / name).is_file() else None


def _next_index() -> int:
    used = set()
    for f in _files():
        stem = os.path.splitext(f)[0]
        if stem.startswith("IMG_") and stem[4:].isdigit():
            used.add(int(stem[4:]))
    i = 1
    while i in used:
        i += 1
    return i


# ── Discord's animated stickers ─────────────────────────────────────────────
# Discord's own stickers ("Wave" and the rest) are Lottie animations, a JSON
# file of shapes rather than a picture, so the Chats tab used to show only
# their names. The panel plays them; this hands it the file, fetched from
# Discord once and kept, since a sticker never changes.
STICKER_DIR = DATA_DIR / "cache" / "stickers"


@router.get("/api/media/sticker/{sid}.json")
def sticker_json(sid: str):
    from fastapi.responses import FileResponse
    if not sid.isdigit() or len(sid) > 24:
        raise HTTPException(status_code=404, detail="not a sticker")
    path = STICKER_DIR / f"{sid}.json"
    if not path.exists():
        import json
        import httpx
        try:
            r = httpx.get(f"https://discord.com/stickers/{sid}.json", timeout=10,
                          headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"could not reach Discord: {exc}")
        if r.status_code != 200 or len(r.content) > 2_000_000:
            raise HTTPException(status_code=404, detail="Discord has no animation for it")
        try:
            json.loads(r.content)          # only a real animation is kept
        except ValueError:
            raise HTTPException(status_code=404, detail="not an animation")
        STICKER_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(path)
    return FileResponse(path, media_type="application/json",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/api/media/chat/{name}")
def chat_picture(name: str):
    """A picture from a DM, kept by the runner when it saw it (app/utils/chatlog.py): Discord's own link expires, and goes with the message when it is deleted."""
    from fastapi.responses import FileResponse
    from app.utils import chatlog
    path = chatlog.media_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="not kept")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/api/pictures")
def pictures(request: Request):
    # One query for every description, not one connection per picture. The per-file lookup opened and closed a sqlite connection for each image on every request, which is what get_all_picture_descriptions() exists for. Plain def, so FastAPI runs the directory scan and stat()s on its threadpool instead of the event loop.
    from app.utils.db import get_all_picture_descriptions, get_picture_looks
    descriptions = get_all_picture_descriptions()
    looks_on = get_picture_looks()
    out = []
    for f in _files():
        try:
            size = (_dir() / f).stat().st_size
        except OSError:
            size = 0
        try:
            pid = _pic_id(_dir() / f)
        except OSError:
            pid = ""
        meta = looks_on.get(f) or {}
        video = _is_video(f)
        out.append({
            "name": f,
            "id": pid,
            "description": descriptions.get(f, ""),
            "size": size,
            # The look on it, if any, and whether it moves (a moving picture keeps its own).
            "look": meta.get("look", ""),
            "strength": meta.get("strength", 0),
            "moving": _moving(f, pid),
            # A video: how long it is, and the still it shows before it plays (/api/pictures/id/<id>/poster).
            "video": video,
            "duration": _duration(f, pid) if video else 0,
        })
    _sweep_originals()
    return {"pictures": out}


def _is_video(name: str) -> bool:
    return os.path.splitext(name)[1].lower() == ".mp4"


_duration_cache: dict = {}


def _duration(name: str, pid: str) -> float:
    """How long a video is, in seconds, remembered by its id (asking ffprobe on every listing would be slow)."""
    if pid in _duration_cache:
        return _duration_cache[pid]
    try:
        from app.utils import videos
        seconds = round(videos.probe(_dir() / name)["duration"], 1)
    except Exception:
        return 0
    _duration_cache[pid] = seconds
    return seconds


_moving_cache: dict = {}


def _moving(name: str, pid: str) -> bool:
    """Whether a GIF or WebP has more than one frame, remembered by the picture's id. A video always moves."""
    if _is_video(name):
        return True
    if os.path.splitext(name)[1].lower() not in (".gif", ".webp"):
        return False
    if pid in _moving_cache:
        return _moving_cache[pid]
    try:
        from PIL import Image
        with Image.open(_dir() / name) as img:
            moving = getattr(img, "n_frames", 1) > 1
    except Exception:
        moving = False
    _moving_cache[pid] = moving
    return moving


def _keep_original(data: bytes, ext: str) -> str:
    """Keep the bytes a look is made from, once, named by their hash: the same picture added twice shares one."""
    import hashlib
    name = hashlib.sha1(data).hexdigest()[:24] + (ext or ".png").lower()
    ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    path = ORIGINALS_DIR / name
    if not path.exists():
        tmp = ORIGINALS_DIR / f"{name}.part"
        tmp.write_bytes(data)
        os.replace(tmp, path)
    return name


def _apply_look_to(name: str, look: str, strength: float) -> dict:
    """Put a look on one picture, made from its original ("" puts the original back), in place. The name changes only
    when the format has to (a still GIF comes out a PNG). Returns what it now is, or why not."""
    from app.utils import looks
    from app.utils.db import get_picture_look, rename_picture_db, set_picture_look
    path = _dir() / name
    if not path.is_file():
        return {"name": name, "error": "picture not found"}
    if _is_video(name):
        return {"name": name, "error": "videos can't take a filter"}
    meta = get_picture_look(name)
    orig = ORIGINALS_DIR / meta["original"] if meta["original"] else None
    kept = orig is not None and orig.is_file()
    if not kept and not look:
        # Nothing on it to take off, or the original went missing and the look has to stay.
        return ({"name": name, "look": "", "strength": 0.0} if not meta["look"]
                else {"name": name, "error": "its original is gone, so the filter can't be removed"})
    src = orig.read_bytes() if kept else path.read_bytes()
    src_ext = orig.suffix.lower() if kept else path.suffix.lower()
    if look:
        try:
            blob, ext = looks.render(src, src_ext, look, strength)
        except looks.Animated:
            return {"name": name, "error": "animated pictures can't take a filter"}
    else:
        blob, ext = src, src_ext
    if not kept:
        orig = ORIGINALS_DIR / _keep_original(src, src_ext)
    new = f"{os.path.splitext(name)[0]}{ext}"
    tmp = _dir() / f"{new}.part"
    tmp.write_bytes(blob)
    os.replace(tmp, _dir() / new)
    if new != name:
        path.unlink(missing_ok=True)
        rename_picture_db(name, new)
    strength = round(float(strength), 2) if look else 0.0
    set_picture_look(new, look, strength, orig.name)
    return {"name": new, "look": look, "strength": strength}


_swept_at = 0.0


def _sweep_originals(force: bool = False) -> None:
    """Originals no picture points to any more (it was deleted), gone, at most every ten minutes. Never one written in
    the last ten: a look being put on may not have recorded it yet."""
    global _swept_at
    import time as _t
    if (not force and _t.time() - _swept_at < 600) or not ORIGINALS_DIR.is_dir():
        return
    _swept_at = _t.time()
    # Shared by every persona (named by their content): one is kept while any persona's picture was made from it.
    from app.utils.db import all_picture_originals
    used = all_picture_originals()
    for f in ORIGINALS_DIR.iterdir():
        try:
            if f.is_file() and f.name not in used and _t.time() - f.stat().st_mtime > 600:
                f.unlink()
        except OSError:
            pass


@router.get("/api/pictures/sample-preview")
def sample_preview(look: str = "", strength: float = 0.7, w: int = 360):
    """A filter on a made-up picture, for Settings to show when there is no picture of yours to show it on."""
    from fastapi.responses import Response
    from app.utils import looks
    if look and look not in looks.LOOKS:
        raise HTTPException(status_code=400, detail="no such filter")
    jpeg = looks.preview(looks.demo_scene(), "demo", look, max(0.0, min(1.0, strength)), max(64, min(1200, int(w))))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/api/pictures/ai-look")
async def ai_look_pick(body: dict = Body(...)):
    """The filter the AI would pick for one picture, from what it shows, to preview: nothing is put on it."""
    from app.utils import looks
    from app.utils.db import get_all_picture_descriptions
    found = _resolve(str(body.get("name") or ""), str(body.get("id") or "") or None)
    if not found:
        raise HTTPException(status_code=404, detail="picture not found")
    import asyncio
    description = (await asyncio.to_thread(get_all_picture_descriptions)).get(found, "")
    if not description:
        raise HTTPException(status_code=409, detail="describe the picture first: the AI picks from what it shows")
    look = await looks.ai_pick_look(description)
    if not look:
        raise HTTPException(status_code=502, detail="the AI could not be asked")
    return {"ok": True, "look": look, "name": looks.LOOKS[look]}


@router.get("/api/pictures/looks")
def looks_list():
    """The looks there are, what the AI may add as it sends a picture, and how Settings has both."""
    from app.utils import looks
    return {"looks": [{"id": k, "name": v, "group": looks.GROUP_OF.get(k, "")} for k, v in looks.LOOKS.items()],
            "kinds": list(looks.TOUCH_KINDS), "auto": looks.auto_look_cfg(), "touches": looks.touches_cfg()}


@router.get("/api/pictures/id/{pid}/preview")
def look_preview(pid: str, look: str = "", strength: float = 0.7, w: int = 360):
    """A small JPEG of a picture with a look on it, made from its original. Plain def: it decodes an image."""
    from fastapi.responses import Response
    from app.utils import looks
    from app.utils.db import get_picture_look
    if not pid.isalnum() or len(pid) > 40:
        raise HTTPException(status_code=404, detail="picture not found")
    if look and look not in looks.LOOKS:
        raise HTTPException(status_code=400, detail="no such look")
    found = _resolve("", pid)
    if not found or _is_video(found):
        raise HTTPException(status_code=404, detail="picture not found")
    meta = get_picture_look(found)
    src = ORIGINALS_DIR / meta["original"] if meta["original"] else None
    if src is None or not src.is_file():
        src = _dir() / found
    st = src.stat()
    jpeg = looks.preview(src.read_bytes(), f"{src.name}:{st.st_mtime_ns}:{st.st_size}", look,
                         max(0.0, min(1.0, strength)), max(64, min(1200, int(w))))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@router.post("/api/pictures/look")
def put_look(body: dict = Body(...)):
    """Put a look on one picture or several, or take it off (look ""). Plain def: each is an image re-encoded."""
    from app.utils import looks
    items = body.get("items")
    look = str(body.get("look") or "")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="which pictures?")
    if look and look not in looks.LOOKS:
        raise HTTPException(status_code=400, detail="no such look")
    try:
        strength = max(0.05, min(1.0, float(body.get("strength", 0.7))))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="strength is a number from 0 to 1")
    names, missing = [], []
    for it in items:
        if not isinstance(it, dict):
            raise HTTPException(status_code=400, detail="items must be objects")
        found = _resolve(str(it.get("name") or ""), str(it.get("id") or "") or None)
        (names if found else missing).append(found or str(it.get("name") or it.get("id") or ""))
    results = [_apply_look_to(n, look, strength) for n in dict.fromkeys(names)]
    done = [r for r in results if not r.get("error")]
    if done:
        many = f"{len(done)} picture{'' if len(done) == 1 else 's'}"
        bus.append("pictures", f"Added the {looks.LOOKS[look]} filter to {many}." if look else f"Removed the filter from {many}.")
    return {"ok": True, "results": results, "missing": missing}


# Putting the new-picture look on every picture at once: in the background, with its progress in /api/pictures/status.
_look_job = {"running": False, "total": 0, "done": 0}
_look_task = None


@router.post("/api/pictures/auto-look")
async def auto_look_all(request: Request):
    """The look Settings gives new pictures, put on every picture now."""
    import asyncio
    from app.utils import looks
    global _look_task
    cfg = looks.auto_look_cfg()
    if cfg["mode"] == "off":
        raise HTTPException(status_code=400, detail="new pictures are set to no filter")
    if _look_job["running"]:
        return {"ok": True, "queued": 0, "running": True}
    # A video keeps how it looks.
    names = [n for n in _files() if not _is_video(n)]
    _look_job.update(running=True, total=len(names), done=0)
    _look_task = asyncio.create_task(_auto_look_pass(names, cfg, _here()))
    return {"ok": True, "queued": len(names), "running": True}


async def _auto_look_pass(names: list, cfg: dict, pid: str = "default") -> None:
    from app.utils import personas
    with personas.scope(pid):
        await _auto_look_run(names, cfg)


async def _auto_look_run(names: list, cfg: dict) -> None:
    import asyncio
    from app.utils import looks
    from app.utils.db import get_all_picture_descriptions
    descriptions = get_all_picture_descriptions()
    done = 0
    try:
        for name in names:
            try:
                if cfg["mode"] == "ai":
                    look = await looks.ai_pick_look(descriptions.get(name, ""))
                    strength = looks.varied(cfg["strength"], cfg["vary"])
                else:
                    look, strength = looks.pick_auto(cfg)
                if look and (_dir() / name).is_file():
                    if not (await asyncio.to_thread(_apply_look_to, name, look, strength)).get("error"):
                        done += 1
            except Exception as exc:
                bus.append("pictures", f"Could not add a filter to {name}: {exc}", "warn")
            finally:
                _look_job["done"] += 1
    finally:
        _look_job["running"] = False
        bus.append("pictures", f"Added filters to {done} picture{'' if done == 1 else 's'}.")


@router.post("/api/pictures/touch-preview")
async def touch_preview(body: dict = Body(...)):
    """What the AI would add to this picture as it sends it, drawn: the picture as a small JPEG, and what it chose.
    Asked as if someone had just asked for a picture. With {"all": true}, every kind it may add at once instead, to see
    how each one is drawn (the time on the persona's clock, the day, Apple's emoji...)."""
    import asyncio
    from app.utils import looks
    from app.utils.db import get_all_picture_descriptions
    from app.utils.helpers import load_config
    found = _resolve(str(body.get("name") or ""), str(body.get("id") or "") or None)
    if not found:
        raise HTTPException(status_code=404, detail="picture not found")
    if _is_video(found):
        return {"ok": True, "spec": {}, "image": "", "said": "A video is sent as it is.",
                "note": "A video is sent as it is."}
    wanted = body.get("kinds")
    kinds = [k for k in (wanted if isinstance(wanted, list) else looks.touches_cfg()["kinds"]) if k in looks.TOUCH_KINDS]
    if not kinds:
        raise HTTPException(status_code=400, detail="nothing is allowed on the pictures")
    lang = str((load_config().get("bot") or {}).get("default_language") or "en")
    sample = bool(body.get("all"))
    if sample:
        spec = looks.sample_touch(kinds, lang)
    else:
        try:
            import asyncio
            described = (await asyncio.to_thread(get_all_picture_descriptions)).get(found, "")
            spec = await looks.plan_touch(described, ["them: send a pic"], "", lang, kinds, strict=True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"the AI could not be asked: {exc}")
    if not spec:
        return {"ok": True, "spec": {}, "image": "", "said": "It would send this one as it is.",
                "note": "It would send this one as it is."}
    path = str(_dir() / found)
    try:
        data = await asyncio.to_thread(looks.source_bytes, path, spec)
        blob = await asyncio.to_thread(looks.shrunk_touch, data, spec, lang, 720)
    except looks.Animated:
        return {"ok": True, "spec": {}, "image": "", "said": "An animated picture is sent as it is.",
                "note": "An animated picture is sent as it is."}
    said = looks.describe_touch(spec)
    return {"ok": True, "spec": spec, "said": said, "sample": sample,
            "note": "Everything it can add, all at once." if sample else f"It added {said}.",
            "image": "data:image/jpeg;base64," + base64.b64encode(blob).decode()}


def _save(data: bytes, original: str) -> tuple[str, bytes]:
    """Normalise one image and write it into the pictures folder, with the look Settings gives new pictures (the AI's
    pick waits for the description: see _ai_look)."""
    from app.utils.imageimport import convert
    blob, ext, note = convert(data, original)
    _dir().mkdir(parents=True, exist_ok=True)
    with _save_lock:
        name = f"IMG_{_next_index()}{ext}"
        (_dir() / name).write_bytes(blob)
    if note:
        bus.append("pictures", f"{os.path.basename(original) or name}: {note}")
    from app.utils import looks
    look, strength = looks.pick_auto()
    if look:
        done = _apply_look_to(name, look, strength)
        if not done.get("error"):
            name = done["name"]
            blob = (_dir() / name).read_bytes()
    _new_pictures.add((_here(), name))
    return name, blob


# Pictures just added, so the AI's look goes on those and never on old ones described again: (persona, name).
_new_pictures: set = set()

# A number is taken and its file written in one go: a video converts for a while, and another upload meanwhile must
# not end up with the same name.
import threading as _threading  # noqa: E402
_save_lock = _threading.Lock()

# The video being converted now, for the page to say how far it has got (/api/pictures/status); "step" is convert,
# then describe while its frames are looked at.
_video_job = {"active": False, "name": "", "percent": 0, "step": ""}


def _save_video(src, original: str) -> tuple[str, dict]:
    """Convert one video into the pictures folder as IMG_<n>.mp4 (app/utils/videos.py): any kind in, H.264 and AAC
    out, made smaller to the size Settings allows. Converted aside first and moved in under its number at the end."""
    import uuid
    from app.utils import videos
    label = os.path.basename(original or "") or "a video"
    work = DATA_DIR / "cache" / "convert" / f"{uuid.uuid4().hex}.mp4"
    _video_job.update(active=True, name=label, percent=0, step="convert")
    try:
        info = videos.convert(src, work, videos.max_bytes(), progress=lambda p: _video_job.update(percent=p))
        _dir().mkdir(parents=True, exist_ok=True)
        with _save_lock:
            name = f"IMG_{_next_index()}.mp4"
            os.replace(work, _dir() / name)
    finally:
        _video_job.update(active=False, name="", percent=0, step="")
        try:
            work.unlink()
        except OSError:
            pass
    smaller = f", made smaller to {info['size'] / 1_000_000:.1f} MB to send" if info["smaller"] else ""
    bus.append("pictures", f"{label}: saved as {name}{smaller}.")
    return name, info


def _save_video_bytes(data: bytes, original: str) -> tuple[str, dict]:
    """A video from inside a zip: on disk for ffmpeg, then as any other."""
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="llmselfbot-video-", suffix=os.path.splitext(original)[1] or ".bin")
    with os.fdopen(fd, "wb") as out:
        out.write(data)
    try:
        return _save_video(tmp, original)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _here() -> str:
    from app.utils import personas
    return personas.current() or personas.DEFAULT


async def _ai_look(name: str, description: str) -> str:
    """With new pictures set to "Let the AI pick": the look it thinks suits this one, once it is described. Returns the
    picture's name, which a look can change."""
    import asyncio
    from app.utils import looks
    if (_here(), name) not in _new_pictures:
        return name
    _new_pictures.discard((_here(), name))
    cfg = looks.auto_look_cfg()
    if cfg["mode"] != "ai" or not description:
        return name
    look = await looks.ai_pick_look(description)
    if not look:
        return name
    done = await asyncio.to_thread(_apply_look_to, name, look, looks.varied(cfg["strength"], cfg["vary"]))
    if done.get("error"):
        return name
    bus.append("pictures", f"{done['name']}: the AI gave it the {looks.LOOKS[look]} filter.")
    return done["name"]


# Describing a zip of thirty photos is thirty model calls, which is far longer than a request should stay open. The files land immediately and the descriptions fill in behind them, with progress the page can poll.
_describe_state = {"running": False, "total": 0, "done": 0, "failed": 0,
                   "reason": "", "workers": 1}
_describe_queue: list = []
_describe_task = None

# Groq's limits are per key, so two keys are two separate allowances rather than one shared faster one. Describing ran strictly one picture at a time on whichever key happened to be active, only touching the others when that one hit its ceiling, so a second key did nothing for a big import except get used once the first was exhausted. One worker per key, each pinned to its own, turns them into real parallelism. Capped because the point is to use the keys, not to open an unbounded number of concurrent uploads: each call carries a base64 image.
MAX_DESCRIBE_WORKERS = 4


async def _describe_worker(slot: int):
    """Drain the shared queue, describing each picture on this worker's key. `slot` is both the worker number and the Groq key index, so two workers never spend the same allowance. The queue is shared and popped from the front, so a worker whose key is throttled simply takes fewer pictures rather than holding up the ones that are not."""
    import asyncio

    from app.utils import personas
    while _describe_queue:
        pid, name = _describe_queue.pop(0)
        if not personas.exists(pid):
            continue        # deleted while it waited
        with personas.scope(pid):
            await _describe_one(slot, name)
        # Spacing keeps one key under its per minute ceiling instead of tripping it on the second picture. Each worker paces its own key, so more keys means more pictures in the same wall time, not a tighter gap on any one of them.
        if _describe_queue:
            await asyncio.sleep(3)


async def _describe_one(slot: int, name: str):
    """One picture of the persona this works as, described, its new look put on."""
    import asyncio
    if True:
        try:
            path = _dir() / name
            if not path.exists():
                return

            # A per minute limit clears by waiting, so a rate limited picture is worth a second and third go. Anything else is a real failure and retrying it just wastes the allowance.
            description, reason = "", ""
            for backoff in (0, 20, 40):
                if backoff:
                    _describe_state["reason"] = (
                        f"Waiting {backoff}s for the rate limit to clear.")
                    await asyncio.sleep(backoff)
                description, reason = await _describe_file(name, client_index=slot)
                if description or "rate" not in reason.lower():
                    break
            _describe_state["reason"] = ""

            if description:
                bus.append("pictures", f"Described {name}.")
                await _ai_look(name, description)
            else:
                _describe_state["failed"] += 1
                _describe_state["reason"] = reason
                bus.append("pictures", f"Could not describe {name}: {reason}", "warn")
        except Exception as exc:
            # One bad file must not stop the rest of the batch, and an escaping exception here would be an unhandled task error.
            _describe_state["failed"] += 1
            _describe_state["reason"] = str(exc)
            bus.append("pictures", f"Could not describe {name}: {exc}", "warn")
        finally:
            _describe_state["done"] += 1
            if _describe_state["done"] > _describe_state["total"]:
                _describe_state["total"] = _describe_state["done"]


async def _describe_pending():
    """Describe everything queued, including anything added while running. Dropping a second archive mid pass used to leave its pictures with no description and no sign of why, because the guard simply refused to start a second task; the queue is drained instead, so a later batch joins the one already going."""
    import asyncio
    from app.utils.ai import groq_key_count, vision_is_local

    # A local vision model is one server with one queue, so spreading work across "keys" there would just queue up on the same machine.
    try:
        keys = 1 if vision_is_local() else max(1, groq_key_count())
    except Exception:
        keys = 1
    workers = max(1, min(keys, MAX_DESCRIBE_WORKERS))

    _describe_state.update(running=True, done=0, failed=0, reason="",
                           workers=workers, total=len(_describe_queue))
    if workers > 1:
        bus.append("pictures",
                   f"Describing with {workers} keys at once.")
    try:
        await asyncio.gather(*(_describe_worker(slot) for slot in range(workers)))
    finally:
        _describe_state["running"] = False
        # `workers` deliberately keeps its value: with running False it reads as "that last pass used N keys", which is what the page wants to say.
        failed = _describe_state["failed"]
        bus.append("pictures",
                   "Finished describing the new pictures."
                   if not failed else
                   f"Finished, {failed} could not be described.",
                   "warn" if failed else "info")


@router.post("/api/pictures/describe-missing")
async def describe_missing(request: Request):
    """Describe every picture that has none, one after another. A batch can end up part described when the provider rate limits partway through, and re-running each one by hand is not a reasonable way out. With {"long": true}, the ones with a description longer than a caption are described again too: those were written when the prompt asked for "full detail"."""
    import asyncio
    from app.utils.db import get_all_picture_descriptions
    from app.utils.pictures import LONG_DESCRIPTION

    global _describe_task
    try:
        body = await request.json()
    except Exception:
        body = {}
    redo_long = isinstance(body, dict) and bool(body.get("long"))
    import asyncio
    descriptions = await asyncio.to_thread(get_all_picture_descriptions)

    def wanted(f):
        text = (descriptions.get(f) or "").strip()
        return not text or (redo_long and len(text) > LONG_DESCRIPTION)

    pid = _here()
    pending = [f for f in _files() if wanted(f)]
    pending = [f for f in pending if (pid, f) not in _describe_queue]
    if not pending:
        return {"ok": True, "queued": 0, "running": _describe_state["running"]}
    _describe_queue.extend((pid, f) for f in pending)
    if _describe_state["running"]:
        # Joining a pass already under way: the total was fixed when it began.
        _describe_state["total"] += len(pending)
    else:
        _describe_task = asyncio.create_task(_describe_pending())
    return {"ok": True, "queued": len(pending), "running": True}


@router.get("/api/pictures/status")
async def describe_status(request: Request):
    """Progress of the background pass that describes a freshly imported batch, of looks put on every picture, and of
    a video being converted."""
    return {**_describe_state, "looks": dict(_look_job), "video": dict(_video_job)}


@router.post("/api/pictures")
async def upload(request: Request, file: UploadFile = File(...)):
    """Take an image in any format, a video in any format, or a zip full of them. A zip is walked recursively, so the usual "right click the folder, send to compressed" shape works; anything the machine can decode is converted into something the bot can actually send. A video becomes an MP4, smaller when it is too big to send (app/utils/videos.py)."""
    import asyncio
    from app.utils import videos
    from app.utils.imageimport import is_zip

    global _describe_task

    original = file.filename or ""
    head = await file.read(64)
    await file.seek(0)
    if not head:
        raise HTTPException(status_code=400, detail="that file is empty")

    # ── A video: on disk rather than in memory, converted on a thread ───────
    if videos.is_video(original, head):
        tmp = await asyncio.to_thread(videos.spool, file.file, os.path.splitext(original)[1])
        try:
            name, info = await asyncio.to_thread(_save_video, tmp, original)
        except videos.VideoError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        _video_job.update(active=True, name=os.path.basename(original) or name, percent=100, step="describe")
        try:
            description, reason = await _describe_file(name)
        finally:
            _video_job.update(active=False, name="", percent=0, step="")
        return {"ok": True, "name": name, "description": description, "reason": reason, "added": [name],
                "skipped": [], "video": True, "smaller": info["smaller"], "size": info["size"]}

    data = await file.read()

    # ── A whole archive ──────────────────────────────────────────────────────
    if is_zip(data, original):
        from app.utils.imageimport import iter_zip
        try:
            members = list(iter_zip(data))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"could not read that zip: {exc}")

        def save_all():
            added, skipped = [], []
            for member, blob in members:
                try:
                    if videos.is_video(member, blob[:64]):
                        name, _ = _save_video_bytes(blob, member)
                    else:
                        name, _ = _save(blob, member)
                    added.append(name)
                except ValueError as exc:
                    skipped.append({"name": os.path.basename(member), "reason": str(exc)})
                except Exception as exc:
                    skipped.append({"name": os.path.basename(member),
                                    "reason": f"{type(exc).__name__}: {exc}"})
            return added, skipped

        # On a thread: each picture is decoded and written, and a video in it converts for a while.
        added, skipped = await asyncio.to_thread(save_all)
        if not added and not skipped:
            raise HTTPException(status_code=400, detail="no images in that zip")
        bus.append("pictures",
                   f"Imported {len(added)} picture(s) from {os.path.basename(original) or 'a zip'}"
                   + (f", skipped {len(skipped)}" if skipped else "") + ".")
        if added:
            _describe_queue.extend((_here(), n) for n in added)
            if _describe_state["running"]:
                _describe_state["total"] += len(added)
            else:
                _describe_task = asyncio.create_task(_describe_pending())
        return {"ok": True, "zip": True, "added": added, "skipped": skipped,
                "describing": bool(added)}

    # ── A single picture ─────────────────────────────────────────────────────
    try:
        name, blob = _save(data, original)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    description, reason = await _describe(name, blob, os.path.splitext(name)[1].lower())
    if description:
        name = await _ai_look(name, description)
    else:
        _new_pictures.discard((_here(), name))
    return {"ok": True, "name": name, "description": description, "reason": reason,
            "added": [name], "skipped": []}


async def _describe_file(name: str, client_index=None):
    """The caption of a picture or a video as the file is now. A video is shown to the model as frames from across it
    on one picture (app/utils/videos.py), with what is said in it when it says anything."""
    import asyncio
    path = _dir() / name
    if not _is_video(name):
        data = await asyncio.to_thread(path.read_bytes)
        return await _describe(name, data, os.path.splitext(name)[1].lower(), client_index=client_index)
    from app.utils import videos

    def material():
        return videos.sheet(path), videos.sound(path)

    try:
        sheet, sound = await asyncio.to_thread(material)
    except videos.VideoError as exc:
        return "", str(exc)
    return await _describe(name, sheet, ".jpg", client_index=client_index, video=True, sound=sound)


async def _describe(name: str, data: bytes, ext: str, client_index=None, video: bool = False, sound: bytes | None = None):
    """Ask the model what is in the picture. Returns the description and, when there is none, the reason. Swallowing the failure silently left the page showing "no description" with no way to tell a missing key from a model that was down.
    `video`: `data` is a video's frames on one picture, and `sound` its sound to be transcribed for the caption."""
    import asyncio
    try:
        if not (os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY_1")):
            from dotenv import load_dotenv
            from app.utils.helpers import get_env_path
            await asyncio.to_thread(load_dotenv, dotenv_path=get_env_path(), override=True)
        # On a thread: init_ai reads the .env and the config and, the first time, loads the OpenAI library, which on
        # the event loop froze every page of the panel for seconds ("busy in ai.py in init_ai").
        from app.utils.ai import init_ai, vision_is_local
        if not (os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY_1")):
            # A local vision model reads pictures without any key at all. With no model at all, init_ai() exits, as
            # a runner should; the panel only says so.
            try:
                await asyncio.to_thread(init_ai)
            except SystemExit:
                return "", "Nothing can look at the picture: no model is set up yet."
            if not vision_is_local():
                return "", ("Nothing can look at the picture: no Groq key, and "
                            "no local model set to read images.")

        from app.utils.ai import _create_image_completion
        from app.utils.helpers import load_config
        from app.utils.pictures import DESCRIBE_MAX_TOKENS, clean_description, describe_messages
        await asyncio.to_thread(init_ai)
        model = load_config()["bot"].get(
            "groq_image_model", "meta-llama/llama-4-scout-17b-16e-instruct")
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext[1:]}"
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        messages = describe_messages(data_url)
        if video:
            from app.utils import videos
            said = ""
            if sound:
                # What is said in it, when anything is: a caption of someone talking says what about.
                try:
                    from app.utils.ai import transcribe_voice
                    said = videos.heard(await transcribe_voice(sound, "sound.mp3"))
                except Exception:
                    said = ""
            messages = videos.describe_messages(data_url, said)
        resp = await _create_image_completion(
            model,
            client_index=client_index,
            # A caption, the same wherever a picture is added: DESCRIBE_PROMPT in app/utils/pictures.py says why.
            messages=messages,
            # Keeps the request inside the free tier's output budget, and stops a reasoning model spending the whole allowance on its monologue.
            max_tokens=DESCRIBE_MAX_TOKENS,
            reasoning_effort="none",
        )
        raw = (resp.choices[0].message.content or "")
        description = clean_description(raw)
        if not description:
            if raw.strip():
                return "", (f"{model} spent its whole answer on internal reasoning "
                            "before running out of room. Pick a different model "
                            "under Settings, groq_image_model.")
            return "", "The model answered with nothing."
        from app.utils.db import add_picture_description
        add_picture_description(name, description)
        return description, ""
    except Exception as exc:
        from app.utils import apihealth
        text = str(exc)
        if "429" in text or "rate" in text.lower():
            event = apihealth.record("rate_limit", text, model="image")
            return "", event["message"] + " It will be retried."
        apihealth.record("error", text, model="image")
        return "", f"{type(exc).__name__}: {exc}"


@router.post("/api/pictures/{name}/analyse")
async def analyse(request: Request, name: str, id: str = ""):
    """Describe a picture again, for one that arrived without a description."""
    found = _resolve(name, id or None)
    if not found:
        raise HTTPException(status_code=404, detail="picture not found")
    description, reason = await _describe_file(found)
    return {"ok": bool(description), "description": description, "reason": reason}


@router.post("/api/pictures/{name}/desc")
async def set_desc(request: Request, name: str):
    body = await request.json()
    description = (body.get("description") or "").strip()
    found = _resolve(name, str(body.get("id") or "") or None)
    if not found:
        raise HTTPException(status_code=404, detail="picture not found")
    name = found
    if not description:
        raise HTTPException(status_code=400, detail="description required")
    from app.utils.db import add_picture_description
    import asyncio
    await asyncio.to_thread(add_picture_description, name, description)
    return {"ok": True}


def _renumber():
    """Close the gaps so the files stay IMG_1..IMG_n with nothing missing."""
    from app.utils.db import rename_picture_db
    renamed = 0
    for i, fname in enumerate(_files(), start=1):
        stem, ext = os.path.splitext(fname)
        if stem.startswith("IMG_") and stem[4:].isdigit() and int(stem[4:]) != i:
            new = f"IMG_{i}{ext}"
            os.rename(_dir() / fname, _dir() / new)
            rename_picture_db(fname, new)
            renamed += 1
    return renamed


def _delete_one(name: str) -> bool:
    """Remove one picture and its description. No renumbering."""
    from app.utils.db import delete_picture_db
    path = _dir() / name
    if not path.exists():
        return False
    try:
        pid = _pic_id(path)
        # Its still and its small copies go with it.
        if _is_video(name):
            (POSTERS_DIR / f"{pid}.jpg").unlink(missing_ok=True)
        for t in THUMBS_DIR.glob(f"{pid}_*.jpg"):
            t.unlink(missing_ok=True)
    except OSError:
        pass
    path.unlink()
    delete_picture_db(name)
    return True


@router.post("/api/pictures/delete")
def delete_many(request: Request, body: dict = Body(...)):
    """Delete several pictures in one go. This exists because deleting renumbers: every file is renamed so the set stays IMG_1..IMG_n with no gaps, so calling the single delete in a loop from the client would delete the wrong pictures, after the first call every name the client is holding refers to a different file. The whole selection is removed first and the renumber happens once, at the end. Plain def: unlink and rename are blocking, and there can be a lot of them."""
    items = body.get("items")
    if isinstance(items, list) and items:
        # By id: each one resolved to the file it is now, before anything is removed.
        safe = []
        missing_ids = []
        for it in items:
            if not isinstance(it, dict):
                raise HTTPException(status_code=400, detail="items must be objects")
            found = _resolve(str(it.get("name") or ""), str(it.get("id") or "") or None)
            if found:
                safe.append(found)
            else:
                missing_ids.append(str(it.get("name") or it.get("id") or ""))
        if not safe:
            return {"ok": True, "deleted": 0, "missing": missing_ids}
    else:
        missing_ids = []
        names = body.get("names")
        if not isinstance(names, list) or not names:
            raise HTTPException(status_code=400, detail="names must be a non-empty list")

        # Reject path traversal rather than trusting the client with a filename.
        safe = []
        for name in names:
            if not isinstance(name, str) or not name or os.path.basename(name) != name:
                raise HTTPException(status_code=400, detail=f"bad picture name: {name!r}")
            safe.append(name)

    deleted = [n for n in dict.fromkeys(safe) if _delete_one(n)]
    missing = [n for n in dict.fromkeys(safe) if n not in deleted]
    _renumber()
    if deleted:
        bus.append("pictures",
                   f"Deleted {len(deleted)} picture{'' if len(deleted) == 1 else 's'}.")
    return {"ok": True, "deleted": len(deleted), "missing": missing + missing_ids}


@router.delete("/api/pictures/{name}")
def delete(request: Request, name: str, id: str = ""):
    """One picture, the one with this id when it is given: its name may have moved on since the page read it."""
    found = _resolve(name, id or None)
    if not found or not _delete_one(found):
        raise HTTPException(status_code=404, detail="picture not found")
    _renumber()
    return {"ok": True, "deleted": found}


@router.get("/api/pictures/id/{pid}")
def picture_by_id(request: Request, pid: str):
    """A picture by its id. The address never comes to mean another picture, whatever is renumbered, so it is kept for good.
    With no persona named, every persona's pictures are looked through: an id is the file's own, whoever's it is."""
    from fastapi.responses import FileResponse
    found, folder = _find_by_id(request, pid)
    return FileResponse(folder / found, headers={"Cache-Control": "private, max-age=31536000, immutable"})


def _find_by_id(request: Request, pid: str):
    """The file with this id and its folder: the named persona's, or with none named, any persona's."""
    from app.utils import personas
    if not pid.isalnum() or len(pid) > 40:
        raise HTTPException(status_code=404, detail="picture not found")
    found = _resolve("", pid)
    folder = _dir()
    if not found and not request.query_params.get("persona"):
        for other in personas.ids():
            with personas.scope(other):
                found = _resolve("", pid)
                if found:
                    folder = _dir()
                    break
    if not found:
        raise HTTPException(status_code=404, detail="picture not found")
    return found, folder


@router.get("/api/pictures/id/{pid}/poster")
def video_poster(request: Request, pid: str):
    """The still a video shows before it plays, taken once and kept by the video's id (which never comes to mean
    another). Plain def: ffmpeg takes a moment."""
    from fastapi.responses import FileResponse
    found, folder = _find_by_id(request, pid)
    if not _is_video(found):
        raise HTTPException(status_code=404, detail="not a video")
    out = POSTERS_DIR / f"{pid}.jpg"
    if not out.is_file():
        from app.utils import videos
        try:
            videos.poster(folder / found, out)
        except Exception:
            raise HTTPException(status_code=404, detail="no still could be taken from it")
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/api/pictures/id/{pid}/thumb")
def picture_thumb(request: Request, pid: str, w: int = 160):
    """A small JPEG of a picture as it is sent (its look on it), its shorter side `w` (rounded up to one of a few sizes),
    or of a video's still: for tiles and cards. Made once and kept by the id. Plain def: it decodes an image."""
    from fastapi.responses import FileResponse
    found, folder = _find_by_id(request, pid)
    size = next((x for x in _THUMB_WIDTHS if x >= w), _THUMB_WIDTHS[-1])
    out = THUMBS_DIR / f"{pid}_{size}.jpg"
    if not out.is_file():
        from PIL import Image, ImageOps
        src = folder / found
        if _is_video(found):
            still = POSTERS_DIR / f"{pid}.jpg"
            if not still.is_file():
                from app.utils import videos
                try:
                    videos.poster(src, still)
                except Exception:
                    raise HTTPException(status_code=404, detail="no still could be taken from it")
            src = still
        try:
            with Image.open(src) as im:
                im.seek(0)
                im = ImageOps.exif_transpose(im).convert("RGB")
                scale = size / max(1, min(im.size))
                if scale < 1:
                    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
                THUMBS_DIR.mkdir(parents=True, exist_ok=True)
                tmp = out.with_name(out.name + ".part")
                im.save(tmp, "JPEG", quality=82, optimize=True)
                tmp.replace(out)
        except HTTPException:
            raise
        except Exception:
            # Something Pillow cannot open: the picture itself.
            return FileResponse(folder / found, headers={"Cache-Control": "private, max-age=600"})
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/api/pictures/{name}")
async def download(request: Request, name: str):
    path = _dir() / name
    if os.path.basename(name) != name or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="picture not found")
    from fastapi.responses import FileResponse
    # By name, it is a different picture after a delete: always asked again.
    return FileResponse(path, headers={"Cache-Control": "no-cache"})
