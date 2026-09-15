# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Linux (x86_64 and aarch64), headless supervisor + web UI.
# No GUI shell, the server serves the same Svelte UI on 127.0.0.1:8787,
# so it runs on servers / Raspberry Pi / ARM boards, opened in a browser.
# Lives in packaging/, run: pyinstaller packaging/selfbot-linux.spec --noconfirm

from pathlib import Path

# SPECPATH is the directory holding this file, so one .parent reaches the repo
# root. Two put it above the checkout, which made every path here point at
# somewhere that does not exist: the build died on "script '/main.py' not
# found". selfbot.spec next door has always had this right.
ROOT = Path(SPECPATH).parent

hiddenimports = [
    "app.cogs.general",
    "app.cogs.management",
    "app.cogs.error_handler",
    "groq",
    "discord",
    "discord.gateway",
    "telegram",
    "telegram.ext",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.loops.auto",
    "uvicorn.logging",
    "uvicorn.protocols.utils",
    "curl_cffi",
    "dotenv",
    "yaml",
    "PIL",
]

datas = [
    (str(ROOT / "webui" / "dist"), "webui/dist"),
    # Shipped templates, seed_data_dir() copies these into the writable data dir.
    (str(ROOT / "resources"), "resources"),
    (str(ROOT / "app" / "platforms" / "snapchat" / "snapchat_runner.js"), "app/platforms/snapchat"),
    (str(ROOT / "app" / "platforms" / "snapchat" / "snapbot.js"), "app/platforms/snapchat"),
    (str(ROOT / "app" / "platforms" / "snapchat" / "log.js"), "app/platforms/snapchat"),
    (str(ROOT / "app" / "platforms" / "snapchat" / "package.json"), "app/platforms/snapchat"),
]

excludes = [
    "tkinter", "matplotlib", "test", "unittest", "pydoc_data",
    "pystray", "webview", "pywebview",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
