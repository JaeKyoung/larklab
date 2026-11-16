from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from larklab.sources.papers import biorxiv_source

_REAL_CLIENT = httpx.Client  # tests replace httpx.Client itself


def _entry(title: str, category: str = "bioinformatics", **overrides) -> dict:
    return {
        "title": title,
        "authors": "Doe, J.; Roe, R.;",
        "server": "biorxiv",
        "abstract": "An abstract.",
        "doi": f"10.64898/{title.lower().replace(' ', '-')}",
        "date": "2026-11-12",
        "category": category,
    } | overrides


def test_paper_from_entry_normalizes_server_and_authors():
    paper = biorxiv_source.paper_from_entry(_entry("A Preprint"))

    assert paper.journal == "bioRxiv"
    assert paper.authors == ["Doe, J.", "Roe, R."]  # trailing ';' leaves no blank
    assert paper.published_date == date(2026, 11, 12)


def test_paper_from_entry_tolerates_missing_date_and_authors():
    paper = biorxiv_source.paper_from_entry(
        {"title": "T", "doi": "10.1/x", "date": "not-a-date"}
    )

    assert paper.published_date is None
    assert paper.authors == []


def test_fetch_by_doi_returns_latest_version_with_requested_doi(http_client):
    def handler(request):
        collection = [
            _entry("Old", abstract="First version."),
            _entry("New", abstract="Second version."),
        ]
        return httpx.Response(200, json={"collection": collection})

    paper = biorxiv_source.fetch_by_doi(http_client(handler), "10.64898/requested")

    assert (paper.title, paper.abstract) == ("New", "Second version.")
    assert paper.doi == "10.64898/requested"


def test_fetch_by_doi_returns_none_for_unknown_doi(http_client):
    def handler(request):
        return httpx.Response(200, json={"collection": []})

    assert biorxiv_source.fetch_by_doi(http_client(handler), "10.1/none") is None


def test_crawl_filters_categories_dedupes_and_pages(monkeypatch):
    pages = {
        0: {
            "messages": [{"total": 5}],
            "collection": [
                _entry("Wanted One"),
                _entry("Unwanted", category="neuroscience"),
                _entry("Wanted Two", category="Biochemistry"),
            ],
        },
        3: {
            "messages": [{"total": 5}],
            "collection": [_entry("wanted one!"), _entry("Wanted Three")],
        },
    }
    requested_cursors = []

    def handler(request):
        cursor = int(request.url.path.rsplit("/", 1)[1])
        requested_cursors.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        biorxiv_source.httpx,
        "Client",
        lambda **kwargs: _REAL_CLIENT(transport=transport),
    )

    crawl = biorxiv_source.crawl_recent(["bioinformatics", "biochemistry"], days_back=1)

    assert [p.title for p in crawl.papers] == [
        "Wanted One",
        "Wanted Two",
        "Wanted Three",
    ]
    assert crawl.complete is True
    assert requested_cursors == [0, 3]  # the next page starts after what came back


def test_the_next_page_starts_after_the_entries_the_api_returned(monkeypatch):
    """Regression: the API's pages hold 30 entries now (they once held 100).
    Stepping by a fixed 100 skipped 70 of every 100 entries, about 3 papers in 4."""
    cursors = []

    def handler(request):
        cursor = int(request.url.path.rsplit("/", 1)[1])
        cursors.append(cursor)
        entries = [_entry(f"Paper {i}") for i in range(cursor, min(cursor + 2, 5))]
        return httpx.Response(
            200, json={"messages": [{"total": "5"}], "collection": entries}
        )

    _serve(monkeypatch, handler)

    crawl = biorxiv_source.crawl_recent(days_back=1)

    assert cursors == [0, 2, 4]
    assert len(crawl.papers) == 5


def test_the_cap_never_cuts_a_day_in_half(monkeypatch):
    """The next run resumes on the day after the last one read, so a day cut short
    would lose the rest of its papers for good."""
    pages = {
        0: [_entry("Mon 0", date="2026-11-12"), _entry("Mon 1", date="2026-11-12")],
        2: [_entry("Mon 2", date="2026-11-12"), _entry("Tue 0", date="2026-11-13")],
    }
    cursors = []

    def handler(request):
        cursor = int(request.url.path.rsplit("/", 1)[1])
        cursors.append(cursor)
        return httpx.Response(
            200, json={"messages": [{"total": 4}], "collection": pages[cursor]}
        )

    _serve(monkeypatch, handler)

    crawl = biorxiv_source.crawl_recent(days_back=1, max_results=2)

    assert [p.title for p in crawl.papers] == ["Mon 0", "Mon 1", "Mon 2"]
    assert crawl.complete is True
    assert cursors == [0, 2]  # Tuesday was seen only as the end of Monday


