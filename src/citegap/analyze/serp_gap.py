"""6.4 SERP gap: rank, indexation, title/snippet divergence, competitor delta (needs Search)."""
from __future__ import annotations

import re
import statistics

from rapidfuzz import fuzz

from ..collect.serp import core_title
from ..fixes import snippets as sn
from ..report.model import Finding, Fix, PageFeatures
from ..util import clip, host_of, same_site
from .context import AuditData, ev
from .extractability import boilerplate_ratio
from .semantics import core_part

BOILER_SNIP = re.compile(r"(cookie|privacy|sign in|log in|subscribe|menu|skip to|all rights reserved|©|accept all)", re.I)
RICH = re.compile(r"(\b(19|20)\d{2}\b|\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|★|\brating\b|\breviews?\b|\$\s?\d|€\s?\d|£\s?\d)", re.I)


def analyze_serp(d: AuditData) -> tuple[list[Finding], list[dict], dict]:
    s = d.serp
    out: list[Finding] = []
    extras: dict = {}
    tf = d.target_features
    q = d.query
    t_probe = s.probe("target_query")
    top3 = [f"#{r.position} {r.url}" for r in s.organic[:3]]
    pid = t_probe.call_id if t_probe else None
    if s.error and not s.organic:
        d.notes.append(f"Search for the target query failed ({s.error}); rank findings skipped.")
    elif t_probe and not t_probe.error:
        if s.rank is None:
            out.append(Finding(
                id="SERP_NOT_RANKED", category="serp", severity="high",
                title=f"Not in the top {s.pages_checked * 10} results for “{q}”",
                evidence=[ev("rank", f"query “{q}”: target absent from {s.pages_checked} page(s) of results", pid), ev("url", "top results: " + "; ".join(top3), pid)],
                ai_impact="AI tools that retrieve through search will not surface this page for the query.", search_impact="Absent from the first results page(s) for this query.",
                fix=Fix(steps=["Close the readability and answerability gaps in this report, then re-audit.", f"Make the page answer “{q}” in its title, H1 and opening paragraph."],
                        effort_minutes=120, where_to_paste="Page content"), confidence="observed"))
        elif s.rank > 10:
            out.append(Finding(
                id="SERP_RANK_LOW", category="serp", severity="medium", title=f"Ranks #{s.rank} for “{q}” (second page)",
                evidence=[ev("rank", f"position {s.rank} for “{q}”", pid), ev("url", s.rank_result.url if s.rank_result else "")],
                ai_impact="Retrieval pipelines usually read only the first results.", search_impact="Few users reach the second page.",
                fix=Fix(steps=["Close the competitor gaps listed below and re-audit."], effort_minutes=120, where_to_paste="Page content"), confidence="observed"))
    ind = s.probe("indexation")
    if ind and not ind.error and s.indexation in ("partial", "none") and s.title_probe_found is not True and s.rank is None:
        ev_list = [ev("rank", f"include_domains={host_of(d.url)}, query “{q}”: {len(s.domain_hits)} domain page(s), target not among them", ind.call_id)]
        if s.domain_hits:
            ev_list.append(ev("url", "other pages surfaced: " + "; ".join(r.url for r in s.domain_hits[:3]), ind.call_id))
        out.append(Finding(
            id="SERP_NOT_INDEXED", category="serp", severity="high",
            title="Page does not surface even when search is limited to its own domain" if s.indexation == "partial" else "Nothing from this domain surfaced in search",
            evidence=ev_list, ai_impact="If the search index lacks the page, search-backed AI tools cannot find it.",
            search_impact="Likely not indexed (search results are not an authoritative index check; confirm in Search Console / Bing Webmaster Tools).",
            fix=Fix(steps=["Confirm in Google Search Console (URL Inspection) and Bing Webmaster Tools whether the URL is indexed.",
                           "Submit the URL, link to it from indexed pages and list it in sitemap.xml."],
                    snippet=f"Sitemap: {d.site.origin if d.site else 'https://' + host_of(d.url)}/sitemap.xml", snippet_lang="text", effort_minutes=20,
                    where_to_paste="robots.txt / sitemap / internal links"), confidence="inferred"))
    entry = s.target_entry
    page_title = d.raw_doc.title if d.raw_doc and d.raw_doc.title else d.page_title
    if entry and page_title and entry.title:
        ratio = fuzz.ratio(core_part(page_title).lower(), core_title(entry.title).lower())
        extras["title_match"] = ratio
        if ratio < d.settings.title_rewrite_ratio:
            out.append(Finding(
                id="SERP_TITLE_REWRITTEN", category="serp", severity="medium", title="Search engine shows a different title than your <title>",
                evidence=[ev("quote", f"page <title>: {page_title}", d.md_call), ev("quote", f"SERP title: {entry.title}", pid or (ind.call_id if ind else None)),
                          ev("metric", f"similarity={ratio:.0f}/100 (threshold {d.settings.title_rewrite_ratio:.0f})")],
                ai_impact="Citations use the engine's title; yours was not trusted as the page label.", search_impact="Rewritten titles often signal a title that doesn't match the content or query.",
                fix=Fix(steps=["Rewrite the <title> to state the page's main topic, matching the H1 and the query."],
                        snippet=sn.head_title_meta(sn.title_suggestion(d.h1, page_title, host_of(d.url)), ""), snippet_lang="html", effort_minutes=5, where_to_paste="<head>"),
                confidence="observed"))
    if entry and entry.snippet:
        snip = re.sub(r"\.{3}|…", " ", entry.snippet).strip()
        junk_sample = ""
        if d.target.main and d.target.main.text and d.md:
            _, junk_sample = boilerplate_ratio(d.md, d.target.main.text)
        hit_junk = (junk_sample and len(snip) > 30 and fuzz.partial_ratio(snip.lower(), junk_sample.lower()) >= 90) or bool(BOILER_SNIP.search(snip))
        if hit_junk:
            out.append(Finding(
                id="SERP_SNIPPET_BOILERPLATE", category="serp", severity="medium", title="Search snippet is taken from navigation/boilerplate text",
                evidence=[ev("snippet", entry.snippet, pid), ev("quote", f"meta description: {d.meta_description or '(none)'}")],
                ai_impact="Answer engines that reuse the snippet quote menu text, not your content.", search_impact="A boilerplate snippet lowers click-through.",
                fix=Fix(steps=["Write a meta description that summarises the page, and keep nav/cookie text outside <main>."],
                        snippet=f'<meta name="description" content="{sn.meta_description_suggestion((d.doc.first_paragraphs[0] if d.doc and d.doc.first_paragraphs else ""))}">',
                        snippet_lang="html", effort_minutes=10, where_to_paste="<head>"), confidence="observed"))
    if s.question and s.question_probe_domain_found is False:
        qp = s.probe("question")
        out.append(Finding(
            id="SERP_QUESTION_ABSENT", category="serp", severity="low", title="Domain does not appear for the natural-language question",
            evidence=[ev("rank", f"“{s.question}”: no result from {host_of(d.url)} in the first page", qp.call_id if qp else None),
                      ev("url", "top: " + "; ".join(f"#{r.position} {r.url}" for r in (qp.results[:3] if qp else [])))],
            ai_impact="Conversational AI queries resemble this phrasing.", search_impact="The page is not matched to the question form of the topic.",
            fix=Fix(steps=[f"Add a subheading phrased as “{s.question}” with a direct answer beneath it."], snippet=sn.answer_block(s.question, tf.best_passage),
                    snippet_lang="html", effort_minutes=20, where_to_paste="Page body"), confidence="inferred"))

    comps = d.competitor_features
    rows, worse = build_delta(tf, comps)
    if comps:
        med_words = statistics.median([c.word_count for c in comps])
        if tf.word_count and med_words >= 2 * tf.word_count and med_words > 0 and s.rank != 1:
            out.append(Finding(
                id="SERP_THIN_VS_COMPETITORS", category="serp", severity="medium",
                title=f"Competitors have ~{med_words/max(1,tf.word_count):.1f}× the content depth",
                evidence=[ev("metric", f"target words={tf.word_count}; competitors: " + ", ".join(f"#{c.serp_position} {c.word_count}" for c in comps)),
                          ev("url", "; ".join(c.url for c in comps))],
                ai_impact="Shallower pages give answer engines less to draw on.", search_impact="Top results for this query are substantially longer.",
                fix=Fix(steps=["Cover subtopics competitors cover: use their H2s as a checklist.", "Add examples, data and steps rather than padding."],
                        effort_minutes=180, where_to_paste="Page body"), confidence="observed"))
        structural = [r for r in rows if r["feature"] in ("H2 headings", "Lists", "Tables", "FAQ") and r["status"] == "worse"]
        if len(structural) >= 2:
            out.append(Finding(
                id="SERP_STRUCTURE_GAP", category="serp", severity="low", title=f"Less structured than competitors ({', '.join(r['feature'] for r in structural)})",
                evidence=[ev("metric", f"{r['feature']}: target {r['target']} vs competitors {r['competitors']}") for r in structural],
                ai_impact="Structured content is easier to chunk and quote.", search_impact="Competitors use headings/lists/tables to answer more of the query.",
                fix=Fix(steps=["Break the page into question-style H2 sections; convert enumerations to lists and comparisons to tables."],
                        effort_minutes=60, where_to_paste="Page body"), confidence="observed"))
        rich_c = [c for c in comps if c.serp_snippet and RICH.search(c.serp_snippet)]
        tgt_snip = entry.snippet if entry else ""
        if rich_c and not RICH.search(tgt_snip or "") and not tf.schema_types:
            out.append(Finding(
                id="SERP_COMPETITOR_RICHER_SNIPPETS", category="serp", severity="medium", title="Competitors' snippets show dates/ratings/prices; yours shows none",
                evidence=[ev("snippet", f"#{c.serp_position} {c.url}: {clip(c.serp_snippet or '', 160)}", pid) for c in rich_c[:2]]
                         + [ev("snippet", f"target: {clip(tgt_snip, 160) or '(target not in results)'}", pid)],
                ai_impact="Machine-readable facts (date, rating, price) make a source easier to trust and quote.",
                search_impact="Pages without structured data cannot earn those enhancements.",
                fix=Fix(steps=["Add JSON-LD with datePublished/dateModified (articles) or offers/aggregateRating (products)."], effort_minutes=20, where_to_paste="<head>"),
                confidence="inferred"))
    top10 = [r for r in (t_probe.results if t_probe else []) if r.position <= 10]
    extras["domain_share"] = {"in_top10": sum(1 for r in top10 if same_site(r.url, d.url)), "of": len(top10)}
    return out, rows, extras


