"""
app/web/routes/prefs_routes.py - panel preferences, kept with the app.

Theme, typeface, the dashboard layout and the rest were held in the browser's
localStorage, which loses them in two ordinary situations:

  * The desktop shell ran the webview in private mode, so everything was thrown
    away when the app closed.
  * localStorage is keyed on the origin, and the port is not fixed: when 8787
    is busy the app takes 8788, which is a different origin and therefore an
    empty store. Relaunching before the old instance had exited was enough.

Keeping them here fixes both, and means the panel looks the same opened from a
phone as it does on the machine, which the browser could never do.

These are display preferences, nothing the bot reads: config.yaml stays the
place for anything that changes behaviour.
"""

import json
import threading

from fastapi import APIRouter, HTTPException, Request

from app.utils.paths import DATA_DIR

router = APIRouter(tags=["prefs"])

PREFS_PATH = DATA_DIR / "config" / "panel.json"

# Only these keys are stored. An open dictionary would let a stray page write
# whatever it liked into a file the app reads on every start.
ALLOWED = {
    "theme", "font", "snow", "motion", "dashOrder", "rail",
    # Whether the uploaded backdrop is in use, and how far it is dimmed. The
    # image itself lives in config/appearance/; these are just the choice.
    "customBgOn", "customBgDim",
    # Which living background is drawn behind the app, and how solid the
    # cards sitting on it are.
    "backdrop", "surface",
}

_lock = threading.Lock()


def _read() -> dict:
    try:
        data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in ALLOWED} if isinstance(data, dict) else {}
    except Exception:
        return {}


@router.get("/api/prefs")
async def get_prefs(request: Request):
    return {"prefs": _read()}


@router.post("/api/prefs")
async def set_prefs(request: Request):
    """Merge in whatever changed. A partial write must not drop the rest."""
    body = await request.json()
    updates = body.get("prefs")
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="prefs must be an object")

    unknown = set(updates) - ALLOWED
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"not a panel preference: {', '.join(sorted(unknown))}")

    with _lock:
        current = _read()
        current.update(updates)
        try:
            PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            PREFS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "prefs": current}
