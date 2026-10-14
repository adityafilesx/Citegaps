# CiteGap — AI-Readability × Search-Visibility Auditor

> Working name: **CiteGap**. Tagline: *"Search shows how you rank. Fetch shows what AI can actually read. CiteGap shows how the two are connected, and what to fix today."*

Built for the **TinyFish × DTU: SEO Page Auditor** bounty (Technical category, Agentic App + Skill, 200-pt tier target).

This file is the instruction set for Claude Code. Read it fully before writing code. Follow the **Rules** section strictly.

---

## 0. Rules for Claude Code (read first)

1. **No canned data in the product path.** Every audit must call TinyFish Search and Fetch live. Fixtures are allowed only in `tests/` for unit tests of parsers and scorers. Never ship a "demo mode" that replays saved results.
2. **Always fetch live.** Send `ttl: 0` on every Fetch call so the audit never reads a cached copy.
3. **Every finding needs evidence.** A finding with no concrete evidence (quoted text, selector, URL, rank number, HTTP/error code) is dropped by a lint step. No generic SEO tips like "improve your content".
4. **No causation claims we can't back up.** Say "likely contributing" and show the evidence. Never promise rankings.
5. **Don't pad endpoint usage.** Each TinyFish call must produce at least one finding or score input. If a call produces nothing, remove it.
6. **Security.** Never commit keys. Read `TINYFISH_API_KEY` (and optional `ANTHROPIC_API_KEY`) from env. Block private IPs/localhost in our own raw HTTP fetcher (SSRF guard). Rate-limit our public endpoint per IP. Never log full API keys.
7. **Verify the docs before coding each integration.** Start by reading `https://docs.tinyfish.ai/for-coding-agents.md`, `https://docs.tinyfish.ai/search-api/reference.md`, `https://docs.tinyfish.ai/fetch-api/reference.md`. Index of all docs: `https://docs.tinyfish.ai/llms.txt`. If anything in this plan conflicts with the docs, the docs win. Update this file.
8. Use raw `httpx` (async) for TinyFish calls instead of the SDK, so we control concurrency, backoff, and call logging. (SDK exists: `from tinyfish import TinyFish`; optional.)
9. Commit small, commit often. Keep a `DECISIONS.md` for any deviation from this plan.

---

## 1. Product in one paragraph

User pastes a URL (and optionally a target query). CiteGap:

1. **Fetches** the live page the way an AI tool would and records what was extracted, what failed, and what was lost.
2. **Searches** the live web to see how that page (and the domain) actually shows up: indexed or not, rank for the target query, how the SERP title/snippet differs from the page, and who outranks it.
3. **Fetches the top competitors** and diffs them against the target.
4. **Connects the two sides.** Each AI-readability problem is mapped to the visibility symptom it likely causes, with evidence.
5. Outputs **two scores, a Gap Matrix, a "what AI sees" view, and a fix pack** a site owner can paste into their site the same day.

### Why this should win (map to approval criteria)

| Criterion | How CiteGap satisfies it |
|---|---|
| Search and Fetch both contribute meaningfully | Search = rank, indexation, SERP title/snippet, competitors. Fetch = target extraction, selector tests, robots/llms.txt, competitor extraction. Neither works alone; the Gap Matrix needs both. |
| Audits live pages | `ttl: 0` on every Fetch, live Search, UI shows a live call log with timestamps. |
| Findings specific and actionable | Evidence-or-drop lint. Every fix ships a paste-ready snippet (title/meta rewrite, JSON-LD, robots.txt lines, heading/answer block). |
| Works for any URL | Graceful handling of every Fetch error code (`bot_blocked`, `login_required`, `empty_content`, `timeout`, `selector_not_matched`, etc.). A blocked page produces a *finding*, not a crash. |
| Connects readability to search visibility | The **Gap Bridge**: symptom to cause mapping + competitor delta. This is the core idea. |
| Posts | LinkedIn + X posts tagging TinyFish, plus Discord #showcase (see Section 12). |

---

## 2. TinyFish API facts (verified from docs; re-verify before coding)

