"""Bridge rules: a bridge needs BOTH sides present; blocked training bots never bridge to rank."""
from types import SimpleNamespace

from citegap.analyze.bridge import AI_VIS, build_bridges
from citegap.analyze.context import AuditData
from citegap.analyze.scoring import score_svs
from citegap.collect.serp import SerpData
from citegap.report.model import Evidence, Finding, Fix, PageFeatures, SerpProbe, SerpResult
from fakes import settings


def F(id, cat="serp", sev="medium", title="t"):
    return Finding(id=id, category=cat, severity=sev, title=title, evidence=[Evidence(kind="quote", value=f"ev-{id}")],
                   ai_impact="a", search_impact="s", fix=Fix(steps=["Do the concrete thing described here"]))


def data(serp=None):
    d = SimpleNamespace(serp=serp or SerpData(target_urls=["https://x.example/p"], indexation="partial", domain_hits=[SerpResult(position=1, url="https://x.example/o")]),
                        query="my query", settings=settings())
    return d


def pairs(bs):
    return {(b.cause_id, b.symptom_id) for b in bs}


def test_no_bridge_when_symptom_missing():
    assert build_bridges(data(), [F("EXTRACT_JS_DEPENDENT", "extractability")]) == []


def test_no_bridge_when_cause_missing():
    assert build_bridges(data(), [F("SERP_NOT_INDEXED")]) == []


def test_js_to_not_indexed_requires_partial_indexation():
    fs = [F("EXTRACT_JS_DEPENDENT", "extractability"), F("SERP_NOT_INDEXED")]
    assert pairs(build_bridges(data(), fs)) == {("EXTRACT_JS_DEPENDENT", "SERP_NOT_INDEXED")}
    none = SerpData(target_urls=["https://x.example/p"], indexation="none")
    assert build_bridges(data(none), [F("EXTRACT_JS_DEPENDENT", "extractability"), F("SERP_NOT_INDEXED")]) == []


def test_bridge_to_links_both_ends():
    fs = [F("EXTRACT_JS_DEPENDENT", "extractability"), F("SERP_NOT_INDEXED")]
    build_bridges(data(), fs)
    assert fs[0].bridge_to == ["SERP_NOT_INDEXED"] and fs[1].bridge_to == ["EXTRACT_JS_DEPENDENT"]


def test_bot_blocks_bridge_only_for_high_severity_ai_visibility():
    search_bot = F("ACCESS_BOT_BLOCKED_PERPLEXITYBOT", "access", "high", "robots.txt blocks PerplexityBot (Perplexity, search bot) from this page")
    training = F("ACCESS_BOT_BLOCKED_GPTBOT", "access", "medium", "robots.txt blocks GPTBot (OpenAI, training bot) from this page")
    bs = build_bridges(data(), [search_bot, training])
    assert pairs(bs) == {("ACCESS_BOT_BLOCKED_PERPLEXITYBOT", AI_VIS)}
    assert bs[0].confidence == "observed" and "not a Google ranking signal" in bs[0].statement


def test_title_rewrite_bridge_observed():
    rw = F("SERP_TITLE_REWRITTEN")
    rw.evidence = [Evidence(kind="quote", value="page <title>: a"), Evidence(kind="quote", value="SERP title: Better one")]
    bs = build_bridges(data(), [F("SEM_TITLE_LONG", "semantics", "low"), rw])
    assert bs[0].confidence == "observed" and "Better one" in bs[0].statement


def test_noindex_bridges_to_not_indexed():
    assert ("ACCESS_NOINDEX", "SERP_NOT_INDEXED") in pairs(build_bridges(data(), [F("ACCESS_NOINDEX", "access", "critical"), F("SERP_NOT_INDEXED")]))


# ---- SVS ----
def svs_data(rank=None, indexation="indexed", entry=None, search_ok=True, ind_ok=True, derived=False):
    s = SerpData(query="q", rank=rank, indexation=indexation, target_entry=entry, pages_checked=2)
    s.probes = []
    if search_ok:
        s.probes.append(SerpProbe(kind="target_query", query="q"))
    s.probes.append(SerpProbe(kind="indexation", query="q", error=None if ind_ok else "x"))
    return SimpleNamespace(serp=s, query="q", query_derived=derived)


def test_svs_full_marks():
    e = SerpResult(position=1, title="t", snippet="s" * 80)
    sc = score_svs(svs_data(1, "indexed", e), [], 5, 5, 100.0)
    assert sc.total == 100 and not sc.note


def test_svs_absent_zero_for_rank_and_rescales_when_unmeasurable():
    sc = score_svs(svs_data(None, "none"), [], 0, 0, None)
    pts = {c.name: c.points for c in sc.components}
    assert pts["rank"] == 0 and pts["indexation"] == 0 and sc.total == 0
    assert "Rescaled" in sc.note  # no competitors -> parity excluded


def test_svs_search_failed_excluded_not_zeroed():
    sc = score_svs(svs_data(None, "indexed", None, search_ok=False), [], 4, 5, None)
    assert sc.total > 0 and any(c.max_points == 0 and "n/a" in c.note for c in sc.components)


def test_svs_derived_query_label():
    assert "derived query" in score_svs(svs_data(3, "indexed", SerpResult(position=3, snippet="x" * 70), derived=True), [], 1, 1, 90).note
