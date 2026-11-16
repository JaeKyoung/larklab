from datetime import UTC, datetime

import pytest

from larklab.models import Paper, ScholarPaper
from larklab.processing.abstract_enricher import enrich_abstracts
from larklab.sources.papers import crossref_source, pubmed_source, web_page_source

FULL_ABSTRACT = "A much longer, complete abstract. " * 5


@pytest.fixture
def sources(monkeypatch, sleeps):
    """Fake the four sources; each returns what the test stored under its name."""
    answers: dict[str, object] = {}
    calls: list[str] = []

    def install(module, function, name):
        def fake(*args, **kwargs):
            calls.append(name)
            return answers.get(name)

        monkeypatch.setattr(module, function, fake)

    install(pubmed_source, "fetch_by_doi", "pubmed_doi")
    install(pubmed_source, "fetch_by_title", "pubmed_title")
    install(crossref_source, "fetch_by_doi", "crossref")
    install(web_page_source, "fetch_abstract", "html")
    answers["sleeps"] = sleeps
    return answers, calls


def _snippet_paper(url="https://doi.org/10.1000/abc", **fields) -> ScholarPaper:
    return ScholarPaper(
        title="A Paper",
        authors=[],
        journal="",
        abstract="short snippet",
        url=url,
        source_email_id="m1",
        received_at=datetime(2026, 11, 16, tzinfo=UTC),
        **fields,
    )


def _record(abstract="", doi="") -> Paper:
    return Paper(title="A Paper", authors=[], journal="", abstract=abstract, doi=doi)


def test_pubmed_abstract_replaces_the_snippet_and_stops_the_search(sources):
    answers, calls = sources
    answers["pubmed_doi"] = _record(FULL_ABSTRACT)

    [paper] = enrich_abstracts([_snippet_paper()])

    assert paper.abstract == FULL_ABSTRACT
    assert paper.doi == "10.1000/abc"
    assert calls == ["pubmed_doi"]


def test_snippet_is_kept_when_nothing_longer_is_found(sources):
    [paper] = enrich_abstracts([_snippet_paper()])

    assert paper.abstract == "short snippet"


def test_doi_found_through_a_title_search_is_attached(sources):
    answers, _ = sources
    answers["pubmed_title"] = _record(FULL_ABSTRACT, doi="10.1/found")

    [paper] = enrich_abstracts([_snippet_paper(url="https://example.com/no-doi")])

    assert (paper.doi, paper.abstract) == ("10.1/found", FULL_ABSTRACT)


def test_doi_of_an_unhelpful_title_match_is_not_adopted(sources):
    """A title search can hit the wrong record; its DOI must not leak in."""
    answers, calls = sources
    answers["pubmed_title"] = _record("", doi="10.9999/wrong")  # no usable abstract

    [paper] = enrich_abstracts([_snippet_paper(url="https://example.com/no-doi")])

    assert paper.doi is None
    assert "crossref" not in calls


def test_web_page_is_the_last_resort(sources):
    answers, calls = sources
    answers["html"] = FULL_ABSTRACT

    [paper] = enrich_abstracts([_snippet_paper()])

    assert paper.abstract == FULL_ABSTRACT
    assert calls == ["pubmed_doi", "pubmed_title", "crossref", "html"]


def test_a_failing_paper_keeps_its_snippet_and_does_not_stop_the_rest(
    sources, monkeypatch
):
    answers, _ = sources
    answers["pubmed_doi"] = _record(FULL_ABSTRACT)
    original_fetch = pubmed_source.fetch_by_doi

    def flaky(client, doi):
        if doi == "10.1000/boom":
            raise RuntimeError("network exploded")
        return original_fetch(client, doi)

    monkeypatch.setattr(pubmed_source, "fetch_by_doi", flaky)
    broken = _snippet_paper(url="https://doi.org/10.1000/boom")
    healthy = _snippet_paper(url="https://doi.org/10.1000/fine")

    first, second = enrich_abstracts([broken, healthy])

    assert first.abstract == "short snippet"
    assert second.abstract == FULL_ABSTRACT


def test_papers_found_in_pubmed_are_not_made_to_wait(sources):
    """Regression: every paper used to wait 2 seconds, so 80 papers took minutes."""
    answers, _ = sources
    answers["pubmed_doi"] = _record(FULL_ABSTRACT)

    enrich_abstracts(
        [_snippet_paper(f"https://doi.org/10.1000/p{i}") for i in range(5)]
    )

    assert answers["sleeps"] == []


def test_a_publisher_page_is_fetched_politely(sources):
    answers, _ = sources
    answers["html"] = FULL_ABSTRACT

    enrich_abstracts([_snippet_paper()])

    assert len(answers["sleeps"]) == 1
