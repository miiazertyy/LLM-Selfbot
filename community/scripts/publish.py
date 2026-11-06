"""publish.py - a profile into the catalog, and out of it again.

A live profile is a folder on the data branch (profiles/<slug>/: its details, text, settings, face and thumbnails)
and a file per version in the community's release (community_rules.RELEASE_TAG), pictures and videos included.
Installing downloads that file, which is what GitHub counts. A new version is always a new file, so a count is never
reset. The release keeps a profile's last two versions (an app with an older catalog can still download the one it
knows); older files are deleted, their counts kept in the profile first ("earlier"), so no download is ever lost.

Out of the catalog three ways: the author removes it (its files go too), a moderator takes it down (its files stay,
so it can be restored), or its author is banned (taken down, every one of theirs).
"""
from __future__ import annotations

import datetime as dt
import json

import community_rules as rules

PROFILES = "profiles"
SITE = "community-site.yml"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(repo, rel: str, default):
    raw = repo.read(rel)
    if raw is None:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return default


def live_profile(repo, slug: str) -> dict | None:
    if not rules.SLUG.match(str(slug or "")):
        return None
    data = read_json(repo, f"{PROFILES}/{slug}/profile.json", None)
    return data if isinstance(data, dict) else None


def live_slugs(repo) -> list:
    root = repo.path(PROFILES)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "profile.json").is_file())


def by_owner(repo, key: str) -> list:
    return [s for s in live_slugs(repo) if (live_profile(repo, s) or {}).get("owner") == key]


def _changelog(prev: dict | None, version: int, note: str) -> list:
    old = list((prev or {}).get("changelog") or [])
    entry = {"version": version, "date": now_iso()[:10], "note": note or ("First version" if version == 1 else "")}
    return [entry] + old[:29]


def release(ctx) -> dict:
    """The community's one release, made the first time it's needed."""
    return ctx.gh.release_by_tag(rules.RELEASE_TAG) or ctx.gh.create_release(
        rules.RELEASE_TAG, "Community profiles",
        "Downloads of the profiles people shared from LLMSelfbot, one file per version. Not a version of the app: the "
        "app adds these from Profiles, Community.", prerelease=True, target=rules.DATA_BRANCH)


def files_of(ctx, rel: dict, slug: str) -> dict:
    """{version: asset} of one profile in the release."""
    out = {}
    for a in ctx.gh.release_assets(rel["id"]):
        parsed = rules.parse_asset(a.get("name"))
        if parsed and parsed[0] == slug:
            out[parsed[1]] = a
    return out


