"""What goes into a build, shared by every spec.

There are four builds: Windows folder (what the installer wraps) and Windows
single file, plus headless folder and headless single file for Linux, ARM and
macOS. They must contain the same things, and the list is long and easy to get
wrong: a hidden import added to one spec and forgotten in the others produces a
build that starts fine and then dies the moment that module is first needed,
which is in front of a user rather than in CI. The Linux spec had drifted to a
much shorter list than Windows for exactly that reason.

So the list lives here once and every spec asks for it.

The only real difference between them is the desktop shell. Windows opens a
native window; everywhere else the app serves the same panel and you open it in
a browser, so the GUI packages are left out entirely. pywebview and pystray have
no headless backend worth shipping, and app/desktop.py cannot even be imported
off Windows because app/utils/backdrop.py reaches for ctypes.wintypes.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Packages that resolve things at runtime. collect_all pulls submodules, data
# files and binaries, which matters for curl_cffi (bundled libcurl), certifi
# (CA bundle) and groq/discord metadata.
_COLLECT = (
    "curl_cffi",      # ships libcurl DLLs
    "certifi",        # CA bundle for requests/httpx/aiohttp
    "groq",
    "openai",         # the local AI provider speaks the OpenAI API
    "discord",        # discord.py-self
    "telegram",       # python-telegram-bot
    "uvicorn",
    "fastapi",
    "starlette",
    "anyio",
    "aiohttp",
    "yaml",
    "PIL",
    "pillow_heif",    # HEIC and AVIF, which is every iPhone photo
    "segno",          # QR code on the System page, pure Python
)

# Only in the windowed build.
_COLLECT_GUI = (
    "webview",        # pywebview: picks its GUI backend at runtime
    "pystray",        # tray icon backend is chosen at runtime
)

_HIDDEN = [
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

EXCLUDES = ["tkinter", "matplotlib", "pytest", "pydoc_data", "test", "unittest"]


def build_parts(root, gui=True):
    """(datas, binaries, hiddenimports, excludes) for one build.

    gui=False drops the desktop shell, for the headless builds that serve the
    panel to a browser instead of opening a window.
    """
    datas, binaries, hiddenimports = [], [], []
    excludes = list(EXCLUDES)

    for pkg in _COLLECT + (_COLLECT_GUI if gui else ()):
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception as exc:        # a package may be absent on some setups
            print(f"[spec] skipping {pkg}: {exc}")

    hiddenimports += _HIDDEN
    app_modules = collect_submodules("app")

    if gui:
        hiddenimports += ["app.desktop"]
    else:
        # collect_submodules walks the whole package, so it finds the desktop
        # shell whether or not this build wants it. Dropped by name as well as
        # excluded, rather than trusting exclusion to win: app.utils.backdrop
        # does `from ctypes import wintypes` at import time, which does not
        # exist off Windows and takes the whole analysis down with it.
        skip = ("app.desktop", "app.utils.backdrop")
        app_modules = [m for m in app_modules if m not in skip]
        excludes += ["webview", "pywebview", "pystray", *skip]

    hiddenimports += app_modules

    datas += [
        (str(root / "webui" / "dist"), "webui/dist"),
        # Shipped templates, seed_data_dir() copies these into the data dir.
        (str(root / "resources"), "resources"),
        # Node runner source; _sync_node_runner() mirrors it into DATA_DIR.
        (str(root / "app" / "platforms" / "snapchat"), "app/platforms/snapchat"),
        # The updater role imports this by path.
        (str(root / "scripts" / "updater.py"), "scripts"),
    ]

    return datas, binaries, hiddenimports, excludes
