"""The model search goes on past its first batch, and can be narrowed to a kind of model and a size (asked 2026-11-05:
"why's there only 3 pages ... make it so we can filter models and type of models").

It used to ask Hugging Face for one batch of 60, keep the ones that write, and with "Fits this computer" on that was
13: three pages, then nothing. Now each page that runs short fetches the batch after (Hugging Face's own cursor), and
the filters are asked of Hugging Face itself, so every batch is already of the kind asked for. Live, on the computer
this was written on: six batches gave 126 models that fit, at 0.2-0.4 s a batch. Nothing here leaves this computer."""
import asyncio
import os
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name
(Path(_tmp.name) / "config").mkdir(parents=True, exist_ok=True)
(Path(_tmp.name) / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"),
                                                       encoding="utf-8")

from app.utils import hfsearch, localai, localfix  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def item(repo, tag="text-generation", total=0):
    return {"id": repo, "author": repo.split("/")[0], "downloads": 10, "likes": 1, "lastModified": "2026-10-01T00:00:00Z",
            "pipeline_tag": tag, "gguf": {"total": total, "architecture": "qwen3"}}


asked = []
BATCHES = {"": [item("a/One-9B-GGUF"), item("a/Two-27B-GGUF"), item("a/Three-3B-GGUF")],
           "C2": [item("b/Four-7B-GGUF"), item("b/Five-12B-GGUF")],
           "C3": [item("c/Six-14B-GGUF")]}
NEXT = {"": "C2", "C2": "C3", "C3": ""}


def fake_get(url, timeout=20.0, accept="", tries=4):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    asked.append(q)
    after = NEXT.get(q.get("cursor", ""), "")
    # What Hugging Face's Link header carries, as _hf_request keeps it for the thread that asked.
    localfix._hf_local.next = f"https://huggingface.co/api/models?filter=gguf&cursor={after}" if after else ""
    return BATCHES.get(q.get("cursor", ""), [])


real_get = localfix._hf_get
localfix._hf_get = fake_get

print("== going on past the first batch ==")
r = hfsearch.search("", "popular")
check("the first batch, and where the one after it is", [x["repo"] for x in r["results"]][:3] == ["a/One-9B-GGUF", "a/Two-27B-GGUF", "a/Three-3B-GGUF"]
      and r["next"] == "C2", str(r.get("next")))
r2 = hfsearch.search("", "popular", cursor=r["next"])
check("the batch after, asked for by its cursor", asked[-1].get("cursor") == "C2" and [x["repo"] for x in r2["results"]] == ["b/Four-7B-GGUF", "b/Five-12B-GGUF"])
r3 = hfsearch.search("", "popular", cursor=r2["next"])
check("and the one after that, which is the last", r3["next"] == "" and len(r3["results"]) == 1)
kept = hfsearch._kept_list("downloads")
check("the first batch is kept on the disk with where the next is", kept and kept[2] == "C2")
check("a later batch is not kept over it", [x["repo"] for x in kept[1]][:1] == ["a/One-9B-GGUF"])
n = len(asked)
hfsearch.search("", "popular", cursor="C2")
check("a batch asked for again comes from what was kept", len(asked) == n)
check("a cursor with anything strange in it is cleaned", hfsearch.search("", "popular", cursor="C2;DROP")["results"] is not None
      and asked[-1].get("cursor") in ("C2DROP", "C2"))

print("\n== narrowed by Hugging Face itself ==")
hfsearch._searches.clear()
hfsearch.search("", "popular", kind="code", size="medium")
q = asked[-1]
check("a kind goes as Hugging Face's tag", q.get("filter") == "code" or "code" in [v for k, v in urllib.parse.parse_qsl(
    urllib.parse.urlencode(q)) if k == "filter"])
check("a size as its own parameter count", q.get("num_parameters") == "min:4B,max:14B")
hfsearch.search("", "popular", kind="sees")
check("seeing pictures is a kind of model, not a tag", asked[-1].get("pipeline_tag") == "image-text-to-text")
hfsearch.search("", "popular", size="huge")
check("over 40B has no top", asked[-1].get("num_parameters") == "min:40B")
hfsearch._searches.clear()
hfsearch._list_file("downloads").unlink(missing_ok=True)      # or the kept list would answer, asking nothing
hfsearch.search("", "popular", kind="nonsense", size="enormous")
check("anything it does not know is left out", "pipeline_tag" not in asked[-1] and "num_parameters" not in asked[-1])
r = hfsearch.search("qwen", "trending", kind="roleplay", size="small")
check("with what was typed and the order too", asked[-1].get("search") == "qwen" and asked[-1].get("sort") == "trendingScore")
check("the size its name says decides: 9B and 27B are not up to 4B", [x["repo"] for x in r["results"]] == ["a/Three-3B-GGUF"],
      str([x["repo"] for x in r["results"]]))
