import os
import shutil
import sys
from pathlib import Path


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


if _frozen():
    APP_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    APP_DIR = Path(__file__).resolve().parent.parent.parent


# Making a folder called "portable" next to the app is the whole opt in: no
# marker file to write, no setting to find. Everything then lives in it, so the
# app can be carried on a stick or kept entirely inside its own folder.
PORTABLE_DIR_NAME = "portable"


def portable_root() -> Path | None:
    """The portable folder beside the app, if someone has made one."""
    base = Path(sys.executable).resolve().parent if _frozen() else APP_DIR
    candidate = base / PORTABLE_DIR_NAME
    return candidate if candidate.is_dir() else None


def _resolve_data_dir() -> Path:
    portable = portable_root()
    if portable is not None:
        return portable
    if not _frozen():
        return APP_DIR
    exe_dir = Path(sys.executable).resolve().parent
    # The older opt in, kept working for anyone already using it.
    if (exe_dir / "portable.txt").exists():
        return exe_dir / "data"
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LLMSelfbot"


def is_portable() -> bool:
    return portable_root() is not None


DATA_DIR = _resolve_data_dir()

REQUIRED_SUBDIRS = [
    DATA_DIR / "config" / "pictures",
    DATA_DIR / "config" / "temp",
    DATA_DIR / "ipc",
    DATA_DIR / "logs",
    DATA_DIR / "backups",
    DATA_DIR / "snapchat",
]


# Shipped templates. config/ is pure runtime state (gitignored) and is seeded
# from here on first run, identical in a source checkout and a frozen build, so
# the seeding path is actually exercised during development.
DEFAULTS_DIR = APP_DIR / "resources"

_SEED_FILES = (
    ("config.yaml", "config.yaml"),
    ("instructions.txt", "instructions.txt"),
    ("example.env", ".env"),
)


def seed_data_dir() -> None:
    for d in REQUIRED_SUBDIRS:
        d.mkdir(parents=True, exist_ok=True)
    cfg = DATA_DIR / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in _SEED_FILES:
        src, dst = DEFAULTS_DIR / src_name, cfg / dst_name
        if src.exists() and not dst.exists():
            shutil.copyfile(src, dst)
        elif src_name == "instructions.txt" and src.exists() and dst.exists():
            # Upgrade pre-style-guide installs: an empty/blank file gets the
            # shipped template; anything the user actually wrote is kept.
            try:
                if not dst.read_text(encoding="utf-8", errors="replace").strip():
                    shutil.copyfile(src, dst)
            except OSError:
                pass

    # Keep the annotated template beside the live .env as a reference, and
    # refresh it every start so it never drifts behind the shipped version.
    # It is only documentation, nothing reads it as configuration.
    reference = DEFAULTS_DIR / "example.env"
    if reference.exists():
        try:
            shutil.copyfile(reference, cfg / "example.env")
        except OSError:
            pass        # a read-only data dir must not stop the app booting

    prune_dead_settings()


# Settings for features that no longer exist. config/ is seeded once and then
# never touched again, so removing a feature from the code leaves its settings
# sitting in everyone's file forever, showing up in the editor as options that
# do nothing.
_DEAD_CONFIG_KEYS = (
    ("bot", "captcha"),          # the captcha solver, and its Gemini model
)
_DEAD_ENV_KEYS = ("GEMINI_API_KEY",)


def prune_dead_settings() -> None:
    """Drop settings belonging to features that have been removed."""
    cfg = DATA_DIR / "config"
    _prune_config(cfg / "config.yaml")
    for name in (".env", ".env.bak"):
        _prune_env(cfg / name)


def _prune_config(path) -> bool:
    if not path.exists():
        return False
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False

    changed = False
    for section, key in _DEAD_CONFIG_KEYS:
        parent = data.get(section)
        if isinstance(parent, dict) and key in parent:
            parent.pop(key)
            changed = True
    if not changed:
        return False
    try:
        path.write_text(
            yaml.safe_dump(data, default_flow_style=False, allow_unicode=True,
                           sort_keys=False),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


def _prune_env(path) -> bool:
    """Remove a dead variable and the comment heading that introduced it."""
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except OSError:
        return False

    kept, changed = [], False
    for line in lines:
        name = line.split("=", 1)[0].strip().lstrip("#").strip()
        if "=" in line and name in _DEAD_ENV_KEYS:
            changed = True
            # The "# --- Gemini API ---" banner above it is now a heading over
            # nothing, so it goes too.
            while kept and (kept[-1].lstrip().startswith("#") or not kept[-1].strip()):
                dropped = kept.pop()
                if dropped.strip() and not dropped.lstrip().startswith("#"):
                    kept.append(dropped)
                    break
            continue
        kept.append(line)

    if not changed:
        return False
    # Collapse the run of blank lines the removal can leave behind.
    out = []
    for line in kept:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    try:
        path.write_text("\n".join(out), encoding="utf-8")
    except OSError:
        return False
    return True


def is_writable_state(relative_path: str) -> bool:
    p = relative_path.replace("\\", "/").strip("/")
    return p == "config" or p.startswith("config/") or p == "ipc" or p.startswith("ipc/")
