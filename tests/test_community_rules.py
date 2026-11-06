"""What a community profile may hold (app/utils/community_rules.py), the one file both the app and the community's
workflow check everything with: every limit, every setting that may be shared and its values, what the scanner
refuses and what it only points out, the zips and the request inside an issue, where it all lives in the app's repo,
and that the workflow's copy is the same file."""
import ast
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import community_rules as rules  # noqa: E402

TEXT = ("You are Pebble, a calm study buddy who loves rocks and minerals. You text in lowercase, keep things short and "
        "kind, and ask what the other person is working on. You get excited about geodes and you always know a fun "
        "fact about quartz. You never pretend to be an assistant; you are just a friend who happens to love rocks.")
META = {"slug": "pebble", "name": "Pebble", "tagline": "Rocks", "description": "Kind.", "tags": ["chill"],
        "color": "#A78BFA", "author": "rockfan", "adult": False, "language": "en", "note": ""}

print("== the details ==")
clean, p = rules.check_meta(META)
check("a good one passes, cleaned", p == [] and clean["color"] == "#a78bfa", p)
for slug, ok in (("pebble", True), ("pebble-2", True), ("ab", False), ("a" * 33, False), ("Pebble", False),
                 ("peb--ble", False), ("-pebble", False), ("pebble_", False), ("default", False), ("test", False)):
    _, p = rules.check_meta({**META, "slug": slug})
    check(f"short name {slug!r}: {'fine' if ok else 'refused'}", (p == []) == ok, p)
cases = [("name", "", "needs a name"), ("name", "x" * 41, "too long"), ("tagline", "x" * 91, "too long"),
         ("description", "\n".join(["line"] * 9), "too many lines"), ("author", "a", "author name"),
         ("author", "@me", "@"), ("tags", ["chill"] * 1 + ["funny", "shy", "gamer", "anime", "music"], "At most"),
         ("tags", ["made-up"], "Not a tag"), ("color", "red", "colour"), ("language", "english!", "language"),
         ("note", "x" * 201, "too long"), ("adult", "yes", "18+"), ("tagline", "visit example.com", "link")]
for field, value, word in cases:
    _, p = rules.check_meta({**META, field: value})
    check(f"{field} = {str(value)[:20]!r} is refused, plainly", any(word in x for x in p), p)
_, p = rules.check_meta({**META, "name": "a​b"})
check("invisible characters are taken out", rules.check_meta({**META, "name": "Pe" + chr(0x200B) + "bble"})[0]["name"] == "Pebble")

print("\n== the text ==")
t, p = rules.check_text(TEXT + "\r\n\r\n")
check("a good text passes, its line ends made plain", p == [] and "\r" not in t and not t.endswith("\n"))
check("too short", any("too short" in x for x in rules.check_text("hi there")[1]))
check("too long", any("too long" in x for x in rules.check_text("word " * 5000)[1]))
check("a blank left from the template", any("blank" in x for x in rules.check_text(TEXT + " [HOBBIES - games]")[1]))
check("direction marks can't turn text around", chr(0x202E) not in rules.check_text(TEXT + chr(0x202E) + "x")[0])

