"""Markdown/HTML feature extraction shared by target and competitors, plus passage scoring."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from rank_bm25 import BM25Okapi

from ..collect.htmlparse import Doc, iter_jsonld_nodes
from ..report.model import PageFeatures
from ..util import content_terms, stem, word_count, words

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_FENCE = re.compile(r"```.*?```", re.S)
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_COPULA = re.compile(r"\b(is|are|was|were|means|refers to|stands for|defined as|consists of)\b", re.I)
_BOILER_LINE = re.compile(r"(cookie|accept all|privacy policy|terms of (use|service)|subscribe|newsletter|sign in|log in|"
                          r"all rights reserved|copyright|skip to (main )?content|menu|©)", re.I)


def clean_md(md: str) -> str:
    md = _FENCE.sub(" ", md or "")
    return _LINK.sub(lambda m: m.group(1), md)


def md_headings(md: str) -> list[tuple[int, str]]:
    out = []
    for line in (md or "").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            out.append((len(m.group(1)), re.sub(r"[*_`]", "", m.group(2)).strip()))
    return out


def md_paragraphs(md: str) -> list[str]:
    paras, buf = [], []
    for line in clean_md(md).splitlines() + [""]:
        s = line.strip()
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        if s.startswith("#") or _TABLE_SEP.match(s) or s.startswith("|") or _LIST.match(s):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(s)
    return [p for p in paras if word_count(p) >= 8]


def md_counts(md: str) -> dict[str, int]:
    lists = tables = 0
    in_list = False
    lines = (md or "").splitlines()
    for i, line in enumerate(lines):
        if _LIST.match(line):
            if not in_list:
                lists += 1
            in_list = True
        else:
            in_list = False
        if _TABLE_SEP.match(line) and i > 0 and "|" in lines[i - 1]:
            tables += 1
    return {"lists": lists, "tables": tables}


def has_faq_md(heads: list[tuple[int, str]]) -> bool:
    if any(re.search(r"\bfaq\b|frequently asked|common questions", t, re.I) for _, t in heads):
        return True
    return sum(1 for _, t in heads if t.rstrip().endswith("?")) >= 2


def query_stems(query: str) -> list[str]:
    return sorted({stem(t) for t in content_terms(query)})


def coverage(text: str, qstems: list[str]) -> float:
    if not qstems:
        return 0.0
    have = {stem(t) for t in content_terms(text)}
    return sum(1 for s in qstems if s in have) / len(qstems)


def first_n_words(md: str, n: int = 150) -> str:
    body = "\n".join(l for l in clean_md(md).splitlines() if not l.strip().startswith("#"))
    return " ".join(words(body)[:n])


def answer_first(md: str, query: str) -> bool:
    qs = query_stems(query)
    paras = md_paragraphs(md)[:2]
    if not qs or not paras:
        return False
    budget = " ".join(paras)
    budget = " ".join(budget.split()[:120])
    for sent in re.split(r"(?<=[.!?])\s+", budget):
        if coverage(sent, qs) >= 0.5 and (_COPULA.search(sent) or re.search(r"\d", sent)):
            return True
    return False


def chunk_passages(md: str, max_words: int = 90) -> list[str]:
    out: list[str] = []
    for p in md_paragraphs(md):
        w = p.split()
        for i in range(0, len(w), max_words):
            out.append(" ".join(w[i:i + max_words]))
    # include list items grouped as one passage each so lists can answer
    return out


def best_passage(md: str, query: str) -> tuple[Optional[str], Optional[float], float]:
    """(passage, bm25 score, query-term coverage of that passage). Local fallback for highlights."""
    qs = query_stems(query)
    chunks = chunk_passages(md)
    if not chunks or not qs:
        return None, None, 0.0
    toks = [[stem(t) for t in content_terms(c)] for c in chunks]
    bm = BM25Okapi([t or ["_"] for t in toks])
    scores = list(bm.get_scores(qs))
    covs = [coverage(c, qs) for c in chunks]
    # rank by coverage first (comparable across pages), BM25 as tie-break
    idx = max(range(len(chunks)), key=lambda i: (covs[i], scores[i]))
    return chunks[idx], float(scores[idx]), covs[idx]


def _jsonld_value(doc: Doc, *keys: str) -> Optional[str]:
    for node in iter_jsonld_nodes(doc.jsonld):
        for k in keys:
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, (dict, list)) and v:
                return str(v)[:80]
    return None


def page_date(doc: Optional[Doc], fetch_date: Optional[str]) -> Optional[str]:
    if fetch_date:
        return fetch_date
    if doc is None:
        return None
    v = _jsonld_value(doc, "dateModified", "datePublished")
    if v:
        return v
    for k in ("article:modified_time", "article:published_time"):
        if doc.meta_dates.get(k):
            return doc.meta_dates[k]
    for v in doc.meta_dates.values():
        if v:
            return v
    for t in doc.time_datetimes:
        if t:
            return t
    return None


def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y/%m/%d",
                "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s.replace("Z", "+0000") if "%z" in fmt else s, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def has_author(doc: Optional[Doc], fetch_author: Optional[str]) -> bool:
    if fetch_author:
        return True
    if doc is None:
        return False
    return bool(doc.author_meta or doc.byline_found or _jsonld_value(doc, "author", "creator"))


def build_features(url: str, md: Optional[str], query: str, *, title: Optional[str] = None,
                   doc: Optional[Doc] = None, fetch_date: Optional[str] = None,
                   fetch_author: Optional[str] = None, serp_position: Optional[int] = None,
                   serp_snippet: Optional[str] = None) -> PageFeatures:
    md = md or ""
    heads = md_headings(md)
    counts = md_counts(md)
    qs = query_stems(query)
    f150 = first_n_words(md, 150)
    pas, score, cov = best_passage(md, query)
    types = doc.jsonld_types if doc is not None else []
    return PageFeatures(
        url=url, title=title, word_count=word_count(clean_md(md)),
        h2_count=sum(1 for l, _ in heads if l == 2), list_count=counts["lists"],
        table_count=counts["tables"],
        has_faq=has_faq_md(heads) or "FAQPage" in types,
        schema_types=types, schema_known=doc is not None, date=page_date(doc, fetch_date),
        has_author=has_author(doc, fetch_author), answer_first=answer_first(md, query),
        query_coverage_first150=round(coverage(f150, qs), 2), best_passage=pas,
        best_passage_score=round(score, 2) if score is not None else None,
        passage_coverage=round(cov, 2), serp_position=serp_position, serp_snippet=serp_snippet)


def highlight_texts(highlights: Any) -> list[str]:
    out: list[str] = []
    for h in highlights or []:
        if isinstance(h, str):
            out.append(h)
        elif isinstance(h, dict):
            t = h.get("text") or h.get("passage") or h.get("snippet") or h.get("content")
            if t:
                out.append(str(t))
    return out
