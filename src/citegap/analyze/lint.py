"""Evidence-or-drop: findings without concrete evidence or with generic advice never reach the report."""
from __future__ import annotations

import re

from ..report.model import Finding

DENY_PHRASES = [
    "improve content quality", "improve your content", "add more keywords", "build backlinks", "get more backlinks",
    "create high-quality content", "create quality content", "optimize your content", "improve seo", "write better content",
    "increase your authority", "follow seo best practices", "make your site better",
]
MIN_STEP_CHARS = 12


def lint_finding(f: Finding) -> str | None:
    """Return a reason string if the finding must be dropped, else None."""
    if not f.evidence:
        return "no evidence"
    if any(not (e.value or "").strip() for e in f.evidence):
        return "empty evidence value"
    if not f.fix.steps:
        return "no fix steps"
    for step in f.fix.steps:
        low = re.sub(r"\s+", " ", step.lower())
        if len(low.strip()) < MIN_STEP_CHARS:
            return f"fix step too short: {step!r}"
        for phrase in DENY_PHRASES:
            if phrase in low:
                return f"generic advice: {phrase!r}"
    for phrase in DENY_PHRASES:
        if phrase in f.title.lower():
            return f"generic title: {phrase!r}"
    return None


def lint(findings: list[Finding]) -> tuple[list[Finding], list[dict]]:
    kept, dropped = [], []
    seen: set[str] = set()
    for f in findings:
        reason = lint_finding(f)
        if reason is None and f.id in seen:
            reason = "duplicate id"
        if reason:
            dropped.append({"id": f.id, "reason": reason})
        else:
            seen.add(f.id)
            kept.append(f)
    return kept, dropped
