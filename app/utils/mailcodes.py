"""Codes a social emails to make sure it is the account's owner signing in, read from the owner's own mailbox and typed
where the social asks (Instagram, X and Reddit: app/platforms/snapchat_bridge.py hands them over).

A mailbox is an address and its password, kept with the other secrets in config/.env (MAIL_<n>, MAIL_PASSWORD_<n>,
and MAIL_SERVER_<n> once found). The app works out how to reach it by itself, the way mail apps do: the big providers
it knows, then Thunderbird's list of providers, then the domain's own settings, then whoever handles its mail (its MX).
It says when a provider wants an app password instead of the usual one.

Only what the social sent is read: messages from its own addresses, newer than its ask, in the inbox or the spam
folder. The mailbox is opened read-only, so nothing is marked read, moved or deleted, and the code is all that leaves.
"""
from __future__ import annotations

import email
import html
import imaplib
import json
import re
import socket
import ssl
import threading
import time
import urllib.parse
from email.header import decode_header, make_header

#: Who each social sends its codes from.
SENDERS = {
    "instagram": ("instagram.com", "facebookmail.com"),
    "x": ("x.com", "twitter.com"),
    "reddit": ("reddit.com", "redditmail.com"),
    "tiktok": ("tiktok.com", "tiktokv.com"),
    "snapchat": ("snapchat.com",),
    "discord": ("discord.com", "discordapp.com"),
}

#: How long a social's code is looked for, and how often.
WAIT_S = 240
EVERY_S = 6
#: A message this much older than the ask still counts: clocks differ, and a code can come a moment before the screen.
SKEW_S = 120
_TIMEOUT = 20

def _name(platform: str) -> str:
    from app.platforms import registry
    return registry.name_of(platform)


# ── Providers ──────────────────────────────────────────────────────────────────────────────────

#: The ones nearly everybody uses, with what they want instead of the usual password when they want something else.
_KNOWN = (
    (("gmail.com", "googlemail.com"), "imap.gmail.com:993",
     "Gmail takes an app password here, not your usual one: make one at https://myaccount.google.com/apppasswords "
     "(2-Step Verification has to be on)."),
    (("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.fr", "hotmail.fr", "live.fr", "hotmail.co.uk",
      "live.co.uk", "outlook.de", "hotmail.de", "hotmail.it", "outlook.es", "hotmail.es"), "outlook.office365.com:993",
     "Microsoft no longer lets mail apps sign in to Outlook and Hotmail with a password, so it may refuse this one."),
    (("yahoo.com", "yahoo.fr", "yahoo.co.uk", "yahoo.de", "yahoo.es", "yahoo.it", "ymail.com", "rocketmail.com"),
     "imap.mail.yahoo.com:993", "Yahoo takes an app password: make one in Account security, under App passwords."),
    (("icloud.com", "me.com", "mac.com"), "imap.mail.me.com:993",
     "iCloud takes an app-specific password: make one at https://account.apple.com, under Sign-In and Security."),
    (("aol.com",), "imap.aol.com:993", "AOL takes an app password: make one in Account security."),
    (("gmx.com", "gmx.net", "gmx.de", "gmx.fr", "gmx.at", "gmx.ch"), "imap.gmx.net:993",
     "GMX only lets mail apps in once IMAP is turned on in its settings."),
    (("web.de",), "imap.web.de:993", "WEB.DE only lets mail apps in once IMAP is turned on in its settings."),
    (("mail.ru", "inbox.ru", "list.ru", "bk.ru"), "imap.mail.ru:993",
     "Mail.ru takes a password for outside apps, made in its security settings."),
    (("yandex.com", "yandex.ru", "ya.ru"), "imap.yandex.com:993", "Yandex takes an app password."),
    (("zoho.com", "zohomail.com"), "imap.zoho.com:993", "Zoho only lets mail apps in once IMAP is turned on."),
    (("proton.me", "protonmail.com", "pm.me"), "",
     "Proton Mail can only be read by a mail app through Proton Bridge, so the app can't read it."),
    (("tutanota.com", "tuta.io", "tutamail.com", "tuta.com"), "", "Tuta has no way in for mail apps."),
)
#: Where a domain's mail is handled (its MX), for a domain of its own on one of the big providers.
_BY_MX = (("google.com", "googlemail.com"), ("outlook.com", "outlook.com"), ("zoho", "zoho.com"),
          ("yandex", "yandex.com"), ("mail.ru", "mail.ru"), ("icloud.com", "icloud.com"), ("yahoodns", "yahoo.com"))


