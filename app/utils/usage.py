"""What each model has been used for, and what is left of its limits.

No provider lets an ordinary API key ask how much it has used: Groq's API
reference has no such endpoint, and OpenAI's and Anthropic's usage APIs need an
admin key. What every one of them does send is the usage of each request in its
answer, and most send the state of the rate limit in the headers. So the app
counts for itself. Every answer a runner gets is read on its way back through
the SDK's own HTTP client, and counted per provider, model and job, per day, in
the shared database, where every account's runner adds to the same totals. The
headers give what is left: for Groq, the requests left today and the tokens left
this minute, for each model and key.

Each answer is also announced to the panel as it happens, so the model's row in
Models can light up the moment it is used.
"""
import asyncio
import contextvars
import json
import os
import re
import sys
import time
from datetime import datetime

# Which job a request belongs to ("replies", "small", "vision", "stt", "tts"), and the model asked for when the
# request body does not say (a voice note goes up as a file). Set by whoever makes the call.
JOB = contextvars.ContextVar("llmselfbot_ai_job", default="")
MODEL = contextvars.ContextVar("llmselfbot_ai_model", default="")
# Who the call is for, when it is a reply: the panel shows which model is writing
# for the conversation you are looking at, rather than whichever answered last
# anywhere. Empty for background work that belongs to nobody in particular.
CONV = contextvars.ContextVar("llmselfbot_ai_conversation", default="")

# Written in front of a usage event on a runner's stdout, for the supervisor to pass on.
MODEL_MARK = "\x1eMODEL "
# And in front of a request to a model starting or ending: the panel shows a model at work (the echo round the local
# server's logo in Settings) while it is, rather than all the time it is running.
WORK_MARK = "\x1eWORK "

# The endpoints worth counting. Listing models and the like is not usage.
_COUNTED = ("/chat/completions", "/responses", "/audio/transcriptions", "/audio/translations",
            "/audio/speech", "/embeddings")

# Plain x-ratelimit-*-requests / -tokens headers do not say their window. Groq's requests are per day and its
# tokens per minute; OpenAI-style ones are both per minute.
_WINDOWS = {"groq": {"requests": "day", "tokens": "minute"}}

KEEP_DAYS = 90


