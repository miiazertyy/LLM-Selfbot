"""
A web page read and boiled down to what a person takes from it: its title, its site, its words and its links.

Read plainly with httpx: no browser, no JavaScript, at most MAX_BYTES of it. Every hop of a redirect goes through the
guard (guard.py) before it is followed, so a link cannot bounce the bot into the home network. The words come out
with the standard library's HTMLParser, nothing to install: scripts, styles, menus, footers and forms are left out,
and an <article> or <main> is preferred when it holds enough to read. A page that needs JavaScript to show anything
comes back with almost no words; the browser (browser.py) reads those.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.utils.web import guard

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
HEADERS = {"user-agent": UA, "accept-language": "en-US,en;q=0.9",
           "accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5"}
MAX_BYTES = 3_000_000
MAX_TEXT = 8000
MAX_LINKS = 80
TIMEOUT = 15.0
# Less than this many characters of words reads as a page that needs its JavaScript to show anything.
THIN = 200

_SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas", "object", "embed",
         "nav", "footer", "header", "aside", "form", "button", "select", "option", "dialog", "menu"}
# Left out even when a page is read loosely (see extract): never words anyone reads.
_NEVER = {"script", "style", "noscript", "svg", "template"}
_BLOCK = {"p", "div", "section", "article", "main", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br",
          "tr", "table", "blockquote", "pre", "figcaption", "dd", "dt", "hr", "summary", "details", "caption"}
_VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr", "area", "base", "col", "embed", "param",
         "track"}


@dataclass
class Page:
    url: str
    title: str = ""
    site: str = ""
    description: str = ""
    text: str = ""
    links: list = field(default_factory=list)    # [{"text": ..., "url": ...}], in page order
    error: str = ""
    # Refused by the guard (guard.py): somewhere private. Nothing tries it another way.
    blocked: bool = False

    @property
    def ok(self) -> bool:
        return not self.error


def site_of(url: str) -> str:
    """example.com for https://www.example.com/a/b."""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


class _Reader(HTMLParser):
    def __init__(self, base: str, skip: set):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.skip_tags = skip
        self.skipping = 0
        self.in_title = False
        self.title = ""
        self.meta: dict = {}
        self.lines: list = []          # the whole page's words
        self.main_lines: list = []     # inside <article>/<main>
        self.main_depth = 0
        self.link: dict | None = None
        self.links: list = []
        # Every link's words, however many and with an address or not: a site's menus, to leave out of its text.
        self.link_texts: set = set()
        self._buf: list = []

    def _flush(self):
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if text:
            self.lines.append(text)
            if self.main_depth:
                self.main_lines.append(text)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:title", "og:description", "description", "og:site_name", "twitter:title"):
                self.meta.setdefault(key, a.get("content", "").strip())
            return
        if tag in _VOID and tag not in ("br", "hr"):
            return
        if tag in self.skip_tags:
            self.skipping += 1
            return
        if tag == "title":
            # The page's own, once: an icon's <title> inside an <svg> is not it.
            self.in_title = not self.skipping and not self.title.strip()
            return
        if self.skipping:
            return
        if tag in ("article", "main"):
            self._flush()
            self.main_depth += 1
        if tag in _BLOCK:
            self._flush()
        if tag == "a":
            self.link = {"href": a.get("href", ""), "text": [], "label": a.get("aria-label") or a.get("title") or ""}

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            if self.skipping:
                self.skipping -= 1
            return
        if tag == "title":
            self.in_title = False
            return
        if self.skipping:
            return
        if tag == "a" and self.link is not None:
            self._add_link(self.link)
            self.link = None
        if tag in _BLOCK:
            self._flush()
        if tag in ("article", "main") and self.main_depth:
            self._flush()
            self.main_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.skipping:
            return
        self._buf.append(data)
        if self.link is not None:
            self.link["text"].append(data)

    def _add_link(self, link):
        words = " ".join("".join(link["text"]).split())
        if words:
            self.link_texts.add(words)
        href = link["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return
        url = urljoin(self.base, href)
        if not url.startswith(("http://", "https://")):
            return
        text = " ".join("".join(link["text"]).split()) or link["label"].strip()
        if not text or len(self.links) >= MAX_LINKS * 2:
            return
        self.links.append({"text": text[:90], "url": url.split("#")[0]})

    def close(self):
        super().close()
        self._flush()


def _tidy(lines: list, menu: frozenset = frozenset()) -> str:
    """The lines worth reading: no repeats, and none that is only a short link's own words. Those are a site's
    menus, which many sites build without a <nav>, and they buried the article under its menu on every page."""
    from collections import Counter
    # A short line said over and over ("Back", "Read more") is the page's furniture, not something to read.
    repeated = {line for line, n in Counter(lines).items() if n >= 3 and len(line) < 25}
    out, last = [], ""
    for line in lines:
        if len(line) < 2 or line == last or (len(line) < 60 and line in menu) or line in repeated:
            continue
        out.append(line)
        last = line
    return "\n".join(out)


def extract(html: str, url: str) -> Page:
    """What a person reads on this page, from its HTML."""
    def read(skip):
        r = _Reader(url, skip)
        try:
            r.feed(html)
            r.close()
        except Exception:
            pass
        return r

    r = read(_SKIP)
    menu = frozenset(r.link_texts)
    main = _tidy(r.main_lines, menu)
    text = main if len(main) >= 400 else _tidy(r.lines, menu)
    if len(text) < THIN and len(html) > 20_000:
        # An unclosed <nav> or <form> can swallow the rest of a page: read it again, leaving out only what is never
        # words at all.
        loose = read(_NEVER)
        loose_text = _tidy(loose.lines, frozenset(loose.link_texts))
        if len(loose_text) > len(text):
            r, text = loose, loose_text
    links, seen = [], set()
    for link in r.links:
        if link["url"] in seen or link["url"].rstrip("/") == url.rstrip("/"):
            continue
        seen.add(link["url"])
        links.append(link)
        if len(links) >= MAX_LINKS:
            break
    meta = r.meta
    return Page(
        url=url,
        title=" ".join((meta.get("og:title") or r.title or meta.get("twitter:title") or "").split())[:200],
        site=meta.get("og:site_name") or site_of(url),
        description=" ".join((meta.get("og:description") or meta.get("description") or "").split())[:400],
        text=text[:MAX_TEXT],
        links=links,
    )


def _decode(body: bytes, declared: str | None) -> str:
    charset = declared
    if not charset:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4000], re.I)
        charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# A user agent that says what it is: a site that refuses a browser's from something that is not one (Wikipedia
