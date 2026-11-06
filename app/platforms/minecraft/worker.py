"""A Minecraft account's part of its worker, beside the shared bridge (snapchat_bridge.py).

The bridge stays what it is for every platform it serves: the panel's and Telegram's commands, pause, ignore, mood,
the wake channel to its runner, crash and restart. For Minecraft it also has to:

  * serve the brain (brain.py) on its own loopback port, bound before anything is started, so mindcraft is only
    ever given an address that is already listening (Session);
  * write the profile mindcraft plays under (profile.py) and the settings it runs with (mindcraft_settings);
  * start minecraft_runner.mjs, which starts mindcraft and speaks for it, in an environment that holds none of the
    app's secrets (runner_env): mindcraft is someone else's code, and a model's commands run inside it;
  * keep what is said in the game in the chat log, a conversation per player (split_reply, action_words).

Who an account plays as and where comes from its own fields (MINECRAFT_USERNAME_<n>, _HOST_<n>, _PORT_<n>, _AUTH_<n>
in .env, written by the Accounts page), then from Settings, Minecraft, then from DEFAULTS.
"""
from __future__ import annotations

import os
import re
import secrets
import socket
from pathlib import Path

from app.platforms.minecraft import brain as brain_mod, install, profile as profile_mod
from app.utils.paths import APP_DIR, DATA_DIR

# What it runs at when nothing says otherwise: a settings file from before Minecraft has no section for it.
DEFAULTS = {
    "enabled": True, "host": "localhost", "port": 25565, "version": "auto", "auth": "offline",
    "only_chat_with": [], "greet": True, "max_brain_calls_per_hour": 120, "brain_timeout_s": 45,
    "persona": "brief", "remember_world": True, "max_messages": 15, "cooldown_ms": 2000,
    "modes": {"self_defense": True, "hunting": True, "item_collecting": True, "torch_placing": True,
              "cowardice": False},
    # Joining another server when someone asks it to (in the game, or on any platform its persona talks on).
    "join_when_asked": True, "never_join": [],
    # ViaProxy between it and the server: "auto" (a server that does not take 1.21), "always", or "off".
    "translate_versions": "auto",
    # Signing itself in where a server asks in the chat (/register, /login).
    "auto_login": True,
    # How far the live view shows, in chunks.
    "view_distance": 6,
}
RUNNER_DIR = install.MC_DIR / "llmselfbot"


def section(cfg: dict) -> dict:
    """The minecraft: settings, over DEFAULTS."""
    own = (cfg or {}).get("minecraft") or {}
    mc = {**DEFAULTS, **{k: v for k, v in own.items() if v is not None}}
    mc["modes"] = {**DEFAULTS["modes"], **(own.get("modes") or {})}
    return mc