def _duration(text):
    """Seconds from now, from "2m59.56s", "7.66s", "450ms", "1h2m", a plain number, or an ISO time."""
    t = str(text or "").strip()
    if not t:
        return None
    try:
        return max(0.0, float(t))
    except ValueError:
        pass
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", t)
    if parts and "".join(n + u for n, u in parts) == t.replace(" ", ""):
        return sum(float(n) / 1000 if u == "ms" else float(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in parts)
    try:
        return max(0.0, datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() - time.time())
    except ValueError:
        return None


def parse_limits(provider: str, headers) -> list:
    """Every rate limit a set of headers describes, as [{what, window, limit, remaining, reset_at}].

    Providers name them differently: x-ratelimit-remaining-tokens (Groq, OpenAI, xAI),
    x-ratelimit-remaining-requests-day (Cerebras), anthropic-ratelimit-tokens-remaining,
    x-ratelimitbysize-remaining-minute (Mistral), x-tokenlimit-remaining (Together).
    """
    now = time.time()
    found = {}
    for name, value in headers.items():
        n = name.lower()
        m = re.match(r"^x-ratelimit-(limit|remaining|reset)-(requests|tokens)(?:-(minute|hour|day|month))?$", n)
        if m:
            field, what, window = m.groups()
        elif (m := re.match(r"^anthropic-ratelimit-(requests|tokens|input-tokens|output-tokens)-(limit|remaining|reset)$", n)):
            what, field = m.groups()
            window = "minute"
        elif (m := re.match(r"^x-ratelimitbysize-(limit|remaining|reset)-(minute|hour|day|month)$", n)):
            field, window = m.groups()
            what = "tokens"
        elif (m := re.match(r"^x-(ratelimit|tokenlimit)-(limit|remaining|reset)$", n)):
            kind, field = m.groups()
            what, window = ("requests" if kind == "ratelimit" else "tokens"), "second"
        else:
            continue
        window = window or _WINDOWS.get(provider, {}).get(what, "minute")
        item = found.setdefault((what, window), {"what": what, "window": window})
        if field == "reset":
            secs = _duration(value)
            if secs is not None:
                item["reset_at"] = round(now + secs, 1)
        else:
            try:
                item[field] = int(float(str(value).strip()))
            except (TypeError, ValueError):
                pass
    return [v for v in found.values() if "limit" in v or "remaining" in v]


def _request_model(request) -> str:
    """The model a request asked for, from its JSON body, or the form field of an upload."""
    try:
        body = request.content
    except Exception:
        return ""
    if not body:
        return ""
    ctype = request.headers.get("content-type", "")
    try:
        if "json" in ctype:
            return str(json.loads(body).get("model") or "")
        if "multipart" in ctype:
            m = re.search(rb'name="model"\r\n\r\n([^\r\n]+)', body)
            return m.group(1).decode("utf-8", "replace") if m else ""
    except Exception:
        return ""
    return ""


def tokens_of(data) -> tuple:
    """(in, out, reasoning) from an answer's usage, in either the chat or the responses shape."""
    u = (data or {}).get("usage") or {}
    if not isinstance(u, dict):
        return 0, 0, 0
    tin = u.get("prompt_tokens") or u.get("input_tokens") or 0
    tout = u.get("completion_tokens") or u.get("output_tokens") or 0
    det = u.get("completion_tokens_details") or u.get("output_tokens_details") or {}
    reasoning = det.get("reasoning_tokens") if isinstance(det, dict) else 0
    try:
        return int(tin), int(tout), int(reasoning or 0)
    except (TypeError, ValueError):
        return 0, 0, 0


async def _observe(provider: str, key: str, response) -> None:
    request = response.request
    path = request.url.path
    if not path.endswith(_COUNTED):
        return
    model = _request_model(request) or MODEL.get() or "?"
    job = JOB.get() or "other"
    status = response.status_code
    t0 = request.extensions.get("llmselfbot_t0")
    ms = int((time.monotonic() - t0) * 1000) if t0 else 0
    tin = tout = reasoning = 0
    if status == 200 and "json" in response.headers.get("content-type", ""):
        # Read here, once: httpx keeps the body, so the SDK reads the same bytes after this rather than the network.
        await response.aread()
        try:
            tin, tout, reasoning = tokens_of(json.loads(response.content))
        except Exception:
            pass
    ok = 200 <= status < 300
    limited = status == 429
    limits = parse_limits(provider, response.headers)
    now = time.time()
    record = {"provider": provider, "model": model, "job": job, "ok": ok, "limited": limited,
              "status": status, "in": tin, "out": tout, "reasoning": reasoning, "ms": ms,
              "key": key, "limits": limits, "at": now, "uid": CONV.get() or ""}
    try:
        asyncio.get_running_loop().run_in_executor(None, save, record)
    except RuntimeError:
        save(record)
    emit(record)


# How many sockets one provider's client may hold open. The SDKs default to
# httpx's 100, and there is one client per Groq key and per provider: with a few
# keys set up that is several hundred sockets from this process alone. The
# account runners use a SelectorEventLoop on Windows (curl_cffi needs
# add_reader), and select() there cannot watch more than 512 sockets at once -
# past that every pass of the event loop dies with WinError 10055 and takes the
# account down with it. Replies are a handful of requests at a time, never
# dozens, so a small pool costs nothing and keeps the total far below that.
POOL_MAX = 12
POOL_KEEPALIVE = 6


def http_client(provider: str, key: str = "", sdk: str = "openai"):
    """The SDK's own default HTTP client, looking at every answer on its way back, and holding a bounded number of sockets (see POOL_MAX)."""
    import httpx

    if sdk == "groq":
        from groq import DefaultAsyncHttpxClient
    else:
        from openai import DefaultAsyncHttpxClient

    async def on_request(request):
        request.extensions["llmselfbot_t0"] = time.monotonic()
        if request.url.path.endswith(_COUNTED):
            rid = f"{os.getpid()}-{id(request)}"
            request.extensions["llmselfbot_rid"] = rid
            work(provider, request, rid, True)

    async def on_response(response):
        try:
            await _observe(provider, key, response)
        except Exception:
            pass
        finally:
            rid = response.request.extensions.get("llmselfbot_rid")
            if rid:
                work(provider, response.request, rid, False)

    return DefaultAsyncHttpxClient(
        event_hooks={"request": [on_request], "response": [on_response]},
        limits=httpx.Limits(max_connections=POOL_MAX, max_keepalive_connections=POOL_KEEPALIVE),
    )


def work(provider: str, request, rid: str, start: bool) -> None:
    """Tell the panel, when running under it, that a request to a model has started or ended (see WORK_MARK). One
    that never ends (the connection broke) the panel lets go of after a while."""
    from app.core.launcher import under_panel
    if not under_panel():
        return
    try:
        evt = {"provider": provider, "model": _request_model(request) or MODEL.get() or "", "job": JOB.get() or "",
               "rid": rid, "state": "start" if start else "end", "at": time.time()}
        sys.stdout.write(WORK_MARK + json.dumps(evt, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def emit(record: dict) -> None:
    """Tell the panel, when running under it, so the row can light up."""
    from app.core.launcher import under_panel
    if not under_panel():
        return
    try:
        evt = {k: record[k] for k in ("provider", "model", "job", "ok", "limited", "in", "out", "ms", "at")}
        if record.get("uid"):
            evt["uid"] = record["uid"]
        if record.get("limits"):
            evt["limits"] = record["limits"]
        sys.stdout.write(MODEL_MARK + json.dumps(evt, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


# ── The counts, in the shared database ───────────────────────────────────────

def _ensure(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_usage (
            day TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, job TEXT NOT NULL,
            requests INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
            limited INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0, reasoning_tokens INTEGER NOT NULL DEFAULT 0,
            ms INTEGER NOT NULL DEFAULT 0, last_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (day, provider, model, job))""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_limits (
            provider TEXT NOT NULL, model TEXT NOT NULL, key TEXT NOT NULL,
            data TEXT NOT NULL, at REAL NOT NULL,
            PRIMARY KEY (provider, model, key))""")


_pruned_day = ""


def save(record: dict) -> None:
    """Add one answer to the day's counts, and keep the latest limits it reported."""
    global _pruned_day
    from app.utils.db import connect_raw
    day = datetime.fromtimestamp(record["at"]).strftime("%Y-%m-%d")
    ok, limited = bool(record["ok"]), bool(record["limited"])
    conn = connect_raw()
    try:
        _ensure(conn)
        conn.execute("""
            INSERT INTO model_usage (day, provider, model, job, requests, errors, limited, input_tokens,
                                     output_tokens, reasoning_tokens, ms, last_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day, provider, model, job) DO UPDATE SET
                requests = requests + excluded.requests, errors = errors + excluded.errors,
                limited = limited + excluded.limited, input_tokens = input_tokens + excluded.input_tokens,
                output_tokens = output_tokens + excluded.output_tokens,
                reasoning_tokens = reasoning_tokens + excluded.reasoning_tokens,
                ms = ms + excluded.ms, last_at = MAX(last_at, excluded.last_at)""",
            (day, record["provider"], record["model"], record["job"], 1 if ok else 0,
             0 if ok or limited else 1, 1 if limited else 0, record["in"], record["out"],
             record["reasoning"], record["ms"] if ok else 0, record["at"]))
        if record.get("limits"):
            conn.execute("INSERT OR REPLACE INTO model_limits (provider, model, key, data, at) VALUES (?, ?, ?, ?, ?)",
                         (record["provider"], record["model"], record.get("key") or "", json.dumps(record["limits"]),
                          record["at"]))
        if _pruned_day != day:
            cutoff = datetime.fromtimestamp(record["at"] - KEEP_DAYS * 86400).strftime("%Y-%m-%d")
            conn.execute("DELETE FROM model_usage WHERE day < ?", (cutoff,))
            _pruned_day = day
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def summary(days: int = 7) -> dict:
    """Every model used in the last `days` days, with today's counts, one bar per day, what each job used, and the
    latest limits per key. Read by the panel."""
    from app.utils.db import connect_raw
    days = max(1, min(60, int(days)))
    now = time.time()
    today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    span = [datetime.fromtimestamp(now - i * 86400).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    conn = connect_raw()
    try:
        _ensure(conn)
        rows = conn.execute("""
            SELECT day, provider, model, job, requests, errors, limited, input_tokens, output_tokens,
                   reasoning_tokens, ms, last_at FROM model_usage WHERE day >= ?""", (span[0],)).fetchall()
        lim_rows = conn.execute("SELECT provider, model, key, data, at FROM model_limits").fetchall()
    finally:
        conn.close()
    models = {}
    for day, provider, model, job, req, err, lim, tin, tout, reas, ms, last in rows:
        m = models.setdefault((provider, model), {
            "provider": provider, "model": model, "last_at": 0.0, "jobs": {},
            "today": {"requests": 0, "errors": 0, "limited": 0, "in": 0, "out": 0, "reasoning": 0, "ms": 0},
            "days": {d: {"requests": 0, "tokens": 0} for d in span}, "limits": [],
        })
        m["last_at"] = max(m["last_at"], last or 0)
        if day in m["days"]:
            m["days"][day]["requests"] += req
            m["days"][day]["tokens"] += tin + tout
        if day == today:
            t = m["today"]
            t["requests"] += req
            t["errors"] += err
            t["limited"] += lim
            t["in"] += tin
            t["out"] += tout
            t["reasoning"] += reas
            t["ms"] += ms
            m["jobs"][job] = m["jobs"].get(job, 0) + req
    for provider, model, key, data, at in lim_rows:
        m = models.get((provider, model))
        if m is None:
            continue
        try:
            m["limits"].append({"key": key, "at": at, "items": json.loads(data)})
        except ValueError:
            pass
    out = []
    for m in models.values():
        m["days"] = [{"day": d, **v} for d, v in m["days"].items()]
        m["limits"] = merge_limits(m["limits"], now)
        out.append(m)
    out.sort(key=lambda m: (-m["today"]["requests"], -m["last_at"]))
    return {"models": out, "today": today, "days": span}


def merge_limits(per_key: list, now: float) -> list:
    """One gauge per limit, adding up every key's: the app moves to the next key when one runs out, so together
    they are what is left. A key whose window has reset since it last answered counts as full again."""
    merged = {}
    for entry in per_key:
        for item in entry.get("items") or []:
            k = (item.get("what"), item.get("window"))
            g = merged.setdefault(k, {"what": k[0], "window": k[1], "limit": 0, "remaining": 0, "keys": 0,
                                      "reset_at": None})
            limit = item.get("limit")
            remaining = item.get("remaining")
            reset_at = item.get("reset_at")
            if reset_at and reset_at <= now and limit is not None:
                remaining = limit
                reset_at = None
            if limit is not None:
                g["limit"] += limit
            if remaining is not None:
                g["remaining"] += remaining
            if reset_at and (g["reset_at"] is None or reset_at < g["reset_at"]):
                g["reset_at"] = reset_at
            g["keys"] += 1
    order = {"day": 0, "month": 1, "hour": 2, "minute": 3, "second": 4}
    return sorted((g for g in merged.values() if g["limit"] > 0),
                  key=lambda g: (order.get(g["window"], 9), g["what"] != "requests"))
