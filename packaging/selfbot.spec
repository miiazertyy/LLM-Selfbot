# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the LLMSelfbot desktop app.
# onedir build (fast start, less AV flagging). No UPX.
# Run from the repo root:  pyinstaller packaging/selfbot.spec --noconfirm
#
# Produces dist/LLMSelfbot/LLMSelfbot.exe, one package containing every platform
# (Discord, Snapchat bridge, Telegram controller), the web control panel and
# the desktop window. Node/Chrome (Snapchat) and ffmpeg (voice messages) are
# fetched on demand from the System page; everything else is inside the build.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

# ── Packages that resolve things at runtime ──────────────────────────────────
# collect_all pulls submodules + data files + binaries, which matters for
# curl_cffi (bundled libcurl), certifi (CA bundle) and groq/discord metadata.
datas, binaries, hiddenimports = [], [], []
for pkg in (
    "curl_cffi",      # ships libcurl DLLs
    "certifi",        # CA bundle for requests/httpx/aiohttp
    "groq",
    "discord",        # discord.py-self
    "telegram",       # python-telegram-bot
    "webview",        # pywebview: picks its GUI backend at runtime
    "pystray",        # tray icon backend is chosen at runtime
    "uvicorn",
    "fastapi",
    "starlette",
    "anyio",
    "aiohttp",
    "yaml",
    "PIL",
    "pillow_heif",  # HEIC and AVIF, which is every iPhone photo
    "segno",       # QR code on the System page, pure Python
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:            # a package may be absent on some setups
        print(f"[spec] skipping {pkg}: {exc}")

hiddenimports += [
    # Cogs are loaded by name at runtime, so nothing imports them statically.
    "app.cogs.general",
    "app.cogs.management",
    "app.cogs.error_handler",
    # Roles the exe re-invokes itself as.
    "app.platforms.discord_runner",
    "app.platforms.snapchat_bridge",
    "app.telegram_bot.telegram_controller",
    "app.web.server",
    "app.web.supervisor",
    "app.desktop",
    # Selected by uvicorn at runtime from strings.
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.logging",
    "websockets",
    "wsproto",
    "h11",
    # FastAPI multipart uploads (pictures, backup restore).
    "multipart",
    "python_multipart",
    # Discord voice + HTTP stack.
    "nacl",
    "davey",
    "httpx",
    "httpcore",
    "requests",
    "dotenv",
    "colorama",
    "sqlite3",
]
hiddenimports += collect_submodules("app")

datas += [
    (str(ROOT / "webui" / "dist"), "webui/dist"),
    # Shipped templates, seed_data_dir() copies these into the writable data dir.
    (str(ROOT / "resources"), "resources"),
    # Node runner source; _sync_node_runner() mirrors it into DATA_DIR/snapchat.
    (str(ROOT / "app" / "platforms" / "snapchat"), "app/platforms/snapchat"),
    # The updater role imports this by path.
    (str(ROOT / "scripts" / "updater.py"), "scripts"),
]

excludes = ["tkinter", "matplotlib", "pytest", "pydoc_data", "test", "unittest"]

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
