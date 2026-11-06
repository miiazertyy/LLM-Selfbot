"""The requests workflow, end to end against a fake GitHub and a real git repo in a temp folder: publishing, updating
and removing one's own, refusals and why, the limits, the moderators' commands, reports and the sweep. The repo is the
app's own: everything lands on the data branch and in the community's release, and the app's main branch and issues
are never touched."""
from __future__ import annotations

import datetime as dt
import io
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_rules as rules  # noqa: E402
import fakes  # noqa: E402
import media as media_mod  # noqa: E402
import moderate  # noqa: E402
import publish  # noqa: E402
from gitrepo import Repo, seed_branch  # noqa: E402

SECRET = "test-author-key"
ALICE = {"login": "alice", "id": 111, "type": "User"}
BOB = {"login": "bob", "id": 222, "type": "User"}
MOD = {"login": "miiazertyy", "id": 156575850, "type": "User"}
OLD = {"created_at": "2020-01-01T00:00:00Z"}
L = rules.label


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = fakes.tmpdir()
        self.work = fakes.make_repo(self.tmp)
        self.main_before = fakes.main_head(self.work)
        self.gh = fakes.FakeGitHub(users={"alice": {**ALICE, **OLD}, "bob": {**BOB, **OLD},
                                          "miiazertyy": {**MOD, **OLD}})
        self.gists: dict = {}
        self.ctx = self.new_ctx()
        self.n = 0

    def tearDown(self):
        self.assertEqual(fakes.main_head(self.work), self.main_before, "the app's main branch never moves")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new_ctx(self):
        def fetch(gist, revision, dest):
            shutil.copytree(self.gists[(gist, revision)], dest)
            return dest
        return moderate.Ctx(self.gh, Repo(self.work), SECRET, fetch_gist=fetch,
                            today=lambda: dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc))

    def send(self, user, body):
        self.n += 1
        issue = self.gh.add_issue(self.n, body, user)
        moderate.handle(self.ctx, "issues", {"action": "opened", "issue": issue})
        return self.n

    def state(self, n):
        st, _ = self.gh.status(n)
        return (st or {}).get("state")

    def reasons(self, n):
        st, _ = self.gh.status(n)
        return " ".join((st or {}).get("reasons") or [])

    def comment(self, n, user, text):
        c = {"id": 9000 + n, "body": text, "user": user}
        moderate.handle(self.ctx, "issue_comment", {"issue": self.gh.issue(n), "comment": c})
        return self.gh.comments(n)[-1]["body"] if self.gh.comments(n) else ""


