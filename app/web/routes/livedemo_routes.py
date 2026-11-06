"""The practice LIVE (Settings, TikTok, LIVE): a pretend TikTok LIVE in the panel, to try the co-host without going
live. Its viewers are made up by the page; the persona answers them exactly as it would on a real LIVE
(app/utils/livecohost.py), with the LIVE settings on screen, saved or not: the same line, the same voice, the same pace
(one at a time, so many a minute, a viewer not again too soon or too often, a moment before each). Nothing goes to
TikTok, nobody is remembered, nothing is counted.

It speaks as the persona being edited in Settings, else the TikTok account's, else Default's: written here, in the
panel, so it works before any account is set up or running.

Its screen can be a picture or a video of your own (the page picks everything else it can show: one of the persona's
pictures or videos, its face, or nothing): one file per persona, kept in the persona's folder so it goes with it, and
never one of the pictures it sends.
"""
import asyncio
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.core import ipc

router = APIRouter(tags=["live-demo"])

# The practice LIVE going on: its pace (app/utils/livecohost.Pace) and the lines it wrote, to say out loud.
_STATE: dict = {"pace": None, "answers": {}}
_AUDIO = re.compile(r"demo_[0-9a-f]{32}_\d{1,2}\.wav")
# Each practice viewer is someone of their own to the engine, kept apart from anyone real.
_UID_PREFIX = "livedemo_"
_CHANNEL = "livedemo"


def _audio_dir():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "live_audio"


def _tiktok_account() -> str:
    """The first TikTok account, "" when there is none."""
    ids = sorted((k for k in ipc.discover_targets() if k.startswith("tiktok_")), key=lambda k: int(k.split("_")[1]))
    return ids[0] if ids else ""


def _persona(requested: str) -> str:
    """Whose voice it is: the persona asked for (the one being edited), else the TikTok account's, else Default."""
    from app.utils import personas
    if requested and personas.exists(requested):
        return requested
    account = _tiktok_account()
    return personas.persona_of(account) if account else personas.DEFAULT


def _host(pid: str) -> dict:
    """Who is live: the TikTok account as TikTok shows it, when there is one speaking as this persona; else the
    persona itself, by its name and picture."""
    from app.utils import personas
    account = _tiktok_account()
    if account and personas.persona_of(account) == pid:
        try:
            from app.web.routes.status_routes import _tiktok_identity
            me = _tiktok_identity(int(account.split("_")[1]))
            if me.get("username"):
                return {"name": me.get("display_name") or me["username"], "handle": me["username"],
                        "avatar": me.get("avatar") or ""}
        except Exception:
            pass
    info = personas.get(pid) or {"name": pid}
    avatar = f"/api/personas/{pid}/avatar?v={personas.avatar_version(pid)}" if personas.has_avatar(pid) else ""
    return {"name": info.get("name") or pid, "handle": "", "avatar": avatar}


def _who(requested: str) -> tuple[str, list]:
    """Whose practice LIVE it is, and what its chat may call it (its host's name and @handle, the persona's name),
    for answering only when it is named. Reads files: off the loop."""
    from app.utils import personas
    pid = _persona(requested)
    host = _host(pid)
    info = personas.get(pid) or {}
    return pid, sorted({str(n) for n in (host.get("name"), host.get("handle"), info.get("name")) if n})


def _pace():
    from app.utils import livecohost
    if _STATE["pace"] is None:
        _STATE["pace"] = livecohost.Pace()
    return _STATE["pace"]


def _voice_ready() -> bool:
    """Whether anything can speak: speaking switched on, and a voice set up under Models or a Groq key for Orpheus."""
    from app.utils.helpers import load_config
    if not ((load_config().get("bot") or {}).get("tts") or {}).get("enabled", True):
        return False
    try:
        from app.utils import ai
        return bool(ai.tts_targets()) or ai.groq_key_count() > 0
    except BaseException:
        return False


