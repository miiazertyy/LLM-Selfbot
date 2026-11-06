"""A Microsoft (premium) Minecraft account's skin, changed from the panel.

Minecraft keeps a premium account's skin itself (api.minecraftservices.com), so changing it takes the account's own
login: ms_skin.mjs, beside mindcraft, with the very login its bot plays with. A picture put on it, classic or slim
arms; or its skin taken off, so it wears the game's default again. The card's picture is drawn from the new skin
here and then, rather than asked of Mojang, which goes on serving the old one for a while after a change.

An account with no account ("offline") has no skin of its own to change: the server it plays on decides what it looks
like.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid as _uuid
from pathlib import Path

SIZES = ((64, 64), (64, 32))
MAX_BYTES = 256 * 1024


def check_png(png: bytes) -> str:
    """Why a picture cannot be a skin, or "" when it can: a PNG, 64 by 64 (or the old 64 by 32)."""
    from app.platforms.minecraft.skins import skin_size
    if not png:
        return "No picture came with it."
    if len(png) > MAX_BYTES:
        return "That picture is too big to be a skin."
    size = skin_size(png)
    if size is None:
        return "A skin is a PNG picture."
    if size not in SIZES:
        return f"A skin is 64 by 64 pixels. That one is {size[0]} by {size[1]}."
    return ""


def _run(name: str, png: bytes | None, slim: bool, timeout: float, keep: bool = False) -> dict:
    from app.platforms.minecraft import install
    from app.platforms.minecraft.ms_signin import _requirements
    from app.utils.procs import quiet_kwargs
    node, script, problem = _requirements("ms_skin.mjs")
    if problem:
        return {"ok": False, "reason": problem}
    kept = b""
    with tempfile.TemporaryDirectory(prefix="lsb-skin-") as tmp:
        env = {**os.environ, "LSB_MC_DIR": str(install.MC_DIR), "LSB_MC_NAME": name,
               "LSB_SKIN_VARIANT": "slim" if slim else "classic"}
        out = Path(tmp) / "kept.png"
        if png is not None:
            path = Path(tmp) / "skin.png"
            path.write_bytes(png)
            env["LSB_SKIN_FILE"] = str(path)
        elif keep:
            env.update(LSB_SKIN_KEEP="1", LSB_SKIN_OUT=str(out))
        else:
            env["LSB_SKIN_RESET"] = "1"
        try:
            p = subprocess.run([node, script], cwd=str(install.MC_DIR), env=env, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace", **quiet_kwargs())
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "Minecraft took too long to answer. Try again in a moment."}
        except OSError as exc:
            return {"ok": False, "reason": f"The skin could not be changed ({type(exc).__name__})."}
        if out.is_file():
            kept = out.read_bytes()
    said = {}
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                said = json.loads(line)
            except ValueError:
                continue
    if said.get("done"):
        return {"ok": True, "url": str(said.get("url") or ""), "variant": str(said.get("variant") or ""),
                "id": str(said.get("id") or ""), "kept": kept}
    return {"ok": False, "reason": str(said.get("error") or "Minecraft did not say whether it worked.")[:300]}


def change(account: int, name: str, png: bytes | None, slim: bool = False, timeout: float = 90.0,
           keep: bool = False) -> dict:
    """Put a skin on the account (png); put the one it has back on with other arms (keep); or take its skin off
    (neither). `name` is the one it was added under, which its login is kept by. {"ok", "reason"?, "slim"}."""
    if png is not None:
        why = check_png(png)
        if why:
            return {"ok": False, "reason": why}
    done = _run(name, png, slim, timeout, keep=keep and png is None)
    if not done.get("ok"):
        return done
    from app.platforms.minecraft import skins
    png = png if png is not None else (done.get("kept") or None)
    try:
        if png is not None:
            skins.keep_picture(account, name, png, done.get("variant") == "slim" or slim, "mojang")
        else:
            # The game's own default for this account, which is what it wears with none: picked by its id.
            ident = _uuid.UUID(done["id"]) if done.get("id") else skins.offline_uuid(name)
            which, thin = skins.default_for(ident)
            skins.keep_picture(account, name, skins.default_png(which, thin), thin, "default", which)
    except Exception:
        pass   # the skin changed; the card catches up the next time it looks
    return {"ok": True, "slim": done.get("variant") == "slim" if done.get("variant") else bool(slim)}


def current(account: int) -> dict:
    """What the card knows of its skin: classic or slim arms, where it came from, and its picture standing up."""
    import base64
    from app.utils.paths import DATA_DIR
    cfg = DATA_DIR / "config"
    stem = f"identity_minecraft_{int(account)}"
    try:
        data = json.loads((cfg / f"{stem}.json").read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    body = cfg / f"{stem}_body.png"
    picture = ""
    if body.is_file():
        picture = "data:image/png;base64," + base64.b64encode(body.read_bytes()).decode("ascii")
    return {"slim": bool(data.get("slim")), "source": str(data.get("skin_source") or ""),
            "skin": str(data.get("skin") or ""), "picture": picture}
