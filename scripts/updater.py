"""
updater.py - Self-updater for frozen installs.

Run as a standalone script (or via `LLMSelfbot.exe --role updater`):
  1. Downloads the latest release zip from GitHub.
  2. Extracts it to DATA_DIR/update/new/.
  3. Waits for the main exe to exit, swaps the app dir, relaunches.

DATA_DIR is never touched, so config, DB and pictures survive.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "miiazertyy/LLM-Selfbot"
STAGE = "update/staged.zip"
NEW = "update/new"


def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "portable.txt").exists():
            return exe_dir / "data"
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "LLMSelfbot"
    return Path(__file__).resolve().parent.parent


def fetch_latest_release():
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    asset = next((a for a in data.get("assets", []) if a["name"].endswith(".zip")), None)
    if not asset:
        raise RuntimeError("no zip asset on the latest release")
    return asset["browser_download_url"], data.get("tag_name", "unknown")


def download(url: str, dest: Path):
    print(f"[Updater] Downloading {url}")
    with urllib.request.urlopen(url, timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def apply_update(app_dir: Path):
    new_dir = app_dir / "new"
    backup = app_dir / "old"
    if new_dir.exists():
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        # Wait for the app to fully exit (it stops children before calling us).
        for _ in range(120):
            try:
                os.rename(app_dir / "LLMSelfbot.exe", app_dir / "LLMSelfbot.exe.locked")
                os.rename(app_dir / "LLMSelfbot.exe.locked", app_dir / "LLMSelfbot.exe")
                break
            except OSError:
                time.sleep(1)
        os.rename(app_dir, backup)
        os.rename(new_dir, app_dir)
        shutil.rmtree(backup, ignore_errors=True)
        print("[Updater] Swapped app directory.")


def main():
    data = _data_dir()
    stage = data / STAGE
    new_dir = data / NEW

    if new_dir.exists():
        apply_update(Path(sys.executable).resolve().parent)
    else:
        url, tag = fetch_latest_release()
        print(f"[Updater] Latest: {tag}")
        stage.parent.mkdir(parents=True, exist_ok=True)
        download(url, stage)
        new_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(stage) as zf:
            zf.extractall(new_dir)
        stage.unlink()
        print("[Updater] Staged, restart the app to finish the swap.")

    exe = Path(sys.executable)
    subprocess.Popen([str(exe)])


if __name__ == "__main__":
    main()
