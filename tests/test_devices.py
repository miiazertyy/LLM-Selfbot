"""Every device the app runs on, what works on each, and updating on each.

  * the app knows what it is running on (Windows, macOS, Linux on x86 or ARM,
    the Android and iPhone apps) and how it was installed, and a device can be
    pretended to with LLMSELFBOT_DEVICE so all of this can be seen here
  * what does not work on a device is said in one short sentence, and what
    works is not mentioned at all
  * updating fetches this device's own file from the release, checked against
    its size and GitHub's checksum, and puts it in place the way this copy was
    installed; the release's file names are the ones the workflow publishes
  * on a phone, accounts run on threads of the app, since a phone does not let
    an app start processes, with their output and stopping as before
  * the phone apps (mobile/) are laid out from the same app/, with the few
    packages nobody publishes for phones made by stage.py
"""
import array
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


class env:
    """Set environment variables for a block, and put them back after."""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.values}
        for k, v in self.values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


CLEAN = dict(LLMSELFBOT_DEVICE=None, LLMSELFBOT_SHELL=None, LLMSELFBOT_INPROCESS=None)

from app.utils import device, compat  # noqa: E402

print("== what it is running on ==")
with env(**CLEAN):
    here = device.detect()
    check("this machine is one of the known devices", here in device.DEVICES, here)
    check("a checkout run with Python is a source install", device.install() == "source")
    check("and updates with git", device.update_method() == "git")
    check("a computer is not a phone, and runs accounts as processes",
          not device.is_phone() and not device.single_process())
for name in device.DEVICES:
    with env(**{**CLEAN, "LLMSELFBOT_DEVICE": name}):
        ok = device.detect() == name and device.summary()["name"] == name and device.summary()["pretend"]
    check(f"it can pretend to be {name}", ok)
with env(**{**CLEAN, "LLMSELFBOT_SHELL": "android"}):
    check("the Android app says so", device.detect() == "android" and device.install() == "apk"
          and device.single_process() and device.update_method() == "download")
with env(**{**CLEAN, "LLMSELFBOT_SHELL": "ios"}):
    check("the iPhone app too", device.detect() == "ios" and device.install() == "ipa"
          and device.single_process() and device.update_method() == "sideload")
with env(**{**CLEAN, "LLMSELFBOT_INPROCESS": "1"}):
    check("accounts can be put on threads anywhere, to try it on a computer", device.single_process())
with env(**{**CLEAN, "LLMSELFBOT_DEVICE": "android"}):
    check("pretending to be a phone does not change how accounts run", not device.single_process())

print("\n== which file on a release is this device's ==")
check("the installed Windows app takes the installer", device.asset("windows-x64", "installer") == "LLMSelfbotSetup.exe")
check("the single exe takes the single exe", device.asset("windows-x64", "portable") == "LLMSelfbot-portable.exe")
check("Windows on ARM runs the x64 build", device.asset("windows-arm64", "installer") == "LLMSelfbotSetup.exe")
check("Linux on ARM takes the aarch64 binary", device.asset("linux-arm64", "binary") == "LLMSelfbot-linux-aarch64")
check("the phones take their app", device.asset("android", "apk") == "LLMSelfbot-android.apk"
      and device.asset("ios", "ipa") == "LLMSelfbot-ios.ipa")
check("a Mac on Intel has no build, and says so rather than fetching the wrong one",
      device.asset("macos-x64", "binary") is None and device.update_method("macos-x64", "binary") == "none")
check("the installed app updates with the installer, a single file by replacing it",
      device.update_method("windows-x64", "installer") == "installer"
      and device.update_method("windows-x64", "portable") == "replace"
      and device.update_method("linux-arm64", "binary") == "replace")
wf = read(".github/workflows/build-exe.yml")
missing = [a for a in device.ASSETS.values() if a not in wf]
check("every one of those names is what the workflow publishes", not missing, ", ".join(missing))
check("the workflow builds Linux on ARM64 on an ARM runner", "ubuntu-24.04-arm" in wf and "LLMSelfbot-linux-aarch64" in wf)