print("\n== settings ==")
GOOD = {
    "bot.trigger": "Pebble, Peb", "bot.default_language": "fr", "bot.message_style.mode": "short",
    "bot.message_style.max_chunk_chars": 400, "bot.typo_chance": 0.05, "bot.mood.enabled": True,
    "bot.mood.shift_interval_min": 900, "bot.mood.shift_interval_max": 3600,
    "bot.mood.moods": {"chill": "Be relaxed.", "sleepy": "Yawn a lot."}, "bot.reactions.enabled": True,
    "bot.reactions.chance": 0.2, "bot.reactions.react_only_max_ratio": 0.1, "bot.reactions.emojis": ["😂", "🪨"],
    "bot.late_reply.enabled": True, "bot.late_reply.threshold": 600, "bot.late_reply.style": "casual",
    "bot.late_reply.openers": {"en": ["sorry was out "]}, "bot.refusal.fallbacks": ["huh?"],
    "bot.refusal.extra_phrases": ["as an ai"], "bot.sampling.temperature": None, "bot.sampling.top_p": 0.9,
    "bot.sampling.frequency_penalty": 0.5, "bot.sampling.presence_penalty": -0.5, "bot.tts.voice": "diana",
    "bot.tts.tones": ["[casual]", "[warm]"], "tiktok.live.tone": "hype", "tiktok.live.topic": "rocks",
    "tiktok.live.language": "persona", "tiktok.live.max_words": 12, "tiktok.live.use_names": False,
    "tiktok.live.emoji": True,
}
s, p = rules.check_settings(GOOD)
check("every allowed setting, with a good value, passes", p == [] and set(s) == set(GOOD), p)
check("the allowed list is exactly these, no more", set(rules.ALLOWED) == set(GOOD), set(rules.ALLOWED) ^ set(GOOD))
BAD = {
    "bot.trigger": "hi", "bot.default_language": "english", "bot.message_style.mode": "novel",
    "bot.message_style.max_chunk_chars": 20, "bot.typo_chance": 0.5, "bot.mood.enabled": "yes",
    "bot.mood.shift_interval_min": 10, "bot.mood.moods": {"Bad Name": "x"}, "bot.reactions.chance": 0.9,
    "bot.reactions.emojis": ["lol"], "bot.late_reply.threshold": 5, "bot.late_reply.openers": {"english": ["x"]},
    "bot.refusal.fallbacks": [], "bot.sampling.temperature": 3, "bot.sampling.top_p": 0, "bot.tts.voice": "Diana!",
    "bot.tts.tones": ["casual"], "tiktok.live.tone": "angry", "tiktok.live.max_words": 100, "tiktok.live.use_names": 1,
}
for key, value in BAD.items():
    _, p = rules.check_settings({key: value})
    check(f"{key} = {value!r} is refused", any(key in x for x in p), p)
for key in ("bot.groq_models", "bot.owner_id", "bot.typing.wpm_min", "bot.nudge.enabled", "tiktok.engage.like_sent",
            "bot.timezone", "services.webui.port", "bot.refusal.enabled", "bot.allow_dm", "discord.enabled"):
    _, p = rules.check_settings({key: True})
    check(f"{key} can never be shared", any("can't be shared" in x for x in p), p)
_, p = rules.check_settings({"bot.mood.shift_interval_min": 5000, "bot.mood.shift_interval_max": 1000})
check("a mood's shortest change can't be longer than its longest", any("longer" in x for x in p))
_, p = rules.check_settings({"bot.mood.moods": {"chill": "dm me at me@mail.com"}})
check("words inside settings are scanned too", any("email" in x for x in p), p)
_, p = rules.check_settings({f"bot.x{i}": 1 for i in range(41)})
check("at most 40 settings", any("Too many" in x for x in p))
check("integers sent as 300.0 are fine, 300.5 aren't", rules.ALLOWED["bot.late_reply.threshold"](300.0) == (300, "")
      and rules.ALLOWED["bot.late_reply.threshold"](300.5)[1])

print("\n== the scanner ==")
for text, kind in (("join discord.gg/abc", "invite"), ("t.me/somebody", "invite"), ("go to example.com", "link"),
                   ("https://x.io/a", "link"), ("me@site.com", "email"), ("venmo me", "money"),
                   ("$cashtag123", "money"), ("send your 2fa code", "secret"), ("seed phrase", "secret"),
                   ("+1 (555) 010-9999", "phone"), ("123456789012345678", "id"), ("ask @rockfan", "handle")):
    kinds = [f["kind"] for f in rules.scan({"text": text})]
    check(f"{kind}: {text!r}", kind in kinds, kinds)
check("plain words are just words", rules.scan({"text": TEXT}) == [])
check("an email isn't also a link", [f["kind"] for f in rules.scan({"text": "me@site.com"})] == ["email"])
check("short numbers aren't phone numbers", rules.scan({"text": "i'm 19 and 5 7"}) == [])
yours = rules.scan({"text": "find me as mysnap on snap"}, yours=["mysnap"])
check("your own usernames, when given, are pointed out", [f["kind"] for f in yours] == ["yours"])
check("handles and yours are warnings, the rest refused", rules.WARN == {"handle", "yours"}
      and {"link", "invite", "email", "phone", "money", "secret", "id"} == set(rules.REFUSE))