def _num(v) -> float:
    return float(v or 0)


def build_delta(t: PageFeatures, comps: list[PageFeatures]) -> tuple[list[dict], int]:
    rows: list[dict] = []
    n_worse = 0
    if not comps:  # nothing to compare against: no rows, so parity is "n/a" rather than full marks
        return rows, 0

    def numeric(label: str, attr: str, min_median: float = 1):
        nonlocal n_worse
        vals = [_num(getattr(c, attr)) for c in comps]
        tv = _num(getattr(t, attr))
        med = statistics.median(vals) if vals else 0
        status = "worse" if comps and med >= min_median and (tv < 0.5 * med or (tv == 0 and med >= min_median)) else "ok"
        if status == "worse":
            n_worse += 1
        rows.append({"feature": label, "target": getattr(t, attr), "competitors": [getattr(c, attr) for c in comps], "status": status})

    def boolean(label: str, tv: bool, cvals: list, known: bool = True):
        nonlocal n_worse
        if not known:
            rows.append({"feature": label, "target": tv, "competitors": cvals, "status": "n/a"})
            return
        status = "worse" if comps and not tv and sum(1 for v in cvals if v) * 2 > len(cvals) else "ok"
        if status == "worse":
            n_worse += 1
        rows.append({"feature": label, "target": tv, "competitors": cvals, "status": status})

    numeric("Word count", "word_count", 100)
    numeric("H2 headings", "h2_count", 2)
    numeric("Lists", "list_count", 1)
    numeric("Tables", "table_count", 1)
    boolean("FAQ", t.has_faq, [c.has_faq for c in comps])
    known = bool(comps) and all(c.schema_known for c in comps) and t.schema_known
    boolean("Structured data (JSON-LD)", bool(t.schema_types), [bool(c.schema_types) for c in comps], known)
    boolean("Visible date", bool(t.date), [bool(c.date) for c in comps])
    boolean("Author", t.has_author, [c.has_author for c in comps])
    boolean("Answer-first", t.answer_first, [c.answer_first for c in comps])
    cov_c = [c.query_coverage_first150 for c in comps]
    cm = statistics.median(cov_c) if cov_c else 0
    st = "worse" if comps and t.query_coverage_first150 + 0.25 < cm else "ok"
    n_worse += st == "worse"
    rows.append({"feature": "Query coverage (first 150 words)", "target": t.query_coverage_first150, "competitors": cov_c, "status": st})
    return rows, n_worse
