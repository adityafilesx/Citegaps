"""6.3 Semantics: titles, headings, canonical, language, structured data, links, authorship."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..collect.htmlparse import Doc, generic_links, iter_jsonld_nodes
from ..fixes import snippets as sn
from ..report.model import Finding, Fix
from ..util import clip, host_of, normalize_url
from .context import AuditData, ev
from .pagetype import EXPECTED, infer_page_type

REQUIRED = {
    "Article": ["headline", "datePublished", "author"], "BlogPosting": ["headline", "datePublished", "author"],
    "NewsArticle": ["headline", "datePublished", "author"], "TechArticle": ["headline", "datePublished", "author"],
    "Product": ["name", "offers"], "FAQPage": ["mainEntity"], "HowTo": ["name", "step"],
    "Organization": ["name", "url"], "Recipe": ["name", "recipeIngredient"],
}


def jsonld_missing(doc: Doc) -> list[tuple[str, list[str]]]:
    res = []
    for node in iter_jsonld_nodes(doc.jsonld):
        types = node.get("@type")
        for t in ([types] if isinstance(types, str) else types or []):
            req = REQUIRED.get(t)
            if req:
                miss = [k for k in req if not node.get(k)]
                if miss:
                    res.append((t, miss))
    return res


def _tokset(s: str) -> str:
    return " ".join(sorted(set(re.findall(r"\w+", s.lower()))))


def analyze_semantics(d: AuditData) -> list[Finding]:
    out: list[Finding] = []
    if d.target.fully_failed and d.raw_doc is None:
        return out
    doc = d.doc
    raw = d.raw_doc
    s = d.settings
    call = d.target.html.call_id if d.target.html else d.md_call
    title = d.page_title
    host = host_of(d.target.final_url)
    h1 = d.h1
    first_para = (doc.first_paragraphs[0] if doc and doc.first_paragraphs else "") or ""
    og_site = (raw.og.get("og:site_name") if raw else None)

    if not title:
        sug = sn.title_suggestion(h1, None, host, og_site)
        out.append(Finding(
            id="SEM_TITLE_MISSING", category="semantics", severity="high", title="No <title> tag",
            evidence=[ev("selector", "<title> not found in raw or rendered HTML", call)],
            ai_impact="Tools lose the page's one-line label.", search_impact="Engines generate a title themselves, often poorly.",
            fix=Fix(steps=["Add a unique <title> of 30–60 characters that states the page's topic."], snippet=sn.head_title_meta(sug, ""),
                    snippet_lang="html", effort_minutes=5, where_to_paste="<head>"), confidence="observed"))
    else:
        sug = sn.title_suggestion(h1, title, host, og_site)
        meta_s = sn.meta_description_suggestion(first_para, d.query)
        snippet = sn.head_title_meta(sug, meta_s)
        if len(title) > s.title_max + 5:
            out.append(Finding(
                id="SEM_TITLE_LONG", category="semantics", severity="low", title=f"Title is {len(title)} characters (~{s.title_max} display limit)",
                evidence=[ev("quote", title, call), ev("metric", f"length={len(title)}")],
                ai_impact="Long titles are truncated or rewritten when shown as citations.", search_impact="Truncated titles lose the keywords at the end.",
                fix=Fix(steps=["Shorten to ≤ 60 characters, keep the topic first, brand last."], snippet=snippet, snippet_lang="html",
                        effort_minutes=5, where_to_paste="<head>"), confidence="observed"))
        words_in_title = re.findall(r"\w+", title)
        brand_tokens = set(re.findall(r"\w+", (og_site or "").lower())) | set(re.findall(r"\w+", host.split(".")[0].lower().replace("-", " ")))
        title_tokens = {w.lower() for w in words_in_title}
        h1_tokens = {w.lower() for w in re.findall(r"\w+", h1 or "")}
        if (title_tokens and title_tokens <= brand_tokens) or title.strip().lower().rstrip(".") == host.lower() \
                or (len(words_in_title) <= 2 and h1_tokens and not (title_tokens & h1_tokens)):
            out.append(Finding(
                id="SEM_TITLE_BRAND_ONLY", category="semantics", severity="medium", title="Title is only a brand/site name",
                evidence=[ev("quote", title, call)],
                ai_impact="A citation labelled only with the brand tells a reader nothing about the page.", search_impact="Gives engines no topical signal.",
                fix=Fix(steps=["Lead the title with the page topic; keep the brand as a suffix."], snippet=snippet, snippet_lang="html",
                        effort_minutes=5, where_to_paste="<head>"), confidence="observed"))
        if h1 and title.strip().lower() == h1.strip().lower() and len(title) > 0:
            out.append(Finding(
                id="SEM_TITLE_EQUALS_H1", category="semantics", severity="low", title="Title is identical to the H1",
                evidence=[ev("quote", f"<title> = <h1> = {title}", call)],
                ai_impact="Missed chance to add distinguishing context in the title.", search_impact="Minor: titles usually benefit from a brand or qualifier.",
                fix=Fix(steps=["Differentiate the title (e.g. add brand or a qualifier) while keeping the H1 as the on-page headline."], snippet=snippet,
                        snippet_lang="html", effort_minutes=5, where_to_paste="<head>"), confidence="observed"))
        if h1 and fuzz.token_set_ratio(_tokset(core_part(title)), _tokset(h1)) < 40:
            out.append(Finding(
                id="SEM_TITLE_H1_MISMATCH", category="semantics", severity="medium", title="Title and H1 describe different topics",
                evidence=[ev("quote", f"<title>: {title}", call), ev("quote", f"<h1>: {h1}", call),
                          ev("metric", f"token_set_ratio={fuzz.token_set_ratio(_tokset(core_part(title)), _tokset(h1)):.0f}")],
                ai_impact="Conflicting labels make the page's topic ambiguous.", search_impact="Engines tend to rewrite titles that don't match on-page content.",
                fix=Fix(steps=["Align the title and the H1 on the same primary topic."], snippet=snippet, snippet_lang="html",
                        effort_minutes=10, where_to_paste="<head> and page heading"), confidence="observed"))

    desc = d.meta_description
    if desc is None or not desc.strip():
        meta_s = sn.meta_description_suggestion(first_para, d.query)
        out.append(Finding(
            id="SEM_DESC_MISSING", category="semantics", severity="medium", title="No meta description",
            evidence=[ev("selector", 'meta[name="description"] not found', call)],
            ai_impact="No author-written summary to quote.", search_impact="Engines pick a snippet automatically, often from boilerplate.",
            fix=Fix(steps=["Write a 110–155 character summary that answers the page's main question."],
                    snippet=f'<meta name="description" content="{meta_s}">' if meta_s else '<meta name="description" content="">',
                    snippet_lang="html", effort_minutes=5, where_to_paste="<head>"), confidence="observed"))
    elif len(desc) < s.desc_min or len(desc) > s.desc_max + 20:
        out.append(Finding(
            id="SEM_DESC_LENGTH", category="semantics", severity="low", title=f"Meta description is {len(desc)} characters",
            evidence=[ev("quote", clip(desc, 200), call), ev("metric", f"length={len(desc)}, target {s.desc_min}-{s.desc_max}")],
            ai_impact="Too short gives little to quote; too long is cut off.", search_impact="Truncated or ignored in results.",
            fix=Fix(steps=[f"Rewrite to {s.desc_min}–{s.desc_max} characters."], snippet=f'<meta name="description" content="{sn.meta_description_suggestion(first_para)}">',
                    snippet_lang="html", effort_minutes=5, where_to_paste="<head>"), confidence="observed"))

    if doc is not None:
        h1s = doc.h1s
        if not h1s:
            out.append(Finding(
                id="SEM_H1_MISSING", category="semantics", severity="high", title="No <h1> on the page",
                evidence=[ev("selector", "h1 not found; headings: " + (", ".join(f"h{l}:{clip(t,40)}" for l, t in doc.headings[:4]) or "none"), call)],
                ai_impact="No clear statement of what the page is about.", search_impact="A missing H1 weakens topical clarity.",
                fix=Fix(steps=["Add exactly one <h1> stating the page topic."], snippet=f"<h1>{h1 or d.query.title()}</h1>", snippet_lang="html",
                        effort_minutes=5, where_to_paste="Page body"), confidence="observed"))
        elif len(h1s) > 1:
            out.append(Finding(
                id="SEM_H1_MULTIPLE", category="semantics", severity="medium", title=f"{len(h1s)} <h1> elements",
                evidence=[ev("selector", f"h1: {clip(t, 80)}", call) for t in h1s[:4]],
                ai_impact="Ambiguous primary topic for extractors.", search_impact="Dilutes the primary heading signal.",
                fix=Fix(steps=["Keep one <h1>; demote the others to <h2>."], effort_minutes=10, where_to_paste="Page template"), confidence="observed"))
        seq = [l for l, _ in doc.headings]
        skips = [(a, b) for a, b in zip(seq, seq[1:]) if b - a > 1]
        if skips:
            a, b = skips[0]
            idx = next(i for i, (x, y) in enumerate(zip(seq, seq[1:])) if (x, y) == (a, b))
            window = seq[max(0, idx - 1): idx + 3]
            out.append(Finding(
                id="SEM_HEADING_SKIP", category="semantics", severity="low", title=f"Heading hierarchy skips from h{a} to h{b}",
                evidence=[ev("selector", "sequence: " + sn.heading_fix(window) + f" ('{clip(doc.headings[idx+1][1], 50)}')", call)],
                ai_impact="Skipped levels blur the document outline used to chunk content.", search_impact="Minor structure signal.",
                fix=Fix(steps=[f"Change the h{b} to h{a+1} (or add the missing h{a+1} section)."], effort_minutes=10, where_to_paste="Page body"), confidence="observed"))

    fu = d.target.final_url
    canon = (raw.canonical if raw else None) or (d.target.rendered_doc.canonical if d.target.rendered_doc else None)
    if not canon:
        out.append(Finding(
            id="SEM_CANONICAL_MISSING", category="semantics", severity="low", title="No canonical link",
            evidence=[ev("selector", 'link[rel="canonical"] not found', call)],
            ai_impact="No declared preferred URL.", search_impact="Duplicate URL variants can split signals.",
            fix=Fix(steps=["Add a self-referencing canonical to the preferred URL."], snippet=sn.canonical_tag(fu), snippet_lang="html",
                    effort_minutes=5, where_to_paste="<head>"), confidence="observed"))
    elif normalize_url(canon) != normalize_url(fu):
        out.append(Finding(
            id="SEM_CANONICAL_MISMATCH", category="semantics", severity="high", title="Canonical points to a different URL",
            evidence=[ev("selector", f'link[rel=canonical] href={canon}', call), ev("url", f"fetched final URL: {fu}", d.md_call)],
            ai_impact="Tools may attribute this content to the canonical URL instead.", search_impact="Engines may drop this URL from the index in favour of the canonical.",
            fix=Fix(steps=["If this URL should be indexed, make the canonical self-referential; otherwise this is intended."], snippet=sn.canonical_tag(fu),
                    snippet_lang="html", effort_minutes=5, where_to_paste="<head>"), confidence="observed"))

    page_lang = (raw.html_lang if raw else None) or (d.target.rendered_doc.html_lang if d.target.rendered_doc else None)
    det = d.target.md.language if d.target.md else None
    if not page_lang:
        out.append(Finding(
            id="SEM_LANG_MISSING", category="semantics", severity="low", title="<html lang> is missing",
            evidence=[ev("selector", "html[lang] not set", call)], ai_impact="Language must be guessed.", search_impact="May affect language/region targeting.",
            fix=Fix(steps=["Declare the page language."], snippet=sn.html_lang_tag(det or "en"), snippet_lang="html", effort_minutes=2, where_to_paste="<html> tag"),
            confidence="observed"))
    elif det and page_lang.split("-")[0].lower() != det.split("-")[0].lower():
        out.append(Finding(
            id="SEM_LANG_MISMATCH", category="semantics", severity="medium", title="Declared language differs from detected language",
            evidence=[ev("selector", f'html lang="{page_lang}"', call), ev("metric", f"Fetch detected language={det}", d.md_call)],
            ai_impact="Wrong language hints can misroute the page in multilingual retrieval.", search_impact="Wrong geo/language targeting.",
            fix=Fix(steps=[f"Set lang to the actual content language ({det})."], snippet=sn.html_lang_tag(det), snippet_lang="html",
                    effort_minutes=2, where_to_paste="<html> tag"), confidence="observed"))

    ptype, why = infer_page_type(fu, raw or doc, d.md)
    d.page_type = ptype
    if raw is not None:
        _jsonld(d, raw, ptype, why, out, call)
        missing_og = [k for k in ("og:title", "og:description", "og:image") if not raw.og.get(k)]
        if missing_og:
            out.append(Finding(
                id="SEM_OG_MISSING", category="semantics", severity="low", title=f"Missing Open Graph tags: {', '.join(missing_og)}",
                evidence=[ev("selector", f'meta[property="{k}"] not found', call) for k in missing_og],
                ai_impact="Link previews and some retrieval systems use OG metadata as the page summary.", search_impact="Weaker social/preview presentation.",
                fix=Fix(steps=["Add the missing OG/Twitter tags."], snippet=sn.og_tags(title or sn.title_suggestion(h1, title, host), desc or sn.meta_description_suggestion(first_para), fu,
                                                                                  raw.og.get("og:image"), "article" if ptype == "article" else "website"),
                        snippet_lang="html", effort_minutes=10, where_to_paste="<head>"), confidence="observed"))
    if doc is not None:
        gl = generic_links(doc)
        if len(gl) >= 2:
            out.append(Finding(
                id="SEM_LINK_TEXT_GENERIC", category="semantics", severity="low", title=f"{len(gl)} links use generic anchor text",
                evidence=[ev("selector", f'<a href="{l["href"]}">{l["text"]}</a>', call) for l in gl[:4]],
                ai_impact="Anchor text is how tools understand link targets; “read more” says nothing.", search_impact="Wasted internal-link relevance signal.",
                fix=Fix(steps=["Replace generic anchors with text that names the destination."], snippet='<a href="/guide">How to configure robots.txt for AI crawlers</a>',
                        snippet_lang="html", effort_minutes=15, where_to_paste="Page body"), confidence="observed"))
    if ptype == "article" and doc is not None:
        from .features import has_author, page_date
        fetch_author = d.target.md.author if d.target.md else None
        fetch_date = d.target.md.published_date if d.target.md else None
        dt = page_date(raw or doc, fetch_date)
        au = has_author(raw or doc, fetch_author)
        if not dt or not au:
            what = " and ".join(x for x, ok in (("a publish/updated date", dt), ("an author", au)) if not ok)
            art = sn.jsonld_article(fu, h1 or title or d.query, dt, None, fetch_author or (raw.author_meta if raw else None) or None,
                                    (raw.og.get("og:image") if raw else None), d.meta_description)
            out.append(Finding(
                id="SEM_NO_AUTHOR_DATE", category="semantics", severity="medium", title=f"Article has no machine-readable {what}",
                evidence=[ev("metric", f"date found={bool(dt)}, author found={bool(au)}; page type inferred from {why}", call)],
                ai_impact="AI answers weigh freshness and attribution; neither can be read here.", search_impact="Freshness-sensitive queries favour dated pages.",
                fix=Fix(steps=[f"Add {what} in visible text and in JSON-LD (Article.datePublished / author)."], snippet=art, snippet_lang="html",
                        effort_minutes=15, where_to_paste="<head> (JSON-LD) and byline"), confidence="inferred"))
    return out


def core_part(title: str) -> str:
    parts = [p.strip() for p in re.split(r"\s+[|–—•·]\s+|\s+-\s+", title) if p.strip()]
    return max(parts, key=len) if parts else title


def _jsonld(d: AuditData, raw: Doc, ptype: str, why: str, out: list[Finding], call) -> None:
    fu = d.target.final_url
    title = d.page_title
    if raw.jsonld_errors:
        out.append(Finding(
            id="SEM_JSONLD_INVALID", category="semantics", severity="medium", title="JSON-LD block does not parse",
            evidence=[ev("error", e) for e in raw.jsonld_errors[:3]], ai_impact="Invalid structured data is ignored.",
            search_impact="No rich-result eligibility from broken markup.",
            fix=Fix(steps=["Validate the JSON-LD (valid JSON, double quotes, no trailing commas)."], effort_minutes=15, where_to_paste="JSON-LD <script>"),
            confidence="observed"))
    types = raw.jsonld_types
    exp = EXPECTED.get(ptype)
    if not raw.jsonld and not raw.jsonld_errors:
        if ptype in ("article", "product", "faq", "howto") or True:
            gen = _gen_schema(d, raw, ptype)
            out.append(Finding(
                id="SEM_JSONLD_MISSING", category="semantics", severity="medium" if ptype in ("article", "product", "faq", "howto") else "low",
                title="No JSON-LD structured data in the raw HTML", evidence=[ev("selector", 'script[type="application/ld+json"] not found in raw HTML', d.target.raw and None)],
                ai_impact="Machines get no explicit statement of what this page is (type, author, date, price).",
                search_impact="Pages without markup are ineligible for rich results; competitors with markup can show dates/ratings.",
                fix=Fix(steps=["Add JSON-LD matching the page type (generated below from values found on the page)."], snippet=gen, snippet_lang="html",
                        effort_minutes=20, where_to_paste="<head>"), confidence="observed"))
    elif exp and types and not (set(types) & exp):
        out.append(Finding(
            id="SEM_JSONLD_TYPE_MISMATCH", category="semantics", severity="medium", title=f"JSON-LD type {', '.join(types)} does not match a {ptype} page",
            evidence=[ev("selector", f"@type present: {', '.join(types)}"), ev("metric", f"page type inferred: {ptype} ({why})")],
            ai_impact="Declared type contradicts the content.", search_impact="Engines may ignore mismatched markup.",
            fix=Fix(steps=[f"Add {'/'.join(sorted(exp))[:40]} markup for this page."], snippet=_gen_schema(d, raw, ptype), snippet_lang="html",
                    effort_minutes=20, where_to_paste="<head>"), confidence="inferred"))
    for t, miss in jsonld_missing(raw):
        out.append(Finding(
            id=f"SEM_JSONLD_PROPS_{t.upper()}", category="semantics", severity="medium", title=f"{t} JSON-LD is missing {', '.join(miss)}",
            evidence=[ev("selector", f"@type={t} lacks: {', '.join(miss)}")], ai_impact="Incomplete markup omits the facts tools most want.",
            search_impact="Required properties are needed for rich-result eligibility.",
            fix=Fix(steps=[f"Add {', '.join(miss)} to the {t} object."], snippet=_gen_schema(d, raw, ptype), snippet_lang="html",
                    effort_minutes=15, where_to_paste="Existing JSON-LD block"), confidence="observed"))


def _gen_schema(d: AuditData, raw: Doc, ptype: str) -> str:
    from .features import page_date
    fu = d.target.final_url
    h1 = d.h1 or d.page_title or d.query
    fa = d.target.md.author if d.target.md else None
    fd = d.target.md.published_date if d.target.md else None
    img = raw.og.get("og:image")
    if ptype == "product":
        return sn.jsonld_product(fu, h1, img, d.meta_description)
    if ptype == "faq":
        from .features import md_headings
        qs = [t for _, t in md_headings(d.md) if t.endswith("?")][:3]
        if qs:
            return sn.jsonld_faq([(q, "<answer text taken from the page>") for q in qs])
    if ptype in ("article", "docs", "howto", "faq"):
        return sn.jsonld_article(fu, h1, page_date(raw, fd), None, fa or raw.author_meta, img, d.meta_description)
    return sn.jsonld_org(sn.brand_from(host_of(fu), raw.og.get("og:site_name")), f"{fu.split('/')[0]}//{host_of(fu)}")
