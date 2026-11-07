"""community.py - community profiles: browsing them, looking inside, adding them, and sharing your own.

Everything lives on GitHub, in the app's own repo (REPO), with no server of ours. Its GitHub Pages site (SITE) lists
every live profile with its stats; the profiles themselves are on a branch of their own (rules.DATA_BRANCH); adding
one downloads its file from the community's release (rules.RELEASE_TAG), which is what GitHub counts as a download.
Sharing opens a request in the repo (an issue) with the signed-in person's token, and the repo's community workflow
checks it with the same rules as here (app/utils/community_rules.py) and publishes it, or says why not. Pictures and
videos travel in the person's own private gist.

What a profile is and may hold: community_rules. Signing in: github_signin. Talking to GitHub: ghhttp. This module is
synchronous and does file and network work; the routes run it on worker threads.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from app.utils import community_rules as rules
from app.utils import ghhttp, github_signin, personas

# The community, as the app ships it. The environment can point a development copy elsewhere; config.yaml can't, so a
# shared settings file can never send anyone to another catalog.
DEFAULT_REPO = "miiazertyy/LLM-Selfbot"
DEFAULT_SITE = "https://miiazertyy.github.io/LLM-Selfbot"
# The GitHub App's client ID ("LLMSelfbot Community", github.com/apps/llmselfbot-community, made 2026-11-07). Public by
# design: the device flow needs no secret.
DEFAULT_CLIENT_ID = "Iv23lixnkoFP4wTqwn27"

INDEX_TTL = 600
META_TTL = 3600
STATS_TTL = 900


class CommunityError(Exception):
    """A plain reason for the person, with the HTTP status the route should answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def repo() -> str:
    r = os.environ.get("LLMSELFBOT_COMMUNITY_REPO") or DEFAULT_REPO
    return r if re.match(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", r) else DEFAULT_REPO


def site() -> str:
    s = (os.environ.get("LLMSELFBOT_COMMUNITY_SITE") or DEFAULT_SITE).rstrip("/")
    return s if ghhttp.allowed(s + "/") else DEFAULT_SITE


def client_id() -> str:
    c = os.environ.get("LLMSELFBOT_COMMUNITY_CLIENT_ID") or DEFAULT_CLIENT_ID
    return c if re.match(r"^[A-Za-z0-9._-]{0,64}$", c) else ""


def cache_dir() -> Path:
    from app.utils.paths import DATA_DIR
    p = DATA_DIR / "cache" / "community"
    p.mkdir(parents=True, exist_ok=True)
    return p


def mine_path() -> Path:
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "config" / "community_mine.json"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    from app.utils.atomic import write_json_atomic
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, data, indent=2)


def _log(text: str, level: str = "info") -> None:
    try:
        from app.web.logbus import bus
        bus.append("community", text, level)
    except Exception:
        pass


# ── The catalog ──────────────────────────────────────────────────────────────

_mem: dict = {}
_locks: dict = {}
_locks_lock = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _locks_lock:
        return _locks.setdefault(name, threading.Lock())


def _site_json(name: str, ttl: int, force: bool = False) -> tuple:
    """(data, how): a file of the site, from memory, the disk or GitHub. how is "fresh", "cached", "offline" (GitHub
    out of reach: the last copy) or "closed" (no site yet). Only one fetch of a name at a time."""
    with _lock_for(name):
        hit = _mem.get(name)
        if hit and not force and time.time() - hit[0] < ttl:
            return hit[1], "cached"
        path = cache_dir() / name
        etag_path = cache_dir() / (name + ".etag")
        headers = {}
        if path.is_file() and etag_path.is_file():
            headers["If-None-Match"] = etag_path.read_text(encoding="utf-8").strip()
        try:
            r = ghhttp.send("GET", f"{site()}/{name}", headers=headers, cap=16_000_000)
        except ghhttp.GitHubError:
            data = _read(path, None)
            if data is not None:
                _mem[name] = (time.time() - ttl + 60, data)
            return data, "offline"
        if r.status == 304:
            data = _read(path, None)
        elif r.status == 200:
            data = r.json()
            if data is None:
                return _read(path, None), "offline"
            _write(path, data)
            etag = r.headers.get("etag") or r.headers.get("ETag") or ""
            if etag:
                etag_path.write_text(etag, encoding="utf-8")
        elif r.status == 404:
            return _read(path, None), "closed"
        else:
            return _read(path, None), "offline"
        _mem[name] = (time.time(), data)
        return data, "fresh"


def _index(force: bool = False) -> tuple:
    data, how = _site_json("index.json", INDEX_TTL, force)
    if not isinstance(data, dict):
        data = {"profiles": [], "totals": {"profiles": 0, "downloads": 0, "week": 0}}
    return data, how


def _meta(force: bool = False) -> dict:
    data, _ = _site_json("meta.json", META_TTL, force)
    return data if isinstance(data, dict) else {}


def entry(slug: str, force: bool = False) -> dict | None:
    if not rules.SLUG.match(str(slug or "")):
        return None
    data, _ = _index(force)
    return next((p for p in data.get("profiles") or [] if p.get("slug") == slug), None)


def installed() -> dict:
    """{slug: {pid, version}} for every profile added from the community (the last one added, per slug)."""
    out = {}
    for pid in personas.ids():
        note = personas.extra(pid, "community")
        if note and rules.SLUG.match(str(note.get("slug") or "")):
            out[note["slug"]] = {"pid": pid, "version": int(note.get("version") or 0)}
    return out


