"""Pydantic models shared across the pipeline and the API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["access", "extractability", "semantics", "answerability", "serp"]
Severity = Literal["critical", "high", "medium", "low"]
Confidence = Literal["observed", "inferred"]


class Evidence(BaseModel):
    kind: str  # quote | selector | url | rank | http | error | metric | rule | snippet
    value: str
    source_call_id: Optional[str] = None


class Fix(BaseModel):
    steps: list[str]
    snippet: Optional[str] = None
    snippet_lang: Optional[str] = None
    effort_minutes: int = 10
    where_to_paste: Optional[str] = None


class Finding(BaseModel):
    id: str
    category: Category
    severity: Severity
    title: str
    evidence: list[Evidence]
    ai_impact: str
    search_impact: str
    fix: Fix
    bridge_to: list[str] = Field(default_factory=list)
    confidence: Confidence = "observed"


class Bridge(BaseModel):
    id: str
    cause_id: str
    symptom_id: str  # a SERP finding id, or the virtual AI_ANSWER_VISIBILITY
    symptom_kind: str  # indexation | rank | title | snippet | rich_snippet | ai_visibility | depth
    statement: str
    confidence: Confidence
    evidence: list[Evidence]


class CallLogEntry(BaseModel):
    id: str
    endpoint: Literal["search", "fetch", "browser"]
    summary: str
    ttl: Optional[int] = None
    started_at: str
    latency_ms: int = 0
    status: str = "pending"  # ok | http_<code> | error
    detail: str = ""


class ScoreComponent(BaseModel):
    name: str
    points: float
    max_points: float
    note: str = ""


class Score(BaseModel):
    total: float
    components: list[ScoreComponent]
    note: str = ""


class PageFeatures(BaseModel):
    url: str
    title: Optional[str] = None
    word_count: int = 0
    h2_count: int = 0
    list_count: int = 0
    table_count: int = 0
    has_faq: bool = False
    schema_types: list[str] = Field(default_factory=list)
    schema_known: bool = False  # False when we could not read raw HTML
    date: Optional[str] = None
    has_author: bool = False
    answer_first: bool = False
    query_coverage_first150: float = 0.0
    best_passage: Optional[str] = None
    best_passage_score: Optional[float] = None
    passage_coverage: Optional[float] = None
    serp_position: Optional[int] = None
    serp_snippet: Optional[str] = None


class SerpResult(BaseModel):
    position: int
    title: str = ""
    snippet: str = ""
    url: str = ""
    site_name: str = ""


class SerpProbe(BaseModel):
    kind: str  # target_query | indexation | exact_title | question
    query: str
    page: int = 0
    include_domains: Optional[str] = None
    results: list[SerpResult] = Field(default_factory=list)
    call_id: Optional[str] = None
    error: Optional[str] = None


class WhatAISeesLine(BaseModel):
    text: str
    boilerplate: bool = False


class WhatAISees(BaseModel):
    lines: list[WhatAISeesLine] = Field(default_factory=list)
    lost: list[Evidence] = Field(default_factory=list)
    rendered_chars: int = 0
    raw_chars: int = 0
    extraction_method: str = "full-page"


class Report(BaseModel):
    id: str
    url: str
    final_url: Optional[str] = None
    query: str
    query_derived: bool
    created_at: str
    duration_s: float = 0.0
    could_not_read: bool = False
    answerability_method: str = "bm25"  # highlights | bm25
    ars: Score
    svs: Score
    findings: list[Finding] = Field(default_factory=list)
    bridges: list[Bridge] = Field(default_factory=list)
    lint_dropped: list[dict] = Field(default_factory=list)
    target: Optional[PageFeatures] = None
    competitors: list[PageFeatures] = Field(default_factory=list)
    serp: list[SerpProbe] = Field(default_factory=list)
    delta_table: list[dict] = Field(default_factory=list)
    domain_share: Optional[dict] = None
    what_ai_sees: Optional[WhatAISees] = None
    serp_card: Optional[dict] = None
    calls: list[CallLogEntry] = Field(default_factory=list)
    endpoints_used: dict[str, int] = Field(default_factory=dict)
    previous: Optional[dict] = None  # {id, ars, svs, created_at, delta}
    notes: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)
