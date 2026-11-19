import threading
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from larklab.models import (
    CrawlResult,
    Paper,
    Recommendation,
    RecommendationResult,
    SourceProgress,
)
from larklab.pipelines import paper_recommendations as pipeline
from larklab.pipelines.paper_recommendations import recommend_papers


def _crawled(
    title: str,
    doi: str,
    journal: str = "arXiv",
    day: date | None = date(2026, 11, 15),
    hour: int = 0,
    source: str = "",
) -> Paper:
    return Paper(
        title=title,
        authors=["A"],
        journal=journal,
        abstract="abstract",
        doi=doi,
        published_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
        if day
        else None,
        source=source,
    )


def _fake_crawlers(monkeypatch, incomplete=(), read_until=None, **papers_by_source):
    """Crawlers that return fixed papers and remember the `since` they were given.
    `read_until` says per source how far its crawl reports having read."""
    seen_since: dict[str, datetime | None] = {}
    read_until = read_until or {}

    def crawler(name, papers):
        def crawl_recent(categories, days_back, since=None):
            seen_since[name] = since
            return CrawlResult(
                papers,
                complete=name not in incomplete,
                read_until=read_until.get(name),
            )

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
        biorxiv=[_crawled("New", "10.64898/2", journal="bioRxiv")],
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
    seen_since = _fake_crawlers(monkeypatch, arxiv=[], biorxiv=[], pubmed=[])
    mark = datetime(2026, 11, 13, 18, 59, tzinfo=UTC)

    _recommend(
        repository,
        sources=("arxiv", "biorxiv", "pubmed"),
        progress={"biorxiv": SourceProgress(mark), "arxiv": SourceProgress(mark)},
    )

    assert seen_since == {
        "arxiv": mark - timedelta(days=2),  # arXiv is read a little further back
        "biorxiv": mark,
        "pubmed": None,  # nothing saved yet: the first run
    }


def test_a_paper_announced_late_is_recommended_but_one_seen_before_is_not(
    repository, make_paper, one_hot, monkeypatch
):
    """arXiv can list a paper after newer ones; the overlap lets it through once."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    mark = datetime(2026, 11, 13, 18, tzinfo=UTC)
    earlier = SourceProgress(
        mark, seen={"10.48550/arxiv.1": datetime(2026, 11, 13, 9, tzinfo=UTC)}
    )
    _fake_crawlers(
        monkeypatch,
        arxiv=[
            _crawled("Seen before", "10.48550/arXiv.1", day=date(2026, 11, 13), hour=9),
            _crawled(
                "Held, now listed", "10.48550/arXiv.2", day=date(2026, 11, 12), hour=20
            ),
        ],
    )
    _score_by_title(monkeypatch, {"Seen before": 0.9, "Held, now listed": 0.9})

    result = _recommend(repository, sources=("arxiv",), progress={"arxiv": earlier})

    assert [r.paper.title for r in result.recommendations] == ["Held, now listed"]


def test_progress_keeps_only_the_papers_of_the_stretch_the_next_run_reads_again(
    repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    old = SourceProgress(
        datetime(2026, 11, 10, tzinfo=UTC),
        seen={"10.48550/arxiv.old": datetime(2026, 11, 8, 12, tzinfo=UTC)},
    )
    _fake_crawlers(
        monkeypatch,
        arxiv=[_crawled("Fresh", "10.48550/arXiv.9", day=date(2026, 11, 14), hour=12)],
        biorxiv=[
            _crawled("Day", "10.64898/9", journal="bioRxiv", day=date(2026, 11, 14))
        ],
    )
    _score_by_title(monkeypatch, {"Fresh": 0.9, "Day": 0.9})

    result = _recommend(
        repository, sources=("arxiv", "biorxiv"), progress={"arxiv": old}
    )

    newest = datetime(2026, 11, 14, 12, tzinfo=UTC)
    assert result.progress["arxiv"] == SourceProgress(
        newest,
        seen={"10.48550/arxiv.9": newest},  # the Nov 8 paper is out of reach
    )
    assert result.progress["biorxiv"].seen == {}  # read by whole days: no overlap


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
    newest = {source: p.newest for source, p in result.progress.items()}
    assert newest == {
        "arxiv": datetime(2026, 11, 13, 18, tzinfo=UTC)
    }  # biorxiv found nothing, so it has no resume point


def test_papers_that_could_not_be_scored_are_not_marked_as_handled(
    repository, make_paper, one_hot, monkeypatch
):
    """Without a library, or without embeddings, nothing was looked at: moving the
    resume point would hide those papers for good once the library is ready."""
    _fake_crawlers(monkeypatch, arxiv=[_crawled("Anything", "10.48550/arXiv.1")])

    assert _recommend(repository).progress == {}  # empty library

    repository.add(make_paper("Reference", embedding=one_hot(0)))
    monkeypatch.setattr(
        pipeline, "find_similar_references", lambda papers, repo: [[] for _ in papers]
    )

    assert _recommend(repository).progress == {}  # nothing could be scored


def test_every_paper_remembers_which_source_found_it(
    repository, make_paper, one_hot, monkeypatch
):
    """The crawler decides: `arxiv`, `biorxiv`, or `pubmed:<journal>` for PubMed."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    named = _crawled(
        "From PubMed", "10.1/p1", journal="Cell Systems", source="pubmed:Cell Syst"
    )
    _fake_crawlers(
        monkeypatch,
        arxiv=[_crawled("From arXiv", "10.48550/arXiv.1")],
        pubmed=[named, _crawled("PubMed, unnamed", "10.1/p2", journal="Cell Systems")],
    )
    _score_by_title(
        monkeypatch, {"From arXiv": 0.9, "From PubMed": 0.8, "PubMed, unnamed": 0.7}
    )

    result = _recommend(repository, sources=("arxiv", "pubmed"))

    assert {r.paper.title: r.paper.source for r in result.recommendations} == {
        "From arXiv": "arxiv",
        "From PubMed": "pubmed:Cell Syst",  # the crawler's own, more exact name wins
        "PubMed, unnamed": "pubmed",
    }


