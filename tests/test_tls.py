"""HTTPS that trusts Windows' roots and certifi's together (app/utils/tls.py, 2026-11-11).

The updater failed on some PCs with "CERTIFICATE_VERIFY_FAILED ... unable to get issuer certificate": the exe sees
only the Windows store's roots, and Windows adds a root the first time it needs it itself, so a PC that never had
GitHub's root could not update. certifi's bundle carries it. Checked here: the shared context holds certifi's roots on
top of the system's, certifi's alone are enough for GitHub (a real handshake, skipped offline), every urllib call in
the app uses the context, and a certificate failure is said in plain words rather than as Python's error.
"""
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


from app.utils import tls  # noqa: E402

print("== one context, both sets of roots ==")
ctx = tls.context()
plain = ssl.create_default_context()
try:
    import certifi
    have_certifi = True
except Exception:
    have_certifi = False
check("certifi is there to add (it ships in the exe: packaging/specparts.py)", have_certifi)
ours, system = ctx.cert_store_stats()["x509_ca"], plain.cert_store_stats()["x509_ca"]
check("more roots than the system's alone", ours > system, f"{ours} vs {system}")
check("made once and shared", tls.context() is ctx)
check("still checks names and certificates", ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED)


def handshake(context, host="api.github.com"):
    with socket.create_connection((host, 443), timeout=8) as sock:
        with context.wrap_socket(sock, server_hostname=host):
            return "ok"


print("\n== certifi's roots are enough for GitHub (what a PC missing Windows' copy of the root needs) ==")
try:
    socket.create_connection(("api.github.com", 443), timeout=5).close()
    online = True
except OSError:
    online = False
if not online:
    print("  SKIP  offline: no handshake to try")
else:
    empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)          # no roots at all: the failure the updater met
    try:
        handshake(empty)
        refused = False
    except ssl.SSLCertVerificationError:
        refused = True
    check("with no roots, GitHub's certificate is refused", refused)
    if have_certifi:
        only_certifi = ssl.create_default_context(cafile=certifi.where())
        try:
            said = handshake(only_certifi)
        except Exception as e:
            said = f"{type(e).__name__}: {e}"
        check("with certifi's roots alone, it is accepted", said == "ok", said)
    try:
        said = handshake(ctx)
    except Exception as e:
        said = f"{type(e).__name__}: {e}"
    check("and with the shared context", said == "ok", said)

print("\n== every urllib download uses it ==")
tls.install()
installed = getattr(urllib.request, "_opener", None)
https = [h for h in getattr(installed, "handlers", []) if isinstance(h, urllib.request.HTTPSHandler)]
check("urlopen's default opener checks with the shared context", bool(https) and https[0]._context is ctx)
cli = (ROOT / "app" / "cli.py").read_text(encoding="utf-8")
check("installed as each process starts", "tls.install()" in cli.split("def bootstrap", 1)[1].split("def load_env", 1)[0])
upd = (ROOT / "app" / "core" / "update.py").read_text(encoding="utf-8")
check("the updater asks with it itself too, for the release and its file", upd.count("tls.opener().open(req") == 2
      and "urllib.request.urlopen(" not in upd)
check("as do the mail codes and the voice download", "tls.context()" in (ROOT / "app/utils/mailcodes.py").read_text(encoding="utf-8")
      and "tls.context()" in (ROOT / "app/voice/onboard.py").read_text(encoding="utf-8"))

print("\n== said plainly ==")
bad = urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                                                           "unable to get issuer certificate (_ssl.c:1000)"))
said = tls.explain(bad)
check("a certificate that could not be checked", said == "This PC couldn't check GitHub's certificate. An antivirus or "
      "VPN that checks web traffic can cause this.", str(said))
check("the same from the message alone", tls.explain(RuntimeError("<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] x>")) == said)
check("anything else is left to say itself", tls.explain(urllib.error.URLError(TimeoutError("timed out"))) is None
      and tls.explain(ConnectionResetError()) is None)
routes = (ROOT / "app" / "web" / "routes" / "system_routes.py").read_text(encoding="utf-8")
check("the update check says it that way", '"reason": tls.explain(e) or str(e)' in routes)
check("and the update itself", "tls.explain(exc) or f\"Could not reach GitHub: {exc}\"" in upd
      and "The update failed: {tls.explain(exc) or exc}" in upd)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
