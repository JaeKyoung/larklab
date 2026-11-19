from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import arxiv
import requests

from larklab.sources.papers import arxiv_source
from larklab.sources.papers.arxiv_source import crawl_recent, fetch_by_id

MODULE = "larklab.sources.papers.arxiv_source"


def _ago(**delta) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


def _result(title: str, published: datetime | None = None):
    result = Mock()
    result.published = published or _ago(days=1)
    result.title = title
    result.authors = []
    result.summary = "abstract"
    result.doi = None
    result.get_short_id.return_value = "2605.12345v1"
    return result


def _crawl_returning(*batches, **options):
    """Run crawl_recent with one canned result list per category query."""
    options.setdefault("max_results", 5)
    with patch(f"{MODULE}.arxiv.Client") as client_cls:
        client_cls.return_value.results.side_effect = list(batches)
        return crawl_recent(**options)


def test_crawl_continues_after_category_network_error():
    crawl = _crawl_returning(
        requests.ConnectionError("dns failed"),
        [_result("Recovered Paper")],
        categories=["cs.LG", "cs.AI"],
    )

    assert [p.title for p in crawl.papers] == ["Recovered Paper"]


def test_a_category_that_could_not_be_read_makes_the_crawl_incomplete():
    """Regression: the caller used to move on as if everything had been read."""
    crawl = _crawl_returning(
        requests.ConnectionError("dns failed"),
        [_result("Fine")],
        categories=["cs.LG", "cs.AI"],
    )

    assert crawl.complete is False


def test_crawl_retries_category_after_rate_limit():
    with patch(f"{MODULE}.time.sleep") as sleep:
        crawl = _crawl_returning(
            arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 429),
            [_result("Recovered After Backoff")],
            categories=["cs.LG"],
        )

    sleep.assert_called_once()
    assert [p.title for p in crawl.papers] == ["Recovered After Backoff"]
    assert crawl.complete is True  # the retry worked: everything was read


def test_a_second_rate_limit_gives_up_on_the_category_and_marks_it_incomplete():
    error = arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 429)
    with patch(f"{MODULE}.time.sleep"):
        crawl = _crawl_returning(error, error, categories=["cs.LG"])

    assert crawl.papers == []
    assert crawl.complete is False


def test_crawl_skips_papers_repeated_across_categories():
    crawl = _crawl_returning(
        [_result("Shared Paper")],
        [_result("shared paper.")],  # same title, different case/punctuation
        categories=["cs.LG", "cs.AI"],
    )

    assert len(crawl.papers) == 1


def test_busy_categories_are_not_cut_off_at_a_few_hundred_papers():
    """Regression: a 200-paper cap dropped the older part of a busy announcement."""
    with patch(f"{MODULE}.arxiv.Client") as client_cls:
        client_cls.return_value.results.return_value = []
        with patch(f"{MODULE}.arxiv.Search") as search_cls:
            crawl_recent(categories=["cs.LG"])

    assert search_cls.call_args.kwargs["max_results"] >= 1000


def test_a_category_that_hits_the_cap_before_the_cutoff_makes_the_crawl_incomplete():
    """Regression: reading up to the cap counted as done, so the resume point moved
    past the older papers that were never read."""
    crawl = _crawl_returning(
        [_result(f"Paper {n}", _ago(hours=n + 1)) for n in range(3)],  # all newer
        categories=["cs.LG"],
        max_results=3,
    )

    assert len(crawl.papers) == 3
    assert crawl.complete is False


def test_a_category_that_reaches_the_cutoff_is_complete_even_with_a_full_page():
    crawl = _crawl_returning(
        [
            _result("New", _ago(days=1)),
            _result("New too", _ago(days=2)),
            _result("Old", _ago(days=30)),  # the cutoff: this is the third result
        ],
        categories=["cs.LG"],
        max_results=3,
    )

    assert crawl.complete is True


def test_one_capped_category_is_enough_to_make_the_crawl_incomplete():
    crawl = _crawl_returning(
        [_result("Quiet", _ago(days=1)), _result("Old", _ago(days=30))],
        [_result(f"Busy {n}", _ago(hours=n + 1)) for n in range(3)],
        categories=["cs.AI", "cs.LG"],
        max_results=3,
    )

    assert crawl.complete is False


# --- the window: arXiv lists papers only after they are announced -------------


def test_first_run_reaches_back_past_the_announcement_lag():
    """Regression: "yesterday only" was always empty, because the newest paper arXiv
    lists is one to three days old when the daily job runs."""
    crawl = _crawl_returning(
        [
            _result("Announced two days ago", _ago(days=2)),
            _result("Announced three and a half days ago", _ago(days=3, hours=12)),
            _result("Too old", _ago(days=6)),
        ],
        categories=["cs.LG"],
        days_back=1,
    )

    assert [p.title for p in crawl.papers] == [
        "Announced two days ago",
        "Announced three and a half days ago",
    ]


def test_crawl_resumes_after_the_last_paper_already_handled():
    since = _ago(days=2)
    crawl = _crawl_returning(
        [
            _result("New", _ago(days=1)),
            _result("Handled already", since),  # exactly the resume point
            _result("Older", _ago(days=3)),
        ],
        categories=["cs.LG"],
        since=since,
    )

    assert [p.title for p in crawl.papers] == ["New"]


def test_catching_up_never_goes_back_more_than_a_week():
    crawl = _crawl_returning(
        [_result("Last week", _ago(days=6)), _result("Last month", _ago(days=30))],
        categories=["cs.LG"],
        since=_ago(days=60),
    )

    assert [p.title for p in crawl.papers] == ["Last week"]


def test_paper_from_result_collapses_wrapped_title_and_builds_doi():
    published = _ago(days=1)
    paper = arxiv_source.paper_from_result(_result("Wrapped\n  Title", published))

    assert paper.title == "Wrapped Title"
    assert paper.journal == "arXiv"
    assert paper.doi == "10.48550/arXiv.2605.12345"
    assert paper.published_at == published  # the exact time, not just the day


def test_fetch_by_id_returns_none_when_arxiv_is_unreachable():
    with patch(f"{MODULE}.arxiv.Client") as client_cls:
        client_cls.return_value.results.side_effect = requests.ConnectionError("down")
        assert fetch_by_id("2401.01234") is None
