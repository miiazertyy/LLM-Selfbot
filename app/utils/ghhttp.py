"""ghhttp.py - every request the app makes to GitHub for community profiles, in one place.

Only GitHub's own hosts are ever reached (the API, github.com for the sign-in, the release downloads, gists and the
community's Pages site); a redirect anywhere else is refused. Answers are read up to a size, and a failure comes back
as a sentence a person can act on. Synchronous: the routes call it on a worker thread. Tests replace `send`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

TIMEOUT = 20.0
_HOSTS = re.compile(r"^(?:api\.github\.com|github\.com|uploads\.github\.com|gist\.github\.com|codeload\.github\.com|"
                    r"[a-z0-9-]+\.githubusercontent\.com|[a-z0-9-]+\.github\.io)$")


class GitHubError(Exception):
    """A plain reason, for the person: "Couldn't reach GitHub.", "Sign in again.", and so on."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass
class Reply:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8") or "null")
        except ValueError:
            return None


def allowed(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and bool(_HOSTS.match(u.hostname or ""))


def _agent() -> str:
    try:
        from app.version import __version__
        return f"LLMSelfbot/{__version__}"
    except Exception:
        return "LLMSelfbot"


def send(method: str, url: str, *, headers: dict | None = None, body: bytes | None = None, cap: int = 4_000_000,
         timeout: float = TIMEOUT, progress=None) -> Reply:
    """One request, its redirects followed only within GitHub, the answer read up to `cap` bytes."""
    import httpx
    if not allowed(url):
        raise GitHubError("That isn't a GitHub address.")
    hdrs = {"User-Agent": _agent(), **(headers or {})}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for _hop in range(6):
                with client.stream(method, url, headers=hdrs, content=body) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        nxt = str(httpx.URL(url).join(r.headers["location"]))
                        if not allowed(nxt):
                            raise GitHubError("GitHub sent the download somewhere else.")
                        url = nxt
                        if r.status_code == 303:
                            method, body = "GET", None
                        # A download's next stop needs no GitHub token, and must not be handed one.
                        hdrs = {k: v for k, v in hdrs.items() if k.lower() != "authorization"}
                        continue
                    total = int(r.headers.get("content-length") or 0)
                    chunks, got = [], 0
                    for chunk in r.iter_bytes(65536):
                        got += len(chunk)
                        if got > cap:
                            raise GitHubError("GitHub's answer was bigger than expected.")
                        chunks.append(chunk)
                        if progress and total:
                            progress(got, total)
                    return Reply(r.status_code, dict(r.headers), b"".join(chunks))
        raise GitHubError("GitHub kept redirecting.")
    except GitHubError:
        raise
    except httpx.TimeoutException:
        raise GitHubError("GitHub took too long to answer.") from None
    except httpx.HTTPError:
        raise GitHubError("Couldn't reach GitHub.") from None


def api(method: str, path: str, *, token: str = "", json_body=None, params: dict | None = None,
        cap: int = 4_000_000, timeout: float = TIMEOUT):
    """The REST API: (status, parsed JSON). Errors as plain sentences."""
    from urllib.parse import urlencode
    url = "https://api.github.com" + path + (("?" + urlencode(params)) if params else "")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = send(method, url, headers=headers, body=body, cap=cap, timeout=timeout)
    data = r.json()
    if r.status >= 400:
        message = str((data or {}).get("message") or "") if isinstance(data, dict) else ""
        raise GitHubError(plain(r.status, message, r.headers), r.status)
    return r.status, data


def plain(status: int, message: str = "", headers: dict | None = None) -> str:
    m = message.lower()
    if status == 401:
        return "Sign in to GitHub again."
    if status in (403, 429) and ("rate limit" in m or (headers or {}).get("retry-after")):
        return "GitHub asked to wait a minute. Try again shortly."
    if status == 403 and "not accessible by integration" in m:
        return "Sharing isn't set up on GitHub yet."
    if status == 403:
        return "GitHub said no to that."
    if status == 404:
        return "GitHub couldn't find it."
    if status == 410:
        return "That's gone from GitHub."
    if status == 422:
        return "GitHub didn't accept it. It may be too big."
    if status >= 500:
        return "GitHub is having trouble. Try again in a bit."
    return f"GitHub answered {status}."
