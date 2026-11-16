import httpx

from larklab.sources.papers import crossref_source


def _respond_with(message: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": message})

    return handler


def test_journal_article_uses_container_title(http_client):
    handler = _respond_with(
        {
            "title": ["A Title"],
            "container-title": ["Nature"],
            "author": [{"family": "Doe", "given": "Jane"}],
            "abstract": "<jats:p>Abstract text.</jats:p>",
        }
    )

    paper = crossref_source.fetch_by_doi(http_client(handler), "10.1038/x")

    assert (paper.title, paper.journal) == ("A Title", "Nature")
    assert paper.authors == ["Doe, Jane"]
    assert paper.abstract == "text."


def test_preprint_journal_comes_from_the_posting_institution(http_client):
    handler = _respond_with(
        {"title": ["A Preprint"], "institution": [{"name": "bioRxiv"}]}
    )

    paper = crossref_source.fetch_by_doi(http_client(handler), "10.64898/x")

    assert paper.journal == "bioRxiv"


def test_organisation_authors_are_kept_and_blank_ones_dropped(http_client):
    handler = _respond_with(
        {
            "title": ["T"],
            "author": [
                {"name": "The Consortium"},
                {"family": "Doe", "given": "Jane"},
                {},
            ],
        }
    )

    paper = crossref_source.fetch_by_doi(http_client(handler), "10.1/x")

    assert paper.authors == ["The Consortium", "Doe, Jane"]


def test_unknown_doi_returns_none(http_client):
    handler = _respond_with({}, status=404)
    assert crossref_source.fetch_by_doi(http_client(handler), "10.1/missing") is None


def test_record_without_title_returns_none(http_client):
    handler = _respond_with({"container-title": ["Nature"]})
    assert crossref_source.fetch_by_doi(http_client(handler), "10.1/x") is None


def test_clean_crossref_abstract_strips_tags_and_label():
    raw = "<jats:title>Abstract</jats:title><jats:p>We study  proteins.</jats:p>"
    assert crossref_source._clean_abstract(raw) == "We study proteins."


def test_clean_crossref_abstract_keeps_words_that_start_with_abstract():
    assert crossref_source._clean_abstract("Abstractive summarization is hard.") == (
        "Abstractive summarization is hard."
    )
    assert (
        crossref_source._clean_abstract("Abstract Proteins fold.") == "Proteins fold."
    )