print("\n== what does not work where ==")
for name in ("windows-x64", "macos-arm64", "linux-x64"):
    with env(**{**CLEAN, "LLMSELFBOT_DEVICE": name}):
        rep = compat.report()
    check(f"{name}: nothing to say", not rep["missing"], json.dumps(rep["missing"])[:160])
with env(**{**CLEAN, "LLMSELFBOT_DEVICE": "linux-arm64"}):
    arm = compat.report()["missing"]
check("Linux on ARM: Snapchat needs Chromium, with the command to get it",
      set(arm) == {"snapchat"} and arm["snapchat"]["fix"]["command"] == "sudo apt install chromium")
with env(**{**CLEAN, "LLMSELFBOT_DEVICE": "android"}):
    android = compat.report()["missing"]
check("Android: no Snapchat, no AI servers, no voice, one Discord account, keep it open",
      {"snapchat", "local_start", "voice_messages", "voice_calls", "discord_many", "background",
       "browser_login", "files_pick", "files_save", "folders"} <= set(android), ", ".join(sorted(android)))
check("but Discord itself works there, and it updates", "discord" not in android and "update" not in android)
with env(**{**CLEAN, "LLMSELFBOT_DEVICE": "ios"}):
    ios = compat.report()["missing"]
check("iPhone: no Discord yet, and it cannot update itself", "discord" in ios and "update" in ios)
check("but it can pick files, and turns photos into JPEGs itself", "files_pick" not in ios and "heic" not in ios)
all_why = [m["why"] for rep in (android, ios, arm) for m in rep.values()]
check("every reason is one short sentence or two", all(len(w) <= 90 for w in all_why),
      max(all_why, key=len))
check("each has a short tag for where a sentence will not fit",
      all(len(m["tag"]) <= 18 for rep in (android, ios, arm) for m in rep.values()))
check("the tag says Needs ffmpeg rather than Not on Windows when only ffmpeg is missing",
      'tag": "Needs ffmpeg"' in read("app/utils/compat.py"))

print("\n== updating ==")
from app.core import update  # noqa: E402
old_style = {"tag": "v1.7.0", "page": "p", "assets": [
    {"name": n, "url": "u/" + n, "size": 10, "digest": ""} for n in
    ("LLMSelfbot-portable.exe", "LLMSelfbotSetup.exe", "selfbot-linux-aarch64", "selfbot-linux-x86_64",
     "selfbot-macos-arm64", "SHA256SUMS-windows.txt")]}
check("releases up to 1.7.0 named the Linux and macOS files differently, and are still found",
      update.pick(old_style, "linux-arm64", "binary")["name"] == "selfbot-linux-aarch64"
      and update.pick(old_style, "macos-arm64", "binary")["name"] == "selfbot-macos-arm64")
p = update.plan(old_style, "android", "apk", current="1.6.0")
check("a release without this device's file says so instead of offering an update",
      not p["ready"] and "no Android build" in p["why"], json.dumps(p))
p = update.plan(old_style, "windows-x64", "portable", current="1.6.0")
check("the single exe finds its file", p["ready"] and p["method"] == "replace"
      and p["asset"]["name"] == "LLMSelfbot-portable.exe")
p = update.plan(old_style, "windows-x64", "portable", current="0.0.0-dev")
check("a build made without a release tag is never replaced by a release, which may be older",
      not p["ready"] and "development build" in p["why"], json.dumps(p))
check("a source install needs no file", update.plan(old_style, "windows-x64", "source")["method"] == "git")

# A download is checked against the release's size and SHA-256.
serve_dir = Path(tempfile.mkdtemp(prefix="upd_"))
payload = os.urandom(200_000)
(serve_dir / "LLMSelfbot-linux-aarch64").write_bytes(payload)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(serve_dir), **k)

    def log_message(self, *a):
        pass


httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{httpd.server_address[1]}/LLMSelfbot-linux-aarch64"
good = {"url": url, "size": len(payload), "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}
dest = serve_dir / "out" / "new"
update.download(good, dest)
check("a download that matches is kept", dest.read_bytes() == payload and not (dest.parent / "new.part").exists())
bad = {**good, "digest": "sha256:" + "0" * 64}
try:
    update.download(bad, serve_dir / "out" / "bad")
    refused = False
except RuntimeError:
    refused = True
check("one that does not match the checksum is thrown away", refused and not (serve_dir / "out" / "bad").exists()
      and not (serve_dir / "out" / "bad.part").exists())
short = {**good, "size": len(payload) + 5}
try:
    update.download(short, serve_dir / "out" / "short")
    refused = False
except RuntimeError:
    refused = True
check("and so is one that stopped short", refused)
httpd.shutdown()
shutil.rmtree(serve_dir, ignore_errors=True)

check("paths in the installer's script are quoted, their own quotes doubled",
      update._ps(r"D:\Apps\O'Brien\LLMSelfbot.exe") == r"'D:\Apps\O''Brien\LLMSelfbot.exe'")
src = read("app/core/update.py")
check("the installer runs silently once the app has closed, then starts it again",
      "Wait-Process -Id" in src and "/VERYSILENT" in src and "Start-Process -FilePath {_ps(exe)}" in src)
check("a running exe steps aside rather than being overwritten, and comes back if the swap fails",
      'exe.with_name(exe.name + ".old")' in src and "os.replace(old, exe)" in src)
check("the new copy waits for the old one's lock rather than giving up", '"LLMSELFBOT_RESTART"' in src)
check("the phones hand the file to the phone: the APK to Android, the release page to an iPhone",
      'if method in ("download", "sideload")' in src and "device.open_url(url)" in src)

leftovers = Path(tempfile.mkdtemp(prefix="left_"))
exe = leftovers / "LLMSelfbot.exe"
exe.write_bytes(b"x")
(leftovers / "LLMSelfbot.exe.old").write_bytes(b"old")
saved = (getattr(sys, "frozen", None), sys.executable)
sys.frozen = True
sys.executable = str(exe)
try:
    update.clean_leftovers()
finally:
    if saved[0] is None:
        del sys.frozen
    else:
        sys.frozen = saved[0]
    sys.executable = saved[1]
check("the exe the last update stepped aside from is cleared away on the next start",
      not (leftovers / "LLMSelfbot.exe.old").exists() and exe.exists())
shutil.rmtree(leftovers, ignore_errors=True)
old_updater = read("scripts/updater.py")
check("the old updater script, which wanted a zip no release has, now runs this",
      "from app.core import update" in old_updater and "zipfile" not in old_updater)

print("\n== accounts on threads, for the phones ==")
from app.core import inprocess  # noqa: E402


def chatty():
    print("hello")
    sys.stdout.write("half a ")
    print("line")
    raise SystemExit(3)


role = inprocess.ThreadRole("discord", 1, chatty)
lines = list(role.stdout)
check("what a role prints comes out as its own lines", lines == ["hello\n", "half a line\n"], repr(lines))
check("and how it ended is kept", role.wait(5) == 3 and role.poll() == 3)
check("its pid is this process's, and nothing writes a pid file for it", role.pid == os.getpid())


def looping():
    import asyncio

    async def forever():
        print("up")
        await asyncio.sleep(3600)
    asyncio.run(forever(), loop_factory=inprocess.loop_factory(None))


role = inprocess.ThreadRole("telegram", None, looping)
first = next(role.stdout)
t0 = time.time()
role.terminate()
role.wait(10)
check("one sitting in its event loop stops at once when asked", first == "up\n" and time.time() - t0 < 3,
      f"{time.time() - t0:.2f}s")


def crashing():
    raise ValueError("boom")


role = inprocess.ThreadRole("discord", 2, crashing)
out = "".join(role.stdout)
check("a crash comes out as its traceback, on its own output", role.wait(5) == 1 and "ValueError: boom" in out)
check("the rest of the app still prints where it always did", sys.stdout.write("") == 0)
with env(**{**CLEAN, "LLMSELFBOT_INPROCESS": "1"}):
    from app.core import launcher
    try:
        launcher.spawn_role("snapchat", 1)
        refused = False
    except RuntimeError:
        refused = True
    check("Snapchat is refused rather than attempted on a thread", refused)
check("each start loads the app afresh, keeping only what it shares with the panel",
      '"app.core", "app.web"' in read("app/core/inprocess.py") and "_fresh()" in read("app/core/inprocess.py"))
check("so a restarted account is not left holding the stopped one's closed event loop",
      "bound to the event loop" in read("app/core/inprocess.py"))
check("chat and model events reach the panel from a thread as from a process",
      "under_panel()" in read("app/utils/usage.py") and "under_panel()" in read("app/utils/logger.py")
      and "_under_panel()" in read("app/platforms/discord_runner.py"))
check("Telegram polls without signal handlers there, which only a main thread may set",
      '{"stop_signals": None}' in read("app/telegram_bot/telegram_controller.py"))
sup = read("app/web/supervisor.py")
check("one Discord account at a time where accounts share the app", "n = min(n, 1)" in sup)
check("no Snapchat planned on a phone", "if snap_on and device.is_phone():" in sup)
check("and no stale processes swept, since a thread leaves none", "if device.single_process() or not IPC_DIR.exists():" in sup)

print("\n== the panel, on a phone ==")
routes = read("app/web/routes/system_routes.py")
check("it asks what this device is", '@router.get("/api/system/device")' in routes)
check("links open outside the phone app's web view, only from the phone itself, only web addresses",
      '@router.post("/api/system/open-url")' in routes and 'host not in ("127.0.0.1", "::1", "localhost")' in routes
      and 'url.startswith(("https://", "http://"))' in routes and "if not device.single_process():" in routes)
check("restarting there restarts the accounts, since ending the process would close the app",
      '"accounts_only": True' in routes)
check("a folder cannot be opened where there is no file manager", 'compat.check("folders")' in routes)
check("the phone checks skip the tools a phone never has", "return _doctor_rest(checks, add, supervisor)" in routes)
check("ffmpeg's fix off Windows is the package manager, not a download that only works on Windows",
      '"sudo apt install ffmpeg"' in routes and "ffmpeg_act = None" in routes)
check("the update check says how this device updates", '"method": plan["method"]' in routes
      and '"ready": plan["ready"]' in routes)
check("a build without Discord can still start the panel",
      "import discord" not in read("app/utils/error_notifications.py").split("async def webhook_log")[0])
check("the phones keep their data in their own storage",
      'os.environ.get("LLMSELFBOT_DATA_DIR"' in read("app/utils/paths.py"))

print("\n== the phone apps ==")
mob = tomllib.loads(read("mobile/pyproject.toml"))["tool"]["briefcase"]
app_cfg = mob["app"]["llmselfbot"]
req = app_cfg["requires"]
check("FastAPI 0.125 with pydantic 1, which is plain Python", "fastapi==0.125.0" in req
      and "pydantic>=1.10.24,<2" in req)
check("the stand-ins, and where they come from", "jiter==0.99.0" in req
      and app_cfg["requirement_installer_args"] == ["--find-links", "./wheels"])
check("Android has Discord", {"discord.py-self", "curl_cffi", "audioop-lts==0.99.0"} <= set(app_cfg["android"]["requires"]))
check("64-bit ARM, as curl_cffi's Android build is", app_cfg["android"]["android_abis"] == ["arm64-v8a"])
check("and the web view's link handling", "toga_android.widgets.internal.webview" in app_cfg["android"]["build_gradle_extra_content"])
check("the iPhone app has no Discord", not any("discord" in r for r in app_cfg["iOS"]["requires"]))
check("and may reach its own panel over http", app_cfg["iOS"]["info"]["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True})
check("the whole panel goes in", {"src/app", "src/resources", "src/webui", "src/llmselfbot"} == set(app_cfg["sources"]))

sys.path.insert(0, str(ROOT / "mobile" / "shims" / "jiter"))
import jiter  # noqa: E402
check("jiter's stand-in parses whole documents", jiter.from_json(b'{"a": [1, 2]}') == {"a": [1, 2]})
check("and closes off partial ones", jiter.from_json(b'{"a": [1, 2', partial_mode=True) == {"a": [1, 2]}
      and jiter.from_json(b'{"a": "hel', partial_mode=True) == {"a": "hel"})
spec = importlib.util.spec_from_file_location("audioop_standin", ROOT / "mobile" / "shims" / "audioop-lts" / "audioop.py")
audioop_standin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audioop_standin)
pcm = array.array("h", [1000, -1000, 30000]).tobytes()
check("audioop's stand-in turns the volume, clipping as the real one does",
      array.array("h", audioop_standin.mul(pcm, 2, 2.0)).tolist() == [2000, -2000, 32767])
check("both are numbered above every real release, so pip prefers them",
      'version = "0.99.0"' in read("mobile/shims/jiter/pyproject.toml")
      and 'version = "0.99.0"' in read("mobile/shims/audioop-lts/pyproject.toml"))
stage = read("mobile/stage.py")
check("curl_cffi's own Android build is used, with only its cffi requirement relaxed",
      "def relaxed_curl_cffi" in stage and 'f"{version}+phone"' in stage and "Requires-Dist: cffi>=1.12.0" in stage)
check("and it stops rather than relax something that has changed", "look again before relaxing anything" in stage)
check("what is downloaded is checked against PyPI's checksum", 'entry["digests"]["sha256"]' in stage)
check("PyYAML goes to the iPhone as plain Python", "def pure_pyyaml" in stage)
check("the version comes from the tag, into both the package and the app", "_build.py" in stage
      and "VERSION = " in stage and 'version = "{packaged}"' in stage)
check("a build that is not a release still gets an Android version code", 'packaged = "0.0.1"' in stage)
check("every icon size Android and iOS ask for is made from the app's own",
      "ANDROID = {" in stage and "IOS = (" in stage and "resources\" / \"icon.png\"" in stage.replace("'", '"'))
shell = read("mobile/src/llmselfbot/app.py")
check("the shell starts the panel's server on a thread and shows it once it answers",
      "run_supervisor(port=self.port)" in shell and "self.web.url = self.panel" in shell)
check("it says the app is a phone app before anything of it is imported",
      shell.index('os.environ["LLMSELFBOT_SHELL"]') < shell.index("from app.cli import"))
check("and sends links to anywhere else to the phone's browser", "webbrowser.open" in shell and "return False" in shell)
check("if the server cannot start, it says why instead of staying blank", "could not start" in shell)

print("\n== in the workflow ==")
check("an Android job and an iPhone job", "\n  android:\n" in wf and "\n  ios:\n" in wf)
check("both on Python 3.13, which curl_cffi's Android build is for", wf.count('python-version: "3.13"') >= 2)
check("both stage the app with the release's version", '--version "$APP_VERSION" --android' in wf
      and '--version "$APP_VERSION" --ios' in wf)
check("the APK is signed with the repository's key when there is one", "ANDROID_KEYSTORE_BASE64" in wf
      and "apksigner" in wf and "apksigner\" verify" in wf)
check("and says plainly when there is not", "::warning::No ANDROID_KEYSTORE_BASE64 secret" in wf)
check("the IPA is built for a phone, unsigned, with an ad-hoc signature for Python's libraries",
      "-sdk iphoneos" in wf and "CODE_SIGNING_ALLOWED=NO" in wf and 'EXPANDED_CODE_SIGN_IDENTITY="-"' in wf)
check("and packed the way an IPA is", "mkdir -p ipa/Payload" in wf and "LLMSelfbot-ios.ipa" in wf)
check("with an AltStore source beside it, so SideStore keeps it up to date", "altstore.json" in wf
      and "releases/latest/download/altstore.json" in read("mobile/altstore.py"))
check("the iPhone build cannot hold back the rest of a release", "continue-on-error: true" in wf.split("\n  ios:\n")[1][:600])
check("both are attached to the release", wf.count("LLMSelfbot-android.apk") >= 3 and wf.count("LLMSelfbot-ios.ipa") >= 3)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
