"""Optional: Claude rewrite of title / meta / answer block. Uses only facts already in the report."""
from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from ..config import Settings
from ..report.model import Report


async def llm_suggestions(r: Report, settings: Settings, h1: Optional[str], meta: Optional[str],
                          transport: Optional[httpx.AsyncBaseTransport] = None) -> Optional[dict]:
    if not settings.anthropic_api_key:
        return None
    facts = {
        "url": r.url, "target_query": r.query, "current_h1": h1, "current_meta_description": meta,
        "serp_title": (r.serp_card or {}).get("serp_title"), "page_title": (r.serp_card or {}).get("page_title"),
        "best_passage_on_page": r.target.best_passage if r.target else None,
        "competitor_titles": [c.title for c in r.competitors if c.title],
        "top_findings": [f.title for f in r.findings[:6]],
    }
    prompt = ("Using ONLY these facts, propose: a <title> (<=60 chars), a meta description (110-155 chars) and a 2-sentence answer "
              "paragraph that answers the target query. Do not invent facts, numbers, names or claims. Reply as JSON with keys "
              "title, meta_description, answer_paragraph.\n\n" + json.dumps(facts, ensure_ascii=False))
    try:
        async with httpx.AsyncClient(transport=transport, timeout=60) as c:
            resp = await c.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": settings.llm_model, "max_tokens": 600, "messages": [{"role": "user", "content": prompt}]})
        resp.raise_for_status()
        text = "".join(b.get("text", "") for b in resp.json().get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None
