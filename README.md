# CiteGap — AI-readability × search-visibility auditor

> Search shows how you rank. Fetch shows what AI can actually read. CiteGap shows how the two are connected, and what to fix today.

Built for the **TinyFish × DTU: SEO Page Auditor** bounty (Technical, Agentic App + Skill).
Paste a URL (and optionally a target query). CiteGap fetches the live page the way an AI tool would, searches how it actually ranks, fetches the pages outranking it, and links each readability problem to the visibility symptom it plausibly causes, with evidence.

**Outputs:** an AI Readability Score (ARS) and a Search Visibility Score (SVS) with visible breakdowns, a **Gap Bridge** (cause → symptom), a "what AI sees" view, a real-SERP card, a competitor delta table, and a fix pack with paste-ready snippets.

## How TinyFish is used

Two endpoints are core and verified in tests. An opt-in **deep mode** (`citegap audit --deep`, UI checkbox) adds the Browser API (remote Chromium over CDP) to find content that only appears after clicks/scroll and consent overlays. It is experimental, uses credits, and has not been validated live yet; see `DECISIONS.md`.

| Call | Endpoint | Why |
|---|---|---|
| Target, markdown + links + images + iframes | **Fetch** `ttl:0` | What an AI extractor gets: text, link/iframe/image inventory, redirect chain, errors |
| Target, semantic HTML | **Fetch** `ttl:0` | Heading structure, landmarks, alt text, link text, as rendered after JavaScript |
| Target, `include_selectors=[main,article]` | **Fetch** `ttl:0` | Is there a `<main>`/`<article>`? How much of the extraction is boilerplate? (`selector_not_matched` + `candidate_selectors` become a finding) |
| robots.txt, llms.txt, sitemap.xml (one batch) | **Fetch** `ttl:0` | Per-bot access rules (with the exact matching rule line), llms.txt presence, sitemap coverage |
| Top 3 competitors (one batch) | **Fetch** `ttl:0` | Same feature vector as the target, for the delta table |
| Target + competitors with `highlights` | **Fetch** `ttl:0` | Passages that answer the query; empty on target while competitors answer = specific finding. Falls back to local BM25 if the account lacks the beta (labelled in the report) |
| Target query (page 0, page 1 only if absent) | **Search** | Rank by normalized URL match, who outranks you, real SERP title/snippet |
| Same query + `include_domains=<your domain>` | **Search** | Indexation probe: does this domain surface, and is this page among it? |
| `"<exact page title>"` | **Search** | Is the page findable by its own title, or was it heavily rewritten? |
| H1 as a question (answer/article pages only) | **Search** | Does the domain appear for the natural-language form? |

At most 6 Search calls per audit. Every Fetch is live (`ttl: 0`); the UI's call log shows each call with its latency. Our own SSRF-guarded plain GET (not a TinyFish call) reads the raw HTML, because Fetch strips scripts and JSON-LD only exists in raw HTML.

## Why the Gap Bridge is the point

Neither half works alone. A bridge is drawn only when **both** sides are in this audit's evidence, for example:

- Content only exists after JavaScript **and** a domain-restricted search finds other pages on the domain but not this one.
- The engine replaced your `<title>` **and** your title is overlong or unrelated to your H1 (both strings shown).
- No passage on your page answers the query **and** competitors have one (their passage quoted).
- robots.txt blocks an AI *search* bot (reported as an **AI-answer visibility** loss, not a Google rank signal).

Bridges are marked `observed` (both sides measured, link demonstrated) or `inferred`. Nothing promises rankings.

## Quickstart

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # add TINYFISH_API_KEY
python scripts/smoke.py         # one live Search + one live Fetch
citegap audit "https://example.com/blog/post" --query "your target query"
citegap serve                   # web app on :8000
pytest                          # tests use fixtures from tests/ only
```

Web app: paste a URL → live stage list and TinyFish call log (SSE) → report with permalink (`/r/<id>`), fix-pack zip, and **Re-audit** (shows the score/rank/finding delta against the previous run of the same URL).

### Skill
`skill/SKILL.md` wraps the CLI for agents: when to trigger, required env var, how to read the output, and a hard rule never to fabricate findings if the CLI errors.

### API
`POST /audit {url, query?}` → `{id}` · `GET /audit/{id}/events` (SSE) · `GET /audit/{id}` · `GET /audit/{id}/report.md` · `GET /audit/{id}/fixpack.zip` · `POST /audit/{id}/reaudit` · `GET /healthz`. Per-IP rate limit (429 with `Retry-After`).

## Honest limits
- Search results are not an authoritative index check; "not indexed" findings say *likely* and tell you to confirm in Search Console / Bing Webmaster Tools.
- "Many AI crawlers do not execute JavaScript" is a heuristic, not a claim about every crawler.
- `llms.txt` is reported as low severity; it is an emerging convention, not a proven ranking factor.
- Blocking training bots while allowing search bots is a valid policy; the report says so.
- Rank and presentation depend on the Search API's results at audit time.

## Security
Keys come from the environment only and are never logged (`TinyFishClient.__repr__` masks them). The raw HTTP fetcher resolves DNS, rejects private/loopback/link-local/CGNAT addresses, re-checks every redirect hop, connects to the validated IP, caps responses at 3 MB, and uses an honest UA (`CiteGapAuditor/1.0`). The audit endpoint is rate-limited per IP. The UI renders page-derived text with `textContent` only.

## Demo set
`scripts/demo_set.py` runs six live audits (SPA, weak blog, docs, product page, bot-blocking page, your own page before/after) and writes real outputs to `examples/`. **They have not been generated yet** (they need a live key and URLs); see `examples/README.md`.

## Layout
`src/citegap/{tinyfish,collect,analyze,fixes,report}`, `pipeline.py`, `api.py`, `cli.py`; `web/`; `skill/`; `tests/`. See `CLAUDE.md` for the full spec and `BUILD_GUIDE.md` for the phased build.
