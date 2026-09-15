"""What goes into a Windows build, shared by both specs.

There are two Windows builds now: the folder one behind the installer, and the
single file one. They must contain exactly the same things, and the list is long
and easy to get wrong: a hidden import added to one spec and forgotten in the
other produces a build that starts and then fails at the moment the missing
module is first needed, which is usually in front of a user rather than in CI.

So the list lives here once, and both specs ask for it.
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
    "webview",        # pywebview: picks its GUI backend at runtime
    "pystray",        # tray icon backend is chosen at runtime
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

EXCLUDES = ["tkinter", "matplotlib", "pytest", "pydoc_data", "test", "unittest"]


def build_parts(root):
    """(datas, binaries, hiddenimports, excludes) for a Windows build."""
    datas, binaries, hiddenimports = [], [], []

    for pkg in _COLLECT:
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception as exc:        # a package may be absent on some setups
            print(f"[spec] skipping {pkg}: {exc}")

    hiddenimports += _HIDDEN
    hiddenimports += collect_submodules("app")

    datas += [
        (str(root / "webui" / "dist"), "webui/dist"),
        # Shipped templates, seed_data_dir() copies these into the data dir.
        (str(root / "resources"), "resources"),
        # Node runner source; _sync_node_runner() mirrors it into DATA_DIR.
        (str(root / "app" / "platforms" / "snapchat"), "app/platforms/snapchat"),
        # The updater role imports this by path.
        (str(root / "scripts" / "updater.py"), "scripts"),
    ]

    return datas, binaries, hiddenimports, list(EXCLUDES)
