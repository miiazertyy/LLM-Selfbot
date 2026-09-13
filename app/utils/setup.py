import os
import yaml
import requests

from time import sleep
from colorama import init, Fore, Style
from app.utils.helpers import resource_path, clear_console

init()


def validate_token(token):
    headers = {"Authorization": token}
    try:
        r = requests.get("https://discord.com/api/v10/users/@me", headers=headers)
        return r.status_code == 200
    except:
        return False


def validate_api_key(api_key, provider="openai"):
    if provider == "openai":
        if not api_key.startswith("sk-"):
            return False
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            r = requests.get("https://api.openai.com/v1/models", headers=headers)
            return r.status_code == 200
        except:
            return False
    elif provider == "groq":
        if not api_key.startswith("gsk_"):
            return False
        return True
    return False


def get_input(prompt, validator=None, default=None, password=False):
    while True:
        if (
            default is not None
            and prompt == "Enter error webhook URL (optional - press enter to skip)"
        ):
            user_input = input(f"{prompt} (default: {default}): ").strip()
            if not user_input:
                return default
        else:
            if password:
                import getpass

                user_input = getpass.getpass(prompt + ": ").strip()
            else:
                user_input = input(prompt + ": ").strip()

        if not user_input and default is None:
            print(f"{Fore.RED}Input cannot be empty!{Style.RESET_ALL}")
            continue

        if validator:
            if validator(user_input):
                return user_input
            print(f"{Fore.RED}Invalid input! Please try again.{Style.RESET_ALL}")
            continue

        return user_input


def create_config():
    clear_console()

    print(f"\n{Fore.CYAN}=== LLMSelfbot Setup Wizard ==={Style.RESET_ALL}\n")

    config = {
        "bot": {
            "owner_id": int(
                get_input(
                    "Enter your Discord user ID (can't be same as bot id)",
                    lambda x: x.isdigit(),
                )
            ),
            "prefix": get_input("Enter command prefix", default="~"),
            "trigger": get_input(
                "Enter trigger word(s) (comma-separated for multiple)"
            ),
            # groq_models is a list, the AI module reads config["bot"]["groq_models"]
            "groq_models": ["llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct"],
            "groq_image_model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "groq_whisper_model": "whisper-large-v3-turbo",
            "allow_dm": input("Allow DMs? (y/n): ").lower() == "y",
            "allow_gc": input("Allow group chats? (y/n): ").lower() == "y",
            "allow_server": True,
            "realistic_typing": input("Enable realistic typing? (y/n): ").lower()
            == "y",
            "batch_messages": True,
            "batch_wait_times": [
                {"time": 20, "weight": 30},
                {"time": 40, "weight": 35},
                {"time": 90, "weight": 22},
                {"time": 600, "weight": 10},
                {"time": 1600, "weight": 3},
            ],
            "ignore_chance": 0.08,
            "typo_chance": 0.03,
            "priority_prefix": "=",
            "hold_conversation": True,
            "anti_age_ban": False,
            "disable_mentions": False,
            "reply_ping": True,
            "mood": {
                "enabled": True,
                "shift_interval_min": 1800,
                "shift_interval_max": 3600,
                "moods": {
                    "chill": "Be relaxed and unbothered. Keep replies easy-going, don't overthink.",
                    "playful": "Be playful and energetic. Tease more, be funnier than usual.",
                    "busy": "You're distracted. Keep replies short, slightly impatient.",
                    "tired": "You're tired. Low energy, shorter replies, less enthusiasm.",
                    "annoyed": "You're mildly annoyed. Be blunt and less patient, but not rude.",
                    "flirty": "Be flirty and a bit more suggestive than usual.",
                },
            },
            "status": {
                "enabled": True,
                "change_interval_min": 1800,
                "change_interval_max": 10800,
                "statuses": ["online", "idle", "dnd"],
            },
            "late_reply": {
                "enabled": True,
                "threshold": 300,
                "openers_en": [
                    "sorry was watching tiktok lol ",
                    "omg sorry just saw this ",
                    "sorry was busy haha ",
                    "oh sorry didn't see this ",
                ],
                "openers_fr": [
                    "déso je viens de voir lol ",
                    "pardon j'étais occupée haha ",
                    "mdrr déso je t'avais pas vu ",
                ],
                "french_indicators": ["salut", "bonjour", "quoi", "tu", "je", "ouais", "oui", "non"],
            },
            "stale_reply": {"enabled": False, "max_messages": 10, "min_age": 120},
            "friend_requests": {
                "enabled": True,
                "accept_delay_min": 120,
                "accept_delay_max": 600,
            },
            "nudge": {
                "enabled": False,
                "threshold_days": 2,
                "check_interval_hours": 6,
                "send_during_hours": [10, 22],
            },
            "tts": {"enabled": False, "voice": "diana", "tones": ["[casual]", "[warm]"]},
        },
        # notifications must be a top-level key, readers use config.get("notifications")
        "notifications": {
            "error_webhook": get_input(
                "Enter error webhook URL (optional - press enter to skip)",
                lambda x: x.startswith("https://discord.com/api/webhooks/") or not x,
                default="",
            ),
            "ratelimit_notifications": input(
                "Enable webhook ratelimit notifications? (y/n): "
            ).lower()
            == "y",
            "telegram_error_notifications": False,
        },
    }

    token = get_input(
        "Enter Discord token (input will be hidden)", validate_token, password=True
    )
    api_keys = {"DISCORD_TOKEN": token}

    import getpass as _gp
    groq_key = _gp.getpass("Enter Groq API key (press enter to skip): ").strip()
    while groq_key and not validate_api_key(groq_key, provider="groq"):
        print(f"{Fore.RED}Invalid input! Please try again.{Style.RESET_ALL}")
        groq_key = _gp.getpass("Enter Groq API key (press enter to skip): ").strip()
    if groq_key:
        api_keys["GROQ_API_KEY"] = groq_key

    config_dir = resource_path("config")
    os.makedirs(config_dir, exist_ok=True)

    with open(os.path.join(config_dir, ".env"), "w") as f:
        for key, value in api_keys.items():
            f.write(f"{key}={value}\n")

    with open(os.path.join(config_dir, "config.yaml"), "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False)

    print(f"\n{Fore.GREEN}Setup complete! Configuration saved.{Style.RESET_ALL}")
    print(
        f"\n{Fore.LIGHTBLACK_EX}For help or support, join: https://discord.gg/yUWmzQBV4P{Style.RESET_ALL}"
    )

    sleep(3)


if __name__ == "__main__":
    create_config()
