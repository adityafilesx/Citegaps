"""ARS (AI Readability) and SVS (Search Visibility). Components always visible; no black box."""
from __future__ import annotations

from ..report.model import Finding, Score, ScoreComponent
from .context import AuditData

PENALTY = {"critical": 12, "high": 7, "medium": 3, "low": 1}
ARS_CATS = ["access", "extractability", "semantics", "answerability"]


def rank_points(rank: int | None) -> float:
    if rank is None:
        return 0.0
    if rank == 1:
        return 35.0
    if rank <= 3:
        return 30.0
    if rank <= 10:
        return 26.0 - (rank - 4) * 2.0  # 26 at #4 -> 14 at #10
    if rank <= 20:
        return 8.0
    return 0.0


def score_ars(findings: list[Finding], could_not_read: bool) -> Score:
    comps = []
    for cat in ARS_CATS:
        pts = 25.0 - sum(PENALTY[f.severity] for f in findings if f.category == cat)
        pts = max(0.0, pts)
        note = ""
        if could_not_read and cat != "access":
            pts, note = 0.0, "could not read: Fetch returned no content"
        comps.append(ScoreComponent(name=cat, points=pts, max_points=25.0, note=note))
    note = "Fetch could not read the page, so extractability, semantics and answerability are 0." if could_not_read else ""
    return Score(total=round(sum(c.points for c in comps), 1), components=comps, note=note)


def score_svs(d: AuditData, findings: list[Finding], parity_ok: int, parity_total: int, title_match: float | None) -> Score:
    s = d.serp
    comps: list[ScoreComponent] = []
    notes: list[str] = []
    search_ok = any(p.kind == "target_query" and not p.error for p in s.probes)
    ind_probe = s.probe("indexation")
    # indexation
    if ind_probe and not ind_probe.error:
        pts = {"indexed": 25.0, "partial": 8.0, "none": 0.0}.get(s.indexation, 0.0)
        comps.append(ScoreComponent(name="indexation", points=pts, max_points=25.0, note=s.indexation))
    else:
        comps.append(ScoreComponent(name="indexation", points=0.0, max_points=0.0, note="n/a: indexation probe failed"))
        notes.append("indexation not measured")
    # rank
    if search_ok:
        comps.append(ScoreComponent(name="rank", points=rank_points(s.rank), max_points=35.0,
                                    note=f"position {s.rank}" if s.rank else f"not in top {s.pages_checked * 10}"))
    else:
        comps.append(ScoreComponent(name="rank", points=0.0, max_points=0.0, note="n/a: search failed"))
        notes.append("rank not measured")
    # presentation
    entry = s.target_entry
    if entry:
        tm = title_match if title_match is not None else 50.0
        tpts = 10.0 if tm >= 80 else 7.0 if tm >= 60 else 4.0 if tm >= 40 else 1.0
        bad = any(f.id == "SERP_SNIPPET_BOILERPLATE" for f in findings)
        spts = 3.0 if bad else (10.0 if len(entry.snippet) >= 60 else 5.0)
        comps.append(ScoreComponent(name="serp_presentation", points=tpts + spts, max_points=20.0,
                                    note=f"title match {tm:.0f}, snippet {'boilerplate' if bad else 'ok' if spts == 10 else 'short'}"))
    elif search_ok:
        comps.append(ScoreComponent(name="serp_presentation", points=0.0, max_points=20.0, note="target not shown in results"))
    else:
        comps.append(ScoreComponent(name="serp_presentation", points=0.0, max_points=0.0, note="n/a"))
    # parity
    if parity_total > 0:
        comps.append(ScoreComponent(name="competitive_parity", points=round(20.0 * parity_ok / parity_total, 1), max_points=20.0,
                                    note=f"{parity_ok}/{parity_total} features at or above competitors"))
    else:
        comps.append(ScoreComponent(name="competitive_parity", points=0.0, max_points=0.0, note="n/a: no competitors fetched"))
        notes.append("no competitors to compare")
    avail = sum(c.max_points for c in comps)
    earned = sum(c.points for c in comps)
    total = round(100.0 * earned / avail, 1) if avail else 0.0
    note = ""
    if avail < 100:
        note = "Rescaled to 100 over measurable components (" + "; ".join(notes) + ")."
    if d.query_derived:
        note = (note + " " if note else "") + f"Based on derived query: “{d.query}”. Re-run with your own target query."
    return Score(total=total, components=comps, note=note)
