"""Everything collected for one audit, handed to the (deterministic) analyzers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..collect.answerability import HighlightsResult
from ..collect.competitors import CompetitorData
from ..collect.htmlparse import Doc
from ..collect.serp import SerpData
from ..collect.site_files import SiteFiles
from ..collect.target import TargetData
from ..config import Settings
from ..report.model import Evidence, PageFeatures


@dataclass
class AuditData:
    url: str
    query: str
    query_derived: bool
    settings: Settings
    target: TargetData
    serp: SerpData
    site: Optional[SiteFiles]
    competitors: list[CompetitorData]
    target_features: PageFeatures
    competitor_features: list[PageFeatures]
    highlights: HighlightsResult
    page_type: str = "other"
    notes: list[str] = field(default_factory=list)

    @property
    def raw_doc(self) -> Optional[Doc]:
        return self.target.raw.doc if self.target.raw else None

    @property
    def doc(self) -> Optional[Doc]:
        """Best structural view: rendered HTML (Fetch) preferred, raw as fallback."""
        return self.target.rendered_doc or self.raw_doc

    @property
    def md(self) -> str:
        return (self.target.md.text or "") if self.target.md else ""

    @property
    def md_call(self) -> Optional[str]:
        return self.target.md.call_id if self.target.md else None

    @property
    def h1(self) -> Optional[str]:
        d = self.doc
        return d.h1s[0] if d and d.h1s else None

    @property
    def page_title(self) -> Optional[str]:
        if self.raw_doc and self.raw_doc.title:
            return self.raw_doc.title
        if self.target.rendered_doc and self.target.rendered_doc.title:
            return self.target.rendered_doc.title
        return self.target.md.title if self.target.md else None

    @property
    def meta_description(self) -> Optional[str]:
        for d in (self.raw_doc, self.target.rendered_doc):
            if d and d.meta_description is not None:
                return d.meta_description
        return self.target.md.description if self.target.md else None

    @property
    def target_urls(self) -> list[str]:
        urls = [self.url, self.target.final_url]
        for d in (self.raw_doc, self.target.rendered_doc):
            if d and d.canonical:
                urls.append(d.canonical)
        return [u for u in dict.fromkeys(urls) if u]


def ev(kind: str, value: object, call: Optional[str] = None) -> Evidence:
    return Evidence(kind=kind, value=str(value), source_call_id=call)
