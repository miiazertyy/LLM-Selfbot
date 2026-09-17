"""
app/web/routes/appearance_routes.py - a background image and a typeface of
your own.

The built-in themes and faces are shipped with the app. These two are files the
user supplies, so they need somewhere to live that survives an update and is
readable by the panel from another machine on the network. That rules out
localStorage, which is per-origin and was already losing preferences when the
webview ran private or the port moved, and rules out config.yaml, which is text.

One file of each kind at a time. This is a personal look, not a library: a
second upload replaces the first, which is also what makes the UI a single
drop area rather than a gallery with management around it.
"""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from app.utils.paths import DATA_DIR

router = APIRouter(tags=["appearance"])

APPEARANCE_DIR = DATA_DIR / "config" / "appearance"

# Fonts are matched on extension because that is what the @font-face format()
# hint has to agree with; guessing from content sniffing would still leave the
# hint to derive from the name.
FONT_TYPES = {
    ".woff2": ("font/woff2", "woff2"),
    ".woff": ("font/woff", "woff"),
    ".ttf": ("font/ttf", "truetype"),
    ".otf": ("font/otf", "opentype"),
}

# A background is normalised through the same importer the pictures tab uses,
# so a HEIC straight off a phone works here too.
MAX_UPLOAD_BYTES = 40 * 1024 * 1024


def _existing(kind: str) -> Path | None:
    """The stored file for this kind, whatever extension it ended up with."""
    if not APPEARANCE_DIR.is_dir():
        return None
    for path in sorted(APPEARANCE_DIR.glob(f"{kind}.*")):
        if path.is_file():
            return path
    return None


def _clear(kind: str) -> None:
    for path in APPEARANCE_DIR.glob(f"{kind}.*"):
        try:
            path.unlink()
        except OSError:
            pass


def _info(kind: str) -> dict:
    path = _existing(kind)
    if path is None:
        return {"present": False}
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    out = {"present": True, "name": path.name, "size": size}
    if kind == "font":
        out["format"] = FONT_TYPES.get(path.suffix.lower(), ("", ""))[1]
    return out


@router.get("/api/appearance")
def appearance(request: Request):
    """What the user has uploaded, if anything."""
    return {"background": _info("background"), "font": _info("font")}


@router.post("/api/appearance/background")
async def upload_background(request: Request, file: UploadFile = File(...)):
    """Store one image to sit behind the panel."""
    import asyncio

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="that file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400,
                            detail="that image is over 40 MB")

    def _write() -> dict:
        from app.utils.imageimport import convert
        try:
            # Reuse the pictures importer: it handles HEIC, AVIF and the rest,
            # and hands back something every browser can actually display.
            blob, ext, _note = convert(data, file.filename or "background")
        except Exception as exc:
            raise HTTPException(status_code=400,
                                detail=f"could not read that image: {exc}")
        APPEARANCE_DIR.mkdir(parents=True, exist_ok=True)
        _clear("background")
        (APPEARANCE_DIR / f"background{ext}").write_bytes(blob)
        return _info("background")

    # convert() decodes and re-encodes, which is CPU-bound.
    return await asyncio.to_thread(_write)


@router.post("/api/appearance/font")
async def upload_font(request: Request, file: UploadFile = File(...)):
    """Store one typeface for the panel to render in."""
    name = file.filename or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in FONT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="that is not a font file - use .woff2, .woff, .ttf or .otf")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="that file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="that font is over 40 MB")

    APPEARANCE_DIR.mkdir(parents=True, exist_ok=True)
    _clear("font")
    (APPEARANCE_DIR / f"font{ext}").write_bytes(data)
    return _info("font")


@router.get("/api/appearance/background")
def get_background(request: Request):
    path = _existing("background")
    if path is None:
        raise HTTPException(status_code=404, detail="no background uploaded")
    # Named by mtime on the client side, so this can be cached hard: a replaced
    # file changes the URL rather than needing a revalidation.
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


@router.get("/api/appearance/font")
def get_font(request: Request):
    path = _existing("font")
    if path is None:
        raise HTTPException(status_code=404, detail="no font uploaded")
    media, _ = FONT_TYPES.get(path.suffix.lower(), ("application/octet-stream", ""))
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=604800"})


@router.delete("/api/appearance/{kind}")
def remove(kind: str, request: Request):
    if kind not in ("background", "font"):
        raise HTTPException(status_code=404, detail="unknown appearance item")
    _clear(kind)
    return {"ok": True, kind: _info(kind)}
