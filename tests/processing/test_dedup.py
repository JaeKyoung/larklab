from datetime import UTC, datetime, timedelta

from builders import scholar_paper

from larklab.models import ScholarPaper
from larklab.processing.dedup import dedup_and_group_by_date

NOON = datetime(2026, 11, 16, 12, tzinfo=UTC)


def _paper(title: str, received_at: datetime | None = NOON) -> ScholarPaper:
    return scholar_paper(title, received_at=received_at)


def test_repeated_titles_are_dropped_ignoring_case_and_spacing():
    digests = dedup_and_group_by_date(
        [_paper("Protein Design"), _paper(" protein design "), _paper("Other")]
    )

    assert [p.title for p in digests[0].papers] == ["Protein Design", "Other"]


def test_titles_differing_in_punctuation_are_distinct_papers():
    """The digest must never silently merge two papers: only exact repeats go."""
    digests = dedup_and_group_by_date([_paper("Hox-A1 genes"), _paper("Hox A1 genes")])

    assert len(digests[0].papers) == 2


def test_papers_are_grouped_by_day_newest_first():
    older = _paper("Older", NOON - timedelta(days=2))
    newer = _paper("Newer", NOON)

    digests = dedup_and_group_by_date([older, newer])

    assert [d.papers[0].title for d in digests] == ["Newer", "Older"]
    assert digests[0].date > digests[1].date


def test_papers_without_a_received_time_land_in_today():
    [digest] = dedup_and_group_by_date([_paper("No Date", received_at=None)])

    assert digest.papers[0].title == "No Date"
    assert digest.date == datetime.now().astimezone().date()


def test_nothing_in_nothing_out():
    assert dedup_and_group_by_date([]) == []
