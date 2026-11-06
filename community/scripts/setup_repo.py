"""setup_repo.py - what the community needs in the app's repo before anything else: its labels, and its data branch,
made from community/data the first time. What's already there is left as it is, so running it again does no harm.

Run by .github/workflows/community-setup.yml when that file is first pushed, and at the start of the other community
workflows, so a first run that was missed fixes itself.

    python community/scripts/setup_repo.py --labels --branch
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_rules as rules  # noqa: E402
from gitrepo import seed_branch  # noqa: E402
from moderate import LABELS  # noqa: E402

SEED = Path(__file__).resolve().parent.parent / "data"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", action="store_true", help="make the community's labels")
    ap.add_argument("--branch", action="store_true", help=f"make the {rules.DATA_BRANCH} branch")
    args = ap.parse_args(argv)
    repo = os.environ["REPO"]
    token = os.environ.get("GH_TOKEN", "")
    if args.labels:
        from ghapi import GitHub
        GitHub(token, repo).ensure_labels(LABELS)
        print("labels ready")
    if args.branch:
        # From the app's checkout this runs in: its own sign-in pushes the new branch.
        made = seed_branch(Path.cwd(), SEED, rules.DATA_BRANCH)
        print(f"{rules.DATA_BRANCH}: {'made' if made else 'already there'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
