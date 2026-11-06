"""Minecraft, its looks and its window.

  * its picture is its skin, standing in 3D as NameMC draws it: the premium account's of that name, looked up through
    Mojang's API, or else the default the game itself gives the name (one of the nine, Steve and Alex among them),
    picked from the name as the game picks it
  * its mark is the grass block on the Settings page; everywhere else it is the flat one, as every platform's is
  * its game version is a dropdown: the server's own, each version it plays, or one typed in; and ViaProxy is named
    for what it is, the bot's ViaFabricPlus
  * what it sees can open in a window of its own as it joins a world (minecraft.show_window), the bot's way of not
    being headless; and its Watch pops out into one

The renderer runs for real on skins made here; Mojang is a stand-in, nothing goes out. The rest is read from source.
"""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="llmbot_mc_extras_"))
os.environ["LLMSELFBOT_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(ROOT))
(DATA / "config").mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "resources" / "config.yaml", DATA / "config" / "config.yaml")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


from PIL import Image  # noqa: E402

RED, BLUE, GREEN = (255, 0, 0, 255), (0, 0, 255, 255), (0, 200, 0, 255)


def skin(face=RED, back=BLUE, size=(64, 64)) -> bytes:
    """A skin with its head's front one colour and its back another, everything else grey."""
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    for box in ((0, 0, 32, 16), (16, 16, 40, 32), (40, 16, 56, 32), (0, 16, 16, 32)):
        im.paste((128, 128, 128, 255), box)
    if size == (64, 64):
        for box in ((16, 48, 48, 64),):
            im.paste((128, 128, 128, 255), box)
    im.paste(face, (8, 8, 16, 16))
    im.paste(back, (24, 8, 32, 16))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def has(img, color) -> bool:
    """Whether a colour is drawn, lit or not: the game lights a block's faces differently, the front at 90%."""
    want = [c > 0 for c in color[:3]]
    return any([c > 100 for c in px[:3]] == want and all(c == 0 or c > 100 or not w for c, w in zip(px[:3], want))
               for px in img.getdata() if px[3] > 200)


print("== which skin ==")
from app.platforms.minecraft import skins  # noqa: E402

check("the id an offline server gives a name, as Java makes it",
      str(skins.offline_uuid("Notch")) == "b50ad385-829d-3141-a216-7e7d7539ba7f")
check("and its hash, as Java's UUID.hashCode", skins.java_hash(skins.offline_uuid("Notch")) == -524802362)
check("the default the game gives it: one of the nine, slim or wide, by that hash",
      skins.default_for(skins.offline_uuid("Notch")) == ("makena", True)
      and skins.default_for(skins.offline_uuid("aliciamwwoff")) == ("ari", False))
check("the nine, Steve and Alex among them, in the game's order",
      skins.DEFAULTS == ["alex", "ari", "efe", "kai", "makena", "noor", "steve", "sunny", "zuri"])

# The nine read from the bot's install: a stand-in of it, newest version first.
assets = DATA / "mindcraft" / "node_modules" / "minecraft-assets" / "minecraft-assets" / "data"
for ver in ("1.20.2", "1.21.8"):
    for model in ("slim", "wide"):
        d = assets / ver / "entity" / "player" / model
        d.mkdir(parents=True, exist_ok=True)
        for n in skins.DEFAULTS:
            (d / f"{n}.png").write_bytes(skin(face=GREEN if ver == "1.21.8" else RED))
got = skins.default_png("ari", False)
check("read from the newest version the install has", got and has(Image.open(io.BytesIO(got)), GREEN))

calls = []


def stand_in(url, timeout):
    calls.append(url)
    if "api.mojang.com" in url:
        return json.dumps({"id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch"}).encode() if "Notch" in url else b""
    if "sessionserver" in url:
        tex = {"textures": {"SKIN": {"url": "http://textures.minecraft.net/texture/abc", "metadata": {"model": "slim"}}}}
        return json.dumps({"properties": [{"name": "textures",
                                           "value": base64.b64encode(json.dumps(tex).encode()).decode()}]}).encode()
    if "textures.minecraft.net" in url:
        return skin(face=BLUE, back=RED)
    return b""