def _known(domain: str) -> dict | None:
    for domains, server, note in _KNOWN:
        if domain in domains:
            return {"server": server, "note": note, "found": "known"}
    return None


def _ipv4_http(url: str, timeout: float = 8.0, headers: dict | None = None):
    """A GET over IPv4: here, IPv6 stalls where IPv4 answers at once."""
    import httpx
    transport = httpx.HTTPTransport(local_address="0.0.0.0", retries=1)
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=True, headers=headers or {}) as client:
        return client.get(url)


def _autoconfig(url: str, address: str) -> str:
    """The IMAP server a Thunderbird-style config names, as host:port, or ""."""
    try:
        r = _ipv4_http(url)
    except Exception:
        return ""
    if r.status_code != 200 or "incomingServer" not in r.text:
        return ""
    domain = address.rsplit("@", 1)[-1]
    best = ""
    for block in re.findall(r'<incomingServer type="imap">(.*?)</incomingServer>', r.text, re.S):
        host = re.search(r"<hostname>\s*([^<\s]+)\s*</hostname>", block)
        port = re.search(r"<port>\s*(\d+)\s*</port>", block)
        sock = re.search(r"<socketType>\s*(\w+)\s*</socketType>", block)
        if not host:
            continue
        name = host.group(1).replace("%EMAILDOMAIN%", domain)
        found = f"{name}:{port.group(1) if port else 993}"
        if sock and sock.group(1).upper() == "SSL":
            return found
        best = best or found
    return best


def _mx(domain: str) -> list:
    """Who handles the domain's mail, best first, asked of DNS over HTTPS (no DNS library ships with the app)."""
    for url in (f"https://cloudflare-dns.com/dns-query?name={domain}&type=MX",
                f"https://dns.google/resolve?name={domain}&type=MX"):
        try:
            r = _ipv4_http(url, headers={"accept": "application/dns-json"})
            answers = r.json().get("Answer") or []
        except Exception:
            continue
        found = []
        for a in answers:
            parts = str(a.get("data") or "").split()
            if len(parts) == 2 and parts[0].isdigit():
                found.append((int(parts[0]), parts[1].rstrip(".").lower()))
        if found:
            return [host for _, host in sorted(found)]
    return []


def discover(address: str) -> dict:
    """How to reach this mailbox: {"server": "host:port" or "", "note": what it wants, "found": how it was found}."""
    domain = address.rsplit("@", 1)[-1].strip().lower()
    known = _known(domain)
    if known:
        return known
    q = urllib.parse.quote(address)
    for url, how in ((f"https://autoconfig.thunderbird.net/v1.1/{domain}", "Thunderbird's list"),
                     (f"https://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress={q}", "its own settings"),
                     (f"https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml?emailaddress={q}", "its own settings")):
        server = _autoconfig(url, address)
        if server:
            return {"server": server, "note": "", "found": how}
    for host in _mx(domain):
        for part, provider in _BY_MX:
            if part in host:
                known = _known(provider)
                if known:
                    return {**known, "found": "where its mail goes"}
        base = ".".join(host.split(".")[-2:])
        server = _autoconfig(f"https://autoconfig.thunderbird.net/v1.1/{base}", address)
        if server:
            return {"server": server, "note": "", "found": "where its mail goes"}
    return {"server": f"imap.{domain}:993", "note": "", "found": "a guess"}


# ── Reading a mailbox ──────────────────────────────────────────────────────────────────────────

def _context() -> ssl.SSLContext:
    """Windows' roots and certifi's together (app/utils/tls.py): certifi's alone missed a mail server behind an
    antivirus or company proxy that checks connections with a root of its own."""
    from app.utils import tls
    return tls.context()


class _IMAP(imaplib.IMAP4_SSL):
    """IMAP over TLS that tries IPv4 first."""

    def _create_socket(self, timeout):
        last = None
        for family in (socket.AF_INET, socket.AF_UNSPEC):
            try:
                infos = socket.getaddrinfo(self.host, self.port, family, socket.SOCK_STREAM)
            except OSError as e:
                last = e
                continue
            for *_, addr in infos:
                try:
                    sock = socket.create_connection(addr[:2], timeout)
                    return self.ssl_context.wrap_socket(sock, server_hostname=self.host)
                except OSError as e:
                    last = e
        raise last or OSError(f"could not reach {self.host}")


