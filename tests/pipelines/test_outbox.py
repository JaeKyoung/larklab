import json
from datetime import UTC, datetime, timedelta

from larklab.models import Paper, Recommendation
from larklab.pipelines.outbox import (
    load_outbox,
    merge_recommendations,
    save_outbox,
)


def _recommendation(
    title: str, score: float = 0.8, age_days: float | None = 1
) -> Recommendation:
    published = (
        datetime.now(UTC) - timedelta(days=age_days) if age_days is not None else None
    )
    paper = Paper(
        title=title,
        authors=["Doe, Jane"],
        journal="arXiv",
        abstract="abstract",
        doi=f"10.48550/arXiv.{title}",
        published_at=published,
    )
    return Recommendation(paper=paper, similar_papers=[("Reference", score)])


def test_nothing_waiting_when_there_is_no_file(tmp_path):
    assert load_outbox(tmp_path / "outbox.json") == []


def test_a_saved_recommendation_comes_back_unchanged(tmp_path):
    path = tmp_path / "outbox.json"
    original = _recommendation("One", score=0.73)

    save_outbox(path, [original])
    [restored] = load_outbox(path)

    assert restored.paper == original.paper
    assert restored.similar_papers == [("Reference", 0.73)]
    assert restored.score == 0.73


def test_saving_nothing_removes_the_file(tmp_path):
    """Once Slack took everything, the waiting list disappears."""
    path = tmp_path / "outbox.json"
    save_outbox(path, [_recommendation("One")])
    assert path.exists()

    save_outbox(path, [])

    assert not path.exists()


def test_saving_nothing_without_a_file_is_fine(tmp_path):
    save_outbox(tmp_path / "outbox.json", [])


def test_an_unreadable_file_means_nothing_is_waiting(tmp_path):
    path = tmp_path / "outbox.json"
    path.write_text("[{ not json")

    assert load_outbox(path) == []


def test_a_file_with_the_wrong_shape_means_nothing_is_waiting(tmp_path):
    path = tmp_path / "outbox.json"
    path.write_text('[{"paper": 5, "similar_papers": []}]')

    assert load_outbox(path) == []


def test_one_unreadable_entry_does_not_take_the_others_with_it(tmp_path, caplog):
    """E.g. a field this Paper does not know: the other papers still go out."""
    path = tmp_path / "outbox.json"
    save_outbox(path, [_recommendation("Good"), _recommendation("Odd")])
    entries = json.loads(path.read_text())
    entries[1]["paper"]["a_field_from_the_future"] = 1
    path.write_text(json.dumps(entries))

    assert [r.paper.title for r in load_outbox(path)] == ["Good"]
    assert "Skipping an unreadable outbox entry" in caplog.text


def test_papers_too_old_to_recommend_are_dropped_on_load(tmp_path):
    path = tmp_path / "outbox.json"
    save_outbox(
        path,
        [
            _recommendation("Fresh", age_days=2),
            _recommendation("Stale", age_days=40),
            _recommendation("Undated", age_days=None),
        ],
    )

    assert [r.paper.title for r in load_outbox(path)] == ["Fresh", "Undated"]


def test_merge_keeps_one_entry_per_paper_with_the_newest_score_best_first():
    waiting = [_recommendation("Same", score=0.6), _recommendation("Only waiting", 0.9)]
    new = [_recommendation("Same", score=0.7), _recommendation("Only new", 0.5)]

    merged = merge_recommendations(waiting, new)

    assert [(r.paper.title, r.score) for r in merged] == [
        ("Only waiting", 0.9),
        ("Same", 0.7),  # the new score replaced the waiting one
        ("Only new", 0.5),
    ]
