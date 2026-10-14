"""Stage 3: pick the top competitors and fetch them live (one batched Fetch) + raw HTML for schema/date."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings
from ..report.model import SerpResult
from ..tinyfish.client import TinyFishClient
from ..tinyfish.fetch import FetchFailure, FetchResult, fetch_many
from ..util import normalize_url, same_site
from .htmlparse import Doc
from .raw_http import fetch_raw


@dataclass
class CompetitorData:
    serp: SerpResult
    fetch: Optional[FetchResult] = None
    error: Optional[FetchFailure] = None
    raw_doc: Optional[Doc] = None


def pick_competitors(organic: list[SerpResult], target_url: str, n: int) -> list[SerpResult]:
    seen_urls: set[str] = set()
    seen_sites: set[str] = set()
    out: list[SerpResult] = []
    for r in organic:
        if not r.url or same_site(r.url, target_url):
            continue
        nu = normalize_url(r.url)
        site = r.site_name or nu.split("/")[2]
        if nu in seen_urls or site in seen_sites:
            continue
        if r.url.lower().split("?")[0].endswith((".pdf",)):
            pass  # PDFs are still real competition; Fetch extracts text
        seen_urls.add(nu)
        seen_sites.add(site)
        out.append(r)
        if len(out) >= n:
            break
    return out


async def collect_competitors(client: TinyFishClient, settings: Settings, comps: list[SerpResult],
                              raw_transport=None, resolver=None) -> list[CompetitorData]:
    if not comps:
        return []
    urls = [c.url for c in comps]
    kw = {"transport": raw_transport}
    if resolver:
        kw["resolver"] = resolver
    sem = asyncio.Semaphore(3)

    async def raw(u: str):
        async with sem:
            return await fetch_raw(u, settings, **kw)

    batch, raws = await asyncio.gather(
        fetch_many(client, urls, summary="Fetch top competitors", fmt="markdown", links=True,
                   per_url_timeout_ms=60000, purpose="Compare competitor page structure and content depth"),
        asyncio.gather(*[raw(u) for u in urls]))
    out = []
    for c, r in zip(comps, raws):
        out.append(CompetitorData(serp=c, fetch=batch.results.get(c.url), error=batch.errors.get(c.url),
                                  raw_doc=r.doc))
    return out
