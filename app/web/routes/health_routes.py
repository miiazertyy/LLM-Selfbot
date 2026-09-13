"""
app/web/routes/health_routes.py - what is stopping the bot from working.

Returns a flat list of issues, each tagged with the page that can fix it. The
sidebar puts a dot on that page's icon and the Dashboard lists them in full, so
"it isn't working" turns into a specific thing to go and do.

Every check is cheap enough to poll: the only expensive one (asking Puppeteer
where Chrome is, which spawns node) is cached.
"""

import os
import threading
import time

from fastapi import APIRouter, Request

from app.utils.credentials import real, real_int

router = APIRouter(tags=["health"])

# level: "error" stops the bot working, "warn" degrades it.
_chrome_cache = {"at": 0.0, "value": ""}
# Asking Puppeteer where Chrome is starts node, which takes about four and
# a half seconds. Chrome does not appear or vanish minute to minute, so a
# short cache bought nothing and paid that cost every single minute.
_CHROME_TTL = 900.0


def _chrome_path_cached() -> str:
    now = time.time()
    if now - _chrome_cache["at"] > _CHROME_TTL:
        try:
            from app.web.routes.system_routes import chrome_path
            _chrome_cache["value"] = chrome_path()
        except Exception:
            _chrome_cache["value"] = ""
        _chrome_cache["at"] = now
    return _chrome_cache["value"]


_RATE_MARKERS = ("rate_limit_exceeded", "RateLimitError", "rate limited",
                 "RATE LIMITED", "429", "tokens per minute")


def _rate_limited_in_log(within: float = 300.0) -> bool:
    """Whether an account has complained about rate limits recently.

    Accounts are child processes, so the in-memory record cannot see them. Their
    output is captured though, so the log buffer is the shared channel.
    """
    try:
        from app.web.logbus import bus
        cutoff = time.time() - within
        for entry in bus.tail(300):
            if entry.get("ts", 0) < cutoff:
                continue
            text = entry.get("text", "")
            if any(m in text for m in _RATE_MARKERS):
                return True
    except Exception:
        pass
    return False


# Checking GitHub on every health poll would be a request every 15 seconds, so
# the answer is kept for an hour. An update is not urgent enough to need finer.
_update_cache = {"at": 0.0, "value": None}
_UPDATE_TTL = 3600.0


def _update_available():
    """The newer release, or None. Never raises, never blocks for long."""
    now = time.time()
    if now - _update_cache["at"] < _UPDATE_TTL:
        return _update_cache["value"]
    _update_cache["at"] = now
    _update_cache["value"] = None
    try:
        import httpx
        from app.version import __version__, is_newer
        resp = httpx.get(
            "https://api.github.com/repos/miiazertyy/LLM-Selfbot/releases/latest",
            timeout=6)
        if resp.status_code == 200:
            tag = (resp.json() or {}).get("tag_name", "")
            from app.web.routes.system_routes import _ignored_update
            if is_newer(tag, __version__) and _ignored_update() != tag:
                _update_cache["value"] = {"latest": tag, "current": __version__}
    except Exception:
        pass          # offline is not a problem worth reporting
    return _update_cache["value"]