def shared() -> dict:
    """{slug: {pid, version}} for your own profiles that are live, as this computer knows them."""
    out = {}
    for pid in personas.ids():
        note = personas.extra(pid, "shared")
        if note and rules.SLUG.match(str(note.get("slug") or "")):
            out[note["slug"]] = {"pid": pid, "version": int(note.get("version") or 0)}
    return out


def home(force: bool = False) -> dict:
    """Everything the Community view opens with."""
    index, how = _index(force)
    meta = _meta(force and how == "fresh")
    who = github_signin.me()
    mods = {int(m) for m in meta.get("moderators") or [] if str(m).isdigit()}
    return {
        "state": "ok" if how in ("fresh", "cached") else how,
        "fetched": (_mem.get("index.json") or (0,))[0],
        "index": index,
        "meta": {k: meta.get(k) for k in ("tags", "submissions_open", "limits", "settings", "min_app")},
        "me": who,
        "moderator": bool(who["signed_in"] and who["id"] in mods),
        "installed": installed(),
        "shared": shared(),
        "sharing": bool(client_id()) and meta.get("submissions_open", True) is not False,
        "repo": repo(),
        # Yours, to say beside each profile whether it was made for this app ("" for a development build).
        "app": rules.app_version(_version()),
    }


def stats(force: bool = False) -> dict:
    data, how = _site_json("stats.json", STATS_TTL, force)
    return {"state": how, **(data if isinstance(data, dict) else {"days": [], "total": {}, "profiles": {}})}


def site_file(slug: str, name: str, version: int) -> bytes:
    """One of a live profile's files (its text, settings, face, a thumbnail), kept per version so a version is only
    fetched once. Raises CommunityError."""
    if not rules.SLUG.match(slug) or not re.match(r"^(?:profile\.json|persona\.txt|settings\.json|avatar\.jpg|"
                                                  r"thumbs/m\d{2}\.jpg)$", name):
        raise CommunityError("No such file.", 404)
    path = cache_dir() / "files" / f"{slug}-v{int(version)}" / name
    if path.is_file():
        return path.read_bytes()
    try:
        r = ghhttp.send("GET", f"{site()}/profiles/{slug}/{name}", cap=4_000_000)
    except ghhttp.GitHubError as e:
        raise CommunityError(str(e), 502)
    if r.status != 200:
        raise CommunityError("That file isn't there.", 404)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(r.body)
    os.replace(tmp, path)
    _prune_files()
    return r.body


def _prune_files(keep: int = 400) -> None:
    root = cache_dir() / "files"
    try:
        folders = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for p in folders[:-keep]:
        shutil.rmtree(p, ignore_errors=True)


# ── Looking inside ───────────────────────────────────────────────────────────

def _effective(pid: str | None = None) -> dict:
    """Everyone's settings, or a persona's (everyone's with its own on top), flattened."""
    from app.utils.helpers import load_base_config
    from app.web import settings_io
    base = load_base_config() or {}
    if pid:
        base = personas.merged(base, pid)
    return settings_io.flatten(base)


def _setting_rows(settings: dict, against: dict) -> list:
    from app.web import settings_io
    rows = []
    for key, value in settings.items():
        ok = key in rules.ALLOWED
        mine = against.get(key)
        rows.append({"key": key, "label": settings_io.label(key), "value": value, "yours": mine,
                     "same": ok and json.dumps(mine, sort_keys=True) == json.dumps(value, sort_keys=True),
                     "ok": ok, "why": "" if ok else rules.never_reason(key)})
    return rows


def segments(text: str, findings: list) -> list:
    """The text in pieces, the risky ones marked, for the page to light up: [{text, kind?}]."""
    marks = sorted((f for f in findings if f["field"] == "text"), key=lambda f: f["start"])
    out, at = [], 0
    for f in marks:
        if f["start"] < at:
            continue
        if f["start"] > at:
            out.append({"text": text[at:f["start"]]})
        out.append({"text": text[f["start"]:f["end"]], "kind": f["kind"]})
        at = f["end"]
    if at < len(text):
        out.append({"text": text[at:]})
    return out