def test_the_headline_lists_only_pubmed_journals_that_have_a_recommendation(
    make_paper,
):
    """PubMed has one source per journal, hundreds a day; arXiv/bioRxiv always show."""
    day = date(2026, 11, 15)
    when = datetime(2026, 11, 15, tzinfo=UTC)

    def recommended(title, source):
        paper = make_paper(title, published_at=when, source=source)
        return Recommendation(paper, [("Reference", 0.8)])

    result = RecommendationResult(
        recommendations=[recommended("kept", "pubmed:Bioinformatics")],
        candidate_counts={
            day: {
                "arxiv": 40,
                "pubmed:Bioinformatics": 21,
                "pubmed:Chem Sci": 27,  # candidates, but nothing recommended
            }
        },
    )

    assert result.source_counts(day) == [
        ("arxiv", 0, 40),
        ("pubmed:Bioinformatics", 1, 21),
    ]


def test_a_paper_two_sources_both_return_is_scored_once_under_the_first(
    repository, make_paper, one_hot, monkeypatch
):
    """PubMed indexes bioRxiv preprints: the same DOI arrives from both crawlers."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    _fake_crawlers(
        monkeypatch,
        biorxiv=[_crawled("Same Preprint", "10.1101/abc", journal="bioRxiv")],
        pubmed=[
            _crawled(
                "Same Preprint",
                "10.1101/ABC",
                journal="bioRxiv",
                source="pubmed:bioRxiv",
            )
        ],
    )
    _score_by_title(monkeypatch, {"Same Preprint": 0.9})

    result = _recommend(repository, sources=("biorxiv", "pubmed"))

    [recommendation] = result.recommendations
    assert recommendation.paper.source == "biorxiv"  # the first source keeps it
    assert result.candidate_counts[date(2026, 11, 15)] == {"biorxiv": 1}


def test_the_sources_are_read_at_the_same_time(repository, monkeypatch):
    """Each crawler waits for the other: it only gets through if they overlap."""
    both_running = threading.Barrier(2, timeout=5)

    def crawler(papers):
        def crawl_recent(categories, days_back, since=None):
            both_running.wait()  # would time out if the sources were read one by one
            return CrawlResult(papers)

        return SimpleNamespace(DEFAULT_CATEGORIES=["cat"], crawl_recent=crawl_recent)

    monkeypatch.setattr(
        pipeline,
        "_CRAWLERS",
        {"arxiv": crawler([]), "biorxiv": crawler([])},
    )

    result = _recommend(repository, sources=("arxiv", "biorxiv"))

    assert result.recommendations == []  # reached the end without a BrokenBarrierError


def test_a_failing_source_still_fails_the_run(repository, monkeypatch):
    def broken(categories, days_back, since=None):
        raise RuntimeError("arXiv exploded")

    crawler = SimpleNamespace(DEFAULT_CATEGORIES=["cat"], crawl_recent=broken)
    monkeypatch.setattr(pipeline, "_CRAWLERS", {"arxiv": crawler})

    with pytest.raises(RuntimeError, match="arXiv exploded"):
        _recommend(repository, sources=("arxiv",))


def test_a_source_named_twice_is_crawled_once(repository, monkeypatch):
    reads = []

    def crawl_recent(categories, days_back, since=None):
        reads.append(1)
        return CrawlResult([])

    crawler = SimpleNamespace(DEFAULT_CATEGORIES=["cat"], crawl_recent=crawl_recent)
    monkeypatch.setattr(pipeline, "_CRAWLERS", {"arxiv": crawler})

    _recommend(repository, sources=("arxiv", "arxiv"))

    assert len(reads) == 1


def test_no_crawled_papers_means_no_progress_to_save(repository, monkeypatch):
    _fake_crawlers(monkeypatch, arxiv=[])

    assert _recommend(repository).progress == {}


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
            _crawled("Whole", "10.64898/2", journal="bioRxiv", day=date(2026, 11, 13))
        ],
    )
    _score_by_title(monkeypatch, {"Half read": 0.9, "Whole": 0.9})

    result = _recommend(repository, sources=("arxiv", "biorxiv"))

    assert {r.paper.title for r in result.recommendations} == {"Half read", "Whole"}
    assert list(result.progress) == ["biorxiv"]  # arxiv is left out


# --- how far a source was read, and which reading a resume point belongs to ----------


def test_a_source_that_says_how_far_it_read_moves_exactly_that_far(
    repository, make_paper, one_hot, monkeypatch
):
    """PubMed reads whole days: the resume point is the last day read, not the time
    of some paper, and a day without a single usable paper still counts."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    last_day = datetime(2026, 11, 14, tzinfo=UTC)
    _fake_crawlers(
        monkeypatch,
        pubmed=[_crawled("Early", "10.1/e", day=date(2026, 11, 12))],
        read_until={"pubmed": last_day},
    )
    _score_by_title(monkeypatch, {"Early": 0.1})

    result = _recommend(repository, sources=("pubmed",))

    assert result.progress == {"pubmed": SourceProgress(last_day)}


