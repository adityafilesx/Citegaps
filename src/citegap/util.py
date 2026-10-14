"""URL normalization, host safety checks, small text helpers."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid",
                   "yclid", "_hsenc", "_hsmi", "mkt_tok"}


def normalize_url(url: str) -> str:
    """Canonical form for URL matching: strip tracking params, fragment, trailing slash, www, default ports."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = p.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https" if p.scheme in ("http", "https") else p.scheme, host + port, path,
                       urlencode(sorted(q)), ""))


def host_of(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def registrable_hint(host: str) -> str:
    """Cheap eTLD+1 approximation (last two labels; three for common 2-level TLDs)."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_site(a: str, b: str) -> bool:
    return registrable_hint(host_of(a)) == registrable_hint(host_of(b))


def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped  # type: ignore[assignment]
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified or
                (addr.version == 4 and ipaddress.ip_address("100.64.0.0") <= addr <= ipaddress.ip_address("100.127.255.255")))


def resolve_host(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def check_public_url(url: str, resolver=resolve_host) -> tuple[bool, str, list[str]]:
    """(ok, reason, ips). Rejects non-http(s), credentials, localhost, private/link-local IPs."""
    try:
        p = urlsplit(url)
    except ValueError:
        return False, "invalid url", []
    if p.scheme not in ("http", "https"):
        return False, "only http/https allowed", []
    if p.username or p.password:
        return False, "credentials in url not allowed", []
    host = p.hostname
    if not host:
        return False, "missing host", []
    if host.lower() in ("localhost",) or host.lower().endswith((".localhost", ".local", ".internal")):
        return False, "localhost/internal hostname", []
    try:
        ips = [host] if _is_ip_literal(host) else resolver(host)
    except OSError:
        return False, "dns resolution failed", []
    if not ips:
        return False, "no addresses", []
    bad = [ip for ip in ips if not is_public_ip(ip)]
    if bad:
        return False, f"non-public address {bad[0]}", ips
    return True, "ok", ips


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


_WORD = re.compile(r"[A-Za-z0-9À-ɏͰ-῿぀-ヿ一-鿿]+(?:'[a-z]+)?")


def words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def word_count(text: str) -> int:
    return len(words(text))


STOPWORDS = set("""a an the and or but if of to in on at for with by from as is are was were be been being it its this that
these those you your we our they their he she his her i me my not no do does did have has had can could should would will
may might must than then so such into over under about after before more most other some any each how what why when where
who which while also just very get got one two new use used using vs via per up out off all""".split())


def content_terms(text: str) -> list[str]:
    return [w.lower() for w in words(text) if w.lower() not in STOPWORDS and len(w) > 1]


def stem(t: str) -> str:
    for suf in ("ing", "ies", "es", "s", "ed"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


def clip(text: str, n: int = 200) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"