skins._get = stand_in
got = skins.lookup("Notch")
check("a premium name: its own skin, through Mojang, slim as Mojang says",
      got["source"] == "mojang" and got["slim"] is True and has(Image.open(io.BytesIO(got["png"])), BLUE), got["source"])
check("its skin fetched over https", any(u.startswith("https://textures.minecraft.net/") for u in calls), calls)
got = skins.lookup("aliciamwwoff")
check("a name with no premium account: the game's default for it", got["source"] == "default" and got["skin"] == "ari"
      and not got["slim"] and got["png"])


def broken(url, timeout):
    raise OSError("no network")


skins._get = broken
check("Mojang unreachable is the same as no premium account", skins.lookup("Notch")["source"] == "default")
check("a name that cannot be one is never sent to Mojang", (calls.clear() or True) and skins.lookup("not a name!")["source"] == "default"
      and not calls)

print("\n== drawing it ==")
body = skins.render(skin(), slim=False)
check("standing: taller than it is wide, on a clear ground", body.mode == "RGBA" and body.height > body.width * 1.6
      and body.getpixel((0, 0))[3] == 0, body.size)
check("its face drawn, from the front of its head", has(body, RED))
check("and the back of its head not: only what faces the eye is drawn", not has(body, BLUE))
lit = {px[:3] for px in body.getdata() if px[3] > 200}
check("its sides darker than its front, as the game lights a block", (128, 128, 128) in lit
      and any(c[0] == c[1] == c[2] and c[0] < 128 for c in lit))
slim = skins.render(skin(), slim=True)
check("a slim model's arms are narrower", slim.width < body.width, (slim.width, body.width))
legacy = skins.render(skin(size=(64, 32)), slim=False)
check("an old 64x32 skin: its left arm and leg made from the right ones", legacy.height > legacy.width * 1.6
      and abs(legacy.width - body.width) <= 2, (legacy.size, body.size))
port = skins.portrait(body)
check("its picture: head and shoulders, square, for a round frame", port.size == (256, 256) and has(port, RED))

print("\n== kept for its card ==")
skins._get = stand_in
r = skins.save_picture(1, "aliciamwwoff")
info = json.loads((DATA / "config" / "identity_minecraft_1.json").read_text(encoding="utf-8"))
check("saved beside its identity, named for the card", r["ok"] and (DATA / "config" / "identity_minecraft_1.png").is_file()
      and info.get("picture") == "identity_minecraft_1.png" and info.get("username") == "aliciamwwoff", info)
check("with what it was made from", info.get("skin") == "ari" and info.get("skin_source") == "default", info)
from app.web.routes import status_routes  # noqa: E402

ident = status_routes._web_identity("minecraft", 1, "#5b8731")
check("and the card shows it", ident.get("avatar", "").startswith("/api/accounts/minecraft_1/picture?v="), ident)
runner = read("app/platforms/minecraft/minecraft_runner.mjs")
check("the runner, writing who it is in the game, keeps the picture", "writeJson(file, { ...was, username: shown" in runner)
bridge = read("app/platforms/snapchat_bridge.py")
check("made as the account starts, off the loop since it asks Mojang",
      'asyncio.create_task(_mc_picture(_MC["picture_for"]))' in bridge
      and "r = await asyncio.to_thread(skins.save_picture, ACCOUNT_INDEX, name)" in bridge)

print("\n== its mark ==")
gb = read("webui/src/lib/components/GrassBlock.svelte")
check("the grass block in pixels: a grass top, dirt sides with grass over their edge, the sides shaded",
      gb.count('<g transform="matrix(') == 3 and "#7bc04a" in gb and "#6aae3d" in gb
      and "#744c2a" in gb and gb.count("<rect") > 60)
check("on the Settings page, where there is room for it",
      "<GrassBlock size={36} />" in read("webui/src/lib/components/MinecraftSetup.svelte"))
# Everywhere else it is one mark in the text's own colour, like every other platform's: a row of marks is read
# by shape, and one in full colour among them shouts.
icon = read("webui/src/lib/components/Icon.svelte")
check("and nowhere else: the icon set keeps its own flat mark", "GrassBlock" not in icon
      and "minecraft: MINECRAFT_CUBE," in icon
      and "GrassBlock" not in read("webui/src/pages/Accounts.svelte"))