def connect(server: str, address: str, password: str):
    """A logged-in IMAP connection. Raises MailError in words."""
    host, _, port = server.partition(":")
    try:
        box = _IMAP(host, int(port or 993), ssl_context=_context(), timeout=_TIMEOUT)
    except ssl.SSLError:
        raise MailError(f"{host} answered, but its certificate could not be checked.") from None
    except (OSError, imaplib.IMAP4.error):
        raise MailError(f"Could not reach {host}.") from None
    try:
        box.login(address, password)
    except imaplib.IMAP4.error as e:
        try:
            box.logout()
        except Exception:
            pass
        said = e.args[0].decode("utf-8", "replace") if e.args and isinstance(e.args[0], bytes) else str(e)
        raise MailError(f"The password was refused ({said.strip()[:120]}).") from None
    return box


class MailError(Exception):
    """What went wrong with a mailbox, in words."""


def _folders(box) -> list:
    """The inbox, then wherever the provider puts spam: a first code to a new account often lands there."""
    out = ["INBOX"]
    try:
        typ, rows = box.list()
    except Exception:
        return out
    for row in rows or []:
        line = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
        m = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if not m:
            continue
        name = m.group("name").strip()
        bare = name.strip('"')
        if "\\Junk" in m.group("flags") or re.search(r"spam|junk|bulk|ind.sirable|no deseado|indesiderat", bare, re.I):
            out.append(name if name.startswith('"') else f'"{bare}"')
    return out


def _decoded(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return str(value or "")


def _text_of(msg) -> str:
    """The message's words: its plain text, or its HTML with the markup taken out."""
    plain, rich = [], []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html") or part.get_filename():
            continue
        try:
            raw = part.get_payload(decode=True) or b""
            text = raw.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        (plain if kind == "text/plain" else rich).append(text)
    if plain:
        return "\n".join(plain)
    words = "\n".join(rich)
    words = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", words)
    words = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|td|h\d|li)>", "\n", words)
    return html.unescape(re.sub(r"<[^>]+>", " ", words))


def messages(box, platform: str, since: float, limit: int = 6) -> list:
    """The social's messages newer than `since`, newest first: {"subject", "text", "at"}. Read-only."""
    day = time.strftime("%d-%b-%Y", time.gmtime(since - 86400))
    out = []
    for folder in _folders(box):
        try:
            typ, _ = box.select(folder, readonly=True)
        except Exception:
            continue
        if typ != "OK":
            continue
        uids = set()
        for sender in SENDERS.get(platform, ()):
            try:
                typ, data = box.uid("SEARCH", None, "SINCE", day, "FROM", f'"{sender}"')
            except Exception:
                continue
            if typ == "OK" and data and data[0]:
                uids.update(u.decode() if isinstance(u, bytes) else str(u) for u in data[0].split())
        for uid in sorted(uids, key=int, reverse=True)[:limit]:
            try:
                typ, data = box.uid("FETCH", uid, "(INTERNALDATE RFC822.SIZE BODY.PEEK[])")
            except Exception:
                continue
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            meta, raw = data[0]
            stamp = imaplib.Internaldate2tuple(meta)
            at = time.mktime(stamp) if stamp else 0.0
            if at and at < since - SKEW_S:
                continue
            msg = email.message_from_bytes(raw[:2_000_000])
            sender = _decoded(msg.get("From", "")).lower()
            if not any(s in sender for s in SENDERS.get(platform, ())):
                continue
            out.append({"subject": _decoded(msg.get("Subject", "")), "text": _text_of(msg)[:20000], "at": at})
    out.sort(key=lambda m: -m["at"])
    return out


# ── Finding the code in a message ──────────────────────────────────────────────────────────────

_CODE_WORD = re.compile(r"code|c.digo|codice|kod|код|confirm|verif|security|s.curit|bestätig|best.tig|pin\b", re.I)
_DIGITS = re.compile(r"(?<![\w#/.:-])(\d{4,8})(?![\w/-])")
# X's login codes are letters and digits together: one of each at least, 6 to 10 of them.
_MIXED = re.compile(r"(?<![\w#/.:-])(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])([a-z0-9]{6,10})(?![\w/-])")


