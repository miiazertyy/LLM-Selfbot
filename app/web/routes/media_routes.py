import base64
import os

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.utils.paths import DATA_DIR
from app.web.logbus import bus

router = APIRouter(tags=["media"])

PICTURES_DIR = DATA_DIR / "config" / "pictures"
_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _files():
    if not PICTURES_DIR.exists():
        return []
    return sorted(
        [f for f in os.listdir(PICTURES_DIR) if os.path.splitext(f)[1].lower() in _EXTS],
        key=lambda f: int(os.path.splitext(f)[0][4:])
        if os.path.splitext(f)[0].startswith("IMG_") and os.path.splitext(f)[0][4:].isdigit()
        else 99999,
    )


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


@router.get("/api/pictures")
async def pictures(request: Request):
    from app.utils.db import get_picture_description
    out = []
    for f in _files():
        try:
            size = (PICTURES_DIR / f).stat().st_size
        except OSError:
            size = 0
        out.append({
            "name": f,
            "description": get_picture_description(f) or "",
            "size": size,
        })
    return {"pictures": out}


def _save(data: bytes, original: str) -> tuple[str, bytes]:
    """Normalise one image and write it into the pictures folder."""
    from app.utils.imageimport import convert
    blob, ext, note = convert(data, original)
    PICTURES_DIR.mkdir(parents=True, exist_ok=True)
    name = f"IMG_{_next_index()}{ext}"
    (PICTURES_DIR / name).write_bytes(blob)
    if note:
        bus.append("pictures", f"{os.path.basename(original) or name}: {note}")
    return name, blob


# Describing a zip of thirty photos is thirty model calls, which is far longer
# than a request should stay open. The files land immediately and the
# descriptions fill in behind them, with progress the page can poll.
_describe_state = {"running": False, "total": 0, "done": 0, "failed": 0, "reason": ""}
_describe_queue: list = []
_describe_task = None


async def _describe_pending():
    """Describe everything queued, including anything added while running.

    Dropping a second archive mid pass used to leave its pictures with no
    description and no sign of why, because the guard simply refused to start a
    second task. The queue is drained instead, so a later batch joins the one
    already going.
    """
    import asyncio
    _describe_state.update(running=True, done=0, failed=0, reason="")
    try:
        while _describe_queue:
            name = _describe_queue.pop(0)
            _describe_state["total"] = _describe_state["done"] + len(_describe_queue) + 1
            try:
                path = PICTURES_DIR / name
                if not path.exists():
                    continue
                ext = os.path.splitext(name)[1].lower()

                # A per minute limit clears by waiting, so a rate limited
                # picture is worth a second and third go. Anything else is a
                # real failure and retrying it just wastes the allowance.
                description, reason = "", ""
                for attempt, backoff in enumerate((0, 20, 40)):
                    if backoff:
                        _describe_state["reason"] = (
                            f"Waiting {backoff}s for the rate limit to clear.")
                        await asyncio.sleep(backoff)
                    description, reason = await _describe(name, path.read_bytes(), ext)
                    if description or "rate" not in reason.lower():
                        break
                _describe_state["reason"] = ""

                if description:
                    bus.append("pictures", f"Described {name}.")
                else:
                    _describe_state["failed"] += 1
                    _describe_state["reason"] = reason
                    bus.append("pictures", f"Could not describe {name}: {reason}", "warn")
            except Exception as exc:
                # One bad file must not stop the rest of the batch, and an
                # escaping exception here would be an unhandled task error.
                _describe_state["failed"] += 1
                _describe_state["reason"] = str(exc)
                bus.append("pictures", f"Could not describe {name}: {exc}", "warn")
            finally:
                _describe_state["done"] += 1
            # Spacing the calls out keeps a batch under the per minute ceiling
            # instead of tripping it on the second picture.
            if _describe_queue:
                await asyncio.sleep(3)
    finally:
        _describe_state["running"] = False
        failed = _describe_state["failed"]
        bus.append("pictures",
                   "Finished describing the new pictures."
                   if not failed else
                   f"Finished, {failed} could not be described.",
                   "warn" if failed else "info")


@router.post("/api/pictures/describe-missing")
async def describe_missing(request: Request):
    """Describe every picture that has none, one after another.

    A batch can end up part described when the provider rate limits partway
    through, and re-running each one by hand is not a reasonable way out.
    """
    import asyncio
    from app.utils.db import get_picture_description

    global _describe_task
    pending = [f for f in _files() if not (get_picture_description(f) or "").strip()]
    pending = [f for f in pending if f not in _describe_queue]
    if not pending:
        return {"ok": True, "queued": 0, "running": _describe_state["running"]}
    _describe_queue.extend(pending)
    if not _describe_state["running"]:
        _describe_task = asyncio.create_task(_describe_pending())
    return {"ok": True, "queued": len(pending), "running": True}


@router.get("/api/pictures/status")
async def describe_status(request: Request):
    """Progress of the background pass that describes a freshly imported batch."""
    return dict(_describe_state)


