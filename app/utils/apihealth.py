"""
app/utils/apihealth.py - remembering when the AI provider says no.

A rate limit is the single most likely reason the bot goes quiet, and it used
to be completely invisible: the call failed, the caller swallowed the reason,
and the picture simply had no description with nothing to explain why. The
answer came back as a 429 with a perfectly clear message, and nobody ever saw
it.

Every provider refusal is recorded here, in memory, so the panel can put a dot
on the sidebar and say what happened in words rather than leaving you guessing.
Nothing is written to disk: these are transient conditions, and a limit from
yesterday is not worth reporting today.
"""

import re
import time
from collections import deque
from threading import Lock

# Enough history to see a pattern, not enough to grow without bound.
_MAX = 40

# How long a problem stays interesting. A rate limit is per minute, so a few
# minutes of quiet means it has cleared.
FRESH_SECONDS = 300

_events = deque(maxlen=_MAX)
_lock = Lock()


def _humanise(kind: str, message: str) -> str:
    """Turn a provider error into something worth reading.

    The raw text is a nested JSON blob quoting limits and organisation ids. The
    useful part is which limit was hit and what to do, so that is what gets
    pulled out.
    """
    text = " ".join((message or "").split())

    if kind == "rate_limit":
        # "on output tokens per minute (OTPM): Limit 1000, Requested 1751"
        # The digit class must not run past the number onto the comma that
        # separates the two figures, or the message reads "allows 1000, output".
        limits = re.search(
            r"\(([A-Z]{3,6})\).{0,40}?Limit\s+([\d,]*\d).{0,20}?Requested\s+([\d,]*\d)", text)
        if limits:
            kinds = {"OTPM": "output tokens per minute",
                     "TPM": "tokens per minute",
                     "RPM": "requests per minute",
                     "TPD": "tokens per day",
                     "RPD": "requests per day",
                     "ITPM": "input tokens per minute"}
            what = kinds.get(limits.group(1), limits.group(1))
            return (f"Groq allows {limits.group(2)} {what} on this plan and the "
                    f"request needed {limits.group(3)}.")
        if "quota" in text.lower() or "credit" in text.lower():
            return "The Groq account is out of quota."
        inner = re.search(r"'message':\s*\"([^\"]{10,240})", text)
        if inner:
            return inner.group(1)
        return "Groq refused the request as too frequent or too large."

    if "authentication" in text.lower() or "api key" in text.lower() or "401" in text:
        return "Groq rejected the API key."
    inner = re.search(r"'message':\s*\"([^\"]{10,240})", text)
    if inner:
        return inner.group(1)
    return text[:240] or "The AI provider returned an error."


def record(kind: str, message: str, model: str = "") -> dict:
    """Note that the provider refused something. Safe to call from anywhere."""
    event = {
        "kind": kind,
        "model": model,
        "message": _humanise(kind, message),
        "raw": " ".join((message or "").split())[:600],
        "ts": time.time(),
    }
    with _lock:
        _events.append(event)
    # The log stream is where someone actually looks, so it goes there too, at a
    # level the Logs page paints red.
    try:
        from app.web.logbus import bus
        label = "Rate limited" if kind == "rate_limit" else "AI error"
        bus.append("ai", f"{label}: {event['message']}"
                         + (f" [{model}]" if model else ""),
                   "warn" if kind == "rate_limit" else "error")
    except Exception:
        pass          # the runners import this without a web server present
    return event


def recent(within: float = FRESH_SECONDS) -> list:
    """Problems new enough to still be true."""
    cutoff = time.time() - within
    with _lock:
        return [e for e in _events if e["ts"] >= cutoff]


def summary(within: float = FRESH_SECONDS) -> dict | None:
    """One line about the current state, or None when nothing is wrong."""
    events = recent(within)
    if not events:
        return None
    latest = events[-1]
    rate = [e for e in events if e["kind"] == "rate_limit"]
    return {
        "kind": latest["kind"],
        "message": latest["message"],
        "model": latest["model"],
        "count": len(events),
        "rate_limited": len(rate),
        "ts": latest["ts"],
    }


def clear() -> None:
    with _lock:
        _events.clear()
