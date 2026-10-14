"""Fetch wrapper: batching to 10 URLs, per-URL error normalization."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .client import TinyFishClient, TinyFishError

BATCH = 10
PURPOSE_DEFAULT = "Audit what an AI tool can extract from this page"


class FetchResult(BaseModel):
    url: str
    final_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[str] = None
    text: Optional[str] = None
    links: list[Any] = Field(default_factory=list)
    image_links: list[Any] = Field(default_factory=list)
    iframe_links: list[Any] = Field(default_factory=list)
    unmatched_selectors: list[str] = Field(default_factory=list)
    highlights: Optional[list[Any]] = None
    latency_ms: Optional[float] = None
    format: Optional[str] = None
    call_id: Optional[str] = None


class FetchFailure(BaseModel):
    url: str
    error: str
    status: Optional[int] = None
    unmatched_selectors: list[str] = Field(default_factory=list)
    candidate_selectors: list[Any] = Field(default_factory=list)
    call_id: Optional[str] = None
    request_level: bool = False  # True when the whole HTTP request failed


class FetchBatch(BaseModel):
    results: dict[str, FetchResult] = Field(default_factory=dict)
    errors: dict[str, FetchFailure] = Field(default_factory=dict)
    request_error: Optional[str] = None
    request_status: Optional[int] = None

    def get(self, url: str) -> FetchResult | None:
        return self.results.get(url)


def _link_urls(items: list[Any]) -> list[Any]:
    return items or []


def normalize(data: dict, requested: list[str], call_id: Optional[str]) -> FetchBatch:
    batch = FetchBatch()
    for r in data.get("results") or []:
        url = r.get("url") or ""
        res = FetchResult(
            url=url, final_url=r.get("final_url") or url, title=r.get("title"),
            description=r.get("description"), language=r.get("language"),
            author=r.get("author"), published_date=r.get("published_date"),
            text=r.get("text"), links=r.get("links") or [], image_links=r.get("image_links") or [],
            iframe_links=r.get("iframe_links") or [],
            unmatched_selectors=r.get("unmatched_selectors") or [],
            highlights=r.get("highlights"), latency_ms=r.get("latency_ms"),
            format=r.get("format"), call_id=call_id)
        batch.results[url] = res
    for e in data.get("errors") or []:
        url = e.get("url") or ""
        batch.errors[url] = FetchFailure(
            url=url, error=str(e.get("error") or "unknown"), status=e.get("status"),
            unmatched_selectors=e.get("unmatched_selectors") or [],
            candidate_selectors=e.get("candidate_selectors") or [], call_id=call_id)
    # URLs the API silently dropped
    for u in requested:
        if u not in batch.results and u not in batch.errors:
            # tolerate normalization differences (trailing slash)
            alt = {k.rstrip("/"): k for k in batch.results}
            if u.rstrip("/") in alt:
                batch.results[u] = batch.results[alt[u.rstrip("/")]]
            else:
                altE = {k.rstrip("/"): k for k in batch.errors}
                if u.rstrip("/") in altE:
                    batch.errors[u] = batch.errors[altE[u.rstrip("/")]]
                else:
                    batch.errors[u] = FetchFailure(url=u, error="missing_from_response", call_id=call_id)
    return batch


async def fetch_many(client: TinyFishClient, urls: list[str], *, summary: str,
                     fmt: str = "markdown", links: bool = False, image_links: bool = False,
                     iframe_links: bool = False, per_url_timeout_ms: int = 60000,
                     include_selectors: list[str] | None = None,
                     exclude_selectors: list[str] | None = None,
                     highlights: dict | None = None, purpose: str = PURPOSE_DEFAULT) -> FetchBatch:
    """Fetch urls live (ttl=0 forced by the client). Never raises on API errors."""
    merged = FetchBatch()
    for i in range(0, len(urls), BATCH):
        chunk = urls[i:i + BATCH]
        body: dict[str, Any] = {"urls": chunk, "format": fmt, "per_url_timeout_ms": per_url_timeout_ms,
                                "purpose": purpose}
        if links:
            body["links"] = True
        if image_links:
            body["image_links"] = True
        if iframe_links:
            body["iframe_links"] = True
        if include_selectors:
            body["include_selectors"] = include_selectors
        if exclude_selectors:
            body["exclude_selectors"] = exclude_selectors
        if highlights:
            body["highlights"] = highlights
        before = len(client.calls)
        try:
            data = await client.fetch(body, summary=summary)
        except TinyFishError as exc:
            cid = client.calls[before].id if len(client.calls) > before else None
            merged.request_error, merged.request_status = f"{exc.code}: {exc.message}", exc.status
            for u in chunk:
                merged.errors[u] = FetchFailure(url=u, error=exc.code, status=exc.status,
                                                call_id=cid, request_level=True)
            continue
        cid = client.calls[before].id if len(client.calls) > before else None
        b = normalize(data, chunk, cid)
        merged.results.update(b.results)
        merged.errors.update(b.errors)
    return merged
