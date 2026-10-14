import json
import zipfile
import io

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from citegap.api import create_app
from citegap.store import Store
from citegap.tinyfish.client import TinyFishClient
from fakes import resolver, settings
from scenarios import A_URL, scenario_a


def make_app(tmp_path, **kw):
    fake, web = scenario_a()
    s = settings(db_path=str(tmp_path / "t.db"), audits_per_minute=3, audits_per_hour=50)
    app = create_app(s, client_factory=lambda st: TinyFishClient(st, transport=fake.transport()), raw_transport=web.transport(),
                     resolver=resolver, store=Store(s.db_path))
    return app, fake


async def wait_report(ac, job_id):
    async with ac.stream("GET", f"/audit/{job_id}/events") as r:
        assert r.status_code == 200
        events = [json.loads(l[6:]) async for l in r.aiter_lines() if l.startswith("data: ")]
    return events


async def test_audit_flow_sse_report_fixpack_permalink(tmp_path):
    app, fake = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/audit", json={"url": A_URL, "query": "robots.txt for ai crawlers"})
        assert r.status_code == 200
        jid = r.json()["id"]
        events = await wait_report(ac, jid)
        stages = [e["stage"] for e in events]
        assert "target" in stages and "search" in stages and stages[-1] == "report"
        assert any(e.get("tinyfish_call", {}).get("ttl") == 0 for e in events)
        rep = (await ac.get(f"/audit/{jid}")).json()
        assert rep["id"] == jid and rep["findings"] and rep["bridges"]
        z = zipfile.ZipFile(io.BytesIO((await ac.get(f"/audit/{jid}/fixpack.zip")).content))
        assert "report.md" in z.namelist() and any(n.startswith("snippets/") for n in z.namelist())
        assert "Gap Matrix" in (await ac.get(f"/audit/{jid}/report.md")).text
        assert (await ac.get(f"/r/{jid}")).status_code == 200
        # re-audit links to the previous run and reports a delta
        j2 = (await ac.post(f"/audit/{jid}/reaudit")).json()["id"]
        await wait_report(ac, j2)
        rep2 = (await ac.get(f"/audit/{j2}")).json()
        assert rep2["previous"]["id"] == jid and rep2["previous"]["ars_delta"] == 0


async def test_rate_limit_returns_429(tmp_path):
    app, _ = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        codes = [(await ac.post("/audit", json={"url": A_URL})).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


async def test_rejects_private_and_bad_urls(tmp_path):
    app, fake = make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for u in ("http://127.0.0.1/admin", "http://169.254.169.254/", "ftp://x.example/"):
            r = await ac.post("/audit", json={"url": u})
            assert r.status_code == 400, u
        assert (await ac.get("/audit/nope")).status_code == 404
    assert fake.requests == []


async def test_missing_server_key_is_503(tmp_path):
    s = settings(tinyfish_api_key="", db_path=str(tmp_path / "t.db"))
    app = create_app(s, resolver=resolver, store=Store(s.db_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        assert (await ac.post("/audit", json={"url": A_URL})).status_code == 503
        assert (await ac.get("/healthz")).json()["tinyfish_key"] == "<unset>"


async def test_api_problem_surfaces_as_error_event_without_key_leak(tmp_path):
    from fakes import FakeTinyFish, FakeWeb
    fake = FakeTinyFish({}, lambda q, p: [], fail_status=401)
    s = settings(db_path=str(tmp_path / "t.db"))
    app = create_app(s, client_factory=lambda st: TinyFishClient(st, transport=fake.transport()), raw_transport=FakeWeb({}).transport(),
                     resolver=resolver, store=Store(s.db_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        jid = (await ac.post("/audit", json={"url": A_URL})).json()["id"]
        events = await wait_report(ac, jid)
    assert events[-1]["stage"] == "error" and "abcdef123456" not in json.dumps(events)
