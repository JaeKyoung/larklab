"""Recommendation pipeline: crawl preprint servers, score against the library, rank.

Pure orchestration like the digest pipeline, so a future bot can reuse it.
"""

import logging
from collections import Counter, defaultdict
from datetime import date, datetime

from larklab.library.repository import PaperRepository
from larklab.library.similarity import find_similar_references
from larklab.models import CrawlResult, Paper, Recommendation, RecommendationResult
from larklab.sources.papers import arxiv_source, biorxiv_source
from larklab.utils.text import normalize_title

logger = logging.getLogger(__name__)

_CRAWLERS = {"arxiv": arxiv_source, "biorxiv": biorxiv_source}
RECOMMEND_SOURCES = tuple(_CRAWLERS)


def recommend_papers(
    repository: PaperRepository,
    *,
    sources: list[str],
    categories: list[str] | None,
    days_back: int,
    top_n: int,
    threshold: float,
    since: dict[str, datetime] | None = None,
) -> RecommendationResult:
    """Crawl `sources`, drop papers already in the library, and return the
    `top_n` most similar to the library with similarity ≥ `threshold`.

    `since` maps a source to the newest paper time already handled; each source
    resumes after it (see `crawl_progress`). The result's `newest_published`
    is what to save once the recommendations were delivered; a source that could
    not be read completely is left out so its papers are fetched again.
    """
    crawled_by_source = _crawl(sources, categories, days_back, since or {})
    crawled = [paper for crawl in crawled_by_source.values() for paper in crawl.papers]
    newest_published = _newest_published(crawled_by_source)

    def result(
        recommendations=(), candidate_counts=None, *, scored=True
    ) -> RecommendationResult:
        return RecommendationResult(
            recommendations=list(recommendations),
            candidate_counts=candidate_counts or {},
            # Papers that were never scored must come back next time, e.g. once
            # reference papers were added or the embeddings were rebuilt.
            newest_published=newest_published if scored else {},
        )

    if not crawled:
        logger.info("No papers found.")
        return result()
    if repository.count() == 0:
        logger.info("No reference papers in DB. Add papers with `db-add` first.")
        return result(scored=False)

    candidates = _exclude_library_papers(crawled, repository)
    if not candidates:
        logger.info("All crawled papers are already in your reference library.")
        return result()

    logger.info("Embedding %d papers...", len(candidates))
    scored = [
        Recommendation(paper=paper, similar_papers=similar)
        for paper, similar in zip(
            candidates, find_similar_references(candidates, repository), strict=True
        )
        if similar
    ]
    candidate_counts = _count_by_date_and_source(candidates)

    if not scored:
        logger.info(
            "No similarity scores found. Run `db-rebuild` to regenerate embeddings."
        )
        return result(candidate_counts=candidate_counts, scored=False)

    qualified = sorted(
        (rec for rec in scored if rec.score >= threshold),
        key=lambda rec: rec.score,
        reverse=True,
    )
    if not qualified:
        logger.info("No papers above threshold (%.2f).", threshold)
    return result(qualified[:top_n], candidate_counts)


def _crawl(
    sources: list[str],
    categories: list[str] | None,
    days_back: int,
    since: dict[str, datetime],
) -> dict[str, CrawlResult]:
    crawled: dict[str, CrawlResult] = {}
    for source in sources:
        crawler = _CRAWLERS[source]
        shown_categories = categories or crawler.DEFAULT_CATEGORIES
        logger.info("Crawling %s (%s)...", source, ", ".join(shown_categories))
        crawled[source] = crawler.crawl_recent(
            categories, days_back, since=since.get(source)
        )
        if not crawled[source].complete:
            logger.warning(
                "Could not read all of %s; its progress will not move, so the next "
                "run tries again.",
                source,
            )

    total = sum(len(crawl.papers) for crawl in crawled.values())
    if total:
        breakdown = ", ".join(f"{s}: {len(c.papers)}" for s, c in crawled.items())
        logger.info("Found %d papers (%s).", total, breakdown)
    return crawled


def _newest_published(crawled: dict[str, CrawlResult]) -> dict[str, datetime]:
    """Publication time of the newest crawled paper per source.

    Sources that returned nothing, or could not be read completely, are omitted.
    """
    return {
        source: max(p.published_at for p in crawl.papers if p.published_at)
        for source, crawl in crawled.items()
        if crawl.complete and any(p.published_at for p in crawl.papers)
    }


def _exclude_library_papers(
    papers: list[Paper], repository: PaperRepository
) -> list[Paper]:
    """Drop papers already in the library, matched by DOI or normalized title."""
    known_dois: set[str] = set()
    known_titles: set[str] = set()
    for known in repository.list_papers():
        if known.doi:
            known_dois.add(known.doi.lower())
        known_titles.add(normalize_title(known.title))
    return [
        paper
        for paper in papers
        if paper.doi.lower() not in known_dois
        and normalize_title(paper.title) not in known_titles
    ]


def _count_by_date_and_source(papers: list[Paper]) -> dict[date | None, dict[str, int]]:
    counts: dict[date | None, Counter[str]] = defaultdict(Counter)
    for paper in papers:
        counts[paper.published_date][paper.source] += 1
    return dict(counts)
