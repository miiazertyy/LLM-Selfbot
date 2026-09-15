# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for every platform without the native window: Linux x86_64,
# Linux aarch64 and macOS. Run from the repo root:
#   pyinstaller packaging/selfbot-headless.spec --noconfirm
#
# Same application as the Windows build, minus the desktop shell. It serves the
# control panel on 127.0.0.1:8787 and you open that in a browser, which is what
# makes it useful on a server, a Raspberry Pi or over Tailscale.
#
# Produces dist/selfbot/selfbot plus its _internal folder. For a single file
# with nothing beside it, see selfbot-headless-onefile.spec.
#
# The contents come from specparts.py, shared with the Windows specs, so a
# hidden import added for one platform is added for all of them. This file used
# to carry its own much shorter list and quietly lacked things the Windows build
# had.

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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="selfbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="selfbot",
)