class Publishing(Base):
    def test_a_new_profile_goes_live(self):
        n = self.send(ALICE, fakes.request_body())
        self.assertEqual(self.state(n), "published", self.reasons(n))
        prof = json.loads((self.work / "profiles/test-pebble/profile.json").read_text(encoding="utf-8"))
        self.assertEqual(prof["version"], 1)
        self.assertEqual(prof["owner"], rules.owner_key(SECRET, 111))
        self.assertNotIn("alice", json.dumps(prof))
        self.assertEqual(prof["author"], "rockfan")
        rel = self.gh.release_by_tag(rules.RELEASE_TAG)
        self.assertTrue(rel["prerelease"], "never taken for a version of the app")
        self.assertEqual(rel["target_commitish"], rules.DATA_BRANCH)
        self.assertEqual(self.gh.asset_names(), ["test-pebble-v1.zip"])
        data = self.gh.asset("test-pebble-v1.zip")["data"]
        pkg = rules.read_zip(data, media=True)
        self.assertEqual(set(pkg), {"profile.json", "persona.txt", "settings.json", "avatar.jpg"})
        self.assertEqual(prof["package"]["sha256"], rules.sha256(data))
        self.assertEqual(self.gh.closed[n], "completed")
        self.assertIn(L("published"), self.gh.labels[n])
        self.assertIn("community-site.yml", self.gh.dispatched)
        self.assertIn("community-site.yml", self.gh.enabled, "turned back on if GitHub paused it")
        log = fakes.git("log", "--format=%an %s", "-1", cwd=self.work).stdout
        self.assertIn("github-actions[bot] Publish test-pebble v1", log)
        remote = fakes.git("log", f"origin/{rules.DATA_BRANCH}", "--format=%s", "-1", cwd=self.work).stdout
        self.assertIn("Publish test-pebble v1", remote)

    def test_the_face_keeps_nothing_hidden(self):
        self.send(ALICE, fakes.request_body())
        from PIL import Image
        face = (self.work / "profiles/test-pebble/avatar.jpg").read_bytes()
        with Image.open(io.BytesIO(face)) as im:
            self.assertEqual(im.size, (256, 256))
            self.assertFalse(im.getexif())

    def test_its_author_updates_it(self):
        self.send(ALICE, fakes.request_body())
        n = self.send(ALICE, fakes.request_body("update", files=fakes.core_files(note="Calmer now")))
        self.assertEqual(self.state(n), "published", self.reasons(n))
        prof = json.loads((self.work / "profiles/test-pebble/profile.json").read_text(encoding="utf-8"))
        self.assertEqual(prof["version"], 2)
        self.assertEqual(prof["changelog"][0], {"version": 2, "date": prof["changelog"][0]["date"], "note": "Calmer now"})
        self.assertEqual(self.gh.asset_names(), ["test-pebble-v1.zip", "test-pebble-v2.zip"])

    def test_older_versions_go_but_their_downloads_stay(self):
        self.send(ALICE, fakes.request_body())
        self.gh.asset("test-pebble-v1.zip")["download_count"] = 12
        self.send(ALICE, fakes.request_body("update", files=fakes.core_files(note="Two")))
        self.gh.asset("test-pebble-v2.zip")["download_count"] = 30
        n = self.send(ALICE, fakes.request_body("update", files=fakes.core_files(note="Three")))
        self.assertEqual(self.state(n), "published", self.reasons(n))
        self.assertEqual(self.gh.asset_names(), ["test-pebble-v2.zip", "test-pebble-v3.zip"],
                         "the last two versions are kept, so an older catalog can still download")
        prof = json.loads((self.work / "profiles/test-pebble/profile.json").read_text(encoding="utf-8"))
        self.assertEqual(prof["earlier"], {"1": 12})
        n = self.send(ALICE, fakes.request_body("update", files=fakes.core_files(note="Four")))
        prof = json.loads((self.work / "profiles/test-pebble/profile.json").read_text(encoding="utf-8"))
        self.assertEqual(prof["earlier"], {"1": 12, "2": 30})
        self.assertEqual(self.gh.asset_names(), ["test-pebble-v3.zip", "test-pebble-v4.zip"])

    def test_the_app_it_was_made_with(self):
        def made():
            return json.loads((self.work / "profiles/test-pebble/profile.json").read_text(encoding="utf-8"))["app"]
        n = self.send(ALICE, fakes.request_body(app="v1.6.0-beta.2"))
        self.assertEqual(made(), "1.6.0")
        self.assertIn("made with app 1.6.0", self.gh.status(n)[1])
        self.send(ALICE, fakes.request_body("update", files=fakes.core_files(note="Later"), app="99.0.0"))
        self.assertEqual(made(), "1.7.1", "never newer than the newest release there is")
        self.send(ALICE, fakes.request_body("update", files=fakes.core_files(note="Dev"), app="0.0.0-dev"))
        self.assertEqual(made(), "", "a development build tells nobody anything")

    def test_profiles_share_one_release(self):
        self.send(ALICE, fakes.request_body())
        self.send(BOB, fakes.request_body(slug="sunny-days", name="Sunny"))
        self.assertEqual(list(self.gh.releases_by_tag), [rules.RELEASE_TAG])
        self.assertEqual(self.gh.asset_names(), ["sunny-days-v1.zip", "test-pebble-v1.zip"])

    def test_nobody_else_can_update_or_remove_it(self):
        self.send(ALICE, fakes.request_body())
        n = self.send(BOB, fakes.request_body("update"))
        self.assertEqual((self.state(n), self.reasons(n)), ("refused", "It isn't yours."))
        n = self.send(BOB, fakes.request_body("remove"))
        self.assertEqual((self.state(n), self.reasons(n)), ("refused", "It isn't yours."))
        n = self.send(BOB, fakes.request_body())
        self.assertIn("taken", self.reasons(n))
        self.assertTrue((self.work / "profiles/test-pebble").is_dir())

    def test_its_author_removes_it(self):
        self.send(ALICE, fakes.request_body())
        self.send(BOB, fakes.request_body(slug="sunny-days", name="Sunny"))
        n = self.send(ALICE, fakes.request_body("remove"))
        self.assertEqual(self.state(n), "removed")
        self.assertFalse((self.work / "profiles/test-pebble").exists())
        self.assertEqual(self.gh.asset_names(), ["sunny-days-v1.zip"], "only its own files go")
        retired = json.loads((self.work / "retired.json").read_text(encoding="utf-8"))
        self.assertEqual(retired["test-pebble"]["reason"], "removed")
        n = self.send(BOB, fakes.request_body())
        self.assertIn("used before", self.reasons(n))
        n = self.send(ALICE, fakes.request_body())
        self.assertEqual(self.state(n), "published", self.reasons(n))
        prof = json.loads((self.work / "profiles/test-pebble/profile.json").read_text(encoding="utf-8"))
        self.assertEqual(prof["version"], 2, "a name used again keeps counting, so no file name repeats")

    def test_twice_is_once(self):
        n = self.send(ALICE, fakes.request_body())
        before = len(self.gh.comments(n))
        moderate.process_request(self.ctx, self.gh.issue(n))
        self.gh.issue(n)["state"] = "open"
        moderate.process_request(self.ctx, self.gh.issue(n))
        self.assertEqual(len(self.gh.comments(n)), before)
        self.assertEqual(self.gh.asset_names(), ["test-pebble-v1.zip"])


