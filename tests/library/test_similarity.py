import pytest

from larklab.library import similarity
from larklab.library.similarity import find_similar_references


def test_scores_are_similarities_not_distances(
    repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Ref A", embedding=one_hot(0)))
    repository.add(make_paper("Ref B", embedding=one_hot(1)))
    papers = [make_paper("Close to A"), make_paper("Close to B")]
    monkeypatch.setattr(similarity, "embed_papers", lambda p: [one_hot(0), one_hot(1)])

    first, second = find_similar_references(papers, repository)

    assert first[0] == ("Ref A", pytest.approx(1.0, abs=1e-6))  # identical → 1, not 0
    assert first[1] == ("Ref B", pytest.approx(0.0, abs=1e-6))
    assert second[0][0] == "Ref B"


def test_at_most_three_references_are_returned(
    repository, make_paper, one_hot, monkeypatch
):
    for axis in range(5):
        repository.add(make_paper(f"Ref {axis}", embedding=one_hot(axis)))
    monkeypatch.setattr(similarity, "embed_papers", lambda p: [one_hot(0)])

    [similar] = find_similar_references([make_paper("Query")], repository)

    assert len(similar) == 3


def test_an_empty_library_gives_empty_lists_aligned_with_the_papers(
    repository, make_paper, one_hot, monkeypatch
):
    monkeypatch.setattr(similarity, "embed_papers", lambda p: [one_hot(0), one_hot(1)])

    assert find_similar_references([make_paper("A"), make_paper("B")], repository) == [
        [],
        [],
    ]
