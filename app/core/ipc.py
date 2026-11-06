import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

from app.platforms import registry
from app.utils.paths import DATA_DIR

# Target type: Discord account index (int), "snap" / "snapN" for Snapchat, "tiktok" / "tiktokN" for TikTok,
# "insta" / "instaN" for Instagram, "x" / "xN" for X, "reddit" / "redditN" for Reddit, "wa" / "waN" for
# WhatsApp, "mc" / "mcN" for
# Minecraft, "imsg" / "imsgN" for iMessage, or "tg" / "tgN" for one of the persona's Telegram accounts.
CONFIG_DIR = DATA_DIR / "config"
IPC_DIR = DATA_DIR / "ipc"


def _count_accounts() -> int:
    """How many Discord accounts are actually configured, 0 is a real answer. This used to floor at 1, which invented an account with no token: the UI listed a phantom "Discord #1" and the supervisor spawned a runner for it that crash-looped forever."""
    from app.utils.credentials import real
    count = 0
    i = 1
    while real(f"DISCORD_TOKEN_{i}"):
        count = i
        i += 1
    if count == 0 and real("DISCORD_TOKEN"):
        count = 1
    return count


def _count_snap_accounts() -> int:
    from app.utils.credentials import real
    if not (real("SNAP_USERNAME") or real("SNAP_USERNAME_1")):
        return 0
    n = 1
    while real(f"SNAP_USERNAME_{n + 1}"):
        n += 1
    return n


def _count_tiktok_accounts() -> int:
    """TikTok accounts, by the @handle each was signed in as (TIKTOK_USERNAME_<n>). The login itself lives in that
    account's own browser profile, so there is no password to count."""
    from app.utils.credentials import real
    if not real("TIKTOK_USERNAME_1"):
        return 0
    n = 1
    while real(f"TIKTOK_USERNAME_{n + 1}"):
        n += 1
    return n


def _count_instagram_accounts() -> int:
    """Instagram accounts, by the username each was added as (INSTAGRAM_USERNAME_<n>). Its password and 2FA key sit
    beside it in config/.env, write-only, as Snapchat's password does."""
    from app.utils.credentials import real
    if not real("INSTAGRAM_USERNAME_1"):
        return 0
    n = 1
    while real(f"INSTAGRAM_USERNAME_{n + 1}"):
        n += 1
    return n


def _count_x_accounts() -> int:
    """X accounts, by the @handle each was added as (X_USERNAME_<n>). Its password and 2FA key sit beside it in
    config/.env, write-only, as Instagram's do; the email or phone X asks for when it questions a login sits there
    too."""
    from app.utils.credentials import real
    if not real("X_USERNAME_1"):
        return 0
    n = 1
    while real(f"X_USERNAME_{n + 1}"):
        n += 1
    return n


def _count_reddit_accounts() -> int:
    """Reddit accounts, by the username each was added as (REDDIT_USERNAME_<n>). Its password and 2FA key sit
    beside it in config/.env, write-only, as X's do. Reddit asks for no email on a login, so there is no third."""
    from app.utils.credentials import real
    if not real("REDDIT_USERNAME_1"):
        return 0
    n = 1
    while real(f"REDDIT_USERNAME_{n + 1}"):
        n += 1
    return n


def _count_whatsapp_accounts() -> int:
    """WhatsApp accounts, by the number each was linked as (WHATSAPP_NUMBER_<n>). Nothing secret sits beside it:
    the login is the linked session in config/whatsapp-<number>-auth, which a person made with their phone."""
    from app.utils.credentials import real
    if not real("WHATSAPP_NUMBER_1"):
        return 0
    n = 1
    while real(f"WHATSAPP_NUMBER_{n + 1}"):
        n += 1
    return n


def _count_minecraft_accounts() -> int:
    """Minecraft accounts, by the name each plays as (MINECRAFT_USERNAME_<n>). Offline servers need nothing else;
    a Microsoft account signs in through a code on its first run, and keeps no password here."""
    from app.utils.credentials import real
    if not real("MINECRAFT_USERNAME_1"):
        return 0
    n = 1
    while real(f"MINECRAFT_USERNAME_{n + 1}"):
        n += 1
    return n


def _count_imessage_accounts() -> int:
    """iMessage accounts, by the BlueBubbles server each reads through (IMESSAGE_SERVER_<n>): a Mac signed in to
    iMessage. Its password sits beside it in config/.env, write-only."""
    from app.utils.credentials import real
    if not real("IMESSAGE_SERVER_1"):
        return 0
    n = 1
    while real(f"IMESSAGE_SERVER_{n + 1}"):
        n += 1
    return n


