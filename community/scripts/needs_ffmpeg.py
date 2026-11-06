"""needs_ffmpeg.py - whether this run may meet a video (exit 0) or surely not (exit 1), so ffmpeg is installed only
when it can be needed. Read from the event file, in Python, like everything else from an issue."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_rules as rules  # noqa: E402


def needs(name: str, event: dict) -> bool:
    if name in ("schedule", "workflow_dispatch"):
        return True
    if name == "issue_comment":
        return str((event.get("comment") or {}).get("body") or "").lstrip().startswith("/recheck")
    if name == "issues":
        try:
            request, _ = rules.parse_request((event.get("issue") or {}).get("body") or "")
        except ValueError:
            return False
        files = ((request.get("media") or {}).get("files")) or []
        return any(isinstance(f, dict) and f.get("kind") == "video" for f in files)
    return False


if __name__ == "__main__":
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    event = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
    sys.exit(0 if needs(os.environ.get("GITHUB_EVENT_NAME", ""), event) else 1)