def _int(v, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if lo <= n <= hi else default


def slot(account: int, mc: dict) -> dict:
    """Who this account plays as, and where: {"name", "host", "port", "auth"}. "name" is "" when its name is not one
    Minecraft would take, which the bridge says rather than guessing at one."""
    def own(field: str) -> str:
        return (os.getenv(f"MINECRAFT_{field}_{int(account)}") or "").strip()

    host = own("HOST")
    if host:
        # Its own server: its own port with it, or Minecraft's, never the port of the server Settings names.
        port = _int(own("PORT"), 25565, 1, 65535)
    else:
        host = str(mc.get("host") or DEFAULTS["host"]).strip() or DEFAULTS["host"]
        port = _int(mc.get("port"), 25565, 1, 65535)
    auth = (own("AUTH") or str(mc.get("auth") or "offline")).lower()
    return {"name": profile_mod.clean_name(own("USERNAME")), "host": host, "port": port,
            "auth": auth if auth in ("offline", "microsoft") else "offline"}


def server_id(host: str, port: int) -> str:
    """The world, as a piece of an id ("mcs_<this>"): its host and port, in what an id may hold."""
    h = re.sub(r"[^a-z0-9.-]+", "-", str(host or "").lower()).strip("-.") or "world"
    return f"{h}-{int(port)}"


def only_chat_with(mc: dict) -> list[str]:
    """The players it only talks with, as names Minecraft takes; anything else in the list is left out."""
    raw = mc.get("only_chat_with") or []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    return [n for n in (profile_mod.clean_name(x) for x in raw if x) if n]


def mindcraft_settings(s: dict, mc: dict, profile_path: Path) -> dict:
    """mindcraft's settings (its settings.js), as SETTINGS_JSON, which mindcraft applies last, over everything else.

    What it never does here, whatever the settings say: speak through this computer's speakers (nobody in the game
    hears it), open mindcraft's own window, render what it sees, chat to other bots, narrate every small thing its
    modes do (each is a call to the model), or write and run code of its own (!newAction: a player's words become
    code running on this computer). Its language is English to mindcraft, which then translates nothing: the
    persona answers in whatever language it speaks, through the engine."""
    return {
        "minecraft_version": str(mc.get("version") or "auto").strip() or "auto",
        "host": s["host"], "port": s["port"], "auth": s["auth"],
        "mindserver_port": 0,                     # the runner picks a free one
        "auto_open_ui": False,
        "base_profile": "survival",
        "profiles": [str(profile_path)],
        "load_memory": bool(mc.get("remember_world", True)),
        "init_message": brain_mod.JOINED,
        "only_chat_with": only_chat_with(mc),
        "speak": False,
        "chat_ingame": True,
        "language": "en",
        "render_bot_view": False,
        "allow_insecure_coding": False,
        "allow_vision": False,
        "blocked_actions": list(brain_mod.BLOCKED_COMMANDS),
        "code_timeout_mins": 10,
        "relevant_docs_count": 5,
        "max_messages": _int(mc.get("max_messages"), 15, 4, 40),
        "num_examples": 2,
        "max_commands": -1,
        "show_command_syntax": "none",
        "narrate_behavior": False,
        "chat_bot_messages": False,
        "spawn_timeout": 60,
        "block_place_delay": 0,
        "log_all_prompts": False,
    }


def modes(mc: dict) -> dict:
    """The modes Settings, Minecraft switches, as mindcraft names them."""
    return {k: bool(v) for k, v in (mc.get("modes") or {}).items() if k in DEFAULTS["modes"]}


# What the runner and mindcraft are given of this process's environment: what Node and the system need to run,
# where the user's own folders are (Microsoft's sign-in is kept under them), and nothing else. Not the .env this
# worker loaded: Discord tokens, passwords, API keys.
_SYSTEM_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "USERNAME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
}


def runner_env(extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in _SYSTEM_ENV}
    env.update({k: str(v) for k, v in extra.items()})
    return env


def sync_runner() -> Path:
    """The runner, written beside mindcraft (RUNNER_DIR) so Node finds mindcraft's node_modules from it, as .mjs so
    it is a module whatever mindcraft's own package.json says; with the shared core the other runners use. Written
    only where this build's copy differs, every start, so it always matches the build."""
    src = Path(APP_DIR) / "app" / "platforms"
    RUNNER_DIR.mkdir(parents=True, exist_ok=True)
    for source, name in ((src / "minecraft" / "minecraft_runner.mjs", "minecraft_runner.mjs"),
                         (src / "minecraft" / "agent_hooks.mjs", "agent_hooks.mjs"),
                         (src / "minecraft" / "proxy_connect.mjs", "proxy_connect.mjs"),
                         # The panel's Microsoft sign-in, which needs mindcraft's prismarine-auth (ms_signin.py),
                         # and a premium account's skin changed from the panel with that login (skin_change.py).
                         (src / "minecraft" / "ms_signin.mjs", "ms_signin.mjs"),
                         (src / "minecraft" / "ms_skin.mjs", "ms_skin.mjs"),
                         (src / "snapchat" / "runner_core.js", "runner_core.mjs")):
        data = source.read_bytes()
        dst = RUNNER_DIR / name
        if not dst.exists() or dst.read_bytes() != data:
            dst.write_bytes(data)
    return RUNNER_DIR / "minecraft_runner.mjs"


