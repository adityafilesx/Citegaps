# CiteGap — AI Readability × Search Visibility

> Search shows how you rank. Fetch shows what AI can actually read. CiteGap connects the two and shows what to fix.

CiteGap audits a public web page using **TinyFish Search and Fetch**. Give it a URL and an optional target query to compare extracted content, raw HTML, search results, and competing pages. The report links readability problems to visibility symptoms when the collected evidence supports a connection.

The project includes a Python CLI, a FastAPI service, a vanilla JavaScript web interface, downloadable reports and fix packs, SQLite report history, and an agent skill. It was built for the **TinyFish × DTU SEO Page Auditor** bounty.

**Current status:** the core pipeline and HTTP API are covered by offline tests. The repository does not yet contain saved live demo audits or a published demo URL. Browser deep mode is implemented but experimental and has not been validated against the live Browser API. See [implementation decisions](DECISIONS.md) and [demo status](examples/README.md).

## Contents

- [What an audit produces](#what-an-audit-produces)
- [Quickstart](#quickstart)
- [CLI usage](#cli-usage)
- [Web interface](#web-interface)
- [Configuration](#configuration)
- [How an audit works](#how-an-audit-works)
- [How TinyFish is used](#how-tinyfish-is-used)
- [Findings and the Gap Bridge](#findings-and-the-gap-bridge)
- [Scoring](#scoring)
- [Reports, fix packs, and history](#reports-fix-packs-and-history)
- [HTTP API](#http-api)
- [Experimental deep mode](#experimental-deep-mode)
- [Development and testing](#development-and-testing)
- [Deployment](#deployment)
- [Security and operational behavior](#security-and-operational-behavior)
- [Limitations and troubleshooting](#limitations-and-troubleshooting)
- [Live demos and agent skill](#live-demos-and-agent-skill)
- [Project structure](#project-structure)

## What an audit produces

| Output | What it tells you |
|---|---|
| **AI Readability Score (ARS)** | Access, extractability, semantics, and answerability, with a component breakdown |
| **Search Visibility Score (SVS)** | Search discovery, rank, result presentation, and parity with competitors |
| **Gap Matrix / Gap Bridge** | Readability causes connected to visibility symptoms, with evidence and confidence labels |
| **What AI sees** | Extracted text, likely boilerplate, missing content signals, and raw versus rendered content sizes |
| **Search result card** | Returned title and snippet compared with the page title and meta description |
| **Competitor delta** | Content depth, headings, lists, tables, FAQ, structured data, dates, authorship, and query coverage |
| **Prioritized fixes** | Evidence, impact, concrete steps, estimated effort, and snippets where applicable |
| **Fix pack** | Markdown and JSON reports plus available snippets in a ZIP archive |
| **Re-audit delta** | Score and rank changes, resolved finding IDs, and newly detected finding IDs |
| **TinyFish call log** | Endpoint, purpose summary, timestamps, latency, status, and Fetch cache setting |

Audits use live TinyFish calls. Stored reports are historical results; starting a new audit does not replay them. Suggested fixes are for you to review and apply to your site.

## Quickstart

### Requirements

- **Python 3.11 or newer** and `pip`.
- A **TinyFish API key** with access to Search and Fetch.
- Network access to TinyFish services and the public URLs being audited.
- A writable directory for the SQLite database and exported reports.

Run these commands from the repository root. The frontend requires no Node.js installation or build step.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and copy the template with `Copy-Item .env.example .env`.

Edit `.env` and set your key:

```dotenv
TINYFISH_API_KEY=your_tinyfish_api_key
```

The CLI, API app factory, and live scripts load `.env` from the current working directory. Existing environment variables take precedence. `.env` is excluded from Git.

Check the installation without making live API calls:

```bash
citegap --help
python -m pytest -q
```

When your key is configured, verify one live Search and one live Fetch:

```bash
python scripts/smoke.py "https://www.tinyfish.ai/"
```

The smoke script searches for `web automation tools`, fetches the supplied URL, and prints result summaries and call logs. It consumes API usage.

Run your first audit or start the web app:

```bash
citegap audit "https://example.com/blog/post" --query "your target query"
citegap serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for the web interface. Replace the example URL and query with a public page and the search phrase you want to evaluate.

## CLI usage

### Audit and export

```bash
# Markdown report on stdout; progress on stderr
citegap audit "https://example.com/blog/post" --query "target query"

# Derive a query from the page's H1/title and frequent content terms
citegap audit "https://example.com/blog/post"

# JSON output suitable for another program
citegap audit "https://example.com/blog/post" -q "target query" --format json --quiet

# Write both report formats and a ZIP fix pack
citegap audit "https://example.com/blog/post" \
  --query "target query" --out ./audit-output --fixpack

# Save JSON through shell redirection
citegap audit "https://example.com/blog/post" --format json --quiet > report.json
```

| Option | Default | Behavior |
|---|---|---|
| `url` | Required | Public HTTP/HTTPS page; the CLI adds `https://` when the argument does not start with `http` |
| `--query`, `-q` | Derived | Target search phrase |
| `--format` (`md` or `json`) | `md` | Output format when printing to stdout |
| `--out DIRECTORY` | Unset | Creates the directory and writes both `report.md` and `report.json` |
| `--fixpack` | Off | Also writes `citegap-fixpack-<id>.zip` when `--out` is supplied |
| `--quiet` | Off | Suppresses stage and call progress |
| `--deep` | Off | Enables experimental remote-browser analysis |

`--fixpack` has no effect without `--out`. When `--out` is set, the report is written to disk instead of stdout, regardless of `--format`. Successful CLI audits are also saved to the configured SQLite database.

Exit codes are `0` for a completed audit, `1` for a handled audit/API or URL-validation error, and `2` for a missing TinyFish key or argument-parsing error. A completed report can still contain severe findings about an inaccessible page; completion does not mean the page passed.

The module entry point works too:

```bash
python -m citegap audit "https://example.com/blog/post" --query "target query"
```

### Run the server

```bash
citegap serve --host 127.0.0.1 --port 8000

# Equivalent application factory invocation
uvicorn citegap.api:app_factory --factory --host 127.0.0.1 --port 8000
```

`citegap serve` defaults to `0.0.0.0:8000`. Use `127.0.0.1` to bind locally.

## Web interface

1. Enter a public URL and, optionally, a target query.
2. Start the audit. The page displays stages and live TinyFish call updates through **Server-Sent Events (SSE)**.
3. Review scores, the Gap Matrix, extracted content, search presentation, competitor comparison, and fixes.
4. Copy relevant snippets or download the Markdown report and ZIP fix pack.
5. Apply changes to your site, then select **Re-audit** to compare the next run with saved history.

Completed reports have a permalink at `/r/<id>`. The browser UI uses the same HTTP API documented below. Deep mode is available through an explicitly marked checkbox.

## Configuration

These environment variables are read by `load_settings()` in [config.py](src/citegap/config.py):

| Variable | Default | Purpose |
|---|---|---|
| `TINYFISH_API_KEY` | Empty | Required for live audits; shared by Search, Fetch, and optional Browser calls |
| `ANTHROPIC_API_KEY` | Empty | Optional rewrite suggestions during fix-pack generation |
| `CITEGAP_SEARCH_RPM` | `5` | Search token-bucket refill rate, in requests per minute |
| `CITEGAP_FETCH_UPM` | `150` | Fetch token-bucket refill rate, in URLs per minute |
| `CITEGAP_AUDITS_PER_HOUR` | `10` | API audit-start limit per client IP, including re-audits |
| `CITEGAP_DB` | `citegap.db` | SQLite database path, relative to the working directory unless absolute |

Numeric environment settings are clamped to at least `1`; invalid integer values fall back to their defaults. The API also has a **3 audits/minute/IP** default in `Settings`, without an environment override. Create the parent directory before selecting a database path inside a new directory.

Additional settings are available programmatically through the `Settings` dataclass, including endpoint URLs, timeouts, retry count, analysis thresholds, competitor count, and the optional LLM model. These are not all environment-configurable. `PORT` is used by the Docker startup command; select a local CLI port with `--port`.

The normal audit pipeline, findings, bridges, scores, and deterministic snippets work without an Anthropic key. With a key, fix-pack generation attempts title, meta-description, and answer-paragraph rewrites from report facts. Failed rewrite requests are skipped. The model identifier is defined in `Settings.llm_model`.

## How an audit works

```text
Public URL + optional query
          |
          v
Validate URL and resolved addresses
          |
          v
Target: TinyFish Markdown + HTML + main-content Fetches
        and an independent raw HTTP GET
          |
          v
Search probes + site-file Fetch
          |
          v
Select and fetch up to three competitors
          |
          v
Answerability: Fetch highlights or local BM25 passages
          |
          v
Deterministic analyzers + optional browser deep analysis
          |
          v
Evidence lint -> Gap Bridges -> ARS/SVS -> Report
          |
          v
SQLite history + UI / Markdown / JSON / ZIP
```

The pipeline is implemented in [pipeline.py](src/citegap/pipeline.py). Independent target requests run concurrently. Search probes and site-file collection also run concurrently.

The raw HTTP request reads initial HTML without executing JavaScript. It supplies metadata and JSON-LD that TinyFish's cleaned extraction may omit, and supports comparison with rendered content. Competitors receive raw GETs for schema and date information too. A raw GET can also recover robots.txt when Fetch fails or returns text without recognizable rules.

When no query is supplied, CiteGap uses the H1 or title, removes a likely brand suffix, trims long phrases, and extends short phrases with frequent content terms. If page text is unavailable, it falls back to the URL slug or hostname. Derived queries are labeled in the report.

Target-page retrieval failures such as bot blocking or a login wall can produce access findings while search analysis continues. Target Fetch request failures for authentication, billing, permissions, or exhausted rate limits are treated as API problems, rather than evidence about the page. Failed Search probes are recorded, and unavailable score components are handled separately.

## How TinyFish is used

The client uses asynchronous `httpx` requests with an `X-API-Key` header. Endpoint URLs below are the defaults configured in this repository.

| Service | Request | Role |
|---|---|---|
| Search | `GET https://api.search.tinyfish.ai` | Rank, discovery probes, returned titles/snippets, and competitor selection |
| Fetch | `POST https://api.fetch.tinyfish.ai` | Target and competitor extraction, structure checks, site files, and answer passages |
| Browser, opt-in | `POST https://api.browser.tinyfish.ai`; session deletion afterward | Remote Chromium interaction through CDP for deep-mode analysis |

### Calls within an audit

| Call | Input / condition | Evidence or score input |
|---|---|---|
| Target Markdown Fetch | URL with link, image, and iframe inventories | Extracted text, metadata, final URL, and retrieval errors |
| Target HTML Fetch | Same URL, `format: html` | Headings, landmarks, image alt text, and link text |
| Main-content Fetch | Include `main`, `article`; exclude `nav`, `footer`, `aside` | Main-content isolation, boilerplate share, unmatched selectors, and candidate selectors |
| Target-query Search | Page `0`; page `1` only if no target match is found | Rank and competing results |
| Domain-restricted Search | Same query with `include_domains` | Whether this page or other pages from its domain surface |
| Quoted-title Search | Quoted core title, if available; brand segment removed and length capped | Another discovery check and a possible target result card |
| Question Search | H1 converted to a question for answer-like pages | Domain presence for a conversational phrasing |
| Site-file Fetch | One batch: `/robots.txt`, `/llms.txt`, `/sitemap.xml` | Per-bot access rules, file presence, and sitemap coverage |
| Competitor Fetch | One batch of up to three selected results | Comparable page features and retrieval errors |
| Highlights Fetch | Target plus selected competitors, when the target was readable and competitors were selected | Query-answer passages; falls back to local BM25 if unavailable |
| Browser session | Only when deep mode is requested and the target was readable | Interaction-only content, overlays, and a load screenshot |

**Every Fetch is forced to `ttl: 0` by the client**, including batches and highlights. The Fetch wrapper splits larger inputs into batches of at most ten URLs. Search includes a purpose and passes language/region hints when available from the page.

The configured Search budget is six logical calls per audit; the current collector normally makes two to five, depending on available page metadata and whether page `1` is needed. A full ordinary audit with competitors and highlights makes six logical Fetch requests. Retries can increase HTTP attempts and usage.

The client retries transient HTTP `429`, `502`, `503`, and `504` responses, timeouts, and network failures, with up to three retries by default. Fetch has a 150-second client timeout; target and competitor extraction request a 60-second per-URL budget, while site files request 30 seconds. Call-log latency includes limiter waits and retries.

Competitors are the first eligible non-target-site results, deduplicated by URL and site label. They may include aggregators and PDFs, and are not guaranteed to all outrank the target when the target already ranks highly.

## Findings and the Gap Bridge

The analyzers cover five categories:

| Category | Examples of implemented checks |
|---|---|
| Access | Fetch failures, raw HTTP errors, slow extraction, off-host redirects, `noindex`, snippet restrictions, robots rules, missing site files |
| Extractability | JavaScript dependency, missing main landmarks, boilerplate, iframe content, images without alt text, thin content, PDF limitations |
| Semantics | Title and description checks, H1 and heading hierarchy, canonical tags, language, JSON-LD types/properties, Open Graph metadata, generic links, authorship/dates |
| Answerability | Query coverage, best passage versus competitors, answer-first structure, lists/tables/Q&A, and freshness comparisons |
| Search visibility | Missing/low rank, discovery gaps, title rewrites, boilerplate snippets, question-query absence, and competitor differences |

Each retained finding includes an ID, category, severity, confidence, concrete evidence, AI/search impact, and actionable fix steps. Snippets, paste locations, and estimated effort are supplied where appropriate. The lint step drops empty evidence, missing or overly short fix steps, generic advice, and duplicate IDs; dropped items are recorded in the JSON report.

The **Gap Bridge** connects findings using explicit rules. For example:

- A large rendered-versus-raw gap plus a domain search that finds other pages but misses this page supports an **inferred** JavaScript/indexation connection.
- A problematic title plus a different returned search title produces an **observed** title/presentation bridge.
- Missing answer passages plus weak rank supports an **inferred** answerability/rank connection.
- A robots rule blocking an AI search/user bot produces an **observed** bridge to the virtual `AI_ANSWER_VISIBILITY` symptom, rather than to Google rank.

`observed` and `inferred` are the implementation's confidence labels. They do not establish that a particular fix will improve ranking. A report may have valid findings and no bridges when the necessary paired evidence is absent.

## Scoring

Both scores are deterministic heuristics on a **0–100** scale. Their implementation is in [scoring.py](src/citegap/analyze/scoring.py).

### AI Readability Score (ARS)

| Component | Maximum |
|---|---:|
| Access | 25 |
| Extractability | 25 |
| Semantics | 25 |
| Answerability | 25 |

Each component starts at 25 and subtracts penalties for retained findings in that category: **critical: 12**, **high: 7**, **medium: 3**, **low: 1**. Components are floored at zero, then summed. Search-category findings do not directly subtract from ARS.

If the target Markdown extraction is missing or empty, extractability, semantics, and answerability receive zero with a “could not read” note. Access still uses its finding penalties, so the total is not necessarily zero.

### Search Visibility Score (SVS)

| Component | Maximum | Calculation |
|---|---:|---|
| Indexation/discovery | 25 | `indexed`: 25; `partial`: 8; `none`: 0 |
| Rank | 35 | #1: 35; #2–3: 30; #4–10: 26, 24, 22, 20, 18, 16, 14; #11–20: 8; absent: 0 |
| Search presentation | 20 | Up to 10 for title similarity and 10 for snippet quality |
| Competitive parity | 20 | `20 × acceptable feature rows / measurable feature rows` |

Title-similarity thresholds award 10 points at 80+, 7 at 60+, 4 at 40+, and 1 below 40. Snippets receive 3 points when flagged as boilerplate, 10 when at least 60 characters long, and 5 otherwise. When title similarity is unavailable for a returned target entry, the scorer uses a fallback value of 50.

Competitive parity reflects the delta table's thresholds. For example, numeric features are generally marked worse when the target is below half the competitor median; an acceptable row does not necessarily mean the target equals or exceeds every competitor.

A failed probe or unavailable competitor comparison is excluded from the measurable maximum, and SVS is rescaled to 100 with a visible note. Successful search that omits the target can earn zero rank points. Discovery labels are based on Search probes, including a quoted-title match; they are not authoritative search-engine index states.

## Reports, fix packs, and history

### Exported files

Using `--out ./audit-output --fixpack` creates:

```text
audit-output/
├── report.md
├── report.json
└── citegap-fixpack-<id>.zip
```

The ZIP contains:

```text
README.txt
report.md
report.json
snippets/
    <priority>_<finding-id>.<extension>
    llm_suggestions.md                 # only if optional rewrites succeeded
```

Only findings with a snippet generate snippet files. Some fixes require server, CDN, rendering, or content changes described in their steps. Snippets can include placeholders and must be reviewed against your actual content and templates.

The JSON report includes `ars`, `svs`, `findings`, `bridges`, `target`, `competitors`, `serp`, `delta_table`, `what_ai_sees`, `serp_card`, `calls`, `endpoints_used`, `notes`, `lint_dropped`, and optional `previous`/`extras` fields. The complete models are in [report/model.py](src/citegap/report/model.py).

Fixes are sorted by severity, then whether they have bridges, then estimated effort. Optional LLM suggestions are generated at ZIP-export time and are not required to produce the underlying report.

### Persistence and comparisons

[store.py](src/citegap/store.py) stores full completed reports as JSON in SQLite and indexes normalized URLs. CLI audits, API audits, and the demo script share history when they use the same database path.

A new audit compares against the latest saved report for the **normalized URL**. URL normalization removes common tracking parameters, fragments, `www`, default ports, and trailing slashes, and treats HTTP/HTTPS variants alike. History is not keyed by query, so compare runs with the same query for meaningful deltas.

The re-audit API preserves an explicit query and re-derives a previously derived query. It starts a standard audit and does **not** preserve the earlier deep-mode flag. Deltas include ARS/SVS differences, previous/current rank, and finding IDs that disappeared or appeared; disappearance alone does not prove a fix caused the change.

Completed reports survive restarts if the database survives. Running jobs and their detailed SSE event history are held in memory. After a restart, an SSE request for a saved report emits a “Report ready” event.

## HTTP API

The FastAPI application exposes interactive documentation at `/docs` and its schema at `/openapi.json`.

| Method | Path | Response / purpose |
|---|---|---|
| `GET` | `/healthz` | App health and masked key-configuration status |
| `POST` | `/audit` | Start an audit from `{ "url": "...", "query": "...", "deep": false }`; returns `{ "id": "..." }` |
| `GET` | `/audit/{id}/events` | SSE progress and TinyFish call updates |
| `GET` | `/audit/{id}` | Completed report JSON or running/failed status |
| `GET` | `/audit/{id}/report.md` | Completed Markdown report |
| `GET` | `/audit/{id}/fixpack.zip` | ZIP export, optionally including LLM suggestions |
| `POST` | `/audit/{id}/reaudit` | Start another audit from the saved report; returns a new ID |
| `GET` | `/audits` | Summaries of the 20 most recently saved reports |
| `GET` | `/r/{id}` | Browser report view |
| `GET` | `/` | Web interface |

### Request sequence

With the server running locally:

```bash
# 1. Start an audit and copy the returned id
curl -sS -X POST http://127.0.0.1:8000/audit \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/blog/post","query":"target query"}'

# 2. Replace AUDIT_ID with that id and stream progress
curl -N http://127.0.0.1:8000/audit/AUDIT_ID/events

# 3. Read the completed report
curl -sS http://127.0.0.1:8000/audit/AUDIT_ID

# 4. Download exports after completion
curl -sS -o report.md http://127.0.0.1:8000/audit/AUDIT_ID/report.md
curl -sS -o fixpack.zip http://127.0.0.1:8000/audit/AUDIT_ID/fixpack.zip

# 5. Start a re-audit; this returns a new id
curl -sS -X POST http://127.0.0.1:8000/audit/AUDIT_ID/reaudit
```

Progress events use `data: <JSON>` frames. Stage updates carry `stage` and `message`; call updates additionally carry `tinyfish_call`. The API emits `stage: "report"` with `report_id` after saving the report, or `stage: "error"` on failure. The pipeline's earlier `done` event is a scoring-completion update; use `report` as the signal to download results.

Starting an audit returns immediately with HTTP `200`; completion is asynchronous. `GET /audit/{id}` returns `{ "status": "running", "error": null }` while running. Failed jobs return HTTP `500` with status/error information.

Other relevant responses are `400` for rejected URLs, `422` for invalid request bodies, `503` when the server lacks a TinyFish key, `404` for unknown audits or exports without a saved report, and `429` with `Retry-After` when the audit-start limiter is exceeded. `/healthz` checks configuration, not live TinyFish connectivity or key validity.

## Experimental deep mode

Deep mode uses the TinyFish Browser API and Playwright to connect to remote Chromium over CDP. It records initial body text and a screenshot, scrolls the page, clicks expandable sections/tabs, and compares newly revealed text with Fetch extraction. It can add `EXTRACT_INTERACTION_ONLY_CONTENT` and `EXTRACT_CONSENT_OVERLAY` findings.

```bash
python -m pip install -e ".[deep]"
citegap audit "https://example.com/blog/post" --query "target query" --deep
```

The browser is remote; this driver connects to it instead of launching local Chromium. Deep mode is off by default, uses TinyFish credits, and attempts session cleanup after analysis. The report records Browser calls and stores a successful screenshot in `extras.screenshot_jpeg_b64`. Expected deep-mode errors become report notes.

The deep-mode tests use an injected driver. **Live Browser behavior remains unvalidated**, and the project currently claims the two core integrations, Search and Fetch. The supplied Docker image installs the base dependencies only; enabling deep mode there requires installing the `deep` extra too. See [DECISIONS.md](DECISIONS.md).

## Development and testing

```bash
python -m pip install -e ".[dev]"
python -m pytest -q

# Run a focused area
python -m pytest tests/test_pipeline.py tests/test_api.py -q
```

Tests use mock HTTP transports, fixtures, and fake browser drivers from `tests/`. They require no live key and do not consume API usage. Coverage includes batching and forced `ttl: 0`, retries, URL normalization, SSRF checks and redirect validation, robots precedence, parser/scorer behavior, evidence lint, bridge conditions, highlights fallback, pipeline error handling, API/SSE flows, exports, rate limits, and optional browser behavior.

To inspect the web UI with test fixtures:

```bash
python scripts/dev_preview_server.py
```

Open `http://127.0.0.1:8791`. This is a **test-only preview** using `tests/` doubles and `/tmp/citegap_preview.db`; its results are not live audits. The production CLI and server do not use this preview mode.

For changes, keep fixtures in `tests/`, preserve forced live Fetches, add concrete evidence and actionable steps to findings, and label uncertain bridge relationships. See [CLAUDE.md](CLAUDE.md) for the original specification, [BUILD_GUIDE.md](BUILD_GUIDE.md) for the phased build process, and [DECISIONS.md](DECISIONS.md) for implementation differences.

## Deployment

### Docker

From the repository root, with `.env` configured:

```bash
docker build -t citegap .
docker run --name citegap --rm \
  -p 8000:8000 \
  --env-file .env \
  -e CITEGAP_DB=/data/citegap.db \
  -v citegap-data:/data \
  citegap
```

The image uses Python 3.11, copies the Python source and `web/`, installs the package in editable mode, and starts the Uvicorn app factory. Its default port is 8000, configurable through `PORT`; update the port mapping when changing it. The named volume preserves SQLite reports when the container is recreated. `.env` is excluded from the build context and keys are supplied at runtime.

### Render

[render.yaml](render.yaml) defines a Docker web service with `/healthz` as the health-check path and a disk mounted at `/data`. Create the service from this blueprint, supply `TINYFISH_API_KEY` through platform settings, and optionally supply `ANTHROPIC_API_KEY`. The Docker image defaults `CITEGAP_DB` to `/data/citegap.db`.

The blueprint specifies a `starter` plan and a 1 GB disk. No deployed public instance is linked in this repository.

### Other hosts

Run from a checkout containing both `src/` and `web/`, install with `python -m pip install -e .`, and start:

```bash
uvicorn citegap.api:app_factory --factory --host 0.0.0.0 --port 8000
```

Configure runtime keys and persistent database storage. The current packaging configuration discovers Python packages but does not bundle `web/` as package data, so a standalone wheel installation is insufficient for the web interface. The checkout and Docker workflows retain those assets.

Use a single application worker for this implementation: running jobs, event streams, and API rate-limit state are process-local. Multiple workers need shared job coordination to route progress requests reliably. Configure a reverse proxy to allow SSE streams and avoid response buffering.

## Security and operational behavior

- URL validation permits HTTP/HTTPS and rejects embedded credentials, internal hostnames, and non-public resolved addresses.
- The raw fetcher validates DNS answers on every redirect hop, connects to a validated IP with the original Host/TLS name, limits redirects to five, caps retained bodies at 3 MiB, and uses a 10-second timeout and `CiteGapAuditor/1.0` user agent.
- API keys come from the environment. Client representations and health output mask them; normal call summaries do not contain the key.
- Page-derived UI strings are inserted with `textContent`, rather than interpreted as HTML.
- Audit starts and re-audits are rate-limited per client IP. The implementation takes the first `X-Forwarded-For` value when present; a public proxy should control that header.
- TinyFish request limiters belong to each client, and API audit-start limits belong to each app process. Concurrent audits do not share an account-wide TinyFish limiter.
- The app has no built-in user authentication or report ownership checks. Recent report summaries, report URLs, extracted content, and exports are accessible to anyone who can reach the service. Use access controls at the hosting layer if reports should be private.

## Limitations and troubleshooting

### Interpretation limits

- Search results are a snapshot for the query, language, region hints, and audit time. Absence is not definitive proof that a page is unindexed; verify index status using the relevant webmaster tools.
- The collector checks at most two target-query result pages. It does not track rankings continuously or audit an entire site.
- ARS/SVS, page type, boilerplate, query coverage, and answer-first checks are heuristics. An ARS of 80 is not a measurement that an AI can read 80% of a page.
- Highlights may be unavailable for an account or omitted for a content type. BM25 is a lexical fallback and is explicitly labeled.
- `/sitemap.xml` is checked at the default location. Sitemap indexes are recognized but their children are not recursively fetched; target coverage is unknown for an index.
- JSON-LD checks inspect raw HTML and selected expected properties. They do not establish search-engine rich-result eligibility. If raw HTML cannot be read, schema comparison may be unavailable.
- Training-bot restrictions can be intentional. AI search-bot restrictions and Google/Bing crawler restrictions have different consequences.
- The report treats `llms.txt` as an optional convention with low-severity findings and no established rank effect within its analysis.
- Live run time depends on upstream responses, retries, limiter waits, and deep mode. The build guide's roughly 90-second target is not a measured guarantee.
- Offline tests do not establish that a live deployment, Browser API session, or before/after ranking improvement has been validated.

### Common problems

| Symptom | What to check |
|---|---|
| `citegap: command not found` | Activate the virtual environment and install from the root with `python -m pip install -e .`, or use `python -m citegap` |
| `TINYFISH_API_KEY is not set` | Set the variable or edit `.env` in the working directory; an existing environment variable overrides `.env` |
| API returns `503` when starting an audit | Configure the server's key and restart the process |
| TinyFish API problem (`401`, `402`, `403`, `429`) | Check authentication, billing/quota, permissions, and account limits; these errors do not justify page findings |
| `URL rejected` | Supply a publicly resolvable HTTP/HTTPS URL without credentials; localhost/private addresses are deliberately rejected |
| API returns `429` | Wait for `Retry-After`; inspect the configured hourly limit and the per-minute default |
| Highlights fall back to BM25 | Review `answerability_method` and report notes; core auditing still works |
| No bridges appear | Check that both a readability finding and its matching visibility evidence exist |
| SQLite cannot open the database | Create the parent directory and ensure it is writable; mount `/data` for persistent containers |
| Report/export returns `404` | Wait for the SSE `report` event and verify the audit ID; failed jobs have no completed export |
| SSE progress fails behind a proxy or multiple workers | Disable stream buffering and use one worker; in-memory jobs are not shared |
| Deep mode notes missing Playwright | Install `.[deep]` in the server environment; the base Docker image does not include it |
| Web UI files are missing after package installation | Run from an editable repository checkout or the supplied Docker image, which retain `web/` |

## Live demos and agent skill

### Generate real demo audits

Saved examples have not yet been generated. The demo script expects six real public URLs covering a SPA, a weak blog post, documentation, a product page, a bot-blocking page, and a page you control.

```bash
cp scripts/demo_urls.example.json scripts/demo_urls.json
# Replace every placeholder URL and set relevant queries in demo_urls.json
python scripts/demo_set.py
```

With a TinyFish key, the script runs live audits sequentially, saves Markdown/JSON reports to `examples/<label-slug>/`, writes `examples/INDEX.md`, and stores successful runs in SQLite. It pauses 20 seconds between successful audits and records failures in the index. Generated examples are documentation artifacts; the product does not read them.

For a before/after comparison, audit a page you control with a fixed query, apply the selected fixes, and run another audit against the same database. Record observed score and rank changes, including unchanged rank. [docs/POSTS.md](docs/POSTS.md) contains launch-post drafts awaiting real results.

### Agent integration

[skill/SKILL.md](skill/SKILL.md) provides an agent workflow for requests such as “audit this page for AI search,” “why doesn't AI cite my page,” or “check what AI can read on this URL.” It explains requirements, CLI/API usage, score interpretation, and how to summarize prioritized fixes.

The skill requires agents to report errors and avoid inventing findings, scores, or ranks. It wraps the same installed CLI and live API rather than providing a separate audit implementation.

## Project structure

```text
.
├── README.md                  # Setup, usage, architecture, and operational reference
├── CLAUDE.md                  # Original product specification and build rules
├── BUILD_GUIDE.md             # Phased implementation plan and validation gates
├── DECISIONS.md               # Implementation differences and validation status
├── pyproject.toml             # Package metadata, dependencies, extras, and CLI entry point
├── .env.example               # Environment configuration template
├── Dockerfile                 # Container image and server command
├── render.yaml                # Render service and persistent-disk configuration
├── src/citegap/
│   ├── config.py              # Environment loader, settings, bot list, thresholds
│   ├── cli.py                 # audit and serve commands
│   ├── api.py                 # FastAPI routes, jobs, SSE, rate limiting, and static UI
│   ├── pipeline.py            # Collection, analysis, scoring, and report orchestration
│   ├── store.py               # SQLite persistence and prior-report lookup
│   ├── util.py                # URL normalization, host validation, and text helpers
│   ├── tinyfish/              # Async client, retries, call logs, Search/Fetch wrappers
│   ├── collect/               # Target, raw HTML, SERP, competitors, site files, browser
│   ├── analyze/               # Features, findings, lint, bridges, and score calculations
│   ├── fixes/                 # Deterministic snippets and optional LLM rewrites
│   └── report/                # Pydantic models, Markdown rendering, ZIP generation
├── web/                       # HTML, CSS, and JavaScript frontend
├── tests/                     # Offline fixtures, mocks, and automated tests
├── scripts/
│   ├── smoke.py               # One live Search + one live Fetch
│   ├── demo_set.py            # Live demo-audit export script
│   ├── demo_urls.example.json # Six-page demo configuration template
│   └── dev_preview_server.py  # Test-fixture UI preview
├── skill/SKILL.md              # Agent workflow wrapping the CLI/API
├── examples/README.md         # Saved live audit status and generation instructions
└── docs/POSTS.md               # Launch-post drafts
```
