"""
A search, the way bot.web.search_with says:

- auto: Google in its own browser (browser.py), then DuckDuckGo. Brave and Tavily after those when they have a key.
- google, duckduckgo, brave, tavily: that one first, the others after it when it cannot answer.

Google is asked like a person asks it, in a real Chrome. When it answers with a captcha ("unusual traffic") it is
left alone for an hour and DuckDuckGo answers instead. DuckDuckGo's HTML page needs no key and no browser, so a
search works on any install. Brave and Tavily are search APIs: BRAVE_API_KEY, TAVILY_API_KEY in config/.env, free
tiers with a sign up, never blocked.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from app.utils.web import page

ENGINE_NAMES = {"google": "Google", "duckduckgo": "DuckDuckGo", "brave": "Brave", "tavily": "Tavily"}
TIMEOUT = 12.0
# Google, after a captcha: left alone this long, twice as long for each captcha in a row, a day at most. A browser it
# has decided is a robot gets nothing but captchas for a while, and each try costs a lookup seconds.
GOOGLE_REST = 3600.0
GOOGLE_REST_MAX = 86400.0
_google_rested_until = 0.0
_google_strikes = 0


@dataclass
class Result:
    title: str
    url: str
    snippet: str = ""


class Unavailable(Exception):
    """This engine cannot answer now (no key, no browser, blocked, offline)."""


class Captcha(Unavailable):
    """The engine asked to prove it is a person."""


def _key(name: str) -> str:
    try:
        from app.utils.credentials import real
        return real(name)
    except Exception:
        return ""


def _rest_file():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "web" / "google.json"


def _load_rest() -> None:
    """Google's rest as every account sees it: each runs in a process of its own, and one captcha is enough for all
    of them to know."""
    global _google_rested_until, _google_strikes
    try:
        import json
        data = json.loads(_rest_file().read_text(encoding="utf-8"))
        _google_rested_until = float(data.get("until") or 0)
        _google_strikes = int(data.get("strikes") or 0)
    except (OSError, ValueError, TypeError):
        pass


def _save_rest() -> None:
    try:
        from app.utils.atomic import write_json_atomic
        _rest_file().parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(_rest_file(), {"until": _google_rested_until, "strikes": _google_strikes})
    except Exception:
        pass


def rest_google() -> float:
    """Google left alone after a captcha; how long for, in seconds."""
    global _google_rested_until, _google_strikes
    _load_rest()
    seconds = min(GOOGLE_REST_MAX, GOOGLE_REST * (2 ** _google_strikes))
    _google_strikes += 1
    _google_rested_until = time.time() + seconds
    _save_rest()
    return seconds


def google_answered() -> None:
    global _google_strikes, _google_rested_until
    if _google_strikes:
        _google_strikes, _google_rested_until = 0, 0.0
        _save_rest()


def google_resting() -> bool:
    _load_rest()
    return time.time() < _google_rested_until


def order(choice: str, has_browser: bool) -> list:
    """The engines to ask, in turn, for this choice: each one that can answer at all."""
    auto = ["google", "duckduckgo", "brave", "tavily"]
    names = auto if choice not in auto else [choice] + [e for e in auto if e != choice]
    out = []
    for name in names:
        if name == "google" and (not has_browser or google_resting()):
            continue
        if name == "brave" and not _key("BRAVE_API_KEY"):
            continue
        if name == "tavily" and not _key("TAVILY_API_KEY"):
            continue
        out.append(name)
    return out


# ── DuckDuckGo ───────────────────────────────────────────────────────────────

class _DuckReader(HTMLParser):
    """The results of html.duckduckgo.com: each one's link (result__a) and its line (result__snippet). Ads left out."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list = []
        self.cur: dict | None = None
        self.field = ""
        self.depth = 0
        self.ad = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        cls = a.get("class", "")
        if tag == "div" and "result" in cls.split() or "result--ad" in cls:
            self.ad = "result--ad" in cls
        if tag == "a" and "result__a" in cls:
            if self.cur and self.cur.get("url"):
                self.results.append(self.cur)
            self.cur = {"title": "", "url": _ddg_target(a.get("href", "")), "snippet": "", "ad": self.ad}
            self.field = "title"
        elif "result__snippet" in cls and self.cur is not None:
            self.field = "snippet"
            self.depth = 1
            return
        if self.field == "snippet":
            self.depth += 1

    def handle_endtag(self, tag):
        if self.field == "title" and tag == "a":
            self.field = ""
        elif self.field == "snippet":
            self.depth -= 1
            if self.depth <= 0:
                self.field = ""

    def handle_data(self, data):
        if self.cur is not None and self.field in ("title", "snippet"):
            self.cur[self.field] += data

    def close(self):
        super().close()
        if self.cur and self.cur.get("url"):
            self.results.append(self.cur)


