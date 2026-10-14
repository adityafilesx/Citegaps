import pytest

from citegap.pipeline import AuditError, run_audit
from citegap.tinyfish.client import TinyFishClient
from fakes import FakeTinyFish, FakeWeb, resolver, settings
from scenarios import A_URL, B_URL, QUERY, scenario_a, scenario_b


async def audit(fake, web, url, query=QUERY, **kw):
    s = settings()
    c = TinyFishClient(s, transport=fake.transport())
    events = []
    rep = await run_audit(url, query, settings=s, client=c, emit=events.append, raw_transport=web.transport(), resolver=resolver, **kw)
    await c.aclose()
    return rep, events


def ids(rep):
    return {f.id for f in rep.findings}


async def test_scenario_a_full_audit():
    fake, web = scenario_a()
    rep, events = await audit(fake, web, A_URL)
    got = ids(rep)
    # extractability + access + semantics findings from live (fake) data
    assert {"EXTRACT_JS_DEPENDENT", "EXTRACT_BOILERPLATE_HEAVY", "ACCESS_BOT_BLOCKED_OAI_SEARCHBOT", "ACCESS_BOT_BLOCKED_GPTBOT",
            "ACCESS_NOSNIPPET", "SEM_JSONLD_MISSING", "SEM_TITLE_LONG", "SEM_CANONICAL_MISSING"} <= got
    assert "ACCESS_NO_LLMS_TXT" in got and "ACCESS_SITEMAP_MISSING_TARGET" in got
    assert "EXTRACT_IMG_ALT_MISSING" in got and "SEM_HEADING_SKIP" in got and "SEM_LINK_TEXT_GENERIC" in got
    # search side
    assert "SERP_NOT_RANKED" in got and "SERP_NOT_INDEXED" in got
    assert rep.answerability_method == "highlights" and "ANS_NO_PASSAGE" in got
    # bridges: JS -> not indexed (inferred), no-passage -> rank, blocked search bot -> AI visibility only
    pairs = {(b.cause_id, b.symptom_id): b for b in rep.bridges}
    assert pairs[("EXTRACT_JS_DEPENDENT", "SERP_NOT_INDEXED")].confidence == "inferred"
    assert ("ANS_NO_PASSAGE", "SERP_NOT_RANKED") in pairs
    assert pairs[("ACCESS_BOT_BLOCKED_OAI_SEARCHBOT", "AI_ANSWER_VISIBILITY")].confidence == "observed"
    assert ("ACCESS_BOT_BLOCKED_GPTBOT", "AI_ANSWER_VISIBILITY") not in pairs  # training bot: policy choice, no bridge
    # every finding has evidence and concrete steps
    assert all(f.evidence and f.fix.steps for f in rep.findings)
    assert rep.ars.total < 100 and 0 <= rep.svs.total <= 100
    assert [c.name for c in rep.ars.components] == ["access", "extractability", "semantics", "answerability"]


async def test_every_fetch_is_live_and_budget_respected():
    fake, web = scenario_a()
    rep, events = await audit(fake, web, A_URL)
    fetches = [r for r in fake.requests if r["endpoint"] == "fetch"]
    searches = [r for r in fake.requests if r["endpoint"] == "search"]
    assert fetches and all(r["body"]["ttl"] == 0 for r in fetches)
    assert all(c.ttl == 0 for c in rep.calls if c.endpoint == "fetch")
    assert len(searches) <= 6 and all(r["params"].get("purpose") for r in searches)
    assert rep.endpoints_used == {"search": len(searches), "fetch": len(fetches)}
    # competitors in ONE batched fetch; site files in ONE batched fetch
    comp_urls = {"https://guides.example/robots-ai", "https://docs.other.example/crawlers", "https://news.example/ai-bots"}
    assert sum(1 for r in fetches if set(r["body"]["urls"]) == comp_urls and "highlights" not in r["body"]) == 1
    assert sum(1 for r in fetches if any(u.endswith("robots.txt") for u in r["body"]["urls"])) == 1
    # progress events carry the live call log
    assert any(e.get("tinyfish_call", {}).get("endpoint") == "search" for e in events)
    assert events[-1]["stage"] == "done"


