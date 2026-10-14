---
name: citegap
description: Audit a public web page for AI search and SEO. Use when asked to "audit this page for AI search", "why doesn't AI cite my page", "check what AI can read on this URL", or to compare a page against the pages outranking it. Runs the CiteGap CLI, which fetches the page live like an AI tool, searches how it ranks, and links readability problems to visibility symptoms.
---

# CiteGap page audit

CiteGap uses TinyFish **Fetch** (what AI tools can extract) and **Search** (how the page ranks, who outranks it) and connects the two.

## Requirements
- `TINYFISH_API_KEY` in the environment or a `.env` file (get one at agent.tinyfish.ai/api-keys). If it is missing, tell the user and stop; do not invent results.
- The package installed: `pip install -e .` from the CiteGap repo (Python 3.11+). Optional `ANTHROPIC_API_KEY` adds LLM rewrite suggestions to the fix pack.

## Run
```bash
citegap audit "https://example.com/blog/post" --query "target query" --format md
citegap audit "https://example.com/blog/post" --out ./audit --fixpack      # report.md, report.json, fix-pack zip
```
Omit `--query` to derive one from the page (the report labels it as derived; suggest the user re-run with their real query).
Or call a hosted instance: `POST /audit {"url": "...", "query": "..."}` then `GET /audit/{id}`.

## Reading the output
- **ARS** (AI readability) and **SVS** (search visibility), each 0-100, with visible component breakdowns.
- **Gap Matrix**: readability cause linked to visibility symptom. `observed` means both sides were measured and the link is demonstrated; `inferred` means plausible but not proven. Never state an inferred link as fact, and never promise rankings.
- Each finding has evidence (quoted text, selector, URL, rank, HTTP/error code) and a paste-ready snippet.

## What to tell the user
1. One-sentence verdict (scores plus rank).
2. The top 5 fixes ordered by impact then effort (the report already sorts them). For each: the evidence, the fix, the minutes.
3. Mention any note about `highlights` unavailable (BM25 fallback) or a derived query.

## Rules
- If the CLI errors (missing key, quota, rate limit, rejected URL), report the exact error. **Never fabricate findings, scores or ranks.**
- A page the fetcher could not read (`bot_blocked`, `login_required`, `empty_content`, `timeout`) is a real finding: say AI tools likely cannot read it either.
- Audit only public pages; do not hammer a site (one audit is a handful of requests).
