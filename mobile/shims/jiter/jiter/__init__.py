"""A stand-in for jiter, for the phone apps.

jiter is a JSON parser written in Rust that the openai package imports, and
nobody builds it for Android or iOS. openai only uses it to read structured
output and tool arguments while they are still streaming in, which this app
never asks for, so the standard library's json does the job here: a whole
document parses as usual, and a partial one as much of it as can be closed off.
"""
import json

__version__ = "0.99.0"


class LosslessFloat(float):
    """jiter keeps a float's exact digits; here it is simply a float."""


def from_json(json_data, *, allow_inf_nan=True, cache_mode=True, partial_mode=False,
              catch_duplicate_keys=False, float_mode="float"):
    text = json_data.decode("utf-8") if isinstance(json_data, (bytes, bytearray)) else str(json_data)
    try:
        return json.loads(text)
    except ValueError:
        if not partial_mode:
            raise
    return _partial(text)


def _partial(text):
    """A document cut off mid-stream, closed off: open strings and brackets shut,
    and a dangling comma, colon or key dropped until what is left parses."""
    body = text.rstrip()
    while body:
        stack = []
        in_str = False
        esc = False
        for ch in body:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch in "[{":
                stack.append("]" if ch == "[" else "}")
            elif ch in "]}" and stack:
                stack.pop()
        closed = body + ('"' if in_str else "") + "".join(reversed(stack))
        try:
            return json.loads(closed)
        except ValueError:
            body = body[:-1].rstrip()
    return None


def cache_clear():
    pass


def cache_usage():
    return 0