**Auth:** header `X-API-Key: $TINYFISH_API_KEY`. Keys at `agent.tinyfish.ai/api-keys`.

**Search** `GET https://api.search.tinyfish.ai`
- Params: `query` (required), `purpose`, `location`, `language`, `include_domains`, `exclude_domains`, `recency_minutes`, `after_date`, `before_date`, `domain_type` (`web` | `news` | `research_paper`), `page` (0 to 10).
- Response: `{query, results:[{position, site_name, title, snippet, url, date?}], total_results, page}`.
- Limits: docs say 30 req/min default; the launch blog says free tier 5 queries/min. **Plan for 5/min** (make configurable). Free up to 12,000/day.
- Always pass `purpose` (e.g. "Audit how a page ranks for its target query and who outranks it").

**Fetch** `POST https://api.fetch.tinyfish.ai`
- Body: `urls` (max 10), `format` (`markdown` default | `html` | `json`), `links`, `image_links`, `iframe_links`, `ttl` (0 = live), `per_url_timeout_ms` (1 to 110000), `include_selectors`, `exclude_selectors`, `purpose`, `include_etag_and_last_modified`, `highlights` (beta, per-account).
- Response: `{results:[{url, final_url, title, description, language, author, published_date, text, links, image_links, iframe_links, unmatched_selectors, highlights, latency_ms, format}], errors:[{url, error, status?, unmatched_selectors?, candidate_selectors?}]}`.
- Per-URL error codes: `target_http_error`, `page_not_found`, `target_unreachable`, `timeout`, `bot_blocked`, `empty_content`, `login_required`, `content_too_large`, `invalid_url`, `invalid_redirect_url`, `proxy_error`, `selector_not_matched`, `selector_unsupported`, `conditional_unsupported`.
- Renders JS-heavy pages when needed. Rejects private IPs/localhost.
- Limits: 150 URLs/min default (launch blog says 25/min free). Free up to 1,000 URLs/day. **Batch up to 10 URLs per request**, set client timeout >= 150 s.
- `highlights` returns ranked verbatim passages answering a question. An **empty array** means the page does not answer the query. Needs account enablement (403 otherwise). **Treat as optional; implement a local fallback** (Section 6.5).

> **Docs check (2026-10-14):** differences from the lines above are logged in `DECISIONS.md` (Search default is 30/min; highlights requires `format: markdown`; Fetch limits are URLs/min). Browser stage was cut; the submission claims 2 endpoints.

**Browser** `POST https://api.browser.tinyfish.ai` (remote CDP session; uses credits) and **Agent** (`https://agent.tinyfish.ai/v1/automation/...`, uses credits). Free tier of credits: ~500. Only for the optional Phase 6.

---

## 3. Architecture

```
citegap/
├── CLAUDE.md                  # this file
├── DECISIONS.md               # deviations log
├── README.md                  # judge-facing: what/why/how TinyFish is used, demo links
├── .env.example               # TINYFISH_API_KEY=, ANTHROPIC_API_KEY= (optional)
├── pyproject.toml
├── src/citegap/
│   ├── config.py              # env, rate limits, AI-bot list, thresholds
│   ├── tinyfish/
│   │   ├── client.py          # httpx async client, retry/backoff, token-bucket limiter, call log
│   │   ├── search.py          # search(), paginate()
│   │   └── fetch.py           # fetch_many() with batching, error normalization
│   ├── collect/
│   │   ├── target.py          # Stage 1: live fetch of target (markdown + html + links)
│   │   ├── raw_http.py        # SSRF-safe plain GET (no JS) for raw HTML comparison
│   │   ├── serp.py            # Stage 2: Search queries and rank detection
│   │   ├── competitors.py     # Stage 3: fetch top-N competitors
│   │   ├── site_files.py      # robots.txt, llms.txt, sitemap via Fetch
│   │   └── answerability.py   # highlights or local passage scoring
│   ├── analyze/
│   │   ├── access.py          # AI-bot access, error-code findings
│   │   ├── extractability.py  # raw vs rendered, main-content detection, boilerplate ratio
│   │   ├── semantics.py       # title/meta/H1/headings/canonical/JSON-LD/alt/link text
│   │   ├── answerability.py   # query coverage, answer-first, lists/tables/FAQ, freshness
│   │   ├── serp_gap.py        # rank, indexation, title/snippet rewrite, competitor delta
│   │   ├── bridge.py          # THE CORE: symptom to cause mapping
│   │   ├── scoring.py         # ARS + SVS
│   │   └── lint.py            # evidence-or-drop
│   ├── fixes/
│   │   ├── snippets.py        # deterministic paste-ready snippets
│   │   └── llm_rewrite.py     # optional Claude rewrite of title/meta/answer block
│   ├── report/
│   │   ├── model.py           # pydantic models (Finding, Report, CallLogEntry)
│   │   ├── render_md.py       # Markdown report
│   │   └── fixpack.py         # zip: report.md, report.json, snippets/*
│   ├── pipeline.py            # orchestrates stages, emits progress events
│   ├── api.py                 # FastAPI: POST /audit, GET /audit/{id}/events (SSE), GET /audit/{id}
│   └── cli.py                 # `citegap audit <url> --query "..."`
├── web/                       # single-page UI (vanilla JS + Tailwind CDN or small Vite app)
├── skill/SKILL.md             # Claude Skill wrapper (Section 10)
├── tests/
└── examples/                  # saved REAL audit outputs for the README only (not used by the app)
```

