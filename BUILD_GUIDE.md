# CiteGap Build Guide (for Claude Code as executor)

Source of truth: `CLAUDE.md`. If this guide and CLAUDE.md conflict, CLAUDE.md wins, and the TinyFish docs win over both (Rule 7). Log every deviation in `DECISIONS.md`.

## How to use this guide

1. Work one phase at a time, in order. Never start a phase before the previous gate passes.
2. Paste the phase's **Prompt** into Claude Code. Claude Code does the work, then runs the **Gate** commands and reports actual output.
3. The human reviews the gate output and replies "go" before the next phase. Claude Code must not self-advance.
4. Commit at the end of each phase: `git commit -m "phase N: <name>"`.
5. Standing rules in every phase (CLAUDE.md Section 0): no canned data in the product path, `ttl: 0` on every Fetch, every finding has evidence, no keys in git, no padded endpoint calls.

Standing preamble (prepend to every prompt):

> Read CLAUDE.md Section 0 and the section(s) named below. Follow the rules strictly. Do only this phase. When done, run the gate checks, show real output, list any deviations for DECISIONS.md, then stop and wait for "go".

---

## Phase 0: Preflight (Day 1, before any code)

**Human does:**
- Get a TinyFish API key (`agent.tinyfish.ai/api-keys`). Put it in `.env` as `TINYFISH_API_KEY=...`. Optional: `ANTHROPIC_API_KEY`.
- `git init`; add `.env` to `.gitignore`.
- Python 3.11 available (`python3.11 --version`).

**Prompt:**
> Read CLAUDE.md Sections 0, 2, 16. Fetch and read `https://docs.tinyfish.ai/for-coding-agents.md`, `.../search-api/reference.md`, `.../fetch-api/reference.md`. Write `DECISIONS.md` with a ~10-line summary of every difference from CLAUDE.md Section 2 (params, limits, error codes, response shape). Update CLAUDE.md Section 2 where docs differ. Write no code.

**Gate:** `DECISIONS.md` exists; differences are listed, or "none found" is stated with the doc URLs checked.

---

## Phase 1: Scaffold + TinyFish client (Day 1)

**Prompt:**
> Sections 3, 2. Scaffold the repo tree from Section 3 (empty modules with docstrings are fine), `pyproject.toml` (Python 3.11; fastapi, uvicorn, httpx, selectolax, pydantic>=2, rapidfuzz, rank-bm25, pytest, pytest-asyncio, respx), `.env.example`, `.gitignore`, `config.py` (env loading, search limit default 5/min configurable, AI-bot list, thresholds). Implement `tinyfish/client.py`: async httpx client, `X-API-Key` header, token-bucket limiter, retry with backoff on 429/503, client timeout >= 150 s, call log entries `{id, endpoint, params_summary, ttl, started_at, latency_ms, status}`, API key never logged. Implement `search.py` and `fetch.py` (batching to 10 URLs, error normalization into typed objects, `ttl=0` forced). Unit tests with `respx` mocks for limiter, backoff, batching, error normalization. Do NOT make live calls yet; ask me to confirm `.env` first.

**Gate:** `pytest -q` passes. Then, after the human confirms the key: one live Search and one live Fetch (`ttl: 0`) smoke script prints results and the call log.

---

## Phase 2: Stage 1 + 1b, target Fetch and raw HTTP (Days 2-3)

**Prompt:**
> Section 4 Stage 1 and 1b, Section 6.2. Implement `collect/target.py` (three Fetches: markdown+links+images+iframes; html; include/exclude selectors with `selector_not_matched` + `candidate_selectors` stored). A Fetch error must be recorded and must NOT abort the run. Implement `collect/raw_http.py` with the SSRF guard (reject private/loopback/link-local, resolve DNS and re-check after each redirect, 3 MB cap, 10 s timeout, UA `CiteGapAuditor/1.0`) and a parser for title, meta, canonical, robots meta, X-Robots-Tag, og/twitter, hreflang, html lang, JSON-LD, headings, noscript, visible text length. Compute the rendered-vs-raw gap. Pydantic models in `report/model.py` (Finding, Evidence, Fix, CallLogEntry, Report). Tests use fixtures from `tests/` only. Add a script that prints extracted-vs-raw for a list of URLs.

**Gate:** tests pass (include SSRF tests: `127.0.0.1`, `169.254.169.254`, redirect-to-private, DNS rebinding case). The script runs on 5 real URLs, including one JS-heavy page and one blocked or login page, with no crash.

---

## Phase 3: Stage 2, Search probes (Days 4-5)

**Prompt:**
> Section 4 Stage 2, Section 6.4. Implement `collect/serp.py`: derive the query when none is given (H1/title + TF-IDF keyphrases), target-query search (page 0, page 1 only if the target is missing), domain-restricted indexation probe, exact-title probe, optional question probe. Max 4-6 Search calls per audit, `purpose` always set, `location`/`language` from `<html lang>`. URL normalization (strip tracking params, trailing slash, `www`) with rank detection. Remove any probe that doesn't feed a finding or score.