# does) gets this on the second try.
HONEST_UA = "LLMSelfbot/1.0 (a personal chat assistant reading one page someone shared)"
_RETRY = ("could not be read", "the site answered 403", "the site answered 429")


def _charset(content_type: str) -> str | None:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    return m.group(1) if m else None


def _session(v4: bool):
    """A requests session. With v4, its connections go out over IPv4 only: on this kind of home connection IPv6
    often connects and then stalls in the TLS handshake (formula1.com did, every time), and an IPv4 address is bound
    as the source, so an IPv6 address simply fails and the next one is tried."""
    import requests
    from requests.adapters import HTTPAdapter

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            if v4:
                kwargs["source_address"] = ("0.0.0.0", 0)
            return super().init_poolmanager(*args, **kwargs)

    session = requests.Session()
    session.mount("http://", _Adapter())
    session.mount("https://", _Adapter())
    return session


def _fetch_once(url: str, headers: dict, limit: int, v4: bool) -> Page:
    """One go at it, on a worker thread. httpx is not used here: Wikipedia refuses its connections whatever they
    say, and answers requests'."""
    try:
        with _session(v4) as session:
            for _ in range(6):
                r = session.get(url, headers=headers, timeout=(8, TIMEOUT), stream=True, allow_redirects=False)
                try:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        try:
                            url = guard.check_sync(urljoin(url, r.headers["location"]))
                        except guard.Blocked as e:
                            return Page(url=url, error=f"it redirects to {e}", blocked=True)
                        continue
                    if r.status_code >= 400:
                        return Page(url=url, error=f"the site answered {r.status_code}")
                    ctype = (r.headers.get("content-type") or "").lower()
                    readable = any(t in ctype for t in ("text/html", "xhtml", "text/plain", "json", "xml"))
                    if ctype and not readable:
                        return Page(url=url, site=site_of(url), error=f"not a page ({ctype.split(';')[0]})")
                    body = bytearray()
                    for chunk in r.iter_content(65536):
                        body += chunk
                        if len(body) >= limit:
                            break
                finally:
                    r.close()
                text = _decode(bytes(body), _charset(ctype))
                if "html" in ctype or (not ctype and "<html" in text[:1000].lower()):
                    return extract(text, url)
                return Page(url=url, site=site_of(url), title=site_of(url), text=" ".join(text.split())[:MAX_TEXT])
            return Page(url=url, error="too many redirects")
    except Exception as e:
        return Page(url=url, error=f"could not be read ({type(e).__name__})")


async def fetch(url: str, limit: int = MAX_BYTES) -> Page:
    """The page at `url`, read plainly. Never raises: what went wrong is in Page.error.

    Over IPv4 first, then any way at all when that cannot connect; and once more with a user agent that says what
    it is when a site refuses one that looks like a browser."""
    import asyncio
    try:
        url = await guard.check(url)
    except guard.Blocked as e:
        return Page(url=str(url or ""), error=str(e), blocked=True)
    page = Page(url=url)
    for headers, v4 in ((HEADERS, True), (HEADERS, False), ({**HEADERS, "user-agent": HONEST_UA}, True)):
        if page.error and not page.error.startswith(_RETRY):
            break
        if page.error.startswith("the site answered") and headers is HEADERS:
            continue                              # refused, not dropped: only another user agent can help
        page = await asyncio.to_thread(_fetch_once, url, headers, limit, v4)
        if page.ok:
            break
    return page
