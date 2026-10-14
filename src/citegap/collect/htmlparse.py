"""Parse an HTML document into the features the analyzers need (works for raw and rendered HTML)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..util import word_count

GENERIC_LINK_TEXT = {"click here", "read more", "here", "more", "learn more", "link", "this", "details",
                     "click", "continue", "continue reading", "see more"}


@dataclass
class Doc:
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    meta_robots: list[str] = field(default_factory=list)
    og: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    hreflang: list[dict[str, str]] = field(default_factory=list)
    html_lang: str | None = None
    jsonld: list[dict] = field(default_factory=list)
    jsonld_errors: list[str] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)  # {src, alt (None if missing)}
    links: list[dict[str, str]] = field(default_factory=list)  # {text, href}
    text: str = ""
    word_count: int = 0
    noscript_text: str = ""
    details_count: int = 0
    tabpanel_count: int = 0
    iframes: list[str] = field(default_factory=list)
    has_main: bool = False
    has_article: bool = False
    time_datetimes: list[str] = field(default_factory=list)
    meta_dates: dict[str, str] = field(default_factory=dict)
    author_meta: str | None = None
    byline_found: bool = False
    first_paragraphs: list[str] = field(default_factory=list)
    h1s: list[str] = field(default_factory=list)

    @property
    def jsonld_types(self) -> list[str]:
        return sorted({t for o in iter_jsonld_nodes(self.jsonld) for t in _types(o)})


def _types(node: dict) -> list[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


def iter_jsonld_nodes(blocks: list[dict]):
    """Yield every dict node, flattening @graph and nested lists."""
    stack = list(blocks)
    while stack:
        n = stack.pop(0)
        if isinstance(n, list):
            stack = [x for x in n if isinstance(x, (dict, list))] + stack
            continue
        if not isinstance(n, dict):
            continue
        yield n
        g = n.get("@graph")
        if isinstance(g, list):
            stack = [x for x in g if isinstance(x, (dict, list))] + stack


def _t(node) -> str:
    return re.sub(r"\s+", " ", node.text(separator=" ")).strip() if node is not None else ""


def parse_document(html: str, base_url: str = "") -> Doc:
    d = Doc()
    if not html or not html.strip():
        return d
    tree = HTMLParser(html)
    root = tree.css_first("html")
    if root is not None:
        d.html_lang = (root.attributes.get("lang") or "").strip() or None
    t = tree.css_first("title")
    d.title = _t(t) or None if t is not None else None

    for m in tree.css("meta"):
        a = m.attributes
        name = (a.get("name") or "").lower()
        prop = (a.get("property") or "").lower()
        content = a.get("content") or ""
        if name == "description" and d.meta_description is None:
            d.meta_description = content.strip()
        elif name in ("robots", "googlebot", "bingbot"):
            d.meta_robots.append(f"{name}: {content.strip().lower()}")
        elif prop.startswith("og:"):
            d.og[prop] = content.strip()
        elif name.startswith("twitter:"):
            d.twitter[name] = content.strip()
        elif name == "author" and content.strip():
            d.author_meta = content.strip()
        elif prop in ("article:published_time", "article:modified_time") or name in (
                "date", "pubdate", "datepublished", "dc.date", "dc.date.issued", "last-modified"):
            d.meta_dates[prop or name] = content.strip()
    for l in tree.css("link"):
        rel = (l.attributes.get("rel") or "").lower()
        href = l.attributes.get("href") or ""
        if "canonical" in rel.split() and href and d.canonical is None:
            d.canonical = urljoin(base_url, href) if base_url else href
        elif rel == "alternate" and l.attributes.get("hreflang"):
            d.hreflang.append({"hreflang": l.attributes["hreflang"], "href": href})

    for s in tree.css('script[type="application/ld+json"]'):
        raw = (s.text() or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            d.jsonld.extend(obj if isinstance(obj, list) else [obj])
        except ValueError as exc:
            d.jsonld_errors.append(f"{exc}: {raw[:80]}")

    d.noscript_text = " ".join(_t(n) for n in tree.css("noscript")).strip()
    d.details_count = len(tree.css("details"))
    d.tabpanel_count = len(tree.css('[role="tabpanel"], [role="tab"], .accordion, [data-accordion]'))
    d.iframes = [i.attributes.get("src") or i.attributes.get("data-src") or "" for i in tree.css("iframe")]
    d.iframes = [i for i in d.iframes if i]
    d.has_main = tree.css_first("main, [role=main]") is not None
    d.has_article = tree.css_first("article") is not None
    d.time_datetimes = [t.attributes.get("datetime") or _t(t) for t in tree.css("time")]
    d.byline_found = tree.css_first('[rel="author"], [itemprop="author"], .author, .byline, [class*="byline"]') is not None

    for h in tree.css("h1, h2, h3, h4, h5, h6"):
        txt = _t(h)
        if txt:
            d.headings.append((int(h.tag[1]), txt))
    d.h1s = [t for lvl, t in d.headings if lvl == 1]

    for img in tree.css("img"):
        a = img.attributes
        src = a.get("src") or a.get("data-src") or ""
        w, h_ = a.get("width"), a.get("height")
        tiny = (w and w.isdigit() and int(w) <= 2) or (h_ and h_.isdigit() and int(h_) <= 2)
        if not src or tiny:
            continue
        d.images.append({"src": urljoin(base_url, src) if base_url else src, "alt": a.get("alt")})
    for a in tree.css("a[href]"):
        d.links.append({"text": _t(a), "href": a.attributes.get("href") or ""})

    for p in tree.css("p"):
        txt = _t(p)
        if word_count(txt) >= 8:
            d.first_paragraphs.append(txt)
            if len(d.first_paragraphs) >= 5:
                break

    tree.strip_tags(["script", "style", "noscript", "template", "svg"])
    body = tree.body
    d.text = re.sub(r"\s+", " ", body.text(separator=" ")).strip() if body is not None else ""
    d.word_count = word_count(d.text)
    return d


def generic_links(doc: Doc) -> list[dict[str, str]]:
    return [l for l in doc.links if l["text"].strip().lower().strip(".›»→>") in GENERIC_LINK_TEXT]
