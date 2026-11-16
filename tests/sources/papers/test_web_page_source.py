import httpx
from bs4 import BeautifulSoup

from larklab.sources.papers.web_page_source import (
    extract_abstract,
    fetch_abstract,
    fetch_paper,
)

ARTICLE_PAGE = """
<html><head>
<title>Site title</title>
<meta name="citation_title" content="  A Study of Proteins ">
<meta name="citation_author" content="Doe, Jane">
<meta name="citation_author" content="Roe, Rich">
<meta name="citation_journal_title" content="Cell Systems">
<meta name="citation_doi" content="10.1016/j.cels.2024.01.001">
<meta property="og:description" content="Meta description of the study.">
</head><body></body></html>
"""


def _page(html: str, status: int = 200):
    return lambda request: httpx.Response(status, text=html)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# --- site-specific abstract parsing --------------------------------------------


def test_arxiv_abstract_loses_its_leading_label():
    html = (
        '<blockquote class="abstract"><span class="descriptor">Abstract:</span>'
        "  We fold proteins.</blockquote>"
    )
    assert extract_abstract(_soup(html), "https://arxiv.org/abs/2401.01234") == (
        "We fold proteins."
    )


def test_arxiv_page_without_an_abstract_block_does_not_fall_back_to_meta_tags():
    html = '<meta property="og:description" content="Marketing blurb">'
    assert extract_abstract(_soup(html), "https://arxiv.org/abs/2401.01234") is None


def test_nature_abstract_drops_footnote_markers():
    html = '<div id="Abs1-content">Proteins fold<sup>1</sup> quickly.</div>'
    assert extract_abstract(_soup(html), "https://www.nature.com/articles/x") == (
        "Proteins fold quickly."
    )


def test_pubmed_abstract_comes_from_the_abstract_block():
    html = '<div class="abstract-content"> Background text. </div>'
    assert extract_abstract(_soup(html), "https://pubmed.ncbi.nlm.nih.gov/1/") == (
        "Background text."
    )


def test_other_sites_use_the_meta_description():
    assert extract_abstract(_soup(ARTICLE_PAGE), "https://example.org/p") == (
        "Meta description of the study."
    )


# --- building a paper from a page ------------------------------------------------


def test_citation_meta_tags_become_a_paper(http_client):
    client = http_client(_page(ARTICLE_PAGE))

    paper = fetch_paper(client, "https://example.org/p")

    assert paper.title == "A Study of Proteins"
    assert paper.authors == ["Doe, Jane", "Roe, Rich"]
    assert paper.journal == "Cell Systems"
    assert paper.doi == "10.1016/j.cels.2024.01.001"
    assert paper.abstract == "Meta description of the study."


def test_a_known_doi_wins_over_the_page_and_preprint_hosts_name_the_journal(
    http_client,
):
    html = (
        '<meta name="citation_title" content="T">'
        '<meta name="citation_doi" content="10.9/page">'
    )

    paper = fetch_paper(
        http_client(_page(html)), "https://www.biorxiv.org/content/x", doi="10.1/known"
    )

    assert paper.doi == "10.1/known"
    assert paper.journal == "bioRxiv"


def test_a_cloudflare_challenge_page_is_not_mistaken_for_a_paper(http_client):
    html = '<title>Just a moment...</title><div id="challenge-error-text"></div>'

    assert fetch_paper(http_client(_page(html)), "https://example.org/p") is None


def test_missing_pages_and_untitled_pages_give_nothing(http_client):
    assert (
        fetch_paper(http_client(_page("", status=404)), "https://example.org/p") is None
    )
    assert (
        fetch_paper(http_client(_page("<html></html>")), "https://example.org/p")
        is None
    )


# --- fetching an abstract with retries ----------------------------------------


def test_transient_errors_are_retried(http_client):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, text=ARTICLE_PAGE)

    abstract = fetch_abstract(http_client(handler), "https://example.org/p")

    assert abstract == "Meta description of the study."
    assert len(attempts) == 3


def test_client_errors_are_final_and_not_retried(http_client):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(403)

    assert fetch_abstract(http_client(handler), "https://example.org/p") is None
    assert len(attempts) == 1


def test_a_redirect_loop_gives_up_quietly():
    def handler(request):
        return httpx.Response(302, headers={"Location": str(request.url)})

    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        assert fetch_abstract(client, "https://example.org/loop") is None