def _count_telegram_accounts() -> int:
    """Telegram accounts, by the sign-in each one left behind (TELEGRAM_SESSION_<n>): the persona's own Telegram
    account, not the control bot (app/telegram_bot). The session is the whole login; it sits in config/.env,
    write-only."""
    from app.utils.credentials import real
    if not real("TELEGRAM_SESSION_1"):
        return 0
    n = 1
    while real(f"TELEGRAM_SESSION_{n + 1}"):
        n += 1
    return n


_VALID_TARGET = re.compile(r"^(?:[1-9][0-9]{0,2}|snap(?:[2-9]|[1-9][0-9]{1,2})?"
                           r"|tiktok(?:[2-9]|[1-9][0-9]{1,2})?|insta(?:[2-9]|[1-9][0-9]{1,2})?"
                           r"|mc(?:[2-9]|[1-9][0-9]{1,2})?|imsg(?:[2-9]|[1-9][0-9]{1,2})?"
                           r"|tg(?:[2-9]|[1-9][0-9]{1,2})?|x(?:[2-9]|[1-9][0-9]{1,2})?"
                           r"|reddit(?:[2-9]|[1-9][0-9]{1,2})?"
                           r"|wa(?:[2-9]|[1-9][0-9]{1,2})?)$")


def validate_target(target):
    """Normalise a target, rejecting anything that isn't a real account id. The target is interpolated into an IPC filename, so an unchecked value like "../../evil" would write outside the data directory."""
    t = str(target).strip()
    if not _VALID_TARGET.match(t):
        raise ValueError(f"invalid IPC target: {target!r}")
    return int(t) if t.isdigit() else t


def is_snap(account) -> bool:
    return isinstance(account, str) and account.startswith("snap")


def snap_index(account) -> int:
    if account == "snap":
        return 1
    try:
        return int(str(account)[4:])
    except (ValueError, TypeError):
        return 1


def is_tiktok(account) -> bool:
    return isinstance(account, str) and account.startswith("tiktok")


def tiktok_index(account) -> int:
    try:
        return int(str(account)[6:] or 1)
    except (ValueError, TypeError):
        return 1


def is_instagram(account) -> bool:
    return isinstance(account, str) and account.startswith("insta")


def instagram_index(account) -> int:
    try:
        return int(str(account)[5:] or 1)
    except (ValueError, TypeError):
        return 1


def is_x(account) -> bool:
    """An X account ("x", "x2"). No other target starts with an x, so the one letter is enough."""
    return isinstance(account, str) and account.startswith("x")


def x_index(account) -> int:
    try:
        return int(str(account)[1:] or 1)
    except (ValueError, TypeError):
        return 1


def is_reddit(account) -> bool:
    """A Reddit account ("reddit", "reddit2"). Six letters nothing else here begins with."""
    return isinstance(account, str) and account.startswith("reddit")


def reddit_index(account) -> int:
    try:
        return int(str(account)[6:] or 1)
    except (ValueError, TypeError):
        return 1


def is_whatsapp(account) -> bool:
    """A WhatsApp account ("wa", "wa2"). Two letters nothing else here begins with."""
    return isinstance(account, str) and account.startswith("wa")


def whatsapp_index(account) -> int:
    try:
        return int(str(account)[2:] or 1)
    except (ValueError, TypeError):
        return 1


def is_minecraft(account) -> bool:
    return isinstance(account, str) and account.startswith("mc")


def minecraft_index(account) -> int:
    try:
        return int(str(account)[2:] or 1)
    except (ValueError, TypeError):
        return 1


def is_imessage(account) -> bool:
    return isinstance(account, str) and account.startswith("imsg")


def imessage_index(account) -> int:
    try:
        return int(str(account)[4:] or 1)
    except (ValueError, TypeError):
        return 1


def is_telegram(account) -> bool:
    """A Telegram account of the persona's ("tg", "tg2"). The control bot is no account and has no target."""
    return isinstance(account, str) and account.startswith("tg")


def telegram_index(account) -> int:
    try:
        return int(str(account)[2:] or 1)
    except (ValueError, TypeError):
        return 1


def is_browser(account) -> bool:
    """Driven through a browser by the shared bridge (app/platforms/snapchat_bridge.py): Snapchat, TikTok,
    Instagram, X and Reddit. Not Minecraft nor iMessage, which the same bridge runs with no browser at all
    (is_bridged)."""
    return (is_snap(account) or is_tiktok(account) or is_instagram(account) or is_x(account)
            or is_reddit(account))


def is_bridged(account) -> bool:
    """Run by the shared bridge, whose command and result files live in ipc/: the browser platforms, and the ones
    that need no browser at all - Minecraft, iMessage and WhatsApp."""
    return (is_browser(account) or is_minecraft(account) or is_imessage(account)
            or is_whatsapp(account) or is_telegram(account))