class Session:
    """The brain, behind HTTP on this worker's own loopback port. bind() takes the port at once; serve() answers on
    it once the bridge's event loop is running."""

    def __init__(self, brain: brain_mod.Brain):
        self.brain = brain
        self.token = brain_mod.new_token()
        self.sock: socket.socket | None = None
        self.server = None

    def bind(self) -> str:
        """The brain's address, with its token in the path, for the profile."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        port = self.sock.getsockname()[1]
        return f"http://127.0.0.1:{port}/v1/{self.token}"

    async def serve(self) -> None:
        import uvicorn
        app = brain_mod.make_app(self.brain, self.token)
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off"))
        await self.server.serve(sockets=[self.sock])


def new_control_token() -> str:
    return secrets.token_urlsafe(32)


# ── Its password on servers that ask for one in the chat ─────────────────────
def password_key(name: str, server: str) -> str:
    """The .env key its password on a server is kept under: by its name and the server, as the server's sign-in
    plugin keeps it (renamed, it is someone new there). Two underscores between them: a name has single ones."""
    def part(x) -> str:
        return re.sub(r"[^A-Z0-9]+", "_", str(x).upper()).strip("_")
    return f"MINECRAFT_PASSWORD_{part(name)}__{part(server)}"


def new_password(length: int = 14) -> str:
    """Letters and digits, at least one of each: what every sign-in plugin's rules take."""
    import string
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def server_password(name: str, server: str) -> str:
    """Its password on this server, made the first time a server could ask for it and kept in .env (write-only,
    with the app's other secrets), so it signs in with the same one every time it comes back."""
    from app.web.envfile import read_env, write_env
    key = password_key(name, server)
    known = (os.getenv(key) or "").strip()
    if known:
        return known
    values = read_env()
    pw = str(values.get(key) or "").strip()
    if not pw:
        pw = new_password()
        values[key] = pw
        write_env(values)
    os.environ[key] = pw
    return pw


# ── A server someone names ────────────────────────────────────────────────────
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:localhost|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}"
                      r"|(?:\d{1,3}\.){3}\d{1,3})$")


def parse_address(text: str) -> tuple[str, int] | None:
    """(host, port) of a server as people write one ("play.example.net", "mc.foo.org:25570", "192.168.1.20"), or
    None for anything that is not: a word, a link to a website, a port out of range."""
    t = str(text or "").strip().strip("<>()[]\"'`").lower()
    t = re.sub(r"^(?:minecraft|mc)://", "", t).rstrip("/.")
    host, _, port = t.partition(":")
    if port:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return None
    if not _HOST_RE.match(host):
        return None
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", host) and any(int(p) > 255 for p in host.split(".")):
        return None
    return host, int(port) if port else 25565


def blocked(host: str, mc: dict) -> bool:
    """A server Settings says it never joins (by its name, or the domain it is under)."""
    raw = mc.get("never_join") or []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    host = host.lower()
    return any(host == b or host.endswith("." + b) for b in (str(x).strip().lower() for x in raw) if b)


# Big networks that let in Microsoft accounts only (online mode): an offline account is turned away at the door.
NEEDS_MICROSOFT = ("hypixel.net", "cubecraft.net", "wynncraft.com", "minemen.club", "mineplex.com", "2b2t.org")


def needs_microsoft(host: str) -> bool:
    host = str(host or "").lower()
    return any(host == d or host.endswith("." + d) for d in NEEDS_MICROSOFT)


# Why a server turned it away, when trying again changes nothing: it wants a Microsoft account (every server in online
# mode refuses an offline one), a ban, a whitelist, a client it does not take.
_FOR_GOOD_RE = re.compile(
    r"verify username|not (?:logged|signed) in(?:to)? (?:to )?(?:your |a )?(?:minecraft|microsoft|mojang)|premium|"
    r"online.mode|authenticat|invalid session|\bbanned\b|blacklist|whitelist|white-list|not white|"
    r"outdated (?:client|server)|incompatible|unsupported (?:client|version)", re.I)


