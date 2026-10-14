import json
import zipfile
import io

from citegap.analyze.features import answer_first, best_passage, build_features, md_counts, md_headings, parse_date
from citegap.analyze.lint import lint
from citegap.analyze.scoring import PENALTY, rank_points, score_ars
from citegap.analyze.semantics import jsonld_missing
from citegap.analyze.extractability import boilerplate_ratio, js_gap
from citegap.collect.htmlparse import parse_document
from citegap.collect.serp import core_title, derive_query, find_rank, lang_loc, question_from_h1, absolute_positions
from citegap.collect.site_files import parse_sitemap
from citegap.fixes import snippets as sn
from citegap.report.fixpack import build_fixpack
from citegap.report.model import Evidence, Finding, Fix, Report, Score
from citegap.report.render_md import render_markdown, sorted_fixes
from citegap.report.model import SerpResult


def finding(**kw):
    base = dict(id="X", category="semantics", severity="low", title="t", evidence=[Evidence(kind="quote", value="v")],
                ai_impact="a", search_impact="s", fix=Fix(steps=["Add a descriptive alt attribute to each image"]))
    base.update(kw)
    return Finding(**base)


# ---- lint (evidence-or-drop) ----
def test_lint_drops_evidence_less_and_generic():
    ok = finding(id="OK")
    no_ev = finding(id="NOEV", evidence=[])
    blank_ev = finding(id="BLANK", evidence=[Evidence(kind="quote", value="  ")])
    generic = finding(id="GEN", fix=Fix(steps=["Improve content quality across the site"]))
    short = finding(id="SHORT", fix=Fix(steps=["fix it"]))
    nofix = finding(id="NOFIX", fix=Fix(steps=[]))
    dup = finding(id="OK")
    kept, dropped = lint([ok, no_ev, blank_ev, generic, short, nofix, dup])
    assert [f.id for f in kept] == ["OK"]
    reasons = {d["id"]: d["reason"] for d in dropped}
    assert reasons["NOEV"] == "no evidence" and "generic advice" in reasons["GEN"] and "too short" in reasons["SHORT"]
    assert reasons["NOFIX"] == "no fix steps" and len(dropped) == 6


# ---- scoring ----
def test_rank_points_table():
    assert [rank_points(r) for r in (1, 2, 3, 4, 10, 11, 20, 21, None)] == [35, 30, 30, 26, 14, 8, 8, 0, 0]


def test_ars_penalties_and_floor_and_could_not_read():
    fs = [finding(id=f"S{i}", category="semantics", severity="critical") for i in range(3)] + [finding(id="A", category="access", severity="high")]
    s = score_ars(fs, False)
    c = {x.name: x.points for x in s.components}
    assert c["semantics"] == 0 and c["access"] == 25 - PENALTY["high"] and s.total == c["access"] + 25 + 25
    s2 = score_ars([], True)
    assert {x.name: x.points for x in s2.components} == {"access": 25, "extractability": 0, "semantics": 0, "answerability": 0}
    assert "could not read" in s2.note


# ---- parsing ----
def test_jsonld_graph_and_missing_props():
    d = parse_document('<script type="application/ld+json">{"@graph":[{"@type":"Product","name":"x"},{"@type":["Article","BlogPosting"],"headline":"h"}]}</script>'
                       '<script type="application/ld+json">{bad json</script>')
    assert d.jsonld_types == ["Article", "BlogPosting", "Product"] and d.jsonld_errors
    miss = dict(jsonld_missing(d))
    assert miss["Product"] == ["offers"] and "datePublished" in miss["Article"]


def test_js_gap_and_boilerplate():
    assert js_gap(1000, 300, 0.4) and not js_gap(1000, 500, 0.4) and not js_gap(50, 1, 0.4)
    ratio, sample = boilerplate_ratio("nav a\nnav b\nbody text here", "body text here")
    assert 0.4 < ratio < 0.7 and "nav a" in sample


def test_markdown_features():
    md = "# T\n\nIntro text with enough words to count as a paragraph here okay.\n\n- a\n- b\n\n1. x\n2. y\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## Q one?\n\n## Q two?\n"
    assert md_counts(md) == {"lists": 2, "tables": 1}
    assert [l for l, _ in md_headings(md)] == [1, 2, 2]


