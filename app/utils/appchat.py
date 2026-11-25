"""The Ask box in Settings: someone says what they want in words, the model that writes their replies works out which
settings that means, and the same tools a connected AI app gets do it (app/utils/apptools.py), under the same limits.

Most models take tools the official way, and those have to be given them that way: described in the prompt instead, the
gpt-oss models tried to call them regardless and came back empty, or said a thing was done without doing it (asked for
real, 2026-11-09). A model or server that won't take tools falls back to writing one JSON object a turn, which all can do.
"""
from __future__ import annotations

import asyncio
import json
import re

from app.utils import apptools

WHO = "Ask box"
#: Model turns one question can take, and tool calls in one turn.
MAX_ROUNDS = 8
MAX_CALLS = 6
#: How much of one tool's answer goes back to the model.
ROOM = 12_000
#: How long a turn may be, and how long the second try when a reasoning model spent it all on thinking.
LENGTH = 2000
LONGER = 5000
#: Earlier turns of the conversation it is reminded of.
KEEP_TURNS = 8
TOO_LONG = "That took too many steps, so I stopped. Anything changed so far is listed above."
NUDGE = "Reply with the one JSON object only."
#: Seconds before asking again when a model failed: a rate limit is usually gone by then.
PAUSE = 2.0


class NoModel(Exception):
    """No model could be asked."""


def _specs() -> list:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
            for t in apptools.TOOLS]


def _signature(tool: dict) -> str:
    schema = tool["inputSchema"]
    needed = schema.get("required") or []
    args = ", ".join(a if a in needed else f"{a}?" for a in schema.get("properties", {}))
    return f"- {tool['name']}({args}): {tool['description']}"


_RULES = """- Search first. Only change keys that search_settings gave you. Values go as text.
- Change only what they asked for. If what they want is unclear, ask.
- A setting marked locked is theirs to change in Settings. Tell them so, and do not try it again.
- A new persona starts from the app's template. To give it a character, fill in its blanks with edit_persona, all in one call.
- Never say something changed unless a tool's result says it did."""


def instructions(persona_name: str = "", native: bool = True) -> str:
    scope = f"\nThey are looking at {persona_name}'s own settings, so that is what you change." if persona_name else ""
    if native:
        return f"""You help someone set up LLMSelfbot, an app that runs AI replies on their own accounts. You work in its settings and personas with your tools.

{_RULES}
- Be short and plain, in the language they wrote in, with no markdown.{scope}"""
    tools = "\n".join(_signature(t) for t in apptools.TOOLS)
    return f"""You help someone set up LLMSelfbot, an app that runs AI replies on their own accounts. You work in its settings and personas with these tools:
{tools}

Reply with exactly one JSON object and nothing around it. To use tools:
{{"do":[{{"tool":"search_settings","args":{{"query":"typing speed"}}}}]}}
When you are finished, or need to ask them something:
{{"say":"what you tell them"}}

Rules:
{_RULES}
- "say" is short and plain, in the language they wrote in, with no markdown.{scope}"""