BATCHES[""] = [item("a/Mystery-GGUF"), item("a/One-9B-GGUF")]
hfsearch._searches.clear()
r = hfsearch.search("", "popular", size="medium")
check("one with no size at all is left out of a size", [x["repo"] for x in r["results"]] == ["a/One-9B-GGUF"])
hfsearch._list_file("downloads").unlink(missing_ok=True)
r = hfsearch.search("", "popular")
check("and kept with no size asked for", "a/Mystery-GGUF" in [x["repo"] for x in r["results"]])

print("\n== where the next batch is, from Hugging Face's answer ==")


class Answer:
    status = 200

    def __init__(self, link):
        self.link = link

    def read(self):
        return b"[]"

    def getheader(self, name, default=None):
        return {"link": self.link}.get(name.lower(), default)


class Conn:
    def __init__(self, link):
        self.link, self.sock, self.timeout = link, None, 0

    def request(self, *a, **k):
        pass

    def getresponse(self):
        return Answer(self.link)

    def close(self):
        pass


real_conn = localai.hf_connection
localfix._hf_drop()
localai.hf_connection = lambda host, timeout: Conn('<https://huggingface.co/api/models?filter=gguf&cursor=XYZ>; rel="next"')
localfix._hf_get = real_get
localfix.hf_next_reset()
localfix._hf_get("https://huggingface.co/api/models?filter=gguf")
check("its Link header read for the thread that asked", localfix.hf_next() == "https://huggingface.co/api/models?filter=gguf&cursor=XYZ")
check("and its cursor taken out of it", hfsearch._cursor(localfix.hf_next()) == "XYZ")
localfix._hf_drop()
localai.hf_connection = lambda host, timeout: Conn("")
localfix._hf_get("https://huggingface.co/api/models?filter=gguf")
check("no Link: the end", localfix.hf_next() == "" and hfsearch._cursor("") == "")
localfix._hf_drop()
localai.hf_connection = real_conn
localfix._hf_get = fake_get
check("a kept batch from before there were cursors still reads", hfsearch._after((1.0, [])) == "")

print("\n== the route ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web.routes import local_routes  # noqa: E402

got = {}
real_search = hfsearch.search
hfsearch.search = lambda *a: got.update(args=a) or {"ok": True, "results": [], "room": 0, "stale": False, "next": ""}
app = FastAPI()
app.include_router(local_routes.router)
TestClient(app).get("/api/local/hf/search", params={"q": "qwen", "sort": "new", "kind": "code", "size": "large", "cursor": "C9"},
                    headers={"x-llmselfbot": "1"})
check("the panel's filters and cursor reach the search", got.get("args") == ("qwen", "new", "code", "large", "C9"), str(got))
hfsearch.search = real_search

print("\n== the panel ==")
panel = (ROOT / "webui" / "src" / "lib" / "components" / "ModelSearch.svelte").read_text(encoding="utf-8")
api = (ROOT / "webui" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
check("asks with them", "new URLSearchParams({ q, sort, kind, size, cursor })" in api
      and "api.localHfSearch(query.trim(), sort, what, scale)" in panel)
check("filters that unroll under the order, each a row of choices", "{#if filtersOpen}" in panel and 'class="ms-filters"' in panel
      and all(w in panel for w in ("Sees pictures", "Coding", "Reasoning", "Roleplay", "Uncensored", "Up to 4B", "Over 40B")))
check("the button says how many are set", "{#if narrowed}<span class=\"ms-count\">{narrowed}</span>{/if}" in panel)
check("a change of filter is looked for at once, like a change of order", "const s = `${sort}|${what}|${scale}`;" in panel)
check("the pages fill up ahead of the reader", "const want = (at + 2) * PER_PAGE;" in panel and "untrack(() => loadMore())" in panel)
check("and stop asking after four batches with nothing that fits", "dry >= 4" in panel)
check("the arrow fetches on from the last page found so far", "onclick={onward}" in panel
      and "disabled={at === pageCount - 1 && (!cursor || more)}" in panel)
check("with a sign there is more", "{#if cursor}<span class=\"ms-page-gap\" aria-hidden=\"true\">…</span>{/if}" in panel)
check("nothing matching says so, with a way out", "Nothing on Hugging Face matches these filters." in panel and "Clear filters" in panel)
check("each choice makes its own sound", panel.count('data-sound="self"') >= 3 and 'play("select")' in panel)
local = (ROOT / "webui" / "src" / "lib" / "components" / "LocalAI.svelte").read_text(encoding="utf-8")
check("the line under it keeps its space: Svelte drops one at the start of an {#if}", "No models yet. Search for one above" in local
      and "No models yet.{#if" not in local)

localfix._hf_get = real_get
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