class Refusals(Base):
    def refused(self, body, user=ALICE):
        n = self.send(user, body)
        self.assertEqual(self.state(n), "refused")
        self.assertEqual(self.gh.closed[n], "not_planned")
        self.assertIn(L("refused"), self.gh.labels[n])
        return self.reasons(n)

    def test_links_and_contacts_in_the_text(self):
        for bad, word in (("join discord.gg/abcd now", "invite"), ("see example.com", "link"),
                          ("mail me@site.com", "email"), ("call +33 6 12 34 56 78", "phone"),
                          ("send it to my cashapp", "money"), ("tell me your password", "password")):
            text = fakes.TEXT + " " + bad
            why = self.refused(fakes.request_body(files=fakes.core_files(text=text)))
            self.assertIn(word.split()[0], why.lower() if word != "password" else why.lower(), why)

    def test_text_too_short_and_blanks(self):
        self.assertIn("too short", self.refused(fakes.request_body(files=fakes.core_files(text="hi"))))
        why = self.refused(fakes.request_body(files=fakes.core_files(text=fakes.TEXT + " [HOBBIES - games]")))
        self.assertIn("blank", why)

    def test_settings_outside_the_list(self):
        why = self.refused(fakes.request_body(files=fakes.core_files(settings={"bot.groq_models": ["x"]})))
        self.assertIn("can't be shared", why)
        why = self.refused(fakes.request_body(files=fakes.core_files(settings={"bot.typo_chance": 0.9})))
        self.assertIn("bot.typo_chance", why)
        why = self.refused(fakes.request_body(files=fakes.core_files(settings={"bot.trigger": "hi"})))
        self.assertIn("common word", why)

    def test_a_damaged_or_foreign_body(self):
        self.assertIn("damaged", self.refused("<!-- llmselfbot:request {nope} -->"))
        body = fakes.request_body().replace("llmselfbot:package\n", "llmselfbot:package\nAAAA")
        self.assertTrue(self.refused(body))
        hostile = fakes.request_body(files=fakes.core_files(name="$(rm -rf ~) `id`", text=fakes.TEXT + " ;rm -rf /"))
        n = self.send(ALICE, hostile)
        self.assertIn(self.state(n), ("published", "refused"))

    def test_banned_words(self):
        self.ctx.config["banned_words"] = ["geodes"]
        self.assertIn("isn't allowed here", self.refused(fakes.request_body()))

    def test_the_limits(self):
        self.gh.users["alice"]["created_at"] = "2026-10-08T00:00:00Z"
        self.assertIn("too new", self.refused(fakes.request_body()))
        self.gh.users["alice"]["created_at"] = OLD["created_at"]
        self.ctx.config["submissions_open"] = False
        self.assertIn("paused", self.refused(fakes.request_body()))
        self.ctx.config["submissions_open"] = True
        self.ctx.config["limits"]["requests_per_day"] = 1
        self.send(ALICE, fakes.request_body())
        self.assertIn("a lot today", self.refused(fakes.request_body(slug="another-one", name="Another")))

    def test_a_banned_author(self):
        self.ctx.config["banned"] = [{"key": rules.owner_key(SECRET, 111)}]
        self.assertEqual(self.refused(fakes.request_body()), "You can't send profiles here.")


