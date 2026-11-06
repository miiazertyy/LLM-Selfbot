"""Careful mode and the stealth tweaks (app/utils/stealth.py) (2026-11-05).

What is checked: the mode's own logic (dates, clamping), the jitter that de-fixed-intervals every poll,
the environment pass that paces a browser runner down and turns its public actions off, and the rows
the System page's "Under the radar" section shows. Nothing here touches any platform.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import stealth  # noqa: E402


def cfg(block):
    return {"bot": {"conservative": block}}


print("== careful mode ==")
check("off by default", stealth.conservative(cfg({}))["on"] is False)
future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
check("on until a future date", stealth.conservative(cfg({"enabled": True, "until": future}))["on"] is True)
check("and says until when", stealth.conservative(cfg({"enabled": True, "until": future}))["until"] == future)
check("off by itself once the date passes", stealth.conservative(cfg({"enabled": True, "until": past}))["on"] is False)
check("on with no date until switched off", stealth.conservative(cfg({"enabled": True}))["on"] is True)
check("a date it cannot read does not turn it off",
      stealth.conservative(cfg({"enabled": True, "until": "not-a-date"}))["on"] is True)
check("scales are clamped to their range",
      stealth.conservative(cfg({"enabled": True, "reply_scale": 0.001, "wait_scale": 99}))["reply_scale"] >= 0.05
      and stealth.conservative(cfg({"enabled": True, "wait_scale": 99}))["wait_scale"] <= 4.0)
check("quiet() follows the mode", stealth.quiet(cfg({"enabled": True})) is True
      and stealth.quiet(cfg({})) is False)

print("== jitter and pace ==")
seen = {stealth.jitter(10000) for _ in range(30)}
check("jitter wanders", len(seen) > 10)
check("and stays inside \u00b112%", all(8800 <= v <= 11200 for v in seen))
check("never below half a second", stealth.jitter(100, pct=99) >= 500)
p = stealth.pace(10000, cfg({"enabled": True, "wait_scale": 1.5}))
check("careful pace stretches the wait", p >= 10000 * 1.5 * 0.88)
r = stealth.rate(20, cfg({"enabled": True, "reply_scale": 0.4}))
check("careful rate scales sends per hour down", r == 8)
check("and never below one", stealth.rate(2, cfg({"enabled": True, "reply_scale": 0.05})) >= 1)

print("== the environment pass ==")
env = {
    "TIKTOK_POLL_INTERVAL_MS": "10000",
    "TIKTOK_RELOAD_INTERVAL_MS": "20000",
    "TIKTOK_MAX_SENDS_PER_HOUR": "20",
    "TIKTOK_MIN_SEND_GAP_MS": "30000",
    "TIKTOK_MAX_SEND_GAP_MS": "45000",
    "TIKTOK_COMMENTS": "true",
    "TIKTOK_LIKE_SENT": "true",
    "TIKTOK_FOLLOW_BACK": "true",
    "TIKTOK_WATCH": "true",
    "TIKTOK_HEADLESS": "false",
    "TIKTOK_QUIET_HOURS": "2-6",
    "TIKTOK_LOCALE": "en-US",
}
out = stealth.tone_down_env(dict(env), cfg({}))
check("polls are jittered even without careful mode",
      8800 <= int(out["TIKTOK_POLL_INTERVAL_MS"]) <= 11200
      and 17600 <= int(out["TIKTOK_RELOAD_INTERVAL_MS"]) <= 22400)
check("and nothing else is touched", out["TIKTOK_MAX_SENDS_PER_HOUR"] == "20"
      and out["TIKTOK_COMMENTS"] == "true")

out = stealth.tone_down_env(dict(env), cfg({"enabled": True, "reply_scale": 0.4, "wait_scale": 1.5}))
check("sends per hour scaled down", int(out["TIKTOK_MAX_SENDS_PER_HOUR"]) == 8)
check("send gaps stretched", int(out["TIKTOK_MIN_SEND_GAP_MS"]) >= 45000
      and int(out["TIKTOK_MAX_SEND_GAP_MS"]) >= 67500)
check("public actions forced off", out["TIKTOK_COMMENTS"] == "false" and out["TIKTOK_LIKE_SENT"] == "false"
      and out["TIKTOK_FOLLOW_BACK"] == "false")
check("passive reading stays on", out["TIKTOK_WATCH"] == "true")
check("quiet hours and locale untouched", out["TIKTOK_QUIET_HOURS"] == "2-6"
      and out["TIKTOK_LOCALE"] == "en-US")

print("== the report ==")
rows = {r["name"]: r for r in stealth.report({"bot": {"calls": {"enabled": False}, "conservative": {}},
                                             "tiktok": {"headless": False}, "instagram": {},
                                             "snapchat": {}, "x": {}, "reddit": {}})}
check("careful mode off is called out", rows["Careful mode"]["ok"] is False)
check("  and says where to turn it on", rows["Careful mode"]["where"] == ["ai/careful"])
check("voice off reads as fine", rows["Voice channels"]["ok"] is True)
rows = {r["name"]: r for r in stealth.report({"bot": {"calls": {"enabled": True, "vc": True},
                                                      "conservative": {}},
                                             "tiktok": {"headless": True}, "instagram": {},
                                             "snapchat": {}, "x": {}, "reddit": {}})}
check("voice on reads as a risk", rows["Voice channels"]["ok"] is False)
check("a hidden browser reads as a risk", rows["Hidden browser windows"]["ok"] is False)
rows = {r["name"]: r for r in stealth.report({"bot": {"calls": {"enabled": True, "vc": True},
                                                      "conservative": {"enabled": True}},
                                             "tiktok": {"headless": True,
                                                        "engage": {"like_sent": True}}, "instagram": {},
                                             "snapchat": {}, "x": {}, "reddit": {}})}
check("careful mode on keeps public actions off by definition",
      rows["Public actions"]["ok"] is True)
check("careful mode gates voice", rows["Voice channels"]["ok"] is True)

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
