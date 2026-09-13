"""
app/web/routes/env_routes.py - edit every value in config/.env from the app.

Two sources are merged so the editor shows the whole surface, not just what
happens to be set already:

  * keys present in config/.env
  * keys documented in resources/example.env, including commented-out ones,
    with the comment block above each carried through as help text

That means an option the user has never set (SNAP_QUIET_HOURS, say) is still
listed, described, and one click away from being filled in.

Secret values are masked on read and only written when actually changed; the
account tokens have their own dedicated editor (see account_routes) but remain
visible here as masked entries so nothing in the file is hidden from the owner.
"""

import re

from fastapi import APIRouter, HTTPException, Request

from app.utils.paths import APP_DIR
from app.web.envfile import SECRET_KEYS, mask, read_env, reload_into_process, write_env

router = APIRouter(tags=["env"])

TEMPLATE = APP_DIR / "resources" / "example.env"

# Keys the account editor owns. Still listed (masked) so the file is fully
# visible, but flagged so the UI can point at the better tool for them.
_ACCOUNT_KEY = re.compile(
    r"^(DISCORD_TOKEN|DISCORD_PROXY|SNAP_USERNAME|SNAP_PASSWORD)(_\d+)?$")

_VALID_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$", re.IGNORECASE)


def _strip_trailing_comment(value: str) -> str:
    """Drop an aligned trailing comment from a template example.

    "9000       # min ms between sends" is documentation, not part of the
    value. Only a comment set off by whitespace counts, so a value that
    legitimately contains '#' survives.
    """
    text = value.strip()
    cut = re.search(r"\s+#", text)
    return text[:cut.start()].strip() if cut else text


def _template() -> dict:
    """Parse resources/example.env into {key: {"help", "example", "section"}}.

    The template is well commented, and those comments are the only
    documentation these settings have, so they become the field help rather
    than being thrown away.
    """
    out: dict[str, dict] = {}
    if not TEMPLATE.exists():
        return out
    comment: list[str] = []
    section = "General"
    for raw in TEMPLATE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            comment.clear()
            continue
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            if not body:
                continue
            # A rule made of dashes or box characters either names a section
            # ("── Discord ──────") or is pure decoration ("═════════"), which
            # must not be swept up as help text for the next option.
            stripped = body.strip("-─═ ").strip()
            if body.strip("-─═ ") != body or set(body) <= set("-─═ "):
                if stripped and any(body.count(c) >= 3 for c in "-─═"):
                    section = stripped
                comment.clear()
                continue
            # A commented-out assignment is a documented-but-unset option.
            if "=" in body and _VALID_KEY.match(body.split("=", 1)[0].strip()):
                key, _, val = body.partition("=")
                out.setdefault(key.strip(), {
                    "help": " ".join(comment).strip(),
                    "example": _strip_trailing_comment(val),
                    "section": section,
                })
                continue
            comment.append(body)
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            out.setdefault(key.strip(), {
                "help": " ".join(comment).strip(),
                "example": _strip_trailing_comment(val),
                "section": section,
            })
            comment.clear()
    return out


def _rows() -> list:
    values = read_env()
    meta = _template()
    keys = sorted(set(values) | set(meta))
    rows = []
    for key in keys:
        raw = values.get(key, "")
        secret = bool(SECRET_KEYS.match(key))
        rows.append({
            "key": key,
            "value": mask(raw) if (secret and raw) else raw,
            "secret": secret,
            "set": bool(raw.strip()),
            "managed": bool(_ACCOUNT_KEY.match(key)),
            "help": meta.get(key, {}).get("help", ""),
            "example": meta.get(key, {}).get("example", ""),
            "section": meta.get(key, {}).get("section", "Other"),
        })
    return rows


