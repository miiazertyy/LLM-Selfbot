"""
Which socials are switched on.

Each one has two switches in config.yaml: services.<name>.enabled (does it start with the app) and <name>.enabled (its
own section). It is on only when both are. A switch that is not written down counts as on, so everything is on until
someone turns it off. One that is off is not run, and the panel shows it nowhere: not its accounts, not its tab in
Settings, not a way to add one.
"""
from __future__ import annotations

from app.platforms import registry

SOCIALS = registry.IDS

# The persona's own Telegram accounts start on services.telegram_accounts. services.telegram is the bot that controls
# the app, which is not a social and is never hidden.
_SERVICE = {"telegram": "telegram_accounts"}


#: Every key that switches a social on or off.
SWITCHES = frozenset([f"{name}.enabled" for name in SOCIALS]
                     + [f"services.{_SERVICE.get(name, name)}.enabled" for name in SOCIALS])


def _switch(section) -> bool:
    if not isinstance(section, dict):
        return True
    return bool(section.get("enabled", True))


def on(config: dict | None = None) -> dict:
    """{social: True when it is on}, for every social."""
    if config is None:
        from app.utils.helpers import load_config
        try:
            config = load_config()
        except Exception:
            config = {}
    config = config or {}
    services = config.get("services") or {}
    return {name: _switch(config.get(name)) and _switch(services.get(_SERVICE.get(name, name)))
            for name in SOCIALS}


def child_shown(role, account, switches: dict | None = None) -> bool:
    """Whether one of the supervisor's workers belongs on screen, by on() (asked for when not given). The control bot
    (role "telegram" with no account) is not a social and always does."""
    if role == "telegram" and account is None:
        return True
    return (switches if switches is not None else on()).get(role, True)


def shown(platform: str, config: dict | None = None) -> bool:
    """Whether a platform's things belong on screen. Anything that is not one of the socials always does."""
    return on(config).get(platform, True)
