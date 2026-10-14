"""6.5 Answerability: does the page contain what the target query asks for, vs competitors?"""
from __future__ import annotations

import re
import statistics

from ..fixes import snippets as sn
from ..report.model import Finding, Fix
from ..util import clip
from .context import AuditData, ev
from .features import coverage, highlight_texts, md_headings, parse_date, query_stems


def analyze_answerability(d: AuditData) -> list[Finding]:
    out: list[Finding] = []
    if d.target.fully_failed:
        return out
    tf, comps = d.target_features, d.competitor_features
    qs = query_stems(d.query)
    if not qs:
        return out
    doc = d.doc
    title = d.page_title or ""
    h1 = d.h1 or ""
    h2s = [t for l, t in (doc.headings if doc else []) if l == 2]
    c_title, c_h1 = coverage(title, qs), coverage(h1, qs)
    c_h2 = max([coverage(t, qs) for t in h2s] or [0.0])
    if not d.query_derived and max(c_title, c_h1) < 0.5:
        out.append(Finding(
            id="ANS_QUERY_NOT_IN_HEADLINE", category="answerability", severity="medium",
            title=f"Target query terms are missing from the title and H1 ({int(max(c_title, c_h1)*100)}% covered)",
            evidence=[ev("quote", f"query: {d.query}"), ev("quote", f"title: {clip(title,100)}", d.md_call), ev("quote", f"h1: {clip(h1,100)}", d.md_call),
                      ev("metric", f"coverage title={c_title:.2f}, h1={c_h1:.2f}, best h2={c_h2:.2f}, first150={tf.query_coverage_first150:.2f}")],
            ai_impact="Retrieval systems match on headline vocabulary first.", search_impact="Pages whose headline lacks the query's terms rank below those that match.",
            fix=Fix(steps=[f"Work the query's key terms ({', '.join(d.query.split()[:5])}) into the title and H1 naturally."],
                    snippet=sn.head_title_meta(sn.title_suggestion(d.query.title(), None, d.target.final_url.split('/')[2]), ""), snippet_lang="html",
                    effort_minutes=10, where_to_paste="<head> and H1"), confidence="observed"))

    # best-passage comparison
    hl = d.highlights
    comp_with_passage = []
    if hl.method == "highlights":
        tgt_p = hl.passages.get(d.url) or hl.passages.get(d.target.final_url) or []
        for cf in comps:
            ps = hl.passages.get(cf.url) or []
            if ps:
                comp_with_passage.append((cf, ps[0]))
        if not tgt_p and comp_with_passage:
            cf, p = comp_with_passage[0]
            out.append(Finding(
                id="ANS_NO_PASSAGE", category="answerability", severity="high",
                title=f"No passage on the page answers “{d.query}” — {len(comp_with_passage)} competitor(s) have one",
                evidence=[ev("metric", "TinyFish highlights for the target returned an empty array", hl.call_id),
                          ev("quote", f"{cf.url}: “{clip(p, 220)}”", hl.call_id)],
                ai_impact="An answer engine asked this query finds nothing on your page to quote.",
                search_impact="Competitors with a direct answer passage are the natural results; this page has none.",
                fix=Fix(steps=[f"Add a section that answers “{d.query}” directly within the first two paragraphs.", "Lead with the answer, then support it."],
                        snippet=sn.answer_block(d.query[0].upper() + d.query[1:] + ("" if d.query.endswith("?") else "?"), clip(p, 200)),
                        snippet_lang="html", effort_minutes=30, where_to_paste="Top of the page body"), confidence="observed"))
    else:
        best = [cf for cf in comps if (cf.passage_coverage or 0) >= 0.75 and cf.best_passage]
        tcov = tf.passage_coverage or 0.0
        if best and tcov < 0.5 and (max(c.passage_coverage or 0 for c in best) - tcov) >= 0.25:
            cf = max(best, key=lambda c: c.passage_coverage or 0)
            out.append(Finding(
                id="ANS_NO_PASSAGE", category="answerability", severity="high",
                title=f"No passage covers the query terms ({int(tcov*100)}% best-passage coverage) — competitors reach {int((cf.passage_coverage or 0)*100)}%",
                evidence=[ev("quote", f"target best passage: “{clip(tf.best_passage or '(none)', 200)}”", d.md_call),
                          ev("quote", f"{cf.url}: “{clip(cf.best_passage or '', 200)}”"),
                          ev("metric", f"method=local BM25/term coverage; target coverage={tcov:.2f}, competitor={cf.passage_coverage}")],
                ai_impact="Passage-level retrieval will not find an answer chunk on this page.", search_impact="Competitors have chunks that match the query; this page does not.",
                fix=Fix(steps=[f"Add a passage that states the answer to “{d.query}” using the query's own terms."],
                        snippet=sn.answer_block(d.query[0].upper() + d.query[1:] + ("" if d.query.endswith("?") else "?"), clip(cf.best_passage or "", 200)),
                        snippet_lang="html", effort_minutes=30, where_to_paste="Top of the page body"), confidence="inferred"))
        elif tcov < 0.34 and tf.word_count > 0:
            out.append(Finding(
                id="ANS_WEAK_PASSAGE", category="answerability", severity="medium",
                title=f"Best passage covers only {int(tcov*100)}% of the query terms",
                evidence=[ev("quote", f"best passage: “{clip(tf.best_passage or '(none)', 220)}”", d.md_call), ev("metric", f"query={d.query!r}, coverage={tcov:.2f}")],
                ai_impact="No chunk of the page matches what was asked.", search_impact="Weak topical match for this query.",
                fix=Fix(steps=[f"Add a section that addresses “{d.query}” explicitly."], snippet=sn.answer_block(d.query[0].upper() + d.query[1:] + "?", None),
                        snippet_lang="html", effort_minutes=30, where_to_paste="Page body"), confidence="inferred"))

    if not tf.answer_first and tf.word_count >= 150:
        others = [c for c in comps if c.answer_first]
        first = " ".join(d.md.split()[:80])
        out.append(Finding(
            id="ANS_NOT_ANSWER_FIRST", category="answerability", severity="medium" if others else "low",
            title="The answer is not stated in the opening paragraphs",
            evidence=[ev("quote", f"opening text: “{clip(first, 220)}”", d.md_call), ev("metric", f"competitors answering first: {len(others)}/{len(comps)}")],
            ai_impact="Summarisers lift the first direct statement; this page opens without one.", search_impact="Featured/AI answers favour pages that answer immediately.",
            fix=Fix(steps=["Open with one or two sentences that define or answer the query, then expand."],
                    snippet=sn.answer_block(d.query[0].upper() + d.query[1:] + "?", tf.best_passage), snippet_lang="html", effort_minutes=20,
                    where_to_paste="Directly under the H1"), confidence="inferred"))

    qa_heads = sum(1 for _, t in md_headings(d.md) if t.rstrip().endswith("?"))
    if tf.list_count == 0 and tf.table_count == 0 and qa_heads == 0 and comps:
        withs = [c for c in comps if c.list_count or c.table_count]
        if len(withs) * 2 >= len(comps) and tf.word_count >= 300:
            out.append(Finding(
                id="ANS_NO_LIFTABLE_STRUCTURE", category="answerability", severity="low",
                title="No lists, tables or Q&A headings for summarisers to lift",
                evidence=[ev("metric", f"target lists=0 tables=0 question-headings=0; competitors with lists/tables: {len(withs)}/{len(comps)}", d.md_call)],
                ai_impact="Structured blocks are the easiest units for AI summaries to quote.", search_impact="Competitors with lists/tables are eligible for richer results.",
                fix=Fix(steps=["Turn key steps into a numbered list and comparisons into a table; phrase subheadings as the questions users ask."],
                        snippet="<h2>How do I …?</h2>\n<ol>\n  <li>Step one</li>\n  <li>Step two</li>\n</ol>", snippet_lang="html", effort_minutes=25,
                        where_to_paste="Page body"), confidence="inferred"))

    t_date = parse_date(tf.date)
    comp_dates = [(parse_date(c.date), c) for c in comps if parse_date(c.date)]
    if not tf.date and comp_dates:
        out.append(Finding(
            id="ANS_NO_DATE", category="answerability", severity="low", title="No publish/updated date while competitors show one",
            evidence=[ev("metric", f"{len(comp_dates)}/{len(comps)} competitors expose a date; target exposes none"), ev("url", comp_dates[0][1].url)],
            ai_impact="Recency cannot be judged, so the page may be skipped for time-sensitive questions.", search_impact="No freshness signal.",
            fix=Fix(steps=["Show a visible 'Updated <date>' and add dateModified in JSON-LD."], snippet='<p>Updated <time datetime="YYYY-MM-DD">Month D, YYYY</time></p>',
                    snippet_lang="html", effort_minutes=10, where_to_paste="Page header"), confidence="observed"))
    elif t_date and comp_dates:
        fresh = max(comp_dates, key=lambda x: x[0])
        gap = (fresh[0] - t_date).days
        if gap > 365:
            out.append(Finding(
                id="ANS_STALE", category="answerability", severity="medium", title=f"Content is {gap//30} months older than the freshest competitor",
                evidence=[ev("metric", f"target date={tf.date}"), ev("metric", f"freshest competitor date={fresh[1].date} ({fresh[1].url})")],
                ai_impact="Answer engines prefer current sources for evolving topics.", search_impact="Older pages lose to freshly updated ones on fresh-sensitive queries.",
                fix=Fix(steps=["Review and update the facts, then publish a visible updated date."], effort_minutes=60, where_to_paste="Page body"), confidence="observed"))
    return out
