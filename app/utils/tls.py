"""app/utils/tls.py - HTTPS that trusts the certificates Windows has and the ones the app ships (certifi), together.

Python checks a server's certificate against the roots it can see. In the exe those are only the Windows store's, and
Windows fills that store lazily: a root it has not needed yet arrives the first time Windows itself checks a chain that
ends in it. On a PC that had never needed GitHub's root, the update check failed with "CERTIFICATE_VERIFY_FAILED ...
unable to get issuer certificate", and the app could not update (2026-11-11). certifi's bundle carries the public roots;
the Windows store carries whatever an antivirus or a company proxy that checks HTTPS added. One context with both covers
each case: the updater uses it, and install() makes it what every other urllib download uses too.
"""

import ssl
import threading
import urllib.request

_lock = threading.Lock()
_context: ssl.SSLContext | None = None


def context() -> ssl.SSLContext:
    """The system's roots and certifi's in one context, made once and shared (a context is safe across threads)."""
    global _context
    with _lock:
        if _context is None:
            ctx = ssl.create_default_context()
            try:
                import certifi
                ctx.load_verify_locations(certifi.where())
            except Exception:
                pass   # no certifi (a stripped source run): the system's roots alone, as before
            _context = ctx
        return _context


def opener() -> urllib.request.OpenerDirector:
    """A urllib opener that checks certificates with context()."""
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context()))


def install() -> None:
    """Make context() what urllib.request.urlopen uses wherever a call names no context of its own."""
    urllib.request.install_opener(opener())


def explain(exc: BaseException, site: str = "GitHub") -> str | None:
    """A plain sentence for a certificate that could not be checked, or None when the failure was something else."""
    reason = getattr(exc, "reason", None)
    if isinstance(exc, ssl.SSLCertVerificationError) or isinstance(reason, ssl.SSLCertVerificationError) \
            or "CERTIFICATE_VERIFY_FAILED" in str(exc):
        return f"This PC couldn't check {site}'s certificate. An antivirus or VPN that checks web traffic can cause this."
    return None