# ── Numbered key families ────────────────────────────────────────────────────
# NAME_1, NAME_2, ... are read in order and must stay contiguous: the loaders
# stop at the first gap, so deleting #2 of 3 has to renumber #3 down to #2 or
# the last key silently stops being used.
# A family is a numbered credential, optionally with fields that belong to the
# same slot: a Discord token has a proxy, a Snapchat username has a password.
# Those extras must renumber together with the main value, or deleting account
# #2 of 3 would leave #3's password attached to #2.
KEY_FAMILIES = {
    "groq": {
        "prefix": "GROQ_API_KEY",
        "label": "Groq API key",
        "secret": True,
        "extras": [],
    },
    "discord": {
        "prefix": "DISCORD_TOKEN",
        "label": "Discord account",
        "secret": True,
        "extras": [{"prefix": "DISCORD_PROXY", "label": "Proxy", "secret": False,
                    "placeholder": "http://user:pass@host:port, optional"}],
    },
    "snapchat": {
        "prefix": "SNAP_USERNAME",
        "label": "Snapchat account",
        "secret": False,
        "extras": [{"prefix": "SNAP_PASSWORD", "label": "Password", "secret": True,
                    "placeholder": "password"}],
    },
}


def _family(name: str) -> dict:
    fam = KEY_FAMILIES.get(name)
    if not fam:
        raise HTTPException(status_code=404, detail=f"unknown key family: {name}")
    return fam


def _family_values(values: dict, prefix: str) -> list:
    """The numbered keys, in order. A legacy unsuffixed key counts as #1."""
    out = []
    if values.get(prefix, "").strip() and not values.get(f"{prefix}_1", "").strip():
        out.append(values[prefix].strip())
    i = 1
    while values.get(f"{prefix}_{i}", "").strip():
        out.append(values[f"{prefix}_{i}"].strip())
        i += 1
    return out


def _clear_numbered(values: dict, prefix: str) -> None:
    old = 1
    while f"{prefix}_{old}" in values:
        values.pop(f"{prefix}_{old}")
        old += 1
    values.pop(prefix, None)


def _write_family(values: dict, prefix: str, keys: list) -> dict:
    """Rewrite the family as a contiguous NAME_1..N, dropping the legacy key."""
    _clear_numbered(values, prefix)
    for i, key in enumerate(keys, start=1):
        values[f"{prefix}_{i}"] = key
    return values


def _write_slots(values: dict, fam: dict, slots: list) -> dict:
    """Rewrite a whole family, extras included, keeping the slots aligned.

    Every field of a slot is renumbered from the same index, so a slot can be
    removed from the middle without its proxy or password ending up attached to
    somebody else's account.
    """
    _write_family(values, fam["prefix"], [s["value"] for s in slots])
    for extra in fam.get("extras", []):
        _clear_numbered(values, extra["prefix"])
        for i, slot in enumerate(slots, start=1):
            value = (slot.get("extras") or {}).get(extra["prefix"], "").strip()
            if value:
                values[f"{extra['prefix']}_{i}"] = value
    return values


def _read_slots(values: dict, fam: dict) -> list:
    """Every slot in the family, with its extras, in order."""
    out = []
    for i, value in enumerate(_family_values(values, fam["prefix"]), start=1):
        extras = {}
        for extra in fam.get("extras", []):
            # Slot 1 may still be stored under the unnumbered legacy name.
            raw = values.get(f"{extra['prefix']}_{i}", "")
            if not raw and i == 1:
                raw = values.get(extra["prefix"], "")
            extras[extra["prefix"]] = raw.strip()
        out.append({"index": i, "value": value, "extras": extras})
    return out


def _family_rows(values: dict, prefix: str, fam: dict = None) -> list:
    fam = fam or {"prefix": prefix, "secret": True, "extras": []}
    rows = []
    for slot in _read_slots(values, fam):
        extras = {}
        for extra in fam.get("extras", []):
            raw = slot["extras"].get(extra["prefix"], "")
            extras[extra["prefix"]] = {
                "preview": (mask(raw) if extra.get("secret") else raw) if raw else "",
                "set": bool(raw),
            }
        rows.append({
            "index": slot["index"],
            "preview": mask(slot["value"]) if fam.get("secret", True) else slot["value"],
            "set": True,
            "extras": extras,
        })
    return rows


