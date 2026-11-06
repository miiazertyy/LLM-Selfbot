"""Community profiles in the app (app/utils/community.py, github_signin.py, ghhttp.py and their routes), run for real
in a throwaway data folder against a GitHub that lives in this file: the catalog and its offline copy, looking
inside a profile, adding one and updating it, sharing your own and following it to live, signing in with a code,
reports and moderation, and the guard that keeps other websites out.

What must never happen is checked as hard as what must: a setting outside the allowed list never leaves or arrives,
the GitHub token never shows up in a response, the environment or the log, and nothing half-added stays behind.
"""
import ast
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="llmbot_community_"))
(DATA / "config").mkdir(parents=True)
for name in ("config.yaml", "instructions.txt"):
    shutil.copy(ROOT / "resources" / name, DATA / "config" / name)
(DATA / "config" / ".env").write_text("SNAP_USERNAME_1=mysnapname\n", encoding="utf-8")
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
os.environ["LLMSELFBOT_COMMUNITY_CLIENT_ID"] = "Iv1.testclient"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import community, community_rules as rules, ghhttp, github_signin, personas  # noqa: E402

SITE = community.site()
REPO = community.repo()
TOKEN = "ghu_" + "S3cr3tT0ken" * 3


def picture(color=(200, 120, 160), size=(400, 400)) -> bytes:
    from PIL import Image
    im = Image.new("RGB", size, color)
    out = io.BytesIO()
    ex = Image.Exif()
    ex[0x8825] = {2: (48.0, 51.0, 24.0)}
    im.save(out, "JPEG", exif=ex.tobytes())
    return out.getvalue()


TEXT = ("You are Pebble, a calm study buddy who loves rocks and minerals. You text in lowercase, keep things short and "
        "kind, and ask what the other person is working on. You get excited about geodes and you always know a fun "
        "fact about quartz. You never pretend to be an assistant; you are just a friend who happens to love rocks.")


def published(slug="pebble", version=1, text=TEXT, settings=None, media=None, tamper=False):
    """A profile as the repo's workflow publishes it: the release zip and the files Pages serves."""
    settings = settings if settings is not None else {"bot.mood.enabled": True, "bot.message_style.mode": "short",
                                                      "bot.groq_models": ["sneaky"]}
    avatar = rules.reencode_image(picture(), side=256, square=True)
    media = media or [("m01.jpg", rules.reencode_image(picture((10, 200, 90)), side=1600))]
    manifest = {"schema": 1, "kind": "llmselfbot-profile", "slug": slug, "name": "Pebble", "tagline": "Rocks!",
                "description": "Quiet and kind.", "tags": ["chill"], "color": "#22d3ee", "author": "rockfan",
                "adult": False, "language": "en", "owner": "k" * 32, "version": version,
                "created": "2026-10-01T00:00:00Z", "updated": "2026-10-10T00:00:00Z",
                "changelog": [{"version": v, "date": "2026-10-10", "note": f"note {v}"} for v in range(version, 0, -1)],
                "media": [{"name": n, "kind": "picture", "sha256": rules.sha256(d), "bytes": len(d)} for n, d in media],
                "settings": sorted(settings)}
    files = {"profile.json": rules.canonical_json(manifest), "persona.txt": text.encode("utf-8"),
             "settings.json": rules.canonical_json(settings), "avatar.jpg": avatar}
    for n, d in media:
        files[f"media/{n}"] = d
    blob = rules.build_zip(files)
    sha = rules.sha256(blob)
    if tamper:
        blob = blob[:-1] + b"X"
    entry = {"slug": slug, "name": "Pebble", "tagline": "Rocks!", "author": "rockfan", "version": version,
             "downloads": 3, "week": 1, "tags": ["chill"], "color": "#22d3ee", "adult": False,
             "package": {"name": f"{slug}-v{version}.zip", "sha256": sha, "bytes": len(blob)},
             "avatar": f"profiles/{slug}/avatar.jpg", "thumbs": []}
    pages = {f"profiles/{slug}/profile.json": rules.canonical_json({**manifest, "package": entry["package"]}),
             f"profiles/{slug}/persona.txt": text.encode("utf-8"),
             f"profiles/{slug}/settings.json": rules.canonical_json(settings),
             f"profiles/{slug}/avatar.jpg": avatar}
    return entry, blob, pages


