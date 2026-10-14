"""Heuristic page-type inference used to pick expected schema.org types."""
from __future__ import annotations

import re

from ..collect.htmlparse import Doc

EXPECTED = {
    "article": {"Article", "BlogPosting", "NewsArticle", "TechArticle", "ScholarlyArticle", "Report"},
    "product": {"Product"},
    "faq": {"FAQPage"},
    "howto": {"HowTo"},
}


def infer_page_type(url: str, doc: Doc | None, text: str = "") -> tuple[str, str]:
    """(type, reason). Only returns a confident type; else ('other', reason)."""
    path = re.sub(r"https?://[^/]+", "", url).lower()
    og_type = (doc.og.get("og:type", "") if doc else "").lower()
    types = set(doc.jsonld_types) if doc else set()
    if types & EXPECTED["product"] or og_type in ("product", "og:product") or re.search(r"/(product|products|p|item|dp)/", path):
        return "product", "product signals (JSON-LD/og:type/URL)"
    if types & EXPECTED["faq"]:
        return "faq", "FAQPage JSON-LD"
    if types & EXPECTED["howto"]:
        return "howto", "HowTo JSON-LD"
    if types & EXPECTED["article"] or og_type == "article" or re.search(r"/(blog|post|posts|news|article|articles)/", path) \
            or (doc and any(k in doc.meta_dates for k in ("article:published_time",))):
        return "article", "article signals (JSON-LD/og:type/URL/meta date)"
    if re.search(r"/(docs?|documentation|guide|guides|reference|manual)/", path):
        return "docs", "documentation URL path"
    if path in ("", "/"):
        return "home", "site root"
    return "other", "no confident signal"
