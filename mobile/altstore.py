"""An AltStore / SideStore source for the iPhone app, printed as JSON.

    python mobile/altstore.py --version 1.7.2 --ipa LLMSelfbot-ios.ipa --tag v1.7.2 > altstore.json

An iPhone app installed outside the App Store cannot update itself. AltStore
and SideStore can, from a "source": a small file listing the app and where its
newest IPA is. Each release carries this file, and the address of the latest
release's copy never changes, so a source added once keeps finding new ones:

    https://github.com/miiazertyy/LLM-Selfbot/releases/latest/download/altstore.json
"""

import argparse
import json
import os
from datetime import datetime, timezone

REPO = "miiazertyy/LLM-Selfbot"
BUNDLE = "io.github.miiazertyy.llmselfbot"


def source(version: str, ipa: str, tag: str) -> dict:
    return {
        "name": "LLMSelfbot",
        "identifier": BUNDLE + ".source",
        "sourceURL": f"https://github.com/{REPO}/releases/latest/download/altstore.json",
        "website": f"https://github.com/{REPO}",
        "apps": [{
            "name": "LLMSelfbot",
            "bundleIdentifier": BUNDLE,
            "developerName": "miiazertyy",
            "subtitle": "Replies to your messages as you.",
            "localizedDescription": "LLMSelfbot and its panel, running on the iPhone itself. "
                                    "Keep the app open while it replies: iOS pauses apps in the background.",
            "iconURL": f"https://raw.githubusercontent.com/{REPO}/main/resources/icon.png",
            "tintColor": "#F7A1C4",
            "versions": [{
                "version": version,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "downloadURL": f"https://github.com/{REPO}/releases/download/{tag}/{os.path.basename(ipa)}",
                "size": os.path.getsize(ipa),
                "minOSVersion": "13.0",
            }],
        }],
        "news": [],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--ipa", required=True)
    ap.add_argument("--tag", required=True, help="the release's tag, for the download address")
    args = ap.parse_args()
    print(json.dumps(source(args.version.lstrip("vV"), args.ipa, args.tag), indent=2))


if __name__ == "__main__":
    main()
