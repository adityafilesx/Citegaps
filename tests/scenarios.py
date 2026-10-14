"""Two realistic fake sites for end-to-end tests."""
from __future__ import annotations

from fakes import FakeTinyFish, FakeWeb, para

QUERY = "robots.txt for ai crawlers"

# ---------- Scenario A: JS-rendered blog post, not indexed, blocks OAI-SearchBot ----------
A_URL = "https://smallblog.example/posts/robots-for-ai"
A_CONTENT = "\n\n".join([f"## Section {i}\n\n" + para(60, "robots") for i in range(1, 6)])
A_JUNK = "\n".join(f"Cookie settings and privacy notice item {i} subscribe to newsletter" for i in range(45))
A_MD = f"# How to configure robots.txt for AI crawlers\n\n{A_JUNK}\n\n{A_CONTENT}\n"
A_MAIN = f"# How to configure robots.txt for AI crawlers\n\n{A_CONTENT}\n"
A_HTML = ("<html lang='en'><head><title>x</title></head><body><nav>menu</nav><main><h1>How to configure robots.txt for AI crawlers</h1>"
          "<h2>Section 1</h2><h4>Skipped level</h4><img src='/a.png'><img src='/b.png'><img src='/c.png'><img src='/d.png' alt='ok'>"
          "<a href='/x'>click here</a><a href='/y'>read more</a><p>" + para(40) + "</p></main></body></html>")
A_RAW = ("<html><head><title>Robots.txt, AI crawlers, SEO tips, guides and many more things about crawling the web | SmallBlog</title>"
         "<meta name='robots' content='max-snippet:0'></head><body><div id='root'></div><p>" + para(30) + "</p></body></html>")
A_ROBOTS = "User-agent: *\nAllow: /\n\nUser-agent: OAI-SearchBot\nDisallow: /posts/\n\nUser-agent: GPTBot\nDisallow: /\n"

COMP = [
    ("https://guides.example/robots-ai", "Robots.txt for AI crawlers: the complete guide", "Robots.txt controls AI crawlers. Updated Jan 12, 2025 - 4.8 rating"),
    ("https://docs.other.example/crawlers", "AI crawler reference", "A reference of AI user agents and robots.txt rules."),
    ("https://news.example/ai-bots", "Which AI bots respect robots.txt?", "Robots.txt is a file that tells bots what they may fetch."),
]


def comp_md(title: str) -> str:
    body = f"# {title}\n\nRobots.txt is a file that tells AI crawlers which pages they may fetch. " + para(120, "robots") + "\n\n"
    body += "\n\n".join(f"## Q{i} Which crawler?\n\n- GPTBot\n- ClaudeBot\n- PerplexityBot\n\n| bot | owner |\n|---|---|\n| GPTBot | OpenAI |\n" + para(150, "crawlers") for i in range(5))
    return body


def scenario_a(highlights_enabled: bool = True):
    pages = {A_URL: {"md": A_MD, "main_md": A_MAIN, "html": A_HTML, "title": "How to configure robots.txt", "language": "en"},
             "https://smallblog.example/robots.txt": {"md": A_ROBOTS},
             "https://smallblog.example/llms.txt": {"error": "page_not_found", "status": 404},
             "https://smallblog.example/sitemap.xml": {"md": "<?xml version='1.0'?><urlset><url><loc>https://smallblog.example/posts/other</loc></url></urlset>"}}
    for u, t, _ in COMP:
        pages[u] = {"md": comp_md(t), "title": t, "published_date": "2025-01-12", "author": "Ann",
                    "highlights": ["Robots.txt is a file that tells AI crawlers which pages they may fetch."]}
    pages[A_URL]["highlights"] = []

    def search(q, p):
        if p.get("include_domains") == "smallblog.example":
            return [{"title": "Other post", "snippet": "something", "url": "https://smallblog.example/posts/other", "site_name": "smallblog.example"}]
        if q.startswith('"'):
            return []
        return [{"title": t, "snippet": s, "url": u, "site_name": u.split("/")[2]} for u, t, s in COMP]

    fake = FakeTinyFish(pages, search, highlights_enabled=highlights_enabled)
    web = FakeWeb({A_URL: (200, {"content-type": "text/html"}, A_RAW),
                   "https://smallblog.example/robots.txt": (200, {}, A_ROBOTS),
                   **{u: (200, {"content-type": "text/html"}, "<html><head><title>" + t + "</title></head><body><h1>" + t + "</h1></body></html>")
                      for u, t, _ in COMP}})
    return fake, web


# ---------- Scenario B: ranks #14, title rewritten, bot-challenged ----------
B_URL = "https://shop.example/guides/crawler-rules"
B_RAW = ("<html lang='en'><head><title>Crawler rules</title><link rel='canonical' href='https://shop.example/guides/crawler-rules'>"
         "<meta name='description' content='Rules for crawlers and how to set them up on your site today'>"
         "<script type='application/ld+json'>{\"@context\":\"https://schema.org\",\"@type\":\"Article\",\"headline\":\"Crawler rules\"}</script>"
         "</head><body><main><h1>Crawler rules</h1><p>" + para(300) + "</p></main></body></html>")
B_MD = "# Crawler rules\n\n" + para(300) + "\n"


def scenario_b():
    pages = {B_URL: {"md": B_MD, "main_md": B_MD, "html": B_RAW, "title": "Crawler rules"},
             "https://shop.example/robots.txt": {"error": "page_not_found", "status": 404},
             "https://shop.example/llms.txt": {"error": "page_not_found", "status": 404},
             "https://shop.example/sitemap.xml": {"error": "page_not_found", "status": 404}}
    for u, t, _ in COMP:
        pages[u] = {"md": comp_md(t), "title": t, "published_date": "2025-01-12", "highlights": ["Robots.txt tells crawlers what to fetch."]}
    pages[B_URL]["highlights"] = ["Rules for crawlers"]

    def search(q, p):
        page = int(p.get("page", 0))
        if p.get("include_domains") == "shop.example":
            return [{"title": "Totally Different Title - Shop", "snippet": "Home | Cookie settings | Sign in", "url": B_URL, "site_name": "shop.example"}]
        if q.startswith('"'):
            return [{"title": "Totally Different Title - Shop", "snippet": "Home | Cookie settings | Sign in", "url": B_URL, "site_name": "shop.example"}]
        if page == 0:
            return [{"title": t, "snippet": s, "url": u, "site_name": u.split("/")[2]} for u, t, s in COMP] + [
                {"title": f"filler {i}", "snippet": "x", "url": f"https://filler{i}.example/", "site_name": f"filler{i}.example"} for i in range(7)]
        return [{"title": f"filler p1 {i}", "snippet": "x", "url": f"https://f1-{i}.example/", "site_name": f"f1-{i}.example"} for i in range(3)] + [
            {"title": "Totally Different Title - Shop", "snippet": "Home | Cookie settings | Sign in", "url": B_URL + "?utm_source=x", "site_name": "shop.example"}]

    fake = FakeTinyFish(pages, search)
    web = FakeWeb({B_URL: (200, {"content-type": "text/html"}, B_RAW)})
    return fake, web
