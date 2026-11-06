"""ghapi.py - the few GitHub REST calls the community workflows make, with the standard library only.

Retries what is worth retrying (GitHub's 5xx, a dropped connection, "wait a minute" limits), pages through lists, and
uploads release files. Tests hand the scripts a fake with the same methods instead.

The repo is the app's own, so everything here stays inside what the community owns: issues it's handed, the
community's release, its own workflows.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status
        self.message = message


class GitHub:
    def __init__(self, token: str, repo: str, api: str = API):
        self.token = token
        self.repo = repo
        self.api = api.rstrip("/")

    # ── The wire ──────────────────────────────────────────────────────────────

    def request(self, method: str, path: str, *, body=None, params=None, data: bytes | None = None,
                content_type: str = "", base: str | None = None, accept: str = "application/vnd.github+json"):
        url = (base or self.api) + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        headers = {"Accept": accept, "User-Agent": "llmselfbot-community", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            payload = data
            headers["Content-Type"] = content_type or "application/octet-stream"
        for attempt in range(4):
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw = r.read()
                    return r.status, dict(r.headers), (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    info = json.loads(raw)
                except ValueError:
                    info = {"message": raw[:200].decode("utf-8", "replace")}
                message = str(info.get("message") or e.reason)
                limited = e.code in (403, 429) and ("rate limit" in message.lower() or e.headers.get("Retry-After"))
                if (e.code >= 500 or limited) and attempt < 3:
                    wait = int(e.headers.get("Retry-After") or 0) or (5 * (attempt + 1))
                    time.sleep(min(wait, 60))
                    continue
                raise GitHubError(e.code, message) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise GitHubError(0, str(e)) from None
        raise GitHubError(0, "no answer")

    def get(self, path, **params):
        return self.request("GET", path, params=params or None)[2]

    def paginate(self, path, **params):
        out, page = [], 1
        while True:
            chunk = self.request("GET", path, params={**params, "per_page": 100, "page": page})[2]
            if not isinstance(chunk, list) or not chunk:
                return out
            out += chunk
            if len(chunk) < 100:
                return out
            page += 1

    # ── Issues ────────────────────────────────────────────────────────────────

    def r(self, rest: str) -> str:
        return f"/repos/{self.repo}{rest}"

    def issue(self, n: int) -> dict:
        return self.get(self.r(f"/issues/{n}"))

    def issues(self, **params) -> list:
        return [i for i in self.paginate(self.r("/issues"), **params) if "pull_request" not in i]

    def comments(self, n: int) -> list:
        return self.paginate(self.r(f"/issues/{n}/comments"))

    def comment(self, n: int, body: str) -> dict:
        return self.request("POST", self.r(f"/issues/{n}/comments"), body={"body": body})[2]

    def edit_comment(self, comment_id: int, body: str) -> dict:
        return self.request("PATCH", self.r(f"/issues/comments/{comment_id}"), body={"body": body})[2]

    def open_issue(self, title: str, body: str, labels=()) -> dict:
        return self.request("POST", self.r("/issues"), body={"title": title, "body": body, "labels": list(labels)})[2]

    def react(self, comment_id: int, content: str = "+1") -> None:
        try:
            self.request("POST", self.r(f"/issues/comments/{comment_id}/reactions"), body={"content": content})
        except GitHubError:
            pass

    def add_labels(self, n: int, labels) -> None:
        self.request("POST", self.r(f"/issues/{n}/labels"), body={"labels": list(labels)})

    def remove_label(self, n: int, label: str) -> None:
        try:
            self.request("DELETE", self.r(f"/issues/{n}/labels/{urllib.parse.quote(label)}"))
        except GitHubError:
            pass

    def close(self, n: int, reason: str = "completed", lock: bool = True) -> None:
        self.request("PATCH", self.r(f"/issues/{n}"), body={"state": "closed", "state_reason": reason})
        if lock:
            try:
                self.request("PUT", self.r(f"/issues/{n}/lock"), body={"lock_reason": "resolved"})
            except GitHubError:
                pass

    def ensure_labels(self, specs: dict) -> None:
        have = {label["name"] for label in self.paginate(self.r("/labels"))}
        for name, (color, description) in specs.items():
            if name not in have:
                self.request("POST", self.r("/labels"), body={"name": name, "color": color, "description": description})

    # ── People ────────────────────────────────────────────────────────────────

    def user(self, login: str) -> dict:
        return self.get(f"/users/{urllib.parse.quote(login)}")

    def permission(self, login: str) -> str:
        try:
            return str(self.get(self.r(f"/collaborators/{urllib.parse.quote(login)}/permission")).get("permission") or "")
        except GitHubError:
            return ""

    # ── Releases ──────────────────────────────────────────────────────────────

    def release_by_tag(self, tag: str) -> dict | None:
        try:
            return self.get(self.r(f"/releases/tags/{urllib.parse.quote(tag)}"))
        except GitHubError as e:
            if e.status == 404:
                return None
            raise

    def latest_release_tag(self) -> str:
        """The app's newest release ("v1.7.1"), "" when there's none. GitHub's latest skips pre-releases, so never the
        community's own."""
        try:
            return str(self.get(self.r("/releases/latest")).get("tag_name") or "")
        except GitHubError:
            return ""

    def release_assets(self, release_id: int) -> list:
        """Every file of a release, page by page (a release can hold up to 1000)."""
        return self.paginate(self.r(f"/releases/{release_id}/assets"))

    def create_release(self, tag: str, name: str, body: str, prerelease: bool = False, target: str = "") -> dict:
        # Never "latest": the app and its download badge ask for the latest release, which must stay the app's.
        return self.request("POST", self.r("/releases"), body={
            "tag_name": tag, "name": name, "body": body, "prerelease": prerelease, "make_latest": "false",
            **({"target_commitish": target} if target else {})})[2]

    def upload_asset(self, release: dict, name: str, data: bytes, content_type: str = "application/zip") -> dict:
        path = f"/repos/{self.repo}/releases/{release['id']}/assets?name={urllib.parse.quote(name)}"
        return self.request("POST", path, data=data, content_type=content_type, base=UPLOADS)[2]

    def delete_asset(self, asset_id: int) -> None:
        self.request("DELETE", self.r(f"/releases/assets/{asset_id}"))

    # ── Workflows ─────────────────────────────────────────────────────────────

    def enable(self, workflow: str) -> None:
        """A workflow turned back on if GitHub paused it (it pauses scheduled ones after 60 quiet days)."""
        try:
            self.request("PUT", self.r(f"/actions/workflows/{workflow}/enable"))
        except GitHubError:
            pass

    def dispatch(self, workflow: str, ref: str = "main") -> None:
        self.enable(workflow)
        try:
            self.request("POST", self.r(f"/actions/workflows/{workflow}/dispatches"), body={"ref": ref})
        except GitHubError:
            pass
