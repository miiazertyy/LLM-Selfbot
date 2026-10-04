"""
updater.py - update an install to the latest release, by hand.

    python scripts/updater.py

This used to download a zip from the release and swap folders, but releases
stopped carrying a zip: each device has its own file on them now (the Windows
installer and exe, the Linux and macOS binaries, the Android APK, the iPhone
IPA). The work lives in app/core/update.py, which knows which file is this
device's and how to put it in place; this only runs it. The app itself does
the same from System, Updates, and from `LLMSelfbot --role updater`.

DATA_DIR is never touched, so config, the database and pictures survive.
"""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.core import update
    print(f"[Updater] {update.run(wait=True)}", flush=True)


if __name__ == "__main__":
    main()