def refused_for_good(reason: str) -> bool:
    """Whether a server's reason for turning it away is one that trying again does not change."""
    return bool(_FOR_GOOD_RE.search(str(reason or "")))


def away(slot: dict, target: dict) -> bool:
    """Whether it plays somewhere other than its own server."""
    def key(d: dict) -> tuple[str, int]:
        return str((d or {}).get("host") or "").lower(), _int((d or {}).get("port"), 25565, 1, 65535)
    return bool(target) and key(target) != key(slot)


# ── What it said and did, for the chat log ───────────────────────────────────
# mindcraft's own command pattern (commands/index.js commandRegex): its first match is the command it runs, and
# only the words before it are said in the game (agent.js, show_command_syntax "none").
_COMMAND_RE = re.compile(
    r'!(\w+)(?:\(((?:-?\d+(?:\.\d+)?|true|false|"[^"]*")(?:\s*,\s*(?:-?\d+(?:\.\d+)?|true|false|"[^"]*"))*)\))?')
_ARG_RE = re.compile(r'"([^"]*)"|(-?\d+(?:\.\d+)?|true|false)')

# What each command looks like done, in a few words: "follows Steve".
_DONE = {
    "goToPlayer": "goes to {0}", "followPlayer": "follows {0}", "goToCoordinates": "walks to {0} {1} {2}",
    "searchForBlock": "looks for {0}", "searchForEntity": "looks for a {0}", "moveAway": "moves away",
    "rememberHere": "remembers this place as {0}", "goToRememberedPlace": "goes back to {0}",
    "givePlayer": "gives {0} {2} {1}", "consume": "eats {0}", "equip": "equips {0}",
    "putInChest": "puts {1} {0} in a chest", "takeFromChest": "takes {1} {0} from a chest", "viewChest": "looks in a chest",
    "discard": "drops {1} {0}", "collectBlocks": "collects {1} {0}", "craftRecipe": "crafts {0}",
    "smeltItem": "smelts {1} {0}", "clearFurnace": "empties a furnace", "placeHere": "places {0}",
    "attack": "attacks a {0}", "attackPlayer": "attacks {0}", "goToBed": "goes to bed", "stay": "stays put",
    "setMode": "sets {0} {1}", "goal": "sets out to {0}", "endGoal": "stops what it set out to do", "stop": "stops",
    "lookAtPlayer": "looks at {0}", "lookAtPosition": "looks over there", "digDown": "digs down",
    "goToSurface": "goes up to the surface", "useOn": "uses {0} on {1}", "showVillagerTrades": "looks at the trades",
    "tradeWithVillager": "trades with a villager", "stats": "checks itself", "inventory": "checks its things",
    "nearbyBlocks": "looks around", "entities": "looks around", "craftable": "checks what it can craft",
    "modes": "checks its modes", "savedPlaces": "checks its saved places", "help": "checks its commands",
}


def split_reply(reply: str) -> tuple[str, str, list[str]]:
    """(the words it says, the command it runs, that command's arguments) of one of its replies."""
    text = str(reply or "")
    m = _COMMAND_RE.search(text)
    if not m:
        return text.strip(), "", []
    # findall gives "" for the alternative that did not match: a quoted text or a bare number, whichever it was.
    args = [quoted or bare for quoted, bare in _ARG_RE.findall(m.group(2) or "")]
    return text[: m.start()].strip(), m.group(1), args


def action_words(command: str, args: list[str]) -> str:
    """The command as something done, for the conversation in the panel: "*follows Steve*". An item's underscores
    read as spaces ("oak log")."""
    if not command:
        return ""
    shown = [str(a).replace("_", " ") for a in args]
    pattern = _DONE.get(command)
    if pattern is None:
        return f"*{command}*"
    try:
        words = pattern.format(*shown)
    except IndexError:
        words = re.sub(r"\s*\{\d\}", "", pattern)
    return f"*{' '.join(words.split())}*"


def chat_text(reply: str) -> str:
    """What one of its replies was, in the panel: the words players saw, then what it did."""
    said, command, args = split_reply(reply)
    done = action_words(command, args)
    return " ".join(p for p in (said, done) if p)
