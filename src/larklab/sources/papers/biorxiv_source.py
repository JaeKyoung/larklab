"""bioRxiv: fetch a paper by DOI and crawl recent submissions per category."""

import contextlib
import logging
import re
import time
from datetime import UTC, date, datetime, timedelta

import httpx

from larklab.models import CrawlResult, Paper
from larklab.sources.papers import crawl_window
from larklab.utils.http import build_http_client
from larklab.utils.text import canonical_journal_name, normalize_title

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = [
    "bioinformatics",
    "biochemistry",
    "biophysics",
    "molecular biology",
    "synthetic biology",
]

_API_URL = "https://api.biorxiv.org/details/biorxiv"
_PAGE_ATTEMPTS = 3  # the API times out now and then; one bad read must not end a crawl
_PAGE_RETRY_SECONDS = 5


def paper_from_entry(entry: dict) -> Paper:
    """Convert one entry of the bioRxiv API's `collection` list."""
    published_at = None
    if entry.get("date"):
        with contextlib.suppress(ValueError):
            day = date.fromisoformat(entry["date"])
            published_at = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return Paper(
        title=entry.get("title", "").strip(),
        authors=[a.strip() for a in entry.get("authors", "").split(";") if a.strip()],
        journal=canonical_journal_name(entry.get("server", "bioRxiv")),
        abstract=_clean_abstract(entry.get("abstract", "")),
        doi=entry.get("doi", ""),
        published_at=published_at,
    )


def fetch_by_doi(client: httpx.Client, doi: str) -> Paper | None:
    """Return the latest version of a bioRxiv preprint, or None."""
    try:
        response = client.get(f"{_API_URL}/{doi}")
        response.raise_for_status()
        collection = response.json().get("collection")
    except (httpx.HTTPError, ValueError) as error:
        logger.debug("bioRxiv lookup failed for %s: %s", doi, error)
        return None
    if not collection:
        return None
    paper = paper_from_entry(collection[-1])
    paper.doi = doi
    return paper


def crawl_recent(
    categories: list[str] | None = None,
    days_back: int = 1,
    max_results: int = 200,
    since: datetime | None = None,
) -> CrawlResult:
    """Collect preprints posted in the last `days_back` full days.

    With `since` it resumes the day after the last one already seen instead,
    catching up on missed days (at most a week). The result is marked incomplete
    when the API kept failing, so the caller does not treat the papers as seen.
    `max_results` never cuts a day in half: the crawl runs to the end of the day
    it reached it in, because the next run resumes on the day after.
    """
    wanted_categories = {c.lower() for c in (categories or DEFAULT_CATEGORIES)}
    # bioRxiv posts whole days; today is still open
    window = crawl_window(date.today() - timedelta(days=1), days_back, since)
    if window is None:
        return CrawlResult([])
    start, end = window

    papers: list[Paper] = []
    seen_titles: set[str] = set()
    complete = True
    last_day = None  # date of the newest paper kept
    capped = False
    with build_http_client(timeout=30) as client:
        cursor = 0
        while not capped:
            page = _fetch_page(client, start, end, cursor)
            if page is None:
                complete = False
                break
            entries, total = page
            if not entries:
                break

            for entry in entries:
                if len(papers) >= max_results and entry.get("date") != last_day:
                    capped = True
                    break
                if entry.get("category", "").lower() not in wanted_categories:
                    continue
                title_key = normalize_title(entry.get("title", ""))
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
                papers.append(paper_from_entry(entry))
                last_day = entry.get("date")

            # The API picks the page size (30 now, once 100): step by what came back
            cursor += len(entries)
            if cursor >= total:
                break
    return CrawlResult(papers, complete=complete)


def _fetch_page(
    client: httpx.Client, start: date, end: date, cursor: int
) -> tuple[list[dict], int] | None:
    """Return (entries, total entries in range) for one page, or None when the
    API keeps failing."""
    for attempt in range(1, _PAGE_ATTEMPTS + 1):
        try:
            response = client.get(f"{_API_URL}/{start}/{end}/{cursor}")
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning(
                "bioRxiv API error at cursor %d (attempt %d/%d): %s",
                cursor,
                attempt,
                _PAGE_ATTEMPTS,
                error,
            )
            if attempt < _PAGE_ATTEMPTS:
                time.sleep(_PAGE_RETRY_SECONDS)
            continue
        messages = data.get("messages") or [{}]
        return data.get("collection", []), int(messages[0].get("total", 0))
    return None


def _clean_abstract(raw: str) -> str:
    """The API leaves SCPLOW markup and trailing footnote digits in abstracts."""
    text = re.sub(r"[A-Z]+_SCPLOW[A-Z]*C_SCPLOW", "", raw)
    text = re.sub(r"\d+$", "", text)
    return text.strip()
