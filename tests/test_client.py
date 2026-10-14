import httpx
import pytest

from citegap.tinyfish.client import TinyFishClient, TinyFishError, TokenBucket
from citegap.tinyfish.fetch import fetch_many
from fakes import FakeTinyFish, settings


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


async def test_token_bucket_waits_for_refill(monkeypatch):
    clock = Clock()
    b = TokenBucket(60, capacity=2, clock=clock)  # 1 token/s
    assert b.wait_time(1) == 0
    b.tokens = 0
    assert b.wait_time(1) == pytest.approx(1.0)
    clock.t = 0.5
    assert b.wait_time(1) == pytest.approx(0.5)


async def test_fetch_forces_ttl_zero_and_sends_key():
    fake = FakeTinyFish({"https://a.example/": {"md": "hello"}}, lambda q, p: [])
    c = TinyFishClient(settings(), transport=fake.transport())
    await fetch_many(c, ["https://a.example/"], summary="t")
    body = fake.requests[0]["body"]
    assert body["ttl"] == 0 and fake.requests[0]["key"] == "test-key-abcdef123456"
    assert c.calls[0].ttl == 0 and c.calls[0].status == "ok"
    await c.aclose()


async def test_batches_of_ten():
    urls = [f"https://a.example/{i}" for i in range(23)]
    fake = FakeTinyFish({u: {"md": "x"} for u in urls}, lambda q, p: [])
    c = TinyFishClient(settings(), transport=fake.transport())
    b = await fetch_many(c, urls, summary="t")
    assert [len(r["body"]["urls"]) for r in fake.requests] == [10, 10, 3]
    assert len(b.results) == 23
    await c.aclose()


async def test_per_url_errors_are_normalized_not_raised():
    fake = FakeTinyFish({"https://ok.example/": {"md": "x"}, "https://b.example/": {"error": "bot_blocked", "status": 403}}, lambda q, p: [])
    c = TinyFishClient(settings(), transport=fake.transport())
    b = await fetch_many(c, ["https://ok.example/", "https://b.example/", "https://missing.example/"], summary="t")
    assert "https://ok.example/" in b.results
    assert b.errors["https://b.example/"].error == "bot_blocked"
    assert b.errors["https://missing.example/"].error == "page_not_found"
    await c.aclose()


async def test_retry_on_429_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"code": "RATE"}}) if calls["n"] < 3 else httpx.Response(200, json={"results": [], "errors": []})

    slept = []
    async def fake_sleep(s): slept.append(s)
    c = TinyFishClient(settings(), transport=httpx.MockTransport(handler), sleep=fake_sleep)
    await c.fetch({"urls": ["https://a.example/"]}, summary="t")
    assert calls["n"] == 3 and slept == [1.5, 3.0]
    await c.aclose()


async def test_request_level_failure_is_reported_per_url():
    fake = FakeTinyFish({}, lambda q, p: [], fail_status=401)
    c = TinyFishClient(settings(), transport=fake.transport())
    b = await fetch_many(c, ["https://a.example/"], summary="t")
    assert b.request_status == 401 and b.errors["https://a.example/"].request_level
    assert c.calls[0].status == "http_401"
    await c.aclose()


async def test_missing_key_raises_without_network():
    c = TinyFishClient(settings(tinyfish_api_key=""), transport=httpx.MockTransport(lambda r: pytest.fail("no network")))
    with pytest.raises(TinyFishError) as ei:
        await c.search("q", purpose="p")
    assert ei.value.code == "missing_api_key"
    await c.aclose()


def test_repr_never_leaks_key():
    c = TinyFishClient(settings())
    assert "abcdef123456" not in repr(c)