@router.post("/api/pictures")
async def upload(request: Request, file: UploadFile = File(...)):
    """Take an image in any format, or a zip full of them.

    A zip is walked recursively, so the usual "right click the folder, send to
    compressed" shape works. Anything the machine can decode is converted into
    something the bot can actually send.
    """
    import asyncio
    from app.utils.imageimport import is_zip

    global _describe_task

    data = await file.read()
    original = file.filename or ""
    if not data:
        raise HTTPException(status_code=400, detail="that file is empty")

    # ── A whole archive ──────────────────────────────────────────────────────
    if is_zip(data, original):
        from app.utils.imageimport import iter_zip
        added, skipped = [], []
        try:
            members = list(iter_zip(data))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"could not read that zip: {exc}")
        for member, blob in members:
            try:
                name, _ = _save(blob, member)
                added.append(name)
            except ValueError as exc:
                skipped.append({"name": os.path.basename(member), "reason": str(exc)})
            except Exception as exc:
                skipped.append({"name": os.path.basename(member),
                                "reason": f"{type(exc).__name__}: {exc}"})
        if not added and not skipped:
            raise HTTPException(status_code=400, detail="no images in that zip")
        bus.append("pictures",
                   f"Imported {len(added)} picture(s) from {os.path.basename(original) or 'a zip'}"
                   + (f", skipped {len(skipped)}" if skipped else "") + ".")
        if added:
            _describe_queue.extend(added)
            if not _describe_state["running"]:
                _describe_task = asyncio.create_task(_describe_pending())
        return {"ok": True, "zip": True, "added": added, "skipped": skipped,
                "describing": bool(added)}

    # ── A single picture ─────────────────────────────────────────────────────
    try:
        name, blob = _save(data, original)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    description, reason = await _describe(name, blob, os.path.splitext(name)[1].lower())
    return {"ok": True, "name": name, "description": description, "reason": reason,
            "added": [name], "skipped": []}


async def _describe(name: str, data: bytes, ext: str):
    """Ask the model what is in the picture.

    Returns the description and, when there is none, the reason. Swallowing the
    failure silently left the page showing "no description" with no way to tell
    a missing key from a model that was down.
    """
    try:
        if not (os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY_1")):
            from dotenv import load_dotenv
            from app.utils.helpers import get_env_path
            load_dotenv(dotenv_path=get_env_path(), override=True)
        if not (os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY_1")):
            return "", "No Groq key set, so nothing can look at the picture."

        from app.utils.ai import init_ai, _create_image_completion
        from app.utils.helpers import load_config
        from app.utils.humanize import plain_text
        init_ai()
        model = load_config()["bot"].get(
            "groq_image_model", "meta-llama/llama-4-scout-17b-16e-instruct")
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext[1:]}"
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        resp = await _create_image_completion(
            model,
            messages=[{
                "role": "user",
                "content": [
                    # Plain prose, and bounded. The old prompt asked for "full
                    # detail" and got a structured essay: about 1700 output
                    # tokens, which on Groq's free tier is over the per minute
                    # ceiling, so the request was refused outright rather than
                    # answered. A few sentences is all the picture matching
                    # needs anyway.
                    {"type": "text", "text":
                        "Describe this image in 3 to 5 plain sentences: who or what is in it, "
                        "what they are wearing or doing, the setting, and any visible text. "
                        "Write flowing prose only. No headings, no lists, no bold, no preamble."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            # Keeps the request inside the free tier's output budget, and stops
            # a reasoning model spending the whole allowance on its monologue.
            max_tokens=400,
            reasoning_effort="none",
        )
        raw = (resp.choices[0].message.content or "")
        description = plain_text(raw)
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
async def analyse(request: Request, name: str):
    """Describe a picture again, for one that arrived without a description."""
    path = PICTURES_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="picture not found")
    ext = os.path.splitext(name)[1].lower()
    description, reason = await _describe(name, path.read_bytes(), ext)
    return {"ok": bool(description), "description": description, "reason": reason}


@router.post("/api/pictures/{name}/desc")
async def set_desc(request: Request, name: str):
    body = await request.json()
    description = (body.get("description") or "").strip()
    if not (PICTURES_DIR / name).exists():
        raise HTTPException(status_code=404, detail="picture not found")
    if not description:
        raise HTTPException(status_code=400, detail="description required")
    from app.utils.db import add_picture_description
    add_picture_description(name, description)
    return {"ok": True}


@router.delete("/api/pictures/{name}")
async def delete(request: Request, name: str):
    path = PICTURES_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="picture not found")
    path.unlink()
    from app.utils.db import delete_picture_db, rename_picture_db
    delete_picture_db(name)
    for i, fname in enumerate(_files(), start=1):
        stem, ext = os.path.splitext(fname)
        if stem.startswith("IMG_") and stem[4:].isdigit() and int(stem[4:]) != i:
            new = f"IMG_{i}{ext}"
            os.rename(PICTURES_DIR / fname, PICTURES_DIR / new)
            rename_picture_db(fname, new)
    return {"ok": True}


@router.get("/api/pictures/{name}")
async def download(request: Request, name: str):
    path = PICTURES_DIR / name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="picture not found")
    from fastapi.responses import FileResponse
    return FileResponse(path)
