"""db-search (and db-list)."""

from larklab.cli.library.browse import search_paper


def test_search_requires_a_query_or_journal(run):
    assert run(search_paper, []).exit_code != 0
