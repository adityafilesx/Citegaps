"""Stage 1: live Fetch of the target (markdown, html, main-content selectors) + raw HTTP."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings
from ..tinyfish.client import TinyFishClient
from ..tinyfish.fetch import FetchFailure, FetchResult, fetch_many
from .htmlparse import Doc, parse_document
from .raw_http import RawResponse, fetch_raw


@dataclass
class TargetData:
    url: str
    md: Optional[FetchResult] = None
    md_error: Optional[FetchFailure] = None
    html: Optional[FetchResult] = None
    html_error: Optional[FetchFailure] = None
    main: Optional[FetchResult] = None
    main_error: Optional[FetchFailure] = None
    rendered_doc: Optional[Doc] = None
    raw: Optional[RawResponse] = None
    request_errors: list[str] = field(default_factory=list)

    @property
    def fully_failed(self) -> bool:
        return self.md is None or not (self.md.text or "").strip()

    @property
    def final_url(self) -> str:
        return (self.md.final_url if self.md else None) or (self.raw.final_url if self.raw else None) or self.url


async def _one(client: TinyFishClient, url: str, **kw):
    batch = await fetch_many(client, [url], **kw)
    return batch.results.get(url), batch.errors.get(url), batch.request_error


async def collect_target(client: TinyFishClient, url: str, settings: Settings,
                         raw_transport=None, resolver=None) -> TargetData:
    t = TargetData(url=url)
    kw_raw = {"transport": raw_transport}
    if resolver:
        kw_raw["resolver"] = resolver
    (md, md_err, e1), (html, html_err, e2), (main, main_err, e3), raw = await asyncio.gather(
        _one(client, url, summary="Fetch target (markdown+links+images+iframes)", fmt="markdown",
             links=True, image_links=True, iframe_links=True, per_url_timeout_ms=60000,
             purpose="Audit what an AI tool can extract from this page"),
        _one(client, url, summary="Fetch target (semantic html)", fmt="html", per_url_timeout_ms=60000,
             purpose="Audit page structure: headings, landmarks, alt text and link text"),
        _one(client, url, summary="Fetch target (main/article only)", fmt="markdown",
             include_selectors=["main", "article"], exclude_selectors=["nav", "footer", "aside"],
             per_url_timeout_ms=60000, purpose="Test whether main content can be isolated by landmarks"),
        fetch_raw(url, settings, **kw_raw),
    )
    t.md, t.md_error, t.html, t.html_error, t.main, t.main_error = md, md_err, html, html_err, main, main_err
    t.raw = raw
    t.request_errors = [e for e in (e1, e2, e3) if e]
    if html and html.text:
        t.rendered_doc = parse_document(html.text, html.final_url or url)
    return t