class Media(Base):
    def gist(self, files, revision="a" * 40):
        gid = "f" * 32
        folder = self.tmp / "gist"
        manifest = fakes.gist_from(files, folder)
        self.gists[(gid, revision)] = folder
        return {"gist": gid, "revision": revision, "files": manifest}

    def test_pictures_come_clean(self):
        media = self.gist({"m01.jpg": fakes.picture_bytes(), "m02.jpg": fakes.picture_bytes((10, 200, 90))})
        n = self.send(ALICE, fakes.request_body(media=media))
        self.assertEqual(self.state(n), "published", self.reasons(n))
        pkg = rules.read_zip(self.gh.asset("test-pebble-v1.zip")["data"], media=True)
        self.assertEqual(sorted(k for k in pkg if k.startswith("media/")), ["media/m01.jpg", "media/m02.jpg"])
        from PIL import Image
        with Image.open(io.BytesIO(pkg["media/m01.jpg"])) as im:
            self.assertFalse(im.getexif(), "no EXIF, no GPS")
        self.assertTrue((self.work / "profiles/test-pebble/thumbs/m01.jpg").is_file())

    def test_a_picture_that_doesnt_match(self):
        media = self.gist({"m01.jpg": fakes.picture_bytes()})
        media["files"][0]["sha256"] = "0" * 64
        n = self.send(ALICE, fakes.request_body(media=media))
        self.assertIn("doesn't match", self.reasons(n))

    @unittest.skipUnless(media_mod.ffmpeg_ready(), "needs ffmpeg")
    def test_a_short_video(self):
        import subprocess
        clip = self.tmp / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=2",
                        "-metadata", "location=+48.8+002.3/", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip)],
                       check=True)
        media = self.gist({"m01.mp4": clip.read_bytes()})
        media["files"][0]["seconds"] = 2.0
        n = self.send(ALICE, fakes.request_body(media=media))
        self.assertEqual(self.state(n), "published", self.reasons(n))
        prof = json.loads((self.work / "profiles/test-pebble/profile.json").read_text(encoding="utf-8"))
        self.assertEqual(prof["media"][0]["kind"], "video")
        self.assertTrue((self.work / "profiles/test-pebble/thumbs/m01.jpg").is_file())
        data = rules.read_zip(self.gh.asset("test-pebble-v1.zip")["data"], media=True)["media/m01.mp4"]
        self.assertNotIn(b"+48.8+002.3", data, "no location left in the video")


