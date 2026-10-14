from citegap.collect.robots import check_access, parse_robots, sitemaps

ROBOTS = """
# comment
User-agent: *
Disallow: /private/
Allow: /private/public.html
Disallow: /*.pdf$

User-agent: GPTBot
User-agent: ClaudeBot
Disallow: /

User-agent: OAI-SearchBot
Disallow:

User-agent: PerplexityBot
Disallow: /blog/
Allow: /blog/open/

Sitemap: https://example.com/sitemap.xml
"""


def g():
    return parse_robots(ROBOTS)


def test_shared_group_blocks_both_bots_with_rule_line():
    for bot in ("GPTBot", "ClaudeBot"):
        allowed, rule, _ = check_access(g(), bot, "/anything")
        assert not allowed and rule.line == "Disallow: /"


def test_empty_disallow_allows():
    assert check_access(g(), "OAI-SearchBot", "/x")[0]


def test_longest_match_allow_beats_shorter_disallow():
    assert check_access(g(), "PerplexityBot", "/blog/open/post")[0]
    assert not check_access(g(), "PerplexityBot", "/blog/closed")[0]
    assert check_access(g(), "*", "/private/public.html")[0]


def test_wildcard_and_anchor():
    assert not check_access(g(), "Googlebot", "/files/a.pdf")[0]
    assert check_access(g(), "Googlebot", "/files/a.pdf.html")[0]


def test_fallback_star_group_and_no_group():
    assert not check_access(g(), "CCBot", "/private/x")[0]
    assert check_access(parse_robots(""), "GPTBot", "/")[0]


def test_ua_matching_is_case_insensitive_substring():
    assert not check_access(parse_robots("User-agent: gptbot\nDisallow: /"), "GPTBot", "/x")[0]


def test_sitemaps():
    assert sitemaps(ROBOTS) == ["https://example.com/sitemap.xml"]


def test_allow_wins_tie():
    groups = parse_robots("User-agent: *\nDisallow: /a\nAllow: /a")
    assert check_access(groups, "x", "/a")[0]