def inspect(slug: str) -> dict:
    """Everything that would come with a profile, before adding it: its text (risky parts marked), each setting
    beside yours, its pictures and videos, versions and notes, downloads, and whether you have it."""
    e = entry(slug)
    if not e:
        raise CommunityError("That profile isn't in the catalog.", 404)
    v = int(e.get("version") or 1)
    try:
        prof = json.loads(site_file(slug, "profile.json", v).decode("utf-8"))
        text = site_file(slug, "persona.txt", v).decode("utf-8")
        settings = json.loads(site_file(slug, "settings.json", v).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CommunityError("That profile's files couldn't be read.", 502)
    text = rules.normalize_text(text)
    findings = rules.scan({"text": text})
    have = installed().get(slug)
    return {
        "profile": e,
        "changelog": prof.get("changelog") or [],
        "media": prof.get("media") or [],
        "text": text,
        "segments": segments(text, findings),
        "flags": [{"kind": f["kind"], "match": f["match"]} for f in findings],
        "settings": _setting_rows(settings if isinstance(settings, dict) else {}, _effective()),
        "installed": have,
        "update": bool(have and have["version"] < v),
    }


# ── Adding one ───────────────────────────────────────────────────────────────

_install_lock = threading.Lock()


def _download(e: dict, progress=None) -> dict:
    """A profile's file, as the catalog lists it, checked: its size and checksum, then everything inside by the
    rules. Counted by GitHub as a download."""
    slug = e["slug"]
    pkg = e.get("package") or {}
    v = int(e.get("version") or 1)
    name = rules.asset_name(slug, v)
    if pkg.get("name") != name or not re.match(r"^[0-9a-f]{64}$", str(pkg.get("sha256") or "")):
        raise CommunityError("That profile's file isn't listed right.", 502)
    url = f"https://github.com/{repo()}/releases/download/{rules.RELEASE_TAG}/{name}"
    try:
        r = ghhttp.send("GET", url, cap=rules.LIMITS["package_bytes"] + 2_000_000, timeout=180,
                        progress=progress)
    except ghhttp.GitHubError as e2:
        raise CommunityError(str(e2), 502)
    if r.status != 200:
        raise CommunityError(ghhttp.plain(r.status), 502)
    if len(r.body) != int(pkg.get("bytes") or -1) or rules.sha256(r.body) != pkg["sha256"]:
        raise CommunityError("The download doesn't match the catalog. Try again later.", 502)
    try:
        files = rules.read_zip(r.body, media=True)
        manifest = json.loads(files["profile.json"].decode("utf-8"))
        text_raw = files["persona.txt"].decode("utf-8")
        settings_raw = json.loads(files.get("settings.json", b"{}").decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e3:
        raise CommunityError(f"The profile's file is damaged: {e3}", 502)
    meta, p1 = rules.check_meta(manifest, tags=())
    text, p2 = rules.check_text(text_raw)
    # A setting this version doesn't take is left behind (Inspect said so); a bad value of one it does take is not.
    settings_raw = settings_raw if isinstance(settings_raw, dict) else {}
    settings, p3 = rules.check_settings({k: v for k, v in settings_raw.items() if k in rules.ALLOWED})
    problems = p1 + p2 + p3
    if meta["slug"] != slug:
        problems.append("It isn't the profile that was asked for.")
    avatar = b""
    if files.get("avatar.jpg"):
        avatar, p4 = rules.check_avatar(files["avatar.jpg"])
        problems += p4
    listed = {m.get("name"): m for m in manifest.get("media") or [] if isinstance(m, dict)}
    media = []
    for name in sorted(n for n in files if n.startswith("media/")):
        short = name.split("/", 1)[1]
        data = files[name]
        info = listed.get(short)
        if not info or info.get("sha256") != rules.sha256(data):
            problems.append(f"{short} isn't what the profile lists.")
            continue
        if short.endswith(".jpg"):
            try:
                data = rules.reencode_image(data, side=rules.LIMITS["picture_side"])
            except ValueError:
                problems.append(f"{short} isn't a picture.")
                continue
        media.append((short, data))
    if problems:
        raise CommunityError("It didn't pass the checks: " + problems[0], 422)
    return {"meta": meta, "text": text, "settings": settings, "avatar": avatar, "media": media,
            "version": v, "manifest": manifest}


def _overrides_for(name: str, settings: dict) -> dict:
    """Its settings as a persona's own: what differs from everyone's, and the name it answers to."""
    base = _effective()
    wanted = {"bot.trigger": name, **settings}
    return {k: v for k, v in wanted.items()
            if json.dumps(base.get(k), sort_keys=True) != json.dumps(v, sort_keys=True)}


def _sha_text(text: str) -> str:
    return rules.sha256(rules.normalize_text(text).encode("utf-8"))


def _sha_settings(pid: str) -> str:
    own = {k: v for k, v in personas.overrides(pid).items() if k in rules.ALLOWED}
    return rules.sha256(rules.canonical_json(own))


def _sha_avatar(pid: str) -> str:
    p = personas.avatar_path(pid)
    return rules.sha256(p.read_bytes()) if p.is_file() else ""


def _put_media(pid: str, media: list) -> None:
    folder = personas.pictures_dir(pid)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("community-*"):
        try:
            old.unlink()
        except OSError:
            pass
    for short, data in media:
        m = rules.MEDIA_NAME.match(short)
        if not m:
            continue
        dest = folder / f"community-{m.group(1)}.{m.group(2)}"
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, dest)


def install(slug: str, copy: bool = False, progress=None) -> dict:
    """The profile as one of yours: a new profile with its text, its settings as its own, its face, pictures and
    videos. Your accounts, models, keys and limits stay as they are. Returns {pid}."""
    with _install_lock:
        e = entry(slug, force=True) or entry(slug)
        if not e:
            raise CommunityError("That profile isn't in the catalog anymore.", 404)
        have = installed().get(slug)
        if have and not copy:
            raise CommunityError("It's already in your profiles.", 409)
        got = _download(e, progress)
        meta = got["meta"]
        made = personas.create(meta["name"], meta["color"])
        pid = made["id"]
        try:
            personas.save_text(pid, got["text"], backup=False)
            personas.set_overrides(pid, _overrides_for(meta["name"], got["settings"]))
            if got["avatar"]:
                personas.set_avatar(pid, got["avatar"])
            _put_media(pid, got["media"])
            personas.set_extra(pid, "community", {
                "slug": slug, "version": got["version"], "author": meta["author"], "installed": time.time(),
                "text_sha": _sha_text(got["text"]), "settings_sha": _sha_settings(pid), "avatar_sha": _sha_avatar(pid),
            })
        except Exception:
            try:
                personas.delete(pid)
            except Exception:
                pass
            raise
    _log(f"Added the community profile {meta['name']} ({slug} v{got['version']}).")
    return {"pid": pid}


def _source(pid: str) -> dict:
    note = personas.extra(pid, "community")
    if not note:
        raise CommunityError("That profile isn't from the community.", 404)
    return note


def update_preview(pid: str) -> dict:
    """What a newer version changes, read from the catalog's files (which is not a download)."""
    note = _source(pid)
    slug = note["slug"]
    e = entry(slug, force=True) or entry(slug)
    if not e:
        raise CommunityError("That profile isn't in the catalog anymore.", 404)
    v = int(e.get("version") or 1)
    try:
        prof = json.loads(site_file(slug, "profile.json", v).decode("utf-8"))
        text = rules.normalize_text(site_file(slug, "persona.txt", v).decode("utf-8"))
        settings = json.loads(site_file(slug, "settings.json", v).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CommunityError("That profile's files couldn't be read.", 502)
    old_text = rules.normalize_text(personas.read_text(pid))
    old_lines, new_lines = old_text.split("\n"), text.split("\n")
    now, everyone = _effective(pid), _effective()
    settings = settings if isinstance(settings, dict) else {}
    changes = []
    for k in sorted(set(settings) | {x for x in personas.overrides(pid) if x in rules.ALLOWED}):
        if k == "bot.trigger":
            continue
        old, new = now.get(k), settings.get(k, everyone.get(k))
        if json.dumps(old, sort_keys=True) != json.dumps(new, sort_keys=True):
            changes.append({"key": k, "label": _label(k), "old": old, "new": new})
    return {
        "slug": slug, "from": int(note.get("version") or 0), "to": v,
        "notes": [c for c in prof.get("changelog") or [] if int(c.get("version") or 0) > int(note.get("version") or 0)],
        "text": {"changed": old_text != text, "added": len(set(new_lines) - set(old_lines)),
                 "removed": len(set(old_lines) - set(new_lines))},
        "settings": changes,
        "media": len(prof.get("media") or []),
        "edited": _sha_text(old_text) != note.get("text_sha") or _sha_settings(pid) != note.get("settings_sha"),
        "face_kept": _sha_avatar(pid) != note.get("avatar_sha"),
    }


def _label(key: str) -> str:
    from app.web import settings_io
    return settings_io.label(key)


def update(pid: str, confirm: bool = False, progress=None) -> dict:
    """The newer version in place: its text (the old one kept in backups/), its settings (your other settings of this
    profile kept), its face unless you changed it, its pictures and videos. Name, colour, memory and accounts stay."""
    note = _source(pid)
    preview = update_preview(pid)
    if preview["to"] <= preview["from"]:
        raise CommunityError("It's up to date.", 409)
    if preview["edited"] and not confirm:
        raise CommunityError("You changed this profile since you added it. Updating replaces those changes.", 409)
    with _install_lock:
        e = entry(note["slug"])
        got = _download(e, progress)
        from app.utils.paths import DATA_DIR
        backups = DATA_DIR / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        if personas.settings_path(pid).is_file():
            shutil.copyfile(personas.settings_path(pid), backups / f"persona-{pid}-settings-{int(time.time())}.yaml")
        personas.save_text(pid, got["text"])
        own = {k: v for k, v in personas.overrides(pid).items() if k not in rules.ALLOWED or k == "bot.trigger"}
        fresh = _overrides_for(got["meta"]["name"], got["settings"])
        fresh.pop("bot.trigger", None)
        personas.set_overrides(pid, {**own, **fresh})
        if got["avatar"] and not preview["face_kept"]:
            personas.set_avatar(pid, got["avatar"])
        _put_media(pid, got["media"])
        personas.set_extra(pid, "community", {
            **note, "version": got["version"], "updated": time.time(), "text_sha": _sha_text(got["text"]),
            "settings_sha": _sha_settings(pid), "avatar_sha": _sha_avatar(pid),
        })
    _log(f"Updated the community profile {got['meta']['name']} to version {got['version']}.")
    return {"pid": pid, "version": got["version"]}


# ── Sharing your own ─────────────────────────────────────────────────────────

def _mine() -> dict:
    data = _read(mine_path(), {})
    data = data if isinstance(data, dict) else {}
    data.setdefault("requests", [])
    data.setdefault("gists", {})
    return data


def _save_mine(data: dict) -> None:
    data["requests"] = data.get("requests", [])[-60:]
    _write(mine_path(), data)


def _media_of(pid: str) -> list:
    """The pictures and videos a profile has, for the picker: [{name, video, bytes}]."""
    from app.utils import videos
    folder = personas.pictures_dir(pid)
    out = []
    try:
        files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in personas._IMAGE_EXT)
    except OSError:
        return out
    for p in files:
        out.append({"name": p.name, "video": videos.is_kept_video(p.name), "bytes": p.stat().st_size})
    return out


def _author_default() -> str:
    return str(_mine().get("author") or "")


def share_form(pid: str) -> dict:
    """What the share form opens with."""
    if not personas.exists(pid):
        raise CommunityError("There's no such profile.", 404)
    info = personas.get(pid) or {}
    text = personas.read_text(pid)
    own = personas.overrides(pid)
    effective = _effective(pid)
    was = personas.extra(pid, "shared") or {}
    rows = []
    for key in sorted(rules.ALLOWED):
        if key not in effective and key not in own:
            continue
        rows.append({"key": key, "label": _label(key), "value": own.get(key, effective.get(key)),
                     "own": key in own and key != "bot.trigger", "trigger": key == "bot.trigger"})
    never = [{"label": why, "count": sum(1 for k in effective if any(k == p.rstrip(".") or k.startswith(p)
                                                                     for p in prefixes))}
             for why, prefixes in rules.NEVER]
    return {
        "pid": pid,
        "action": "update" if was.get("slug") else "publish",
        "slug": was.get("slug") or rules.slug_from(info.get("name") or pid),
        "name": info.get("name") or pid,
        "tagline": personas.vibe(text)[:90],
        "color": info.get("color") or "",
        "author": _author_default(),
        "language": str(effective.get("bot.default_language") or ""),
        "tags": [],
        "adult": False,
        "settings": rows,
        "never": [n for n in never if n["count"]],
        "media": _media_of(pid),
        "has_avatar": personas.has_avatar(pid),
        "shared": was or None,
        "limits": {k: rules.LIMITS[k] for k in ("pictures", "videos", "video_seconds", "text", "core_bytes")},
        "tags_allowed": list((_meta().get("tags") or rules.TAGS)),
    }


def _yours() -> list:
    """Your own usernames and ids, so the preview can point them out if the text has them."""
    out = []
    try:
        from app.web.envfile import read_env
        env = read_env()
        for k, v in env.items():
            if re.match(r"^(SNAP_USERNAME|TIKTOK_USERNAME)(_\d+)?$", k) and v:
                out.append(str(v))
    except Exception:
        pass
    try:
        from app.utils.helpers import load_base_config
        owner = (load_base_config().get("bot") or {}).get("owner_id")
        if owner:
            out.append(str(owner))
    except Exception:
        pass
    who = github_signin.me()
    if who.get("login"):
        out.append(who["login"])
    return [x for x in out if len(x) >= 3]


def _form_meta(pid: str, form: dict) -> dict:
    info = personas.get(pid) or {}
    return {
        "slug": str(form.get("slug") or ""), "name": str(form.get("name") or info.get("name") or ""),
        "tagline": str(form.get("tagline") or ""), "description": str(form.get("description") or ""),
        "tags": [str(t) for t in form.get("tags") or []][:10], "color": str(form.get("color") or info.get("color") or ""),
        "author": str(form.get("author") or ""), "adult": bool(form.get("adult")),
        "language": str(form.get("language") or ""), "note": str(form.get("note") or ""),
    }


def _form_settings(pid: str, form: dict) -> dict:
    """The settings ticked, at this profile's values. Only allowed keys ever leave."""
    effective = _effective(pid)
    own = personas.overrides(pid)
    out = {}
    for key in form.get("settings") or []:
        key = str(key)
        if key in rules.ALLOWED:
            value = own.get(key, effective.get(key))
            if value is not None or key.startswith("bot.sampling."):
                out[key] = value
    return out


def _picked(pid: str, form: dict) -> list:
    """The pictures and videos picked, by name, found in this profile's own folder only."""
    names = {m["name"]: m for m in _media_of(pid)}
    picked = []
    for n in form.get("media") or []:
        n = str(n)
        if n in names and n not in [p["name"] for p in picked]:
            picked.append(names[n])
    return picked


def preview(pid: str, form: dict) -> dict:
    """Exactly what would go public, what stays out, and what would stop it, without sending anything."""
    if not personas.exists(pid):
        raise CommunityError("There's no such profile.", 404)
    meta, problems = rules.check_meta(_form_meta(pid, form), tags=tuple(_meta().get("tags") or rules.TAGS))
    text, p2 = rules.check_text(personas.read_text(pid))
    settings, p3 = rules.check_settings(_form_settings(pid, form))
    problems += p2 + p3
    picked = _picked(pid, form)
    pics = [m for m in picked if not m["video"]]
    vids = [m for m in picked if m["video"]]
    if len(pics) > rules.LIMITS["pictures"]:
        problems.append(f"At most {rules.LIMITS['pictures']} pictures.")
    if len(vids) > rules.LIMITS["videos"]:
        problems.append(f"At most {rules.LIMITS['videos']} videos.")
    findings = rules.scan({"text": text, **rules.text_values(settings)}, yours=_yours())
    warnings = [f"{rules._field_word(f['field'])} has {rules.KIND_WORDS[f['kind']]} ({f['match']})."
                for f in findings if f["kind"] in rules.WARN]
    slug_state = "free"
    e = entry(meta["slug"]) if rules.SLUG.match(meta["slug"]) else None
    was = personas.extra(pid, "shared") or {}
    action = "update" if was.get("slug") == meta["slug"] else "publish"
    if e:
        slug_state = "yours" if was.get("slug") == meta["slug"] else "taken"
        if slug_state == "taken":
            problems.append("That short name is taken. Pick another one.")
    left_out = [{"label": _label(k), "why": rules.never_reason(k)}
                for k in personas.overrides(pid) if k not in rules.ALLOWED]
    return {
        "ready": not problems,
        "problems": problems,
        "warnings": warnings,
        "needs_check": any(f["kind"] == "yours" for f in findings),
        "segments": segments(text, findings),
        "action": action,
        "slug_state": slug_state,
        "public": {
            "meta": meta, "words": rules.words(text),
            "settings": [{"key": k, "label": _label(k), "value": v} for k, v in settings.items()],
            "media": [{"name": m["name"], "video": m["video"], "bytes": m["bytes"]} for m in picked],
            "avatar": personas.has_avatar(pid),
        },
        "left_out": left_out,
    }


def _core(pid: str, meta: dict, text: str, settings: dict) -> bytes:
    """The request's core zip, the face made smaller until it fits in an issue."""
    files = {"profile.json": rules.canonical_json(meta), "persona.txt": text.encode("utf-8"),
             "settings.json": rules.canonical_json(settings)}
    src = personas.avatar_path(pid)
    face = src.read_bytes() if src.is_file() else b""
    if face:
        from PIL import Image
        for side, quality in ((256, 85), (256, 72), (224, 70), (192, 64), (160, 60), (128, 56)):
            with Image.open(io.BytesIO(face)) as im:
                small = im.convert("RGB").resize((side, side), Image.LANCZOS)
                out = io.BytesIO()
                small.save(out, "JPEG", quality=quality, optimize=True)
            files["avatar.jpg"] = out.getvalue()
            blob = rules.build_zip(files)
            if len(blob) <= rules.LIMITS["core_bytes"]:
                return blob
        files.pop("avatar.jpg", None)
    blob = rules.build_zip(files)
    if len(blob) > rules.LIMITS["core_bytes"]:
        raise CommunityError("The text is too long to send.", 422)
    return blob


def _clean_media(pid: str, picked: list, work: Path, progress=None) -> list:
    """The picked pictures and videos made clean for sending: pictures from their pixels (no EXIF, no GPS), videos
    converted with no metadata. [{name, kind, data, seconds?}] as m01.jpg, m02.mp4..."""
    from app.utils import imageimport, videos
    imageimport._ensure_openers()
    out = []
    folder = personas.pictures_dir(pid)
    for i, m in enumerate(picked, start=1):
        src = folder / m["name"]
        name = f"m{i:02d}.{'mp4' if m['video'] else 'jpg'}"
        if progress:
            progress(f"Getting {m['name']} ready", i, len(picked))
        if m["video"]:
            info = videos.probe(src)
            if info["duration"] > rules.LIMITS["video_seconds"]:
                raise CommunityError(f"{m['name']} is longer than {int(rules.LIMITS['video_seconds'])} seconds.", 422)
            dst = work / name
            videos.convert(src, dst, limit=rules.LIMITS["video_bytes"])
            out.append({"name": name, "kind": "video", "data": dst.read_bytes(),
                        "seconds": round(float(info["duration"] or 0), 1) or 0.1})
        else:
            try:
                data = rules.reencode_image(src.read_bytes(), side=rules.LIMITS["picture_side"],
                                            formats=("JPEG", "PNG", "WEBP", "GIF", "MPO", "HEIF", "AVIF"))
            except ValueError as e:
                raise CommunityError(f"{m['name']}: {e}", 422)
            out.append({"name": name, "kind": "picture", "data": data})
    return out


def _gist(token: str, slug: str, media: list, progress=None) -> dict:
    """The media in your own private gist (one per shared profile, reused for updates): {gist, revision, files}."""
    mine = _mine()
    files_out = {}
    manifest = []
    for m in media:
        parts = rules.split_parts(m["data"])
        for i, part in enumerate(parts):
            files_out[rules.part_name(m["name"], i)] = {"content": part}
        manifest.append({"name": m["name"], "kind": m["kind"], "sha256": rules.sha256(m["data"]),
                         "bytes": len(m["data"]), **({"seconds": m["seconds"]} if m.get("seconds") else {})})
    names = list(files_out)
    batches, size, cur = [], 0, []
    for n in names:
        s = len(files_out[n]["content"])
        if cur and size + s > 8_000_000:
            batches.append(cur)
            cur, size = [], 0
        cur.append(n)
        size += s
    if cur:
        batches.append(cur)
    gid = str(mine["gists"].get(slug) or "")
    readme = {"README.md": {"content": f"Pictures and videos for the LLMSelfbot profile {slug}, sent from the app.\n"}}
    data = None
    if gid:
        try:
            _, old = ghhttp.api("GET", f"/gists/{gid}", token=token)
            stale = {n: None for n in (old or {}).get("files") or {} if n != "README.md" and n not in files_out}
            _, data = ghhttp.api("PATCH", f"/gists/{gid}", token=token,
                                 json_body={"files": {**readme, **stale}}, timeout=120)
        except ghhttp.GitHubError:
            gid = ""
    if not gid:
        _, data = ghhttp.api("POST", "/gists", token=token, json_body={
            "description": f"LLMSelfbot profile: {slug}", "public": False, "files": readme}, timeout=120)
        gid = str((data or {}).get("id") or "")
        if not rules.GIST.match(gid):
            raise CommunityError("GitHub didn't make the gist.", 502)
        mine["gists"][slug] = gid
        _save_mine(mine)
    for i, batch in enumerate(batches, start=1):
        if progress:
            progress("Sending pictures and videos", i, len(batches))
        _, data = ghhttp.api("PATCH", f"/gists/{gid}", token=token,
                             json_body={"files": {n: files_out[n] for n in batch}}, timeout=300, cap=16_000_000)
    revision = str(((data or {}).get("history") or [{}])[0].get("version") or "")
    if not rules.REVISION.match(revision):
        raise CommunityError("GitHub didn't keep the pictures and videos.", 502)
    return {"gist": gid, "revision": revision, "files": manifest}


def _token() -> str:
    tok = github_signin.token()
    if not tok:
        raise CommunityError("Sign in with GitHub first.", 401)
    return tok


def _open_issue(token: str, title: str, body: str) -> dict:
    try:
        _, issue = ghhttp.api("POST", f"/repos/{repo()}/issues", token=token,
                              json_body={"title": title[:200], "body": body}, timeout=60)
    except ghhttp.GitHubError as e:
        if e.status == 401:
            github_signin.on_401()
        raise CommunityError(str(e), 502)
    return issue or {}


def send(pid: str, form: dict, progress=None) -> dict:
    """Shared: the media cleaned and put in your gist, the request opened in the catalog's repo. The repo's workflow
    takes it from there. Returns {number, url}."""
    pv = preview(pid, form)
    if not pv["ready"]:
        raise CommunityError(pv["problems"][0], 422)
    if pv["needs_check"] and not form.get("checked"):
        raise CommunityError("Check the highlighted parts first.", 422)
    token = _token()
    meta = pv["public"]["meta"]
    text, _ = rules.check_text(personas.read_text(pid))
    settings, _ = rules.check_settings(_form_settings(pid, form))
    action = pv["action"]
    core = _core(pid, {**meta}, text, settings)
    request = {"v": 1, "action": action, "slug": meta["slug"], "sha256": rules.sha256(core), "bytes": len(core),
               "app": _version()}
    picked = _picked(pid, form)
    if picked:
        with tempfile.TemporaryDirectory(prefix="llmselfbot-share-") as tmp:
            media = _clean_media(pid, picked, Path(tmp), progress)
        total = sum(len(m["data"]) for m in media)
        if total > rules.LIMITS["package_bytes"]:
            raise CommunityError("The pictures and videos are too big together.", 422)
        request["media"] = _gist(token, meta["slug"], media, progress)
    pics = sum(1 for m in picked if not m["video"])
    vids = len(picked) - pics
    summary = (f"**{rules.md_inline(meta['name'], 40)}**, {'an update' if action == 'update' else 'new'}  \n"
               + (f"{rules.md_inline(meta['tagline'], 90)}  \n" if meta["tagline"] else "")
               + f"{rules.words(text)} words · {len(settings)} settings · {pics} pictures · {vids} videos\n\n"
               "Sent from LLMSelfbot. The checks run in a moment.")
    body = rules.render_request(request, core, summary)
    if len(body) > rules.LIMITS["body_chars"]:
        raise CommunityError("It's too big to send. Shorten the text.", 422)
    if progress:
        progress("Sending", 1, 1)
    # The app's own issues are in the same repo: a title that says it's a profile.
    kind = "Profile update" if action == "update" else "Profile"
    issue = _open_issue(token, f"{kind}: {meta['name']} ({meta['slug']})", body)
    mine = _mine()
    mine["author"] = meta["author"]
    mine["requests"].append({"number": issue.get("number"), "slug": meta["slug"], "action": action, "pid": pid,
                             "sent": time.time(), "sha": request["sha256"], "state": "checking"})
    _save_mine(mine)
    _log(f"Sent {meta['name']} to the community ({action}).")
    return {"number": issue.get("number"), "url": issue.get("html_url", "")}


def remove(slug: str) -> dict:
    """Your own profile out of the catalog: a remove request, checked by the repo like any other."""
    if not rules.SLUG.match(str(slug or "")):
        raise CommunityError("That isn't a profile's short name.", 400)
    token = _token()
    request = {"v": 1, "action": "remove", "slug": slug, "sha256": "", "bytes": 0, "app": _version()}
    body = rules.render_request(request, b"", f"Remove **{slug}** from the catalog. Sent from LLMSelfbot.")
    issue = _open_issue(token, f"Profile removal: {slug}", body)
    mine = _mine()
    pid = (shared().get(slug) or {}).get("pid", "")
    mine["requests"].append({"number": issue.get("number"), "slug": slug, "action": "remove", "pid": pid,
                             "sent": time.time(), "sha": "", "state": "checking"})
    _save_mine(mine)
    return {"number": issue.get("number"), "url": issue.get("html_url", "")}


def _version() -> str:
    try:
        from app.version import __version__
        return str(__version__)
    except Exception:
        return ""


def mine(force: bool = False) -> dict:
    """Your requests and how each went (checking, live, refused and why, removed), and your shared profiles with
    their downloads. Following a request reads its issue, with your token."""
    data = _mine()
    token = github_signin.token()
    changed = False
    for r in data["requests"]:
        if r.get("state") in ("published", "refused", "removed") and not force:
            continue
        if not token or not r.get("number"):
            continue
        try:
            _, issue = ghhttp.api("GET", f"/repos/{repo()}/issues/{int(r['number'])}", token=token)
            _, comments = ghhttp.api("GET", f"/repos/{repo()}/issues/{int(r['number'])}/comments", token=token,
                                     params={"per_page": 100})
        except ghhttp.GitHubError:
            continue
        st = None
        for c in reversed(comments or []):
            if (c.get("user") or {}).get("type") == "Bot":
                st = rules.parse_status(c.get("body") or "")
                if st:
                    break
        if st and st.get("state") != r.get("state"):
            r["state"] = st["state"]
            r["reasons"] = list(st.get("reasons") or [])[:20]
            if st.get("version"):
                r["version"] = int(st["version"])
            changed = True
            pid = r.get("pid") or ""
            if pid and personas.exists(pid):
                if st["state"] == "published":
                    personas.set_extra(pid, "shared", {"slug": r["slug"], "version": int(st.get("version") or 1),
                                                       "shas": {"text": _sha_text(personas.read_text(pid)),
                                                                "settings": _sha_settings(pid)}})
                elif st["state"] == "removed":
                    personas.set_extra(pid, "shared", None)
        elif not st and (issue or {}).get("state") == "closed" and r.get("state") == "checking":
            r["state"] = "error"
            changed = True
    if changed:
        _save_mine(data)
    index, _ = _index()
    by_slug = {p.get("slug"): p for p in index.get("profiles") or []}
    profiles = []
    for slug, s in shared().items():
        e = by_slug.get(slug) or {}
        pid = s["pid"]
        note = personas.extra(pid, "shared") or {}
        shas = note.get("shas") or {}
        profiles.append({
            "slug": slug, "pid": pid, "version": s["version"], "live": bool(e), "app": rules.app_version(e.get("app")),
            "downloads": int(e.get("downloads") or 0), "week": int(e.get("week") or 0),
            "changed": bool(shas) and (shas.get("text") != _sha_text(personas.read_text(pid))
                                       or shas.get("settings") != _sha_settings(pid)),
        })
    return {"requests": list(reversed(data["requests"]))[:30], "profiles": profiles,
            "author": data.get("author", ""), "signed_in": bool(token)}


# ── Reports and moderation ───────────────────────────────────────────────────

REPORT_REASONS = ("A scam or a trick", "Someone's private info", "A real person without their consent",
                  "Hate or harassment", "Sexual content involving minors", "Copied from someone else", "Something else")


def report(slug: str, reason: str, details: str) -> dict:
    """A report in the catalog's repo, signed in; the moderators get it. Without a sign-in the page opens the form."""
    if not rules.SLUG.match(str(slug or "")):
        raise CommunityError("That isn't a profile's short name.", 400)
    reason = reason if reason in REPORT_REASONS else "Something else"
    token = _token()
    details = rules.normalize_text(details)[:1000]
    body = (f"<!-- llmselfbot:report {json.dumps({'slug': slug, 'reason': reason})} -->\n"
            f"**{slug}**: {rules.md_inline(reason, 60)}\n\n" + (rules.fence(details) if details else ""))
    issue = _open_issue(token, f"Profile report: {slug}", body)
    return {"number": issue.get("number"), "url": issue.get("html_url", "")}


def _moderator_token() -> str:
    token = _token()
    meta = _meta()
    mods = {int(m) for m in meta.get("moderators") or [] if str(m).isdigit()}
    if github_signin.me()["id"] not in mods:
        raise CommunityError("Only moderators can do that.", 403)
    return token


def queue() -> dict:
    """For moderators: open reports, the latest requests (with who sent them), takedowns and bans."""
    token = _moderator_token()
    try:
        _, reports = ghhttp.api("GET", f"/repos/{repo()}/issues", token=token,
                                params={"labels": rules.label("report"), "state": "open", "per_page": 50})
        _, recent = ghhttp.api("GET", f"/repos/{repo()}/issues", token=token,
                               params={"labels": rules.label("request"), "state": "all", "per_page": 30})
    except ghhttp.GitHubError as e:
        raise CommunityError(str(e), 502)

    def row(i: dict) -> dict:
        # "profile-published" to "published": the page reads the kind, not how the repo spells it.
        labels = [str(x.get("name") or "").removeprefix(rules.label("")) for x in i.get("labels") or []]
        return {"number": i.get("number"), "title": rules.one_line(i.get("title"), 120),
                "by": (i.get("user") or {}).get("login", ""), "state": i.get("state"), "labels": labels,
                "created": i.get("created_at"), "url": i.get("html_url")}
    return {"reports": [row(i) for i in reports or [] if "pull_request" not in i],
            "requests": [row(i) for i in recent or [] if "pull_request" not in i]}


def moderate(command: str, target: str, reason: str = "", number: int = 0) -> dict:
    """A moderator's command, posted as a comment for the repo's workflow to carry out: on the issue given, or on the
    moderation log issue (made once)."""
    if command not in ("takedown", "restore", "ban", "unban", "close", "open"):
        raise CommunityError("Not a command.", 400)
    if command in ("takedown", "restore") and not rules.SLUG.match(str(target or "")):
        raise CommunityError("That isn't a profile's short name.", 400)
    if command in ("ban", "unban") and not re.match(r"^@?[A-Za-z0-9-]{1,39}$", str(target or "")):
        raise CommunityError("Ban by a profile's short name or an @login.", 400)
    token = _moderator_token()
    data = _mine()
    n = int(number or data.get("modlog") or 0)
    if not n:
        # Its marker is what lets the workflow hear commands here. Closed at once: comments still count, and the
        # app's open issues stay the app's.
        issue = _open_issue(token, "Community moderation log",
                            "<!-- llmselfbot:modlog -->\nModeration commands for community profiles, sent from the app.")
        n = int(issue.get("number") or 0)
        try:
            ghhttp.api("PATCH", f"/repos/{repo()}/issues/{n}", token=token, json_body={"state": "closed"})
        except ghhttp.GitHubError:
            pass
        data["modlog"] = n
        _save_mine(data)
    line = f"/{command}" + (f" {target}" if target else "") + (f" {rules.one_line(reason, 200)}" if reason else "")
    try:
        ghhttp.api("POST", f"/repos/{repo()}/issues/{n}/comments", token=token, json_body={"body": line})
    except ghhttp.GitHubError as e:
        raise CommunityError(str(e), 502)
    _log(f"Moderation: {line}")
    return {"ok": True, "issue": n}


# ── Links ────────────────────────────────────────────────────────────────────

def link(what: str, slug: str = "", number: int = 0) -> str:
    """A GitHub address made only from known parts. "" for anything else."""
    r = repo()
    if what == "repo":
        return f"https://github.com/{r}"
    if what == "site":
        return site() + "/"
    if what == "device":
        return "https://github.com/login/device"
    if what == "apps":
        return "https://github.com/settings/applications"
    if what == "profile" and rules.SLUG.match(slug or ""):
        return f"https://github.com/{r}/tree/{rules.DATA_BRANCH}/profiles/{slug}"
    if what == "report" and rules.SLUG.match(slug or ""):
        return f"https://github.com/{r}/issues/new?template=profile-report.yml&slug={slug}"
    if what == "issue" and int(number or 0) > 0:
        return f"https://github.com/{r}/issues/{int(number)}"
    return ""