print("\n== its version ==")
st = read("webui/src/pages/Settings.svelte")
check("a dropdown: the server's own first, then each version it plays, newest first, then any other",
      '{ value: "auto", label: "Match the server"' in st and '{ value: "26.1", label: "26.1"' in st
      and '{ value: "1.8.8", label: "1.8.8", hint: "And 1.8.9 servers" }' in st
      and '{ value: "custom", label: "Custom", hint: "Type the version", icon: "edit" }' in st)
check("one typed earlier, not on the list, shows as Custom with it in the box",
      '<Select value={mcKnown(v) ? v : "custom"} options={MC_VERSIONS}' in st and "{#if !mcKnown(v)}" in st)
check("ViaProxy named for what it does: any version's servers, as ViaFabricPlus",
      "as ViaFabricPlus does" in read("app/web/descriptions.py")
      and '"label": "Other versions (ViaProxy)"' in read("app/web/schema.py"))

print("\n== what it sees, as it moves ==")
hooks = read("app/platforms/minecraft/agent_hooks.mjs")
check("the picture is sent steadily, not only when it happens to move: that is what made it a slideshow",
      'bot.on("physicsTick", draw);' in hooks and 'bot.on("move", moved)' not in hooks)
check("and the world is re-centred far less often, since that loads and builds chunks",
      "now - lastChunks > 250" in hooks)
check("the view from above follows it, instead of staying where it spawned and ending up in the ground",
      "const BACK = 6, UP = 5;" in hooks and "Math.sin(yaw) * BACK" in hooks and "pitch: LOOK_DOWN" in hooks)
check("with the bot itself still drawn, as its own packet",
      'socket.emit("position", { pos, yaw, addMesh: true });' in hooks)
check("and the page's own camera settled first, so it never fights ours",
      "The page places its own camera on the first position it is sent" in hooks)
check("said as what it is",
      "Over its shoulder, following it about." in read("webui/src/lib/accounts/WatchView.svelte"))

print("\n== its window ==")
from app.web import schema  # noqa: E402

key = next(f for f in schema.CONFIG_SCHEMA if f["key"] == "minecraft.show_window")
check("a setting, off: it opens a window with what it sees as it joins a world", key["default"] is False
      and "requires_restart" not in key and "  show_window: false" in read("resources/config.yaml")
      and '"minecraft.show_window",' in read("webui/src/lib/settingsmap.ts"))
desk = read("app/desktop.py")
check("the app's own window onto its live view, one per account, brought back when open",
      'page = f"{_APP[\'url\']}?watch={account}"' in desk and "win = _VIEWS.get(account)" in desk
      and "win.show()" in desk)
check("opened when it comes into a world, once each time in",
      "if now_in and not inside.get(account) and on:" in desk
      and 'threading.Thread(target=_watch_views, daemon=True, name="minecraft-views").start()' in desk)
check("and from its Watch, popped out (a tab in a browser)", "def open_view(self, account=\"\", title=\"\"):" in desk
      and 'await window.pywebview?.api?.open_view?.(account, name)' in read("webui/src/lib/accounts/WatchView.svelte"))


# ── A screen on the view ────────────────────────────────────────────────────
# prismarine-viewer draws the world and nothing else: no chat, no hotbar, no health, and in its own eyes it drew the
# bot's own body right where the camera was. All of that is the panel's now, over the picture.
print("\n== what a player would have on screen ==")
_hooks = read("app/platforms/minecraft/agent_hooks.mjs")
check("in its own eyes it no longer draws its own body, which the camera sat inside",
      'if (view.above) socket.emit("position", { pos: bot.entity.position, yaw: bot.entity.yaw, addMesh: true });' in _hooks
      and "window.__lsbSelf.visible = !!window.__lsbAbove;" in _hooks)
check("the bot says what is on its screen, on the viewer's own server",
      "export function hudOf(bot, ask = {})" in _hooks and "app.get(`${prefix}/hud`" in _hooks)
check("  its hotbar, and which slot is in its hand",
      "for (let i = 0; i < 9; i++) hotbar.push(" in _hooks and "held: Number(" in _hooks)
