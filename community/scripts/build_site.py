"""build_site.py - the catalog GitHub Pages serves, and the download stats.

Run by .github/workflows/community-site.yml every hour and whenever a profile changes, with the data branch checked
out beside the code (COMMUNITY_DATA). It reads how many times each file in the community's release was downloaded
(GitHub counts them itself, and a profile keeps the counts of its older files it no longer has), keeps one point a day
in stats/history.json on the data branch, and writes:

  index.json   every live profile with its details, downloads and "this week", and the totals
  stats.json   90 days of downloads a day, overall and per profile, with each version's share
  meta.json    the rules the app and the workflows share: allowed settings, limits, tags, moderators
  profiles/    each live profile's files, for the app's Inspect
  index.html   a small gallery for any browser

With --check it only checks every live profile against the rules. With --keepalive it also keeps the community's
workflows from being paused by GitHub, and every six hours starts the requests sweep.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_rules as rules  # noqa: E402

KEEP_DAYS = 400
SHOW_DAYS = 90
SITE = "community-site.yml"
REQUESTS = "community-requests.yml"


def release_counts(gh) -> dict:
    """{slug: {version: downloads}} from the community release's files."""
    out: dict = {}
    rel = gh.release_by_tag(rules.RELEASE_TAG)
    for a in gh.release_assets(rel["id"]) if rel else []:
        parsed = rules.parse_asset(a.get("name"))
        if parsed:
            out.setdefault(parsed[0], {})[parsed[1]] = int(a.get("download_count") or 0)
    return out


def with_earlier(root: Path, counts: dict) -> dict:
    """The counts with each live profile's older versions added back: their files are gone, their counts were kept in
    the profile ("earlier"). A file still there counts as it is now."""
    out = {slug: dict(v) for slug, v in counts.items()}
    folder = root / "profiles"
    for p in sorted(folder.iterdir()) if folder.is_dir() else []:
        prof = read_json(p / "profile.json", None)
        if not isinstance(prof, dict):
            continue
        for v, c in (prof.get("earlier") or {}).items():
            if str(v).isdigit():
                out.setdefault(p.name, {}).setdefault(int(v), max(0, int(c or 0)))
    return out


def update_history(history: dict, counts: dict, today: str) -> bool:
    """Today's point, once a day: each profile's downloads so far. A count never goes down, so a removed profile
    keeps what it had. True when a point was added."""
    days = history.setdefault("days", [])
    profiles = history.setdefault("profiles", {})
    history["schema"] = 1
    if days and days[-1] >= today:
        return False
    days.append(today)
    for slug in sorted(set(profiles) | set(counts)):
        series = profiles.setdefault(slug, [])
        while len(series) < len(days) - 1:
            series.append(series[-1] if series else 0)
        last = series[-1] if series else 0
        series.append(max(sum(counts.get(slug, {}).values()), last))
    if len(days) > KEEP_DAYS:
        cut = len(days) - KEEP_DAYS
        history["days"] = days[cut:]
        for slug in profiles:
            profiles[slug] = profiles[slug][cut:]
    return True


def _series(history: dict, slug: str) -> list:
    days = history.get("days") or []
    series = list((history.get("profiles") or {}).get(slug) or [])
    while len(series) < len(days):
        series.insert(0, 0)
    return series


def derive(history: dict, counts: dict) -> dict:
    """{slug: {downloads, week, daily, versions}} plus a "*" total. daily[i] is downloads on days[i]; the last day is
    "today so far"."""
    days = history.get("days") or []
    out = {}
    slugs = sorted(set(counts) | set(history.get("profiles") or {}))
    total_daily = [0] * min(len(days), SHOW_DAYS)
    total_now = total_week = 0
    for slug in slugs:
        series = _series(history, slug)
        now = max(sum(counts.get(slug, {}).values()), series[-1] if series else 0)
        daily = [series[i + 1] - series[i] for i in range(len(series) - 1)] + ([now - series[-1]] if series else [])
        daily = [max(0, d) for d in daily][-SHOW_DAYS:]
        week_base = series[-7] if len(series) >= 7 else (series[0] if series else 0)
        week = max(0, now - week_base)
        out[slug] = {"downloads": now, "week": week, "daily": daily,
                     "versions": {str(v): c for v, c in sorted(counts.get(slug, {}).items())}}
        total_now += now
        total_week += week
        tail = daily[-len(total_daily):] if total_daily else []
        offset = len(total_daily) - len(tail)
        for i, d in enumerate(tail):
            total_daily[offset + i] += d
    out["*"] = {"downloads": total_now, "week": total_week, "daily": total_daily}
    return out


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def check_profiles(root: Path) -> list:
    """Every live profile against the rules: [(slug, problem)]."""
    out = []
    folder = root / "profiles"
    for p in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not p.is_dir():
            continue
        profile = read_json(p / "profile.json", None)
        if not isinstance(profile, dict):
            out.append((p.name, "profile.json is missing or broken"))
            continue
        _, problems = rules.check_meta(profile, tags=())
        if profile.get("slug") != p.name:
            problems.append("its folder and its short name don't agree")
        try:
            _, p2 = rules.check_text((p / "persona.txt").read_text(encoding="utf-8"))
        except OSError:
            p2 = ["persona.txt is missing"]
        _, p3 = rules.check_settings(read_json(p / "settings.json", {}))
        out += [(p.name, x) for x in problems + p2 + p3]
    return out


