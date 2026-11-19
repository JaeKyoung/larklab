from datetime import UTC, datetime

import pytest

from larklab.models import SourceProgress
from larklab.pipelines.crawl_progress import advance_progress, load_progress

NOV_13 = datetime(2026, 11, 13, 18, 59, tzinfo=UTC)
NOV_14 = datetime(2026, 11, 14, 18, 59, tzinfo=UTC)


def test_missing_file_means_start_fresh(tmp_path):
    assert load_progress(tmp_path / "progress.json") == {}


def test_unreadable_file_means_start_fresh_not_a_crash(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("{ this is not json")

    assert load_progress(path) == {}


@pytest.mark.parametrize(
    "body",
    [
        '{"arxiv": 123}',
        '{"arxiv": null}',
        "[1, 2]",
        '{"arxiv": "2026-11-13T18:59:00+00:00"}',  # the shape before `seen` existed
        '{"arxiv": {"newest": "not a date", "seen": {}}}',
    ],
)
def test_a_file_with_the_wrong_shape_means_start_fresh_not_a_crash(tmp_path, body):
    """A hand-edited or damaged file must never stop the daily run."""
    path = tmp_path / "progress.json"
    path.write_text(body)

    assert load_progress(path) == {}


def test_progress_round_trips_with_timezones_and_seen_papers(tmp_path):
    path = tmp_path / "progress.json"
    progress = SourceProgress(NOV_13, seen={"10.1/a": NOV_13, "10.1/b": NOV_14})

    advance_progress(path, {"arxiv": progress})

    assert load_progress(path) == {"arxiv": progress}


def test_progress_only_moves_forward_and_sources_are_independent(tmp_path):
    path = tmp_path / "progress.json"
    advance_progress(
        path, {"arxiv": SourceProgress(NOV_14), "biorxiv": SourceProgress(NOV_13)}
    )

    advance_progress(path, {"arxiv": SourceProgress(NOV_13)})  # an older run

    assert load_progress(path) == {
        "arxiv": SourceProgress(NOV_14),  # not rewound
        "biorxiv": SourceProgress(NOV_13),
    }


def test_the_seen_papers_of_an_update_replace_the_old_ones(tmp_path):
    """The caller sends the full list to keep: what left the window is dropped."""
    path = tmp_path / "progress.json"
    advance_progress(path, {"arxiv": SourceProgress(NOV_13, seen={"10.1/old": NOV_13})})

    advance_progress(path, {"arxiv": SourceProgress(NOV_14, seen={"10.1/new": NOV_14})})

    assert load_progress(path)["arxiv"].seen == {"10.1/new": NOV_14}
