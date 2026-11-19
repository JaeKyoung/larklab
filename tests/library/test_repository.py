import sqlite3

import pytest

from larklab.library.embedder import EMBED_DIM
from larklab.library.repository import PaperRepository


def test_add_and_read_back(repository, make_paper, one_hot):
    paper_id = repository.add(make_paper("First", embedding=one_hot(0)))

    stored = repository.get_by_id(paper_id)
    assert (stored.title, stored.authors, stored.journal) == (
        "First",
        ["Doe, Jane"],
        "Nature",
    )
    assert repository.get_by_title("First").id == paper_id
    assert repository.get_by_id(999) is None
    assert repository.count() == 1


def test_titles_are_unique(repository, make_paper):
    repository.add(make_paper("Same"))
    with pytest.raises(sqlite3.IntegrityError):
        repository.add(make_paper("Same", doi="10.1/other"))
    assert repository.count() == 1


def test_search_similar_orders_by_cosine_similarity(repository, make_paper, one_hot):
    repository.add(make_paper("Near", embedding=one_hot(0)))
    repository.add(make_paper("Far", embedding=one_hot(1)))

    results = repository.search_similar(one_hot(0), limit=2)

    assert [paper.title for paper, _ in results] == ["Near", "Far"]
    assert results[0][1] == pytest.approx(1.0, abs=1e-6)  # the same direction
    assert results[1][1] == pytest.approx(0.0, abs=1e-6)  # orthogonal


def test_find_duplicates_by_title_and_by_embedding(repository, make_paper, one_hot):
    repository.add(make_paper("Existing", embedding=one_hot(0)))

    same_title = repository.find_duplicates(make_paper("Existing", doi="10.1/new"))
    near = repository.find_duplicates(make_paper("Reworded", embedding=one_hot(0)))
    unrelated = repository.find_duplicates(
        make_paper("Different", embedding=one_hot(5))
    )

    assert same_title[0][1] == 1.0
    assert near[0][0].title == "Existing"
    assert near[0][1] == pytest.approx(1.0, abs=1e-6)
    assert unrelated == []


def test_update_replaces_metadata_and_embedding(repository, make_paper, one_hot):
    paper_id = repository.add(make_paper("Old", embedding=one_hot(0)))

    repository.update(paper_id, make_paper("New", embedding=one_hot(1)))

    assert repository.get_by_id(paper_id).title == "New"
    assert repository.search_similar(one_hot(1), limit=1)[0][0].id == paper_id


def test_update_without_embedding_keeps_the_existing_one(
    repository, make_paper, one_hot
):
    paper_id = repository.add(make_paper("Old", embedding=one_hot(0)))

    repository.update(paper_id, make_paper("Retitled"))

    assert repository.ids_without_embedding() == []


def test_delete_removes_paper_and_embedding(repository, make_paper, one_hot):
    paper_id = repository.add(make_paper("Gone", embedding=one_hot(0)))

    assert repository.delete(paper_id) is True
    assert repository.delete(paper_id) is False
    assert repository.count() == 0
    vectors = repository._db.execute("SELECT COUNT(*) FROM papers_vec").fetchone()[0]
    assert vectors == 0  # no orphan vector left behind to crowd out neighbours


def test_ids_without_embedding_flags_unsearchable_papers(
    repository, make_paper, one_hot
):
    repository.add(make_paper("Searchable", embedding=one_hot(0)))
    missing_id = repository.add(make_paper("Unsearchable"))

    assert repository.ids_without_embedding() == [missing_id]


def test_replace_all_swaps_the_library_and_restarts_ids(
    repository, make_paper, one_hot
):
    repository.add(make_paper("Old A", embedding=one_hot(0)))
    repository.add(make_paper("Old B", embedding=one_hot(1)))

    stored = repository.replace_all(
        [
            make_paper("New A", embedding=one_hot(2)),
            make_paper("New A", doi="10.1/dup"),  # duplicate title is skipped
            make_paper("New B", embedding=one_hot(3)),
        ]
    )

    assert stored == 2
    assert [(p.id, p.title) for p in repository.list_papers()] == [
        (1, "New A"),
        (2, "New B"),
    ]
    assert repository.search_similar(one_hot(0), limit=5)[0][0].title != "Old A"


def test_replace_all_is_atomic(repository, make_paper, one_hot):
    """A failure half-way (here: a vector of the wrong size) keeps the old library."""
    repository.add(make_paper("Keep Me", embedding=one_hot(0)))
    bad_vector = [1.0] * (EMBED_DIM - 1)

    with pytest.raises(sqlite3.Error):
        repository.replace_all(
            [
                make_paper("Fine", embedding=one_hot(1)),
                make_paper("Bad", embedding=bad_vector),
            ]
        )

    assert [p.title for p in repository.list_papers()] == ["Keep Me"]
    assert repository.search_similar(one_hot(0), limit=1)[0][0].title == "Keep Me"


def test_replace_all_embeddings_is_atomic(repository, make_paper, one_hot):
    first = repository.add(make_paper("First", embedding=one_hot(0)))
    second = repository.add(make_paper("Second", embedding=one_hot(1)))

    with pytest.raises(sqlite3.Error):
        repository.replace_all_embeddings(
            {first: one_hot(2), second: [1.0] * (EMBED_DIM - 1)}
        )

    # old vectors survive the failed swap
    assert repository.search_similar(one_hot(0), limit=1)[0][0].id == first

    repository.replace_all_embeddings({first: one_hot(2), second: one_hot(3)})
    assert repository.search_similar(one_hot(2), limit=1)[0][0].id == first


def test_schema_migration_drops_legacy_url_column(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    with sqlite3.connect(db_path) as legacy:
        legacy.execute(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " title TEXT NOT NULL UNIQUE, authors TEXT NOT NULL,"
            " journal TEXT NOT NULL, abstract TEXT NOT NULL, url TEXT)"
        )
    legacy.close()

    with PaperRepository(db_path) as repo:
        columns = {r["name"] for r in repo._db.execute("PRAGMA table_info(papers)")}

    assert "url" not in columns
    assert "doi" in columns
