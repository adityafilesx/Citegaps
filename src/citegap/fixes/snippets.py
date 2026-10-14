"""Deterministic paste-ready snippets. Values come from the audited page; unknown values are omitted, never invented."""
from __future__ import annotations

import html
import json
import re
from typing import Optional

from ..util import clip, host_of


def brand_from(host: str, og_site: Optional[str] = None) -> str:
    if og_site:
        return og_site.strip()
    label = host.split(".")[0] if host else ""
    return label.replace("-", " ").title()


def title_suggestion(h1: Optional[str], title: Optional[str], host: str, og_site: Optional[str] = None,
                     limit: int = 60) -> str:
    core = re.split(r"\s+[|–—•·]\s+|\s+-\s+", (h1 or title or host), maxsplit=1)[0].strip()
    brand = brand_from(host, og_site)
    cand = f"{core} | {brand}" if brand and brand.lower() not in core.lower() else core
    if len(cand) > limit:
        cand = core if len(core) <= limit else clip(core, limit).rstrip("…").rstrip() 
    return cand


def meta_description_suggestion(first_paragraph: Optional[str], query: str = "", lo: int = 110, hi: int = 155) -> str:
    p = re.sub(r"\s+", " ", first_paragraph or "").strip()
    if not p:
        return ""
    if len(p) <= hi:
        return p
    cut = p[:hi]
    cut = cut[: cut.rfind(" ")] if " " in cut else cut
    return cut.rstrip(",;:- ") + "…" if len(cut) >= lo else cut


def head_title_meta(title: str, desc: str) -> str:
    out = [f"<title>{html.escape(title)}</title>"]
    if desc:
        out.append(f'<meta name="description" content="{html.escape(desc, quote=True)}">')
    return "\n".join(out)


def robots_allow_lines(bots: list[str]) -> str:
    return "\n\n".join(f"User-agent: {b}\nAllow: /" for b in bots)


def robots_remove_note(rule_lines: list[str]) -> str:
    return "\n".join(f"# remove or narrow:  {l}" for l in rule_lines)


def jsonld_script(obj: dict) -> str:
    return '<script type="application/ld+json">\n' + json.dumps(obj, indent=2, ensure_ascii=False) + "\n</script>"


def jsonld_article(url: str, headline: str, date_published: Optional[str] = None, date_modified: Optional[str] = None,
                   author: Optional[str] = None, image: Optional[str] = None, description: Optional[str] = None,
                   kind: str = "Article") -> str:
    o: dict = {"@context": "https://schema.org", "@type": kind, "headline": clip(headline, 110),
               "mainEntityOfPage": {"@type": "WebPage", "@id": url}}
    if description:
        o["description"] = clip(description, 300)
    if image:
        o["image"] = [image]
    if date_published:
        o["datePublished"] = date_published
    if date_modified:
        o["dateModified"] = date_modified
    if author:
        o["author"] = {"@type": "Person", "name": author}
    return jsonld_script(o)


def jsonld_product(url: str, name: str, image: Optional[str] = None, description: Optional[str] = None,
                   price: Optional[str] = None, currency: Optional[str] = None) -> str:
    o: dict = {"@context": "https://schema.org", "@type": "Product", "name": name, "url": url}
    if image:
        o["image"] = [image]
    if description:
        o["description"] = clip(description, 300)
    if price and currency:
        o["offers"] = {"@type": "Offer", "price": price, "priceCurrency": currency,
                       "availability": "https://schema.org/InStock", "url": url}
    return jsonld_script(o)


def jsonld_faq(pairs: list[tuple[str, str]]) -> str:
    o = {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": q,
                         "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs]}
    return jsonld_script(o)


def jsonld_org(name: str, url: str, logo: Optional[str] = None) -> str:
    o: dict = {"@context": "https://schema.org", "@type": "Organization", "name": name, "url": url}
    if logo:
        o["logo"] = logo
    return jsonld_script(o)


def canonical_tag(url: str) -> str:
    return f'<link rel="canonical" href="{html.escape(url, quote=True)}">'


def og_tags(title: str, desc: str, url: str, image: Optional[str] = None, kind: str = "website") -> str:
    lines = [f'<meta property="og:type" content="{kind}">',
             f'<meta property="og:title" content="{html.escape(title, quote=True)}">',
             f'<meta property="og:url" content="{html.escape(url, quote=True)}">']
    if desc:
        lines.append(f'<meta property="og:description" content="{html.escape(desc, quote=True)}">')
    if image:
        lines.append(f'<meta property="og:image" content="{html.escape(image, quote=True)}">')
    lines.append('<meta name="twitter:card" content="summary_large_image">')
    return "\n".join(lines)


def answer_block(question: str, passage: Optional[str]) -> str:
    ans = clip(passage, 280) if passage else "<one or two sentences that directly answer the question>"
    return f"<h2>{html.escape(question)}</h2>\n<p>{html.escape(ans)}</p>"


def main_landmark(example_selector: str = "") -> str:
    return ('<body>\n  <header>…site navigation…</header>\n  <main>\n    <article>\n      <h1>Page title</h1>\n'
            '      …primary content…\n    </article>\n  </main>\n  <footer>…</footer>\n</body>')


def html_lang_tag(lang: str) -> str:
    return f'<html lang="{lang}">'


def heading_fix(seq: list[int]) -> str:
    return " → ".join(f"h{n}" for n in seq)