def platform_of(target) -> str:
    """"discord", "snapchat", "tiktok", "instagram", "x", "reddit", "whatsapp", "minecraft", "imessage" or
    "telegram", for an IPC target."""
    if is_telegram(target):
        return "telegram"
    if is_tiktok(target):
        return "tiktok"
    if is_instagram(target):
        return "instagram"
    if is_x(target):
        return "x"
    if is_reddit(target):
        return "reddit"
    if is_whatsapp(target):
        return "whatsapp"
    if is_minecraft(target):
        return "minecraft"
    if is_imessage(target):
        return "imessage"
    return "snapchat" if is_snap(target) else "discord"


def cmd_file(target) -> Path:
    target = validate_target(target)
    if is_bridged(target):
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        return IPC_DIR / f"tg_commands_{target}.json"
    return CONFIG_DIR / f"tg_commands_{target}.json"


def result_file(target) -> Path:
    target = validate_target(target)
    if is_bridged(target):
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        return IPC_DIR / f"tg_results_{target}.json"
    return CONFIG_DIR / f"tg_results_{target}.json"


# Commands and answers are a few KB. A file past this is damaged, and parsing it is what froze the panel: a results file once reached 900 MB through an encoding mismatch, and it was re-read three times a second per waiting call.
MAX_FILE_BYTES = 8 * 1024 * 1024


def _read_json(path: Path, default):
    try:
        if not path.exists():
            return default
        if path.stat().st_size > MAX_FILE_BYTES:
            _discard(path, default)
            return default
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return default
        return json.loads(text)
    except Exception:
        return default


def _discard(path: Path, default):
    """Start a runaway IPC file over. Whatever it held is long stale."""
    try:
        _write_json_atomic(path, default)
    except Exception:
        pass


def _write_json_atomic(path: Path, data):
    # A temporary file of its own and a few tries: see app/utils/atomic.py, and the night it was the same name as the Snapchat bridge's.
    from app.utils.atomic import write_json_atomic
    write_json_atomic(path, data)


def send_command(target, cmd: str, payload: dict = None) -> str:
    """Append a command to the target's IPC file (atomic write, merge-safe)."""
    cmd_id = str(uuid.uuid4())
    entry = {"id": cmd_id, "cmd": cmd, "payload": payload or {}, "ts": time.time()}
    f = cmd_file(target)
    for attempt in range(5):
        try:
            existing = _read_json(f, [])
            if not isinstance(existing, list):
                existing = []
            existing.append(entry)
            _write_json_atomic(f, existing)
            return cmd_id
        except Exception:
            time.sleep(0.05 * (attempt + 1))
    return ""


# Matches the runner's own cap. A result is only cleared when it is read, so anything whose caller timed out lingers; unbounded, the file grew to tens of megabytes and every read/write of it blocked the event loop.
MAX_RESULTS = 40


def _prune(results: dict) -> dict:
    if len(results) <= MAX_RESULTS:
        return results
    return dict(list(results.items())[-MAX_RESULTS:])


def append_result(path: Path, cmd_id: str, data, keep: int = MAX_RESULTS) -> None:
    """A worker posting its answer: add it, keep the newest `keep`, write back. Shared so the two ends of the file cannot disagree about it again. The Discord worker used to do this itself with the Windows default encoding while the panel wrote UTF-8, and every leftover answer holding an emoji or an accent doubled in size on each pass through the pair, to 900 MB. Written in place rather than renamed over: the panel may be reading the file, and on Windows a rename onto an open file fails; a reader catching it half-written gets a parse error and simply looks again."""
    results = _read_json(path, {})
    if not isinstance(results, dict):
        results = {}
    results[cmd_id] = data
    if len(results) > keep:
        # dicts keep insertion order, so the tail is the newest.
        results = dict(list(results.items())[-keep:])
    path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")


