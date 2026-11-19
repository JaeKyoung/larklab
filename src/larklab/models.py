"""Data models passed between sources, processing, library, pipelines, outputs."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Self

SimilarPapers = list[tuple[str, float]]  # [(reference title, similarity score)]
_METADATA_FIELDS = ("title", "authors", "journal", "abstract")
# PubMed papers name their journal in the source (`pubmed:Chem Sci`): one source per
# journal, so the recommendation headline lists only those that have a recommendation.
JOURNAL_SOURCE_PREFIX = "pubmed:"


@dataclass
class ScholarPaper:
    """Paper parsed from a Google Scholar alert email (transient, digest only)."""

    title: str
    authors: list[str]
    journal: str
    abstract: str
    url: str
    source_email_id: str
    received_at: datetime | None
    summary: str = ""
    doi: str | None = None
    similar_papers: SimilarPapers | None = None


@dataclass
class Paper:
    """Paper from a metadata source or the reference DB. DOI is required to store."""

    title: str
    authors: list[str]
    journal: str
    abstract: str
    doi: str
    id: int | None = None
    embedding: list[float] | None = None
    published_at: datetime | None = None
    source: str = ""  # who found it: arxiv, biorxiv or pubmed:<journal>

    @classmethod
    def empty(cls, doi: str = "") -> Self:
        """Placeholder returned when no source knows the paper."""
        return cls(title="", authors=[], journal="", abstract="", doi=doi)

    @property
    def url(self) -> str:
        return f"https://doi.org/{self.doi}"

    def missing_metadata(self) -> list[str]:
        """Names of the metadata fields (title, authors, journal, abstract) that are
        still empty; the DOI is not one of them."""
        return [name for name in _METADATA_FIELDS if not getattr(self, name)]

    @property
    def published_date(self) -> date | None:
        return self.published_at.date() if self.published_at else None


@dataclass
class CrawlResult:
    """Papers a source returned, and how much of it was read."""

    papers: list[Paper]
    complete: bool = True  # False: part of the source failed, so don't mark it as seen
    # Set by a source that reads in order, one day at a time (PubMed): everything up
    # to this moment was read, even when `complete` is False, so the next run resumes
    # right after it. Without it the resume point is the newest paper of a complete
    # crawl. It says how far the source was read; `Paper.published_at` only says
    # when a paper appeared.
    read_until: datetime | None = None


@dataclass
class Recommendation:
    """A crawled paper scored against the reference library."""

    paper: Paper
    similar_papers: SimilarPapers  # closest reference papers, best first

    @property
    def score(self) -> float:
        """Similarity to the closest reference paper."""
        return self.similar_papers[0][1]


@dataclass
class SourceProgress:
    """How far one source has been read; saved between runs."""

    newest: datetime  # time of the newest paper already handled: the resume point
    # DOI -> paper time, for the stretch the next run reads again. A source that can
    # announce a paper after newer ones (arXiv) is read a little further back each
    # time, and these papers must not be recommended twice.
    seen: dict[str, datetime] = field(default_factory=dict)


@dataclass
class RecommendationResult:
    recommendations: list[Recommendation]
    # publication date -> source -> number of candidates scored (before thresholding)
    candidate_counts: dict[date | None, dict[str, int]]
    # progress key (the source, plus the categories read when they are not the
    # default) -> what to save once the recommendations were delivered
    progress: dict[str, SourceProgress] = field(default_factory=dict)

    def by_date(self) -> dict[date | None, list[Recommendation]]:
        """Recommendations grouped by publication date, newest date first."""
        grouped: dict[date | None, list[Recommendation]] = defaultdict(list)
        for recommendation in self.recommendations:
            grouped[recommendation.paper.published_date].append(recommendation)
        return dict(
            sorted(grouped.items(), key=lambda item: item[0] or date.min, reverse=True)
        )

    def source_counts(self, published: date | None) -> list[tuple[str, int, int]]:
        """(source, recommended, candidates) for one publication date."""
        recommended = Counter(
            r.paper.source
            for r in self.recommendations
            if r.paper.published_date == published
        )
        # Recommendations that were waiting from an earlier run have no crawl count:
        # never show "5/3".
        totals = dict(self.candidate_counts.get(published, {}))
        for source, count in recommended.items():
            totals[source] = max(totals.get(source, 0), count)
        return [
            (source, recommended[source], total)
            for source, total in totals.items()
            if recommended[source] or not source.startswith(JOURNAL_SOURCE_PREFIX)
        ]


@dataclass
class DailyDigest:
    date: date
    papers: list[ScholarPaper] = field(default_factory=list)
