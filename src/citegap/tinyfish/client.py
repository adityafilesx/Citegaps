"""Async TinyFish client: auth, token-bucket limiter, retry/backoff, call log."""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from ..config import Settings, mask_key
from ..report.model import CallLogEntry


class TinyFishError(Exception):
    """Whole-request failure (HTTP error, network error)."""

    def __init__(self, status: Optional[int], code: str, message: str):
        super().__init__(f"{status or 'net'} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class TokenBucket:
    """Token bucket; `acquire(n)` waits until n tokens are available."""

    def __init__(self, per_minute: int, capacity: Optional[int] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.rate = per_minute / 60.0
        self.capacity = float(capacity if capacity is not None else per_minute)
        self.tokens = self.capacity
        self.clock = clock
        self.updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    def wait_time(self, n: float) -> float:
        self._refill()
        if self.tokens >= n:
            return 0.0
        return (n - self.tokens) / self.rate

    async def acquire(self, n: float = 1.0) -> float:
        n = min(n, self.capacity)
        waited = 0.0
        async with self._lock:
            while True:
                wt = self.wait_time(n)
                if wt <= 0:
                    self.tokens -= n
                    return waited
                await asyncio.sleep(wt)
                waited += wt


class TinyFishClient:
    def __init__(self, settings: Settings, transport: Optional[httpx.AsyncBaseTransport] = None,
                 on_call: Optional[Callable[[CallLogEntry], None]] = None,
                 sleep: Callable[[float], Any] = asyncio.sleep):
        self.s = settings
        self.on_call = on_call
        self._sleep = sleep
        self.calls: list[CallLogEntry] = []
        self._search_bucket = TokenBucket(settings.search_rpm)
        self._fetch_bucket = TokenBucket(settings.fetch_upm)
        self._browser_bucket = TokenBucket(10)
        self._http = httpx.AsyncClient(
            transport=transport,
            headers={"X-API-Key": settings.tinyfish_api_key, "User-Agent": "CiteGap/0.1"},
            timeout=httpx.Timeout(settings.fetch_client_timeout_s, connect=15.0),
        )

    def __repr__(self) -> str:  # never leak the key
        return f"TinyFishClient(key={mask_key(self.s.tinyfish_api_key)})"

    async def aclose(self) -> None:
        await self._http.aclose()

    def _log(self, entry: CallLogEntry) -> None:
        if self.on_call:
            self.on_call(entry)

    async def _request(self, endpoint: str, method: str, url: str, summary: str,
                       ttl: Optional[int] = None, *, params: dict | None = None,
                       json: dict | None = None, timeout: float | None = None,
                       cost: float = 1.0) -> dict:
        if not self.s.tinyfish_api_key:
            raise TinyFishError(None, "missing_api_key", "TINYFISH_API_KEY is not set")
        bucket = {"search": self._search_bucket, "fetch": self._fetch_bucket}.get(endpoint, self._browser_bucket)
        entry = CallLogEntry(id=f"{endpoint[0]}-{uuid.uuid4().hex[:6]}", endpoint=endpoint,  # type: ignore[arg-type]
                             summary=summary, ttl=ttl,
                             started_at=datetime.now(timezone.utc).isoformat())
        self.calls.append(entry)
        self._log(entry)
        last: Optional[TinyFishError] = None
        t0 = time.monotonic()
        for attempt in range(self.s.max_retries + 1):
            await bucket.acquire(cost)
            try:
                resp = await self._http.request(method, url, params=params, json=json, timeout=timeout)
            except httpx.TimeoutException:
                last = TinyFishError(None, "client_timeout", "request timed out")
            except httpx.HTTPError as exc:
                last = TinyFishError(None, "network_error", type(exc).__name__)
            else:
                if resp.status_code < 400:
                    if resp.status_code == 204 or not resp.content:
                        entry.latency_ms = int((time.monotonic() - t0) * 1000)
                        entry.status = "ok"
                        self._log(entry)
                        return {}
                    try:
                        data = resp.json()
                    except ValueError:
                        last = TinyFishError(resp.status_code, "bad_json", "non-JSON response")
                        break
                    entry.latency_ms = int((time.monotonic() - t0) * 1000)
                    entry.status = "ok"
                    self._log(entry)
                    return data
                last = TinyFishError(resp.status_code, _err_code(resp), _err_msg(resp))
                if resp.status_code not in (429, 503, 502, 504):
                    break
            if attempt < self.s.max_retries:
                await self._sleep(min(30.0, 1.5 * (2 ** attempt)))
        entry.latency_ms = int((time.monotonic() - t0) * 1000)
        entry.status = f"http_{last.status}" if last and last.status else "error"
        entry.detail = f"{last.code}: {last.message}"[:200] if last else ""
        self._log(entry)
        assert last is not None
        raise last

    async def search(self, query: str, *, purpose: str, summary: str | None = None,
                     **params: Any) -> dict:
        p = {"query": query, "purpose": purpose, **{k: v for k, v in params.items() if v not in (None, "")}}
        return await self._request("search", "GET", self.s.search_url,
                                   summary or f"Search q={query[:60]!r} " + " ".join(
                                       f"{k}={v}" for k, v in params.items() if v not in (None, "")),
                                   params=p, timeout=self.s.search_client_timeout_s)

    async def browser_create(self, url: str, *, timeout_seconds: int = 120) -> dict:
        """Create a remote browser session (uses credits). Returns {session_id, cdp_url, base_url}."""
        return await self._request("browser", "POST", self.s.browser_url, "Browser session (deep mode)",
                                   json={"url": url, "timeout_seconds": timeout_seconds}, timeout=90.0)

    async def browser_close(self, session_id: str) -> None:
        await self._request("browser", "DELETE", f"{self.s.browser_url}/{session_id}", "Browser session close", timeout=30.0)

    async def fetch(self, body: dict, *, summary: str) -> dict:
        body = {**body, "ttl": 0}  # Rule 2: always live
        n = len(body.get("urls", [])) or 1
        return await self._request("fetch", "POST", self.s.fetch_url,
                                   f"{summary} ({n} url{'s' if n != 1 else ''})", ttl=0, json=body,
                                   timeout=self.s.fetch_client_timeout_s, cost=n)


def _err_code(resp: httpx.Response) -> str:
    try:
        d = resp.json()
        if isinstance(d, dict):
            e = d.get("error") or d
            if isinstance(e, dict):
                return str(e.get("code") or e.get("type") or f"http_{resp.status_code}")
            return str(e)[:60]
    except ValueError:
        pass
    return f"http_{resp.status_code}"


def _err_msg(resp: httpx.Response) -> str:
    try:
        d = resp.json()
        if isinstance(d, dict):
            e = d.get("error") or d
            if isinstance(e, dict):
                return str(e.get("message") or e)[:200]
            return str(e)[:200]
    except ValueError:
        pass
    return resp.text[:200]