def _stamp(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _take_result(f: Path, cmd_id: str):
    """Read the results file; if our answer is there, remove it and return it."""
    results = _read_json(f, {})
    if not (isinstance(results, dict) and cmd_id in results):
        return False, None
    result = results.pop(cmd_id)
    try:
        _write_json_atomic(f, _prune(results))
    except Exception:
        pass            # left in the file, pruned later; the caller has its answer
    return True, result


async def wait_for_result(target, cmd_id: str, timeout: float = 10.0) -> dict | None:
    """Poll the target's result file until the runner posts a result. The file is only read again when it has changed, and the read happens on a thread: this runs for every call to a running account, several at a time, three times a second, and every read used to parse the whole file on the event loop the rest of the panel is served from."""
    f = result_file(target)
    deadline = time.time() + timeout
    seen = None
    while time.time() < deadline:
        stamp = _stamp(f)
        if stamp is not None and stamp != seen:
            seen = stamp
            found, result = await asyncio.to_thread(_take_result, f, cmd_id)
            if found:
                return result
        await asyncio.sleep(0.3)
    # Timed out. Trim here too, so a run of timeouts cannot pile up unread answers faster than the runner's own cap clears them.
    def _trim():
        results = _read_json(f, {})
        if isinstance(results, dict) and len(results) > MAX_RESULTS:
            try:
                _write_json_atomic(f, _prune(results))
            except Exception:
                pass
    await asyncio.to_thread(_trim)
    return None


async def send_and_wait(target, cmd: str, payload: dict = None, timeout: float = 10.0) -> dict | None:
    cmd_id = send_command(target, cmd, payload)
    if not cmd_id:
        return {"ok": False, "reason": "could not write IPC command file"}
    return await wait_for_result(target, cmd_id, timeout)


_WEB_ID = registry.ACCOUNT_ID
# Each bridged platform's target names: account 1 is the bare prefix, the rest carry their number.
_PREFIX = registry.TARGETS


def browser_target(platform: str, n: int) -> str:
    """"snap", "snap2", "tiktok", "tiktok3", "insta", "insta2"..."""
    p = _PREFIX[platform]
    return p if int(n) == 1 else f"{p}{int(n)}"


def target_for(web_id):
    """The IPC target of an account by its web id: "discord_2" is 2, "snapchat_1" is "snap", "snapchat_3" "snap3",
    "tiktok_1" "tiktok". None for anything else. Handing a web id straight to send_command failed silently: it is
    not a target."""
    m = _WEB_ID.match(str(web_id or ""))
    if not m:
        return None
    n = int(m.group(2))
    if m.group(1) == "discord":
        return n
    target = browser_target(m.group(1), n)
    return target if _VALID_TARGET.match(target) else None


def web_id_for(target):
    """The other way: an IPC target's web id, or None."""
    try:
        t = validate_target(target)
    except ValueError:
        return None
    if is_tiktok(t):
        return f"tiktok_{tiktok_index(t)}"
    if is_instagram(t):
        return f"instagram_{instagram_index(t)}"
    if is_x(t):
        return f"x_{x_index(t)}"
    if is_reddit(t):
        return f"reddit_{reddit_index(t)}"
    if is_whatsapp(t):
        return f"whatsapp_{whatsapp_index(t)}"
    if is_minecraft(t):
        return f"minecraft_{minecraft_index(t)}"
    if is_imessage(t):
        return f"imessage_{imessage_index(t)}"
    if is_telegram(t):
        return f"telegram_{telegram_index(t)}"
    return f"snapchat_{snap_index(t)}" if is_snap(t) else f"discord_{t}"


def discover_targets() -> dict:
    """All reachable IPC targets keyed by a stable web id."""
    out = {}
    for n in range(1, _count_accounts() + 1):
        out[f"discord_{n}"] = {"platform": "discord", "account": n, "target": n}
    for n in range(1, _count_snap_accounts() + 1):
        out[f"snapchat_{n}"] = {"platform": "snapchat", "account": n, "target": browser_target("snapchat", n)}
    for n in range(1, _count_tiktok_accounts() + 1):
        out[f"tiktok_{n}"] = {"platform": "tiktok", "account": n, "target": browser_target("tiktok", n)}
    for n in range(1, _count_instagram_accounts() + 1):
        out[f"instagram_{n}"] = {"platform": "instagram", "account": n, "target": browser_target("instagram", n)}
    for n in range(1, _count_x_accounts() + 1):
        out[f"x_{n}"] = {"platform": "x", "account": n, "target": browser_target("x", n)}
    for n in range(1, _count_reddit_accounts() + 1):
        out[f"reddit_{n}"] = {"platform": "reddit", "account": n, "target": browser_target("reddit", n)}
    for n in range(1, _count_whatsapp_accounts() + 1):
        out[f"whatsapp_{n}"] = {"platform": "whatsapp", "account": n, "target": browser_target("whatsapp", n)}
    for n in range(1, _count_minecraft_accounts() + 1):
        out[f"minecraft_{n}"] = {"platform": "minecraft", "account": n, "target": browser_target("minecraft", n)}
    for n in range(1, _count_imessage_accounts() + 1):
        out[f"imessage_{n}"] = {"platform": "imessage", "account": n, "target": browser_target("imessage", n)}
    for n in range(1, _count_telegram_accounts() + 1):
        out[f"telegram_{n}"] = {"platform": "telegram", "account": n, "target": browser_target("telegram", n)}
    return out


def shown_targets() -> dict:
    """discover_targets() without the accounts of a social switched off in Settings: what the panel lists. Anything
    that acts on one account by its id still finds it in discover_targets()."""
    from app.utils import socials
    on = socials.on()
    return {web_id: meta for web_id, meta in discover_targets().items() if on.get(meta["platform"], True)}
