"""What the supervisor decides to start, from the credentials on disk.

The counters used to floor at 1, so a config with no Discord token still
produced a phantom "Discord #1" that the supervisor spawned and crash-looped.
Removing that floor only works if the supervisor actually reads .env, it never
did, which would have flipped the bug to "starts nothing". Both halves are
checked here.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="plan_test_"))
(SANDBOX / "config").mkdir(parents=True)
shutil.copy(ROOT / "resources" / "config.yaml", SANDBOX / "config" / "config.yaml")

import app.utils.paths as paths
paths.DATA_DIR = SANDBOX
paths.seed_data_dir = lambda: None
import app.utils.helpers as helpers
helpers.resource_path = lambda rel: str(
    (SANDBOX if rel.replace("\\", "/").split("/")[0] in ("config", "ipc") else paths.APP_DIR) / rel)
helpers.get_env_path = lambda: str(SANDBOX / "config" / ".env")

import app.core.ipc as ipc
import app.cli as cli

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def set_env_file(text):
    (SANDBOX / "config" / ".env").write_text(text, encoding="utf-8")
    for k in list(os.environ):
        if k.startswith(("DISCORD_TOKEN", "DISCORD_PROXY", "SNAP_USERNAME", "SNAP_PASSWORD")):
            os.environ.pop(k, None)
    cli.load_env()


def planned():
    from app.web.supervisor import Supervisor
    return Supervisor(port=0)._planned_children()


print("\n== no credentials at all ==")
set_env_file("GROQ_API_KEY_1=gsk_fake\n")
check("counter reports 0 discord accounts", ipc._count_accounts() == 0, str(ipc._count_accounts()))
check("counter reports 0 snapchat accounts", ipc._count_snap_accounts() == 0)
check("no IPC targets discovered", ipc.discover_targets() == {}, str(ipc.discover_targets()))
plan = planned()
check("supervisor plans NO discord child", not any(k.startswith("discord") for k in plan), str(plan))
check("supervisor plans NO snapchat child", not any(k.startswith("snapchat") for k in plan), str(plan))

print("\n== two discord tokens ==")
set_env_file("DISCORD_TOKEN_1=aaa\nDISCORD_TOKEN_2=bbb\nGROQ_API_KEY_1=gsk_fake\n")
check("supervisor reads .env itself", ipc._count_accounts() == 2, str(ipc._count_accounts()))
plan = planned()
check("plans exactly two discord children",
      sorted(k for k in plan if k.startswith("discord")) == ["discord_1", "discord_2"], str(plan))
check("targets discovered for both", len(ipc.discover_targets()) == 2, str(ipc.discover_targets()))

print("\n== legacy unsuffixed token still works ==")
set_env_file("DISCORD_TOKEN=legacy\nGROQ_API_KEY_1=gsk_fake\n")
check("counted as one account", ipc._count_accounts() == 1, str(ipc._count_accounts()))

print("\n== snapchat only starts with a username ==")
set_env_file("DISCORD_TOKEN_1=aaa\nSNAP_USERNAME=someone\nSNAP_PASSWORD=pw\n")
check("snap counter sees one", ipc._count_snap_accounts() == 1, str(ipc._count_snap_accounts()))
set_env_file("DISCORD_TOKEN_1=aaa\n")
check("and none once it is gone", ipc._count_snap_accounts() == 0, str(ipc._count_snap_accounts()))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
shutil.rmtree(SANDBOX, ignore_errors=True)
sys.exit(1 if FAIL else 0)
