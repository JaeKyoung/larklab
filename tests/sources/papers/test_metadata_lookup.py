"""The resolver is tested with fake sources: the point is the merge/ordering rules."""

import pytest

from larklab.models import Paper
from larklab.sources.papers import (
    arxiv_source,
    biorxiv_source,
    crossref_source,
    pubmed_source,
    web_page_source,
)
from larklab.sources.papers.metadata_lookup import fetch_paper_metadata

DOI_BIORXIV_2026 = "10.64898/2026.11.12.766037"


@pytest.fixture
def sources(monkeypatch):
    """Replace every source with a fake returning what the test sets. Records calls."""
    answers: dict[str, Paper | Exception | None] = {}
    calls: list[str] = []

    def install(module, function, name):
        def fake(*args, **kwargs):
            calls.append(name)
            answer = answers.get(name)
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(module, function, fake)

    install(pubmed_source, "fetch_by_doi", "pubmed")
    install(arxiv_source, "fetch_by_id", "arxiv")
    install(crossref_source, "fetch_by_doi", "crossref")
    install(biorxiv_source, "fetch_by_doi", "biorxiv")
    install(web_page_source, "fetch_paper", "html")
    return answers, calls


def _paper(**fields) -> Paper:
    return Paper(
        **{"title": "", "authors": [], "journal": "", "abstract": "", "doi": ""}
        | fields
    )


def test_new_biorxiv_prefix_still_gets_journal_and_full_author_list(sources):
    """Regression: 10.64898/ DOIs skipped bioRxiv and came back with no journal."""
    answers, calls = sources
    full_authors = [f"Author{i}, A." for i in range(61)]
    answers["crossref"] = _paper(
        title="RFD4", authors=full_authors, abstract="Abstract."
    )
    answers["biorxiv"] = _paper(
        title="RFD4", authors=full_authors[:45], journal="bioRxiv", abstract="Abstract."
    )

    paper = fetch_paper_metadata(DOI_BIORXIV_2026, client=object())

    assert paper.journal == "bioRxiv"
    assert len(paper.authors) == 61  # CrossRef's list wins over the truncated one
    assert calls == ["pubmed", "crossref", "biorxiv"]


def test_a_source_that_fails_does_not_stop_the_others(sources, caplog):
    answers, calls = sources
    answers["pubmed"] = RuntimeError("PubMed exploded")
    answers["crossref"] = _paper(
        title="T", authors=["A"], journal="Cell", abstract="Abstract."
    )

    paper = fetch_paper_metadata("10.1016/j.cell.2020.1", client=object())

    assert paper.title == "T"
    assert calls == ["pubmed", "crossref"]
    assert "A metadata source failed: PubMed exploded" in caplog.text


def test_a_failing_web_page_gives_an_empty_paper_not_a_crash(sources):
    answers, _ = sources
    answers["html"] = ValueError("unreadable page")

    paper = fetch_paper_metadata(url="https://example.com/paper", client=object())

    assert paper.title == ""


def test_stops_at_the_first_source_that_completes_the_record(sources):
    answers, calls = sources
    answers["pubmed"] = _paper(
        title="T", authors=["A"], journal="Cell", abstract="Abstract."
    )

    paper = fetch_paper_metadata("10.1016/j.cell.2020.1", client=object())

    assert paper.journal == "Cell"
    assert calls == ["pubmed"]


def test_later_sources_only_fill_gaps_and_never_overwrite(sources):
    answers, _ = sources
    answers["pubmed"] = _paper(title="PubMed title", authors=["A"], journal="Cell")
    answers["crossref"] = _paper(
        title="CrossRef title", authors=["B"], journal="Other", abstract="From CrossRef"
    )

    paper = fetch_paper_metadata("10.1016/x", client=object())

    assert paper.title == "PubMed title"
    assert paper.authors == ["A"]
    assert paper.journal == "Cell"
    assert paper.abstract == "From CrossRef"


def test_arxiv_dois_skip_pubmed_and_use_the_arxiv_api(sources):
    answers, calls = sources
    answers["arxiv"] = _paper(
        title="T", authors=["A"], journal="arXiv", abstract="Abstract."
    )

    fetch_paper_metadata("10.48550/arXiv.2401.01234", client=object())

    assert calls == ["arxiv"]


def test_arxiv_url_without_a_doi_is_resolved_through_the_arxiv_id(sources):
    answers, calls = sources
    answers["arxiv"] = _paper(
        title="T", authors=["A"], journal="arXiv", abstract="Abstract."
    )

    paper = fetch_paper_metadata(
        url="https://arxiv.org/abs/2401.01234", client=object()
    )

    assert calls == ["arxiv"]
    assert paper.doi == "10.48550/arXiv.2401.01234"


def test_html_is_a_last_resort_used_only_when_no_title_was_found(sources):
    answers, calls = sources
    answers["html"] = _paper(title="Scraped", authors=["A"], journal="Site")

    scraped = fetch_paper_metadata(
        "10.1/x", url="https://example.com/p", client=object()
    )
    assert scraped.title == "Scraped"
    assert calls[-1] == "html"

    calls.clear()
    answers["crossref"] = _paper(
        title="CrossRef title"
    )  # title found, still incomplete
    resolved = fetch_paper_metadata(
        "10.1/x", url="https://example.com/p", client=object()
    )
    assert resolved.title == "CrossRef title"
    assert "html" not in calls  # a meta-tag description must not fill the abstract


def test_arxiv_abstract_page_backs_up_a_failing_arxiv_api(sources):
    answers, calls = sources
    answers["html"] = _paper(title="Scraped", authors=["A"], journal="arXiv")

    paper = fetch_paper_metadata("10.48550/arXiv.2401.01234", client=object())

    assert paper.title == "Scraped"
    assert calls == ["arxiv", "crossref", "html"]


def test_version_suffix_on_a_bare_biorxiv_doi_is_dropped(sources):
    answers, _ = sources
    seen = []
    answers["pubmed"] = None
    answers["crossref"] = _paper(title="T", authors=["A"], journal="J", abstract="x")

    paper = fetch_paper_metadata("10.1101/2024.01.01.123456v2", client=object())

    assert paper.doi == "10.1101/2024.01.01.123456"
    assert seen == []


def test_journal_names_are_canonicalised(sources):
    answers, _ = sources
    answers["pubmed"] = _paper(
        title="T",
        authors=["A"],
        journal="bioRxiv : the preprint server for biology",
        abstract="Abstract.",
    )

    paper = fetch_paper_metadata("10.1101/2020.01.01.000001", client=object())

    assert paper.journal == "bioRxiv"


def test_unknown_paper_comes_back_empty_but_keeps_the_doi(sources):
    paper = fetch_paper_metadata("10.1/unknown", client=object())

    assert paper == Paper.empty("10.1/unknown")


def test_doi_is_recovered_from_the_url(sources):
    answers, calls = sources
    answers["pubmed"] = _paper(
        title="T", authors=["A"], journal="Nature", abstract="Abstract."
    )

    paper = fetch_paper_metadata(
        url="https://doi.org/10.1038/s41586-021-03819-2", client=object()
    )

    assert paper.doi == "10.1038/s41586-021-03819-2"


def test_a_shared_client_is_used_when_given(sources, monkeypatch):
    marker = object()
    seen = []
    monkeypatch.setattr(
        pubmed_source, "fetch_by_doi", lambda client, doi: seen.append(client)
    )

    fetch_paper_metadata("10.1/x", client=marker)

    assert seen == [marker]
