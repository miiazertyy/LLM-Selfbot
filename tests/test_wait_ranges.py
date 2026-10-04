"""Batch waits that are a range, not just a time, each with its chance.

A wait was one number of seconds and a weight: 20s picked 30 times in 100,
40s 35 times. Now a wait can also be "any time from 40s to 90s", with its own
weight, mixed freely with the fixed ones: {time: 40, to: 90, weight: 35}.

  * the runner picks a row by weight, then a whole second across its range
  * a config with only fixed waits behaves exactly as before
  * the Discord config command shows and takes 40s-90s(35)
  * the chart draws a range as a plateau with a handle at each end, and a
    single wait can be pulled out into one, or typed as 20s-1m
"""
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fixtures import use_shipped_config
use_shipped_config()

from app.utils.behavior import pick_wait

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== the runner's pick ==")
random.seed(7)
fixed_only = [{"time": 20, "weight": 30}, {"time": 40, "weight": 70}]
got = Counter(pick_wait(fixed_only) for _ in range(5000))
check("fixed waits only: as before, just those times", set(got) == {20, 40}, str(got))
check("at their odds", 0.66 < got[40] / 5000 < 0.74, str(got[40] / 5000))

mixed = [{"time": 20, "weight": 50}, {"time": 60, "to": 120, "weight": 50}]
picks = [pick_wait(mixed) for _ in range(6000)]
ranged = [p for p in picks if p != 20]
check("a range and a fixed wait share by their weights", 0.46 < picks.count(20) / len(picks) < 0.54)
check("a range lands anywhere across it", min(ranged) == 60 and max(ranged) == 120, f"{min(ranged)}..{max(ranged)}")
check("in whole seconds", all(isinstance(p, int) for p in ranged))
check("evenly: every second of it comes up", len(set(ranged)) == 61, str(len(set(ranged))))
check("a range whose end is not past its start is just its start", pick_wait([{"time": 30, "to": 30, "weight": 1}]) == 30)
check("nothing to pick from is no wait, not a crash", pick_wait([]) == 0)
check("weights all zero still picks something", pick_wait([{"time": 9, "weight": 0}]) == 9)

runner = (ROOT / "app" / "platforms" / "discord_runner.py").read_text(encoding="utf-8")
check("the runner uses it", "return pick_wait(wait_times)" in runner and "    pick_wait," in runner)

print("\n== the Discord config command ==")
mgmt = (ROOT / "app" / "cogs" / "management.py").read_text(encoding="utf-8")
pat = re.search(r're\.fullmatch\(r"(.+?)", token', mgmt).group(1)
check("it reads a fixed wait as before", re.fullmatch(pat, "15s(30)").groups() == ("15", None, "30"))
check("and a range", re.fullmatch(pat, "40s-90s(35)").groups() == ("40", "90", "35"))
check("a range is saved with its end", 'row["to"] = int(m.group(2))' in mgmt)
check("and shown as 40s-90s(35)", """(f"-{w['to']}s" if w.get('to') and w['to'] > w['time'] else "")""" in mgmt)
tg = (ROOT / "app" / "telegram_bot" / "telegram_controller.py").read_text(encoding="utf-8")
check("the Telegram controller shows ranges too", """f"-{w['to']}s" """.strip() in tg)

print("\n== settings files take them ==")
from app.web import settings_io
current = {"bot": {"batch_wait_times": [{"time": 20, "weight": 100}]}}
plan = settings_io.plan(current, current, {"bot": {"batch_wait_times": [
    {"time": 20, "weight": 50}, {"time": 40, "to": 90, "weight": 50}]}})
check("an imported list with a range in it is accepted",
      [c["key"] for c in plan["changes"]] == ["bot.batch_wait_times"] and not plan["skipped"], str(plan)[:200])

print("\n== the chart ==")
wt = (ROOT / "webui" / "src" / "lib" / "components" / "WaitTimes.svelte").read_text(encoding="utf-8")
check("a row may carry the end of its range", "type Row = { time: number; weight: number; to?: number }" in wt)
check("and keeps it only when it is past the start", "if (isFinite(to) && to > time) row.to = to;" in wt)
check("sent back with it", "{ time: w.time, to: w.to, weight: pcts[i] }" in wt)
check("a range is drawn as a plateau across its span", 'class="wt-band"' in wt and 'class="wt-bar"' in wt)
check("with a handle at each end, and a single wait's tucked beside it",
      'class="wt-end" class:is-stub={w.to == null}' in wt and "{#each ENDS as part (part)}" in wt)
check("an end drags sideways only, against the other end", 'hold.part !== "all"' in wt and "span(hold.anchor, timeAt(p.x))" in wt)
check("pushed back into the other end it is one time again", "hi / lo < 1.08" in wt)
check("the head moves a range whole, keeping its span", "timeAt(p.x + hold.d0), timeAt(p.x + hold.d1)" in wt)
check("a range can be typed: 20s-1m, 20-40s, 1 to 2m", "function readSpan(" in wt and r"\bto\b" in wt)
check("a bare number before the dash takes the unit after it", "parts[0] + unit" in wt)
check("its odds spread across the hill", "A range spreads its odds evenly across its span" in wt)
check("the average counts a range as its middle", "((w.time + endOf(w)) / 2) * w.share" in wt)
check("and it is said in words", "between ${say(w.time, \"s\")} and ${say(w.to, \"s\")}" in wt)
check("the hint says how", "Pull its sides out for a range." in wt)

print("\n== the typing keyboard ==")
ts = (ROOT / "webui" / "src" / "lib" / "components" / "TypingSpeed.svelte").read_text(encoding="utf-8")
pad = ts.split(".ts-pad {")[1].split("}")[0]
check("no panel round it", "background" not in pad and "border" not in pad and "padding" not in pad)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
