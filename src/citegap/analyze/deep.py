"""Findings only reachable with a real browser: interaction-only content and overlays."""
from __future__ import annotations

from ..collect.browser_deep import DeepResult, added_text, shingle_coverage
from ..report.model import Finding, Fix
from ..util import clip, word_count
from .context import AuditData, ev


def analyze_deep(d: AuditData, deep: DeepResult, call_id: str | None = None) -> list[Finding]:
    out: list[Finding] = []
    if deep.error:
        return out
    add = added_text(deep.baseline_text, deep.after_text)
    n_add = word_count(add)
    base_n = max(1, word_count(deep.baseline_text))
    if n_add >= 50 and n_add >= 0.10 * base_n and deep.clicked:
        cov = shingle_coverage(d.md, add)
        got = int(round(cov * n_add))
        sev = "high" if cov < 0.25 else "medium"
        if cov < 0.8:
            out.append(Finding(
                id="EXTRACT_INTERACTION_ONLY_CONTENT", category="extractability", severity=sev,
                title=f"{n_add} words only appear after clicking or scrolling; Fetch extracted ~{got} of them",
                evidence=[ev("metric", f"words before interaction={base_n}, newly revealed={n_add}, present in Fetch extraction≈{got} ({int(cov*100)}%)", call_id),
                          ev("selector", "clicked: " + "; ".join(deep.clicked[:5])), ev("quote", clip(add, 200))],
                ai_impact="Content revealed only by a click or scroll is invisible to extractors that do not interact.",
                search_impact="Crawlers that do not click or scroll never index it.",
                fix=Fix(steps=["Render the revealed text in the initial HTML (collapse it with CSS or <details>, not by injecting it on click).",
                               "Server-render lazy sections instead of loading them on scroll."],
                        snippet="<details>\n  <summary>Read more</summary>\n  <p>…the full text, present in the HTML from the start…</p>\n</details>",
                        snippet_lang="html", effort_minutes=60, where_to_paste="Page template"), confidence="observed"))
    ov = deep.overlay
    if ov and ov.get("covers_pct", 0) >= 25 and ov.get("text"):
        out.append(Finding(
            id="EXTRACT_CONSENT_OVERLAY", category="extractability", severity="medium",
            title=f"An overlay covers {ov['covers_pct']}% of the viewport on load",
            evidence=[ev("selector", ov.get("selector", "overlay"), call_id), ev("quote", clip(ov["text"], 200))],
            ai_impact="Screenshot- and browser-based AI agents read the overlay instead of the page until it is dismissed.",
            search_impact="Large interstitials on load can hurt usability signals.",
            fix=Fix(steps=["Shrink the consent banner to a bottom bar and keep it out of the main content flow."],
                    snippet=".consent-banner { position: fixed; bottom: 0; left: 0; right: 0; max-height: 20vh; }", snippet_lang="css",
                    effort_minutes=20, where_to_paste="Site CSS / consent tool settings"), confidence="observed"))
    return out
