"""Stage 2: Search probes (rank, indexation, exact-title, question) and query derivation."""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings
from ..report.model import SerpProbe, SerpResult
from ..tinyfish.client import TinyFishClient
from ..tinyfish.search import run_probe
from ..util import content_terms, host_of, normalize_url, same_site, words

BRAND_SPLIT = re.compile(r"\s+[|–—•·]\s+|\s+-\s+")
QUESTION_WORDS = ("how", "what", "why", "when", "where", "which", "who", "can", "does", "do", "is", "are", "should")


def core_title(title: str) -> str:
    """Drop the brand suffix/prefix: 'Foo bar | Brand' -> 'Foo bar' (keeps the longest segment)."""
    parts = [p.strip() for p in BRAND_SPLIT.split(title or "") if p.strip()]
    return max(parts, key=len) if parts else (title or "").strip()


def derive_query(title: Optional[str], h1: Optional[str], text: str) -> str:
    """H1 (or title) core, trimmed to 8 words; short ones are extended with top keyphrase terms."""
    base = core_title(h1 or title or "")
    ws = base.split()
    if len(ws) > 8:
        base = " ".join(ws[:8])
    if len(base.split()) >= 3:
        return base
    tf = Counter(content_terms(text))
    seed = {t for t in content_terms(base)}
    extra = [t for t, _ in tf.most_common(12) if t not in seed and len(t) > 3][:3 if base else 5]
    return " ".join([base] + extra).strip()


def question_from_h1(h1: str) -> str:
    h = h1.strip().rstrip(".")
    if h.endswith("?"):
        return h
    if h.lower().split(" ")[0] in QUESTION_WORDS:
        return h + "?"
    return f"What is {h[0].lower() + h[1:]}?" if len(h.split()) <= 6 else f"{h}?"


def looks_like_answer_page(h1: Optional[str], word_count: int, page_type: str) -> bool:
    if not h1:
        return False
    return page_type in ("article", "docs", "faq", "howto") or word_count >= 400


def lang_loc(html_lang: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not html_lang:
        return None, None
    parts = re.split(r"[-_]", html_lang.strip())
    lang = parts[0].lower() if parts and re.fullmatch(r"[a-zA-Z]{2,3}", parts[0]) else None
    loc = parts[1].upper() if len(parts) > 1 and re.fullmatch(r"[a-zA-Z]{2}", parts[1]) else None
    return lang, loc


def absolute_positions(results: list[SerpResult], offset: int) -> list[SerpResult]:
    """Page>0 positions may be page-relative; make them absolute (no-op if already > offset)."""
    if not results or min(r.position for r in results) > offset:
        return results
    return [r.model_copy(update={"position": r.position + offset}) for r in results]


def find_rank(results: list[SerpResult], urls: list[str]) -> Optional[SerpResult]:
    want = {normalize_url(u) for u in urls if u}
    for r in results:
        if normalize_url(r.url) in want:
            return r
    return None


@dataclass
class SerpData:
    probes: list[SerpProbe] = field(default_factory=list)
    query: str = ""
    target_urls: list[str] = field(default_factory=list)
    rank: Optional[int] = None
    rank_result: Optional[SerpResult] = None
    target_entry: Optional[SerpResult] = None  # best SERP entry for the target from any probe
    organic: list[SerpResult] = field(default_factory=list)  # target-query results, page 0 then 1
    pages_checked: int = 0
    indexation: str = "unknown"  # indexed | partial | none | unknown
    domain_hits: list[SerpResult] = field(default_factory=list)
    title_probe_found: Optional[bool] = None
    question_probe_domain_found: Optional[bool] = None
    question: Optional[str] = None
    error: Optional[str] = None

    def probe(self, kind: str) -> Optional[SerpProbe]:
        return next((p for p in self.probes if p.kind == kind), None)


async def collect_serp(client: TinyFishClient, settings: Settings, *, target_urls: list[str], query: str,
                       page_title: Optional[str], h1: Optional[str], html_lang: Optional[str],
                       answer_page: bool) -> SerpData:
    data = SerpData(query=query, target_urls=target_urls)
    host = host_of(target_urls[0])
    lang, loc = lang_loc(html_lang)
    common = {"language": lang, "location": loc}
    jobs = [("target_query", query, {}), ("indexation", query, {"include_domains": host})]
    if page_title and page_title.strip():
        jobs.append(("exact_title", f'"{core_title(page_title)[:120]}"', {}))
    if answer_page and h1:
        data.question = question_from_h1(h1)
        jobs.append(("question", data.question, {}))
    jobs = jobs[: settings.max_search_calls]
    probes = await asyncio.gather(*[run_probe(client, k, q, **common, **extra) for k, q, extra in jobs])
    data.probes = list(probes)
    t = data.probe("target_query")
    if t and not t.error:
        data.organic = list(t.results)
        data.pages_checked = 1
        hit = find_rank(t.results, target_urls)
        if not hit and len(data.probes) < settings.max_search_calls:
            p1 = await run_probe(client, "target_query", query, page=1, **common)
            data.probes.append(p1)
            if not p1.error:
                p1.results = absolute_positions(p1.results, offset=len(t.results))
                data.pages_checked = 2
                data.organic += p1.results
                hit = find_rank(p1.results, target_urls)
        if hit:
            data.rank, data.rank_result = hit.position, hit
    elif t and t.error:
        data.error = t.error
    ind = data.probe("indexation")
    if ind and not ind.error:
        hit = find_rank(ind.results, target_urls)
        data.domain_hits = [r for r in ind.results if same_site(r.url, target_urls[0])]
        if hit:
            data.indexation = "indexed"
        elif data.domain_hits:
            data.indexation = "partial"
        else:
            data.indexation = "none"
    tp = data.probe("exact_title")
    if tp and not tp.error:
        th = find_rank(tp.results, target_urls)
        data.title_probe_found = th is not None
        if th and data.indexation in ("partial", "none", "unknown"):
            data.indexation = "indexed"
        if th and not data.target_entry:
            data.target_entry = th
    qp = data.probe("question")
    if qp and not qp.error:
        data.question_probe_domain_found = any(same_site(r.url, target_urls[0]) for r in qp.results)
    # best entry for the presentation score: prefer the main query hit, else domain probe, else title probe
    if data.rank_result:
        data.target_entry = data.rank_result
    elif ind and not ind.error and find_rank(ind.results, target_urls):
        data.target_entry = find_rank(ind.results, target_urls)
    return data
