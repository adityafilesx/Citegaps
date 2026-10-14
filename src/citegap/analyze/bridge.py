"""THE CORE: link AI-readability causes to the search-visibility symptoms they plausibly produce.

A bridge is drawn only when BOTH sides are present in this audit's evidence. Anything not directly
demonstrated is marked `inferred`. Causes with no matching symptom (or vice versa) get no bridge."""
from __future__ import annotations

from ..report.model import Bridge, Evidence, Finding
from .context import AuditData, ev

AI_VIS = "AI_ANSWER_VISIBILITY"


def _by_id(findings: list[Finding]) -> dict[str, Finding]:
    return {f.id: f for f in findings}


def _first(findings: list[Finding], *prefixes: str) -> list[Finding]:
    return [f for f in findings if any(f.id == p or f.id.startswith(p) for p in prefixes)]


def build_bridges(d: AuditData, findings: list[Finding]) -> list[Bridge]:
    by = _by_id(findings)
    bridges: list[Bridge] = []

    def add(cause: Finding, symptom_id: str, kind: str, statement: str, conf: str, evidence: list[Evidence]) -> None:
        b = Bridge(id=f"{cause.id}->{symptom_id}", cause_id=cause.id, symptom_id=symptom_id, symptom_kind=kind,
                   statement=statement, confidence=conf, evidence=evidence)  # type: ignore[arg-type]
        if any(x.id == b.id for x in bridges):
            return
        bridges.append(b)
        cause.bridge_to.append(symptom_id)
        if symptom_id in by:
            by[symptom_id].bridge_to.append(cause.id)

    not_idx, not_rank, low_rank = by.get("SERP_NOT_INDEXED"), by.get("SERP_NOT_RANKED"), by.get("SERP_RANK_LOW")
    visibility_gap = [x for x in (not_idx, not_rank, low_rank) if x]

    # 1. JS-only content <-> domain-restricted search finds other pages but not this one
    js = by.get("EXTRACT_JS_DEPENDENT")
    if js and not_idx and d.serp.indexation == "partial":
        add(js, not_idx.id, "indexation",
            f"Your content only exists after JavaScript runs. Search found {len(d.serp.domain_hits)} other page(s) on {d.serp.target_urls[0].split('/')[2]} but not this one.",
            "inferred", js.evidence[:1] + not_idx.evidence[:1])

    # 2. title rewritten <-> a title-quality problem on the page
    rw = by.get("SERP_TITLE_REWRITTEN")
    if rw:
        for tid in ("SEM_TITLE_LONG", "SEM_TITLE_BRAND_ONLY", "SEM_TITLE_H1_MISMATCH"):
            if tid in by:
                add(by[tid], rw.id, "title",
                    f"The engine replaced your title with “{_quote(rw.evidence, 'SERP title')}”, which suggests your <title> did not fit the page or the query.",
                    "observed", by[tid].evidence[:1] + rw.evidence[:2])

    # 3. no answer passage <-> poor rank/visibility
    ap = by.get("ANS_NO_PASSAGE")
    rank_gap = [x for x in (not_rank, low_rank) if x]
    if ap and rank_gap:
        for sy in rank_gap[:1]:
            add(ap, sy.id, "rank", f"Competitors have passages that answer “{d.query}”; your page has none. That fits the rank gap.",
                "inferred", ap.evidence[:2] + sy.evidence[:1])

    # 3b. query terms missing from title/H1 <-> poor rank
    qh = by.get("ANS_QUERY_NOT_IN_HEADLINE")
    if qh and rank_gap:
        add(qh, rank_gap[0].id, "rank", f"The target query's terms are not in your title or H1, and the page is {'absent from' if rank_gap[0].id == 'SERP_NOT_RANKED' else 'on the second page of'} the results for it.",
            "inferred", qh.evidence[:2] + rank_gap[0].evidence[:1])

    # 4. missing/incorrect JSON-LD <-> competitors show richer snippets
    rich = by.get("SERP_COMPETITOR_RICHER_SNIPPETS")
    if rich:
        for cid in ("SEM_JSONLD_MISSING", "SEM_JSONLD_TYPE_MISMATCH", "SEM_NO_AUTHOR_DATE"):
            if cid in by:
                add(by[cid], rich.id, "rich_snippet", "Competitors' results carry dates/ratings/prices in their snippets; your page exposes no structured data to do the same.",
                    "inferred", by[cid].evidence[:1] + rich.evidence[:2])

    # 5. robots blocks AI search/user bots -> AI answer visibility (NOT Google rank)
    blocked = [f for f in findings if f.id.startswith("ACCESS_BOT_BLOCKED_") and f.severity == "high"
               and not f.id.endswith(("GOOGLEBOT", "BINGBOT"))]
    for f in blocked:
        bot = f.title.split(" blocks ")[1].split(" (")[0] if " blocks " in f.title else f.id
        add(f, AI_VIS, "ai_visibility",
            f"robots.txt blocks {bot}. That is an AI-answer visibility loss for that product, not a Google ranking signal.",
            "observed", f.evidence[:2])

    # 6. boilerplate-heavy extraction <-> snippet pulled from boilerplate
    bp, sn_ = by.get("EXTRACT_BOILERPLATE_HEAVY"), by.get("SERP_SNIPPET_BOILERPLATE")
    if bp and sn_:
        add(bp, sn_.id, "snippet", "Most of the extractable text is navigation/footer, and the search snippet was built from it.",
            "observed", bp.evidence[:1] + sn_.evidence[:1])

    # 7. thin content <-> competitors have far more depth
    thin, depth = by.get("EXTRACT_THIN_CONTENT"), by.get("SERP_THIN_VS_COMPETITORS")
    if thin and depth:
        add(thin, depth.id, "depth", "Your page is thin and the pages outranking it carry several times the content.", "inferred",
            thin.evidence[:1] + depth.evidence[:1])
    if thin and not depth and visibility_gap:
        pass  # no competitor delta -> no bridge

    # 8. noindex <-> not indexed
    ni = by.get("ACCESS_NOINDEX")
    if ni and not_idx:
        add(ni, not_idx.id, "indexation", "The page carries a noindex directive and search does not surface it, consistent with the directive working.",
            "observed", ni.evidence[:1] + not_idx.evidence[:1])
    elif ni and not_rank:
        add(ni, not_rank.id, "rank", "The page carries a noindex directive and is absent from the results.", "observed", ni.evidence[:1] + not_rank.evidence[:1])

    # 9. canonical to another URL <-> target missing from index
    cm = by.get("SEM_CANONICAL_MISMATCH")
    if cm and (not_idx or not_rank):
        sy = not_idx or not_rank
        add(cm, sy.id, "indexation" if not_idx else "rank", "The canonical tag points elsewhere, and this URL does not surface; engines usually index the canonical instead.",
            "inferred", cm.evidence[:1] + sy.evidence[:1])

    # 10. blocked fetch / bot challenge <-> not indexed or ranked
    for fid in ("ACCESS_FETCH_BOT_BLOCKED", "ACCESS_FETCH_LOGIN_REQUIRED", "ACCESS_FETCH_EMPTY_CONTENT", "ACCESS_RAW_HTTP_STATUS"):
        f = by.get(fid)
        if f and visibility_gap:
            sy = visibility_gap[0]
            add(f, sy.id, "indexation" if sy is not_idx else "rank",
                "Automated fetchers cannot read this page, and it is missing/low in search. Search crawlers may meet the same barrier.", "inferred",
                f.evidence[:1] + sy.evidence[:1])

    # 11. blocked Googlebot/Bingbot <-> not indexed / ranked
    for f in _first(findings, "ACCESS_BOT_BLOCKED_GOOGLEBOT", "ACCESS_BOT_BLOCKED_BINGBOT"):
        sy = not_idx or not_rank
        if sy:
            add(f, sy.id, "indexation" if not_idx else "rank", "robots.txt blocks a major search crawler and the page is missing from results.",
                "inferred", f.evidence[:1] + sy.evidence[:1])
    return bridges


def _quote(evs: list[Evidence], prefix: str) -> str:
    for e in evs:
        if e.value.startswith(prefix):
            return e.value.split(":", 1)[1].strip()
    return ""
