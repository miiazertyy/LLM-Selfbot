"""What is left with each provider, asked of the provider itself, for Settings, Models, Usage.

Each one is asked in the one way it allows an ordinary key:

  its account    OpenRouter's credits (GET /key), DeepSeek's balance (GET /user/balance), ElevenLabs' characters
                 (GET /user/subscription).
  an answer      Groq, OpenAI, Anthropic, Mistral, xAI, Together and Cerebras have no such route for an ordinary key, but
                 every answer carries how much is left of its limits in its headers. Their model lists do not (Groq's
                 tried, 2026-11-05), so it takes a real answer: one token, per model, per key where a provider's keys
                 are told apart. A request off the day's allowance and a fraction of a cent, at most every five minutes.
  nothing        Google tells an ordinary key nothing at all, and an answer from it carries no limits: said so, with the
                 way to its own page.

What an answer says is kept with what real answers have said (usage.keep_limits), so the rest of the app has it too. These
answers are not counted as requests: they were not the app doing anything.
"""
import concurrent.futures
import json
import time
import urllib.error
import urllib.request

from app.utils import providers, usage

ASK_EVERY = 300.0
MODELS_ASKED = 4
# Where each one's own numbers are, for what it will not say here.
CONSOLES = {
    "groq": "https://console.groq.com/settings/limits",
    "openai": "https://platform.openai.com/usage",
    "anthropic": "https://console.anthropic.com/settings/usage",
    "gemini": "https://aistudio.google.com/usage",
    "mistral": "https://admin.mistral.ai/plateforme/limits",
    "xai": "https://console.x.ai",
    "together": "https://api.together.ai/settings/billing",
    "cerebras": "https://cloud.cerebras.ai",
}
_TIMEOUT = 12.0


def _json(url: str, headers: dict) -> dict:
    return providers._get_json(url, headers, _TIMEOUT)


def _labelled_keys(pid: str) -> list:
    """(the label usage.py keeps limits under, the key). Groq's clients are one per key, each with its own label, and its
    keys' limits add up. Every other provider's answers are kept under one name however many keys it has, so one is asked."""
    keys = providers.keys_for(pid)
    if pid != "groq":
        return [("", keys[0])] if keys else []
    out = []
    for i in range(1, 51):
        k = providers._env_value(f"GROQ_API_KEY_{i}")
        if k:
            out.append((f"GROQ_API_KEY_{i}", k))
    if not out and keys:
        out.append(("GROQ_API_KEY", keys[0]))
    return out


def _models_to_ask(pid: str, config: dict) -> list:
    """The models that have been used, those it is set to use, and otherwise the first it lists. Only what can answer: a
    voice or a transcriber has no answer to give one token of."""
    can = lambda m: "chat" in providers.capabilities(pid, m)
    chosen = [e["model"] for e in providers.reply_chain(config) if e.get("provider") == pid]
    for chain in providers.plan(config).get("chains", {}).values():
        chosen += [e["model"] for e in chain if e.get("provider") == pid]
    out = list(dict.fromkeys(m for m in [*usage.recent_models(pid), *chosen] if m and can(m)))
    if not out:
        listed = providers.list_models(pid, config).get("models") or []
        out = [m["id"] for m in listed if "chat" in (m.get("capabilities") or [])][:1]
    return out[:MODELS_ASKED]


