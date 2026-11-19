"""arXiv: fetch a paper by ID and crawl newly announced submissions per category."""

import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import arxiv
import requests

from larklab.models import CrawlResult, Paper
from larklab.sources.papers import MAX_CATCH_UP_DAYS
from larklab.utils.identifiers import ARXIV_DOI_PREFIX
from larklab.utils.text import collapse_whitespace, normalize_title

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = [
    "q-bio.BM",
    "cs.LG",
    "cs.AI",
    "physics.bio-ph",
    "physics.chem-ph",
]

_ARXIV_ERRORS = (arxiv.ArxivError, requests.RequestException)
# Each request costs a 10 s pause, so big pages are what make a crawl fast: measured
# on cs.LG, 240 papers took 11 s at 200 per page and 42 s at 50, with the same result.
_PAGE_SIZE = 200
_REQUEST_DELAY_SECONDS = 10
_RATE_LIMIT_BACKOFF_SECONDS = 60
# Results are newest-first, so a cap cuts off the older part. A week's catch-up plus
# the overlap of two days stays well below this; a category that reaches it anyway
# makes the crawl incomplete (the resume point stays) instead of skipping papers.
_MAX_RESULTS_PER_CATEGORY = 3000

# arXiv's API only lists papers that were already *announced* (Sunday to Thursday
# evening, US Eastern). Seen from Asia at breakfast time the newest paper is one to
# three days old, so "yesterday" is almost always empty.
_ANNOUNCEMENT_LAG_DAYS = 3


def paper_from_result(result: arxiv.Result) -> Paper:
    arxiv_id = result.get_short_id().split("v")[0]
    return Paper(
        title=collapse_whitespace(result.title),
        authors=[author.name for author in result.authors],
        journal="arXiv",
        abstract=collapse_whitespace(result.summary),
        doi=result.doi or f"{ARXIV_DOI_PREFIX}{arxiv_id}",
        published_at=_as_utc(result.published) if result.published else None,
    )


def fetch_by_id(arxiv_id: str) -> Paper | None:
    """Return the arXiv record for an ID like '2401.01234', or None."""
    try:
        results = list(arxiv.Client().results(arxiv.Search(id_list=[arxiv_id])))
    except _ARXIV_ERRORS as error:
        logger.debug("arXiv lookup failed for %s: %s", arxiv_id, error)
        return None
    return paper_from_result(results[0]) if results else None


def crawl_recent(
    categories: list[str] | None = None,
    days_back: int = 1,
    max_results: int = _MAX_RESULTS_PER_CATEGORY,
    since: datetime | None = None,
) -> CrawlResult:
    """Collect papers newer than `since` (at most a week back).

    Without `since` (first run) it looks back `days_back` days plus the
    announcement lag. Each paper is returned once, however many of the requested
    categories it is listed in. The result is marked incomplete when a category
    could not be read, or hit `max_results` before reaching the cutoff (the older
    papers were not read), so the caller does not treat its papers as seen.
    """
    now = datetime.now(UTC)
    if since:
        cutoff = max(_as_utc(since), now - timedelta(days=MAX_CATCH_UP_DAYS))
    else:
        cutoff = now - timedelta(days=days_back + _ANNOUNCEMENT_LAG_DAYS)

    # Query each category separately: arXiv's API returns HTTP 429 for the
    # combined "cat:A OR cat:B OR ..." query, while single-category queries
    # work reliably. delay_seconds spaces requests to avoid rate limiting.
    client = arxiv.Client(
        page_size=min(_PAGE_SIZE, max_results),
        delay_seconds=_REQUEST_DELAY_SECONDS,
        num_retries=5,
    )

    papers: list[Paper] = []
    seen_titles: set[str] = set()
    failed_categories: list[str] = []
    capped_categories: list[str] = []
    for category in categories or DEFAULT_CATEGORIES:
        search = arxiv.Search(
            query=f"cat:{category}",
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        results = _iter_results_with_backoff(
            client, search, category, failed_categories
        )
        read = 0
        reached_cutoff = False
        for result in results:
            read += 1
            if _as_utc(result.published) <= cutoff:
                reached_cutoff = True
                break  # results are newest-first, so everything after is older
            title_key = normalize_title(result.title)
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            papers.append(paper_from_result(result))
        if read >= max_results and not reached_cutoff:
            capped_categories.append(category)
    if capped_categories:
        logger.warning(
            "arXiv cat:%s has %d or more papers since %s; the older ones were not "
            "read, so the next run tries again.",
            ", cat:".join(capped_categories),
            max_results,
            cutoff.date(),
        )
    return CrawlResult(papers, complete=not (failed_categories or capped_categories))


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _iter_results_with_backoff(
    client: arxiv.Client,
    search: arxiv.Search,
    category: str,
    failed_categories: list[str],
) -> Iterator[arxiv.Result]:
    """Yield results for one category, retrying once after an HTTP 429.

    A category that still fails is added to `failed_categories`.
    """
    for attempt in range(2):
        try:
            yield from client.results(search)
            return
        except _ARXIV_ERRORS as error:
            rate_limited = isinstance(error, arxiv.HTTPError) and error.status == 429
            if attempt == 0 and rate_limited:
                logger.warning(
                    "arXiv rate limited for cat:%s; retrying after %ds",
                    category,
                    _RATE_LIMIT_BACKOFF_SECONDS,
                )
                time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
                continue
            logger.warning("arXiv crawl stopped for cat:%s: %s", category, error)
            failed_categories.append(category)
            return
