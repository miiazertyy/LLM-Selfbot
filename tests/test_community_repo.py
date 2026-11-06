"""Community profiles run on this repo, with no server: the scripts in community/ (requests, refusals, moderators,
reports, the site and the stats, tested against a fake GitHub and a real git repo in a temp folder), and the
Community workflows in .github/workflows, read as files: nothing from an issue ever in a shell line, each job's
permissions written out, nothing queued dropped, its secret only where it's used, the profiles on their own branch,
and the app's own issues, releases and branch left alone."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMMUNITY = ROOT / "community"
WORKFLOWS = ROOT / ".github" / "workflows"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


print("== the scripts' own tests ==")
if not shutil.which("git"):
    print("  SKIP  needs git")
else:
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests"], cwd=COMMUNITY,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-4:]
    print("  " + " | ".join(tail))
    check("community/scripts/tests pass", proc.returncode == 0, "\n".join(tail))

print("\n== the workflows ==")
flows = {p.name: (p.read_text(encoding="utf-8"), yaml.safe_load(p.read_text(encoding="utf-8")))
         for p in sorted(WORKFLOWS.glob("community-*.yml"))}
check("requests, site and setup, in this repo", set(flows) == {"community-requests.yml", "community-site.yml",
                                                               "community-setup.yml"}, sorted(flows))
check("no second repo, nothing left of the old template", not (COMMUNITY / ".github").exists()
      and not (ROOT / "scripts" / "community_sync.py").exists())
for name, (text, flow) in flows.items():
    runs = [s.get("run", "") for job in (flow.get("jobs") or {}).values() for s in job.get("steps") or []]
    check(f"{name}: nothing from an issue in a shell line", not any("github.event" in r for r in runs))
    jobs = flow.get("jobs") or {}
    check(f"{name}: each job's permissions written out", flow.get("permissions") == {}
          and all("permissions" in j for j in jobs.values()))
    check(f"{name}: no em dashes", chr(0x2014) not in text)
req = flows["community-requests.yml"][1]
site = flows["community-site.yml"][1]
setup = flows["community-setup.yml"][1]
on = req.get("on") or req.get(True)
check("requests run one after another, none dropped", req["concurrency"] == {"group": "community-write", "queue": "max"})
check("it hears new and edited requests and comments", set(on["issues"]["types"]) == {"opened", "edited", "reopened"}
      and on["issue_comment"]["types"] == ["created"] and "workflow_dispatch" in on)
check("no schedule of its own, so GitHub never pauses it", "schedule" not in on)
guard = req["jobs"]["handle"]["if"]
check("only the community's issues start a run, never the app's own", "llmselfbot:" in guard
      and "profile-report" in guard and "profile-" in guard)
site_on = site.get("on") or site.get(True)
check("the site every hour, and when its code changes", site_on["schedule"] and "workflow_dispatch" in site_on
      and all(p.startswith("community/") for p in site_on["push"]["paths"]))
setup_on = setup.get("on") or setup.get(True)
check("setup runs on its own when it's first pushed", setup_on["push"]["paths"] == [".github/workflows/community-setup.yml"])
sj = site["jobs"]
check("only the deploy job may publish Pages", sj["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
      and sj["build"]["permissions"].get("pages", "none") in ("none", "read"))
check("and it waits for Pages to be on, rather than failing every hour until it is",
      sj["deploy"].get("if") == "needs.build.outputs.pages == 'true'"
      and sj["build"]["outputs"]["pages"] == "${{ steps.pages.outputs.on }}")
check("only the requests and the site build may start or wake a workflow",
      {f"{n}:{j}" for n, (_, f) in flows.items() for j, job in (f.get("jobs") or {}).items()
       if "actions" in (job.get("permissions") or {})} == {"community-requests.yml:handle", "community-site.yml:build"})
secret_lines = [line for n, (t, _) in flows.items() for line in t.splitlines() if "secrets." in line]
check("the author key reaches only the requests step", len(secret_lines) == 1
      and "AUTHOR_KEY: ${{ secrets.AUTHOR_KEY }}" in secret_lines[0])
check("Pillow installed exactly, by hash", all("--require-hashes" in t for n, (t, _) in flows.items() if "pip install" in t))


def data_checkout(flow):
    return [s.get("with") or {} for j in flow["jobs"].values() for s in j.get("steps") or []
            if str(s.get("uses", "")).startswith("actions/checkout") and (s.get("with") or {}).get("ref")]


check("the profiles come from their own branch, beside the code", all(
    data_checkout(f) == [{"ref": "community-data", "path": "data", **({"fetch-depth": 0} if f is req else {})}]
    for f in (req, site)), [data_checkout(f) for f in (req, site)])
check("and the code is only the community's part of the repo", all(
    (s.get("with") or {}).get("sparse-checkout") == "community" for f in (req, site, setup)
    for j in f["jobs"].values() for s in j.get("steps") or []
    if str(s.get("uses", "")).startswith("actions/checkout") and not (s.get("with") or {}).get("ref")))
sys.path.insert(0, str(COMMUNITY / "scripts"))
import community_rules as script_rules  # noqa: E402
import gitrepo  # noqa: E402
check("the scripts never push to the app's branch", {"main", "master"} <= gitrepo.NEVER
      and script_rules.DATA_BRANCH not in gitrepo.NEVER)

print("\n== the forms, the data and the page ==")
report = yaml.safe_load((ROOT / ".github/ISSUE_TEMPLATE/profile-report.yml").read_text(encoding="utf-8"))
ids = [b.get("id") for b in report["body"]]
check("the Report form: which profile (prefillable), why, details", ids == ["slug", "reason", "details"]
      and report["labels"] == ["profile-report"])
check("blank issues stay open for the app's own bug reports", not (ROOT / ".github/ISSUE_TEMPLATE/config.yml").exists())
page = (COMMUNITY / "site/index.html").read_text(encoding="utf-8")
check("the web gallery puts a profile's words on the page as text only", "textContent" in page and "innerHTML" not in page
      and "insertAdjacentHTML" not in page)
cfg = json.loads((COMMUNITY / "data/community.json").read_text(encoding="utf-8"))
check("the owner is the moderator, by account number", cfg["moderators"] == [156575850])
check("sending is open, nobody banned, sensible limits", cfg["submissions_open"] is True and cfg["banned"] == []
      and cfg["limits"] == {"account_age_days": 7, "live_profiles": 10, "requests_per_day": 6})
check("the data branch starts with what the scripts read", all((COMMUNITY / "data" / p).is_file() for p in (
    "community.json", "retired.json", "stats/history.json", "profiles/.gitkeep", "README.md")))
for p in [*COMMUNITY.rglob("*.md"), COMMUNITY / "site/index.html", *COMMUNITY.glob("scripts/*.py"),
          ROOT / ".github/ISSUE_TEMPLATE/profile-report.yml"]:
    check(f"no em dashes: {p.relative_to(ROOT)}", chr(0x2014) not in p.read_text(encoding="utf-8"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
