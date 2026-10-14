"""6.1 Access: can AI tools reach the page?"""
from __future__ import annotations

from urllib.parse import urlsplit

from ..collect.robots import check_access, parse_robots
from ..fixes import snippets as sn
from ..report.model import Finding, Fix
from ..util import host_of
from .context import AuditData, ev

FETCH_SEVERITY = {"bot_blocked": "critical", "login_required": "critical", "empty_content": "high",
                  "timeout": "high", "target_http_error": "high", "page_not_found": "high",
                  "target_unreachable": "high"}
FETCH_FIX = {
    "bot_blocked": ("The site served a bot challenge or blocked TinyFish's fetcher, so AI tools using similar fetchers "
                    "get nothing.", ["Check your WAF / bot-protection rules (Cloudflare, Akamai, DataDome) for challenges served to non-browser clients.",
                                     "Allow the AI search/user agents you want to appear in (see robots.txt findings) through the WAF."]),
    "login_required": ("The URL needs a login, so no AI tool can read it.",
                       ["Serve a public, crawlable version of this content or move the intended-public page off the login wall."]),
    "empty_content": ("The fetcher got a response but extracted no text.",
                      ["Confirm the HTML contains the content without requiring JavaScript, or add server-side rendering for this route."]),
    "timeout": ("The page did not finish loading in the fetch budget.",
                ["Reduce time-to-first-byte and blocking scripts; target < 3 s server response."]),
    "target_http_error": ("The server returned an HTTP error status.", ["Fix the server error for this URL, or redirect it to a working page."]),
    "page_not_found": ("The URL returns not-found.", ["Restore the page or add a 301 redirect to its replacement."]),
    "target_unreachable": ("The host could not be reached.", ["Check DNS, TLS certificate and firewall rules for the host."]),
}


def analyze_access(d: AuditData) -> list[Finding]:
    out: list[Finding] = []
    t = d.target
    for label, err in (("markdown", t.md_error),):
        if err is None:
            continue
        sev = FETCH_SEVERITY.get(err.error, "medium")
        why, steps = FETCH_FIX.get(err.error, (f"Fetch failed with {err.error}.", ["Open the URL in a clean browser session and resolve whatever blocks automated retrieval."]))
        status = f" (HTTP {err.status})" if err.status else ""
        out.append(Finding(
            id=f"ACCESS_FETCH_{err.error.upper()}", category="access", severity=sev,  # type: ignore[arg-type]
            title=f"AI fetch failed: {err.error}{status}",
            evidence=[ev("error", f"{err.error}{status} for {d.url}", err.call_id)],
            ai_impact=why, search_impact="If crawlers meet the same response, the page cannot be indexed or quoted.",
            fix=Fix(steps=steps, effort_minutes=30, where_to_paste="Server / CDN / WAF configuration"),
            confidence="observed"))
    if t.md_error is None and t.md is not None and not (t.md.text or "").strip():
        out.append(Finding(
            id="ACCESS_FETCH_EMPTY_CONTENT", category="access", severity="high",
            title="AI fetch returned an empty body", evidence=[ev("metric", "extracted text length = 0", d.md_call)],
            ai_impact="The fetcher succeeded but extracted no text.", search_impact="Nothing for an index or an answer engine to use.",
            fix=Fix(steps=FETCH_FIX["empty_content"][1], effort_minutes=60, where_to_paste="Page rendering / SSR"),
            confidence="observed"))
    if t.md and t.md.latency_ms and t.md.latency_ms > 15000:
        out.append(Finding(
            id="ACCESS_SLOW_RESPONSE", category="access", severity="medium",
            title=f"Page took {t.md.latency_ms/1000:.1f} s to fetch", evidence=[ev("metric", f"latency_ms={int(t.md.latency_ms)}", d.md_call)],
            ai_impact="Slow pages risk fetch timeouts in AI tools with tight budgets.", search_impact="Slow responses can reduce crawl rate.",
            fix=Fix(steps=["Profile server response time and render-blocking scripts for this URL; aim for < 3 s."], effort_minutes=120,
                    where_to_paste="Server / front-end performance"), confidence="observed"))
    fu, ou = t.final_url, d.url
    if t.md and host_of(fu) != host_of(ou):
        out.append(Finding(
            id="ACCESS_REDIRECT_OFF_HOST", category="access", severity="medium",
            title="URL redirects to a different host", evidence=[ev("url", f"{ou} → {fu}", d.md_call)],
            ai_impact="Tools that do not follow cross-host redirects stop at the redirect.",
            search_impact="Signals consolidate on the destination host, not the URL you submitted.",
            fix=Fix(steps=[f"Link, sitemap and canonical to the final URL {fu} instead of {ou}."], effort_minutes=15,
                    where_to_paste="Internal links, sitemap.xml, canonical tag"), confidence="observed"))
    raw = t.raw
    if raw is not None and raw.error:
        out.append(Finding(
            id="ACCESS_RAW_HTTP_ERROR", category="access", severity="medium",
            title=f"Plain HTTP request failed: {raw.error}", evidence=[ev("error", f"{raw.error} for {d.url}")],
            ai_impact="Crawlers that do not render JavaScript could not retrieve the page either.",
            search_impact="Unreachable to simple crawlers.", fix=Fix(steps=["Check the server answers plain GET requests with an honest user agent."], effort_minutes=20),
            confidence="observed"))
    elif raw is not None and raw.status and raw.status >= 400:
        out.append(Finding(
            id="ACCESS_RAW_HTTP_STATUS", category="access", severity="high" if raw.status in (401, 403, 429) else "medium",
            title=f"Plain HTTP GET returned {raw.status}", evidence=[ev("http", f"GET {raw.final_url} → {raw.status} (UA {d.settings.raw_user_agent})")],
            ai_impact="Simple crawlers receive an error instead of the page.", search_impact="Pages that answer bots with errors cannot be refreshed in indexes.",
            fix=Fix(steps=["Review bot-protection rules that answer non-browser user agents with 4xx."], effort_minutes=30,
                    where_to_paste="WAF / CDN"), confidence="observed"))
    if raw is not None and raw.status and raw.status < 400:
        _meta_directives(d, out)
    _robots(d, out)
    _site_files(d, out)
    return out


