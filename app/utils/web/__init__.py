"""
app/utils/web - the persona on the internet, the way a person with a phone is: it looks something up when a message
needs it, reads the links people send, and browses a little in its own free time.

- guard.py: where it may go. http and https, to public addresses only: never the panel on 127.0.0.1, never anything
  on the home network.
- page.py: a page read and boiled down to its title, its words and its links.
- search.py: a search. Google in its own browser first, then DuckDuckGo, or Brave or Tavily with a key.
- browser.py: a Chrome of its own (app/platforms/snapchat/webbrowser.js), for Google, pages that need JavaScript,
  clicking around and a look at the screen. Without Node or the browser packages everything still works, plainer.
- agent.py: the loop that searches, opens, follows and reads until it can answer.
- lookup.py: a reply that needs the web. The model says so itself (LOOKUP: ...), the agent looks, it is asked again.
- links.py: links people send, read, with a note on what they say going in with the message.
- journal.py, freetime.py: browsing on its own a few times a day, and what it saw, for it to bring up later.

Settings: bot.web (enabled, links, free_time, sessions_per_day, search_with, share_links, per_hour). Keys for Brave
and Tavily: BRAVE_API_KEY, TAVILY_API_KEY in config/.env.
"""
from __future__ import annotations

# bot.web as config.yaml ships it: everything on, at a gentle pace.
DEFAULTS = {
    "enabled": True,
    "links": True,
    "free_time": True,
    "sessions_per_day": 3,
    "search_with": "auto",
    "share_links": True,
    "per_hour": 12,
}
SEARCH_WITH = ("auto", "google", "duckduckgo", "brave", "tavily")


def settings(config: dict | None = None) -> dict:
    """bot.web, each setting there and of its kind. Read for the persona this process speaks as (load_config)."""
    if config is None:
        try:
            from app.utils.helpers import load_config
            config = load_config()
        except Exception:
            config = {}
    raw = ((config or {}).get("bot") or {}).get("web")
    out = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for key in ("enabled", "links", "free_time", "share_links"):
        if raw.get(key) is not None:
            out[key] = bool(raw[key])
    for key, low, high in (("sessions_per_day", 0, 24), ("per_hour", 0, 120)):
        try:
            out[key] = max(low, min(high, int(raw.get(key, out[key]))))
        except (TypeError, ValueError):
            pass
    if str(raw.get("search_with") or "").lower() in SEARCH_WITH:
        out["search_with"] = str(raw["search_with"]).lower()
    return out