def _candidates(subject: str, text: str) -> list:
    """Each thing that could be the code, with how sure it looks."""
    text = re.sub(r"https?://\S+", " ", text)
    scored: dict = {}

    def weigh(where: str, bonus: int):
        for pattern, kind in ((_DIGITS, "digits"), (_MIXED, "mixed")):
            for m in pattern.finditer(where):
                code = m.group(1)
                if kind == "digits" and len(code) == 4 and 1990 <= int(code) <= 2040:
                    continue          # a year
                score = bonus + (1 if kind == "digits" else 0)
                near = where[max(0, m.start() - 60):m.end() + 40]
                if _CODE_WORD.search(near):
                    score += 4
                line = where[where.rfind("\n", 0, m.start()) + 1:where.find("\n", m.end()) if "\n" in where[m.end():] else len(where)]
                if line.strip() == code:
                    score += 3        # a code on a line of its own, the way these emails set it out
                scored[code] = max(scored.get(code, 0), score)

    weigh(subject, 5)
    weigh(text, 0)
    return sorted(scored.items(), key=lambda kv: -kv[1])


def extract(subject: str, text: str) -> str:
    """The code in a social's email, or "" when it is not clear which one it is."""
    found = _candidates(subject, text)
    if not found or found[0][1] < 5:
        return ""
    if len(found) > 1 and found[1][1] == found[0][1] and found[1][0] != found[0][0]:
        return ""             # two that look as likely: not a guess worth typing
    return found[0][0]


def ask_model(platform: str, subject: str, text: str, run=None) -> str:
    """When the words alone don't say which it is: the model is shown this one message and asked. Whatever it answers
    has to be in the message, or it is not taken. `run` runs the question where the model's clients live (the
    account's own event loop); left out, it gets a loop of its own."""
    if not _CODE_WORD.search(f"{subject}\n{text}"):
        return ""             # no code spoken of at all: not worth a question
    try:
        import asyncio
        from app.utils import ai
        question = ai.condense(
            f"Subject: {subject}\n\n{text[:4000]}",
            f"This is an email from {_name(platform)}. Reply with only the sign-in or verification code "
            "it gives, exactly as written, or NONE if there is none.", max_tokens=60)
        answer = (run or asyncio.run)(question)
    except Exception:
        return ""
    code = answer.strip().strip(".").split()[0] if answer.strip() else ""
    if not code or code.upper() == "NONE" or not re.fullmatch(r"[A-Za-z0-9]{4,10}", code):
        return ""
    return code if code in subject or code in text else ""


# ── The mailboxes ──────────────────────────────────────────────────────────────────────────────

def mailboxes() -> list:
    """Each mailbox in config/.env: {"index", "address", "password", "server"}. Read from the file each time, so one
    added while an account runs is used without a restart."""
    from app.web.envfile import read_env
    env = read_env()
    out = []
    for key, address in env.items():
        m = re.fullmatch(r"MAIL_(\d+)", key)
        if m and address.strip():
            n = m.group(1)
            out.append({"index": int(n), "address": address.strip(), "password": env.get(f"MAIL_PASSWORD_{n}", ""),
                        "server": env.get(f"MAIL_SERVER_{n}", "")})
    return sorted(out, key=lambda b: b["index"])


def _found_path():
    from app.utils.paths import DATA_DIR
    return DATA_DIR / "cache" / "mail_codes.json"


_lock = threading.Lock()


def _note_found(address: str, platform: str) -> None:
    """When each mailbox last gave a code, for the panel to show (never the code itself)."""
    with _lock:
        path = _found_path()
        try:
            seen = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}
        seen[address.lower()] = {"platform": platform, "ts": time.time()}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(seen), encoding="utf-8")
        except OSError:
            pass


def last_found() -> dict:
    try:
        return json.loads(_found_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


#: Codes already typed, so the same one is never typed twice.
_used: set = set()


def find_code(platform: str, since: float, boxes: list | None = None, opener=connect, model=ask_model) -> dict | None:
    """One look in every mailbox: {"code", "address"} for the newest code the social sent since `since`, or None."""
    for box in boxes if boxes is not None else mailboxes():
        if not box["server"] or not box["password"]:
            continue
        try:
            conn = opener(box["server"], box["address"], box["password"])
        except MailError:
            continue
        try:
            for msg in messages(conn, platform, since):
                code = extract(msg["subject"], msg["text"]) or model(platform, msg["subject"], msg["text"])
                if code and (platform, code) not in _used:
                    _used.add((platform, code))
                    _note_found(box["address"], platform)
                    return {"code": code, "address": box["address"]}
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    return None


def wait_for_code(platform: str, since: float, wait_s: float = WAIT_S, stop=None, **kw) -> dict | None:
    """Looks every few seconds until the code comes, `wait_s` passes, or `stop()` says to give up."""
    until = time.time() + wait_s
    while time.time() < until:
        if stop is not None and stop():
            return None
        found = find_code(platform, since, **kw)
        if found:
            return found
        time.sleep(EVERY_S)
    return None
