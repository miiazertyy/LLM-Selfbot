# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the LLMSelfbot desktop app.
# onedir build (fast start, less AV flagging). No UPX.
# Run from the repo root:  pyinstaller packaging/selfbot.spec --noconfirm
#
# Produces dist/LLMSelfbot/LLMSelfbot.exe, one package containing every platform
# (Discord, Snapchat bridge, Telegram controller), the web control panel and
# the desktop window. Node/Chrome (Snapchat) and ffmpeg (voice messages) are
# fetched on demand from the System page; everything else is inside the build.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(Path(SPECPATH)))

# Shared with selfbot-onefile.spec. Both Windows builds must contain exactly the
# same things, and a hidden import added to one and forgotten in the other gives
# a build that starts fine and then dies the moment that module is first needed,
# which is in front of a user rather than in CI.
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LLMSelfbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed; main.py gives stdout a sink when it is None
    icon=icon,
)

# Same code, console attached - for reading tracebacks when something misbehaves.
exe_console = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LLMSelfbot-console",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=icon,
)

coll = COLLECT(
    exe,
    exe_console,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LLMSelfbot",
)