def _ai_ready() -> str:
    """"" when a model can write the persona's lines; else why not, plainly. Its AI is set up here when it is not yet:
    a runner with no model at all exits on purpose (init_ai), which in the panel would have taken every page down."""
    from app.utils import ai
    if ai._initialised:
        return ""
    try:
        ai.init_ai()
    except SystemExit:
        return "No model is set up to write replies. Add one under Settings, Models."
    except Exception as e:
        return f"The AI could not start: {e}"[:200]
    return ""


def _warm() -> str:
    """What the first line and its voice load, loaded here, on a worker thread: loaded by the first answer instead, on
    the loop every page shares, it held the whole panel still for a moment (the engine, the AI clients, openai's
    package for the voice). Answers _ai_ready()'s reason."""
    try:
        import app.core.engine  # noqa: F401
        import openai  # noqa: F401
    except Exception:
        pass
    return _ai_ready()


@router.get("/api/live-demo")
def demo_info(persona: str = ""):
    """Who goes live in the practice LIVE and how: its host, its persona, its saved LIVE settings, and whether it
    can speak. Plain def: it reads files, and loads what its first line needs off the shared loop."""
    from app.utils import livecohost, personas
    from app.utils.helpers import load_config
    not_ready = _warm()
    pid = _persona(persona)
    with personas.scope(pid):
        live = livecohost.settings(((load_config().get("tiktok") or {}).get("live")))
        voice = not not_ready and _voice_ready()
    info = personas.get(pid) or {"name": pid}
    return {"persona": {"id": pid, "name": info.get("name") or pid}, "host": _host(pid), "live": live, "voice": voice,
            "account": _tiktok_account(), "not_ready": not_ready}


@router.post("/api/live-demo/start")
def demo_start():
    """A new practice LIVE: nobody in it has been answered yet, and its pace starts again."""
    from app.core import engine
    for key in [k for k in engine.message_history if k.startswith(_UID_PREFIX)]:
        engine.message_history.pop(key, None)
    for uid in [u for u in engine._lang_cache if u.startswith(_UID_PREFIX)]:
        engine._lang_cache.pop(uid, None)
    from app.utils import livecohost
    _STATE["pace"] = livecohost.Pace()
    _STATE["answers"].clear()
    return {"ok": True}


@router.post("/api/live-demo/answer")
async def demo_answer(request: Request):
    """Something in the practice LIVE's chat ("quiet" when its chat has gone quiet), and the persona's line to it, as
    on a real LIVE: what the settings on screen say is answered, at the pace they set.
    {answered, id, text} or {answered: false, why}."""
    from app.utils import livecohost, personas
    body = await request.json()
    kind = str(body.get("event") or "")
    name = str(body.get("name") or "").strip()[:40] or "someone"
    text = str(body.get("text") or "").strip()[:300]
    live = livecohost.settings(body.get("live"))
    pid, names = await asyncio.to_thread(_who, str(body.get("persona") or ""))
    why = livecohost.skip_reason(kind, text, live, name, "", names)
    if why:
        return {"answered": False, "why": why}
    uid = livecohost.viewer_id(name, prefix=_UID_PREFIX) if kind != "quiet" else ""
    pace = _pace()
    why = pace.why_not(live, uid)
    if why:
        return {"answered": False, "why": why}
    not_ready = _ai_ready()
    if not_ready:
        return {"answered": False, "why": not_ready}
    pace.busy = True
    started = time.time()
    try:
        with personas.scope(pid):
            response = await livecohost.line(kind, name, text, uid=uid or f"{_UID_PREFIX}everyone", channel=_CHANNEL,
                                             live=live)
        if response:
            # A moment before it shows, as on a real LIVE: the time the model took counts toward it.
            await asyncio.sleep(max(0.0, live["reply_delay"] - (time.time() - started)))
    except Exception as e:
        return {"answered": False, "why": "The AI did not answer", "error": str(e)[:200]}
    finally:
        pace.busy = False
    if not response:
        return {"answered": False, "why": "The AI did not answer"}
    pace.note(uid)
    rid = uuid.uuid4().hex
    answers = _STATE["answers"]
    answers[rid] = (response, pid, livecohost.reading(kind, name, text, live))
    while len(answers) > 60:
        answers.pop(next(iter(answers)))
    return {"answered": True, "id": rid, "text": response}