check("  how worn a tool is, where a tool wears out at all", "left: max > 0 ?" in _hooks)
check("  what it has heard, on every server and not only one that asks it to sign in",
      'bot.on("messagestr", (text, position) => (position === "game_info" ? heardOverHotbar(text) : remember(text)));'
      in _hooks and "const heard = []" in _hooks)
check("  who is near it, nearest first", "near.sort((a, b) => a.away - b.away)" in _hooks)
_watch = read("webui/src/lib/accounts/WatchView.svelte")
check("the panel draws it over the picture, and lets the pointer through to the world",
      'class="hud"' in _watch and "pointer-events: none;" in _watch)
check("  hearts, food and air, counted in halves as the game counts them",
      "const hearts = (n: number) => Math.max(0, Math.min(10, n / 2));" in _watch)
check("  the nine slots, the held one lit", 'class="hud-bar"' in _watch and "is-held={i === hud.held}" in _watch)
check("  its chat where a player's is", 'class="hud-chat"' in _watch)
check("  where it is and what time it is there", 'class="hud-where"' in _watch and "const clock = $derived.by" in _watch)
check("  and what it is carrying, when you ask for it", 'class="hud-bag"' in _watch and "showBag" in _watch)

print("\n== the names over players' heads ==")
check("the viewer's own are black, squashed and off to one side, so they are redrawn",
      "NAMETAG_AS_SHIPPED" in _hooks and "NAMETAG_AS_DRAWN" in _hooks)
check("  white, centred, on a plate, in proportion",
      'r.fillStyle="#ffffff"' in _hooks and 'r.textAlign="center"' in _hooks
      and "u.scale.set(H*cw/ch,H,1)" in _hooks)
check("  served ahead of its page rather than written into mindcraft's node_modules",
      "app.get(`${prefix}/index.js`" in _hooks and "pageWithBetterNames" in _hooks)
check("  and a page this no longer fits is said, not quietly left as it was",
      "its page is not the one this knows" in _hooks)

# ── Played by hand ──────────────────────────────────────────────────────────
# Its owner takes the body over from the view: keyboard and mouse as the game is played, a stick and buttons on a
# phone, its chat typed into, F3. Its AI is paused meanwhile and carries on after.
print("\n== playing it by hand, from its view ==")
import subprocess  # noqa: E402

_node = shutil.which("node")
if _node:
    _p = subprocess.run([_node, str(ROOT / "tests" / "minecraft_drive.mjs")], cwd=ROOT, capture_output=True,
                        text=True, timeout=120, encoding="utf-8", errors="replace")
    print("\n".join(line for line in _p.stdout.strip().splitlines() if not line.startswith("\x1eLSB")))
    check("minecraft_drive.mjs passes", _p.returncode == 0, (_p.stdout + _p.stderr)[-400:])
check("the bot's own view server takes the hands, only from the panel (its header)",
      all(f"app.post(`${{prefix}}/{r}`, fromPanel, body" in _hooks for r in ("say", "drive", "input", "act"))
      and 'req.get("x-llmselfbot")' in _hooks)
check("  mindcraft's agent found where its own modules keep it, and only when it is this bot's",
      'new URL("../agent/mindserver_proxy.js", main)' in _hooks and "agent.bot === bot ? agent : null" in _hooks)
check("  hands that go quiet come off, and the body goes back to its AI before long",
      "KEYS_IDLE_MS = 1500" in _hooks and "GIVE_BACK_MS = 45000" in _hooks
      and 'letGo(bot, "no word from the panel")' in _hooks)
check("  a goal from its card takes the body back from the hands first",
      "await _let_go(web_id)" in read("app/web/routes/minecraft_routes.py"))
check("  the log says when it is played and when it is let go",
      'msg.event === "driving"' in read("app/platforms/minecraft/minecraft_runner.mjs"))
_api = read("webui/src/lib/api.ts")
check("the panel's calls for it", all(f"{n}: (webId" in _api for n in
      ("minecraftSay", "minecraftDrive", "minecraftInput", "minecraftAct")))
