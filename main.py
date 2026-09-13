"""
main.py - Launcher for the LLMSelfbot (source checkouts).

  python main.py                              → supervisor + web control panel
  python main.py discord | snapchat | both    → legacy: platforms only, no panel
  python main.py --role discord --account N   → one Discord account worker
  python main.py --role snapchat --account N  → one Snapchat worker
  python main.py --role telegram              → Telegram controller worker
  python main.py --role updater               → download + apply the latest release

Argument handling lives in app/cli.py so the frozen exe (app/desktop.py) shares
exactly the same dispatch.
"""

import multiprocessing
multiprocessing.freeze_support()

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import cli   # importing it installs the stdout/stderr sink


def main():
    if not cli.run():
        # No role, no legacy mode → run the supervisor headlessly.
        cli.run(["--no-window"])


if __name__ == "__main__":
    main()