def test_a_source_read_for_days_that_had_no_papers_still_moves_on(
    repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    last_day = datetime(2026, 11, 14, tzinfo=UTC)
    _fake_crawlers(monkeypatch, pubmed=[], read_until={"pubmed": last_day})

    assert _recommend(repository, sources=("pubmed",)).progress == {
        "pubmed": SourceProgress(last_day)
    }


def test_an_incomplete_crawl_keeps_the_part_it_read(
    repository, make_paper, one_hot, monkeypatch
):
    """A failing day must not make the next run read, embed and post the days before
    it again."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    day_read = datetime(2026, 11, 13, tzinfo=UTC)
    _fake_crawlers(
        monkeypatch,
        incomplete=("pubmed",),
        read_until={"pubmed": day_read},
        pubmed=[_crawled("Safe", "10.1/s", day=date(2026, 11, 13))],
    )
    _score_by_title(monkeypatch, {"Safe": 0.9})

    result = _recommend(repository, sources=("pubmed",))

    assert [r.paper.title for r in result.recommendations] == ["Safe"]
    assert result.progress == {"pubmed": SourceProgress(day_read)}


def test_reading_other_journals_has_a_resume_point_of_its_own(
    repository, make_paper, one_hot, monkeypatch
):
    """Regression: after `pubmed -c Bioinformatics`, a run over all of PubMed resumed
    from that run's point and never read what the first one had skipped."""
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    seen_since = _fake_crawlers(
        monkeypatch, pubmed=[_crawled("P", "10.1/p", day=date(2026, 11, 14))]
    )
    _score_by_title(monkeypatch, {"P": 0.1})
    narrow = SourceProgress(datetime(2026, 11, 13, tzinfo=UTC))

    result = _recommend(
        repository,
        sources=("pubmed",),
        categories=["Bioinformatics"],
        progress={"pubmed": SourceProgress(datetime(2026, 11, 1, tzinfo=UTC))},
    )

    assert seen_since["pubmed"] is None  # not the point of the all-journals reading
    assert list(result.progress) == ["pubmed:bioinformatics"]

    _recommend(
        repository,
        sources=("pubmed",),
        categories=["Bioinformatics"],
        progress={"pubmed:bioinformatics": narrow},
    )
    assert seen_since["pubmed"] == narrow.newest  # ...but its own point is used

    _recommend(
        repository, sources=("pubmed",), progress={"pubmed:bioinformatics": narrow}
    )
    assert seen_since["pubmed"] is None  # the all-journals reading has none yet


def test_the_same_journals_in_any_order_or_case_share_a_resume_point():
    key = pipeline._progress_key

    assert key("pubmed", ["Chem Sci", " bioinformatics"]) == key(
        "pubmed", ["Bioinformatics", "chem sci"]
    )
    assert key("pubmed", None) == "pubmed"
    assert key("pubmed", ["Chem Sci"]) != key("arxiv", ["Chem Sci"])
