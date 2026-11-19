"""Recommendation pipeline: crawl the paper sources, score against the library, rank,
deliver, and remember how far each source was read.

Pure orchestration like the digest pipeline, so a future bot can reuse it.
"""

import logging
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from larklab.library.repository import PaperRepository
from larklab.library.similarity import find_similar_references
from larklab.models import (
    CrawlResult,
    Paper,
    Recommendation,
    RecommendationResult,
    SourceProgress,
)
from larklab.pipelines.crawl_progress import advance_progress, load_progress
from larklab.pipelines.outbox import load_outbox, merge_recommendations, save_outbox
from larklab.sources.papers import arxiv_source, biorxiv_source, pubmed_source
from larklab.utils.text import normalize_title

logger = logging.getLogger(__name__)

_CRAWLERS = {"arxiv": arxiv_source, "biorxiv": biorxiv_source, "pubmed": pubmed_source}
RECOMMEND_SOURCES = tuple(_CRAWLERS)
# arXiv can announce a paper after newer ones (one held for moderation), so each run
# reads this far back from where the last one stopped and skips what it has seen.
_OVERLAP = {"arxiv": timedelta(days=2)}

# Posts a result and returns the recommendations it could not post.
Send = Callable[[RecommendationResult], list[Recommendation]]


@dataclass
class RecommendationRun:
    shown: RecommendationResult  # the waiting recommendations plus the new ones
    undelivered: list[Recommendation]  # refused by `send`; already kept in the outbox


def run_recommendations(
    repository: PaperRepository,
    *,
    sources: list[str],
    categories: list[str] | None,
    days_back: int,
    top_n: int,
    threshold: float,
    progress_path: Path,
    outbox_path: Path,
    send: Send | None,
) -> RecommendationRun:
    """Read the sources, deliver the recommendations, and remember — in an order
    that loses nothing.

    Recommendations Slack refused earlier go out together with the new ones. What
    `send` could not post is saved to the outbox *before* the resume points move, so
    a crash can only cause a repeat, never a gap. `send=None` is a dry run: nothing
    is sent and nothing is saved.
    """
    result = recommend_papers(
        repository,
        sources=sources,
        categories=categories,
        days_back=days_back,
        top_n=top_n,
        threshold=threshold,
        progress=load_progress(progress_path),
    )
    waiting = _still_unknown(load_outbox(outbox_path), repository)
    shown = replace(
        result,
        recommendations=merge_recommendations(waiting, result.recommendations),
    )
    if send is None:
        return RecommendationRun(shown, [])

    undelivered = send(shown) if shown.recommendations else []
    save_outbox(outbox_path, undelivered)
    advance_progress(progress_path, result.progress)
    return RecommendationRun(shown, undelivered)


def _still_unknown(
    waiting: list[Recommendation], repository: PaperRepository
) -> list[Recommendation]:
    """The waiting recommendations of papers that are still not in the library: one
    may have been added since it was queued."""
    unknown = {
        id(paper)
        for paper in _exclude_library_papers([r.paper for r in waiting], repository)
    }
    return [r for r in waiting if id(r.paper) in unknown]


def recommend_papers(
    repository: PaperRepository,
    *,
    sources: list[str],
    categories: list[str] | None,
    days_back: int,
    top_n: int,
    threshold: float,
    progress: dict[str, SourceProgress] | None = None,
) -> RecommendationResult:
    """Crawl `sources`, drop papers already in the library, and return the
    `top_n` most similar to the library with similarity ≥ `threshold`.

    `progress` says how far each source was read (see `crawl_progress`); each source
    resumes there. The result's `progress` is what to save once the recommendations
    were delivered; a source that could not be read completely is left out so its
    papers are fetched again.
    """
    previous = progress or {}
    crawled_by_source = _crawl(sources, categories, days_back, previous)
    crawled = _one_per_paper(_not_seen(crawled_by_source, previous))
    next_progress = _next_progress(crawled_by_source, previous)

    def result(
        recommendations=(), candidate_counts=None, *, scored=True
    ) -> RecommendationResult:
        return RecommendationResult(
            recommendations=list(recommendations),
            candidate_counts=candidate_counts or {},
            # Papers that were never scored must come back next time, e.g. once
            # reference papers were added or the embeddings were rebuilt.
            progress=next_progress if scored else {},
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
    previous: dict[str, SourceProgress],
) -> dict[str, CrawlResult]:
    names = list(dict.fromkeys(sources))  # a source named twice is read once
    # Different servers: read them together, the slowest one sets the time.
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures = {
            name: pool.submit(
                _crawl_one, name, categories, days_back, previous.get(name)
            )
            for name in names
        }
        crawled = {name: future.result() for name, future in futures.items()}

    total = sum(len(crawl.papers) for crawl in crawled.values())
    if total:
        breakdown = ", ".join(f"{s}: {len(c.papers)}" for s, c in crawled.items())
        logger.info("Found %d papers (%s).", total, breakdown)
    return crawled


def _crawl_one(
    source: str,
    categories: list[str] | None,
    days_back: int,
    previous: SourceProgress | None,
) -> CrawlResult:
    crawler = _CRAWLERS[source]
    shown_categories = categories or crawler.DEFAULT_CATEGORIES
    logger.info(
        "Crawling %s (%s)...", source, ", ".join(shown_categories) or "everything"
    )
    since = previous.newest - _OVERLAP.get(source, timedelta()) if previous else None
    crawl = crawler.crawl_recent(categories, days_back, since=since)
    for paper in crawl.papers:
        paper.source = paper.source or source  # PubMed names the journal too
    if not crawl.complete:
        logger.warning(
            "Could not read all of %s; its progress will not move, so the next "
            "run tries again.",
            source,
        )
    return crawl


def _not_seen(
    crawled: dict[str, CrawlResult], previous: dict[str, SourceProgress]
) -> list[Paper]:
    """The crawled papers an earlier run has not handled yet."""
    papers = []
    for source, crawl in crawled.items():
        seen = previous[source].seen if source in previous else {}
        papers += [paper for paper in crawl.papers if paper.doi.lower() not in seen]
    return papers


def _next_progress(
    crawled: dict[str, CrawlResult], previous: dict[str, SourceProgress]
) -> dict[str, SourceProgress]:
    """What to save once the recommendations were delivered: per source the time of
    the newest paper crawled and, for sources that are read again from a little way
    back, the papers of that stretch. A source that returned nothing, or could not be
    read completely, is left out so it is read again from the old point."""
    updates = {}
    for source, crawl in crawled.items():
        dated = [paper for paper in crawl.papers if paper.published_at]
        if not (crawl.complete and dated):
            continue
        newest = max(paper.published_at for paper in dated)
        seen: dict[str, datetime] = {}
        if source in _OVERLAP:
            from_here = newest - _OVERLAP[source]
            before = previous[source].seen if source in previous else {}
            seen = {doi: at for doi, at in before.items() if at > from_here}
            seen |= {
                paper.doi.lower(): paper.published_at
                for paper in dated
                if paper.published_at > from_here
            }
        updates[source] = SourceProgress(newest, seen)
    return updates


def _one_per_paper(papers: list[Paper]) -> list[Paper]:
    """Two sources can return the same paper (PubMed indexes bioRxiv preprints):
    keep the first, so it is scored, counted and labelled once."""
    unique: dict[str, Paper] = {}
    for paper in papers:
        unique.setdefault(paper.doi.lower() or normalize_title(paper.title), paper)
    return list(unique.values())


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
