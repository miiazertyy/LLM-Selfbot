import os
import shutil
import sys
from datetime import datetime
from colorama import Fore, Style

RESET = "\033[0m"

# Every log line uses box-drawing and symbol glyphs. When stdout is not a UTF-8
# console, piped output, a redirected log file, or a subprocess started by
# main.py on Windows, printing them raises UnicodeEncodeError, taking down
# whatever was logging (including the Groq key-rotation path).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Per-platform accent palette ──────────────────────────────────────────────
# set_theme() distinguishes Discord (blurple) and Snapchat (gold) output in a
# shared console.
def _supports_truecolor() -> bool:
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return True
    if os.environ.get("WT_SESSION") or os.environ.get("WT_PROFILE_ID"):  # Windows Terminal
        return True
    if os.name != "nt":  # most modern macOS/Linux terminals
        return True
    return False


_TRUECOLOR = _supports_truecolor()

if _TRUECOLOR:
    _THEMES = {
        # (accent, soft accent) as 24-bit truecolor
        "discord":  ("\033[38;2;88;101;242m", "\033[38;2;67;78;180m"),    # Discord blurple
        "snapchat": ("\033[38;2;255;196;37m", "\033[38;2;191;143;18m"),   # Snapchat gold
    }
else:
    _THEMES = {
        "discord":  (Fore.LIGHTBLUE_EX,   Fore.BLUE),
        "snapchat": (Fore.LIGHTYELLOW_EX, Fore.YELLOW),
    }

# Default until a runner picks one.
_ACCENT, _ACCENT_SOFT = _THEMES["discord"]


def set_theme(platform: str):
    """Select the accent palette for this process ('discord' or 'snapchat')."""
    global _ACCENT, _ACCENT_SOFT
    key = "snapchat" if str(platform).lower().startswith("snap") else "discord"
    _ACCENT, _ACCENT_SOFT = _THEMES.get(key, _THEMES["discord"])


def get_width():
    columns, _ = shutil.get_terminal_size()
    return columns


def separator(char="─"):
    print(f"{_ACCENT_SOFT}{char * (get_width() - 2)}{RESET}")


def timestamp():
    return f"{Fore.LIGHTBLACK_EX}{datetime.now().strftime('%H:%M:%S')}{RESET}"


def log_incoming(author: str, channel: str, guild: str, content: str):
    print(
        f"{timestamp()} "
        f"{Style.BRIGHT}{Fore.WHITE}{author}{RESET} "
        f"{Fore.LIGHTBLACK_EX}in #{channel} ({guild}){RESET}"
        f"\n  {_ACCENT}▸{RESET} {content}"
    )


def log_response(author: str, chunk: str, model: str = None):
    model_tag = f" {Fore.LIGHTBLACK_EX}[{model}]{RESET}" if model else ""
    print(
        f"{timestamp()} "
        f"{_ACCENT}{Style.BRIGHT}Responding to {author}{RESET}{model_tag}"
        f"\n  {_ACCENT}▸{RESET} {chunk}"
    )


def log_rate_limit(wait: int, model: str = None):
    model_tag = f" on {model}" if model else ""
    print(
        f"{timestamp()} {Fore.YELLOW}{Style.BRIGHT}⚠ RATE LIMITED{model_tag}, waiting {wait}s{RESET}"
    )


def log_model_fallback(from_model: str, to_model: str):
    print(
        f"{timestamp()} {Fore.YELLOW}⟳ Model fallback: {Style.BRIGHT}{from_model}{Style.NORMAL} → {to_model}{RESET}"
    )


def log_error(context: str, error: str):
    print(
        f"{timestamp()} {Fore.RED}{Style.BRIGHT}✗ {context}:{RESET} {Fore.RED}{error}{RESET}"
    )


def log_system(msg: str):
    print(f"{timestamp()} {_ACCENT}⚙{RESET} {msg}")


def log_cooldown(username: str, remaining: int):
    print(
        f"{timestamp()} {Fore.YELLOW}⏱ {username} is on cooldown for {remaining}s{RESET}"
    )


def log_received(author: str, channel: str, guild: str, wait: int):
    if wait == 0:
        print(
            f"{timestamp()} "
            f"{Style.BRIGHT}{Fore.WHITE}{author}{RESET} "
            f"{Fore.LIGHTBLACK_EX}in #{channel} ({guild}){RESET} "
            f"{Fore.RED}→ priority, responding immediately{RESET}"
        )
        return
    wait_str = f"{wait}s" if wait < 60 else f"{wait // 60}m {wait % 60}s" if wait % 60 else f"{wait // 60}m"
    print(
        f"{timestamp()} "
        f"{Style.BRIGHT}{Fore.WHITE}{author}{RESET} "
        f"{Fore.LIGHTBLACK_EX}in #{channel} ({guild}){RESET} "
        f"{_ACCENT_SOFT}→ waiting {wait_str} before responding{RESET}"
    )
