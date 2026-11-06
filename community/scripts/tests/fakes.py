"""Stand-ins for the tests: GitHub in memory, a real git repo in a temp folder with its own remote (the app's main
branch, and the data branch made the way the setup workflow makes it), and a gist as a folder of parts."""
from __future__ import annotations

import io
import itertools
import subprocess
import tempfile
from pathlib import Path

import community_rules as rules
from gitrepo import seed_branch

ROOT = Path(__file__).resolve().parent.parent.parent
SEED = ROOT / "data"
_ids = itertools.count(1000)


class FakeGitHub:
    def __init__(self, users=None):
        self.issues_by_n: dict = {}
        self.comments_by_n: dict = {}
        self.labels: dict = {}
        self.closed: dict = {}
        self.releases_by_tag: dict = {}
        self.dispatched: list = []
        self.enabled: list = []
        self.reactions: list = []
        self.users = users or {}
        self.perms: dict = {}
        self.latest_tag = "v1.7.1"

    # issues
    def add_issue(self, n, body, user, created_at="2026-10-10T10:00:00Z", labels=(), state="open"):
        issue = {"number": n, "body": body, "user": user, "state": state, "created_at": created_at,
                 "labels": [{"name": x} for x in labels]}
        self.issues_by_n[n] = issue
        self.comments_by_n.setdefault(n, [])
        return issue

    def issue(self, n):
        return self.issues_by_n[n]

    def issues(self, **params):
        out = list(self.issues_by_n.values())
        if params.get("state") == "open":
            out = [i for i in out if i["state"] == "open"]
        if params.get("creator"):
            out = [i for i in out if i["user"]["login"] == params["creator"]]
        return out

    def comments(self, n):
        return list(self.comments_by_n.get(n, []))

    def comment(self, n, body):
        c = {"id": next(_ids), "body": body, "user": {"login": "github-actions[bot]", "type": "Bot", "id": 41898282}}
        self.comments_by_n.setdefault(n, []).append(c)
        return c

    def edit_comment(self, cid, body):
        for cs in self.comments_by_n.values():
            for c in cs:
                if c["id"] == cid:
                    c["body"] = body
                    return c
        raise KeyError(cid)

    def react(self, cid, content="+1"):
        self.reactions.append((cid, content))

    def add_labels(self, n, labels):
        self.labels.setdefault(n, set()).update(labels)

    def remove_label(self, n, label):
        self.labels.setdefault(n, set()).discard(label)

    def close(self, n, reason="completed", lock=True):
        self.issues_by_n[n]["state"] = "closed"
        self.closed[n] = reason

    def ensure_labels(self, specs):
        self.made_labels = set(specs)

    def open_issue(self, title, body, labels=()):
        n = max(self.issues_by_n or [0]) + 1
        return self.add_issue(n, body, {"login": "github-actions[bot]", "type": "Bot", "id": 41898282}, labels=labels)

    # people
    def user(self, login):
        return self.users[login]

    def permission(self, login):
        return self.perms.get(login, "read")

    # releases
    def latest_release_tag(self):
        return self.latest_tag

    def release_by_tag(self, tag):
        return self.releases_by_tag.get(tag)

    def release_assets(self, rid):
        for rel in self.releases_by_tag.values():
            if rel["id"] == rid:
                return list(rel["assets"])
        return []

    def create_release(self, tag, name, body, prerelease=False, target=""):
        rel = {"id": next(_ids), "tag_name": tag, "name": name, "body": body, "assets": [], "prerelease": prerelease,
               "target_commitish": target or "main"}
        self.releases_by_tag[tag] = rel
        return rel

    def upload_asset(self, release, name, data, content_type="application/zip"):
        asset = {"id": next(_ids), "name": name, "size": len(data), "download_count": 0,
                 "digest": f"sha256:{rules.sha256(data)}", "data": data}
        release["assets"].append(asset)
        return asset

    def delete_asset(self, aid):
        for rel in self.releases_by_tag.values():
            rel["assets"] = [a for a in rel["assets"] if a["id"] != aid]

    def enable(self, workflow):
        self.enabled.append(workflow)

    def dispatch(self, workflow, ref="main"):
        self.enable(workflow)
        self.dispatched.append(workflow)

    def asset(self, name):
        rel = self.releases_by_tag.get(rules.RELEASE_TAG) or {"assets": []}
        return next((a for a in rel["assets"] if a["name"] == name), None)

    def asset_names(self):
        rel = self.releases_by_tag.get(rules.RELEASE_TAG) or {"assets": []}
        return sorted(a["name"] for a in rel["assets"])

    # helpers for the tests
    def status(self, n):
        for c in reversed(self.comments_by_n.get(n, [])):
            st = rules.parse_status(c["body"])
            if st is not None:
                return st, c["body"]
        return None, ""


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def make_repo(tmp: Path) -> Path:
    """The app's repo as a bare remote (its main branch with the app's code in it), the data branch made on it by the
    setup script from a checkout of main (as the workflow runs it), and that branch checked out as the workflows check
    it out. Returns the data checkout."""
    remote = tmp / "remote.git"
    app = tmp / "app"
    git("init", "-q", "--bare", "-b", "main", str(remote))
    git("init", "-q", "-b", "main", str(app))
    (app / "main.py").write_text("print('the app')\n")
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=app)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "the app", cwd=app)
    git("remote", "add", "origin", str(remote), cwd=app)
    git("push", "-q", "origin", "main", cwd=app)
    seed_branch(app, SEED)
    work = tmp / "data"
    git("clone", "-q", "-b", rules.DATA_BRANCH, str(remote), str(work))
    return work


