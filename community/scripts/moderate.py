"""moderate.py - what the community does when the app sends something, someone reports, or a moderator speaks.

Run by .github/workflows/community-requests.yml on new and edited issues and on comments, with the data branch
checked out beside the code (COMMUNITY_DATA), and every few hours as a sweep for anything an event missed (the site
workflow starts it). Everything is worked out from the issue as it is now, so running twice does no harm. Issues that
aren't the community's (the app's own bug reports) are left alone.

- A request (an issue the app opened, with a request marker): checked with community_rules, then published, updated
  or removed, or refused with each reason in a plain sentence. There is no approval queue: what passes the checks
  goes live, and moderators take down what shouldn't be there.
- A moderator's command in a comment: /takedown, /restore, /ban, /unban, /close, /open, /recheck. Commands from
  anyone else are ignored, except /recheck by the person who sent the request.
- A report (the Report form, or one the app opened): acknowledged and left for the moderators. Nothing automatic.

The issue's text never reaches a shell: the event is read from its file, here, in Python.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_rules as rules  # noqa: E402
import media as media_mod  # noqa: E402
import publish  # noqa: E402

LABELS = {rules.label(kind): spec for kind, spec in {
    "request": ("1f6feb", "A community profile sent from the app"),
    "published": ("2da44e", "Live in the community"),
    "refused": ("d1242f", "Didn't pass the checks"),
    "removed": ("6e7781", "Taken out by its author"),
    "report": ("fb8500", "Someone reported a community profile"),
    "takedown": ("8250df", "Taken down by a moderator"),
    "error": ("bf3989", "Something went wrong; tried again later"),
}.items()}
FINAL = {"published", "refused", "removed"}
_REPORT = re.compile(r"<!--\s*llmselfbot:report\s+(\{.*?\})\s*-->", re.S)


class Ctx:
    """What a run works with: GitHub, the repo's files, the owner's config, and the secret that keys authors."""

    def __init__(self, gh, repo, secret: str, fetch_gist=media_mod.fetch_gist, today=None):
        self.gh = gh
        self.repo = repo
        self.secret = secret
        self.fetch_gist = fetch_gist
        self.today = today or (lambda: dt.datetime.now(dt.timezone.utc))
        self.config = publish.read_json(repo, "community.json", {})
        self.retired = publish.read_json(repo, "retired.json", {})

    def save_config(self) -> None:
        self.repo.write("community.json", rules.canonical_json(self.config))

    def save_retired(self) -> None:
        self.repo.write("retired.json", rules.canonical_json(self.retired))

    def limit(self, name: str, default: int) -> int:
        try:
            return int((self.config.get("limits") or {}).get(name, default))
        except (TypeError, ValueError):
            return default

    def banned_keys(self) -> set:
        return {str(b.get("key")) for b in self.config.get("banned") or [] if isinstance(b, dict)}

    def is_moderator(self, user: dict) -> bool:
        mods = self.config.get("moderators") or []
        if mods:
            return int(user.get("id") or 0) in {int(m) for m in mods if str(m).isdigit() or isinstance(m, int)}
        return self.gh.permission(str(user.get("login") or "")) in ("admin", "maintain")


# ── The status comment ───────────────────────────────────────────────────────

def _bot(comment: dict) -> bool:
    return (comment.get("user") or {}).get("type") == "Bot"


def status_comment(ctx: Ctx, n: int) -> tuple:
    """(the bot's status comment on this issue, its status), or (None, None)."""
    for c in reversed(ctx.gh.comments(n)):
        if _bot(c):
            st = rules.parse_status(c.get("body") or "")
            if st is not None:
                return c, st
    return None, None


def set_status(ctx: Ctx, n: int, status: dict, text: str) -> None:
    body = rules.render_status(status, text)
    c, _ = status_comment(ctx, n)
    if c:
        ctx.gh.edit_comment(c["id"], body)
    else:
        ctx.gh.comment(n, body)


def app_version(ctx: Ctx, claimed) -> str:
    """The app version a request was sent from, as the app says, but never newer than the app's newest release: a
    made-up future version would tell everyone their app is out of date."""
    said = rules.app_version(claimed)
    if not said:
        return ""
    latest = rules.app_version(ctx.gh.latest_release_tag())
    return latest if latest and rules.version_key(said) > rules.version_key(latest) else said


def _summary(meta: dict, text: str, settings: dict, media: list, app: str = "") -> str:
    pics = sum(1 for m in media if m["kind"] == "picture")
    vids = len(media) - pics
    parts = [f"**{rules.md_inline(meta['name'], 40)}**"]
    if meta.get("tagline"):
        parts.append(rules.md_inline(meta["tagline"], 90))
    line2 = [f"by {rules.md_inline(meta['author'], 32)}", f"{rules.words(text)} words", f"{len(settings)} settings"]
    if app:
        line2.append(f"made with app {app}")
    if pics:
        line2.append(f"{pics} picture{'s' if pics != 1 else ''}")
    if vids:
        line2.append(f"{vids} video{'s' if vids != 1 else ''}")
    if meta.get("adult"):
        line2.append("18+")
    out = "  \n".join(parts) + "\n" + " · ".join(line2)
    out += "\n\n<details><summary>Its text</summary>\n\n" + rules.fence(text) + "\n\n</details>"
    if settings:
        rows = "\n".join(f"| {rules.md_inline(k, 60)} | {rules.md_inline(json.dumps(v, ensure_ascii=False), 80)} |"
                         for k, v in settings.items())
        out += "\n\n<details><summary>Its settings</summary>\n\n| Setting | Value |\n|---|---|\n" + rows + "\n\n</details>"
    return out


def refuse(ctx: Ctx, issue: dict, sha: str, reasons: list) -> None:
    n = issue["number"]
    lines = "\n".join(f"- {r}" for r in reasons[:20])
    set_status(ctx, n, {"v": 1, "state": "refused", "sha": sha, "reasons": reasons[:20]},
               f"**Not published.**\n\n{lines}\n\nFix these and send it again from the app.")
    ctx.gh.add_labels(n, [rules.label("request"), rules.label("refused")])
    ctx.gh.close(n, "not_planned")


# ── Requests ─────────────────────────────────────────────────────────────────

def _created(issue: dict) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(str(issue.get("created_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return dt.datetime.now(dt.timezone.utc)


def gate(ctx: Ctx, user: dict, request: dict) -> list:
    """Whether this person may send now: sending open, not banned, an account old enough, within the limits."""
    if ctx.config.get("submissions_open") is False:
        return ["Sending is paused for now. Try again later."]
    key = rules.owner_key(ctx.secret, user["id"])
    if key in ctx.banned_keys():
        return ["You can't send profiles here."]
    try:
        made = dt.datetime.fromisoformat(str(ctx.gh.user(user["login"]).get("created_at")).replace("Z", "+00:00"))
        days = (ctx.today() - made).days
    except Exception:
        days = 10 ** 6
    need = ctx.limit("account_age_days", 7)
    if days < need:
        return [f"Your GitHub account is too new to send profiles (at least {need} days old)."]
    since = ctx.today() - dt.timedelta(days=1)
    recent = [i for i in ctx.gh.issues(state="all", creator=user["login"], since=since.isoformat())
              if "llmselfbot:request" in (i.get("body") or "") and _created(i) >= since]
    if len(recent) > ctx.limit("requests_per_day", 6):
        return ["You've sent a lot today. Try again tomorrow."]
    if request.get("action") == "publish":
        live = len(publish.by_owner(ctx.repo, key))
        cap = ctx.limit("live_profiles", 10)
        if live >= cap:
            return [f"You have {live} profiles live already (at most {cap})."]
    return []


def _words_blocked(ctx: Ctx, texts: list) -> list:
    words = [str(w).strip().lower() for w in ctx.config.get("banned_words") or [] if str(w).strip()]
    hay = "\n".join(texts).lower()
    hits = [w for w in words if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", hay)]
    return ["It has a word that isn't allowed here."] if hits else []


def process_request(ctx: Ctx, issue: dict, force: bool = False) -> str:
    """Do what this request asks, once. Returns the state it ends in ("" when there was nothing to do)."""
    n = issue["number"]
    user = issue.get("user") or {}
    if issue.get("pull_request") or user.get("type") != "User":
        return ""
    if issue.get("state") == "closed" and not force:
        return ""
    body = issue.get("body") or ""
    if "llmselfbot:request" not in body:
        return ""
    try:
        request, core = rules.parse_request(body)
    except ValueError as e:
        refuse(ctx, issue, "", [str(e)])
        return "refused"
    sha = str(request.get("sha256") or rules.sha256(body.encode("utf-8")))
    _, st = status_comment(ctx, n)
    if st and st.get("sha") == sha and st.get("state") in FINAL and not force:
        return ""
    ctx.gh.add_labels(n, [rules.label("request")])
    if not ctx.secret:
        set_status(ctx, n, {"v": 1, "state": "error", "sha": sha}, "**This repo isn't set up yet.** It will be tried again.")
        ctx.gh.add_labels(n, [rules.label("error")])
        return "error"

    reasons = gate(ctx, user, request)
    if reasons:
        refuse(ctx, issue, sha, reasons)
        return "refused"
    action = request["action"]
    slug = str(request.get("slug") or "")
    key = rules.owner_key(ctx.secret, user["id"])
    live = publish.live_profile(ctx.repo, slug)
    gone = ctx.retired.get(slug) or {}

    if action == "remove":
        if not live:
            refuse(ctx, issue, sha, [f"There's no live profile called {slug}."])
            return "refused"
        if live.get("owner") != key:
            refuse(ctx, issue, sha, ["It isn't yours."])
            return "refused"
        publish.remove(ctx, slug, n)
        set_status(ctx, n, {"v": 1, "state": "removed", "sha": sha, "slug": slug},
                   f"**Removed.** {rules.md_inline(live.get('name', slug), 40)} is out of the catalog. "
                   "Copies people already added stay theirs.")
        ctx.gh.add_labels(n, [rules.label("removed")])
        ctx.gh.close(n, "completed")
        return "removed"

    if action == "publish":
        if live:
            msg = "It's already live. Send it as an update." if live.get("owner") == key else \
                "That short name is taken. Pick another one."
            refuse(ctx, issue, sha, [msg])
            return "refused"
        if gone and (gone.get("owner") != key or gone.get("reason") == "takedown"):
            refuse(ctx, issue, sha, ["That short name was used before. Pick another one."])
            return "refused"
    else:
        if not live:
            refuse(ctx, issue, sha, [f"There's no live profile called {slug} to update."])
            return "refused"
        if live.get("owner") != key:
            refuse(ctx, issue, sha, ["It isn't yours."])
            return "refused"

    # What it holds, checked as the app checked it, and then some.
    try:
        files = rules.read_zip(core)
        meta_in = json.loads(files["profile.json"].decode("utf-8"))
        text_in = files["persona.txt"].decode("utf-8")
        settings_in = json.loads(files.get("settings.json", b"{}").decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        refuse(ctx, issue, sha, [str(e) if isinstance(e, ValueError) and str(e) else "The profile is damaged."])
        return "refused"
    tags = tuple(ctx.config.get("tags") or rules.TAGS)
    reserved = set(ctx.config.get("reserved_slugs") or rules.RESERVED)
    meta, problems = rules.check_meta(meta_in, tags=tags, reserved=reserved)
    if meta["slug"] != slug:
        problems.append("The request and the profile don't agree on its short name.")
    text, p2 = rules.check_text(text_in)
    settings, p3 = rules.check_settings(settings_in)
    problems += p2 + p3
    avatar = b""
    if files.get("avatar.jpg"):
        avatar, p4 = rules.check_avatar(files["avatar.jpg"])
        problems += p4
    problems += _words_blocked(ctx, [text, meta["name"], meta["tagline"], meta["description"], meta["author"],
                                     *rules.text_values(settings).values()])
    media_req = request.get("media") or {}
    problems += rules.check_media(media_req)
    if problems:
        refuse(ctx, issue, sha, problems)
        return "refused"

    kept = []
    manifest = list(media_req.get("files") or []) if media_req else []
    if manifest:
        try:
            with tempfile.TemporaryDirectory(prefix="gist-") as tmp:
                folder = ctx.fetch_gist(media_req["gist"], media_req["revision"], Path(tmp) / "g")
                raw = media_mod.files_from(media_mod.read_parts(folder), manifest)
                for f in sorted(manifest, key=lambda x: x["name"]):
                    if f["kind"] == "picture":
                        data, thumb = media_mod.picture(raw[f["name"]])
                        kept.append({"name": f["name"], "kind": "picture", "data": data, "thumb": thumb})
                    else:
                        data, thumb, secs = media_mod.video(raw[f["name"]], Path(tmp) / f["name"])
                        kept.append({"name": f["name"], "kind": "video", "data": data, "thumb": thumb,
                                     "seconds": secs})
        except ValueError as e:
            refuse(ctx, issue, sha, [str(e)])
            return "refused"
        total = sum(len(m["data"]) for m in kept)
        if total > rules.LIMITS["package_bytes"]:
            refuse(ctx, issue, sha, ["The pictures and videos are too big together."])
            return "refused"

    app = app_version(ctx, request.get("app"))
    version = publish.publish(ctx, slug=slug, meta=meta, text=text, settings=settings, avatar=avatar, media=kept,
                              owner=key, issue=n, app=app)
    set_status(ctx, n, {"v": 1, "state": "published", "sha": sha, "slug": slug, "version": version},
               f"**Live as version {version}.** It can take a few minutes to show in the catalog.\n\n"
               + _summary(meta, text, settings, kept, app))
    ctx.gh.remove_label(n, rules.label("error"))
    ctx.gh.add_labels(n, [rules.label("published")])
    ctx.gh.close(n, "completed")
    return "published"


# ── Moderators ───────────────────────────────────────────────────────────────

def _target_key(ctx: Ctx, target: str) -> str:
    """An author's key from a slug, an @login, a GitHub account number or a key itself. "" when unknown."""
    t = target.strip()
    if re.match(r"^[0-9a-f]{32}$", t):
        return t
    if t.startswith("@") or (not rules.SLUG.match(t) and re.match(r"^[A-Za-z0-9-]{1,39}$", t)):
        try:
            return rules.owner_key(ctx.secret, ctx.gh.user(t.lstrip("@"))["id"])
        except Exception:
            return ""
    if t.isdigit():
        return rules.owner_key(ctx.secret, int(t))
    live = publish.live_profile(ctx.repo, t)
    if live:
        return str(live.get("owner") or "")
    return str((ctx.retired.get(t) or {}).get("owner") or "")


def command(ctx: Ctx, issue: dict, comment: dict) -> str:
    """One moderator command, done. Returns what was said back ("" when it was not a command for here)."""
    user = comment.get("user") or {}
    if _bot(comment):
        return ""
    lines = [line.strip() for line in str(comment.get("body") or "").splitlines() if line.strip().startswith("/")]
    if not lines:
        return ""
    parts = lines[0].split(None, 2)
    name = parts[0][1:].lower()
    arg = parts[1] if len(parts) > 1 else ""
    why = rules.one_line(parts[2], 200) if len(parts) > 2 else ""
    mod = ctx.is_moderator(user)
    by = f"@{user.get('login', '')}"

    if name == "recheck":
        own = (issue.get("user") or {}).get("id") == user.get("id")
        if not (mod or own):
            return ""
        target = issue
        if arg.isdigit() and mod:
            target = ctx.gh.issue(int(arg))
        state = process_request(ctx, target, force=True)
        reply = f"Checked again: {state or 'nothing to do'}."
    elif not mod:
        return ""
    elif name == "takedown":
        ok = publish.takedown(ctx, arg, why or "Taken down by a moderator.", by)
        reply = f"Taken down: {arg}." if ok else f"There's no live profile called {rules.md_inline(arg, 40)}."
        if ok:
            ctx.gh.add_labels(issue["number"], [rules.label("takedown")])
    elif name == "restore":
        ok = publish.restore(ctx, arg, by)
        reply = f"Restored: {arg}." if ok else f"{rules.md_inline(arg, 40)} can't be restored."
    elif name in ("ban", "unban"):
        key = _target_key(ctx, arg)
        if not key:
            reply = f"Nobody found for {rules.md_inline(arg, 40)}."
        elif name == "ban":
            banned = [b for b in ctx.config.get("banned") or [] if isinstance(b, dict) and b.get("key") != key]
            banned.append({"key": key, "reason": why, "date": publish.now_iso()[:10], "by": by})
            ctx.config["banned"] = banned
            ctx.save_config()
            ctx.repo.commit_and_push(f"Ban an author ({by})")
            down = [s for s in publish.by_owner(ctx.repo, key)
                    if publish.takedown(ctx, s, why or "Its author is banned.", by)]
            reply = "Banned." + (f" Taken down: {', '.join(down)}." if down else "")
        else:
            before = len(ctx.config.get("banned") or [])
            ctx.config["banned"] = [b for b in ctx.config.get("banned") or [] if b.get("key") != key]
            ctx.save_config()
            ctx.repo.commit_and_push(f"Unban an author ({by})")
            reply = "Unbanned." if len(ctx.config["banned"]) < before else "They weren't banned."
    elif name in ("close", "open"):
        ctx.config["submissions_open"] = name == "open"
        ctx.save_config()
        ctx.repo.commit_and_push(f"Sending {'opened' if name == 'open' else 'paused'} ({by})")
        reply = "Sending is open." if name == "open" else "Sending is paused. Nothing new is published until /open."
    else:
        return ""
    ctx.gh.react(comment.get("id"), "+1")
    return reply


# ── Reports ──────────────────────────────────────────────────────────────────

def report(ctx: Ctx, issue: dict) -> None:
    """A report: acknowledged once, with a link to the profile. The moderators decide."""
    n = issue["number"]
    _, st = status_comment(ctx, n)
    if st and st.get("state") == "report":
        return
    body = issue.get("body") or ""
    slug = ""
    m = _REPORT.search(body)
    if m:
        try:
            slug = str(json.loads(m.group(1)).get("slug") or "")
        except ValueError:
            slug = ""
    if not slug:
        fm = re.search(r"###\s*(?:Profile|Which profile)[^\n]*\n+\s*([a-z0-9-]{3,32})", body)
        slug = fm.group(1) if fm else ""
    live = publish.live_profile(ctx.repo, slug) if slug else None
    ctx.gh.add_labels(n, [rules.label("report")])
    text = (f"Thanks. A moderator will look at **{rules.md_inline(live.get('name', slug), 40)}** ({slug})."
            if live else "Thanks. A moderator will look at it.")
    set_status(ctx, n, {"v": 1, "state": "report", "slug": slug}, text)


# ── The sweep and the entry point ────────────────────────────────────────────

def sweep(ctx: Ctx) -> int:
    """Every open request done if it wasn't (an event can be lost). Returns how many were looked at."""
    done = 0
    for issue in ctx.gh.issues(state="open"):
        body = issue.get("body") or ""
        if "llmselfbot:request" in body:
            process_request(ctx, issue)
            done += 1
        elif "llmselfbot:report" in body:
            report(ctx, issue)
    return done


def community_issue(issue: dict) -> bool:
    """One of the community's issues: a request, a report, or the moderation log. Commands are only heard there, so a
    slash in a comment on one of the app's own issues never does anything here."""
    body = issue.get("body") or ""
    labels = {str(label.get("name") or "") for label in issue.get("labels") or []}
    return "llmselfbot:" in body or any(name.startswith(rules.label("")) for name in labels)


def handle(ctx: Ctx, event_name: str, event: dict) -> None:
    if event_name == "issues":
        issue = event.get("issue") or {}
        if issue.get("pull_request"):
            return
        body = issue.get("body") or ""
        labels = {label.get("name") for label in issue.get("labels") or []}
        if "llmselfbot:request" in body:
            process_request(ctx, issue)
        elif "llmselfbot:report" in body or rules.label("report") in labels:
            report(ctx, issue)
    elif event_name == "issue_comment":
        issue = event.get("issue") or {}
        if issue.get("pull_request") or not community_issue(issue):
            return
        reply = command(ctx, issue, event.get("comment") or {})
        if reply:
            ctx.gh.comment(issue["number"], reply)
    else:
        sweep(ctx)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from ghapi import GitHub
    from gitrepo import Repo
    gh = GitHub(os.environ.get("GH_TOKEN", ""), os.environ["REPO"])
    repo = Repo(os.environ.get("COMMUNITY_DATA", "data"))
    ctx = Ctx(gh, repo, os.environ.get("AUTHOR_KEY", ""))
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    event = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
    handle(ctx, name, event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
