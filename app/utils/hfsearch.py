"""Finding a model on Hugging Face, for the search under Settings, Models: what its own search gives, in the shape the
panel draws, with how each would do on this computer, its sizes when one is opened, and the picture of whoever made it.

Only what the app's servers can talk to is shown: a GGUF that writes, and perhaps sees. The voices, images, embeddings
and music that also come as GGUF would download fine and then answer nothing. Downloading is localai.start_pull, the
same as a name typed in.

Everything goes over IPv4 where it can (localai.hf_source): that is what makes the rest of this quick. A list is kept on
the disk, so the page has it at once, even the first time after a restart, with a new look behind it. Pictures come from
a few threads of their own, side by side, and are kept on the disk too: the page asks which are in and draws those. Each
picture a request of its own that waited its turn would hold one of the six connections a browser has to the panel, and
with a dozen on the go the rest of the app would stop answering.
"""
import glob
import http.client
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from app.utils import localai, localfix
from app.utils.paths import DATA_DIR

API = "https://huggingface.co/api/models"
SORTS = {"popular": "downloads", "trending": "trendingScore", "new": "createdAt"}
_FIELDS = ("author", "downloads", "likes", "lastModified", "gguf", "pipeline_tag", "gated")
# A list's worth, and more: the panel can narrow them to what fits, which on a small computer is about one in four.
LOOK_AT = 60
# What else the panel can ask for: what a model is (its tags on Hugging Face) and how big (Hugging Face's own count of
# its parameters), asked of Hugging Face itself so that each batch is already that and every page fills up.
KINDS = {"sees": ("pipeline_tag", "image-text-to-text"), "code": ("filter", "code"), "reasoning": ("filter", "reasoning"),
         "roleplay": ("filter", "roleplay"), "uncensored": ("filter", "uncensored")}
# (fewest weights, most, Hugging Face's own range). Its range lets in repos it has no count for, so the size each one's
# name says decides too.
SIZES = {"small": (0, 4e9, "min:0,max:4B"), "medium": (4e9, 14e9, "min:4B,max:14B"),
         "large": (14e9, 40e9, "min:14B,max:40B"), "huge": (40e9, 0, "min:40B")}
KEEP_SEARCH = 600.0
KEEP_PICTURE = 14 * 86400
MAX_PICTURE = 2 * 1024 * 1024

_WRITES = {"text-generation", "image-text-to-text", "any-to-any", "conversational", "text2text-generation"}
_SEES = {"image-text-to-text", "any-to-any"}
# With no word from the repo on what it does, its architecture says: these are the ones that write.
_TEXT_ARCH = re.compile(r"^(llama|qwen|gemma|phi|mistral|mixtral|deepseek|gpt|granite|command|cohere|falcon|olmo|"
                        r"exaone|hunyuan|lfm|minimax|smol|glm|chatglm|kimi|yi|baichuan|internlm|starcoder|stablelm|"
                        r"rwkv|mpt|jais|nemotron|ernie|solar|aya|laguna|orion|bloom)", re.I)
_GGUF_END = re.compile(r"[-_. ]?gguf$", re.I)
_AUTHOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
# Bytes a weight, roughly: what a model of so many weights comes to in the usual size, and in the smallest.
_Q4 = 0.63
_Q2 = 0.42
_PICTURE_HOSTS = ("huggingface.co", "cdn-avatars.huggingface.co", "aeiljuispo.cloudimg.io")
_PICTURE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}

_lock = threading.Lock()
_searches: dict = {}
_machine_was: tuple = (0.0, None)
# Lists being looked at behind what was just answered, so that no two go at once.
_looking: set = set()
PICTURE_TRIES = 5
PICTURE_WORKERS = 6
PICTURE_AGAIN = 0.4
GIVE_UP_FOR = 600.0
# Waiting to be fetched, being fetched just now, how many times each has failed and when it was given up on, and how many
# threads are fetching them.
_wanted: list = []
_fetching: set = set()
_failed: dict = {}
_given_up: dict = {}
_fetchers = 0
# Each of those threads' own connections, one to a host, kept open as long as there is more to fetch.
_own = threading.local()


