# -*- mode: python ; coding: utf-8 -*-
# Single file build for Linux x86_64, Linux aarch64 and macOS: one `selfbot`
# binary with nothing beside it. Run from the repo root:
#   pyinstaller packaging/selfbot-headless-onefile.spec --noconfirm
#
# The same trade as on Windows. One file is far easier to drop on a server or
# carry to a Pi, but every launch unpacks the whole bundle into a temp folder
# first, so it takes a few seconds to answer rather than starting at once. The
# folder build next door (selfbot-headless.spec) starts immediately.
#
# Contents come from specparts.py, shared with every other spec.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(Path(SPECPATH)))

from specparts import build_parts

datas, binaries, hiddenimports, excludes = build_parts(ROOT, gui=False)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# Everything inside the binary: no exclude_binaries, no COLLECT.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="selfbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)