check("  Take control, and Let go", "Take control" in _watch and "Let go" in _watch
      and "api.minecraftDrive(account, true)" in _watch and "api.minecraftDrive(account, false)" in _watch)
check("  the mouse locked in for looking, as the game does", "requestPointerLock" in _watch
      and "turn(e.movementX, e.movementY, SENS)" in _watch)
check("  the game's keys, ahead of the dialog around it", 'KeyW: "forward"' in _watch
      and 'window.addEventListener("keydown", onKey, true)' in _watch)
check("  a tap shorter than one send still gets there", "latch.keys" in _watch and "latch.attack" in _watch)
check("  the camera turns with the mouse at once, in its eyes", "w.__lsbLook = { yaw: look.yaw" in _watch
      and "window.__lsbLook" in _hooks)
check("  its chat typed into, commands included", "api.minecraftSay(account, text)" in _watch
      and "or a /command" in _watch)
check("  a stick and buttons on a phone", 'class="pad-stick"' in _watch and 'matchMedia("(pointer: coarse)")' in _watch)
check("  F3, F1, F2, F5 and Tab, as in the game", all(c in _watch for c in
      ('"F3") toggleDebug()', '"F1") hideHud', '"F2") screenshot()', '"F5") switchView()', 'e.code === "Tab"')))
check("  pictures saved through the app's own Save dialog", "saveUrlAs(url," in _watch
      and "window.__lsbShot" in _hooks)
check("the rest of a player's screen: experience, armour, effects, boss bars, the board, titles, the player list",
      all(k in _hooks for k in ("xp: {", "armourPoints:", "effects: effectsOf(bot)", "bossBars: bossBarsOf(bot)",
                                 "sidebar: sidebarOf(bot)", "title: screen.titleAt", "players: playersOf(bot, pos)"))
      and all(c in _watch for c in ('class="hud-xp"', 'class="hud-effects"', 'class="hud-boss"', 'class="hud-side"',
                                     'class="hud-title"', 'class="hud-tab"', 'class="hud-debug"')))
check("  Minecraft's own pictures for items and hearts, from the viewer's textures",
      "items_textures.json" in _hooks and "gui/sprites/hud/heart/" in _watch and "image-rendering: pixelated" in _watch)
check("its window of its own is the panel's Watch, HUD and controls and all",
      'params.has("watch") ? WatchWindow' in read("webui/src/main.ts")
      and "<WatchView {account} {name} full />" in read("webui/src/WatchWindow.svelte"))

# ── Lag, breaking blocks, creatures, server menus ───────────────────────────
print("\n== played without lag, breaking blocks, creatures, server menus ==")
_hooks = read("app/platforms/minecraft/agent_hooks.mjs")
_routes = read("app/web/routes/minecraft_routes.py")
check("keys and clicks go over the view's own connection, not a web request each",
      'socket.on("lsb:input"' in _hooks and 'sock.emit("lsb:input", body)' in read("webui/src/lib/accounts/WatchView.svelte")
      and "SOCKET_AS_PATCHED" in _hooks)
check("  that connection only through the panel, and never from another site's page",
      'done(null, req.headers["x-lsb-panel"] === "1")' in _hooks and 'headers["x-lsb-panel"] = "1"' in _routes
      and '"X-Lsb-Panel": "1"' in _routes and "if not _same_site(ws.headers.get(\"origin\", \"\"), ws.headers.get(\"host\", \"\")):" in _routes)
check("  positions sent straight after each physics tick", 'bot.on("physicsTick", draw);' in _hooks)
check("  the world sent a chunk at a time, everything else let through between",
      "export function loadGently(world)" in _hooks and "loadGently(world);" in _hooks)
check("  its eyes and above switched in place, the world kept", 'socket.on("lsb:view"' in _hooks
      and 'sock.emit("lsb:view", { above: m === "above" })' in read("webui/src/lib/accounts/WatchView.svelte"))
check("blocks broken the game's way: the face looked at, the next only once the server says",
      "function startBreaking(bot, block)" in _hooks and "const DESTROY_DELAY_MS = 250;" in _hooks
      and "bot.dig(" not in _hooks)
