from datetime import UTC, datetime

import pytest

from larklab.pipelines.crawl_progress import advance_progress, load_progress

NOV_13 = datetime(2026, 11, 13, 18, 59, tzinfo=UTC)
NOV_14 = datetime(2026, 11, 14, 18, 59, tzinfo=UTC)


def test_missing_file_means_start_fresh(tmp_path):
    assert load_progress(tmp_path / "progress.json") == {}


def test_unreadable_file_means_start_fresh_not_a_crash(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("{ this is not json")

    assert load_progress(path) == {}


@pytest.mark.parametrize("body", ['{"arxiv": 123}', '{"arxiv": null}', "[1, 2]"])
def test_a_file_with_the_wrong_shape_means_start_fresh_not_a_crash(tmp_path, body):
    """A hand-edited or damaged file must never stop the daily run."""
    path = tmp_path / "progress.json"
    path.write_text(body)

    assert load_progress(path) == {}


def test_progress_round_trips_with_timezones(tmp_path):
    path = tmp_path / "progress.json"

    advance_progress(path, {"arxiv": NOV_13})

    assert load_progress(path) == {"arxiv": NOV_13}


def test_progress_only_moves_forward_and_sources_are_independent(tmp_path):
    path = tmp_path / "progress.json"
    advance_progress(path, {"arxiv": NOV_14, "biorxiv": NOV_13})

    advance_progress(path, {"arxiv": NOV_13})  # an older run must not rewind it

    assert load_progress(path) == {"arxiv": NOV_14, "biorxiv": NOV_13}