@router.get("/api/env/keys/{name}")
async def list_keys(request: Request, name: str):
    fam = _family(name)
    return {"prefix": fam["prefix"], "label": fam["label"],
            "secret": fam.get("secret", True),
            "extras": fam.get("extras", []),
            "keys": _family_rows(read_env(), fam["prefix"], fam)}


@router.post("/api/env/keys/{name}")
async def add_key(request: Request, name: str):
    fam = _family(name)
    body = await request.json()
    value = str(body.get("value", "")).strip()
    if not value:
        raise HTTPException(status_code=400, detail="a value is required")
    values = read_env()
    keys = _family_values(values, fam["prefix"])
    if len(keys) >= 50:
        raise HTTPException(status_code=400, detail="too many keys")
    slots = _read_slots(values, fam)
    slots.append({"index": len(slots) + 1, "value": value,
                  "extras": {e["prefix"]: str(body.get(e["prefix"], "")).strip()
                             for e in fam.get("extras", [])}})
    values = _write_slots(values, fam, slots)
    write_env(values)
    reload_into_process(values)
    return {"ok": True, "keys": _family_rows(values, fam["prefix"], fam)}


@router.post("/api/env/keys/{name}/{index}")
async def replace_key(request: Request, name: str, index: int):
    fam = _family(name)
    body = await request.json()
    value = str(body.get("value", "")).strip()
    values = read_env()
    keys = _family_values(values, fam["prefix"])
    if not 1 <= index <= len(keys):
        raise HTTPException(status_code=404, detail="no such key")
    # Editing only a proxy or a password should not mean retyping the token
    # above it, which is masked and cannot be read back.
    keep = bool(body.get("keep")) and not value
    if not value and not keep:
        raise HTTPException(status_code=400, detail="a value is required")
    slots = _read_slots(values, fam)
    if not keep:
        slots[index - 1]["value"] = value
    for extra in fam.get("extras", []):
        if extra["prefix"] in body:
            slots[index - 1]["extras"][extra["prefix"]] = str(body[extra["prefix"]]).strip()
    values = _write_slots(values, fam, slots)
    write_env(values)
    reload_into_process(values)
    return {"ok": True, "keys": _family_rows(values, fam["prefix"], fam)}


@router.delete("/api/env/keys/{name}/{index}")
async def delete_key(request: Request, name: str, index: int):
    fam = _family(name)
    values = read_env()
    keys = _family_values(values, fam["prefix"])
    if not 1 <= index <= len(keys):
        raise HTTPException(status_code=404, detail="no such key")
    slots = _read_slots(values, fam)
    slots.pop(index - 1)
    values = _write_slots(values, fam, slots)
    write_env(values)
    reload_into_process(values)
    return {"ok": True, "keys": _family_rows(values, fam["prefix"], fam)}


@router.get("/api/env")
async def get_env(request: Request):
    return {"vars": _rows()}


@router.post("/api/env")
async def post_env(request: Request):
    """Apply edits. `updates` sets values, `deletes` removes keys entirely."""
    body = await request.json()
    updates = body.get("updates") or {}
    deletes = body.get("deletes") or []
    if not isinstance(updates, dict) or not isinstance(deletes, list):
        raise HTTPException(status_code=400, detail="updates must be an object, deletes a list")

    values = read_env()
    for key, value in updates.items():
        if not _VALID_KEY.match(str(key)):
            raise HTTPException(status_code=400, detail=f"invalid key: {key}")
        text = "" if value is None else str(value)
        # A masked value came straight back from a GET untouched, writing it
        # would replace the real secret with literal bullet characters.
        if SECRET_KEYS.match(key) and ("…" in text or set(text.strip()) == {"•"}):
            continue
        values[str(key)] = text.strip()

    for key in deletes:
        values.pop(str(key), None)

    write_env(values)
    reload_into_process(values)
    return {"ok": True, "vars": _rows()}
