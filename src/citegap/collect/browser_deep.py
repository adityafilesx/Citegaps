"""Optional deep mode (TinyFish Browser API, uses credits): what a human sees after interaction vs what Fetch extracted.

EXPERIMENTAL / not validated against the live Browser API. Off by default. The driver is injectable so the
analysis is unit-tested without a browser; the Playwright driver needs `pip install citegap[deep]`.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from ..tinyfish.client import TinyFishClient, TinyFishError
from ..util import words

EXPAND_SELECTORS = [
    "details:not([open]) > summary", '[aria-expanded="false"]', 'button:has-text("Read more")', 'button:has-text("Show more")',
    'a:has-text("Read more")', '[role="tab"]',
]
OVERLAY_WORDS = re.compile(r"(cookie|consent|gdpr|privacy|accept all|we use|subscribe|newsletter)", re.I)
MAX_CLICKS = 12


@dataclass
class DeepResult:
    baseline_text: str = ""
    after_text: str = ""
    clicked: list[str] = field(default_factory=list)
    overlay: Optional[dict] = None  # {selector, text, covers_pct}
    screenshot_jpeg_b64: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None


Driver = Callable[[str, str], Awaitable[DeepResult]]  # (cdp_url, url) -> DeepResult


async def playwright_driver(cdp_url: str, url: str) -> DeepResult:
    res = DeepResult()
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        res.error = "playwright not installed (pip install 'citegap[deep]')"
        return res
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=45000)
            res.baseline_text = await page.inner_text("body")
            res.overlay = await page.evaluate("""() => {
                const vw = innerWidth, vh = innerHeight; let best = null;
                for (const el of document.querySelectorAll('body *')) {
                  const cs = getComputedStyle(el);
                  if (!['fixed','sticky'].includes(cs.position)) continue;
                  const r = el.getBoundingClientRect();
                  const pct = Math.round(100 * Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0)) / (vw * vh));
                  const text = (el.innerText || '').trim().slice(0, 200);
                  if (pct >= 25 && text && (!best || pct > best.covers_pct)) best = {selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''), text, covers_pct: pct};
                }
                return best;
            }""")
            shot = await page.screenshot(type="jpeg", quality=50)
            res.screenshot_jpeg_b64 = base64.b64encode(shot).decode()
            for _ in range(8):  # reveal lazy-loaded content
                await page.mouse.wheel(0, 1600)
                await page.wait_for_timeout(300)
            clicks = 0
            for sel in EXPAND_SELECTORS:
                for el in (await page.query_selector_all(sel))[:MAX_CLICKS]:
                    if clicks >= MAX_CLICKS:
                        break
                    try:
                        label = (await el.inner_text() or sel)[:40]
                        await el.click(timeout=1500)
                        res.clicked.append(f"{sel}: {label.strip()}")
                        clicks += 1
                    except Exception:  # element detached / not clickable: skip
                        continue
            await page.wait_for_timeout(500)
            res.after_text = await page.inner_text("body")
    except Exception as exc:
        res.error = f"{type(exc).__name__}: {str(exc)[:160]}"
    return res


async def run_deep(client: TinyFishClient, url: str, driver: Optional[Driver] = None) -> DeepResult:
    drv = driver or playwright_driver
    try:
        sess = await client.browser_create(url)
    except TinyFishError as exc:
        return DeepResult(error=f"browser session failed: {exc.code}")
    sid = sess.get("session_id")
    try:
        res = await drv(sess.get("cdp_url", ""), url)
        res.session_id = sid
        return res
    finally:
        if sid:
            try:
                await client.browser_close(sid)
            except TinyFishError:
                pass


def added_text(before: str, after: str) -> str:
    seen = {l.strip() for l in before.splitlines() if l.strip()}
    return "\n".join(l.strip() for l in after.splitlines() if l.strip() and l.strip() not in seen)


def shingle_coverage(extracted_md: str, text: str, k: int = 5) -> float:
    """Share of k-word shingles of `text` that appear in the Fetch extraction."""
    tw = [w.lower() for w in words(text)]
    if len(tw) < k:
        return 0.0
    ex = " ".join(w.lower() for w in words(extracted_md))
    sh = [" ".join(tw[i:i + k]) for i in range(len(tw) - k + 1)]
    return sum(1 for s in sh if s in ex) / len(sh)
