"""The search for a model under Settings, Models: what Hugging Face says, shaped for the page, with how each would do on
this computer, its sizes, and the pictures of whoever made them. Hugging Face is never reached here: what it answers is
written out below, made up in its shape."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name

from app.utils import hfsearch, localai, localfix  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


GB = 1024 ** 3
hfsearch._machine = lambda: {"ram": 16 * GB, "vram": 4 * GB}    # about 11 GB to give a model
# The looks behind a list have a part of their own, below: until then each search asks once, and only for what it says.
real_look_behind = hfsearch._look_behind
hfsearch._look_behind = lambda orders: None


def item(repo, tag="text-generation", total=9_000_000_000, arch="qwen35", **kw):
    return {"id": repo, "author": repo.split("/")[0], "downloads": 5000, "likes": 12, "lastModified": "2026-09-29T10:28:23.000Z",
            "pipeline_tag": tag, "gguf": {"total": total, "architecture": arch, "chat_template": "x" * 50}, **kw}


print("\n== what goes on the list ==")
r = hfsearch.row_of(item("maker/Small-9B-GGUF"))
check("named without its -GGUF, by whoever made it", r["name"] == "Small-9B" and r["author"] == "maker" and r["repo"] == "maker/Small-9B-GGUF", str(r))
check("how much it is used, and when it changed", r["downloads"] == 5000 and r["likes"] == 12 and r["updated"] > 1.7e9)
check("no chat template or anything else long goes to the page", "gguf" not in r and len(json.dumps(r)) < 300)
for tag in ("automatic-speech-recognition", "text-to-speech", "text-to-image", "feature-extraction", "image-text-to-video", "object-detection"):
    check(f"not {tag}: it downloads fine and answers nothing", hfsearch.row_of(item("a/b", tag)) is None)
check("what can see says so", hfsearch.row_of(item("a/b", "image-text-to-text"))["sees"] is True and r["sees"] is False)
check("with no word on what it does, its architecture says", hfsearch.row_of(item("a/b", None, arch="gemma4")) is not None
      and hfsearch.row_of(item("a/b", None, arch="mert2")) is None and hfsearch.row_of(item("a/b", None, arch="")) is None)
check("gated: it could not be fetched", hfsearch.row_of(item("a/b", gated="auto")) is None)
check("anything else in the name is refused", hfsearch.row_of(item("../b")) is None and hfsearch.row_of(item("nope")) is None)

print("\n== how many weights ==")
check("what its name says, over what its first file says", hfsearch.row_of(item("a/Big-27B-GGUF", total=1_900_000_000))["weights"] == 27_000_000_000)
check("no size in the name: its file's", hfsearch.row_of(item("a/Flash-Next", total=176_000_000_000))["weights"] == 176_000_000_000)
check("not from a vision part, which is all some repos' first file is", hfsearch.row_of(item("a/Flash", total=500_000_000, arch="clip"))["weights"] == 0)
check("in millions too", hfsearch.row_of(item("a/Tiny-350M"))["weights"] == 350_000_000)

print("\n== will it run here ==")
mach = hfsearch._machine()
check("9B fits, in the usual size", hfsearch.fit_of(9_000_000_000, mach) == "fits")
check("20B only just, in its smallest", hfsearch.fit_of(20_000_000_000, mach) == "tight", hfsearch.fit_of(20_000_000_000, mach))
check("70B no", hfsearch.fit_of(70_000_000_000, mach) == "big")
check("not known either way says nothing", hfsearch.fit_of(0, mach) == "" and hfsearch.fit_of(9_000_000_000, {"ram": 0, "vram": 0}) == "")

print("\n== the search ==")
asked = []
answers = [[item("maker/Small-9B-GGUF"), item("v/Voice", "text-to-speech"), item("x/Huge-70B-GGUF")]]


def fake_get(url, timeout=20.0, accept="", tries=4):
    asked.append(url)
    a = answers[0]
    if isinstance(a, Exception):
        raise a
    return a


real_get = localfix._hf_get
localfix._hf_get = fake_get
s = hfsearch.search("", "popular")
check("what is popular, with nothing typed", s["ok"] and [r["repo"] for r in s["results"]] == ["maker/Small-9B-GGUF", "x/Huge-70B-GGUF"], str(s))
check("each with whether it fits", [r["fit"] for r in s["results"]] == ["fits", "big"])
check("and how much this computer can give one", s["room"] == localfix.budget(mach))
check("only GGUFs, most downloaded first", "filter=gguf" in asked[0] and "sort=downloads" in asked[0] and "direction=-1" in asked[0])
check("no search word with nothing typed", "search=" not in asked[0])
n = len(asked)
hfsearch.search("", "popular")
check("kept a while: asked once", len(asked) == n)
hfsearch.search("", "trending")
check("each order asked for by itself", "sort=trendingScore" in asked[-1])
hfsearch.search("", "new")
check("newest", "sort=createdAt" in asked[-1])
hfsearch.search("Qwen  3.5 ")
check("what is typed, tidied", "search=Qwen+3.5" in asked[-1], asked[-1])
hfsearch.search("https://huggingface.co/maker/Small-9B-GGUF")
check("a link is searched for by its name", "search=maker%2FSmall-9B-GGUF" in asked[-1], asked[-1])
answers[0] = OSError("reset")
f = hfsearch.search("something new")
check("no answer: said, in plain words", f == {"ok": False, "reason": "Hugging Face did not answer. Try again."}, str(f))
for key in list(hfsearch._searches):
    hfsearch._searches[key] = (time.time() - 10_000, hfsearch._searches[key][1])
check("no answer, but one from before: that one", hfsearch.search("", "popular")["ok"])
typed_before = hfsearch.search("qwen  3.5")
check("typed, with no answer: what was found before", typed_before["ok"] and typed_before["stale"] is False)
answers[0] = [item("maker/New-4B-GGUF")]
check("typed, and it answers: a fresh one", hfsearch.search("qwen 3.5")["results"][0]["repo"] == "maker/New-4B-GGUF")

print("\n== a list at once, with a new look behind it ==")
hfsearch._look_behind = real_look_behind
hfsearch._searches.clear()
hfsearch._list_file("downloads").unlink(missing_ok=True)
hfsearch._list_file("trendingScore").unlink(missing_ok=True)
hfsearch._list_file("createdAt").unlink(missing_ok=True)


def settled():
    for _ in range(300):
        with hfsearch._lock:
            if not hfsearch._looking:
                return
        time.sleep(0.01)


answers[0] = [item("maker/Kept-4B-GGUF")]
got = hfsearch.search("", "popular")
settled()
check("nothing kept: it waits for the answer", got["stale"] is False and got["results"][0]["repo"] == "maker/Kept-4B-GGUF")
check("and keeps it on the disk", hfsearch._kept_list("downloads")[1][0]["repo"] == "maker/Kept-4B-GGUF")
check("the other orders are one press away, so they are looked at behind it",
      all(any(f"sort={o}" in a for a in asked) for o in ("trendingScore", "createdAt")), str(asked[-3:]))
check("and kept too", hfsearch._kept_list("trendingScore") is not None and hfsearch._kept_list("createdAt") is not None)
before = len(asked)
hfsearch.search("", "trending")
settled()
check("so pressing one asks nobody", len(asked) == before, str(asked[before:]))
hfsearch._searches.clear()
before = len(asked)
again = hfsearch.search("", "popular")
settled()
check("the app started again: from the disk, asking nobody", again["results"][0]["repo"] == "maker/Kept-4B-GGUF" and len(asked) == before
      and again["stale"] is False, str(asked[before:]))
old = hfsearch._kept_list("downloads")
hfsearch._keep_list("downloads", time.time() - 10_000, old[1])
hfsearch._searches.clear()
answers[0] = [item("maker/Newer-4B-GGUF")]
stale = hfsearch.search("", "popular")
check("kept too long: that one at once, said to be old", stale["stale"] is True and stale["results"][0]["repo"] == "maker/Kept-4B-GGUF")
settled()
fresher = hfsearch.search("", "popular")
check("and the new one when the page asks again", fresher["stale"] is False and fresher["results"][0]["repo"] == "maker/Newer-4B-GGUF")
check("a fit is worked out for each, kept or not", fresher["results"][0]["fit"] == "fits", str(fresher["results"][0]))
hfsearch._list_file("createdAt").write_text("not json", encoding="utf-8")
check("a kept list that cannot be read is no list", hfsearch._kept_list("createdAt") is None)
hfsearch._look_behind = lambda orders: None
localfix._hf_get = real_get

print("\n== one connection, kept open ==")


class Reply:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def read(self):
        return self.body

    def getheader(self, name):
        return self.headers.get(name)


class Conn:
    made = []
    script = []

    def __init__(self, host, timeout=None, source_address=None):
        self.host, self.timeout, self.sock, self.asked, self.source = host, timeout, None, [], source_address
        Conn.made.append(self)

    def request(self, method, path, headers=None):
        self.sock = self.sock or type("Sock", (), {"settimeout": lambda s, t: None})()
        self.asked.append(path)
        self.headers = headers

    def getresponse(self):
        next_up = Conn.script.pop(0)
        if isinstance(next_up, Exception):
            raise next_up
        return next_up

    def close(self):
        self.sock = None


import gzip  # noqa: E402
import http.client  # noqa: E402

real_conn = http.client.HTTPSConnection
http.client.HTTPSConnection = Conn
localfix._hf_get = real_get
localfix.time.sleep, real_sleep = (lambda s: None), localfix.time.sleep
Conn.script = [Reply(body=b'{"a": 1}'), Reply(body=b'{"a": 2}')]
one, two = real_get("https://huggingface.co/api/x"), real_get("https://huggingface.co/api/y?z=1")
check("asked over the same connection", (one, two) == ({"a": 1}, {"a": 2}) and len(Conn.made) == 1 and Conn.made[0].asked == ["/api/x", "/api/y?z=1"])
check("to Hugging Face, and no other", Conn.made[0].host == "huggingface.co")
check("over IPv4: it opens over IPv6 and is then cut, three times in four", Conn.made[0].source == ("0.0.0.0", 0))
Conn.script = [http.client.RemoteDisconnected("closed"), Reply(body=b'{"a": 3}')]
was = len(Conn.made)
slept = []
localfix.time.sleep = slept.append
check("one it had closed since is no failure: asked again at once, on a new one", real_get("https://huggingface.co/api/x") == {"a": 3}
      and len(Conn.made) == was + 1 and not slept, str(slept))
Conn.script = [ConnectionResetError("10054")] * 3 + [Reply(body=b'{"a": 4}')]
localfix._hf_drop()
slept.clear()
check("cut off as it starts: tried again after a moment", real_get("https://huggingface.co/api/x", tries=4) == {"a": 4} and [round(x, 1) for x in slept] == [0.8, 1.6, 2.4], str(slept))
check("each new one the other way from the last, for a network with no IPv4", [c.source for c in Conn.made[-4:]] == [("0.0.0.0", 0), None, ("0.0.0.0", 0), None],
      str([c.source for c in Conn.made[-4:]]))
localai._hf_over_v4 = True
Conn.script = [ConnectionResetError("10054")] * 2
localfix._hf_drop()
try:
    real_get("https://huggingface.co/api/x", tries=2)
    check("cut off every time, it says so, as urllib would", False)
except urllib.error.URLError as e:
    check("cut off every time, it says so, as urllib would", isinstance(e.reason, ConnectionResetError))
    check("and in words", "kept dropping" in localai._net_reason(e), localai._net_reason(e))
Conn.script = [Reply(404)]
slept.clear()
try:
    real_get("https://huggingface.co/api/nope", tries=4)
    check("an answer it gives is not asked again", False)
except urllib.error.HTTPError as e:
    check("an answer it gives is not asked again", e.code == 404 and not slept and not Conn.script)
Conn.script = [Reply(body=gzip.compress(b'{"a": 5}'), headers={"content-encoding": "gzip"})]
check("packed small on the way", real_get("https://huggingface.co/api/x") == {"a": 5})
Conn.script = [Reply(307, headers={"location": "/api/models/new/name"}), Reply(body=b'{"a": 6}')]
check("a renamed repo's redirect is followed", real_get("https://huggingface.co/api/models/old/name") == {"a": 6}
      and Conn.made[-1].asked[-1] == "/api/models/new/name")
http.client.HTTPSConnection = real_conn
localfix.time.sleep = real_sleep
localfix._hf_drop()
localai._hf_over_v4 = True
check("a download goes that way too, and where it redirects to", 'with hf_open(urllib.request.Request(url, headers=headers), timeout=60) as r:' in read("app/utils/localai.py"))
check("by what is asked of each connection it opens", localai.hf_source() == {"source_address": ("0.0.0.0", 0)})
localai.hf_failed()
check("and the other way once one has failed", localai.hf_source() == {})
localai.hf_failed()

print("\n== the files that are not the model ==")
names = {"MTP/mtp-gemma-12b-Q8_0.gguf": False, "mtp-gemma-12b-F16.gguf": False, "FastMTP-model-Q4_K_M.gguf": False,
         "mmproj-F16.gguf": False, "Qwen3.6-35B-A3B-MTP-Q4_K_M.gguf": True, "gemma-12b-Q4_K_M.gguf": True}
got = {f["name"] for f in localfix.model_files([{"name": n, "size": 1} for n in names])}
for n, wanted in names.items():
    check(("the model: " if wanted else "not the model: ") + n, (n in got) == wanted, str(got))

print("\n== its sizes ==")
files = [{"name": "m-Q2_K.gguf", "size": 3 * GB}, {"name": "m-Q4_K_M.gguf", "size": 6 * GB}, {"name": "sub/m-Q4_K_M.gguf", "size": 6 * GB},
         {"name": "m-Q8_0.gguf", "size": 13 * GB}, {"name": "m-F16.gguf", "size": 25 * GB}, {"name": "mmproj-F16.gguf", "size": GB // 2},
         {"name": "MTP/mtp-m-Q8_0.gguf", "size": GB // 2}, {"name": "README.md", "size": 10}]
localfix.repo_files = lambda repo: files
folder = localai.app_models_dir()
(folder / "m-Q2_K.gguf").write_bytes(b"x")
s = hfsearch.sizes("maker/M-GGUF")
check("smallest first, each once, the model's only", [r["tag"] for r in s["sizes"]] == ["Q2_K", "Q4_K_M", "Q8_0", "F16"], str(s["sizes"]))
check("the usual size is the one to pick", [r["tag"] for r in s["sizes"] if r["best"]] == ["Q4_K_M"])
check("what would run badly says so", [r["fits"] for r in s["sizes"]] == [True, True, False, False], str(s["sizes"]))
check("what is here already says so", [r["have"] for r in s["sizes"]] == [True, False, False, False])
check("it can see, having a vision part", s["sees"] is True)
check("a repo in any form", hfsearch.sizes("https://huggingface.co/maker/M-GGUF")["repo"] == "maker/M-GGUF")
check("not a repo: said", hfsearch.sizes("nothing")["ok"] is False)


def cut_off(repo):
    raise OSError("reset")


localfix.repo_files = cut_off
check("cut off: said plainly, not as if it were a download", hfsearch.sizes("maker/M-GGUF") == {"ok": False, "reason": "Hugging Face did not answer. Try again."})

print("\n== whose picture ==")
urls = {"good": "https://cdn-avatars.huggingface.co/v1/a.png", "none": "", "gone": None, "away": "http://evil.example/a.png"}
tried = []
real_picture_url = hfsearch._picture_url
hfsearch._picture_url = lambda a: (tried.append(a), urls.get(a, ""))[1]
real_fetch = hfsearch._fetch_picture


def wait_for_thread():
    for _ in range(200):
        with hfsearch._lock:
            if not hfsearch._fetchers:
                return
        time.sleep(0.02)


hfsearch._fetch_picture = lambda url: (b"PNGDATA", ".png") if "cdn-avatars" in url else real_fetch(url)
hfsearch.PICTURE_TRIES = 3
hfsearch.PICTURE_AGAIN = 0.0
check("nothing fetched until it is asked for", hfsearch.picture("good") is None and not tried)
first = hfsearch.pictures(["good", "none", "../x", "good"])
check("not there yet: being fetched, one each", first["ready"] == [] and first["waiting"] == 2, str(first))
wait_for_thread()
again = hfsearch.pictures(["good", "none"])
check("then there, and no more to wait for", again == {"ready": ["good"], "waiting": 0}, str(again))
check("the file, for the page to draw", hfsearch.picture("good").read_bytes() == b"PNGDATA")
check("someone with no picture is written down, not asked again", tried.count("none") == 1 and hfsearch.picture("none") is None)
hfsearch.pictures(["good"])
wait_for_thread()
check("nor one that is in", tried.count("good") == 1)
hfsearch.pictures(["gone"])
wait_for_thread()
check("a dropped connection is tried again, and given up on", tried.count("gone") == 3 and hfsearch.pictures(["gone"]) == {"ready": [], "waiting": 0},
      str(tried.count("gone")))
hfsearch._given_up["gone"] -= hfsearch.GIVE_UP_FOR + 1
urls["gone"] = "https://cdn-avatars.huggingface.co/v1/gone.png"
hfsearch.pictures(["gone"])
wait_for_thread()
check("given up on for a while, not for good", hfsearch.picture("gone") is not None)
hfsearch.pictures(["away"])
wait_for_thread()
check("a picture from anywhere else is not fetched", hfsearch.picture("away") is None)
check("a name that is no name is nobody", hfsearch.picture("../x") is None and hfsearch.pictures(["../x", "a/b", ""]) == {"ready": [], "waiting": 0})
check("kept under a letter: CON and NUL are makers too", (hfsearch._pictures_folder() / "a_good.png").is_file())


print("\n== side by side ==")
real_one = hfsearch._fetch_one
going = {"now": 0, "most": 0, "each": {}}
go_on = threading.Event()


def slow_one(author):
    with hfsearch._lock:
        going["now"] += 1
        going["most"] = max(going["most"], going["now"])
        going["each"][author] = going["each"].get(author, 0) + 1
    go_on.wait(5)
    with hfsearch._lock:
        going["now"] -= 1
    return True


hfsearch._fetch_one = slow_one
names = [f"maker{i}" for i in range(12)]
for _ in range(5):
    hfsearch.pictures(names)        # as the page does, several times a second, while they come in
    time.sleep(0.01)
check("several at once", going["most"] == hfsearch.PICTURE_WORKERS, str(going["most"]))
check("no more than that", hfsearch._fetchers == hfsearch.PICTURE_WORKERS, str(hfsearch._fetchers))
go_on.set()
wait_for_thread()
check("every one fetched", set(going["each"]) == set(names), str(going["each"]))
check("none twice, however often the page asks while it comes in", all(n == 1 for n in going["each"].values()), str(going["each"]))
hfsearch._fetch_one = real_one
hfsearch._wanted[:] = ["later1", "later2"]
hfsearch._fetchers = hfsearch.PICTURE_WORKERS       # busy: nothing starts, so the line can be read
hfsearch.pictures(["seen"])
check("what the page is waiting for goes first", hfsearch._wanted[0] == "seen", str(hfsearch._wanted))
hfsearch.pictures(["maybe"], later=True)
check("what is only fetched in case goes last", hfsearch._wanted[-1] == "maybe", str(hfsearch._wanted))
hfsearch._wanted.clear()
hfsearch._fetchers = 0

print("\n== whose picture it is, asked ==")
real_ask, stand_in = hfsearch._ask, hfsearch._picture_url


class Said:
    script = []

    @staticmethod
    def ask(host, path, accept):
        next_up = Said.script.pop(0)
        if isinstance(next_up, Exception):
            raise next_up
        return next_up


hfsearch._ask = Said.ask
hfsearch._picture_url = real_picture_url
Said.script = [(200, "application/json", "", b'{"avatarUrl": "https://cdn-avatars.huggingface.co/a.webp"}')]
check("an organisation's", hfsearch._picture_url("org") == "https://cdn-avatars.huggingface.co/a.webp")
Said.script = [(404, "", "", b""), (200, "application/json", "", b'{"avatarUrl": "/avatars/x.svg"}')]
check("not one of those: the other, and a path made whole", hfsearch._picture_url("someone") == "https://huggingface.co/avatars/x.svg")
Said.script = [(404, "", "", b""), (404, "", "", b"")]
check("neither: written down as having none", hfsearch._picture_url("nobody") == "")
for status in (429, 500, 503):
    Said.script = [(status, "", "", b"")]
    check(f"a {status} is not having no picture: asked again later, not kept as a letter for two weeks", hfsearch._picture_url("busy") is None)
Said.script = [OSError("reset")]
check("cut off: asked again later", hfsearch._picture_url("cut") is None)
Said.script = [(307, "", "/api/users/new/avatar", b""), (200, "application/json", "", b'{"avatarUrl": "/a.png"}')]
check("a maker who changed name is followed", hfsearch._picture_url("old") == "https://huggingface.co/a.png")
Said.script = [(200, "text/html", "", b"<html>")]
check("not what was asked for: asked again later", hfsearch._picture_url("odd") is None)
hfsearch._ask = real_ask
hfsearch._picture_url = stand_in


class PictureReply:
    def __init__(self, kind, body=b"x", status=200):
        self.kind, self.body, self.status = kind, body, status
        self.short = False

    def getheader(self, name):
        return self.kind

    def read(self, n=-1):
        self.short = 0 <= n < len(self.body)
        return self.body[:n] if n >= 0 else self.body

    def isclosed(self):
        return not self.short


class PictureConn:
    made = []
    replies = []

    def __init__(self, host, timeout=None, source_address=None):
        self.host, self.sock, self.closed = host, None, False
        PictureConn.made.append(self)

    def request(self, method, path, headers=None):
        self.sock = object()
        self.path = path

    def getresponse(self):
        next_up = PictureConn.replies.pop(0)
        if isinstance(next_up, Exception):
            raise next_up
        return next_up

    def close(self):
        self.closed, self.sock = True, None


http.client.HTTPSConnection = PictureConn
hfsearch._own.__dict__.pop("conns", None)
PictureConn.replies = [PictureReply("image/svg+xml")]
check("no SVG: it can carry a script", real_fetch(urls["good"]) == (b"", ""))
PictureConn.replies = [PictureReply("image/webp", b"y" * (hfsearch.MAX_PICTURE + 5))]
check("nothing enormous, and nothing more asked over one left half read", real_fetch(urls["good"]) == (b"", "") and PictureConn.made[-1].closed)
hfsearch._own.__dict__.pop("conns", None)
PictureConn.replies = [PictureReply("image/webp; charset=x", b"y" * 9), PictureReply("image/png", b"z" * 9)]
was = len(PictureConn.made)
check("a picture is a picture", real_fetch(urls["good"]) == (b"y" * 9, ".webp"))
check("and the next over the same connection", real_fetch(urls["good"]) == (b"z" * 9, ".png") and len(PictureConn.made) == was + 1)
PictureConn.replies = [PictureReply("image/png", b"", status=404)]
check("not there: nothing", real_fetch(urls["good"]) == (b"", ""))
PictureConn.replies = [ConnectionResetError("10054"), PictureReply("image/png", b"w" * 9)]
check("one it had closed since: asked again at once, on a new one", real_fetch(urls["good"]) == (b"w" * 9, ".png"))
PictureConn.replies = [ConnectionResetError("10054")]
hfsearch._own.__dict__.pop("conns", None)
try:
    real_fetch(urls["good"])
    check("a new one cut off: it says so, to go to the back of the line", False)
except OSError:
    check("a new one cut off: it says so, to go to the back of the line", True)
localai._hf_over_v4 = True
http.client.HTTPSConnection = real_conn
hfsearch._own.__dict__.pop("conns", None)
check("only over https", real_fetch("http://cdn-avatars.huggingface.co/a.png") == (b"", ""))
check("and only from Hugging Face", real_fetch("https://evil.example/a.png") == (b"", ""))

print("\n== the routes ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import local_routes  # noqa: E402

app = FastAPI()
app.include_router(local_routes.router)
client = TestClient(app)
localfix._hf_get = lambda url, timeout=20.0, accept="", tries=4: [item("maker/Small-9B-GGUF")]
hfsearch._searches.clear()
check("the search", client.get("/api/local/hf/search", params={"q": "small", "sort": "popular"}).json()["results"][0]["repo"] == "maker/Small-9B-GGUF")
localfix.repo_files = lambda repo: files
check("its sizes", [r["tag"] for r in client.get("/api/local/hf/sizes", params={"repo": "maker/M-GGUF"}).json()["sizes"]][0] == "Q2_K")
check("which pictures are in", client.get("/api/local/hf/pictures", params={"authors": "good,none"}).json()["ready"] == ["good"])
pic = client.get("/api/local/hf/picture", params={"author": "good"})
check("the picture itself, kept by the browser too", pic.status_code == 200 and pic.content == b"PNGDATA" and "max-age" in pic.headers.get("cache-control", ""))
check("none: nothing to draw, and no fetching on the way", client.get("/api/local/hf/picture", params={"author": "nobody-yet"}).status_code == 404
      and "nobody-yet" not in tried)

print("\n== the page ==")
page = read("webui/src/lib/components/ModelSearch.svelte")
local = read("webui/src/lib/components/LocalAI.svelte")
check("the search where the box to paste in was", "<ModelSearch kind={pullKind}" in local and "lc-get-go" not in local)
check("what is going on stays under the box", "between={underway}" in local and "{@render between?.()}" in page)
check("a name that is known can still be fetched as it stands", "const direct = $derived.by" in page and "get(direct)" in page)
check("the size that suits it, in one press, or a size picked", "get(r.repo)" in page and "get(`${r.repo}:${picked.tag}`)" in page)
check("it asks for pictures rather than waiting on each", "api.localHfPictures(authors)" in page and "pictures.includes(r.author)" in page)
check("the letter stays until a picture has loaded", "ms-pic-letter" in page and 'classList.add("is-in")' in page)
check("what it says about each", all(w in page for w in ('"Fits"', "Too big", "Sees pictures", "Fits this computer", "In line")))
check("each size in words as well as its name", '"4": "Balanced"' in page and '"8": "Best"' in page)
check("what will not run is left out, and can be shown", "None of these fit this computer." in page and "Show them anyway" in page)
check("cut off once, it tries again by itself", "tries - 1" in page)
check("heard: its own sounds, and off with the rest of the motion", 'play(openRepo ? "open" : "tick")' in page and ':root[data-motion="off"]' in page)

print("\n== six at a time ==")
check("six to a page, with pages to turn", "const PER_PAGE = 6;" in page and "fitted.slice(at * PER_PAGE, (at + 1) * PER_PAGE)" in page and "Show more" not in page)
check("two across, closing the gap an opened one leaves", "minmax(min(100%, 290px), 1fr)" in page and "grid-auto-flow: dense" in page and "grid-column: 1 / -1" in page)
check("a short last page takes the same room, so the buttons do not move", "PER_PAGE - shown.length" in page and "is-blank" in page)
check("a list that came back shorter cannot leave it on a page that is gone", "Math.min(page, pageCount - 1)" in page)
check("the numbers to press, and the ones between left out", "Math.abs(p - at) <= 1" in page and 'class="ms-page-gap"' in page and 'aria-current={p === at ? "page" : undefined}' in page)
check("a turn is heard, and comes in from that side", 'play("tick")' in page and 'data-sound="self"' in page and "--from: {turned * 14}px" in page)
check("the pages have the look the app's buttons have", read("webui/src/app.css").count(".ms-page,") >= 6 and ".ms-more" not in read("webui/src/app.css"))

print("\n== quickly ==")
check("the next page's pictures come ahead of it", "fitted.slice((at + 1) * PER_PAGE, (at + 2) * PER_PAGE)" in page and "new Image()" in page)
check("asked for five times a second while they come in, and stops as soon as none are left", "setTimeout(ask, 200)" in page and "if (left &&" in page)
check("not on a timer that slows to twenty seconds behind another window", "visiblePoll" not in page)
check("one the browser has already is simply there", "img.complete && img.naturalWidth" in page and "is-there" in page)
check("what was kept comes first, and the new one without the page moving", "if (r.stale && freshen < 4)" in page and "if (!freshen) {" in page)
hs = read("app/utils/hfsearch.py")
check("the graphics card is asked once, as the server starts", "def warm()" in hs and "hfsearch.warm()" in read("app/web/server.py") and "KEEP_MACHINE" not in hs)
check("no sleeping between pictures", "PICTURE_GAP" not in hs)

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