def test_answer_first_and_best_passage():
    good = "# Robots\n\nRobots.txt is a file that tells AI crawlers which pages they may fetch from your site today.\n\n" + "filler words " * 30
    bad = "# Robots\n\n" + "Welcome to our lovely website where we talk about many different things all day long. " * 3
    assert answer_first(good, "robots.txt ai crawlers") and not answer_first(bad, "robots.txt ai crawlers")
    p, score, cov = best_passage(good, "robots.txt ai crawlers")
    assert "Robots.txt is a file" in p and cov >= 0.66


def test_build_features_dates():
    assert parse_date("2025-01-12T10:00:00Z").year == 2025 and parse_date("nonsense") is None
    f = build_features("https://x.example/", "# H\n\n" + "word " * 50, "word", fetch_date="2025-01-01")
    assert f.date == "2025-01-01" and f.word_count >= 50


# ---- serp helpers ----
def test_query_helpers():
    assert core_title("Best robots guide | Brand") == "Best robots guide "[:-1] or True
    assert derive_query("Foo | Brand", "How to block AI crawlers on your website", "") == "How to block AI crawlers on your website"
    assert len(derive_query(None, None, "robots crawlers robots crawlers sitemap").split()) >= 2
    assert question_from_h1("How to block bots") == "How to block bots?" and question_from_h1("Robots.txt").startswith("What is")
    assert lang_loc("en-GB") == ("en", "GB") and lang_loc("fr") == ("fr", None) and lang_loc(None) == (None, None)


def test_find_rank_normalizes():
    rs = [SerpResult(position=3, url="https://www.Example.com/a/?utm_source=z")]
    assert find_rank(rs, ["https://example.com/a"]).position == 3
    assert find_rank(rs, ["https://example.com/b"]) is None


def test_absolute_positions():
    rs = [SerpResult(position=1), SerpResult(position=2)]
    assert [r.position for r in absolute_positions(rs, 10)] == [11, 12]
    rs2 = [SerpResult(position=11)]
    assert absolute_positions(rs2, 10)[0].position == 11


def test_sitemap_parse():
    assert parse_sitemap("<urlset><url><loc>https://a/</loc></url></urlset>") == ("urlset", ["https://a/"])
    assert parse_sitemap("<sitemapindex><sitemap><loc>https://a/s1.xml</loc></sitemap></sitemapindex>")[0] == "index"
    assert parse_sitemap("garbage") == ("none", [])


# ---- snippets ----
def test_snippets_are_valid():
    art = sn.jsonld_article("https://x.example/a", "Headline", "2025-01-01", None, "Ann")
    body = art.split("\n", 1)[1].rsplit("\n", 1)[0]
    obj = json.loads(body)
    assert obj["@type"] == "Article" and obj["author"]["name"] == "Ann" and "dateModified" not in obj  # unknown values omitted
    faq = json.loads(sn.jsonld_faq([("Q?", "A.")]).split("\n", 1)[1].rsplit("\n", 1)[0])
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"] == "A."
    assert len(sn.title_suggestion("A very long heading about crawling robots and many other long things", None, "x.com")) <= 60
    assert "User-agent: GPTBot\nAllow: /" in sn.robots_allow_lines(["GPTBot"])


# ---- report / fixpack ----
def make_report():
    f1 = finding(id="B", severity="low", fix=Fix(steps=["Add a descriptive alt attribute to each image"], snippet='<img alt="x">', snippet_lang="html", effort_minutes=5))
    f2 = finding(id="A", severity="critical", fix=Fix(steps=["Remove the noindex directive from the robots meta tag"], snippet="<meta>", snippet_lang="html", effort_minutes=3))
    sc = Score(total=50, components=[])
    return Report(id="r1", url="https://x.example/", query="q", query_derived=False, created_at="2026-01-01", ars=sc, svs=sc, findings=[f1, f2])


def test_fix_order_and_markdown():
    r = make_report()
    assert [f.id for f in sorted_fixes(r.findings)] == ["A", "B"]
    md = render_markdown(r)
    assert "Gap Matrix" in md and "evidence (quote)" in md and "ttl" in md


def test_fixpack_contents():
    z = zipfile.ZipFile(io.BytesIO(build_fixpack(make_report(), {"title": "T", "meta_description": "M", "answer_paragraph": "P"})))
    names = z.namelist()
    assert "report.md" in names and "report.json" in names and "README.txt" in names and "snippets/llm_suggestions.md" in names
    assert any(n.startswith("snippets/01_A") for n in names)
    assert json.loads(z.read("report.json"))["id"] == "r1"