check("it plays like a 1.21 client: one rising number for what it predicts, and its keys (not the end of each tick, which got it kicked)",
      "export function playLikeTheGame(bot, given = null)" in _hooks and "playLikeTheGame(bot);" in _hooks
      and 'write.call(client, "tick_end"' not in _hooks and 'write.call(client, "player_input", { inputs })' in _hooks)
check("taking control never uses mindcraft's own stop, which ends its process after ten seconds",
      "interruptMind(agent);" in _hooks and "await agent.actions.stop()" not in _hooks and "await sp.stop(false);" in _hooks)
check("commands sent plain when there is nothing to sign, as the game does",
      'bot._client.write("chat_command", { command: command.slice(0, 255) });' in _hooks)
check("creatures it has no model for: a stand-in, their name, or a dropped item's picture, never a magenta box",
      "const STAND_INS = {" in _hooks and 'username: `\\u0004textures/${pictures.version}/${icon}`' in _hooks)
check("its AI given commands for a server's menus, and told of them in its prompt",
      all(n in _hooks for n in ('"!useItem"', '"!menu"', '"!clickMenuSlot"', '"!closeMenu"', '"!runCommand"'))
      and "!clickMenuSlot" in read("app/platforms/minecraft/profile.py"))
check("  never a command that pays, sells, trades or gives", "const NEVER_RUN = /^(pay|give|trade|sell" in _hooks)
check("  a menu that opens shows in the log", 'msg.event === "menu"' in read("app/platforms/minecraft/minecraft_runner.mjs"))
check("  its F3 screen says what it sent and got", "net: netOf()," in _hooks and "Sent: {d.net.sent.join" in read("webui/src/lib/accounts/WatchView.svelte"))

# ── A premium account's skin, from the panel ────────────────────────────────
# Minecraft keeps it, so it is changed with the account's own Microsoft login. Minecraft is a stand-in here.
print("\n== its skin, changed from the panel ==")
from fastapi import HTTPException  # noqa: E402
from PIL import Image as _Image  # noqa: E402
from app.platforms.minecraft import skin_change  # noqa: E402
from app.web.routes import account_routes  # noqa: E402


def _png(w, h):
    buf = io.BytesIO()
    _Image.new("RGBA", (w, h), (90, 140, 200, 255)).save(buf, "PNG")
    return buf.getvalue()


check("a 64 by 64 PNG can be a skin, and the old 64 by 32", skin_change.check_png(_png(64, 64)) == ""
      and skin_change.check_png(_png(64, 32)) == "")
check("  any other size is refused, saying which it is", "128 by 128" in skin_change.check_png(_png(128, 128)))
check("  and anything that is not a PNG", skin_change.check_png(b"GIF89a....") == "A skin is a PNG picture."
      and skin_change.check_png(b"") == "No picture came with it.")
_ran = []
_real_run = skin_change._run
skin_change._run = lambda name, png, slim, timeout, keep=False: (
    _ran.append((name, png is None, slim)) or
    {"ok": True, "variant": "slim" if slim else "classic", "id": "0123456789abcdef0123456789abcdef",
     "kept": _png(64, 64) if keep else b""})
r = skin_change.change(7, "Alicia", _png(64, 64), slim=True)
_info = json.loads((DATA / "config" / "identity_minecraft_7.json").read_text(encoding="utf-8"))
check("put on: Minecraft asked with its name and the arms, and the card drawn from the new skin at once",
      r.get("ok") and _ran[-1] == ("Alicia", False, True) and _info.get("slim") is True
      and _info.get("skin_source") == "mojang" and (DATA / "config" / "identity_minecraft_7_body.png").is_file())
r = skin_change.change(7, "Alicia", None)
_info = json.loads((DATA / "config" / "identity_minecraft_7.json").read_text(encoding="utf-8"))
check("taken off: the game's own default for its id drawn instead", r.get("ok") and _ran[-1][1] is True
      and _info.get("skin_source") == "default" and _info.get("skin"))
check("  what the edit window shows: its arms and its picture standing up",
      skin_change.current(7)["picture"].startswith("data:image/png;base64,"))
