import httpx
import pytest

from citegap.collect.raw_http import fetch_raw
from fakes import FakeWeb, resolver, settings

HTML = "<html lang='en'><head><title>T</title></head><body><h1>Hi</h1><p>one two three four five six seven eight nine ten</p></body></html>"


async def test_fetches_and_parses_and_pins_to_validated_ip():
    web = FakeWeb({"https://site.example/p": (200, {"content-type": "text/html", "X-Robots-Tag": "noindex"}, HTML)})
    r = await fetch_raw("https://site.example/p", settings(), resolver=resolver, transport=web.transport())
    assert r.status == 200 and r.doc.title == "T" and r.x_robots == ["noindex"]
    assert web.seen[0][0].startswith("https://93.184.216.34/")  # connected to the validated IP, Host preserved
    assert web.seen[0][1] == "site.example"


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://localhost:8000/", "http://[::1]/"])
async def test_ssrf_literals_blocked_without_network(url):
    r = await fetch_raw(url, settings(), resolver=resolver, transport=httpx.MockTransport(lambda q: pytest.fail("must not connect")))
    assert r.error and "SSRF" in r.error


async def test_dns_resolving_to_private_blocked():
    r = await fetch_raw("https://rebind.example/", settings(), resolver=lambda h: ["10.0.0.7"],
                        transport=httpx.MockTransport(lambda q: pytest.fail("must not connect")))
    assert "SSRF" in r.error


async def test_redirect_to_private_blocked_after_first_hop():
    def res(h): return ["10.0.0.7"] if h == "internal.example" else ["93.184.216.34"]

    def handler(req):
        return httpx.Response(302, headers={"location": "https://internal.example/admin"})

    r = await fetch_raw("https://start.example/", settings(), resolver=res, transport=httpx.MockTransport(handler))
    assert r.error and "SSRF" in r.error and r.redirects == ["https://start.example/"]


async def test_redirect_chain_followed_and_recorded():
    def handler(req):
        host = req.headers["host"]
        if host == "a.example":
            return httpx.Response(301, headers={"location": "https://b.example/final"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=HTML)

    r = await fetch_raw("https://a.example/", settings(), resolver=resolver, transport=httpx.MockTransport(handler))
    assert r.final_url == "https://b.example/final" and r.redirects == ["https://a.example/"] and r.doc.title == "T"


async def test_redirect_loop_gives_up():
    h = lambda req: httpx.Response(302, headers={"location": "https://a.example/"})
    r = await fetch_raw("https://a.example/", settings(), resolver=resolver, transport=httpx.MockTransport(h))
    assert r.error == "too many redirects"


async def test_size_cap_truncates():
    big = "<html><body>" + "x " * 500000 + "</body></html>"
    h = lambda req: httpx.Response(200, headers={"content-type": "text/html"}, text=big)
    r = await fetch_raw("https://a.example/", settings(raw_max_bytes=10_000), resolver=resolver, transport=httpx.MockTransport(h))
    assert r.truncated and len(r.text) <= 10_000


async def test_timeout_reported():
    def h(req): raise httpx.ReadTimeout("slow")
    r = await fetch_raw("https://a.example/", settings(), resolver=resolver, transport=httpx.MockTransport(h))
    assert r.error == "timeout"
