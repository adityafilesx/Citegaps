"""Stage 4: Fetch `highlights` when the account has it; otherwise the caller uses local BM25."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..analyze.features import highlight_texts
from ..tinyfish.client import TinyFishClient
from ..tinyfish.fetch import fetch_many
from ..util import content_terms


@dataclass
class HighlightsResult:
    method: str = "bm25"  # highlights | bm25
    passages: dict[str, list[str]] = field(default_factory=dict)
    reason: str = ""
    call_id: str | None = None


def highlights_query(query: str, h1: str | None) -> str:
    """Retrieval works on vocabulary overlap: add entity words from the H1 that the query lacks."""
    have = set(content_terms(query))
    extra = [w for w in content_terms(h1 or "") if w not in have][:4]
    return " ".join([query] + extra).strip()


async def collect_highlights(client: TinyFishClient, urls: list[str], query: str, h1: str | None,
                             max_snippets: int = 5) -> HighlightsResult:
    res = HighlightsResult()
    if not urls:
        return res
    batch = await fetch_many(
        client, urls, summary="Fetch highlights (answerability)", fmt="markdown", per_url_timeout_ms=60000,
        highlights={"query": highlights_query(query, h1), "max_snippets": max_snippets},
        purpose="Check whether each page contains passages that answer the target query")
    if batch.request_error:
        res.reason = batch.request_error
        return res  # 403 (not enabled) or other: caller falls back to BM25
    got_any_field = False
    for u in urls:
        r = batch.results.get(u)
        if r is None:
            continue
        if r.highlights is not None:
            got_any_field = True
            res.passages[u] = highlight_texts(r.highlights)
    if got_any_field:
        res.method = "highlights"
        first = batch.results.get(urls[0])
        res.call_id = first.call_id if first else None
    else:
        res.reason = "highlights field absent in response"
    return res
