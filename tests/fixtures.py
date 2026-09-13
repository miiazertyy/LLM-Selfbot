"""Shared setup for tests that need a config file to exist.

config/ is runtime state: it is gitignored, and the app creates it on first run
by copying the templates out of resources/. So on a developer's machine it is
always there, and on a fresh checkout it never is. Three test modules called
load_config() directly and passed locally for months while failing on every CI
run with "Config file not found".

Seeding a sandbox from resources/ fixes both halves of that. The tests stop
depending on a file that only exists once you have run the app, and they read
the config the project actually ships rather than whatever the person running
them happens to have edited, which for a test that asks "is every setting
reachable from the UI?" is the more honest question anyway.

Import this before anything that reads the config, since resource_path has to
be patched before the first call caches a path.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_sandbox = None


def use_shipped_config() -> Path:
    """Point the app's config lookups at a fresh copy of resources/.

    Returns the sandbox root. Safe to call more than once; the copy is made
    once per process.
    """
    global _sandbox
    if _sandbox is not None:
        return _sandbox

    _sandbox = Path(tempfile.mkdtemp(prefix="llmbot_cfg_"))
    (_sandbox / "config").mkdir(parents=True)
    for name in ("config.yaml", "instructions.txt"):
        src = ROOT / "resources" / name
        if src.exists():
            shutil.copyfile(src, _sandbox / "config" / name)
    (_sandbox / "config" / ".env").write_text("", encoding="utf-8")

    import app.utils.paths as paths
    paths.DATA_DIR = _sandbox
    paths.seed_data_dir = lambda: None

    import app.utils.helpers as helpers
    helpers.resource_path = lambda rel: str(
        (_sandbox if rel.replace("\\", "/").split("/")[0] in ("config", "ipc")
         else ROOT) / rel)
    helpers.invalidate_config_cache()

    return _sandbox
