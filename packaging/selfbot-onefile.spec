# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the single file build: one LLMSelfbot.exe, nothing beside
# it. Run from the repo root:  pyinstaller packaging/selfbot-onefile.spec --noconfirm
#
# This is the same application as selfbot.spec, packed differently, and the
# difference is worth knowing before choosing it:
#
#   * every launch unpacks the whole bundle into a temporary folder first, so
#     it takes a few seconds to appear rather than opening straight away
#   * a single file that unpacks itself and then spawns copies of itself is
#     exactly the shape antivirus heuristics look for, so it is flagged more
#     often than the folder build
#
# The folder build (selfbot.spec) and the installer are the better default. This
# exists for people who want one file to carry around.
#
# The imports and data are deliberately shared with selfbot.spec through
# specparts.py, so the two builds cannot drift apart: a hidden import added for
# one is added for both.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(Path(SPECPATH)))

from specparts import build_parts

datas, binaries, hiddenimports, excludes = build_parts(ROOT)

a = Analysis(
    [str(ROOT / "app" / "desktop.py")],
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

icon = str(ROOT / "resources" / "icon.ico") if (ROOT / "resources" / "icon.ico").exists() else None

# Everything goes inside the EXE: no exclude_binaries, no COLLECT.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LLMSelfbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # windowed; main.py gives stdout a sink when it is None
    icon=icon,
)