def _machine() -> dict:
    """The memory this computer can give a model. Asking the graphics card takes over a second (nvidia-smi) and it does
    not change while the app runs, so it is asked once: the server does that as it starts (warm)."""
    global _machine_was
    at, held = _machine_was
    if held is None:
        held = {"ram": localfix._ram(), "vram": localfix._vram()}
        _machine_was = (time.time(), held)
    return held


def warm() -> None:
    """The one slow thing a first search would otherwise wait for, out of the way. Nothing goes over the network."""
    threading.Thread(target=_machine, daemon=True, name="hf-machine").start()


def _weights(name: str, gguf: dict) -> int:
    """How many weights it has: what its name says, over what its first file says. A repo's first file can be its
    vision part or a sliver of it (HF's own figure for one 27B repo here: 0.5B, from a "clip" file)."""
    said = localfix._billions(name)
    if said:
        return int(said * 1e9)
    if str(gguf.get("architecture") or "") == "clip":
        return 0
    try:
        return max(0, int(gguf.get("total") or 0))
    except (TypeError, ValueError):
        return 0


def fit_of(weights: int, mach: dict) -> str:
    """"fits" in the usual size, "tight" only in the smallest, "big" in none, "" when either is not known."""
    if not weights or not localfix.budget(mach):
        return ""
    if localfix.fits_memory(int(weights * _Q4), mach):
        return "fits"
    return "tight" if localfix.fits_memory(int(weights * _Q2), mach) else "big"


def _when(text) -> float:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def row_of(item: dict) -> dict | None:
    """One result as the panel draws it, or None for what cannot be used: gated, or not something that writes."""
    repo = str(item.get("id") or "")
    if repo.count("/") != 1 or item.get("gated") or item.get("private") or item.get("disabled"):
        return None
    tag = str(item.get("pipeline_tag") or "")
    gguf = item.get("gguf") if isinstance(item.get("gguf"), dict) else {}
    if tag not in _WRITES and (tag or not _TEXT_ARCH.match(str(gguf.get("architecture") or ""))):
        return None
    author, name = repo.split("/")
    if not _AUTHOR.match(author):
        return None
    return {"repo": repo, "name": _GGUF_END.sub("", name) or name, "author": author,
            "downloads": int(item.get("downloads") or 0), "likes": int(item.get("likes") or 0),
            "updated": _when(item.get("lastModified")), "weights": _weights(name, gguf), "sees": tag in _SEES}


def _list_file(order: str) -> Path:
    folder = DATA_DIR / "cache" / "hf_lists"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{order}.json"


