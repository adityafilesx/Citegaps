"""Markdown report renderer."""
from __future__ import annotations

from .model import Finding, Report

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEV_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}


def sorted_fixes(findings: list[Finding]) -> list[Finding]:
    """Impact desc (severity, bridged first), effort asc."""
    return sorted(findings, key=lambda f: (SEV_ORDER[f.severity], -len(f.bridge_to), f.fix.effort_minutes))


def verdict(r: Report) -> str:
    if r.could_not_read:
        return ("Fetch could not read this page, so AI tools likely cannot either. "
                f"Search side: {_rank_phrase(r)}.")
    return f"AI Readability {r.ars.total:.0f}/100 · Search Visibility {r.svs.total:.0f}/100. {_rank_phrase(r).capitalize()}."


def _rank_phrase(r: Report) -> str:
    sp = (r.serp_card or {})
    if sp.get("position"):
        return f"ranks #{sp['position']} for “{r.query}”"
    if any(p.kind == "target_query" and not p.error for p in r.serp):
        return f"not in the top results for “{r.query}”"
    return "search results unavailable"


def render_markdown(r: Report) -> str:
    L: list[str] = []
    L.append(f"# CiteGap report: {r.url}\n")
    L.append(f"_{r.created_at} · {r.duration_s:.0f}s · query: **{r.query}**{' (derived)' if r.query_derived else ''} · "
             f"answerability method: `{r.answerability_method}`_\n")
    L.append(f"> {verdict(r)}\n")
    L.append("## Scores\n")
    L.append("| | Score | Breakdown |\n|---|---|---|")
    for name, sc in (("AI Readability (ARS)", r.ars), ("Search Visibility (SVS)", r.svs)):
        parts = ", ".join(f"{c.name} {c.points:.0f}/{c.max_points:.0f}" for c in sc.components if c.max_points)
        L.append(f"| {name} | **{sc.total:.0f}/100** | {parts} |")
    for sc in (r.ars, r.svs):
        if sc.note:
            L.append(f"\n_{sc.note}_")
    if r.previous:
        p = r.previous
        L.append(f"\n**Re-audit delta** vs {p['created_at']}: ARS {p['ars_delta']:+.1f}, SVS {p['svs_delta']:+.1f}"
                 f"{'; rank ' + str(p['rank_prev']) + ' → ' + str(p['rank_now']) if p.get('rank_prev') != p.get('rank_now') else ''}. "
                 f"Fixed: {', '.join(p['fixed']) or 'none'}. New: {', '.join(p['new']) or 'none'}.")
    L.append("\n## Gap Matrix (readability cause → visibility symptom)\n")
    if r.bridges:
        L.append("| Cause (AI-readability) | Symptom (search/AI visibility) | Link | Confidence |\n|---|---|---|---|")
        for b in r.bridges:
            L.append(f"| `{b.cause_id}` | `{b.symptom_id}` ({b.symptom_kind}) | {b.statement} | {b.confidence} |")
    else:
        L.append("_No evidence-backed bridge in this audit (a bridge needs both the cause and the symptom to be observed)._")
    L.append("\n## Fix list (impact ↓, effort ↑)\n")
    for i, f in enumerate(sorted_fixes(r.findings), 1):
        L.append(f"### {i}. {SEV_ICON[f.severity]} {f.title}  \n`{f.id}` · {f.category} · {f.severity} · {f.confidence} · ~{f.fix.effort_minutes} min\n")
        for e in f.evidence:
            L.append(f"- **evidence ({e.kind})**: {e.value}")
        L.append(f"- **AI impact**: {f.ai_impact}\n- **Search impact**: {f.search_impact}")
        L.append("- **Fix**:")
        for s in f.fix.steps:
            L.append(f"  1. {s}")
        if f.fix.where_to_paste:
            L.append(f"  - paste into: {f.fix.where_to_paste}")
        if f.fix.snippet:
            L.append(f"\n```{f.fix.snippet_lang or ''}\n{f.fix.snippet}\n```")
        L.append("")
    if r.delta_table:
        L.append("## Competitor delta\n")
        L.append("| Feature | Target | " + " | ".join(f"#{c.serp_position or '?'}" for c in r.competitors) + " | Status |")
        L.append("|---|---|" + "---|" * len(r.competitors) + "---|")
        for row in r.delta_table:
            L.append(f"| {row['feature']} | {row['target']} | " + " | ".join(str(v) for v in row["competitors"]) + f" | {row['status']} |")
        L.append("")
        for c in r.competitors:
            L.append(f"- #{c.serp_position}: {c.url}")
    if r.serp_card:
        c = r.serp_card
        L.append("\n## How you appear in search\n")
        L.append(f"- **SERP title**: {c.get('serp_title') or '(target not shown)'}\n- **Your <title>**: {c.get('page_title')}")
        L.append(f"- **SERP snippet**: {c.get('serp_snippet') or '(none)'}\n- **Your meta description**: {c.get('meta_description') or '(none)'}")
    L.append("\n## TinyFish call log (all Fetch calls use `ttl: 0`)\n")
    L.append("| # | Endpoint | Call | ttl | Latency | Status |\n|---|---|---|---|---|---|")
    for i, c in enumerate(r.calls, 1):
        L.append(f"| {i} | {c.endpoint} | {c.summary} | {c.ttl if c.ttl is not None else '-'} | {c.latency_ms} ms | {c.status} |")
    if r.notes:
        L.append("\n## Notes\n" + "\n".join(f"- {n}" for n in r.notes))
    if r.lint_dropped:
        L.append("\n## Dropped by evidence lint\n" + "\n".join(f"- `{x['id']}`: {x['reason']}" for x in r.lint_dropped))
    return "\n".join(L) + "\n"
