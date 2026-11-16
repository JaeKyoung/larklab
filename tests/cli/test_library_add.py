"""db-add: fetching, previewing and storing a paper."""

import pytest

from larklab.cli.library import add
from larklab.cli.library.add import add_paper
from larklab.models import Paper


@pytest.fixture
def fetch_returns(monkeypatch):
    def install(paper: Paper):
        monkeypatch.setattr(add, "fetch_paper_metadata", lambda doi, url: paper)

    return install


def _fetched(**overrides) -> Paper:
    fields = {
        "title": "RFD4-Proteina",
        "authors": ["Corley, Nathaniel"],
        "journal": "",
        "abstract": "An abstract.",
        "doi": "10.64898/2026.11.12.766037",
    }
    return Paper(**{**fields, **overrides})


def test_add_saves_the_paper_with_a_journal_override(run, fetch_returns, repository):
    fetch_returns(_fetched())

    result = run(
        add_paper, ["10.64898/2026.11.12.766037", "--journal", "bioRxiv"], "y\n"
    )

    assert result.exit_code == 0, result.output
    assert "Saved (id=1)" in result.output
    stored = repository.get_by_id(1)
    assert (stored.title, stored.journal) == ("RFD4-Proteina", "bioRxiv")
    assert repository.ids_without_embedding() == []


def test_add_warns_about_missing_fields_and_defaults_to_no(
    run, fetch_returns, repository
):
    fetch_returns(_fetched())  # journal is empty

    result = run(add_paper, ["10.64898/x"], "\n")  # accept the default answer

    assert "Missing: journal" in result.output
    assert "Cancelled." in result.output
    assert repository.count() == 0


def test_add_refuses_a_paper_without_a_doi(run, fetch_returns, repository):
    fetch_returns(_fetched(doi=""))

    result = run(add_paper, ["https://example.com/paper"])

    assert result.exit_code != 0
    assert "DOI is required" in result.output
    assert repository.count() == 0


def test_add_refuses_a_paper_without_a_title(run, fetch_returns):
    fetch_returns(_fetched(title=""))

    result = run(add_paper, ["10.1/x"])

    assert result.exit_code != 0
    assert "--title" in result.output


@pytest.mark.parametrize(
    ("answer", "message", "expected_title"),
    [
        ("skip", "Skipped.", "Existing"),
        ("update", "Updated paper (id=1)", "RFD4-Proteina"),
        ("new", "Saved (id=2)", "Existing"),
    ],
)
def test_add_asks_what_to_do_about_a_near_duplicate(
    run, fetch_returns, repository, make_paper, one_hot, answer, message, expected_title
):
    repository.add(make_paper("Existing", embedding=one_hot(0)))
    fetch_returns(_fetched(journal="bioRxiv"))

    result = run(add_paper, ["10.64898/x"], f"y\n{answer}\n")

    assert message in result.output
    assert repository.get_by_id(1).title == expected_title


def test_add_reports_a_title_clash_instead_of_a_traceback(
    run, fetch_returns, repository, make_paper, one_hot
):
    repository.add(make_paper("RFD4-Proteina", doi="10.1/other", embedding=one_hot(0)))
    fetch_returns(_fetched(journal="bioRxiv"))

    result = run(add_paper, ["10.64898/x"], "y\nnew\n")

    assert result.exit_code != 0
    assert "already has this title" in result.output
    assert "Traceback" not in result.output