def test_an_api_error_on_a_later_page_keeps_what_was_read_but_says_so(monkeypatch):
    def handler(request):
        if not request.url.path.endswith("/0"):
            return httpx.Response(500)
        entries = [_entry(f"Paper {i}") for i in range(3)]
        return httpx.Response(
            200, json={"messages": [{"total": 500}], "collection": entries}
        )

    _serve(monkeypatch, handler)

    partial = biorxiv_source.crawl_recent(days_back=1, max_results=10)

    assert len(partial.papers) == 3
    assert partial.complete is False


def test_crawl_asks_for_the_requested_date_window(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"messages": [{"total": 0}], "collection": []})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        biorxiv_source.httpx,
        "Client",
        lambda **kwargs: _REAL_CLIENT(transport=transport),
    )

    biorxiv_source.crawl_recent(days_back=3)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=2)
    assert seen == [f"/details/biorxiv/{start}/{end}/0"]


# --- resuming, and surviving a flaky API -------------------------------------


def _serve(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        biorxiv_source.httpx,
        "Client",
        lambda **kwargs: _REAL_CLIENT(transport=transport),
    )


def _empty_page(request):
    return httpx.Response(200, json={"messages": [{"total": 0}], "collection": []})


def test_crawl_resumes_the_day_after_the_last_one_seen(monkeypatch):
    requested = []

    def handler(request):
        requested.append(request.url.path)
        return _empty_page(request)

    _serve(monkeypatch, handler)
    end = date.today() - timedelta(days=1)
    seen = datetime(end.year, end.month, end.day, tzinfo=UTC) - timedelta(days=2)

    biorxiv_source.crawl_recent(days_back=1, since=seen)

    assert requested == [f"/details/biorxiv/{end - timedelta(days=1)}/{end}/0"]


def test_nothing_new_since_yesterday_means_no_request_at_all(monkeypatch):
    _serve(monkeypatch, lambda request: pytest.fail("the API must not be called"))
    end = date.today() - timedelta(days=1)

    crawl = biorxiv_source.crawl_recent(
        since=datetime(end.year, end.month, end.day, tzinfo=UTC)
    )

    assert (crawl.papers, crawl.complete) == ([], True)  # nothing to read is fine


def test_catching_up_never_goes_back_more_than_a_week(monkeypatch):
    requested = []

    def handler(request):
        requested.append(request.url.path)
        return _empty_page(request)

    _serve(monkeypatch, handler)
    end = date.today() - timedelta(days=1)

    biorxiv_source.crawl_recent(since=datetime(2020, 1, 1, tzinfo=UTC))

    assert requested == [f"/details/biorxiv/{end - timedelta(days=6)}/{end}/0"]


def test_a_timeout_is_retried_instead_of_ending_the_crawl(monkeypatch):
    """Regression: one read timeout used to turn a whole day into 'No papers found'."""
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("The read operation timed out")
        entries = [_entry("Survivor")]
        return httpx.Response(
            200, json={"messages": [{"total": 1}], "collection": entries}
        )

    _serve(monkeypatch, handler)

    crawl = biorxiv_source.crawl_recent(days_back=1)

    assert [p.title for p in crawl.papers] == ["Survivor"]
    assert crawl.complete is True  # the retry worked
    assert len(attempts) == 2


def test_gives_up_after_the_last_attempt_without_raising(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ReadTimeout("down")

    _serve(monkeypatch, handler)

    crawl = biorxiv_source.crawl_recent(days_back=1)

    assert (crawl.papers, crawl.complete) == ([], False)
    assert len(attempts) == 3


def test_clean_biorxiv_abstract_strips_markup_and_trailing_footnote():
    raw = "Proteins fold. SCPLOWABC_SCPLOWC_SCPLOW Done.12"
    cleaned = biorxiv_source._clean_abstract(raw)
    assert "SCPLOW" not in cleaned
    assert not cleaned.endswith("12")
