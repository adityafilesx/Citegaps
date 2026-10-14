import pytest

from citegap.util import check_public_url, is_public_ip, normalize_url, registrable_hint, same_site


def test_normalize_strips_tracking_www_slash_fragment():
    assert normalize_url("http://www.Example.com/a/b/?utm_source=x&id=2&gclid=z#frag") == "https://example.com/a/b?id=2"
    assert normalize_url("https://example.com/") == "https://example.com/"
    assert normalize_url("https://example.com/a/") == normalize_url("https://www.example.com/a")


@pytest.mark.parametrize("ip,expected", [
    ("127.0.0.1", False), ("10.1.2.3", False), ("192.168.0.1", False), ("169.254.169.254", False),
    ("::1", False), ("0.0.0.0", False), ("100.64.0.1", False), ("::ffff:127.0.0.1", False),
    ("93.184.216.34", True), ("2606:2800:220:1:248:1893:25c8:1946", True)])
def test_is_public_ip(ip, expected):
    assert is_public_ip(ip) is expected


@pytest.mark.parametrize("url", [
    "http://localhost/x", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "ftp://example.com/",
    "http://user:pw@example.com/", "http://[::1]/", "http://foo.internal/", "file:///etc/passwd"])
def test_check_public_url_rejects(url):
    ok, reason, _ = check_public_url(url, resolver=lambda h: ["93.184.216.34"])
    assert not ok, reason


def test_check_public_url_rejects_private_dns_answer():
    ok, reason, _ = check_public_url("https://evil.example/", resolver=lambda h: ["10.0.0.5"])
    assert not ok and "non-public" in reason


def test_check_public_url_accepts_public():
    assert check_public_url("https://example.com/p", resolver=lambda h: ["93.184.216.34"])[0]


def test_same_site():
    assert same_site("https://blog.example.com/a", "https://www.example.com/b")
    assert not same_site("https://example.com", "https://example.org")
    assert registrable_hint("a.b.example.co.uk") == "example.co.uk"
