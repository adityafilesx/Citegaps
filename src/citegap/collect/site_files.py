"""robots.txt / llms.txt / sitemap.xml via one batched Fetch (+ raw GET fallback for robots)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

from ..config import Settings
from ..tinyfish.client import TinyFishClient
from ..tinyfish.fetch import fetch_many
from ..util import normalize_url
from .raw_http import fetch_raw


@dataclass
class SiteFile:
    url: str
    status: str = "unknown"  # ok | missing | error
    text: str = ""
    error: Optional[str] = None
    source: str = "fetch"
    call_id: Optional[str] = None


@dataclass
class SiteFiles:
    origin: str
    robots: SiteFile
    llms: SiteFile
    sitemap: SiteFile
    sitemap_kind: str = "none"  # urlset | index | none
    sitemap_urls: list[str] = field(default_factory=list)

    def sitemap_contains(self, url: str) -> Optional[bool]:
        """None when undeterminable (index or missing)."""
        if self.sitemap_kind != "urlset":
            return None
        want = normalize_url(url)
        return any(normalize_url(u) == want for u in self.sitemap_urls)


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def parse_sitemap(text: str) -> tuple[str, list[str]]:
    if re.search(r"<sitemapindex", text or "", re.I):
        return "index", re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.S)
    if re.search(r"<urlset", text or "", re.I):
        return "urlset", re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.S)
    return "none", []


def _clean_text(text: str) -> str:
    return text or ""


async def collect_site_files(client: TinyFishClient, url: str, settings: Settings,
                             raw_transport=None, resolver=None) -> SiteFiles:
    origin = origin_of(url)
    urls = [f"{origin}/robots.txt", f"{origin}/llms.txt", f"{origin}/sitemap.xml"]
    batch = await fetch_many(client, urls, summary="Fetch site files (robots, llms.txt, sitemap)",
                             fmt="markdown", per_url_timeout_ms=30000,
                             purpose="Check AI-bot access rules, llms.txt and sitemap coverage")
    files: list[SiteFile] = []
    for u in urls:
        sf = SiteFile(url=u)
        r = batch.results.get(u)
        e = batch.errors.get(u)
        if r is not None and (r.text or "").strip():
            sf.status, sf.text, sf.call_id = "ok", _clean_text(r.text), r.call_id
        elif e is not None:
            sf.call_id = e.call_id
            if e.error in ("page_not_found",) or (e.error == "target_http_error" and e.status in (404, 410)):
                sf.status = "missing"
            else:
                sf.status, sf.error = "error", f"{e.error}{' ' + str(e.status) if e.status else ''}"
        else:
            sf.status = "missing"
        files.append(sf)
    robots, llms, sm = files
    if robots.status != "ok" or "user-agent" not in robots.text.lower():
        kw = {"transport": raw_transport}
        if resolver:
            kw["resolver"] = resolver
        raw = await fetch_raw(robots.url, settings, parse=False, **kw)
        if raw.status == 200 and "user-agent" in raw.text.lower():
            robots.status, robots.text, robots.source, robots.error = "ok", raw.text, "raw-http", None
        elif robots.status != "ok" and raw.status == 404:
            robots.status = "missing"
    kind, locs = parse_sitemap(sm.text) if sm.status == "ok" else ("none", [])
    return SiteFiles(origin=origin, robots=robots, llms=llms, sitemap=sm, sitemap_kind=kind, sitemap_urls=locs)
