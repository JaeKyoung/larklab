"""Crawl arXiv and bioRxiv for new papers."""

import logging
from datetime import UTC, date, datetime, timedelta

import arxiv
import httpx

from larklab.extract.paper_fetcher import (
    paper_from_arxiv_result,
    paper_from_biorxiv_entry,
)
from larklab.schemas import Paper

logger = logging.getLogger(__name__)

ARXIV_DEFAULTS = [
    "q-bio.BM",
    "cs.LG",
    "cs.AI",
    "physics.bio-ph",
    "physics.chem-ph",
]
BIORXIV_DEFAULTS = [
    "bioinformatics",
    "biochemistry",
    "biophysics",
    "molecular biology",
    "synthetic biology",
]


def crawl_arxiv(
    categories: list[str] | None = None,
    days_back: int = 2,
    max_results: int = 200,
) -> list[Paper]:
    cats = categories or ARXIV_DEFAULTS
    query = " OR ".join(f"cat:{c}" for c in cats)
    today = date.today()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back - 1)
    cutoff = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)

    client = arxiv.Client(page_size=100, delay_seconds=3)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers = []
    seen: set[str] = set()
    try:
        for r in client.results(search):
            pub = r.published if r.published.tzinfo else r.published.replace(tzinfo=UTC)
            if pub.date() > end_date:
                continue
            if pub < cutoff:
                break
            key = r.title.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            papers.append(paper_from_arxiv_result(r))
    except (arxiv.HTTPError, arxiv.UnexpectedEmptyPageError) as e:
        logger.warning("arXiv crawl stopped: %s", e)

    return papers


def crawl_biorxiv(
    categories: list[str] | None = None,
    days_back: int = 2,
    max_results: int = 200,
) -> list[Paper]:
    cats = {c.lower() for c in (categories or BIORXIV_DEFAULTS)}
    today = date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=days_back - 1)

    papers = []
    seen: set[str] = set()
    cursor = 0
    while len(papers) < max_results:
        url = f"https://api.biorxiv.org/details/biorxiv/{start}/{end}/{cursor}"
        try:
            resp = httpx.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("bioRxiv API error at cursor %d: %s", cursor, e)
            break

        collection = data.get("collection", [])
        if not collection:
            break

        for entry in collection:
            if entry.get("category", "").lower() not in cats:
                continue
            key = entry.get("title", "").lower().strip()
            if key in seen:
                continue
            seen.add(key)

            papers.append(paper_from_biorxiv_entry(entry))
            if len(papers) >= max_results:
                break

        messages = data.get("messages", [{}])
        total = int(messages[0].get("total", 0)) if messages else 0
        cursor += 100
        if cursor >= total:
            break

    return papers