**Gate:** rank detection correct on 5 known pages (include one that's not in the top 20). Normalization unit tests pass. The call log shows <= 6 Search calls per audit.

---

## Phase 4: Stage 3, competitors and site files (Day 6)

**Prompt:**
> Section 4 Stage 3, Sections 6.1, 6.4. Implement `collect/competitors.py` (top 3 non-target-domain organic results, ONE batched Fetch, `ttl=0`), `collect/site_files.py` (ONE batched Fetch for robots.txt, llms.txt, sitemap.xml; tolerate `page_not_found`), the robots.txt parser covering the bot list in Section 6.1 with the exact matching rule line as evidence (test tricky files: multiple UA groups, wildcards, Allow/Disallow precedence, empty Disallow), sitemap contains-target check, and the competitor feature vector.

**Gate:** parser tests pass on tricky fixtures. A live run shows exactly 2 batched Fetch calls for this stage.

---

## Phase 5: Stage 4, answerability (Day 7)

**Prompt:**
> Section 4 Stage 4, Section 6.5. Implement `collect/answerability.py`: try Fetch `highlights`; on 403/unavailable fall back to local BM25 over paragraph chunks. Record which method ran (`highlights` | `bm25`) in the report. Implement `analyze/answerability.py` (query coverage in title/H1/first 150 words/H2, answer-first heuristic, structure signals, freshness vs competitors).

**Gate:** both paths tested (mock the 403 for the fallback). The method label is present in the report JSON.

---

## Phase 6: Analyzers, lint, bridge, scoring (Days 8-9)

**Prompt:**
> Sections 5, 6, 7, 8. Implement `access.py`, `extractability.py`, `semantics.py`, `serp_gap.py`, `lint.py` (drop findings with empty evidence or generic fix steps; deny-list from Section 5), `bridge.py` (rule table from Section 7; draw a bridge ONLY when both sides are in this audit's evidence; mark `inferred` when not directly demonstrated), `scoring.py` (ARS and SVS exactly per Section 8, component breakdown visible; Fetch full failure gives ARS 0 for three components with a "could not read" note). `pipeline.py` orchestrates the stages and emits `{stage, message, tinyfish_call?}` events. Produce report JSON.

**Gate:** lint test proves an evidence-less finding is dropped. Bridge tests prove no bridge is drawn when one side is missing. A full audit of one real URL produces report JSON, with both scores and at least one bridge on a suitable page.

**Decision gate (Day 9): Browser API.** Read `browser-api/reference.md`. Build only if it can yield a finding class that Search and Fetch cannot reach (Section 9), on >= 2 demo pages. Otherwise cut it and claim 2 endpoints. Record the decision in DECISIONS.md.

---

## Phase 7: API + UI (Days 10-11)

**Prompt:**
> Sections 3, 11. Implement `api.py` (POST /audit, GET /audit/{id}/events via SSE, GET /audit/{id}, per-IP rate limit, permalink /r/<id>) and `cli.py` (`citegap audit <url> --query "..." --format md|json`). Build `web/` as vanilla JS + SSE: input, live call log, ARS/SVS dials with component bars, Gap Matrix hero, what-AI-sees split view, mock SERP card with real returned title/snippet, competitor delta table, sorted fix list with copy buttons. Store reports in SQLite/JSON for permalinks and re-audit deltas.

**Gate:** end-to-end in a browser on one real URL. The call log shows live Search and Fetch with `ttl: 0`. Rate limit returns 429 on a burst.

---

## Phase 8: Fix pack + snippets (Day 12)

**Prompt:**
> Sections 3, 5. Implement `fixes/snippets.py` (deterministic: title/meta rewrite, JSON-LD, robots.txt lines, heading/answer block), optional `llm_rewrite.py` (only if `ANTHROPIC_API_KEY` is set; the app works without it), `report/render_md.py`, `report/fixpack.py` (zip with report.md, report.json, snippets/*). Re-audit endpoint with score delta.

**Gate:** zip downloads; JSON-LD snippets parse as valid JSON; the re-audit delta renders.

---

## Phase 9: Robustness (Day 13)

**Prompt:**
> Section 13, Definition of Done in Section 15. Run the pipeline on 20 diverse public URLs (SPA, PDF, 404, redirect chain, bot-blocked, login wall, huge page, non-English, timeout). Fix every crash. Every Fetch error code must produce a sensible report with a finding, not an exception. Don't hammer any site.

**Gate:** table of 20 URLs, outcome and runtime for each. No crashes. Typical audit under ~90 s.

---

## Phase 10: Deploy + README + Skill (Day 14)

**Prompt:**
> Sections 10, 14. Deploy config for Render/Fly/Railway (env vars only for keys). Write `README.md` (what/why, a "How TinyFish is used" section naming each Search/Fetch/Browser call and why, setup, demo links). Write `skill/SKILL.md` (trigger phrases, env var, CLI examples, how to read output, a rule to never fabricate findings if the CLI errors).

**Gate:** the public URL works from a clean browser; `git grep -i "api_key"` shows no secrets in the repo.

---

## Phase 11: Demo set + before/after (Days 15-16)

**Human + Claude Code:** audit the 6 pages in Section 13 live; save real outputs to `examples/` (README only, never read by the app). For the page you control: audit, apply the fix pack, re-audit, and record the ARS/SVS delta honestly. If rank hasn't moved, say so. Record the 2-3 minute demo video and screenshots.

**Gate:** 6 saved audits, one before/after, video uploaded.

---

## Phase 12: Submit (Day 17; Day 18 is buffer, no new features)

Human checklist (CLAUDE.md Section 14):
- [ ] Public repo + live demo URL
- [ ] Notes: what it does + how TinyFish is used
- [ ] LinkedIn post tagging TinyFish
- [ ] X post tagging TinyFish
- [ ] Share in Discord #showcase
- [ ] No secrets in the repo or demo; no padded API usage

---

## Failure protocol

If a gate fails twice, stop and report: what was tried, the exact error, and one proposed change. Do not loop. Do not weaken a rule (canned data, dropped `ttl: 0`, unevidenced findings) to make a gate pass.
