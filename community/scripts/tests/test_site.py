"""The catalog and the stats: download counts read per version from the community's release (and the app's own
releases left out), older versions' counts kept, one history point a day that never goes down, the numbers the app
draws, and the files Pages serves."""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site  # noqa: E402
import community_rules as rules  # noqa: E402
import fakes  # noqa: E402

PAGE = fakes.ROOT / "site" / "index.html"


class Counts(unittest.TestCase):
    def test_counts_per_version_from_the_community_release_only(self):
        gh = fakes.FakeGitHub()
        rel = gh.create_release(rules.RELEASE_TAG, "Community profiles", "", prerelease=True)
        for name, c in (("juni-v1.zip", 5), ("juni-v2.zip", 7), ("mix-v2-v1.zip", 3), ("notes.txt", 99)):
            gh.upload_asset(rel, name, b"x")["download_count"] = c
        app = gh.create_release("v1.7.1", "LLMSelfbot 1.7.1", "")
        gh.upload_asset(app, "LLMSelfbot.exe", b"x")["download_count"] = 5000
        self.assertEqual(build_site.release_counts(gh), {"juni": {1: 5, 2: 7}, "mix-v2": {1: 3}})

    def test_no_release_yet(self):
        self.assertEqual(build_site.release_counts(fakes.FakeGitHub()), {})

    def test_older_versions_counted_from_the_profile(self):
        tmp = fakes.tmpdir()
        try:
            p = tmp / "profiles" / "juni"
            p.mkdir(parents=True)
            (p / "profile.json").write_text(json.dumps({"slug": "juni", "earlier": {"1": 12, "2": 30}}))
            counts = build_site.with_earlier(tmp, {"juni": {2: 31, 3: 4}})
            self.assertEqual(counts, {"juni": {1: 12, 2: 31, 3: 4}}, "a file still there counts as it is now")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class History(unittest.TestCase):
    def test_one_point_a_day_and_never_down(self):
        h = {"days": [], "profiles": {}}
        self.assertTrue(build_site.update_history(h, {"juni": {1: 3}}, "2026-10-01"))
        self.assertFalse(build_site.update_history(h, {"juni": {1: 9}}, "2026-10-01"))
        self.assertTrue(build_site.update_history(h, {"juni": {1: 8}, "mara": {1: 2}}, "2026-10-02"))
        self.assertTrue(build_site.update_history(h, {"mara": {1: 4}}, "2026-10-03"))
        self.assertEqual(h["days"], ["2026-10-01", "2026-10-02", "2026-10-03"])
        self.assertEqual(h["profiles"]["juni"], [3, 8, 8], "a removed profile keeps what it had")
        self.assertEqual(h["profiles"]["mara"], [0, 2, 4])

    def test_the_numbers_drawn(self):
        h = {"days": [f"2026-10-{d:02d}" for d in range(1, 11)], "profiles": {"juni": [0, 1, 1, 3, 6, 6, 7, 9, 9, 10]}}
        s = build_site.derive(h, {"juni": {1: 4, 2: 8}})
        juni = s["juni"]
        self.assertEqual(juni["downloads"], 12)
        self.assertEqual(juni["daily"], [1, 0, 2, 3, 0, 1, 2, 0, 1, 2])
        self.assertEqual(juni["week"], 12 - 3)
        self.assertEqual(juni["versions"], {"1": 4, "2": 8})
        self.assertEqual(s["*"]["downloads"], 12)
        self.assertEqual(s["*"]["daily"], juni["daily"])


class Keepalive(unittest.TestCase):
    def test_kept_on_and_the_sweep_four_times_a_day(self):
        for hour, sweep in ((0, True), (5, False), (6, True), (13, False), (18, True)):
            gh = fakes.FakeGitHub()
            build_site.keepalive(gh, hour)
            self.assertIn("community-site.yml", gh.enabled)
            self.assertEqual("community-requests.yml" in gh.dispatched, sweep, hour)


class Site(unittest.TestCase):
    def setUp(self):
        self.tmp = fakes.tmpdir()
        self.root = self.tmp / "data"
        shutil.copytree(fakes.SEED, self.root)
        p = self.root / "profiles" / "juni"
        files = fakes.core_files(slug="juni", name="Juni")
        p.mkdir(parents=True)
        meta = json.loads(files["profile.json"])
        meta.update({"version": 2, "owner": "k" * 32, "app": "1.7.1", "media": [{"name": "m01.jpg", "kind": "picture"}],
                     "settings": ["bot.mood.enabled"], "words": 60, "package": {"name": "juni-v2.zip", "sha256": "a" * 64,
                                                                                 "bytes": 10}})
        (p / "profile.json").write_bytes(rules.canonical_json(meta))
        (p / "persona.txt").write_bytes(files["persona.txt"])
        (p / "settings.json").write_bytes(files["settings.json"])
        (p / "avatar.jpg").write_bytes(files["avatar.jpg"])
        (p / "thumbs").mkdir()
        (p / "thumbs" / "m01.jpg").write_bytes(files["avatar.jpg"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_catalog(self):
        out = self.tmp / "_site"
        h = {"days": ["2026-10-09", "2026-10-10"], "profiles": {"juni": [1, 3]}}
        index = build_site.build(self.root, out, {"juni": {1: 1, 2: 4}}, h, "2026-10-10T12:00:00Z", PAGE)
        juni = index["profiles"][0]
        self.assertEqual((juni["slug"], juni["version"], juni["downloads"], juni["pictures"]), ("juni", 2, 5, 1))
        self.assertEqual(juni["app"], "1.7.1", "the app it was made with, beside its version")
        self.assertEqual(juni["thumbs"], ["profiles/juni/thumbs/m01.jpg"])
        self.assertNotIn("owner", juni, "who made it isn't in the catalog")
        self.assertEqual(index["totals"], {"profiles": 1, "downloads": 5, "week": 4},
                         "this week counts from the first day on record")
        for name in ("index.json", "stats.json", "meta.json", "index.html", ".nojekyll",
                     "profiles/juni/persona.txt", "profiles/juni/avatar.jpg"):
            self.assertTrue((out / name).is_file(), name)
        self.assertEqual((out / "index.html").read_bytes(), PAGE.read_bytes(), "the gallery comes from the code")
        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["settings"], sorted(rules.ALLOWED))
        self.assertEqual(meta["moderators"], [156575850])

    def test_checking_every_live_profile(self):
        self.assertEqual(build_site.check_profiles(self.root), [])
        (self.root / "profiles" / "juni" / "persona.txt").write_text("too short", encoding="utf-8")
        self.assertTrue(build_site.check_profiles(self.root))


if __name__ == "__main__":
    unittest.main()