class Moderators(Base):
    def setUp(self):
        super().setUp()
        self.live = self.send(ALICE, fakes.request_body())

    def test_takedown_and_restore(self):
        reply = self.comment(self.live, MOD, "/takedown test-pebble spam")
        self.assertIn("Taken down", reply)
        self.assertFalse((self.work / "profiles/test-pebble").exists())
        self.assertEqual(self.gh.asset_names(), ["test-pebble-v1.zip"], "kept, so it can come back")
        self.assertIn(L("takedown"), self.gh.labels[self.live])
        self.assertEqual(json.loads((self.work / "retired.json").read_text())["test-pebble"]["reason"], "takedown")
        n = self.send(ALICE, fakes.request_body())
        self.assertIn("used before", self.reasons(n), "taken down stays down, even for its author")
        reply = self.comment(self.live, MOD, "/restore test-pebble")
        self.assertIn("Restored", reply)
        self.assertTrue((self.work / "profiles/test-pebble/profile.json").is_file())

    def test_only_moderators(self):
        self.comment(self.live, BOB, "/takedown test-pebble")
        self.assertTrue((self.work / "profiles/test-pebble").is_dir())
        self.comment(self.live, BOB, "/ban test-pebble")
        self.assertFalse(self.ctx.config.get("banned"))

    def test_only_on_the_communitys_issues(self):
        self.n += 1
        bug = self.gh.add_issue(self.n, "The app crashes when I open Settings.", BOB, labels=["bug"])
        before = len(self.gh.comments(bug["number"]))
        self.comment(bug["number"], MOD, "/close")
        self.comment(bug["number"], MOD, "/takedown test-pebble")
        self.assertIsNot(self.ctx.config.get("submissions_open"), False, "a /close on an app issue pauses nothing")
        self.assertTrue((self.work / "profiles/test-pebble").is_dir())
        self.assertEqual(len(self.gh.comments(bug["number"])), before, "and nothing is said there")
        self.n += 1
        log = self.gh.add_issue(self.n, "<!-- llmselfbot:modlog -->\nModeration commands.", MOD, state="closed")
        self.assertIn("Sending is paused", self.comment(log["number"], MOD, "/close"))

    def test_ban_and_unban(self):
        reply = self.comment(self.live, MOD, "/ban test-pebble scams")
        self.assertIn("Banned", reply)
        self.assertIn("test-pebble", reply)
        self.assertFalse((self.work / "profiles/test-pebble").exists())
        n = self.send(ALICE, fakes.request_body(slug="new-one", name="New one"))
        self.assertEqual(self.reasons(n), "You can't send profiles here.")
        self.comment(self.live, MOD, "/unban @alice")
        self.assertFalse(self.ctx.config["banned"])

    def test_pause_sending(self):
        self.comment(self.live, MOD, "/close")
        self.assertFalse(self.ctx.config["submissions_open"])
        cfg = json.loads((self.work / "community.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["submissions_open"])
        self.comment(self.live, MOD, "/open")
        self.assertTrue(self.ctx.config["submissions_open"])

    def test_recheck_by_its_author(self):
        self.gh.issue(self.live)["state"] = "open"
        reply = self.comment(self.live, ALICE, "/recheck")
        self.assertIn("Checked again", reply)

    def test_moderators_by_permission_when_none_are_listed(self):
        self.ctx.config["moderators"] = []
        self.gh.perms["carol"] = "admin"
        self.assertTrue(self.ctx.is_moderator({"login": "carol", "id": 5}))
        self.assertFalse(self.ctx.is_moderator({"login": "bob", "id": 222}))


class Reports(Base):
    def test_a_report_is_acknowledged_once(self):
        self.send(ALICE, fakes.request_body())
        body = "### Which profile\n\ntest-pebble\n\n### Why\n\nA scam or a trick"
        self.n += 1
        issue = self.gh.add_issue(self.n, body, BOB, labels=[L("report")])
        moderate.handle(self.ctx, "issues", {"issue": issue})
        moderate.handle(self.ctx, "issues", {"issue": issue})
        self.assertIn(L("report"), self.gh.labels[self.n])
        self.assertEqual(len(self.gh.comments(self.n)), 1)
        self.assertIn("Pebble", self.gh.comments(self.n)[0]["body"])
        self.assertTrue((self.work / "profiles/test-pebble").is_dir(), "a report changes nothing on its own")

    def test_the_apps_own_issues_are_left_alone(self):
        self.n += 1
        issue = self.gh.add_issue(self.n, "Snapchat won't log in.", BOB, labels=["bug"])
        moderate.handle(self.ctx, "issues", {"issue": issue})
        self.assertFalse(self.gh.comments(self.n))
        self.assertFalse(self.gh.labels.get(self.n))


class Sweep(Base):
    def test_the_sweep_finishes_what_an_event_missed(self):
        self.n += 1
        self.gh.add_issue(self.n, fakes.request_body(), ALICE)
        self.n += 1
        self.gh.add_issue(self.n, "An app bug, open.", BOB)
        moderate.handle(self.ctx, "workflow_dispatch", {})
        self.assertEqual(self.state(self.n - 1), "published")
        self.assertFalse(self.gh.comments(self.n))


class DataBranch(Base):
    def test_made_once_from_the_seed(self):
        app = fakes.app_checkout(self.work)
        files_before = sorted(p.name for p in app.iterdir())
        self.assertFalse(seed_branch(app, fakes.SEED), "there already: left as it is")
        self.assertEqual(sorted(p.name for p in app.iterdir()), files_before, "the app's checkout isn't touched")
        self.assertEqual(fakes.git("status", "--porcelain", cwd=app).stdout, "")
        cfg = json.loads((self.work / "community.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["moderators"], [156575850])
        files = fakes.git("ls-tree", "-r", "--name-only", "HEAD", cwd=self.work).stdout.split()
        self.assertEqual(sorted(files), ["README.md", "community.json", "profiles/.gitkeep", "retired.json",
                                         "stats/history.json"])
        ours = fakes.git("rev-list", "HEAD", cwd=self.work).stdout.split()
        apps = fakes.git("rev-list", "origin/main", cwd=self.work).stdout.split()
        self.assertTrue(ours and apps and not set(ours) & set(apps), "it shares no history with the app")

    def test_never_the_apps_branch(self):
        with self.assertRaises(ValueError):
            Repo(self.work, branch="main")
        with self.assertRaises(ValueError):
            seed_branch(fakes.app_checkout(self.work), fakes.SEED, branch="main")

    def test_a_run_that_loses_the_race(self):
        import gitrepo
        import os
        app = fakes.app_checkout(self.work)
        head = fakes.git("ls-remote", "origin", f"refs/heads/{rules.DATA_BRANCH}", cwd=app).stdout.split()[0]
        real, asked = gitrepo._exists, []
        gitrepo._exists = lambda *a: real(*a) if asked.append(1) or len(asked) > 1 else False
        # Another moment, so another commit: two runs in the same second make the very same commit, and that one push
        # is simply nothing to do (the branch is right either way).
        dates = {k: os.environ.get(k) for k in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE")}
        os.environ.update({k: "2001-01-01T00:00:00Z" for k in dates})
        try:
            self.assertFalse(seed_branch(app, fakes.SEED), "another run made it first: that's fine")
        finally:
            gitrepo._exists = real
            for k, v in dates.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(fakes.git("ls-remote", "origin", f"refs/heads/{rules.DATA_BRANCH}", cwd=app).stdout.split()[0],
                         head, "and what it made stays")


if __name__ == "__main__":
    unittest.main()