**Stack:** Python 3.11, FastAPI, httpx, selectolax (or BeautifulSoup), pydantic v2, rapidfuzz, `rank-bm25` (local passage scoring). UI: plain HTML/JS with SSE. Deploy: Render/Fly/Railway (needs a public URL for the demo).

**Pipeline events:** every stage emits `{stage, message, tinyfish_call?}` over SSE so the UI shows a live call log. This doubles as evidence for judges.

---

## 4. Pipeline stages (build in this order)

### Stage 1 — Fetch the target (live)
- One Fetch request, `urls=[target]`, `format=markdown`, `links=true`, `image_links=true`, `iframe_links=true`, `ttl=0`, `per_url_timeout_ms=60000`, `purpose="Audit what an AI tool can extract from this page"`.
- Second Fetch request, same URL, `format=html` (semantic HTML) for structure parsing (headings, landmarks, alt text, link text).
- Third Fetch with `include_selectors=["main","article"]` and `exclude_selectors=["nav","footer","aside"]`. If `selector_not_matched`, store `candidate_selectors` (finding: "no `<main>`/`<article>` landmark; an AI extractor must guess where content is").
- Store: `final_url` (redirect chains), title, description, language, author, published_date, text, links, image_links, latency_ms, any `errors[]`.
- If Fetch errors (`bot_blocked`, `login_required`, `empty_content`, `timeout`, ...): **do not abort.** Record as a top-severity access finding, then continue with Search so the visibility half still works.

### Stage 1b — Raw HTML (no JS) via our own `httpx` GET
- SSRF guard (reject private/loopback/link-local; resolve DNS and re-check after redirects; cap 3 MB; 10 s timeout; honest UA `CiteGapAuditor/1.0`).
- Parse: `<title>`, meta description, canonical, meta robots / X-Robots-Tag, `og:*`, `twitter:*`, hreflang, `<html lang>`, **JSON-LD blocks** (Fetch strips scripts, so only raw HTML shows structured data), headings, visible text length, `<noscript>` content.
- **JS-dependency gap:** `rendered_text_len` (Fetch) vs `raw_text_len`. If raw is < 40% of rendered, finding: "most content only exists after JavaScript runs; crawlers that don't execute JS see a near-empty page". Phrase as "many AI crawlers do not execute JavaScript" (heuristic, not universal).

### Stage 2 — Search: how the page shows up
Derive queries (if user gave none, derive from Fetch results: H1/title + top keyphrases via simple TF-IDF; let user edit and rerun):
1. **Target query** (user or derived), `page=0` and `page=1` only if the target URL isn't in page 0. Detect the target's rank by normalized URL match (strip tracking params, trailing slash, `www`).
2. **Indexation probe:** same query with `include_domains=<target domain>`: which pages of this domain surface? Is the target among them?
3. **Exact-title probe:** `"<page title>"` in quotes. Not found means likely not indexed or heavily rewritten.
4. **Question probe** (only if the page looks like an answer/article): turn the H1 into a natural question and search it. Does the domain appear?