def publish(ctx, *, slug: str, meta: dict, text: str, settings: dict, avatar: bytes, media: list, owner: str,
            issue: int, app: str = "") -> int:
    """Live as a new version: the release file first, then the data branch, so a version is never listed before it can
    be downloaded. Returns the version. `media` is [{name, kind, data, thumb, seconds}]; `app` the app version it was
    sent from ("" when unknown), so everyone sees whether it was made for the app they have."""
    prev = live_profile(ctx.repo, slug)
    gone = ctx.retired.get(slug) or {}
    version = int((prev or {}).get("version") or gone.get("version") or 0) + 1
    created = (prev or {}).get("created") or now_iso()
    files_info = {"persona.txt": rules.sha256(text.encode("utf-8")),
                  "settings.json": rules.sha256(rules.canonical_json(settings))}
    if avatar:
        files_info["avatar.jpg"] = rules.sha256(avatar)
    manifest = {
        "schema": rules.SCHEMA, "kind": "llmselfbot-profile", "rules": rules.RULES,
        "slug": slug, "name": meta["name"], "tagline": meta["tagline"], "description": meta["description"],
        "tags": meta["tags"], "color": meta["color"], "author": meta["author"], "adult": meta["adult"],
        "language": meta["language"], "owner": owner, "version": version, "created": created, "updated": now_iso(),
        "app": rules.app_version(app), "request": issue, "changelog": _changelog(prev, version, meta.get("note", "")),
        "words": rules.words(text), "settings": sorted(settings),
        "media": [{"name": m["name"], "kind": m["kind"], "bytes": len(m["data"]), "sha256": rules.sha256(m["data"]),
                   **({"seconds": m["seconds"]} if m.get("seconds") else {})} for m in media],
        "files": files_info,
    }
    package = {"profile.json": rules.canonical_json(manifest), "persona.txt": text.encode("utf-8"),
               "settings.json": rules.canonical_json(settings)}
    if avatar:
        package["avatar.jpg"] = avatar
    for m in media:
        package[f"media/{m['name']}"] = m["data"]
    blob = rules.build_zip(package)
    asset_name = rules.asset_name(slug, version)

    rel = release(ctx)
    have = files_of(ctx, rel, slug)
    old = have.get(version)
    digest = f"sha256:{rules.sha256(blob)}"
    if old and old.get("digest") == digest:
        asset = old
    else:
        if old:
            # Left by a run that stopped before the profile was listed: never downloaded from the catalog.
            ctx.gh.delete_asset(old["id"])
        asset = ctx.gh.upload_asset(rel, asset_name, blob)

    # Versions before the last one: their counts kept in the profile, then their files deleted (after the push, so a
    # run that stops halfway never loses a count; a file still there is simply counted live instead).
    earlier = {str(k): int(v) for k, v in ((prev or {}).get("earlier") or {}).items()}
    stale = {v: a for v, a in have.items() if v < version - 1}
    for v, a in stale.items():
        earlier[str(v)] = max(earlier.get(str(v), 0), int(a.get("download_count") or 0))

    listed = {**manifest, "package": {"name": asset_name, "sha256": rules.sha256(blob), "bytes": len(blob),
                                      "id": asset.get("id")},
              **({"earlier": dict(sorted(earlier.items(), key=lambda kv: int(kv[0])))} if earlier else {})}
    folder = f"{PROFILES}/{slug}"
    ctx.repo.remove(folder)
    ctx.repo.write(f"{folder}/profile.json", rules.canonical_json(listed))
    ctx.repo.write(f"{folder}/persona.txt", text.encode("utf-8"))
    ctx.repo.write(f"{folder}/settings.json", rules.canonical_json(settings))
    if avatar:
        ctx.repo.write(f"{folder}/avatar.jpg", avatar)
    for m in media:
        ctx.repo.write(f"{folder}/thumbs/{m['name'].rsplit('.', 1)[0]}.jpg", m["thumb"])
    if slug in ctx.retired:
        ctx.retired.pop(slug)
        ctx.save_retired()
    ctx.repo.commit_and_push(f"Publish {slug} v{version} (#{issue})")
    for a in stale.values():
        try:
            ctx.gh.delete_asset(a["id"])
        except Exception:
            pass
    ctx.gh.dispatch(SITE)
    return version


def _retire(ctx, slug: str, profile: dict, reason: str, why: str = "") -> None:
    ctx.retired[slug] = {"owner": profile.get("owner", ""), "version": int(profile.get("version") or 0),
                         "removed": now_iso(), "reason": reason, **({"why": why} if why else {})}
    ctx.save_retired()


def remove(ctx, slug: str, issue: int) -> None:
    """The author's own removal: out of the catalog, and its files with it."""
    profile = live_profile(ctx.repo, slug) or {}
    rel = ctx.gh.release_by_tag(rules.RELEASE_TAG)
    if rel:
        for a in files_of(ctx, rel, slug).values():
            ctx.gh.delete_asset(a["id"])
    ctx.repo.remove(f"{PROFILES}/{slug}")
    _retire(ctx, slug, profile, "removed")
    ctx.repo.commit_and_push(f"Remove {slug} (#{issue})")
    ctx.gh.dispatch(SITE)


def takedown(ctx, slug: str, why: str, by: str) -> bool:
    """A moderator's takedown: out of the catalog at once. Its files stay, so /restore can bring it back."""
    profile = live_profile(ctx.repo, slug)
    if not profile:
        return False
    ctx.repo.remove(f"{PROFILES}/{slug}")
    _retire(ctx, slug, profile, "takedown", why)
    ctx.repo.commit_and_push(f"Take down {slug} ({by})")
    ctx.gh.dispatch(SITE)
    return True


def restore(ctx, slug: str, by: str) -> bool:
    gone = ctx.retired.get(slug)
    if not gone or gone.get("reason") != "takedown" or live_profile(ctx.repo, slug):
        return False
    if not ctx.repo.restore(f"{PROFILES}/{slug}"):
        return False
    ctx.retired.pop(slug, None)
    ctx.save_retired()
    ctx.repo.commit_and_push(f"Restore {slug} ({by})")
    ctx.gh.dispatch(SITE)
    return True
