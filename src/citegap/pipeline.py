"""Orchestrates the stages and emits progress events (the UI's live call log)."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from .analyze.access import analyze_access
from .analyze.deep import analyze_deep
from .collect.browser_deep import run_deep
from .analyze.answerability import analyze_answerability
from .analyze.bridge import build_bridges
from .analyze.context import AuditData, ev
from .analyze.extractability import analyze_extractability
from .analyze.features import build_features
from .analyze.lint import lint
from .analyze.pagetype import infer_page_type
from .analyze.scoring import score_ars, score_svs
from .analyze.semantics import analyze_semantics
from .analyze.serp_gap import analyze_serp
from .collect.answerability import HighlightsResult, collect_highlights
from .collect.competitors import collect_competitors, pick_competitors
from .collect.serp import SerpData, collect_serp, derive_query, looks_like_answer_page
from .collect.site_files import collect_site_files
from .collect.target import collect_target
from .config import Settings
from .report.model import Evidence, Report, WhatAISees, WhatAISeesLine
from .tinyfish.client import TinyFishClient
from .util import check_public_url, clip, host_of, normalize_url, resolve_host, word_count

Emit = Callable[[dict], None]
_BOILER = re.compile(r"(cookie|accept all|privacy policy|terms of (use|service)|subscribe|newsletter|sign in|log in|"
                     r"all rights reserved|copyright|skip to (main )?content|©)", re.I)


class AuditError(Exception):
    """Configuration/API problem (bad key, quota) — NOT a finding about the audited page."""


async def run_audit(url: str, query: Optional[str] = None, *, settings: Settings, client: Optional[TinyFishClient] = None,
                    emit: Optional[Emit] = None, raw_transport=None, resolver=None, audit_id: Optional[str] = None,
                    store=None, llm_transport=None, deep: bool = False, deep_driver=None) -> Report:
    t0 = time.monotonic()
    stage = {"name": "start"}

    def E(name: str, message: str, call: Optional[dict] = None) -> None:
        stage["name"] = name
        if emit:
            emit({"stage": name, "message": message, **({"tinyfish_call": call} if call else {})})

    res = resolver or resolve_host
    ok, reason, _ = check_public_url(url, res)
    if not ok:
        raise ValueError(f"URL rejected: {reason}")
    own_client = client is None
    if client is None:
        client = TinyFishClient(settings)
    client.on_call = lambda e: emit and emit({"stage": stage["name"], "message": e.summary, "tinyfish_call": e.model_dump()})
    kw = {"raw_transport": raw_transport, "resolver": resolver}
    try:
        E("target", "Fetching the live page (markdown, HTML, main-content test) and plain HTTP")
        target = await collect_target(client, url, settings, **kw)
        _raise_on_api_problem(target)
        raw_doc = target.raw.doc if target.raw else None
        doc = target.rendered_doc or raw_doc
        md = target.md.text if target.md and target.md.text else ""
        h1 = doc.h1s[0] if doc and doc.h1s else None
        title = (raw_doc.title if raw_doc and raw_doc.title else None) or (target.md.title if target.md else None)
        final_url = target.final_url
        E("target", f"Target read: {word_count(md)} words extracted, final URL {final_url}" if md else "Target could not be read; continuing with the search half")
        derived = not (query and query.strip())
        q = (query or "").strip() or derive_query(title, h1, md or (doc.text if doc else "")) or _query_from_url(url)
        ptype, _ = infer_page_type(final_url, raw_doc or doc, md)
        urls = list(dict.fromkeys([url, final_url] + ([raw_doc.canonical] if raw_doc and raw_doc.canonical else [])))
        html_lang = (raw_doc.html_lang if raw_doc else None) or (target.rendered_doc.html_lang if target.rendered_doc else None) \
            or (target.md.language if target.md else None)

        E("search", f"Searching: how the page shows up for “{q}”" + (" (derived query)" if derived else ""))
        serp_t = collect_serp(client, settings, target_urls=urls, query=q, page_title=title, h1=h1, html_lang=html_lang,
                              answer_page=looks_like_answer_page(h1, word_count(md), ptype))
        site_t = collect_site_files(client, url, settings, **kw)
        serp, site = await asyncio.gather(serp_t, site_t)
        E("search", f"Rank: {'#' + str(serp.rank) if serp.rank else 'not found'}; indexation probe: {serp.indexation}")

        comps_sel = pick_competitors(serp.organic, final_url, settings.competitors) if serp.organic else []
        E("competitors", f"Fetching {len(comps_sel)} competitor(s) live")
        comps = await collect_competitors(client, settings, comps_sel, **kw)
        E("answerability", "Checking which passages answer the query")
        if target.fully_failed or not comps:
            hl = HighlightsResult(method="bm25", reason="no target content" if target.fully_failed else "no competitors")
        else:
            hl = await collect_highlights(client, [url] + [c.serp.url for c in comps], q, h1)
        E("answerability", f"Method: {hl.method}" + (f" ({hl.reason})" if hl.reason and hl.method == 'bm25' else ""))

        tf = build_features(final_url, md, q, title=title, doc=raw_doc or doc,
                            fetch_date=target.md.published_date if target.md else None,
                            fetch_author=target.md.author if target.md else None,
                            serp_position=serp.rank, serp_snippet=serp.target_entry.snippet if serp.target_entry else None)
        cfs = [build_features(c.serp.url, c.fetch.text if c.fetch else "", q, title=(c.fetch.title if c.fetch else None) or c.serp.title,
                              doc=c.raw_doc, fetch_date=c.fetch.published_date if c.fetch else None,
                              fetch_author=c.fetch.author if c.fetch else None, serp_position=c.serp.position,
                              serp_snippet=c.serp.snippet) for c in comps if c.fetch and (c.fetch.text or "").strip()]
        # BM25 fallback needs all pages; with real highlights, overwrite coverage from returned passages
        d = AuditData(url=url, query=q, query_derived=derived, settings=settings, target=target, serp=serp, site=site,
                      competitors=comps, target_features=tf, competitor_features=cfs, highlights=hl, page_type=ptype)
        E("analyze", "Analyzing access, extractability, semantics, answerability and SERP gap")
        findings = []
        for fn in (analyze_access, analyze_extractability, analyze_semantics, analyze_answerability):
            findings += fn(d)
        serp_findings, delta, extras = analyze_serp(d)
        findings += serp_findings
        shot = None
        if deep and not target.fully_failed:
            E("browser", "Deep mode: opening the page in a remote browser (uses TinyFish credits; experimental)")
            dres = await run_deep(client, final_url, deep_driver)
            if dres.error:
                d.notes.append(f"Deep mode did not complete ({dres.error}).")
            else:
                bcall = next((c.id for c in client.calls if c.endpoint == "browser"), None)
                findings += analyze_deep(d, dres, bcall)
                shot = dres.screenshot_jpeg_b64
        for c in comps:
            if c.error:
                d.notes.append(f"Competitor {c.serp.url} could not be fetched ({c.error.error}); excluded from the delta.")
        if hl.method == "bm25" and hl.reason and "no " not in hl.reason:
            d.notes.append(f"Fetch highlights unavailable ({hl.reason}); used local BM25 passage scoring.")
        kept, dropped = lint(findings)
        bridges = build_bridges(d, kept)
        E("score", "Scoring and building the report")
        could_not_read = target.fully_failed
        ars = score_ars(kept, could_not_read)
        rated = [r for r in delta if r["status"] != "n/a"]
        svs = score_svs(d, kept, sum(1 for r in rated if r["status"] == "ok"), len(rated), extras.get("title_match"))
        rep = Report(
            id=audit_id or uuid.uuid4().hex[:10], url=url, final_url=final_url, query=q, query_derived=derived,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), duration_s=round(time.monotonic() - t0, 1),
            could_not_read=could_not_read, answerability_method=hl.method, ars=ars, svs=svs, findings=kept, bridges=bridges,
            lint_dropped=dropped, target=tf, competitors=cfs, serp=serp.probes, delta_table=delta,
            domain_share=extras.get("domain_share"), what_ai_sees=build_what_ai_sees(d), serp_card=build_serp_card(d, serp),
            calls=list(client.calls), notes=d.notes)
        rep.endpoints_used = {ep: sum(1 for c in rep.calls if c.endpoint == ep) for ep in ("search", "fetch", "browser") if any(c.endpoint == ep for c in rep.calls)}
        if shot:
            rep.extras["screenshot_jpeg_b64"] = shot
        if store is not None:
            prev = store.previous_for(url)  # new report is saved after this, so the latest stored one is the prior run
            if prev:
                rep.previous = previous_delta(prev, rep)
        E("done", f"Done in {rep.duration_s}s: ARS {ars.total:.0f}, SVS {svs.total:.0f}")
        return rep
    finally:
        if own_client:
            await client.aclose()


def _raise_on_api_problem(t) -> None:
    for err in (t.md_error, t.html_error, t.main_error):
        if err is not None and err.request_level and (err.status in (401, 402, 403, 429) or err.error == "missing_api_key"):
            raise AuditError(f"TinyFish API problem: {err.error}" + (f" (HTTP {err.status})" if err.status else "") +
                             ". Check TINYFISH_API_KEY, quota and rate limits; this is not a finding about the page.")


def _query_from_url(url: str) -> str:
    slug = re.sub(r"https?://[^/]+", "", url).strip("/").split("/")[-1] if re.sub(r"https?://[^/]+", "", url).strip("/") else ""
    words = re.sub(r"[-_]+", " ", re.sub(r"\.\w+$", "", slug)).strip()
    return words or host_of(url).split(".")[0]


def build_what_ai_sees(d: AuditData) -> WhatAISees:
    t = d.target
    main_lines = {l.strip() for l in (t.main.text or "").splitlines() if l.strip()} if t.main and t.main.text else None
    lines = []
    for l in d.md.splitlines():
        s = l.strip()
        if not s:
            continue
        boiler = (s not in main_lines) if main_lines is not None else bool(len(s) <= 120 and _BOILER.search(s))
        lines.append(WhatAISeesLine(text=l.rstrip(), boilerplate=boiler))
    lost: list[Evidence] = []
    md_norm = re.sub(r"\s+", " ", d.md.lower())
    if t.rendered_doc:
        missing = [h for _, h in t.rendered_doc.headings if re.sub(r"\s+", " ", h.lower()) not in md_norm]
        for h in missing[:8]:
            lost.append(ev("quote", f"heading in the page HTML but not in the extracted text: {h}", t.html.call_id if t.html else None))
        for u in t.rendered_doc.iframes[:5]:
            lost.append(ev("selector", f"iframe content not extracted inline: {u}"))
        nalt = sum(1 for i in t.rendered_doc.images if i["alt"] is None)
        if nalt:
            lost.append(ev("metric", f"{nalt} image(s) without alt text carry no text for AI"))
    raw_w = t.raw.doc.word_count if t.raw and t.raw.doc else 0
    rend_w = word_count(d.md)
    if raw_w and rend_w and raw_w < 0.4 * rend_w:
        lost.append(ev("metric", f"JS-only content: {rend_w - raw_w} of {rend_w} words absent from raw HTML"))
    return WhatAISees(lines=lines, lost=lost, rendered_chars=len(d.md), raw_chars=len(t.raw.doc.text) if t.raw and t.raw.doc else 0,
                      extraction_method="main/article landmarks" if main_lines is not None else "heuristic boilerplate detection")


def build_serp_card(d: AuditData, serp: SerpData) -> dict:
    e = serp.target_entry
    return {
        "position": serp.rank, "serp_title": e.title if e else None, "serp_snippet": e.snippet if e else None,
        "serp_url": e.url if e else None, "page_title": d.page_title, "meta_description": d.meta_description,
        "indexation": serp.indexation, "pages_checked": serp.pages_checked,
        "competitors": [{"position": r.position, "title": r.title, "snippet": r.snippet, "url": r.url}
                        for r in [c.serp for c in d.competitors]],
    }


def previous_delta(prev: Report, now: Report) -> dict:
    p_ids, n_ids = {f.id for f in prev.findings}, {f.id for f in now.findings}
    rk = lambda r: (r.serp_card or {}).get("position")
    return {"id": prev.id, "created_at": prev.created_at, "ars": prev.ars.total, "svs": prev.svs.total,
            "ars_delta": round(now.ars.total - prev.ars.total, 1), "svs_delta": round(now.svs.total - prev.svs.total, 1),
            "rank_prev": rk(prev), "rank_now": rk(now), "fixed": sorted(p_ids - n_ids), "new": sorted(n_ids - p_ids)}