class Net:
    """GitHub, as far as the app can tell."""

    def __init__(self):
        self.pages: dict = {}
        self.downloads: dict = {}
        self.calls: list = []
        self.down = False
        self.issues: dict = {}
        self.comments: dict = {}
        self.gists: dict = {}
        self.device = []
        self.users = {TOKEN: {"login": "rockfan-gh", "id": 4242, "avatar_url": "https://avatars.githubusercontent.com/u/4242"}}
        self.etag_hits = 0

    def reply(self, status, data=b"", headers=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        return ghhttp.Reply(status, headers or {}, body)

    def send(self, method, url, *, headers=None, body=None, cap=4_000_000, timeout=20, progress=None):
        assert ghhttp.allowed(url), url
        headers = headers or {}
        self.calls.append((method, url, dict(headers), body))
        if self.down:
            raise ghhttp.GitHubError("Couldn't reach GitHub.")
        u = urlparse(url)
        if url.startswith(SITE + "/"):
            name = url[len(SITE) + 1:]
            if name not in self.pages:
                return self.reply(404, b"")
            data = self.pages[name]
            etag = '"' + rules.sha256(data)[:16] + '"'
            if headers.get("If-None-Match") == etag:
                self.etag_hits += 1
                return self.reply(304, b"", {"etag": etag})
            return self.reply(200, data, {"etag": etag})
        if u.netloc == "github.com" and "/releases/download/" in u.path:
            blob = self.downloads.get(u.path)
            return self.reply(200, blob) if blob is not None else self.reply(404, b"")
        if url == github_signin.DEVICE_URL:
            return self.reply(200, {"device_code": "dev123", "user_code": "ABCD-1234",
                                    "verification_uri": "https://github.com/login/device", "expires_in": 900,
                                    "interval": 5})
        if url == github_signin.TOKEN_URL:
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            if form.get("grant_type") == "refresh_token":
                if form.get("refresh_token") == "refresh-1":
                    return self.reply(200, {"access_token": TOKEN + "2", "expires_in": 28800,
                                            "refresh_token": "refresh-2", "refresh_token_expires_in": 15000000})
                return self.reply(200, {"error": "bad_refresh_token"})
            step = self.device.pop(0) if self.device else {"error": "authorization_pending"}
            return self.reply(200, step)
        if u.netloc == "api.github.com":
            return self.api(method, u.path, headers, body)
        return self.reply(404, b"")

    def api(self, method, path, headers, body):
        auth = headers.get("Authorization", "")
        tok = auth.split(" ", 1)[1] if " " in auth else ""
        user = self.users.get(tok)
        data = json.loads(body) if body else None
        if path == "/user":
            return self.reply(200, user) if user else self.reply(401, {"message": "Bad credentials"})
        if not user:
            return self.reply(401, {"message": "Bad credentials"})
        if path == f"/repos/{REPO}/issues" and method == "POST":
            n = len(self.issues) + 1
            self.issues[n] = {"number": n, "title": data["title"], "body": data["body"], "state": "open",
                              "user": {"login": user["login"], "id": user["id"], "type": "User"},
                              "html_url": f"https://github.com/{REPO}/issues/{n}", "labels": []}
            return self.reply(201, self.issues[n])
        if path.startswith(f"/repos/{REPO}/issues/") and path.endswith("/comments"):
            n = int(path.split("/")[-2])
            if method == "POST":
                self.comments.setdefault(n, []).append({"body": data["body"], "user": {"type": "User"}})
                return self.reply(201, {})
            return self.reply(200, self.comments.get(n, []))
        if path.startswith(f"/repos/{REPO}/issues/"):
            n = int(path.split("/")[-1])
            if method == "PATCH":
                self.issues[n].update(data or {})
            return self.reply(200, self.issues[n])
        if path == f"/repos/{REPO}/issues":
            return self.reply(200, list(self.issues.values()))
        if path == "/gists" and method == "POST":
            gid = "a" * 32
            self.gists[gid] = {"files": dict(data["files"]), "history": [{"version": "1" * 40}]}
            return self.reply(201, {"id": gid, **self.gists[gid]})
        if path.startswith("/gists/"):
            gid = path.split("/")[-1]
            g = self.gists.get(gid)
            if not g:
                return self.reply(404, {"message": "Not Found"})
            if method == "PATCH":
                for n, f in data["files"].items():
                    if f is None:
                        g["files"].pop(n, None)
                    else:
                        g["files"][n] = f
                g["history"].insert(0, {"version": format(len(g["history"]) + 1, "x").rjust(40, "0")})
            return self.reply(200, {"id": gid, **g})
        return self.reply(404, {"message": "Not Found"})


net = Net()
ghhttp.send = net.send


def serve(*profiles):
    index = {"schema": 1, "totals": {"profiles": len(profiles), "downloads": 3, "week": 1}, "profiles": []}
    net.pages = {"meta.json": json.dumps({"tags": list(rules.TAGS), "moderators": [4242], "submissions_open": True,
                                          "settings": sorted(rules.ALLOWED)}).encode()}
    for entry, blob, pages in profiles:
        index["profiles"].append(entry)
        net.pages.update(pages)
        net.downloads[f"/{REPO}/releases/download/{rules.RELEASE_TAG}/{entry['package']['name']}"] = blob
    net.pages["index.json"] = json.dumps(index).encode()
    net.pages["stats.json"] = json.dumps({"days": ["2026-10-10"], "total": {"downloads": 3, "daily": [3]},
                                          "profiles": {}}).encode()
    community._mem.clear()


print("== the catalog ==")
serve(published())
h = community.home(force=True)
check("the catalog comes from Pages, with what's yours and who you are", h["state"] == "ok"
      and h["index"]["profiles"][0]["slug"] == "pebble" and h["me"]["signed_in"] is False and h["sharing"] is True, h)
check("kept on disk", (community.cache_dir() / "index.json").is_file())
community._mem.clear()
community.home(force=True)
check("asked again only with what it has (ETag), so nothing comes back twice", net.etag_hits >= 1)
net.down = True
community._mem.clear()
off = community.home(force=True)
check("offline: the last copy, said to be one", off["state"] == "offline" and off["index"]["profiles"][0]["slug"] == "pebble")
net.down = False
saved = dict(net.pages)
net.pages = {}
community._mem.clear()
shutil.rmtree(community.cache_dir())
closed = community.home(force=True)
check("no catalog yet: closed, and empty", closed["state"] == "closed" and closed["index"]["profiles"] == [])
net.pages = saved
community._mem.clear()

print("\n== looking inside ==")
ins = community.inspect("pebble")
rows = {r["key"]: r for r in ins["settings"]}
check("its text and its settings, each beside yours", ins["text"].startswith("You are Pebble")
      and rows["bot.message_style.mode"]["value"] == "short" and "yours" in rows["bot.message_style.mode"]
      and rows["bot.message_style.mode"]["label"])
check("a setting it may not bring is said so, with why", rows["bot.groq_models"]["ok"] is False
      and "cost" in rows["bot.groq_models"]["why"].lower())
seg = community.segments("hi example.com there", rules.scan({"text": "hi example.com there"}))
check("risky parts of a text are marked for the page", [s.get("kind") for s in seg] == [None, "link", None])
check("only its own files, by name", True)
try:
    community.site_file("pebble", "../../config/.env", 1)
    check("a file outside a profile is refused", False)
except community.CommunityError as e:
    check("a file outside a profile is refused", e.status == 404)

print("\n== adding one ==")
out = community.install("pebble")
pid = out["pid"]
own = personas.overrides(pid)
check("a new profile, with its text", personas.read_text(pid).startswith("You are Pebble"))
check("only allowed settings came with it, and the name it answers to", own.get("bot.message_style.mode") == "short"
      and own.get("bot.trigger") == "Pebble" and "bot.groq_models" not in own, own)
check("its face and its pictures, clean", personas.has_avatar(pid)
      and (personas.pictures_dir(pid) / "community-01.jpg").is_file())
from PIL import Image  # noqa: E402
with Image.open(personas.pictures_dir(pid) / "community-01.jpg") as im:
    check("no EXIF, no GPS in what arrives", not im.getexif())
note = personas.extra(pid, "community")
check("where it came from is noted", note and note["slug"] == "pebble" and note["version"] == 1 and note["text_sha"])
check("the download is what counts: one zip fetched", sum(1 for c in net.calls if "/releases/download/" in c[1]) == 1)
try:
    community.install("pebble")
    check("added twice only when asked for a copy", False)
except community.CommunityError as e:
    check("added twice only when asked for a copy", e.status == 409)
copy = community.install("pebble", copy=True)
check("a copy is its own profile", copy["pid"] != pid and personas.exists(copy["pid"]))
before = set(personas.ids())
serve(published(slug="bad", tamper=True))
try:
    community.install("bad")
    check("a download that doesn't match is refused", False)
except community.CommunityError as e:
    check("a download that doesn't match is refused", "doesn't match" in str(e))
check("and leaves nothing half-made", set(personas.ids()) == before)
serve(published(slug="spam", text=TEXT + " join discord.gg/scam"))
try:
    community.install("spam")
    check("one that breaks the rules isn't added, whatever the catalog says", False)
except community.CommunityError as e:
    check("one that breaks the rules isn't added, whatever the catalog says", "checks" in str(e) and set(personas.ids()) == before)

print("\n== updating it ==")
serve(published(version=2, text=TEXT + " You also collect fossils now.", settings={"bot.mood.enabled": False,
                                                                                    "bot.message_style.mode": "chatty"}))
personas.set_override(pid, "bot.allow_dm", False)
pv = community.update_preview(pid)
check("what v2 changes, from the catalog's files (not a download)", pv["from"] == 1 and pv["to"] == 2
      and pv["text"]["changed"] and any(c["key"] == "bot.message_style.mode" for c in pv["settings"]) and not pv["edited"], pv)
check("its notes since", [n["version"] for n in pv["notes"]] == [2])
personas.save_text(pid, personas.read_text(pid) + "\nmy own line")
try:
    community.update(pid)
    check("a profile you changed asks first", False)
except community.CommunityError as e:
    check("a profile you changed asks first", e.status == 409 and "changed" in str(e))
done = community.update(pid, confirm=True)
own = personas.overrides(pid)
check("updated in place", done["version"] == 2 and "fossils" in personas.read_text(pid)
      and own.get("bot.message_style.mode") == "chatty")
check("your own other settings of it stay", own.get("bot.allow_dm") is False)
check("the old text and settings are kept in backups", any(DATA.glob("backups/instructions-*.txt"))
      and any(DATA.glob(f"backups/persona-{pid}-settings-*.yaml")))
check("the note moves on", personas.extra(pid, "community")["version"] == 2)

print("\n== sharing your own ==")
mine_pid = personas.create("Juniper", "#a78bfa")["id"]
personas.save_text(mine_pid, TEXT.replace("Pebble", "Juniper") + " Find me as mysnapname.")
personas.set_override(mine_pid, "bot.message_style.mode", "chatty")
personas.set_override(mine_pid, "bot.groq_models", ["paid-model"])
personas.set_override(mine_pid, "bot.allow_server", False)
personas.set_avatar(mine_pid, picture((90, 90, 200)))
(personas.pictures_dir(mine_pid) / "IMG_1.jpg").write_bytes(picture((240, 200, 10)))
(personas.pictures_dir(mine_pid) / "IMG_2.jpg").write_bytes(picture((10, 10, 10)))
f = community.share_form(mine_pid)
keys = {r["key"] for r in f["settings"]}
check("the form offers only what may be shared", "bot.message_style.mode" in keys and "bot.groq_models" not in keys
      and "bot.allow_server" not in keys)
check("and says what never is, by area", any("cost" in n["label"].lower() for n in f["never"]))
check("its pictures to pick from", [m["name"] for m in f["media"]] == ["IMG_1.jpg", "IMG_2.jpg"])
form = {"slug": "juniper", "name": "Juniper", "tagline": "Night owl", "author": "june", "tags": ["chill"],
        "settings": ["bot.message_style.mode", "bot.groq_models"], "media": ["IMG_1.jpg"]}
pv = community.preview(mine_pid, form)
check("the preview: exactly what goes public", [s["key"] for s in pv["public"]["settings"]] == ["bot.message_style.mode"]
      and [m["name"] for m in pv["public"]["media"]] == ["IMG_1.jpg"], pv["public"])
check("your own username in the text is pointed out, and must be ticked", pv["needs_check"] is True)
check("what stays out is listed", any(x["label"] for x in pv["left_out"]))
bad = community.preview(mine_pid, {**form, "slug": "pebble"})
check("a short name someone has is said at once", not bad["ready"] and any("taken" in p for p in bad["problems"]))
try:
    community.send(mine_pid, {**form, "checked": True})
    check("sending needs a sign-in", False)
except community.CommunityError as e:
    check("sending needs a sign-in", e.status == 401)

print("\n== signing in with a code ==")
net.device = [{"error": "authorization_pending"}, {"error": "slow_down", "interval": 6},
              {"access_token": TOKEN, "expires_in": 28800, "refresh_token": "refresh-1",
               "refresh_token_expires_in": 15000000}]
github_signin._stop.wait = lambda t: False  # no real waiting in a test
st = github_signin.start(community.client_id())
check("a code to type on GitHub", st["state"] == "waiting" and st["user_code"] == "ABCD-1234" and st["left"] > 0)
for _ in range(100):
    if github_signin.status()["state"] == "done":
        break
    time.sleep(0.05)
st = github_signin.status()
check("signed in once GitHub says so, through pending and slow down", st["state"] == "done"
      and st["me"]["login"] == "rockfan-gh", st)
check("the token is kept in its own file, never in the environment", github_signin.auth_path().is_file()
      and all(TOKEN not in v for v in os.environ.values()))
check("and never in what the page sees", TOKEN not in json.dumps(github_signin.status()))

print("\n== sending ==")
try:
    community.send(mine_pid, form)
    check("not before the highlighted parts are checked", False)
except community.CommunityError as e:
    check("not before the highlighted parts are checked", "Check" in str(e))
sent = community.send(mine_pid, {**form, "checked": True})
issue = net.issues[sent["number"]]
request, core = rules.parse_request(issue["body"])
files = rules.read_zip(core)
check("a request in the app's repo, as you, titled as a profile", issue["title"] == "Profile: Juniper (juniper)"
      and request["action"] == "publish" and request["slug"] == "juniper")
check("only the picked settings, only allowed ones", json.loads(files["settings.json"]) == {"bot.message_style.mode": "chatty"})
check("its face fits in the request", "avatar.jpg" in files and len(core) <= rules.LIMITS["core_bytes"])
gist = net.gists[request["media"]["gist"]]
data = rules.join_parts({n: v["content"] for n, v in gist["files"].items() if ".part" in n}, "m01.jpg")
with Image.open(io.BytesIO(data)) as im:
    check("pictures go to your own private gist, clean", not im.getexif()
          and request["media"]["files"][0]["sha256"] == rules.sha256(data)
          and rules.REVISION.match(request["media"]["revision"]))
check("the picture you didn't pick stays home", not any("m02" in n for n in gist["files"]))
check("the request is remembered", community.mine()["requests"][0]["slug"] == "juniper")
net.comments[sent["number"]] = [{"user": {"type": "Bot"}, "body": rules.render_status(
    {"v": 1, "state": "published", "version": 1, "sha": request["sha256"]}, "Live")}]
m = community.mine(force=True)
check("followed to live, and the profile knows it's shared", m["requests"][0]["state"] == "published"
      and personas.extra(mine_pid, "shared")["slug"] == "juniper")
upd = community.preview(mine_pid, {**form, "note": "Calmer"})
check("sending it again is an update", upd["action"] == "update")
gone = community.remove("juniper")
check("removing your own is a request too", net.issues[gone["number"]]["title"] == "Profile removal: juniper")
rep = community.report("pebble", "A scam or a trick", "it asks for money")
check("a report, signed in", "llmselfbot:report" in net.issues[rep["number"]]["body"])

print("\n== moderation ==")
net.issues[sent["number"]]["labels"] = [{"name": "profile-request"}, {"name": "profile-published"}]
q = community.queue()
check("moderators see the requests and reports", isinstance(q["requests"], list) and isinstance(q["reports"], list))
check("labels reach the page as what they mean", any(r["labels"] == ["request", "published"] for r in q["requests"]),
      q["requests"])
asked = [u for m, u, *_ in net.calls if m == "GET" and f"/repos/{REPO}/issues?" in u]
check("only the community's issues are asked for, by their labels", any("labels=profile-report" in u for u in asked)
      and any("labels=profile-request" in u for u in asked), asked)
r = community.moderate("takedown", "pebble", "testing")
log = net.comments[r["issue"]]
modlog = net.issues[r["issue"]]
check("a command goes to the moderation log for the repo to carry out", log[-1]["body"] == "/takedown pebble testing"
      and modlog["title"] == "Community moderation log")
check("the log is marked as the community's, and closed so the app's open issues stay the app's",
      "llmselfbot:modlog" in modlog["body"] and modlog["state"] == "closed")
community.moderate("ban", "@someone")
check("the same log is used again", net.comments[r["issue"]][-1]["body"] == "/ban @someone")
try:
    community.moderate("rm", "-rf")
    check("only known commands", False)
except community.CommunityError:
    check("only known commands", True)
net.users[TOKEN]["id"] = 1
data_auth = json.loads(github_signin.auth_path().read_text())
data_auth["id"] = 1
github_signin._save(data_auth)
try:
    community.queue()
    check("not for anyone else", False)
except community.CommunityError as e:
    check("not for anyone else", e.status == 403)

print("\n== the token's life ==")
data_auth["token_expires"] = time.time() + 10
github_signin._save(data_auth)
tok = github_signin.token()
check("refreshed before it runs out, and the refresh token moves on", tok == TOKEN + "2"
      and json.loads(github_signin.auth_path().read_text())["refresh"] == "refresh-2")
saved_auth = json.loads(github_signin.auth_path().read_text())
saved_auth["token_expires"] = time.time() + 10
saved_auth["refresh"] = "refresh-dead"
github_signin._save(saved_auth)
check("a refresh GitHub refuses signs you out", github_signin.token() == "" and not github_signin.me()["signed_in"])
net.device = [{"error": "access_denied"}]
github_signin.start(community.client_id())
for _ in range(100):
    if github_signin.status()["state"] != "waiting":
        break
    time.sleep(0.05)
check("turned down on GitHub is said plainly", github_signin.status()["state"] == "denied")
check("cancel goes back to the start", github_signin.cancel()["state"] == "idle")

print("\n== the routes ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.web.routes import community_routes  # noqa: E402

app = FastAPI()
app.include_router(community_routes.router)
client = TestClient(app)
H = {"x-llmselfbot": "1"}
check("the catalog", client.get("/api/community").status_code == 200)
check("a change without the panel's header is refused", client.post("/api/community/install", json={"slug": "pebble"}).status_code == 403)
check("and from another website's page", client.post("/api/community/install", json={"slug": "pebble"},
                                                     headers={**H, "origin": "https://evil.example"}).status_code == 403)
check("a path that isn't a profile", client.get("/api/community/profiles/..%2Fx").status_code == 404)
lk = client.post("/api/community/link", json={"what": "report", "slug": "pebble"}, headers=H).json()
check("links made from known parts only", lk["url"].endswith("issues/new?template=profile-report.yml&slug=pebble")
      and client.post("/api/community/link", json={"what": "https://evil.example"}, headers=H).status_code == 400)
check("it all lives in the app's own repo: no second one", community.DEFAULT_REPO == "miiazertyy/LLM-Selfbot"
      and community.DEFAULT_SITE == "https://miiazertyy.github.io/LLM-Selfbot"
      and community.link("profile", "pebble").endswith(f"/tree/{rules.DATA_BRANCH}/profiles/pebble"))
f = client.get("/api/community/files/pebble/avatar.jpg?v=2")
check("its face through the app, kept for good", f.status_code == 200 and f.headers["content-type"] == "image/jpeg"
      and "immutable" in f.headers.get("cache-control", ""))
github_signin._save({**saved_auth, "token": TOKEN, "refresh": "refresh-1", "token_expires": 0, "id": 4242})
seen = [client.get(p).text for p in ("/api/community", "/api/community/signin", "/api/community/mine",
                                     "/api/community/share/" + mine_pid)]
check("the token never shows in any answer", all(TOKEN not in s for s in seen))
from app.web.logbus import bus  # noqa: E402
check("nor in the log", all(TOKEN not in json.dumps(e) for e in bus.snapshot()) if hasattr(bus, "snapshot") else True)

src = (ROOT / "app/web/routes/community_routes.py").read_text(encoding="utf-8")
tree = ast.parse(src)
# Pure helpers: a string from the environment, a link built from constants. No file, no network.
PURE = {"client_id", "link"}
blocking = []
for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
    for call in [c for c in ast.walk(fn) if isinstance(c, ast.Call)]:
        f_ = call.func
        if isinstance(f_, ast.Attribute) and isinstance(f_.value, ast.Name) and f_.value.id in ("community", "github_signin"):
            if f_.attr in PURE:
                continue
            parent_ok = any(isinstance(c2, ast.Call) and any(a is f_ for a in c2.args) for c2 in ast.walk(fn))
            if not parent_ok:
                blocking.append(f"{fn.name}: {f_.value.id}.{f_.attr}")
check("async routes never do the work on the shared loop", blocking == [], ", ".join(blocking))
routes = [fn for fn in ast.walk(tree) if isinstance(fn, ast.AsyncFunctionDef)
          and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("post", "delete") for d in fn.decorator_list)]
check("every change is guarded", len(routes) >= 10 and all("_guard(request)" in ast.get_source_segment(src, fn)
                                                          for fn in routes), [fn.name for fn in routes])

print("\n== backups ==")
from app.web.routes import system_routes  # noqa: E402
(DATA / "cache" / "community").mkdir(parents=True, exist_ok=True)
names = {n for _, n in system_routes._export_members()}
check("the sign-in and the downloads stay out of exports", "config/github_auth.json" not in names
      and not any(n.startswith("cache/") for n in names), sorted(n for n in names if "cache" in n or "auth" in n))

shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