def _keep_audio(rid: str, chunks: list) -> list:
    """The spoken line's wavs, saved for the page to play; only the newest few dozen practice ones are kept."""
    folder = _audio_dir()
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for i, wav in enumerate(chunks[:8]):
        name = f"demo_{rid}_{i}.wav"
        (folder / name).write_bytes(wav)
        names.append(name)
    # The ones just saved ahead of all: files written within one tick of the file clock share its time.
    fresh = set(names)
    old = sorted(folder.glob("demo_*.wav"), key=lambda p: (p.name in fresh, p.stat().st_mtime_ns), reverse=True)[48:]
    for p in old:
        try:
            p.unlink()
        except OSError:
            pass
    return names


@router.post("/api/live-demo/voice")
async def demo_voice(request: Request):
    """One of the persona's practice lines, said out loud with the voice set up under Models. {audio: [names]}."""
    from app.utils import livecohost, personas
    body = await request.json()
    rid = str(body.get("id") or "")
    hit = _STATE["answers"].get(rid)
    if not re.fullmatch(r"[0-9a-f]{32}", rid) or not hit:
        raise HTTPException(status_code=404, detail="no such line")
    text, pid, read_first = hit
    try:
        with personas.scope(pid):
            chunks = await livecohost.voice(text, read_first)
    except Exception as e:
        return {"audio": [], "why": str(e)[:200] or "the voice did not answer"}
    if not chunks:
        return {"audio": [], "why": "No voice is set up"}
    return {"audio": await asyncio.to_thread(_keep_audio, rid, chunks)}


@router.get("/api/live-demo/audio/{name}")
def demo_audio(name: str):
    """A practice line's wav, by its name only."""
    from fastapi.responses import FileResponse
    if not _AUDIO.fullmatch(name):
        raise HTTPException(status_code=404, detail="no such audio")
    path = _audio_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such audio")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


# ── Its screen: a picture or a video of your own ─────────────────────────────

_SCREEN = "live_screen"
_STILL = f"{_SCREEN}.still.jpg"
_SCREEN_BYTES = 400 * 1024 * 1024
_PICTURE_BYTES = 40 * 1024 * 1024
# What a browser plays as it is, kept as it came when there's no ffmpeg to make it into an MP4.
_PLAYABLE = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm"}
_screen_lock = threading.Lock()


def _guard(request: Request) -> None:
    """Only the panel itself: its own header, and no other website's page (a form anywhere can post a file here)."""
    if request.headers.get("x-llmselfbot") != "1":
        raise HTTPException(status_code=403, detail="Refused.")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host", ""):
        raise HTTPException(status_code=403, detail="Refused.")


def _screen_dir(persona: str) -> Path:
    """The persona's own folder, where its screen is kept. Reads files: off the loop."""
    from app.utils import personas
    if not personas.valid_id(persona) or not personas.exists(persona):
        raise HTTPException(status_code=404, detail="There's no such profile.")
    return personas.folder(persona)


def _screen_path(folder: Path) -> Path | None:
    """The screen itself (not its still), or None."""
    if not folder.is_dir():
        return None
    for p in sorted(folder.glob(f"{_SCREEN}.*")):
        if p.is_file() and p.name != _STILL:
            return p
    return None