def _ddg_target(href: str) -> str:
    """Where one of DuckDuckGo's own redirect links goes."""
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    if parts.hostname and parts.hostname.endswith("duckduckgo.com"):
        if parts.path.startswith("/y.js"):
            return ""                          # an ad
        target = parse_qs(parts.query).get("uddg", [""])[0]
        return target
    return href


def parse_duckduckgo(html: str) -> list:
    r = _DuckReader()
    try:
        r.feed(html)
        r.close()
    except Exception:
        pass
    out, seen = [], set()
    for item in r.results:
        url = item["url"]
        if item.get("ad") or not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(Result(title=" ".join(item["title"].split())[:160], url=url,
                          snippet=" ".join(item["snippet"].split())[:300]))
    return out


async def duckduckgo(q: str, n: int) -> list:
    import httpx
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={**page.HEADERS, "referer": "https://html.duckduckgo.com/"},
                                 follow_redirects=True) as c:
        r = await c.post("https://html.duckduckgo.com/html/", data={"q": q})
    if r.status_code >= 400:
        raise Unavailable(f"DuckDuckGo answered {r.status_code}")
    results = parse_duckduckgo(r.text)
    if not results and ("anomaly" in r.text.lower() or "bots use duckduckgo" in r.text.lower()):
        raise Captcha("DuckDuckGo asked if it is a bot")
    return results[:n]


# ── Brave and Tavily ─────────────────────────────────────────────────────────

async def brave(q: str, n: int) -> list:
    import httpx
    key = _key("BRAVE_API_KEY")
    if not key:
        raise Unavailable("no Brave key")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get("https://api.search.brave.com/res/v1/web/search", params={"q": q, "count": n},
                        headers={"accept": "application/json", "x-subscription-token": key})
    if r.status_code >= 400:
        raise Unavailable(f"Brave answered {r.status_code}")
    items = ((r.json() or {}).get("web") or {}).get("results") or []
    return [Result(title=str(i.get("title") or "")[:160], url=str(i.get("url") or ""),
                   snippet=" ".join(str(i.get("description") or "").split())[:300]) for i in items if i.get("url")][:n]


async def tavily(q: str, n: int) -> list:
    import httpx
    key = _key("TAVILY_API_KEY")
    if not key:
        raise Unavailable("no Tavily key")
    async with httpx.AsyncClient(timeout=TIMEOUT + 8) as c:
        r = await c.post("https://api.tavily.com/search", headers={"authorization": f"Bearer {key}"},
                         json={"query": q, "max_results": n, "search_depth": "basic"})
    if r.status_code >= 400:
        raise Unavailable(f"Tavily answered {r.status_code}")
    items = (r.json() or {}).get("results") or []
    return [Result(title=str(i.get("title") or "")[:160], url=str(i.get("url") or ""),
                   snippet=" ".join(str(i.get("content") or "").split())[:300]) for i in items if i.get("url")][:n]


# ── All of them ──────────────────────────────────────────────────────────────

async def search(q: str, n: int = 6, browser=None, choice: str | None = None) -> tuple:
    """(results, the engine that found them): ([], "") when none of them could. `browser` is an open browser.Session,
    for Google; without one Google is skipped. Never raises."""
    if choice is None:
        from app.utils.web import settings
        choice = settings()["search_with"]
    has_browser = browser is not None and getattr(browser, "can_google", False)
    for name in order(choice, has_browser):
        try:
            if name == "google":
                results = await browser.google(q, n)
            elif name == "duckduckgo":
                results = await duckduckgo(q, n)
            elif name == "brave":
                results = await brave(q, n)
            else:
                results = await tavily(q, n)
        except Captcha:
            if name == "google":
                hours = rest_google() / 3600
                try:
                    from app.utils.logger import log_system
                    log_system("Google asked if it is a robot: searching elsewhere for the next "
                               + (f"{hours:.0f} hours" if hours >= 2 else "hour"))
                except Exception:
                    pass
            continue
        except Exception:
            continue
        if results:
            if name == "google":
                google_answered()
            return results, name
    return [], ""
