"""
app/web/routes/account_routes.py - add, edit and remove account slots.

An "account" is a numbered set of credentials in config/.env:

    Discord   DISCORD_TOKEN_<n>   DISCORD_PROXY_<n>
    Snapchat  SNAP_USERNAME_<n>   SNAP_PASSWORD_<n>

The numbering must stay contiguous from 1, because the account counters stop at
the first gap, so deleting slot 2 of 3 renumbers the old slot 3 down to 2.

Credentials are write-only. A GET never returns a token or password, not even
masked: it reports whether one is set, and the UI can only replace it.
"""

from fastapi import APIRouter, HTTPException, Request

from app.web.envfile import read_env, reload_into_process, write_env

router = APIRouter(tags=["accounts"])

PLATFORMS = {
    "discord": {
        "fields": {"token": "DISCORD_TOKEN", "proxy": "DISCORD_PROXY"},
        "secret": ("token",),
        "required": "token",
    },
    "snapchat": {
        "fields": {"username": "SNAP_USERNAME", "password": "SNAP_PASSWORD"},
        "secret": ("password",),
        "required": "username",
    },
}
MAX_SLOTS = 50


def _platform(name: str) -> dict:
    spec = PLATFORMS.get(name)
    if not spec:
        raise HTTPException(status_code=404, detail=f"unknown platform: {name}")
    return spec


def _key(prefix: str, index: int) -> str:
    return f"{prefix}_{index}"


def _migrate_legacy(values: dict) -> dict:
    """Fold the old unsuffixed keys (DISCORD_TOKEN) into slot 1.

    Both spellings are read by the counters, so leaving the bare key in place
    alongside a numbered one would make a single account look like two.
    """
    for spec in PLATFORMS.values():
        for prefix in spec["fields"].values():
            bare = values.pop(prefix, None)
            if bare and not values.get(_key(prefix, 1)):
                values[_key(prefix, 1)] = bare
    return values


def _count(values: dict, platform: str) -> int:
    prefix = PLATFORMS[platform]["fields"][PLATFORMS[platform]["required"]]
    n = 0
    while values.get(_key(prefix, n + 1), "").strip():
        n += 1
    return n


def _slots(values: dict) -> list:
    out = []
    for platform, spec in PLATFORMS.items():
        for i in range(1, _count(values, platform) + 1):
            row = {"id": f"{platform}_{i}", "platform": platform, "index": i}
            for field, prefix in spec["fields"].items():
                val = values.get(_key(prefix, i), "").strip()
                if field in spec["secret"]:
                    # Never leaves the server, not even masked.
                    row[f"{field}_set"] = bool(val)
                else:
                    row[field] = val
            out.append(row)
    return out


@router.get("/api/accounts/slots")
async def list_slots(request: Request):
    return {"slots": _slots(_migrate_legacy(read_env())), "platforms": list(PLATFORMS)}


@router.post("/api/accounts/slots/{platform}")
async def add_slot(request: Request, platform: str):
    """Append a new account. The body carries its initial credentials."""
    spec = _platform(platform)
    body = await request.json()
    values = _migrate_legacy(read_env())

    required = spec["required"]
    if not str(body.get(required, "")).strip():
        raise HTTPException(status_code=400, detail=f"{required} is required")
    index = _count(values, platform) + 1
    if index > MAX_SLOTS:
        raise HTTPException(status_code=400, detail="too many accounts")

    for field, prefix in spec["fields"].items():
        values[_key(prefix, index)] = str(body.get(field, "")).strip()

    write_env(values)
    reload_into_process(values)
    return {"ok": True, "index": index, "slots": _slots(values)}


@router.post("/api/accounts/slots/{platform}/{index}")
async def update_slot(request: Request, platform: str, index: int):
    """Replace fields on an existing account.

    A field that is absent, or sent as an empty string, is left untouched - 
    that is what lets the UI edit the proxy without knowing the token.
    """
    spec = _platform(platform)
    body = await request.json()
    values = _migrate_legacy(read_env())

    if not 1 <= index <= _count(values, platform):
        raise HTTPException(status_code=404, detail="no such account")

    for field, prefix in spec["fields"].items():
        if field not in body:
            continue
        new = str(body[field] or "").strip()
        if not new:
            # Clearing the required field would orphan the slot; use DELETE.
            if field == spec["required"] or field in spec["secret"]:
                continue
            values[_key(prefix, index)] = ""
        else:
            values[_key(prefix, index)] = new

    write_env(values)
    reload_into_process(values)
    return {"ok": True, "slots": _slots(values)}


@router.delete("/api/accounts/slots/{platform}/{index}")
async def delete_slot(request: Request, platform: str, index: int):
    """Remove an account and close the gap so the numbering stays contiguous."""
    spec = _platform(platform)
    values = _migrate_legacy(read_env())
    total = _count(values, platform)
    if not 1 <= index <= total:
        raise HTTPException(status_code=404, detail="no such account")

    for prefix in spec["fields"].values():
        # Shift every later slot down one, then drop the now-duplicate tail.
        for i in range(index, total):
            values[_key(prefix, i)] = values.get(_key(prefix, i + 1), "")
        values.pop(_key(prefix, total), None)

    write_env(values)
    reload_into_process(values)

    # Stop the child that was running this slot, if any: its credentials are
    # gone and the numbering it was started with no longer refers to it.
    supervisor = request.app.state.supervisor
    if supervisor is not None:
        for child_id in (f"{platform}_{i}" for i in range(index, total + 1)):
            try:
                supervisor.stop(child_id)
            except Exception:
                pass

    return {"ok": True, "slots": _slots(values)}
