"""6.2 Extractability: can AI read it once reached?"""
from __future__ import annotations

from ..collect.htmlparse import Doc
from ..fixes import snippets as sn
from ..report.model import Finding, Fix
from ..util import clip, word_count
from .context import AuditData, ev
from .features import clean_md

IGNORE_IFRAME = ("googletagmanager", "doubleclick", "facebook.com/tr", "google.com/recaptcha", "about:blank")


def js_gap(rendered_words: int, raw_words: int, ratio: float) -> bool:
    return rendered_words >= 100 and raw_words < ratio * rendered_words


def boilerplate_ratio(full_md: str, main_md: str) -> tuple[float, str]:
    """Share of the extracted text that is outside main/article, plus a junk sample."""
    main_lines = {l.strip() for l in main_md.splitlines() if l.strip()}
    junk, total = [], 0
    for l in full_md.splitlines():
        s = l.strip()
        if not s:
            continue
        total += len(s)
        if s not in main_lines:
            junk.append(s)
    jt = sum(len(s) for s in junk)
    return (jt / total if total else 0.0), clip(" ".join(junk), 200)


def analyze_extractability(d: AuditData) -> list[Finding]:
    out: list[Finding] = []
    if d.target.fully_failed:
        return out
    s, t = d.settings, d.target
    rendered_words = word_count(clean_md(d.md))
    raw = t.raw.doc if t.raw and t.raw.doc else None
    if raw is not None and js_gap(rendered_words, raw.word_count, s.js_gap_ratio):
        pct = int(100 * raw.word_count / max(1, rendered_words))
        out.append(Finding(
            id="EXTRACT_JS_DEPENDENT", category="extractability", severity="high",
            title=f"Most content only exists after JavaScript runs ({pct}% in raw HTML)",
            evidence=[ev("metric", f"rendered words={rendered_words} (Fetch) vs raw HTML words={raw.word_count} (plain GET)", d.md_call),
                      ev("url", t.raw.final_url if t.raw else d.url)],
            ai_impact="Many AI crawlers do not execute JavaScript; they see only the raw HTML (heuristic: not every crawler behaves this way).",
            search_impact="Crawlers that skip rendering index a near-empty page.",
            fix=Fix(steps=["Server-side render or pre-render this route so the main content is in the initial HTML response.",
                           "Verify with `curl -s <url> | wc -w` that the word count matches the rendered page."],
                    snippet=f"curl -s '{d.url}' | sed -e 's/<[^>]*>//g' | wc -w   # expect close to ~{rendered_words}",
                    snippet_lang="bash", effort_minutes=240, where_to_paste="Rendering strategy (SSR/SSG)"),
            confidence="observed"))
    if t.main_error is not None and t.main_error.error == "selector_not_matched":
        cands = ", ".join(str(c) for c in t.main_error.candidate_selectors[:6]) or "none suggested"
        out.append(Finding(
            id="EXTRACT_NO_MAIN_LANDMARK", category="extractability", severity="medium",
            title="No <main> or <article> landmark", evidence=[ev("selector", f"include_selectors=['main','article'] → selector_not_matched; candidates: {cands}", t.main_error.call_id)],
            ai_impact="An extractor has to guess where the content is, which pulls in navigation and footers.",
            search_impact="Search engines also use landmarks to separate main content from boilerplate.",
            fix=Fix(steps=["Wrap the primary content in <main> (and <article> for self-contained posts)."], snippet=sn.main_landmark(),
                    snippet_lang="html", effort_minutes=20, where_to_paste="Page template"), confidence="observed"))
    elif t.main and t.main.text:
        ratio, sample = boilerplate_ratio(d.md, t.main.text)
        if ratio > s.boilerplate_ratio and sample:
            out.append(Finding(
                id="EXTRACT_BOILERPLATE_HEAVY", category="extractability", severity="medium",
                title=f"{int(ratio*100)}% of extracted text is outside <main>/<article>",
                evidence=[ev("quote", sample, d.md_call), ev("metric", f"outside-main share={ratio:.2f}, threshold={s.boilerplate_ratio}")],
                ai_impact="Navigation, cookie and footer text dominates what a general extractor returns.",
                search_impact="Snippets and summaries can be pulled from boilerplate instead of the article.",
                fix=Fix(steps=["Move navigation/footer/cookie markup into <nav>, <footer>, <aside> and keep the page body in <main>.",
                               "Load cookie banners after the main content in the DOM."], snippet=sn.main_landmark(), snippet_lang="html",
                        effort_minutes=45, where_to_paste="Page template"), confidence="observed"))
    ifr = [u for u in (t.md.iframe_links if t.md else []) if isinstance(u, str) and not any(x in u for x in IGNORE_IFRAME)]
    ifr_urls = ifr or [u for u in (t.rendered_doc.iframes if t.rendered_doc else []) if not any(x in u for x in IGNORE_IFRAME)]
    if ifr_urls:
        out.append(Finding(
            id="EXTRACT_IFRAME_CONTENT", category="extractability", severity="medium",
            title=f"{len(ifr_urls)} embedded iframe(s) hold content AI tools do not read inline",
            evidence=[ev("selector", f"iframe src={u}", d.md_call) for u in ifr_urls[:4]],
            ai_impact="Text inside an iframe is a separate document; the page's own extraction does not include it.",
            search_impact="Content in frames is attributed to the frame URL, not this page.",
            fix=Fix(steps=["Render the important content directly in the page, or add a text equivalent next to the embed."],
                    effort_minutes=60, where_to_paste="Page template"), confidence="observed"))
    doc = d.doc
    if doc is not None:
        hidden = doc.details_count + doc.tabpanel_count
        if hidden >= 3:
            out.append(Finding(
                id="EXTRACT_HIDDEN_CONTENT", category="extractability", severity="low",
                title=f"{hidden} collapsible/tabbed sections",
                evidence=[ev("selector", f"<details>={doc.details_count}, tab/accordion elements={doc.tabpanel_count}", t.html.call_id if t.html else None)],
                ai_impact="Content revealed only by interaction may be dropped or deprioritised by extractors.",
                search_impact="Hidden-by-default content can be weighted lower.",
                fix=Fix(steps=["Keep the answer-critical text visible by default; reserve accordions for secondary detail."],
                        effort_minutes=30, where_to_paste="Page template"), confidence="inferred"))
        imgs = doc.images
        missing = [i for i in imgs if i["alt"] is None]
        if len(imgs) >= 3 and len(missing) / len(imgs) >= 0.3:
            out.append(Finding(
                id="EXTRACT_IMG_ALT_MISSING", category="extractability", severity="medium",
                title=f"{len(missing)} of {len(imgs)} images have no alt attribute",
                evidence=[ev("selector", f"<img src='{i['src']}'> (no alt)", t.html.call_id if t.html else None) for i in missing[:5]],
                ai_impact="Text-only extractors lose whatever the images communicate.", search_impact="Missing alt text reduces image-search eligibility and accessibility.",
                fix=Fix(steps=["Add short, descriptive alt text to each content image; use alt=\"\" for decorative ones."],
                        snippet='<img src="..." alt="Describe what the image shows in one sentence">', snippet_lang="html",
                        effort_minutes=15, where_to_paste="Image markup"), confidence="observed"))
    if rendered_words < s.thin_words:
        out.append(Finding(
            id="EXTRACT_THIN_CONTENT", category="extractability", severity="high" if rendered_words < 100 else "medium",
            title=f"Thin content: {rendered_words} words extracted", evidence=[ev("metric", f"word_count={rendered_words} (threshold {s.thin_words})", d.md_call)],
            ai_impact="Little text for an AI tool to summarise or quote.", search_impact="Very short pages rarely satisfy informational queries.",
            fix=Fix(steps=[f"Expand the page to cover the target query ('{d.query}') in depth: definition, key facts, steps, examples."],
                    effort_minutes=90, where_to_paste="Page body"), confidence="observed"))
    ctype = (t.raw.content_type if t.raw else "").lower()
    if "pdf" in ctype or d.target.final_url.lower().split("?")[0].endswith(".pdf"):
        out.append(Finding(
            id="EXTRACT_PDF_CONTENT", category="extractability", severity="low", title="Target is a PDF, not an HTML page",
            evidence=[ev("http", f"content-type: {ctype or 'application/pdf (by extension)'}")],
            ai_impact="Text is extracted, but there are no headings, landmarks or structured data to anchor it.",
            search_impact="PDFs rarely earn rich results and are harder to quote precisely.",
            fix=Fix(steps=["Publish an HTML version of this content and link the PDF as a download."], effort_minutes=120), confidence="observed"))
    return out