def _screen_info(folder: Path) -> dict:
    p = _screen_path(folder)
    if p is None:
        return {"present": False}
    st = p.stat()
    return {"present": True, "kind": "video" if p.suffix.lower() in _PLAYABLE else "image", "size": st.st_size,
            "still": (folder / _STILL).is_file(), "version": st.st_mtime_ns // 1_000_000}


def _clear_screen(folder: Path) -> None:
    for p in folder.glob(f"{_SCREEN}.*") if folder.is_dir() else []:
        try:
            p.unlink()
        except OSError:
            pass


def _save_screen(persona: str, src: Path, original: str, head: bytes) -> dict:
    """One file in as the persona's screen, replacing the one it had: a picture through the Pictures page's importer
    (HEIC and the rest), a video made into an MP4 every browser plays, with a still for its tile."""
    from app.utils import videos
    folder = _screen_dir(persona)
    size = src.stat().st_size
    if size > _SCREEN_BYTES:
        raise HTTPException(status_code=400, detail="That file is over 400 MB.")
    folder.mkdir(parents=True, exist_ok=True)
    if videos.is_video(original, head):
        ext = os.path.splitext(original or "")[1].lower()
        # Named apart from live_screen.*, which is cleared just before this moves in.
        work = folder / f".{_SCREEN}-{uuid.uuid4().hex}.part"
        try:
            if videos.available():
                # Room for a long clip: this is never sent anywhere, only shown here.
                videos.convert(src, work, 1024 * 1024 * 1024)
                ext = ".mp4"
            elif ext in _PLAYABLE:
                shutil.copyfile(src, work)
            else:
                raise HTTPException(status_code=400,
                                    detail="Videos need ffmpeg: get it on the System page, or use an MP4.")
            with _screen_lock:
                _clear_screen(folder)
                os.replace(work, folder / f"{_SCREEN}{ext}")
        except videos.VideoError as e:
            raise HTTPException(status_code=400, detail=str(e))
        finally:
            try:
                work.unlink()
            except OSError:
                pass
        if videos.available():
            try:
                videos.poster(folder / f"{_SCREEN}{ext}", folder / _STILL, 360)
            except Exception:
                pass  # its tile shows a plain video mark instead
        return _screen_info(folder)
    if size > _PICTURE_BYTES:
        raise HTTPException(status_code=400, detail="That picture is over 40 MB.")
    from app.utils.imageimport import convert
    try:
        blob, ext, _note = convert(src.read_bytes(), original or "screen")
    except ValueError:
        raise HTTPException(status_code=400, detail="That isn't a picture or a video.")
    with _screen_lock:
        _clear_screen(folder)
        (folder / f"{_SCREEN}{ext}").write_bytes(blob)
    return _screen_info(folder)


@router.get("/api/live-demo/screen")
def screen_info(persona: str = ""):
    """Whether this persona's practice LIVE has a screen of its own, and what kind. Plain def: it reads files."""
    return _screen_info(_screen_dir(persona))


@router.post("/api/live-demo/screen")
async def screen_upload(request: Request, persona: str = "", file: UploadFile = File(...)):
    """A picture or a video of your own for this persona's practice LIVE to show. Copied to disk in pieces and
    converted on a thread: a video can be big."""
    from app.utils import videos
    _guard(request)
    head = await file.read(64)
    await file.seek(0)
    if not head:
        raise HTTPException(status_code=400, detail="That file is empty.")
    original = file.filename or ""
    tmp = await asyncio.to_thread(videos.spool, file.file, os.path.splitext(original)[1])
    try:
        return await asyncio.to_thread(_save_screen, persona, tmp, original, head)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


@router.get("/api/live-demo/screen/file")
def screen_file(persona: str = "", still: bool = False):
    """The screen, or a video's still for its tile. Its address changes with the file, so it's kept for good."""
    from fastapi.responses import FileResponse
    folder = _screen_dir(persona)
    path = folder / _STILL if still else _screen_path(folder)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="It has no screen of its own.")
    media = "image/jpeg" if still else _PLAYABLE.get(path.suffix.lower())
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=31536000, immutable",
                                                         "X-Content-Type-Options": "nosniff"})


@router.delete("/api/live-demo/screen")
def screen_remove(request: Request, persona: str = ""):
    """Its screen of its own, gone: the practice LIVE shows what's picked for it instead. Plain def: it deletes files."""
    _guard(request)
    folder = _screen_dir(persona)
    with _screen_lock:
        _clear_screen(folder)
    return {"present": False}