def _meta_directives(d: AuditData, out: list[Finding]) -> None:
    raw = d.target.raw
    assert raw is not None
    sources: list[tuple[str, str]] = [(f"<meta {m}>", m) for m in (raw.doc.meta_robots if raw.doc else [])]
    sources += [(f"X-Robots-Tag: {v}", v) for v in raw.x_robots]
    for label, text in sources:
        low = text.lower()
        if "noindex" in low and "no-noindex" not in low:
            out.append(Finding(
                id="ACCESS_NOINDEX", category="access", severity="critical",
                title="Page tells search engines not to index it", evidence=[ev("http" if label.startswith("X-") else "selector", label)],
                ai_impact="Compliant crawlers drop the page; AI tools that respect robots directives skip it.",
                search_impact="A noindex page will not appear in search results.",
                fix=Fix(steps=["Remove `noindex` from the robots meta tag / X-Robots-Tag header if this page should rank."],
                        snippet='<meta name="robots" content="index, follow">', snippet_lang="html", effort_minutes=5,
                        where_to_paste="<head> or server response headers"), confidence="observed"))
            break
    for label, text in sources:
        low = text.lower()
        if "nosnippet" in low or "max-snippet:0" in low.replace(" ", ""):
            out.append(Finding(
                id="ACCESS_NOSNIPPET", category="access", severity="high",
                title="Snippets are disabled for this page", evidence=[ev("http" if label.startswith("X-") else "selector", label)],
                ai_impact="`nosnippet` / `max-snippet:0` limits quoting in search and AI answers.",
                search_impact="Results show no text excerpt, which usually lowers click-through.",
                fix=Fix(steps=["Remove nosnippet / set max-snippet to -1 (or a sensible length) if you want excerpts shown."],
                        snippet='<meta name="robots" content="max-snippet:-1, max-image-preview:large">', snippet_lang="html",
                        effort_minutes=5, where_to_paste="<head> or server response headers"), confidence="observed"))
            break