print("\n== pictures ==")
from PIL import Image  # noqa: E402
buf = io.BytesIO()
ex = Image.Exif()
ex[0x8825] = {2: (48.0, 51.0, 24.0)}
Image.new("RGB", (900, 600), (10, 120, 200)).save(buf, "JPEG", exif=ex.tobytes())
face, p = rules.check_avatar(buf.getvalue())
with Image.open(io.BytesIO(face)) as im:
    check("a face: 256 square, nothing hidden", p == [] and im.size == (256, 256) and not im.getexif())
pic = rules.reencode_image(buf.getvalue(), side=1600)
with Image.open(io.BytesIO(pic)) as im:
    check("a picture: kept its size, nothing hidden", im.size == (900, 600) and not im.getexif())
check("not a picture is said so", rules.check_avatar(b"GIF89a nonsense")[1] != [])
tiny = io.BytesIO()
Image.new("RGB", (20, 20)).save(tiny, "PNG")
check("too small is said so", "too small" in " ".join(rules.check_avatar(tiny.getvalue())[1]))

print("\n== files ==")
files = {"profile.json": rules.canonical_json(META), "persona.txt": TEXT.encode(), "settings.json": b"{}\n",
         "avatar.jpg": face}
z1, z2 = rules.build_zip(files), rules.build_zip(dict(reversed(list(files.items()))))
check("the same files make the same zip, whatever the order", z1 == z2)
check("and read back exactly", rules.read_zip(z1) == files)


def zip_of(entries, flag=0):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries:
            info = zipfile.ZipInfo(name)
            info.flag_bits |= flag
            z.writestr(info, data)
    return out.getvalue()


for label, blob in (("something extra", zip_of([("profile.json", b"{}"), ("persona.txt", b"x"), ("evil.exe", b"MZ")])),
                    ("a path out", zip_of([("profile.json", b"{}"), ("persona.txt", b"x"), ("../x.txt", b"x")])),
                    ("too big a text", zip_of([("profile.json", b"{}"), ("persona.txt", b"x" * 200_000)])),
                    ("no text at all", zip_of([("profile.json", b"{}")])),
                    ("media in a request's core", zip_of([("profile.json", b"{}"), ("persona.txt", b"x"),
                                                          ("media/m01.jpg", b"x")])),
                    ("not a zip", b"hello")):
    try:
        rules.read_zip(blob)
        check(f"refused: {label}", False)
    except ValueError:
        check(f"refused: {label}", True)
check("media only in a full package", "media/m01.jpg" in rules.read_zip(
    zip_of([("profile.json", b"{}"), ("persona.txt", b"x"), ("media/m01.jpg", b"x")]), media=True))

print("\n== a request inside an issue ==")
req = {"v": 1, "action": "publish", "slug": "pebble", "sha256": rules.sha256(z1), "bytes": len(z1),
       "author": "--> <script>"}
body = rules.render_request(req, z1, "**Pebble**")
back, core = rules.parse_request(body.replace("\n", "\r\n"))
check("written and read back, even with Windows line ends", back == req and core == z1)
check("nothing in it can close the comment it sits in", body.count("-->") == 2 and "<script>" not in body)
try:
    rules.parse_request(body.replace(req["sha256"], "0" * 64))
    check("a changed profile doesn't match its checksum", False)
except ValueError as e:
    check("a changed profile doesn't match its checksum", "checksum" in str(e))
for broken in ("no marker", "<!-- llmselfbot:request {\"v\":2,\"action\":\"publish\"} -->",
               "<!-- llmselfbot:request {\"v\":1,\"action\":\"delete-all\"} -->"):
    try:
        rules.parse_request(broken)
        check(f"refused: {broken[:30]}", False)
    except ValueError:
        check(f"refused: {broken[:30]}", True)
rm, nothing = rules.parse_request(rules.render_request({"v": 1, "action": "remove", "slug": "pebble"}, b"", "x"))
check("a remove has nothing else in it", rm["action"] == "remove" and nothing == b"")
st = rules.render_status({"state": "published", "version": 2}, "Live")
check("a status marker reads back", rules.parse_status(st) == {"state": "published", "version": 2})
check("a fence longer than any backticks inside", rules.fence("a ```` b").startswith("`````"))
check("inline text is inert", rules.md_inline("@everyone [x](y) | #1") == "\\@everyone \\[x\\]\\(y\\) \\| \\#1")
big = rules.build_zip({**files, "persona.txt": ("lorem ipsum dolor sit amet " * 800)[:20_000].encode()})
check("a 20,000 character text fits the issue, with room", len(big) <= rules.LIMITS["core_bytes"]
      and len(rules.render_request(req, big, "x" * 400)) <= rules.LIMITS["body_chars"], len(big))

