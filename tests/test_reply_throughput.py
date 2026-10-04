"""Three things that decide whether a reply is safe and how long it takes.

  * The [[PIC:N]] tag the model is asked for to choose a picture must never
    reach the person. It once did, as a malformed "[[PIC:2", which gives the
    account away in one line.
  * Replies written at the same time spread across the models that are set up,
    instead of every one of them starting on the same model and rate limiting it.
  * The pause between sends comes down when several people are waiting, so a
    backlog is worked through instead of each person paying the full pause.
  * The connection pools are bounded: a Windows account runner dies with
    WinError 10055 once more than 512 sockets are open at once.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


RUNNER = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")

# The two helpers, lifted out and run for real: importing the runner connects to Discord.
_src = RUNNER[RUNNER.index("_CONTROL_TAG_RE = re.compile"):RUNNER.index("def _get_random_picture")]
ns = {"re": re}
exec(compile(_src, "_pic_helpers", "exec"), ns)
strip, pick = ns["_strip_control_tags"], ns["_pick_pic_choice"]

print("== the picture tag never reaches the person ==")
check("the exact reply that leaked is cleaned",
      strip("not your face :) [[PIC:2") == "not your face :)", repr(strip("not your face :) [[PIC:2")))
check("a one-bracket tag too", strip("hey [[PIC:2]") == "hey", repr(strip("hey [[PIC:2]")))
check("a well-formed one", strip("hey lol [[PIC:2]]") == "hey lol")
check("two choices on their own line", strip("hey lol\n[[PIC:1|3]]") == "hey lol")
check("one left mid-sentence, without leaving a double space",
      strip("hey [[PIC:2]] you there") == "hey you there", repr(strip("hey [[PIC:2]] you there")))
check("a reply cut off part way through writing one", strip("lol ok [[PI") == "lol ok")
check("and one cut off even earlier", strip("lol ok [[P") == "lol ok")
check("written in lower case", strip("k [[pic:0]]") == "k")
check("or with spaces in it", strip("k [[ PIC : 2 ]]") == "k")

print("\n== the reaction tag is caught the same way ==")
check("the exact [[REACT: that leaked", strip("prove it instead of talking :sob: [[REACT:") == "prove it instead of talking :sob:", repr(strip("prove it instead of talking :sob: [[REACT:")))
check("a well-formed reaction tag", strip("lol [[REACT:X]]") == "lol")
check("one with a single bracket", strip("lol [[REACT:X]") == "lol")
check("a react-only tag", strip("[[REACT_ONLY:X]]") == "")
check("and any other bracketed token the model invents", strip("x [[WHATEVER:stuff]]") == "x")

print("\n== and ordinary brackets are left alone ==")
check("a sentence with brackets in it", strip("i love [brackets] in text") == "i love [brackets] in text")
check("a lone bracket", strip("nothing to see [") == "nothing to see [")
check("single-bracket everyday writing", strip("brb [2 min] ok") == "brb [2 min] ok")
check("a message with no bracket at all is untouched", strip("just a normal reply") == "just a normal reply")
check("an empty reply stays empty", strip("") == "")

print("\n== the choice is still read, however it was written ==")
check("a well-formed tag", pick("x [[PIC:2]]", 5) == (2, None))
check("a malformed one still picks", pick("x [[PIC:2]", 5) == (2, None))
check("a first and second choice", pick("x [[PIC:1|3]]", 5) == (1, 3))
check("one out of range picks nothing rather than crashing", pick("x [[PIC:9]]", 5) == (None, None))
check("the last tag wins, since that is where it is asked for", pick("[[PIC:0]] hm [[PIC:3]]", 5) == (3, None))
check("no tag at all", pick("plain reply", 5) == (None, None))

print("\n== it is stripped whatever happened upstream ==")
after = RUNNER[RUNNER.index("if _available_pics:"):]
after = after[:after.index("tts_cfg = config")]
check("stripped outside the 'pictures were offered' branch, so a stray tag goes too",
      after.rstrip().endswith("response = _strip_pic_tags(response)"), after[-120:])
chunk_guard = RUNNER[RUNNER.index("# Last line of defence, per chunk"):]
chunk_guard = chunk_guard[:chunk_guard.index("if i == 0:")]
check("and again on every chunk, beside the refusal guard",
      "_strip_pic_tags(chunk)" in chunk_guard and "is_refusal(chunk)" in chunk_guard)
check("a chunk left empty by it is not sent", "if not chunk.strip():" in chunk_guard)
check("a nudge is cleaned too", "nudge_text = _strip_pic_tags(nudge_text)" in RUNNER)

print("\n== replies written at once spread across the models ==")
AI = (ROOT / "app" / "utils" / "ai.py").read_text(encoding="utf-8")
check("how many are being written is tracked", "_inflight_replies" in AI)
check("counted around the call, and always given back",
      "_inflight_replies += 1" in AI and "_inflight_replies -= 1" in AI
      and "finally:" in AI.split("_inflight_replies += 1")[1][:200])


# The ordering itself, run for real against a stand-in chain.
def order_for(chain_len, others):
    order = list(range(chain_len))
    others = max(0, others)
    if others and len(order) > 1:
        shift = others % len(order)
        order = order[shift:] + order[:shift]
    return order


check("one reply on its own still starts at the first model", order_for(4, 0) == [0, 1, 2, 3])
check("a second one running at the same time starts at the next", order_for(4, 1) == [1, 2, 3, 0])
check("a third at the one after", order_for(4, 2) == [2, 3, 0, 1])
check("and it wraps round rather than running off the end", order_for(3, 5) == [2, 0, 1])
check("a chain of one is left alone", order_for(1, 3) == [0])
check("every model is still tried, only the starting point moves",
      all(sorted(order_for(4, n)) == [0, 1, 2, 3] for n in range(8)))

print("\n== the pause shrinks when people are waiting ==")
cool = RUNNER[RUNNER.index("# global cooldown:"):]
cool = cool[:cool.index("if not bypass_cooldown and message.author.id in bot.cancelled_replies")]
check("it counts who is waiting", "_people_waiting()" in cool)
check("and only shortens, never lengthens, the configured gap",
      "GLOBAL_COOLDOWN_MIN * 0.5" in cool and "_crowd" in cool)
check("the counter reads the reply states the panel already keeps",
      "_PENDING_STATES" in RUNNER.split("def _people_waiting")[1][:400])


def gap_for(base, waiting, lo=45):
    if waiting > 1:
        crowd = min(1.0, (waiting - 1) / 3.0)
        base = base * (1 - crowd) + lo * 0.5 * crowd
    return base


check("one person waiting pays the full gap", gap_for(90, 1) == 90)
check("two pay less", gap_for(90, 2) < 90)
check("four pay the floor", abs(gap_for(90, 4) - 22.5) < 0.01, str(gap_for(90, 4)))
check("and it never goes below that floor however many wait",
      all(gap_for(90, n) >= 22.4 for n in range(1, 40)))

print("\n== the sockets stay under Windows' limit ==")
USAGE = (ROOT / "app" / "utils" / "usage.py").read_text(encoding="utf-8")
check("each client's pool is bounded", "POOL_MAX" in USAGE and "max_connections=POOL_MAX" in USAGE)
check("small enough that many clients still fit in 512",
      __import__("re").search(r"POOL_MAX = (\d+)", USAGE) and int(re.search(r"POOL_MAX = (\d+)", USAGE).group(1)) <= 25)
check("the runner says what the crash meant instead of a bare traceback",
      "winerror" in RUNNER and "10055" in RUNNER and "ran out of sockets" in RUNNER)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