def _robots(d: AuditData, out: list[Finding]) -> None:
    site = d.site
    if site is None or site.robots.status != "ok":
        return
    groups = parse_robots(site.robots.text)
    p = urlsplit(d.target.final_url)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    for bot in d.settings.ai_bots:
        allowed, rule, label = check_access(groups, bot["name"], path)
        if allowed:
            continue
        search_bot = bot["kind"] == "search"
        note = ("Blocking a training crawler while allowing search crawlers is a legitimate policy choice; "
                "keep this rule if it is intentional.") if not search_bot else \
               "This blocks a crawler that fetches pages to answer user questions or build search results."
        out.append(Finding(
            id=f"ACCESS_BOT_BLOCKED_{bot['name'].upper().replace('-', '_')}", category="access",
            severity="high" if search_bot else "medium",
            title=f"robots.txt blocks {bot['name']} ({bot['owner']}, {bot['kind']} bot) from this page",
            evidence=[ev("rule", f"{rule.line}  (robots.txt line {rule.lineno}, group: {label})" if rule else "blocked", site.robots.call_id),
                      ev("url", site.robots.url, site.robots.call_id)],
            ai_impact=f"{bot['name']} will not fetch this URL, so it cannot appear in that product's answers or index. {note}",
            search_impact=("Affects AI-answer visibility for that bot, not Google/Bing rank." if bot["name"] not in ("Googlebot", "Bingbot")
                           else "Blocking a major search crawler prevents the page from being crawled for ranking."),
            fix=Fix(steps=[f"If you want {bot['name']} to reach this page, narrow or remove the matching rule.",
                           "Then add an explicit group for it (below)."],
                    snippet=sn.robots_allow_lines([bot["name"]]) + ("\n\n" + sn.robots_remove_note([rule.line]) if rule else ""),
                    snippet_lang="text", effort_minutes=5, where_to_paste=f"{site.origin}/robots.txt"),
            confidence="observed"))


def _site_files(d: AuditData, out: list[Finding]) -> None:
    site = d.site
    if site is None:
        return
    if site.llms.status == "missing":
        out.append(Finding(
            id="ACCESS_NO_LLMS_TXT", category="access", severity="low",
            title="No /llms.txt file", evidence=[ev("url", f"{site.llms.url} → not found", site.llms.call_id)],
            ai_impact="llms.txt is an emerging convention for pointing AI tools at key pages. It is not a proven ranking factor and support varies by tool.",
            search_impact="No known effect on search rank.",
            fix=Fix(steps=["Optional: publish a short Markdown index of your most important pages."],
                    snippet=f"# {sn.brand_from(host_of(d.url))}\n\n> One-line description of the site.\n\n## Key pages\n- [{d.h1 or 'Page'}]({d.target.final_url}): what it covers\n",
                    snippet_lang="markdown", effort_minutes=15, where_to_paste=f"{site.origin}/llms.txt"),
            confidence="observed"))
    if site.sitemap.status == "missing":
        out.append(Finding(
            id="ACCESS_NO_SITEMAP", category="access", severity="low",
            title="No /sitemap.xml at the default location", evidence=[ev("url", f"{site.sitemap.url} → not found", site.sitemap.call_id)],
            ai_impact="Crawlers fall back to link discovery.", search_impact="Slower discovery of new or deep pages.",
            fix=Fix(steps=["Generate a sitemap and reference it in robots.txt with a `Sitemap:` line."],
                    snippet=f"Sitemap: {site.origin}/sitemap.xml", snippet_lang="text", effort_minutes=15, where_to_paste=f"{site.origin}/robots.txt"),
            confidence="observed"))
    elif site.sitemap_contains(d.target.final_url) is False:
        out.append(Finding(
            id="ACCESS_SITEMAP_MISSING_TARGET", category="access", severity="medium",
            title="Target URL is not listed in sitemap.xml",
            evidence=[ev("url", f"{d.target.final_url} not among {len(site.sitemap_urls)} URLs in {site.sitemap.url}", site.sitemap.call_id)],
            ai_impact="Crawlers that rely on sitemaps will not be told about this page.", search_impact="Discovery depends on internal links alone.",
            fix=Fix(steps=["Add the URL to the sitemap."], snippet=f"<url>\n  <loc>{d.target.final_url}</loc>\n</url>", snippet_lang="xml",
                    effort_minutes=10, where_to_paste=site.sitemap.url), confidence="observed"))