print("\n== media lists and parts ==")
good = {"gist": "f" * 32, "revision": "a" * 40, "files": [
    {"name": "m01.jpg", "kind": "picture", "sha256": "0" * 64, "bytes": 1000},
    {"name": "m02.mp4", "kind": "video", "sha256": "1" * 64, "bytes": 2_000_000, "seconds": 12.5}]}
check("a good list", rules.check_media(good) == [])
check("a video too long", any("longer" in x for x in rules.check_media(
    {**good, "files": [{**good["files"][1], "seconds": 45}]})))
check("too many pictures", any("Too many pictures" in x for x in rules.check_media(
    {**good, "files": [{**good["files"][0], "name": f"m{i:02d}.jpg"} for i in range(1, 22)]})))
check("a name that isn't one", rules.check_media({**good, "files": [{**good["files"][0], "name": "../x.jpg"}]}) != [])
data = bytes(range(256)) * 5000
parts = {rules.part_name("m01.jpg", i): p for i, p in enumerate(rules.split_parts(data, 100_000))}
check("a file in parts comes back whole", rules.join_parts(parts, "m01.jpg") == data and len(parts) > 1)
parts.pop(rules.part_name("m01.jpg", 1))
try:
    rules.join_parts(parts, "m01.jpg")
    check("a missing part is said so", False)
except ValueError:
    check("a missing part is said so", True)
check("an author is a keyed hash, the same each time, never the account", rules.owner_key("k", 111)
      == rules.owner_key("k", "111") != rules.owner_key("k2", 111) and "111" not in rules.owner_key("k", 111))

print("\n== where it lives in the app's repo ==")
check("its own branch and its own release, never the app's", rules.DATA_BRANCH not in ("main", "master")
      and rules.RELEASE_TAG and not rules.RELEASE_TAG.startswith("v"))
check("a version's file name, read back", rules.asset_name("pebble", 3) == "pebble-v3.zip"
      and rules.parse_asset("pebble-v3.zip") == ("pebble", 3))
check("a short name with -v in it still reads right", rules.parse_asset(rules.asset_name("mix-v2", 1)) == ("mix-v2", 1))
check("nothing else is taken for a profile's file", all(rules.parse_asset(n) is None for n in (
    "LLMSelfbot.exe", "pebble.zip", "pebble-v0.zip", "Pebble-v1.zip", "pebble-v1.zip.sig", "../x-v1.zip", "")))
check("the community's labels all say profile", rules.label("report") == "profile-report"
      and rules.label("request") == "profile-request")
check("the app version a profile was made with, as it's shown", rules.app_version("v1.7.1") == "1.7.1"
      and rules.app_version("1.8.0-beta.2") == "1.8.0" and rules.app_version("2.0") == "2.0")
check("and none for a development build or anything else", all(rules.app_version(v) == "" for v in (
    "0.0.0-dev", "", None, "latest", "1", "1.2.3.4.5", "1.2; rm -rf", "<b>1.2</b>")))
check("versions compare as numbers, 1.7 the same as 1.7.0", rules.version_key("1.10.0") > rules.version_key("1.9.9")
      and rules.version_key("1.7") == rules.version_key("v1.7.0") and rules.version_key("junk") == (0, 0, 0, 0))

print("\n== one file, two places ==")
src = (ROOT / "app/utils/community_rules.py").read_text(encoding="utf-8")
imports = [n for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))]
names = [(getattr(n, "module", None) or ", ".join(a.name for a in n.names)) for n in imports]
check("it imports nothing from the app", not any(str(x).startswith("app") for x in names), names)
check("the community's scripts have the very same file", (ROOT / "community/scripts/community_rules.py").read_bytes()
      == (ROOT / "app/utils/community_rules.py").read_bytes())
fixture = json.loads((ROOT / "tests/community_fixtures/slugs.json").read_text(encoding="utf-8"))
bad_slugs = {name: (rules.slug_from(name), want) for name, want in fixture.items() if rules.slug_from(name) != want}
check("short names made from names, as the page makes them", not bad_slugs, bad_slugs)
check("no em dashes", chr(0x2014) not in src)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