async def test_highlights_403_falls_back_to_bm25_and_is_labelled():
    fake, web = scenario_a(highlights_enabled=False)
    rep, _ = await audit(fake, web, A_URL)
    assert rep.answerability_method == "bm25"
    assert any("highlights unavailable" in n.lower() for n in rep.notes)
    assert "ANS_NO_PASSAGE" in ids(rep)


async def test_scenario_b_rank_page_two_title_rewrite_snippet_bridge():
    fake, web = scenario_b()
    rep, _ = await audit(fake, web, B_URL)
    got = ids(rep)
    assert rep.serp_card["position"] == 14  # utm param stripped by URL normalization
    assert "SERP_RANK_LOW" in got and "SERP_TITLE_REWRITTEN" in got and "SERP_SNIPPET_BOILERPLATE" in got
    assert "SERP_NOT_INDEXED" not in got
    # title is short -> no rewrite bridge because no title-quality cause is present
    assert not any(b.symptom_id == "SERP_TITLE_REWRITTEN" for b in rep.bridges)
    assert rep.svs.components[1].points == 8.0  # rank 11-20 flat points


async def test_derived_query_labelled():
    fake, web = scenario_b()
    rep, _ = await audit(fake, web, B_URL, query=None)
    assert rep.query_derived and rep.query and "Based on derived query" in rep.svs.note


async def test_blocked_page_is_a_finding_not_a_crash():
    fake, web = scenario_a()
    fake.pages[A_URL] = {"error": "bot_blocked", "status": 403}
    rep, _ = await audit(fake, web, A_URL)
    assert rep.could_not_read
    assert "ACCESS_FETCH_BOT_BLOCKED" in ids(rep)
    assert next(f for f in rep.findings if f.id == "ACCESS_FETCH_BOT_BLOCKED").severity == "critical"
    comps = {c.name: c for c in rep.ars.components}
    assert comps["extractability"].points == 0 and comps["semantics"].points == 0 and comps["answerability"].points == 0
    assert "could not read" in comps["semantics"].note
    assert rep.svs.total >= 0  # visibility half still ran
    assert any(p.kind == "target_query" for p in rep.serp)


@pytest.mark.parametrize("err", ["login_required", "empty_content", "timeout", "page_not_found", "target_http_error",
                                 "target_unreachable", "content_too_large", "proxy_error", "invalid_redirect_url"])
async def test_every_fetch_error_code_yields_a_sensible_report(err):
    fake, web = scenario_a()
    fake.pages[A_URL] = {"error": err, "status": 500 if err == "target_http_error" else None}
    rep, _ = await audit(fake, web, A_URL)
    assert rep.could_not_read and any(f.id == f"ACCESS_FETCH_{err.upper()}" for f in rep.findings)


async def test_api_key_problem_is_an_error_not_a_finding():
    s = settings()
    fake = FakeTinyFish({}, lambda q, p: [], fail_status=401)
    c = TinyFishClient(s, transport=fake.transport())
    with pytest.raises(AuditError):
        await run_audit(A_URL, QUERY, settings=s, client=c, raw_transport=FakeWeb({}).transport(), resolver=resolver)
    await c.aclose()


async def test_private_url_rejected_before_any_call():
    fake, web = scenario_a()
    with pytest.raises(ValueError):
        await audit(fake, web, "http://169.254.169.254/latest")
    assert fake.requests == []


async def test_search_failure_does_not_abort_readability_half():
    fake, web = scenario_a()
    orig = fake.handle

    def handle(req):
        import httpx
        if req.url.host == "api.search.tinyfish.ai":
            return httpx.Response(500, json={"error": {"code": "X"}})
        return orig(req)

    fake.handle = handle
    s = settings(max_retries=0)
    c = TinyFishClient(s, transport=fake.transport())
    rep = await run_audit(A_URL, QUERY, settings=s, client=c, raw_transport=web.transport(), resolver=resolver)
    await c.aclose()
    assert "EXTRACT_JS_DEPENDENT" in ids(rep) and "SERP_NOT_RANKED" not in ids(rep)
    assert any("Search" in n for n in rep.notes)
    assert "n/a" in " ".join(c.note for c in rep.svs.components)