def build(root: Path, out: Path, counts: dict, history: dict, now: str, page: Path | None = None) -> dict:
    """The whole site into `out`, from the data branch at `root` (and the gallery `page`, from the code). Returns
    index.json."""
    config = read_json(root / "community.json", {})
    stats = derive(history, counts)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    profiles = []
    folder = root / "profiles"
    for p in sorted(folder.iterdir()) if folder.is_dir() else []:
        prof = read_json(p / "profile.json", None)
        if not p.is_dir() or not isinstance(prof, dict):
            continue
        slug = p.name
        dest = out / "profiles" / slug
        shutil.copytree(p, dest)
        media = prof.get("media") or []
        thumbs = sorted(f"profiles/{slug}/thumbs/{t.name}" for t in (p / "thumbs").glob("*.jpg")) \
            if (p / "thumbs").is_dir() else []
        s = stats.get(slug) or {"downloads": 0, "week": 0}
        profiles.append({
            "slug": slug, "name": prof.get("name", slug), "tagline": prof.get("tagline", ""),
            "description": prof.get("description", ""), "tags": prof.get("tags", []), "color": prof.get("color", ""),
            "author": prof.get("author", ""), "adult": bool(prof.get("adult")), "language": prof.get("language", ""),
            "version": prof.get("version", 1), "app": rules.app_version(prof.get("app")),
            "created": prof.get("created", ""), "updated": prof.get("updated", ""),
            "words": prof.get("words", 0), "settings": len(prof.get("settings") or []),
            "pictures": sum(1 for m in media if m.get("kind") == "picture"),
            "videos": sum(1 for m in media if m.get("kind") == "video"),
            "downloads": s["downloads"], "week": s["week"],
            "avatar": f"profiles/{slug}/avatar.jpg" if (p / "avatar.jpg").is_file() else "",
            "thumbs": thumbs, "package": {k: (prof.get("package") or {}).get(k) for k in ("name", "sha256", "bytes")},
        })
    total = stats["*"]
    index = {"schema": 1, "generated": now, "totals": {"profiles": len(profiles), "downloads": total["downloads"],
                                                       "week": total["week"]}, "profiles": profiles}
    days = (history.get("days") or [])[-SHOW_DAYS:]
    live = {p["slug"] for p in profiles}
    stats_out = {"schema": 1, "generated": now, "days": days,
                 "total": {"downloads": total["downloads"], "week": total["week"], "daily": total["daily"]},
                 "profiles": {k: v for k, v in stats.items() if k in live}}
    meta = {"schema": 1, "rules": rules.RULES, "min_app": config.get("min_app", ""),
            "moderators": config.get("moderators") or [], "tags": config.get("tags") or list(rules.TAGS),
            "settings": sorted(rules.ALLOWED), "submissions_open": config.get("submissions_open", True) is not False,
            "limits": {k: rules.LIMITS[k] for k in ("text", "pictures", "videos", "video_seconds", "package_bytes")}}
    for name, data in (("index.json", index), ("stats.json", stats_out), ("meta.json", meta)):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if page and page.is_file():
        shutil.copy2(page, out / "index.html")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return index


def keepalive(gh, hour: int) -> None:
    """GitHub pauses a scheduled workflow after 60 days without activity in the repo: this one is turned on again on
    every run, and every six hours it starts the requests sweep (the requests workflow has no schedule of its own, so
    it's never paused and always hears a request)."""
    gh.enable(SITE)
    if hour % 6 == 0:
        gh.dispatch(REQUESTS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--commit", action="store_true", help="commit today's stats point")
    ap.add_argument("--keepalive", action="store_true", help="keep the workflows on, start the sweep now and then")
    args = ap.parse_args(argv)
    root = Path(os.environ.get("COMMUNITY_DATA", "data")).resolve()
    if args.check:
        problems = check_profiles(root)
        for slug, p in problems:
            print(f"{slug}: {p}")
        return 1 if problems else 0
    from ghapi import GitHub
    gh = GitHub(os.environ.get("GH_TOKEN", ""), os.environ["REPO"])
    counts = with_earlier(root, release_counts(gh))
    history_path = root / "stats" / "history.json"
    history = read_json(history_path, {"schema": 1, "days": [], "profiles": {}})
    now = dt.datetime.now(dt.timezone.utc)
    if update_history(history, counts, now.date().isoformat()) and args.commit:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_bytes(rules.canonical_json(history))
        from gitrepo import Repo
        Repo(root).commit_and_push(f"stats: {now.date().isoformat()}")
    page = Path(__file__).resolve().parent.parent / "site" / "index.html"
    build(root, Path(args.out).resolve(), counts, history, now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
          page)
    if args.keepalive:
        keepalive(gh, now.hour)
    print(f"site built: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