def app_checkout(work: Path) -> Path:
    """The checkout of the app's main branch that made the data branch, beside it."""
    return work.parent / "app"


def main_head(work: Path) -> str:
    """The app's main branch on the remote, to see that nothing here ever moved it."""
    return git("ls-remote", "origin", "refs/heads/main", cwd=work).stdout.split()[0]


def picture_bytes(color=(200, 120, 160), size=(320, 400), fmt="JPEG", exif=True) -> bytes:
    from PIL import Image
    im = Image.new("RGB", size, color)
    out = io.BytesIO()
    if exif and fmt == "JPEG":
        ex = Image.Exif()
        ex[0x010F] = "SecretCam"           # Make
        ex[0x8825] = {2: (48.0, 51.0, 24.0)}  # GPS, which must never survive
        im.save(out, fmt, exif=ex.tobytes())
    else:
        im.save(out, fmt)
    return out.getvalue()


TEXT = ("You are Pebble, a calm study buddy who loves rocks and minerals. You text in lowercase, keep things short and "
        "kind, and ask what the other person is working on. You get excited about geodes and you always know a fun "
        "fact about quartz. You never pretend to be an assistant; you are just a friend who happens to love rocks.")


def core_files(slug="test-pebble", name="Pebble", text=TEXT, settings=None, avatar=True, **meta) -> dict:
    m = {"slug": slug, "name": name, "tagline": "A calm study buddy who loves rocks", "description": "Quiet and kind.",
         "tags": ["chill", "nerdy"], "color": "#a78bfa", "author": "rockfan", "adult": False, "language": "en",
         "note": "", **meta}
    files = {"profile.json": rules.canonical_json(m), "persona.txt": text.encode("utf-8"),
             "settings.json": rules.canonical_json(settings if settings is not None else
                                                   {"bot.mood.enabled": True, "bot.message_style.mode": "short"})}
    if avatar:
        files["avatar.jpg"] = picture_bytes(size=(300, 300))
    return files


def request_body(action="publish", slug="test-pebble", files=None, media=None, app="1.7.1", **meta) -> str:
    if action == "remove":
        return rules.render_request({"v": 1, "action": "remove", "slug": slug, "sha256": "", "bytes": 0}, b"",
                                    f"Remove {slug}")
    core = rules.build_zip(files or core_files(slug=slug, **meta))
    req = {"v": 1, "action": action, "slug": slug, "sha256": rules.sha256(core), "bytes": len(core), "app": app}
    if media:
        req["media"] = media
    return rules.render_request(req, core, f"**{slug}**")


def gist_from(files: dict, folder: Path, chars: int = 50_000) -> list:
    """Media files written as a gist would hold them; returns the manifest."""
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, data in files.items():
        for i, part in enumerate(rules.split_parts(data, chars)):
            (folder / rules.part_name(name, i)).write_text(part, encoding="ascii")
        manifest.append({"name": name, "kind": "picture" if name.endswith(".jpg") else "video",
                         "sha256": rules.sha256(data), "bytes": len(data)})
    return manifest


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="community-test-"))
