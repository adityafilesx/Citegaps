"""SSRF-safe plain GET (no JS) used to read the raw HTML crawlers without JS would see."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ..config import Settings
from ..util import check_public_url, resolve_host
from .htmlparse import Doc, parse_document

MAX_REDIRECTS = 5


@dataclass
class RawResponse:
    url: str
    final_url: str = ""
    status: Optional[int] = None
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    text: str = ""
    truncated: bool = False
    redirects: list[str] = field(default_factory=list)
    error: Optional[str] = None
    x_robots: list[str] = field(default_factory=list)
    doc: Optional[Doc] = None


def _pin(url: str, ip: str) -> tuple[str, str]:
    """Rewrite the URL host to the validated IP; return (new_url, original_host_header)."""
    p = urlsplit(url)
    host = p.hostname or ""
    netloc_ip = f"[{ip}]" if ":" in ip else ip
    netloc = netloc_ip + (f":{p.port}" if p.port else "")
    hdr = host + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, p.path or "/", p.query, "")), hdr


async def fetch_raw(url: str, settings: Settings, *, resolver: Callable = resolve_host,
                    transport: Optional[httpx.AsyncBaseTransport] = None,
                    parse: bool = True) -> RawResponse:
    out = RawResponse(url=url, final_url=url)
    current = url
    async with httpx.AsyncClient(transport=transport, timeout=settings.raw_timeout_s, follow_redirects=False,
                                 headers={"User-Agent": settings.raw_user_agent,
                                          "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            ok, reason, ips = check_public_url(current, resolver)
            if not ok:
                out.error = f"blocked by SSRF guard: {reason}"
                return out
            target, host_hdr = _pin(current, ips[0])
            ext = {"sni_hostname": urlsplit(current).hostname} if urlsplit(current).scheme == "https" else {}
            try:
                async with client.stream("GET", target, headers={"Host": host_hdr}, extensions=ext) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        out.redirects.append(current)
                        current = urljoin(current, resp.headers["location"])
                        continue
                    out.final_url = current
                    out.status = resp.status_code
                    out.headers = {k.lower(): v for k, v in resp.headers.items()}
                    out.content_type = out.headers.get("content-type", "")
                    out.x_robots = [v for k, v in resp.headers.multi_items() if k.lower() == "x-robots-tag"]
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > settings.raw_max_bytes:
                            out.truncated = True
                            break
                    enc = resp.encoding or "utf-8"
                    out.text = bytes(buf[: settings.raw_max_bytes]).decode(enc, errors="replace")
            except httpx.TimeoutException:
                out.error = "timeout"
                return out
            except httpx.HTTPError as exc:
                out.error = f"network error: {type(exc).__name__}"
                return out
            if parse and out.text and ("html" in out.content_type.lower() or "<html" in out.text[:2000].lower()):
                out.doc = parse_document(out.text, out.final_url)
            return out
        out.error = "too many redirects"
        return out
