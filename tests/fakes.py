"""Test doubles. Fixtures live in tests/ only — never in the product path (CLAUDE.md Rule 1)."""
from __future__ import annotations

import json
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

import httpx

from citegap.config import Settings

PUBLIC_IP = "93.184.216.34"


def resolver(host: str) -> list[str]:
    return [PUBLIC_IP]


def para(n: int, seed: str = "crawlers") -> str:
    base = (f"{seed} fetch pages and read robots rules before they index content so site owners control access "
            "and structure matters for every automated reader ").split()
    return " ".join((base * (n // len(base) + 1))[:n]).capitalize() + "."


def settings(**kw) -> Settings:
    s = Settings(tinyfish_api_key="test-key-abcdef123456", search_rpm=600, fetch_upm=6000, max_retries=2)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class FakeTinyFish:
    """Serves Search + Fetch from dicts and records every request."""

    def __init__(self, pages: dict[str, dict], search_fn: Callable[[str, dict], list[dict]],
                 highlights_enabled: bool = True, fail_status: Optional[int] = None):
        self.pages, self.search_fn = pages, search_fn
        self.highlights_enabled, self.fail_status = highlights_enabled, fail_status
        self.requests: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if self.fail_status:
            return httpx.Response(self.fail_status, json={"error": {"code": "BOOM", "message": "forced"}})
        if host == "api.browser.tinyfish.ai":
            self.requests.append({"endpoint": "browser", "method": req.method, "path": req.url.path, "key": req.headers.get("x-api-key")})
            if req.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(201, json={"session_id": "br-test-1", "cdp_url": "wss://fake/cdp", "base_url": "https://fake"})
        if host == "api.search.tinyfish.ai":
            params = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
            self.requests.append({"endpoint": "search", "params": params, "key": req.headers.get("x-api-key")})
            results = self.search_fn(params["query"], params)
            return httpx.Response(200, json={"query": params["query"], "results": [
                {"position": i, **r} for i, r in enumerate(results, 1)], "total_results": len(results), "page": int(params.get("page", 0))})
        body = json.loads(req.content)
        self.requests.append({"endpoint": "fetch", "body": body, "key": req.headers.get("x-api-key")})
        results, errors = [], []
        if "highlights" in body and not self.highlights_enabled:
            return httpx.Response(403, json={"error": {"code": "FORBIDDEN", "message": "highlights not enabled"}})
        for u in body["urls"]:
            p = self.pages.get(u)
            if p is None:
                errors.append({"url": u, "error": "page_not_found", "status": 404})
                continue
            if p.get("error"):
                errors.append({"url": u, "error": p["error"], "status": p.get("status")})
                continue
            if body.get("include_selectors"):
                if p.get("main_md") is None:
                    errors.append({"url": u, "error": "selector_not_matched", "unmatched_selectors": body["include_selectors"],
                                   "candidate_selectors": ["div.post", "#content"]})
                    continue
                text = p["main_md"]
            elif body.get("format") == "html":
                text = p.get("html", "")
            else:
                text = p.get("md", "")
            r = {"url": u, "final_url": p.get("final_url", u), "title": p.get("title"), "description": p.get("description"),
                 "language": p.get("language", "en"), "author": p.get("author"), "published_date": p.get("published_date"),
                 "text": text, "links": p.get("links", []) if body.get("links") else [],
                 "image_links": [], "iframe_links": p.get("iframes", []) if body.get("iframe_links") else [],
                 "latency_ms": 900, "format": body.get("format", "markdown")}
            if "highlights" in body:
                r["highlights"] = p.get("highlights", [])
                r["text"] = None
            results.append(r)
        return httpx.Response(200, json={"results": results, "errors": errors})


class FakeWeb:
    """Raw-HTTP side: maps (host, path) to (status, headers, body)."""

    def __init__(self, routes: dict[str, tuple[int, dict, str]]):
        self.routes, self.seen = routes, []

    def transport(self) -> httpx.MockTransport:
        def handle(req: httpx.Request) -> httpx.Response:
            host = req.headers.get("host", req.url.host).split(":")[0]
            key = f"https://{host}{req.url.path}"
            self.seen.append((str(req.url), host))
            status, headers, body = self.routes.get(key, (404, {}, "not found"))
            return httpx.Response(status, headers=headers, text=body)
        return httpx.MockTransport(handle)
