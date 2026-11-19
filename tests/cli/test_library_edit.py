"""db-edit and db-delete."""

import pytest

from larklab.cli.library.edit import delete_paper, edit_paper


def test_edit_reports_a_title_clash_instead_of_a_traceback(run, repository, make_paper):
    repository.add(make_paper("First"))
    repository.add(make_paper("Second"))

    result = run(edit_paper, ["2", "--title", "First"])

    assert result.exit_code != 0
    assert "already has this title" in result.output


def test_unknown_paper_ids_fail_with_a_nonzero_exit_code(run):
    assert run(delete_paper, ["99"]).exit_code != 0
    assert run(edit_paper, ["99", "--title", "X"]).exit_code != 0


def test_delete_asks_for_confirmation(run, repository, make_paper):
    repository.add(make_paper("Keep"))

    declined = run(delete_paper, ["1"], "n\n")
    confirmed = run(delete_paper, ["1"], "y\n")

    assert "Cancelled." in declined.output
    assert "Deleted paper (id=1)" in confirmed.output
    assert repository.count() == 0


def test_edit_updates_fields_and_refreshes_the_embedding(
    run, repository, make_paper, one_hot
):
    repository.add(make_paper("Old", embedding=one_hot(5)))
    repository.add(make_paper("Other", embedding=one_hot(1)))

    result = run(edit_paper, ["1", "--title", "New", "--authors", "A|B"])

    assert result.exit_code == 0, result.output
    edited = repository.get_by_id(1)
    assert (edited.title, edited.authors) == ("New", ["A", "B"])
    nearest, similarity = repository.search_similar(one_hot(0), limit=1)[0]
    assert nearest.id == 1  # re-embedded: `embed_paper` is stubbed to one_hot(0)
    assert similarity == pytest.approx(1.0, abs=1e-6)
