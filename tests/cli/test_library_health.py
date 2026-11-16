"""db-check and db-rebuild."""

from larklab.cli.library import health
from larklab.cli.library.health import check_papers, rebuild_embeddings


def test_check_reports_papers_missing_their_embedding(
    run, repository, make_paper, one_hot
):
    repository.add(make_paper("Fine", embedding=one_hot(0)))
    repository.add(make_paper("Unsearchable"))

    result = run(check_papers, [])

    assert "[2] Unsearchable" in result.output
    assert "missing: embedding" in result.output
    assert "[1] Fine" not in result.output
    assert "1 issue(s) found." in result.output


def test_check_refetch_shows_what_changed_and_survives_failures(
    run, repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Stored Title", journal="Biorxiv", embedding=one_hot(0)))
    repository.add(make_paper("Unreachable", embedding=one_hot(1)))

    def fetch(doi, client=None):
        if "unreachable" in doi:
            raise RuntimeError("boom")
        return make_paper("Stored Title", journal="bioRxiv")

    monkeypatch.setattr(health, "fetch_paper_metadata", fetch)

    result = run(check_papers, ["--refetch"])

    assert "changed: journal" in result.output
    assert "DB:      Biorxiv" in result.output
    assert "Fetched: bioRxiv" in result.output
    assert "[2] re-fetch failed" in result.output


def test_check_is_quiet_when_everything_is_fine(run, repository, make_paper, one_hot):
    repository.add(make_paper("Fine", embedding=one_hot(0)))

    assert "All 1 papers OK." in run(check_papers, []).output


def test_rebuild_gives_every_paper_an_embedding(run, repository, make_paper):
    repository.add(make_paper("One"))
    repository.add(make_paper("Two"))

    result = run(rebuild_embeddings, [])

    assert "Rebuilt embeddings for 2 papers." in result.output
    assert repository.ids_without_embedding() == []