def _issues(supervisor) -> list:
    from app.core import ipc
    from app.utils.helpers import load_config

    out = []

    def add(route, level, title, detail, where="", section=""):
        # `where` names the exact spot on that page and `section` is the
        # Settings category holding it, so the banner can be a link that opens
        # the right place instead of a label you then have to go and find.
        out.append({"route": route, "level": level, "title": title,
                    "detail": detail, "where": where, "section": section})

    try:
        config = load_config()
    except Exception as e:
        add("settings", "error", "config.yaml could not be read", str(e))
        return out

    services = config.get("services", {}) or {}

    # ── What the AI provider has been saying ─────────────────────────────────
    # A rate limit is the most likely reason the bot goes quiet, and it used to
    # fail completely silently: the call was refused, the reason was swallowed,
    # and nothing anywhere said so.
    try:
        from app.utils import apihealth
        recent = apihealth.summary()
        if recent:
            if recent["kind"] == "rate_limit":
                add("logs", "warn", "Groq is rate limiting the bot",
                    recent["message"]
                    + (f" Seen {recent['count']} times in the last few minutes."
                       if recent["count"] > 1 else ""),
                    "the ai source in the log")
            else:
                add("logs", "error", "The AI provider returned an error",
                    recent["message"], "the ai source in the log")
        elif _rate_limited_in_log():
            # The accounts are separate processes, so their refusals never
            # reach the record above. What they print does reach the log bus,
            # which is the only channel that crosses the process boundary.
            add("logs", "warn", "Groq is rate limiting an account",
                "An account reported a rate limit in the last few minutes. "
                "The free tier caps tokens per minute, so replies are being "
                "delayed or dropped until it clears.",
                "the log below")
    except Exception:
        pass

    # ── A newer release ──────────────────────────────────────────────────────
    # Informational, so it is a "warn" rather than an error: nothing is broken,
    # there is just something newer. The dot on System is the point.
    update = _update_available()
    if update:
        # Quiet on purpose: nothing is broken, so this is a dot on System and a
        # line in the Updates card, not a banner across the top of every page.
        add("system", "info", f"Version {update['latest']} is available",
            f"You are running {update['current']}. Update from the System page, "
            f"or ignore this release and you will not be told about it again.",
            "the Updates card")

    # ── Models that Groq has retired ─────────────────────────────────────────
    # A decommissioned model answers every request with a 404, which looks
    # exactly like the bot being broken. Groq publishes what it actually has,
    # so this is checkable rather than guessable. The list is cached, and a
    # failure to fetch it says nothing at all rather than crying wolf.
    try:
        from app.utils.groqmodels import check_configured
        JOB = {"chat": "write replies", "vision": "read images",
               "stt": "transcribe speech", "tts": "speak out loud"}
        for problem in check_configured(config):
            if problem["reason"] == "wrong_kind":
                job = JOB.get(problem.get("needs"), problem.get("needs", ""))
                add("settings", "warn",
                    f"{problem['model']} cannot {job}",
                    "It is a real model, but not the sort this setting needs, so "
                    "every request using it fails. The picker only lists models "
                    "that can do the job.",
                    f"Groq, Models, {problem['key']}", section="Groq models")
                continue
            add("settings", "warn",
                f"{problem['model']} is not available",
                ("Groq has retired this model."
                 if problem["reason"] == "retired" else
                 "Groq does not offer this model on your account.")
                + " Requests using it will fail. Pick another from the list.",
                f"Groq, Models, {problem['key']}", section="Groq models")
    except Exception:
        pass

    # ── The brain ────────────────────────────────────────────────────────────
    # Running locally is a complete answer to where replies come from, so a
    # missing Groq key is only an error when nothing else can write them. What
    # matters then is whether that server is actually up.
    from app.utils import localai
    has_key = bool(real("GROQ_API_KEY_1") or real("GROQ_API_KEY"))
    if localai.active(config):
        local = localai.settings(config)
        probe = localai.probe(local["base_url"], timeout=2.0)
        if not probe["ok"]:
            add("settings", "error", "The local AI server is not answering",
                f"Replies are set to run on {local['model']} at "
                f"{local['base_url']}, and nothing is there. {probe['error']}. "
                "Start it, or turn local replies off to go back to Groq.",
                "AI provider, Local AI", section="local ai")
        elif local["model"] and local["model"] not in probe["models"]:
            add("settings", "error", f"{local['model']} is not on that server",
                "Every reply will fail with a 404. Pick one it actually has, or "
                "download it.",
                "AI provider, Local AI", section="local ai")
        elif not has_key:
            add("settings", "info", "Voice messages are off",
                "Replies run locally, which is fine, but no local server does "
                "speech. Voice notes need a Groq key.",
                "AI provider, API keys", section="Groq keys")
    elif not has_key:
        add("settings", "error", "No Groq API key",
            "The bot cannot generate any replies without one, unless you run a "
            "model on this machine instead.",
            "AI provider, API keys", section="Groq keys")

    # ── Accounts ─────────────────────────────────────────────────────────────
    discord_n = ipc._count_accounts()
    snap_n = ipc._count_snap_accounts()
    if discord_n == 0 and snap_n == 0:
        add("accounts", "error", "No accounts configured",
            "Nothing can run until one is configured.",
            "Add Discord account")

    children = []
    if supervisor is not None:
        try:
            children = supervisor.status()
        except Exception:
            children = []
    for child in children:
        label = child.get("label") or child.get("id")
        if child.get("state") == "crashing":
            add("accounts", "error", f"{label} keeps crashing",
                f"It has restarted {child.get('restarts', 0)} time(s).",
                f"Logs → filter by {child.get('id', 'the account')}")
        elif child.get("restarts", 0) >= 3:
            add("accounts", "warn", f"{label} has restarted {child['restarts']} times",
                "Something is making it exit.",
                f"Logs → filter by {child.get('id', 'the account')}")

    # ── Snapchat runtime ─────────────────────────────────────────────────────
    snap_on = (config.get("snapchat", {}).get("enabled", False)
               and services.get("snapchat", {}).get("enabled", True))
    if snap_on and snap_n:
        from app.web.routes.system_routes import SNAP_DIR, _snap_dir_for_probe, _which
        if not _which("node"):
            add("settings", "error", "Node.js is not installed",
                "Snapchat drives a real browser through Node. Install it from "
                "nodejs.org first.",
                "Snapchat, Install, Node.js", section="Snapchat setup")
        elif not (_snap_dir_for_probe() / "node_modules").is_dir():
            add("settings", "error", "Snapchat packages are not installed",
                "The Node packages have not been installed yet.",
                "Snapchat, Install", section="Snapchat setup")
        elif not _chrome_path_cached():
            add("settings", "error", "Snapchat's Chrome is missing",
                "The browser download did not finish. Repairing clears the "
                "partial download and fetches it again.",
                "Snapchat, Install, Repair install", section="Snapchat setup")

    # ── Telegram ─────────────────────────────────────────────────────────────
    if services.get("telegram", {}).get("enabled", True):
        token, owner = real("TELEGRAM_BOT_TOKEN"), real_int("TELEGRAM_OWNER_ID")
        if token and not owner:
            add("settings", "warn", "Telegram is half configured",
                "TELEGRAM_BOT_TOKEN is set but TELEGRAM_OWNER_ID is not, so the "
                "control bot will not start.",
                "App, Telegram, TELEGRAM_OWNER_ID", section="Telegram")
        elif owner and not token:
            add("settings", "warn", "Telegram is half configured",
                "TELEGRAM_OWNER_ID is set but TELEGRAM_BOT_TOKEN is not, so the "
                "control bot will not start.",
                "App, Telegram, TELEGRAM_BOT_TOKEN", section="Telegram")

    # ── Persona ──────────────────────────────────────────────────────────────
    try:
        from app.utils.paths import DATA_DIR
        instructions = DATA_DIR / "config" / "instructions.txt"
        if not instructions.exists() or not instructions.read_text(encoding="utf-8").strip():
            add("persona", "warn", "No persona instructions",
                "The bot has no character to play.",
                "the instructions editor")
    except OSError:
        pass

    # ── Optional tooling ─────────────────────────────────────────────────────
    try:
        from app.utils import binaries
        if not binaries.ffmpeg_status().get("ffmpeg"):
            add("system", "warn", "ffmpeg not found",
                "Voice messages fall back to a lower-quality path.",
                "Dependency doctor → ffmpeg")
    except Exception:
        pass

    return out