def _one_token(pid: str, config: dict, key: str, model: str) -> tuple:
    """(status, the limits its headers gave, what it said). An error comes with the same headers, so it is an answer too."""
    url = providers.base_url(pid, config).rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json", "user-agent": providers.user_agent()}
    if pid == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    # Some of OpenAI's newest take the limit under another name, and say so.
    for field in ("max_tokens", "max_completion_tokens"):
        body = json.dumps({"model": model, field: 1, "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                return r.status, usage.parse_limits(pid, dict(r.headers.items())), ""
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")[:600]
            if e.code == 400 and field == "max_tokens" and "max_completion_tokens" in raw:
                continue
            return e.code, usage.parse_limits(pid, dict(e.headers.items())), raw
    return 0, [], ""


def _ask_answers(pid: str, config: dict) -> dict:
    """The limits of what it is used for, from a one-token answer per model and per key, side by side."""
    keys = _labelled_keys(pid)
    models = _models_to_ask(pid, config)
    if not models:
        return {"why": "It has no model to ask about yet."}
    jobs = [(label, key, model) for model in models for label, key in keys]
    refused, trouble = 0, ""
    usage.drop_other_keys(pid, [label for label, _key in keys])

    def one(job):
        label, key, model = job
        status, limits, raw = _one_token(pid, config, key, model)
        if limits:
            usage.keep_limits(pid, model, label, limits)
        return status, raw

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for job, done in zip(jobs, pool.map(lambda j: _safely(one, j), jobs)):
            if isinstance(done, Exception):
                trouble = f"Could not reach {providers.BY_ID[pid]['name']}."
                continue
            status, _raw = done
            if status in (401, 403):
                refused += 1
            elif status == 402:
                trouble = "It says the account is out of credit."
            elif status and status >= 500:
                trouble = f"{providers.BY_ID[pid]['name']} is having trouble."
    held = usage.limits_of(pid)
    rows = [{"model": m, "limits": held.get(m) or []} for m in models]
    out = {"models": [r for r in rows if r["limits"]]}
    if refused == len(jobs):
        out["why"] = "The key was refused."
    elif trouble:
        out["why"] = trouble
    elif not out["models"]:
        out["why"] = f"{providers.BY_ID[pid]['name']} does not say how much is left."
    return out


def _safely(fn, arg):
    try:
        return fn(arg)
    except Exception as e:
        return e


def _openrouter(config: dict) -> dict:
    key = providers.keys_for("openrouter")[0]
    d = _json(providers.base_url("openrouter", config).rstrip("/") + "/key", {"Authorization": f"Bearer {key}"}).get("data") or {}
    free = d.get("free_model_daily_requests") or {}
    out = {"plan": "Free" if d.get("is_free_tier") else "",
           "money": {"currency": "USD", "left": d.get("limit_remaining"), "limit": d.get("limit"),
                     "today": d.get("usage_daily"), "month": d.get("usage_monthly"), "used": d.get("usage")}}
    if free:
        out["meters"] = [{"what": "free-requests", "window": "day", "limit": free.get("limit") or 0,
                          "remaining": free.get("remaining") or 0, "keys": 1, "reset_at": None}]
    return out


def _deepseek(config: dict) -> dict:
    key = providers.keys_for("deepseek")[0]
    d = _json("https://api.deepseek.com/user/balance", {"Authorization": f"Bearer {key}"})
    infos = d.get("balance_infos") or []
    if not infos:
        return {"why": "It says there is no balance." if not d.get("is_available") else ""}
    first = infos[0]
    return {"money": {"currency": first.get("currency"), "left": _number(first.get("total_balance")),
                      "granted": _number(first.get("granted_balance")), "topped_up": _number(first.get("topped_up_balance"))},
            "why": "" if d.get("is_available") else "It says the balance is too low to answer."}


def _elevenlabs(config: dict) -> dict:
    key = providers.keys_for("elevenlabs")[0]
    d = _json(providers.base_url("elevenlabs", config).rstrip("/") + "/user/subscription", {"xi-api-key": key})
    limit, used = int(d.get("character_limit") or 0), int(d.get("character_count") or 0)
    return {"plan": str(d.get("tier") or "").replace("_", " ").capitalize(),
            "meters": [{"what": "characters", "window": "month", "limit": limit, "remaining": max(0, limit - used), "keys": 1,
                        "reset_at": d.get("next_character_count_reset_unix") or None}] if limit else []}


def _number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


ACCOUNTS = {"openrouter": _openrouter, "deepseek": _deepseek, "elevenlabs": _elevenlabs}
# Google tells an ordinary key nothing, and its answers carry no limits, so nothing is spent finding that out.
SILENT = {"gemini": "Google does not say how much is left, except on its own page.",
          "deepgram": "Deepgram shows what is left on its own page.",
          "cartesia": "Cartesia shows what is left on its own page.",
          "fish": "Fish Audio shows what is left on its own page.",
          "rime": "Rime shows what is left on its own page.",
          "minimax": "MiniMax shows what is left on its own page."}


def ask(pid: str, config: dict) -> dict:
    """What is left with one provider: {id, at, keys, plan, money, meters, models, why, link}."""
    out = {"id": pid, "at": time.time(), "keys": len(providers.keys_for(pid)), "plan": "", "money": None, "meters": [],
           "models": [], "why": "", "link": CONSOLES.get(pid, "")}
    try:
        if pid in SILENT:
            out["why"] = SILENT[pid]
        elif pid in ACCOUNTS:
            out.update(ACCOUNTS[pid](config))
        else:
            out.update(_ask_answers(pid, config))
    except urllib.error.HTTPError as e:
        out["why"] = "The key was refused." if e.code in (401, 403) else f"{providers.BY_ID[pid]['name']} said {e.code}."
    except Exception as e:
        out["why"] = f"Could not reach {providers.BY_ID[pid]['name']} ({type(e).__name__})."
    return out


def ask_all(config: dict) -> list:
    """Every provider with a key, side by side, in the order Settings lists them. This computer has no limits to ask about."""
    pids = [p["id"] for p in providers.PROVIDERS if p["id"] != "local" and providers.keys_for(p["id"])]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, len(pids)))) as pool:
        return list(pool.map(lambda pid: ask(pid, config), pids))
