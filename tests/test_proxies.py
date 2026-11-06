"""A proxy for every account, not only Discord's (2026-11-05): set when it is added, kept with its login, and used by what
connects that account. Nothing here reaches a proxy or a platform, bar proxies made on this computer by the Node part."""
import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["LLMSELFBOT_DATA_DIR"] = _tmp.name
(Path(_tmp.name) / "config").mkdir(parents=True, exist_ok=True)
(Path(_tmp.name) / "config" / "config.yaml").write_text((ROOT / "resources" / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")

from app.utils import proxies  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


print("== what a proxy is ==")
p = proxies.parse("http://me:pa%40ss@1.2.3.4:8080")
check("read as a browser writes one", p == {"scheme": "http", "host": "1.2.3.4", "port": 8080, "username": "me", "password": "pa@ss"}, str(p))
check("nothing said: http", proxies.parse("1.2.3.4:8080")["scheme"] == "http")
check("socks too", proxies.parse("socks5://h.example:1080")["scheme"] == "socks5")
for bad in ("not a proxy", "ftp://1.2.3.4:21", "http://1.2.3.4", "http://:8080", "http://h:notaport"):
    check(f"not one: {bad}", proxies.parse(bad) is None and proxies.problem(bad), str(proxies.parse(bad)))
check("nothing at all is fine: no proxy", proxies.parse("") is None and proxies.problem("") == "" and proxies.problem(None) == "")
why = proxies.problem("socks5://me:pw@1.2.3.4:1080", "tiktok")
check("Chrome cannot take a password on SOCKS, and it says so before it fails", "Chrome cannot" in why, why)
check("for each that runs in a Chrome", all(proxies.problem("socks5://me:pw@1.2.3.4:1080", x) for x in ("snapchat", "tiktok", "instagram", "x", "reddit")))
check("and only those", all(not proxies.problem("socks5://me:pw@1.2.3.4:1080", x) for x in ("discord", "telegram", "whatsapp", "minecraft")))
check("with no password, Chrome is fine", not proxies.problem("socks5://1.2.3.4:1080", "tiktok"))
t = proxies.for_telethon("socks5://me:pw@1.2.3.4:1080")
check("as Telethon takes one", t == {"proxy_type": "socks5", "addr": "1.2.3.4", "port": 1080, "rdns": True, "username": "me", "password": "pw"}, str(t))
check("with no login, none is sent", "username" not in proxies.for_telethon("http://1.2.3.4:8080"))
check("no proxy: none", proxies.for_telethon("") is None)

print("\n== the store ==")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.web import envfile  # noqa: E402
from app.web.routes import account_routes as ar  # noqa: E402

PROXY_FIELDS = {"discord": "DISCORD_PROXY", "snapchat": "SNAP_PROXY", "tiktok": "TIKTOK_PROXY", "instagram": "INSTAGRAM_PROXY",
                "x": "X_PROXY", "reddit": "REDDIT_PROXY", "whatsapp": "WHATSAPP_PROXY", "minecraft": "MINECRAFT_PROXY",
                "telegram": "TELEGRAM_PROXY"}
for platform, prefix in PROXY_FIELDS.items():
    check(f"{platform} keeps one", ar.PLATFORMS[platform]["fields"].get("proxy") == prefix, str(ar.PLATFORMS[platform]["fields"]))
check("not iMessage: it talks to your own Mac or phone, not to a service", "proxy" not in ar.PLATFORMS["imessage"]["fields"])
for prefix in PROXY_FIELDS.values():
    check(f"{prefix} is kept out of the plain list, as Discord's always was", envfile.SECRET_KEYS.match(f"{prefix}_3"))

app = FastAPI()
app.state.supervisor = None
app.include_router(ar.router)
client = TestClient(app)
H = {"x-llmselfbot": "1"}
r = client.post("/api/accounts/slots/snapchat", headers=H, json={"username": "someone", "password": "pw", "proxy": "http://1.2.3.4:8080"})
check("adding one takes it", r.status_code == 200 and envfile.read_env().get("SNAP_PROXY_1") == "http://1.2.3.4:8080", r.text[:200])
check("and shows it again, to be edited", next(s for s in r.json()["slots"] if s["platform"] == "snapchat")["proxy"] == "http://1.2.3.4:8080")
r = client.post("/api/accounts/slots/snapchat/1", headers=H, json={"proxy": "not a proxy"})
check("nonsense is refused, saying what one looks like", r.status_code == 400 and "http://user:pass@host:port" in r.text, r.text[:200])
check("and nothing changed", envfile.read_env().get("SNAP_PROXY_1") == "http://1.2.3.4:8080")
r = client.post("/api/accounts/slots/snapchat/1", headers=H, json={"proxy": ""})
check("emptied, it goes", r.status_code == 200 and not envfile.read_env().get("SNAP_PROXY_1"), r.text[:200])
r = client.post("/api/accounts/slots/snapchat", headers=H, json={"username": "two", "password": "pw", "proxy": "socks5://me:pw@1.2.3.4:1080"})
check("what Chrome cannot use is refused when it is typed", r.status_code == 400 and "Chrome cannot" in r.text, r.text[:200])
client.post("/api/accounts/slots/snapchat", headers=H, json={"username": "two", "password": "pw", "proxy": "http://5.6.7.8:8080"})
client.post("/api/accounts/slots/snapchat", headers=H, json={"username": "three", "password": "pw", "proxy": "http://9.9.9.9:8080"})
client.delete("/api/accounts/slots/snapchat/1", headers=H)
env = envfile.read_env()
check("an account removed: the rest keep their own, renumbered", env.get("SNAP_PROXY_1") == "http://5.6.7.8:8080" and env.get("SNAP_PROXY_2") == "http://9.9.9.9:8080", str({k: v for k, v in env.items() if "PROXY" in k}))

print("\n== signing in through it ==")
started = {}
from app.utils import instagram_signin, reddit_signin, tiktok_browser_login, x_signin  # noqa: E402

for mod, name in ((tiktok_browser_login, "tiktok"), (reddit_signin, "reddit"), (instagram_signin, "instagram"), (x_signin, "x")):
    mod.start = lambda timeout_ms=0, proxy="", _n=name: (started.__setitem__(_n, proxy), {"state": "opening"})[1]
for path, name in (("/api/accounts/tiktok/browser-login/start", "tiktok"), ("/api/accounts/reddit/browser-login/start", "reddit"),
                   ("/api/accounts/instagram/sign-in/start", "instagram"), ("/api/accounts/x/sign-in/start", "x")):
    client.post(path, headers=H, json={"proxy": "http://1.1.1.1:3128"})
    check(f"{name}'s window goes through it", started.get(name) == "http://1.1.1.1:3128", str(started))
r = client.post("/api/accounts/x/sign-in/start", headers=H, json={"proxy": "socks5://me:pw@1.1.1.1:1080"})
check("refused before a window opens, if it could not work", r.status_code == 400)
client.post("/api/accounts/tiktok/browser-login/start", headers=H, json={"proxy": "http://1.1.1.1:3128"})
values = envfile.read_env()
index, slots = ar._store_tiktok(values, "someone_new")
slots = ar._keep_signin_proxy("tiktok", index, slots)
check("and the account it finds keeps it", envfile.read_env().get(f"TIKTOK_PROXY_{index}") == "http://1.1.1.1:3128"
      and next(s for s in slots if s["platform"] == "tiktok")["proxy"] == "http://1.1.1.1:3128", str(slots)[:200])
check("once", "tiktok" not in ar._signin_proxy)
for script in ("tiktok_login", "x_login", "reddit_login", "instagram_login"):
    check(f"{script}.js opens its window through it", 'proxy: process.env.LOGIN_PROXY || ""' in read(f"app/platforms/snapchat/{script}.js"))
for mod in ("x_signin", "instagram_signin", "reddit_signin"):
    check(f"{mod} passes it on", 'extra_env={"LOGIN_PROXY": proxy} if proxy else None' in read(f"app/utils/{mod}.py"))
check("TikTok's too", '"LOGIN_PROXY": str(proxy or "")' in read("app/utils/tiktok_browser_login.py"))
check("WhatsApp links through it", '"WHATSAPP_PROXY": str(proxy or "")' in read("app/platforms/whatsapp/link.py")
      and "agentFor(process.env.WHATSAPP_PROXY)" in read("app/platforms/snapchat/whatsapp_link.js"))
check("Telegram signs in through it", "proxy=proxies.for_telethon(proxy)" in read("app/platforms/telegram/signin.py"))

print("\n== running through it ==")
bridge = read("app/platforms/snapchat_bridge.py")
check("each runner gets its own, over any set for the whole platform",
      """_own_proxy = os.getenv(f"{P['env']}_PROXY_{ACCOUNT_INDEX}", "").strip()""" in bridge
      and """node_env[f"{P['env']}_PROXY"] = _own_proxy""" in bridge)
check("TikTok, Instagram, X and Reddit read it", all('proxy: core.text("PROXY")' in read(f"app/platforms/snapchat/{r_}_runner.js") for r_ in ("tiktok", "instagram", "x", "reddit")))
snap = read("app/platforms/snapchat/snapbot.js")
check("Snapchat, in its own launch", "process.env.SNAP_PROXY" in snap and "--proxy-server=" in snap and "page.authenticate(proxyLogin)" in snap)
browser = read("app/platforms/snapchat/browser.js")
check("a proxy's password goes to every page, as each opens", 'browser.on("targetcreated", give)' in browser and "page.authenticate(browser.__proxyAuth)" in browser)
check("WhatsApp's connection and what it fetches", "agentFor(process.env.WHATSAPP_PROXY)" in read("app/platforms/snapchat/whatsappbot.js")
      and "{ agent, fetchAgent: agent }" in read("app/platforms/snapchat/whatsappbot.js"))
check("Telegram", 'proxy=os.getenv(f"TELEGRAM_PROXY_{ACCOUNT_INDEX}", "").strip()' in bridge and "proxy=proxies.for_telethon(self.proxy)" in read("app/platforms/telegram/client.py"))
hooks = read("app/platforms/minecraft/agent_hooks.mjs")
check("Minecraft's bot", "original.call(this, throughProxy(options))" in hooks)
check("and mindcraft's look at the server, which would show this computer's address first", "protocol.ping = wrapped" in hooks and "original.call(this, throughProxy(options), cb)" in hooks)
check("and the runner's own", "mc.ping(throughProxy({ host, port: Number(port) || 25565 })" in read("app/platforms/minecraft/minecraft_runner.mjs"))
check("and then ViaProxy is what goes through it", '"--backend-proxy-url", process.env.MC_PROXY' in read("app/platforms/minecraft/minecraft_runner.mjs"))
check("the file goes with the runner", '"proxy_connect.mjs"' in read("app/platforms/minecraft/worker.py"))
spec = read("packaging/specparts.py")
check("and into the exe, or every Minecraft account would fail to start", '"minecraft" / "proxy_connect.mjs"' in spec)
check("Telethon's way of reaching a proxy is in the build", '"python_socks"' in spec and "python-socks" in read("requirements.txt"))

print("\n== the panel ==")
page = read("webui/src/pages/Accounts.svelte")
check("the field is under every account's form, not only Discord's", page.count('aria-label="Proxy"') == 1
      and page.index('aria-label="Proxy"') > page.index('{:else if editPlatform === "imessage"}'))
check("every account but iMessage", 'const hasProxy = $derived(editPlatform !== "imessage");' in page and "{#if hasProxy}" in page)
check("saved with the rest", "if (hasProxy) body.proxy = fProxy.trim();" in page)
check("sign-ins go through what was typed", all(s in page for s in ("api.tiktokBrowserLoginStart({ proxy: fProxy.trim() })", "api.redditBrowserLoginStart({ proxy: fProxy.trim() })",
                                                                    "api.xSignInStart({ proxy: fProxy.trim() })", "api.instagramSignInStart({ proxy: fProxy.trim() })",
                                                                    "way: waWay, proxy: fProxy.trim()", "phone: tgPhone.trim(), proxy: fProxy.trim()")))
check("changing it says to restart the account", 'hasProxy && fProxy.trim() !== (editing?.proxy ?? "")' in page)

print("\n== the connection, through real sockets ==")
node = subprocess.run(["node", "tests/proxy_connect_logic.mjs"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
for line in node.stdout.splitlines():
    if "FAIL" in line:
        print(line)
check("proxy_connect_logic.mjs passes", node.returncode == 0 and " 0 failed" in node.stdout, (node.stdout + node.stderr)[-400:])
if node.returncode == 0:
    print("  " + node.stdout.strip().splitlines()[-1])

_ = asyncio, re
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