# The last computed answer, and when it was taken.
#
# Working this out means probing the filesystem, starting node to find Chrome,
# and two network calls. All of that is synchronous, and it used to run inside
# the request: on an async endpoint that blocks the whole event loop, so for
# several seconds at a time the server could not answer anything at all. The
# page polls this every fifteen seconds, so the entire panel stalled on a
# timer, which felt like every tab taking seconds to open.
#
# Now the work happens on a worker thread and the endpoint serves the most
# recent answer straight away.
_snapshot = {"at": 0.0, "value": None}
_SNAPSHOT_TTL = 12.0
_refreshing = threading.Lock()


def _refresh_snapshot(supervisor) -> dict:
    try:
        issues = _issues(supervisor)
    except Exception as exc:      # a broken probe must not blank the sidebar
        return _snapshot["value"] or {"issues": [], "routes": {}, "errors": 0,
                                      "warnings": 0, "error": str(exc)}
    by_route: dict[str, str] = {}
    for i in issues:
        # error outranks warn when one page has several issues.
        if by_route.get(i["route"]) != "error":
            by_route[i["route"]] = i["level"]
    value = {
        "issues": issues,
        "routes": by_route,
        "errors": sum(1 for i in issues if i["level"] == "error"),
        "warnings": sum(1 for i in issues if i["level"] == "warn"),
    }
    _snapshot.update(at=time.time(), value=value)
    return value


@router.get("/api/health")
async def health(request: Request):
    import asyncio

    supervisor = request.app.state.supervisor
    fresh = time.time() - _snapshot["at"] < _SNAPSHOT_TTL

    if _snapshot["value"] is None:
        # Nothing to serve yet, so this one call waits, but on a thread so the
        # rest of the panel keeps being answered while it does.
        return await asyncio.to_thread(_refresh_snapshot, supervisor)

    if not fresh and not _refreshing.locked():
        # Stale: hand back what we have and refresh behind it. A health warning
        # arriving a few seconds late costs nothing; a stalled panel does not.
        def _bg():
            with _refreshing:
                _refresh_snapshot(supervisor)
        threading.Thread(target=_bg, daemon=True, name="health-refresh").start()

    return _snapshot["value"]


@router.get("/api/health/blocking")
async def health_blocking(request: Request):
    """The uncached answer, for tests and for anything that must be current."""
    import asyncio
    return await asyncio.to_thread(_refresh_snapshot, request.app.state.supervisor)
