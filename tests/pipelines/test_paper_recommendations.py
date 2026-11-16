from datetime import UTC, date, datetime
from types import SimpleNamespace

from larklab.models import CrawlResult, Paper
from larklab.pipelines import paper_recommendations as pipeline
from larklab.pipelines.paper_recommendations import recommend_papers


def _crawled(
    title: str,
    doi: str,
    source: str = "arXiv",
    day: date | None = date(2026, 11, 15),
    hour: int = 0,
) -> Paper:
    return Paper(
        title=title,
        authors=["A"],
        journal=source,
        abstract="abstract",
        doi=doi,
        published_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
        if day
        else None,
    )


def _fake_crawlers(monkeypatch, incomplete=(), **papers_by_source):
    """Crawlers that return fixed papers and remember the `since` they were given."""
    seen_since: dict[str, datetime | None] = {}

    def crawler(name, papers):
        def crawl_recent(categories, days_back, since=None):
            seen_since[name] = since
            return CrawlResult(papers, complete=name not in incomplete)

        return SimpleNamespace(DEFAULT_CATEGORIES=["cat"], crawl_recent=crawl_recent)

    monkeypatch.setattr(
        pipeline,
        "_CRAWLERS",
        {name: crawler(name, papers) for name, papers in papers_by_source.items()},
    )
    return seen_since


def _score_by_title(monkeypatch, scores: dict[str, float]):
    monkeypatch.setattr(
        pipeline,
        "find_similar_references",
        lambda papers, repo: [[("Reference", scores[p.title])] for p in papers],
    )


def _recommend(repository, sources=("arxiv",), **options):
    settings = {"categories": None, "days_back": 1, "top_n": 10, "threshold": 0.5}
    return recommend_papers(repository, sources=list(sources), **(settings | options))


def test_recommendations_exclude_library_papers_threshold_and_rank(
    repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Already Here.", doi="10.1/here", embedding=one_hot(0)))
    _fake_crawlers(
        monkeypatch,
        arxiv=[
            _crawled("already here", "10.48550/arXiv.1"),  # same title, new punctuation
            _crawled("Same DOI, new title", "10.1/HERE"),  # same DOI, other case
            _crawled("Good", "10.48550/arXiv.2"),
            _crawled("Better", "10.48550/arXiv.3"),
            _crawled("Poor", "10.48550/arXiv.4"),
        ],
    )
    _score_by_title(monkeypatch, {"Good": 0.7, "Better": 0.8, "Poor": 0.1})

    result = _recommend(repository)

    assert [r.paper.title for r in result.recommendations] == ["Better", "Good"]
    assert result.recommendations[0].score == 0.8
    # candidate counts include the paper below the threshold, not the library ones
    assert result.source_counts(date(2026, 11, 15)) == [("arxiv", 2, 3)]


def test_recommendations_respect_top_n_and_group_by_date(
    repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    _fake_crawlers(
        monkeypatch,
        arxiv=[_crawled("Old", "10.48550/arXiv.1", day=date(2026, 11, 14))],
        biorxiv=[_crawled("New", "10.64898/2", source="bioRxiv")],
    )
    _score_by_title(monkeypatch, {"Old": 0.9, "New": 0.8})

    result = _recommend(
        repository, sources=("arxiv", "biorxiv"), top_n=1, threshold=0.0
    )

    assert [r.paper.title for r in result.recommendations] == ["Old"]
    assert list(result.by_date()) == [date(2026, 11, 14)]


def test_recommendations_are_empty_without_a_library(repository, monkeypatch):
    _fake_crawlers(monkeypatch, arxiv=[_crawled("Anything", "10.48550/arXiv.1")])

    assert _recommend(repository).recommendations == []


def test_by_date_orders_newest_first_with_unknown_dates_last(
    repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    _fake_crawlers(
        monkeypatch,
        arxiv=[
            _crawled("Undated", "10.48550/arXiv.1", day=None),
            _crawled("Older", "10.48550/arXiv.2", day=date(2026, 11, 1)),
            _crawled("Newer", "10.48550/arXiv.3", day=date(2026, 11, 2)),
        ],
    )
    _score_by_title(monkeypatch, {"Undated": 0.6, "Older": 0.6, "Newer": 0.6})

    result = _recommend(repository, days_back=30)

    assert list(result.by_date()) == [date(2026, 11, 2), date(2026, 11, 1), None]


# --- resuming where the last delivered run stopped --------------------------


def test_each_source_resumes_from_its_own_progress(repository, monkeypatch):
    seen_since = _fake_crawlers(monkeypatch, arxiv=[], biorxiv=[])
    arxiv_mark = datetime(2026, 11, 13, 18, 59, tzinfo=UTC)

    _recommend(repository, sources=("arxiv", "biorxiv"), since={"arxiv": arxiv_mark})

    assert seen_since == {"arxiv": arxiv_mark, "biorxiv": None}


def test_result_reports_the_newest_paper_per_source_even_when_nothing_qualifies(
    repository, make_paper, one_hot, monkeypatch
):
    """Seen-but-below-threshold papers still count as handled."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    _fake_crawlers(
        monkeypatch,
        arxiv=[
            _crawled("Early", "10.48550/arXiv.1", day=date(2026, 11, 12), hour=9),
            _crawled("Late", "10.48550/arXiv.2", day=date(2026, 11, 13), hour=18),
        ],
        biorxiv=[],
    )
    _score_by_title(monkeypatch, {"Early": 0.1, "Late": 0.1})

    result = _recommend(repository, sources=("arxiv", "biorxiv"))

    assert result.recommendations == []
    assert result.newest_published == {
        "arxiv": datetime(2026, 11, 13, 18, tzinfo=UTC)
    }  # biorxiv found nothing, so it has no resume point


def test_papers_that_could_not_be_scored_are_not_marked_as_handled(
    repository, make_paper, one_hot, monkeypatch
):
    """Without a library, or without embeddings, nothing was looked at: moving the
    resume point would hide those papers for good once the library is ready."""
    _fake_crawlers(monkeypatch, arxiv=[_crawled("Anything", "10.48550/arXiv.1")])

    assert _recommend(repository).newest_published == {}  # empty library

    repository.add(make_paper("Reference", embedding=one_hot(0)))
    monkeypatch.setattr(
        pipeline, "find_similar_references", lambda papers, repo: [[] for _ in papers]
    )

    assert _recommend(repository).newest_published == {}  # nothing could be scored


def test_no_crawled_papers_means_no_progress_to_save(repository, monkeypatch):
    _fake_crawlers(monkeypatch, arxiv=[])

    assert _recommend(repository).newest_published == {}


def test_a_source_that_could_not_be_read_completely_keeps_its_old_resume_point(
    repository, make_paper, one_hot, monkeypatch
):
    """Its papers are still recommended now, but it is fetched again next time."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    _fake_crawlers(
        monkeypatch,
        incomplete=("arxiv",),
        arxiv=[_crawled("Half read", "10.48550/arXiv.1", day=date(2026, 11, 13))],
        biorxiv=[
            _crawled("Whole", "10.64898/2", source="bioRxiv", day=date(2026, 11, 13))
        ],
    )
    _score_by_title(monkeypatch, {"Half read": 0.9, "Whole": 0.9})

    result = _recommend(repository, sources=("arxiv", "biorxiv"))

    assert {r.paper.title for r in result.recommendations} == {"Half read", "Whole"}
    assert list(result.newest_published) == ["biorxiv"]  # arxiv is left out
