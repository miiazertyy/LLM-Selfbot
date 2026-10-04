import json
import os
import time

from datetime import datetime
from pathlib import Path
from app.utils.helpers import load_config, resource_path


def print_error(error_type, error):
    print(f"{datetime.now().strftime('[%H:%M:%S]')} {error_type}: {error}")


async def webhook_log(ctx, error, is_ratelimit=False):
    # Imported here, not at the top: this module is reached from the panel's own
    # imports (through app.utils.ai), and a build without Discord (the iPhone
    # app, which has no curl_cffi) still has to be able to start the panel.
    import discord
    from curl_cffi.requests import AsyncSession

    config = load_config()  # Always reload so webhook URL changes are picked up live
    webhook_url = config["notifications"]["error_webhook"]

    if not webhook_url:
        return

    # Rate limit notifications can be silenced separately
    if is_ratelimit and not config["notifications"]["ratelimit_notifications"]:
        return
    if is_ratelimit:
        embed = discord.Embed(
            title="LLMSelfbot Ratelimited",
            description=f"{error}",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
    elif isinstance(ctx, discord.Message):
        embed = discord.Embed(
            title="LLMSelfbot Error",
            description=f"Message: `{ctx.content}`\nTrigger: {ctx.jump_url}\nError: `{error}`",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
    elif isinstance(ctx, discord.ext.commands.Context):
        embed = discord.Embed(
            title="LLMSelfbot Error",
            description=f"Command: `{ctx.command}`\nTrigger: {ctx.message.jump_url}\nError: `{error}`",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
    else:
        embed = discord.Embed(
            title="LLMSelfbot Error",
            description=f"Error: `{error}`",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )

    data = {
        "username": "LLMSelfbot",
        "avatar_url": "https://cdn.discordapp.com/avatars/1040916971635621959/a_e52b4f8a9115021e5cc2e510232e8bd8.gif?size=256",
        "embeds": [embed.to_dict()],
    }

    try:
        async with AsyncSession(impersonate="chrome") as session:
            response = await session.post(webhook_url, json=data)
            if response.status_code != 204:
                print_error("Webhook Error", f"Status: {response.status_code}")
    except Exception as e:
        print(f"Error while sending webhook: {e}")


# telegram error relay: the discord runner drops a "send_error_notification" entry into its own IPC command file and the telegram controller polls that file and DMs the owner

def notify_telegram_error(title: str, detail: str):
    """Queue an error for the Telegram controller (no-op when disabled)."""
    try:
        cfg = load_config()
        if not cfg.get("notifications", {}).get("telegram_error_notifications", False):
            return
        # One command file per Discord account; the runner pins the index.
        index = os.environ.get("DISCORD_ACCOUNT_INDEX", "1")
        cmd_file = Path(resource_path(f"config/tg_commands_{index}.json"))

        entries = []
        if cmd_file.exists():
            try:
                loaded = json.loads(cmd_file.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    entries = loaded
            except Exception:
                pass
        entries.append({
            "id": f"err_{time.time()}",
            "cmd": "send_error_notification",
            "payload": {"title": title, "detail": str(detail)[:1500]},
            "ts": time.time(),
        })
        from app.utils.atomic import write_json_atomic
        write_json_atomic(cmd_file, entries)
    except Exception:
        pass
