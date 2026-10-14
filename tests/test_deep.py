from citegap.analyze.deep import analyze_deep
from citegap.collect.browser_deep import DeepResult, added_text, run_deep, shingle_coverage
from citegap.pipeline import run_audit
from citegap.tinyfish.client import TinyFishClient
from fakes import para, resolver, settings
from scenarios import A_URL, scenario_a

BASE = "Intro line\n" + " ".join(["word"] * 120)
HIDDEN = " ".join(f"zq{i}x mm{i}y" for i in range(100))  # words that occur nowhere in the Fetch extraction


async def fake_driver(cdp_url, url):
    assert cdp_url == "wss://fake/cdp"
    return DeepResult(baseline_text=BASE, after_text=BASE + "\n" + HIDDEN, clicked=["button: Read more"],
                      overlay={"selector": "div#cookie", "text": "We use cookies to improve things", "covers_pct": 62},
                      screenshot_jpeg_b64="AAAA")


def test_added_text_and_shingles():
    assert added_text("a\nb", "a\nb\nc d e f g h") == "c d e f g h"
    assert shingle_coverage("alpha beta gamma delta epsilon zeta", "alpha beta gamma delta epsilon zeta") == 1.0
    assert shingle_coverage("nothing here at all really", "alpha beta gamma delta epsilon zeta") == 0.0


async def test_session_lifecycle_and_logging():
    fake, web = scenario_a()
    c = TinyFishClient(settings(), transport=fake.transport())
    res = await run_deep(c, A_URL, fake_driver)
    assert res.session_id == "br-test-1" and res.clicked
    methods = [(r["method"], r["path"]) for r in fake.requests if r["endpoint"] == "browser"]
    assert methods == [("POST", "/"), ("DELETE", "/br-test-1")]  # session always closed
    assert [x.endpoint for x in c.calls] == ["browser", "browser"] and all(x.status == "ok" for x in c.calls)
    await c.aclose()


async def test_session_closed_even_if_driver_crashes():
    fake, web = scenario_a()
    c = TinyFishClient(settings(), transport=fake.transport())

    async def boom(cdp, url):
        raise RuntimeError("cdp died")

    try:
        await run_deep(c, A_URL, boom)
    except RuntimeError:
        pass
    assert ("DELETE", "/br-test-1") in [(r["method"], r["path"]) for r in fake.requests if r["endpoint"] == "browser"]
    await c.aclose()


async def test_deep_audit_adds_findings_distinct_from_fetch():
    fake, web = scenario_a()
    s = settings()
    c = TinyFishClient(s, transport=fake.transport())
    rep = await run_audit(A_URL, "robots.txt for ai crawlers", settings=s, client=c, raw_transport=web.transport(), resolver=resolver,
                          deep=True, deep_driver=fake_driver)
    await c.aclose()
    ids = {f.id for f in rep.findings}
    assert {"EXTRACT_INTERACTION_ONLY_CONTENT", "EXTRACT_CONSENT_OVERLAY"} <= ids
    f = next(f for f in rep.findings if f.id == "EXTRACT_INTERACTION_ONLY_CONTENT")
    assert f.severity == "high" and "present in Fetch extraction" in f.evidence[0].value
    assert rep.endpoints_used["browser"] == 2 and rep.extras["screenshot_jpeg_b64"] == "AAAA"


async def test_deep_off_by_default_makes_no_browser_calls():
    fake, web = scenario_a()
    s = settings()
    c = TinyFishClient(s, transport=fake.transport())
    rep = await run_audit(A_URL, "robots.txt for ai crawlers", settings=s, client=c, raw_transport=web.transport(), resolver=resolver)
    await c.aclose()
    assert "browser" not in rep.endpoints_used and not [r for r in fake.requests if r["endpoint"] == "browser"]


async def test_deep_failure_is_a_note_not_a_crash():
    fake, web = scenario_a()
    s = settings()
    c = TinyFishClient(s, transport=fake.transport())

    async def failing(cdp, url):
        return DeepResult(error="TimeoutError: nav")

    rep = await run_audit(A_URL, "robots.txt for ai crawlers", settings=s, client=c, raw_transport=web.transport(), resolver=resolver,
                          deep=True, deep_driver=failing)
    await c.aclose()
    assert any("Deep mode did not complete" in n for n in rep.notes)


def test_no_finding_when_content_already_extracted():
    from types import SimpleNamespace
    d = SimpleNamespace(md=BASE + " " + HIDDEN)
    r = DeepResult(baseline_text=BASE, after_text=BASE + "\n" + HIDDEN, clicked=["x"])
    assert analyze_deep(d, r) == []