def parse(text: str) -> dict | None:
    """The one object a turn is, from what a model really writes: fenced, with words around it, or as one bare call.
    None when there is no object in it, which from a model means it just answered."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if "tool" in data or "name" in data:
        data = {"do": [data]}
    calls = data.get("do")
    if isinstance(calls, dict):
        calls = [calls]
    if isinstance(calls, list) and calls:
        tidy = []
        for call in calls:
            if isinstance(call, dict) and (call.get("tool") or call.get("name")):
                tidy.append({"tool": str(call.get("tool") or call.get("name")),
                             "args": call.get("args") if isinstance(call.get("args"), dict) else call.get("arguments") or {}})
        return {"do": tidy} if tidy else None
    if isinstance(data.get("say"), str):
        return {"say": data["say"]}
    return None


def _call_args(raw) -> dict:
    try:
        args = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return args if isinstance(args, dict) else {}


async def _model(messages: list, native: bool) -> dict:
    """One turn from the model that writes the replies, or the next in line: {"text": ..., "calls": [...]}."""
    from app.utils import ai, providers
    from app.utils.helpers import load_config
    extra = {"tools": _specs(), "tool_choice": "auto"} if native else {}
    chain = providers.reply_chain(load_config())
    token = ai.FIRST.set({**ai.FIRST.get(), "small": chain[0]}) if chain else None
    # Someone is waiting: a rate limit hands over to the next key and model, not a sleep on this one.
    now = ai.REALTIME.set(True)
    try:
        response = await ai._create_small_completion(messages, max_tokens=LENGTH, temperature=0.2, **extra)
        if ai._out_of_room(response) and not response.choices[0].message.tool_calls:
            response = await ai._create_small_completion(messages, max_tokens=LONGER, temperature=0.2, **extra)
    except Exception as e:
        raise NoModel(str(e) or type(e).__name__) from None
    finally:
        ai.REALTIME.reset(now)
        if token is not None:
            ai.FIRST.reset(token)
    message = response.choices[0].message
    calls = [{"id": c.id, "tool": c.function.name, "args": _call_args(c.function.arguments)} for c in (message.tool_calls or [])]
    return {"text": ai._answer_of(response).strip(), "calls": calls}


def _step(name: str, args: dict, out: dict | None, error: str = "") -> dict:
    """One line for the person, for a tool that ran."""
    if error:
        return {"kind": "blocked", "text": error}
    if out and out.get("changed"):
        return {"kind": "change", "text": out.get("label") or name,
                "change": {"id": out.get("change_id"), **{k: out.get(k) for k in ("label", "for", "from", "to")}},
                "restart": bool(out.get("needs_restart"))}
    if out and out.get("undone"):
        return {"kind": "look", "text": f"Undid: {out.get('label')}"}
    if name == "search_settings":
        return {"kind": "look", "text": f"Looked up: {str(args.get('query') or '')[:60]}"}
    if name == "get_setting":
        return {"kind": "look", "text": f"Read: {(out or {}).get('label') or args.get('key')}"}
    if name in ("list_personas", "read_persona"):
        return {"kind": "look", "text": "Read the personas"}
    if name == "recent_changes":
        return {"kind": "look", "text": "Read the recent changes"}
    return {"kind": "look", "text": (out or {}).get("note") or name}


async def ask(text: str, history: list, request, persona: str = "", on_step=lambda step: None, model=None, native: bool = True) -> str:
    """Work through what they asked. Each tool that ran goes to on_step as it happens; returns what to tell them."""
    model = model or _model
    name = apptools._persona_name(persona) if persona else ""
    earlier = [t for t in (history or []) if isinstance(t, dict) and t.get("role") in ("user", "assistant")
               and isinstance(t.get("text"), str)][-KEEP_TURNS:]

    def start(with_tools: bool) -> list:
        said = [{"role": t["role"], "content": t["text"][:2000] if t["role"] == "user" or with_tools
                 else json.dumps({"say": t["text"][:2000]}, ensure_ascii=False)} for t in earlier]
        return [{"role": "system", "content": instructions(name, with_tools)}, *said, {"role": "user", "content": text}]

    async def run(call: dict, allowed: bool) -> str:
        tool, args = call["tool"], call["args"] if isinstance(call["args"], dict) else {}
        if not allowed:
            return json.dumps({"error": "Too many at once. Send that one again."})
        try:
            out = await apptools.call(tool, args, request, who=WHO, persona=persona)
        except apptools.ToolError as e:
            on_step(_step(tool, args, None, str(e)))
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        on_step(_step(tool, args, out))
        return json.dumps(out, ensure_ascii=False)[:ROOM]

    messages = start(native)
    rounds, again, nudged, ran = 0, False, False, False
    while rounds < MAX_ROUNDS:
        try:
            reply = await model(messages, native)
        except NoModel:
            if not again:
                again = True
                await asyncio.sleep(PAUSE)
                continue
            if native and not ran:      # nothing done yet: this one may just not take tools
                native, again, messages = False, False, start(False)
                continue
            raise
        rounds += 1
        again = False
        said = (reply.get("text") or "").strip()
        calls = reply.get("calls") or []
        written = None
        if not calls:
            written = parse(said)
            if written and "say" in written:
                return written["say"][:1500]
            if written:
                calls = written["do"]
            elif said:
                return said[:1500]
            elif native and not ran:
                native, messages = False, start(False)
                continue
            elif not nudged:
                nudged = True
                messages.append({"role": "user", "content": NUDGE})
                continue
            else:
                raise NoModel("The model gave no answer.")
        ran = True
        answers = [await run(call, i < MAX_CALLS) for i, call in enumerate(calls)]
        if written:
            shown = [{"tool": c["tool"], "answer": a} for c, a in zip(calls, answers)]
            messages.append({"role": "assistant", "content": said})
            messages.append({"role": "user", "content": "Results:\n" + json.dumps(shown, ensure_ascii=False)})
        else:
            messages.append({"role": "assistant", "content": said, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["tool"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                for c in calls]})
            messages.extend({"role": "tool", "tool_call_id": c["id"], "content": a} for c, a in zip(calls, answers))
    return TOO_LONG
