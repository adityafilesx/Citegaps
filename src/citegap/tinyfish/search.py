"""Search wrapper with typed results."""
from __future__ import annotations

from typing import Optional

from ..report.model import SerpProbe, SerpResult
from .client import TinyFishClient, TinyFishError

PURPOSE = "Audit how a page ranks for its target query and who outranks it"


def parse_results(data: dict) -> list[SerpResult]:
    out: list[SerpResult] = []
    for i, r in enumerate(data.get("results") or [], 1):
        out.append(SerpResult(
            position=int(r.get("position") or i),
            title=r.get("title") or "",
            snippet=r.get("snippet") or "",
            url=r.get("url") or "",
            site_name=r.get("site_name") or "",
        ))
    return out


async def run_probe(client: TinyFishClient, kind: str, query: str, *, page: int = 0,
                    include_domains: Optional[str] = None, location: Optional[str] = None,
                    language: Optional[str] = None, purpose: str = PURPOSE) -> SerpProbe:
    probe = SerpProbe(kind=kind, query=query, page=page, include_domains=include_domains)
    before = len(client.calls)
    try:
        data = await client.search(
            query, purpose=purpose, summary=f"Search[{kind}] page={page}",
            page=page or None, include_domains=include_domains,
            location=location, language=language)
        probe.results = parse_results(data)
    except TinyFishError as exc:
        probe.error = str(exc)
    if len(client.calls) > before:
        probe.call_id = client.calls[before].id
    return probe
