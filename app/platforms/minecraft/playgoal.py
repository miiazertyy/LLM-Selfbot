"""The standing goal a Minecraft account plays at when nobody has given it one (agent_hooks.mjs keepPlaying).

Here on its own, with nothing imported, so Settings' schema can show it as the setting's default without loading the
worker. Without a standing goal it only ever played when told to, and in a busy lobby it stood and talked
("make sure the ai thinks more about playing than talking", 2026-11-11).
"""

DEFAULT_PLAY_GOAL = (
    "Play this server's game well, the way a skilled player would, and keep making progress on your own. "
    "Look at your inventory and what is around you first, then plan a few steps ahead. On SkyBlock, build up your "
    "island: a cobblestone generator, trees, farms, chests, better tools, and use the island's own commands. On "
    "survival, gather wood and stone, craft better tools and armour, find food, build a shelter and stay safe at "
    "night. Never spend money, sell or trade. Talk only when someone talks to you."
)