Budget: **at most 4 to 6 Search calls per audit**; respect the limiter (default 5/min). Use `location`/`language` from the page's `<html lang>`.

Record per result: position, title, snippet, url, site_name.

### Stage 3 — Competitors and site files (batched Fetch)
- Take the top 3 organic results that are not the target domain (skip obvious aggregators like reddit/quora/pinterest only if the user opts in; otherwise keep them, since they're real competition).
- **One batched Fetch** for competitors (`format=markdown`, `links=true`, `ttl=0`).
- **One batched Fetch** for `https://<domain>/robots.txt`, `/llms.txt`, `/sitemap.xml` (plain text/JSON returns as text; tolerate `page_not_found`).
- Compute the same feature vector for each competitor (word count, heading counts, list/table counts, FAQ presence, date, author, answer-first score, query coverage).

### Stage 4 — Answerability
- **Preferred:** Fetch with `highlights={query: "<entity> <target query>", max_snippets: 5}` on the target and competitors. Empty highlights on the target while competitors return passages means "the page does not answer this query" (strong, specific finding). Keep the passages for the report.
- **Fallback (when 403/unavailable):** local BM25 over paragraph chunks of the markdown, scoring the query; report the best passage and its score. Label clearly in the UI which method was used.

### Stage 5 — Analyze, bridge, score, lint (all deterministic)
See Sections 5 to 8.

### Stage 6 (optional, only if it earns its place) — Browser API deep mode
See Section 9. Decision gate on Day 9.

---

## 5. Finding model

```python
class Finding(BaseModel):
    id: str                      # stable, e.g. "ACCESS_GPTBOT_BLOCKED"
    category: Literal["access","extractability","semantics","answerability","serp"]
    severity: Literal["critical","high","medium","low"]
    title: str                   # one line, plain English
    evidence: list[Evidence]     # REQUIRED non-empty. {kind, value, source_call_id}
    ai_impact: str               # what AI search/fetch tools experience
    search_impact: str           # how this plausibly affects visibility
    fix: Fix                     # {steps: [..], snippet: str|None, snippet_lang, effort_minutes, where_to_paste}
    bridge_to: list[str] = []    # ids of linked SERP findings (Section 7)
    confidence: Literal["observed","inferred"]   # observed = directly measured; inferred = heuristic
```

`lint.py` drops any finding where `evidence` is empty or whose `fix.steps` are generic. Maintain a small deny-list of vague phrases ("improve content quality", "add more keywords", "build backlinks").

---

## 6. Analyzers (specific checks)

### 6.1 Access (AI can reach it?)
- Fetch error codes mapped to findings: `bot_blocked` (critical), `login_required` (critical), `empty_content` (high), `timeout` (high, with `latency_ms`), `target_http_error` + status (high), redirect chain to a different host (medium).
- robots.txt parsing (use `urllib.robotparser` + a manual pass for `User-agent` groups): check **GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-SearchBot, PerplexityBot, Google-Extended, Applebot-Extended, CCBot, Bingbot, Googlebot**. Finding per blocked bot with the exact matching rule line as evidence. Fix = exact robots.txt lines to add, with a note that blocking a training bot while allowing a search bot is a valid choice (say so; don't push one policy).
- `meta robots noindex/nosnippet`, `X-Robots-Tag` (raw HTTP). `nosnippet`/`max-snippet:0` limits snippets in search and AI answers.
- `llms.txt`: present or absent. **Low severity, and be honest** that it is an emerging convention and not a proven ranking factor.
- sitemap.xml present and contains the target URL (parse and check).

### 6.2 Extractability (AI can read it?)
- Rendered vs raw gap (Stage 1b).
- Main content detection: `include_selectors` result. Landmark presence (`main`, `article`, `h1`).
- **Boilerplate ratio:** extracted markdown vs main-only extraction; if > 50% of extracted text is nav/footer/cookie text, flag with the first 200 chars of junk as evidence.
- Hidden or interactive content: content inside `<details>`, tabs, accordions, `iframe_links` (embedded content AI never sees; evidence = iframe `src`).
- Images carrying text: `image_links` count vs `<img alt>` coverage; flag missing alt on content images.
- Text length sanity (thin content threshold with the actual word count shown).
- PDF/CSV/other content types: note extraction behavior.

### 6.3 Semantics
- Title: missing, too long (> ~60 chars), duplicate of H1 verbatim, brand-only. Description: missing, too short/long.
- Exactly one H1; heading hierarchy skips (h2 to h4) with the offending sequence as evidence.
- Canonical present and self-referential; conflicts with `final_url`.
- `<html lang>` vs detected language mismatch.
- JSON-LD: absent; present but wrong type for the page (Article vs Product vs FAQPage vs HowTo vs Organization); required properties missing (e.g. Article without `datePublished`/`author`; Product without `offers`). Validate with a small built-in checker (no external calls).
- OG/Twitter tags.
- Descriptive link text ("click here", "read more" counts with examples).
- Author + published/updated date visible and machine-readable.

### 6.4 SERP gap (needs Search)
- **Rank:** position for target query (or "not in top 20").
- **Indexation:** target absent from domain-restricted search while other pages appear = likely indexation problem.
- **Title rewrite:** compare SERP `title` to page `<title>` using `rapidfuzz`. Large divergence = the engine didn't trust the title; evidence shows both strings.
- **Snippet mismatch:** SERP snippet vs meta description vs first paragraph. If the snippet is pulled from boilerplate/nav, flag.
- **Competitor delta table:** for each feature (word count, #H2s, lists, tables, FAQ/schema type, date, author, query coverage in first 150 words, answer-first) show target vs competitor 1 to 3. Only call out features where the target is clearly worse.
- **Domain share:** how many of the top 10 are the target domain.

### 6.5 Answerability
- Query-term coverage in title, H1, first 150 words, and any H2.
- **Answer-first score:** does a concise definition/answer appear within the first 2 paragraphs? (heuristic: sentence containing query entity + copula/number within the first 120 words.)
- Best matching passage (highlights or BM25) and its score vs competitors' best passages.
- Structure that AI summarizers lift easily: lists, tables, definition blocks, Q&A headings.
- Freshness: published/updated date and its age relative to the freshest competitor.

---

## 7. The Gap Bridge (core differentiator; spend real time here)

`bridge.py` is a rule table linking each readability finding to the SERP symptom it plausibly causes, **only when both are present in this audit's evidence**. Output a "Gap Matrix": rows = AI-readability problems, columns = visibility symptoms, cells = evidence-backed links.

Example rules:

| Readability cause (observed via Fetch/raw HTTP) | Visibility symptom (observed via Search) | Bridge statement |
|---|---|---|
| Rendered text >> raw text (JS-only content) | Target missing from domain-restricted Search while other pages appear | "Your content only exists after JS. Search found N other pages on your domain but not this one." |
| Title in page differs a lot from SERP title | SERP title rewritten | "The engine replaced your title with X, which suggests your `<title>` didn't match page content." |
| Empty `highlights` / low BM25 for target query | Rank > 10 or absent while competitors answer it | "Competitors have passages that answer 'X'; your page has none." |
| No JSON-LD / wrong type | Competitors' SERP entries carry richer snippets (dates/ratings visible in snippet) | Show both snippets. |
| robots blocks AI search bots | N/A to rank, but AI-answer visibility = zero for that bot | Mark as AI-visibility loss, not Google rank (be precise). |
| Boilerplate-heavy extraction | SERP snippet pulled from nav/footer text | Show the snippet. |
| Thin content vs competitor word counts | Rank behind competitors with 3x content | Show the delta table. |

If a cause exists with no matching symptom (or vice versa), keep both findings but **do not draw a bridge**. Mark confidence `inferred` for any bridge not directly demonstrated.

---

## 8. Scoring

Two scores, each 0 to 100, with the component breakdown always visible (no black box):

**AI Readability Score (ARS)** = Access 25 + Extractability 25 + Semantics 25 + Answerability 25. Each component starts at max and subtracts per-finding penalties (critical -12, high -7, medium -3, low -1), floored at 0. If Fetch fully fails, ARS = 0 for Extractability/Semantics/Answerability and the report says "could not read".

**Search Visibility Score (SVS)** = Indexation 25 + Rank 35 + SERP presentation 20 + Competitive parity 20.
- Rank points: pos 1 = 35, 2 to 3 = 30, 4 to 10 = 20 (linear), 11 to 20 = 8, absent = 0.
- Indexation: target appears in domain-restricted search = 25; domain appears but not target = 8; nothing = 0.
- SERP presentation: title match + snippet quality.
- Parity: fraction of competitor features the target meets.

Show **"ARS vs SVS" side by side with the bridge lines** between them. When user gave no target query, SVS is labeled "based on derived query: ..." and the user can re-run with their own.

---

## 9. Optional Phase 6: Browser API (third endpoint, 200-pt tier)

Only build this if it yields a **finding class not reachable otherwise**. Candidate value:
- Open the page in a remote browser session (CDP) and capture: consent/cookie overlays covering content, content behind lazy-load/scroll, content hidden in tabs/accordions only revealed by interaction, and a screenshot for the "what a human sees vs what AI extracted" panel.
- Compare rendered-DOM text (post-interaction) vs Fetch extraction. Findings like "412 words exist only after clicking 'Read more'; Fetch extracted 0 of them."

**Decision gate (Day 9):** if after a working prototype it produces at least one distinct, reproducible finding on at least 2 demo pages, keep it and claim 3 endpoints. Otherwise delete it and submit as 2 endpoints (100 pts, still eligible for approval). The rules say padding doesn't qualify. Read `https://docs.tinyfish.ai/browser-api/reference.md` before building; watch credit usage (~500 free credits).

---

## 10. Skill packaging (submission type: Agentic App / Skill)

Ship **both**:
1. The web app + CLI (primary demo).
2. `skill/SKILL.md`: a Claude Skill that instructs an agent to run `citegap audit <url> --query "..." --format md` (or call the hosted API) and then summarize the top 5 fixes by effort/impact. Include: when to trigger ("audit this page for AI search / SEO"), required env var, command examples, how to read the output, and a rule to never fabricate findings if the CLI errors.

---

## 11. UI (web/)

Single page, fast, clear. No framework needed.

1. **Input:** URL + optional target query + "Audit" button.
2. **Live run panel (SSE):** stage list with spinners and a *TinyFish call log* ("Fetch #1 live, 2.1 s, 4,812 chars", "Search #2, 10 results"). Shows endpoint counts so judges see Search and Fetch (and Browser, if kept) in action.
3. **Result header:** ARS and SVS dials + component bars + one-sentence verdict.
4. **Gap Matrix** (hero section): causes to symptoms with evidence on hover/expand.
5. **"What AI sees" split view:** left = original page URL in a link; right = extracted markdown with lost content marked (e.g. nav boilerplate dimmed, missing sections listed).
6. **"How you appear in search":** a mock SERP card using the *real* returned title/snippet vs your page's title/meta; plus top 3 competitors.
7. **Competitor delta table.**
8. **Fix list:** sorted by (impact desc, effort asc); each fix has a copy button on its snippet; checkboxes.
9. **Download Fix Pack** (zip) and **Re-audit** button (shows score delta vs previous run for the same URL, stored in a small SQLite/JSON file). The re-audit delta powers the before/after demo.
10. Shareable report permalink (`/r/<id>`), read-only.

---

## 12. Build schedule (18 days)

| Days | Goal | Done when |
|---|---|---|
| 1 | Setup + docs read + TinyFish client | `client.py` with limiter, retry, call log; smoke test hits Search + Fetch live |
| 2 to 3 | Stage 1 + 1b (target Fetch, raw HTTP, SSRF guard) | Prints extracted vs raw comparison for 5 URLs |
| 4 to 5 | Stage 2 (Search probes, rank detection, URL normalization) | Correct rank detection on 5 known pages |
| 6 | Stage 3 + site files + competitors | Batched Fetch works; robots parser correct on tricky files |
| 7 | Stage 4 answerability (highlights + BM25 fallback) | Method label shown; both paths tested |
| 8 to 9 | Analyzers, evidence lint, Gap Bridge, scoring | Report JSON produced; lint drops evidence-less findings |
| 9 | **Decision gate: Browser API** | Keep or cut (Section 9) |
| 10 to 11 | FastAPI + SSE + UI | End-to-end in browser |
| 12 | Fix pack + snippets + optional LLM rewrite | Zip downloads; snippets validate |
| 13 | Robustness pass on 20 diverse URLs | No crashes; every error code yields a sensible report |
| 14 | Deploy + README + skill | Public URL live; README has "How TinyFish is used" |
| 15 | Demo pages + **before/after** on a real page you control | Re-audit delta captured |
| 16 | Record demo video (2 to 3 min) + screenshots | Uploaded |
| 17 | LinkedIn + X posts, Discord #showcase, submit | Submitted with buffer |
| 18 | Buffer / fixes | Do not start new features |

---

## 13. Demo set (required: "several real pages")

Audit at least 6 live pages that show different failure modes. Save the real outputs in `examples/`.

1. A **JS-rendered SPA** page (shows the rendered vs raw gap).
2. A **blog post** from a small site with weak titles/meta/schema.
3. A **documentation page** (strong structure; shows what good looks like).
4. An **e-commerce product page** (Product schema, offers).
5. A page that **blocks AI bots in robots.txt** or serves a bot challenge (shows `bot_blocked` handling).
6. **Your own page / DTU-related site, before and after fixes** (the winning story: apply the fix pack, re-audit, show ARS/SVS delta and any rank movement you can honestly observe; if rank doesn't move yet, say so and show only what changed).

Never audit pages that require login, and don't hammer any site (one audit = a handful of requests).

---

## 14. Submission checklist (from the rulebook + track)

- [ ] Working build link (public repo + live demo URL)
- [ ] Notes: what it does + **how TinyFish is used** (Search: which queries and why; Fetch: which calls and why; Browser if kept)
- [ ] Takes a URL and optional target query
- [ ] Uses Search **and** Fetch meaningfully
- [ ] Report covers: what AI tools can/can't read, visibility gaps, concrete fixes
- [ ] Demo on several real pages (Section 13)
- [ ] **LinkedIn post** tagging [TinyFish](https://www.linkedin.com/company/tinyfish-ai/)
- [ ] **X post** tagging TinyFish (the track lists both as required)
- [ ] Share in **#showcase** on the TinyFish Discord
- [ ] Original work, built for this bounty; no secrets in repo/demo; no padded API usage

**Post outline (LinkedIn/X):** hook with a real finding ("This page ranks #14 and AI tools can read 9% of it"), the Gap Matrix screenshot, 3-bullet how-it-works (Search to see the SERP, Fetch to see what AI extracts, bridge to connect them), the before/after delta, repo + demo link, tag TinyFish.

---

## 15. Definition of done

- Run `citegap audit <any public URL>` and get a report in under ~90 s, with no crash for any Fetch error code.
- Every finding has evidence; zero generic tips; every fix is paste-ready.
- The Gap Matrix contains at least one evidence-backed bridge on most real pages.
- The UI call log shows live Search and Fetch calls with `ttl: 0`.
- README explains TinyFish usage and includes the 6 real demo audits.
- Public demo URL works from a clean browser.

## 16. First actions for Claude Code

1. Read the three docs pages in Rule 7; write a 10-line summary of any differences from Section 2 into `DECISIONS.md`.
2. Scaffold the repo per Section 3.
3. Implement `tinyfish/client.py` (limiter, backoff on 429/503, call log) and a smoke test that does one live Search and one live Fetch (`ttl: 0`).
4. Ask the user to confirm the API key is in `.env` before running live calls.
5. Then proceed through Section 12 in order, committing after each stage.