r = skin_change.change(7, "Alicia", _png(10, 10))
check("  a wrong picture never reaches Minecraft", not r.get("ok") and len(_ran) == 2)
r = skin_change.change(7, "Alicia", None, slim=False, keep=True)
_info = json.loads((DATA / "config" / "identity_minecraft_7.json").read_text(encoding="utf-8"))
check("other arms only: the skin it has goes back on, and the card is drawn from that very skin",
      r.get("ok") and _info.get("skin_source") == "mojang" and _info.get("slim") is False)
skin_change._run = _real_run
_skin_py = read("app/platforms/minecraft/skin_change.py")
_skin_route = read("app/web/routes/account_routes.py")
check("  that skin is the account's own as Minecraft has it, never one looked up by a name",
      'env.update(LSB_SKIN_KEEP="1", LSB_SKIN_OUT=str(out))' in _skin_py
      and 'skin_change.change, index, name, None, variant == "slim", keep=True' in _skin_route
      and "skins.lookup" not in _skin_route)
_bridge = read("app/platforms/snapchat_bridge.py")
check("its card's picture is the skin of the player it really is, not of whoever owns the name it was added under",
      'core.tellPython({ kind: "mc_event", event: "spawned", name: String(msg.name) });'
      in read("app/platforms/minecraft/minecraft_runner.mjs")
      and 'msg.get("event") == "spawned"' in _bridge and "_spawn_panel(_mc_picture(real))" in _bridge
      and '_MC["picture_for"] = _mc_played_as(slot)' in _bridge)

from app.web import envfile  # noqa: E402

envfile.ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
envfile.ENV_PATH.write_text("MINECRAFT_USERNAME_1=Offliner\nMINECRAFT_AUTH_1=offline\n"
                            "MINECRAFT_USERNAME_2=Alicia\nMINECRAFT_AUTH_2=microsoft\n", encoding="utf-8")
try:
    account_routes._minecraft_premium(1)
    refused = False
except HTTPException as e:
    refused = e.status_code == 400 and "Microsoft" in str(e.detail)
check("an account with no account has no skin of its own to change", refused)
check("  a Microsoft one does, under the name its login is kept by", account_routes._minecraft_premium(2) == "Alicia")
try:
    account_routes._minecraft_premium(9)
    missing_ok = False
except HTTPException as e:
    missing_ok = e.status_code == 404
check("  and there is no account 9", missing_ok)
_skin_js = read("app/platforms/minecraft/ms_skin.mjs")
check("the helper uses the login its bot plays with, as the sign-in leaves it",
      '{ authTitle: Titles.MinecraftNintendoSwitch, deviceType: "Nintendo", flow: "live" }' in _skin_js
      and '{ authTitle: Titles.MinecraftNintendoSwitch, deviceType: "Nintendo", flow: "live" }'
      in read("app/platforms/minecraft/ms_signin.mjs"))
check("  and never starts a sign-in of its own: asked for a code, it says so and stops",
      "say({ error: SIGN_IN_AGAIN });\n      process.exit(2);" in _skin_js)
check("  Minecraft's own skin calls: put on (variant and file), taken off",
      'fetch(`${API}/skins`, { method: "POST", headers, body: form })' in _skin_js
      and 'fetch(`${API}/skins/active`, { method: "DELETE", headers })' in _skin_js
      and 'form.append("variant"' in _skin_js and 'form.append("file"' in _skin_js)
check("  written beside mindcraft, and packed into the app", '"ms_skin.mjs")' in read("app/platforms/minecraft/worker.py")
      and '"minecraft" / "ms_skin.mjs"' in read("packaging/specparts.py"))
_acc = read("webui/src/pages/Accounts.svelte")
check("the edit window shows it for a Microsoft account already signed in, and only then",
      "<McSkin index={editIndex} />" in _acc and 's.auth === "microsoft")}' in _acc)
_mk = read("webui/src/lib/accounts/McSkin.svelte")
check("  a picture is checked as Minecraft will, and shown standing before it is sent",
      "i.width !== 64 || (i.height !== 64 && i.height !== 32)" in _mk and "part(8, 8, 8, 8, 4, 0);" in _mk)
check("  slim arms told from the picture itself", "getImageData(54, 20, 2, 12)" in _mk)

shutil.rmtree(DATA, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