def _kept_list(order: str) -> tuple | None:
    """What was popular (or trending, or new) when it was last asked: (when, the rows, where the next batch is), or None."""
    try:
        data = json.loads(_list_file(order).read_text(encoding="utf-8"))
        return (float(data["at"]), [r for r in data["rows"] if isinstance(r, dict) and r.get("repo")],
                str(data.get("next") or ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _keep_list(order: str, at: float, rows: list, after: str = "") -> None:
    target = _list_file(order)
    part = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        part.write_text(json.dumps({"at": at, "rows": rows, "next": after}), encoding="utf-8")
        os.replace(part, target)
    except OSError:
        part.unlink(missing_ok=True)        # only a head start for next time


def _cursor(link: str) -> str:
    """The cursor in Hugging Face's link to its next batch, "" when there is none."""
    return (urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("cursor") or [""])[0] if link else ""


def _after(held: tuple) -> str:
    """Where the batch after a kept one is: kept ones from before this was kept have no word on it."""
    return held[2] if len(held) > 2 else ""


def _look(text: str, order: str, kind: str = "", size: str = "", cursor: str = "") -> tuple:
    """Hugging Face asked, and what it said kept: (the rows, the cursor of the batch after it). Raises when it cannot
    be asked."""
    ask = [("filter", "gguf"), ("sort", order), ("direction", "-1"), ("limit", str(LOOK_AT))]
    if kind in KINDS:
        ask.append(KINDS[kind])
    if size in SIZES:
        ask.append(("num_parameters", SIZES[size][2]))
    ask += [("expand[]", f) for f in _FIELDS]
    if text:
        ask.append(("search", text))
    if cursor:
        ask.append(("cursor", cursor))
    localfix.hf_next_reset()
    found = localfix._hf_get(f"{API}?{urllib.parse.urlencode(ask)}", timeout=15.0, tries=6)
    after = _cursor(localfix.hf_next())
    rows = [r for r in (row_of(i) for i in found if isinstance(i, dict)) if r]
    if size in SIZES:
        low, high, _ = SIZES[size]
        rows = [r for r in rows if r["weights"] and r["weights"] >= low and (not high or r["weights"] <= high)]
    at = time.time()
    with _lock:
        if len(_searches) >= 64:
            _searches.pop(min(_searches, key=lambda k: _searches[k][0]))
        _searches[(text.lower(), order, kind, size, cursor)] = (at, rows, after)
    if not (text or kind or size or cursor):
        _keep_list(order, at, rows, after)
    return rows, after


def _look_behind(orders: list) -> None:
    """New looks at these lists behind what was just answered, with the pictures of what would be shown from them: the
    other orders are one press away, and so have what they need before it."""
    def look() -> None:
        try:
            for order in orders:
                try:
                    rows, _ = _look("", order)
                except Exception:
                    continue                # only a head start
                mach = _machine()
                pictures([r["author"] for r in rows if fit_of(r["weights"], mach) != "big"][:12], later=True)
        finally:
            with _lock:
                _looking.difference_update(orders)
    with _lock:
        orders = [o for o in orders if o not in _looking]
        _looking.update(orders)
    if orders:
        threading.Thread(target=look, daemon=True, name="hf-lists").start()


def search(query: str = "", sort: str = "popular", kind: str = "", size: str = "", cursor: str = "") -> dict:
    """What Hugging Face has for that, most downloaded first unless asked otherwise. Nothing typed: what is popular.
    `kind` and `size` narrow it (KINDS, SIZES); `cursor` is the batch after one already shown.
    {"ok", "results": [...], "room", "stale", "next"}, or {"ok": False, "reason"}. Stale: what was found last time, with a
    new look behind it, so the page has something at once and asks again in a moment. Next: the cursor of the batch
    after this one, "" at the end."""
    text = re.sub(r"\s+", " ", str(query or "")).strip()[:80]
    # A link or a repo's whole name is searched for as that name.
    repo, _ = localai._hf_name(text)
    text = repo or text
    order = SORTS.get(sort, SORTS["popular"])
    kind = kind if kind in KINDS else ""
    size = size if size in SIZES else ""
    cursor = re.sub(r"[^\w=+/-]", "", str(cursor or ""))[:2000]
    plain = not (text or kind or size or cursor)
    key = (text.lower(), order, kind, size, cursor)
    with _lock:
        held = _searches.get(key)
    if held is None and plain:
        held = _kept_list(order)
        if held:
            with _lock:
                held = _searches.setdefault(key, held)
    stale = False
    if held and time.time() - held[0] < KEEP_SEARCH:
        rows, after = held[1], _after(held)
    elif held and plain:
        rows, after, stale = held[1], _after(held), True
    else:
        try:
            rows, after = _look(text, order, kind, size, cursor)
        except Exception:
            if not held:
                return {"ok": False, "reason": "Hugging Face did not answer. Try again."}
            rows, after = held[1], _after(held)   # kept from before: better than nothing while it will not answer
    if plain:
        def old(o: str) -> bool:
            with _lock:
                was = _searches.get(("", o, "", "", ""))
            was = was or _kept_list(o)
            return not was or time.time() - was[0] >= KEEP_SEARCH
        behind = [o for o in SORTS.values() if (o == order and stale) or (o != order and old(o))]
        if behind:
            _look_behind(behind)
    mach = _machine()
    return {"ok": True, "results": [{**r, "fit": fit_of(r["weights"], mach)} for r in rows],
            "room": localfix.budget(mach), "stale": stale, "next": after}


def sizes(repo: str, kind: str = "file") -> dict:
    """The sizes a repo comes in, smallest first, each with whether it fits and whether it is here already, and the one
    that would be picked. {"ok", "repo", "sizes": [{"tag", "size", "fits", "best", "have"}], "sees", "why"}."""
    repo, _ = localai._hf_name(repo)
    if not repo:
        return {"ok": False, "reason": "That is not a Hugging Face repo."}
    try:
        files = localfix.repo_files(repo)
    except urllib.error.HTTPError as e:
        return {"ok": False, "reason": localai._net_reason(e)}
    except Exception:
        return {"ok": False, "reason": "Hugging Face did not answer. Try again."}
    folder = localai.app_models_dir()
    vision = localfix.mmproj_file(files)
    extra = int(vision["size"]) if vision else 0
    try:
        free = shutil.disk_usage(folder).free if kind == "file" else localfix.machine()["free"]
    except OSError:
        free = 0
    picks, why = localfix.choices(files, {**_machine(), "free": free - extra})
    good = {f["tag"] for f in picks}
    best = picks[0]["tag"] if picks else ""
    rows, seen = [], set()
    for f in sorted(localfix.model_files(files), key=lambda f: f["size"]):
        if f["tag"] in seen:
            continue
        seen.add(f["tag"])
        base = os.path.basename(f["name"])
        stem = os.path.splitext(base)[0]
        rows.append({"tag": f["tag"], "size": int(f["size"]), "fits": f["tag"] in good, "best": f["tag"] == best,
                     "have": kind == "file" and ((folder / base).is_file() or (folder / stem / base).is_file())})
    return {"ok": True, "repo": repo, "sizes": rows, "sees": bool(vision), "why": "" if picks else why}


def _ask(host: str, path: str, accept: str) -> tuple:
    """(status, its type, where it redirects to, the body) over this thread's connection to that host. One it had closed
    in the meantime is no failure: asked again at once, on a new one."""
    conns = _own.__dict__.setdefault("conns", {})
    while True:
        conn = conns.get(host)
        kept = conn is not None
        try:
            if conn is None:
                conn = conns[host] = localai.hf_connection(host, 12.0)
            conn.request("GET", path, headers={"user-agent": "LLMSelfbot", "accept": accept})
            r = conn.getresponse()
            kind = (r.getheader("content-type") or "").split(";")[0].strip().lower()
            body = r.read(MAX_PICTURE + 1)
            if not r.isclosed():
                # Something left unread on it: not one to ask anything more over.
                conns.pop(host, None)
                conn.close()
            return r.status, kind, r.getheader("location") or "", body
        except (http.client.HTTPException, OSError):
            conns.pop(host, None)
            if conn is not None:
                conn.close()
            if not kept:
                localai.hf_failed()
                raise


def _picture_url(author: str) -> str | None:
    """Where the maker's picture is: "" when they have none, None when Hugging Face could not be asked. Only "there is
    no such one" moves on to the other kind: a busy server, or one asked too often, says nothing about the maker, and
    taking it to mean no picture would keep the letter for two weeks."""
    for kind in ("organizations", "users"):
        path = f"/api/{kind}/{author}/avatar"
        try:
            for _ in range(3):
                status, _type, location, body = _ask("huggingface.co", path, "application/json")
                if status not in (301, 302, 307, 308) or not location.startswith(("/", "https://huggingface.co/")):
                    break
                path = location.removeprefix("https://huggingface.co")
        except (http.client.HTTPException, OSError):
            return None
        if status in (401, 404):
            continue
        if status != 200:
            return None
        try:
            said = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            return None
        url = str(said.get("avatarUrl") or "") if isinstance(said, dict) else ""
        if url:
            return "https://huggingface.co" + url if url.startswith("/") else url
    return ""


def _fetch_picture(url: str) -> tuple:
    """(bytes, the file ending for its type), or (b"", "") for anything but a picture of a sensible size from Hugging
    Face. No SVG: it can carry a script, and this is served from the panel's own address."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or parts.hostname not in _PICTURE_HOSTS:
        return b"", ""
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    status, kind, _where, data = _ask(parts.hostname, path, "image/*")
    ending = _PICTURE_TYPES.get(kind, "")
    if status != 200 or not ending or len(data) > MAX_PICTURE:
        return b"", ""
    return data, ending


def _pictures_folder() -> Path:
    folder = DATA_DIR / "cache" / "hf_pictures"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _kept(author: str) -> tuple:
    """(what is on the disk, is it recent): the file, False for someone written down as having no picture, or None.
    A file with a letter in front: "CON" and "NUL" are makers' names too, and Windows will not have them as files."""
    for f in _pictures_folder().glob(glob.escape(f"a_{author}") + ".*"):
        if f.suffix == ".part":
            continue
        recent = time.time() - f.stat().st_mtime < KEEP_PICTURE
        return (False if f.suffix == ".none" else f), recent
    return None, False


def _fetch_one(author: str) -> bool:
    """Fetched and kept, or written down as having none. False when the connection dropped: it can be tried again."""
    url = _picture_url(author)
    if url is None:
        return False
    data, ending = b"", ""
    if url:
        try:
            data, ending = _fetch_picture(url)
        except Exception:
            return False
    old, _ = _kept(author)
    target = _pictures_folder() / (f"a_{author}" + (ending if data else ".none"))
    part = target.with_name(target.name + f".{os.getpid()}.part")
    part.write_bytes(data)
    os.replace(part, target)
    if isinstance(old, Path) and old != target:
        old.unlink(missing_ok=True)
    return True


def _fetch_wanted() -> None:
    """Until none are left. Each that failed goes to the back of the line, a few times."""
    global _fetchers
    try:
        while True:
            with _lock:
                if not _wanted:
                    _fetchers -= 1
                    return
                author = _wanted.pop(0)
                _fetching.add(author)
            try:
                done = _fetch_one(author)
            except Exception:
                done = False
            with _lock:
                _fetching.discard(author)
                if not done:
                    _failed[author] = _failed.get(author, 0) + 1
                    if _failed[author] < PICTURE_TRIES:
                        _wanted.append(author)
                    else:
                        _given_up[author] = time.time()
            if not done:
                time.sleep(PICTURE_AGAIN)
    finally:
        for conn in _own.__dict__.pop("conns", {}).values():
            conn.close()


def _on_disk() -> dict:
    """Every maker kept on the disk, with one look at the folder however many are asked about: the page asks several
    times a second while pictures come in. {author: (is it a picture, is it recent)}."""
    out, now = {}, time.time()
    with os.scandir(_pictures_folder()) as found:
        for f in found:
            stem, _dot, ending = f.name.rpartition(".")
            if ending != "part" and stem.startswith("a_"):
                out[stem[2:]] = (ending != "none", now - f.stat().st_mtime < KEEP_PICTURE)
    return out


def pictures(authors, later: bool = False) -> dict:
    """Which of these makers' pictures are in: {"ready": [...], "waiting": n}, the rest fetched behind this. What a page
    is waiting for goes ahead of what is only being fetched in case (later)."""
    global _fetchers
    ready, waiting = [], 0
    kept = _on_disk()
    now = time.time()
    with _lock:
        for author in {str(a) for a in authors if _AUTHOR.match(str(a or ""))}:
            is_picture, recent = kept.get(author, (False, False))
            if is_picture:
                ready.append(author)
            if recent:
                continue
            if _failed.get(author, 0) >= PICTURE_TRIES:
                if now - _given_up.get(author, 0) < GIVE_UP_FOR:
                    continue                # not for now
                _failed.pop(author, None)
            waiting += author not in kept
            if author in _fetching:
                continue
            if not later:
                if author in _wanted:
                    _wanted.remove(author)
                _wanted.insert(0, author)
            elif author not in _wanted:
                _wanted.append(author)
        start = max(0, min(PICTURE_WORKERS - _fetchers, len(_wanted)))
        _fetchers += start
    for _ in range(start):
        threading.Thread(target=_fetch_wanted, daemon=True, name="hf-pictures").start()
    return {"ready": sorted(ready), "waiting": waiting}


def picture(author: str) -> Path | None:
    """The file of whoever made it, if it is in. Never fetched here: see pictures()."""
    if not _AUTHOR.match(str(author or "")):
        return None
    kept, _ = _kept(author)
    return kept if isinstance(kept, Path) else None
